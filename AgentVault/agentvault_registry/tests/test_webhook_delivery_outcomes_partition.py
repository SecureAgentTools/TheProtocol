"""§DOCSFIX D6-786 (2026-10-17): the delivery outcomes partition every webhook delivery row, a 3xx included.

A 3xx answer is a failed attempt: redirects are not followed, the service schedules a retry and, since D6-765, the worker
runs it. The delivery lists still read "failed" as 4xx/5xx, so a 3xx row was listed as neither success nor failed, in
a developer's own list (GET /webhooks/{id}/deliveries?status=), the administrators' feed and its window counts, and the
"deliveries that never landed" view. One rule now (services/webhook_service.delivery_outcome_clause): success is a 2xx
answer, failed any other answer, pending no answer.

Each statement the code builds is run against an in-memory SQLite table holding one row per status class (no answer, 1xx,
2xx, 3xx, 4xx, 5xx); the routes are driven with a recording session. Nothing reaches a database or the network.
"""
from __future__ import annotations

import ast
import importlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import sqlite as sqlite_dialect

from agentvault_registry.routers import admin_health as AH
from agentvault_registry.routers import webhooks as W

WS = importlib.import_module("agentvault_registry.services.webhook_service")

STATUSES = [None, 101, 199, 200, 201, 204, 299, 300, 301, 302, 304, 307, 308, 399, 400, 401, 404, 410, 429, 500, 503, 599]
SUCCESS = {200, 201, 204, 299}
REDIRECTS = {300, 301, 302, 304, 307, 308, 399}
FAILED = set(STATUSES) - SUCCESS - {None}
DEVELOPERS_PY = Path(W.__file__).resolve().parent / "developers.py"


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE webhook_deliveries (id TEXT, webhook_id TEXT, event_type TEXT, response_status INTEGER, "
              "retry_count INTEGER, delivered_at TEXT)")
    c.execute("CREATE TABLE developer_webhooks (id TEXT, url TEXT, is_active BOOLEAN, developer_id INTEGER)")
    c.executemany("INSERT INTO webhook_deliveries VALUES (?, 'wh-1', 'webhook.test', ?, 0, '2026-10-17T01:00:00')",
                  [(f"d{i}", s) for i, s in enumerate(STATUSES)])
    c.execute("INSERT INTO developer_webhooks VALUES ('wh-1', 'https://hooks.example/in', 1, 7)")
    yield c
    c.close()


def _sql(clause) -> str:
    return str(clause.compile(dialect=sqlite_dialect.dialect(), compile_kwargs={"literal_binds": True}))


def _statuses(con, where) -> set:
    return {r[0] for r in con.execute(f"SELECT response_status FROM webhook_deliveries WHERE {_sql(where)}")}


def _assert_partition(found: dict):
    assert set().union(*found.values()) == set(STATUSES), "every row is in one of the outcomes"
    assert sum(len(v) for v in found.values()) == len(STATUSES), f"no row is in two outcomes: {found}"
    assert found["success"] == SUCCESS and found["pending"] == {None}
    assert found["failed"] == FAILED and REDIRECTS <= found["failed"]


class _Recording:
    """A session that keeps every statement and answers with nothing (scalar 0, no rows)."""

    def __init__(self):
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        rows = SimpleNamespace(all=lambda: [])
        return SimpleNamespace(scalar=lambda: 0, all=lambda: [], scalars=lambda: rows)


def test_the_rule_partitions_every_status_and_a_redirect_is_failed(con):
    _assert_partition({o: _statuses(con, WS.delivery_outcome_clause(o)) for o in WS.DELIVERY_OUTCOMES})


async def test_a_developers_own_list_filters_by_the_rule(con, monkeypatch):
    async def owned(*_a, **_k):
        return SimpleNamespace(id="wh-1")
    monkeypatch.setattr(W, "_get_owned_webhook", owned)
    found = {}
    for outcome in ("success", "failed", "pending"):
        db = _Recording()
        out = await W.list_deliveries("wh-1", limit=100, status_filter=outcome, developer=SimpleNamespace(id=7), db=db)
        assert out["deliveries"] == [] and len(db.statements) == 1
        found[outcome] = _statuses(con, db.statements[0].whereclause)
    _assert_partition(found)


async def test_the_administrators_feed_filters_by_the_rule(con):
    found = {}
    for outcome in ("success", "failed", "pending"):
        db = _Recording()
        out = await AH.get_webhooks_recent_deliveries(limit=100, status_filter=outcome, event_type=None, db=db,
                                                      _admin=None)
        assert len(db.statements) == 1, out
        found[outcome] = _statuses(con, db.statements[0].whereclause)
    _assert_partition(found)


async def test_the_administrators_window_counts_add_up_to_the_total(con):
    class _Counting(_Recording):
        async def execute(self, stmt):
            sql = _sql(stmt)
            if sql.startswith("SELECT count(*)") and "FROM webhook_deliveries" in sql:
                n = con.execute(sql).fetchone()[0]
                return SimpleNamespace(scalar=lambda: n)
            return await super().execute(stmt)

    out = await AH.get_webhooks_aggregate(period="all", db=_Counting(), _admin=None)
    d = out["deliveries_in_window"]
    assert d["total"] == len(STATUSES)
    assert (d["success"], d["failed"], d["pending"]) == (len(SUCCESS), len(FAILED), 1), d
    assert d["success_rate_pct"] == round(len(SUCCESS) / (len(SUCCESS) + len(FAILED)) * 100.0, 2)


def test_the_deliveries_that_never_landed_are_every_answer_but_a_2xx(con):
    """routers/developers.py's raw SQL for the "deliveries that never landed" view, run as written."""
    sqls = [n.value for n in ast.walk(ast.parse(DEVELOPERS_PY.read_text(encoding="utf-8")))
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and "FROM webhook_deliveries d" in n.value
            and "JOIN developer_webhooks w" in n.value]
    assert len(sqls) == 1, f"the reader found {len(sqls)} statements for the view"
    bad = con.execute(sqls[0], {"dev": 7, "lim": 10}).fetchall()
    assert len(bad) == 1 and bad[0][3] == len(FAILED) + 1, f"every non-2xx answer and the one with none: {bad}"
