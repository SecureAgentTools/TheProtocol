"""
API endpoints for the Agent Senate governance system.
P3/D2: Enhanced with veToken voting power, quorum, and policy_change proposals.
"""
from typing import Annotated, List, Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Path, Query, Security
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, field_validator

from ..database import get_db
from ..crud import crud_governance
from ..models import Agent, GovernanceProposal, Vote
from .utils import get_current_agent
from agentvault_registry.security import require_agent_permission  # IRONKEY
from ..event_emitter import get_event_emitter
from .. import security
from ..services.vetoken_calculator import vetoken_calculator
from sqlalchemy import select, func, distinct
from decimal import Decimal
import asyncio
import logging

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Prometheus instrumentation (added 2026-04-30 — Grafana governance dash)
# ----------------------------------------------------------------------
import os as _os_for_metrics
try:
    from prometheus_client import Counter as _Counter, Gauge as _Gauge

    GOVERNANCE_PROPOSALS_CREATED_TOTAL = _Counter(
        "governance_proposals_created_total",
        "Governance proposals created by type",
        labelnames=["proposal_type", "registry"],
    )
    GOVERNANCE_VOTES_CAST_TOTAL = _Counter(
        "governance_votes_cast_total",
        "Governance votes cast by stance",
        labelnames=["in_favor", "registry"],  # in_favor: yes|no
    )
    GOVERNANCE_TALLIES_TOTAL = _Counter(
        "governance_tallies_total",
        "Governance proposal tallies by outcome",
        labelnames=["outcome", "registry"],  # outcome: passed|failed
    )
    GOVERNANCE_PROPOSALS_ACTIVE = _Gauge(
        "governance_proposals_active",
        "Active governance proposals by status (refreshed by background task)",
        labelnames=["status", "registry"],  # status: voting|passed|failed
    )
    _GOV_PROM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _GOV_PROM_AVAILABLE = False
    GOVERNANCE_PROPOSALS_CREATED_TOTAL = None  # type: ignore[assignment]
    GOVERNANCE_VOTES_CAST_TOTAL = None  # type: ignore[assignment]
    GOVERNANCE_TALLIES_TOTAL = None  # type: ignore[assignment]
    GOVERNANCE_PROPOSALS_ACTIVE = None  # type: ignore[assignment]


def _gov_registry_label() -> str:
    return _os_for_metrics.getenv("REGISTRY_NAME", "registry")


# OWL20-PREP: Event Store integration — lazy init, not at import time


# Pydantic schemas for governance
class ProposalCreate(BaseModel):
    """Schema for creating a new governance proposal."""
    title: str = Field(..., min_length=1, max_length=200, description="Short title for the proposal")
    description: str = Field(..., min_length=1, max_length=5000, description="Detailed description of the proposal")
    duration_seconds: int = Field(..., gt=0, le=2592000, description="Voting duration in seconds (max 30 days)")
    proposal_type: str = Field(default="standard", max_length=50, description="Proposal type: 'standard' or 'policy_change'")
    policy_diff: Optional[Dict[str, Any]] = Field(default=None, description="JSON diff for policy_change proposals")

    @field_validator("title", "description")
    @classmethod
    def sanitize_text(cls, v):
        from agentvault_registry.input_validators import validate_safe_text
        return validate_safe_text(v, "proposal field")


class VoteCreate(BaseModel):
    """Schema for casting a vote on a proposal."""
    vote_in_favor: bool = Field(..., description="True for FOR, False for AGAINST")
    reason: Optional[str] = Field(default=None, max_length=1000, description="Optional reason for the vote")
    # §MEMBERSHIP (2026-10-02) — where GOVERNANCE_PRESENCE_MODE asks for it, a member's vote is confirmed
    # by its human: the same two fields, and the same meaning, as the credential reset's step-up.
    totp_code: Optional[str] = Field(
        default=None, max_length=16,
        description="Current code from your authenticator app, if you confirm the vote that way.",
    )
    challenge_id: Optional[str] = Field(
        default=None, max_length=44,
        description="Id of the step-up challenge you approved on your phone (Pocket, Approvals) for THIS vote.",
    )


def _deep_merge_dict(base: dict, override: dict) -> dict:
    """Recursively merge override into base (mutates base). Used to build the
    candidate policy document a policy_change proposal would produce, so it can
    be validated before the vote rather than after it."""
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge_dict(base[key], value)
        else:
            base[key] = value
    return base


class ProposalResponse(BaseModel):
    """Schema for proposal responses."""
    id: int
    proposer_did: str
    title: str
    description: str
    status: str
    proposal_type: str = "standard"
    quorum_percent: Optional[float] = 10.0
    pass_percent: Optional[float] = 50.0
    created_at: datetime
    end_timestamp: datetime
    votes_for: Optional[int] = 0
    votes_against: Optional[int] = 0
    total_voters: Optional[int] = 0
    # §MEMBERSHIP (mig 0185): the numbers a real tally decided on; all None until then. tally_weight_mode is the unit of
    # the two numbers ('lock' = veToken power, 'member' = members' points), recorded because a registry may switch modes.
    tally_weight_mode: Optional[str] = None
    tally_network_power: Optional[float] = None
    tally_quorum_required: Optional[float] = None
    tally_quorum_met: Optional[bool] = None
    tallied_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class VoteResponse(BaseModel):
    """Schema for vote responses."""
    id: int
    proposal_id: int
    voter_did: str
    vote: bool
    voting_power: int
    reason: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class TallyResponse(BaseModel):
    """Schema for vote tally responses.

    ⚠ §FRAMEPOLICY (2026-09-11) — a field the response_model does not declare is
    dropped SILENTLY and the endpoint still answers 200. The policy fields below
    were added to the tally payload in crud_governance and would have reached
    nobody: the Senate Floor's "which policy decided this" line would have been
    dead code and a policy_change that PASSED without applying would have gone
    on being invisible, which is the exact defect it was written to close.
    """
    proposal_id: int
    votes_for: int
    votes_against: int
    total_votes: int
    # None only on an already-tallied proposal whose stored outcome did not turn on the quorum.
    quorum_met: Optional[bool] = True
    pass_rate: float = 0.0
    status: str
    # Which document judged this tally, and under what thresholds.
    policy_version: Optional[int] = None
    policy_source: Optional[str] = None
    quorum_percent: Optional[float] = None
    pass_percent: Optional[float] = None
    # For a policy_change: did the document actually move? None = not a policy_change.
    policy_applied: Optional[bool] = None
    policy_new_version: Optional[int] = None
    policy_apply_error: Optional[str] = None
    # §MEMBERSHIP (2026-10-02): True when the proposal was already closed. The answer is its stored result; nothing
    # was recomputed, applied or emitted (crud_governance._closed_tally).
    already_tallied: bool = False
    # §MEMBERSHIP (mig 0185): the tally-time record (crud_governance.tally_record), the same five fields as the proposal.
    tally_weight_mode: Optional[str] = None
    tally_network_power: Optional[float] = None
    tally_quorum_required: Optional[float] = None
    tally_quorum_met: Optional[bool] = None
    tallied_at: Optional[datetime] = None


