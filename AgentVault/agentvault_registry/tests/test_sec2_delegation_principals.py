"""D6-270 (2026-10-16): who may act for whom is checked when a delegation grant is written and when it is used.

POST /api/v1/agents/{did}/delegations checked only that the caller controlled the principal: a developer could name
any agent (another developer's included) and any permission in the catalogue, and an organization's owner or admin
could hand out the permissions no organization slice ever carries (authz.delegate, phone.use, teg.system_transfer,
contract.template.publish, ...). An act-token naming that principal then carried them. Now:

  * a `dev:<id>` grant reaches only an agent that developer created, and carries only what the developer may give its
    own agent directly (every role but legacy-full, plus authz.delegate);
  * an `org:` grant never carries the permissions NEVER_IN_ORG_SLICES names;
  * the resolver applies the same rule to rows already written, so an act-token conveys no more than a new grant could.

Through FastAPI on the real routes (POST /agents/{did}/delegations, POST /agents/act-token); only the database, the
audit writer and the event emitter are doubles, and the authenticated developer or agent is supplied.
RED on 7140a4a6: the three write refusals (200 on the base) and test_an_old_cross_owner_grant_conveys_nothing.
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import event_emitter, security
from agentvault_registry.database import get_db
from agentvault_registry.routers import agent_delegation_api as api

OWN_AGENT = "did:theprotocol:sec2:own"
OTHER_AGENT = "did:theprotocol:sec2:other"
OWNER = {OWN_AGENT: 41, OTHER_AGENT: 77}


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _Db:
    """Answers each statement the two routes issue, by what it reads."""

    def __init__(self, grants=(), org_admin=True):
        self.grants, self.org_admin = list(grants), org_admin
        self.inserted = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        p = params or {}
        if sql.startswith("INSERT INTO agent_delegation_grants"):
            self.inserted.append(dict(p))
            return _Result([])
        if "creator_developer_id FROM agents WHERE did" in sql:   # the delegate row (the base reads fewer columns)
            did = p.get("d")
            return _Result([SimpleNamespace(did=did, organization_id=None, creator_developer_id=OWNER.get(did))]
                           if did in OWNER else [])
        if "SELECT did, organization_id FROM agents" in sql:      # the base's delegate read
            did = p.get("d")
            return _Result([SimpleNamespace(did=did, organization_id=None)] if did in OWNER else [])
        if "FROM organization_members" in sql:
            return _Result([(1,)] if self.org_admin else [])
        if "SELECT permissions FROM agent_delegation_grants" in sql:   # the act-token's live-grant read
            rows = [g for g in self.grants if g[2] == p.get("p")]
            return _Result([SimpleNamespace(permissions=rows[0][0])] if rows else [])
        if "FROM agent_delegation_grants" in sql:                        # the resolver's grant read
            return _Result([g for g in self.grants if g[2] == p.get("pref")])
        if "FROM agent_role_grants" in sql:
            return _Result([])
        if "FROM developers WHERE id" in sql:
            return _Result([(False, None, None)])
        if "FROM agents WHERE did = :did AND creator_developer_id" in sql:
            return _Result([(1,)] if OWNER.get(p.get("did")) == p.get("dev") else [])
        if "FROM agents a JOIN organizations" in sql:
            return _Result([(1,)])
        return _Result([])

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def close(self):
        pass


class _Emitter:
    """Records what reaches the ledger emitter (tests/test_doubles_assert_receipt.py: a double asserts receipt)."""

    def __init__(self):
        self.received: list = []

    async def emit(self, **k):
        self.received.append(k)
        return True

    def emit_background(self, **k):
        self.received.append(k)
        return None


EMITTER = _Emitter()


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    async def _audit(*a, **k):
        return None

    EMITTER.received.clear()

    monkeypatch.setattr(api, "log_ironkey_action", _audit)
    monkeypatch.setattr(api, "_notify_delegate_owner", lambda *a, **k: None)
    monkeypatch.setattr(event_emitter, "get_event_emitter", lambda: EMITTER)
    monkeypatch.setenv("AGENT_DELEGATION_MODE", "enforce")


def _as_developer(db, dev_id=41):
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[security.get_current_developer] = lambda: SimpleNamespace(
        id=dev_id, is_admin=False, must_change_password=False)
    return TestClient(app, raise_server_exceptions=False)


def _grant(db, did, principal_type, principal_ref, permissions):
    return _as_developer(db).post(f"/api/v1/agents/{did}/delegations", json={
        "principal_type": principal_type, "principal_ref": principal_ref, "permissions": permissions})


def test_a_developer_cannot_delegate_to_another_developers_agent():
    db = _Db()
    r = _grant(db, OTHER_AGENT, "dev", "dev:41", ["gov.vote"])
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert db.inserted == []
    assert not EMITTER.received, "a refused grant reported an event"


def test_a_developer_cannot_delegate_a_permission_it_cannot_grant():
    db = _Db()
    r = _grant(db, OWN_AGENT, "dev", "dev:41", ["teg.system_transfer", "phone.use"])
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert "teg.system_transfer" in r.text and db.inserted == []


def test_an_organization_never_delegates_the_reserved_permissions():
    db = _Db(org_admin=True)
    r = _grant(db, OWN_AGENT, "org", "org:acme", ["authz.delegate", "teg.transfer"])
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert "authz.delegate" in r.text and db.inserted == []


def test_control_a_developer_delegates_to_its_own_agent():
    db = _Db()
    r = _grant(db, OWN_AGENT, "dev", "dev:41", ["gov.propose", "gov.vote", "authz.delegate"])
    assert r.status_code == 200, (r.status_code, r.text[:300])
    assert db.inserted and db.inserted[0]["pr"] == "dev:41"


def test_control_an_organization_delegates_a_slice_permission():
    db = _Db(org_admin=True)
    r = _grant(db, OWN_AGENT, "org", "org:acme", ["teg.transfer", "teg.transfer_xreg"])
    assert r.status_code == 200, (r.status_code, r.text[:300])


def test_control_the_controller_gate_still_refuses_another_developers_principal():
    r = _grant(_Db(), OWN_AGENT, "dev", "dev:77", ["gov.vote"])
    assert r.status_code == 403, (r.status_code, r.text[:300])


# ── the use side: an act-token over a row written before the write check existed ───────────────────────────────────

def _act_token(db, agent_did, act_as):
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[security.get_current_agent] = lambda: SimpleNamespace(did=agent_did, id=9)
    return TestClient(app, raise_server_exceptions=False).post("/api/v1/agents/act-token", json={"act_as": act_as})


def test_an_old_cross_owner_grant_conveys_nothing():
    """dev:41 wrote a grant onto dev 77's agent before the check: the token it mints carries none of it."""
    db = _Db(grants=[(["teg.system_transfer", "gov.vote"], "dev", "dev:41")])
    r = _act_token(db, OTHER_AGENT, "dev:41")
    assert r.status_code == 200, (r.status_code, r.text[:300])
    eff = set(r.json()["effective_permissions"])
    assert "teg.system_transfer" not in eff and "gov.vote" not in eff, eff


