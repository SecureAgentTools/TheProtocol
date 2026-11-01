"""V0652 (s) follow-up (order gwo_16cb368b37f9b13d39ed1786, agentvault2-14, 2026-11-01): the owner opens his agent's Guild
thread read-only, without a seat.

V0651's pair proof (nt261101x1, its finding 3): a Guild bid opens the poster agent's Guild thread (kind system, one
participant: the agent). The owner's list reaches every thread one of his agents sits in, so the thread showed in his list,
and opening it answered 403 (resolve_membership seats an owner only in a pair thread). The list now tells the truth by the
entry working (session-lead's choice, the sessions' room seq 473): the message read lets the agent's owner read it, with
no participant row (so no chat notice per bid: the push and the webhook tell him), and every other act still asks for a
seat: his post and his mark-read are refused, and a developer who does not own the agent reads nothing. The page's other
read on every open, the support-review banner, asks the same rule (services/chat_service.resolve_reader): refused, it told
the owner the check had failed.
Red on V0651 (05441be31): the owner's read answers 403 (and the banner's read).
"""
from __future__ import annotations

import asyncio
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
from tests.test_chat_sync_wait import LoggedDb, _agent_recipient, _read_deps, _stub_delivery

OWNER, STRANGER = 6, 9
POSTER = "did:theprotocol:eu.test:poster-agent"
WORKER = "did:theprotocol:eu.test:worker-agent"
OID = "gwo_0123456789abcdef01234567"


def _seed():
    db = sqlite_db(models.Developer, models.Agent, models.AgentCard, models.Conversation, models.ConversationParticipant,
                   models.ChatMessage, models.ChatBlock, models.SupportTicket, models.SupportReviewGrant)
    s = db.sync
    import datetime as _dt
    s.connection().connection.dbapi_connection.create_function(
        "now", 0, lambda: _dt.datetime.now(_dt.timezone.utc).isoformat(" "))
    for i in (OWNER, STRANGER):
        s.add(models.Developer(id=i, name=f"dev{i}", email=f"d{i}@example.test", hashed_password="x"))
    s.add(models.Agent(id=1, did=POSTER, client_id="c1", hashed_client_secret="x", creator_developer_id=OWNER,
                       status="active"))
    s.commit()
    return db


@pytest.fixture()
async def env(monkeypatch):
    async def _no_redis():
        return None
    monkeypatch.setattr(leader, "get_redis", _no_redis)
    monkeypatch.setattr(WS, "manager", WS.ConnectionManager())
    _stub_delivery(monkeypatch)
    db = _seed()

    async def _recipients(db_, conv, sender):
        return [_agent_recipient(POSTER, OWNER)]
    monkeypatch.setattr(cs, "recipients_snapshot", _recipients)

    async def _owners(db_, dids):   # PostgreSQL's = ANY(...) in the real lookup; its answer for this one agent
        return {d: OWNER for d in dids if str(d).lower() == POSTER.lower()}
    monkeypatch.setattr(cs, "agent_owner_map", _owners)

    async def _names(db_, keys):    # the same: the names lookup asks = ANY(...)
        return {k: k for k in keys}
    monkeypatch.setattr(cs, "display_names", _names)
    app = FastAPI()
    app.include_router(chat_router.router)

    async def _db():
        yield LoggedDb(db)
    app.dependency_overrides[get_db] = _db
    who = {"as": ("developer", OWNER)}

    def caller():
        kind, ident = who["as"]
        if kind == "developer":
            return {"kind": "developer", "developer_id": ident, "developer": types.SimpleNamespace(id=ident, name=f"dev{ident}")}
        return {"kind": "agent", "agent_did": ident, "agent": types.SimpleNamespace(name="poster-agent")}
    for dep in _read_deps():
        app.dependency_overrides[dep] = caller
    from agentvault_registry.services import guild_thread
    posted = await guild_thread.post_bid(db, poster_did=POSTER, order_id=OID, title="A task", bid_id=277,
                                         bidder_did=WORKER, price="15", currency="ECU", eta_seconds=10800)
    assert posted is not None
    guild = db.sync.query(models.Conversation).filter_by(dm_pair_key=guild_thread.guild_pair_key(POSTER)).one()
    before = set(asyncio.all_tasks())
    yield types.SimpleNamespace(app=app, db=db, who=who, guild=guild.id)
    left = [t for t in asyncio.all_tasks() - before if t is not asyncio.current_task()]
    for t in left:
        t.cancel()
    await asyncio.gather(*left, return_exceptions=True)


async def _call(env, method, path, who=("developer", OWNER), **kw):
    env.who["as"] = who
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://t", timeout=30) as c:
        return await c.request(method, path, **kw)


def _participants(env):
    return env.db.sync.query(models.ConversationParticipant).filter_by(conversation_id=env.guild).count()


async def test_the_owner_opens_his_agents_guild_thread_without_taking_a_seat(env):
    r = await _call(env, "GET", f"/api/v1/chat/conversations/{env.guild}/messages")
    assert r.status_code == 200, r.text                      # V0651: 403, the entry his list showed was dead
    body = r.json()
    assert any(f"New bid on order {OID} (bid 277)" in (m.get("body") or "") for m in body["messages"])
    assert _participants(env) == 1                           # the agent alone: no seat for the owner, no notice per bid


async def test_a_developer_who_does_not_own_the_agent_reads_nothing(env):
    r = await _call(env, "GET", f"/api/v1/chat/conversations/{env.guild}/messages", who=("developer", STRANGER))
    assert r.status_code == 403, r.text
    banner = await _call(env, "GET", f"/api/v1/chat/conversations/{env.guild}/support-review", who=("developer", STRANGER))
    assert banner.status_code == 403, banner.text


async def test_the_page_banner_read_answers_the_owner_too(env):
    r = await _call(env, "GET", f"/api/v1/chat/conversations/{env.guild}/support-review")
    assert r.status_code == 200, r.text                      # V0651: 403, and the page said "the check failed"
    assert r.json()["grants"] == []
    assert _participants(env) == 1


async def test_every_other_act_still_asks_for_a_seat(env):
    post = await _call(env, "POST", f"/api/v1/chat/conversations/{env.guild}/messages",
                       json={"kind": "text", "body": "hello", "client_ref": "owner-post-0001"})
    assert post.status_code in (403, 409), post.text         # rail-only, and the owner holds no seat
    read = await _call(env, "POST", f"/api/v1/chat/conversations/{env.guild}/read", json={"seq": 1})
    assert read.status_code == 403, read.text                # no read position of his own (the console ignores this)
    assert _participants(env) == 1
