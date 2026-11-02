"""V0654 (session-tester's read of check 140 in V0653's console proof, the sessions' room seq 944-946; session-lead seq 949):
a reader's read floor never steps back. chat_service.mark_read read the floor, took max() in Python and wrote the row back,
so two marks in flight at once (a page marks one per message it takes in; a phone and a tab) both read the old floor and
the lower one, committing last, stepped it back: read messages turned unread again, and a reopened thread drew its NEW
line twelve messages too early. The floor now rises in one statement on the row (GREATEST in SQL).

The race is driven, not hoped for: both marks read the floor before either writes (a barrier inside resolve_membership),
then the HIGHER one commits first and the lower one after it. BASE (V0653, 1549d6edf348): the floor reads the lower mark.
Skipped unless MEMBERSHIP_TEST_DB names a throwaway Postgres it may WIPE (a real database: two connections, row locks).
"""
from __future__ import annotations

import asyncio
import os

import pytest

DB = os.environ.get("MEMBERSHIP_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres it may wipe: set MEMBERSHIP_TEST_DB. Skipped, never silently passed.",
                allow_module_level=True)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402


@pytest.fixture
async def maker():
    from agentvault_registry.models import Base
    engine = create_async_engine(DB)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _room(maker, floor: int, last_seq: int = 40):
    """A DM between developers A and B with `last_seq` messages, A's floor at `floor`: (conversation id, A's id)."""
    from agentvault_registry.models import Conversation, ConversationParticipant, Developer
    async with maker() as s:
        a = Developer(name="reader", email="reader@test.local", hashed_password="x", is_verified=True)
        b = Developer(name="writer", email="writer@test.local", hashed_password="x", is_verified=True)
        s.add_all([a, b])
        await s.flush()
        conv = Conversation(kind="dm", created_by_ptype="developer", created_by_id=str(b.id), last_seq=last_seq)
        s.add(conv)
        await s.flush()
        s.add_all([ConversationParticipant(conversation_id=conv.id, ptype="developer", developer_id=a.id, last_read_seq=floor),
                   ConversationParticipant(conversation_id=conv.id, ptype="developer", developer_id=b.id, last_read_seq=last_seq)])
        await s.commit()
        return conv.id, a.id


async def _floor(maker, conv_id: str, dev_id: int) -> int:
    async with maker() as s:
        return int((await s.execute(text("SELECT last_read_seq FROM conversation_participants WHERE conversation_id = :c "
                                         "AND developer_id = :d"), {"c": conv_id, "d": dev_id})).scalar_one())


async def test_two_marks_in_flight_never_step_the_floor_back(maker, monkeypatch):
    # BASE: the floor reads 15 (the lower mark, committed last, wrote the floor it computed from the stale 10)
    from agentvault_registry.services import chat_service as cs
    conv_id, a_id = await _room(maker, floor=10)
    actor = cs.Actor("developer", developer_id=a_id, display_name="reader")
    orig = cs.resolve_membership
    read = {"n": 0}
    both_read = asyncio.Event()
    high_done = asyncio.Event()
    sessions = {}

    async def held(db, conv, act, **kw):
        row = await orig(db, conv, act, **kw)
        read["n"] += 1
        if read["n"] == 2:
            both_read.set()
        await both_read.wait()                       # both marks have read the floor before either writes
        if db is sessions["low"]:
            await high_done.wait()                   # the higher mark commits first, the lower one after it
        return row

    monkeypatch.setattr(cs, "resolve_membership", held)

    async def mark(name: str, seq: int):
        async with maker() as s:
            sessions[name] = s
            out = await cs.mark_read(s, conv_id, actor, seq)
            if name == "high":
                high_done.set()
            return out

    high, low = await asyncio.wait_for(asyncio.gather(mark("high", 20), mark("low", 15)), timeout=30)
    assert high["last_read_seq"] == 20
    assert low["last_read_seq"] == 20, f"the lower mark answered {low['last_read_seq']}: it computed from the stale floor"
    assert await _floor(maker, conv_id, a_id) == 20, "the floor stepped back"


async def test_a_lower_mark_after_a_higher_one_keeps_the_floor(maker):
    # one mark after the other: the floor rises, a lower mark later changes nothing, a mark past the end stops at the end
    from agentvault_registry.services import chat_service as cs
    conv_id, a_id = await _room(maker, floor=5, last_seq=30)
    actor = cs.Actor("developer", developer_id=a_id, display_name="reader")
    async with maker() as s:
        assert (await cs.mark_read(s, conv_id, actor, 25))["last_read_seq"] == 25
    async with maker() as s:
        assert (await cs.mark_read(s, conv_id, actor, 12))["last_read_seq"] == 25
    async with maker() as s:
        assert (await cs.mark_read(s, conv_id, actor, 99))["last_read_seq"] == 30
    assert await _floor(maker, conv_id, a_id) == 30
