"""
Reactor: FrameFederationRevoked → audit propagation
====================================================
When a sovereign frame's federation is revoked (a frame-level peer is
deactivated, distinct from operator hub-and-spoke peers), the synchronous
revoke handler in `frame_invitations.py:823` already does the load-bearing
local work:
- SPIRE bundle removal
- DB peer status flip (PeerRegistry.status = INACTIVE)
- SF-4 cross-frame peer teardown
- SF-5 federation operator teardown
- Email notification to admin contact

The reactor's job is *propagation*: fan out a `frame_federation.revoked`
webhook so external integrators (compliance dashboards, audit log mirrors,
notification services) can react without polling the registry. Same shape as
the Phase 6 AgentSuspended/AgentReinstated reactors — webhook only, no
inline work repeated.

The PeerRegistryDeactivated reactor (Phase 1) fires for the co-emitted
PeerRegistryDeactivated event. Since 2026-10-21 a federated frame is a TEG
partner (reactor_frame_federation_established registers it at the handshake),
so that event names the partner the revoke releases and the Phase 1 reactor
removes it (teg_id None only when another ACTIVE row names the same partner).
Both reactors run; their concerns are separate.
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import dispatch_webhook_event

logger = logging.getLogger(__name__)


class FrameFederationRevokedReactor(EventStoreReactor):
    event_type = "FrameFederationRevoked"
    leader_key = "reactor_frame_federation_revoked"
    name = "FrameFederationRevoked"

    async def handle_event(self, event_data: dict) -> None:
        peer_id = event_data.get("peer_id")
        peer_name = event_data.get("peer_name") or "?"
        trust_domain = event_data.get("trust_domain") or "?"
        reason = event_data.get("reason") or "(no reason given)"

        logger.info(
            f"[Reactor:{self.name}] peer={peer_name} ({trust_domain}) "
            f"peer_id={peer_id} reason={reason!r} — propagating webhook"
        )

        await dispatch_webhook_event(
            event_type="frame_federation.revoked",
            event_data=event_data,
            source_label=self.name,
        )


# ----------------------------------------------------------------------- module API

_instance: Optional[FrameFederationRevokedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = FrameFederationRevokedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
