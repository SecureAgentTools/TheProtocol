"""§bc2 T2.5 — Per-batch email retry worker for broadcast email failures.

BackgroundWorker subclass; cadence 60s. Leader-elected.

Per cycle:
  1. Query `broadcast_email_failed` WHERE `delivered_at IS NULL` AND
     `dead_letter_at IS NULL` AND `next_retry_at <= NOW()`. Limit 20.
  2. For each: load the parent AdminBroadcast (still active?) + the
     batched developer IDs, re-attempt `_send_broadcast_email` for just
     that batch.
  3. On success: `delivered_at = NOW()`.
  4. On failure: increment `retry_count`, compute next_retry_at via
     exponential backoff 60s → 5min → 30min → 2h → 12h. After 5 retries,
     set `dead_letter_at = NOW()` and surface via admin endpoint.

Env gate:
  REACTOR_BROADCAST_EMAIL_RETRY_ENABLED=true|false  (default true)

Snapshot stats:
  - cycle_attempts, cycle_delivered, cycle_failed, cycle_dead_lettered
  - pending_now, dead_lettered_lifetime
"""
from __future__ import annotations

import datetime
import logging
import os
from typing import Any, List

from sqlalchemy import select, text

from agentvault_registry.database import get_db_context
from agentvault_registry import models

from ._worker_base import BackgroundWorker, WORKER_ERRORS_TOTAL

logger = logging.getLogger(__name__)


# Backoff schedule (seconds). Index = retry_count.
_BACKOFF_SEC = [60, 300, 1800, 7200, 43200]  # 1m, 5m, 30m, 2h, 12h
_MAX_RETRIES = len(_BACKOFF_SEC)


try:
    from prometheus_client import Counter as _BC, Gauge as _BG

    EMAIL_RETRY_ATTEMPT_TOTAL = _BC(
        "broadcast_email_retry_attempt_total",
        "Total email-retry attempts across all batches",
        labelnames=["registry_id", "outcome"],   # delivered / failed / dead_lettered
    )
    EMAIL_RETRY_PENDING = _BG(
        "broadcast_email_retry_pending",
        "Pending email-retry batches (not delivered, not dead-lettered)",
        labelnames=["registry_id"],
        multiprocess_mode="max",
    )
    EMAIL_RETRY_DEAD_LETTERED = _BG(
        "broadcast_email_retry_dead_lettered_total_g",
        "Total batches dead-lettered lifetime",
        labelnames=["registry_id"],
        multiprocess_mode="max",
    )
except Exception:  # pragma: no cover
    EMAIL_RETRY_ATTEMPT_TOTAL = None
    EMAIL_RETRY_PENDING = None
    EMAIL_RETRY_DEAD_LETTERED = None


async def _retry_one_batch(
    db,
    row: models.BroadcastEmailFailed,
    parent: models.AdminBroadcast,
) -> tuple[bool, str | None]:
    """Re-attempt email send for the developer-id batch on `row`. Returns
    (delivered, error_reason). Caller updates DB row state."""
    from agentvault_registry.email_utils import send_themed_email

    dev_ids: List[int] = row.developer_ids_json if isinstance(row.developer_ids_json, list) else []
    if not dev_ids:
        return (True, None)  # empty batch is trivially delivered
    # Resolve emails for the batch
    r = await db.execute(
        text("SELECT id, email FROM developers WHERE id = ANY(:ids)"),
        {"ids": dev_ids},
    )
    recipients = [e for (_did, e) in r.fetchall() if e]
    if not recipients:
        return (True, None)  # nobody to email; consider delivered
    try:
        await send_themed_email(
            subject=parent.title,
            recipients=recipients,
            template="admin_broadcast",
            context={
                "title": parent.title,
                "body": parent.body,
                "broadcast_type": parent.broadcast_type,
                "cta_url": parent.cta_url,
                "cta_label": parent.cta_label,
            },
            theme="sovereign" if parent.broadcast_type == "critical" else "neural",
        )
        return (True, None)
    except Exception as e:
        return (False, str(e)[:480])


