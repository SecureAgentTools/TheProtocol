"""§pass49 B1 — Admin endpoints for agent_flags table.

  GET  /api/v1/admin/agents/{did}/flags          — list flags for one agent
  GET  /api/v1/admin/flags                        — global feed across all agents
  POST /api/v1/admin/agents/{did}/flags/{id}/acknowledge — mark a flag acknowledged

Companion to `reactor_jws_verify_failed_throttle` + `reactor_agent_card_drift`
which now also persist a row into agent_flags alongside the EventStore emit.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Security
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, security
from ..database import get_db
from ..event_emitter import get_event_emitter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin — Agent Flags"])


@router.get("/agents/{did:path}/flags")
async def list_flags_for_agent(
    did: str = Path(...),
    only_unacknowledged: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """List flags for one agent. Pass only_unacknowledged=true to filter."""
    stmt = (
        select(models.AgentFlag)
        .where(models.AgentFlag.agent_did == did)
        .order_by(desc(models.AgentFlag.raised_at))
        .limit(limit)
    )
    if only_unacknowledged:
        stmt = stmt.where(models.AgentFlag.acknowledged_at.is_(None))
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "agent_did": did,
        "count": len(rows),
        "flags": [_serialize(r) for r in rows],
    }


@router.get("/flags")
async def list_flags_global(
    flag_type: Optional[str] = Query(None),
    only_unacknowledged: bool = Query(True),
    since_hours: int = Query(24, ge=1, le=168),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Global flag feed across all agents (recent + filterable)."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    stmt = (
        select(models.AgentFlag)
        .where(models.AgentFlag.raised_at > cutoff)
        .order_by(desc(models.AgentFlag.raised_at))
        .limit(limit)
    )
    if flag_type:
        stmt = stmt.where(models.AgentFlag.flag_type == flag_type)
    if only_unacknowledged:
        stmt = stmt.where(models.AgentFlag.acknowledged_at.is_(None))
    rows = (await db.execute(stmt)).scalars().all()

    # Counts by type (within window) for header tiles.
    counts_stmt = (
        select(models.AgentFlag.flag_type, func.count(models.AgentFlag.id))
        .where(models.AgentFlag.raised_at > cutoff)
        .group_by(models.AgentFlag.flag_type)
    )
    by_type = {t: c for t, c in (await db.execute(counts_stmt)).all()}

    return {
        "window_hours": since_hours,
        "count": len(rows),
        "by_type": by_type,
        "flags": [_serialize(r) for r in rows],
    }


@router.post("/agents/{did:path}/flags/{flag_id}/acknowledge")
async def acknowledge_flag(
    did: str = Path(...),
    flag_id: str = Path(...),
    notes: Optional[str] = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Mark a flag as acknowledged. Idempotent — if already acked, returns the row."""
    # A flag id is a UUID; anything else names no flag, and binding it against the uuid column is a database error.
    try:
        flag_id = str(uuid.UUID(flag_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Flag not found for this agent")
    row = (await db.execute(_flag_lookup_stmt(did, flag_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Flag not found for this agent")

    if row.acknowledged_at is not None:
        return {"status": "already_acknowledged", "flag": _serialize(row)}

    row.acknowledged_at = datetime.now(timezone.utc)
    row.acknowledged_by_dev_id = current_admin.id
    row.ack_notes = (notes or "")[:500]
    db.add(row)
    await db.commit()
    await db.refresh(row)

    # Audit emit (best-effort).
    try:
        emitter = get_event_emitter()
        if emitter is not None:
            await emitter.emit(
                event_type="AgentFlagAcknowledged",
                aggregate_id=did,
                aggregate_type="AgentCard",
                data={
                    "agent_did": did,
                    "flag_id": flag_id,
                    "flag_type": row.flag_type,
                    "acknowledged_by_dev_id": current_admin.id,
                    "acknowledged_by_email": current_admin.email,
                    "ack_notes": row.ack_notes,
                    "raised_at": row.raised_at.isoformat() if row.raised_at else None,
                },
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[AgentFlagAck] emit failed (non-fatal): {e}")

    # Generic admin audit log (security_audit_logs).
    try:
        from ..services.admin_audit import log_admin_action
        await log_admin_action(
            db,
            action="acknowledge_agent_flag",
            actor_id=str(current_admin.id),
            target_type="agent",
            target_id=did,
            details={"flag_id": flag_id, "flag_type": row.flag_type, "notes": row.ack_notes},
            severity="info",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[AgentFlagAck] audit log failed: {e}")

    return {"status": "acknowledged", "flag": _serialize(row)}


def _flag_lookup_stmt(did: str, flag_id: str):
    """The acknowledge route's lookup, one flag of one agent. Kept apart so a test can compile the exact statement."""
    return select(models.AgentFlag).where(
        models.AgentFlag.id == flag_id,
        models.AgentFlag.agent_did == did,
    )


def _serialize(r: models.AgentFlag) -> dict:
    return {
        "id": str(r.id),
        "agent_did": r.agent_did,
        "flag_type": r.flag_type,
        "raised_at": r.raised_at.isoformat() if r.raised_at else None,
        "raised_by_event_id": r.raised_by_event_id,
        "reason": r.reason,
        "source": r.source,
        "details": r.details,
        "acknowledged_at": r.acknowledged_at.isoformat() if r.acknowledged_at else None,
        "acknowledged_by_dev_id": r.acknowledged_by_dev_id,
        "ack_notes": r.ack_notes,
    }
