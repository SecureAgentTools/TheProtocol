"""The A2A stale-settlement sweep trusts only the settlement's own transfer under the settlement key (2026-10-17).

A token still `settling` 90 s after it was verified is closed by the sweep from the record the transfer endpoint kept
under the token's settlement key (routers/a2a_payment._settlement_key), in the records of the payer's side (D6-777).
The key carries a digest of the token's hash, so only the registry and the holders of the plain token can derive it:
and the payer holds the plain token. It could send a transfer of its own under that key (a cent to a friend), and the
sweep, trusting any success kept there, settled the token with that transfer's id: the payee was never paid, the token
read SETTLED and a contract-bound token stamped the payer's transfer on the contract. (The settlement's own transfer,
sent after it under the same key, was refused as a different request, so nothing else paid the payee either.)

Now the sweep rebuilds the request the settlement sent from the token's row (payee, amount, the settlement's message,
and on the cross-registry endpoint its backend: none, or 2pc through /teg/send) and trusts a record only when it was
kept for that request (its body hash, bound to the caller that kept it); any other record under the key is read as no
record, so the token fails as one whose transfer moved nothing. And the task id in that message is written only by the
settle that wins the token's claim (a settle that lost the race used to rewrite it).

Through FastAPI where a route is involved: the payer's transfer goes through the real POST /api/v1/teg/transfer and
/api/v1/teg/cross-registry-transfer (their kept-attempt idempotency, over a fake Redis; the transfer's work after the
claim is a stand-in answering completed), the settle through POST /api/v1/a2a-payment/settle; the sweep runs its own
statements against SQLite (tests/test_a2a_settle_sweep_asks_first.py's table).
RED on 453cc8b8: every test named *payers_own*, the durable-copy one and the claim race (the base settles from the
payer's transfer, and a losing settle rewrites the task id); the pin of the rebuilt body needs this change's helper.
The controls are green before and after.
"""
from __future__ import annotations

import asyncio
import importlib
import types
from decimal import Decimal

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.routers import teg_integration as ti
from agentvault_registry.services.idempotency import cache
from tests import test_a2a_settle_sweep_asks_first as sw
from tests.test_idempotency_per_caller import FakeRedis

a2a, sweep, durable, leader = sw.a2a, sw.sweep, sw.durable, sw.leader
PAYER, PAYEE = sw.PAYER, sw.PAYEE
FRIEND = "did:theprotocol:eu.theprotocol.cloud:friend-0000"
T = sw.T


def _message(tid):
    """The settlement's message as settle_payment builds it for a settle without a task id."""
    return f"A2A service payment (token={tid[:8]}, task=n/a)"


