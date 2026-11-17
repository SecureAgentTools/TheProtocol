"""V0663 recut (order gwo_c281b2b0f53bd610bde557e7, the pair proof's finding, room seq 3767): an archived room takes nothing from
another frame.

Archiving a room said "it can be read, not posted in", and only the host's own insert_message kept to it. A member on another frame
posts through the host's relay-send (relay_gate, then insert_remote_message) and a mirror's post goes to _relay_resident_send:
neither read archived_at, so the outsider's post landed. The same door stood open for the cross-frame changes (an edit, a take-back,
a reaction, a pin): they enter at the same gate. The host decides (relay_gate); the mirror refuses first, from its own copy.
"""
from __future__ import annotations

import asyncio
import datetime

import pytest

from agentvault_registry import models
from agentvault_registry.routers import chat as chat_router
from agentvault_registry.services import chat_federation as fed
from agentvault_registry.services import chat_fed_events as fev
from agentvault_registry.services import chat_rooms as rooms
from agentvault_registry.services import chat_service as cs
from tests.test_chat_fed_events_v0663 import (  # noqa: F401  (db is the fixture the helpers need)
    B, C, HOST, MEMBER, MOD, ROOM, _client, _host_room, _mirror, _Resp, db)

POST_SENTENCE = "this room is archived: it can be read, not posted in"
CHANGE_SENTENCE = "this room is archived: it can be read, not changed"
NOW = datetime.datetime.now(datetime.timezone.utc)


def run(coro):
    return asyncio.run(coro)


def _archive(db, conv):
    conv.archived_at, conv.archived_by = NOW, "dev:1"
    db.sync.commit()


def _unarchive(db, conv):
    conv.archived_at, conv.archived_by = None, None
    db.sync.commit()


def _part(db, key):
    return db.sync.query(models.ConversationParticipant).filter_by(conversation_id=ROOM, remote_key=key).one()


# ── HOST: the relayed post ────────────────────────────────────────────────────────────────────────────────────────
def test_the_host_refuses_a_relayed_post_into_an_archived_room_and_takes_it_again_after_unarchive(db):
    conv = _host_room(db)
    part = _part(db, MEMBER)
    run(rooms.relay_gate(db, conv, part))                                       # open: the gate lets the member through
    _archive(db, conv)
    with pytest.raises(cs.ChatError) as e:
        run(rooms.relay_gate(db, conv, part))
    assert e.value.status_code == 409 and e.value.detail == POST_SENTENCE
    _unarchive(db, conv)
    run(rooms.relay_gate(db, conv, part))                                       # unarchive restores posting