router = APIRouter()


@router.post("/proposals", response_model=ProposalResponse)
async def create_proposal(
    proposal: ProposalCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_agent: Annotated[Agent, Security(require_agent_permission("gov.propose"))]
) -> ProposalResponse:
    """
    Create a governance proposal in the Agent Senate; it is open for voting for `duration_seconds`. Needs an agent
    token with the `gov.propose` permission. Where the registry counts votes by membership, as on the public
    network, the agent's developer must be a member; elsewhere the agent needs locked units, at least the frame's
    minimum (`governance.min_stake_to_propose_avt`).

    A `policy_change` proposal carries a `policy_diff` and is held to the frame's higher quorum and pass percentages
    (20% and 66% by default). A diff the policy document would refuse is refused at once (400); one that would move
    a rule an environment setting decides answers 409.
    """
    # §FRAMEPOLICY (2026-09-11) — the frame declares who may propose.
    # `governance.min_stake_to_propose_avt` has been in every policy document
    # (and BOUNDED to [10, 10000] by the network) while the only check here was
    # "> 0". Measured on both roll targets before wiring it: of the agents that
    # could propose, 0 hold less than the declared 100 — so this refuses nobody
    # who can propose today, and starts refusing the case the document always
    # said it would.
    from ..services.frame_policy import load as _load_frame_policy
    from ..services import membership as _membership
    _fp = await _load_frame_policy(db)
    if _membership.member_mode():
        # §MEMBERSHIP (2026-10-02) — in member mode a MEMBER may propose; locked Units decide nothing.
        try:
            await crud_governance.member_vote_weight(db, current_agent)
        except crud_governance.GovernanceRefusal as refusal:
            return JSONResponse(status_code=refusal.status_code, content=refusal.body())
    else:
        _min_stake = float(_fp.get("governance.min_stake_to_propose_avt", 0) or 0)
        if current_agent.staked_balance <= 0:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only agents with locked units can create proposals"
            )
        if float(current_agent.staked_balance) < _min_stake:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(f"This frame requires {_min_stake:g} locked units to open a proposal "
                        f"(governance.min_stake_to_propose_avt); you hold "
                        f"{float(current_agent.staked_balance):g} locked."),
            )
    
    # P3/D2: Validate proposal_type
    if proposal.proposal_type not in ("standard", "policy_change"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="proposal_type must be 'standard' or 'policy_change'"
        )
    
    # §FRAMEPOLICY (2026-09-11) — the thresholds come from THIS FRAME'S policy
    # document, not from a literal here. They were 10.0/50.0 and 20.0/66.0 in
    # this function while the frame's own policy document declared its own
    # values and nothing ever read them; on the one node with a real document
    # the operator's declared 20% quorum had been ignored since April.
    # The factory defaults are those same 10.0/50.0/20.0/66.0, so a frame that
    # has never amended its policy behaves exactly as it did before this line.
    quorum_percent = float(_fp.get("governance.standard_quorum_percent", 10.0))
    pass_percent = float(_fp.get("governance.standard_pass_percent", 50.0))

    if proposal.proposal_type == "policy_change":
        if not proposal.policy_diff:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="policy_change proposals require a policy_diff payload"
            )
        # A change to the rules themselves is held to the frame's own higher bar.
        quorum_percent = float(_fp.get("governance.policy_change_quorum_percent", 20.0))
        pass_percent = float(_fp.get("governance.policy_change_pass_percent", 66.0))

        # §FRAMEPOLICY — refuse a diff the document itself would refuse, at
        # PROPOSE time rather than at apply time. A proposal carrying an unknown
        # key or an out-of-range value would otherwise run its whole voting
        # window, PASS, and then be swallowed by the apply path's except-clause.
        from ..services.frame_policy import validate_document as _validate_policy_doc
        from ..services.frame_policy import resolve as _resolve_policy
        from ..services.frame_policy import knob_governed_changes as _knob_governed_changes
        import copy as _copy
        _candidate_row = _deep_merge_dict(_copy.deepcopy(_fp._row_json or {}), proposal.policy_diff)
        _candidate = _resolve_policy(_candidate_row)
        _problems = _validate_policy_doc(_candidate)
        if _problems:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=("policy_diff would produce an invalid policy document: "
                        + "; ".join(_problems[:5])),
            )
        # §CARDBOND (2026-09-11) — a vote must be able to change what it votes on. Where an env
        # var or the network profile decides a rule (EU and ASIA charge the profile's 250 bond
        # while their documents say 50), a diff that MOVES that rule would pass, be stored, and
        # change nothing. Compared against the stored row, so restating today's value passes.
        _governed = _knob_governed_changes(_fp._row_json or {}, _candidate_row)
        if _governed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="knob_governed: " + "; ".join(_governed),
            )
    
    try:
        governance_proposal = await crud_governance.create_proposal(
            db=db,
            proposer_did=current_agent.did,
            title=proposal.title,
            description=proposal.description,
            duration_seconds=proposal.duration_seconds,
            proposal_type=proposal.proposal_type,
            policy_diff=proposal.policy_diff,
            quorum_percent=quorum_percent,
            pass_percent=pass_percent
        )

        if _GOV_PROM_AVAILABLE:
            GOVERNANCE_PROPOSALS_CREATED_TOTAL.labels(
                proposal_type=proposal.proposal_type,
                registry=_gov_registry_label(),
            ).inc()

        # Get initial vote summary (will be zeros)
        summary = await crud_governance.get_proposal_vote_summary(db, governance_proposal.id)
        
        # OWL20-PREP: Emit ProposalCreated to Event Store
        get_event_emitter().emit_background(
            event_type="ProposalCreated",
            aggregate_id=current_agent.did,
            aggregate_type="Governance",
            data={
                "proposal_id": governance_proposal.id,
                "proposer_did": current_agent.did,
                "title": proposal.title,
                "proposal_type": proposal.proposal_type,
                "duration_seconds": proposal.duration_seconds,
                "quorum_percent": quorum_percent,
                "pass_percent": pass_percent,
                "end_timestamp": governance_proposal.end_timestamp.isoformat()
            }
        )

        # A1 (2026-07-24): governance.proposal_created was subscribable but never fired.
        # Governance is public — broadcast (no developer scoping).
        import asyncio as _aio
        from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_event
        _aio.create_task(dispatch_webhook_event(
            "governance.proposal_created",
            {"proposal_id": governance_proposal.id, "proposer_did": current_agent.did,
             "title": proposal.title, "proposal_type": proposal.proposal_type,
             "end_timestamp": governance_proposal.end_timestamp.isoformat()},
            source_label="governance.create"))

        return ProposalResponse(
            id=governance_proposal.id,
            proposer_did=governance_proposal.proposer_did,
            title=governance_proposal.title,
            description=governance_proposal.description,
            status=governance_proposal.status,
            proposal_type=governance_proposal.proposal_type,
            quorum_percent=governance_proposal.quorum_percent,
            pass_percent=governance_proposal.pass_percent,
            created_at=governance_proposal.created_at,
            end_timestamp=governance_proposal.end_timestamp,
            votes_for=summary["votes_for"],
            votes_against=summary["votes_against"],
            total_voters=summary["total_voters"],
            **crud_governance.tally_record(governance_proposal),
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create proposal: {str(e)}"
        )


