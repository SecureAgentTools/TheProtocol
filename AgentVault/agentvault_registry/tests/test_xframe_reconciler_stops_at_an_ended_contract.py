"""§DOCSFIX D6-461 (2026-10-16): the cross-frame contract reconciler stops at a contract that has ended.

`contract_xframe.TERMINAL` listed settled, cancelled and failed, while a contract (v2) ends completed, cancelled or
expired: every completed or expired replica stayed in `open_replicas` and was re-checked against its home registry
forever, taking its slot in each 60-second batch. An ended contract is terminal now (completed and expired join the
list; the older names stay). The reconciler's own statement runs against an in-memory SQLite table.

RED on the pre-change tree: the ended-contract test. The control is green before and after.
"""
from __future__ import annotations

import asyncio
import datetime

import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from agentvault_registry.services import contract_xframe as cx


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Db:
    def __init__(self, conn):
        self.conn = conn

    async def execute(self, stmt, params=None):
        return self.conn.execute(stmt, params or {})


def _replicas(statuses):
    eng = sa.create_engine("sqlite://", poolclass=StaticPool)
    conn = eng.connect()
    conn.execute(sa.text("CREATE TABLE contract_replicas (cid TEXT PRIMARY KEY, home_registry TEXT, digest TEXT, "
                         "seq INTEGER, status TEXT, last_synced_at TIMESTAMP)"))
    t0 = datetime.datetime(2026, 10, 16, 12, 0, 0)
    for i, st in enumerate(statuses):
        conn.execute(sa.text("INSERT INTO contract_replicas VALUES (:c, 'eu', 'd', 1, :s, :t)"),
                     {"c": f"ctr_{st}", "s": st, "t": t0 + datetime.timedelta(seconds=i)})
    return _Db(conn)


def test_a_completed_or_expired_replica_is_no_longer_reconciled():
    db = _replicas(["completed", "expired", "agreed"])
    assert [r["cid"] for r in _run(cx.open_replicas(db))] == ["ctr_agreed"]


# ── control: green before and after ──────────────────────────────────────────────────────────────────────────────

def test_control_open_and_disputed_replicas_are_reconciled_and_cancelled_ones_are_not():
    db = _replicas(["offered", "agreed", "in_progress", "disputed", "cancelled", "settled", "failed"])
    assert [r["cid"] for r in _run(cx.open_replicas(db))] == [
        "ctr_offered", "ctr_agreed", "ctr_in_progress", "ctr_disputed"]
