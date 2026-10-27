"""
Reactor: DisputeFiled → enforcement-admin toast
================================================
When a dispute is filed (via `routers/disputes.py:207` or
`routers/contracts.py:1235`), `DisputeFiled` is emitted into the
EventStore. Without this reactor, the event sits as audit-only — operators
have to refresh the Disputes view to see it.

This reactor adds a single side effect:
- **Live WS toast** (audience='admin_enforcement') so connected
  enforcement admins see new disputes as they're filed. No throttle —
  dispute filings are rare and high-value for triage.

Webhook fan-out for `dispute.filed` is NOT wired here yet (no developer
webhook subscription exists today; the AdminWebhooks watchtower already
shows dispute events via the EventStore feed). Add `dispatch_webhook_event`
here if/when developers want push delivery.

Idempotency: EventStore deduplicates by `(event_type, idempotency_key)`,
so a re-emitted event reaches `handle_event` at most once. Leader-elected
so only one worker per cluster fires the toast.
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor

logger = logging.getLogger(__name__)


def _frame_unit() -> str:
    # D6-835 (2026-10-25): this frame's unit, asked where the amount is written (it said AVT on every frame)
    from agentvault_registry.core.frame_currency import frame_currency
    return frame_currency()


class DisputeFiledReactor(EventStoreReactor):
    event_type = "DisputeFiled"
    leader_key = "reactor_dispute_filed"
    name = "DisputeFiled"

    async def handle_event(self, event_data: dict) -> None:
        dispute_id = event_data.get("dispute_id") or event_data.get("id") or "?"
        complainant_did = event_data.get("complainant_did") or "?"
        defendant_did = event_data.get("defendant_did") or "?"
        amount_disputed = event_data.get("amount_disputed", "—")

        logger.info(
            f"[Reactor:{self.name}] dispute={dispute_id} complainant={complainant_did} "
            f"defendant={defendant_did} amount={amount_disputed}"
        )

        try:
            from agentvault_registry.routers.websocket import broadcast_notification
            short_def = defendant_did if len(defendant_did) <= 28 else defendant_did[:14] + "…" + defendant_did[-10:]
            short_comp = complainant_did if len(complainant_did) <= 28 else complainant_did[:14] + "…" + complainant_did[-10:]
            await broadcast_notification(
                title=f"Dispute #{dispute_id} filed",
                message=f"{short_comp} → {short_def}{(' · ' + str(amount_disputed) + ' ' + _frame_unit()) if amount_disputed and amount_disputed != '—' else ''}",
                notification_type="warning",
                audience="admin_enforcement",
            )
        except Exception as e:
            logger.warning(
                f"[Reactor:{self.name}] broadcast_notification failed (non-fatal): {e}"
            )


_instance: Optional[DisputeFiledReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = DisputeFiledReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
