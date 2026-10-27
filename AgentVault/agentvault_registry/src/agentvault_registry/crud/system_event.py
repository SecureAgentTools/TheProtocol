"""CRUD operations for SystemEvent model."""
import logging
from typing import List, Optional
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models

logger = logging.getLogger(__name__)


async def create_system_event(
    db: AsyncSession,
    event_type: str,
    title: str,
    description: str,
    event_metadata: Optional[dict] = None
) -> models.SystemEvent:
    """
    Create a new system event.
    
    Args:
        db: Database session
        event_type: Type of event (e.g., AGENT_ONBOARDED, FEDERATION_REQUEST)
        title: Short, human-readable title
        description: Detailed description
        event_metadata: Optional additional data
        
    Returns:
        Created SystemEvent object
    """
    logger.info(f"Creating system event: {event_type} - {title}")
    
    db_event = models.SystemEvent(
        event_type=event_type,
        title=title,
        description=description,
        event_metadata=event_metadata
    )
    
    db.add(db_event)
    await db.commit()
    await db.refresh(db_event)
    
    logger.info(f"Created system event with ID: {db_event.id}")
    return db_event


async def get_recent_system_events(
    db: AsyncSession,
    limit: int = 10,
    offset: int = 0
) -> List[models.SystemEvent]:
    """
    Get recent system events ordered by creation time (newest first).
    
    Args:
        db: Database session
        limit: Maximum number of events to return
        offset: Number of events to skip
        
    Returns:
        List of SystemEvent objects
    """
    logger.info(f"Fetching recent system events (limit={limit}, offset={offset})")
    
    stmt = (
        select(models.SystemEvent)
        .order_by(desc(models.SystemEvent.created_at))
        .limit(limit)
        .offset(offset)
    )
    
    result = await db.execute(stmt)
    events = result.scalars().all()
    
    logger.info(f"Found {len(events)} system events")
    return events


async def get_system_events_by_type(
    db: AsyncSession,
    event_type: str,
    limit: int = 10,
    offset: int = 0
) -> List[models.SystemEvent]:
    """
    Get system events of a specific type.
    
    Args:
        db: Database session
        event_type: Type of events to filter
        limit: Maximum number of events to return
        offset: Number of events to skip
        
    Returns:
        List of SystemEvent objects
    """
    logger.info(f"Fetching system events of type: {event_type}")
    
    stmt = (
        select(models.SystemEvent)
        .where(models.SystemEvent.event_type == event_type)
        .order_by(desc(models.SystemEvent.created_at))
        .limit(limit)
        .offset(offset)
    )
    
    result = await db.execute(stmt)
    events = result.scalars().all()
    
    logger.info(f"Found {len(events)} system events of type {event_type}")
    return events
