"""V0659 (f): cross-frame rooms (the design: sessionlogs2026/DESIGN_2026-11-07_XFRAME_ROOMS.md, approved at room seq
2201). A room is a thread with its own member list (kind 'room'), NOT an organization's room: those stay local, since
their membership is one registry's roster.

A room is HOSTED for life by the registry it was opened on, on the same path a cross-frame direct chat takes
(services/chat_federation): the host is the only writer of seq and delivers once per resident registry; a member on
another registry is a remote participant row the host keeps (`ptype='remote'`, its address), and its home keeps a
mirror and relays its sends. This module is the HOST's half: opening a room, seating members under the owner's join
rule, and moderation. A resident never moderates; it shows what its host decided.

THE BINDING RULE (session-lead, seq 2201): a registry may join, speak or announce only for its OWN residents. Every
remote participant key the host takes from a peer is checked against the authenticated peer (chat_federation.caller_is):
the key's origin must be the calling registry, or one peer could join a room, or dodge a ban, in another's name.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.models import ChatRoomBan, Conversation, ConversationParticipant
from agentvault_registry.services import chat_service as cs

JOIN_RULES = ("invited", "request", "anyone")
DEFAULT_JOIN_RULE = "invited"
MAX_MEMBERS = 200                 # active and pending seats in one room
MAX_ROOMS_PER_OWNER = 20          # rooms one principal owns on this registry
TITLE_MAX = 160
OPERATOR_ROLES = ("owner", "moderator")
ROOM_ACTIONS = ("invite", "mute", "unmute", "remove", "ban", "accept", "moderator", "unmoderator", "rule", "topic",
                "title")
SEATED = ("active", "pending")


def room_address(conv: Conversation) -> str:
    """A room's address: room:<conversation id>@<its host's origin>, the form a person's key takes."""
    from agentvault_registry.services import chat_federation as fed
    return f"room:{conv.id}@{fed.origin(fed.self_base_url())}"


def parse_room_address(raw: str) -> Optional[Tuple[str, str]]:
    """'room:<id>@https://host' -> (id, origin), or None."""
    from agentvault_registry.services import chat_federation as fed
    s = str(raw or "").strip()
    if not s.lower().startswith("room:") or "@" not in s:
        return None
    rid, _, host = s[5:].rpartition("@")
    rid = rid.strip()
    if not rid or not host.lower().startswith(("https://", "http://")):
        return None
    return rid, fed.origin(host)


def _key_of_row(p: ConversationParticipant) -> str:
    if p.ptype == "remote":
        return str(p.remote_key or "")
    if p.ptype == "developer":
        return cs.principal_key("developer", p.developer_id)
    return cs.principal_key("agent", p.agent_did)


async def _hosted_room(db: AsyncSession, conversation_id: str) -> Conversation:
    conv = (await db.execute(select(Conversation).where(Conversation.id == conversation_id))).scalars().first()
    if conv is None or conv.kind != "room" or conv.host_registry:
        raise cs.ChatError(404, "this registry does not host that room")
    return conv


async def _seated_count(db: AsyncSession, conv_id: str) -> int:
    return int((await db.execute(select(func.count()).select_from(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv_id,
        ConversationParticipant.state.in_(SEATED)))).scalar() or 0)


async def _banned(db: AsyncSession, conv_id: str, key: str) -> bool:
    return (await db.execute(select(ChatRoomBan).where(
        ChatRoomBan.conversation_id == conv_id, ChatRoomBan.participant_key == key))).scalars().first() is not None


async def _queue_for(db: AsyncSession, conv: Conversation, name: str):
    """The before_commit hook that queues a hosted message for every resident registry in its own transaction."""
    from agentvault_registry.services import chat_federation as fed
    if not fed.federation_enabled():
        return None

    async def _queue(m):
        await fed.enqueue_delivery(db, conv, m, name)
    return _queue


