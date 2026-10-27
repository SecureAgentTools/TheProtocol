"""§LEDGERGATE (2026-10-11): the balance outbox measures the ledger every cycle and publishes one verdict.

Integration test of the REAL cycle (BalanceOutboxEmitter._cycle_once, its SQL and the journal measurement) against a
THROWAWAY database from DATABASE_URL, inside its own schema, dropped at the end. The event store and Redis are fakes
that record what they were asked: the store answers each group by a script (201, 422, no answer), so the test can
make the store healthy, reject one malformed group, or be out of reach, and read the verdict the gate would read.

  1. a healthy cycle emits every group, stamps the rows and publishes ok;
  2. a group the store rejects (422) is stuck: the others flow, the verdict is degraded (rejected_group), never
     unhealthy, and the stuck rows are not in the waiting age;
  3. a store out of reach: each cycle stops after three groups running could not reach it, the third cycle is
     unhealthy (store_unreachable), and two cycles clear of it after the store is back bring it to ok;
  4. a row waiting past 30 s (the store drains more slowly than work arrives) is unhealthy (waiting);
  5. a worker that becomes leader carries on from the published verdict (no reset of the hysteresis), and a failed-
     cycle count with nothing left waiting cannot hold the verdict unhealthy.

Mutation-verify: with `obs.unreachable > 0` removed from Observation.failed_cycle, test 2 FAILS (a 422 cycle counts as
an outage); with the `rejected` branch removed from the cycle, test 2 FAILS (the poison group is waiting, then
unhealthy). Runner exits non-zero on any failure.

Run:  python tests/test_ledger_health_cycle.py   (inside a container with the TEG deps, PYTHONPATH naming src)
"""
import asyncio
import json
import os
import re
import sys
import uuid
from decimal import Decimal
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"   # the tree this test sits in (the image's /app, or a checkout)
if _SRC.is_dir():
    sys.path.insert(0, str(_SRC))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from teg_core_service import redis_client  # noqa: E402
from teg_core_service.core import balance_outbox as bo  # noqa: E402
from teg_core_service.core import ledger_health as lh  # noqa: E402
from teg_core_service.database import db_session  # noqa: E402

TEG = "teg-ledgerhealth-test"
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
    assert any("WHERE emitted_at IS NULL" in i for i in indexes), "the unemitted partial index is gone"
    return [re.sub(r"--[^\n]*", "", table)] + indexes


def _run(coro):
    """A private loop, closed after: asyncio.run() would unset the thread's loop for whatever runs next."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value
        return True

    async def get(self, key):
        return self.store.get(key)

    def verdict(self):
        return json.loads(self.store[lh.health_key(TEG)])


class FakeStore:
    """The event store, answering each group's emit by its txid: 'ok' (201), 'reject' (422), 'down' (no answer)."""

    def __init__(self, default="ok", by_txid=None):
        self.default, self.by_txid, self.calls = default, dict(by_txid or {}), []
        self.last_status = None

    async def emit(self, event_type, aggregate_id, data, aggregate_type="Agent", metadata=None, idempotency_key=None):
        self.calls.append(data.get("txid"))
        how = self.by_txid.get(data.get("txid"), self.default)
        if how == "ok":
            self.last_status = 201
            return True
        if how == "reject":
            self.last_status = 422
            return False
        self.last_status = None
        return False


async def _insert(c, agent, txid, dl, age_s=0):
    await c.execute(text(
        "INSERT INTO balance_ledger_journal (agent_id, txid, delta_liquid, new_liquid, entry_type, changed_at) "
        "VALUES (:a, :t, :d, 0, 'transfer', now() - make_interval(secs => :age))"),
        {"a": agent, "t": txid, "d": Decimal(str(dl)), "age": float(age_s)})


async def _transfer(c, txid, age_s=0):
    """One transfer = three rows in one transaction (sender, receiver, fee collector)."""
    await _insert(c, f"did:s{txid}", txid, -10, age_s)
    await _insert(c, f"did:r{txid}", txid, 9, age_s)
    await _insert(c, "teg:system:fee_collector", txid, 1, age_s)


async def _with_outbox(body):
    schema = f"lgh_{uuid.uuid4().hex[:10]}"
    admin = create_async_engine(DB_URL)
    async with admin.begin() as c:
        await c.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_async_engine(DB_URL, connect_args={"server_settings": {"search_path": schema}})
    saved = (db_session.AsyncSessionLocal, redis_client.get_redis, bo.GROUP_LIMIT)
    fake_redis = FakeRedis()

    async def _get_redis():
        return fake_redis
    try:
        async with eng.begin() as c:
            for stmt in _journal_ddl():
                await c.execute(text(stmt))
        db_session.AsyncSessionLocal = async_sessionmaker(eng, expire_on_commit=False)
        redis_client.get_redis = _get_redis
        ob = bo.BalanceOutboxEmitter()
        ob.teg_id = TEG
        ob._health = lh.HealthTracker(thresholds=lh.Thresholds(), interval_s=5.0)
        return await body(eng, ob, fake_redis)
    finally:
        db_session.AsyncSessionLocal, redis_client.get_redis, bo.GROUP_LIMIT = saved
        await eng.dispose()
        async with admin.begin() as c:
            await c.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()


