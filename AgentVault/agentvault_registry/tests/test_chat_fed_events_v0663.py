"""V0663 (order gwo_9dce94d939aff2fa8ea4f91c): edits, take-backs, reactions, pins and a room's archive or close across frames
(services/chat_fed_events.py). The three halves over real (SQLite) rows:

  * HOST publish: one event row per registry that has a member, in the messages' own outbox, its seq the host's last seq;
  * HOST apply of a request a resident relayed: the rules of a local thread (sender only and the window, a room's operators for a
    pin, the closed reaction words), the asker's own key and home;
  * RESIDENT receive: the host's word applied to the mirror, idempotent, refused when the host or the thread is not the caller's;
  * RESIDENT relay: a member of a mirror asks the host and nothing is stored here.

Not in this slice, on the record: state from before a registry joined (earlier reactions and pins on lines it never saw): the
events are live, and a late joiner mirrors the messages it receives from then on.
"""
from __future__ import annotations

import asyncio
import datetime
import types

import pytest

from agentvault_registry import models
from agentvault_registry.services import chat_federation as fed
from agentvault_registry.services import chat_fed_events as fev
from agentvault_registry.services import chat_service as cs
from tests._sqlite_db import sqlite_db

HOST = "https://a.example"
B, C, ME = "https://b.example", "https://c.example", "https://me.example"
MEMBER = f"dev:5@{B}"           # a resident member of the room, on b
MOD = f"dev:6@{C}"              # a resident moderator, on c
ROOM = "room-1"
NOW = datetime.datetime.now(datetime.timezone.utc)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def db(monkeypatch):
    d = sqlite_db(models.Developer, models.Agent, models.Conversation, models.ConversationParticipant, models.ChatMessage,
                  models.ChatMessageEdit, models.ChatReaction, models.ChatPin, models.ChatFederationOutbox, models.ChatRoomBan)
    s = d.sync
    for i in (1, 3):
        s.add(models.Developer(id=i, name=f"d{i}", email=f"d{i}@example.org", hashed_password="x"))
    s.commit()

    async def caller_is(db_, peer, origin):
        return peer == origin

    async def peer_ok(db_, base):
        return base

    async def rate_ok(*a, **k):
        return True
    monkeypatch.setattr(fed, "caller_is", caller_is)
    monkeypatch.setattr(fed, "assert_peer_allowed", peer_ok)
    monkeypatch.setattr(fed, "fed_rate_ok", rate_ok)
    monkeypatch.setattr(fed, "federation_enabled", lambda: True)
    monkeypatch.setattr(fed, "self_base_url", lambda: HOST)
    monkeypatch.setattr(fed, "wake_after_commit", lambda db_: None)
    d.host_seq = 0
    return d


def _host_room(db, *, pins=False):
    """A room this registry hosts: local owner dev 1, a remote member (b) and a remote moderator (c); seq 1 by the member,
    seq 2 by the owner."""
    s = db.sync
    s.add(models.Conversation(id=ROOM, kind="room", title="R", created_by_ptype="developer", created_by_id="1", last_seq=2,
                              join_rule="anyone"))
    s.add(models.ConversationParticipant(id="p1", conversation_id=ROOM, ptype="developer", developer_id=1, role="owner", state="active"))
    s.add(models.ConversationParticipant(id="p2", conversation_id=ROOM, ptype="remote", remote_key=MEMBER, role="member", state="active"))
    s.add(models.ConversationParticipant(id="p3", conversation_id=ROOM, ptype="remote", remote_key=MOD, role="moderator", state="active"))
    s.add(models.ChatMessage(id="m1", conversation_id=ROOM, seq=1, sender_ptype="remote", sender_id=MEMBER, kind="text",
                             body="hello from b", client_ref="c-000001", created_at=NOW))
    s.add(models.ChatMessage(id="m2", conversation_id=ROOM, seq=2, sender_ptype="developer", sender_id="1", kind="text",
                             body="hello from a", client_ref="c-000002", created_at=NOW))
    s.commit()
    return s.get(models.Conversation, ROOM)