async def _post_system(db: AsyncSession, conv: Conversation, actor: cs.Actor, actor_row: ConversationParticipant,
                       action: str, target_name: Optional[str] = None, value: Optional[str] = None):
    """The visible row every member's copy shows: who did what (the in-band record of every room act)."""
    name = actor.display_name or actor.key
    msg, _dup = await cs.insert_message(
        db, conv, actor_row, actor, "system", f"room.{action}",
        cs._room_system_card(actor, name, action, target_name, value),
        f"room-{action}-{uuid.uuid4().hex}", before_commit=await _queue_for(db, conv, name))
    return msg


# ── opening a room ────────────────────────────────────────────────────────────────────────────────────────────────
async def create_room(db: AsyncSession, actor: cs.Actor, title: str, topic: Optional[str] = None,
                      join_rule: str = DEFAULT_JOIN_RULE) -> Conversation:
    """A room hosted here, owned by `actor` (a developer or an agent; session-lead, seq 2201)."""
    if actor.ptype not in ("developer", "agent"):
        raise cs.ChatError(403, "a room is opened by a developer or an agent")
    title = (title or "").strip()
    if not title or len(title) > TITLE_MAX:
        raise cs.ChatError(422, f"a room needs a title of 1 to {TITLE_MAX} characters")
    if join_rule not in JOIN_RULES:
        raise cs.ChatError(422, f"join_rule is one of {', '.join(JOIN_RULES)}")
    owned = int((await db.execute(select(func.count()).select_from(Conversation).where(
        Conversation.kind == "room", Conversation.host_registry.is_(None),
        Conversation.created_by_ptype == actor.ptype,
        Conversation.created_by_id == str(actor.sender_id)))).scalar() or 0)
    if owned >= MAX_ROOMS_PER_OWNER:
        raise cs.ChatError(409, f"you own {owned} rooms here, the most one owner may ({MAX_ROOMS_PER_OWNER})")
    conv = Conversation(kind="room", title=title, topic=((topic or "").strip()[:200] or None), join_rule=join_rule,
                        created_by_ptype=actor.ptype, created_by_id=str(actor.sender_id))
    db.add(conv)
    await db.flush()
    db.add(ConversationParticipant(
        conversation_id=conv.id, ptype=actor.ptype,
        developer_id=actor.developer_id if actor.ptype == "developer" else None,
        agent_did=actor.agent_did if actor.ptype == "agent" else None, role="owner", state="active"))
    await db.commit()
    return conv


# ── seating ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _state_for(rule: str, invited: bool) -> Optional[str]:
    """The seat a join takes under the room's rule: None when the rule refuses it."""
    if invited or rule == "anyone":
        return "active"
    if rule == "request":
        return "pending"
    return None


