"""V0666 the Flare view reworked, on a REAL Postgres: an agent wears an unlocked ring, the same ring moves to a second agent, a locked one is refused.

The wear rule reads the store: the owner of the agent, the developer's unlock row, and one bearer per earned copy. The SQLite twin (tests/test_flare_agent_earned_wear_v0666.py) proves the
cases one by one over rows that are filtered; this one runs the whole story through the real router over real Postgres tables, with the registry's own `touch_native_card_no_commit`
statement (a Postgres JSON-path UPDATE the SQLite twin has to stub) and the developer's own wear, which takes the ring off the agent that wore it.

  1. A1 wears the unlocked ring `ember`: the agent's row holds it.
  2. A2 takes the same ring: it moves (A1's row is empty, A2's holds it); the unlock table is untouched.
  3. `quantum-halo` is not unlocked: refused with the sentence that unlocks it, nothing is written.
  4. A stranger's agent cannot be given the unlocked ring.
  5. The developer wears `ember` themself through the flare selection route: A2 gives it up.
  6. A bought ring on an agent is refused for an agent that wears an unlocked one (and the reverse), with the sentence.

Skipped unless FLARE_WEAR_TEST_DB names a throwaway database it may WIPE (postgresql+asyncpg://...).
"""
from __future__ import annotations

import datetime
import os
import uuid

import pytest

DB = os.environ.get("FLARE_WEAR_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres it may wipe: set FLARE_WEAR_TEST_DB. Skipped, never silently passed.", allow_module_level=True)

import httpx  # noqa: E402
from fastapi import Depends, FastAPI  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

NOW = datetime.datetime(2026, 11, 15, 12, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture
async def world():
    from agentvault_registry import models as M
    from agentvault_registry.database import get_db
    from agentvault_registry.routers import fiat_onramp as fo

    engine = create_async_engine(DB, pool_size=2)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(M.Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    ids = {}
    async with maker() as s:
        for k in ("me", "other"):
            d = M.Developer(name=k, email=f"{k}-{uuid.uuid4().hex[:6]}@test.local", hashed_password="x")
            s.add(d)
            await s.flush()
            ids[k] = d.id
        for k, owner in (("a1", "me"), ("a2", "me"), ("stranger", "other")):
            a = M.Agent(did=f"did:theprotocol:eu.test:{k}", client_id=f"c-{k}-{uuid.uuid4().hex[:6]}", hashed_client_secret="x", creator_developer_id=ids[owner], status="active")
            s.add(a)
        s.add(M.CosmeticUnlock(developer_id=ids["me"], kind="encirclement", item_key="ember", tier=4, unlocked_at=NOW, source="test"))
        await s.commit()

    app = FastAPI()
    app.include_router(fo.router)

    async def _db():
        async with maker() as session:
            yield session

    async def _me(db: AsyncSession = Depends(get_db)):
        return await db.get(M.Developer, ids["me"])
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[fo.get_current_developer_unified] = _me
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    yield client, maker, ids, M
    await client.aclose()
    await engine.dispose()


def did(k):
    return f"did:theprotocol:eu.test:{k}"


async def ring_of(maker, M, k):
    async with maker() as s:
        return (await s.execute(select(M.Agent.flare_encirclement_variant).where(M.Agent.did == did(k)))).scalar_one()


async def test_the_wear_rule_end_to_end_over_real_rows(world):
    client, maker, ids, M = world

    # 1. A1 wears the unlocked ring
    r = await client.patch(f"/api/v1/fiat/flare/agent/{did('a1')}/variant", json={"variant": "ember"})
    assert r.status_code == 200, r.text
    assert await ring_of(maker, M, "a1") == "ember"

    # 2. A2 takes the same ring: one copy, one bearer; the unlock table is untouched (the evaluator is the one writer)
    r = await client.patch(f"/api/v1/fiat/flare/agent/{did('a2')}/variant", json={"variant": "ember"})
    assert r.status_code == 200, r.text
    assert await ring_of(maker, M, "a1") is None and await ring_of(maker, M, "a2") == "ember"
    async with maker() as s:
        assert (await s.execute(select(func.count()).select_from(M.CosmeticUnlock))).scalar_one() == 1

    # 3. a ring that is not unlocked is refused with the sentence that unlocks it, and nothing is written
    r = await client.patch(f"/api/v1/fiat/flare/agent/{did('a1')}/variant", json={"variant": "quantum-halo"})
    assert r.status_code == 403 and "quantum page" in r.text, r.text
    assert await ring_of(maker, M, "a1") is None and await ring_of(maker, M, "a2") == "ember"

    # 4. a stranger's agent cannot be given the unlocked ring
    r = await client.patch(f"/api/v1/fiat/flare/agent/{did('stranger')}/variant", json={"variant": "ember"})
    assert r.status_code == 403 and "do not own" in r.text
    assert await ring_of(maker, M, "stranger") is None

    # 5. the developer wears it themself: the agent that wore it gives it up
    r = await client.patch("/api/v1/fiat/flare/selection", json={"variant": "ember"})
    assert r.status_code == 200, r.text
    assert await ring_of(maker, M, "a2") is None
    async with maker() as s:
        assert (await s.get(M.Developer, ids["me"])).flare_encirclement_variant == "ember"

    # 6. an agent that wears a bought ring is refused the unlocked one, with the sentence
    async with maker() as s:
        a = (await s.execute(select(M.Agent).where(M.Agent.did == did("a1")))).scalar_one()
        a.bears_encirclement_flare = True
        await s.commit()
    r = await client.patch(f"/api/v1/fiat/flare/agent/{did('a1')}/variant", json={"variant": "ember"})
    assert r.status_code == 409 and "bought ring" in r.text
    assert await ring_of(maker, M, "a1") is None
