"""V0666 repository accounts on a REAL Postgres (gwo_662c03447bcd627afa4a11e5; SQLite never sees a CHECK). Three halves:

  1. the CHECKs refuse what the rules refuse: a username outside the rule, a state or a leg that is not a known word, a paused
     account with no record of what the pause found, a leg marked done with no time, a negative attempt count; one account per
     developer and one developer per username (the keys)
  2. the migration (alembic/versions/0234_repo_accounts.py) creates exactly the constraints the models declare, and its downgrade
     removes both tables
  3. the database store under the flow: a link recorded, a leg written in the caller's transaction and kept or lost with it, the
     drain landing it, good standing read as the code change rail reads it (a deletion pending, requested or done is not)

Skipped unless REPO_ACCOUNTS_TEST_DB names a throwaway database it may WIPE (postgresql+asyncpg://...). Skipped, never silently
passed. RED on 633f06b42: there is no RepoAccount model and no migration 0234.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import pathlib
import uuid

import pytest

DB = os.environ.get("REPO_ACCOUNTS_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres database it may wipe: set REPO_ACCOUNTS_TEST_DB. Skipped, never silently passed.",
                allow_module_level=True)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

MIGRATION = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0234_repo_accounts.py"
NOW = dt.datetime(2026, 11, 16, 1, 0, tzinfo=dt.timezone.utc)


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


async def _dev(s, **kw):
    from agentvault_registry.models import Developer
    d = Developer(name=f"d-{uuid.uuid4().hex[:6]}", email=f"{uuid.uuid4().hex[:8]}@test.local", hashed_password="x",
                  is_verified=kw.pop("is_verified", True), **kw)
    s.add(d)
    await s.flush()
    return d.id


@pytest.mark.parametrize("over", [{"username": "Ada"}, {"username": "-ada"}, {"username": "ab"}, {"state": "frozen"},
                                  {"state": "paused", "paused_before": None}])
async def test_the_account_checks_refuse_what_the_rules_refuse(maker, over):
    from agentvault_registry.models import RepoAccount
    async with maker() as s:
        dev = await _dev(s)
        row = {"developer_id": dev, "username": "ada-lovelace", "host_user_id": 10, "state": "active", "paused_before": None}
        s.add(RepoAccount(**{**row, **over}))
        with pytest.raises(IntegrityError):
            await s.commit()


@pytest.mark.parametrize("over", [{"op": "delete"}, {"status": "failed"}, {"status": "done", "done_at": None}, {"attempts": -1}])
async def test_the_leg_checks_refuse_what_the_rules_refuse(maker, over):
    from agentvault_registry.models import RepoAccount, RepoAccountOp
    async with maker() as s:
        dev = await _dev(s)
        s.add(RepoAccount(developer_id=dev, username="ada-lovelace", host_user_id=10, state="active"))
        await s.flush()
        row = {"developer_id": dev, "op": "pause", "cause": "developer_suspended", "status": "pending", "attempts": 0}
        s.add(RepoAccountOp(**{**row, **over}))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_one_account_per_developer_and_one_developer_per_username(maker):
    from agentvault_registry.models import RepoAccount
    async with maker() as s:
        a, b = await _dev(s), await _dev(s)
        s.add(RepoAccount(developer_id=a, username="ada-lovelace", host_user_id=10, state="active"))
        await s.commit()
    async with maker() as s:
        s.add(RepoAccount(developer_id=b, username="ada-lovelace", host_user_id=11, state="active"))
        with pytest.raises(IntegrityError):
            await s.commit()
    async with maker() as s:
        s.add(RepoAccount(developer_id=a, username="ada-two", host_user_id=12, state="active"))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_the_migration_creates_exactly_the_models_constraints_and_its_downgrade_removes_them(maker):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location("m0234", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.down_revision == "0233_guild_orders_agent_org" and len(mod.revision) <= 32
    engine = create_async_engine(DB)

    async def checks(conn):
        rows = (await conn.execute(text(
            "SELECT conrelid::regclass::text || '.' || conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid IN ('repo_accounts'::regclass, 'repo_account_ops'::regclass) ORDER BY 1"))).all()
        return {n: d for n, d in rows}

    def run(sync_conn, fn):
        with Operations.context(MigrationContext.configure(sync_conn)):
            fn()

    async with engine.begin() as conn:
        from_models = await checks(conn)
        await conn.run_sync(run, mod.downgrade)
        for t in ("repo_accounts", "repo_account_ops"):
            assert (await conn.execute(text(f"SELECT to_regclass('{t}')"))).scalar() is None, t
        await conn.run_sync(run, mod.upgrade)
        from_migration = await checks(conn)
        idx = (await conn.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'repo_account_ops'"))).scalars().all()
    await engine.dispose()
    assert from_migration == from_models, (from_migration, from_models)
    assert "ix_repo_account_ops_pending" in idx


async def test_the_store_under_the_flow(maker, monkeypatch):
    from agentvault_registry.services import repo_accounts as ra

    class FakeClient:
        def __init__(self):
            self.users = {}

        async def create_user(self, username, email, password):
            self.users[username] = {"id": len(self.users) + 10, "login": username, "email": email, "prohibit_login": False}
            return self.users[username]["id"]

        async def get_user(self, username):
            return dict(self.users[username])

        async def edit_user(self, username, fields):
            self.users[username].update(fields)
            return dict(self.users[username])
    monkeypatch.setenv("REPO_ACCOUNTS_ENABLED", "true")
    client = FakeClient()
    async with maker() as s:
        dev = await _dev(s)
        leaving = await _dev(s, deletion_status="pending_deletion", deletion_requested_at=NOW)
        await s.commit()
    async with maker() as s:
        flow = ra.RepoAccounts(ra.DbStore(s), client, now=lambda: NOW)
        out = await flow.link(dev, {"username": "ada-lovelace", "confirm": True, "accept_terms": ra.terms_version()})
        await s.commit()
        assert out["username"] == "ada-lovelace"
        with pytest.raises(ra.RepoAccountRefusal) as e:
            await flow.link(leaving, {"username": "leaving-one", "confirm": True, "accept_terms": ra.terms_version()})
        assert e.value.code == "deleted"
    # a leg written in a transaction that rolls back is gone with it
    async with maker() as s:
        await ra.enqueue_in(s, dev, "pause", "developer_suspended")
        await s.rollback()
    async with maker() as s:
        assert await ra.DbStore(s).pending_ops() == []
        await ra.enqueue_in(s, dev, "pause", "developer_suspended")
        await s.commit()
    async with maker() as s:
        flow = ra.RepoAccounts(ra.DbStore(s), client, now=lambda: NOW)
        assert await flow.drain_once() == 1
    async with maker() as s:
        st = ra.DbStore(s)
        assert (await st.account(dev))["state"] == "paused" and (await st.account(dev))["paused_before"] == {"prohibit_login": False}
        assert await st.pending_ops() == [] and client.users["ada-lovelace"]["prohibit_login"] is True


async def test_the_route_records_the_terms_accepted_at_the_press(maker, monkeypatch):
    """session-lead room seq 5175 (Terms § 10.2): pressing Link repository account accepts the Terms served now. The route writes
    the acceptance record (via repo_account_link) and the developer's fast-path columns in the link's own transaction; a stale
    version creates nothing at all."""
    import json
    from agentvault_registry.models import Developer
    from agentvault_registry.routers import repo_accounts as route
    from agentvault_registry.services import repo_accounts as ra

    class FakeClient:
        def __init__(self, *a, **k):
            self.users = {}

        async def create_user(self, username, email, password):
            self.users[username] = {"id": 77, "login": username}
            return 77

        async def get_user(self, username):
            return dict(self.users[username])

        async def edit_user(self, username, fields):
            return dict(self.users[username])

    class Req:
        headers = {"user-agent": "the console"}
        client = None
    monkeypatch.setenv("REPO_ACCOUNTS_ENABLED", "true")
    monkeypatch.setattr(ra, "ForgejoClient", FakeClient)
    async with maker() as s:
        dev_id = await _dev(s)
        await s.commit()
    served = ra.terms_version()
    async with maker() as s:
        dev = await s.get(Developer, dev_id)
        stale = await route.link_repo_account(route.LinkIn(username="ada-lovelace", confirm=True, accept_terms="1.0"), Req(), dev, s)
        assert stale.status_code == 409 and json.loads(stale.body)["code"] == "legal_version_mismatch"
    async with maker() as s:
        n = (await s.execute(text("SELECT (SELECT count(*) FROM repo_accounts), (SELECT count(*) FROM legal_acceptances)"))).one()
        assert tuple(n) == (0, 0)
        dev = await s.get(Developer, dev_id)
        ok = await route.link_repo_account(route.LinkIn(username="ada-lovelace", confirm=True, accept_terms=served), Req(), dev, s)
        assert ok.status_code == 201
    async with maker() as s:
        row = (await s.execute(text("SELECT developer_id, document, version, via, user_agent FROM legal_acceptances"))).one()
        assert tuple(row) == (dev_id, "terms", served, "repo_account_link", "the console")
        assert (await s.get(Developer, dev_id)).tos_accepted_version == served




async def test_a_failed_commit_leaves_no_account_anywhere(maker, monkeypatch):
    """session-lead room seq 5217 (V0667 follow-up 2): the host user is made before the registry commits; when the commit
    fails, the route removes that user again and answers 503, so no account exists that the registry does not know."""
    import json
    from agentvault_registry.models import Developer
    from agentvault_registry.routers import repo_accounts as route
    from agentvault_registry.services import repo_accounts as ra
    made = {}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def create_user(self, username, email, password):
            made[username] = 88
            return 88

        async def get_user(self, username):
            return {"id": made[username], "login": username}

        async def edit_user(self, username, fields):
            return {}

        async def delete_user(self, username):
            made.pop(username, None)

    class Req:
        headers = {"user-agent": "the console"}
        client = None
    monkeypatch.setenv("REPO_ACCOUNTS_ENABLED", "true")
    monkeypatch.setattr(ra, "ForgejoClient", FakeClient)
    async with maker() as s:
        dev_id = await _dev(s)
        await s.commit()
    async with maker() as s:
        dev = await s.get(Developer, dev_id)

        async def broken_commit():
            raise RuntimeError("the database went away")
        monkeypatch.setattr(s, "commit", broken_commit)
        out = await route.link_repo_account(route.LinkIn(username="ada-lovelace", confirm=True, accept_terms=ra.terms_version()),
                                            Req(), dev, s)
        assert out.status_code == 503 and json.loads(out.body)["code"] == "not_recorded"
    assert made == {}
    async with maker() as s:
        n = (await s.execute(text("SELECT (SELECT count(*) FROM repo_accounts), (SELECT count(*) FROM legal_acceptances)"))).one()
        assert tuple(n) == (0, 0)
