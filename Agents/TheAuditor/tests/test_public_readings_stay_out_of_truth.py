"""§MTLSHOPS (a) (2026-09-15, agentvault2-b5; agentvault2-85's calls): a public-only frame's readings never feed the truth.

A public reading is two queries and can show a transient BREACH under cross-frame load, so it opens a kind='public' incident
only after 5 consecutive BREACH readings outside maintenance, an OK reading resolves it, and it never feeds the audit count,
the streak or the uptime; a scope that holds only public readings reports its uptime as not measured (None).
RED on the base: every public test (the base has no reading source). CONTROL that passes on the base: a truth BREACH still
opens its supply incident at once.
AUDITOR_TREE points the suite at another checkout of Agents/TheAuditor (the base run).
"""
import asyncio
import importlib
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.getenv("AUDITOR_TREE") or HERE


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


def public(db, status, maintenance=False):
    return run(db.record_audit(tokens_issued=10.0, total_circulating=10.0, delta=0.0 if status == "OK" else 2.0,
                               status=status, response_ms=5, frame="po", extra_data={"public_only": True},
                               maintenance=maintenance, source="public", public_breach_readings=5))


def open_incidents(db, frame):
    return [b for b in run(db.get_breaches(frame=frame)) if not b.get("resolved_at")]


def test_red_four_public_breach_readings_open_nothing_the_fifth_opens_one_and_ok_resolves_it(db):
    for i in range(4):
        assert public(db, "BREACH")["public_breach_streak"] == i + 1
        assert run(db.get_breaches(frame="po")) == []
    assert public(db, "BREACH")["public_breach_streak"] == 5
    assert [b["kind"] for b in open_incidents(db, "po")] == ["public"]
    public(db, "BREACH")
    assert len(open_incidents(db, "po")) == 1
    public(db, "OK")
    assert open_incidents(db, "po") == [] and len(run(db.get_breaches(frame="po"))) == 1


def test_red_a_maintenance_reading_breaks_the_public_streak(db):
    for _ in range(4):
        public(db, "BREACH")
    public(db, "BREACH", maintenance=True)
    for _ in range(4):
        public(db, "BREACH")
    assert run(db.get_breaches(frame="po")) == []


def test_red_public_readings_never_feed_the_audit_count_or_the_uptime(db):
    for _ in range(3):
        public(db, "BREACH")
    only_public = run(db.get_stats(frame="po"))
    assert only_public["total_audits"] == 0 and only_public["uptime_pct"] is None and only_public["public_readings"] == 3
    run(db.record_audit(tokens_issued=1.0, total_circulating=1.0, delta=0.0, status="OK", response_ms=1, frame="eu",
                        atomic_delta=0.0, atomic_status="OK"))
    everything = run(db.get_stats())
    assert everything["total_audits"] == 1 and everything["uptime_pct"] == 100.0


def test_control_a_truth_breach_still_opens_its_supply_incident_at_once(db):
    run(db.record_audit(tokens_issued=1.0, total_circulating=0.0, delta=1.0, status="BREACH", response_ms=1, frame="eu",
                        atomic_delta=1.0, atomic_status="BREACH"))
    assert [b["kind"] for b in open_incidents(db, "eu")] == ["supply"]


def test_red_a_public_reading_row_carries_no_count_and_a_truth_row_does(db):
    # §MTLSHOPS (a) with §LIVESTATS (the merge): the page moves its stats by the row's counts_ok and counts_breach, so a public
    # reading's row must carry None (the server's word that it counts for nothing), never False, which would reset the streak.
    # RED on 497d4e7 (no counts on any row) and on the automatic merge (a public BREACH row carried False and False).
    row = public(db, "BREACH")
    assert row["counts_ok"] is None and row["counts_breach"] is None
    truth = run(db.record_audit(tokens_issued=1.0, total_circulating=1.0, delta=0.0, status="OK", response_ms=1, frame="eu",
                                atomic_delta=0.0, atomic_status="OK"))
    assert truth["counts_ok"] is True and truth["counts_breach"] is False
