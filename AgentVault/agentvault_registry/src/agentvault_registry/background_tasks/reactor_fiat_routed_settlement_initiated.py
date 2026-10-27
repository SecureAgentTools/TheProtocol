"""
Reactor: FiatRoutedSettlementInitiated → operator-side settle (event-sourced fallback)
======================================================================================
PB-2 (2026-05-10) — event-sourced fallback path for routed-fiat settlement.

When the mainframe's HTTP push callback fails (cert config drift, transient
nginx hiccup, operator down at moment-of-callback, etc.), the event-sourced
fallback ensures eventual consistency. The mainframe emits this event AFTER
the cross-TEG fund step succeeds (operator's treasury is already credited).
This reactor picks up the event and runs the SAME settle logic as the HTTP
handler, but is gated by `event.data.operator_did == FEDERATION_OPERATOR_DID`
so only the targeted operator acts.

Idempotent: the underlying `_operator_settle_routed_purchase` helper checks
`fp.status == COMPLETED` and returns a noop if either the HTTP handler or
a prior reactor invocation already settled. Both paths converge to the same
end state.

Pattern: mirrors `reactor_cross_frame_initiated.py` — same shape, same
idempotency model, same leader-elected Redis lock, same WS subscription.

Operator-only: gated on `not _is_fiat_genesis()`. Mainframe-side reactor
(reactor_fiat_routed_settlement_completed) closes the loop when the operator
emits FiatRoutedSettlementCompleted.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from .reactor_base import EventStoreReactor

logger = logging.getLogger(__name__)


def _operator_self_did() -> str:
    """Return this operator's federation DID. Empty on mainframe / unconfigured."""
    return (os.getenv("FEDERATION_OPERATOR_DID") or "").strip()


def _is_fiat_genesis() -> bool:
    return os.getenv("FIAT_GENESIS_REGISTRY", "false").lower() in ("true", "1", "yes")


class FiatRoutedSettlementInitiatedReactor(EventStoreReactor):
    event_type = "FiatRoutedSettlementInitiated"
    leader_key = "reactor_fiat_routed_settlement_initiated"
    name = "FiatRoutedSettlementInitiated"

    async def handle_event(self, event_data: dict) -> None:
        # Mainframe registry runs this reactor too (subscribed to its own ES),
        # but the gate below ensures it doesn't act on its own emissions —
        # only operators with matching DID settle.
        if _is_fiat_genesis():
            return  # mainframe noop — the operator handles it

        operator_did_in_event = (event_data.get("operator_did") or "").strip()
        my_did = _operator_self_did()
        if not my_did or operator_did_in_event != my_did:
            # Event for a different operator — silently ignore.
            return

        mf_purchase_id = event_data.get("mainframe_fiat_purchase_id")
        if not mf_purchase_id:
            logger.warning(
                f"[Reactor:{self.name}] event missing mainframe_fiat_purchase_id — skipping"
            )
            return

        logger.info(
            f"[Reactor:{self.name}] settling mainframe_fiat_purchase_id={mf_purchase_id} "
            f"operator_did={my_did}"
        )

        # Locate the local FiatPurchase row by mainframe ID, then delegate
        # to the shared helper. Idempotent — if HTTP path already settled,
        # helper returns noop.
        from sqlalchemy import select
        from ..database import get_db_context
        from ..models import FiatPurchase, FiatPurchaseStatus
        from ..routers.fiat_onramp import _operator_settle_routed_purchase

        async with get_db_context() as db:
            row = await db.execute(
                select(FiatPurchase).where(
                    FiatPurchase.mainframe_fiat_purchase_id == mf_purchase_id
                )
            )
            fp = row.scalar_one_or_none()
            if not fp:
                # Local row not yet created (event arrived before operator's
                # checkout-session row was inserted — rare race). The
                # operator-side reconciler will catch this on next pass.
                logger.warning(
                    f"[Reactor:{self.name}] no local FiatPurchase for "
                    f"mainframe_id={mf_purchase_id} — local reconciler will handle"
                )
                return

            try:
                result = await _operator_settle_routed_purchase(
                    db=db,
                    fp=fp,
                    body=event_data,
                    source="event_reactor",
                )
                if result.get("noop"):
                    logger.info(
                        f"[Reactor:{self.name}] mainframe_id={mf_purchase_id} already settled "
                        f"by HTTP path — noop"
                    )
                else:
                    logger.info(
                        f"[Reactor:{self.name}] mainframe_id={mf_purchase_id} settled via "
                        f"event-sourced fallback (HTTP push must have failed)"
                    )
            except Exception as exc:
                # The helper raises HTTPException on hard failures. Log and
                # let the operator-side local reconciler retry on its cadence.
                logger.exception(
                    f"[Reactor:{self.name}] settle failed for mainframe_id={mf_purchase_id}: {exc}"
                )


_instance: Optional[FiatRoutedSettlementInitiatedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = FiatRoutedSettlementInitiatedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
