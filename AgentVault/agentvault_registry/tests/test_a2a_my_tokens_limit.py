"""§DOCSFIX CB-455 (2026-10-16): GET /a2a-payment/my-tokens refuses a `limit` below 1 with 422.

`limit` had an upper bound (200) and no lower one: 0 answered an empty list (which reads exactly like "you hold no
tokens") and a negative value reached the database, where PostgreSQL refuses a negative LIMIT and the call failed
with a server error. Driven through FastAPI with the route's own parameter declarations.

RED on the pre-change tree: the two refusals. The controls are green before and after.
"""
from __future__ import annotations

import importlib
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

a2a = importlib.import_module("agentvault_registry.routers.a2a_payment")

PAYER = "did:theprotocol:eu.theprotocol.cloud:payer-0000"


class _Db:
    def __init__(self):
        self.statements = []

    async def execute(self, stmt, *a, **k):
        self.statements.append(stmt)
        return types.SimpleNamespace(scalars=lambda: types.SimpleNamespace(all=lambda: []))


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(a2a.router)
    db = _Db()

    async def _get_db():
        yield db
    app.dependency_overrides[a2a.get_current_agent] = lambda: types.SimpleNamespace(did=PAYER)
    app.dependency_overrides[a2a.get_db] = _get_db
    c = TestClient(app)
    c.db = db
    return c


@pytest.mark.parametrize("limit", ["0", "-1"])
def test_a_limit_below_one_is_refused_before_the_database_is_asked(client, limit):
    r = client.get(f"/api/v1/a2a-payment/my-tokens?limit={limit}")
    assert r.status_code == 422, r.text
    assert client.db.statements == []


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("query", ["", "?limit=1", "?limit=200"])
def test_control_a_limit_in_range_is_answered(client, query):
    r = client.get(f"/api/v1/a2a-payment/my-tokens{query}")
    assert r.status_code == 200 and r.json() == []


def test_control_a_limit_above_200_is_refused(client):
    assert client.get("/api/v1/a2a-payment/my-tokens?limit=201").status_code == 422