@router.get("/proposals/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(
    proposal_id: int = Path(..., gt=0, description="ID of the proposal"),
    db: AsyncSession = Depends(get_db)
) -> ProposalResponse:
    """Get a specific proposal and its current vote tally."""
    try:
        proposal = await crud_governance.get_proposal_with_votes(db, proposal_id)
        
        if not proposal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Proposal {proposal_id} not found"
            )
        
        summary = await crud_governance.get_proposal_vote_summary(db, proposal_id)
        
        return ProposalResponse(
            id=proposal.id,
            proposer_did=proposal.proposer_did,
            title=proposal.title,
            description=proposal.description,
            status=proposal.status,
            proposal_type=getattr(proposal, 'proposal_type', 'standard'),
            quorum_percent=getattr(proposal, 'quorum_percent', 10.0),
            pass_percent=getattr(proposal, 'pass_percent', 50.0),
            created_at=proposal.created_at,
            end_timestamp=proposal.end_timestamp,
            votes_for=summary["votes_for"],
            votes_against=summary["votes_against"],
            total_voters=summary["total_voters"],
            **crud_governance.tally_record(proposal),
        )
        
    except ValueError as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="An internal error occurred")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve proposal: {str(e)}"
        )


@router.get("/proposals", response_model=List[ProposalResponse])
async def list_active_proposals(
    db: AsyncSession = Depends(get_db),
    include_closed: bool = Query(False, description="Include closed proposals"),
    limit: int = Query(50, ge=1, le=200, description="Maximum proposals to return"),
    offset: int = Query(0, ge=0, description="Number of proposals to skip")
) -> List[ProposalResponse]:
    """List governance proposals. By default only returns active (VOTING) proposals."""
    try:
        if include_closed:
            stmt = select(GovernanceProposal).order_by(
                GovernanceProposal.created_at.desc()
            ).limit(limit).offset(offset)
            result = await db.execute(stmt)
            proposals = result.scalars().all()
        else:
            proposals = await crud_governance.get_active_proposals(db, limit=limit, offset=offset)
        
        # Batch-load all votes for these proposals in one query (avoid N+1)
        proposal_ids = [p.id for p in proposals]
        vote_summaries_map = {}
        if proposal_ids:
            all_votes_result = await db.execute(
                select(Vote).where(Vote.proposal_id.in_(proposal_ids))
            )
            all_votes = all_votes_result.scalars().all()
            for v in all_votes:
                entry = vote_summaries_map.setdefault(v.proposal_id, {
                    "votes_for": 0, "votes_against": 0, "total_voters": 0
                })
                entry["total_voters"] += 1
                if v.vote:
                    entry["votes_for"] += float(v.voting_power) if v.voting_power else 1
                else:
                    entry["votes_against"] += float(v.voting_power) if v.voting_power else 1

        response = []
        for p in proposals:
            summary = vote_summaries_map.get(p.id, {
                "votes_for": 0, "votes_against": 0, "total_voters": 0
            })
            response.append(ProposalResponse(
                id=p.id,
                proposer_did=p.proposer_did,
                title=p.title,
                description=p.description,
                status=p.status,
                proposal_type=getattr(p, 'proposal_type', 'standard'),
                quorum_percent=getattr(p, 'quorum_percent', 10.0),
                pass_percent=getattr(p, 'pass_percent', 50.0),
                created_at=p.created_at,
                end_timestamp=p.end_timestamp,
                votes_for=summary["votes_for"],
                votes_against=summary["votes_against"],
                total_voters=summary["total_voters"],
                **crud_governance.tally_record(p),
            ))
        
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list proposals: {str(e)}"
        )


