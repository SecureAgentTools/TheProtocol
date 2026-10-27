"""D6-281 (2026-10-16): an agent token minted before a credential reset stops working at the reset.

POST /onboard/agents/{did}/reset-credentials (and the admin's rotate-credentials) replaced the agent's client secret,
and its description says the old credentials stop at once; but a token already minted from them lived to its expiry
(90 minutes by default): agent JWTs carried no version to compare. Now a token minted from the agent's credential
(POST /auth/agent/token, an act token) carries `cv`, a fingerprint of the stored secret hash, and every path that
admits an agent JWT asks security.agent_token_refusal, which refuses it once the credential has changed: the agent
routes (security.get_current_agent and routers/utils.get_current_agent), the read-actor resolvers (here through the
agent-log writer, which decoded the token alone before) and the MCP bridge. An owner session token, bound to its
owner's session instead, is unaffected. Each case marked BASE fails on 7140a4a6.

Through FastAPI on the real routes (POST /api/v1/auth/agent/token, GET /api/v1/agents/capabilities/mine,
POST /api/v1/agents/{did}/logs, POST /mcp/rpc); only the database is replaced (the agent row the reset rewrites, the
capability and log rows).
"""
from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.crud import agent as agent_crud
from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers

DID = "did:theprotocol:test:3f1c0e8e-0000-4000-8000-000000000007"
OLD, NEW = "old-secret-" + "a" * 24, "new-secret-" + "b" * 24


class _Rows:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Session:
    def __init__(self):
        self.logs = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        if "FROM agent_capability_tokens" in sql:
            return _Rows()
        if "FROM developers" in sql:     # an owner token's one read: the owner's session is live
            return _Rows([(3, False, None, None)])
        raise AssertionError(f"unexpected statement: {sql[:90]}")

    def add(self, obj):
        self.logs.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        obj.id = len(self.logs)

    async def rollback(self):
        pass


@pytest.fixture()
def world(monkeypatch):
    agent = SimpleNamespace(id=7, did=DID, client_id="cid-old", hashed_client_secret=security.hash_password(OLD),
                            status="active", enforcement_status="active", creator_developer_id=42)

    async def _by_client_id(db, client_id):
        return agent if client_id == agent.client_id else None

    async def _by_did(db, did):
        return agent if did == agent.did else None

    async def _touch(*a, **k):
        return None
    monkeypatch.setattr(agent_crud, "get_agent_by_client_id", _by_client_id)
    monkeypatch.setattr(agent_crud, "get_agent_by_did", _by_did)
    monkeypatch.setattr(agent_crud, "update_agent_last_active", _touch)

    from agentvault_registry.routers import agent_delegation_api, agent_logs, auth_secure
    session = _Session()
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(auth_secure.router, prefix="/api/v1")
    app.include_router(agent_delegation_api.router, prefix="/api/v1")
    app.include_router(agent_logs.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app, raise_server_exceptions=False)

    def mint(client_id, secret):
        r = client.post("/api/v1/auth/agent/token", data={"username": client_id, "password": secret})
        return r.json().get("access_token") if r.status_code == 200 else r.status_code

    def reset():
        """What POST /onboard/agents/{did}/reset-credentials commits (routers/onboarding.py, step 6)."""
        agent.client_id, agent.hashed_client_secret = "cid-new", security.hash_password(NEW)

    return SimpleNamespace(agent=agent, client=client, session=session, mint=mint, reset=reset)


def _mine(w, token):
    return w.client.get("/api/v1/agents/capabilities/mine", headers={"Authorization": f"Bearer {token}"}).status_code


def _log(w, token):
    return w.client.post(f"/api/v1/agents/{DID}/logs", json={"level": "INFO", "message": "hello"},
                         headers={"Authorization": f"Bearer {token}"}).status_code


def test_a_token_from_the_old_credential_ends_at_the_reset(world):
    old = world.mint("cid-old", OLD)
    assert isinstance(old, str) and _mine(world, old) == 200            # control: the token works before the reset
    world.reset()
    assert world.mint("cid-old", OLD) == 401                             # control: the old pair stops (both trees)
    r = world.client.get("/api/v1/agents/capabilities/mine", headers={"Authorization": f"Bearer {old}"})
    assert r.status_code == 401 and "reset" in r.text, r.text           # BASE: 200 until it expires
    new = world.mint("cid-new", NEW)
    assert isinstance(new, str) and _mine(world, new) == 200            # control: the new pair's token works


def test_the_agent_log_writer_asks_the_same_question(world):
    old = world.mint("cid-old", OLD)
    assert _log(world, old) == 201                                       # control
    world.reset()
    assert _log(world, old) == 401                                       # BASE: 201
    assert _log(world, world.mint("cid-new", NEW)) == 201                # control
    assert len(world.session.logs) == 2


def test_an_owner_session_token_is_not_a_credential_token(world):
    owner_token, _ = security.create_owner_session_token(
        world.agent, SimpleNamespace(id=42, token_version=3))
    world.reset()
    assert _mine(world, owner_token) == 200   # control: bound to its owner's session, which the reset did not end


def test_the_second_agent_resolver_refuses_it_too(world):
    import jwt
    from agentvault_registry.routers import utils as rutils

    class _Db:
        async def execute(self, *a, **k):
            return SimpleNamespace(scalar_one_or_none=lambda: world.agent)
    old = world.mint("cid-old", OLD)
    claims = jwt.decode(old, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    info = {"did": DID, "id": 7, "act": None, "via": None, "owner": None, "owner_tv": None, "cv": claims.get("cv")}
    import asyncio
    assert asyncio.run(rutils.get_current_agent(db=_Db(), token_data=info)) is world.agent   # control
    world.reset()
    with pytest.raises(HTTPException) as e:                                                   # BASE: the agent
        asyncio.run(rutils.get_current_agent(db=_Db(), token_data=info))
    assert e.value.status_code == 401


def test_the_mcp_bridge_reads_it_as_no_agent(world, monkeypatch):
    from agentvault_registry.mcp import server as S
    tool = "theprotocol_getMyBalance"

    async def _who(ctx, **kw):
        return {"auth_type": ctx.auth_type}
    monkeypatch.setitem(S.TOOL_DISPATCH, tool, _who)

    @contextlib.asynccontextmanager
    async def _db():
        yield world.session
    monkeypatch.setattr(S, "get_db_context", _db)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(S.router, prefix="/mcp")
    mcp = TestClient(app, raise_server_exceptions=False)

    def who(token):
        body = mcp.post("/mcp/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                          "params": {"name": tool, "arguments": {}}},
                        headers={"Authorization": f"Bearer {token}"}).json()
        return ((body.get("result") or {}).get("structuredContent") or {}).get("auth_type")

    old = world.mint("cid-old", OLD)
    assert who(old) == "agent"                       # control
    world.reset()
    assert who(old) != "agent"                       # BASE: "agent"
    assert who(world.mint("cid-new", NEW)) == "agent"
