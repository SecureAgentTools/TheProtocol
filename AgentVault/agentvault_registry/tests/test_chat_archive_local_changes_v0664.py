"""V0664 (order gwo_d00e70ecfebc83950ebbb9fb, found by session-watch, room seq 3824): an archived room is read, not changed,
by anyone, its LOCAL members included.

A local post was refused by insert_message and a relayed change by the host's relay gate (V0663, e7e51341d); a local member's
edit, take-back, reaction (on and off), pin (on and off) and progress-card update went through. Every one of them is refused
now with ARCHIVED_CHANGE (409) while the conversation's archived_at is set, and passes again after the unarchive; nothing it
would have written is written. Over real (SQLite) rows, the harness of tests/test_chat_fed_events_v0663.py.

Decided with it (the hand-in names them):
  a rail's card update   the Guild's live order card and an approval's decided card are the host's own record of an act decided
                         elsewhere, like its system rows: they pass in an archived room as before
  a stranger             is told what a stranger is told (the membership refusal), never that the room is archived
  a direct thread        is never archived (only a room is): its changes pass as before
  the board and agent    exist in an organization's room only, and only a room archives: an archived room has neither, and
  status                 the archive act refuses an organization's room (pinned below, so a change to either rule shows here)
Red on e7e51341d: the seven local changes go through in an archived room.
"""
from __future__ import annotations

import asyncio
import datetime

import pytest

from agentvault_registry import models
from agentvault_registry.services import chat_fed_events as fev
from agentvault_registry.services import chat_federation as fed
from agentvault_registry.services import chat_live_cards as lc
from agentvault_registry.services import chat_rooms as rooms
from agentvault_registry.services import chat_service as cs
from tests._sqlite_db import sqlite_db

HOST = "https://a.example"
NOW = datetime.datetime.now(datetime.timezone.utc)
OWNER = cs.Actor("developer", developer_id=1, display_name="One")
MEMBER = cs.Actor("developer", developer_id=3, display_name="Three")
STRANGER = cs.Actor("developer", developer_id=9, display_name="Nine")
ROOM, DM = "room-1", "dm-1"


def run(coro):
    return asyncio.run(coro)


def progress(state="running"):
    return {"v": 1, "type": "progress", "data": {"title": "the pair proof", "state": state}}