async def seat_remote(db: AsyncSession, conversation_id: str, participant_key: str, display: Optional[str],
                      peer_identity: str) -> Dict[str, Any]:
    """HOST side of a join carried by the joiner's own registry (POST /api/v1/federation/chat/rooms/join). The calling
    registry must be the participant's home (the binding rule); then the ban list, the per-peer join rate for 'anyone',
    the cap, and the room's rule. An invite already seated (pending, by an operator) is accepted by this join."""
    from agentvault_registry.services import chat_federation as fed
    parsed = fed.parse_remote_key(participant_key or "")
    if not parsed:
        raise cs.ChatError(422, "participant_key must be id@https://their.registry")
    if not await fed.caller_is(db, peer_identity, parsed[1]):
        raise cs.ChatError(403, "the calling registry is not that participant's home registry")
    key = fed.remote_key(parsed[0], parsed[1])
    conv = await _hosted_room(db, conversation_id)
    if await _banned(db, conv.id, key):
        raise cs.ChatError(403, "this room's operators removed that participant for good")
    row = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id, ConversationParticipant.ptype == "remote",
        ConversationParticipant.remote_key == key))).scalars().first()
    invited = row is not None and row.state == "pending" and row.role == "invited"
    if row is not None and row.state == "active":
        return _head(conv, row)
    rule = conv.join_rule or DEFAULT_JOIN_RULE
    state = _state_for(rule, invited)
    if state is None:
        raise cs.ChatError(403, "this room is by invitation: ask one of its members for an invite")
    if rule == "anyone" and not invited and not await fed.fed_rate_ok("room_join_peer", parsed[1]):
        raise cs.ChatError(429, "too many joins from that registry this hour; retry later")
    if row is None and await _seated_count(db, conv.id) >= MAX_MEMBERS:
        raise cs.ChatError(409, f"this room is full ({MAX_MEMBERS} members)")
    if row is None:
        row = ConversationParticipant(conversation_id=conv.id, ptype="remote", remote_key=key, role="member",
                                      state=state)
        db.add(row)
    else:
        row.state, row.role, row.can_post = state, "member", True
    await db.flush()
    if state == "active":
        owner_row, owner = await _owner_of(db, conv)
        await _post_system(db, conv, owner, owner_row, "join", target_name=(display or key)[:120])
    else:
        await db.commit()
    return _head(conv, row)


async def join_local(db: AsyncSession, actor: cs.Actor, conversation_id: str) -> Dict[str, Any]:
    """A principal of THIS registry joins a room hosted here: under 'anyone', or its invite (seated pending as
    'invited'), seated active; under 'request', pending for an operator; refused under 'invited' with no invite."""
    if actor.ptype not in ("developer", "agent"):
        raise cs.ChatError(403, "a developer or an agent joins a room")
    conv = await _hosted_room(db, conversation_id)
    if await _banned(db, conv.id, actor.key):
        raise cs.ChatError(403, "this room's operators removed you for good")
    row = await cs._my_row(db, conv.id, actor)
    if row is not None and row.state == "active":
        return _head(conv, row)
    invited = row is not None and row.state == "pending" and row.role == "invited"
    state = _state_for(conv.join_rule or DEFAULT_JOIN_RULE, invited)
    if state is None:
        raise cs.ChatError(403, "this room is by invitation: ask one of its members for an invite")
    if row is None and await _seated_count(db, conv.id) >= MAX_MEMBERS:
        raise cs.ChatError(409, f"this room is full ({MAX_MEMBERS} members)")
    if row is None:
        row = ConversationParticipant(conversation_id=conv.id, ptype=actor.ptype,
                                      developer_id=actor.developer_id if actor.ptype == "developer" else None,
                                      agent_did=actor.agent_did if actor.ptype == "agent" else None,
                                      role="member", state=state)
        db.add(row)
    else:
        row.state, row.role, row.can_post = state, "member", True
    await db.flush()
    if state == "active":
        owner_row, owner = await _owner_of(db, conv)
        await _post_system(db, conv, owner, owner_row, "join", target_name=actor.display_name or actor.key)
    else:
        await db.commit()
    return _head(conv, row)


