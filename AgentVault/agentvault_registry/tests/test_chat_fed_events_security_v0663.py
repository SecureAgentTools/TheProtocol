"""V0663 (order gwo_7b419a71432588d46a90ff5d, the security read of 2026-11-14, E1 to E4): the cross-frame change events.

Each test names the failure scenario the read described and was written red before its fix.

  E1  a host cannot make a resident record a reaction or a pin as one of the resident's OWN users: an actor naming this
      registry maps to a local principal only when this registry relayed that very change (as a delivered message does);
  E2  the relay-event door is capped per thread and per peer, and per actor, like relay-send and the local routes;
  E3  a host's "close" never deletes a mirror that holds a message from a person or an agent: it archives it;
  E4  a delivered reaction word outside the closed vocabulary is not stored (and does not hold back the thread).
"""
from __future__ import annotations

import pytest

from agentvault_registry import models
from agentvault_registry.background_tasks import leader
from agentvault_registry.services import chat_federation as fed
from agentvault_registry.services import chat_fed_events as fev
from agentvault_registry.services import chat_service as cs
from tests.test_chat_fed_events_v0663 import (  # noqa: F401  (db is the shared fixture)
    HOST, ME, MEMBER, NOW, ROOM, _asked, _host_room, _mirror, _recv, db, run)


class _Redis:
    def __init__(self):
        self.kv = {}

    async def set(self, key, value, ex=None, nx=False):
        self.kv[key] = value
        return True

    async def get(self, key):
        return self.kv.get(key)


@pytest.fixture()
def redis(monkeypatch):
    r = _Redis()

    async def _get_redis():
        return r
    monkeypatch.setattr(leader, "get_redis", _get_redis)
    return r


def _mine(monkeypatch):
    """This registry is `ME`, and `dev:3` is one of its own developers."""
    async def mine(db_, handle):
        return ("developer", "3") if handle == "dev:3" else None
    monkeypatch.setattr(fed, "_resolve_local_principal", mine)
    monkeypatch.setattr(fed, "self_base_url", lambda: ME)


# ── E1 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_E1_a_host_cannot_make_us_record_a_reaction_as_one_of_our_users_we_never_relayed(db, monkeypatch, redis):
    """Host H delivers {"type": "reaction", "actor": "dev:3@<us>"} for a change dev 3 never made: it must not be stored as dev 3."""
    _mirror(db)
    _mine(monkeypatch)
    _recv(db, {"type": "reaction", "message_seq": 1, "word": "ack", "on": True, "actor": f"dev:3@{ME}"})
    r = db.sync.query(models.ChatReaction).one()
    assert (r.actor_ptype, r.actor_id) == ("remote", f"dev:3@{ME}")          # a stranger's word, never our developer's own


def test_E1_a_host_cannot_make_us_record_a_pin_as_one_of_our_users_we_never_relayed(db, monkeypatch, redis):
    _mirror(db)
    _mine(monkeypatch)
    _recv(db, {"type": "pin", "message_seq": 1, "on": True, "actor": f"dev:3@{ME}"})
    p = db.sync.query(models.ChatPin).one()
    assert (p.pinned_by_ptype, p.pinned_by_id) == ("remote", f"dev:3@{ME}")


def test_E1_the_reaction_we_relayed_comes_back_as_our_own_user(db, monkeypatch, redis):
    """The honest path stays whole: dev 3 reacts on the mirror, the relay writes its record before the POST, the host's event
    comes back and reads as dev 3's own (so the console shows it as `mine`)."""
    mir = _mirror(db)
    _mine(monkeypatch)
    run(fev._record_event_relay(HOST, ROOM, "reaction", 1, f"dev:3@{ME}", word="ack", on=True))
    _recv(db, {"type": "reaction", "message_seq": 1, "word": "ack", "on": True, "actor": f"dev:3@{ME}"})
    r = db.sync.query(models.ChatReaction).one()
    assert (r.actor_ptype, r.actor_id) == ("developer", "3")
    run(fev._record_event_relay(HOST, ROOM, "pin", 2, f"dev:3@{ME}", on=True))
    _recv(db, {"type": "pin", "message_seq": 2, "on": True, "actor": f"dev:3@{ME}"})
    assert db.sync.query(models.ChatPin).one().pinned_by_ptype == "developer"
    assert mir is not None


def test_E1_a_record_for_one_change_does_not_vouch_for_another(db, monkeypatch, redis):
    """Relayed: dev 3 reacts `ack` on message 1. The host also sends `done` on message 1, `ack` on message 2 and an `off`: no record, no vouch."""
    _mirror(db)
    _mine(monkeypatch)
    run(fev._record_event_relay(HOST, ROOM, "reaction", 1, f"dev:3@{ME}", word="ack", on=True))
    for ev in ({"message_seq": 1, "word": "done", "on": True}, {"message_seq": 2, "word": "ack", "on": True}):
        _recv(db, {"type": "reaction", "actor": f"dev:3@{ME}", **ev})
    rows = db.sync.query(models.ChatReaction).all()
    assert len(rows) == 2 and {r.actor_ptype for r in rows} == {"remote"}


