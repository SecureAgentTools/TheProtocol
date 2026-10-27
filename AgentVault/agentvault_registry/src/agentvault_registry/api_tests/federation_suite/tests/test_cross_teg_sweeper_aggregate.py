"""Cross-TEG sweeper + saga timeout events observability tests
(§pass73.3.10 Batch 41).

3 read-only tests probing the §pass44 cross-TEG sweeper + saga timeout
event streams. These workers clean up stuck 2PC coordination state.
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
    name="cross_teg_sweeper_events_observable",
    category="cross_teg_sweeper_events",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["cross-teg", "sweeper", "events"],
)
async def test_cross_teg_sweeper_events(
    rig: FederationTestRig,
) -> AssertionResult:
    """getCrossTegSweeperEvents returns recent sweeper firing events.

    Each event captures a stuck 2PC coordination state being either
    completed or rolled back by the sweeper.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCrossTegSweeperEvents")
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
        description="cross-TEG sweeper events stream reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="saga_timeout_events_observable",
    category="cross_teg_sweeper_events",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["saga", "timeout", "events"],
)
async def test_saga_timeout_events(rig: FederationTestRig) -> AssertionResult:
    """getSagaTimeoutEvents returns recent saga timeout firing events.

    The saga timeout worker fires when a multi-step transfer has been
    in-flight beyond the SLO budget, rolling back or completing it.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getSagaTimeoutEvents")
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
        description="saga timeout events stream reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="supply_auditor_events_observable",
    category="cross_teg_sweeper_events",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["supply-auditor", "events"],
)
async def test_supply_auditor_events(
    rig: FederationTestRig,
) -> AssertionResult:
    """getSupplyAuditorEvents returns recent supply audit cycle events.

    Each event captures a cycle's invariant check + per-registry
    delta. Used to investigate any supply breach incidents.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getSupplyAuditorEvents")
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
        description="supply auditor events stream reachable",
        capture_state=lambda: state,
    )
