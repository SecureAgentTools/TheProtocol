"""IRONKEY — agent authorization management API (Task 6).

Read/administer agent roles + spend policy. All endpoints are DEVELOPER-JWT
(owner/org-gated) or ADMIN. Δ-irrelevant (metadata only — never moves money). The
role→permission catalog is SERVED here so the FE never duplicates it (single source of
truth with the Python/Rego side). Enforcement itself lives in
``security.require_agent_permission`` gated by ``AGENT_RBAC_MODE``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import json
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry.security import get_current_developer, require_admin_flag, admin_credential
from agentvault_registry.agent_authz import (
    ROLE_PERMISSIONS, ALL_PERMISSIONS, BASE_PERMISSIONS, DEV_DELEGATABLE_PERMISSIONS,
    agent_rbac_mode, resolve_agent_permissions, resolve_agent_roles,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Roles a developer may assign (legacy-full is grandfather-only; not self-assignable).
ASSIGNABLE_ROLES = sorted(k for k in ROLE_PERMISSIONS if k != "legacy-full")

# Bare permissions an owner/admin may toggle from the UI. Deliberately a TINY allowlist —
# `authz.delegate` (the L4 meta-permission = "may issue capability tokens") is the only one.
# High-blast-radius bare perms (teg.system_transfer) are NEVER UI-grantable — that would
# re-open the exact over-permission IRONKEY closed.
UI_GRANTABLE_PERMISSIONS = {"authz.delegate"}


# ── schemas ────────────────────────────────────────────────────────────────
class SpendPolicyIn(BaseModel):
    max_per_tx: Optional[float] = None
    max_per_day: Optional[float] = None
    allowed_currencies: Optional[List[str]] = None
    counterparty_mode: str = "any"
    counterparty_allow: Optional[List[str]] = None
    require_approval_above: Optional[float] = None
    # B4 (RBAC plan) — richer axes (mig 0148):
    rate_per_hour: Optional[int] = Field(None, ge=1)    # spend attempts per rolling hour
    geo_allow: Optional[List[str]] = None               # registries where spends may EXECUTE


class RoleAdd(BaseModel):
    """§MEMBERSHIP (2026-10-02, agentvault2-0f's finding): grant ONE role and touch no other grant."""
    role: str = Field(..., min_length=1, max_length=40, description="A role name, e.g. governor")
    expires_at: Optional[str] = Field(default=None, description="ISO-8601 expiry for THIS grant only; omit = permanent")


class AuthzUpdate(BaseModel):
    roles: Optional[List[str]] = Field(default=None, description="Full replacement set of role names")
    roles_expires_at: Optional[str] = Field(
        default=None,
        description="B2 — ISO-8601 expiry applied to the roles set in THIS call (time-boxed grant). "
                    "Omit/null = permanent. Expired grants self-retire at resolution (no sweeper).",
    )
    spend_policy: Optional[SpendPolicyIn] = None
    delegate_enabled: Optional[bool] = Field(
        default=None,
        description="Grant/revoke the authz.delegate meta-permission (may issue L4 capability tokens)",
    )


class ClampIn(BaseModel):
    roles: List[str] = Field(default_factory=lambda: ["observer"])
    zero_cap: bool = True


# ── helpers ────────────────────────────────────────────────────────────────
async def _load_owned_agent(db: AsyncSession, did: str, dev: models.Developer) -> models.Agent:
    row = (await db.execute(text(
        "SELECT id, did, creator_developer_id, status FROM agents WHERE did = :did"
    ), {"did": did})).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if not (admin_credential(dev) or row.creator_developer_id == dev.id):   # §POCKETPAIR
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your agent")
    return row  # row-like; only .did/.status/.creator_developer_id used


async def _has_bare_perm(db: AsyncSession, did: str, perm: str) -> bool:
    r = (await db.execute(text(
        "SELECT 1 FROM agent_role_grants WHERE agent_did = :did AND grant_type = 'permission' "
        "AND value = :p AND (expires_at IS NULL OR expires_at > now())"
    ), {"did": did, "p": perm})).first()
    return r is not None


async def _set_delegate(db: AsyncSession, did: str, enabled: bool, dev_id: Optional[int]) -> None:
    if enabled:
        await db.execute(text(
            "INSERT INTO agent_role_grants (agent_did, grant_type, value, granted_by_dev_id) "
            "VALUES (:did, 'permission', 'authz.delegate', :dev) "
            "ON CONFLICT (agent_did, grant_type, value) DO NOTHING"
        ), {"did": did, "dev": dev_id})
    else:
        await db.execute(text(
            "DELETE FROM agent_role_grants WHERE agent_did = :did AND grant_type = 'permission' "
            "AND value = 'authz.delegate'"
        ), {"did": did})


async def _spend_policy(db: AsyncSession, did: str) -> Optional[Dict[str, Any]]:
    r = (await db.execute(text(
        "SELECT max_per_tx, max_per_day, allowed_currencies, counterparty_mode, "
        "counterparty_allow, require_approval_above, rate_per_hour, geo_allow "
        "FROM agent_spend_policies WHERE agent_did = :did"
    ), {"did": did})).first()
    if not r:
        return None
    return {
        "max_per_tx": float(r.max_per_tx) if r.max_per_tx is not None else None,
        "max_per_day": float(r.max_per_day) if r.max_per_day is not None else None,
        "allowed_currencies": r.allowed_currencies,
        "counterparty_mode": r.counterparty_mode,
        "counterparty_allow": r.counterparty_allow,
        "require_approval_above": float(r.require_approval_above) if r.require_approval_above is not None else None,
        "rate_per_hour": int(r.rate_per_hour) if r.rate_per_hour is not None else None,
        "geo_allow": r.geo_allow,
    }


async def _apply_roles(db: AsyncSession, did: str, roles: List[str], dev_id: Optional[int],
                       expires_at: Optional[str] = None) -> None:
    bad = [r for r in roles if r not in ROLE_PERMISSIONS]
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown roles: {bad}")
    # B2 — optional time-box for THIS role set. Column + resolver filter already
    # existed; this is the writer. Must parse AND be in the future.
    exp_dt = None
    if expires_at:
        import datetime as _dt
        try:
            exp_dt = _dt.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=_dt.timezone.utc)
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="roles_expires_at must be ISO-8601")
        if exp_dt <= _dt.datetime.now(_dt.timezone.utc):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="roles_expires_at must be in the future")
    # Full replacement of role grants (leaves bare-permission grants untouched).
    await db.execute(text(
        "DELETE FROM agent_role_grants WHERE agent_did = :did AND grant_type = 'role'"
    ), {"did": did})
    for r in roles:
        await db.execute(text(
            "INSERT INTO agent_role_grants (agent_did, grant_type, value, granted_by_dev_id, expires_at) "
            "VALUES (:did, 'role', :val, :dev, :exp) ON CONFLICT (agent_did, grant_type, value) DO NOTHING"
        ), {"did": did, "val": r, "dev": dev_id, "exp": exp_dt})


