"""§MEMBERSHIP (2026-10-02) — membership and member-mode governance against a REAL Postgres.

Skipped unless MEMBERSHIP_TEST_DB names a throwaway database (the harness:
scratchpad of agentvault2-33, `membership_db_harness.sh`, or any postgresql+asyncpg URL you are willing to
WIPE: every test drops and recreates the public schema). The SQL in services/membership.py is the rule
itself, so it is tested as SQL, not through a mock.

What it holds:
  1. who is a member: self/wallet bonds count, a treasury backstop never does, nor an unverified,
     suspended, deleted or shadow developer, nor a suspended agent; the age rule and the matured knob;
  2. the weight: tenure from 1.0 to 2.0, stored as points;
  3. member-mode votes: one per developer (a second agent of the same member is refused 409), a
     non-member is refused 403 with what is missing, and the quorum is measured in members' points;
  4. the CONTROL: with the switch unset (lock mode) a non-member with a lock position still votes,
     exactly as before. The switch, not the code path, decides;
  5. a phone confirmation is bound to its proposal and choice and is spent once;
  6. an account awaiting deletion is no member (the same four statuses agent_authz reads as conveying nothing),
     and cancelling the deletion restores the original member-since;
  7. a closed proposal keeps the result it was closed with: a second tally recomputes nothing, applies no policy
     diff again and emits nothing (agentvault2-33's member gate, 2026-10-02).
  8. a decided proposal keeps the numbers it was decided on (mig 0185): its weight mode, the network's power or points,
     the quorum it needed and whether it met it, on the tally answer and on every proposal read (agentvault2-0f's ask).
"""
from __future__ import annotations

import datetime as dt
import os
import uuid

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
    for k in ("GOVERNANCE_WEIGHT_MODE", "GOVERNANCE_PRESENCE_MODE", "GOVERNANCE_MEMBER_MIN_BOND_AGE_DAYS",
              "GOVERNANCE_MEMBER_REQUIRES_MATURED_BOND", "GOVERNANCE_MEMBER_TENURE_FULL_DAYS", "NETWORK_PROFILE"):
        monkeypatch.delenv(k, raising=False)
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


async def _dev(s, name, *, verified=True, suspended=False, deleted=False, shadow=False, two_fa=False):
    from agentvault_registry.models import Developer
    d = Developer(name=name, email=f"{name}@test.local", hashed_password="x", is_verified=verified,
                  is_suspended=suspended, is_federation_shadow=shadow,
                  deleted_at=NOW if deleted else None,
                  two_fa_enabled=two_fa, totp_secret="sealed" if two_fa else None)
    s.add(d)
    await s.flush()
    return d


async def _agent(s, dev, *, status="active", enforcement="active"):
    from agentvault_registry.models import Agent
    did = f"did:theprotocol:{uuid.uuid4()}"
    a = Agent(did=did, client_id=f"cid-{uuid.uuid4().hex[:12]}", hashed_client_secret="x",
              creator_developer_id=dev.id, status=status, enforcement_status=enforcement)
    s.add(a)
    await s.flush()
    return a


async def _bond(s, agent, *, days_ago, status="locked", funded_by="self", matured_days_ago=None,
                ended_days_ago=None):
    from agentvault_registry.models import ReputationBond
    b = ReputationBond(id=f"rb-{uuid.uuid4().hex[:16]}", agent_did=agent.did, amount=250,
                       locked_at=NOW - dt.timedelta(days=days_ago), status=status, funded_by=funded_by,
                       matured_at=(NOW - dt.timedelta(days=matured_days_ago)) if matured_days_ago is not None else None,
                       released_at=(NOW - dt.timedelta(days=ended_days_ago))
                       if (ended_days_ago is not None and status == "released") else None,
                       forfeited_at=(NOW - dt.timedelta(days=ended_days_ago))
                       if (ended_days_ago is not None and status == "forfeited") else None)
    s.add(b)
    await s.flush()
    return b


async def _proposal(s, proposer_did, *, quorum=10.0, ends_in_seconds=3600):
    from agentvault_registry.models import GovernanceProposal
    p = GovernanceProposal(proposer_did=proposer_did, title="Lower the transfer fee", description="test",
                           status="VOTING", proposal_type="standard", quorum_percent=quorum, pass_percent=50.0,
                           end_timestamp=NOW + dt.timedelta(seconds=ends_in_seconds))
    s.add(p)
    await s.flush()
    return p


