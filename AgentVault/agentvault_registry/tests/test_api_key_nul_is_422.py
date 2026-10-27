"""§MCPTEST30 (V0526, 2026-10-01) — a NUL in an API key's name is the caller's 422, end to end through the route.

Round 9's write-hygiene probe (sbx-alpha, V0525): createApiKey with a NUL in its name answered 500. The CRUD caught the
database's refusal and returned None, and the route's failure log then read `current_developer.id` from a row the
rollback had expired (MissingGreenlet). V0524's NUL mapping lives in the SQLAlchemy handler, which never saw the error:
its own test drove the handler, not this route. This one drives the route.
"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import auth_secure


class _Session:
    """add() works, commit() raises what the database said; rollback() is counted."""

    def __init__(self, said):
        self.said, self.rollbacks = said, 0

    def add(self, _obj):
        pass

    async def commit(self):
        raise DBAPIError("INSERT INTO developer_api_keys", {}, Exception(self.said))

    async def refresh(self, _obj):
        raise AssertionError("never reached")

    async def rollback(self):
        self.rollbacks += 1


def _client(said):
    session = _Session(said)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(auth_secure.router)

    async def _db():
        yield session
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[security.get_current_developer] = lambda: SimpleNamespace(id=7, email="dev@example.test")
    return TestClient(app, raise_server_exceptions=False), session


def test_a_nul_in_the_name_is_the_callers_422_and_rolls_back():
    client, session = _client('invalid byte sequence for encoding "UTF8": 0x00')
    r = client.post("/auth/api-keys", json="mcp-hyg-x\u0000n")
    assert r.status_code == 422, r.text[:300]
    assert r.json()["error"]["code"] == "NUL_IN_TEXT"
    assert session.rollbacks >= 1


def test_control_another_database_failure_stays_500_without_its_words():
    client, _session = _client("connection reset by peer")
    r = client.post("/auth/api-keys", json="mcp-hyg-plain")
    assert r.status_code == 500, r.text[:300]
    assert r.json()["detail"] == "A database error occurred" and "connection reset" not in r.text
