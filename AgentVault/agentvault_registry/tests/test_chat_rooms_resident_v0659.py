"""V0659 (f): cross-frame rooms, the RESIDENT's half (services/chat_federation.receive_delivery, apply_remote_state;
services/chat_rooms.join_by_address). New in V0659: red on V0657's cut, which refused every kind but dm.

Pinned here, over real (SQLite) rows:
  * a room's delivery is mirrored as a room, and our principal is seated as the HOST says: pending for an invite,
    active once accepted, left once removed, on every delivery (a dm keeps its own rule: a developer active at once);
  * an org room's delivery is still refused (its roster is one registry's);
  * on the host, a resident's accept of a room invite goes through the room's own checks (a ban holds), and a
    household join does not apply to a room.
"""
from __future__ import annotations

import asyncio
import datetime as dt

import pytest

from agentvault_registry import models
from agentvault_registry.services import chat_federation as fed
from agentvault_registry.services import chat_rooms as rooms
from agentvault_registry.services import chat_service as cs
from tests._sqlite_db import sqlite_db

A, B = "https://a.example", "https://b.example"
OURS = f"dev:5@{B}"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def resident(monkeypatch):
    d = sqlite_db(models.Developer, models.Agent, models.Conversation, models.ConversationParticipant,
                  models.ChatMessage, models.ChatBlock)
    d.sync.add(models.Developer(id=5, name="ada", email="ada@example.org", hashed_password="x"))
    d.sync.commit()
    # the database's clock, as tests/test_chat_approvals_waiting does (SQLite has no now())
    d.sync.connection().connection.dbapi_connection.create_function(
        "now", 0, lambda: dt.datetime(2026, 11, 7, 22, 0).isoformat(sep=" "))

    async def _caller_is(db_, peer, origin):
        return peer == origin

    async def _rate_ok(kind, *parts):
        return True

    async def _no(*a, **k):
        return False
    async def _peer(db_, base):
        return base

    async def _peers(db_):
        return {"a": A}
    monkeypatch.setattr(fed, "self_base_url", lambda: B)
    monkeypatch.setattr(fed, "federation_enabled", lambda: True)
    monkeypatch.setattr(fed, "assert_peer_allowed", _peer)
    monkeypatch.setattr(fed, "peer_base_urls", _peers)
    monkeypatch.setattr(fed, "caller_is", _caller_is)
    monkeypatch.setattr(fed, "fed_rate_ok", _rate_ok)
    monkeypatch.setattr(fed, "_we_relayed", _no)
    monkeypatch.setattr(cs, "deliver", lambda *a, **k: None)
    monkeypatch.setattr(cs, "spawn", lambda coro, what=None: coro.close())
    return d


def envelope(kind, our_state, seq, body="hello", others=None):
    return {
        "v": 1, "host_registry": A,
        "conversation": {"id": "room-1", "kind": kind, "title": "Cross-frame room",
                         "participants": [{"ptype": "remote", "key": f"dev:1@{A}", "state": "active"},
                                          {"ptype": "remote", "key": OURS, "state": our_state}] + (others or [])},
        "message": {"id": f"m{seq}", "seq": seq, "kind": "text", "body": body, "card": None,
                    "client_ref": f"ref-{seq}-0123456789", "sender": {"id": "dev:1", "registry": A, "display": "owner"},
                    "created_at": dt.datetime(2026, 11, 7, 22, 0, tzinfo=dt.timezone.utc).isoformat()},
    }


def _ours(d):
    conv = d.sync.query(models.Conversation).filter_by(host_registry=A, remote_ref="room-1").one()
    row = d.sync.query(models.ConversationParticipant).filter_by(conversation_id=conv.id, developer_id=5).one()
    d.sync.expire_all()
    return conv, row


def test_a_rooms_delivery_mirrors_a_room_and_seats_us_as_the_host_says(resident):
    run(fed.receive_delivery(resident, envelope("room", "pending", 1), A))
    conv, row = _ours(resident)
    assert conv.kind == "room" and row.state == "pending"          # an invite waits in the Requests lane
    run(fed.receive_delivery(resident, envelope("room", "active", 2), A))
    assert _ours(resident)[1].state == "active"                    # the invite accepted, by the host's word
    run(fed.receive_delivery(resident, envelope("room", "left", 3), A))
    assert _ours(resident)[1].state == "left"                      # removed


