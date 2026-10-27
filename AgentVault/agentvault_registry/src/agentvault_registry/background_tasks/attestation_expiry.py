"""Background task: ZKP attestation expiry sweeper (Phase 2).

Daily cycle. For each attestation row where `expires_at < now() AND
revoked_at IS NULL AND expired_emitted_at IS NULL`, emit one
`AttestationExpired` event and stamp `expired_emitted_at` so the next
sweep skips it (daily idempotency).

Configurable:
  ATTESTATION_EXPIRY_ENABLED=true|false  (default true)
  ATTESTATION_EXPIRY_INTERVAL_SECONDS    (default 86400)

The sweeper is leader-elected via Redis to avoid duplicate emission across
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
    if os.getenv("ZKP_PHASE_2_ENABLED", "true").lower() != "true":
        return False
    return os.getenv("ATTESTATION_EXPIRY_ENABLED", "true").lower() in ("true", "1", "yes")


def _interval() -> int:
    try:
        return max(60, int(os.getenv("ATTESTATION_EXPIRY_INTERVAL_SECONDS", "86400")))
    except (ValueError, TypeError):
        return 86400


async def expiry_cycle_once(db) -> int:
    """Run a single sweep cycle synchronously. Returns count of events emitted.

    The caller is responsible for providing an open AsyncSession (used by the
    sandbox-only debug endpoint `POST /admin/attestations/run-expiry-sweep`).
    """
    expired = await crud_attestation.find_expired_pending(db, batch_size=200)
    if not expired:
        return 0

    emitter = get_event_emitter()
    count = 0
    for row in expired:
        try:
            await emitter.emit(
                event_type="AttestationExpired",
                aggregate_id=row.agent_did,
                data={
                    "attestation_id": str(row.id),
                    "agent_did": row.agent_did,
                    "circuit_id": row.circuit_id,
                    "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                    "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
                },
                idempotency_key=f"attestation_expired:{row.id}",
            )
            await crud_attestation.mark_expired_emitted(
                db, attestation_id=row.id, when=datetime.now(timezone.utc)
            )
            count += 1
        except Exception as exc:
            logger.error(
                f"[AttestationExpiry] failed to emit/mark for {row.id}: {exc}",
                exc_info=True,
            )
    if count:
        logger.info(f"[AttestationExpiry] swept {count} expired attestation(s)")
    return count


class AttestationExpiryWorker:
    def __init__(self) -> None:
        self.running: bool = False
        self.task: Optional[asyncio.Task] = None

    async def _cycle(self) -> None:
        try:
            async with get_db_context() as db:
                await expiry_cycle_once(db)
        except Exception as exc:
            # §VITALS: this try covers the whole cycle, so swallowing here made a
            # failed sweep identical to a sweep with nothing to do. Re-raised into
            # the loop, which already caught and continued.
            logger.error(f"[AttestationExpiry] cycle error: {exc}", exc_info=True)
            raise

    async def run_forever(self) -> None:
        from .leader import try_acquire_leadership
        from . import vitals as _vitals

        interval = _interval()
        logger.info(
            f"[AttestationExpiry] worker started (interval={interval}s, "
            f"enabled={_is_enabled()})"
        )
        self.running = True
        await _vitals.register("attestation_expiry", module=__name__,
                               pattern="hand-rolled", interval_sec=interval, enabled=True)
        while self.running:
            try:
                if not _is_enabled():
                    await asyncio.sleep(interval)
                    continue
                if not await try_acquire_leadership("attestation_expiry"):
                    await asyncio.sleep(interval)
                    continue
                async with _vitals.cycle("attestation_expiry"):
                    await self._cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[AttestationExpiry] unexpected: {exc}", exc_info=True)
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


_worker: Optional[AttestationExpiryWorker] = None


def get_attestation_expiry_worker() -> AttestationExpiryWorker:
    global _worker
    if _worker is None:
        _worker = AttestationExpiryWorker()
    return _worker


async def start_attestation_expiry() -> None:
    await get_attestation_expiry_worker().start()


async def stop_attestation_expiry() -> None:
    await get_attestation_expiry_worker().stop()
