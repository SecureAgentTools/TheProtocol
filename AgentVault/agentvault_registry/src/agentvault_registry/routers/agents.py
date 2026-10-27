"""API endpoints for agent-specific operations."""
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Security
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Agent, AgentCard
from ..security import get_current_agent
from ..schemas import BaseModel, Field
from ..routers.websocket import send_notification, manager
from ..event_emitter import get_event_emitter
import asyncio

# OWL20-PREP: Event Store integration for operational events
event_emitter = get_event_emitter()

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/agents",
    tags=["Agents"],
    dependencies=[Security(get_current_agent)]  # All endpoints require agent authentication
)


# --- Response Models ---

class AgentSelfInfo(BaseModel):
    """Schema for agent's own information."""
    did: str = Field(..., description="The agent's DID")
    client_id: str = Field(..., description="OAuth client ID")
    status: str = Field(..., description="Account status (active, suspended, revoked)")
    creator_developer_id: int = Field(..., description="ID of the developer who created this agent")
    created_at: str = Field(..., description="ISO format creation timestamp")
    last_active_at: Optional[str] = Field(None, description="ISO format last activity timestamp")
    public_key_jwk: Optional[Dict[str, Any]] = Field(None, description="Agent's public key in JWK format")


# --- API Endpoints ---

@router.get("/me", response_model=AgentSelfInfo, summary="Get Current Agent Information")
async def get_agent_self(
    current_agent: Agent = Security(get_current_agent),
    db: AsyncSession = Depends(get_db)
) -> AgentSelfInfo:
    """
    Get the authenticated agent's own information.
    
    This endpoint allows agents to verify their identity and retrieve
    their account details using their OAuth access token.
    """
    logger.info(f"Agent {current_agent.did} requested self information")
    
    return AgentSelfInfo(
        did=current_agent.did,
        client_id=current_agent.client_id,
        status=current_agent.status,
        creator_developer_id=current_agent.creator_developer_id,
        created_at=current_agent.created_at.isoformat(),
        last_active_at=current_agent.last_active_at.isoformat() if current_agent.last_active_at else None,
        public_key_jwk=current_agent.public_key_jwk
    )


@router.get("/health", summary="Agent Health Check")
async def agent_health_check(
    current_agent: Agent = Security(get_current_agent)
) -> Dict[str, str]:
    """
    Simple health check endpoint for agents.
    
    Returns a success message if the agent is authenticated and active.
    This can be used by agents to verify their authentication is working.
    """
    logger.debug(f"Health check from agent {current_agent.did}")
    
    return {
        "status": "healthy",
        "did": current_agent.did,
        "message": "Agent authentication successful"
    }


@router.post("/heartbeat", summary="Agent Heartbeat")
async def agent_heartbeat(
    current_agent: Agent = Security(get_current_agent),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, str]:
    """
    Heartbeat endpoint for agents to signal they are still active.
    
    Updates the agent's last_active_at timestamp. This could be used
    for monitoring agent health and detecting inactive agents.
    """
    logger.debug(f"Heartbeat from agent {current_agent.did}")
    
    # The last_active_at is already updated by get_current_agent dependency
    # This endpoint mainly serves as an explicit way for agents to stay active
    
    # §TWOAGENT (2026-09-24): the OWNER's own activity goes to the owner. Without an audience it went to every connected
    # user on every worker, one tenant's agents and activity to all tenants (the #34 class).
    # Send WebSocket notification about agent activity
    await manager.broadcast({
        "type": "agent.heartbeat",
        "data": {
            "agent_id": current_agent.did,
            "timestamp": current_agent.last_active_at.isoformat() if current_agent.last_active_at else None,
            "message": f"Agent {current_agent.did} sent heartbeat"
        }
    }, audience=f"user_{current_agent.creator_developer_id}")
    
    # OWL20-PREP: Emit AgentHeartbeat to Event Store (liveness proof)
    asyncio.create_task(event_emitter.emit(
        event_type="AgentHeartbeat",
        aggregate_id=current_agent.did,
        data={
            "timestamp": current_agent.last_active_at.isoformat() if current_agent.last_active_at else None,
            "status": current_agent.status
        }
    ))
    
    return {
        "status": "acknowledged",
        "did": current_agent.did,
        "message": "Heartbeat received"
    }


@router.delete("/me", summary="Delete Current Agent", status_code=status.HTTP_204_NO_CONTENT)
async def delete_current_agent(
    current_agent: Agent = Security(get_current_agent),
    db: AsyncSession = Depends(get_db)
) -> None:
    """
    Delete (deactivate) the currently authenticated agent.
    
    This endpoint allows an agent to self-delete by setting its status to 'revoked'.
    The agent's credentials will no longer be valid after this operation.
    
    Note: This is a soft delete - the agent record remains in the database
    but is marked as revoked.
    """
    logger.info(f"Agent {current_agent.did} requested self-deletion")
    
    # Update agent status to revoked
    _old_status = current_agent.status
    current_agent.status = "revoked"
    # §MCPTEST30 (V0640): the agent's own delete retires its cards, as the owner's delete does (OWL24). They stayed
    # active, listed here and pulled by the peers as live: on 2026-10-24 every tester throwaway that deleted itself kept
    # its card (187 on sbx-alpha, 4 on each sandbox operator; the operators' newest two listed active on sbx-alpha).
    # Deactivating moves the card's updated_at, so the peers' pull carries it like the owner's delete.
    _cards = (await db.execute(select(AgentCard).where(
        AgentCard.agent_did == current_agent.did, AgentCard.is_active == True))).scalars().all()  # noqa: E712
    for _card in _cards:
        _card.is_active = False
    # §ENFPROP: a revoked agent whose card stays active must still reach the mirrors
    from agentvault_registry.services import enforcement_propagation as _ep
    await _ep.touch_native_card_no_commit(db, current_agent.did)
    await db.commit()

    logger.info(f"Agent {current_agent.did} has been revoked")

    # A1 (2026-07-24): agent.deleted / agent.status_changed were subscribable but never fired.
    from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
    asyncio.create_task(dispatch_webhook_for_agents(
        "agent.deleted",
        {"agent_did": current_agent.did, "mode": "soft", "deleted_by": "self"},
        [current_agent.did], source_label="agents.self_delete"))
    asyncio.create_task(dispatch_webhook_for_agents(
        "agent.status_changed",
        {"agent_did": current_agent.did, "old_status": _old_status, "new_status": "revoked",
         "reason": "self_delete"},
        [current_agent.did], source_label="agents.self_delete"))
    
    # OWL20-PREP: Emit AgentStatusChanged to Event Store
    asyncio.create_task(event_emitter.emit(
        event_type="AgentStatusChanged",
        aggregate_id=current_agent.did,
        data={
            "old_status": "active",
            "new_status": "revoked",
            "reason": "self_deletion"
        }
    ))
    
    # Send WebSocket notification about agent deletion
    await manager.broadcast({
        "type": "agent.deleted",
        "data": {
            "agent_id": current_agent.did,
            "message": f"Agent {current_agent.did} has been deleted"
        }
    }, audience=f"user_{current_agent.creator_developer_id}")
    
    # Return 204 No Content
    return None
