"""
LEGACY CONTRACTS SURFACE (RUC) — **thin adapter over THE CONTRACT SPINE since P2 (2026-07-25)**.

Every route, request model, response shape and status code below is the original RUC API — the
10 public MCP tools, `views/Contracts.vue`, the api-tester shapes and the cross-registry proxy all
keep working unchanged. The BODIES now delegate to the spine (`contracts` tables +
`services/contract_settlement`), which closes the RUC's defects in place:

  M1  money is now ESCROWED AT ACCEPT (`ctrref:{cid}:hold`) — accept can 402 on an empty client
      wallet, which is the point: the provider never works uncovered again.
  M2  the slash→compensate→manual-refund fallback is GONE — settlement is milestone release on
      the shared escrow rail (local legs, or the guild-proven stage-through-client xreg saga).
  M7  no manual liquid_balance write-back — TEG is the source of truth, the outbox syncs.
  M8  GET /{id} no longer fires a webhook (reads never emit).

Adapter mapping: RUC PROPOSED⇄offered · ACCEPTED⇄agreed · IN_PROGRESS/PENDING_MERGE⇄in_progress
(PENDING_MERGE = milestone 1 submitted) · COMPLETED⇄completed · FAILED⇄cancelled/expired ·
DISPUTED⇄disputed. Legacy int ids ride `contracts.legacy_ruc_id` (new rows draw from
`contracts_legacy_id_seq`); this surface lists ONLY legacy-id rows — the v2 surface is
/api/v1/contracts/v2. NOT gated by CONTRACTS_V2_ENABLED: the legacy API keeps working fleet-wide.

`approve-completion`'s optional A2A `payment_token` is accepted but NO LONGER SETTLED — settling it
would double-pay on top of the escrow release. The token is left to its 15-minute expiry (the a2a
expiry worker reclaims it); callers should stop sending it.
"""

from typing import List, Dict, Any, Optional, Union
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Request, status, Security
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel, Field, field_validator
import json
import os
import secrets
import logging

from ..database import get_db
from ..models import Agent
from ..event_emitter import get_event_emitter
from .utils import get_current_agent
from agentvault_registry.security import require_agent_permission, enforce_agent_spend  # IRONKEY
from ..security import get_current_actor_for_read
from ..services import contract_settlement as cs
from ..services import escrow as escrow_rail
from ..services import reputation_bond as _rb
from ..services import enforcement_propagation as _ep  # §ENFPROP
from .contracts_v2 import mint_contract

logger = logging.getLogger(__name__)

event_emitter = get_event_emitter()