# ── 1 + 2: who is a member, and what the vote weighs ──────────────────────────

async def test_who_is_a_member(session, monkeypatch):
    from agentvault_registry.services import membership as m
    s = session
    alice = await _dev(s, "alice")                       # self bond, 400 days: member, full tenure
    a1 = await _agent(s, alice)
    await _bond(s, a1, days_ago=400)
    bob = await _dev(s, "bob")                           # wallet bond, 45 days: member since day 30
    await _bond(s, await _agent(s, bob), days_ago=45, funded_by="wallet")
    cara = await _dev(s, "cara")                         # bond 10 days old: not yet
    await _bond(s, await _agent(s, cara), days_ago=10)
    dan = await _dev(s, "dan")                           # treasury backstop: never
    await _bond(s, await _agent(s, dan), days_ago=400, funded_by="treasury")
    eve = await _dev(s, "eve", verified=False)           # unverified developer
    await _bond(s, await _agent(s, eve), days_ago=400)
    fay = await _dev(s, "fay", suspended=True)           # suspended developer
    await _bond(s, await _agent(s, fay), days_ago=400)
    gus = await _dev(s, "gus", shadow=True)              # a federation shadow developer
    await _bond(s, await _agent(s, gus), days_ago=400)
    hal = await _dev(s, "hal")                           # suspended agent
    await _bond(s, await _agent(s, hal, enforcement="suspended"), days_ago=400)
    ivy = await _dev(s, "ivy")                           # released bond: was a member, left 5 days ago
    await _bond(s, await _agent(s, ivy), days_ago=200, status="released", ended_days_ago=5)
    await s.commit()

    members = await m.members(s)
    assert set(members) == {alice.id, bob.id}, members
    assert abs((members[bob.id] - (NOW - dt.timedelta(days=15))).total_seconds()) < 5

    assert await m.weight_points_for(s, alice.id) == 200, "400 days a member: full tenure"
    bob_points = await m.weight_points_for(s, bob.id)
    assert 103 <= bob_points <= 105, bob_points            # 15 of 365 days
    assert await m.weight_points_for(s, cara.id) == 0
    assert await m.network_points(s) == 200 + bob_points

    st = await m.stats(s)
    assert st["members"] == 2 and st["joined_30d"] == 1 and st["left_30d"] == 1, st

    cara_status = await m.status_for_developer(s, cara)
    assert not cara_status["is_member"] and "bond_age" in cara_status["missing"]
    assert cara_status["next_step"] == "wait_until" and cara_status["next_step_at"]
    assert cara_status["next_step_text"].startswith("Your bond qualifies on")
    dan_status = await m.status_for_developer(s, dan)
    assert "bond_funded_by_treasury" in dan_status["missing"] and dan_status["next_step"] == "use_own_funds"
    nobody = await _dev(s, "nobody")
    await s.commit()
    nobody_status = await m.status_for_developer(s, nobody)
    assert nobody_status["missing"] == ["bond"] and nobody_status["next_step"] == "post_bond"
    alice_status = await m.status_for_developer(s, alice)
    assert alice_status["is_member"] and alice_status["next_step"] == "none" and alice_status["points"] == 200

    monkeypatch.setenv("GOVERNANCE_MEMBER_MIN_BOND_AGE_DAYS", "0")
    assert cara.id in await m.members(s), "the age knob (the sandbox runs 0) admits a fresh bond"
    monkeypatch.setenv("GOVERNANCE_MEMBER_REQUIRES_MATURED_BOND", "true")
    assert await m.members(s) == {}, "with the matured knob, locked bonds make nobody a member"


