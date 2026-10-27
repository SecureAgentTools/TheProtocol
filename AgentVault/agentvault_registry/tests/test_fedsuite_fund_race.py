"""§MCPTEST30 (V0557): the event matrix's treasury funding tries once more after a pause when the refusal is the TEG's
funding race (two parallel suite funds sharing the fee collector, measured by agentvault2-33 on 2026-10-03), keeps the
first refusal in the row's evidence, and passes every other refusal through untouched (the control)."""
from __future__ import annotations

import pytest

from agentvault_registry.api_tests.federation_suite.rig import PreconditionUnmet
from agentvault_registry.api_tests.federation_suite.tests import test_event_emission_matrix_2 as M


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch):
    async def instant(_s):
        return None
    monkeypatch.setattr(M.asyncio, "sleep", instant)


def _must_answers(monkeypatch, answers):
    calls = []

    async def fake_must(rig, method, path, *, body=None, **kw):
        calls.append((method, path, body))
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    monkeypatch.setattr(M, "_must", fake_must)
    return calls


async def test_the_race_is_tried_once_more_and_kept_in_the_evidence(monkeypatch):
    race = PreconditionUnmet("POST /api/v1/teg/treasury/fund-agent → HTTP 400: Reward fund failed: Insufficient balance")
    calls = _must_answers(monkeypatch, [race, {"ok": True}])
    state = {}
    await M._fund(None, "did:theprotocol:x", "1000.0", state=state)
    assert len(calls) == 2 and calls[0] == calls[1]
    assert calls[0][2]["amount"] == "1000.0" and state["fund_race"][0].startswith("POST /api/v1/teg/treasury/fund-agent")


async def test_the_race_is_known_in_the_tegs_words_before_and_after_its_rewording(monkeypatch):
    for said in ("HTTP 400: Reward fund failed: Insufficient balance", "HTTP 400: Payout funding failed"):
        calls = _must_answers(monkeypatch, [PreconditionUnmet(said), {"ok": True}])
        await M._fund(None, "did:theprotocol:x", "1.0", state={})
        assert len(calls) == 2, said


async def test_a_race_twice_is_still_the_rows_refusal(monkeypatch):
    race = PreconditionUnmet("HTTP 400: Insufficient balance")
    _must_answers(monkeypatch, [race, PreconditionUnmet("HTTP 400: Insufficient balance")])
    with pytest.raises(PreconditionUnmet):
        await M._fund(None, "did:theprotocol:x", "50.0", state={})


async def test_any_other_refusal_passes_through_at_once(monkeypatch):
    calls = _must_answers(monkeypatch, [PreconditionUnmet("HTTP 403: admin flag missing")])
    state = {}
    with pytest.raises(PreconditionUnmet, match="403"):
        await M._fund(None, "did:theprotocol:x", "50.0", state=state)
    assert len(calls) == 1 and "fund_race" not in state
