"""V0653 (am), item 7 (the hardening list in the sessions' room; found reading item 13): a refused request's VALUES never
reach the log.

errors.validation_exception_handler logged exc.errors() whole, and pydantic 2 puts the value it refused into each error
("input"), so a registration whose password was one character short wrote that password into the registry's log, which
Dozzle reads and the backups keep. The line keeps where and why (loc, type, msg); the answer to the caller never carried
the value. BASE (a5ef48ddd, V0652): the refused password is in the log.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from agentvault_registry import errors as E

PASSWORD = "Sh0rt!pw-11"          # 11 characters: one short of the rule


class _Register(BaseModel):
    email: str
    password: str = Field(min_length=12)


def _client():
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, E.validation_exception_handler)

    @app.post("/register")
    async def register(body: _Register):
        return {"ok": True}

    return TestClient(app)


def test_a_refused_password_never_reaches_the_log(caplog):
    with caplog.at_level(logging.DEBUG):
        r = _client().post("/register", json={"email": "someone@example.org", "password": PASSWORD})
    assert r.status_code == 422
    assert PASSWORD not in caplog.text
    assert PASSWORD not in r.text                         # the control: the answer never carried it


def test_the_line_still_says_where_and_why(caplog):
    with caplog.at_level(logging.DEBUG):
        _client().post("/register", json={"email": "someone@example.org", "password": PASSWORD})
    line = [m for m in caplog.messages if m.startswith("Validation error on POST /register")]
    assert line and "password" in line[0] and "string_too_short" in line[0]
