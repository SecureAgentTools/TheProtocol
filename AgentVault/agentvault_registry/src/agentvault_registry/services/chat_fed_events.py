"""V0663 (order gwo_9dce94d939aff2fa8ea4f91c): edits, take-backs, reactions, pins and a room's archive or close across frames.

A thread another registry hosts (a cross-frame room or a direct thread) is mirrored here. The HOST stays the only authority, as for
messages: it applies a change, then tells every registry that has a member in the thread. This module is the three halves of that:

  * HOST, publish: after a change on a thread it hosts, one EVENT per resident registry in the same outbox the messages use
    (`chat_federation_outbox.event_id` set, its seq the host's last seq when it was made, so events and messages keep their order).
  * RESIDENT, relay: a member of a mirror who edits, takes back, reacts or pins sends the request to the host
    (POST /api/v1/federation/chat/relay-event); nothing is applied on the mirror before the host says so.
  * HOST, apply a relayed request under the SAME rules a local thread has (sender only and the window for an edit, a room's
    operators for a pin, the closed reaction words), then publish; RESIDENT, receive an event and apply the host's word to the mirror.

An event names the message by the HOST's seq, which every mirror stores as remote_seq. A mirror that does not hold that message yet
answers 503 and the host sends it again, bounded like a message's retry (an event whose message never arrives expires with the
outbox's own attempts instead of looping), so a late message cannot lose its edit. Δ-irrelevant: no money moves here.

THE LIMIT, on the record: events are LIVE. A registry that joins a thread later mirrors the messages it receives from then on and is
told nothing about earlier reactions and pins on lines it never saw; an edit or a take-back of a line it never received finds no
message and expires the same way. A thread's pins and reactions are not backfilled to a new member's registry in this version.
"""
from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.models import (ChatFederationOutbox, ChatMessage, ChatMessageEdit, ChatPin, ChatReaction,
                                        Conversation, ConversationParticipant)
from agentvault_registry.services import chat_federation as fed
from agentvault_registry.services import chat_service as cs

logger = logging.getLogger(__name__)

EVENT_TYPES = ("edit", "delete", "reaction", "pin", "room")
ROOM_EVENTS = ("archive", "unarchive", "close")


# ── the wire ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _iso(dt: Optional[datetime.datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _parse_dt(raw: Any) -> Optional[datetime.datetime]:
    try:
        d = datetime.datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


async def local_actor_key(db: AsyncSession, actor: "cs.Actor") -> str:
    """The key a LOCAL principal goes by in an event: `handle@this registry` (or `dev:<id>@…`, an agent's DID@…), the form the
    participant list already uses."""
    return fed.remote_key(await fed.local_wire_id(db, actor.ptype, actor.developer_id if actor.ptype == "developer"
                                                  else actor.agent_did), fed.self_base_url())


def event_envelope(conv: Conversation, event: Dict[str, Any], participants: List[dict]) -> dict:
    """The wire format of one event: the host and the thread as a message envelope states them, and the event."""
    return {"v": 1, "host_registry": fed.self_base_url(),
            "conversation": {"id": conv.id, "kind": conv.kind, "title": conv.title, "participants": participants},
            "event": {**event, "id": event.get("id") or str(uuid.uuid4())}}


async def _targets(db: AsyncSession, conv: Conversation) -> List[str]:
    parts = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id, ConversationParticipant.ptype == "remote"))).scalars().all()
    out = set()
    for p in parts:
        parsed = fed.parse_remote_key(p.remote_key or "")
        if parsed:
            out.add(parsed[1])
    return sorted(out)


async def publish(db: AsyncSession, conv: Conversation, event: Dict[str, Any]) -> int:
    """HOST: queue `event` for the home registry of every remote participant (the originator's included: its mirror learns the
    change from the host, never from itself). Commits nothing: the caller owns the transaction, because an event that exists without
    its change would be a promise about something that never happened. Returns the rows queued (0 on a mirror or a thread no other
    registry reaches)."""
    if conv.host_registry:
        return 0
    targets = await _targets(db, conv)
    if not targets:
        return 0
    env = event_envelope(conv, event, await fed.participant_wire(db, conv))
    for base in targets:
        db.add(ChatFederationOutbox(id=str(uuid.uuid4()), conversation_id=conv.id, seq=int(conv.last_seq or 0),
                                    event_id=env["event"]["id"], peer_base_url=base, payload=env))
    fed.wake_after_commit(db)
    return len(targets)