async def join_by_address(db: AsyncSession, actor: cs.Actor, address: str) -> Dict[str, Any]:
    """RESIDENT side: one of this registry's principals joins a room by its address. A room hosted here is a local
    join; a room on a peer is asked of its host over federation mTLS (POST /api/v1/federation/chat/rooms/join, which
    seats only the calling registry's own residents), and on its answer this registry keeps a mirror of the room and
    seats the principal as the host said (active, or pending under 'request'). Messages arrive from the join onward."""
    from agentvault_registry.services import chat_federation as fed
    parsed = parse_room_address(address)
    if not parsed:
        raise cs.ChatError(422, "a room's address is room:<id>@https://its.registry")
    room_id, host_origin = parsed
    if host_origin == fed.origin(fed.self_base_url()):
        return {**await join_local(db, actor, room_id), "local": True}
    if not fed.federation_enabled():
        raise cs.ChatError(501, "cross-registry chat is not enabled on this registry")
    if actor.ptype not in ("developer", "agent"):
        raise cs.ChatError(403, "a developer or an agent joins a room")
    await fed.assert_peer_allowed(db, host_origin)
    pid = actor.developer_id if actor.ptype == "developer" else actor.agent_did
    key = fed.remote_key(await fed.local_wire_id(db, actor.ptype, pid), fed.self_base_url())
    target, kwargs, headers = await fed.federation_target(db, host_origin)
    import httpx
    try:
        async with httpx.AsyncClient(**kwargs) as c:
            r = await c.post(f"{target.rstrip('/')}/api/v1/federation/chat/rooms/join", headers=headers,
                             json={"room_ref": room_id, "participant_key": key,
                                   "participant_display": (actor.display_name or "")[:200] or None})
    except Exception as e:  # noqa: BLE001
        raise cs.ChatError(502, f"the room's host registry could not be reached ({type(e).__name__}); you did not join")
    if r.status_code != 200:
        try:
            detail = str((r.json() or {}).get("detail") or "")[:240]
        except ValueError:
            detail = ""
        raise cs.ChatError(r.status_code if 400 <= r.status_code < 500 else 502,
                           detail or f"the room's host answered HTTP {r.status_code}; you did not join")
    head = r.json()
    host = str(head.get("host_registry") or host_origin).rstrip("/")
    conv = (await db.execute(select(Conversation).where(
        Conversation.host_registry == host, Conversation.remote_ref == room_id))).scalars().first()
    if conv is None:
        conv = Conversation(kind="room", title=head.get("title"), topic=head.get("topic"),
                            join_rule=head.get("join_rule"), created_by_ptype="remote",
                            created_by_id=str(head.get("address") or address), host_registry=host, remote_ref=room_id)
        db.add(conv)
        await db.flush()
    state = str(head.get("state") or "pending")
    row = await cs._my_row(db, conv.id, actor)
    if row is None:
        db.add(ConversationParticipant(
            conversation_id=conv.id, ptype=actor.ptype,
            developer_id=actor.developer_id if actor.ptype == "developer" else None,
            agent_did=actor.agent_did if actor.ptype == "agent" else None, role="member", state=state))
    else:
        row.state = state
    await db.commit()
    return {**head, "conversation_id": conv.id, "local": False}


async def _owner_of(db: AsyncSession, conv: Conversation) -> Tuple[ConversationParticipant, cs.Actor]:
    row = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id,
        ConversationParticipant.role == "owner"))).scalars().first()
    if row is None:
        raise cs.ChatError(409, "this room has no owner")
    actor = cs.Actor(row.ptype, developer_id=row.developer_id, agent_did=row.agent_did, display_name="the room")
    return row, actor


def _head(conv: Conversation, row: ConversationParticipant) -> Dict[str, Any]:
    from agentvault_registry.services import chat_federation as fed
    # host_registry: the host's own base URL, the exact string its deliveries carry, so a resident keys its mirror by
    # the same value the deliveries look it up with
    return {"room_ref": conv.id, "address": room_address(conv), "host_registry": fed.self_base_url().rstrip("/"),
            "title": conv.title, "topic": conv.topic,
            "join_rule": conv.join_rule, "state": row.state, "can_post": bool(row.can_post),
            "last_seq": int(conv.last_seq or 0)}


