"""
Reputation Signal endpoints for TEG Core Service

This module provides endpoints for the low-friction justice system,
allowing agents to provide immediate feedback on transactions.

Created as part of the reputation signal integration.
"""
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Header, Path, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, update

# §pass54 PR-3-expansion: APIKeyHeader spec markers for X-Service-Token +
# X-Agent-DID (same pattern as endpoints_tokenomics.py). Runtime unchanged.
_service_token_header = APIKeyHeader(
    name="X-Service-Token",
    scheme_name="ServiceToken",
    description="Service token authorization for reputation-signal endpoints.",
    auto_error=False,
)
_agent_did_header = APIKeyHeader(
    name="X-Agent-DID",
    scheme_name="AgentDID",
    description="Agent DID for the principal emitting the reputation signal.",
    auto_error=False,
)
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_403_FORBIDDEN, HTTP_404_NOT_FOUND, HTTP_409_CONFLICT

from ...api.auth import get_current_agent
from ...core.config import get_settings
from ...database.db_session import get_db
from ...database.models import TEGTransaction, TransactionStatus
from ...database.crud import ReputationService, ReputationSignalAlreadyApplied
from pydantic import BaseModel, Field

import logging

logger = logging.getLogger(__name__)

router = APIRouter()
settings = get_settings()


class ReputationSignalRequest(BaseModel):
    """Request to submit a reputation signal"""
    transaction_id: str = Field(..., description="TEG transaction ID")
    signal_value: int = Field(..., ge=-1, le=1, description="+1 or -1 signal")
    agent_did: str = Field(..., description="DID of the agent submitting signal")
    reason: Optional[str] = Field(None, max_length=200, description="Optional reason for signal")


class ReputationSignalResponse(BaseModel):
    """Response from reputation signal submission"""
    success: bool
    transaction_id: str
    signal_value: int
    affected_agent_did: str
    new_reputation_score: int
    timestamp: datetime


class ReputationSignalStatus(BaseModel):
    """Status of reputation signal for a transaction"""
    has_signaled: bool
    signal_value: Optional[int] = None
    signal_timestamp: Optional[datetime] = None
    can_signal: bool
    reason: Optional[str] = None


# In-memory storage for reputation signals (temporary until proper DB table)
# In production, this should be a proper database table
# §TRUSTCHAIN (2026-09-12): the per-process `reputation_signals` dict that used to live here was
# the dedup for a NINE-worker service; the transaction row (`reputation_signal_applied`) is the
# dedup now, claimed atomically in ReputationService.apply_signal.


def verify_registry_service_token(token: str, request=None) -> bool:
    """Verify an internal registry caller.

    §2026-06-17 Phase 4 — mTLS SVID (presented via the nginx-teg sidecar) is PRIMARY; the
    legacy shared key is a fallback honored ONLY while TEG_MTLS_REQUIRED is false (shadow).
    Under enforce, only an accepted internal SVID passes. Pass the FastAPI Request for mTLS.
    """
    if request is not None:
        try:
            from ...core.internal_auth import (
                extract_spiffe_from_request, is_internal_service_identity, teg_mtls_required,
            )
            spiffe = extract_spiffe_from_request(request)
            if spiffe and is_internal_service_identity(spiffe):  # §MONEY-R51: the ONE rule
                return True
            if teg_mtls_required():
                return False
        except Exception:
            pass
    from ...core.internal_auth import admin_key_ok  # §MONEY-M3a R26
    return admin_key_ok(token)


