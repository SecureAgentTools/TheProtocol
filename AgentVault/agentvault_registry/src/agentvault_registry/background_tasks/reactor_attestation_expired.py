"""Reactor: AttestationExpired → webhook (lightweight, no email).

Subscribes to `AttestationExpired` events emitted by the daily
`attestation_expiry` background sweeper. Lightweight: webhook only —
expiry is a normal lifecycle event, not a security incident, so no
email is dispatched.
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import (
    dispatch_webhook_for_agents,
)

logger = logging.getLogger(__name__)


class AttestationExpiredReactor(EventStoreReactor):
    event_type = "AttestationExpired"
    leader_key = "reactor_attestation_expired"
    name = "AttestationExpired"

    async def handle_event(self, event_data: dict) -> None:
        attestation_id = event_data.get("attestation_id") or "?"
        agent_did = event_data.get("agent_did") or "?"
        circuit_id = event_data.get("circuit_id") or "?"

        logger.info(
            f"[Reactor:{self.name}] attestation={attestation_id} "
            f"agent={agent_did} circuit={circuit_id} — webhook fan-out"
        )

        # §TWOAGENT #34 class (2026-09-23): to the owner of agent_did only. The broadcast form delivered this owner-private
        # event to every subscriber on the frame and, through the §TRUSTWIRE bridge, to the peer frame's; a DID with no
        # local owner (a foreign agent) now reaches nobody's webhook.
        if agent_did and agent_did != "?":
            await dispatch_webhook_for_agents(
                "attestation.expired", event_data, [agent_did], source_label=self.name,
            )


_instance: Optional[AttestationExpiredReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = AttestationExpiredReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
