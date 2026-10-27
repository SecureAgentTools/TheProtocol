"""D6-272 (2026-10-17): a cross-registry delegation revoke that does not reach the delegate's registry is sent again.

DELETE /api/v1/agents/delegate-cross-registry/{credential_id} records the revoke on the issuer's registry (the record the
delegate's registry asks at use: the source of truth since V0620) and sends it to the delegate's registry. That send was
made once. Now a send that did not land is owed (xreg_revokes_owed, written with the issuer-side record) and
background_tasks/xreg_revoke_retry sends it again with backoff until the delegate's registry takes it, refuses it for
good, the budget is spent or the delegation expires. Every recorded revoke answers 200 with `delivery`; the issuer's
list and the admin delegation report show each delivery. A revoke is sent only for a delegation this agent issued, to
the registry it was issued to.

Through FastAPI on the real router; the database is a fake that answers the audit-record and owed-row queries the code
makes (no SQL runs), the federation client and the peer resolution are doubles, the audit writer and the event emitter
record what they are given. RED on 453cc8b8 (the base's route, models and issuer-authority mounted): every route test
(the base answers 502 or ships to the caller's URL, keeps no owed row, and lists an undelivered revoke as active) and the
worker tests (no owed table on the base's models). The receiver's idempotency test is green on both: it is the
property the retries rely on.
"""
import asyncio
import contextlib
import datetime as dt
import json
from collections import Counter
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.routers import agent_delegation_api as deleg
from agentvault_registry.routers import guild
from agentvault_registry.services import xreg_revoke_delivery as xrd

ISSUER = "did:theprotocol:eu.theprotocol.cloud:issuer-0001"
OTHER_AGENT = "did:theprotocol:eu.theprotocol.cloud:other-0002"
DELEGATE = "did:theprotocol:asia.theprotocol.cloud:delegate-0003"
PEER = "https://asia.example.invalid"
ELSEWHERE = "https://elsewhere.example.invalid"
CRED = "cred-0123456789abcdef"
SELF = "https://eu.example.invalid"
NOW = dt.datetime.now(dt.timezone.utc)


class _Res:
    def __init__(self, *, rows=None, mappings=None, scalar=None):
        self._rows, self._mappings, self._scalar = list(rows or []), list(mappings or []), scalar

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._scalar

    def fetchall(self):
        return list(self._rows)

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))

    def mappings(self):
        return SimpleNamespace(all=lambda: list(self._mappings))


def _param(stmt, prefix):
    return next(v for k, v in stmt.compile().params.items() if k.startswith(prefix))


