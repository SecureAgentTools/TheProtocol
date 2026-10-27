"""D6-056 (V0639): an achievement's payout goes only to one of the developer's own agents.

POST /achievements/record and /achievements/claim-pending paid the treasury's reward to whatever agent_did the request
named. Now claim-pending refuses (403) a DID that is not one of the caller's agents (Agent.creator_developer_id), and
record keeps recording but holds the payout pending when the DID is not the caller's own: the console records with the
agent selected at the top, which may be one the developer acts as and did not create (an organisation's), so a refusal
there would lose the achievement itself.
RED on V0638's router: the two stranger tests. The controls hold on both.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import importlib
import types

import pytest
from fastapi import HTTPException

ach = importlib.import_module("agentvault_registry.routers.achievements")
funding = importlib.import_module("agentvault_registry.services.reward_funding")

ME, OTHER = 7, 8
MINE, THEIRS = "did:theprotocol:sbx-alpha:mine-0001", "did:theprotocol:sbx-alpha:theirs-0001"
OWNERS = {MINE: ME, THEIRS: OTHER}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Result:
    def __init__(self, one=None, rows=()):
        self._one, self._rows = one, list(rows)

    def scalar_one_or_none(self):
        return self._one

    def first(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return types.SimpleNamespace(all=lambda: list(self._rows))


class _DB:
    """Answers the three selects the routes make by the table each one reads."""
    def __init__(self, pending=()):
        self.added, self.pending = [], list(pending)
        self.reward = types.SimpleNamespace(achievement_type="first_agent", achievement_name="First agent", enabled=True,
                                            payout_avt=5.0)

    async def execute(self, stmt):
        sql = str(stmt)
        if "FROM agents" in sql:
            did = stmt.compile().params.get("did_1")
            return _Result(rows=[(OWNERS[did],)] if did in OWNERS else [])
        if "FROM achievement_rewards" in sql:
            return _Result(one=self.reward)
        if "FROM developer_achievements" in sql:
            return _Result(one=None, rows=self.pending)
        raise AssertionError(f"an unexpected statement: {sql[:120]}")

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        for o in self.added:
            if getattr(o, "awarded_at", None) is None:
                o.awarded_at = dt.datetime.now(dt.timezone.utc)

    async def rollback(self):
        pass


@pytest.fixture
def paid(monkeypatch):
    calls = []

    async def _fund(db, *, target_agent_did, amount, reason, reference_id, idempotency_key):
        calls.append(target_agent_did)
        return {"status": "completed", "first_transaction_id": "tx-1", "legs": [], "funded_amount": amount}
    monkeypatch.setattr(funding, "fund_reward_via_waterfall", _fund)
    return calls


def _dev():
    return types.SimpleNamespace(id=ME)


def _record(did):
    return _run(ach.record_achievement(ach.RecordAchievementRequest(achievement_type="first_agent", agent_did=did),
                                       current_developer=_dev(), db=_DB()))


def test_a_record_naming_a_strangers_agent_records_and_holds_the_payout(paid):
    out = _record(THEIRS)
    assert out["status"] == "awarded" and out["achievement"]["payout_avt"] == 0.0
    assert paid == [] and "payout_held" in out


def test_a_claim_to_a_strangers_agent_is_refused(paid):
    with pytest.raises(HTTPException) as e:
        _run(ach.claim_pending_payouts(ach.ClaimPendingRequest(agent_did=THEIRS), current_developer=_dev(), db=_DB()))
    assert e.value.status_code == 403 and paid == []


def test_control_a_record_naming_my_agent_pays_it(paid):
    out = _record(MINE)
    assert out["status"] == "awarded" and paid == [MINE] and "payout_held" not in out


def test_control_a_record_naming_no_agent_stays_pending(paid):
    out = _record(None)
    assert out["status"] == "awarded" and paid == [] and "payout_held" not in out


def test_control_a_claim_to_my_agent_passes_the_owner_check(paid):
    out = _run(ach.claim_pending_payouts(ach.ClaimPendingRequest(agent_did=MINE), current_developer=_dev(), db=_DB()))
    assert out["status"] == "no_pending"
