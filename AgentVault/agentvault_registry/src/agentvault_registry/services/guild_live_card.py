"""V0652 (aa) gwo_840aa2b590306f7eba147758 (2026-11-01, agentvault2-14): a Guild order's lifecycle as one card.

The sessions' room typed an order's lifecycle by hand (BID, AWARDED, DONE ...), ten messages per order. An order whose
poster names a room (POST /guild/orders `room_id`, a thread the poster's agent takes part in and may post in) now has ONE
`guild.order.live` card there, posted by the Guild rail when the order is posted and updated in place at each step of
its lifecycle (posted, bid, awarded, delivered, settling, settled, disputed, cancelled). Settled or cancelled closes it.

ONE writer path: routers/guild.py `_audit`, the one place every lifecycle event is written, asks for a refresh after it
writes an event. The refresh runs in its own session after the event's transaction: it waits until that event is
committed (an event that never commits, because its transaction rolled back, shows nothing), takes the order's lock for
the card (a Postgres advisory lock, so two workers never write the card out of order), reads the order as it now is and
renders the card from it; an older refresh that runs late renders the same latest state, so the card never goes back.
Best effort: a card that fails to post or to update is logged and the order stands. Nothing here moves money.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from . import chat_live_cards as lc
from . import chat_service as cs

logger = logging.getLogger(__name__)

GUILD_SENDER_ID = "guild"
GUILD_NAME = "Guild"
COMMIT_WAIT_S = 15.0
COMMIT_POLL_S = 0.25


def guild_sender() -> "cs.Actor":
    """The rail the card speaks as (a system sender: the card is the order's record, not a member's message)."""
    return cs.Actor("system", display_name=GUILD_NAME, system_id=GUILD_SENDER_ID)


def card_client_ref(order_id: str) -> str:
    """The card's one client_ref: an order posts its card once, whatever retries or races."""
    return f"glive-{order_id}"[:64]


async def room_refusal(db: AsyncSession, room_id: str, poster: "cs.Actor") -> Optional[str]:
    """Why the poster may not announce its order in this room, or None. The room must be one the poster's agent takes
    part in and may post in now (the room's speech gates), hosted here, and not a support or system thread."""
    try:
        conv = await cs._get_conversation(db, room_id)
    except cs.ChatError:
        return "room_id names no conversation on this registry"
    if conv.kind in ("support", "system"):
        return "an order is announced in a room or a conversation, not in a support or system thread"
    if getattr(conv, "host_registry", None):
        return "room_id names a thread another registry hosts: announce the order there"
    try:
        row = await cs.resolve_membership(db, conv, poster)
    except cs.ChatError as e:
        return f"the poster cannot announce in this room: {e.detail}"
    if row is None or row.state != "active":
        return "the poster's agent does not take part in this room"
    try:
        await cs.room_posting_gate(db, conv, row, poster)
    except cs.ChatError as e:
        return f"the poster may not post in this room now: {e.detail}"
    return None


async def _lock(db: AsyncSession, order_id: str) -> None:
    """The order card's writers, one at a time across workers: a lock the transaction holds until its commit."""
    await db.execute(sa_text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"guild-live:{order_id}"})


async def _committed_through(db: AsyncSession, order_id: str, seq: int) -> bool:
    deadline = asyncio.get_running_loop().time() + COMMIT_WAIT_S
    while True:
        n = (await db.execute(sa_text("SELECT COALESCE(MAX(seq), 0) FROM guild_order_events WHERE order_id = :o"),
                              {"o": order_id})).scalar()
        await db.rollback()                        # end the read: the next one sees what committed since
        if int(n or 0) >= int(seq):
            return True
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(COMMIT_POLL_S)


