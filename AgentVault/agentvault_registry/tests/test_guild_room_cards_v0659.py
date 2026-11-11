"""V0659 (n) (order gwo_54d9e9b56ff69609f5e8fbbe, 2026-11-08): Guild orders show as live cards from the MCP tool too, and
an existing order can name its room.

The maintainer (the sessions' room, seq 1831) sees the approvals and the attachments in the room, never the Guild work.
V0652 (aa) built the card (an order posted with `room_id` shows as ONE guild.order.live card the Guild rail keeps
current), but MCP's guildPostOrder took no room_id, so no order posted through MCP had a card. Two halves:

1. guildPostOrder takes room_id, and the other fields POST /api/v1/guild/orders takes that it lacked (currency,
   required_skills). The route checks the room (room_refusal) before any escrow moves, through MCP as through REST. The
   tool's signature, its advertised schema and the REST model name the same fields, so they cannot drift apart again.
2. POST /api/v1/guild/orders/{oid}/room: the poster names a room for an order posted without one, while the order has
   not ended; the rail posts the order's card there with its current state and keeps it current from there. Refused for
   anyone but the poster, for a room the poster's agent cannot post in, for an order that already has a room, and for
   an order that ended (settled, cancelled, or expired by the reaper: the card treats all three as closed). Its MCP
   tool: guildSetOrderRoom.

And a gap met on the way: the reaper writes its own events (an open order expired, an order disputed after a missed
deadline or a silent poster, a stuck settlement re-driven or reverted) without asking for the card's refresh, so such an
order's card kept its last state (an expired order read "open for bids"). It asks now, as each route's event does.

Measured through the real guild router, the real chat service and the real room checks over SQLite rows, and through the
MCP tools against that router in process. Every case is red on origin/v0657/cut (553347408) except the ones marked
control: there the tool takes none of the three fields, the route and the room tool do not exist, and the reaper asks
for no refresh.

The review's cases (2026-11-08, the last section): red on ae6f7ccc4 (the change above) for their reasons, except the
three marked GUARD. Those pin what ae6f7ccc4 already does and no test held: the room is claimed by a guarded UPDATE (a
room another naming claimed first, or an order that ended in the same moment, is refused and left as it is), and a card
that is not posted now leaves the room named and says so. They are green on ae6f7ccc4 and red on a claim without its
guard.

Naming the room an order already has, again (the last section): a client's retry after a timeout read its own success
as a refusal (409), and an order whose card was not posted could not get it before its next step. Those cases are red
on the review's change (e5e151590) for that reason, except the one marked control.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime
import inspect
import re
import sqlite3
import sys
import types
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import text

import agentvault_registry.database as D
from agentvault_registry import models, security
from agentvault_registry.background_tasks import leader
from agentvault_registry.database import get_db
from agentvault_registry.mcp import tools_guild as G
from agentvault_registry.mcp.auth_bridge import MCPAuthContext
from agentvault_registry.routers import guild
from agentvault_registry.services import chat_service as cs
from agentvault_registry.services import guild_live_card as glc
from tests._sqlite_db import sqlite_db

POSTER = "did:theprotocol:eu.test:session-lead"
OTHER = "did:theprotocol:eu.test:session-code"
STRANGER = "did:theprotocol:eu.test:stranger"
ROOM = "conv-guild-room-1"          # the poster and OTHER take part
FAR = "conv-guild-room-2"           # OTHER and STRANGER only
OID = "gwo_" + "ab" * 12
ROOM_TOOL = "theprotocol_guildSetOrderRoom"


def run(coro):
    return asyncio.run(coro)


class _Manager:
    def __init__(self):
        self.sent, self.woken = [], []

    async def broadcast_to_subscribers(self, topic, envelope):
        self.sent.append((topic, envelope))

    async def wake_chat(self, keys):
        self.woken.append(set(keys))

    async def is_present(self, dev_id):
        return False


@pytest.fixture()
def env(monkeypatch):
    """The guild router over SQLite rows, the chat service's real room checks and card writes, and MCP's guild tools
    calling that router in process. Background work (the card's refresh, the deliveries) is collected and run by
    `drain`, so a test reads the rows once it is done."""
    async def _no_redis():
        return None
    monkeypatch.setattr(leader, "get_redis", _no_redis)
    mgr = _Manager()
    ws = types.ModuleType("agentvault_registry.routers.websocket")
    ws.manager = mgr
    pn = types.ModuleType("agentvault_registry.background_tasks.push_notify")

    async def _quiet(*a, **k):
        return 0
    pn.notify = _quiet
    pn.notify_agent_owners = _quiet
    rh = types.ModuleType("agentvault_registry.background_tasks.reactor_helpers")
    rh.dispatch_webhook_for_agents = _quiet
    for mod in (ws, pn, rh):
        monkeypatch.setitem(sys.modules, mod.__name__, mod)

    async def _names(db, keys):
        return {k: k.split(":")[-1] for k in keys}
    monkeypatch.setattr(cs, "display_names", _names)

    async def _owners(db, dids):
        return {d: {POSTER: 6, OTHER: 7, STRANGER: 8}.get(d) for d in dids}
    monkeypatch.setattr(cs, "agent_owner_map", _owners)
    spawned, failed = [], []

    def _spawn(coro, what=None):
        spawned.append(coro)
    monkeypatch.setattr(cs, "spawn", _spawn)
    # the routes bind Decimals and datetimes as SQL parameters; SQLite takes them as text (restored after the test)
    monkeypatch.setitem(sqlite3.adapters, (Decimal, sqlite3.PrepareProtocol), str)
    monkeypatch.setitem(sqlite3.adapters, (datetime.datetime, sqlite3.PrepareProtocol), lambda d: d.isoformat(" "))
    db = sqlite_db(models.Developer, models.Agent, models.Conversation, models.ConversationParticipant,
                   models.ChatMessage, models.ChatCardUpdate, models.ChatBlock, models.GuildWorkOrder, models.GuildBid)
    s = db.sync
    s.connection().connection.driver_connection.create_function(
        "now", 0, lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"))
    # the events' BIGINT key does not number itself in SQLite; the table as the routes write it, with one that does
    s.execute(text("CREATE TABLE guild_order_events (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id VARCHAR(40) NOT NULL,"
                   " seq INTEGER NOT NULL, event_type VARCHAR(24) NOT NULL, actor_did VARCHAR(120), payload JSON,"
                   " created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"))
    for conv, members in ((ROOM, (POSTER, OTHER)), (FAR, (OTHER, STRANGER))):
        s.add(models.Conversation(id=conv, kind="dm", created_by_ptype="agent", created_by_id=members[0]))
        for i, did in enumerate(members):
            s.add(models.ConversationParticipant(id=f"{conv}-p{i}", conversation_id=conv, ptype="agent", agent_did=did,
                                                 state="active"))
    s.commit()

    @contextlib.asynccontextmanager
    async def _ctx():
        yield db

    async def _no_lock(db_, oid):          # Postgres's advisory lock; SQLite has one connection anyway
        return None
    monkeypatch.setattr(D, "get_db_context", _ctx)
    monkeypatch.setattr(glc, "_lock", _no_lock)
    monkeypatch.setattr(glc, "COMMIT_WAIT_S", 0.3)
    monkeypatch.setenv("GUILD_ENABLED", "true")
    from agentvault_registry.services import jurisdiction
    escrow = []

    async def _nothing(*a, **k):
        return None

    async def _deposit(did, amount, oid, *a, **k):
        escrow.append((did, str(amount), oid))
    monkeypatch.setattr(jurisdiction, "check_jurisdiction", _nothing)
    monkeypatch.setattr(guild.guild_escrow, "escrow_deposit", _deposit)
    monkeypatch.setattr(guild, "_emit", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(guild.router)

    async def _db():
        yield db
    who = {"did": POSTER}
    by_token = {f"Bearer jwt-of-{d.split(':')[-1]}": d for d in (POSTER, OTHER, STRANGER)}

    def _agent(request: Request):
        """The agent a request speaks for: its bearer's (an MCP tool's call), else the test's caller."""
        did = by_token.get(request.headers.get("authorization", ""), who["did"])
        return types.SimpleNamespace(did=did, name=did.split(":")[-1])
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[security.get_current_agent] = _agent
    # MCP's tools call this registry over HTTP: here, the app in process
    monkeypatch.setattr(G, "mcp_http_client",
                        lambda **kw: httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kw))
    monkeypatch.setattr(G, "REGISTRY_SELF_URL", "http://registry.test")
    return types.SimpleNamespace(app=app, db=db, s=s, who=who, mgr=mgr, escrow=escrow, spawned=spawned, failed=failed)


