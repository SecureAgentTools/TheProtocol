"""
Reactor: Org-lifecycle → user-targeted notification
====================================================
§bc4 T4.5 (2026-05-19).

Subscribes to organization lifecycle events emitted by
`organization_service._emit_org_event`. Converts each event into a
user-targeted broadcast via `ws_manager.broadcast(..., audience='user_<id>')`.

Routing rules per Commander lock #3 + drift-reactor-pattern:
  - OrganizationMemberInvited → notify INVITEE only ("You've been invited to org X")
  - OrganizationMemberJoined  → notify ALL ORG ADMINS ("Y joined your org")
  - OrganizationMemberRemoved → notify REMOVED DEV + remaining org admins

Audit-only: the reactor calls `broadcast_notification` (ephemeral WS push,
no persistence as AdminBroadcast row). Critical-banner / bell items for
these are short-lived by design — they're operational notifications, not
admin announcements.

V0652 (af) (order gwo_3b80091fe506da824c40f903): each also goes out as its catalog type (org.invitation_received,
org.invitation_accepted to the inviter, org.member_joined, org.member_left), so it reaches the bell and, where the
person's preferences say so, their devices; the live toast stays. And every developer id is read with
local_developer_id: a peer frame's bridged event names no developer of ours (its developer 12 is not our 12), which
the joined and removed reactors had not asked.

Env gate: REACTOR_ORG_LIFECYCLE_NOTIFICATION_ENABLED (default true).
"""
import logging
import os
from typing import List

from sqlalchemy import select

from agentvault_registry import models
from agentvault_registry.database import get_db_context
from agentvault_registry.routers.websocket import broadcast_notification

from .reactor_base import EventStoreReactor
from .reactor_helpers import local_developer_id

logger = logging.getLogger(__name__)


async def _org_admin_dev_ids(db, organization_id: str) -> List[int]:
    """Return developer_ids of org members with role in (owner, admin)."""
    r = await db.execute(
        select(models.OrganizationMember.developer_id).where(
            models.OrganizationMember.organization_id == organization_id,
            models.OrganizationMember.role.in_(["owner", "admin"]),
        )
    )
    return [row[0] for row in r.fetchall() if row[0]]


async def _org_name(db, organization_id: str) -> str:
    r = await db.execute(
        select(models.Organization.name).where(models.Organization.id == organization_id)
    )
    row = r.first()
    return (row[0] if row else None) or organization_id


async def _dev_name(db, dev_id: int) -> str:
    """V0652 (af): a person's name for a notice ("Developer #12" said nothing to anybody)."""
    try:
        r = (await db.execute(select(models.Developer.name).where(models.Developer.id == int(dev_id)))).first()
        if r and r[0]:
            return str(r[0])
    except Exception:  # noqa: BLE001 — a label
        pass
    return f"Developer #{dev_id}"


async def _notify_user(dev_id: int, title: str, message: str, notification_type: str = "info") -> None:
    try:
        await broadcast_notification(
            title=title,
            message=message,
            notification_type=notification_type,
            audience=f"user_{dev_id}",
        )
    except Exception as e:
        logger.warning(f"[Reactor:OrgLifecycle] notify user {dev_id} failed: {e}")


async def _notice(type_key: str, dev_id: int, title: str, message: str) -> None:
    """V0652 (af): the typed notice beside the toast: the bell, and the devices the person's preferences allow. Never
    raises (notify() never does), and it is the handler's last step for its person, after the toast."""
    from agentvault_registry.background_tasks import push_notify
    await push_notify.notify(type_key, [int(dev_id)], title=title, message=message, click="/ui#/organization")


class OrgMemberInvitedReactor(EventStoreReactor):
    event_type = "OrganizationMemberInvited"
    leader_key = "reactor_org_member_invited"
    name = "OrgMemberInvited"

    async def handle_event(self, event_data: dict) -> None:
        org_id = event_data.get("organization_id") or event_data.get("org_id")
        # §DOCSFIX D6-484 (2026-10-16): the invite route now names the invitee's account (invitee_developer_id, null
        # when the address has none here). A bridged copy of a peer's invitation names no developer of ours: a
        # developer id is only unique per database (local_developer_id), so nobody here is told.
        invitee_dev_id = local_developer_id(event_data, "invitee_developer_id")
        if not org_id or not invitee_dev_id:
            logger.debug(f"[Reactor:{self.name}] missing org_id or invitee_dev_id: {event_data}")
            return
        async with get_db_context() as db:
            oname = await _org_name(db, org_id)
        await _notify_user(
            int(invitee_dev_id),
            title=f"Invitation to {oname}",
            message=f"You've been invited to join the organization '{oname}'.",
            notification_type="info",
        )
        await _notice("org.invitation_received", int(invitee_dev_id), f"Invitation to {oname}", f"You've been invited to join the organization '{oname}'.")


