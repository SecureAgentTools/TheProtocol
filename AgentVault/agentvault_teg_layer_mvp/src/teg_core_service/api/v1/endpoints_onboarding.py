"""Onboarding protocol API endpoints

Implements the Concierge-OS Self-Onboarding Protocol for secure agent registration.
This module provides endpoints for bootstrap token issuance and agent self-registration.
"""
import secrets
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Header, Security
from sqlalchemy.orm import Session
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_401_UNAUTHORIZED, HTTP_429_TOO_MANY_REQUESTS

from ...api.auth import verify_admin_key, get_current_agent
from ...core.config import get_settings
from ...core.error_handling import TEGException, ErrorCode
from ...database.db_session import get_db
from ...database.crud import BootstrapTokenCRUD, AgentCRUD, TransferService
from .schemas import (
    BootstrapTokenRequest,
    BootstrapTokenResponse,
    AgentRegisterRequest,
    AgentRegisterResponse,
    ErrorResponse
)

router = APIRouter()
settings = get_settings()

# §MONEY-R31 (2026-09-04): the rate limit below is PER PROCESS, and the TEG runs
# 8-9 gunicorn workers, so the effective limit is ~8x the number stated and it
# resets on every recreate. Same class as the in-process worker state that made
# §SUPPORTBATCH1 unreadable across 38 workers. Shared state belongs in Redis; the
# rail has no production caller today (the registry runs its own bootstrap flow),
# so this is recorded rather than rebuilt. Retiring it is decision D8.
# Rate limiting configuration (in-memory, per worker)
_token_requests_per_creator = {}
TOKEN_REQUEST_LIMIT_PER_HOUR = 10
BOOTSTRAP_TOKEN_EXPIRY_SECONDS = 300  # 5 minutes
INITIAL_FUNDING_AMOUNT = "100.0"  # Initial AVT grant from faucet


def _generate_bootstrap_token() -> str:
    """Generate a secure bootstrap token"""
    prefix = "bst"
    unique_id = secrets.token_hex(8)  # 16 characters
    random_suffix = secrets.token_hex(6)  # 12 characters
    return f"{prefix}_{unique_id}_{random_suffix}"


def _generate_agent_did(method: str) -> str:
    """Generate a new agent DID based on the requested method"""
    if method == "cos":
        # Concierge-OS native DID format
        return f"did:cos:{uuid4()}"
    else:
        # Default to simple format for MVP
        return f"did:{method}:{uuid4()}"


def _generate_client_credentials() -> tuple[str, str]:
    """Generate OAuth client credentials for the agent"""
    client_id = f"agent-{uuid4()}"
    client_secret = f"cos_secret_{secrets.token_urlsafe(32)}"
    return client_id, client_secret


def _check_rate_limit(creator_id: str) -> bool:
    """Simple in-memory rate limiting for MVP"""
    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)
    
    if creator_id not in _token_requests_per_creator:
        _token_requests_per_creator[creator_id] = []
    
    # Clean up old entries
    _token_requests_per_creator[creator_id] = [
        timestamp for timestamp in _token_requests_per_creator[creator_id]
        if timestamp > hour_ago
    ]
    
    # Check limit
    if len(_token_requests_per_creator[creator_id]) >= TOKEN_REQUEST_LIMIT_PER_HOUR:
        return False
    
    # Record this request
    _token_requests_per_creator[creator_id].append(now)
    return True


@router.post(
    "/bootstrap/request-token",
    response_model=BootstrapTokenResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized - Invalid or missing access token"},
        429: {"model": ErrorResponse, "description": "Too Many Requests - Rate limit exceeded"},
    }
)
async def request_bootstrap_token(
    request: BootstrapTokenRequest,
    creator_id: Annotated[str, Security(get_current_agent)],  # Agent creator must be authenticated
    db: Session = Depends(get_db)
):
    """
    Request a bootstrap token for creating a new agent.
    
    This endpoint is called by an authenticated Agent Creator (developer, platform service, etc.)
    to obtain a single-use bootstrap token. The token can then be given to a new agent
    for self-registration.
    
    **Authentication**: Requires valid Bearer token from the Agent Creator
    
    **Rate Limiting**: Maximum 10 tokens per creator per hour
    
    **Token Validity**: 5 minutes
    """
    # Check rate limit
    if not _check_rate_limit(creator_id):
        raise HTTPException(
            status_code=HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Maximum 10 bootstrap tokens per hour."
        )
    
    # Generate token details
    token_value = _generate_bootstrap_token()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=BOOTSTRAP_TOKEN_EXPIRY_SECONDS)
    
    try:
        # Create token in database
        token = BootstrapTokenCRUD.create_bootstrap_token(
            db=db,
            token_value=token_value,
            expires_at=expires_at,
            agent_type_hint=request.agent_type_hint,
            requested_by=request.requested_by or creator_id
        )
        
        return BootstrapTokenResponse(
            bootstrap_token=token_value,
            expires_in=BOOTSTRAP_TOKEN_EXPIRY_SECONDS,
            expires_at=expires_at
        )
        
    except ValueError as e:
        # Shouldn't happen with proper token generation, but handle it
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.SYS_INTERNAL_ERROR,
            message="Failed to create bootstrap token",
            detail=str(e)
        )