_FRAME_CCY = (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"


# ── request/response models (VERBATIM legacy shapes) ─────────────────────────────────────────

class ContractCreate(BaseModel):
    """Request model for creating a new RUC."""
    client_agent_did: str = Field(..., max_length=120, description="DID of the agent requesting the work")
    scope_description: str = Field(..., max_length=5000, min_length=10, description="Description of the work to be done")
    source_code_repo_url: str = Field(..., max_length=500, description="Git repository URL of the Client Agent's code")
    source_code_branch: str = Field(..., max_length=200, description="Specific branch to work on")
    acceptance_criteria: Dict[str, Any] = Field(..., description="JSON defining conditions for success")
    payment_amount: int = Field(..., description="Agreed payment for successful completion", gt=0, le=10_000_000)

    @field_validator("scope_description")
    @classmethod
    def sanitize_description(cls, v):
        from agentvault_registry.input_validators import validate_safe_text
        sanitized = validate_safe_text(v, "scope_description")
        if len(sanitized.strip()) < 10:
            raise ValueError("scope_description must be at least 10 characters after sanitization")
        return sanitized

    @field_validator("client_agent_did")
    @classmethod
    def _validate_client_did(cls, v):
        from agentvault_registry.input_validators import validate_did
        return validate_did(v)

    @field_validator("source_code_repo_url")
    @classmethod
    def _validate_repo_url(cls, v):
        from agentvault_registry.input_validators import validate_repo_url
        return validate_repo_url(v)

    @field_validator("source_code_branch")
    @classmethod
    def _validate_branch(cls, v):
        from agentvault_registry.input_validators import validate_branch_name
        return validate_branch_name(v)


class ContractAccept(BaseModel):
    """Request model for accepting a contract."""
    upgrader_agent_did: str = Field(..., max_length=120, description="DID of the agent accepting the work")

    @field_validator("upgrader_agent_did")
    @classmethod
    def _validate_upgrader_did(cls, v):
        from agentvault_registry.input_validators import validate_did
        return validate_did(v)


class ContractSubmit(BaseModel):
    """Request model for submitting completed work."""
    pr_url: str = Field(..., max_length=500, description="URL of the pull request containing the work")

    @field_validator("pr_url")
    @classmethod
    def _validate_pr_url(cls, v):
        from agentvault_registry.input_validators import validate_repo_url
        return validate_repo_url(v)


class ContractMarkFailed(BaseModel):
    """Request model for marking a contract as FAILED."""
    reason: Optional[str] = Field(None, max_length=500, description="Reason for failure")


class ContractApproveRequest(BaseModel):
    """Optional request body for approve-completion. `payment_token` is accepted for backward
    compatibility but NOT settled — settlement is the escrow release (see module docstring)."""
    payment_token: Optional[str] = Field(None, description="A2A payment token (legacy; ignored for settlement)")


class ContractResponse(BaseModel):
    """Response model for a contract."""
    id: int
    # §BLOGSHOTS-FIX (2026-07-27): the spine id (ctr_…), always set. Spine-native rows have no
    # legacy_ruc_id (id serialises as -1) — clients address those via ref. Additive.
    ref: Optional[str] = None
    client_agent_did: str
    upgrader_agent_did: Optional[str]
    status: str
    scope_description: str
    source_code_repo_url: str
    source_code_branch: str
    acceptance_criteria: Dict[str, Any]
    payment_amount: int
    currency: str = _FRAME_CCY
    payment_transaction_id: Optional[str] = None
    access_credentials_id: Optional[str]
    pr_url: Optional[str]
    created_at: str
    updated_at: str
    accepted_at: Optional[str]
    completed_at: Optional[str]

    class Config:
        from_attributes = True


router = APIRouter(
    prefix="/api/v1/contracts",
    tags=["Contracts"],
    responses={404: {"description": "Not found"}},
)


# ── adapter core ─────────────────────────────────────────────────────────────────────────────

async def _resolve(db: AsyncSession, contract_id) -> Optional[dict]:
    """Legacy int id → spine row via legacy_ruc_id; 'ctr_…' string accepted too."""
    s = str(contract_id)
    if s.startswith("ctr_"):
        return await cs.load_contract(db, s)
    if not s.lstrip("-").isdigit():
        return None
    row = (await db.execute(text(
        "SELECT * FROM contracts WHERE legacy_ruc_id=:i"), {"i": int(s)})).mappings().first()
    return dict(row) if row else None


async def _m1(db: AsyncSession, cid: str) -> Optional[dict]:
    return await cs.load_milestone(db, cid, 1)


def _legacy_status(c: dict, m1: Optional[dict]) -> str:
    st = c["status"]
    if st in ("draft", "offered"):
        return "PROPOSED"
    if st == "agreed":
        return "ACCEPTED"
    if st == "in_progress":
        return "PENDING_MERGE" if (m1 and m1["status"] in ("submitted", "releasing")) else "IN_PROGRESS"
    if st == "completed":
        return "COMPLETED"
    if st == "disputed":
        return "DISPUTED"
    return "FAILED"  # cancelled | expired


def _to_response(c: dict, m1: Optional[dict]) -> ContractResponse:
    t = c.get("terms") or {}
    if isinstance(t, str):
        try:
            t = json.loads(t)
        except Exception:  # noqa: BLE001
            t = {}
    pr = t.get("pr_url")
    if not pr and m1 and isinstance(m1.get("deliverable"), dict):
        pr = m1["deliverable"].get("pr_url")
    created = c["created_at"]
    updated = c.get("updated_at") or created
    return ContractResponse(
        id=int(c["legacy_ruc_id"]) if c.get("legacy_ruc_id") is not None else -1,
        ref=c.get("id"),
        client_agent_did=c["client_did"],
        upgrader_agent_did=c.get("provider_did"),
        status=_legacy_status(c, m1),
        scope_description=str(t.get("scope_description") or c.get("title") or ""),
        source_code_repo_url=str(t.get("repo_url") or ""),
        source_code_branch=str(t.get("branch") or ""),
        acceptance_criteria=t.get("acceptance_criteria") or {},
        payment_amount=int(Decimal(str(c["total_amount"]))),
        currency=c.get("currency") or _FRAME_CCY,
        payment_transaction_id=t.get("legacy_payment_transaction_id"),
        access_credentials_id=t.get("access_credentials_id"),
        pr_url=pr,
        created_at=created.isoformat(),
        updated_at=updated.isoformat(),
        accepted_at=c["agreed_at"].isoformat() if c.get("agreed_at") else None,
        completed_at=c["completed_at"].isoformat() if c.get("completed_at") else None,
    )


def _fire_contract_webhook(event: str, c: dict, extra: dict = None) -> None:
    """Legacy-named webhook fan-out to both parties (A1). Fire-and-forget; reads never call this."""
    import asyncio as _aio
    from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
    data = {"contract_id": c.get("legacy_ruc_id"), "spine_contract_id": c["id"],
            "status": c.get("status"), "client_agent_did": c["client_did"],
            "upgrader_agent_did": c.get("provider_did"), **(extra or {})}
    dids = [d for d in (c["client_did"], c.get("provider_did")) if d]
    _aio.create_task(dispatch_webhook_for_agents(event, data, dids, source_label="contracts"))


async def _emit_legacy(event_type: str, c: dict, **extra):
    """Legacy ES event types (policy rows exist, emit_from_registry=t) — kept for ledger
    continuity alongside the spine's own Contract* events."""
    try:
        await event_emitter.emit(
            event_type=event_type, aggregate_id=c["client_did"], aggregate_type="Contract",
            data={"contract_id": c.get("legacy_ruc_id"), "spine_contract_id": c["id"],
                  "client_agent_did": c["client_did"], "upgrader_agent_did": c.get("provider_did"),
                  "payment_amount": str(c["total_amount"]), "status": c.get("status"), **extra})
    except Exception as e:  # noqa: BLE001
        logger.error(f"Event Store contract emit error: {e}")


async def _patch_terms(db: AsyncSession, cid: str, patch: dict) -> None:
    await db.execute(text(
        "UPDATE contracts SET terms = COALESCE(terms,'{}'::jsonb) || CAST(:p AS JSONB), "
        "updated_at=now() WHERE id=:c"), {"p": json.dumps(patch), "c": cid})


# ── mutation endpoints (legacy paths, spine bodies) ──────────────────────────────────────────

@router.post("/", response_model=ContractResponse, status_code=status.HTTP_201_CREATED)
async def create_contract(
    contract_data: ContractCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(require_agent_permission("contracts.engage"))
):
    """Create a contract (legacy RUC shape). The client_agent_did must match the caller."""
    if contract_data.client_agent_did != current_agent.did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="client_agent_did must match your authenticated agent DID"
        )
    if not isinstance(contract_data.acceptance_criteria, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Acceptance criteria must be a valid JSON object"
        )
    # §SUBAGENT-LIABILITY P1 — a hand's contract is the PRINCIPAL's. Book the client (the payer whose
    # escrow funds it, see _do_accept → escrow_deposit(client_did)) as the wallet-holding principal;
    # the acting hand stays actor_did and is recorded as evidence by the anchor seam. Byte-INERT when
    # the anchor is off or no hand acted: resolve_spend_purse_agent returns the caller itself, so
    # client_did == current_agent.did and nothing about a normal agent's contract changes.
    from agentvault_registry.services.spawn_anchor import resolve_spend_purse_agent
    _purse, client_did = await resolve_spend_purse_agent(db, current_agent, request)
    if client_did != current_agent.did:  # a walletless hand is binding its principal → gate the principal
        from ..services import liability as liab
        # §FACTS2 — currency is the frame's here because `mint_contract` REFUSES any
        # other for a locally-authored contract (it validates against _FRAME_CCY), so
        # this is the currency the row about to be written will carry, not a guess.
        # counterparty_did is None ON PURPOSE and passed EXPLICITLY: at create the work
        # is being posted and nobody has accepted it, so there genuinely is no other
        # party yet. Declaring that is different from forgetting to — the builder
        # refuses an undeclared counterparty on a money fact, which is what catches a
        # future call site that simply omits it.
        await liab.check_liability_gate(db, client_did, "contracts.engage",
                                        action_ref="contract-create",
                                        amount=contract_data.payment_amount,
                                        currency=liab.frame_currency(),
                                        counterparty_did=None,
                                        acting_hand_did=current_agent.did,
                                        presence=liab.presence_from_request(request))
    legacy_id = (await db.execute(text("SELECT nextval('contracts_legacy_id_seq')"))).scalar()
    c = await mint_contract(
        db, client_did=client_did,
        title=f"RUC #{legacy_id}: {contract_data.scope_description[:150]}",
        total_amount=Decimal(contract_data.payment_amount),
        contract_type="work_order",
        terms={"scope_description": contract_data.scope_description,
               "repo_url": contract_data.source_code_repo_url,
               "branch": contract_data.source_code_branch,
               "acceptance_criteria": contract_data.acceptance_criteria},
        origin_surface="api", legacy_ruc_id=int(legacy_id),
        actor_did=current_agent.did, request=request)
    await _emit_legacy("ContractCreated", c,
                       scope_description=contract_data.scope_description[:200])
    _fire_contract_webhook("contract.created", c)
    return _to_response(c, await _m1(db, c["id"]))


