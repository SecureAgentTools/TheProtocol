"""§MEMBERSHIP D1 follow-up (2026-10-02, agentvault2-33): each incident kind is opened and closed by its own check.

A truth (supply) OK reading closed EVERY open incident of its frame, so each long escrow breach on the legacy frames became a
run of one-cycle incidents (17,049 from 2026-06-28 to 08-27); and a truth BREACH found an open incident of any kind and opened
no supply incident of its own. The track record's integrity score reads the supply and public incidents' durations.
RED on the base: the first three tests. CONTROL that passes on the base: a supply breach with nothing open opens its incident
and a supply OK closes it.
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


def truth(db, status, frame="eu"):
    bad = status != "OK"
    return run(db.record_audit(tokens_issued=1.0, total_circulating=0.0 if bad else 1.0, delta=1.0 if bad else 0.0,
                               status=status, response_ms=1, frame=frame, atomic_delta=1.0 if bad else 0.0,
                               atomic_status=status))


def public(db, status, frame="eu"):
    return run(db.record_audit(tokens_issued=10.0, total_circulating=10.0, delta=0.0 if status == "OK" else 2.0,
                               status=status, response_ms=5, frame=frame, extra_data={"public_only": True},
                               source="public", public_breach_readings=5))


def kinds_open(db, frame="eu"):
    return sorted(b["kind"] for b in run(db.get_breaches(frame=frame)) if not b.get("resolved_at"))


def test_red_a_healthy_supply_reading_leaves_an_escrow_incident_open(db):
    run(db.record_escrow_incident("eu", True, {"delta": 3.0}))
    truth(db, "OK")
    assert kinds_open(db) == ["escrow"], "only the escrow check closes an escrow incident"


def test_red_a_supply_breach_opens_its_own_incident_beside_an_open_escrow_one(db):
    run(db.record_escrow_incident("eu", True, {"delta": 3.0}))
    truth(db, "BREACH")
    assert kinds_open(db) == ["escrow", "supply"]
    truth(db, "OK")
    assert kinds_open(db) == ["escrow"], "a supply OK closes the supply incident only"
    run(db.record_escrow_incident("eu", False))
    assert kinds_open(db) == []


def test_red_solvency_and_public_incidents_outlive_a_healthy_supply_reading(db):
    run(db.record_solvency_incident("eu", True, {"headroom": -5.0}))
    for _ in range(5):
        public(db, "BREACH")
    assert kinds_open(db) == ["public", "solvency"]
    truth(db, "OK")
    assert kinds_open(db) == ["public", "solvency"]
    public(db, "OK")
    run(db.record_solvency_incident("eu", False))
    assert kinds_open(db) == [], "each closes on its own check"


def test_control_a_supply_breach_opens_one_incident_and_a_supply_ok_closes_it(db):
    truth(db, "BREACH")
    truth(db, "BREACH")
    assert kinds_open(db) == ["supply"]
    truth(db, "OK")
    assert kinds_open(db) == []
