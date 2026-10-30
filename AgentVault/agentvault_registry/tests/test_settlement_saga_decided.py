"""V0649 (agentvault2-13, 2026-10-30): a settlement an administrator decided keeps its decision.

routers/federation_disputes.approve_settlement and reject_settlement set the status and left saga_state at INITIATED
with the 72 h deadline receive_slash_request gave it, so SettlementSaga.check_timeouts (it selects on the saga state
alone) rewrote the decided row as EXPIRED, replaced the administrator's words with "Saga timeout after 72h in state
INITIATED" and emitted SettlementTimeout with requires_admin_review. Measured on sbx-beta 2026-10-30: the settlements
the nightly federation suite had rejected on 10-26 and 10-27 read EXPIRED/TIMED_OUT, the three younger ones still
REJECTED/INITIATED with their deadline ahead. Now the decision moves the saga (SLASH_FAILED for a rejection or a failed
slash, SLASH_CONFIRMED for a slash, as the automatic path does), and the sweep never rewrites a decided status, which
also covers the rows decided before this release. Each test fails on V0647's code (the control).
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from agentvault_registry.routers import federation_disputes as fd
from agentvault_registry.services import settlement_saga as saga_mod

CALLBACK = "https://origin.example.test/api/v1/federation/disputes/slash-confirmation"
ADMIN = SimpleNamespace(email="admin@example.test")


class _Db:
    """execute answers the queued results in order (the settlement, then the defendant)."""
    def __init__(self, *rows):
        self.rows, self.commits, self.statements = list(rows), 0, []

    async def execute(self, stmt):
        self.statements.append(stmt)
        row = self.rows.pop(0) if self.rows else None
        return SimpleNamespace(scalar_one_or_none=lambda: row,
                               scalars=lambda: SimpleNamespace(all=lambda: [] if row is None else [row]))

    async def commit(self):
        self.commits += 1


def _pending():
    return SimpleNamespace(id="s1", status="PENDING_ADMIN_APPROVAL", callback_url=CALLBACK, error_message=None,
                           saga_state="INITIATED", saga_last_step_at=None, dispute_id=7,
                           defendant_did="did:theprotocol:x:d", requested_amount=Decimal("2"),
                           origin_registry_url="https://origin.example.test", slashed_amount=None,
                           slashed_at=None, slash_tx_id=None)


def _http(monkeypatch, teg_status=200):
    """httpx.AsyncClient as the router sees it: the TEG's treasury/receive and the origin's callback both answer."""
    posted = []

    class _Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            posted.append(url)
            if "/treasury/receive" in url:
                return SimpleNamespace(status_code=teg_status, json=lambda: {"new_source_balance": "3"}, text="")
            return SimpleNamespace(status_code=200)
    monkeypatch.setattr(fd.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(fd.svid_client, "get_client_cert_config", lambda: None)
    monkeypatch.setattr(fd, "get_httpx_verify", lambda: False)
    monkeypatch.setattr(fd, "settings", SimpleNamespace(TEG_API_BASE_URL="http://teg.test", TEG_ADMIN_API_KEY="k"))

    received = []   # the emitter double records what it received, so a test can assert receipt (test_doubles_assert_receipt)

    async def _slash(**kw):
        received.append(kw)
        return True
    monkeypatch.setattr(fd, "get_event_emitter", lambda: SimpleNamespace(emit_dispute_slash=_slash))
    return posted, received


def test_a_rejection_moves_the_saga(monkeypatch):
    _, received = _http(monkeypatch)
    s = _pending()
    out = asyncio.run(fd.reject_settlement("s1", None, current_admin=ADMIN, db=_Db(s)))
    assert out["status"] == "REJECTED" and s.status == "REJECTED"
    assert received == []   # a rejection emits no slash
    assert s.saga_state == "SLASH_FAILED" and s.saga_last_step_at is not None


def test_an_approved_slash_moves_the_saga(monkeypatch):
    posted, received = _http(monkeypatch)
    s = _pending()
    defendant = SimpleNamespace(liquid_balance=Decimal("5"))
    out = asyncio.run(fd.approve_settlement("s1", None, current_admin=ADMIN, db=_Db(s, defendant)))
    assert any("/treasury/receive" in u for u in posted)
    assert len(received) == 1 and received[0]["amount"] == 2 and received[0]["slash_tx_id"] == s.slash_tx_id   # the slash event, once
    assert out["status"] == "SLASHED" and s.status == "SLASHED" and s.slashed_amount == Decimal("2")
    assert s.saga_state == "SLASH_CONFIRMED" and s.saga_last_step_at is not None


def test_an_approval_with_nothing_to_slash_moves_the_saga_to_failed(monkeypatch):
    _http(monkeypatch)
    s = _pending()
    out = asyncio.run(fd.approve_settlement("s1", None, current_admin=ADMIN, db=_Db(s, SimpleNamespace(liquid_balance=0))))
    assert out["status"] == "FAILED" and s.saga_state == "SLASH_FAILED"


def test_an_approval_whose_defendant_is_gone_moves_the_saga_to_failed(monkeypatch):
    _http(monkeypatch)
    s = _pending()
    with pytest.raises(HTTPException) as e:
        asyncio.run(fd.approve_settlement("s1", None, current_admin=ADMIN, db=_Db(s, None)))
    assert e.value.status_code == 404 and s.status == "FAILED" and s.saga_state == "SLASH_FAILED"


def test_a_teg_refusal_keeps_the_request_pending_and_the_saga_running(monkeypatch):
    _http(monkeypatch, teg_status=503)
    s = _pending()
    with pytest.raises(HTTPException) as e:
        asyncio.run(fd.approve_settlement("s1", None, current_admin=ADMIN, db=_Db(s, SimpleNamespace(liquid_balance=Decimal("5")))))
    assert e.value.status_code == 502
    assert s.status == "PENDING_ADMIN_APPROVAL" and s.saga_state == "INITIATED"   # retryable: the deadline still applies


def test_the_sweep_never_rewrites_a_decided_settlement():
    db = _Db()
    out = asyncio.run(saga_mod.SettlementSaga.__new__(saga_mod.SettlementSaga).check_timeouts(db))
    assert out == [] and len(db.statements) == 1
    sql = db.statements[0].compile(dialect=postgresql.dialect())
    text = str(sql)
    assert "cross_registry_settlements.saga_state IN" in text and "cross_registry_settlements.status NOT IN" in text
    decided = [v for v in sql.params.values() if isinstance(v, (list, tuple))]
    assert sorted(saga_mod.DECIDED_STATUSES) == ["EXPIRED", "FAILED", "REJECTED", "SETTLED", "SLASHED"]
    assert any(sorted(v) == sorted(saga_mod.DECIDED_STATUSES) for v in decided), sql.params
    # what the sweep may still expire: a request nobody decided
    for undecided in ("PENDING_ADMIN_APPROVAL", "SLASHING", "PENDING_SLASH"):
        assert undecided not in saga_mod.DECIDED_STATUSES