def test_insert_remote_message_refuses_a_non_system_row_in_an_archived_room_and_a_system_row_still_passes(db):
    conv = _host_room(db)
    part = _part(db, MEMBER)
    db.sync.connection().connection.driver_connection.create_function(      # the seq statement is PostgreSQL's now()
        "now", 0, lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"))
    _archive(db, conv)
    for kind in ("text", "card"):
        with pytest.raises(cs.ChatError) as e:
            run(cs.insert_remote_message(db, conv, part, MEMBER, "b member", kind, "late", None, "ref-late-0001"))
        assert e.value.status_code == 409 and e.value.detail == POST_SENTENCE
    n_before = db.sync.query(models.ChatMessage).filter_by(conversation_id=ROOM).count()
    assert n_before == 2                                                         # nothing was stored
    # the host's own system row (the archive's notice, a join, an unarchive) is not a member's post
    msg, dup = run(cs.insert_remote_message(db, conv, part, MEMBER, "b member", "system", "room.unarchive", None,
                                            "ref-sys-0001", system_row=True))
    assert not dup and msg.kind == "system"
    _unarchive(db, conv)
    msg, dup = run(cs.insert_remote_message(db, conv, part, MEMBER, "b member", "text", "back again", None, "ref-ok-00001"))
    assert not dup and msg.body == "back again"


# ── HOST: the relayed changes (edit, take-back, reaction, pin) ────────────────────────────────────────────────────
def _req(etype, actor, **kw):
    return {"conversation_ref": ROOM, "actor_key": actor, "actor_display": "x", "type": etype, "message_seq": 1, **kw}


@pytest.mark.parametrize("etype,actor,extra", [
    ("edit", MEMBER, {"body": "changed"}),
    ("delete", MEMBER, {}),
    ("reaction", MEMBER, {"word": "ack", "on": True}),
    ("pin", MOD, {"on": True}),
])
def test_the_host_refuses_every_relayed_change_in_an_archived_room_and_takes_it_after_unarchive(db, etype, actor, extra):
    conv = _host_room(db)
    peer = actor.rpartition("@")[2]
    _archive(db, conv)
    with pytest.raises(cs.ChatError) as e:
        run(fev.host_apply_relayed(db, _req(etype, actor, **extra), peer))
    assert e.value.status_code == 409 and e.value.detail == CHANGE_SENTENCE
    m = db.sync.get(models.ChatMessage, "m1")
    db.sync.refresh(m)
    assert m.body == "hello from b" and m.deleted_at is None                      # nothing changed
    assert db.sync.query(models.ChatReaction).count() == 0 and db.sync.query(models.ChatPin).count() == 0
    _unarchive(db, conv)
    out = run(fev.host_apply_relayed(db, _req(etype, actor, **extra), peer))
    assert out["changed"] is True


def test_a_take_back_of_a_pin_is_refused_in_an_archived_room_too(db):
    conv = _host_room(db)
    run(fev.host_apply_relayed(db, _req("pin", MOD, on=True), C))
    _archive(db, conv)
    with pytest.raises(cs.ChatError) as e:
        run(fev.host_apply_relayed(db, _req("pin", MOD, on=False), C))
    assert e.value.status_code == 409 and e.value.detail == CHANGE_SENTENCE
    assert db.sync.query(models.ChatPin).count() == 1


# ── MIRROR: refuses first, from its own copy ──────────────────────────────────────────────────────────────────────
def test_a_mirror_refuses_a_residents_post_into_an_archived_room_before_any_relay(db, monkeypatch):
    mir = _mirror(db)
    _archive(db, mir)
    sent = []

    async def relay_to_host(*a, **k):
        sent.append(a)
        return {"seq": 3}
    monkeypatch.setattr(fed, "relay_to_host", relay_to_host)
    actor = cs.Actor("developer", developer_id=3, display_name="Three")
    my_row = db.sync.get(models.ConversationParticipant, "q1")
    for kind in ("text", "card"):
        with pytest.raises(cs.ChatError) as e:
            run(chat_router._relay_resident_send(db, mir, my_row, actor, kind, "hello", None, "ref-mirror-001"))
        assert e.value.status_code == 409 and e.value.detail == POST_SENTENCE
    assert sent == []                                                            # nothing left this registry


def test_a_mirror_refuses_a_residents_change_in_an_archived_room_before_asking_the_host(db, monkeypatch):
    mir = _mirror(db)
    _archive(db, mir)
    calls = []
    _client(monkeypatch, _Resp(200, {"changed": True}), calls)
    msg = db.sync.get(models.ChatMessage, "mm1")
    actor = cs.Actor("developer", developer_id=3, display_name="Three")
    for etype, kw in (("edit", {"body": "x"}), ("delete", {}), ("reaction", {"word": "ack", "on": True}), ("pin", {"on": True})):
        with pytest.raises(cs.ChatError) as e:
            run(fev.relay_change(db, mir, actor, msg, etype, **kw))
        assert e.value.status_code == 409 and e.value.detail == CHANGE_SENTENCE
    assert calls == []
    _unarchive(db, mir)                                                          # unarchive restores asking the host
    out = run(fev.relay_change(db, mir, actor, msg, "edit", body="new"))
    assert out["changed"] is True and len(calls) == 1


def test_an_open_mirror_still_relays_a_post(db, monkeypatch):
    mir = _mirror(db)
    sent = []

    async def relay_to_host(*a, **k):
        sent.append(a)
        return {"seq": 3, "duplicate": False}

    async def wire_id(db_, ptype, ident):
        return f"dev:{ident}"
    monkeypatch.setattr(fed, "relay_to_host", relay_to_host)
    monkeypatch.setattr(fed, "local_wire_id", wire_id)
    actor = cs.Actor("developer", developer_id=3, display_name="Three")
    my_row = db.sync.get(models.ConversationParticipant, "q1")
    out = run(chat_router._relay_resident_send(db, mir, my_row, actor, "text", "hello", None, "ref-mirror-002"))
    assert out["relayed"] is True and len(sent) == 1