def test_an_old_reserved_permission_on_an_own_agent_is_dropped():
    db = _Db(grants=[(["teg.system_transfer", "gov.vote"], "dev", "dev:41")])
    eff = set(_act_token(db, OWN_AGENT, "dev:41").json()["effective_permissions"])
    assert "gov.vote" in eff and "teg.system_transfer" not in eff, eff


def test_an_old_org_grant_drops_the_reserved_permissions():
    db = _Db(grants=[(["phone.use", "teg.transfer"], "org", "org:acme")])
    eff = set(_act_token(db, OWN_AGENT, "org:acme").json()["effective_permissions"])
    assert "teg.transfer" in eff and "phone.use" not in eff, eff


def test_the_developer_rule_is_what_an_owner_may_grant_directly():
    """The set a developer delegates equals what the access API lets an owner give its own agent."""
    from agentvault_registry.agent_authz import DEV_DELEGATABLE_PERMISSIONS, ROLE_PERMISSIONS
    from agentvault_registry.routers.agent_authz_api import ASSIGNABLE_ROLES, UI_GRANTABLE_PERMISSIONS
    direct = set().union(*(ROLE_PERMISSIONS[r] for r in ASSIGNABLE_ROLES)) | set(UI_GRANTABLE_PERMISSIONS)
    assert set(DEV_DELEGATABLE_PERMISSIONS) == direct
    assert "teg.system_transfer" not in direct and "phone.use" not in direct
