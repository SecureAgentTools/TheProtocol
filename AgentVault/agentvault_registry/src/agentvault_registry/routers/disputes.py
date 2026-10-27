"""
API router for the Decentralized Dispute Resolution (DDR) system.

This module provides REST API endpoints for creating and managing disputes
between agents in the decentralized justice system.
"""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Security
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, field_validator

from ..database import get_db
from ..crud import crud_disputes
from ..models import Dispute, Evidence, Agent
from ..event_emitter import get_event_emitter
from ..security import get_current_agent, get_current_developer, get_current_actor_for_read
import asyncio
import logging

logger = logging.getLogger(__name__)

# OWL20-PREP: Event Store integration for dispute audit trail — lazy init
def _serialize_dispute(dispute) -> "DisputeResponse":
    """Shared serialization for dispute + evidence."""
    evidence_list = [
        EvidenceResponse(
            id=e.id,
            dispute_id=e.dispute_id,
            submitter_did=e.submitter_did,
            evidence_data=e.evidence_data,
            created_at=e.created_at.isoformat()
        )
        for e in (dispute.evidence or [])
    ]
    return DisputeResponse(
        id=dispute.id,
        status=dispute.status,
        ruling=dispute.ruling,
        complainant_did=dispute.complainant_did,
        defendant_did=dispute.defendant_did,
        created_at=dispute.created_at.isoformat(),
        updated_at=dispute.updated_at.isoformat(),
        evidence=evidence_list,
        # X1 (2026-05-06): soft int reference to source RUC contract.
        contract_id=getattr(dispute, "contract_id", None),
        contract_ref=getattr(dispute, "contract_ref", None),
    )


# Pydantic models for request/response
class DisputeCreate(BaseModel):
    """Request model for creating a new dispute."""
    defendant_did: str = Field(..., max_length=120, description="DID of the agent being accused")
    # Phase 3 trust-chain: defendant's verified ZKP attestations cited as
    # exculpatory evidence, stored on the dispute (referenced_attestations). No slash
    # path applies a reduction in this release (D6-440): the sandbox-only
    # /admin/disputes/{id}/preview-slash-reduction computes one without applying it.
    attestation_ids: Optional[List[str]] = Field(
        default=None,
        description="UUID strings of verified attestations cited as exculpatory evidence",
        max_length=20,
    )

    @field_validator("defendant_did")
    @classmethod
    def validate_did(cls, v):
        from agentvault_registry.input_validators import validate_did as _validate
        return _validate(v)


class EvidenceSubmit(BaseModel):
    """Request model for submitting evidence to a dispute."""
    evidence_data: Dict[str, Any] = Field(..., description="JSON data containing the evidence details")

    @field_validator("evidence_data")
    @classmethod
    def _cap_size(cls, v):
        """D3: cap serialized size at 100KB to prevent DoS via huge JSON."""
        import json as _json
        try:
            blob = _json.dumps(v)
        except Exception:
            raise ValueError("evidence_data must be JSON-serializable")
        if len(blob) > 102400:
            raise ValueError(
                f"evidence_data exceeds 100KB limit ({len(blob)} bytes). "
                "Split large evidence into multiple submissions or store off-chain."
            )
        return v


class EvidenceResponse(BaseModel):
    """Response model for evidence."""
    id: int
    dispute_id: int
    submitter_did: str
    evidence_data: Dict[str, Any]
    created_at: str

    class Config:
        from_attributes = True


class DisputeResponse(BaseModel):
    """Response model for a dispute."""
    id: int
    status: str
    ruling: Optional[str]
    complainant_did: str
    defendant_did: str
    created_at: str
    updated_at: str
    evidence: List[EvidenceResponse]
    # X1 (2026-05-06): soft int reference to source RUC contract when the
    # dispute was filed via /contracts/{id}/malpractice. Null otherwise.
    contract_id: Optional[int] = None
    # CONTRACT SPINE (2026-07-25): the spine contract this dispute is about (ctr_…). Set by the
    # milestone-reject / malpractice paths; rulings on such disputes settle the ESCROW, not
    # wallet compensation (one settlement authority).
    contract_ref: Optional[str] = None

    class Config:
        from_attributes = True