def _parse_expiry(expires_at: Optional[str], field: str):
    if not expires_at:
        return None
    import datetime as _dt
    try:
        exp_dt = _dt.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{field} must be ISO-8601")
    if exp_dt <= _dt.datetime.now(_dt.timezone.utc):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{field} must be in the future")
    return exp_dt


async def _apply_spend(db: AsyncSession, did: str, sp: SpendPolicyIn, dev_id: Optional[int]) -> None:
    if sp.counterparty_mode not in ("any", "same_registry", "allowlist"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="bad counterparty_mode")
    await db.execute(text("""
        INSERT INTO agent_spend_policies
            (agent_did, max_per_tx, max_per_day, allowed_currencies, counterparty_mode,
             counterparty_allow, require_approval_above, rate_per_hour, geo_allow,
             updated_by_dev_id, updated_at)
        VALUES (:did, :mtx, :mday, :cur, :cpm, :cpa, :appr, :rph, :geo, :dev, now())
        ON CONFLICT (agent_did) DO UPDATE SET
            max_per_tx = EXCLUDED.max_per_tx, max_per_day = EXCLUDED.max_per_day,
            allowed_currencies = EXCLUDED.allowed_currencies, counterparty_mode = EXCLUDED.counterparty_mode,
            counterparty_allow = EXCLUDED.counterparty_allow, require_approval_above = EXCLUDED.require_approval_above,
            rate_per_hour = EXCLUDED.rate_per_hour, geo_allow = EXCLUDED.geo_allow,
            updated_by_dev_id = EXCLUDED.updated_by_dev_id, updated_at = now()
    """), {"did": did, "mtx": sp.max_per_tx, "mday": sp.max_per_day, "cur": sp.allowed_currencies,
           "cpm": sp.counterparty_mode, "cpa": sp.counterparty_allow, "appr": sp.require_approval_above,
           "rph": sp.rate_per_hour, "geo": sp.geo_allow, "dev": dev_id})


