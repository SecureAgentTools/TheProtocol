"""Federation governance router — cross-registry proposals to the mainframe.

Endpoints for creating, voting on, tallying, and managing federation-wide
policy change proposals. Auth: mTLS or internal key required.
"""
from fastapi import APIRouter, HTTPException, Depends, Header, Security, Body
from typing import Optional, Dict, List
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from ..database.connection import get_db
from ..services import federation_governance as gov_service
from .events import verify_event_auth
from ..es_auth import is_origin, own_trust_domain
import os
import uuid
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/federation-governance", tags=["federation-governance"])


# ─── Request/Response Schemas ───────────────────────────────────────────

class FederationProposalCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=5000)
    policy_diff: Optional[dict] = None
    origin_proposal_id: Optional[int] = None
    origin_tally: Optional[dict] = None  # {votes_for, votes_against, pass_rate, quorum_met}
    duration_seconds: int = Field(default=604800, ge=3600, le=2592000)  # 1 hour to 30 days
    ballot_mode: bool = False  # §MEMBERSHIP D2: decided by one ballot per registry (the host's FEDERATION_BALLOT_MODE)


class RegistryBallotCreate(BaseModel):
    """§MEMBERSHIP D2: one registry's ballot, as the host registry recorded it after verifying it."""
    registry_id: str = Field(..., min_length=12, max_length=255, pattern=r"^registry:[^/\s]+/[^\s]+$")
    choice: str = Field(..., pattern="^(for|against|abstain)$")
    ballot_jws: str = Field(..., min_length=20, max_length=16384)
    basis: Optional[dict] = None
    eligibility: Optional[dict] = None


class TallyRequest(BaseModel):
    """§MEMBERSHIP D2: a ballot proposal's tally needs the registries eligible NOW (the host registry computes them)."""
    eligible_registries: Optional[List[str]] = Field(default=None, max_length=500)


class FederationVoteCreate(BaseModel):
    voter_did: str = Field(..., min_length=1, max_length=255)
    vote_in_favor: bool
    voting_power: int = Field(..., ge=1)  # veToken power (calculated by registry)
    reason: Optional[str] = Field(None, max_length=1000)


class VetoRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000)


# ─── Endpoints ──────────────────────────────────────────────────────────

@router.post("/propose", status_code=201)
async def create_proposal(
    body: FederationProposalCreate,
    auth_context: Dict = Security(verify_event_auth),
    db: AsyncSession = Depends(get_db),
):
    """Elevate a local proposal to federation. Requires mTLS or internal auth.

    The proposing registry must include evidence of a passed local proposal.
    """
    # Must be authenticated (mTLS, internal key, or federation license)
    operator_name = auth_context.get("operator", "unknown")
    registry_id = auth_context.get("spiffe_id") or auth_context.get("operator_id") or "origin"

    if not body.origin_tally:
        raise HTTPException(400, "origin_tally required — must include evidence of a passed local proposal")

    # Validate origin tally shows the proposal passed
    tally = body.origin_tally
    if not tally.get("quorum_met") or tally.get("status") not in ("PASSED", "passed"):
        raise HTTPException(400, "Local proposal must have passed (quorum_met=true, status=PASSED)")

    proposal = await gov_service.create_federation_proposal(
        db=db,
        title=body.title,
        description=body.description,
        policy_diff=body.policy_diff,
        origin_registry_id=registry_id,
        origin_proposal_id=body.origin_proposal_id,
        origin_tally=body.origin_tally,
        proposer_operator_name=operator_name,
        duration_seconds=body.duration_seconds,
        ballot_mode=body.ballot_mode,
    )
    return gov_service._proposal_to_dict(proposal)


@router.get("/proposals")
async def list_proposals(
    status: Optional[str] = None,
    auth_context: Dict = Security(verify_event_auth),
    db: AsyncSession = Depends(get_db),
):
    """List federation proposals with optional status filter."""
    return await gov_service.list_federation_proposals(db, status_filter=status)


