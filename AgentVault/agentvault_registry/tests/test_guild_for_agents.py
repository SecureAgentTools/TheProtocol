"""V0651 (s) (2026-10-31, agentvault2-14): the Guild for agents.

Order gwo_16cb368b37f9b13d39ed1786, found running the pilot's orders: (1) the verifying agent verified blind, because
_may_see_deliverable admitted only developers, so the poster agent's own token read `deliverable: null` through the REST
route and MCP guildGetOrder alike, while guildVerify is that agent's act; (2) a bid reached the poster's owners (push,
webhook) but nothing the poster agent could wait on; (3) guildCancelOrder took no reason ("unexpected keyword argument
reason"). The acceptance: the poster agent and the worker agent read the deliverable, a third agent and an anonymous
caller stay withheld; a bid wakes the poster agent's sync wait; a cancel's reason is in the order's events. Cases marked
BASE fail on 48d07ecf2 (V0650).
"""
from __future__ import annotations

import asyncio
import json
import time
import types
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import models
from agentvault_registry.background_tasks import leader
from agentvault_registry.database import get_db
from agentvault_registry.routers import chat as chat_router
from agentvault_registry.routers import guild as G
from agentvault_registry.routers import websocket as WS
from agentvault_registry.services import chat_service as cs
from tests._sqlite_db import sqlite_db
from tests.test_chat_sync_wait import LoggedDb, _agent_recipient, _read_deps, _stub_delivery

POSTER = "did:theprotocol:eu.test:poster-agent"
WORKER = "did:theprotocol:eu.test:worker-agent"
THIRD = "did:theprotocol:eu.test:third-agent"
OID = "gwo_0123456789abcdef01234567"
ORDER = {"id": OID, "poster_did": POSTER, "worker_did": WORKER, "title": "A task", "status": "submitted",
         "currency": "ECU", "bounty": Decimal("15"), "deliverable": {"report": "the work", "commit": "abc"}}


# ─────────────────────────────── (1) who reads the deliverable ───────────────────────────────

class _NoDb:
    """The agent rule decides before any query; a developer-less caller never reaches one."""

    async def execute(self, *a, **k):
        raise AssertionError("the deliverable rule queried the database for an agent or an anonymous caller")


@pytest.mark.parametrize("who,sees", [(POSTER, True), (POSTER.upper(), True), (WORKER, True), (THIRD, False),
                                      (None, False)])
def test_the_poster_and_worker_agents_read_the_deliverable_and_nobody_else(who, sees):
    # BASE: TypeError (the rule took no agent on V0650)
    assert asyncio.run(G._may_see_deliverable(_NoDb(), dict(ORDER), None, who)) is sees


class _DetailDb:
    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        if "FROM organizations WHERE treasury_agent_did" in sql:
            return SimpleNamespace(first=lambda: None)
        if "FROM guild_bids" in sql or "FROM guild_order_events" in sql:
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: []))
        raise AssertionError(f"unexpected statement: {sql[:100]}")


def _detail(monkeypatch, reader):
    from agentvault_registry.security import get_current_actor_for_read_optional, get_current_developer_optional

    async def _load(db, oid):
        return json.loads(json.dumps(ORDER, default=str))
    monkeypatch.setattr(G, "_load", _load)
    monkeypatch.setattr(G, "_require_enabled", lambda: None)
    app = FastAPI()
    app.include_router(G.router)
    app.dependency_overrides[get_db] = lambda: _DetailDb()
    app.dependency_overrides[get_current_developer_optional] = lambda: None
    app.dependency_overrides[get_current_actor_for_read_optional] = lambda: reader
    r = TestClient(app, raise_server_exceptions=False).get(f"/api/v1/guild/orders/{OID}")
    assert r.status_code == 200, r.text
    return r.json()["order"]


@pytest.mark.parametrize("did", [POSTER, WORKER])
def test_the_route_shows_the_poster_and_worker_agent_the_deliverable(monkeypatch, did):
    # BASE: deliverable withheld (V0650 read no agent)
    o = _detail(monkeypatch, {"kind": "agent", "agent_did": did, "agent": SimpleNamespace()})
    assert o["deliverable"] == {"report": "the work", "commit": "abc"} and "deliverable_withheld" not in o


@pytest.mark.parametrize("reader", [{"kind": "agent", "agent_did": THIRD, "agent": SimpleNamespace()}, None])
def test_the_route_withholds_it_from_a_third_agent_and_from_anonymous(monkeypatch, reader):
    o = _detail(monkeypatch, reader)
    assert o["deliverable"] is None and o["deliverable_withheld"] is True and o["deliverable_keys"] == ["commit", "report"]


