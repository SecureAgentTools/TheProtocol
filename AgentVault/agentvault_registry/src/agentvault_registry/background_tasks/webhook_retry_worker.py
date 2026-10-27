"""
Background worker: Retry failed webhook deliveries.

Runs every 60 seconds, finds deliveries with retry_count < 5
and next_retry_at in the past, and re-delivers them.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.database import AsyncSessionLocal
from agentvault_registry import models
from agentvault_registry.services.webhook_service import WebhookService

logger = logging.getLogger(__name__)

_task = None


async def _retry_loop():
    """Background loop: retry failed webhook deliveries every 60 seconds."""
    from .leader import try_acquire_leadership
    logger.info("[WebhookRetry] Worker started")
    from . import vitals as _vitals
    await _vitals.register(
        "webhook_retry", module=__name__, pattern="hand-rolled",
        interval_sec=60, enabled=True,
    )
    while True:
        try:
            await asyncio.sleep(60)
            if not await try_acquire_leadership("webhook_retry"):
                continue
            async with _vitals.cycle("webhook_retry") as _ctx:
                retried, failed = await _retry_pending()
                _ctx.note(retried=retried, failed=failed)
            if retried > 0:
                logger.info(f"[WebhookRetry] Retried {retried} deliveries")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[WebhookRetry] Error: {e}")


async def _retry_pending() -> tuple[int, int]:
    """Find and retry pending webhook deliveries. Returns (retried, failed).

    §VITALS: a per-DELIVERY failure is not a cycle failure — it is counted and
    carried in the stamp. A failure of the whole query or session IS a cycle
    failure and is re-raised, so the cycle stamps `error` instead of returning a
    contented zero. The loop's own except still logs and continues.
    """
    count = 0
    failed = 0
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            result = await db.execute(
                select(models.WebhookDelivery).where(
                    and_(
                        models.WebhookDelivery.retry_count < 5,
                        models.WebhookDelivery.next_retry_at.isnot(None),
                        models.WebhookDelivery.next_retry_at <= now,
                        # §DOCSFIX D6-765 (2026-10-16): every non-2xx answer, as the service scheduled it. A 3xx is a
                        # failed attempt with a retry slot, and `>= 400` left that slot never run.
                        models.WebhookDelivery.response_status.is_(None) |
                        (models.WebhookDelivery.response_status >= 300),
                    )
                ).limit(20)  # Process max 20 per cycle
            )
            deliveries = result.scalars().all()

            if not deliveries:
                # The early return has to match the pair the caller unpacks. It did
                # not, and the §VITALS rail reported `TypeError: cannot unpack
                # non-iterable int object` within a minute of the deploy — which is
                # the whole point of the contract, applied to its own author twice.
                return 0, 0

            # Group by webhook to batch
            for delivery in deliveries:
                # Get the webhook
                wh_result = await db.execute(
                    select(models.DeveloperWebhook).where(
                        models.DeveloperWebhook.id == delivery.webhook_id,
                        models.DeveloperWebhook.is_active == True,
                    )
                )
                webhook = wh_result.scalar_one_or_none()
                if not webhook:
                    # Webhook deactivated or deleted — skip
                    delivery.retry_count = 5  # Stop retrying
                    delivery.next_retry_at = None  # and say so on the row: no retry is scheduled
                    continue

                # Retry THIS delivery in place (§TWOAGENT #33, 2026-09-23): same id, same envelope,
                # X-TheProtocol-Retry. Re-sending through deliver_webhook minted a fresh delivery every
                # cycle and left this row eligible forever: after the endpoint recovered, the same event
                # arrived once a minute under a new id each time (measured on sbx-alpha).
                try:
                    service = WebhookService()
                    async with service:
                        await service.retry_delivery(delivery, webhook, db)
                    count += 1
                except Exception as e:
                    failed += 1
                    logger.error(f"[WebhookRetry] Retry failed for delivery {delivery.id}: {e}")

            await db.commit()
    except Exception as e:
        logger.error(f"[WebhookRetry] DB error: {e}")
        raise

    return count, failed


async def start_webhook_retry_worker():
    global _task
    _task = asyncio.create_task(_retry_loop())


async def stop_webhook_retry_worker():
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
