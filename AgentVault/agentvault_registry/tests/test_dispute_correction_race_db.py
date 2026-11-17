"""V0657 (a), session-lead's review (room seq 1597): two corrections of one ruling sent at the same moment, on a REAL
Postgres. Both read the old ruling; the record is claimed before any effect, so one is refused (CorrectionInFlight, the
route's 409) and every reputation change is made once: dispute 1's shape ends with the worker at 2 + 10 + 2 and the
poster at 12 - 2, the warning reversed once, one correction row, 'applied'. Then two finishes of a correction a failure
left 'applying' run at once: each remaining step is done once.

Skipped unless DISPUTES_TEST_DB names a throwaway database it may WIPE (postgresql+asyncpg://...).
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

DB = os.environ.get("DISPUTES_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres it may wipe: set DISPUTES_TEST_DB. Skipped, never silently passed.",
                allow_module_level=True)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

NOTE = "It delivered and was paid; the record stayed open by mistake."


@pytest.fixture
async def maker(monkeypatch):
    from agentvault_registry.models import Base
    from tests._doubles import StrictEmitter
    engine = create_async_engine(DB, pool_size=4)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    emitter = StrictEmitter()
    monkeypatch.setattr("agentvault_registry.event_emitter.get_event_emitter", lambda: emitter)

    async def _none(*a, **k):
        return None
    monkeypatch.setattr("agentvault_registry.background_tasks.push_notify.notify_agent_owners", _none)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _dispute_one(maker):
    """Dispute 1's shape: ruled for the poster before V0657 (no record of its changes), a warning on the worker."""
    from agentvault_registry.models import Agent, Developer, Dispute, EnforcementAction
    async with maker() as s:
        dev = Developer(name="owner", email=f"o{uuid.uuid4().hex[:6]}@test.local", hashed_password="x", is_verified=True)
        s.add(dev)
        await s.flush()
        poster, worker = (f"did:theprotocol:test:{n}-{uuid.uuid4().hex[:8]}" for n in ("poster", "worker"))
        for did, score in ((poster, 12), (worker, 2)):
            s.add(Agent(did=did, client_id=f"c-{uuid.uuid4().hex[:10]}", hashed_client_secret="x",
                        creator_developer_id=dev.id, status="active", enforcement_status="active",
                        reputation_score=score, offense_count=1 if did == worker else 0,
                        enforcement_level=1 if did == worker else 0))
        await s.flush()
        d = Dispute(status="CLOSED", ruling="IN_FAVOR_OF_COMPLAINANT", complainant_did=poster, defendant_did=worker,
                    filed_by="system", reason="deadline_missed")
        s.add(d)
        await s.flush()
        s.add(EnforcementAction(id=f"ea_{uuid.uuid4().hex[:8]}", agent_did=worker, action_type="warn",
                                trigger="dispute_ruling", trigger_reference=str(d.id), status="executed",
                                escalation_level=1, policy_version=1))
        await s.commit()
        return d.id, poster, worker


async def _state(maker, poster, worker, dispute_id):
    async with maker() as s:
        scores = dict((await s.execute(text("SELECT did, reputation_score FROM agents WHERE did = ANY(:d)"),
                                       {"d": [poster, worker]})).all())
        offenses = (await s.execute(text("SELECT offense_count FROM agents WHERE did = :d"), {"d": worker})).scalar()
        actions = [r[0] for r in (await s.execute(text(
            "SELECT status FROM enforcement_actions WHERE trigger_reference = :r"), {"r": str(dispute_id)})).all()]
        corrections = (await s.execute(text(
            "SELECT status, to_ruling FROM dispute_corrections WHERE dispute_id = :d ORDER BY id"),
            {"d": dispute_id})).all()
        ruling = (await s.execute(text("SELECT ruling FROM disputes WHERE id = :d"), {"d": dispute_id})).scalar()
    return scores, offenses, actions, [tuple(c) for c in corrections], ruling