def _mirror(db):
    """The same room as this registry (me) mirrors it: host a, local member dev 3, the host's messages with their remote_seq."""
    s = db.sync
    s.add(models.Conversation(id="mir-1", kind="room", title="R", created_by_ptype="remote", created_by_id=f"x@{HOST}",
                              host_registry=HOST, remote_ref=ROOM, last_seq=2))
    s.add(models.ConversationParticipant(id="q1", conversation_id="mir-1", ptype="developer", developer_id=3, role="member", state="active"))
    s.add(models.ChatMessage(id="mm1", conversation_id="mir-1", seq=1, remote_seq=1, origin_registry=HOST, sender_ptype="remote",
                             sender_id=MEMBER, kind="text", body="hello from b", client_ref="c-000001", created_at=NOW))
    s.add(models.ChatMessage(id="mm2", conversation_id="mir-1", seq=2, remote_seq=2, origin_registry=HOST, sender_ptype="remote",
                             sender_id=f"dev:1@{HOST}", kind="text", body="hello from a", client_ref="c-000002", created_at=NOW))
    s.commit()
    return s.get(models.Conversation, "mir-1")


def _envelope(event, host=HOST, ref=ROOM):
    return {"v": 1, "host_registry": host, "conversation": {"id": ref, "kind": "room", "title": "R", "participants": []},
            "event": {"id": "ev-1", **event}}


# ── HOST: publish ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_publish_queues_one_event_per_registry_with_the_hosts_last_seq(db):
    conv = _host_room(db)
    n = run(fev.publish(db, conv, {"type": "pin", "message_seq": 1, "on": True, "actor": "dev:1@" + HOST}))
    db.sync.commit()
    rows = db.sync.query(models.ChatFederationOutbox).order_by(models.ChatFederationOutbox.peer_base_url).all()
    assert n == 2 and [r.peer_base_url for r in rows] == [B, C]
    assert all(r.event_id and r.seq == 2 and r.conversation_id == ROOM for r in rows)
    env = rows[0].payload
    assert env["host_registry"] == HOST and env["conversation"]["id"] == ROOM and env["event"]["type"] == "pin"
    assert env["event"]["id"] == rows[0].event_id == rows[1].event_id


def test_publish_does_nothing_on_a_mirror_or_for_a_thread_no_other_registry_reaches(db):
    mir = _mirror(db)
    assert run(fev.publish(db, mir, {"type": "pin", "message_seq": 1, "on": True})) == 0
    s = db.sync
    s.add(models.Conversation(id="solo", kind="room", title="S", created_by_ptype="developer", created_by_id="1", last_seq=0))
    s.commit()
    assert run(fev.publish(db, s.get(models.Conversation, "solo"), {"type": "pin", "message_seq": 1, "on": True})) == 0
    assert s.query(models.ChatFederationOutbox).count() == 0


def test_a_message_row_and_event_rows_of_one_seq_can_live_together_but_a_message_row_twice_cannot(db):
    from sqlalchemy.exc import IntegrityError
    conv = _host_room(db)
    s = db.sync
    s.add(models.ChatFederationOutbox(id="o1", conversation_id=ROOM, seq=2, peer_base_url=B, payload={}))
    s.commit()
    run(fev.publish(db, conv, {"type": "pin", "message_seq": 2, "on": True}))
    run(fev.publish(db, conv, {"type": "reaction", "message_seq": 2, "word": "ack", "on": True}))
    s.commit()                                                          # two events and a message, all at seq 2, to b
    assert s.query(models.ChatFederationOutbox).filter_by(peer_base_url=B, seq=2).count() == 3
    s.add(models.ChatFederationOutbox(id="o2", conversation_id=ROOM, seq=2, peer_base_url=B, payload={}))
    with pytest.raises(IntegrityError):
        s.commit()
    s.rollback()


def test_the_outbox_keeps_events_after_the_message_they_follow():
    import inspect
    src = inspect.getsource(fed._due_conditions) + inspect.getsource(fed.drain_outbox) + inspect.getsource(fed._due_batch)
    assert "e.created_at < chat_federation_outbox.created_at" in src
    assert 'int(r.seq), str(getattr(r, "created_at", "") or "")' in src and "ChatFederationOutbox.seq, ChatFederationOutbox.created_at" in src