class OrgMemberJoinedReactor(EventStoreReactor):
    event_type = "OrganizationMemberJoined"
    leader_key = "reactor_org_member_joined"
    name = "OrgMemberJoined"

    async def handle_event(self, event_data: dict) -> None:
        org_id = event_data.get("organization_id") or event_data.get("org_id")
        joined_dev_id = local_developer_id(event_data, "developer_id")   # V0652 (af): ours, never a peer's id
        if not org_id or not joined_dev_id:
            return
        inviter_id = local_developer_id(event_data, "invited_by")
        async with get_db_context() as db:
            oname = await _org_name(db, org_id)
            admin_ids = await _org_admin_dev_ids(db, org_id)
            joiner = await _dev_name(db, joined_dev_id)
        # V0652 (af): the one who invited them hears that it was accepted
        if inviter_id and int(inviter_id) != int(joined_dev_id):
            await _notify_user(
                int(inviter_id),
                title=f"{joiner} accepted your invitation",
                message=f"{joiner} joined the organization '{oname}'.",
                notification_type="info",
            )
            await _notice("org.invitation_accepted", int(inviter_id), f"{joiner} accepted your invitation", f"{joiner} joined the organization '{oname}'.")
        # Notify admins — not the joiner themselves (nor the inviter, told above).
        for aid in admin_ids:
            if int(aid) == int(joined_dev_id) or (inviter_id and int(aid) == int(inviter_id)):
                continue
            await _notify_user(
                int(aid),
                title=f"New member in {oname}",
                message=f"{joiner} joined your organization '{oname}'.",
                notification_type="info",
            )
            await _notice("org.member_joined", int(aid), f"New member in {oname}", f"{joiner} joined your organization '{oname}'.")


class OrgMemberRemovedReactor(EventStoreReactor):
    event_type = "OrganizationMemberRemoved"
    leader_key = "reactor_org_member_removed"
    name = "OrgMemberRemoved"

    async def handle_event(self, event_data: dict) -> None:
        org_id = event_data.get("organization_id") or event_data.get("org_id")
        # V0652 (af): ours, never a peer's id
        removed_dev_id = (local_developer_id(event_data, "developer_id")
                          or local_developer_id(event_data, "removed_developer_id"))
        if not org_id or not removed_dev_id:
            return
        async with get_db_context() as db:
            oname = await _org_name(db, org_id)
            admin_ids = await _org_admin_dev_ids(db, org_id)
            removed = await _dev_name(db, removed_dev_id)
        # Notify removed dev
        await _notify_user(
            int(removed_dev_id),
            title=f"Removed from {oname}",
            message=f"You've been removed from the organization '{oname}'.",
            notification_type="warning",
        )
        await _notice("org.member_left", int(removed_dev_id), f"Removed from {oname}", f"You've been removed from the organization '{oname}'.")
        # Notify remaining admins (NOT the removed dev)
        for aid in admin_ids:
            if int(aid) == int(removed_dev_id):
                continue
            await _notify_user(
                int(aid),
                title=f"Member removed from {oname}",
                message=f"{removed} was removed from '{oname}'.",
                notification_type="info",
            )
            await _notice("org.member_left", int(aid), f"Member removed from {oname}", f"{removed} was removed from '{oname}'.")


# ─── module API ─────────────────────────────────────────────────────────────

_invited: OrgMemberInvitedReactor | None = None
_joined: OrgMemberJoinedReactor | None = None
_removed: OrgMemberRemovedReactor | None = None


def _gated() -> bool:
    return os.getenv("REACTOR_ORG_LIFECYCLE_NOTIFICATION_ENABLED", "true").lower() == "true"


async def start() -> None:
    global _invited, _joined, _removed
    if not _gated():
        logger.info("[Reactor:OrgLifecycle] disabled by env gate")
        return
    if _invited is None: _invited = OrgMemberInvitedReactor()
    if _joined is None: _joined = OrgMemberJoinedReactor()
    if _removed is None: _removed = OrgMemberRemovedReactor()
    await _invited.start()
    await _joined.start()
    await _removed.start()


async def stop() -> None:
    global _invited, _joined, _removed
    for r in (_invited, _joined, _removed):
        if r is not None:
            try:
                await r.stop()
            except Exception as e:
                logger.warning(f"reactor stop error: {e}")
    _invited = _joined = _removed = None
