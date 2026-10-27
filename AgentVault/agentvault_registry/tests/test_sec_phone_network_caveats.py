"""D6-523 (2026-10-16): the Phone Fabric session routes enforce phone_no_network and phone_allowed_domains.

A capability token can carry both caveats (routers/agent_delegation_api.CaveatsIn) and the registry stored them, but no
session route read them: a token issued "no network" leased a device and loaded pages like any other. Now an action is
asked of the device before it runs (the driver's network_use): under phone_no_network an action that would reach the
network is refused and recorded (network_blocked); under phone_allowed_domains an action reaching an address not on the
list, or one the device cannot name, is refused and recorded (domain_not_allowed:<host>). A backend that cannot report
its network use (redroid) opens no session for a token carrying either caveat. Each case marked BASE fails on 7140a4a6.

Through FastAPI on the real routes (POST /api/v1/phone/sessions, POST /api/v1/phone/sessions/{id}/act), the scripted
mock device behind them; only the database, the capability-token resolution and the agent token are replaced.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import phone_fabric as pf
from agentvault_registry.security import get_current_agent

AGENT = "did:theprotocol:test:phone-agent"
SID = "pfs_test"


class _Result:
    def __init__(self, first=None, scalar=0):
        self._first, self._scalar = first, scalar

    def first(self):
        return self._first

    def mappings(self):
        return self

    def scalar(self):
        return self._scalar


class _Session:
    """The session routes' statements, answered from one session row; records the trace rows and the state writes."""

    def __init__(self, app=None, screen=None):
        self.row = {"id": SID, "agent_did": AGENT, "capability_token_id": 11, "backend": "mock", "instance_id": 3,
                    "status": "active", "allowed_apps": [], "max_actions": None, "actions_used": 0,
                    "no_screenshot": False, "budget_currency": None, "current_app": app, "current_screen": screen,
                    "expires_at": None}
        self.trace, self.moves, self.sessions = [], 0, 0

    async def execute(self, stmt, params=None):
        sql, p = " ".join(str(stmt).split()), dict(params or {})
        if sql.startswith("SELECT count(*) FROM phone_sessions"):
            return _Result(scalar=0)
        if sql.startswith("INSERT INTO phone_pool_instances"):
            return _Result(first=SimpleNamespace(id=3))
        if sql.startswith("INSERT INTO phone_sessions"):
            self.sessions += 1
            return _Result()
        if sql.startswith("INSERT INTO phone_session_actions"):
            self.trace.append((p.get("at"), p.get("oc"), p.get("dt")))
            return _Result()
        if sql.startswith("SELECT id, agent_did, capability_token_id"):
            return _Result(first=self.row)
        if sql.startswith("SELECT status, expires_at <= now()"):
            return _Result(first=SimpleNamespace(status="active", expired=False))
        if sql.startswith("UPDATE phone_sessions SET actions_used"):
            self.moves += 1
        return _Result()

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.fixture()
def phone(monkeypatch):
    monkeypatch.setenv("PHONE_FABRIC_ENABLED", "true")
    monkeypatch.setenv("PHONE_FABRIC_BACKEND", "mock")
    monkeypatch.setattr(pf, "_emit_push", lambda *a, **k: None)
    state = {"caveats": {}}

    async def _cap(db, token, agent_did):
        return {"id": 11, "permissions": {"phone.use"}, "caveats": {"permissions": ["phone.use"], **state["caveats"]},
                "budget_remaining": None, "currency": None}
    monkeypatch.setattr(pf, "_resolve_phone_cap", _cap)

    def client(session):
        app = FastAPI()
        register_error_handlers(app)
        app.include_router(pf.router)
        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[get_current_agent] = lambda: SimpleNamespace(did=AGENT, id=1)
        return TestClient(app, raise_server_exceptions=False)
    return state, client


H = {"Authorization": "Bearer agent-token", "X-Capability-Token": "att_test"}


def _go(client):
    return client.post(f"/api/v1/phone/sessions/{SID}/act", json={"type": "tap", "target": "go"}, headers=H)


def test_a_page_load_without_network_caveats_runs(phone):
    state, client = phone
    s = _Session("com.acme.browser", "home")
    r = _go(client(s))
    assert r.status_code == 200 and r.json()["screen"] == "page" and s.moves == 1, r.text   # control


def test_no_network_refuses_the_page_load_and_records_it(phone):
    state, client = phone
    state["caveats"] = {"phone_no_network": True}
    s = _Session("com.acme.browser", "home")
    r = _go(client(s))
    assert r.status_code == 403 and "phone_no_network" in r.text, r.text     # BASE: 200, the page loaded
    assert s.moves == 0 and s.trace == [("tap", "denied", "network_blocked")], s.trace


def test_no_network_leaves_actions_that_reach_no_network(phone):
    state, client = phone
    state["caveats"] = {"phone_no_network": True}
    s = _Session(None, None)   # at the home screen: opening the browser loads nothing
    r = client(s).post(f"/api/v1/phone/sessions/{SID}/act", json={"type": "tap", "target": "icon:com.acme.browser"},
                       headers=H)
    assert r.status_code == 200 and r.json()["package"] == "com.acme.browser", r.text   # control


def test_an_address_the_device_cannot_name_is_off_any_list(phone):
    state, client = phone
    state["caveats"] = {"phone_allowed_domains": ["example.com"]}
    s = _Session("com.acme.browser", "home")
    r = _go(client(s))
    assert r.status_code == 403 and "phone_allowed_domains" in r.text, r.text   # BASE: 200
    assert s.moves == 0 and s.trace == [("tap", "denied", "domain_not_allowed:unknown")], s.trace


def test_the_domain_check_reads_the_host_the_device_names(phone, monkeypatch):
    state, client = phone
    state["caveats"] = {"phone_allowed_domains": ["Example.com."]}
    from agentvault_registry.services.phone import mock_driver
    monkeypatch.setattr(mock_driver.MockPhoneDriver, "network_use", lambda self, at, target=None, text=None: "example.com",
                        raising=False)
    s = _Session("com.acme.browser", "home")
    assert _go(client(s)).status_code == 200                                              # control: on the list
    monkeypatch.setattr(mock_driver.MockPhoneDriver, "network_use", lambda self, at, target=None, text=None: "evil.test",
                        raising=False)
    s = _Session("com.acme.browser", "home")
    r = _go(client(s))
    assert r.status_code == 403 and s.trace == [("tap", "denied", "domain_not_allowed:evil.test")], r.text


@pytest.mark.parametrize("backend,caveats,want", [
    ("mock", {"phone_no_network": True}, 200),          # control: the mock device reports its network use
    ("redroid", {}, 200),                               # control: no network caveat, any backend
    ("redroid", {"phone_no_network": True}, 403),       # BASE: 200 (leased a device that cannot apply it)
    ("redroid", {"phone_allowed_domains": ["example.com"]}, 403),   # BASE: 200
])
def test_a_backend_that_cannot_report_its_network_use_opens_no_limited_session(phone, monkeypatch, backend, caveats,
                                                                               want):
    state, client = phone
    monkeypatch.setenv("PHONE_FABRIC_BACKEND", backend)
    state["caveats"] = caveats
    from agentvault_registry.services.phone import redroid_driver

    async def _offline(self, *a, **k):
        raise RuntimeError("no device host in a test")
    monkeypatch.setattr(redroid_driver.RedroidPhoneDriver, "_call", _offline)
    s = _Session()
    r = client(s).post("/api/v1/phone/sessions", json={}, headers=H)
    assert r.status_code == want, (backend, caveats, r.status_code, r.text)
    assert s.sessions == (1 if want == 200 else 0)
