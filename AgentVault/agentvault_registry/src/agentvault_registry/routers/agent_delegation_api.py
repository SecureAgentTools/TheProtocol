"""IRONKEY L3/L4 — delegation grants + attenuable capability tokens API.

- **Delegation grants** (developer JWT, principal-controller-gated): a dev/org/agent
  principal delegates a permission subset to an agent, effective only when that agent's
  token carries a matching ``act.sub``.
- **Capability tokens** (agent JWT): an agent holding ``authz.delegate`` issues an ``att_``
  token to a sub-agent, strictly weaker than itself; the holder may attenuate again down a
  bounded chain; revoke cascades to the subtree; a ``consume`` step debits the delegated
  budget. Every real transfer still clears the escrow rails — Δ-irrelevant.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging
import os
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Security, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry.security import (
    admin_credential,
    get_current_developer, get_current_agent, require_admin_flag, require_agent_permission,
    create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES, agent_token_claims,
)
from agentvault_registry.agent_authz import (
    ALL_PERMISSIONS, DEV_DELEGATABLE_PERMISSIONS, agent_delegation_mode, agent_rbac_mode, resolve_agent_permissions,
)
from agentvault_registry import agent_delegation as capmod
from agentvault_registry.core.federation_auth import get_federation_identity, require_peer_registry_identity
# §auditfix (2026-07-19): every authority-changing operation on this surface writes a
# security_audit_logs row (SIEM prefix `ironkey.`) AND an EventStore event. The writer
# COMMITS the session — each call sits immediately before the endpoint's own commit so
# the mutation and its audit row land in ONE transaction. Security-critical records
# (revocations, breaker) use the AWAITED emitter; routine ones keep emit_background.
from agentvault_registry.services.admin_audit import log_ironkey_action
from agentvault_registry.core.public_url import credential_home_url  # §FEFRAME W1

logger = logging.getLogger(__name__)
router = APIRouter()


def _notify_delegate_owner(event: str, data: Dict[str, Any], delegate_did: str) -> None:
    """§TWOAGENT G3 (2026-09-23): tell the DELEGATE's owner that its agent gained or lost delegated authority.
    Owner-scoped (never broadcast), scheduled after the caller's commit, and never able to fail the grant or the
    revoke it reports: like every webhook, it is best-effort."""
    try:
        import asyncio
        from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
        asyncio.create_task(dispatch_webhook_for_agents(event, data, [delegate_did], source_label="ironkey.delegation"))
    except Exception as e:  # noqa: BLE001
        logger.debug("[IRONKEY] %s notice skipped for %s: %s", event, delegate_did, e)


async def _caller_peer(db: AsyncSession, peer_spiffe_id: Optional[str]) -> Optional[str]:
    """The peer NAME a federation caller's identity resolves to, or None. Never taken from the request body."""
    from agentvault_registry.services.contract_xframe import resolve_peer_name
    for cand in (peer_spiffe_id, (peer_spiffe_id or "").rstrip("/")):
        name = await resolve_peer_name(db, cand)
        if name:
            return name
    return None


# ── schemas ──────────────────────────────────────────────────────────────────
class DelegationIn(BaseModel):
    principal_type: str = Field(..., pattern="^(dev|org|agent|service)$")
    principal_ref: str
    permissions: List[str]
    may_redelegate: bool = False
    max_depth: int = 1
    ttl_hours: Optional[int] = None


class CaveatsIn(BaseModel):
    permissions: List[str]
    max_per_tx: Optional[float] = None
    allowed_currencies: Optional[List[str]] = None
    counterparty_allow: Optional[List[str]] = None
    resources_listings: Optional[List[str]] = None
    operations: Optional[List[str]] = None
    # B4 (RBAC plan) — richer money caveats:
    rate_per_hour: Optional[int] = Field(None, ge=1)    # spend attempts per rolling hour
    geo_allow: Optional[List[str]] = None               # registry names where spends may EXECUTE
    # B6 — per-TOOL scoping: MCP tool names (bare, e.g. "getMyBalance") this token may
    # invoke; enforced at MCP dispatch before any REST call. Absent = all tools.
    tools: Optional[List[str]] = None
    no_redelegate: bool = False
    # PHONE FABRIC caveats (2026-07-07) — carried on a phone.use capability token.
    phone_allowed_apps: Optional[List[str]] = None      # package allowlist (absent or empty = not limited to a list)
    phone_allowed_domains: Optional[List[str]] = None   # network egress allowlist (absent or empty = no host list)
    phone_max_actions: Optional[int] = None             # hard action ceiling for the session
    phone_ttl_seconds: Optional[int] = None             # session wall-clock cap (absent = registry default; 0 or less = no session)
    phone_no_screenshot: Optional[bool] = None          # privacy: tree-only, never pixels
    phone_no_network: Optional[bool] = None             # airplane-mode instance


class IssueIn(BaseModel):
    holder_agent_did: Optional[str] = None
    caveats: CaveatsIn
    budget_total: Optional[float] = None
    currency: Optional[str] = None
    max_uses: Optional[int] = None
    ttl_seconds: int = Field(capmod.DEFAULT_TTL_SECONDS, ge=60, le=capmod.MAX_TTL_SECONDS)


class AttenuateIn(BaseModel):
    caveats: CaveatsIn
    budget_total: Optional[float] = None
    max_uses: Optional[int] = None
    ttl_seconds: int = Field(capmod.DEFAULT_TTL_SECONDS, ge=60, le=capmod.MAX_TTL_SECONDS)


class ConsumeIn(BaseModel):
    token: str
    amount: float = Field(..., ge=0)
    currency: Optional[str] = None


def _caveats_dict(c: CaveatsIn) -> dict:
    d: Dict[str, Any] = {"permissions": [p for p in c.permissions if p in ALL_PERMISSIONS]}
    if c.max_per_tx is not None:
        d["max_per_tx"] = str(c.max_per_tx)
    for k, v in (("allowed_currencies", c.allowed_currencies),
                 ("counterparty_allow", c.counterparty_allow),
                 ("resources_listings", c.resources_listings),
                 ("operations", c.operations),
                 ("geo_allow", c.geo_allow),
                 ("tools", c.tools),
                 ("phone_allowed_apps", c.phone_allowed_apps),
                 ("phone_allowed_domains", c.phone_allowed_domains)):
        if v:
            d[k] = v
    for k, v in (("rate_per_hour", c.rate_per_hour),
                 ("phone_max_actions", c.phone_max_actions),
                 ("phone_ttl_seconds", c.phone_ttl_seconds)):
        if v is not None:
            d[k] = v
    if c.phone_no_screenshot:
        d["phone_no_screenshot"] = True
    if c.phone_no_network:
        d["phone_no_network"] = True
    if c.no_redelegate:
        d["no_redelegate"] = True
    return d


# ════════════════════════════ L3 — delegation grants ════════════════════════
@router.post("/agents/{did}/delegations", summary="Delegate a permission subset TO an agent (L3)")
async def create_delegation(
    did: str,
    body: DelegationIn,
    current: models.Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    agent = (await db.execute(text(
        "SELECT did, organization_id, creator_developer_id FROM agents WHERE did = :d"), {"d": did})).first()
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Delegate agent not found")
    bad = [p for p in body.permissions if p not in ALL_PERMISSIONS]
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown permissions: {bad}")
    # Canonicalize principal_ref to the full "type:ref" form (matches the token's act.sub),
    # stripping a redundant leading "type:" the caller may have typed → no "dev:dev:2".
    raw = body.principal_ref.strip()
    bare = raw.split(":", 1)[1] if raw.startswith(body.principal_type + ":") else raw
    principal_full = f"{body.principal_type}:{bare}"
    # D6-270: who may act for whom. A principal hands out only what it may give, whoever writes the grant (an admin
    # included: the resolver applies the same rule to every row, so a grant beyond it would convey nothing anyway).
    if body.principal_type == "dev":
        if not bare.isdigit():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A dev principal is dev:<developer id>")
        if getattr(agent, "creator_developer_id", None) != int(bare):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                detail="A developer delegates only to an agent that developer created")
        beyond = sorted(set(body.permissions) - DEV_DELEGATABLE_PERMISSIONS)
        if beyond:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                detail=f"A developer cannot delegate {beyond}: only what it may grant its agent directly")
    elif body.principal_type == "org":
        from agentvault_registry.services.org_authz import NEVER_IN_ORG_SLICES
        beyond = sorted(set(body.permissions) & NEVER_IN_ORG_SLICES)
        if beyond:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                detail=f"An organization never delegates {beyond}: they stay per-agent grants")
    is_admin = admin_credential(current)   # §POCKETPAIR: a scoped key is not admin
    # Principal-controller gate: only the principal's controller may delegate its authority.
    if not is_admin:
        if body.principal_type == "dev":
            if principal_full != f"dev:{current.id}":
                raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Can only delegate your own dev authority")
        elif body.principal_type == "org":
            slug = bare
            ok = (await db.execute(text(
                "SELECT 1 FROM organization_members m JOIN organizations o ON m.organization_id=o.id "
                "WHERE m.developer_id=:dev AND (o.slug=:slug OR CAST(o.id AS TEXT)=:slug) "
                "AND m.role IN ('owner','admin') LIMIT 1"
            ), {"dev": current.id, "slug": slug})).first()
            if not ok:
                raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not an admin of that org")
        else:  # agent / service principals — admin-only for v1
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="agent/service delegation is admin-only in v1")
    exp = None
    if body.ttl_hours:
        exp = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=body.ttl_hours)
    await db.execute(text("""
        INSERT INTO agent_delegation_grants
            (principal_type, principal_ref, delegate_agent_did, permissions, may_redelegate,
             max_depth, granted_by_dev_id, expires_at)
        VALUES (:pt, :pr, :did, :perms, :mr, :md, :dev, :exp)
        ON CONFLICT (principal_type, principal_ref, delegate_agent_did) DO UPDATE SET
            permissions = EXCLUDED.permissions, may_redelegate = EXCLUDED.may_redelegate,
            max_depth = EXCLUDED.max_depth, expires_at = EXCLUDED.expires_at,
            revoked_at = NULL, revoke_reason = NULL
    """), {"pt": body.principal_type, "pr": principal_full, "did": did,
           "perms": body.permissions, "mr": body.may_redelegate, "md": body.max_depth,
           "dev": current.id, "exp": exp})
    await log_ironkey_action(  # commits — grant + audit row in one transaction
        db, action="delegation_grant", actor_type="developer", actor_id=str(current.id),
        target_type="agent", target_id=did,
        details={"principal": principal_full, "permissions": body.permissions,
                 "may_redelegate": body.may_redelegate,
                 "expires_at": exp.isoformat() if exp else None})
    await db.commit()
    logger.info("[IRONKEY-L3] delegation %s -> %s perms=%s by dev=%s",
                principal_full, did, body.permissions, current.id)
    # POCKET FRAME: audit event (non-financial, Δ-irrelevant; registry emitter is
    # fail-open for unknown types per f037 — rule-11 checked 2026-07-07). Feeds the
    # push_notify reactors so the owner's phone sees delegation activity.
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        get_event_emitter().emit_background(
            event_type="AgentDelegationGranted",
            aggregate_id=did,
            data={
                "delegate_agent_did": did,
                "principal": principal_full,
                "permissions": body.permissions,
                "granted_by_dev_id": current.id,
                "expires_at": exp.isoformat() if exp else None,
            },
        )
    except Exception:  # noqa: BLE001 — notification plumbing must never block the grant
        logger.debug("[IRONKEY-L3] AgentDelegationGranted emit skipped", exc_info=True)
    _notify_delegate_owner("delegation.received", {
        "scope": "local", "delegate_did": did, "principal": principal_full, "permissions": list(body.permissions),
        "expires_at": exp.isoformat() if exp else None, "granted_by_dev_id": current.id,
        "use_with": f"POST /api/v1/agents/act-token with act_as={principal_full}, then present that token"}, did)
    return {"ok": True, "delegate_agent_did": did, "principal": principal_full,
            "permissions": body.permissions, "mode": agent_delegation_mode()}


