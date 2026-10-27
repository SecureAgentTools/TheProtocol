"""§NIGHTLYTRUTH (2026-09-14) — the admin dashboard does not count soft-deleted developers.

Measured on sandbox-A: `GET /admin/dashboard` said 633 developers and 633 active while `GET /admin/developers`
held 625, all verified, none deleted; the eight were accounts the tester's own deletion lifecycles had removed
(`deleted_at` set) and the dashboard's two counts had no deletion filter. The federation suite's cross-reference
row (`dashboard_total_developers_matches_admin_list`) was red on it every night. The route is driven with a
recording fake database so the statements it executes are pinned: both developer counts carry `deleted_at IS NULL`.
"""
from __future__ import annotations

import types

from sqlalchemy.dialects import postgresql

from agentvault_registry.routers import admin as admin_router


class _Result:
    def scalar(self):
        return 0

    def scalar_one_or_none(self):
        return None

    def scalars(self):
        return self

    def all(self):
        return []

    def fetchall(self):
        return []

    def first(self):
        return None


class _RecordingDB:
    def __init__(self):
        self.sql = []

    async def execute(self, stmt, *a, **k):
        try:
            self.sql.append(str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})))
        except Exception:
            self.sql.append(str(stmt))
        return _Result()


async def test_both_developer_counts_exclude_soft_deleted_rows():
    db = _RecordingDB()
    admin = types.SimpleNamespace(email="admin@example.test", id=1, is_admin=True)
    await admin_router.get_admin_dashboard(db=db, current_admin=admin)
    dev_counts = [s for s in db.sql if "count(*)" in s.lower() and "from developers" in s.lower()]
    assert len(dev_counts) >= 2, db.sql[:4]
    for s in dev_counts[:2]:
        assert "deleted_at is null" in s.lower(), s
    assert any("is_verified" in s.lower() for s in dev_counts[:2]), "the active count still asks for verification"


async def test_both_developer_counts_exclude_federation_placeholders():
    # §NIGHTLYTRUTH-2 (2026-10-11): the federation suite's cross-reference row read the dashboard at 1,450 against the
    # list's 1,324 on sandbox-A; the 126 were sandbox-B's federation placeholders (`is_federation_shadow`), which the
    # list hides by default and the dashboard counted.
    db = _RecordingDB()
    admin = types.SimpleNamespace(email="admin@example.test", id=1, is_admin=True)
    await admin_router.get_admin_dashboard(db=db, current_admin=admin)
    dev_counts = [s for s in db.sql if "count(*)" in s.lower() and "from developers" in s.lower()]
    assert len(dev_counts) >= 2, db.sql[:4]
    for s in dev_counts[:2]:
        assert "is_federation_shadow is false" in s.lower(), s
        assert "deleted_at is null" in s.lower(), s

