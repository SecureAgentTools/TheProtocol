"""
Background Task: Account-Deletion Anonymizer (W2, 2026-05-09).

Cycles daily (default 86400s), leader-elected via Redis. Picks up developer
rows where `deletion_status='pending_deletion'` and `deletion_requested_at`
is older than `ACCOUNT_DELETION_COOLING_OFF_DAYS` (default 14d) and runs
the canonical `anonymize_developer` helper from `routers/account_deletion`.

Configurable via environment:
  ACCOUNT_DELETION_WORKER_ENABLED=true|false   (default true)
  ACCOUNT_DELETION_INTERVAL_SECONDS=86400      (default 86400 — daily)
  ACCOUNT_DELETION_COOLING_OFF_DAYS=14         (default 14)
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select

from ..database import get_db_context
from ..models import Developer
from ..routers.account_deletion import (
    DELETION_STATUS_PENDING,
    anonymize_developer,
)

logger = logging.getLogger(__name__)


def _is_enabled() -> bool:
    return os.getenv("ACCOUNT_DELETION_WORKER_ENABLED", "true").lower() in ("true", "1", "yes")


def _interval() -> int:
    try:
        return int(os.getenv("ACCOUNT_DELETION_INTERVAL_SECONDS", "86400"))
    except (ValueError, TypeError):
        return 86400


def _cooling_off_days() -> int:
    try:
        return int(os.getenv("ACCOUNT_DELETION_COOLING_OFF_DAYS", "14"))
    except (ValueError, TypeError):
        return 14


class AccountDeletionWorker:
    """Anonymize developers whose cooling-off has elapsed."""

    def __init__(self) -> None:
        self.task: Optional[asyncio.Task] = None
        self.running: bool = False

    async def _scan_and_anonymize(self) -> dict:
        """One cycle. Returns the cycle's numbers so the caller can judge it:
        ``anonymized`` · ``failed`` (anonymization raised) · ``drain_failures`` (a
        forfeiture that moved no money, §MONEY-R39) · ``avt_forfeited``."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=_cooling_off_days())
        anonymized_count = 0
        failure_count = 0
        drain_failures = 0
        drain_owed = 0
        avt_forfeited = Decimal("0")

        async with get_db_context() as db:
            res = await db.execute(
                select(Developer)
                .where(Developer.deletion_status == DELETION_STATUS_PENDING)
                .where(Developer.deletion_requested_at != None)  # noqa: E711
                .where(Developer.deletion_requested_at <= cutoff)
            )
            candidates = res.scalars().all()
            if not candidates:
                logger.debug("[AccountDeletionWorker] No candidates this cycle.")
                return {"anonymized": 0, "failed": 0, "drain_failures": 0, "drain_owed": 0, "avt_forfeited": "0"}

            logger.info(
                "[AccountDeletionWorker] Found %d developers past cooling-off; anonymizing...",
                len(candidates),
            )
            for dev in candidates:
                try:
                    report = await anonymize_developer(
                        db, dev, actor_email_for_audit="account_deletion_worker"
                    )
                    await db.commit()
                    anonymized_count += 1
                    drain_failures += int(report.get("teg_drain_failures") or 0)
                    drain_owed += int(report.get("teg_drain_owed") or 0)
                    avt_forfeited += Decimal(str(report.get("avt_forfeited") or "0"))
                    logger.info(
                        "[AccountDeletionWorker] Anonymized dev_id=%s (deletion_id=%s)",
                        report.get("developer_id"), report.get("deletion_id"),
                    )
                except Exception as exc:
                    failure_count += 1
                    logger.exception(
                        "[AccountDeletionWorker] Failed to anonymize dev_id=%s: %s",
                        getattr(dev, "id", "unknown"), exc,
                    )
                    # Roll back this dev's partial changes; the next cycle retries.
                    try:
                        await db.rollback()
                    except Exception:
                        pass

        logger.info(
            "[AccountDeletionWorker] Cycle complete — anonymized=%d failed=%d drain_failures=%d avt_forfeited=%s",
            anonymized_count, failure_count, drain_failures, avt_forfeited,
        )
        return {
            "anonymized": anonymized_count,
            "failed": failure_count,
            "drain_failures": drain_failures,
            "drain_owed": drain_owed,
            "avt_forfeited": str(avt_forfeited),
        }

    async def run_forever(self) -> None:
        interval = _interval()
        enabled = _is_enabled()
        logger.info(
            "[AccountDeletionWorker] Started (interval=%ds, enabled=%s, cooling_off=%dd)",
            interval, enabled, _cooling_off_days(),
        )
        self.running = True

        if not enabled:
            logger.info("[AccountDeletionWorker] Disabled by env — exiting loop.")
            self.running = False
            return

        from .leader import try_acquire_leadership
        from . import vitals as _vitals

        await _vitals.register("account_deletion_worker", module=__name__,
                               pattern="hand-rolled", interval_sec=interval, enabled=True)
        while self.running:
            try:
                if not await try_acquire_leadership("account_deletion_worker"):
                    await asyncio.sleep(interval)
                    continue
                # _scan_and_anonymize does not catch at its top level, so a failure
                # reaches the stamp on its own.
                async with _vitals.cycle("account_deletion_worker") as ctx:
                    summary = await self._scan_and_anonymize()
                    ctx.note(**summary)
                    if int(summary["drain_failures"]) > int(summary.get("drain_owed") or 0):
                        # §MONEY-R39: every developer may have been anonymized and the cycle
                        # is STILL a failure — a forfeiture that moved no money leaves a
                        # balance stranded on a revoked agent. The pre-R39 worker stamped `ok`
                        # over exactly that (dev 8483, 2026-09-04). §LEDGERGATE (V0599): a drain
                        # recorded as OWED (forfeitures_owed, in the anonymization's transaction)
                        # is drained later by forfeiture_retry with its own key; only one that is
                        # not owed is still stranded, and that one fails the cycle.
                        ctx.fail(
                            f"{int(summary['drain_failures']) - int(summary.get('drain_owed') or 0)} forfeiture "
                            f"drain(s) moved no money and are not owed (R39)"
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    "[AccountDeletionWorker] Unexpected error: %s", exc, exc_info=True,
                )

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

        logger.info("[AccountDeletionWorker] Stopped.")

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


# Module-level singleton.
_worker: Optional[AccountDeletionWorker] = None


def get_account_deletion_worker() -> AccountDeletionWorker:
    global _worker
    if _worker is None:
        _worker = AccountDeletionWorker()
    return _worker


async def start_account_deletion_worker() -> None:
    await get_account_deletion_worker().start()


async def stop_account_deletion_worker() -> None:
    if _worker is not None:
        await _worker.stop()
