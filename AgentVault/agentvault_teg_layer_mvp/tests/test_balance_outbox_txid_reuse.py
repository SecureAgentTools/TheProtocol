"""§PG18XID (2026-09-29): a balance-change group whose txid an earlier journal row already carries gets its own key.

MEASURED on the sandbox, which is why this exists: four TEG databases moved to Postgres 18 by dump/restore into new
clusters, and txid_current() restarted near 750 while the journal and the event store held txids up to 1,046,447. The
outbox keyed each group `ledger-tx-{teg_id}-{txid}`, the store's Kafka consumer skipped every reused key as a duplicate
without comparing payloads, and 80 balance changes never reached the projection (sbx-alpha: 74 groups, 37 accounts,
supply delta still 0). A group that reuses history is now keyed `...-{txid}-j{first journal id}`; everything else keeps
the key it always had, so normal operation and retries are unchanged.

Integration test (real Postgres, the outbox's own SQL) against a THROWAWAY database from DATABASE_URL, inside its own
schema, dropped at the end. Mutation-verify: with the EXISTS clause in SELECT_GROUPS_SQL replaced by FALSE, the first
test FAILS (the reused group keeps the old key). Runner exits non-zero on any failure.

Run:  python tests/test_balance_outbox_txid_reuse.py   (inside a container with the TEG deps)
"""
import asyncio
import os
import re
import sys
import uuid
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, "/app")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.teg_core_service.core.balance_outbox import (
    SELECT_GROUPS_SQL, counter_behind_history, ledger_event_key,
)

TEG = "teg-test"
_raw = os.environ.get("DATABASE_URL") or os.environ["DATABASE_URL_SYNC"]
DB_URL = re.sub(r"^postgresql(\+\w+)?://", "postgresql+asyncpg://", _raw)


def _journal_ddl() -> list:
    """The journal's REAL table and indexes, cut from the migration the TEG runs (never a copy that can drift)."""
    here = Path(__file__).resolve().parents[1]
    for cand in (here / "src" / "teg_core_service" / "migrations" / "balance_journal.sql",
                 Path("/app/src/teg_core_service/migrations/balance_journal.sql")):
        if cand.is_file():
            sql = cand.read_text()
            break
    else:
        raise AssertionError("balance_journal.sql not found in the repo or image layout")
    table = re.search(r"CREATE TABLE IF NOT EXISTS balance_ledger_journal \(.*?\n\);", sql, re.S).group(0)
    indexes = re.findall(r"CREATE INDEX IF NOT EXISTS [^;]+;", sql)
    assert any("(txid)" in i for i in indexes), "the txid index the reuse test relies on is gone"
    return [re.sub(r"--[^\n]*", "", table)] + indexes


def _run(coro):
    """A private loop, closed after: asyncio.run() would unset the thread's loop for whatever runs next."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _with_schema(body):
    schema = f"obx_{uuid.uuid4().hex[:10]}"
    admin = create_async_engine(DB_URL)
    async with admin.begin() as c:
        await c.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_async_engine(DB_URL, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with eng.begin() as c:
            for stmt in _journal_ddl():
                await c.execute(text(stmt))
        return await body(eng)
    finally:
        await eng.dispose()
        async with admin.begin() as c:
            await c.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()


async def _insert(c, agent, txid, dl, emitted):
    await c.execute(text(
        "INSERT INTO balance_ledger_journal (agent_id, txid, delta_liquid, new_liquid, entry_type, emitted_at) "
        "VALUES (:a, :t, :d, 0, 'transfer', CASE WHEN :e THEN now() END)"),
        {"a": agent, "t": txid, "d": Decimal(str(dl)), "e": bool(emitted)})


def test_a_group_that_reuses_an_old_txid_gets_its_own_key():
    async def body(eng):
        async with eng.begin() as c:
            # the old cluster's history, emitted long ago
            await _insert(c, "did:a", 1000, 10, True)
            await _insert(c, "did:a", 1001, -5, True)
            await _insert(c, "did:b", 1001, 5, True)
            # after the restore: a new transaction reuses txid 1001; another has a txid no row ever carried
            await _insert(c, "did:c", 1001, 7, False)
            await _insert(c, "did:d", 2000, 1, False)
        async with eng.connect() as c:
            rows = (await c.execute(SELECT_GROUPS_SQL, {"glim": 200})).fetchall()
        groups = {}
        for (_id, agent, txid, _dl, _dk, _et, first_id, reuses) in rows:
            groups.setdefault(txid, (first_id, bool(reuses), []))[2].append(agent)
        assert set(groups) == {1001, 2000}, groups
        first, reuses, agents = groups[1001]
        assert reuses and agents == ["did:c"], groups[1001]
        key = ledger_event_key(TEG, 1001, first, reuses)
        assert key == f"ledger-tx-{TEG}-1001-j{first}" and key != f"ledger-tx-{TEG}-1001", key
        first2, reuses2, _ = groups[2000]
        assert not reuses2 and ledger_event_key(TEG, 2000, first2, reuses2) == f"ledger-tx-{TEG}-2000"
    _run(_with_schema(body))


def test_the_rows_of_one_transaction_are_not_history():
    """Several rows of ONE transaction share its txid; the group's own rows must never flag it."""
    async def body(eng):
        async with eng.begin() as c:
            await _insert(c, "did:s", 3000, -10, False)
            await _insert(c, "did:r", 3000, 9, False)
            await _insert(c, "teg:system:fee_collector", 3000, 1, False)
        async with eng.connect() as c:
            rows = (await c.execute(SELECT_GROUPS_SQL, {"glim": 200})).fetchall()
        assert len(rows) == 3 and not any(r[7] for r in rows), rows
    _run(_with_schema(body))


def test_the_counter_below_the_journal_is_reported_and_above_it_is_not():
    async def body(eng):
        async with eng.begin() as c:
            await _insert(c, "did:a", 5_000_000_000, 1, True)   # far above any throwaway cluster's counter
        async with eng.connect() as c:
            behind, nxt, jmax = await counter_behind_history(c)
        assert behind and jmax == 5_000_000_000 and nxt < jmax, (behind, nxt, jmax)
        async with eng.begin() as c:
            await c.execute(text("DELETE FROM balance_ledger_journal"))
            await _insert(c, "did:a", 1, 1, True)
        async with eng.connect() as c:
            behind, nxt, jmax = await counter_behind_history(c)
        assert not behind and nxt > jmax, (behind, nxt, jmax)
    _run(_with_schema(body))


def test_the_keys_of_normal_operation_are_byte_identical_to_before():
    # the pre-§PG18XID code: f"ledger-tx-{teg}-{txid}" and, for a legacy NULL txid, f"ledger-tx-{teg}-null-{ids[0]}"
    assert ledger_event_key(TEG, 123, 9, False) == f"ledger-tx-{TEG}-123"
    assert ledger_event_key(TEG, None, 7, False) == f"ledger-tx-{TEG}-null-7"


TESTS = [
    test_a_group_that_reuses_an_old_txid_gets_its_own_key,
    test_the_rows_of_one_transaction_are_not_history,
    test_the_counter_below_the_journal_is_reported_and_above_it_is_not,
    test_the_keys_of_normal_operation_are_byte_identical_to_before,
]

if __name__ == "__main__":
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            import traceback
            print(f"FAIL  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
