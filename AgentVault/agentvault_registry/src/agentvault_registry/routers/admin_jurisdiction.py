"""Jurisdiction Profile admin API (SPEC 2026-07-31).

GET/PUT/DELETE the deployment's declared jurisdiction profile. The profile is the
OPERATOR'S declaration of what their law permits; this API stores and attests it,
it does not advise on it. Deny-only downstream (services/jurisdiction.py gates),
so everything here is delta-irrelevant.

Gated per-endpoint on admin_platform (the dependency also yields the acting
developer for the audit row).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException, Request, Security, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models, security
from agentvault_registry.database import get_db
from agentvault_registry.services import jurisdiction
from agentvault_registry.services.admin_audit import log_admin_action
from agentvault_registry.services.exchange_service import set_flag

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/jurisdiction-profile", tags=["Admin - Jurisdiction"])


def _summary(profile: Dict[str, Any] | None) -> Dict[str, Any]:
    if profile is None:
        return {"declared": False, "mode": jurisdiction.mode(), "profile": None}
    return {
        "declared": True,
        "mode": jurisdiction.mode(),
        "profile": profile,
        "features_denied": jurisdiction.features_denied(profile),
        "profile_hash": jurisdiction.profile_hash(profile),
    }


@router.get("")
async def get_jurisdiction_profile(
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    profile = await jurisdiction.get_profile(db, fresh=True)
    return _summary(profile)


@router.put("")
async def put_jurisdiction_profile(
    request: Request,
    profile: Dict[str, Any] = Body(..., description="Jurisdiction profile document (see SPEC 2026-07-31)"),
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    errs = jurisdiction.validate_profile(profile)
    if errs:
        raise HTTPException(status_code=422, detail={"message": "invalid jurisdiction profile", "errors": errs})
    # Server stamps the declaration time; the operator's document controls the rest.
    profile = dict(profile)
    profile["declared_at"] = datetime.now(timezone.utc).isoformat()
    await set_flag(db, jurisdiction.FLAG_KEY, json.dumps(profile, sort_keys=True))
    await db.commit()
    jurisdiction.clear_cache()
    await log_admin_action(
        db,
        action="jurisdiction.profile_declared",
        actor_id=str(getattr(admin, "id", "")),
        actor_ip=(request.client.host if request.client else None),
        target_type="jurisdiction_profile",
        target_id=profile.get("name"),
        severity="warning",  # compliance-posture changes must stand out in the audit trail
        details={
            "version": profile.get("version"),
            "features_denied": jurisdiction.features_denied(profile),
            "profile_hash": jurisdiction.profile_hash(profile),
        },
    )
    logger.warning(
        "[JURISDICTION] profile declared name=%s version=%s denied=%s by dev=%s",
        profile.get("name"), profile.get("version"),
        ",".join(jurisdiction.features_denied(profile)) or "-", getattr(admin, "id", "?"),
    )
    return _summary(profile)


@router.delete("")
async def clear_jurisdiction_profile(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    await set_flag(db, jurisdiction.FLAG_KEY, "")
    await db.commit()
    jurisdiction.clear_cache()
    await log_admin_action(
        db,
        action="jurisdiction.profile_cleared",
        actor_id=str(getattr(admin, "id", "")),
        actor_ip=(request.client.host if request.client else None),
        target_type="jurisdiction_profile",
        severity="warning",
    )
    logger.warning("[JURISDICTION] profile cleared by dev=%s", getattr(admin, "id", "?"))
    return {"declared": False, "mode": jurisdiction.mode(), "profile": None}


# ═══════════════════════════════════════════════════════════════════════════
# REGAUTH (SPEC 2026-08-15) — recorded regulatory authorizations
# ═══════════════════════════════════════════════════════════════════════════

async def _emit_regauth_event(event_type: str, aggregate_id: str, data: Dict[str, Any]) -> None:
    """One implementation lives in the service (§VCSIGN-2: the break-watcher
    emits too); this thin alias keeps the existing call sites."""
    from agentvault_registry.services.regulatory_auth import emit_regauth_event
    await emit_regauth_event(event_type, aggregate_id, data)


@router.get("/authorizations")
async def list_regulatory_authorizations(
    include_revoked: bool = False,
    action: str | None = None,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    from agentvault_registry.services import regulatory_auth
    rows = await regulatory_auth.list_authorizations(
        db, include_revoked=include_revoked, action=action)
    # §VCSIGN: annotate countersigned rows with the contract digest (when the
    # ref is attestation-grade) or the concrete problem (so the panel can show
    # a truthful check / cross instead of a bare string).
    contracts = await regulatory_auth.load_attestation_contracts(
        db, [r.contract_ref for r in rows])
    out = []
    for r in rows:
        a = regulatory_auth.to_admin(r)
        if r.contract_ref:
            c = contracts.get(r.contract_ref)
            problem = regulatory_auth.classify_loaded_attestation_contract(c)
            a["contract_resolves"] = problem is None
            if problem is None:
                a["contract_digest"] = regulatory_auth.contract_attestation_digest(
                    regulatory_auth.contract_attestation_subset(c))
            else:
                a["contract_problem"] = problem
        out.append(a)
    return {
        "authorizations": out,
        "actions": list(regulatory_auth.REG_ACTIONS),
        "display_only_actions": list(regulatory_auth.DISPLAY_ONLY_ACTIONS),
        "mode": jurisdiction.mode(),
    }


@router.get("/attestation-candidates")
async def list_attestation_candidates(
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """§VCSIGN-2: contracts eligible as a countersign (agreed + zero-value) for
    the record form's picker. Read-only; C2's record-time validation stays the
    enforcement — this only kills typos. `referenced` marks contracts already
    backing an ACTIVE authorization."""
    from sqlalchemy import text
    rows = (await db.execute(text("""
        SELECT id, title, contract_type, client_did, provider_did, agreed_at
        FROM contracts
        WHERE status = 'agreed' AND total_amount = 0
        ORDER BY agreed_at DESC NULLS LAST
        LIMIT 100
    """))).mappings().all()
    referenced = {r[0] for r in (await db.execute(text(
        "SELECT DISTINCT contract_ref FROM regulatory_authorizations "
        "WHERE status = 'active' AND contract_ref IS NOT NULL"
    ))).all()}
    return {"candidates": [{
        "id": r["id"],
        "title": r["title"],
        "contract_type": r["contract_type"],
        "client_did": r["client_did"],
        "provider_did": r["provider_did"],
        "agreed_at": r["agreed_at"].isoformat() if r["agreed_at"] else None,
        "referenced": r["id"] in referenced,
    } for r in rows]}


@router.post("/authorizations", status_code=201)
async def record_regulatory_authorization(
    request: Request,
    body: Dict[str, Any] = Body(..., description="Authorization record (action, authority, jurisdiction, reference_id, optional subject_ref/valid_from/valid_until/evidence_hash/evidence_note/contract_ref)"),
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Record ONE regulatory authorization: the operator's attestation that the
    named authority approved the named act, under the given reference id. The
    system never verifies the state's stamp; the attestation is public on the
    signed card, so the liability model is the verification."""
    from agentvault_registry.services import regulatory_auth
    payload = regulatory_auth.validate_record_payload(body)
    # Presence step-up is a BONUS evidence tier in v1: a presented proof is noted
    # but NOT verified here (the liability presence rail is mandate-scoped), so we
    # record honestly rather than claim a verification that did not happen.
    presence_method = "none"
    if request.headers.get("X-Presence-Proof"):
        presence_method = "presented_unverified"
        logger.info("[REGAUTH] X-Presence-Proof presented on record (noted, not verified in v1)")
    row = await regulatory_auth.record_authorization(
        db, payload, recorded_by_dev_id=int(admin.id), presence_method=presence_method)
    await db.commit()
    await log_admin_action(
        db,
        action="jurisdiction.authorization_recorded",
        actor_id=str(getattr(admin, "id", "")),
        actor_ip=(request.client.host if request.client else None),
        target_type="regulatory_authorization",
        target_id=row.id,
        severity="warning",  # compliance-posture changes must stand out in the audit trail
        details={
            "reg_action": row.action,
            "subject_ref": row.subject_ref,
            "authority": row.authority,
            "reference_id": row.reference_id,
        },
    )
    await _emit_regauth_event("RegulatoryAuthorizationRecorded", row.subject_ref or "registry", {
        "authorization_id": row.id,
        "action": row.action,
        "subject_ref": row.subject_ref,
        "authority": row.authority,
        "jurisdiction": row.jurisdiction,
        "reference_id": row.reference_id,
        "valid_until": row.valid_until.isoformat() if row.valid_until else None,
        "evidence_hash": row.evidence_hash,
        "recorded_by_dev_id": row.recorded_by_dev_id,
    })
    logger.warning(
        "[REGAUTH] authorization recorded id=%s action=%s subject=%s authority=%s ref=%s by dev=%s",
        row.id, row.action, row.subject_ref or "-", row.authority, row.reference_id,
        getattr(admin, "id", "?"),
    )
    return {"recorded": True, "authorization": regulatory_auth.to_admin(row)}


