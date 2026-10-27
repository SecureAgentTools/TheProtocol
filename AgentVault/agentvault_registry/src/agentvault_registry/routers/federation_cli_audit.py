"""CLI Audit Event Receiver (BL-1, Q7 approved 2026-05-11).

Accepts audit events from operator-side tp-operator CLI invocations and emits
them to EventStore as `OperatorCliAction` events. Provides cross-operator
visibility into CLI activity (per Operator_CLI_Strategy.md §6.4).

Auth: X-Federation-License (Mode 3 in core/federation_auth.py).

Event type: `OperatorCliAction`
  - skip_in_projection=true (audit-only; never balance-affecting)
  - aggregate_id = operator_did (groups by operator)
  - Default emission policy is permissive (no DB row required); we add one
    explicitly via migration 0049 for clarity + explicit skip_in_projection.

Kill switch: OPERATOR_CLI_AUDIT_EMIT_ENABLED (default false on production;
sandbox-A flips true). Hard 503 when disabled.

Strategy: PRODUCTION_DOCS/ROADMAP/Operator_CLI_Strategy.md §6.4 + §14.Q7.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry.event_emitter import get_event_emitter
from agentvault_registry.routers.federation_license_self import _resolve_caller_license

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return os.getenv("OPERATOR_CLI_AUDIT_EMIT_ENABLED", "false").lower() in ("true", "1", "yes")


class CliAuditRequest(BaseModel):
    """Payload sent by tp-operator after each state-mutating command.

    No secrets ever land here. CLI strips license keys to prefix only.
    """
    action: str = Field(..., description="Command name, e.g. 'license rotate', 'restart registry'", max_length=64)
    cli_version: str = Field(..., max_length=20)
    actor_host: str = Field(..., max_length=120, description="hostname where CLI ran")
    actor_user: str = Field(..., max_length=64, description="local user who invoked the CLI")
    dry_run: bool = False
    exit_code: int = 0
    duration_ms: float = 0.0
    extra: Optional[Dict[str, Any]] = None


class CliAuditResponse(BaseModel):
    emitted: bool
    event_type: str = "OperatorCliAction"
    aggregate_id: str
    operator_did: str


router = APIRouter(
    prefix="/api/v1/federation/cli-audit",
    tags=["Federation CLI Audit"],
)


@router.post(
    "",
    response_model=CliAuditResponse,
    status_code=status.HTTP_200_OK,
    summary="Emit a CLI audit event to EventStore (operator-callable)",
)
async def receive_cli_audit(
    body: CliAuditRequest,
    x_federation_license: Optional[str] = Header(None, alias="X-Federation-License"),
    db: AsyncSession = Depends(get_db),
) -> CliAuditResponse:
    """Accept an audit event from a federation-license-authenticated operator CLI.

    Authentication: the caller must present a valid X-Federation-License header.
    The operator_did is derived from the license row (never trusted from the
    request body: operators cannot impersonate each other).
    """
    if not _enabled():
        raise HTTPException(
            status_code=503,
            detail=(
                "Remote CLI audit-event emission is disabled on this registry. "
                "Set OPERATOR_CLI_AUDIT_EMIT_ENABLED=true to enable."
            ),
        )

    if not x_federation_license:
        raise HTTPException(
            status_code=400,
            detail="X-Federation-License header required",
        )

    caller_lic = await _resolve_caller_license(db, x_federation_license)
    operator_did = caller_lic.operator_did
    operator_name = caller_lic.operator_name

    # Defensive: scrub any secret-looking keys from extra
    safe_extra: Dict[str, Any] = {}
    if body.extra:
        for k, v in body.extra.items():
            if any(s in k.lower() for s in ("secret", "password", "private", "key")):
                if isinstance(v, str) and len(v) > 12:
                    safe_extra[k] = v[:12] + "..."
                else:
                    safe_extra[k] = "[redacted]"
            else:
                safe_extra[k] = v

    event_data = {
        "operator_did": operator_did,
        "operator_name": operator_name,
        "license_key_prefix": caller_lic.license_key_prefix,
        "action": body.action,
        "cli_version": body.cli_version,
        "actor_host": body.actor_host,
        "actor_user": body.actor_user,
        "dry_run": body.dry_run,
        "exit_code": body.exit_code,
        "duration_ms": body.duration_ms,
        "extra": safe_extra,
    }

    emitter = get_event_emitter()
    try:
        await emitter.emit_event(
            aggregate_id=operator_did,
            event_type="OperatorCliAction",
            event_data=event_data,
        )
        emitted = True
    except Exception as exc:
        logger.warning(f"[CLI-Audit] Emit failed for op={operator_name}: {exc}")
        emitted = False

    return CliAuditResponse(
        emitted=emitted,
        event_type="OperatorCliAction",
        aggregate_id=operator_did,
        operator_did=operator_did,
    )
