"""V0667 D5b (order gwo_efd89f2041bfda1eeb7e2cda): a content change's room card and its state lines on a REAL Postgres, and the whole path through the real routes. Like D3's card for a code change:

  1. the first refresh posts ONE `content.change.live` card (rail-only: the chat's own validator takes it from the rail and refuses it from a client) into the room, remembers its message and
     the state the room saw, and posts no state line (the card announces the change); a refresh with nothing new posts nothing;
  2. a state change updates the same card in place and posts ONE line; two refreshes racing on one state change post the line once;
  3. through the real routes: a proposal naming a room of the line's organization gets its card; the deciders' votes through the vote route close the ballot, the change is applied, and the room's
     card reads Applied with ONE line telling the room; a room of another organization is refused at the proposal and nothing is written;
  4. a change with no room posts nothing, ever.

Skipped unless CODE_DISTRIBUTIONS_TEST_DB names a throwaway database it may WIPE (postgresql+asyncpg://...). Skipped, never silently passed.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import uuid

import pytest

DB = os.environ.get("CODE_DISTRIBUTIONS_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres database it may wipe: set CODE_DISTRIBUTIONS_TEST_DB. Skipped, never silently passed.", allow_module_level=True)

from sqlalchemy import text  # noqa: E402

from tests.test_content_changes_v0667_db import PROP, deciders_vote_for, vote_all, world  # noqa: E402,F401  (the fixture and the helpers of the routes' own database test)

from agentvault_registry.services import chat_service as cs  # noqa: E402
from agentvault_registry.services import content_change_card as ccc  # noqa: E402


@pytest.fixture(autouse=True)
def _no_delivery(monkeypatch):
    delivered = []
    monkeypatch.setattr(cs, "deliver", lambda *a, **k: delivered.append(a))
    return delivered


def _ctx(maker):
    @contextlib.asynccontextmanager
    async def session():
        async with maker() as s:
            yield s
    return session


async def _room(w, org=None):
    from agentvault_registry.models import Conversation
    async with w.maker() as s:
        room = Conversation(id=str(uuid.uuid4()), kind="org", title="Lyceum builders", org_id=org or w.org, created_by_ptype="developer", created_by_id=str(w.devs["owner"]))
        s.add(room)
        await s.commit()
        return room.id


async def _messages(w, room):
    async with w.maker() as s:
        return [dict(r) for r in (await s.execute(text("SELECT id, kind, body, card FROM chat_messages WHERE conversation_id = :c ORDER BY seq"), {"c": room})).mappings()]


async def _row(w, cid):
    async with w.maker() as s:
        return dict((await s.execute(text("SELECT announce_message_id, announce_state, state FROM content_changes WHERE id = :c"), {"c": cid})).mappings().first())


async def _propose(w, room=None, **over):
    body = {**PROP, "kind": "console_text", "target": "landing.tagline", "content": {"text": "Quiet releases."}, **over}
    if room:
        body["room_id"] = room
    return await w.call("POST", "/api/v1/content-changes", body, as_="member")


@pytest.fixture
def refreshes(monkeypatch, world):
    """The background refresh is asked for after each write; here it is recorded, and run by the test when the test wants the room to catch up."""
    asked = []
    monkeypatch.setattr(ccc, "refresh_soon", lambda cid: asked.append(cid))
    monkeypatch.setattr(ccc, "room_refusal", ccc.room_refusal)
    from agentvault_registry.services import code_changes as cc

    async def allow(self, room_id, proposer_did, organization_id):
        from agentvault_registry.services import code_change_card
        conv = await cs._get_conversation(self.db, room_id)
        return None if str(getattr(conv, "org_id", "") or "") == str(organization_id) else "a line's change is announced only in a room of the line's organization"
    monkeypatch.setattr(cc.DbStore, "room_refusal", allow)             # the room's speech rules are D3's own (its tests); here only the organization's
    return asked


async def test_the_first_refresh_posts_one_card_and_no_line_and_a_client_cannot_type_it(world, refreshes):
    w = world
    room = await _room(w)
    cid = (await _propose(w, room)).json()["id"]
    assert cid in refreshes, "the proposal asks for the card"
    await ccc.refresh(cid, session=_ctx(w.maker))
    msgs = await _messages(w, room)
    assert [m["kind"] for m in msgs] == ["card"]
    card = msgs[0]["card"]
    assert card["type"] == "content.change.live" and card["data"]["state"] == "balloting" and card["data"]["kind"] == "console_text"
    assert card["data"]["line"]["organization_name"] == "Lyceum" and card["data"]["line"]["release_name"] == "V0666_lyceum"
    assert "Quiet releases." not in str(card), "the card names the kind of change, never its text"
    assert cs.validate_card(card, rail_author=True) is None and cs.validate_card(card) is not None
    r = await _row(w, cid)
    assert r["announce_message_id"] == msgs[0]["id"] and r["announce_state"] == "balloting"
    await ccc.refresh(cid, session=_ctx(w.maker))
    assert len(await _messages(w, room)) == 1, "a second refresh with nothing new posts nothing"


async def test_the_whole_path_through_the_routes_ends_with_an_applied_card_and_one_line(world, refreshes):
    w = world
    room = await _room(w)
    cid = (await _propose(w, room)).json()["id"]
    await ccc.refresh(cid, session=_ctx(w.maker))
    rec = (await vote_all(w, cid, await deciders_vote_for(w))).json()
    assert rec["state"] == "applied"
    await ccc.refresh(cid, session=_ctx(w.maker))
    msgs = await _messages(w, room)
    assert [m["kind"] for m in msgs] == ["card", "text"]
    assert msgs[0]["card"]["data"]["state"] == "applied" and msgs[0]["card"]["data"]["applied"] is True and msgs[0]["card"]["data"]["ballot"]["result"] == "PASSED"
    assert msgs[1]["body"] == "A content change: passed its ballot and is applied to the organization's own space; its deciders can undo it in one step."
    u = await w.call("POST", f"/api/v1/content-changes/{cid}/undo", None, as_="owner")
    assert u.json()["state"] == "undone"
    await ccc.refresh(cid, session=_ctx(w.maker))
    msgs = await _messages(w, room)
    assert [m["kind"] for m in msgs] == ["card", "text", "text"] and "undone" in msgs[2]["body"]
    assert msgs[0]["card"]["data"]["state"] == "undone"


async def test_two_refreshes_racing_on_one_state_change_post_the_line_once(world, refreshes):
    w = world
    room = await _room(w)
    cid = (await _propose(w, room)).json()["id"]
    await ccc.refresh(cid, session=_ctx(w.maker))
    await vote_all(w, cid, await deciders_vote_for(w))
    await asyncio.gather(ccc.refresh(cid, session=_ctx(w.maker)), ccc.refresh(cid, session=_ctx(w.maker)))
    assert [m["kind"] for m in await _messages(w, room)] == ["card", "text"]


async def test_a_room_of_another_organization_is_refused_and_nothing_is_written(world, refreshes):
    w = world
    other_room = await _room(w, org=w.org2)
    r = await _propose(w, other_room)
    assert r.status_code == 422 and r.json()["code"] == "room"
    async with w.maker() as s:
        assert (await s.execute(text("SELECT count(*) FROM content_changes"))).scalar_one() == 0


async def test_a_change_with_no_room_posts_nothing(world, refreshes):
    w = world
    cid = (await _propose(w)).json()["id"]
    await ccc.refresh(cid, session=_ctx(w.maker))
    async with w.maker() as s:
        assert (await s.execute(text("SELECT count(*) FROM chat_messages"))).scalar_one() == 0
    assert (await _row(w, cid))["announce_message_id"] is None
