"""V0651 (t) (2026-10-31, agentvault2-14): a chat wait that wakes only when I am named.

Order gwo_cddfbd743842eb65906ef8ab. GET /api/v1/chat/sync takes `for=me`: the answer holds only what reaches the caller in
particular (a mention of it, @all or @everyone, the room owner's message, any message in a direct conversation, an
approval card it asked for or may decide; never its own), everything else stays on the server, and a `wait` ends only on
such a message. Its next_cursor continues the filtered stream; plain_cursor is where it started.

The acceptance, measured through FastAPI on the real chat router over real (SQLite) rows, as V0650 (g)'s own tests do: a
message naming another agent does not end the wait; @me, @all, the owner's message, a direct message and an approval card
each end it within a second; the cursor loses nothing. Cases marked BASE fail on 48d07ecf2 (V0650), where FastAPI drops
the unknown `for` and the wait ends on any message, and neither reaches_me nor syncChat exists.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time
import types

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry import models
from agentvault_registry.background_tasks import leader
from agentvault_registry.database import get_db
from agentvault_registry.routers import chat as chat_router
from agentvault_registry.routers import websocket as WS
from agentvault_registry.services import chat_service as cs
from tests._sqlite_db import sqlite_db
from tests.test_chat_sync_wait import LoggedDb, _read_deps

AGENT = "did:theprotocol:eu.test:waiting-agent"
SENDER = "did:theprotocol:eu.test:sender"
OTHER = "did:theprotocol:eu.test:other"
ROOM = "conv-room"
DM = "conv-dm"
ORG = "org-sessions"
OWNER = 6
KEY = "agt:" + AGENT.lower()
_SEQ = {"n": 0}


def _seed():
    db = sqlite_db(models.Developer, models.Agent, models.Organization, models.OrganizationMember,
                   models.Conversation, models.ConversationParticipant, models.ChatMessage, models.ChatApproval)
    s = db.sync
    s.add(models.Organization(id=ORG, name="Sessions", slug="sessions", owner_id=OWNER))
    s.add(models.Conversation(id=ROOM, kind="org", org_id=ORG, created_by_ptype="developer", created_by_id=str(OWNER)))
    s.add(models.Conversation(id=DM, kind="dm", created_by_ptype="agent", created_by_id=SENDER))
    for i, (conv, did) in enumerate([(ROOM, AGENT), (ROOM, SENDER), (ROOM, OTHER), (DM, AGENT), (DM, SENDER)]):
        s.add(models.ConversationParticipant(id=f"p-{i}", conversation_id=conv, ptype="agent", agent_did=did,
                                             state="active"))
    now = dt.datetime.now(dt.timezone.utc)
    for aid, did in (("apr_mine", AGENT), ("apr_other", OTHER)):
        s.add(models.ChatApproval(id=aid, conversation_id=ROOM, org_id=ORG, requester_agent_did=did,
                                  client_ref=f"ref-{aid}", title=f"ask {aid}", facts={"approval_id": aid},
                                  facts_digest="d" * 64, status="pending", expires_at=now + dt.timedelta(hours=1)))
    s.commit()
    return db


def _post(db, conv, *, sender=SENDER, ptype="agent", body="hello", card=None, mentions=None, kind=None):
    _SEQ["n"] += 1
    n = _SEQ["n"]
    m = models.ChatMessage(id=f"m-{n}", conversation_id=conv, seq=n, sender_ptype=ptype, sender_id=sender,
                           kind=kind or ("card" if card else "text"), body=body, card=card, mentions=mentions,
                           client_ref=f"c-{conv}-{n}", created_at=cs.message_clock())
    db.sync.add(m)
    db.sync.commit()
    return m


@pytest.fixture()
async def env(monkeypatch):
    async def _no_redis():
        return None
    monkeypatch.setattr(leader, "get_redis", _no_redis)
    monkeypatch.setattr(WS, "manager", WS.ConnectionManager())
    db = _seed()
    logged = LoggedDb(db)
    app = FastAPI()
    app.include_router(chat_router.router)

    async def _db():
        yield logged
    app.dependency_overrides[get_db] = _db
    caller = lambda: {"kind": "agent", "agent_did": AGENT, "agent": types.SimpleNamespace(name="waiting-agent")}
    for dep in _read_deps():
        app.dependency_overrides[dep] = caller
    before = set(asyncio.all_tasks())
    yield types.SimpleNamespace(app=app, db=db)
    left = [t for t in asyncio.all_tasks() - before if t is not asyncio.current_task()]
    for t in left:
        t.cancel()
    await asyncio.gather(*left, return_exceptions=True)


async def _get(app, **params):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=30) as c:
        return await c.get("/api/v1/chat/sync", params=params)


async def _start(env):
    first = (await _get(env.app)).json()
    assert first["messages"] == [] and first.get("next_cursor"), first
    return first["next_cursor"]


# ─────────────────────────────── the rule ───────────────────────────────

AG = cs.Actor("agent", agent_did=AGENT)
DEV = cs.Actor("developer", developer_id=OWNER)


def _row(**kw):
    base = {"sender_ptype": "agent", "sender_id": SENDER, "body": "hello", "card": None, "mentions": None,
            "conversation_id": ROOM}
    base.update(kw)
    return base


def test_the_rule_names_what_reaches_the_caller_and_nothing_else():
    # BASE: AttributeError (no reaches_me on V0650)
    org = {"kind": "org", "owner_id": OWNER}
    yes = [
        (_row(mentions=[{"key": KEY}]), org, None),
        (_row(body="hi @all"), org, None), (_row(body="(@Everyone)!"), org, None), (_row(body="@ALL."), org, None),
        (_row(sender_ptype="developer", sender_id=str(OWNER)), org, None),
        (_row(conversation_id=DM), {"kind": "dm", "owner_id": None}, None),
        (_row(conversation_id=DM), {"kind": "agent_service", "owner_id": None}, None),
        (_row(card={"type": "approval.decided"}), org, {"requester_agent_did": AGENT.upper(), "org_id": ORG}),
    ]
    no = [
        (_row(mentions=[{"key": "agt:" + OTHER}]), org, None),
        (_row(body="mail me at user@all.com"), org, None), (_row(body="@allison"), org, None),
        (_row(sender_ptype="developer", sender_id="7"), org, None),
        (_row(card={"type": "approval.request"}), org, {"requester_agent_did": OTHER, "org_id": ORG}),
        (_row(sender_id=AGENT, body="@all from me", mentions=[{"key": KEY}]), org, None),       # never my own
    ]
    for row, conv, approval in yes:
        assert cs.reaches_me(AG, row, conv, approval, set()), row
    for row, conv, approval in no:
        assert not cs.reaches_me(AG, row, conv, approval, set()), row


def test_a_developer_is_reached_by_an_approval_card_of_an_org_it_approves_for():
    org = {"kind": "org", "owner_id": 99}
    card = _row(card={"type": "approval.request"})
    assert cs.reaches_me(DEV, card, org, {"requester_agent_did": AGENT, "org_id": ORG}, {ORG})
    assert not cs.reaches_me(DEV, card, org, {"requester_agent_did": AGENT, "org_id": ORG}, {"another-org"})
    assert not cs.reaches_me(DEV, _row(sender_ptype="developer", sender_id=str(OWNER)), {"kind": "org", "owner_id": OWNER},
                             None, set())                                                      # the owner's own


def test_a_card_read_as_json_text_is_read_too():
    assert cs._card_approval_id('{"type": "approval.request", "refs": {"approval_id": "apr_mine"}}') == "apr_mine"
    assert cs._card_approval_id({"type": "service.call", "refs": {"approval_id": "x"}}) is None
    assert cs._mentions_list('[{"key": "agt:x"}]') == [{"key": "agt:x"}] and cs._mentions_list("not json") == []


# ─────────────────────────────── the acceptance ───────────────────────────────

async def test_a_message_naming_another_agent_does_not_end_the_wait(env):
    # BASE: the wait ends on it (FastAPI drops `for`), within the second
    cursor = await _start(env)
    t0 = time.monotonic()
    task = asyncio.create_task(_get(env.app, wait=1, cursor=cursor, **{"for": "me"}))
    await asyncio.sleep(0.3)
    _post(env.db, ROOM, body="@other a look", mentions=[{"key": "agt:" + OTHER}])
    await WS.manager.wake_chat({KEY})
    body = (await asyncio.wait_for(task, 4.0)).json()
    assert body["messages"] == [] and body["woken"] is True and time.monotonic() - t0 >= 0.9, body
    assert body["for"] == "me"


@pytest.mark.parametrize("what", ["mention of me", "@all", "the owner", "a direct message", "my approval card"])
async def test_each_thing_that_names_me_ends_the_wait_within_a_second(env, what):
    # BASE: KeyError 'for' (V0650 answers without the echo)
    cursor = await _start(env)
    task = asyncio.create_task(_get(env.app, wait=5, cursor=cursor, **{"for": "me"}))
    await asyncio.sleep(0.3)
    if what == "mention of me":
        m = _post(env.db, ROOM, body="@waiting-agent hi", mentions=[{"key": KEY}])
    elif what == "@all":
        m = _post(env.db, ROOM, body="news for @all")
    elif what == "the owner":
        m = _post(env.db, ROOM, sender=str(OWNER), ptype="developer", body="a word from the owner")
    elif what == "a direct message":
        m = _post(env.db, DM, body="just to you")
    else:
        m = _post(env.db, ROOM, body=None, card={"v": 1, "type": "approval.decided", "data": {},
                                                 "refs": {"approval_id": "apr_mine"}})
    t0 = time.monotonic()
    await WS.manager.wake_chat({KEY})
    r = await asyncio.wait_for(task, 3.0)
    body = r.json()
    assert r.status_code == 200, body
    assert time.monotonic() - t0 < 1.0
    assert [x["id"] for x in body["messages"]] == [m.id] and body["for"] == "me" and body["woken"] is True
    assert "mentions" not in body["messages"][0]


async def test_another_agents_approval_card_does_not_end_the_wait(env):
    cursor = await _start(env)
    task = asyncio.create_task(_get(env.app, wait=1, cursor=cursor, **{"for": "me"}))
    await asyncio.sleep(0.3)
    _post(env.db, ROOM, body=None, card={"v": 1, "type": "approval.request", "data": {},
                                         "refs": {"approval_id": "apr_other"}})
    await WS.manager.wake_chat({KEY})
    assert (await asyncio.wait_for(task, 4.0)).json()["messages"] == []


async def test_the_cursor_loses_nothing(env):
    # BASE: KeyError 'plain_cursor'
    cursor = await _start(env)
    m1 = _post(env.db, ROOM, body="a plain line")
    m2 = _post(env.db, ROOM, body="@waiting-agent you", mentions=[{"key": KEY}])
    m3 = _post(env.db, ROOM, body="another plain line")
    mine = (await _get(env.app, cursor=cursor, **{"for": "me"})).json()
    assert [x["id"] for x in mine["messages"]] == [m2.id]
    plain = (await _get(env.app, cursor=mine["plain_cursor"])).json()
    assert [x["id"] for x in plain["messages"]] == [m1.id, m2.id, m3.id], "a plain sync loses nothing the filter left"
    again = (await _get(env.app, cursor=mine["next_cursor"], **{"for": "me"})).json()
    assert again["messages"] == [], "the filtered stream returns nothing twice and nothing it left behind"
    m4 = _post(env.db, DM, body="later, to me")
    later = (await _get(env.app, cursor=again["next_cursor"], **{"for": "me"})).json()
    assert [x["id"] for x in later["messages"]] == [m4.id]


async def test_my_own_all_never_ends_my_wait(env):
    cursor = await _start(env)
    task = asyncio.create_task(_get(env.app, wait=1, cursor=cursor, **{"for": "me"}))
    await asyncio.sleep(0.3)
    _post(env.db, ROOM, sender=AGENT, body="@all from me", mentions=[{"key": KEY}])
    await WS.manager.wake_chat({KEY})
    assert (await asyncio.wait_for(task, 4.0)).json()["messages"] == []


async def test_a_plain_sync_is_unchanged(env):
    cursor = await _start(env)
    m1 = _post(env.db, ROOM, body="a plain line")
    body = (await _get(env.app, cursor=cursor)).json()
    assert [x["id"] for x in body["messages"]] == [m1.id]
    assert "for" not in body and "plain_cursor" not in body and "mentions" not in body["messages"][0]


async def test_for_takes_me_only(env):
    # BASE: 200 (V0650 drops the unknown parameter)
    r = await _get(env.app, **{"for": "everyone"})
    assert r.status_code == 422 and "for takes one value, me" in r.text


# ─────────────────────────────── the MCP tool ───────────────────────────────

def test_sync_chat_is_a_wired_tier_2_tool():
    # BASE: KeyError (no syncChat on V0650)
    from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS
    from agentvault_registry.mcp import audit, server
    from agentvault_registry.mcp.tool_categories import get_category
    name = "theprotocol_syncChat"
    assert server.TOOL_DISPATCH[name].__name__ == "chat_sync"
    assert name in server.TIER2_TOOLS and name in server.AUTH_REQUIRED_TOOLS and name in audit._TIER_2_TOOLS
    assert get_category(name) == "account"
    schema = next(t for t in server.ALL_TOOL_SCHEMAS if t["name"] == name)
    assert schema["inputSchema"]["properties"]["wait_seconds"]["maximum"] == 25
    assert MCP_CONTRACTS[name].expect_keys == ["messages", "next_cursor", "plain_cursor", "for"]


async def test_sync_chat_asks_the_route_with_the_filter_and_a_timeout_past_the_wait(monkeypatch):
    from agentvault_registry.mcp import tools_agent as T
    seen = {}

    async def _req(auth, method, path, json_body=None, params=None, op_name="", timeout=None):
        seen.update(method=method, path=path, params=params, op=op_name, timeout=timeout)
        return {"messages": []}
    monkeypatch.setattr(T, "_chat_request", _req)
    await T.chat_sync(types.SimpleNamespace(auth_type="agent", raw_token="t"), cursor="c1", wait_seconds=99,
                      for_me=True)
    assert seen["path"] == "/api/v1/chat/sync" and seen["op"] == "syncChat"
    assert seen["params"] == {"wait": 25, "cursor": "c1", "for": "me"} and seen["timeout"] == 40.0
    assert "error" in await T.chat_sync(types.SimpleNamespace(auth_type="agent", raw_token="t"), wait_seconds="x")
