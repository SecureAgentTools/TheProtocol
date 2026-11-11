"""V0659 (f): cross-frame rooms, the HOST's half (services/chat_rooms.py; the design:
sessionlogs2026/DESIGN_2026-11-07_XFRAME_ROOMS.md, approved at room seq 2201). New in V0659: red on V0657's cut, which
has no room kind.

Pinned here, over real (SQLite) rows:
  * the join rule: 'anyone' seats a joiner at once, 'request' seats it pending for an operator, 'invited' refuses a
    joiner with no invite and an invite seats it;
  * THE BINDING RULE (session-lead, seq 2201): a registry joins only its own residents; a peer naming a key on
    another registry is refused, on the federation route and in the service alike;
  * a ban outlives the seat: a banned outsider cannot rejoin under 'anyone';
  * the per-peer join rate for 'anyone'; the member cap; the owner's room cap;
  * moderation at the host: only the owner or a moderator, only on a lower rank; a muted, pending, removed or banned
    member's relayed message is refused before it takes a seq.
The system rows each act posts go through chat_service.insert_message, recorded here (the real write is the
federation suite's legs on the sandbox pair).
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI

import ast
import pathlib

from agentvault_registry import models
from agentvault_registry.services import chat_federation as fed
from agentvault_registry.services import chat_rooms as rooms
from agentvault_registry.services import chat_service as cs
from tests._sqlite_db import sqlite_db

# the real rate gate, kept before the fixture stubs it (V0659 (f) on the sandbox: the stub hid an undeclared limit)
REAL_FED_RATE_OK = fed.fed_rate_ok
HOST = "https://a.example"
B, C = "https://b.example", "https://c.example"
OWNER = cs.Actor("developer", developer_id=1, display_name="owner")
MOD = cs.Actor("developer", developer_id=2, display_name="moderator")
LOCAL = cs.Actor("developer", developer_id=3, display_name="local member")
OUTSIDER = "did:theprotocol:b.example:0000aaaa@https://b.example"


@pytest.fixture()
def db(monkeypatch):
    d = sqlite_db(models.Developer, models.Conversation, models.ConversationParticipant, models.ChatRoomBan,
                  models.ChatMessage, models.Agent)
    for i in (1, 2, 3):
        d.sync.add(models.Developer(id=i, name=f"d{i}", email=f"d{i}@example.org", hashed_password="x"))
    d.sync.commit()
    posted = []

    async def _post(db_, conv, actor, actor_row, action, target_name=None, value=None):
        await db_.commit()
        posted.append((action, target_name, value))
        return type("M", (), {"seq": len(posted)})()

    async def _caller_is(db_, peer, origin):          # the transport proves the peer: here its name IS its origin
        return peer == origin

    async def _rate_ok(kind, *parts):
        return d.rate_ok

    async def _peer_ok(db_, base):
        return base
    monkeypatch.setattr(rooms, "_post_system", _post)
    monkeypatch.setattr(cs, "serialize_message", lambda m: {"seq": m.seq})
    monkeypatch.setattr(fed, "caller_is", _caller_is)
    monkeypatch.setattr(fed, "fed_rate_ok", _rate_ok)
    monkeypatch.setattr(fed, "assert_peer_allowed", _peer_ok)
    monkeypatch.setattr(fed, "self_base_url", lambda: HOST)
    d.rate_ok = True
    d.posted = posted
    return d


def run(coro):
    return asyncio.run(coro)


def _room(db, rule):
    return run(rooms.create_room(db, OWNER, "Cross-frame room", "topic", rule))


def _row(db, conv, key):
    rows = db.sync.query(models.ConversationParticipant).filter_by(conversation_id=conv.id).all()
    return next((p for p in rows if rooms._key_of_row(p) == key), None)


# ── opening ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_room_is_hosted_here_owned_by_its_maker_with_an_address(db):
    conv = _room(db, "anyone")
    assert conv.kind == "room" and conv.join_rule == "anyone" and conv.host_registry is None
    assert _row(db, conv, "dev:1").role == "owner"
    assert rooms.room_address(conv) == f"room:{conv.id}@{HOST}"
    assert rooms.parse_room_address(rooms.room_address(conv)) == (conv.id, HOST)
    assert rooms.parse_room_address("dm:x@https://a.example") is None


def test_an_unknown_rule_and_the_owners_room_cap_are_refused(db, monkeypatch):
    with pytest.raises(cs.ChatError) as e:
        run(rooms.create_room(db, OWNER, "x", None, "everyone"))
    assert e.value.status_code == 422
    monkeypatch.setattr(rooms, "MAX_ROOMS_PER_OWNER", 1)
    _room(db, "invited")
    with pytest.raises(cs.ChatError) as e:
        _room(db, "invited")
    assert e.value.status_code == 409


# ── the join rule, from another registry ──────────────────────────────────────────────────────────────────────────
def test_anyone_seats_an_outsider_at_once_and_the_room_says_so(db):
    conv = _room(db, "anyone")
    head = run(rooms.seat_remote(db, conv.id, OUTSIDER, "Ada on B", B))
    assert head["state"] == "active" and head["address"] == rooms.room_address(conv)
    assert _row(db, conv, OUTSIDER).ptype == "remote"
    assert db.posted[-1][:2] == ("join", "Ada on B")


def test_request_seats_pending_until_an_operator_accepts(db):
    conv = _room(db, "request")
    assert run(rooms.seat_remote(db, conv.id, OUTSIDER, None, B))["state"] == "pending"
    run(rooms.room_action(db, conv.id, OWNER, "accept", OUTSIDER))
    assert _row(db, conv, OUTSIDER).state == "active"


def test_invited_refuses_a_stranger_and_an_invite_seats_it(db):
    conv = _room(db, "invited")
    with pytest.raises(cs.ChatError) as e:
        run(rooms.seat_remote(db, conv.id, OUTSIDER, None, B))
    assert e.value.status_code == 403 and "invitation" in e.value.detail
    run(rooms.room_action(db, conv.id, OWNER, "invite", OUTSIDER))
    assert _row(db, conv, OUTSIDER).state == "pending"
    assert run(rooms.seat_remote(db, conv.id, OUTSIDER, None, B))["state"] == "active"


def test_a_local_principal_joins_under_the_same_rule(db):
    conv = _room(db, "invited")
    with pytest.raises(cs.ChatError):
        run(rooms.join_local(db, LOCAL, conv.id))
    run(rooms.room_action(db, conv.id, OWNER, "invite", "dev:3"))
    assert run(rooms.join_local(db, LOCAL, conv.id))["state"] == "active"


# ── the binding rule ──────────────────────────────────────────────────────────────────────────────────────────────
def test_a_registry_joins_only_its_own_residents(db):
    conv = _room(db, "anyone")
    foreign = "did:theprotocol:c.example:0000cccc@https://c.example"
    with pytest.raises(cs.ChatError) as e:
        run(rooms.seat_remote(db, conv.id, foreign, None, B))      # B names a key on C
    assert e.value.status_code == 403 and "home registry" in e.value.detail
    assert _row(db, conv, foreign) is None


def test_the_federation_route_binds_the_key_to_the_calling_peer(db, monkeypatch):
    from agentvault_registry.database import get_db
    from agentvault_registry.routers import chat_federation as route
    conv = _room(db, "anyone")
    monkeypatch.setattr(fed, "federation_enabled", lambda: True)
    app = FastAPI()
    app.include_router(route.router)
    who = {"peer": B}

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[route.require_peer_registry_identity] = lambda: who["peer"]

    async def post(key, peer):
        who["peer"] = peer
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.post("/api/v1/federation/chat/rooms/join",
                                json={"room_ref": conv.id, "participant_key": key})
    r = run(post("did:theprotocol:c.example:0000cccc@https://c.example", B))
    assert r.status_code == 403, r.text
    r = run(post(OUTSIDER, B))
    assert r.status_code == 200 and r.json()["state"] == "active", r.text


# ── ban, rate, cap ────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_ban_outlives_the_seat(db):
    conv = _room(db, "anyone")
    run(rooms.seat_remote(db, conv.id, OUTSIDER, None, B))
    run(rooms.room_action(db, conv.id, OWNER, "ban", OUTSIDER))
    assert _row(db, conv, OUTSIDER).state == "left"
    with pytest.raises(cs.ChatError) as e:
        run(rooms.seat_remote(db, conv.id, OUTSIDER, None, B))
    assert e.value.status_code == 403


def test_the_per_peer_join_rate_holds_for_anyone(db):
    conv = _room(db, "anyone")
    db.rate_ok = False
    with pytest.raises(cs.ChatError) as e:
        run(rooms.seat_remote(db, conv.id, OUTSIDER, None, B))
    assert e.value.status_code == 429


def test_the_member_cap(db, monkeypatch):
    conv = _room(db, "anyone")
    monkeypatch.setattr(rooms, "MAX_MEMBERS", 1)                   # the owner fills it
    with pytest.raises(cs.ChatError) as e:
        run(rooms.seat_remote(db, conv.id, OUTSIDER, None, B))
    assert e.value.status_code == 409


# ── moderation at the host ────────────────────────────────────────────────────────────────────────────────────────
def test_only_an_operator_moderates_and_only_down_the_ranks(db):
    conv = _room(db, "anyone")
    run(rooms.join_local(db, MOD, conv.id))
    run(rooms.join_local(db, LOCAL, conv.id))
    run(rooms.seat_remote(db, conv.id, OUTSIDER, None, B))
    with pytest.raises(cs.ChatError) as e:
        run(rooms.room_action(db, conv.id, LOCAL, "mute", OUTSIDER))  # a plain member
    assert e.value.status_code == 403
    with pytest.raises(cs.ChatError):
        run(rooms.room_action(db, conv.id, MOD, "moderator", "dev:3"))  # only the owner names moderators
    run(rooms.room_action(db, conv.id, OWNER, "moderator", "dev:2"))
    run(rooms.room_action(db, conv.id, MOD, "mute", OUTSIDER))
    assert _row(db, conv, OUTSIDER).can_post is False
    with pytest.raises(cs.ChatError) as e:
        run(rooms.room_action(db, conv.id, MOD, "remove", "dev:1"))   # never the owner
    assert e.value.status_code == 403


@pytest.mark.parametrize("make, code", [
    (lambda p: setattr(p, "can_post", False), 403),       # muted
    (lambda p: setattr(p, "state", "pending"), 403),      # asked, not yet accepted
    (lambda p: setattr(p, "state", "left"), 409),         # removed
])
def test_a_relayed_message_from_a_member_who_may_not_speak_is_refused(db, make, code):
    conv = _room(db, "anyone")
    run(rooms.seat_remote(db, conv.id, OUTSIDER, None, B))
    part = _row(db, conv, OUTSIDER)
    make(part)
    with pytest.raises(cs.ChatError) as e:
        run(rooms.relay_gate(db, conv, part))
    assert e.value.status_code == code


def test_a_banned_members_relay_is_refused_and_a_dm_is_untouched(db):
    conv = _room(db, "anyone")
    run(rooms.seat_remote(db, conv.id, OUTSIDER, None, B))
    run(rooms.room_action(db, conv.id, OWNER, "ban", OUTSIDER))
    with pytest.raises(cs.ChatError) as e:
        run(rooms.relay_gate(db, conv, _row(db, conv, OUTSIDER)))
    assert e.value.status_code == 403
    dm = models.Conversation(kind="dm", created_by_ptype="developer", created_by_id="1")
    run(rooms.relay_gate(db, dm, models.ConversationParticipant(state="left", can_post=False)))   # no room: no gate


def test_a_room_mirror_is_a_room():
    import inspect
    src = inspect.getsource(fed.receive_delivery)
    assert 'kind="room" if c_in.get("kind") == "room" else "dm"' in src


# ── the room as its members see it ────────────────────────────────────────────────────────────────────────────────
def test_the_members_list_shows_requests_to_operators_only(db, monkeypatch):
    async def _names(db_, keys):
        return {k: f"name of {k}" for k in keys}
    monkeypatch.setattr(cs, "display_names", _names)
    conv = _room(db, "request")
    run(rooms.join_local(db, LOCAL, conv.id))                       # pending
    run(rooms.room_action(db, conv.id, OWNER, "accept", "dev:3"))   # active
    run(rooms.seat_remote(db, conv.id, OUTSIDER, None, B))          # pending
    owner_view = run(rooms.room_info(db, OWNER, conv.id))
    assert owner_view["i_moderate"] and owner_view["hosted_here"]
    assert {(m["key"], m["state"]) for m in owner_view["members"]} == {
        ("dev:1", "active"), ("dev:3", "active"), (OUTSIDER, "pending")}
    member_view = run(rooms.room_info(db, LOCAL, conv.id))
    assert not member_view["i_moderate"]
    assert OUTSIDER not in {m["key"] for m in member_view["members"]}   # a request is the operators' business
    run(rooms.room_action(db, conv.id, OWNER, "remove", "dev:3"))
    assert "dev:3" not in {m["key"] for m in run(rooms.room_info(db, OWNER, conv.id))["members"]}
    with pytest.raises(cs.ChatError) as e:
        run(rooms.room_info(db, cs.Actor("developer", developer_id=2), conv.id))   # never seated
    assert e.value.status_code == 403


# ── the thread read ──────────────────────────────────────────────────────────────────────────────────────────────
def test_the_thread_read_gives_a_room_its_header_and_no_counterparty(db):
    """The console's thread header and composer read the page's room block: a cross-frame room carries its title, mode,
    topic, member count and the reader's can_post, belongs to no organization, and never turns on the org room's
    operator menu (its moderation is the room panel's). Without the block the header read '…' for good."""
    conv = _room(db, "anyone")
    page = run(cs.list_messages(db, conv.id, OWNER))
    r = page["room"]
    assert page["kind"] == "room" and page["counterparty"] is None
    assert r["title"] == "Cross-frame room" and r["topic"] == "topic" and r["xframe"] is True
    assert r["org_id"] is None and r["org"] is None and r["my_is_operator"] is False
    assert r["my_can_post"] is True and r["member_count"] == 1
    # a room's members are never a counterparty, on the list row as on the thread (like an org room)
    seat = _row(db, conv, "dev:1")
    assert cs.pick_counterparty("room", [seat], set(), "dev:9") == (None, False)


# ── the rate limit is a declared one (V0659 (f) on the sandbox, session-code's seq 2500) ───────────────────────────────
def test_every_fed_rate_kind_in_the_code_is_declared():
    """The anyone-room join called fed_rate_ok("room_join_peer", ...) and FED_RL never declared it: KeyError, the host
    answered 500 (502 through the joiner's registry) for every uninvited joiner. Every literal kind any call names is a
    key of FED_RL."""
    src = pathlib.Path(fed.__file__).resolve().parent.parent
    named = {}
    for f in src.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) == "fed_rate_ok"
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                named.setdefault(node.args[0].value, f.name)
    assert "room_join_peer" in named, "the census found no call it should (the scan itself is broken)"
    missing = {k: v for k, v in named.items() if k not in fed.FED_RL}
    assert missing == {}, f"fed_rate_ok kinds no FED_RL declares: {missing}"


def test_an_outsider_joins_an_anyone_room_through_the_real_rate_gate(db, monkeypatch):
    """No stub between the join and the limit: the real fed_rate_ok (counting in this worker, no Redis here) seats an
    outsider, and refuses the peer once its per-minute joins are spent."""
    monkeypatch.setattr(fed, "fed_rate_ok", REAL_FED_RATE_OK)
    conv = _room(db, "anyone")
    head = run(rooms.seat_remote(db, conv.id, OUTSIDER, "Ada on B", B))
    assert head["state"] == "active"
    limit = fed.FED_RL["room_join_peer"][0]
    for i in range(limit - 1):
        run(rooms.seat_remote(db, conv.id, f"dev:{100 + i}@{B}", None, B))
    with pytest.raises(cs.ChatError) as e:
        run(rooms.seat_remote(db, conv.id, f"dev:999@{B}", None, B))
    assert e.value.status_code == 429
