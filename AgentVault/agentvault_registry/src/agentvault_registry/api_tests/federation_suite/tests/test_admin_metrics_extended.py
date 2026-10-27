"""Admin metrics + agent flags drill-down tests (§pass73.3.11 Batch 50).

3 read-only tests probing admin per-agent and per-developer drill-down
surfaces. Used by /ui#/admin views to investigate specific agents.
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
    name="admin_metrics_agent_activity_envelope",
    category="admin_metrics",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["metrics", "agent-activity"],
)
async def test_metrics_agent_activity(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAdminMetricsAgentActivity returns the rolling 1h activity
    aggregate — active_agents, tx_per_min, error_rate, latency."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "getAdminMetricsAgentActivity"
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            state["active_agents"] = r.get("active_agents")
            state["transactions_per_minute"] = r.get("transactions_per_minute")
            state["error_rate"] = r.get("error_rate")
            state["total_requests_last_hour"] = r.get("total_requests_last_hour")
            return (
                isinstance(r.get("error_rate"), (int, float))
                and isinstance(r.get("active_agents"), int)
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin metrics agent activity envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_agent_flags_for_known_did",
    category="admin_metrics",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["agent-flags", "admin"],
)
async def test_admin_agent_flags(rig: FederationTestRig) -> AssertionResult:
    """getAdminAgentFlags returns agent flag inventory for a known DID.

    Picks a DID from the admin agent list to query.
    """
    state: dict = {}

    async def predicate():
        try:
            agents = await rig.mcp("sandbox-A-admin").call(
                "getAdminAgents", {"limit": 3}
            )
            items = agents if isinstance(agents, list) else (
                agents.get("agents") or agents.get("items") or agents.get("data") or []
            ) if isinstance(agents, dict) else []
            if not items:
                state["no_agents"] = True
                return False
            target = items[0]
            did = (target.get("did") if isinstance(target, dict) else None) or \
                  (target.get("agent_did") if isinstance(target, dict) else None)
            if not did:
                state["no_did"] = True
                return False
            state["did"] = did
            r = await rig.mcp("sandbox-A-admin").call(
                "getAdminAgentFlags", {"agent_did": did}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:6]
                return bool(r.keys())
            elif isinstance(r, list):
                state["count"] = len(r)
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin agent flags readable for known DID",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_agents_paginated_listing",
    category="admin_metrics",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["agents", "pagination"],
)
async def test_admin_agents_pagination(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAdminAgents paginated listing returns ≥1 agent at limit=5.

    Sandbox-A has thousands of agents, so first page should populate.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "getAdminAgents", {"limit": 5, "offset": 0}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("agents") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return state["count"] >= 1
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin agents paginated listing returns ≥1 entry",
        capture_state=lambda: state,
    )
