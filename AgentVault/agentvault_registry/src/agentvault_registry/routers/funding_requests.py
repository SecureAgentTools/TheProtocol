"""
AVT Funding Request System — f041

Endpoints:
  POST /api/v1/funding/request         — Agent submits a funding request
  GET  /api/v1/funding/my-requests     — Agent views own requests

  GET  /api/v1/admin/funding/pending   — Admin views pending requests
  GET  /api/v1/admin/funding/all       — Admin views all requests (with filters)
  POST /api/v1/admin/funding/{id}/approve — Admin approves + funds
  POST /api/v1/admin/funding/{id}/reject  — Admin rejects
"""
import logging
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, Security
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.frame_currency import frame_currency
from ..core.network_profile import money_knob  # §MONEY-M2: the profile owns this amount

from ..database import get_db
from ..models import Agent, Developer, FundingRequest, FundingRequestStatus
from .utils import get_current_agent
from .. import security
from ..event_emitter import get_event_emitter
from ..config import settings
from ..email_utils import send_themed_email

logger = logging.getLogger(__name__)

event_emitter = get_event_emitter()


# ── Email Notification Helpers ────────────────────────────────────────────

async def _get_requester_email(db: AsyncSession, requester_did: str) -> Optional[str]:
    """
    Look up the developer email for the agent that submitted the funding request.
    Agent -> creator_developer_id -> Developer.email
    """
    try:
        result = await db.execute(
            select(Developer.email)
            .join(Agent, Agent.creator_developer_id == Developer.id)
            .where(Agent.did == requester_did)
        )
        email = result.scalar_one_or_none()
        return email
    except Exception as e:
        logger.warning(f"[Funding] Failed to look up requester email for {requester_did}: {e}")
        return None


async def _send_funding_approval_email(
    recipient_email: Optional[str],
    request_id: int,
    requester_did: str,
    approved_amount: Decimal,
    transaction_id: Optional[str],
) -> None:
    """Send approval notification email (fire-and-forget, never raises).

    Takes the resolved recipient_email rather than a db session so this can run as a
    background task without sharing the request's asyncpg connection (which would
    trigger 'another operation is in progress' under load).
    """
    try:
        if not recipient_email:
            logger.debug(f"[Funding] No email available for {requester_did}, skipping notification")
            return

        await send_themed_email(
            subject=f"Your {frame_currency()} Funding Request Has Been Approved",
            recipients=[recipient_email],
            template="funding_approved",
            context={
                "request_id": request_id,
                "approved_amount": str(approved_amount),
                "requester_did": requester_did,
                "transaction_id": transaction_id or "",
            },
            theme="neural",
        )
        logger.info(f"[Funding] Approval email sent to {recipient_email} for request #{request_id}")
    except Exception as e:
        logger.warning(f"[Funding] Failed to send approval email for request #{request_id}: {e}")


async def _send_funding_rejection_email(
    recipient_email: Optional[str],
    request_id: int,
    requester_did: str,
    requested_amount: Decimal,
    rejection_reason: str,
) -> None:
    """Send rejection notification email (fire-and-forget, never raises).

    Takes the resolved recipient_email rather than a db session — see approval-email
    helper for rationale.
    """
    try:
        if not recipient_email:
            logger.debug(f"[Funding] No email available for {requester_did}, skipping notification")
            return

        await send_themed_email(
            subject=f"{frame_currency()} Funding Request Update",
            recipients=[recipient_email],
            template="funding_rejected",
            context={
                "request_id": request_id,
                "requested_amount": str(requested_amount),
                "requester_did": requester_did,
                "rejection_reason": rejection_reason,
            },
            theme="neural",
        )
        logger.info(f"[Funding] Rejection email sent to {recipient_email} for request #{request_id}")
    except Exception as e:
        logger.warning(f"[Funding] Failed to send rejection email for request #{request_id}: {e}")

# ── Schemas ───────────────────────────────────────────────────────────────