def test_E1_the_member_of_a_mirror_who_reacts_writes_the_record_before_the_post(db, monkeypatch, redis):
    """relay_change must leave the record the event's return needs: a reaction and then the host's event of it read as ours."""
    mir = _mirror(db)
    _mine(monkeypatch)
    sent = []

    class _R:
        status_code = 200

        def json(self):
            return {"changed": True}

    class Client:
        async def post(self, url, headers=None, json=None):
            sent.append(json)
            return _R()

    async def target(db_, base):
        return HOST, {}, {}
    monkeypatch.setattr(fed, "federation_target", target)
    monkeypatch.setattr(fed, "peer_client", lambda t, k: Client())

    async def local_key(db_, actor):
        return f"dev:3@{ME}"
    monkeypatch.setattr(fev, "local_actor_key", local_key)
    msg = db.sync.get(models.ChatMessage, "mm1")
    actor = cs.Actor("developer", developer_id=3, display_name="Three")
    run(fev.relay_change(db, mir, actor, msg, "reaction", word="ack", on=True))
    assert sent and sent[0]["type"] == "reaction"
    _recv(db, {"type": "reaction", "message_seq": 1, "word": "ack", "on": True, "actor": f"dev:3@{ME}"})
    assert db.sync.query(models.ChatReaction).one().actor_ptype == "developer"


# ── E2 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_E2_the_relay_event_door_is_capped_per_peer_per_thread_and_per_actor(db, monkeypatch):
    """A peer's member toggling a reaction in a loop is refused with a 429 once the cap is spent, and nothing is queued."""
    _host_room(db)
    asked = []

    async def rate(kind, *parts):
        asked.append((kind, parts))
        return kind not in refused
    refused = {"relay_event_peer"}
    monkeypatch.setattr(fed, "fed_rate_ok", rate)
    with pytest.raises(cs.ChatError) as e:
        _asked(db, MEMBER, "reaction", word="ack", on=True, seq=2)
    assert e.value.status_code == 429
    assert db.sync.query(models.ChatReaction).count() == 0
    assert db.sync.query(models.ChatFederationOutbox).count() == 0
    for kind in ("relay_event_thread", "relay_event_actor"):
        refused.clear()
        refused.add(kind)
        with pytest.raises(cs.ChatError) as e:
            _asked(db, MEMBER, "reaction", word="ack", on=True, seq=2)
        assert e.value.status_code == 429, kind
    assert {k for k, _ in asked} >= {"relay_event_peer", "relay_event_thread", "relay_event_actor"}


def test_E2_the_caps_are_declared_so_the_first_request_does_not_raise_a_key_error():
    for kind in ("relay_event_peer", "relay_event_thread", "relay_event_actor"):
        limit, window = fed.FED_RL[kind]
        assert limit > 0 and window > 0


# ── E3 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_E3_a_host_close_archives_a_mirror_that_holds_messages_instead_of_deleting_its_history(db):
    """Host H sends `close` for a room with a month of messages: the resident keeps them, archived, and the history survives."""
    conv = _mirror(db)
    out = _recv(db, {"type": "room", "action": "close", "at": NOW.isoformat()})
    assert out["action"] == "archive" and out["duplicate"] is False
    assert db.sync.get(models.Conversation, "mir-1") is not None
    assert db.sync.query(models.ChatMessage).filter_by(conversation_id="mir-1").count() == 2
    db.sync.refresh(conv)
    assert conv.archived_at is not None and conv.archived_by == "host"


def test_E3_a_host_close_still_removes_a_mirror_with_nothing_but_system_rows(db):
    s = db.sync
    s.add(models.Conversation(id="mir-2", kind="room", title="R", created_by_ptype="remote", created_by_id=f"x@{HOST}",
                              host_registry=HOST, remote_ref="room-2", last_seq=1))
    s.add(models.ChatMessage(id="sys1", conversation_id="mir-2", seq=1, remote_seq=1, origin_registry=HOST, sender_ptype="remote",
                             sender_id=HOST, kind="system", body="room opened", client_ref="c-sys0001", created_at=NOW))
    s.commit()
    out = _recv(db, {"type": "room", "action": "close", "at": NOW.isoformat()}, ref="room-2")
    assert out["action"] == "close" and db.sync.get(models.Conversation, "mir-2") is None


# ── E4 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_E4_a_delivered_reaction_word_outside_the_closed_vocabulary_is_not_stored(db):
    """A host that sends any text as a reaction word (or one longer than the column) stores nothing, and answers 200 so the
    thread's later rows are not held back behind a row that can never apply."""
    _mirror(db)
    for word in ("lol", "x" * 40, ""):
        out = _recv(db, {"type": "reaction", "message_seq": 1, "word": word, "on": True, "actor": MEMBER})
        assert out["duplicate"] is True
    assert db.sync.query(models.ChatReaction).count() == 0
    _recv(db, {"type": "reaction", "message_seq": 1, "word": "ack", "on": True, "actor": MEMBER})
    assert db.sync.query(models.ChatReaction).count() == 1                   # a word of the vocabulary still lands
