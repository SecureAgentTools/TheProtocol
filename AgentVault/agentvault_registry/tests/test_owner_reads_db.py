"""V0658 (q), item 2, on a REAL Postgres: the owner's reads list exactly his work, and the SQL and the Python agree.

Rows: developer OWNER created agent A; agent B (another developer's) is in OWNER's active organization and its creator
is an active member of it; agent C is in OWNER's INACTIVE organization; agent D is in another owner's organization;
agent L is still assigned to OWNER's organization while its creator was REMOVED from it (the membership row is gone:
the assignment outlives the membership on purpose, §ORGLIFE L2); agent M is assigned there while its creator's
membership is INACTIVE; T is the treasury of OWNER's organization (keyless: no seat ever holds it in production). Orders
and contracts put them in every seat. OWNER's lists hold exactly the work with A or B on it; the other owner's hold D's
(and each creator's hold his own agents'); a member who owns nothing reads none. For every row the list's SQL
(`owned_by_sql`) and the per-party Python (`owned_parties`) give the same answer: the twin rule, proven on rows that
are actually filtered.

The Guild's deliverable is the parties' and their creators' (and an admin's), plus the owner's of the organization the
work was done for (a firm award, `payee_org_id`), whoever its agents are now: the owner of an organization a member's
agent works in reads that order and its parties, not the work the agent did on its own account.

The review of the first cut (V0658 (q)): the organization road trusted `agents.organization_id` alone, so the owner
read a removed member's agent's work, including its deliverables. HEAD 2862d4121: o_l and o_m listed, o_t listed, B's
private deliverable read by the organization's owner, the firm's deliverable withheld from him, the list statement a
correlated EXISTS per row.

Skipped unless OWNER_READS_TEST_DB names a throwaway database it may WIPE (postgresql+asyncpg://...).
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

DB = os.environ.get("OWNER_READS_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres it may wipe: set OWNER_READS_TEST_DB. Skipped, never silently passed.",
                allow_module_level=True)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

REPLICAS_DDL = """
CREATE TABLE IF NOT EXISTS contract_replicas (
    cid VARCHAR(80) PRIMARY KEY, home_registry VARCHAR(300) NOT NULL, client_did VARCHAR(120),
    provider_did VARCHAR(120), title VARCHAR(200), currency VARCHAR(12), total_amount NUMERIC(30,10),
    status VARCHAR(20) NOT NULL, seq INTEGER NOT NULL DEFAULT 0, digest VARCHAR(64) NOT NULL, signature TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb, stale BOOLEAN NOT NULL DEFAULT false,
    last_synced_at TIMESTAMPTZ NOT NULL DEFAULT now(), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now())
