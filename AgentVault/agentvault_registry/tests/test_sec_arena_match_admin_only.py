"""D6-634 (2026-10-16): POST /api/v1/arena/matches is an administrator's call, as its own docstring always said.

The route took no credential at all: anyone could start a match of bots on the registry's game workers, and the
public MCP tool createArenaMatch ("Public.") called it without one. It now depends on
require_admin_flag("admin_platform") (an admin, or that flag, on a credential that may act as an admin), and the
MCP tool moved to the developer tier so it forwards the caller's credential.

Through FastAPI on the real router; the match manager (Redis) and the database session are the only doubles.
RED on 14520b9f: the no-credential and the non-admin cases (the base starts the match for both).
"""
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.arena import spectator
from agentvault_registry.database import get_db


class _Match:
    def __init__(self, match_id):
        self.match_id = match_id
        self.game = types.SimpleNamespace(agents={}, started=False)


@pytest.fixture
def started(monkeypatch):
    calls = []

    async def create_match(mode="battle_royale", max_agents=6, min_agents=2):
        calls.append(("create", mode, max_agents))
        return _Match("m-test")

    async def add_bot(match_id):
        calls.append(("bot", match_id))

    monkeypatch.setattr(spectator.match_manager, "create_match", create_match)
    monkeypatch.setattr(spectator.match_manager, "add_bot", add_bot)
    return calls


def _client(developer=None):
    app = FastAPI()
    app.include_router(spectator.router)

    async def _no_db():
        yield None

    app.dependency_overrides[get_db] = _no_db
    if developer is not None:
        app.dependency_overrides[security.get_current_developer] = lambda: developer
    return TestClient(app)


def _dev(**flags):
    base = dict(id=7, email="dev@example.test", is_admin=False, must_change_password=False,
                admin_treasury=False, admin_support=False, admin_enforcement=False,
                admin_federation=False, admin_platform=False)
    base.update(flags)
    return types.SimpleNamespace(**base)


def test_no_credential_starts_nothing(started):
    r = _client().post("/api/v1/arena/matches?add_bots=3")
    assert r.status_code == 401, (r.status_code, r.text)
    assert started == [], started


def test_a_developer_who_is_not_an_admin_starts_nothing(started):
    r = _client(_dev()).post("/api/v1/arena/matches?add_bots=3")
    assert r.status_code == 403, (r.status_code, r.text)
    assert started == [], started


def test_an_admin_starts_a_match_of_bots(started):
    r = _client(_dev(is_admin=True)).post("/api/v1/arena/matches?add_bots=3")
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json()["match_id"] == "m-test"
    assert started == [("create", "battle_royale", 3)] + [("bot", "m-test")] * 3, started


def test_the_admin_platform_flag_suffices(started):
    r = _client(_dev(admin_platform=True)).post("/api/v1/arena/matches")
    assert r.status_code == 200, (r.status_code, r.text)


def test_the_reads_stay_public(started, monkeypatch):
    async def list_matches():
        return []

    monkeypatch.setattr(spectator.match_manager, "list_matches", list_matches)
    r = _client().get("/api/v1/arena/matches")
    assert r.status_code == 200 and r.json() == {"matches": []}, (r.status_code, r.text)


def test_the_mcp_tool_is_developer_tier_and_sends_the_routes_parameters(monkeypatch):
    from agentvault_registry.mcp import audit, server, tools_developer, tools_discovery

    assert "theprotocol_createArenaMatch" in server.TIER3_TOOLS
    assert "theprotocol_createArenaMatch" in server.AUTH_REQUIRED_TOOLS
    assert "theprotocol_createArenaMatch" in audit._TIER_3_TOOLS
    assert "theprotocol_createArenaMatch" not in audit._TIER_1_TOOLS
    sent = {}

    async def _dev_request(auth, method, path, *, params=None, json_body=None, raw=False):
        sent.update(auth=auth, method=method, path=path, params=params, json_body=json_body)
        return {"match_id": "m"}

    monkeypatch.setattr(tools_developer, "_dev_request", _dev_request)
    import asyncio
    out = asyncio.run(tools_discovery.create_arena_match("AUTH", {"mode": "extraction", "add_bots": 4}))
    assert out == {"match_id": "m"}
    assert sent == {"auth": "AUTH", "method": "POST", "path": "/api/v1/arena/matches",
                    "params": {"mode": "extraction", "add_bots": 4}, "json_body": None}, sent
