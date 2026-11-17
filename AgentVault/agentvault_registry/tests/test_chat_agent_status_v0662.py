"""V0662 (OurChat lane, the batch's item 11, order gwo_6b2cbdf6e982d1662161e802): agent status in a room, the session board.

The room's desk reports each session's state, wake mode, last wake and wakes in 24 hours about every 60 seconds; the registry
keeps the last report per session and shows it to the organization's owners and admins only. It never guesses: a report not
refreshed for 5 minutes reads `unknown`, and then shows no wake mode and no count. Only an owner or admin (or an agent of one)
writes it; a session the room does not hold is skipped; an invalid entry is refused by name. Measured through the real chat
router over real (SQLite) rows. Every case fails on af1a39d5c (the lane before this slice), where the routes, the table and the
rules module do not exist, except the ones marked control.
"""
from __future__ import annotations

import asyncio
import datetime
import sys
import types

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry import models
from agentvault_registry.background_tasks import leader
from agentvault_registry.database import get_db
from agentvault_registry.routers import chat as chat_router
from agentvault_registry.security import get_current_actor_for_read
from agentvault_registry.services import chat_service as cs
from agentvault_registry.services import chat_agent_status as css
from tests._sqlite_db import sqlite_db

ORG, ROOM = "org-sessions", "room-sessions"
ORG2, ROOM2 = "org-quantum", "room-quantum"
OWNER, ADMIN, MEMBER, OUTSIDER, GUESTDEV, EXMEMBER = 6, 8, 7, 9, 10, 11
SESSION = "did:theprotocol:eu.test:quantum-session"
HOMEAGENT = "did:theprotocol:eu.test:session-lead"
DESK = "did:theprotocol:eu.test:session-watch"            # the desk: an agent created by the organization's OWNER
STRAY = "did:theprotocol:eu.test:stray"                   # an agent of a plain MEMBER (no operator standing)
T0 = datetime.datetime(2026, 11, 13, 12, 0, tzinfo=datetime.timezone.utc)


def run(coro):
    return asyncio.run(coro)


class _Manager:
    def __init__(self):
        self.sent = []

    async def broadcast_to_subscribers(self, topic, envelope):
        self.sent.append((topic, envelope))

    async def wake_chat(self, keys):
        return None


# ── the pure rules ─────────────────────────────────────────────────────────────────────────────────────────────

def test_a_report_is_fresh_for_five_minutes_and_then_unknown():
    assert css.effective_state("active", T0, T0 + datetime.timedelta(seconds=css.STALE_AFTER_S)) == "active"
    assert css.effective_state("active", T0, T0 + datetime.timedelta(seconds=css.STALE_AFTER_S + 1)) == "unknown"
    assert css.effective_state("paused", T0.replace(tzinfo=None), T0 + datetime.timedelta(seconds=5)) == "paused"       # naive: UTC
    for bad in (None, "", "asleep", "unknown"):
        assert css.effective_state(bad, T0, T0) == "unknown"
    assert css.effective_state("active", None, T0) == "unknown"


def test_an_entry_is_checked_and_each_fault_is_named():
    ok, why = css.clean_entry({"key": "agt:did:x", "name": "  The   desk ", "state": "active", "wake_mode": "on-call",
                               "last_wake_at": "2026-11-13T12:00:00Z", "wakes_24h": 7})
    assert why is None and ok["name"] == "The desk" and ok["wakes_24h"] == 7 and ok["last_wake_at"].tzinfo is not None
    for bad, frag in (({"key": "x", "state": "active"}, "key"), ({"key": "agt:x", "state": "asleep"}, "state"),
                      ({"key": "agt:x", "state": "active", "wake_mode": "loud"}, "wake_mode"),
                      ({"key": "agt:x", "state": "active", "last_wake_at": "yesterday"}, "last_wake_at"),
                      ({"key": "agt:x", "state": "active", "wakes_24h": -1}, "wakes_24h"),
                      ({"key": "agt:x", "state": "active", "wakes_24h": "many"}, "wakes_24h"), ("nope", "object")):
        got, why = css.clean_entry(bad)
        assert got is None and frag in why, (bad, why)
    assert css.clean_entry({"key": "agt:x", "state": "unreachable"})[0]["wakes_24h"] == 0                              # defaults


def test_a_report_drops_a_repeat_and_cuts_at_sixty():
    good, bad = css.clean_report([{"key": "agt:a", "state": "active"}, {"key": "agt:a", "state": "paused"}, {"key": "x", "state": "active"}])
    assert [g["key"] for g in good] == ["agt:a"] and len(bad) == 2
    many = [{"key": f"agt:{i}", "state": "active"} for i in range(css.MAX_ENTRIES + 5)]
    good, bad = css.clean_report(many)
    assert len(good) == css.MAX_ENTRIES and any("dropped" in b for b in bad)
    assert css.clean_report("not a list") == ([], ["entries is a list"])


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
                   models.ChatReaction, models.ChatPin, models.ChatMessageEdit, models.ChatBoardRevision, models.ChatAgentStatus)
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



BOARD = f"/api/v1/chat/conversations/{ROOM}/agent-status"
HOME = cs.principal_key("agent", HOMEAGENT)
SKEY = cs.principal_key("agent", SESSION)


def _seed_agents(env):
    s = env.db.sync
    s.add(models.Agent(did=DESK, client_id="c-desk", hashed_client_secret="x", creator_developer_id=OWNER, organization_id=ORG, status="active"))
    s.add(models.Agent(did=STRAY, client_id="c-stray", hashed_client_secret="x", creator_developer_id=MEMBER, organization_id=ORG, status="active"))
    for did in (HOMEAGENT, SESSION):
        s.add(models.ConversationParticipant(id=f"pa-{did[-6:]}", conversation_id=ROOM, ptype="agent", agent_did=did, state="active"))
    s.commit()