class FundingRequestCreate(BaseModel):
    amount: str = Field(..., description="Requested amount, in the frame's unit (as string for precision)")
    reason: str = Field(..., min_length=10, max_length=2000, description="Justification for funding request")

    @field_validator("reason")
    @classmethod
    def sanitize_reason(cls, v):
        from agentvault_registry.input_validators import validate_safe_text
        return validate_safe_text(v, "reason")


class FundingApproval(BaseModel):
    approved_amount: Optional[str] = Field(None, description="Amount to approve (defaults to requested_amount)")


class FundingRejection(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000, description="Rejection reason")


class FundingRequestResponse(BaseModel):
    id: int
    requester_did: str
    requester_name: Optional[str] = None
    requested_amount: str
    reason: str
    status: str
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    approved_amount: Optional[str] = None
    rejection_reason: Optional[str] = None
    funded_at: Optional[datetime] = None
    funding_transaction_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


def _to_response(req: FundingRequest) -> FundingRequestResponse:
    """Convert a FundingRequest ORM object to a response schema."""
    return FundingRequestResponse(
        id=req.id,
        requester_did=req.requester_did,
        requester_name=req.requester_name,
        requested_amount=str(req.requested_amount),
        reason=req.reason,
        status=req.status,
        reviewed_by=req.reviewed_by,
        reviewed_at=req.reviewed_at,
        approved_amount=str(req.approved_amount) if req.approved_amount is not None else None,
        rejection_reason=req.rejection_reason,
        funded_at=req.funded_at,
        funding_transaction_id=req.funding_transaction_id,
        created_at=req.created_at,
        updated_at=req.updated_at,
    )


# ── Agent Router ──────────────────────────────────────────────────────────

agent_router = APIRouter(prefix="/api/v1/funding", tags=["Funding"])


@agent_router.post("/request", response_model=FundingRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_funding_request(
    body: FundingRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(get_current_agent),
):
    """
    Submit a funding request: an amount in the frame's units and a reason, for an administrator to approve or reject
    (an approved request is funded from the treasury). At most 3 pending requests per agent (429 beyond) and at most
    the registry's cap per request (`FUNDING_REQUEST_MAX_AVT`). Needs an agent token.
    """
    # Validate amount
    try:
        amount = Decimal(body.amount)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid amount format")

    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")
    _req_max = money_knob("FUNDING_REQUEST_MAX_AVT", "100000")
    if amount > _req_max:
        raise HTTPException(status_code=400, detail=f"Amount must not exceed {_req_max:,} {frame_currency()}")

    # Rate limit: max 3 pending requests
    pending_count_result = await db.execute(
        select(func.count(FundingRequest.id)).where(
            FundingRequest.requester_did == current_agent.did,
            FundingRequest.status == FundingRequestStatus.PENDING.value,
        )
    )
    pending_count = pending_count_result.scalar() or 0

    if pending_count >= 3:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Maximum 3 pending funding requests allowed. Wait for existing requests to be reviewed.",
        )

    # Create request
    funding_req = FundingRequest(
        requester_did=current_agent.did,
        requester_name=getattr(current_agent, "name", None),
        requested_amount=amount,
        reason=body.reason,
        status=FundingRequestStatus.PENDING.value,
    )
    db.add(funding_req)
    await db.commit()
    await db.refresh(funding_req)

    logger.info(f"[Funding] Request #{funding_req.id} created by {current_agent.did} for {amount} AVT")

    # #5 (2026-05-08): emit FundingRequestCreated so the
    # FundingRequestCreatedReactor can broadcast a treasury-admin toast.
    # Fire-and-forget — emission failure must NOT block the request creation
    # response (rate limiter already validated the action).
    asyncio.create_task(event_emitter.emit(
        event_type="FundingRequestCreated",
        aggregate_id=current_agent.did,
        aggregate_type="Funding",
        data={
            "request_id": funding_req.id,
            "requester_did": current_agent.did,
            "requester_name": getattr(current_agent, "name", None),
            "requested_amount": str(amount),
            "reason": body.reason,
            "status": funding_req.status,
            "created_at": funding_req.created_at.isoformat() if funding_req.created_at else None,
        },
        idempotency_key=f"fundreq-created-{funding_req.id}",  # §BATCH7
    ))

    return _to_response(funding_req)