async def drain(env):
    """Run the background work the requests asked for (and what it asks for in turn), as spawn() would."""
    while env.spawned:
        coro = env.spawned.pop(0)
        try:
            await coro
        except Exception as e:  # noqa: BLE001 — spawn() logs a failed task; the tests read the list
            env.failed.append(repr(e))


async def call(env, method, path, as_did=POSTER, **kw):
    env.who["did"] = as_did
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://registry.test",
                                 timeout=30) as c:
        r = await c.request(method, path, **kw)
    await drain(env)
    return r


def agent_auth(did=POSTER):
    return MCPAuthContext(auth_type="agent", agent_did=did, agent_id=1, raw_token=f"jwt-of-{did.split(':')[-1]}")


def add_order(env, status="open", worker=None, room=None, events=("posted",), bids=0, oid=OID, poster=POSTER):
    s = env.s
    s.add(models.GuildWorkOrder(id=oid, poster_did=poster, title="Room cards from MCP", bounty=15, currency="ECU",
                                status=status, worker_did=worker, announce_conversation_id=room, fee_bps=250))
    for i in range(bids):
        s.add(models.GuildBid(order_id=oid, bidder_did=OTHER if i == 0 else STRANGER, price=15, status="open"))
    for seq, etype in enumerate(events, 1):
        s.execute(text("INSERT INTO guild_order_events (order_id, seq, event_type, actor_did) VALUES (:o, :q, :e, :a)"),
                  {"o": oid, "q": seq, "e": etype, "a": poster})
    s.commit()


def order_row(env, oid=OID):
    env.s.expire_all()
    return env.s.get(models.GuildWorkOrder, oid)