# ── HOST: apply a request a resident relayed, under a local thread's rules ───────────────────────────────────────────
class _KeyOnly:
    """The one attribute recipients_snapshot reads from a sender: its principal key."""

    def __init__(self, key: str):
        self.key = key


async def _relayed_target(db: AsyncSession, conversation_ref: str, actor_key: str, peer: str
                          ) -> Tuple[Conversation, ConversationParticipant]:
    """The thread this registry hosts and the REMOTE seat the request comes from: the peer must be the actor's own home, the actor
    seated and not gone, and in a room the host's own gates (not banned, not pending, not muted)."""
    parsed = fed.parse_remote_key(actor_key)
    if not parsed:
        raise cs.ChatError(422, "actor_key must be handle@https://their.registry")
    await fed.assert_peer_allowed(db, parsed[1])
    if not await fed.caller_is(db, peer, parsed[1]):
        raise cs.ChatError(403, "the calling registry is not the actor's home registry")
    conv = (await db.execute(select(Conversation).where(Conversation.id == conversation_ref))).scalars().first()
    if conv is None or conv.host_registry:
        raise cs.ChatError(404, "this registry does not host that thread")
    part = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id, ConversationParticipant.ptype == "remote",
        ConversationParticipant.remote_key == actor_key))).scalars().first()
    if part is None:
        raise cs.ChatError(403, f"'{actor_key}' is not a participant in that thread")
    if part.state == "left":
        raise cs.ChatError(409, "that participant has left the thread")
    from agentvault_registry.services import chat_rooms as rooms
    await rooms.relay_gate(db, conv, part, change=True)
    return conv, part


async def _host_message(db: AsyncSession, conv: Conversation, seq: int, part: ConversationParticipant) -> ChatMessage:
    msg = (await db.execute(select(ChatMessage).where(
        ChatMessage.conversation_id == conv.id, ChatMessage.seq == int(seq)).with_for_update())).scalars().first()
    if msg is None or msg.seq <= int(part.hidden_before_seq or 0):
        raise cs.ChatError(404, "no such message in this thread")
    return msg


