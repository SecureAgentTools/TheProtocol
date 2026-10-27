"""SEC-11 (2026-10-17): the two reads the console's Access panel builds its delegation forms from.

GET /api/v1/agents/authz/catalog serves, per principal type, what a delegation grant may carry
(`delegatable_permissions`). The panel's grant form offered every catalogue permission while POST
/api/v1/agents/{did}/delegations refuses the ones a developer or an organization may not hand out (D6-270); the served
sets are the ones that route applies, checked here permission by permission through the route itself.

GET /api/v1/agents/{did}/capabilities carries each token's caveats and uses bound beside its permissions, so the
attenuate form can start from the parent's own limits (a child must stay within every one of them).

Each case marked BASE fails on 15620967. Through FastAPI on the real routes; only the database, the audit writer, the
event emitter, the owner notice and the signed-in developer are replaced.
"""
from __future__ import annotations

import datetime as _dt
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import event_emitter, security
from agentvault_registry.agent_authz import ALL_PERMISSIONS
from agentvault_registry.database import get_db
from agentvault_registry.routers import agent_authz_api as authz_api
from agentvault_registry.routers import agent_delegation_api as deleg_api

ME = 41
AGENT = "did:theprotocol:sec11:own"


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _Db:
    """Answers the grant route's and the token list's statements; records the grants written."""

    def __init__(self, tokens=()):
        self.tokens, self.inserted = list(tokens), []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        if sql.startswith("INSERT INTO agent_delegation_grants"):
            self.inserted.append(dict(params or {}))
            return _Result([])
        if "creator_developer_id FROM agents WHERE did" in sql:
            return _Result([SimpleNamespace(did=AGENT, organization_id=None, creator_developer_id=ME)])
        if "FROM organization_members" in sql:
            return _Result([(1,)])
        if "FROM agent_capability_tokens" in sql:
            return _Result(self.tokens)
        raise AssertionError(f"unexpected statement: {sql[:80]}")

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _Emitter:
    def __init__(self):
        self.received: list = []

    async def emit(self, **k):
        self.received.append(k)

    def emit_background(self, **k):
        self.received.append(k)


@pytest.fixture()
def emitter(monkeypatch):
    async def _audit(*a, **k):
        return None
    e = _Emitter()
    monkeypatch.setattr(deleg_api, "log_ironkey_action", _audit)
    monkeypatch.setattr(deleg_api, "_notify_delegate_owner", lambda *a, **k: None)
    monkeypatch.setattr(event_emitter, "get_event_emitter", lambda: e)
    return e


def _client(router, db=None):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db or _Db()
    app.dependency_overrides[security.get_current_developer] = lambda: SimpleNamespace(
        id=ME, is_admin=False, must_change_password=False)
    return TestClient(app, raise_server_exceptions=False)


def _served():
    r = _client(authz_api.router).get("/api/v1/agents/authz/catalog")
    assert r.status_code == 200, r.text
    return r.json().get("delegatable_permissions")


def test_the_catalog_serves_what_each_principal_may_grant():
    served = _served()
    assert isinstance(served, dict), served   # BASE: absent
    dev, org = set(served["dev"]), set(served["org"])
    assert {"gov.vote", "teg.transfer", "authz.delegate"} <= dev
    assert not dev & {"teg.system_transfer", "phone.use", "contract.template.publish", "guild.bid_for_org",
                      "forge.evolve_for_org", "cicd.deploy"}, dev
    assert {"teg.transfer", "guild.bid_for_org", "forge.evolve_for_org"} <= org   # the org-consent ones are an org's
    assert not org & {"authz.delegate", "phone.use", "teg.system_transfer", "contract.template.publish"}, org
    assert set(served["agent"]) == set(ALL_PERMISSIONS)   # an admin-only principal is bounded when the grant is used


@pytest.mark.parametrize("ptype,ref", [("dev", f"dev:{ME}"), ("org", "org:acme")])
def test_what_the_catalog_offers_is_exactly_what_the_grant_route_takes(emitter, ptype, ref):
    taken = set()
    for p in sorted(ALL_PERMISSIONS):
        db = _Db()
        r = _client(deleg_api.router, db).post(f"/api/v1/agents/{AGENT}/delegations", json={
            "principal_type": ptype, "principal_ref": ref, "permissions": [p]})
        assert r.status_code in (200, 403), (p, r.status_code, r.text[:200])
        assert (r.status_code == 200) == (len(db.inserted) == 1), (p, db.inserted)
        if r.status_code == 200:
            taken.add(p)
    assert taken and taken != set(ALL_PERMISSIONS), taken          # control: the route refuses some, takes some
    assert [e["event_type"] for e in emitter.received].count("AgentDelegationGranted") == len(taken)
    served = _served()
    assert served is not None and set(served[ptype]) == taken, (ptype, sorted(taken))   # BASE: nothing served


def test_the_token_list_carries_each_tokens_limits():
    exp = _dt.datetime(2026, 10, 18, tzinfo=_dt.timezone.utc)
    tokens = [
        SimpleNamespace(id=7, issuer_agent_did="did:theprotocol:sec11:boss", holder_agent_did=AGENT, parent_token_id=None,
                        depth=0, caveats={"permissions": ["phone.use"], "phone_allowed_apps": ["com.vault.bank"],
                                          "phone_max_actions": 5, "phone_no_screenshot": True},
                        budget_total=100, budget_spent=40, currency="ECU", max_uses=5, uses=2, status="active",
                        created_at=exp, expires_at=exp),
        SimpleNamespace(id=8, issuer_agent_did=AGENT, holder_agent_did=None, parent_token_id=None, depth=0,
                        caveats={"permissions": ["teg.transfer"]}, budget_total=None, budget_spent=0, currency=None,
                        max_uses=None, uses=0, status="issued", created_at=exp, expires_at=exp),
    ]
    r = _client(deleg_api.router, _Db(tokens)).get(f"/api/v1/agents/{AGENT}/capabilities")
    assert r.status_code == 200, r.text
    got = {t["id"]: t for t in r.json()["tokens"]}
    assert got[7].get("caveats", {}).get("phone_allowed_apps") == ["com.vault.bank"], got[7]   # BASE: no caveats
    assert got[7]["caveats"]["phone_no_screenshot"] is True and got[7]["caveats"]["phone_max_actions"] == 5
    assert (got[7].get("max_uses"), got[7].get("uses_left")) == (5, 3), got[7]                  # BASE: absent
    assert (got[8].get("max_uses"), got[8].get("uses_left")) == (None, None) and "max_uses" in got[8], got[8]
    assert got[7]["permissions"] == ["phone.use"] and got[7]["budget_remaining"] == 60.0       # control: unchanged
