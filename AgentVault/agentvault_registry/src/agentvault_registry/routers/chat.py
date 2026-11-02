"""§OURSTATE-1 — the OurChat chat API (`/api/v1/chat`).

Dual-auth throughout (developer JWT or agent JWT — the §POCKETBRIDGE5 disputes
precedent via `get_current_actor_for_read`): the recorded sender is ALWAYS the
authenticated principal, never a client claim. The one exception is
`/service-call`, which is agent-JWT-only because the caller IS the payer.

Law 1 (chat has NO money code) is structural here: the only endpoint that
touches value is `/conversations/{id}/service-call`, and it moves money by
firing this registry's OWN `/a2a-payment/buy` over loopback with the CALLER's
JWT (the teg_send.py smart-send precedent) — one authorize, every RBAC/SSRF/
settlement gate intact, and the honest outcome written back as a
`service.result` card. Delivery of every message happens POST-COMMIT only
(§ESDUP), via services/chat_service.fan_out_message.
"""
from __future__ import annotations

import datetime
import functools
import logging
import os
from typing import Any, Dict, Literal, Optional

import httpx
from fastapi import (APIRouter, Depends, File, HTTPException, Query, Request,
                     Security, UploadFile)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Agent, Conversation
from ..security import (get_current_actor_for_read, get_current_actor_for_read_or_key, get_current_agent,
                        get_current_developer, oauth2_scheme_required)
from ..services import chat_service as cs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["OurChat Chat"])

_SELF_BASE = os.getenv("REGISTRY_SELF_URL", "http://localhost:8000").rstrip("/")

# One shared client for the service-call loopback. The /buy composition has
# 30s legs (authorize / call / settle) — 150s covers the worst honest chain.
_buy_client: Optional[httpx.AsyncClient] = None


def _get_buy_client() -> httpx.AsyncClient:
    global _buy_client
    if _buy_client is None or _buy_client.is_closed:
        _buy_client = httpx.AsyncClient(timeout=httpx.Timeout(150.0, connect=10.0))
    return _buy_client


def chat_errors(fn):
    """Translate chat_service.ChatError → HTTPException (the service never
    imports FastAPI)."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except cs.ChatError as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)
    return wrapper


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class TargetSpec(BaseModel):
    ptype: Literal["developer", "agent"]
    developer_id: Optional[int] = None
    agent_did: Optional[str] = Field(None, max_length=255)
    # §OURSTATE-3: `@name` is an ADDRESS. Resolved server-side (never by the
    # client guessing an id), so a handle in a QR code or a shared link is a
    # first-class way to reach someone.
    handle: Optional[str] = Field(None, max_length=33)
    # §OURSTATE-3b: `handle@https://their.registry` — a person on a PEER
    # registry. This registry becomes the HOST of the resulting thread.
    remote_key: Optional[str] = Field(None, max_length=320)

    def key_parts(self) -> tuple:
        if self.ptype == "developer":
            if self.developer_id is None:
                raise HTTPException(422, "target.developer_id required for ptype=developer")
            return "developer", str(self.developer_id)
        if not self.agent_did:
            raise HTTPException(422, "target.agent_did required for ptype=agent")
        return "agent", self.agent_did


class FirstMessage(BaseModel):
    kind: Literal["text", "card"] = "text"
    body: Optional[str] = Field(None, max_length=8192)
    card: Optional[Dict[str, Any]] = None
    client_ref: str = Field(..., min_length=8, max_length=64)


class ConversationCreate(BaseModel):
    kind: Literal["dm", "agent_service"]
    target: TargetSpec
    first_message: Optional[FirstMessage] = None
    # §OURSTATE-5a — the reference of a transfer that ALREADY happened, when
    # the recipient prices first contact. The registry verifies it at the
    # RECEIVER's ledger and spends it; chat never moves the money itself.
    intro_payment_ref: Optional[str] = Field(None, max_length=128)


class MessagePost(BaseModel):
    kind: Literal["text", "card"] = "text"
    body: Optional[str] = Field(None, max_length=8192)
    card: Optional[Dict[str, Any]] = None
    client_ref: str = Field(..., min_length=8, max_length=64)
    reply_to: Optional[str] = Field(None, max_length=36)


class ReadMark(BaseModel):
    seq: int = Field(..., ge=0)


class BoardWrite(BaseModel):
    """V0652 (ac): the board's whole new text (markdown; empty clears it), and the revision it was written against."""
    text: str = Field(..., max_length=4000)
    base_rev: int = Field(..., ge=0)


class BoardEditors(BaseModel):
    """V0652 (ac): the members the owner names to keep the board (principal keys dev:<id>, agt:<did>)."""
    editors: list = Field(default_factory=list)


class CardUpdate(BaseModel):
    """V0652 (aa): the card's new state (the whole card, its type unchanged)."""
    card: Dict[str, Any]


class MuteBody(BaseModel):
    muted: bool = True
    # V0652 (ak): when a mute set for a while ends (in the future, at most 30 days); without it, until lifted
    until: Optional[datetime.datetime] = None


class PingBody(BaseModel):
    client_ref: str = Field(..., min_length=8, max_length=64)


class BlockBody(BaseModel):
    ptype: Literal["developer", "agent", "remote"]
    developer_id: Optional[int] = None
    agent_did: Optional[str] = Field(None, max_length=255)
    # §TWOAGENT G1 step 3: a principal on a PEER registry, `id@https://their.registry` (a handle, dev:N or a DID)
    remote_key: Optional[str] = Field(None, max_length=320)


def _block_key(req: "BlockBody") -> str:
    """The principal key a block names, for all three kinds (one place, both routes)."""
    if req.ptype == "developer":
        if req.developer_id is None:
            raise cs.ChatError(422, "developer_id required")
        return cs.principal_key("developer", req.developer_id)
    if req.ptype == "agent":
        if not req.agent_did:
            raise cs.ChatError(422, "agent_did required")
        return cs.principal_key("agent", req.agent_did)
    from ..services import chat_federation as fed
    parsed = fed.parse_remote_key(req.remote_key or "")
    if not parsed:
        raise cs.ChatError(422, "remote_key must be id@https://their.registry")
    key = fed.remote_key(parsed[0], parsed[1])
    # A participant row holds a 320-character address and a block row fewer (chat_blocks.blocked_id): an address
    # the block cannot store is refused by name here, not a StringDataRightTruncation 500 at the INSERT.
    limit = cs.ChatBlock.__table__.c.blocked_id.type.length
    if len(key) > limit:
        raise cs.ChatError(422, f"remote_key too long to block ({limit} characters)")
    return cs.principal_key("remote", key)


class ServiceCallBody(BaseModel):
    client_ref: str = Field(..., min_length=8, max_length=64)
    text: Optional[str] = Field(None, max_length=4096)
    payload: Optional[Dict[str, Any]] = None
    amount: Optional[str] = Field(None, description="Amount in YOUR currency; omit to pay the quote")
    ttl_seconds: int = Field(900, ge=60, le=3600)


# ---------------------------------------------------------------------------
# Shared plumbing
# ---------------------------------------------------------------------------

async def _sender_owner_dev_id(db: AsyncSession, actor: cs.Actor) -> Optional[int]:
    if actor.ptype == "developer":
        return actor.developer_id
    owners = await cs.agent_owner_map(db, [actor.agent_did or ""])
    return owners.get(actor.agent_did or "")


async def _named_sender(db: AsyncSession, sender: cs.Actor) -> cs.Actor:
    """§TWOAGENT #5 (2026-09-23): an AGENT actor's display name falls back to its DID (the agents table has no name
    column; names live on agent_cards), so every message it sent went out with sender_name = the raw DID: in the
    webhook payload, the push title and the stored preview, while the conversation list showed the card's name for the
    same agent. Resolve the card name once, with the resolver the message list already uses."""
    if sender.ptype != "agent" or not sender.agent_did or sender.display_name not in ("", sender.agent_did):
        return sender
    try:
        key = cs.principal_key("agent", sender.agent_did)
        name = (await cs.display_names(db, [key])).get(key)
        if name and name != sender.agent_did:
            # V0653's recut (the pair proof of 2026-11-02, session-tester seq 962): the card's name, and NOTHING else of
            # the sender rebuilt. The new Actor dropped how the line was sent (V0653 (w)'s sent_with: an agent with a
            # card stored NULL) and who sent it through the agent (V0652 (aj)'s sent_by: "sent by its owner" was never
            # stored for an agent with a card, production included).
            return cs.Actor("agent", developer_id=sender.developer_id, agent_did=sender.agent_did, display_name=name,
                            system_id=sender.system_id, sent_by=sender.sent_by, sent_with=sender.sent_with)
    except Exception as e:  # noqa: BLE001 — a label; the DID still identifies the sender
        logger.debug("[CHAT] sender name lookup skipped for %s: %s", sender.agent_did, e)
    return sender


async def _send_and_fan_out(db: AsyncSession, conv, my_row, actor: cs.Actor,
                            kind: str, body: Optional[str], card: Optional[dict],
                            client_ref: str, reply_to: Optional[str] = None,
                            *, rail_author: bool = False, is_ping: bool = False,
                            sender_override: Optional[cs.Actor] = None,
                            extra_before_commit=None) -> dict:
    """Rate-gate, insert, then fan out POST-COMMIT. Returns the serialized
    message. A duplicate client_ref returns the original and fans out nothing."""
    gate_key = f"msg:{actor.key}"
    if not await cs._rate_gate(gate_key, cs.RL_MSG_LIMIT, cs.RL_MSG_WINDOW_S):
        raise cs.ChatError(429, "message rate limit reached — slow down")

    if kind == "card" and isinstance(card, dict) and card.get("type") == "media" and isinstance(card.get("data"), dict):
        # V0652 (ae): a file card's preview is what THIS registry reads from the stored file, never what a sender wrote
        from ..services import chat_media
        card = await chat_media.ground_card(db, conv.id, card)

    if getattr(conv, "host_registry", None):
        # §TWOAGENT G1 (2026-09-23): this thread is a MIRROR of one another registry hosts. The host is the only writer
        # of its seq, so the message goes THERE and comes back with the canonical seq; storing it here first would
        # fork the thread (it used to: a resident's reply stayed in its own mirror and the other side never saw it).
        return await _relay_resident_send(db, conv, my_row, actor, kind, body, card, client_ref)

    sender = await _named_sender(db, sender_override or actor)
    from ..services import chat_federation as fed
    queue = None
    if fed.federation_enabled():
        # §OURSTATE-3b / §TWOAGENT G1 step 4: if THIS registry hosts a federated thread, the message's delivery rows for
        # every remote participant's home commit WITH it. They used to be queued after it, in a second transaction whose
        # failure was only logged, and a retry of the same client_ref returned early: a hosted message could exist that
        # no other registry would ever see. Now it is both or neither, and neither says so.
        async def _queue(m):
            try:
                await fed.enqueue_delivery(db, conv, m, sender.display_name)
            except Exception as e:  # noqa: BLE001 — refused by name below, never swallowed
                await db.rollback()
                logger.warning("[CHATFED] delivery rows not written for %s: %s", conv.id, type(e).__name__)
                raise cs.ChatError(503, "this message could not be queued for the other registry, so nothing was "
                                        "sent; retry") from e
        queue = _queue
    if extra_before_commit is not None:
        # V0650 (l): a record that must exist WITH its card (an approval request) is written in the message's own
        # transaction, after the federation delivery rows, so neither can exist without the other.
        _fed_queue = queue

        async def _both(m):
            if _fed_queue is not None:
                await _fed_queue(m)
            await extra_before_commit(m)
        queue = _both
    msg, duplicate = await cs.insert_message(
        db, conv, my_row, sender, kind, body, card, client_ref, reply_to,
        rail_author=rail_author, before_commit=queue)
    payload = cs.serialize_message(msg)
    payload["sender_name"] = sender.display_name
    if duplicate:
        await cs._rate_peek_release(gate_key)
        return payload

    recipients = await cs.recipients_snapshot(db, conv, sender)
    owner_dev = await _sender_owner_dev_id(db, actor)
    cs.deliver(
        conv.id, conv.kind, payload, recipients, sender.display_name,
        is_ping=is_ping, sender_owner_dev_id=owner_dev)

    return payload


async def _relay_resident_send(db: AsyncSession, conv, my_row, actor: cs.Actor, kind: str, body: Optional[str],
                               card: Optional[dict], client_ref: str) -> dict:
    """A resident's message in a mirrored thread, handed to the thread's host (developers since G1 step 1, agents since
    step 2). Replying to a request IS accepting it, as locally: a pending row turns active and the host hears it."""
    from ..services import chat_federation as fed
    if not fed.federation_enabled():
        raise cs.ChatError(501, "cross-registry chat is not enabled on this registry")
    if actor.ptype not in ("developer", "agent"):
        raise cs.ChatError(409, "only a developer or an agent can write in a cross-registry thread")
    state = getattr(my_row, "state", "active")
    if state == "left":
        raise cs.ChatError(409, "you have left this conversation")
    # The id this seat is listed under at the host (fed.local_wire_id, the one answer for a local principal on the wire).
    handle = await fed.local_wire_id(db, actor.ptype, actor.agent_did if actor.ptype == "agent" else actor.developer_id)
    sender_key = fed.remote_key(handle, fed.self_base_url())
    out = await fed.relay_to_host(db, conv, sender_key, actor.display_name, kind, body, card, client_ref)
    if state == "pending":
        my_row.state = "active"
        await db.commit()
        cs.spawn(fed.announce_state_to_host(conv.host_registry, conv.remote_ref, sender_key, "active"))
    return {"relayed": True, "host_registry": conv.host_registry, "conversation_id": conv.id,
            "host_seq": out.get("seq"), "duplicate": bool(out.get("duplicate")), "client_ref": client_ref,
            "note": "the host registry assigned the seq; the message appears in this thread when the host delivers it "
                    "back (seconds)"}


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

