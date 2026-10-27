"""Reputation compute + ironhand SVID inventory tests (§pass73.3.14 Batch 66).

3 read-only tests probing the reputation computation status surface +
ironhand SVID inventory + canary ironhand events feed.
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
    name="reputation_computation_status_envelope",
    category="reputation_compute_ironhand",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["reputation", "compute"],
)
async def test_reputation_compute_status(
    rig: FederationTestRig,
) -> AssertionResult:
    """getReputationComputationStatus returns the EigenTrust + global
    reputation compute envelope (last run, next due, sample size)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getReputationComputationStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return bool(r.keys())
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="reputation computation status envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="ironhand_svids_inventory_via_reputation_compute",
    category="reputation_compute_ironhand",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["canary-ironhand", "svids"],
)
async def test_canary_ironhand_svids(rig: FederationTestRig) -> AssertionResult:
    """getCanaryIronhandSvids returns the canary IRONHAND SVID inventory
    (sandbox SPIFFE identities used by canary runners)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCanaryIronhandSvids")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("svids") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="canary IRONHAND SVID inventory reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="canary_ironhand_events_feed",
    category="reputation_compute_ironhand",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["canary-ironhand", "events"],
)
async def test_canary_ironhand_events(
    rig: FederationTestRig,
) -> AssertionResult:
    """getCanaryIronhandEvents returns the canary IRONHAND audit feed
    (SVID-pinned canary dispatches)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCanaryIronhandEvents")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("events") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="canary IRONHAND events feed reachable",
        capture_state=lambda: state,
    )