# Create the router
router = APIRouter(
    prefix="/api/v1/disputes",
    tags=["Disputes"],
    responses={404: {"description": "Not found"}},
)


def reads_every_dispute(developer) -> bool:
    """An administrator who rules on disputes (admin_enforcement, or the legacy superadmin) reads every dispute, on a
    credential that reaches admin (an API key scoped for MCP use does not, security.api_key_grants_admin) and not while
    the account must change its password: the same bar as PUT /admin/disputes/{id}/ruling. D6-821: and under
    REQUIRE_ADMIN_2FA only with the second factor (security.admin_flag_credential asks all of it)."""
    from ..security import admin_flag_credential
    return admin_flag_credential(developer, "admin_enforcement")


async def developer_owns_one_of(db: AsyncSession, developer_id: int, dids) -> bool:
    """Does this developer own one of these agents (agents.creator_developer_id)?"""
    from sqlalchemy import select as _select
    wanted = [d for d in dids if d]
    if not wanted:
        return False
    row = await db.execute(
        _select(Agent.id).where(Agent.creator_developer_id == developer_id, Agent.did.in_(wanted)).limit(1))
    return row.first() is not None


# FIX-28: GET all disputes endpoint
@router.get("/", response_model=List[DisputeResponse])
async def list_disputes(
    status_filter: Optional[str] = None,
    status: Optional[str] = None,
    defendant_did: Optional[str] = None,
    complainant_did: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_developer=Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """List the disputes one of the caller's agents is a party to (an administrator who rules on disputes: every
    dispute). Requires developer auth.

    ``status`` (canonical) and ``status_filter`` (legacy) are accepted
    interchangeably; ``defendant_did`` + ``complainant_did`` filter at query time.
    For example ``?defendant_did=X&status=open``.

    \f
    §SECFIX D6-465 (2026-10-16, his word): this listed every dispute of the registry, evidence included, to any
    developer credential. The parties' owners read a dispute, and the administrators who rule on it.
    """
    effective_status = status or status_filter
    disputes = await crud_disputes.get_all_disputes(
        db=db,
        status_filter=effective_status,
        defendant_did=defendant_did,
        complainant_did=complainant_did,
        limit=limit,
        offset=offset,
        party_developer_id=None if reads_every_dispute(current_developer) else current_developer.id,
    )
    return [_serialize_dispute(d) for d in disputes]


async def defendant_known(db: AsyncSession, did: str) -> bool:
    """True when ANY local row knows this DID: a native agent (agents.did) or a mirrored card
    (agent_cards.agent_did, active). The same two-table question the mint-time net asks."""
    from sqlalchemy import select as _select
    from ..models import Agent as _Agent, AgentCard as _AgentCard
    if (await db.execute(_select(_Agent.id).where(_Agent.did == did).limit(1))).first() is not None:
        return True
    return (await db.execute(
        _select(_AgentCard.id).where(_AgentCard.agent_did == did, _AgentCard.is_active == True).limit(1)  # noqa: E712
    )).first() is not None


@router.post("/", response_model=DisputeResponse, status_code=status.HTTP_201_CREATED)
async def create_dispute(
    dispute_data: DisputeCreate,
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(get_current_agent)
):
    """
    Create a new dispute between two agents.

    This endpoint allows authenticated agents to file disputes against other agents
    in the decentralized justice system. The complainant is derived from the
    authenticated agent's identity.
    """
    complainant_did = current_agent.did

    # Validate that complainant and defendant are different
    if complainant_did == dispute_data.defendant_did:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Complainant and defendant cannot be the same agent"
        )

    # §DIDWIDEN-1 closer (eb's measurement 2026-09-06: two fabricated DIDs were accepted and a real dispute row filed
    # on a mainframe and on an operator): the defendant must be an agent this registry knows — a native row or a
    # mirrored card. A wider DID space never helps a rail that does not look the DID up. Same phrase as the bond rail.
    if not await defendant_known(db, dispute_data.defendant_did):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Defendant {dispute_data.defendant_did} is not known to this registry: no agent row and no mirrored card",
        )

    # Create the dispute (Phase 3: pass through optional attestation_ids
    # for the slash-reduction lookup pipeline)
    dispute = await crud_disputes.create_dispute(
        db=db,
        complainant_did=complainant_did,
        defendant_did=dispute_data.defendant_did,
        referenced_attestations=dispute_data.attestation_ids,
    )

    # OWL20-PREP: Emit DisputeFiled to Event Store
    # D7: synchronous emit (was fire-and-forget; created GC race).
    # D15: aggregate_id="dispute:N", aggregate_type="Dispute" (normalized).
    try:
        _emitter = get_event_emitter()
        await _emitter.emit(
            event_type="DisputeFiled",
            aggregate_id=f"dispute:{dispute.id}",
            aggregate_type="Dispute",
            data={
                "dispute_id": dispute.id,
                "complainant_did": complainant_did,
                "defendant_did": dispute_data.defendant_did,
                "status": dispute.status
            }
        )
    except Exception as e:
        logger.warning(f"Failed to emit DisputeFiled event: {e}")

    # §NOTIFV2 — a dispute was filed AGAINST you (defendant only; the complainant knows).
    try:
        import asyncio as _aio
        from agentvault_registry.background_tasks.push_notify import notify_agent_owners
        _aio.create_task(notify_agent_owners(
            "dispute.filed_against_you", [dispute_data.defendant_did],
            title="Dispute filed against your agent",
            message=f"Dispute #{dispute.id}: {complainant_did} vs {dispute_data.defendant_did}",
            tags="scales", priority="high", click="/ui/#/disputes"))
    except Exception:  # noqa: BLE001
        logger.debug("dispute notify skipped", exc_info=True)

    # Convert datetime to string for response
    return DisputeResponse(
        id=dispute.id,
        status=dispute.status,
        ruling=dispute.ruling,
        complainant_did=dispute.complainant_did,
        defendant_did=dispute.defendant_did,
        created_at=dispute.created_at.isoformat(),
        updated_at=dispute.updated_at.isoformat(),
        evidence=[],
        contract_id=getattr(dispute, "contract_id", None),
        contract_ref=getattr(dispute, "contract_ref", None),
    )


