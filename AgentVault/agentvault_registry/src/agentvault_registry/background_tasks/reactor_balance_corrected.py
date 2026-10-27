"""
Reactor: BalanceCorrected → security audit alert
=================================================
Admin-initiated balance corrections (TEG admin treasury actions) emit
`BalanceCorrected` to the EventStore. Per the supply invariant:
- Positive deltas count toward `tokens_issued` (treated as mint-equivalent).
- Negative deltas record the correction WITHOUT decrementing `tokens_issued`
  (the issued total is monotonic — corrections account for accounting drift,
  not destruction).

Side effects:
1. **Critical log line** — admin balance changes must be visible to ops
   regardless of webhook/email path.
2. **Webhook fan-out** (`treasury.balance_corrected`) — for integrators
   who track admin treasury actions.
3. **Email** (sovereign theme) — sent to `SUPPLY_ALERT_RECIPIENTS` if
   configured, mirroring the supply-breach alert distribution path. Admin
   balance changes are correctness-critical.

Intraregistry consequences:
- BalanceSync reactor #1 will pick up the resulting balance state on the
  next `TokensTransferred`-flavored event in the same flow (the correction
  itself or a follow-up). No additional sync needed here.
- SupplyInvariantBreachReactor (#6) may also fire if the correction was
  large enough to trip the invariant. The two reactors are independent
  and complementary.

Today's emitter: NONE. This reactor is defensive scaffolding — it ships
ahead of the admin treasury correction endpoint that will emit this event.
When the endpoint lands, the reactor consumes from day one.
"""
import logging
from typing import List, Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import (
    dispatch_webhook_for_agents,
    is_notification_stale,
    send_reactor_email,
)

logger = logging.getLogger(__name__)


class BalanceCorrectedReactor(EventStoreReactor):
    event_type = "BalanceCorrected"
    leader_key = "reactor_balance_corrected"
    name = "BalanceCorrected"

    async def handle_event(self, event_data: dict) -> None:
        agent_did = event_data.get("agent_did") or event_data.get("aggregate_id") or "?"
        delta = event_data.get("delta", "?")
        new_balance = event_data.get("new_balance", "?")
        reason = event_data.get("reason", "—")
        actor = event_data.get("actor") or event_data.get("admin_email", "—")
        recorded_at = event_data.get("recorded_at") or event_data.get("timestamp", "—")

        # §pass63 follow-up (2026-05-22) — silence stale replays at boot.
        # Same rationale as SupplyInvariantBreachReactor: ES replays last 15
        # events on subscribe + polling-backstop initial lookback picks up
        # historical events. Without this guard, every container restart
        # re-fires CRITICAL log + webhook + ops email for old corrections.
        stale, age_sec = is_notification_stale(event_data)
        if stale:
            logger.info(
                f"[Reactor:{self.name}] Skipping stale replay (age={int(age_sec or 0)}s, "
                f"agent={agent_did[:24]}…, delta={delta}, recorded_at={recorded_at}) — "
                f"boot/backstop noise, not a current correction"
            )
            return

        # CRITICAL log — visible to ops scrapers regardless of webhook/email
        logger.critical(
            f"[BALANCE-CORRECTED] agent={agent_did} delta={delta} "
            f"new_balance={new_balance} reason={reason!r} actor={actor!r} at={recorded_at}"
        )

        # Side effect 1: webhook fanout
        # §TWOAGENT #34 class (2026-09-23): to the owner of agent_did only. The broadcast form delivered this owner-private
        # event to every subscriber on the frame and, through the §TRUSTWIRE bridge, to the peer frame's; a DID with no
        # local owner (a foreign agent) now reaches nobody's webhook.
        if agent_did and agent_did != "?":
            await dispatch_webhook_for_agents(
                "treasury.balance_corrected", event_data, [agent_did], source_label=self.name,
            )

        # Side effect 2: email security alert recipients (reuse the same
        # CSV env var used by the supply auditor — admin balance changes
        # are the same audience).
        try:
            from agentvault_registry.config import settings
            recipients_csv = getattr(settings, "SUPPLY_ALERT_RECIPIENTS", None) or ""
            recipients: List[str] = [
                r.strip() for r in recipients_csv.split(",") if r.strip()
            ]
        except Exception:
            recipients = []
        if not recipients:
            return

        await send_reactor_email(
            subject=f"⚠ Treasury balance correction — agent={agent_did[:24]}…",
            recipients=recipients,
            template="treasury_balance_corrected",
            context={
                "agent_did": agent_did,
                "delta": delta,
                "new_balance": new_balance,
                "reason": reason,
                "actor": actor,
                "recorded_at": recorded_at,
            },
            theme="sovereign",
            source_label=self.name,
        )


_instance: Optional[BalanceCorrectedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = BalanceCorrectedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
