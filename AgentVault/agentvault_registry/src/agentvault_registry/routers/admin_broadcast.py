"""
Admin Notification Broadcast Channel — f034

Admin endpoints (is_admin=True required):
  POST   /api/v1/admin/broadcasts         — compose + send
  GET    /api/v1/admin/broadcasts         — list all (paginated)
  DELETE /api/v1/admin/broadcasts/{id}    — soft-delete / retract

Developer endpoints (authenticated developer):
  GET    /api/v1/notifications/unread     — fetch unseen items (called on login)
  POST   /api/v1/notifications/{id}/read  — mark one dismissed

Delivery chain on POST /admin/broadcasts:
  1. Persist AdminBroadcast row
  2. manager.broadcast_notification() → all connected WS users
  3. If send_email=True → bulk send via fastapi-mail
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, Security
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, text

from agentvault_registry import models, security
from agentvault_registry.services.developer_population import a_developer_of_this_registry
from agentvault_registry.database import get_db
from agentvault_registry.routers.websocket import manager as ws_manager
from agentvault_registry.event_emitter import get_event_emitter

# §bc2 T2.6 — rate limit on /notifications/{id}/read. Falls back to a no-op
# decorator if slowapi is unavailable in the test env.
try:
    # §RATEFIX: share the one Redis-backed limiter (see middleware/rate_limiter).
    from agentvault_registry.middleware.rate_limiter import shared_limiter as _bc_limiter
    _RATE_LIMIT_DECORATOR = _bc_limiter.limit("60/minute")
except Exception:  # pragma: no cover
    def _RATE_LIMIT_DECORATOR(func):  # type: ignore[misc]
        return func

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Admin — Broadcasts"])

import os as _bc_os  # local alias

# §bc2 — registry identity used to stamp `source_frame` for federation dedup
# (§bc3) + audit-event metadata.
SOURCE_FRAME = _bc_os.getenv("REGISTRY_NAME", "registry-a")


def event_frame_fields(broadcast) -> dict:
    """§MCPTEST30 (V0558): the frame a broadcast's event may speak for. Only the registry that SENT a broadcast speaks
    for it. A copy materialized from a peer keeps the peer's frame name and this registry's OWN row id, so an event
    naming both points every other copy of that peer's broadcasts at the one with that id: some other broadcast. A
    copy's events keep their audit as local_copy_of and carry no source_frame, which every receiver skips."""
    sf = getattr(broadcast, "source_frame", None)
    if not sf or sf == SOURCE_FRAME:
        return {"source_frame": sf}
    return {"source_frame": None, "local_copy_of": sf}


COPY_BODY_MAX = 16_000   # a body longer than this stays on the sending registry: the copy reads its fallback line


def copy_content(broadcast) -> dict:
    """D6-211 (2026-10-17): the words a peer's copy shows. A broadcast to everyone carries its body and call to action
    in its event, so a peer's copy reads as the broadcast (the receiver read them, the event never carried them: every
    copy said "[Federated from <registry>]" and lost its link). A targeted one carries none: it is never copied
    (§SECFIX D6-305), and its words stay off the shared ledger. The body rides only within COPY_BODY_MAX (a broadcast's
    body has no length limit, and an oversized event would cost the sender its audit record)."""
    if getattr(broadcast, "target_org_id", None) or getattr(broadcast, "target_developer_id", None) is not None:
        return {}
    body = broadcast.body if len(broadcast.body or "") <= COPY_BODY_MAX else None
    return {"body": body, "cta_url": broadcast.cta_url, "cta_label": broadcast.cta_label}


def edit_content(broadcast) -> dict:
    """The words an edit carries to the copies, by copy_content's rule: the title and type, and the body within
    COPY_BODY_MAX; nothing for a targeted broadcast."""
    words = copy_content(broadcast)
    if not words:
        return {}
    out = {"title": broadcast.title, "broadcast_type": broadcast.broadcast_type}
    if words.get("body"):
        out["body"] = words["body"]
    return out


# ---------------------------------------------------------------------------
# Pydantic schemas (inline — no separate schemas.py entry needed yet)
# ---------------------------------------------------------------------------

class BroadcastCreate(BaseModel):
    title: str = Field(..., max_length=200)
    body: str = Field(..., min_length=1)
    broadcast_type: str = Field(default="info", pattern="^(info|warning|maintenance|critical)$")
    send_email: bool = False
    # §bc2 T2.1/T2.7/T2.8 — optional CTA + ack + schedule
    cta_url: Optional[str] = Field(default=None, max_length=500)
    cta_label: Optional[str] = Field(default=None, max_length=50)
    requires_ack: bool = False
    scheduled_for: Optional[datetime] = None
    # §bc4 — optional org-scoped target. §bc3 — optional idempotency key for
    # federation dedup. source_frame is server-stamped (not client-trusted).
    target_org_id: Optional[str] = Field(default=None, max_length=255)
    # A notice for ONE developer of this registry (migration 0179). Delivered live to that developer's sockets
    # only, listed only in their bell, and audited under DIRECT_NOTICE_EVENT so no peer frame copies it.
    target_developer_id: Optional[int] = Field(default=None, ge=1)
    idempotency_key: Optional[str] = Field(default=None, max_length=120)
    # §bc3 T3.7 — admin can opt to NOT receive their own broadcast (most common
    # case: they composed it themselves and don't need the toast on their own
    # screen). Server passes exclude_user to ws_manager.broadcast(). Default
    # FALSE for backward-compat with existing API consumers / tests; the
    # admin compose UI defaults to true on the human-facing checkbox.
    skip_self: bool = False


class BroadcastOut(BaseModel):
    id: int
    title: str
    body: str
    broadcast_type: str
    created_by: int
    created_at: datetime
    is_active: bool
    send_email: bool
    email_sent_at: Optional[datetime]
    ws_recipients: int
    # §bc2 — extension fields. All optional; absent on rows pre-migration 0070.
    cta_url: Optional[str] = None
    cta_label: Optional[str] = None
    requires_ack: bool = False
    scheduled_for: Optional[datetime] = None
    source_frame: Optional[str] = None
    idempotency_key: Optional[str] = None
    target_org_id: Optional[str] = None
    target_developer_id: Optional[int] = None

    model_config = {"from_attributes": True}


# A developer-targeted notice is audited under its own event type. Every AdminBroadcastSent is materialized by
# reactor_admin_broadcast_received on each registry that reads the same event store (a frame's operators read
# their parent's), and those registries do not know this column: the copy would reach ALL their developers.
DIRECT_NOTICE_EVENT = "AdminDirectNoticeSent"