async def test_the_listed_bonds_are_bounded_and_the_verdict_reads_them_all(session):
    """agentvault2-09's finding: the sandbox tester's developer holds 2,907 bonds, and every vote dialog reads this
    answer. The list is bounded (qualifying first, then the soonest to qualify); the counts and the verdict are not."""
    from agentvault_registry.services import membership as m
    s = session
    bo = await _dev(s, "bo")
    for _ in range(m.AGENTS_SHOWN + 5):                  # oldest first in the table: never qualify (treasury)
        await _bond(s, await _agent(s, bo), days_ago=100, funded_by="treasury")
    young = [await _agent(s, bo) for _ in range(2)]      # qualify in 20 days
    for a in young:
        await _bond(s, a, days_ago=10)
    qualifying = [await _agent(s, bo) for _ in range(3)]
    for a in qualifying:
        await _bond(s, a, days_ago=40)
    await s.commit()
    st = await m.status_for_developer(s, bo)
    total = m.AGENTS_SHOWN + 5 + 2 + 3
    assert st["agents_total"] == total and st["agents_qualifying"] == 3
    assert len(st["agents"]) == st["agents_shown"] == m.AGENTS_SHOWN, "the list is bounded"
    assert {a["did"] for a in st["agents"][:3]} == {a.did for a in qualifying}, "qualifying bonds lead"
    assert {a["did"] for a in st["agents"][3:5]} == {a.did for a in young}, "then the ones about to qualify"
    assert all(a["funded_by"] == "treasury" for a in st["agents"][5:])
    assert st["is_member"] and st["missing"] == [] and st["points"] > 0
    assert all(a["name"] == a["did"] for a in st["agents"]), "an agent without a card is named by its DID"

    cy = await _dev(s, "cy")                             # not a member: the verdict still reads every bond
    for _ in range(m.AGENTS_SHOWN + 3):
        await _bond(s, await _agent(s, cy), days_ago=100, funded_by="treasury")
    soon = await _agent(s, cy)
    await _bond(s, soon, days_ago=25)                    # qualifies in 5 days, and is the newest row
    await s.commit()
    st = await m.status_for_developer(s, cy)
    assert not st["is_member"] and st["agents"][0]["did"] == soon.did and st["agents_total"] == m.AGENTS_SHOWN + 4
    assert st["next_step"] == "wait_until" and st["next_step_at"] == st["agents"][0]["qualifies_at"]
    assert {"bond_age", "bond_funded_by_treasury"} <= set(st["missing"])


# ── 3 + 4: member-mode votes, and the lock-mode control ───────────────────────

async def test_member_votes_one_per_developer_and_the_quorum_in_points(session, monkeypatch):
    from agentvault_registry.crud import crud_governance as cg
    s = session
    alice = await _dev(s, "alice")
    a1, a2 = await _agent(s, alice), await _agent(s, alice)
    await _bond(s, a1, days_ago=400)
    bob = await _dev(s, "bob")
    b1 = await _agent(s, bob)
    await _bond(s, b1, days_ago=30)
    outsider = await _dev(s, "outsider")
    o1 = await _agent(s, outsider)
    p = await _proposal(s, a1.did, quorum=60.0, ends_in_seconds=3600)
    await s.commit()
    # plain values: a rollback below expires every ORM object, and an expired attribute cannot load lazily here
    a1_did, a2_did, o1_did, p_id = a1.did, a2.did, o1.did, p.id

    monkeypatch.setenv("GOVERNANCE_WEIGHT_MODE", "member")
    v = await cg.cast_vote(s, p_id, a1_did, True, None)
    assert int(v.voting_power) == 200
    with pytest.raises(cg.GovernanceRefusal) as e:
        await cg.cast_vote(s, p_id, a2_did, False, None)
    assert e.value.status_code == 409 and e.value.error == "developer_already_voted"
    await s.rollback()
    with pytest.raises(cg.GovernanceRefusal) as e:
        await cg.cast_vote(s, p_id, o1_did, True, None)
    assert e.value.status_code == 403 and e.value.error == "not_a_member" and "bond" in e.value.extra["missing"]
    await s.rollback()

    # tally: 200 of 300 network points voted = 66.7 % >= 60 % quorum, all FOR -> PASSED
    await s.execute(text("UPDATE governance_proposals SET end_timestamp = now() - interval '1 second' WHERE id = :i"),
                    {"i": p_id})
    await s.commit()
    s.expire_all()
    result = await cg.tally_votes(s, p_id)
    assert result["status"] == "PASSED" and result["quorum_met"] is True, result

    # the same votes against a 70 % quorum fail: the denominator really is the members' points
    p2 = await _proposal(s, a1_did, quorum=70.0)
    await s.commit()
    p2_id = p2.id
    await cg.cast_vote(s, p2_id, a1_did, True, None)
    await s.execute(text("UPDATE governance_proposals SET end_timestamp = now() - interval '1 second' WHERE id = :i"),
                    {"i": p2_id})
    await s.commit()
    s.expire_all()  # the raw UPDATE moved the deadline under the identity map; read the row again
    r2 = await cg.tally_votes(s, p2_id)
    assert r2["status"] == "FAILED" and r2["quorum_met"] is False, r2


