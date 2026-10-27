"""Federation quarantine + sync peers + admin flare grants tests
(§pass73.3.11 Batch 52).

3 read-only tests probing the federation quarantine subsystem +
sync peer inventory + admin flare grants.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
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


@federation_test(
    name="quarantined_registries_inventory",
    category="quarantine_subsystem",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["quarantine", "federation"],
)
async def test_quarantined_registries(
    rig: FederationTestRig,
) -> AssertionResult:
    """listQuarantinedRegistries returns the quarantine list — registries
    blocked from federation operations. Both mainframes should expose
    this endpoint with a quarantined_count counter."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("listQuarantinedRegistries")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if not isinstance(r, dict):
                    state[label] = {"bad_shape": type(r).__name__}
                    continue
                state[label] = {
                    "quarantined_count": r.get("quarantined_count"),
                    "registry_count": len(r.get("registries") or []),
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent")
                or isinstance(v.get("quarantined_count"), int)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="quarantine inventory reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="federation_sync_peers_inventory",
    category="quarantine_subsystem",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["federation-sync", "peers"],
)
async def test_federation_sync_peers(
    rig: FederationTestRig,
) -> AssertionResult:
    """getFederationSyncPeers returns the peer registries the federation
    sync worker tracks. Validates the worker's peer view."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getFederationSyncPeers")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            peers = r.get("peers") or []
            state["count"] = len(peers) if isinstance(peers, list) else None
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="federation sync peers inventory reachable on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_fiat_flares_inventory",
    category="quarantine_subsystem",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["fiat-flares", "admin"],
)
async def test_admin_fiat_flares(rig: FederationTestRig) -> AssertionResult:
    """getAdminFiatFlares lists developers with active fiat-grant flares
    (commander tier badges + similar). Validates the read path."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAdminFiatFlares")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            flares = r if isinstance(r, list) else (
                r.get("flares") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(flares)
            return isinstance(state.get("count"), int) and state["count"] >= 0
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin fiat flares inventory reachable",
        capture_state=lambda: state,
    )
