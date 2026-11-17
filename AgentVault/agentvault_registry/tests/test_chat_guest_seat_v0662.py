"""V0662 (OurChat lane, order gwo_0fda63bcceb5718a54990b74, the organizations package's item 8): a guest seat in an org's room.

The organization's owner or an admin seats ONE named principal (an agent by DID, a developer by id) as a guest of the
organization's room. A guest reads and posts in that one room and gains nothing else of the organization; they are listed in
their thread list and unread count; they leave at any time; the owner or an admin removes them at any time. The §ORGLEAK
rule (a seat is never derived from a membership, nor a membership from a seat): the live organization table still decides a
MEMBER on every touch; the flag on the participant row decides only whether a seat remains when there is no membership; the
org-removal statement leaves a guest's row alone, so a removed member who is also a guest keeps only the guest seat.
Measured over real (SQLite) rows through the real chat router. Every case fails on bca169627 (the lane before this slice),
where the column, the routes and the rules module do not exist, except the ones marked control.
"""
from __future__ import annotations

import asyncio
import re
import sys
import types
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry import models
from agentvault_registry.background_tasks import leader
from agentvault_registry.database import get_db
from agentvault_registry.routers import chat as chat_router
from agentvault_registry.routers import organizations as org_router
from agentvault_registry.security import get_current_actor_for_read
from agentvault_registry.services import chat_guests as cg
from agentvault_registry.services import chat_service as cs
from tests._sqlite_db import sqlite_db

ORG, ROOM = "org-sessions", "room-sessions"
ORG2, ROOM2 = "org-quantum", "room-quantum"
OWNER, ADMIN, MEMBER, OUTSIDER, GUESTDEV, EXMEMBER = 6, 8, 7, 9, 10, 11
SESSION = "did:theprotocol:eu.test:quantum-session"          # the guest agent: belongs to ORG2, not to ORG
HOMEAGENT = "did:theprotocol:eu.test:session-lead"           # ORG's own agent
CASES = []


def run(coro):
    return asyncio.run(coro)


class _Manager:
    def __init__(self):
        self.sent = []

    async def broadcast_to_subscribers(self, topic, envelope):
        self.sent.append((topic, envelope))

    async def wake_chat(self, keys):
        return None


@pytest.fixture(autouse=True)
def _fresh_rate_counts():
    cs._LOCAL_RL.clear()
    yield
    cs._LOCAL_RL.clear()


