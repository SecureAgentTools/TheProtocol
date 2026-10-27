"""Background task: attestation schedule cron (Phase 5).

Hourly cycle. For each `attestation_schedules` row where `enabled=TRUE
AND next_due_at < now AND last_reminder_at IS NULL OR < next_due_at`,
emit one `AttestationDueReminder` event and stamp `last_reminder_at` so
the next sweep skips it (one reminder per overdue cycle).

Configurable:
  ATTESTATION_SCHEDULE_CRON_ENABLED=true|false  (default true)
  ATTESTATION_SCHEDULE_CRON_INTERVAL_SECONDS    (default 3600)

The worker is leader-elected via Redis to avoid duplicate emission across
N uvicorn workers.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from ..database import get_db_context
from ..event_emitter import get_event_emitter
from ..crud import attestation as crud_attestation

logger = logging.getLogger(__name__)


def _is_enabled() -> bool:
    if os.getenv("ZKP_PHASE_5_ENABLED", "true").lower() != "true":
        return False
    return os.getenv("ATTESTATION_SCHEDULE_CRON_ENABLED", "true").lower() in (
        "true", "1", "yes",
    )


def _interval() -> int:
    try:
        return max(60, int(
            os.getenv("ATTESTATION_SCHEDULE_CRON_INTERVAL_SECONDS", "3600")
        ))
    except (ValueError, TypeError):
        return 3600


async def schedule_cycle_once(db) -> int:
    """Run a single sweep cycle synchronously. Returns count of reminders emitted.

    Caller provides an open AsyncSession (used by the sandbox-only debug
    endpoint `POST /admin/attestations/admin/run-schedule-cron`).
    """
    due = await crud_attestation.find_due_schedules(db, batch_size=200)
    if not due:
        return 0

    emitter = get_event_emitter()
    count = 0
    for row in due:
        try:
            # Idempotency key includes the next_due_at timestamp so that
            # a future overdue cycle for the SAME schedule emits a fresh
            # event (different key) without colliding with the prior one.
            idem = (
                f"attestation_due:{row.id}:"
                f"{int(row.next_due_at.timestamp())}"
            )
            await emitter.emit(
                event_type="AttestationDueReminder",
                aggregate_id=row.agent_did,
                data={
                    "schedule_id": str(row.id),
                    "agent_did": row.agent_did,
                    "circuit_id": row.circuit_id,
                    "interval_hours": row.interval_hours,
                    "next_due_at": row.next_due_at.isoformat(),
                    "last_attestation_at": (
                        row.last_attestation_at.isoformat()
                        if row.last_attestation_at else None
                    ),
                },
                idempotency_key=idem,
            )
            await crud_attestation.mark_reminder_sent(
                db, schedule_id=row.id, when=datetime.now(timezone.utc),
            )
            count += 1
        except Exception as exc:
            logger.error(
                f"[ScheduleCron] failed to emit/mark for {row.id}: {exc}",
                exc_info=True,
            )
    if count:
        logger.info(f"[ScheduleCron] swept {count} overdue schedule(s)")
    return count


class AttestationScheduleCronWorker:
    def __init__(self) -> None:
        self.running: bool = False
        self.task: Optional[asyncio.Task] = None

    async def _cycle(self) -> None:
        try:
            async with get_db_context() as db:
                await schedule_cycle_once(db)
        except Exception as exc:
            # §VITALS: covers the whole cycle — re-raised into the loop, which already
            # caught and continued.
            logger.error(f"[ScheduleCron] cycle error: {exc}", exc_info=True)
            raise

    async def run_forever(self) -> None:
        from .leader import try_acquire_leadership
        from . import vitals as _vitals

        interval = _interval()
        logger.info(
            f"[ScheduleCron] worker started (interval={interval}s, "
            f"enabled={_is_enabled()})"
        )
        self.running = True
        await _vitals.register("attestation_schedule_cron", module=__name__,
                               pattern="hand-rolled", interval_sec=interval, enabled=True)
        while self.running:
            try:
                if not _is_enabled():
                    await asyncio.sleep(interval)
                    continue
                if not await try_acquire_leadership("attestation_schedule_cron"):
                    await asyncio.sleep(interval)
                    continue
                async with _vitals.cycle("attestation_schedule_cron"):
                    await self._cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[ScheduleCron] unexpected: {exc}", exc_info=True)
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    async def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass


_worker: Optional[AttestationScheduleCronWorker] = None


def get_attestation_schedule_cron_worker() -> AttestationScheduleCronWorker:
    global _worker
    if _worker is None:
        _worker = AttestationScheduleCronWorker()
    return _worker


async def start_attestation_schedule_cron() -> None:
    await get_attestation_schedule_cron_worker().start()


async def stop_attestation_schedule_cron() -> None:
    await get_attestation_schedule_cron_worker().stop()
