"""
EventStore System Router — Lockdown Circuit Breaker (Phase 2b)

Provides emergency lockdown for supply invariant breaches and
cryptographic mint violations.  Once locked, all event appends
return HTTP 503 until an admin explicitly clears the lockdown.
The lockdown is kept in the store's database, so it holds on every
worker and across a restart (services/lockdown_state.py, D6-298).

Routes:
  POST /api/v1/system/lockdown        — Activate lockdown (X-Internal-Key)
  POST /api/v1/system/lockdown/clear  — Clear lockdown (X-Internal-Key)
  GET  /api/v1/system/lockdown/status — Check state (public — used by supply auditor)

Auth: X-Internal-Key header required for activation/clear.
      Status endpoint is public (supply_auditor polls it).
"""
import os
import logging
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Header, Depends, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from ..services.lockdown_state import GLOBAL_LOCKDOWN
# §pass71.2 (2026-05-25) — widen lockdown endpoints to accept mTLS SVID, not
# just X-Internal-Key. The nginx-event-store sidecar strips X-Internal-Key per
# §pass69 doctrine ("mTLS is the authority"), so the pre-§pass71.2 strict
# verify_internal_key dependency made these endpoints unreachable through
# the canonical HTTP path — silently disarming the emergency lockdown control.
# Mirrors the same widening applied to /api/v1/events/ and /events/aggregate/.
from .events import verify_event_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/system", tags=["system"])

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

# §pass54 PR-3-expansion: APIKeyHeader spec marker for X-Internal-Key. Runtime
# unchanged — we still validate against INTERNAL_API_KEY in verify_internal_key.
# This only annotates the OpenAPI surface so SDK generators + Swagger UI see
# `security: [{InternalAPIKey: []}]` instead of `security: null` on the two
# lockdown mutators.
_internal_key_header = APIKeyHeader(
    name="X-Internal-Key",
    scheme_name="InternalAPIKey",
    description="EventStore internal API key — required to activate or clear lockdown",
    auto_error=False,
)


# ── Auth dependency ────────────────────────────────────────────────────────────

async def verify_internal_key(x_internal_key: Optional[str] = Security(_internal_key_header)):
    if not INTERNAL_API_KEY:
        logger.error("[SystemRouter] INTERNAL_API_KEY is not set — rejecting all requests")
        raise HTTPException(status_code=500, detail="Server configuration error")
    from ..internal_key import internal_key_ok  # §KEYROT: current OR previous during a rotation window
    if not x_internal_key or not internal_key_ok(x_internal_key):
        raise HTTPException(status_code=403, detail="Invalid internal key")


# ── Request models ─────────────────────────────────────────────────────────────

class LockdownRequest(BaseModel):
    reason: str
    triggered_by: str = "system"


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/lockdown", status_code=200)
async def activate_lockdown(
    request: LockdownRequest,
    auth: Dict = Security(verify_event_auth),
):
    """
    Activate global EventStore lockdown.
    All subsequent calls to POST /api/v1/events/ will return HTTP 503, on every worker of the store.

    Idempotent — calling while already locked returns current state.
    """
    activated = await GLOBAL_LOCKDOWN.activate(
        reason=request.reason,
        triggered_by=request.triggered_by,
    )
    if not activated:
        logger.warning(
            f"[SystemRouter] Lockdown activate called but already active: "
            f"{GLOBAL_LOCKDOWN.reason}"
        )
        return {
            **GLOBAL_LOCKDOWN.to_dict(),
            "message": "Lockdown already active — state unchanged",
        }

    logger.critical(
        f"[SystemRouter] 🔒 EVENTSTORE LOCKDOWN ACTIVATED "
        f"by={request.triggered_by}: {request.reason}"
    )
    return {
        **GLOBAL_LOCKDOWN.to_dict(),
        "message": "Lockdown activated — all event appends suspended",
    }


@router.post("/lockdown/clear", status_code=200)
async def clear_lockdown(
    auth: Dict = Security(verify_event_auth),
):
    """
    Clear the lockdown state.

    This is an admin-only manual action — it is NOT called automatically by
    the supply auditor or any background task.  It requires human verification
    that the supply invariant has been restored before calling.
    """
    was_active, previous_reason = await GLOBAL_LOCKDOWN.clear()
    logger.warning(
        f"[SystemRouter] 🔓 Lockdown cleared. "
        f"Was active={was_active}, previous_reason={previous_reason}"
    )
    return {
        "lockdown_active": False,
        "previous_reason": previous_reason,
        "message": "Lockdown cleared — event appends resumed",
    }


@router.get("/lockdown/status", status_code=200)
async def get_lockdown_status():
    """
    Public status endpoint.
    Readable by supply auditor, health checks, and monitoring.
    The shared row, read at most once per LOCKDOWN_CACHE_SECONDS by each worker.
    """
    await GLOBAL_LOCKDOWN.is_locked()
    return GLOBAL_LOCKDOWN.to_dict()
