"""notification_log_retention — keeps the per-decision notification history bounded.

The history table (mig 0138) takes a row per DEVICE per notify() call, including suppressions.
On registry-a that measured ~222 rows/hour for a single developer with a registered phone, so
it is small but strictly monotonic: without a pruner it is an unbounded table, and unbounded
tables are how a debugging convenience becomes an incident.

Leader-elected (one worker per registry, not per gunicorn worker) and deliberately dumb: one
indexed DELETE against ix_notification_log_created, hourly. Deleting by age rather than by
row-count keeps the window predictable when volume changes.

Env gates: NOTIFICATION_LOG_ENABLED (shared with the writer), NOTIFICATION_LOG_RETENTION_DAYS.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from ._worker_base import BackgroundWorker
from ..config import settings
from ..database import AsyncSessionLocal

logger = logging.getLogger(__name__)


class NotificationLogRetentionWorker(BackgroundWorker):
    worker_id = "notification_log_retention"
    leader_key = "leader:notification_log_retention"
    interval_sec = 3600  # hourly
    cold_start_delay_sec = 120

    def _should_run(self) -> bool:
        return bool(getattr(settings, "NOTIFICATION_LOG_ENABLED", True))

    async def _cycle_once(self) -> None:
        days = int(getattr(settings, "NOTIFICATION_LOG_RETENTION_DAYS", 14) or 14)
        if days <= 0:  # 0 = keep forever, an explicit operator choice
            return
        try:
            async with AsyncSessionLocal() as db:
                res = await db.execute(
                    text(
                        "DELETE FROM notification_log "
                        "WHERE created_at < now() - make_interval(days => :d)"
                    ),
                    {"d": days},
                )
                await db.commit()
                if res.rowcount:
                    logger.info(
                        "[NOTIFY-LOG] pruned %d row(s) older than %dd", res.rowcount, days
                    )
        except Exception as exc:  # noqa: BLE001
            # A failed prune must never take the worker loop down; next hour tries again.
            logger.warning("[NOTIFY-LOG] prune failed: %s", exc)

        # The in-app FEED (mig 0139) is user-visible, so it is pruned more gently than the
        # decision log: READ entries age out on the same clock, but something you never opened
        # survives to the 90-day horizon the broadcast bell already uses. Silently deleting an
        # unread notification is just a slower version of never sending it.
        try:
            async with AsyncSessionLocal() as db:
                res = await db.execute(
                    text(
                        "DELETE FROM notification_feed WHERE "
                        "(read_at IS NOT NULL AND created_at < now() - make_interval(days => :d)) "
                        "OR created_at < now() - interval '90 days'"
                    ),
                    {"d": days},
                )
                await db.commit()
                if res.rowcount:
                    logger.info("[NOTIFY-FEED] pruned %d row(s)", res.rowcount)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[NOTIFY-FEED] prune failed: %s", exc)


notification_log_retention_worker = NotificationLogRetentionWorker()
