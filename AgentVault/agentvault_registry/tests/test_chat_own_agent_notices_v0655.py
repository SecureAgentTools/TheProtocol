"""V0655 (az) (order gwo_16a6212cd90dbe18baa3537c): your own agents' asks and mentions reach you; only a visible page
counts as present.

Measured on EU (the order): in 14 days the maintainer's notification history held no chat.approval_requested, no
chat.mention and no chat.direct, while the four session agents (all of his account) asked him for approvals at least
eight times. Two causes in chat_service.fan_out_message / _notify_absent (V0654):
  * "you are never notified about your own household's send" counted every line his agents wrote as his own send;
  * a socket of his that was alive anywhere (a background tab, a pocketed phone) held every notice back, and left no
    history row, so the history could not say why nothing came.
Now an agent's own line (sent_by_owner false) tells its owner what is addressed to him: a request he may decide, a line
that names him. Its other traffic stays quiet for him, and a line he wrote himself, or as the agent, never notifies him.
Presence counts a page that says it is visible (routers/websocket.py); a notice held back for presence leaves one row.

BASE (V0654, 670962dea): the owner receives nothing in the first two cases, no row is written in the held-back case,
and a hidden heartbeat refreshes presence. The tests drive asyncio.run themselves (any pytest-asyncio mode).
"""
from __future__ import annotations

import asyncio
import sys
import types

from agentvault_registry.services import chat_service as cs

OWNER, OTHER = 6, 7
LEAD = "did:theprotocol:eu.test:lead"
APPROVAL = {"v": 1, "type": "approval.request", "data": {"approval_id": "apr_" + "a" * 32, "title": "Roll V0655"}}


def _msg(body="the build is green", *, mentions=None, card=None, sent_by_owner=False, ptype="agent"):
    return {"id": "m1", "seq": 9, "kind": "card" if card else "text", "body": None if card else body, "card": card,
            "mentions": mentions or [], "sender_ptype": ptype, "sender_id": LEAD if ptype == "agent" else OWNER,
            "sent_by_owner": sent_by_owner}


def _room():
    """the other participants of the sessions' room: its owner (whose agent wrote the line) and another developer"""
    return [{"ptype": "developer", "agent_did": None, "developer_id": d, "owner_developer_id": d, "muted": False}
            for d in (OWNER, OTHER)]


def _deliver(monkeypatch, message, *, present=(), deciders=(), recipients=None, conv_kind="org", is_ping=False):
    """fan_out_message with the modules it imports at call time as stand-ins; returns (notices, held-back rows)"""
    sent, held = [], []

    class _Manager:
        async def broadcast_to_subscribers(self, topic, envelope):
            pass

        async def is_present(self, dev_id):
            return int(dev_id) in set(present)

    ws = types.ModuleType("agentvault_registry.routers.websocket")
    ws.manager = _Manager()
    pn = types.ModuleType("agentvault_registry.background_tasks.push_notify")

    async def _notify(ntype, devs, **kw):
        sent.append((ntype, tuple(devs)))

    async def _held(ntype, dev, reason, **kw):
        held.append((ntype, dev, reason, kw.get("title")))
    pn.notify, pn.record_held_back = _notify, _held
    for mod in (ws, pn):
        monkeypatch.setitem(sys.modules, mod.__name__, mod)
    from agentvault_registry.services import chat_approvals as ca

    async def _deciders(_conv, ids, db=None):
        return set(deciders) & set(ids)
    monkeypatch.setattr(ca, "deciders_among", _deciders)

    async def go():
        await cs.fan_out_message("room1", conv_kind, message, recipients or _room(), "session-lead",
                                 is_ping=is_ping, sender_owner_dev_id=OWNER)
        await asyncio.gather(*[t for t in list(cs._BACKGROUND) if not t.done()], return_exceptions=True)
    asyncio.run(go())
    return sorted(sent), held


def test_his_agents_approval_request_reaches_him_as_an_approval(monkeypatch):
    sent, _ = _deliver(monkeypatch, _msg(card=APPROVAL), deciders=(OWNER,))
    assert ("chat.approval_requested", (OWNER,)) in sent, sent       # BASE: nothing for the owner


def test_his_agents_mention_of_him_reaches_him_as_a_mention(monkeypatch):
    sent, _ = _deliver(monkeypatch, _msg("@Commander the cut is open", mentions=[{"key": "dev:6", "token": "Commander"}]))
    assert ("chat.mention", (OWNER,)) in sent, sent                  # BASE: nothing for the owner
    assert ("chat.message", (OTHER,)) in sent                        # the room's other member: unchanged


def test_his_agents_plain_line_and_its_all_stay_quiet_for_him(monkeypatch):
    for body in ("the build is green", "@all the build is green"):
        sent, held = _deliver(monkeypatch, _msg(body))
        assert all(OWNER not in devs for _t, devs in sent), (body, sent)
        assert not held


def test_a_line_he_wrote_as_his_agent_never_notifies_him(monkeypatch):
    sent, _ = _deliver(monkeypatch, _msg("@Commander note to self", mentions=[{"key": "dev:6"}], sent_by_owner=True))
    assert all(OWNER not in devs for _t, devs in sent), sent
    sent, _ = _deliver(monkeypatch, _msg(card=APPROVAL, sent_by_owner=True), deciders=(OWNER,))
    assert all(OWNER not in devs for _t, devs in sent), sent


