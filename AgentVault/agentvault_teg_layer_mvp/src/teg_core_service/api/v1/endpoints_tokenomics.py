"""
Tokenomics endpoints for TEG Core Service

This module provides endpoints for token balance queries and lock/unlock
operations used by the staking system.

Created as part of the staking integration fix.
"""
from decimal import Decimal
from datetime import datetime, timezone
from typing import Annotated, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Header, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, text

# §pass54 PR-3-expansion: APIKeyHeader spec markers for X-Service-Token +
# X-Agent-DID. auto_error=False preserves the existing runtime check (handler
# still validates value); this only annotates the OpenAPI surface so SDK
# generators emit `security: [{ServiceToken: [], AgentDID: []}]` instead of
# `security: null`. Closes T-P0-3 swagger audit gap on /tokenomics/* mutators.
_service_token_header = APIKeyHeader(
    name="X-Service-Token",
    scheme_name="ServiceToken",
    description="Service token (lock/unlock authorization). Required on staking integration endpoints.",
    auto_error=False,
)
_agent_did_header = APIKeyHeader(
    name="X-Agent-DID",
    scheme_name="AgentDID",
    description="Agent DID for the principal whose tokens are being moved.",
    auto_error=False,
)
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_403_FORBIDDEN, HTTP_404_NOT_FOUND

from ...api.auth import get_current_agent
from ...core.config import get_settings
from ...core.error_handling import TEGException, ErrorCode
from ...database.db_session import get_db
from ...database.models import AgentTEGProfile, TEGTransaction, TransactionStatus
# from ...database.crud import AgentCRUD  # Not needed for this implementation
from pydantic import BaseModel, Field

import logging

logger = logging.getLogger(__name__)

router = APIRouter()
settings = get_settings()


class TokenBalanceResponse(BaseModel):
    """Response for token balance query"""
    agent_id: str
    balance: Decimal = Field(..., description="Available (unlocked) balance")
    locked_balance: Decimal = Field(default=Decimal("0"), description="Locked balance (e.g., for staking)")
    total_balance: Decimal = Field(..., description="Total balance (available + locked)")


class TokenLockRequest(BaseModel):
    """Request to lock tokens"""
    agent_did: str = Field(..., description="DID of the agent whose tokens to lock")
    amount: Decimal = Field(..., gt=0, description="Amount to lock")
    purpose: str = Field(default="staking", description="Purpose of locking (e.g., staking, escrow)")


class TokenLockResponse(BaseModel):
    """Response from token lock operation"""
    transaction_id: str
    agent_id: str
    amount: Decimal
    locked: bool
    new_available_balance: Decimal
    new_locked_balance: Decimal
    timestamp: datetime


class TokenUnlockRequest(BaseModel):
    """Request to unlock tokens"""
    agent_did: str = Field(..., description="DID of the agent whose tokens to unlock")
    amount: Decimal = Field(..., gt=0, description="Amount to unlock")
    purpose: str = Field(default="unstaking", description="Purpose of unlocking")


class TokenUnlockResponse(BaseModel):
    """Response from token unlock operation"""
    transaction_id: str
    agent_id: str
    amount: Decimal
    unlocked: bool
    new_available_balance: Decimal
    new_locked_balance: Decimal
    timestamp: datetime


class LockedBalanceResponse(BaseModel):
    """Response for locked balance query"""
    agent_id: str
    locked_balance: Decimal


@router.get(
    "/balance/{agent_did}",
    response_model=TokenBalanceResponse,
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden"},
        404: {"description": "Agent not found"},
    }
)
async def get_agent_balance_service(
    http_request: Request,
    agent_did: str,
    service_token: Optional[str] = Security(_service_token_header),
    db: Session = Depends(get_db)
):
    """
    Get token balance for any agent - Registry service endpoint.
    
    This endpoint is used by the Registry service to query agent balances
    when processing staking operations.
    
    Requires Registry service token authentication.
    """
    # Verify Registry service token
    if not verify_registry_service_token(service_token, http_request):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Invalid service token"
        )
    
    # Get agent from database
    agent = db.query(AgentTEGProfile).filter(AgentTEGProfile.agent_id == agent_did).first()
    if not agent:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    
    # Calculate balances
    available_balance = agent.token_balance
    locked_balance = getattr(agent, 'locked_balance', Decimal("0"))
    total_balance = available_balance + locked_balance
    
    return TokenBalanceResponse(
        agent_id=agent_did,
        balance=available_balance,
        locked_balance=locked_balance,
        total_balance=total_balance
    )


