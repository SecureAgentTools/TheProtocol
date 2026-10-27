"""§pass49 — Admin fleet CI/CD + audit-log endpoints.

  GET /api/v1/admin/cicd/summary           — fleet rollup for AdminCICD.vue
  GET /api/v1/admin/cicd/deployments       — paginated recent deployments
  GET /api/v1/admin/audit-logs             — query security_audit_logs

Designed as read-only observability over data that the rest of §pass47/48
already produces (CI/CD events, audit log rows). No mutations.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, security
from ..database import get_db
from ..mcp.audit_sanitizer import redact_text_shapes, sanitize_stored_details

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin — CI/CD Fleet"])


@router.get("/cicd/summary")
async def cicd_fleet_summary(
    window_hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Fleet-wide CI/CD rollup over `window_hours`.

    Returns:
      pipelines: total count + last_created_at
      versions: total, current count
      deployments: total/success/failed/pending + top-5 failing agents
      drift: events 24h, top drifted field
      flags: unacknowledged count by type
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    pipe_row = (await db.execute(text("""
        SELECT COUNT(*)::int AS total, MAX(created_at) AS last_created
        FROM agent_pipelines
    """))).first()

    ver_row = (await db.execute(text("""
        SELECT COUNT(*)::int AS total,
               SUM(CASE WHEN is_current THEN 1 ELSE 0 END)::int AS active
        FROM agent_versions
    """))).first()

    dep_row = (await db.execute(text("""
        SELECT
          COUNT(*)::int AS total,
          SUM(CASE WHEN status='success' THEN 1 ELSE 0 END)::int AS success,
          SUM(CASE WHEN status='failed'  THEN 1 ELSE 0 END)::int AS failed,
          SUM(CASE WHEN status IN ('pending','running') THEN 1 ELSE 0 END)::int AS pending
        FROM agent_deployments
        WHERE started_at > :cutoff
    """), {"cutoff": cutoff})).first()

    top_fail_rows = await db.execute(text("""
        SELECT agent_did, COUNT(*)::int AS fail_count
        FROM agent_deployments
        WHERE status='failed' AND started_at > :cutoff
        GROUP BY agent_did
        ORDER BY fail_count DESC
        LIMIT 5
    """), {"cutoff": cutoff})
    top_failing = [{"did": r.agent_did, "fail_count": r.fail_count} for r in top_fail_rows]

    # Flag counts by type (window).
    flag_rows = await db.execute(text("""
        SELECT flag_type,
               COUNT(*) FILTER (WHERE acknowledged_at IS NULL)::int AS unacked,
               COUNT(*)::int AS total_in_window
        FROM agent_flags
        WHERE raised_at > :cutoff
        GROUP BY flag_type
    """), {"cutoff": cutoff})
    flags_by_type = [
        {"flag_type": r.flag_type, "unacked": r.unacked, "total": r.total_in_window}
        for r in flag_rows
    ]

    return {
        "window_hours": window_hours,
        "pipelines": {
            "total": pipe_row.total if pipe_row else 0,
            "last_created_at": (pipe_row.last_created.isoformat() if (pipe_row and pipe_row.last_created) else None),
        },
        "versions": {
            "total":  (ver_row.total  or 0) if ver_row else 0,
            "active": (ver_row.active or 0) if ver_row else 0,
        },
        "deployments": {
            "total":   (dep_row.total   or 0) if dep_row else 0,
            "success": (dep_row.success or 0) if dep_row else 0,
            "failed":  (dep_row.failed  or 0) if dep_row else 0,
            "pending": (dep_row.pending or 0) if dep_row else 0,
            "top_failing_agents": top_failing,
        },
        "flags": flags_by_type,
    }


@router.get("/cicd/deployments")
async def cicd_recent_deployments(
    status_filter: Optional[str] = Query(None, alias="status"),
    agent_did: Optional[str] = Query(None),
    organization_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Recent deployments across the fleet with filters."""
    where = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}
    if status_filter:
        where.append("d.status = :status")
        params["status"] = status_filter
    if agent_did:
        where.append("d.agent_did = :did")
        params["did"] = agent_did
    if organization_id:
        where.append("a.organization_id = :org_id")
        params["org_id"] = organization_id

    sql = f"""
        SELECT d.id, d.agent_did, d.deployment_type, d.environment, d.status,
               d.started_at, d.completed_at, d.duration_seconds,
               d.error_message, v.version, p.pipeline_name,
               a.organization_id
        FROM agent_deployments d
        LEFT JOIN agent_versions v ON d.version_id = v.id
        LEFT JOIN agent_pipelines p ON d.pipeline_id = p.id
        LEFT JOIN agents a          ON a.did       = d.agent_did
        WHERE {' AND '.join(where)}
        ORDER BY d.started_at DESC
        LIMIT :limit OFFSET :offset
    """
    rows = await db.execute(text(sql), params)
    items = [{
        "id": str(r.id),
        "agent_did": r.agent_did,
        "deployment_type": r.deployment_type,
        "environment": r.environment,
        "status": r.status,
        "version": r.version,
        "pipeline_name": r.pipeline_name,
        "organization_id": r.organization_id,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "duration_seconds": r.duration_seconds,
        "error_message": r.error_message,
    } for r in rows]
    return {"count": len(items), "items": items}


