"""V0651 (y2) (order gwo_6f197b1815662c025e8a8eb0, agentvault2-14, 2026-10-31): an approval request reaches its deciders'
devices by default.

session-lead's check in the sessions' room (seq 340): the maintainer's two web-push devices are registered and enabled,
and an approval request reached neither. It went out as chat.message, whose pushes are off until a thread's opt-in card
is tapped; EU runs the v2 notices (NOTIFY_V2_MODE=on), where a device without its own list gets a type exactly when the
type's default says so. (y) promised "the push" too. Now a request's deciders (the org's owner and the named approvers,
read live) get chat.approval_requested, on by default on both push channels and in the legacy default set; the room's
other members keep the in-app chat.message. Each case fails on 84e840985 (the first V0651 cut).
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.services import notification_catalog as nc
from agentvault_registry.services import notification_prefs as np_


def run(coro):
    return asyncio.run(coro)


def test_a_device_with_default_settings_gets_an_approval_request():
    entry = nc.get_type("chat.approval_requested")
    assert entry is not None and entry.category == "chat" and not entry.mandatory
    ctx = np_.DevCtx(dev_id=6)   # no preference rows at all: his account as measured
    for channel in ("push_desktop", "push_mobile", "inapp"):
        send, reason, _ = np_.decide(entry, channel, ctx=ctx, device_prefs=None, amount=None, now_hour=12)
        assert send, (channel, reason)


def test_control_room_traffic_still_waits_for_the_opt_in():
    entry = nc.get_type("chat.message")
    send, _reason, _ = np_.decide(entry, "push_mobile", ctx=np_.DevCtx(dev_id=6), device_prefs=None, amount=None,
                                  now_hour=12)
    assert not send


def test_the_legacy_default_set_carries_it_like_a_sign_in_approval():
    from agentvault_registry.background_tasks import push_notify as pn
    assert {"LoginApproval", "chat.approval_requested"} <= pn.DELEGATION_DEFAULT_EVENTS
    assert pn._device_wants(None, "chat.approval_requested", None) is True
    assert pn._device_wants(None, "chat.message", None) is False


def test_a_device_that_narrowed_its_list_stays_narrowed():
    entry = nc.get_type("chat.approval_requested")
    send, reason, _ = np_.decide(entry, "push_mobile", ctx=np_.DevCtx(dev_id=6),
                                 device_prefs={"event_types": ["LoginApproval"]}, amount=None, now_hour=12)
    assert not send and reason == "narrowed"


# ── who gets which notice ────────────────────────────────────────────────────────────────────────────────────────────

APR = "apr_" + "d1" * 16


def _card_message():
    return {"id": "m1", "seq": 9, "kind": "card", "body": None,
            "card": {"v": 1, "type": "approval.request", "data": {"approval_id": APR, "title": "V0651 production roll"}}}


def _absent(monkeypatch, message, deciders=None, fail=False, is_ping=False):
    from agentvault_registry.background_tasks import push_notify
    from agentvault_registry.services import chat_approvals as ca
    from agentvault_registry.services import chat_service as cs
    sent = []

    async def _notify(event, devs, **kw):
        sent.append((event, tuple(devs), kw.get("click")))

    async def _deciders(_conv, ids, db=None):
        if fail:
            raise RuntimeError("the database went away")
        return set(deciders or ()) & set(ids)

    monkeypatch.setattr(push_notify, "notify", _notify)
    monkeypatch.setattr(ca, "deciders_among", _deciders)
    run(cs._notify_absent("room-a", message, [6, 7, 8], "session-release", is_ping, None))
    return sent


def test_the_deciders_get_the_request_and_the_room_the_plain_notice(monkeypatch):
    sent = _absent(monkeypatch, _card_message(), deciders={6, 7})
    by_dev = {devs[0]: event for event, devs, _click in sent}
    assert by_dev == {6: "chat.approval_requested", 7: "chat.approval_requested", 8: "chat.message"}, sent
    assert all(click.endswith(f"?approval={APR}") for _e, _d, click in sent)


def test_a_failed_read_of_the_deciders_still_tells_everyone(monkeypatch):
    sent = _absent(monkeypatch, _card_message(), deciders={6}, fail=True)
    assert sorted(devs[0] for _e, devs, _c in sent) == [6, 7, 8]
    assert {event for event, _d, _c in sent} == {"chat.message"}


def test_control_a_text_message_never_asks_for_deciders(monkeypatch):
    sent = _absent(monkeypatch, {"id": "m2", "seq": 10, "kind": "text", "body": "hello", "card": None}, deciders={6, 7, 8})
    assert {event for event, _d, _c in sent} == {"chat.message"}


def test_the_deciders_are_read_live_from_the_org(monkeypatch):
    from agentvault_registry.models import Conversation, Organization, OrganizationMember
    from agentvault_registry.services import chat_approvals as ca
    from tests._sqlite_db import sqlite_db
    db = sqlite_db(Organization, OrganizationMember, Conversation)
    s = db.sync
    s.add(Organization(id="org-a", name="TheProtocol Sessions", slug="org-a", owner_id=6))
    for i, (dev, role, can, active) in enumerate(((6, "owner", False, True), (7, "member", True, True),
                                                  (8, "member", False, True), (9, "member", True, False))):
        s.add(OrganizationMember(id=f"m{i}", organization_id="org-a", developer_id=dev, role=role, is_active=active,
                                 can_approve=can))
    s.add(Conversation(id="room-a", kind="org", title="TheProtocol Sessions", org_id="org-a",
                       created_by_ptype="system", created_by_id="genesis"))
    s.add(Conversation(id="dm-1", kind="dm", title=None, created_by_ptype="developer", created_by_id="6"))
    s.commit()
    assert run(ca.deciders_among("room-a", [6, 7, 8, 9], db=db)) == {6, 7}
    assert run(ca.deciders_among("dm-1", [6, 7], db=db)) == set()
    assert run(ca.deciders_among("room-a", [], db=db)) == set()
