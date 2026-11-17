"""V0663 (order gwo_01681f32a8cfe7390b773532, his suggestion 6, his yes at room seq 3068): a delivery panel for admins.

Per peer, from the chat federation outbox (chat_federation_outbox, the table session-tester soaked): the rows waiting,
the age of the oldest, the most attempts among them, how many reached MAX_ATTEMPTS (given up, waiting for a human), the
next attempt, the latest error and the last delivery. One grouped read, only a read. Every ACTIVE peer appears, a peer
with nothing waiting as clear, so a stuck delivery shows at a glance:
  given_up  a row reached MAX_ATTEMPTS
  late      the oldest waiting row is older than CHAT_DELIVERY_LATE_SECONDS (120)
  waiting   rows waiting, none late
  clear     nothing waiting
Rows for an address that is no longer an active peer still show (a queue for a peer that went away is a finding).
GET /api/v1/admin/chat/federation/delivery, admin_federation (the one admin rule; adminRoutes regenerated).
Red on b27f2ebaf: the module and the route do not exist.
"""
from __future__ import annotations

import asyncio
import datetime as dt

import httpx
import pytest

try:     # red as one failure per test, not a collection error that stops the suite
    from agentvault_registry.services import chat_delivery as cd
except ImportError:
    cd = None

NOW = dt.datetime(2026, 11, 14, 1, 0, tzinfo=dt.timezone.utc)
ASIA, LISBON, GONE = "https://asia.example.org", "https://lisbon.example.org", "https://gone.example.org"


def test_the_module_exists():
    from agentvault_registry.services import chat_delivery
    from agentvault_registry.routers import chat_delivery_admin as r
    assert callable(chat_delivery.delivery_by_peer) and r.router is not None


def _row(peer, *, waiting=0, oldest=None, attempts=0, given_up=0, next_at=None, error=None, delivered=None):
    return {"peer_base_url": peer, "waiting": waiting, "oldest_waiting_at": oldest, "max_attempts": attempts,
            "given_up": given_up, "next_attempt_at": next_at, "last_error": error, "last_delivered_at": delivered}


def test_each_active_peer_gets_a_line_and_a_verdict():
    rows = [
        _row(ASIA, waiting=3, oldest=NOW - dt.timedelta(seconds=30), attempts=1, next_at=NOW + dt.timedelta(seconds=1),
             delivered=NOW - dt.timedelta(seconds=5)),
        _row(LISBON, waiting=2, oldest=NOW - dt.timedelta(hours=3), attempts=12, given_up=1,
             error="ConnectError: the host did not answer", delivered=NOW - dt.timedelta(hours=4)),
    ]
    peers = {ASIA: "asia-registry", LISBON: "lisbon", "https://quiet.example.org": "quiet"}
    out = cd.delivery_view(rows, peers, now=NOW)
    by = {p["peer_base_url"]: p for p in out}
    assert by[ASIA]["verdict"] == "waiting" and by[ASIA]["oldest_age_seconds"] == 30 and by[ASIA]["name"] == "asia-registry"
    assert by[LISBON]["verdict"] == "given_up" and by[LISBON]["last_error"].startswith("ConnectError")
    assert by["https://quiet.example.org"]["verdict"] == "clear" and by["https://quiet.example.org"]["waiting"] == 0
    assert [p["peer_base_url"] for p in out][0] == LISBON, "the worst first"


def test_a_waiting_row_older_than_the_threshold_is_late(monkeypatch):
    monkeypatch.setenv("CHAT_DELIVERY_LATE_SECONDS", "60")
    out = cd.delivery_view([_row(ASIA, waiting=1, oldest=NOW - dt.timedelta(seconds=90), attempts=3)], {ASIA: "asia"}, now=NOW)
    assert out[0]["verdict"] == "late"


def test_a_queue_for_a_peer_that_went_away_still_shows():
    out = cd.delivery_view([_row(GONE, waiting=4, oldest=NOW - dt.timedelta(days=2), attempts=12, given_up=4)], {}, now=NOW)
    assert out[0]["peer_base_url"] == GONE and out[0]["name"] is None and out[0]["active_peer"] is False
    assert out[0]["verdict"] == "given_up"


def test_times_are_iso_and_ages_whole_seconds():
    out = cd.delivery_view([_row(ASIA, waiting=1, oldest=NOW - dt.timedelta(seconds=7.6), delivered=NOW)], {ASIA: "a"}, now=NOW)
    assert out[0]["oldest_age_seconds"] == 7 and out[0]["last_delivered_at"] == NOW.isoformat()


def test_the_read_is_one_grouped_select():
    from sqlalchemy.dialects import postgresql
    sql = str(cd.delivery_stmt().compile(dialect=postgresql.dialect())).lower()
    assert sql.lstrip().startswith("select") and "group by" in sql and "chat_federation_outbox" in sql
    assert "delivered_at is null" in sql
    for verb in ("insert ", "update ", "delete "):
        assert verb not in sql


# --- the route -----------------------------------------------------------------------------------------------------

def _app(monkeypatch, rows, peers):
    from fastapi import FastAPI
    from agentvault_registry import database
    from agentvault_registry.routers import chat_delivery_admin as route

    async def read(db):
        return rows

    async def peer_map(db):
        return peers

    async def stats():
        return {"cycles": 9, "delivered": 40, "failed": 0}
    monkeypatch.setattr(cd, "read_rows", read)
    monkeypatch.setattr(cd, "active_peers", peer_map)
    monkeypatch.setattr(cd, "worker_stats", stats)
    monkeypatch.setattr(cd, "federation_enabled", lambda: True)
    app = FastAPI()
    app.include_router(route.router)

    async def get_db():
        yield None
    app.dependency_overrides[database.get_db] = get_db
    app.dependency_overrides[route._ADMIN] = lambda: object()
    return app


def test_the_route_answers_per_peer_with_the_worker_and_the_time(monkeypatch):
    app = _app(monkeypatch, [_row(ASIA, waiting=1, oldest=NOW, attempts=1)], {ASIA: "asia"})

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://reg.test") as c:
            return await c.get("/api/v1/admin/chat/federation/delivery")
    r = asyncio.run(go())
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True and body["worker"]["cycles"] == 9 and body["as_of"]
    assert body["peers"][0]["peer_base_url"] == ASIA and body["max_attempts"] == 12


def test_the_route_is_behind_the_federation_admin_flag():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "routers"
           / "chat_delivery_admin.py").read_text()
    assert '_ADMIN = require_admin_flag("admin_federation")' in src and "Security(_ADMIN)" in src
