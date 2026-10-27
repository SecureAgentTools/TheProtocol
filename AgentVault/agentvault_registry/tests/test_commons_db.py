"""§MEMBERSHIP phase B (2026-10-02) — a whole commons season against a REAL Postgres, with the payment rail faked.

Skipped unless MEMBERSHIP_TEST_DB names a throwaway database it may WIPE. No money moves here: the reward funding
waterfall is replaced by a recorder, and what is asserted is what the commons ASKS it to pay (one payment per
recipient, keyed so a re-run pays nothing). The real rail is proven on the sandbox with Δ 0.0 after every award.
"""
from __future__ import annotations

import datetime as dt
import os
import uuid
from decimal import Decimal

import pytest

DB = os.environ.get("MEMBERSHIP_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres it may wipe: set MEMBERSHIP_TEST_DB. Skipped, never silently passed.",
                allow_module_level=True)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

UTC = dt.timezone.utc
NOW = dt.datetime.now(UTC)


@pytest.fixture(autouse=True)
def _knobs(monkeypatch):
    from agentvault_registry.core import network_profile as np_
    for k in ("GOVERNANCE_WEIGHT_MODE", "GOVERNANCE_PRESENCE_MODE", "GOVERNANCE_MEMBER_REQUIRES_MATURED_BOND",
              "COMMONS_FEE_SHARE_PERCENT", "COMMONS_RECIPIENT_CAP_PERCENT", "COMMONS_MIN_VOTERS_PER_SUBMISSION",
              "COMMONS_MAX_SUBMISSIONS_PER_DEVELOPER", "COMMONS_MAX_BUDGET", "NETWORK_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("COMMONS_ENABLED", "true")
    monkeypatch.setenv("GOVERNANCE_MEMBER_MIN_BOND_AGE_DAYS", "0")
    monkeypatch.setenv("FRAME_CURRENCY", "SBXA")
    np_.reset_cache()
    yield
    np_.reset_cache()


@pytest.fixture
async def session():
    from agentvault_registry.models import Base
    engine = create_async_engine(DB)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _member(s, name, *, bond=True, verified=True):
    """A developer with one agent; with bond=True a self-funded bond makes them a member (age knob 0)."""
    from agentvault_registry.models import Agent, Developer, ReputationBond
    d = Developer(name=name, email=f"{name}@test.local", hashed_password="x", is_verified=verified)
    s.add(d)
    await s.flush()
    a = Agent(did=f"did:theprotocol:{uuid.uuid4()}", client_id=f"cid-{uuid.uuid4().hex[:12]}",
              hashed_client_secret="x", creator_developer_id=d.id, status="active", enforcement_status="active")
    s.add(a)
    await s.flush()
    if bond:
        s.add(ReputationBond(id=f"rb-{uuid.uuid4().hex[:16]}", agent_did=a.did, amount=250,
                             locked_at=NOW - dt.timedelta(days=1), status="locked", funded_by="self"))
        await s.flush()
    return d, a


EVIDENCE = [{"type": "commit", "ref": "a1b2c3d4", "url": "https://git.example/commit/a1b2c3d4"}]


async def test_a_season_from_opening_to_payment(session, monkeypatch):
    from agentvault_registry.services import commons as c
    from agentvault_registry.services import reward_funding
    s = session
    ana, ana_a = await _member(s, "ana")
    ben, ben_a = await _member(s, "ben")
    cy, cy_a = await _member(s, "cy")
    dee, dee_a = await _member(s, "dee", bond=False)        # not a member: may submit, may not ballot
    admin, _ = await _member(s, "admin", bond=False)
    await s.commit()

    async def fake_balance():
        return Decimal("2000")
    monkeypatch.setattr(c, "fee_collector_balance", fake_balance)
    events = []   # the audit events are recorded, not sent: no store is reachable from a unit test
    monkeypatch.setattr(c, "_emit", lambda event_type, season_id, data, key: events.append((event_type, key)))
    season = await c.open_season(s, admin_id=admin.id, title="October", ends_at=NOW + dt.timedelta(days=30),
                                 seed=Decimal("100"))
    assert season.budget == Decimal("1100"), "50 % of the fee collector's 2000 plus the 100 seed"
    with pytest.raises(c.CommonsRefusal) as e:
        await c.open_season(s, admin_id=admin.id, title="again", ends_at=NOW + dt.timedelta(days=30))
    assert e.value.error == "season_live"

    with pytest.raises(c.CommonsRefusal) as e:
        await c.submit(s, agent=dee_a, season_id=season.id, kind="change", title="No evidence", description="",
                       evidence=[])
    assert e.value.error == "evidence_required"
    x_dee = await c.submit(s, agent=dee_a, season_id=season.id, kind="translation", title="Polish Risk Notice",
                           description="", evidence=EVIDENCE)
    x_ana = await c.submit(s, agent=ana_a, season_id=season.id, kind="change", title="Escrow test",
                           description="", evidence=EVIDENCE)
    ids = {"dee": str(x_dee.id), "ana": str(x_ana.id)}

    with pytest.raises(c.CommonsRefusal) as e:
        await c.validate_ballot(s, agent=dee_a, season_id=season.id, allocations={ids["ana"]: 10})
    assert e.value.status_code == 403 and e.value.error == "not_a_member"
    with pytest.raises(c.CommonsRefusal) as e:
        await c.validate_ballot(s, agent=ana_a, season_id=season.id, allocations={ids["ana"]: 10})
    assert e.value.error == "own_submission"
    with pytest.raises(c.CommonsRefusal) as e:
        await c.validate_ballot(s, agent=ben_a, season_id=season.id, allocations={ids["ana"]: 70, ids["dee"]: 40})
    assert e.value.error == "too_many_points"

    for agent, alloc in ((ben_a, {ids["dee"]: 60, ids["ana"]: 40}), (cy_a, {ids["dee"]: 50, ids["ana"]: 50}),
                         (ana_a, {ids["dee"]: 100})):
        season_row, clean, total, dev_id = await c.validate_ballot(s, agent=agent, season_id=season.id,
                                                                   allocations=alloc)
        await c.store_ballot(s, season_id=season.id, developer_id=dev_id, voter_did=agent.did, allocations=clean,
                             total=total, challenge_id=None)
    # ben replaces his ballot: the replacement counts, not both
    _, clean, total, dev_id = await c.validate_ballot(s, agent=ben_a, season_id=season.id,
                                                      allocations={ids["dee"]: 50, ids["ana"]: 50})
    await c.store_ballot(s, season_id=season.id, developer_id=dev_id, voter_did=ben_a.did, allocations=clean,
                         total=total, challenge_id=None)
    assert (await s.execute(text("SELECT COUNT(*) FROM commons_ballots"))).scalar() == 3
    ben_view = await c.season_detail(s, season.id, viewer_developer_id=ben.id)
    assert ben_view["my_ballot"]["allocations"] == {ids["dee"]: 50, ids["ana"]: 50}, "the replacement is what ben sees"
    ana_view = await c.season_detail(s, season.id, viewer_developer_id=ana.id)
    assert [x["id"] for x in ana_view["submissions"] if x["mine"]] == [x_ana.id]
    assert (await c.season_detail(s, season.id))["my_ballot"] is None, "no viewer, no ballot shown"
    # the route's viewer is a DEVELOPER whichever token arrives: ben's developer token and ben's agent token agree,
    # dee (no bond) sees their own submission and is told they are not a member
    from agentvault_registry.routers import commons as commons_routes
    by_dev = await commons_routes.get_my_season_view(season_id=season.id, actor={"kind": "developer", "developer": ben},
                                                     db=s)
    by_agent = await commons_routes.get_my_season_view(season_id=season.id,
                                                       actor={"kind": "agent", "agent_did": ben_a.did, "agent": ben_a},
                                                       db=s)
    assert by_dev == by_agent and by_dev["is_member"] is True and by_dev["my_submissions"] == []
    assert by_dev["my_ballot"]["allocations"] == {ids["dee"]: 50, ids["ana"]: 50}
    dee_view = await commons_routes.get_my_season_view(season_id=season.id, actor={"kind": "developer", "developer": dee},
                                                       db=s)
    assert dee_view["is_member"] is False and dee_view["my_ballot"] is None
    assert [x["id"] for x in dee_view["my_submissions"]] == [x_dee.id]

    await c.close_season(s, admin_id=admin.id, season_id=season.id)
    detail = await c.season_detail(s, season.id)
    award = {x["id"]: x["award"] for x in detail["submissions"]}
    # dee: points 50 (ben), 50 (cy), 100 (ana) -> median 50; ana: 50 (ben), 50 (cy) -> median 50 (her own ignored)
    assert award[x_dee.id]["median_points"] == "50" and award[x_ana.id]["median_points"] == "50"
    assert Decimal(award[x_dee.id]["amount"]) == Decimal("220"), "each half of 1100, capped at 20 % = 220"
    assert detail["ballots"] is not None and len(detail["ballots"]) == 3, "ballots are published once closed"

    calls = []

    async def fake_fund(db, *, target_agent_did, amount, reason, reference_id=None, idempotency_key=None):
        calls.append({"did": target_agent_did, "amount": Decimal(str(amount)), "reason": reason,
                      "key": idempotency_key})
        return {"status": "completed", "funded_amount": str(amount), "first_transaction_id": f"tx-{len(calls)}"}
    monkeypatch.setattr(reward_funding, "fund_reward_via_waterfall", fake_fund)
    out = await c.pay_season(s, admin_id=admin.id, season_id=season.id)
    assert sorted(c_["did"] for c_ in calls) == sorted([dee_a.did, ana_a.did])
    assert all(c_["reason"] == "commons" and c_["key"] == f"commons-{season.id}-{c_['did']}" for c_ in calls)
    assert out["unpaid_awards"] == 0 and out["season"]["status"] == "paid"
    assert [e for e in events if e[0] != "CommonsAwardPaid"] == [
        ("CommonsSeasonOpened", f"commons-opened-{season.id}"), ("CommonsSeasonClosed", f"commons-closed-{season.id}")]
    assert sorted(k for t, k in events if t == "CommonsAwardPaid") == sorted(
        f"commons-paid-{season.id}-{d}" for d in (dee_a.did, ana_a.did))

    calls.clear()
    with pytest.raises(c.CommonsRefusal):
        await c.pay_season(s, admin_id=admin.id, season_id=season.id)   # a paid season is not closed any more
    assert calls == [], "nothing is paid twice"
    with pytest.raises(c.CommonsRefusal) as e:
        await c.cancel_season(s, admin_id=admin.id, season_id=season.id, reason="changed our minds")
    assert e.value.error == "season_settled"


async def test_a_failed_payment_is_re_sent_in_its_window_and_waits_for_a_person_after_it(session, monkeypatch):
    """A failed award must neither deadlock the commons (one live season at a time) nor be re-sent blind once the
    ledger has forgotten its key; and once payment starts the tally is fixed (no strike, no cancel)."""
    from agentvault_registry.services import commons as c
    from agentvault_registry.services import reward_funding
    s = session
    ana, ana_a = await _member(s, "ana")
    ben, ben_a = await _member(s, "ben")
    cy, cy_a = await _member(s, "cy")
    admin, _ = await _member(s, "admin", bond=False)
    await s.commit()

    async def no_balance():
        return None
    monkeypatch.setattr(c, "fee_collector_balance", no_balance)
    monkeypatch.setattr(c, "_emit", lambda *a, **k: None)
    monkeypatch.setenv("COMMONS_RECIPIENT_CAP_PERCENT", "100")

    async def closed_season_with_two_awards(title):
        season = await c.open_season(s, admin_id=admin.id, title=title, ends_at=NOW + dt.timedelta(days=7),
                                     seed=Decimal("200"))
        xa = await c.submit(s, agent=ana_a, season_id=season.id, kind="help", title="Answered questions",
                            description="", evidence=EVIDENCE)
        xb = await c.submit(s, agent=ben_a, season_id=season.id, kind="operations", title="Ran the canary",
                            description="", evidence=EVIDENCE)
        for agent, alloc in ((cy_a, {str(xa.id): 50, str(xb.id): 50}), (ana_a, {str(xb.id): 100}),
                             (ben_a, {str(xa.id): 100})):
            _, clean, total, dev_id = await c.validate_ballot(s, agent=agent, season_id=season.id, allocations=alloc)
            await c.store_ballot(s, season_id=season.id, developer_id=dev_id, voter_did=agent.did, allocations=clean,
                                 total=total, challenge_id=None)
        await c.close_season(s, admin_id=admin.id, season_id=season.id)
        return season, xa, xb

    calls, failing = [], {ben_a.did}

    async def flaky_fund(db, *, target_agent_did, amount, reason, reference_id=None, idempotency_key=None):
        calls.append((target_agent_did, idempotency_key))
        if target_agent_did in failing:
            raise RuntimeError("ledger unreachable")
        return {"status": "completed", "funded_amount": str(amount), "first_transaction_id": f"tx-{len(calls)}"}
    monkeypatch.setattr(reward_funding, "fund_reward_via_waterfall", flaky_fund)

    async def award_row(season_id, did):
        return (await s.execute(text(
            "SELECT id, status, error, teg_transaction_id, attempted_at FROM commons_awards "
            "WHERE season_id = :s AND recipient_did = :d"), {"s": season_id, "d": did})).mappings().one()

    season, xa, xb = await closed_season_with_two_awards("First")
    out = await c.pay_season(s, admin_id=admin.id, season_id=season.id)
    assert out["unpaid_awards"] == 1 and out["season"]["status"] == "closed" and out["needs_decision"] == []
    first_key = f"commons-{season.id}-{ben_a.did}"
    failed = await award_row(season.id, ben_a.did)
    assert failed["status"] == "failed" and failed["attempted_at"] is not None
    with pytest.raises(c.CommonsRefusal) as e:
        await c.strike(s, admin_id=admin.id, season_id=season.id, submission_id=xa.id, reason="evidence failed")
    assert e.value.error == "payment_started", "the tally is fixed once payment starts"
    with pytest.raises(c.CommonsRefusal) as e:
        await c.cancel_season(s, admin_id=admin.id, season_id=season.id, reason="start over please")
    assert e.value.error == "season_partly_paid"
    with pytest.raises(c.CommonsRefusal) as e:
        await c.write_off_award(s, admin_id=admin.id, season_id=season.id,
                                award_id=(await award_row(season.id, ana_a.did))["id"], reason="not owed after all")
    assert e.value.error == "award_not_failed", "a paid award is never written off"

    failing.clear()
    calls.clear()
    out = await c.pay_season(s, admin_id=admin.id, season_id=season.id)
    assert calls == [(ben_a.did, first_key)], "inside the window only the failed award is re-sent, under its first key"
    assert out["unpaid_awards"] == 0 and out["season"]["status"] == "paid"
    retried = await award_row(season.id, ben_a.did)
    assert retried["status"] == "paid" and retried["teg_transaction_id"] and "ledger unreachable" in retried["error"]
    assert retried["attempted_at"] == failed["attempted_at"], "the window is measured from the FIRST attempt"

    season2, _, _ = await closed_season_with_two_awards("Second")
    sid2, ana_did, ben_did, admin_id = season2.id, ana_a.did, ben_a.did, admin.id   # plain values: see expire_all
    failing.update({ana_did, ben_did})
    out = await c.pay_season(s, admin_id=admin_id, season_id=sid2)
    assert out["unpaid_awards"] == 2
    with pytest.raises(c.CommonsRefusal) as e:
        await c.cancel_season(s, admin_id=admin_id, season_id=sid2, reason="nothing was paid, was it?")
    assert e.value.error == "payment_started", "a cancel could hide a payment whose answer was lost"
    failing.discard(ana_did)
    await c.pay_season(s, admin_id=admin_id, season_id=sid2)     # ana is re-sent inside the window; ben fails again
    await s.execute(text("UPDATE commons_awards SET attempted_at = now() - interval '25 hours' "
                         "WHERE season_id = :s AND status = 'failed'"), {"s": sid2})
    await s.commit()
    s.expire_all()
    failing.clear()
    calls.clear()
    out = await c.pay_season(s, admin_id=admin_id, season_id=sid2)
    assert calls == [], "a failure older than the ledger's memory is never re-sent by a run"
    assert [d["recipient_did"] for d in out["needs_decision"]] == [ben_did] and "write the award off" in out["decision"]
    with pytest.raises(c.CommonsRefusal) as e:
        await c.open_season(s, admin_id=admin_id, title="Third", ends_at=NOW + dt.timedelta(days=7), seed=Decimal("10"))
    assert e.value.error == "season_live", "the undecided season still holds the slot"
    award, left = await c.write_off_award(s, admin_id=admin_id, season_id=sid2,
                                          award_id=out["needs_decision"][0]["award_id"],
                                          reason="checked the ledger: it never landed; paid by hand")
    assert award.status == "written_off" and left == 0 and "ledger unreachable" in award.error
    detail = await c.season_detail(s, sid2)
    assert detail["status"] == "paid"
    assert {x["award"]["status"] for x in detail["submissions"]} == {"paid", "written_off"}
    assert {x["award"]["id"]: x["award"]["status"] for x in detail["submissions"]}[award.id] == "written_off", \
        "the page carries the award id the write-off route takes"
    await c.open_season(s, admin_id=admin_id, title="Third", ends_at=NOW + dt.timedelta(days=7), seed=Decimal("10"))


async def test_strike_retallies_a_closed_season_and_cancel_before_payment(session, monkeypatch):
    from agentvault_registry.services import commons as c
    s = session
    ana, ana_a = await _member(s, "ana")
    ben, ben_a = await _member(s, "ben")
    cy, cy_a = await _member(s, "cy")
    admin, _ = await _member(s, "admin", bond=False)
    await s.commit()

    async def no_balance():
        return None
    monkeypatch.setattr(c, "fee_collector_balance", no_balance)
    monkeypatch.setattr(c, "_emit", lambda *a, **k: None)
    with pytest.raises(c.CommonsRefusal) as e:
        await c.open_season(s, admin_id=admin.id, title="x", ends_at=NOW + dt.timedelta(days=7))
    assert e.value.status_code == 503 and e.value.error == "fee_collector_unreadable"
    season = await c.open_season(s, admin_id=admin.id, title="Seeded", ends_at=NOW + dt.timedelta(days=7),
                                 seed=Decimal("300"))
    assert season.budget == Decimal("300"), "an unreadable fee collector with a seed opens on the seed alone"

    xa = await c.submit(s, agent=ana_a, season_id=season.id, kind="help", title="Answered questions",
                        description="", evidence=EVIDENCE)
    xb = await c.submit(s, agent=ben_a, season_id=season.id, kind="operations", title="Ran the canary",
                        description="", evidence=EVIDENCE)
    for agent, alloc in ((cy_a, {str(xa.id): 50, str(xb.id): 50}), (ana_a, {str(xb.id): 100}),
                         (ben_a, {str(xa.id): 100})):
        _, clean, total, dev_id = await c.validate_ballot(s, agent=agent, season_id=season.id, allocations=alloc)
        await c.store_ballot(s, season_id=season.id, developer_id=dev_id, voter_did=agent.did, allocations=clean,
                             total=total, challenge_id=None)
    monkeypatch.setenv("COMMONS_RECIPIENT_CAP_PERCENT", "100")
    await c.close_season(s, admin_id=admin.id, season_id=season.id)
    before = {a["submission_id"]: a for a in (await s.execute(text(
        "SELECT submission_id, amount FROM commons_awards WHERE season_id = :s"), {"s": season.id})).mappings()}
    assert set(before) == {xa.id, xb.id}

    await c.strike(s, admin_id=admin.id, season_id=season.id, submission_id=xb.id, reason="the canary ran itself")
    after = {a["submission_id"]: a for a in (await s.execute(text(
        "SELECT submission_id, amount FROM commons_awards WHERE season_id = :s"), {"s": season.id})).mappings()}
    assert set(after) == {xa.id}, "a struck submission loses its award when the season is tallied again"

    await c.cancel_season(s, admin_id=admin.id, season_id=season.id, reason="test season, never paid")
    assert (await s.execute(text("SELECT COUNT(*) FROM commons_awards WHERE season_id = :s"),
                            {"s": season.id})).scalar() == 0
    # a cancelled season frees the slot: a new one can open
    await c.open_season(s, admin_id=admin.id, title="Next", ends_at=NOW + dt.timedelta(days=7), seed=Decimal("10"))