async def test_two_corrections_at_once_on_postgres_one_409_and_every_change_once(maker):
    from agentvault_registry.services import dispute_correction as dc
    dispute_id, poster, worker = await _dispute_one(maker)

    async def one(note):
        async with maker() as s:
            return await dc.apply(s, dispute_id, "IN_FAVOR_OF_DEFENDANT", note=note, corrected_by=6)
    results = await asyncio.gather(one(NOTE), one(NOTE + " (the retry)"), return_exceptions=True)
    refused = [r for r in results if isinstance(r, dc.CorrectionInFlight)]
    done = [r for r in results if isinstance(r, dict)]
    assert len(refused) == 1 and len(done) == 1, results
    scores, offenses, actions, corrections, ruling = await _state(maker, poster, worker, dispute_id)
    assert scores == {worker: 2 + 10 + 2, poster: 12 - 2}, scores
    assert offenses == 0 and actions == ["reversed"], (offenses, actions)
    assert corrections == [("applied", "IN_FAVOR_OF_DEFENDANT")] and ruling == "IN_FAVOR_OF_DEFENDANT"


async def test_two_finishes_at_once_on_postgres_do_each_step_once(maker, monkeypatch):
    from agentvault_registry.services import dispute_correction as dc
    dispute_id, poster, worker = await _dispute_one(maker)
    real = dc._reverse_action

    async def fails(*a, **k):
        raise RuntimeError("the database went away mid-correction")
    monkeypatch.setattr(dc, "_reverse_action", fails)
    with pytest.raises(RuntimeError):
        async with maker() as s:
            await dc.apply(s, dispute_id, "IN_FAVOR_OF_DEFENDANT", note=NOTE, corrected_by=6)
    scores, _, actions, corrections, _ = await _state(maker, poster, worker, dispute_id)
    assert corrections == [("applying", "IN_FAVOR_OF_DEFENDANT")] and actions == ["executed"]
    assert scores == {worker: 12, poster: 10}, "the reversal made before the failure stands, once"
    monkeypatch.setattr(dc, "_reverse_action", real)
    async with maker() as s:
        cid = await dc.applying_correction_id(s, dispute_id)

    async def fin():
        async with maker() as s:
            return await dc.finish(s, dispute_id, cid)
    results = await asyncio.gather(fin(), fin(), return_exceptions=True)
    assert all(isinstance(r, (dict, dc.CorrectionRefused)) for r in results), results
    scores, offenses, actions, corrections, _ = await _state(maker, poster, worker, dispute_id)
    assert scores == {worker: 14, poster: 10}, scores
    assert offenses == 0 and actions == ["reversed"] and corrections == [("applied", "IN_FAVOR_OF_DEFENDANT")]


async def test_the_loser_of_a_real_race_is_refused_not_crashed(maker, monkeypatch):
    """Both corrections read the dispute and plan BEFORE either claims it (held at plan until both have planned), so the claim
    itself decides: one claims, the other's claim matches no row. The loser rolls back and must answer CorrectionInFlight (the
    route's 409). Its rollback expires the dispute it read, so reading the dispute's id from that object afterwards is a lazy
    load, which on an async session raises MissingGreenlet. Without the hold the two can run one after the other and the
    loser is refused earlier, by plan (the first race test on this file can pass that way)."""
    from agentvault_registry.services import dispute_correction as dc
    dispute_id, poster, worker = await _dispute_one(maker)
    real, planned, both = dc.plan, [], asyncio.Event()

    async def held(db, d, new):
        p = await real(db, d, new)
        planned.append(1)
        if len(planned) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 15)
        return p
    monkeypatch.setattr(dc, "plan", held)

    async def one(note):
        async with maker() as s:
            return await dc.apply(s, dispute_id, "IN_FAVOR_OF_DEFENDANT", note=note, corrected_by=6)
    results = await asyncio.gather(one(NOTE), one(NOTE + " (the retry)"), return_exceptions=True)
    assert len(planned) == 2, "both planned before either claimed"
    refused = [r for r in results if isinstance(r, dc.CorrectionInFlight)]
    done = [r for r in results if isinstance(r, dict)]
    assert len(refused) == 1 and len(done) == 1, results
    assert f"dispute {dispute_id}" in str(refused[0]).lower()          # either refusal names it: still applying, or changed
    scores, offenses, actions, corrections, ruling = await _state(maker, poster, worker, dispute_id)
    assert scores == {worker: 2 + 10 + 2, poster: 12 - 2}, scores
    assert corrections == [("applied", "IN_FAVOR_OF_DEFENDANT")] and ruling == "IN_FAVOR_OF_DEFENDANT"
