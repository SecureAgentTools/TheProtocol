"""§DOCSFIX CB-449 + CB-440 (2026-10-16): POST /a2a-payment/authorize admits only a payment its settlement can make.

CB-449: the token's amount is kept to six decimal places (the column's scale). An amount with more places was stored
rounded while the answer echoed the unrounded value, and an amount below 0.0000005 passed the "> 0" check and was
stored as 0.000000, so its settlement could only fail. The amount is now rounded as the database rounds (half up) once,
at the start, and that value is what the spend gate, the balance check, the row and the answer carry; an amount that
rounds to nothing is refused with 400.

CB-440: a payee on this registry is paid by /teg/transfer, which charges the intra-registry fee on top of the amount,
while authorize compared the balance with the amount alone: a payer between the two was authorized, the service
delivered, and the settlement failed. The fee estimate is in the admission now (a payee on another registry pays its
fee out of the amount, so nothing is added there).

RED on the pre-change tree: every test but the controls at the end.
"""
from __future__ import annotations

import asyncio
import importlib
import types
from decimal import Decimal

import pytest
from fastapi import HTTPException

from tests._doubles import StrictEmitter

a2a = importlib.import_module("agentvault_registry.routers.a2a_payment")
idem = importlib.import_module("agentvault_registry.services.idempotency")
fees = importlib.import_module("agentvault_registry.services.transaction_fee_service")

PAYER = "did:theprotocol:eu.theprotocol.cloud:payer-0000"
PAYEE = "did:theprotocol:eu.theprotocol.cloud:payee-0000"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Db:
    def __init__(self):
        self.added = []

    async def scalar(self, *a, **k):
        return 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        obj.id = "tok-0001"

    async def execute(self, *a, **k):
        return types.SimpleNamespace(rowcount=1)


class _Fees:
    def __init__(self, fee):
        self.fee = fee
        self.asked = []

    async def get_fee_for_transfer(self, db, sender_did, transfer_amount):
        self.asked.append((sender_did, transfer_amount))
        if isinstance(self.fee, Exception):
            raise self.fee
        return self.fee, 0.5


def _wire(monkeypatch, *, local, fee=Decimal("0.005"), balance="1"):
    spent = []

    async def _none(*a, **k):
        return None

    async def _spend(db, did, amount, **k):
        spent.append(amount)

    async def _lookup(*a, **k):
        return None, None

    async def _is_local(db, did):
        return local

    payer = types.SimpleNamespace(did=PAYER, id=1, liquid_balance=Decimal(balance))

    async def _purse(db, agent, request):
        return payer, PAYER
    f = _Fees(fee)
    emitter = StrictEmitter()
    monkeypatch.setattr(a2a._rb, "gate", _none)
    monkeypatch.setattr(a2a._ep, "gate", _none)
    monkeypatch.setattr(a2a, "enforce_agent_spend", _spend)
    monkeypatch.setattr(idem, "idempotency_lookup", _lookup)
    monkeypatch.setattr(idem, "idempotency_store", _none)
    monkeypatch.setattr(a2a, "get_event_emitter", lambda: emitter)
    monkeypatch.setattr(a2a, "_issuer_url", lambda r: "https://eu.example")
    monkeypatch.setattr(a2a, "_A2A_PROM_AVAILABLE", False)
    monkeypatch.setattr(a2a, "_is_local_agent", _is_local)
    monkeypatch.setattr(a2a, "_payer_purse", _purse)
    monkeypatch.setattr(fees, "get_transaction_fee_service", lambda: f)
    return payer, spent, f, emitter


def _authorize(amount):
    db = _Db()
    req = a2a.AuthorizeRequest(target_agent_did=PAYEE, amount=amount)
    out = _run(a2a.authorize_payment(req, types.SimpleNamespace(headers={}), current_agent=types.SimpleNamespace(did=PAYER),
                                     db=db, idempotency_key=None))
    return out, db


# ── CB-449: six decimal places, one value throughout ─────────────────────────────────────────────────────────────

def test_an_amount_that_rounds_to_nothing_is_refused(monkeypatch):
    *_, emitter = _wire(monkeypatch, local=False)
    with pytest.raises(HTTPException) as e:
        _authorize("0.0000004")
    assert e.value.status_code == 400 and "0.000001" in e.value.detail
    emitter.assert_nothing_received()


def test_the_answer_the_row_the_spend_gate_and_the_event_carry_the_six_place_amount(monkeypatch):
    _, spent, _, emitter = _wire(monkeypatch, local=False)
    out, db = _authorize("0.1234567")
    assert out.amount == "0.123457"
    assert db.added[0].amount == Decimal("0.123457")
    assert spent == ["0.123457"]
    assert emitter.assert_received("A2APaymentAuthorized", key="a2a-authorized-tok-0001")["data"]["amount"] == "0.123457"


def test_half_a_millionth_rounds_up_as_the_database_rounds(monkeypatch):
    _wire(monkeypatch, local=False)
    out, _ = _authorize("0.0000005")
    assert out.amount == "0.000001"


# ── CB-440: the intra-registry fee is part of the admission ──────────────────────────────────────────────────────

def test_a_local_payee_needs_the_amount_and_the_transfer_fee(monkeypatch):
    _, _, f, emitter = _wire(monkeypatch, local=True, fee=Decimal("0.005"), balance="1")
    with pytest.raises(HTTPException) as e:
        _authorize("1")
    assert e.value.status_code == 402
    assert "1.005000" in e.value.detail and "transfer fee" in e.value.detail
    assert f.asked == [(PAYER, Decimal("1.000000"))]
    emitter.assert_nothing_received()


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_a_local_payee_with_room_for_the_fee_is_authorized(monkeypatch):
    *_, emitter = _wire(monkeypatch, local=True, fee=Decimal("0.005"), balance="2")
    out, _ = _authorize("1.000000")
    assert out.token.startswith("apt_") and out.amount == "1.000000"
    emitter.assert_received("A2APaymentAuthorized", key="a2a-authorized-tok-0001")


def test_control_a_payee_on_another_registry_pays_its_fee_out_of_the_amount(monkeypatch):
    _wire(monkeypatch, local=False, fee=Decimal("0.005"), balance="1")
    out, _ = _authorize("1.000000")
    assert out.amount == "1.000000"


def test_control_a_fee_that_cannot_be_read_admits_on_the_amount_alone(monkeypatch):
    _wire(monkeypatch, local=True, fee=RuntimeError("fee table unavailable"), balance="1")
    out, _ = _authorize("1.000000")
    assert out.amount == "1.000000"


def test_control_a_balance_below_the_amount_is_refused(monkeypatch):
    _wire(monkeypatch, local=False, balance="0.5")
    with pytest.raises(HTTPException) as e:
        _authorize("1.000000")
    assert e.value.status_code == 402 and "Insufficient balance" in e.value.detail


def test_control_a_six_place_amount_is_kept_as_sent(monkeypatch):
    _wire(monkeypatch, local=False)
    out, db = _authorize("0.500000")
    assert out.amount == "0.500000" and db.added[0].amount == Decimal("0.500000")


@pytest.mark.parametrize("amount", ["0", "-1"])
def test_control_a_non_positive_amount_is_refused(monkeypatch, amount):
    _wire(monkeypatch, local=False)
    with pytest.raises(HTTPException) as e:
        _authorize(amount)
    assert e.value.status_code == 400 and "positive" in e.value.detail
