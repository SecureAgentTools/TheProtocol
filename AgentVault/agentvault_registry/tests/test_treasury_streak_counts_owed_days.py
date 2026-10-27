"""§FEELOCK (2026-09-11) — the D-FED-10 treasury streak counts days the treasury could not pay,
never days on which nobody was owed.

Measured live on all thirteen registries on 2026-09-11, before the fix:

  * EU: 5 stakers, every one below its policy's reward floor (0.05; none has a trust vector yet),
    so every run paid nobody and counted a "zero day". 2 on 09-11, heading for a CRITICAL
    "TREASURY BANKRUPTCY" line at the 2026-10-09 run, on a solvent frame (ASIA: 10-11).
  * frame-b (98) and frame-c (86) had already fired it the same way, both flags set, both false.
  * sbx-beta at 7, same shape.
  * the ONE real streak: cloud-op-sbxalphaop, 24 stakers owed on each of the last four days (since
    2026-09-08) and every one hitting an exhausted reward waterfall (`partial`); the day before paid 19
    of 19. The class the counter exists for, and it must still count.
  * a skipped re-run ("Distribution already completed for ...") counted as a zero day as well.

The V0349 monitor counted from the run's own numbers (`total == 0 or successful == 0`); this one
re-derives the streak from the completed distributions. Every test marked RED below failed against
the V0349 monitor and passes against this one; the ones marked CONTROL pass against both.
"""
from __future__ import annotations

import ast
import inspect
import logging
import pathlib
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from agentvault_registry.services import federation_compliance_monitor as fcm

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
if not SRC.is_dir():
    SRC = pathlib.Path("/w/src/agentvault_registry")
if not SRC.is_dir():
    SRC = pathlib.Path("/app/src/agentvault_registry")

TODAY = date(2026, 9, 11)
NOBODY_ELIGIBLE = {"status": "completed", "total_distributed": "0", "successful": 0,
                   "failed": 0, "results": []}


def _days(*shapes):
    """(paid, exhausted, failed) per day, newest first, dated back from TODAY."""
    return [(TODAY - timedelta(days=i), p, e, f) for i, (p, e, f) in enumerate(shapes)]


class _Result:
    def __init__(self, scalar=None, rows=None):
        self._scalar, self._rows = scalar, rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def all(self):
        return list(self._rows)


class _Session:
    """Answers the two reads the monitor makes: the operating-state row, and the ledger."""

    def __init__(self, state, days):
        self.state, self.days, self.commits = state, days, 0

    async def execute(self, stmt, params=None):
        if "registry_operating_state" in str(stmt):
            return _Result(scalar=self.state)
        return _Result(rows=self.days)

    async def commit(self):
        self.commits += 1


class _Emitter:
    """A recorder the receipt ratchet can read by name (tests/test_doubles_assert_receipt.py)."""

    def __init__(self):
        self.received = []

    async def emit(self, **kw):
        self.received.append(kw)


def _state(zero_days=0, triggered=False):
    return SimpleNamespace(treasury_zero_days=zero_days, treasury_max_fee_locked=triggered,
                           treasury_quarantine_triggered=triggered, last_treasury_check_at=None)


@pytest.fixture
def emitter(monkeypatch):
    e = _Emitter()
    monkeypatch.setattr(fcm, "get_event_emitter", lambda: e)
    return e


async def _evaluate(db, run):
    """Call the monitor the way the distributor does. The V0349 signature took the run's own
    numbers (`distribution_total`, `successful_count`), which IS the defect; the RED run uses it."""
    monitor = fcm.FederationComplianceMonitor()
    params = inspect.signature(monitor.check_and_update_treasury_health).parameters
    if "distribution_total" in params:
        return await monitor.check_and_update_treasury_health(
            db, distribution_total=Decimal(str(run.get("total_distributed", "0"))),
            successful_count=int(run.get("successful", 0)))
    return await monitor.check_and_update_treasury_health(db, run_result=run)


# ── RED: the false alarms ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_day_with_nobody_owed_is_not_a_zero_day(emitter):
    """EU's live shape: three completed runs, nobody eligible, stored count 2."""
    db = _Session(_state(zero_days=2), _days((0, 0, 0), (0, 0, 0), (0, 0, 0)))
    await _evaluate(db, NOBODY_ELIGIBLE)
    assert db.state.treasury_zero_days == 0
    assert not db.state.treasury_quarantine_triggered
    assert emitter.received == []


@pytest.mark.asyncio
async def test_a_skipped_rerun_cannot_count(emitter):
    """A manual trigger after the day's run returns 'skipped'; it is not a second day."""
    db = _Session(_state(zero_days=1), _days((0, 24, 0)))
    await _evaluate(db, {"status": "skipped",
                         "reason": f"Distribution already completed for {TODAY}"})
    assert db.state.treasury_zero_days == 1


