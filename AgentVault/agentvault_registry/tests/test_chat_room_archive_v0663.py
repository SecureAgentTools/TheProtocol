"""V0663 (order gwo_daf7fc3c8b3174f6f73c0d8a, session-tester's soak, seq 3229): archive and close a room.

An owner who reaches the cap of 20 rooms had no way out. Archive takes a room out of the lists and out of the cap and keeps its
history readable; nobody posts in it until an operator unarchives it. Close removes a room nobody has spoken in. Both are for the
room's owner or a moderator, on a room this registry hosts. Over real (SQLite) rows, the host test's harness (the system row an act
posts is recorded there; the real write is the federation suite's). The lists and the unread count are PostgreSQL statements: pinned
here as statements.
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



CAP = 3


def _mk(db, title="room"):
    return run(rooms.create_room(db, OWNER, title, None, "anyone"))


def _act(db, conv, action, who=OWNER, **kw):
    return run(rooms.room_action(db, conv.id, who, action, kw.get("member"), kw.get("value")))


def _reload(db, conv):
    db.sync.expire_all()
    return db.sync.get(models.Conversation, conv.id)


def test_the_cap_counts_only_open_rooms_so_an_archive_is_a_way_out(db, monkeypatch):
    monkeypatch.setattr(rooms, "MAX_ROOMS_PER_OWNER", CAP)
    made = [_mk(db, f"r{i}") for i in range(CAP)]
    with pytest.raises(cs.ChatError) as e:
        _mk(db, "one too many")
    assert e.value.status_code == 409 and "open rooms" in e.value.detail and "archive" in e.value.detail
    assert run(rooms.open_rooms_owned(db, "developer", "1")) == CAP
    out = _act(db, made[0], "archive")
    assert out["archived"] is True and ("archive", None, None) in db.posted
    assert run(rooms.open_rooms_owned(db, "developer", "1")) == CAP - 1
    assert _mk(db, "now it fits").kind == "room"                     # the archived room left the cap
    assert _reload(db, made[0]).archived_at is not None and _reload(db, made[0]).archived_by == "dev:1"


def test_only_an_operator_archives_and_a_second_archive_or_unarchive_is_a_conflict(db):
    conv = _mk(db)
    with pytest.raises(cs.ChatError) as e:                           # a stranger holds no seat
        _act(db, conv, "archive", who=LOCAL)
    assert e.value.status_code == 403
    _act(db, conv, "archive")
    with pytest.raises(cs.ChatError) as e:
        _act(db, conv, "archive")
    assert e.value.status_code == 409
    other = _mk(db, "open one")
    with pytest.raises(cs.ChatError) as e:
        _act(db, other, "unarchive")
    assert e.value.status_code == 409


def test_unarchive_puts_the_room_back_into_the_cap_and_is_refused_over_it(db, monkeypatch):
    monkeypatch.setattr(rooms, "MAX_ROOMS_PER_OWNER", 2)
    a, b = _mk(db, "a"), _mk(db, "b")
    _act(db, a, "archive")
    c = _mk(db, "c")                                                 # the slot a left
    with pytest.raises(cs.ChatError) as e:
        _act(db, a, "unarchive")                                     # the owner is at 2 open rooms again
    assert e.value.status_code == 409 and "open rooms" in e.value.detail
    _act(db, c, "archive")
    assert _act(db, a, "unarchive")["archived"] is False
    assert _reload(db, a).archived_at is None
    assert b.id != c.id


def test_a_member_cannot_archive_a_moderator_may(db):
    conv = _mk(db)
    run(rooms.seat_local_for_test(db, conv, MOD) if hasattr(rooms, "seat_local_for_test") else asyncio.sleep(0))
    row = models.ConversationParticipant(conversation_id=conv.id, ptype="developer", developer_id=2, role="moderator", state="active")
    plain = models.ConversationParticipant(conversation_id=conv.id, ptype="developer", developer_id=3, role="member", state="active")
    db.sync.add_all([row, plain]); db.sync.commit()
    with pytest.raises(cs.ChatError) as e:
        _act(db, conv, "archive", who=LOCAL)
    assert e.value.status_code == 403
    assert _act(db, conv, "archive", who=MOD)["archived"] is True


def test_an_archived_room_is_read_not_posted_in():
    conv = models.Conversation(id="r", kind="room", created_by_ptype="developer", created_by_id="1")
    import datetime
    conv.archived_at = datetime.datetime.now(datetime.timezone.utc)
    for kind in ("text", "card"):
        with pytest.raises(cs.ChatError) as e:
            run(cs.insert_message(None, conv, object(), OWNER, kind, "hello", None, "ref0000000001"))
        assert e.value.status_code == 409 and "archived" in e.value.detail


def test_closing_removes_an_empty_room_and_refuses_one_with_messages(db):
    empty, spoken = _mk(db, "empty"), _mk(db, "spoken")
    db.sync.add(models.ChatMessage(id="s1", conversation_id=empty.id, seq=1, sender_ptype="developer", sender_id="1",
                                   kind="system", body="room.invite", client_ref="sys00000001"))   # an act's own row is not speech
    db.sync.add(models.ChatMessage(id="t1", conversation_id=spoken.id, seq=1, sender_ptype="developer", sender_id="1",
                                   kind="text", body="hi", client_ref="txt00000001"))
    db.sync.commit()
    with pytest.raises(cs.ChatError) as e:
        run(rooms.close_room(db, spoken.id, OWNER))
    assert e.value.status_code == 409 and "archive it instead" in e.value.detail
    assert _reload(db, spoken) is not None
    assert run(rooms.close_room(db, empty.id, OWNER)) == {"ok": True, "closed": empty.id}
    assert db.sync.get(models.Conversation, empty.id) is None
    with pytest.raises(cs.ChatError) as e:                           # not an operator
        run(rooms.close_room(db, spoken.id, LOCAL))
    assert e.value.status_code == 403
    with pytest.raises(cs.ChatError) as e:                           # gone
        run(rooms.close_room(db, empty.id, OWNER))
    assert e.value.status_code == 404


def test_an_open_room_still_works_as_before(db, monkeypatch):
    async def names(db_, keys):                 # the names read is PostgreSQL's (= ANY(...))
        return {k: k for k in keys}
    monkeypatch.setattr(cs, "display_names", names)
    conv = _mk(db)
    assert conv.archived_at is None
    info = run(rooms.room_info(db, OWNER, conv.id))
    assert info["archived"] is False
    _act(db, conv, "archive")
    assert run(rooms.room_info(db, OWNER, conv.id))["archived"] is True       # read still answers: the history stays


def test_the_lists_and_the_unread_count_know_archived_rooms():
    import inspect
    lst = inspect.getsource(cs.list_conversations)
    assert 'archive_clause = "AND c.archived_at IS NOT NULL" if state == "archived" else "AND c.archived_at IS NULL"' in lst
    assert "{cursor_clause} {archive_clause}" in lst
    assert "c.archived_at IS NULL" in inspect.getsource(cs.unread_total)


def test_the_routes_take_the_actions_and_the_lane():
    import re
    from agentvault_registry.routers import chat as R
    assert re.match(R.RoomMemberAct.model_fields["action"].metadata[0].pattern, "archive")
    assert re.match(R.RoomMemberAct.model_fields["action"].metadata[0].pattern, "unarchive")
    paths = {getattr(r, "path", "") for r in R.router.routes}
    assert "/api/v1/chat/rooms/{conversation_id}/close" in paths or any(p.endswith("/rooms/{conversation_id}/close") for p in paths)