@router.get("/agents/{did}/delegations", summary="List delegation grants held by an agent")
async def list_delegations(
    did: str,
    current: models.Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    # §TWOAGENT (2026-09-23): the agent's OWNER or an admin, like its sibling /agents/{did}/capabilities. Any developer
    # used to read any agent's grants: who delegated what to it, and until when.
    await _owned_agent_did(db, did, current)
    rows = (await db.execute(text(
        "SELECT id, principal_type, principal_ref, permissions, may_redelegate, max_depth, "
        "expires_at, revoked_at FROM agent_delegation_grants WHERE delegate_agent_did = :d "
        "ORDER BY created_at DESC"
    ), {"d": did})).fetchall()
    return {"agent_did": did, "grants": [
        {"id": r.id, "principal": r.principal_ref if ":" in r.principal_ref else f"{r.principal_type}:{r.principal_ref}", "permissions": r.permissions,
         "may_redelegate": r.may_redelegate, "max_depth": r.max_depth,
         "expires_at": r.expires_at.isoformat() if r.expires_at else None,
         "revoked": r.revoked_at is not None} for r in rows]}


@router.delete("/delegations/{grant_id}", summary="Revoke a delegation grant")
async def revoke_delegation(
    grant_id: int,
    current: models.Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(text(
        "SELECT granted_by_dev_id, delegate_agent_did, principal_ref, revoked_at "
        "FROM agent_delegation_grants WHERE id = :i"), {"i": grant_id})).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Grant not found")
    if not (admin_credential(current) or row.granted_by_dev_id == current.id):   # §POCKETPAIR
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your grant")
    await db.execute(text(
        "UPDATE agent_delegation_grants SET revoked_at = now(), revoke_reason = 'manual' WHERE id = :i"
    ), {"i": grant_id})
    await log_ironkey_action(  # commits — revocation + audit row in one transaction
        db, action="delegation_revoke", actor_type="developer", actor_id=str(current.id),
        target_type="agent", target_id=row.delegate_agent_did,
        details={"grant_id": grant_id, "principal": row.principal_ref, "reason": "manual"})
    await db.commit()
    # Revocation is a security action — AWAITED emit (as durable as the revoke itself).
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        await get_event_emitter().emit(
            event_type="AgentDelegationRevoked",
            aggregate_id=row.delegate_agent_did,
            data={"grant_id": grant_id, "delegate_agent_did": row.delegate_agent_did,
                  "principal": row.principal_ref, "revoked_by_dev_id": current.id,
                  "reason": "manual"},
            idempotency_key=f"deleg-revoked-{grant_id}",
        )
    except Exception:  # noqa: BLE001 — the revocation itself already stands
        logger.warning("[IRONKEY-L3] AgentDelegationRevoked emit failed grant=%s", grant_id)
    if row.revoked_at is None:   # a repeat revoke tells nobody twice
        _notify_delegate_owner("delegation.revoked", {
            "scope": "local", "delegate_did": row.delegate_agent_did, "principal": row.principal_ref,
            "grant_id": grant_id, "reason": "manual"}, row.delegate_agent_did)
    return {"ok": True, "revoked_grant_id": grant_id}


# ═══════════════════════ L4 — attenuable capability tokens ═══════════════════
async def _issue_root_token(db: AsyncSession, issuer_did: str, body: IssueIn,
                            issued_via: str = "agent") -> Dict[str, Any]:
    """The ONE root-issue path — shared by the agent route and the owner wrapper so the
    subset check, insert, audit row and event can never drift between the two."""
    cav = _caveats_dict(body.caveats)
    # permissions ⊆ issuer's CURRENT effective authority (you cannot delegate what you lack).
    iss_eff = await resolve_agent_permissions(db, issuer_did)
    over = set(cav["permissions"]) - iss_eff
    if over:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Cannot delegate permissions you lack: {sorted(over)}")
    plain = capmod.generate_token()
    exp = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=body.ttl_seconds)
    row = (await db.execute(text("""
        INSERT INTO agent_capability_tokens
            (token_hash, token_prefix, issuer_agent_did, holder_agent_did, parent_token_id,
             depth, caveats, budget_total, budget_spent, currency, max_uses, uses, status, expires_at)
        VALUES (:h, :pfx, :iss, :hold, NULL, 0, CAST(:cav AS JSONB), :bt, 0, :cur, :mu, 0, 'issued', :exp)
        RETURNING id
    """), {"h": capmod.hash_token(plain), "pfx": plain[:12], "iss": issuer_did,
           "hold": body.holder_agent_did, "cav": __import__("json").dumps(cav),
           "bt": body.budget_total, "cur": body.currency, "mu": body.max_uses, "exp": exp})).first()
    await log_ironkey_action(  # commits — token + audit row in one transaction
        db, action="capability_issue", actor_type="agent", actor_id=issuer_did,
        target_type="capability_token", target_id=str(row.id),
        details={"holder_did": body.holder_agent_did, "permissions": cav["permissions"],
                 "budget_total": body.budget_total, "currency": body.currency,
                 "expires_at": exp.isoformat(), "via": issued_via})
    await db.commit()
    logger.info("[IRONKEY-L4] issued cap id=%s issuer=%s holder=%s perms=%s budget=%s",
                row.id, issuer_did, body.holder_agent_did, cav["permissions"], body.budget_total)
    # POCKET FRAME: audit event → push reactors (non-financial, Δ-irrelevant, f037 fail-open).
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        get_event_emitter().emit_background(
            event_type="AgentCapabilityIssued",
            aggregate_id=body.holder_agent_did,
            data={
                "token_id": row.id,
                "issuer_did": issuer_did,
                "holder_did": body.holder_agent_did,
                "permissions": cav["permissions"],
                "budget_total": body.budget_total,
                "currency": body.currency,
                "expires_at": exp.isoformat(),
            },
            idempotency_key=f"cap-issued-{row.id}",
        )
    except Exception:  # noqa: BLE001
        logger.debug("[IRONKEY-L4] AgentCapabilityIssued emit skipped", exc_info=True)
    return {"id": row.id, "token": plain, "issuer_did": issuer_did, "depth": 0,
            "caveats": cav, "expires_at": exp.isoformat(),
            "note": "token shown once — store it now"}


@router.post("/agents/capabilities", summary="Issue an att_ capability token to a sub-agent (L4)")
async def issue_capability(
    body: IssueIn,
    issuer: models.Agent = Depends(require_agent_permission("authz.delegate")),
    db: AsyncSession = Depends(get_db),
):
    return await _issue_root_token(db, issuer.did, body)


@router.post("/agents/{did}/capabilities/issue-as-owner",
             summary="Issue a root att_ token FOR one of your agents (owner, L4)")
