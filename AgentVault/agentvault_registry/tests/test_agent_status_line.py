"""V0650 (a) (2026-10-31, agentvault2-14): an agent's status line (PUT/GET /api/v1/agents/me/status).

Order gwo_6630c6afb216eba6c3270dbc. An agent says what it is doing in one line that expires on its own. Through FastAPI
on the real agents router over real (SQLite) tables; only the caller's identity is supplied. Cases marked BASE fail on
6c1f036b (V0649), where the routes, the table and the service do not exist.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry import models, security
from agentvault_registry.database import get_db
from agentvault_registry.routers import agents as agents_router
from tests._sqlite_db import sqlite_db

DID = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-0000000000a1"
T0 = dt.datetime(2026, 10, 31, 5, 0, 0, tzinfo=dt.timezone.utc)


def _db():
    tables = [m for m in (models.Developer, models.Agent, getattr(models, "AgentStatusLine", None)) if m is not None]
    db = sqlite_db(*tables)
    s = db.sync
    s.add(models.Developer(id=6, name="Commander", email="c@example.org", hashed_password="x"))
    s.add(models.Agent(id=1, did=DID, client_id="c1", hashed_client_secret="x", creator_developer_id=6, status="active"))
    s.commit()
    return db


@pytest.fixture()
def call(monkeypatch):
    db = _db()
    clock = {"now": T0}
    try:
        from agentvault_registry.services import agent_status_line as sl
        monkeypatch.setattr(sl, "_now", lambda: clock["now"])
    except ImportError:
        pass
    app = FastAPI()
    app.include_router(agents_router.router)

    async def _yield_db():
        yield db
    app.dependency_overrides[get_db] = _yield_db
    app.dependency_overrides[security.get_current_agent] = lambda: SimpleNamespace(did=DID, status="active",
                                                                                     creator_developer_id=6)

    async def do(method, body=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.request(method, "/api/v1/agents/me/status", json=body)
    do.db, do.clock = db, clock
    return do


@pytest.mark.asyncio
async def test_set_then_read_the_line(call):
    # BASE: 404
    r = await call("PUT", {"text": "  building V0650 (a)  ", "ttl_seconds": 600})
    assert r.status_code == 200, r.text
    got = (await call("GET")).json()
    assert got["agent_did"] == DID and got["status"]["text"] == "building V0650 (a)"
    assert got["status"]["expires_at"].startswith("2026-10-31T05:10:00") and got["status"]["expires_in_seconds"] == 600


@pytest.mark.asyncio
async def test_a_new_line_replaces_the_old_one(call):
    # BASE: 404
    await call("PUT", {"text": "first"})
    await call("PUT", {"text": "second", "ttl_seconds": 60})
    assert (await call("GET")).json()["status"]["text"] == "second"
    assert len(call.db.sync.query(models.AgentStatusLine).all()) == 1


@pytest.mark.asyncio
async def test_an_expired_line_reads_as_none(call):
    # BASE: 404
    await call("PUT", {"text": "short", "ttl_seconds": 30})
    call.clock["now"] = T0 + dt.timedelta(seconds=31)
    got = await call("GET")
    assert got.status_code == 200 and got.json()["status"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"text": "x" * 141}, {"text": ""}, {"text": "   "}, {"text": "two\nlines"}, {"text": "nul\x00"},
    {"text": "ok", "ttl_seconds": 0}, {"text": "ok", "ttl_seconds": 86401},
])
async def test_what_a_line_may_not_be(call, body):
    # BASE: 404 (and nothing is written on the branch)
    r = await call("PUT", body)
    assert r.status_code == 422, (r.status_code, r.text[:200])


@pytest.mark.asyncio
async def test_a_credential_shaped_line_is_refused_and_nothing_is_written(call):
    # BASE: 404
    jwt_like = ".".join(["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", "eyJzdWIiOiJhIn0", "c2lnbmF0dXJlc2lnbmF0dXJl"])
    r = await call("PUT", {"text": f"token {jwt_like}"})
    assert r.status_code == 422, r.text
    assert (await call("GET")).json()["status"] is None


def test_live_line_reads_naive_and_aware_timestamps():
    # BASE: ImportError
    from agentvault_registry.services.agent_status_line import live_line
    row = SimpleNamespace(status_text="t", set_at=dt.datetime(2026, 10, 31, 5, 0, 0),
                          expires_at=dt.datetime(2026, 10, 31, 6, 0, 0))
    assert live_line(row, T0)["expires_in_seconds"] == 3600
    row.expires_at = T0 + dt.timedelta(minutes=1)
    assert live_line(row, T0)["expires_in_seconds"] == 60
    assert live_line(row, T0 + dt.timedelta(minutes=2)) is None and live_line(None, T0) is None


def test_the_routes_are_agent_tier():
    # BASE: the routes do not exist
    from agentvault_registry.core import auth_tiers
    routes = {(m, r.path): r for r in agents_router.router.routes for m in getattr(r, "methods", ())}
    for method in ("PUT", "GET"):
        route = routes.get((method, "/api/v1/agents/me/status"))
        assert route is not None, f"{method} /api/v1/agents/me/status is not a route"
        assert auth_tiers.route_tier(route) == auth_tiers.AGENT


def test_the_migration_creates_what_the_model_declares():
    # BASE: no 0199 file
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0199_agent_status_lines.py"
    src = path.read_text(encoding="utf-8")
    rev = re.search(r'^revision: str = "([^"]+)"', src, re.M).group(1)
    assert rev == "0199_agent_status_lines" and len(rev) <= 32
    # the parent is the head this lands on (0197 on the branch; the V0650 cut re-chains it): any revision that exists
    down = re.search(r'^down_revision: Union\[str, None\] = "([^"]+)"', src, re.M).group(1)
    assert any(f.name.startswith(down) for f in path.parent.glob("*.py")), down
    assert "op.create_table(" in src and 'op.drop_table("agent_status_lines")' in src
    cols = set(re.findall(r'sa\.Column\("([a-z_]+)"', src))
    assert cols == {c.name for c in models.AgentStatusLine.__table__.columns}