class _Db:
    """The registry's session, as far as these routes and the worker use it."""

    def __init__(self):
        self.owed = {}       # xreg_revokes_owed by credential id
        self.audit = []      # security_audit_logs, oldest first
        self.commits = 0

    def issue(self, cred=CRED, *, actor=ISSUER, registry=PEER, outcome="success", hours=24):
        self.audit.append({"action": "ironkey.xreg_delegation_issue", "actor_type": "agent", "actor_id": actor,
                           "target_id": DELEGATE, "outcome": outcome, "timestamp": NOW,
                           "details": json.dumps({"credential_id": cred, "delegate_registry": registry,
                                                  "permissions": ["teg.transfer"], "caveats": {},
                                                  "expires_at": (NOW + dt.timedelta(hours=hours)).isoformat()})})

    async def get(self, model, pk):
        return self.owed.get(pk)

    def add(self, obj):
        self.owed[obj.credential_id] = obj

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        p = params or {}
        if "xreg_revokes_owed" in sql:
            rows = list(self.owed.values())
            if "GROUP BY" in sql:
                return _Res(rows=list(Counter(xrd.state_of(r) for r in rows).items()))
            if "count(" in sql:
                return _Res(scalar=sum(1 for r in rows if r.done_at is None and r.dead_at is None))
            if "issuer_did =" in sql:
                return _Res(rows=[r for r in rows if r.issuer_did == _param(stmt, "issuer_did")])
            if "next_attempt_at <=" in sql:
                due = _param(stmt, "next_attempt_at")
                return _Res(rows=sorted((r for r in rows if r.done_at is None and r.dead_at is None
                                         and r.next_attempt_at <= due), key=lambda r: r.next_attempt_at))
            if "done_at IS NULL" in sql:
                return _Res(rows=sorted((r for r in rows if r.done_at is None), key=lambda r: r.created_at))
            raise AssertionError(f"an owed-row query this fake does not know: {sql}")
        if "security_audit_logs" in sql:
            newest = list(reversed(self.audit))
            if "IN ('ironkey.xreg_delegation_issue', 'ironkey.xreg_delegation_revoke')" in sql:
                return _Res(mappings=[{k: a[k] for k in ("timestamp", "action", "outcome", "target_id", "details")}
                                      for a in newest if a["actor_type"] == "agent" and a["actor_id"] == p["d"]
                                      and a["action"] in ("ironkey.xreg_delegation_issue",
                                                          "ironkey.xreg_delegation_revoke")])
            if "'ironkey.xreg_delegation_issue'" in sql:
                return _Res(rows=[(a["details"],) for a in newest if a["action"] == "ironkey.xreg_delegation_issue"
                                  and a["actor_id"] == p["iss"]
                                  and ("outcome = 'success'" not in sql or a["outcome"] == "success")])
            if "'ironkey.xreg_delegation_revoke'" in sql and ":cid" in sql:
                hit = any(a["action"] == "ironkey.xreg_delegation_revoke" and a["actor_id"] == p["iss"]
                          and a["target_id"] == p["cid"] for a in self.audit)
                return _Res(rows=[(1,)] if hit else [])
        if "FROM agents WHERE did" in sql:
            return _Res(rows=[("active", "active")])
        if "agent_delegation_grants" in sql:
            return _Res(scalar=0)
        if "agent_capability_tokens" in sql:
            return _Res(rows=[])
        raise AssertionError(f"a query this fake does not know: {sql}")