async def host_apply_relayed(db: AsyncSession, req: Dict[str, Any], peer: str) -> Dict[str, Any]:
    """HOST: one change a resident's member asked for. `req`: conversation_ref, actor_key, actor_display, type, message_seq and the
    type's fields (edit: body; reaction: word, on; pin: on). Applied under the rules of a local thread, published to every
    registry (the asker's included), and answered with the host's own copy of the result. COMMITS."""
    from agentvault_registry.services import chat_edits as ce
    from agentvault_registry.services import chat_pins as cp
    from agentvault_registry.services import chat_reactions as cr
    etype = str(req.get("type") or "")
    if etype not in ("edit", "delete", "reaction", "pin"):
        raise cs.ChatError(422, f"a resident may ask for: edit, delete, reaction, pin (not {etype!r})")
    actor_key = str(req.get("actor_key") or "")
    # E2: the caps the message relay and the local routes have, per calling registry and per thread-and-registry first (before
    # any read), then per actor once it is known to be seated. Each change queues a row per registry with a member.
    if (not await fed.fed_rate_ok("relay_event_peer", peer)
            or not await fed.fed_rate_ok("relay_event_thread", str(req.get("conversation_ref") or ""), peer)):
        raise cs.ChatError(429, "this registry is asking for changes faster than the thread's host accepts; slow down")
    conv, part = await _relayed_target(db, str(req.get("conversation_ref") or ""), actor_key, peer)
    if not await fed.fed_rate_ok("relay_event_actor", actor_key):
        raise cs.ChatError(429, "that member is changing messages faster than the thread's host accepts; slow down")
    msg = await _host_message(db, conv, int(req.get("message_seq") or 0), part)
    me = cs.principal_key("remote", actor_key)
    display = str(req.get("actor_display") or actor_key)
    now = cs.message_clock()
    event: Dict[str, Any]
    if etype in ("edit", "delete"):
        revs = await cs._edit_revs(db, msg.id)
        mine = cs.sender_key_of(msg) == me
        why = ce.refusal(msg.kind, deleted=msg.deleted_at is not None, mirrored=False, mine=mine, created_at=msg.created_at,
                         now=now, revs=revs, editing=(etype == "edit"))
        if why:
            raise cs.ChatError(409 if mine else 403, why)
        if etype == "edit":
            body = req.get("body")
            if not isinstance(body, str) or not body.strip():
                raise cs.ChatError(422, "a message needs text: take it back instead of emptying it")
            bad = cs.validate_body(body)
            if bad:
                raise cs.ChatError(422, bad)
            if body == (msg.body or ""):
                return {"message": cs.serialize_message(msg), "changed": False}
            db.add(ChatMessageEdit(message_id=msg.id, conversation_id=conv.id, rev=revs + 1, kind="edit",
                                   body_before=msg.body, actor_ptype="remote", actor_id=actor_key, created_at=now))
            msg.body, msg.edited_at = body, now
            if int(conv.last_seq or 0) == int(msg.seq):
                conv.last_preview = cs.preview_for("text", body, None, display)
            event = {"type": "edit", "message_seq": int(msg.seq), "body": body, "at": _iso(now), "rev": revs + 1,
                     "actor": actor_key}
        else:
            db.add(ChatMessageEdit(message_id=msg.id, conversation_id=conv.id, rev=revs + 1, kind="delete",
                                   body_before=msg.body, actor_ptype="remote", actor_id=actor_key, created_at=now))
            msg.deleted_at = now
            await db.execute(sa_delete(ChatPin).where(ChatPin.message_id == msg.id))
            if int(conv.last_seq or 0) == int(msg.seq):
                conv.last_preview = ""
            event = {"type": "delete", "message_seq": int(msg.seq), "at": _iso(now), "actor": actor_key}
        result: Dict[str, Any] = {"message": cs.serialize_message(msg), "changed": True}
    elif etype == "reaction":
        word, on = str(req.get("word") or ""), bool(req.get("on", True))
        if not cr.valid(word):
            raise cs.ChatError(422, f"a reaction is one of: {', '.join(cr.VOCAB)}")
        why = cr.refusal(msg.kind, deleted=msg.deleted_at is not None)
        if why:
            raise cs.ChatError(409, why)
        existing = (await db.execute(select(ChatReaction).where(
            ChatReaction.message_id == msg.id, ChatReaction.actor_ptype == "remote",
            ChatReaction.actor_id == actor_key, ChatReaction.word == word))).scalars().first()
        if on and existing is None:
            db.add(ChatReaction(message_id=msg.id, conversation_id=conv.id, word=word, actor_ptype="remote", actor_id=actor_key))
        elif not on and existing is not None:
            await db.delete(existing)
        else:
            return {"message_id": msg.id, "seq": int(msg.seq), "changed": False}
        event = {"type": "reaction", "message_seq": int(msg.seq), "word": word, "on": on, "actor": actor_key}
        result = {"message_id": msg.id, "seq": int(msg.seq), "changed": True}
    else:                                                    # pin
        on = bool(req.get("on", True))
        if conv.kind == "room" and part.role not in _operator_roles():
            raise cs.ChatError(403, "in a room its owner and moderators pin")
        already = (await db.execute(select(ChatPin.id).where(
            ChatPin.conversation_id == conv.id, ChatPin.message_id == msg.id))).first() is not None
        n = await cs._pin_count(db, conv.id)
        if on:
            why = cp.refusal(conv.kind, msg.kind, deleted=msg.deleted_at is not None, pins_now=n, already=already)
            if why:
                raise cs.ChatError(409, why)
            if already:
                return {"message_id": msg.id, "changed": False}
            db.add(ChatPin(conversation_id=conv.id, message_id=msg.id, pinned_by_ptype="remote", pinned_by_id=actor_key))
        else:
            if not already:
                return {"message_id": msg.id, "changed": False}
            await db.execute(sa_delete(ChatPin).where(ChatPin.conversation_id == conv.id, ChatPin.message_id == msg.id))
        event = {"type": "pin", "message_seq": int(msg.seq), "on": on, "actor": actor_key}
        result = {"message_id": msg.id, "conversation_id": conv.id, "pinned": on, "changed": True}
    await publish(db, conv, event)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise cs.ChatError(409, "another change of this message landed at the same moment: read it and try again")
    result["conversation_id"] = conv.id
    result["_fan"] = {"conv": conv, "event": event, "actor_key": actor_key, "display": display, "message": result.get("message")}
    return result


