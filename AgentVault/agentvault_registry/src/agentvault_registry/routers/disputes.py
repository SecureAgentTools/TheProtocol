"""
API router for the Decentralized Dispute Resolution (DDR) system.

This module provides REST API endpoints for creating and managing disputes
between agents in the decentralized justice system.
"""

from decimal import Decimal
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
def _serialize_dispute(dispute, parties: Optional[Dict[str, Dict[str, Any]]] = None,
                       detail: Optional[Dict[str, Any]] = None) -> "DisputeResponse":
    """Shared serialization for dispute + evidence. V0657 (a): the parties' names, owners and homes (`parties`, from
    services/dispute_parties), why it opened, who ruled and why, and what the ruling did; a single read adds `detail`
    (the linked Guild order's evidence and the corrections)."""
    from ..services.dispute_rules import REASONS
    parties = parties or {}
    c = parties.get(dispute.complainant_did) or {}
    d_ = parties.get(dispute.defendant_did) or {}
    detail = detail or {}
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
        guild_order_id=getattr(dispute, "guild_order_id", None),
        reason=getattr(dispute, "reason", None),
        reason_text=REASONS.get(getattr(dispute, "reason", None) or ""),
        filed_by=getattr(dispute, "filed_by", None),
        amount_claimed=(str(dispute.amount_claimed) if getattr(dispute, "amount_claimed", None) is not None else None),
        ruled_by=getattr(dispute, "ruled_by", None),
        ruled_at=(dispute.ruled_at.isoformat() if getattr(dispute, "ruled_at", None) else None),
        ruling_note=getattr(dispute, "ruling_note", None),
        outcome=getattr(dispute, "outcome", None),
        complainant_name=c.get("name"),
        defendant_name=d_.get("name"),
        parties={"complainant": c, "defendant": d_} if parties else None,
        guild_order=detail.get("guild_order"),
        corrections=detail.get("corrections"),
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
    # V0657 (a), item 2: what the complainant claims, set here and nowhere else. A ruling for the complainant may move
    # it from the defendant's wallet (the ruler sees it before the click); free-form evidence keys no longer do.
    amount_claimed: Optional[Decimal] = Field(
        default=None, gt=0, max_digits=38, decimal_places=18,
        description="The amount the complainant claims; a ruling in its favour may move it from the defendant's wallet",
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
    # V0657 (a), disputes v2: the Guild order it is about, why it opened and who filed it, the complainant's explicit
    # claim, who ruled, when and why, and what the ruling did; the parties by name (items 5, 9, 10, 22)
    guild_order_id: Optional[str] = None
    reason: Optional[str] = None
    reason_text: Optional[str] = None
    filed_by: Optional[str] = None
    amount_claimed: Optional[str] = None
    ruled_by: Optional[int] = None
    ruled_at: Optional[str] = None
    ruling_note: Optional[str] = None
    outcome: Optional[Dict[str, Any]] = None
    complainant_name: Optional[str] = None
    defendant_name: Optional[str] = None
    parties: Optional[Dict[str, Any]] = None
    # a single read only: the linked Guild order as evidence (item 8), and the ruling's corrections
    guild_order: Optional[Dict[str, Any]] = None
    corrections: Optional[List[Dict[str, Any]]] = None

    class Config:
        from_attributes = True


async def _parties_of(db: AsyncSession, disputes) -> Dict[str, Dict[str, Any]]:
    """The parties of these disputes by name, owner and home (services/dispute_parties). A dispute is read without
    names rather than not at all."""
    from ..services.dispute_parties import parties
    dids = []
    for d in disputes:
        dids += [d.complainant_did, d.defendant_did]
    try:
        return await parties(db, dids)
    except Exception as e:  # noqa: BLE001
        logger.warning("dispute parties unreadable: %s", e)
        return {}


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


async def _detail(db: AsyncSession, dispute) -> Dict[str, Any]:
    """A single read's evidence (item 8): the linked Guild order (its spec, the award, the hand-in or that there was
    none, the deadline, its events, its room thread, the escrow) and the ruling's corrections. Best effort: a dispute
    is read without them rather than not at all."""
    from sqlalchemy import text as _t
    out: Dict[str, Any] = {}
    try:
        from ..services.dispute_settlement import handed_in, linked_guild_order
        o = await linked_guild_order(db, dispute)
        if o is not None:
            bid = None
            if o.get("awarded_bid_id"):
                b = (await db.execute(_t("SELECT bidder_did, price, eta_seconds, pitch, stake_amount, created_at "
                                         "FROM guild_bids WHERE id=:b"), {"b": o["awarded_bid_id"]})).mappings().first()
                if b:
                    bid = {k: (str(v) if k in ("price", "stake_amount") and v is not None else _iso(v))
                           for k, v in dict(b).items()}
            events = (await db.execute(_t("SELECT seq, event_type, actor_did, payload, created_at FROM guild_order_events "
                                          "WHERE order_id=:o ORDER BY seq"), {"o": o["id"]})).mappings().all()
            held = o.get("status") in ("open", "awarded", "submitted", "disputed", "resolving", "settling")
            out["guild_order"] = {
                "id": o["id"], "title": o.get("title"), "spec": o.get("spec"), "status": o.get("status"),
                "bounty": str(o.get("bounty")), "currency": o.get("currency"),
                "escrow_held": str(o.get("bounty")) if held else "0",
                "poster_did": o.get("poster_did"), "worker_did": o.get("worker_did"), "payee_did": o.get("payee_did"),
                "deadline": _iso(o.get("deadline")), "created_at": _iso(o.get("created_at")),
                "awarded_at": _iso(o.get("awarded_at")), "submitted_at": _iso(o.get("submitted_at")),
                "settled_at": _iso(o.get("settled_at")),
                "handed_in": handed_in(o), "deliverable": o.get("deliverable"),
                "awarded_bid": bid, "announce_conversation_id": o.get("announce_conversation_id"),
                "events": [{"seq": e["seq"], "event_type": e["event_type"], "actor_did": e["actor_did"],
                            "payload": e["payload"], "created_at": _iso(e.get("created_at"))} for e in events],
            }
    except Exception as e:  # noqa: BLE001
        logger.warning("dispute %s: the linked order could not be read: %s", getattr(dispute, "id", "?"), e)
    try:
        rows = (await db.execute(_t("SELECT id, from_ruling, to_ruling, note, corrected_by, corrected_at, status, "
                                    "finished_at FROM dispute_corrections WHERE dispute_id=:d ORDER BY id"),
                                 {"d": dispute.id})).mappings().all()
        out["corrections"] = [{**dict(r), "corrected_at": _iso(r.get("corrected_at")),
                               "finished_at": _iso(r.get("finished_at"))} for r in rows]
    except Exception as e:  # noqa: BLE001
        logger.warning("dispute %s: corrections unreadable: %s", getattr(dispute, "id", "?"), e)
    return out


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
    §SECFIX D6-465 (2026-10-16): this listed every dispute of the registry, evidence included, to any
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
    parties = await _parties_of(db, disputes)
    return [_serialize_dispute(d, parties) for d in disputes]


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
        reason="filed_by_party", filed_by="party", amount_claimed=dispute_data.amount_claimed,
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

    # §NOTIFV2: the defendant hears of it from crud_disputes.create_dispute since V0657 (a), which tells every filing's
    # parties and its rulers (the complainant knows: it filed).

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
    return _serialize_dispute(dispute, await _parties_of(db, [dispute]), await _detail(db, dispute))


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

    return await _record_evidence(db, dispute, submitter_did, evidence_data.evidence_data)


async def _record_evidence(db: AsyncSession, dispute, submitter_did: str, evidence_data: Dict[str, Any],
                           owner_developer_id: Optional[int] = None) -> "EvidenceResponse":
    """Record one piece of evidence as `submitter_did`, a party already checked by the caller: the open-dispute rule,
    the per-submitter cap, the ledger event and the webhook. One recording for the agent's route and the owner's
    (V0658 (d)), so the two cannot drift. `owner_developer_id` names the owner who filed it for the party."""
    dispute_id = dispute.id
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
            evidence_data=evidence_data
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
                "submitter_did": submitter_did,
                **({"filed_by_owner_developer_id": owner_developer_id} if owner_developer_id is not None else {}),
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


class OwnerEvidenceSubmit(EvidenceSubmit):
    """V0658 (d): evidence an owner files for one of their agents that is a party. `agent_did` names which party when
    the caller owns both; with one owned party it may be left out."""
    agent_did: Optional[str] = Field(None, max_length=512, description="the owned party to file as")


@router.post("/{dispute_id}/evidence/as-owner", response_model=EvidenceResponse, status_code=status.HTTP_201_CREATED)
async def submit_evidence_as_owner(
    dispute_id: int,
    body: OwnerEvidenceSubmit,
    db: AsyncSession = Depends(get_db),
    current_developer=Security(get_current_developer),
):
    """Evidence from the owner of a party, filed AS that party (V0658 (d), polish 15 of the disputes discovery).

    The agent's own route takes an agent token only, so an owner reading the dispute in the console could not add to
    it without acting as the agent. Here the owner's developer credential files it for an agent they own that is a
    complainant or defendant: the agent's DID is the submitter, through the same recording (the open-dispute rule and
    the per-submitter cap). An owner of both parties names which one; an owner of neither is refused."""
    dispute = await crud_disputes.get_dispute_by_id(db=db, dispute_id=dispute_id)
    if not dispute:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Dispute with id {dispute_id} not found")
    parties = [d for d in (dispute.complainant_did, dispute.defendant_did) if d]
    from sqlalchemy import select as _select
    owned = set((await db.execute(_select(Agent.did).where(
        Agent.creator_developer_id == getattr(current_developer, "id", None), Agent.did.in_(parties)))).scalars())
    if body.agent_did:
        if body.agent_did not in parties or body.agent_did not in owned:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="agent_did must be a party to this dispute that you own")
        submitter_did = body.agent_did
    elif not owned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only the owners of a dispute's parties may add evidence for them")
    elif len(owned) > 1:
        raise HTTPException(status_code=422,
                            detail="You own both parties: name the one you file for in agent_did")
    else:
        submitter_did = next(iter(owned))
    return await _record_evidence(db, dispute, submitter_did, body.evidence_data,
                                  owner_developer_id=getattr(current_developer, "id", None))


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
    parties = await _parties_of(db, disputes)
    return [_serialize_dispute(d, parties) for d in disputes]