# ── moderation (the host only) ────────────────────────────────────────────────────────────────────────────────────
async def room_action(db: AsyncSession, conversation_id: str, actor: cs.Actor, action: str,
                      target_key: Optional[str] = None, value: Optional[str] = None) -> Dict[str, Any]:
    """One operator act in a room this registry hosts, by its owner or a moderator, on a member of lower rank. Every act
    is a system row each member's copy shows."""
    if action not in ROOM_ACTIONS:
        raise cs.ChatError(422, f"unknown room action {action!r}")
    conv = await _hosted_room(db, conversation_id)
    my_row = await cs._my_row(db, conv.id, actor)
    if my_row is None or my_row.state != "active" or my_row.role not in OPERATOR_ROLES:
        raise cs.ChatError(403, "room operations need the room's owner or a moderator")
    target: Optional[ConversationParticipant] = None
    target_name: Optional[str] = None
    if action == "invite":
        target = await _invite(db, conv, target_key)
        target_name = target_key
    elif action in ("mute", "unmute", "remove", "ban", "accept", "moderator", "unmoderator"):
        if not target_key:
            raise cs.ChatError(422, f"{action} needs a member")
        rows = (await db.execute(select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conv.id))).scalars().all()
        target = next((p for p in rows if _key_of_row(p) == target_key), None)
        if target is None and action != "ban":
            raise cs.ChatError(404, "that member is not in this room")
        if target is not None:
            if target.id == my_row.id:
                raise cs.ChatError(422, "you cannot act on yourself")
            if target.role == "owner" or (target.role == "moderator" and my_row.role != "owner"):
                raise cs.ChatError(403, "an operator acts only on a member of lower rank")
        if action in ("moderator", "unmoderator") and my_row.role != "owner":
            raise cs.ChatError(403, "only the room's owner names its moderators")
        target_name = target_key
    if action == "invite":
        pass                                  # seated pending by _invite; the invitee's own join accepts it
    elif action == "mute":
        target.can_post = False
    elif action == "unmute":
        target.can_post = True
    elif action == "accept":
        if target.state != "pending":
            raise cs.ChatError(409, "that member is not asking to join")
        target.state, target.role = "active", "member"
    elif action in ("remove", "ban"):
        if target is not None:
            target.state, target.can_post = "left", True
        if action == "ban" and not await _banned(db, conv.id, target_key):
            db.add(ChatRoomBan(conversation_id=conv.id, participant_key=target_key, banned_by=actor.key))
    elif action == "moderator":
        target.role = "moderator"
    elif action == "unmoderator":
        target.role = "member"
    elif action == "rule":
        if value not in JOIN_RULES:
            raise cs.ChatError(422, f"join_rule is one of {', '.join(JOIN_RULES)}")
        conv.join_rule = value
    elif action == "topic":
        conv.topic = (value or "").strip()[:200] or None
    elif action == "title":
        t = (value or "").strip()
        if not t or len(t) > TITLE_MAX:
            raise cs.ChatError(422, f"a room needs a title of 1 to {TITLE_MAX} characters")
        conv.title = t
    msg = await _post_system(db, conv, actor, my_row, action, target_name, value)
    return {"ok": True, "action": action, "seq": int(msg.seq), "system_message": cs.serialize_message(msg),
            "target": target_key, "target_state": getattr(target, "state", None),
            "target_can_post": getattr(target, "can_post", None), "join_rule": conv.join_rule}


