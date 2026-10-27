"""§MCPTEST30 (V0545) — the session dependency logs a CLIENT's mistake as one line, a server's as a traceback.

One tester sweep left 203 tracebacks in 30 minutes on sbx-alpha: 51 RequestValidationError (FastAPI raises it after the
yield dependencies are entered, and it is not an HTTPException, so get_db logged it at ERROR with its stack) and the
database refusing an id past int32 (errors.py answers it 422, the caller's value; get_db logged a traceback first). Any
caller can fill the log with either. A real server failure keeps its traceback.
"""
from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import DBAPIError

from agentvault_registry import database as db


class _Session:
    def __init__(self):
        self.rolled_back = self.closed = 0

    async def rollback(self):
        self.rolled_back += 1

    async def close(self):
        self.closed += 1


def _throw(monkeypatch, exc):
    s = _Session()
    monkeypatch.setattr(db, "AsyncSessionLocal", lambda: s)

    async def go():
        gen = db.get_db()
        await gen.__anext__()
        with pytest.raises(type(exc)):
            await gen.athrow(exc)
    asyncio.run(go())
    return s


def _overflow():
    orig = Exception("invalid input for query argument $1: 2147483648 (value out of int32 range)")
    return DBAPIError("SELECT * FROM governance_proposals WHERE id = $1", {"id": 2147483648}, orig)


def test_a_request_that_fails_validation_rolls_back_without_a_traceback(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=db.logger.name)
    s = _throw(monkeypatch, RequestValidationError([{"loc": ["path", "id"], "msg": "bad", "type": "value_error"}]))
    assert s.rolled_back == 1 and s.closed == 1
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], [r.getMessage() for r in caplog.records]


def test_a_value_the_database_refused_is_one_warning_line(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=db.logger.name)
    s = _throw(monkeypatch, _overflow())
    assert s.rolled_back == 1
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    warns = [r for r in caplog.records if r.levelno == logging.WARNING and "a value the caller sent" in r.getMessage()]
    assert len(warns) == 1 and warns[0].exc_info is None, "one line, no stack"
    assert "out of int32 range" in warns[0].getMessage() and "SELECT" not in warns[0].getMessage(), \
        "the driver's words, never the statement or its parameters"


def test_a_server_failure_keeps_its_traceback(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=db.logger.name)
    s = _throw(monkeypatch, RuntimeError("the pool is gone"))
    assert s.rolled_back == 1
    errs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errs) == 1 and errs[0].exc_info is not None


def test_the_classification_is_the_answer_rule():
    from agentvault_registry.errors import db_error_answer
    assert db.caller_caused_db_error(_overflow()) is True
    assert db_error_answer(str(_overflow()).split("\n", 1)[0])["status_code"] == 422
    assert db.caller_caused_db_error(RuntimeError("connection reset by peer")) is False
    assert db.caller_caused_db_error(DBAPIError("SELECT 1", {}, Exception("too many clients already"))) is False


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
