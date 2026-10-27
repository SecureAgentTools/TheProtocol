"""§TWOAGENT G3 (2026-09-23) — money can be pushed: `payment.received`, `payment.settled`, `payment.settlement_failed`.

Findings 6 and 24: the webhook vocabulary (50 events) had nothing for money, so a runtime selling a service had to poll
its balance to learn it was paid; and an FX-pool arrival leaves ONE event on the receiver's own store, a
`LedgerBalanceChanged` (measured on ASIA at 09:58:54Z: the fx reserve −1.988495, the agent +1.988495), while the event
naming the sender lives on the sending frame's store.

`payment.received` is read from the frame's own ledger (every credit is exactly one LedgerBalanceChanged, whatever the
rail), owner-scoped, once per credit; the A2A payer's owner hears how its payment ended. The ledger shapes below are
copied from real events on ASIA's and sbx-beta's stores.

RED on the pre-change tree: every test except the control at the end.
"""
from __future__ import annotations

import asyncio
import importlib
import types
from decimal import Decimal

import pytest

AGENT = "did:theprotocol:asia.theprotocol.cloud:011dbd40-1039-4ef9-a457-404d87f2e130"
PAYER = "did:theprotocol:asia.theprotocol.cloud:3fdb3644-20a0-4d0f-ac4c-b89eaba24913"
FEE = "teg:system:fee_collector"
RESERVE = "did:theprotocol:teg_system_fx_reserve"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _mod():
    return importlib.import_module("agentvault_registry.background_tasks.reactor_payment_received")


def _ledger(kind, entries, txid=2443, frame="teg-layer", **extra):
    return {"net": "0", "kind": kind, "txid": txid, "frame": frame,
            "entries": [{"agent_did": d, "delta_liquid": v, "delta_staked": "0"} for d, v in entries], **extra}


FX_ARRIVAL = _ledger("transfer", [(AGENT, "1.988495000000000000"), (RESERVE, "-1.988495000000000000")])
LOCAL = _ledger("transfer", [(PAYER, "-0.100500000000000000"), (AGENT, "0.100000000000000000"),
                             (FEE, "0.000500000000000000")], txid=1939, frame="teg-shenzhen")
XFRAME = _ledger("cross_teg_credit", [(AGENT, "0.099500000000000000"), (FEE, "0.000500000000000000")], txid=2753)


# ── what counts as a payment, and what the ledger can say about it ──────────────────────────────────────────────

def test_a_local_transfer_is_a_payment_from_the_named_payer():
    [p] = _mod().payments_in(LOCAL)
    assert (p["agent_did"], p["amount"], p["from_did"], p["via"], p["sender_known"]) == (AGENT, "0.1", PAYER, "transfer", True)
    assert p["ledger_txid"] == 1939 and p["teg"] == "teg-shenzhen"


def test_an_fx_pool_arrival_is_a_payment_whose_sender_this_ledger_cannot_name():
    [p] = _mod().payments_in(FX_ARRIVAL)
    assert p["amount"] == "1.988495" and p["via"] == "fx_pool" and p["from_did"] is None
    assert "sending frame" in p["note"]


def test_a_cross_frame_credit_is_a_payment_and_says_where_the_sender_is_recorded():
    [p] = _mod().payments_in(XFRAME)
    assert p["amount"] == "0.0995" and p["via"] == "cross_frame" and p["from_did"] is None
    assert "sending frame" in p["note"]


def test_trading_and_escrow_kinds_are_not_payments_and_the_fee_collector_is_never_paid():
    m = _mod()
    assert m.payments_in(_ledger("exchange_trade_payout", [(AGENT, "5"), ("teg:system:exchange_escrow", "-5")])) == []
    assert m.payments_in(_ledger("cross_teg_escrow_release", [(AGENT, "5")])) == []
    assert all(p["agent_did"] != FEE for p in m.payments_in(LOCAL))


# ── the reactor: owner-scoped, once per credit, never for a peer's copy ─────────────────────────────────────────

class _Redis:
    def __init__(self):
        self.keys = set()

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.keys:
            return None
        self.keys.add(k)
        return True

    async def delete(self, k):
        self.keys.discard(k)


