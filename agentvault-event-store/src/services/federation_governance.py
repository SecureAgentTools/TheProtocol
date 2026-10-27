"""Federation governance service — CRUD for cross-registry proposals."""
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sql_func, distinct
from ..models.federation_governance import FederationProposal, FederationVote
from ..models.federation_operator import FederationOperator
from ..es_auth import voter_trust_weight
import uuid
import logging

logger = logging.getLogger(__name__)

VETO_WINDOW_DAYS = 7

# §MEMBERSHIP D2 (2026-10-02): federal ballots. A ballot proposal passes when at least two thirds of the for-and-against
# ballots are for, at least half the eligible registries cast a ballot (abstain counts as cast), and at least
# min_registries ballots were counted. Only ballots from registries still eligible at the tally count.
BALLOT_PASS_NUM, BALLOT_PASS_DEN = 2, 3
BALLOT_CHOICES = ("for", "against", "abstain")


def ballot_outcome(ballots: List[Dict], eligible: List[str], min_registries: Optional[int]) -> Dict:
    """The ballot rule, pure. `ballots` = [{registry_id, choice}]; `eligible` = the registry ids eligible now."""
    eligible_ids = sorted(set(eligible or []))
    counted = [b for b in ballots if b["registry_id"] in eligible_ids]
    n_for = sum(1 for b in counted if b["choice"] == "for")
    n_against = sum(1 for b in counted if b["choice"] == "against")
    n_abstain = sum(1 for b in counted if b["choice"] == "abstain")
    cast, decided = len(counted), n_for + n_against
    participation_met = bool(eligible_ids) and cast * 2 >= len(eligible_ids)
    multi_met = cast >= max(1, int(min_registries or 1))
    two_thirds_met = decided > 0 and n_for * BALLOT_PASS_DEN >= decided * BALLOT_PASS_NUM
    return {
        "status": "PASSED" if (participation_met and multi_met and two_thirds_met) else "FAILED",
        "for": n_for, "against": n_against, "abstain": n_abstain, "cast": cast, "eligible": len(eligible_ids),
        "eligible_registries": eligible_ids,
        "not_counted": sorted(b["registry_id"] for b in ballots if b["registry_id"] not in eligible_ids),
        "participation_met": participation_met, "multi_registry_met": multi_met, "two_thirds_met": two_thirds_met,
        "pass_rate": round(n_for / decided * 100.0, 2) if decided else 0.0,
    }


async def create_federation_proposal(
    db: AsyncSession,
    title: str,
    description: str,
    policy_diff: Optional[dict],
    origin_registry_id: str,
    origin_proposal_id: Optional[int],
    origin_tally: Optional[dict],
    proposer_operator_name: str,
    duration_seconds: int = 604800,  # 7 days
    ballot_mode: bool = False,
) -> FederationProposal:
    """Create a federation proposal from a passed local proposal."""
    now = datetime.now(timezone.utc)
    proposal = FederationProposal(
        id=uuid.uuid4(),
        title=title,
        description=description,
        proposal_type="federation_policy_change",
        policy_diff=policy_diff,
        status="VOTING",
        origin_registry_id=origin_registry_id,
        origin_proposal_id=origin_proposal_id,
        origin_tally=origin_tally,
        proposer_operator_name=proposer_operator_name,
        duration_seconds=duration_seconds,
        end_timestamp=now + timedelta(seconds=duration_seconds),
        ballot_mode=bool(ballot_mode),
    )
    db.add(proposal)
    await db.commit()
    await db.refresh(proposal)
    logger.info(f"[FedGov] Created federation proposal {proposal.id}: {title} (from {proposer_operator_name})")
    return proposal


