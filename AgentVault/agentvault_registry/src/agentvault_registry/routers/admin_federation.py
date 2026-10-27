"""API endpoints for federated peer registry management (admin-facing)."""
from typing import List, Optional
import math
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status, Security
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from .. import schemas, models
from ..database import get_db
from .. import security
from ..crud import crud_peer_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/federation/peers", tags=["Admin — Federation Peers"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _notify_peer(peer, template: str, subject: str, extra_ctx: dict) -> None:
    """Best-effort email to a peer registry's admin contact. Never raises —
    a mail failure must not block the federation state change."""
    contact = getattr(peer, "admin_contact_email", None)
    if not contact:
        return
    try:
        from ..email_utils import send_themed_email
        ctx = {
            "peer_name": getattr(peer, "name", None),
            "peer_base_url": getattr(peer, "base_url", None),
            **extra_ctx,
        }
        await send_themed_email(
            subject=subject, recipients=[contact], template=template,
            context=ctx, theme="neural",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[Federation] peer notification email failed (%s): %s", template, e)


@router.get("/pending", response_model=schemas.PeerRegistryListResponse)
async def list_pending_peer_registries(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of items to return"),
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation"))
) -> schemas.PeerRegistryListResponse:
    """List all peer registries pending approval.
    
    Returns only peer registries with status='PENDING_APPROVAL'.
    
    Requires: Admin Developer JWT authentication
    """
    # Get pending peer registries
    peer_registries = await crud_peer_registry.get_peer_registries_by_status(
        db, "PENDING_APPROVAL", skip=skip, limit=limit
    )
    
    # Get total count for pagination
    total_count = await crud_peer_registry.count_peer_registries_by_status(db, "PENDING_APPROVAL")
    
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


@router.post("/{peer_id}/approve", response_model=schemas.PeerRegistryRead)
async def approve_peer_registry(
    peer_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation"))
) -> schemas.PeerRegistryRead:
    """Approve a pending peer registry request.
    
    Updates status to 'ACTIVE' and sets approval metadata.
    Future enhancement: Generate shared secret or public key for inter-registry auth.
    
    Requires: Admin Developer JWT authentication
    """
    db_peer = await crud_peer_registry.get_peer_registry_by_id(db, peer_id)
    
    if not db_peer:
        raise HTTPException(status_code=404, detail="Peer registry not found")
    
    if db_peer.status != "PENDING_APPROVAL":
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot approve peer registry with status '{db_peer.status}'"
        )
    
    # Update status to ACTIVE with admin info
    updated_peer = await crud_peer_registry.update_peer_registry_status(
        db, db_peer, "ACTIVE", admin_id=current_admin.id
    )

    # TODO: Future - Generate and store shared secret or public key
    await _notify_peer(
        updated_peer, "federation_peer_approved",
        "TheProtocol — Your registry federation request was approved",
        {"approved_at": _now_iso()},
    )

    return schemas.PeerRegistryRead.model_validate(updated_peer)


@router.post("/{peer_id}/reject", response_model=schemas.PeerRegistryRead)
async def reject_peer_registry(
    peer_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation"))
) -> schemas.PeerRegistryRead:
    """Reject a pending peer registry request.
    
    Updates status to 'REJECTED'.
    
    Requires: Admin Developer JWT authentication
    """
    db_peer = await crud_peer_registry.get_peer_registry_by_id(db, peer_id)
    
    if not db_peer:
        raise HTTPException(status_code=404, detail="Peer registry not found")
    
    if db_peer.status != "PENDING_APPROVAL":
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot reject peer registry with status '{db_peer.status}'"
        )
    
    # Update status to REJECTED
    updated_peer = await crud_peer_registry.update_peer_registry_status(
        db, db_peer, "REJECTED", admin_id=current_admin.id
    )

    await _notify_peer(
        updated_peer, "federation_peer_rejected",
        "TheProtocol — Your registry federation request",
        {"rejected_at": _now_iso()},
    )

    return schemas.PeerRegistryRead.model_validate(updated_peer)


@router.post("/{peer_id}/deactivate", response_model=schemas.PeerRegistryRead)
async def deactivate_peer_registry(
    peer_id: int,
    reason: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation"))
) -> schemas.PeerRegistryRead:
    """Deactivate an active peer registry.
    
    Updates status to 'INACTIVE'.
    
    Requires: Admin Developer JWT authentication
    """
    db_peer = await crud_peer_registry.get_peer_registry_by_id(db, peer_id)
    
    if not db_peer:
        raise HTTPException(status_code=404, detail="Peer registry not found")
    
    if db_peer.status != "ACTIVE":
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot deactivate peer registry with status '{db_peer.status}'"
        )
    
    # Update status to INACTIVE — P2-004: include admin_id for audit trail
    updated_peer = await crud_peer_registry.update_peer_registry_status(
        db, db_peer, "INACTIVE", admin_id=current_admin.id, reason=reason
    )
    
    return schemas.PeerRegistryRead.model_validate(updated_peer)


@router.post("/{peer_id}/reactivate", response_model=schemas.PeerRegistryRead)
async def reactivate_peer_registry(
    peer_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation"))
) -> schemas.PeerRegistryRead:
    """Reactivate an inactive peer registry.
    
    Updates status back to 'ACTIVE'.
    
    Requires: Admin Developer JWT authentication
    """
    db_peer = await crud_peer_registry.get_peer_registry_by_id(db, peer_id)
    
    if not db_peer:
        raise HTTPException(status_code=404, detail="Peer registry not found")
    
    if db_peer.status != "INACTIVE":
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot reactivate peer registry with status '{db_peer.status}'"
        )
    
    # Update status to ACTIVE
    updated_peer = await crud_peer_registry.update_peer_registry_status(
        db, db_peer, "ACTIVE", admin_id=current_admin.id
    )
    # The TEG partner rule (ledgergate3): the PeerDeactivated reactor removed its TEG partner and no leg adds it back.
    try:
        from agentvault_registry.background_tasks.reactor_helpers import register_peer_partner_on_teg
        await register_peer_partner_on_teg(db, updated_peer.name, source_label="peer-reactivate")
    except Exception as exc:  # noqa: BLE001  non-fatal: this frame's next leg to the peer adds it too
        logger.warning(f"[admin_federation] TEG partner re-registration for peer {peer_id} failed: {exc}")
    
    return schemas.PeerRegistryRead.model_validate(updated_peer)


@router.get("/all", response_model=schemas.PeerRegistryListResponse)
async def list_all_peer_registries(
    status: Optional[str] = Query(None, description="Filter by status"),
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of items to return"),
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation"))
) -> schemas.PeerRegistryListResponse:
    """List all peer registries with optional status filter.
    
    Admin endpoint to view all peer registries regardless of status.
    
    Requires: Admin Developer JWT authentication
    """
    # Build the query
    stmt = select(models.PeerRegistry)
    
    if status:
        stmt = stmt.filter(models.PeerRegistry.status == status)
    
    # Get total count for pagination
    count_stmt = select(func.count()).select_from(models.PeerRegistry)
    if status:
        count_stmt = count_stmt.filter(models.PeerRegistry.status == status)
    count_result = await db.execute(count_stmt)
    total_count = count_result.scalar()
    
    # Get paginated results
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    peer_registries = result.scalars().all()
    
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
