"""§FEDLICENCE improvement 11 (2026-09-28): a rotation's plain key does not outlive its 24 h replay window.

`federation_license_rotations.new_license_key` holds the NEW key in plain text so a client that lost the response can
replay its idempotency key and receive the same key; the column's comment promised it was cleared, and nothing ever
cleared it. The sweep clears every rotation whose window has closed (a replay then already answers 410), at the start of
every rotation and once per license_drift_monitor cycle. The statement runs here on a real SQL engine (sqlite, the real
table definition), not only compiled.
"""
from __future__ import annotations

import datetime
import os
import types

import sqlalchemy as sa

from agentvault_registry import models
from agentvault_registry.routers import federation_license_self as fls

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 9, 28, 2, 0, tzinfo=UTC)


def _engine_with_rows(rows):
    eng = sa.create_engine("sqlite://")
    models.FederationLicenseRotation.__table__.create(eng)
    with eng.begin() as c:
        for i, (expires, key) in enumerate(rows):
            c.execute(models.FederationLicenseRotation.__table__.insert().values(
                id=f"rot-{i}", idempotency_key=f"idem-{i:016d}", caller_license_id="lic-1",
                prev_license_key_hash="p" * 64, status="returned", new_license_key=key,
                expires_at=expires, created_at=NOW))
    return eng


def _keys(eng):
    t = models.FederationLicenseRotation.__table__
    with eng.connect() as c:
        return dict(c.execute(sa.select(t.c.id, t.c.new_license_key).order_by(t.c.id)).all())


def test_the_sweep_clears_only_keys_whose_window_has_closed():
    eng = _engine_with_rows([
        (NOW - datetime.timedelta(hours=1), "tp_fed_expired"),      # window closed: cleared
        (NOW + datetime.timedelta(hours=1), "tp_fed_inside"),       # control: still replayable, kept
        (NOW - datetime.timedelta(hours=2), None),                  # control: already empty, not counted
    ])
    with eng.begin() as c:
        n = c.execute(fls.expired_rotation_key_sweep(NOW)).rowcount
    assert n == 1
    assert _keys(eng) == {"rot-0": None, "rot-1": "tp_fed_inside", "rot-2": None}


def test_a_key_expiring_exactly_now_is_cleared():
    eng = _engine_with_rows([(NOW, "tp_fed_edge")])
    with eng.begin() as c:
        c.execute(fls.expired_rotation_key_sweep(NOW))
    assert _keys(eng) == {"rot-0": None}


class _Db:
    def __init__(self, rowcount):
        self.rowcount, self.commits, self.stmts = rowcount, 0, []

    async def execute(self, stmt):
        self.stmts.append(stmt)
        return types.SimpleNamespace(rowcount=self.rowcount)

    async def commit(self):
        self.commits += 1


async def test_the_session_helper_commits_what_it_cleared():
    db = _Db(3)
    assert await fls.clear_expired_rotation_keys(db, NOW) == 3 and db.commits == 1


async def test_control_nothing_cleared_means_no_commit():
    db = _Db(0)
    assert await fls.clear_expired_rotation_keys(db, NOW) == 0 and db.commits == 0


def _src(rel):
    return open(os.path.join(os.path.dirname(models.__file__), rel), encoding="utf-8").read()


def test_the_rotation_route_sweeps_before_its_replay_check():
    s = _src("routers/federation_license_self.py")
    sweep, replay = s.index("await clear_expired_rotation_keys(db, now)"), s.index("# ── IDEMPOTENT REPLAY CHECK")
    assert sweep < replay


def test_the_drift_monitor_sweeps_every_cycle_under_its_own_guard():
    s = _src("background_tasks/license_drift_monitor.py")
    run, sweep = s.index("await run_once()"), s.index("await clear_expired_rotation_keys(_db)")
    assert run < sweep and "rotation key sweep failed" in s
