"""Dispute-related API endpoints"""
import logging
import traceback
from datetime import datetime, timezone
from typing import Annotated, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from starlette.status import (
    HTTP_400_BAD_REQUEST, HTTP_403_FORBIDDEN, HTTP_404_NOT_FOUND, HTTP_409_CONFLICT,
    HTTP_201_CREATED
)

from ...core.security import verify_agent_token, verify_admin_token
from ...database.db_session import get_db
from ...database.crud import DisputeCRUD, AgentCRUD
from ...database.models import DisputeStatus
from .schemas import (
    DisputeLogRequest,
    DisputeLogResponse,
    DisputeQueryResponse,
    DisputeStatusUpdateRequest,
    DisputeStatusUpdateResponse,
    DisputeWithdrawRequest,
    DisputeWithdrawResponse,
    ErrorResponse
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/",
    response_model=DisputeLogResponse,
    status_code=HTTP_201_CREATED,  # OWL-FIX 2026-03-07: registry proxy expects 201
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
    summary="Log a new dispute",
    description="Allows an authenticated agent to log a dispute against another agent."
)
async def log_dispute(
    request: DisputeLogRequest,
    agent_id: Annotated[str, Security(verify_agent_token)],
    db: Session = Depends(get_db)
):
    """
    Log a dispute between agents.
    
    The authenticated agent must be the claimant.
    """
    # Verify the authenticated agent is the claimant
    if agent_id != request.claimant_agent_did:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Authenticated agent must be the claimant"
        )

    # OWL-FIX (2026-03-07): Restore create-dispute body (was orphaned as dead code below resolve_dispute return)
    # Ensure both agents exist in TEG DB
    AgentCRUD.get_or_create(db, request.claimant_agent_did)
    AgentCRUD.get_or_create(db, request.defendant_agent_did)

    # Prevent self-disputes
    if request.claimant_agent_did == request.defendant_agent_did:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Cannot file a dispute against yourself"
        )

    try:
        dispute = DisputeCRUD.create_dispute(
            db=db,
            claimant_agent_did=request.claimant_agent_did,
            defendant_agent_did=request.defendant_agent_did,
            reason_code=request.reason_code,
            brief_description=request.brief_description,
            avtp_transaction_id=request.avtp_transaction_id,
            evidence_pointer=request.evidence_pointer,
            dispute_reason_category=request.dispute_reason_category,
            related_transaction_id=request.related_transaction_id,
            evidence_description_or_url=getattr(request, 'evidence_description_or_url', None)
        )

        return DisputeLogResponse(
            dispute_log_id=dispute.dispute_log_id,
            status=str(dispute.status.value) if hasattr(dispute.status, 'value') else str(dispute.status)
        )

    except Exception as e:
        logger.error(f"OWL-DIAG: create_dispute failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Failed to log dispute: {type(e).__name__}: {e}"
        )


