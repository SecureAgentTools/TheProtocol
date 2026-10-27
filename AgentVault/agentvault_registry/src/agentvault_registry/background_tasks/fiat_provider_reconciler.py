"""PB-3 W5 — Generic PSP reconciliation worker (2026-05-12).

Mainframe-side background task that catches direct-flow FiatPurchase rows
where the PSP's webhook never fired (or arrived too late and the row is
stranded in `pending` status). For each stuck row, calls
`provider.retrieve_session(provider_session_id)` to read the PSP's
current state, and if the state has moved past `open`, synthesizes a
ProviderEvent and dispatches it through the normal handler pipeline.

Stripe DOES NOT need reconciliation in v1.0 — Stripe's webhook retry
window (3 days, exponential backoff) is generous enough that the
real-world stranded-purchase rate is near zero. This reconciler targets
Mollie + future PSPs whose retry windows are shorter (Mollie's is ~26h).

Scope:
  - payment_provider IN enabled_providers EXCEPT 'stripe' (Stripe self-heals)
  - status='pending'
  - provider_session_id IS NOT NULL (we have something to ask the PSP about)
  - created_at < NOW - INTERVAL '1 hour' (give the webhook a chance first)
  - routed=false (routed-flow has its own reconciler — fiat_routed_reconciler.py)

Mainframe-only via FIAT_GENESIS_REGISTRY env (operators don't issue
checkouts; they can't have stranded purchases).

Leader-elected via Redis. Single fire per cluster per cycle.

Gated by:
  REACTOR_FIAT_PROVIDER_RECONCILER_ENABLED=true|false (default false; sandbox-A flips true)

Strategy: PRODUCTION_DOCS/ROADMAP/Webhook_Fiat_Layer_Strategy.md §7.2 + §A.4 W5.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
from typing import Optional

from sqlalchemy import and_, select

from ..database import get_db_context
from ..models import FiatPurchase, FiatPurchaseStatus
from ..services.fiat_providers import ProviderEvent
from ..services.fiat_providers.registry import enabled_providers, get_provider

logger = logging.getLogger(__name__)


# Loop cadence (default hourly; sandbox-A may shorten via env)
RECONCILE_INTERVAL_SEC = int(os.getenv("FIAT_PROVIDER_RECONCILER_INTERVAL_SEC", "3600"))
# Grace window before reconciling — webhooks may legitimately take time
GRACE_PERIOD_MIN = int(os.getenv("FIAT_PROVIDER_RECONCILER_GRACE_MIN", "60"))
# Hard kill switch
ENABLED = os.getenv("REACTOR_FIAT_PROVIDER_RECONCILER_ENABLED", "false").lower() == "true"
# Genesis gate (mainframe-only)
IS_GENESIS = os.getenv("FIAT_GENESIS_REGISTRY", "false").lower() == "true"


class FiatProviderReconciler:
    """Background task — leader-elected, single-instance per cluster."""

    def __init__(self):
        self.running = False
        self.task: Optional[asyncio.Task] = None

    async def _run_loop(self):
        from .leader import try_acquire_leadership
        from . import vitals as _vitals
        await _vitals.register("fiat_provider_reconciler", module=__name__, pattern="hand-rolled",
                               interval_sec=RECONCILE_INTERVAL_SEC, enabled=True)

        logger.info(
            "[FiatProviderReconciler] Started (interval=%ds, grace=%dmin)",
            RECONCILE_INTERVAL_SEC, GRACE_PERIOD_MIN,
        )
        while self.running:
            try:
                if not await try_acquire_leadership("fiat_provider_reconciler"):
                    await asyncio.sleep(RECONCILE_INTERVAL_SEC)
                    continue
                async with _vitals.cycle("fiat_provider_reconciler"):
                    await self.check_once()
            except Exception as exc:
                logger.error("[FiatProviderReconciler] Loop error: %s", exc, exc_info=True)
            await asyncio.sleep(RECONCILE_INTERVAL_SEC)

    async def check_once(self):
        """One reconciliation pass. Imported + re-callable for tests."""
        # Build the set of providers to reconcile (skip stripe — Stripe self-heals).
        providers_to_check = [p for p in enabled_providers() if p != "stripe"]
        if not providers_to_check:
            return

        grace_floor = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            minutes=GRACE_PERIOD_MIN
        )

        async with get_db_context() as db:
            q = await db.execute(
                select(FiatPurchase).where(
                    and_(
                        FiatPurchase.payment_provider.in_(providers_to_check),
                        FiatPurchase.status == FiatPurchaseStatus.PENDING.value,
                        FiatPurchase.provider_session_id.isnot(None),
                        FiatPurchase.routed == False,
                        FiatPurchase.created_at < grace_floor,
                    )
                )
            )
            stuck = q.scalars().all()

        if not stuck:
            return

        logger.info(
            "[FiatProviderReconciler] %d stuck row(s) across providers=%s",
            len(stuck), providers_to_check,
        )
        for fp in stuck:
            try:
                await self._reconcile_one(fp)
            except Exception as exc:
                logger.error(
                    "[FiatProviderReconciler] reconcile failed for %s: %s",
                    fp.id, exc, exc_info=True,
                )

    async def _reconcile_one(self, fp: FiatPurchase) -> None:
        """Reconcile a single stuck row by re-pulling PSP state."""
        provider = get_provider(fp.payment_provider)
        if provider is None:
            logger.warning(
                "[FiatProviderReconciler] %s provider=%s no longer enabled; skipping",
                fp.id, fp.payment_provider,
            )
            return

        try:
            payment = await provider.retrieve_session(fp.provider_session_id)
        except Exception as exc:
            logger.warning(
                "[FiatProviderReconciler] %s retrieve_session failed: %s",
                fp.id, exc,
            )
            return

        # Normalize to ProviderEvent. Each provider's _normalize_event handles
        # its own envelope shape. We synthesize an event from a snapshot, not
        # from a real webhook delivery, so the L1 idempotency log will see a
        # fresh event_id and process it normally.
        try:
            # Provider-specific normalization — works because MollieProvider's
            # _normalize_event takes a Mollie payment resource dict directly.
            event: ProviderEvent = provider._normalize_event(payment)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.error(
                "[FiatProviderReconciler] %s _normalize_event failed: %s",
                fp.id, exc,
            )
            return

        if event.kind == "unknown":
            # PSP says it's still open / pending — leave for next cycle
            logger.debug(
                "[FiatProviderReconciler] %s still in-flight (kind=unknown)",
                fp.id,
            )
            return

        # Reconciler-synthesized events get a distinguishing event_id so the
        # L1 log records they came from reconciliation. If a real webhook
        # eventually arrives with the same provider_event_id, the L1 UNIQUE
        # gate catches it as a replay.
        logger.info(
            "[FiatProviderReconciler] %s dispatching reconciled event kind=%s provider_event_id=%s",
            fp.id, event.kind, event.provider_event_id,
        )

        # Lazy import to avoid circular dep
        from ..routers.fiat_onramp import _dispatch_provider_event
        await _dispatch_provider_event(event)

    async def start(self):
        if self.running:
            logger.warning("[FiatProviderReconciler] already running")
            return
        if not ENABLED:
            logger.info("[FiatProviderReconciler] disabled via REACTOR_FIAT_PROVIDER_RECONCILER_ENABLED")
            return
        if not IS_GENESIS:
            logger.info("[FiatProviderReconciler] mainframe-only (FIAT_GENESIS_REGISTRY!=true); skipping")
            return
        self.running = True
        self.task = asyncio.create_task(self._run_loop())
        logger.info("[FiatProviderReconciler] worker started")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        logger.info("[FiatProviderReconciler] worker stopped")


_singleton: Optional[FiatProviderReconciler] = None


def get_reconciler() -> FiatProviderReconciler:
    global _singleton
    if _singleton is None:
        _singleton = FiatProviderReconciler()
    return _singleton


async def start_fiat_provider_reconciler() -> None:
    await get_reconciler().start()


async def stop_fiat_provider_reconciler() -> None:
    if _singleton is not None:
        await _singleton.stop()


__all__ = [
    "FiatProviderReconciler",
    "get_reconciler",
    "start_fiat_provider_reconciler",
    "stop_fiat_provider_reconciler",
]
