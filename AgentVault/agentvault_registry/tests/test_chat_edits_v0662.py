"""V0662 (OurChat lane, order gwo_173e400022a85073f908044b): edit and take back a message within a window.

A text message its sender wrote changes (or is taken back) for CHAT_EDIT_WINDOW_S after it was posted; the change is
marked, the original is KEPT (chat_message_edits) and readable by the thread's members; nothing else about the message
moves. Measured through the real chat router over real (SQLite) rows. Every case fails on f569f6a6e (the V0661 cut),
where the routes, the table and the rules module do not exist, except the ones marked control.
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
from agentvault_registry.services import chat_edits as ce
from agentvault_registry.services import chat_service as cs
from tests._sqlite_db import sqlite_db

AUTHOR = "did:theprotocol:eu.test:session-tester"
OTHER = "did:theprotocol:eu.test:session-lead"
CONV = "conv-edit-1"
BASE = f"/api/v1/chat/conversations/{CONV}/messages"


def run(coro):
    return asyncio.run(coro)


T0 = datetime.datetime(2026, 11, 13, 12, 0, tzinfo=datetime.timezone.utc)


# ── the pure rules ─────────────────────────────────────────────────────────────────────────────────────────────

def test_the_window_is_fifteen_minutes_and_clamped(monkeypatch):
    monkeypatch.delenv("CHAT_EDIT_WINDOW_S", raising=False)
    assert ce.window_seconds() == 900
    for raw, want in (("30", 60), ("100000", 86400), ("junk", 900), ("600", 600)):
        monkeypatch.setenv("CHAT_EDIT_WINDOW_S", raw)
        assert ce.window_seconds() == want, raw


def test_a_message_is_in_the_window_up_to_and_including_its_end(monkeypatch):
    monkeypatch.delenv("CHAT_EDIT_WINDOW_S", raising=False)
    assert ce.in_window(T0, T0 + datetime.timedelta(seconds=900))
    assert not ce.in_window(T0, T0 + datetime.timedelta(seconds=901))
    assert not ce.in_window(None, T0)
    assert ce.in_window(T0.replace(tzinfo=None), T0 + datetime.timedelta(seconds=5))     # a naive stored time reads as UTC


def _why(**kw):
    base = dict(kind="text", deleted=False, mirrored=False, mine=True, created_at=T0,
                now=T0 + datetime.timedelta(seconds=10), revs=0)
    base.update(kw)
    return ce.refusal(**base)


def test_the_refusals_each_name_their_own_reason(monkeypatch):
    monkeypatch.delenv("CHAT_EDIT_WINDOW_S", raising=False)
    assert _why() is None                                                                    # control
    assert "taken back" in _why(deleted=True)
    assert "another registry" in _why(mirrored=True)
    assert "only whoever wrote" in _why(mine=False)
    assert "only a text message" in _why(kind="card")
    assert "15 minutes" in _why(now=T0 + datetime.timedelta(hours=1))
    assert "20 edits" in _why(revs=ce.EDIT_REV_MAX)
    assert _why(revs=ce.EDIT_REV_MAX, editing=False) is None                                 # a take-back is not an edit


# ── the route, over real rows ─────────────────────────────────────────────────────────────────────────────────

class _Manager:
    def __init__(self):
        self.sent, self.woken = [], []

    async def broadcast_to_subscribers(self, topic, envelope):
        self.sent.append((topic, envelope))

    async def wake_chat(self, keys):
        self.woken.append(set(keys))

    async def is_present(self, dev_id):
        return False


@pytest.fixture(autouse=True)
def _fresh_rate_counts():
    """The send's rate gate counts per principal in this process when Redis is absent (60 a minute): this file posts
    more than that as one principal, and the counts must not outlive it into another file's tests."""
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
                   models.ChatMessage, models.ChatCardUpdate, models.ChatMessageEdit, models.ChatPin, models.ChatBlock,
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


def _say(env, text="first draft", ref="text-00000001", as_did=AUTHOR):
    async def go():
        r = await _call(env, "POST", BASE, as_did=as_did, json={"kind": "text", "body": text, "client_ref": ref})
        assert r.status_code == 201, r.text
        return r.json()["message"]
    return go()


def _edit(env, mid, body, as_did=AUTHOR):
    return _call(env, "PUT", f"{BASE}/{mid}", as_did=as_did, json={"body": body})


def _back_date(env, mid, seconds):
    row = env.db.sync.get(models.ChatMessage, mid)
    row.created_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=seconds)
    env.db.sync.commit()