@router.post("/{contract_id}/accept", response_model=ContractResponse)
async def accept_contract(
    contract_id: str,
    accept_data: ContractAccept,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(require_agent_permission("contracts.engage"))
):
    """Accept a proposed contract as the Upgrader Agent. **Escrows the client's funds**: answers 402
    when the client's balance does not cover the payment."""
    if accept_data.upgrader_agent_did != current_agent.did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("upgrader_agent_did must match your authenticated agent DID. A provider homed on another "
                    "registry accepts there (POST /api/v1/contracts/v2/{cid}/accept), which carries it here.")
        )
    c = await _resolve(db, contract_id)
    if not c or c["status"] not in ("offered", "draft"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Contract {contract_id} not found or not in PROPOSED status"
        )
    # §SUBAGENT-LIABILITY P1 — a hand's contract is the PRINCIPAL's: the PROVIDER of record (who is
    # paid at release and answerable for delivery) is the wallet-holding principal, not the walletless
    # hand. Byte-INERT when the anchor is off / no hand: provider_did == current_agent.did.
    from agentvault_registry.services.spawn_anchor import resolve_spend_purse_agent
    _purse, provider_did = await resolve_spend_purse_agent(db, current_agent, request)
    if c["client_did"] in (current_agent.did, provider_did):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="A client cannot accept their own contract")
    # §REPBOND — accepting as the provider is a provider act: the bond and enforcement gates apply here as at the v2
    # accept (contracts_v2.accept_contract_v2). This door skipped both, so under REPUTATION_BOND_MODE=enforce an agent
    # with no bond took an escrowed contract here while the v2 accept refused it (sbx-alpha 2026-10-24: v2 403, this
    # route 200). The provider of record is gated: the principal when a hand accepts for it.
    await _rb.gate(db, provider_did, site="contract_accept")
    await _ep.gate(db, provider_did, site="contract_accept")
    if provider_did != current_agent.did:  # a hand is agreeing to deliver for its principal → gate it
        from ..services import liability as liab
        # §FACTS2 — the accepting side's counterparty is the CLIENT (who will pay).
        # Currency from the contract row, which already exists at accept.
        await liab.check_liability_gate(db, provider_did, "contracts.engage",
                                        action_ref=f"contract-accept:{contract_id}",
                                        amount=c["total_amount"],
                                        currency=c.get("currency") or liab.frame_currency(),
                                        counterparty_did=c.get("client_did"),
                                        counterparty_home_registry=c.get("counterparty_home_registry"),
                                        acting_hand_did=current_agent.did,
                                        presence=liab.presence_from_request(request))
    out = await _do_accept(db, c, provider_did=provider_did, via=None)
    await _emit_legacy("ContractAccepted", out, accepted_by=current_agent.did)
    _fire_contract_webhook("contract.accepted", out)
    return _to_response(out, await _m1(db, out["id"]))


