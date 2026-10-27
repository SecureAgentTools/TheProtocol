"""Operator Lifecycle Read Endpoints (Option D-light Phase D5 — 2026-04-21)

Two read-only endpoints that assemble the full 4-layer operator state stack
(application + license + peer_registry + cloud) into a single response so
callers don't need to execute multi-table joins.

  GET /api/v1/operators/me/lifecycle
      — developer JWT; returns the caller's own operator state (404 if not an operator)

  GET /api/v1/admin/operators/lifecycle-overview
      — admin_federation flag; returns every operator with per-row drift flags.
        Supports ?status=X, ?drift_only=true, ?limit=N&offset=M.

Drift detection calls into background_tasks.license_drift_monitor.detect_drift_for_operator
to keep the rules in one place.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status, Security
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.background_tasks.license_drift_monitor import (
    detect_drift_for_operator,
    _derive_operator_did_from_app,
    TOPOLOGY_STALENESS_SECONDS,
)

router = APIRouter(tags=["Operator Lifecycle"])


# ---------------------------------------------------------------------------
# Assemblers
# ---------------------------------------------------------------------------

def _application_block(app: models.OperatorApplication) -> Dict[str, Any]:
    return {
        "id": app.id,
        "name": app.name,
        "status": app.status,
        "cloud_hosted": bool(getattr(app, "cloud_hosted", False)),
        "organization": app.organization,
        "email": app.email,
        "activated_at": app.activated_at.isoformat() if app.activated_at else None,
        "revoked_at": app.revoked_at.isoformat() if app.revoked_at else None,
        "revoked_reason": app.revoked_reason,
        "reviewed_at": app.reviewed_at.isoformat() if app.reviewed_at else None,
        "created_at": app.created_at.isoformat() if app.created_at else None,
    }


def _license_block(lic: Optional[models.FederationLicense]) -> Optional[Dict[str, Any]]:
    if lic is None:
        return None
    return {
        "id": lic.id,
        "operator_did": lic.operator_did,
        "status": lic.status,
        "license_key_prefix": lic.license_key_prefix,
        "issued_at": lic.issued_at.isoformat() if lic.issued_at else None,
        "last_seen_at": lic.last_seen_at.isoformat() if lic.last_seen_at else None,
        "event_count": lic.event_count,
        "suspended_at": lic.suspended_at.isoformat() if getattr(lic, "suspended_at", None) else None,
        "suspended_reason": getattr(lic, "suspended_reason", None),
        "revoked_at": lic.revoked_at.isoformat() if lic.revoked_at else None,
        "revoked_reason": lic.revoked_reason,
        "federation_tier": lic.federation_tier,
    }


def _peer_block(peer: Optional[models.PeerRegistry]) -> Optional[Dict[str, Any]]:
    if peer is None:
        return None
    last_seen = getattr(peer, "last_seen_in_topology_at", None)
    return {
        "id": peer.id,
        "name": peer.name,
        "status": peer.status,
        "base_url": peer.base_url,
        "peer_type": peer.peer_type,
        "hop_distance": peer.hop_distance,
        "parent_registry_id": peer.parent_registry_id,
        "registered_at": peer.registered_at.isoformat() if peer.registered_at else None,
        "approved_at": peer.approved_at.isoformat() if peer.approved_at else None,
        "last_synced_at": peer.last_synced_at.isoformat() if peer.last_synced_at else None,
        "last_seen_in_topology_at": last_seen.isoformat() if last_seen else None,
        "bfs_reachable": bool(
            last_seen
            and (datetime.now(timezone.utc) - last_seen).total_seconds()
            <= TOPOLOGY_STALENESS_SECONDS
        ),
    }


def _cloud_block(app: models.OperatorApplication) -> Optional[Dict[str, Any]]:
    if not getattr(app, "cloud_hosted", False):
        return None
    return {
        "cloud_hosted": True,
        "cloud_url": app.cloud_url,
        "cloud_port_base": app.cloud_port_base,
        "cloud_provisioned_at": (
            app.cloud_provisioned_at.isoformat() if app.cloud_provisioned_at else None
        ),
        "cloud_torn_down_at": (
            app.cloud_torn_down_at.isoformat() if app.cloud_torn_down_at else None
        ),
        "cloud_stack_dir": app.cloud_stack_dir,
    }


async def _lookup_license(db: AsyncSession, app: models.OperatorApplication) -> Optional[models.FederationLicense]:
    did = _derive_operator_did_from_app(app)
    result = await db.execute(
        select(models.FederationLicense).where(
            models.FederationLicense.operator_did == did
        )
    )
    return result.scalar_one_or_none()


async def _lookup_peer(db: AsyncSession, app: models.OperatorApplication) -> Optional[models.PeerRegistry]:
    # cloud_provisioner + operator_provisioner both insert peer rows with name == application.name
    result = await db.execute(
        select(models.PeerRegistry).where(models.PeerRegistry.name == app.name)
    )
    return result.scalar_one_or_none()


async def _assemble_lifecycle(db: AsyncSession, app: models.OperatorApplication) -> Dict[str, Any]:
    lic = await _lookup_license(db, app)
    peer = await _lookup_peer(db, app)
    drift_flags = detect_drift_for_operator(app, lic, peer)
    return {
        "application": _application_block(app),
        "federation_license": _license_block(lic),
        "peer_registry": _peer_block(peer),
        "cloud": _cloud_block(app),
        "drift_flags": drift_flags,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/operators/me/lifecycle",
    summary="Operator self-view: full lifecycle state stack",
)
async def get_my_lifecycle(
    current_developer: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Returns the caller's own 4-layer operator state (application, license,
    peer registry, cloud) with drift flags.

    404 if the developer has no OperatorApplication. Finds the application
    via developer_id OR activated_developer_id (covers both the applicant
    account and the operator-bootstrap account if they differ).
    """
    result = await db.execute(
        select(models.OperatorApplication).where(
            or_(
                models.OperatorApplication.developer_id == current_developer.id,
                models.OperatorApplication.activated_developer_id == current_developer.id,
            )
        ).order_by(models.OperatorApplication.created_at.desc())
    )
    app = result.scalars().first()
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No operator application found for this developer account.",
        )
    return await _assemble_lifecycle(db, app)


