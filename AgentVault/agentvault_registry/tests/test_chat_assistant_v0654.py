"""V0654 (ap) (2026-11-02, agentvault2-14): the assistant in OurChat, order gwo_03a846cb91b37628c3c6710a.

The assistant is pickable per identity in the "send as" choice; the
prompt is visible to its author alone; the assistant's answer below it, marked. POST /chat/conversations/{id}/assist asks his
personal assistant (services/assistant_bridge, the bridge's no-tools profile) with the room's recent lines and the
REGISTRY posts the answer, as the identity he sends with (himself, or his agent through his own signed-in session), with
sent_with "assistant". Only the identity's owner, signed in, on an account the bridge serves (admin_credential), where
the bridge is enabled; every refusal a post would meet is asked BEFORE the bridge, and nothing is posted on a refusal.
The prompt is stored nowhere in the room.

Through FastAPI on the real chat router and the real auth chain (the developer and agent lookups, the room's steps, the
fan-out and the bridge calls are replaced); the stored line on a real Postgres (MEMBERSHIP_TEST_DB, a throwaway one it may
WIPE). BASE (V0653's cut, f8f1993fb): no route and no services/assistant_bridge, so every test here fails there.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
from types import SimpleNamespace

import httpx
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.crud import agent as agent_crud
from agentvault_registry.crud import developer as developer_crud
from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import chat
from agentvault_registry.services import chat_service as cs

ADMIN = SimpleNamespace(id=6, name="maintainer", email="m@example.test", is_active=True, is_admin=True, is_verified=True,
                        token_version=0, must_change_password=False, two_fa_enabled=True)
PLAIN = SimpleNamespace(id=7, name="reader", email="r@example.test", is_active=True, is_admin=False, is_verified=True,
                        token_version=0, must_change_password=False, two_fa_enabled=True)
DEVS = {6: ADMIN, 7: PLAIN}
MINE = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-0000000000a1"     # an agent of the admin's
THEIRS = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-0000000000b2"   # an agent of the reader's
AGENTS = {MINE: SimpleNamespace(did=MINE, id=11, status="active", name="Atlas", creator_developer_id=6),
          THEIRS: SimpleNamespace(did=THEIRS, id=12, status="active", name="Borealis", creator_developer_id=7)}
ASK = "say we start the build at five and ask who holds the proof window"
ANSWER = "We start the build at 17:00Z. Who holds the proof window tonight?"
URL = "/api/v1/chat/conversations/conv-1/assist"


def _exp():
    return int(dt.datetime.now(dt.timezone.utc).timestamp()) + 600


def dev_jwt(dev_id=6):
    return jwt.encode({"sub": str(dev_id), "tv": 0, "exp": _exp()}, security.SECRET_KEY, algorithm=security.ALGORITHM)


def owner_jwt(did=MINE, owner=6):
    """The token the console mints when he sends as his agent (security.create_owner_session_token's claims)."""
    return jwt.encode({"sub": did, "type": "agent", "agent_id": str(AGENTS[did].id), "via": "owner", "owner": str(owner),
                       "owner_tv": 0, "exp": _exp()}, security.SECRET_KEY, algorithm=security.ALGORITHM)


def agent_jwt(did=MINE):
    """The agent's own token (its client credentials): no owner behind it."""
    return jwt.encode({"sub": did, "type": "agent", "agent_id": str(AGENTS[did].id), "exp": _exp()},
                      security.SECRET_KEY, algorithm=security.ALGORITHM)


class _Rows:
    def __init__(self, row=None, scalar=None):
        self._row, self._scalar = row, scalar

    def first(self):
        return self._row

    def scalars(self):
        return _Rows(row=self._scalar)


class _Db:
    """Two statements reach it: the owner-token check's developer row and the route's own retry lookup."""

    def __init__(self):
        self.dup = None

    async def execute(self, stmt, *a, **k):
        sql = str(stmt)
        if "FROM chat_messages" in sql:
            return _Rows(scalar=self.dup)
        if "FROM developers" in sql:
            return _Rows(row=(0, False, None, None))   # token_version 0, not suspended, not deleted
        raise AssertionError(f"unexpected statement: {sql[:120]}")

    def add(self, obj):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.fixture()
def world(monkeypatch):
    from agentvault_registry.services import admin_audit
    from agentvault_registry.services import assistant_bridge as ab
    w = SimpleNamespace(asks=[], sent=[], audits=[], db=_Db(), flag=True, rate=True, read=True,
                        reply={"reply": ANSWER, "meta": {"tools": "none"}}, raise_=None,
                        conv=SimpleNamespace(id="conv-1", kind="dm", org_id=None, host_registry=None, title="release"),
                        row=SimpleNamespace(state="active", can_post=True), ab=ab)

    async def _dev(db, developer_id):
        return DEVS.get(int(developer_id))

    async def _tv_ok(db, developer_id, tv):
        return True

    async def _agent(db, did):
        return AGENTS.get(did)

    async def _conv(db, conversation_id):
        return w.conv

    async def _member(db, conv, actor, announce_ok=False):
        return w.row

    async def _page(db, conversation_id, actor, limit=40, **kw):
        return {"messages": [{"id": "m-7", "sender_name": "session-lead", "kind": "text", "body": "the build waits on (ap)"},
                             {"sender_name": "session-tester", "kind": "card",
                              "card": {"type": "approval.request", "data": {"title": "V0654 production"}}}],
                "room": {"title": "sessions"}}

    async def _send(db, conv, my_row, actor, kind, body, card, client_ref, reply_to=None, **kw):
        s = kw.get("sender_override")
        w.sent.append({"actor": actor, "sender": s, "kind": kind, "body": body, "client_ref": client_ref,
                       "reply_to": reply_to})
        return {"id": "m-1", "conversation_id": conv.id, "body": body, "sent_with": getattr(s, "sent_with", None)}

    async def _ask(prompt, *, tools=None):
        w.asks.append((prompt, tools))
        if w.raise_:
            raise w.raise_
        return w.reply

    async def _rate(dev_id):
        return w.rate

    async def _read():
        return w.read

    async def _audit(db, **kw):
        w.audits.append(kw)

    monkeypatch.setattr(developer_crud, "get_developer_by_id_lean", _dev)
    monkeypatch.setattr(developer_crud, "get_developer_by_id_strict", _dev)
    monkeypatch.setattr(security, "token_version_current", _tv_ok)
    monkeypatch.setattr(agent_crud, "get_agent_by_did", _agent)
    monkeypatch.setattr(cs, "_get_conversation", _conv)
    monkeypatch.setattr(cs, "resolve_membership", _member)
    monkeypatch.setattr(cs, "list_messages", _page)
    monkeypatch.setattr(chat, "_send_and_fan_out", _send)
    monkeypatch.setattr(ab, "flag_on", lambda: w.flag)
    monkeypatch.setattr(ab, "rate_ok", _rate)
    monkeypatch.setattr(ab, "chat_profile_supported", _read)
    monkeypatch.setattr(ab, "ask", _ask)
    monkeypatch.setattr(admin_audit, "log_admin_action", _audit)
    monkeypatch.setattr(security.settings, "REQUIRE_ADMIN_2FA", False, raising=False)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(chat.router)
    app.dependency_overrides[get_db] = lambda: w.db
    w.client = TestClient(app, raise_server_exceptions=False)
    return w


def _assist(w, token, ref="ref-assist-0001", prompt=ASK, **more):
    return w.client.post(URL, headers={"Authorization": f"Bearer {token}"},
                         json={"prompt": prompt, "client_ref": ref, **more})


def _nothing_happened(w):
    assert w.asks == [] and w.sent == [], (w.asks, w.sent)


# ── the answer, posted by the registry as the chosen identity ─────────────────────────────────────────────────────────

def test_his_own_identity_the_answer_is_posted_as_him_marked_assistant(world):
    r = _assist(world, dev_jwt())
    assert r.status_code == 201, (r.status_code, r.text[:300])
    [s] = world.sent
    assert (s["sender"].ptype, s["sender"].developer_id, s["sender"].sent_with) == ("developer", 6, "assistant")
    assert (s["kind"], s["body"], s["client_ref"]) == ("text", ANSWER, "ref-assist-0001")
    assert r.json()["message"]["sent_with"] == "assistant"


def test_his_agent_the_answer_is_posted_as_the_agent_sent_by_him(world):
    r = _assist(world, owner_jwt(MINE))
    assert r.status_code == 201, (r.status_code, r.text[:300])
    [s] = world.sent
    assert (s["sender"].ptype, s["sender"].agent_did, s["sender"].sent_by, s["sender"].sent_with) == \
        ("agent", MINE, 6, "assistant")


def test_the_bridge_is_asked_once_with_no_tools_and_the_room_in_the_prompt(world):
    _assist(world, dev_jwt())
    [(prompt, tools)] = world.asks
    assert tools == "none"                                   # no tools at all: the room is in the prompt
    assert ASK in prompt and "session-lead: the build waits on (ap)" in prompt
    assert "[approval.request: V0654 production]" in prompt and '"sessions"' in prompt
    assert len(prompt) <= world.ab.CHAT_PROMPT_MAX_CHARS


def test_the_prompt_is_stored_nowhere_in_the_room(world):
    _assist(world, dev_jwt())
    [s] = world.sent
    assert ASK not in s["body"]
    [a] = world.audits
    assert ASK not in repr(a) and a["details"]["prompt_chars"] == len(ASK)


def test_a_reply_folds_under_the_line_it_answers_and_the_assistant_is_told_which(world):
    r = _assist(world, dev_jwt(), reply_to="m-7")
    assert r.status_code == 201, r.text[:200]
    assert world.sent[0]["reply_to"] == "m-7"
    assert "Your reply answers this line: session-lead: the build waits on (ap)" in world.asks[0][0]


def test_a_long_answer_is_cut_to_the_room_s_limit_visibly(world):
    world.reply = {"reply": "ü" * 5000, "meta": {"tools": "none"}}
    r = _assist(world, dev_jwt())
    assert r.status_code == 201, r.text[:200]
    body = world.sent[0]["body"]
    assert len(body.encode("utf-8")) <= cs.BODY_MAX_BYTES and body.endswith(chat._ASSIST_CUT_MARK)


# ── who may ask ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_not_enabled_here_is_refused_in_words(world):
    world.flag = False
    r = _assist(world, dev_jwt())
    assert r.status_code == 404 and "not enabled on this registry" in r.text, (r.status_code, r.text[:200])
    _nothing_happened(world)


def test_an_agent_s_own_token_has_no_owner_and_is_refused(world):
    r = _assist(world, agent_jwt(MINE))
    assert r.status_code == 403 and "Only the identity's owner" in r.text, (r.status_code, r.text[:200])
    _nothing_happened(world)


def test_an_agent_he_does_not_own_is_refused(world):
    # an owner token for another developer's agent: the auth chain's owner check refuses it before the route
    r = _assist(world, owner_jwt(THEIRS, owner=6))
    assert r.status_code == 401 and "no longer belongs" in r.text, (r.status_code, r.text[:200])
    _nothing_happened(world)


def test_an_account_the_bridge_does_not_serve_is_refused(world):
    # a signed-in developer who is not the bridge's (admin) owner, for himself and for his own agent
    for token in (dev_jwt(7), owner_jwt(THEIRS, owner=7)):
        r = _assist(world, token)
        assert r.status_code == 403 and "only for its owner's own account" in r.text, (r.status_code, r.text[:200])
    _nothing_happened(world)


def test_an_api_key_never_makes_the_assistant_speak(world):
    r = _assist(world, "avreg_" + "f" * 40)
    assert r.status_code == 401, (r.status_code, r.text[:200])
    _nothing_happened(world)


# ── where it answers: every refusal a post would meet comes before the bridge ─────────────────────────────────────────

@pytest.mark.parametrize("kind", ["support", "system"])
def test_a_support_or_system_thread_is_refused(world, kind):
    world.conv.kind = kind
    r = _assist(world, dev_jwt())
    assert r.status_code == 409 and "support or system thread" in r.text, (r.status_code, r.text[:200])
    _nothing_happened(world)


def test_a_thread_another_registry_hosts_is_refused(world):
    world.conv.host_registry = "https://asia.theprotocol.cloud"
    r = _assist(world, dev_jwt())
    assert r.status_code == 409 and "another registry hosts this one" in r.text, (r.status_code, r.text[:200])
    _nothing_happened(world)


def test_a_request_not_yet_accepted_is_refused(world):
    world.row.state = "pending"
    r = _assist(world, dev_jwt())
    assert r.status_code == 409 and "Accept this request first" in r.text, (r.status_code, r.text[:200])
    _nothing_happened(world)


def test_a_thread_he_left_is_refused(world):
    world.row.state = "left"
    r = _assist(world, dev_jwt())
    assert r.status_code == 409 and "left this conversation" in r.text, (r.status_code, r.text[:200])
    _nothing_happened(world)


def test_a_room_that_muted_him_is_refused(world):
    world.conv.kind, world.conv.org_id, world.row.can_post = "org", "org-1", False
    r = _assist(world, dev_jwt())
    assert r.status_code == 403 and "muted you here" in r.text, (r.status_code, r.text[:200])
    _nothing_happened(world)


def test_too_many_asks_are_refused(world):
    world.rate = False
    r = _assist(world, dev_jwt())
    assert r.status_code == 429 and "asks a minute" in r.text, (r.status_code, r.text[:200])
    _nothing_happened(world)


def test_a_bridge_that_cannot_run_without_tools_is_never_asked(world):
    world.read = False
    r = _assist(world, dev_jwt())
    assert r.status_code == 503 and "needs its update" in r.text, (r.status_code, r.text[:200])
    _nothing_happened(world)


# ── the bridge's own failures ───────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,words", [(504, "took too long"), (502, "could not answer just now")])
def test_a_bridge_failure_posts_nothing_and_says_so(world, status, words):
    world.raise_ = world.ab.BridgeError(status, "The assistant took too long to answer." if status == 504
                                        else "The assistant could not answer just now (HTTP 500).")
    r = _assist(world, dev_jwt())
    assert r.status_code == status and words in r.text, (r.status_code, r.text[:200])
    assert len(world.asks) == 1 and world.sent == []


def test_an_empty_answer_posts_nothing_and_says_so(world):
    world.reply = {"reply": "  \n ", "meta": {"tools": "none"}}
    r = _assist(world, dev_jwt())
    assert r.status_code == 502 and "empty answer" in r.text, (r.status_code, r.text[:200])
    assert world.sent == []


# ── a retry ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _stored(sent_with):
    return SimpleNamespace(id="m-0", conversation_id="conv-1", seq=41, sender_ptype="developer", sender_id="6",
                           kind="text", body=ANSWER, card=None, reply_to=None, client_ref="ref-assist-0001", mentions=[],
                           sent_by_developer_id=None, sent_with=sent_with, deleted_at=None, edited_at=None,
                           card_rev=0, card_updated_at=None, created_at=dt.datetime(2026, 11, 2, 16, 0))


def test_a_retry_returns_the_answer_already_posted_and_asks_nothing(world):
    world.db.dup = _stored("assistant")
    r = _assist(world, dev_jwt())
    assert r.status_code == 201 and r.json()["message"]["seq"] == 41, (r.status_code, r.text[:200])
    _nothing_happened(world)


def test_a_client_ref_of_another_message_is_refused(world):
    world.db.dup = _stored("session")
    r = _assist(world, dev_jwt())
    assert r.status_code == 409 and "belongs to another message" in r.text, (r.status_code, r.text[:200])
    _nothing_happened(world)


# ── services/assistant_bridge: the no-tools profile is asked for and checked ──────────────────────────────────────────────

def _bridge_answers(monkeypatch, handler):
    from agentvault_registry.services import assistant_bridge as ab
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("COMMANDER_AI_BRIDGE_URL", "http://bridge.test:8787")
    monkeypatch.setenv("COMMANDER_AI_BRIDGE_TOKEN", "t" * 40)
    monkeypatch.setitem(ab._health_cache, "none", None)
    return ab


def test_the_ask_names_no_tools_and_refuses_a_bridge_that_ran_others(monkeypatch):
    seen = []

    def handler(req):
        seen.append(req.read())
        return httpx.Response(200, json={"reply": "ok", "meta": {"tools": "full"}})   # an older bridge ignores the field

    ab = _bridge_answers(monkeypatch, handler)
    with pytest.raises(ab.BridgeError) as e:
        asyncio.run(ab.ask("hello", tools="none"))
    assert e.value.status == 502 and "other tools" in e.value.message
    assert b'"tools": "none"' in seen[0] or b'"tools":"none"' in seen[0]


def test_the_ask_returns_the_reply_when_the_bridge_ran_without_tools(monkeypatch):
    ab = _bridge_answers(monkeypatch, lambda req: httpx.Response(200, json={"reply": "fine", "meta": {"tools": "none"}}))
    assert asyncio.run(ab.ask("hello", tools="none"))["reply"] == "fine"


@pytest.mark.parametrize("health,want", [({"ok": True, "profiles": ["full", "none"]}, True),
                                         ({"ok": True, "read_profile": True, "profiles": ["full", "read"]}, False),
                                         ({"ok": True, "mcp": True}, False)],
                         ids=["no-tools-bridge", "read-profile-bridge", "v0653-bridge"])
def test_the_no_tools_profile_is_read_from_the_bridge_s_health(monkeypatch, health, want):
    ab = _bridge_answers(monkeypatch, lambda req: httpx.Response(200, json=health))
    assert asyncio.run(ab.chat_profile_supported()) is want


def test_a_bridge_that_does_not_answer_its_health_is_never_asked(monkeypatch):
    def handler(req):
        raise httpx.ConnectError("refused", request=req)

    ab = _bridge_answers(monkeypatch, handler)
    assert asyncio.run(ab.chat_profile_supported()) is False


# ── the stored line, on a real Postgres ───────────────────────────────────────────────────────────────────────────────

DB = os.environ.get("MEMBERSHIP_TEST_DB")


@pytest.mark.skipif(not DB, reason="needs a REAL Postgres it may wipe: set MEMBERSHIP_TEST_DB. Skipped, never silently passed.")
def test_the_stored_line_is_the_answer_marked_assistant_and_the_prompt_is_nowhere(monkeypatch):
    # and the audit write fails here (Base has no security_audit_logs: a migration makes it), so its rollback expires
    # the session's rows after the answer was stored: the route still answers (it read its state before the audit)
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from agentvault_registry.models import Base, Conversation, ConversationParticipant, Developer
    from agentvault_registry.services import assistant_bridge as ab

    asks = []

    async def _ask(prompt, *, tools=None):
        asks.append((prompt, tools))
        return {"reply": ANSWER, "meta": {"tools": "none"}}

    async def _yes(*a, **k):
        return True

    monkeypatch.setattr(ab, "flag_on", lambda: True)
    monkeypatch.setattr(ab, "rate_ok", _yes)
    monkeypatch.setattr(ab, "chat_profile_supported", _yes)
    monkeypatch.setattr(ab, "ask", _ask)
    monkeypatch.setattr(cs, "deliver", lambda *a, **k: None)          # the live fan-out: no socket here
    monkeypatch.setattr(security.settings, "REQUIRE_ADMIN_2FA", False, raising=False)

    async def go():
        engine = create_async_engine(DB)
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            me = Developer(name="maintainer", email="owner@test.local", hashed_password="x", is_verified=True,
                           is_admin=True)
            other = Developer(name="reader", email="reader@test.local", hashed_password="x", is_verified=True)
            s.add_all([me, other])
            await s.flush()
            conv = Conversation(kind="dm", created_by_ptype="developer", created_by_id=str(other.id), last_seq=0)
            s.add(conv)
            await s.flush()
            s.add_all([ConversationParticipant(conversation_id=conv.id, ptype="developer", developer_id=me.id),
                       ConversationParticipant(conversation_id=conv.id, ptype="developer", developer_id=other.id)])
            await s.commit()
            cid, me_id = conv.id, me.id      # the ids before the route: the audit's rollback expires these rows
            out = await chat.assist_message(cid, chat.AssistPost(prompt=ASK, client_ref="ref-assist-db01"),
                                            SimpleNamespace(client=None),
                                            actor_dict={"kind": "developer", "developer": me, "credential": "session"},
                                            db=s)
            rows = (await s.execute(text(
                "SELECT sender_ptype, sender_id, body, sent_with FROM chat_messages WHERE conversation_id = :c"),
                {"c": cid})).all()
            preview = (await s.execute(text("SELECT last_preview FROM conversations WHERE id = :c"),
                                       {"c": cid})).scalar()
            stored_anywhere = (await s.execute(text(
                "SELECT count(*) FROM chat_messages WHERE body LIKE :p"), {"p": f"%{ASK[:30]}%"})).scalar()
        await engine.dispose()
        return out, rows, preview, stored_anywhere, me_id

    out, rows, preview, stored_anywhere, me_id = asyncio.run(go())
    assert [tuple(r) for r in rows] == [("developer", str(me_id), ANSWER, "assistant")]
    assert out["message"]["sent_with"] == "assistant" and out["message"]["body"] == ANSWER
    assert stored_anywhere == 0 and ASK[:30] not in (preview or "")
    assert len(asks) == 1 and asks[0][1] == "none"
