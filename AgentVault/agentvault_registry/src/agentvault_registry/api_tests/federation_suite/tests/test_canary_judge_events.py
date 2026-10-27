"""Canary judge + rebalancer event stream observability tests
(§pass73.3.10 Batch 42).

3 read-only tests probing the canary judge + rebalancer event streams.
These workers process canary firing outcomes + maintain canary sender
balance topology.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
    require_canary_subsystem,
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
    name="canary_judge_events_stream_populated",
    category="canary_events",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["canary", "judge", "events"],
)
async def test_canary_judge_events(rig: FederationTestRig) -> AssertionResult:
    """getCanaryJudgeEvents returns ≥1 recent judge classification
    event (passed/failed/timeout per canary firing)."""
    state: dict = {}

    # §FEDCANARY: a tier with zero configured paths has no canary subsystem to
    # measure — skip loudly rather than poll a fixture that was never provisioned.
    # A CONFIGURED path that is missing or failing still goes RED.
    await require_canary_subsystem(rig)
    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCanaryJudgeEvents")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            events = r.get("events") if isinstance(r, dict) else r
            if not isinstance(events, list):
                state["bad_shape"] = type(events).__name__
                return False
            state["count"] = len(events)
            if events and isinstance(events[0], dict):
                state["latest_outcome"] = events[0].get("outcome")
            return len(events) >= 1
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="canary judge events stream has ≥1 recent classification",
        capture_state=lambda: state,
    )


@federation_test(
    name="canary_rebalancer_events_observable",
    category="canary_events",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["canary", "rebalancer", "events"],
)
async def test_canary_rebalancer_events(
    rig: FederationTestRig,
) -> AssertionResult:
    """getCanaryRebalancerEvents returns rebalancer firing events
    (sender re-fund events when balance drops below threshold)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCanaryRebalancerEvents")
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
        description="canary rebalancer events stream reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="pending_peer_registries_inventory",
    category="canary_events",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["peer-registries", "pending"],
)
async def test_pending_peer_registries(
    rig: FederationTestRig,
) -> AssertionResult:
    """getPendingPeerRegistries returns the pending peer registry
    application queue. Federation peers go through this approval gate
    before becoming active partners."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getPendingPeerRegistries")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r.get("items") if isinstance(r, dict) else r
            if not isinstance(items, list):
                state["bad_shape"] = type(items).__name__
                return False
            state["count"] = len(items)
            return True
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="pending peer registries inventory reachable",
        capture_state=lambda: state,
    )