async def cast_federation_vote(
    db: AsyncSession,
    proposal_id: uuid.UUID,
    voter_did: str,
    voter_registry_id: str,
    vote_in_favor: bool,
    raw_voting_power: int,
    reason: Optional[str] = None,
    *,
    auth_context: Optional[Dict],
    own_domain: Optional[str],
) -> FederationVote:
    """Cast a vote on a federation proposal with trust-weighted power: the caller's own record's trust value
    (es_auth.voter_trust_weight). A caller with no active record here casts nothing (PermissionError)."""
    # Verify proposal exists and is in VOTING status
    result = await db.execute(select(FederationProposal).where(FederationProposal.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise ValueError("Federation proposal not found")
    if proposal.status != "VOTING":
        raise ValueError(f"Proposal is not in VOTING status (current: {proposal.status})")
    if datetime.now(timezone.utc) > proposal.end_timestamp:
        raise ValueError("Voting period has ended")
    if getattr(proposal, "ballot_mode", False):
        raise ValueError("this proposal is decided by registry ballots; an agent's vote does not count here")

    # SF-5B, SEC-20: the vote weighs by the trust value of the caller's own record, the value this frame's registry
    # derived (es_auth.voter_trust_weight); a caller with no active record here casts nothing (2026-10-17, his word:
    # "record must exist first").
    rows = (await db.execute(select(
        FederationOperator.id, FederationOperator.spiffe_id, FederationOperator.operator_name,
        FederationOperator.status, FederationOperator.bayesian_discount,
    ))).fetchall()
    trust_weight = voter_trust_weight(rows, auth_context, own_domain)
    if trust_weight is None:
        raise PermissionError("This store holds no active federation operator record for the registry submitting this "
                              "vote; a vote counts only from a registry whose record is here")
    logger.info(f"[FedGov] Trust weight for {voter_registry_id}: {trust_weight:.4f}")

    weighted_power = max(1, int(round(raw_voting_power * trust_weight)))

    vote = FederationVote(
        id=uuid.uuid4(),
        proposal_id=proposal_id,
        voter_did=voter_did,
        voter_registry_id=voter_registry_id,
        vote_in_favor=vote_in_favor,
        voting_power=weighted_power,
        raw_voting_power=raw_voting_power,
        reason=reason,
    )
    db.add(vote)
    await db.commit()
    await db.refresh(vote)
    logger.info(f"[FedGov] Vote on {proposal_id}: {voter_did} from {voter_registry_id} → {'FOR' if vote_in_favor else 'AGAINST'} (power={weighted_power})")
    return vote


async def cast_registry_ballot(
    db: AsyncSession,
    proposal_id: uuid.UUID,
    *,
    registry_id: str,
    choice: str,
    ballot_jws: str,
    basis: Optional[dict] = None,
    eligibility: Optional[dict] = None,
) -> FederationVote:
    """§MEMBERSHIP D2: record ONE registry's ballot (weight 1). The host registry verified it before writing it here."""
    if choice not in BALLOT_CHOICES:
        raise ValueError("choice must be for, against or abstain")
    if not registry_id.startswith("registry:") or "/" not in registry_id:
        raise ValueError("a ballot's registry id is registry:<trust domain>/<name>")
    result = await db.execute(select(FederationProposal).where(FederationProposal.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise ValueError("Federation proposal not found")
    if not getattr(proposal, "ballot_mode", False):
        raise ValueError("this proposal is decided by agents' votes, not registry ballots")
    if proposal.status != "VOTING":
        raise ValueError(f"Proposal is not in VOTING status (current: {proposal.status})")
    if datetime.now(timezone.utc) > proposal.end_timestamp:
        raise ValueError("Voting period has ended")
    vote = FederationVote(
        id=uuid.uuid4(), proposal_id=proposal_id, voter_did=registry_id, voter_registry_id=registry_id,
        vote_in_favor=(choice == "for"), voting_power=1, raw_voting_power=1, reason=None,
        choice=choice, ballot_jws=ballot_jws, ballot_basis=basis, eligibility=eligibility,
    )
    db.add(vote)
    await db.commit()
    await db.refresh(vote)
    logger.info(f"[FedGov] Ballot on {proposal_id}: {registry_id} -> {choice}")
    return vote


async def list_registry_ballots(db: AsyncSession, proposal_id: uuid.UUID) -> List[Dict]:
    rows = (await db.execute(
        select(FederationVote).where(FederationVote.proposal_id == proposal_id, FederationVote.choice.isnot(None))
        .order_by(FederationVote.created_at))).scalars().all()
    return [{"registry_id": v.voter_registry_id, "choice": v.choice, "basis": v.ballot_basis,
             "eligibility": v.eligibility, "ballot_jws": v.ballot_jws,
             "cast_at": v.created_at.isoformat() if v.created_at else None} for v in rows]


async def tally_federation_proposal(
    db: AsyncSession,
    proposal_id: uuid.UUID,
    eligible_registries: Optional[List[str]] = None,
) -> Dict:
    """Tally votes for a federation proposal. Checks multi-registry quorum.

    §MEMBERSHIP D2: a ballot proposal is tallied by ballot_outcome, with the eligible registries the host registry
    passes in (it alone knows the licences and the track records); without them it refuses rather than guess."""
    result = await db.execute(select(FederationProposal).where(FederationProposal.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise ValueError("Federation proposal not found")
    if proposal.status != "VOTING":
        raise ValueError(f"Proposal already tallied (status: {proposal.status})")
    if getattr(proposal, "ballot_mode", False):
        if eligible_registries is None:
            raise ValueError("a ballot proposal is tallied with the eligible registries (the host registry computes them)")
        ballots = (await db.execute(
            select(FederationVote).where(FederationVote.proposal_id == proposal_id, FederationVote.choice.isnot(None))
        )).scalars().all()
        out = ballot_outcome([{"registry_id": v.voter_registry_id, "choice": v.choice} for v in ballots],
                             eligible_registries, proposal.min_registries)
        now = datetime.now(timezone.utc)
        proposal.status = out["status"]
        if out["status"] == "PASSED":
            proposal.veto_deadline = now + timedelta(days=VETO_WINDOW_DAYS)
        proposal.tallied_at = now
        proposal.votes_for, proposal.votes_against = out["for"], out["against"]
        proposal.total_voters = proposal.distinct_registries = out["cast"]
        proposal.pass_rate = out["pass_rate"]
        proposal.quorum_met = out["participation_met"] and out["multi_registry_met"]
        proposal.ballot_summary = out
        await db.commit()
        logger.info(f"[FedGov] Ballot tally {proposal_id}: {out['status']} (for={out['for']}, against={out['against']}, "
                    f"abstain={out['abstain']}, cast={out['cast']}/{out['eligible']})")
        return {"proposal_id": str(proposal.id), "title": proposal.title, "ballot_mode": True, **out,
                "quorum_met": proposal.quorum_met,
                "veto_deadline": proposal.veto_deadline.isoformat() if proposal.veto_deadline else None}

    # Get all votes
    votes_result = await db.execute(
        select(FederationVote).where(FederationVote.proposal_id == proposal_id)
    )
    votes = votes_result.scalars().all()

    # Calculate totals
    votes_for = sum(v.voting_power for v in votes if v.vote_in_favor)
    votes_against = sum(v.voting_power for v in votes if not v.vote_in_favor)
    total_power = votes_for + votes_against
    total_voters = len(votes)

    # Count distinct registries
    registry_ids = set(v.voter_registry_id for v in votes)
    distinct_registries = len(registry_ids)

    # Calculate pass rate
    pass_rate = (votes_for / total_power * 100.0) if total_power > 0 else 0.0

    # GV3 (2026-07-24): WEIGHT-BASED quorum. Baseline = this frame's total
    # staked power from materialized_balances (the projection the supply audit
    # trusts), overridable via FEDGOV_NETWORK_POWER_BASELINE. Participating
    # voting power must reach quorum_percent of the baseline. If no baseline
    # resolves (empty projection, query error) the legacy ≥3-voters floor
    # applies so tallies never brick.
    import os as _os
    from sqlalchemy import text as _text
    baseline = 0.0
    try:
        baseline = float(_os.getenv("FEDGOV_NETWORK_POWER_BASELINE", "0") or 0)
    except ValueError:
        baseline = 0.0
    if baseline <= 0:
        try:
            baseline = float((await db.execute(_text(
                "SELECT COALESCE(SUM(staked_balance), 0) FROM materialized_balances"
            ))).scalar() or 0)
        except Exception as _qb_err:
            logger.warning(f"[FedGov] quorum baseline query failed: {_qb_err}")
            baseline = 0.0
    if baseline > 0:
        required_power = baseline * float(proposal.quorum_percent or 20.0) / 100.0
        quorum_met = float(total_power) >= required_power
    else:
        required_power = None
        quorum_met = total_power > 0 and total_voters >= 3  # legacy floor

    # Check multi-registry requirement
    multi_registry_met = distinct_registries >= proposal.min_registries

    # Determine outcome
    now = datetime.now(timezone.utc)
    if not quorum_met or not multi_registry_met:
        proposal.status = "FAILED"
    elif pass_rate >= proposal.pass_percent:
        proposal.status = "PASSED"
        proposal.veto_deadline = now + timedelta(days=VETO_WINDOW_DAYS)
    else:
        proposal.status = "FAILED"

    proposal.tallied_at = now
    proposal.votes_for = votes_for
    proposal.votes_against = votes_against
    proposal.total_voters = total_voters
    proposal.distinct_registries = distinct_registries
    proposal.pass_rate = round(pass_rate, 2)
    proposal.quorum_met = quorum_met and multi_registry_met

    await db.commit()

    tally_result = {
        "proposal_id": str(proposal.id),
        "title": proposal.title,
        "votes_for": votes_for,
        "votes_against": votes_against,
        "total_voters": total_voters,
        "distinct_registries": distinct_registries,
        "pass_rate": round(pass_rate, 2),
        "quorum_met": quorum_met,
        "multi_registry_met": multi_registry_met,
        "quorum_baseline_power": baseline if baseline > 0 else None,
        "quorum_required_power": required_power,
        "status": proposal.status,
        "veto_deadline": proposal.veto_deadline.isoformat() if proposal.veto_deadline else None,
    }
    logger.info(f"[FedGov] Tally {proposal_id}: {proposal.status} (for={votes_for}, against={votes_against}, registries={distinct_registries})")
    return tally_result


async def veto_federation_proposal(
    db: AsyncSession,
    proposal_id: uuid.UUID,
    vetoed_by: str,
    reason: str,
) -> FederationProposal:
    """Commander vetoes a passed federation proposal."""
    result = await db.execute(select(FederationProposal).where(FederationProposal.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise ValueError("Federation proposal not found")
    if proposal.status != "PASSED":
        raise ValueError(f"Can only veto PASSED proposals (current: {proposal.status})")

    proposal.status = "VETOED"
    proposal.vetoed_by = vetoed_by
    proposal.veto_reason = reason
    await db.commit()
    await db.refresh(proposal)
    logger.info(f"[FedGov] VETOED {proposal_id} by {vetoed_by}: {reason}")
    return proposal


async def apply_federation_proposal(
    db: AsyncSession,
    proposal_id: uuid.UUID,
) -> FederationProposal:
    """Apply a passed federation proposal (after veto window)."""
    result = await db.execute(select(FederationProposal).where(FederationProposal.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise ValueError("Federation proposal not found")
    if proposal.status != "PASSED":
        raise ValueError(f"Can only apply PASSED proposals (current: {proposal.status})")
    if proposal.veto_deadline and datetime.now(timezone.utc) < proposal.veto_deadline:
        raise ValueError("Veto window has not expired yet")

    proposal.status = "APPLIED"
    proposal.applied_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(proposal)

    # GV1 (2026-07-24): applying now APPLIES — the policy_diff rides a real
    # FederationPolicyUpdated ledger event (idempotent on the proposal id).
    # Every registry's FederationPolicyUpdatedReactor sees it on the stream and
    # triggers an immediate compliance poll; nothing changes silently anymore.
    try:
        from ..models.events import Event
        from .event_store import EventStore
        evt = Event(
            event_type="FederationPolicyUpdated",
            aggregate_id=f"federation:policy:{proposal.id}",
            aggregate_type="Federation",
            data={
                "proposal_id": str(proposal.id),
                "title": proposal.title,
                "policy_diff": proposal.policy_diff or {},
                "origin_registry_id": proposal.origin_registry_id,
                "applied_at": proposal.applied_at.isoformat(),
                "pass_rate": proposal.pass_rate,
                "distinct_registries": proposal.distinct_registries,
            },
            source_service="event-store:federation-governance",
            idempotency_key=f"fedgov-applied-{proposal.id}",
        )
        stored = await EventStore(db).append_event(evt)
        try:
            from .websocket_publisher import event_publisher
            await event_publisher.publish_event(stored)
        except Exception as ws_err:
            logger.warning(f"[FedGov] WS publish of FederationPolicyUpdated failed: {ws_err}")
    except Exception as emit_err:
        logger.error(f"[FedGov] FederationPolicyUpdated emit failed for {proposal.id}: {emit_err}")

    logger.info(f"[FedGov] APPLIED {proposal_id}: {proposal.title}")
    return proposal


async def list_federation_proposals(
    db: AsyncSession,
    status_filter: Optional[str] = None,
) -> List[Dict]:
    """List federation proposals with optional status filter."""
    query = select(FederationProposal).order_by(FederationProposal.created_at.desc())
    if status_filter:
        query = query.where(FederationProposal.status == status_filter)
    result = await db.execute(query)
    proposals = result.scalars().all()
    return [_proposal_to_dict(p) for p in proposals]


async def get_federation_proposal(
    db: AsyncSession,
    proposal_id: uuid.UUID,
) -> Optional[Dict]:
    """Get a single federation proposal with vote summary."""
    result = await db.execute(select(FederationProposal).where(FederationProposal.id == proposal_id))
    proposal = result.scalar_one_or_none()
    if not proposal:
        return None

    # Get vote summary
    votes_result = await db.execute(
        select(FederationVote).where(FederationVote.proposal_id == proposal_id)
    )
    votes = votes_result.scalars().all()

    d = _proposal_to_dict(proposal)
    d["vote_summary"] = {
        "total_voters": len(votes),
        "votes_for": sum(v.voting_power for v in votes if v.vote_in_favor),
        "votes_against": sum(v.voting_power for v in votes if not v.vote_in_favor),
        "distinct_registries": len(set(v.voter_registry_id for v in votes)),
    }
    return d


def _proposal_to_dict(p: FederationProposal) -> Dict:
    return {
        "id": str(p.id),
        "title": p.title,
        "description": p.description,
        "proposal_type": p.proposal_type,
        "policy_diff": p.policy_diff,
        "status": p.status,
        "origin_registry_id": p.origin_registry_id,
        "origin_proposal_id": p.origin_proposal_id,
        "origin_tally": p.origin_tally,
        "proposer_operator_name": p.proposer_operator_name,
        "quorum_percent": p.quorum_percent,
        "pass_percent": p.pass_percent,
        "min_registries": p.min_registries,
        "duration_seconds": p.duration_seconds,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "end_timestamp": p.end_timestamp.isoformat() if p.end_timestamp else None,
        "tallied_at": p.tallied_at.isoformat() if p.tallied_at else None,
        "veto_deadline": p.veto_deadline.isoformat() if p.veto_deadline else None,
        # a veto requires a written reason; it is served with who vetoed (None until a veto)
        "vetoed_by": p.vetoed_by,
        "veto_reason": p.veto_reason,
        "applied_at": p.applied_at.isoformat() if p.applied_at else None,
        "votes_for": p.votes_for,
        "votes_against": p.votes_against,
        "total_voters": p.total_voters,
        "distinct_registries": p.distinct_registries,
        "pass_rate": p.pass_rate,
        "quorum_met": p.quorum_met,
        "ballot_mode": bool(getattr(p, "ballot_mode", False)),
        "ballot_summary": getattr(p, "ballot_summary", None),
    }
