"""§DOCSFIX D6-629, D6-631, D6-632 (2026-10-16): three game-server defects.

D6-629: the game servers resolve a player's DID from the agent token they are given, to link scores to the agent. They
decoded it with `settings.SECRET_KEY`, a setting that does not exist (the registry signs its JWTs with API_KEY_SECRET),
and then read the claims `agent_did` / `did`, which an agent token does not carry (it carries `sub`, `type`, `agent_id`).
Every stored game result had a NULL agent_did, /api/v1/arena/agent-stats/{did} found no games, and a lobby's game.started
webhook (sent only to seats with a DID) never went. The player-id readers of the five servers decoded with the same
missing setting, so every token-holding player was named `token:<the first 12 characters>`, which is the JWT header and
the same for everyone.

D6-631: GET /mcp/<game>/sse announced a fixed message endpoint on https://api.theprotocol.cloud (arena and td behind an
env override), so an SSE client of any other registry, ASIA included, was sent to EU's servers. It now names the
registry the client reached (its public base URL), the env overrides still first.

D6-632: a bet pool is created on the first bet and match start closes only a pool that exists, so a bet placed after the
start opened a fresh pool and was accepted. The bet tool now refuses once the match (shared state) has started.
"""
from __future__ import annotations

import asyncio
import importlib
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from agentvault_registry import security

DID = "did:theprotocol:asia.theprotocol.cloud:7c1e4f2a-9b3d-4e5f-8a6b-1c2d3e4f5a6b"


def _agent_token(**extra):
    return security.create_access_token({"sub": DID, "type": "agent", "agent_id": "42", **extra},
                                        expires_delta=timedelta(minutes=5))


# The player identity itself (D6-629: an agent token names its DID in `sub`, a developer token or a forgery names no
# player) is tested where the merged release implements it, arena/player_identity.py, by agentvault2-56's
# tests/test_sec2_game_did_link.py; this file keeps the announced endpoint (D6-631) and the bet window (D6-632).


def _headers_request(path, header):
    req = Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "root_path": "",
                   "scheme": "http", "server": ("registry", 8000),
                   "headers": [(b"host", b"asia.theprotocol.cloud")] + ([header] if header else [])})
    return req


@pytest.mark.parametrize("modname", ["mcp_server", "snake_mcp_server", "lobby_mcp_server", "trading_mcp_server",
                                     "td_mcp_server"])
def test_no_server_decodes_with_a_setting_that_does_not_exist(modname):
    mod = importlib.import_module(f"agentvault_registry.arena.{modname}")
    src = importlib.util.find_spec(mod.__name__).loader.get_source(mod.__name__)
    assert "settings.SECRET_KEY" not in src, f"{modname} still decodes with a setting that does not exist"


@pytest.mark.parametrize("modname,fn,game", [
    ("mcp_server", "arena_sse", "arena"), ("td_mcp_server", None, "td"), ("snake_mcp_server", "snake_sse", "snake"),
    ("trading_mcp_server", None, "trading"), ("lobby_mcp_server", None, "lobby"),
])
def test_the_sse_endpoint_names_the_registry_the_client_reached(monkeypatch, modname, fn, game):
    from agentvault_registry.config import settings
    monkeypatch.setattr(settings, "BASE_URL", "http://localhost:8000")     # unset in effect: the request decides
    monkeypatch.delenv("MCP_ARENA_PUBLIC_RPC_URL", raising=False)
    monkeypatch.delenv("MCP_TD_PUBLIC_RPC_URL", raising=False)
    mod = importlib.import_module(f"agentvault_registry.arena.{modname}")
    route = next(r for r in mod.router.routes if getattr(r, "path", "") == "/sse" and "GET" in (r.methods or set()))
    req = _headers_request(f"/mcp/{game}/sse", (b"x-forwarded-proto", b"https"))

    async def _first_event():
        resp = await route.endpoint(req)
        it = resp.body_iterator
        try:
            return await it.__anext__()
        finally:
            await it.aclose()

    first = asyncio.run(_first_event())
    first = first.decode() if isinstance(first, bytes) else first
    assert first == f"event: endpoint\ndata: https://asia.theprotocol.cloud/mcp/{game}/rpc\n\n", first


def test_an_operator_override_still_wins(monkeypatch):
    monkeypatch.setenv("MCP_ARENA_PUBLIC_RPC_URL", "https://games.example.org/mcp/arena/rpc")
    mod = importlib.import_module("agentvault_registry.arena.mcp_server")

    async def _first_event():
        resp = await mod.arena_sse(_headers_request("/mcp/arena/sse", None))
        it = resp.body_iterator
        try:
            return await it.__anext__()
        finally:
            await it.aclose()

    first = asyncio.run(_first_event())
    first = first.decode() if isinstance(first, bytes) else first
    assert first == "event: endpoint\ndata: https://games.example.org/mcp/arena/rpc\n\n"


def test_a_bet_after_the_match_started_is_refused(monkeypatch):
    mod = importlib.import_module("agentvault_registry.arena.mcp_server")
    match_id = f"M-{uuid.uuid4().hex[:8]}"
    reaper = SimpleNamespace(agent_id="bot:abc", name="BOT-Reaper")
    started = SimpleNamespace(game=SimpleNamespace(started=True, finished=False, agents={"bot:abc": reaper}))

    async def _get(mid):
        return started if mid == match_id else None

    monkeypatch.setattr(mod.match_manager, "get_match", _get)
    out = asyncio.run(mod._handle_tool_call(
        "robowars_bet", {"match_id": match_id, "target_agent_name": "BOT-Reaper", "amount": 5}, DID))
    assert "error" in out and "closed" in out["error"], out
    assert mod.betting_manager.get_pool_status(match_id) is None, "no pool was opened by the refused bet"


def test_a_bet_before_the_start_is_still_taken(monkeypatch):
    mod = importlib.import_module("agentvault_registry.arena.mcp_server")
    match_id = f"M-{uuid.uuid4().hex[:8]}"
    reaper = SimpleNamespace(agent_id="bot:abc", name="BOT-Reaper")
    waiting = SimpleNamespace(game=SimpleNamespace(started=False, finished=False, agents={"bot:abc": reaper}))

    async def _get(mid):
        return waiting if mid == match_id else None

    monkeypatch.setattr(mod.match_manager, "get_match", _get)
    out = asyncio.run(mod._handle_tool_call(
        "robowars_bet", {"match_id": match_id, "target_agent_name": "BOT-Reaper", "amount": 5}, DID))
    assert out.get("match_id") == match_id and out.get("total_pool") == 5, out
