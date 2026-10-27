"""§DOCSFIX D6-674 (2026-10-16): a suite's runs reach every target in turn, least recently evaluated first.

A run evaluates at most EVAL_MAX_AGENTS_PER_TICK agents (8 by default) and took the first ones of its target list every
time, so an agent past the eighth was never evaluated by that suite; with no list it read 50 active native cards in no
fixed order. Targets are now ordered by the suite's last result for each (never-evaluated first, then the oldest), in
the explicit list and in the default query alike. Driven through EvalRunner.run_suite with a recording session.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from agentvault_registry.background_tasks import eval_runner as ER

T0 = dt.datetime(2026, 10, 16, tzinfo=dt.timezone.utc)
DIDS = [f"did:theprotocol:x:{i}" for i in range(10)]


class _Session:
    """Answers run_suite: its task list, then (when asked) each target's last result for the suite."""

    def __init__(self, last):
        self.last = last
        self.sql = []

    async def execute(self, stmt, params=None):
        try:
            sql = str(stmt.compile(dialect=postgresql.dialect()))
        except Exception:
            sql = str(stmt)
        self.sql.append(" ".join(sql.split()))
        if "FROM eval_tasks" in sql:
            task = SimpleNamespace(id=1, scorer="http_status", expected={}, input={}, weight=1.0)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [task]))
        if "FROM eval_results" in sql and "max(created_at)" in sql:
            rows = [(d, t) for d, t in self.last.items() if d in (params or {}).get("d", [])]
            return SimpleNamespace(fetchall=lambda: rows)
        return SimpleNamespace(fetchall=lambda: [], first=lambda: None)

    def add(self, obj):
        pass

    async def commit(self):
        pass


def _run(last, monkeypatch):
    seen = []

    async def _one(self, suite, task, did, endpoint, db=None, pay_slot=None):
        seen.append(did)
        return (1.0, True, 5, "ok", None)

    async def _endpoint(self, db, did):
        return "https://agent.example"

    monkeypatch.setattr(ER.EvalRunner, "_run_one", _one)
    monkeypatch.setattr(ER.EvalRunner, "_agent_endpoint", _endpoint)
    suite = SimpleNamespace(id=4, key="probe", target_dids=list(DIDS), emit_reputation_signal=False, pay_per_task=0)
    db = _Session(last)
    asyncio.run(ER.EvalRunner().run_suite(db, suite))
    return seen, db


def test_agents_never_evaluated_come_first_then_the_oldest(monkeypatch):
    # d0..d7 were evaluated (d7 longest ago); d8, d9 never
    last = {DIDS[i]: T0 + dt.timedelta(minutes=i * -10) for i in range(8)}
    seen, _ = _run(last, monkeypatch)
    assert seen[:2] == [DIDS[8], DIDS[9]], seen
    assert seen[2:] == [DIDS[7], DIDS[6], DIDS[5], DIDS[4], DIDS[3], DIDS[2]], seen
    assert len(seen) == ER.EVAL_MAX_AGENTS_PER_TICK


def test_the_default_target_query_orders_by_the_suites_last_result():
    async def _targets():
        db = _Session({})
        await ER.EvalRunner()._resolve_targets(db, SimpleNamespace(id=4, target_dids=None))
        return db.sql
    sql = asyncio.run(_targets())[0]
    assert "FROM agent_cards" in sql and "eval_results" in sql, sql
    assert "NULLS FIRST" in sql, sql
