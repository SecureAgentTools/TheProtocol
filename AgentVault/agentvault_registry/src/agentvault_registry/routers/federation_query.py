"""API endpoints for internal federation queries between peer registries.

P1-003: Token validation now checks against PeerRegistry.federation_access_token
P3-001: Excessive [FEDERATION DEBUG] logging replaced with appropriate log levels
"""
import logging
from typing import List, Optional
import math

from fastapi import APIRouter, Depends, HTTPException, Query, Header, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .. import schemas, models
from ..database import get_db
from ..crud import agent_card

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/federation", tags=["Internal - Federation"])


async def verify_peer_token(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db)
) -> models.PeerRegistry:
    """Verify that the request comes from an authenticated peer registry.
    
    P1-003: Validates bearer token against PeerRegistry.federation_access_token
    in the database. Only ACTIVE peers with matching tokens are accepted.
    
    Returns:
        The authenticated PeerRegistry model instance
        
    Raises:
        HTTPException 401: If token is missing, malformed, or not found
        HTTPException 403: If peer is not in ACTIVE status
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Expected: Bearer <token>"
        )
    
    token = authorization[7:]  # Remove "Bearer " prefix
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token"
        )
    
    # Look up token in PeerRegistry table
    stmt = select(models.PeerRegistry).where(
        models.PeerRegistry.federation_access_token == token
    )
    result = await db.execute(stmt)
    peer = result.scalar_one_or_none()
    
    if not peer:
        logger.warning(f"Federation query rejected: unknown token (first 8 chars: {token[:8]}...)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or unrecognized peer token"
        )
    
    if peer.status != "ACTIVE":
        logger.warning(f"Federation query rejected: peer '{peer.name}' has status '{peer.status}'")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Peer registry '{peer.name}' is not active (status: {peer.status})"
        )
    
    logger.info(f"Federation query authenticated: peer '{peer.name}' (id={peer.id})")
    return peer


@router.post("/query", response_model=schemas.AgentCardListResponse)
async def federation_query(
    search: Optional[str] = Query(None, description="Search term for agent discovery"),
    tags: Optional[List[str]] = Query(None, description="Filter by tags"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    active_only: bool = Query(True, description="Only return active agents"),
    has_tee: Optional[bool] = Query(None, description="Filter for TEE-enabled agents"),
    tee_type: Optional[str] = Query(None, description="Filter by TEE type"),
    db: AsyncSession = Depends(get_db),
    peer: models.PeerRegistry = Depends(verify_peer_token)
) -> schemas.AgentCardListResponse:
    """Internal endpoint for peer registries to query our agent database.
    
    This endpoint is not meant for public use - it's only for authenticated
    peer registries to search our local agent database as part of the
    federation protocol.
    
    Requires: Bearer token authentication from a trusted, ACTIVE peer registry.
    Token must match a federation_access_token in the peer_registries table.
    """
    logger.info(
        f"Federation query from peer '{peer.name}': "
        f"search='{search}', tags={tags}, limit={limit}, offset={offset}"
    )
    
    try:
        # Use the existing agent card CRUD functions to search
        items, total_items = await agent_card.list_agent_cards(
            db=db,
            skip=offset,
            limit=limit,
            active_only=active_only,
            search=search,
            tags=tags,
            has_tee=has_tee,
            tee_type=tee_type
        )
        
        logger.info(f"Federation query returned {len(items)}/{total_items} agents for peer '{peer.name}'")
        
        # Calculate pagination info
        current_page = (offset // limit) + 1 if limit > 0 else 1
        total_pages = math.ceil(total_items / limit) if limit > 0 else (1 if total_items > 0 else 0)
        
        pagination_info = schemas.PaginationInfo(
            total_items=total_items,
            limit=limit,
            offset=offset,
            total_pages=total_pages,
            current_page=current_page,
        )
        
        # Convert to summary format and add origin registry info
        summaries = []
        for item in items:
            summary = schemas.AgentCardSummary.model_validate(item)
            summary_dict = summary.model_dump()
            summary_dict["origin_registry_name"] = "Local"
            summaries.append(schemas.AgentCardSummary.model_validate(summary_dict))
        
        return schemas.AgentCardListResponse(
            items=summaries,
            pagination=pagination_info
        )
        
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except SQLAlchemyError:
        raise   # §MCPTEST30 (V0546): answered by its cause (errors module); the CRUD no longer answers an empty page
    except Exception as e:
        logger.error(f"Error processing federation query from peer '{peer.name}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process federation query"
        )