def _owners(monkeypatch):
    owners = {DESK: OWNER, STRAY: MEMBER}                          # the desk is the organization's owner's; STRAY belongs to a plain member

    async def _o(db, dids):
        return {d: owners[d] for d in dids if d in owners}
    monkeypatch.setattr(cs, "agent_owner_map", _o)


def _report(env, entries, who=("developer", OWNER)):
    return _call(env, "PUT", BOARD, who=who, json={"entries": entries})


def _entry(key=HOME, **kw):
    base = {"key": key, "name": "session-lead", "state": "active", "wake_mode": "listen", "wakes_24h": 12, "last_wake_at": "2026-11-13T12:00:00+00:00"}
    base.update(kw)
    return base


def test_the_desk_reports_and_the_owner_reads_the_busiest_first(env, monkeypatch):
    _seed_agents(env)
    _owners(monkeypatch)

    async def go():
        r = await _report(env, [_entry(), _entry(SKEY, name="quantum-session", wakes_24h=40, state="paused", wake_mode="off")], who=("agent", DESK))
        assert r.status_code == 200, r.text
        assert r.json() == {"kept": 2, "skipped": 0, "refused": []}
        got = (await _call(env, "GET", BOARD, who=("developer", OWNER))).json()
        assert [s["name"] for s in got["sessions"]] == ["quantum-session", "session-lead"]               # the busiest first
        top = got["sessions"][0]
        assert top["state"] == "paused" and top["wake_mode"] == "off" and top["wakes_24h"] == 40 and top["age_s"] is not None
        assert got["stale_after_s"] == 300
        r = await _report(env, [_entry(wakes_24h=13)], who=("agent", DESK))                                 # the next report replaces
        assert r.json()["kept"] == 1
        rows = env.db.sync.query(models.ChatAgentStatus).filter_by(conversation_id=ROOM).all()
        assert len(rows) == 2 and {x.member_key: x.wakes_24h for x in rows}[HOME] == 13
    run(go())


def test_a_report_not_refreshed_for_five_minutes_reads_unknown_and_shows_no_count(env, monkeypatch):
    _seed_agents(env)
    _owners(monkeypatch)

    async def go():
        await _report(env, [_entry()])
        fresh = (await _call(env, "GET", BOARD)).json()["sessions"][0]
        assert fresh["state"] == "active" and fresh["wakes_24h"] == 12                                        # control: fresh
        row = env.db.sync.query(models.ChatAgentStatus).one()
        row.reported_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=css.STALE_AFTER_S + 30)
        env.db.sync.commit()
        old = (await _call(env, "GET", BOARD)).json()["sessions"][0]
        assert old["state"] == "unknown" and old["wake_mode"] is None and old["wakes_24h"] is None
        assert old["age_s"] >= css.STALE_AFTER_S
    run(go())


def test_only_an_owner_an_admin_or_an_agent_of_one_writes_and_reads(env, monkeypatch):
    _seed_agents(env)
    _owners(monkeypatch)

    async def go():
        for who in (("developer", MEMBER), ("developer", OUTSIDER), ("developer", EXMEMBER), ("agent", STRAY), ("agent", SESSION)):
            r = await _report(env, [_entry()], who=who)
            assert r.status_code == 403 and "report agent status" in r.text, who
            assert (await _call(env, "GET", BOARD, who=who)).status_code == 403, who
        assert env.db.sync.query(models.ChatAgentStatus).count() == 0
        assert (await _report(env, [_entry()], who=("developer", ADMIN))).status_code == 200              # an admin may
        assert (await _call(env, "GET", BOARD, who=("developer", ADMIN))).status_code == 200
        assert (await _call(env, "GET", BOARD, who=("agent", DESK))).status_code == 200                  # the owner's agent reads too
    run(go())


def test_an_entry_for_a_session_the_room_does_not_hold_is_skipped_and_an_invalid_one_is_refused_by_name(env, monkeypatch):
    _seed_agents(env)
    _owners(monkeypatch)

    async def go():
        r = await _report(env, [_entry(), _entry("agt:did:theprotocol:eu.test:ghost", name="ghost"), _entry(SKEY, state="asleep")])
        assert r.status_code == 200
        out = r.json()
        assert out["kept"] == 1 and out["skipped"] == 1 and len(out["refused"]) == 1 and "state" in out["refused"][0]
        assert env.db.sync.query(models.ChatAgentStatus).count() == 1
        too_many = [_entry(f"agt:x{i}") for i in range(61)]
        r = await _call(env, "PUT", BOARD, json={"entries": too_many})
        assert r.status_code == 422                                                                          # the body bound
    run(go())


def test_a_direct_thread_has_no_board_and_a_report_wakes_no_one(env, monkeypatch):
    _seed_agents(env)
    _owners(monkeypatch)

    async def go():
        env.db.sync.add(models.Conversation(id="dm-x", kind="dm", created_by_ptype="developer", created_by_id=str(OWNER)))
        env.db.sync.commit()
        r = await _call(env, "GET", "/api/v1/chat/conversations/dm-x/agent-status")
        assert r.status_code == 409 and "organization's room" in r.text and "agent status" in r.text
        sent = len(env.mgr.sent)
        await _report(env, [_entry()], who=("agent", DESK))
        assert len(env.mgr.sent) == sent                                                                      # nothing told, nothing woken
    run(go())
