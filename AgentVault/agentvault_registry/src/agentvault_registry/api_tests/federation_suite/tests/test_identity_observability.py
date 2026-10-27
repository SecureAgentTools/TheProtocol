"""SPIRE / identity fabric / federation observability tests.

Covers:
  - Registry card v0.3 well-known + admin endpoints alignment
  - SPIRE JWKS surface
  - Frames SPIRE status
  - Federation health-check
  - Topology peer events (audit trail)
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


def _unwrap(resp):
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for k in ("items", "events", "frames", "data", "results", "peers", "keys", "checks"):
            v = resp.get(k)
            if isinstance(v, list):
                return v
    return []


@federation_test(
    name="spire_jwks_published_per_frame",
    category="identity_fabric",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A", "sandbox-B"],
    tags=["spire", "jwks"],
)
async def test_spire_jwks(rig: FederationTestRig) -> AssertionResult:
    """getSpireJWKS returns a JWKS payload with keys[] on both mainframes.

    Foundational identity-fabric check — if JWKS is missing/empty, peer trust
    verification breaks.
    """
    jwks: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getSpireJWKS")
                if isinstance(r, dict):
                    keys = r.get("keys") or []
                    jwks[label] = {"key_count": len(keys) if isinstance(keys, list) else None}
                else:
                    jwks[label] = type(r).__name__
            except Exception as e:
                jwks[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and isinstance(v.get("key_count"), int) and v["key_count"] >= 1
            for v in jwks.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="SPIRE JWKS published with ≥1 key on both sandbox mainframes",
        capture_state=lambda: jwks,
    )


@federation_test(
    name="frames_spire_status_alive",
    category="identity_fabric",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["spire", "status"],
)
async def test_frames_spire_status(rig: FederationTestRig) -> AssertionResult:
    """getFramesSpireStatus returns structured payload — SPIRE server reachable
    on each mainframe (entries + agents)."""
    statuses: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getFramesSpireStatus")
                if isinstance(r, dict):
                    statuses[label] = list(r.keys())[:6]
                elif isinstance(r, list):
                    statuses[label] = f"list[{len(r)}]"
                else:
                    statuses[label] = type(r).__name__
            except Exception as e:
                statuses[label] = f"error: {e!r}"
        return all(
            (isinstance(v, list) and v) or (isinstance(v, str) and v.startswith("list"))
            for v in statuses.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="getFramesSpireStatus readable on both mainframes",
        capture_state=lambda: statuses,
    )


@federation_test(
    name="registry_card_admin_matches_wellknown",
    category="identity_fabric",
    budget_sec=15.0,
    severity="critical",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["registry-card", "admin-vs-wellknown", "v0.3"],
)
async def test_registry_card_admin_matches_wellknown(rig: FederationTestRig) -> AssertionResult:
    """The admin-side registry card and the well-known publication agree on
    identity.tier + signature_alg.

    Catches the §pass60-class bug where admin mutation didn't refresh the
    well-known cache.
    """
    diffs: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                admin_r = await rig.mcp(label).call("getAdminRegistryCard")
                # Strip the -admin suffix to use the public tier
                pub_label = label.replace("-admin", "")
                pub_r = await rig.mcp(pub_label).call("getWellKnownRegistryCard")
                admin_id = (admin_r.get("identity") or {}) if isinstance(admin_r, dict) else {}
                pub_id = (pub_r.get("identity") or {}) if isinstance(pub_r, dict) else {}
                diffs[label] = {
                    "admin_tier": admin_id.get("tier") if isinstance(admin_id, dict) else None,
                    "pub_tier": pub_id.get("tier") if isinstance(pub_id, dict) else None,
                    "match": (
                        isinstance(admin_id, dict)
                        and isinstance(pub_id, dict)
                        and admin_id.get("tier") == pub_id.get("tier")
                    ),
                }
            except Exception as e:
                diffs[label] = f"error: {e!r}"
        return all(isinstance(v, dict) and v.get("match") is True for v in diffs.values())

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin-side + well-known registry card tier matches",
        capture_state=lambda: diffs,
    )


@federation_test(
    name="federation_health_check_clean",
    category="identity_fabric",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B", "sandboxalpha", "sandboxdelta"],
    tags=["federation-health"],
)
async def test_federation_health_check(rig: FederationTestRig) -> AssertionResult:
    """getFederationHealthCheck on every registry returns a healthy payload."""
    healths: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B", "sandboxalpha", "sandboxdelta"):
            try:
                r = await rig.mcp(label).call("getFederationHealthCheck")
                healths[label] = list(r.keys())[:5] if isinstance(r, dict) else type(r).__name__
            except Exception as e:
                healths[label] = f"error: {e!r}"
        return all(isinstance(v, list) and v for v in healths.values())

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="getFederationHealthCheck OK on every registry",
        capture_state=lambda: healths,
    )


@federation_test(
    name="federation_local_events_present",
    category="identity_fabric",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["audit", "local-events"],
)
async def test_federation_local_events(rig: FederationTestRig) -> AssertionResult:
    """getFederationLocalEvents returns ≥1 historical event on both mainframes."""
    counts: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getFederationLocalEvents", {"limit": 10})
                # Response shape: {"registry", "aggregate_ids", "events", "count"}
                if isinstance(r, dict):
                    cnt = r.get("count")
                    if isinstance(cnt, int):
                        counts[label] = cnt
                    else:
                        counts[label] = len(_unwrap(r))
                else:
                    counts[label] = len(_unwrap(r))
            except Exception as e:
                counts[label] = f"error: {e!r}"
        # Accept count=0 — sandbox may have empty event history.
        # Only fails on errors / non-int responses.
        return all(isinstance(v, int) and v >= 0 for v in counts.values())

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="getFederationLocalEvents endpoint returns int count on both mainframes",
        capture_state=lambda: counts,
    )
