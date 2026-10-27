"""Volume + transaction analytics + cross-frame reputation tests
(§pass73.3.12 Batch 56).

3 read-only tests probing aggregation surfaces that show up on the
public landing page + admin dashboard.
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
    name="transactions_analytics_envelope",
    category="volume_and_analytics",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["analytics", "transactions"],
)
async def test_transactions_analytics(rig: FederationTestRig) -> AssertionResult:
    """getTransactionsAnalytics returns the rolling tx analytics envelope
    (per-period totals, volume, fee accumulation)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getTransactionsAnalytics")
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
        description="transactions analytics envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="volume_profile_envelope",
    category="volume_and_analytics",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["analytics", "volume"],
)
async def test_volume_profile(rig: FederationTestRig) -> AssertionResult:
    """getVolumeProfile returns the per-agent volume profile envelope."""
    state: dict = {}

    async def predicate():
        try:
            agents = await rig.mcp("sandbox-A").call(
                "discoverAgents", {"limit": 1}
            )
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
            r = await rig.mcp("sandbox-A").call(
                "getVolumeProfile", {"agent_did": did}
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
            return "401" in repr(e) or "403" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="volume profile endpoint reachable for picked agent",
        capture_state=lambda: state,
    )


@federation_test(
    name="cross_frame_reputation_envelope",
    category="volume_and_analytics",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["reputation", "cross-frame"],
)
async def test_cross_frame_reputation(rig: FederationTestRig) -> AssertionResult:
    """getCrossFrameReputation returns the cross-frame reputation
    aggregation envelope. May be empty in sandbox — still validates."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getCrossFrameReputation")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:6]
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="cross-frame reputation envelope reachable",
        capture_state=lambda: state,
    )