@router.post("/proposals/{proposal_id}/vote", response_model=VoteResponse)
async def cast_vote(
    vote: VoteCreate,
    proposal_id: int = Path(..., gt=0, description="ID of the proposal"),
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(require_agent_permission("gov.vote"))
) -> VoteResponse:
    """
    Cast a vote on a proposal of this registry. Where the registry counts votes by membership
    (`governance_weight_mode` member, as on the public network), the vote carries the developer's membership points,
    one vote per member and proposal whichever of its agents casts it, and the member may have to confirm it
    (`GOVERNANCE_PRESENCE_MODE`); elsewhere it carries the weight of the agent's locked units over their remaining lock
    time, one vote per agent. Needs an agent token with the `gov.vote` permission.

    \f
    Cast a vote on a governance proposal.
    
    P3/D2: Voting power is calculated from veToken formula (time-weighted quadratic).
    Each agent can only vote once per proposal.
    """
    from ..services import membership as _membership
    if _membership.member_mode():
        # §MEMBERSHIP (2026-10-02) — one vote per member developer, weighed by tenure, confirmed by its
        # human where GOVERNANCE_PRESENCE_MODE asks. Refusals that would make a confirmation pointless
        # are answered first, so a single-use approval is never spent on a vote that cannot count.
        try:
            proposal_row, points = await crud_governance.precheck_member_vote(db, proposal_id, current_agent)
        except crud_governance.GovernanceRefusal as refusal:
            return JSONResponse(status_code=refusal.status_code, content=refusal.body())
        except ValueError as e:
            msg = str(e)
            code = (status.HTTP_404_NOT_FOUND if "not found" in msg else status.HTTP_400_BAD_REQUEST)
            raise HTTPException(status_code=code, detail=msg)
        if _membership.presence_mode() != "off":
            from ..models import Developer
            from ..services import governance_presence as _presence
            developer = await db.get(Developer, current_agent.creator_developer_id)
            ok, http_status, body = await _presence.require_presence(
                db, developer,
                action_type="governance.vote",
                action_ref=_presence.vote_action_ref(proposal_id, vote.vote_in_favor),
                facts=_presence.vote_facts(proposal_id=proposal_id, title=proposal_row.title,
                                           in_favor=vote.vote_in_favor, points=points),
                totp_code=vote.totp_code, challenge_id=vote.challenge_id,
            )
            if not ok:
                await db.commit()  # a freshly minted challenge must outlive this refusal
                chid = ((body or {}).get("step_up") or {}).get("challenge_id")
                if chid:
                    asyncio.create_task(_presence.announce_challenge(
                        current_agent.creator_developer_id, chid, action_type="governance.vote",
                        title="Confirm your vote",
                        message=f"Approve your vote on proposal #{proposal_id} in Pocket, Approvals."))
                return JSONResponse(status_code=http_status, content=body)
    else:
        # Check if agent has staked balance
        if current_agent.staked_balance <= 0:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only agents with locked units can vote"
            )
    
    try:
        vote_record = await crud_governance.cast_vote(
            db=db,
            proposal_id=proposal_id,
            voter_did=current_agent.did,
            vote_in_favor=vote.vote_in_favor,
            reason=vote.reason
        )

        if _GOV_PROM_AVAILABLE:
            GOVERNANCE_VOTES_CAST_TOTAL.labels(
                in_favor="yes" if vote.vote_in_favor else "no",
                registry=_gov_registry_label(),
            ).inc()

        # OWL20-PREP: Emit VoteCast to Event Store
        # NB: voting_power is Numeric(30,6) on the Vote model → Decimal at runtime,
        # which is NOT JSON-serializable. Convert to str (preserving precision)
        # before emitting; otherwise emit_background silently retries 3× then logs
        # "Object of type Decimal is not JSON serializable" and the event is lost.
        # Bug observed 2026-05-07: prod ES had only 2 VoteCast events ever (March 2026)
        # because of this.
        get_event_emitter().emit_background(
            event_type="VoteCast",
            aggregate_id=current_agent.did,
            aggregate_type="Governance",
            data={
                "proposal_id": proposal_id,
                "voter_did": current_agent.did,
                "vote_in_favor": vote.vote_in_favor,
                "voting_power": str(vote_record.voting_power) if vote_record.voting_power is not None else "0",
                "reason": vote.reason,
            }
        )

        # A1 (2026-07-24): governance.vote_cast was subscribable but never fired. Broadcast.
        import asyncio as _aio
        from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_event
        _aio.create_task(dispatch_webhook_event(
            "governance.vote_cast",
            {"proposal_id": proposal_id, "voter_did": current_agent.did,
             "vote_in_favor": vote.vote_in_favor,
             "voting_power": str(vote_record.voting_power) if vote_record.voting_power is not None else "0"},
            source_label="governance.vote"))

        return VoteResponse(
            id=vote_record.id,
            proposal_id=vote_record.proposal_id,
            voter_did=vote_record.voter_did,
            vote=vote_record.vote,
            voting_power=vote_record.voting_power,
            reason=vote_record.reason,
            created_at=vote_record.created_at
        )
        
    except crud_governance.GovernanceRefusal as refusal:
        return JSONResponse(status_code=refusal.status_code, content=refusal.body())
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg:
            status_code = status.HTTP_404_NOT_FOUND
        elif "already voted" in error_msg:
            status_code = status.HTTP_409_CONFLICT
        elif "not open for voting" in error_msg or "has ended" in error_msg:
            status_code = status.HTTP_400_BAD_REQUEST
        elif "no veToken voting power" in error_msg:
            status_code = status.HTTP_403_FORBIDDEN
        else:
            status_code = status.HTTP_400_BAD_REQUEST
            
        raise HTTPException(status_code=status_code, detail=error_msg)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cast vote: {str(e)}"
        )


