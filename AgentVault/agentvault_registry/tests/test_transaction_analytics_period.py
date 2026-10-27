"""§FESUITE (V0571, 2026-10-04) — the analytics route names the period its counts cover.

Measured on V0569 at sbx-beta: GET /teg/transactions/analytics answered 24h, 30d and 1y with the same 1,208,418 events
(the Event Store's counts of every event since its first, one cached snapshot: there is no window to apply) while it
echoed the period it was asked for, so Mission Control's Economy Pulse labelled all-time counts "24h"; and it refused
"all" (422), the one period that described the counts and one the Economy Pulse offered. The answer now says "all" in
`period` whatever was asked, keeps what was asked in `period_requested`, and takes "all".
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import teg_transactions as TT
from agentvault_registry.security import get_current_developer

STATS = {
    "total_events": 1208418, "unique_agents": 3,
    "event_counts": {"TokensTransferred": 48680, "TokensStaked": 12},
    "oldest_event": "2026-09-03T19:48:07.706150+00:00", "newest_event": "2026-10-04T12:01:25.805119+00:00",
}


@pytest.fixture()
def client(monkeypatch):
    async def fake_es_get(path, params=None, require_key=True):
        if path.endswith("/projections/stats"):
            return STATS
        return {"agents": [], "total_liquid": 0, "total_staked": 0}
    monkeypatch.setattr(TT, "_es_get", fake_es_get)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(TT.router)
    app.dependency_overrides[get_current_developer] = lambda: SimpleNamespace(id=7)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("asked", ["24h", "7d", "30d", "90d", "1y", "all"])
def test_the_answer_names_the_period_its_counts_cover(client, asked):
    r = client.get("/transactions/analytics", params={"period": asked})
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["period"] == "all", "the counts cover every event since the first, whatever was asked"
    assert body["period_requested"] == asked
    assert body["summary"]["total_events"] == STATS["total_events"]
    assert body["oldest_event"] == STATS["oldest_event"]


def test_no_period_reads_every_event(client):
    body = client.get("/transactions/analytics").json()
    assert body["period"] == "all" and body["period_requested"] == "all"


def test_a_period_it_does_not_know_is_still_refused(client):
    assert client.get("/transactions/analytics", params={"period": "5m"}).status_code == 422