@agent_router.get("/my-requests", response_model=List[FundingRequestResponse])
async def get_my_funding_requests(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status: pending, approved, rejected, funded"),
    db: AsyncSession = Depends(get_db),
    current_agent: Agent = Security(get_current_agent),
):
    """Get all funding requests submitted by the current agent."""
    stmt = select(FundingRequest).where(
        FundingRequest.requester_did == current_agent.did
    )

    if status_filter:
        # Validate status filter
        valid_statuses = {s.value for s in FundingRequestStatus}
        if status_filter not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status filter. Must be one of: {', '.join(valid_statuses)}")
        stmt = stmt.where(FundingRequest.status == status_filter)

    stmt = stmt.order_by(FundingRequest.created_at.desc())
    result = await db.execute(stmt)
    requests = result.scalars().all()

    return [_to_response(r) for r in requests]


# ── Admin Router ──────────────────────────────────────────────────────────

admin_router = APIRouter(
    prefix="/api/v1/admin/funding",
    tags=["Funding Admin"],
    dependencies=[Security(security.require_admin_flag("admin_treasury"))],
)


@admin_router.get("/pending", response_model=List[FundingRequestResponse])
async def get_pending_requests(
    db: AsyncSession = Depends(get_db),
    _admin=Security(security.require_admin_flag("admin_treasury")),
):
    """Get all pending funding requests, oldest first."""
    stmt = (
        select(FundingRequest)
        .where(FundingRequest.status == FundingRequestStatus.PENDING.value)
        .order_by(FundingRequest.created_at.asc())
    )
    result = await db.execute(stmt)
    requests = result.scalars().all()
    return [_to_response(r) for r in requests]