def _operator_roles() -> Tuple[str, ...]:
    from agentvault_registry.services import chat_rooms as rooms
    return rooms.OPERATOR_ROLES


# ── RESIDENT: the record of a change this registry relayed (E1) ──────────────────────────────────────────────────────
EVENT_RELAY_TTL_S = 7 * 24 * 3600


def _event_relay_key(host: str, remote_ref: str, etype: str, message_seq: int, actor_key: str, word: str, on: Optional[bool]) -> str:
    import hashlib
    raw = "|".join([str(host).rstrip("/"), str(remote_ref), str(etype), str(int(message_seq)), str(actor_key), str(word or ""),
                    "" if on is None else ("1" if on else "0")])
    return "chatfed:evrelayed:" + hashlib.sha256(raw.encode()).hexdigest()[:40]


async def _record_event_relay(host: str, remote_ref: str, etype: str, message_seq: int, actor_key: str, *,
                              word: str = "", on: Optional[bool] = None) -> None:
    """Remember that THIS registry relayed this very change for `actor_key`, before the POST: the host's event of it is read as the
    actor's own only when we sent it (a delivered message is believed the same way: `chat_federation._we_relayed`). Without the
    record (no Redis, an expired record) the event reads as a remote actor's, never as a forged local one."""
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is not None:
            await r.set(_event_relay_key(host, remote_ref, etype, message_seq, actor_key, word, on), actor_key,
                        ex=EVENT_RELAY_TTL_S)
    except Exception as e:  # noqa: BLE001
        logger.warning("[CHATFED] event relay record not written: %s", type(e).__name__)


async def _we_relayed_event(host: str, remote_ref: str, etype: str, message_seq: int, actor_key: str, *,
                            word: str = "", on: Optional[bool] = None) -> bool:
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return False
        got = await r.get(_event_relay_key(host, remote_ref, etype, message_seq, actor_key, word, on))
        if isinstance(got, bytes):
            got = got.decode()
        return bool(got) and got == actor_key
    except Exception:  # noqa: BLE001
        return False


# ── RESIDENT: ask the host ───────────────────────────────────────────────────────────────────────────────────────────
async def relay_change(db: AsyncSession, conv: Conversation, actor: "cs.Actor", message: ChatMessage, etype: str,
                       **fields: Any) -> Dict[str, Any]:
    """RESIDENT: a member of this mirror asks the host for a change (`POST /api/v1/federation/chat/relay-event`). Nothing is
    stored here: the host decides, and its event comes back to this registry like every other. Raises cs.ChatError with the
    host's own sentence when it refuses, or 502 when it cannot be reached (nothing was changed)."""
    if not conv.host_registry or not conv.remote_ref:
        raise cs.ChatError(409, "this thread is not a mirror of another registry's thread")
    if getattr(conv, "archived_at", None) is not None:
        # V0663 recut: the mirror's own copy shows the room archived, so a member's change is refused here, before it leaves
        raise cs.ChatError(409, cs.ARCHIVED_CHANGE)
    if message.remote_seq is None:
        raise cs.ChatError(409, "this message has no place at the thread's host yet: try again in a moment")
    payload = {"conversation_ref": conv.remote_ref, "actor_key": await local_actor_key(db, actor),
               "actor_display": actor.display_name or "", "type": etype, "message_seq": int(message.remote_seq), **fields}
    if etype in ("reaction", "pin"):
        # E1: the host's event of this change comes back naming our own user; it is believed only because this record exists
        await _record_event_relay(conv.host_registry, conv.remote_ref, etype, int(message.remote_seq), payload["actor_key"],
                                  word=str(fields.get("word") or ""), on=bool(fields.get("on", True)))
    target, kwargs, headers = await fed.federation_target(db, conv.host_registry)
    url = f"{target.rstrip('/')}/api/v1/federation/chat/relay-event"
    try:
        r = await fed.peer_client(target, kwargs).post(url, headers=headers, json=payload)
    except Exception as e:  # noqa: BLE001
        logger.warning("[CHATFED] relay-event to %s failed: %s", conv.host_registry, type(e).__name__)
        raise cs.ChatError(502, "the thread's host registry could not be reached; nothing was changed")
    if r.status_code in (200, 201):
        try:
            return r.json()
        except ValueError:
            return {}
    detail = ""
    try:
        detail = str((r.json() or {}).get("detail") or "")[:240]
    except ValueError:
        pass
    raise cs.ChatError(502 if r.status_code >= 500 else r.status_code,
                       detail or f"the thread's host registry refused the change ({r.status_code})")


