"""§OURSTATE-7 D — support tickets, as threads.

The last frozen item of the OurChat program, and the smallest in scope on
purpose: **support keeps deciding, chat starts displaying.**

Before this, a developer filed a ticket and the answer arrived as a
notification pointing at a settings tab — a parallel inbox next to the one they
actually read. §OURSTATE-2 already fixed the loud half of that (the reply used
to broadcast to EVERY developer; it now notifies the ticket owner and only
them). This is the quiet half: the conversation appears where conversations
appear.

THE RULES, and why each one is here:

  * **The ticket is the authority.** Status, reopening, who may read it — all of
    that stays on `support_tickets`. This module never decides anything; it
    writes a MIRROR. That is why `insert_message` refuses a direct client post
    into a support thread (`ChatError(409)`): one writer, or the thread and the
    ticket drift and the thread is the one people believe.

  * **The desk is a RAIL, not a participant.** An admin who answers a ticket
    does not become a member of the customer's thread — their reply is written
    with `sender_ptype='system'`. So the participant list stays exactly one
    person: the ticket owner. (`chat_messages` has allowed 'system' authorship
    since mig 0155; nothing had needed it until now.)

  * **A reply written TO you is UNREAD.** `mark_read=False` on desk writes. The
    default in `insert_message` is True because a principal's own send is read
    by definition — passing the owner's row with that default would have marked
    their incoming support reply as already seen, which is the whole thing this
    feature exists to stop.

  * **Mirroring never fails the ticket.** Every entry point is wrapped by the
    caller so that a chat problem cannot swallow a support reply. A ticket that
    was answered and did not mirror is a display bug; a reply that 500s because
    the mirror broke is a support outage.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (Conversation, ConversationParticipant, ChatMessage,
                      SupportReviewGrant, SupportTicket, Developer)
from . import chat_service as cs

logger = logging.getLogger(__name__)

SUPPORT_KIND = "support"

#: The desk. One synthetic principal for every registry — it authenticates
#: nothing and holds nothing; it is a label on a rail write.
SUPPORT_DESK = cs.Actor("system", display_name="Support", system_id="support")


def support_pair_key(ticket_id: int) -> str:
    """One thread per ticket, on the same UNIQUE column org rooms use."""
    return f"support|{int(ticket_id)}"


def _title(subject: Any) -> str:
    s = str(subject or "Support").strip() or "Support"
    return s[:160]


async def ensure_thread(db: AsyncSession, ticket: Any) -> Optional[Conversation]:
    """The thread for this ticket, created on first use. Idempotent.

    Returns None only if the ticket has no owner to put in it — a ticket
    without a developer is not a conversation, and inventing a participant for
    it would be worse than having no thread.
    """
    dev_id = getattr(ticket, "developer_id", None)
    if dev_id is None:
        return None
    tid = int(ticket.id)
    pk = support_pair_key(tid)

    conv = (await db.execute(select(Conversation).where(
        Conversation.dm_pair_key == pk))).scalars().first()
    if conv is not None:
        # The subject is the thread's name; an edited subject renames it, the
        # same way a renamed org renames its room.
        if conv.title != _title(ticket.subject):
            conv.title = _title(ticket.subject)
        return conv

    conv = Conversation(
        kind=SUPPORT_KIND, title=_title(ticket.subject),
        created_by_ptype="system", created_by_id="support",
        dm_pair_key=pk, support_ticket_id=tid)
    db.add(conv)
    try:
        await db.flush()
    except IntegrityError:
        # Two replies raced the first mirror. The twin won; use it.
        await db.rollback()
        return (await db.execute(select(Conversation).where(
            Conversation.dm_pair_key == pk))).scalars().first()

    db.add(ConversationParticipant(
        conversation_id=conv.id, ptype="developer", developer_id=int(dev_id),
        role="owner", state="active"))
    await db.flush()
    return conv


async def _owner_row(db: AsyncSession, conv: Conversation) -> Optional[ConversationParticipant]:
    return (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id,
        ConversationParticipant.ptype == "developer"))).scalars().first()


async def _write(db: AsyncSession, conv: Conversation, *, sender: cs.Actor,
                 kind: str, body: Optional[str], card: Optional[dict],
                 client_ref: str, mark_read: bool) -> Optional[dict]:
    my_row = None
    if sender.ptype == "developer":
        my_row = await _owner_row(db, conv)
        if my_row is None:
            return None
    msg, dup = await cs.insert_message(
        db, conv, my_row, sender, kind, body, card,
        client_ref=client_ref, rail_author=True, mark_read=mark_read)
    if dup:
        return None
    return cs.serialize_message(msg)


async def _announce(db: AsyncSession, conv: Conversation, sender: cs.Actor,
                    payload: dict) -> None:
    """Post-commit fan-out (§ESDUP: never announce what might roll back)."""
    try:
        recipients = await cs.recipients_snapshot(db, conv, sender)
        if recipients:
            cs.deliver(
                conv.id, conv.kind, payload, recipients, sender.display_name)
    except Exception as e:  # noqa: BLE001 — a missed live update is not an outage
        logger.debug("support thread fan-out skipped: %s", e)


async def mirror_user_message(db: AsyncSession, ticket: Any, text: str,
                              *, client_ref: Optional[str] = None) -> Optional[dict]:
    """The owner's own words, authored by the owner.

    ⚠ CALL AFTER THE TICKET IS COMMITTED. `insert_message` commits, so calling
    it mid-transaction would commit a half-written ticket — and the ticket is
    the authority, so it goes in first, always.
    """
    conv = await ensure_thread(db, ticket)
    if conv is None:
        return None
    sender = cs.Actor("developer", developer_id=int(ticket.developer_id),
                      display_name="you")
    payload = await _write(db, conv, sender=sender, kind="text", body=str(text)[:4000],
                           card=None, client_ref=client_ref or str(_uuid.uuid4()),
                           mark_read=True)
    if payload:
        await _announce(db, conv, sender, payload)
    return payload


async def mirror_desk_message(db: AsyncSession, ticket: Any, sender_name: str, text: str,
                              *, client_ref: Optional[str] = None) -> Optional[dict]:
    """An answer from support. Authored by the RAIL, and left UNREAD."""
    conv = await ensure_thread(db, ticket)
    if conv is None:
        return None
    desk = cs.Actor("system", display_name=str(sender_name or "Support")[:120],
                    system_id="support")
    payload = await _write(db, conv, sender=desk, kind="text", body=str(text)[:4000],
                           card=None, client_ref=client_ref or str(_uuid.uuid4()),
                           mark_read=False)
    if payload:
        await _announce(db, conv, desk, payload)
    return payload


async def mirror_status(db: AsyncSession, ticket: Any, old: str, new: str,
                        *, by_name: str = "Support") -> Optional[dict]:
    """A visible system row for a status change — the same in-band trail a room
    moderation act leaves. `support.<status>` is a machine string the client
    renders as a sentence; it never reaches a human raw (the `retention.24h`
    scar, which he read off his own screen)."""
    if str(old) == str(new):
        return None
    conv = await ensure_thread(db, ticket)
    if conv is None:
        return None
    desk = cs.Actor("system", display_name=str(by_name or "Support")[:120],
                    system_id="support")
    payload = await _write(db, conv, sender=desk, kind="system",
                           body=f"support.{str(new)[:24]}", card=None,
                           client_ref=str(_uuid.uuid4()), mark_read=False)
    if payload:
        await _announce(db, conv, desk, payload)
    # §CHATDESK C4 — closing/resolving the ticket ends every review grant on
    # it. Same choke point as the status mirror so no path can miss it; the
    # transcript read validates ticket status independently (fail closed).
    if str(new) in ("closed", "resolved"):
        try:
            await end_review_grants_for_ticket(db, int(ticket.id), reason=f"ticket_{new}")
        except Exception as e:  # noqa: BLE001 — the belt is the read-side check
            logger.warning("[CHATDESK] review-grant auto-revoke failed for ticket #%s: %s",
                           getattr(ticket, "id", "?"), e)
    return payload


async def ticket_for_conversation(db: AsyncSession, conversation_id: str) -> Optional[int]:
    """The ticket a support thread mirrors, or None when the thread is not one.

    Reads the COLUMN, never a prefix parsed back out of `dm_pair_key` — a thing
    this code asks on every reply is a column (mig 0164).
    """
    conv = (await db.execute(select(Conversation).where(
        Conversation.id == conversation_id))).scalars().first()
    if conv is None or conv.kind != SUPPORT_KIND:
        return None
    return int(conv.support_ticket_id) if conv.support_ticket_id is not None else None


# ═══════════════════════════════════════════════════════════════════════════
# §CHATDESK C4 — SUPPORT REVIEW WITH CONSENT
#
# The desk may READ a conversation only while a live, visible, ticket-bound
# grant exists. LIVE means: not revoked, not expired, AND the ticket status is
# still open/in_progress — validated at READ TIME, so even a missed
# revocation write cannot keep a closed ticket readable (fail closed, both
# halves; the §ORGLIFE grant law applied on day one). Every state change
# posts a system row into the conversation itself: never covert.
# ⚠ System-row bodies are server-authored EN sentences (the desk-is-a-rail
# reality); the BANNER is the localized surface.
# ═══════════════════════════════════════════════════════════════════════════

REVIEW_LIVE_STATUSES = ("open", "in_progress")


def _now():
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(v):
    return v.isoformat() if v is not None else None


def grant_is_live(g: SupportReviewGrant, ticket_status: Optional[str]) -> bool:
    if g.revoked_at is not None:
        return False
    if g.expires_at is not None and g.expires_at <= _now():
        return False
    return str(ticket_status or "") in REVIEW_LIVE_STATUSES


def _grant_dict(g: SupportReviewGrant, ticket_status: Optional[str],
                granted_by_name: Optional[str] = None) -> dict:
    return {
        "grant_id": g.id, "ticket_id": g.ticket_id,
        "conversation_id": g.conversation_id,
        "granted_by_dev": g.granted_by_dev,
        "granted_by_name": granted_by_name,
        "scope": g.scope,
        "created_at": _iso(g.created_at), "expires_at": _iso(g.expires_at),
        "revoked_at": _iso(g.revoked_at), "revoked_reason": g.revoked_reason,
        "ticket_status": ticket_status,
        "live": grant_is_live(g, ticket_status),
    }


async def review_grants_for_conversation(db: AsyncSession, conversation_id: str) -> list:
    rows = (await db.execute(
        select(SupportReviewGrant, SupportTicket.status, Developer.name)
        .join(SupportTicket, SupportTicket.id == SupportReviewGrant.ticket_id)
        .join(Developer, Developer.id == SupportReviewGrant.granted_by_dev)
        .where(SupportReviewGrant.conversation_id == conversation_id)
        .order_by(SupportReviewGrant.created_at.desc()))).all()
    return [_grant_dict(g, st, nm) for g, st, nm in rows]


async def review_grants_for_ticket(db: AsyncSession, ticket_id: int) -> list:
    rows = (await db.execute(
        select(SupportReviewGrant, SupportTicket.status, Developer.name, Conversation)
        .join(SupportTicket, SupportTicket.id == SupportReviewGrant.ticket_id)
        .join(Developer, Developer.id == SupportReviewGrant.granted_by_dev)
        .join(Conversation, Conversation.id == SupportReviewGrant.conversation_id)
        .where(SupportReviewGrant.ticket_id == ticket_id)
        .order_by(SupportReviewGrant.created_at.desc()))).all()
    out = []
    for g, st, nm, conv in rows:
        d = _grant_dict(g, st, nm)
        d["conversation_kind"] = conv.kind
        d["conversation_title"] = conv.title
        out.append(d)
    return out


async def get_review_grant(db: AsyncSession, grant_id: str,
                           conversation_id: Optional[str] = None) -> Optional[SupportReviewGrant]:
    q = select(SupportReviewGrant).where(SupportReviewGrant.id == grant_id)
    if conversation_id is not None:
        q = q.where(SupportReviewGrant.conversation_id == conversation_id)
    return (await db.execute(q)).scalars().first()


async def create_review_grant(db: AsyncSession, ticket: Any, conv: Conversation,
                              granted_by_dev: int, expires_hours: Optional[int] = None):
    """Returns (grant, created). Idempotent on a LIVE (ticket, conversation)
    pair; a revoked grant never comes back — a re-grant is a NEW row."""
    existing = (await db.execute(select(SupportReviewGrant).where(
        SupportReviewGrant.ticket_id == int(ticket.id),
        SupportReviewGrant.conversation_id == conv.id,
        SupportReviewGrant.revoked_at.is_(None)))).scalars().first()
    if existing is not None and grant_is_live(existing, ticket.status):
        return existing, False
    import datetime as _dt
    g = SupportReviewGrant(
        id=str(_uuid.uuid4()), ticket_id=int(ticket.id), conversation_id=conv.id,
        granted_by_dev=int(granted_by_dev), scope="read",
        expires_at=(_now() + _dt.timedelta(hours=int(expires_hours))) if expires_hours else None)
    db.add(g)
    await db.flush()
    return g, True


async def revoke_review_grant(db: AsyncSession, g: SupportReviewGrant, reason: str) -> None:
    if g.revoked_at is None:
        g.revoked_at = _now()
        g.revoked_reason = str(reason)[:200]
        await db.flush()


async def announce_review_event(db: AsyncSession, conv: Conversation,
                                sender: cs.Actor, body_text: str) -> Optional[dict]:
    """The visibility half: a system row in the conversation itself."""
    payload = await _write(db, conv, sender=sender, kind="system",
                           body=str(body_text)[:1000], card=None,
                           client_ref=str(_uuid.uuid4()), mark_read=False)
    if payload:
        await _announce(db, conv, sender, payload)
    return payload


async def end_review_grants_for_ticket(db: AsyncSession, ticket_id: int,
                                       reason: str = "ticket_closed") -> int:
    """Auto-revoke on ticket close/resolve — the grant dies with the ticket.
    Called through the mirror wrapper (display path); the READ side validates
    the ticket status independently, so a failure here cannot fail open."""
    live = (await db.execute(select(SupportReviewGrant).where(
        SupportReviewGrant.ticket_id == int(ticket_id),
        SupportReviewGrant.revoked_at.is_(None)))).scalars().all()
    n = 0
    for g in live:
        await revoke_review_grant(db, g, reason)
        n += 1
        conv = (await db.execute(select(Conversation).where(
            Conversation.id == g.conversation_id))).scalars().first()
        if conv is not None:
            await announce_review_event(
                db, conv, SUPPORT_DESK,
                f"The support desk's review access ended: ticket #{ticket_id} closed.")
    return n


async def review_access_reason(db: AsyncSession, g: SupportReviewGrant) -> Optional[str]:
    """None while the grant is LIVE; otherwise the refusal sentence."""
    if g.revoked_at is not None:
        return f"this review grant was revoked ({g.revoked_reason or 'by the granter'})"
    if g.expires_at is not None and g.expires_at <= _now():
        return "this review grant has expired"
    st = (await db.execute(select(SupportTicket.status).where(
        SupportTicket.id == g.ticket_id))).scalar()
    if str(st or "") not in REVIEW_LIVE_STATUSES:
        return f"ticket #{g.ticket_id} is {st or 'gone'} — review access ends with the ticket"
    return None


async def review_transcript(db: AsyncSession, g: SupportReviewGrant,
                            limit: int = 100, before_seq: Optional[int] = None) -> list:
    """READ-ONLY transcript for a live grant. The route audits every call."""
    q = select(ChatMessage).where(ChatMessage.conversation_id == g.conversation_id)
    if before_seq is not None:
        q = q.where(ChatMessage.seq < int(before_seq))
    q = q.order_by(ChatMessage.seq.desc()).limit(max(1, min(int(limit), 200)))
    msgs = (await db.execute(q)).scalars().all()
    return [cs.serialize_message(m) for m in reversed(msgs)]
