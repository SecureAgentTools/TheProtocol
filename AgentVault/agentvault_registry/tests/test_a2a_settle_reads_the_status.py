"""§DOCSFIX D6-436 (2026-10-16): an A2A settlement whose transfer answers HTTP 200 with "status": "failed" is a
failed settlement.

The cross-registry transfer answers a transfer the TEG refused with HTTP 200 and `"status": "failed"` (and /teg/send
passes that status on), and the background settle took any 200 for a payment: the token read SETTLED while the payee
was never paid. The answer's status is now read; a failed transfer leaves the token FAILED and the payer's owner hears
`payment.settlement_failed`.

RED on the pre-change tree: the three "failed" tests. The controls are green before and after.
"""
from __future__ import annotations

import asyncio
import importlib
import types
from decimal import Decimal

a2a = importlib.import_module("agentvault_registry.routers.a2a_payment")

PAYER = "did:theprotocol:eu.theprotocol.cloud:payer-0000"
PAYEE = "did:theprotocol:asia.theprotocol.cloud:payee-0000"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Resp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class _Client:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    async def post(self, url, json=None, headers=None):
        self.calls.append((url, json, dict(headers or {})))
        return self.resp


def _wire(monkeypatch, resp, *, local=False, smart_send=False):
    client = _Client(resp)

    async def _is_local(db, did):
        return local
    monkeypatch.setattr(a2a, "_get_settle_client", lambda: client)
    monkeypatch.setattr(a2a, "_is_local_agent", _is_local)
    if smart_send:
        monkeypatch.setenv("A2A_SETTLE_VIA_SMART_SEND", "1")
    else:
        monkeypatch.delenv("A2A_SETTLE_VIA_SMART_SEND", raising=False)
    return client


def _settle(db=None):
    return _run(a2a._settle_via_transfer("jwt", PAYEE, Decimal("2"), db, "m"))


FAILED_XREG = {"transfer_id": "xf-1", "status": "failed", "sender_did": PAYER, "receiver_did": PAYEE, "amount": "2",
               "source_teg": "teg-a", "target_teg": "teg-b", "error_message": "Insufficient balance (no funds moved)",
               "timestamp": "2026-10-16T10:00:00+00:00"}
DONE_XREG = dict(FAILED_XREG, status="completed", error_message=None)


def test_a_cross_registry_transfer_answering_200_failed_is_no_settlement(monkeypatch):
    _wire(monkeypatch, _Resp(200, FAILED_XREG))
    assert _settle() is None


def test_a_smart_send_answer_carrying_the_inner_failed_status_is_no_settlement(monkeypatch):
    body = {"ok": True, "method": "2pc", "status": "failed", "transfer_id": "xf-1", "detail": FAILED_XREG}
    _wire(monkeypatch, _Resp(200, body), smart_send=True)
    assert _settle() is None


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


def _background(monkeypatch, resp):
    helpers = importlib.import_module("agentvault_registry.background_tasks.reactor_helpers")
    sent = []

    async def _dispatch(event, data, dids, *, source_label="x"):
        sent.append((event, data.get("status"), data.get("settlement_tx_id")))
        return 1
    auth = types.SimpleNamespace(id="tok-0001", caller_did=PAYER, target_agent_did=PAYEE, amount=Decimal("2"),
                                 status="settling", settlement_tx_id=None, settled_at=None, task_id=None)
    _wire(monkeypatch, resp)
    monkeypatch.setattr(helpers, "dispatch_webhook_for_agents", _dispatch)
    monkeypatch.setattr(a2a, "AsyncSessionLocal", lambda: _Sess(auth))
    monkeypatch.setattr(a2a, "_A2A_PROM_AVAILABLE", False)
    _run(a2a._process_settlement_async(auth_id="tok-0001", caller_jwt="j", receiver_did=PAYEE, amount=Decimal("2"),
                                       message="m", contract_id=None))
    return auth, sent


def test_the_token_of_a_refused_cross_registry_transfer_ends_failed_and_the_payer_hears_it(monkeypatch):
    auth, sent = _background(monkeypatch, _Resp(200, FAILED_XREG))
    assert (auth.status, auth.settlement_tx_id) == ("failed", None)
    assert sent == [("payment.settlement_failed", "failed", None)]


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_a_completed_cross_registry_transfer_settles(monkeypatch):
    auth, sent = _background(monkeypatch, _Resp(200, DONE_XREG))
    assert (auth.status, auth.settlement_tx_id) == ("settled", "xf-1")
    assert sent == [("payment.settled", "settled", "xf-1")]


def test_control_the_async_rails_locked_answer_still_settles(monkeypatch):
    # the async rail answers "locked": the lock moved the money and its saga settles it (or refunds it)
    _wire(monkeypatch, _Resp(200, dict(DONE_XREG, status="locked")))
    assert _settle() == "xf-1"


def test_control_a_local_transfer_settles_on_its_transaction_id(monkeypatch):
    _wire(monkeypatch, _Resp(200, {"transaction_id": "tx-9", "status": "completed"}), local=True)
    assert _settle() == "tx-9"


def test_control_an_error_status_is_no_settlement(monkeypatch):
    _wire(monkeypatch, _Resp(503, {"detail": "Cross-registry transfer service unavailable"}))
    assert _settle() is None
