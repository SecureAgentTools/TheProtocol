"""§OURSTATE-3b — the peer-facing half of cross-registry chat.

Two endpoints, both PEER-authenticated (mTLS / license / internal secret, via
the shared `require_peer_registry_identity` gate — one gate, every federation
surface, so a revoked operator stops working everywhere at once):

  POST /api/v1/federation/chat/deliver      host → resident: mirror a message.
  POST /api/v1/federation/chat/relay-send   resident → host: a resident's own
                                            person wrote; the HOST assigns seq.

Both are idempotent, because the wire is at-least-once by design: `deliver`
lands a repeat once (unique conversation+remote_seq) and `relay-send` lands a
repeat once (unique conversation+sender+client_ref, the same key the offline
queue has always used).

Peer identity is checked TWICE on purpose: the transport proves which registry
is calling, and the envelope's `host_registry` must ALSO resolve to an active
peer row. A caller that authenticates as one peer cannot then claim to be
speaking for another.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.federation_auth import require_peer_registry_identity
from ..database import get_db
from ..models import Conversation, ConversationParticipant
from ..services import chat_federation as fed
from ..services import chat_service as cs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/federation/chat", tags=["OurChat Federation"])


def _translate(e: Exception):
    if isinstance(e, fed.FederationOff):
        # 501, not 403: the capability is absent here, which is a different
        # fact from "you may not". A peer should stop trying, not retry.
        return HTTPException(status_code=501, detail=str(e))
    if isinstance(e, cs.ChatError):
        return HTTPException(status_code=e.status_code, detail=e.detail)
    return None


@router.post("/deliver")
async def deliver(
    envelope: Dict[str, Any],
    peer: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
):
    """Mirror one message from the thread's HOST into this registry.

    Returns `duplicate: true` with 200 for a repeat: the host counts that as
    delivered and stops retrying, which is why the receive must never 500 on a
    message it already has.
    """
    try:
        out = await fed.receive_delivery(db, envelope, peer)
    except Exception as e:  # noqa: BLE001
        http = _translate(e)
        if http:
            raise http
        logger.exception("[CHATFED] receive failed")
        raise HTTPException(status_code=500, detail="delivery could not be mirrored")

    # Realtime for OUR residents, POST-COMMIT (§ESDUP) — they read their own
    # registry, so this is the only push that reaches them.
    if not out.get("duplicate") and (out.get("residents") or out.get("resident_agents")):
        m_in = envelope.get("message") or {}
        payload = {"id": out.get("message_id"), "seq": out.get("seq"),
                   "conversation_id": out.get("conversation_id"),
                   "kind": m_in.get("kind"), "body": m_in.get("body"), "card": m_in.get("card"),
                   "sender_ptype": out.get("sender_ptype") or "remote",
                   "sender_id": out.get("sender_local") or (m_in.get("sender") or {}).get("id"),
                   "sender_name": out.get("sender_display"), "client_ref": m_in.get("client_ref")}
        # §TWOAGENT G1 step 2: the recipients are the mirror's ACTIVE local rows (developers AND agents), never the
        # sender itself: our own relayed message coming home with its canonical seq must not wake the agent that
        # wrote it (the echo half of the loop guard). A pending agent is told of the knock instead.
        sender_key = cs.principal_key(out.get("sender_ptype") or "remote", out.get("sender_local") or "")
        conv = await cs._get_conversation(db, out["conversation_id"])
        recipients = await cs.recipients_snapshot(db, conv, _KeyOnly(sender_key))
        cs.deliver(
            out["conversation_id"], "dm", payload, recipients,
            str(out.get("sender_display") or ""))
        for did in out.get("pending_agents") or []:
            cs.spawn(cs.notify_request_received(
                out["conversation_id"], "dm", did, payload, str(out.get("sender_display") or "")))
    return out


class _KeyOnly:
    """The one attribute `recipients_snapshot` reads from a sender: its principal key."""

    def __init__(self, key: str):
        self.key = key


class StateChange(BaseModel):
    conversation_ref: str = Field(..., max_length=64, description="The HOST's conversation id")
    participant_key: str = Field(..., max_length=320, description="id@https://their.registry")
    state: str = Field(..., pattern="^(active|left|join)$")
    # §TWOAGENT G1 household seat (V0436): a join names the ACTIVE agent participant the owner joins through (its home
    # vouches for both), the owner's display name for the visible join, and that row's client_ref (chosen by the home).
    household_of: Optional[str] = Field(None, max_length=320)
    participant_display: Optional[str] = Field(None, max_length=200)
    client_ref: Optional[str] = Field(None, min_length=8, max_length=64)


@router.post("/state")
async def state_change(
    req: StateChange,
    peer: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
):
    """
    A resident's home says that its participant accepted (or left) a thread this registry hosts. Only the
    participant's own home may say so; accepting a pending request tells the requester's owner. Peer registries only
    (mTLS).

    \f
    §TWOAGENT G1 step 2: a resident's home says its participant ACCEPTED (or left) a thread this registry hosts.
    Only the participant's own home may say so; an accept of a pending knock tells the knocker's owner.
    """
    if not fed.federation_enabled():
        raise HTTPException(status_code=501, detail="cross-registry chat is not enabled on this registry")
    try:
        return await fed.apply_remote_state(db, req.conversation_ref, req.participant_key, req.state, peer,
                                            household_of=req.household_of,
                                            participant_display=req.participant_display, client_ref=req.client_ref)
    except cs.ChatError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


class RelaySend(BaseModel):
    conversation_ref: str = Field(..., max_length=64,
                                  description="The HOST's conversation id")
    sender_key: str = Field(..., max_length=320,
                            description="handle@https://sender.registry")
    sender_display: str = Field("", max_length=200)
    kind: str = Field("text", max_length=12)
    body: Optional[str] = Field(None, max_length=8192)
    card: Optional[Dict[str, Any]] = None
    client_ref: str = Field(..., min_length=8, max_length=64)


@router.post("/relay-send", status_code=201)
async def relay_send(
    req: RelaySend,
    peer: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
):
    """A resident's person wrote in a thread WE host. We assign the seq (the
    host is the only writer of it), store, and fan out to everyone, including
    back to the sender's own registry, so their mirror carries the canonical
    ordering rather than a local guess."""
    if not fed.federation_enabled():
        raise HTTPException(status_code=501,
                            detail="cross-registry chat is not enabled on this registry")
    parsed = fed.parse_remote_key(req.sender_key)
    if not parsed:
        raise HTTPException(status_code=422,
                            detail="sender_key must be handle@https://their.registry")
    sender_handle, sender_base = parsed
    try:
        await fed.assert_peer_allowed(db, sender_base)
    except cs.ChatError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    # §TWOAGENT G1 step 2: caps per thread and per peer, and a tighter one for an AGENT sender, because two agents
    # that answer automatically would otherwise relay into each other forever (the loop guard's rate half).
    if (not await fed.fed_rate_ok("relay_thread", req.conversation_ref)
            or not await fed.fed_rate_ok("relay_peer", sender_base)
            or (sender_handle.lower().startswith("did:")
                and not await fed.fed_rate_ok("relay_agent_thread", req.conversation_ref))):
        raise HTTPException(status_code=429, detail="this thread's cross-registry message rate is capped; slow down "
                                                    "(an agent answering automatically is capped tighter)")
    # §TWOAGENT (2026-09-23): only the sender's own home may relay for it. Any active peer could relay as another
    # peer's participant, because the caller was checked against nothing.
    if not await fed.caller_is(db, peer, sender_base):
        raise HTTPException(status_code=403, detail="the calling registry is not the sender's home registry")

    conv = (await db.execute(select(Conversation).where(
        Conversation.id == req.conversation_ref))).scalars().first()
    if conv is None or conv.host_registry:
        # Either we do not know it, or we are a mirror too — in both cases we
        # are not the host and must not invent a seq for someone else's thread.
        raise HTTPException(status_code=404, detail="this registry does not host that thread")

    part = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id,
        ConversationParticipant.ptype == "remote",
        ConversationParticipant.remote_key == req.sender_key))).scalars().first()
    if part is None:
        raise HTTPException(status_code=403,
                            detail=f"'{req.sender_key}' is not a participant in that thread")
    if part.state == "left":
        raise HTTPException(status_code=409, detail="that participant has left the thread")

    actor = cs.Actor("remote", display_name=req.sender_display or req.sender_key)
    # Actor has no 'remote' branch by design (it models THIS registry's
    # principals); the insert path takes the sender fields explicitly instead.
    queued = []

    async def _queue(m):
        # §TWOAGENT G1 step 4: out to every remote participant's home (the sender's too, so its mirror learns the
        # canonical seq), in the message's own transaction: a failure here stores nothing and the sender's home
        # answers "NOT sent", where it used to store a message no other registry would ever receive.
        try:
            queued.append(await fed.enqueue_delivery(db, conv, m, req.sender_display or req.sender_key))
        except Exception as e:  # noqa: BLE001 — refused by name, never swallowed
            await db.rollback()
            logger.warning("[CHATFED] relay-send: delivery rows not written for %s: %s", conv.id, type(e).__name__)
            raise cs.ChatError(503, "the relayed message could not be queued for delivery; nothing was stored") from e
    try:
        msg, duplicate = await cs.insert_remote_message(
            db, conv, part, req.sender_key, req.sender_display or req.sender_key,
            req.kind, req.body, req.card, req.client_ref, before_commit=_queue)
    except cs.ChatError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    del actor

    payload = cs.serialize_message(msg)
    payload["sender_name"] = req.sender_display or req.sender_key
    if not duplicate:
        # §TWOAGENT G1 step 3: the REAL sender, so a participant here who blocks that remote principal is skipped
        # (it used to be a stand-in developer -1, which nobody could block)
        recipients = await cs.recipients_snapshot(db, conv, _KeyOnly(cs.principal_key("remote", req.sender_key)))
        cs.deliver(
            conv.id, conv.kind, payload, recipients, payload["sender_name"])
        logger.info("[CHATFED] relay-send accepted seq=%s, %s deliveries queued", msg.seq, sum(queued))
    return {"seq": int(msg.seq), "duplicate": duplicate, "conversation_id": conv.id,
            "peer": peer}