"""


@pytest.fixture
async def world(monkeypatch):
    from agentvault_registry import models as M
    from agentvault_registry.routers import contracts_v2 as C
    from agentvault_registry.routers import guild as G
    monkeypatch.setattr(G, "_require_enabled", lambda: None)
    monkeypatch.setattr(C, "_require_enabled", lambda: None)
    engine = create_async_engine(DB, pool_size=2)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(M.Base.metadata.create_all)
        await conn.execute(text(REPLICAS_DDL))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    w = SimpleNamespace(maker=maker)
    async with maker() as s:
        devs = {}
        for k in ("owner", "other_owner", "b_creator", "member", "leaver", "lapsed"):
            d = M.Developer(name=k, email=f"{k}-{uuid.uuid4().hex[:6]}@test.local", hashed_password="x",
                            is_verified=True)
            s.add(d)
            await s.flush()
            devs[k] = d.id
        w.devs = devs
        did = lambda n: f"did:theprotocol:test:{n}-{uuid.uuid4().hex[:8]}"  # noqa: E731
        w.A, w.B, w.C, w.D, w.T, w.X, w.Y, w.L, w.M = (did(n) for n in "ABCDTXYLM")
        orgs = [M.Organization(id="org-live", name="Live org", slug="live", owner_id=devs["owner"], is_active=True,
                               treasury_agent_did=w.T),
                M.Organization(id="org-gone", name="Gone org", slug="gone", owner_id=devs["owner"], is_active=False),
                M.Organization(id="org-other", name="Other org", slug="other", owner_id=devs["other_owner"],
                               is_active=True)]
        s.add_all(orgs)
        await s.flush()
        # the leaver has no row: a removal deletes it (OrganizationService.remove_member); the lapsed one is inactive
        for org, who, active in (("org-live", "member", True), ("org-live", "b_creator", True),
                                 ("org-other", "b_creator", True), ("org-live", "lapsed", False)):
            s.add(M.OrganizationMember(id=str(uuid.uuid4()), organization_id=org, developer_id=devs[who],
                                       role="member", is_active=active))
        for a, creator, org in ((w.A, "owner", None), (w.B, "b_creator", "org-live"), (w.C, "b_creator", "org-gone"),
                                (w.D, "b_creator", "org-other"), (w.X, "b_creator", None), (w.Y, "b_creator", None),
                                (w.L, "leaver", "org-live"), (w.M, "lapsed", "org-live")):
            s.add(M.Agent(did=a, client_id=f"c-{uuid.uuid4().hex[:10]}", hashed_client_secret="x",
                          creator_developer_id=devs[creator], status="active", organization_id=org))
        await s.flush()
        s.add(M.AgentCard(developer_id=devs["owner"], agent_did=w.A, card_data={"name": "Agent A"}, name="Agent A"))
        s.add(M.AgentCard(developer_id=devs["b_creator"], agent_did=w.B, card_data={"name": "Agent B"}, name="Agent B"))
        seats = {  # order/contract id -> (first party, second party)
            "o_a": (w.A, None), "o_b": (w.X, w.B), "o_c": (w.C, None), "o_d": (w.D, w.X), "o_t": (w.T, w.X),
            "o_ad": (w.D, w.A), "o_x": (w.X, None), "o_l": (w.X, w.L), "o_m": (w.M, w.X), "o_f": (w.X, w.Y)}
        # o_f: Y won it bidding as OWNER's organization (a firm award, paid to it), and is in no organization now
        firm = {"o_f": "org-live"}
        w.seats = seats
        for oid, (p, k) in seats.items():
            s.add(M.GuildWorkOrder(id=oid, poster_did=p, worker_did=k, title=oid, bounty=Decimal("1"), currency="ECU",
                                   status="submitted", deliverable={"report": oid}, payee_org_id=firm.get(oid)))
            s.add(M.Contract(id=f"c{oid}", client_did=p, provider_did=k, title=oid, currency="ECU",
                             total_amount=Decimal("1"), status="agreed"))
        await s.flush()
        await s.execute(text(
            "INSERT INTO contract_replicas (cid, home_registry, client_did, provider_did, title, status, digest) "
            "VALUES ('r_b', 'https://asia.test', :x, :b, 'rb', 'offered', 'd1'), "
            "('r_x', 'https://asia.test', :x, :x, 'rx', 'offered', 'd2'), "
            "('r_l', 'https://asia.test', :x, :l, 'rl', 'offered', 'd3')"), {"x": w.X, "b": w.B, "l": w.L})
        await s.commit()
    yield w
    await engine.dispose()


def _dev(w, k):
    return SimpleNamespace(id=w.devs[k], is_admin=False)


# A (his), B (his organization's, brought by an active member); not C (an inactive organization), not D (another
# owner's), not T (a treasury holds no seat: no road), not L (its creator was removed), not M (an inactive membership)
MINE_FOR_OWNER = {"o_a", "o_b", "o_ad"}


async def test_the_owners_guild_list_is_exactly_his_work(world):
    from agentvault_registry.routers import guild as G
    async with world.maker() as s:
        out = await G.owned_orders(limit=100, dev=_dev(world, "owner"), db=s)
    got = {o["id"]: o["my_parties"] for o in out["orders"]}
    assert set(got) == MINE_FOR_OWNER
    assert got["o_a"] == [{"role": "poster", "agent_did": world.A, "name": "Agent A", "via": "agent",
                           "organization_id": None, "organization_name": None}]
    assert got["o_b"] == [{"role": "worker", "agent_did": world.B, "name": "Agent B", "via": "organization",
                           "organization_id": "org-live", "organization_name": "Live org"}]
    assert [(p["role"], p["agent_did"]) for p in got["o_ad"]] == [("worker", world.A)]
    async with world.maker() as s:
        other = await G.owned_orders(limit=100, dev=_dev(world, "other_owner"), db=s)
        creator = await G.owned_orders(limit=100, dev=_dev(world, "b_creator"), db=s)
        member = await G.owned_orders(limit=100, dev=_dev(world, "member"), db=s)
        leaver = await G.owned_orders(limit=100, dev=_dev(world, "leaver"), db=s)
    assert {o["id"] for o in other["orders"]} == {"o_d", "o_ad"}
    # B, C, D, X and Y are his
    assert {o["id"] for o in creator["orders"]} == {"o_b", "o_c", "o_d", "o_t", "o_ad", "o_x", "o_l", "o_m", "o_f"}
    assert member["orders"] == [], "a member owns nothing: membership is not ownership"
    assert {o["id"] for o in leaver["orders"]} == {"o_l"}, "the removed member still reads his own agent's work"


async def test_a_removed_members_agent_still_assigned_is_not_the_owners(world):
    # HEAD 2862d4121: listed (the organization road read the assignment alone, which outlives the membership)
    from agentvault_registry.routers import contracts_v2 as C
    from agentvault_registry.routers import guild as G
    async with world.maker() as s:
        orders = {o["id"] for o in (await G.owned_orders(limit=100, dev=_dev(world, "owner"), db=s))["orders"]}
        contracts = {i["id"] for i in (await C.owned_contracts(status_f=None, limit=50, dev=_dev(world, "owner"),
                                                                db=s))["items"]}
    assert "o_l" not in orders and "co_l" not in contracts and "r_l" not in contracts, "a removed member's agent"
    assert "o_m" not in orders and "co_m" not in contracts, "a member whose membership is inactive"
    assert "o_t" not in orders and "co_t" not in contracts, "no treasury road: a treasury holds no seat"


async def test_the_owners_contract_list_holds_his_contracts_and_replicas(world):
    from agentvault_registry.routers import contracts_v2 as C
    async with world.maker() as s:
        out = await C.owned_contracts(status_f=None, limit=50, dev=_dev(world, "owner"), db=s)
    ids = {i["id"] for i in out["items"]}
    assert ids == {f"c{o}" for o in MINE_FOR_OWNER} | {"r_b"}
    rb = next(i for i in out["items"] if i["id"] == "r_b")
    assert rb["replica"] is True and [(p["role"], p["via"]) for p in rb["my_parties"]] == [("provider", "organization")]


async def test_the_sql_and_the_python_agree_on_every_row(world):
    from agentvault_registry.services import owner_reads as R
    tables = (("guild_work_orders", "id", R.GUILD_ROLES), ("contracts", "id", R.CONTRACT_ROLES),
              ("contract_replicas", "cid", R.CONTRACT_ROLES))
    for who in world.devs:
        dev = world.devs[who]
        async with world.maker() as s:
            for table, key, roles in tables:
                cols = [c for _r, c in roles]
                listed = {r[0] for r in (await s.execute(text(
                    f"SELECT t.{key} FROM {table} t WHERE " + R.owned_by_sql(*(f"t.{c}" for c in cols))),
                    {"dev": dev})).all()}
                rows = [dict(r) for r in (await s.execute(text(
                    f"SELECT {key} AS id, {', '.join(cols)} FROM {table}"))).mappings().all()]
                parties = await R.owned_parties(s, dev, rows, roles)
                for row, p in zip(rows, parties):
                    assert (row["id"] in listed) == bool(p), (who, table, row["id"], listed, p)


async def test_the_list_statement_reads_his_set_once_not_a_probe_per_row(world):
    # HEAD 2862d4121: a SubPlan (the correlated EXISTS ran once per order of the registry, however little he owns)
    from agentvault_registry.services import owner_reads as R
    async with world.maker() as s:
        plan = "\n".join(r[0] for r in (await s.execute(text(
            "EXPLAIN SELECT o.id FROM guild_work_orders o WHERE " + R.owned_by_sql("o.poster_did", "o.worker_did")),
            {"dev": world.devs["owner"]})).all())
    assert "SubPlan" not in plan, plan
    assert "InitPlan" in plan, plan


async def _sees(world, oid, who):
    from agentvault_registry.routers import guild as G
    async with world.maker() as s:
        o = dict((await s.execute(text("SELECT * FROM guild_work_orders WHERE id = :o"), {"o": oid})).mappings().first())
        return await G._may_see_deliverable(s, o, _dev(world, who))


async def test_the_deliverable_is_the_creators_and_the_firms_owners_on_real_rows(world):
    assert await _sees(world, "o_a", "owner") is True, "his own agent's work"
    assert await _sees(world, "o_b", "b_creator") is True, "the worker's creator"
    # HEAD 2862d4121: True (the owner of the organization B works in read the work B did on its own account)
    assert await _sees(world, "o_b", "owner") is False, "a member's agent's own work is not the organization's"
    # HEAD 2862d4121: True (the removed member's agent still assigned)
    assert await _sees(world, "o_l", "owner") is False
    # HEAD 2862d4121: False (the worker is in no organization of his now)
    assert await _sees(world, "o_f", "owner") is True, "the firm's work: the owner of the organization it was for"
    assert await _sees(world, "o_f", "member") is False, "a member of the firm is not its owner"
    assert await _sees(world, "o_f", "other_owner") is False
    assert await _sees(world, "o_c", "owner") is False, "an inactive organization: no"
