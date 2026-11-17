"""V0666 the games switch (order gwo_a01c49ec): one flag turns the game routes, tools, loops and console views off together.
GAMES_ENABLED, default true (today's behaviour):

  on   the six game routers are mounted (/mcp/arena, /mcp/td, /mcp/snake, /mcp/trading, /mcp/lobby, /api/v1/arena/*), the
       game tools are listed and dispatched, the registry-config says games_enabled true;
  off  none of the six is mounted (an unknown route), no game tool is listed (tools/list, the counts) or dispatched
       (tools/call answers -32601 with the switch's sentence), the registry-config says games_enabled false.
An unknown value counts as ON (a typo never switches a running surface off). ARENA_BETTING_ENABLED keeps its own say over
the bet reads; off games list no bet read either. Red before V0666: core/games.py, arena/mount.py and the switch's tool set
do not exist, and main.py mounts the game routers unconditionally.
"""
from __future__ import annotations

import asyncio
import pathlib

import pytest
from fastapi import FastAPI

from agentvault_registry.core import games
from agentvault_registry.mcp import server, tool_switches

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
GAME_PREFIXES = ("/mcp/arena", "/mcp/td", "/mcp/snake", "/mcp/trading", "/mcp/lobby", "/api/v1/arena")
GAME_TOOLS = {"theprotocol_" + n for n in ("listArenaMatches", "getArenaMatch", "getArenaMatchBets", "getArenaMatchMap",
                                           "getArenaLeaderboard", "getArenaAgentStats", "createArenaMatch")}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _paths(app):
    """Every route path, the included routers' too (this FastAPI keeps them as _IncludedRouter until walked: the boot gate's
    iter_route_contexts, build_v0665.sh)."""
    from fastapi.routing import iter_route_contexts
    return [getattr(r, "path", "") or "" for r in iter_route_contexts(app.routes)]


@pytest.mark.parametrize("value,want", [(None, True), ("true", True), ("1", True), ("yes", True), ("on", True),
                                        ("ture", True), ("false", False), ("0", False), ("no", False), ("off", False),
                                        (" FALSE ", False)])
def test_the_switch_reads_like_the_other_surfaces(monkeypatch, value, want):
    if value is None:
        monkeypatch.delenv("GAMES_ENABLED", raising=False)
    else:
        monkeypatch.setenv("GAMES_ENABLED", value)
    assert games.games_enabled() is want


def test_on_mounts_every_game_router(monkeypatch):
    monkeypatch.setenv("GAMES_ENABLED", "true")
    from agentvault_registry.arena import mount
    app = FastAPI()
    assert mount.mount_games(app) is True
    paths = _paths(app)
    for p in GAME_PREFIXES:
        assert any(x.startswith(p) for x in paths), p


def test_off_mounts_no_game_router(monkeypatch):
    monkeypatch.setenv("GAMES_ENABLED", "false")
    from agentvault_registry.arena import mount
    app = FastAPI()
    assert mount.mount_games(app) is False
    paths = _paths(app)
    assert not [x for x in paths if x.startswith(GAME_PREFIXES)], paths


def test_main_mounts_the_games_only_through_the_switch():
    text = (SRC / "main.py").read_text()
    assert "mount_games(app)" in text
    for r in ("arena_mcp_router", "arena_spectator_router", "td_mcp_router", "snake_mcp_router", "trading_mcp_router",
              "lobby_mcp_router"):
        assert f"app.include_router({r}" not in text, r
    assert '"games_enabled": _games_enabled()' in text, "the registry-config says the switch"


def test_every_game_tool_is_gated_and_a_dispatch_key():
    assert tool_switches.NEEDS_GAMES == GAME_TOOLS
    for n in GAME_TOOLS:
        assert n in server.TOOL_DISPATCH, n


def test_on_lists_and_dispatches_the_game_tools(monkeypatch):
    monkeypatch.setenv("GAMES_ENABLED", "true")
    monkeypatch.setenv("ARENA_BETTING_ENABLED", "true")
    listed = {t["name"] for t in _run(server._handle_tools_list())["tools"]}
    assert GAME_TOOLS <= listed
    assert all(tool_switches.dispatchable(n) for n in GAME_TOOLS)