@pytest.fixture
def redis(monkeypatch):
    r = FakeRedis()

    async def _get():
        return r
    monkeypatch.setattr(leader, "get_redis", _get)
    monkeypatch.setenv("IDEMPOTENCY_DURABLE", "off")
    monkeypatch.setattr(cache, "IDEMPOTENCY_INFLIGHT_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(cache, "IDEMPOTENCY_INFLIGHT_POLL_SECONDS", 0.005)
    return r


@pytest.fixture
def conn(monkeypatch):
    """The sweep's SQLite session; the payee is remote unless a test adds it to sw.LOCAL."""
    eng = sa.create_engine("sqlite://", poolclass=StaticPool)
    T.__table__.create(eng)
    c = eng.connect()
    sw.LOCAL.clear()

    async def _is_local(db, did):
        return did in sw.LOCAL

    async def _no_notice(*a, **k):
        return 0
    monkeypatch.setattr(sweep, "async_session_factory", lambda: sw._Db(c))
    monkeypatch.setattr(durable, "enabled", lambda: False)
    monkeypatch.setattr(importlib.import_module("agentvault_registry.background_tasks.reactor_helpers"),
                        "dispatch_webhook_for_agents", _no_notice)
    monkeypatch.setattr(a2a, "_is_local_agent", _is_local)
    monkeypatch.setenv("REDIS_URL", "redis://redis.test:6379/0")
    yield c
    c.close()


@pytest.fixture
def transfers(monkeypatch):
    """The two transfer routes as the payer calls them: the real routes and their kept attempts; the work after the
    claim answers completed with the transfer id the test names (no TEG is reached)."""
    ran = []

    async def _xreg(xfer_req, request, backend, current_agent, db, attempt):
        attempt.mark_dispatched()
        ran.append(("xreg", xfer_req.receiver_did, xfer_req.amount, backend))
        return {"transfer_id": f"xf-{len(ran)}", "status": "completed", "sender_did": current_agent.did,
                "receiver_did": xfer_req.receiver_did, "amount": xfer_req.amount, "source_teg": "teg-eu",
                "target_teg": "teg-asia", "timestamp": "2026-10-17T00:00:00Z"}

    async def _local(transfer_request, request, current_agent, db, attempt):
        attempt.mark_dispatched()
        ran.append(("local", transfer_request.receiver_agent_id, transfer_request.amount, None))
        return {"transaction_id": f"tx-{len(ran)}", "status": "completed", "sender_agent_id": current_agent.did,
                "receiver_agent_id": transfer_request.receiver_agent_id, "amount": transfer_request.amount,
                "fee_amount": "0", "new_sender_balance": "0", "timestamp": "2026-10-17T00:00:00Z"}
    monkeypatch.setattr(ti, "_cross_registry_transfer_run", _xreg)
    monkeypatch.setattr(ti, "_teg_transfer_run", _local)
    monkeypatch.setenv("AGENT_RBAC_MODE", "off")

    app = FastAPI()
    app.include_router(ti.router, prefix="/api/v1")

    async def _db():
        yield types.SimpleNamespace()
    app.dependency_overrides[get_db] = _db
    payer = types.SimpleNamespace(id=7, did=PAYER, status="active", mtls_enabled=False, spiffe_id=None)
    app.dependency_overrides[security.get_current_agent] = lambda: payer
    app.dependency_overrides[security.verify_agent_token] = lambda: {}
    client = TestClient(app, raise_server_exceptions=False)

    def send(path, body, key):
        r = client.post(path, json=body, headers={"Idempotency-Key": key})
        assert r.status_code == 200, (r.status_code, r.text[:300])
        return r.json()
    send.ran = ran
    return send


def _sweep(conn):
    sw._run(sweep._expire_stale_tokens())


def _amount(conn, tid):
    return conn.execute(sa.select(T.__table__.c.amount).where(T.__table__.c.id == tid)).scalar()


# ── the payer's own transfer under the settlement key ──────────────────────────────────────────────────────────────

def test_the_payers_own_cross_registry_transfer_under_the_key_settles_nothing(conn, redis, transfers):
    sw._token(conn, "tok-1")
    transfers("/api/v1/teg/cross-registry-transfer", {"receiver_did": FRIEND, "amount": "0.01"}, sw._key("tok-1"))
    _sweep(conn)
    assert sw._row(conn, "tok-1") == ("failed", None)


def test_the_payers_own_local_transfer_under_the_key_settles_nothing(conn, redis, transfers):
    sw.LOCAL.add(PAYEE)
    sw._token(conn, "tok-1")
    transfers("/api/v1/teg/transfer", {"receiver_agent_id": FRIEND, "amount": "0.01"}, sw._key("tok-1"))
    _sweep(conn)
    assert sw._row(conn, "tok-1") == ("failed", None)


def test_the_payers_own_transfer_to_the_payee_of_another_amount_settles_nothing(conn, redis, transfers):
    sw._token(conn, "tok-1")
    transfers("/api/v1/teg/cross-registry-transfer", {"receiver_did": PAYEE, "amount": "0.000001",
                                                      "message": _message("tok-1")}, sw._key("tok-1"))
    _sweep(conn)
    assert sw._row(conn, "tok-1") == ("failed", None)


def test_the_payers_own_record_in_the_durable_copy_settles_nothing(conn, monkeypatch):
    sw._token(conn, "tok-1")
    sw._store(monkeypatch, {})   # Redis holds nothing under the key
    own = {"receiver_did": FRIEND, "amount": "0.01", "message": None, "backend": None}
    rec = {"body_hash": cache._record_hash(cache.agent_caller(PAYER), own), "state": "answer",
           "payload": {"transfer_id": "xf-friend", "status": "completed"}}

    async def _get(scope, key, unscoped_key=None):
        return rec if key == cache._durable_key(sw._key("tok-1"), cache.agent_caller(PAYER)) else None
    monkeypatch.setattr(durable, "enabled", lambda: True)
    monkeypatch.setattr(durable, "get", _get)
    _sweep(conn)
    assert sw._row(conn, "tok-1") == ("failed", None)


# ── controls: the settlement's own transfer settles its token (green before and after) ─────────────────────────────

class _Capture:
    """The background settlement's HTTP client: records what _settle_via_transfer posts and answers completed."""

    def __init__(self):
        self.posts = []

    async def post(self, url, json=None, headers=None):
        self.posts.append((url, dict(json or {}), dict(headers or {})))
        return types.SimpleNamespace(status_code=200, json=lambda: {"transfer_id": "unused", "status": "completed"},
                                     text="")


def _what_the_settlement_sends(monkeypatch, conn, tid, *, smart=False):
    cap = _Capture()
    monkeypatch.setattr(a2a, "_get_settle_client", lambda: cap)
    if smart:
        monkeypatch.setenv("A2A_SETTLE_VIA_SMART_SEND", "true")
    else:
        monkeypatch.delenv("A2A_SETTLE_VIA_SMART_SEND", raising=False)
    sw._run(a2a._settle_via_transfer("jwt", PAYEE, _amount(conn, tid), None, _message(tid),
                                     idempotency_key=sw._key(tid)))
    (url, body, headers), = cap.posts
    assert headers["Idempotency-Key"] == sw._key(tid)
    return url, body


@pytest.mark.parametrize("local", [False, True])
def test_control_the_settlements_own_transfer_settles_its_token(conn, redis, transfers, monkeypatch, local):
    if local:
        sw.LOCAL.add(PAYEE)
    sw._token(conn, "tok-1")
    url, body = _what_the_settlement_sends(monkeypatch, conn, "tok-1")
    path = "/api/v1/teg/transfer" if local else "/api/v1/teg/cross-registry-transfer"
    assert url.endswith(path), url
    answer = transfers(path, body, sw._key("tok-1"))
    _sweep(conn)
    assert sw._row(conn, "tok-1") == ("settled", answer.get("transfer_id") or answer.get("transaction_id"))


def test_control_a_settlement_through_smart_send_settles_its_token(conn, redis, transfers, monkeypatch):
    """/teg/send forwards a same-currency payee's settlement to the cross-registry endpoint with backend 2pc."""
    sw._token(conn, "tok-1")
    url, body = _what_the_settlement_sends(monkeypatch, conn, "tok-1", smart=True)
    assert url.endswith("/api/v1/teg/send"), url
    inner = {"receiver_did": body["receiver_did"], "amount": body["amount"], "message": body["message"]}
    answer = transfers("/api/v1/teg/cross-registry-transfer?backend=2pc", inner, sw._key("tok-1"))
    _sweep(conn)
    assert sw._row(conn, "tok-1") == ("settled", answer["transfer_id"])


def test_control_a_record_kept_before_records_were_the_callers_still_settles_its_token(conn, monkeypatch):
    sw._token(conn, "tok-1")
    own = ti.CrossRegistryTransferRequest(receiver_did=PAYEE, amount=str(_amount(conn, "tok-1")),
                                          message=_message("tok-1")).model_dump(mode="json")
    own["backend"] = None
    sw._store(monkeypatch, sw._kept("teg.cross-registry-transfer", "tok-1", {
        "body_hash": cache._body_hash(own), "response": {"transfer_id": "xf-old", "status": "completed"}}))
    _sweep(conn)
    assert sw._row(conn, "tok-1") == ("settled", "xf-old")


# ── the rebuilt body is the one the settlement sends ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("local,smart", [(False, False), (True, False), (False, True), (True, True)])
def test_the_sweep_rebuilds_exactly_the_body_the_settlement_sends(conn, monkeypatch, local, smart):
    if local:
        sw.LOCAL.add(PAYEE)
    sw._token(conn, "tok-1")
    _url, body = _what_the_settlement_sends(monkeypatch, conn, "tok-1", smart=smart)
    amount = _amount(conn, "tok-1")
    rebuilt = a2a._settlement_record_bodies(PAYEE, amount, a2a._settlement_message("tok-1", None), local)
    if local:
        kept = ti.TEGTransferRequest(receiver_agent_id=PAYEE, amount=body["amount"],
                                     message=body["message"]).model_dump(mode="json")
    else:
        kept = ti.CrossRegistryTransferRequest(receiver_did=PAYEE, amount=body["amount"],
                                               message=body["message"]).model_dump(mode="json")
        kept["backend"] = "2pc" if smart else None
    assert kept in rebuilt, (kept, rebuilt)


# ── the settle that wins the claim writes the task id ──────────────────────────────────────────────────────────────

PLAIN = "apt_" + "cd" * 32


@pytest.fixture
def settle(monkeypatch):
    """POST /api/v1/a2a-payment/settle over an ORM session on SQLite, as the payer."""
    eng = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    T.__table__.create(eng)
    session = Session(eng)
    started = []

    async def _purse(db, agent, request):
        return agent, agent.did

    def _process(**kw):
        started.append(kw)
        return asyncio.sleep(0)
    monkeypatch.setattr(a2a, "_payer_purse", _purse)
    monkeypatch.setattr(a2a, "_process_settlement_async", _process)
    monkeypatch.setattr(a2a._rb, "bond_mode", lambda: "off")
    monkeypatch.setattr(a2a._ep, "propagation_mode", lambda: "off")
    monkeypatch.setattr(a2a, "_A2A_PROM_AVAILABLE", False)
    monkeypatch.setenv("AGENT_RBAC_MODE", "off")

    class _OrmDb:
        def __init__(self):
            self.race = None

        async def execute(self, stmt, *a, **k):
            if self.race is not None and type(stmt).__name__ == "Update":
                race, self.race = self.race, None
                with session.no_autoflush:      # the winner's claim lands first, outside this settle's own writes
                    session.execute(race)
            return session.execute(stmt, *a, **k)

        async def commit(self):
            session.commit()

        async def refresh(self, obj):
            session.refresh(obj)

        async def rollback(self):
            session.rollback()
    db = _OrmDb()
    app = FastAPI()
    app.include_router(a2a.router)
    app.dependency_overrides[get_db] = lambda: db
    payer = types.SimpleNamespace(id=7, did=PAYER, status="active", mtls_enabled=False, spiffe_id=None)
    app.dependency_overrides[security.get_current_agent] = lambda: payer
    app.dependency_overrides[security.verify_agent_token] = lambda: {}
    client = TestClient(app, raise_server_exceptions=False)
    session.execute(sa.insert(T.__table__).values(
        id="tok-9", caller_did=PAYER, target_agent_did=PAYEE, amount=Decimal("2"), token_hash=a2a._hash_token(PLAIN),
        token_prefix="apt_c", status="consumed", created_at=sa.func.now(), expires_at=sa.func.now()))
    session.commit()

    def task_id():
        session.expire_all()
        return session.execute(sa.select(T.__table__.c.status, T.__table__.c.task_id)
                               .where(T.__table__.c.id == "tok-9")).one()
    return types.SimpleNamespace(client=client, db=db, task_id=task_id, started=started)


def test_a_settle_that_loses_the_claim_leaves_the_winners_task_id(settle):
    settle.db.race = (sa.update(T.__table__).where(T.__table__.c.id == "tok-9")
                      .values(status="settling", task_id="task-A"))
    r = settle.client.post("/api/v1/a2a-payment/settle", json={"token": PLAIN, "task_id": "task-B"},
                           headers={"Authorization": "Bearer jwt"})
    assert r.status_code == 409, (r.status_code, r.text[:300])
    assert tuple(settle.task_id()) == ("settling", "task-A")
    assert settle.started == []


def test_control_the_settle_that_wins_the_claim_writes_its_task_id(settle):
    r = settle.client.post("/api/v1/a2a-payment/settle", json={"token": PLAIN, "task_id": "task-B"},
                           headers={"Authorization": "Bearer jwt"})
    assert r.status_code == 200 and r.json()["status"] == "settling", (r.status_code, r.text[:300])
    assert tuple(settle.task_id()) == ("settling", "task-B")
    [kw] = settle.started
    assert kw["message"] == "A2A service payment (token=tok-9, task=task-B)"
