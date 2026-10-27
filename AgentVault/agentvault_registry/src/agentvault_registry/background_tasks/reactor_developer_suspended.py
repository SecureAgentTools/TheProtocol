"""
Reactor: DeveloperSuspended → webhook dispatch
==============================================
Inline cascade (suspend dev + suspend N owned agents per coordinated
suspension) happens in admin_developers.suspend_developer before this event
is emitted. The reactor fires the developer-level webhook event AND, for
integrators who didn't subscribe to the developer-level event, fires a
per-agent `agent.suspended` webhook for each cascaded agent so they get
the granular signal.

The cascade results are embedded in the event payload (`cascade_results`)
by the suspend handler — this reactor reads them and fans out.
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import dispatch_webhook_event, dispatch_webhook_for_agents, local_developer_id

logger = logging.getLogger(__name__)


class DeveloperSuspendedReactor(EventStoreReactor):
    event_type = "DeveloperSuspended"
    leader_key = "reactor_developer_suspended"
    name = "DeveloperSuspended"

    async def handle_event(self, event_data: dict) -> None:
        target_dev_id = event_data.get("target_developer_id") or "?"
        target_email = event_data.get("target_email", "?")
        cascade = event_data.get("cascade_results") or []
        cascade_count = event_data.get("cascade_count", len(cascade))

        logger.info(
            f"[Reactor:{self.name}] Propagating dev suspension dev_id={target_dev_id} "
            f"email={target_email} cascade={cascade_count} agents"
        )

        # 1. Fire developer.suspended webhook for integrators subscribed at dev-level
        # §TWOAGENT #34 (2026-09-23): to that developer's OWN webhooks on this registry (was every subscriber
        # on the frame, and through the §TRUSTWIRE bridge the peer frame's too, target_email included).
        _dev = local_developer_id(event_data)
        if _dev is not None:
            await dispatch_webhook_event(
                event_type="developer.suspended",
                event_data=event_data,
                source_label=self.name,
                developer_id=_dev,
            )

        # 2. For each cascaded agent, fire agent.suspended webhook (granular fan-out
        #    — integrators subscribed at agent-level still see each).
        for entry in cascade[:50]:  # cap to match emission cap
            if not isinstance(entry, dict):
                continue
            did = entry.get("agent_did")
            if not did:
                continue
            await dispatch_webhook_for_agents(
                "agent.suspended",
                {
                    "target_agent_did": did,
                    "agent_did": did,
                    "reason": event_data.get("reason", "developer suspended"),
                    "cascade_source": "developer.suspended",
                    "developer_id": target_dev_id,
                    "lever_status": entry,
                },
                [did],
                source_label=f"{self.name}/cascade",
            )


_instance: Optional[DeveloperSuspendedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = DeveloperSuspendedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
