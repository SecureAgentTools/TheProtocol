"""V0653 (w) (2026-11-02, agentvault2-14): a developer API key writes in the chat; it never decides an approval.

Order gwo_213e530b4ca2de3130c4a1d1 (session-lead, the sessions' room seq 844 and 847). The credential of an MCP
connector (its OAuth flow mints a key, mcp/oauth.py) and of his personal bridge is a key, and through MCP a key read a
room (V0650 (m)) but every chat write answered 401 "Could not validate credentials": post_message and the other write
routes took get_current_actor_for_read, which decodes JWTs only (measured on sbx-beta 2026-11-02 01:11Z: readThread 200,
sendChatMessage 401, the same key). The write routes the MCP chat tools call now take get_current_actor_for_read_or_key.
And an approval is decided by a person, signed in: decide_approvals refuses any key, whatever its scopes (before, a key
through MCP's relay decided, and the record only noted it); requesting and consuming take an agent JWT, as before.

Through FastAPI on the real chat router and the real resolution chain (the relay proof is the real HMAC); only the key,
developer and agent lookups and the chat service's own steps are replaced. Cases marked BASE fail on a5ef48ddd (V0652).
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
from agentvault_registry.services import chat_approvals as ca
from agentvault_registry.services import chat_service as cs

FULL, MCP, REVOKED = "avreg_" + "f" * 40, "avreg_" + "m" * 40, "avreg_" + "r" * 40
DEV = SimpleNamespace(id=6, name="Commander", email="c@example.test", is_active=True, is_admin=False,
                      is_verified=True, token_version=0, must_change_password=False)
DID = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-0000000000ab"
PAST_THE_KEY_RULE = 418   # the room lookup after decide's key rule, replaced: reaching it answers this

# the write routes the MCP chat tools call (mcp/tools_agent.py: send, progress, board, mark read, respond, block)
KEY_WRITES = {"create_conversation", "post_message", "update_card", "write_board", "read_mark", "accept_conversation",
              "decline_conversation", "leave_conversation", "create_block", "remove_block"}


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
    seen, sent_with = [], []

    async def _by_key(db, plain_key):
        return DEV if plain_key in (FULL, MCP) else None

    async def _scopes(db, plain_key):
        return (["mcp:tools"], 12) if plain_key == MCP else (["*"], 11)

    async def _by_id(db, developer_id):
        return DEV if developer_id == DEV.id else None

    async def _tv_ok(db, developer_id, tv):
        return True

    async def _agent(db, did):
        return SimpleNamespace(did=did, status="active", name="session-release", creator_developer_id=DEV.id)

    async def _no_refusal(db, payload, agent):
        return None

    async def _conv(db, conversation_id):
        return SimpleNamespace(id=conversation_id, kind="dm", org_id=None)

    async def _member(db, conv, actor, announce_ok=False):
        return SimpleNamespace(state="active")

    async def _send(db, conv, my_row, actor, kind, body, card, client_ref, reply_to=None, **kw):
        seen.append(("send", actor.ptype, actor.developer_id, actor.agent_did, body))
        sent_with.append(getattr(actor, "sent_with", "no such field"))
        return {"id": "m-1", "conversation_id": conv.id, "body": body}

    async def _room(db, conversation_id):
        raise cs.ChatError(PAST_THE_KEY_RULE, "past the key rule")

    monkeypatch.setattr(developer_crud, "get_developer_by_plain_api_key", _by_key)
    monkeypatch.setattr(developer_crud, "get_developer_by_id_strict", _by_id)
    monkeypatch.setattr(developer_crud, "get_developer_by_id_lean", _by_id)   # the chat dependency's developer lookup
    monkeypatch.setattr(security, "presented_key_scopes", _scopes)
    monkeypatch.setattr(security, "token_version_current", _tv_ok)
    monkeypatch.setattr(agent_crud, "get_agent_by_did", _agent)
    monkeypatch.setattr(security, "agent_token_refusal", _no_refusal)
    monkeypatch.setattr(cs, "_get_conversation", _conv)
    monkeypatch.setattr(cs, "resolve_membership", _member)
    monkeypatch.setattr(chat, "_send_and_fan_out", _send)
    monkeypatch.setattr(chat, "_approval_room", _room)
    monkeypatch.setattr(ca, "enabled", lambda: True)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(chat.router)
    app.dependency_overrides[get_db] = lambda: _Db()
    c = TestClient(app, raise_server_exceptions=False)
    c.seen, c.sent_with = seen, sent_with
    return c


def _headers(token, relay=False):
    h = {"Authorization": f"Bearer {token}"}
    if relay:
        h[security.MCP_RELAY_HEADER] = security.mcp_relay_proof(token)
    return h


def _send(client, token, relay=False):
    return client.post("/api/v1/chat/conversations/conv-1/messages", headers=_headers(token, relay),
                       json={"kind": "text", "body": "hello from a key", "client_ref": "ref-00000001"})


def _decide(client, token, relay=False):
    return client.post("/api/v1/chat/conversations/room-1/approvals/decide", headers=_headers(token, relay),
                       json={"decision": "approve", "approval_ids": ["apr_" + "a" * 32]})


def _dev_jwt():
    return jwt.encode({"sub": str(DEV.id), "tv": 0, "exp": int(dt.datetime.now(dt.timezone.utc).timestamp()) + 600},
                      security.SECRET_KEY, algorithm=security.ALGORITHM)


def _agent_jwt():
    return jwt.encode({"sub": DID, "type": "agent", "agent_id": "7",
                       "exp": int(dt.datetime.now(dt.timezone.utc).timestamp()) + 600},
                      security.SECRET_KEY, algorithm=security.ALGORITHM)


def test_a_key_sends_through_mcp_and_the_message_lands(client):
    # BASE: 401 (the JWT-only reader cannot decode a key); the MCP connector's and the bridge's case
    r = _send(client, MCP, relay=True)
    assert r.status_code == 201, (r.status_code, r.text[:200])
    assert client.seen == [("send", "developer", DEV.id, None, "hello from a key")]


def test_a_full_authority_key_sends(client):
    # BASE: 401
    r = _send(client, FULL)
    assert r.status_code == 201, (r.status_code, r.text[:200])
    assert client.seen == [("send", "developer", DEV.id, None, "hello from a key")]


def test_an_mcp_key_without_the_relay_proof_still_cannot_send(client):
    # control (both trees refuse; the branch with D6-514's 403): a narrow key reaches the REST API through MCP only
    r = _send(client, MCP)
    assert r.status_code in (401, 403) and client.seen == [], (r.status_code, r.text[:200])


@pytest.mark.parametrize("token", [REVOKED, "not-a-token"])
def test_a_revoked_key_or_garbage_still_cannot_send(client, token):
    # control
    r = _send(client, token)
    assert r.status_code == 401 and client.seen == [], (r.status_code, r.text[:200])


def test_an_agent_jwt_sends_exactly_as_before(client):
    # control: the agent path is get_current_actor_for_read's, unchanged
    r = _send(client, _agent_jwt())
    assert r.status_code == 201, (r.status_code, r.text[:200])
    assert client.seen == [("send", "agent", None, DID, "hello from a key")]


@pytest.mark.parametrize("token,relay", [(MCP, True), (FULL, False)], ids=["mcp-key-through-the-relay", "full-key"])
def test_a_key_never_decides_an_approval(client, token, relay):
    # BASE: the key passes and the route goes on (PAST_THE_KEY_RULE); his click stays the only way
    r = _decide(client, token, relay)
    assert r.status_code == 403, (r.status_code, r.text[:200])
    assert "API key cannot decide" in r.text


def test_a_signed_in_session_still_decides(client):
    # control: a developer JWT goes past the key rule to the room
    r = _decide(client, _dev_jwt())
    assert r.status_code == PAST_THE_KEY_RULE, (r.status_code, r.text[:200])


def test_a_key_never_consumes_or_requests_an_approval(client):
    # control (both trees): consuming and requesting take an agent JWT
    c = client.post(f"/api/v1/chat/approvals/apr_{'a' * 32}/consume", headers=_headers(MCP, relay=True),
                    json={"act": "x", "act_sha256": "c" * 64})
    q = client.post("/api/v1/chat/conversations/room-1/approvals", headers=_headers(MCP, relay=True),
                    json={"title": "x", "client_ref": "ref-00000002"})
    assert c.status_code in (401, 403, 422) and q.status_code in (401, 403, 422), (c.status_code, q.status_code)
    assert c.status_code != 422 or "agent" in c.text.lower(), c.text[:200]


def test_exactly_the_mcp_tools_write_routes_take_a_key():
    # BASE: none does. A write route outside the set is a new way for a key to act in the chat: add it here on purpose.
    tree = ast.parse(Path(chat.__file__).read_text(encoding="utf-8"))
    writes = set()
    for n in tree.body:
        if not isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        methods = {d.func.attr for d in n.decorator_list
                   if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                   and d.func.attr in ("get", "post", "put", "delete", "patch")}
        if methods and methods != {"get"} and "get_current_actor_for_read_or_key" in ast.unparse(n.args):
            writes.add(n.name)
    assert writes == KEY_WRITES, (sorted(writes - KEY_WRITES), sorted(KEY_WRITES - writes))


# ── the mark (session-lead, the sessions' room seq 880): each message records the credential it was sent with ─────────

@pytest.mark.parametrize("token,relay,want", [(MCP, True, "api_key"), (FULL, False, "api_key")],
                         ids=["mcp-key-through-the-relay", "full-key"])
def test_a_key_s_line_records_api_key(client, token, relay, want):
    # BASE (18ee29f22): the actor had no such field, so the line recorded nothing about how it was sent
    r = _send(client, token, relay)
    assert r.status_code == 201, (r.status_code, r.text[:200])
    assert client.sent_with == [want]


def test_a_signed_in_developer_s_line_records_session(client):
    # BASE: no such field
    r = _send(client, _dev_jwt())
    assert r.status_code == 201, (r.status_code, r.text[:200])
    assert client.sent_with == ["session"]


def test_an_agent_s_line_records_agent(client):
    # BASE: no such field
    r = _send(client, _agent_jwt())
    assert r.status_code == 201, (r.status_code, r.text[:200])
    assert client.sent_with == ["agent"]
