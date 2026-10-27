"""SEC-09 (2026-10-17): a capability token derived by attenuation never holds more than its parent, budget and phone
session lifetime included.

POST /api/v1/agents/capabilities/{id}/attenuate compared a child's budget with what its parent had left only when the
child named one: a child that named none was written with no budget at all, an unbounded child of a budgeted parent
(the console, the SDK, the federation suite and the sim all derive children without naming a budget). The child now
takes the parent's remainder, as a lifetime past the parent's takes the parent's expiry; one naming more is refused.

The phone session lifetime had the same shape one step later: attenuation reads `phone_ttl_seconds: 0` as within any
bound, and POST /api/v1/phone/sessions read 0 as absent and gave the session the registry default. Only an absent
lifetime takes the default now, and a lifetime of 0 or less opens no session.

Each case marked BASE fails on 15620967. Through FastAPI on the real routes; only the database, the agent token, the
capability resolution (the phone route) and the audit writer are replaced.
"""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import agent_delegation_api as api
from agentvault_registry.routers import phone_fabric as pf
from agentvault_registry.security import get_current_agent

HOLDER = "did:theprotocol:test:holder"
PHONE_AGENT = "did:theprotocol:test:phone-agent"


class _Result:
    def __init__(self, first=None, scalar=0):
        self._first, self._scalar = first, scalar

    def first(self):
        return self._first

    def scalar(self):
        return self._scalar


# ── the attenuate route ──────────────────────────────────────────────────────
class _TokenSession:
    """The attenuate route's statements: the parent read, the child insert (its parameters recorded)."""

    def __init__(self, parent):
        self.parent, self.inserted = parent, []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        if sql.startswith("SELECT id, issuer_agent_did"):
            return _Result(first=self.parent)
        if sql.startswith("INSERT INTO agent_capability_tokens"):
            self.inserted.append(dict(params or {}))
            return _Result(first=SimpleNamespace(id=99))
        raise AssertionError(f"unexpected statement: {sql[:80]}")

    async def commit(self):
        pass

    async def rollback(self):
        pass


def _parent(budget_total=None, budget_spent=0, caveats=None):
    return SimpleNamespace(id=5, issuer_agent_did="did:theprotocol:test:issuer", holder_agent_did=HOLDER,
                           status="active", caveats={"permissions": ["teg.transfer"], **(caveats or {})},
                           budget_total=budget_total, budget_spent=budget_spent, currency="ECU", depth=0,
                           expires_at=None, max_uses=None, uses=0)


