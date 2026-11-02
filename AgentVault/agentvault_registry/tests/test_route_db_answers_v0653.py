"""V0653's recut (the pair proof of 2026-11-02 09:02Z, session-tester's read in the sessions' room seq 961; session-lead
seq 965): a route's database error answers as it did before (am) item 2, classified from the exception itself.

Until V0653 a route's 5xx detail carried the driver's words (f"Failed to retrieve proposal: {e}") and the 5xx guard
(errors.withheld_db_words) read them: the caller's value (an id past int32) answered 422, a busy database 503 with
Retry-After, and the words never left. (am) item 2 (core/caller_errors.internal_detail) took the words away first, so
both answered 500 "Failed to retrieve proposal (error id ...)": GET /api/v1/governance/proposals/2147483648 and its
/votes on sbx-beta, the lifecycle suite's two range rows. internal_detail now decides a database error's answer from the
exception before any text is withheld; any other error keeps the route's status, its words and the error id only.

Through FastAPI on the real governance router and the real error handlers; only the database is replaced, by one that
raises what SQLAlchemy raises over asyncpg. Cases marked BASE fail on the cut (1d92f4882).
"""
from __future__ import annotations

import logging
import re

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from agentvault_registry.core.caller_errors import internal_detail
from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import governance

DRIVER_WORDS = ("asyncpg", "[SQL", "SELECT", "int32", "too many clients", "relation", "sqlalche")


def _asyncpg(name, message):
    """An exception of asyncpg's own class name and module (the package is not needed to raise one)."""
    return type(name, (Exception,), {"__module__": "asyncpg.exceptions"})(message)


def _db_error(orig):
    # what SQLAlchemy raises around the driver's error (sqlalchemy.exc.DBAPIError, its text carries the statement)
    return DBAPIError("SELECT governance_proposals.id FROM governance_proposals WHERE governance_proposals.id = $1::INTEGER",
                      (2147483648,), orig)


OUT_OF_RANGE = _db_error(_asyncpg("DataError", "invalid input for query argument $1: 2147483648 (value out of int32 range)"))
TOO_MANY = _db_error(_asyncpg("TooManyConnectionsError", "sorry, too many clients already"))
NO_TABLE = _db_error(_asyncpg("UndefinedTableError", 'relation "governance_proposals" does not exist'))


class _Db:
    def __init__(self, exc):
        self.exc = exc

    async def execute(self, *a, **k):
        raise self.exc

    async def scalar(self, *a, **k):
        raise self.exc

    async def scalars(self, *a, **k):
        raise self.exc

    async def get(self, *a, **k):
        raise self.exc

    async def rollback(self):
        pass

    async def close(self):
        pass


def _client(exc):
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(governance.router, prefix="/api/v1/governance")
    app.dependency_overrides[get_db] = lambda: _Db(exc)
    return TestClient(app, raise_server_exceptions=False)


def _no_driver_words(r):
    low = r.text.lower()
    return [w for w in DRIVER_WORDS if w.lower() in low]


@pytest.mark.parametrize("path", ["/api/v1/governance/proposals/2147483648",
                                  "/api/v1/governance/proposals/2147483648/votes"], ids=["proposal", "votes"])
def test_the_range_row_answers_422_again_with_no_driver_text(path):
    # BASE: 500 "Failed to retrieve proposal (error id ...)" (and "Failed to get votes (...)")
    r = _client(OUT_OF_RANGE).get(path)
    assert r.status_code == 422, (r.status_code, r.text[:300])
    body = r.json()
    assert body["error"]["code"] == "PARAM_OUT_OF_RANGE"
    assert body["detail"] == "A path or query parameter value is out of range or invalid."
    assert not _no_driver_words(r), _no_driver_words(r)


def test_a_busy_database_through_a_route_answers_503_with_retry_after():
    # BASE: 500, no Retry-After
    r = _client(TOO_MANY).get("/api/v1/governance/proposals/7")
    assert r.status_code == 503, (r.status_code, r.text[:300])
    assert r.headers.get("retry-after") == "5"
    body = r.json()
    assert body["error"]["code"] == "DATABASE_BUSY"
    assert body["detail"] == "Failed to retrieve proposal: the registry's database is busy right now; try again shortly"
    assert not _no_driver_words(r), _no_driver_words(r)


def test_another_database_error_still_answers_500_with_the_error_id_only(caplog):
    # control (as on the cut): neither the caller's nor a busy database: the route's words and an error id, the words in
    # the log under that id
    with caplog.at_level(logging.ERROR):
        r = _client(NO_TABLE).get("/api/v1/governance/proposals/7")
    assert r.status_code == 500, (r.status_code, r.text[:300])
    m = re.fullmatch(r"Failed to retrieve proposal \(error id ([0-9a-f]{12})\)", r.json()["detail"])
    assert m, r.json()["detail"]
    assert not _no_driver_words(r), _no_driver_words(r)
    assert any(m.group(1) in rec.getMessage() and "does not exist" in rec.getMessage() for rec in caplog.records)


def test_a_connection_refused_that_is_not_the_database_keeps_the_routes_status():
    # a TEG that refused the connection is the route's 502, never a busy database's 503: classified by the exception's
    # type, not by its words
    from agentvault_registry.core.caller_errors import database_error
    e = httpx.ConnectError("[Errno 111] Connection refused")
    assert database_error(e) is None
    detail = internal_detail(e, "local TEG unreachable")
    assert re.fullmatch(r"local TEG unreachable \(error id [0-9a-f]{12}\)", detail)


def test_a_database_error_raised_from_another_is_still_one():
    from agentvault_registry.core.caller_errors import DatabaseAnswer
    try:
        try:
            raise TOO_MANY
        except DBAPIError as db_err:
            raise RuntimeError("the vote could not be written") from db_err
    except RuntimeError as e:
        with pytest.raises(DatabaseAnswer) as ans:
            internal_detail(e, "Failed to cast vote")
    assert (ans.value.status_code, ans.value.error_code) == (503, "DATABASE_BUSY")
    assert ans.value.headers == {"Retry-After": "5"}


def test_an_answer_caught_again_by_an_outer_handler_keeps_its_status():
    # a route that catches Exception around a block that already answered: the answer stands (never a 500 around it)
    def route():
        try:
            try:
                raise OUT_OF_RANGE
            except Exception as e:
                raise HTTPException(status_code=500, detail=internal_detail(e, "Failed to tally votes"))
        except Exception as e2:
            raise HTTPException(status_code=500, detail=internal_detail(e2, "Failed to tally"))

    from agentvault_registry.core.caller_errors import DatabaseAnswer
    with pytest.raises(DatabaseAnswer) as ans:
        route()
    assert (ans.value.status_code, ans.value.error_code) == (422, "PARAM_OUT_OF_RANGE")


def test_a_refusal_of_the_routes_own_keeps_its_words_and_its_status_stays_the_routes():
    # unchanged by the recut: a 404 the route raised and caught on its way out keeps its words
    assert internal_detail(HTTPException(404, "Proposal 7 not found"), "Failed to retrieve proposal") == \
        "Failed to retrieve proposal: Proposal 7 not found"