def test_off_lists_no_game_tool_and_refuses_their_call(monkeypatch):
    monkeypatch.setenv("GAMES_ENABLED", "false")
    monkeypatch.setenv("ARENA_BETTING_ENABLED", "true")
    listed = {t["name"] for t in _run(server._handle_tools_list())["tools"]}
    assert not (listed & GAME_TOOLS), sorted(listed & GAME_TOOLS)
    init = _run(server._handle_initialize({}))
    assert f"provides {len(listed)} tools" in init["instructions"], "the count a client is told is the count tools/list gives"
    assert not any(tool_switches.dispatchable(n) for n in GAME_TOOLS)
    with pytest.raises(ValueError, match="games are off on this registry"):
        _run(server._handle_tools_call("theprotocol_listArenaMatches", {}, None))
    # a tool that is not a game is untouched
    assert tool_switches.dispatchable("theprotocol_getNetworkStats")


def test_off_refuses_a_game_tool_on_the_jsonrpc_door(monkeypatch):
    monkeypatch.setenv("GAMES_ENABLED", "false")
    text = (SRC / "mcp" / "server.py").read_text()
    # the JSON-RPC tools/call door asks the same predicate before it dispatches
    assert "if tool_name not in TOOL_DISPATCH or not _tool_dispatchable(tool_name):" in text


def test_betting_off_games_on_keeps_the_bet_read_unlisted(monkeypatch):
    monkeypatch.setenv("GAMES_ENABLED", "true")
    monkeypatch.setenv("ARENA_BETTING_ENABLED", "false")
    assert not tool_switches.listed("theprotocol_getArenaMatchBets")
    assert tool_switches.listed("theprotocol_listArenaMatches")


# ── the MCP tester (item 5): a game row is NOT MEASURED where the target's games are off, never passed and never failed ──
def test_the_tester_reads_the_switch_and_marks_game_rows_not_measured():
    from agentvault_registry.api_tests.contracts import mcp_switches as sw
    assert set(sw.UNMEASURED_WHEN_OFF) == GAME_TOOLS
    sw.use_target({"games_enabled": False})
    try:
        for t in GAME_TOOLS:
            assert (sw.unmeasured_off(t) or "").startswith("NOT MEASURED: the games are off on this target"), t
        assert sw.unmeasured_off("theprotocol_getNetworkStats") is None
        assert sw.switched_off("theprotocol_listArenaMatches") is None, "a game row is never held to a refusal (a pass)"
    finally:
        sw.use_target({})
    sw.use_target({"games_enabled": True})
    assert all(sw.unmeasured_off(t) is None for t in GAME_TOOLS)
    sw.use_target({})   # a target that does not report the key (an image before V0666) has its games on
    assert all(sw.unmeasured_off(t) is None for t in GAME_TOOLS)


def test_the_arena_lifecycle_calls_nothing_where_games_are_off():
    from agentvault_registry.api_tests.contracts import mcp_lifecycles as lc, mcp_switches as sw
    calls = []

    async def rpc(tool, args, jwt=None, timeout=None):
        calls.append(tool)
        return True, {}, "200"

    class Bag:
        developer_jwt = "x"
    outcomes = {}
    sw.use_target({"games_enabled": False})
    try:
        _run(lc.lifecycle_arena_safe_paths(rpc, lambda b: b, Bag(), outcomes))
    finally:
        sw.use_target({})
    assert calls == [], calls
    assert {"theprotocol_createArenaMatch", "theprotocol_getArenaMatch", "theprotocol_getArenaMatchMap",
            "theprotocol_getArenaMatchBets"} <= set(outcomes)
    for t, d in outcomes.items():
        assert (d.get("skip_reason") or "").startswith("NOT MEASURED"), (t, d)


def test_the_public_sweep_names_the_unlisted_game_tools():
    text = (SRC / "api_tests" / "categories" / "flow_mcp_lifecycle" / "test_flow_mcp_lifecycle.py").read_text()
    assert "for _g in sorted(_switches.UNMEASURED_WHEN_OFF):" in text
    assert "skip_reason=_why" in text
