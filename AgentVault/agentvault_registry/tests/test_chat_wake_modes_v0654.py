"""V0654 (aq) (2026-11-02, agentvault2-14): sessions wake only when needed, the registry's side.

Order gwo_238870d0f3c281c7d870554d (his word in the sessions' room, seq 1091: "I approve ... the planned and approved modes
for chat"; the design: sessionlogs2026/DESIGN_2026-11-02_SESSION_WAKE_MODES.md, step 2). Each member of a conversation
keeps a wake mode (migration 0209): listen (every line meant for it, as before), on-call (only a line that @-names it, a
direct message, a decision on its own approval card, or the room owner's @all) or off (nothing). The sync feed's for=me
and the live delivery honour it. A member sets its own; the room's owner sets another's from a signed-in session only
(never a key, never an assistant). Each change posts one short line, which reaches the member it is about alone.

The pure rules directly; for=me through FastAPI on the real chat router over real (SQLite) rows (test_chat_sync_for_me's
environment); the setter on a real Postgres (MEMBERSHIP_TEST_DB, a throwaway one it may WIPE). BASE (V0653, f8f1993fb):
no mode, no rule, no route.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from agentvault_registry.services import chat_service as cs
from tests.test_chat_sync_for_me import AGENT, DM, KEY, OTHER, OWNER, ROOM, SENDER, _get, _post, _start
from tests.test_chat_sync_for_me import env  # noqa: F401,F811 (the fixture, registered by its import)

OTHER_KEY = "agt:" + OTHER.lower()


def _set_mode(db, conv, did, mode):
    from agentvault_registry import models
    row = db.sync.query(models.ConversationParticipant).filter_by(conversation_id=conv, agent_did=did).one()
    row.wake_mode = mode
    db.sync.commit()


async def _for_me(env, cursor):
    return (await _get(env.app, cursor=cursor, **{"for": "me"})).json()


# ── the rule ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _lets(mode, *, row, kind="org", owner=OWNER, decided_for=None):
    return cs.wake_mode_lets_through(mode, me_key=KEY, me_did=AGENT, row=row, conv_kind=kind, owner_id=owner,
                                     decided_for=decided_for)


def _r(**kw):
    base = {"sender_ptype": "agent", "sender_id": SENDER, "body": "hello", "card": None, "mentions": None}
    base.update(kw)
    return base


def test_listen_leaves_the_question_to_the_feeds_own_rule_and_off_lets_nothing_through():
    assert _lets("listen", row=_r()) is None and _lets(None, row=_r()) is None
    assert _lets("off", row=_r(mentions=[{"key": KEY}])) is False
    assert _lets("off", row=_r(), kind="dm") is False


def test_on_call_lets_through_its_four_and_nothing_else():
    assert _lets("on-call", row=_r(mentions=[{"key": KEY}])) is True                      # @-names it
    assert _lets("on-call", row=_r(), kind="dm") is True                                  # a direct message
    decided = _r(card={"type": "approval.decided", "data": {"approval_id": "apr_x"}})
    assert _lets("on-call", row=decided, decided_for=AGENT.upper()) is True              # a decision on its own card
    assert _lets("on-call", row=decided, decided_for=OTHER) is False                     # on another's
    assert _lets("on-call", row=decided, decided_for="*") is True                        # the delivery's hint
    owner_all = _r(sender_ptype="developer", sender_id=str(OWNER), body="@all we build at five")
    assert _lets("on-call", row=owner_all) is True                                       # the owner's @all
    assert _lets("on-call", row=_r(body="@all from a session")) is False                 # anyone else's @all
    assert _lets("on-call", row=_r(sender_ptype="developer", sender_id=str(OWNER), body="a word")) is False
    assert _lets("on-call", row=_r(mentions=[{"key": OTHER_KEY}])) is False              # naming another session


def test_a_wake_line_reaches_the_member_it_is_about_alone_whatever_its_mode():
    line = _r(kind="system", body="room.wake", sender_ptype="developer", sender_id=str(OWNER),
              card={"action": "wake", "value": "on-call", "target": KEY})
    me = cs.Actor("agent", agent_did=AGENT)
    other = cs.Actor("agent", agent_did=OTHER)
    conv = {"kind": "org", "owner_id": OWNER}
    assert cs.reaches_me(me, line, {**conv, "wake_mode": "off"}, None, set()) is True
    assert cs.reaches_me(other, line, conv, None, set()) is False         # the owner's line, and still not another's
    assert cs.live_wakes({"key": KEY, "agent_did": AGENT, "wake_mode": "off"}, line, "org") is True
    assert cs.live_wakes({"key": OTHER_KEY, "agent_did": OTHER, "wake_mode": "listen"}, line, "org") is False


def test_the_live_delivery_wakes_what_the_mode_lets_through():
    plain = {"sender_ptype": "agent", "sender_id": SENDER, "body": "progress", "mentions": []}
    named = dict(plain, mentions=[{"key": KEY}])
    r = {"key": KEY, "agent_did": AGENT, "room_owner_id": OWNER}
    assert cs.live_wakes(dict(r, wake_mode="listen"), plain, "org") is True
    assert cs.live_wakes(dict(r, wake_mode="on-call"), plain, "org") is False
    assert cs.live_wakes(dict(r, wake_mode="on-call"), named, "org") is True
    assert cs.live_wakes(dict(r, wake_mode="off"), named, "org") is False


def test_the_thread_list_previews_a_wake_line_as_a_sentence():
    card = {"by": "dev:6", "by_name": "maintainer", "action": "wake", "target_name": "session-tester",
            "value": "on-call", "target": KEY}
    assert cs._system_sentence("room.wake", card) == "maintainer set session-tester's wake mode to on-call"


def test_only_the_rooms_owner_signed_in_sets_another_members_mode():
    owner = cs.Actor("developer", developer_id=OWNER, sent_with="session")
    assert cs.may_set_wake_for_others(owner, OWNER) is True
    assert cs.may_set_wake_for_others(cs.Actor("developer", developer_id=OWNER, sent_with="api_key"), OWNER) is False
    assert cs.may_set_wake_for_others(cs.Actor("developer", developer_id=OWNER, sent_with="assistant"), OWNER) is False
    assert cs.may_set_wake_for_others(cs.Actor("developer", developer_id=7, sent_with="session"), OWNER) is False
    assert cs.may_set_wake_for_others(cs.Actor("agent", agent_did=AGENT, sent_with="agent"), OWNER) is False
    assert cs.may_set_wake_for_others(owner, None) is False


# ── the sync feed's for=me, over real rows ─────────────────────────────────────────────────────────────────────────────

async def test_on_call_the_feed_holds_only_its_four(env):
    _set_mode(env.db, ROOM, AGENT, "on-call")
    cursor = await _start(env)
    _post(env.db, ROOM, sender=str(OWNER), ptype="developer", body="a word from the owner")    # listen: reaches
    _post(env.db, ROOM, body="@all from a session")                                          # listen: reaches
    named = _post(env.db, ROOM, body="@waiting-agent you", mentions=[{"key": KEY}])
    owner_all = _post(env.db, ROOM, sender=str(OWNER), ptype="developer", body="@all build at five")
    mine = _post(env.db, ROOM, body=None, card={"v": 1, "type": "approval.decided", "data": {"approval_id": "apr_mine"},
                                                "refs": {"approval_id": "apr_mine"}})
    _post(env.db, ROOM, body=None, card={"v": 1, "type": "approval.decided", "data": {"approval_id": "apr_other"},
                                         "refs": {"approval_id": "apr_other"}})
    direct = _post(env.db, DM, body="just to you")                                           # the DM row listens
    out = await _for_me(env, cursor)
    assert [m["id"] for m in out["messages"]] == [named.id, owner_all.id, mine.id, direct.id]


async def test_off_the_feed_holds_nothing_from_that_room(env):
    _set_mode(env.db, ROOM, AGENT, "off")
    cursor = await _start(env)
    _post(env.db, ROOM, body="@waiting-agent you", mentions=[{"key": KEY}])
    _post(env.db, ROOM, sender=str(OWNER), ptype="developer", body="@all build at five")
    direct = _post(env.db, DM, body="just to you")
    out = await _for_me(env, cursor)
    assert [m["id"] for m in out["messages"]] == [direct.id]


async def test_listen_is_as_before(env):
    # control: every row starts listen (the migration's default), and the feed holds what V0651 (t) held
    cursor = await _start(env)
    owner_line = _post(env.db, ROOM, sender=str(OWNER), ptype="developer", body="a word from the owner")
    anyone_all = _post(env.db, ROOM, body="@all from a session")
    _post(env.db, ROOM, body="a plain line")
    out = await _for_me(env, cursor)
    assert [m["id"] for m in out["messages"]] == [owner_line.id, anyone_all.id]


async def test_a_wake_line_reaches_its_member_and_no_other(env):
    cursor = await _start(env)
    about_me = _post(env.db, ROOM, sender=str(OWNER), ptype="developer", kind="system", body="room.wake",
                     card={"by": "dev:6", "by_name": "maintainer", "action": "wake", "value": "on-call", "target": KEY})
    _post(env.db, ROOM, sender=str(OWNER), ptype="developer", kind="system", body="room.wake",
          card={"by": "dev:6", "by_name": "maintainer", "action": "wake", "value": "off", "target": OTHER_KEY})
    out = await _for_me(env, cursor)
    assert [m["id"] for m in out["messages"]] == [about_me.id]


# ── the route's door ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_route_takes_a_jwt_only_and_names_the_three_modes():
    from agentvault_registry.routers import chat
    route = next(rt for rt in chat.router.routes if getattr(rt, "path", "").endswith("/conversations/{conversation_id}/wake"))
    assert route.methods == {"PUT"}
    deps = [d.call.__name__ for d in route.dependant.dependencies]
    assert "get_current_actor_for_read" in deps and "get_current_actor_for_read_or_key" not in deps
    assert set(chat.WakeModeSet.model_fields["mode"].annotation.__args__) == set(cs.WAKE_MODES)


# ── the setter, on a real Postgres ─────────────────────────────────────────────────────────────────────────────────────

DB = os.environ.get("MEMBERSHIP_TEST_DB")


@pytest.mark.skipif(not DB, reason="needs a REAL Postgres it may wipe: set MEMBERSHIP_TEST_DB. Skipped, never silently passed.")
def test_a_change_writes_the_mode_and_one_line_and_only_the_owner_signed_in_sets_anothers(monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from agentvault_registry.models import (Base, Conversation, ConversationParticipant, Developer, Organization)

    # the room's door (the live org roster) is not what this test measures: the owner holds the room, the rest are members
    holder = {}

    async def _role(db, org_id, actor):
        if actor.ptype == "developer":
            return "owner" if actor.developer_id == holder.get("owner") else "member"
        return "member"
    monkeypatch.setattr(cs, "actor_org_role", _role)

    async def go():
        engine = create_async_engine(DB)
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        out = {}
        async with maker() as s:
            owner = Developer(name="maintainer", email="owner@test.local", hashed_password="x", is_verified=True)
            other = Developer(name="reader", email="reader@test.local", hashed_password="x", is_verified=True)
            s.add_all([owner, other])
            await s.flush()
            holder["owner"] = owner.id
            s.add(Organization(id="org-w", name="Sessions", slug="sessions-w", owner_id=owner.id))
            await s.flush()
            conv = Conversation(kind="org", org_id="org-w", created_by_ptype="developer", created_by_id=str(owner.id),
                                last_seq=0)
            s.add(conv)
            await s.flush()
            s.add_all([ConversationParticipant(conversation_id=conv.id, ptype="developer", developer_id=owner.id),
                       ConversationParticipant(conversation_id=conv.id, ptype="developer", developer_id=other.id),
                       ConversationParticipant(conversation_id=conv.id, ptype="agent", agent_did=AGENT),
                       ConversationParticipant(conversation_id=conv.id, ptype="agent", agent_did=OTHER)])
            await s.commit()
            cid, oid, xid = conv.id, owner.id, other.id
            signed_in = cs.Actor("developer", developer_id=oid, display_name="maintainer", sent_with="session")
            a, msg, _ = await cs.set_wake_mode(s, cid, signed_in, "on-call", KEY)
            out["first"] = (a["changed"], a["previous"], a["wake_mode"], msg is not None, msg.card if msg else None)
            a, msg, _ = await cs.set_wake_mode(s, cid, signed_in, "on-call", KEY)
            out["again"] = (a["changed"], msg)
            refusals = []
            for actor, member, mode in (
                    (cs.Actor("developer", developer_id=oid, display_name="m", sent_with="api_key"), KEY, "off"),
                    (cs.Actor("developer", developer_id=xid, display_name="r", sent_with="session"), KEY, "off"),
                    (cs.Actor("agent", agent_did=OTHER, display_name="o", sent_with="agent"), KEY, "off"),
                    (signed_in, "agt:did:theprotocol:nobody", "off"),
                    (signed_in, KEY, "sleep")):
                try:
                    await cs.set_wake_mode(s, cid, actor, mode, member)
                    refusals.append(None)
                except cs.ChatError as e:
                    refusals.append(e.status_code)
            out["refusals"] = refusals
            me = cs.Actor("agent", agent_did=AGENT, display_name="waiting-agent", sent_with="agent")
            a, msg, _ = await cs.set_wake_mode(s, cid, me, "off")           # its own, with its own token
            out["own"] = (a["changed"], a["member"], msg.card.get("target") if msg else None)
            rows = (await s.execute(text(
                "SELECT agent_did, wake_mode FROM conversation_participants WHERE conversation_id = :c AND ptype = 'agent' "
                "ORDER BY agent_did"), {"c": cid})).all()
            out["modes"] = {r[0]: r[1] for r in rows}
            out["lines"] = (await s.execute(text(
                "SELECT count(*) FROM chat_messages WHERE conversation_id = :c AND body = 'room.wake'"), {"c": cid})).scalar()
            members = await cs.room_members(s, cid, signed_in)
            out["sheet"] = ({m["key"]: m["wake_mode"] for m in members["members"] if m["ptype"] == "agent"},
                            members["can_set_wake"])
        await engine.dispose()
        return out

    out = asyncio.run(go())
    changed, previous, mode, has_line, card = out["first"]
    assert (changed, previous, mode, has_line) == (True, "listen", "on-call", True)
    assert card["action"] == "wake" and card["value"] == "on-call" and card["target"] == KEY
    assert out["again"] == (False, None)                          # nothing to change, no line
    assert out["refusals"] == [403, 403, 403, 404, 422]
    assert out["own"] == (True, KEY, KEY)
    assert out["modes"] == {AGENT: "off", OTHER: "listen"}
    assert out["lines"] == 2
    assert out["sheet"] == ({KEY: "off", OTHER_KEY: "listen"}, True)
