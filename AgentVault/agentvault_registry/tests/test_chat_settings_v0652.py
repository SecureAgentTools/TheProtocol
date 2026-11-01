"""V0652 (ak) (order gwo_8c69cc0fd1f3033a35f47969, agentvault2-14, 2026-11-01): the chat settings' server half.

The design (sessionlogs2026/DESIGN_2026-11-01_OURCHAT_SETTINGS.md) and session-lead's review of it (the sessions' room,
seq 397, and REVIEW_2026-11-01_OURCHAT_SETTINGS_PART2.md):
- a mute can last a while and then ends by itself (muted_until, mig 0205); past its time it reads as no mute;
- a muted thread still brings you an approval or a choice that waits on you, and nothing else;
- a support thread has no timer (the ticket keeps the record), and in an organization's room an owner or an admin sets
  it (seq 398, "unless he says otherwise"); a direct thread keeps the old rule;
- a developer with no name is shown by their handle, else as "dev N", never by their e-mail address (item 20);
- a room in the list carries its organization's live name, as the thread does (item 14).
Each case fails on 05441be31 (the V0651 recut) except the ones marked control.
"""
from __future__ import annotations

import asyncio
import datetime
from types import SimpleNamespace

import pytest

from agentvault_registry.services import chat_service as cs

UTC = datetime.timezone.utc


def run(coro):
    return asyncio.run(coro)


def now():
    return datetime.datetime.now(UTC)


# ── a mute that ends by itself ──────────────────────────────────────────────────────────────────────────────────

def test_a_mute_reads_as_none_once_its_time_has_passed():
    t = now()
    assert cs.mute_in_effect(True, None, t) is True                                       # until lifted
    assert cs.mute_in_effect(True, t + datetime.timedelta(hours=1), t) is True
    assert cs.mute_in_effect(True, t - datetime.timedelta(seconds=1), t) is False
    assert cs.mute_in_effect(False, t + datetime.timedelta(hours=1), t) is False
    naive = (t + datetime.timedelta(hours=1)).replace(tzinfo=None)                          # read as UTC
    assert cs.mute_in_effect(True, naive, t) is True


@pytest.fixture()
def row(monkeypatch):
    r = SimpleNamespace(muted=False, muted_until=None)

    async def _conv(db, cid):
        return SimpleNamespace(id=cid, kind="dm", org_id=None)

    async def _member(db, conv, actor):
        return r
    monkeypatch.setattr(cs, "_get_conversation", _conv)
    monkeypatch.setattr(cs, "resolve_membership", _member)
    return r


class _Db:
    async def commit(self):
        return None


ME = SimpleNamespace(key="dev:6", ptype="developer", developer_id=6, display_name="maintainer")


def test_a_mute_for_a_while(row):
    until = now() + datetime.timedelta(hours=8)
    out = run(cs.set_muted(_Db(), "c1", ME, True, until))
    assert row.muted is True and row.muted_until == until
    assert out["muted"] is True and out["muted_until"] == until.isoformat()
    out = run(cs.set_muted(_Db(), "c1", ME, False))
    assert row.muted is False and row.muted_until is None and out["muted_until"] is None


@pytest.mark.parametrize("muted,delta,words", [
    (True, datetime.timedelta(seconds=-5), "in the future"),
    (True, datetime.timedelta(days=31), "at most 30 days"),
    (False, datetime.timedelta(hours=1), "until goes with a mute"),
])
def test_a_mute_for_a_while_is_bounded(row, muted, delta, words):
    with pytest.raises(cs.ChatError) as e:
        run(cs.set_muted(_Db(), "c1", ME, muted, now() + delta))
    assert e.value.status_code == 422 and words in e.value.detail


def test_a_mute_until_lifted_is_unchanged(row):
    # control: the V0651 call (no until) still mutes until lifted
    out = run(cs.set_muted(_Db(), "c1", ME, True))
    assert row.muted is True and row.muted_until is None and out["muted"] is True