@pytest.mark.asyncio
async def test_a_transport_failure_is_no_evidence(emitter):
    """`failed` = the TEG never answered and no money moved. That says nothing about solvency."""
    db = _Session(_state(zero_days=2), _days((0, 0, 3), (0, 5, 0), (0, 5, 0)))
    await _evaluate(db, {"status": "completed", "total_distributed": "0", "successful": 0,
                         "failed": 3})
    assert db.state.treasury_zero_days == 2


@pytest.mark.asyncio
async def test_a_frame_that_fired_on_empty_days_is_cleared_by_the_recount(emitter):
    """frame-b's live shape: stored 98, both flags set, and not one staker owed in the window."""
    db = _Session(_state(zero_days=98, triggered=True), _days(*[(0, 0, 0)] * 60))
    await _evaluate(db, NOBODY_ELIGIBLE)
    assert db.state.treasury_zero_days == 0
    assert db.state.treasury_quarantine_triggered is False
    assert db.state.treasury_max_fee_locked is False
    lifted = [e for e in emitter.received if e["event_type"] == "TreasuryQuarantineLifted"]
    assert len(lifted) == 1 and lifted[0]["data"]["reason"] == "recount", emitter.received


# ── RED: the real streak is read from the ledger, and the alarm says what is true ───────────────────

@pytest.mark.asyncio
async def test_owed_and_exhausted_days_are_counted_from_the_ledger(emitter):
    """Eight synthetic days of 24 stakers owed and an exhausted waterfall against a stored 4: the
    ledger is the record, so the count is 8. (sbxalphaop's live ledger, read after the roll: four such
    days since 2026-09-08, then a day that paid 19 of 19, so its stored 4 was right.)"""
    db = _Session(_state(zero_days=4), _days(*[(0, 24, 0)] * 8))
    await _evaluate(db, {"status": "completed", "total_distributed": "0", "successful": 0,
                         "failed": 0})
    assert db.state.treasury_zero_days == 8


@pytest.mark.asyncio
async def test_the_trigger_says_nothing_is_locked(emitter, caplog):
    """No code path reads either flag. The event and the CRITICAL line must not claim a lock."""
    db = _Session(_state(zero_days=29), _days(*[(0, 24, 0)] * 30))
    with caplog.at_level(logging.CRITICAL, logger=fcm.__name__):
        await _evaluate(db, {"status": "completed", "total_distributed": "0", "successful": 0})
    assert db.state.treasury_quarantine_triggered is True
    fired = [e for e in emitter.received if e["event_type"] == "TreasuryBankruptcyQuarantineTriggered"]
    assert len(fired) == 1, emitter.received
    data = fired[0]["data"]
    assert data["enforced"] is False
    assert data["action"] == "flags_recorded"
    assert data["zero_days"] == 30
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "RECORDED ONLY" in text and "ACTIVATED" not in text, text


def test_the_streak_walk():
    """The pure rule, newest day first."""
    walk = fcm.unfunded_streak
    assert walk([])["streak"] == 0
    assert walk(_days((0, 0, 0), (0, 0, 0)))["streak"] == 0                 # nobody owed
    assert walk(_days((0, 3, 0), (0, 3, 0), (1, 2, 0), (0, 9, 0)))["streak"] == 2  # a payment ends it
    assert walk(_days((0, 3, 0), (0, 0, 0), (0, 0, 7), (0, 3, 0)))["streak"] == 2  # steps over no-evidence days
    r = walk(_days((0, 1, 0), (2, 0, 0)))
    assert r["streak"] == 1 and r["last_solvent_date"] == TODAY - timedelta(days=1)


def test_the_distributor_hands_over_the_run_not_its_totals():
    """The monitor is only as honest as its caller: an AST read of the one call site."""
    tree = ast.parse((SRC / "background_tasks" / "staking_distributor.py").read_text(encoding="utf-8"))
    calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call)
             and isinstance(c.func, ast.Attribute) and c.func.attr == "check_and_update_treasury_health"]
    assert len(calls) == 1, len(calls)
    kws = {k.arg for k in calls[0].keywords}
    assert "run_result" in kws and not ({"distribution_total", "successful_count"} & kws), kws


def test_the_ledger_read_counts_each_date_once_and_only_completed_runs():
    sql = fcm._TREASURY_EVIDENCE_SQL.text
    assert "WHERE d.status = 'completed'" in sql
    assert "GROUP BY d.distribution_date" in sql
    assert "ORDER BY d.distribution_date DESC" in sql
    assert fcm.TREASURY_EVIDENCE_WINDOW >= 2 * fcm.TREASURY_ZERO_DAY_THRESHOLD


# ── CONTROL: both monitors agree ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_staker_paid_in_full_ends_the_streak(emitter):
    db = _Session(_state(zero_days=5), _days((3, 0, 0), *[(0, 4, 0)] * 5))
    await _evaluate(db, {"status": "completed", "total_distributed": "1.25", "successful": 3})
    assert db.state.treasury_zero_days == 0
    assert emitter.received == []