@router.post(
    "/onboard/register",
    response_model=AgentRegisterResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request - Invalid request or PoW solution"},
        401: {"model": ErrorResponse, "description": "Unauthorized - Invalid, expired, or already used token"},
    }
)
async def register_agent(
    request: AgentRegisterRequest,
    bootstrap_token: str = Header(..., alias="Bootstrap-Token", description="Single-use bootstrap token"),
    db: Session = Depends(get_db)
):
    """
    Register a new agent using a bootstrap token.
    
    This endpoint is called by a new, uninitialized agent to complete its registration.
    The agent must provide a valid bootstrap token obtained from an Agent Creator.
    
    **Authentication**: Requires `Bootstrap-Token` header with a valid token
    
    **One-Time Use**: Each bootstrap token can only be used once
    
    **Response**: Returns permanent credentials that must be stored securely.
    The `client_secret` is shown only once and cannot be retrieved later.
    """
    # Validate bootstrap token
    token = BootstrapTokenCRUD.get_active_bootstrap_token_by_value(db, bootstrap_token)
    
    if not token:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or already used bootstrap token"
        )
    
    # §MONEY-R31: proof of work is NOT validated. The route advertises
    # 400 "Invalid request or PoW solution" in its own responses={} block, which
    # promises a check that does not happen — an API documenting a control it does
    # not perform. The gate that actually holds is the single-use Bootstrap-Token,
    # issued only to an authenticated agent (verified live: request-token 403s
    # without auth). Either validate or stop advertising; both are D8.
    if request.proof_of_work_solution:
        # In production, validate the PoW solution here
        # For MVP, we'll accept any non-empty solution
        pass
    
    # Generate agent credentials
    agent_did = _generate_agent_did(request.agent_did_method)
    client_id, client_secret = _generate_client_credentials()
    
    try:
        # Create agent profile with initial balance
        agent = AgentCRUD.get_or_create(db, agent_did)
        
        # Issue initial funding from faucet (system treasury)
        try:
            faucet_transaction = TransferService.execute_issuance(
                db=db,
                receiver_id=agent_did,
                amount=Decimal(INITIAL_FUNDING_AMOUNT)
            )
            initial_funding_status = "completed"
            faucet_transaction_id = faucet_transaction.transaction_id
        except Exception as e:
            # Initial funding failed, but agent is created
            initial_funding_status = "failed"
            faucet_transaction_id = f"failed_{uuid4()}"
            # Log the error in production
        
        # Mark bootstrap token as used
        BootstrapTokenCRUD.mark_bootstrap_token_as_used(
            db=db,
            token_id=token.token_id,
            used_by_agent_did=agent_did
        )
        
        # §MONEY-R31: the credentials are returned to the caller and NOT persisted
        # here, so nothing on the TEG can later verify them — this rail cannot
        # authenticate the agent it just "registered". The registry's own onboarding
        # is the flow that issues and stores real credentials. Recorded, not
        # rebuilt: retiring this surface is D8.
        
        return AgentRegisterResponse(
            agent_did=agent_did,
            client_id=client_id,
            client_secret=client_secret,
            account_status="active",
            initial_funding_status=initial_funding_status,
            faucet_transaction_id=faucet_transaction_id
        )
        
    except Exception as e:
        # Rollback any changes
        db.rollback()
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.SYS_INTERNAL_ERROR,
            message="Agent registration failed",
            detail=str(e) if settings.debug else "Please try again later"
        )


# Admin endpoint for token cleanup (optional)
@router.delete(
    "/admin/bootstrap/cleanup-expired",
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    }
)
async def cleanup_expired_tokens(
    admin_token: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db)
):
    """
    Clean up expired bootstrap tokens.
    
    **Admin only**: Removes expired unused tokens from the database.
    This is a housekeeping operation to prevent database bloat.
    
    Returns the number of tokens deleted.
    """
    if not admin_token:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required"
        )
    
    deleted_count = BootstrapTokenCRUD.cleanup_expired_tokens(db)
    
    return {
        "status": "success",
        "deleted_tokens": deleted_count,
        "message": f"Cleaned up {deleted_count} expired tokens"
    }
