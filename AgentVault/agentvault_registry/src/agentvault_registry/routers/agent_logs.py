# Agent Logs Router
# routers/agent_logs.py

import logging
from typing import List, Optional, Union
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select, and_, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas, security
from ..database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/agents",
    # §pass56 PR-5: tags= dropped; main.py:include_router supplies "Agent Logs"
)

# HTTP Bearer for agent authentication
bearer_scheme = HTTPBearer(auto_error=False)

async def get_auth_context(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[dict]:
    """
    The caller of POST /agents/{did}/logs: {"type": "agent", "agent_did", "agent_id"} or {"type": "developer",
    "developer_id"}, or None.

    D6-281: resolved by the shared optional resolver (security.get_current_actor_for_read_optional), which refuses what
    every other agent and developer route refuses: an agent token whose credential was reset or rotated since it was
    issued, a suspended or revoked agent, an ended owner session; a developer token that is not a live ACCESS token
    (a refresh, password-set or 2FA partial token, a revoked token_version, a suspended or deleted account). This used
    to decode the token alone, so each of those kept writing log entries until the token expired.
    """
    if not credentials:
        return None
    actor = await security.get_current_actor_for_read_optional(
        db=db, authorization=f"Bearer {credentials.credentials}")
    if not actor:
        return None
    if actor.get("kind") == "agent":
        agent = actor.get("agent")
        return {"type": "agent", "agent_did": actor["agent_did"],
                "agent_id": str(getattr(agent, "id", "") or "") or None}
    return {"type": "developer", "developer_id": int(actor["developer"].id)}

async def _developer_owns_agent(db: AsyncSession, agent_did: str, developer_id: int) -> bool:
    """May this developer act on this agent's logs? The creator of the agent row, or the owner of a card the SERVER linked
    to it (`agent_cards.agent_did`, written when the agent is created; a submitted card's content never sets it).

    §MCPTEST30 (2026-10-01): the three log routes read `card_data['did']`, a field inside the card CONTENT its owner
    writes (POST /agent-cards/ keeps unknown top-level keys), so a card naming somebody else's DID read, deleted and
    wrote that agent's logs. Ownership now comes only from columns the server sets."""
    hit = (await db.execute(select(models.Agent.id).where(
        models.Agent.did == agent_did, models.Agent.creator_developer_id == developer_id).limit(1))).first()
    if hit is not None:
        return True
    hit = (await db.execute(select(models.AgentCard.id).where(
        models.AgentCard.agent_did == agent_did, models.AgentCard.developer_id == developer_id).limit(1))).first()
    return hit is not None


@router.get("/{agent_did}/logs", response_model=List[schemas.AgentLogRead])
async def get_agent_logs(
    agent_did: str,
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of logs to return"),
    offset: int = Query(0, ge=0, description="Number of logs to skip"),
    level: Optional[str] = Query(None, description="Filter by log level (DEBUG, INFO, WARN, ERROR)"),
    start_time: Optional[datetime] = Query(None, description="Filter logs after this time"),
    end_time: Optional[datetime] = Query(None, description="Filter logs before this time"),
):
    """
    Get logs for a specific agent.
    
    Only the agent's owner can view its logs.
    Returns logs in reverse chronological order (newest first).
    """
    if not await _developer_owns_agent(db, agent_did, current_developer.id):
        # Return empty list instead of 404 to avoid breaking the UI
        logger.warning(f"No agent found with DID {agent_did} for developer {current_developer.id}")
        return []
    
    # Build query for logs
    query = select(models.AgentLog).where(
        models.AgentLog.agent_did == agent_did
    )
    
    # Apply filters
    if level:
        query = query.where(models.AgentLog.level == level.upper())
    
    if start_time:
        query = query.where(models.AgentLog.timestamp >= start_time)
    
    if end_time:
        query = query.where(models.AgentLog.timestamp <= end_time)
    
    # Order by timestamp descending (newest first)
    query = query.order_by(desc(models.AgentLog.timestamp))
    
    # Apply pagination
    query = query.limit(limit).offset(offset)
    
    # Execute query
    result = await db.execute(query)
    logs = result.scalars().all()
    
    logger.info(f"Retrieved {len(logs)} logs for agent {agent_did}")
    
    return logs

@router.post("/{agent_did}/logs", response_model=schemas.AgentLogRead, status_code=status.HTTP_201_CREATED)
async def create_agent_log(
    agent_did: str,
    log_entry: schemas.AgentLogCreate,
    db: AsyncSession = Depends(get_db),
    auth_context: Optional[dict] = Depends(get_auth_context),
):
    """
    Create a new log entry for an agent.
    
    Supports both agent and developer authentication:
    - Agents can only create logs for their own DID
    - Developers can create logs for their agents (for testing/debugging)
    """
    # Check if we have valid authentication
    if not auth_context:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Handle based on authentication type
    if auth_context["type"] == "agent":
        # Agent authentication - verify they're logging to their own DID
        if agent_did != auth_context["agent_did"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Agents can only create logs for their own DID"
            )
        logger.debug(f"Agent {agent_did} creating log entry")
        
    elif auth_context["type"] == "developer":
        # Developer authentication - verify they own the agent
        developer_id = auth_context["developer_id"]
        
        if not await _developer_owns_agent(db, agent_did, developer_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found or not authorized"
            )
        
        logger.debug(f"Developer {developer_id} creating log entry for agent {agent_did}")
    
    # Create log entry
    db_log = models.AgentLog(
        agent_did=agent_did,
        level=log_entry.level.upper(),
        message=log_entry.message,
        source=log_entry.source,
        log_metadata=log_entry.log_metadata,
        timestamp=log_entry.timestamp or datetime.now(timezone.utc)
    )
    
    db.add(db_log)
    await db.commit()
    await db.refresh(db_log)
    
    logger.info(f"Created log entry for agent {agent_did}: {log_entry.level} - {log_entry.message[:50]}...")
    
    return db_log

@router.delete("/{agent_did}/logs")
async def delete_agent_logs(
    agent_did: str,
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(security.get_current_developer),
    before: Optional[datetime] = Query(None, description="Delete logs before this time"),
):
    """
    Delete logs for an agent.
    
    If 'before' is specified, only deletes logs older than that time.
    Otherwise, deletes all logs for the agent.
    """
    if not await _developer_owns_agent(db, agent_did, current_developer.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found or not authorized"
        )
    
    # Build delete query
    delete_stmt = delete(models.AgentLog).where(
        models.AgentLog.agent_did == agent_did
    )
    
    if before:
        delete_stmt = delete_stmt.where(models.AgentLog.timestamp < before)
    
    # Execute delete
    result = await db.execute(delete_stmt)
    await db.commit()
    
    deleted_count = result.rowcount
    logger.info(f"Deleted {deleted_count} logs for agent {agent_did}")
    
    return {"deleted": deleted_count}

# Add this router to main.py:
# from .routers import agent_logs
# app.include_router(agent_logs.router, prefix="/api/v1")
