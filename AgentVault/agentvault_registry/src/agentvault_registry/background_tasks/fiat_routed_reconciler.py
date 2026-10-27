"""PB-2 — Mainframe-side routed-fiat reconciliation worker (2026-05-09).

Runs on the mainframe registry-a (or sandbox-A) only. Catches routed-fiat
purchases where the cross-TEG fund succeeded but the operator callback
failed or never landed. Re-attempts the HMAC-signed callback up to 5 times
before flagging as MANUAL_INTERVENTION (admin alert via SecurityAlerts@).

Scan target (from migration 0038's partial index):
  routed=true
  AND status='PROCESSING'
  AND cross_teg_correlation_id IS NOT NULL
  AND operator_callback_status IN ('pending','failed')
  AND (operator_callback_last_attempted_at IS NULL OR
       operator_callback_last_attempted_at < NOW - INTERVAL '15 minutes')

Default loop interval: hourly (RECONCILE_INTERVAL_SEC). Sandbox-A may set
shorter for test cadence. Leader-elected via Redis (single fire per cluster).

Mirrors the saga_timeout_checker.py pattern.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
from typing import Optional

from sqlalchemy import select, and_, or_

from .. import models
from ..database import get_db_context
from ..models import FiatPurchase, FiatPurchaseStatus

logger = logging.getLogger(__name__)


RECONCILE_INTERVAL_SEC = int(os.getenv("FIAT_ROUTED_RECONCILER_INTERVAL_SEC", "3600"))
RETRY_COOLDOWN_MIN = int(os.getenv("FIAT_ROUTED_RECONCILER_RETRY_COOLDOWN_MIN", "15"))
MAX_RETRIES = int(os.getenv("FIAT_ROUTED_RECONCILER_MAX_RETRIES", "5"))


class FiatRoutedReconciler:
    """Background task — leader-elected, single-instance per cluster."""

    def __init__(self):
        self.running = False
        self.task: Optional[asyncio.Task] = None

    async def _run_loop(self):
        from .leader import try_acquire_leadership
        from . import vitals as _vitals
        await _vitals.register("fiat_routed_reconciler", module=__name__, pattern="hand-rolled",
                               interval_sec=RECONCILE_INTERVAL_SEC, enabled=True)
        logger.info(
            "[FiatRoutedReconciler] Started (interval=%ds, cooldown=%dmin, max=%d)",
            RECONCILE_INTERVAL_SEC, RETRY_COOLDOWN_MIN, MAX_RETRIES,
        )
        while self.running:
            try:
                if not await try_acquire_leadership("fiat_routed_reconciler"):
                    await asyncio.sleep(RECONCILE_INTERVAL_SEC)
                    continue
                async with _vitals.cycle("fiat_routed_reconciler"):
                    await self.check_once()
            except Exception as e:
                logger.error(f"[FiatRoutedReconciler] Loop error: {e}", exc_info=True)
            await asyncio.sleep(RECONCILE_INTERVAL_SEC)

    async def check_once(self):
        """One reconciliation pass. Imported and re-callable for tests."""
        cooldown_floor = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            minutes=RETRY_COOLDOWN_MIN
        )
        async with get_db_context() as db:
            q = await db.execute(
                select(FiatPurchase).where(
                    and_(
                        FiatPurchase.routed == True,
                        FiatPurchase.status == FiatPurchaseStatus.PROCESSING.value,
                        FiatPurchase.cross_teg_correlation_id.isnot(None),
                        FiatPurchase.operator_callback_status.in_(("pending", "failed")),
                        or_(
                            FiatPurchase.operator_callback_last_attempted_at.is_(None),
                            FiatPurchase.operator_callback_last_attempted_at < cooldown_floor,
                        ),
                    )
                )
            )
            stuck = q.scalars().all()

        if not stuck:
            return

        logger.info("[FiatRoutedReconciler] %d stuck row(s) to retry", len(stuck))
        for fp in stuck:
            await self._retry_callback(fp)

    async def _retry_callback(self, fp: FiatPurchase):
        """Retry the HMAC-signed callback for one stuck row."""
        from ..routers.fiat_onramp import _post_operator_callback

        async with get_db_context() as db:
            # Re-fetch to avoid stale state
            current = await db.get(FiatPurchase, fp.id)
            if not current or current.status != FiatPurchaseStatus.PROCESSING.value:
                return
            if current.operator_callback_attempts >= MAX_RETRIES:
                # Promote to MANUAL_INTERVENTION (admin alert)
                if current.operator_callback_status != "manual_intervention":
                    current.operator_callback_status = "manual_intervention"
                    await db.commit()
                    logger.critical(
                        "[FiatRoutedReconciler] purchase %s reached max retries (%d) — "
                        "MANUAL_INTERVENTION required. operator=%s correlation=%s",
                        current.id, MAX_RETRIES,
                        current.target_operator_did, current.cross_teg_correlation_id,
                    )
                return

            # Resolve target peer for callback delivery
            peer_q = await db.execute(
                select(models.PeerRegistry).where(
                    models.PeerRegistry.name == current.target_operator_registry_name,
                    models.PeerRegistry.status == "ACTIVE",
                )
            )
            peer = peer_q.scalar_one_or_none()
            if not peer:
                current.operator_callback_status = "failed"
                current.operator_callback_last_error = (
                    f"target_peer_inactive_or_missing: {current.target_operator_registry_name}"
                )
                current.operator_callback_attempts += 1
                current.operator_callback_last_attempted_at = datetime.datetime.now(datetime.timezone.utc)
                await db.commit()
                return

            body = {
                "mainframe_fiat_purchase_id": current.id,
                "stripe_session_id": current.stripe_session_id,
                "stripe_payment_intent_id": current.stripe_payment_intent_id,
                "amount_eur": str(current.amount_eur),
                "amount_avt": str(current.amount_avt),
                "tier_label": current.tier_label,
                "anonymous_flow": current.anonymous_flow,
                "customer_email": current.customer_email,
                "agent_did": current.agent_did or "",
                "requested_developer_name": current.requested_developer_name,
                "requested_agent_name": current.requested_agent_name,
                "operator_did": current.target_operator_did,
                "operator_registry_name": current.target_operator_registry_name,
                "cross_teg_correlation_id": current.cross_teg_correlation_id,
                "_retry_attempt": current.operator_callback_attempts + 1,
            }
            current.operator_callback_attempts += 1
            current.operator_callback_last_attempted_at = datetime.datetime.now(datetime.timezone.utc)
            ok, err = await _post_operator_callback(peer=peer, body=body)
            if ok:
                current.operator_callback_status = "success"
                current.status = FiatPurchaseStatus.COMPLETED.value
                current.completed_at = datetime.datetime.now(datetime.timezone.utc)
                current.operator_callback_last_error = None
                logger.info(
                    "[FiatRoutedReconciler] purchase %s recovered after %d attempts",
                    current.id, current.operator_callback_attempts,
                )
            else:
                current.operator_callback_status = "failed"
                current.operator_callback_last_error = err[:500]
                logger.warning(
                    "[FiatRoutedReconciler] purchase %s retry %d/%d failed: %s",
                    current.id, current.operator_callback_attempts, MAX_RETRIES, err,
                )
            await db.commit()

    async def start(self):
        if self.running:
            logger.warning("[FiatRoutedReconciler] already running")
            return
        self.running = True
        self.task = asyncio.create_task(self._run_loop())
        logger.info("[FiatRoutedReconciler] worker started")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        logger.info("[FiatRoutedReconciler] worker stopped")


_singleton: Optional[FiatRoutedReconciler] = None


def get_reconciler() -> FiatRoutedReconciler:
    global _singleton
    if _singleton is None:
        _singleton = FiatRoutedReconciler()
    return _singleton


async def start_fiat_routed_reconciler() -> None:
    await get_reconciler().start()


async def stop_fiat_routed_reconciler() -> None:
    if _singleton is not None:
        await _singleton.stop()
