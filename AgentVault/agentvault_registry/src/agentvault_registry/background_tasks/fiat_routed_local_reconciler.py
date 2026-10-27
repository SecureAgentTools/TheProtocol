"""PB-2 — Operator-side routed-fiat local reconciliation worker (2026-05-09).

Runs on operator registries only. Catches local FiatPurchase rows where:
  • PENDING for >24h with no callback (mainframe → operator callback was lost)
  • PROCESSING but no avt_transfer_tx_id (local treasury transfer never ran)

For each stuck row, queries the mainframe's
  GET /api/v1/admin/fiat/routed/{mainframe_fiat_purchase_id}
to get the canonical state. If mainframe says COMPLETED but operator side
PENDING/PROCESSING → re-trigger the local fund-agent step. If FAILED or
REFUNDED on mainframe → mark local FAILED. If NOT_FOUND → MANUAL_INTERVENTION
+ admin alert.

Skipped on mainframe (FIAT_GENESIS_REGISTRY=true). Operators with
ROUTED_FIAT_ENABLED=false are also skipped.

Default loop interval: hourly. Leader-elected via Redis.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
from typing import Optional

import httpx
from ..es_ssl_helper import get_httpx_verify
from sqlalchemy import select, and_, or_

from .. import models
from ..database import get_db_context
from ..models import FiatPurchase, FiatPurchaseStatus

logger = logging.getLogger(__name__)


RECONCILE_INTERVAL_SEC = int(os.getenv("FIAT_ROUTED_LOCAL_RECONCILER_INTERVAL_SEC", "3600"))
STALE_PENDING_HOURS = int(os.getenv("FIAT_ROUTED_LOCAL_STALE_PENDING_HOURS", "24"))


def _is_operator() -> bool:
    return os.getenv("FIAT_GENESIS_REGISTRY", "false").lower() != "true"


def _is_routed_fiat_enabled() -> bool:
    return os.getenv("ROUTED_FIAT_ENABLED", "false").lower() == "true"


class FiatRoutedLocalReconciler:
    """Background task — leader-elected, operator-only."""

    def __init__(self):
        self.running = False
        self.task: Optional[asyncio.Task] = None

    async def _run_loop(self):
        from .leader import try_acquire_leadership
        from . import vitals as _vitals
        # §FRAMELIC (2026-09-07, findings row 167) — DECLARE THE GATE YOU ARE ABOUT TO OBEY.
        # This used to register `enabled=True` and THEN return on its own gate, so the vitals
        # verdict read WARMING — "it has not run yet" — for a worker that had already decided
        # never to run. WARMING expires into NEVER_RAN and then reads as a fault; DISABLED is
        # the truth and stays true. Same shape as the roster's whole purpose: a worker that is
        # off is a ROW saying off, not an absence and not a pending arrival.
        _operator, _routed = _is_operator(), _is_routed_fiat_enabled()
        _gate = ("FIAT_GENESIS_REGISTRY=true (mainframe)" if not _operator
                 else "ROUTED_FIAT_ENABLED=false" if not _routed else "")
        await _vitals.register("fiat_routed_local_reconciler", module=__name__, pattern="hand-rolled",
                               interval_sec=RECONCILE_INTERVAL_SEC,
                               enabled=bool(_operator and _routed), gate=_gate)
        # Operator-only — mainframe skips (different reconciler does mainframe-side work)
        if not _operator:
            logger.info(
                "[FiatRoutedLocalReconciler] skipping on mainframe (FIAT_GENESIS_REGISTRY=true)"
            )
            return
        if not _routed:
            logger.info(
                "[FiatRoutedLocalReconciler] skipping (ROUTED_FIAT_ENABLED=false)"
            )
            return
        logger.info(
            "[FiatRoutedLocalReconciler] Started (interval=%ds, stale_pending=%dh)",
            RECONCILE_INTERVAL_SEC, STALE_PENDING_HOURS,
        )
        while self.running:
            try:
                if not await try_acquire_leadership("fiat_routed_local_reconciler"):
                    await asyncio.sleep(RECONCILE_INTERVAL_SEC)
                    continue
                async with _vitals.cycle("fiat_routed_local_reconciler"):
                    await self.check_once()
            except Exception as e:
                logger.error(f"[FiatRoutedLocalReconciler] Loop error: {e}", exc_info=True)
            await asyncio.sleep(RECONCILE_INTERVAL_SEC)

    async def check_once(self):
        """One reconciliation pass — find stuck routed rows + reconcile."""
        stale_floor = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            hours=STALE_PENDING_HOURS
        )
        async with get_db_context() as db:
            # Stuck rows: PENDING past 24h OR PROCESSING with no tx_id
            q = await db.execute(
                select(FiatPurchase).where(
                    and_(
                        FiatPurchase.routed == True,
                        FiatPurchase.mainframe_fiat_purchase_id.isnot(None),
                        or_(
                            and_(
                                FiatPurchase.status == FiatPurchaseStatus.PENDING.value,
                                FiatPurchase.created_at < stale_floor,
                            ),
                            and_(
                                FiatPurchase.status == FiatPurchaseStatus.PROCESSING.value,
                                FiatPurchase.avt_transfer_tx_id.is_(None),
                            ),
                        ),
                    )
                )
            )
            stuck = q.scalars().all()

        if not stuck:
            return
        logger.info("[FiatRoutedLocalReconciler] %d stuck row(s) to reconcile", len(stuck))
        for fp in stuck:
            await self._reconcile_one(fp)

    async def _reconcile_one(self, fp: FiatPurchase):
        """Query mainframe for canonical state; act accordingly."""
        mainframe_url = (
            os.getenv("MAINFRAME_PROXY_URL", "")
            or os.getenv("CENTRAL_REGISTRY_URL", "")
        ).strip()
        license_key = (
            os.getenv("FEDERATION_LICENSE_KEY", "")
            or os.getenv("MAINFRAME_FEDERATION_LICENSE_KEY", "")
        ).strip()
        if not mainframe_url or not license_key:
            logger.error(
                "[FiatRoutedLocalReconciler] missing MAINFRAME_PROXY_URL or FEDERATION_LICENSE_KEY"
            )
            return

        url = (
            mainframe_url.rstrip("/") + "/api/v1/admin/fiat/routed/" + fp.mainframe_fiat_purchase_id
        )
        try:
            async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
                resp = await client.get(
                    url,
                    headers={"X-Federation-License": license_key},
                )
        except Exception as exc:
            logger.warning(
                "[FiatRoutedLocalReconciler] mainframe query failed for %s: %s",
                fp.id, exc,
            )
            return

        if resp.status_code == 404:
            # Mainframe doesn't know this row — flag for manual review
            async with get_db_context() as db:
                current = await db.get(FiatPurchase, fp.id)
                if current and current.operator_callback_status != "manual_intervention":
                    current.operator_callback_status = "manual_intervention"
                    current.operator_callback_last_error = "mainframe row not found"
                    await db.commit()
                    logger.critical(
                        "[FiatRoutedLocalReconciler] purchase %s — mainframe row %s NOT FOUND. "
                        "MANUAL_INTERVENTION required.",
                        fp.id, fp.mainframe_fiat_purchase_id,
                    )
            return
        if resp.status_code != 200:
            logger.warning(
                "[FiatRoutedLocalReconciler] mainframe query %s returned %s",
                fp.id, resp.status_code,
            )
            return

        mf_state = resp.json()
        mf_status = mf_state.get("status")

        if mf_status in (FiatPurchaseStatus.FAILED.value, FiatPurchaseStatus.REFUNDED.value):
            async with get_db_context() as db:
                current = await db.get(FiatPurchase, fp.id)
                if current and current.status not in (
                    FiatPurchaseStatus.FAILED.value,
                    FiatPurchaseStatus.REFUNDED.value,
                ):
                    current.status = mf_status
                    current.failure_reason = (
                        mf_state.get("failure_reason") or "mainframe_says_failed"
                    )[:500]
                    if mf_status == FiatPurchaseStatus.REFUNDED.value:
                        current.refunded_at = datetime.datetime.now(datetime.timezone.utc)
                    await db.commit()
                    logger.info(
                        "[FiatRoutedLocalReconciler] purchase %s synced to %s from mainframe",
                        fp.id, mf_status,
                    )
            return

        if mf_status == FiatPurchaseStatus.COMPLETED.value:
            # Mainframe says COMPLETED but our row still PENDING/PROCESSING —
            # callback was lost in transit. Build a synthetic callback body
            # and call the local handler directly to fund the agent.
            logger.warning(
                "[FiatRoutedLocalReconciler] purchase %s — mainframe COMPLETED but local %s; "
                "re-running local fund step",
                fp.id, fp.status,
            )
            from ..routers.fiat_onramp import (
                _resolve_or_create_anonymous,
                _send_purchase_email,
                _grant_flare,
                _emit,
            )
            async with get_db_context() as db:
                current = await db.get(FiatPurchase, fp.id)
                if not current:
                    return
                # Pull authoritative amounts from mainframe state
                from decimal import Decimal as _Dec
                current.amount_eur = _Dec(str(mf_state.get("amount_eur") or current.amount_eur))
                current.amount_avt = _Dec(str(mf_state.get("amount_avt") or current.amount_avt))
                current.tier_label = mf_state.get("tier_label") or current.tier_label
                current.cross_teg_correlation_id = (
                    mf_state.get("cross_teg_correlation_id") or current.cross_teg_correlation_id
                )
                current.status = FiatPurchaseStatus.PROCESSING.value
                await db.commit()

                target_agent_did = current.agent_did
                developer_id = current.developer_id
                if current.anonymous_flow and not target_agent_did:
                    try:
                        target_agent_did, developer_id = await _resolve_or_create_anonymous(
                            db=db,
                            email=current.customer_email or mf_state.get("customer_email") or "",
                            purchase=current,
                            requested_developer_name=current.requested_developer_name,
                            requested_agent_name=current.requested_agent_name,
                        )
                        current.agent_did = target_agent_did
                        current.developer_id = developer_id
                        await db.commit()
                    except Exception as exc:
                        logger.exception(
                            "[FiatRoutedLocalReconciler] anon resolve failed for %s", current.id
                        )
                        return

                if not target_agent_did:
                    return

                # Fund local agent
                teg_url = (
                    os.getenv("TEG_API_BASE_URL")
                    or os.getenv("PARTNER_TEG_URL")
                    or "http://teg-layer:8080"
                )
                teg_admin_key = os.getenv("TEG_ADMIN_API_KEY", "")
                try:
                    async with httpx.AsyncClient(timeout=15.0, verify=get_httpx_verify()) as client:
                        resp = await client.post(
                            f"{teg_url}/api/v1/admin/treasury/transfer",
                            headers={"Authorization": f"Bearer {teg_admin_key}"},
                            json={
                                "target_agent_id": target_agent_did,
                                "amount": str(current.amount_avt),
                                "reason": "fiat_purchase",
                                "reference_id": current.id,
                            },
                        )
                        if resp.status_code != 200:
                            logger.error(
                                "[FiatRoutedLocalReconciler] local treasury/transfer failed %s: %s",
                                resp.status_code, resp.text[:200],
                            )
                            return
                        tx_data = resp.json()
                except Exception as exc:
                    logger.exception(
                        "[FiatRoutedLocalReconciler] local treasury error for %s", current.id
                    )
                    return

                current.avt_transfer_tx_id = tx_data.get("transaction_id", "")
                current.status = FiatPurchaseStatus.COMPLETED.value
                current.completed_at = datetime.datetime.now(datetime.timezone.utc)
                await db.commit()

                try:
                    await _grant_flare(
                        db=db,
                        purchase=current,
                        developer_id=developer_id,
                        target_agent_did=target_agent_did,
                    )
                except Exception:
                    pass

                await _emit(
                    event_type="FiatPurchaseSettled",
                    aggregate_id=current.id,
                    idempotency_key=f"fiat-settled-{current.id}",
                    data={
                        "fiat_purchase_id": current.id,
                        "mainframe_fiat_purchase_id": current.mainframe_fiat_purchase_id,
                        "agent_did": target_agent_did,
                        "amount_avt": str(current.amount_avt),
                        "tier_label": current.tier_label,
                        "tx_id": current.avt_transfer_tx_id,
                        "anonymous_flow": current.anonymous_flow,
                        "routed": True,
                        "recovered_via_reconciler": True,
                    },
                )
                asyncio.create_task(
                    _send_purchase_email(current, target_agent_did, current.avt_transfer_tx_id)
                )
                logger.info(
                    "[FiatRoutedLocalReconciler] purchase %s recovered locally — funded %s",
                    current.id, target_agent_did,
                )

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._run_loop())

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None


_singleton: Optional[FiatRoutedLocalReconciler] = None


def get_local_reconciler() -> FiatRoutedLocalReconciler:
    global _singleton
    if _singleton is None:
        _singleton = FiatRoutedLocalReconciler()
    return _singleton


async def start_fiat_routed_local_reconciler() -> None:
    await get_local_reconciler().start()


async def stop_fiat_routed_local_reconciler() -> None:
    if _singleton is not None:
        await _singleton.stop()