@router.post(
    "/reputation/signal",
    response_model=ReputationSignalResponse,
    responses={
        400: {"description": "Bad Request"},
        403: {"description": "Forbidden - Not transaction sender"},
        404: {"description": "Transaction not found"},
        409: {"description": "Already signaled"},
    }
)
async def submit_reputation_signal(
    http_request: Request,
    request: ReputationSignalRequest,
    db: Session = Depends(get_db),
    service_token: Optional[str] = Security(_service_token_header),
    agent_did_header: Optional[str] = Security(_agent_did_header)
):
    """
    Submit a reputation signal for a completed transaction.
    
    Rules:
    - Only transaction sender can signal
    - One signal per transaction
    - Signal value must be +1 or -1
    - Can only signal completed transactions
    - Signals must be submitted within 30 days
    """
    # Verify Registry service token
    if not verify_registry_service_token(service_token, http_request):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Invalid service token"
        )
    
    # Verify agent DID matches request
    if agent_did_header != request.agent_did:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Agent DID mismatch"
        )
    
    # Validate signal value
    if request.signal_value not in [-1, 1]:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Signal value must be +1 or -1"
        )
    
    # Get transaction from database
    transaction = db.query(TEGTransaction).filter(
        TEGTransaction.transaction_id == request.transaction_id
    ).first()
    
    if not transaction:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    
    # Verify agent is the transaction sender
    if transaction.sender_agent_id != request.agent_did:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Only the transaction sender can submit signals"
        )
    
    # Verify transaction is completed
    if transaction.status != TransactionStatus.COMPLETED:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Can only signal completed transactions"
        )
    
    # Check if signal period has expired (30 days)
    if datetime.now(timezone.utc) - transaction.timestamp > timedelta(days=30):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Signal period has expired (30 days)"
        )
    
    # §TRUSTCHAIN (2026-09-12): the dedup used to be a per-PROCESS dict on a nine-worker
    # service (a signal seen by worker 3 was invisible to worker 5), the score was read into
    # Python and written back absolutely, and three counters were written onto attributes the
    # model does not map (measured: 0 of 3,582 profiles carry one). The transaction row is the
    # dedup and ReputationService.apply_signal is the ONE implementation, shared with the token
    # routes; `cap=100` keeps this route's historical clamp. The receiver profile is ensured by
    # `AgentCRUD.get_or_create` (0 reputation, home-frame guard) — the `reputation_score=50`
    # inline create this route carried was unreachable for a COMPLETED transfer, whose receiver
    # already holds the profile the transfer credited.
    if transaction.reputation_signal_applied:
        raise HTTPException(
            status_code=HTTP_409_CONFLICT,
            detail="You have already signaled this transaction"
        )
    try:
        new_score = ReputationService.apply_signal(
            db, request.transaction_id, transaction.receiver_agent_id, request.signal_value, cap=100
        )
    except ReputationSignalAlreadyApplied:
        db.rollback()
        raise HTTPException(
            status_code=HTTP_409_CONFLICT,
            detail="You have already signaled this transaction"
        )

    logger.info(
        f"Reputation signal applied: {request.agent_did} -> {transaction.receiver_agent_id} "
        f"({'+' if request.signal_value > 0 else '-'}1), "
        f"new reputation: {new_score}"
    )

    return ReputationSignalResponse(
        success=True,
        transaction_id=request.transaction_id,
        signal_value=request.signal_value,
        affected_agent_did=transaction.receiver_agent_id,
        new_reputation_score=new_score,
        timestamp=datetime.now(timezone.utc)
    )


@router.get(
    "/reputation/signal/{transaction_id}/{agent_did}",
    response_model=ReputationSignalStatus,
    responses={
        403: {"description": "Forbidden"},
        404: {"description": "Transaction not found"},
    }
)
async def check_reputation_signal(
    http_request: Request,
    transaction_id: Annotated[str, Path(description="TEG transaction ID")],
    agent_did: Annotated[str, Path(description="Agent DID")],
    db: Session = Depends(get_db),
    service_token: Optional[str] = Security(_service_token_header)
):
    """
    Check if an agent has already submitted a reputation signal for a transaction.
    
    Also indicates whether the agent can still signal (is sender, within time limit, etc).
    """
    # Verify Registry service token
    if not verify_registry_service_token(service_token, http_request):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Invalid service token"
        )
    
    # Get transaction from database
    transaction = db.query(TEGTransaction).filter(
        TEGTransaction.transaction_id == transaction_id
    ).first()
    
    if not transaction:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    
    # §TRUSTCHAIN (2026-09-12): the answer comes from the transaction row, which every worker
    # sees, instead of a per-process dict that answered "no" on eight of nine workers. The row
    # records THAT a signal was applied and not its value, so `signal_value` and
    # `signal_timestamp` are honest Nones rather than a value one worker happened to remember.
    has_signaled = bool(transaction.reputation_signal_applied) and transaction.sender_agent_id == agent_did
    signal_data = None

    # Determine if agent can signal
    can_signal = (
        not has_signaled and
        transaction.sender_agent_id == agent_did and
        transaction.status == TransactionStatus.COMPLETED and
        datetime.now(timezone.utc) - transaction.timestamp <= timedelta(days=30)
    )
    
    # Build reason if cannot signal
    reason = None
    if not can_signal and not has_signaled:
        if transaction.sender_agent_id != agent_did:
            reason = "Not the transaction sender"
        elif transaction.status != TransactionStatus.COMPLETED:
            reason = "Transaction not completed"
        elif datetime.now(timezone.utc) - transaction.timestamp > timedelta(days=30):
            reason = "Signal period expired"
    
    return ReputationSignalStatus(
        has_signaled=has_signaled,
        signal_value=signal_data["signal_value"] if signal_data else None,
        signal_timestamp=signal_data["timestamp"] if signal_data else None,
        can_signal=can_signal,
        reason=signal_data["reason"] if signal_data else reason
    )