def test_the_route_takes_until():
    from agentvault_registry.routers.chat import MuteBody
    b = MuteBody(muted=True, until="2026-11-01T08:00:00Z")
    assert b.until == datetime.datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
    assert MuteBody().until is None and MuteBody().muted is True


def test_the_unread_count_and_the_list_read_the_mute_by_its_time():
    import inspect
    src = inspect.getsource(cs)
    assert "AND NOT (COALESCE(p.muted, false) AND (p.muted_until IS NULL OR p.muted_until > now()))" in src
    assert "BOOL_AND(COALESCE(p.muted, false) AND (p.muted_until IS NULL OR p.muted_until > now())) AS muted" in src


# ── an ask reaches a muted decider, nothing else does ───────────────────────────────────────────────────────────

APR = {"id": "m1", "seq": 3, "kind": "card", "body": None, "mentions": [],
       "card": {"v": 1, "type": "approval.request", "data": {"approval_id": "apr_" + "1" * 32, "title": "Roll"}}}
TEXT = {"id": "m2", "seq": 4, "kind": "text", "body": "hello room", "mentions": [], "card": None}


def _fan(monkeypatch, message, recipients):
    seen = {}

    async def _absent(conv_id, msg, notices, sender_name, is_ping, manager, conv_kind="", asks_only=None):
        seen["notices"], seen["asks_only"] = sorted(notices), sorted(asks_only or ())

    def _spawn(coro, what=None):
        seen["coro"] = coro

    async def _owners(*a, **k):
        return 0
    monkeypatch.setattr(cs, "_notify_absent", _absent)
    monkeypatch.setattr(cs, "spawn", _spawn)
    monkeypatch.setattr(cs, "_tell_agent_owners", _owners)
    import agentvault_registry.routers.websocket as ws
    monkeypatch.setattr(ws, "manager", None, raising=False)
    run(cs.fan_out_message("room-1", "org", message, recipients, "session-release"))
    if "coro" in seen:
        run(seen.pop("coro"))
    return seen


def _rcpt(dev, muted):
    return {"key": f"dev:{dev}", "ptype": "developer", "developer_id": dev, "agent_did": None, "muted": muted,
            "owner_developer_id": dev}


def test_a_muted_member_is_offered_an_ask_and_not_a_message(monkeypatch):
    seen = _fan(monkeypatch, APR, [_rcpt(6, True), _rcpt(7, False)])
    assert seen["notices"] == [6, 7] and seen["asks_only"] == [6]
    seen = _fan(monkeypatch, TEXT, [_rcpt(6, True), _rcpt(7, False)])
    assert seen["notices"] == [7] and seen["asks_only"] == []                            # control: as before


def test_the_ask_goes_to_a_muted_decider_only(monkeypatch):
    told = []

    async def _notify(ntype, devs, **kw):
        told.append((ntype, tuple(devs)))

    async def _deciders(conv_id, devs):
        return {6}
    import agentvault_registry.background_tasks.push_notify as pn
    from agentvault_registry.services import chat_approvals as ca
    monkeypatch.setattr(pn, "notify", _notify)
    monkeypatch.setattr(ca, "deciders_among", _deciders)
    # 6 and 8 muted; 6 decides, 8 does not; 7 is not muted
    run(cs._notify_absent("room-1", APR, [6, 7, 8], "session-release", False, None, conv_kind="org", asks_only={6, 8}))
    assert told == [("chat.approval_requested", (6,)), ("chat.message", (7,))]


# ── the timer ───────────────────────────────────────────────────────────────────────────────────────────────────

def _timer(monkeypatch, kind, role):
    conv = SimpleNamespace(id="c1", kind=kind, org_id="org-1" if kind == "org" else None, retention_hours=None)

    async def _conv(db, cid):
        return conv

    async def _row(db, cid, actor):
        return SimpleNamespace(state="active")

    async def _role(db, org_id, actor):
        return role

    async def _insert(db, conv, row, actor, kind, body, card, **kw):
        return SimpleNamespace(), False
    monkeypatch.setattr(cs, "_get_conversation", _conv)
    monkeypatch.setattr(cs, "_my_row", _row)
    monkeypatch.setattr(cs, "actor_org_role", _role)
    monkeypatch.setattr(cs, "insert_message", _insert)
    monkeypatch.setattr(cs, "serialize_message", lambda m: {"kind": "system"})
    return conv


