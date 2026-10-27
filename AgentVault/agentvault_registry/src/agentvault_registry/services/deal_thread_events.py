"""§DEALTHREADS (O-D, 2026-08-29) — the hire negotiation's rail-authored half.

ONE server emitter, the ``org_room_events.py`` pattern verbatim. Chat stays
money-free (§OURSTATE-1 law): every function here runs AFTER an existing
contract rail has already moved and committed its state, and posts a RAIL-ONLY
``engagement.*`` card into the client↔provider DEAL THREAD — a record, never a
lever. The rules it encodes:

  * **Only the engage rail OPENS a thread** (``open_thread=True`` on the engage
    body — the client's explicit choice, default OFF, §HIRECOHERE's
    offer-is-a-decision law extended to the conversation). Every later
    transition posts ONLY into a thread that already exists — an accept or a
    settlement must never conjure a conversation (the org-room "a money event
    never creates a room" law, verbatim).
  * **Exactly-once per transition.** client_ref derives from the contract id +
    transition, so a retried caller re-posts nothing (insert_message dedupes on
    (sender, client_ref) per thread).
  * **Failures are contained.** Post-commit, best-effort, swallowed: a thrown
    card must never poison the contract path it is reporting on.
  * **Cross-frame: the thread lives on the CLIENT's registry** (where the
    contract lives). The provider's participant row is its DID; whether the
    provider can READ it from home is the chat-federation lane's business —
    the thread is sugar, never the rail.
"""
import hashlib
import logging
import os
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Conversation, ConversationParticipant
from . import chat_service as cs

logger = logging.getLogger(__name__)