@router.post(
    "/{dispute_id}/resolve",
    summary="Resolve a dispute",
    description="Resolve a dispute with a specific resolution and optional penalty (admin only)."
)
async def resolve_dispute(
    dispute_id: str,
    resolution: str,
    resolution_details: Optional[str] = None,
    penalty_amount: Optional[str] = None,
    is_admin: bool = Security(verify_admin_token),
    db: Session = Depends(get_db)
):
    """Resolve a dispute (admin/moderator only)."""
    from ...database.models import TEGDisputeLog, TEGTransaction, TransactionStatus, AgentTEGProfile
    from decimal import Decimal
    import uuid
    
    if not is_admin:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Admin authentication required"
        )
    
    dispute = db.query(TEGDisputeLog).filter(
        TEGDisputeLog.dispute_log_id == dispute_id
    ).first()
    
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")
    
    resolved_statuses = [
        DisputeStatus.RESOLVED_FAVOR_INITIATOR,
        DisputeStatus.RESOLVED_FAVOR_RESPONDENT,
        DisputeStatus.RESOLVED_NO_ACTION,
        DisputeStatus.REJECTED
    ]
    
    if dispute.status in resolved_statuses:
        raise HTTPException(status_code=400, detail="Dispute is already resolved")
    
    resolution_map = {
        "RESOLVED_FAVOR_INITIATOR": DisputeStatus.RESOLVED_FAVOR_INITIATOR,
        "RESOLVED_FAVOR_RESPONDENT": DisputeStatus.RESOLVED_FAVOR_RESPONDENT,
        "RESOLVED_NO_ACTION": DisputeStatus.RESOLVED_NO_ACTION,
        "REJECTED": DisputeStatus.REJECTED
    }
    
    new_status = resolution_map.get(resolution.upper())
    if not new_status:
        raise HTTPException(status_code=400, detail=f"Invalid resolution: {resolution}")
    
    dispute.status = new_status
    dispute.resolution_notes = resolution_details
    dispute.updated_at = datetime.now(timezone.utc)
    
    penalty_tx_id = None
    if penalty_amount and Decimal(penalty_amount) > 0:
        defendant = db.query(AgentTEGProfile).filter(
            AgentTEGProfile.agent_id == dispute.defendant_agent_did
        ).first()
        
        if defendant:
            penalty = Decimal(penalty_amount)
            if defendant.token_balance >= penalty:
                defendant.token_balance -= penalty
                # Keep audited_balance in sync (penalty is legitimate)
                defendant.audited_balance = defendant.token_balance
                penalty_tx_id = str(uuid.uuid4())
                transaction = TEGTransaction(
                    transaction_id=penalty_tx_id,
                    sender_agent_id=dispute.defendant_agent_did,
                    receiver_agent_id="SYSTEM_PENALTIES",
                    amount=penalty,
                    fee_amount=Decimal("0"),
                    status=TransactionStatus.COMPLETED,
                    transaction_type="penalty",
                    attached_message=f"Dispute resolution penalty for {dispute_id}",
                    timestamp=datetime.now(timezone.utc)
                )
                db.add(transaction)
            else:
                raise HTTPException(status_code=400, detail="Defendant has insufficient balance for penalty")
    
    db.commit()
    db.refresh(dispute)
    
    return {
        "dispute_id": dispute_id,
        "status": dispute.status.value,
        "resolution": resolution,
        "resolution_details": resolution_details,
        "penalty_applied": penalty_amount is not None and Decimal(penalty_amount) > 0,
        "penalty_transaction_id": penalty_tx_id,
        "resolved_at": dispute.updated_at.isoformat()
    }


# D6-825 (V0658): a claimant withdraws its own OPEN dispute. There was no way to close a
# dispute short of an admin's ruling, so every dispute filed stayed OPEN (the MCP tester's fixture alone was 187 of the
# 319 OPEN disputes on sbx-alpha's TEG, 2026-10-24). The withdrawal moves nothing (no ruling, no penalty): one guarded
# update, OPEN to WITHDRAWN, that only the claimant's own row can take, so a second withdrawal, or a withdrawal racing an
# admin's ruling, finds the row no longer OPEN and is refused. The row records it: who withdrew it, when, and the reason
# given (resolution_notes); the registry that relays it audits it as the agent.
WITHDRAW_NOTE = "Withdrawn by its claimant {did} at {at}"


@router.post(
    "/{dispute_log_id}/withdraw",
    response_model=DisputeWithdrawResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Not the dispute's claimant"},
        404: {"model": ErrorResponse, "description": "Not Found"},
        409: {"model": ErrorResponse, "description": "The dispute is no longer OPEN"},
    },
    summary="Withdraw your own open dispute",
    description="The dispute's claimant withdraws it while it is OPEN: its status becomes WITHDRAWN, with no ruling, no "
                "penalty and no money moved.",
)
async def withdraw_dispute(
    dispute_log_id: str,
    agent_id: Annotated[str, Security(verify_agent_token)],
    request: Optional[DisputeWithdrawRequest] = None,
    db: Session = Depends(get_db),
):
    """The claimant withdraws its own OPEN dispute (D6-825)."""
    from ...database.models import TEGDisputeLog
    now = datetime.now(timezone.utc)
    reason = ((request.reason if request is not None else None) or "").strip()
    note = WITHDRAW_NOTE.format(did=agent_id, at=now.isoformat()) + (f": {reason}" if reason else "")
    claimed = db.query(TEGDisputeLog).filter(
        TEGDisputeLog.dispute_log_id == dispute_log_id,
        TEGDisputeLog.claimant_agent_did == agent_id,
        TEGDisputeLog.status == DisputeStatus.OPEN,
    ).update({TEGDisputeLog.status: DisputeStatus.WITHDRAWN, TEGDisputeLog.resolution_notes: note[:2000],
              TEGDisputeLog.updated_at: now}, synchronize_session=False)
    if claimed != 1:
        db.rollback()
        dispute = DisputeCRUD.get_dispute_by_id(db, dispute_log_id)
        if dispute is None:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Dispute not found")
        if dispute.claimant_agent_did != agent_id:
            raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Only the dispute's claimant can withdraw it")
        current = dispute.status.value if hasattr(dispute.status, "value") else str(dispute.status)
        raise HTTPException(status_code=HTTP_409_CONFLICT,
                            detail=f"Only an OPEN dispute can be withdrawn; this one is {current}")
    db.commit()
    logger.info(f"[TEG-DISPUTE] dispute {dispute_log_id} withdrawn by its claimant {agent_id}")
    return DisputeWithdrawResponse(dispute_log_id=dispute_log_id, status=DisputeStatus.WITHDRAWN.value,
                                   resolution_notes=note[:2000], withdrawn_at=now)


