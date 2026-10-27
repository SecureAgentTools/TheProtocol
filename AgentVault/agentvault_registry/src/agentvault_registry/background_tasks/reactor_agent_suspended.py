"""
Reactor: AgentSuspended → webhook + cross-TEG blocklist + admin toast
======================================================================
The synchronous coupling (registry status + IRONHAND mTLS revoke + local
TEG suspend) happens INLINE in the bulk/suspend handler before this event
is emitted. This reactor does THREE out-of-process side effects:

1. **Webhook propagation** — fires the `agent.suspended` webhooks of the
   agent's OWN developer (never every subscriber on the frame; §TWOAGENT #34).
2. **Cross-TEG blocklist** (Phase 7, 2026-04-27) — calls the local TEG's
   `/cross-teg/admin/agents/{did}/block` endpoint to add the DID to the
   external blocklist. This blocklist gates incoming cross-TEG transfers
   targeting the suspended DID at the protocol-edge.
3. **Live WS toast** (#5, 2026-05-08) — broadcast_notification with
   `audience='admin_enforcement'` so connected enforcement admins see a
   suspension as it happens. 30s throttle to suppress bulk-suspend storms.

The reactor does NOT repeat the IRONHAND/local-TEG-suspend calls. Those are
already done by the inline path. The cross-TEG block is genuinely additive:
the inline path only suspends the agent on its OWN TEG, not on partner TEGs
that might receive cross-frame transfers FOR this agent.

Phase 8 follow-up: wire the blocklist check into the cross-TEG transfer
path itself (`endpoints_token.py`, `cross_teg_router.py:/accept`). Today the
endpoints + reactor exist as scaffolding + audit; the actual refusal at
transfer-time is staged for next phase.
"""
import logging
import os
import time
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import (
    block_agent_on_remote_frames,
    block_agent_on_teg,
    dispatch_webhook_for_agents,
)

logger = logging.getLogger(__name__)

# #5 (2026-05-08): throttle the live WS toast (NOT the webhook dispatch
# or the cross-TEG block) so a bulk-suspend run on N agents doesn't fan
# out N toasts to every connected enforcement admin. Per-process state —
# the reactor is leader-elected so this is the single source of truth.
_NOTIF_THROTTLE_SECONDS = 30
_last_notif_at: float = 0.0


class AgentSuspendedReactor(EventStoreReactor):
    event_type = "AgentSuspended"
    leader_key = "reactor_agent_suspended"
    name = "AgentSuspended"

    async def handle_event(self, event_data: dict) -> None:
        target_did = (
            event_data.get("target_agent_did")
            or event_data.get("agent_did")
            or "?"
        )
        reason = event_data.get("reason", "")
        logger.info(
            f"[Reactor:{self.name}] Propagating suspension for agent={target_did} "
            f"(reason={reason[:60]})"
        )

        # Side effect 1: webhook fan-out, to the agent's OWN developer only (§TWOAGENT #34, 2026-09-23). The broadcast
        # form delivered every tenant's suspension (reason, actor id, the admin's email) to every agent.suspended
        # subscriber on the frame, and the §TRUSTWIRE bridge feeds a peer's AgentSuspended into this reactor, so it
        # crossed frames as well: measured both ways between EU and ASIA. A foreign agent has no owner here, so a
        # bridged event reaches nobody's webhook; the blocklist side effects below still run for it.
        if target_did and target_did != "?":
            await dispatch_webhook_for_agents(
                "agent.suspended", event_data, [target_did], source_label=self.name,
            )

        # Side effect 2: cross-TEG blocklist on LOCAL TEG (Phase 7)
        if target_did and target_did != "?":
            result = await block_agent_on_teg(
                target_did,
                reason=reason or "AgentSuspended reactor",
                source_label=self.name,
            )
            if result is not None:
                logger.info(
                    f"[Reactor:{self.name}] TEG block-agent → "
                    f"status={result.get('status')} "
                    f"size={result.get('blocklist_size')}"
                )

        # Side effect 3: cross-FRAME blocklist propagation (Phase 10 #4)
        # In separate-EventStore topologies (e.g., production Frame B), peer
        # reactors don't see this event, so we must call each peer's
        # federation blocklist proxy directly. In shared-EventStore topologies
        # (sandbox), peer reactors handle their own block independently and
        # this fanout is redundant-but-safe (TEG endpoint is idempotent).
        # Env-gated so the legacy single-frame behavior is opt-in for now.
        if (
            target_did and target_did != "?"
            and os.getenv("REACTOR_CROSSFRAME_BLOCKLIST_ENABLED", "true").lower() == "true"
        ):
            summary = await block_agent_on_remote_frames(
                target_did,
                reason=reason or "AgentSuspended reactor cross-frame",
                source_label=self.name,
            )
            if summary["attempted"]:
                logger.info(
                    f"[Reactor:{self.name}] cross-frame block fanout: "
                    f"{summary['successful']}/{summary['attempted']} peers OK"
                )

        # Side effect 4: live WS toast for connected enforcement admins
        # (#5, 2026-05-08). 30s throttle suppresses bulk-suspend storms;
        # webhook fanout above always fires (per-event audit trail).
        global _last_notif_at
        now = time.monotonic()
        if (now - _last_notif_at) >= _NOTIF_THROTTLE_SECONDS:
            try:
                from agentvault_registry.routers.websocket import broadcast_notification
                short_did = target_did if len(target_did) <= 28 else target_did[:14] + "…" + target_did[-10:]
                await broadcast_notification(
                    title="Agent suspended",
                    message=f"{short_did}{(' — ' + reason[:80]) if reason else ''}",
                    notification_type="warning",
                    audience="admin_enforcement",
                )
                _last_notif_at = now
            except Exception as e:
                logger.warning(
                    f"[Reactor:{self.name}] broadcast_notification failed (non-fatal): {e}"
                )


_instance: Optional[AgentSuspendedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = AgentSuspendedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
