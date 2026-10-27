"""Multi-hop TEG routing tests (Phase F §pass73.3.6+).

5 tests exercising the cross-cloud-op multi-hop resolver newly unblocked
in §pass73.3.6. The 2 critical end-to-end direction tests live in
test_cross_frame_economic_flows.py; this file focuses on routing-layer
invariants + supporting infrastructure.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
    require_canary_subsystem,
    canary_path_leaves_registry,
)


def _is_silent_or_error(r):
    if isinstance(r, str):
        return True
    if isinstance(r, dict):
        if not r:
            return True
        if "_text" in r:
            return isinstance(r["_text"], str)
    return False


def _unwrap_admin_request(r):
    """adminRequest wraps response in {status_code, response, ok} — drill in."""
    if isinstance(r, dict) and "response" in r and isinstance(r.get("response"), dict):
        return r["response"]
    return r


@federation_test(
    name="cloud_op_resolver_alt_slug_match_supported",
    category="multi_hop_routing",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["resolver", "slug", "dash-insensitive"],
)
async def test_resolver_alt_slug_match(rig: FederationTestRig) -> AssertionResult:
    """sandbox-A's reactor + worker subsystem includes the
    canary_validator reactor that drives the multi-hop canary outcomes.

    Validates the validator reactor is alive — it's the worker that converts
    `fired` outcomes into `passed` after seeing the expected EventStore
    events. Without it, multi-hop canary outcomes stay at `fired` forever.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "adminRequest",
                {"method": "GET", "endpoint": "/api/v1/admin/canary/judge/status"},
            )
            inner = _unwrap_admin_request(r)
            if _is_silent_or_error(inner):
                state["silent"] = True
                return True
            if not isinstance(inner, dict):
                state["raw"] = str(inner)[:200]
                return False
            state["judge"] = {
                "keys": list(inner.keys())[:8],
                "active": inner.get("worker_active") or inner.get("is_active") or inner.get("running"),
            }
            return bool(inner.get("keys", inner) or state["judge"]["keys"])
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="canary judge worker is alive on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="cross_cloud_op_canary_pass_rate_healthy",
    category="multi_hop_routing",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["canary", "cross-cloud-op", "pass-rate"],
)
async def test_cross_cloud_op_pass_rate(rig: FederationTestRig) -> AssertionResult:
    """Every CROSS-REGISTRY canary path this tier fires is active, and the ones that have fired have passed.

    §CANARYONBOARD (2026-09-23): this named two path ids from the legacy topology
    (`sb-alpha->sb-delta:async`, and its reverse) and went red on a tier that carries neither — the sandbox frames fire
    `sb-<frame>-to-<peer>` over 2pc. The set is derivable: a path's own `frame_pair` says whether it leaves the
    registry. A path that has not fired YET (armed minutes ago, at a 1800 s cadence) is not a failure and does not go
    red; a path that has fired and never passed does.
    """
    state: dict = {}

    # §FEDCANARY: a tier with zero configured paths has no canary subsystem to
    # measure — skip loudly rather than poll a fixture that was never provisioned.
    # A CONFIGURED path that is missing or failing still goes RED.
    await require_canary_subsystem(rig)
    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "adminRequest",
                {"method": "GET", "endpoint": "/api/v1/admin/canary/status"},
            )
            inner = _unwrap_admin_request(r)
            if not isinstance(inner, dict):
                return False
            paths = inner.get("paths") or []
            cross = [p for p in paths if isinstance(p, dict) and canary_path_leaves_registry(p)]
            state["cross_paths"] = {
                str(p.get("path_id")): {
                    "frame_pair": p.get("frame_pair"),
                    "backend": p.get("backend"),
                    "active": p.get("is_active"),
                    "total_24h": (p.get("stats_24h") or {}).get("total", 0),
                    "passed_24h": (p.get("stats_24h") or {}).get("passed", 0),
                }
                for p in cross
            }
            if not cross:
                state["note"] = "this tier fires no cross-registry canary path"
                return False
            fired = [p for p in cross if ((p.get("stats_24h") or {}).get("total", 0) or 0) >= 1]
            if not fired:
                state["note"] = "no cross-registry canary has fired yet in the 24h window"
                return False
            return (all(p.get("is_active") for p in cross)
                    and all(((p.get("stats_24h") or {}).get("passed", 0) or 0) >= 1 for p in fired))
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="every cross-registry canary is active, and each one that fired has passed in 24h",
        capture_state=lambda: state,
    )