def direct_notice_refusal(payload: "BroadcastCreate") -> Optional[str]:
    """Why a developer-targeted notice cannot be sent as asked, or None. The email, schedule and org paths
    all fan out to more than one developer, so they are refused rather than quietly narrowed."""
    if payload.target_developer_id is None:
        return None
    if payload.target_org_id:
        return "target_developer_id and target_org_id are exclusive"
    if payload.send_email:
        return "a developer-targeted notice is in-app only; send_email is not supported"
    if payload.scheduled_for is not None:
        return "a developer-targeted notice is sent now; scheduled_for is not supported"
    return None


def visible_to(broadcast: "models.AdminBroadcast", developer_id: int, org_ids=()) -> bool:
    """Who may read a broadcast: a developer-targeted notice only its developer, an organization's broadcast only the
    organization's active members (`org_ids`: the caller's, from member_org_ids), anything else every developer.

    The one audience rule of every developer read (the bell, the community page, one broadcast by id, mark-read) and of
    the email. §SECFIX D6-212/D6-305 (2026-10-16): it hid only direct notices, so another organization's broadcast was
    readable by id, listed on the community page and emailed to every verified developer. audience_clause is its SQL twin."""
    target = getattr(broadcast, "target_developer_id", None)
    if target is not None and target != developer_id:
        return False
    org = getattr(broadcast, "target_org_id", None)
    return org is None or org in set(org_ids or ())


def developer_clause(developer_id: int):
    """The bell's filter: untargeted broadcasts plus the notices addressed to this developer."""
    return models.AdminBroadcast.target_developer_id.is_(None) | (
        models.AdminBroadcast.target_developer_id == developer_id
    )


def audience_clause(developer_id: int, org_ids=()):
    """visible_to in SQL: the developer's notices or untargeted ones, AND untargeted by organization or for one of the
    organizations it is an active member of."""
    org = models.AdminBroadcast.target_org_id.is_(None)
    if org_ids:
        org = org | models.AdminBroadcast.target_org_id.in_(list(org_ids))
    return and_(developer_clause(developer_id), org)


async def member_org_ids(db: AsyncSession, developer_id: int) -> List[str]:
    """The organizations whose broadcasts this developer may read: those it is an ACTIVE member of (live_reach and the
    email count the same members)."""
    rows = await db.execute(
        select(models.OrganizationMember.organization_id).where(
            models.OrganizationMember.developer_id == developer_id,
            models.OrganizationMember.is_active == True,  # noqa: E712
        ))
    return [str(r[0]) for r in rows.fetchall() if r[0]]


def is_sent(broadcast: "models.AdminBroadcast") -> bool:
    """A broadcast scheduled for later is not sent yet: the bell hides it until then, and so does every developer read."""
    when = getattr(broadcast, "scheduled_for", None)
    if when is None:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when <= datetime.now(timezone.utc)


def sent_clause():
    """is_sent in SQL (the bell's deferred-broadcast guard)."""
    return models.AdminBroadcast.scheduled_for.is_(None) | (
        models.AdminBroadcast.scheduled_for <= datetime.now(timezone.utc)
    )


def email_audience_clause(broadcast: "models.AdminBroadcast"):
    """The developers a broadcast's email may reach: its developer, its organization's active members, or everyone."""
    target = getattr(broadcast, "target_developer_id", None)
    if target is not None:
        return models.Developer.id == target
    org = getattr(broadcast, "target_org_id", None)
    if org:
        return models.Developer.id.in_(
            select(models.OrganizationMember.developer_id).where(
                models.OrganizationMember.organization_id == org,
                models.OrganizationMember.is_active == True,  # noqa: E712
            ))
    return models.Developer.id.is_not(None)


def ws_audience(broadcast: "models.AdminBroadcast") -> Optional[str]:
    """Who a live push about this broadcast reaches: its developer, its organization's members, or everyone.

    §FESUITE (2026-10-10, lifecycle 87): an org-scoped broadcast was pushed live to EVERY connected developer of the frame,
    title and body: the push named no audience and its data carried no target_org_id, so the socket manager's org filter
    never applied (only the bell's read was scoped). The org_<id> audience is resolved by the manager (§bc4 T4.3)."""
    target = getattr(broadcast, "target_developer_id", None)
    if target is not None:
        return f"user_{target}"
    org = getattr(broadcast, "target_org_id", None)
    return f"org_{org}" if org else None


def live_notice(broadcast: "models.AdminBroadcast") -> dict:
    """The live push of a broadcast as it goes out, sent now or at its scheduled time: its id (mark-read), its CTA,
    whether it must be acknowledged, and its organization (the per-org mute reads it, _passes_prefs_filter).

    §SECFIX D6-304 (2026-10-16): the scheduler built its own push with title, message and type only."""
    return {
        "type": "notification",
        "data": {
            "broadcast_id": broadcast.id,
            "title": broadcast.title,
            "message": broadcast.body,
            "type": broadcast.broadcast_type,
            "cta_url": broadcast.cta_url,
            "cta_label": broadcast.cta_label,
            "requires_ack": broadcast.requires_ack,
            "target_org_id": broadcast.target_org_id,
        },
    }