def cards(env, conv=None):
    env.s.expire_all()
    q = env.s.query(models.ChatMessage).filter(models.ChatMessage.kind == "card")
    if conv:
        q = q.filter(models.ChatMessage.conversation_id == conv)
    return q.all()


def schema_of(schemas, name):
    return next(x for x in schemas if x["name"] == name)["inputSchema"]


def bounds(field):
    """A pydantic field's stated bounds ({min_length, max_length, ge, le, gt} as set)."""
    out = {}
    for m in field.metadata:
        for k in ("min_length", "max_length", "ge", "le", "gt"):
            if getattr(m, k, None) is not None:
                out[k] = getattr(m, k)
    return out


# ── 1. guildPostOrder: the fields the REST route takes ─────────────────────────────────────────────────────────────

def test_the_tool_its_schema_and_the_rest_model_name_the_same_fields():
    # BASE: room_id, currency and required_skills are in the model and nowhere in the tool
    from agentvault_registry.mcp import server
    model = set(guild.OrderPostIn.model_fields)
    params = set(inspect.signature(G.guild_post_order).parameters) - {"auth"}
    assert params == model, f"the tool's own parameters: missing {sorted(model - params)}, extra {sorted(params - model)}"
    for schemas in (G.GUILD_TOOL_SCHEMAS, server.ALL_TOOL_SCHEMAS):
        props = set(schema_of(schemas, "theprotocol_guildPostOrder")["properties"]) - {"agent_jwt"}
        assert props == model, f"the advertised schema: missing {sorted(model - props)}, extra {sorted(props - model)}"


def test_the_schema_states_the_models_bounds_where_both_take_the_same_kind():
    # BASE: the three fields are not advertised, and title, spec and deadline_seconds state no bound
    props = schema_of(G.GUILD_TOOL_SCHEMAS, "theprotocol_guildPostOrder")["properties"]
    for name, field in guild.OrderPostIn.model_fields.items():
        bound = bounds(field)
        kind = props[name]["type"]
        if "max_length" in bound and kind == "string":
            assert props[name].get("maxLength") == bound["max_length"], name
        if kind == "integer":
            assert props[name].get("minimum") == bound.get("ge") and props[name].get("maximum") == bound.get("le"), name
    assert props["room_id"]["maxLength"] == 36 and props["currency"]["maxLength"] == 12
    assert props["required_skills"]["type"] == "array" and props["required_skills"]["items"] == {"type": "string"}


@pytest.fixture
def sent(monkeypatch):
    calls = []

    async def _post(path, payload, token):
        calls.append((path, payload, token))
        return {"ok": True}
    monkeypatch.setattr(G, "_guild_post", _post)
    return calls


def test_every_field_the_tool_takes_reaches_the_route_under_the_models_name(sent):
    # BASE: TypeError, the tool takes no room_id, currency or required_skills
    out = run(G.guild_post_order(agent_auth(), title="Ship V0659 (n)", bounty="15", spec="cards from MCP",
                                 deadline_seconds=3600, stake_required="2", min_reputation="100",
                                 intended_worker_did=f" {OTHER} ", room_id=f"  {ROOM} ", currency=" ECU ",
                                 required_skills=["python", "chat"]))
    assert out == {"ok": True}
    path, payload, token = sent[-1]
    assert path == "/api/v1/guild/orders" and token == "jwt-of-session-lead"
    assert set(payload) == set(guild.OrderPostIn.model_fields)
    body = guild.OrderPostIn(**payload)                       # the route's own model takes what the tool sends
    assert (body.room_id, body.currency, body.required_skills) == (ROOM, "ECU", ["python", "chat"])
    assert body.intended_worker_did == OTHER and body.bounty == 15.0 and body.stake_required == 2.0


@pytest.mark.parametrize("given,skills", [
    (["python", "chat"], ["python", "chat"]),
    ('["python", "chat"]', ["python", "chat"]),        # a JSON list as text (the arguments gate lets text through)
    ("python, chat ,, ", ["python", "chat"]),           # a comma-separated text
])
def test_required_skills_takes_a_list_json_text_or_a_comma_list(sent, given, skills):
    # BASE: TypeError
    run(G.guild_post_order(agent_auth(), title="t", bounty="1", required_skills=given))
    assert sent[-1][1]["required_skills"] == skills


@pytest.mark.parametrize("given", ['["python"', '{"python": 1}', 7])
def test_a_skill_list_that_is_no_list_is_refused_before_any_request(sent, given):
    # BASE: TypeError
    out = run(G.guild_post_order(agent_auth(), title="t", bounty="1", required_skills=given))
    assert "required_skills" in out["error"] and sent == []


@pytest.mark.parametrize("blank", [{}, {"room_id": "", "currency": "", "required_skills": []},
                                   {"room_id": "   ", "currency": " ", "required_skills": ""}])
def test_a_blank_room_currency_or_skill_list_sends_none_of_them(sent, blank):
    # BASE: TypeError on the keywords; {} is the control and passes on both trees
    run(G.guild_post_order(agent_auth(), title="t", bounty="1", **blank))
    assert not {"room_id", "currency", "required_skills"} & set(sent[-1][1])