def test_a_support_thread_has_no_timer(monkeypatch):
    _timer(monkeypatch, "support", None)
    with pytest.raises(cs.ChatError) as e:
        run(cs.set_retention(_Db(), "c1", ME, 24))
    assert e.value.status_code == 409 and "the ticket keeps its record" in e.value.detail


@pytest.mark.parametrize("role", ["member", None])
def test_in_an_org_room_a_member_or_an_agent_cannot_set_it(monkeypatch, role):
    _timer(monkeypatch, "org", role)
    with pytest.raises(cs.ChatError) as e:
        run(cs.set_retention(_Db(), "c1", ME, 1))
    assert e.value.status_code == 403 and "an owner or an admin sets the timer" in e.value.detail


@pytest.mark.parametrize("kind,role", [("org", "owner"), ("org", "admin"), ("dm", None)])
def test_an_owner_an_admin_and_either_side_of_a_dm_can(monkeypatch, kind, role):
    # control: they could before, and still can
    conv = _timer(monkeypatch, kind, role)
    out = run(cs.set_retention(_Db(), "c1", ME, 24))
    assert conv.retention_hours == 24 and out["retention_hours"] == 24


# ── names, never an e-mail address ──────────────────────────────────────────────────────────────────────────────

def test_a_developer_is_named_by_name_then_handle_then_number():
    assert cs.developer_display_name(SimpleNamespace(id=6, name="maintainer", handle="ruffa", email="x@y.z")) == "maintainer"
    assert cs.developer_display_name(SimpleNamespace(id=6, name="  ", handle="ruffa", email="x@y.z")) == "@ruffa"
    assert cs.developer_display_name(SimpleNamespace(id=12, name=None, handle=None, email="x@y.z")) == "dev 12"


def test_display_names_never_reads_an_email(monkeypatch):
    seen = {}

    class _Rows:
        def all(self):
            return [(12, None), (6, "maintainer"), (9, "@kestrel")]

    class _NamesDb:
        async def execute(self, stmt, params=None):
            seen["sql"] = " ".join(str(stmt).split())
            return _Rows()
    out = run(cs.display_names(_NamesDb(), ["dev:12", "dev:6", "dev:9"]))
    assert out == {"dev:12": "dev 12", "dev:6": "maintainer", "dev:9": "@kestrel"}
    assert "email" not in seen["sql"] and "handle" in seen["sql"]


def test_the_actor_is_never_named_by_email():
    dev = SimpleNamespace(id=12, name="", handle=None, email="someone@example.test", is_admin=False)
    a = cs.actor_from_auth({"kind": "developer", "developer": dev})
    assert a.display_name == "dev 12"


# ── the list names a room by its organization's live name ───────────────────────────────────────────────────────

def test_the_list_reads_the_organizations_live_name():
    import inspect
    src = inspect.getsource(cs.list_conversations)
    assert "(SELECT o.name FROM organizations o WHERE o.id = c.org_id) AS org_name" in src
    assert '"title": (r[19] or r[2]) if r[1] == "org" else r[2]' in src


# ── the thread read says the reader's mute, and how many have opened a room ─────────────────────────────────────

def test_the_thread_read_carries_the_mute_and_the_rooms_count():
    import inspect
    src = inspect.getsource(cs.list_messages)
    assert '"muted": mute_in_effect(getattr(my_row, "muted", False), getattr(my_row, "muted_until", None))' in src
    assert '"muted_until": (my_row.muted_until.isoformat()' in src
    assert '"member_count": int((await db.execute(sa_text(' in src
    assert "WHERE conversation_id = :c AND state = 'active'" in src