def _wire(monkeypatch, *, redis=None, subscribers=True):
    m = _mod()
    sent = []

    async def _dispatch(event, data, dids, *, source_label="x"):
        sent.append((event, data, list(dids)))
        return 1

    async def _subs():
        return subscribers
    leader = importlib.import_module("agentvault_registry.background_tasks.leader")
    r = redis if redis is not None else _Redis()

    async def _get_redis():
        return r
    monkeypatch.setattr(m, "dispatch_webhook_for_agents", _dispatch)
    monkeypatch.setattr(m, "_any_subscribers", _subs)
    monkeypatch.setattr(m, "is_notification_stale", lambda d: (False, 0))
    monkeypatch.setattr(leader, "get_redis", _get_redis)
    return m, sent


def _handle(m, data):
    _run(m.PaymentReceivedReactor.handle_event(types.SimpleNamespace(name="PaymentReceived"), data))


def test_the_receivers_owner_is_told_once_even_when_the_event_is_replayed(monkeypatch):
    m, sent = _wire(monkeypatch)
    _handle(m, dict(LOCAL))
    _handle(m, dict(LOCAL))  # the store's reconnect replay / the polling backstop
    assert [(e, d["agent_did"], dids) for e, d, dids in sent] == [("payment.received", AGENT, [AGENT])]


def test_a_peers_copy_of_a_ledger_event_tells_nobody(monkeypatch):
    m, sent = _wire(monkeypatch)
    _handle(m, {**FX_ARRIVAL, "_foreign_frame_id": "eu.theprotocol.cloud"})
    assert sent == []


def test_without_a_claim_store_nothing_is_announced(monkeypatch):
    m, sent = _wire(monkeypatch)
    leader = importlib.import_module("agentvault_registry.background_tasks.leader")

    async def _none():
        return None
    monkeypatch.setattr(leader, "get_redis", _none)
    _handle(m, dict(XFRAME))
    assert sent == []


def test_with_no_subscriber_the_reactor_does_no_work(monkeypatch):
    m, sent = _wire(monkeypatch, subscribers=False)
    _handle(m, dict(LOCAL))
    assert sent == []


def test_the_events_are_in_the_catalogue():
    from agentvault_registry.services.webhook_service import WebhookService
    assert {"payment.received", "payment.settled", "payment.settlement_failed"} <= set(WebhookService.SUPPORTED_EVENTS)


# ── the A2A payer hears how its payment ended ──────────────────────────────────────────────────────────────────

class _Sess:
    def __init__(self, auth):
        self.auth = auth

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, model, key):
        return self.auth

    async def commit(self):
        pass

    async def execute(self, *a, **k):
        return types.SimpleNamespace(scalar_one_or_none=lambda: None)


def _settle_bg(monkeypatch, tx):
    a2a = importlib.import_module("agentvault_registry.routers.a2a_payment")
    helpers = importlib.import_module("agentvault_registry.background_tasks.reactor_helpers")
    sent = []

    async def _dispatch(event, data, dids, *, source_label="x"):
        sent.append((event, data, list(dids)))
        return 1

    async def _xfer(*a, **k):
        return tx
    auth = types.SimpleNamespace(id="tok-0001", caller_did=PAYER, target_agent_did=AGENT, amount=Decimal("2"),
                                 status="settling", settlement_tx_id=None, settled_at=None, task_id="t1")
    monkeypatch.setattr(helpers, "dispatch_webhook_for_agents", _dispatch)
    monkeypatch.setattr(a2a, "_settle_via_transfer", _xfer)
    monkeypatch.setattr(a2a, "AsyncSessionLocal", lambda: _Sess(auth))
    monkeypatch.setattr(a2a, "_A2A_PROM_AVAILABLE", False)
    _run(a2a._process_settlement_async(auth_id="tok-0001", caller_jwt="j", receiver_did=AGENT, amount=Decimal("2"),
                                       message="m", contract_id=None))
    return sent


def test_the_payers_owner_is_told_the_payment_settled(monkeypatch):
    sent = _settle_bg(monkeypatch, "tx-77")
    assert [(e, d["status"], d["settlement_tx_id"], dids) for e, d, dids in sent] == [
        ("payment.settled", "settled", "tx-77", [PAYER])]


def test_the_payers_owner_is_told_the_settlement_failed(monkeypatch):
    sent = _settle_bg(monkeypatch, None)
    assert [(e, d["status"], dids) for e, d, dids in sent] == [("payment.settlement_failed", "failed", [PAYER])]


# ── control: green before and after ────────────────────────────────────────────────────────────────────────────

def test_control_the_older_vocabulary_is_intact():
    from agentvault_registry.services.webhook_service import WebhookService
    assert {"contract.agreed", "chat.message.received", "agent.suspended"} <= set(WebhookService.SUPPORTED_EVENTS)
