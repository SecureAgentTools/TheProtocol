"""§TWOAGENT (2026-09-23) — a suspended agent that proves its secret is told it is suspended.

Measured on ASIA (V0426) during the S7 suspension: the agent's OWN, correct client credentials answered
`POST /api/v1/auth/agent/token` 401 "Invalid client credentials", word for word what a wrong secret gets. Its runtime
could not tell "I was suspended" from "my secret broke" and, like any client that sees a 401, it retries. The cause:
`crud/agent.verify_agent_credentials` checked the status BEFORE the secret and returned None for both.

Now the secret is checked first; a caller that proves it and is suspended (or revoked) gets a 403 that says so. A
caller that does NOT prove the secret still gets the plain 401 whatever the agent's status, so a client_id alone cannot
probe whether an agent is suspended.

RED on V0429: the suspended agent with a correct secret gets 401 "Invalid client credentials" and
`agent_credentials_status` does not exist. The controls (a wrong secret on a suspended agent is a plain 401; an active
agent with a correct secret gets a token) pass on both trees.
"""
from __future__ import annotations

import types

import pytest
from fastapi import HTTPException

from agentvault_registry import security
from agentvault_registry.crud import agent as agent_crud
from agentvault_registry.routers import auth_secure

SECRET = "tp_test_not_a_real_secret_0001"
_HASH = security.hash_password(SECRET)


def _agent(status):
    return types.SimpleNamespace(id=42, did="did:theprotocol:asia.test:s7", client_id="cid-s7", status=status,
                                 hashed_client_secret=_HASH)


def _wire(monkeypatch, status):
    async def _by_client_id(db, client_id):
        return _agent(status) if client_id == "cid-s7" else None

    async def _seen(db, agent_id):
        return None
    monkeypatch.setattr(agent_crud, "get_agent_by_client_id", _by_client_id)
    monkeypatch.setattr(agent_crud, "update_agent_last_active", _seen)


async def _token(secret):
    form = types.SimpleNamespace(username="cid-s7", password=secret)
    return await auth_secure.agent_token(form_data=form, db=None)


async def test_a_suspended_agent_with_its_secret_is_told_it_is_suspended(monkeypatch):
    _wire(monkeypatch, "suspended")
    with pytest.raises(HTTPException) as e:
        await _token(SECRET)
    assert e.value.status_code == 403 and "suspended" in str(e.value.detail), (e.value.status_code, e.value.detail)


async def test_a_revoked_agent_with_its_secret_is_told_it_is_revoked(monkeypatch):
    _wire(monkeypatch, "revoked")
    with pytest.raises(HTTPException) as e:
        await _token(SECRET)
    assert e.value.status_code == 403 and "revoked" in str(e.value.detail), (e.value.status_code, e.value.detail)


async def test_control_a_wrong_secret_learns_nothing_about_the_status(monkeypatch):
    _wire(monkeypatch, "suspended")
    with pytest.raises(HTTPException) as e:
        await _token("not-the-secret")
    assert e.value.status_code == 401 and e.value.detail == "Invalid client credentials"


async def test_control_an_active_agent_gets_its_token(monkeypatch):
    _wire(monkeypatch, "active")
    tok = await _token(SECRET)
    assert tok.access_token and tok.token_type == "bearer"


async def test_control_verify_agent_credentials_keeps_its_contract(monkeypatch):
    _wire(monkeypatch, "suspended")
    assert await agent_crud.verify_agent_credentials(None, "cid-s7", SECRET) is None
    _wire(monkeypatch, "active")
    assert (await agent_crud.verify_agent_credentials(None, "cid-s7", SECRET)).did == "did:theprotocol:asia.test:s7"
