"""§DOCSFIX D6-527 + D6-528 (2026-10-16): a phone session's trace numbers every step once, and every end is on the ledger.

D6-528: each trace row took its sequence number from the session's action counter plus one, and only an allowed action
advances that counter. An observe, a refused action and the next allowed action therefore wrote the same number (start
0, observe 1, act 1, observe 2, act 2). A row now takes the next number of its own session's trace.

D6-527: PhoneSessionEnded went to the event store only when the agent ended its session. A session the TTL ended, whose
token died, that an operator killed or that a global halt ended left the ledger with a PhoneSessionStarted and no end.
Every end now emits PhoneSessionEnded, with its `status` and `end_reason`.

DB-free, like tests/test_phone_fabric.py: the route functions and the reaper run against a session double that keeps
the trace and answers the statements they send; the mock driver is the real one.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry import event_emitter as EE
from agentvault_registry.background_tasks import phone_session_reaper as REAPER
from agentvault_registry.routers import phone_fabric as PF

AGENT = SimpleNamespace(did="did:theprotocol:eu.theprotocol.cloud:4b8f2a10-6c1d-4e7b-9a35-1f0e2d3c4b5a")
SID = "pfs_0123456789abcdef01234567"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Res:
    def __init__(self, scalar=None, first=None, rows=(), mapping=None, rowcount=0):
        self._scalar, self._first, self._rows, self._mapping, self.rowcount = scalar, first, list(rows), mapping, rowcount

    def scalar(self):
        return self._scalar

    def first(self):
        return self._first

    def fetchall(self):
        return list(self._rows)

    def mappings(self):
        return SimpleNamespace(first=lambda: self._mapping)


class _PhoneDB:
    """Keeps one session's trace (`seqs`) and answers the router's and the reaper's statements."""

    def __init__(self, session_row=None, token_ok=True, ended_rows=()):
        self.seqs = [0]                 # the start row
        self.actions_used = 0
        self.session_row = session_row
        self.token_ok = token_ok
        self.ended_rows = list(ended_rows)
        self.commits = 0

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        p = params or {}
        if "MAX(seq)" in sql:
            return _Res(scalar=(max(self.seqs) + 1) if self.seqs else 0)
        if sql.startswith("INSERT INTO phone_session_actions"):
            self.seqs.append(p["q"])
            return _Res()
        if "SET actions_used=actions_used+1" in sql:
            self.actions_used += 1
            return _Res(rowcount=1)
        if sql.startswith("SELECT id, agent_did, capability_token_id"):
            return _Res(mapping=self.session_row)
        if sql.startswith("SELECT status, expires_at <= now() AS expired"):
            return _Res(first=SimpleNamespace(status="active" if self.token_ok else "revoked", expired=False))
        if sql.startswith("SELECT status, instance_id, actions_used") or sql.startswith("SELECT agent_did, status"):
            return _Res(first=SimpleNamespace(status="active", instance_id=3, actions_used=2, agent_did=AGENT.did,
                                              budget_spent=Decimal("3")))
        if "RETURNING" in sql:
            rows, self.ended_rows = self.ended_rows, []
            return _Res(rows=rows, rowcount=len(rows))
        return _Res(rowcount=0)

    async def commit(self):
        self.commits += 1


class _Recorder:
    """emit_background is synchronous on the real emitter; this double records each call (receipt asserted below)."""

    def __init__(self):
        self.received = []

    def emit_background(self, event_type, aggregate_id, data, aggregate_type="Agent", metadata=None,
                        idempotency_key=None, max_retries=3):
        self.received.append({"event_type": event_type, "aggregate_id": aggregate_id, "data": dict(data)})

    def ended(self):
        return [r for r in self.received if r["event_type"] == "PhoneSessionEnded"]


@pytest.fixture
def emitter(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(EE, "get_event_emitter", lambda: rec)
    monkeypatch.setenv("PHONE_FABRIC_ENABLED", "true")
    return rec


def _live_session(db, **kw):
    row = {"id": SID, "agent_did": AGENT.did, "capability_token_id": 5, "backend": "mock", "instance_id": 3,
           "status": "active", "allowed_apps": [], "max_actions": None, "actions_used": db.actions_used,
           "no_screenshot": False, "budget_currency": "ECU", "current_app": None, "current_screen": None,
           "expires_at": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)}
    row.update(kw)
    return row


def test_observe_and_act_never_share_a_sequence_number(monkeypatch, emitter):
    db = _PhoneDB()

    async def _cap(db_, token, agent_did):
        return {"id": 5, "permissions": ["phone.use"], "caveats": {}}

    async def _load(db_, sid, agent_did):
        return _live_session(db)

    monkeypatch.setattr(PF, "_resolve_phone_cap", _cap)
    monkeypatch.setattr(PF, "_load_session", _load)
    acted = []
    for step in ("observe", "act", "observe", "act"):
        if step == "observe":
            _run(PF.observe(SID, screenshot=False, agent=AGENT, db=db, x_capability_token="att_x"))
        else:
            out = _run(PF.act(SID, SimpleNamespace(type="home", target=None, text=None), agent=AGENT, db=db,
                              x_capability_token="att_x"))
            acted.append(out["seq"])
    assert db.seqs == [0, 1, 2, 3, 4], db.seqs
    assert acted == [2, 4], "an action answers the number its own trace row carries"
    assert db.actions_used == 2, "the caveat counter still counts allowed actions only"