# ── HOST: a request a resident relayed ────────────────────────────────────────────────────────────────────────────
def _asked(db, who, etype, **kw):
    _host_room(db) if db.sync.get(models.Conversation, ROOM) is None else None
    return run(fev.host_apply_relayed(db, {"conversation_ref": ROOM, "actor_key": who, "actor_display": "A", "type": etype,
                                           "message_seq": kw.pop("seq", 1), **kw}, peer=who.split("@", 1)[1]))


def test_a_resident_edits_its_own_line_inside_the_window_and_the_host_tells_everyone(db):
    out = _asked(db, MEMBER, "edit", body="hello again")
    assert out["changed"] is True and out["message"]["body"] == "hello again"
    m1 = db.sync.get(models.ChatMessage, "m1")
    db.sync.refresh(m1)
    assert m1.body == "hello again" and m1.edited_at is not None
    ev = db.sync.query(models.ChatFederationOutbox).all()
    assert len(ev) == 2 and ev[0].payload["event"]["type"] == "edit" and ev[0].payload["event"]["actor"] == MEMBER
    assert out["_fan"]["event"]["rev"] == 1


def test_a_resident_cannot_edit_someone_elses_line_or_a_line_outside_the_window(db):
    with pytest.raises(cs.ChatError) as e:
        _asked(db, MEMBER, "edit", body="not mine", seq=2)                 # the owner's line
    assert e.value.status_code == 403 and "only whoever wrote" in e.value.detail
    old = db.sync.get(models.ChatMessage, "m1")
    old.created_at = NOW - datetime.timedelta(hours=2)
    db.sync.commit()
    with pytest.raises(cs.ChatError) as e:
        _asked(db, MEMBER, "edit", body="too late")
    assert e.value.status_code == 409 and "minutes" in e.value.detail
    assert db.sync.query(models.ChatFederationOutbox).count() == 0         # a refusal queues nothing


def test_a_resident_takes_back_its_own_line_and_the_pin_goes_with_it(db):
    _host_room(db)
    db.sync.add(models.ChatPin(conversation_id=ROOM, message_id="m1", pinned_by_ptype="developer", pinned_by_id="1"))
    db.sync.commit()
    out = _asked(db, MEMBER, "delete")
    assert out["message"]["deleted"] is True or out["message"].get("deleted_at")
    assert db.sync.query(models.ChatPin).count() == 0
    assert db.sync.query(models.ChatFederationOutbox).first().payload["event"]["type"] == "delete"


def test_a_resident_reacts_once_and_takes_it_back_and_only_with_the_closed_words(db):
    _asked(db, MEMBER, "reaction", word="ack", on=True, seq=2)
    again = _asked(db, MEMBER, "reaction", word="ack", on=True, seq=2)
    assert again["changed"] is False                                       # the same press twice is one reaction
    r = db.sync.query(models.ChatReaction).one()
    assert (r.actor_ptype, r.actor_id, r.word) == ("remote", MEMBER, "ack")
    with pytest.raises(cs.ChatError) as e:
        _asked(db, MEMBER, "reaction", word="lol", on=True, seq=2)
    assert e.value.status_code == 422
    _asked(db, MEMBER, "reaction", word="ack", on=False, seq=2)
    assert db.sync.query(models.ChatReaction).count() == 0


def test_in_a_room_its_moderator_pins_and_a_member_does_not(db):
    with pytest.raises(cs.ChatError) as e:
        _asked(db, MEMBER, "pin", on=True)
    assert e.value.status_code == 403 and "owner and moderators" in e.value.detail
    out = _asked(db, MOD, "pin", on=True)
    assert out["pinned"] is True and db.sync.query(models.ChatPin).one().pinned_by_id == MOD
    _asked(db, MOD, "pin", on=False)
    assert db.sync.query(models.ChatPin).count() == 0


