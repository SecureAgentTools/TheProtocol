"""§ECHO-2 (2026-09-28): the federation suite waits for a card by READING THAT CARD, never a capped page of the feed.

Measured in the V0484 nightly (federation run 4dba8bdad0234627): `cross_cloud_op_transfer_delta_to_alpha` skipped with
"never reached sandbox-B within 360 s" for a card that was on sbx-beta 20 s after its birth. The wait read ONE page of
`GET /agent-cards/?limit=200&updated_since=now-30min`, oldest first; the daily digest read-repair walk had rewritten
~4,500 mirrors at 14:11Z, so the page ended at 14:11:19 and could never reach a 14:29 card. Pinned here: both helpers
read the card by DID, a 404 is "not yet", a failed read is never "no", and neither helper asks the feed.
RED control: the tree before this change fails every test here (no `_card_path`).
"""
from __future__ import annotations

import inspect
import types

import pytest

from agentvault_registry.api_tests.federation_suite.tests import test_operator_money_rails as m

DID = "did:theprotocol:sandbox-a.theprotocol.cloud:f7f81a27-17f7-41dc-9cc7-14af58c30fed"
ARRIVED = {"agent_did": DID, "is_active": True, "unlisted": False}


def _fake_rest(answers, calls):
    async def _rest(rig, method, path, label=None, **kw):
        calls.append((method, path, label))
        return answers.pop(0) if answers else (404, {"detail": "Agent Card not found"})
    return _rest


async def _no_wait(*a, **k):
    return None


@pytest.fixture
def quick(monkeypatch):
    """No 12 s sleeps and no nudges: only this module's `asyncio` name is replaced, never the real module."""
    monkeypatch.setattr(m, "asyncio", types.SimpleNamespace(sleep=_no_wait))
    monkeypatch.setattr(m, "_nudge", _no_wait)
    return monkeypatch


def test_the_card_is_read_by_did_keeping_its_colons():
    assert m._card_path(DID) == "/api/v1/agent-cards/" + DID
    assert m._card_path("did:x:a b") == "/api/v1/agent-cards/did:x:a%20b"


async def test_an_arrived_card_is_found_whatever_else_was_rewritten(quick):
    """404 is "not yet", a lost answer is attributed and waited through, and the card's own read ends the wait."""
    calls = []
    quick.setattr(m, "_rest", _fake_rest([(404, {}), (None, None), (200, dict(ARRIVED))], calls))
    state = {}
    assert await m._await_card_at(None, "sandbox-B", DID, state, budget_sec=60) is True
    assert state["card_wait_cycles"] == 3 and state["card_probe_last_status"] == 200
    assert {(meth, path, label) for meth, path, label in calls} == {("GET", m._card_path(DID), "sandbox-B-admin")}


async def test_an_inactive_card_has_not_arrived_and_the_budget_ends_false(quick):
    calls = []
    quick.setattr(m, "_rest", _fake_rest([(200, dict(ARRIVED, is_active=False))], calls))
    state = {}
    assert await m._await_card_at(None, "sandbox-B", DID, state, budget_sec=0.05) is False
    assert state["card_reached_gateway_after_sec"] is None
    assert state["card_probe_last_status"] == 404 and state["card_wait_cycles"] == len(calls) >= 2


@pytest.mark.parametrize("answer,expected", [
    ((404, {"detail": "Agent Card not found"}), False),
    ((200, dict(ARRIVED)), True),
    ((200, dict(ARRIVED, unlisted=True)), False),
    ((200, dict(ARRIVED, is_active=False)), False),
    ((500, {"detail": "boom"}), None),
    ((None, None), None),
    ((200, dict(ARRIVED, agent_did="did:theprotocol:someone-else")), None),
])
async def test_card_listed_keeps_its_three_states(quick, answer, expected):
    """True / False / None: a read that failed, or answered about another card, is never a "no"."""
    quick.setattr(m, "_rest", _fake_rest([answer], []))
    assert await m._card_listed(None, "sandbox-B", DID) is expected


def test_neither_helper_asks_the_feed():
    for fn in (m._await_card_at, m._card_listed):
        code = inspect.getsource(fn).split('"""')[-1]   # the body after the docstring
        assert "_card_path(did)" in code, f"{fn.__name__} stopped reading the card by DID"
        assert "agent-cards/?" not in code and "updated_since" not in code, f"{fn.__name__} reads a capped page again"