async def live_reach(db: AsyncSession, audience: Optional[str], exclude_user: Optional[str] = None) -> int:
    """How many of a broadcast's audience were online when it went out: developers holding a live socket, read from the
    presence keys (routers/websocket.py `presence:ws:<developer id>`, written by a live socket and refreshed by its
    heartbeat, 90 s TTL), for its developer, its organization's active members or everyone.

    §FESUITE V0595: the row stored ws_manager.get_connection_count(), the connections held by the ONE gunicorn worker that
    served the POST: neither the frame's nor the audience's (an org- or developer-scoped broadcast stored the same figure
    as one to everyone), and the scheduled path stored none. A presence that cannot be read counts 0 and says so in the
    log: never a stand-in figure."""
    try:
        r = await ws_manager._get_redis()
    except Exception:  # noqa: BLE001
        r = None
    if r is None:
        logger.warning("[broadcast] presence unreadable (no Redis): the reach is recorded as 0")
        return 0
    skip = str(exclude_user) if exclude_user else None
    try:
        if audience and audience.startswith("user_"):
            ids = [audience[len("user_"):]]
        elif audience and audience.startswith("org_"):
            rows = await db.execute(
                select(models.OrganizationMember.developer_id).where(
                    models.OrganizationMember.organization_id == audience[len("org_"):],
                    models.OrganizationMember.is_active == True,  # noqa: E712
                ))
            ids = [str(x) for x in rows.scalars().all()]
        else:
            found = 0
            async for key in r.scan_iter(match="presence:ws:*", count=500):
                suffix = (key.decode() if isinstance(key, bytes) else str(key)).rsplit(":", 1)[-1]
                if suffix.isdigit() and suffix != skip:
                    found += 1
            return found
        ids = [i for i in ids if i != skip]
        return int(await r.exists(*[f"presence:ws:{i}" for i in ids])) if ids else 0
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[broadcast] presence read failed ({e}): the reach is recorded as 0")
        return 0


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/admin/broadcasts",
    response_model=BroadcastOut,
    status_code=status.HTTP_201_CREATED,
    summary="Compose and broadcast an admin notification to all developers",
)
async def create_broadcast(
    payload: BroadcastCreate,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    """
    Creates an admin broadcast, pushes it via WebSocket to all online users,
    persists it for offline users, and optionally sends email.
    """
    refusal = direct_notice_refusal(payload)
    if refusal:
        raise HTTPException(status_code=422, detail=refusal)
    if payload.target_developer_id is not None:
        exists = await db.execute(select(models.Developer.id).where(models.Developer.id == payload.target_developer_id))
        if exists.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="target developer not found")

    # 1. Persist (with §bc2 extension fields)
    broadcast = models.AdminBroadcast(
        title=payload.title,
        body=payload.body,
        broadcast_type=payload.broadcast_type,
        created_by=current_admin.id,
        send_email=payload.send_email,
        cta_url=payload.cta_url,
        cta_label=payload.cta_label,
        requires_ack=payload.requires_ack,
        scheduled_for=payload.scheduled_for,
        target_org_id=payload.target_org_id,
        target_developer_id=payload.target_developer_id,
        idempotency_key=payload.idempotency_key,
        source_frame=SOURCE_FRAME,
    )
    db.add(broadcast)
    await db.flush()  # get the id before WS send

    # §bc2 — if scheduled_for is in the future, DON'T fire WS/email now;
    # broadcast_scheduler.py picks it up at the scheduled time.
    is_deferred = (
        payload.scheduled_for is not None
        and payload.scheduled_for > datetime.now(timezone.utc)
    )

    if not is_deferred:
        # It goes out now, so nothing is left for the scheduler: a schedule time already past stayed on the row and the
        # scheduler, which takes every row still holding one as not sent yet, pushed it a second time (§SECFIX D6-304).
        broadcast.scheduled_for = None
        # 2. WebSocket broadcast
        # §bc3 T3.7 — admin's `skip_self` flag → exclude_user kwarg to skip
        # the composer's own connections (most common case).
        ws_exclude_user = str(current_admin.id) if payload.skip_self else None
        try:
            # §bc2 T2.7/T2.8: the CTA and the sticky flag ride along (live_notice, the scheduler's push too)
            await ws_manager.broadcast(
                live_notice(broadcast), exclude_user=ws_exclude_user, audience=ws_audience(broadcast))
            # §FESUITE V0595: the audience's developers online at send (live_reach), not one worker's connections
            broadcast.ws_recipients = await live_reach(db, ws_audience(broadcast), ws_exclude_user)
            logger.info(
                f"Broadcast #{broadcast.id} '{broadcast.title}' pushed live; {broadcast.ws_recipients} of its audience online"
            )
        except Exception as e:
            logger.error(f"WS broadcast failed for broadcast #{broadcast.id}: {e}")

        # 3. Email (optional)
        if payload.send_email:
            try:
                await _send_broadcast_email(broadcast, db)
                broadcast.email_sent_at = datetime.now(timezone.utc)
                logger.info(f"Broadcast #{broadcast.id} email queued")
            except Exception as e:
                logger.error(f"Email send failed for broadcast #{broadcast.id}: {e}")
                # Don't fail the request — WS + DB are the primary channels

    await db.commit()
    await db.refresh(broadcast)

    # §bc2 T2.3 — EventStore audit emit (after commit, fire-and-forget; never
    # block the admin response on EventStore reachability).
    try:
        emitter = get_event_emitter()
        await emitter.emit(
            # Both branches are literals so the emission census reads both names (it reads literals, not variables).
            event_type="AdminDirectNoticeSent" if broadcast.target_developer_id is not None else "AdminBroadcastSent",
            aggregate_id=f"broadcast-{broadcast.id}",
            aggregate_type="AdminBroadcast",
            # The source frame is part of the key: a frame's operators write into the same store and number their
            # broadcasts from 1 too, so a key of the id alone would drop another registry's event as a duplicate.
            idempotency_key=f"admin-broadcast-sent:{broadcast.source_frame}:{broadcast.id}",
            data={
                "broadcast_id": broadcast.id,
                "title": broadcast.title,
                "broadcast_type": broadcast.broadcast_type,
                "created_by": current_admin.id,
                "send_email": broadcast.send_email,
                "scheduled_for": broadcast.scheduled_for.isoformat() if broadcast.scheduled_for else None,
                "deferred": is_deferred,
                "target_org_id": broadcast.target_org_id,
                "target_developer_id": broadcast.target_developer_id,
                "source_frame": broadcast.source_frame,
                "requires_ack": broadcast.requires_ack,
                "has_cta": bool(broadcast.cta_url),
                **copy_content(broadcast),
            },
            metadata={"action_class": "admin_broadcast"},
        )
    except Exception as e:
        logger.warning(f"AdminBroadcastSent EventStore emit failed for #{broadcast.id}: {e}")
    return broadcast