@pytest.fixture()
def env(monkeypatch):
    async def _no_redis():
        return None
    monkeypatch.setattr(leader, "get_redis", _no_redis)
    mgr = _Manager()
    ws = types.ModuleType("agentvault_registry.routers.websocket")
    ws.manager = mgr
    monkeypatch.setitem(sys.modules, ws.__name__, ws)

    async def _names(db, keys):
        return {k: k for k in keys}
    monkeypatch.setattr(cs, "display_names", _names)

    async def _owners(db, dids):
        return {d: OWNER for d in dids}
    monkeypatch.setattr(cs, "agent_owner_map", _owners)
    db = sqlite_db(models.Developer, models.Organization, models.OrganizationLogo, models.OrganizationMember, models.Agent,
                   models.Conversation, models.ConversationParticipant, models.ChatMessage, models.ChatBlock,
                   models.ChatReaction, models.ChatPin, models.ChatMessageEdit, models.ChatBoardRevision)
    s = db.sync
    # the list and unread queries read organizations.chat_enabled, a column the model does not map (the migrations add it)
    s.execute(__import__('sqlalchemy').text('ALTER TABLE organizations ADD COLUMN chat_enabled BOOLEAN NOT NULL DEFAULT 1'))
    for i in (OWNER, ADMIN, MEMBER, OUTSIDER, GUESTDEV, EXMEMBER):
        s.add(models.Developer(id=i, name=f"dev{i}", email=f"d{i}@example.test", hashed_password="x"))
    s.flush()
    s.add(models.Organization(id=ORG, name="TheProtocol Sessions", slug="sessions", owner_id=OWNER, is_active=True))
    s.add(models.Organization(id=ORG2, name="TheProtocol Quantum", slug="quantum", owner_id=GUESTDEV, is_active=True))
    s.flush()
    for i, (org, dev, role, active) in enumerate(((ORG, OWNER, "owner", True), (ORG, ADMIN, "admin", True), (ORG, MEMBER, "member", True),
                                                  (ORG, EXMEMBER, "member", False), (ORG2, GUESTDEV, "owner", True))):
        s.add(models.OrganizationMember(id=f"om-{i}", organization_id=org, developer_id=dev, role=role, is_active=active))
    s.add(models.Agent(did=HOMEAGENT, client_id="c-home", hashed_client_secret="x", creator_developer_id=OWNER, organization_id=ORG, status="active"))
    s.add(models.Agent(did=SESSION, client_id="c-sess", hashed_client_secret="x", creator_developer_id=GUESTDEV, organization_id=ORG2, status="active"))
    for room, org, title in ((ROOM, ORG, "TheProtocol Sessions"), (ROOM2, ORG2, "TheProtocol Quantum")):
        s.add(models.Conversation(id=room, kind="org", org_id=org, title=title, created_by_ptype="developer", created_by_id=str(OWNER),
                                  dm_pair_key=f"org|{org}"))
    for room, dev in ((ROOM, OWNER), (ROOM, ADMIN), (ROOM, MEMBER), (ROOM2, GUESTDEV)):
        s.add(models.ConversationParticipant(id=f"p-{room}-{dev}", conversation_id=room, ptype="developer", developer_id=dev, state="active"))
    s.commit()
    s.connection().connection.driver_connection.create_function(
        "now", 0, lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"))
    s.connection().connection.driver_connection.create_function("GREATEST", 2, lambda a, b: max(a or 0, b or 0))   # the list and unread queries are Postgres


    class _BoolAnd:
        def __init__(self):
            self.v = True

        def step(self, x):
            self.v = self.v and bool(x)

        def finalize(self):
            return 1 if self.v else 0
    s.connection().connection.driver_connection.create_aggregate("BOOL_AND", 1, _BoolAnd)
    app = FastAPI()
    app.include_router(chat_router.router)

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    who = {"as": ("developer", OWNER)}

    def caller():
        kind, ident = who["as"]
        if kind == "developer":
            return {"kind": "developer", "developer_id": ident, "developer": types.SimpleNamespace(id=ident, name=f"dev{ident}")}
        return {"kind": "agent", "agent_did": ident, "agent": types.SimpleNamespace(name=ident)}
    from agentvault_registry import security
    for dep in (get_current_actor_for_read, getattr(security, "get_current_actor_for_read_or_key", None)):
        if dep:
            app.dependency_overrides[dep] = caller
    import contextlib
    import agentvault_registry.database as D

    @contextlib.asynccontextmanager
    async def _ctx():
        yield db
    monkeypatch.setattr(D, "get_db_context", _ctx)
    return types.SimpleNamespace(app=app, db=db, who=who, mgr=mgr)


async def _call(env, method, path, who=("developer", OWNER), **kw):
    env.who["as"] = who
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://t", timeout=30) as c:
        r = await c.request(method, path, **kw)
    await asyncio.sleep(0.03)
    return r


GUESTS = f"/api/v1/chat/conversations/{ROOM}/guests"
AS_SESSION = ("agent", SESSION)


def _seat(env, who=("developer", OWNER), **body):
    return _call(env, "POST", GUESTS, who=who, json=body or {"agent_did": SESSION})


def _read(env, who, room=ROOM):
    return _call(env, "GET", f"/api/v1/chat/conversations/{room}/messages", who=who)


def _say(env, who, text, room=ROOM, ref="guest-000001"):
    return _call(env, "POST", f"/api/v1/chat/conversations/{room}/messages", who=who, json={"kind": "text", "body": text, "client_ref": ref})


# ── the pure rules ─────────────────────────────────────────────────────────────────────────────────────────────

def _why(**kw):
    base = dict(actor_org_role="owner", is_org_room=True, target_is_live_member=False, target_is_self=False, already_guest=False, guests_now=0)
    base.update(kw)
    return cg.seating_refusal(**base)


def test_the_seating_rules_each_name_their_reason():
    assert _why() is None and _why(actor_org_role="admin") is None                                   # control
    assert "organization's room" in _why(is_org_room=False)
    for role in ("member", None):
        assert "owners and admins" in _why(actor_org_role=role)
    assert "your own" in _why(target_is_self=True)
    assert "already a member" in _why(target_is_live_member=True)
    assert "20 guests" in _why(guests_now=cg.MAX_GUESTS)
    assert _why(guests_now=cg.MAX_GUESTS, already_guest=True) is None                                # renewing one of them


# ── a guest in the room, and nowhere else ──────────────────────────────────────────────────────────────────────

def test_a_guest_agent_reads_and_posts_in_this_room_and_only_this_room(env):
    async def go():
        assert (await _read(env, AS_SESSION)).status_code == 403                                      # control: before the seat
        r = await _seat(env)
        assert r.status_code == 201, r.text
        assert r.json()["guest"]["key"] == cs.principal_key("agent", SESSION) and r.json()["guest"]["guest"] is True
        assert (await _say(env, ("developer", OWNER), "welcome")).status_code == 201
        got = await _read(env, AS_SESSION)
        assert got.status_code == 200 and [m["body"] for m in got.json()["messages"]] == ["welcome"]
        assert (await _say(env, AS_SESSION, "thanks for having us", ref="guest-000002")).status_code == 201
        # nothing else of the organization: no standing, no other room, no opening the room as a member
        assert await cs.actor_org_role(env.db, ORG, cs.Actor("agent", agent_did=SESSION)) is None
        assert (await _read(env, AS_SESSION, room=ROOM2)).status_code == 200                           # its OWN organization's room: its own
        other = await _read(env, ("developer", OWNER), room=ROOM2)
        assert other.status_code == 403                                                                  # the owner has no seat there either
        with pytest.raises(cs.ChatError) as e:
            await cs.open_org_room(env.db, cs.Actor("agent", agent_did=SESSION), ORG)
        assert e.value.status_code == 403
    run(go())


def test_a_guest_developer_is_seated_by_id_and_the_room_counts_in_their_unread(env):
    async def go():
        outsider = cs.Actor("developer", developer_id=OUTSIDER)
        assert (await cs.unread_total(env.db, outsider)) == {"messages": 0, "threads": 0}                # before the seat
        r = await _seat(env, developer_id=OUTSIDER)
        assert r.status_code == 201, r.text
        await _say(env, ("developer", OWNER), "hello outsider")
        assert (await cs.unread_total(env.db, outsider)) == {"messages": 1, "threads": 1}                # the room is theirs to count
        assert (await _read(env, ("developer", OUTSIDER))).status_code == 200
        # the thread LIST asks the same question (the same predicate, written beside it): both carry the seat's clause
        src = Path(cs.__file__).read_text(encoding="utf-8")
        assert src.count("OR p.guest_seat = true") == 4                                                    # two queries, a developer and an agent each
    run(go())


def test_only_the_owner_and_an_admin_seat_and_remove(env):
    async def go():
        for who in (("developer", MEMBER), ("developer", OUTSIDER), ("developer", EXMEMBER), AS_SESSION):
            r = await _seat(env, who=who)
            assert r.status_code == 403, (who, r.text)
        assert env.db.sync.query(models.ConversationParticipant).filter_by(guest_seat=True).count() == 0
        assert (await _seat(env, who=("developer", ADMIN))).status_code == 201                          # an admin may
        key = cs.principal_key("agent", SESSION)
        assert (await _call(env, "DELETE", f"{GUESTS}/{key}", who=("developer", MEMBER))).status_code == 403
        assert (await _call(env, "DELETE", f"{GUESTS}/{key}", who=AS_SESSION)).status_code == 403          # nor may a guest remove a guest
        assert (await _call(env, "DELETE", f"{GUESTS}/{key}", who=("developer", ADMIN))).status_code == 200
    run(go())


def test_seating_refuses_a_member_yourself_nobody_two_names_and_a_twentyfirst(env):
    async def go():
        assert (await _seat(env, developer_id=MEMBER)).status_code == 409                                 # a live member: the room is theirs
        assert (await _seat(env, agent_did=HOMEAGENT)).status_code == 409                                 # the organization's own agent
        assert (await _seat(env, developer_id=OWNER)).status_code == 409                                  # yourself
        assert (await _seat(env, developer_id=999)).status_code == 404                                    # nobody
        assert (await _seat(env, agent_did="did:theprotocol:eu.test:ghost")).status_code == 404
        assert (await _call(env, "POST", GUESTS, json={"developer_id": 9, "agent_did": SESSION})).status_code == 422
        assert (await _call(env, "POST", GUESTS, json={})).status_code == 422
        s = env.db.sync
        for i in range(cg.MAX_GUESTS):
            did = f"did:theprotocol:eu.test:g{i}"
            s.add(models.Agent(did=did, client_id=f"cg{i}", hashed_client_secret="x", creator_developer_id=GUESTDEV, status="active"))
            s.flush()
            s.add(models.ConversationParticipant(id=f"pg{i}", conversation_id=ROOM, ptype="agent", agent_did=did, state="active", guest_seat=True))
        s.commit()
        r = await _seat(env, developer_id=OUTSIDER)
        assert r.status_code == 409 and "20 guests" in r.text
        assert (await _seat(env, agent_did="did:theprotocol:eu.test:g3")).status_code == 201             # renewing one that has a seat
    run(go())


# ── the §ORGLEAK rules ─────────────────────────────────────────────────────────────────────────────────────────

def test_a_guest_leaves_at_any_time_and_the_seat_goes_with_them(env):
    async def go():
        await _seat(env)
        assert (await _call(env, "POST", f"/api/v1/chat/conversations/{ROOM}/leave", who=AS_SESSION)).status_code == 200
        row = env.db.sync.query(models.ConversationParticipant).filter_by(conversation_id=ROOM, agent_did=SESSION).one()
        env.db.sync.refresh(row)
        assert row.state == "left" and row.guest_seat is False and row.guest_invited_by is None
        assert (await _read(env, AS_SESSION)).status_code == 403                                          # no way back on their own
        assert (await _seat(env)).status_code == 201                                                       # the owner seats them again
        assert (await _read(env, AS_SESSION)).status_code == 200
    run(go())


def test_removing_a_guest_ends_the_seat_at_once_and_leaves_a_member_their_membership(env):
    async def go():
        await _seat(env)
        key = cs.principal_key("agent", SESSION)
        r = await _call(env, "DELETE", f"{GUESTS}/{key}")
        assert r.status_code == 200 and r.json()["guest"] is False and r.json()["still_member"] is False
        assert (await _read(env, AS_SESSION)).status_code == 403
        assert (await _call(env, "DELETE", f"{GUESTS}/{key}")).status_code == 404                          # not a guest any more
        # a member who also holds a seat: only the seat ends
        s = env.db.sync
        p = s.query(models.ConversationParticipant).filter_by(conversation_id=ROOM, developer_id=MEMBER).one()
        p.guest_seat = True
        s.commit()
        r = await _call(env, "DELETE", f"{GUESTS}/dev:{MEMBER}")
        assert r.json()["still_member"] is True
        assert (await _read(env, ("developer", MEMBER))).status_code == 200
    run(go())


def test_the_organizations_removal_leaves_a_guest_row_alone_so_a_removed_member_who_is_also_a_guest_keeps_only_the_seat(env):
    async def go():
        s = env.db.sync
        # the EXACT statement organizations.py runs when a member is removed
        src = Path(org_router.__file__).read_text(encoding="utf-8")
        m = re.search(r'sa_text\("""(\s*UPDATE conversation_participants SET state = \'left\'.*?)"""\)', src, re.S)
        assert m, "the room-detach statement was not found"
        stmt = m.group(1)
        assert "guest_seat = false" in stmt
        # MEMBER also holds a guest seat; EXMEMBER is a plain participant row (no seat); both are removed from the organization
        for dev, seat in ((MEMBER, True), (EXMEMBER, False)):
            row = s.query(models.ConversationParticipant).filter_by(conversation_id=ROOM, developer_id=dev).first()
            if row is None:
                s.add(models.ConversationParticipant(id=f"p-x{dev}", conversation_id=ROOM, ptype="developer", developer_id=dev, state="active", guest_seat=seat))
            else:
                row.guest_seat = seat
        s.query(models.OrganizationMember).filter_by(organization_id=ORG, developer_id=MEMBER).update({"is_active": False})
        s.commit()
        from sqlalchemy import text
        for dev in (MEMBER, EXMEMBER):
            s.execute(text(stmt), {"d": dev, "o": ORG})
        s.commit()
        s.expire_all()
        states = {dev: s.query(models.ConversationParticipant).filter_by(conversation_id=ROOM, developer_id=dev).one() for dev in (MEMBER, EXMEMBER)}
        assert states[MEMBER].state == "active" and states[MEMBER].guest_seat is True                       # keeps the seat
        assert states[EXMEMBER].state == "left"                                                              # control: a plain member goes
        # and the room treats them for what they are now: a guest reads and posts, a plain ex-member is refused
        assert (await _read(env, ("developer", MEMBER))).status_code == 200
        assert (await _say(env, ("developer", MEMBER), "still here as a guest", ref="guest-000009")).status_code == 201
        assert await cs.actor_org_role(env.db, ORG, cs.Actor("developer", developer_id=MEMBER)) is None
        assert (await _read(env, ("developer", EXMEMBER))).status_code == 403
    run(go())


def test_a_seat_is_never_derived_from_a_membership_and_a_stale_row_without_the_flag_is_still_refused(env):
    async def go():
        # control, the §ORGLEAK measurement: a participant row from before a removal is not authority
        s = env.db.sync
        s.add(models.ConversationParticipant(id="p-stale", conversation_id=ROOM, ptype="developer", developer_id=EXMEMBER, state="active"))
        s.commit()
        r = await _read(env, ("developer", EXMEMBER))
        assert r.status_code == 403 and "not an active member" in r.text
        # and a live member who was never seated gains no guest flag by being read
        assert (await _read(env, ("developer", MEMBER))).status_code == 200
        env.db.sync.expire_all()
        assert env.db.sync.query(models.ConversationParticipant).filter_by(conversation_id=ROOM, developer_id=MEMBER).one().guest_seat is False
    run(go())


def test_a_guest_cannot_post_where_only_the_organizations_owners_and_admins_may(env):
    async def go():
        await _seat(env)
        conv = env.db.sync.get(models.Conversation, ROOM)
        conv.mode = "announce"
        env.db.sync.commit()
        r = await _say(env, AS_SESSION, "may we?", ref="guest-000007")
        assert r.status_code == 403 and "announce" in r.text
        assert (await _read(env, AS_SESSION)).status_code == 200                                           # reading stays theirs
    run(go())
