"""
Reactor: FundingRequestCreated → treasury-admin toast
======================================================
When an agent submits a funding request via `POST /api/v1/funding/request`
(routers/funding_requests.py), the handler emits `FundingRequestCreated`
into the EventStore. Without this reactor, treasury admins have to poll
`GET /admin/funding/requests?status=pending` to see new requests.

This reactor adds a single side effect:
- **Live WS toast** (audience='admin_treasury') so connected treasury
  admins see new funding requests as they land. No throttle — requests
  are rate-limited at the source (max 3 pending per agent), so a storm
  is structurally bounded.

Webhook fan-out for `funding.request_created` is intentionally NOT wired
here (no operator-side use case yet; the AdminDevelopers + Senate Funding
tab views already consume the data via REST polling).

Idempotency: EventStore deduplicates by `(event_type, idempotency_key)`.
Leader-elected so only one worker per cluster fires the toast.
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor

logger = logging.getLogger(__name__)


def _frame_unit() -> str:
    # D6-835 (2026-10-25): this frame's unit, asked where the amount is written (it said AVT on every frame)
    from agentvault_registry.core.frame_currency import frame_currency
    return frame_currency()


class FundingRequestCreatedReactor(EventStoreReactor):
    event_type = "FundingRequestCreated"
    leader_key = "reactor_funding_request_created"
    name = "FundingRequestCreated"

    async def handle_event(self, event_data: dict) -> None:
        request_id = event_data.get("request_id") or "?"
        requester_did = event_data.get("requester_did") or "?"
        amount = event_data.get("requested_amount") or event_data.get("amount") or "?"
        reason = event_data.get("reason") or ""

        logger.info(
            f"[Reactor:{self.name}] request={request_id} requester={requester_did} "
            f"amount={amount}"
        )

        try:
            from agentvault_registry.routers.websocket import broadcast_notification
            short_did = requester_did if len(requester_did) <= 28 else requester_did[:14] + "…" + requester_did[-10:]
            reason_clip = (reason[:60] + "…") if reason and len(reason) > 60 else (reason or "")
            msg_tail = f" — {reason_clip}" if reason_clip else ""
            await broadcast_notification(
                title=f"Funding request #{request_id} — {amount} {_frame_unit()}",   # D6-835: not AVT on every frame
                message=f"{short_did}{msg_tail}",
                notification_type="info",
                audience="admin_treasury",
            )
        except Exception as e:
            logger.warning(
                f"[Reactor:{self.name}] broadcast_notification failed (non-fatal): {e}"
            )


_instance: Optional[FundingRequestCreatedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = FundingRequestCreatedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