@admin_router.get("/all", response_model=List[FundingRequestResponse])
async def get_all_requests(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin=Security(security.require_admin_flag("admin_treasury")),
):
    """Get all funding requests with optional status filter and pagination."""
    stmt = select(FundingRequest)

    if status_filter:
        valid_statuses = {s.value for s in FundingRequestStatus}
        if status_filter not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status filter. Must be one of: {', '.join(valid_statuses)}")
        stmt = stmt.where(FundingRequest.status == status_filter)

    stmt = stmt.order_by(FundingRequest.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    requests = result.scalars().all()
    return [_to_response(r) for r in requests]


@admin_router.post("/{request_id}/approve", response_model=FundingRequestResponse)
async def approve_funding_request(
    request_id: int = Path(..., gt=0),
    body: FundingApproval = FundingApproval(),
    db: AsyncSession = Depends(get_db),
    admin=Security(security.require_admin_flag("admin_treasury")),
):
    """
    Approve a funding request and execute treasury funding.

    If approved_amount is not provided, the requested_amount is used.
    Immediately calls TEG treasury fund-agent to execute the transfer.
    """
    # Fetch request
    result = await db.execute(
        select(FundingRequest).where(FundingRequest.id == request_id)
    )
    funding_req = result.scalar_one_or_none()

    if not funding_req:
        raise HTTPException(status_code=404, detail=f"Funding request #{request_id} not found")

    if funding_req.status != FundingRequestStatus.PENDING.value:
        raise HTTPException(
            status_code=400,
            detail=f"Request #{request_id} is already {funding_req.status}, cannot approve",
        )

    # Determine approved amount
    if body.approved_amount is not None:
        try:
            approved_amount = Decimal(body.approved_amount)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid approved_amount format")
        if approved_amount <= 0:
            raise HTTPException(status_code=400, detail="Approved amount must be greater than 0")
    else:
        approved_amount = funding_req.requested_amount

    now = datetime.now(timezone.utc)
    admin_email = getattr(admin, "email", str(getattr(admin, "id", "unknown")))

    # Atomic claim: only ONE concurrent approval may flip PENDING → APPROVED.
    # Closes the double-fund race (two admins / a retried approval both reading
    # PENDING and both executing treasury funding).
    claim = await db.execute(
        update(FundingRequest)
        .where(FundingRequest.id == request_id,
               FundingRequest.status == FundingRequestStatus.PENDING.value)
        .values(status=FundingRequestStatus.APPROVED.value,
                reviewed_by=admin_email, reviewed_at=now, approved_amount=approved_amount)
    )
    await db.commit()
    if getattr(claim, "rowcount", 0) == 0:
        await db.refresh(funding_req)
        raise HTTPException(
            status_code=409,
            detail=f"Request #{request_id} is already {funding_req.status}, cannot approve",
        )
    await db.refresh(funding_req)

    # Execute funding via TEG treasury
    transaction_id = None
    funding_error = None
    try:
        transaction_id = await _execute_treasury_funding(
            db=db,
            target_did=funding_req.requester_did,
            amount=approved_amount,
            request_id=request_id,
            request_reason=funding_req.reason,
            actor_label=admin_email,
        )
        funding_req.status = FundingRequestStatus.FUNDED.value
        funding_req.funded_at = datetime.now(timezone.utc)
        funding_req.funding_transaction_id = transaction_id
        await db.commit()

        logger.info(
            f"[Funding] Request #{request_id} approved and funded: {approved_amount} AVT → {funding_req.requester_did} (tx: {transaction_id})"
        )
    except Exception as e:
        funding_error = str(e)
        logger.error(f"[Funding] Request #{request_id} approved but funding failed: {e}")
        # Status stays APPROVED — can be retried

    await db.refresh(funding_req)

    # Resolve recipient email synchronously while we still own the request's db
    # session. Background tasks must not borrow this session — concurrent use
    # triggers asyncpg "another operation is in progress".
    recipient_email = await _get_requester_email(db, funding_req.requester_did)

    # $10 (2026-07-24): money-adjacent event AWAITED — a create_task here is
    # dropped on worker restart and the approval audit trail silently vanishes.
    try:
        await event_emitter.emit(
            event_type="FundingRequestApproved",
            aggregate_id=funding_req.requester_did,
            aggregate_type="Funding",
            data={
                "request_id": request_id,
                "requester_did": funding_req.requester_did,
                "approved_amount": str(approved_amount),
                "approved_by": admin_email,
                "funded": funding_req.status == FundingRequestStatus.FUNDED.value,
                "transaction_id": transaction_id,
                "funding_error": funding_error,
            },
            idempotency_key=f"fundreq-approved-{request_id}",  # §BATCH7
        )
    except Exception as e:
        logger.warning(f"[Funding] FundingRequestApproved emit failed (non-fatal): {e}")

    # Send email notification (fire-and-forget, no db session borrowed)
    asyncio.create_task(_send_funding_approval_email(
        recipient_email=recipient_email,
        request_id=funding_req.id,
        requester_did=funding_req.requester_did,
        approved_amount=approved_amount,
        transaction_id=transaction_id,
    ))
    # §NOTIFV2 — funding.decided (approved). Post-commit, best-effort.
    try:
        from agentvault_registry.background_tasks.push_notify import notify_agent_owners
        asyncio.create_task(notify_agent_owners(
            "funding.decided", [funding_req.requester_did],
            title="Funding request approved",
            message=f"Request #{funding_req.id}: {approved_amount} approved",
            tags="moneybag", click="/ui/#/funding"))
    except Exception:  # noqa: BLE001
        logger.debug("[Funding] approve notify skipped", exc_info=True)

    return _to_response(funding_req)


@admin_router.post("/{request_id}/reject", response_model=FundingRequestResponse)
async def reject_funding_request(
    body: FundingRejection,
    request_id: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_db),
    admin=Security(security.require_admin_flag("admin_treasury")),
):
    """Reject a funding request with a reason."""
    result = await db.execute(
        select(FundingRequest).where(FundingRequest.id == request_id)
    )
    funding_req = result.scalar_one_or_none()

    if not funding_req:
        raise HTTPException(status_code=404, detail=f"Funding request #{request_id} not found")

    if funding_req.status != FundingRequestStatus.PENDING.value:
        raise HTTPException(
            status_code=400,
            detail=f"Request #{request_id} is already {funding_req.status}, cannot reject",
        )

    admin_email = getattr(admin, "email", str(getattr(admin, "id", "unknown")))
    now = datetime.now(timezone.utc)

    funding_req.status = FundingRequestStatus.REJECTED.value
    funding_req.reviewed_by = admin_email
    funding_req.reviewed_at = now
    funding_req.rejection_reason = body.reason
    await db.commit()
    await db.refresh(funding_req)

    logger.info(f"[Funding] Request #{request_id} rejected by {admin_email}: {body.reason}")
    # §NOTIFV2 — funding.decided (rejected). Post-commit, best-effort.
    try:
        from agentvault_registry.background_tasks.push_notify import notify_agent_owners
        asyncio.create_task(notify_agent_owners(
            "funding.decided", [funding_req.requester_did],
            title="Funding request rejected",
            message=f"Request #{funding_req.id} rejected: {(body.reason or '')[:80]}",
            tags="x", click="/ui/#/funding"))
    except Exception:  # noqa: BLE001
        logger.debug("[Funding] reject notify skipped", exc_info=True)

    # Resolve recipient email synchronously while we still own the request's db
    # session (see approval handler for rationale).
    recipient_email = await _get_requester_email(db, funding_req.requester_did)

    # $10 (2026-07-24): AWAITED (see approval handler).
    try:
        await event_emitter.emit(
            event_type="FundingRequestRejected",
            aggregate_id=funding_req.requester_did,
            aggregate_type="Funding",
            data={
                "request_id": request_id,
                "requester_did": funding_req.requester_did,
                "requested_amount": str(funding_req.requested_amount),
                "rejected_by": admin_email,
                "reason": body.reason,
            },
            idempotency_key=f"fundreq-rejected-{request_id}",  # §BATCH7
        )
    except Exception as e:
        logger.warning(f"[Funding] FundingRequestRejected emit failed (non-fatal): {e}")

    # Send email notification (fire-and-forget, no db session borrowed)
    asyncio.create_task(_send_funding_rejection_email(
        recipient_email=recipient_email,
        request_id=funding_req.id,
        requester_did=funding_req.requester_did,
        requested_amount=funding_req.requested_amount,
        rejection_reason=body.reason,
    ))

    return _to_response(funding_req)


