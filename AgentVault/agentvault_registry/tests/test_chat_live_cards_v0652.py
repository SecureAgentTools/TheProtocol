"""V0652 (aa) (order gwo_840aa2b590306f7eba147758, agentvault2-14, 2026-11-01): cards that live.

A card updated in place: the message keeps its seq and its place, its card is the latest state, every update is kept
(who, when, what changed). The update rules the order names, measured through the real chat router over real (SQLite)
rows: only the author updates a progress card; the history is kept; the thread's members see each update (the WS
envelope, and the sync feed's `updates` lane, once per update); a closed card takes no more. The Guild's order card and
an approval card's use ride the same path (rail-only types). Every case fails on 05441be31 (the V0651 recut), where the
route, the types and the columns do not exist, except the ones marked control.
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
from agentvault_registry.services import chat_live_cards as lc
from agentvault_registry.services import chat_service as cs
from tests._sqlite_db import sqlite_db

AUTHOR = "did:theprotocol:eu.test:session-tester"
OTHER = "did:theprotocol:eu.test:session-lead"
CONV = "conv-live-1"


def run(coro):
    return asyncio.run(coro)


def progress(state="running", steps=None, title="V0651 pair proof", note=None):
    d = {"title": title, "state": state}
    if steps is not None:
        d["steps"] = steps
    if note is not None:
        d["note"] = note
    return {"v": 1, "type": "progress", "data": d}


# ── the pure rules ─────────────────────────────────────────────────────────────────────────────────────────────

def test_a_progress_card_is_client_postable_and_validated():
    assert cs.validate_card(progress()) is None
    assert cs.validate_card(progress(steps=[{"label": "console", "state": "done"}])) is None
    assert "data.title" in cs.validate_card({"v": 1, "type": "progress", "data": {"state": "running"}})
    assert "data.state" in cs.validate_card(progress(state="almost"))
    assert "a step's state" in cs.validate_card(progress(steps=[{"label": "x", "state": "half"}]))
    assert "at most 30" in cs.validate_card(progress(steps=[{"label": str(i), "state": "pending"} for i in range(31)]))
    assert "carries only" in cs.validate_card({"v": 1, "type": "progress",
                                               "data": {"title": "t", "state": "running", "url": "x"}})


def test_the_guild_order_card_is_written_by_the_guild_rail_only():
    card = lc.guild_order_card({"id": "gwo_1", "title": "Build (ad)", "status": "open", "bounty": "15", "currency": "ECU"},
                               [{"seq": 1, "event_type": "posted", "at": "2026-11-01T00:00:00+00:00"}], bid_count=0)
    reason = cs.validate_card(card)
    assert reason and "the Guild rail" in reason
    assert cs.validate_card(card, rail_author=True) is None


def test_a_closed_card_says_why():
    assert lc.closed_reason(progress("running")) is None
    assert lc.closed_reason(progress("passed")) == "its verdict is passed"
    assert lc.closed_reason({"type": "guild.order.live", "data": {"status": "settled"}}) == "the order is settled"
    assert lc.closed_reason({"type": "guild.order.live", "data": {"status": "awarded"}}) is None
    assert lc.closed_reason({"type": "approval.decided", "data": {"used": {"act": "roll"}}}) == "the approval was used"
    assert lc.closed_reason({"type": "approval.decided", "data": {}}) is None


def test_what_changed_names_the_step_and_the_verdict():
    old = progress(steps=[{"label": "console", "state": "running"}, {"label": "pair", "state": "pending"}])
    new = progress("passed", steps=[{"label": "console", "state": "done"}, {"label": "federation", "state": "done"}])
    ch = lc.card_changes(old, new)
    assert {"path": "state", "from": "running", "to": "passed"} in ch
    assert {"path": "step console", "from": "running", "to": "done"} in ch
    assert {"path": "step federation", "from": None, "to": "done"} in ch     # added
    assert {"path": "step pair", "from": "pending", "to": None} in ch          # dropped
    assert lc.card_changes(old, old) == []
    many = progress(steps=[{"label": str(i), "state": "done"} for i in range(20)])
    ch = lc.card_changes(progress(steps=[]), many)
    assert len(ch) == lc.CHANGES_MAX and ch[-1]["path"].startswith("and ")


def test_the_list_preview_follows_the_cards_state():
    assert cs.preview_for("card", None, progress("running")) == "In progress: V0651 pair proof"
    assert cs.preview_for("card", None, progress("failed")) == "Failed: V0651 pair proof"
    assert cs.preview_for("card", None, {"v": 1, "type": "guild.order.live",
                                         "data": {"status": "settled", "title": "Build"}}) == "Guild order settled: Build"


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
                   models.ChatMessage, models.ChatCardUpdate, models.ChatBlock,
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


async def _post_progress(env, card=None):
    r = await _call(env, "POST", f"/api/v1/chat/conversations/{CONV}/messages",
                    json={"kind": "card", "card": card or progress(steps=[{"label": "console", "state": "running"}]),
                          "client_ref": "progress-0001"})
    assert r.status_code == 201, r.text
    return r.json()["message"]


def _put(env, mid, card, as_did=AUTHOR):
    return _call(env, "PUT", f"/api/v1/chat/conversations/{CONV}/messages/{mid}/card", as_did=as_did,
                 json={"card": card})


def test_the_author_updates_in_place_and_the_history_is_kept(env):
    async def go():
        m = await _post_progress(env)
        assert m["card_rev"] == 0 and m["card_updated_at"] is None
        r = await _put(env, m["id"], progress(steps=[{"label": "console", "state": "done"},
                                                     {"label": "pair", "state": "running"}]))
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["changed"] is True
        assert out["message"]["seq"] == m["seq"] and out["message"]["id"] == m["id"]     # same place
        assert out["message"]["card_rev"] == 1 and out["message"]["card_updated_at"]
        r = await _put(env, m["id"], progress("passed", steps=[{"label": "console", "state": "done"},
                                                               {"label": "pair", "state": "done"}]))
        assert r.json()["message"]["card_rev"] == 2
        # one message in the thread, its card the latest state
        rows = env.db.sync.query(models.ChatMessage).all()
        assert len(rows) == 1 and rows[0].card["data"]["state"] == "passed"
        h = await _call(env, "GET", f"/api/v1/chat/conversations/{CONV}/messages/{m['id']}/card/history",
                        as_did=OTHER)
        assert h.status_code == 200, h.text
        hist = h.json()
        assert hist["card_rev"] == 2 and [u["rev"] for u in hist["updates"]] == [1, 2]
        assert hist["updates"][0]["by"]["id"] == AUTHOR and hist["updates"][0]["at"]
        assert {"path": "step console", "from": "running", "to": "done"} in hist["updates"][0]["changes"]
        assert {"path": "state", "from": "running", "to": "passed"} in hist["updates"][1]["changes"]
    run(go())


def test_only_the_author_updates_a_progress_card(env):
    async def go():
        m = await _post_progress(env)
        r = await _put(env, m["id"], progress("failed"), as_did=OTHER)
        assert r.status_code == 403 and "only whoever posted this card" in r.text
        assert env.db.sync.query(models.ChatCardUpdate).count() == 0
    run(go())


def test_a_closed_card_takes_no_more(env):
    async def go():
        m = await _post_progress(env)
        assert (await _put(env, m["id"], progress("failed"))).status_code == 200
        r = await _put(env, m["id"], progress("running"))
        assert r.status_code == 409 and "closed (its verdict is failed)" in r.text
    run(go())


def test_a_card_keeps_its_type_and_other_cards_stay_as_posted(env):
    async def go():
        m = await _post_progress(env)
        r = await _put(env, m["id"], {"v": 1, "type": "agent.card", "data": {"name": "x"}})
        assert r.status_code == 422 and "keeps its type" in r.text
        r = await _call(env, "POST", f"/api/v1/chat/conversations/{CONV}/messages",
                        json={"kind": "card", "card": {"v": 1, "type": "agent.card", "data": {"name": "x", "did": OTHER}},
                              "client_ref": "agentcard-0001"})
        assert r.status_code == 201, r.text
        r = await _put(env, r.json()["message"]["id"], {"v": 1, "type": "agent.card", "data": {"name": "y"}})
        assert r.status_code == 409 and "stays as it was posted" in r.text
        txt = await _call(env, "POST", f"/api/v1/chat/conversations/{CONV}/messages",
                          json={"kind": "text", "body": "hello", "client_ref": "text-00000001"})
        r = await _put(env, txt.json()["message"]["id"], progress())
        assert r.status_code == 409 and "carries no card" in r.text
    run(go())


def test_an_update_that_changes_nothing_writes_no_revision(env):
    async def go():
        m = await _post_progress(env)
        r = await _put(env, m["id"], m["card"])
        assert r.status_code == 200 and r.json()["changed"] is False and r.json()["message"]["card_rev"] == 0
        assert env.db.sync.query(models.ChatCardUpdate).count() == 0
        assert env.mgr.sent == [] or all(e["type"] != "chat.card_updated" for _, e in env.mgr.sent)
    run(go())


def test_a_bad_card_is_refused_with_the_validators_reason(env):
    async def go():
        m = await _post_progress(env)
        r = await _put(env, m["id"], progress(state="nearly"))
        assert r.status_code == 422 and "data.state must be one of" in r.text
    run(go())


def test_the_members_see_each_update_and_nobody_is_notified(env):
    async def go():
        m = await _post_progress(env)
        env.mgr.sent.clear()
        env.mgr.woken.clear()
        await _put(env, m["id"], progress("passed"))
        ups = [(t, e) for t, e in env.mgr.sent if e["type"] == "chat.card_updated"]
        assert sorted(t for t, _ in ups) == ["chat:dev:6", "chat:dev:7"]   # the other's owner, the author's household
        assert ups[0][1]["data"]["message"]["card_rev"] == 1
        assert ups[0][1]["data"]["message"]["card"]["data"]["state"] == "passed"
        assert any("agt:" + OTHER.lower() in keys for keys in env.mgr.woken)  # a waiting sync wakes
        assert not [e for _, e in env.mgr.sent if e["type"] in ("chat.message", "notification")]
    run(go())


def test_the_sync_feed_returns_each_update_once_with_its_cursor(env):
    async def go():
        m = await _post_progress(env)
        first = (await _call(env, "GET", "/api/v1/chat/sync", as_did=OTHER)).json()
        cur = first["next_cursor"]
        assert "updates" not in first                   # control: a since call reads the thread's cards as they are
        await _put(env, m["id"], progress("passed"))
        a = (await _call(env, "GET", "/api/v1/chat/sync", as_did=OTHER, params={"cursor": cur})).json()
        assert [(u["id"], u["card_rev"]) for u in a["updates"]] == [(m["id"], 1)]
        assert a["updates"][0]["card"]["data"]["state"] == "passed"
        b = (await _call(env, "GET", "/api/v1/chat/sync", as_did=OTHER, params={"cursor": a["next_cursor"]})).json()
        assert b["updates"] == []                       # once: the cursor remembers it inside the overlap
        f = (await _call(env, "GET", "/api/v1/chat/sync", as_did=OTHER, params={"cursor": cur, "for": "me"})).json()
        assert "updates" not in f                       # control: for=me carries what names you, not updates
    run(go())


def test_a_thread_that_reaches_another_registry_is_refused(env):
    async def go():
        m = await _post_progress(env)
        env.db.sync.add(models.ConversationParticipant(id="p-r", conversation_id=CONV, ptype="remote",
                                                       remote_key="dev@https://asia.test", state="active"))
        env.db.sync.commit()
        r = await _put(env, m["id"], progress("passed"))
        assert r.status_code == 409 and "reaches another registry" in r.text
    run(go())


def test_the_rail_keeps_its_card_current_and_a_client_cannot(env):
    async def go():
        card = lc.guild_order_card({"id": "gwo_1", "title": "Build (ad)", "status": "open", "bounty": "15",
                                    "currency": "ECU"}, [{"seq": 1, "event_type": "posted", "at": None}], bid_count=0)
        conv = env.db.sync.get(models.Conversation, CONV)
        sys_actor = cs.Actor("system", display_name="Guild", system_id="guild")
        msg, dup = await cs.insert_message(env.db, conv, None, sys_actor, "card", None, card, "glive-gwo_1",
                                           rail_author=True, mark_read=False)
        r = await _put(env, msg.id, card)
        assert r.status_code == 403 and "kept current by the Guild rail only" in r.text
        done = lc.guild_order_card({"id": "gwo_1", "title": "Build (ad)", "status": "settled", "bounty": "15",
                                    "currency": "ECU"}, [{"seq": 1, "event_type": "posted", "at": None},
                                                         {"seq": 5, "event_type": "settled", "at": None}], bid_count=1)
        out, _c, changed = await cs.update_card(env.db, CONV, msg.id, sys_actor, done, rail_author=True)
        assert changed and out["card_rev"] == 1 and out["card"]["data"]["status"] == "settled"
        with pytest.raises(cs.ChatError) as e:      # settled closes it
            await cs.update_card(env.db, CONV, msg.id, sys_actor, card, rail_author=True)
        assert e.value.status_code == 409 and "the order is settled" in e.value.detail
    run(go())


# ── the Guild's order card, over real rows ─────────────────────────────────────────────────────────────────────

def test_the_guild_card_follows_the_order_and_never_goes_back(env, monkeypatch):
    import contextlib

    import agentvault_registry.database as D
    from agentvault_registry.services import guild_live_card as glc

    @contextlib.asynccontextmanager
    async def _ctx():
        yield env.db

    async def _no_lock(db, oid):           # Postgres's advisory lock; SQLite has one connection anyway
        return None
    monkeypatch.setattr(D, "get_db_context", _ctx)
    monkeypatch.setattr(glc, "_lock", _no_lock)
    monkeypatch.setattr(glc, "COMMIT_WAIT_S", 0.3)
    s = env.db.sync
    s.add(models.GuildWorkOrder(id="gwo_live1", poster_did=AUTHOR, title="Build (ad)", bounty=15, currency="ECU",
                                status="open", announce_conversation_id=CONV))
    s.add(models.GuildOrderEvent(id=1, order_id="gwo_live1", seq=1, event_type="posted", actor_did=AUTHOR))
    s.commit()

    def card():
        s.expire_all()
        o = s.get(models.GuildWorkOrder, "gwo_live1")
        return s.get(models.ChatMessage, o.announce_message_id) if o.announce_message_id else None

    async def go():
        await glc.refresh("gwo_live1", 1)
        m = card()
        assert m is not None and m.sender_ptype == "system" and m.client_ref == "glive-gwo_live1"
        assert m.card["type"] == "guild.order.live" and m.card["data"]["status"] == "open" and m.card_rev == 0
        o = s.get(models.GuildWorkOrder, "gwo_live1")
        s.add(models.GuildBid(order_id="gwo_live1", bidder_did=OTHER, price=15, status="open"))
        s.add(models.GuildOrderEvent(id=2, order_id="gwo_live1", seq=2, event_type="bid", actor_did=OTHER))
        s.add(models.GuildOrderEvent(id=3, order_id="gwo_live1", seq=3, event_type="awarded", actor_did=AUTHOR))
        o.status, o.worker_did = "awarded", OTHER
        s.commit()
        await glc.refresh("gwo_live1", 3)
        m = card()
        assert m.card_rev == 1 and m.card["data"]["status"] == "awarded" and m.card["data"]["bids"] == 1
        assert [e["type"] for e in m.card["data"]["events"]] == ["posted", "bid", "awarded"]
        assert m.card["data"]["worker_did"] == OTHER
        await glc.refresh("gwo_live1", 2)            # a late refresh renders the same latest state: no revision
        assert card().card_rev == 1
        await glc.refresh("gwo_live1", 9)            # an event that never committed shows nothing
        assert card().card_rev == 1
        o = s.get(models.GuildWorkOrder, "gwo_live1")
        s.add(models.GuildOrderEvent(id=4, order_id="gwo_live1", seq=4, event_type="settled", actor_did=AUTHOR))
        o.status = "settled"
        s.commit()
        await glc.refresh("gwo_live1", 4)
        assert card().card_rev == 2 and card().card["data"]["status"] == "settled"
        await glc.refresh("gwo_live1", 4)            # closed: a repeat changes nothing and raises nothing
        assert card().card_rev == 2
        assert s.query(models.ChatMessage).count() == 1      # one card, never a second message
    run(go())


def test_an_order_names_only_a_room_its_poster_may_post_in(env):
    from agentvault_registry.services import guild_live_card as glc

    async def go():
        me = cs.Actor("agent", agent_did=AUTHOR, display_name="session-tester")
        assert await glc.room_refusal(env.db, CONV, me) is None                      # control
        stranger = cs.Actor("agent", agent_did="did:theprotocol:eu.test:stranger", display_name="x")
        assert "cannot announce" in (await glc.room_refusal(env.db, CONV, stranger) or "")
        assert "no conversation" in (await glc.room_refusal(env.db, "conv-none", me) or "")
    run(go())


def test_an_approval_card_shows_its_use_once(env):
    async def go():
        conv = env.db.sync.get(models.Conversation, CONV)
        dev = cs.Actor("developer", developer_id=6, display_name="maintainer")
        decided = {"v": 1, "type": "approval.decided", "refs": {"approval_id": "apr_1"},
                   "data": {"approval_id": "apr_1", "decision": "approved", "title": "Roll V0651",
                            "decided_by_developer_id": 6}}
        msg, _ = await cs.insert_message(env.db, conv, None, dev, "card", None, decided, "aprdec-apr_1",
                                         rail_author=True)
        agent = cs.Actor("agent", agent_did=AUTHOR, display_name="session-tester")
        at = datetime.datetime(2026, 11, 1, 5, 0, tzinfo=datetime.timezone.utc)
        await chat_router._decision_card_shows_use(env.db, conv, "apr_1", agent, "roll V0651 to production",
                                                   "ab" * 32, at)
        env.db.sync.expire_all()
        m = env.db.sync.get(models.ChatMessage, msg.id)
        assert m.card_rev == 1 and m.card["data"]["used"]["act"] == "roll V0651 to production"
        assert m.card["data"]["used"]["at"].startswith("2026-11-01T05:00") and m.card["data"]["decision"] == "approved"
        with pytest.raises(cs.ChatError) as e:            # used once, it is closed
            await chat_router._decision_card_shows_use(env.db, conv, "apr_1", agent, "a second act", "cd" * 32, at)
        assert e.value.status_code == 409 and "the approval was used" in e.value.detail
    run(go())