def test_the_sender_edits_in_place_and_the_original_is_kept(env):
    async def go():
        m = await _say(env)
        assert m["edited_at"] is None
        r = await _edit(env, m["id"], "second draft")
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["changed"] is True and out["message"]["body"] == "second draft"
        assert out["message"]["seq"] == m["seq"] and out["message"]["id"] == m["id"]         # same place
        assert out["message"]["edited_at"]
        assert (await _edit(env, m["id"], "third draft")).status_code == 200
        rows = env.db.sync.query(models.ChatMessage).all()
        assert len(rows) == 1 and rows[0].body == "third draft"
        h = await _call(env, "GET", f"{BASE}/{m['id']}/history", as_did=OTHER)               # another member reads it
        assert h.status_code == 200, h.text
        ch = h.json()["changes"]
        assert [c["rev"] for c in ch] == [1, 2] and [c["body_before"] for c in ch] == ["first draft", "second draft"]
        assert ch[0]["by"]["id"] == AUTHOR and ch[0]["kind"] == "edit"
    run(go())


def test_only_the_sender_edits_and_nothing_is_written_for_a_refusal(env):
    async def go():
        m = await _say(env)
        r = await _edit(env, m["id"], "mine now", as_did=OTHER)
        assert r.status_code == 403 and "only whoever wrote" in r.text
        assert env.db.sync.get(models.ChatMessage, m["id"]).body == "first draft"
        assert env.db.sync.query(models.ChatMessageEdit).count() == 0
    run(go())


def test_the_window_closes(env):
    async def go():
        m = await _say(env)
        _back_date(env, m["id"], 901)
        r = await _edit(env, m["id"], "too late")
        assert r.status_code == 409 and "15 minutes" in r.text
        d = await _call(env, "DELETE", f"{BASE}/{m['id']}")
        assert d.status_code == 409 and "15 minutes" in d.text
        assert env.db.sync.get(models.ChatMessage, m["id"]).body == "first draft"
        _back_date(env, m["id"], 899)                                                        # control: just inside
        assert (await _edit(env, m["id"], "just in time")).status_code == 200
    run(go())


def test_an_edit_that_changes_nothing_writes_no_revision_and_tells_no_one(env):
    async def go():
        m = await _say(env)
        before = len(env.mgr.sent)
        r = await _edit(env, m["id"], "first draft")
        assert r.status_code == 200 and r.json()["changed"] is False and r.json()["message"]["edited_at"] is None
        assert env.db.sync.query(models.ChatMessageEdit).count() == 0
        assert len(env.mgr.sent) == before
    run(go())


def test_the_thread_hears_the_edit_and_the_take_back(env):
    async def go():
        m = await _say(env)
        await _edit(env, m["id"], "second draft")
        await _call(env, "DELETE", f"{BASE}/{m['id']}")
        types_ = [e["type"] for _, e in env.mgr.sent]
        assert "chat.message_edited" in types_ and "chat.message_deleted" in types_
        edited = next(e for _, e in env.mgr.sent if e["type"] == "chat.message_edited")
        assert edited["data"]["message"]["body"] == "second draft" and edited["data"]["conversation_id"] == CONV
        gone = next(e for _, e in env.mgr.sent if e["type"] == "chat.message_deleted")
        assert gone["data"]["message"]["deleted"] is True and gone["data"]["message"]["body"] is None
    run(go())


def test_a_taken_back_message_is_a_tombstone_and_its_text_is_kept(env):
    async def go():
        m = await _say(env, "oops wrong room")
        d = await _call(env, "DELETE", f"{BASE}/{m['id']}")
        assert d.status_code == 200, d.text
        tomb = d.json()["message"]
        assert tomb["deleted"] is True and tomb["body"] is None and tomb["seq"] == m["seq"]
        listed = (await _call(env, "GET", BASE, as_did=OTHER)).json()
        shown = [x for x in (listed.get("messages") or listed) if x["id"] == m["id"]]
        assert shown and shown[0]["deleted"] is True and shown[0]["body"] is None
        h = (await _call(env, "GET", f"{BASE}/{m['id']}/history", as_did=OTHER)).json()
        assert h["deleted"] is True and h["changes"][-1]["kind"] == "delete"
        assert h["changes"][-1]["body_before"] == "oops wrong room"
        assert (await _call(env, "DELETE", f"{BASE}/{m['id']}")).status_code == 409           # not twice
        r = await _edit(env, m["id"], "revived")
        assert r.status_code == 409 and "taken back" in r.text
    run(go())


def test_a_message_cannot_be_emptied_or_made_too_long(env):
    async def go():
        m = await _say(env)
        r = await _edit(env, m["id"], "   ")
        assert r.status_code == 422 and "take it back" in r.text
        r = await _edit(env, m["id"], "x" * (cs.BODY_MAX_BYTES + 1))
        assert r.status_code == 422
        assert env.db.sync.get(models.ChatMessage, m["id"]).body == "first draft"
    run(go())


def test_a_card_is_never_edited(env):
    async def go():
        r = await _call(env, "POST", BASE, json={"kind": "card", "client_ref": "progress-0001",
                        "card": {"v": 1, "type": "progress", "data": {"title": "t", "state": "running"}}})
        mid = r.json()["message"]["id"]
        r = await _edit(env, mid, "text over a card")
        assert r.status_code == 409 and "only a text message" in r.text
        assert (await _call(env, "DELETE", f"{BASE}/{mid}")).status_code == 409
    run(go())


