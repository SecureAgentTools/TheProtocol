"""§NIGHTLYTRUTH-2 (2026-10-11): every count and recipient list of "developers" means the developers of THIS registry.

Measured on sandbox-A: the admin list held 1,324 developers, the dashboard said 1,450 (126 federation placeholders from
sandbox-B), the registry card's stats block said 2,163 (also 711 accounts the tester's lifecycles had deleted), and a
frame-wide broadcast email selected every verified row, so it would have mailed the deleted accounts' kept addresses
and the placeholders' synthetic ones. services/developer_population.py holds the one predicate; the sites are driven
with a recording session so the statements they execute are pinned, never a source grep; the control proves the check
can fail.
"""
from __future__ import annotations

import asyncio
import types

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from agentvault_registry import models
from agentvault_registry.services.developer_population import a_developer_of_this_registry


def _sql(stmt) -> str:
    try:
        return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).lower()
    except Exception:  # noqa: BLE001
        return str(stmt).lower()


def _ours(sql: str) -> bool:
    return "deleted_at is null" in sql and "is_federation_shadow is false" in sql


class _Result:
    def scalar(self):
        return 0

    def scalar_one_or_none(self):
        return None

    def scalars(self):
        return self

    def mappings(self):
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
        self.sql.append(_sql(stmt))
        return _Result()


def test_the_predicate_is_not_deleted_and_not_a_placeholder():
    assert _ours(_sql(select(func.count(models.Developer.id)).where(a_developer_of_this_registry())))


def test_the_registry_cards_developer_count_is_the_registrys_developers():
    from agentvault_registry.services import registry_card_builder as rcb
    rcb._CACHE.pop("stats", None)
    db = _RecordingDB()
    try:
        asyncio.run(rcb._build_stats_block(db))
    except Exception:  # noqa: BLE001 - a later read may want a shape the empty session lacks; the count came first
        pass
    finally:
        rcb._CACHE.pop("stats", None)
    devs = [s for s in db.sql if "from developers" in s and "count(" in s]
    assert devs, db.sql[:6]
    assert all(_ours(s) for s in devs), devs


def test_a_broadcast_email_never_selects_a_deleted_account_or_a_placeholder():
    from agentvault_registry.routers import admin_broadcast
    db = _RecordingDB()
    broadcast = types.SimpleNamespace(id=1, broadcast_type="info", title="t", body="b", cta_url=None, cta_label=None)
    asyncio.run(admin_broadcast._send_broadcast_email(broadcast, db))   # no recipients: it returns before any send
    picks = [s for s in db.sql if "from developers" in s and "developers.email" in s]
    assert picks, db.sql[:4]
    assert all(_ours(s) and "is_verified" in s for s in picks), picks


def test_the_check_can_fail():
    # the recipient query as V0593 shipped it: every verified row
    assert not _ours(_sql(select(models.Developer.id, models.Developer.email).where(models.Developer.is_verified == True)))  # noqa: E712