def test_an_mcp_post_naming_a_room_its_poster_cannot_post_in_is_refused_before_any_escrow(env):
    # BASE: TypeError, the room never reaches the route
    async def go():
        out = await G.guild_post_order(agent_auth(), title="t", bounty="3", room_id=FAR)
        await drain(env)
        return out
    out = run(go())
    poster = cs.Actor("agent", agent_did=POSTER, display_name="session-lead")
    why = run(glc.room_refusal(env.db, FAR, poster))
    assert why and out == {"error": f"HTTP 422: room_id: {why}"}
    assert env.escrow == [] and env.s.query(models.GuildWorkOrder).count() == 0
    out = run(G.guild_post_order(agent_auth(), title="t", bounty="3", room_id="conv-none"))
    assert "HTTP 422: room_id: room_id names no conversation" in out["error"] and env.escrow == []


def test_an_mcp_post_naming_its_room_shows_there_as_the_live_card(env):
    # BASE: TypeError; the order posted through MCP had no room and so no card
    async def go():
        out = await G.guild_post_order(agent_auth(), title="Room cards from MCP", bounty="3", room_id=ROOM,
                                       currency="ECU", required_skills=["chat"])
        await drain(env)
        return out
    out = run(go())
    assert out["room_id"] == ROOM and out["currency"] == "ECU" and env.failed == []
    assert [(d, Decimal(a), o) for d, a, o in env.escrow] == [(POSTER, Decimal("3"), out["order_id"])]
    row = order_row(env, out["order_id"])
    (card,) = cards(env, ROOM)
    assert row.announce_conversation_id == ROOM and row.announce_message_id == card.id
    assert card.sender_ptype == "system" and card.card["type"] == "guild.order.live"
    assert card.card["data"]["order_id"] == out["order_id"] and card.card["data"]["status"] == "open"
    assert [e["type"] for e in card.card["data"]["events"]] == ["posted"]


# ── 2. POST /api/v1/guild/orders/{oid}/room ───────────────────────────────────────────────────────────────────────

def test_the_poster_names_a_room_and_the_card_shows_the_order_as_it_is_now(env):
    # BASE: 404, the route does not exist
    add_order(env, status="awarded", worker=OTHER, events=("posted", "bid", "awarded"), bids=1)
    r = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": f" {ROOM} "}))
    assert r.status_code == 200, r.text
    out = r.json()
    (card,) = cards(env)
    assert out == {"ok": True, "order_id": OID, "room_id": ROOM, "status": "awarded", "card_message_id": card.id}
    row = order_row(env)
    assert row.announce_conversation_id == ROOM and row.announce_message_id == card.id
    data = card.card["data"]
    assert card.conversation_id == ROOM and card.sender_ptype == "system" and card.client_ref == f"glive-{OID}"
    assert card.card["type"] == "guild.order.live" and data["status"] == "awarded" and data["bids"] == 1
    assert [e["type"] for e in data["events"]] == ["posted", "bid", "awarded"] and data["worker_did"] == OTHER
    # the room's members hear the card as they hear a message
    heard = [e for _, e in env.mgr.sent if e["type"] == "chat.message"]
    assert heard and all(e["data"]["message"]["id"] == card.id for e in heard) and env.failed == []


def test_the_card_is_kept_current_from_there(env):
    # BASE: 404 at the naming
    add_order(env, status="awarded", worker=OTHER, events=("posted", "bid", "awarded"), bids=1)
    assert run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": ROOM})).status_code == 200

    async def deliver():                    # the worker delivers: the route's one writer path, then its commit
        await env.db.execute(text("UPDATE guild_work_orders SET status='submitted' WHERE id=:o"), {"o": OID})
        await guild._audit(env.db, OID, await guild._next_seq(env.db, OID), "submitted", OTHER, {"keys": ["text"]})
        await env.db.commit()
        await drain(env)
    run(deliver())
    (card,) = cards(env)
    assert card.card_rev == 1 and card.card["data"]["status"] == "submitted"
    assert [e["type"] for e in card.card["data"]["events"]] == ["posted", "bid", "awarded", "submitted"]


def test_anyone_but_the_poster_is_refused_and_nothing_changes(env):
    # BASE: 404
    add_order(env)
    r = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", as_did=OTHER, json={"room_id": ROOM}))
    assert r.status_code == 403 and "poster" in r.json()["detail"]
    assert order_row(env).announce_conversation_id is None and cards(env) == []


def test_a_room_the_posters_agent_cannot_post_in_is_refused_and_nothing_changes(env):
    # BASE: 404
    add_order(env)
    poster = cs.Actor("agent", agent_did=POSTER, display_name="session-lead")
    for room in (FAR, "conv-none"):
        why = run(glc.room_refusal(env.db, room, poster))
        r = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": room}))
        assert why and r.status_code == 422 and r.json()["detail"] == f"room_id: {why}", r.text
    r = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": "   "}))
    assert r.status_code == 422 and r.json()["detail"].startswith("room_id:")
    assert order_row(env).announce_conversation_id is None and cards(env) == []


def test_an_order_that_already_has_a_room_is_refused(env):
    # BASE: 404. Another room than the one it has (its own room named again: the last section)
    add_order(env, room=FAR)
    r = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": ROOM}))
    assert r.status_code == 409 and "already has a room" in r.json()["detail"], r.text
    assert order_row(env).announce_conversation_id == FAR and cards(env) == []


