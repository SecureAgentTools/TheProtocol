"""
Support Ticket System — f042

Developer endpoints (authenticated developer):
  POST   /api/v1/support/tickets          — create ticket (with first message)
  GET    /api/v1/support/tickets          — list my tickets
  GET    /api/v1/support/tickets/{id}     — get ticket detail + messages
  POST   /api/v1/support/tickets/{id}/reply — add reply

Admin endpoints (admin_support flag required):
  GET    /api/v1/admin/support/tickets/stats     — counts by status, WHOLE table (§S7)
  GET    /api/v1/admin/support/tickets           — list ALL tickets (status/priority/category/offset)
  GET    /api/v1/admin/support/tickets/{id}      — read ANY ticket (§S1)
  POST   /api/v1/admin/support/tickets/{id}/reply  — admin reply + notify owner
  POST   /api/v1/admin/support/tickets/{id}/status — change ticket status
  POST   /api/v1/admin/support/tickets/{id}/triage — set priority / category (§S12)

⚠ Both `/stats` routes are declared ABOVE their `{ticket_id}` siblings. FastAPI
matches in registration order and `{ticket_id}` is an int, so declaring them
below would make them unreachable behind a 422 (the §NOTIFV2 trap).

Every mutation emits a `support.ticket` WS cue to `user_<owner>` AND to
`admin_support`, cross-worker through Redis (§S6).
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query, Security
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sa_func
from sqlalchemy.orm import selectinload

from agentvault_registry import models, security
from agentvault_registry.database import get_db
from agentvault_registry.routers.websocket import manager as ws_manager
from agentvault_registry.core.client_ip import effective_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Support"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

# §FESUITE (CLAUDE.md §DIRFEED-2): a page keyed on a column that is not unique is not a partition. Two tickets touched
# in the same instant could be ordered differently by two OFFSET plans, so one shows on both pages and one on neither.
# The id breaks every tie; both ticket lists (the owner's and the desk's) page on this order.
TICKET_PAGE_ORDER = (models.SupportTicket.updated_at.desc(), models.SupportTicket.id.desc())


class TicketCreate(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    category: str = Field(default="general", pattern="^(bug|question|feature|account|general)$")
    message: str = Field(..., min_length=1)
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")


class TicketReply(BaseModel):
    message: str = Field(..., min_length=1)


class TicketStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(open|in_progress|resolved|closed)$")


class OwnerStatusUpdate(BaseModel):
    """§S2 — what the TICKET OWNER may set.

    Deliberately NOT `TicketStatusUpdate`: a customer can say *closed* ("I am
    done with this") and *open* ("no, I am not"), and those are the only two
    sentences they are entitled to. **`resolved` is the desk's verdict about the
    WORK** — letting the person who filed the ticket mark it resolved collapses
    two different statements into one, and the queue stops meaning anything.

    The field is a bare `str` rather than a pattern so the refusal can NAME the
    distinction; a pattern would 422 at pydantic with a regex nobody can read
    (the §29k class: a request that fails validation never reaches the gate you
    are actually testing).
    """
    status: str = Field(..., min_length=1, max_length=32)


class TicketTriageUpdate(BaseModel):
    """§S12 — what the DESK may re-decide about a ticket it did not file.

    Priority and category are set by the CUSTOMER at creation and, until now,
    by nobody ever again. The admin queue has offered filters on both fields
    since it was written (`adminFilterPriority`, `adminFilterCategory`), so the
    desk could sort by two values it had no way to set: a triage view with no
    triage. A customer who marks everything urgent could not be corrected, and
    a ticket filed under the wrong category stayed there.

    Both fields are optional and at least one must be present — a PATCH-shaped
    body, so re-categorising does not silently re-assert a priority the caller
    never mentioned (the read-modify-write class that nearly deleted an
    11-entry allowlist in §V0193).
    """
    priority: Optional[str] = Field(default=None, pattern="^(low|normal|high|urgent)$")
    category: Optional[str] = Field(default=None, pattern="^(bug|question|feature|account|general)$")


class TicketCounts(BaseModel):
    """§S7 — the status buckets, counted in the database rather than in a browser."""
    total: int = 0
    open: int = 0
    in_progress: int = 0
    resolved: int = 0
    closed: int = 0


class MessageOut(BaseModel):
    id: int
    ticket_id: int
    sender_type: str
    sender_name: Optional[str]
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TicketOut(BaseModel):
    id: int
    developer_id: int
    subject: str
    category: str
    status: str
    priority: str
    created_at: datetime
    updated_at: datetime
    messages: List[MessageOut] = []

    model_config = {"from_attributes": True}


class TicketListItem(BaseModel):
    id: int
    subject: str
    category: str
    status: str
    priority: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    last_message_preview: Optional[str] = None
    last_message_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AdminTicketListItem(TicketListItem):
    developer_id: int
    developer_email: Optional[str] = None
    developer_name: Optional[str] = None


class AdminTicketOut(TicketOut):
    """§S1 — the admin's view of ONE ticket, which did not exist.

    Same body as `TicketOut` plus who filed it, because an admin reading a queue
    entry needs to know whose problem it is — and because the client decides
    which reply rail to use by comparing `developer_id` to itself (§S5).
    """
    developer_email: Optional[str] = None
    developer_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _mirror(coro_fn, *args, **kwargs):
    """Run one chat mirror, swallowing anything it raises.

    §OURSTATE-7 D — a ticket that was answered and did not mirror is a display
    bug; a reply that 500s because the mirror broke is a support outage. The
    ticket is committed before any of these run, so the worst case is a thread
    that catches up on the next message.
    """
    try:
        return await coro_fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 — deliberate: support must not depend on chat
        logger.warning(f"support→chat mirror failed: {e}")
        return None


async def _thread_click(db: AsyncSession, ticket_id: int) -> str:
    """Where a support notification LANDS.

    §OURSTATE-7 D moves the primary door to the thread — that is the point of
    the batch: the answer arrives where the person already reads. The settings
    tab stays the fallback, so a ticket whose thread was never opened (or whose
    mirror failed) still has somewhere to go rather than a dead link.
    """
    try:
        from agentvault_registry.models import Conversation
        from agentvault_registry.services.chat_support import support_pair_key
        row = (await db.execute(
            select(Conversation.id).where(
                Conversation.dm_pair_key == support_pair_key(int(ticket_id))))).first()
        if row and row[0]:
            return f"/ui#/pocket/ourchat/{row[0]}"
    except Exception as e:  # noqa: BLE001
        logger.debug(f"support thread lookup for click target failed: {e}")
    return f"/ui#/settings?tab=support&ticket={ticket_id}"


async def _send_ticket_notification(
    db: AsyncSession,
    admin_id: int,
    developer_id: int,
    ticket_id: int,
    title: str,
    body: str,
):
    """Notify the TICKET OWNER — and only them — about a ticket event.

    §OURSTATE-2 fix: this used to create an AdminBroadcast row (visible to
    EVERY developer) and `ws_manager.broadcast` (delivered to EVERY connected
    user) despite its "targeted" docstring. Now it rides the typed notify()
    rail (per-developer row + prefs) plus a personal WS push to the owner.
    `admin_id` stays in the signature for the existing call sites.
    """
    _ = admin_id
    click = await _thread_click(db, ticket_id)
    try:
        from agentvault_registry.background_tasks.push_notify import notify
        await notify(
            "support.reply", [int(developer_id)],
            title=title, message=body, click=click)
    except Exception as e:
        logger.error(f"notify() failed for ticket #{ticket_id}: {e}")
    try:
        await ws_manager.send_personal_message({
            "type": "notification",
            "data": {"title": title, "message": body,
                     "type": "info", "ticket_id": ticket_id},
        }, str(developer_id))
    except Exception as e:
        logger.debug(f"Personal WS push failed for ticket #{ticket_id}: {e}")
    logger.info(f"Ticket notification sent to dev {developer_id}: '{title}' for ticket #{ticket_id}")


def _ticket_to_list_item(ticket: models.SupportTicket, include_dev: bool = False):
    """Convert a ticket ORM object to a list item dict."""
    messages = ticket.messages or []
    last_msg = messages[-1] if messages else None
    data = {
        "id": ticket.id,
        "subject": ticket.subject,
        "category": ticket.category,
        "status": ticket.status,
        "priority": ticket.priority,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "message_count": len(messages),
        "last_message_preview": (last_msg.message[:120] + "...") if last_msg and len(last_msg.message) > 120 else (last_msg.message if last_msg else None),
        "last_message_at": last_msg.created_at if last_msg else None,
    }
    if include_dev:
        data["developer_id"] = ticket.developer_id
        dev = ticket.developer
        data["developer_email"] = dev.email if dev else None
        data["developer_name"] = dev.display_name or dev.name if dev else None
    return data


async def _emit_support_event(ticket: models.SupportTicket, event: str) -> None:
    """§S6 — tell BOTH sides of the desk that a ticket moved, across workers.

    The queue never refreshed because nothing ever told it to. The backlog
    recorded that as *"the signal exists, nobody listens to it"*. Measuring it
    found that half true and the other half worse:

    * **The owner's signal mostly would not have arrived.** It was
      `ws_manager.send_personal_message`, which reads `self.active_connections`
      — a PER-WORKER dict (`websocket.py:310`). registry-a runs 38 gunicorn
      workers, so a push fired by whichever worker handled the admin's reply
      reached the owner only when the owner's socket happened to live on that
      same worker. Wiring the view to it would have produced a refresh that
      works about one time in thirty-eight, which reads as a flaky UI rather
      than a missing one and is therefore harder to diagnose than silence.
    * **The admin had no signal at all.** `_send_ticket_notification` notifies
      the ticket OWNER and only them, deliberately. Nothing has ever told a
      desk that a customer wrote in.

    `broadcast()` publishes through Redis Pub/Sub, so every worker's listener
    delivers to its own connections. Both audience predicates already existed
    (`websocket.py:90-99`): `user_<id>` is resolved dynamically and
    `admin_support` is `is_admin OR admin_support`.

    ⚠ **The type is `support.ticket`, deliberately NOT `notification`.**
    `_local_broadcast` applies the per-developer prefs filter and quiet hours
    ONLY to `type == "notification"`. This carries no words for a human — it is
    a cue to re-read a list — so muting your support notifications must not
    freeze your ticket queue. The bell keeps riding `notify()`; this is the
    view's cue and nothing else.

    ⚠ On a single-operator registry the owner IS the admin, so both audiences
    resolve to the same socket and the view is cued twice for one event. A
    refresh is idempotent so that costs a wasted fetch, not correctness — but
    the client still has to be written so two cues cannot interleave into a
    stale render.

    Best-effort by construction: immediacy is not correctness here, and a
    refresh cue must never fail the write that earned it.
    """
    payload = {
        "type": "support.ticket",
        "data": {
            "ticket_id": int(ticket.id),
            "event": event,
            "status": ticket.status,
            "priority": ticket.priority,
            "category": ticket.category,
            "developer_id": int(ticket.developer_id),
        },
    }
    for audience in (f"user_{ticket.developer_id}", "admin_support"):
        try:
            await ws_manager.broadcast(dict(payload), audience=audience)
        except Exception as e:  # noqa: BLE001
            logger.debug("[SUPPORT] WS cue to %s failed for ticket #%s: %s",
                         audience, ticket.id, e)


async def _ticket_counts(db: AsyncSession, developer_id: Optional[int] = None) -> dict:
    """§S7 — the four status buckets, counted in the DATABASE.

    `ticketStats` was `tickets.value.filter(...)` over whatever the browser had
    loaded, which was only ever right because the list loaded everything.
    Paginating without moving the counters would have turned *"the numbers are
    wrong past 200 tickets"* into *"the numbers describe page one"* — the same
    lie with better manners. One grouped count over the whole table.

    ⚠ The dict is seeded with all four buckets at 0 before the rows are folded
    in, so a status with no tickets reports 0 rather than going missing and
    rendering as blank.
    """
    q = (select(models.SupportTicket.status, sa_func.count())
         .group_by(models.SupportTicket.status))
    if developer_id is not None:
        q = q.where(models.SupportTicket.developer_id == developer_id)
    counts = {"open": 0, "in_progress": 0, "resolved": 0, "closed": 0}
    total = 0
    for st, n in (await db.execute(q)).all():
        total += int(n)
        if st in counts:
            counts[st] = int(n)
    return {"total": total, **counts}


# ---------------------------------------------------------------------------
# Developer endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/api/v1/support/tickets/stats",
    response_model=TicketCounts,
    summary="Counts of my tickets by status",
)
async def my_ticket_stats(
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """
    Counts of the calling developer's support tickets by status.

    \f
    ⚠ **REGISTERED ABOVE `/support/tickets/{ticket_id}` ON PURPOSE.**

    FastAPI matches in REGISTRATION order, never by path specificity, and
    `{ticket_id}` is typed `int`. Declared below it this route would be
    unreachable: `/support/tickets/stats` would bind `ticket_id="stats"` and
    422 with *"unable to parse string as an integer"* — the exact trap that
    swallowed `/notifications/catalog` in §NOTIFV2. Do not move it down.
    """
    return await _ticket_counts(db, developer_id=current_dev.id)


@router.post(
    "/api/v1/support/tickets",
    response_model=TicketOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a support ticket",
)
async def create_ticket(
    payload: TicketCreate,
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Create a new support ticket with the first message."""
    ticket = models.SupportTicket(
        developer_id=current_dev.id,
        subject=payload.subject,
        category=payload.category,
        priority=payload.priority,
        status="open",
    )
    db.add(ticket)
    await db.flush()

    # Add the first message
    message = models.SupportMessage(
        ticket_id=ticket.id,
        sender_type="user",
        sender_name=current_dev.display_name or current_dev.name or current_dev.email,
        message=payload.message,
    )
    db.add(message)
    await db.commit()

    # §OURSTATE-7 D — the thread opens with the ticket, so the first reply has
    # somewhere to land. AFTER the commit: the ticket is the authority.
    from agentvault_registry.services import chat_support
    await _mirror(chat_support.mirror_user_message, db, ticket, payload.message)
    # §S6 — a new ticket is the one event the desk had NO way of hearing about.
    await _emit_support_event(ticket, "created")

    # Reload with messages
    result = await db.execute(
        select(models.SupportTicket)
        .where(models.SupportTicket.id == ticket.id)
        .options(selectinload(models.SupportTicket.messages))
    )
    ticket = result.scalar_one()
    return ticket


@router.get(
    "/api/v1/support/tickets",
    response_model=List[TicketListItem],
    summary="List my support tickets",
)
async def list_my_tickets(
    ticket_status: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """List the current developer's support tickets."""
    query = (
        select(models.SupportTicket)
        .where(models.SupportTicket.developer_id == current_dev.id)
        .options(selectinload(models.SupportTicket.messages))
        .order_by(*TICKET_PAGE_ORDER)
    )
    if ticket_status:
        query = query.where(models.SupportTicket.status == ticket_status)
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    tickets = result.scalars().all()
    return [_ticket_to_list_item(t) for t in tickets]


@router.get(
    "/api/v1/support/tickets/{ticket_id}",
    response_model=TicketOut,
    summary="Get ticket detail with all messages",
)
async def get_ticket(
    ticket_id: int,
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Get a support ticket with all messages. Only own tickets."""
    result = await db.execute(
        select(models.SupportTicket)
        .where(
            models.SupportTicket.id == ticket_id,
            models.SupportTicket.developer_id == current_dev.id,
        )
        .options(selectinload(models.SupportTicket.messages))
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@router.post(
    "/api/v1/support/tickets/{ticket_id}/reply",
    response_model=TicketOut,
    summary="Reply to a support ticket",
)
async def reply_to_ticket(
    ticket_id: int,
    payload: TicketReply,
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Add a reply message to a ticket. Only own tickets. Reopens resolved/closed tickets."""
    result = await db.execute(
        select(models.SupportTicket)
        .where(
            models.SupportTicket.id == ticket_id,
            models.SupportTicket.developer_id == current_dev.id,
        )
        .options(selectinload(models.SupportTicket.messages))
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    await add_developer_reply(db, ticket, current_dev, payload.message)

    # Reload
    result = await db.execute(
        select(models.SupportTicket)
        .where(models.SupportTicket.id == ticket.id)
        .options(selectinload(models.SupportTicket.messages))
    )
    return result.scalar_one()


async def add_developer_reply(db: AsyncSession, ticket: models.SupportTicket,
                              dev: models.Developer, text: str) -> None:
    """THE developer-side reply writer. Commits, then mirrors.

    §OURSTATE-7 D factored this out of the route so the chat composer's
    `/chat/conversations/{id}/support-reply` door writes through exactly the
    same code — one writer for the ticket, whichever surface the words were
    typed on. A second copy is how the thread and the ticket start disagreeing
    about what was said (the §FANOUTFIX class).
    """
    db.add(models.SupportMessage(
        ticket_id=ticket.id,
        sender_type="user",
        sender_name=dev.display_name or dev.name or dev.email,
        message=text,
    ))
    # Replying reopens a resolved/closed ticket — the ticket rail's rule, kept
    # here rather than re-decided by chat.
    if ticket.status in ("resolved", "closed"):
        ticket.status = "open"
    await db.commit()

    from agentvault_registry.services import chat_support
    await _mirror(chat_support.mirror_user_message, db, ticket, text)
    # §S6 — emitted from THE writer, not from the route, so a reply typed in the
    # chat composer cues the queue exactly like one typed in the ticket view.
    # A second emit at the route would have covered one surface and quietly
    # missed the other (the §FANOUTFIX class: two sites asking one question).
    await _emit_support_event(ticket, "reply")


@router.post(
    "/api/v1/support/tickets/{ticket_id}/status",
    response_model=TicketOut,
    summary="Close or reopen your own ticket",
)
async def set_my_ticket_status(
    ticket_id: int,
    payload: OwnerStatusUpdate,
    current_dev: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """
    The owner closes or reopens their own ticket. Only those two states can be set here; any other status is
    refused.

    \f
    §S2 — the owner ends their own ticket.

    Until now the only way a ticket ever ended was an admin ending it: there was
    no developer-facing status route at all, so a person who had solved their own
    problem could do nothing but leave it open forever. His report, verbatim:
    *"cant close ticket"*.

    Two states, and the refusal for the third is the point — see
    `OwnerStatusUpdate`.
    """
    result = await db.execute(
        select(models.SupportTicket)
        .where(
            models.SupportTicket.id == ticket_id,
            models.SupportTicket.developer_id == current_dev.id,
        )
        .options(selectinload(models.SupportTicket.messages))
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    wanted = str(payload.status or "").strip().lower()
    if wanted in ("resolved", "in_progress"):
        raise HTTPException(
            status_code=409,
            detail=("'resolved' is the support team's verdict about the work. "
                    "You can close this ticket, or reopen it."),
        )
    if wanted not in ("open", "closed"):
        raise HTTPException(
            status_code=422,
            detail="status must be 'closed' or 'open'",
        )

    old_status = ticket.status
    ticket.status = wanted
    await db.commit()

    # The thread and the ticket must agree about state, whichever side moved it.
    if old_status != wanted:
        from agentvault_registry.services import chat_support
        await _mirror(chat_support.mirror_status, db, ticket, old_status, wanted,
                      by_name=current_dev.display_name or current_dev.name or "You")
    await _emit_support_event(ticket, "status")

    result = await db.execute(
        select(models.SupportTicket)
        .where(models.SupportTicket.id == ticket.id)
        .options(selectinload(models.SupportTicket.messages))
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/api/v1/admin/support/tickets/stats",
    response_model=TicketCounts,
    summary="Counts of ALL tickets by status (admin)",
)
async def admin_ticket_stats(
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    """⚠ Same registration-order rule as `my_ticket_stats` — this must stay
    above `/api/v1/admin/support/tickets/{ticket_id}`."""
    return await _ticket_counts(db)


@router.get(
    "/api/v1/admin/support/tickets",
    response_model=List[AdminTicketListItem],
    summary="List all support tickets (admin)",
)
async def admin_list_tickets(
    ticket_status: Optional[str] = Query(default=None, alias="status"),
    priority: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    """List all support tickets with filters. Admin only."""
    query = (
        select(models.SupportTicket)
        .options(
            selectinload(models.SupportTicket.messages),
            selectinload(models.SupportTicket.developer),
        )
        .order_by(*TICKET_PAGE_ORDER)
    )
    if ticket_status:
        query = query.where(models.SupportTicket.status == ticket_status)
    if priority:
        query = query.where(models.SupportTicket.priority == priority)
    if category:
        query = query.where(models.SupportTicket.category == category)
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    tickets = result.scalars().all()
    return [_ticket_to_list_item(t, include_dev=True) for t in tickets]


@router.get(
    "/api/v1/admin/support/tickets/{ticket_id}",
    response_model=AdminTicketOut,
    summary="Get any ticket with all messages (admin)",
)
async def admin_get_ticket(
    ticket_id: int,
    request: Request,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    """§S1 — THE ADMIN QUEUE WAS A LIST OF TICKETS YOU COULD NOT OPEN.

    `GET /api/v1/admin/support/tickets` has always listed every ticket, but no
    admin route ever existed to READ one, so `SupportView.loadTicketDetail()`
    fell back to the developer route — which filters `developer_id == me`.
    Measured in a browser: an admin clicking any customer's ticket got
    `404 Ticket not found` and stayed on the list. Because the status controls
    live INSIDE the detail view, this also presented as *"cant close ticket"*.

    ⚠ It survived because it is invisible to a one-account test: when the admin
    OWNS the ticket, the developer route answers 200 and everything looks fine.
    Every check that reads `developer_id == me` passes for the wrong reason.
    """
    result = await db.execute(
        select(models.SupportTicket)
        .where(models.SupportTicket.id == ticket_id)
        .options(
            selectinload(models.SupportTicket.messages),
            selectinload(models.SupportTicket.developer),
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # §ADMINDESK (2026-08-29) — the participant lane becomes as auditable as the
    # consent lane. `admin_review_messages` has written a row per read since
    # §CHATDESK C4; THIS route (the full customer transcript) never did, so
    # "which admin read which customer's thread, when" was answerable for
    # granted DMs but not for the desk's own queue. One row per detail open,
    # stored as `admin.chatdesk.thread_read` (the `admin.` prefix is added by
    # log_admin_action — the §V0177 trap). Best-effort like its siblings: an
    # audit failure logs loudly but never blocks the desk.
    try:
        from agentvault_registry.services.admin_audit import log_admin_action
        await log_admin_action(
            db,
            action="chatdesk.thread_read",
            actor_id=str(current_admin.id),
            actor_ip=effective_client_ip(request),
            target_type="support_ticket",
            target_id=str(ticket.id),
            details={"developer_id": ticket.developer_id,
                     "messages": len(ticket.messages or [])},
        )
    except Exception as e:  # noqa: BLE001
        logger.error("[CHATDESK] thread_read audit row failed for ticket #%s: %s", ticket_id, e)

    dev = ticket.developer
    out = AdminTicketOut.model_validate(ticket)
    out.developer_email = dev.email if dev else None
    out.developer_name = (dev.display_name or dev.name) if dev else None
    return out


@router.post(
    "/api/v1/admin/support/tickets/{ticket_id}/reply",
    response_model=TicketOut,
    summary="Admin reply to a support ticket",
)
async def admin_reply_to_ticket(
    ticket_id: int,
    payload: TicketReply,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin reply to a support ticket.
    Sets status to 'in_progress' if currently 'open'.
    Sends a broadcast notification to the developer.
    """
    result = await db.execute(
        select(models.SupportTicket)
        .where(models.SupportTicket.id == ticket_id)
        .options(selectinload(models.SupportTicket.messages))
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Add admin message.
    # §ORGMARKET S4 (2026-08-29, privacy-preserving default): the desk label is
    # the admin's CHOSEN display_name or the role label "Support" — the account
    # NAME never auto-reaches a customer. An admin who wants their name on
    # replies sets display_name in their own profile; one-line reversible.
    desk_name = current_admin.display_name or "Support"
    message = models.SupportMessage(
        ticket_id=ticket.id,
        sender_type="admin",
        sender_name=desk_name,
        message=payload.message,
    )
    db.add(message)

    # Auto-progress from open to in_progress
    auto_progressed = False
    if ticket.status == "open":
        ticket.status = "in_progress"
        auto_progressed = True

    await db.commit()

    # §OURSTATE-7 D — mirror FIRST, then notify: the notification's click
    # target is the thread, and a link that resolves before the thread exists
    # would land the owner on an empty page.
    from agentvault_registry.services import chat_support
    # §ORGMARKET S11 — the AUTO status move writes the SAME visible system row
    # an explicit change writes (it used to happen silently, so the owner saw
    # the ticket flip state with nothing in the trail saying when or why).
    if auto_progressed:
        await _mirror(chat_support.mirror_status, db, ticket, "open", "in_progress",
                      by_name=desk_name)
    await _mirror(chat_support.mirror_desk_message, db, ticket, desk_name, payload.message)

    await _send_ticket_notification(
        db=db,
        admin_id=current_admin.id,
        developer_id=ticket.developer_id,
        ticket_id=ticket.id,
        title=f"Support Ticket #{ticket.id}: New Reply",
        body=f"Your support ticket \"{ticket.subject}\" has a new reply from the admin team.",
    )
    await _emit_support_event(ticket, "reply")

    # Reload
    result = await db.execute(
        select(models.SupportTicket)
        .where(models.SupportTicket.id == ticket.id)
        .options(selectinload(models.SupportTicket.messages))
    )
    return result.scalar_one()


@router.post(
    "/api/v1/admin/support/tickets/{ticket_id}/status",
    response_model=TicketOut,
    summary="Change ticket status (admin)",
)
async def admin_change_ticket_status(
    ticket_id: int,
    payload: TicketStatusUpdate,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    """Change the status of a support ticket. Sends notification on resolve/close."""
    result = await db.execute(
        select(models.SupportTicket)
        .where(models.SupportTicket.id == ticket_id)
        .options(selectinload(models.SupportTicket.messages))
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    old_status = ticket.status
    ticket.status = payload.status
    await db.commit()

    # §OURSTATE-7 D — every status change leaves a visible system row in the
    # thread, whether or not it is one of the two that also notifies. A status
    # that moves silently is a thread that disagrees with its own ticket.
    if old_status != payload.status:
        from agentvault_registry.services import chat_support
        await _mirror(chat_support.mirror_status, db, ticket, old_status, payload.status,
                      by_name=current_admin.display_name or "Support")   # §ORGMARKET S4 — no auto name leak

    # Notify on resolve/close
    if payload.status in ("resolved", "closed") and old_status != payload.status:
        status_label = "resolved" if payload.status == "resolved" else "closed"
        await _send_ticket_notification(
            db=db,
            admin_id=current_admin.id,
            developer_id=ticket.developer_id,
            ticket_id=ticket.id,
            title=f"Support Ticket #{ticket.id}: {status_label.title()}",
            body=f"Your support ticket \"{ticket.subject}\" has been {status_label}.",
        )
    await _emit_support_event(ticket, "status")

    # Reload
    result = await db.execute(
        select(models.SupportTicket)
        .where(models.SupportTicket.id == ticket.id)
        .options(selectinload(models.SupportTicket.messages))
    )
    return result.scalar_one()


@router.get(
    "/api/v1/admin/support/tickets/{ticket_id}/review-grants",
    summary="Review grants on this ticket: which conversations the desk may read (§CHATDESK C4)",
)
async def admin_review_grants(
    ticket_id: int,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    from agentvault_registry.services import chat_support
    return {"ticket_id": ticket_id,
            "grants": await chat_support.review_grants_for_ticket(db, ticket_id)}


@router.get(
    "/api/v1/admin/support/review/{grant_id}/messages",
    summary="READ-ONLY transcript for a LIVE review grant; every call is audited (§CHATDESK C4)",
)
async def admin_review_messages(
    grant_id: str,
    request: Request,
    limit: int = 100,
    before_seq: Optional[int] = None,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    """Fail closed, twice: the grant row must be unrevoked and unexpired AND the
    ticket must still be open/in_progress — checked HERE, at read time, so a
    missed auto-revocation cannot keep a closed ticket readable. There is no
    write counterpart: the desk is not a participant, so the normal message
    POST already refuses it."""
    from agentvault_registry.services import chat_support
    g = await chat_support.get_review_grant(db, grant_id)
    if g is None:
        raise HTTPException(status_code=404, detail="No such review grant")
    reason = await chat_support.review_access_reason(db, g)
    if reason is not None:
        raise HTTPException(status_code=403, detail=reason)
    msgs = await chat_support.review_transcript(db, g, limit=limit, before_seq=before_seq)
    try:
        from agentvault_registry.services.admin_audit import log_admin_action
        await log_admin_action(
            db,
            action="chatdesk.review_read",
            actor_id=str(current_admin.id),
            actor_ip=effective_client_ip(request),
            target_type="conversation",
            target_id=str(g.conversation_id),
            details={"grant_id": g.id, "ticket_id": g.ticket_id, "messages": len(msgs)},
        )
    except Exception as e:  # noqa: BLE001
        logger.error("[CHATDESK] review_read audit row failed for grant %s: %s", grant_id, e)
    return {"grant_id": g.id, "ticket_id": g.ticket_id,
            "conversation_id": g.conversation_id, "read_only": True,
            "messages": msgs}


@router.post(
    "/api/v1/admin/support/tickets/{ticket_id}/triage",
    response_model=AdminTicketOut,
    summary="Set a ticket's priority and/or category (admin)",
)
async def admin_triage_ticket(
    ticket_id: int,
    payload: TicketTriageUpdate,
    request: Request,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    """§S12 — THE DESK COULD FILTER ON TWO FIELDS IT COULD NOT SET.

    His report: *"there is also no admin controls in the support admin view"*.
    The status row was there; everything else a desk does to a queue was not.
    `priority` and `category` are written once, by the customer, at creation —
    and the admin list has offered filters on both since it was written. So the
    queue could be sorted by two values only the person who filed the ticket
    could ever choose. A customer who marks everything urgent could not be
    corrected; a ticket filed under the wrong category stayed there forever.

    **Deliberately does NOT mirror into the customer's thread, and does NOT
    notify.** Status is a statement TO the customer about their problem, which
    is why §OURSTATE-7 D writes a system row for every status move. Priority
    and category are the desk organising its own work. Announcing *"your ticket
    was downgraded from urgent to normal"* in someone's chat thread is a
    different product decision, and not one to make silently on the way past.
    It lands in the admin audit log instead, where a desk action belongs.

    ⚠ **The customer still SEES the new priority** on their own ticket, because
    `TicketOut` carries it. So the field changes under them with no explanation
    attached. That is a real (small) honesty gap and it is a policy call, not a
    defect — filed beside S4, which is the same shape of question.

    PATCH-shaped: omitted fields are left alone rather than re-asserted, so
    re-categorising cannot silently overwrite a priority the caller never
    mentioned.
    """
    if payload.priority is None and payload.category is None:
        raise HTTPException(
            status_code=422,
            detail="Send at least one of 'priority' or 'category'.",
        )

    result = await db.execute(
        select(models.SupportTicket)
        .where(models.SupportTicket.id == ticket_id)
        .options(
            selectinload(models.SupportTicket.messages),
            selectinload(models.SupportTicket.developer),
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    before = {"priority": ticket.priority, "category": ticket.category}
    if payload.priority is not None:
        ticket.priority = payload.priority
    if payload.category is not None:
        ticket.category = payload.category
    after = {"priority": ticket.priority, "category": ticket.category}

    if after == before:
        # Nothing moved. Don't write an audit row claiming a change.
        dev = ticket.developer
        out = AdminTicketOut.model_validate(ticket)
        out.developer_email = dev.email if dev else None
        out.developer_name = (dev.display_name or dev.name) if dev else None
        return out

    await db.commit()

    try:
        from agentvault_registry.services.admin_audit import log_admin_action
        await log_admin_action(
            db,
            action="support.triage",
            actor_id=str(current_admin.id),
            actor_ip=effective_client_ip(request),
            target_type="support_ticket",
            target_id=str(ticket.id),
            details={"before": before, "after": after},
        )
    except Exception as e:  # noqa: BLE001
        logger.error("[SUPPORT] triage audit row failed for ticket #%s: %s", ticket.id, e)

    await _emit_support_event(ticket, "triage")

    result = await db.execute(
        select(models.SupportTicket)
        .where(models.SupportTicket.id == ticket.id)
        .options(
            selectinload(models.SupportTicket.messages),
            selectinload(models.SupportTicket.developer),
        )
    )
    ticket = result.scalar_one()
    dev = ticket.developer
    out = AdminTicketOut.model_validate(ticket)
    out.developer_email = dev.email if dev else None
    out.developer_name = (dev.display_name or dev.name) if dev else None
    return out