async def _unemitted(eng):
    async with eng.connect() as c:
        return (await c.execute(text("SELECT count(*) FROM balance_ledger_journal WHERE emitted_at IS NULL"))).scalar()


def test_a_healthy_cycle_emits_and_publishes_ok():
    async def body(eng, ob, r):
        async with eng.begin() as c:
            await _transfer(c, 100)
            await _transfer(c, 101)
        ob._emitter = FakeStore("ok")
        await ob._cycle_once()
        v = r.verdict()
        assert (v["state"], v["reason"]) == (lh.OK, "ok"), v
        assert v["cycle"]["attempted"] == 2 and v["cycle"]["emitted"] == 2 and v["cycle"]["emitted_rows"] == 6, v
        assert v["waiting_rows"] == 0 and v["stuck_rows"] == 0 and v["oldest_waiting_age_s"] is None, v
        assert await _unemitted(eng) == 0
        # an empty cycle still publishes (the verdict stays alive while nothing happens)
        r.store.clear()
        await ob._cycle_once()
        assert r.verdict()["state"] == lh.OK
    _run(_with_outbox(body))


def test_a_rejected_group_is_stuck_and_the_rest_flows():
    async def body(eng, ob, r):
        async with eng.begin() as c:
            await _transfer(c, 200, age_s=900)   # the poison group: old, rejected every cycle
            await _transfer(c, 201)
        ob._emitter = FakeStore("ok", {200: "reject"})
        for _ in range(4):
            await ob._cycle_once()
            v = r.verdict()
            assert (v["state"], v["reason"]) == (lh.DEGRADED, "rejected_group"), v
            assert v["stuck_rows"] == 3 and v["oldest_stuck_age_s"] >= 899, v
            assert v["waiting_rows"] == 0 and v["oldest_waiting_age_s"] is None, v
            assert v["failed_cycles"] == 0, v
        assert await _unemitted(eng) == 3, "the rejected group stays unemitted (retried), the other one landed"
    _run(_with_outbox(body))


def test_an_unreachable_store_is_unhealthy_on_the_third_cycle_and_recovers():
    async def body(eng, ob, r):
        async with eng.begin() as c:
            for t in range(300, 310):
                await _transfer(c, t)
        store = FakeStore("down")
        ob._emitter = store
        states = []
        for _ in range(3):
            store.calls.clear()
            await ob._cycle_once()
            v = r.verdict()
            states.append((v["state"], v["reason"]))
            assert len(store.calls) == bo.BREAK_AFTER_FAILS == 3, ("a cycle stops after three groups running", store.calls)
        assert states == [(lh.DEGRADED, "store_failing"), (lh.DEGRADED, "store_failing"),
                          (lh.UNHEALTHY, "store_unreachable")], states
        assert r.verdict()["retry_after_s"] == 30
        store.default = "ok"
        await ob._cycle_once()                       # the store is back: every group lands
        assert await _unemitted(eng) == 0
        assert r.verdict()["state"] == lh.UNHEALTHY, "one clear cycle is not enough"
        await ob._cycle_once()                       # nothing left: clear again
        assert r.verdict()["state"] == lh.OK, r.verdict()
    _run(_with_outbox(body))


def test_a_row_waiting_past_the_age_is_unhealthy():
    async def body(eng, ob, r):
        async with eng.begin() as c:
            await _transfer(c, 400, age_s=50)
            await _transfer(c, 401, age_s=40)
        bo.GROUP_LIMIT = 1                            # the store drains one group a cycle; work waits behind it
        ob._emitter = FakeStore("ok")
        await ob._cycle_once()
        v = r.verdict()
        assert (v["state"], v["reason"]) == (lh.UNHEALTHY, "waiting"), v
        assert v["waiting_rows"] == 3 and v["oldest_waiting_age_s"] >= 39, v
        assert 10 <= v["retry_after_s"] <= 120, v
    _run(_with_outbox(body))


def test_a_new_leader_carries_on_from_the_published_verdict():
    async def body(eng, ob, r):
        published = lh.HealthTracker(thresholds=lh.Thresholds(), interval_s=5.0)
        for _ in range(3):
            published.observe(lh.Observation(waiting_rows=1, oldest_waiting_age_s=6.0, attempted=1, emitted=0,
                                             unreachable=1))
        await lh.publish(r, TEG, published.snapshot(), "old-leader", 5.0)
        await ob._seed_health()
        assert (ob._health.state, ob._health.reason, ob._health.failed_cycles) == (
            lh.UNHEALTHY, "store_unreachable", 3), ob._health.snapshot()
        ob._emitter = FakeStore("ok")
        await ob._cycle_once()                       # nothing waits: the count resets, the hysteresis holds
        v = r.verdict()
        assert (v["state"], v["failed_cycles"]) == (lh.UNHEALTHY, 0), v
        await ob._cycle_once()
        assert r.verdict()["state"] == lh.OK, "two clear cycles under the new leader"
    _run(_with_outbox(body))


TESTS = [
    test_a_healthy_cycle_emits_and_publishes_ok,
    test_a_rejected_group_is_stuck_and_the_rest_flows,
    test_an_unreachable_store_is_unhealthy_on_the_third_cycle_and_recovers,
    test_a_row_waiting_past_the_age_is_unhealthy,
    test_a_new_leader_carries_on_from_the_published_verdict,
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