@pytest.mark.parametrize("ended", ["settled", "cancelled", "expired"])
def test_an_order_that_ended_is_refused(env, ended):
    # BASE: 404
    add_order(env, status=ended, events=("posted", ended))
    r = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": ROOM}))
    assert r.status_code == 409 and ended in r.json()["detail"], r.text
    assert order_row(env).announce_conversation_id is None and cards(env) == []


@pytest.mark.parametrize("running", ["open", "submitted", "disputed", "resolved"])
def test_an_order_still_running_takes_its_room(env, running):
    # BASE: 404. The other side of the case above: every status the card shows as running takes a room
    add_order(env, status=running)
    r = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": ROOM}))
    assert r.status_code == 200 and r.json()["status"] == running, r.text


def test_an_unknown_order_is_refused_with_the_routes_own_sentence(env):
    # BASE: 404 too, but FastAPI's "Not Found": no route serves the path
    r = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": ROOM}))
    assert r.status_code == 404 and r.json()["detail"] == "Order not found"


def test_a_registry_with_the_guild_off_says_so(env, monkeypatch):
    # BASE: 404
    add_order(env)
    monkeypatch.setenv("GUILD_ENABLED", "false")
    r = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": ROOM}))
    assert r.status_code == 503 and "disabled" in r.json()["detail"]


# ── 2. the room tool ───────────────────────────────────────────────────────────────────────────────────────────────

def test_the_room_tool_is_exactly_its_route(sent):
    # BASE: AttributeError, no such tool
    run(G.guild_set_order_room(agent_auth(), order_id=" gwo_a/b ", room_id=f" {ROOM} "))
    assert sent == [("/api/v1/guild/orders/gwo_a%2Fb/room", {"room_id": ROOM}, "jwt-of-session-lead")]


@pytest.mark.parametrize("args", [{"order_id": "", "room_id": ROOM}, {"order_id": OID, "room_id": "  "}])
def test_the_room_tool_refuses_a_missing_argument_before_any_request(sent, args):
    # BASE: AttributeError
    out = run(G.guild_set_order_room(agent_auth(), **args))
    assert out == {"error": "order_id and room_id are required"} and sent == []


def test_the_room_tool_is_an_agent_tool_wired_like_its_family():
    # BASE: the name is in no table
    from agentvault_registry.mcp import audit, server, tool_categories
    assert server.TOOL_DISPATCH[ROOM_TOOL] is G.guild_set_order_room
    assert ROOM_TOOL in server.TIER2_TOOLS and ROOM_TOOL in server.AUTH_REQUIRED_TOOLS
    assert ROOM_TOOL in audit._TIER_2_TOOLS and tool_categories.get_category(ROOM_TOOL) == "guild"
    for schemas in (G.GUILD_TOOL_SCHEMAS, server.ALL_TOOL_SCHEMAS, server.AGENT_TOOL_SCHEMAS):
        sc = schema_of(schemas, ROOM_TOOL)
        assert set(sc["properties"]) == {"order_id", "room_id", "agent_jwt"} and sc["required"] == ["order_id", "room_id"]


def test_the_room_tools_schema_states_the_routes_body():
    # BASE: no such schema and no such model
    sc = schema_of(G.GUILD_TOOL_SCHEMAS, ROOM_TOOL)
    assert set(sc["properties"]) - {"order_id", "agent_jwt"} == set(guild.OrderRoomIn.model_fields)
    bound = bounds(guild.OrderRoomIn.model_fields["room_id"])
    assert (sc["properties"]["room_id"]["minLength"], sc["properties"]["room_id"]["maxLength"]) == (
        bound["min_length"], bound["max_length"]) == (1, 36)


def test_the_room_tool_names_the_route_over_mcp(env):
    # BASE: AttributeError. Through the router: the poster's room, and a stranger's order refused with its sentence
    add_order(env, status="open", bids=1, events=("posted", "bid"))

    async def go():
        refused = await G.guild_set_order_room(agent_auth(OTHER), order_id=OID, room_id=ROOM)
        out = await G.guild_set_order_room(agent_auth(), order_id=OID, room_id=ROOM)
        await drain(env)
        return refused, out
    refused, out = run(go())
    assert refused["error"].startswith("HTTP 403: ") and "poster" in refused["error"]
    (card,) = cards(env)
    assert out["ok"] is True and out["card_message_id"] == card.id and card.card["data"]["bids"] == 1


def test_the_room_tools_tester_contract_pins_what_the_route_answers(env):
    # BASE: no contract (the fall-through takes no arguments)
    from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS
    c = MCP_CONTRACTS[ROOM_TOOL]
    assert c.tier == "2" and c.expect_status == "error_4xx" and not c.skip_reason
    args = {k: v for k, v in c.arguments.items() if k != "agent_jwt"}
    assert c.arguments.get("agent_jwt") == "${sentinel_jwt}" and set(args) == {"order_id", "room_id"}
    out = run(G.guild_set_order_room(agent_auth(), **args))
    phrases = c.expect_error_message_contains
    phrases = [phrases] if isinstance(phrases, str) else list(phrases)
    assert phrases and all(p in out["error"] for p in phrases), out
    assert env.s.query(models.GuildWorkOrder).count() == 0 and cards(env) == []


