"""§MCPSWEEP 2026-09-28: the fiat bad-signature row must see a new event even when the store is past the page size.

`events_fiat_bad_signature_is_evented` counted FiatProviderSignatureFailed events on a type-filtered page of 100
before and after its drive and required the count to rise. The type-filtered read returns the NEWEST 100, so once
the store holds 100 a new event pushes an old one off the page and the count stays at 100: on V0481 sbx-alpha held
101, the 101st landed during the run (07:46:47Z) and the row went red. The row now compares event ids. Driven here
through a fake rig with the module's own read and REST helpers replaced.
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.api_tests.federation_suite.rig import AssertionResult, FederationTestRig, PreconditionUnmet
from agentvault_registry.api_tests.federation_suite.tests import test_event_emission_matrix_2 as em2


def _ev(i):
    return {"id": f"ev-{i:04d}", "event_type": "FiatProviderSignatureFailed", "aggregate_id": f"sigfail-stripe-{i:04x}"}


class _Rig(FederationTestRig):
    async def assert_within(self, *, budget_sec, predicate, description, poll_interval_sec=1.0, capture_state=None):
        ok = await predicate()
        return AssertionResult(passed=bool(ok), description=description, budget_sec=budget_sec, elapsed_sec=0.0,
                               polling_attempts=1, last_state=capture_state() if capture_state else None)


def _run(monkeypatch, pages, webhook=(401, {"detail": "Webhook verification failed: missing Stripe-Signature header"})):
    calls = {"n": 0}

    async def events_of_type(rig, etype, limit=60, label=None):
        assert etype == "FiatProviderSignatureFailed" and limit == 100
        page = pages[min(calls["n"], len(pages) - 1)]
        calls["n"] += 1
        return page

    async def rest(rig, method, endpoint, *a, **kw):
        return webhook

    monkeypatch.setattr(em2, "_events_of_type", events_of_type)
    monkeypatch.setattr(em2, "_rest", rest)
    return asyncio.run(em2.test_fiat_bad_signature_is_evented(_Rig()))


SATURATED_BEFORE = [_ev(i) for i in range(100, 0, -1)]               # the newest 100 of a store holding more
SATURATED_AFTER = [_ev(101)] + SATURATED_BEFORE[:-1]                  # one new on top, the oldest pushed off


def test_a_new_event_past_the_page_size_is_seen(monkeypatch):
    r = _run(monkeypatch, [SATURATED_BEFORE, SATURATED_AFTER])
    assert r.passed, r.last_state
    assert r.last_state["sigfail_before"] == r.last_state["sigfail_after"] == 100   # the count alone cannot tell


def test_control_no_new_event_on_a_full_page_stays_red(monkeypatch):
    assert not _run(monkeypatch, [SATURATED_BEFORE, SATURATED_BEFORE]).passed


def test_control_below_the_page_size_a_new_event_is_seen(monkeypatch):
    small = [_ev(i) for i in range(5, 0, -1)]
    assert _run(monkeypatch, [small, [_ev(6)] + small]).passed


def test_an_accepted_unsigned_webhook_is_not_measured(monkeypatch):
    with pytest.raises(PreconditionUnmet):
        _run(monkeypatch, [SATURATED_BEFORE, SATURATED_AFTER], webhook=(200, {"ok": True}))


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