@router.get(
    "/admin/operators/lifecycle-overview",
    summary="Admin view: lifecycle state + drift flags for every operator",
)
async def get_lifecycle_overview(
    status_filter: Optional[str] = Query(
        None, alias="status",
        pattern=r"^(all|approved|suspended|revoked|pending|rejected)$",
        description="Filter by application status",
    ),
    drift_only: bool = Query(False, description="Return only operators with at least one drift flag"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Per-operator lifecycle state + drift flags, across every OperatorApplication.

    Intended as the data source for the Lifecycle tab in the admin OperatorManagement
    drawer and for the at-a-glance drift indicator column on the main table.
    """
    query = select(models.OperatorApplication)
    if status_filter and status_filter != "all":
        query = query.where(models.OperatorApplication.status == status_filter)
    query = query.order_by(models.OperatorApplication.created_at.desc())
    # Over-fetch if drift_only because filtering happens after drift detection
    fetch_limit = limit * 4 if drift_only else limit
    query = query.limit(fetch_limit).offset(offset)

    apps = (await db.execute(query)).scalars().all()

    rows: List[Dict[str, Any]] = []
    for app in apps:
        row = await _assemble_lifecycle(db, app)
        if drift_only and not row["drift_flags"]:
            continue
        rows.append(row)
        if len(rows) >= limit:
            break

    drift_count = sum(1 for r in rows if r["drift_flags"])
    return {
        "operators": rows,
        "total_returned": len(rows),
        "drift_count": drift_count,
        "limit": limit,
        "offset": offset,
        "filters": {"status": status_filter, "drift_only": drift_only},
    }
