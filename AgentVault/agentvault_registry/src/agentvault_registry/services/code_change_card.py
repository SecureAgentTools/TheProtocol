"""V0666 D3 (order gwo_542285271416c653ca39af3f, session-tester): a code distribution's change, live in its organization's room.

A change proposed into an organization's release line may name one room of that organization (POST /code-changes
`room_id`, checked at propose: services/code_changes.propose asks room_refusal here). The room then carries ONE
`code.change.live` card, posted by this rail and updated in place as the change moves (proposed, checked, in review,
balloting, passed, merged, and the ends: failed, vetoed, withdrawn), and each change of state posts ONE short line into
that room, the team's development log. Only the line's own organization's room: a room of another organization, a support
or system thread, a thread another registry hosts or one the proposer's agent may not post in is refused.

ONE writer path: services/code_changes.DbStore calls refresh_soon(cid) after each write it commits (a proposal, a state,
a review, a line's vote), so a change that moved in a read (a line's ballot closing at its end) or in the reaper's sweep
is announced the same way. The refresh runs in its own session: it renders the change's public view (never a reader's
own vote), takes the change's lock for the card (a Postgres advisory lock held to the next commit, so two workers never
write the card out of order), posts the card once (one client_ref per change) or updates it in place, and moves the
state the room last saw by compare-and-set, so a state line is posted once whatever races. Best effort: a card that
fails to post or to update is logged and the change stands. Nothing here moves value; a bounty stays a Guild order.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from . import chat_live_cards as lc
from . import chat_service as cs

logger = logging.getLogger(__name__)

SENDER_ID = "code-changes"
SENDER_NAME = "Code changes"


def sender() -> "cs.Actor":
    """The rail the card and its lines speak as (a system sender: the change's record, not a member's message)."""
    return cs.Actor("system", display_name=SENDER_NAME, system_id=SENDER_ID)


def card_client_ref(cid: str) -> str:
    """The card's one client_ref: a change posts its card once, whatever retries or races."""
    return f"cclive-{cid}"[:64]


def line_client_ref(cid: str, seen: Optional[str], state: str) -> str:
    """A state line's client_ref: one per change of state (from what the room saw to the state now)."""
    return f"ccline-{cid}-{seen or 'none'}-{state}"[:64]


async def room_refusal(db: AsyncSession, room_id: str, proposer_did: Optional[str], organization_id: str) -> Optional[str]:
    """Why a line's change may not be announced in this room, or None: the room must be a room of the line's own
    organization, hosted here, and one the proposer's agent takes part in and may post in now (the room's speech gates)."""
    try:
        conv = await cs._get_conversation(db, room_id)
    except cs.ChatError:
        return "room_id names no conversation on this registry"
    if conv.kind in ("support", "system"):
        return "a change is announced in a room of its organization, not in a support or system thread"
    if getattr(conv, "host_registry", None):
        return "room_id names a thread another registry hosts"
    if str(getattr(conv, "org_id", None) or "") != str(organization_id):
        return "a line's change is announced only in a room of the line's organization"
    if not proposer_did:
        return "the proposer's agent cannot announce in this room"
    poster = cs.Actor("agent", agent_did=proposer_did)
    try:
        row = await cs.resolve_membership(db, conv, poster)
    except cs.ChatError as e:
        return f"the proposer cannot announce in this room: {e.detail}"
    if row is None or row.state != "active":
        return "the proposer's agent does not take part in this room"
    try:
        await cs.room_posting_gate(db, conv, row, poster)
    except cs.ChatError as e:
        return f"the proposer may not post in this room now: {e.detail}"
    return None


async def _lock(db: AsyncSession, cid: str) -> None:
    """The change card's writers, one at a time across workers: a lock the transaction holds until its commit."""
    await db.execute(sa_text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"code-change-live:{cid}"})


async def _room(db: AsyncSession, cid: str) -> Optional[dict]:
    r = (await db.execute(sa_text(
        "SELECT announce_conversation_id, announce_message_id, announce_state FROM code_changes WHERE id = :c"),
        {"c": cid})).mappings().first()
    return dict(r) if r and r["announce_conversation_id"] else None


