"""§bc2 T2.2 — Scheduled-broadcast firing worker.

BackgroundWorker subclass; cadence 30s. Leader-elected via Redis lock.

Per cycle:
  1. Query `admin_broadcasts` for rows where `scheduled_for <= NOW()` AND
     `email_sent_at IS NULL` AND `is_active=TRUE`. Limit 50 per cycle.
  2. For each: claim the row by NULLing `scheduled_for` in a sub-transaction
     FIRST, with one conditional UPDATE; only the cycle whose UPDATE changed
     the row sends it. This guarantees no double-fire if the worker crashes
     between WS-send and column-null (a crash AFTER NULL = missed broadcast —
     acceptable, admin can re-trigger; double-fire is worse than miss), and
     none when two cycles selected the same row.
  3. Then send it as an immediate broadcast is sent: the live push
     (admin_broadcast.live_notice to admin_broadcast.ws_audience) and, when
     `send_email` is set, its email once (admin_broadcast._send_broadcast_email:
     the broadcast's own audience). `email_sent_at` records that email; the
     claim, not that column, is what keeps a fired row from firing again.

Env gate:
  REACTOR_BROADCAST_SCHEDULER_ENABLED=true|false  (default true)

Snapshot stats:
  - cycles_24h, fired_24h, missed_24h, errors_24h
  - last_fired_iso
  - next_scheduled_iso  (peek at next pending broadcast)
"""
from __future__ import annotations

import datetime
import logging
import os
from typing import Any

from sqlalchemy import func, select, text, update

from agentvault_registry.database import get_db_context
from agentvault_registry import models
from agentvault_registry.routers.websocket import manager as ws_manager

from ._worker_base import BackgroundWorker, WORKER_ERRORS_TOTAL

logger = logging.getLogger(__name__)


try:
    from prometheus_client import Counter as _BC, Gauge as _BG

    BROADCAST_SCHEDULER_FIRED_TOTAL = _BC(
        "broadcast_scheduler_fired_total",
        "Total scheduled broadcasts fired",
        labelnames=["registry_id", "broadcast_type"],
    )
    BROADCAST_SCHEDULER_PENDING = _BG(
        "broadcast_scheduler_pending",
        "Pending scheduled broadcasts (scheduled_for <= NOW() and not yet fired)",
        labelnames=["registry_id"],
        multiprocess_mode="max",
    )
except Exception:  # pragma: no cover
    BROADCAST_SCHEDULER_FIRED_TOTAL = None
    BROADCAST_SCHEDULER_PENDING = None


