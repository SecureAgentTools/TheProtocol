"""V0659 (o) (order gwo_d7ce94c88a55f629c17b4ff7): an owner sees what his agents post, marked as his agent's.

The maintainer, in the sessions' room (seq 1833): "if any of my agents use any card, i should also see it ... maybe opake or
some other indicator/distinction so the dev knows this is from his agent and not posted by him/his dev account." Every
message and card one of a developer's own agents posts in a thread he can read reaches his view, and each read he makes
says which lines are his agent's: `sender_is_my_agent`, decided by the registry (the sending agent's creator is the
reader), on the thread read, on the sync feed and on his live copy of a new line. His own lines, another member's agent
and a rail's card are never marked; the same line reads unmarked to anyone else.

One case per card type the vocabulary has, read from the vocabulary itself (chat_service.KNOWN_CARD_TYPES), so a new
card type fails here until it has a sample and reaches the owner too. Through the real chat router over real (SQLite)
rows: a client card through the chat route as the agent, and every rail-only card through the shared write path
(_send_and_fan_out) with his agent as the sender. That is how an agent's own rail-only cards are written (a service's call
and answer, a holding certificate, an approval or a choice it asks); for the cards a rail writes as itself
(engagement.*, org.work.receipt, guild.order.live) and the decisions a developer posts (approval.decided,
choice.decided) those cases ask "if his agent were the sender", and the cases under "the cards his agent does not write"
read each from its own writer. BASE (origin/v0658/cut 4b79322d7): no read answers the field, and his service agent's
answer never reaches his open view live in a thread he holds no seat in; every case fails there but the two vocabulary
controls and the seatless service agent (which only this branch's first change broke). REVIEW (98edfcf03, this branch
before session-code's review fixes): the line an approval's use posts and his stand-in's away reply went out live naming
no owner, and his service agent's answer reached his open view in a thread his own read refuses. The cases marked
control pass on REVIEW.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime
import json
import sys
import types

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text as sa_text
from sqlalchemy.dialects import postgresql

from agentvault_registry import models
from agentvault_registry.background_tasks import leader
from agentvault_registry.database import get_db
from agentvault_registry.routers import chat as chat_router
from agentvault_registry.security import get_current_actor_for_read
from agentvault_registry.services import chat_service as cs
from tests._sqlite_db import sqlite_db

OWNER, MEMBER, STRANGER = 6, 7, 9
ORG, ROOM, DM, SVC = "org-sessions", "room-sessions", "dm-household", "svc-household"
SESSION = "did:theprotocol:eu.test:session-lead"         # the owner's own agent, seated in his organization's room
PEER = "did:theprotocol:eu.test:member-agent"            # another member's agent in the same room
NAMES = {f"dev:{OWNER}": "maintainer", f"dev:{MEMBER}": "a member", f"dev:{STRANGER}": "a stranger",
         f"agt:{SESSION.lower()}": "session-lead", f"agt:{PEER.lower()}": "member-agent"}
ORDER = "gwo_0123456789abcdef01234567"
APR = "apr_" + "a" * 32
SHA = "0" * 64


def card(ctype: str) -> dict:
    """A valid card of each type the vocabulary has (validated below), as its writer posts it."""
    data = {
        "pay.request": {"amount": "12.5", "currency": "ECU", "memo": "the proof run"},
        "pay.receipt": {"amount": "12.5", "currency": "ECU", "tx_id": "tx-v0659"},
        "agent.card": {"did": PEER, "name": "member-agent"},
        "contract.offer": {"ref": "ctr_v0659", "title": "Translate the handbook"},
        "guild.order": {"ref": ORDER, "title": "Write the proxy's MQTT source"},
        "media": {"attachment_id": "att-v0659", "name": "report.md", "mime": "text/markdown", "bytes": 120},
        "applet": {"title": "Pick a slot", "fields": [{"kind": "text", "key": "note", "label": "Note"}],
                   "action": {"kind": "open_reply", "label": "Send"}},
        "exchange.listing": {"symbol": "SMKD", "display_name": "Samarkand Freight Lines"},
        "engagement.proposal": {"title": "Audit the ledger", "total": "40", "currency": "ECU"},
        "engagement.counter": {"title": "Audit the ledger", "total": "35", "currency": "ECU"},
        "progress": {"title": "V0659 pair proof", "state": "running", "steps": [{"label": "console", "state": "running"}]},
        "service.call": {"ask": "the weather in Berlin", "status": "dispatched"},
        "service.result": {"ok": True, "stage": "settled", "summary": "delivered"},
        "share.certificate": {"certificate_id": "cert-v0659", "symbol": "SMKD", "qty": 3, "currency": "ECU",
                              "digest": SHA},
        "org.work.receipt": {"kind": "treasury.fund", "amount": "5", "currency": "ECU"},
        "engagement.offer": {"contract_id": "ctr_v0659", "total": "40", "currency": "ECU"},
        "engagement.accepted": {"contract_id": "ctr_v0659", "total": "40", "currency": "ECU"},
        "engagement.milestone": {"contract_id": "ctr_v0659", "seq": 1},
        "engagement.settled": {"contract_id": "ctr_v0659", "seq": 1, "amount": "40", "currency": "ECU"},
        "approval.request": {"approval_id": APR, "title": "Roll V0659 to the sandbox",
                             "expires_at": "2026-11-08T12:00:00+00:00"},
        "approval.decided": {"approval_id": APR, "title": "Roll V0659 to the sandbox", "decision": "approved",
                             "decided_by_developer_id": OWNER},
        "choice.request": {"approval_id": APR, "title": "Which slot", "options": ["morning", "evening"],
                           "expires_at": "2026-11-08T12:00:00+00:00"},
        "choice.decided": {"approval_id": APR, "title": "Which slot", "options": ["morning", "evening"],
                           "decision": "chosen", "decided_by_developer_id": OWNER,
                           "chosen": {"index": 0, "label": "morning"}},
        "guild.order.live": {"order_id": ORDER, "title": "Write the proxy's MQTT source", "status": "open",
                             "events": []},
        "topup.offer": {"amount": "10", "currency": "ECU"},
    }[ctype]
    out = {"v": 1, "type": ctype, "data": data}
    if ctype == "engagement.counter":
        out["refs"] = {"supersedes": "msg-proposal"}
    return out


# Every type a message can carry: the vocabulary's own list (a later-phase type is refused at the write, so it can never
# be a line nobody sees; the control below holds that).
POSTABLE = sorted(cs.CLIENT_POSTABLE_CARDS | cs.RAIL_ONLY_CARDS)


class _Manager:
    """The live delivery's sockets: what each developer's topic was sent."""

    def __init__(self):
        self.sent = []

    async def broadcast_to_subscribers(self, topic, envelope):
        self.sent.append((topic, envelope))

    async def wake_chat(self, keys):
        return None

    async def is_present(self, dev_id):
        return False

    def copies(self, dev_id: int, message_id: str) -> list:
        return [env["data"]["message"] for topic, env in self.sent
                if topic == f"chat:dev:{dev_id}" and env.get("data", {}).get("message", {}).get("id") == message_id]


@pytest.fixture()
def env(monkeypatch):
    async def _no_redis():
        return None
    monkeypatch.setattr(leader, "get_redis", _no_redis)
    mgr = _Manager()
    ws = types.ModuleType("agentvault_registry.routers.websocket")
    ws.manager = mgr
    pn = types.ModuleType("agentvault_registry.background_tasks.push_notify")
    rh = types.ModuleType("agentvault_registry.background_tasks.reactor_helpers")

    async def _quiet(*a, **k):
        return 0
    pn.notify = _quiet
    rh.dispatch_webhook_for_agents = _quiet
    for mod in (ws, pn, rh):
        monkeypatch.setitem(sys.modules, mod.__name__, mod)

    async def _open(*a, **k):
        return True
    monkeypatch.setattr(cs, "_rate_gate", _open)         # the abuse gates are not what this measures

    async def _no_notices(*a, **k):
        return None
    monkeypatch.setattr(cs, "_notify_absent", _no_notices)

    async def _names(db_, keys):                            # PostgreSQL's = ANY(...) in the real lookup
        return {k: NAMES.get(k, k) for k in keys}
    monkeypatch.setattr(cs, "display_names", _names)

    db = sqlite_db(models.Developer, models.Organization, models.OrganizationLogo, models.OrganizationMember,
                   models.Agent, models.AgentCard, models.Conversation, models.ConversationParticipant,
                   models.ChatMessage, models.ChatBoardRevision, models.ChatBlock, models.ChatCardUpdate,
                   models.DeveloperPref)

    async def _owners(db_, dids):                           # the same lookup over the agents rows, portably
        rows = db.sync.execute(sa_text("SELECT did, creator_developer_id FROM agents")).all()
        found = {str(r[0]).lower(): r[1] for r in rows}
        return {d: found.get(str(d).lower()) for d in dids if d}
    monkeypatch.setattr(cs, "agent_owner_map", _owners)

    s = db.sync
    s.connection().connection.driver_connection.create_function(
        "now", 0, lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"))
    # the media card's preview read asks the attachments table (raw SQL, no model)
    s.execute(sa_text("CREATE TABLE chat_attachments (id TEXT PRIMARY KEY, conversation_id TEXT, filename TEXT, "
                      "mime TEXT, bytes INTEGER, storage_path TEXT, deleted_at TEXT)"))
    for i in (OWNER, MEMBER, STRANGER):
        s.add(models.Developer(id=i, name=f"dev{i}", email=f"d{i}@example.test", hashed_password="x"))
    s.flush()
    s.add(models.Organization(id=ORG, name="TheProtocol Sessions", slug="sessions", owner_id=OWNER, is_active=True))
    s.flush()
    s.add(models.OrganizationMember(id="om-1", organization_id=ORG, developer_id=OWNER, role="owner", is_active=True))
    s.add(models.OrganizationMember(id="om-2", organization_id=ORG, developer_id=MEMBER, role="member", is_active=True))
    for i, (did, owner) in enumerate(((SESSION, OWNER), (PEER, MEMBER))):
        s.add(models.Agent(did=did, client_id=f"client-{i}", hashed_client_secret="x", creator_developer_id=owner,
                           organization_id=ORG, status="active"))
    s.add(models.Conversation(id=ROOM, kind="org", org_id=ORG, title="TheProtocol Sessions",
                              created_by_ptype="developer", created_by_id=str(OWNER), dm_pair_key=f"org|{ORG}"))
    for i, (ptype, dev, did) in enumerate((("developer", OWNER, None), ("developer", MEMBER, None),
                                           ("agent", None, SESSION), ("agent", None, PEER))):
        s.add(models.ConversationParticipant(id=f"pr-{i}", conversation_id=ROOM, ptype=ptype, developer_id=dev,
                                             agent_did=did, role="owner" if dev == OWNER else "member",
                                             state="active"))
    # a thread the owner holds no seat in: his agent and a developer from outside (he reads it as his household)
    s.add(models.Conversation(id=DM, kind="dm", created_by_ptype="agent", created_by_id=SESSION,
                              dm_pair_key=cs.pair_key("dm", cs.principal_key("agent", SESSION),
                                                      cs.principal_key("developer", STRANGER))))
    s.add(models.ConversationParticipant(id="pd-1", conversation_id=DM, ptype="agent", agent_did=SESSION,
                                         role="owner", state="active"))
    s.add(models.ConversationParticipant(id="pd-2", conversation_id=DM, ptype="developer", developer_id=STRANGER,
                                         role="member", state="active"))
    # a service thread between the member's agent (the caller) and the owner's agent (the service), agents only
    s.add(models.Conversation(id=SVC, kind="agent_service", created_by_ptype="agent", created_by_id=PEER,
                              dm_pair_key=cs.pair_key("agent_service", cs.principal_key("agent", PEER),
                                                      cs.principal_key("agent", SESSION))))
    s.add(models.ConversationParticipant(id="ps-1", conversation_id=SVC, ptype="agent", agent_did=PEER,
                                         role="owner", state="active"))
    s.add(models.ConversationParticipant(id="ps-2", conversation_id=SVC, ptype="agent", agent_did=SESSION,
                                         role="member", state="active"))
    s.commit()

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
        kind, ident, *more = who["as"]          # more: the agent credential's own fields (its owner's session)
        if kind == "developer":
            return {"kind": "developer", "developer_id": ident,
                    "developer": types.SimpleNamespace(id=ident, name=f"dev{ident}")}
        return {"kind": "agent", "agent_did": ident, "agent": types.SimpleNamespace(name=NAMES[f"agt:{ident.lower()}"]),
                **(more[0] if more else {})}
    from agentvault_registry import security
    for dep in (get_current_actor_for_read, getattr(security, "get_current_actor_for_read_or_key", None)):
        if dep:
            app.dependency_overrides[dep] = caller
    return types.SimpleNamespace(app=app, db=db, who=who, mgr=mgr)


async def _call(env, method, path, who=("developer", OWNER), **kw):
    env.who["as"] = who
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://t", timeout=30) as c:
        r = await c.request(method, path, **kw)
    await asyncio.sleep(0.05)              # the background fan-out
    return r


def _agent(did: str) -> cs.Actor:
    return cs.Actor("agent", agent_did=did, display_name=NAMES[f"agt:{did.lower()}"], sent_with="agent")


def _row(env, conv_id: str, did: str):
    return env.db.sync.query(models.ConversationParticipant).filter_by(conversation_id=conv_id, agent_did=did).one()


async def _post(env, ctype: str, *, conv_id: str = ROOM, did: str = SESSION) -> dict:
    """His agent posts a card. A client type goes through the chat route as the agent itself. A rail-only type goes
    through the shared write path (_send_and_fan_out) with the agent as the sender: the path its rail takes for
    service.call, service.result, share.certificate, approval.request and choice.request. The other rail-only types are
    written by a rail as a system sender or by the developer who decided; here they stand for such a card if an agent
    were its sender, and the cases under "the cards his agent does not write" read each from its own writer."""
    ref = f"v0659-{ctype}"[:64]
    if ctype in cs.CLIENT_POSTABLE_CARDS:
        r = await _call(env, "POST", f"/api/v1/chat/conversations/{conv_id}/messages", who=("agent", did),
                        json={"kind": "card", "card": card(ctype), "client_ref": ref})
        assert r.status_code == 201, r.text
        return r.json()["message"]
    conv = await cs._get_conversation(env.db, conv_id)
    msg = await chat_router._send_and_fan_out(env.db, conv, _row(env, conv_id, did), _agent(did), "card", None,
                                              card(ctype), ref, rail_author=True)
    await asyncio.sleep(0.05)
    return msg


async def _thread(env, conv_id: str = ROOM, who=("developer", OWNER)) -> dict:
    r = await _call(env, "GET", f"/api/v1/chat/conversations/{conv_id}/messages", who=who)
    assert r.status_code == 200, r.text
    return {m["id"]: m for m in r.json()["messages"]}


async def _sync(env, who=("developer", OWNER)) -> dict:
    r = await _call(env, "GET", "/api/v1/chat/sync", who=who)
    assert r.status_code == 200, r.text
    out = {}
    for m in r.json()["messages"]:
        if isinstance(m.get("card"), str):      # a JSON column read as text through a raw statement (SQLite; asyncpg
            m["card"] = json.loads(m["card"])   # decodes it to an object)
        out[m["id"]] = m
    return out


def run(coro):
    return asyncio.run(coro)


# ── control: the vocabulary is covered ──────────────────────────────────────────────────────────────────────────────

def test_every_card_type_of_the_vocabulary_has_a_valid_sample_here():
    """control: a type added to the vocabulary fails here until it has a sample (and so a case below)."""
    assert set(POSTABLE) | set(cs.LATER_PHASE_CARDS) == set(cs.KNOWN_CARD_TYPES)
    for t in POSTABLE:
        assert cs.validate_card(card(t), rail_author=True) is None, t
    for t in cs.LATER_PHASE_CARDS:   # the door is not resolved here: refused, as every closed door refuses it
        assert cs.validate_card(card(t), rail_author=True) is not None, t


def test_a_later_phase_card_is_refused_at_the_write_so_no_such_line_exists(env):
    """control: topup.offer (the fiat door, dark behind three locks) is refused when posted, so it is never a line in a
    thread the owner reads and does not see."""
    async def go():
        for t in sorted(cs.LATER_PHASE_CARDS):
            r = await _call(env, "POST", f"/api/v1/chat/conversations/{ROOM}/messages", who=("agent", SESSION),
                            json={"kind": "card", "card": card(t), "client_ref": f"v0659-{t}"})
            assert r.status_code == 422, r.text
        assert env.db.sync.query(models.ChatMessage).count() == 0
    run(go())


# ── 1 and 2: every card his agent posts reaches his view, marked as his agent's ─────────────────────────────────────

@pytest.mark.parametrize("ctype", POSTABLE)
def test_his_agents_card_reaches_his_thread_read_marked(env, ctype):
    async def go():
        posted = await _post(env, ctype)
        mine = (await _thread(env))[posted["id"]]
        assert mine["kind"] == "card" and mine["card"]["type"] == ctype and mine["card"]["data"] == card(ctype)["data"]
        assert mine["sender_ptype"] == "agent" and mine["sender_id"] == SESSION
        assert mine.get("sender_is_my_agent") is True                 # BASE: the read does not say whose agent it is
        assert mine["sender_name"] == "session-lead"                  # with the agent's name
        theirs = (await _thread(env, who=("developer", MEMBER)))[posted["id"]]
        assert theirs.get("sender_is_my_agent") is False              # the same line, read by another member
    run(go())


@pytest.mark.parametrize("ctype", POSTABLE)
def test_his_agents_card_reaches_his_sync_feed_marked(env, ctype):
    async def go():
        posted = await _post(env, ctype)
        mine = (await _sync(env))[posted["id"]]
        assert mine["card"]["type"] == ctype
        assert mine.get("sender_is_my_agent") is True                 # BASE: the feed does not say whose agent it is
        assert (await _sync(env, who=("developer", MEMBER)))[posted["id"]].get("sender_is_my_agent") is False
    run(go())


@pytest.mark.parametrize("ctype", POSTABLE)
def test_his_agents_card_reaches_his_open_view_live_marked(env, ctype):
    async def go():
        posted = await _post(env, ctype)
        mine = env.mgr.copies(OWNER, posted["id"])
        assert len(mine) == 1 and mine[0]["card"]["type"] == ctype
        assert mine[0].get("sender_is_my_agent") is True              # BASE: his live copy is not marked
        theirs = env.mgr.copies(MEMBER, posted["id"])
        assert len(theirs) == 1 and theirs[0].get("sender_is_my_agent") is not True
    run(go())


def test_his_agents_text_line_is_marked_too(env):
    async def go():
        r = await _call(env, "POST", f"/api/v1/chat/conversations/{ROOM}/messages", who=("agent", SESSION),
                        json={"kind": "text", "body": "V0659 (o) is in", "client_ref": "v0659-text-1"})
        assert r.status_code == 201, r.text
        mid = r.json()["message"]["id"]
        assert (await _thread(env))[mid].get("sender_is_my_agent") is True
        assert (await _sync(env))[mid].get("sender_is_my_agent") is True
        assert env.mgr.copies(OWNER, mid)[0].get("sender_is_my_agent") is True
    run(go())


# ── his own lines stay his; the mark is the reader's ────────────────────────────────────────────────────────────────

def test_his_own_line_is_never_marked_as_his_agents(env):
    async def go():
        r = await _call(env, "POST", f"/api/v1/chat/conversations/{ROOM}/messages",
                        json={"kind": "text", "body": "approved", "client_ref": "v0659-own-1"})
        assert r.status_code == 201, r.text
        mid = r.json()["message"]["id"]
        mine = (await _thread(env))[mid]
        assert (mine["sender_ptype"], mine.get("sender_is_my_agent")) == ("developer", False)
        assert (await _sync(env))[mid].get("sender_is_my_agent") is False
        assert all(m.get("sender_is_my_agent") is not True for m in env.mgr.copies(OWNER, mid))
    run(go())


def test_another_members_agent_is_his_owners_not_the_rooms_owners(env):
    async def go():
        posted = await _post(env, "progress", did=PEER)
        assert (await _thread(env))[posted["id"]].get("sender_is_my_agent") is False
        assert (await _thread(env, who=("developer", MEMBER)))[posted["id"]].get("sender_is_my_agent") is True
        assert (await _sync(env, who=("developer", MEMBER)))[posted["id"]].get("sender_is_my_agent") is True
        assert env.mgr.copies(MEMBER, posted["id"])[0].get("sender_is_my_agent") is True
        assert env.mgr.copies(OWNER, posted["id"])[0].get("sender_is_my_agent") is not True
    run(go())


def test_an_agent_reading_its_own_line_is_not_its_own_agent(env):
    async def go():
        posted = await _post(env, "progress")
        assert (await _thread(env, who=("agent", SESSION)))[posted["id"]].get("sender_is_my_agent") is False
        assert (await _sync(env, who=("agent", SESSION)))[posted["id"]].get("sender_is_my_agent") is False
    run(go())


def test_a_line_he_typed_as_his_agent_says_so_beside_the_mark(env):
    """control: a line he typed as his agent through his own session is his agent's line by its sender
    (sender_is_my_agent: the sending agent is his) and his own hand by sent_by_owner; the console draws it as his own
    (services/chat/myAgent.ts reads both), and an API reader reads the same two fields."""
    async def go():
        r = await _call(env, "POST", f"/api/v1/chat/conversations/{ROOM}/messages",
                        who=("agent", SESSION, {"owner_session": OWNER}),
                        json={"kind": "text", "body": "typed as session-lead", "client_ref": "v0659-as-agent-1"})
        assert r.status_code == 201, r.text
        mid = r.json()["message"]["id"]
        for read in ((await _thread(env))[mid], (await _sync(env))[mid], env.mgr.copies(OWNER, mid)[0]):
            assert (read["sender_ptype"], read["sent_by_owner"], read.get("sender_is_my_agent")) == ("agent", True, True)
        theirs = (await _thread(env, who=("developer", MEMBER)))[mid]
        assert (theirs["sent_by_owner"], theirs.get("sender_is_my_agent")) == (True, False)
    run(go())


# ── the cards his agent does not write: each from its own writer, never marked as his agent's ───────────────────────

def test_a_guild_card_reaches_him_as_the_guilds(env):
    """control: the Guild rail posts an order's card as itself (services/guild_live_card.py: guild_sender(), its client
    ref, rail_author) into the room the poster's agent named: it reaches him, and it is the rail's line (a system
    sender), not his agent's."""
    async def go():
        from agentvault_registry.services import guild_live_card as glc
        conv = await cs._get_conversation(env.db, ROOM)
        msg, dup = await cs.insert_message(env.db, conv, None, glc.guild_sender(), "card", None,
                                           card("guild.order.live"), client_ref=glc.card_client_ref(ORDER),
                                           rail_author=True, mark_read=False)
        assert not dup
        mine = (await _thread(env))[msg.id]
        assert (mine["sender_ptype"], mine["card"]["type"]) == ("system", "guild.order.live")
        assert mine.get("sender_is_my_agent") is False
        assert (await _sync(env))[msg.id].get("sender_is_my_agent") is False
    run(go())


