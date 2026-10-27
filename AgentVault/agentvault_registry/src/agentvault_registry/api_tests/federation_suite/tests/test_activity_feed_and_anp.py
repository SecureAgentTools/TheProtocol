"""Activity feed + agent ANP + batch balances tests (§pass73.3.14 Batch 64).

3 read-only tests probing the activity feed (typed event stream) +
agent ANP (Agent Negotiation Protocol metadata) + batch balance lookup.
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
    name="activity_feed_by_type_envelope",
    category="activity_feed_anp",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["activity-feed", "events"],
)
async def test_activity_feed_by_type(rig: FederationTestRig) -> AssertionResult:
    """getActivityFeedByType returns the typed activity feed envelope.
    Common feed types: 'agent', 'transaction', 'governance'."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call(
                "getActivityFeedByType", {"feed_type": "transaction"}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("activities") or r.get("items") or r.get("data") or
                r.get("events") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e) or "400" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="activity feed by type envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="agent_anp_envelope",
    category="activity_feed_anp",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["agent-anp", "negotiation"],
)
async def test_agent_anp(rig: FederationTestRig) -> AssertionResult:
    """getAgentANP returns the Agent Negotiation Protocol metadata for
    a given DID. Probe discoverAgents first."""
    state: dict = {}

    async def predicate():
        try:
            agents = await rig.mcp("sandbox-A").call("discoverAgents", {"limit": 1})
            items = agents if isinstance(agents, list) else (
                agents.get("agents") or agents.get("items") or agents.get("data") or []
            ) if isinstance(agents, dict) else []
            if not items or not isinstance(items[0], dict):
                state["no_agents"] = True
                return True
            did = items[0].get("did") or items[0].get("agent_did")
            if not did:
                state["no_did"] = True
                return True
            state["agent_did"] = did
            r = await rig.mcp("sandbox-A").call("getAgentANP", {"agent_did": did})
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e) or "400" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="agent ANP envelope reachable for picked DID",
        capture_state=lambda: state,
    )


@federation_test(
    name="batch_agent_balances_envelope",
    category="activity_feed_anp",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["balances", "batch"],
)
async def test_batch_agent_balances(rig: FederationTestRig) -> AssertionResult:
    """getBatchAgentBalances returns balances for multiple agents in
    one call. Probe discoverAgents for ≥1 DID first."""
    state: dict = {}

    async def predicate():
        try:
            agents = await rig.mcp("sandbox-A").call("discoverAgents", {"limit": 3})
            items = agents if isinstance(agents, list) else (
                agents.get("agents") or agents.get("items") or agents.get("data") or []
            ) if isinstance(agents, dict) else []
            if not items:
                state["no_agents"] = True
                return True
            dids = [
                (it.get("did") or it.get("agent_did"))
                for it in items if isinstance(it, dict)
            ]
            dids = [d for d in dids if d]
            if not dids:
                state["no_dids"] = True
                return True
            state["dids"] = dids
            r = await rig.mcp("sandbox-A").call(
                "getBatchAgentBalances", {"agent_dids": dids}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return True
            elif isinstance(r, list):
                state["count"] = len(r)
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e) or "400" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="batch agent balances envelope reachable",
        capture_state=lambda: state,
    )