def test_a_refused_action_takes_its_own_number(monkeypatch, emitter):
    db = _PhoneDB()
    s = _live_session(db, allowed_apps=["com.vault.bank"])
    with pytest.raises(HTTPException):
        _run(PF._do_act(db, SID, AGENT.did, 5, "launch", "com.evil.app", None, ["com.vault.bank"], None, "mock",
                        "mock-restored", s=s))
    out = _run(PF._do_act(db, SID, AGENT.did, 5, "home", None, None, ["com.vault.bank"], None, "mock",
                          "mock-restored", s=_live_session(db)))
    assert db.seqs == [0, 1, 2] and out["seq"] == 2


@pytest.mark.parametrize("kw,token_ok,status,reason", [
    ({"expires_at": dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)}, True, "expired", "ttl"),
    ({}, False, "revoked", "token_revoked"),
])
def test_a_session_closed_on_a_call_is_ended_on_the_ledger(emitter, kw, token_ok, status, reason):
    db = _PhoneDB(token_ok=token_ok)
    db.session_row = _live_session(db, **kw)
    with pytest.raises(HTTPException):
        _run(PF._load_session(db, SID, AGENT.did))
    ended = emitter.ended()
    assert len(ended) == 1 and ended[0]["aggregate_id"] == AGENT.did
    assert ended[0]["data"]["session_id"] == SID
    assert (ended[0]["data"]["status"], ended[0]["data"]["end_reason"]) == (status, reason)


def test_the_agents_own_end_says_why(emitter):
    db = _PhoneDB()
    _run(PF.end_session(SID, agent=AGENT, db=db))
    assert [r["event_type"] for r in emitter.received] == ["PhoneSessionEnded"]
    ended = emitter.ended()
    assert len(ended) == 1
    assert (ended[0]["data"]["status"], ended[0]["data"]["end_reason"]) == ("ended", "agent")


def test_an_operator_kill_is_ended_on_the_ledger(emitter):
    db = _PhoneDB()
    out = _run(PF.admin_kill_session(SID, dev=SimpleNamespace(id=1, is_admin=True), db=db))
    assert out["status"] == "revoked"
    ended = emitter.ended()
    assert len(ended) == 1 and ended[0]["aggregate_id"] == AGENT.did
    assert (ended[0]["data"]["status"], ended[0]["data"]["end_reason"]) == ("revoked", "admin_kill")


def test_a_global_halt_ends_every_session_on_the_ledger(emitter):
    rows = [SimpleNamespace(id=f"pfs_{i}", agent_did=f"did:theprotocol:x:{i}", actions_used=i, budget_spent=Decimal(i))
            for i in range(3)]
    db = _PhoneDB(ended_rows=rows)
    out = _run(PF.admin_global_halt(dev=SimpleNamespace(id=1, is_admin=True), db=db))
    assert out["halted"] == 3
    ended = emitter.ended()
    assert sorted(e["data"]["session_id"] for e in ended) == ["pfs_0", "pfs_1", "pfs_2"]
    assert {e["data"]["end_reason"] for e in ended} == {"global_halt"}


def test_the_reaper_ends_its_sessions_on_the_ledger(monkeypatch, emitter):
    expired = [SimpleNamespace(id="pfs_ttl", agent_did="did:theprotocol:x:a", actions_used=1, budget_spent=Decimal(2))]
    dead = [SimpleNamespace(id="pfs_dead", agent_did="did:theprotocol:x:b", actions_used=0, budget_spent=Decimal(1))]

    class _ReaperDB(_PhoneDB):
        async def execute(self, stmt, params=None):
            sql = " ".join(str(stmt).split())
            if "RETURNING" in sql and "end_reason='ttl'" in sql:
                return _Res(rows=expired, rowcount=len(expired))
            if "RETURNING" in sql and "end_reason='token_dead'" in sql:
                return _Res(rows=dead, rowcount=len(dead))
            return _Res(rowcount=1)

    class _Ctx:
        async def __aenter__(self):
            return _ReaperDB()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(REAPER, "AsyncSessionLocal", lambda: _Ctx())
    assert _run(REAPER._sweep_once()) == 2
    ended = {e["data"]["session_id"]: e for e in emitter.ended()}
    assert set(ended) == {"pfs_ttl", "pfs_dead"}
    assert (ended["pfs_ttl"]["data"]["status"], ended["pfs_ttl"]["data"]["end_reason"]) == ("expired", "ttl")
    assert (ended["pfs_dead"]["data"]["status"], ended["pfs_dead"]["data"]["end_reason"]) == ("revoked", "token_dead")
