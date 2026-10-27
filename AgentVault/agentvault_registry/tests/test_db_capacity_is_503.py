"""§MCPTEST30 (V0529, 2026-10-01) — a database that cannot take the call is a 503 with Retry-After, not a 500.

sbx-alpha-db reached its connection ceiling twice on 2026-10-01 (100 of 100 connections idle in the registry's pools):
every request that needed a new connection failed with "too many clients already" and answered 500 "A database error
occurred", which tells a client its request is broken. It is the registry's trouble and it passes; 503 with
Retry-After says try again (agentvault2-21's suggestion, beside their credential-check 503). The same in the 5xx guard
(errors.withheld_db_words) for a route that raised a 500 around such an error, keeping the route's own sentence. A
database error that is NOT capacity keeps its 500, and a value the caller sent keeps its 422.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError, ProgrammingError, TimeoutError as PoolTimeout

from agentvault_registry.errors import db_capacity_error, register_error_handlers


def _raise(exc):
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/x")
    async def x():
        raise exc

    return TestClient(app, raise_server_exceptions=False).get("/x")


def _busy(r, detail="The registry's database is busy right now; try again shortly."):
    assert r.status_code == 503, r.text[:300]
    assert r.headers.get("retry-after") == "5"
    assert r.json()["error"]["code"] == "DATABASE_BUSY" and r.json()["detail"] == detail
    assert "too many clients" not in r.text and "QueuePool" not in r.text and "sqlalchemy" not in r.text


def test_the_connection_ceiling_is_503_with_retry_after():
    _busy(_raise(OperationalError("SELECT 1", {}, Exception("FATAL:  sorry, too many clients already"))))


def test_a_pool_that_timed_out_is_503():
    _busy(_raise(PoolTimeout("QueuePool limit of size 40 overflow 40 reached, connection timed out, timeout 30.00")))


def test_a_route_500_around_the_ceiling_keeps_its_sentence_and_says_busy():
    r = _raise(HTTPException(status_code=500, detail="Failed to list policies: (sqlalchemy.exc.OperationalError) "
                                                     "(psycopg2.OperationalError) FATAL:  sorry, too many clients already"))
    _busy(r, "Failed to list policies: the registry's database is busy right now; try again shortly")


def test_control_another_database_error_stays_500():
    r = _raise(ProgrammingError("SELECT x FROM t", {}, Exception('relation "t" does not exist')))
    assert r.status_code == 500 and r.json()["error"]["code"] == "DATABASE_ERROR"
    assert "retry-after" not in r.headers


def test_the_classifier():
    for busy in ("FATAL: sorry, too many clients already", "remaining connection slots are reserved",
                 "connection refused", "server closed the connection unexpectedly",
                 "terminating connection due to administrator command", "the database system is starting up",
                 "QueuePool limit of size 5 overflow 10 reached", "asyncpg.exceptions.TooManyConnectionsError: x"):
        assert db_capacity_error(busy), busy
    for other in ('relation "t" does not exist', "duplicate key value violates unique constraint",
                  "value out of int32 range", "deadlock detected", "", None):
        assert not db_capacity_error(other), other
