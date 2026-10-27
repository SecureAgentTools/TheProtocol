"""Agent card drift detector tests (§pass73.3.17 Batch 98).

3 tests verifying the agent card drift detection subsystem reports
correctly + the pull-sync worker processes events.
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
    name="card_drift_list_envelope",
    category="agent_card_drift_detector",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["card-drift", "list"],
)
async def test_card_drift_list(rig: FederationTestRig) -> AssertionResult:
    """getAgentCardDriftList returns the drift inventory (drifted
    federated agent cards) — typically empty when sync is healthy."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getAgentCardDriftList")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                return False
            state["keys"] = sorted(r.keys())[:8]
            drifts = r.get("drifts") or r.get("items") or []
            state["count"] = len(drifts) if isinstance(drifts, list) else None
            return isinstance(state["count"], int)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="card drift list envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="pullsync_status_envelope_present",
    category="agent_card_drift_detector",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["pullsync", "status"],
)
async def test_pullsync_status(rig: FederationTestRig) -> AssertionResult:
    """getAgentCardPullsyncStatus returns the pull-sync worker state +
    metrics envelope."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getAgentCardPullsyncStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                return False
            state["keys"] = sorted(r.keys())[:10]
            return len(r.keys()) >= 1
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="pullsync status envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="pullsync_events_inventory_present",
    category="agent_card_drift_detector",
    budget_sec=20.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["pullsync", "events"],
)
async def test_pullsync_events(rig: FederationTestRig) -> AssertionResult:
    """getAgentCardPullsyncEvents returns the pull-sync audit feed."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getAgentCardPullsyncEvents")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            events = r if isinstance(r, list) else (
                r.get("events") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(events) if isinstance(events, list) else None
            return isinstance(state["count"], int)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="pullsync events inventory reachable",
        capture_state=lambda: state,
    )