@router.post("/conversations", status_code=201)
@chat_errors
async def create_conversation(
    req: ConversationCreate,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """Create (or dedup-return) a pair conversation. A first message from a
    stranger lands the recipient's side in their Requests lane; they see the
    thread only after accepting. Blocks are honored silently."""
    actor = cs.actor_from_auth(actor_dict)
    if req.target.remote_key:
        return await _create_federated(db, actor, req)
    if req.kind == "dm" and req.target.ptype == "agent" and req.target.agent_did:
        # §TWOAGENT G1 step 2 (2026-09-23): a dm to an agent this registry holds only as a MIRROR goes to its home
        # when cross-registry chat is on here (the host is this registry); otherwise the honest refusal stands.
        from ..services import chat_federation as fed
        if fed.federation_enabled():
            home_key = await fed.home_key_for_mirror(db, req.target.agent_did)
            if home_key:
                req.target.remote_key = home_key
                return await _create_federated(db, actor, req)
    if req.target.ptype == "developer" and req.target.developer_id is None and req.target.handle:
        resolved = await cs.resolve_handle(db, req.target.handle)
        if resolved is None:
            raise cs.ChatError(404, f"no account carries the handle "
                                    f"'{cs.normalize_handle(req.target.handle)}'")
        req.target.developer_id = resolved
    t_type, t_id = req.target.key_parts()
    conv, created, my_row = await cs.create_conversation(
        db, actor, req.kind, t_type, t_id, intro_payment_ref=req.intro_payment_ref)

    first = None
    if req.first_message is not None:
        first = await _send_and_fan_out(
            db, conv, my_row, actor,
            req.first_message.kind, req.first_message.body, req.first_message.card,
            req.first_message.client_ref)

    # §TWOAGENT #1: a stranger's first message to an AGENT lands in its Requests lane, where the fan-out above cannot
    # reach it (recipients are ACTIVE participants). Tell the agent's owner, owner-scoped, after the commit.
    if created and first is not None:
        try:
            pending_did = await cs.pending_agent_target(db, conv, t_type, t_id)
            if pending_did:
                cs.spawn(cs.notify_request_received(
                    conv.id, conv.kind, pending_did, first, actor.display_name))
            # V0652 (z): a person is told too (chat.request), not only an agent's owner
            pending_dev = await cs.pending_developer_target(db, conv, t_type, t_id)
            if pending_dev:
                cs.spawn(cs.notify_developer_request(conv.id, pending_dev, first, actor.display_name))
        except Exception as e:  # noqa: BLE001 — a notice is advisory; the knock itself already landed
            logger.warning("[CHAT] request notice skipped for %s: %s", conv.id, e)

    # §OURSTATE-2 Away mode v1: if the RECIPIENT designated a stand-in and this
    # is a stranger's first knock, the stand-in answers ONCE — disclosed as
    # software, spending nothing. Post-commit, after the caller's own message,
    # and never able to fail the send (away_answer swallows its own errors).
    away = None
    if created and first is not None and conv.kind == "dm":
        t_type, t_raw = req.target.key_parts()
        if t_type == "developer":
            away = await cs.away_answer(db, conv, int(t_raw))
            if away:
                recipients = await cs.recipients_snapshot(
                    db, conv, cs.Actor("agent", agent_did=away.get("sender_id")))
                cs.deliver(
                    conv.id, conv.kind, away, recipients, away.get("sender_name") or "")

    return {"conversation_id": conv.id, "kind": conv.kind, "created": created,
            "my_state": my_row.state, "first_message": first, "away_reply": away}


@router.get("/conversations")
@chat_errors
async def list_conversations(
    state: Literal["active", "requests"] = Query("active"),
    cursor: Optional[str] = Query(None),
    limit: int = Query(30, ge=1, le=cs.LIST_MAX),
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """Inbox (active) or the Requests lane (pending). A developer's inbox spans
    their own rows plus their local agents' rows; unread sums both."""
    actor = cs.actor_from_auth(actor_dict)
    return await cs.list_conversations(db, actor, state=state, cursor=cursor, limit=limit)


@router.get("/conversations/{conversation_id}/messages")
@chat_errors
async def get_messages(
    conversation_id: str,
    before_seq: Optional[int] = Query(None, ge=1),
    limit: int = Query(40, ge=1, le=cs.PAGE_MAX),
    join: bool = Query(False, description="§TWOAGENT G1 (V0437): an agent's OWNER opening its cross-registry thread "
                                          "for the first time is announced to the other side; true confirms it"),
    mentions: Optional[Literal["me"]] = Query(
        None, description="me: only the messages that @mention you (your handle, your card name or your DID)"),
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    actor = cs.actor_from_auth(actor_dict)
    return await cs.list_messages(db, conversation_id, actor,
                                  before_seq=before_seq, limit=limit, join=join, mentions=mentions)


@router.post("/conversations/{conversation_id}/messages", status_code=201)
@chat_errors
async def post_message(
    conversation_id: str,
    req: MessagePost,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """Post one message. Idempotent on client_ref (the offline queue's replay
    contract). Cards are validated against the CLOSED vocabulary; publish
    happens only after commit."""
    actor = cs.actor_from_auth(actor_dict)
    conv = await cs._get_conversation(db, conversation_id)
    my_row = await cs.resolve_membership(db, conv, actor, announce_ok=True)
    msg = await _send_and_fan_out(db, conv, my_row, actor,
                                  req.kind, req.body, req.card,
                                  req.client_ref, req.reply_to)
    # §ROOMBRAIN — @assistant answers ADDRESSED org-room messages only, from
    # records only, post-commit and best-effort (a broken brain never breaks chat).
    if conv.kind == "org" and req.kind == "text":
        from agentvault_registry.services import room_assistant
        await room_assistant.maybe_answer(db, conv, req.body)
    return {"message": msg, "my_state": my_row.state}


@router.put("/conversations/{conversation_id}/messages/{message_id}/card")
@chat_errors
async def update_card(
    conversation_id: str,
    message_id: str,
    req: CardUpdate,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """Update a card in place: the message keeps its place, its card becomes the one sent, and the update is kept
    (who, when, what changed). A `progress` card is updated by whoever posted it; its verdict (passed, failed,
    cancelled) closes it. Every member of the thread sees the update; the verdict also tells the thread's people in
    the app (chat.progress_finished).

    \f
    V0652 (aa), order gwo_840aa2b590306f7eba147758 (services.chat_service.update_card). A `guild.order.live` and an
    `approval.decided` card are kept current by their rails only; any other card stays as it was posted. An update that
    changes nothing answers `changed: false` and writes no revision. V0653: the verdict's notice
    (services.chat_service.notify_progress_finished)."""
    actor = cs.actor_from_auth(actor_dict)
    gate_key = f"msg:{actor.key}"
    if not await cs._rate_gate(gate_key, cs.RL_MSG_LIMIT, cs.RL_MSG_WINDOW_S):
        raise cs.ChatError(429, "message rate limit reached — slow down")
    updater = await _named_sender(db, actor)
    msg, conv, changed = await cs.update_card(db, conversation_id, message_id, updater, req.card)
    if changed and conv is not None:
        await cs.deliver_card_update(db, conv, msg, updater)
        try:
            await cs.notify_progress_finished(db, conv, msg, updater)
        except Exception:  # noqa: BLE001 — the update is committed and delivered; its notice is a courtesy
            logger.warning("[CHAT] the verdict notice of card %s was not sent", message_id, exc_info=True)
    return {"message": msg, "changed": changed}


@router.get("/conversations/{conversation_id}/messages/{message_id}/card/history")
@chat_errors
async def card_history(
    conversation_id: str,
    message_id: str,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """The updates a card took, oldest first: when, who, what changed. A member of the thread reads it."""
    actor = cs.actor_from_auth(actor_dict)
    return await cs.card_history(db, conversation_id, message_id, actor)


@router.get("/conversations/{conversation_id}/board")
@chat_errors
async def read_board(
    conversation_id: str,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """An organization's room's status board (any member): its text, its revision, who last edited it, and whether
    you may edit it."""
    from ..services import chat_board
    return await chat_board.read_board(db, conversation_id, cs.actor_from_auth(actor_dict))


@router.put("/conversations/{conversation_id}/board")
@chat_errors
async def write_board(
    conversation_id: str,
    req: BoardWrite,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """Write the room's status board: the room's owner, or a member the owner named. Send the whole new text and the
    revision you read (`base_rev`); an edit written against an older board is refused (409), so nobody overwrites an
    edit unseen. The room sees the new board at once; nobody is notified.

    \f
    V0652 (ac), order gwo_2ae43c7789db1e808ea1417f (services.chat_board)."""
    from ..services import chat_board
    actor = await _named_sender(db, cs.actor_from_auth(actor_dict))
    board, conv, changed = await chat_board.set_board(db, conversation_id, actor, req.text, req.base_rev)
    if changed:
        cs.spawn(chat_board.fan_out_board(conv, board, actor), what=f"the board update of {conversation_id}")
    return {"board": board, "changed": changed}


@router.get("/conversations/{conversation_id}/board/history")
@chat_errors
async def board_history(
    conversation_id: str,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """Every edit of the room's status board, oldest first: when, who, the text after it."""
    from ..services import chat_board
    return await chat_board.board_history(db, conversation_id, cs.actor_from_auth(actor_dict))


@router.put("/conversations/{conversation_id}/board/editors")
@chat_errors
async def board_editors(
    conversation_id: str,
    req: BoardEditors,
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    """The room's owner names who keeps the status board with them: members and agents of the organization (principal
    keys `dev:<id>`, `agt:<did>`, at most 20). A name stops counting when its principal leaves the organization."""
    from ..services import chat_board
    return await chat_board.set_editors(db, conversation_id, cs.actor_from_auth(actor_dict), req.editors)


@router.post("/conversations/{conversation_id}/read")
@chat_errors
async def read_mark(
    conversation_id: str,
    req: ReadMark,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """Monotonic read floor. Never shown to the counterparty (law 6: no read
    receipts, ever)."""
    actor = cs.actor_from_auth(actor_dict)
    return await cs.mark_read(db, conversation_id, actor, req.seq)


@router.post("/conversations/{conversation_id}/accept")
@chat_errors
async def accept_conversation(
    conversation_id: str,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    actor = cs.actor_from_auth(actor_dict)
    return await cs.set_state(db, conversation_id, actor, "accept")


@router.post("/conversations/{conversation_id}/decline")
@chat_errors
async def decline_conversation(
    conversation_id: str,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    actor = cs.actor_from_auth(actor_dict)
    return await cs.set_state(db, conversation_id, actor, "decline")


@router.post("/conversations/{conversation_id}/leave")
@chat_errors
async def leave_conversation(
    conversation_id: str,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    actor = cs.actor_from_auth(actor_dict)
    return await cs.set_state(db, conversation_id, actor, "leave")


@router.post("/conversations/{conversation_id}/mute")
@chat_errors
async def mute_conversation(
    conversation_id: str,
    req: MuteBody,
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    actor = cs.actor_from_auth(actor_dict)
    return await cs.set_muted(db, conversation_id, actor, req.muted, req.until)


@router.post("/conversations/{conversation_id}/burn")
@chat_errors
async def burn_conversation(
    conversation_id: str,
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    """Burn-for-me (CORE): history before this point stops existing for your
    side. The hold IS the confirmation: the client renders the honest
    footnote; this endpoint just moves the floor."""
    actor = cs.actor_from_auth(actor_dict)
    return await cs.burn_for_me(db, conversation_id, actor)


@router.post("/conversations/{conversation_id}/ping", status_code=201)
@chat_errors
async def ping_conversation(
    conversation_id: str,
    req: PingBody,
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    """The one non-text nudge: a knock, never a siren. Preference-obedient
    (never overrides mute), banned in request-state threads, hard rate-limited
    (1 per 10 minutes per thread, 30 a day)."""
    actor = cs.actor_from_auth(actor_dict)
    conv = await cs._get_conversation(db, conversation_id)
    my_row = await cs.resolve_membership(db, conv, actor, announce_ok=True)
    if my_row.state != "active":
        raise cs.ChatError(409, "you are not active in this conversation")
    # Banned while the thread is still a request — a ping must not knock
    # harder than the request the recipient has not accepted.
    if await cs.thread_is_request(db, conv.id):
        raise cs.ChatError(409, "this thread is still a request — a ping cannot knock harder")

    if not await cs._rate_gate(f"ping:{actor.key}:{conv.id}",
                               cs.RL_PING_THREAD_LIMIT, cs.RL_PING_THREAD_WINDOW_S):
        raise cs.ChatError(429, "one ping per thread per 10 minutes")
    if not await cs._rate_gate(f"pingday:{actor.key}",
                               cs.RL_PING_DAY_LIMIT, cs.RL_PING_DAY_WINDOW_S):
        raise cs.ChatError(429, "daily ping limit reached")

    msg = await _send_and_fan_out(db, conv, my_row, actor,
                                  "system", "ping", None, req.client_ref,
                                  is_ping=True)
    return {"message": msg}


# ---------------------------------------------------------------------------
# Service call — the §BUYSERVICE loop wearing a thread (agent JWT = the payer)
# ---------------------------------------------------------------------------

class ShareCertBody(BaseModel):
    symbol: str = Field(..., max_length=16)
    client_ref: Optional[str] = Field(None, max_length=120)
    # §CERTEVERYBUY — set when the shares were bought on a FOREIGN venue via
    # Passport. The certificate is then fetched from that venue (which holds the
    # register and signs for it) and posted here by the same rail.
    venue_registry: Optional[str] = Field(None, max_length=128)


@router.post("/conversations/{conversation_id}/certificate", summary="Post my holding certificate in the thread", status_code=201)
@chat_errors
async def post_share_certificate(
    conversation_id: str,
    req: ShareCertBody,
    request: Request,
    current_agent: Agent = Security(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Issue the caller's holding certificate (`share.certificate`) and post it in the thread as a rail card. A client
    cannot author this card: the registry builds it from its own read of the caller's AGORA holding and signs it
    with the attestation signer. Holding nothing is refused by name rather than posted as an empty certificate.

    \f
    §SHOWCASESTOCKS — mint the caller's `share.certificate` and post it as a
    RAIL card.

    Why a rail and not a client post: `share.certificate` is in
    RAIL_ONLY_CARDS, so a client cannot author one. That is the point — a
    certificate anybody could type would make every real one worthless. The
    registry mints it here from its OWN read of `org_share_positions`, signs it
    with the attestation signer, and writes it under the rail author.

    Holding nothing refuses BY NAME rather than posting an empty certificate.
    """
    from agentvault_registry.services.share_certificate import build_certificate
    from agentvault_registry.config import settings as _st

    actor = cs.Actor("agent", agent_did=current_agent.did,
                     display_name=getattr(current_agent, "name", None) or current_agent.did)
    conv = await cs._get_conversation(db, conversation_id)
    my_row = await cs.resolve_membership(db, conv, actor, announce_ok=True)
    if my_row.state != "active":
        raise cs.ChatError(409, "you are not active in this conversation")

    venue = (req.venue_registry or "").strip()
    if venue:
        # FOREIGN holding: relay to the venue that keeps the register. This
        # registry deliberately does NOT mint it — see federated_certificate:
        # signing a claim about another registry's cap table would make every
        # certificate worth less. What comes back carries the VENUE's signature.
        from agentvault_registry.services import exchange_passport as _pp

        code, body = await _pp.peer_request(
            db, venue, "POST", "/api/v1/federation/agora-certificate",
            {"agent_did": current_agent.did, "symbol": req.symbol},
        )
        # 🔴 TWO DIFFERENT 404s. The venue answers 404 "holds no X" while the
        # relayed order has not filled yet — retry that. A venue on an older
        # build has no such ROUTE and answers FastAPI's own 404 "Not Found" —
        # retrying that forever would be waiting for something that can never
        # arrive. Tell them apart by the body, and give the caller a status it
        # can act on: 409 = ask again, 501 = this venue cannot issue one.
        _d = ""
        if isinstance(body, dict):
            _d = str(body.get("detail") or (body.get("error") or {}).get("detail") or "")
        if code == 404 and "holds no" in _d:
            raise cs.ChatError(409, f"{venue} has not recorded your {req.symbol.upper()} yet — "
                                    "the relayed order has not filled there")
        if code in (404, 405):
            raise cs.ChatError(501, f"{venue} does not issue holding certificates yet, "
                                    "the points are held there and it has not been rolled")
        if code != 200 or not isinstance(body, dict) or not body.get("certificate"):
            raise cs.ChatError(502, f"{venue} could not issue the certificate "
                                    f"(HTTP {code}): {str(body)[:160]}")
        cert = body["certificate"]
    else:
        cert = await build_certificate(db, current_agent.did, req.symbol,
                                       getattr(_st, "REGISTRY_NAME", "") or "")
    if cert is None:
        raise cs.ChatError(409, f"you hold no {req.symbol.upper()} on this registry, "
                                "so there is nothing to certify")

    card = {"v": 1, "type": "share.certificate",
            "data": {k: cert.get(k) for k in (
                "certificate_id", "symbol", "display_name", "qty", "avg_cost",
                "currency", "total_shares", "venue_registry", "as_of", "digest",
                "signature", "signature_alg", "signature_pubkey_id",
                "unsigned_reason")},
            "refs": {"listing_id": cert.get("listing_id"),
                     "holder_did": cert.get("holder_did")}}
    ref = req.client_ref or f"cert-{cert.get('certificate_id')}"
    msg = await _send_and_fan_out(db, conv, my_row, actor, "card", None, card, ref,
                                  rail_author=True)
    return {"message": msg, "certificate": cert}


@router.post("/conversations/{conversation_id}/service-call", status_code=201)
@chat_errors
async def service_call(
    conversation_id: str,
    req: ServiceCallBody,
    request: Request,
    current_agent: Agent = Security(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Run one priced (or free) service call inside an agent_service thread.

    Writes the ask as a `service.call` card, fires this registry's OWN
    `/a2a-payment/buy` over loopback with the CALLER's JWT (one authorize,
    every gate intact: quote, RBAC, SSRF, settle, release on non-delivery),
    then writes the agent's `service.result` card with the honest outcome:
    "no answer: you were not charged" and "delivered but settlement failed"
    are said in those words. One call in flight per thread; retries are
    idempotent on client_ref and re-run nothing.
    """
    caller_jwt = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not caller_jwt:
        raise HTTPException(401, "Bearer token required")

    actor = cs.Actor("agent", agent_did=current_agent.did,
                     display_name=getattr(current_agent, "name", None) or current_agent.did)
    conv = await cs._get_conversation(db, conversation_id)
    if conv.kind != "agent_service":
        raise cs.ChatError(409, "service calls run only in agent_service threads")
    my_row = await cs.resolve_membership(db, conv, actor, announce_ok=True)
    if my_row.state != "active":
        raise cs.ChatError(409, "you are not active in this conversation")

    # The service agent = the pair-key side that is not the CALLER itself.
    #
    # ⚠ THIS USED TO SKIP THE WHOLE HOUSEHOLD, AND THE TWO MONEY RAILS THEN
    # DISAGREED ABOUT THE SAME ACT. `/a2a-payment/buy` happily sells one of your
    # agents a service from another of your agents — proven, real BVT, §BUYSERVICE
    # — but this wrapper skipped any participant owned by the caller's developer
    # and then reported "could not resolve the service agent", so the identical
    # purchase succeeded through the API and was refused through the chat. That
    # is the §FANOUTFIX class: one question asked in two places, answered
    # differently. Measured 2026-08-24 on the Commander's own demo, where buyer
    # and seller are both his.
    #
    # In an `agent_service` thread the target is not ambiguous — the pair key was
    # built FROM it. Skip only the caller. A human counterparty is still refused
    # by name, because a person does not sell a service call.
    caller_owner = (await cs.agent_owner_map(db, [actor.agent_did or ""])).get(actor.agent_did or "")
    target_did: Optional[str] = None
    for part in (conv.dm_pair_key or "").split("|")[1:]:
        ptype, pid = cs._split_key(part)
        if ptype == "developer":
            if caller_owner is not None and int(pid) == caller_owner:
                continue
            raise cs.ChatError(409, "this thread's counterparty is a human — use a plain message")
        if pid.lower() == (actor.agent_did or "").lower():
            continue
        target_did = pid
    if not target_did:
        raise cs.ChatError(409, "could not resolve the service agent in this thread")

    ask_text = (req.text or "").strip()
    if not ask_text and not req.payload:
        raise cs.ChatError(422, "a service call needs text or a payload")

    # Idempotency: the SAME client_ref returns the recorded pair, re-runs nothing.
    from sqlalchemy import select as _sel
    from ..models import ChatMessage as _CM
    existing = (await db.execute(_sel(_CM).where(
        _CM.conversation_id == conv.id,
        _CM.sender_ptype == "agent",
        _CM.sender_id == actor.sender_id,
        _CM.client_ref == req.client_ref))).scalars().first()
    if existing is not None:
        sibling = (await db.execute(_sel(_CM).where(
            _CM.conversation_id == conv.id,
            _CM.client_ref == cs.result_client_ref(req.client_ref)))).scalars().first()
        return {"duplicate": True,
                "call_message": cs.serialize_message(existing),
                "result_message": cs.serialize_message(sibling) if sibling else None}

    if not await cs.claim_service_inflight(db, conv.id):
        raise cs.ChatError(409, "a service call is already in flight in this thread")

    result_msg_payload = None
    try:
        ask_card = {"v": 1, "type": "service.call",
                    "data": {"ask": ask_text or "[structured payload]", "status": "dispatched"},
                    "refs": {"target_did": target_did}}
        call_msg = await _send_and_fan_out(
            db, conv, my_row, actor, "card", None, ask_card, req.client_ref,
            rail_author=True)

        # ── the SAME composition /buy runs, over loopback, caller's own JWT ──
        buy_body: Dict[str, Any] = {"target_agent_did": target_did,
                                    "ttl_seconds": req.ttl_seconds}
        if req.payload:
            buy_body["payload"] = req.payload
        else:
            buy_body["text"] = ask_text
        if req.amount:
            buy_body["amount"] = req.amount
        try:
            r = await _get_buy_client().post(
                f"{_SELF_BASE}/api/v1/a2a-payment/buy", json=buy_body,
                headers={"Authorization": f"Bearer {caller_jwt}",
                         "Idempotency-Key": f"ourstate-call-{req.client_ref}"})
            buy = r.json() if r.status_code == 200 else {
                "ok": False, "stage": "failed",
                "error": f"buy rail returned HTTP {r.status_code}: {(r.text or '')[:200]}"}
        except httpx.RequestError as e:
            buy = {"ok": False, "stage": "failed",
                   "error": f"buy rail unreachable: {e.__class__.__name__}"}

        # ── the honest result card ──
        settlement = buy.get("settlement_status")
        if buy.get("ok"):
            if settlement in (None, "consumed", "settled") or buy.get("stage") == "settled":
                summary = "delivered"
            elif settlement == "failed":
                summary = ("delivered, but settlement failed — you owe this agent; "
                           f"retry settle on token {buy.get('token_id')}")
            else:
                summary = f"delivered (settlement: {settlement})"
        else:
            charged = settlement not in (None, "released")
            summary = (buy.get("error") or "the agent did not deliver")
            if not charged:
                summary += " — you were not charged"
        charged_ok = bool(buy.get("ok")) and settlement not in ("released", "release_failed")

        result_body = buy.get("result")
        truncated = False
        if result_body is not None:
            import json as _json
            blob = _json.dumps(result_body)
            if len(blob.encode("utf-8", errors="ignore")) > 6000:
                result_body = {"truncated": True, "preview": blob[:2000]}
                truncated = True

        result_card = {"v": 1, "type": "service.result",
                       "data": {"ok": bool(buy.get("ok")), "stage": buy.get("stage"),
                                "summary": summary,
                                # Defence in depth: even if an upstream ever
                                # leaves an authorized amount set, a card that
                                # says "you were not charged" must not also
                                # print a figure next to the word paid.
                                "paid_amount": buy.get("paid_amount") if charged_ok else None,
                                "paid_currency": buy.get("paid_currency") if charged_ok else None,
                                "settlement_status": settlement,
                                "result": result_body,
                                "result_truncated": truncated,
                                "error": buy.get("error") or ""},
                       "refs": {"target_did": target_did,
                                "token_id": buy.get("token_id"),
                                "settlement_tx_id": buy.get("settlement_tx_id")}}
        target_actor = cs.Actor("agent", agent_did=target_did,
                                display_name=buy.get("target_name") or target_did)
        result_msg_payload = await _send_and_fan_out(
            db, conv, my_row, actor, "card", None, result_card,
            cs.result_client_ref(req.client_ref),
            rail_author=True, sender_override=target_actor)
    finally:
        try:
            await cs.release_service_inflight(db, conv.id)
        except Exception as e:  # noqa: BLE001
            logger.warning("[CHAT] inflight release failed for %s: %s", conv.id, e)

    return {"duplicate": False, "call_message": call_msg,
            "result_message": result_msg_payload}


# ---------------------------------------------------------------------------
# Blocks + sync
# ---------------------------------------------------------------------------

@router.get("/blocks")
@chat_errors
async def get_blocks(
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    actor = cs.actor_from_auth(actor_dict)
    return {"blocks": await cs.list_blocks(db, actor)}


@router.post("/blocks", status_code=201)
@chat_errors
async def create_block(
    req: BlockBody,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """Block a principal. Silent by design: shared threads leave your list,
    delivery stops both ways, and the blocked party is told nothing. Since G1 step 3 a principal on a PEER registry
    can be blocked too (ptype remote, remote_key)."""
    actor = cs.actor_from_auth(actor_dict)
    await cs.create_block(db, actor, _block_key(req))
    return {"blocked": True}


@router.delete("/blocks")
@chat_errors
async def remove_block(
    req: BlockBody,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    actor = cs.actor_from_auth(actor_dict)
    removed = await cs.delete_block(db, actor, _block_key(req))
    return {"removed": removed}


@router.get("/sync")
@chat_errors
async def sync(
    since: Optional[str] = Query(None, description="ISO timestamp; default = 24h ago"),
    cursor: Optional[str] = Query(None, max_length=4096,
                                  description="next_cursor from the previous answer (instead of since)"),
    wait: int = Query(0, ge=0, le=cs.SYNC_WAIT_MAX_S,
                      description="Seconds to wait for something new when nothing is there yet (0 to 25)"),
    for_: Optional[str] = Query(None, alias="for", max_length=8,
                                description="`me`: only what reaches you in particular (a mention of you, @all, the "
                                            "room owner's message, a direct message, an approval card of yours)"),
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """Polling catch-up for clients and agent runtimes: everything in your
    active threads since a timestamp, bounds stated in the body.

    Every answer carries `next_cursor`: pass it as `cursor` on the next call and nothing is missed or returned twice.
    With `wait` (up to 25 seconds) the call answers as soon as something new reaches one of your threads, or answers
    empty at the bound, so a client can stay current without polling. Your own sends are included, as before.

    With a cursor the answer also carries `updates`: the cards in your threads that changed in place since then
    (V0652), each the message's current card with its `card_rev`; apply the higher rev. A `wait` ends on an update too.

    With `for=me` the answer holds only what reaches you in particular: a message that mentions you, @all or
    @everyone, a message from the room's owner, any message in a direct conversation, and an approval card you asked
    for or may decide; never your own. Everything else stays on the server, and a `wait` ends only on such a message.
    Its `next_cursor` continues the filtered stream; `plain_cursor` is where it started, so a plain sync from there
    later loses nothing the filter left behind.

    \f
    V0650 (g), order gwo_e0c0c8b4d1a5c6a016077567: the long-poll (services.chat_service.sync_wait). While a call waits
    it holds no database connection and runs no query; fan_out_message wakes it, on any worker over Redis. A registry
    before V0650 answers without next_cursor, which is how a client tells that wait and cursor were not understood.
    V0651 (t), order gwo_cddfbd743842eb65906ef8ab: for=me (services.chat_service.for_me_clause). A registry before
    V0651 drops the parameter and answers everything; the answer's `for` field says the filter was applied.
    """
    if for_ not in (None, "", "me"):
        raise cs.ChatError(422, "for takes one value, me (only what reaches you in particular)")
    actor = cs.actor_from_auth(actor_dict)
    return await cs.sync_wait(db, actor, since=since, cursor=cursor, wait_s=wait, for_me=(for_ == "me"))


@router.get("/unread-count")
@chat_errors
async def unread_count(
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Two numbers for the navigation badge: unread messages, and how many threads hold them. Muted threads are not
    counted.

    \f
    §CHATPOLISH — two numbers for the nav badge: unread messages, and how
    many threads hold them. Muted threads are excluded, because a badge that
    counts what you told it to be quiet about is not a badge.

    ⚠ A LITERAL under a router that also owns `/conversations/{id}` families:
    declared here, above every `{param}` sibling, so the §NOTIFV2
    registration-order trap (which is what left `/notifications/unread-count`
    answering 422 for months) cannot claim it.
    """
    actor = cs.actor_from_auth(actor_dict)
    return await cs.unread_total(db, actor)


# ---------------------------------------------------------------------------
# §OURSTATE-2 — org rooms (the chat as the org's admin panel)
# ---------------------------------------------------------------------------

class RoomActionBody(BaseModel):
    action: Literal["kick", "mute", "unmute", "mode", "topic", "motd",
                    "assistant_on", "assistant_off"]
    target: Optional[TargetSpec] = None
    value: Optional[str] = Field(None, max_length=2000)


@router.get("/org-rooms")
@chat_errors
async def org_rooms(
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """The rooms section: every org you belong to, with its room's live state
    when the room exists. Opening one is an explicit act: a room enters your
    main list only after you open it."""
    actor = cs.actor_from_auth(actor_dict)
    return await cs.list_org_rooms(db, actor)


@router.post("/org-rooms/{org_id}/open", status_code=201)
@chat_errors
async def open_org_room(
    org_id: str,
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    """Open (or dedup-return) THE room for an org (one room per org), gated on
    LIVE membership in organization_members. No message is sent by opening."""
    actor = cs.actor_from_auth(actor_dict)
    conv, created, my_row = await cs.open_org_room(db, actor, org_id)
    my_org_role = await cs.actor_org_role(db, org_id, actor)
    return {"conversation_id": conv.id, "kind": conv.kind, "created": created,
            "my_state": my_row.state, "title": conv.title,
            "room": {"org_id": org_id, "title": conv.title,
                     "mode": conv.mode, "topic": conv.topic, "genesis": conv.genesis,
                     "my_can_post": bool(getattr(my_row, "can_post", True)),
                     "my_org_role": my_org_role,
                     "my_is_operator": my_org_role in cs.ROOM_OPS_ROLES}}


@router.post("/conversations/{conversation_id}/room")
@chat_errors
async def room_op(
    conversation_id: str,
    req: RoomActionBody,
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    """One room operation (kick / mute / unmute / mode / topic / motd).
    Gated on the actor's LIVE org role; every act posts a visible system row.
    ⚠ /kick removes from the ROOM only; org removal is the org rail's own
    explicit action, deliberately not reachable from here."""
    actor = cs.actor_from_auth(actor_dict)
    t_type = t_id = None
    if req.target is not None:
        t_type, t_id = req.target.key_parts()
    result = await cs.room_action(db, conversation_id, actor, req.action,
                                  target_ptype=t_type, target_id=t_id,
                                  value=req.value)
    # Fan out the system row POST-COMMIT (§ESDUP), same contract as a message.
    conv = await cs._get_conversation(db, conversation_id)
    payload = dict(result["system_message"])
    payload["sender_name"] = actor.display_name
    recipients = await cs.recipients_snapshot(db, conv, actor)
    owner_dev = await _sender_owner_dev_id(db, actor)
    cs.deliver(
        conv.id, conv.kind, payload, recipients, actor.display_name,
        sender_owner_dev_id=owner_dev)
    result["system_message"] = payload
    return result


@router.get("/conversations/{conversation_id}/members")
@chat_errors
async def room_members(
    conversation_id: str,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """Room member sheet (org rooms only): who has opened the room, their LIVE
    org role, and their can_post state (the data of the /kick and /mute picker)."""
    actor = cs.actor_from_auth(actor_dict)
    return await cs.room_members(db, conversation_id, actor)


@router.get("/away/digest")
@chat_errors
async def away_digest(
    limit: int = Query(30, ge=1, le=cs.LIST_MAX),
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    "While you were away": the threads your designated stand-in answered. Everything in them is staged: nothing was
    accepted, paid or signed.

    \f
    "While you were away" — the threads your designated stand-in answered.
    Everything in them is STAGED: nothing was accepted, paid or signed (§5c).
    """
    actor = cs.actor_from_auth(actor_dict)
    return await cs.away_digest(db, actor, limit)


# ---------------------------------------------------------------------------
# §OURSTATE-3 REACH — handles, public profiles, and the poll/ack inbox
# ---------------------------------------------------------------------------

class HandleClaim(BaseModel):
    # Deliberately permissive HERE (1..33): the real rule lives in
    # chat_service.validate_handle, which can say the WHOLE rule ("3-32
    # characters, starts alphanumeric, letters/digits/-/_"). A pydantic
    # min_length would 422 first with half the sentence — the §29k class,
    # where the request never reaches the gate that knows why.
    handle: str = Field(..., min_length=1, max_length=33)


@router.get("/handles/me")
@chat_errors
async def my_handle(
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """Your claimed handle, or null. Absence is not an error."""
    actor = cs.actor_from_auth(actor_dict)
    if actor.ptype != "developer":
        return {"handle": None, "note": "handles belong to developer accounts"}
    row = (await db.execute(
        __import__("sqlalchemy").text(
            "SELECT handle, handle_claimed_at FROM developers WHERE id = :me"),
        {"me": actor.developer_id})).first()
    return {"handle": row[0] if row else None,
            "claimed_at": row[1].isoformat() if row and row[1] else None}


@router.post("/handles/claim", status_code=201)
@chat_errors
async def claim_handle(
    req: HandleClaim,
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    """Claim a handle so people can reach you by name instead of by id.
    Opt-in: an account without one is simply unreachable by name."""
    actor = cs.actor_from_auth(actor_dict)
    if actor.ptype != "developer":
        raise cs.ChatError(403, "handles belong to developer accounts")
    return await cs.claim_handle(db, actor.developer_id, req.handle)


class PulseConfig(BaseModel):
    enabled: bool = False
    show_agents: bool = True
    note: str = Field("", max_length=200)


@router.get("/pulse/me")
@chat_errors
async def my_pulse(
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """Your own pulse, including the settings, so the switch and what it
    publishes are read from the same place a stranger would read."""
    from ..services import pulse as pl
    actor = cs.actor_from_auth(actor_dict)
    if actor.ptype != "developer":
        return {"enabled": False, "moments": [], "note": "a pulse belongs to a developer account"}
    return await pl.developer_pulse(db, actor.developer_id, include_config=True)


@router.put("/pulse/me")
@chat_errors
async def set_my_pulse(
    req: PulseConfig,
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    """Turn the pulse on or off. OFF is the default and the only state you get
    without asking for another."""
    from ..services import pulse as pl
    actor = cs.actor_from_auth(actor_dict)
    if actor.ptype != "developer":
        raise cs.ChatError(403, "a pulse belongs to a developer account")
    import json as _json
    from sqlalchemy.dialects.postgresql import insert as _pg_insert
    from ..models import DeveloperPref
    value = {"enabled": bool(req.enabled), "show_agents": bool(req.show_agents),
             "note": (req.note or "")[:200]}
    _json.dumps(value)     # a value that cannot serialize must fail HERE
    stmt = (_pg_insert(DeveloperPref)
            .values(developer_id=actor.developer_id, key=pl.PULSE_PREF_KEY, value=value)
            .on_conflict_do_update(index_elements=["developer_id", "key"],
                                   set_={"value": value}))
    await db.execute(stmt)
    await db.commit()
    return await pl.developer_pulse(db, actor.developer_id, include_config=True)


@router.get("/handles/{handle}/pulse")
@chat_errors
async def handle_pulse(
    handle: str,
    db: AsyncSession = Depends(get_db),
):
    """The public pulse behind a handle. Reads only what the registry already
    attests to; an account with the pulse off says exactly that."""
    from ..services import pulse as pl
    dev_id = await cs.resolve_handle(db, handle)
    if dev_id is None:
        raise cs.ChatError(404, f"no account carries the handle '{cs.normalize_handle(handle)}'")
    return await pl.developer_pulse(db, dev_id)


@router.get("/handles/{handle}")
@chat_errors
async def handle_profile(
    handle: str,
    db: AsyncSession = Depends(get_db),
):
    """The public card behind a handle. PUBLIC by design: this is the page a
    contact QR opens. A private profile still resolves as reachable and says
    so, because "no such person" and "prefers not to be listed" must not look
    the same."""
    return await cs.public_profile(db, handle)


@router.post("/conversations/{conversation_id}/attachments", status_code=201)
@chat_errors
async def upload_attachment(
    conversation_id: str,
    file: UploadFile = File(...),
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    """
    Store a file for this thread and return its pointer. Uploading posts nothing: the caller then sends a `media`
    card referencing the returned id, so a failed upload never leaves a half-message in the thread.

    \f
    §OURSTATE-5e — store a file for THIS thread and return its pointer.

    Uploading does not post anything: the caller then sends a `media` card
    referencing the returned id, so sending a file is the same two-step every
    other typed card follows and a failed upload never leaves a half-message
    in the thread.
    """
    from ..services import chat_media
    actor = cs.actor_from_auth(actor_dict)
    conv = await cs._get_conversation(db, conversation_id)
    mine = await cs._my_row(db, conv.id, actor)
    if mine is None or mine.state not in ("active", "pending"):
        raise cs.ChatError(403, "not a participant in this conversation")
    # D6-554: the THREAD's state, not the uploader's own row: a stranger who knocked holds an 'active' row while the
    # recipient's is 'pending', so the uploader's row let a stranger push a file into a request nobody had accepted.
    thread_state = "pending" if mine.state == "pending" or await cs.thread_is_request(db, conv.id) else mine.state

    data = await file.read()
    att = await chat_media.store(
        db, conversation_id=conv.id, uploader_key=actor.key,
        filename=file.filename or "file",
        declared_mime=file.content_type or "", data=data,
        thread_state=thread_state)
    return {**att, "card": chat_media.media_card(att)}


@router.get("/attachments/{attachment_id}")
@chat_errors
async def download_attachment(
    attachment_id: str,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """Stream a file back to a PARTICIPANT of its thread.

    Never public, never inline. `Content-Disposition: attachment` plus
    `nosniff` mean a stored file cannot execute against this origin, the
    origin that holds the session that moves units. That is not a hardening
    detail; it is the reason uploads are allowed at all.
    """
    from fastapi.responses import FileResponse
    from ..services import chat_media
    actor = cs.actor_from_auth(actor_dict)
    att = await chat_media.fetch(db, attachment_id)
    if att is None:
        raise cs.ChatError(404, "no such attachment")
    if att["deleted_at"]:
        # A tombstone is an answer, not an absence: the card can say "removed"
        # instead of rendering a broken download.
        raise cs.ChatError(410, "this file was removed")

    conv = await cs._get_conversation(db, att["conversation_id"])
    mine = await cs._my_row(db, conv.id, actor)
    if mine is None or mine.state not in ("active", "pending"):
        raise cs.ChatError(403, "not a participant in this conversation")

    import os as _os
    if not _os.path.exists(att["path"]):
        raise cs.ChatError(410, "this file is no longer stored here")
    return FileResponse(
        att["path"], media_type="application/octet-stream",
        filename=att["filename"],
        headers={"X-Content-Type-Options": "nosniff",
                 "Content-Security-Policy": "default-src 'none'; sandbox",
                 "Cache-Control": "private, no-store"})


class OrgChatSettings(BaseModel):
    """An org's own answer to: do we have a room, and who may open it."""
    chat_enabled: Optional[bool] = None
    chat_open_policy: Optional[Literal["owner_admin", "members"]] = None


@router.put("/org-rooms/{org_id}/settings")
@chat_errors
async def set_org_chat_settings(
    org_id: str,
    req: OrgChatSettings,
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    """
    Turn an organization's chat on or off, and set who may open its room. Changing the policy is always an owner or
    admin act, even in an organization that lets members open the room. Enabling follows the policy the organization
    already set.

    \f
    §OURSTATE-6 — turn an org's chat on or off, and set who may open it.

    Changing the POLICY is always an owner/admin act, even in an org that lets
    members open the room: deciding who may act is a different power from
    acting. Enabling follows the policy the org already set.
    """
    from sqlalchemy import text as _text
    actor = cs.actor_from_auth(actor_dict)
    role = await cs.actor_org_role(db, org_id, actor)
    if role is None:
        raise cs.ChatError(403, "you are not an active member of this organization")
    row = (await db.execute(_text(
        "SELECT chat_enabled, chat_open_policy FROM organizations "
        "WHERE id = :o AND is_active = true"), {"o": org_id})).first()
    if row is None:
        raise cs.ChatError(404, "organization not found")

    is_op = role in cs.ROOM_OPS_ROLES
    policy = str(row[1] or "owner_admin")

    if req.chat_open_policy is not None and not is_op:
        raise cs.ChatError(403, "only an owner or admin can change who may open the room")
    if req.chat_enabled is not None and not (is_op or policy == "members"):
        raise cs.ChatError(403, "this organization lets only owners and admins "
                                "turn the room on")

    sets, params = [], {"o": org_id}
    if req.chat_enabled is not None:
        sets.append("chat_enabled = :e"); params["e"] = bool(req.chat_enabled)
    if req.chat_open_policy is not None:
        sets.append("chat_open_policy = :p"); params["p"] = req.chat_open_policy
    if sets:
        await db.execute(_text(
            f"UPDATE organizations SET {', '.join(sets)} WHERE id = :o"), params)
        await db.commit()

    after = (await db.execute(_text(
        "SELECT chat_enabled, chat_open_policy FROM organizations WHERE id = :o"),
        {"o": org_id})).first()
    return {"org_id": org_id, "chat_enabled": bool(after[0]),
            "chat_open_policy": after[1], "my_org_role": role,
            "note": ("disabling hides the room; it does not delete it, and it changes "
                     "nobody's membership or roles")}


class RetentionSet(BaseModel):
    """The disappearing timer. `hours: null` clears it (keep by default, D9)."""
    hours: Optional[int] = None


@router.put("/conversations/{conversation_id}/retention")
@chat_errors
async def set_retention(
    conversation_id: str,
    req: RetentionSet,
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    """
    Set how long this thread keeps its messages. Either participant may set it and both are told. The answer states
    what it does and does not reach.

    \f
    §OURSTATE-6 — set how long this thread keeps its messages.

    Either participant may set it and BOTH are told, because a timer one side
    could set privately would be a promise about the other side's copy that
    nobody can keep. The answer states plainly what it does and does not reach.
    """
    actor = cs.actor_from_auth(actor_dict)
    out = await cs.set_retention(db, conversation_id, actor, req.hours)
    await db.commit()
    return out


@router.get("/retention/status")
@chat_errors
async def retention_status(
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """What the sweeper last did. A timer nobody enforces is a claim, so the
    enforcement is readable."""
    from ..background_tasks.chat_retention_sweeper import retention_stats
    cs.actor_from_auth(actor_dict)
    return await retention_stats()


# ---------------------------------------------------------------------------
# §OURSTATE-7 D — support threads
# ---------------------------------------------------------------------------

class SupportReply(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


class SupportOpen(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=4000)
    category: str = Field(default="general", pattern="^(bug|question|feature|account|general)$")


#: V0652 (ai): the support routes take the shared actor resolver (so an agent hears the sentence that refuses it,
#: not a bare 401) and therefore declared "agent or developer" in the OpenAPI; the reference read that as a promise.
#: x-callers names who may actually call them (scripts/gen_reference_docs.py reads it).
SUPPORT_CALLERS = {"x-callers": ["developer"]}


@router.get("/conversations/{conversation_id}/support", openapi_extra=SUPPORT_CALLERS)
@chat_errors
async def support_state(
    conversation_id: str,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """The TICKET behind a support thread: status, category, and whether it is
    still open to replies. The thread displays; the ticket decides, so the
    thread has to be able to ask."""
    from ..services import chat_support
    from .. import models as m
    actor = cs.actor_from_auth(actor_dict)
    if actor.ptype != "developer":
        raise cs.ChatError(403, "a support thread belongs to a person, not an agent")
    tid = await chat_support.ticket_for_conversation(db, conversation_id)
    if tid is None:
        raise cs.ChatError(404, "this conversation is not a support thread")
    row = (await db.execute(select(m.SupportTicket).where(
        m.SupportTicket.id == tid))).scalars().first()
    if row is None or int(row.developer_id) != int(actor.developer_id):
        # A thread whose ticket vanished, or somebody else's. Both are 404 to
        # the caller: "not yours" and "not there" leak the same thing here.
        raise cs.ChatError(404, "this conversation is not a support thread")
    return {"ticket_id": row.id, "subject": row.subject, "status": row.status,
            "category": row.category, "priority": row.priority,
            "note": "support decides this ticket; the thread shows it"}


@router.post("/conversations/{conversation_id}/support-reply", status_code=201, openapi_extra=SUPPORT_CALLERS)
@chat_errors
async def support_reply(
    conversation_id: str,
    req: SupportReply,
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    """Reply to a support ticket FROM its thread.

    This writes the TICKET and lets the mirror follow, the same rule
    `/service-call` follows for payments: chat owns no support logic, it calls the
    rail that already has it (`support.add_developer_reply`). That is why a
    direct `POST /messages` into a support thread is refused: two writers would
    let the thread say something the ticket never heard.
    """
    from ..services import chat_support
    from .support import add_developer_reply
    from .. import models as m
    actor = cs.actor_from_auth(actor_dict)
    if actor.ptype != "developer":
        raise cs.ChatError(403, "a support thread belongs to a person, not an agent")
    tid = await chat_support.ticket_for_conversation(db, conversation_id)
    if tid is None:
        raise cs.ChatError(404, "this conversation is not a support thread")
    ticket = (await db.execute(select(m.SupportTicket).where(
        m.SupportTicket.id == tid))).scalars().first()
    if ticket is None or int(ticket.developer_id) != int(actor.developer_id):
        raise cs.ChatError(404, "this conversation is not a support thread")
    dev = actor_dict["developer"]
    await add_developer_reply(db, ticket, dev, req.text)
    return {"conversation_id": conversation_id, "ticket_id": ticket.id,
            "status": ticket.status}


@router.post("/support/open", status_code=201, openapi_extra=SUPPORT_CALLERS)
@chat_errors
async def support_open(
    req: SupportOpen,
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    """File a ticket and land in its thread (the Pocket door).

    Creating the ticket is the support rail's job, so this calls it rather than
    writing `support_tickets` itself; all this endpoint adds is the answer a
    chat client needs, which is *which conversation do I open now*.
    """
    from ..services import chat_support
    from .support import create_ticket, TicketCreate
    actor = cs.actor_from_auth(actor_dict)
    if actor.ptype != "developer":
        raise cs.ChatError(403, "a support ticket belongs to a person, not an agent")
    dev = actor_dict["developer"]
    ticket = await create_ticket(
        TicketCreate(subject=req.subject, category=req.category,
                     message=req.message, priority="normal"),
        current_dev=dev, db=db)
    conv = (await db.execute(select(Conversation).where(
        Conversation.dm_pair_key == chat_support.support_pair_key(int(ticket.id))
    ))).scalars().first()
    if conv is None:
        # The ticket EXISTS — say so rather than reporting a failure that did
        # not happen. The thread catches up on the next message.
        return {"ticket_id": ticket.id, "conversation_id": None,
                "note": "the ticket was filed; its thread will appear shortly"}
    return {"ticket_id": ticket.id, "conversation_id": conv.id}


# ---------------------------------------------------------------------------
# §CHATDESK C4 — SUPPORT REVIEW WITH CONSENT (the participant half).
# The desk may read a conversation ONLY while a live, ticket-bound grant
# exists. The FILER grants (org rooms: owner/admin — the room belongs to the
# organization), every participant SEES it as a system row + banner, the
# granter can withdraw it, and it dies with the ticket. Read-only by
# construction: the desk never gains a write path because it never becomes a
# participant. Marker: CHATDESK.
# ---------------------------------------------------------------------------

class ReviewGrantBody(BaseModel):
    ticket_id: int
    expires_hours: Optional[int] = Field(None, ge=1, le=720)


@router.get("/conversations/{conversation_id}/support-review")
@chat_errors
async def support_review_state(
    conversation_id: str,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """The banner's data: every grant on this conversation, live flag included.
    Participants only: the grant list is part of the conversation (and the owner who reads his agent's system thread
    reads its grants too, V0652 (s): the page asks this on every open)."""
    from ..services import chat_support
    actor = cs.actor_from_auth(actor_dict)
    conv = await cs._get_conversation(db, conversation_id)
    await cs.resolve_reader(db, conv, actor)
    grants = await chat_support.review_grants_for_conversation(db, conv.id)
    # the server answers "is this yours" — the client never compares ids locally
    # (the §ORGJOIN masked-hint lesson, applied to grants).
    for g in grants:
        g["granted_by_me"] = (actor.ptype == "developer"
                              and int(g["granted_by_dev"]) == int(actor.developer_id or 0))
    return {"conversation_id": conv.id, "grants": grants}


@router.post("/conversations/{conversation_id}/support-review", status_code=201, openapi_extra=SUPPORT_CALLERS)
@chat_errors
async def support_review_grant(
    conversation_id: str,
    req: ReviewGrantBody,
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    from ..services import chat_support
    from .. import models as m
    actor = cs.actor_from_auth(actor_dict)
    if actor.ptype != "developer":
        raise cs.ChatError(403, "a person grants review access, not an agent")
    conv = await cs._get_conversation(db, conversation_id)
    if conv.kind == "support":
        raise cs.ChatError(409, "the desk already sees its own thread")
    await cs.resolve_membership(db, conv, actor)
    if conv.kind == "org":
        role = await cs.actor_org_role(db, conv.org_id or "", actor)
        if role not in cs.ROOM_OPS_ROLES:
            raise cs.ChatError(403, "an org room is the organization's to share — owner or admin grants")
    ticket = (await db.execute(select(m.SupportTicket).where(
        m.SupportTicket.id == int(req.ticket_id)))).scalars().first()
    if ticket is None or int(ticket.developer_id) != int(actor.developer_id):
        # "not yours" and "not there" deliberately leak the same thing here
        # (the support_state stance).
        raise cs.ChatError(404, "no such ticket of yours")
    if str(ticket.status) not in chat_support.REVIEW_LIVE_STATUSES:
        raise cs.ChatError(409, "that ticket is closed — review access ends with the ticket; file a new one")
    grant, created = await chat_support.create_review_grant(
        db, ticket, conv, int(actor.developer_id), req.expires_hours)
    if created:
        until = " (time-boxed)" if grant.expires_at is not None else ""
        await chat_support.announce_review_event(
            db, conv, actor,
            f"{actor.display_name} allowed the support desk to review this conversation "
            f"for ticket #{ticket.id} — read-only, until the ticket is resolved or closed{until}. Revocable here.")
    else:
        await db.commit()
    return {"grant_id": grant.id, "ticket_id": ticket.id, "created": created,
            "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
            "note": "read-only; visible to every participant; dies with the ticket"}


@router.delete("/conversations/{conversation_id}/support-review/{grant_id}", openapi_extra=SUPPORT_CALLERS)
@chat_errors
async def support_review_revoke(
    conversation_id: str,
    grant_id: str,
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    from ..services import chat_support
    actor = cs.actor_from_auth(actor_dict)
    if actor.ptype != "developer":
        raise cs.ChatError(403, "a person grants review access, not an agent")
    conv = await cs._get_conversation(db, conversation_id)
    await cs.resolve_membership(db, conv, actor)
    g = await chat_support.get_review_grant(db, grant_id, conversation_id=conv.id)
    if g is None:
        raise cs.ChatError(404, "no such review grant on this conversation")
    if int(g.granted_by_dev) != int(actor.developer_id):
        raise cs.ChatError(403, "only the person who granted review access may withdraw it")
    if g.revoked_at is not None:
        return {"grant_id": g.id, "revoked": True, "already": True}
    await chat_support.revoke_review_grant(db, g, "granter")
    await chat_support.announce_review_event(
        db, conv, actor,
        f"{actor.display_name} withdrew the support desk's review access (ticket #{g.ticket_id}).")
    return {"grant_id": g.id, "revoked": True, "already": False}


@router.get("/fiat-door")
@chat_errors
async def fiat_door(
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Whether the top-up (fiat on-ramp) door may be shown here and, if not, which lock is shut: the on-ramp switch
    (`FIAT_ONRAMP_ENABLED`, off on the public network), the genesis registry, or the operator's fiat authorization.
    A closed door also points to the ways to be paid for work. The client asks before offering the control.

    \f
    §OURSTATE-5c — may the top-up door be shown here, and if not, why not.

    The client asks BEFORE offering the control, so a user never taps a button
    that cannot work. When it is shut the answer names the lock and points at
    the earn surfaces, because "you cannot buy tokens here" is only half an
    answer on a network where you can work for them.
    """
    from ..services.fiat_door import door_state
    cs.actor_from_auth(actor_dict)   # authentication only: no per-actor variation
    return await door_state(db)


@router.get("/away/authority")
@chat_errors
async def my_away_authority(
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """What YOUR stand-in may commit: the same derivation a counterparty sees.

    Deliberately the same function, not a friendlier owner-side variant: if the
    two could differ, the owner would be reading a number the stranger never
    sees. When it is not authorized the reason is named, because the owner is
    the only person who can act on it.
    """
    from ..services.chat_authority import authority_snapshot, authority_sentence
    actor = cs.actor_from_auth(actor_dict)
    if actor.ptype != "developer":
        raise cs.ChatError(403, "an away designation belongs to a developer account")
    cfg = await cs.away_config(db, actor.developer_id) or {}
    did = str(cfg.get("agent_did") or "")
    if not did:
        return {"authorized": False, "reason": "no agent is designated", "agent_did": None}
    snap = await authority_snapshot(
        db, developer_id=actor.developer_id, agent_did=did,
        token_id=cfg.get("capability_token_id"))
    names = await cs.display_names(db, [cs.principal_key("agent", did)])
    snap["sentence"] = authority_sentence(
        snap, names.get(cs.principal_key("agent", did), did), actor.display_name)
    return snap


@router.get("/conversations/{conversation_id}/authority")
@chat_errors
async def conversation_authority(
    conversation_id: str,
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """
    What the stand-in in this thread may actually commit; participants only. Every field is derived from IRONKEY at
    request time, so a revoked grant reads empty on the very next call.

    \f
    §OURSTATE-5b — what the stand-in in THIS thread may actually commit.

    Scoped to participants on purpose: a ceiling is a fact about a negotiation
    you are inside, not a public inventory of what someone can spend. Every
    field is re-derived from IRONKEY at request time, so a revoked grant reads
    empty on the very next call — there is no cached copy to go stale.
    """
    from ..services.chat_authority import authority_snapshot, authority_sentence
    actor = cs.actor_from_auth(actor_dict)
    conv = await cs._get_conversation(db, conversation_id)
    mine = await cs._my_row(db, conv.id, actor)
    if mine is None or mine.state not in ("active", "pending"):
        raise cs.ChatError(403, "not a participant in this conversation")

    from sqlalchemy import select as _select
    from ..models import ConversationParticipant as _CP
    rows = (await db.execute(_select(_CP).where(
        _CP.conversation_id == conv.id, _CP.ptype == "agent"))).scalars().all()

    dids = [r.agent_did for r in rows if r.agent_did]
    owners = await cs.agent_owner_map(db, dids) if dids else {}
    names = await cs.display_names(db, [cs.principal_key("agent", d) for d in dids]) if dids else {}

    out = []
    for r in rows:
        did = r.agent_did
        dev_id = owners.get(did)
        if not did or dev_id is None:
            continue
        cfg = await cs.away_config(db, int(dev_id)) or {}
        # Only a DESIGNATED stand-in has an authority line at all. An ordinary
        # agent in a thread is not claiming to act for anyone, and inventing a
        # line for it would be the overstatement this feature exists to avoid.
        if str(cfg.get("agent_did") or "") != did:
            continue
        snap = await authority_snapshot(
            db, developer_id=int(dev_id), agent_did=did,
            token_id=cfg.get("capability_token_id"))
        snap["sentence"] = authority_sentence(
            snap, names.get(cs.principal_key("agent", did), did), "their owner")
        out.append(snap)

    return {"conversation_id": conv.id, "stand_ins": out,
            "note": ("re-derived from the capability grant and the liability mandate "
                     "at read time; revoking either empties this immediately")}


class ContactPolicyUpdate(BaseModel):
    """Your terms for a stranger's first thread. Every field optional: this is
    a patch, so setting a price does not silently clear your Genesis."""
    policy: Optional[Literal["open", "contacts", "priced"]] = None
    price: Optional[str] = Field(None, max_length=32)
    currency: Optional[str] = Field(None, max_length=12)
    purse_did: Optional[str] = Field(None, max_length=255)
    stated: Optional[str] = Field(None, max_length=2000)


@router.get("/contact-policy/me")
@chat_errors
async def get_my_contact_policy(
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """What you declare AND what the registry will enforce, returned
    separately, so a price nobody can pay is visible to the one person who can
    fix it."""
    from ..services import contact_policy as cp
    actor = cs.actor_from_auth(actor_dict)
    if actor.ptype != "developer":
        raise cs.ChatError(403, "contact terms belong to a developer account")
    decl = await cp.declaration(db, actor.developer_id)
    return {**decl, "card": cp.genesis_card(decl, actor.display_name)}


@router.put("/contact-policy/me")
@chat_errors
async def set_my_contact_policy(
    req: ContactPolicyUpdate,
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    """Set your terms. Refuses BY NAME (unknown policy, negative price, an
    agent that is not yours) rather than coercing a value you did not mean."""
    from ..services import contact_policy as cp
    actor = cs.actor_from_auth(actor_dict)
    if actor.ptype != "developer":
        raise cs.ChatError(403, "contact terms belong to a developer account")
    decl = await cp.set_declaration(
        db, actor.developer_id, policy=req.policy, price=req.price,
        currency=req.currency, purse_did=req.purse_did, stated=req.stated)
    return {**decl, "card": cp.genesis_card(decl, actor.display_name)}


class InboxAck(BaseModel):
    conversation_id: str = Field(..., max_length=64)
    seq: int = Field(..., ge=0)


@router.post("/inbox/ack")
@chat_errors
async def inbox_ack(
    req: InboxAck,
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    """Acknowledge everything up to `seq` in one thread: the poll/ack half of
    the SDK Messenger loop. It IS `mark_read` (read floors are monotonic and
    already per-participant); giving it a second name here means a runtime can
    speak the loop's vocabulary without learning the UI's."""
    actor = cs.actor_from_auth(actor_dict)
    return await cs.mark_read(db, req.conversation_id, actor, req.seq)


async def _create_federated(db: AsyncSession, actor: "cs.Actor", req: ConversationCreate) -> dict:
    """§OURSTATE-3b — open a thread with someone on a PEER registry.

    THIS registry becomes the HOST: it owns the seq, and it delivers to the
    other side's home registry. The remote participant is recorded as an
    ADDRESS (`handle@https://their.registry`), never as a local principal —
    we cannot authenticate them and must not imply that we can.
    """
    from ..services import chat_federation as fed
    if not fed.federation_enabled():
        raise cs.ChatError(501, "cross-registry chat is not enabled on this registry")
    if actor.ptype not in ("developer", "agent"):
        raise cs.ChatError(403, "cross-registry threads are opened by a developer or an agent")
    if req.kind != "dm":
        raise cs.ChatError(422, "only dm threads federate in this version")

    parsed = fed.parse_remote_key(req.target.remote_key or "")
    if not parsed:
        raise cs.ChatError(422, "remote_key must be handle@https://their.registry")
    _, base = parsed
    if base == fed.origin(fed.self_base_url()):
        raise cs.ChatError(422, "that address is on THIS registry — use handle instead")
    await fed.assert_peer_allowed(db, base)

    key = fed.remote_key(parsed[0], base)
    to_agent = parsed[0].lower().startswith("did:")
    if (await cs.blocks_between(db, actor.key, cs.principal_key("remote", key)))["a_blocks_b"]:
        # §TWOAGENT G1 step 3: the same refusal a local block gives
        raise cs.ChatError(403, "you have blocked this principal — unblock to start a conversation")
    pair = cs.pair_key("dm", actor.key, f"rem:{key}")
    existing = (await db.execute(
        __import__("sqlalchemy").select(cs.Conversation).where(
            cs.Conversation.dm_pair_key == pair))).scalars().first()
    if existing is None:
        mirror = await fed.mirror_thread_with(db, actor, key)
        if mirror is not None:
            return await _reengage_mirror(db, mirror[0], mirror[1], actor, key, req)
        if not await fed.fed_rate_ok("create_actor", actor.key):
            raise cs.ChatError(429, "too many new cross-registry threads from you this hour")
        conv = cs.Conversation(kind="dm", created_by_ptype=actor.ptype,
                               created_by_id=actor.sender_id, dm_pair_key=pair)
        db.add(conv)
        await db.flush()
        my_row = cs.ConversationParticipant(
            conversation_id=conv.id, ptype=actor.ptype,
            developer_id=actor.developer_id if actor.ptype == "developer" else None,
            agent_did=actor.agent_did if actor.ptype == "agent" else None,
            role="owner", state="active")
        # §TWOAGENT G1 step 2: an AGENT on the other side has not agreed to talk yet. Its home seats it pending (its
        # Requests lane), and this row says the same until its home announces the accept (POST .../state).
        their_row = cs.ConversationParticipant(
            conversation_id=conv.id, ptype="remote", remote_key=key,
            role="member", state="pending" if to_agent else "active")
        db.add_all([my_row, their_row])
        await db.commit()
        created = True
    else:
        conv, created = existing, False
        my_row = await cs.resolve_membership(db, conv, actor, auto_join=False)
        if my_row.state in ("left", "pending"):
            # §TWOAGENT G1 step 3: opening the pair thread IS engaging with it, as create_conversation does locally.
            # Without this, a resident who left (or blocked, then unblocked) got the same thread back and a 409 on
            # every message, for good: the pair key dedups to it.
            my_row.state = "active"
            await db.commit()

    first = None
    if req.first_message is not None:
        first = await _send_and_fan_out(
            db, conv, my_row, actor, req.first_message.kind, req.first_message.body,
            req.first_message.card, req.first_message.client_ref)
    return {"conversation_id": conv.id, "kind": conv.kind, "created": created,
            "my_state": my_row.state, "first_message": first,
            "federated": True, "host": fed.self_base_url(), "remote": key}


async def _reengage_mirror(db: AsyncSession, conv, my_row, actor: "cs.Actor", key: str,
                           req: ConversationCreate) -> dict:
    """§TWOAGENT G1 step 4: open the thread the OTHER registry hosts with this address, as a local create opens the
    pair's thread. A pending row is the accept and a left row a rejoin; either reaches the host BEFORE any message (the
    host refuses a message from a participant it holds as left), and if the host cannot hear it nothing changes here."""
    from ..services import chat_federation as fed
    before = my_row.state
    if before in ("left", "pending"):
        my_row.state = "active"
        await db.commit()
        pkey = fed.remote_key(await cs._participant_handle(db, my_row), fed.self_base_url())
        if not await fed.announce_state_to_host(conv.host_registry, conv.remote_ref, pkey, "active"):
            my_row.state = before
            await db.commit()
            raise cs.ChatError(502, "the thread's host registry could not be reached; nothing changed, try again")
    first = None
    if req.first_message is not None:
        first = await _send_and_fan_out(
            db, conv, my_row, actor, req.first_message.kind, req.first_message.body,
            req.first_message.card, req.first_message.client_ref)
    return {"conversation_id": conv.id, "kind": conv.kind, "created": False,
            "my_state": my_row.state, "first_message": first,
            "federated": True, "host": conv.host_registry, "remote": key}


@router.get("/federation/status")
@chat_errors
async def federation_status(
    actor_dict: dict = Depends(get_current_actor_for_read_or_key),
    db: AsyncSession = Depends(get_db),
):
    """Is cross-registry chat on here, which peers can it reach, and what has
    the delivery worker actually DONE? `cycles: 0` means it has never run,
    which must never look like 'nothing to deliver'."""
    from ..services import chat_federation as fed
    from ..background_tasks.chat_federation_outbox import outbox_stats
    cs.actor_from_auth(actor_dict)      # any authenticated principal may look
    enabled = fed.federation_enabled()
    peers = await fed.peer_base_urls(db) if enabled else {}
    pending = (await db.execute(__import__("sqlalchemy").text(
        "SELECT count(*) FROM chat_federation_outbox WHERE delivered_at IS NULL"))).scalar_one()
    stuck = (await db.execute(__import__("sqlalchemy").text(
        "SELECT count(*) FROM chat_federation_outbox "
        "WHERE delivered_at IS NULL AND attempts >= :m"), {"m": fed.MAX_ATTEMPTS})).scalar_one()
    return {"enabled": enabled, "host_base_url": fed.self_base_url(),
            "peers": sorted(peers.keys()), "pending": int(pending),
            "given_up": int(stuck), "worker": await outbox_stats(),
            "note": "dm only; rooms and money rails do not federate in this version"}


# ---------------------------------------------------------------------------
# V0650 (l) — approvals in the chat (services/chat_approvals.py holds the rules)
# ---------------------------------------------------------------------------

class ApprovalRequestBody(BaseModel):
    client_ref: str = Field(..., min_length=8, max_length=64,
                            description="Your idempotency key: a repeat returns the original request")
    title: str = Field(..., min_length=1, max_length=200, description="What is asked, in one line")
    reason: Optional[str] = Field(None, max_length=2000, description="Why")
    unlocks: Optional[str] = Field(None, max_length=500, description="The action an approval unlocks")
    expires_in_seconds: int = Field(3600, ge=60, le=604800,
                                    description="How long the request stays decidable (60 s to 7 days)")
    artifact_sha256: Optional[str] = Field(None, max_length=71,
                                           description="sha256 of the artifact the approval is about (64 hex)")
    artifact_label: Optional[str] = Field(None, max_length=200, description="A human name for that artifact")
    production_impact: bool = Field(False, description="Declared by you: the action touches production")
    # V0652 (ab): a decision that is not yes or no: up to five options, one of which the owner or an approver chooses
    options: Optional[list[str]] = Field(None, min_length=2, max_length=5,
                                         description="A choice: 2 to 5 short labels (up to 80 characters each); the "
                                                     "decider taps one, or declines them all. Omit for an approval")


class ApprovalDecideBody(BaseModel):
    # V0652 (ab): "choose" decides a choice request by one of its options (`option`, its index); "deny" declines either
    decision: Literal["approve", "deny", "choose"]
    option: Optional[int] = Field(None, ge=0, le=4, description="With choose: the index of the option chosen (0 for the "
                                                                 "first)")
    approval_ids: list[str] = Field(..., min_length=1, max_length=50,
                                    description="The requests to decide: one, several, or every one shown")
    challenge_id: Optional[str] = Field(None, max_length=44,
                                        description="An approved presence challenge, when the room asks for one")
    note: Optional[str] = Field(None, max_length=500)
    surface: Optional[str] = Field(None, max_length=40, description="Where the decision was made (client-stated)")


class ApprovalConsumeBody(BaseModel):
    """V0651 (o): the act an approval opens, named by the sha256 the approval was asked with."""
    act_label: str = Field(..., min_length=1, max_length=200,
                           description="What the act is, as the room should read it (e.g. 'V0651 production roll')")
    act_sha256: str = Field(..., min_length=64, max_length=71,
                            description="The act's sha256 (64 hex, `sha256:` accepted): it must equal the approval's "
                                        "artifact_sha256")
    production: bool = Field(True, description="The act is a production act: the approval must have been asked with "
                                               "production_impact")


def approval_errors(fn):
    """chat_errors, plus the approval rail's refusals; a 428 step-up answer is a JSON body, never a stringified
    detail (the RFC 7807 layer would flatten a dict)."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        from fastapi.responses import JSONResponse
        from ..services import chat_approvals as ca
        try:
            return await fn(*args, **kwargs)
        except cs.ChatError as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)
        except ca.ApprovalError as e:
            if e.body is not None:
                return JSONResponse(status_code=e.status_code, content=e.body)
            raise HTTPException(status_code=e.status_code, detail=e.detail)
    return wrapper


def _approvals_switched_on() -> None:
    from ..services import chat_approvals as ca
    if not ca.enabled():
        raise cs.ChatError(501, "approvals in the chat are switched off on this registry (CHAT_APPROVALS_ENABLED)")


async def _approval_room(db: AsyncSession, conversation_id: str):
    """The room an approval lives in: an organization's room this registry hosts, with chat on."""
    from ..services import chat_approvals as ca
    conv = await cs._get_conversation(db, conversation_id)
    if conv.kind != "org" or not conv.org_id:
        raise cs.ChatError(409, "approvals are asked and decided in an organization's room; this conversation is not one")
    if getattr(conv, "host_registry", None):
        raise cs.ChatError(409, "this room is a mirror of another registry's; approvals live in a room this registry hosts")
    org = await ca.org_facts(db, conv.org_id)
    if org is None:
        raise cs.ChatError(404, "this room's organization no longer exists")
    return conv, org


async def _approval_reader(request: Request, db: AsyncSession = Depends(get_db),
                           token: str = Depends(oauth2_scheme_required)) -> dict:
    """The chat routes' dual-principal read (an agent JWT or a developer JWT), plus a developer API key (`avreg_`):
    the MCP bridges and the CLI present one, and get_current_actor_for_read decodes JWTs only, so a session reading an
    approval's status through MCP would be refused 401. Only the approval reads take this; the other chat routes are
    unchanged."""
    if token.startswith("avreg_"):
        from ..security import verify_access_token_required
        developer_id = await verify_access_token_required(request=request, token=token, db=db)
        developer = await get_current_developer(db=db, developer_id=developer_id)
        return {"kind": "developer", "developer": developer}
    return await get_current_actor_for_read(db=db, token=token)


def _mcp_relay_attested(request: Request) -> bool:
    """Did this registry's own MCP server relay the call (its HMAC proof over the presented API key)?"""
    import hmac as _hmac
    from ..security import MCP_RELAY_HEADER, mcp_relay_proof
    proof = request.headers.get(MCP_RELAY_HEADER) or ""
    auth = request.headers.get("authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not proof or not token:
        return False
    return _hmac.compare_digest(proof, mcp_relay_proof(token))


@router.post("/conversations/{conversation_id}/approvals", status_code=201,
             summary="Ask the organization's owner for an approval (agents only)")
@approval_errors
async def request_approval(
    conversation_id: str,
    req: ApprovalRequestBody,
    current_agent: Agent = Security(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Post an approval request into your organization's room. The registry writes the request's record and an
    `approval.request` card in one transaction; the org's owner or a named approver decides it (POST
    `.../approvals/decide`), and the decision arrives as an `approval.decided` card in the thread, on `/chat/sync`
    and in `GET /chat/approvals/{id}`. A repeat `client_ref` returns the original request. Agents only: the caller is
    the asking agent.
    """
    import datetime as _dt
    import hashlib as _hl
    from ..models import ChatApproval
    from ..services import chat_approvals as ca
    from ..services.admin_audit import log_chat_action

    _approvals_switched_on()
    conv, org = await _approval_room(db, conversation_id)
    if not org["chat_enabled"]:
        raise cs.ChatError(409, "this organization's chat is switched off")
    did = current_agent.did
    actor = await _named_sender(db, cs.Actor("agent", agent_did=did,
                                             display_name=getattr(current_agent, "name", None) or did))
    my_row = await cs.resolve_membership(db, conv, actor, announce_ok=True)
    if my_row.state != "active":
        raise cs.ChatError(409, "you are not active in this conversation")
    # The card is rail-authored, so insert_message skips the room's speech gates: ask them here, because a muted
    # agent or an announce-only room must not be a way to post anyway.
    await cs.room_posting_gate(db, conv, my_row, actor)

    title = " ".join(req.title.split())
    if not title:
        raise cs.ChatError(422, "title must say what is asked")
    options, why = ca.normalize_options(req.options)   # V0652 (ab): None for an approval
    if why:
        raise cs.ChatError(422, why)
    sha = ca.normalize_sha256(req.artifact_sha256)
    existing = await ca.by_client_ref(db, did, req.client_ref)
    if existing is not None:
        if existing.conversation_id != conv.id:
            raise cs.ChatError(409, "this client_ref already names an approval request in another conversation")
        return {"approval": ca.serialize(existing, await ca.db_now(db), requester_name=actor.display_name),
                "duplicate": True}
    if org["owner_id"] is None:
        raise cs.ChatError(409, "nobody can decide here: the organization has no owner")
    if await ca.pending_count(db, conv.id, did) >= ca.max_pending():
        raise cs.ChatError(429, f"you already have {ca.max_pending()} undecided approval requests in this room; "
                                "wait for a decision or let one expire")

    now = await ca.db_now(db)
    aid = ca.new_id()
    expires_at = now + _dt.timedelta(seconds=int(req.expires_in_seconds))
    reason = (req.reason or "").strip() or None
    unlocks = (req.unlocks or "").strip() or None
    label = (req.artifact_label or "").strip() or None
    facts = ca.request_facts(
        approval_id=aid, conversation_id=conv.id, org_id=conv.org_id, requester_agent_did=did, title=title,
        reason=reason, unlocks=unlocks, artifact_sha256=sha, artifact_label=label,
        production_impact=req.production_impact, created_at=now, expires_at=expires_at, client_ref=req.client_ref,
        options=options)
    row = ChatApproval(
        id=aid, conversation_id=conv.id, org_id=conv.org_id, requester_agent_did=did, client_ref=req.client_ref,
        title=title, reason=reason, unlocks=unlocks, artifact_sha256=sha, artifact_label=label,
        production_impact=bool(req.production_impact), facts=facts, facts_digest=ca.digest(facts),
        status="pending", created_at=now, expires_at=expires_at, options=options)
    card = ca.request_card(row)

    async def _with_record(m):
        row.request_message_id = m.id
        db.add(row)
        await db.flush()
        await log_chat_action(db, action="choice.requested" if options else "approval.requested", actor_type="agent",
                              actor_id=did, target_type="chat_approval", target_id=aid,
                              details={"conversation_id": conv.id, "org_id": conv.org_id, "title": title[:120],
                                       "artifact_sha256": sha, "production_impact": bool(req.production_impact),
                                       "expires_at": ca.iso(expires_at), "options": options})

    msg_ref = "aprq-" + _hl.sha1(f"{did}|{req.client_ref}".encode()).hexdigest()[:40]
    msg = await _send_and_fan_out(db, conv, my_row, actor, "card", None, card, msg_ref,
                                  rail_author=True, extra_before_commit=_with_record)
    saved = await ca.by_client_ref(db, did, req.client_ref)
    if saved is None:
        raise cs.ChatError(500, "the approval request was not recorded; nothing was asked, try again")
    return {"approval": ca.serialize(saved, now, requester_name=actor.display_name), "message": msg,
            "duplicate": saved.id != aid}


@router.get("/conversations/{conversation_id}/approvals", summary="The approval requests of a room")
@approval_errors
async def list_approvals(
    conversation_id: str,
    status_filter: Literal["pending", "decided", "all"] = Query("pending", alias="status"),
    limit: int = Query(50, ge=1, le=200),
    actor_dict: dict = Depends(_approval_reader),
    db: AsyncSession = Depends(get_db),
):
    """Any active member of the room may read its approval requests. `can_decide` says whether the caller may decide
    them (the org's owner or a named approver), and `presence` which decisions ask for a phone confirmation."""
    from ..services import chat_approvals as ca
    _approvals_switched_on()
    actor = cs.actor_from_auth(actor_dict)
    conv, org = await _approval_room(db, conversation_id)
    await cs.resolve_membership(db, conv, actor)
    rows = await ca.list_for_conversation(db, conv.id, status_filter, limit)
    now = await ca.db_now(db)
    agents, devs = await ca.names_for(db, rows)
    role = None
    if actor.ptype == "developer":
        role = await ca.decider_role(db, conv.org_id, actor.developer_id, org["owner_id"])
    return {
        "conversation_id": conv.id,
        "status": status_filter,
        "items": [ca.serialize(r, now, requester_name=agents.get(r.requester_agent_did),
                               decider_name=devs.get(r.decided_by_developer_id)) for r in rows],
        "can_decide": role is not None,
        "my_role": role,
        "presence": ca.presence_policy(ca.registry_presence(), org["settings"]),
        "server_time": ca.iso(now),
    }


@router.get("/approvals", summary="The approval requests waiting for my decision, in every room")
@approval_errors
async def approvals_waiting_for_me(
    limit: int = Query(50, ge=1, le=200),
    actor_dict: dict = Depends(_approval_reader),
    db: AsyncSession = Depends(get_db),
):
    """V0651 (y): every pending, unexpired request the caller may decide, across the organization rooms this registry
    hosts, for a surface that lists them outside a room (Pocket's Approvals). The rooms' own authority, read live: the
    caller is the org's owner or an active member the owner named an approver (decider_role's rule), and still an
    active member of the org (the room's read rule, resolve_membership's). Agents never decide and are refused."""
    from ..services import chat_approvals as ca
    _approvals_switched_on()
    actor = cs.actor_from_auth(actor_dict)
    if actor.ptype != "developer":
        raise cs.ChatError(403, "agents never decide approvals: this list is for the organization's owner and its "
                                "named approvers")
    now = await ca.db_now(db)
    found = await ca.waiting_for(db, actor.developer_id, now, limit)
    member_of: dict = {}
    rows, rooms = [], {}
    for row, conv, org in found:
        if conv.org_id not in member_of:
            member_of[conv.org_id] = (await cs.actor_org_role(db, conv.org_id, actor)) is not None
        if member_of[conv.org_id]:
            rows.append(row)
            rooms[row.id] = (conv, org)
    agents, devs = await ca.names_for(db, rows)
    items = []
    for r in rows:
        conv, org = rooms[r.id]
        item = ca.serialize(r, now, requester_name=agents.get(r.requester_agent_did),
                            decider_name=devs.get(r.decided_by_developer_id))
        item["room"] = {"conversation_id": conv.id, "title": conv.title or org.name, "org_id": org.id,
                        "org_name": org.name}
        items.append(item)
    return {"items": items, "count": len(items), "server_time": ca.iso(now)}


@router.get("/approvals/{approval_id}", summary="One approval request, its decision and the proof")
@approval_errors
async def get_approval(
    approval_id: str,
    wait: int = Query(0, ge=0, le=20, description="Seconds to wait while it is still pending (0 = answer now)"),
    actor_dict: dict = Depends(_approval_reader),
    db: AsyncSession = Depends(get_db),
):
    """The record and, once decided, its proof: who decided, when, in which role, how (the credential kind and
    whether this registry's MCP server relayed it, attested; the surface, as the client stated it), the presence
    proof when one was asked for, and the registry's signed statement (its public key travels beside it, outside the
    signed object). Any active member of the room may read it. `wait` holds the answer up to 20 seconds while the
    request is pending, so a session learns the decision about a second after the click."""
    from ..services import chat_approvals as ca
    _approvals_switched_on()
    actor = cs.actor_from_auth(actor_dict)
    row = await ca.fetch(db, approval_id)
    if row is None:
        raise cs.ChatError(404, "approval request not found")
    conv = await cs._get_conversation(db, row.conversation_id)
    await cs.resolve_membership(db, conv, actor)
    if wait:
        row = await ca.wait_until_decided(db, approval_id, wait)
        if row is None:
            raise cs.ChatError(404, "approval request not found")
    now = await ca.db_now(db)
    agents, devs = await ca.names_for(db, [row])
    out = ca.serialize(row, now, requester_name=agents.get(row.requester_agent_did),
                       decider_name=devs.get(row.decided_by_developer_id), include_proof=True)
    if row.decision_statement and row.decision_statement.get("signature"):
        try:
            from ..services.attestation_signer import get_pubkey_b64
            out["decision"]["statement_pubkey_b64"] = get_pubkey_b64()
        except Exception:  # noqa: BLE001 — the key is also served by the attestation rail
            out["decision"]["statement_pubkey_b64"] = None
    return out


async def _decision_card_shows_use(db: AsyncSession, conv, approval_id: str, actor: cs.Actor, label: str, sha: str,
                                   used_at) -> None:
    """V0652 (aa): the approval.decided card of this approval (the rail's `aprdec-<id>` message) gains `used`, in place."""
    import copy
    from ..models import ChatMessage
    m = (await db.execute(select(ChatMessage.id, ChatMessage.card).where(
        ChatMessage.conversation_id == conv.id, ChatMessage.client_ref == f"aprdec-{approval_id}"))).first()
    if m is None or not isinstance(m[1], dict) or m[1].get("type") != "approval.decided":
        return
    card = copy.deepcopy(m[1])                   # the stored value is not edited in place
    card.setdefault("data", {})["used"] = {
        "act": label[:200], "act_sha256": sha,
        "at": used_at.isoformat() if hasattr(used_at, "isoformat") else str(used_at),
        "by_agent_did": actor.agent_did}
    msg, conv2, changed = await cs.update_card(db, conv.id, m[0], actor, card, rail_author=True)
    if changed and conv2 is not None:
        await cs.deliver_card_update(db, conv2, msg, actor)


@router.post("/approvals/{approval_id}/consume",
             summary="Use an approved request to open one act (the agent that asked, once)")
@approval_errors
async def consume_approval(
    approval_id: str,
    req: ApprovalConsumeBody,
    current_agent: Agent = Security(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    V0651 (o): a driver opens its act with an approval instead of a typed word. It may only when the approval is
    approved, by the organization's owner or a named approver who still holds that right now, unexpired, asked with
    production_impact (for a production act), names this act's sha256 (artifact_sha256: the driver file, which pins
    the certified image id), and was never used before. The registry records the use once (`consumed` in GET
    /chat/approvals/{id}), in one UPDATE that repeats every condition, so a race opens one act; a second use answers
    409 naming the act it opened and when. The room gets one line under the approval card. Agents only: the caller is
    the agent that asked.
    """
    from ..services import chat_approvals as ca
    from ..services.admin_audit import log_chat_action
    _approvals_switched_on()
    did = current_agent.did
    sha = ca.normalize_sha256(req.act_sha256)
    label = " ".join(req.act_label.split())
    if not sha or not label:
        raise cs.ChatError(422, "act_label must say what the act is and act_sha256 must name it")
    row = await ca.fetch(db, approval_id, fresh=True)
    now = await ca.db_now(db)
    role = None
    if row is not None and row.decided_by_developer_id is not None and row.org_id:
        org = await ca.org_facts(db, row.org_id)
        role = await ca.decider_role(db, row.org_id, int(row.decided_by_developer_id), (org or {}).get("owner_id"))
    refusal = ca.consume_refusal(row, agent_did=did, act_sha256=sha, now=now, role=role, production=req.production)
    if refusal:
        raise cs.ChatError(*refusal)
    conv = await cs._get_conversation(db, row.conversation_id)
    actor = await _named_sender(db, cs.Actor("agent", agent_did=did,
                                             display_name=getattr(current_agent, "name", None) or did))
    my_row = await cs.resolve_membership(db, conv, actor)
    if my_row.state != "active":
        raise cs.ChatError(409, "you are not active in this approval's conversation: nothing opened")
    used_at = await ca.mark_consumed(db, row.id, agent_did=did, act_label=label, act_sha256=sha)
    if used_at is None:
        # the belt: used, decided otherwise or expired between the read and the write; say which, write nothing
        await db.rollback()
        again = await ca.fetch(db, approval_id, fresh=True)
        refusal = ca.consume_refusal(again, agent_did=did, act_sha256=sha, now=await ca.db_now(db), role=role,
                                     production=req.production)
        raise cs.ChatError(*(refusal or (409, "this approval could not be used at the moment of writing: "
                                              "nothing opened")))
    await log_chat_action(db, action="approval.consumed", actor_type="agent", actor_id=did,
                          target_type="chat_approval", target_id=row.id,
                          details={"conversation_id": conv.id, "org_id": conv.org_id, "act": label,
                                   "act_sha256": sha, "decided_by_developer_id": row.decided_by_developer_id,
                                   "role": role})
    await db.commit()
    used = await ca.fetch(db, row.id, fresh=True)
    # The line follows the record, as the decided card does: one that fails to post is logged, the record stays the
    # authority.
    try:
        msg, dup = await cs.insert_message(db, conv, my_row, actor, "text", ca.consumed_notice(label, sha, used_at),
                                           None, client_ref=f"aprused-{row.id}", reply_to=row.request_message_id,
                                           rail_author=True)
        if not dup:
            payload = cs.serialize_message(msg)
            payload["sender_name"] = actor.display_name
            recipients = await cs.recipients_snapshot(db, conv, actor)
            cs.deliver(conv.id, conv.kind, payload, recipients, actor.display_name)
    except Exception as e:  # noqa: BLE001 — the use is committed; its line is a display
        logger.warning("[CHATAPPROVAL] the use line for %s was not posted: %s", row.id, e)
    # V0652 (aa): the decision's card shows its use on itself (used for <act> at <time>), kept in its history; once
    # used it is closed
    try:
        await _decision_card_shows_use(db, conv, row.id, actor, label, sha, used_at)
    except Exception as e:  # noqa: BLE001 — the use is committed; the card is a display of it
        logger.warning("[CHATAPPROVAL] the decision card of %s does not show its use: %s", row.id, e)
    # V0652 (af): the person who approved it hears that it was used, pushed when the act was a production act (once:
    # mark_consumed above lets one use through); the room's line above reaches everyone else in the app
    try:
        if row.decided_by_developer_id:
            from agentvault_registry.background_tasks import push_notify
            prod = bool(getattr(used, "production_impact", False))
            push_notify.spawn_notice(push_notify.notify(
                "chat.approval_used_production" if prod else "chat.approval_used", [int(row.decided_by_developer_id)],
                title="Your approval was used" + (" for a production act" if prod else ""),
                message=f"{actor.display_name} used your approval {row.id}: {label[:160]}",
                tags="white_check_mark", click=f"/ui#/pocket/ourchat/{conv.id}?approval={row.id}"))
    except Exception:  # noqa: BLE001 — the use is committed; its notice is a courtesy
        logger.debug("[CHATAPPROVAL] the use notice for %s was skipped", row.id, exc_info=True)
    agents, devs = await ca.names_for(db, [used])
    return {"approval": ca.serialize(used, now, requester_name=agents.get(used.requester_agent_did),
                                     decider_name=devs.get(used.decided_by_developer_id))}


@router.post("/conversations/{conversation_id}/approvals/decide",
             summary="Approve or deny approval requests (the org's owner or a named approver)")
@approval_errors
async def decide_approvals(
    conversation_id: str,
    req: ApprovalDecideBody,
    request: Request,
    current_developer=Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """
    Decide one request, several, or every one shown (Approve all). Only requests that are pending and unexpired are
    decided; every other id is reported in `skipped` by name (not_found, expired, already_approved, already_denied).
    Who may decide is read live: the organization's owner, or an active member the owner named an approver. Agents
    never decide (this route takes a developer credential only). When the room's presence setting asks for it, an
    approval needs a phone confirmation: the answer is then 428 with a challenge, and the same call is sent again with
    `challenge_id` once the phone approved it. Denying never asks.
    """
    import json as _json
    from sqlalchemy import text as _sql
    from ..config import settings as _st
    from ..models import ChatApproval
    from ..security import presented_api_key_id, presented_api_key_scopes
    from ..services import chat_approvals as ca
    from ..services.admin_audit import log_chat_action

    _approvals_switched_on()
    # V0653 (w) (session-lead's call, the sessions' room seq 847): a person decides, signed in, in the console or
    # Pocket. An API key never decides, whatever its scopes: an MCP connector's, a bridge's or a script's key reads a
    # room and writes in it, and an injected line it reads must not become his approval of a production act.
    if presented_api_key_id() is not None or presented_api_key_scopes() is not None:
        raise cs.ChatError(403, "an approval is decided in the console or in Pocket, signed in; an API key cannot "
                                "decide it")
    conv, org = await _approval_room(db, conversation_id)
    dev = current_developer
    role = await ca.decider_role(db, conv.org_id, int(dev.id), org["owner_id"])
    if role is None:
        raise cs.ChatError(403, "only the organization's owner or a named approver decides approval requests")
    dev_name = (getattr(dev, "name", None) or getattr(dev, "username", None) or f"developer {dev.id}")
    actor = cs.Actor("developer", developer_id=int(dev.id), display_name=dev_name)
    my_row = await cs.resolve_membership(db, conv, actor, announce_ok=True)

    ids = list(dict.fromkeys(i.strip() for i in req.approval_ids if i and i.strip()))
    if not ids:
        raise cs.ChatError(422, "approval_ids must name at least one request")
    rows = (await db.execute(select(ChatApproval).where(
        ChatApproval.conversation_id == conv.id, ChatApproval.id.in_(ids)).with_for_update())).scalars().all()
    now = await ca.db_now(db)
    # V0652 (ab): a choice is decided by one of its options, one request at a time; an approval is approved or denied
    if req.decision == "choose":
        if len(ids) != 1 or req.option is None:
            raise cs.ChatError(422, "choose decides one choice request at a time, by the index of one of its options")
        r0 = next((r for r in rows if r.id == ids[0]), None)
        r0_opts = list(getattr(r0, "options", None) or []) if r0 is not None else []
        if r0 is not None and not r0_opts:
            raise cs.ChatError(409, "this is an approval request, not a choice: approve or deny it")
        if r0 is not None and not (0 <= int(req.option) < len(r0_opts)):
            raise cs.ChatError(422, f"option must be 0 to {len(r0_opts) - 1}: this choice offers {len(r0_opts)}")
    elif req.decision == "approve" and any(getattr(r, "options", None) for r in rows):
        raise cs.ChatError(409, "a choice is decided by choosing one of its options (decision choose, option), or "
                                "declined with deny")
    decidable, skipped = ca.partition_for_decision(rows, ids, now)
    if not decidable:
        code, sentence, already = ca.refusal_when_nothing_decided(skipped, req.decision)
        if already and req.decision == "choose":
            # a choice is made once: the same option again is the same decision; another option is not
            r0 = next((r for r in rows if r.id == ids[0]), None)
            if r0 is None or getattr(r0, "chosen_option", None) != int(req.option):
                label = (list(getattr(r0, "options", None) or [])[int(r0.chosen_option)]
                         if r0 is not None and getattr(r0, "chosen_option", None) is not None else "another option")
                raise cs.ChatError(409, f"this choice was already made: {label!r}; a decision is final")
        if already:
            return {"decision": ca.DECISIONS[req.decision], "decided": [], "skipped": skipped, "already": True}
        raise cs.ChatError(code, sentence)

    policy = ca.presence_policy(ca.registry_presence(), org["settings"])
    presence = None
    if any(ca.presence_required(policy, req.decision, r.production_impact) for r in decidable):
        presence = await ca.require_device_presence(db, dev, decision=req.decision, rows=decidable,
                                                    conversation_id=conv.id, challenge_id=req.challenge_id)
    via = ca.via_record(api_key_id=presented_api_key_id(), api_key_scopes=presented_api_key_scopes(),
                        mcp_relay=_mcp_relay_attested(request), surface=req.surface)
    word = ca.DECISIONS[req.decision]
    note = (req.note or "").strip() or None
    statements = {}
    for r in decidable:
        chosen = int(req.option) if req.decision == "choose" else None
        stmt = ca.build_statement(r, decision=req.decision, decided_at=now, decider_id=int(dev.id),
                                  decider_name=dev_name, role=role, via=via, presence=presence,
                                  registry=str(getattr(_st, "REGISTRY_NAME", "") or ""), chosen=chosen)
        res = await db.execute(_sql(
            "UPDATE chat_approvals SET status = :st, decided_at = :t, decided_by_developer_id = :d, "
            "decided_by_role = :role, decision_note = :n, decision_via = CAST(:via AS JSONB), "
            "presence_method = :pm, presence_challenge_id = :pc, decision_statement = CAST(:stmt AS JSONB), "
            "chosen_option = :co "
            "WHERE id = :id AND status = 'pending' AND expires_at > now() RETURNING id"),
            {"st": word, "t": now, "d": int(dev.id), "role": role, "n": note, "via": _json.dumps(via),
             "pm": (presence or {}).get("method"), "pc": (presence or {}).get("challenge_id"),
             "stmt": _json.dumps(stmt), "co": chosen, "id": r.id})
        if res.first() is None:
            skipped[r.id] = "expired"      # the belt: a request that expired under us is never decided
            continue
        statements[r.id] = stmt
    if not statements:
        await db.rollback()
        code, sentence, already = ca.refusal_when_nothing_decided(skipped, req.decision)
        raise cs.ChatError(code if code != 200 else 409, sentence)
    await log_chat_action(db, action=f"approval.{word}", actor_type="developer", actor_id=str(dev.id),
                          target_type="chat_approval", target_id=",".join(sorted(statements))[:255],
                          details={"conversation_id": conv.id, "org_id": conv.org_id, "role": role,
                                   "count": len(statements), "skipped": skipped, "via": via,
                                   "presence_method": (presence or {}).get("method")})
    await db.commit()

    decided_rows = [await ca.fetch(db, aid, fresh=True) for aid in statements]
    decided_rows = [r for r in decided_rows if r is not None]
    agents, _ = await ca.names_for(db, decided_rows)
    out = [ca.serialize(r, now, requester_name=agents.get(r.requester_agent_did), decider_name=dev_name)
           for r in decided_rows]
    # The cards follow the record (the org-receipt discipline): a card that fails to post is logged, and the record
    # (GET /chat/approvals/{id}) stays the authority.
    for r in decided_rows:
        try:
            card = ca.decided_card(r, statements[r.id])
            msg, dup = await cs.insert_message(db, conv, my_row, actor, "card", None, card,
                                               client_ref=f"aprdec-{r.id}", reply_to=r.request_message_id,
                                               rail_author=True)
            if not dup:
                payload = cs.serialize_message(msg)
                payload["sender_name"] = dev_name
                recipients = await cs.recipients_snapshot(db, conv, actor)
                cs.deliver(conv.id, conv.kind, payload, recipients, dev_name,
                           sender_owner_dev_id=int(dev.id))
        except Exception as e:  # noqa: BLE001 — the decision is committed; its card is a display
            logger.warning("[CHATAPPROVAL] the decided card for %s was not posted: %s", r.id, e)
    return {"decision": word, "decided": out, "skipped": skipped, "already": False}
