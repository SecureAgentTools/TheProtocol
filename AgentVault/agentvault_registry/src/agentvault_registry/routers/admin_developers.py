"""
Admin Developer Management Router (M1, 2026-04-20)

Provides admin-facing endpoints for managing developer accounts:
  GET    /api/v1/admin/developers                        — List with filters
  GET    /api/v1/admin/developers/{id}                   — Full detail
  POST   /api/v1/admin/developers/{id}/suspend            — Suspend account
  POST   /api/v1/admin/developers/{id}/reinstate          — Reinstate account
  POST   /api/v1/admin/developers/{id}/force-password-reset  — Email reset token
  POST   /api/v1/admin/developers/{id}/disable-2fa        — Emergency 2FA unlock
  POST   /api/v1/admin/developers/{id}/force-email-verify — Manual email verify
  POST   /api/v1/admin/developers/{id}/revoke-api-keys    — Invalidate all keys
  DELETE /api/v1/admin/developers/{id}                    — Soft-delete
  GET    /api/v1/admin/developers/{id}/activity           — EventStore activity

All endpoints gate on granular admin flags via require_admin_flag(...):
  list/detail/activity/support-ops → admin_support
  suspend/reinstate → admin_enforcement
  delete/admin-flags → admin_platform
Legacy is_admin=True passes every check via super-flag fallback.
All mutations emit audit events to EventStore.
"""
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Path, status, Security
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentvault_registry import models, schemas, security
from agentvault_registry.database import get_db
from agentvault_registry.event_emitter import get_event_emitter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin/developers",
    tags=["Admin — Developer Management"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _load_developer(
    db: AsyncSession,
    developer_id: int,
    *,
    include_relations: bool = False,
) -> models.Developer:
    """Load developer by id, 404 if not found. Optionally eager-load relations."""
    stmt = select(models.Developer).where(models.Developer.id == developer_id)
    if include_relations:
        stmt = stmt.options(
            selectinload(models.Developer.api_keys),
            selectinload(models.Developer.organization_memberships).selectinload(
                models.OrganizationMember.organization
            ),
        )
    result = await db.execute(stmt)
    developer = result.scalar_one_or_none()
    if developer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Developer {developer_id} not found",
        )
    return developer


async def _agent_count(db: AsyncSession, developer_id: int) -> int:
    """Count agents created by this developer (active + suspended + revoked)."""
    stmt = select(func.count(models.Agent.id)).where(
        models.Agent.creator_developer_id == developer_id
    )
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


