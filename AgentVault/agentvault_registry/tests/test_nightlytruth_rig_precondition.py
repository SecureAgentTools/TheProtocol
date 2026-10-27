"""§NIGHTLYTRUTH (2026-09-14) — a precondition unmet at the END of a budget is NOT MEASURED, not FAILED.

`FederationTestRig.assert_within` polls a predicate until it is True or the budget ends. It used to swallow
every exception the predicate raised, including `PreconditionUnmet`, and report "budget exhausted;
last_exception=PreconditionUnmet(...)" as a FAILED row. The decorator has a third state for an unmet
precondition ("skipped: precondition unmet"), reachable only when the exception escapes the loop, so a
row whose evidence was out of frame read as a defect every night (`fx_route_refund_claim_matches_the_money`).

The rule pinned here: the LAST attempt decides. Raised `PreconditionUnmet` at the end -> it escapes; raised
anything else -> FAILED with the exception named; returned False -> FAILED; and a precondition that becomes
met inside the budget still passes, because the loop keeps polling through it.
"""
from __future__ import annotations

import pytest

from agentvault_registry.api_tests.federation_suite.rig import FederationTestRig, PreconditionUnmet


def _rig() -> FederationTestRig:
    # assert_within reads nothing from the instance; bypass the constructor, which wants a tier
    return object.__new__(FederationTestRig)


async def test_a_precondition_unmet_on_the_last_attempt_escapes_the_budget():
    async def pred():
        raise PreconditionUnmet("the evidence is out of frame")

    with pytest.raises(PreconditionUnmet) as exc:
        await _rig().assert_within(budget_sec=0.25, predicate=pred, description="x", poll_interval_sec=0.05)
    assert "out of frame" in str(exc.value)


async def test_a_precondition_that_is_met_inside_the_budget_passes():
    calls = {"n": 0}

    async def pred():
        calls["n"] += 1
        if calls["n"] < 3:
            raise PreconditionUnmet("not yet")
        return True

    r = await _rig().assert_within(budget_sec=2.0, predicate=pred, description="x", poll_interval_sec=0.02)
    assert r.passed is True and r.polling_attempts == 3


async def test_any_other_exception_on_the_last_attempt_is_a_failure_that_names_it():
    async def pred():
        raise ValueError("the probe is wrong")

    r = await _rig().assert_within(budget_sec=0.2, predicate=pred, description="x", poll_interval_sec=0.05)
    assert r.passed is False
    assert "ValueError" in (r.failure_detail or "") and "the probe is wrong" in (r.failure_detail or "")


async def test_a_false_on_the_last_attempt_is_a_failure_even_after_an_earlier_unmet_precondition():
    calls = {"n": 0}

    async def pred():
        calls["n"] += 1
        if calls["n"] == 1:
            raise PreconditionUnmet("first attempt only")
        return False

    r = await _rig().assert_within(budget_sec=0.3, predicate=pred, description="x", poll_interval_sec=0.05)
    assert r.passed is False
    assert "budget" in (r.failure_detail or "")