# ── catalog (dev JWT) ────────────────────────────────────────────────────────
@router.get("/agents/authz/catalog", summary="IRONKEY role→permission catalog (served SSOT)")
async def authz_catalog(current: models.Developer = Depends(get_current_developer)):
    from agentvault_registry.services.org_authz import NEVER_IN_ORG_SLICES
    return {
        "mode": agent_rbac_mode(),
        "assignable_roles": ASSIGNABLE_ROLES,
        "all_permissions": sorted(ALL_PERMISSIONS),
        "base_permissions": sorted(BASE_PERMISSIONS),
        "grantable_permissions": sorted(UI_GRANTABLE_PERMISSIONS),
        "roles": {r: sorted(p) for r, p in ROLE_PERMISSIONS.items()},
        # SEC-11: what a delegation grant from each kind of principal may carry, from the sets POST
        # /agents/{did}/delegations and the resolver apply (D6-270), so a form offers only what the registry takes: a
        # developer what it may grant its agent directly, an organization all but the per-agent ones. An agent or service
        # principal (admin-only) is bounded when the grant is used, by what that principal holds then.
        "delegatable_permissions": {
            "dev": sorted(DEV_DELEGATABLE_PERMISSIONS),
            "org": sorted(ALL_PERMISSIONS - NEVER_IN_ORG_SLICES),
            "agent": sorted(ALL_PERMISSIONS),
            "service": sorted(ALL_PERMISSIONS),
        },
    }


