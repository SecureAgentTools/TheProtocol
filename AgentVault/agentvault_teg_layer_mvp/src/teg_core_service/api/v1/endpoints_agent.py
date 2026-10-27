"""Agent-related API endpoints for TEG account initialization and management"""
from decimal import Decimal
from typing import Annotated
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Security
from sqlalchemy.orm import Session
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND, HTTP_409_CONFLICT

from ...core.security import verify_admin_token, verify_agent_token
from ...core.config import get_settings
from ...core.structured_logging import get_logger, LogContext, log_performance
from ...core.error_handling import TEGException, ErrorCode, agent_not_found_error
from ...core.supply_guard import refuse_nonzero_opening_balance  # §MONEY-R35
from ...database.db_session import get_db
from ...database.crud import AgentCRUD
from ...database.models import AgentTEGProfile, TEGTransaction, TEGAttestationLog
from pydantic import BaseModel, Field
from typing import List
from .schemas import (
    AgentInitializationRequest,
    AgentInitializationResponse,
    ErrorResponse
)


class BulkInitializeAgentsRequest(BaseModel):
    """Request schema for bulk agent initialization (agent endpoint)."""
    agent_ids: List[str] = Field(..., min_length=1, max_length=500)
    initial_balance: str = Field(default="0")
    initial_reputation: int = Field(default=0, ge=0, le=1000)

router = APIRouter()
settings = get_settings()
logger = get_logger(__name__)


@router.post(
    "/initialize-teg-account",
    response_model=AgentInitializationResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
        409: {"model": ErrorResponse, "description": "Conflict - Agent already initialized"},
    }
)
@log_performance("initialize_teg_account")
async def initialize_teg_account(
    request: AgentInitializationRequest,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db)
):
    """
    Initialize TEG account for a TheProtocol v1.0.0 agent.
    
    This endpoint creates the necessary TEG records for a new agent:
    - Creates TEG profile with initial balance (0)
    - Sets initial reputation score (0)
    - Logs the initialization event
    
    This endpoint is idempotent - calling it multiple times for the same
    agent will not create duplicate records or throw errors.
    
    Requires admin authentication (called by agentvault_registry backend).
    """
    with LogContext(
        logger,
        operation="initialize_teg_account",
        agent_id=request.agent_id
    ):
        try:
            # Check if agent already has TEG account
            existing_agent = db.query(AgentTEGProfile).filter(
                AgentTEGProfile.agent_id == request.agent_id
            ).first()
            
            if existing_agent:
                # Idempotent behavior - return existing data
                logger.info(f"TEG account already exists for agent {request.agent_id}")
                
                return AgentInitializationResponse(
                    agent_id=existing_agent.agent_did,
                    teg_account_status="existing",
                    initial_balance=existing_agent.token_balance,
                    initial_reputation_score=existing_agent.reputation_score,
                    initialized_at=existing_agent.created_at,
                    message="TEG account already initialized"
                )
            
            # Create new TEG account
            # §MONEY-R35: an opening balance here would write token_balance
            # directly — no mint event, no entry_type, no idempotency. Both
            # real callers already pass "0"; a non-zero value is refused.
            initial_balance = refuse_nonzero_opening_balance(
                request.initial_balance, rail="agent/initialize-teg-account"
            )
            initial_reputation = request.initial_reputation_score or 0
            
            # Ensure agent_id follows expected format.
            # Accept the current did:theprotocol: prefix (rebranded from the legacy
            # did:agentvault: prefix) plus the legacy did:cos: method. The old
            # did:agentvault:-only check rejected every real DID after the rebrand,
            # which is why new-developer TEG-account init was failing.
            _valid_did_prefixes = ("did:theprotocol:", "did:agentvault:", "did:cos:")
            if not request.agent_id.startswith(_valid_did_prefixes):
                raise TEGException(
                    status_code=HTTP_400_BAD_REQUEST,
                    error_code=ErrorCode.VALIDATION_INVALID_INPUT,
                    message="Invalid agent_id format",
                    detail="agent_id must start with 'did:theprotocol:' (or legacy 'did:agentvault:' / 'did:cos:')",
                    metadata={"agent_id": request.agent_id}
                )
            
            # Create agent profile
            new_agent = AgentCRUD.get_or_create(db, request.agent_id)
            
            # Set initial values (get_or_create returns existing if found)
            if new_agent.token_balance == 0 and new_agent.reputation_score == 0:
                # Only update if truly new (zero values)
                new_agent.token_balance = initial_balance
                new_agent.audited_balance = initial_balance
                new_agent.reputation_score = initial_reputation
                
                # Log initialization event.
                # ⚠ These three calls used to pass structured fields as KEYWORDS
                # (event_type=, agent_id=, ...). get_logger() returns a plain
                # stdlib logging.Logger, which accepts none of them, so every one
                # raised TypeError — caught by the generic `except Exception`
                # below and returned as 400 "Failed to initialize TEG account".
                # Because it fired BEFORE db.commit(), a first-time
                # initialisation through this rail created nothing and reported
                # failure. Measured 2026-09-04 on frame-a: the probe DID had no
                # row afterwards. Fields kept, folded into the message, which is
                # this file's own convention everywhere else.
                logger.info(
                    "agent_teg_account_initialized - event_type: agent_initialization, "
                    f"agent_id: {request.agent_id}, initial_balance: {initial_balance}, "
                    f"initial_reputation_score: {initial_reputation}, "
                    "initialization_source: admin_api, initialized_by: teg_admin"
                )
                
                db.commit()
                db.refresh(new_agent)
                
                logger.info(
                    f"TEG account initialized for agent {request.agent_id} - "
                    f"initial_balance: {initial_balance}, "
                    f"initial_reputation: {initial_reputation}"
                )
                
                # Log admin action for security
                logger.warning(
                    "ADMIN ACTION: TEG account initialization - "
                    f"action: teg_account_init, agent_id: {request.agent_id}, "
                    f"initial_balance: {initial_balance}, "
                    f"initial_reputation: {initial_reputation}"
                )
                
                return AgentInitializationResponse(
                    agent_id=new_agent.agent_did,
                    teg_account_status="created",
                    initial_balance=new_agent.token_balance,
                    initial_reputation_score=new_agent.reputation_score,
                    initialized_at=new_agent.created_at,
                    message="TEG account successfully initialized"
                )
            else:
                # Agent exists with non-zero values - treat as already initialized
                return AgentInitializationResponse(
                    agent_id=new_agent.agent_did,
                    teg_account_status="existing",
                    initial_balance=new_agent.token_balance,
                    initial_reputation_score=new_agent.reputation_score,
                    initialized_at=new_agent.created_at,
                    message="TEG account already initialized with existing values"
                )
            
        except TEGException:
            raise
        except Exception as e:
            logger.error(f"Failed to initialize TEG account: {e}", exc_info=True)
            raise TEGException(
                status_code=HTTP_400_BAD_REQUEST,
                error_code=ErrorCode.SYS_INTERNAL_ERROR,
                message="Failed to initialize TEG account",
                detail=str(e) if settings.debug else None
            )


