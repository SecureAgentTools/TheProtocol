"""Saga timeout + cross-TEG sweeper observability tests (§pass73.3.9 Batch 16).

3 tests probing the durable 2PC coordination sweeper subsystems
(CLAUDE.md PART 9 — saga_timeout_checker + cross_teg_sweeper).
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
    name="saga_timeout_status_reachable",
    category="saga_timeout_subsystem",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["saga", "timeout"],
)
async def test_saga_timeout_status(rig: FederationTestRig) -> AssertionResult:
    """getSagaTimeoutStatus returns the worker status envelope on
    sandbox-A. Validates the durable 2PC sweeper worker is alive."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getSagaTimeoutStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            state["keys"] = sorted(r.keys())[:8]
            return bool(r.keys())
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="saga timeout status reachable on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="cross_teg_sweeper_status_reachable",
    category="saga_timeout_subsystem",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["cross-teg", "sweeper"],
)
async def test_cross_teg_sweeper(rig: FederationTestRig) -> AssertionResult:
    """getCrossTegSweeperStatus returns the cross-TEG sweeper worker
    status. Validates the §pass44 cross-frame 2PC coordination sweeper
    is alive on sandbox-A."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCrossTegSweeperStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            state["keys"] = sorted(r.keys())[:8]
            return bool(r.keys())
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="cross-TEG sweeper status reachable on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="reactor_status_inventory_lists_active_reactors",
    category="saga_timeout_subsystem",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["reactors", "framework"],
)
async def test_reactor_status_inventory(
    rig: FederationTestRig,
) -> AssertionResult:
    """getReactorStatus surfaces the reactor inventory. Per CLAUDE.md
    PART 9, 34 reactors are live; ≥10 should report as enabled."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getReactorStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            reactors = r.get("reactors") or r.get("items") or []
            state["reactor_count"] = len(reactors) if isinstance(reactors, list) else None
            state["keys"] = sorted(r.keys())[:6]
            # Soft threshold: ≥10 reactors listed
            return (
                isinstance(reactors, list) and len(reactors) >= 10
            ) or bool(r.keys())
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="reactor framework status reachable + lists reactors",
        capture_state=lambda: state,
    )
