"""V0666: the migration chain 0230 -> 0231_code_distributions (D1) -> 0232_code_change_room (D3) -> 0233_guild_orders_agent_org (Firms), on a REAL Postgres.

The Firms migration was 0231 on its own branch, the same number as D1's: two heads. It now sits on top of D3 (the lead's order, room seq 4920). This test pins:

  1. the revision graph has ONE head with 0233_guild_orders_agent_org below it (V0667 puts 0234_repo_accounts on top), and the chain
     from 0233 down is exactly 0230, 0231, 0232, 0233 in that order;
  2. 0233's own downgrade and upgrade on a database built from this branch's models: down removes exactly its two columns and two indexes from guild_work_orders, up puts exactly them back
     (the table's columns and index names equal what they were), and 0233 touches no table 0231 or 0232 creates, so the order of the chain cannot matter to it. (0231's and 0232's own
     up/down are covered by D1's and D3's tests, which this branch runs too: a create_all database carries auto-named constraints their downgrades do not expect.)
  3. 0233's backfill: an order already awarded takes the agents' CURRENT organization on both sides, an order not awarded takes none, and an agent without an organization leaves the column NULL;
  4. a database at 0232 (0233 downgraded) really lacks the two columns and their indexes, and one at 0233 has them.

Skipped unless FIRMS_TEST_DB names a throwaway database it may WIPE (postgresql+asyncpg://...). Skipped, never silently passed.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import pathlib
import uuid

import pytest

DB = os.environ.get("FIRMS_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres database it may wipe: set FIRMS_TEST_DB. Skipped, never silently passed.", allow_module_level=True)

from alembic.config import Config  # noqa: E402
from alembic.operations import Operations  # noqa: E402
from alembic.runtime.migration import MigrationContext  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

ALEMBIC = pathlib.Path(__file__).resolve().parents[1] / "alembic"
CHAIN = ["0230_contributor_track", "0231_code_distributions", "0232_code_change_room", "0233_guild_orders_agent_org"]


def _module(rev: str):
    path = next((ALEMBIC / "versions").glob(f"{rev.split('_')[0]}_*.py"))
    # the file names that carry two heads in the repo would show here as more than one match
    matches = list((ALEMBIC / "versions").glob(f"{rev.split('_')[0]}_*.py"))
    assert len(matches) == 1, f"two migrations share the number {rev.split('_')[0]}: {[m.name for m in matches]}"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_graph_has_one_head_and_the_chain_below_it_is_in_order():
    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC))
    sd = ScriptDirectory.from_config(cfg)
    heads = sd.get_heads()
    assert len(heads) == 1, heads                       # one head; a later migration (V0667's 0234_repo_accounts) sits on top of 0233
    rev = sd.get_revision(heads[0])
    while rev is not None and rev.revision != "0233_guild_orders_agent_org":
        rev = sd.get_revision(rev.down_revision) if rev.down_revision else None
    assert rev is not None, f"0233_guild_orders_agent_org is not below the head {heads[0]}"
    chain = []
    rev = sd.get_revision("0233_guild_orders_agent_org")
    while rev is not None and rev.revision != "0229_proxy_status":
        chain.append(rev.revision)
        rev = sd.get_revision(rev.down_revision) if rev.down_revision else None
    assert list(reversed(chain)) == CHAIN


def test_the_migration_numbers_are_unique_in_the_chain():
    for rev in CHAIN[1:]:
        _module(rev)                    # asserts one file per number


async def _run(conn, mod, fn):
    def go(sync_conn):
        ctx = MigrationContext.configure(sync_conn)
        with Operations.context(ctx):
            getattr(mod, fn)()
    await conn.run_sync(go)


def _schema(sync_conn):
    insp = inspect(sync_conn)
    out = {}
    for t in sorted(insp.get_table_names()):
        out[t] = {"columns": sorted(c["name"] for c in insp.get_columns(t)),
                  "indexes": sorted(i["name"] for i in insp.get_indexes(t) if i.get("name")),
                  "checks": sorted(c["name"] for c in insp.get_check_constraints(t) if c.get("name")),
                  "fks": sorted(f["name"] for f in insp.get_foreign_keys(t) if f.get("name"))}
    return out


@pytest.fixture
async def engine():
    from agentvault_registry.models import Base
    eng = create_async_engine(DB)
    async with eng.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
        # the model declares the two columns 0233 adds but not its two partial indexes (an index the migration alone creates): a database 0233 produced has them
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_gwo_worker_org_at_award ON guild_work_orders (worker_org_at_award) WHERE worker_org_at_award IS NOT NULL"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_gwo_poster_org_at_award ON guild_work_orders (poster_org_at_award) WHERE poster_org_at_award IS NOT NULL"))
    yield eng
    await eng.dispose()


async def test_0233_down_then_up_restores_guild_work_orders_exactly_and_touches_nothing_else(engine):
    mod = _module("0233_guild_orders_agent_org")
    async with engine.begin() as conn:
        before = await conn.run_sync(_schema)
    async with engine.begin() as conn:
        await _run(conn, mod, "downgrade")
        mid = await conn.run_sync(_schema)
    gwo = mid["guild_work_orders"]
    assert "worker_org_at_award" not in gwo["columns"] and "poster_org_at_award" not in gwo["columns"]
    assert not {"ix_gwo_worker_org_at_award", "ix_gwo_poster_org_at_award"} & set(gwo["indexes"])
    assert {t: v for t, v in mid.items() if t != "guild_work_orders"} == {t: v for t, v in before.items() if t != "guild_work_orders"}, "the downgrade touched another table"
    async with engine.begin() as conn:
        await _run(conn, mod, "upgrade")
        after = await conn.run_sync(_schema)
    assert after == before, f"the round trip left a different schema: {({t: (before.get(t), after.get(t)) for t in before if before.get(t) != after.get(t)})}"


async def test_0233_alone_adds_the_two_columns_and_backfills_by_the_current_organization(engine):
    from agentvault_registry.models import Agent, Developer, GuildWorkOrder, Organization
    mod = _module("0233_guild_orders_agent_org")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    now = dt.datetime.now(dt.timezone.utc)
    async with maker() as s:
        dev = Developer(name=f"o-{uuid.uuid4().hex[:6]}", email=f"o{uuid.uuid4().hex[:6]}@test.local", hashed_password="x", is_verified=True)
        s.add(dev)
        await s.flush()
        org = Organization(id=str(uuid.uuid4()), name="Chain Test Org", slug=f"chain-{uuid.uuid4().hex[:6]}", owner_id=dev.id, is_active=True, settings={})
        s.add(org)
        await s.flush()

        def agent(org_id):
            did = f"did:theprotocol:eu.test:{uuid.uuid4()}"
            s.add(Agent(did=did, client_id=f"c-{uuid.uuid4().hex[:10]}", hashed_client_secret="x", creator_developer_id=dev.id,
                        status="active", enforcement_status="active", organization_id=org_id))
            return did
        member, stranger = agent(org.id), agent(None)
        await s.flush()
        ids = {}
        for key, worker, poster, awarded in (("awarded", member, stranger, now), ("not_awarded", member, member, None), ("no_org", stranger, stranger, now)):
            oid = f"gwo_{uuid.uuid4().hex[:20]}"
            ids[key] = oid
            s.add(GuildWorkOrder(id=oid, poster_did=poster, title="t", bounty=1, currency="ECU", status="settled" if awarded else "open",
                                 worker_did=worker, awarded_at=awarded))
        await s.commit()
    async with engine.begin() as conn:
        await _run(conn, mod, "downgrade")                       # the database as it was at 0232
        cols = (await conn.run_sync(_schema))["guild_work_orders"]["columns"]
        assert "worker_org_at_award" not in cols and "poster_org_at_award" not in cols
        await _run(conn, mod, "upgrade")                         # 0233 on rows that already exist
        rows = {r[0]: (r[1], r[2]) for r in (await conn.execute(text("SELECT id, worker_org_at_award, poster_org_at_award FROM guild_work_orders"))).all()}
    assert rows[ids["awarded"]] == (org.id, None), "an awarded order takes the member's CURRENT organization on the worker side; the poster has none"
    assert rows[ids["not_awarded"]] == (None, None), "an order not awarded takes nothing"
    assert rows[ids["no_org"]] == (None, None), "an agent without an organization leaves the column NULL"
