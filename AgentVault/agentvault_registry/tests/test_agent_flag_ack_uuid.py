"""§MCPSWEEP 2026-09-27 — acknowledging an agent flag answered 500 for every id.

`agent_flags.id` is a UUID column (mig 0068 creates it in raw SQL) and the model mapped it as String(36), so the
acknowledge route's lookup bound the id as VARCHAR and Postgres refused `uuid = character varying`. Measured on
sbx-alpha (V0462) through the admin MCP bridge: a well-formed UUID and a made-up string both answered 500
DATABASE_ERROR, so no admin could ever acknowledge a flag. Pinned by compiling the route's own statement with the
asyncpg dialect, which renders every bind's type: the id must bind as UUID, and a control proves the check can fail.
An id that is not a UUID names no flag: 404 before any query.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentvault_registry.routers import agent_flags_admin as afa  # noqa: E402

_ID_AS_UUID = re.compile(r"agent_flags\.id = \$\d+::UUID\b")
_A_UUID = "00000000-0000-4000-8000-000000000000"


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.asyncpg.dialect()))


def test_the_lookup_binds_the_flag_id_as_uuid():
    sql = _sql(afa._flag_lookup_stmt("did:theprotocol:x", _A_UUID))
    assert _ID_AS_UUID.search(sql), sql


def test_control_a_text_mapped_id_fails_the_check():
    t = sa.table("agent_flags", sa.column("id", sa.String(36)))
    sql = _sql(sa.select(t).where(t.c.id == _A_UUID))
    assert "::VARCHAR" in sql and not _ID_AS_UUID.search(sql), sql


class _NoQuery:
    async def execute(self, *a, **k):
        raise AssertionError("a flag id that is not a UUID must be refused before any query")


def test_an_id_that_is_not_a_uuid_is_404_without_a_query():
    with pytest.raises(HTTPException) as e:
        asyncio.run(afa.acknowledge_flag(did="did:theprotocol:x", flag_id="phase6-no-such-flag", notes=None,
                                         db=_NoQuery(), current_admin=object()))
    assert e.value.status_code == 404
    assert "Flag not found" in str(e.value.detail)


class _Empty:
    def __init__(self):
        self.statements = []

    async def execute(self, stmt, *a, **k):
        self.statements.append(stmt)

        class _R:
            def scalar_one_or_none(self):
                return None
        return _R()


def test_a_well_formed_unknown_id_reaches_the_typed_lookup_and_is_404():
    db = _Empty()
    with pytest.raises(HTTPException) as e:
        asyncio.run(afa.acknowledge_flag(did="did:theprotocol:x", flag_id=_A_UUID.upper(), notes=None,
                                         db=db, current_admin=object()))
    assert e.value.status_code == 404
    assert len(db.statements) == 1
    sql = _sql(db.statements[0])
    assert _ID_AS_UUID.search(sql), sql