async def _invite(db: AsyncSession, conv: Conversation, key: Optional[str]) -> ConversationParticipant:
    """Seat an invitee PENDING with role 'invited': a remote address (its home learns it with the next delivery and
    shows it in its Requests lane; its accept is its own registry's join) or a local principal (dev:<id>, agt:<did>)."""
    from agentvault_registry.services import chat_federation as fed
    if not key:
        raise cs.ChatError(422, "invite needs a member: dev:<id>, agt:<did> or id@https://their.registry")
    if await _banned(db, conv.id, key):
        raise cs.ChatError(403, "this room's operators removed that participant for good")
    rows = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id))).scalars().all()
    have = next((p for p in rows if _key_of_row(p) == key), None)
    if have is not None and have.state in SEATED:
        raise cs.ChatError(409, f"that member is already {have.state} here")
    if have is None and await _seated_count(db, conv.id) >= MAX_MEMBERS:
        raise cs.ChatError(409, f"this room is full ({MAX_MEMBERS} members)")
    if have is not None:
        have.state, have.role, have.can_post = "pending", "invited", True
        return have
    # an address on another registry first: a peer's developer with no handle goes by dev:<id>@https://... on the wire
    if "@" not in key and key.startswith("dev:") and key[4:].isdigit():
        row = ConversationParticipant(conversation_id=conv.id, ptype="developer", developer_id=int(key[4:]),
                                      role="invited", state="pending")
    elif "@" not in key and key.startswith("agt:"):
        row = ConversationParticipant(conversation_id=conv.id, ptype="agent", agent_did=key[4:],
                                      role="invited", state="pending")
    else:
        parsed = fed.parse_remote_key(key)
        if not parsed:
            raise cs.ChatError(422, "invite needs a member: dev:<id>, agt:<did> or id@https://their.registry")
        await fed.assert_peer_allowed(db, parsed[1])
        row = ConversationParticipant(conversation_id=conv.id, ptype="remote", remote_key=fed.remote_key(*parsed),
                                      role="invited", state="pending")
    db.add(row)
    await db.flush()
    return row


async def room_info(db: AsyncSession, actor: cs.Actor, conversation_id: str) -> Dict[str, Any]:
    """A room as its members see it: the head (address, rule, title, topic), your own seat, and its members with the
    key each goes by here, their role, state and whether they may post. On the host the list is the room's own; on a
    resident's copy it is what the host's deliveries said (a copy never moderates). Read by any seated member; an
    operator's list includes the pending requests."""
    conv = (await db.execute(select(Conversation).where(Conversation.id == conversation_id))).scalars().first()
    if conv is None or conv.kind != "room":
        raise cs.ChatError(404, "no such room here")
    me = await cs._my_row(db, conv.id, actor)
    if me is None:
        raise cs.ChatError(403, "you are not in this room")
    hosted = conv.host_registry is None
    operator = hosted and me.state == "active" and me.role in OPERATOR_ROLES
    rows = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id))).scalars().all()
    keys = [cs.principal_key(p.ptype, p.developer_id if p.ptype == "developer" else p.agent_did)
            for p in rows if p.ptype != "remote"]
    names = await cs.display_names(db, keys) if keys else {}
    members = []
    for p in rows:
        if p.state == "left" or (p.state == "pending" and not operator and p.id != me.id):
            continue
        k = _key_of_row(p)
        members.append({"key": k, "name": names.get(k) or k, "remote": p.ptype == "remote", "role": p.role,
                        "state": p.state, "can_post": bool(p.can_post)})
    head = {"room_ref": conv.remote_ref or conv.id, "conversation_id": conv.id, "title": conv.title,
            "topic": conv.topic, "join_rule": conv.join_rule, "hosted_here": hosted,
            "address": room_address(conv) if hosted else str(conv.created_by_id or ""),
            "host_registry": None if hosted else conv.host_registry}
    return {**head, "my_state": me.state, "my_role": me.role, "my_can_post": bool(me.can_post),
            "i_moderate": operator, "members": members, "member_count": sum(1 for m in members if m["state"] == "active")}


async def relay_gate(db: AsyncSession, conv: Conversation, part: ConversationParticipant) -> None:
    """The host's checks before a remote member's relayed message takes a seq in a room: seated and active, not muted,
    not banned. (A dm keeps its own checks; this runs for rooms only.)"""
    if conv.kind != "room":
        return
    if await _banned(db, conv.id, str(part.remote_key or "")):
        raise cs.ChatError(403, "this room's operators removed you for good")
    if part.state == "pending":
        raise cs.ChatError(403, "your request to join this room is waiting for its operators")
    if part.state != "active":
        raise cs.ChatError(409, "you are no longer in this room")
    if not bool(part.can_post):
        raise cs.ChatError(403, "a room operator muted you here; you can read, not post")