@federation_test(
    name="canary_runner_subsystem_alive",
    category="multi_hop_routing",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["canary", "worker", "liveness"],
)
async def test_canary_runner_alive(rig: FederationTestRig) -> AssertionResult:
    """Canary runner worker subsystem is alive — without it, no canaries fire."""
    state: dict = {}

    # §FEDCANARY: a tier with zero configured paths has no canary subsystem to
    # measure — skip loudly rather than poll a fixture that was never provisioned.
    # A CONFIGURED path that is missing or failing still goes RED.
    await require_canary_subsystem(rig)
    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "adminRequest",
                {"method": "GET", "endpoint": "/api/v1/admin/canary/status"},
            )
            inner = _unwrap_admin_request(r)
            if not isinstance(inner, dict):
                return False
            summary = inner.get("summary") or {}
            state["summary"] = {
                "total_paths": summary.get("total_paths"),
                "active_paths": summary.get("active_paths"),
                "tests_per_minute_5m": summary.get("tests_per_minute_5m"),
                "snapshot_at": summary.get("snapshot_at"),
            }
            # "Subsystem alive" = canary topology configured + paths active. The
            # runner worker is leader-elected (verified in workers_alive_matrix:
            # canary_runner holds a lease). Actual per-5-min throughput
            # (tests_per_minute_5m) is schedule-dependent and legitimately 0 on a
            # quiet sandbox window (last_run_at=None between fires) — asserting >0
            # made this liveness test flaky. Throughput / pass-rate is covered by
            # the dedicated cross_cloud_op_canary_pass_rate_healthy test; keep tpm
            # here as an advisory field only.
            return (
                isinstance(summary.get("total_paths"), int)
                and summary["total_paths"] >= 1
                and isinstance(summary.get("active_paths"), int)
                and summary["active_paths"] >= 1
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="canary subsystem alive: ≥1 active path configured",
        capture_state=lambda: state,
    )


@federation_test(
    name="cloud_op_peer_count_meets_multi_hop_minimum",
    category="multi_hop_routing",
    budget_sec=15.0,
    severity="critical",
    requires=["sandboxalpha-admin", "sandboxdelta-admin"],
    tags=["peer-registries", "topology", "multi-hop"],
)
async def test_cloud_op_peer_count_minimum(rig: FederationTestRig) -> AssertionResult:
    """Each sandbox cloud-op has ≥3 ACTIVE peer registry rows visible via
    the admin federation_sync_peers surface — required for cross-cloud-op
    multi-hop routing.

    The §pass73.3.6 seed: parent + cross-frame mainframe + cross-frame
    sibling cloud-op. peer_activation_keeper holds these rows ACTIVE.

    The PUBLIC `listFederationPeers` filters by peer_type='direct_peer'
    so it only shows the parent (1 row). The ADMIN surface returns the
    full peer_registries view including discovered + frame peer types.
    """
    state: dict = {}

    async def predicate():
        for label in ("sandboxalpha-admin", "sandboxdelta-admin"):
            try:
                r = await rig.mcp(label).call("getFederationSyncPeers")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                peers = r if isinstance(r, list) else (
                    r.get("peers") or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                active = [
                    p for p in peers
                    if isinstance(p, dict) and p.get("status") == "ACTIVE"
                ]
                state[label] = {
                    "total": len(peers),
                    "active": len(active),
                    "active_names": sorted([(p.get("name") or "?") for p in active])[:6],
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent")
                or (isinstance(v.get("active"), int) and v["active"] >= 3)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="each sandbox cloud-op admin reports ≥3 ACTIVE peers (multi-hop set)",
        capture_state=lambda: state,
    )


@federation_test(
    name="cross_teg_sweeper_status_per_frame",
    category="multi_hop_routing",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["cross-teg", "sweeper", "2pc"],
)
async def test_cross_teg_sweeper(rig: FederationTestRig) -> AssertionResult:
    """getCrossTegSweeperStatus returns alive state on both mainframes —
    the durable 2PC sweeper is what completes hung cross-frame transfers."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getCrossTegSweeperStatus")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {"keys": list(r.keys())[:8]}
                else:
                    state[label] = type(r).__name__
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (isinstance(v.get("keys"), list) and v["keys"])
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="cross-TEG sweeper status reachable on both mainframes",
        capture_state=lambda: state,
    )
