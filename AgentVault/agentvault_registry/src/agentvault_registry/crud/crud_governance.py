"""
CRUD operations for the Agent Senate governance system.

This module implements the business logic for managing governance proposals
and votes, including creating proposals, casting votes, and tallying results.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from ..models import GovernanceProposal, Vote, Agent, Stake
from ..services.vetoken_calculator import vetoken_calculator

# §FRAMEPOLICY (2026-09-11) — a policy_change proposal that PASSES and whose
# policy write then fails is the one governance outcome nobody can see from the
# result payload. It gets its own counter so "the rules did not change" is a
# number, not a log line in one worker.
import os as _os_for_metrics
try:
    from prometheus_client import Counter as _Counter

    GOVERNANCE_POLICY_APPLY_FAILED_TOTAL = _Counter(
        "governance_policy_apply_failed_total",
        "policy_change proposals that PASSED but whose policy document did not move",
        labelnames=["registry"],
    )
    _GOV_CRUD_PROM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _GOV_CRUD_PROM_AVAILABLE = False
    GOVERNANCE_POLICY_APPLY_FAILED_TOTAL = None  # type: ignore[assignment]


def _gov_registry_label() -> str:
    return _os_for_metrics.getenv("REGISTRY_NAME", "registry")


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Returns mutated base."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


class GovernanceRefusal(ValueError):
    """§MEMBERSHIP (2026-10-02) — a refusal that knows its own HTTP status and code word.

    The routes used to map a ValueError to a status by searching its message ("already voted" -> 409),
    which works until a sentence changes. A member-mode refusal carries its status, its code word and
    any detail the console needs (what is missing), so the answer cannot drift from its meaning.
    Subclassing ValueError keeps every existing `except ValueError` (and its substring mapping) intact.
    """

    def __init__(self, status_code: int, error: str, message: str, **extra):
        super().__init__(message)
        self.status_code = status_code
        self.error = error
        self.message = message
        self.extra = extra

    def body(self) -> dict:
        return {"error": self.error, "message": self.message, **self.extra}


async def member_vote_weight(db: AsyncSession, agent: Agent) -> int:
    """§MEMBERSHIP — the vote of the agent's DEVELOPER in points (100 = weight 1.0), or a refusal.

    Membership belongs to the developer, not to the agent: any agent of a member may cast the vote, and
    only one of them per proposal (cast_vote holds that line under a lock).
    """
    from ..services import membership as _membership
    points = await _membership.weight_points_for(db, agent.creator_developer_id)
    if points <= 0:
        from ..models import Developer
        dev = await db.get(Developer, agent.creator_developer_id)
        status = await _membership.status_for_developer(db, dev) if dev is not None else {"missing": ["developer"]}
        raise GovernanceRefusal(
            403, "not_a_member", _membership.not_a_member_sentence(),
            missing=status.get("missing", []), next_step=status.get("next_step"),
        )
    return points


async def developer_vote_on(db: AsyncSession, proposal_id: int, developer_id: int) -> Optional[str]:
    """The agent through which this developer already voted on the proposal, if any."""
    stmt = (
        select(Vote.voter_did)
        .join(Agent, Agent.did == Vote.voter_did)
        .where(and_(Vote.proposal_id == proposal_id, Agent.creator_developer_id == developer_id))
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def precheck_member_vote(db: AsyncSession, proposal_id: int, agent: Agent):
    """§MEMBERSHIP — everything that would refuse a member's vote, checked BEFORE the phone is asked.

    A step-up approval is single-use: spending it on a vote that is then refused for an unrelated reason
    (the proposal closed, the developer already voted) would make the member confirm twice for nothing.
    cast_vote repeats these checks under its lock; this is the courtesy pass. Returns (proposal, points).
    """
    proposal = (await db.execute(
        select(GovernanceProposal).where(GovernanceProposal.id == proposal_id)
    )).scalar_one_or_none()
    if not proposal:
        raise ValueError(f"Proposal {proposal_id} not found")
    if proposal.status != "VOTING":
        raise ValueError(f"Proposal {proposal_id} is not open for voting")
    if datetime.now(timezone.utc) > proposal.end_timestamp:
        raise ValueError(f"Voting period for proposal {proposal_id} has ended")
    already = await developer_vote_on(db, proposal_id, agent.creator_developer_id)
    if already:
        raise GovernanceRefusal(
            409, "developer_already_voted",
            f"developer_already_voted: your developer already voted on proposal {proposal_id} "
            f"through agent {already}; a member has one vote.",
            agent_did=already,
        )
    points = await member_vote_weight(db, agent)
    return proposal, points


async def create_proposal(
    db: AsyncSession,
    proposer_did: str,
    title: str,
    description: str,
    duration_seconds: int,
    proposal_type: str = "standard",
    policy_diff: dict = None,
    quorum_percent: float = 10.0,
    pass_percent: float = 50.0
) -> GovernanceProposal:
    """
    Create a new governance proposal.
    
    Args:
        db: Database session
        proposer_did: DID of the agent creating the proposal
        title: Short title for the proposal
        description: Detailed description of the proposal
        duration_seconds: How long the voting period should last
        proposal_type: 'standard' or 'policy_change'
        policy_diff: JSON diff for policy_change proposals
        quorum_percent: Required quorum as % of network veToken power (default 10%)
        pass_percent: Required pass threshold (default 50% = simple majority)
        
    Returns:
        The created GovernanceProposal object
    """
    # Calculate end timestamp
    end_timestamp = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
    
    # Create the proposal
    proposal = GovernanceProposal(
        proposer_did=proposer_did,
        title=title,
        description=description,
        status="VOTING",
        proposal_type=proposal_type,
        policy_diff=policy_diff,
        quorum_percent=quorum_percent,
        pass_percent=pass_percent,
        end_timestamp=end_timestamp
    )
    
    db.add(proposal)
    await db.commit()
    await db.refresh(proposal)
    
    return proposal


async def cast_vote(
    db: AsyncSession,
    proposal_id: int,
    voter_did: str,
    vote_in_favor: bool,
    reason: str = None
) -> Vote:
    """
    Cast a vote on a governance proposal.
    
    P3/D2: Uses veToken calculator for voting power instead of raw staked_balance.
    Voting power = sum of veToken power across all active positions.
    
    Args:
        db: Database session
        proposal_id: ID of the proposal being voted on
        voter_did: DID of the agent casting the vote
        vote_in_favor: True for FOR, False for AGAINST
        reason: Optional reason for the vote
        
    Returns:
        The created Vote object
        
    Raises:
        ValueError: If the proposal doesn't exist, voting has ended, or agent already voted
    """
    # Check if proposal exists and is still open for voting
    stmt = select(GovernanceProposal).where(GovernanceProposal.id == proposal_id)
    result = await db.execute(stmt)
    proposal = result.scalar_one_or_none()
    
    if not proposal:
        raise ValueError(f"Proposal {proposal_id} not found")
    
    if proposal.status != "VOTING":
        raise ValueError(f"Proposal {proposal_id} is not open for voting")
    
    if datetime.now(timezone.utc) > proposal.end_timestamp:
        raise ValueError(f"Voting period for proposal {proposal_id} has ended")
    
    # Check if agent already voted
    stmt = select(Vote).where(
        and_(Vote.proposal_id == proposal_id, Vote.voter_did == voter_did)
    )
    result = await db.execute(stmt)
    existing_vote = result.scalar_one_or_none()
    
    if existing_vote:
        raise ValueError(f"Agent {voter_did} has already voted on proposal {proposal_id}")
    
    # Get agent
    stmt = select(Agent).where(Agent.did == voter_did)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise ValueError(f"Agent {voter_did} not found")
    
    # §MEMBERSHIP (2026-10-02) — member mode: the vote is the DEVELOPER's, weighed by tenure, and there is
    # one per developer per proposal. The transaction-scoped advisory lock makes "check, then insert"
    # atomic for that developer and proposal, so two agents of one member racing each other cannot both
    # vote. Nothing below reads a balance or a stake position.
    from ..services import membership as _membership
    if _membership.member_mode():
        from sqlalchemy import text as _text
        await db.execute(_text("SELECT pg_advisory_xact_lock(hashtext(:k)::bigint)"),
                         {"k": f"gov-vote:{proposal_id}:{agent.creator_developer_id}"})
        already = await developer_vote_on(db, proposal_id, agent.creator_developer_id)
        if already:
            raise GovernanceRefusal(
                409, "developer_already_voted",
                f"developer_already_voted: your developer already voted on proposal {proposal_id} "
                f"through agent {already}; a member has one vote.",
                agent_did=already,
            )
        points = await member_vote_weight(db, agent)
        vote = Vote(
            proposal_id=proposal_id,
            voter_did=voter_did,
            vote=vote_in_favor,
            voting_power=points,
            reason=reason
        )
        db.add(vote)
        await db.commit()
        await db.refresh(vote)
        return vote

    # P3/D2: Calculate veToken voting power from all active positions
    # §FRAMEPOLICY — weigh the vote with THIS frame's declared rule.
    from ..services.frame_policy import load as _load_frame_policy
    from ..services.vetoken_calculator import VeTokenCalculator
    _calc = VeTokenCalculator.from_policy(await _load_frame_policy(db))
    ve_power = await _calc.calculate_agent_power(db, voter_did)

    if ve_power <= 0:
        raise ValueError(f"Agent {voter_did} has no voting weight")

    # ZKP Phase 3 trust-chain: agents with ≥ZKP_GOVERNANCE_BONUS_THRESHOLD_COUNT
    # verified, non-revoked attestations submitted in the last
    # ZKP_GOVERNANCE_BONUS_THRESHOLD_DAYS days earn a multiplier on their
    # voting power. Default: 10 attestations / 30 days → ×1.05.
    import os as _os
    if _os.environ.get("ZKP_PHASE_3_ENABLED", "true").lower() == "true":
        try:
            from . import attestation as crud_attestation
            try:
                threshold_count = max(1, int(_os.environ.get(
                    "ZKP_GOVERNANCE_BONUS_THRESHOLD_COUNT", "10"
                )))
            except (TypeError, ValueError):
                threshold_count = 10
            try:
                threshold_days = max(1, int(_os.environ.get(
                    "ZKP_GOVERNANCE_BONUS_THRESHOLD_DAYS", "30"
                )))
            except (TypeError, ValueError):
                threshold_days = 30
            try:
                multiplier = max(1.0, min(2.0, float(_os.environ.get(
                    "ZKP_GOVERNANCE_BONUS_MULTIPLIER", "1.05"
                ))))
            except (TypeError, ValueError):
                multiplier = 1.05
            attest_count = await crud_attestation.count_recent_verified(
                db, agent_did=voter_did, since_days=threshold_days,
            )
            if attest_count >= threshold_count and multiplier > 1.0:
                ve_power = ve_power * multiplier
        except Exception:
            # Bonus is best-effort — never block a vote on a lookup failure.
            pass

    # Store as integer (rounded) for vote weight
    voting_power_int = max(1, int(round(ve_power)))
    
    # Create the vote with veToken power
    vote = Vote(
        proposal_id=proposal_id,
        voter_did=voter_did,
        vote=vote_in_favor,
        voting_power=voting_power_int,
        reason=reason
    )
    
    db.add(vote)
    await db.commit()
    await db.refresh(vote)
    
    return vote


async def tally_votes(
    db: AsyncSession,
    proposal_id: int
) -> dict:
    """
    Tally the votes for a proposal and update its status.
    
    This function should be called after a proposal's voting period ends.
    It sums the voting power for FOR and AGAINST votes and updates the
    proposal status to PASSED or FAILED based on simple majority.
    
    Args:
        db: Database session
        proposal_id: ID of the proposal to tally
        
    Returns:
        Dictionary with vote tallies and final status
        
    Raises:
        ValueError: If the proposal doesn't exist
    """
    # Get the proposal
    stmt = select(GovernanceProposal).where(GovernanceProposal.id == proposal_id)
    result = await db.execute(stmt)
    proposal = result.scalar_one_or_none()
    
    if not proposal:
        raise ValueError(f"Proposal {proposal_id} not found")
    
    # Only tally if voting period has ended
    if datetime.now(timezone.utc) <= proposal.end_timestamp and proposal.status == "VOTING":
        raise ValueError(f"Voting period for proposal {proposal_id} has not ended yet")

    if proposal.status != "VOTING":
        # §MEMBERSHIP (2026-10-02): a closed proposal answers the result it was closed with. A second tally used to
        # recompute it against TODAY's network (in member mode, every member who joined since), so its creator could
        # flip a PASSED to FAILED; it emitted ProposalTallied again; and for a passed policy_change it merged the OLD
        # diff onto the current policy again, which reverts any amendment adopted after it.
        return await _closed_tally(db, proposal)
    
    # Calculate total voting power FOR
    stmt = select(func.sum(Vote.voting_power)).where(
        and_(Vote.proposal_id == proposal_id, Vote.vote == True)
    )
    result = await db.execute(stmt)
    votes_for = result.scalar() or 0
    
    # Calculate total voting power AGAINST
    stmt = select(func.sum(Vote.voting_power)).where(
        and_(Vote.proposal_id == proposal_id, Vote.vote == False)
    )
    result = await db.execute(stmt)
    votes_against = float(result.scalar() or 0)

    votes_for = float(votes_for)
    total_power_cast = votes_for + votes_against

    # P3/D2: Check quorum — total power cast must meet quorum_percent of network power
    quorum_met = True
    required_quorum = None
    from ..services.frame_policy import load as _load_frame_policy
    from ..services.vetoken_calculator import VeTokenCalculator
    from ..services import membership as _membership
    _frame_policy = await _load_frame_policy(db)
    if _membership.member_mode():
        # §MEMBERSHIP — the quorum is measured in the same unit as the votes: members' points.
        network_power = float(await _membership.network_points(db) or 0)
    else:
        _calc = VeTokenCalculator.from_policy(_frame_policy)
        network_power = float(await _calc.get_network_total_power(db) or 0)
    if proposal.quorum_percent and network_power > 0:
        required_quorum = network_power * (float(proposal.quorum_percent) / 100.0)
        quorum_met = total_power_cast >= required_quorum

    # P3/D2: Check pass threshold
    pass_threshold = float(proposal.pass_percent or 50.0)
    if total_power_cast > 0:
        pass_rate = (votes_for / total_power_cast) * 100.0
    else:
        pass_rate = 0.0
    
    # Determine outcome
    if not quorum_met:
        proposal.status = "FAILED"  # Quorum not reached
    elif pass_rate >= pass_threshold:
        proposal.status = "PASSED"
    else:
        proposal.status = "FAILED"
    # §MEMBERSHIP (mig 0185): the numbers this decision was made on stay with the proposal. A later read, or a second
    # tally of the closed proposal, answers these instead of today's network (which members join and leave).
    proposal.tally_weight_mode = "member" if _membership.member_mode() else "lock"
    proposal.tally_network_power = network_power
    proposal.tally_quorum_required = required_quorum
    proposal.tally_quorum_met = bool(quorum_met)
    proposal.tallied_at = datetime.now(timezone.utc)

    # §6.3: Auto-apply policy_diff when a policy_change proposal passes
    policy_applied = None          # None = not a policy_change proposal
    policy_apply_error = None
    policy_new_version = None
    if proposal.status == "PASSED" and \
            getattr(proposal, 'proposal_type', 'standard') == 'policy_change' and \
            getattr(proposal, 'policy_diff', None):
        policy_applied = False
        try:
            from ..crud.crud_enforcement import get_active_policy, update_policy, DEFAULT_POLICY_JSON
            import copy

            # §FRAMEPOLICY (2026-09-11) — merge onto what this frame has ACTUALLY
            # CHOSEN, not onto the shipped defaults.
            #
            # Measured on EU right after the first real policy_change: a proposal
            # that changed ONE value (standard_quorum_percent) persisted the
            # ENTIRE default document, so every other field then read back as
            # "this frame set it" when nobody had chosen it — and the frame
            # silently stopped inheriting any later change to a shipped default,
            # because its row now pins all of them.
            #
            # The row holds the frame's decisions; services/frame_policy.resolve()
            # merges them onto the defaults at read time. That is the whole point
            # of having a resolver, and it keeps explain()'s provenance honest.
            current_policy_row = await get_active_policy(db)
            base_json = copy.deepcopy(current_policy_row.policy_json) if current_policy_row else {}

            # Deep-merge: policy_diff values override base values at each key
            merged = _deep_merge(copy.deepcopy(base_json), proposal.policy_diff)

            new_policy = await update_policy(
                db=db,
                new_policy_json=merged,
                modified_by=f"governance_proposal_{proposal_id}",
            )
            policy_applied = True
            policy_new_version = new_policy.version
            from ..event_emitter import get_event_emitter
            emitter = get_event_emitter()
            await emitter.emit_event(
                aggregate_id="governance",
                event_type="GovernancePolicyChangeApplied",
                event_data={
                    "proposal_id": proposal_id,
                    "new_policy_version": new_policy.version,
                    "policy_diff": proposal.policy_diff,
                },
            )
        except Exception as e:
            # §FRAMEPOLICY (2026-09-11) — this handler is still non-fatal on
            # purpose (a failed write must not un-pass a vote that really
            # passed), but it used to be SILENT: the proposal reported PASSED,
            # the caller got "status": "PASSED", and the value had not moved.
            # A governance result nobody can distinguish from an applied one is
            # the §S4 class on the rail whose whole job is changing the rules.
            import logging
            logging.getLogger(__name__).error(
                f"[crud_governance] Failed to auto-apply policy_diff for proposal {proposal_id}: {e}",
                exc_info=True,
            )
            policy_apply_error = str(e)[:500]
            try:
                from ..event_emitter import get_event_emitter
                await get_event_emitter().emit_event(
                    aggregate_id="governance",
                    event_type="GovernancePolicyChangeFailed",
                    event_data={
                        "proposal_id": proposal_id,
                        "error": policy_apply_error,
                        "policy_diff": proposal.policy_diff,
                    },
                )
            except Exception:
                logging.getLogger(__name__).error(
                    "[crud_governance] could not even record the policy-apply failure "
                    f"for proposal {proposal_id}", exc_info=True)
            if _GOV_CRUD_PROM_AVAILABLE:
                GOVERNANCE_POLICY_APPLY_FAILED_TOTAL.labels(
                    registry=_gov_registry_label()).inc()

    await db.commit()
    await db.refresh(proposal)
    
    return {
        "proposal_id": proposal_id,
        "votes_for": votes_for,
        "votes_against": votes_against,
        "total_votes": total_power_cast,
        "quorum_met": quorum_met,
        "pass_rate": round(pass_rate, 2),
        "status": proposal.status,
        # §FRAMEPOLICY — a policy_change that PASSED but did not apply must be
        # distinguishable from one that did. None = not a policy_change.
        "policy_applied": policy_applied,
        "policy_new_version": policy_new_version,
        "policy_apply_error": policy_apply_error,
        # Which document judged this tally (the handover's "Senate Floor shows
        # which policy decided a tally").
        "policy_version": _frame_policy.version,
        "policy_source": _frame_policy.source,
        "quorum_percent": float(proposal.quorum_percent or 0),
        "pass_percent": pass_threshold,
        "already_tallied": False,
        **tally_record(proposal),
    }


TALLY_RECORD_FIELDS = ("tally_weight_mode", "tally_network_power", "tally_quorum_required", "tally_quorum_met",
                       "tallied_at")


def tally_record(proposal: GovernanceProposal) -> dict:
    """The tally-time record of a decided proposal (mig 0185); every value None until a real tally wrote it."""
    return {k: getattr(proposal, k, None) for k in TALLY_RECORD_FIELDS}


async def _closed_tally(db: AsyncSession, proposal: GovernanceProposal) -> dict:
    """The stored result of a closed proposal: nothing is written, applied or emitted. The vote sums are read again
    (no vote can land on a closed proposal); `quorum_met` is the one the tally recorded (mig 0185), and for a proposal
    tallied before that record existed, what the stored status implies: True for PASSED, False for a FAILED whose
    majority was there (only the quorum can have failed it), None where the outcome did not turn on it."""
    rows = (await db.execute(
        select(Vote.vote, func.sum(Vote.voting_power)).where(Vote.proposal_id == proposal.id).group_by(Vote.vote)
    )).all()
    votes_for = float(sum((p or 0) for v, p in rows if v))
    votes_against = float(sum((p or 0) for v, p in rows if not v))
    total = votes_for + votes_against
    pass_threshold = float(proposal.pass_percent or 50.0)
    pass_rate = (votes_for / total) * 100.0 if total > 0 else 0.0
    if getattr(proposal, "tally_quorum_met", None) is not None:
        quorum_met = bool(proposal.tally_quorum_met)
    elif proposal.status == "PASSED":
        quorum_met = True
    elif proposal.status == "FAILED" and total > 0 and pass_rate >= pass_threshold:
        quorum_met = False
    else:
        quorum_met = None
    return {
        "proposal_id": proposal.id,
        "votes_for": votes_for,
        "votes_against": votes_against,
        "total_votes": total,
        "quorum_met": quorum_met,
        "pass_rate": round(pass_rate, 2),
        "status": proposal.status,
        "policy_applied": None,
        "policy_new_version": None,
        "policy_apply_error": None,
        "policy_version": None,
        "policy_source": None,
        "quorum_percent": float(proposal.quorum_percent or 0),
        "pass_percent": pass_threshold,
        "already_tallied": True,
        **tally_record(proposal),
    }


async def get_proposal_with_votes(
    db: AsyncSession,
    proposal_id: int
) -> Optional[GovernanceProposal]:
    """
    Get a proposal with all its votes loaded.
    
    Args:
        db: Database session
        proposal_id: ID of the proposal
        
    Returns:
        GovernanceProposal with votes loaded, or None if not found
    """
    stmt = select(GovernanceProposal).options(
        selectinload(GovernanceProposal.votes)
    ).where(GovernanceProposal.id == proposal_id)
    
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_active_proposals(
    db: AsyncSession,
    limit: Optional[int] = None,
    offset: int = 0,
) -> List[GovernanceProposal]:
    """
    Get the proposals currently open for voting, newest first.
    
    Args:
        db: Database session
        limit: at most this many (None: all). §DOCSFIX D6-570: the listing route passes its own
        offset: skip this many           `limit` and `offset`; the open listing ignored both.
        
    Returns:
        List of active GovernanceProposal objects
    """
    stmt = select(GovernanceProposal).where(
        and_(
            GovernanceProposal.status == "VOTING",
            GovernanceProposal.end_timestamp > datetime.now(timezone.utc)
        )
    ).order_by(GovernanceProposal.created_at.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    if offset:
        stmt = stmt.offset(offset)
    
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_proposal_vote_summary(
    db: AsyncSession,
    proposal_id: int
) -> dict:
    """
    Get a summary of the current vote tally for a proposal without finalizing it.
    
    Args:
        db: Database session
        proposal_id: ID of the proposal
        
    Returns:
        Dictionary with current vote tallies
    """
    # Get the proposal
    stmt = select(GovernanceProposal).where(GovernanceProposal.id == proposal_id)
    result = await db.execute(stmt)
    proposal = result.scalar_one_or_none()
    
    if not proposal:
        raise ValueError(f"Proposal {proposal_id} not found")
    
    # Calculate current voting power FOR
    stmt = select(func.sum(Vote.voting_power)).where(
        and_(Vote.proposal_id == proposal_id, Vote.vote == True)
    )
    result = await db.execute(stmt)
    votes_for = result.scalar() or 0
    
    # Calculate current voting power AGAINST
    stmt = select(func.sum(Vote.voting_power)).where(
        and_(Vote.proposal_id == proposal_id, Vote.vote == False)
    )
    result = await db.execute(stmt)
    votes_against = result.scalar() or 0
    
    # Count unique voters
    stmt = select(func.count(Vote.id)).where(Vote.proposal_id == proposal_id)
    result = await db.execute(stmt)
    total_voters = result.scalar() or 0
    
    return {
        "proposal_id": proposal_id,
        "title": proposal.title,
        "status": proposal.status,
        "proposal_type": getattr(proposal, 'proposal_type', 'standard'),
        "votes_for": votes_for,
        "votes_against": votes_against,
        "total_voting_power": votes_for + votes_against,
        "total_voters": total_voters,
        # §BATCH0911 — the STORED quorum, the one tally_proposal applies (None: the tally applies
        # none). `or 10.0` invented a number nothing here decides by.
        "quorum_percent": getattr(proposal, 'quorum_percent', None),
        "pass_percent": getattr(proposal, 'pass_percent', 50.0) or 50.0,
        "voting_ends_at": proposal.end_timestamp.isoformat()
    }


async def get_agent_vote_on_proposal(
    db: AsyncSession,
    proposal_id: int,
    voter_did: str
) -> Optional[Vote]:
    """Check if an agent has voted on a specific proposal."""
    stmt = select(Vote).where(
        and_(Vote.proposal_id == proposal_id, Vote.voter_did == voter_did)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_proposal_votes(
    db: AsyncSession,
    proposal_id: int,
    page: int = 1,
    limit: int = 20
) -> dict:
    """Get paginated list of individual votes for a proposal."""
    offset = (page - 1) * limit
    
    # Count total
    count_stmt = select(func.count(Vote.id)).where(Vote.proposal_id == proposal_id)
    total = await db.scalar(count_stmt) or 0
    
    # Get votes
    stmt = select(Vote).where(
        Vote.proposal_id == proposal_id
    ).order_by(Vote.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    votes = result.scalars().all()
    
    return {
        "votes": votes,
        "total": total,
        "page": page,
        "limit": limit
    }
