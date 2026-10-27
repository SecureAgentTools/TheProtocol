"""API endpoints for federated peer registry management (developer-facing)."""
from typing import List, Optional
import math
import logging

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status, Security
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from .. import schemas, models
from ..database import get_db
from ..security import get_current_developer
from ..crud import crud_peer_registry

router = APIRouter(prefix="/federation/peers", tags=["Federation Peers"])


@router.post("/", response_model=schemas.PeerRegistryRead, status_code=status.HTTP_201_CREATED)
async def register_peer_registry(
    peer_data: schemas.PeerRegistryCreate,
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Security(get_current_developer)
) -> schemas.PeerRegistryRead:
    """Register a new peer registry request.
    
    This endpoint allows developers to submit a request to register their
    TheProtocol Registry instance as a peer. The request will be pending
    approval by an administrator.
    
    Requires: Developer JWT authentication
    """
    try:
        db_peer = await crud_peer_registry.create_peer_registry_request(
            db=db,
            owner_id=current_developer.id,
            peer_data=peer_data
        )
        return schemas.PeerRegistryRead.model_validate(db_peer)
    except ValueError as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=400, detail="An internal error occurred")
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to create peer registry request")


@router.get("/", response_model=schemas.PeerRegistryPublicListResponse)
async def list_public_peer_registries(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of items to return"),
    db: AsyncSession = Depends(get_db)
) -> schemas.PeerRegistryPublicListResponse:
    """List all publicly approved (ACTIVE) peer registries.
    
    This endpoint is public and does not require authentication.
    Only peer registries with status='ACTIVE' are returned, without their administrators' contact e-mail (the admin
    federation routes, and the owner's GET /federation/peers/my/registrations, carry it).
    """
    # Get active peer registries
    peer_registries = await crud_peer_registry.list_active_peer_registries(db, skip=skip, limit=limit)
    
    # Get total count for pagination
    total_count = await crud_peer_registry.count_active_peer_registries(db)
    
    # Calculate pagination info
    total_pages = math.ceil(total_count / limit) if limit > 0 else 1
    current_page = (skip // limit) + 1 if limit > 0 else 1
    
    return schemas.PeerRegistryPublicListResponse(
        items=[schemas.PeerRegistryPublicRead.model_validate(pr) for pr in peer_registries],
        pagination=schemas.PaginationInfo(
            total_items=total_count,
            limit=limit,
            offset=skip,
            total_pages=total_pages,
            current_page=current_page
        )
    )


@router.get("/{peer_id}", response_model=schemas.PeerRegistryPublicRead)
async def get_public_peer_registry(
    peer_id: int,
    db: AsyncSession = Depends(get_db)
) -> schemas.PeerRegistryPublicRead:
    """Get details of a publicly approved peer registry.
    
    This endpoint is public and does not require authentication.
    Only returns details if the peer registry status is 'ACTIVE', without its administrator's contact e-mail.
    """
    db_peer = await crud_peer_registry.get_peer_registry_by_id(db, peer_id)
    
    if not db_peer:
        raise HTTPException(status_code=404, detail="Peer registry not found")
    
    if db_peer.status != "ACTIVE":
        raise HTTPException(status_code=404, detail="Peer registry not found")
    
    return schemas.PeerRegistryPublicRead.model_validate(db_peer)


@router.put("/{peer_id}", response_model=schemas.PeerRegistryRead)
async def update_owned_peer_registry(
    peer_id: int,
    update_data: schemas.PeerRegistryUpdate,
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Security(get_current_developer)
) -> schemas.PeerRegistryRead:
    """Update details of an owned peer registry.
    
    Developers can only update peer registries they own.
    Updateable fields: description, admin_contact_email, discovery_auth_info
    
    Requires: Developer JWT authentication
    """
    db_peer = await crud_peer_registry.get_peer_registry_by_id(db, peer_id)
    
    if not db_peer:
        raise HTTPException(status_code=404, detail="Peer registry not found")
    
    # Verify ownership
    if db_peer.owner_developer_id != current_developer.id:
        raise HTTPException(status_code=403, detail="You can only update peer registries you own")
    
    # Update the peer registry
    updated_peer = await crud_peer_registry.update_peer_registry_details(db, db_peer, update_data)
    
    return schemas.PeerRegistryRead.model_validate(updated_peer)


@router.delete("/{peer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_owned_peer_registry(
    peer_id: int,
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Security(get_current_developer)
) -> Response:
    """Deactivate an owned peer registry.
    
    Developers can only deactivate peer registries they own.
    This sets the status to 'INACTIVE'.
    
    Requires: Developer JWT authentication
    """
    db_peer = await crud_peer_registry.get_peer_registry_by_id(db, peer_id)
    
    if not db_peer:
        raise HTTPException(status_code=404, detail="Peer registry not found")
    
    # Verify ownership
    if db_peer.owner_developer_id != current_developer.id:
        raise HTTPException(status_code=403, detail="You can only deactivate peer registries you own")
    
    # Update status to INACTIVE
    await crud_peer_registry.update_peer_registry_status(db, db_peer, "INACTIVE")

    # A1 (2026-07-24): federation.peer_removed was subscribable but never fired. Broadcast.
    import asyncio as _aio
    from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_event
    _aio.create_task(dispatch_webhook_event(
        "federation.peer_removed",
        {"peer_id": peer_id, "peer_name": db_peer.name, "base_url": db_peer.base_url,
         "removed_by_developer_id": current_developer.id},
        source_label="federation.peer_delete"))

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/my/registrations", response_model=schemas.PeerRegistryListResponse)
async def list_my_peer_registries(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of items to return"),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Security(get_current_developer)
) -> schemas.PeerRegistryListResponse:
    """List all peer registries owned by the current developer.
    
    Returns all peer registries regardless of status.
    
    Requires: Developer JWT authentication
    """
    # Get peer registries owned by current developer
    peer_registries = await crud_peer_registry.get_peer_registries_by_owner(
        db, current_developer.id, skip=skip, limit=limit
    )
    
    # Count total for pagination
    from sqlalchemy import select, func
    stmt = select(func.count()).select_from(models.PeerRegistry).filter(
        models.PeerRegistry.owner_developer_id == current_developer.id
    )
    result = await db.execute(stmt)
    total_count = result.scalar()
    
    # Calculate pagination info
    total_pages = math.ceil(total_count / limit) if limit > 0 else 1
    current_page = (skip // limit) + 1 if limit > 0 else 1
    
    return schemas.PeerRegistryListResponse(
        items=[schemas.PeerRegistryRead.model_validate(pr) for pr in peer_registries],
        pagination=schemas.PaginationInfo(
            total_items=total_count,
            limit=limit,
            offset=skip,
            total_pages=total_pages,
            current_page=current_page
        )
    )
