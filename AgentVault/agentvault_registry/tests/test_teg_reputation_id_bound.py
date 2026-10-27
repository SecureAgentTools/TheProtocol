"""§MCPTEST30 (V0526, 2026-10-01) — the reputation proxy refuses an agent id the TEG cannot hold, 422, before forwarding.

Round 8 (sbx-alpha, V0523): the hostile-input probe's 4,000-character agent_id reached the TEG's String(255) column,
psycopg2 StringDataRightTruncation answered 500 there and 503 here (an outage that was the caller's value).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import teg_integration as T
from agentvault_registry.security import get_current_agent


@pytest.fixture()
def client(monkeypatch):
    async def reached(*_a, **_k):   # past validation the handler asks for a TEG token first: proof the request got in
        raise HTTPException(status_code=418, detail="reached the handler")
    monkeypatch.setattr(T, "get_teg_token_for_agent", reached)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(T.router)
    app.dependency_overrides[get_current_agent] = lambda: SimpleNamespace(id=1, did="did:theprotocol:probe")
    return TestClient(app, raise_server_exceptions=False)


def test_an_id_longer_than_the_tegs_column_is_refused_before_the_teg(client):
    assert client.get("/teg/agents/" + "p" * 256 + "/reputation").status_code == 422
    assert client.get("/teg/agents/" + "p" * 4000 + "/reputation").status_code == 422


def test_control_an_id_the_column_holds_reaches_the_handler(client):
    assert client.get("/teg/agents/did:theprotocol:x/reputation").status_code == 418
    assert client.get("/teg/agents/" + "p" * 255 + "/reputation").status_code == 418