# ── RESIDENT: apply the host's word to the mirror ────────────────────────────────────────────────────────────────────
async def _mapped_actor(db: AsyncSession, wire_key: str, relayed: bool = False) -> Tuple[str, str]:
    """(ptype, id) an event's actor is stored under here: one of THIS registry's own principals as itself (so its reactions read
    as `mine` on this side) ONLY when this registry relayed that change (`relayed`, E1: a host's word that one of our users did
    something we never sent is not our user's act), anyone else as a remote."""
    parsed = fed.parse_remote_key(wire_key)
    if relayed and parsed and fed.origin(parsed[1]) == fed.origin(fed.self_base_url()):
        own = await fed._resolve_local_principal(db, parsed[0])
        if own is not None:
            return own
    return "remote", wire_key


async def receive_event(db: AsyncSession, envelope: Dict[str, Any], peer: str) -> Dict[str, Any]:
    """RESIDENT: one event the host delivered. IDEMPOTENT (a repeat changes nothing and answers duplicate). The host is the
    envelope's, checked twice exactly as a delivered message is; a thread this registry has no mirror of is refused (an event
    cannot create one). Applies the host's word and COMMITS; the route fans out to our members from the returned `fan`."""
    if not fed.federation_enabled():
        raise fed.FederationOff("cross-registry chat is not enabled on this registry")
    if int(envelope.get("v") or 0) != 1:
        raise cs.ChatError(422, "unsupported federation envelope version")
    host = str(envelope.get("host_registry") or "").rstrip("/")
    if not host:
        raise cs.ChatError(422, "envelope is missing its host_registry")
    await fed.assert_peer_allowed(db, host)
    if not await fed.caller_is(db, peer, host):
        raise cs.ChatError(403, "the calling registry is not this thread's host")
    c_in, ev = envelope.get("conversation") or {}, envelope.get("event") or {}
    etype = str(ev.get("type") or "")
    if etype not in EVENT_TYPES:
        raise cs.ChatError(422, f"unknown event type {etype!r}")
    remote_ref = str(c_in.get("id") or "")
    conv = (await db.execute(select(Conversation).where(
        Conversation.host_registry == host, Conversation.remote_ref == remote_ref))).scalars().first()
    if conv is None:
        raise cs.ChatError(404, "this registry holds no mirror of that thread")
    if not await fed.fed_rate_ok("deliver_thread", host, remote_ref) or not await fed.fed_rate_ok("deliver_peer", host):
        raise cs.ChatError(429, "this peer is delivering faster than this registry accepts for one thread; retry later")

    if etype == "room":
        return await _receive_room(db, conv, str(ev.get("action") or ""), _parse_dt(ev.get("at")))
    seq = int(ev.get("message_seq") or 0)
    msg = (await db.execute(select(ChatMessage).where(
        ChatMessage.conversation_id == conv.id, ChatMessage.remote_seq == seq))).scalars().first()
    if msg is None:
        # the message itself has not been delivered here yet: say so, and the host sends this again
        raise cs.ChatError(503, "the message this event is about has not been delivered here yet")
    actor_key = str(ev.get("actor") or "")
    if etype == "edit":
        rev, body = int(ev.get("rev") or 0), ev.get("body")
        revs = await cs._edit_revs(db, msg.id)
        if rev <= revs or not isinstance(body, str):
            return {"conversation_id": conv.id, "duplicate": True}
        when = _parse_dt(ev.get("at")) or cs.message_clock()
        db.add(ChatMessageEdit(message_id=msg.id, conversation_id=conv.id, rev=rev, kind="edit", body_before=msg.body,
                               actor_ptype="remote", actor_id=actor_key or host, created_at=when))
        msg.body, msg.edited_at = body, when
        if int(conv.last_seq or 0) == int(msg.seq):
            conv.last_preview = cs.preview_for("text", body, None, None)
    elif etype == "delete":
        if msg.deleted_at is not None:
            return {"conversation_id": conv.id, "duplicate": True}
        when = _parse_dt(ev.get("at")) or cs.message_clock()
        revs = await cs._edit_revs(db, msg.id)
        db.add(ChatMessageEdit(message_id=msg.id, conversation_id=conv.id, rev=revs + 1, kind="delete", body_before=msg.body,
                               actor_ptype="remote", actor_id=actor_key or host, created_at=when))
        msg.deleted_at = when
        await db.execute(sa_delete(ChatPin).where(ChatPin.message_id == msg.id))
        if int(conv.last_seq or 0) == int(msg.seq):
            conv.last_preview = ""
    elif etype == "reaction":
        from agentvault_registry.services import chat_reactions as cr
        word, on = str(ev.get("word") or ""), bool(ev.get("on", True))
        if not cr.valid(word):
            # E4: a word outside the closed vocabulary is never stored (a long one would be a DataError, a 500 and a thread held
            # back); answered 200 so the host's later rows for this thread are not held behind a row that can never apply
            logger.warning("[CHATFED] a reaction word outside the vocabulary was not stored (host %s)", host)
            return {"conversation_id": conv.id, "duplicate": True, "refused": "reaction word"}
        aptype, aid = await _mapped_actor(db, actor_key, await _we_relayed_event(
            host, remote_ref, "reaction", seq, actor_key, word=word, on=on))
        existing = (await db.execute(select(ChatReaction).where(
            ChatReaction.message_id == msg.id, ChatReaction.actor_ptype == aptype,
            ChatReaction.actor_id == aid, ChatReaction.word == word))).scalars().first()
        if on and existing is None:
            db.add(ChatReaction(message_id=msg.id, conversation_id=conv.id, word=word, actor_ptype=aptype, actor_id=aid))
        elif not on and existing is not None:
            await db.delete(existing)
        else:
            return {"conversation_id": conv.id, "duplicate": True}
    else:                                                    # pin
        on = bool(ev.get("on", True))
        aptype, aid = await _mapped_actor(db, actor_key, await _we_relayed_event(host, remote_ref, "pin", seq, actor_key, on=on))
        already = (await db.execute(select(ChatPin.id).where(
            ChatPin.conversation_id == conv.id, ChatPin.message_id == msg.id))).first() is not None
        if on and not already:
            db.add(ChatPin(conversation_id=conv.id, message_id=msg.id, pinned_by_ptype=aptype, pinned_by_id=aid))
        elif not on and already:
            await db.execute(sa_delete(ChatPin).where(ChatPin.conversation_id == conv.id, ChatPin.message_id == msg.id))
        else:
            return {"conversation_id": conv.id, "duplicate": True}
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return {"conversation_id": conv.id, "duplicate": True}
    return {"conversation_id": conv.id, "duplicate": False, "type": etype, "message_id": msg.id,
            "actor": actor_key, "kind": conv.kind}


