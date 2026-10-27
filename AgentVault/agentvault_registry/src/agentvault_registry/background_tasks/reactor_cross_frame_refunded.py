"""
Reactor: CrossFrameTransferRefunded → receiver-side compensating reverse
=========================================================================
Receiver-frame reactor for the async cross-frame transfer path. Catches
`CrossFrameTransferRefunded` events emitted by the sender frame's saga
sweeper after a 5-min timeout. If we previously credited the recipient
(inbound row exists with status='credited'), we MUST reverse the credit
to keep the supply invariant intact across both frames.

Filter: only acts when `target_frame` matches THIS frame's trust domain.

Idempotency:
- UPDATE WHERE status='credited' — already-reversed rows are no-ops.
- TEG /cross-teg/reverse-async dedups on transfer_id.
- If no inbound row exists at all, sender refunded before we credited
  (the normal "everyone agrees" timeout path) — pure no-op.
- Reactor framework dedup-ring absorbs WS replay.

This is the COMPENSATING ACTION of the saga. Without it, a race where
SF-4 lost the Settled event but the receiver actually credited would
double-count tokens (sender refunded + receiver credited). The reactor
catches the receiver side back up to the sender's view.
"""
from __future__ import annotations

import datetime
import logging
import os
import uuid
from decimal import Decimal
from typing import Optional

import httpx
from ..es_ssl_helper import get_httpx_verify
from sqlalchemy import select, update

from .. import models
from ..database import get_db_context
from .reactor_base import EventStoreReactor

logger = logging.getLogger(__name__)


def _this_frame_trust_domain() -> str:
    return os.getenv("SPIRE_TRUST_DOMAIN", "agentvault.com")


def _reverse_txid(transfer_id: str) -> str:
    """§PlanB-②: deterministic, collision-free reverse-leg id (distinct from
    transfer_id — the credit RECEIVE leg holds that on this same TEG). Used as
    BOTH the reverse leg's transaction_id (via /reverse-async) AND the audit
    CrossFrameTransferReversed.data.transaction_id, so the listed reverse leg
    resolves in getTegTransactionDetail."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"theprotocol:cross_frame_reverse:{transfer_id}"))


class CrossFrameRefundedReactor(EventStoreReactor):
    event_type = "CrossFrameTransferRefunded"
    leader_key = "reactor_cross_frame_refunded"
    name = "CrossFrameRefunded"
    # 2026-05-16: Tighten polling-backstop to 10s for cross-frame reactors.
    # See reactor_cross_frame_initiated.py for full rationale (SLO contract).
    polling_backstop_interval_seconds = int(
        os.environ.get("REACTOR_CROSS_FRAME_POLLING_BACKSTOP_INTERVAL_SEC", "10")
    )

    async def handle_event(self, event_data: dict) -> None:
        target_frame = event_data.get("target_frame", "")
        local_frame = _this_frame_trust_domain()
        if target_frame != local_frame:
            logger.debug(
                f"[Reactor:{self.name}] Skip — target_frame={target_frame} "
                f"!= local={local_frame}"
            )
            return

        transfer_id = event_data.get("transfer_id", "")
        if not transfer_id:
            logger.warning(f"[Reactor:{self.name}] Missing transfer_id in payload")
            return

        # Look up the inbound row. If absent, sender refunded before we
        # ever credited — nothing to reverse.
        async with get_db_context() as db:
            row = (await db.execute(
                select(models.CrossFrameTransferInbound).where(
                    models.CrossFrameTransferInbound.id == transfer_id
                )
            )).scalar_one_or_none()

        if row is None:
            logger.info(
                f"[Reactor:{self.name}] No inbound row for transfer_id={transfer_id} "
                f"— sender refunded before we credited (normal path)"
            )
            return

        if row.status != "credited":
            # "reversed": already reversed; "refused" (D6-801, a credit from a quarantined peer): never credited here
            logger.info(
                f"[Reactor:{self.name}] transfer_id={transfer_id} is {row.status} here, not credited "
                f"— nothing to reverse"
            )
            return

        # We previously credited. Reverse via TEG (idempotent on transfer_id).
        teg_url = os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080")
        teg_key = os.getenv("TEG_ADMIN_API_KEY", "")
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
                resp = await client.post(
                    f"{teg_url}/api/v1/cross-teg/reverse-async",
                    json={
                        "transfer_id": transfer_id,
                        "receiver_did": row.receiver_did,
                        "amount": str(row.amount),
                        "source_frame": row.source_frame,
                        "idempotency_key": f"reverse-{transfer_id}",
                        "reversal_txid": _reverse_txid(transfer_id),  # §PlanB-②: reverse leg PK (≠ transfer_id)
                    },
                    headers={"Authorization": f"Bearer {teg_key}"},
                )
        except Exception as e:
            logger.warning(
                f"[Reactor:{self.name}] TEG reverse-async failed for "
                f"transfer_id={transfer_id}: {e}"
            )
            raise

        if resp.status_code not in (200, 201):
            logger.warning(
                f"[Reactor:{self.name}] TEG reverse-async returned "
                f"{resp.status_code} for transfer_id={transfer_id}: "
                f"{resp.text[:200]}"
            )
            raise RuntimeError(
                f"TEG reverse-async non-2xx: {resp.status_code}"
            )

        # Mark the inbound row reversed.
        async with get_db_context() as db:
            await db.execute(
                update(models.CrossFrameTransferInbound)
                .where(
                    models.CrossFrameTransferInbound.id == transfer_id,
                    models.CrossFrameTransferInbound.status == "credited",
                )
                .values(
                    status="reversed",
                    reversed_at=datetime.datetime.now(datetime.timezone.utc),
                )
            )
            await db.commit()

        # §PlanB-②: emit an audit-only CrossFrameTransferReversed carrying the
        # reverse leg's transaction_id so getTegTransactionDetail resolves the
        # listed reverse leg. Δ-NEUTRAL: the ES projection (projections.py) has
        # NO balance branch for this event type, so it never moves supply.
        try:
            from ..event_emitter import get_event_emitter
            _emitter = get_event_emitter()
            if _emitter is not None:
                await _emitter.emit(
                    event_type="CrossFrameTransferReversed",
                    aggregate_id=row.receiver_did,
                    aggregate_type="Transfer",
                    data={
                        "transfer_id": transfer_id,
                        "transaction_id": _reverse_txid(transfer_id),
                        "from": row.receiver_did,
                        "to": event_data.get("sender_did", ""),
                        "amount": str(row.amount),
                        "memo": "cross_frame_async_reverse",
                    },
                    idempotency_key=f"reversed-tt-{transfer_id}",
                )
        except Exception as _emit_err:
            logger.warning(
                f"[Reactor:{self.name}] reverse audit-emit failed (non-fatal) "
                f"for transfer_id={transfer_id}: {_emit_err}"
            )

        logger.warning(
            f"[Reactor:{self.name}] REVERSED transfer_id={transfer_id} "
            f"receiver={row.receiver_did[-12:]} amount={row.amount} "
            f"(saga-driven compensating reverse — receiver had credited "
            f"but sender refunded)"
        )


# ----------------------------------------------------------------------- module API

_instance: Optional[CrossFrameRefundedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = CrossFrameRefundedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
