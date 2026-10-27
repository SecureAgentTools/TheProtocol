"""
Reactor: CrossFrameTransferSettled → sender-side pending clear
================================================================
Sender-frame reactor for the async cross-frame transfer path. Catches
`CrossFrameTransferSettled` events that arrived via the foreign_events
Pub/Sub bridge from the receiver frame (where the receiver reactor
emitted it after crediting). Updates the sender's `cross_frame_transfers`
row from `locked` → `settled`.

The sender's balance was already deducted at lock time in the entry
endpoint, so there is no balance change here — only the status update.

Filter: only acts when `source_frame` matches THIS frame's trust domain
(Settled events are emitted from the receiver but address the sender).

Idempotency:
- UPDATE WHERE status='locked' — only flips locked rows. Already-settled
  or refunded rows are no-ops (race with saga refund or replay).
- Reactor framework dedup-ring (256 entries) absorbs WS replay.
"""
from __future__ import annotations

import datetime
import logging
import os
import time
from typing import Optional

from sqlalchemy import update

from .. import models
from ..database import get_db_context
from .reactor_base import EventStoreReactor

logger = logging.getLogger(__name__)


def _this_frame_trust_domain() -> str:
    return os.getenv("SPIRE_TRUST_DOMAIN", "agentvault.com")


class CrossFrameSettledReactor(EventStoreReactor):
    event_type = "CrossFrameTransferSettled"
    leader_key = "reactor_cross_frame_settled"
    name = "CrossFrameSettled"
    # 2026-05-16: Tighten polling-backstop to 10s for cross-frame reactors.
    # See reactor_cross_frame_initiated.py for full rationale (SLO contract).
    polling_backstop_interval_seconds = int(
        os.environ.get("REACTOR_CROSS_FRAME_POLLING_BACKSTOP_INTERVAL_SEC", "10")
    )

    async def handle_event(self, event_data: dict) -> None:
        source_frame = event_data.get("source_frame", "")
        local_frame = _this_frame_trust_domain()
        if source_frame != local_frame:
            logger.debug(
                f"[Reactor:{self.name}] Skip — source_frame={source_frame} "
                f"!= local={local_frame}"
            )
            return

        transfer_id = event_data.get("transfer_id", "")
        if not transfer_id:
            logger.warning(f"[Reactor:{self.name}] Missing transfer_id in payload")
            return

        # Idempotent flip: only locked rows transition to settled.
        # If the row is already settled, refunded, or doesn't exist, no-op.
        async with get_db_context() as db:
            result = await db.execute(
                update(models.CrossFrameTransfer)
                .where(
                    models.CrossFrameTransfer.id == transfer_id,
                    models.CrossFrameTransfer.status == "locked",
                )
                .values(
                    status="settled",
                    settled_at=datetime.datetime.now(datetime.timezone.utc),
                )
                .returning(models.CrossFrameTransfer.id)
            )
            settled_id = result.scalar_one_or_none()
            await db.commit()

        if settled_id is None:
            logger.info(
                f"[Reactor:{self.name}] No locked row for transfer_id={transfer_id} "
                f"— already settled / refunded / unknown"
            )
            return

        logger.info(
            f"[Reactor:{self.name}] Cleared transfer_id={transfer_id} "
            f"(locked → settled)"
        )

        # §TRUSTWIRE (2026-09-10) — the peer-trust observation for this settlement is NOT
        # recorded here. It used to be, and that was the second of three hand-wired call sites
        # that between them still missed the FX pool swap. `CrossFrameTransferSettled` is one of
        # the three event types `reactor_peer_trust_observed` consumes, so this settlement is
        # observed there, once, alongside the paths this file never sees.

        # Vector A (2026-05-04) — adaptive saga concurrency: increment a per-frame,
        # per-minute Redis counter. saga_timeout_checker reads the last 5 buckets
        # to derive the cluster-wide Settled-event rate and scales the refund
        # semaphore accordingly. Best-effort; failure here is logged at debug
        # and never blocks the settle path.
        try:
            from .leader import get_redis
            r = await get_redis()
            if r is not None:
                bucket = int(time.time() // 60)
                key = f"cross_frame_settled_rate:{local_frame}:{bucket}"
                await r.incr(key)
                await r.expire(key, 600)
        except Exception as e:
            logger.debug(f"[Reactor:{self.name}] rate counter failed: {e}")


# ----------------------------------------------------------------------- module API

_instance: Optional[CrossFrameSettledReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = CrossFrameSettledReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