@pytest.fixture()
def db(monkeypatch):
    d = sqlite_db(models.Developer, models.Agent, models.Conversation, models.ConversationParticipant, models.ChatMessage,
                  models.ChatMessageEdit, models.ChatReaction, models.ChatPin, models.ChatCardUpdate,
                  models.ChatFederationOutbox, models.ChatRoomBan)
    s = d.sync
    for i in (1, 3, 9):
        s.add(models.Developer(id=i, name=f"d{i}", email=f"d{i}@example.org", hashed_password="x"))
    for cid, kind, roles in ((ROOM, "room", {1: "owner", 3: "member"}), (DM, "dm", {1: None, 3: None})):
        s.add(models.Conversation(id=cid, kind=kind, title="R" if kind == "room" else None, created_by_ptype="developer",
                                  created_by_id="1", last_seq=3, join_rule="anyone" if kind == "room" else None))
        for dev, role in roles.items():
            s.add(models.ConversationParticipant(id=f"{cid}-p{dev}", conversation_id=cid, ptype="developer", developer_id=dev,
                                                 role=role, state="active"))
        s.add(models.ChatMessage(id=f"{cid}-m1", conversation_id=cid, seq=1, sender_ptype="developer", sender_id="3",
                                 kind="text", body="hello from three", client_ref=f"{cid}-c1", created_at=NOW))
        s.add(models.ChatMessage(id=f"{cid}-m2", conversation_id=cid, seq=2, sender_ptype="developer", sender_id="1",
                                 kind="text", body="hello from one", client_ref=f"{cid}-c2", created_at=NOW))
        s.add(models.ChatMessage(id=f"{cid}-m3", conversation_id=cid, seq=3, sender_ptype="developer", sender_id="3",
                                 kind="card", card=progress(), client_ref=f"{cid}-c3", created_at=NOW))
    s.commit()

    async def resolve(db_, conv, actor):
        return s.query(models.ConversationParticipant).filter_by(
            conversation_id=conv.id, developer_id=actor.developer_id).first()

    async def local_key(db_, actor):
        return f"dev:{actor.developer_id}@{HOST}"
    monkeypatch.setattr(cs, "resolve_membership", resolve)
    monkeypatch.setattr(cs, "room_posting_gate", lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr(fev, "local_actor_key", local_key)
    monkeypatch.setattr(fed, "self_base_url", lambda: HOST)
    monkeypatch.setattr(fed, "wake_after_commit", lambda db_: None)
    return d


def _set_archived(db, cid, on):
    db.sync.expire_all()
    conv = db.sync.get(models.Conversation, cid)
    conv.archived_at, conv.archived_by = (NOW, "dev:1") if on else (None, None)
    db.sync.commit()


# each act: (who, the call), on the room or the dm
ACTS = {
    "edit": (MEMBER, lambda d, c: cs.edit_message(d, c, f"{c}-m1", MEMBER, "edited by three")),
    "take back": (MEMBER, lambda d, c: cs.delete_message(d, c, f"{c}-m1", MEMBER)),
    "reaction on": (MEMBER, lambda d, c: cs.add_reaction(d, c, f"{c}-m2", MEMBER, "ack")),
    "reaction off": (MEMBER, lambda d, c: cs.remove_reaction(d, c, f"{c}-m2", MEMBER, "thanks")),
    "pin": (OWNER, lambda d, c: cs.pin_message(d, c, f"{c}-m1", OWNER)),
    "unpin": (OWNER, lambda d, c: cs.unpin_message(d, c, f"{c}-m2", OWNER)),
    "progress card": (MEMBER, lambda d, c: cs.update_card(d, c, f"{c}-m3", MEMBER, progress("passed"))),
}


def _before(db, cid):
    """What a reaction-off and an unpin take away: a reaction and a pin put on while the room is open."""
    run(cs.add_reaction(db, cid, f"{cid}-m2", MEMBER, "thanks"))
    run(cs.pin_message(db, cid, f"{cid}-m2", OWNER))


def _state(db, cid):
    db.sync.expire_all()
    s = db.sync
    m1, m3 = s.get(models.ChatMessage, f"{cid}-m1"), s.get(models.ChatMessage, f"{cid}-m3")
    return {"m1": (m1.body, m1.deleted_at is not None), "m3": m3.card,
            "edits": s.query(models.ChatMessageEdit).count(),
            "reactions": sorted((r.message_id, r.word) for r in s.query(models.ChatReaction).all()),
            "pins": sorted(p.message_id for p in s.query(models.ChatPin).filter_by(conversation_id=cid).all()),
            "card_updates": s.query(models.ChatCardUpdate).count()}


@pytest.mark.parametrize("act", list(ACTS))
def test_an_archived_room_refuses_a_local_members_change_and_takes_it_after_the_unarchive(db, act):
    _before(db, ROOM)
    _set_archived(db, ROOM, True)
    seen = _state(db, ROOM)
    with pytest.raises(cs.ChatError) as e:
        run(ACTS[act][1](db, ROOM))
    assert (e.value.status_code, e.value.detail) == (409, cs.ARCHIVED_CHANGE)
    assert _state(db, ROOM) == seen, "nothing written"
    _set_archived(db, ROOM, False)
    run(ACTS[act][1](db, ROOM))
    assert _state(db, ROOM) != seen, "the same act changes the room once it is open again"


@pytest.mark.parametrize("act", list(ACTS))
def test_a_direct_thread_is_not_affected(db, act):
    _before(db, DM)
    seen = _state(db, DM)
    run(ACTS[act][1](db, DM))
    assert _state(db, DM) != seen


def test_a_stranger_is_told_what_a_stranger_is_told_not_that_the_room_is_archived(db):
    _set_archived(db, ROOM, True)
    with pytest.raises(cs.ChatError) as e:
        run(cs.add_reaction(db, ROOM, f"{ROOM}-m2", STRANGER, "ack"))
    assert e.value.detail != cs.ARCHIVED_CHANGE and "archived" not in e.value.detail


def test_a_rails_card_update_still_passes_in_an_archived_room(db):
    card = lc.guild_order_card({"id": "gwo_1", "title": "Build", "status": "open", "bounty": "15", "currency": "ECU"},
                               [{"seq": 1, "event_type": "posted", "at": None}], bid_count=0)
    s = db.sync
    s.add(models.ChatMessage(id="glive", conversation_id=ROOM, seq=4, sender_ptype="system", sender_id="guild", kind="card",
                             card=card, client_ref="glive-gwo_1", created_at=NOW))
    s.commit()
    _set_archived(db, ROOM, True)
    done = lc.guild_order_card({"id": "gwo_1", "title": "Build", "status": "settled", "bounty": "15", "currency": "ECU"},
                               [{"seq": 1, "event_type": "posted", "at": None},
                                {"seq": 5, "event_type": "settled", "at": None}], bid_count=1)
    sys_actor = cs.Actor("system", display_name="Guild", system_id="guild")
    out, _conv, changed = run(cs.update_card(db, ROOM, "glive", sys_actor, done, rail_author=True))
    assert changed and out["card"]["data"]["status"] == "settled"


def test_the_board_and_agent_status_cannot_meet_an_archived_room(db):
    """The board and agent status exist in an organization's room only; only a room archives. Both halves pinned."""
    from agentvault_registry.services import chat_board
    _set_archived(db, ROOM, True)
    with pytest.raises(cs.ChatError) as e:
        run(chat_board.set_board(db, ROOM, OWNER, "the plan", 0))
    assert e.value.status_code == 409 and "organization's room" in e.value.detail
    with pytest.raises(cs.ChatError) as e:
        run(cs.report_agent_status(db, ROOM, OWNER, []))
    assert e.value.status_code == 409 and "organization's room" in e.value.detail
    s = db.sync
    s.add(models.Conversation(id="org-1", kind="org", org_id="o-1", title="O", created_by_ptype="developer", created_by_id="1",
                              last_seq=0))
    s.add(models.ConversationParticipant(id="org-p1", conversation_id="org-1", ptype="developer", developer_id=1, role="owner",
                                         state="active"))
    s.commit()
    with pytest.raises(cs.ChatError) as e:
        run(rooms.room_action(db, "org-1", OWNER, "archive"))
    assert e.value.status_code in (404, 409, 422) and db.sync.get(models.Conversation, "org-1").archived_at is None