@pytest.mark.parametrize("ctype", sorted(t for t in cs.RAIL_ONLY_CARDS if t.startswith("engagement.")))
def test_a_contract_rails_card_reaches_him_as_the_rails(env, ctype):
    """control: the contract rail (services/deal_thread_events.py, its own _thread and _post) writes a contract's cards
    into the deal thread of the two agents as itself: the thread his agent is in reaches him, read, synced and live, and
    every one is the rail's line."""
    async def go():
        from agentvault_registry.services import deal_thread_events as dte
        conv = await dte._thread(env.db, SESSION, PEER, create=True)
        await dte._post(env.db, conv, ctype, card(ctype)["data"], {"contract_id": "ctr_v0659"}, f"v0659-{ctype}")
        await asyncio.sleep(0.05)
        msg = env.db.sync.query(models.ChatMessage).filter_by(conversation_id=conv.id).one()
        mine = (await _thread(env, conv_id=conv.id))[msg.id]
        assert (mine["sender_ptype"], mine["card"]["type"], mine.get("sender_is_my_agent")) == ("system", ctype, False)
        assert (await _sync(env))[msg.id].get("sender_is_my_agent") is False
        live = env.mgr.copies(OWNER, msg.id)
        assert len(live) == 1 and live[0].get("sender_is_my_agent") is not True
    run(go())