# ── Internal: TEG Treasury Funding ────────────────────────────────────────

async def _execute_treasury_funding(
    db: AsyncSession,
    target_did: str,
    amount: Decimal,
    request_id: int,
    request_reason: str,
    actor_label: str,
) -> str:
    """
    Execute treasury funding via an in-process call to the TEG proxy helper.

    Calls `_fund_agent_from_treasury_internal()` directly — no HTTP loopback, no
    re-authentication, same DB session as the caller (so the funding-request status
    update and the treasury transfer share one transactional context).

    Returns the transaction ID on success. Raises on failure (HTTPException from
    the helper, or any other Exception) — caller catches and keeps the funding
    request in APPROVED state for retry.
    """
    # Local import — defensive against future module-import cycles even though
    # neither file currently imports the other at module level.
    from .teg_integration import (
        TreasuryFundAgentRequest,
        _fund_agent_from_treasury_internal,
    )

    # TreasuryFundAgentRequest.reason is max_length=100 (see teg_integration.py).
    # FundingRequest.reason is unbounded Text and submission caps at 2000 chars,
    # so we MUST truncate here. Structured `reference_id` (max 200) carries the
    # request id losslessly even when the prose tail is clipped.
    safe_reason = (f"Req #{request_id}: " + (request_reason or ""))[:100]

    req = TreasuryFundAgentRequest(
        target_agent_did=target_did,
        amount=str(amount),
        reason=safe_reason,
        reference_id=f"funding_request:{request_id}",
    )
    # §MONEY-R36 (class): approve is a state transition guarded by status, but
    # the transition and the transfer are not one atomic act — a retry between
    # them would fund twice. The request id is the natural exactly-once key.
    result = await _fund_agent_from_treasury_internal(
        db, req, actor_label=actor_label, idempotency_key=f"funding-approve-{request_id}",
    )
    return str(result.get("transaction_id") or result.get("id") or "unknown")