@pytest.fixture()
def attenuate(monkeypatch):
    async def _no_audit(*a, **k):
        return None
    monkeypatch.setattr(api, "log_ironkey_action", _no_audit)
    from agentvault_registry import event_emitter

    class _Events:
        def __init__(self):
            self.received = []

        def emit_background(self, *, event_type, aggregate_id, data, idempotency_key=None, **k):
            self.received.append({"event_type": event_type, "data": data})
    events = _Events()
    monkeypatch.setattr(event_emitter, "get_event_emitter", lambda: events)

    def call(parent, raw=None, **body):
        events.received.clear()
        session = _TokenSession(parent)
        app = FastAPI()
        register_error_handlers(app)
        app.include_router(api.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[get_current_agent] = lambda: SimpleNamespace(did=HOLDER, id=1)
        client = TestClient(app, raise_server_exceptions=False)
        url = "/api/v1/agents/capabilities/5/attenuate"
        if raw is not None:   # a body JSON tools refuse to write (NaN)
            r = client.post(url, content=raw, headers={"Content-Type": "application/json"})
        else:
            r = client.post(url, json={"caveats": {"permissions": ["teg.transfer"]}, "ttl_seconds": 600, **body})
        return r, session, events
    return call


def test_a_child_naming_no_budget_takes_what_its_parent_has_left(attenuate):
    r, s, events = attenuate(_parent(budget_total=100, budget_spent=40))
    assert r.status_code == 200, r.text
    assert len(s.inserted) == 1 and s.inserted[0]["bt"] == Decimal("60"), s.inserted   # BASE: None, no budget at all
    assert r.json()["budget_total"] == 60.0, r.json()                                     # the answer says so
    assert [e["data"]["budget_total"] for e in events.received] == [60.0], events.received   # and so does the ledger


def test_a_child_of_a_spent_parent_is_born_spent(attenuate):
    r, s, _ = attenuate(_parent(budget_total=100, budget_spent=100))
    assert r.status_code == 200 and s.inserted[0]["bt"] == Decimal("0"), (r.text, s.inserted)   # BASE: None


@pytest.mark.parametrize("parent,child,want", [
    (_parent(budget_total=100, budget_spent=40), 50, Decimal("50")),   # control: a named budget within the remainder
    (_parent(budget_total=100, budget_spent=40), 60, Decimal("60")),   # control: exactly the remainder
    (_parent(), None, None),                                             # control: an unbudgeted parent bounds nothing
    (_parent(), 5, Decimal("5")),                                        # control
])
def test_a_budget_within_the_parent_is_written_as_named(attenuate, parent, child, want):
    body = {} if child is None else {"budget_total": child}
    r, s, _ = attenuate(parent, **body)
    assert r.status_code == 200 and len(s.inserted) == 1, r.text
    assert (s.inserted[0]["bt"] is None) if want is None else (Decimal(str(s.inserted[0]["bt"])) == want), s.inserted


def test_a_budget_over_the_remainder_is_refused(attenuate):
    r, s, events = attenuate(_parent(budget_total=100, budget_spent=40), budget_total=61)
    assert r.status_code == 422 and s.inserted == [] and events.received == [], r.text   # control: refused on the base too
    assert "budget_total_exceeds_parent" in r.text, r.text   # the axis named, as on every other one (BASE: a sentence)


@pytest.mark.parametrize("parent", [_parent(budget_total=100), _parent()])
def test_a_budget_that_is_not_a_number_is_refused(attenuate, parent):
    raw = b'{"caveats": {"permissions": ["teg.transfer"]}, "ttl_seconds": 600, "budget_total": NaN}'
    r, s, _ = attenuate(parent, raw=raw)
    assert r.status_code == 422 and "budget_total_not_a_number" in r.text and s.inserted == [], r.text   # BASE: 500 / 200


def test_the_other_axes_still_bind(attenuate):
    # control: the budget rule runs after the caveat and uses checks, which still refuse a looser child first
    r, s, _ = attenuate(_parent(budget_total=100, caveats={"max_per_tx": "5"}),
                        caveats={"permissions": ["teg.transfer"], "max_per_tx": 9})
    assert r.status_code == 422 and "max_per_tx_exceeds_parent" in r.text and s.inserted == [], r.text


# ── the phone session lifetime ───────────────────────────────────────────────
class _PhoneSession:
    """POST /api/v1/phone/sessions' statements; records the session rows it writes (their expiry)."""

    def __init__(self):
        self.sessions, self.leases = [], 0

    async def execute(self, stmt, params=None):
        sql, p = " ".join(str(stmt).split()), dict(params or {})
        if sql.startswith("SELECT count(*) FROM phone_sessions"):
            return _Result(scalar=0)
        if sql.startswith("INSERT INTO phone_pool_instances"):
            self.leases += 1
            return _Result(first=SimpleNamespace(id=3))
        if sql.startswith("INSERT INTO phone_sessions"):
            self.sessions.append(p)
            return _Result()
        if sql.startswith("SELECT COALESCE(MAX(seq)"):
            return _Result(scalar=0)
        return _Result()

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.fixture()
def phone(monkeypatch):
    monkeypatch.setenv("PHONE_FABRIC_ENABLED", "true")
    monkeypatch.setenv("PHONE_FABRIC_BACKEND", "mock")
    monkeypatch.delenv("PHONE_SESSION_TTL_DEFAULT", raising=False)
    monkeypatch.setattr(pf, "_emit_push", lambda *a, **k: None)
    state = {"caveats": {}}

    async def _cap(db, token, agent_did):
        return {"id": 11, "permissions": {"phone.use"}, "caveats": {"permissions": ["phone.use"], **state["caveats"]},
                "budget_remaining": None, "currency": None}
    monkeypatch.setattr(pf, "_resolve_phone_cap", _cap)

    def start(caveats):
        state["caveats"] = caveats
        session = _PhoneSession()
        app = FastAPI()
        register_error_handlers(app)
        app.include_router(pf.router)
        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[get_current_agent] = lambda: SimpleNamespace(did=PHONE_AGENT, id=1)
        before = _dt.datetime.now(_dt.timezone.utc)
        r = TestClient(app, raise_server_exceptions=False).post(
            "/api/v1/phone/sessions", json={}, headers={"Authorization": "Bearer agent-token",
                                                        "X-Capability-Token": "att_test"})
        return r, session, before
    return start


@pytest.mark.parametrize("caveats,lifetime", [
    ({}, 600),                          # control: no lifetime named, the registry default
    ({"phone_ttl_seconds": 30}, 30),    # control: a named lifetime
])
def test_a_named_or_absent_lifetime_is_the_sessions(phone, caveats, lifetime):
    r, s, before = phone(caveats)
    assert r.status_code == 200 and len(s.sessions) == 1, r.text
    secs = (s.sessions[0]["exp"] - before).total_seconds()
    assert lifetime - 5 <= secs <= lifetime + 5, secs


@pytest.mark.parametrize("ttl", [0, -30])
def test_a_lifetime_of_zero_or_less_opens_no_session(phone, ttl):
    r, s, _ = phone({"phone_ttl_seconds": ttl})
    assert r.status_code == 403 and "phone_ttl_seconds" in r.text, r.text   # BASE: 200 (0: a 600 s session)
    assert s.sessions == [] and s.leases == 0, (s.sessions, s.leases)
