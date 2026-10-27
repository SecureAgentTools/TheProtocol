"""§MCPTEST30 (V0525, 2026-10-01) — the TEG proxy refuses a page it cannot ask for, 422, before anything is forwarded.

Measured on sbx-alpha (V0521) by the bounds probe: offset=2^63 on /teg/transactions reached the TEG, whose database
answered "bigint out of range" (its 500), and this registry reported it as 503 "Unable to fetch transaction history at
this time": an outage that was the caller's value. Three proxy routes forwarded limit and offset with no bounds at all.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import teg_integration as T
from agentvault_registry.security import get_current_agent

ROUTES = ("/teg/transactions", "/teg/disputes", "/teg/attestations")


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


@pytest.mark.parametrize("path", ROUTES)
@pytest.mark.parametrize("query", ["offset=9223372036854775808", "offset=2147483648", "offset=-1",
                                   "limit=9223372036854775808", "limit=-1"])
def test_a_page_past_the_bounds_is_refused_before_the_teg(client, path, query):
    r = client.get(f"{path}?{query}")
    assert r.status_code == 422, (path, query, r.status_code, r.text[:200])


@pytest.mark.parametrize("path", ROUTES)
def test_control_a_page_inside_the_bounds_reaches_the_handler(client, path):
    r = client.get(f"{path}?limit=20&offset=2147483647")
    assert r.status_code == 418, (path, r.status_code, r.text[:200])
    assert client.get(path).status_code == 418