@pytest.fixture
def rig(monkeypatch):
    db = _Db()
    rec = {"posts": [], "emitter_calls": []}
    state = {"answers": [], "resolve": {}}

    class _Resp:
        def __init__(self, status_code, text="{}"):
            self.status_code, self.text = status_code, text

    class _Client:
        def __init__(self, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            rec["posts"].append((url, json))
            a = state["answers"].pop(0) if state["answers"] else (200, '{"ok": true, "revoked": true}')
            if isinstance(a, Exception):
                raise a
            return _Resp(*a)

    async def _resolve(_db, url):
        return state["resolve"].get(url, url + "/fed")

    async def _audit(_db, **k):
        db.audit.append({"action": f"ironkey.{k['action']}", "actor_type": k["actor_type"], "actor_id": k["actor_id"],
                         "target_id": k["target_id"], "outcome": k.get("outcome", "success"), "timestamp": NOW,
                         "details": json.dumps(k.get("details") or {})})
        await db.commit()

    class _Emitter:
        def emit_background(self, **k):
            rec["emitter_calls"].append(k)

    import agentvault_registry.event_emitter as em
    monkeypatch.setenv("AGENT_XREG_DELEGATION_ENABLED", "true")
    monkeypatch.setenv("AGENT_RBAC_MODE", "off")
    monkeypatch.delenv("XREG_REVOKE_RETRY_MAX_ATTEMPTS", raising=False)
    monkeypatch.setattr(deleg, "log_ironkey_action", _audit)
    monkeypatch.setattr(em, "get_event_emitter", lambda: _Emitter())
    monkeypatch.setattr(guild, "_resolve_peer_url", _resolve)
    monkeypatch.setattr(guild, "_fed_client_config", lambda target: ({}, {}))
    monkeypatch.setattr(guild, "_self_public_url", lambda: SELF)
    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    app = FastAPI()
    app.include_router(deleg.router)
    app.dependency_overrides[get_db] = lambda: db
    who = {"did": ISSUER}
    app.dependency_overrides[security.get_current_agent] = lambda: SimpleNamespace(did=who["did"], id=1,
                                                                                  status="active")
    app.dependency_overrides[security.verify_agent_token] = lambda: {"type": "agent"}
    for r in deleg.router.routes:   # the router's own routes: an included router is not flattened into app.routes
        if getattr(r, "path", "") == "/admin/agents/delegation/report":
            for d in r.dependant.dependencies:
                if d.name == "current":   # the admin gate only; the session stays the fake
                    app.dependency_overrides[d.call] = lambda: SimpleNamespace(id=1, is_admin=True)
    client = TestClient(app, raise_server_exceptions=False)

    async def _cycle():
        from agentvault_registry.background_tasks import xreg_revoke_retry as xrr

        @contextlib.asynccontextmanager
        async def _ctx():
            yield db
        monkeypatch.setattr(xrr, "get_db_context", _ctx)
        w = xrr.XRegRevokeRetry()
        await w._cycle_once()
        return w._last_stats()

    def revoke(cred=CRED, **params):
        return client.delete(f"/agents/delegate-cross-registry/{cred}", params=params)

    def make_due():
        for row in db.owed.values():
            row.next_attempt_at = NOW - dt.timedelta(seconds=1)

    return SimpleNamespace(db=db, rec=rec, state=state, client=client, revoke=revoke, who=who,
                           cycle=lambda: asyncio.run(_cycle()), make_due=make_due,
                           listing=lambda: client.get("/agents/delegate-cross-registry"),
                           report=lambda: client.get("/admin/agents/delegation/report"))


def _revoke_records(rig):
    return [a for a in rig.db.audit if a["action"] == "ironkey.xreg_delegation_revoke"]


# ─────────────────────────────── the route and the worker ───────────────────────────────

def test_a_revoke_whose_send_did_not_land_is_owed_and_a_later_cycle_delivers_it(rig):
    rig.db.issue()
    rig.state["answers"] = [httpx.ConnectError("connection refused")]
    r = rig.revoke(delegate_registry_url=PEER)
    assert r.status_code == 200, (r.status_code, r.text[:300])
    body = r.json()
    assert body["ok"] is False and body["delegate_registry"] == PEER
    d = body["delivery"]
    assert d["state"] == "retrying" and d["attempts"] == 1 and d["last_status"] is None
    assert "ConnectError" in d["last_error"]
    nxt = dt.datetime.fromisoformat(d["next_attempt_at"])
    assert 50 <= (nxt - dt.datetime.now(dt.timezone.utc)).total_seconds() <= 70, "the first wait is one minute"
    rows = _revoke_records(rig)   # the source of truth, written with the owed row
    assert len(rows) == 1 and rows[0]["outcome"] == "ship_failed"
    assert json.loads(rows[0]["details"])["ship_error"] == "ConnectError"
    assert len(rig.rec["emitter_calls"]) == 1 and rig.rec["emitter_calls"][0]["event_type"] == "AgentXRegDelegationRevoked"
    listed = rig.listing().json()["delegations"][0]
    assert listed["state"] == "revoked" and listed["revoke_delivered"] is False
    assert listed["revoke_delivery"]["state"] == "retrying"

    stats = rig.cycle()   # not due yet: nothing is sent
    assert stats["delivered_this_cycle"] == 0 and len(rig.rec["posts"]) == 1

    rig.make_due()
    stats = rig.cycle()
    assert stats == {"delivered_this_cycle": 1, "retried_this_cycle": 0, "dead_this_cycle": 0, "open_now": 0}
    assert rig.rec["posts"][-1] == (f"{PEER}/fed/api/v1/federation/ironkey/delegation-revoke",
                                    {"credential_id": CRED, "issuer_registry": SELF}), "the same request, again"
    row = rig.db.owed[CRED]
    assert row.done_at is not None and row.attempts == 2 and row.last_status == 200
    listed = rig.listing().json()["delegations"][0]
    assert listed["state"] == "revoked" and listed["revoke_delivered"] is True
    assert listed["revoke_delivery"]["state"] == "delivered"
    report = rig.report().json()["xreg_revoke_delivery"]
    assert report["counts"]["delivered"] == 1 and report["undelivered"] == []


def test_a_refusal_that_cannot_change_parks_the_delivery_and_the_admin_sees_it(rig):
    rig.db.issue()
    rig.state["answers"] = [(503, "unavailable"), (422, "bad request body")]
    r = rig.revoke()
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["peer_status"] == 503
    assert r.json()["delivery"]["state"] == "retrying"
    rig.make_due()
    stats = rig.cycle()
    assert stats["dead_this_cycle"] == 1 and stats["open_now"] == 0
    row = rig.db.owed[CRED]
    assert row.dead_at is not None and row.last_status == 422 and row.attempts == 2
    report = rig.report().json()["xreg_revoke_delivery"]
    assert report["counts"]["given_up"] == 1
    (u,) = report["undelivered"]
    assert (u["credential_id"], u["issuer_did"], u["delegate_registry"], u["state"], u["last_status"]) == \
        (CRED, ISSUER, PEER, "given_up", 422)
    rig.make_due()
    rig.cycle()
    assert len(rig.rec["posts"]) == 2, "a parked delivery is not sent again"


def test_the_attempt_budget_parks_a_delivery_that_never_lands(rig, monkeypatch):
    monkeypatch.setenv("XREG_REVOKE_RETRY_MAX_ATTEMPTS", "3")
    rig.db.issue()
    rig.state["answers"] = [(503, "")] * 3
    rig.revoke()
    for want_open in (1, 0):
        rig.make_due()
        assert rig.cycle()["open_now"] == want_open
    row = rig.db.owed[CRED]
    assert row.attempts == 3 and row.dead_at is not None and xrd.state_of(row) == "given_up"
    assert rig.listing().json()["delegations"][0]["revoke_delivery"]["state"] == "given_up"


def test_once_the_delegation_has_expired_its_revoke_is_not_sent_again(rig):
    rig.db.issue()
    rig.state["answers"] = [(503, "")]
    rig.revoke()
    row = rig.db.owed[CRED]
    row.credential_expires_at = NOW - dt.timedelta(minutes=1)
    rig.make_due()
    assert rig.cycle()["dead_this_cycle"] == 1
    assert len(rig.rec["posts"]) == 1, "nothing is left to revoke there: no send"
    assert xrd.state_of(row) == "expired" and row.last_error == xrd.EXPIRED_NOTE


def test_a_delivered_send_closes_an_open_delivery_and_revoking_again_reopens_a_parked_one(rig):
    rig.db.issue()
    rig.state["answers"] = [(503, ""), (200, "{}")]
    rig.revoke()
    assert xrd.state_of(rig.db.owed[CRED]) == "retrying"
    r = rig.revoke()
    assert r.json()["ok"] is True and r.json()["delivery"]["state"] == "delivered"
    assert xrd.state_of(rig.db.owed[CRED]) == "delivered"

    rig.db.issue("cred-parked")
    rig.state["answers"] = [(422, ""), (503, "")]
    rig.revoke("cred-parked")
    assert xrd.state_of(rig.db.owed["cred-parked"]) == "given_up"
    r = rig.revoke("cred-parked")
    d = r.json()["delivery"]
    assert d["state"] == "retrying" and d["attempts"] == 1, "the issuer asked again: a fresh budget"


def test_a_registry_that_is_not_an_active_peer_right_now_is_tried_again_later(rig, monkeypatch):
    from fastapi import HTTPException
    rig.db.issue()

    async def _not_a_peer(_db, url):
        raise HTTPException(400, detail="target_registry_url is not an ACTIVE peer of this registry")
    monkeypatch.setattr(guild, "_resolve_peer_url", _not_a_peer)
    r = rig.revoke()
    assert r.status_code == 200 and r.json()["ok"] is False and rig.rec["posts"] == []
    assert r.json()["delivery"]["state"] == "retrying" and "not an active peer" in r.json()["delivery"]["last_error"]
    assert _revoke_records(rig)[0]["outcome"] == "ship_failed"


def test_the_revoke_is_recorded_even_when_its_delivery_cannot_be(rig, monkeypatch):
    """The issuer-side record decides; a failure to write the owed delivery must not take it along."""
    async def _broken(*a, **k):
        raise RuntimeError("relation xreg_revokes_owed does not exist")
    monkeypatch.setattr(xrd, "record_send", _broken)
    rig.db.issue()
    rig.state["answers"] = [(503, "")]
    r = rig.revoke()
    assert r.status_code == 200 and r.json()["delivery"]["state"] == "not_queued"
    assert [a["outcome"] for a in _revoke_records(rig)] == ["ship_failed"]


def test_only_a_delegation_this_agent_issued_can_be_revoked(rig):
    rig.db.issue(actor=OTHER_AGENT)   # another agent of this registry issued it
    r = rig.revoke(delegate_registry_url=PEER)
    assert r.status_code == 404, (r.status_code, r.text[:300])
    assert rig.rec["posts"] == [] and _revoke_records(rig) == [] and rig.db.owed == {}


def test_the_revoke_goes_to_the_registry_the_delegation_was_issued_to(rig):
    rig.db.issue(registry=PEER)
    r = rig.revoke(delegate_registry_url=ELSEWHERE)
    assert r.status_code == 200 and r.json()["delegate_registry"] == PEER
    assert [u for u, _ in rig.rec["posts"]] == [f"{PEER}/fed/api/v1/federation/ironkey/delegation-revoke"]
    assert json.loads(_revoke_records(rig)[0]["details"])["delegate_registry"] == PEER


def test_the_issuer_authority_answer_says_revoked_while_the_delivery_is_still_owed(rig, monkeypatch):
    """The source of truth does not wait for the delivery: the issuer-side record is what the delegate's home asks."""
    from agentvault_registry.services import contract_xframe
    from agentvault_registry.services import xreg_issuer_authority as xia

    async def _peer_name(_db, value):
        return "asia" if "asia" in str(value or "") else None
    monkeypatch.setattr(contract_xframe, "resolve_peer_name", _peer_name)
    rig.db.issue()
    rig.state["answers"] = [httpx.ConnectError("down")]
    rig.revoke()
    assert xrd.state_of(rig.db.owed[CRED]) == "retrying"
    from agentvault_registry import agent_authz

    async def _held(_db, did, act_principal=None):
        return {"teg.transfer"}
    monkeypatch.setattr(agent_authz, "resolve_agent_permissions", _held)
    answer = asyncio.run(xia.issuer_answer(rig.db, ISSUER, CRED, "asia"))
    assert answer["credential"] == "revoked"


# ─────────────────────────────── the receiver ───────────────────────────────

def test_the_delegates_registry_takes_a_second_delivery_as_nothing_left_to_revoke(monkeypatch):
    """The retries rely on it: delegation-revoke is idempotent at the delegate's registry."""
    flips = []

    class _RecvDb:
        def __init__(self):
            self.revoked = False

        async def execute(self, stmt, params=None):
            sql = str(stmt)
            if sql.lstrip().startswith("SELECT issuer_did"):
                return _Res(rows=[] if self.revoked else [SimpleNamespace(issuer_did=ISSUER, delegate_did=DELEGATE)])
            if sql.lstrip().startswith("UPDATE agent_delegation_credentials"):
                self.revoked = True
            return _Res()

        async def commit(self):
            pass

    async def _caller(_db, _spiffe):
        return "eu"

    async def _name(_db, value):
        return "eu" if "eu." in str(value or "") else None

    async def _audit(_db, **k):
        return None

    class _Emitter:
        async def emit(self, **k):
            flips.append(("emitter_calls", k["event_type"]))
    import agentvault_registry.event_emitter as em
    from agentvault_registry.services import contract_xframe
    monkeypatch.setattr(deleg, "_caller_peer", _caller)
    monkeypatch.setattr(contract_xframe, "resolve_peer_name", _name)
    monkeypatch.setattr(deleg, "log_ironkey_action", _audit)
    monkeypatch.setattr(deleg, "_notify_delegate_owner", lambda *a, **k: None)
    monkeypatch.setattr(em, "get_event_emitter", lambda: _Emitter())
    db = _RecvDb()
    app = FastAPI()
    app.include_router(deleg.router)
    app.dependency_overrides[get_db] = lambda: db
    from agentvault_registry.core.federation_auth import get_federation_identity
    app.dependency_overrides[get_federation_identity] = lambda: "spiffe://eu.theprotocol.cloud/service/registry"
    c = TestClient(app)
    body = {"credential_id": CRED, "issuer_registry": SELF}
    first = c.post("/federation/ironkey/delegation-revoke", json=body)
    second = c.post("/federation/ironkey/delegation-revoke", json=body)
    assert first.status_code == 200 and first.json() == {"ok": True, "revoked": True}
    assert second.status_code == 200 and second.json() == {"ok": True, "revoked": False,
                                                           "reason": "unknown_or_already_revoked"}
    assert flips.count(("emitter_calls", "AgentXRegDelegationRevoked")) == 1, "a second delivery changes nothing"


# ─────────────────────────────── the pure decision and the wiring ───────────────────────────────

def test_the_decision_after_a_send():
    later = NOW + dt.timedelta(days=30)
    ok = xrd.next_state(1, {"delivered": True, "status": 200}, NOW, budget=40, credential_expires_at=later)
    assert ok == {"attempts": 2, "last_status": 200, "last_error": None, "done_at": NOW}
    for status in (400, 422):
        out = xrd.next_state(0, {"delivered": False, "status": status, "final": True, "error": "no"}, NOW, budget=40,
                             credential_expires_at=later)
        assert out["dead_at"] == NOW and "next_attempt_at" not in out
    waits = []
    for n in range(10):
        out = xrd.next_state(n, {"delivered": False, "status": 503, "error": "x"}, NOW, budget=40,
                             credential_expires_at=later)
        waits.append(int((out["next_attempt_at"] - NOW).total_seconds()))
    assert waits == [60, 300, 900, 3600, 10800, 21600, 43200, 86400, 86400, 86400]
    assert "dead_at" in xrd.next_state(39, {"delivered": False, "error": "x"}, NOW, budget=40, credential_expires_at=later)
    assert xrd.next_state(0, {"delivered": False, "error": "x"}, NOW, budget=40,
                          credential_expires_at=NOW)["last_error"] == xrd.EXPIRED_NOTE


def test_the_worker_runs_with_the_registry_and_the_migration_is_next():
    import inspect
    import pathlib
    from agentvault_registry import main
    m = inspect.getsource(main)
    assert "await get_xreg_revoke_retry().start()" in m and "await get_xreg_revoke_retry().stop()" in m
    versions = pathlib.Path(__file__).resolve().parent.parent / "alembic" / "versions"
    text = (versions / "0194_delivery_xreg_revoke.py").read_text()
    assert 'revision = "0194_delivery_xreg_revoke"' in text
    assert 'down_revision = "0193_bootstrap_plain_scrub"' in text
    assert len("0194_delivery_xreg_revoke") <= 32
    assert "xreg_revokes_owed" in text and 'drop_table("xreg_revokes_owed")' in text
