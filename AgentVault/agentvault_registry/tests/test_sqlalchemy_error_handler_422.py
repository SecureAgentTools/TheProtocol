"""§BATCH3 / B2 — a non-UUID (or otherwise unparseable) path parameter that reaches the database
answers 422, never 500. The release audit filed this as open; measured on registry-a (V0221,
2026-09-05) twelve admin routes already answer 404/422/405 for `not-a-uuid`, because
errors.sqlalchemy_error_handler has mapped asyncpg's DataError text to 422 since §pass73.1.
This pins the mapping so the OSS cut cannot lose it, with a control for the generic 500.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from agentvault_registry.errors import sqlalchemy_error_handler


def _req(path="/api/v1/admin/bundles/not-a-uuid/unhide", method="POST"):
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path), headers={}, state=SimpleNamespace(),
                           client=SimpleNamespace(host="127.0.0.1"))


def _run(exc):
    # §DEPS: pytest-asyncio 1.x leaves no current event loop for a synchronous test, so a shared-loop lookup
    # passes or fails by test order; a private loop does not depend on what ran before.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(sqlalchemy_error_handler(_req(), exc))
    finally:
        loop.close()


@pytest.mark.parametrize("message", [
    # asyncpg, a str bound to a uuid column
    "invalid input for query argument $1: 'not-a-uuid' (invalid UUID 'not-a-uuid': length must be between 32..36 characters, got 10)",
    # asyncpg, an int32 overflow on an int path param
    "invalid input for query argument $1: 2147483648 (value out of int32 range)",
    # postgres-side cast failure
    'invalid input syntax for type uuid: "not-a-uuid"',
])
def test_unparseable_parameter_is_a_422(message):
    exc = DBAPIError("SELECT 1", {}, Exception(message))
    resp = _run(exc)
    assert resp.status_code == 422, resp.body
    body = json.loads(resp.body)
    assert body["error"]["code"] == "PARAM_OUT_OF_RANGE" if "code" in body.get("error", {}) else body["status"] == 422


def test_control_a_real_database_error_stays_a_500():
    resp = _run(SQLAlchemyError("connection reset by peer"))
    assert resp.status_code == 500
