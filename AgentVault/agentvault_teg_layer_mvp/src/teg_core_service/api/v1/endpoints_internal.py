"""Internal API endpoints for service-to-service communication.

These endpoints are secured and should only be accessible by trusted internal services
like the AgentVault Registry.
"""
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Security
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.status import HTTP_201_CREATED, HTTP_400_BAD_REQUEST

from ...api.auth import verify_admin_key
from ...database.db_session import get_db
from ...database.crud import AgentCRUD
from ...database.models import AgentTEGProfile
from .schemas import ErrorResponse

router = APIRouter()


# --- Request/Response Models ---

class CreateAgentProfileRequest(BaseModel):
    """Request model for creating an agent TEG profile."""
    agent_did: str = Field(..., description="The DID of the agent to create a profile for")


class CreateAgentProfileResponse(BaseModel):
    """Response model for agent TEG profile creation."""
    agent_did: str = Field(..., description="The DID of the agent")
    balance: str = Field(..., description="The initial token balance (always 0 for new profiles)")
    reputation_score: int = Field(..., description="The initial reputation score")
    account_status: str = Field(..., description="The account status")
    created: bool = Field(..., description="Whether a new profile was created (false if already existed)")


# --- API Endpoints ---

@router.post(
    "/create-agent-profile",
    response_model=CreateAgentProfileResponse,
    responses={
        201: {"model": CreateAgentProfileResponse, "description": "Profile created successfully"},
        200: {"model": CreateAgentProfileResponse, "description": "Profile already exists"},
        400: {"model": ErrorResponse, "description": "Bad Request"},
        403: {"model": ErrorResponse, "description": "Forbidden"},
    }
)
async def create_agent_profile(
    request: CreateAgentProfileRequest,
    is_admin: Annotated[bool, Security(verify_admin_key)],
    db: Session = Depends(get_db)
):
    """
    Create a TEG profile for a newly registered agent.
    
    This endpoint is idempotent - if the profile already exists, it returns
    the existing profile without creating a new one.
    
    This endpoint requires admin authentication and is intended to be called
    by the Registry immediately after an agent is successfully registered.
    
    Args:
        request: The create profile request containing the agent DID
        is_admin: Admin authentication verification
        db: Database session
        
    Returns:
        CreateAgentProfileResponse with profile details and creation status
    """
    agent_did = request.agent_did
    
    # Check if profile already exists
    existing_agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == agent_did
    ).first()
    
    if existing_agent:
        # Profile already exists - return existing profile (idempotent)
        return CreateAgentProfileResponse(
            agent_did=existing_agent.agent_id,
            balance=str(existing_agent.token_balance),
            reputation_score=existing_agent.reputation_score,
            account_status=existing_agent.account_status,
            created=False
        )
    
    try:
        # W2 guard (2026-05-05): refuse cross-frame profile creation.
        from ...database.home_frame_resolver import check_home_or_raise
        check_home_or_raise(agent_did)
        # Create new agent profile with default values
        new_agent = AgentTEGProfile(
            agent_id=agent_did,
            token_balance=Decimal("0"),
            audited_balance=Decimal("0"),
            reputation_score=0,
            account_status="active"
        )
        
        db.add(new_agent)
        db.commit()
        db.refresh(new_agent)
        
        return CreateAgentProfileResponse(
            agent_did=new_agent.agent_id,
            balance=str(new_agent.token_balance),
            reputation_score=new_agent.reputation_score,
            account_status=new_agent.account_status,
            created=True
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Failed to create agent profile: {str(e)}"
        )