async def issue_capability_as_owner(
    did: str,
    body: IssueIn,
    developer: models.Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Owner convenience over the SAME rail: the panel can issue a root token without
    pasting the agent's client secret around. Manufactures NO authority: the issuing
    agent must itself hold ``authz.delegate`` (identical gate + B1 deny row as the
    agent-JWT route) and :func:`_issue_root_token`'s caveat-subset check still binds.
    Strictly owner-or-platform-admin; org-acting contexts deliberately do NOT qualify.
    """
    row = (await db.execute(text(
        "SELECT creator_developer_id, status FROM agents WHERE did = :d"), {"d": did})).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if row[0] != developer.id and not admin_credential(developer):   # §POCKETPAIR
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your agent")
    if str(row[1] or "").lower() != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f"Agent is {row[1]}, not active")
    # Parity with require_agent_permission("authz.delegate") on the agent route.
    mode = agent_rbac_mode()
    if mode == "enforce":
        perms = await resolve_agent_permissions(db, did)
        if "authz.delegate" not in perms:
            try:  # B1 — the denial feed must see this path too (best-effort)
                await log_ironkey_action(
                    db, action="rbac_deny", actor_type="agent", actor_id=did,
                    target_type="permission", target_id="authz.delegate",
                    outcome="deny", severity="warning",
                    details={"mode": mode, "via": f"owner_dev:{developer.id}",
                             "held": sorted(perms)[:40]},
                )
            except Exception:  # noqa: BLE001
                pass
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                detail="Agent lacks required permission: authz.delegate")
    return await _issue_root_token(db, did, body, issued_via=f"owner_dev:{developer.id}")


@router.post("/agents/capabilities/{token_id}/attenuate", summary="Derive a strictly-weaker child token (L4)")
async def attenuate_capability(
    token_id: int,
    body: AttenuateIn,
    # Attenuation authority rides the TOKEN, not the holder's own role: anyone holding a
    # capability may weaken it further (unless the parent set no_redelegate). The child can
    # never exceed the parent, so re-delegation cannot escalate — the meta-permission is
    # only needed to MINT root authority from your own role (issue), not to attenuate.
    holder: models.Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    parent = (await db.execute(text(
        "SELECT id, issuer_agent_did, holder_agent_did, status, caveats, budget_total, "
        "budget_spent, currency, depth, expires_at, max_uses, uses FROM agent_capability_tokens WHERE id = :i"
    ), {"i": token_id})).first()
    if not parent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Parent token not found")
    if parent.holder_agent_did and parent.holder_agent_did != holder.did and parent.issuer_agent_did != holder.did:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You do not hold this token")
    if parent.status not in ("issued", "active"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Parent is {parent.status}")
    if (parent.caveats or {}).get("no_redelegate"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Parent forbids re-delegation")
    if parent.depth + 1 > capmod.MAX_CHAIN_DEPTH:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Max chain depth {capmod.MAX_CHAIN_DEPTH} reached")
    child_cav = _caveats_dict(body.caveats)
    ok, why = capmod.caveats_subset_ok(child_cav, parent.caveats or {})
    if ok:   # D6-522: and the uses bound, a column of the token rather than a caveat
        ok, why = capmod.uses_subset_ok(body.max_uses, parent.max_uses, parent.uses)
    child_bt = None
    if ok:   # SEC-09: and the budget, another column: a child naming none takes what its parent has left
        ok, why, child_bt = capmod.child_budget_within_parent(body.budget_total, parent.budget_total,
                                                              parent.budget_spent)
    if not ok:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Child not ≤ parent: {why}")
    child_bt_out = float(child_bt) if child_bt is not None else None   # the audit row, the ledger event, the answer
    # child expiry ≤ parent expiry
    exp = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=body.ttl_seconds)
    if parent.expires_at and exp > parent.expires_at:
        exp = parent.expires_at
    plain = capmod.generate_token()
    row = (await db.execute(text("""
        INSERT INTO agent_capability_tokens
            (token_hash, token_prefix, issuer_agent_did, holder_agent_did, parent_token_id,
             depth, caveats, budget_total, budget_spent, currency, max_uses, uses, status, expires_at)
        VALUES (:h, :pfx, :iss, NULL, :parent, :depth, CAST(:cav AS JSONB), :bt, 0, :cur, :mu, 0, 'issued', :exp)
        RETURNING id
    """), {"h": capmod.hash_token(plain), "pfx": plain[:12], "iss": holder.did, "parent": parent.id,
           "depth": parent.depth + 1, "cav": __import__("json").dumps(child_cav),
           "bt": child_bt, "cur": parent.currency, "mu": body.max_uses, "exp": exp})).first()
    await log_ironkey_action(  # commits — child token + audit row in one transaction
        db, action="capability_attenuate", actor_type="agent", actor_id=holder.did,
        target_type="capability_token", target_id=str(row.id),
        details={"parent_token_id": parent.id, "depth": parent.depth + 1,
                 "permissions": child_cav["permissions"], "budget_total": child_bt_out,
                 "expires_at": exp.isoformat()})
    await db.commit()
    logger.info("[IRONKEY-L4] attenuated parent=%s -> child=%s depth=%s by=%s",
                parent.id, row.id, parent.depth + 1, holder.did)
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        get_event_emitter().emit_background(
            event_type="AgentCapabilityAttenuated",
            aggregate_id=holder.did,
            data={"parent_token_id": parent.id, "child_token_id": row.id,
                  "issuer_did": holder.did, "depth": parent.depth + 1,
                  "permissions": child_cav["permissions"],
                  "budget_total": child_bt_out, "currency": parent.currency,
                  "expires_at": exp.isoformat()},
            idempotency_key=f"cap-attenuated-{row.id}",
        )
    except Exception:  # noqa: BLE001
        logger.debug("[IRONKEY-L4] AgentCapabilityAttenuated emit skipped", exc_info=True)
    return {"id": row.id, "token": plain, "parent_token_id": parent.id, "depth": parent.depth + 1,
            "caveats": child_cav, "budget_total": child_bt_out, "currency": parent.currency,
            "max_uses": body.max_uses, "expires_at": exp.isoformat()}


@router.post("/agents/capabilities/consume", summary="Debit a capability token's delegated budget (L4)")
async def consume_capability(
    body: ConsumeIn,
    holder: models.Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    cap, reason = await capmod.resolve_capability(db, body.token, holder.did)
    if cap is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f"Capability rejected: {reason}")
    amt = Decimal(str(body.amount))
    if cap["budget_remaining"] is not None and amt > cap["budget_remaining"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Amount {amt} exceeds remaining budget {cap['budget_remaining']}")
    if cap["currency"] and body.currency and cap["currency"] != body.currency:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Currency not permitted by caveat")
    # Atomic debit + use-count; flip to exhausted when budget/uses run out.
    await db.execute(text(
        "UPDATE agent_capability_tokens SET budget_spent = budget_spent + :a, uses = uses + 1, "
        "status = 'active' WHERE id = :i"
    ), {"a": amt, "i": cap["id"]})
    await db.execute(text(
        "UPDATE agent_capability_tokens SET status = 'exhausted' WHERE id = :i "
        "AND ((budget_total IS NOT NULL AND budget_spent >= budget_total) "
        "     OR (max_uses IS NOT NULL AND uses >= max_uses))"
    ), {"i": cap["id"]})
    st = (await db.execute(text(
        "SELECT budget_total, budget_spent, uses, status FROM agent_capability_tokens WHERE id = :i"
    ), {"i": cap["id"]})).first()
    remaining = None
    if st.budget_total is not None:
        remaining = float(Decimal(str(st.budget_total)) - Decimal(str(st.budget_spent)))
    await log_ironkey_action(  # commits — debit + audit row in one transaction
        db, action="capability_consume", actor_type="agent", actor_id=holder.did,
        target_type="capability_token", target_id=str(cap["id"]),
        details={"issuer_did": cap["issuer_did"], "amount": str(amt),
                 "currency": body.currency or cap["currency"], "uses": st.uses,
                 "status": st.status, "budget_remaining": remaining})
    await db.commit()
    # The USE of delegated authority — the most audit-worthy moment of a token's life.
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        get_event_emitter().emit_background(
            event_type="AgentCapabilityConsumed",
            aggregate_id=holder.did,
            data={"token_id": cap["id"], "issuer_did": cap["issuer_did"],
                  "holder_did": holder.did, "amount": float(amt),
                  "currency": body.currency or cap["currency"], "uses": st.uses,
                  "status": st.status, "budget_remaining": remaining,
                  "permissions": sorted(cap["permissions"])},
            idempotency_key=f"cap-consumed-{cap['id']}-{st.uses}",
        )
    except Exception:  # noqa: BLE001
        logger.debug("[IRONKEY-L4] AgentCapabilityConsumed emit skipped", exc_info=True)
    return {"ok": True, "token_id": cap["id"], "debited": float(amt),
            "budget_remaining": remaining, "uses": st.uses, "status": st.status,
            "effective_permissions": sorted(cap["permissions"])}


@router.delete("/agents/capabilities/{token_id}", summary="Revoke a capability token + its whole subtree (L4)")
async def revoke_capability(
    token_id: int,
    holder: models.Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(text(
        "SELECT issuer_agent_did, holder_agent_did FROM agent_capability_tokens WHERE id = :i"
    ), {"i": token_id})).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Token not found")
    if holder.did not in (row.issuer_agent_did, row.holder_agent_did):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the issuer or holder may revoke")
    n = await capmod.revoke_subtree(db, token_id, f"manual:{holder.did}")
    await log_ironkey_action(  # commits — cascade + audit row in one transaction
        db, action="capability_revoke", actor_type="agent", actor_id=holder.did,
        target_type="capability_token", target_id=str(token_id),
        details={"issuer_did": row.issuer_agent_did, "holder_did": row.holder_agent_did,
                 "revoked_count": n, "via": "self"})
    await db.commit()
    logger.warning("[IRONKEY-L4] revoke cascade token=%s by=%s revoked=%s", token_id, holder.did, n)
    # POCKET FRAME: audit event → push reactors (high priority — this is the panic path).
    # §auditfix: AWAITED — a revocation's ledger record must be as durable as the cut.
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        await get_event_emitter().emit(
            event_type="AgentCapabilityRevoked",
            aggregate_id=row.holder_agent_did or row.issuer_agent_did,
            data={
                "token_id": token_id,
                "issuer_did": row.issuer_agent_did,
                "holder_did": row.holder_agent_did,
                "revoked_by": holder.did,
                "revoked_count": n,
                "via": "self",
            },
            idempotency_key=f"cap-revoked-{token_id}",
        )
    except Exception:  # noqa: BLE001 — the revocation itself already stands
        logger.warning("[IRONKEY-L4] AgentCapabilityRevoked emit failed token=%s", token_id)
    return {"ok": True, "root_token_id": token_id, "revoked_count": n}


@router.get("/agents/capabilities/mine", summary="Capability tokens I issued or hold")
async def my_capabilities(
    agent: models.Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(text(
        "SELECT id, issuer_agent_did, holder_agent_did, parent_token_id, depth, caveats, "
        "budget_total, budget_spent, currency, status, expires_at FROM agent_capability_tokens "
        "WHERE issuer_agent_did = :d OR holder_agent_did = :d ORDER BY created_at DESC LIMIT 200"
    ), {"d": agent.did})).fetchall()
    def _rem(r):
        return float(Decimal(str(r.budget_total)) - Decimal(str(r.budget_spent))) if r.budget_total is not None else None
    return {"agent_did": agent.did, "mode": agent_delegation_mode(), "tokens": [
        {"id": r.id, "role": "issuer" if r.issuer_agent_did == agent.did else "holder",
         "issuer_did": r.issuer_agent_did, "holder_did": r.holder_agent_did,
         "parent_token_id": r.parent_token_id, "depth": r.depth, "status": r.status,
         "permissions": (r.caveats or {}).get("permissions", []), "budget_remaining": _rem(r),
         "currency": r.currency, "expires_at": r.expires_at.isoformat() if r.expires_at else None}
        for r in rows]}


# ── owner/admin oversight (developer JWT) — read + revoke an agent's cap tokens ──
async def _owned_agent_did(db: AsyncSession, did: str, dev: models.Developer) -> None:
    row = (await db.execute(text(
        "SELECT creator_developer_id FROM agents WHERE did = :d"), {"d": did})).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if not (admin_credential(dev) or row.creator_developer_id == dev.id):   # §POCKETPAIR
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your agent")


@router.get("/agents/{did}/capabilities", summary="Oversight: capability tokens an agent issued/holds (owner/admin)")
async def agent_capabilities_oversight(
    did: str,
    current: models.Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await _owned_agent_did(db, did, current)
    rows = (await db.execute(text(
        "SELECT id, issuer_agent_did, holder_agent_did, parent_token_id, depth, caveats, "
        "budget_total, budget_spent, currency, max_uses, uses, status, created_at, expires_at "
        "FROM agent_capability_tokens WHERE issuer_agent_did = :d OR holder_agent_did = :d "
        "ORDER BY created_at DESC LIMIT 200"
    ), {"d": did})).fetchall()
    def _rem(r):
        return float(Decimal(str(r.budget_total)) - Decimal(str(r.budget_spent))) if r.budget_total is not None else None
    # SEC-11: each token's own limits (its caveats and its uses bound) beside its permissions, so the owner sees what a
    # child derived from it must stay within (the console's attenuate form starts from them)
    return {"agent_did": did, "mode": agent_delegation_mode(), "tokens": [
        {"id": r.id, "role": "issuer" if r.issuer_agent_did == did else "holder",
         "issuer_did": r.issuer_agent_did, "holder_did": r.holder_agent_did,
         "parent_token_id": r.parent_token_id, "depth": r.depth, "status": r.status,
         "permissions": (r.caveats or {}).get("permissions", []), "budget_remaining": _rem(r),
         "currency": r.currency, "expires_at": r.expires_at.isoformat() if r.expires_at else None,
         "caveats": r.caveats or {},
         "max_uses": None if r.max_uses is None else int(r.max_uses),
         "uses_left": None if r.max_uses is None else max(0, int(r.max_uses) - int(r.uses or 0))}
        for r in rows]}


@router.delete("/agents/{did}/capabilities/{token_id}", summary="Oversight: revoke a token + subtree (owner/admin)")
async def agent_capability_revoke_oversight(
    did: str,
    token_id: int,
    current: models.Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    await _owned_agent_did(db, did, current)
    row = (await db.execute(text(
        "SELECT issuer_agent_did, holder_agent_did FROM agent_capability_tokens WHERE id = :i"
    ), {"i": token_id})).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Token not found")
    if did not in (row.issuer_agent_did, row.holder_agent_did):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Token not issued/held by this agent")
    n = await capmod.revoke_subtree(db, token_id, f"oversight:dev:{current.id}")
    await log_ironkey_action(  # commits — cascade + audit row in one transaction
        db, action="capability_revoke", actor_type="developer", actor_id=str(current.id),
        target_type="capability_token", target_id=str(token_id),
        details={"agent_did": did, "issuer_did": row.issuer_agent_did,
                 "holder_did": row.holder_agent_did, "revoked_count": n, "via": "oversight"})
    await db.commit()
    logger.warning("[IRONKEY-L4] oversight revoke token=%s by dev=%s revoked=%s", token_id, current.id, n)
    # §auditfix: the owner/admin EMERGENCY cut previously left no ledger trace — the
    # opposite of what a kill-switch should do. Same event type + idempotency key as the
    # self-revoke path (one revocation, one event, whichever hand pulled it), AWAITED.
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        await get_event_emitter().emit(
            event_type="AgentCapabilityRevoked",
            aggregate_id=row.holder_agent_did or row.issuer_agent_did,
            data={
                "token_id": token_id,
                "issuer_did": row.issuer_agent_did,
                "holder_did": row.holder_agent_did,
                "revoked_by": f"dev:{current.id}",
                "revoked_count": n,
                "via": "oversight",
            },
            idempotency_key=f"cap-revoked-{token_id}",
        )
    except Exception:  # noqa: BLE001 — the revocation itself already stands
        logger.warning("[IRONKEY-L4] AgentCapabilityRevoked (oversight) emit failed token=%s", token_id)
    return {"ok": True, "root_token_id": token_id, "revoked_count": n}


# ── admin: delegation/capability census ──────────────────────────────────────
@router.get("/admin/agents/delegation/report", summary="Delegation + capability fleet report (admin)")
async def delegation_report(
    current: models.Developer = Depends(require_admin_flag("admin_platform")),
    db: AsyncSession = Depends(get_db),
):
    """Fleet census of delegations and capability tokens. D6-272: `xreg_revoke_delivery` is the delivery of this
    registry's cross-registry revokes to the delegates' registries: how many are in each state (delivered, retrying,
    given_up, expired) and the ones not delivered, oldest first (credential, issuer, registry, sends, last answer)."""
    from agentvault_registry.services import xreg_revoke_delivery as _xrd
    grants = (await db.execute(text(
        "SELECT count(*) FROM agent_delegation_grants WHERE revoked_at IS NULL"))).scalar() or 0
    caps = (await db.execute(text(
        "SELECT status, count(*) AS n FROM agent_capability_tokens GROUP BY status"))).fetchall()
    return {"mode": agent_delegation_mode(), "active_delegation_grants": int(grants),
            "capability_tokens_by_status": {r.status: int(r.n) for r in caps},
            "xreg_revoke_delivery": await _xrd.admin_summary(db)}


# ════════════════════════════ ★1 — SUB-AGENT SPAWN ══════════════════════════════
# The identity↔authority seam: an agent holding ``authz.delegate`` creates a scoped worker
# UNDER ITSELF in one call — a real, independently-addressable agent PLUS a birth ``att_``
# capability token (issuer=parent, holder=child) that is ≤ the parent on every axis.
#   * Lineage is the birth token itself (no schema change): child's parent = the birth
#     token's issuer; a parent's sub-agents = birth-token holders it issued.
#   * Suspension cascade is FREE: ``resolve_capability`` intersects with the issuer's CURRENT
#     authority, and ``issuer_effective`` returns ∅ for a non-active issuer — so suspending a
#     parent instantly de-authorizes every child it spawned, same request. (AGENTFIX-A.)
#   * The child is BASE-only on its OWN JWT (no roles seeded) — it ACTS by presenting the
#     birth token on ``X-Capability-Token``. Least privilege by construction.
# Δ-neutral: identity + a permission/budget object; any real money still clears the escrow rail.
SPAWN_MAX_TTL_SECONDS = 2592000  # 30d — a birth token is a standing delegation, not a 15-min cap


# §TWOAGENT (2026-09-23): the spawn response told the parent the child's own JWT carried no roles. It does: since §EXTMTLS (2026-08-09)
# spawn seeds the frame's birth roles (measured on ASIA: client, staker, trader, no expiry, 12 permissions), on purpose
# ("roles are a baseline, the token is the ceiling"). The ceiling binds only when the child PRESENTS the token.
SPAWN_NOTE = ("client_secret + birth_token shown ONCE. The child spends and acts under its caveats by presenting the "
              "birth token on X-Capability-Token; the token is the ceiling only when it is presented. The child's own "
              "JWT carries this registry's birth roles (listed in child_roles) and, under SPAWN_WALLET_ANCHOR_MODE, "
              "no wallet of its own. While the parent is suspended the birth token conveys nothing.")


def caveats_advisory(mode: Optional[str] = None) -> str:
    """§TWOAGENT #29 (2026-09-23): what the act-token's delegation_caveats actually DO on this registry. The old text
    told the delegate the limits were only recorded and to honour them itself; under enforce, a 0.3 transfer against
    max_per_tx 0.2 was refused 403 (measured on ASIA). The spend gate (security.enforce_agent_spend, the IRONKEY-XREG block) runs under
    AGENT_RBAC_MODE."""
    if mode is None:
        from agentvault_registry.agent_authz import agent_rbac_mode
        mode = agent_rbac_mode()
    if mode == "enforce":
        return ("issuer-attached limits, enforced on this registry's spend path whenever you act with this token "
                "(max_per_tx, allowed_currencies, geo_allow, rate_per_hour): a spend that breaks one is refused 403")
    if mode == "shadow":
        return ("issuer-attached limits, checked and logged on this registry's spend path but NOT refused "
                "(AGENT_RBAC_MODE=shadow): honor them client-side")
    return "issuer-attached limits, not checked on this registry (AGENT_RBAC_MODE=off): honor them client-side"


def spawn_enabled() -> bool:
    """``AGENT_SPAWN_ENABLED`` — default off (byte-inert). Identity creation is always valid;
    the birth token's ENFORCEMENT still follows ``AGENT_DELEGATION_MODE`` (off ⇒ inert)."""
    return os.getenv("AGENT_SPAWN_ENABLED", "false").strip().lower() == "true"


class SpawnIn(BaseModel):
    name: Optional[str] = Field(None, max_length=120)
    permissions: List[str] = Field(default_factory=list, description="child authority ⊆ parent's CURRENT effective")
    ttl_seconds: int = Field(86400, ge=60, le=SPAWN_MAX_TTL_SECONDS)
    budget_total: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = None
    max_uses: Optional[int] = Field(None, ge=1)
    max_per_tx: Optional[float] = Field(None, ge=0)
    allowed_currencies: Optional[List[str]] = None
    counterparty_allow: Optional[List[str]] = None
    no_redelegate: bool = False


@router.post("/agents/spawn", summary="Spawn a scoped sub-agent under yourself (L4 birth token)")
async def spawn_subagent(
    body: SpawnIn,
    parent: models.Agent = Depends(require_agent_permission("authz.delegate")),
    db: AsyncSession = Depends(get_db),
):
    if not spawn_enabled():
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Sub-agent spawn is disabled (AGENT_SPAWN_ENABLED)")
    parent_did = parent.did
    # child authority ⊆ parent's CURRENT effective authority (you cannot delegate what you lack)
    parent_eff = await resolve_agent_permissions(db, parent_did)
    req_perms = [p for p in body.permissions if p in ALL_PERMISSIONS]
    over = set(req_perms) - parent_eff
    if over:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Cannot delegate permissions you lack: {sorted(over)}")
    # ── mint the child identity by reusing onboarding's building blocks (bootstrap-free:
    #    the child inherits the PARENT's owning developer) ──
    from agentvault_registry.routers.onboarding import (
        generate_agent_did, generate_client_credentials, _build_stub_card_data,
        create_teg_profile_for_agent, mint_unique_agent_did,
    )
    from agentvault_registry.crud import agent as agent_crud, agent_card as card_crud
    from agentvault_registry import schemas as _schemas

    child_did = await mint_unique_agent_did(db, "theprotocol", site="spawn")  # §DIDWIDEN
    child_cid, child_secret = generate_client_credentials()
    dev_id = parent.creator_developer_id
    try:
        await agent_crud.create_agent(db, child_did, child_cid, child_secret, dev_id, None)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Child identity creation failed: {e}")
    # a schema-valid stub card at a unique host (pull-sync overwrites agent-owned fields later)
    suffix = child_did.split(":")[-1]
    host = f"https://sub-{suffix}.agents.local"
    card_data = _build_stub_card_data(host, f"spawned-by-{parent_did.split(':')[-1]}")
    if body.name:
        card_data["name"] = body.name[:120]
    try:
        card = await card_crud.create_agent_card(
            db=db, developer_id=dev_id, card_create=_schemas.AgentCardCreate(card_data=card_data))
        card.agent_did = child_did
        db.add(card)
        await db.commit()
    except Exception as e:  # noqa: BLE001 — card is non-fatal for authority; log + continue
        await db.rollback()
        logger.warning("[SPAWN] child card create/link failed for %s: %s", child_did, e)
    # §SPAWN-ANCHOR (2026-08-12): when anchoring is on, the child gets NO own wallet — it
    # spends from the parent's purse via its birth token (services/spawn_anchor.py). Default
    # off ⇒ today's behaviour (its own wallet) is unchanged, byte-for-byte.
    from agentvault_registry.services.spawn_anchor import (
        anchor_enabled as _anchor_enabled, ANCHOR_CAVEAT as _ANCHOR_CAVEAT,
    )
    _anchored = _anchor_enabled()
    if _anchored:
        logger.info("[SPAWN-ANCHOR] child %s anchored to parent %s — skipping own wallet", child_did, parent_did)
    else:
        try:
            await create_teg_profile_for_agent(child_did)  # give the child a wallet (server-to-server)
        except Exception as e:  # noqa: BLE001
            logger.warning("[SPAWN] child TEG profile failed for %s: %s", child_did, e)

    _birth_roles_seeded: List[str] = []
    # ── IRONKEY: seed DEFAULT BIRTH ROLES on the spawn path too (§EXTMTLS, 2026-08-09) ──
    # Onboarding has seeded these since 2026-07-08, but /agents/spawn never did, so every
    # spawned child was born with NO role rows and resolved to BASE only — measured 1094
    # such agents on registry-a. A child's authority still rides its birth capability
    # token (caveats ∩ issuer-current), which is unchanged; these rows only give it the
    # same baseline any onboarded agent gets, so capabilities that are role-gated rather
    # than token-gated (e.g. identity.mtls for IRONHAND enrollment) stop silently failing.
    # Deliberately NOT clamped to req_perms: roles are a baseline, the token is the ceiling.
    try:
        from agentvault_registry.agent_authz import ROLE_PERMISSIONS as _ROLE_PERMS
        _birth_roles = [r.strip() for r in os.getenv("AGENT_RBAC_DEFAULT_ROLES", "trader,client").split(",") if r.strip()]
        _birth_roles = [r for r in _birth_roles if r in _ROLE_PERMS and r != "legacy-full"]
        _birth_roles_seeded = list(_birth_roles)
        for _r in _birth_roles:
            await db.execute(text(
                "INSERT INTO agent_role_grants (agent_did, grant_type, value, granted_by_dev_id) "
                "VALUES (:did, 'role', :val, :dev) ON CONFLICT (agent_did, grant_type, value) DO NOTHING"
            ), {"did": child_did, "val": _r, "dev": dev_id})
        if _birth_roles:
            await db.commit()
            logger.info("[IRONKEY] seeded default birth roles %s for spawned %s", _birth_roles, child_did)
    except Exception as e:  # noqa: BLE001 — role seeding must never block a spawn
        await db.rollback()
        logger.warning("[IRONKEY] default birth-role seed failed for spawned %s: %s", child_did, e)
    # ── mint the BIRTH capability token: issuer=parent, holder=child, ≤ parent ──
    caveats: Dict[str, Any] = {"permissions": req_perms, "birth": True}
    if _anchored:
        caveats[_ANCHOR_CAVEAT] = True  # walletless child → spend path resolves purse to the issuer chain
    if body.max_per_tx is not None:
        caveats["max_per_tx"] = str(body.max_per_tx)
    for k, v in (("allowed_currencies", body.allowed_currencies),
                 ("counterparty_allow", body.counterparty_allow)):
        if v:
            caveats[k] = v
    if body.no_redelegate:
        caveats["no_redelegate"] = True
    plain = capmod.generate_token()
    exp = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=body.ttl_seconds)
    row = (await db.execute(text("""
        INSERT INTO agent_capability_tokens
            (token_hash, token_prefix, issuer_agent_did, holder_agent_did, parent_token_id,
             depth, caveats, budget_total, budget_spent, currency, max_uses, uses, status, expires_at)
        VALUES (:h, :pfx, :iss, :hold, NULL, 0, CAST(:cav AS JSONB), :bt, 0, :cur, :mu, 0, 'issued', :exp)
        RETURNING id
    """), {"h": capmod.hash_token(plain), "pfx": plain[:12], "iss": parent_did, "hold": child_did,
           "cav": __import__("json").dumps(caveats), "bt": body.budget_total,
           "cur": body.currency, "mu": body.max_uses, "exp": exp})).first()
    await log_ironkey_action(  # commits — birth token + audit row in one transaction
        db, action="agent_spawn", actor_type="agent", actor_id=parent_did,
        target_type="agent", target_id=child_did,
        details={"birth_token_id": row.id, "permissions": req_perms,
                 "budget_total": body.budget_total, "currency": body.currency,
                 "ttl_seconds": body.ttl_seconds, "owner_dev_id": dev_id})
    await db.commit()
    logger.info("[SPAWN] parent=%s spawned child=%s birth_token=%s perms=%s",
                parent_did, child_did, row.id, req_perms)
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        get_event_emitter().emit_background(
            event_type="AgentSpawned", aggregate_id=child_did,
            data={"parent_did": parent_did, "child_did": child_did, "birth_token_id": row.id,
                  "permissions": req_perms}, idempotency_key=f"spawn-{row.id}")
    except Exception:  # noqa: BLE001
        logger.debug("[SPAWN] AgentSpawned emit skipped", exc_info=True)
    try:  # §TWOAGENT (2026-09-24): a spawned child is a new agent of the same owner; agent.created was never fired
        from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
        asyncio.create_task(dispatch_webhook_for_agents(
            "agent.created",
            {"agent_did": child_did, "name": body.name or None, "created_via": "spawn", "parent_did": parent_did},
            [child_did], source_label="agents.spawn"))
    except Exception as e:  # noqa: BLE001
        logger.warning("[SPAWN] agent.created webhook not scheduled for %s: %s", child_did, e)
    return {
        "child_did": child_did, "client_id": child_cid, "client_secret": child_secret,
        "registry_url": credential_home_url(),  # §FEFRAME W1: the child credential's home
        "birth_token": plain, "birth_token_id": row.id, "parent_did": parent_did,
        "permissions": req_perms, "expires_at": exp.isoformat(),
        "note": SPAWN_NOTE,
        "child_roles": list(_birth_roles_seeded),
    }


