"""V0662 (OurChat lane, order gwo_173e400022a85073f908044b): search in a thread.

GET /chat/conversations/{id}/search?q=: the text lines whose words hold q (case ignored), newest first, a page at a time;
only what the reader may read (their own floor, no line taken back, text lines only, this thread only); the reader's own
% and _ are literal. Measured through the real chat router over real (SQLite) rows. Every case fails on c42be1743 (the
console reactions), where the route does not exist, except the ones marked control.
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
from tests._sqlite_db import sqlite_db

AUTHOR = "did:theprotocol:eu.test:session-tester"
OTHER = "did:theprotocol:eu.test:session-lead"
STRANGER = "did:theprotocol:eu.test:nobody"
CONV = "conv-search-1"
BASE = f"/api/v1/chat/conversations/{CONV}/messages"
SEARCH = f"/api/v1/chat/conversations/{CONV}/search"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _fresh_rate_counts():
    cs._LOCAL_RL.clear()
    yield
    cs._LOCAL_RL.clear()


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
    rh = types.ModuleType("agentvault_registry.background_tasks.reactor_helpers")
    rh.dispatch_webhook_for_agents = _quiet
    for mod in (ws, pn, rh):
        monkeypatch.setitem(sys.modules, mod.__name__, mod)

    async def _names(db, keys):
        return {k: k.split(":")[-1] for k in keys}
    monkeypatch.setattr(cs, "display_names", _names)

    async def _owners(db, dids):
        return {d: {AUTHOR: 6, OTHER: 7}.get(d) for d in dids}
    monkeypatch.setattr(cs, "agent_owner_map", _owners)
    db = sqlite_db(models.Developer, models.Agent, models.Conversation, models.ConversationParticipant,
                   models.ChatMessage, models.ChatCardUpdate, models.ChatMessageEdit, models.ChatPin, models.ChatReaction, models.ChatBlock,
                   models.GuildWorkOrder, models.GuildOrderEvent, models.GuildBid)
    s = db.sync
    # the send's own UPDATE stamps last_message_at with now(), which SQLite does not have
    s.connection().connection.driver_connection.create_function(
        "now", 0, lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"))
    s.add(models.Conversation(id=CONV, kind="dm", created_by_ptype="agent", created_by_id=AUTHOR))
    for i, did in enumerate((AUTHOR, OTHER)):
        s.add(models.ConversationParticipant(id=f"p-{i}", conversation_id=CONV, ptype="agent", agent_did=did,
                                             state="active"))
    s.commit()
    app = FastAPI()
    app.include_router(chat_router.router)

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    who = {"did": AUTHOR}
    caller = lambda: {"kind": "agent", "agent_did": who["did"], "agent": types.SimpleNamespace(name=who["did"])}
    from agentvault_registry import security
    for dep in (get_current_actor_for_read, getattr(security, "get_current_actor_for_read_or_key", None)):
        if dep:
            app.dependency_overrides[dep] = caller
    return types.SimpleNamespace(app=app, db=db, who=who, mgr=mgr)


async def _call(env, method, path, as_did=AUTHOR, **kw):
    env.who["did"] = as_did
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://t", timeout=30) as c:
        r = await c.request(method, path, **kw)
    await asyncio.sleep(0.05)              # the background fan-out
    return r


async def _say(env, text, as_did=AUTHOR):
    env.n = getattr(env, "n", 0) + 1
    r = await _call(env, "POST", BASE, as_did=as_did, json={"kind": "text", "body": text, "client_ref": f"text-{env.n:08d}"})
    assert r.status_code == 201, r.text
    return r.json()["message"]


def _find(env, q, as_did=OTHER, **params):
    return _call(env, "GET", SEARCH, as_did=as_did, params={"q": q, **params})


def test_it_finds_the_lines_that_hold_the_words_newest_first_ignoring_case(env):
    async def go():
        await _say(env, "The Release train leaves at nine")
        await _say(env, "lunch?")
        await _say(env, "release notes are ready")
        r = await _find(env, "RELEASE")
        assert r.status_code == 200, r.text
        got = r.json()
        assert [x["body"] for x in got["results"]] == ["release notes are ready", "The Release train leaves at nine"]
        assert got["results"][0]["sender_name"] == AUTHOR.split(":")[-1] and got["more"] is False and got["q"] == "RELEASE"
        assert got["next_before_seq"] is None
    run(go())


def test_the_readers_own_percent_and_underscore_are_literal(env):
    async def go():
        await _say(env, "we are 100% done")
        await _say(env, "about 1000 done")
        await _say(env, "see file a_b.txt")
        await _say(env, "see file axb.txt")
        assert [x["body"] for x in (await _find(env, "100%")).json()["results"]] == ["we are 100% done"]
        assert [x["body"] for x in (await _find(env, "a_b")).json()["results"]] == ["see file a_b.txt"]
        assert (await _find(env, "%%")).json()["results"] == []                           # not "everything"
    run(go())


def test_a_page_continues_below_the_last_seq(env):
    async def go():
        for i in range(5):
            await _say(env, f"needle number {i}")
        a = (await _find(env, "needle", limit=2)).json()
        assert [x["body"] for x in a["results"]] == ["needle number 4", "needle number 3"] and a["more"] is True
        b = (await _find(env, "needle", limit=2, before_seq=a["next_before_seq"])).json()
        assert [x["body"] for x in b["results"]] == ["needle number 2", "needle number 1"] and b["more"] is True
        c = (await _find(env, "needle", limit=2, before_seq=b["next_before_seq"])).json()
        assert [x["body"] for x in c["results"]] == ["needle number 0"] and c["more"] is False and c["next_before_seq"] is None
    run(go())


def test_a_line_taken_back_a_card_and_another_thread_are_never_found(env):
    async def go():
        gone = await _say(env, "needle taken back")
        await _call(env, "DELETE", f"{BASE}/{gone['id']}", as_did=AUTHOR)
        await _call(env, "POST", BASE, json={"kind": "card", "client_ref": "card-0000001",
                    "card": {"v": 1, "type": "progress", "data": {"title": "needle card", "state": "running"}}})
        s = env.db.sync
        s.add(models.Conversation(id="conv-other", kind="dm", created_by_ptype="agent", created_by_id=AUTHOR))
        s.add(models.ChatMessage(id="m-other", conversation_id="conv-other", seq=1, sender_ptype="agent", sender_id=AUTHOR,
                                 kind="text", body="needle elsewhere", client_ref="x-1"))
        s.commit()
        await _say(env, "needle kept")
        # a system line that carries words (a row some rail wrote) is not a line anyone said: not searched
        s.add(models.ChatMessage(id="m-sys", conversation_id=CONV, seq=99, sender_ptype="system", sender_id="guild",
                                 kind="system", body="needle system line", client_ref="sys-1"))
        s.commit()
        assert [x["body"] for x in (await _find(env, "needle")).json()["results"]] == ["needle kept"]
    run(go())


def test_a_reader_s_own_floor_hides_what_came_before_it(env):
    async def go():
        await _say(env, "needle early")
        await _say(env, "needle late")
        s = env.db.sync
        row = s.query(models.ConversationParticipant).filter_by(conversation_id=CONV, agent_did=OTHER).one()
        row.hidden_before_seq = 1
        s.commit()
        assert [x["body"] for x in (await _find(env, "needle", as_did=OTHER)).json()["results"]] == ["needle late"]
        assert len((await _find(env, "needle", as_did=AUTHOR)).json()["results"]) == 2     # control: the other reader's floor is not his
    run(go())


def test_the_query_has_bounds_and_a_stranger_is_refused(env):
    async def go():
        await _say(env, "needle")
        assert (await _find(env, "n")).status_code == 422
        assert (await _find(env, " n ")).status_code == 422
        assert (await _find(env, "x" * 101)).status_code == 422
        assert (await _find(env, "needle", as_did=STRANGER)).status_code in (403, 404, 409)
        assert (await _find(env, "needle")).status_code == 200                              # control
    run(go())