# ── met on the way: the reaper's events keep the card current too ──────────────────────────────────────────────────

class _Result:
    def __init__(self, rows=(), rowcount=None):
        self._rows = list(rows)
        self.rowcount = len(self._rows) if rowcount is None else rowcount

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def scalar(self):
        r = self.first()
        if r is None:
            return None
        return r[0] if isinstance(r, (tuple, list)) else r

    def mappings(self):
        return self


class _Db:
    """Records every statement; answers through (needle, result) handlers, first match wins; counts commits."""

    def __init__(self, handlers=()):
        self.handlers, self.calls, self.commits = list(handlers), [], 0

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.calls.append(sql)
        for needle, res in self.handlers:
            if needle in sql:
                return res
        return _Result([], rowcount=1)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None


@pytest.fixture
def asked(monkeypatch):
    """Which card refreshes the code asked for, as (order, event seq, the database's commits when it asked)."""
    out, pending, db_ref = [], [], {}

    def _refresh(order_id, seq):           # refresh_soon calls refresh() when it asks: record the ask then
        out.append((order_id, seq, db_ref["db"].commits if "db" in db_ref else None))

        async def _nothing():
            return None
        return _nothing()

    def _spawn(coro, what=None):
        pending.append(coro)
    monkeypatch.setattr(glc, "refresh", _refresh)
    monkeypatch.setattr(cs, "spawn", _spawn)

    def drain_():
        while pending:
            run(pending.pop(0))
        return list(out)
    return types.SimpleNamespace(of=lambda db: db_ref.__setitem__("db", db), drain=drain_)


def test_the_cards_refresh_follows_an_order_that_expired_and_skips_what_it_does_not_show(asked):
    # BASE: an expired order asks for no refresh, so its card read "open for bids" for good
    glc.refresh_soon(OID, 3, "expired")
    glc.refresh_soon(OID, 4, "stuck_reverted")
    glc.refresh_soon(OID, 5, "xf_stage_retained")      # control: a step the card does not show asks for nothing
    glc.refresh_soon(OID, 6, "settled")                 # control: as before
    assert [(o, q) for o, q, _ in asked.drain()] == [(OID, 3), (OID, 4), (OID, 6)]


def _reaper_db(**over):
    handlers = {
        "FROM guild_remote_stakes": _Result([]),
        "WHERE status='open' AND deadline IS NOT NULL": _Result([]),
        "WHERE status='awarded' AND deadline IS NOT NULL": _Result([]),
        "WHERE o.status IN ('settling','resolving')": _Result([]),
        "WHERE status='submitted' AND submitted_at": _Result([]),
        "SELECT COALESCE(MAX(seq),0)+1": _Result([(3,)]),
        "stake_status='held'": _Result([]),
    }
    handlers.update(over)
    return _Db(list(handlers.items()))


def _reaper(monkeypatch, db):
    from agentvault_registry.background_tasks import guild_order_reaper as R

    @contextlib.asynccontextmanager
    async def _session():
        yield db

    async def _nothing(*a, **k):
        return None
    monkeypatch.setattr(R, "AsyncSessionLocal", _session)
    monkeypatch.setattr(R.guild_escrow, "escrow_payout", _nothing)
    monkeypatch.setattr(guild, "_emit", lambda *a, **k: None)
    return R


def test_an_order_the_reaper_expires_asks_for_its_card_after_the_claim(monkeypatch, asked):
    # BASE: nothing is asked
    db = _reaper_db(**{"WHERE status='open' AND deadline IS NOT NULL": _Result([
        {"id": OID, "poster_did": POSTER, "bounty": "15"}])})
    asked.of(db)
    R = _reaper(monkeypatch, db)
    run(R._sweep_once())
    assert any("'expired'" in q and "INSERT INTO guild_order_events" in q for q in db.calls)
    got = asked.drain()
    assert [(o, q) for o, q, _ in got] == [(OID, 3)] and got[0][2] >= 1      # after the event's commit


def test_an_order_the_reaper_disputes_asks_for_its_card(monkeypatch, asked):
    # BASE: nothing is asked
    from agentvault_registry.crud import crud_disputes
    db = _reaper_db()
    asked.of(db)
    R = _reaper(monkeypatch, db)

    async def _dispute(db_, **kw):
        return types.SimpleNamespace(id=41)
    monkeypatch.setattr(crud_disputes, "create_dispute", _dispute)
    assert run(R._flag_disputed(db, OID, POSTER, OTHER, {"reason": "deadline_missed"}, from_status="awarded")) is True
    got = asked.drain()
    assert [(o, q) for o, q, _ in got] == [(OID, 3)] and got[0][2] >= 1


@pytest.mark.parametrize("stuck,event", [("resolving", "stuck_reverted"), ("settling", "settled")])
def test_a_stuck_order_the_reaper_recovers_asks_for_its_card(monkeypatch, asked, stuck, event):
    # BASE: nothing is asked
    row = {"id": OID, "status": stuck, "poster_did": POSTER, "worker_did": OTHER, "payee_did": None, "bounty": "15",
           "fee_bps": 250, "worker_home_registry": None, "resolved_worker_amt": None}
    db = _reaper_db(**{"WHERE o.status IN ('settling','resolving')": _Result([row])})
    asked.of(db)
    R = _reaper(monkeypatch, db)

    async def _nothing(*a, **k):
        return None
    monkeypatch.setattr(guild, "_payout_with_royalty", _nothing)
    monkeypatch.setattr(guild, "_resolve_worker_stake", _nothing)
    assert run(R._sweep_stuck_money_states(db)) == 1
    assert any(f"'{event}'" in q and "INSERT INTO guild_order_events" in q for q in db.calls)
    got = asked.drain()
    assert [(o, q) for o, q, _ in got] == [(OID, 3)] and got[0][2] >= 1