class BroadcastScheduler(BackgroundWorker):
    worker_id = "broadcast_scheduler"
    leader_key = "broadcast_scheduler"
    interval_sec = 30
    cold_start_delay_sec = 6

    def _should_run(self) -> bool:
        return os.getenv("REACTOR_BROADCAST_SCHEDULER_ENABLED", "true").lower() == "true"

    def _count_error(self, reason: str) -> None:
        if WORKER_ERRORS_TOTAL is not None:
            try:
                WORKER_ERRORS_TOTAL.labels(worker_id=self.worker_id, reason=reason).inc()
            except Exception:
                pass

    async def _cycle_once(self) -> None:
        fired = 0
        errors = 0
        last_fired_id: int | None = None
        last_fired_at: datetime.datetime | None = None
        next_scheduled_at: datetime.datetime | None = None
        pending_now = 0

        async with get_db_context() as db:
            # Snapshot: how many are pending RIGHT NOW (pre-fire)
            r = await db.execute(text("""
                SELECT COUNT(*) FROM admin_broadcasts
                WHERE scheduled_for IS NOT NULL
                  AND scheduled_for <= NOW()
                  AND email_sent_at IS NULL
                  AND is_active = TRUE
            """))
            pending_now = int(r.scalar() or 0)
            if BROADCAST_SCHEDULER_PENDING is not None:
                try:
                    BROADCAST_SCHEDULER_PENDING.labels(registry_id=self._registry_id).set(pending_now)
                except Exception:
                    pass

            # Peek the next pending in the future (for snapshot only)
            r = await db.execute(text("""
                SELECT scheduled_for FROM admin_broadcasts
                WHERE scheduled_for IS NOT NULL AND scheduled_for > NOW()
                  AND email_sent_at IS NULL AND is_active = TRUE
                ORDER BY scheduled_for ASC LIMIT 1
            """))
            row = r.first()
            if row is not None and row[0] is not None:
                next_scheduled_at = row[0]

            # Fire up to 50 due broadcasts this cycle
            due = await db.execute(
                select(models.AdminBroadcast)
                .where(models.AdminBroadcast.scheduled_for.is_not(None))
                .where(models.AdminBroadcast.scheduled_for <= text("NOW()"))
                .where(models.AdminBroadcast.email_sent_at.is_(None))
                .where(models.AdminBroadcast.is_active == True)  # noqa: E712
                .order_by(models.AdminBroadcast.scheduled_for.asc())
                .limit(50)
            )
            broadcasts = due.scalars().all()

            # A scheduled broadcast goes out as an immediate one does (§SECFIX D6-304): the scheduled path pushed title,
            # message and type only, and never sent the email a broadcast with send_email asked for.
            from agentvault_registry.routers.admin_broadcast import (
                _send_broadcast_email, live_notice, live_reach, ws_audience)
            table = models.AdminBroadcast.__table__

            for b in broadcasts:
                # Sub-tx: claim the row by NULLing scheduled_for FIRST, so a crash between here and the send results in a
                # missed broadcast (acceptable) rather than a double-fired one (worse). Only the cycle whose UPDATE
                # changed the row sends it: a row another cycle claimed after both selected it, or one retracted since,
                # is left alone (the UPDATE asks the due query's own conditions).
                try:
                    claim = await db.execute(
                        text("""
                            UPDATE admin_broadcasts
                            SET scheduled_for = NULL
                            WHERE id = :id AND scheduled_for IS NOT NULL
                              AND email_sent_at IS NULL AND is_active = TRUE
                        """),
                        {"id": b.id},
                    )
                    await db.commit()
                except Exception as e:
                    errors += 1
                    logger.warning(
                        f"[broadcast_scheduler] failed to null scheduled_for #{b.id}: {e}"
                    )
                    self._count_error("null_scheduled_for")
                    continue
                if claim.rowcount != 1:
                    logger.info(f"[broadcast_scheduler] broadcast #{b.id} was claimed elsewhere or retracted: not sent here")
                    continue

                # the broadcast's own audience (its organization's members): a scheduled org notice went to every
                # connected developer of the frame (§FESUITE lifecycle 87)
                audience = ws_audience(b)
                pushed = emailed = False
                try:
                    await ws_manager.broadcast(live_notice(b), audience=audience)
                    pushed = True
                except Exception as e:
                    errors += 1
                    logger.error(f"[broadcast_scheduler] failed to push broadcast #{b.id}: {e}", exc_info=True)
                    self._count_error("fire")
                if b.send_email:
                    # Once: the claim above is the only way here. _send_broadcast_email mails the broadcast's own
                    # audience (its developer, its organization's active members, or everyone) and records a failed
                    # batch for broadcast_email_retry_worker.
                    try:
                        await _send_broadcast_email(b, db)
                        emailed = True
                    except Exception as e:
                        errors += 1
                        logger.error(f"[broadcast_scheduler] failed to email broadcast #{b.id}: {e}", exc_info=True)
                        self._count_error("email")
                if not (pushed or emailed):
                    continue
                fired += 1
                last_fired_id = b.id
                last_fired_at = datetime.datetime.now(datetime.timezone.utc)
                if BROADCAST_SCHEDULER_FIRED_TOTAL is not None:
                    try:
                        BROADCAST_SCHEDULER_FIRED_TOTAL.labels(
                            registry_id=self._registry_id,
                            broadcast_type=b.broadcast_type,
                        ).inc()
                    except Exception:
                        pass
                # §FESUITE V0595: the reach a scheduled send had (its audience online at fire time); it stored none.
                # email_sent_at says the email went out (the console shows it, the overview counts it), as on an
                # immediate send: it was stamped on every scheduled broadcast, email or not, as the do-not-refire
                # signal the claim is now.
                try:
                    values = {"ws_recipients": await live_reach(db, audience) if pushed else 0}
                    if emailed:
                        values["email_sent_at"] = func.now()
                    await db.execute(update(table).where(table.c.id == b.id).values(**values))
                    await db.commit()
                except Exception as e:
                    logger.warning(
                        f"[broadcast_scheduler] failed to record the send of #{b.id}: {e}"
                    )

        # Stats for /admin/broadcast-scheduler/status
        self._stats = {
            "fired_this_cycle": fired,
            "errors_this_cycle": errors,
            "pending_now": pending_now,
            "last_fired_id": last_fired_id,
            "last_fired_iso": last_fired_at.isoformat() if last_fired_at else None,
            "next_scheduled_iso": next_scheduled_at.isoformat() if next_scheduled_at else None,
        }


_singleton: BroadcastScheduler | None = None


def get_broadcast_scheduler() -> BroadcastScheduler:
    global _singleton
    if _singleton is None:
        _singleton = BroadcastScheduler()
    return _singleton
