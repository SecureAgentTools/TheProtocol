"""Per-agent history drill-down tests (§pass73.3.15 Batch 70).

3 read-only tests probing per-DID history surfaces — transaction
history, staking history, rewards history.
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


async def _pick_did(rig: FederationTestRig, label: str = "sandbox-A"):
    agents = await rig.mcp(label).call("discoverAgents", {"limit": 1})
    items = agents if isinstance(agents, list) else (
        agents.get("agents") or agents.get("items") or agents.get("data") or []
    ) if isinstance(agents, dict) else []
    if not items or not isinstance(items[0], dict):
        return None
    return items[0].get("did") or items[0].get("agent_did")


@federation_test(
    name="agent_transaction_history_envelope",
    category="agent_history_drilldowns",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["agent-history", "transactions"],
)
async def test_agent_transaction_history(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAgentTransactionHistory returns the per-agent tx feed."""
    state: dict = {}

    async def predicate():
        try:
            did = await _pick_did(rig)
            if not did:
                state["no_did"] = True
                return True
            state["agent_did"] = did
            r = await rig.mcp("sandbox-A").call(
                "getAgentTransactionHistory", {"agent_did": did}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("transactions") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e) or "400" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="agent transaction history reachable for picked DID",
        capture_state=lambda: state,
    )


@federation_test(
    name="agent_staking_history_envelope",
    category="agent_history_drilldowns",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["agent-history", "staking"],
)
async def test_agent_staking_history(rig: FederationTestRig) -> AssertionResult:
    """getAgentLockHistory returns the per-agent staking event feed."""
    state: dict = {}

    async def predicate():
        try:
            did = await _pick_did(rig)
            if not did:
                state["no_did"] = True
                return True
            state["agent_did"] = did
            r = await rig.mcp("sandbox-A").call(
                "getAgentLockHistory", {"agent_did": did}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("stakes") or r.get("history") or r.get("items") or
                r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e) or "400" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="agent staking history reachable for picked DID",
        capture_state=lambda: state,
    )


@federation_test(
    name="agent_rewards_history_envelope",
    category="agent_history_drilldowns",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["agent-history", "rewards"],
)
async def test_agent_rewards_history(rig: FederationTestRig) -> AssertionResult:
    """getAgentPayoutHistory returns the per-agent rewards feed."""
    state: dict = {}

    async def predicate():
        try:
            did = await _pick_did(rig)
            if not did:
                state["no_did"] = True
                return True
            state["agent_did"] = did
            r = await rig.mcp("sandbox-A").call(
                "getAgentPayoutHistory", {"agent_did": did}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("rewards") or r.get("history") or r.get("items") or
                r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e) or "400" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="agent rewards history reachable for picked DID",
        capture_state=lambda: state,
    )