# ── the review's findings (2026-11-08) ─────────────────────────────────────────────────────────────────────────────

def _between_the_checks_and_the_claim(monkeypatch, sql, params):
    """What another request commits after this request's checks and before its claim (the room check is the last step
    before the claim)."""
    real = guild._room_refusal

    async def racing(db, room, agent):
        why = await real(db, room, agent)
        await db.execute(text(sql), params)
        await db.commit()
        return why
    monkeypatch.setattr(guild, "_room_refusal", racing)


def test_a_room_another_naming_claimed_first_is_kept_and_this_naming_refused(env, monkeypatch):
    # GUARD: a claim without its guard overwrote FAR with ROOM and posted a card there
    add_order(env)
    _between_the_checks_and_the_claim(
        monkeypatch, "UPDATE guild_work_orders SET announce_conversation_id = :r WHERE id = :o", {"r": FAR, "o": OID})
    r = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": ROOM}))
    assert r.status_code == 409 and "already has a room" in r.json()["detail"], r.text
    assert order_row(env).announce_conversation_id == FAR and cards(env) == []


def test_an_order_that_ends_before_the_claim_takes_no_room(env, monkeypatch):
    # GUARD: a claim without its guard named a room for an order cancelled in the same moment and posted its card
    add_order(env)
    _between_the_checks_and_the_claim(
        monkeypatch, "UPDATE guild_work_orders SET status = 'cancelled' WHERE id = :o", {"o": OID})
    r = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": ROOM}))
    assert r.status_code == 409 and "cancelled" in r.json()["detail"], r.text
    assert order_row(env).announce_conversation_id is None and cards(env) == []


def test_a_card_not_posted_now_leaves_the_room_named_and_the_answer_says_so(env, monkeypatch):
    # GUARD: the room stands when its card cannot be written, and the answer names no card
    add_order(env)

    async def _fails(*a, **k):
        raise RuntimeError("the card could not be written")
    monkeypatch.setattr(cs, "insert_message", _fails)
    r = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": ROOM}))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["card_message_id"] is None and out["card"].startswith("not posted now"), out
    row = order_row(env)
    assert row.announce_conversation_id == ROOM and row.announce_message_id is None and cards(env) == []


def test_a_card_id_left_from_a_room_that_is_gone_does_not_stand_for_the_new_rooms_card(env):
    # ae6f7ccc4: the answer named msg-stale-0000 and the new room got no card. The room column is ON DELETE SET NULL
    # and the card's id is not, so an order whose room was deleted kept the old card's id; the refresh then updated
    # that message in the new room (a 404 it swallows) instead of posting the card
    add_order(env)
    env.s.execute(text("UPDATE guild_work_orders SET announce_message_id = 'msg-stale-0000' WHERE id = :o"), {"o": OID})
    env.s.commit()
    r = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": ROOM}))
    assert r.status_code == 200, r.text
    (card,) = cards(env, ROOM)
    assert r.json()["card_message_id"] == card.id and order_row(env).announce_message_id == card.id


def test_the_currency_field_says_it_is_a_label_and_the_bounty_moves_in_this_registrys_unit():
    # ae6f7ccc4: "the currency the bounty is stated in", which invites a caller to send EUR or USD, while the escrow
    # always moves this registry's unit and the label goes on to the card, the board and the signed records
    desc = schema_of(G.GUILD_TOOL_SCHEMAS, "theprotocol_guildPostOrder")["properties"]["currency"]["description"]
    assert "label" in desc and "escrowed in this registry's unit whatever it says" in desc, desc


GUILD_CHAPTER = (Path(guild.__file__).resolve().parents[1] / "static" / "new_registry_frontend" / "src" / "assets"
                 / "docs" / "oracle" / "26_guild.md")


def test_the_guild_chapters_reference_names_every_route_and_every_tool():
    # ae6f7ccc4: the room route has no row in the Endpoint Reference (only the prose above names it) and
    # guildSetOrderRoom is not in its list of the Guild's MCP tools; every other route and tool is named there
    chapter = GUILD_CHAPTER.read_text(encoding="utf-8")
    md = chapter.split("\n## Endpoint Reference\n", 1)[1].split("\n## ", 1)[0]
    missing = []
    for route in guild.router.routes:
        path = route.path.replace("{oid}", "{id}")
        for method in sorted(set(route.methods) - {"HEAD"}):
            if f"`{method} {path}`" not in md and f"`{method} {path.removeprefix('/api/v1')}`" not in md:
                missing.append(f"{method} {path}")
    assert missing == [], f"routes the chapter's reference does not name: {missing}"
    (tools_line,) = [ln for ln in md.splitlines() if ln.startswith("The Guild MCP tools wrap these calls:")]
    named = set(re.findall(r"`(guild\w+)`", tools_line))
    tools = {s["name"].removeprefix("theprotocol_") for s in G.GUILD_TOOL_SCHEMAS}
    assert sorted(tools - named) == [], "the Guild's MCP tools the chapter's list leaves out"


