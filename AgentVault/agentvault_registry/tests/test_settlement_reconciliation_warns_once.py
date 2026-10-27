"""§MCPTEST30 (V0640): a settlement whose slash retries are spent is warned about once, not every cycle.

tasks/settlement_reconciliation logged "Settlement <id> exhausted 3 retry attempts. Awaiting EventStore evidence or
manual resolution." on every 60-second cycle until the settlement expired a day later. Two sandbox test settlements
(2026-10-24 17:36Z and 17:49Z, their slash requests delivered nowhere) made that two WARNINGs a minute, and with the log
metrics' keyword classes fired production's SettlementFailureRate as EU's (agentvault2-66). Pinned: the warning comes
once, the row is marked (exhausted_at=) and its retry count still reads; later cycles still check the EventStore and
say nothing above DEBUG; a settlement with retries left still retries; expiry still warns.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from agentvault_registry.tasks import settlement_reconciliation as R


class _Db:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def _settlement(msg, age_hours=1):
    return SimpleNamespace(id="63761626", dispute_id=236, status="PENDING_SLASH", error_message=msg,
                           requested_at=datetime.now(timezone.utc) - timedelta(hours=age_hours))


def _patch(monkeypatch):
    seen = {"evidence": 0, "retries": []}

    async def no_slash(_s):
        seen["evidence"] += 1
        return None

    async def retry(_db, _s, count):
        seen["retries"].append(count)

    monkeypatch.setattr(R, "_check_eventstore_for_slash", no_slash)
    monkeypatch.setattr(R, "_retry_slash_request", retry)
    return seen


def test_spent_retries_warn_once_and_mark_the_row(monkeypatch, caplog):
    seen = _patch(monkeypatch)
    db, s = _Db(), _settlement("retry_count=3, last_retry=2026-10-24T17:51:41+00:00")
    with caplog.at_level(logging.DEBUG, logger=R.logger.name):
        for _ in range(3):
            asyncio.run(R._reconcile_single_settlement(db, s))
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warns) == 1 and "exhausted 3 retry attempts" in warns[0].getMessage()
    assert s.error_message.startswith("retry_count=3, last_retry=") and "exhausted_at=" in s.error_message
    assert db.commits == 1 and seen["evidence"] == 3 and seen["retries"] == []   # still checked, never retried again


def test_a_settlement_with_retries_left_still_retries(monkeypatch):
    seen = _patch(monkeypatch)
    s = _settlement("retry_count=1, last_retry=2026-10-24T17:50:00+00:00")
    asyncio.run(R._reconcile_single_settlement(_Db(), s))
    assert seen["retries"] == [1]


def test_expiry_still_warns(monkeypatch, caplog):
    _patch(monkeypatch)
    s = _settlement("retry_count=3, last_retry=x, exhausted_at=y", age_hours=25)
    with caplog.at_level(logging.WARNING, logger=R.logger.name):
        asyncio.run(R._reconcile_single_settlement(_Db(), s))
    assert s.status == "EXPIRED" and any("EXPIRED" in r.getMessage() for r in caplog.records)
