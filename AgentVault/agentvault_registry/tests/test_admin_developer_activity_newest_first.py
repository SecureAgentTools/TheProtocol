"""§DOCSFIX D6-317 (2026-10-16): GET /admin/developers/{id}/activity shows the developer's NEWEST events.

The route asked the event store's aggregate route for `limit` events and nothing else. The store answers oldest first
unless asked `sort_order=desc` (its legacy replay contract), so a developer with more events than `limit` showed their
first events, never their latest, under the summary "Recent EventStore activity". The fake store below answers the way
the real one does (agentvault-event-store services/event_store.py get_events_for_aggregate: ascending by default, the
newest first only on `sort_order=desc`).
"""
from __future__ import annotations

import asyncio

import aiohttp
import pytest

from agentvault_registry import es_ssl_helper
from agentvault_registry.routers import admin_developers as AD

EVENTS = [{"event_id": f"e{i:02d}", "timestamp": f"2026-10-{1 + i // 24:02d}T{i % 24:02d}:00:00Z"} for i in range(30)]


class _Resp:
    status = 200

    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Store:
    """An aiohttp.ClientSession stand-in that answers like the store's aggregate route."""
    asked = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def get(self, url, headers=None, params=None, timeout=None):
        params = dict(params or {})
        _Store.asked.append((url, params))
        rows = sorted(EVENTS, key=lambda e: e["timestamp"], reverse=params.get("sort_order") == "desc")
        if params.get("limit") is not None:
            rows = rows[: int(params["limit"])]
        return _Resp(rows)


@pytest.fixture
def store(monkeypatch):
    _Store.asked = []

    async def _exists(db, developer_id):
        return object()

    monkeypatch.setattr(AD, "_load_developer", _exists)
    monkeypatch.setattr(es_ssl_helper, "get_es_ssl_context", lambda: None)
    monkeypatch.setattr(aiohttp, "ClientSession", _Store)
    return _Store


def test_the_activity_list_is_the_newest_events(store):
    out = asyncio.run(AD.get_developer_activity(developer_id=7, limit=5, db=None, admin=None))
    assert [e["event_id"] for e in out] == ["e29", "e28", "e27", "e26", "e25"]
    url, params = store.asked[-1]
    assert url.endswith("/api/v1/events/aggregate/developer:7")
    assert params == {"limit": 5, "sort_order": "desc"}


def test_a_short_history_is_all_there(store):
    out = asyncio.run(AD.get_developer_activity(developer_id=7, limit=200, db=None, admin=None))
    assert len(out) == 30 and out[0]["event_id"] == "e29" and out[-1]["event_id"] == "e00"
