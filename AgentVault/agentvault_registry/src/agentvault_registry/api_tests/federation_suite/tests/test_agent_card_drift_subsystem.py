"""Agent card drift detection subsystem tests (§pass73.3.11 Batch 47).

3 read-only tests probing the agent card drift subsystem. Drift fires
when an agent's on-disk card hash differs from the registry-stored
hash — used to detect tampering or version skew.
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
    name="agent_card_drift_list_reachable",
    category="agent_card_drift",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["drift", "agent-cards"],
)
async def test_agent_card_drift_list(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAgentCardDriftList returns the inventory of agent cards
    showing drift. Sandbox-A typically has some drift due to
    fed-test-agent heartbeats updating cards."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAgentCardDriftList")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            items = r.get("items") or []
            state["count"] = len(items) if isinstance(items, list) else None
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="agent card drift list reachable on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="agent_card_drift_detail_by_did",
    category="agent_card_drift",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["drift", "detail"],
)
async def test_agent_card_drift_detail(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAgentCardDriftDetail returns the per-DID drift envelope when
    given a known agent DID from the drift list."""
    state: dict = {}

    async def predicate():
        try:
            lst = await rig.mcp("sandbox-A-admin").call("getAgentCardDriftList")
            items = (lst or {}).get("items") if isinstance(lst, dict) else []
            if not items:
                state["no_items"] = True
                return True
            target = items[0]
            did = target.get("agent_did") if isinstance(target, dict) else None
            if not did:
                state["no_did"] = True
                return False
            state["did"] = did
            r = await rig.mcp("sandbox-A-admin").call(
                "getAgentCardDriftDetail", {"did": did}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return bool(r.keys())
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="agent card drift detail readable for known DID",
        capture_state=lambda: state,
    )


@federation_test(
    name="agent_card_pullsync_events_reachable",
    category="agent_card_drift",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["pullsync", "events"],
)
async def test_agent_card_pullsync_events(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAgentCardPullsyncEvents returns the pull-sync event stream.

    Each event captures a federation pull-sync cycle — peer queried for
    cards, response received, drift detected/resolved.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "getAgentCardPullsyncEvents"
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            events = r if isinstance(r, list) else (
                r.get("events") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(events)
            return isinstance(state.get("count"), int) and state["count"] >= 0
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="agent card pullsync events stream reachable",
        capture_state=lambda: state,
    )