@router.get(
    "/balance",
    response_model=TokenBalanceResponse,
    responses={
        401: {"description": "Unauthorized"},
    }
)
async def get_token_balance(
    agent_id: Annotated[str, Security(get_current_agent)],
    db: Session = Depends(get_db)
):
    """
    Get comprehensive token balance for authenticated agent.
    
    Returns:
    - balance: Available (unlocked) tokens
    - locked_balance: Tokens locked for staking or other purposes
    - total_balance: Sum of available and locked
    
    Requires agent authentication via Bearer token.
    """
    # Get agent from database
    agent = db.query(AgentTEGProfile).filter(AgentTEGProfile.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    
    # Calculate balances
    available_balance = agent.token_balance
    locked_balance = getattr(agent, 'locked_balance', Decimal("0"))
    total_balance = available_balance + locked_balance
    
    return TokenBalanceResponse(
        agent_id=agent_id,
        balance=available_balance,
        locked_balance=locked_balance,
        total_balance=total_balance
    )


@router.get(
    "/locked_balance",
    response_model=LockedBalanceResponse,
    responses={
        401: {"description": "Unauthorized"},
    }
)
async def get_locked_balance(
    agent_id: Annotated[str, Security(get_current_agent)],
    db: Session = Depends(get_db)
):
    """
    Get only the locked token balance for authenticated agent.
    
    This endpoint is useful for systems that only need to know
    about locked tokens (e.g., staking queries).
    
    Requires agent authentication via Bearer token.
    """
    # Get agent from database
    agent = db.query(AgentTEGProfile).filter(AgentTEGProfile.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    
    locked_balance = getattr(agent, 'locked_balance', Decimal("0"))
    
    return LockedBalanceResponse(
        agent_id=agent_id,
        locked_balance=locked_balance
    )


@router.post(
    "/lock",
    response_model=TokenLockResponse,
    responses={
        400: {"description": "Bad Request - Insufficient balance"},
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden - Invalid service token"},
    }
)
async def lock_tokens(
    http_request: Request,
    request: TokenLockRequest,
    db: Session = Depends(get_db),
    service_token: Optional[str] = Security(_service_token_header),
    agent_did_header: Optional[str] = Security(_agent_did_header)
):
    """
    Lock tokens for staking or other purposes.
    
    This endpoint is called by the Registry service when an agent
    initiates staking. It moves tokens from available balance to
    locked balance.
    
    Authentication:
    - Requires Registry service token
    - Agent DID passed in header
    
    Process:
    1. Verify service token
    2. Check agent has sufficient available balance
    3. Move tokens from available to locked
    4. Create transaction record
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
    
    # Get agent from database
    agent = db.query(AgentTEGProfile).filter(AgentTEGProfile.agent_id == request.agent_did).first()
    if not agent:
        # W2 guard (2026-05-05): refuse cross-frame profile creation.
        from ...database.home_frame_resolver import check_home_or_raise
        check_home_or_raise(request.agent_did)
        # Create agent if doesn't exist (with 0 balance)
        agent = AgentTEGProfile(
            agent_id=request.agent_did,
            token_balance=Decimal("0"),
            locked_balance=Decimal("0"),
            audited_balance=Decimal("0"),
            reputation_score=50
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)
    
    # Check sufficient available balance
    if agent.token_balance < request.amount:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance. Available: {agent.token_balance}, Requested: {request.amount}"
        )
    
    # Create transaction ID (without prefix to fit in VARCHAR(36) column)
    transaction_id = str(uuid4())
    
    try:
        # §pass77 Phase B: tag the staking lock so it is distinguishable from
        # cross-TEG escrow (both use locked_balance) in the L1 journal / ES projection.
        db.execute(text(
            "SELECT set_config('teg.entry_type','stake_lock',true),"
            " set_config('teg.entry_ref',:r,true)"
        ), {"r": str(getattr(request, 'purpose', ''))[:160]})
        # Move tokens from available to locked
        agent.token_balance -= request.amount
        if not hasattr(agent, 'locked_balance'):
            agent.locked_balance = Decimal("0")
        agent.locked_balance += request.amount
        # Keep audited_balance in sync (staking is legitimate)
        agent.audited_balance = agent.token_balance
        
        # Create transaction record
        transaction = TEGTransaction(
            transaction_id=transaction_id,
            sender_agent_id=request.agent_did,
            receiver_agent_id="SYSTEM_LOCK",
            amount=request.amount,
            fee_amount=Decimal("0"),
            status=TransactionStatus.COMPLETED,
            transaction_type="lock",
            attached_message=f"Token lock for {request.purpose}",
            timestamp=datetime.now(timezone.utc)
        )
        db.add(transaction)
        
        # Commit changes
        db.commit()
        db.refresh(agent)
        
        logger.info(f"Locked {request.amount} tokens for {request.agent_did}. Purpose: {request.purpose}")
        
        return TokenLockResponse(
            transaction_id=transaction_id,
            agent_id=request.agent_did,
            amount=request.amount,
            locked=True,
            new_available_balance=agent.token_balance,
            new_locked_balance=agent.locked_balance,
            timestamp=transaction.timestamp
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to lock tokens: {str(e)}")
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Failed to lock tokens: {str(e)}"
        )


@router.post(
    "/unlock",
    response_model=TokenUnlockResponse,
    responses={
        400: {"description": "Bad Request - Insufficient locked balance"},
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden - Invalid service token"},
    }
)
async def unlock_tokens(
    http_request: Request,
    request: TokenUnlockRequest,
    db: Session = Depends(get_db),
    service_token: Optional[str] = Security(_service_token_header),
    agent_did_header: Optional[str] = Security(_agent_did_header)
):
    """
    Unlock tokens from staking or other purposes.
    
    This endpoint is called by the Registry service when an agent
    initiates unstaking. It moves tokens from locked balance back
    to available balance.
    
    Authentication:
    - Requires Registry service token
    - Agent DID passed in header
    
    Process:
    1. Verify service token
    2. Check agent has sufficient locked balance
    3. Move tokens from locked to available
    4. Create transaction record
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
    
    # Get agent from database
    agent = db.query(AgentTEGProfile).filter(AgentTEGProfile.agent_id == request.agent_did).first()
    if not agent:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    
    # Check sufficient locked balance
    locked_balance = getattr(agent, 'locked_balance', Decimal("0"))
    if locked_balance < request.amount:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Insufficient locked balance. Locked: {locked_balance}, Requested: {request.amount}"
        )
    
    # Create transaction ID (without prefix to fit in VARCHAR(36) column)
    transaction_id = str(uuid4())
    
    try:
        # §pass77 Phase B: tag the staking unlock (unstake).
        db.execute(text(
            "SELECT set_config('teg.entry_type','stake_unlock',true),"
            " set_config('teg.entry_ref',:r,true)"
        ), {"r": str(getattr(request, 'purpose', ''))[:160]})
        # Move tokens from locked to available
        agent.locked_balance -= request.amount
        agent.token_balance += request.amount
        # Keep audited_balance in sync (unstaking is legitimate)
        agent.audited_balance = agent.token_balance
        
        # Create transaction record
        transaction = TEGTransaction(
            transaction_id=transaction_id,
            sender_agent_id="SYSTEM_LOCK",
            receiver_agent_id=request.agent_did,
            amount=request.amount,
            fee_amount=Decimal("0"),
            status=TransactionStatus.COMPLETED,
            transaction_type="unlock",
            attached_message=f"Token unlock for {request.purpose}",
            timestamp=datetime.now(timezone.utc)
        )
        db.add(transaction)
        
        # Commit changes
        db.commit()
        db.refresh(agent)
        
        logger.info(f"Unlocked {request.amount} tokens for {request.agent_did}. Purpose: {request.purpose}")
        
        return TokenUnlockResponse(
            transaction_id=transaction_id,
            agent_id=request.agent_did,
            amount=request.amount,
            unlocked=True,
            new_available_balance=agent.token_balance,
            new_locked_balance=agent.locked_balance,
            timestamp=transaction.timestamp
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to unlock tokens: {str(e)}")
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Failed to unlock tokens: {str(e)}"
        )


def verify_registry_service_token(token: str, request=None) -> bool:
    """Verify an internal registry caller.

    §2026-06-17 Phase 4 — mTLS SVID (presented via the nginx-teg sidecar) is PRIMARY; the
    legacy shared key is a fallback honored ONLY while TEG_MTLS_REQUIRED is false (shadow).
    Under enforce, only an accepted internal SVID passes — the shared key is rejected, so the
    key can be retired from the environment. Pass the FastAPI Request to enable the mTLS path.
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
