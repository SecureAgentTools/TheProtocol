"""§LEDGERGATE E (2026-10-11): the projection marks an agent below zero, never refuses the event, never moves Δ.

Integration test of the REAL trigger (src/migrations/materialized_balances.sql, applied whole) against a THROWAWAY
database from DATABASE_URL, inside its own schema, dropped at the end. LedgerBalanceChanged events are inserted the
way the store inserts them; the test reads materialized_balances, projection_negative_log and supply_summary back.

  1. a delta that takes an agent below zero is applied (the ledger is append-only), marks negative_since and logs ONE
     row; more deltas while it stays below zero log nothing more and keep the first mark;
  2. the balance back at or above zero clears the mark; going below again logs a second row;
  3. the supply summary is exactly what it would be without the mark (Δ-neutral: transit_net = the sum of the nets);
  4. a note that cannot be written (the log table gone) loses the note, never the event.

Controls, run 2026-10-11 on Postgres 18.6: the SQL before this change fails all four; with the `negative_since = CASE
...` clause removed from the upsert's UPDATE, test 2 FAILS (the mark is never cleared; test 1 still passes, its first
mark comes from the INSERT branch); with the EXCEPTION block removed, test 4 FAILS (the event insert raises). Runner
exits non-zero on any failure.

Run:  python tests/test_projection_negative_mark.py   (DATABASE_URL names a throwaway Postgres; asyncpg installed)
The scenarios are named case_* so a whole-directory pytest run (the image builds' gate, with a dummy DATABASE_URL)
collects none of them; this file is its own runner, as test_supply_invariant.py is.
"""
import asyncio
import json
import os
import re
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import asyncpg

SQL = (Path(__file__).resolve().parents[1] / "src" / "migrations" / "materialized_balances.sql").read_text()
DSN = re.sub(r"^postgresql\+\w+://", "postgresql://", os.environ.get("DATABASE_URL", ""))

EVENTS_DDL = """
CREATE TABLE events (
    id UUID PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    aggregate_id VARCHAR(255) NOT NULL,
    aggregate_type VARCHAR(50) NOT NULL DEFAULT 'Ledger',
    data JSONB NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    version INTEGER NOT NULL DEFAULT 1,
    source_service VARCHAR(50) NOT NULL DEFAULT 'teg-balance-outbox'
)
"""


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _with_store(body):
    schema = f"pneg_{uuid.uuid4().hex[:10]}"
    admin = await asyncpg.connect(DSN)
    await admin.execute(f"CREATE SCHEMA {schema}")
    con = await asyncpg.connect(DSN, server_settings={"search_path": schema})
    try:
        await con.execute(EVENTS_DDL)
        await con.execute(SQL)
        return await body(con)
    finally:
        await con.close()
        await admin.execute(f"DROP SCHEMA {schema} CASCADE")
        await admin.close()


async def _ledger(con, entries, kind="transfer", frame="teg-pneg"):
    """One LedgerBalanceChanged, one transaction, as the store inserts it."""
    net = sum(Decimal(str(e[1])) + Decimal(str(e[2] if len(e) > 2 else 0)) for e in entries)
    data = {"txid": 1, "frame": frame, "kind": kind, "net": str(net),
            "entries": [{"agent_did": e[0], "delta_liquid": str(e[1]),
                         "delta_staked": str(e[2] if len(e) > 2 else 0)} for e in entries]}
    async with con.transaction():
        await con.execute("INSERT INTO events (id, event_type, aggregate_id, data) VALUES ($1, 'LedgerBalanceChanged', $2, $3)",
                          uuid.uuid4(), f"ledger-tx-{uuid.uuid4().hex[:8]}", json.dumps(data))


async def _row(con, did):
    return await con.fetchrow("SELECT liquid_balance, staked_balance, negative_since FROM materialized_balances "
                              "WHERE agent_did = $1", did)


async def _logs(con, did):
    return await con.fetchval("SELECT count(*) FROM projection_negative_log WHERE agent_did = $1", did)


def case_a_delta_below_zero_is_applied_and_marked_once():
    async def body(con):
        await _ledger(con, [("did:a", 5), ("did:b", -5)])         # b arrives first with only its debit: behind
        r = await _row(con, "did:b")
        assert r["liquid_balance"] == Decimal(-5) and r["negative_since"] is not None, dict(r)
        assert await _logs(con, "did:b") == 1
        first = r["negative_since"]
        await _ledger(con, [("did:b", -1), ("did:c", 1)])          # still below zero
        r = await _row(con, "did:b")
        assert r["liquid_balance"] == Decimal(-6) and r["negative_since"] == first, dict(r)
        assert await _logs(con, "did:b") == 1, "one note per episode, never one per event"
        r = await _row(con, "did:a")
        assert r["negative_since"] is None and await _logs(con, "did:a") == 0
    _run(_with_store(body))


def case_back_above_zero_clears_and_a_new_episode_logs_again():
    async def body(con):
        await _ledger(con, [("did:b", -5), ("did:a", 5)])
        await _ledger(con, [("did:b", 5), ("did:a", -5)])          # the missing credit landed
        r = await _row(con, "did:b")
        assert r["liquid_balance"] == 0 and r["negative_since"] is None, dict(r)
        await _ledger(con, [("did:b", 0, -2), ("did:a", 0, 2)])    # staked below zero is a mark too
        r = await _row(con, "did:b")
        assert r["staked_balance"] == Decimal(-2) and r["negative_since"] is not None, dict(r)
        assert await _logs(con, "did:b") == 2
    _run(_with_store(body))


def case_the_supply_summary_is_untouched_by_the_mark():
    async def body(con):
        await _ledger(con, [("did:m", 100)], kind="mint")
        await _ledger(con, [("did:m", -30), ("did:n", 30)])
        await _ledger(con, [("did:x", -7)])                        # a single-sided leg (a cross-frame debit)
        s = await con.fetchrow("SELECT tokens_issued, tokens_destroyed, transit_net FROM supply_summary WHERE id = 1")
        total = await con.fetchval("SELECT sum(liquid_balance + staked_balance) FROM materialized_balances")
        assert s["tokens_issued"] == 100 and s["tokens_destroyed"] == 0 and s["transit_net"] == Decimal(-7), dict(s)
        assert s["tokens_issued"] - s["tokens_destroyed"] + s["transit_net"] == total == Decimal(93)
        assert (await _row(con, "did:x"))["negative_since"] is not None
    _run(_with_store(body))


def case_a_note_that_cannot_be_written_never_costs_the_event():
    async def body(con):
        await con.execute("DROP TABLE projection_negative_log")
        await _ledger(con, [("did:q", -3), ("did:r", 3)])           # must not raise
        r = await _row(con, "did:q")
        assert r["liquid_balance"] == Decimal(-3) and r["negative_since"] is not None, dict(r)
        assert await con.fetchval("SELECT count(*) FROM events") == 1
    _run(_with_store(body))


CASES = [
    case_a_delta_below_zero_is_applied_and_marked_once,
    case_back_above_zero_clears_and_a_new_episode_logs_again,
    case_the_supply_summary_is_untouched_by_the_mark,
    case_a_note_that_cannot_be_written_never_costs_the_event,
]

if __name__ == "__main__":
    if not DSN:
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