async def render(db: AsyncSession, order_id: str) -> Optional[Dict[str, Any]]:
    """The order as its card shows it now, and where the card lives; None when the order names no room."""
    o = (await db.execute(sa_text(
        "SELECT id, poster_did, title, bounty, currency, status, worker_did, announce_conversation_id, "
        "announce_message_id FROM guild_work_orders WHERE id = :o"), {"o": order_id})).mappings().first()
    if not o or not o["announce_conversation_id"]:
        return None
    events = [dict(r) for r in (await db.execute(sa_text(
        "SELECT seq, event_type, created_at FROM guild_order_events WHERE order_id = :o ORDER BY seq")
        .columns(created_at=DateTime(timezone=True)), {"o": order_id})).mappings().all()]
    for e in events:
        at = e.pop("created_at", None)
        e["at"] = at.isoformat() if hasattr(at, "isoformat") else (str(at) if at else None)
    bids = int((await db.execute(sa_text("SELECT count(*) FROM guild_bids WHERE order_id = :o"),
                                 {"o": order_id})).scalar() or 0)
    keys = [cs.principal_key("agent", d) for d in (o["poster_did"], o["worker_did"]) if d]
    names = await cs.display_names(db, keys) if keys else {}
    worker = o["worker_did"]
    card = lc.guild_order_card(dict(o), events, bid_count=bids,
                               worker_name=names.get(cs.principal_key("agent", worker)) if worker else None)
    poster_name = names.get(cs.principal_key("agent", o["poster_did"]))
    card["data"]["poster_did"] = o["poster_did"]
    if poster_name:
        card["data"]["poster_name"] = str(poster_name)[:120]
    return {"card": card, "conversation_id": o["announce_conversation_id"], "message_id": o["announce_message_id"]}


async def refresh(order_id: str, seq: int) -> None:
    """Post or update the order's card once event `seq` is committed (the background entry; never raises)."""
    from ..database import get_db_context
    try:
        async with get_db_context() as db:
            if not await _committed_through(db, order_id, seq):
                return                            # the event's transaction did not commit: nothing to show
            await _lock(db, order_id)
            now = await render(db, order_id)
            if now is None:
                await db.rollback()
                return
            conv = await cs._get_conversation(db, now["conversation_id"])
            sender = guild_sender()
            mid = now["message_id"]
            if not mid:
                msg, dup = await cs.insert_message(db, conv, None, sender, "card", None, now["card"],
                                                   client_ref=card_client_ref(order_id), rail_author=True,
                                                   mark_read=False)
                await db.execute(sa_text("UPDATE guild_work_orders SET announce_message_id = :m "
                                         "WHERE id = :o AND announce_message_id IS NULL"), {"m": msg.id, "o": order_id})
                await db.commit()
                if not dup:
                    payload = cs.serialize_message(msg)
                    payload["sender_name"] = GUILD_NAME
                    recipients = await cs.recipients_snapshot(db, conv, sender)
                    if recipients:
                        cs.deliver(conv.id, conv.kind, payload, recipients, GUILD_NAME)
                    return
                mid = msg.id                       # a twin posted it first: keep that one current
                await _lock(db, order_id)
                now = await render(db, order_id) or now
            try:
                msg, conv2, changed = await cs.update_card(db, conv.id, mid, sender, now["card"], rail_author=True)
            except cs.ChatError as e:
                # a closed card (a late refresh after the order ended), or a card its room's timer erased: the order
                # stands, the card simply stays as it last read
                await db.rollback()
                logger.debug("[GUILD] the card of %s was not updated: %s", order_id, e.detail)
                return
            if changed and conv2 is not None:
                await cs.deliver_card_update(db, conv2, msg, sender)
    except Exception as e:  # noqa: BLE001 — the card is a display of the order, which is already recorded
        logger.warning("[GUILD] the room card of order %s was not kept current: %s", order_id, e)


def refresh_soon(order_id: str, seq: int, event_type: str) -> None:
    """Ask for the card's refresh after event `seq` (only the lifecycle events a card shows; never raises)."""
    if event_type not in lc.GUILD_EVENT_TYPES:
        return
    try:
        cs.spawn(refresh(order_id, seq), what=f"the room card of guild order {order_id} after event {seq}")
    except Exception:  # noqa: BLE001 — no running loop (a script): no card, the order stands
        logger.debug("[GUILD] room card refresh for %s skipped", order_id, exc_info=True)