class BroadcastEmailRetryWorker(BackgroundWorker):
    worker_id = "broadcast_email_retry"
    leader_key = "broadcast_email_retry"
    interval_sec = 60
    cold_start_delay_sec = 8

    def _should_run(self) -> bool:
        return os.getenv("REACTOR_BROADCAST_EMAIL_RETRY_ENABLED", "true").lower() == "true"

    async def _cycle_once(self) -> None:
        attempts = 0
        delivered = 0
        failed = 0
        dead_lettered = 0
        pending_now = 0
        dead_lifetime = 0

        async with get_db_context() as db:
            # Pending snapshot
            r = await db.execute(text("""
                SELECT COUNT(*) FROM broadcast_email_failed
                WHERE delivered_at IS NULL AND dead_letter_at IS NULL
            """))
            pending_now = int(r.scalar() or 0)
            r = await db.execute(text("""
                SELECT COUNT(*) FROM broadcast_email_failed
                WHERE dead_letter_at IS NOT NULL
            """))
            dead_lifetime = int(r.scalar() or 0)

            if EMAIL_RETRY_PENDING is not None:
                try: EMAIL_RETRY_PENDING.labels(registry_id=self._registry_id).set(pending_now)
                except Exception: pass
            if EMAIL_RETRY_DEAD_LETTERED is not None:
                try: EMAIL_RETRY_DEAD_LETTERED.labels(registry_id=self._registry_id).set(dead_lifetime)
                except Exception: pass

            # Fetch up to 20 due retries
            due = await db.execute(
                select(models.BroadcastEmailFailed)
                .where(models.BroadcastEmailFailed.delivered_at.is_(None))
                .where(models.BroadcastEmailFailed.dead_letter_at.is_(None))
                .where(models.BroadcastEmailFailed.next_retry_at <= text("NOW()"))
                .order_by(models.BroadcastEmailFailed.next_retry_at.asc())
                .limit(20)
            )
            rows = due.scalars().all()

            for row in rows:
                attempts += 1
                # Load parent broadcast — if missing or retracted, dead-letter.
                parent = (await db.execute(
                    select(models.AdminBroadcast).where(models.AdminBroadcast.id == row.broadcast_id)
                )).scalar_one_or_none()
                if parent is None or not parent.is_active:
                    row.dead_letter_at = datetime.datetime.now(datetime.timezone.utc)
                    row.last_retry_at = row.dead_letter_at
                    row.error_reason = "parent broadcast missing or retracted"
                    dead_lettered += 1
                    await db.commit()
                    if EMAIL_RETRY_ATTEMPT_TOTAL is not None:
                        try: EMAIL_RETRY_ATTEMPT_TOTAL.labels(registry_id=self._registry_id, outcome="dead_lettered").inc()
                        except Exception: pass
                    continue

                ok, err = await _retry_one_batch(db, row, parent)
                now = datetime.datetime.now(datetime.timezone.utc)
                row.last_retry_at = now
                if ok:
                    row.delivered_at = now
                    delivered += 1
                    if EMAIL_RETRY_ATTEMPT_TOTAL is not None:
                        try: EMAIL_RETRY_ATTEMPT_TOTAL.labels(registry_id=self._registry_id, outcome="delivered").inc()
                        except Exception: pass
                else:
                    row.retry_count += 1
                    if row.retry_count >= _MAX_RETRIES:
                        row.dead_letter_at = now
                        row.error_reason = err or "unknown"
                        dead_lettered += 1
                        if EMAIL_RETRY_ATTEMPT_TOTAL is not None:
                            try: EMAIL_RETRY_ATTEMPT_TOTAL.labels(registry_id=self._registry_id, outcome="dead_lettered").inc()
                            except Exception: pass
                    else:
                        backoff = _BACKOFF_SEC[min(row.retry_count, _MAX_RETRIES - 1)]
                        row.next_retry_at = now + datetime.timedelta(seconds=backoff)
                        row.error_reason = err or "unknown"
                        failed += 1
                        if EMAIL_RETRY_ATTEMPT_TOTAL is not None:
                            try: EMAIL_RETRY_ATTEMPT_TOTAL.labels(registry_id=self._registry_id, outcome="failed").inc()
                            except Exception: pass
                await db.commit()

        self._stats = {
            "attempts_this_cycle": attempts,
            "delivered_this_cycle": delivered,
            "failed_this_cycle": failed,
            "dead_lettered_this_cycle": dead_lettered,
            "pending_now": pending_now,
            "dead_lettered_lifetime": dead_lifetime,
        }


_singleton: BroadcastEmailRetryWorker | None = None


def get_broadcast_email_retry_worker() -> BroadcastEmailRetryWorker:
    global _singleton
    if _singleton is None:
        _singleton = BroadcastEmailRetryWorker()
    return _singleton