async def _receive_room(db: AsyncSession, conv: Conversation, action: str, at: Optional[datetime.datetime]) -> Dict[str, Any]:
    """RESIDENT: the host archived, unarchived or closed a room. A mirror follows: archived it leaves the lists here too and is
    read, not posted in; closed (an empty room the host removed) it goes with its seats."""
    if conv.kind != "room":
        raise cs.ChatError(422, "only a room is archived or closed")
    if action == "archive":
        if conv.archived_at is not None:
            return {"conversation_id": conv.id, "duplicate": True}
        conv.archived_at, conv.archived_by = at or cs.message_clock(), "host"
    elif action == "unarchive":
        if conv.archived_at is None:
            return {"conversation_id": conv.id, "duplicate": True}
        conv.archived_at, conv.archived_by = None, None
    elif action == "close":
        # E3: the host's own rule closes only a room nobody has spoken in (chat_rooms.close_room archives one with messages); a
        # mirror that holds a line from a person or an agent follows that rule instead of deleting its members' history
        spoken = int((await db.execute(select(func.count()).select_from(ChatMessage).where(
            ChatMessage.conversation_id == conv.id, ChatMessage.kind != "system"))).scalar() or 0)
        if spoken:
            if conv.archived_at is not None:
                return {"conversation_id": conv.id, "duplicate": True}
            conv.archived_at, conv.archived_by = at or cs.message_clock(), "host"
            await db.commit()
            return {"conversation_id": conv.id, "duplicate": False, "type": "room", "action": "archive", "kind": "room"}
        cid = conv.id
        await db.delete(conv)
        await db.commit()
        return {"conversation_id": cid, "duplicate": False, "type": "room", "action": "close", "kind": "room"}
    else:
        raise cs.ChatError(422, f"unknown room event {action!r}")
    await db.commit()
    return {"conversation_id": conv.id, "duplicate": False, "type": "room", "action": action, "kind": "room"}