def test_his_own_line_and_a_ping_from_his_agent_never_notify_him(monkeypatch):
    sent, _ = _deliver(monkeypatch, _msg("@Commander", mentions=[{"key": "dev:6"}], ptype="developer"))
    assert all(OWNER not in devs for _t, devs in sent), sent
    sent, _ = _deliver(monkeypatch, _msg("ping", mentions=[{"key": "dev:6"}]), is_ping=True)
    assert all(OWNER not in devs for _t, devs in sent), sent


def test_a_room_he_muted_brings_only_the_ask(monkeypatch):
    muted = [{"ptype": "developer", "agent_did": None, "developer_id": OWNER, "owner_developer_id": OWNER, "muted": True}]
    sent, _ = _deliver(monkeypatch, _msg("@Commander", mentions=[{"key": "dev:6"}]), recipients=muted)
    assert sent == []
    sent, _ = _deliver(monkeypatch, _msg(card=APPROVAL), deciders=(OWNER,), recipients=muted)
    assert sent == [("chat.approval_requested", (OWNER,))]


def test_a_notice_held_back_because_he_is_in_the_app_leaves_one_row(monkeypatch):
    sent, held = _deliver(monkeypatch, _msg(card=APPROVAL), deciders=(OWNER,), present=(OWNER,))
    assert all(OWNER not in devs for _t, devs in sent)
    assert [(t, d, r) for t, d, r, _title in held] == [("chat.approval_requested", OWNER, "present")]  # BASE: no row
    assert held[0][3] == "Approval requested by session-lead"
    # a member the line does not address is not told, so nothing is held back for him either
    sent, held = _deliver(monkeypatch, _msg("the build is green"), present=(OWNER, OTHER))
    assert sent == [] and [(t, d) for t, d, _r, _ti in held] == [("chat.message", OTHER)]


# ── the row itself ────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_held_back_row_is_one_suppressed_row_with_its_reason(monkeypatch):
    from agentvault_registry.background_tasks import push_notify as pn
    rows = []

    async def _write(r):
        rows.extend(r)
    monkeypatch.setattr(pn, "_write_notification_log", _write)
    monkeypatch.setattr(pn.settings, "NOTIFY_V2_MODE", "on", raising=False)
    asyncio.run(pn.record_held_back("chat.approval_requested", OWNER, "present", title="Approval requested", message="x"))
    assert len(rows) == 1
    r = rows[0]
    assert (r["developer_id"], r["type_key"], r["outcome"], r["reason"], r["channel"]) == \
        (OWNER, "chat.approval_requested", "suppressed", "present", "all")
    monkeypatch.setattr(pn.settings, "NOTIFY_V2_MODE", "off", raising=False)
    asyncio.run(pn.record_held_back("chat.approval_requested", OWNER, "present", title="t", message="m"))
    assert len(rows) == 1, "no history while the legacy path runs (it keeps none)"
    asyncio.run(pn.record_held_back("no.such.type", OWNER, "present", title="t", message="m"))
    assert len(rows) == 1


# ── presence: only a visible page counts ─────────────────────────────────────────────────────────────────────────────

def _manager(monkeypatch):
    from agentvault_registry.routers import websocket as ws
    m = ws.ConnectionManager.__new__(ws.ConnectionManager)
    m.active_connections, m._hidden = {}, set()
    keys = {}

    class _Redis:
        async def setex(self, k, ttl, v):
            keys[k] = v

        async def exists(self, k):
            return 1 if k in keys else 0

    async def _r():
        return _Redis()
    m._get_redis = _r
    return m, keys


def test_a_hidden_page_is_not_present_and_a_visible_one_is(monkeypatch):
    m, keys = _manager(monkeypatch)
    m.active_connections["6"] = object()
    m.mark_shown("6", False)
    assert asyncio.run(m.is_present("6")) is False, "a hidden tab holds a socket and reads nothing"   # BASE: True
    m.mark_shown("6", True)
    assert asyncio.run(m.is_present("6")) is True


def test_the_heartbeat_refreshes_presence_only_for_a_visible_page_or_one_that_does_not_say(monkeypatch):
    from agentvault_registry.routers import websocket as ws
    m, keys = _manager(monkeypatch)
    monkeypatch.setattr(ws, "manager", m)
    asyncio.run(ws.heartbeat_presence("6", {"timestamp": 1, "visible": False}))
    assert keys == {} and "6" in m._hidden                                # BASE: no such step, the key was refreshed
    asyncio.run(ws.heartbeat_presence("6", {"timestamp": 2, "visible": True}))
    assert keys == {"presence:ws:6": "1"} and "6" not in m._hidden
    keys.clear()
    asyncio.run(ws.heartbeat_presence("7", {"timestamp": 3}))             # a client that does not say: as before
    assert keys == {"presence:ws:7": "1"}
    asyncio.run(ws.heartbeat_presence("8", None))
    assert "presence:ws:8" in keys