def test_a_thread_another_registry_reaches_is_changed_here_and_the_registry_is_told(env, monkeypatch):
    """V0663 (order gwo_9dce94d939aff2fa8ea4f91c): this registry hosts the thread, so the edit applies here as for any thread and
    an event goes to the registries that have a member (services/chat_fed_events: the wire is pinned in test_chat_fed_events_v0663)."""
    from agentvault_registry.services import chat_fed_events as fev
    told = []

    async def publish(db, conv, event):
        told.append(event)
        return 1

    async def key(db, actor):
        return "dev:1@https://a.example"
    monkeypatch.setattr(fev, "publish", publish)
    monkeypatch.setattr(fev, "local_actor_key", key)

    async def go():
        m = await _say(env)
        s = env.db.sync
        s.add(models.ConversationParticipant(id="p-remote", conversation_id=CONV, ptype="remote",
                                             remote_key="dev:5@https://b.example", state="active"))
        s.commit()
        r = await _edit(env, m["id"], "second draft")
        assert r.status_code == 200 and r.json()["changed"] is True
        assert s.get(models.ChatMessage, m["id"]).body == "second draft"
        assert len(told) == 1 and told[0]["type"] == "edit" and told[0]["body"] == "second draft" and told[0]["rev"] == 1
        assert told[0]["message_seq"] == m["seq"] and told[0]["actor"] == "dev:1@https://a.example"
    run(go())


def test_the_list_preview_follows_an_edit_of_the_newest_line(env):
    async def go():
        m = await _say(env)
        await _edit(env, m["id"], "the corrected line")
        conv = env.db.sync.get(models.Conversation, CONV)
        env.db.sync.refresh(conv)
        assert "the corrected line" in (conv.last_preview or "")
    run(go())


def test_a_message_takes_at_most_twenty_edits(env):
    async def go():
        m = await _say(env)
        for i in range(ce.EDIT_REV_MAX):
            assert (await _edit(env, m["id"], f"draft {i}")).status_code == 200
        r = await _edit(env, m["id"], "one more")
        assert r.status_code == 409 and "20 edits" in r.text
        assert (await _call(env, "DELETE", f"{BASE}/{m['id']}")).status_code == 200          # a take-back is still open
    run(go())


# ── the sync feed: a client that was away reads what changed (the `updates` lane the card updates ride) ────────────

def test_the_sync_feed_carries_an_edit_and_a_take_back_once_with_its_cursor(env):
    async def go():
        m = await _say(env)
        n = await _say(env, "second line", ref="text-00000002")
        first = (await _call(env, "GET", "/api/v1/chat/sync", as_did=OTHER)).json()
        cur = first["next_cursor"]
        assert "updates" not in first                                                       # control: a since call
        await _edit(env, m["id"], "first line, corrected")
        a = (await _call(env, "GET", "/api/v1/chat/sync", as_did=OTHER, params={"cursor": cur})).json()
        assert [(u["id"], u["change"], u["body"]) for u in a["updates"]] == [(m["id"], "edit", "first line, corrected")]
        assert a["updates"][0]["edited_at"] and a["updates"][0]["deleted_at"] is None
        await _call(env, "DELETE", f"{BASE}/{n['id']}")
        b = (await _call(env, "GET", "/api/v1/chat/sync", as_did=OTHER, params={"cursor": a["next_cursor"]})).json()
        got = {u["id"]: u for u in b["updates"]}
        assert got[n["id"]]["change"] == "delete" and got[n["id"]]["body"] is None and got[n["id"]]["deleted_at"]
        assert m["id"] not in got                                                           # the edit came once
        c = (await _call(env, "GET", "/api/v1/chat/sync", as_did=OTHER, params={"cursor": b["next_cursor"]})).json()
        assert c["updates"] == []
        f = (await _call(env, "GET", "/api/v1/chat/sync", as_did=OTHER, params={"cursor": cur, "for": "me"})).json()
        assert "updates" not in f                                                           # for=me carries what names you
    run(go())


def test_a_second_edit_comes_again_and_a_message_edited_then_taken_back_comes_as_the_take_back(env):
    async def go():
        m = await _say(env)
        cur = (await _call(env, "GET", "/api/v1/chat/sync", as_did=OTHER)).json()["next_cursor"]
        await _edit(env, m["id"], "v2")
        a = (await _call(env, "GET", "/api/v1/chat/sync", as_did=OTHER, params={"cursor": cur})).json()
        await _edit(env, m["id"], "v3")
        b = (await _call(env, "GET", "/api/v1/chat/sync", as_did=OTHER, params={"cursor": a["next_cursor"]})).json()
        assert [u["body"] for u in a["updates"]] == ["v2"] and [u["body"] for u in b["updates"]] == ["v3"]
        await _call(env, "DELETE", f"{BASE}/{m['id']}")
        c = (await _call(env, "GET", "/api/v1/chat/sync", as_did=OTHER, params={"cursor": b["next_cursor"]})).json()
        assert [(u["change"], u["body"]) for u in c["updates"]] == [("delete", None)]
    run(go())
