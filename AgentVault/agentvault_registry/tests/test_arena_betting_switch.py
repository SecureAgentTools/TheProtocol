"""Arena betting where ARENA_BETTING_ENABLED is off (agentvault2-d6, 2026-10-25; his word through agentvault2-69 at 21:15Z):
getArenaMatchBets is not listed on the public MCP surface, robowars_bet is not listed by the arena MCP server, and the
spectator's bet read is refused with the retired surface's sentence. Where the switch is on (or unset), all three are as
before."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.arena import mcp_server as arena_mcp
from agentvault_registry.arena import spectator
from agentvault_registry.mcp import tool_switches


def _arena_tools(client):
    r = client.post("/arena-mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 200
    return {t["name"] for t in r.json()["result"]["tools"]}


def _client():
    app = FastAPI()
    app.include_router(arena_mcp.router, prefix="/arena-mcp")
    app.include_router(spectator.router)
    return TestClient(app)


def test_betting_off_hides_the_bet_tools_and_refuses_the_read(monkeypatch):
    monkeypatch.setenv("ARENA_BETTING_ENABLED", "false")
    assert tool_switches.listed("theprotocol_getArenaMatchBets") is False
    c = _client()
    tools = _arena_tools(c)
    assert "robowars_bet" not in tools and "robowars_join_match" in tools
    r = c.get("/api/v1/arena/matches/m1/bets")
    assert r.status_code == 404 and "ARENA_BETTING_ENABLED=false" in r.json()["detail"]


def test_betting_on_or_unset_keeps_all_three(monkeypatch):
    for value in ("true", None):
        if value is None:
            monkeypatch.delenv("ARENA_BETTING_ENABLED", raising=False)
        else:
            monkeypatch.setenv("ARENA_BETTING_ENABLED", value)
        assert tool_switches.listed("theprotocol_getArenaMatchBets") is True
        c = _client()
        assert "robowars_bet" in _arena_tools(c)
        r = c.get("/api/v1/arena/matches/no-such-match/bets")
        assert r.status_code == 200 and r.json()["total_pool"] == 0