async def test_lock_mode_is_unchanged(session):
    """CONTROL: no switch set. A non-member with a lock position votes with veToken power, as before."""
    from agentvault_registry.crud import crud_governance as cg
    from agentvault_registry.models import Stake
    s = session
    dev = await _dev(s, "locker")
    a = await _agent(s, dev)
    s.add(Stake(id=f"st-{uuid.uuid4().hex[:12]}", agent_id=a.id, agent_did=a.did, amount=400,
                staked_at=NOW, is_active=True, lock_period_days=365))
    p = await _proposal(s, a.did)
    await s.commit()
    v = await cg.cast_vote(s, p.id, a.did, True, None)
    assert int(v.voting_power) == 20, "sqrt(400) x 365/365 = 20: the veToken weight, untouched"


# ── 5: the phone confirmation is bound and single-use ─────────────────────────

async def test_presence_modes_and_binding(session, monkeypatch):
    from agentvault_registry.services import governance_presence as gp
    s = session
    plain = await _dev(s, "plain")
    secured = await _dev(s, "secured", two_fa=True)
    await s.commit()
    facts = gp.vote_facts(proposal_id=7, title="Lower the fee", in_favor=True, points=137)
    assert facts["choice"] == "for" and facts["weight"] == "1.37" and facts["proposal_id"] == 7
    assert facts["proposal_title"] == "Lower the fee" and facts["kind"] == "governance.vote"
    ref_for, ref_against = gp.vote_action_ref(7, True), gp.vote_action_ref(7, False)

    monkeypatch.setenv("GOVERNANCE_PRESENCE_MODE", "off")
    assert (await gp.require_presence(s, secured, action_type="governance.vote", action_ref=ref_for,
                                      facts=facts))[0] is True

    monkeypatch.setenv("GOVERNANCE_PRESENCE_MODE", "conditional")
    ok, code, body = await gp.require_presence(s, plain, action_type="governance.vote", action_ref=ref_for,
                                               facts=facts)
    assert ok is True, "conditional: a member without a factor votes as before"
    ok, code, body = await gp.require_presence(s, secured, action_type="governance.vote", action_ref=ref_for,
                                               facts=facts)
    assert ok is False and code == 428 and body["error"] == "step_up_required"
    chid = body["step_up"]["challenge_id"]
    await s.commit()
    await s.execute(text("UPDATE liability_challenges SET status = 'approved' WHERE id = :c"), {"c": chid})
    await s.commit()
    ok, code, body = await gp.require_presence(s, secured, action_type="governance.vote", action_ref=ref_against,
                                               facts=facts, challenge_id=chid)
    assert ok is False and code == 428, "an approval for FOR cannot be spent on AGAINST"
    await s.commit()
    ok, code, body = await gp.require_presence(s, secured, action_type="governance.vote", action_ref=ref_for,
                                               facts=facts, challenge_id=chid)
    assert ok is True, "the approved challenge confirms exactly the vote it was minted for"
    await s.commit()
    ok, code, body = await gp.require_presence(s, secured, action_type="governance.vote", action_ref=ref_for,
                                               facts=facts, challenge_id=chid)
    assert ok is False and code == 428, "an approval is spent once"
    await s.commit()

    monkeypatch.setenv("GOVERNANCE_PRESENCE_MODE", "required")
    ok, code, body = await gp.require_presence(s, plain, action_type="governance.vote", action_ref=ref_for,
                                               facts=facts)
    assert ok is False and code == 403 and body["error"] == "second_factor_required"


# ── 6: an account awaiting deletion is no member (agentvault2-0f's finding, 2026-10-02) ───────────────────────────

