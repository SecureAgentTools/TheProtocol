"""§LIVESTATS (2026-09-15, agentvault2-b5; agentvault2-85's one-definition rule): which rows count is decided once, by the server.

get_stats counts the OK rows (uptime, the streak) and the last breach with SQL. Every row record_audit returns, which is the
websocket row the page counts, carries counts_ok and counts_breach from the Python form of the same rule, and get_stats serves
ok_audits, the integer the page adds live rows to. One fixture runs through both forms and through get_stats: an OK row, a
BREACH, an ERROR, a maintenance BREACH, a maintenance ERROR, an atomic OK over a live BREACH, an atomic BREACH over a live OK
and the same inside maintenance, and rows whose maintenance argument is None: record_audit stores it as 0, so the counts it
returns must come from the stored value (agentvault2-85's probe: a BREACH with maintenance None returned counts_breach False
while its stored row answers BREACH_SQL true).
RED on master: record_audit returns no counts_ok and get_stats serves no ok_audits. RED on 76d2a5f: the None rows. CONTROL
that passes on master too: the server's streak has always counted a maintenance row (the page's copy of the rule did not).
AUDITOR_TREE points the suite at another checkout of Agents/TheAuditor (the base run).
"""
import asyncio
import importlib
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.getenv("AUDITOR_TREE") or HERE

# (status, atomic_status, maintenance, counts_ok, counts_breach)
ROWS = [
    ("OK", None, False, True, False),
    ("BREACH", None, False, False, True),
    ("ERROR", None, False, False, False),
    ("BREACH", None, True, True, False),
    ("ERROR", None, True, True, False),
    ("BREACH", "OK", False, True, False),
    ("OK", "BREACH", False, False, True),
    ("OK", "BREACH", True, True, False),
    ("BREACH", None, None, False, True),
    ("OK", None, None, True, False),
    ("ERROR", None, None, False, False),
]


def _purge():
    for name in [n for n in sys.modules if n == "src" or n.startswith("src.")]:
        del sys.modules[name]


@pytest.fixture()
def db(tmp_path, monkeypatch):
    _purge()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AUDITOR_EXTRA_FRAMES_JSON", raising=False)
    monkeypatch.delenv("AUDITOR_EXTRA_FRAMES_FILE", raising=False)
    monkeypatch.syspath_prepend(TREE)
    database = importlib.import_module("src.auditor.database")
    asyncio.run(database.init_db())
    yield database
    _purge()


def run(coro):
    return asyncio.run(coro)


def record(db, status, atomic, maintenance, frame="f"):
    return run(db.record_audit(tokens_issued=1.0, total_circulating=1.0, delta=0.0, status=status, response_ms=1, frame=frame,
                               atomic_delta=None if atomic is None else 0.0, atomic_status=atomic, maintenance=maintenance))


def test_red_every_returned_row_carries_the_rule_and_the_sql_form_agrees_row_by_row(db):
    import aiosqlite

    returned = [record(db, s, a, m) for s, a, m, _, _ in ROWS]
    assert [(r["counts_ok"], r["counts_breach"]) for r in returned] == [(ok, br) for *_, ok, br in ROWS]

    async def sql_form():
        async with aiosqlite.connect(str(db.DB_PATH)) as con:
            cur = await con.execute(f"SELECT {db.OK_SQL}, {db.BREACH_SQL} FROM audit_history ORDER BY id")
            return [(bool(x), bool(y)) for x, y in await cur.fetchall()]

    assert run(sql_form()) == [(ok, br) for *_, ok, br in ROWS]


def test_red_get_stats_serves_ok_audits_and_counts_by_the_same_rule(db):
    returned = [record(db, s, a, m) for s, a, m, _, _ in ROWS]
    st = run(db.get_stats())
    oks = [r["counts_ok"] for r in returned]
    assert st["total_audits"] == len(ROWS)
    assert isinstance(st["ok_audits"], int) and st["ok_audits"] == sum(oks)
    trailing = 0
    for ok in reversed(oks):
        if not ok:
            break
        trailing += 1
    assert st["consecutive_ok"] == trailing
    assert st["last_breach"] == [r["timestamp"] for r in returned if r["counts_breach"]][-1]
    assert st["uptime_pct"] == round(sum(oks) / len(ROWS) * 100, 2)


def test_red_an_empty_scope_serves_ok_audits_zero(db):
    record(db, "OK", None, False)
    st = run(db.get_stats(frame="nothing-here"))
    assert st["total_audits"] == 0 and st["ok_audits"] == 0


def test_control_the_server_streak_counts_maintenance_rows(db):
    for status, maintenance in (("BREACH", False), ("OK", False), ("ERROR", True), ("BREACH", True), ("OK", False)):
        record(db, status, None, maintenance)
    st = run(db.get_stats())
    assert st["consecutive_ok"] == 4 and st["last_breach"] is not None