# ── per-agent read/update (owner/admin) ──────────────────────────────────────
@router.get("/agents/{did}/authz", summary="Agent roles + spend policy + effective permissions")
async def get_agent_authz(
    did: str,
    current: models.Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await _load_owned_agent(db, did, current)
    # Track A2 provenance — live grants delegated TO this agent, per principal, so
    # the readout distinguishes OWN authority (roles → effective_permissions, always
    # on) from DELEGATED authority (bites only when the agent presents a matching
    # act-token). Additive field; the FE service returns raw data (no field-mapper).
    deleg_rows = (await db.execute(text(
        "SELECT id, principal_type, principal_ref, permissions, expires_at "
        "FROM agent_delegation_grants "
        "WHERE delegate_agent_did = :did AND revoked_at IS NULL "
        "AND (expires_at IS NULL OR expires_at > now()) ORDER BY principal_ref"
    ), {"did": did})).fetchall()
    return {
        "agent_did": did,
        "mode": agent_rbac_mode(),
        "roles": await resolve_agent_roles(db, did),
        "effective_permissions": sorted(await resolve_agent_permissions(db, did)),
        "spend_policy": await _spend_policy(db, did),
        "delegate_enabled": await _has_bare_perm(db, did, "authz.delegate"),
        # B2 — per-role grant detail incl. expiry, so the panel can show the time-box
        "role_grants": [
            {"role": r[0], "expires_at": r[1].isoformat() if r[1] else None}
            for r in (await db.execute(text(
                "SELECT value, expires_at FROM agent_role_grants "
                "WHERE agent_did = :did AND grant_type = 'role' "
                "AND (expires_at IS NULL OR expires_at > now()) ORDER BY value"
            ), {"did": did})).fetchall()
        ],
        "delegations": [
            {
                "grant_id": r[0],
                "principal_type": r[1],
                "principal_ref": r[2],
                "permissions": sorted(r[3] or []),
                "expires_at": r[4].isoformat() if r[4] else None,
            }
            for r in deleg_rows
        ],
    }


@router.post("/agents/{did}/authz/roles", summary="Grant ONE role, leaving every other grant as it is (owner/admin)")
async def add_agent_role(
    did: str,
    body: RoleAdd,
    current: models.Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """
    Grant one role to an agent and leave every other grant as it is (owner or admin). An absent or expired grant is
    written with `expires_at` (or none); an active grant is left exactly as it is (`changed: false`). Unlike PUT
    /api/v1/agents/{did}/authz, which replaces the whole role set with one expiry, no other grant is read or
    written.

    \f
    §MEMBERSHIP (2026-10-02). PUT /agents/{did}/authz REPLACES the whole role set and stamps every grant with the
    call's one expiry (its documented time-box), so adding a role through it to an agent holding a time-limited role
    would silently make that role permanent (agentvault2-0f's finding while wiring "Allow this agent to vote"). This
    grants one role: an absent or expired grant is written with `expires_at` (or none); an active grant is left exactly
    as it is (`changed: false`); no other grant is read or written.
    """
    await _load_owned_agent(db, did, current)
    if body.role not in ROLE_PERMISSIONS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown role: {body.role}")
    if body.role == "legacy-full" and not admin_credential(current):   # §POCKETPAIR
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="legacy-full is not self-assignable")
    exp_dt = _parse_expiry(body.expires_at, "expires_at")
    active = (await db.execute(text(
        "SELECT 1 FROM agent_role_grants WHERE agent_did = :did AND grant_type = 'role' AND value = :r "
        "AND (expires_at IS NULL OR expires_at > now())"), {"did": did, "r": body.role})).first()
    changed = active is None
    if changed:
        await db.execute(text(
            "INSERT INTO agent_role_grants (agent_did, grant_type, value, granted_by_dev_id, expires_at) "
            "VALUES (:did, 'role', :r, :dev, :exp) ON CONFLICT (agent_did, grant_type, value) "
            "DO UPDATE SET expires_at = EXCLUDED.expires_at, granted_by_dev_id = EXCLUDED.granted_by_dev_id"),
            {"did": did, "r": body.role, "dev": current.id, "exp": exp_dt})
        await db.commit()
        logger.info("[AGENT-RBAC] role added did=%s by dev=%s role=%s expires_at=%s", did, current.id, body.role,
                    exp_dt.isoformat() if exp_dt else None)
    return {"agent_did": did, "role": body.role, "changed": changed,
            "roles": await resolve_agent_roles(db, did),
            "effective_permissions": sorted(await resolve_agent_permissions(db, did))}


@router.put("/agents/{did}/authz", summary="Set agent roles and/or spend policy (owner/admin)")
async def put_agent_authz(
    did: str,
    body: AuthzUpdate,
    current: models.Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await _load_owned_agent(db, did, current)
    if body.roles is not None:
        # non-admins cannot self-assign the grandfather role
        if not admin_credential(current) and "legacy-full" in body.roles:   # §POCKETPAIR
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="legacy-full is not self-assignable")
        await _apply_roles(db, did, body.roles, current.id, expires_at=body.roles_expires_at)
    if body.spend_policy is not None:
        await _apply_spend(db, did, body.spend_policy, current.id)
    if body.delegate_enabled is not None:
        await _set_delegate(db, did, body.delegate_enabled, current.id)
    await db.commit()
    logger.info("[AGENT-RBAC] authz updated did=%s by dev=%s roles=%s delegate=%s",
                did, current.id, body.roles, body.delegate_enabled)
    return {
        "agent_did": did,
        "roles": await resolve_agent_roles(db, did),
        "effective_permissions": sorted(await resolve_agent_permissions(db, did)),
        "spend_policy": await _spend_policy(db, did),
        "delegate_enabled": await _has_bare_perm(db, did, "authz.delegate"),
        # B2 — mirror the GET readout so the panel shows the time-box right after save
        "role_grants": [
            {"role": r[0], "expires_at": r[1].isoformat() if r[1] else None}
            for r in (await db.execute(text(
                "SELECT value, expires_at FROM agent_role_grants "
                "WHERE agent_did = :did AND grant_type = 'role' "
                "AND (expires_at IS NULL OR expires_at > now()) ORDER BY value"
            ), {"did": did})).fetchall()
        ],
    }


@router.get("/agents/{did}/authz/denials", summary="Recent authz denials for an agent")
async def get_agent_denials(
    did: str,
    current: models.Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await _load_owned_agent(db, did, current)
    # B1 — the durable denial feed. Deny rows are written best-effort at the gates
    # (security.py: rbac_deny / spend_deny / org_ceiling_deny / delegation_caveat_deny /
    # capability_caveat_deny; delegation: capability_misuse) into
    # security_audit_logs with the ironkey. prefix.
    # §POCKETBRIDGE5 W-E (DOCSYNC defect 3): the filter had omitted the two
    # caveat-deny writers, so an agent refused by an att_ token's own caveats
    # never showed WHY in the owner-facing feed — the exact refusals L4 exists
    # to make legible.
    # §MISUSEDETAIL (2026-08-30) — the WHY was being thrown away one line before
    # it reached the screen. `security_audit_logs.details` is a **text** column
    # (information_schema: data_type = text), so the old
    #     "details": r[4] if isinstance(r[4], dict) else {}
    # could never be true and EVERY denial arrived as `{}`. Measured live before
    # the fix: 50 of 50 rows for one agent carried no details, while the table
    # held `revoked_reuse` x1429 and `holder_mismatch` x756 FOR THAT SAME AGENT.
    # The comment above this query says the point was to make refusals legible;
    # the field that says why was the one being dropped.
    #
    # Also returned now, because the row has always carried them and nothing ever
    # showed them: `severity` and `outcome` (a misuse row is warning/denied; a
    # breaker trip is critical/revoked), and the trip itself, which was missing
    # from the action filter entirely — the loudest thing that can happen to a
    # capability token did not appear in the agent's own denial feed.
    _ACTIONS = (
        "ironkey.rbac_deny", "ironkey.spend_deny", "ironkey.org_ceiling_deny",
        "ironkey.capability_misuse",
        "ironkey.delegation_caveat_deny", "ironkey.capability_caveat_deny",
        "ironkey.capability_circuit_breaker_trip",
    )
    rows = (await db.execute(text(
        "SELECT action, timestamp, target_type, target_id, details, severity, outcome "
        "FROM security_audit_logs "
        "WHERE actor_id = :did AND action = ANY(:acts) "
        "ORDER BY timestamp DESC LIMIT 50"
    ), {"did": did, "acts": list(_ACTIONS)})).fetchall()

    def _details(v):
        """text | dict | NULL -> dict, never an exception and never a lie."""
        if isinstance(v, dict):
            return v
        if isinstance(v, str) and v.strip():
            try:
                d = json.loads(v)
                return d if isinstance(d, dict) else {"value": d}
            except (ValueError, TypeError):
                return {"raw": v[:200]}
        return {}

    # A feed of 50 rows all saying the same thing is not legible either: this
    # agent's own history is 8,904 revoked_reuse denials fleet-wide. The summary
    # counts REASONS over a 30-day window so the shape is visible above the list.
    summary = [
        {"reason": r[0] or "unknown", "count": int(r[1])}
        for r in (await db.execute(text(
            "SELECT COALESCE(details::jsonb->>'reason', 'unknown') AS reason, count(*) "
            "FROM security_audit_logs "
            "WHERE actor_id = :did AND action = ANY(:acts) "
            "  AND timestamp > now() - interval '30 days' "
            "  AND details IS NOT NULL AND details <> '' "
            "GROUP BY 1 ORDER BY 2 DESC LIMIT 8"
        ), {"did": did, "acts": list(_ACTIONS)})).fetchall()
    ]
    return {
        "agent_did": did,
        "mode": agent_rbac_mode(),
        "summary_window_days": 30,
        "summary": summary,
        "denials": [
            {
                "action": r[0].replace("ironkey.", "", 1),
                "timestamp": r[1].isoformat() if r[1] else None,
                "target_type": r[2],
                "target": r[3],
                "details": _details(r[4]),
                "severity": r[5],
                "outcome": r[6],
            }
            for r in rows
        ],
    }


# ── admin: fleet report + clamp ──────────────────────────────────────────────
@router.get("/admin/agents/authz/report", summary="Fleet authz report (admin)")
async def admin_authz_report(
    current: models.Developer = Depends(require_admin_flag("admin_platform")),
    db: AsyncSession = Depends(get_db),
):
    legacy_full = (await db.execute(text(
        "SELECT count(*) FROM agent_role_grants WHERE grant_type='role' AND value='legacy-full'"
    ))).scalar() or 0
    capped = (await db.execute(text(
        "SELECT count(*) FROM agent_spend_policies WHERE max_per_tx IS NOT NULL OR max_per_day IS NOT NULL"
    ))).scalar() or 0
    census_rows = (await db.execute(text(
        "SELECT value, count(*) AS n FROM agent_role_grants WHERE grant_type='role' "
        "GROUP BY value ORDER BY n DESC"
    ))).fetchall()
    return {
        "mode": agent_rbac_mode(),
        "legacy_full_agents": int(legacy_full),
        "capped_agents": int(capped),
        "role_census": {r.value: int(r.n) for r in census_rows},
    }


@router.post("/admin/agents/{did}/authz/clamp", summary="Clamp an agent's authority (admin)")
async def admin_clamp_agent(
    did: str,
    body: ClampIn,
    current: models.Developer = Depends(require_admin_flag("admin_enforcement")),
    db: AsyncSession = Depends(get_db),
):
    exists = (await db.execute(text("SELECT 1 FROM agents WHERE did = :did"), {"did": did})).first()
    if not exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent not found")
    await _apply_roles(db, did, body.roles, current.id)
    if body.zero_cap:
        await _apply_spend(db, did, SpendPolicyIn(max_per_tx=0, max_per_day=0), current.id)
    await db.commit()
    logger.warning("[AGENT-RBAC] CLAMP did=%s by admin=%s roles=%s zero_cap=%s",
                   did, current.id, body.roles, body.zero_cap)
    return {
        "agent_did": did,
        "roles": await resolve_agent_roles(db, did),
        "spend_policy": await _spend_policy(db, did),
    }


# ═══════════════════════ B3 — the spend step-up approval queue ═══════════════════════
# A spend over the agent's `require_approval_above` threshold now PARKS as a pending row
# (services/spend_approvals.py) instead of dead-ending. These rails are the human half:
# the owning developer lists the queue and approves/denies; the agent's retry consumes an
# approval exactly once at the spend gate. Paths live under /agents/authz/* so no
# /agents/{did} route registered elsewhere can swallow them (FastAPI registration order
# beats specificity — the §NOTIFV2 lesson).

@router.get("/agents/authz/spend-approvals", summary="My agents' spend approval queue (B3)")
async def list_spend_approvals(
    status_filter: Optional[str] = None,
    current: models.Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    from agentvault_registry.services.spend_approvals import list_for_dev
    if status_filter is not None and status_filter not in (
            "pending", "approved", "denied", "expired", "consumed"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown status filter")
    return {"approvals": await list_for_dev(db, current.id, status=status_filter)}


@router.post("/agents/authz/spend-approvals/{approval_id}/approve",
             summary="Approve ONE parked spend (owner; usable once, 15-minute fuse)")
async def approve_spend_approval(
    approval_id: str,
    current: models.Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    from agentvault_registry.services.spend_approvals import resolve
    out = await resolve(db, current, approval_id, "approved")
    logger.info("[B3-STEPUP] approval %s APPROVED by dev=%s", approval_id, current.id)
    return out


@router.post("/agents/authz/spend-approvals/{approval_id}/deny",
             summary="Deny ONE parked spend (owner)")
async def deny_spend_approval(
    approval_id: str,
    current: models.Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    from agentvault_registry.services.spend_approvals import resolve
    out = await resolve(db, current, approval_id, "denied")
    logger.info("[B3-STEPUP] approval %s DENIED by dev=%s", approval_id, current.id)
    return out