@router.get(
    "/{agent_id}/teg-status",
    responses={
        200: {"description": "TEG account status"},
        404: {"model": ErrorResponse, "description": "Agent not found"},
    }
)
@log_performance("get_agent_teg_status")
async def get_agent_teg_status(
    agent_id: str,
    db: Session = Depends(get_db)
):
    """
    Check if an agent has an initialized TEG account.
    
    This endpoint can be used to verify if an agent needs initialization
    before performing TEG operations.
    """
    with LogContext(
        logger,
        operation="get_agent_teg_status",
        agent_id=agent_id
    ):
        agent = db.query(AgentTEGProfile).filter(
            AgentTEGProfile.agent_id == agent_id
        ).first()
        
        if not agent:
            return {
                "agent_id": agent_id,
                "teg_initialized": False,
                "message": "Agent does not have a TEG account"
            }
        
        return {
            "agent_id": agent_id,
            "teg_initialized": True,
            "balance": agent.token_balance,
            "reputation_score": agent.reputation_score,
            "created_at": agent.created_at,
            "message": "Agent has active TEG account"
        }


@router.post(
    "/initialize",
    responses={
        200: {"description": "TEG account initialized"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    }
)
@log_performance("initialize_agent")
async def initialize_agent(
    agent_id: Annotated[str, Security(verify_agent_token)],
    db: Session = Depends(get_db)
):
    """
    Initialize TEG account for authenticated agent.
    
    This is a simplified version that agents can call directly.
    It's idempotent - calling multiple times has no effect.
    """
    with LogContext(
        logger,
        operation="initialize_agent",
        agent_id=agent_id
    ):
        # Check if already initialized
        existing = db.query(AgentTEGProfile).filter(
            AgentTEGProfile.agent_id == agent_id
        ).first()
        
        if existing:
            # Get actual counts from DB
            tx_count = db.query(TEGTransaction).filter(
                (TEGTransaction.sender_agent_id == agent_id) | (TEGTransaction.receiver_agent_id == agent_id)
            ).count()
            att_count = db.query(TEGAttestationLog).filter(
                TEGAttestationLog.agent_did == agent_id
            ).count()

            return {
                "agent_id": agent_id,
                "status": "initialized",
                "teg_account": {
                    "balance": str(existing.token_balance) if existing.token_balance != 0 else "0",
                    "reputation_score": existing.reputation_score,
                    "account_status": "active",
                    "created_at": existing.created_at.isoformat(),
                    "transaction_count": tx_count,
                    "attestation_count": att_count
                },
                "is_new_account": False
            }
        
        # Create new account
        new_agent = AgentCRUD.get_or_create(db, agent_id)
        
        # Check for welcome bonus
        welcome_bonus = Decimal("0")
        welcome_bonus_applied = False
        if hasattr(settings, 'welcome_bonus_amount') and settings.welcome_bonus_amount > 0:
            welcome_bonus = Decimal(str(settings.welcome_bonus_amount))
            new_agent.token_balance = welcome_bonus
            new_agent.audited_balance = welcome_bonus
            welcome_bonus_applied = True
        
        db.commit()
        db.refresh(new_agent)
        
        response = {
            "agent_id": agent_id,
            "status": "initialized",
            "teg_account": {
                "balance": str(new_agent.token_balance) if new_agent.token_balance != 0 else "0",
                "reputation_score": new_agent.reputation_score,
                "account_status": "active",
                "created_at": new_agent.created_at.isoformat(),
                "transaction_count": 0,
                "attestation_count": 0
            },
            "is_new_account": True
        }
        
        if welcome_bonus_applied:
            response["welcome_bonus_applied"] = True
            
        return response


@router.get(
    "/profile",
    responses={
        200: {"description": "Agent profile"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    }
)
@log_performance("get_agent_profile")
async def get_agent_profile(
    agent_id: Annotated[str, Security(verify_agent_token)],
    db: Session = Depends(get_db)
):
    """
    Get profile for authenticated agent.
    """
    agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == agent_id
    ).first()
    
    if not agent:
        # Auto-create if doesn't exist
        agent = AgentCRUD.get_or_create(db, agent_id)
        db.commit()
        db.refresh(agent)
    
    # Get account status from database
    account_status = agent.account_status
    
    return {
        "agent_id": agent_id,
        "teg_profile": {
            "token_balance": str(agent.token_balance) if agent.token_balance != 0 else "0",
            "reputation_score": agent.reputation_score,
            "account_status": account_status,
            "created_at": agent.created_at.isoformat(),
            "updated_at": agent.updated_at.isoformat() if agent.updated_at else agent.created_at.isoformat()
        }
    }


@router.get(
    "/onboarding/status",
    responses={
        200: {"description": "Onboarding status"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    }
)
async def get_onboarding_status(
    agent_id: Annotated[str, Security(verify_agent_token)],
    db: Session = Depends(get_db)
):
    """
    Get onboarding status for authenticated agent.
    """
    agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == agent_id
    ).first()
    
    is_onboarded = agent is not None
    
    return {
        "agent_id": agent_id,
        "is_onboarded": is_onboarded,
        "required_steps": [
            "account_initialization",
            "capability_registration",
            "identity_attestation"
        ],
        "completed_steps": {
            "account_initialized": is_onboarded
        }
    }


# MVP implementations for agent endpoints
@router.put(
    "/profile/metadata",
    responses={
        200: {"description": "Metadata updated"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    }
)
async def update_agent_metadata(
    agent_id: Annotated[str, Security(verify_agent_token)],
    metadata: dict,
    db: Session = Depends(get_db)
):
    """Update agent metadata - MVP implementation"""
    # For MVP, just verify agent exists and return success
    agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == agent_id
    ).first()
    
    if not agent:
        agent = AgentCRUD.get_or_create(db, agent_id)
        db.commit()
    
    # In a full implementation, we'd store metadata
    # For MVP, just return success
    return {
        "agent_id": agent_id,
        "status": "metadata_updated",
        "metadata": metadata,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }


@router.post(
    "/capabilities/register",
    responses={
        200: {"description": "Capabilities registered"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    }
)
async def register_capabilities(
    agent_id: Annotated[str, Security(verify_agent_token)],
    capabilities: dict,
    db: Session = Depends(get_db)
):
    """Register agent capabilities - MVP implementation"""
    # For MVP, just verify agent exists and return success
    agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == agent_id
    ).first()
    
    if not agent:
        agent = AgentCRUD.get_or_create(db, agent_id)
        db.commit()
    
    # Extract the capabilities array from the request
    capability_list = capabilities.get("capabilities", []) if isinstance(capabilities, dict) else capabilities
    
    return {
        "agent_id": agent_id,
        "status": "capabilities_registered",
        "capabilities": capabilities,
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "registered_capabilities": capability_list
    }


@router.post(
    "/services/register",
    responses={
        200: {"description": "Services registered"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    }
)
async def register_services(
    agent_id: Annotated[str, Security(verify_agent_token)],
    services: dict,
    db: Session = Depends(get_db)
):
    """Register agent services - MVP implementation"""
    # For MVP, just verify agent exists and return success
    agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == agent_id
    ).first()
    
    if not agent:
        agent = AgentCRUD.get_or_create(db, agent_id)
        db.commit()
    
    # Extract the services array from the request
    service_list = services.get("services", []) if isinstance(services, dict) else services
    
    return {
        "agent_id": agent_id,
        "status": "services_registered",
        "services": services,
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "registered_services": service_list
    }


@router.post(
    "/deactivate",
    responses={
        200: {"description": "Agent deactivated"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    }
)
async def deactivate_agent(
    agent_id: Annotated[str, Security(verify_agent_token)],
    reason: dict,
    db: Session = Depends(get_db)
):
    """Deactivate agent account - MVP implementation"""
    # For MVP, just verify agent exists and return success
    agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == agent_id
    ).first()
    
    if not agent:
        raise agent_not_found_error(agent_id)
    
    # Update account status in database
    agent.account_status = "inactive"
    db.commit()
    
    return {
        "agent_id": agent_id,
        "status": "deactivated",
        "reason": reason,
        "deactivated_at": datetime.now(timezone.utc).isoformat()
    }


@router.get(
    "/onboarding/requirements",
    responses={
        200: {"description": "Onboarding requirements"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    }
)
async def get_onboarding_requirements(
    agent_id: Annotated[str, Security(verify_agent_token)],
    db: Session = Depends(get_db)
):
    """Get onboarding requirements - MVP implementation"""
    # Check agent status
    agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == agent_id
    ).first()
    
    has_capabilities = False  # In MVP, we don't track this
    has_attestation = False   # In MVP, we don't track this
    has_min_reputation = agent and agent.reputation_score >= 0
    
    requirements = [
        {
            "requirement": "minimum_reputation",
            "description": "Minimum reputation score",
            "met": has_min_reputation
        },
        {
            "requirement": "capability_registration",
            "description": "Register at least one capability",
            "met": has_capabilities
        },
        {
            "requirement": "identity_attestation",
            "description": "Complete identity attestation",
            "met": has_attestation
        }
    ]
    
    met = [r for r in requirements if r["met"]]
    pending = [r for r in requirements if not r["met"]]
    
    return {
        "agent_id": agent_id,
        "requirements": requirements,
        "met": met,
        "pending": pending
    }


@router.get(
    "/onboarding/stages",
    responses={
        200: {"description": "Onboarding stages"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    }
)
async def get_onboarding_stages(
    agent_id: Annotated[str, Security(verify_agent_token)],
    db: Session = Depends(get_db)
):
    """Get onboarding stages - MVP implementation"""
    # Check if agent exists to determine current stage
    agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == agent_id
    ).first()
    
    current_stage = 1 if agent else 0
    
    stages = [
        {
            "stage_id": "account_init",
            "stage_name": "Account Initialization",
            "description": "Initialize TEG account",
            "required": True,
            "completed": agent is not None
        },
        {
            "stage_id": "capability_registration",
            "stage_name": "Capability Registration",
            "description": "Register agent capabilities",
            "required": False,
            "completed": False
        },
        {
            "stage_id": "service_registration",
            "stage_name": "Service Registration",
            "description": "Register offered services",
            "required": False,
            "completed": False
        }
    ]
    
    completed_stages = [s for s in stages if s["completed"]]
    next_stage_data = None
    
    if current_stage < len(stages):
        next_stage_data = {
            "stage_name": stages[current_stage]["stage_name"],
            "requirements": ["Complete previous stages"],
            "rewards": ["Unlock new features"]
        }
    
    return {
        "agent_id": agent_id,
        "current_stage": current_stage,
        "completed_stages": completed_stages,
        "next_stage": next_stage_data,
        "total_stages": len(stages)
    }


@router.get(
    "/onboarding/rewards",
    responses={
        200: {"description": "Onboarding rewards"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    }
)
async def get_onboarding_rewards(
    agent_id: Annotated[str, Security(verify_agent_token)],
    db: Session = Depends(get_db)
):
    """Get onboarding rewards - MVP implementation"""
    return {
        "agent_id": agent_id,
        "available_rewards": [
            {
                "reward_id": "welcome_bonus",
                "name": "Welcome Bonus",
                "description": "Initial tokens for new agents",
                "amount": "0",
                "claimed": True
            },
            {
                "reward_id": "first_capability",
                "name": "First Capability Bonus",
                "description": "Reward for registering first capability",
                "amount": "0",
                "claimed": False
            }
        ],
        "total_claimed": "0",
        "total_available": "0",
        "total_rewards_earned": "0",
        "reward_history": []
    }


# Admin endpoints
@router.post(
    "/bulk-initialize",
    responses={
        200: {"description": "Agents bulk initialized"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    }
)
@log_performance("bulk_initialize_agents")
async def bulk_initialize_agents(
    payload: BulkInitializeAgentsRequest,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db)
):
    """Bulk initialize multiple agents - Admin only"""
    agent_ids = payload.agent_ids
    # §MONEY-R35: accounts are created at zero; funding has its own rail.
    initial_balance = refuse_nonzero_opening_balance(
        payload.initial_balance, rail="agent/bulk-initialize"
    )
    initial_reputation = payload.initial_reputation
    
    details = []
    successful = 0
    failed = 0
    
    for agent_id in agent_ids:
        try:
            # Get or create agent
            agent = AgentCRUD.get_or_create(db, agent_id)
            # §MONEY-R35: this assignment used to be UNCONDITIONAL, so calling
            # bulk-initialize on an agent that already held a balance OVERWROTE
            # it — a destruction path, not only a creation one. Its sibling in
            # endpoints_admin.py always had the `== 0` guard; this one did not.
            # Only ever initialise a genuinely new (zero) account.
            if agent.token_balance == 0 and agent.reputation_score == 0:
                agent.token_balance = initial_balance
                agent.audited_balance = initial_balance
                agent.reputation_score = initial_reputation
                db.commit()
                db.refresh(agent)
                status_word = "success"
            else:
                status_word = "existing"

            details.append({
                "agent_id": agent_id,
                "status": status_word,
                "balance": str(agent.token_balance)
            })
            successful += 1
        except Exception as e:
            details.append({
                "agent_id": agent_id,
                "status": "failed",
                "error": str(e)
            })
            failed += 1
    
    return {
        "total_processed": len(agent_ids),
        "successful": successful,
        "failed": failed,
        "details": details
    }


@router.post(
    "/{agent_id}/reactivate",
    responses={
        200: {"description": "Agent reactivated"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Agent not found"},
    }
)
@log_performance("reactivate_agent")
async def reactivate_agent(
    agent_id: str,
    is_admin: Annotated[bool, Security(verify_admin_token)],
    db: Session = Depends(get_db)
):
    """Reactivate a deactivated agent - Admin only"""
    agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == agent_id
    ).first()
    
    if not agent:
        raise agent_not_found_error(agent_id)
    
    # Update account status in database
    agent.account_status = "active"
    db.commit()
    
    return {
        "agent_id": agent_id,
        "status": "reactivated",
        "reactivated_at": datetime.now(timezone.utc).isoformat()
    }