@router.get("/proposals/{proposal_id}/votes", response_model=List[VoteResponse])
async def get_proposal_votes(
    proposal_id: int = Path(..., gt=0, description="ID of the proposal"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
) -> List[VoteResponse]:
    """Get paginated list of individual votes for a proposal."""
    try:
        result = await crud_governance.get_proposal_votes(db, proposal_id, page, limit)
        return [
            VoteResponse(
                id=v.id,
                proposal_id=v.proposal_id,
                voter_did=v.voter_did,
                vote=v.vote,
                voting_power=v.voting_power,
                reason=getattr(v, 'reason', None),
                created_at=v.created_at
            )
            for v in result["votes"]
        ]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get votes: {str(e)}"
        )


@router.get("/proposals/{proposal_id}/my-vote")
async def get_my_vote_on_proposal(
    proposal_id: int = Path(..., gt=0, description="ID of the proposal"),
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(get_current_agent)
) -> Dict[str, Any]:
    """Check if the current agent has voted on a specific proposal."""
    vote = await crud_governance.get_agent_vote_on_proposal(db, proposal_id, current_agent.did)
    
    if vote:
        return {
            "has_voted": True,
            "vote": {
                "id": vote.id,
                "choice": "for" if vote.vote else "against",
                "voting_power": vote.voting_power,
                "reason": getattr(vote, 'reason', None),
                "created_at": vote.created_at.isoformat()
            }
        }
    
    return {"has_voted": False, "vote": None}


@router.post("/proposals/{proposal_id}/tally", response_model=TallyResponse)
async def tally_proposal_votes(
    proposal_id: int = Path(..., gt=0, description="ID of the proposal"),
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(require_agent_permission("gov.vote"))
) -> TallyResponse:
    """
    Tally the votes for a proposal and finalize its status.
    
    Only the proposal creator can trigger the tally. The voting period
    must have ended before tallying is allowed.
    
    P3/D2: Now checks quorum_percent and pass_percent thresholds.
    """
    # OWL28 Issue #3: Verify caller is the proposal creator
    proposal_check = await crud_governance.get_proposal_with_votes(db, proposal_id)
    if not proposal_check:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proposal {proposal_id} not found"
        )
    if proposal_check.proposer_did != current_agent.did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the proposal creator can trigger the tally"
        )
    
    try:
        tally = await crud_governance.tally_votes(db, proposal_id)
        if tally.get("already_tallied"):
            # A closed proposal answers its stored result: nothing was tallied, so nothing is counted or emitted.
            return TallyResponse(**tally)

        if _GOV_PROM_AVAILABLE:
            outcome = "passed" if tally.get("status") in ("passed", "PASSED") else "failed"
            GOVERNANCE_TALLIES_TOTAL.labels(
                outcome=outcome,
                registry=_gov_registry_label(),
            ).inc()

        # OWL20-PREP: Emit ProposalTallied to Event Store
        get_event_emitter().emit_background(
            event_type="ProposalTallied",
            aggregate_id=f"proposal_{proposal_id}",
            aggregate_type="Governance",
            data={
                "proposal_id": tally["proposal_id"],
                "votes_for": tally["votes_for"],
                "votes_against": tally["votes_against"],
                "total_votes": tally["total_votes"],
                "quorum_met": tally["quorum_met"],
                "pass_rate": tally["pass_rate"],
                "result": tally["status"]
            }
        )
        
        # ⚠ §FRAMEPOLICY (2026-09-11) — this was a FIELD-BY-FIELD mapper, and it is
        # exactly the silent-drop machine PART 1 names. Widening TallyResponse was
        # not enough: the seven policy fields existed in the payload AND in the
        # response model, and this constructor simply never passed them, so the
        # live tally of proposal #2 on EU applied its policy and reported
        # policy_applied=None. Caught by the live proof, not by the unit test —
        # which pinned the MODEL and was blind to the constructor in the same way.
        # Splatting means a field added to the payload reaches the wire by
        # construction; TallyResponse is the contract that decides what is allowed.
        return TallyResponse(**tally)
        
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg:
            status_code = status.HTTP_404_NOT_FOUND
        elif "not ended yet" in error_msg:
            status_code = status.HTTP_400_BAD_REQUEST
        else:
            status_code = status.HTTP_400_BAD_REQUEST
            
        raise HTTPException(status_code=status_code, detail=error_msg)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to tally votes: {str(e)}"
        )