@router.post("/authorizations/{auth_id}/revoke")
async def revoke_regulatory_authorization(
    auth_id: str,
    request: Request,
    body: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    reason = (body or {}).get("reason")
    if not isinstance(reason, str) or not (1 <= len(reason.strip()) <= 500):
        raise HTTPException(status_code=422, detail="reason: required string (1-500 chars)")
    from agentvault_registry.services import regulatory_auth
    row = await regulatory_auth.revoke_authorization(db, auth_id, reason=reason.strip())
    await db.commit()
    await log_admin_action(
        db,
        action="jurisdiction.authorization_revoked",
        actor_id=str(getattr(admin, "id", "")),
        actor_ip=(request.client.host if request.client else None),
        target_type="regulatory_authorization",
        target_id=row.id,
        severity="warning",
        details={"reg_action": row.action, "subject_ref": row.subject_ref, "reason": reason.strip()},
    )
    await _emit_regauth_event("RegulatoryAuthorizationRevoked", row.subject_ref or "registry", {
        "authorization_id": row.id,
        "action": row.action,
        "subject_ref": row.subject_ref,
        "reference_id": row.reference_id,
        "reason": reason.strip(),
    })
    logger.warning(
        "[REGAUTH] authorization revoked id=%s action=%s subject=%s reason=%s by dev=%s",
        row.id, row.action, row.subject_ref or "-", reason.strip(), getattr(admin, "id", "?"),
    )
    return {"revoked": True, "authorization": regulatory_auth.to_admin(row)}


# Public read-only proof surface: what the card attests, queryable without auth.
# LIVE authorizations only (active + inside the validity window) — the same set
# the card publishes, so the two can never tell different stories.
public_router = APIRouter(prefix="/api/v1/jurisdiction", tags=["Jurisdiction"])


@public_router.get("/authorizations")
async def public_regulatory_authorizations(db: AsyncSession = Depends(get_db)):
    from agentvault_registry.services import regulatory_auth
    auths = await regulatory_auth.active_card_authorizations(db)
    return {"authorizations": auths, "count": len(auths)}


@public_router.get("/contracts/{cid}")
async def public_attested_contract(cid: str, db: AsyncSession = Depends(get_db)):
    """
    The countersigned attestation contract behind a recorded authorization, with a digest anyone can recompute from
    the response bytes. Keyed by contract id. It resolves only while at least one live authorization references the
    contract (404 otherwise: a proof surface, not a contract browser); a referenced contract that is missing, has a
    non-zero value or is no longer agreed answers 409 with the problem. The title, parties and terms of a referenced
    contract are public by design: countersigning an attestation publishes it.

    \f
    §VCSIGN: the countersigned attestation contract behind a recorded
    authorization, with a digest anyone can recompute from the response bytes.

    Keyed by contract id, NOT reference_id — reference ids contain '/'
    (FCDEMO-2026/EXCH-0001) and would break path routing.

    Fail closed: resolves ONLY while at least one LIVE authorization references
    the contract (404 otherwise — this is a proof surface, not a contract
    browser). A referenced contract that is missing, non-zero-value or no
    longer agreed answers 409 with the concrete problem: an integrity break is
    surfaced, never hidden. NOTE: the title, parties and TERMS of a referenced
    contract are PUBLIC by design — countersigning an attestation publishes it.
    """
    from agentvault_registry.services import regulatory_auth
    refs = await regulatory_auth.live_references_for_contract(db, cid)
    if not refs:
        raise HTTPException(status_code=404, detail="no live authorization references this contract")
    contract, problem = await regulatory_auth.classify_attestation_contract(db, cid)
    if problem is not None:
        detail = {
            "missing": "references a contract that does not exist on this registry",
            "nonzero_value": "references a contract that is not zero-value",
            "not_agreed": (
                "references a contract that is not in the agreed state "
                f"(status={contract.get('status') if contract else '?'})"
            ),
        }[problem]
        raise HTTPException(status_code=409, detail=(
            f"attestation_integrity: a live authorization {detail}. "
            "The countersign cannot currently be verified."
        ))
    subset = regulatory_auth.contract_attestation_subset(contract)
    return {
        "contract": subset,
        "digest": regulatory_auth.contract_attestation_digest(subset),
        "status": contract.get("status"),
        "authorization_references": refs,
    }