def test_the_organizations_ledger_card_reaches_him_as_the_ledgers(env):
    """control: an organization's money rails post their receipt through post_org_receipt (services/org_room_events.py)
    as the room's Treasury: it reaches him, read, synced and live, and it is the ledger's line."""
    async def go():
        from agentvault_registry.services import org_room_events as ore
        await ore.post_org_receipt(env.db, ORG, kind="treasury.fund", amount="5", currency="ECU", ref="v0659-fund-1")
        await asyncio.sleep(0.05)
        msg = env.db.sync.query(models.ChatMessage).filter_by(conversation_id=ROOM).one()
        mine = (await _thread(env))[msg.id]
        assert (mine["sender_ptype"], mine["card"]["type"], mine.get("sender_is_my_agent")) == (
            "system", "org.work.receipt", False)
        assert (await _sync(env))[msg.id].get("sender_is_my_agent") is False
        live = env.mgr.copies(OWNER, msg.id)
        assert len(live) == 1 and live[0].get("sender_is_my_agent") is not True
    run(go())


@pytest.mark.parametrize("ctype", ["approval.decided", "choice.decided"])
def test_a_decision_card_is_the_line_of_the_developer_who_decided(env, ctype):
    """control: the approval rail posts a decision as the developer who decided (routers/chat.py decide_approvals:
    insert_message as him, then the delivery naming him as the sender's household): his own decision is his own line,
    and another member reads it unmarked too."""
    async def go():
        conv = await cs._get_conversation(env.db, ROOM)
        me = cs.Actor("developer", developer_id=OWNER, display_name="maintainer")
        seat = env.db.sync.query(models.ConversationParticipant).filter_by(conversation_id=ROOM,
                                                                          developer_id=OWNER).one()
        msg, dup = await cs.insert_message(env.db, conv, seat, me, "card", None, card(ctype),
                                           client_ref=f"aprdec-v0659-{ctype}", rail_author=True)
        assert not dup
        payload = cs.serialize_message(msg)
        payload["sender_name"] = me.display_name
        cs.deliver(conv.id, conv.kind, payload, await cs.recipients_snapshot(env.db, conv, me), me.display_name,
                   sender_owner_dev_id=OWNER)
        await asyncio.sleep(0.05)
        mine = (await _thread(env))[msg.id]
        assert (mine["sender_ptype"], mine.get("sender_is_my_agent")) == ("developer", False)
        assert (await _sync(env))[msg.id].get("sender_is_my_agent") is False
        assert all(m.get("sender_is_my_agent") is not True for m in env.mgr.copies(OWNER, msg.id))
        assert (await _thread(env, who=("developer", MEMBER)))[msg.id].get("sender_is_my_agent") is False
    run(go())


