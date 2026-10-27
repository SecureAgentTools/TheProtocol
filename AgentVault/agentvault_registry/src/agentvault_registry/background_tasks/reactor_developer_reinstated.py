"""
Reactor: DeveloperReinstated → webhook dispatch (A3, 2026-07-24)
================================================================
The inline cascade (reinstate dev + coordinated-reinstate their cascade-suspended
agents) already happens in admin_developers.reinstate_developer BEFORE this event
is emitted — the asymmetry the wiring audit flagged was the NOTIFICATION side:
DeveloperSuspended had a webhook fan-out reactor, DeveloperReinstated had zero
consumers, so `developer.reinstated` / per-agent `agent.reinstated` webhooks
never fired even though both strings are subscribable.

This mirrors DeveloperSuspendedReactor exactly: dev-level event + per-cascaded-
agent granular fan-out from the payload's `cascade_results`.
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import dispatch_webhook_event, dispatch_webhook_for_agents, local_developer_id

logger = logging.getLogger(__name__)


class DeveloperReinstatedReactor(EventStoreReactor):
    event_type = "DeveloperReinstated"
    leader_key = "reactor_developer_reinstated"
    name = "DeveloperReinstated"

    async def handle_event(self, event_data: dict) -> None:
        target_dev_id = event_data.get("target_developer_id") or "?"
        target_email = event_data.get("target_email", "?")
        cascade = event_data.get("cascade_results") or []
        cascade_count = event_data.get("cascade_count", len(cascade))

        logger.info(
            f"[Reactor:{self.name}] Propagating dev reinstatement dev_id={target_dev_id} "
            f"email={target_email} cascade={cascade_count} agents"
        )

        # §TWOAGENT #34 (2026-09-23): to that developer's OWN webhooks on this registry (was every subscriber
        # on the frame, and through the §TRUSTWIRE bridge the peer frame's too, target_email included).
        _dev = local_developer_id(event_data)
        if _dev is not None:
            await dispatch_webhook_event(
                event_type="developer.reinstated",
                event_data=event_data,
                source_label=self.name,
                developer_id=_dev,
            )

        for entry in cascade[:50]:
            if not isinstance(entry, dict):
                continue
            did = entry.get("agent_did")
            if not did:
                continue
            await dispatch_webhook_for_agents(
                "agent.reinstated",
                {
                    "target_agent_did": did,
                    "agent_did": did,
                    "cascade_source": "developer.reinstated",
                    "developer_id": target_dev_id,
                    "lever_status": entry,
                },
                [did],
                source_label=f"{self.name}/cascade",
            )


_instance: Optional[DeveloperReinstatedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = DeveloperReinstatedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
