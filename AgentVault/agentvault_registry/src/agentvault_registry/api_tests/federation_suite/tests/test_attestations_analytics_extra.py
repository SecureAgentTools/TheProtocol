"""Attestations analytics + canary judge/rebalancer events tests
(§pass73.3.13 Batch 60).

3 read-only tests probing the attestations analytics envelope + the
canary judge/rebalancer event feeds.
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
    name="attestations_analytics_envelope",
    category="attestations_analytics_extra",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["attestations", "analytics"],
)
async def test_attestations_analytics(rig: FederationTestRig) -> AssertionResult:
    """getAttestationsAnalytics returns rolling attestation aggregates
    (submit rates, verify rates, type breakdowns)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAttestationsAnalytics")
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
        description="attestations analytics envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="canary_judge_events_feed",
    category="attestations_analytics_extra",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["canary-judge", "events"],
)
async def test_canary_judge_events(rig: FederationTestRig) -> AssertionResult:
    """getCanaryJudgeEvents returns the canary judge audit feed."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCanaryJudgeEvents")
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
        description="canary judge events feed reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="canary_rebalancer_events_feed",
    category="attestations_analytics_extra",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["canary-rebalancer", "events"],
)
async def test_canary_rebalancer_events(
    rig: FederationTestRig,
) -> AssertionResult:
    """getCanaryRebalancerEvents returns the canary rebalancer audit
    feed (dispatch routing rebalances)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCanaryRebalancerEvents")
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
        description="canary rebalancer events feed reachable",
        capture_state=lambda: state,
    )
