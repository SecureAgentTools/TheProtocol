"""§pass47 C4 — Generic admin-action audit helper.

Thin wrapper around `security_oauth.audit_logger.SecurityAuditor.log_event`
for non-OAuth admin operations: key rotation, partner add/remove, manual
coordination aborts, force-recovery operations, etc.

Uses `SecurityEventType.SUSPICIOUS_ACTIVITY` as the catch-all event type
(since we don't want to migrate the enum for every new admin action). The
structured `action` + `details` fields carry the specifics — SIEM consumers
can filter by `action` prefix.

Pattern:
    from agentvault_registry.services.admin_audit import log_admin_action
    await log_admin_action(
        db,
        action="rotate_signing_key",
        actor_id=str(current_developer.id),
        target_type="agent",
        target_id=did,
        details={"new_rotation_seq": seq, "grace_days": 7},
    )

§auditfix (2026-07-19) — `log_ironkey_action` sibling for the IRONKEY
delegation/spawn surface (agent- and registry-actors, not just admins).
Same writer, distinct `ironkey.` action prefix so SIEM filters stay clean.
NOTE for callers: the underlying `log_event` COMMITS the passed session —
place the call where a commit is safe (immediately before the endpoint's
own commit → mutation + audit row land in ONE transaction; or on a deny
path before anything else is pending).

Best-effort: failures NEVER raise — admin operations succeed even if the
audit log write fails. The DB error is logged.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _log_action(
    db: AsyncSession,
    *,
    prefix: str,
    action: str,
    actor_type: str,
    actor_id: Optional[str] = None,
    actor_ip: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    outcome: str = "success",
    severity: str = "info",
    details: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> None:
    """Shared best-effort writer to security_audit_logs. Never raises."""
    try:
        from ..security_oauth.audit_logger import SecurityAuditor, SecurityEventType
        auditor = SecurityAuditor(service_name="registry-admin")
        await auditor.log_event(
            db,
            event_type=SecurityEventType.SUSPICIOUS_ACTIVITY,
            action=f"{prefix}.{action}",
            outcome=outcome,
            severity=severity,
            actor_type=actor_type,
            actor_id=actor_id,
            actor_ip=actor_ip,
            target_type=target_type,
            target_id=target_id,
            details=details,
            error_message=error_message,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"[AdminAudit] log {prefix}.{action} actor={actor_id} target={target_id} "
            f"failed: {e}"
        )


async def log_admin_action(
    db: AsyncSession,
    *,
    action: str,
    actor_id: Optional[str] = None,
    actor_ip: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    outcome: str = "success",
    severity: str = "info",
    details: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> None:
    """Best-effort write to security_audit_logs. Never raises."""
    await _log_action(
        db,
        prefix="admin",
        action=action,
        actor_type="admin",
        actor_id=actor_id,
        actor_ip=actor_ip,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        severity=severity,
        details=details,
        error_message=error_message,
    )


async def log_ironkey_action(
    db: AsyncSession,
    *,
    action: str,
    actor_type: str,
    actor_id: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    outcome: str = "success",
    severity: str = "info",
    details: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> None:
    """Best-effort security_audit_logs row for the IRONKEY delegation/spawn surface.

    `actor_type` is explicit ("agent" | "developer" | "registry" | "system") because
    most of this surface is agent-driven, not admin-driven. Recorded action is
    `ironkey.<action>` — SIEM consumers filter on the prefix. Never raises.
    """
    await _log_action(
        db,
        prefix="ironkey",
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        severity=severity,
        details=details,
        error_message=error_message,
    )


async def log_liability_action(
    db: AsyncSession,
    *,
    action: str,
    actor_type: str,
    actor_id: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    outcome: str = "success",
    severity: str = "info",
    details: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> None:
    """COCKPIT CARD (2026-07-25) security_audit_logs row — recorded as `liability.<action>`.

    Its own prefix, not a nested `ironkey.liability.*`: the liable-identity surface is a distinct
    SIEM filter (who underwrote what, which presence method, which denials) and auditors query it
    on its own. Same best-effort contract — never raises, commits with the caller. Never mixes
    with the agent-authority feed. Pairs with the per-mandate evidence hash chain.
    """
    await _log_action(
        db,
        prefix="liability",
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        severity=severity,
        details=details,
        error_message=error_message,
    )


async def log_session_action(
    db: AsyncSession,
    *,
    action: str,
    actor_id: Optional[str] = None,
    actor_ip: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    outcome: str = "success",
    severity: str = "info",
    details: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> None:
    """§FEFRAME W3 (V0504) security_audit_logs row for the session surface — recorded as `session.<action>` (the owner
    session token mints and their refusals). A developer acts here, so the actor type is `developer`. Same best-effort
    contract: never raises, commits with the caller."""
    await _log_action(
        db,
        prefix="session",
        action=action,
        actor_type="developer",
        actor_id=actor_id,
        actor_ip=actor_ip,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        severity=severity,
        details=details,
        error_message=error_message,
    )


async def log_chat_action(
    db: AsyncSession,
    *,
    action: str,
    actor_type: str,
    actor_id: Optional[str] = None,
    actor_ip: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    outcome: str = "success",
    severity: str = "info",
    details: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> None:
    """V0650 (l) security_audit_logs row for the chat approval rail — recorded as `chat.<action>` (an agent's
    approval request, a developer's decision, an owner naming an approver). Same best-effort contract: never raises,
    commits with the caller, so call it before the caller's own commit."""
    await _log_action(
        db,
        prefix="chat",
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_ip=actor_ip,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        severity=severity,
        details=details,
        error_message=error_message,
    )