async def _do_accept(db: AsyncSession, c: dict, *, provider_did: str,
                     via: Optional[str]) -> dict:
    """Shared local/federated accept: claim → escrow → credentials. Guild-doctrine ordering."""
    cid = c["id"]
    res = await db.execute(text(
        "UPDATE contracts SET status='agreed', provider_did=:p, agreed_at=now(), "
        "counterparty_home_registry=:hr, updated_at=now() "
        "WHERE id=:c AND status IN ('offered','draft') AND (provider_did IS NULL OR provider_did=:p)"),
        {"c": cid, "p": provider_did, "hr": via})
    if getattr(res, "rowcount", 0) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Contract not found or not in PROPOSED status")
    await cs.audit(db, cid, await cs.next_seq(db, cid), "agreed", provider_did,
                   {"via": via or "local"})
    await db.commit()
    total = Decimal(str(c["total_amount"]))
    if total > 0:
        try:
            await escrow_rail.escrow_deposit(c["client_did"], total, f"ctrref:{cid}:hold",
                                             reason="contract_escrow")
            await db.execute(text("UPDATE contracts SET escrow_ref=:r WHERE id=:c"),
                             {"r": f"ctrref:{cid}", "c": cid})
            await cs.audit(db, cid, await cs.next_seq(db, cid), "escrowed", None,
                           {"amount": str(total)})
            await db.commit()
        except escrow_rail.EscrowError as e:
            await db.execute(text(
                "UPDATE contracts SET status='offered', provider_did=NULL, agreed_at=NULL, "
                "counterparty_home_registry=NULL, updated_at=now() "
                "WHERE id=:c AND status='agreed' AND escrow_ref IS NULL"), {"c": cid})
            await cs.audit(db, cid, await cs.next_seq(db, cid), "escrow_failed", provider_did,
                           {"error": e.message[:300]})
            await db.commit()
            from agentvault_registry.services.ledger_unavailable import refusal_from_error  # §LEDGERGATE (V0598)
            raise refusal_from_error(e) or HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Escrow failed (client has insufficient balance?): {e.message}")
    access_credentials_id = f"cred_{secrets.token_hex(16)}"
    await _patch_terms(db, cid, {"access_credentials_id": access_credentials_id})
    await db.commit()
    out = await cs.load_contract(db, cid)
    cs.emit("ContractAgreed", cid, {"client": c["client_did"], "provider": provider_did,
                                    "total": str(total), "via": via or "local"})
    # §DEALTHREADS — the federated accept LANDS HERE at home, where the deal
    # thread lives (existing thread only; best-effort; exactly-once by ref).
    from agentvault_registry.services import deal_thread_events as dte
    await dte.post_accepted(db, out)
    return out


