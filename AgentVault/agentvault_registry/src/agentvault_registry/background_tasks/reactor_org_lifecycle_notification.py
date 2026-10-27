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


class OrgMemberJoinedReactor(EventStoreReactor):
    event_type = "OrganizationMemberJoined"
    leader_key = "reactor_org_member_joined"
    name = "OrgMemberJoined"

    async def handle_event(self, event_data: dict) -> None:
        org_id = event_data.get("organization_id") or event_data.get("org_id")
        joined_dev_id = event_data.get("developer_id")
        if not org_id or not joined_dev_id:
            return
        async with get_db_context() as db:
            oname = await _org_name(db, org_id)
            admin_ids = await _org_admin_dev_ids(db, org_id)
        # Notify admins — not the joiner themselves.
        for aid in admin_ids:
            if int(aid) == int(joined_dev_id):
                continue
            await _notify_user(
                int(aid),
                title=f"New member in {oname}",
                message=f"Developer #{joined_dev_id} joined your organization '{oname}'.",
                notification_type="info",
            )


class OrgMemberRemovedReactor(EventStoreReactor):
    event_type = "OrganizationMemberRemoved"
    leader_key = "reactor_org_member_removed"
    name = "OrgMemberRemoved"

    async def handle_event(self, event_data: dict) -> None:
        org_id = event_data.get("organization_id") or event_data.get("org_id")
        removed_dev_id = event_data.get("developer_id") or event_data.get("removed_developer_id")
        if not org_id or not removed_dev_id:
            return
        async with get_db_context() as db:
            oname = await _org_name(db, org_id)
            admin_ids = await _org_admin_dev_ids(db, org_id)
        # Notify removed dev
        await _notify_user(
            int(removed_dev_id),
            title=f"Removed from {oname}",
            message=f"You've been removed from the organization '{oname}'.",
            notification_type="warning",
        )
        # Notify remaining admins (NOT the removed dev)
        for aid in admin_ids:
            if int(aid) == int(removed_dev_id):
                continue
            await _notify_user(
                int(aid),
                title=f"Member removed from {oname}",
                message=f"Developer #{removed_dev_id} was removed from '{oname}'.",
                notification_type="info",
            )


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
