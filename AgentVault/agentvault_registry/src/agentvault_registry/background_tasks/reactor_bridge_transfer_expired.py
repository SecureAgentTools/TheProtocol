"""
Reactor: BridgeTransferExpired → originator notification
=========================================================
The `bridge_expiry` worker sweeps stale LOCKED bridge transactions every
60s. When it expires + unlocks a transfer, it emits `BridgeTransferExpired`
to the EventStore. This reactor fans the news out to the originator.

Side effects:
1. **Webhook fan-out** (`bridge.transfer_expired`).
2. **Email** (neural theme) — to the source agent's creator developer.
   Lets them know funds were unlocked back to the source agent.

Intraregistry consequences: none. The bridge expiry path already:
- Marked the row EXPIRED in `bridge_transactions`.
- Called `POST {TEG}/api/v1/bridge/unlock` to release the escrowed funds.
- Triggered TEG-side balance sync via the next `TokensTransferred`-flavored
  emission (BalanceSync reactor #1 picks it up).

This reactor is purely outbound notification. No further DB writes.
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


class BridgeTransferExpiredReactor(EventStoreReactor):
    event_type = "BridgeTransferExpired"
    leader_key = "reactor_bridge_transfer_expired"
    name = "BridgeTransferExpired"

    async def handle_event(self, event_data: dict) -> None:
        # §pass63 pattern: drop stale boot/WS replays so a process restart does not
        # re-email a months-old bridge expiry. See FINDING_2026-05-29_DISPUTE_EMAIL_ON_RESTART.md.
        stale, age_sec = is_notification_stale(event_data)
        if stale:
            logger.info(f"[Reactor:{self.name}] Skipping stale replay (age={int(age_sec or 0)}s)")
            return

        bridge_tx_id = event_data.get("bridge_tx_id") or "?"
        source_agent_did = event_data.get("source_agent_did") or "?"
        amount = event_data.get("amount", "?")
        source_frame = event_data.get("source_frame_id", "?")
        target_frame = event_data.get("target_frame_id", "?")

        logger.info(
            f"[Reactor:{self.name}] bridge_tx={bridge_tx_id} src={source_agent_did} "
            f"amount={amount} {source_frame}→{target_frame} — fanning out"
        )

        # Side effect 1: webhook fanout
        # §TWOAGENT #34 class (2026-09-23): to the owner of source_agent_did only. The broadcast form delivered this owner-private
        # event to every subscriber on the frame and, through the §TRUSTWIRE bridge, to the peer frame's; a DID with no
        # local owner (a foreign agent) now reaches nobody's webhook.
        if source_agent_did and source_agent_did != "?":
            await dispatch_webhook_for_agents(
                "bridge.transfer_expired", event_data, [source_agent_did], source_label=self.name,
            )

        # Side effect 2: email source agent's creator developer
        email = await get_developer_email_for_agent(source_agent_did)
        if not email:
            logger.warning(
                f"[Reactor:{self.name}] No creator developer email found for "
                f"source_agent={source_agent_did}"
            )
            return
        await send_reactor_email(
            subject=f"Bridge transfer expired — {amount} {frame_currency()} unlocked",
            recipients=[email],
            template="bridge_transfer_expired",
            context={
                "bridge_tx_id": bridge_tx_id,
                "source_agent_did": source_agent_did,
                "target_agent_did": event_data.get("target_agent_did", "—"),
                "source_frame_id": source_frame,
                "target_frame_id": target_frame,
                "amount": amount,
                "expires_at": event_data.get("expires_at", "—"),
                "expired_at": event_data.get("expired_at", "—"),
            },
            theme="neural",
            source_label=self.name,
        )


_instance: Optional[BridgeTransferExpiredReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = BridgeTransferExpiredReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
