"""§pass68 (2026-05-23) — Developer-scoped MCP audit log query surface.

Two endpoints:

  GET /api/v1/me/mcp-audit-log
    Returns ONLY rows where actor_id == current_developer.id (or matches a
    DID for an agent under the caller). Developer JWT or API key required.

  GET /api/v1/admin/mcp-audit-log?actor_id=...
    Admin variant gated on `admin_support` flag. When the requested actor_id
    does NOT match the calling admin's own id, an `admin_read_mcp_audit`
    event is written into the TARGET developer's own audit log (self-watching
    admin pattern). The target developer can then see that an admin viewed
    their MCP audit log by querying their own /me/mcp-audit-log.

Privacy model:
  - Default-private: no developer can see another developer's MCP audit rows
    via the /me endpoint.
  - Admin override is observable: every cross-developer admin read is itself
    a row in the target developer's log.
  - MCP_TOOL_INVOKED + MCP_TOOL_FAILED rows are the per-tool calls.
  - ADMIN_READ_MCP_AUDIT rows are the meta-events about cross-developer reads.

Response shape:
  {
    "rows": [
      {
        "id": "uuid",
        "timestamp": "2026-05-23T17:00:00Z",
        "event_type": "mcp_tool_invoked",
        "actor_type": "developer",
        "actor_id": "10",
        "actor_ip": "1.2.3.4",
        "target_id": "theprotocol_transferUnits",
        "outcome": "success",
        "severity": "info",
        "latency_ms": 42.5,
        "tier": "2",
        "is_admin_server": false,
        "request_id": "uuid",
        "details": { ... }
      },
      ...
    ],
    "next_cursor": "<id-of-last-row-or-null>"
  }
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models, security
from agentvault_registry.database import get_db
from agentvault_registry.mcp.audit_sanitizer import sanitize_stored_details
from agentvault_registry.security import (
    get_current_developer,
    require_admin_flag,
)
from agentvault_registry.security_oauth.audit_logger import (
    SecurityAuditLog,
    SecurityEventType,
    security_auditor,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["MCP Audit Log"])

# Hard cap to prevent runaway queries
_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50

# Rows we consider "MCP audit" — both the call rows and the admin-read meta-rows
_MCP_AUDIT_EVENT_TYPES = (
    SecurityEventType.MCP_TOOL_INVOKED,
    SecurityEventType.MCP_TOOL_FAILED,
    SecurityEventType.ADMIN_READ_MCP_AUDIT,
)


def _serialize_row(row: SecurityAuditLog) -> Dict[str, Any]:
    """Convert a SecurityAuditLog row to the API response shape."""
    details_parsed: Any = None
    if row.details:
        try:
            details_parsed = json.loads(row.details)
        except Exception:  # noqa: BLE001
            details_parsed = {"raw": row.details[:500]}
        # §MCPSWEEP 2026-09-27: rows written before the result sanitizer parsed tool text hold the credentials a
        # tool returned (client_secret, API keys, JWTs); served as stored, a developer's JWT read them back
        details_parsed = sanitize_stored_details(details_parsed)

    latency_ms: Optional[float] = None
    tier: Optional[str] = None
    is_admin_server: Optional[bool] = None
    if isinstance(details_parsed, dict):
        latency_ms = details_parsed.get("latency_ms")
        tier = details_parsed.get("tier")
        is_admin_server = details_parsed.get("is_admin_server")

    return {
        "id": row.id,
        "timestamp": row.timestamp.isoformat() + "Z" if row.timestamp else None,
        "event_type": row.event_type.value if hasattr(row.event_type, "value") else str(row.event_type),
        "actor_type": row.actor_type,
        "actor_id": row.actor_id,
        "actor_ip": row.actor_ip,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "outcome": row.outcome,
        "severity": row.severity,
        "latency_ms": latency_ms,
        "tier": tier,
        "is_admin_server": is_admin_server,
        "request_id": row.request_id,
        "user_agent": row.user_agent,
        "details": details_parsed,
        "error_message": row.error_message,
    }


def _visible_to(me: str):
    """What a developer may read at /me: the MCP calls they made, and every admin read of
    their log. An `admin_read_mcp_audit` row names the ADMIN as actor and the developer as
    target, so filtering on the actor alone hid every read from the person it was about
    (2026-09-25: the promise "admin reads are visible to the developer being read" was
    written, stored and never returned)."""
    return or_(
        and_(SecurityAuditLog.actor_id == me, SecurityAuditLog.event_type.in_(_MCP_AUDIT_EVENT_TYPES)),
        and_(SecurityAuditLog.event_type == SecurityEventType.ADMIN_READ_MCP_AUDIT,
             SecurityAuditLog.target_type == "developer_audit_log",
             SecurityAuditLog.target_id == me),
    )


def my_mcp_audit_stmt(me: str, limit: int, before=None):
    """The /me query, as a pure builder (tests compile it)."""
    stmt = select(SecurityAuditLog).where(_visible_to(me))
    if before is not None:
        stmt = stmt.where(SecurityAuditLog.timestamp < before)
    return stmt.order_by(SecurityAuditLog.timestamp.desc()).limit(limit)


def _serialize_for_subject(row: SecurityAuditLog, me: str) -> Dict[str, Any]:
    """A row as the developer sees it. An admin read keeps who and when; the admin's email
    stays with the admins."""
    out = _serialize_row(row)
    if out.get("actor_id") != me and isinstance(out.get("details"), dict):
        out["details"] = {k: v for k, v in out["details"].items() if k != "admin_email"}
    return out


@router.get(
    "/me/mcp-audit-log",
    summary="Get my MCP tool call audit log",
    description=(
        "Returns rows from `security_audit_logs` for MCP tool calls performed "
        "under the calling developer's identity, plus every admin read of this "
        "log (an `admin_read_mcp_audit` row naming the admin). Cursor-paginated. "
        "Other developers' rows are invisible at this endpoint by construction."
    ),
)
async def get_my_mcp_audit_log(
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: Optional[str] = Query(None, description="Pagination cursor (id of last row from previous page)"),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(get_current_developer),
) -> Dict[str, Any]:
    """Developer-scoped MCP audit log query."""
    me = str(current_developer.id)
    before = None
    if cursor:
        # Cursor is the id of the last row from the previous page; fetch rows
        # with timestamp < that row's timestamp. Resolve via lookup.
        cursor_row = await db.get(SecurityAuditLog, cursor)
        if cursor_row is not None:
            before = cursor_row.timestamp

    result = await db.execute(my_mcp_audit_stmt(me, limit, before))
    rows: List[SecurityAuditLog] = list(result.scalars().all())

    next_cursor = rows[-1].id if len(rows) == limit else None
    return {
        "rows": [_serialize_for_subject(r, me) for r in rows],
        "next_cursor": next_cursor,
        "limit": limit,
    }


@router.get(
    "/admin/mcp-audit-log",
    summary="Admin: read MCP audit log for any developer (self-watched)",
    description=(
        "Admin variant of the developer-scoped MCP audit log query. Gated on "
        "`admin_support`. When the requested `actor_id` does NOT match the "
        "calling admin's own id, an `admin_read_mcp_audit` row is inserted "
        "into the target developer's log so they can see that an admin "
        "viewed their MCP audit. Use sparingly."
    ),
)
async def admin_get_mcp_audit_log(
    request: Request,
    actor_id: str = Query(..., description="Developer id (numeric string) or agent DID to query"),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Depends(require_admin_flag("admin_support")),
) -> Dict[str, Any]:
    """Admin MCP audit log query with self-watching meta-event."""
    self_id = str(current_developer.id)

    # If reading someone else's log, emit a meta-event into the TARGET's log
    if actor_id != self_id:
        actor_ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent")
        req_id = request.headers.get("x-request-id")
        try:
            await security_auditor.log_event(
                db=db,
                event_type=SecurityEventType.ADMIN_READ_MCP_AUDIT,
                action="read_audit_log",
                outcome="success",
                severity="info",
                actor_type="admin",
                actor_id=self_id,  # the admin reading
                actor_ip=actor_ip,
                target_type="developer_audit_log",
                target_id=actor_id,  # the developer being read
                details={
                    "admin_email": current_developer.email,
                    "requested_limit": limit,
                    "cursor": cursor,
                },
                request_id=req_id,
                user_agent=ua,
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            # Self-watch is best-effort; log + continue
            logger.warning("Failed to write admin_read_mcp_audit row: %s", exc)
            await db.rollback()

    stmt = (
        select(SecurityAuditLog)
        .where(SecurityAuditLog.actor_id == actor_id)
        .where(SecurityAuditLog.event_type.in_(_MCP_AUDIT_EVENT_TYPES))
        .order_by(SecurityAuditLog.timestamp.desc())
        .limit(limit)
    )
    if cursor:
        cursor_row = await db.get(SecurityAuditLog, cursor)
        if cursor_row is not None:
            stmt = (
                select(SecurityAuditLog)
                .where(SecurityAuditLog.actor_id == actor_id)
                .where(SecurityAuditLog.event_type.in_(_MCP_AUDIT_EVENT_TYPES))
                .where(SecurityAuditLog.timestamp < cursor_row.timestamp)
                .order_by(SecurityAuditLog.timestamp.desc())
                .limit(limit)
            )

    result = await db.execute(stmt)
    rows: List[SecurityAuditLog] = list(result.scalars().all())

    next_cursor = rows[-1].id if len(rows) == limit else None
    return {
        "rows": [_serialize_row(r) for r in rows],
        "next_cursor": next_cursor,
        "limit": limit,
        "queried_actor_id": actor_id,
        "self_watched": actor_id != self_id,
    }