@router.get("/voting-power")
async def get_voting_power(
    current_agent: Annotated[Agent, Security(get_current_agent)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None
) -> Dict[str, Any]:
    """
    The calling agent's voting weight. Where the registry counts votes by membership (as on the public network), the
    answer has `mode` member, the developer's membership points as `votingPower`, `canVote` and the membership picture;
    elsewhere the weight of the agent's locked positions, per position, with its decay over time (each position weighs
    the square root of its amount times the share of the longest lock it has left). Delegation is not supported.
    Needs an agent token.

    \f
    Get veToken voting power for the current agent.
    
    P3/D2: Returns per-position veToken power breakdown and decay timeline.
    Formula: v_i = sqrt(amount) × (remaining_lock / T_max)
    """
    from ..services import membership as _membership
    if _membership.member_mode():
        # §MEMBERSHIP (2026-10-02) — in member mode a vote weighs what membership says, not what is locked.
        # The legacy keys keep their types (votingPower a string, positions a list) so an older console
        # renders a sane value; `membership` carries the whole picture.
        from ..models import Developer
        developer = await db.get(Developer, current_agent.creator_developer_id)
        picture = await _membership.status_for_developer(db, developer)
        return {
            "mode": "member",
            "votingPower": str(picture["points"]),
            "canVote": bool(picture["is_member"]),
            "positions": [],
            "decay_timeline": [],
            "delegatedFrom": [],
            "delegationSupported": False,
            "delegatedTo": None,
            "membership": picture,
        }

    # P3/D2: Use VeTokenCalculator for per-position breakdown
    breakdown = await vetoken_calculator.get_agent_power_breakdown(db, current_agent.did)
    
    # Build decay timeline from largest position (if any)
    decay_timeline = []
    if breakdown["positions"]:
        # Find the position with highest power for the decay chart
        from ..models import Stake
        stmt = select(Stake).where(
            Stake.agent_did == current_agent.did,
            Stake.is_active == True
        ).order_by(Stake.amount.desc()).limit(1)
        result = await db.execute(stmt)
        largest_stake = result.scalar_one_or_none()
        
        if largest_stake:
            decay_timeline = vetoken_calculator.get_power_decay_timeline(
                amount=largest_stake.amount,
                lock_period_days=largest_stake.lock_period_days,
                staked_at=largest_stake.staked_at,
                days_ahead=365,
                step_days=7
            )
    
    return {
        "votingPower": str(breakdown["total_ve_power"]),
        "canVote": breakdown["can_vote"],
        "positions": breakdown["positions"],
        "decay_timeline": decay_timeline,
        # A8 (2026-07-24): voting delegation is NOT implemented — [] is
        # definitional, not computed. delegationSupported tells clients not to
        # render delegated power as a real zero.
        "delegatedFrom": [],
        "delegationSupported": False,
        "delegatedTo": None
    }


@router.get("/lock-options")
async def get_lock_options() -> Dict[str, Any]:
    """
    Get available lock tiers and projected power multipliers.
    
    P3/D2: Helps users understand how lock duration affects voting power.
    """
    return vetoken_calculator.get_lock_options()


@router.get("/stats")
async def get_governance_stats(
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Governance statistics of this registry: proposals in all and open, distinct voters, the voting power cast,
    the network's total voting power (`networkVePower`: its members' points where votes count by membership, with
    `mode` member and the member count; else the weight of locked units) and the share of active agents that voted."""
    
    # Query all proposals
    stmt = select(GovernanceProposal)
    result = await db.execute(stmt)
    all_proposals = result.scalars().all()
    
    # Count by status
    active_count = sum(1 for p in all_proposals if p.status == "VOTING")
    
    # Count unique voters (real query)
    voters_stmt = select(func.count(distinct(Vote.voter_did)))
    total_voters = await db.scalar(voters_stmt) or 0
    
    # Calculate total voting power used in votes (real query)
    voting_power_stmt = select(func.sum(Vote.voting_power))
    total_voting_power = await db.scalar(voting_power_stmt) or 0
    
    # P3/D2: Calculate network total veToken power
    # §MEMBERSHIP (2026-10-02) — in member mode the network's power is its members' points.
    from ..services import membership as _membership
    _member_stats = None
    if _membership.member_mode():
        _member_stats = await _membership.stats(db)
        network_ve_power = _member_stats["network_points"]
    else:
        network_ve_power = await vetoken_calculator.get_network_total_power(db)
    
    # Calculate participation rate
    active_agents_stmt = select(func.count(Agent.id)).where(Agent.status == "active")
    total_active_agents = await db.scalar(active_agents_stmt) or 0
    
    participation_rate = 0.0
    if total_active_agents > 0:
        participation_rate = round((total_voters / total_active_agents) * 100, 2)
    
    out = {
        "totalProposals": len(all_proposals),
        "activeProposals": active_count,
        "totalVoters": total_voters,
        "totalVotingPower": str(total_voting_power),
        "networkVePower": str(network_ve_power),
        "participationRate": participation_rate
    }
    if _member_stats is not None:
        out["mode"] = "member"
        out["members"] = _member_stats["members"]
    return out


# ═══ Admin: Auto-Tally Configuration ═══════════════════════════════════════

@router.get("/auto-tally/config", summary="Get auto-tally configuration")
async def get_auto_tally_config(
    admin=Security(security.require_admin_flag("admin_platform")),
):
    """Get the current auto-tally configuration (admin only). `store` says where an override lives: `shared` (Redis,
    every worker reads it) or `process` (no Redis on this registry: the answering worker only)."""
    from ..background_tasks.auto_tally import get_config
    return await get_config()


class AutoTallyConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    interval_seconds: Optional[int] = Field(None, ge=10, le=3600)


@router.put("/auto-tally/config", summary="Update auto-tally configuration")
async def update_auto_tally_config(
    config: AutoTallyConfigUpdate,
    admin=Security(security.require_admin_flag("admin_platform")),
):
    """Update auto-tally configuration at runtime (admin only).
    Changes take effect on the next tally cycle, no restart required: the loop reads the configuration every turn
    (§DOCSFIX D6-567: kept in Redis, so the worker that holds the loop sees a change any worker answered)."""
    from ..background_tasks.auto_tally import set_config
    return await set_config(
        enabled=config.enabled,
        interval_seconds=config.interval_seconds,
    )


# ═══ Federation Governance — Cross-Registry Proposals ═══════════════════════

import httpx
import os
import ssl as _ssl

def _get_es_client_kwargs():
    """Get EventStore client kwargs with mTLS certs if available.

    §BATCH7 (eb's finding, 2026-09-05): `verify=bundle.0.pem` alone trusts ONLY the SPIRE roots, so
    a registry whose EVENT_STORE_URL is a public Let's-Encrypt vhost (every cloud operator:
    https://events.theprotocol.cloud) failed CERTIFICATE_VERIFY_FAILED here while the emitter,
    which chooses per host, kept working. The shared dual-trust context (SPIRE bundle + system
    roots, the SVID loaded as the client chain — es_ssl_helper) is the ONE rule; the bare cert
    tuple is only needed when no context could be built."""
    import ssl as _ssl
    from ..es_ssl_helper import get_httpx_verify
    kwargs = {"timeout": 30.0}
    verify = get_httpx_verify()
    kwargs["verify"] = verify
    if not isinstance(verify, _ssl.SSLContext):
        cert_dir = os.getenv("SVID_CERT_DIR", "/certs")
        cert_path = os.path.join(cert_dir, "svid.0.pem")
        key_path = os.path.join(cert_dir, "svid.0.key")
        if os.path.exists(cert_path) and os.path.exists(key_path):
            kwargs["cert"] = (cert_path, key_path)
    return kwargs

def _get_es_headers():
    """Get EventStore auth headers (internal key for direct HTTP, or nothing for mTLS)."""
    key = os.getenv("EVENT_STORE_API_KEY") or os.getenv("EVENT_STORE_INTERNAL_API_KEY", "")
    if key:
        return {"X-Internal-Key": key}
    return {}

def _get_es_url():
    return os.getenv("EVENT_STORE_URL", "http://event-store:8200").rstrip("/")


def _federation_ballot_mode() -> bool:
    from ..services import federation_ballot as _fb
    return _fb.ballot_mode()


class FederationProposeRequest(BaseModel):
    local_proposal_id: int = Field(..., description="ID of the passed local proposal to elevate")
    duration_seconds: int = Field(default=604800, ge=3600, le=2592000, description="Federation voting window (default 7 days)")


class FederationVoteRequest(BaseModel):
    vote_in_favor: bool
    reason: Optional[str] = Field(None, max_length=1000)


class FederationVetoRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000)


def origin_tally_payload(tally_result: Dict[str, Any], local_proposal_id: int) -> Dict[str, Any]:
    """The tally evidence an elevated proposal carries to the federation ledger, JSON-safe.

    §FEDPROOF (2026-09-13): the vote summary carries Decimals (voting power is Numeric(30,6)), and
    `httpx` json= refuses them: every elevation on a frame whose voters held ve power answered
    500 `Object of type Decimal is not JSON serializable`. No federation proposal had ever been
    created on any live ledger, which is how the class hid. Numbers are coerced here, once.
    """
    def num(v: Any) -> Any:
        if isinstance(v, Decimal):
            return int(v) if v == v.to_integral_value() else float(v)
        return v
    return {
        "votes_for": num(tally_result.get("votes_for", 0)),
        "votes_against": num(tally_result.get("votes_against", 0)),
        "pass_rate": num(tally_result.get("pass_rate", 0)),
        "quorum_met": True,
        "status": "PASSED",
        "local_proposal_id": local_proposal_id,
    }


@router.post("/federation/propose", summary="Elevate local proposal to federation", status_code=201)
async def federation_propose(
    body: FederationProposeRequest,
    admin=Security(security.require_admin_flag("admin_platform")),
    db: AsyncSession = Depends(get_db),
):
    """Elevate a passed local proposal to the federation. Admin only.

    The local proposal must have status=PASSED. Its tally evidence is included.
    """
    # Fetch the local proposal
    proposal = await crud_governance.get_proposal_with_votes(db, body.local_proposal_id)
    if not proposal:
        raise HTTPException(404, "Local proposal not found")
    if getattr(proposal, "proposal_type", None) == "federation_ballot":
        # §MEMBERSHIP D2: a members' vote that decides this registry's ballot is not itself a proposal to elevate
        raise HTTPException(400, "A federation ballot vote decides this registry's ballot; it is not elevated")
    if proposal.status != "PASSED":
        raise HTTPException(400, f"Local proposal must be PASSED (current: {proposal.status})")

    # Build tally evidence
    tally_result = await crud_governance.get_proposal_vote_summary(db, body.local_proposal_id)
    origin_tally = origin_tally_payload(tally_result, body.local_proposal_id)

    # §MCPTEST30 (V0559): the name the card publishes (a cloud operator's REGISTRY_NAME is its container label)
    from ..services.registry_card_builder import federation_name
    registry_name = federation_name() or "Unknown Registry"

    # Forward to EventStore
    es_url = _get_es_url()
    async with httpx.AsyncClient(**_get_es_client_kwargs()) as client:
        try:
            resp = await client.post(
                f"{es_url}/api/v1/federation-governance/propose",
                json={
                    "title": proposal.title,
                    "description": proposal.description,
                    "policy_diff": proposal.policy_diff,
                    "origin_proposal_id": body.local_proposal_id,
                    "origin_tally": origin_tally,
                    "duration_seconds": body.duration_seconds,
                    # §MEMBERSHIP D2: where FEDERATION_BALLOT_MODE=on, registries decide it, one ballot each
                    "ballot_mode": _federation_ballot_mode(),
                },
                headers=_get_es_headers(),
            )
            if resp.status_code == 201:
                return resp.json()
            raise HTTPException(resp.status_code, f"EventStore: {resp.text}")
        except httpx.RequestError as e:
            raise HTTPException(502, f"Failed to reach EventStore: {str(e)}")


@router.get("/federation/proposals", summary="List federation proposals")
async def federation_list_proposals(
    status_filter: Optional[str] = Query(None, alias="status"),
    agent: Agent = Security(get_current_agent),
):
    """List federation proposals (proxied from EventStore)."""
    es_url = _get_es_url()
    params = {}
    if status_filter:
        params["status"] = status_filter

    async with httpx.AsyncClient(**_get_es_client_kwargs()) as client:
        try:
            resp = await client.get(
                f"{es_url}/api/v1/federation-governance/proposals",
                params=params,
                headers=_get_es_headers(),
            )
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(resp.status_code, f"EventStore: {resp.text}")
        except httpx.RequestError as e:
            raise HTTPException(502, f"Failed to reach EventStore: {str(e)}")


@router.post("/federation/proposals/{proposal_id}/vote", summary="Vote on federation proposal")
async def federation_vote(
    proposal_id: str,
    body: FederationVoteRequest,
    agent: Agent = Security(require_agent_permission("gov.vote")),
    db: AsyncSession = Depends(get_db),
):
    """Vote on a federation proposal. Where federation proposals are decided by one ballot per registry
    (`FEDERATION_BALLOT_MODE`, on the public network) this answers 409: vote on the linked local proposal instead.
    Where votes count by membership it answers 409 as well. Elsewhere the registry weighs the agent's locked units and
    forwards the vote to the event store. Needs an agent token with the `gov.vote` permission.

    \f
    Vote on a federation proposal. Registry calculates veToken power and forwards to EventStore."""
    from ..services import membership as _membership
    if _federation_ballot_mode():
        # §MEMBERSHIP D2: registries cast ballots here, one each; an agent decides through its registry
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={
            "error": "registry_ballots",
            "message": ("Federation proposals here are decided by one ballot per registry. With members, the "
                        "registry's ballot follows their vote on the linked local proposal; vote there."),
        })
    if _membership.member_mode():
        # §MEMBERSHIP (2026-10-02) — in member mode a registry will vote in the federation as ONE ballot
        # carrying its members' result (design § 12, S2). Until that ships, an agent's federation vote is
        # refused rather than forwarded: the store keeps votes per agent, so it cannot tell that two
        # agents belong to one member, and it would count locked Units against a member's points.
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={
            "error": "federation_ballot_pending",
            "message": ("In member mode this registry votes in federation proposals as one ballot carrying "
                        "its members' result; that ballot is not available yet. Vote on the local proposal."),
        })
    # Calculate agent's veToken power locally
    ve_power = await vetoken_calculator.calculate_agent_power(db, agent.did)
    if ve_power <= 0:
        raise HTTPException(403, "Must have locked units (voting weight above 0) to vote on federation proposals")

    voting_power_int = max(1, int(round(ve_power)))

    es_url = _get_es_url()
    async with httpx.AsyncClient(**_get_es_client_kwargs()) as client:
        try:
            resp = await client.post(
                f"{es_url}/api/v1/federation-governance/proposals/{proposal_id}/vote",
                json={
                    "voter_did": agent.did,
                    "vote_in_favor": body.vote_in_favor,
                    "voting_power": voting_power_int,
                    "reason": body.reason,
                },
                headers=_get_es_headers(),
            )
            if resp.status_code == 201:
                return resp.json()
            raise HTTPException(resp.status_code, f"EventStore: {resp.text}")
        except httpx.RequestError as e:
            raise HTTPException(502, f"Failed to reach EventStore: {str(e)}")


@router.post("/federation/proposals/{proposal_id}/veto", summary="Veto federation proposal (commander)")
async def federation_veto(
    proposal_id: str,
    body: FederationVetoRequest,
    admin=Security(security.require_admin_flag("admin_platform")),
):
    """Commander vetoes a passed federation proposal. Admin only."""
    es_url = _get_es_url()
    async with httpx.AsyncClient(**_get_es_client_kwargs()) as client:
        try:
            resp = await client.post(
                f"{es_url}/api/v1/federation-governance/proposals/{proposal_id}/veto",
                json={"reason": body.reason},
                headers=_get_es_headers(),
            )
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(resp.status_code, f"EventStore: {resp.text}")
        except httpx.RequestError as e:
            raise HTTPException(502, f"Failed to reach EventStore: {str(e)}")


# GV2 (2026-07-24): the ES has had tally/apply endpoints since day one but the
# registry never proxied them — federation proposals rotted in VOTING forever
# unless someone curled the ES directly. The auto_tally worker drives these on
# schedule; the admin proxies below are the manual lever.
@router.post("/federation/proposals/{proposal_id}/tally", summary="Tally federation proposal (admin)")
async def federation_tally(
    proposal_id: str,
    admin=Security(security.require_admin_flag("admin_platform")),
):
    """Tally a federation proposal (weight-based quorum + multi-registry check; a ballot proposal by its ballots,
    with the registries eligible now, which only this host can say)."""
    from ..database import get_db_context
    from ..services import federation_ballot as _fb
    es_url = _get_es_url()
    async with httpx.AsyncClient(**_get_es_client_kwargs()) as client:
        try:
            body = None
            got = await client.get(f"{es_url}/api/v1/federation-governance/proposals/{proposal_id}",
                                   headers=_get_es_headers())
            if got.status_code == 200 and got.json().get("ballot_mode"):
                async with get_db_context() as db:
                    body = await _fb.tally_body(db, got.json())
            resp = await client.post(
                f"{es_url}/api/v1/federation-governance/proposals/{proposal_id}/tally",
                headers=_get_es_headers(), json=body,
            )
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(resp.status_code, f"EventStore: {resp.text}")
        except httpx.RequestError as e:
            raise HTTPException(502, f"Failed to reach EventStore: {str(e)}")


@router.post("/federation/proposals/{proposal_id}/apply", summary="Apply federation proposal (admin)")
async def federation_apply(
    proposal_id: str,
    admin=Security(security.require_admin_flag("admin_platform")),
):
    """Apply a PASSED federation proposal after its veto window — emits
    FederationPolicyUpdated on the ledger (the compliance pollers react)."""
    es_url = _get_es_url()
    async with httpx.AsyncClient(**_get_es_client_kwargs()) as client:
        try:
            resp = await client.post(
                f"{es_url}/api/v1/federation-governance/proposals/{proposal_id}/apply",
                headers=_get_es_headers(),
            )
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(resp.status_code, f"EventStore: {resp.text}")
        except httpx.RequestError as e:
            raise HTTPException(502, f"Failed to reach EventStore: {str(e)}")