async def render(db: AsyncSession, cid: str) -> Optional[dict]:
    """The change's public view and its card, or None when the change names no room (or is no line's change)."""
    from . import code_changes as cc
    if await _room(db, cid) is None:
        await db.rollback()
        return None
    view = await cc.CodeChangeFlow(cc.store_for(db)).view(cid)
    if not view.get("code_distribution"):
        return None
    return {"view": view, "card": lc.code_change_card(view)}


async def _post(db: AsyncSession, conv: Any, kind: str, body: Optional[str], card: Optional[dict], ref: str) -> Any:
    msg, dup = await cs.insert_message(db, conv, None, sender(), kind, body, card, client_ref=ref, rail_author=True,
                                       mark_read=False)
    if not dup:
        payload = cs.serialize_message(msg)
        payload["sender_name"] = SENDER_NAME
        recipients = await cs.recipients_snapshot(db, conv, sender())
        if recipients:
            cs.deliver(conv.id, conv.kind, payload, recipients, SENDER_NAME)
    return msg


async def refresh(cid: str, session: Optional[Callable[[], Any]] = None) -> None:
    """Post or update the change's card in its room, and post its state line once (the background entry; never raises).
    `session` is a context factory for a session (the app's own by default)."""
    if session is None:
        from ..database import get_db_context as session
    try:
        async with session() as db:
            now = await render(db, cid)
            if now is None:
                return
            view, card = now["view"], now["card"]
            state = lc.room_state(view)         # V0667 D4: `upstreaming` / `upstream` for a merged change that went upstream
            await _lock(db, cid)
            room = await _room(db, cid)
            if room is None:
                await db.rollback()
                return
            conv = await cs._get_conversation(db, room["announce_conversation_id"])
            if not room["announce_message_id"]:
                msg = await _post(db, conv, "card", None, card, card_client_ref(cid))       # commits
                await db.execute(sa_text(
                    "UPDATE code_changes SET announce_message_id = :m, announce_state = COALESCE(announce_state, :s) "
                    "WHERE id = :c AND announce_message_id IS NULL"), {"m": msg.id, "s": state, "c": cid})
                await db.commit()
                return
            try:
                msg, conv2, changed = await cs.update_card(db, conv.id, room["announce_message_id"], sender(), card,
                                                           rail_author=True)               # commits
                if changed and conv2 is not None:
                    await cs.deliver_card_update(db, conv2, msg, sender())
            except cs.ChatError as e:
                # a closed card (a late refresh after the change ended) or one its room's timer erased: the change
                # stands, the card stays as it last read; the state line below still tells the room
                await db.rollback()
                # the rollback expires every object the session holds, `conv` among them: read it again before the state line below posts into it
                # (V0667 D4: the first state line AFTER a change ended, `upstream`, meets this path; before it no line followed a closed card)
                conv = await cs._get_conversation(db, room["announce_conversation_id"])
                logger.debug("[CODE-CHANGES] the card of %s was not updated: %s", cid, e.detail)
            seen = room["announce_state"]
            line = lc.code_change_state_line(seen, view)
            if line is None:
                return
            moved = (await db.execute(sa_text(
                "UPDATE code_changes SET announce_state = :s WHERE id = :c AND announce_state IS NOT DISTINCT FROM :seen "
                "RETURNING id"), {"s": state, "c": cid, "seen": seen})).first()
            await db.commit()
            if moved is not None:                    # this refresh moved it: its line, once
                await _post(db, conv, "text", line, None, line_client_ref(cid, seen, state))
    except Exception as e:  # noqa: BLE001 — the card is a display of the change, which is already recorded
        logger.warning("[CODE-CHANGES] the room card of %s was not kept current: %s", cid, e)


def refresh_soon(cid: str) -> None:
    """Ask for the card's refresh after a write that committed (never raises)."""
    try:
        cs.spawn(refresh(cid), what=f"the room card of code change {cid}")
    except Exception:  # noqa: BLE001 — no running loop (a script): no card, the change stands
        logger.debug("[CODE-CHANGES] room card refresh for %s skipped", cid, exc_info=True)
