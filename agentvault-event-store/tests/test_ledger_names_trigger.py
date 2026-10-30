"""W4 phase 1 (agentvault2-aa, 2026-10-25): the projection trigger applies a typed event under its new name as its old one.

His words that day to agentvault2-69: "i want the illegal wording completly gone before opening" and, on the ledger, "just
use the new wording and make it accept both or something" (sessionlogs2026/PLAN_2026-10-25_COMPLIANT_OPENING.md, W4).
Integration test of the REAL trigger (src/migrations/materialized_balances.sql, applied whole) against a THROWAWAY
database from DATABASE_URL, one schema per store, dropped at the end, as tests/test_projection_negative_mark.py does.

  1. a store without single_writer (a fresh store's default) projects a history written under the new names
     (UnitsIssued, UnitsTransferred, UnitsLocked, UnitsUnlocked, LockPayoutsRelocked, LockPayoutsDistributed,
     UnitsBridgeLocked) to the same balances, counts and supply summary as the same history under the old names;
  2. a legacy spelling (TokenTransferred) moves nothing, as before;
  3. under single_writer (every running store, measured 2026-10-25) a typed event is audit-only under either name, and a
     LedgerBalanceChanged still applies.
Control, run 2026-10-25 on the SQL before this change: case 1 FAILS (the new names fell to the CASE's ELSE and projected
nothing); cases 2 and 3 pass on both. Runner exits non-zero on any failure.

Run:  python tests/test_ledger_names_trigger.py   (DATABASE_URL names a throwaway Postgres; asyncpg installed)
The scenarios are named case_* so a whole-directory pytest run collects none of them; this file is its own runner.
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
    aggregate_type VARCHAR(50) NOT NULL DEFAULT 'Agent',
    data JSONB NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    version INTEGER NOT NULL DEFAULT 1,
    source_service VARCHAR(50) NOT NULL DEFAULT 'registry'
)
"""

RENAMED = {"TokensIssued": "UnitsIssued", "TokensTransferred": "UnitsTransferred", "TokensStaked": "UnitsLocked",
           "TokensUnstaked": "UnitsUnlocked", "RewardsAutoCompounded": "LockPayoutsRelocked",
           "RewardsDistributed": "LockPayoutsDistributed", "TokensBridgeLocked": "UnitsBridgeLocked"}
A, B = "did:theprotocol:w4t-a", "did:theprotocol:w4t-b"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _with_store(body, single_writer=False):
    schema = f"w4n_{uuid.uuid4().hex[:10]}"
    admin = await asyncpg.connect(DSN)
    await admin.execute(f"CREATE SCHEMA {schema}")
    con = await asyncpg.connect(DSN, server_settings={"search_path": schema})
    try:
        await con.execute(EVENTS_DDL)
        await con.execute(SQL)
        await con.execute("UPDATE projection_config SET single_writer = $1 WHERE id = 1", single_writer)
        return await body(con)
    finally:
        await con.close()
        await admin.execute(f"DROP SCHEMA {schema} CASCADE")
        await admin.close()


def _history(new_names: bool):
    n = (lambda t: RENAMED.get(t, t)) if new_names else (lambda t: t)
    return [
        (n("TokensIssued"), A, {"amount": "100"}),
        (n("TokensTransferred"), A, {"from": A, "to": B, "amount": "30"}),
        ("TransactionFeeCollected", A, {"fee_amount": "0.15"}),
        (n("TokensStaked"), A, {"amount": "20"}),
        (n("TokensUnstaked"), A, {"amount": "5"}),
        (n("TokensIssued"), A, {"amount": "1.25"}),
        (n("RewardsAutoCompounded"), A, {"amount": "1.25"}),
        (n("RewardsDistributed"), A, {"amount": "1.25"}),
        (n("TokensBridgeLocked"), A, {"amount": "2"}),
        ("DisputeSlash", B, {"amount": "1"}),
    ]


async def _insert(con, rows):
    for t, agg, data in rows:
        await con.execute("INSERT INTO events (id, event_type, aggregate_id, data) VALUES ($1, $2, $3, $4)",
                          uuid.uuid4(), t, agg, json.dumps(data))


async def _state(con):
    rows = await con.fetch("SELECT agent_did, liquid_balance, staked_balance, event_count FROM materialized_balances "
                           "ORDER BY agent_did")
    s = await con.fetchrow("SELECT tokens_issued, tokens_destroyed, tokens_minted_compensation, transit_net "
                           "FROM supply_summary WHERE id = 1")
    return [tuple(r) for r in rows], tuple(s)


def _projected(new_names: bool, single_writer=False):
    async def body(con):
        await _insert(con, _history(new_names))
        return await _state(con)
    return _run(_with_store(body, single_writer))


def case_new_names_project_as_the_old_without_single_writer():
    old, new = _projected(False), _projected(True)
    assert new == old, f"\nold {old}\nnew {new}"
    rows, supply = old
    by = {r[0]: r[1:] for r in rows}
    assert by[A] == (Decimal("54.85"), Decimal("16.25"), 7), by[A]
    assert by[B] == (Decimal("29"), Decimal("0"), 2), by[B]
    assert by["teg:system:fee_collector"] == (Decimal("0.15"), Decimal("0"), 1)
    assert supply == (Decimal("101.25"), Decimal("1"), Decimal("0"), Decimal("0")), supply


def case_a_legacy_spelling_moves_nothing():
    async def body(con):
        await _insert(con, [("TokenTransferred", A, {"from": A, "to": B, "amount": "7"})])
        return await _state(con)
    rows, supply = _run(_with_store(body))
    assert rows == [] and supply == (0, 0, 0, 0), (rows, supply)


def case_under_single_writer_a_typed_event_is_audit_only_under_either_name():
    async def body(con):
        await _insert(con, _history(True) + _history(False))
        before = await _state(con)
        data = {"txid": 1, "frame": "teg-w4", "kind": "transfer", "net": "0",
                "entries": [{"agent_did": A, "delta_liquid": "-3", "delta_staked": "0"},
                            {"agent_did": B, "delta_liquid": "3", "delta_staked": "0"}]}
        await con.execute("INSERT INTO events (id, event_type, aggregate_id, data) VALUES ($1, 'LedgerBalanceChanged', "
                          "'ledger-tx-w4', $2)", uuid.uuid4(), json.dumps(data))
        return before, await _state(con)
    before, after = _run(_with_store(body, single_writer=True))
    assert before == ([], (0, 0, 0, 0)), before
    by = {r[0]: r[1:] for r in after[0]}
    assert by == {A: (Decimal("-3"), Decimal("0"), 1), B: (Decimal("3"), Decimal("0"), 1)}, by


CASES = [
    case_new_names_project_as_the_old_without_single_writer,
    case_a_legacy_spelling_moves_nothing,
    case_under_single_writer_a_typed_event_is_audit_only_under_either_name,
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
