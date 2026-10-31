"""V0650 (m) (2026-10-31, agentvault2-14): developer API keys on the chat read routes.

Order gwo_a19052e2e099921b01aad9a5. The chat read routes resolved their caller with get_current_actor_for_read, which
decodes JWTs only, so a developer API key (`avreg_`, what the MCP bridges, the CLI and the sessions' tools present)
answered 401 on every one of them. They now take get_current_actor_for_read_or_key: a key resolves exactly as on every
other developer route (verify_access_token_required, then get_current_developer), and a JWT, developer or agent, goes
through get_current_actor_for_read unchanged. No write route changes.

Through FastAPI on the real chat router and the real resolution chain; only the key and developer lookups, the agent
lookup and the chat service's reads are replaced. Cases marked BASE fail on 6c1f036b (V0649).
"""
from __future__ import annotations

import ast
import datetime as dt
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.crud import agent as agent_crud
from agentvault_registry.crud import developer as developer_crud
from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import chat
from agentvault_registry.services import chat_service as cs

LIVE, REVOKED, EXPIRED = "avreg_" + "a" * 40, "avreg_" + "r" * 40, "avreg_" + "e" * 40
DEV = SimpleNamespace(id=6, name="Commander", email="c@example.test", is_active=True, is_admin=False,
                      is_verified=True, token_version=0)
DID = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-0000000000ab"


class _Db:
    async def execute(self, *a, **k):
        raise AssertionError("no statement should reach the database in these tests")

    def add(self, obj):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.fixture()
def client(monkeypatch):
    seen = []

    async def _by_key(db, plain_key):
        # the real crud's answers: a live key -> its developer; a revoked key (is_active false) and an expired key -> None
        return DEV if plain_key == LIVE else None

    async def _scopes(db, plain_key):
        return ["*"], 11

    async def _by_id(db, developer_id):
        return DEV if developer_id == DEV.id else None

    async def _agent(db, did):
        return SimpleNamespace(did=did, status="active", name="session-release", creator_developer_id=DEV.id)

    async def _no_refusal(db, payload, agent):
        return None

    async def _list(db, actor, state="active", cursor=None, limit=30, **kw):   # V0650: other orders add keywords
        seen.append(("list", actor.ptype, actor.developer_id, actor.agent_did))
        return {"conversations": [], "state": state, "next_cursor": None}

    async def _messages(db, conversation_id, actor, before_seq=None, limit=40, join=False, **kw):   # (h) adds mentions
        seen.append(("messages", actor.ptype, actor.developer_id, conversation_id))
        return {"messages": [], "conversation_id": conversation_id}

    monkeypatch.setattr(developer_crud, "get_developer_by_plain_api_key", _by_key)
    monkeypatch.setattr(developer_crud, "get_developer_by_id_strict", _by_id)
    monkeypatch.setattr(security, "presented_key_scopes", _scopes)
    monkeypatch.setattr(agent_crud, "get_agent_by_did", _agent)
    monkeypatch.setattr(security, "agent_token_refusal", _no_refusal)
    monkeypatch.setattr(cs, "list_conversations", _list)
    monkeypatch.setattr(cs, "list_messages", _messages)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(chat.router)
    app.dependency_overrides[get_db] = lambda: _Db()
    c = TestClient(app, raise_server_exceptions=False)
    c.seen = seen
    return c


def _get(client, path, token):
    return client.get(path, headers={"Authorization": f"Bearer {token}"})


def test_a_developer_key_reads_its_own_inbox(client):
    # BASE: 401 (the JWT-only reader cannot decode a key)
    r = _get(client, "/api/v1/chat/conversations", LIVE)
    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert client.seen == [("list", "developer", DEV.id, None)]


def test_a_developer_key_reads_a_thread_it_may_read(client):
    # BASE: 401
    r = _get(client, "/api/v1/chat/conversations/conv-1/messages", LIVE)
    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert client.seen == [("messages", "developer", DEV.id, "conv-1")]


@pytest.mark.parametrize("key", [REVOKED, EXPIRED])
def test_a_revoked_or_expired_key_is_refused(client, key):
    # control: 401 on both trees (the base refuses every key; the branch refuses these two by name of the crud)
    r = _get(client, "/api/v1/chat/conversations", key)
    assert r.status_code == 401 and client.seen == [], (r.status_code, r.text[:200])


def test_an_agent_jwt_reads_exactly_as_before(client):
    # control: the agent path is get_current_actor_for_read's, unchanged
    token = jwt.encode({"sub": DID, "type": "agent", "agent_id": "7",
                        "exp": int(dt.datetime.now(dt.timezone.utc).timestamp()) + 600},
                       security.SECRET_KEY, algorithm=security.ALGORITHM)
    r = _get(client, "/api/v1/chat/conversations", token)
    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert client.seen == [("list", "agent", None, DID)]


def test_a_garbage_token_is_still_refused(client):
    # control
    assert _get(client, "/api/v1/chat/conversations", "not-a-token").status_code == 401


def test_only_the_read_routes_moved():
    # BASE: no route uses the new reader
    src = Path(chat.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    got, writes_with_new = set(), set()
    for n in tree.body:
        if not isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        methods = {d.func.attr for d in n.decorator_list
                   if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                   and d.func.attr in ("get", "post", "put", "delete", "patch")}
        if not methods:
            continue
        sig = ast.unparse(n.args)
        if "get_current_actor_for_read_or_key" in sig:
            (got if methods == {"get"} else writes_with_new).add(n.name)
        elif "get" in methods and "Depends(get_current_actor_for_read)" in sig:
            raise AssertionError(f"{n.name} is a read route still on the JWT-only reader")
    assert len(got) >= 19 and {"list_conversations", "get_messages", "sync", "download_attachment"} <= got
    assert not writes_with_new, f"a write route took the new reader: {writes_with_new}"
