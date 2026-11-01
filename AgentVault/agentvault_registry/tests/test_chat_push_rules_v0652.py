"""V0652 (z) (order gwo_2b801ba5d3a2fba7ae5e1909, agentvault2-14, 2026-10-31): push only what needs you.

His plan "readable chat and Claude on phone and desktop" (approval card apr_830978ac, item 5): a push reaches a member
only for what needs them: an approval request they may decide, a message that names them, a direct message to them;
never a room's other traffic. Approval requests cross quiet hours; the others keep them. On the existing preferences.
And session-tester's finding (the room, seq 337-339): a stranger's first message to a PERSON notified nobody.

Each case fails on 05441be31 (the V0651 recut), which routes every absent member's notice to chat.message (pushes off
until a thread's card is tapped, then ALL of a room's traffic) and tells a person of nothing at a knock.
"""
from __future__ import annotations

import asyncio
import inspect
import types

from agentvault_registry.services import chat_service as cs
from agentvault_registry.services import notification_catalog as nc
from agentvault_registry.services import notification_prefs as np_


def run(coro):
    return asyncio.run(coro)


def _msg(body="hello", mentions=None, card=None, kind="text"):
    return {"id": "m1", "seq": 3, "kind": kind, "body": body, "card": card, "mentions": mentions or []}


# ── which notice a member gets ───────────────────────────────────────────────────────────────────────────────────────

def test_a_room_message_naming_another_member_is_room_traffic_for_him():
    m = _msg("@session-lead please look", mentions=[{"key": "dev:7", "label": "session-lead"}])
    assert cs.notice_type_for(6, m, "org", set(), False) == "chat.message"
    assert cs.notice_type_for(7, m, "org", set(), False) == "chat.mention"


def test_his_mention_a_direct_message_and_a_decision_each_have_their_type():
    assert cs.notice_type_for(6, _msg(mentions=[{"key": "dev:6"}]), "org", set(), False) == "chat.mention"
    assert cs.notice_type_for(6, _msg("@all the roll starts"), "org", set(), False) == "chat.mention"
    assert cs.notice_type_for(6, _msg("hi"), "dm", set(), False) == "chat.direct"
    card = {"v": 1, "type": "approval.request", "data": {"approval_id": "apr_" + "a" * 32}}
    assert cs.notice_type_for(6, _msg(None, card=card, kind="card"), "org", {6}, False) == "chat.approval_requested"
    assert cs.notice_type_for(6, _msg("x"), "org", set(), True) == "chat.ping"


def _absent(monkeypatch, message, conv_kind, deciders=()):
    from agentvault_registry.background_tasks import push_notify
    from agentvault_registry.services import chat_approvals as ca
    sent = []

    async def _notify(event, devs, **kw):
        sent.append((event, tuple(devs)))

    async def _deciders(_conv, ids, db=None):
        return set(deciders) & set(ids)

    monkeypatch.setattr(push_notify, "notify", _notify)
    monkeypatch.setattr(ca, "deciders_among", _deciders)
    run(cs._notify_absent("c1", message, [6, 7, 8], "session-lead", False, None, conv_kind=conv_kind))
    return sent


def test_each_absent_member_gets_one_notice_of_its_kind(monkeypatch):
    sent = _absent(monkeypatch, _msg("@maintainer see this", mentions=[{"key": "dev:6"}]), "org")
    assert sorted(sent) == [("chat.mention", (6,)), ("chat.message", (7,)), ("chat.message", (8,))]
    sent = _absent(monkeypatch, _msg("just us"), "dm")
    assert sorted(sent) == [("chat.direct", (6,)), ("chat.direct", (7,)), ("chat.direct", (8,))]


def test_the_fan_out_tells_the_notice_step_what_kind_of_conversation_it_is():
    src = inspect.getsource(cs.fan_out_message)
    assert "conv_kind=conv_kind" in src


# ── the preferences route them ───────────────────────────────────────────────────────────────────────────────────────

def _decide(key, channel, rows=None, prefs=None, hour=12):
    ctx = np_.DevCtx(dev_id=6, notification_prefs=prefs or {}, rows=rows or {})
    return np_.decide(nc.get_type(key), channel, ctx=ctx, device_prefs=None, amount=None, now_hour=hour)