@router.get(
    "/admin/broadcasts",
    response_model=List[BroadcastOut],
    summary="List all admin broadcasts (admin only)",
)
async def list_broadcasts(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
    include_inactive: bool = Query(default=True),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    query = select(models.AdminBroadcast).order_by(models.AdminBroadcast.created_at.desc())
    if not include_inactive:
        query = query.where(models.AdminBroadcast.is_active == True)
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.delete(
    "/admin/broadcasts/{broadcast_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retract / soft-delete a broadcast (admin only)",
)
async def retract_broadcast(
    broadcast_id: int,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(models.AdminBroadcast).where(models.AdminBroadcast.id == broadcast_id)
    )
    broadcast = result.scalar_one_or_none()
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    broadcast.is_active = False
    await db.commit()
    # §bc1 T1.4 — notify connected clients to retract this broadcast.
    try:
        await ws_manager.broadcast({
            "type": "broadcast.retracted",
            "data": {"broadcast_id": broadcast_id},
        }, audience=ws_audience(broadcast))
    except Exception as e:
        logger.warning(f"broadcast.retracted WS emit failed for #{broadcast_id}: {e}")
    # §bc2 T2.3 — EventStore audit emit
    try:
        emitter = get_event_emitter()
        await emitter.emit(
            event_type="AdminBroadcastRetracted",
            aggregate_id=f"broadcast-{broadcast_id}",
            aggregate_type="AdminBroadcast",
            data={
                "broadcast_id": broadcast_id,
                "retracted_by": current_admin.id,
                # §MCPTEST30 V0639: an organization's broadcast and a direct notice are never copied to a peer, so a
                # receiver must not hold a place for their copy (reactor_admin_broadcast_received)
                "targeted": broadcast.target_org_id is not None or broadcast.target_developer_id is not None,
                **event_frame_fields(broadcast),
            },
            metadata={"action_class": "admin_broadcast"},
        )
    except Exception as e:
        logger.warning(f"AdminBroadcastRetracted EventStore emit failed for #{broadcast_id}: {e}")


# ---------------------------------------------------------------------------
# §pass40 (2026-05-18) — Reinstate + Edit + Stats + Overview for AAA+ admin UI
# ---------------------------------------------------------------------------

class BroadcastUpdate(BaseModel):
    """Partial update for an existing broadcast. Title/body/type editable.
    Cannot retroactively change send_email (that fired on create)."""
    title: Optional[str] = Field(default=None, max_length=200)
    body: Optional[str] = Field(default=None, min_length=1)
    broadcast_type: Optional[str] = Field(
        default=None,
        pattern="^(info|warning|maintenance|critical)$",
    )


class BroadcastStats(BaseModel):
    """Per-broadcast stats — read count, dismissed-by, recipient breakdown."""
    broadcast_id: int
    title: str
    is_active: bool
    ws_recipients_at_send: int
    email_sent: bool
    read_count: int
    total_developers: int
    read_pct: float
    recent_readers: List[dict]  # last 10 readers: { developer_id, email, read_at }


class OverviewStats(BaseModel):
    """Aggregate broadcast metrics for the admin dashboard top bar."""
    total: int
    active: int
    retracted: int
    last_24h: int
    last_7d: int
    by_type: dict  # { "info": N, "warning": N, "maintenance": N, "critical": N }
    emails_sent: int
    total_recipients_lifetime: int
    ws_connections_now: int
    verified_developers: int
    # §pass40 introduced this field as "local-only with federation on the
    # roadmap". §bc3 T3.1 (2026-05-19) shipped that federation reactor
    # (background_tasks/reactor_admin_broadcast_received.py), so the original
    # text became inaccurate. §pass69.6 (2026-05-25) Commander confirmed
    # cross-frame propagation works end-to-end (broadcast id=231 on Frame A
    # materialized on op-paris row 482 + op-tokyo row 19 within seconds).
    # Receiver auto-generates `foreign-<source_id>` dedup keys when the sender
    # omits `idempotency_key`, so the practical scope today is fleet-wide for
    # every broadcast. The opt-out hook is planned as `target_audience`
    # (§bc3.2 / §bc4 — not yet shipped).
    scope: str = "federated"
    scope_description: str = (
        "Broadcasts federate fleet-wide. The local AdminBroadcastSent/Edited/"
        "Retracted events are emitted on this registry's EventStore, and every "
        "peer registry's AdminBroadcastReceived reactor materializes a local "
        "row so its developers see the broadcast. Dedup is by "
        "(source_frame, idempotency_key); when the sender omits "
        "idempotency_key, the receiver synthesizes `foreign-<source_id>`. "
        "Explicit per-broadcast scope control via `target_audience` is a "
        "future hardening (§bc3.2)."
    )


@router.put(
    "/admin/broadcasts/{broadcast_id}",
    response_model=BroadcastOut,
    summary="Edit broadcast title/body/type after send (admin only)",
)
async def update_broadcast(
    broadcast_id: int,
    payload: BroadcastUpdate,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    """Edit an existing broadcast. Useful for typo fixes after send.
    WS clients re-fetch via /community/announcements so will see the
    update; offline developers see the edited version when they come back.
    """
    result = await db.execute(
        select(models.AdminBroadcast).where(models.AdminBroadcast.id == broadcast_id)
    )
    broadcast = result.scalar_one_or_none()
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    if payload.title is not None:
        broadcast.title = payload.title
    if payload.body is not None:
        broadcast.body = payload.body
    if payload.broadcast_type is not None:
        broadcast.broadcast_type = payload.broadcast_type
    await db.commit()
    await db.refresh(broadcast)
    logger.info(f"Broadcast #{broadcast_id} edited by admin={current_admin.id}")
    # §bc1 T1.4 — notify connected clients to patch this broadcast in place.
    try:
        await ws_manager.broadcast({
            "type": "broadcast.updated",
            "data": {
                "broadcast_id": broadcast_id,
                "title": broadcast.title,
                "body": broadcast.body,
                "broadcast_type": broadcast.broadcast_type,
            },
        }, audience=ws_audience(broadcast))
    except Exception as e:
        logger.warning(f"broadcast.updated WS emit failed for #{broadcast_id}: {e}")
    # §bc2 T2.3 — EventStore audit emit
    try:
        emitter = get_event_emitter()
        await emitter.emit(
            event_type="AdminBroadcastEdited",
            aggregate_id=f"broadcast-{broadcast_id}",
            aggregate_type="AdminBroadcast",
            data={
                "broadcast_id": broadcast_id,
                "edited_by": current_admin.id,
                "title_changed": payload.title is not None,
                "body_changed": payload.body is not None,
                "type_changed": payload.broadcast_type is not None,
                **event_frame_fields(broadcast),
                # D6-211: a peer's copy of a broadcast to everyone follows the edit (copy_content's rule)
                **edit_content(broadcast),
            },
            metadata={"action_class": "admin_broadcast"},
        )
    except Exception as e:
        logger.warning(f"AdminBroadcastEdited EventStore emit failed for #{broadcast_id}: {e}")
    return broadcast


@router.post(
    "/admin/broadcasts/{broadcast_id}/reinstate",
    response_model=BroadcastOut,
    summary="Reinstate a previously-retracted broadcast (admin only)",
)
async def reinstate_broadcast(
    broadcast_id: int,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    """Inverse of retract — flips is_active back to True. Useful when a
    retraction was a mis-click. Does NOT re-broadcast over WS (would be
    confusing to send the same notification twice)."""
    result = await db.execute(
        select(models.AdminBroadcast).where(models.AdminBroadcast.id == broadcast_id)
    )
    broadcast = result.scalar_one_or_none()
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    broadcast.is_active = True
    await db.commit()
    await db.refresh(broadcast)
    logger.info(f"Broadcast #{broadcast_id} reinstated by admin={current_admin.id}")
    return broadcast


@router.get(
    "/admin/broadcasts/overview",
    response_model=OverviewStats,
    summary="Aggregate broadcast metrics for the admin dashboard (admin only)",
)
async def get_overview(
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    """Top-bar metrics: lifetime/24h/7d totals, by-type breakdown, email count,
    aggregate WS recipients, current WS connection count, verified dev count."""
    from sqlalchemy import func

    # Counts
    total_q = await db.execute(select(func.count(models.AdminBroadcast.id)))
    total = total_q.scalar() or 0

    active_q = await db.execute(
        select(func.count(models.AdminBroadcast.id))
        .where(models.AdminBroadcast.is_active == True)
    )
    active = active_q.scalar() or 0
    retracted = total - active

    now = datetime.now(timezone.utc)
    h24 = now - timedelta(hours=24)
    d7 = now - timedelta(days=7)

    last_24h_q = await db.execute(
        select(func.count(models.AdminBroadcast.id))
        .where(models.AdminBroadcast.created_at >= h24)
    )
    last_24h = last_24h_q.scalar() or 0

    last_7d_q = await db.execute(
        select(func.count(models.AdminBroadcast.id))
        .where(models.AdminBroadcast.created_at >= d7)
    )
    last_7d = last_7d_q.scalar() or 0

    by_type_q = await db.execute(
        select(models.AdminBroadcast.broadcast_type, func.count(models.AdminBroadcast.id))
        .group_by(models.AdminBroadcast.broadcast_type)
    )
    by_type = {row[0]: row[1] for row in by_type_q.fetchall()}
    # Ensure all 4 types present in response
    for t in ("info", "warning", "maintenance", "critical"):
        by_type.setdefault(t, 0)

    emails_q = await db.execute(
        select(func.count(models.AdminBroadcast.id))
        .where(models.AdminBroadcast.email_sent_at.is_not(None))
    )
    emails_sent = emails_q.scalar() or 0

    recipients_q = await db.execute(
        select(func.coalesce(func.sum(models.AdminBroadcast.ws_recipients), 0))
    )
    total_recipients_lifetime = int(recipients_q.scalar() or 0)

    dev_q = await db.execute(
        select(func.count(models.Developer.id))
        .where(models.Developer.is_verified == True, a_developer_of_this_registry())
    )
    verified_developers = dev_q.scalar() or 0

    return OverviewStats(
        total=total,
        active=active,
        retracted=retracted,
        last_24h=last_24h,
        last_7d=last_7d,
        by_type=by_type,
        emails_sent=emails_sent,
        total_recipients_lifetime=total_recipients_lifetime,
        # §FESUITE V0595: developers online on this registry now (every worker: the presence keys), not one worker's sockets
        ws_connections_now=await live_reach(db, None),
        verified_developers=verified_developers,
    )


@router.get(
    "/admin/broadcasts/{broadcast_id}/stats",
    response_model=BroadcastStats,
    summary="Per-broadcast read/dismiss statistics (admin only)",
)
async def get_broadcast_stats(
    broadcast_id: int,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    """Read-count + dismiss-by-developer breakdown for a single broadcast.
    Used by the admin drawer to show "X of Y developers dismissed; recent
    readers: …" in real time."""
    from sqlalchemy import func

    result = await db.execute(
        select(models.AdminBroadcast).where(models.AdminBroadcast.id == broadcast_id)
    )
    broadcast = result.scalar_one_or_none()
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    read_count_q = await db.execute(
        select(func.count(models.DeveloperNotificationRead.id))
        .where(models.DeveloperNotificationRead.broadcast_id == broadcast_id)
    )
    read_count = read_count_q.scalar() or 0

    total_devs_q = await db.execute(
        select(func.count(models.Developer.id))
        .where(models.Developer.is_verified == True, a_developer_of_this_registry())
    )
    total_developers = total_devs_q.scalar() or 0

    # Last 10 readers
    recent_q = await db.execute(
        select(
            models.DeveloperNotificationRead.developer_id,
            models.Developer.email,
            models.DeveloperNotificationRead.read_at,
        )
        .join(
            models.Developer,
            models.Developer.id == models.DeveloperNotificationRead.developer_id,
        )
        .where(models.DeveloperNotificationRead.broadcast_id == broadcast_id)
        .order_by(models.DeveloperNotificationRead.read_at.desc())
        .limit(10)
    )
    recent_readers = [
        {
            "developer_id": row[0],
            "email": row[1],
            "read_at": row[2].isoformat() if row[2] else None,
        }
        for row in recent_q.fetchall()
    ]

    read_pct = (read_count / total_developers * 100.0) if total_developers else 0.0

    return BroadcastStats(
        broadcast_id=broadcast.id,
        title=broadcast.title,
        is_active=broadcast.is_active,
        ws_recipients_at_send=broadcast.ws_recipients,
        email_sent=broadcast.email_sent_at is not None,
        read_count=read_count,
        total_developers=total_developers,
        read_pct=round(read_pct, 1),
        recent_readers=recent_readers,
    )


# ---------------------------------------------------------------------------
# Developer endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/notifications/unread",
    response_model=List[BroadcastOut],
    summary="Get unread broadcasts for the current developer",
)
async def get_unread_notifications(
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """
    All active broadcasts the calling developer has not dismissed yet, for the notification bell. A new developer
    sees the broadcasts from sign-up or from the last 90 days, whichever is later; a broadcast scheduled for later
    stays hidden until it is sent.

    \f
    Returns all active broadcasts that the current developer has NOT yet dismissed.
    Call this on login or page load to populate the notification bell.

    §bc2 T2.4 — Backfill window (Locked Commander decision #1):
      New developers see broadcasts from `GREATEST(developer.created_at,
      NOW() - INTERVAL '90 days')` onwards. Old broadcasts predating that
      window aren't relevant to a freshly-signed-up dev.

    §bc2 T2.1 — Deferred-broadcast guard:
      Rows with `scheduled_for > NOW()` are NOT yet "sent" — they're queued
      for broadcast_scheduler.py. Hide them from the unread list so the
      bell doesn't show a notification before it's actually been broadcast.
    """
    # Subquery: broadcast ids already read by this developer
    read_ids_q = select(models.DeveloperNotificationRead.broadcast_id).where(
        models.DeveloperNotificationRead.developer_id == current_dev.id
    )
    result = await db.execute(read_ids_q)
    read_ids = {row[0] for row in result.fetchall()}

    # §bc2 T2.4 — backfill horizon. Use the more recent of (dev.created_at,
    # NOW() - 90d) so freshly-signed-up devs don't get blasted with the
    # full history but pre-existing devs see everything since they joined.
    horizon = max(
        current_dev.created_at,
        datetime.now(timezone.utc) - timedelta(days=90),
    )

    # §bc4 T4.4 — org-scoped visibility: target_org_id IS NULL means broadcast-to-all; non-NULL means visible ONLY to
    # that org's active members. The one rule every developer read asks (audience_clause, visible_to).
    dev_org_ids = await member_org_ids(db, current_dev.id)

    # Active, NOT-deferred, post-horizon, audience-visible, not-already-read, newest first
    query = (
        select(models.AdminBroadcast)
        .where(
            and_(
                models.AdminBroadcast.is_active == True,
                models.AdminBroadcast.created_at >= horizon,
                sent_clause(),  # Deferred-broadcast guard
                audience_clause(current_dev.id, dev_org_ids),
                models.AdminBroadcast.id.not_in(read_ids) if read_ids else True,
            )
        )
        .order_by(models.AdminBroadcast.created_at.desc())
        .limit(50)
    )
    result = await db.execute(query)
    items = list(result.scalars().all())

    # ── PENDING CONFIRMATIONS IN THE BELL (2026-07-25) ───────────────────────────────────────
    # The system notification arrived but the in-app bell stayed empty (Commander-found): the bell
    # only ever showed broadcasts, and a confirmation is not a broadcast. A push the app itself
    # cannot show is a push you have to take on faith. Synthesised per request from live rows —
    # never stored, never read-tracked — so the bell shows exactly what is still waiting and
    # empties itself the moment an item is approved, denied or expires.
    try:
        pend = (await db.execute(text("""
            SELECT id, action_type, action_ref, created_at
            FROM liability_challenges
            WHERE developer_id = :d AND status = 'pending' AND expires_at > now()
            ORDER BY created_at DESC LIMIT 10
        """), {"d": current_dev.id})).mappings().all()
        for i2, r in enumerate(pend):
            items.insert(i2, BroadcastOut(
                id=-(100000 + i2), title="Confirmation waiting",
                body=f"{r['action_type']}" + (f" \u00b7 {r['action_ref']}" if r["action_ref"] else "")
                     + " — approve with your fingerprint before it expires.",
                broadcast_type="action_required", created_by=0, created_at=r["created_at"],
                is_active=True, send_email=False, email_sent_at=None, ws_recipients=0,
                cta_url="/ui/#/pocket/approvals", cta_label="Review", requires_ack=False,
            ))
        logins = (await db.execute(text("""
            SELECT id, requested_ip, created_at FROM login_approvals
            WHERE developer_id = :d AND status = 'pending' AND expires_at > now()
            ORDER BY created_at DESC LIMIT 5
        """), {"d": current_dev.id})).mappings().all()
        for j, r in enumerate(logins):
            items.insert(j, BroadcastOut(
                id=-(200000 + j), title="Approve sign-in",
                body=f"A sign-in from {r['requested_ip'] or 'an unknown address'} is waiting for your fingerprint.",
                broadcast_type="action_required", created_by=0, created_at=r["created_at"],
                is_active=True, send_email=False, email_sent_at=None, ws_recipients=0,
                cta_url=f"/ui/#/pocket/approve-login?id={r['id']}", cta_label="Approve", requires_ack=False,
            ))
    except Exception:
        # The bell must never fail because a side feature is unavailable on this registry.
        logger.warning("[BELL] pending-confirmation merge skipped", exc_info=True)

    return items


class NotificationReadReceipt(BaseModel):
    """§bc3 T3.3 — per-user read-receipt + the broadcast itself.

    NO aggregate stats leaked (read_count is admin-only via the existing
    /admin/broadcasts/{id}/stats endpoint). This endpoint tells the calling
    developer EXACTLY two things: (1) is the broadcast read by THEM, (2)
    what's its current content."""
    read: bool
    read_at: Optional[datetime]
    broadcast: BroadcastOut


@router.get(
    "/notifications/{broadcast_id}",
    response_model=NotificationReadReceipt,
    summary="One broadcast with this developer's read receipt",
)
async def get_notification_with_receipt(
    broadcast_id: int,
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Per-user view of a single broadcast: whether THIS developer
    has read it + when. No aggregate stats."""
    r = await db.execute(
        select(models.AdminBroadcast).where(models.AdminBroadcast.id == broadcast_id)
    )
    broadcast = r.scalar_one_or_none()
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    if not broadcast.is_active:
        # Retracted broadcasts: only admins can see them. Devs get 404.
        raise HTTPException(status_code=404, detail="Broadcast not found")
    if not is_sent(broadcast) or not visible_to(broadcast, current_dev.id, await member_org_ids(db, current_dev.id)):
        # Another developer's notice, another organization's broadcast, or one not sent yet: the same 404 as a missing
        # id, so its existence is not disclosed.
        raise HTTPException(status_code=404, detail="Broadcast not found")
    r2 = await db.execute(
        select(models.DeveloperNotificationRead).where(
            and_(
                models.DeveloperNotificationRead.broadcast_id == broadcast_id,
                models.DeveloperNotificationRead.developer_id == current_dev.id,
            )
        )
    )
    read_row = r2.scalar_one_or_none()
    return NotificationReadReceipt(
        read=read_row is not None,
        read_at=read_row.read_at if read_row else None,
        broadcast=BroadcastOut.model_validate(broadcast),
    )


@router.post(
    "/notifications/{broadcast_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark a broadcast as read / dismissed",
)
@_RATE_LIMIT_DECORATOR  # §bc2 T2.6 — 60/minute per remote address
async def mark_notification_read(
    request: Request,   # required by slowapi to extract remote_address
    broadcast_id: int,
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    # Verify broadcast exists, and is not another developer's notice (same 404 either way)
    result = await db.execute(
        select(models.AdminBroadcast).where(models.AdminBroadcast.id == broadcast_id)
    )
    found = result.scalar_one_or_none()
    if not found or not visible_to(found, current_dev.id, await member_org_ids(db, current_dev.id)):
        raise HTTPException(status_code=404, detail="Broadcast not found")

    # Upsert read record
    existing = await db.execute(
        select(models.DeveloperNotificationRead).where(
            and_(
                models.DeveloperNotificationRead.broadcast_id == broadcast_id,
                models.DeveloperNotificationRead.developer_id == current_dev.id,
            )
        )
    )
    if not existing.scalar_one_or_none():
        row = models.DeveloperNotificationRead(
            broadcast_id=broadcast_id,
            developer_id=current_dev.id,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        # §bc3 T3.8 — cross-device read sync. Fire a targeted WS event to all
        # of THIS developer's other connections so they remove the item from
        # their bell/banner without a refresh. Audience `user_<id>` is
        # resolved by _local_broadcast's dynamic predicate (§bc3 T3.2b).
        try:
            await ws_manager.broadcast({
                "type": "developer.notification_read",
                "data": {
                    "broadcast_id": broadcast_id,
                    "developer_id": current_dev.id,
                    "read_at": row.read_at.isoformat() if row.read_at else None,
                },
            }, audience=f"user_{current_dev.id}", exclude_user=str(current_dev.id))
        except Exception as e:
            logger.debug(f"cross-device read sync emit failed for #{broadcast_id}: {e}")


# ---------------------------------------------------------------------------
# §bc3 T3.6 — saved broadcast templates (admin-scoped)
# ---------------------------------------------------------------------------

class BroadcastTemplateCreate(BaseModel):
    label: str = Field(..., max_length=80)
    title_template: str = Field(..., max_length=200)
    body_template: str = Field(..., min_length=1)
    broadcast_type: str = Field(default="info", pattern="^(info|warning|maintenance|critical)$")
    send_email: bool = False
    requires_ack: bool = False
    cta_url: Optional[str] = Field(default=None, max_length=500)
    cta_label: Optional[str] = Field(default=None, max_length=50)


class BroadcastTemplateOut(BaseModel):
    id: int
    created_by: int
    label: str
    title_template: str
    body_template: str
    broadcast_type: str
    send_email: bool
    requires_ack: bool
    cta_url: Optional[str]
    cta_label: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get(
    "/admin/broadcast-templates",
    response_model=List[BroadcastTemplateOut],
    summary="§bc3 T3.6 — list current admin's saved compose templates",
)
async def list_broadcast_templates(
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(models.AdminBroadcastTemplate)
        .where(models.AdminBroadcastTemplate.created_by == current_admin.id)
        .order_by(models.AdminBroadcastTemplate.created_at.desc())
        .limit(50)
    )
    return r.scalars().all()


@router.post(
    "/admin/broadcast-templates",
    response_model=BroadcastTemplateOut,
    status_code=status.HTTP_201_CREATED,
    summary="§bc3 T3.6 — save a new compose template",
)
async def create_broadcast_template(
    payload: BroadcastTemplateCreate,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    row = models.AdminBroadcastTemplate(
        created_by=current_admin.id,
        label=payload.label,
        title_template=payload.title_template,
        body_template=payload.body_template,
        broadcast_type=payload.broadcast_type,
        send_email=payload.send_email,
        requires_ack=payload.requires_ack,
        cta_url=payload.cta_url,
        cta_label=payload.cta_label,
    )
    db.add(row)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        # 23505 = UNIQUE violation on (created_by, label)
        raise HTTPException(status_code=409, detail=f"Template label already exists: {payload.label}")
    await db.refresh(row)
    return row


@router.delete(
    "/admin/broadcast-templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="§bc3 T3.6 — delete a saved template (owner only)",
)
async def delete_broadcast_template(
    template_id: int,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(models.AdminBroadcastTemplate).where(
            models.AdminBroadcastTemplate.id == template_id
        )
    )
    row = r.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    if row.created_by != current_admin.id:
        raise HTTPException(status_code=403, detail="Cannot delete another admin's template")
    await db.delete(row)
    await db.commit()


# ---------------------------------------------------------------------------
# §bc3 T3.2 — per-developer notification preferences
# ---------------------------------------------------------------------------

# Default preferences for a developer who has never set any. Reader code MUST
# tolerate unknown keys (forward-compat) and missing keys (back-compat).
DEFAULT_NOTIFICATION_PREFS = {
    "prefs_version": 1,
    # Mute toggles. mute_critical is intentionally NOT in this dict — critical
    # is always delivered (you can't opt out of "your account is suspended").
    "mute_info": False,
    "mute_warning": False,
    "mute_maintenance": False,
    # Delivery channels (in-app = WS + bell + toast + banner). Email defaults
    # to on for the broadcast email path; PATCH can flip to off.
    "delivery_in_app": True,
    "delivery_email": True,
    # Quiet hours (local hours 0-23) — within this window, broadcasts skip
    # the WS+toast path but still hit /unread (admin can review on next login).
    # Both nulls = no quiet hours.
    "quiet_hours_start": None,
    "quiet_hours_end": None,
}


class NotificationPrefsUpdate(BaseModel):
    """PATCH body for /developers/me/notification-prefs.

    All fields optional — only the keys present in the request body are
    overwritten. Unknown keys are stored unchanged so future versions can
    ship new toggles without a backend change.
    """
    mute_info: Optional[bool] = None
    mute_warning: Optional[bool] = None
    mute_maintenance: Optional[bool] = None
    delivery_in_app: Optional[bool] = None
    delivery_email: Optional[bool] = None
    quiet_hours_start: Optional[int] = Field(default=None, ge=0, le=23)
    quiet_hours_end: Optional[int] = Field(default=None, ge=0, le=23)


@router.get(
    "/developers/me/notification-prefs",
    summary="Read this developer's notification preferences",
)
async def get_notification_prefs(
    current_dev: models.Developer = Depends(security.get_current_developer),
):
    """Returns the calling developer's prefs merged with defaults so the UI
    always has a complete object to bind to."""
    return {**DEFAULT_NOTIFICATION_PREFS, **(current_dev.notification_prefs or {})}


@router.patch(
    "/developers/me/notification-prefs",
    summary="Update this developer's notification preferences",
)
async def patch_notification_prefs(
    payload: NotificationPrefsUpdate,
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Partial-update: only the fields present in the body are touched.
    Unknown fields in the existing JSON are preserved (forward-compat).
    Invalidates the Redis cache (`dev_prefs:{id}`) so next broadcast respects
    the new prefs immediately."""
    existing = current_dev.notification_prefs or {}
    patch = payload.model_dump(exclude_unset=True)
    merged = {**existing, **patch}
    # Pin prefs_version so reader knows what shape to expect
    merged["prefs_version"] = max(int(merged.get("prefs_version", 1)), 1)
    current_dev.notification_prefs = merged
    await db.commit()
    # §bc3 T3.2 — invalidate Redis cache so the next broadcast respects this
    # immediately rather than waiting up to 60s for TTL.
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is not None:
            await r.delete(f"dev_prefs:{current_dev.id}")
    except Exception as e:
        logger.debug(f"dev_prefs cache invalidation skipped: {e}")
    return {**DEFAULT_NOTIFICATION_PREFS, **merged}


# ---------------------------------------------------------------------------
# §bc2 — worker status endpoints (admin observability)
# ---------------------------------------------------------------------------

@router.get(
    "/admin/broadcast-scheduler/status",
    summary="§bc2 — broadcast_scheduler worker snapshot",
)
async def broadcast_scheduler_status(
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Snapshot of the scheduled-broadcast firing worker. Powers the
    `/admin/broadcast-scheduler` admin modal (Tier-3 observability)."""
    from agentvault_registry.background_tasks.broadcast_scheduler import get_broadcast_scheduler
    return get_broadcast_scheduler().snapshot()


@router.get(
    "/admin/broadcast-email-retry/status",
    summary="§bc2 — broadcast_email_retry worker snapshot",
)
async def broadcast_email_retry_status(
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Snapshot of the per-batch email retry worker. Powers the
    `/admin/broadcast-email-retry` admin modal (Tier-3 observability)."""
    from agentvault_registry.background_tasks.broadcast_email_retry_worker import (
        get_broadcast_email_retry_worker,
    )
    return get_broadcast_email_retry_worker().snapshot()


@router.get(
    "/admin/broadcast-email-retry/dead-letter",
    summary="§bc2 — list dead-lettered broadcast email batches",
)
async def broadcast_email_dead_letter(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=500),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
    db: AsyncSession = Depends(get_db),
):
    """Audit-grade list of every broadcast batch the retry worker gave up on.
    The operator decides what to do: manual resend, write off, etc."""
    r = await db.execute(text("""
        SELECT id, broadcast_id, batch_index, retry_count, error_reason,
               created_at, last_retry_at, dead_letter_at
        FROM broadcast_email_failed
        WHERE dead_letter_at IS NOT NULL
        ORDER BY dead_letter_at DESC
        OFFSET :skip LIMIT :limit
    """), {"skip": skip, "limit": limit})
    rows = []
    for row in r.fetchall():
        rows.append({
            "id": row[0],
            "broadcast_id": row[1],
            "batch_index": row[2],
            "retry_count": row[3],
            "error_reason": row[4],
            "created_at": row[5].isoformat() if row[5] else None,
            "last_retry_at": row[6].isoformat() if row[6] else None,
            "dead_letter_at": row[7].isoformat() if row[7] else None,
        })
    return {"items": rows, "skip": skip, "limit": limit}


# ---------------------------------------------------------------------------
# Public / developer-accessible endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/community/announcements",
    response_model=List[BroadcastOut],
    summary="List active broadcasts for the community page (developer auth)",
)
async def list_community_announcements(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, le=50),
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """
    The active broadcasts the caller may see, newest first, for the Community Hub page: the bell's audience (untargeted,
    the caller's organizations, the caller's own notices) and only once sent, read or not.

    \f
    §SECFIX D6-212 (2026-10-16): this listed EVERY active broadcast to every signed-in developer, another developer's
    direct notice and another organization's broadcast included, and broadcasts scheduled for later before they went
    out. It asks the bell's rule now (audience_clause, sent_clause).
    """
    org_ids = await member_org_ids(db, current_dev.id)
    query = (
        select(models.AdminBroadcast)
        .where(
            models.AdminBroadcast.is_active == True,  # noqa: E712
            sent_clause(),
            audience_clause(current_dev.id, org_ids),
        )
        .order_by(models.AdminBroadcast.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Email helper (Phase 2)
# ---------------------------------------------------------------------------

async def _send_broadcast_email(broadcast: models.AdminBroadcast, db: AsyncSession):
    """Send themed broadcast email to all verified developers.

    Theme is sovereign for warning/critical broadcasts (so the From: header reads
    `TheProtocol Security`), neural for info/maintenance.
    """
    from agentvault_registry.email_utils import send_themed_email

    # §9 (2026-07-27) — DEFECT FIX. This used to select EVERY verified developer with no
    # preference filter at all: `delivery_email` and the mute_info/mute_warning/mute_maintenance
    # toggles were honoured by the WebSocket in-app gate (websocket.py builds the key
    # dynamically as `mute_{type}`) but were silently ignored for EMAIL, so a developer who
    # switched broadcast email off kept receiving it. Now the recipient list goes through the
    # SAME v2 resolver as every other notification, which also means the panel's per-type
    # switches finally govern this path.
    #
    # broadcast.critical is mandatory, so decide() short-circuits it to True — an ACTION
    # REQUIRED announcement stays unmutable, by design.
    # §NIGHTLYTRUTH-2 (2026-10-11): never a deleted account (an admin delete keeps the row's address for its audit) and
    # never a federation placeholder (a synthetic `<peer>.federation` address): services/developer_population.py
    # §SECFIX D6-305 (2026-10-16): and only the broadcast's audience (email_audience_clause). An organization's broadcast
    # with send_email went to every verified developer of the registry; it reaches that organization's members now.
    result = await db.execute(
        select(models.Developer.id, models.Developer.email).where(
            models.Developer.is_verified == True, a_developer_of_this_registry(), email_audience_clause(broadcast)
        )
    )
    all_devs = [(did, em) for (did, em) in result.fetchall() if em]
    emails: List[str] = []
    try:
        from agentvault_registry.services import notification_prefs as _np
        from agentvault_registry.services.notification_catalog import get_type as _get_type

        _entry = _get_type(f"broadcast.{broadcast.broadcast_type}")
        if _entry is None:
            emails = [em for (_d, em) in all_devs]  # unknown severity → never silently drop mail
        else:
            _ctxs = await _np.load_context([d for (d, _e) in all_devs], _entry.key)
            for _did, _em in all_devs:
                _ctx = _ctxs.get(_did) or _np.DevCtx(dev_id=_did)
                _send, _reason, _ = _np.decide(
                    _entry, "email", ctx=_ctx, device_prefs=None, amount=None,
                )
                if _send:
                    emails.append(_em)
        logger.info(
            "[Broadcast] email recipients after v2 prefs: %d of %d verified",
            len(emails), len(all_devs),
        )
    except Exception as exc:  # noqa: BLE001
        # Fail OPEN: a resolver hiccup must not silence an admin broadcast. Same posture as the
        # rest of the notification stack, and the pre-existing behaviour was "email everyone".
        logger.warning("[Broadcast] pref filter failed, emailing all verified: %s", exc)
        emails = [em for (_d, em) in all_devs]

    if not emails:
        logger.info("No verified developers to email (after preference filter)")
        return

    type_labels = {
        "info": "INFO",
        "warning": "WARNING",
        "maintenance": "MAINTENANCE NOTICE",
        "critical": "ACTION REQUIRED",
    }
    subject_prefix = type_labels.get(broadcast.broadcast_type, "NOTICE")
    theme = "sovereign" if broadcast.broadcast_type in ("warning", "critical") else "neural"

    # Resolve email -> developer_id mapping for failure capture (the recipients' own rows: every batch is drawn from them).
    email_to_did = {e: did for (did, e) in all_devs}

    # §bc2 T2.5 — per-batch try/except so one bad batch doesn't cancel the rest.
    # Failed batches insert a `broadcast_email_failed` row for retry_worker.
    batch_size = 50
    for batch_index, i in enumerate(range(0, len(emails), batch_size)):
        batch = emails[i:i + batch_size]
        try:
            ok = await send_themed_email(
                subject=f"[TheProtocol] {subject_prefix}: {broadcast.title}",
                recipients=batch,
                template="broadcast_notification",
                context={
                    "title": broadcast.title,
                    "body": broadcast.body,
                    "broadcast_type": broadcast.broadcast_type,
                    "type_label": subject_prefix,
                    "cta_url": broadcast.cta_url,
                    "cta_label": broadcast.cta_label,
                },
                theme=theme,
            )
            err: Optional[str] = None if ok else "send_themed_email returned False"
        except Exception as e:
            ok = False
            err = str(e)[:480]

        if ok:
            logger.info(f"Broadcast email batch sent ({theme}): {len(batch)} recipients")
        else:
            logger.error(
                f"Broadcast email batch FAILED ({theme}, batch_index={batch_index}, "
                f"recipients={len(batch)}): {err}"
            )
            # Insert a retry row so broadcast_email_retry_worker.py picks it up.
            try:
                dev_ids = [email_to_did[e] for e in batch if e in email_to_did]
                db.add(models.BroadcastEmailFailed(
                    broadcast_id=broadcast.id,
                    batch_index=batch_index,
                    developer_ids_json=dev_ids,
                    error_reason=err,
                ))
                await db.commit()
            except Exception as insert_err:
                logger.error(
                    f"Could not persist broadcast_email_failed for #{broadcast.id} "
                    f"batch {batch_index}: {insert_err}"
                )