@router.get("/audit-logs")
async def list_audit_logs(
    action: Optional[str] = Query(None, description="Prefix-match on action (LIKE 'X%')"),
    event_type: Optional[str] = Query(None, description="Exact event type (security_audit_logs.event_type)"),
    actor_type: Optional[str] = Query(None, description="developer | agent | admin | anonymous | system"),
    actor_id: Optional[str] = Query(None),
    target_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    since_hours: int = Query(24, ge=1, le=720),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """List rows from `security_audit_logs`.

    §pass48 unblocked the audit_logger silent failure; now this endpoint
    exposes the data for AdminAuditLogs.vue. Read-only.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    # security_audit_logs.timestamp is TIMESTAMP WITHOUT TIME ZONE in this DB.
    cutoff_naive = cutoff.replace(tzinfo=None)
    where = ["timestamp > :cutoff"]
    params: dict = {"cutoff": cutoff_naive, "limit": limit, "offset": offset}
    if action:
        where.append("action LIKE :action_like")
        params["action_like"] = f"{action}%"
    if actor_id:
        where.append("actor_id = :actor_id")
        params["actor_id"] = actor_id
    if target_id:
        where.append("target_id = :target_id")
        params["target_id"] = target_id
    if severity:
        where.append("severity = :severity")
        params["severity"] = severity
    # §MCPTEST30 (2026-10-01): getAdminAuditLogs sent event_type and actor_type and this route read neither, so the
    # filtered list a caller asked for came back unfiltered with a 200 (the request survey's UNDECLARED class)
    if event_type:
        where.append("event_type::text = :event_type")
        params["event_type"] = event_type
    if actor_type:
        where.append("actor_type = :actor_type")
        params["actor_type"] = actor_type

    sql = f"""
        SELECT id, timestamp, event_type::text AS event_type, correlation_id,
               actor_type, actor_id, actor_ip, target_type, target_id,
               action, outcome, severity, details, error_message,
               request_id, user_agent
        FROM security_audit_logs
        WHERE {' AND '.join(where)}
        ORDER BY timestamp DESC, id DESC
        LIMIT :limit OFFSET :offset
    """
    rows = await db.execute(text(sql), params)
    items = [{
        "id": r.id, "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        "event_type": r.event_type, "correlation_id": r.correlation_id,
        "actor_type": r.actor_type, "actor_id": r.actor_id, "actor_ip": r.actor_ip,
        "target_type": r.target_type, "target_id": r.target_id,
        "action": r.action, "outcome": r.outcome, "severity": r.severity,
        # §MCPSWEEP 2026-09-27: an MCP tool row can hold the credentials its tool returned; masked on the way out
        "details": (sanitize_stored_details(r.details) if r.target_type == "mcp_tool"
                    else redact_text_shapes(r.details)),
        "error_message": r.error_message,
        "request_id": r.request_id, "user_agent": r.user_agent,
    } for r in rows]
    return {"count": len(items), "items": items, "window_hours": since_hours}
