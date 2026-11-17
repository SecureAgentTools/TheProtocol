"""V0666 (order gwo_e086b25f868da7ec9fce9fd2) on a REAL Postgres: a registry that is not the governing one writes NO code_changes row, NO review, NO bounty order and NO governance
proposal of the type, by any step of the rail; the governing registry still writes them.

The store is the production one (services/code_changes.DbStore on a real session). The refusal is raised before the first statement, so the counts of four tables stay exactly 0 after a
refusal of every flow step and every store write, and the same calls on the governing registry write (the control that the counts can move at all).

Skipped unless CODE_CHANGES_TEST_DB names a throwaway database it may WIPE (postgresql+asyncpg://...). Skipped, never silently passed.
"""
from __future__ import annotations

import datetime as dt
import os
import uuid

import pytest

DB = os.environ.get("CODE_CHANGES_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres database it may wipe: set CODE_CHANGES_TEST_DB. Skipped, never silently passed.", allow_module_level=True)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from agentvault_registry.services import code_authority as ca  # noqa: E402
from agentvault_registry.services import code_changes as cc  # noqa: E402
from agentvault_registry.services import code_distributions as cd  # noqa: E402


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


async def _counts(maker):
    async with maker() as s:
        return {t: (await s.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one()
                for t in ("code_changes", "code_change_reviews", "guild_work_orders", "governance_proposals", "code_distributions", "code_distribution_votes")}


ROW = {"id": "cc_x", "state": "proposed"}        # placeholder: the refusal happens before any column is read


async def _try_every_write(maker):
    """Every flow step and every store write, once; returns the codes the refusals carried."""
    out = []
    async with maker() as db:
        store = cc.DbStore(db)
        flow = cc.CodeChangeFlow(store)
        lines = cd.CodeDistributionFlow(store)
        calls = [flow.propose({"did": "d", "developer_id": 1}, {"title": "t", "problem": "p", "repository": "r", "paths": ["a"]}),
                 flow.record_acceptance({"admin": True}, "cc_1", {}), flow.review({"developer_id": 1}, "cc_1", {"verdict": "approve", "commit": "a"}),
                 flow.open_ballot({"did": "d", "developer_id": 1}, "cc_1"), flow.veto({"admin": True}, "cc_1", {}), flow.withdraw({"admin": True}, "cc_1", {}),
                 flow.go({"admin": True}, "cc_1"), flow.record_merge({"admin": True}, "cc_1", {}),
                 store.create_proposal(title="t", description="d", diff={}, quorum=1.0, pass_percent=1.0, ends=dt.datetime.now(dt.timezone.utc)),
                 store.insert(dict(ROW)), store.update("cc_x", state="passed"), store.add_review({"id": "r"}), store.void_proposal(1),
                 store.post_bounty_order({"did": "d"}, title="t", spec="s", bounty=1.0, currency="ECU"), store.settle_order("o", actor="x"),
                 store.return_order("o", actor="x", reason="r"),
                 flow.line_vote({"did": "d", "developer_id": 1}, "cc_1", {"vote": True}), flow.line_owner_veto({"developer_id": 1}, "cc_1", {}), flow.line_owner_go({"developer_id": 1}, "cc_1"),
                 flow.propose_upstream({"did": "d", "developer_id": 1}, "cc_1"),
                 store._announce("cc_1"), store.add_distribution_vote({"code_change_id": "cc_1", "developer_id": 1, "vote": True, "agent_did": "d", "cast_at": dt.datetime.now(dt.timezone.utc)}),
                 store.insert_distribution({"id": "cdst_x"}), store.update_distribution("cdst_x", state="paused"),
                 lines.create({"developer_id": 1}, {"organization_id": "o", "slug": "line-a"}), lines.update({"developer_id": 1}, "line-a", {"title": "t"}),
                 lines.pause({"developer_id": 1, "admin": True}, "line-a", "r"), lines.resume({"developer_id": 1, "admin": True}, "line-a")]
        for c in calls:
            try:
                await c
                out.append(None)
            except cc.CodeChangeRefusal as r:
                out.append(r.code)
    return out


async def test_a_registry_that_does_not_govern_writes_nothing_by_any_step(maker, monkeypatch):
    monkeypatch.setattr(ca, "own_name", lambda: "asia")
    monkeypatch.setenv(ca.ENV, "eu")
    before = await _counts(maker)
    assert before == {"code_changes": 0, "code_change_reviews": 0, "guild_work_orders": 0, "governance_proposals": 0, "code_distributions": 0, "code_distribution_votes": 0}
    codes = await _try_every_write(maker)
    assert codes == ["code_change_not_governed_here"] * 28, codes
    assert await _counts(maker) == before, "a refused step wrote a row"


async def test_unset_is_read_only_too(maker, monkeypatch):
    monkeypatch.setattr(ca, "own_name", lambda: "eu")
    monkeypatch.delenv(ca.ENV, raising=False)
    assert set(await _try_every_write(maker)) == {"code_change_not_governed_here"}
    assert (await _counts(maker))["governance_proposals"] == 0


async def test_the_governing_registry_still_writes(maker, monkeypatch):
    """The control: the same store, on the registry the env names, writes its proposal (and nothing refuses it)."""
    monkeypatch.setattr(ca, "own_name", lambda: "eu")
    monkeypatch.setenv(ca.ENV, "eu")
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "eu.theprotocol.cloud")
    async with maker() as db:
        pid = await cc.DbStore(db).create_proposal(title="t", description="d", diff={}, quorum=10.0, pass_percent=60.0,
                                                   ends=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7))
    assert isinstance(pid, int)
    c = await _counts(maker)
    assert c["governance_proposals"] == 1
    async with maker() as s:
        row = (await s.execute(text("SELECT proposal_type FROM governance_proposals"))).scalar_one()
    assert row == "code_change"


async def test_reads_still_answer_where_nothing_governs(maker, monkeypatch):
    monkeypatch.setattr(ca, "own_name", lambda: "asia")
    monkeypatch.setenv(ca.ENV, "eu")
    async with maker() as db:
        store = cc.DbStore(db)
        assert await store.list(None, 10) == []
        flow = cc.CodeChangeFlow(store)
        with pytest.raises(cc.CodeChangeRefusal) as e:
            await flow.view("nope")
    assert e.value.code != "code_change_not_governed_here", "a read of a missing record says it is missing, not that code is governed elsewhere"