def test_room_traffic_never_pushes_even_after_the_old_opt_in():
    opted = {("chat.message", "push_mobile"): (True, None), ("chat.message", "push_desktop"): (True, None)}
    for channel in ("push_mobile", "push_desktop"):
        send, reason, _ = _decide("chat.message", channel, rows=opted)
        assert not send and reason == "inapp_only"
    assert _decide("chat.message", "inapp")[0] is True


def test_what_needs_you_pushes_by_default():
    for key in ("chat.mention", "chat.direct", "chat.request", "chat.approval_requested"):
        for channel in ("push_mobile", "push_desktop", "inapp"):
            assert _decide(key, channel)[0] is True, (key, channel)


def test_an_approval_request_crosses_quiet_hours_while_a_mention_waits():
    quiet = {"quiet_hours_start": 22, "quiet_hours_end": 6}
    send, reason, _ = _decide("chat.mention", "push_mobile", prefs=quiet, hour=23)
    assert not send and reason == "quiet"
    send, reason, _ = _decide("chat.approval_requested", "push_mobile", prefs=quiet, hour=23)
    assert send, reason
    # a person who turned approval pushes off is still obeyed (crossing quiet hours is not mandatory)
    off = {("chat.approval_requested", "push_mobile"): (False, None)}
    assert _decide("chat.approval_requested", "push_mobile", rows=off, prefs=quiet, hour=23)[0] is False


def test_the_catalog_names_the_new_category():
    for key in ("chat.mention", "chat.direct", "chat.request"):
        t = nc.get_type(key)
        assert t is not None and t.category == "chat" and not t.mandatory and not t.crosses_quiet_hours
    assert nc.get_type("chat.approval_requested").crosses_quiet_hours is True
    assert nc.get_type("chat.message").inapp_only is True
    # the decisions someone waits on: an approval request, and (V0652 (af)) a choice asked of you
    assert [t.key for t in nc.CATALOG if t.crosses_quiet_hours] == ["chat.approval_requested", "chat.choice_requested"]


# ── a stranger's first message to a person ───────────────────────────────────────────────────────────────────────────

def test_a_knock_on_a_person_finds_them_waiting():
    from agentvault_registry.models import Conversation, ConversationParticipant
    from tests._sqlite_db import sqlite_db
    db = sqlite_db(Conversation, ConversationParticipant)
    s = db.sync
    s.add(Conversation(id="c1", kind="dm", title=None, created_by_ptype="developer", created_by_id="16"))
    s.add(ConversationParticipant(conversation_id="c1", ptype="developer", developer_id=16, role="owner", state="active"))
    s.add(ConversationParticipant(conversation_id="c1", ptype="developer", developer_id=6, role="member", state="pending"))
    s.add(Conversation(id="c2", kind="dm", title=None, created_by_ptype="developer", created_by_id="16"))
    s.add(ConversationParticipant(conversation_id="c2", ptype="developer", developer_id=6, role="member", state="active"))
    s.commit()
    conv = types.SimpleNamespace(id="c1")
    assert run(cs.pending_developer_target(db, conv, "developer", "6")) == 6
    assert run(cs.pending_developer_target(db, types.SimpleNamespace(id="c2"), "developer", "6")) is None
    assert run(cs.pending_developer_target(db, conv, "agent", "did:theprotocol:x")) is None


def test_the_person_is_told_once(monkeypatch):
    from agentvault_registry.background_tasks import push_notify
    sent = []

    async def _notify(event, devs, **kw):
        sent.append((event, tuple(devs), kw["title"], kw["click"]))

    monkeypatch.setattr(push_notify, "notify", _notify)
    run(cs.notify_developer_request("c1", 6, _msg("Hello, I found you by your handle"), "support-probe-p"))
    assert sent == [("chat.request", (6,), "support-probe-p wants to talk with you", "/ui#/pocket/ourchat/c1")]


def test_the_create_route_tells_a_person_of_a_knock():
    from agentvault_registry.routers import chat
    src = inspect.getsource(chat)
    assert "cs.pending_developer_target(db, conv, t_type, t_id)" in src
    assert "cs.notify_developer_request(conv.id, pending_dev, first, actor.display_name)" in src