async def test_an_account_awaiting_deletion_is_no_member_until_it_cancels(session, monkeypatch):
    from agentvault_registry.crud import crud_governance as cg
    from agentvault_registry.models import Developer
    from agentvault_registry.services import membership as m
    s = session
    ann = await _dev(s, "ann")
    a1 = await _agent(s, ann)
    await _bond(s, a1, days_ago=400)
    ben = await _dev(s, "ben")
    await _bond(s, await _agent(s, ben), days_ago=400)
    p = await _proposal(s, a1.did)
    await s.commit()
    ann_id, a1_did, p_id = ann.id, a1.did, p.id
    before, points_before = await m.members(s), await m.network_points(s)
    st = await m.status_for_developer(s, ann)
    assert ann_id in before and st["is_member"] and st["points"] > 0
    pts = st["points"]

    await s.execute(text("UPDATE developers SET deletion_status = 'pending_deletion' WHERE id = :i"), {"i": ann_id})
    await s.commit()
    s.expire_all()
    ann = await s.get(Developer, ann_id)
    assert ann_id not in await m.members(s), "the member count drops the account"
    assert await m.network_points(s) == points_before - pts, "and so does the quorum denominator"
    st = await m.status_for_developer(s, ann)
    assert not st["is_member"] and "deletion_pending" in st["missing"] and st["next_step"] == "cancel_deletion", st
    monkeypatch.setenv("GOVERNANCE_WEIGHT_MODE", "member")
    with pytest.raises(cg.GovernanceRefusal) as e:
        await cg.cast_vote(s, p_id, a1_did, True, None)
    assert e.value.status_code == 403 and e.value.error == "not_a_member" and "deletion_pending" in e.value.extra["missing"]
    await s.rollback()

    await s.execute(text("UPDATE developers SET deletion_status = NULL WHERE id = :i"), {"i": ann_id})
    await s.commit()
    s.expire_all()
    assert (await m.members(s))[ann_id] == before[ann_id], "cancelling restores the original member-since"
    assert await m.network_points(s) == points_before


async def test_the_deletion_rule_is_the_one_authz_uses(session):
    """agent_authz._dev_principal_live and membership must agree on every deletion status: one object, one answer."""
    from agentvault_registry import agent_authz
    from agentvault_registry.services import membership as m
    s = session
    cases = (None, "", "pending", "pending_deletion", "deleted", "anonymized", "PENDING_DELETION", "cancelled", "active")
    ids = {}
    for i, status in enumerate(cases):
        d = await _dev(s, f"del{i}")
        await _bond(s, await _agent(s, d), days_ago=400)
        await s.flush()
        await s.execute(text("UPDATE developers SET deletion_status = :st WHERE id = :i"), {"st": status, "i": d.id})
        ids[status] = d.id
    await s.commit()
    members = await m.members(s)
    for status, dev_id in ids.items():
        live = await agent_authz._dev_principal_live(s, f"dev:{dev_id}")
        assert live == (not m.deletion_not_live(status)) == (dev_id in members), status


# ── 7: a closed proposal keeps the result it was closed with ───────────────────────────────────────────────────

async def _close(s, p_id):
    await s.execute(text("UPDATE governance_proposals SET end_timestamp = now() - interval '1 second' WHERE id = :i"),
                    {"i": p_id})
    await s.commit()
    s.expire_all()


