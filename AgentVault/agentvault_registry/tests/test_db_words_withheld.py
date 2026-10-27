"""§MCPTEST30 (V0525, 2026-10-01) — a 5xx a route raised around a database error never carries the database's own words.

Measured on sbx-alpha (V0521) by the bounds probe: getProposalDetail with an id past int32 answered 500 "Failed to
retrieve proposal: (sqlalchemy.dialects.postgresql.asyncpg.Error) invalid input for query argument $1: 2147483648 (value
out of int32 range)". The route's catch-all turned the caller's value into a 500, pre-empted the SQLAlchemy handler (which
answers that error 422 PARAM_OUT_OF_RANGE), and handed the caller the driver's sentence. 93 route catch-alls raise a 500
for any exception; 30 of them put the exception's text in the detail. The guard sits in the HTTPException handler, so it
covers every one of them and the next one written.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agentvault_registry.errors import register_error_handlers, withheld_db_words

MEASURED = ("Failed to retrieve proposal: (sqlalchemy.dialects.postgresql.asyncpg.Error) invalid input for query "
            "argument $1: 2147483648 (value out of int32 range)")


def _get(detail, code=500):
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/x")
    async def x():
        raise HTTPException(status_code=code, detail=detail)

    return TestClient(app, raise_server_exceptions=False).get("/x")


def test_the_measured_proposal_answer_is_the_callers_422_without_the_drivers_words():
    r = _get(MEASURED)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "PARAM_OUT_OF_RANGE"
    assert "sqlalchemy" not in r.text and "2147483648" not in r.text and "query argument" not in r.text


def test_another_database_error_keeps_its_status_and_the_routes_sentence():
    r = _get("Failed to list policies: (psycopg2.errors.UndefinedColumn) column x does not exist\n[SQL: SELECT x FROM t]")
    assert r.status_code == 500
    assert r.json()["detail"] == "Failed to list policies: a database error occurred"
    assert r.json()["error"]["code"] == "DATABASE_ERROR"
    assert "[SQL" not in r.text and "psycopg2" not in r.text and "UndefinedColumn" not in r.text


def test_a_bare_driver_sentence_a_503_and_a_nul():
    # (V0529: a refused connection is the capacity class, 503 + Retry-After, tests/test_db_capacity_is_503.py; these keep
    # the V0525 contract with an error that is not)
    r = _get("(sqlalchemy.exc.InternalError) current transaction is aborted")
    assert r.status_code == 500 and r.json()["detail"] == "A database error occurred"
    r = _get("Unable to sync: (sqlalchemy.exc.InternalError) current transaction is aborted", 503)
    assert r.status_code == 503 and r.json()["detail"] == "Unable to sync: a database error occurred"
    r = _get('Failed: (sqlalchemy.dialects.postgresql.asyncpg.Error) invalid byte sequence for encoding "UTF8": 0x00')
    assert r.status_code == 422 and r.json()["error"]["code"] == "NUL_IN_TEXT"


def test_a_dict_detail_carrying_the_words_is_withheld_too():
    r = _get({"error": "boom", "cause": "asyncpg.exceptions.UndefinedTableError: relation t does not exist"})
    assert r.status_code == 500 and r.json()["detail"] == "A database error occurred"
    assert "UndefinedTableError" not in r.text


def test_controls_a_5xx_without_driver_words_and_a_4xx_are_untouched():
    r = _get("Failed: list index out of range")
    assert r.status_code == 500 and r.json()["detail"] == "Failed: list index out of range"
    r = _get("Proposal 7 not found", 404)
    assert r.status_code == 404 and r.json()["detail"] == "Proposal 7 not found"
    assert withheld_db_words(None, 404, "(sqlalchemy.exc.X) y") is None   # the scope is a 5xx
