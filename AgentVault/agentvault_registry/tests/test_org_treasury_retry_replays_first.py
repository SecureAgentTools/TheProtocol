"""§DOCSFIX D6-497 (2026-10-16): a retried org treasury fund or remit replays its legs before any solvency question.

Both rails move units in two escrow legs whose keys derive from the caller's Idempotency-Key, so a retry replays the
debit leg it already ran and finishes (or replays) the credit. But they read the source's balance first and refused
with "insufficient ... balance" (409 at the route) when it held less than the amount: after a partial failure (the
debit ran, the credit did not) the source no longer held the amount, the retry was refused and the units stayed in the
escrow; and a retry of a finished request answered 409 instead of its result. The TEG is asked first now: it replays a
leg it already ran whatever the balance, and refuses a fresh debit the source cannot cover, which is answered with the
same sentence as before.

The mover below behaves as the TEG's /admin/exchange/move does: a completed key replays without a balance check, a
fresh debit beyond the balance is refused with 400 "Insufficient balance".

RED on the pre-change tree: the three retry tests and the mover outage. The controls are green before and after.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from agentvault_registry.services import exchange_service as xs
from agentvault_registry.services import org_treasury as ot
from agentvault_registry.services.idempotency import cache

ORG = "org-1"
TREASURY = "did:theprotocol:orgtreasury-acme"
AGENT = "did:theprotocol:eu.theprotocol.cloud:member-0000"
ESCROW = xs.EXCHANGE_ESCROW_SENTINEL


def _leg(kind, caller, key, leg):
    """D6-777: a move's leg key is its caller's (org_treasury.move_ref): the fund below is developer 5's, the remit
    AGENT's own."""
    return f"{ot.move_ref(kind, ORG, caller, key)}:{leg}"


FUND_IN = _leg("fund", cache.developer_caller(5), "k-1", "in")
FUND_OUT = _leg("fund", cache.developer_caller(5), "k-1", "out")
REMIT_IN = _leg("remit", cache.agent_caller(AGENT), "r-1", "in")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Mover:
    def __init__(self, balances, fail_once=()):
        self.bal = {k: Decimal(v) for k, v in balances.items()}
        self.done = {}
        self.fail_once = set(fail_once)

    async def agent_balance(self, did):
        return self.bal.get(did, Decimal("0"))

    async def move(self, src, dst, amount, reason, key, floor=None, timeout_s=35.0):
        if key in self.done:
            return dict(self.done[key], idempotent_replay=True)
        if key in self.fail_once:
            self.fail_once.discard(key)
            raise xs.MoverError(502, "exchange mover timeout: ReadTimeout")
        if src != ESCROW and self.bal.get(src, Decimal("0")) < amount:
            raise xs.MoverError(400, "exchange mover 400: exchange/move transfer failed: Insufficient balance")
        self.bal[src] = self.bal.get(src, Decimal("0")) - amount
        self.bal[dst] = self.bal.get(dst, Decimal("0")) + amount
        self.done[key] = {"transaction_id": f"tx-{len(self.done) + 1}", "status": "completed"}
        return self.done[key]


@pytest.fixture
def wired(monkeypatch):
    async def _own(db, org_id):
        return TREASURY

    async def _member(db, org_id, did):
        return None

    async def _cap(db, org_id, dev, amount):
        return None
    monkeypatch.setattr(ot, "_own_treasury_or_raise", _own)
    monkeypatch.setattr(ot, "_org_agent_or_raise", _member)
    monkeypatch.setattr(ot, "_procurement_cap_or_raise", _cap)
    monkeypatch.setattr(ot, "_emit_org_money_event", lambda *a, **k: None)

    def _use(mover):
        monkeypatch.setattr(xs, "mover", mover)
        return mover
    return _use


def _fund(key="k-1", amount="10"):
    return _run(ot.fund_agent_from_org(None, org_id=ORG, agent_did=AGENT, amount=amount, idempotency_key=key,
                                       actor_developer_id=5))


def _remit(key="r-1", amount="10"):
    return _run(ot.remit_agent_to_org(None, org_id=ORG, agent_did=AGENT, amount=amount, idempotency_key=key))


def test_a_fund_retried_after_its_credit_failed_finishes_the_move(wired):
    m = wired(_Mover({TREASURY: "10"}, fail_once={FUND_IN}))
    with pytest.raises(xs.MoverError):
        _fund()
    assert (m.bal[TREASURY], m.bal[ESCROW]) == (Decimal("0"), Decimal("10"))   # the debit ran, the credit did not
    out = _fund()
    assert out["amount"] == "10" and (m.bal[ESCROW], m.bal[AGENT]) == (Decimal("0"), Decimal("10"))


def test_a_retry_of_a_finished_fund_answers_its_result(wired):
    m = wired(_Mover({TREASURY: "10"}))
    first = _fund()
    again = _fund()
    assert again["amount"] == first["amount"] == "10" and again["result"]["idempotent_replay"] is True
    assert (m.bal[TREASURY], m.bal[AGENT]) == (Decimal("0"), Decimal("10"))   # paid once


def test_a_remit_retried_after_its_credit_failed_finishes_the_move(wired):
    m = wired(_Mover({AGENT: "10"}, fail_once={REMIT_IN}))
    with pytest.raises(xs.MoverError):
        _remit()
    out = _remit()
    assert out["amount"] == "10" and (m.bal[AGENT], m.bal[ESCROW], m.bal[TREASURY]) == (0, 0, Decimal("10"))


def test_a_debit_the_mover_could_not_make_is_answered_as_that_not_as_insufficient_funds(wired):
    # the balance read says 5 of 10, but only the TEG can say whether this key's debit already ran
    wired(_Mover({TREASURY: "5"}, fail_once={FUND_OUT}))
    with pytest.raises(xs.MoverError) as e:
        _fund()
    assert e.value.status_code == 502


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_a_fresh_fund_the_treasury_cannot_cover_is_refused_and_moves_nothing(wired):
    m = wired(_Mover({TREASURY: "5"}))
    with pytest.raises(ValueError) as e:
        _fund()
    assert str(e.value) == "insufficient treasury balance: has 5, needs 10"
    assert m.bal[TREASURY] == Decimal("5") and AGENT not in m.bal


def test_control_a_fresh_remit_the_agent_cannot_cover_is_refused(wired):
    wired(_Mover({AGENT: "1"}))
    with pytest.raises(ValueError) as e:
        _remit()
    assert str(e.value) == "insufficient agent balance: has 1, needs 10"


def test_control_a_covered_fund_moves_once(wired):
    m = wired(_Mover({TREASURY: "25"}))
    assert _fund()["amount"] == "10" and (m.bal[TREASURY], m.bal[AGENT]) == (Decimal("15"), Decimal("10"))
