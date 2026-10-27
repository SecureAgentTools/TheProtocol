"""§MCPTEST30 (V0524, 2026-10-01) — a NUL the database refuses is the caller's 422, never a 500.

Postgres refuses a NUL in text ("invalid byte sequence for encoding "UTF8": 0x00") and in jsonb ("unsupported Unicode
escape sequence"). V0523 refuses one in a path or a query at the edge; a write's JSON body reaches the database, and the
SQLAlchemy handler answered it 500 "A database error occurred" (measured: /api/v1/discover before V0523).
"""
from __future__ import annotations

import asyncio
import json

from sqlalchemy.exc import DBAPIError
from starlette.requests import Request

from agentvault_registry.errors import sqlalchemy_error_handler


def _req():
    return Request({"type": "http", "method": "POST", "path": "/api/v1/organizations/o/teams", "headers": [],
                    "query_string": b""})


def _answer(msg):
    r = asyncio.run(sqlalchemy_error_handler(_req(), DBAPIError("INSERT INTO teams", {}, Exception(msg))))
    return r.status_code, json.loads(r.body)


def test_a_nul_in_text_is_422():
    st, body = _answer('invalid byte sequence for encoding "UTF8": 0x00')
    assert st == 422 and body["error"]["code"] == "NUL_IN_TEXT"
    assert body["detail"] == "A text value carries a NUL character, which this registry cannot store or search for."


def test_a_nul_in_jsonb_is_422():
    st, body = _answer("unsupported Unicode escape sequence")
    assert st == 422 and body["error"]["code"] == "NUL_IN_TEXT"


def test_another_byte_sequence_and_other_errors_stay_500():
    assert _answer('invalid byte sequence for encoding "UTF8": 0xc3 0x28')[0] == 500
    assert _answer("connection reset by peer")[0] == 500
