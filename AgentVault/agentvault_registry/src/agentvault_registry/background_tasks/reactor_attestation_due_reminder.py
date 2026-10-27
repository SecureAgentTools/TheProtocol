"""Reactor: AttestationDueReminder → webhook (lightweight, no email).

Subscribes to `AttestationDueReminder` events emitted by the hourly
`attestation_schedule_cron` worker. Side effect: webhook only — overdue
attestations are a routine notification, not an incident, so no email
is dispatched.
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import (
    dispatch_webhook_for_agents,
)

logger = logging.getLogger(__name__)


class AttestationDueReminderReactor(EventStoreReactor):
    event_type = "AttestationDueReminder"
    leader_key = "reactor_attestation_due_reminder"
    name = "AttestationDueReminder"

    async def handle_event(self, event_data: dict) -> None:
        schedule_id = event_data.get("schedule_id") or "?"
        agent_did = event_data.get("agent_did") or "?"
        circuit_id = event_data.get("circuit_id") or "?"

        logger.info(
            f"[Reactor:{self.name}] schedule={schedule_id} "
            f"agent={agent_did} circuit={circuit_id} — webhook fan-out"
        )

        # §TWOAGENT #34 class (2026-09-23): to the owner of agent_did only. The broadcast form delivered this owner-private
        # event to every subscriber on the frame and, through the §TRUSTWIRE bridge, to the peer frame's; a DID with no
        # local owner (a foreign agent) now reaches nobody's webhook.
        if agent_did and agent_did != "?":
            await dispatch_webhook_for_agents(
                "attestation.due_reminder", event_data, [agent_did], source_label=self.name,
            )


_instance: Optional[AttestationDueReminderReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = AttestationDueReminderReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
