"""Reactor: AttestationRevoked → webhook + sovereign-themed dev email.

Subscribes to `AttestationRevoked` events emitted by the revoke endpoints
(`POST /attestations/{id}/revoke` and `POST /admin/attestations/{id}/revoke`).
Side effects:
  1. Webhook fan-out (`attestation.revoked`) to subscribed developers.
  2. Sovereign-themed email to the attesting agent's owning developer.
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import (
    dispatch_webhook_for_agents,
    get_developer_email_for_agent,
    is_notification_stale,
    send_reactor_email,
)

logger = logging.getLogger(__name__)


class AttestationRevokedReactor(EventStoreReactor):
    event_type = "AttestationRevoked"
    leader_key = "reactor_attestation_revoked"
    name = "AttestationRevoked"

    async def handle_event(self, event_data: dict) -> None:
        # §pass63 pattern: drop stale boot/WS replays so a process restart does not
        # re-email a months-old revocation. See FINDING_2026-05-29_DISPUTE_EMAIL_ON_RESTART.md.
        stale, age_sec = is_notification_stale(event_data)
        if stale:
            logger.info(f"[Reactor:{self.name}] Skipping stale replay (age={int(age_sec or 0)}s)")
            return

        attestation_id = event_data.get("attestation_id") or "?"
        agent_did = event_data.get("agent_did") or "?"
        revoked_by = event_data.get("revoked_by") or "?"
        reason = event_data.get("revoked_reason") or "(no reason given)"

        logger.info(
            f"[Reactor:{self.name}] attestation={attestation_id} "
            f"agent={agent_did} revoked_by={revoked_by} — fanning out"
        )

        # Side effect 1: webhook fan-out
        # §TWOAGENT #34 class (2026-09-23): to the owner of agent_did only. The broadcast form delivered this owner-private
        # event to every subscriber on the frame and, through the §TRUSTWIRE bridge, to the peer frame's; a DID with no
        # local owner (a foreign agent) now reaches nobody's webhook.
        if agent_did and agent_did != "?":
            await dispatch_webhook_for_agents(
                "attestation.revoked", event_data, [agent_did], source_label=self.name,
            )

        # Side effect 2: email creator developer
        email = await get_developer_email_for_agent(agent_did)
        if not email:
            logger.warning(
                f"[Reactor:{self.name}] No creator developer email found for "
                f"agent={agent_did}"
            )
            return
        await send_reactor_email(
            subject=f"ZKP attestation revoked — {attestation_id[:8]}…",
            recipients=[email],
            template="attestation_revoked",
            context={
                "attestation_id": attestation_id,
                "agent_did": agent_did,
                "revoked_by": revoked_by,
                "revoked_reason": reason,
                "revoked_at": event_data.get("revoked_at", "—"),
            },
            theme="sovereign",
            source_label=self.name,
        )


_instance: Optional[AttestationRevokedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = AttestationRevokedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