FRAME_CCY = (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"

# The contract rail actor — the org-ledger shape: a rail, never a participant.
DEAL_RAIL = cs.Actor("system", display_name="Contract rail", system_id="deal-rail")


def _client_ref(kind: str, ref: str) -> str:
    return "dealcard-" + hashlib.sha1(f"{kind}|{ref}".encode()).hexdigest()[:32]


def _deal_pair_key(client_did: str, provider_did: str) -> str:
    return cs.pair_key("dm", cs.principal_key("agent", client_did),
                       cs.principal_key("agent", provider_did))


async def _thread(db: AsyncSession, client_did: str, provider_did: str,
                  *, create: bool) -> Optional[Conversation]:
    """The client↔provider deal thread (an ordinary dm between the two agent
    principals). ``create=True`` only from the engage rail; both participants
    are born ACTIVE — the contract object IS the consent, so the stranger
    defusing that guards unsolicited first contact does not apply here (and
    rail-only cards therefore can never appear in a defused thread)."""
    pk = _deal_pair_key(client_did, provider_did)
    conv = (await db.execute(select(Conversation).where(
        Conversation.dm_pair_key == pk))).scalars().first()
    if conv is not None or not create:
        return conv
    conv = Conversation(kind="dm", created_by_ptype="agent",
                        created_by_id=str(client_did), dm_pair_key=pk)
    db.add(conv)
    try:
        await db.flush()
    except Exception:  # noqa: BLE001 — pair-key race: someone else created it
        await db.rollback()
        return (await db.execute(select(Conversation).where(
            Conversation.dm_pair_key == pk))).scalars().first()
    db.add_all([
        ConversationParticipant(conversation_id=conv.id, ptype="agent",
                                agent_did=client_did, role="owner", state="active"),
        ConversationParticipant(conversation_id=conv.id, ptype="agent",
                                agent_did=provider_did, role="member", state="active"),
    ])
    await db.commit()
    return conv


async def _post(db: AsyncSession, conv: Conversation, ctype: str,
                data: dict, refs: dict, ref: str) -> None:
    card = {"v": 1, "type": ctype, "data": data, "refs": refs}
    msg, dup = await cs.insert_message(
        db, conv, None, DEAL_RAIL, "card", None, card,
        client_ref=_client_ref(ctype, ref), rail_author=True, mark_read=False)
    if dup:
        return
    try:
        payload = cs.serialize_message(msg)
        recipients = await cs.recipients_snapshot(db, conv, DEAL_RAIL)
        if recipients:
            cs.deliver(
                conv.id, conv.kind, payload, recipients, DEAL_RAIL.display_name)
    except Exception:  # noqa: BLE001 — a missed live update is not an outage
        logger.debug("[DEALTHREADS] fan-out skipped", exc_info=True)


def _c(c: dict, key: str) -> Optional[str]:
    v = c.get(key)
    return str(v) if v is not None else None


async def _home_label(db: AsyncSession, c: dict) -> Optional[str]:
    """The provider home as a HUMAN name. The federated accept overwrites
    `counterparty_home_registry` with the peer's SPIFFE identity (the accept's
    `via`), so a card reading the column raw would show a machine URI where the
    offer card said "Frame-B" (§HIRECOHERE: name the registry, never the SPIFFE
    id). Resolve through the SAME §XHIRE predicate; fall back to the raw value
    rather than dropping the fact."""
    hr = c.get("counterparty_home_registry")
    if not hr:
        return None
    hr = str(hr)
    if not hr.startswith("spiffe://"):
        return hr
    try:
        from agentvault_registry.services import contract_xframe as xf
        name = await xf.resolve_peer_name(db, hr)
        return name or hr
    except Exception:  # noqa: BLE001
        return hr


async def post_offer(db: AsyncSession, c: dict) -> None:
    """The offer MINTED — the ONLY entry point that may create the thread."""
    try:
        if not c.get("provider_did"):
            return  # an open offer has no counterparty to converse with
        conv = await _thread(db, c["client_did"], c["provider_did"], create=True)
        if conv is None:
            return
        data = {"contract_id": c["id"], "title": (c.get("title") or "")[:200],
                "total": str(c.get("total_amount")), "currency": c.get("currency") or FRAME_CCY,
                "provider_did": c["provider_did"]}
        if c.get("offer_expires_at"):
            # silence is answered by the TTL, not by read receipts (law)
            data["offer_expires_at"] = str(c["offer_expires_at"])
        if c.get("counterparty_home_registry"):
            data["provider_home"] = _c(c, "counterparty_home_registry")
        await _post(db, conv, "engagement.offer", data,
                    {"contract_id": c["id"]}, f"{c['id']}|offer")
    except Exception:  # noqa: BLE001
        logger.warning("[DEALTHREADS] offer card not posted for %s", c.get("id"), exc_info=True)


async def post_accepted(db: AsyncSession, c: dict) -> None:
    try:
        if not c.get("provider_did"):
            return
        conv = await _thread(db, c["client_did"], c["provider_did"], create=False)
        if conv is None:
            return
        data = {"contract_id": c["id"], "total": str(c.get("total_amount")),
                "currency": c.get("currency") or FRAME_CCY}
        if c.get("escrow_ref"):
            data["escrow_ref"] = _c(c, "escrow_ref")
        await _post(db, conv, "engagement.accepted", data,
                    {"contract_id": c["id"]}, f"{c['id']}|accepted")
    except Exception:  # noqa: BLE001
        logger.warning("[DEALTHREADS] accepted card not posted for %s", c.get("id"), exc_info=True)


async def post_milestone(db: AsyncSession, c: dict, seq: int,
                         title: Optional[str] = None) -> None:
    try:
        if not c.get("provider_did"):
            return
        conv = await _thread(db, c["client_did"], c["provider_did"], create=False)
        if conv is None:
            return
        data = {"contract_id": c["id"], "seq": int(seq),
                "title": (title or f"Milestone {seq}")[:200]}
        await _post(db, conv, "engagement.milestone", data,
                    {"contract_id": c["id"]}, f"{c['id']}|milestone|{int(seq)}")
    except Exception:  # noqa: BLE001
        logger.warning("[DEALTHREADS] milestone card not posted for %s", c.get("id"), exc_info=True)


async def post_settled(db: AsyncSession, c: dict, seq: int, amount, *,
                       completed: bool) -> None:
    try:
        if not c.get("provider_did"):
            return
        conv = await _thread(db, c["client_did"], c["provider_did"], create=False)
        if conv is None:
            return
        data = {"contract_id": c["id"], "seq": int(seq), "amount": str(amount),
                "currency": c.get("currency") or FRAME_CCY, "completed": bool(completed)}
        home = await _home_label(db, c)
        if home:
            data["provider_home"] = home
        await _post(db, conv, "engagement.settled", data,
                    {"contract_id": c["id"]}, f"{c['id']}|settled|{int(seq)}")
    except Exception:  # noqa: BLE001
        logger.warning("[DEALTHREADS] settled card not posted for %s", c.get("id"), exc_info=True)
