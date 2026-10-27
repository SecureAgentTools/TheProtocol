"""SF-3: Bridge Expiry Worker

Finds LOCKED bridge transactions past their expires_at and compensates:
- Unlocks escrowed funds on local TEG
- Marks transaction as EXPIRED
- Emits BridgeTransferExpired event for reactor #16 (developer notification)

Runs every 60 seconds with leader election (same pattern as a2a_payment_expiry).
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx
from ..es_ssl_helper import get_httpx_verify
from sqlalchemy import select, update

from ..database import AsyncSessionLocal
from .. import models

logger = logging.getLogger(__name__)
_running = False


async def _expire_stale_bridges():
    """Find and expire bridge transactions past their timeout."""
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            result = await db.execute(
                select(models.BridgeTransaction).where(
                    models.BridgeTransaction.status == "LOCKED",
                    models.BridgeTransaction.expires_at < now,
                    models.BridgeTransaction.direction == "outbound",
                )
            )
            expired = result.scalars().all()

            if not expired:
                return

            teg_url = os.environ.get("TEG_API_BASE_URL", "http://teg-layer:8080")
            teg_key = os.environ.get("TEG_ADMIN_API_KEY", "")
            unlocked_for_emit = []

            for tx in expired:
                try:
                    # Unlock escrowed funds
                    async with httpx.AsyncClient(timeout=15, verify=get_httpx_verify()) as client:
                        resp = await client.post(
                            f"{teg_url}/api/v1/bridge/unlock",
                            json={
                                "agent_id": tx.source_agent_did,
                                "amount": str(tx.amount),
                                "bridge_tx_id": tx.id,
                            },
                            headers={"Authorization": f"Bearer {teg_key}"},
                        )
                        if resp.status_code == 200:
                            tx.status = "EXPIRED"
                            tx.error_message = "Bridge timeout — funds unlocked"
                            logger.info(f"[BridgeExpiry] Expired + unlocked {tx.amount} AVT for {tx.source_agent_did} (tx={tx.id})")
                            unlocked_for_emit.append(tx)
                        else:
                            logger.error(f"[BridgeExpiry] Unlock failed for {tx.id}: {resp.status_code}")
                except Exception as e:
                    logger.error(f"[BridgeExpiry] Error expiring {tx.id}: {e}")

            await db.commit()
            if expired:
                logger.info(f"[BridgeExpiry] Processed {len(expired)} expired bridge transactions")

            # Emit BridgeTransferExpired AFTER successful commit so reactor sees
            # the persisted EXPIRED row. Idempotent on bridge_tx_id.
            if unlocked_for_emit:
                from ..event_emitter import get_event_emitter
                emitter = get_event_emitter()
                for tx in unlocked_for_emit:
                    emitter.emit_background(
                        event_type="BridgeTransferExpired",
                        aggregate_id=tx.id,
                        aggregate_type="BridgeTransaction",
                        data={
                            "bridge_tx_id": tx.id,
                            "source_frame_id": tx.source_frame_id,
                            "target_frame_id": tx.target_frame_id,
                            "source_agent_did": tx.source_agent_did,
                            "target_agent_did": tx.target_agent_did,
                            "amount": str(tx.amount),
                            "expired_at": now.isoformat(),
                            "expires_at": tx.expires_at.isoformat() if tx.expires_at else None,
                        },
                        idempotency_key=f"bridge_expired:{tx.id}",
                    )
    except Exception as e:
        # §VITALS: re-raised so the cycle stamps `error`. The loop still catches and
        # continues, so behaviour is unchanged — a failed sweep just stops looking
        # identical to a sweep with nothing to do.
        logger.error(f"[BridgeExpiry] Sweep error: {e}")
        raise


async def bridge_expiry_loop():
    """Background loop — runs every 60 seconds with leader election."""
    from .leader import try_acquire_leadership
    global _running
    _running = True
    from . import vitals as _vitals
    await _vitals.register("bridge_expiry", module=__name__,
                           pattern="hand-rolled", interval_sec=60, enabled=True)
    while _running:
        try:
            if await try_acquire_leadership("bridge_expiry"):
                async with _vitals.cycle("bridge_expiry"):
                    await _expire_stale_bridges()
        except Exception as e:
            logger.error(f"[BridgeExpiry] Cycle error: {e}")
        await asyncio.sleep(60)


def stop():
    global _running
    _running = False
