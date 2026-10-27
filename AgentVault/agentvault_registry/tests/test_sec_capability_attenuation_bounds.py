"""D6-522 (2026-10-16): an attenuated capability token is no looser than its parent on the phone axes or in uses.

POST /api/v1/agents/capabilities/{id}/attenuate checks the child's caveats against the parent's with
agent_delegation.caveats_subset_ok, which compared permissions, the money bounds and the scope lists, and ignored every
PHONE FABRIC caveat (the app and network-domain allowlists, the action ceiling, the session lifetime, the no-screenshot
and no-network flags) and the uses bound (`max_uses`, a column of the token). So a holder of a phone token limited to
one app, five actions, no screenshots and no network could derive a child with none of those limits, and a token with
one use left could derive a child with a thousand. Each case marked BASE fails on 7140a4a6.

Through FastAPI on the real route; only the database (the parent read, the child insert) and the agent token are
replaced.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import agent_delegation_api as api
from agentvault_registry.security import get_current_agent

HOLDER = "did:theprotocol:test:holder"


class _Row:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _Session:
    def __init__(self, parent):
        self.parent, self.inserted = parent, 0

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        if sql.startswith("SELECT id, issuer_agent_did"):
            return _Row(self.parent)
        if sql.startswith("INSERT INTO agent_capability_tokens"):
            self.inserted += 1
            return _Row(SimpleNamespace(id=99))
        raise AssertionError(f"unexpected statement: {sql[:80]}")

    async def commit(self):
        pass

    async def rollback(self):
        pass


def _parent(caveats, max_uses=None, uses=0):
    return SimpleNamespace(id=5, issuer_agent_did="did:theprotocol:test:issuer", holder_agent_did=HOLDER,
                           status="active", caveats={"permissions": ["phone.use"], **caveats}, budget_total=None,
                           budget_spent=0, currency=None, depth=0, expires_at=None, max_uses=max_uses, uses=uses)


@pytest.fixture()
def attenuate(monkeypatch):
    async def _no_audit(*a, **k):
        return None
    monkeypatch.setattr(api, "log_ironkey_action", _no_audit)
    from agentvault_registry import event_emitter

    class _Events:
        """Records what the route hands the emitter (emit_background is synchronous on the real one)."""

        def __init__(self):
            self.received = []

        def emit_background(self, *, event_type, aggregate_id, data, idempotency_key=None, **k):
            self.received.append({"event_type": event_type, "idempotency_key": idempotency_key, "data": data})
    events = _Events()
    monkeypatch.setattr(event_emitter, "get_event_emitter", lambda: events)

    def call(parent, child_caveats, **body):
        events.received.clear()
        session = _Session(parent)
        session.events = events
        app = FastAPI()
        register_error_handlers(app)
        app.include_router(api.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[get_current_agent] = lambda: SimpleNamespace(did=HOLDER, id=1)
        r = TestClient(app, raise_server_exceptions=False).post(
            "/api/v1/agents/capabilities/5/attenuate",
            json={"caveats": {"permissions": ["phone.use"], **child_caveats}, "ttl_seconds": 600, **body})
        return r, session
    return call


BOUNDED = {"phone_allowed_apps": ["com.vault.bank"], "phone_allowed_domains": ["bank.example"],
           "phone_max_actions": 5, "phone_ttl_seconds": 120, "phone_no_screenshot": True, "phone_no_network": True}


def test_a_child_within_every_bound_is_made(attenuate):
    r, s = attenuate(_parent(BOUNDED, max_uses=10, uses=4), dict(BOUNDED), max_uses=6)   # control
    assert r.status_code == 200 and s.inserted == 1, r.text
    assert [e["idempotency_key"] for e in s.events.received] == ["cap-attenuated-99"]     # the child is on the ledger
    r, s = attenuate(_parent({}), {"phone_max_actions": 500})          # control: an unbounded parent bounds nothing
    assert r.status_code == 200 and s.inserted == 1, r.text


@pytest.mark.parametrize("change,needle", [
    ({"phone_allowed_apps": ["com.vault.bank", "com.acme.browser"]}, "phone_allowed_apps_exceed_parent"),
    ({"phone_allowed_apps": None}, "phone_allowed_apps_exceed_parent"),
    ({"phone_allowed_domains": ["elsewhere.example"]}, "phone_allowed_domains_exceed_parent"),
    ({"phone_max_actions": 50}, "phone_max_actions_exceeds_parent"),
    ({"phone_max_actions": None}, "phone_max_actions_exceeds_parent"),
    ({"phone_ttl_seconds": 3600}, "phone_ttl_seconds_exceeds_parent"),
    ({"phone_no_screenshot": None}, "phone_no_screenshot_dropped_by_child"),
    ({"phone_no_network": None}, "phone_no_network_dropped_by_child"),
])
def test_a_child_looser_on_a_phone_axis_is_refused(attenuate, change, needle):
    child = {k: v for k, v in {**BOUNDED, **change}.items() if v is not None}
    r, s = attenuate(_parent(BOUNDED), child)
    assert r.status_code == 422 and needle in r.text and s.inserted == 0, (change, r.status_code, r.text)   # BASE: 200
    assert s.events.received == []      # a refused child is announced nowhere


@pytest.mark.parametrize("child_uses,want", [
    (1, 200),        # control: within the one use the parent has left
    (2, 422),        # BASE: 200 (more uses than the parent has left)
    (None, 422),     # BASE: 200 (no bound at all under a bounded parent)
])
def test_the_uses_bound(attenuate, child_uses, want):
    body = {} if child_uses is None else {"max_uses": child_uses}
    r, s = attenuate(_parent({}, max_uses=5, uses=4), {}, **body)
    assert r.status_code == want, (child_uses, r.status_code, r.text)
    assert (s.inserted == 1) == (want == 200)
    if want == 422:
        assert "max_uses_exceeds_parent" in r.text