async def test_a_closed_proposal_answers_its_stored_result(session, monkeypatch):
    from agentvault_registry.crud import crud_governance as cg
    s = session
    monkeypatch.setenv("GOVERNANCE_WEIGHT_MODE", "member")
    agents = []
    for i in range(3):
        a = await _agent(s, await _dev(s, f"m{i}"))
        await _bond(s, a, days_ago=400)
        agents.append(a)
    p = await _proposal(s, agents[0].did, quorum=60.0)
    down = await _proposal(s, agents[0].did, quorum=10.0)
    short = await _proposal(s, agents[0].did, quorum=90.0)
    await s.commit()
    dids, p_id, down_id, short_id = [a.did for a in agents], p.id, down.id, short.id
    for did in dids[:2]:
        await cg.cast_vote(s, p_id, did, True, None)
    await cg.cast_vote(s, down_id, dids[0], False, None)
    await cg.cast_vote(s, short_id, dids[0], True, None)
    for i in (p_id, down_id, short_id):
        await _close(s, i)
    first = await cg.tally_votes(s, p_id)
    assert first["status"] == "PASSED" and first["quorum_met"] is True and not first.get("already_tallied"), first

    # the network doubles after the close; re-computed today, 2 of 6 members would be under the 60 % quorum
    for i in range(3):
        await _bond(s, await _agent(s, await _dev(s, f"late{i}")), days_ago=400)
    await s.commit()
    s.expire_all()
    again = await cg.tally_votes(s, p_id)
    assert again["status"] == "PASSED", "re-computed against today's network, the old tally flipped it to FAILED"
    assert again.get("already_tallied") is True and again["quorum_met"] is True, again
    assert again["votes_for"] == first["votes_for"] and again["pass_rate"] == first["pass_rate"]
    assert (await s.execute(text("SELECT status FROM governance_proposals WHERE id = :i"), {"i": p_id})).scalar() == "PASSED"

    assert (await cg.tally_votes(s, down_id))["status"] == "FAILED"
    assert (await cg.tally_votes(s, down_id))["quorum_met"] is True, "the record (mig 0185): quorum met, the members voted it down"
    # a proposal tallied before the record existed: the stored status decides, and a voted-down FAILED cannot say
    await s.execute(text("UPDATE governance_proposals SET tally_quorum_met = NULL WHERE id = :i"), {"i": down_id})
    await s.commit()
    s.expire_all()
    assert (await cg.tally_votes(s, down_id))["quorum_met"] is None, "voted down: the stored FAILED did not turn on the quorum"
    assert (await cg.tally_votes(s, short_id))["quorum_met"] is False
    assert (await cg.tally_votes(s, short_id))["quorum_met"] is False, "a FAILED with its majority there failed on the quorum"


async def test_a_passed_policy_change_is_applied_once(session, monkeypatch):
    """The old re-tally merged the OLD diff onto the current policy: it reverted any amendment adopted after it."""
    from agentvault_registry import event_emitter as ee
    from agentvault_registry.crud import crud_governance as cg
    from agentvault_registry.crud.crud_enforcement import get_active_policy, update_policy
    from agentvault_registry.models import GovernanceProposal
    received = []

    class _Recorder:
        async def emit_event(self, **kw):
            received.append(kw.get("event_type"))
            return True
    monkeypatch.setattr(ee, "get_event_emitter", lambda: _Recorder())
    monkeypatch.setenv("GOVERNANCE_WEIGHT_MODE", "member")
    s = session
    a = await _agent(s, await _dev(s, "pol"))
    await _bond(s, a, days_ago=400)
    p = GovernanceProposal(proposer_did=a.did, title="Raise the quorum", description="test", status="VOTING",
                           proposal_type="policy_change", quorum_percent=10.0, pass_percent=50.0,
                           policy_diff={"governance": {"standard_quorum_percent": 15}},
                           end_timestamp=NOW + dt.timedelta(hours=1))
    s.add(p)
    await s.commit()
    a_did, p_id = a.did, p.id
    await cg.cast_vote(s, p_id, a_did, True, None)
    await _close(s, p_id)
    first = await cg.tally_votes(s, p_id)
    assert first["status"] == "PASSED" and first["policy_applied"] is True, first
    assert received == ["GovernancePolicyChangeApplied"]
    later = await update_policy(s, new_policy_json={"governance": {"standard_quorum_percent": 10}}, modified_by="later")
    await s.commit()
    version = later.version

    again = await cg.tally_votes(s, p_id)
    active = await get_active_policy(s)
    # measured on the old code: version 2 -> 3 and the quorum back at 15, the later amendment undone
    assert active.version == version and active.policy_json["governance"]["standard_quorum_percent"] == 10, \
        "the later amendment stands; the old diff was not merged again"
    assert received == ["GovernancePolicyChangeApplied"], "nothing emitted again"
    assert again.get("already_tallied") is True and again["policy_applied"] is None