@router.get("/agents/{did}/authority-tree", summary="Sub-agent lineage + capability subtree (owner/admin)")
async def authority_tree(
    did: str,
    current: models.Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Oversight read: the agent's birth lineage (who spawned it) + the whole capability
    subtree it has issued (spawned children + their descendants). Data already exists; this
    is the missing first-class view. Owner or admin only."""
    await _owned_agent_did(db, did, current)

    def _rem(bt, bs):
        return float(Decimal(str(bt)) - Decimal(str(bs or 0))) if bt is not None else None

    born = (await db.execute(text(
        "SELECT id, issuer_agent_did, caveats, status, expires_at FROM agent_capability_tokens "
        "WHERE holder_agent_did = :d AND (caveats->>'birth') = 'true' "
        "ORDER BY created_at DESC LIMIT 1"), {"d": did})).first()
    born_from = None
    if born:
        born_from = {"parent_did": born.issuer_agent_did, "birth_token_id": born.id,
                     "status": born.status, "permissions": (born.caveats or {}).get("permissions", []),
                     "expires_at": born.expires_at.isoformat() if born.expires_at else None}

    rows = (await db.execute(text("""
        WITH RECURSIVE subtree AS (
            SELECT id, issuer_agent_did, holder_agent_did, parent_token_id, depth, caveats,
                   status, budget_total, budget_spent, currency, expires_at
            FROM agent_capability_tokens WHERE issuer_agent_did = :d
            UNION ALL
            SELECT c.id, c.issuer_agent_did, c.holder_agent_did, c.parent_token_id, c.depth,
                   c.caveats, c.status, c.budget_total, c.budget_spent, c.currency, c.expires_at
            FROM agent_capability_tokens c JOIN subtree s ON c.parent_token_id = s.id
        )
        SELECT * FROM subtree ORDER BY depth, id LIMIT 500
    """), {"d": did})).fetchall()
    nodes = [{
        "token_id": r.id, "issuer_did": r.issuer_agent_did, "holder_did": r.holder_agent_did,
        "parent_token_id": r.parent_token_id, "depth": r.depth, "status": r.status,
        "is_birth": bool((r.caveats or {}).get("birth")),
        "permissions": (r.caveats or {}).get("permissions", []),
        "budget_remaining": _rem(r.budget_total, r.budget_spent), "currency": r.currency,
        "expires_at": r.expires_at.isoformat() if r.expires_at else None,
    } for r in rows]
    spawned = [n for n in nodes if n["is_birth"] and n["issuer_did"] == did]
    return {"agent_did": did, "mode": agent_delegation_mode(), "born_from": born_from,
            "spawned_children": spawned, "delegated_subtree": nodes,
            "counts": {"spawned_children": len(spawned), "subtree_total": len(nodes),
                       "active": sum(1 for n in nodes if n["status"] in ("issued", "active"))}}


# ── FOREIGN HANDS: cross-frame delegations this agent issued (★2/D3) ──────────
# The lineage query above is the LOCAL spawn tree. An agent can ALSO extend a
# bounded slice of its authority to an agent on a PEER frame via
# POST /agents/delegate-cross-registry. That credential lives on the DELEGATE's
# home (the peer); the issuer home persists only an audit row + event. So we read
# our OWN `ironkey.xreg_delegation_issue` trail, then best-effort enrich live
# status (verified / revoked / expired) from each named peer. Bounded + fail-open:
# a dead or old peer degrades to the declared record, never blanks the tree.
def _frame_label(url: str) -> Optional[str]:
    if not url:
        return None
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or url
    except Exception:  # noqa: BLE001
        host = url
    return (host.split(".")[0] or host) if host else None


async def _enrich_foreign_live(db: AsyncSession, did: str, foreign: List[Dict[str, Any]]) -> None:
    """Best-effort: ask each named peer for the LIVE status of the credentials it holds
    for this issuer, and fold it into `foreign` in place. Never raises."""
    from agentvault_registry.routers.guild import _resolve_peer_url, _fed_client_config
    import httpx as _httpx
    regs = sorted({f["home_registry"] for f in foreign if f.get("home_registry")})
    live: Dict[str, Dict[str, Any]] = {}
    for reg in regs[:4]:  # bounded fan-out over DISTINCT peers (usually 1)
        try:
            target = await _resolve_peer_url(db, reg)
            cfg, fed_headers = _fed_client_config(target)
            async with _httpx.AsyncClient(**cfg) as client:
                r = await client.get(
                    f"{target}/api/v1/federation/ironkey/delegations-for-issuer",
                    params={"issuer_did": did}, headers=fed_headers, timeout=6)
            if r.status_code == 200:
                for row in (r.json() or {}).get("delegations", []) or []:
                    cid = row.get("credential_id")
                    if cid:
                        live[cid] = row
        except Exception:  # noqa: BLE001
            continue
    if not live:
        return
    now = _dt.datetime.now(_dt.timezone.utc)
    for f in foreign:
        row = live.get(f.get("credential_id"))
        if not row:
            continue
        f["live"] = True
        exp = row.get("expires_at") or f.get("expires_at")
        f["expires_at"] = exp
        past = False
        if exp:
            try:
                past = _dt.datetime.fromisoformat(exp) < now
            except (ValueError, TypeError):
                past = False
        if row.get("revoked"):
            f["status"] = "revoked"
        elif past:
            f["status"] = "expired"
        elif row.get("verified"):
            f["status"] = "active"
        else:
            f["status"] = "delegated"


async def _collect_foreign_delegations(db: AsyncSession, did: str) -> List[Dict[str, Any]]:
    """Cross-frame 'hands' = agents on PEER frames this agent delegated authority to.
    Sourced from our own `ironkey.xreg_delegation_issue` audit trail (authoritative
    for what WE issued), then best-effort live-status enriched from each peer."""
    import json as _json
    rows = (await db.execute(text("""
        SELECT target_id, details, timestamp, outcome
        FROM security_audit_logs
        WHERE action = 'ironkey.xreg_delegation_issue' AND actor_id = :d
        ORDER BY timestamp DESC LIMIT 100
    """), {"d": did})).fetchall()
    now = _dt.datetime.now(_dt.timezone.utc)
    seen: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        try:
            d = _json.loads(r.details) if r.details else {}
        except (ValueError, TypeError):
            d = {}
        if not isinstance(d, dict):
            continue
        cid = d.get("credential_id")
        if not cid or cid in seen:
            continue
        reg = (d.get("delegate_registry") or "").rstrip("/")
        exp = d.get("expires_at")
        past = False
        if exp:
            try:
                past = _dt.datetime.fromisoformat(exp) < now
            except (ValueError, TypeError):
                past = False
        status = "delegated" if (r.outcome == "success") else "ship_failed"
        if past:
            status = "expired"
        seen[cid] = {
            "credential_id": cid,
            "delegate_did": r.target_id,
            "home_registry": reg,
            "home_frame": _frame_label(reg),
            "home_ui_url": (f"{reg}/ui#/agent/{r.target_id}" if (reg and r.target_id) else None),
            "permissions": d.get("permissions") or [],
            "caveats": d.get("caveats") or {},
            "expires_at": exp,
            "status": status,
            "live": False,
            "issued_at": r.timestamp.isoformat() if r.timestamp else None,
        }
    foreign = list(seen.values())
    if foreign:
        try:
            await _enrich_foreign_live(db, did, foreign)
        except Exception:  # noqa: BLE001
            logger.debug("[LINEAGE] foreign live-status enrich failed", exc_info=True)
        # D6-272: a revoke this agent recorded decides (the delegate's home asks this registry at use), even while its
        # message to that home is still being sent again
        revoked = {str(r[0]) for r in (await db.execute(text(
            "SELECT target_id FROM security_audit_logs WHERE action = 'ironkey.xreg_delegation_revoke' "
            "AND actor_type = 'agent' AND actor_id = :d ORDER BY timestamp DESC LIMIT 500"), {"d": did})).all()}
        for f in foreign:
            if f["credential_id"] in revoked:
                f["status"] = "revoked"
    return foreign


@router.get("/agents/{did}/lineage",
            summary="Sub-agent lineage tree (hands → their hands) with reusability + decay (owner/admin)")
async def agent_lineage(
    did: str,
    max_gen: int = 8,
    current: models.Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """The agent's SPAWN tree: each hand it spawned, recursively down to THEIR hands, with each hand's
    capability (permissions ≤ parent), reusability (uses-left), spend leash (budget), and decay
    (status/TTL). Recurses holder→issuer across birth capability tokens (the real spawn chain), because
    `parent_token_id` is the att_ attenuation chain and would miss grandchild hands. A walletless hand
    carries `caveats.anchored`. Owner or admin only. (Per-hand cross-frame MONEY activity lives in the
    EventStore/TEG, not here; this view records identity, authority, and decay.)"""
    await _owned_agent_did(db, did, current)
    mg = max(1, min(12, int(max_gen)))

    def _rem(total, spent):
        return None if total is None else float(Decimal(str(total)) - Decimal(str(spent or 0)))

    born = (await db.execute(text(
        "SELECT id, issuer_agent_did, caveats, status, expires_at FROM agent_capability_tokens "
        "WHERE holder_agent_did = :d AND (caveats->>'birth') = 'true' ORDER BY created_at DESC LIMIT 1"
    ), {"d": did})).first()
    born_from = None if not born else {
        "parent_did": born.issuer_agent_did, "birth_token_id": born.id, "status": born.status,
        "anchored": bool((born.caveats or {}).get("anchored")),
        "expires_at": born.expires_at.isoformat() if born.expires_at else None}

    rows = (await db.execute(text("""
        WITH RECURSIVE hands AS (
            SELECT id, issuer_agent_did, holder_agent_did, caveats, status, budget_total,
                   budget_spent, currency, max_uses, uses, expires_at, created_at, 1 AS gen
            FROM agent_capability_tokens
            WHERE issuer_agent_did = :d AND (caveats->>'birth') = 'true'
            UNION ALL
            SELECT t.id, t.issuer_agent_did, t.holder_agent_did, t.caveats, t.status, t.budget_total,
                   t.budget_spent, t.currency, t.max_uses, t.uses, t.expires_at, t.created_at, h.gen + 1
            FROM agent_capability_tokens t
            JOIN hands h ON t.issuer_agent_did = h.holder_agent_did
            WHERE (t.caveats->>'birth') = 'true' AND h.gen < :mg
        )
        SELECT * FROM hands ORDER BY gen, id LIMIT 1000
    """), {"d": did, "mg": mg})).fetchall()

    hands = []
    for r in rows:
        cav = r.caveats or {}
        uses_left = None if r.max_uses is None else max(0, int(r.max_uses) - int(r.uses or 0))
        dead = (uses_left == 0) or (r.status in ("revoked", "expired", "exhausted"))
        hands.append({
            "token_id": r.id, "hand_did": r.holder_agent_did, "parent_did": r.issuer_agent_did,
            "generation": r.gen, "anchored": bool(cav.get("anchored")),
            "permissions": cav.get("permissions", []), "status": r.status,
            "alive": (r.status in ("issued", "active")) and not dead,
            "uses": int(r.uses or 0),
            "max_uses": (None if r.max_uses is None else int(r.max_uses)), "uses_left": uses_left,
            "budget_remaining": _rem(r.budget_total, r.budget_spent), "currency": r.currency,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "no_redelegate": bool(cav.get("no_redelegate")),
        })

    foreign_hands: List[Dict[str, Any]] = []
    try:
        foreign_hands = await _collect_foreign_delegations(db, did)
    except Exception:  # noqa: BLE001
        logger.debug("[LINEAGE] foreign delegation collection failed", exc_info=True)

    return {"agent_did": did, "mode": agent_delegation_mode(), "born_from": born_from, "hands": hands,
            "foreign_hands": foreign_hands,
            "counts": {"total": len(hands), "alive": sum(1 for h in hands if h["alive"]),
                       "anchored": sum(1 for h in hands if h["anchored"]),
                       "generations": max((h["generation"] for h in hands), default=0),
                       "foreign": len(foreign_hands)},
            "note": "Hands are LOCAL spawned sub-agents. Cross-frame delegations (below) extend a bounded "
                    "slice of this agent's authority to an agent on a peer frame; per-hand money activity "
                    "lives in the EventStore/TEG."}


# ══════════════════ ★2 — CROSS-REGISTRY SUB-AGENT DELEGATION (D3) ════════════════
# Done the Guild way (home-vouched, Ed25519 credential, verify-at-home). Agent A on THIS
# registry delegates a bounded permission subset to agent B on a PEER registry. A's home
# SIGNS a delegation credential and ships it to B's home. B's home VERIFIES the signature
# against A's-home pubkey (allowlisted mTLS channel), records it, and mints a LOCAL
# ``agent_delegation_grants`` row (principal ``agent:A``). Ground-truth #1 preserved: B's
# authority is still resolved at B's OWN home; the peer only supplies a verifiable claim,
# never authority. B exercises it by presenting a token whose ``act.sub = agent:A``.
# Δ-neutral (permission bookkeeping + signature only). Flag AGENT_XREG_DELEGATION_ENABLED.
_XREG_MAX_TTL_HOURS = 720  # 30d


def xreg_delegation_enabled() -> bool:
    return os.getenv("AGENT_XREG_DELEGATION_ENABLED", "false").strip().lower() == "true"


class XRegDelegateIn(BaseModel):
    delegate_did: str = Field(..., max_length=120, description="the REMOTE agent to delegate to")
    delegate_registry_url: str = Field(..., description="delegate's HOME registry (an ACTIVE peer)")
    permissions: List[str] = Field(..., description="subset ⊆ your CURRENT effective authority")
    ttl_hours: int = Field(24, ge=1, le=_XREG_MAX_TTL_HOURS)
    max_per_tx: Optional[float] = Field(None, ge=0)
    allowed_currencies: Optional[List[str]] = None


class XRegRevokeIn(BaseModel):
    credential_id: str = Field(..., max_length=64)


class _FedDelegationIn(BaseModel):
    credential_id: str = Field(..., max_length=64)
    issuer_registry: str = Field(..., max_length=300)
    issuer_did: str = Field(..., max_length=120)
    delegate_did: str = Field(..., max_length=120)
    permissions: List[str]
    caveats: Optional[Dict[str, Any]] = None
    expires_at: Optional[str] = None
    credential: Dict[str, Any]   # the signed bundle


class _FedRevokeIn(BaseModel):
    credential_id: str = Field(..., max_length=64)
    issuer_registry: str = Field(..., max_length=300)


@router.post("/agents/delegate-cross-registry", summary="Delegate a bounded capability to a REMOTE agent (★2/D3)")
async def delegate_cross_registry(
    body: XRegDelegateIn,
    issuer: models.Agent = Depends(require_agent_permission("authz.delegate")),
    db: AsyncSession = Depends(get_db),
):
    if not xreg_delegation_enabled():
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Cross-registry delegation is disabled (AGENT_XREG_DELEGATION_ENABLED)")
    issuer_did = issuer.did
    # permissions ⊆ issuer's CURRENT effective authority (you cannot delegate what you lack)
    eff = await resolve_agent_permissions(db, issuer_did)
    perms = [p for p in body.permissions if p in ALL_PERMISSIONS]
    over = set(perms) - eff
    if over:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Cannot delegate permissions you lack: {sorted(over)}")
    if not perms:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No delegable permissions requested")
    # the delegate must be REMOTE — a local agent uses plain L3 (POST /agents/{did}/delegations)
    local = (await db.execute(text("SELECT 1 FROM agents WHERE did = :d"), {"d": body.delegate_did})).first()
    if local:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail="delegate is LOCAL — use POST /agents/{did}/delegations (plain L3) instead")
    from agentvault_registry.routers.guild import _self_public_url, _resolve_peer_url, _fed_client_config
    from agentvault_registry.services.attestation_signer import sign_bundle
    import secrets as _secrets, httpx as _httpx
    cred_id = _secrets.token_hex(16)
    exp = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=body.ttl_hours)
    caveats: Dict[str, Any] = {}
    if body.max_per_tx is not None:
        caveats["max_per_tx"] = str(body.max_per_tx)
    if body.allowed_currencies:
        caveats["allowed_currencies"] = body.allowed_currencies
    claim = {
        "kind": "ironkey.delegation.v1",
        "credential_id": cred_id,
        "issuer_registry": _self_public_url(),
        "issuer_did": issuer_did,
        "delegate_did": body.delegate_did,
        "permissions": perms,
        "caveats": caveats,
        "not_before": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "expires_at": exp.isoformat(),
    }
    signed = sign_bundle(claim)
    try:
        target = await _resolve_peer_url(db, body.delegate_registry_url)
        cfg, fed_headers = _fed_client_config(target)
        payload = {"credential_id": cred_id, "issuer_registry": _self_public_url(),
                   "issuer_did": issuer_did, "delegate_did": body.delegate_did,
                   "permissions": perms, "caveats": caveats, "expires_at": exp.isoformat(),
                   "credential": signed}
        async with _httpx.AsyncClient(**cfg) as client:
            r = await client.post(f"{target}/api/v1/federation/ironkey/delegation-credential",
                                  json=payload, headers=fed_headers)
        ok = r.status_code in (200, 201)
        detail = r.json() if ok else {"status": r.status_code, "body": r.text[:200]}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"Ship to delegate's home failed: {e}")
    logger.info("[IRONKEY-XREG] issued delegation cred=%s %s -> %s@%s perms=%s ship_ok=%s",
                cred_id, issuer_did, body.delegate_did, body.delegate_registry_url, perms, ok)
    # §auditfix: the issuer side persists NOTHING locally (sign + ship only) — this audit
    # row + ledger event are the issuer-home's ONLY durable record of the delegation.
    await log_ironkey_action(
        db, action="xreg_delegation_issue", actor_type="agent", actor_id=issuer_did,
        target_type="agent", target_id=body.delegate_did,
        outcome="success" if ok else "ship_failed",
        details={"credential_id": cred_id, "delegate_registry": body.delegate_registry_url,
                 "permissions": perms, "caveats": caveats, "expires_at": exp.isoformat()})
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        get_event_emitter().emit_background(
            event_type="AgentXRegDelegationIssued",
            aggregate_id=issuer_did,
            data={"credential_id": cred_id, "issuer_did": issuer_did,
                  "delegate_did": body.delegate_did,
                  "delegate_registry": body.delegate_registry_url,
                  "permissions": perms, "caveats": caveats,
                  "expires_at": exp.isoformat(), "ship_ok": ok},
            idempotency_key=f"xdeleg-{cred_id}",
        )
    except Exception:  # noqa: BLE001
        logger.debug("[IRONKEY-XREG] AgentXRegDelegationIssued emit skipped", exc_info=True)
    return {"ok": ok, "credential_id": cred_id, "issuer_did": issuer_did,
            "delegate_did": body.delegate_did, "permissions": perms,
            "expires_at": exp.isoformat(), "peer_response": detail,
            "note": "the delegate exercises this by presenting a token with act.sub=agent:%s at ITS home" % issuer_did}


@router.post("/federation/ironkey/delegation-credential", summary="Receive a delegation credential for a LOCAL agent (federation)")
async def receive_delegation_credential(
    body: _FedDelegationIn,
    db: AsyncSession = Depends(get_db),
    peer_spiffe_id: str = Security(get_federation_identity),
):
    """HOME side: verify the issuer-home's Ed25519 signature, store the credential, and create a
    LOCAL bounded ``agent:<issuer>`` delegation grant. The delegate must be OUR agent: we never
    create authority for someone else's agent, and we resolve B's authority ourselves at use time."""
    if not xreg_delegation_enabled():
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Cross-registry delegation is disabled")
    mine = (await db.execute(text("SELECT 1 FROM agents WHERE did = :d"), {"d": body.delegate_did})).first()
    if not mine:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Delegate is not homed on this registry")
    # verify the signature against the ISSUER-HOME's published pubkey (TOFU over the allowlist)
    from agentvault_registry.routers.guild import _fetch_peer_pubkey
    from agentvault_registry.services.attestation_signer import verify_bundle_signature
    pk = await _fetch_peer_pubkey(db, body.issuer_registry,
                                 expect_pubkey_id=body.credential.get("signature_pubkey_id"))
    verified = False
    if pk and body.credential.get("signature_pubkey_id") == pk.get("pubkey_id"):
        try:
            ok, why = verify_bundle_signature(dict(body.credential), issuer_pubkey_b64=pk["pubkey_b64"])
            verified = bool(ok)
            if not ok:
                logger.warning("[IRONKEY-XREG] credential signature INVALID cred=%s: %s", body.credential_id, why)
        except Exception as e:  # noqa: BLE001
            logger.warning("[IRONKEY-XREG] verify error cred=%s: %s", body.credential_id, e)
    if not verified:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Credential signature could not be verified against the issuer-home pubkey")
    # ── BUNDLE-AUTHORITATIVE binding (defence-in-depth, DEBUG-2026-07-18 finding #1) ──
    # Only ``body.credential`` (the Ed25519-signed claim) is trusted. The outer envelope
    # fields (permissions/issuer_did/delegate_did/credential_id/expires_at) are UNSIGNED —
    # a peer that reaches this mTLS-gated endpoint must NOT be able to escalate the grant,
    # redirect the delegate, or extend expiry by tampering the envelope around a legitimately
    # signed bundle. We derive every persisted value from the SIGNED claim and reject (422)
    # on any envelope↔signature disagreement.
    c = body.credential
    b_perms = [p for p in (c.get("permissions") or []) if p in ALL_PERMISSIONS]
    b_iss = (c.get("issuer_did") or "")
    b_del = (c.get("delegate_did") or "")
    b_cid = (c.get("credential_id") or "")
    b_reg = (c.get("issuer_registry") or body.issuer_registry or "").rstrip("/")
    b_cav = c.get("caveats") if isinstance(c.get("caveats"), dict) else {}
    outer_perms = sorted(p for p in (body.permissions or []) if p in ALL_PERMISSIONS)
    mism = []
    if body.credential_id != b_cid: mism.append("credential_id")
    if body.issuer_did != b_iss: mism.append("issuer_did")
    if body.delegate_did != b_del: mism.append("delegate_did")
    if outer_perms != sorted(b_perms): mism.append("permissions")
    if mism:
        logger.warning("[IRONKEY-XREG] envelope/signature MISMATCH cred=%s fields=%s (peer=%s)",
                       b_cid or body.credential_id, mism, peer_spiffe_id)
        # §auditfix: a tampered envelope around a legitimately-signed bundle is a FORGERY
        # attempt — the one signal on this endpoint that must survive in the audit table.
        # Nothing is pending on the session at this point, so the writer's commit is safe.
        await log_ironkey_action(
            db, action="xreg_delegation_forgery_rejected", actor_type="registry",
            actor_id=peer_spiffe_id, target_type="agent", target_id=body.delegate_did,
            outcome="denied", severity="critical",
            details={"credential_id": b_cid or body.credential_id,
                     "issuer_registry": body.issuer_registry, "mismatched_fields": mism})
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Envelope does not match the signed credential: {mism}")
    perms = b_perms  # trusted (signed) permission set
    # asyncpg (unlike psycopg2) will NOT coerce an ISO string into TIMESTAMPTZ — parse the
    # SIGNED expiry to a datetime (or None) so the grants.expires_at bind is a real instance.
    exp = None
    if c.get("expires_at"):
        try:
            exp = _dt.datetime.fromisoformat(c["expires_at"])
        except (ValueError, TypeError):
            exp = None
    ins = await db.execute(text("""
        INSERT INTO agent_delegation_credentials
            (id, credential_id, host_registry, issuer_did, delegate_did, permissions, caveats, bundle, pubkey_id, verified)
        VALUES (:id, :cid, :host, :iss, :del, :perms, CAST(:cav AS JSONB), CAST(:bundle AS JSONB), :pk, TRUE)
        ON CONFLICT (host_registry, credential_id) DO NOTHING
    """), {"id": f"adc_{__import__('uuid').uuid4().hex[:24]}", "cid": b_cid,
           "host": b_reg, "iss": b_iss, "del": b_del,
           "perms": perms, "cav": __import__("json").dumps(b_cav),
           "bundle": __import__("json").dumps(body.credential), "pk": body.credential.get("signature_pubkey_id")})
    granted = False
    grant_id = None
    if ins.rowcount:  # first delivery only — mint the local grant once
        pref = f"agent:{b_iss}"
        g = (await db.execute(text("""
            INSERT INTO agent_delegation_grants
                (principal_type, principal_ref, delegate_agent_did, permissions, may_redelegate, max_depth, granted_by_dev_id, expires_at)
            VALUES ('agent', :pref, :del, :perms, false, 1, NULL, :exp)
            ON CONFLICT (principal_type, principal_ref, delegate_agent_did) DO UPDATE SET
                permissions = EXCLUDED.permissions, expires_at = EXCLUDED.expires_at,
                revoked_at = NULL, revoke_reason = NULL
            RETURNING id
        """), {"pref": pref, "del": b_del, "perms": perms, "exp": exp})).first()
        grant_id = g.id if g else None
        await db.execute(text("UPDATE agent_delegation_credentials SET grant_id = :g WHERE host_registry = :h AND credential_id = :c"),
                         {"g": grant_id, "h": b_reg, "c": b_cid})
        granted = True
    await log_ironkey_action(  # commits — credential + grant + audit row in one transaction
        db, action="xreg_delegation_receive", actor_type="registry", actor_id=peer_spiffe_id,
        target_type="agent", target_id=b_del,
        details={"credential_id": b_cid, "issuer_registry": b_reg, "issuer_did": b_iss,
                 "permissions": perms, "caveats": b_cav, "granted": granted,
                 "grant_id": grant_id})
    await db.commit()
    logger.info("[IRONKEY-XREG] received cred=%s %s->%s verified=%s granted=%s grant_id=%s",
                body.credential_id, body.issuer_did, body.delegate_did, verified, granted, grant_id)
    if granted:  # redelivery of a stored credential mints nothing → no duplicate event
        try:
            from agentvault_registry.event_emitter import get_event_emitter
            get_event_emitter().emit_background(
                event_type="AgentXRegDelegationReceived",
                aggregate_id=b_del,
                data={"credential_id": b_cid, "issuer_registry": b_reg, "issuer_did": b_iss,
                      "delegate_did": b_del, "permissions": perms, "caveats": b_cav,
                      "grant_id": grant_id, "peer_spiffe_id": peer_spiffe_id},
                idempotency_key=f"xdeleg-recv-{b_cid}",
            )
        except Exception:  # noqa: BLE001
            logger.debug("[IRONKEY-XREG] AgentXRegDelegationReceived emit skipped", exc_info=True)
        _notify_delegate_owner("delegation.received", {
            "scope": "cross_registry", "delegate_did": b_del, "principal": f"agent:{b_iss}",
            "issuer_did": b_iss, "issuer_registry": b_reg, "credential_id": b_cid, "permissions": perms,
            "caveats": b_cav, "expires_at": c.get("expires_at"),
            "use_with": f"POST /api/v1/agents/act-token with act_as=agent:{b_iss}, then present that token"}, b_del)
    return {"ok": True, "verified": verified, "granted": granted, "grant_id": grant_id,
            "principal_ref": f"agent:{body.issuer_did}", "permissions": perms}


@router.get("/federation/ironkey/delegations-for-issuer",
            summary="Federation: live status of delegations this frame holds for an issuer (peer-authed)")
async def delegations_for_issuer(
    issuer_did: str,
    db: AsyncSession = Depends(get_db),
    peer_spiffe_id: str = Security(get_federation_identity),
):
    """
    Peer-authenticated read for the issuer home's lineage view: the live state (verified, revoked, expiry) of the
    cross-frame delegations this frame holds for one issuer DID. Read-only, and scoped to the caller: a peer sees
    only the credentials its own registry issued (resolved from its SVID, never from the request).

    \f
    Peer-authed read used by the issuer-home's lineage view to show the LIVE state
    (verified / revoked / expiry) of the cross-frame delegations THIS frame holds for
    one of the peer's agents. Read-only, scoped to a single issuer_did.

    §TWOAGENT (2026-09-23): and scoped to the CALLER. It listed every credential held for any issuer to any peer
    (or licensed caller) that asked, and those credential ids are exactly what `delegation-revoke` takes. Now a
    caller sees only the credentials its own registry issued (resolved from its SVID, never from the request).
    """
    caller = await _caller_peer(db, peer_spiffe_id)
    from agentvault_registry.services.contract_xframe import resolve_peer_name
    rows = (await db.execute(text("""
        SELECT c.credential_id, c.host_registry, c.delegate_did, c.permissions, c.verified,
               c.revoked_at AS cred_revoked, g.expires_at AS grant_exp, g.revoked_at AS grant_revoked
        FROM agent_delegation_credentials c
        LEFT JOIN agent_delegation_grants g ON g.id = c.grant_id
        WHERE c.issuer_did = :d
        ORDER BY c.received_at DESC LIMIT 200
    """), {"d": issuer_did})).fetchall()
    from agentvault_registry.routers.guild import _self_public_url
    out = [{
        "credential_id": r.credential_id,
        "delegate_did": r.delegate_did,
        "permissions": list(r.permissions or []),
        "verified": bool(r.verified),
        "revoked": bool(r.cred_revoked or r.grant_revoked),
        "expires_at": r.grant_exp.isoformat() if r.grant_exp else None,
    } for r in rows if caller is not None and await resolve_peer_name(db, r.host_registry) == caller]
    return {"host_registry": _self_public_url(), "issuer_did": issuer_did, "delegations": out}


@router.get("/federation/ironkey/issuer-authority",
            summary="Federation: the CURRENT authority of an agent that issued the caller's delegate a credential")
async def issuer_authority(
    issuer_did: str = Query(..., max_length=120),
    credential_id: str = Query(..., max_length=64),
    db: AsyncSession = Depends(get_db),
    peer_spiffe_id: str = Depends(require_peer_registry_identity),
):
    """
    Issuer side: a delegate's home asks, at use, whether a credential this registry issued still stands and what its
    issuer holds now, and clamps the delegation to that. It answers only the registry the credential was shipped to
    (resolved from the caller's SVID, never from the request); anything else is a 404 that confirms nothing.

    \f
    §TWOAGENT G4 (2026-09-23), ISSUER side. A delegate's home asks, at use, whether a credential this registry issued
    still stands and what its issuer holds NOW, and clamps the delegation to that. It answers only the registry the
    credential was shipped to, resolved from the caller's SVID and never from the request; everything else is a 404
    that confirms nothing (`services/xreg_issuer_authority.py`).
    """
    from agentvault_registry.services import xreg_issuer_authority as _xia
    if not xreg_delegation_enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=_xia.NOT_VOUCHED_DETAIL)
    caller = await _caller_peer(db, peer_spiffe_id)
    answer = await _xia.issuer_answer(db, issuer_did, credential_id, caller)
    if answer is None:
        logger.info("[IRONKEY-XREG] issuer-authority: nothing to say to %s about cred=%s", caller or peer_spiffe_id,
                    credential_id)
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=_xia.NOT_VOUCHED_DETAIL)
    return answer


@router.post("/federation/ironkey/delegation-revoke", summary="Revoke a received delegation credential (federation)")
async def revoke_delegation_credential(
    body: _FedRevokeIn,
    db: AsyncSession = Depends(get_db),
    peer_spiffe_id: str = Security(get_federation_identity),
):
    """
    The issuer's home tells the delegate's home to revoke: the credential and the grant made from it are revoked.
    Idempotent; the local resolver stops honoring the grant on the next request. Only the credential's own issuer
    home may revoke it (its SVID must resolve to that registry); any other caller gets the answer for an unknown
    credential, which confirms nothing.

    \f
    Issuer-home tells the delegate-home to revoke: flip the credential + the minted grant.
    Idempotent. The local resolver stops honoring the grant on the next request.

    §TWOAGENT (2026-09-23): only the credential's own issuer home may revoke it. The caller used to be any peer (or
    licensed caller) that named the issuer's registry in the body; now its SVID must resolve to that registry, and
    any other caller gets the same answer as an unknown credential, which confirms nothing.
    """
    caller = await _caller_peer(db, peer_spiffe_id)
    from agentvault_registry.services.contract_xframe import resolve_peer_name
    if caller is None or await resolve_peer_name(db, body.issuer_registry) != caller:
        logger.warning("[IRONKEY-XREG] revoke of cred=%s naming %s refused for caller %s", body.credential_id,
                       body.issuer_registry, caller or peer_spiffe_id)
        await log_ironkey_action(
            db, action="xreg_delegation_revoke_refused", actor_type="registry", actor_id=peer_spiffe_id,
            target_type="credential", target_id=body.credential_id, outcome="denied", severity="warning",
            details={"issuer_registry": body.issuer_registry, "caller_peer": caller})
        return {"ok": True, "revoked": False, "reason": "unknown_or_already_revoked"}
    row = (await db.execute(text(
        "SELECT issuer_did, delegate_did FROM agent_delegation_credentials "
        "WHERE host_registry = :h AND credential_id = :c AND revoked_at IS NULL"),
        {"h": body.issuer_registry.rstrip("/"), "c": body.credential_id})).first()
    if not row:
        return {"ok": True, "revoked": False, "reason": "unknown_or_already_revoked"}
    await db.execute(text("UPDATE agent_delegation_credentials SET revoked_at = now() "
                          "WHERE host_registry = :h AND credential_id = :c"),
                     {"h": body.issuer_registry.rstrip("/"), "c": body.credential_id})
    await db.execute(text("UPDATE agent_delegation_grants SET revoked_at = now(), revoke_reason = 'xreg_credential_revoked' "
                          "WHERE principal_type = 'agent' AND principal_ref = :pref AND delegate_agent_did = :del AND revoked_at IS NULL"),
                     {"pref": f"agent:{row.issuer_did}", "del": row.delegate_did})
    await log_ironkey_action(  # commits — credential + grant flip + audit row in one transaction
        db, action="xreg_delegation_revoke", actor_type="registry", actor_id=peer_spiffe_id,
        target_type="agent", target_id=row.delegate_did,
        details={"credential_id": body.credential_id, "issuer_registry": body.issuer_registry,
                 "issuer_did": row.issuer_did, "side": "delegate_home"})
    await db.commit()
    logger.warning("[IRONKEY-XREG] revoked cred=%s %s->%s", body.credential_id, row.issuer_did, row.delegate_did)
    # Revocation → AWAITED emit (as durable as the cut). Delegate-home side of the record.
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        await get_event_emitter().emit(
            event_type="AgentXRegDelegationRevoked",
            aggregate_id=row.delegate_did,
            data={"credential_id": body.credential_id, "issuer_registry": body.issuer_registry,
                  "issuer_did": row.issuer_did, "delegate_did": row.delegate_did,
                  "side": "delegate_home"},
            idempotency_key=f"xdeleg-revoked-{body.credential_id}",
        )
    except Exception:  # noqa: BLE001 — the revocation itself already stands
        logger.warning("[IRONKEY-XREG] AgentXRegDelegationRevoked emit failed cred=%s", body.credential_id)
    _notify_delegate_owner("delegation.revoked", {
        "scope": "cross_registry", "delegate_did": row.delegate_did, "principal": f"agent:{row.issuer_did}",
        "issuer_did": row.issuer_did, "issuer_registry": body.issuer_registry,
        "credential_id": body.credential_id, "reason": "revoked_by_issuer"}, row.delegate_did)
    return {"ok": True, "revoked": True}


@router.get("/agents/delegate-cross-registry", summary="The cross-registry delegations this agent issued")
async def list_my_xreg_delegations(
    issuer: models.Agent = Depends(require_agent_permission("authz.delegate")),
    db: AsyncSession = Depends(get_db),
):
    """What this agent delegated to agents on other registries, for the console's Agent Access (a console gap closed in
    V0595: the rail was API and MCP only). The list is read from the issuer side's audit record (the issue and revoke
    rows the two routes above write), newest first; each entry says whether it reached the delegate's home
    (`delivered`), its expiry, and a revoke this side recorded. D6-272: a recorded revoke is `state: revoked` whatever
    became of its message (the issuer-side record is what the delegate's home asks at use), and `revoke_delivery` says
    how the message stands (delivered, sent again later, given up, expired, or not_queued for a revoke recorded before
    this registry kept undelivered revokes); `revoke_delivered` is true once it landed."""
    if not xreg_delegation_enabled():
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Cross-registry delegation is disabled (AGENT_XREG_DELEGATION_ENABLED)")
    rows = (await db.execute(text(
        "SELECT timestamp, action, outcome, target_id, details FROM security_audit_logs "
        "WHERE actor_type = 'agent' AND actor_id = :d "
        "AND action IN ('ironkey.xreg_delegation_issue', 'ironkey.xreg_delegation_revoke') "
        "ORDER BY timestamp DESC LIMIT 500"), {"d": issuer.did})).mappings().all()
    revoked: Dict[str, Any] = {}
    issued: List[Dict[str, Any]] = []
    for r in rows:
        try:
            det = json.loads(r["details"]) if isinstance(r["details"], str) else (r["details"] or {})
        except (TypeError, ValueError):
            det = {}
        if r["action"] == "ironkey.xreg_delegation_revoke":
            # newest first: the first revoke seen per credential is its latest
            revoked.setdefault(str(r["target_id"]), {"at": r["timestamp"], "delivered": r["outcome"] == "success"})
            continue
        cid = str(det.get("credential_id") or "")
        if not cid:
            continue
        issued.append({
            "credential_id": cid, "delegate_did": r["target_id"],
            "delegate_registry": det.get("delegate_registry"), "permissions": det.get("permissions") or [],
            "caveats": det.get("caveats") or {}, "expires_at": det.get("expires_at"),
            "issued_at": r["timestamp"], "delivered": r["outcome"] == "success",
        })
    from agentvault_registry.services import xreg_revoke_delivery as _xrd
    owed = await _xrd.owed_by_credential(db, issuer.did) if revoked else {}
    now = _dt.datetime.now(_dt.timezone.utc)
    for e in issued:
        rv = revoked.get(e["credential_id"])
        row = owed.get(e["credential_id"])
        e["revoked_at"] = rv["at"] if rv else None
        e["revoke_delivered"] = (rv["delivered"] or (row is not None and row.done_at is not None)) if rv else None
        e["revoke_delivery"] = _xrd.delivery_view(row, delivered_at_first_send=rv["delivered"]) if rv else None
        try:
            exp = _dt.datetime.fromisoformat(str(e["expires_at"]))
            expired = exp < now
        except (TypeError, ValueError):
            expired = False
        e["state"] = ("revoked" if rv else "not_delivered" if not e["delivered"]
                      else "expired" if expired else "active")
    return {"issuer_did": issuer.did, "delegations": issued}


@router.delete("/agents/delegate-cross-registry/{credential_id}", summary="Revoke a cross-registry delegation you issued (★2)")
async def revoke_my_xreg_delegation(
    credential_id: str,
    delegate_registry_url: Optional[str] = Query(None, max_length=500, description=(
        "Not needed: the revoke goes to the registry the delegation was issued to (its issue record names it).")),
    issuer: models.Agent = Depends(require_agent_permission("authz.delegate")),
    db: AsyncSession = Depends(get_db),
):
    """
    Revoke a cross-registry delegation this agent issued. The revoke is recorded on this registry first, and that record
    decides: the delegate's registry asks this one before the delegation conveys anything and is told it is revoked.
    The revoke is also sent to the registry the delegation was issued to, which revokes the credential and the grant
    made from it; a send that does not land there is sent again until it does (the answer's `delivery` says how it
    stands). Only a delegation this agent issued can be revoked here (any other id answers 404).

    \f
    Issue-side trigger: record the revoke here and send it to the delegate's home over federation.

    D6-272: the issuer's record of the revoke (the `ironkey.xreg_delegation_revoke` audit row) is written whatever became
    of the send, before any answer. It is what this registry's issuer-authority answer reads
    (services/xreg_issuer_authority.issuer_answer), and the delegate's home asks that answer before a cross-registry grant
    conveys anything, so the revoke stands there at its next check. The send used to be made once (a send that could not
    be made answered 502, a refused one `ok: false`). A send that did not land is now OWED: services/
    xreg_revoke_delivery.record_send writes it into xreg_revokes_owed in the transaction of the issuer-side record (both
    are committed by log_ironkey_action), and background_tasks/xreg_revoke_retry sends it again with backoff until the
    delegate's home takes it, refuses it for good, the budget is spent or the delegation expires. Every recorded revoke
    answers 200: `ok` says whether this send was delivered, `delivery` how the delivery stands.

    The revoke is sent only for a credential this agent issued (its issue record, any outcome), to the registry that
    record names: the delegate's home revokes by (this registry, credential id), so a revoke for another agent's
    credential, or to another registry, was this registry's word on something its caller never issued.
    """
    if not xreg_delegation_enabled():
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Cross-registry delegation is disabled")
    from agentvault_registry.services import xreg_issuer_authority as _xia
    from agentvault_registry.services import xreg_revoke_delivery as _xrd
    issuer_did = str(issuer.did)   # read once: a rollback below expires the loaded agent
    issued = await _xia.issued_record(db, issuer_did, credential_id, delivered_only=False)
    if issued is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail="No cross-registry delegation issued by this agent has that credential id.")
    registry = str(issued.get("delegate_registry") or "").strip() or str(delegate_registry_url or "").strip()
    if not registry:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=(
            "The issue record of this delegation names no delegate registry; name it with delegate_registry_url."))
    sent = await _xrd.send_revoke(db, credential_id, registry)
    try:
        owed = await _xrd.record_send(db, credential_id=credential_id, issuer_did=issuer_did, delegate_registry=registry,
                                      credential_expires_at=_xrd.parse_expiry(issued.get("expires_at")), outcome=sent)
    except Exception as e:  # noqa: BLE001 — the issuer-side record below decides, so it is written whatever this did
        logger.error("[IRONKEY-XREG] the delivery of the revoke of cred=%s could not be recorded (%s): the revoke is "
                     "recorded without it", credential_id, type(e).__name__)
        await db.rollback()
        owed = None
    # §auditfix: issuer-side record of the revoke trigger (the delegate-home writes its
    # own; distinct idempotency key so BOTH survive when the two homes share a frame ES).
    details: Dict[str, Any] = {"delegate_registry": registry, "side": "issuer", "peer_status": sent["status"]}
    if sent.get("error_class"):
        details["ship_error"] = sent["error_class"]
    await log_ironkey_action(  # commits: the issuer-side record and the owed delivery in one transaction
        db, action="xreg_delegation_revoke", actor_type="agent", actor_id=issuer_did,
        target_type="credential", target_id=credential_id,
        outcome="success" if sent["delivered"] else "ship_failed", details=details)
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        get_event_emitter().emit_background(
            event_type="AgentXRegDelegationRevoked",
            aggregate_id=issuer_did,
            data={"credential_id": credential_id, "issuer_did": issuer_did,
                  "delegate_registry": registry, "side": "issuer",
                  "peer_status": sent["status"]},
            idempotency_key=f"xdeleg-revoke-sent-{credential_id}",
        )
    except Exception:  # noqa: BLE001
        logger.debug("[IRONKEY-XREG] AgentXRegDelegationRevoked (issuer) emit skipped", exc_info=True)
    if not sent["delivered"]:
        logger.warning("[IRONKEY-XREG] revoke of cred=%s not delivered to %s (%s): recorded here, sent again later",
                       credential_id, registry, sent.get("error") or sent["status"])
    return {"ok": bool(sent["delivered"]), "credential_id": credential_id, "delegate_registry": registry,
            "peer_status": sent["status"], "peer_response": sent.get("body") or sent.get("error") or "",
            "delivery": _xrd.delivery_view(owed, delivered_at_first_send=bool(sent["delivered"]))}


# ── the exercise leg: re-mint MY OWN agent JWT carrying an on-behalf-of act claim ──
# The RFC 8693 `act` claim is how a delegate SAYS on whose authority it acts; authority itself
# still comes only from a matching agent_delegation_grants row resolved HERE (ground-truth #1).
# There was no way to obtain an act-bearing token before — this adds it, gated so you can only
# act-as a principal that has a LIVE grant to you (defence-in-depth; the claim alone confers
# nothing). Works for any grant source (local L3, org, or a cross-registry credential's grant).
class ActTokenIn(BaseModel):
    act_as: str = Field(..., max_length=160, description="principal to act on behalf of, e.g. agent:did:theprotocol:XXX")


@router.post("/agents/act-token", summary="Create an on-behalf-of (act) agent token for a principal that delegated to you")
async def mint_act_token(
    body: ActTokenIn,
    agent: models.Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    act_as = body.act_as.strip()
    grant = (await db.execute(text(
        "SELECT permissions FROM agent_delegation_grants "
        "WHERE delegate_agent_did = :d AND principal_ref = :p "
        "AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now()) LIMIT 1"
    ), {"d": agent.did, "p": act_as})).first()
    if not grant:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail=f"No live delegation grant from {act_as} to you")
    if act_as.startswith("agent:"):
        # §TWOAGENT G4: a grant from an agent conveys no more than that agent holds NOW at its home. When that is
        # nothing, say why here, instead of minting a token that carries no delegated authority at all.
        from agentvault_registry.services import xreg_issuer_authority as _xia
        if _xia.issuer_check_mode() == "enforce":
            granted = {p for p in (grant.permissions or []) if p in ALL_PERMISSIONS}
            conveyed, outcome = await _xia.clamp_agent_principal(db, agent.did, act_as[len("agent:"):], granted)
            if not conveyed:
                raise HTTPException(status.HTTP_403_FORBIDDEN,
                                    detail=f"This delegation conveys nothing right now: {_xia.refusal_sentence(outcome)}.")
    from datetime import timedelta as _td
    # D6-281: bound to the agent's credential (`cv`) like the token it was asked with: a reset ends both
    token = create_access_token(
        data=agent_token_claims(agent, act={"sub": act_as, "reason": "delegation"}),
        expires_delta=_td(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    effective = sorted(await resolve_agent_permissions(db, agent.did, act_as))
    # Surface any cross-registry credential caveats for this principal so the holder SEES the
    # bounds the issuer attached. (Docstring refresh 2026-07-24: since AGENTFIX/§auditfix the
    # xreg-grant caveats ARE enforced on the spend path — security.py::enforce_agent_spend
    # applies max_per_tx/allowed_currencies from the credential; the att_ capability-token
    # path enforces its caveats there too. This block is display, the gate is real.)
    caveats = None
    if act_as.startswith("agent:"):
        try:
            cav_row = (await db.execute(text(
                "SELECT caveats FROM agent_delegation_credentials "
                "WHERE issuer_did = :iss AND delegate_did = :del AND revoked_at IS NULL "
                "AND caveats IS NOT NULL AND caveats::text <> '{}' "
                "ORDER BY received_at DESC LIMIT 1"
            ), {"iss": act_as[len("agent:"):], "del": agent.did})).first()
            if cav_row and cav_row[0]:
                caveats = cav_row[0]
        except Exception:  # noqa: BLE001 — advisory only, never fail the mint over a caveat read
            caveats = None
    logger.info("[IRONKEY-XREG] act-token minted for %s acting as %s (effective=%s)", agent.did, act_as, effective)
    # §auditfix: the privilege-assumption moment — an agent obtained a token to act AS a
    # principal. Each mint is a distinct event (a fresh bearer credential entered the
    # world), so the idempotency key is a fresh id, not a natural one.
    mint_id = __import__("uuid").uuid4().hex[:16]
    await log_ironkey_action(
        db, action="act_token_mint", actor_type="agent", actor_id=agent.did,
        target_type="principal", target_id=act_as,
        details={"mint_id": mint_id, "effective_permissions": effective,
                 "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                 "caveats": caveats if isinstance(caveats, dict) else None})
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        get_event_emitter().emit_background(
            event_type="AgentActTokenMinted",
            aggregate_id=agent.did,
            data={"agent_did": agent.did, "act_as": act_as, "mint_id": mint_id,
                  "effective_permissions": effective,
                  "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60},
            idempotency_key=f"act-minted-{mint_id}",
        )
    except Exception:  # noqa: BLE001
        logger.debug("[IRONKEY-XREG] AgentActTokenMinted emit skipped", exc_info=True)
    resp = {"access_token": token, "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60, "act_as": act_as,
            "effective_permissions": effective,
            "note": "present this token (Authorization: Bearer) to act with the delegated authority; "
                    "the act claim is attribution — authority comes from the grant, resolved here."}
    if caveats:
        resp["delegation_caveats"] = caveats
        resp["caveats_advisory"] = caveats_advisory()
    return resp