def test_a_request_is_refused_unless_the_calling_registry_is_the_actors_home_and_the_actor_is_seated(db):
    _host_room(db)
    with pytest.raises(cs.ChatError) as e:                                 # c claims b's member
        run(fev.host_apply_relayed(db, {"conversation_ref": ROOM, "actor_key": MEMBER, "type": "pin", "message_seq": 1, "on": True}, peer=C))
    assert e.value.status_code == 403 and "home registry" in e.value.detail
    with pytest.raises(cs.ChatError) as e:                                 # not in the thread
        run(fev.host_apply_relayed(db, {"conversation_ref": ROOM, "actor_key": f"dev:9@{B}", "type": "pin", "message_seq": 1, "on": True}, peer=B))
    assert e.value.status_code == 403 and "not a participant" in e.value.detail
    with pytest.raises(cs.ChatError) as e:                                 # a mirror is not the host
        _mirror(db)
        run(fev.host_apply_relayed(db, {"conversation_ref": "mir-1", "actor_key": MEMBER, "type": "pin", "message_seq": 1, "on": True}, peer=B))
    assert e.value.status_code == 404
    with pytest.raises(cs.ChatError) as e:                                 # a move a resident may not ask for
        run(fev.host_apply_relayed(db, {"conversation_ref": ROOM, "actor_key": MEMBER, "type": "room", "message_seq": 1}, peer=B))
    assert e.value.status_code == 422


# ── RESIDENT: the host's word ─────────────────────────────────────────────────────────────────────────────────────
def _recv(db, event, **kw):
    return run(fev.receive_event(db, _envelope(event, **kw), peer=kw.get("host", HOST)))


def test_a_mirror_applies_an_edit_once_and_a_repeat_changes_nothing(db):
    _mirror(db)
    out = _recv(db, {"type": "edit", "message_seq": 1, "body": "edited at the host", "at": NOW.isoformat(), "rev": 1, "actor": MEMBER})
    assert out["duplicate"] is False
    m = db.sync.get(models.ChatMessage, "mm1")
    db.sync.refresh(m)
    assert m.body == "edited at the host" and m.edited_at is not None
    assert _recv(db, {"type": "edit", "message_seq": 1, "body": "edited at the host", "at": NOW.isoformat(), "rev": 1, "actor": MEMBER})["duplicate"] is True
    assert db.sync.query(models.ChatMessageEdit).count() == 1


def test_a_mirror_applies_a_take_back_a_reaction_and_a_pin_and_follows_the_host(db):
    _mirror(db)
    assert _recv(db, {"type": "reaction", "message_seq": 2, "word": "done", "on": True, "actor": f"dev:3@{HOST[:0]}{ME}"})["duplicate"] is False
    assert db.sync.query(models.ChatReaction).one().word == "done"
    _recv(db, {"type": "reaction", "message_seq": 2, "word": "done", "on": False, "actor": MEMBER})
    assert db.sync.query(models.ChatReaction).count() == 1                  # a different actor's removal removes nothing
    _recv(db, {"type": "pin", "message_seq": 1, "on": True, "actor": MOD})
    assert db.sync.query(models.ChatPin).one().pinned_by_ptype == "remote"
    _recv(db, {"type": "delete", "message_seq": 1, "at": NOW.isoformat(), "actor": MEMBER})
    assert db.sync.query(models.ChatPin).count() == 0                       # the line taken back lost its pin
    m = db.sync.get(models.ChatMessage, "mm1")
    db.sync.refresh(m)
    assert m.deleted_at is not None


def test_one_of_our_own_members_reaction_comes_back_as_its_own_principal(db, monkeypatch):
    _mirror(db)
    kv = {}

    class _Redis:
        async def set(self, key, value, ex=None, nx=False):
            kv[key] = value

        async def get(self, key):
            return kv.get(key)

    async def _get_redis():
        return _Redis()
    from agentvault_registry.background_tasks import leader
    monkeypatch.setattr(leader, "get_redis", _get_redis)

    async def mine(db_, handle):
        return ("developer", "3") if handle == "dev:3" else None
    monkeypatch.setattr(fed, "_resolve_local_principal", mine)
    _recv(db, {"type": "reaction", "message_seq": 1, "word": "ack", "on": True, "actor": f"dev:3@{ME}"}, host=HOST)
    # the mirror's registry is `me`: its own principal is stored as itself, so the reaction reads as `mine` here, but only a change
    # this registry relayed (V0663 security read E1: the record the relay writes before its POST)
    monkeypatch.setattr(fed, "self_base_url", lambda: ME)
    run(fev._record_event_relay(HOST, ROOM, "reaction", 2, f"dev:3@{ME}", word="ack", on=True))
    _recv(db, {"type": "reaction", "message_seq": 2, "word": "ack", "on": True, "actor": f"dev:3@{ME}"})
    rows = db.sync.query(models.ChatReaction).order_by(models.ChatReaction.word).all()
    assert [(r.actor_ptype, r.actor_id) for r in rows][-1] == ("developer", "3")


