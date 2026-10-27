"""§FESUITE (V0531): a credential check that cannot reach the database answers 503, never 401.

Measured on sbx-alpha 2026-10-01 16:55Z during the console suite's admin sweep: at the frame's connection ceiling
("sorry, too many clients already") the token_version read inside verify_access_token_required raised, the catch-all
answered 401 "Could not validate credentials", and the console - which signs out on a 401 - was told a live session
was dead. An API key fared the same: the crud lookup returned None on any error, which every caller reads as "no such
key". The same catch-all also caught the verifier's OWN 401s and logged each revoked token as an unexpected ERROR.

DB-free: the verifier is called directly with a fake session and a real Starlette Request.
"""
import logging

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from starlette.requests import Request

from agentvault_registry import security
from agentvault_registry.crud import developer as developer_crud


def _req() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/api/v1/developers/me", "query_string": b"",
                    "headers": [], "client": ("8.8.8.8", 4321)})


class _DownDB:
    """A session whose every statement fails the way a frame at its connection ceiling does."""

    def __init__(self):
        self.rollbacks = 0

    async def execute(self, *_a, **_k):
        raise OperationalError("SELECT 1", {}, Exception("sorry, too many clients already"))

    async def rollback(self):
        self.rollbacks += 1

    async def commit(self):
        return None

    def add(self, _obj):
        return None


class _Result:
    def __init__(self, scalar):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _DB:
    """Answers the token_version read with the given value."""

    def __init__(self, tv):
        self._tv = tv

    async def execute(self, *_a, **_k):
        return _Result(self._tv)


@pytest.mark.asyncio
async def test_a_jwt_whose_token_version_cannot_be_read_is_a_503():
    token = security.create_access_token(data={"sub": "42"}, token_version=3)
    with pytest.raises(HTTPException) as ei:
        await security.verify_access_token_required(_req(), token=token, db=_DownDB())
    assert ei.value.status_code == 503
    assert (ei.value.headers or {}).get("Retry-After") == "5"


@pytest.mark.asyncio
async def test_an_api_key_that_cannot_be_looked_up_is_a_503():
    with pytest.raises(HTTPException) as ei:
        await security.verify_access_token_required(_req(), token="avreg_" + "a" * 40, db=_DownDB())
    assert ei.value.status_code == 503


@pytest.mark.asyncio
async def test_the_crud_lookup_raises_a_database_error_instead_of_answering_no_such_key():
    db = _DownDB()
    with pytest.raises(OperationalError):
        await developer_crud.get_developer_by_plain_api_key(db=db, plain_key="avreg_" + "b" * 40)
    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_a_revoked_token_is_still_a_401_and_not_logged_as_unexpected(caplog):
    token = security.create_access_token(data={"sub": "42"}, token_version=3)
    caplog.set_level(logging.INFO)
    with pytest.raises(HTTPException) as ei:
        await security.verify_access_token_required(_req(), token=token, db=_DB(tv=4))
    assert ei.value.status_code == 401
    assert "token_version mismatch" in caplog.text
    assert "Unexpected error during JWT decode/validation" not in caplog.text


@pytest.mark.asyncio
async def test_a_live_token_still_passes():
    token = security.create_access_token(data={"sub": "42"}, token_version=3)
    assert await security.verify_access_token_required(_req(), token=token, db=_DB(tv=3)) == 42
