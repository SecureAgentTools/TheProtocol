"""§MCPTEST30 (V0546) — a database error in the agent card list is answered by its cause, never as an empty page.

crud.agent_card.list_agent_cards returned ([], 0) for ANY failure of its count or its page read, so a database at its
connection ceiling, or a value the database refused, read as "no agents" with HTTP 200: to the public /agent-cards/ list
and to a peer's /federation/query alike. Round 14's type probe sent skip=2**63 (sbx-alpha, 2026-10-02 06:48:34Z: "invalid
input for query argument $2: 9223372036854775808 (value out of int64 range)", logged with a traceback, then answered as an
empty page). The CRUD now raises, and both routes let a database error reach errors.sqlalchemy_error_handler: a caller's
value 422, a database at capacity 503, anything else 500.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from agentvault_registry import database
from agentvault_registry.crud import agent_card as crud
from agentvault_registry.errors import sqlalchemy_error_handler
from agentvault_registry.routers import agent_cards as R
from agentvault_registry.security import get_current_actor_for_read_optional, get_current_developer_optional

OVERFLOW = "invalid input for query argument $2: 9223372036854775808 (value out of int64 range)"
CEILING = "sorry, too many clients already"


class _Session:
    def __init__(self, message):
        self.message, self.calls = message, 0

    async def execute(self, stmt):
        self.calls += 1
        raise DBAPIError("SELECT agent_cards.id FROM agent_cards", {"skip": 2 ** 63}, Exception(self.message))

    async def rollback(self):
        pass

    async def close(self):
        pass


@pytest.mark.parametrize("message", [OVERFLOW, CEILING])
def test_the_crud_raises_a_database_error_instead_of_an_empty_page(message):
    s = _Session(message)
    with pytest.raises(DBAPIError):
        asyncio.run(crud.list_agent_cards(s, skip=2 ** 63))
    assert s.calls == 1, "the count read failed and nothing answered for it"


def _client(message):
    app = FastAPI()
    app.include_router(R.router, prefix="/api/v1/agent-cards")
    app.add_exception_handler(SQLAlchemyError, sqlalchemy_error_handler)

    async def db():
        yield _Session(message)

    async def nobody():
        return None
    app.dependency_overrides[database.get_db] = db
    app.dependency_overrides[get_current_developer_optional] = nobody
    app.dependency_overrides[get_current_actor_for_read_optional] = nobody
    return TestClient(app, raise_server_exceptions=False)


def test_a_value_the_database_refused_is_the_callers_422_not_an_empty_200():
    r = _client(OVERFLOW).get("/api/v1/agent-cards/", params={"skip": str(2 ** 63)})
    assert r.status_code == 422, (r.status_code, r.text[:300])
    assert "9223372036854775808" not in r.text, "the database's words stay in the log"


def test_a_database_that_cannot_take_the_call_is_not_an_empty_200():
    r = _client(CEILING).get("/api/v1/agent-cards/")
    assert r.status_code >= 500, (r.status_code, r.text[:300])
    assert '"items"' not in r.text, "no page is claimed"


def test_the_federation_query_route_passes_a_database_error_through():
    from agentvault_registry.routers import federation_query as FQ
    import inspect
    src = inspect.getsource(FQ)
    i_sql, i_any = src.index("except SQLAlchemyError:"), src.index("except Exception as e:\n        logger.error(f\"Error processing federation query")
    assert i_sql < i_any, "a database error is answered by its cause before the catch-all's 500"


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
