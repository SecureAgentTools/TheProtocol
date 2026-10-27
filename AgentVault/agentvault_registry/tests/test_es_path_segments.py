"""§MCPTEST30 (V0526, 2026-10-01) — a value a caller sends lands in an EventStore URL path as ONE encoded segment.

Round 9 (sbx-alpha, V0525): getTegTransactionDetail with `mcp-probe%_\\` answered 503 "Event Store unreachable". The route
put the id into the store's URL unencoded, the store's edge refused the malformed path with 400, and the route reports
any non-200 as an outage. V0523 encoded the MCP tools' and the TEG proxy's paths; these routers were left out.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import teg_transactions as TT
from agentvault_registry.security import get_current_developer

HOSTILE = "mcp-probe%_\\"


@pytest.fixture()
def seen(monkeypatch):
    paths = []

    async def fake_es_get(path, params=None, require_key=True):
        paths.append(path)
        return []
    monkeypatch.setattr(TT, "_es_get", fake_es_get)
    return paths


def _client():
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(TT.router)
    # SEC-01: an administrator, who reads every account (a bare developer that owns nothing is refused before the store)
    app.dependency_overrides[get_current_developer] = lambda: SimpleNamespace(id=7, is_admin=True)
    return TestClient(app, raise_server_exceptions=False)


def test_the_transaction_id_is_one_encoded_segment_and_an_unknown_one_is_404(seen):
    r = _client().get("/transaction/" + "mcp-probe%25_%5C")          # the caller's value, sent encoded
    assert r.status_code == 404, r.text[:200]
    assert seen[0] == "/api/v1/events/by-transaction/mcp-probe%25_%5C"


def test_a_dot_dot_cannot_climb_out_of_the_stores_path(seen):
    from agentvault_registry.core.path_segment import seg
    assert seg("..") == "%2E%2E" and seg("a/b") == "a%2Fb"
    _client().get("/transactions/history/" + "%2E%2E")
    assert seen and all("/../" not in p and not p.endswith("/..") for p in seen), seen


def test_every_store_path_in_the_router_goes_through_seg():
    import inspect
    src = inspect.getsource(TT)
    assert src.count("{seg(") >= 4
    for raw in ("by-transaction/{transaction_id}", "aggregate/{agent_id}", "transactions/{agent_id}", "aggregate/{current_agent.did}"):
        assert raw not in src, raw