def test_a_dm_keeps_its_own_rule(resident):
    env = envelope("dm", "pending", 1)
    run(fed.receive_delivery(resident, env, A))
    conv = resident.sync.query(models.Conversation).filter_by(remote_ref="room-1").one()
    row = resident.sync.query(models.ConversationParticipant).filter_by(conversation_id=conv.id, developer_id=5).one()
    assert conv.kind == "dm" and row.state == "active"


def test_an_org_rooms_delivery_is_still_refused(resident):
    with pytest.raises(cs.ChatError) as e:
        run(fed.receive_delivery(resident, envelope("org", "active", 1), A))
    assert e.value.status_code == 422


# ── the host: an accept is the room's to give ─────────────────────────────────────────────────────────────────────
@pytest.fixture()
def host(monkeypatch):
    d = sqlite_db(models.Developer, models.Conversation, models.ConversationParticipant, models.ChatRoomBan)
    d.sync.add(models.Developer(id=1, name="owner", email="o@example.org", hashed_password="x"))
    d.sync.commit()

    async def _caller_is(db_, peer, origin):
        return peer == origin

    async def _ok(*a, **k):
        return True

    async def _post(db_, *a, **k):
        await db_.commit()
        return type("M", (), {"seq": 1})()

    async def _peer(db_, base):
        return base
    monkeypatch.setattr(fed, "self_base_url", lambda: A)
    monkeypatch.setattr(fed, "federation_enabled", lambda: True)
    monkeypatch.setattr(fed, "caller_is", _caller_is)
    monkeypatch.setattr(fed, "fed_rate_ok", _ok)
    monkeypatch.setattr(fed, "assert_peer_allowed", _peer)
    monkeypatch.setattr(rooms, "_post_system", _post)
    monkeypatch.setattr(cs, "serialize_message", lambda m: {"seq": m.seq})
    return d


OWNER = cs.Actor("developer", developer_id=1, display_name="owner")


def test_an_invite_accepted_from_its_home_seats_the_member(host):
    conv = run(rooms.create_room(host, OWNER, "r", None, "invited"))
    run(rooms.room_action(host, conv.id, OWNER, "invite", OURS))
    out = run(fed.apply_remote_state(host, conv.id, OURS, "active", B))
    assert out["state"] == "active" and out["room"]["host_registry"] == A


def test_an_accept_cannot_seat_a_banned_member(host):
    conv = run(rooms.create_room(host, OWNER, "r", None, "anyone"))
    run(rooms.seat_remote(host, conv.id, OURS, None, B))
    run(rooms.room_action(host, conv.id, OWNER, "ban", OURS))
    with pytest.raises(cs.ChatError) as e:
        run(fed.apply_remote_state(host, conv.id, OURS, "active", B))
    assert e.value.status_code == 403


def test_a_household_join_does_not_apply_to_a_room(host):
    conv = run(rooms.create_room(host, OWNER, "r", None, "anyone"))
    with pytest.raises(cs.ChatError) as e:
        run(fed.apply_remote_state(host, conv.id, OURS, "join", B))
    assert e.value.status_code == 422


def test_a_peers_developer_without_a_handle_is_invited_as_remote(host):
    conv = run(rooms.create_room(host, OWNER, "r", None, "invited"))
    run(rooms.room_action(host, conv.id, OWNER, "invite", OURS))                # dev:5@https://b.example
    row = host.sync.query(models.ConversationParticipant).filter_by(conversation_id=conv.id, remote_key=OURS).one()
    assert row.ptype == "remote" and row.state == "pending" and row.developer_id is None


def test_an_address_names_its_room_and_its_host():
    assert rooms.parse_room_address(f"room:abc@{A}") == ("abc", A)
    assert rooms.parse_room_address("room:abc") is None
