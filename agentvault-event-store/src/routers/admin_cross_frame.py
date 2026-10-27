"""SF-4 WS3.5: Admin CRUD for cross-frame peer registry.

Replaces the static CROSS_FRAME_PEERS env var with a DB-backed list so new
sovereign frames can be registered / suspended / removed at runtime. The
`CrossFrameReplicator` supervisor loop re-reads this table every cycle and
spawns / cancels per-peer polling tasks accordingly — no EventStore restart
needed.

Auth: §pass71.3 (2026-05-25) — uses `verify_event_auth` (mTLS / X-Internal-Key
/ X-Federation-License), mirroring the §pass71.2 widening on /api/v1/events/
and /api/v1/system/lockdown. The original strict `verify_internal_key` local
helper became unreachable through the canonical HTTPS path the moment the
nginx-event-store sidecar started stripping X-Internal-Key (§pass69 doctrine:
"mTLS is the authority"). Live probe pre-fix returned HTTP 422 `Field required`
on every endpoint here through the sidecar.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..models.db_models import CrossFramePeerModel
# §pass71.3 — single canonical auth helper; absorbs the three accepted modes
# (mTLS SVID forwarded by nginx-event-store as X-SSL-Client-S-DN / -Cert,
# X-Internal-Key for callers that bypass the sidecar, X-Federation-License
# for federated peers). The module-local _verify_internal_key helper that
# previously lived here was removed in §pass71.3 so the strict-header
# pattern can't be accidentally re-introduced.
from .events import require_origin_auth, verify_event_auth
# §SOVKIT T2 (2026-09-14): changes need this frame's own services (require_origin_auth); reads stay on
# verify_event_auth, so a peer frame's replicator and this frame's operators can still read.

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/cross-frame-peers", tags=["SF-4 Cross-Frame Peers"])

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


# ─── Schemas ───────────────────────────────────────────────────────

class CrossFramePeerRegister(BaseModel):
    frame_id: str = Field(..., min_length=3, max_length=255)
    url: str = Field(..., min_length=8, max_length=500)
    added_by: Optional[str] = Field(None, max_length=200)


class CrossFramePeerRead(BaseModel):
    frame_id: str
    url: str
    status: str
    last_timestamp: Optional[datetime] = None
    added_by: Optional[str] = None
    added_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ─── Endpoints ─────────────────────────────────────────────────────

@router.post("", response_model=CrossFramePeerRead, dependencies=[Depends(require_origin_auth)])
async def register_cross_frame_peer(
    payload: CrossFramePeerRegister,
    db: AsyncSession = Depends(get_db),
):
    """UPSERT a cross-frame peer. Idempotent on frame_id.

    If the peer was previously suspended/removed, re-registration flips
    status='active' and preserves last_timestamp watermark (so we don't
    re-fetch events we've already seen).
    """
    stmt = (
        pg_insert(CrossFramePeerModel)
        .values(
            frame_id=payload.frame_id,
            url=payload.url,
            status="active",
            added_by=payload.added_by or "admin-api",
            added_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_update(
            index_elements=["frame_id"],
            set_={
                "url": payload.url,
                "status": "active",
                "added_by": payload.added_by or "admin-api",
                "updated_at": datetime.now(timezone.utc),
            },
        )
        .returning(CrossFramePeerModel)
    )
    result = await db.execute(stmt)
    row = result.scalar_one()
    await db.commit()
    logger.info(f"[admin_cross_frame] UPSERT peer: {payload.frame_id} → {payload.url} (by={payload.added_by})")
    return row


@router.get("", dependencies=[Depends(verify_event_auth)])
async def list_cross_frame_peers(
    status: Optional[str] = Query(
        None, pattern=r"^(all|active|suspended|removed)$", description="Filter by status (default: all except 'removed')"
    ),
    db: AsyncSession = Depends(get_db),
):
    q = select(CrossFramePeerModel)
    if status is None:
        q = q.where(CrossFramePeerModel.status != "removed")
    elif status != "all":
        q = q.where(CrossFramePeerModel.status == status)
    q = q.order_by(CrossFramePeerModel.added_at.desc())
    rows = (await db.execute(q)).scalars().all()
    return {
        "peers": [CrossFramePeerRead.model_validate(r).model_dump(mode="json") for r in rows],
        "count": len(rows),
    }


@router.get("/{frame_id}", response_model=CrossFramePeerRead, dependencies=[Depends(verify_event_auth)])
async def get_cross_frame_peer(
    frame_id: str,
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(CrossFramePeerModel).where(CrossFramePeerModel.frame_id == frame_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Cross-frame peer '{frame_id}' not found")
    return row


@router.post("/{frame_id}/suspend", dependencies=[Depends(require_origin_auth)])
async def suspend_cross_frame_peer(
    frame_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Stop polling from this peer. Watermark is preserved — reactivating
    resumes polling from where we left off."""
    row = (await db.execute(
        select(CrossFramePeerModel).where(CrossFramePeerModel.frame_id == frame_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Cross-frame peer '{frame_id}' not found")
    if row.status == "active":
        row.status = "suspended"
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info(f"[admin_cross_frame] Suspended peer: {frame_id}")
    return {"status": "suspended", "frame_id": frame_id}


@router.delete("/{frame_id}", dependencies=[Depends(require_origin_auth)])
async def remove_cross_frame_peer(
    frame_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Mark peer as removed (soft delete — row kept for audit)."""
    row = (await db.execute(
        select(CrossFramePeerModel).where(CrossFramePeerModel.frame_id == frame_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Cross-frame peer '{frame_id}' not found")
    row.status = "removed"
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info(f"[admin_cross_frame] Removed peer: {frame_id}")
    return {"status": "removed", "frame_id": frame_id}