# ── the lines his agent writes outside the shared write path ────────────────────────────────────────────────────────

APPROVAL_SHA = "ab" * 32


def _approval_row(request_message_id: str):
    """An approval his agent asked in his room, approved by him, unused (the shape chat_approvals.fetch returns)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return types.SimpleNamespace(
        id=APR, conversation_id=ROOM, org_id=ORG, requester_agent_did=SESSION, client_ref="ref-apr",
        request_message_id=request_message_id, title="Roll V0659 to the sandbox", reason=None, unlocks=None,
        artifact_sha256=APPROVAL_SHA, artifact_label="roll_v0659.sh", production_impact=True, facts={},
        facts_digest="d" * 64, status="approved", created_at=now - datetime.timedelta(minutes=5),
        expires_at=now + datetime.timedelta(hours=1), decided_at=now - datetime.timedelta(minutes=1),
        decided_by_developer_id=OWNER, decided_by_role="owner", decision_note=None, decision_via=None,
        presence_method=None, presence_challenge_id=None, decision_statement=None,
        consumed_at=None, consumed_by_agent_did=None, consumed_act=None, consumed_act_sha256=None)


def test_his_agents_approval_use_line_reaches_him_marked(env, monkeypatch):
    """When his agent uses his approval (POST /chat/approvals/{id}/consume), the registry posts one line under the card
    as the agent, and delivers it itself (not through the shared write path): his live copy of it is his agent's too.
    The approval record's reads are stood in for (the rail's own tests hold them); the room, the agent's seat, the line
    and its delivery are the real ones. REVIEW: his copy came unmarked, so a room whose page no longer held the agent's
    request drew the line as his own hand."""
    from agentvault_registry.security import get_current_agent
    from agentvault_registry.services import admin_audit
    from agentvault_registry.services import chat_approvals as ca

    async def go():
        request = await _post(env, "approval.request")
        row = _approval_row(request["id"])
        now = datetime.datetime.now(datetime.timezone.utc)

        async def _fetch(db_, aid, fresh=False):
            return row if aid == APR else None

        async def _now(db_):
            return now

        async def _org(db_, org_id):
            return {"owner_id": OWNER, "chat_enabled": True, "settings": {}}

        async def _role(*a, **k):
            return "owner"

        async def _mark(db_, aid, *, agent_did, act_label, act_sha256):
            row.consumed_at, row.consumed_by_agent_did, row.consumed_act, row.consumed_act_sha256 = (
                now, agent_did, act_label, act_sha256)
            return now

        async def _names(db_, rows):
            return ({SESSION: "session-lead"}, {OWNER: "maintainer"})

        async def _audit(db_, **k):
            return None
        for name, fn in (("fetch", _fetch), ("db_now", _now), ("org_facts", _org), ("decider_role", _role),
                         ("mark_consumed", _mark), ("names_for", _names)):
            monkeypatch.setattr(ca, name, fn)
        monkeypatch.setattr(admin_audit, "log_chat_action", _audit)
        monkeypatch.setenv("CHAT_APPROVALS_ENABLED", "true")
        env.app.dependency_overrides[get_current_agent] = lambda: types.SimpleNamespace(did=SESSION,
                                                                                        name="session-lead")
        env.mgr.sent.clear()
        r = await _call(env, "POST", f"/api/v1/chat/approvals/{APR}/consume", who=("agent", SESSION),
                        json={"act_label": "V0659 sandbox roll", "act_sha256": APPROVAL_SHA, "production": True})
        assert r.status_code == 200, r.text
        used = env.db.sync.query(models.ChatMessage).filter_by(conversation_id=ROOM, client_ref=f"aprused-{APR}").one()
        assert (used.sender_ptype, used.sender_id) == ("agent", SESSION)
        mine = env.mgr.copies(OWNER, used.id)
        assert len(mine) == 1 and mine[0].get("sender_is_my_agent") is True        # REVIEW: no mark on his copy
        theirs = env.mgr.copies(MEMBER, used.id)
        assert len(theirs) == 1 and theirs[0].get("sender_is_my_agent") is not True
        assert (await _thread(env))[used.id].get("sender_is_my_agent") is True
    run(go())


def test_his_stand_ins_away_reply_reaches_him_marked(env, monkeypatch):
    """A stranger's first message to him while he is away: his designated stand-in (his own agent) answers once
    (chat_service.away_answer), delivered by the create route itself. The thread waits in his Requests until he
    accepts, and his stand-in's seat in it is what brings it to him (his sync and his household): its answer reaches his
    open view live, marked as his agent's, and the stranger's copy is not marked. His contact policy is read as open
    (its columns are not on the developers model these rows are made from). REVIEW: nothing reached him live."""
    from agentvault_registry.services import contact_policy

    async def _open_contact(db_, developer_id):
        return {"policy": "open", "effective": "open", "price": None, "currency": None, "purse_did": None,
                "genesis": None}
    monkeypatch.setattr(contact_policy, "declaration", _open_contact)

    async def go():
        env.db.sync.add(models.DeveloperPref(developer_id=OWNER, key=cs.AWAY_PREF_KEY,
                                             value={"enabled": True, "agent_did": SESSION}))
        env.db.sync.commit()
        r = await _call(env, "POST", "/api/v1/chat/conversations", who=("developer", STRANGER),
                        json={"kind": "dm", "target": {"ptype": "developer", "developer_id": OWNER},
                              "first_message": {"kind": "text", "body": "a question", "client_ref": "v0659-knock-1"}})
        assert r.status_code == 201, r.text
        away = r.json()["away_reply"]
        assert away and (away["sender_ptype"], away["sender_id"]) == ("agent", SESSION), r.json()
        conv_id = r.json()["conversation_id"]
        seat = env.db.sync.query(models.ConversationParticipant).filter_by(conversation_id=conv_id,
                                                                          developer_id=OWNER).one()
        assert seat.state == "pending"                                  # a request until he accepts it
        mine = env.mgr.copies(OWNER, away["id"])
        assert len(mine) == 1 and mine[0].get("sender_is_my_agent") is True        # REVIEW: no copy reached him
        theirs = env.mgr.copies(STRANGER, away["id"])
        assert len(theirs) == 1 and theirs[0].get("sender_is_my_agent") is not True
        assert (await _thread(env, conv_id=conv_id))[away["id"]].get("sender_is_my_agent") is True
        assert (await _sync(env))[away["id"]].get("sender_is_my_agent") is True
    run(go())


# ── a thread he holds no seat in ────────────────────────────────────────────────────────────────────────────────────

def test_a_thread_he_reads_as_his_agents_owner_marks_its_lines(env):
    async def go():
        posted = await _post(env, "progress", conv_id=DM)
        mine = (await _thread(env, conv_id=DM))[posted["id"]]          # the household read seats nobody it may not
        assert mine.get("sender_is_my_agent") is True
        assert (await _sync(env))[posted["id"]].get("sender_is_my_agent") is True
        assert env.mgr.copies(OWNER, posted["id"])[0].get("sender_is_my_agent") is True
        theirs = (await _thread(env, conv_id=DM, who=("developer", STRANGER)))[posted["id"]]
        assert theirs.get("sender_is_my_agent") is False
    run(go())


def test_his_service_agents_answer_reaches_his_open_view_live(env):
    """service.result is posted by the service-call rail as the SERVICE agent, while the caller is the one who called:
    the owner of the service agent gets his copy, marked, though he holds no seat and the caller is not his."""
    async def go():
        conv = await cs._get_conversation(env.db, SVC)
        msg = await chat_router._send_and_fan_out(
            env.db, conv, _row(env, SVC, PEER), _agent(PEER), "card", None, card("service.result"),
            cs.result_client_ref("v0659-svc-call-1"), rail_author=True, sender_override=_agent(SESSION))
        await asyncio.sleep(0.05)
        assert msg["sender_id"] == SESSION
        mine = env.mgr.copies(OWNER, msg["id"])
        assert len(mine) == 1, env.mgr.sent                            # BASE: nothing reached the service's owner
        assert mine[0].get("sender_is_my_agent") is True
        assert all(m.get("sender_is_my_agent") is not True for m in env.mgr.copies(MEMBER, msg["id"]))
        assert (await _thread(env, conv_id=SVC))[msg["id"]].get("sender_is_my_agent") is True
    run(go())


def test_his_service_agent_without_a_seat_brings_him_no_copy(env):
    """He reads a thread he holds no seat in through his agent's ACTIVE seat (the household rule). Where his service
    agent's row is not active (born 'left' because it blocks the caller), his read refuses the thread, and the live
    delivery gives him no copy of the answer posted as his agent either; the caller's owner still gets his. REVIEW: his
    open view got the line of a thread his read refuses."""
    async def go():
        _row(env, SVC, SESSION).state = "left"
        env.db.sync.commit()
        conv = await cs._get_conversation(env.db, SVC)
        msg = await chat_router._send_and_fan_out(
            env.db, conv, _row(env, SVC, PEER), _agent(PEER), "card", None, card("service.result"),
            cs.result_client_ref("v0659-svc-call-2"), rail_author=True, sender_override=_agent(SESSION))
        await asyncio.sleep(0.05)
        assert msg["sender_id"] == SESSION
        assert env.mgr.copies(OWNER, msg["id"]) == [], env.mgr.sent          # REVIEW: one copy, marked
        assert len(env.mgr.copies(MEMBER, msg["id"])) == 1
        assert (await _call(env, "GET", f"/api/v1/chat/conversations/{SVC}/messages")).status_code == 403
    run(go())


# ── the ownership read ──────────────────────────────────────────────────────────────────────────────────────────────

def test_the_ownership_read_is_one_statement_over_the_pages_senders():
    sql = str(cs.own_agents_statement().compile(dialect=postgresql.dialect()))
    flat = " ".join(sql.split())
    assert flat == ("SELECT lower(did) FROM agents WHERE creator_developer_id = %(me)s "
                    "AND lower(did) IN (__[POSTCOMPILE_dids])")      # the senders on the page, never every agent


def test_an_agent_reader_and_a_page_without_agents_ask_nothing():
    calls = []

    class _Db:
        async def execute(self, *a, **k):
            calls.append(a)
            raise AssertionError("no read expected")

    async def go():
        assert await cs.own_agent_senders(_Db(), cs.Actor("agent", agent_did=SESSION), [("agent", PEER)]) == set()
        assert await cs.own_agent_senders(_Db(), cs.Actor("developer", developer_id=OWNER),
                                          [("developer", "6"), ("system", "guild")]) == set()
    run(go())
    assert calls == []


def test_the_thread_read_answers_from_the_household_it_already_holds():
    """The thread read holds the reader's household (his own key and his agents') for its counterparty already: the
    mark is answered from it, with no read of its own (the same rule: his agents are the ones he created)."""
    class _Db:
        async def execute(self, *a, **k):
            raise AssertionError("no read expected")

    async def go():
        household = {cs.principal_key("developer", OWNER), cs.principal_key("agent", SESSION)}
        got = await cs.own_agent_senders(_Db(), cs.Actor("developer", developer_id=OWNER),
                                         [("agent", SESSION.upper()), ("agent", PEER), ("developer", str(OWNER))],
                                         household=household)
        assert got == {SESSION.lower()}
    run(go())