def test_a_mirror_follows_an_archive_and_a_close_of_the_room(db):
    conv = _mirror(db)
    _recv(db, {"type": "room", "action": "archive", "at": NOW.isoformat()})
    db.sync.refresh(conv)
    assert conv.archived_at is not None
    assert _recv(db, {"type": "room", "action": "archive", "at": NOW.isoformat()})["duplicate"] is True
    _recv(db, {"type": "room", "action": "unarchive", "at": NOW.isoformat()})
    db.sync.refresh(conv)
    assert conv.archived_at is None
    # a mirror that holds a line from a person is archived by a close, never deleted (security read E3: tests/test_chat_fed_events_
    # security_v0663.py); one nobody has spoken in goes with its seats
    db.sync.query(models.ChatMessage).filter_by(conversation_id="mir-1").delete()
    db.sync.commit()
    out = _recv(db, {"type": "room", "action": "close", "at": NOW.isoformat()})
    assert out["action"] == "close" and db.sync.get(models.Conversation, "mir-1") is None


def test_an_event_is_refused_when_the_host_is_not_the_caller_the_thread_is_unknown_or_the_message_not_here_yet(db):
    _mirror(db)
    with pytest.raises(cs.ChatError) as e:
        run(fev.receive_event(db, _envelope({"type": "pin", "message_seq": 1, "on": True, "actor": MOD}), peer=C))
    assert e.value.status_code == 403 and "not this thread's host" in e.value.detail
    with pytest.raises(cs.ChatError) as e:
        _recv(db, {"type": "pin", "message_seq": 1, "on": True, "actor": MOD}, ref="nope")
    assert e.value.status_code == 404                                          # an event cannot create a mirror
    with pytest.raises(cs.ChatError) as e:
        _recv(db, {"type": "pin", "message_seq": 99, "on": True, "actor": MOD})
    assert e.value.status_code == 503 and "not been delivered here yet" in e.value.detail   # the host sends it again, bounded
    with pytest.raises(cs.ChatError) as e:
        _recv(db, {"type": "wave", "message_seq": 1})
    assert e.value.status_code == 422
    with pytest.raises(cs.ChatError) as e:
        run(fev.receive_event(db, {**_envelope({"type": "pin", "message_seq": 1}), "v": 2}, peer=HOST))
    assert e.value.status_code == 422


# ── RESIDENT: ask the host ────────────────────────────────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, code, body):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


def _client(monkeypatch, resp, calls):
    class Client:
        async def post(self, url, headers=None, json=None):
            calls.append((url, json))
            if isinstance(resp, Exception):
                raise resp
            return resp

    async def target(db_, base):
        return HOST, {}, {}
    monkeypatch.setattr(fed, "federation_target", target)
    monkeypatch.setattr(fed, "peer_client", lambda t, k: Client())


def test_a_member_of_a_mirror_asks_the_host_and_nothing_is_stored_here(db, monkeypatch):
    mir = _mirror(db)
    calls = []
    _client(monkeypatch, _Resp(200, {"message": {"id": "host-m1", "body": "new"}, "changed": True}), calls)
    msg = db.sync.get(models.ChatMessage, "mm1")
    actor = cs.Actor("developer", developer_id=3, display_name="Three")
    out = run(fev.relay_change(db, mir, actor, msg, "edit", body="new"))
    assert out["changed"] is True
    url, sent = calls[0]
    assert url == f"{HOST}/api/v1/federation/chat/relay-event"
    assert sent == {"conversation_ref": ROOM, "actor_key": f"dev:3@{HOST}", "actor_display": "Three", "type": "edit",
                    "message_seq": 1, "body": "new"}
    db.sync.refresh(msg)
    assert msg.body == "hello from b"                                          # the mirror waits for the host's event