@router.get("/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: uuid.UUID,
    auth_context: Dict = Security(verify_event_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get a federation proposal with vote summary."""
    result = await gov_service.get_federation_proposal(db, proposal_id)
    if not result:
        raise HTTPException(404, "Federation proposal not found")
    return result


@router.post("/proposals/{proposal_id}/vote", status_code=201)
async def cast_vote(
    proposal_id: uuid.UUID,
    body: FederationVoteCreate,
    auth_context: Dict = Security(verify_event_auth),
    db: AsyncSession = Depends(get_db),
):
    """Cast a vote on a federation proposal.

    The registry calculates veToken power locally and submits it here.
    The auth context identifies which registry is submitting (mTLS identity).
    """
    registry_id = auth_context.get("spiffe_id") or auth_context.get("operator_id") or auth_context.get("operator", "origin")
    own, _own_source = own_trust_domain(os.getenv("ES_OWN_TRUST_DOMAIN"), os.getenv("CERT_DIR", "/certs"))

    try:
        vote = await gov_service.cast_federation_vote(
            db=db,
            proposal_id=proposal_id,
            voter_did=body.voter_did,
            voter_registry_id=registry_id,
            vote_in_favor=body.vote_in_favor,
            raw_voting_power=body.voting_power,
            reason=body.reason,
            auth_context=auth_context,
            own_domain=own,
        )
        return {
            "vote_id": str(vote.id),
            "proposal_id": str(vote.proposal_id),
            "voter_did": vote.voter_did,
            "vote_in_favor": vote.vote_in_favor,
            "voting_power": vote.voting_power,
            "raw_voting_power": vote.raw_voting_power,
            "voter_registry_id": vote.voter_registry_id,
        }
    except PermissionError as e:   # SEC-20: no record of the caller here
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        if "uix_federation_votes_proposal_voter" in str(e):
            raise HTTPException(409, "Agent has already voted on this proposal")
        raise HTTPException(500, f"Vote failed: {str(e)}")


@router.post("/proposals/{proposal_id}/ballots", status_code=201)
async def cast_ballot(
    proposal_id: uuid.UUID,
    body: RegistryBallotCreate,
    auth_context: Dict = Security(verify_event_auth),
    db: AsyncSession = Depends(get_db),
):
    """§MEMBERSHIP D2: record one REGISTRY's ballot. Only this frame's own registry writes here, after verifying the
    ballot's signature, the caller's identity and its eligibility; a peer delivers its ballot to that registry."""
    if not is_origin(auth_context):
        raise HTTPException(403, "Only this frame's own registry records registry ballots")
    try:
        vote = await gov_service.cast_registry_ballot(
            db, proposal_id, registry_id=body.registry_id, choice=body.choice, ballot_jws=body.ballot_jws,
            basis=body.basis, eligibility=body.eligibility,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        if "uix_federation_votes_proposal_voter" in str(e):
            raise HTTPException(409, "this registry has already cast its ballot on this proposal")
        raise HTTPException(500, f"Ballot failed: {str(e)}")
    return {"proposal_id": str(vote.proposal_id), "registry_id": vote.voter_registry_id, "choice": vote.choice,
            "cast_at": vote.created_at.isoformat() if vote.created_at else None}


@router.get("/proposals/{proposal_id}/ballots")
async def list_ballots(
    proposal_id: uuid.UUID,
    auth_context: Dict = Security(verify_event_auth),
    db: AsyncSession = Depends(get_db),
):
    """§MEMBERSHIP D2: the registry ballots on a proposal, each with its signed document as delivered."""
    return {"proposal_id": str(proposal_id), "ballots": await gov_service.list_registry_ballots(db, proposal_id)}


@router.post("/proposals/{proposal_id}/tally")
async def tally_proposal(
    proposal_id: uuid.UUID,
    auth_context: Dict = Security(verify_event_auth),
    db: AsyncSession = Depends(get_db),
    body: Optional[TallyRequest] = Body(default=None),
):
    """Tally votes for a federation proposal. Checks multi-registry quorum.

    Only internal services (mainframe) should call this. A BALLOT proposal (§MEMBERSHIP D2) is tallied only by this
    frame's own registry, which passes the eligible registries: a peer that could pass its own list could pick the
    electorate."""
    if auth_context.get("auth_type") not in ("internal", "mtls"):
        raise HTTPException(403, "Only mainframe services can tally federation proposals")
    eligible = body.eligible_registries if body is not None else None
    if eligible is not None and auth_context.get("auth_type") != "internal" and not is_origin(auth_context):
        raise HTTPException(403, "Only this frame's own registry tallies a ballot proposal")

    try:
        return await gov_service.tally_federation_proposal(db, proposal_id, eligible_registries=eligible)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/proposals/{proposal_id}/veto")
async def veto_proposal(
    proposal_id: uuid.UUID,
    body: VetoRequest,
    auth_context: Dict = Security(verify_event_auth),
    db: AsyncSession = Depends(get_db),
):
    """Commander vetoes a passed federation proposal.

    Only internal services (mainframe admin) should call this.
    """
    # §SOVKIT T5 (2026-09-14): "internal" meant "this frame's own service"; behind the store's mTLS sidecar that caller
    # authenticates by certificate (auth_type mtls, operator origin), so origin is the test, never the header it used.
    if auth_context.get("auth_type") != "internal" and not is_origin(auth_context):
        raise HTTPException(403, "Only mainframe admin can veto federation proposals")

    try:
        proposal = await gov_service.veto_federation_proposal(
            db, proposal_id, vetoed_by=auth_context.get("operator", "commander"), reason=body.reason
        )
        return gov_service._proposal_to_dict(proposal)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/proposals/{proposal_id}/apply")
async def apply_proposal(
    proposal_id: uuid.UUID,
    auth_context: Dict = Security(verify_event_auth),
    db: AsyncSession = Depends(get_db),
):
    """Apply a passed federation proposal after veto window expires.

    Only internal services (mainframe admin) should call this.
    """
    if auth_context.get("auth_type") != "internal" and not is_origin(auth_context):   # §SOVKIT T5: see veto_proposal
        raise HTTPException(403, "Only mainframe admin can apply federation proposals")

    try:
        proposal = await gov_service.apply_federation_proposal(db, proposal_id)
        return gov_service._proposal_to_dict(proposal)
    except ValueError as e:
        raise HTTPException(400, str(e))
