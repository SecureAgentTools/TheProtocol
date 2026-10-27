"""
Reactor: AgentReinstated → webhook + cross-TEG unblock
=======================================================
Mirror of reactor_agent_suspended for the reverse path. Inline coupling
(registry status active + IRONHAND re-enroll + TEG reinstate) happens in
admin_agents.bulk_reinstate before this event is emitted.

Two out-of-process side effects (matching the suspend reactor):
1. **Webhook propagation** — fires `agent.reinstated` to the agent's OWN developer (§TWOAGENT #34).
2. **Cross-TEG unblock** (Phase 7) — calls TEG `/cross-teg/admin/agents/{did}/unblock`.
"""
import logging
import os
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import (
    dispatch_webhook_for_agents,
    unblock_agent_on_remote_frames,
    unblock_agent_on_teg,
)

logger = logging.getLogger(__name__)


class AgentReinstatedReactor(EventStoreReactor):
    event_type = "AgentReinstated"
    leader_key = "reactor_agent_reinstated"
    name = "AgentReinstated"

    async def handle_event(self, event_data: dict) -> None:
        target_did = (
            event_data.get("agent_did")
            or event_data.get("target_agent_did")
            or "?"
        )
        logger.info(f"[Reactor:{self.name}] Propagating reinstate for agent={target_did}")

        # Side effect 1: webhook fan-out, to the agent's OWN developer only (§TWOAGENT #34, 2026-09-23): the broadcast
        # form handed every tenant's reinstatement (prior reason, actor id, the admin's email) to every subscriber on the
        # frame and, through the §TRUSTWIRE bridge, to the peer frame's (measured EU -> ASIA and ASIA -> EU).
        if target_did and target_did != "?":
            await dispatch_webhook_for_agents(
                "agent.reinstated", event_data, [target_did], source_label=self.name,
            )

        # Side effect 2: cross-TEG unblock on LOCAL TEG (Phase 7)
        if target_did and target_did != "?":
            result = await unblock_agent_on_teg(
                target_did,
                reason="AgentReinstated reactor",
                source_label=self.name,
            )
            if result is not None:
                logger.info(
                    f"[Reactor:{self.name}] TEG unblock-agent → "
                    f"status={result.get('status')} "
                    f"size={result.get('blocklist_size')}"
                )

        # Side effect 3: cross-FRAME unblock propagation (Phase 10 #4)
        if (
            target_did and target_did != "?"
            and os.getenv("REACTOR_CROSSFRAME_BLOCKLIST_ENABLED", "true").lower() == "true"
        ):
            summary = await unblock_agent_on_remote_frames(
                target_did,
                reason="AgentReinstated reactor cross-frame",
                source_label=self.name,
            )
            if summary["attempted"]:
                logger.info(
                    f"[Reactor:{self.name}] cross-frame unblock fanout: "
                    f"{summary['successful']}/{summary['attempted']} peers OK"
                )


_instance: Optional[AgentReinstatedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = AgentReinstatedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
