"""D6-629 (2026-10-16): a game played with an agent token links its results to that agent's DID.

`game_persistence.resolve_agent_did` decoded a token passed in a tool's arguments (`agent_token`) with
`settings.SECRET_KEY`, which the registry's settings do not define, and read the claims `agent_did` / `did`, which the
registry's agent tokens do not carry: every stored result had agent_did NULL, GET /api/v1/arena/agent-stats/{did}
returned no games, and the lobby's game.started webhook (sent only to slots with a DID) never fired. Since D6-633 the
player of every call is a verified agent token of this registry in the Authorization header (its DID), or the shared
anonymous player; the DID a result links to is now that player's. The `agent_token` argument is accepted and not read.

Through FastAPI on the lobby server's real router (its lobby store, Redis, is a recorder); the agent and developer
lookups (database) are doubles and the tokens are real JWTs signed with the registry's key, as in
tests/test_sec_game_player_identity.py. The other four servers make the same one call: it is pinned on their call
sites (AST, not text).
RED on 7140a4a6: every test but the anonymous control.
"""
import ast
import datetime as dt
import json
import pathlib
import types

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import database, security
from agentvault_registry.arena import game_persistence, lobby_mcp_server

DID = "did:theprotocol:sec2:player"


def _agent_token(did):
    claims = {"sub": did, "type": "agent", "agent_id": "11",
              "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)}
    return jwt.encode(claims, security.SECRET_KEY, algorithm=security.ALGORITHM)


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.fixture()
def lobby(monkeypatch):
    seen = []

    async def get_agent_by_did(db, did):
        return types.SimpleNamespace(did=did, status="active", creator_developer_id=7) if did == DID else None

    async def get_current_developer_optional(db=None, claims=None):
        return types.SimpleNamespace(id=7, is_active=True) if claims else None

    def create_lobby(**kw):
        seen.append(("create", kw.get("creator_did")))
        return types.SimpleNamespace(lobby_id="L-1", max_players=kw.get("max_players"),
                                     countdown_seconds=kw.get("countdown_seconds"), fill_bots=kw.get("fill_bots"))

    def join_lobby(lobby_id, agent_id, agent_name, agent_did=None):
        seen.append(("join", agent_did))
        return {"joined": lobby_id}

    monkeypatch.setattr(security.agent_crud, "get_agent_by_did", get_agent_by_did)
    monkeypatch.setattr(security, "get_current_developer_optional", get_current_developer_optional)
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _Session())
    monkeypatch.setattr(lobby_mcp_server.lobby_manager, "create_lobby", create_lobby)
    monkeypatch.setattr(lobby_mcp_server.lobby_manager, "join_lobby", join_lobby)
    return seen


def _call(tool, arguments, headers=None):
    app = FastAPI()
    app.include_router(lobby_mcp_server.router, prefix="/mcp/lobby")
    r = TestClient(app).post("/mcp/lobby", headers=headers or {},
                             json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                   "params": {"name": tool, "arguments": arguments}})
    assert r.status_code == 200, (r.status_code, r.text[:300])
    return json.loads(r.json()["result"]["content"][0]["text"])


def test_a_lobby_created_by_an_agent_is_linked_to_its_did(lobby):
    out = _call("lobby_create", {"game_type": "robowars"}, {"Authorization": f"Bearer {_agent_token(DID)}"})
    assert out["identified_as"] == DID, out
    assert lobby == [("create", DID)]


def test_an_agent_joining_a_lobby_is_linked_to_its_did(lobby):
    _call("lobby_join", {"lobby_id": "L-1"}, {"Authorization": f"Bearer {_agent_token(DID)}"})
    assert lobby == [("join", DID)]


def test_control_the_anonymous_player_links_nothing(lobby):
    out = _call("lobby_create", {"game_type": "robowars", "agent_token": _agent_token(DID)})
    assert out["identified_as"] is None, out        # a token in the arguments is not an identity
    assert lobby == [("create", None)]


@pytest.mark.parametrize("player, want", [(DID, DID), ("anonymous", None), (None, None), ("token:abcdef", None)])
def test_the_rule(player, want):
    assert game_persistence.resolve_agent_did(player) == want


SERVERS = {"mcp_server.py": "_handle_tool_call", "snake_mcp_server.py": "_handle_snake_tool",
           "trading_mcp_server.py": "_handle_trading_tool", "td_mcp_server.py": "_handle_td_tool",
           "lobby_mcp_server.py": "_handle_lobby_tool"}


@pytest.mark.parametrize("module, handler", sorted(SERVERS.items()))
def test_every_game_server_links_the_verified_player(module, handler):
    path = pathlib.Path(game_persistence.__file__).resolve().parent / module
    tree = ast.parse(path.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == handler)
    player = fn.args.args[2].arg     # (tool_name, args, <player>)
    calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "resolve_agent_did"]
    assert calls, f"{module}: {handler} links no DID"
    for c in calls:
        assert len(c.args) == 1 and isinstance(c.args[0], ast.Name) and c.args[0].id == player, ast.dump(c)
