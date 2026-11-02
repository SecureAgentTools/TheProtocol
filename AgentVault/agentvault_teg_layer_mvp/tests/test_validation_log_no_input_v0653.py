"""V0653 (am), item 7 (the hardening list in the sessions' room; found reading item 13): a refused request's VALUES never
reach the TEG's log.

errors.validation_exception_handler logged exc.errors() whole, and pydantic 2 puts the value it refused into each error
("input"), so a refused body's key or token went into the TEG's log. The line keeps where and why (loc, type, msg). BASE
(a5ef48ddd, V0652's TEG source): the refused value is in the log.
"""
import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from teg_core_service import errors as E

KEY = "not-a-valid-key-0123"      # 20 characters: the rule wants 32


class _Body(BaseModel):
    agent_id: str
    api_key: str = Field(min_length=32)


def _client():
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, E.validation_exception_handler)

    @app.post("/x")
    async def x(body: _Body):
        return {"ok": True}

    return TestClient(app)


def test_a_refused_key_never_reaches_the_log(caplog):
    with caplog.at_level(logging.DEBUG):
        r = _client().post("/x", json={"agent_id": "did:theprotocol:a", "api_key": KEY})
    assert r.status_code == 422
    assert KEY not in caplog.text
    assert KEY not in r.text                              # the control: the answer never carried it


def test_the_line_still_says_where_and_why(caplog):
    with caplog.at_level(logging.DEBUG):
        _client().post("/x", json={"agent_id": "did:theprotocol:a", "api_key": KEY})
    line = [m for m in caplog.messages if m.startswith("Validation error on POST /x")]
    assert line and "api_key" in line[0] and "string_too_short" in line[0]
