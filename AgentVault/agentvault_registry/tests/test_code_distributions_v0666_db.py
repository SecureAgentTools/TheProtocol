"""V0666 D1, code distributions on a REAL Postgres (the order: "the migration with its Postgres CHECKs ... and a real-Postgres
test"; SQLite never sees a CHECK). Three halves:

  1. the CHECKs refuse what the rules refuse: a slug, a base release, a quorum out of 50-100, a pass rule or a state that
     is not a known word, a pause with no reason; a second vote of one developer on one change (the primary key);
  2. the migration itself (alembic/versions/0231_code_distributions.py) creates exactly the constraints the models
     declare, and its downgrade removes what it added;
  3. DbStore's reads the rule stands on: the organization's ACTIVE memberships with their roles, a team's active leads,
     the developers in good standing (verified, not suspended, no deletion pending or done), the main line's list without
     a line's changes, and a team a line names (team_in_use).

Skipped unless CODE_DISTRIBUTIONS_TEST_DB names a throwaway database it may WIPE (postgresql+asyncpg://...). Skipped, never
silently passed. RED on 2200f0c46: there is no CodeDistribution model and no migration 0231.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import pathlib
import uuid

import pytest

DB = os.environ.get("CODE_DISTRIBUTIONS_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres database it may wipe: set CODE_DISTRIBUTIONS_TEST_DB. Skipped, never silently passed.",
                allow_module_level=True)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

MIGRATION = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0231_code_distributions.py"


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


async def _seed(maker):
    from agentvault_registry.models import Developer, Organization, OrganizationMember, Team, TeamMember
    async with maker() as s:
        devs = {}
        for key, extra in (("owner", {}), ("admin", {}), ("lead", {}), ("guestlead", {}), ("member", {}),
                           ("unverified", {"is_verified": False}), ("suspended", {"is_suspended": True}),
                           ("leaving", {"deletion_status": "pending_deletion",
                                        "deletion_requested_at": dt.datetime.now(dt.timezone.utc)}),
                           ("gone", {})):
            d = Developer(name=f"{key}-{uuid.uuid4().hex[:6]}", email=f"{key}{uuid.uuid4().hex[:6]}@test.local",
                          hashed_password="x", is_verified=extra.pop("is_verified", True), **extra)
            s.add(d)
            await s.flush()
            devs[key] = d.id
        org = Organization(id=f"org-{uuid.uuid4().hex[:8]}", name="Lyceum", slug=f"lyceum-{uuid.uuid4().hex[:6]}",
                           owner_id=devs["owner"])
        s.add(org)
        await s.flush()
        for key, role, active in (("owner", "owner", True), ("admin", "admin", True), ("lead", "member", True),
                                  ("guestlead", "guest", True), ("member", "member", True), ("unverified", "admin", True),
                                  ("suspended", "admin", True), ("leaving", "admin", True), ("gone", "admin", False)):
            s.add(OrganizationMember(id=uuid.uuid4().hex, organization_id=org.id, developer_id=devs[key], role=role,
                                     is_active=active))
        team = Team(id=f"team-{uuid.uuid4().hex[:8]}", organization_id=org.id, name="Core")
        s.add(team)
        await s.flush()
        for key, role, active in (("lead", "lead", True), ("guestlead", "lead", True), ("member", "member", True),
                                  ("admin", "lead", False)):
            s.add(TeamMember(id=uuid.uuid4().hex, team_id=team.id, developer_id=devs[key], role=role, is_active=active))
        await s.commit()
        return devs, org.id, team.id


def _dist(org_id, team_id=None, **over):
    from agentvault_registry.models import CodeDistribution
    row = {"id": f"cdst_{uuid.uuid4().hex[:12]}", "organization_id": org_id, "slug": f"l{uuid.uuid4().hex[:8]}",
           "title": "Lyceum", "base_release": "V0666", "open_paths": ["a/"], "decider_team_id": team_id,
           "quorum_percent": 50, "pass_rule": "simple", "state": "active", "created_by_developer_id": 1}
    row.update(over)
    return CodeDistribution(**row)


@pytest.mark.parametrize("over", [{"slug": "Bad"}, {"base_release": "v666"}, {"quorum_percent": 49},
                                  {"quorum_percent": 101}, {"pass_rule": "two_thirds"}, {"state": "frozen"},
                                  {"state": "paused"}])
async def test_the_checks_refuse_what_the_rules_refuse(maker, over):
    devs, org, team = await _seed(maker)
    async with maker() as s:
        s.add(_dist(org, team, **over))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_a_good_line_is_stored_and_one_developer_votes_once(maker):
    from agentvault_registry.models import CodeChange, CodeDistributionVote
    devs, org, team = await _seed(maker)
    async with maker() as s:
        d = _dist(org, team)
        s.add(d)
        await s.flush()
        s.add(CodeChange(id="cc_line1", repository="r", paths=["a/x"], title="t", problem="p", mode="branch",
                         proposer_did="did:a", proposer_developer_id=devs["member"], sensitive=False, state="balloting",
                         code_distribution_id=d.id))
        await s.flush()
        s.add(CodeDistributionVote(code_change_id="cc_line1", developer_id=devs["owner"], vote=True, agent_did="did:o"))
        await s.commit()
    async with maker() as s:
        s.add(CodeDistributionVote(code_change_id="cc_line1", developer_id=devs["owner"], vote=False, agent_did="did:o"))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_the_store_reads_the_rule_stands_on(maker):
    from agentvault_registry.models import CodeChange
    from agentvault_registry.services import code_distributions as cd
    from agentvault_registry.services.code_changes import DbStore
    devs, org, team = await _seed(maker)
    async with maker() as s:
        d = _dist(org, team)
        s.add(d)
        await s.flush()
        for cid, line in (("cc_main", None), ("cc_line", d.id)):
            s.add(CodeChange(id=cid, repository="r", paths=["a/x"], title="t", problem="p", mode="branch",
                             proposer_did="did:a", proposer_developer_id=devs["member"], sensitive=False,
                             state="proposed", code_distribution_id=line))
        await s.commit()
        dist_id = d.id
    async with maker() as s:
        store = DbStore(s)
        members = await store.org_members(org)
        assert await store.organization_names([org, "org-nosuch"]) == {org: "Lyceum"}, "D2: a name for a known id, nothing else"
        assert devs["gone"] not in members and members[devs["owner"]] == "owner" and members[devs["guestlead"]] == "guest"
        assert await store.team_leads(team) == {devs["lead"], devs["guestlead"]}, "an inactive lead is no lead"
        good = await store.developers_in_good_standing(list(devs.values()))
        assert good == {devs[k] for k in ("owner", "admin", "lead", "guestlead", "member", "gone")}
        who, why = await cd.deciders(store, await store.distribution(dist_id))
        assert who == {devs["owner"], devs["admin"], devs["lead"]} and why is None
        assert [r["id"] for r in await store.list(None, 50)] == ["cc_main"], "the main line's list holds no line's change"
        assert [r["id"] for r in await store.list(None, 50, dist_id)] == ["cc_line"]
        assert await cd.team_in_use(s, team) == (await store.distribution(dist_id))["slug"]


async def test_the_migration_creates_exactly_the_models_constraints_and_its_downgrade_removes_them(maker):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location("m0231", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    engine = create_async_engine(DB)

    async def checks(conn):
        rows = (await conn.execute(text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'code_distributions'::regclass "
            "AND contype = 'c' ORDER BY conname"))).all()
        return {n: d for n, d in rows}

    def run(sync_conn, fn):
        with Operations.context(MigrationContext.configure(sync_conn)):
            fn()

    async with engine.begin() as conn:
        from_models = await checks(conn)
        # V0667 D5: a database built from the models also holds the fast lane's tables, which reference code_distributions; the chain downgrades 0236 before 0231
        # V0667 D6 part 3: and the scoped release channel's two tables, which reference code_distributions too; the chain downgrades 0238 first
        await conn.execute(text("DROP TABLE IF EXISTS distribution_pull_grants, distribution_releases, content_change_votes, content_changes"))
        await conn.run_sync(run, mod.downgrade)
        for col in ("code_distribution_id", "ballot_rule", "ballot_ends", "ballot_result", "org_go"):
            assert not (await conn.execute(text(
                "SELECT 1 FROM information_schema.columns WHERE table_name = 'code_changes' AND column_name = :c"),
                {"c": col})).first(), col
        assert (await conn.execute(text("SELECT to_regclass('code_distributions')"))).scalar() is None
        await conn.run_sync(run, mod.upgrade)
        from_migration = await checks(conn)
    await engine.dispose()
    assert set(from_migration) == set(mod.CHECKS) == set(from_models), (from_migration, from_models)
    assert from_migration == from_models