async def _emit_admin_action(
    *,
    event_type: str,
    target_developer_id: int,
    actor: models.Developer,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Emit an audit event to EventStore for an admin action on a developer.

    Schema: aggregate_type='Developer', aggregate_id=f'developer:{id}',
    data includes actor_developer_id, actor_email, action, and caller-supplied
    context.

    Never raises — audit emission failure should not block the admin action.
    Event policies are seeded by migration 0009; skip_in_projection=true.
    """
    try:
        emitter = get_event_emitter()
        payload = {
            "actor_developer_id": actor.id,
            "actor_email": actor.email,
            "target_developer_id": target_developer_id,
        }
        if data:
            payload.update(data)
        await emitter.emit(
            event_type=event_type,
            aggregate_id=f"developer:{target_developer_id}",
            aggregate_type="Developer",
            data=payload,
        )
    except Exception as e:
        logger.error(f"[AdminDevelopers] Failed to emit {event_type}: {e}", exc_info=True)


def _to_admin_read(dev: models.Developer, agent_count: int = 0) -> schemas.DeveloperAdminRead:
    """Shape Developer model into DeveloperAdminRead list-row shape."""
    return schemas.DeveloperAdminRead(
        id=dev.id,
        name=dev.name,
        email=dev.email,
        is_verified=dev.is_verified,
        is_admin=dev.is_admin,
        two_fa_enabled=bool(dev.two_fa_enabled),
        is_suspended=bool(getattr(dev, "is_suspended", False)),
        is_federation_operator=bool(dev.is_federation_operator),
        federation_operator_status=dev.federation_operator_status,
        must_change_password=bool(getattr(dev, "must_change_password", False)),
        agent_count=agent_count,
        last_login_at=dev.last_login_at,
        created_at=dev.created_at,
        deleted_at=getattr(dev, "deleted_at", None),
        suspended_at=getattr(dev, "suspended_at", None),
        suspended_reason=getattr(dev, "suspended_reason", None),
        admin_treasury=bool(getattr(dev, "admin_treasury", False)),
        admin_support=bool(getattr(dev, "admin_support", False)),
        admin_enforcement=bool(getattr(dev, "admin_enforcement", False)),
        admin_federation=bool(getattr(dev, "admin_federation", False)),
        admin_platform=bool(getattr(dev, "admin_platform", False)),
        agents_unlisted_by_default=bool(getattr(dev, "agents_unlisted_by_default", False)),
    )


# ---------------------------------------------------------------------------
# GET / — list with filters
# ---------------------------------------------------------------------------

@router.get("", response_model=schemas.DeveloperAdminListResponse, summary="List developers")
async def list_developers(
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        pattern=r"^(all|verified|unverified|admins|operators|suspended|deleted)$",
        description="all | verified | unverified | admins | operators | suspended | deleted",
    ),
    has_2fa: Optional[bool] = Query(None, description="Filter by 2FA enabled"),
    search: Optional[str] = Query(None, max_length=200, description="Free-text on name/email"),
    include_deleted: bool = Query(False, description="Include soft-deleted developers"),
    include_federated: bool = Query(
        False,
        description="§pass66.9 — include `is_federation_shadow=TRUE` placeholder rows "
                    "(FK plumbing for federated agent_cards; never real users). "
                    "Default: hide. Set true for federation debugging.",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_support")),
) -> schemas.DeveloperAdminListResponse:
    """List developers with filters and pagination."""
    base = select(models.Developer)
    count_base = select(func.count(models.Developer.id))

    conditions = []

    if not include_deleted:
        conditions.append(models.Developer.deleted_at.is_(None))

    # §pass66.9 — federation-shadow filter (replaces the FE-only string-match
    # in AdminDevelopers.vue from §pass66.4). On a freshly-provisioned cloud-op
    # the first federation_sync cycle creates 20-40 placeholder developer rows
    # to satisfy agent_cards.developer_id NOT NULL FK. They're never real
    # users; hide by default.
    if not include_federated:
        conditions.append(models.Developer.is_federation_shadow.is_(False))

    if status_filter == "verified":
        conditions.append(models.Developer.is_verified.is_(True))
    elif status_filter == "unverified":
        conditions.append(models.Developer.is_verified.is_(False))
    elif status_filter == "admins":
        conditions.append(models.Developer.is_admin.is_(True))
    elif status_filter == "operators":
        conditions.append(models.Developer.is_federation_operator.is_(True))
    elif status_filter == "suspended":
        conditions.append(models.Developer.is_suspended.is_(True))
    elif status_filter == "deleted":
        # override include_deleted
        conditions = [c for c in conditions if True]  # keep others
        conditions.append(models.Developer.deleted_at.is_not(None))

    if has_2fa is True:
        conditions.append(models.Developer.two_fa_enabled.is_(True))
    elif has_2fa is False:
        conditions.append(models.Developer.two_fa_enabled.is_(False))

    if search:
        like = f"%{search.lower()}%"
        conditions.append(
            or_(
                func.lower(models.Developer.name).like(like),
                func.lower(models.Developer.email).like(like),
                func.lower(func.coalesce(models.Developer.company, "")).like(like),
            )
        )

    if conditions:
        base = base.where(and_(*conditions))
        count_base = count_base.where(and_(*conditions))

    total_result = await db.execute(count_base)
    total = int(total_result.scalar() or 0)

    list_result = await db.execute(
        base.order_by(models.Developer.created_at.desc())
            .limit(limit)
            .offset(offset)
    )
    developers = list_result.scalars().all()

    # Bulk agent counts in one query
    if developers:
        dev_ids = [d.id for d in developers]
        count_result = await db.execute(
            select(
                models.Agent.creator_developer_id,
                func.count(models.Agent.id),
            )
            .where(models.Agent.creator_developer_id.in_(dev_ids))
            .group_by(models.Agent.creator_developer_id)
        )
        counts_by_dev = {row[0]: int(row[1]) for row in count_result.all()}
    else:
        counts_by_dev = {}

    return schemas.DeveloperAdminListResponse(
        developers=[_to_admin_read(d, counts_by_dev.get(d.id, 0)) for d in developers],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /{id} — full detail
# ---------------------------------------------------------------------------

# §MCPTEST30 (V0552): the detail named each agent with ONE QUERY PER AGENT; the sandbox tester's developer owns 6,685
# agents, so its detail issued ~6,700 queries and timed out (the MCP tester's getAdminDeveloperDetail, round 17). The
# names now come from one read per chunk: the latest active card of each agent (DISTINCT ON agent_did).
_NAME_CHUNK = 5000


def _agent_card_names_stmt(dids: List[str]):
    return (select(models.AgentCard.agent_did, models.AgentCard.name)
            .where(models.AgentCard.agent_did.in_(dids), models.AgentCard.is_active.is_(True))
            .order_by(models.AgentCard.agent_did, models.AgentCard.created_at.desc())
            .distinct(models.AgentCard.agent_did))


async def _agent_card_names(db: AsyncSession, dids: List[str]) -> Dict[str, Optional[str]]:
    """Each agent's name from its latest active card; best-effort, as before (an agent may have no card yet)."""
    names: Dict[str, Optional[str]] = {}
    for i in range(0, len(dids), _NAME_CHUNK):
        try:
            rows = await db.execute(_agent_card_names_stmt(dids[i:i + _NAME_CHUNK]))
            names.update({d: n for d, n in rows.all()})
        except Exception as e:  # noqa: BLE001 — the names are decoration on an admin read
            logger.warning("admin developer detail: agent names unreadable (%s); listing the agents without them",
                           type(e).__name__)
            break
    return names


@router.get("/{developer_id}", response_model=schemas.DeveloperAdminDetailRead, summary="Developer detail")
async def get_developer_detail(
    developer_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_support")),
) -> schemas.DeveloperAdminDetailRead:
    """Return full developer detail including agents, api keys, and organisation memberships."""
    dev = await _load_developer(db, developer_id, include_relations=True)

    # Agents
    agents_result = await db.execute(
        select(models.Agent).where(models.Agent.creator_developer_id == developer_id)
        .order_by(models.Agent.created_at.desc())
    )
    agents = agents_result.scalars().all()
    names = await _agent_card_names(db, [a.did for a in agents])

    agent_summaries: List[schemas.DeveloperAdminAgentSummary] = []
    for a in agents:
        agent_summaries.append(schemas.DeveloperAdminAgentSummary(
            did=a.did,
            name=names.get(a.did),
            status=a.status,
            enforcement_status=getattr(a, "enforcement_status", None),
            created_at=a.created_at,
            last_active_at=a.last_active_at,
        ))

    # API keys
    api_key_summaries = [
        schemas.DeveloperAdminApiKeySummary(
            id=k.id,
            key_prefix=k.key_prefix,
            description=k.description,
            is_active=k.is_active,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
        )
        for k in dev.api_keys
    ]

    # Organisation memberships
    org_memberships: List[schemas.DeveloperAdminOrgMembership] = []
    for m in dev.organization_memberships:
        if m.is_active and m.organization and m.organization.is_active:
            org_memberships.append(schemas.DeveloperAdminOrgMembership(
                organization_id=m.organization_id,
                organization_name=m.organization.name,
                role=m.role,
            ))

    # Operator application
    op_app_id: Optional[str] = None
    if dev.is_federation_operator:
        op_result = await db.execute(
            select(models.OperatorApplication.id)
            .where(models.OperatorApplication.developer_id == developer_id)
            .order_by(models.OperatorApplication.created_at.desc())
            .limit(1)
        )
        op_app_id = op_result.scalar_one_or_none()

    base = _to_admin_read(dev, len(agent_summaries))
    return schemas.DeveloperAdminDetailRead(
        **base.model_dump(),
        display_name=dev.display_name,
        bio=dev.bio,
        avatar_url=dev.avatar_url,
        website_url=dev.website_url,
        github_url=dev.github_url,
        twitter_handle=dev.twitter_handle,
        company=dev.company,
        timezone=dev.timezone,
        profile_visibility=dev.profile_visibility,
        latitude=dev.latitude,
        longitude=dev.longitude,
        location_label=dev.location_label,
        agents=agent_summaries,
        api_keys=api_key_summaries,
        organizations=org_memberships,
        operator_application_id=op_app_id,
    )


# ---------------------------------------------------------------------------
# POST /{id}/suspend
# ---------------------------------------------------------------------------

@router.post(
    "/{developer_id}/suspend",
    response_model=schemas.DeveloperAdminActionResponse,
    summary="Suspend developer account",
)
async def suspend_developer(
    developer_id: int,
    body: schemas.DeveloperSuspendRequest,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_enforcement")),
) -> schemas.DeveloperAdminActionResponse:
    dev = await _load_developer(db, developer_id)

    if dev.id == admin.id:
        raise HTTPException(400, "Cannot suspend yourself")
    if dev.deleted_at is not None:
        raise HTTPException(400, "Cannot suspend a deleted developer")
    if dev.is_suspended:
        raise HTTPException(400, "Developer is already suspended")

    now = datetime.now(timezone.utc)
    dev.is_suspended = True
    dev.suspended_at = now
    dev.suspended_by = admin.id
    dev.suspended_reason = body.reason
    # AL-2 (2026-07-24): admin force-logout — suspending a developer immediately
    # invalidates all their live access tokens (a suspended dev with a stolen or
    # cached token can no longer act until the token expires). Complements the
    # RA6 refresh gate (a suspended dev also can't mint new tokens).
    dev.token_version = (dev.token_version or 0) + 1

    # Phase 6 cascade: coordinated-suspend ALL agents owned by this developer.
    # Each per-agent step (registry status + mTLS revoke + TEG suspend) is best-effort;
    # the cascade never aborts. Per-agent results are logged + summarized in response.
    cascade_summary: List[dict] = []
    cascade_reason = body.reason or f"developer suspended (id={developer_id})"
    try:
        from agentvault_registry.services.coordinated_suspension import (
            cascade_suspend_developer_agents,
        )
        cascade_results = await cascade_suspend_developer_agents(
            db, developer_id, reason=cascade_reason, actor=admin, soft=False,
        )
        for cr in cascade_results:
            cascade_summary.append(cr.as_dict())
        if cascade_results:
            mtls_revoked = sum(1 for c in cascade_results if c.mtls == "revoked")
            teg_suspended = sum(1 for c in cascade_results if c.teg == "suspended")
            logger.warning(
                f"[AdminDevelopers] Cascade-suspended {len(cascade_results)} agents for "
                f"developer {developer_id} (mtls_revoked={mtls_revoked}, teg_suspended={teg_suspended})"
            )
    except Exception as exc:
        logger.error(
            f"[AdminDevelopers] Cascade-suspend failed for developer {developer_id}: {exc}"
        )
        # don't fail the whole dev suspend — admin still wants the dev blocked

    await db.commit()
    logger.warning(
        f"[AdminDevelopers] Developer {developer_id} SUSPENDED by admin {admin.id} ({admin.email}): {body.reason}"
    )
    await _emit_admin_action(
        event_type="DeveloperSuspended",
        target_developer_id=developer_id,
        actor=admin,
        data={
            "reason": body.reason,
            "target_email": dev.email,
            "cascade_count": len(cascade_summary),
            "cascade_results": cascade_summary[:50],  # cap so EventStore payload doesn't bloat
        },
    )

    # §NOTIFV2 (2026-07-27): tell the account owner. `account.suspended` is one of four
    # mandatory catalog types — the resolver short-circuits every preference, mute and quiet
    # hour for it, because "you have been locked out" is not something a person may
    # accidentally opt out of. It shipped with emitter=False, i.e. the guarantee existed and
    # nothing could trigger it; this is the trigger. Fires POST-COMMIT so a suspend that
    # rolled back can never phantom-notify, and is wrapped because an admin enforcement
    # action must never fail on account of a notification.
    try:
        from agentvault_registry.background_tasks.push_notify import notify
        await notify(
            "account.suspended", [developer_id],
            title="Account suspended",
            message=(f"Your developer account was suspended. Reason: {body.reason}"
                     if body.reason else "Your developer account was suspended."),
            tags="rotating_light", priority="max", click="/ui/#/settings",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[AdminDevelopers] account.suspended notify failed for developer %s: %s",
            developer_id, exc,
        )

    return schemas.DeveloperAdminActionResponse(
        developer_id=developer_id,
        action="suspend",
        status="suspended",
        message=(
            f"Developer {dev.email} suspended. Reason: {body.reason}. "
            f"Cascaded {len(cascade_summary)} owned agents."
        ),
    )


# ---------------------------------------------------------------------------
# POST /{id}/reinstate
# ---------------------------------------------------------------------------

@router.post(
    "/{developer_id}/reinstate",
    response_model=schemas.DeveloperAdminActionResponse,
    summary="Reinstate suspended developer",
)
async def reinstate_developer(
    developer_id: int,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_enforcement")),
) -> schemas.DeveloperAdminActionResponse:
    dev = await _load_developer(db, developer_id)

    if not dev.is_suspended:
        raise HTTPException(400, "Developer is not suspended")
    if dev.deleted_at is not None:
        raise HTTPException(400, "Cannot reinstate a deleted developer")

    prior_reason = dev.suspended_reason
    dev.is_suspended = False
    dev.suspended_at = None
    dev.suspended_by = None
    dev.suspended_reason = None

    # Phase 6 cascade: reinstate suspended agents owned by this developer.
    # Only touches agents currently in "suspended" state — agents suspended by
    # another flow (e.g., individual offense) stay as-is.
    cascade_summary: List[dict] = []
    try:
        from agentvault_registry.services.coordinated_suspension import (
            cascade_reinstate_developer_agents,
        )
        cascade_results = await cascade_reinstate_developer_agents(
            db, developer_id, actor=admin, soft=False,
        )
        for cr in cascade_results:
            cascade_summary.append(cr.as_dict())
        if cascade_results:
            mtls_enrolled = sum(1 for c in cascade_results if c.mtls == "enrolled")
            teg_reinstated = sum(1 for c in cascade_results if c.teg == "reinstated")
            logger.info(
                f"[AdminDevelopers] Cascade-reinstated {len(cascade_results)} agents for "
                f"developer {developer_id} (mtls_enrolled={mtls_enrolled}, teg_reinstated={teg_reinstated})"
            )
    except Exception as exc:
        logger.error(
            f"[AdminDevelopers] Cascade-reinstate failed for developer {developer_id}: {exc}"
        )

    await db.commit()
    logger.info(
        f"[AdminDevelopers] Developer {developer_id} REINSTATED by admin {admin.id} ({admin.email})"
    )
    await _emit_admin_action(
        event_type="DeveloperReinstated",
        target_developer_id=developer_id,
        actor=admin,
        data={
            "target_email": dev.email,
            "prior_reason": prior_reason,
            "cascade_count": len(cascade_summary),
            "cascade_results": cascade_summary[:50],
        },
    )

    # §NOTIFV2 (2026-07-27): the other half of the pair. Not mandatory (being told you are
    # back is good news, not a lockout), so it honours preferences normally.
    try:
        from agentvault_registry.background_tasks.push_notify import notify
        await notify(
            "account.reinstated", [developer_id],
            title="Account reinstated",
            message=(
                f"Your developer account was reinstated. {len(cascade_summary)} agent(s) restored."
                if cascade_summary else "Your developer account was reinstated."
            ),
            tags="white_check_mark", priority="high", click="/ui/#/settings",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[AdminDevelopers] account.reinstated notify failed for developer %s: %s",
            developer_id, exc,
        )

    return schemas.DeveloperAdminActionResponse(
        developer_id=developer_id,
        action="reinstate",
        status="active",
        message=(
            f"Developer {dev.email} reinstated. Cascaded {len(cascade_summary)} owned agents."
        ),
    )


# ---------------------------------------------------------------------------
# POST /{id}/force-password-reset
# ---------------------------------------------------------------------------

@router.post(
    "/{developer_id}/force-password-reset",
    response_model=schemas.DeveloperAdminActionResponse,
    summary="Force password reset (send email)",
)
async def force_password_reset(
    developer_id: int,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_support")),
) -> schemas.DeveloperAdminActionResponse:
    dev = await _load_developer(db, developer_id)

    if dev.deleted_at is not None:
        raise HTTPException(400, "Cannot reset password for a deleted developer")

    # Generate password reset token (follows auth_secure.py convention)
    token = secrets.token_urlsafe(48)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    dev.password_reset_token = token
    dev.password_reset_token_expires = expires

    await db.commit()

    # Email delivery is best-effort; log if email_utils unavailable
    try:
        from agentvault_registry.email_utils import send_password_reset_email  # type: ignore
        await send_password_reset_email(dev.email, dev.name or dev.email, token)
        email_sent = True
    except Exception as e:
        logger.warning(f"[AdminDevelopers] Password-reset email send failed for {dev.email}: {e}")
        email_sent = False

    logger.info(
        f"[AdminDevelopers] Password reset forced for developer {developer_id} ({dev.email}) by admin {admin.id}"
    )
    await _emit_admin_action(
        event_type="DeveloperForcePasswordReset",
        target_developer_id=developer_id,
        actor=admin,
        data={"target_email": dev.email, "email_sent": email_sent, "expires_at": expires.isoformat()},
    )

    # Redact email in response
    local, _, domain = dev.email.partition("@")
    redacted = f"{local[:2]}***@{domain}" if domain else "***"
    return schemas.DeveloperAdminActionResponse(
        developer_id=developer_id,
        action="force_password_reset",
        status="reset_token_issued",
        message=f"Password reset token issued; email {'sent' if email_sent else 'queue failed (see logs)'}: {redacted}",
    )


# ---------------------------------------------------------------------------
# POST /{id}/disable-2fa
# ---------------------------------------------------------------------------

@router.post(
    "/{developer_id}/disable-2fa",
    response_model=schemas.DeveloperAdminActionResponse,
    summary="Disable 2FA (emergency unlock)",
)
async def disable_2fa(
    developer_id: int,
    body: schemas.DeveloperActionReasonRequest,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_support")),
) -> schemas.DeveloperAdminActionResponse:
    dev = await _load_developer(db, developer_id)

    if dev.deleted_at is not None:
        raise HTTPException(400, "Cannot disable 2FA for a deleted developer")
    if not dev.two_fa_enabled:
        raise HTTPException(400, "Developer does not have 2FA enabled")

    dev.two_fa_enabled = False
    dev.totp_secret = None
    dev.backup_codes = None
    dev.two_fa_verified_at = None
    dev.two_fa_recovery_attempts = 0
    dev.two_fa_last_failure = None
    # trusted_devices intentionally kept — user may still trust this device after re-enrolling

    await db.commit()
    logger.warning(
        f"[AdminDevelopers] 2FA DISABLED for developer {developer_id} ({dev.email}) by admin {admin.id}: {body.reason}"
    )
    await _emit_admin_action(
        event_type="DeveloperDisable2FA",
        target_developer_id=developer_id,
        actor=admin,
        data={"target_email": dev.email, "reason": body.reason},
    )

    # §NOTIFV2 security.2fa_changed — call site 3 of 3 (admin force-disable). The OWNER is told,
    # not the admin: someone else removing your second factor is a security event you must hear
    # about even though you did not perform it.
    try:
        import asyncio as _aio_n
        from agentvault_registry.background_tasks.push_notify import notify
        _aio_n.create_task(notify(
            "security.2fa_changed", [developer_id],
            title="Two-factor authentication disabled by an admin",
            message=f"An administrator turned off 2FA on your account. Reason: {body.reason}",
            tags="warning", priority="high", click="/ui/#/settings"))
    except Exception:  # noqa: BLE001
        logger.debug("[NOTIFY] security.2fa_changed emit failed", exc_info=True)

    return schemas.DeveloperAdminActionResponse(
        developer_id=developer_id,
        action="disable_2fa",
        status="2fa_disabled",
        message=f"2FA disabled for {dev.email}. User will be prompted to re-enrol on next login.",
    )


# ---------------------------------------------------------------------------
# POST /{id}/force-email-verify
# ---------------------------------------------------------------------------

@router.post(
    "/{developer_id}/force-email-verify",
    response_model=schemas.DeveloperAdminActionResponse,
    summary="Force email verification (manual)",
)
async def force_email_verify(
    developer_id: int,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_support")),
) -> schemas.DeveloperAdminActionResponse:
    dev = await _load_developer(db, developer_id)

    if dev.deleted_at is not None:
        raise HTTPException(400, "Cannot verify email for a deleted developer")
    if dev.is_verified:
        raise HTTPException(400, "Developer email is already verified")

    dev.is_verified = True
    dev.email_verification_token = None
    dev.verification_token_expires = None

    await db.commit()
    # §R55: the flag lives in a ROW; the peers only re-pull the CARDS. Touch them.
    from agentvault_registry.services.card_touch import touch_developer_native_cards
    await touch_developer_native_cards(db, dev.id, reason="admin force-verify")
    logger.info(
        f"[AdminDevelopers] Email manually verified for developer {developer_id} ({dev.email}) by admin {admin.id}"
    )
    await _emit_admin_action(
        event_type="DeveloperForceEmailVerify",
        target_developer_id=developer_id,
        actor=admin,
        data={"target_email": dev.email},
    )

    return schemas.DeveloperAdminActionResponse(
        developer_id=developer_id,
        action="force_email_verify",
        status="verified",
        message=f"Email manually verified for {dev.email}",
    )


# ---------------------------------------------------------------------------
# POST /{id}/revoke-api-keys
# ---------------------------------------------------------------------------

@router.post(
    "/{developer_id}/revoke-api-keys",
    response_model=schemas.DeveloperAdminActionResponse,
    summary="Revoke all programmatic API keys for a developer",
)
async def revoke_api_keys(
    developer_id: int,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_support")),
) -> schemas.DeveloperAdminActionResponse:
    dev = await _load_developer(db, developer_id)

    if dev.deleted_at is not None:
        raise HTTPException(400, "Cannot revoke keys for a deleted developer")

    keys_stmt = select(models.DeveloperApiKey).where(
        models.DeveloperApiKey.developer_id == developer_id,
        models.DeveloperApiKey.is_active.is_(True),
    )
    result = await db.execute(keys_stmt)
    keys = result.scalars().all()

    revoked_count = 0
    for key in keys:
        key.is_active = False
        revoked_count += 1

    await db.commit()
    logger.warning(
        f"[AdminDevelopers] Revoked {revoked_count} API keys for developer {developer_id} ({dev.email}) by admin {admin.id}"
    )
    await _emit_admin_action(
        event_type="DeveloperRevokeApiKeys",
        target_developer_id=developer_id,
        actor=admin,
        data={"target_email": dev.email, "revoked_count": revoked_count},
    )

    return schemas.DeveloperAdminActionResponse(
        developer_id=developer_id,
        action="revoke_api_keys",
        status="revoked",
        message=f"Revoked {revoked_count} API keys for {dev.email}",
    )


# ---------------------------------------------------------------------------
# DELETE /{id} — soft delete
# ---------------------------------------------------------------------------

@router.post(
    "/{developer_id}/gift-provisioning",
    response_model=schemas.DeveloperAdminActionResponse,
    summary="§pass66.9 — Admin-gift cloud-op provisioning unlock months",
)
async def gift_provisioning(
    developer_id: int,
    body: schemas.GiftProvisioningRequest,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_treasury")),
) -> schemas.DeveloperAdminActionResponse:
    """Gift cloud-op provisioning unlock months to a developer (mainframe-only).

    Bumps `Developer.provisioning_unlocked_until` forward by `months × 30 days`
    (or extends an already-unlocked window) and increments
    `provisioning_months_total` for audit.

    Doesn't move money — strictly a Commander/admin gift. Recipient sees the
    extra months at their next `GET /me/provisioning-eligibility` call.

    Gates:
      - Mainframe-only (router-level dep already enforces).
      - `admin_treasury` flag (gift = monetary value; treasury auth is the
        natural fit. Could also be `admin_platform` but Commander chose
        treasury per the original P10 spec).
    """
    # Mainframe gate: a cloud-op refuses with the mainframe-only answer (D6-820: 404, the code word first).
    from agentvault_registry.core.mainframe_gate import is_mainframe, mainframe_only_refusal
    if not is_mainframe():
        raise mainframe_only_refusal(
            "Gift provisioning is mainframe-only (cloud-ops cannot extend their own provisioning).")

    dev = await _load_developer(db, developer_id)
    if dev.deleted_at is not None:
        raise HTTPException(400, "Cannot gift provisioning to a deleted developer")

    # Compute new unlocked_until: max(now, current_unlocked_until) + months × 30d.
    # Extending a still-active window vs reviving a lapsed one both produce
    # the user-expected "extra months on top of whatever they have now".
    import os as _os_gp
    days_per_month = int(_os_gp.environ.get("PROVISIONING_DAYS_PER_MONTH", "30"))
    now_utc = datetime.now(timezone.utc)
    base_anchor = dev.provisioning_unlocked_until if (
        dev.provisioning_unlocked_until and dev.provisioning_unlocked_until > now_utc
    ) else now_utc
    new_unlocked_until = base_anchor + timedelta(days=body.months * days_per_month)

    dev.provisioning_unlocked_until = new_unlocked_until
    dev.provisioning_months_total = (dev.provisioning_months_total or 0) + body.months
    await db.commit()

    # Audit-emit so the gift is traceable. Non-fatal on emit failure.
    await _emit_admin_action(
        event_type="ProvisioningGifted",
        target_developer_id=dev.id,
        actor=admin,
        data={
            "months_gifted": body.months,
            "reason": body.reason,
            "new_unlocked_until": new_unlocked_until.isoformat(),
            "new_months_total": dev.provisioning_months_total,
            "target_email": dev.email,
        },
    )

    return schemas.DeveloperAdminActionResponse(
        developer_id=dev.id,
        action="provisioning_gifted",
        status="ok",
        message=(
            f"Gifted {body.months} month(s) of cloud-op provisioning to {dev.email}. "
            f"Unlocked until {new_unlocked_until.isoformat()} "
            f"(total months gifted across lifetime: {dev.provisioning_months_total})."
        ),
    )


@router.delete(
    "/{developer_id}",
    response_model=schemas.DeveloperAdminActionResponse,
    summary="Soft-delete developer (PII scrub, row retained)",
)
async def delete_developer(
    developer_id: int,
    body: schemas.DeveloperDeleteRequest,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> schemas.DeveloperAdminActionResponse:
    dev = await _load_developer(db, developer_id)

    if dev.id == admin.id:
        raise HTTPException(400, "Cannot delete yourself")
    if dev.is_admin:
        raise HTTPException(400, "Cannot delete admin accounts via this endpoint")
    if dev.deleted_at is not None:
        raise HTTPException(400, "Developer is already deleted")
    if str(body.confirm_email).lower() != dev.email.lower():
        raise HTTPException(400, "confirm_email does not match target developer's email")

    now = datetime.now(timezone.utc)
    original_email = dev.email

    # PII scrub — retain row for audit
    dev.deleted_at = now
    dev.is_suspended = True  # belt-and-suspenders: blocks login immediately
    dev.suspended_at = dev.suspended_at or now
    dev.suspended_by = dev.suspended_by or admin.id
    dev.suspended_reason = f"account deleted: {body.reason[:400]}"
    dev.hashed_password = "!deleted!"  # Bcrypt-invalid → login impossible
    dev.totp_secret = None
    dev.two_fa_enabled = False
    dev.backup_codes = None
    dev.trusted_devices = None
    dev.password_reset_token = None
    dev.email_verification_token = None

    # Revoke all API keys as a side-effect
    keys_stmt = select(models.DeveloperApiKey).where(
        models.DeveloperApiKey.developer_id == developer_id,
        models.DeveloperApiKey.is_active.is_(True),
    )
    keys_result = await db.execute(keys_stmt)
    for key in keys_result.scalars().all():
        key.is_active = False

    # ─── §ORPHANLIST (2026-09-10) — A DELETED ACCOUNT MUST NOT KEEP OFFERING SERVICES ───
    #
    # This handler already tells the caller "their agents are now orphaned", and until today
    # that is ALL it did: the cards stayed active and LISTED, advertising work on behalf of an
    # account that no longer exists. Nobody could take them down either, because
    # `PATCH /agent-cards/{id}/listing` is owner-only and admins deliberately get no bypass —
    # so a deleted owner is a ONE-WAY DOOR into a permanently listed card. `reinstate` refuses
    # a deleted developer, which closes the only other way back.
    #
    # Measured on frame-c 2026-09-10: 32 `OSFE …` OurState E2E throwaways, every owner
    # soft-deleted, every card still active and still listed, and — because each carries a
    # shadow_chancellor flare sidecar — filling registry-a's DISTINGUISHED AGENTS shelf ahead
    # of every real flare-bearer, on a mirror, on another frame. His words: *"our state
    # throwaway agents are still displayed at distiguished agents … make them not list."*
    #
    # Unlisting is the right verb, not deactivating: the card must stay FETCHABLE by DID so a
    # counterparty holding a past receipt can still read who they dealt with. `updated_at` is
    # touched deliberately — §LISTPROP's export walks `updated_at > cursor`, so a silent write
    # would never reach the peers already holding a mirror.
    cards_stmt = select(models.AgentCard).where(
        models.AgentCard.developer_id == developer_id,
        models.AgentCard.unlisted.is_(False),
    )
    unlisted_cards = 0
    for card in (await db.execute(cards_stmt)).scalars().all():
        card.unlisted = True
        card.updated_at = now
        unlisted_cards += 1

    await db.commit()
    logger.warning(
        f"[AdminDevelopers] Developer {developer_id} ({original_email}) SOFT-DELETED by admin {admin.id}: {body.reason}"
    )
    await _emit_admin_action(
        event_type="DeveloperDeleted",
        target_developer_id=developer_id,
        actor=admin,
        data={"target_email": original_email, "reason": body.reason,
              "unlisted_cards": unlisted_cards},
    )

    # §NOTIFV2 (2026-07-27): the third account-lifecycle path. This function also sets
    # is_suspended=True, but firing account.suspended here would misdescribe a deletion, so it
    # gets its own type rather than staying silent. Soft-delete does not scrub device rows, so
    # the push can still land.
    try:
        from agentvault_registry.background_tasks.push_notify import notify
        await notify(
            "account.deleted", [developer_id],
            title="Account deleted",
            message=(f"Your developer account was deleted. Reason: {body.reason}"
                     if body.reason else "Your developer account was deleted."),
            tags="warning", priority="max", click="/ui/#/",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[AdminDevelopers] account.deleted notify failed for developer %s: %s",
            developer_id, exc,
        )

    return schemas.DeveloperAdminActionResponse(
        developer_id=developer_id,
        action="delete",
        status="deleted",
        message=(f"Developer {original_email} soft-deleted. {unlisted_cards} agent card(s) unlisted "
                 f"— they stay fetchable by DID but stop being offered. Their agents are now "
                 f"orphaned (visible at /admin/agents/orphans)."),
    )


# ---------------------------------------------------------------------------
# PUT /{id}/admin-flags  (Fix 1, 2026-04-20)
# ---------------------------------------------------------------------------

@router.put(
    "/{developer_id}/admin-flags",
    response_model=schemas.DeveloperAdminRead,
    summary="Update granular admin flags (admin_treasury / admin_support / admin_enforcement / admin_federation / admin_platform)",
)
async def update_admin_flags(
    developer_id: int,
    body: schemas.DeveloperAdminFlagsUpdate,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> schemas.DeveloperAdminRead:
    """
    Update one or more granular admin flags for a developer.

    Only fields present in the body are modified; omitted fields are left unchanged.
    This lets an admin grant `admin_support=True` to a new hire without touching
    their other flags.

    Guardrails:
    - Cannot modify your own flags (prevents self-lockout).
    - Cannot touch a suspended or deleted developer.
    - Emits DeveloperAdminFlagsChanged audit event with before/after payload.
    """
    if developer_id == admin.id:
        raise HTTPException(400, "Cannot modify your own admin flags")

    dev = await _load_developer(db, developer_id)

    if dev.deleted_at is not None:
        raise HTTPException(400, "Cannot modify flags on a deleted developer")
    if dev.is_suspended:
        raise HTTPException(400, "Reinstate the developer before modifying admin flags")

    flag_names = (
        "admin_treasury",
        "admin_support",
        "admin_enforcement",
        "admin_federation",
        "admin_platform",
        # §FRAMELIC — the service-account marker travels the same rail: same guardrails,
        # same before/after audit event. It is not an admin GRANT, it is a posture.
        "agents_unlisted_by_default",
    )
    before = {f: bool(getattr(dev, f, False)) for f in flag_names}
    changes: Dict[str, Any] = {}

    for flag in flag_names:
        new_value = getattr(body, flag, None)
        if new_value is None:
            continue
        if bool(getattr(dev, flag)) == bool(new_value):
            continue
        setattr(dev, flag, bool(new_value))
        changes[flag] = {"from": before[flag], "to": bool(new_value)}

    if not changes:
        # No-op, return current shape without emitting an event
        count = await _agent_count(db, dev.id)
        return _to_admin_read(dev, count)

    await db.commit()
    logger.warning(
        f"[AdminDevelopers] Admin flags for developer {developer_id} ({dev.email}) "
        f"changed by admin {admin.id}: {changes}"
    )
    await _emit_admin_action(
        event_type="DeveloperAdminFlagsChanged",
        target_developer_id=developer_id,
        actor=admin,
        data={"target_email": dev.email, "changes": changes},
    )

    count = await _agent_count(db, dev.id)
    return _to_admin_read(dev, count)


# ---------------------------------------------------------------------------
# GET /{id}/activity
# ---------------------------------------------------------------------------

@router.get(
    "/{developer_id}/activity",
    response_model=List[Dict[str, Any]],
    summary="Recent EventStore activity concerning this developer",
)
async def get_developer_activity(
    developer_id: int,
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_support")),
) -> List[Dict[str, Any]]:
    """
    Return recent EventStore events whose aggregate_id == f'developer:{id}'.

    Best-effort: if EventStore is unreachable, returns an empty list with a log warning
    rather than 500-ing (the admin view should still render the rest of the detail drawer).
    """
    # Verify target exists (404 if not)
    await _load_developer(db, developer_id)

    import os
    import aiohttp

    from ..es_ssl_helper import get_es_ssl_context

    event_store_url = os.getenv("EVENT_STORE_URL", "http://localhost:8200")
    internal_key = os.getenv("EVENT_STORE_API_KEY", os.getenv("EVENT_STORE_INTERNAL_KEY", ""))

    url = f"{event_store_url}/api/v1/events/aggregate/developer:{developer_id}"
    headers = {"X-Internal-Key": internal_key} if internal_key else {}

    try:
        # §SOVKIT T5 (2026-09-14): the store's TLS context (SPIRE bundle + system roots + the SVID), the reactor's pattern;
        # a bare session presented no certificate, so behind the frame's mTLS sidecar the activity list read as empty.
        _ssl_ctx = get_es_ssl_context()
        _connector = aiohttp.TCPConnector(ssl=_ssl_ctx) if _ssl_ctx else None
        async with aiohttp.ClientSession(connector=_connector) as session:
            # §DOCSFIX D6-317 (2026-10-16): the store answers oldest first unless asked otherwise (its replay
            # contract), so with `limit` alone a long history showed its first events, never its latest.
            async with session.get(url, headers=headers, params={"limit": limit, "sort_order": "desc"},
                                   timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    logger.warning(f"[AdminDevelopers] EventStore activity fetch returned {resp.status}")
                    return []
                body = await resp.json()
                if isinstance(body, list):
                    return body[:limit]
                if isinstance(body, dict) and "events" in body:
                    return body["events"][:limit]
                return []
    except Exception as e:
        logger.warning(f"[AdminDevelopers] EventStore activity fetch failed: {e}")
        return []
