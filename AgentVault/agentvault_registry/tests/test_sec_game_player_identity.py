"""D6-633 (2026-10-16): a game server's player comes only from a verified agent token of this registry.

Every game server (arena, td, snake, trading, lobby) decoded the bearer token with `settings.SECRET_KEY`, a name
the registry's settings do not define, so every decode raised and every token fell back to
`token:<first 12 characters>`: the encoded JWT header, identical for every token the registry issues. All players
who sent a token were one player, and any string with that prefix acted as them. Now: no Authorization header is
the shared anonymous player (documented); any Authorization header must be a current agent JWT of this registry
(signature, expiry, an agent token, the agent present and not suspended or revoked), and the player is the
agent's DID; anything else is refused with 401 / -32001 and never reaches the game.

Through FastAPI on each server's real router; the game dispatch (Redis) is replaced by a recorder that answers
the player id it was given, and the agent and developer lookups (database) are doubles. Tokens are real JWTs
signed with the registry's own key (security.SECRET_KEY).
RED on 14520b9f: every case but the tokenless one, on all five servers.
"""
import datetime as dt
import json
import types

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import database, security
from agentvault_registry.arena import lobby_mcp_server, mcp_server, snake_mcp_server, td_mcp_server, trading_mcp_server

SERVERS = {  # name: (module, mount prefix, dispatch function name, a tool the server lists)
    "arena": (mcp_server, "/mcp/arena", "_handle_tool_call", "robowars_status"),
    "td": (td_mcp_server, "/mcp/td", "_handle_td_tool", "td_status"),
    "snake": (snake_mcp_server, "/mcp/snake", "_handle_snake_tool", "snake_status"),
    "trading": (trading_mcp_server, "/mcp/trading", "_handle_trading_tool", "trade_status"),
    "lobby": (lobby_mcp_server, "/mcp/lobby", "_handle_lobby_tool", "lobby_list"),
}
AGENTS = {  # did -> status
    "did:theprotocol:player-one": "active",
    "did:theprotocol:player-two": "active",
    "did:theprotocol:suspended": "suspended",
}


def _agent_token(did, *, key=None, minutes=30):
    claims = {"sub": did, "type": "agent", "agent_id": "11",
              "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)}
    return jwt.encode(claims, key or security.SECRET_KEY, algorithm=security.ALGORITHM)


def _developer_token():
    claims = {"sub": "7", "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)}
    return jwt.encode(claims, security.SECRET_KEY, algorithm=security.ALGORITHM)


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def doubles(monkeypatch):
    async def get_agent_by_did(db, did):
        status = AGENTS.get(did)
        return None if status is None else types.SimpleNamespace(did=did, status=status, creator_developer_id=7)

    async def get_current_developer_optional(db=None, claims=None):
        return types.SimpleNamespace(id=7, is_active=True) if claims else None

    monkeypatch.setattr(security.agent_crud, "get_agent_by_did", get_agent_by_did)
    monkeypatch.setattr(security, "get_current_developer_optional", get_current_developer_optional)
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _Session())


def _call(server, headers=None):
    module, prefix, dispatch, tool = SERVERS[server]
    seen = []

    async def recorder(tool_name, args, agent_id):
        seen.append(agent_id)
        return {"player": agent_id}

    setattr_target = (module, dispatch)
    original = getattr(module, dispatch)
    setattr(*setattr_target, recorder)
    try:
        app = FastAPI()
        app.include_router(module.router, prefix=prefix)
        r = TestClient(app).post(prefix, headers=headers or {},
                                 json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                       "params": {"name": tool, "arguments": {}}})
    finally:
        setattr(*setattr_target, original)
    return r, seen


def _player(r):
    assert r.status_code == 200, (r.status_code, r.text)
    return json.loads(r.json()["result"]["content"][0]["text"])["player"]


def _refused(r, seen):
    assert r.status_code == 401, (r.status_code, r.text)
    assert r.json()["error"]["code"] == -32001, r.text
    assert seen == [], seen


@pytest.mark.parametrize("server", SERVERS)
def test_no_authorization_is_the_shared_anonymous_player(server):
    r, seen = _call(server)
    assert _player(r) == "anonymous"


@pytest.mark.parametrize("server", SERVERS)
def test_a_valid_agent_token_plays_as_its_agent(server):
    r, _ = _call(server, {"Authorization": f"Bearer {_agent_token('did:theprotocol:player-one')}"})
    assert _player(r) == "did:theprotocol:player-one"


@pytest.mark.parametrize("server", SERVERS)
def test_two_agents_are_two_players(server):
    one = _player(_call(server, {"Authorization": f"Bearer {_agent_token('did:theprotocol:player-one')}"})[0])
    two = _player(_call(server, {"Authorization": f"Bearer {_agent_token('did:theprotocol:player-two')}"})[0])
    assert one != two, (one, two)


@pytest.mark.parametrize("server", SERVERS)
def test_a_string_with_a_tokens_prefix_is_refused(server):
    forged = _agent_token("did:theprotocol:player-one")[:12] + "anything"
    _refused(*_call(server, {"Authorization": f"Bearer {forged}"}))


@pytest.mark.parametrize("server", SERVERS)
def test_a_token_signed_with_another_key_is_refused(server):
    other = _agent_token("did:theprotocol:player-one", key="not-this-registrys-key-0123456789abcdef")
    _refused(*_call(server, {"Authorization": f"Bearer {other}"}))


@pytest.mark.parametrize("server", SERVERS)
def test_an_expired_agent_token_is_refused(server):
    _refused(*_call(server, {"Authorization": f"Bearer {_agent_token('did:theprotocol:player-one', minutes=-5)}"}))


@pytest.mark.parametrize("server", SERVERS)
def test_a_developer_token_is_not_a_player(server):
    _refused(*_call(server, {"Authorization": f"Bearer {_developer_token()}"}))


@pytest.mark.parametrize("server", SERVERS)
def test_a_suspended_agent_is_refused(server):
    _refused(*_call(server, {"Authorization": f"Bearer {_agent_token('did:theprotocol:suspended')}"}))


@pytest.mark.parametrize("server", SERVERS)
def test_an_authorization_that_is_not_a_bearer_token_is_refused(server):
    _refused(*_call(server, {"Authorization": "Basic dXNlcjpwYXNz"}))
