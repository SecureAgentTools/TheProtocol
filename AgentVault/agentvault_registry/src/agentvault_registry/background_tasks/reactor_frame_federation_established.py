"""
Reactors: FrameInvitationApproved and FrameFederationEstablished → TEG partner add
==================================================================================
(agentvault2-56, 2026-10-21; his word: "1. yes" to "build the reactor so federating frames trust each other
automatically")

The TEG partner rule (ledgergate3) runs a cross-TEG leg only with a peer the TEG holds as a current partner, and only
add-partner makes one. A frame added its cloud operators at provisioning and a peer back at reactivation, quarantine
lift or licence reinstatement, but two frames that federated through the invitation rail never added each other.

A frame starts trusting a peer frame at one of two moments, and each emits an event on this frame's own store:
  - FrameInvitationApproved: this frame's admin approved the peer frame's invitation; the peer row is ACTIVE from then on
    (in a pair where each frame approves the other's invitation, as the nightly pair does, this is the only event:
    measured on nt261021x2 2026-10-21, both invitations 'approved', no FrameFederationEstablished on either store);
  - FrameFederationEstablished: the bilateral handshake completed (the approver at approve, the initiator at finalize).
Each reactor registers the peer named by its event through reactor_helpers.register_peer_partner_on_teg (teg-<safe
name>, the row's address), the helper the reactivation and the quarantine lift use. Each acts only on this registry's
own event: the payload's invitation and peer row are this registry's, so it acts only when this database holds that
invitation naming that peer and the peer row is ACTIVE. That skips another frame's event (marked foreign by the store)
and a parent frame's event a cloud operator reads from the store it shares. add-partner is idempotent (`updated` for a
partner the TEG holds), so a frame that sees both events registers once and confirms once. The revoke releases the
partner: frame_invitations' revoke names it in its PeerRegistryDeactivated event, which the Phase 1 reactor removes.
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import register_peer_partner_on_teg

logger = logging.getLogger(__name__)


async def _register_peer_of_event(event_data: dict, label: str) -> None:
    """Register the ACTIVE peer frame this registry's own event names as a partner on this frame's TEG."""
    invitation_id = event_data.get("invitation_id")
    peer_id = event_data.get("peer_registry_id")
    side = event_data.get("side") or "?"
    if event_data.get("_foreign_frame_id"):
        logger.info(f"[Reactor:{label}] Skipped invitation={invitation_id}: another frame's handshake "
                    f"(frame {event_data.get('_foreign_frame_id')})")
        return
    if not invitation_id or not peer_id:
        logger.info(f"[Reactor:{label}] Skipped: the payload names no invitation or no peer "
                    f"(invitation={invitation_id!r} peer={peer_id!r})")
        return

    from agentvault_registry import models
    from agentvault_registry.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        inv = await db.get(models.FrameInvitation, str(invitation_id))
        if inv is None or str(inv.peer_registry_id) != str(peer_id):
            logger.info(f"[Reactor:{label}] Skipped invitation={invitation_id} peer={peer_id}: this registry holds no "
                        f"such handshake (another registry's event in a shared store)")
            return
        peer = await db.get(models.PeerRegistry, int(peer_id))
        if peer is None or (peer.status or "").upper() != "ACTIVE":
            logger.info(f"[Reactor:{label}] Skipped invitation={invitation_id} peer={peer_id}: the peer row is "
                        f"{'missing' if peer is None else peer.status}, not ACTIVE")
            return
        peer_name = peer.name
        result = await register_peer_partner_on_teg(db, peer_name, source_label=label)
    if result is None:
        logger.warning(f"[Reactor:{label}] invitation={invitation_id} side={side} peer={peer_id}: the TEG partner was not "
                       f"registered (see the helper's line above); this frame's next leg to the peer registers it on "
                       f"this side")
        return
    logger.info(f"[Reactor:{label}] invitation={invitation_id} side={side} peer={peer_name} → TEG partner "
                f"status={result.get('status', '?')} (total_partners={result.get('total_partners', '?')})")


class FrameFederationEstablishedReactor(EventStoreReactor):
    event_type = "FrameFederationEstablished"
    leader_key = "reactor_frame_federation_established"
    name = "FrameFederationEstablished"

    async def handle_event(self, event_data: dict) -> None:
        await _register_peer_of_event(event_data, self.name)


class FrameInvitationApprovedPartnerReactor(EventStoreReactor):
    event_type = "FrameInvitationApproved"
    leader_key = "reactor_frame_invitation_approved_partner"
    name = "FrameInvitationApproved"

    async def handle_event(self, event_data: dict) -> None:
        await _register_peer_of_event(event_data, self.name)


_instance: Optional[FrameFederationEstablishedReactor] = None
_approved_instance: Optional[FrameInvitationApprovedPartnerReactor] = None


async def start() -> None:
    global _instance, _approved_instance
    if _instance is None:
        _instance = FrameFederationEstablishedReactor()
    if _approved_instance is None:
        _approved_instance = FrameInvitationApprovedPartnerReactor()
    await _instance.start()
    await _approved_instance.start()


async def stop() -> None:
    global _instance, _approved_instance
    for inst in (_instance, _approved_instance):
        if inst is not None:
            await inst.stop()
    _instance = None
    _approved_instance = None
