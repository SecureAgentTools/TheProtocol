"""
Admin endpoints for beta invite code management.

POST   /admin/invite-codes/generate   — Generate a batch of invite codes
GET    /admin/invite-codes             — List all codes (with status)
DELETE /admin/invite-codes/{code}      — Revoke an unused code
GET    /admin/invite-codes/validate/{code} — Check if a code is valid (public, no auth)
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, Security
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import schemas, models, security
from agentvault_registry.database import get_db
from agentvault_registry.config import settings
from agentvault_registry.core.public_url import public_base_url
from agentvault_registry.crud.invite_codes import (
    ADMIN_FLAGS,
    generate_invite_codes,
    list_invite_codes,
    delete_invite_code,
    validate_invite_code,
    get_invite_code,
    resolve_admin_flags,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/invite-codes",
    # §pass56 PR-5: tags= dropped; main.py:include_router supplies "Admin — Invite Codes"
)


def _build_invite_url(code: str, request: Request) -> str:
    """Build the full invite URL for a given code.

    §OPGUIDE-6: this used to read ``settings.BASE_URL`` raw. On a cloud operator
    that is the image's baked default ``http://localhost:8000`` — truthy, so no
    guard fired — which meant every invite link an admin copied out of the UI or
    the API pointed at their own loopback and was worthless to the recipient.
    ``public_base_url`` rejects loopback and falls back to the request's
    X-Forwarded-* host, which is correct on every deployment shape.
    """
    return f"{public_base_url(request)}/ui#/register?invite={code}"


def _code_to_response(code_obj, request: Request) -> schemas.InviteCodeResponse:
    """Convert an InviteCode model to InviteCodeResponse schema.

    ``created_by_email`` / ``used_by_email`` are read from already-loaded
    relationships (the list query eager-loads them) and are best-effort: a code
    whose creator has since been deleted still lists, with the field left None.
    """
    def _email(rel):
        try:
            return getattr(rel, "email", None) if rel is not None else None
        except Exception:
            # Un-loaded relationship outside a session — never fail a listing over a label.
            return None

    return schemas.InviteCodeResponse(
        code=code_obj.code,
        invite_url=_build_invite_url(code_obj.code, request),
        expires_at=code_obj.expires_at,
        note=code_obj.note,
        status=code_obj.status,
        use_count=code_obj.use_count,
        max_uses=code_obj.max_uses,
        grants_admin=bool(getattr(code_obj, "grants_admin", False)),
        admin_flags=resolve_admin_flags(code_obj),
        created_at=code_obj.created_at,
        used_at=getattr(code_obj, "used_at", None),
        created_by_email=_email(getattr(code_obj, "creator", None)),
        used_by_email=_email(getattr(code_obj, "used_by_dev", None)),
    )


# ---------------------------------------------------------------------------
# POST /admin/invite-codes/generate
# ---------------------------------------------------------------------------

@router.post(
    "/generate",
    response_model=schemas.InviteCodeBatchResponse,
    summary="Generate invite codes",
    status_code=status.HTTP_201_CREATED,
)
async def generate_codes(
    request: schemas.InviteCodeGenerateRequest,
    http_request: Request,
    current_developer: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a batch of beta invite codes.
    Requires admin_support (or legacy is_admin) privileges.
    Each code produces a shareable URL: BASE_URL/ui#/register?invite=<code>

    An admin-granting batch may only confer flags the CALLER holds (§INVRBAC). Without
    that clamp this endpoint is a privilege-escalation rail: it is gated on
    `admin_support`, the narrowest flag, and before the clamp a support-desk admin could
    create a code that creates an account with treasury and enforcement authority, redeem
    it, and hold everything. The rule is the same one the Cockpit Card uses: a grant is
    intersected with the granter's own authority at the moment it is made.
    """
    granted = list(request.admin_flags) if request.admin_flags else list(ADMIN_FLAGS)
    if request.grants_admin:
        # is_admin is the legacy superadmin bypass: it may still grant anything.
        if not bool(getattr(current_developer, "is_admin", False)):
            held = {f for f in ADMIN_FLAGS if bool(getattr(current_developer, f, False))}
            over_reach = [f for f in granted if f not in held]
            if over_reach:
                logger.warning(
                    f"[InviteCodes] REFUSED admin-granting batch: developer_id="
                    f"{current_developer.id} tried to grant {over_reach} it does not hold "
                    f"(holds {sorted(held)})"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "You cannot grant admin flags you do not hold yourself: "
                        f"{', '.join(over_reach)}."
                    ),
                )

    codes = await generate_invite_codes(
        db=db,
        count=request.count,
        created_by=current_developer.id,
        expires_days=request.expires_days,
        note=request.note,
        max_uses=request.max_uses,
        grants_admin=request.grants_admin,
        admin_flags=request.admin_flags,
    )
    if request.grants_admin:
        # Loud on purpose: this batch mints administrators. Anyone auditing the log
        # later should be able to see exactly when admin-granting codes were issued,
        # by whom, and with WHAT authority, without diffing the invite_codes table.
        logger.warning(
            f"[InviteCodes] ADMIN-GRANTING batch issued: count={request.count} "
            f"max_uses={request.max_uses} by developer_id={current_developer.id} "
            f"grants={granted} note={request.note!r}"
        )

    responses = [_code_to_response(c, http_request) for c in codes]
    return schemas.InviteCodeBatchResponse(codes=responses, count=len(responses))


# ---------------------------------------------------------------------------
# GET /admin/invite-codes
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=List[schemas.InviteCodeResponse],
    summary="List invite codes",
)
async def list_codes(
    http_request: Request,
    status_filter: Optional[str] = Query(None, description="Filter by status: active, used, expired"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_developer: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    """List all invite codes. admin_support (or legacy is_admin) only."""
    # §MCPTEST30: the CRUD applies active / used / expired and ignores anything else, so an unknown value answered the
    # WHOLE list (the MCP tool advertised "revoked": 100 rows back, every one active). Refused now.
    if status_filter and status_filter not in ("active", "used", "expired"):
        raise HTTPException(status_code=422, detail=f"Unknown status_filter '{status_filter}'. Must be one of: active, used, expired")
    codes = await list_invite_codes(
        db=db,
        created_by=None,  # Admin sees all codes
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )
    return [_code_to_response(c, http_request) for c in codes]


# ---------------------------------------------------------------------------
# DELETE /admin/invite-codes/{code}
# ---------------------------------------------------------------------------

@router.delete(
    "/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an invite code",
)
async def revoke_code(
    code: str,
    current_developer: models.Developer = Security(security.require_admin_flag("admin_support")),
    db: AsyncSession = Depends(get_db),
):
    """Revoke (delete) an unused invite code. admin_support (or legacy is_admin) only."""
    success = await delete_invite_code(db=db, code=code)
    if not success:
        raise HTTPException(
            status_code=404,
            detail="Code not found or already used (cannot revoke used codes)"
        )


# ---------------------------------------------------------------------------
# GET /admin/invite-codes/validate/{code}  — PUBLIC endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/validate/{code}",
    response_model=schemas.InviteCodeValidationResponse,
    summary="Validate an invite code (public)",
)
async def validate_code_public(
    code: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Public endpoint — called by the register form to show real-time validity.
    Returns {valid: bool, reason: str | null}.
    Does NOT consume the code.
    """
    valid, reason, _ = await validate_invite_code(db=db, code=code)
    return schemas.InviteCodeValidationResponse(valid=valid, reason=reason)