# ── live fan-out to THIS registry's members (the same envelopes the local changes send) ─────────────────────────────
_WS_EVENT = {"edit": "chat.message_edited", "delete": "chat.message_deleted", "reaction": "chat.message_reaction",
             "pin": "chat.pins_changed", "room": "chat.room_changed"}


async def announce(db: AsyncSession, conv_id: str, event: Dict[str, Any], *, message_id: Optional[str] = None,
                   actor_display: str = "") -> None:
    """Tell this registry's own members about a change that was just applied here (by the host for a request a resident relayed, or
    on a mirror for an event the host delivered). Everyone active in the thread hears it, the actor's own devices included: the
    change reached this registry only now. No notice, no push, no sync wake for a reaction or a pin (as a local change)."""
    etype = str(event.get("type") or "")
    conv = (await db.execute(select(Conversation).where(Conversation.id == conv_id))).scalars().first()
    if conv is None and etype != "room":
        return
    payload: Dict[str, Any]
    if etype in ("edit", "delete"):
        msg = (await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))).scalars().first()
        if msg is None or conv is None:
            return
        payload = cs.serialize_message(msg)
    elif etype == "reaction":
        msg = (await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))).scalars().first()
        if msg is None or conv is None:
            return
        summ = (await cs.reaction_summaries(db, conv.id, [msg.id], set())).get(msg.id, [])
        payload = {"id": msg.id, "conversation_id": conv.id, "seq": int(msg.seq), "word": event.get("word"),
                   "reactions": [{"key": r["key"], "count": r["count"]} for r in summ],
                   "by": {"ptype": "remote", "id": event.get("actor")}}
    elif etype == "pin":
        if conv is None:
            return
        payload = {"id": message_id, "conversation_id": conv.id, "pinned": bool(event.get("on", True)),
                   "count": await cs._pin_count(db, conv.id)}
    else:
        payload = {"id": conv_id, "conversation_id": conv_id, "action": event.get("action")}
        if conv is None:                       # a closed room: nobody is left to tell on a registry with no copy
            return
    recipients = await cs.recipients_snapshot(db, conv, _KeyOnly("fed:event"))
    await cs.fan_out_card_update(conv.id, conv.kind, payload, recipients, actor_display, sender_owner_dev_id=None,
                                 event=_WS_EVENT.get(etype, "chat.card_updated"), wake=etype in ("edit", "delete"))
