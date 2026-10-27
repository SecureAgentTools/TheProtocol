"""§DOCSFIX D6-456 (2026-10-16): a cross-registry milestone release whose transfer answers HTTP 200 with
"status": "failed" is a failed release.

drive_release stages a provider's payout through the client and sends it on with the client's own cross-registry
transfer; it took any 200 or 201 for a payment. The transfer answers a transfer the TEGs did not complete with 200 and
`"status": "failed"`, so the milestone was recorded released while the units stayed with the client. The answer's
status is read now: such a transfer takes the failure path (the staged units go back into escrow, the milestone waits
for the client to release it again, and the release answers 502).

§DOCSFIX review: only a "failed" answer that says nothing moved (NO_FUNDS_MOVED) is undone and reopened. Any other
"failed" (a partial commit, a refusal after a leg reached the TEG) may have paid the provider, and the endpoint keeps
that answer under the stable key for 24 hours and runs the transfer afresh after it: reopening the milestone could pay
it twice. Such a release is held for an administrator, nothing is returned to escrow, and the release answers 502.

RED on the pre-change tree: the "failed" tests. RED before the review: the held test (it reopened the milestone). The
controls are green before and after.
"""
from __future__ import annotations

import asyncio
import types
from decimal import Decimal

import httpx
import pytest

from agentvault_registry.services import contract_settlement as cs
from agentvault_registry.services import deal_thread_events as dte
from agentvault_registry.services import escrow

CLIENT = "did:theprotocol:eu.theprotocol.cloud:client-0000"
PROVIDER = "did:theprotocol:asia.theprotocol.cloud:provider-0000"
CONTRACT = {"id": "ctr_1", "counterparty_home_registry": "asia", "client_did": CLIENT, "provider_did": PROVIDER,
            "payee_did": None, "total_amount": Decimal("10"), "currency": "ECU"}
MILESTONE = {"seq": 1, "amount": Decimal("10")}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Db:
    def __init__(self):
        self.sql = []

    async def execute(self, stmt, params=None):
        self.sql.append(str(stmt))
        return types.SimpleNamespace(rowcount=1, scalar=lambda: 1)

    async def commit(self):
        pass


def _setup(monkeypatch, status_code, body):
    rec = types.SimpleNamespace(moves=[], audits=[], db=_Db())

    async def _legs(db, c, m):
        return Decimal("0"), [(PROVIDER, Decimal("10"), "m1:settle")]

    async def _payout(db, did, amount, ref, reason=None):
        rec.moves.append(("payout", did, amount))

    async def _deposit(did, amount, ref, reason=None):
        rec.moves.append(("deposit", did, amount))

    async def _audit(db, cid, seq, etype, actor, data):
        rec.audits.append(etype)

    async def _seq(db, cid):
        return 1

    async def _posted(*a, **k):
        return None

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            rec.moves.append(("transfer", json["receiver_did"], json["amount"], headers.get("Idempotency-Key")))
            return types.SimpleNamespace(status_code=status_code, json=lambda: body, text=str(body))
    monkeypatch.setattr(cs, "compute_release_legs", _legs)
    monkeypatch.setattr(escrow, "escrow_payout", _payout)
    monkeypatch.setattr(escrow, "escrow_deposit", _deposit)
    monkeypatch.setattr(cs, "audit", _audit)
    monkeypatch.setattr(cs, "next_seq", _seq)
    monkeypatch.setattr(cs, "emit", lambda *a, **k: None)
    monkeypatch.setattr(cs, "announce_release", lambda *a, **k: None)
    monkeypatch.setattr(dte, "post_settled", _posted)
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return rec


def _drive(rec):
    return _run(cs.drive_release(rec.db, CONTRACT, MILESTONE, actor_did=CLIENT, auth_header="Bearer client"))


def _released(rec):
    return any("SET status='released'" in s for s in rec.db.sql)


def test_a_transfer_answering_200_failed_is_a_failed_release_and_the_units_go_back_to_escrow(monkeypatch):
    rec = _setup(monkeypatch, 200, {"transfer_id": "xf-1", "status": "failed",
                                    "error_message": "Insufficient balance (no funds moved)"})
    with pytest.raises(escrow.EscrowError) as e:
        _drive(rec)
    assert e.value.status_code == 502 and "Insufficient balance" in e.value.message
    assert [m[0] for m in rec.moves] == ["payout", "transfer", "deposit"]   # staged, sent, put back into escrow
    assert any("SET status='submitted'" in s for s in rec.db.sql) and not _released(rec)
    assert rec.audits == ["release_failed"]


def test_a_failed_answer_that_does_not_say_nothing_moved_holds_the_milestone_for_an_administrator(monkeypatch):
    # the 2PC's answer after a refusal that may have reached the TEG: no NO_FUNDS_MOVED sentence
    rec = _setup(monkeypatch, 200, {"transfer_id": "xf-1", "status": "failed",
                                    "error_message": "Commit failed on target TEG"})
    with pytest.raises(escrow.EscrowError) as e:
        _drive(rec)
    assert e.value.status_code == 502 and "held for admin review" in e.value.message
    assert [m[0] for m in rec.moves] == ["payout", "transfer"]   # staged and sent; nothing taken back into escrow
    assert not any("SET status='submitted'" in s for s in rec.db.sql) and not _released(rec)
    assert rec.audits == ["release_failed"]


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_a_completed_transfer_releases_the_milestone(monkeypatch):
    rec = _setup(monkeypatch, 200, {"transfer_id": "xf-1", "status": "completed"})
    _drive(rec)
    assert [m[0] for m in rec.moves] == ["payout", "transfer"] and _released(rec)
    assert "release_failed" not in rec.audits


def test_control_the_async_rails_locked_answer_releases_with_the_stable_key(monkeypatch):
    rec = _setup(monkeypatch, 200, {"transfer_id": "xf-1", "status": "locked"})
    _drive(rec)
    assert ("transfer", PROVIDER, "10", "ctr-ctr_1-m1-xfsettle") in rec.moves and _released(rec)


def test_control_an_error_status_is_a_failed_release(monkeypatch):
    rec = _setup(monkeypatch, 503, {"detail": "Cross-registry transfer service unavailable"})
    with pytest.raises(escrow.EscrowError) as e:
        _drive(rec)
    assert e.value.status_code == 502 and not _released(rec)