def test_the_mcp_dispatcher_hands_a_public_tool_the_callers_bearer(monkeypatch):
    # BASE: ImportError (no get_mcp_bearer on V0650)
    from starlette.requests import Request
    from agentvault_registry.mcp import server as S
    from agentvault_registry.mcp.auth_bridge import get_mcp_bearer

    async def _peek():
        return {"bearer": get_mcp_bearer()}
    monkeypatch.setitem(S.TOOL_DISPATCH, "theprotocol_zzPeek", _peek)
    raw = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": "theprotocol_zzPeek", "arguments": {}}}).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    req = Request({"type": "http", "method": "POST", "path": "/mcp/rpc", "query_string": b"",
                   "headers": [(b"content-type", b"application/json"), (b"authorization", b"Bearer the-callers-token")]},
                  receive)

    async def _audit(**kw):
        return None
    monkeypatch.setattr(S, "emit_mcp_audit", _audit)
    out = json.loads(asyncio.run(S.handle_rpc(req)).body)
    assert out["result"]["structuredContent"]["bearer"] == "the-callers-token", out


def test_guild_get_order_forwards_the_bearer_as_an_optional_identity(monkeypatch):
    from agentvault_registry.mcp import tools_guild as TG
    from agentvault_registry.mcp.auth_bridge import set_mcp_bearer
    seen = {}

    async def _get(path, params=None, token=None):
        seen.update(path=path, token=token)
        return {"order": {}}
    monkeypatch.setattr(TG, "_guild_get", _get)
    set_mcp_bearer("agent-jwt")
    asyncio.run(TG.guild_get_order(OID))
    assert seen == {"path": f"/api/v1/guild/orders/{OID}", "token": "agent-jwt"}
    set_mcp_bearer(None)
    asyncio.run(TG.guild_get_order(OID))
    assert seen["token"] is None


# ─────────────────────────────── (2) a bid wakes the poster agent ───────────────────────────────

def _gt():
    """The service, imported where it is used (it does not exist on V0650: the red control reads each case)."""
    from agentvault_registry.services import guild_thread
    return guild_thread


