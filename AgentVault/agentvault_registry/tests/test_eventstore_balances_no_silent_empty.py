"""§MCPTEST30 (2026-10-01) — GET /admin/eventstore-balances reports a store that cannot answer; it never pretends the
store holds no agents.

Every failure (a non-200 from the store, an unreachable store) used to answer {"agents": []}: to the admin MCP tool
getEventStoreBalances ("useful for reconciliation") an outage read exactly like an empty ledger. The globe view, its
only caller in the console, catches the error and falls back to an empty list itself, so it renders as before.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import admin_health as AH


class _Client:
    def __init__(self, answer):
        self.answer = answer

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def get(self, *_a, **_k):
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _call(monkeypatch, answer):
    monkeypatch.setattr(AH.httpx, "AsyncClient", lambda *a, **k: _Client(answer))
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(AH.get_eventstore_balances(current_developer=SimpleNamespace(id=1)))
    finally:
        loop.close()


def test_a_store_answer_passes_through(monkeypatch):
    body = {"agents": [{"agent_did": "did:x", "liquid_balance": 1.0}], "total_agents": 1}
    assert _call(monkeypatch, SimpleNamespace(status_code=200, json=lambda: body)) == body


def test_a_store_that_refuses_is_a_502_not_an_empty_list(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _call(monkeypatch, SimpleNamespace(status_code=500, json=lambda: {}))
    assert e.value.status_code == 502 and "HTTP 500" in e.value.detail


def test_an_unreachable_store_is_a_503_not_an_empty_list(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _call(monkeypatch, ConnectionError("refused"))
    assert e.value.status_code == 503 and "could not be reached" in e.value.detail
