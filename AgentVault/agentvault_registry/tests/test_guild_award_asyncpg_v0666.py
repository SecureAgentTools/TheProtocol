"""V0666 the Guild award through asyncpg on a REAL Postgres (V0666's console proof, lifecycle 21: POST /guild/orders/{id}/award
answered 500; session-release room seq 5272 caught the traceback).

V0666's claim (b5c052119, the firms at the award) bound :w twice, as guild_work_orders.worker_did (varchar(120)) and inside the
subselect agents.did=:w (varchar with no length). asyncpg prepares the statement, Postgres deduces two types for one parameter
and refuses ("inconsistent types deduced for parameter $1"), so every award on a V0666 registry was a 500. The cut's database
test of 0230-0233 seeds the columns and never runs the route, and SQLite never prepares: only the route on asyncpg sees it.

Here the real award() runs on an asyncpg engine: the order is awarded, the bid too, and the organizations at the award are the
worker's and the poster's. The Guild's money and side effects are stubbed (no TEG); the claim, the bid updates and the audit
row are the real SQL.

Skipped unless FIRMS_TEST_DB names a throwaway database it may WIPE (postgresql+asyncpg://...). Skipped, never silently passed.
RED on ef4b84b29: asyncpg's ProgrammingError at the claim.
"""
from __future__ import annotations

import datetime as dt
import os
from urllib.parse import urlparse

import pytest

PG = os.environ.get("FIRMS_TEST_DB")
if not PG:
    pytest.skip("needs a REAL Postgres database it may wipe: set FIRMS_TEST_DB. Skipped, never silently passed.",
                allow_module_level=True)

from sqlalchemy import text  # noqa: E402


@pytest.fixture()
async def db(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from agentvault_registry import models
    assert urlparse(PG).path.lstrip("/").startswith("test_"), "name a database whose name starts with test_"
    engine = create_async_engine(PG)                                  # asyncpg: statements are prepared, as in production
    async with engine.begin() as c:
        await c.execute(text("DROP SCHEMA public CASCADE"))
        await c.execute(text("CREATE SCHEMA public"))
        await c.run_sync(models.Base.metadata.create_all)
        # a column the migrations add that the model does not declare (0119's remote firm payee)
        await c.execute(text("ALTER TABLE guild_bids ADD COLUMN IF NOT EXISTS payee_did_hint VARCHAR(120)"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    then = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)
    async with maker() as s:
        for dev_id, name in ((1, "Poster"), (2, "Worker")):
            s.add(models.Developer(id=dev_id, name=name, email=f"dev{dev_id}@example.invalid", hashed_password="x",
                                   is_verified=True, profile_visibility="public", admin_treasury=False, admin_support=False,
                                   admin_enforcement=False, admin_federation=False, admin_platform=False,
                                   agents_unlisted_by_default=False, is_suspended=False, provisioning_months_total=0,
                                   created_at=then, updated_at=then))
        await s.flush()
        s.add(models.Organization(id="org-w", name="Worker Firm", slug="worker-firm", owner_id=2, created_at=then, updated_at=then))
        await s.flush()
        for did, dev_id, org in (("did:a:poster", 1, None), ("did:a:worker", 2, "org-w")):
            s.add(models.Agent(did=did, client_id=f"c-{dev_id}", hashed_client_secret="x", creator_developer_id=dev_id,
                               status="active", created_at=then, enforcement_status="active", reputation_bond_status="none",
                               mtls_enabled=False, is_canary=False, bears_corner_flare=False, bears_encirclement_flare=False,
                               organization_id=org))
        s.add(models.GuildWorkOrder(id="gwo_award0001", poster_did="did:a:poster", title="Award me", bounty=5, currency="ECU",
                                    status="open", created_at=then))
        await s.flush()
        s.add(models.GuildBid(order_id="gwo_award0001", bidder_did="did:a:worker", price=5, status="open", eta_seconds=3600))
        await s.commit()
        yield s
    async with engine.begin() as c:
        await c.execute(text("DROP SCHEMA public CASCADE"))
        await c.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest.fixture()
def quiet(monkeypatch):
    """The Guild's money and side effects stubbed; the order's rows, the claim and the audit are real."""
    from agentvault_registry.routers import guild as G

    async def nothing(*a, **k):
        return None
    monkeypatch.setattr(G, "guild_enabled", lambda: True)
    monkeypatch.setattr(G, "_refund_all_stakes", nothing)
    monkeypatch.setattr("agentvault_registry.services.workflows.gate", nothing)    # no-op off a workflow; reads a migration-only table
    monkeypatch.setattr(G.guild_contract_mirror, "sync_from_order", nothing)
    monkeypatch.setattr(G, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(G, "_notify_owners", lambda *a, **k: None)
    monkeypatch.setattr("agentvault_registry.background_tasks.push_notify.notify_agent_owners", nothing)
    for name in ("_guild_webhook", "_tr_touch"):
        if hasattr(G, name):
            monkeypatch.setattr(G, name, (lambda *a, **k: None) if name == "_guild_webhook" else nothing)
    return G


async def test_the_award_runs_on_asyncpg_and_keeps_both_organizations(db, quiet):
    from agentvault_registry import models
    G = quiet
    bid_id = (await db.execute(text("SELECT id FROM guild_bids WHERE order_id='gwo_award0001'"))).scalar()
    poster = await db.get(models.Agent, (await db.execute(text("SELECT id FROM agents WHERE did='did:a:poster'"))).scalar())
    await G.award("gwo_award0001", G.AwardIn(bid_id=bid_id), poster, db)
    row = (await db.execute(text("SELECT status, worker_did, worker_org_at_award, poster_org_at_award FROM guild_work_orders "
                                 "WHERE id='gwo_award0001'"))).one()
    assert tuple(row) == ("awarded", "did:a:worker", "org-w", None)
    assert (await db.execute(text("SELECT status FROM guild_bids WHERE id=:b"), {"b": bid_id})).scalar() == "awarded"
