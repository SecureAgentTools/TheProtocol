"""§TWOAGENT #18 (2026-09-23) — the chat routes' dual-principal resolver refuses what every other developer route
refuses.

Measured live on EU before the change, with one developer: login, then POST /auth/logout (token_version bumped), then
the SAME JWT: GET /developers/me 401 (control), GET /chat/conversations 200, POST /chat/conversations 201. The cause was
`get_current_actor_for_read`'s developer branch, which decoded the JWT itself and checked only that the developer
existed, skipping the `tv` claim, the refresh and password-set token types, and a deleted, suspended or anonymized
account. Its OPTIONAL twin already delegated to `verify_access_token_optional_claims` + `get_current_developer_optional`;
the required one now does the same and turns their "no identity" into the 401 it always raised.

RED on the pre-change tree: every refusal below answered 200 there (the control and the agent leg pass on both).
"""
from __future__ import annotations

import types

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security


def _dev(**kw):
    base = dict(id=7, name="d", email="d@x", token_version=1, deleted_at=None, is_suspended=False,
                deletion_status=None, is_active=True)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _client(monkeypatch, dev=None, agent=None):
    async def _get_dev(db, developer_id):
        return dev if dev is not None and developer_id == dev.id else None

    async def _get_agent(db, did):
        return agent if agent is not None and did == agent.did else None
    monkeypatch.setattr(security.developer_crud, "get_developer_by_id_lean", _get_dev)  # V0553: the optional actor reads the developer's own row (crud get_developer_by_id_lean)
    monkeypatch.setattr(security.agent_crud, "get_agent_by_did", _get_agent)

    async def _no_db():
        yield None
    app = FastAPI()
    app.dependency_overrides[security.get_db] = _no_db

    @app.get("/actor")
    async def actor(a=Depends(security.get_current_actor_for_read)):
        if a["kind"] == "developer":
            return {"kind": "developer", "id": a["developer"].id}
        return {"kind": "agent", "did": a["agent_did"]}
    return TestClient(app)


def _get(c, token):
    r = c.get("/actor", headers={"Authorization": f"Bearer {token}"})
    return r.status_code, r.json()


def test_a_live_developer_token_is_the_developer(monkeypatch):
    c = _client(monkeypatch, dev=_dev())
    assert _get(c, security.create_access_token({"sub": "7"}, token_version=1)) == (200, {"kind": "developer", "id": 7})
    # a token minted before token_version existed (no tv claim) is grandfathered, exactly as the required path does
    assert _get(c, security.create_access_token({"sub": "7"}))[0] == 200


def test_a_token_revoked_by_logout_is_refused(monkeypatch):
    c = _client(monkeypatch, dev=_dev(token_version=2))          # logout / password change bumped it after minting
    assert _get(c, security.create_access_token({"sub": "7"}, token_version=1))[0] == 401


@pytest.mark.parametrize("state", [dict(is_suspended=True), dict(deleted_at="2026-09-23"),
                                   dict(deletion_status="anonymized")])
def test_a_suspended_deleted_or_anonymized_developer_is_refused(monkeypatch, state):
    c = _client(monkeypatch, dev=_dev(**state))
    assert _get(c, security.create_access_token({"sub": "7"}, token_version=1))[0] == 401


def test_a_refresh_token_is_not_an_access_token(monkeypatch):
    c = _client(monkeypatch, dev=_dev())
    assert _get(c, security.create_refresh_token(7, token_version=1))[0] == 401


def test_a_password_set_token_is_not_an_access_token(monkeypatch):
    c = _client(monkeypatch, dev=_dev())
    assert _get(c, security.create_access_token({"sub": "7", "purpose": "password-set"}, token_version=1))[0] == 401


def test_an_inactive_developer_keeps_its_403(monkeypatch):
    c = _client(monkeypatch, dev=_dev(is_active=False))
    assert _get(c, security.create_access_token({"sub": "7"}, token_version=1))[0] == 403


def test_the_agent_path_is_unchanged(monkeypatch):
    agent = types.SimpleNamespace(did="did:theprotocol:eu.test:aaaa", status="active", id=3)
    c = _client(monkeypatch, agent=agent)
    tok = security.jwt.encode({"sub": agent.did, "agent_id": "3", "type": "agent", "exp": 4102444800},
                              security.SECRET_KEY, algorithm=security.ALGORITHM)
    assert _get(c, tok) == (200, {"kind": "agent", "did": agent.did})
    agent.status = "suspended"
    assert _get(c, tok)[0] == 403


def test_the_required_resolver_delegates_to_the_shared_checks():
    """Structural pin: the developer branch asks the same two helpers as its optional twin (one place for the rules)."""
    import inspect
    src = inspect.getsource(security.get_current_actor_for_read)
    assert "verify_access_token_optional_claims(" in src and "get_current_developer_optional(" in src
