"""
Reactor: DisputeSlash → owning developer notification
======================================================
When a dispute resolution slashes an agent (via federation_disputes.py),
the slash is recorded on TEG and the corresponding `DisputeSlash` event is
emitted. This reactor turns that into operator-facing notification.

Side effects:
1. **Webhook fan-out** (`agent.slashed`) — for developers subscribed.
2. **Email** (sovereign theme) — to the agent's creator developer.
3. (informational) critical log line for ops/SRE log scrapers.

Intraregistry consequences: none. The slash already updated:
- TEG `agent_teg_profiles.token_balance` (deducted)
- registry `agents.liquid_balance` (synced via BalanceSync reactor #1
  on the resulting balance state)

This reactor is leader-elected; runs idempotently because the email
template is keyed off `slash_tx_id` in the subject and EventStore
deduplicates by `idempotency_key`.
"""
import logging
from typing import Optional

from ..core.frame_currency import frame_currency
from .reactor_base import EventStoreReactor
from .reactor_helpers import (
    dispatch_webhook_for_agents,
    get_developer_email_for_agent,
    is_notification_stale,
    send_reactor_email,
)

logger = logging.getLogger(__name__)


class AgentSlashedReactor(EventStoreReactor):
    event_type = "DisputeSlash"
    leader_key = "reactor_agent_slashed"
    name = "AgentSlashed"

    async def handle_event(self, event_data: dict) -> None:
        # §pass63 pattern: drop stale boot/WS replays so a process restart does not
        # re-email a months-old slash (EventStore replays recent events of this type
        # on WS connect; the in-memory dedup ring is empty after a restart). See
        # FINDING_2026-05-29_DISPUTE_EMAIL_ON_RESTART.md.
        stale, age_sec = is_notification_stale(event_data)
        if stale:
            logger.info(f"[Reactor:{self.name}] Skipping stale replay (age={int(age_sec or 0)}s)")
            return

        defendant_did = event_data.get("defendant_did") or "?"
        amount = event_data.get("amount", "?")
        dispute_id = event_data.get("dispute_id") or "?"
        slash_tx_id = event_data.get("slash_tx_id") or "?"

        logger.warning(
            f"[Reactor:{self.name}] agent={defendant_did} amount={amount} "
            f"dispute={dispute_id} tx={slash_tx_id} — fanning out"
        )

        # Side effect 1: webhook fanout
        # §TWOAGENT #34 class (2026-09-23): to the owner of defendant_did only. The broadcast form delivered this owner-private
        # event to every subscriber on the frame and, through the §TRUSTWIRE bridge, to the peer frame's; a DID with no
        # local owner (a foreign agent) now reaches nobody's webhook.
        if defendant_did and defendant_did != "?":
            await dispatch_webhook_for_agents(
                "agent.slashed", event_data, [defendant_did], source_label=self.name,
            )

        # Side effect 2: live WS toast for enforcement admins (#5, 2026-05-08).
        # No throttle — slashes are rare (one per dispute resolution) and the
        # signal is high-value for admins watching enforcement state.
        try:
            from agentvault_registry.routers.websocket import broadcast_notification
            short_did = defendant_did if len(defendant_did) <= 28 else defendant_did[:14] + "…" + defendant_did[-10:]
            await broadcast_notification(
                title=f"Agent slashed — {amount} {frame_currency()}",   # D6-835: the email subject below already said so
                message=f"{short_did} · dispute {dispute_id}",
                notification_type="warning",
                audience="admin_enforcement",
            )
        except Exception as e:
            logger.warning(
                f"[Reactor:{self.name}] broadcast_notification failed (non-fatal): {e}"
            )

        # Side effect 3: email creator developer
        email = await get_developer_email_for_agent(defendant_did)
        if not email:
            logger.warning(
                f"[Reactor:{self.name}] No creator developer email found for "
                f"agent={defendant_did}"
            )
            return
        await send_reactor_email(
            subject=f"Agent slashed — {amount} {frame_currency()} (dispute {dispute_id})",
            recipients=[email],
            template="agent_slashed",
            context={
                "defendant_did": defendant_did,
                "amount": amount,
                "dispute_id": dispute_id,
                "slash_tx_id": slash_tx_id,
                "origin_registry_url": event_data.get("origin_registry_url", "—"),
            },
            theme="sovereign",
            source_label=self.name,
        )


_instance: Optional[AgentSlashedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = AgentSlashedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
