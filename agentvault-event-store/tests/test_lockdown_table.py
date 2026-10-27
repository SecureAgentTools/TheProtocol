"""D6-298 (2026-10-16): the lockdown row in a real Postgres, as two workers of one store see it.

Integration test of DatabaseLockdownStore (src/services/lockdown_state.py, its SQL as written) against a THROWAWAY
database from DATABASE_URL, each case inside its own schema, dropped at the end. Two workers are two engines (two
connection pools, as two uvicorn processes have), each with its own LockdownState reading the row every time
(cache_seconds=0).

  1. a lockdown taken through one worker is read by the other, with its reason, author and time; the clear lifts it
     for both and reports what it lifted;
  2. a second activation changes nothing: the first lockdown stays;
  3. a worker started after the lockdown (a restart) reads it;
  4. a store whose table does not exist yet reads as never locked, and the first activation creates the table;
  5. a clear on a store never locked reports nothing lifted and writes no row.

Run 2026-10-16 on Postgres 18.6 and 15.19 (the CI job's Debian release): 5/5. Control on 18.6: with
`WHERE l.is_active = false` removed from the activation's upsert, case 2 FAILS (the second activation overwrites the
first reason). The file before this change has no DatabaseLockdownStore at all. Runner exits non-zero on any failure.

Run:  python tests/test_lockdown_table.py   (DATABASE_URL names a throwaway Postgres; sqlalchemy[asyncio] and asyncpg)
The scenarios are named case_* so a whole-directory pytest run collects none of them; this file is its own runner,
as test_projection_negative_mark.py is.
"""
import asyncio
import importlib.util
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

LOCKDOWN = Path(__file__).resolve().parents[1] / "src" / "services" / "lockdown_state.py"
URL = os.environ.get("DATABASE_URL", "")
DSN = re.sub(r"^postgresql(\+\w+)?://", "postgresql+asyncpg://", URL)


def _lockdown_module():
    spec = importlib.util.spec_from_file_location("lockdown_state_under_test", LOCKDOWN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _with_store(body, create_table=True):
    """Run body(m, worker, engine, peek) in a fresh schema: worker() is a new worker on its own pool."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    m = _lockdown_module()
    schema = f"lockd_{uuid.uuid4().hex[:10]}"
    admin = create_async_engine(DSN)
    engines = []
    async with admin.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
        if create_table:
            await conn.execute(text(f"SET LOCAL search_path TO {schema}"))
            await conn.execute(text(m.TABLE_DDL))

    def engine():
        e = create_async_engine(DSN, connect_args={"server_settings": {"search_path": schema}})
        engines.append(e)
        return e

    def worker():
        return m.LockdownState(store=m.DatabaseLockdownStore(engine()), cache_seconds=0)

    async def peek():
        async with admin.connect() as conn:
            if not (await conn.execute(text(f"SELECT to_regclass('{schema}.eventstore_lockdown')"))).scalar():
                return None
            rows = (await conn.execute(text(f"SELECT * FROM {schema}.eventstore_lockdown"))).mappings().all()
            return [dict(r) for r in rows]

    try:
        return await body(m, worker, peek)
    finally:
        for e in engines:
            await e.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()


def case_a_lockdown_through_one_worker_stops_the_other():
    async def body(m, worker, peek):
        a, b = worker(), worker()
        assert await b.is_locked() is False
        assert await a.activate("supply breach: delta 5", "supply_auditor") is True
        assert await b.is_locked() is True
        assert (b.reason, b.triggered_by) == ("supply breach: delta 5", "supply_auditor")
        assert datetime.fromisoformat(b.triggered_at).tzinfo is not None, b.triggered_at
        assert (await a.clear()) == (True, "supply breach: delta 5")
        assert await b.is_locked() is False
        rows = await peek()
        assert len(rows) == 1 and rows[0]["is_active"] is False and rows[0]["reason"] is None, rows
    _run(_with_store(body))


def case_the_first_lockdown_stays():
    async def body(m, worker, peek):
        a, b = worker(), worker()
        assert await a.activate("first", "supply_auditor") is True
        assert await b.activate("second", "admin") is False
        assert (b.reason, b.triggered_by) == ("first", "supply_auditor")
        rows = await peek()
        assert [(r["reason"], r["triggered_by"]) for r in rows] == [("first", "supply_auditor")], rows
    _run(_with_store(body))


def case_a_worker_started_after_the_lockdown_reads_it():
    async def body(m, worker, peek):
        await worker().activate("supply breach", "supply_auditor")
        restarted = worker()
        assert restarted.is_active is False
        assert await restarted.is_locked() is True and restarted.reason == "supply breach"
    _run(_with_store(body))


def case_no_table_reads_unlocked_and_the_first_activation_creates_it():
    async def body(m, worker, peek):
        a = worker()
        assert await peek() is None
        assert await a.is_locked() is False                 # the read fails (no table): never locked, kept
        assert await a.activate("supply breach", "supply_auditor") is True
        assert len(await peek()) == 1
        assert await worker().is_locked() is True
    _run(_with_store(body, create_table=False))


def case_a_clear_on_a_store_never_locked_lifts_nothing():
    async def body(m, worker, peek):
        a = worker()
        assert (await a.clear()) == (False, None)
        assert await peek() == []
        assert await a.is_locked() is False
    _run(_with_store(body))


CASES = [
    case_a_lockdown_through_one_worker_stops_the_other,
    case_the_first_lockdown_stays,
    case_a_worker_started_after_the_lockdown_reads_it,
    case_no_table_reads_unlocked_and_the_first_activation_creates_it,
    case_a_clear_on_a_store_never_locked_lifts_nothing,
]

if __name__ == "__main__":
    if not URL:
        print("DATABASE_URL is not set: this test needs a throwaway Postgres")
        sys.exit(2)
    failed = 0
    for t in CASES:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            import traceback
            print(f"FAIL  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    sys.exit(1 if failed else 0)
