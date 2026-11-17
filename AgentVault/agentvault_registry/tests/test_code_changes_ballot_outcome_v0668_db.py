"""V0668 (order gwo_2d51e1af1b2a21a0bcdff5e7): the ballot's outcome through the REAL store, on Postgres.

The record's reason and numbers come from DbStore.proposal(); a fake store that carries them itself cannot show that the real
one returns them (V0666's bootstrap rule passed on a fake store while DbStore never returned tally_quorum_met). Here a real
governance proposal, tallied the way crud_governance.tally_proposal leaves it (the numbers of mig 0185 and its votes), is read
through DbStore and through the view's rule: the weight that took part is the votes' own voting power, for and against.
Runs where CODE_CHANGES_TEST_DB names a throwaway database (its name starting with test_); skipped, saying why, where not.
"""
from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal
from urllib.parse import urlparse

import pytest

from agentvault_registry.services import code_changes as cc

PG = os.environ.get("CODE_CHANGES_TEST_DB", "")
if not PG:
    pytest.skip("needs a REAL Postgres it may wipe: set CODE_CHANGES_TEST_DB (a database whose name starts with test_). Skipped, "
                "never silently passed.", allow_module_level=True)

TALLIED = dt.datetime(2026, 11, 17, 9, 26, 15, tzinfo=dt.timezone.utc)


@pytest.fixture()
async def db():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from agentvault_registry import models
    name = urlparse(PG).path.lstrip("/")
    assert name.startswith("test_"), f"refusing to drop the tables of {name!r}: name a database whose name starts with test_"
    engine = create_async_engine(PG)
    async with engine.begin() as c:
        await c.execute(text("DROP SCHEMA public CASCADE"))
        await c.execute(text("CREATE SCHEMA public"))
        await c.run_sync(models.Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _proposal(db, *, status, met, votes, required=330.6, network=3306.0, mode="member", tallied=TALLIED):
    from agentvault_registry import models
    p = models.GovernanceProposal(proposer_did="did:a:proposer", title="Code change cc_x", description="d", status=status,
                                  proposal_type="code_change", quorum_percent=10.0, pass_percent=50.0,
                                  end_timestamp=TALLIED - dt.timedelta(minutes=1), tally_weight_mode=mode,
                                  tally_network_power=network, tally_quorum_required=required, tally_quorum_met=met,
                                  tallied_at=tallied)
    db.add(p)
    await db.flush()
    for i, (vote, power) in enumerate(votes):
        db.add(models.Vote(proposal_id=p.id, voter_did=f"did:a:voter{i}", vote=vote, voting_power=Decimal(str(power))))
    await db.commit()
    return p.id


async def test_the_real_store_returns_the_votes_weight_and_the_numbers_the_tally_kept(db):
    pid = await _proposal(db, status="FAILED", met=False, votes=[(True, 100), (True, 100), (True, 100)])
    p = await cc.store_for(db).proposal(pid)
    assert (p["votes_for"], p["votes_against"], p["tally_quorum_required"], p["tally_network_power"]) == (300.0, 0.0, 330.6, 3306.0)
    assert (p["tally_weight_mode"], p["tally_quorum_met"], p["quorum_percent"], p["pass_percent"]) == ("member", False, 10.0, 50.0)
    o = cc.ballot_outcome(p)
    assert (o["reason"], o["took_part"], o["required"], o["tallied_at"]) == ("quorum_not_met", 300.0, 330.6, cc._iso(TALLIED))


async def test_a_rejected_ballot_through_the_real_store(db):
    pid = await _proposal(db, status="FAILED", met=True, votes=[(True, 150), (False, 250.5)])
    o = cc.ballot_outcome(await cc.store_for(db).proposal(pid))
    assert (o["reason"], o["for"], o["against"], o["share_for"]) == ("rejected", 150.0, 250.5, 37.5)


async def test_a_proposal_with_no_votes_reads_zero_weight_not_none(db):
    pid = await _proposal(db, status="FAILED", met=False, votes=[])
    p = await cc.store_for(db).proposal(pid)
    assert (p["votes_for"], p["votes_against"]) == (0.0, 0.0)
    assert cc.ballot_outcome(p)["took_part"] == 0.0