@router.post("/{contract_id}/submit", response_model=ContractResponse)
async def submit_contract_work(
    contract_id: str,
    submit_data: ContractSubmit,
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(require_agent_permission("contracts.engage"))
):
    """Submit completed work (milestone 1 delivery). Only the assigned upgrader."""
    c = await _resolve(db, contract_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Contract {contract_id} not found")
    if c["provider_did"] != current_agent.did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Only the assigned upgrader can submit work. A provider homed on another registry delivers "
                    "there (POST /api/v1/contracts/v2/{cid}/milestones/{seq}/submit), which carries it here.")
        )
    out = await _do_submit(db, c, submit_data.pr_url, actor=current_agent.did, via=None)
    await _emit_legacy("ContractWorkSubmitted", out, pr_url=submit_data.pr_url,
                       submitted_by=current_agent.did)
    return _to_response(out, await _m1(db, out["id"]))


async def _do_submit(db: AsyncSession, c: dict, pr_url: str, *, actor: str,
                     via: Optional[str]) -> dict:
    cid = c["id"]
    if c["status"] not in ("agreed", "in_progress"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Contract not in correct status for submission")
    res = await db.execute(text(
        "UPDATE contract_milestones SET status='submitted', submitted_at=now(), "
        "deliverable=CAST(:d AS JSONB) WHERE contract_id=:c AND seq=1 "
        "AND status IN ('pending','submitted')"),
        {"c": cid, "d": json.dumps({"pr_url": pr_url})})
    if getattr(res, "rowcount", 0) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Contract not in correct status for submission")
    await db.execute(text(
        "UPDATE contracts SET status='in_progress', updated_at=now() WHERE id=:c AND status='agreed'"),
        {"c": cid})
    await _patch_terms(db, cid, {"pr_url": pr_url})
    await cs.audit(db, cid, await cs.next_seq(db, cid), "milestone_submitted", actor,
                   {"seq": 1, "via": via or "local"})
    await db.commit()
    out = await cs.load_contract(db, cid)
    cs.emit("ContractMilestoneSubmitted", cid, {"seq": 1, "by": actor})
    cs.webhook("contract.milestone_submitted", out, {"seq": 1})
    # §DEALTHREADS — delivery card (covers the FEDERATED submit; existing thread only)
    from agentvault_registry.services import deal_thread_events as dte
    await dte.post_milestone(db, out, 1)
    return out


@router.post("/{contract_id}/approve-completion", response_model=ContractResponse)
async def approve_contract_completion(
    contract_id: str,
    request: Request = None,
    body: Optional[ContractApproveRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(require_agent_permission("contracts.engage"))
):
    """Approve completion → release milestone 1 from ESCROW (the client's funds were locked at
    accept). Idempotent: an already-COMPLETED contract returns 200 with its current state; a
    crash-stranded release re-drives (TEG rail keys dedup already-ran legs).

    Legacy `payment_token` is accepted but never settled: the escrow release IS the payment."""
    c = await _resolve(db, contract_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Contract {contract_id} not found")
    if c["client_did"] != current_agent.did:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only the client can approve completion")
    if body and body.payment_token:
        logger.info("[CONTRACT-ADAPTER] %s: payment_token supplied — ignored (escrow release is "
                    "the settlement; token will expire unsettled)", c["id"])
    if c["status"] == "completed":
        return _to_response(c, await _m1(db, c["id"]))
    m1 = await _m1(db, c["id"])
    if not m1 or c["status"] not in ("agreed", "in_progress"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Contract not in correct status for approval")
    if Decimal(str(m1["amount"])) > 0 and not c.get("escrow_ref"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="No escrow is held for this contract (legacy pre-spine row) — "
                                   "cancel and re-create it")
    auth_header = request.headers.get("Authorization", "") if request else ""
    if m1["status"] == "submitted":
        res = await db.execute(text(
            "UPDATE contract_milestones SET status='releasing' WHERE contract_id=:c AND seq=1 "
            "AND status='submitted'"), {"c": c["id"]})
        if getattr(res, "rowcount", 0) > 0:
            await cs.audit(db, c["id"], await cs.next_seq(db, c["id"]), "releasing",
                           current_agent.did, {"seq": 1})
            await db.commit()
        m1 = await _m1(db, c["id"])
    if m1["status"] == "releasing":
        try:
            await cs.drive_release(db, c, m1, actor_did=current_agent.did,
                                   auth_header=auth_header)
        except escrow_rail.EscrowError as e:
            from agentvault_registry.services.ledger_unavailable import refusal_from_error  # §LEDGERGATE (V0598)
            raise refusal_from_error(e) or HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                                                         detail=f"Settlement failed: {e.message}")
    elif m1["status"] != "released":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Contract not in correct status for approval "
                                   f"(work not submitted yet?)")
    out = await cs.load_contract(db, c["id"])
    await _emit_legacy("ContractCompleted", out, approved_by=current_agent.did)
    _fire_contract_webhook("contract.completed", out)
    return _to_response(out, await _m1(db, out["id"]))


@router.post("/{contract_id}/mark-failed", response_model=ContractResponse)
async def mark_contract_failed(
    contract_id: str,
    body: ContractMarkFailed,
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(require_agent_permission("contracts.engage")),
):
    """Mark FAILED (legacy X11 semantics): either party, from ACCEPTED/IN_PROGRESS/PENDING_MERGE/
    DISPUTED → the spine cancels and REFUNDS the unreleased escrow to the client."""
    c = await _resolve(db, contract_id)
    if not c:
        raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found")
    if current_agent.did not in (c["client_did"], c.get("provider_did")):
        raise HTTPException(
            status_code=403,
            detail="Only contract parties (client or upgrader) can mark a contract FAILED")
    if c["status"] not in ("agreed", "in_progress", "disputed"):
        raise HTTPException(
            status_code=400,
            detail=f"Contract {contract_id} cannot be failed from status "
                   f"{_legacy_status(c, await _m1(db, c['id']))}")
    # GRIEFING GUARD (2026-07-25 dispute-wiring audit): with real escrow, letting the CLIENT
    # mark-failed from DISPUTED is a self-serve full refund over the provider's contested work
    # (reject → disputed → mark-failed). From disputed, only the PROVIDER may concede (refund to
    # client is against their own interest) — the client's path is the ruling / admin resolve.
    if c["status"] == "disputed" and current_agent.did == c["client_did"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Disputed contracts resolve via the dispute ruling or admin resolution — "
                   "the client cannot self-cancel over contested work")
    # §MCPTEST30 (2026-10-01): the v2 cancel's rule, which this legacy door skipped. The CLIENT cannot fail a contract
    # out from under delivered work (a milestone `submitted` and awaiting review: the refund below returned the whole
    # unreleased escrow, that milestone's amount included, while the client kept the delivery); and NOBODY cancels
    # while a milestone is `releasing` (a release in flight, or a cross-registry stage held for admin with its funds
    # already with the client: refunding it again pays twice).
    pending = dict((await db.execute(text(
        "SELECT status, COUNT(*) FROM contract_milestones WHERE contract_id=:c AND status IN ('submitted','releasing') "
        "GROUP BY status"), {"c": c["id"]})).all())
    if pending.get("releasing"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="A milestone release is in flight; the contract cannot be failed until it settles")
    if pending.get("submitted") and current_agent.did == c["client_did"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Deliveries are awaiting review — release or reject them first")
    res = await db.execute(text(
        "UPDATE contracts SET status='cancelled', cancelled_at=now(), updated_at=now() "
        "WHERE id=:c AND status IN ('agreed','in_progress','disputed')"), {"c": c["id"]})
    if getattr(res, "rowcount", 0) == 0:
        raise HTTPException(status_code=400, detail="Failed to mark contract FAILED")
    await cs.audit(db, c["id"], await cs.next_seq(db, c["id"]), "cancelling", current_agent.did,
                   {"legacy": "mark-failed", "reason": (body.reason or "")[:300]})
    await db.commit()
    refunded = await cs.refund_remainder(db, c, leg="refund")
    await cs.audit(db, c["id"], await cs.next_seq(db, c["id"]), "cancelled", current_agent.did,
                   {"refunded": str(refunded)})
    await db.commit()
    out = await cs.load_contract(db, c["id"])
    await _emit_legacy("ContractFailed", out, failed_by=current_agent.did,
                       reason=(body.reason or "")[:500])
    cs.emit("ContractCancelled", c["id"], {"by": current_agent.did, "refunded": str(refunded)})
    _fire_contract_webhook("contract.disputed", out,
                           {"failed_by": current_agent.did, "reason": (body.reason or "")[:200]})
    return _to_response(out, await _m1(db, out["id"]))


# ── read endpoints ───────────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[ContractResponse])
async def list_available_contracts(
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """
    List the open offers on both contract surfaces. An open offer names no provider yet; a private offer to a named
    provider is not listed.

    \f
    List open offers — BOTH surfaces (§BLOGSHOTS-FIX 2026-07-27: the legacy_ruc_id filter made
    every spine-native contract invisible to the FE). Open market = no provider named yet; a
    private offer with a named provider is deliberately NOT browsable (it never should have
    been).
    """
    if limit > 100:
        limit = 100
    rows = (await db.execute(text(
        "SELECT * FROM contracts WHERE status='offered' AND provider_did IS NULL "
        "ORDER BY created_at DESC LIMIT :lim"), {"lim": limit})).mappings().all()
    out = []
    for r in rows:
        c = dict(r)
        out.append(_to_response(c, await _m1(db, c["id"])))
    return out


@router.get("/{contract_id}", response_model=ContractResponse)
async def get_contract(
    contract_id: str,
    db: AsyncSession = Depends(get_db),
    actor: dict = Depends(get_current_actor_for_read),
):
    """Retrieve a contract (dual-auth read, X34). Reads never emit (M8/P0 fix)."""
    c = await _resolve(db, contract_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Contract with id {contract_id} not found")
    if not _agent_may_read(actor, c):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a party to this contract")
    return _to_response(c, await _m1(db, c["id"]))


def _agent_may_read(actor: dict, c: dict) -> bool:
    """§MCPTEST30 (2026-10-01): the contracts v2 detail rule (contracts_v2.get_contract_v2), which this legacy view of the
    SAME spine row never applied: an agent reads a contract it is a party to, or an open offer. Measured on sbx-alpha
    (V0508): an agent that is no party to a completed contract read all of it through getContractById (HTTP 200,
    acceptance criteria, amount, pr url), while getContractV2 refused that agent the same row (403). A developer JWT
    reads as the v2 route lets it ("dev JWT = full read"): that is a separate question, left as it is."""
    # §MCPTEST30 (V0556): ONE rule with the v2 detail (an open offer is browsable, a private one naming a provider is not)
    from agentvault_registry.routers.contracts_v2 import agent_may_read
    return agent_may_read(actor, {k: c.get(k) for k in ("client_did", "provider_did", "status")})


@router.get("/agent/{agent_did}", response_model=List[ContractResponse])
async def get_agent_contracts(
    agent_did: str,
    role: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    actor: dict = Depends(get_current_actor_for_read),
):
    """All contracts involving an agent (agent JWT = self-only; developer JWT = any)."""
    if actor.get("kind") == "agent" and actor.get("agent_did") != agent_did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent JWTs may only query contracts for their own DID. "
                   "Use a developer JWT for admin browse.")
    if role and role not in ["client", "upgrader"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Role must be either 'client' or 'upgrader'")
    # §BLOGSHOTS-FIX (2026-07-27): no legacy_ruc_id filter — an agent's contracts are its
    # contracts, spine-native ones included. Spine rows ride the same adapter response with
    # id=-1 and ref='ctr_…'; _resolve() already accepts refs for detail reads.
    q = "SELECT * FROM contracts WHERE "
    if role == "client":
        q += "client_did=:d"
    elif role == "upgrader":
        q += "provider_did=:d"
    else:
        q += "(client_did=:d OR provider_did=:d)"
    q += " ORDER BY created_at DESC LIMIT 200"
    rows = (await db.execute(text(q), {"d": agent_did})).mappings().all()
    out = []
    for r in rows:
        c = dict(r)
        out.append(_to_response(c, await _m1(db, c["id"])))
    return out


# ── cross-registry (federation-authenticated) ────────────────────────────────────────────────

class CrossRegistryContractProxy(BaseModel):
    """A provider's action on a contract, wherever the contract lives (§TWOAGENT V0437: the contracts v2 rail)."""
    target_registry_url: Optional[str] = Field(None, description="Not used since V0437: a contract homed elsewhere is "
                                               "replicated here and its home is the replica's (the answer names it)")
    # §XHIRE: spine ids are 'ctr_…' STRINGS — an int-only field 422'd them at
    # pydantic before the handler (the §29k class), while the receiving
    # accept-federated path param and _resolve() both take either form.
    contract_id: Union[int, str] = Field(..., description="Contract ID on the target registry (int legacy id or 'ctr_…')")
    action: str = Field(..., description="Action: 'accept' or 'submit'")
    upgrader_agent_did: Optional[str] = Field(None, description="Upgrader DID (required for accept)")
    pr_url: Optional[str] = Field(None, description="PR URL (required for submit)")
    seq: Optional[int] = Field(None, ge=1, description="Milestone to deliver (submit); default 1")


# §TWOAGENT (V0437, 2026-09-23): the two peer routes below are RETIRED. They let a federated peer accept or deliver a
# contract in the name of any agent it named in the body (no bond or enforcement gate, no check that the peer is the
# agent's home), and they doubled the cross-frame rail V0428+ built for exactly this: the provider acts on its OWN
# registry, as itself, and that registry gates it and couriers the command to the contract's home
# (POST /api/v1/federation/contract-command), where the gates run again. The routes stay, answering 410 to everyone, so
# an old caller learns where the rail went instead of reading a 404.
_RETIRED_PEER_ACT = (
    "Retired: a peer registry can no longer {verb} a contract in an agent's name. The provider acts on its own "
    "registry, as itself: POST /api/v1/contracts/v2/{{cid}}/{path} there. That registry gates it and carries the "
    "command to the contract's home (POST /api/v1/federation/contract-command), where the gates run again."
)


@router.post("/{contract_id}/accept-federated", status_code=status.HTTP_410_GONE, deprecated=True,
             summary="Retired: a provider accepts on its own registry (contracts v2)")
async def accept_contract_federated(contract_id: str):
    raise HTTPException(status_code=status.HTTP_410_GONE,
                        detail=_RETIRED_PEER_ACT.format(verb="accept", path="accept"))


@router.post("/{contract_id}/submit-federated", status_code=status.HTTP_410_GONE, deprecated=True,
             summary="Retired: a provider delivers on its own registry (contracts v2)")
async def submit_contract_work_federated(contract_id: str):
    raise HTTPException(status_code=status.HTTP_410_GONE,
                        detail=_RETIRED_PEER_ACT.format(verb="deliver on", path="milestones/{seq}/submit"))


@router.post("/cross-registry/proxy", response_model=Dict[str, Any])
async def proxy_contract_action(
    proxy_data: CrossRegistryContractProxy,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(require_agent_permission("contracts.engage"))
):
    """
    Act on a contract as yourself, wherever it lives: `accept`, or `submit` a milestone's delivery. A contract homed
    on another frame is present here as a replica, and the action is carried to its home; `target_registry_url` is
    not needed (the answer names where the action went, `relayed_to`).

    \f
    Act on a contract as YOURSELF, wherever it lives: `accept`, or `submit` a milestone's delivery.

    §TWOAGENT (V0437): this is the contracts v2 provider rail. A contract homed on another frame is present here as a
    replica, and the action is carried to its home by the courier; the contract's home is the replica's, so
    `target_registry_url` is not needed (the answer names where the action went, `relayed_to`). Before V0437 this
    route dialled the peer's accept-federated/submit-federated in the name of whichever `upgrader_agent_did` the body
    carried, which need not have been the caller.
    """
    if proxy_data.action not in ("accept", "submit"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action: {proxy_data.action}. Must be 'accept' or 'submit'."
        )
    if proxy_data.upgrader_agent_did and proxy_data.upgrader_agent_did != current_agent.did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(f"You act as yourself ({current_agent.did}); upgrader_agent_did names another agent. "
                    "Each provider accepts and delivers from its own registry.")
        )
    from . import contracts_v2 as v2
    cid = str(proxy_data.contract_id)
    logger.info(f"Contract proxy (v2 rail): agent={current_agent.did} action={proxy_data.action} contract={cid}")
    if proxy_data.action == "accept":
        return await v2.accept_contract_v2(cid, request, agent=current_agent, db=db)
    if not proxy_data.pr_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="pr_url required for submit action")
    return await v2.submit_milestone(cid, int(proxy_data.seq or 1), v2.SubmitIn(deliverable={"pr_url": proxy_data.pr_url}),
                                     request=request, agent=current_agent, db=db)


# ── malpractice (DDR) ────────────────────────────────────────────────────────────────────────

class MalpracticeDisputeCreate(BaseModel):
    """Request body for creating a malpractice dispute."""
    contract_id: int = Field(..., description="ID of the contract in dispute")
    reason: str = Field(
        default="Malpractice in contract execution",
        description="Reason for the dispute"
    )


@router.post("/malpractice", status_code=status.HTTP_201_CREATED)
async def create_malpractice_dispute(
    dispute_data: MalpracticeDisputeCreate,
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(require_agent_permission("contracts.engage"))
):
    """File a malpractice dispute via DDR. Caller must be a party; the contract → disputed."""
    c = await _resolve(db, dispute_data.contract_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Contract {dispute_data.contract_id} not found")
    if current_agent.did not in (c["client_did"], c.get("provider_did")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only contract parties (client or upgrader) can file malpractice disputes")
    defendant_did = c.get("provider_did") if current_agent.did == c["client_did"] else c["client_did"]
    if not defendant_did:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Cannot file dispute: contract has no opposing party assigned")
    try:
        from ..crud import crud_disputes
        dispute = await crud_disputes.create_dispute(
            db=db, complainant_did=current_agent.did, defendant_did=defendant_did,
            contract_id=c.get("legacy_ruc_id"))
        await db.execute(text("UPDATE disputes SET contract_ref=:r WHERE id=:i"),
                         {"r": c["id"], "i": dispute.id})
        claimed = await db.execute(text(
            "UPDATE contracts SET status='disputed', dispute_id=:d, updated_at=now() "
            "WHERE id=:c AND status IN ('agreed','in_progress')"),
            {"c": c["id"], "d": str(dispute.id)})
        if getattr(claimed, "rowcount", 0) > 0:
            await cs.audit(db, c["id"], await cs.next_seq(db, c["id"]), "disputed",
                           current_agent.did, {"via": "malpractice", "ddr_dispute": dispute.id})
        await db.commit()
        try:
            await event_emitter.emit(
                event_type="DisputeFiled",
                aggregate_id=f"dispute:{dispute.id}",
                aggregate_type="Dispute",
                data={"dispute_id": dispute.id, "contract_id": c.get("legacy_ruc_id"),
                      "spine_contract_id": c["id"],
                      "complainant_did": current_agent.did, "defendant_did": defendant_did,
                      "reason": (dispute_data.reason or "")[:500],
                      "filed_via": "contract_malpractice"})
        except Exception as e:
            logger.error(f"Failed to emit DisputeFiled event for dispute {dispute.id}: {e}")
        return {
            "message": "Malpractice dispute filed via DDR system",
            "dispute_id": dispute.id,
            "contract_id": c.get("legacy_ruc_id"),
            "complainant_did": current_agent.did,
            "defendant_did": defendant_did,
            "status": dispute.status,
        }
    except (ImportError, AttributeError) as e:
        logger.warning(f"DDR system not available for malpractice dispute: {e}")
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Malpractice dispute system integration pending. Use /api/v1/disputes/ directly.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create malpractice dispute: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Failed to create malpractice dispute")