def test_the_hosts_refusal_reaches_the_member_in_the_hosts_words_and_an_unreachable_host_changes_nothing(db, monkeypatch):
    mir = _mirror(db)
    msg = db.sync.get(models.ChatMessage, "mm1")
    actor = cs.Actor("developer", developer_id=3, display_name="Three")
    _client(monkeypatch, _Resp(403, {"detail": "only whoever wrote a message changes it"}), [])
    with pytest.raises(cs.ChatError) as e:
        run(fev.relay_change(db, mir, actor, msg, "edit", body="x"))
    assert e.value.status_code == 403 and "only whoever wrote" in e.value.detail
    _client(monkeypatch, RuntimeError("down"), [])
    with pytest.raises(cs.ChatError) as e:
        run(fev.relay_change(db, mir, actor, msg, "edit", body="x"))
    assert e.value.status_code == 502 and "nothing was changed" in e.value.detail
    host = _host_room(db)
    with pytest.raises(cs.ChatError) as e:                                     # a hosted thread is not relayed
        run(fev.relay_change(db, host, actor, db.sync.get(models.ChatMessage, "m1"), "edit", body="x"))
    assert e.value.status_code == 409


def test_the_local_changes_on_a_mirror_go_to_the_host_not_to_the_mirror(db, monkeypatch):
    """cs.edit_message / add_reaction / pin_message on a mirror: relayed, the mirror untouched, the route told nothing changed
    here (the host's event updates it)."""
    mir = _mirror(db)
    sent = []

    async def relay(db_, conv, actor, message, etype, **fields):
        sent.append((etype, fields, message.remote_seq))
        return {"message": {"id": "host-m", "body": fields.get("body")}, "changed": True}
    monkeypatch.setattr(fev, "relay_change", relay)

    async def resolve(db_, conv, actor):
        return db.sync.get(models.ConversationParticipant, "q1")
    monkeypatch.setattr(cs, "resolve_membership", resolve)
    actor = cs.Actor("developer", developer_id=3, display_name="Three")
    msg, conv, changed = run(cs.edit_message(db, mir.id, "mm1", actor, "x"))
    assert changed is False and msg["id"] == "host-m" and sent[0] == ("edit", {"body": "x"}, 1)
    run(cs.add_reaction(db, mir.id, "mm1", actor, "ack"))
    run(cs.pin_message(db, mir.id, "mm1", actor))
    assert [s[0] for s in sent] == ["edit", "reaction", "pin"] and sent[1][1] == {"word": "ack", "on": True}
    assert db.sync.query(models.ChatReaction).count() == 0 and db.sync.query(models.ChatPin).count() == 0


def test_the_local_changes_on_a_hosted_thread_queue_an_event_in_the_same_transaction(db, monkeypatch):
    host = _host_room(db)
    keys = {}

    async def local_key(db_, actor):
        return f"dev:1@{HOST}"
    monkeypatch.setattr(fev, "local_actor_key", local_key)

    async def resolve(db_, conv, actor):
        return db.sync.get(models.ConversationParticipant, "p1")
    monkeypatch.setattr(cs, "resolve_membership", resolve)
    monkeypatch.setattr(cs, "room_posting_gate", lambda *a, **k: asyncio.sleep(0))
    actor = cs.Actor("developer", developer_id=1, display_name="One")
    run(cs.edit_message(db, ROOM, "m2", actor, "edited by the owner"))
    run(cs.add_reaction(db, ROOM, "m1", actor, "thanks"))
    run(cs.pin_message(db, ROOM, "m1", actor))
    run(cs.unpin_message(db, ROOM, "m1", actor))
    run(cs.remove_reaction(db, ROOM, "m1", actor, "thanks"))
    run(cs.delete_message(db, ROOM, "m2", actor))
    types_ = [r.payload["event"]["type"] for r in db.sync.query(models.ChatFederationOutbox).filter_by(peer_base_url=B).order_by(
        models.ChatFederationOutbox.created_at).all()]
    assert sorted(types_) == sorted(["edit", "reaction", "pin", "pin", "reaction", "delete"])
    assert keys == {} and host is not None
