"""System-wide endpoints for activity feed and other public system information."""
import logging
from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import schemas, models
from agentvault_registry.database import get_db
from agentvault_registry.crud import system_event as system_event_crud

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/system",
    tags=["System"],
    # No authentication required for public system endpoints
)


@router.get(
    "/activity-feed",
    response_model=schemas.SystemEventListResponse,
    summary="Get System Activity Feed",
    description="Returns recent system-wide events like agent onboarding, federation requests, and payout cycles."
)
async def get_activity_feed(
    limit: int = Query(default=10, ge=1, le=50, description="Number of events to return"),
    offset: int = Query(default=0, ge=0, description="Number of events to skip"),
    db: AsyncSession = Depends(get_db)
) -> schemas.SystemEventListResponse:
    """
    Get recent system events for the activity feed.
    
    This is a public endpoint that shows recent activity across the TheProtocol ecosystem.
    Events are returned in reverse chronological order (newest first).
    """
    logger.info(f"Fetching activity feed with limit={limit}, offset={offset}")
    
    # Get recent events
    events = await system_event_crud.get_recent_system_events(
        db=db,
        limit=limit,
        offset=offset
    )
    
    # For now, return a simple total count
    # In production, you might want to add a separate count query
    total = len(events) + offset if len(events) == limit else len(events) + offset
    
    return schemas.SystemEventListResponse(
        items=[schemas.SystemEventRead.model_validate(event) for event in events],
        total=total
    )


@router.get(
    "/activity-feed/by-type/{event_type}",
    response_model=schemas.SystemEventListResponse,
    summary="Get System Events by Type",
    description="Returns system events filtered by type."
)
async def get_activity_by_type(
    event_type: str,
    limit: int = Query(default=10, ge=1, le=50, description="Number of events to return"),
    offset: int = Query(default=0, ge=0, description="Number of events to skip"),
    db: AsyncSession = Depends(get_db)
) -> schemas.SystemEventListResponse:
    """
    Get system events filtered by type.
    
    Event types include:
    - AGENT_ONBOARDED: New agent registered in the system
    - FEDERATION_REQUEST: New federation request received
    - FEDERATION_APPROVED: Federation request approved
    - REWARD_CYCLE: Reward distribution completed
    - GOVERNANCE_PROPOSAL: New governance proposal created
    - DISPUTE_FILED: New dispute filed
    """
    logger.info(f"Fetching activity feed for type={event_type} with limit={limit}, offset={offset}")
    
    # Get events by type
    events = await system_event_crud.get_system_events_by_type(
        db=db,
        event_type=event_type,
        limit=limit,
        offset=offset
    )
    
    # Simple total count
    total = len(events) + offset if len(events) == limit else len(events) + offset
    
    return schemas.SystemEventListResponse(
        items=[schemas.SystemEventRead.model_validate(event) for event in events],
        total=total
    )


logger.info("System router initialized.")
