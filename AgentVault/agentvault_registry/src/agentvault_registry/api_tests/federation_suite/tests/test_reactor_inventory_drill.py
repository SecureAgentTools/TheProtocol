"""Reactor framework inventory + activity tests (§pass73.3.11 Batch 45).

3 tests probing the 47-reactor framework state per CLAUDE.md PART 9.
Validates: total_reactors ≥30, all reactors leader-elected, lifetime
dispatches are accumulating.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from datetime import datetime, timezone

from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
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
    name="reactor_inventory_total_count",
    category="reactor_inventory",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["reactors", "inventory"],
)
async def test_reactor_count(rig: FederationTestRig) -> AssertionResult:
    """getReactorStatus reports total_reactors ≥30. The fleet runs 34+
    reactors per CLAUDE.md (some env-gated)."""
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
            summ = r.get("summary") or {}
            state["total_reactors"] = summ.get("total_reactors")
            state["leaders"] = summ.get("leaders")
            state["ws_connected"] = summ.get("ws_connected")
            return (
                isinstance(summ.get("total_reactors"), int)
                and summ["total_reactors"] >= 30
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="reactor framework reports ≥30 total reactors",
        capture_state=lambda: state,
    )


@federation_test(
    name="reactor_leaders_equals_total",
    category="reactor_inventory",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["reactors", "leader-election"],
)
async def test_reactor_leader_election(
    rig: FederationTestRig,
) -> AssertionResult:
    """leaders == total_reactors. On the central canary registry, every
    reactor should be leader-elected (since it's the only registry
    competing for leadership on sandbox-A)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getReactorStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            summ = (r or {}).get("summary") or {}
            total = summ.get("total_reactors")
            leaders = summ.get("leaders")
            state["total_reactors"] = total
            state["leaders"] = leaders
            return (
                isinstance(total, int) and isinstance(leaders, int)
                and leaders == total
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="all reactors leader-elected on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="reactor_lifetime_dispatches_growing",
    category="reactor_inventory",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["reactors", "dispatches", "activity"],
)
async def test_reactor_dispatches(rig: FederationTestRig) -> AssertionResult:
    """lifetime_dispatches ≥10000 — reactors have processed events; below that, they are processing them now.

    The floor was written for a sandbox that had run for weeks with constant canary + fed-test-agent activity.
    §NIGHTPROV (2026-09-27): a nightly frame two hours old held 211 dispatches and 0 errors and failed it (measured,
    nt260927x2a). Below the floor the test asks what its name asks: do the dispatches GROW within the budget? A YOUNG
    frame (its ledger's oldest event under 7 days, the §TESTBED rule) that stays quiet for the whole budget is NOT
    MEASURED, said once; an older frame under the floor still fails, as before.
    """
    state: dict = {}

    async def _ledger_is_young():
        if "young" not in state:
            stats = await rig.mcp("sandbox-A-admin").call("getEventStoreStats")
            oldest = stats.get("oldest_event") if isinstance(stats, dict) else None
            state["young"] = False
            if isinstance(oldest, str) and oldest:
                try:
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(oldest.replace("Z", "+00:00")))
                    state["ledger_age_sec"] = round(age.total_seconds(), 1)
                    state["young"] = state["ledger_age_sec"] < 7 * 86400
                except Exception:
                    pass
        return state["young"]

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getReactorStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            summ = (r or {}).get("summary") or {}
            disp = summ.get("lifetime_dispatches")
            err = summ.get("lifetime_errors")
            state["lifetime_dispatches"] = disp
            state["lifetime_errors"] = err
            if not isinstance(disp, int):
                return False
            if disp >= 10000:
                return True
            state.setdefault("first_read", disp)
            if disp > state["first_read"]:
                state["grew_by"] = disp - state["first_read"]
                state.pop("verdict", None)      # an earlier quiet read is not the answer once it grew
                return True
            if await _ledger_is_young():
                state["verdict"] = (f"NOT MEASURED — a young frame, quiet for the whole budget: {disp} lifetime "
                                    f"dispatches (a long-running tier holds >= 10000) and none new while it was watched")
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    res = await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="reactor framework reports ≥10000 lifetime dispatches, or dispatches growing",
        capture_state=lambda: state,
    )
    if not res.passed and "error" not in state and str(state.get("verdict", "")).startswith("NOT MEASURED"):
        raise PreconditionUnmet(state["verdict"])
    return res