def _seed():
    db = sqlite_db(models.Developer, models.Agent, models.Conversation, models.ConversationParticipant,
                   models.ChatMessage, models.ChatBlock)
    s = db.sync
    # insert_message stamps the thread with SQL now(); SQLite has none, so this test's one connection gets it
    import datetime as _dt
    s.connection().connection.dbapi_connection.create_function(
        "now", 0, lambda: _dt.datetime.now(_dt.timezone.utc).isoformat(" "))
    s.add(models.Agent(id=1, did=POSTER, client_id="c1", hashed_client_secret="x", creator_developer_id=6,
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
        # the one stand-in: recipients_snapshot's owner lookup is PostgreSQL's `= ANY(...)`, which SQLite cannot run;
        # its answer for the thread's one participant (the poster agent) is written out in (g)'s own shape
        return [_agent_recipient(POSTER, 6)]
    monkeypatch.setattr(cs, "recipients_snapshot", _recipients)
    app = FastAPI()
    app.include_router(chat_router.router)

    async def _db():
        yield LoggedDb(db)
    app.dependency_overrides[get_db] = _db
    caller = lambda: {"kind": "agent", "agent_did": POSTER, "agent": types.SimpleNamespace(name="poster-agent")}
    for dep in _read_deps():
        app.dependency_overrides[dep] = caller
    before = set(asyncio.all_tasks())
    yield types.SimpleNamespace(app=app, db=db)
    left = [t for t in asyncio.all_tasks() - before if t is not asyncio.current_task()]
    for t in left:
        t.cancel()
    await asyncio.gather(*left, return_exceptions=True)


async def _sync(app, **params):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=30) as c:
        return await c.get("/api/v1/chat/sync", params=params)


def _bid(**kw):
    base = dict(poster_did=POSTER, order_id=OID, title="A task", bid_id=277, bidder_did=WORKER, price="15",
                currency="ECU", eta_seconds=10800)
    base.update(kw)
    return base


async def test_a_bid_wakes_the_poster_agents_wait_with_the_order_and_the_bid(env):
    # BASE: ImportError (no guild_thread on V0650): a bid reached only the owners
    cursor = (await _sync(env.app)).json()["next_cursor"]
    task = asyncio.create_task(_sync(env.app, wait=5, cursor=cursor))
    await asyncio.sleep(0.3)
    assert not task.done()
    t0 = time.monotonic()
    posted = await _gt().post_bid(env.db, **_bid())
    assert posted is not None
    body = (await asyncio.wait_for(task, 3.0)).json()
    assert time.monotonic() - t0 < 1.0 and body["woken"] is True
    (m,) = body["messages"]
    assert m["kind"] == "system" and m["sender_ptype"] == "system"
    assert f"New bid on order {OID} (bid 277)" in m["body"] and "15 ECU" in m["body"] and "3 h" in m["body"]
    conv = env.db.sync.query(models.Conversation).filter_by(dm_pair_key=_gt().guild_pair_key(POSTER)).one()
    assert conv.kind == "system" and conv.title == "Guild"


async def test_one_thread_per_agent_and_one_row_per_bid(env):
    await _gt().post_bid(env.db, **_bid())
    assert await _gt().post_bid(env.db, **_bid()) is None                       # the same bid, noticed twice
    await _gt().post_bid(env.db, **_bid(bid_id=278, poster_did=POSTER.upper()))  # the DID in another case
    s = env.db.sync
    assert s.query(models.Conversation).filter_by(kind="system").count() == 1
    assert s.query(models.ChatMessage).count() == 2


async def test_a_poster_this_registry_does_not_host_gets_no_thread(env):
    assert await _gt().post_bid(env.db, **_bid(poster_did="did:theprotocol:asia.test:elsewhere")) is None
    assert env.db.sync.query(models.Conversation).count() == 0


def test_a_system_thread_is_written_by_its_rail_only():
    # BASE: no refusal (V0650 had no rail-only rule for a system thread)
    conv = SimpleNamespace(id="c1", kind="system")
    me = SimpleNamespace(state="active")
    with pytest.raises(cs.ChatError) as e:
        asyncio.run(cs.insert_message(None, conv, me, cs.Actor("agent", agent_did=POSTER), "text", "hi", None,
                                      client_ref="c-12345678"))
    assert e.value.status_code == 409 and "rail only" in str(e.value.detail)


def test_the_sentence_names_the_order_the_bid_and_the_terms():
    s = _gt().bid_sentence(order_id=OID, title="x" * 100, bid_id=5, bidder_did=WORKER, price="2.5", currency="ECU",
                        eta_seconds=600)
    assert s.startswith(f"New bid on order {OID} (bid 5)") and "2.5 ECU" in s and "10 min" in s and "..." in s


def test_both_bid_paths_spawn_the_notice():
    import inspect
    src = inspect.getsource(G)
    assert src.count("_notify_poster_agent(oid, o, bid_id,") == 2


# ─────────────────────────────── (3) a cancel says why ───────────────────────────────

class _CancelDb:
    def __init__(self):
        self.commits = 0

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        assert sql.startswith("UPDATE guild_work_orders SET status='cancelled'"), sql[:100]
        return SimpleNamespace(rowcount=1)

    async def commit(self):
        self.commits += 1


def _cancel(monkeypatch, body):
    from agentvault_registry.security import get_current_agent
    events = []

    async def _load(db, oid):
        return {"id": oid, "poster_did": POSTER, "status": "open", "bounty": Decimal("15")}

    async def _seq(db, oid):
        return 4

    async def _audit(db, oid, seq, kind, actor, payload):
        events.append((kind, actor, payload))

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(G, "_load", _load)
    monkeypatch.setattr(G, "_next_seq", _seq)
    monkeypatch.setattr(G, "_audit", _audit)
    monkeypatch.setattr(G, "_require_enabled", lambda: None)
    monkeypatch.setattr(G, "_refund_all_stakes", _noop)
    monkeypatch.setattr(G, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(G.guild_escrow, "escrow_payout", _noop)
    monkeypatch.setattr(G.guild_contract_mirror, "sync_from_order", _noop)
    app = FastAPI()
    app.include_router(G.router)
    app.dependency_overrides[get_db] = lambda: _CancelDb()
    app.dependency_overrides[get_current_agent] = lambda: SimpleNamespace(did=POSTER)
    c = TestClient(app, raise_server_exceptions=False)
    r = (c.post(f"/api/v1/guild/orders/{OID}/cancel", json=body) if body is not None
         else c.post(f"/api/v1/guild/orders/{OID}/cancel"))
    return r, events


def test_a_cancel_keeps_its_reason_in_the_orders_events(monkeypatch):
    # BASE: the reason is not in the event (V0650 took no body)
    r, events = _cancel(monkeypatch, {"reason": "  posted twice,\n by mistake "})
    assert r.status_code == 200, r.text
    assert events == [("cancelled", POSTER, {"refund": "15", "reason": "posted twice, by mistake"})]


@pytest.mark.parametrize("body", [None, {}, {"reason": ""}])
def test_a_cancel_without_a_reason_is_unchanged(monkeypatch, body):
    r, events = _cancel(monkeypatch, body)
    assert r.status_code == 200 and events == [("cancelled", POSTER, {"refund": "15"})]


def test_a_reason_over_500_characters_is_refused(monkeypatch):
    r, events = _cancel(monkeypatch, {"reason": "x" * 501})
    assert r.status_code == 422 and events == []


def test_the_mcp_cancel_takes_the_reason(monkeypatch):
    # BASE: TypeError, unexpected keyword argument 'reason'
    from agentvault_registry.mcp import server as S
    from agentvault_registry.mcp import tools_guild as TG
    seen = {}

    async def _post(path, payload, token):
        seen.update(path=path, payload=payload)
        return {"ok": True}
    monkeypatch.setattr(TG, "_guild_post", _post)
    auth = SimpleNamespace(is_agent=True, auth_type="agent", raw_token="t", is_anonymous=False)
    asyncio.run(TG.guild_cancel_order(auth, OID, reason="posted twice"))
    assert seen["payload"] == {"reason": "posted twice"}
    asyncio.run(TG.guild_cancel_order(auth, OID))
    assert seen["payload"] == {}
    schema = next(t for t in S.ALL_TOOL_SCHEMAS if t["name"] == "theprotocol_guildCancelOrder")
    assert schema["inputSchema"]["properties"]["reason"]["maxLength"] == 500


def test_the_boundary_address_is_computed_not_written():
    import pathlib
    p = pathlib.Path(__file__).with_name("test_frame_invitation_same_host.py")
    assert "172.32." not in p.read_text()