@router.get("/{dispute_id}", response_model=DisputeResponse)
async def get_dispute(
    dispute_id: int,
    actor: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve one dispute: with an agent token, a dispute the agent is a party to (complainant or respondent); with a
    developer token, a dispute one of the developer's agents is a party to, or any dispute for an administrator who
    rules on disputes; 403 otherwise.

    \f
    Retrieve details of a specific dispute.

    §POCKETBRIDGE5 A' (2026-08-23) — dual-auth, same pattern as
    GET /disputes/agent/{did}. The old developer-only gate produced an
    asymmetry measured live: an AGENT could FILE a dispute (POST /, agent JWT)
    and SUBMIT EVIDENCE on it (POST /{id}/evidence, agent JWT) but got 401
    reading the detail of its own case — the disputes tab expanded into
    "Could not validate credentials".

      - developer JWT: §SECFIX D6-465 (2026-10-16): a dispute one of the developer's agents is a party to, or any
        dispute for an administrator who rules on disputes (reads_every_dispute) → 403 otherwise. It used to be any
        dispute, evidence included, for any developer credential.
      - agent JWT: only a dispute the agent is a PARTY to (complainant or
        respondent) → 403 otherwise.
    """
    dispute = await crud_disputes.get_dispute_by_id(db=db, dispute_id=dispute_id)
    if not dispute:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Dispute with id {dispute_id} not found")
    if actor.get("kind") == "agent":
        me = (actor.get("agent_did") or "").lower()
        parties = {
            (getattr(dispute, "complainant_did", None) or "").lower(),
            (getattr(dispute, "defendant_did", None) or "").lower(),
        }
        if me not in parties:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Agents may only read disputes they are party to")
    else:
        dev = actor.get("developer")
        if not reads_every_dispute(dev) and not await developer_owns_one_of(
                db, getattr(dev, "id", None), [dispute.complainant_did, dispute.defendant_did]):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Only the owners of a dispute's parties, and administrators, may read it")
    return _serialize_dispute(dispute)


@router.post("/{dispute_id}/evidence", response_model=EvidenceResponse, status_code=status.HTTP_201_CREATED)
async def submit_evidence(
    dispute_id: int,
    evidence_data: EvidenceSubmit,
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(get_current_agent)
):
    """
    Submit evidence for a dispute.

    This endpoint allows authenticated agents involved in a dispute to submit
    evidence to support their claims. The submitter is derived from the
    authenticated agent's identity.
    """
    submitter_did = current_agent.did

    # First verify the dispute exists
    dispute = await crud_disputes.get_dispute_by_id(db=db, dispute_id=dispute_id)
    if not dispute:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispute with id {dispute_id} not found"
        )

    # Verify the submitter is involved in the dispute
    if submitter_did not in [dispute.complainant_did, dispute.defendant_did]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only agents involved in the dispute can submit evidence"
        )

    # Check if dispute is still open for evidence
    if dispute.status == "CLOSED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot submit evidence to a closed dispute"
        )

    # Add the evidence (D5: lock + re-check status; D9: cap at 10 per submitter)
    try:
        evidence = await crud_disputes.add_evidence_to_dispute(
            db=db,
            dispute_id=dispute_id,
            submitter_did=submitter_did,
            evidence_data=evidence_data.evidence_data
        )
    except ValueError as cap_err:
        # D9: Per-submitter cap reached
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(cap_err)
        )

    if not evidence:
        # D5: dispute closed between pre-check and insert (race) OR not found
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot submit evidence — dispute not found or closed during submission"
        )

    # OWL20-PREP: Emit EvidenceSubmitted to Event Store
    # D7: synchronous emit.
    # D15: aggregate_id="dispute:N", aggregate_type="Dispute" (normalized).
    try:
        _emitter = get_event_emitter()
        await _emitter.emit(
            event_type="EvidenceSubmitted",
            aggregate_id=f"dispute:{dispute_id}",
            aggregate_type="Dispute",
            data={
                "dispute_id": dispute_id,
                "evidence_id": evidence.id,
                "submitter_did": submitter_did
            }
        )
    except Exception as e:
        logger.warning(f"Failed to emit EvidenceSubmitted event: {e}")

    # A1 (2026-07-24): dispute.evidence_submitted was subscribable but never fired.
    import asyncio as _aio
    from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
    _aio.create_task(dispatch_webhook_for_agents(
        "dispute.evidence_submitted",
        {"dispute_id": dispute_id, "evidence_id": evidence.id, "submitter_did": submitter_did},
        [dispute.complainant_did, dispute.defendant_did], source_label="disputes.evidence"))

    return EvidenceResponse(
        id=evidence.id,
        dispute_id=evidence.dispute_id,
        submitter_did=evidence.submitter_did,
        evidence_data=evidence.evidence_data,
        created_at=evidence.created_at.isoformat()
    )


@router.get("/agent/{agent_did}", response_model=List[DisputeResponse])
async def get_agent_disputes(
    agent_did: str,
    role: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    actor: dict = Depends(get_current_actor_for_read),
):
    """
    Get all disputes involving a specific agent.

    D1 fix (2026-05-06, dual-auth revision): was zero-auth (live IDOR);
    now authenticated only:
      - agent JWT: caller may only query their OWN DID (self-only) → 403 if mismatch
      - developer JWT: an agent the developer owns, or any agent for an administrator who rules on disputes → 403
        otherwise (§SECFIX D6-465, 2026-10-16: it was any agent, evidence included)
    Anonymous → 401.

    Args:
        agent_did: DID of the agent
        role: Optional filter - "complainant" or "defendant"
    """
    # Self-only for an agent JWT; a developer JWT asks about its own agents (an administrator about any).
    if actor.get("kind") == "agent" and actor.get("agent_did") != agent_did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent JWTs may only query disputes for their own DID. "
                   "Use the owner's developer JWT."
        )
    if actor.get("kind") != "agent":
        dev = actor.get("developer")
        if not reads_every_dispute(dev) and not await developer_owns_one_of(db, getattr(dev, "id", None), [agent_did]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="A developer JWT may only query disputes for its own agents"
            )

    if role and role not in ["complainant", "defendant"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be either 'complainant' or 'defendant'"
        )

    disputes = await crud_disputes.get_disputes_by_agent(
        db=db, agent_did=agent_did, role=role
    )
    return [_serialize_dispute(d) for d in disputes]
