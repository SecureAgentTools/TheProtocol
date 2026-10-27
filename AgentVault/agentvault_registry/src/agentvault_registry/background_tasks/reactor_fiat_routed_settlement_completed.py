"""
Reactor: FiatRoutedSettlementCompleted → mainframe-side loop closure
====================================================================
PB-2 (2026-05-10) — closes the event-sourced fallback loop on mainframe.

When the operator settles a routed purchase (whether via HTTP callback OR
via the event-sourced fallback reactor), the operator emits
`FiatRoutedSettlementCompleted` to confirm completion. This reactor, running
on the mainframe, marks the mainframe-side FiatPurchase row as COMPLETED if
the HTTP push didn't already do so.

Idempotent: skips if mainframe row already COMPLETED. The event arrives
regardless of which path settled the operator — the mainframe needs the
notification only when the HTTP push failed (otherwise it set COMPLETED
synchronously after receiving 200 OK from the HTTP push).

Mainframe-only: gated on `_is_fiat_genesis()`. Operator reactors don't run
this — they're the source, not the sink.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from .reactor_base import EventStoreReactor

logger = logging.getLogger(__name__)


def _is_fiat_genesis() -> bool:
    return os.getenv("FIAT_GENESIS_REGISTRY", "false").lower() in ("true", "1", "yes")


class FiatRoutedSettlementCompletedReactor(EventStoreReactor):
    event_type = "FiatRoutedSettlementCompleted"
    leader_key = "reactor_fiat_routed_settlement_completed"
    name = "FiatRoutedSettlementCompleted"

    async def handle_event(self, event_data: dict) -> None:
        # Operator registries also subscribe to this event type but have no
        # work to do — they emitted it. Only mainframe closes the loop.
        if not _is_fiat_genesis():
            return

        mf_purchase_id = event_data.get("mainframe_fiat_purchase_id")
        if not mf_purchase_id:
            logger.warning(
                f"[Reactor:{self.name}] event missing mainframe_fiat_purchase_id — skipping"
            )
            return

        operator_did = event_data.get("operator_did") or "?"
        operator_fp_id = event_data.get("operator_fiat_purchase_id") or "?"
        agent_did = event_data.get("agent_did") or "?"
        tx_id = event_data.get("tx_id") or ""
        settle_source = event_data.get("settle_source") or "?"

        logger.info(
            f"[Reactor:{self.name}] closing loop for mainframe_id={mf_purchase_id} "
            f"operator={operator_did} settle_source={settle_source}"
        )

        # Update mainframe row: status=COMPLETED, operator_callback_status (if not already set).
        from sqlalchemy import select
        from ..database import get_db_context
        from ..models import FiatPurchase, FiatPurchaseStatus

        async with get_db_context() as db:
            fp = await db.get(FiatPurchase, mf_purchase_id)
            if not fp:
                logger.warning(
                    f"[Reactor:{self.name}] mainframe FiatPurchase {mf_purchase_id} not found — skipping"
                )
                return

            if fp.status == FiatPurchaseStatus.COMPLETED.value:
                # HTTP push already closed the loop synchronously.
                logger.info(
                    f"[Reactor:{self.name}] mainframe_id={mf_purchase_id} already COMPLETED "
                    f"(HTTP path closed first) — noop"
                )
                return

            fp.status = FiatPurchaseStatus.COMPLETED.value
            fp.completed_at = datetime.now(timezone.utc)
            # Distinguish event-sourced loop closure from HTTP success in the
            # callback_status field for audit clarity.
            if settle_source == "event_reactor":
                fp.operator_callback_status = "success_via_event"
            else:
                # Operator settled via HTTP push but our HTTP-side ack timed
                # out / didn't reach us — the event arrived first. Mark
                # success but record the alternate-arrival path.
                fp.operator_callback_status = "success_via_event_late_http"
            fp.operator_callback_last_error = None
            await db.commit()

            logger.info(
                f"[Reactor:{self.name}] mainframe_id={mf_purchase_id} CLOSED via event "
                f"(was {('PROCESSING' if fp.status == FiatPurchaseStatus.COMPLETED.value else 'unknown')}; "
                f"operator_fp={operator_fp_id} agent={agent_did} tx={tx_id[:16]})"
            )


_instance: Optional[FiatRoutedSettlementCompletedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = FiatRoutedSettlementCompletedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
