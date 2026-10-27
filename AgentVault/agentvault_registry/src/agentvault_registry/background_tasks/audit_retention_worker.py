"""Background Task: audit-record retention (§LEGALKIT, 2026-09-20).

Privacy Policy § 4.2 promises: "security and API audit records at most 12 months, then deleted or
anonymized". Nothing enforced it (README follow-up F5, open since July); registry-a's oldest row dates
from 2026-05-19, so the sentence would have become false on 2027-05-19 with nothing to notice.

Cycles daily, leader-elected, stamped by vitals. Deletes `security_audit_logs` rows (the table holds both
the security events and the MCP tool invocations, `target_type='mcp_tool'`) whose `timestamp` is older
than the cap, in bounded batches so a year of rows never holds a lock for long.

  AUDIT_RETENTION_ENABLED=true|false          (default true)
  AUDIT_LOG_RETENTION_DAYS=365                (the cap the policy publishes)
  AUDIT_RETENTION_INTERVAL_SECONDS=86400      (daily)
  AUDIT_RETENTION_BATCH=5000                  (rows per DELETE)
  AUDIT_RETENTION_MAX_BATCHES=200             (per cycle; the rest waits for tomorrow, counted)
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text

from ..database import get_db_context

logger = logging.getLogger(__name__)

WORKER_ID = "audit_retention_worker"
TABLE = "security_audit_logs"
TIMESTAMP_COLUMN = "timestamp"


def _enabled() -> bool:
    return os.getenv("AUDIT_RETENTION_ENABLED", "true").lower() in ("true", "1", "yes")


def _int(name: str, default: int, floor: int = 1) -> int:
    try:
        return max(floor, int(os.getenv(name, str(default))))
    except (ValueError, TypeError):
        return default


def retention_days() -> int:
    return _int("AUDIT_LOG_RETENTION_DAYS", 365)


def purge_statement():
    """The one DELETE, bounded by a batch: the test pins its shape, the worker runs it in a loop.

    The subselect picks the oldest rows first so a long backlog drains in order, and the cutoff is
    bound as a parameter (never formatted in), so the cap the policy states is the cap that runs.
    """
    return text(
        f'DELETE FROM {TABLE} WHERE id IN ('
        f'SELECT id FROM {TABLE} WHERE "{TIMESTAMP_COLUMN}" < :cutoff '
        f'ORDER BY "{TIMESTAMP_COLUMN}" ASC LIMIT :batch)'
    )


def cutoff_for(now: Optional[datetime] = None, days: Optional[int] = None) -> datetime:
    """The cutoff in the COLUMN's shape. `security_audit_logs.timestamp` is `timestamp without time zone` (UTC by
    convention, written naive), and asyncpg refuses to bind an aware datetime into it: the first V0412 cycle on EU
    died on `can't subtract offset-naive and offset-aware datetimes` and the cap stayed unenforced. UTC is the clock,
    naive is the wire shape; a test pins this to the model's column so a future `timezone=True` moves both."""
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is not None:
        base = base.astimezone(timezone.utc).replace(tzinfo=None)
    return base - timedelta(days=days if days is not None else retention_days())


async def purge_once() -> dict:
    """Delete rows past the cap in batches; report what moved and what is left for tomorrow."""
    batch = _int("AUDIT_RETENTION_BATCH", 5000, floor=100)
    max_batches = _int("AUDIT_RETENTION_MAX_BATCHES", 200)
    cutoff = cutoff_for()
    deleted = 0
    batches = 0
    async with get_db_context() as db:
        while batches < max_batches:
            res = await db.execute(purge_statement(), {"cutoff": cutoff, "batch": batch})
            await db.commit()
            n = res.rowcount if res.rowcount is not None and res.rowcount >= 0 else 0
            batches += 1
            deleted += n
            if n < batch:
                break
        remaining = (await db.execute(
            text(f'SELECT count(*) FROM {TABLE} WHERE "{TIMESTAMP_COLUMN}" < :cutoff'),
            {"cutoff": cutoff},
        )).scalar_one()
    return {"deleted": deleted, "batches": batches, "remaining_past_cap": int(remaining or 0),
            "retention_days": retention_days(), "cutoff": cutoff.isoformat()}


class AuditRetentionWorker:
    def __init__(self) -> None:
        self.task: Optional[asyncio.Task] = None
        self.running = False

    async def run_forever(self) -> None:
        interval = _int("AUDIT_RETENTION_INTERVAL_SECONDS", 86400, floor=60)
        enabled = _enabled()
        logger.info("[AuditRetentionWorker] Started (interval=%ds, enabled=%s, cap=%dd)",
                    interval, enabled, retention_days())
        self.running = True
        if not enabled:
            logger.info("[AuditRetentionWorker] Disabled by env; exiting loop.")
            self.running = False
            return
        from .leader import try_acquire_leadership
        from . import vitals as _vitals
        await _vitals.register(WORKER_ID, module=__name__, pattern="hand-rolled",
                               interval_sec=interval, enabled=True)
        while self.running:
            try:
                if not await try_acquire_leadership(WORKER_ID):
                    await asyncio.sleep(interval)
                    continue
                async with _vitals.cycle(WORKER_ID) as ctx:
                    summary = await purge_once()
                    ctx.note(**summary)
                    if summary["remaining_past_cap"]:
                        # Not a failure of the cycle, but a fact the operator must see: the cap is not
                        # yet true on this frame, and it will be tomorrow only if the backlog shrinks.
                        logger.warning("[AuditRetentionWorker] %d rows still past the cap after %d batches",
                                       summary["remaining_past_cap"], summary["batches"])
                    logger.info("[AuditRetentionWorker] cycle: %s", summary)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # vitals stamps the failure; the loop survives
                logger.error("[AuditRetentionWorker] Unexpected error: %s", exc, exc_info=True)
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
        logger.info("[AuditRetentionWorker] Stopped.")

    async def start(self) -> None:
        if self.task and not self.task.done():
            return
        self.task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None


_worker: Optional[AuditRetentionWorker] = None


def get_audit_retention_worker() -> AuditRetentionWorker:
    global _worker
    if _worker is None:
        _worker = AuditRetentionWorker()
    return _worker


async def start_audit_retention_worker() -> None:
    await get_audit_retention_worker().start()


async def stop_audit_retention_worker() -> None:
    await get_audit_retention_worker().stop()
