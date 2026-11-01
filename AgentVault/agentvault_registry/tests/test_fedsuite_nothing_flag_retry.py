"""§MCPTEST30 (V0652, agentvault2-d3, 2026-11-01): a nothing flag belongs to the attempt that set it.

V0651's pair proof (nt261101x1) failed on one federation "hard": operator_application_admin_approve set `no_app_id` and
returned False on its first attempt, found the application on its second and passed, and its state, one dict for every
attempt, still carried the flag, so the census read "passed on nothing". rig.assert_within now clears the earlier
attempt's nothing flags before each retry (decorator.clear_nothing_flags). RED before this change: the first test reads
['no_app_id'] on a pass that measured the application.
"""
from __future__ import annotations

import asyncio
import warnings

from agentvault_registry.api_tests.federation_suite.decorator import clear_nothing_flags, measured_nothing
from agentvault_registry.api_tests.federation_suite.rig import FederationTestRig


def _assert_within(predicate, capture_state):
    rig = object.__new__(FederationTestRig)        # assert_within reads nothing of the rig
    return asyncio.run(rig.assert_within(budget_sec=5.0, predicate=predicate, description="t",
                                         poll_interval_sec=0.01, capture_state=capture_state))


def test_a_flag_an_earlier_attempt_set_is_gone_from_a_later_pass():
    state: dict = {}
    calls = {"n": 0}

    async def predicate():
        calls["n"] += 1
        if calls["n"] == 1:
            state["no_app_id"] = True
            return False
        state["app_id"] = "op-app-1"
        return True

    res = _assert_within(predicate, lambda: state)
    assert res.passed and res.polling_attempts == 2
    assert measured_nothing(res.last_state) == [] and res.last_state == {"app_id": "op-app-1"}


def test_a_last_attempt_that_passes_on_nothing_stays_flagged():
    state: dict = {}
    calls = {"n": 0}

    async def predicate():
        calls["n"] += 1
        if calls["n"] == 1:
            return False
        state["no_agents"] = True
        return True

    res = _assert_within(predicate, lambda: state)
    assert res.passed and measured_nothing(res.last_state) == ["no_agents"]


def test_a_first_attempt_pass_on_nothing_is_untouched():
    state: dict = {}

    async def predicate():
        state["silent"] = True
        return True

    res = _assert_within(predicate, lambda: state)
    assert res.passed and res.polling_attempts == 1 and measured_nothing(res.last_state) == ["silent"]


def test_an_async_capture_is_a_snapshot_left_alone_and_never_left_unawaited():
    state: dict = {"no_peer": True}
    calls = {"n": 0}

    async def predicate():
        calls["n"] += 1
        return calls["n"] >= 2

    async def snapshot():
        return dict(state)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)          # "coroutine ... was never awaited" fails the test
        res = _assert_within(predicate, snapshot)
    assert res.passed and measured_nothing(res.last_state) == ["no_peer"]


def test_clear_nothing_flags_drops_only_the_flags():
    state = {"no_app_id": True, "silent": True, "app_id": "x", "no_count": 3, "empty_list": False, "why": "y"}
    assert clear_nothing_flags(state) == ["no_app_id", "silent"]
    assert state == {"app_id": "x", "no_count": 3, "empty_list": False, "why": "y"}
    assert clear_nothing_flags(None) == [] and clear_nothing_flags(["no_x"]) == []