def test_the_guided_flow_for_a_guild_order_names_its_room():
    # ae6f7ccc4: the flow teaches a post with no room, the way every order posted through MCP lost its card
    from agentvault_registry.mcp import prompts
    got = prompts.get_prompt("post_guild_task", {"task_description": "Ship it", "bounty": "3"})
    said = got["messages"][0]["content"]["text"]
    assert "room_id=" in said and "theprotocol_guildSetOrderRoom" in said, said


def test_the_tester_contracts_say_what_the_routes_refuse_before_any_escrow():
    # ae6f7ccc4: the post tool's skip said it names no entity and its only refusal is 402, while it refuses
    # intended_worker_did (V0650 (f)) and room_id (V0652 (aa)) with 422 first; and the room tool's said its success path
    # is earned on rooms no tester run has
    from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS
    post = MCP_CONTRACTS["theprotocol_guildPostOrder"]
    assert post.skip_reason and "names NO entity" not in post.skip_reason and not post.arguments
    assert all(w in post.skip_reason for w in ("room_id", "intended_worker_did", "422", "before any escrow"))
    assert "no tester run" in MCP_CONTRACTS[ROOM_TOOL].success_path_unmeasured


# ── naming the same room again ─────────────────────────────────────────────────────────────────────────────────────

def test_naming_the_same_room_again_answers_what_the_first_naming_did(env):
    # the review's change: HTTP 409 "already has a room", so a client retrying after a timeout read its success as a
    # refusal
    add_order(env, status="open", bids=1, events=("posted", "bid"))

    async def go():
        first = await G.guild_set_order_room(agent_auth(), order_id=OID, room_id=ROOM)
        await drain(env)
        again = await G.guild_set_order_room(agent_auth(), order_id=OID, room_id=f" {ROOM} ")
        await drain(env)
        return first, again
    first, again = run(go())
    (card,) = cards(env)
    assert first == {"ok": True, "order_id": OID, "room_id": ROOM, "status": "open", "card_message_id": card.id}
    assert again == first and card.card_rev == 0 and env.failed == []


def test_naming_the_same_room_again_posts_a_card_that_was_not_posted(env, monkeypatch):
    # the review's change: 409, so an order whose card was not posted waited for its next step to get one
    add_order(env, status="awarded", worker=OTHER, events=("posted", "bid", "awarded"), bids=1)
    real = cs.insert_message

    async def _fails(*a, **k):
        raise RuntimeError("the card could not be written")
    monkeypatch.setattr(cs, "insert_message", _fails)
    first = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": ROOM}))
    assert first.status_code == 200 and first.json()["card_message_id"] is None and cards(env) == []
    monkeypatch.setattr(cs, "insert_message", real)
    again = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": ROOM}))
    assert again.status_code == 200, again.text
    (card,) = cards(env, ROOM)
    assert again.json() == {"ok": True, "order_id": OID, "room_id": ROOM, "status": "awarded", "card_message_id": card.id}
    assert order_row(env).announce_message_id == card.id and card.card["data"]["status"] == "awarded"
    assert [e["type"] for e in card.card["data"]["events"]] == ["posted", "bid", "awarded"]


def test_naming_the_same_room_again_passes_the_room_check_again(env):
    # the review's change: 409 before any check. A poster that may no longer post in the room it named (here it does
    # not take part in it) gets no card posted there, and the room check says why
    add_order(env, room=FAR)
    poster = cs.Actor("agent", agent_did=POSTER, display_name="session-lead")
    why = run(glc.room_refusal(env.db, FAR, poster))
    r = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": FAR}))
    assert why and r.status_code == 422 and r.json()["detail"] == f"room_id: {why}", r.text
    row = order_row(env)
    assert row.announce_conversation_id == FAR and row.announce_message_id is None and cards(env) == []


def test_a_naming_of_the_same_room_that_claimed_it_first_leaves_one_card(env, monkeypatch):
    # the review's change: 409. The poster's retry racing its first naming: the one that claims second answers the
    # same card (posting it when the first has not yet)
    add_order(env)
    _between_the_checks_and_the_claim(
        monkeypatch, "UPDATE guild_work_orders SET announce_conversation_id = :r WHERE id = :o", {"r": ROOM, "o": OID})
    r = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": ROOM}))
    assert r.status_code == 200, r.text
    (card,) = cards(env)
    assert r.json()["card_message_id"] == card.id and order_row(env).announce_message_id == card.id


@pytest.mark.parametrize("ended", ["settled", "cancelled", "expired"])
def test_naming_the_room_of_an_order_that_ended_is_refused_as_before(env, ended):
    # control (green on the review's change): an order that ended takes no room, its own named room included
    add_order(env, status=ended, room=ROOM, events=("posted", ended))
    r = run(call(env, "POST", f"/api/v1/guild/orders/{OID}/room", json={"room_id": ROOM}))
    assert r.status_code == 409 and ended in r.json()["detail"], r.text
    assert cards(env) == []