@router.get(
    "/",
    response_model=List[DisputeQueryResponse],
    responses={401: {"model": ErrorResponse, "description": "Unauthorized"}}
)
async def list_disputes(
    agent_id: Annotated[str, Security(verify_agent_token)],
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    query = db.query(DisputeCRUD.model).filter(
        or_(
            DisputeCRUD.model.claimant_agent_did == agent_id,
            DisputeCRUD.model.defendant_agent_did == agent_id
        )
    )
    
    if status:
        try:
            status_enum = DisputeStatus(status)
            query = query.filter(DisputeCRUD.model.status == status_enum)
        except ValueError:
            return []
    
    if category:
        query = query.filter(DisputeCRUD.model.dispute_reason_category == category)
    
    disputes = query.order_by(DisputeCRUD.model.created_at.desc()).limit(limit).offset(offset).all()
    
    return [
        DisputeQueryResponse(
            dispute_log_id=d.dispute_log_id,
            claimant_agent_did=d.claimant_agent_did,
            defendant_agent_did=d.defendant_agent_did,
            reason_code=d.reason_code,
            brief_description=d.brief_description,
            avtp_transaction_id=d.avtp_transaction_id,
            evidence_pointer=d.evidence_pointer,
            status=d.status.value,
            resolution_notes=d.resolution_notes,
            dispute_reason_category=d.dispute_reason_category,
            related_transaction_id=d.related_transaction_id,
            evidence_description_or_url=d.evidence_description_or_url,
            admin_reviewer_id=d.admin_reviewer_id,
            created_at=d.created_at,
            updated_at=d.updated_at
        )
        for d in disputes
    ]


@router.get(
    "/my-disputes",
    response_model=List[DisputeQueryResponse],
    responses={401: {"model": ErrorResponse, "description": "Unauthorized"}}
)
async def get_my_disputes(
    agent_id: Annotated[str, Security(verify_agent_token)],
    role: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    if role == "claimant":
        query = db.query(DisputeCRUD.model).filter(DisputeCRUD.model.claimant_agent_did == agent_id)
    elif role == "defendant":
        query = db.query(DisputeCRUD.model).filter(DisputeCRUD.model.defendant_agent_did == agent_id)
    else:
        query = db.query(DisputeCRUD.model).filter(
            or_(DisputeCRUD.model.claimant_agent_did == agent_id, DisputeCRUD.model.defendant_agent_did == agent_id)
        )
    
    if status:
        try:
            query = query.filter(DisputeCRUD.model.status == DisputeStatus(status))
        except ValueError:
            return []
    
    disputes = query.order_by(DisputeCRUD.model.created_at.desc()).limit(limit).offset(offset).all()
    
    return [
        DisputeQueryResponse(
            dispute_log_id=d.dispute_log_id, claimant_agent_did=d.claimant_agent_did,
            defendant_agent_did=d.defendant_agent_did, reason_code=d.reason_code,
            brief_description=d.brief_description, avtp_transaction_id=d.avtp_transaction_id,
            evidence_pointer=d.evidence_pointer, status=d.status.value,
            resolution_notes=d.resolution_notes, dispute_reason_category=d.dispute_reason_category,
            related_transaction_id=d.related_transaction_id,
            evidence_description_or_url=d.evidence_description_or_url,
            admin_reviewer_id=d.admin_reviewer_id, created_at=d.created_at, updated_at=d.updated_at
        )
        for d in disputes
    ]


@router.get(
    "/forme",
    response_model=List[DisputeQueryResponse],
    responses={401: {"model": ErrorResponse, "description": "Unauthorized"}}
)
async def get_my_disputes_legacy(
    agent_id: Annotated[str, Security(verify_agent_token)],
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    query = db.query(DisputeCRUD.model).filter(
        or_(DisputeCRUD.model.claimant_agent_did == agent_id, DisputeCRUD.model.defendant_agent_did == agent_id)
    )
    if status:
        query = query.filter(DisputeCRUD.model.status == status)
    
    disputes = query.order_by(DisputeCRUD.model.created_at.desc()).limit(limit).offset(offset).all()
    
    return [
        DisputeQueryResponse(
            dispute_log_id=d.dispute_log_id, claimant_agent_did=d.claimant_agent_did,
            defendant_agent_did=d.defendant_agent_did, reason_code=d.reason_code,
            brief_description=d.brief_description, avtp_transaction_id=d.avtp_transaction_id,
            evidence_pointer=d.evidence_pointer, status=d.status.value,
            resolution_notes=d.resolution_notes, dispute_reason_category=d.dispute_reason_category,
            related_transaction_id=d.related_transaction_id,
            evidence_description_or_url=d.evidence_description_or_url,
            admin_reviewer_id=d.admin_reviewer_id, created_at=d.created_at, updated_at=d.updated_at
        )
        for d in disputes
    ]


@router.get(
    "/{dispute_log_id}",
    response_model=DisputeQueryResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Not Found"},
    }
)
async def get_dispute_details(
    dispute_log_id: str,
    agent_id: Annotated[str, Security(verify_agent_token)],
    db: Session = Depends(get_db)
):
    dispute = DisputeCRUD.get_dispute_by_id(db, dispute_log_id)
    
    if not dispute:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Dispute not found")
    
    if agent_id not in [dispute.claimant_agent_did, dispute.defendant_agent_did]:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="You are not authorized to view this dispute")
    
    return DisputeQueryResponse(
        dispute_log_id=dispute.dispute_log_id,
        claimant_agent_did=dispute.claimant_agent_did,
        defendant_agent_did=dispute.defendant_agent_did,
        reason_code=dispute.reason_code,
        brief_description=dispute.brief_description,
        avtp_transaction_id=dispute.avtp_transaction_id,
        evidence_pointer=dispute.evidence_pointer,
        status=dispute.status.value,
        resolution_notes=dispute.resolution_notes,
        dispute_reason_category=dispute.dispute_reason_category,
        related_transaction_id=dispute.related_transaction_id,
        evidence_description_or_url=dispute.evidence_description_or_url,
        admin_reviewer_id=dispute.admin_reviewer_id,
        created_at=dispute.created_at,
        updated_at=dispute.updated_at
    )


@router.post(
    "/admin/disputes/{dispute_log_id}/update_status",
    response_model=DisputeStatusUpdateResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        404: {"model": ErrorResponse, "description": "Not Found"},
    },
    summary="Update dispute status (Admin only)"
)
async def update_dispute_status_admin(
    dispute_log_id: str,
    request: DisputeStatusUpdateRequest,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db)
):
    if not is_admin:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Admin authentication required")
    
    dispute = DisputeCRUD.get_dispute_by_id(db, dispute_log_id)
    if not dispute:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Dispute not found")
    
    status_mapping = {
        "resolved_claimant_favored": "RESOLVED_FAVOR_INITIATOR",
        "resolved_defendant_favored": "RESOLVED_FAVOR_TARGET"
    }
    status_value = status_mapping.get(request.new_status, request.new_status)
    
    try:
        status_enum = DisputeStatus(status_value)
    except ValueError:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=f"Invalid status: {request.new_status}")
    
    old_status = dispute.status.value
    
    try:
        updated_dispute = DisputeCRUD.update_status(
            db=db, dispute_log_id=dispute_log_id, new_status=status_enum,
            resolution_notes=request.resolution_notes
        )
        return DisputeStatusUpdateResponse(
            dispute_log_id=updated_dispute.dispute_log_id,
            old_status=old_status,
            new_status=updated_dispute.status.value,
            resolution_notes=updated_dispute.resolution_notes,
            updated_at=updated_dispute.updated_at
        )
    except Exception as e:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=f"Failed to update dispute status: {str(e)}")
