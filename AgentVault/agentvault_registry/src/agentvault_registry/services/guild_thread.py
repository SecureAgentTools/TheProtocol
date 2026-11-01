"""V0651 (s) gwo_16cb368b37f9b13d39ed1786 (2026-10-31, agentvault2-14): a bid reaches the poster AGENT as an event it can
wait on.

A bid told the poster's OWNERS (the push, the webhook), but the poster agent itself, which verifies and awards, heard
nothing it could wait on: V0650 (g)'s sync wait returns chat messages in the caller's own threads. So each poster agent
gets ONE Guild thread (kind `system`, created by the system, one participant: the agent), and every bid on its orders lands
there as one system row, written by the rail and fanned out after its commit, so the agent's waiting sync wakes on it.
The row is a sentence that names the order and the bid (`New bid on order gwo_... (bid N): ...`): an agent reads the ids
from it, the console and the list preview show it as it is, and the order itself (guildGetOrder) holds the rest.

Best effort, after the bid's own commit: a notice that fails is logged and the bid stands. The thread is rail-only (a
participant cannot post into it, chat_service.insert_message). Nothing here moves money.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select, text as sa_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Conversation, ConversationParticipant
from . import chat_service as cs

logger = logging.getLogger(__name__)

GUILD_THREAD_KIND = "system"
GUILD_TITLE = "Guild"
GUILD_SYSTEM_ID = "guild"
_PAIR_PREFIX = "guild:"


def guild_pair_key(agent_did: str) -> str:
    """The thread's one key: one Guild thread per agent, whatever case its DID is written in."""
    return _PAIR_PREFIX + str(agent_did).strip().lower()


def _eta(seconds: Any) -> str:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "an unstated time"
    if s < 3600:
        return f"{max(1, round(s / 60))} min"
    if s < 86400:
        return f"{round(s / 3600)} h"
    return f"{round(s / 86400)} d"


def bid_sentence(*, order_id: str, title: Optional[str], bid_id: Any, bidder_did: str, price: Any,
                 currency: Optional[str], eta_seconds: Any) -> str:
    """The row's body: one English sentence with the ids an agent needs (`order <id> (bid <n>)`)."""
    t = " ".join(str(title or "").split())
    named = f' "{t[:80]}{"..." if len(t) > 80 else ""}"' if t else ""
    return (f"New bid on order {order_id} (bid {bid_id}){named}: {price} {currency or ''}".rstrip()
            + f", ready in {_eta(eta_seconds)}, from {bidder_did}.")


async def ensure_thread(db: AsyncSession, agent_did: str) -> Optional[Conversation]:
    """The agent's Guild thread, created on first use; None when the agent is not on this registry (a notice for an
    agent another registry hosts is that registry's to write). Idempotent under a race (the key is unique)."""
    if (await db.execute(sa_text("SELECT 1 FROM agents WHERE lower(did) = lower(:d) LIMIT 1"),
                         {"d": agent_did})).first() is None:
        return None
    pk = guild_pair_key(agent_did)
    conv = (await db.execute(select(Conversation).where(Conversation.dm_pair_key == pk))).scalars().first()
    if conv is not None:
        return conv
    conv = Conversation(kind=GUILD_THREAD_KIND, title=GUILD_TITLE, created_by_ptype="system",
                        created_by_id=GUILD_SYSTEM_ID, dm_pair_key=pk)
    db.add(conv)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()                       # two bids raced the first notice: the twin won, use it
        return (await db.execute(select(Conversation).where(Conversation.dm_pair_key == pk))).scalars().first()
    db.add(ConversationParticipant(conversation_id=conv.id, ptype="agent", agent_did=agent_did, role="owner",
                                   state="active"))
    await db.flush()
    return conv


async def post_bid(db: AsyncSession, *, poster_did: str, order_id: str, title: Optional[str], bid_id: Any,
                   bidder_did: str, price: Any, currency: Optional[str], eta_seconds: Any) -> Optional[dict]:
    """Write the bid's row in the poster agent's Guild thread and fan it out (post-commit: insert_message commits).
    Returns the message as served, or None (a poster this registry does not host; the same bid noticed twice)."""
    conv = await ensure_thread(db, poster_did)
    if conv is None:
        return None
    sender = cs.Actor("system", display_name=GUILD_TITLE, system_id=GUILD_SYSTEM_ID)
    body = bid_sentence(order_id=order_id, title=title, bid_id=bid_id, bidder_did=bidder_did, price=price,
                        currency=currency, eta_seconds=eta_seconds)
    msg, dup = await cs.insert_message(db, conv, None, sender, "system", body, None,
                                       client_ref=f"gbid-{order_id}-{bid_id}"[:64], rail_author=True,
                                       mark_read=False)
    if dup:
        return None
    payload = cs.serialize_message(msg)
    recipients = await cs.recipients_snapshot(db, conv, sender)
    if recipients:
        cs.deliver(conv.id, conv.kind, payload, recipients, GUILD_TITLE)
    return payload


async def notify_bid(**kw: Any) -> None:
    """The background entry, in its own session after the bid committed; never raises (the bid stands either way)."""
    from ..database import get_db_context
    try:
        async with get_db_context() as db:
            await post_bid(db, **kw)
    except Exception as e:  # noqa: BLE001 — a notice is a display of the bid, which is already recorded
        logger.warning("[GUILD] the poster agent's bid notice for %s was not posted: %s", kw.get("order_id"), e)
