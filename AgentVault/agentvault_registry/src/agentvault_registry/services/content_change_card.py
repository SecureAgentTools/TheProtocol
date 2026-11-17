"""V0667 D5b (order gwo_efd89f2041bfda1eeb7e2cda): a content change, live in its organization's room (the fast lane's counterpart of services/code_change_card).

A content change proposed into an organization's release line may name one room of that organization (POST /content-changes `room_id`, checked at the proposal: the same
room rule as a code change's, code_change_card.room_refusal). The room then carries ONE `content.change.live` card, posted by the code changes rail and updated in place as
the change moves (in its ballot, applied, undone, or the ends: not passed, not applied, withdrawn), and each change of state posts ONE short line into the room, the team's
development log. A decider votes from the card (the fast lane's own vote route, gov.vote); the card itself carries no reader's vote and no content text.

ONE writer path, as for a code change: services/content_changes.DbStore calls refresh_soon(cid) after each write it commits (a proposal, a state, a vote), so a change that moved
in a read (a ballot closing at its end) is announced the same way. The refresh runs in its own session, takes the change's lock for the card (a Postgres advisory lock held to the
next commit), posts the card once (one client_ref per change) or updates it in place, and moves the state the room last saw by compare-and-set, so a state line is posted once
whatever races. Best effort: a card that fails to post or to update is logged and the change stands. Nothing here moves value.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from sqlalchemy import text as sa_text

from . import chat_live_cards as lc
from . import chat_service as cs
from .code_change_card import _post, room_refusal, sender  # noqa: F401  (room_refusal is this rail's room rule too)

logger = logging.getLogger(__name__)


def card_client_ref(cid: str) -> str:
    """The card's one client_ref: a change posts its card once, whatever retries or races."""
    return f"ctlive-{cid}"[:64]


def line_client_ref(cid: str, seen: Optional[str], state: str) -> str:
    return f"ctline-{cid}-{seen or 'none'}-{state}"[:64]


async def _lock(db: Any, cid: str) -> None:
    await db.execute(sa_text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"content-change-live:{cid}"})


async def _room(db: Any, cid: str) -> Optional[dict]:
    r = (await db.execute(sa_text("SELECT announce_conversation_id, announce_message_id, announce_state FROM content_changes WHERE id = :c"), {"c": cid})).mappings().first()
    return dict(r) if r and r["announce_conversation_id"] else None


async def render(db: Any, cid: str) -> Optional[dict]:
    """The change's public view and its card, or None when the change names no room."""
    from . import content_changes as cc
    if await _room(db, cid) is None:
        await db.rollback()
        return None
    view = await cc.ContentChangeFlow(cc.store_for(db)).view({"admin": True, "developer_id": None}, cid)
    names = await cc.store_for(db).organization_names([view["organization_id"]])
    view["organization_name"] = names.get(view["organization_id"])
    return {"view": view, "card": lc.content_change_card(view)}


async def refresh(cid: str, session: Optional[Callable[[], Any]] = None) -> None:
    """Post or update the change's card in its room, and post its state line once (the background entry; never raises)."""
    if session is None:
        from ..database import get_db_context as session
    try:
        async with session() as db:
            now = await render(db, cid)
            if now is None:
                return
            view, card = now["view"], now["card"]
            state = card["data"]["state"]
            await _lock(db, cid)
            room = await _room(db, cid)
            if room is None:
                await db.rollback()
                return
            conv = await cs._get_conversation(db, room["announce_conversation_id"])
            if not room["announce_message_id"]:
                msg = await _post(db, conv, "card", None, card, card_client_ref(cid))       # commits
                await db.execute(sa_text("UPDATE content_changes SET announce_message_id = :m, announce_state = COALESCE(announce_state, :s) "
                                         "WHERE id = :c AND announce_message_id IS NULL"), {"m": msg.id, "s": state, "c": cid})
                await db.commit()
                return
            try:
                msg, conv2, changed = await cs.update_card(db, conv.id, room["announce_message_id"], sender(), card, rail_author=True)     # commits
                if changed and conv2 is not None:
                    await cs.deliver_card_update(db, conv2, msg, sender())
            except cs.ChatError as e:
                await db.rollback()
                logger.debug("[CONTENT-CHANGES] the card of %s was not updated: %s", cid, e.detail)
            seen = room["announce_state"]
            line = lc.content_change_state_line(seen, view)
            if line is None:
                return
            moved = (await db.execute(sa_text("UPDATE content_changes SET announce_state = :s WHERE id = :c AND announce_state IS NOT DISTINCT FROM :seen RETURNING id"),
                                      {"s": state, "c": cid, "seen": seen})).first()
            await db.commit()
            if moved is not None:                    # this refresh moved it: its line, once
                await _post(db, conv, "text", line, None, line_client_ref(cid, seen, state))
    except Exception as e:  # noqa: BLE001 — the card is a display of the change, which is already recorded
        logger.warning("[CONTENT-CHANGES] the room card of %s was not kept current: %s", cid, e)


def refresh_soon(cid: str) -> None:
    """Ask for the card's refresh after a write that committed (never raises)."""
    try:
        cs.spawn(refresh(cid), what=f"the room card of content change {cid}")
    except Exception:  # noqa: BLE001 — no running loop (a script): no card, the change stands
        logger.debug("[CONTENT-CHANGES] room card refresh for %s skipped", cid, exc_info=True)
