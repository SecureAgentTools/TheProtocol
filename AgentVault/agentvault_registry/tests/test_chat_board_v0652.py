"""V0652 (ac) (order gwo_2ae43c7789db1e808ea1417f, agentvault2-14, 2026-11-01): a pinned status board per room.

One board per organization's room, kept fresh by the room's owner or the members the owner names, every edit kept.
Measured through the real chat router over real (SQLite) rows: the owner writes it and every member reads it; a member
the owner did not name is refused, one the owner named writes it, and stops counting when it leaves the organization; an
edit written against an older board is refused (nobody overwrites an edit unseen); an edit that changes nothing writes
nothing; the history keeps every edit; only the owner names editors, and only members of the organization; a direct
thread has no board; the room sees each change (the WS envelope), nobody is notified. Every case fails on 05441be31 (the
V0651 recut), where the routes and the columns do not exist.
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
from agentvault_registry.services import chat_board as cb
from agentvault_registry.services import chat_service as cs
from tests._sqlite_db import sqlite_db

ORG = "org-sessions"
ROOM = "room-sessions"
OWNER, MEMBER, LEFT = 6, 7, 8
LEAD = "did:theprotocol:eu.test:session-lead"
STRANGER = "did:theprotocol:eu.test:elsewhere"


def run(coro):
    return asyncio.run(coro)


class _Manager:
    def __init__(self):
        self.sent = []

    async def broadcast_to_subscribers(self, topic, envelope):
        self.sent.append((topic, envelope))

    async def wake_chat(self, keys):
        return None


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
        return {k: {"dev:6": "maintainer", "dev:7": "a member", "agt:" + LEAD.lower(): "session-lead"}.get(k, k)
                for k in keys}
    monkeypatch.setattr(cs, "display_names", _names)

    async def _owners(db, dids):
        return {d: OWNER for d in dids}
    monkeypatch.setattr(cs, "agent_owner_map", _owners)
    db = sqlite_db(models.Developer, models.Organization, models.OrganizationMember, models.Agent, models.Conversation,
                   models.ConversationParticipant, models.ChatMessage, models.ChatBoardRevision, models.ChatBlock)
    s = db.sync
    for i in (OWNER, MEMBER, LEFT):
        s.add(models.Developer(id=i, name=f"dev{i}", email=f"d{i}@example.test", hashed_password="x"))
    s.flush()
    s.add(models.Organization(id=ORG, name="TheProtocol Sessions", slug="sessions", owner_id=OWNER, is_active=True))
    s.flush()
    for i, (dev, role, active) in enumerate(((OWNER, "owner", True), (MEMBER, "member", True), (LEFT, "member", False))):
        s.add(models.OrganizationMember(id=f"om-{i}", organization_id=ORG, developer_id=dev, role=role, is_active=active))
    s.add(models.Agent(did=LEAD, client_id="client-lead", hashed_client_secret="x", creator_developer_id=OWNER,
                       organization_id=ORG, status="active"))
    s.add(models.Conversation(id=ROOM, kind="org", org_id=ORG, title="TheProtocol Sessions", created_by_ptype="developer",
                              created_by_id=str(OWNER), dm_pair_key=f"org|{ORG}"))
    s.add(models.Conversation(id="dm-1", kind="dm", created_by_ptype="developer", created_by_id=str(OWNER)))
    s.add(models.ConversationParticipant(id="p-dm", conversation_id="dm-1", ptype="developer", developer_id=OWNER,
                                         state="active"))
    s.commit()

    import contextlib
    import agentvault_registry.database as D

    @contextlib.asynccontextmanager
    async def _ctx():
        yield db
    monkeypatch.setattr(D, "get_db_context", _ctx)
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
    return types.SimpleNamespace(app=app, db=db, who=who, mgr=mgr)


async def _call(env, method, path, who=("developer", OWNER), **kw):
    env.who["as"] = who
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://t", timeout=30) as c:
        r = await c.request(method, path, **kw)
    await asyncio.sleep(0.05)
    return r


def _put(env, text, base, who=("developer", OWNER)):
    return _call(env, "PUT", f"/api/v1/chat/conversations/{ROOM}/board", who=who, json={"text": text, "base_rev": base})


def test_the_owner_writes_it_and_every_member_reads_it(env):
    async def go():
        r = await _put(env, "**Release:** V0651 rolls at 05:00Z\n- open: (ac), (q)", 0)
        assert r.status_code == 200, r.text
        b = r.json()["board"]
        assert r.json()["changed"] is True and b["rev"] == 1 and b["can_edit"] is True
        assert b["updated_by"]["name"] == "maintainer" and b["editors"] == []
        m = (await _call(env, "GET", f"/api/v1/chat/conversations/{ROOM}/board", who=("developer", MEMBER))).json()
        assert m["text"].startswith("**Release:** V0651") and m["rev"] == 1
        assert m["can_edit"] is False and "editors" not in m           # a member reads; the editors are the owner's
        ups = [e for _, e in env.mgr.sent if e["type"] == "chat.board_updated"]
        assert ups and ups[0]["data"]["board"]["rev"] == 1 and "can_edit" not in ups[0]["data"]["board"]
    run(go())


def test_a_member_the_owner_did_not_name_is_refused(env):
    async def go():
        r = await _put(env, "mine now", 0, who=("developer", MEMBER))
        assert r.status_code == 403 and "the room's owner, or a member the owner named" in r.text
        assert env.db.sync.query(models.ChatBoardRevision).count() == 0
    run(go())


def test_a_named_agent_keeps_it_until_it_leaves_the_organization(env):
    async def go():
        r = await _call(env, "PUT", f"/api/v1/chat/conversations/{ROOM}/board/editors", json={"editors": ["agt:" + LEAD]})
        assert r.status_code == 200, r.text
        assert r.json()["editors"] == [{"key": "agt:" + LEAD.lower(), "name": "session-lead"}]
        r = await _put(env, "status from the lead", 0, who=("agent", LEAD))
        assert r.status_code == 200, r.text
        assert r.json()["board"]["can_edit"] is True
        a = env.db.sync.query(models.Agent).filter_by(did=LEAD).one()
        a.organization_id = None                      # the agent left the organization
        env.db.sync.commit()
        r = await _put(env, "still mine?", 1, who=("agent", LEAD))
        assert r.status_code in (403, 404), r.text     # not a member of the room any more, nor an editor
    run(go())


def test_an_edit_against_an_older_board_is_refused(env):
    async def go():
        assert (await _put(env, "first", 0)).status_code == 200
        assert (await _put(env, "second", 1)).status_code == 200
        r = await _put(env, "written against the first", 1)
        assert r.status_code == 409 and "now revision 2" in r.text
        same = await _put(env, "second", 2)
        assert same.status_code == 200 and same.json()["changed"] is False and same.json()["board"]["rev"] == 2
    run(go())


def test_the_history_keeps_every_edit(env):
    async def go():
        await _put(env, "one", 0)
        await _put(env, "two", 1)
        h = (await _call(env, "GET", f"/api/v1/chat/conversations/{ROOM}/board/history", who=("developer", MEMBER))).json()
        assert [(r["rev"], r["text"], r["by"]["name"]) for r in h["revisions"]] == [(1, "one", "maintainer"), (2, "two", "maintainer")]
    run(go())


def test_only_the_owner_names_editors_and_only_the_organizations(env):
    async def go():
        r = await _call(env, "PUT", f"/api/v1/chat/conversations/{ROOM}/board/editors", who=("developer", MEMBER),
                        json={"editors": ["dev:7"]})
        assert r.status_code == 403 and "the room's owner names" in r.text
        r = await _call(env, "PUT", f"/api/v1/chat/conversations/{ROOM}/board/editors", json={"editors": ["dev:8"]})
        assert r.status_code == 422 and "does not belong to this organization" in r.text     # left
        r = await _call(env, "PUT", f"/api/v1/chat/conversations/{ROOM}/board/editors", json={"editors": ["agt:" + STRANGER]})
        assert r.status_code == 422
        r = await _call(env, "PUT", f"/api/v1/chat/conversations/{ROOM}/board/editors", json={"editors": ["not a key"]})
        assert r.status_code == 422 and "is not a principal key" in r.text
        r = await _call(env, "PUT", f"/api/v1/chat/conversations/{ROOM}/board/editors", json={"editors": ["dev:7", "DEV:7"]})
        assert r.status_code == 200 and [e["key"] for e in r.json()["editors"]] == ["dev:7"]
        assert (await _put(env, "the member's turn", 0, who=("developer", MEMBER))).status_code == 200
    run(go())


def test_a_direct_thread_has_no_board_and_a_long_text_is_refused(env):
    async def go():
        r = await _call(env, "PUT", "/api/v1/chat/conversations/dm-1/board", json={"text": "x", "base_rev": 0})
        assert r.status_code == 409 and "belongs to an organization's room" in r.text
        r = await _put(env, "x" * 4001, 0)
        assert r.status_code == 422
    run(go())


def test_the_editors_list_is_normalized_and_bounded():
    assert cb.normalize_editors(["dev:7", "AGT:did:theprotocol:eu:x", "dev:7"]) == (["dev:7", "agt:did:theprotocol:eu:x"], None)
    assert cb.normalize_editors(None) == ([], None)
    assert cb.normalize_editors("dev:7")[1] is not None
    assert "at most 20" in cb.normalize_editors([f"dev:{i}" for i in range(21)])[1]
    assert cb.board_text_refusal("") is None and cb.board_text_refusal(None) is not None


def test_the_thread_read_carries_the_board_and_whether_the_reader_keeps_it(env):
    async def go():
        await _put(env, "V0651 at 05:00Z", 0)
        owner = (await _call(env, "GET", f"/api/v1/chat/conversations/{ROOM}/messages")).json()
        assert owner["room"]["board"]["text"] == "V0651 at 05:00Z" and owner["room"]["board"]["can_edit"] is True
        member = (await _call(env, "GET", f"/api/v1/chat/conversations/{ROOM}/messages", who=("developer", MEMBER))).json()
        assert member["room"]["board"]["rev"] == 1 and member["room"]["board"]["can_edit"] is False
    run(go())