async def test_the_route_counts_and_emits_only_a_real_tally(session, monkeypatch):
    from agentvault_registry.crud import crud_governance as cg
    from agentvault_registry.models import Agent
    from agentvault_registry.routers import governance as gr
    received = []

    class _Recorder:
        def emit_background(self, **kw):
            received.append(kw.get("event_type"))
    monkeypatch.setattr(gr, "get_event_emitter", lambda: _Recorder())
    monkeypatch.setenv("GOVERNANCE_WEIGHT_MODE", "member")
    s = session
    a = await _agent(s, await _dev(s, "route"))
    await _bond(s, a, days_ago=400)
    p = await _proposal(s, a.did)
    await s.commit()
    a_id, a_did, p_id = a.id, a.did, p.id
    await cg.cast_vote(s, p_id, a_did, True, None)
    await _close(s, p_id)
    agent = await s.get(Agent, a_id)
    r1 = await gr.tally_proposal_votes(proposal_id=p_id, db=s, current_agent=agent)
    assert r1.status == "PASSED" and r1.already_tallied is False, r1
    assert received == ["ProposalTallied"], received
    r2 = await gr.tally_proposal_votes(proposal_id=p_id, db=s, current_agent=agent)
    assert r2.status == "PASSED" and r2.already_tallied is True and r2.quorum_met is True
    assert received == ["ProposalTallied"], "a closed proposal answers without a second ProposalTallied"


# ── 8: a decided proposal keeps the numbers it was decided on (mig 0185) ──────────────────────────────────────────

async def test_a_tally_records_the_numbers_it_decided_on(session, monkeypatch):
    from agentvault_registry.crud import crud_governance as cg
    from agentvault_registry.models import GovernanceProposal
    from agentvault_registry.services import membership as m
    s = session
    monkeypatch.setenv("GOVERNANCE_WEIGHT_MODE", "member")
    agents = []
    for i in range(3):
        a = await _agent(s, await _dev(s, f"r{i}"))
        await _bond(s, a, days_ago=400)
        agents.append(a)
    p = await _proposal(s, agents[0].did, quorum=60.0)
    await s.commit()
    dids, p_id = [a.did for a in agents], p.id
    for did in dids[:2]:
        await cg.cast_vote(s, p_id, did, True, None)
    await _close(s, p_id)
    points = await m.network_points(s)
    first = await cg.tally_votes(s, p_id)
    assert first["tally_weight_mode"] == "member" and first["tally_network_power"] == points
    assert first["tally_quorum_required"] == points * 0.6 and first["tally_quorum_met"] is True and first["tallied_at"]

    # the network doubles; the decided numbers do not move, on the closed tally and on the proposal read
    for i in range(3):
        await _bond(s, await _agent(s, await _dev(s, f"late{i}")), days_ago=400)
    await s.commit()
    s.expire_all()
    assert await m.network_points(s) == 2 * points
    again = await cg.tally_votes(s, p_id)
    assert again["already_tallied"] is True and again["tally_network_power"] == points and again["quorum_met"] is True
    row = await s.get(GovernanceProposal, p_id)
    assert (row.tally_weight_mode, row.tally_network_power, row.tally_quorum_met) == ("member", points, True)

    # an open proposal carries no record
    open_p = await _proposal(s, dids[0])
    await s.commit()
    assert cg.tally_record(open_p) == dict.fromkeys(cg.TALLY_RECORD_FIELDS)


async def test_a_lock_mode_tally_records_its_own_unit(session):
    from agentvault_registry.crud import crud_governance as cg
    s = session
    a = await _agent(s, await _dev(s, "lockrec"))
    p = await _proposal(s, a.did)
    await s.commit()
    p_id = p.id
    await _close(s, p_id)
    out = await cg.tally_votes(s, p_id)
    assert out["tally_weight_mode"] == "lock" and out["tally_quorum_met"] is True and out["tallied_at"], out


async def test_the_proposal_reads_carry_the_record(session, monkeypatch):
    from agentvault_registry.crud import crud_governance as cg
    from agentvault_registry.routers import governance as gr
    s = session
    monkeypatch.setenv("GOVERNANCE_WEIGHT_MODE", "member")
    a = await _agent(s, await _dev(s, "reader"))
    await _bond(s, a, days_ago=400)
    p = await _proposal(s, a.did)
    await s.commit()
    a_did, p_id = a.did, p.id
    await cg.cast_vote(s, p_id, a_did, True, None)
    await _close(s, p_id)
    await cg.tally_votes(s, p_id)
    s.expire_all()
    one = await gr.get_proposal(proposal_id=p_id, db=s)
    assert one.tally_weight_mode == "member" and one.tally_quorum_met is True and one.tally_network_power > 0, one
    listed = [x for x in await gr.list_active_proposals(db=s, include_closed=True, limit=50, offset=0) if x.id == p_id]
    assert listed and listed[0].tally_quorum_required == one.tally_quorum_required and listed[0].tallied_at is not None

