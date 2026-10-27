"""COCKPIT CARD API (L1, 2026-07-25) — /api/v1/liability/*

The liable hybrid identity: a HUMAN developer underwrites ONE agent for a declared scope.
Issue is presence-gated (TOTP now, phone-enclave ES256 when the Pocket key ships), every
authority-relevant event appends to the mandate's evidence hash chain AND the ironkey-style
security_audit_logs feed (prefix `liability.`), and verification re-derives authority from the
CURRENT dev row — never from a snapshot (the issuer-current clamp).

Feature-dark doctrine: 404 unless LIABILITY_MODE ∈ {shadow, enforce} (frame-c first).
Deny-only + pre-escrow → Δ-irrelevant. SPEC: SPEC_2026-07-25_LIABLE_IDENTITY_COCKPIT_CARD.md
"""
import asyncio
import datetime as _dt
import json
import logging
import math
import secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.config import settings
from agentvault_registry.database import get_db
from agentvault_registry.security import get_current_agent, get_current_developer, admin_credential
# §RATEFIX: THE shared, Redis-backed limiter — a router-local Limiter() would give
# every gunicorn worker its own private budget and multiply the cap by 32.
from agentvault_registry.middleware.rate_limiter import shared_limiter as limiter
from agentvault_registry.services import consent_posture as cp
from agentvault_registry.services import liability as liab
from agentvault_registry.services.admin_audit import log_liability_action

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Liability / Cockpit Card"])


def liability_mode() -> str:
    """off | shadow | enforce: the ONE reading of LIABILITY_MODE that the routes' gate and the public registry-config
    (`liability_mode`) share, so the console never asks a route the registry would refuse (§FESUITE, the operator
    batch: an operator chooses what it runs, and the console follows it). Anything else reads as off."""
    mode = (getattr(settings, "LIABILITY_MODE", "off") or "off").strip().lower()
    return mode if mode in ("shadow", "enforce") else "off"


def _require_enabled():
    if liability_mode() == "off":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Liability mandates are not enabled on this registry")


def _require_enabled_for_challenges():
    """§DISCREFINE — the challenge endpoints now serve TWO features.

    Mandate confirms belong to the Cockpit Card and 404 when LIABILITY_MODE is off.
    Step-up confirms (mig 0154, mandate_id NULL) belong to plain account security —
    resetting an agent's credentials — and must work on every registry regardless of
    whether that registry runs liability mandates. Gating them behind LIABILITY_MODE
    would make a second factor available only where a different feature happened to
    be switched on, which is not a defensible reason to weaken account security.
    """
    return None


def _require_enabled_for_device_keys():
    """§FESUITE (2026-10-10, the operator batch) — the device-key routes follow the challenges' doctrine.

    A device key (WebAuthn, user-verified) is what a phone signs with: the Cockpit Card's confirmations, but also the
    phone-approved sign-in (routers/push_login.py verifies against this very row) and Pocket's fingerprint lock
    (usePocketLock enrols through /liability/webauthn/register). Behind LIABILITY_MODE, a registry that does not run
    mandates (a cloud operator that chose not to) could enrol no key, so no phone sign-in and no Pocket lock; and a lost
    phone's key could not be revoked there. Account security does not wait for a different feature to be switched on.
    """
    return None


def _now():
    return _dt.datetime.now(_dt.timezone.utc)


# ---------------------------------------------------------------------------
# §POSTURE (P4) — resolution + the two floors
# ---------------------------------------------------------------------------
async def _posture_for_challenge(db: AsyncSession, ch) -> tuple:
    """(name, bundle, agent_did) for the posture that binds THIS challenge.

    The org is resolved from the challenge's own mandate's agent, through the same
    agent → creator-developer → organization path `effective_liability` walks, so a
    posture and a liability mode can never disagree about which org they belong to.
    A step-up challenge (mandate_id NULL, §DISCREFINE) has no agent and therefore no
    org: the registry posture binds it.
    """
    agent_did = None
    if getattr(ch, "mandate_id", None):
        row = (await db.execute(text(
            "SELECT agent_did FROM liability_mandates WHERE id = :m LIMIT 1"),
            {"m": ch.mandate_id})).first()
        agent_did = row[0] if row else None
    name, b = await cp.for_agent(db, agent_did)
    return name, b, agent_did


async def _has_webauthn_credential(db: AsyncSession, dev_id: int) -> bool:
    """Does this human hold a LIVE WebAuthn credential? Drives `balanced`'s
    "TOTP only while unenrolled" — once a real credential exists, TOTP stops being a
    fallback and becomes a downgrade."""
    row = (await db.execute(text(
        "SELECT 1 FROM device_push_registrations WHERE developer_id = :d "
        "AND webauthn_public_key IS NOT NULL AND key_revoked_at IS NULL LIMIT 1"),
        {"d": dev_id})).first()
    return row is not None


async def _read_floor_clock(db: AsyncSession, ch, b: dict) -> tuple:
    """When did this human demonstrably first have THESE facts? (R9)

    Returns (clock_start, source, preview_id, divergence). `divergence` is the
    field-wise diff of the newest preview for the same action_ref when one exists but
    does NOT match — it is what the desk shows to explain why the clock restarted.

    🔴 The clock is a SERVER timestamp in every branch. R9 named the preview's
    client-asserted `first_presented_at`; §8's law is that the read floor is enforced
    against the server's own clock, and a client-asserted start would make the floor
    advisory (claim you previewed an hour ago, skip it). The preview's `created_at` —
    stamped here when the preview was minted — keeps R9's intent on an attested clock.
    """
    created = ch.created_at
    acked = getattr(ch, "delivery_acked_at", None)
    fallback = acked or created
    fallback_src = "delivery_ack" if acked else "created"

    # `preflight: off` (hardened) means previews grant no credit at all — that is what
    # "every action asks" has to mean, or the dial would be decoration.
    if not b.get("preflight"):
        return fallback, fallback_src, None, None

    digest = liab.facts_comparable_digest(ch.facts or {})
    max_age = int(b.get("preview_credit_max_age_s") or 0)
    rows = (await db.execute(text(
        "SELECT id, facts, facts_digest, created_at FROM consent_previews "
        "WHERE developer_id = :d AND action_ref IS NOT DISTINCT FROM CAST(:r AS VARCHAR) "
        "AND created_at >= now() - make_interval(secs => :age) "
        "ORDER BY created_at ASC LIMIT 25"),
        {"d": ch.developer_id, "r": ch.action_ref, "age": max_age})).mappings().all()
    if not rows:
        return fallback, fallback_src, None, None
    for r in rows:                       # EARLIEST match wins: the first moment they had it
        if r["facts_digest"] == digest:
            start = r["created_at"]
            # A preview that arrived AFTER the ack proves nothing extra; never let a
            # match move the clock forward and make the floor harder than no preview.
            return (start if start < fallback else fallback), "preview", r["id"], None
    newest = rows[-1]
    return fallback, fallback_src, None, liab.facts_diff(newest["facts"], ch.facts or {})


async def _streak_escalated_floor(db: AsyncSession, ch, b: dict):
    """R7 — anti-fatigue with teeth. Diff-first rendering and a badge are
    presentational; nothing CHANGES when a human is plainly auto-piloting. At the
    bundle's streak count the method floor escalates for this action type, so the
    system asks harder exactly when the human is least likely to be reading.
    `None` under `swift` (D3: the default posture keeps it presentational)."""
    at = b.get("streak_method_escalate_at")
    if not at:
        return None, 0
    digest = liab.facts_comparable_digest(ch.facts or {})
    rows = (await db.execute(text(
        "SELECT status, facts FROM liability_challenges "
        "WHERE developer_id = :d AND id <> :c AND status <> 'pending' "
        "ORDER BY created_at DESC LIMIT 25"),
        {"d": ch.developer_id, "c": ch.id})).mappings().all()
    streak = 0
    for r in rows:                       # CONSECUTIVE from the newest; a deny breaks it
        if r["status"] == "approved" and liab.facts_comparable_digest(r["facts"] or {}) == digest:
            streak += 1
        else:
            break
    return ("webauthn_uv" if streak >= int(at) else None), streak


def _posture_ttl(b: dict) -> int:
    """TTL for a new challenge: the bundle's, floored by an operator env if one is SET.

    🔴 AN UNSET ENV IS NOT AN OPERATOR DECISION. This used to read
    `min(bundle, getattr(settings, ..., 120))`, and the 120 in that default silently
    clamped every value above it — so D4's humane TTLs (900/600/300) and every org
    override were quietly capped back to two minutes. Measured by the P7 battery: the
    org asked for 2400 s and the minted row got 120.
    The operator lever still works and is still tighten-only; it just has to be
    EXPLICITLY present in the environment to count as an opinion.
    """
    import os as _os
    ttl = int(b.get("challenge_ttl_seconds") or 900)
    raw = _os.environ.get("LIABILITY_CHALLENGE_TTL_SECONDS")
    if raw:
        try:
            ttl = min(ttl, int(raw))
        except ValueError:
            pass
    return max(1, ttl)


# ---------------------------------------------------------------------------
# §SHOWN — the typed cue
# ---------------------------------------------------------------------------
# 🔴 THE TYPE IS NOT `notification`, and that is load-bearing. Notification prefs and
# quiet hours filter on that type, so a muted developer would stop being told that
# something is waiting on their signature — the §SUPPORTBATCH1 law, where
# `support.ticket` was given its own type for exactly this reason. A cue carries no
# words for a human; it is an instruction to re-read a list.
#
# ⚠ `ws_manager.send_personal_message` is a PER-WORKER dict: on a 38-worker registry
# it lands only if the recipient's socket happens to live on the handling worker.
# `broadcast(audience="user_<id>")` publishes through Redis so every worker's listener
# delivers. That distinction cost §SUPPORTBATCH1 a real, invisible delivery bug.
#
# Best-effort and POST-COMMIT, like `_push_challenge`: a cue that arrives before the
# row it names is worse than a cue that never arrives.
async def _cue(dev_id: int, cue_type: str, payload: dict) -> None:
    try:
        from agentvault_registry.routers.websocket import manager as _ws
        await _ws.broadcast({"type": cue_type, **payload}, audience=f"user_{dev_id}")
    except Exception:  # noqa: BLE001 — never let a cue break the transaction it follows
        logger.debug("[LIABILITY] cue %s for dev %s not delivered", cue_type, dev_id, exc_info=True)


async def _push_challenge(dev_id: int, ch_id: str, action_type: str):
    """Best-effort banking-app push over the EXISTING Pocket rail. Never blocks the request."""
    try:
        # §NOTIFV2: security.liability_challenge is MANDATORY in the catalog — this is
        # the one push the underwriting human must never miss (it IS the thing they sign).
        from agentvault_registry.background_tasks.push_notify import notify
        # BASE_URL is a pydantic Url, not a str — str() it or .rstrip() raises AttributeError
        base = str(getattr(settings, "PUSH_APP_BASE_URL", "") or getattr(settings, "BASE_URL", "") or "").rstrip("/")
        await notify("security.liability_challenge", [dev_id], title="Confirm action — Cockpit Card",
                     message=f"Approve {action_type} ({ch_id[:12]}…) in your Cockpit",
                     tags="closed_lock_with_key", priority="high",
                     click=f"{base}/ui/#/pocket/approvals" if base else None)
    except Exception:
        logger.debug("[LIABILITY] push notify skipped", exc_info=True)


# ---------------------------------------------------------------------------
# Schemas (inline, guild-style)
# ---------------------------------------------------------------------------
class MandateCreateIn(BaseModel):
    agent_did: str = Field(min_length=8, max_length=255)
    scope: List[str] = Field(min_length=1, max_length=32)
    limits: Optional[Dict[str, Any]] = None          # {max_per_tx, currency, budget, ...} — clamp, not grant
    tier: str = Field(default="T1", pattern="^T[0-2]$")
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=365)
    totp_code: str = Field(min_length=6, max_length=8)


class MandateRevokeIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=255)


class ChallengeCreateIn(BaseModel):
    mandate_id: str
    action_type: str = Field(min_length=3, max_length=48)
    action_ref: Optional[str] = Field(default=None, max_length=128)
    facts: Dict[str, Any] = Field(default_factory=dict)


class ChallengeApproveIn(BaseModel):
    totp_code: Optional[str] = Field(default=None, min_length=6, max_length=8)
    device_id: Optional[int] = None
    # WEBAUTHN assertion (the biometric-enforced path). The OS will not produce these without
    # user verification, and the UV bit inside authenticator_data proves it happened.
    credential_id: Optional[str] = None
    authenticator_data: Optional[str] = None
    client_data_json: Optional[str] = None
    signature: Optional[str] = None


class KeyEnrollIn(BaseModel):
    pubkey_jwk: Dict[str, Any]
    attestation: Optional[Dict[str, Any]] = None


class WebAuthnRegisterIn(BaseModel):
    attestation_object: str
    client_data_json: str


def _host_of(url: Any) -> Optional[str]:
    from urllib.parse import urlparse
    try:
        return urlparse(str(url or "")).hostname or None
    except Exception:
        return None


def _rp_id_candidates(request: Optional[Request] = None) -> List[str]:
    """Every hostname this deployment legitimately serves the app from.

    The Relying Party ID is the app origin's HOST, hashed into every signature. One registry is
    reachable at several names (registry./api./theprotocol.cloud here) and the browser bakes in
    whichever one the user is actually on — so a credential enrolled at api. would fail forever
    against a hardcoded registry. (The Commander hit exactly this origin split when a push
    notification opened api. while the app had been installed from registry.)

    The list is built from CONFIGURATION, never from the request alone: an attacker-supplied Host
    header cannot widen it. Loopback is allowed so a local browser (and the E2E harness) works.
    """
    out: List[str] = []
    def add(h: Optional[str]):
        if h and h not in out:
            out.append(h)

    add(_host_of(getattr(settings, "PUSH_APP_BASE_URL", "")))
    add(_host_of(getattr(settings, "BASE_URL", "")))
    for origin in (getattr(settings, "ALLOWED_ORIGINS", None) or []):
        add(_host_of(origin))
    if request is not None:
        rh = (request.url.hostname or "").lower()
        if rh in ("localhost", "127.0.0.1", "::1") or rh in out:
            add(rh)
    if not out:
        add("localhost")
    return out


def _rp_id(request: Optional[Request] = None) -> str:
    """The RP ID to hand the browser at enrolment: the origin it is actually on when that is one
    of ours (the browser rejects anything else), otherwise the configured default."""
    cands = _rp_id_candidates(request)
    if request is not None:
        rh = (request.url.hostname or "").lower()
        if rh in cands:
            return rh
    return cands[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _load_mandate(db: AsyncSession, mid: str) -> models.LiabilityMandate:
    m = await db.get(models.LiabilityMandate, mid)
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Mandate not found")
    return m


def _mandate_out(m: models.LiabilityMandate, resolved: Optional[dict] = None) -> dict:
    out = {
        "id": m.id, "developer_id": m.developer_id, "agent_did": m.agent_did, "tier": m.tier,
        "scope": m.scope, "limits": m.limits, "status": m.status,
        "presence_method": m.presence_method, "authority_snapshot": m.authority_snapshot,
        "content_hash": m.content_hash, "registry_id": m.registry_id,
        "issued_at": m.issued_at, "expires_at": m.expires_at,
        "revoked_at": m.revoked_at, "revoked_reason": m.revoked_reason,
    }
    if resolved is not None:
        out["resolved"] = resolved
    return out


async def _agent_ceiling(db: AsyncSession, agent_did: str) -> Optional[list]:
    """Best-effort IRONKEY ceiling snapshot for the audit record (never authority)."""
    try:
        from agentvault_registry.agent_authz import resolve_agent_permissions
        perms = await resolve_agent_permissions(db, agent_did)
        return sorted(perms) if perms else []
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Discovery: what may I underwrite?
# ---------------------------------------------------------------------------
@router.get("/api/v1/liability/delegatable", summary="What the caller's dev-RBAC may underwrite")
async def get_delegatable(dev: models.Developer = Depends(get_current_developer),
                          db: AsyncSession = Depends(get_db)):
    _require_enabled()
    flags, reasons = liab.dev_authority_now(dev)
    return {
        "authority_now": sorted(flags), "reasons": reasons,
        "delegatable": sorted(liab.delegatable_for(flags)),
        "base": sorted(liab.DELEGATABLE_BASE),
        "non_delegatable": sorted(liab.NON_DELEGATABLE),
        "mode": (settings.LIABILITY_MODE or "off").lower(),
        "presence": {"totp_enrolled": bool(dev.totp_secret)},
    }


# ---------------------------------------------------------------------------
# Mandates
# ---------------------------------------------------------------------------
@router.post("/api/v1/liability/mandates", status_code=status.HTTP_201_CREATED,
             summary="Issue a Cockpit Card mandate (presence-gated)")
async def create_mandate(body: MandateCreateIn,
                         dev: models.Developer = Depends(get_current_developer),
                         db: AsyncSession = Depends(get_db)):
    _require_enabled()
    if getattr(settings, "LIABILITY_ISSUE_ORG_ADMIN_ONLY", False) and not admin_credential(dev):   # §POCKETPAIR
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Mandate issuance restricted to admins on this registry")

    # 1) Live authority — a suspended/deleted human can underwrite nothing.
    flags, reasons = liab.dev_authority_now(dev)
    if reasons:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f"Developer cannot issue mandates: {','.join(reasons)}")

    # 2) Scope ⊆ what the human actually holds — never store a lie.
    offenders = liab.validate_scope(body.scope, flags)
    if offenders:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={"error": "scope_exceeds_authority", "offending": offenders,
                                    "delegatable": sorted(liab.delegatable_for(flags))})

    # 3) Presence precondition first (cheapest honest answer): the human proves they are HERE,
    #    now (TOTP floor; enclave lands with Pocket).
    if not dev.totp_secret:
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED,
                            detail="2FA (TOTP) enrolment is required before issuing a liability mandate")
    if not liab.verify_totp_for_dev(dev, body.totp_code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Presence check failed (invalid TOTP)")

    # 4) The agent must exist and (self-service default) belong to the issuing human.
    agent = (await db.execute(text(
        "SELECT did, creator_developer_id FROM agents WHERE did = CAST(:d AS VARCHAR) LIMIT 1"
    ), {"d": body.agent_did})).first()
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent not found on this registry")
    if agent[1] != dev.id and not admin_credential(dev):   # §POCKETPAIR
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You can only underwrite your own agents")

    mid = liab.new_id("lm")
    now = _now()
    expires_at = (now + _dt.timedelta(days=body.expires_in_days)) if body.expires_in_days else None
    snapshot = {
        "dev_flags": sorted(flags),
        "agent_ceiling": await _agent_ceiling(db, body.agent_did),
        "delegatable_at_issue": sorted(liab.delegatable_for(flags)),
    }
    chash = liab.mandate_content_hash(
        mandate_id=mid, developer_id=dev.id, agent_did=body.agent_did, tier=body.tier,
        scope=body.scope, limits=body.limits, authority_snapshot=snapshot,
        presence_method="totp", issued_at=now.isoformat(),
        expires_at=expires_at.isoformat() if expires_at else None)

    m = models.LiabilityMandate(
        id=mid, developer_id=dev.id, agent_did=body.agent_did, tier=body.tier,
        scope=sorted(set(body.scope)), limits=body.limits, status="signed",
        presence_method="totp", authority_snapshot=snapshot, content_hash=chash,
        registry_id=getattr(settings, "REGISTRY_ID", None) or None,
        issued_at=now, expires_at=expires_at)
    db.add(m)
    await db.flush()
    ev = await liab.append_evidence(
        db, mid, "issued",
        {"scope": sorted(set(body.scope)), "limits": body.limits or {}, "tier": body.tier,
         "content_hash": chash, "expires_at": expires_at.isoformat() if expires_at else None},
        authority_snapshot=snapshot, presence={"method": "totp"})
    await log_liability_action(db, action="mandate_issued", actor_type="dev",
                             actor_id=str(dev.id), target_type="liability_mandate", target_id=mid,
                             details={"agent_did": body.agent_did, "scope": sorted(set(body.scope)),
                                      "tier": body.tier, "presence": "totp"})
    await db.commit()
    return {**_mandate_out(m), "evidence_head": ev}


@router.get("/api/v1/liability/mandates/mine", summary="My mandates (as the liable human)")
async def my_mandates(dev: models.Developer = Depends(get_current_developer),
                      db: AsyncSession = Depends(get_db)):
    _require_enabled()
    rows = (await db.execute(text(
        "SELECT id FROM liability_mandates WHERE developer_id = :d ORDER BY issued_at DESC LIMIT 200"
    ), {"d": dev.id})).scalars().all()
    out = []
    for mid in rows:
        m = await db.get(models.LiabilityMandate, mid)
        out.append(_mandate_out(m, await liab.resolve_mandate(db, m, dev)))
    return {"mandates": out, "count": len(out)}


@router.get("/api/v1/liability/mandates/{mid}", summary="Mandate detail + evidence chain")
async def get_mandate(mid: str, dev: models.Developer = Depends(get_current_developer),
                      db: AsyncSession = Depends(get_db)):
    _require_enabled()
    m = await _load_mandate(db, mid)
    if m.developer_id != dev.id and not admin_credential(dev):   # §POCKETPAIR
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your mandate")
    issuer = dev if m.developer_id == dev.id else await db.get(models.Developer, m.developer_id)
    resolved = await liab.resolve_mandate(db, m, issuer)
    chain_ok, break_at = await liab.verify_chain(db, mid)
    evidence = (await db.execute(text("""
        SELECT seq, event_type, action_ref, payload, authority_snapshot, presence,
               digest, prev_hash, chain_hash, created_at
        FROM liability_evidence WHERE mandate_id = :m ORDER BY seq ASC
    """), {"m": mid})).mappings().all()
    return {**_mandate_out(m, resolved), "chain_ok": chain_ok, "chain_break_at": break_at,
            "evidence": [dict(e) for e in evidence]}


@router.post("/api/v1/liability/mandates/{mid}/revoke", summary="Revoke a mandate (instant clamp)")
async def revoke_mandate(mid: str, body: MandateRevokeIn,
                         dev: models.Developer = Depends(get_current_developer),
                         db: AsyncSession = Depends(get_db)):
    _require_enabled()
    m = await _load_mandate(db, mid)
    if m.developer_id != dev.id and not admin_credential(dev):   # §POCKETPAIR
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your mandate")
    if m.status == "revoked":
        return {"ok": True, "id": mid, "status": "revoked", "idempotent": True}
    claimed = await db.execute(text(
        "UPDATE liability_mandates SET status='revoked', revoked_at=now(), revoked_reason=:r "
        "WHERE id=:m AND status='signed'"), {"m": mid, "r": body.reason})
    if getattr(claimed, "rowcount", 0) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Mandate is {m.status}, not signed")
    await liab.append_evidence(db, mid, "revoked",
                               {"reason": body.reason, "by": "admin" if m.developer_id != dev.id else "issuer"})
    await log_liability_action(db, action="mandate_revoked", actor_type="dev",
                             actor_id=str(dev.id), target_type="liability_mandate", target_id=mid,
                             severity="warning", details={"reason": body.reason})
    await db.commit()
    return {"ok": True, "id": mid, "status": "revoked"}


@router.post("/api/v1/liability/mandates/{mid}/verify",
             summary="PUBLIC verify: re-derive what this card conveys right now")
async def verify_mandate(mid: str, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    m = await _load_mandate(db, mid)
    issuer = await db.get(models.Developer, m.developer_id)
    resolved = await liab.resolve_mandate(db, m, issuer)
    chain_ok, break_at = await liab.verify_chain(db, mid)
    if not chain_ok:
        resolved["valid"] = False
        resolved["reasons"] = list(resolved.get("reasons", [])) + ["evidence_chain_broken"]
    return {"id": mid, "agent_did": m.agent_did, "tier": m.tier, "status": m.status,
            "content_hash": m.content_hash, "chain_ok": chain_ok, "chain_break_at": break_at,
            **resolved}


# ---------------------------------------------------------------------------
# Challenges — the banking-app confirm rail
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# §CEILING (P7) — standing consent: "stop asking me about this shape"
# ---------------------------------------------------------------------------
CEILING_RAISE_VERB = "cockpit.ceiling_raise"


class CeilingIn(BaseModel):
    """A standing consent. `max_per_tx` 0 (or omitted) removes it."""
    scope: str = Field(min_length=3, max_length=48)
    max_per_tx: str = Field(description="decimal string — the most this may cover per action")
    currency: str = Field(min_length=2, max_length=12)
    hours: Optional[int] = Field(default=None, ge=1, le=720,
                                 description="how long before it decays; defaults to the posture's")


async def _org_settings_for_mandate(db: AsyncSession, m) -> dict:
    """The mandate's agent's organization settings. A read that fails answers 503 (OrgSettingsUnavailable): it used
    to read as no organization, which allowed a standing consent the organization forbids or caps (§SECFIX D6-491)."""
    from agentvault_registry.services import org_policy as _op
    return await _op.get_org_settings(db, m.agent_did) or {}


def _ceiling_view(m) -> Optional[dict]:
    c = liab.ceiling_of(getattr(m, "limits", None))
    if not c:
        return None
    covered, why = liab.ceiling_covers(getattr(m, "limits", None), needed=c.get("scope") or "",
                                       amount=c.get("max_per_tx"), currency=c.get("currency"))
    # `live` is re-derived, never stored: a decayed ceiling is ignored at READ time, so
    # the pane must render decay from the same evaluation the gate makes rather than
    # from a flag somebody remembered to flip.
    return {**c, "live": covered, "state": why}


@router.get("/api/v1/liability/mandates/{mid}/ceiling", summary="The standing consent on this mandate")
async def get_ceiling(mid: str, dev: models.Developer = Depends(get_current_developer),
                      db: AsyncSession = Depends(get_db)):
    _require_enabled()
    m = await _load_mandate(db, mid)
    if m.developer_id != dev.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your mandate")
    pname, pb, _ = await _posture_for_challenge(db, type("_", (), {"mandate_id": mid})())
    org = await _org_settings_for_mandate(db, m)
    return {"mandate_id": mid, "ceiling": _ceiling_view(m), "posture": pname,
            "ceilings_allowed": bool(pb.get("ceilings")) and org.get("cockpit_ceilings_enabled") is not False,
            "decay_hours_default": pb.get("ceiling_decay_hours"),
            "org_max_amount": org.get("cockpit_ceiling_max_amount")}


@router.post("/api/v1/liability/mandates/{mid}/ceiling", status_code=status.HTTP_201_CREATED,
             summary="Ask to RAISE a standing consent (creates a confirm; webauthn only)")
async def raise_ceiling(mid: str, body: CeilingIn,
                        dev: models.Developer = Depends(get_current_developer),
                        db: AsyncSession = Depends(get_db)):
    """Granting or widening standing consent is itself a decision, and the strongest one
    the cockpit makes: it is the moment a human stops being asked. So it goes through the
    same challenge rail as everything else and, unlike everything else, it accepts ONLY
    `webauthn_uv` in EVERY posture: **the strongest path guards its own dials**.
    There is deliberately no pre-flight for it either: a raise is never announced by an
    agent, so there is nothing to have pre-read.
    """
    _require_enabled()
    m = await _load_mandate(db, mid)
    if m.developer_id != dev.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your mandate")
    if m.status != "signed":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Mandate is {m.status}")

    pname, pb, _ = await _posture_for_challenge(db, type("_", (), {"mandate_id": mid})())
    if not pb.get("ceilings"):
        # §8: `hardened` means every action asks. Refusing here NAMES the posture, so an
        # org admin learns which dial did it instead of finding an endpoint that "does
        # not work".
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={
            "error": "ceilings_disabled_by_posture", "posture": pname,
            "remedy": "this posture asks for every action; standing consent is not available under it"})
    org = await _org_settings_for_mandate(db, m)
    if org.get("cockpit_ceilings_enabled") is False:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={
            "error": "ceilings_disabled_by_org",
            "remedy": "this organization does not allow standing consent for its agents"})

    from decimal import Decimal as _D, InvalidOperation as _I
    try:
        want = _D(str(body.max_per_tx))
    except (_I, TypeError, ValueError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="max_per_tx must be numeric")
    if want <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail={
            "error": "use_the_tighten_rail",
            "remedy": "removing or lowering a standing consent needs no confirmation — "
                      f"PUT /api/v1/liability/mandates/{mid}/ceiling (I7)"})
    # D7 — the org caps the ceiling. Refused at GRANT as well as clamped at USE, because
    # being told now is better than discovering later that half of what you signed for
    # never applied.
    org_cap = org.get("cockpit_ceiling_max_amount")
    if org_cap not in (None, "", 0, "0"):
        try:
            if want > _D(str(org_cap)):
                raise HTTPException(status.HTTP_403_FORBIDDEN, detail={
                    "error": "above_org_ceiling_cap", "org_max_amount": str(org_cap),
                    "requested": str(want),
                    "remedy": "your organization caps how much any one person may pre-authorise"})
        except (_I, TypeError, ValueError):
            pass

    hours = int(body.hours or pb.get("ceiling_decay_hours") or 24)
    lo, hi = 1, 720
    hours = max(lo, min(hi, hours))
    decays = _now() + _dt.timedelta(hours=hours)
    new_ceiling = {"scope": body.scope, "max_per_tx": str(want), "currency": body.currency.upper(),
                   "granted_at": None, "decays_at": decays.isoformat(), "granted_by_decision": None}
    old = liab.ceiling_of(m.limits) or None

    facts, err = liab.build_facts_v2(
        verb=CEILING_RAISE_VERB, action_ref=f"ceiling:{mid}", mandate_id=mid, agent_did=m.agent_did,
        amount=want, currency=body.currency.upper(), counterparty_did=None,
        auto_stepped_up=False,
        # The human is being asked to stop being asked. The OLD state rides along because
        # "raise it to 50" and "raise it from 5 to 50" are different questions.
        extra={"ceiling_scope": body.scope, "ceiling_hours": hours,
               "ceiling_old": old, "ceiling_new": new_ceiling})
    if facts is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"error": err})

    nonce = secrets.token_hex(16)
    chid = liab.new_id("lch")
    ttl = _posture_ttl(pb)
    ch = models.LiabilityChallenge(
        id=chid, mandate_id=mid, developer_id=dev.id, action_type=CEILING_RAISE_VERB,
        action_ref=f"ceiling:{mid}", facts=facts, nonce=nonce,
        challenge_hash=liab.challenge_hash_for(facts, nonce), status="pending",
        expires_at=_now() + _dt.timedelta(seconds=ttl))
    db.add(ch)
    await db.flush()
    await liab.append_evidence(db, mid, "ceiling_requested",
                               {"challenge_id": chid, "old": old, "new": new_ceiling,
                                "posture": pname, "method_floor": "webauthn_uv"},
                               action_ref=f"ceiling:{mid}")
    await db.commit()
    asyncio.create_task(_cue(dev.id, "liability.cue", {
        "challenge_id": chid, "action_type": CEILING_RAISE_VERB, "action_ref": f"ceiling:{mid}"}))
    return {"id": chid, "mandate_id": mid, "facts": facts, "expires_at": ch.expires_at,
            "method_floor": "webauthn_uv",
            "note": "a raise is signed with an enrolled device in every posture — the strongest "
                    "path guards its own dials"}


@router.put("/api/v1/liability/mandates/{mid}/ceiling",
            summary="Lower or remove a standing consent (instant, no confirmation)")
async def tighten_ceiling(mid: str, body: Optional[CeilingIn] = None,
                          dev: models.Developer = Depends(get_current_developer),
                          db: AsyncSession = Depends(get_db)):
    """
    Tightening is never gated. Removing or shrinking standing consent can only remove authority, so it takes no
    signature, no floor and no posture check: stopping to trust must never be harder than starting. An empty body
    removes the ceiling entirely.
    """
    _require_enabled()
    m = await _load_mandate(db, mid)
    if m.developer_id != dev.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your mandate")
    old = liab.ceiling_of(m.limits) or None
    limits = dict(m.limits or {})
    from decimal import Decimal as _D, InvalidOperation as _I

    if body is None or not str(body.max_per_tx or "").strip() or str(body.max_per_tx).strip() in ("0", "0.0"):
        limits.pop("auto_ceiling", None)
        new = None
    else:
        if not old:
            raise HTTPException(status.HTTP_409_CONFLICT, detail={
                "error": "no_ceiling_to_tighten",
                "remedy": f"granting one is a decision — POST /api/v1/liability/mandates/{mid}/ceiling"})
        try:
            want, have = _D(str(body.max_per_tx)), _D(str(old.get("max_per_tx") or 0))
        except (_I, TypeError, ValueError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="max_per_tx must be numeric")
        if want > have:
            # The whole point of this rail is that it can only remove. Routing a RAISE
            # through it would be a confirmation-free widening, which is the one thing
            # the challenge rail exists to prevent.
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail={
                "error": "raise_needs_a_decision", "current": str(have), "requested": str(want),
                "remedy": f"POST /api/v1/liability/mandates/{mid}/ceiling and sign for it"})
        new = {**old, "max_per_tx": str(want)}
        limits["auto_ceiling"] = new

    # `limits` is JSONB on an ORM attribute: a SHALLOW copy shares the inner dicts, the
    # flush comparator sees old == new, and NO UPDATE is emitted (§POCKETBRIDGE3).
    await db.execute(text("UPDATE liability_mandates SET limits = CAST(:l AS JSONB) WHERE id = :m"),
                     {"l": json.dumps(limits), "m": mid})
    await liab.append_evidence(db, mid, "ceiling_tightened", {"old": old, "new": new},
                               action_ref=f"ceiling:{mid}")
    await log_liability_action(db, action="ceiling_tightened", actor_type="dev", actor_id=str(dev.id),
                               target_type="liability_mandate", target_id=mid,
                               details={"old": old, "new": new})
    await db.commit()
    asyncio.create_task(_cue(dev.id, "liability.resolved", {"mandate_id": mid, "ceiling": new}))
    return {"mandate_id": mid, "ceiling": new, "removed": new is None}


@router.post("/api/v1/liability/challenges", status_code=status.HTTP_201_CREATED,
             summary="Create a presence challenge for a high-value action")
async def create_challenge(body: ChallengeCreateIn,
                           dev: models.Developer = Depends(get_current_developer),
                           db: AsyncSession = Depends(get_db)):
    _require_enabled()
    m = await _load_mandate(db, body.mandate_id)
    if m.developer_id != dev.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your mandate")
    if m.status != "signed":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Mandate is {m.status}")
    # Server-canonical facts only: what the phone renders IS what gets signed.
    # §FACTS2 — through the SAME builder the gate uses, so a hand-minted challenge and
    # an auto-stepped one are the same shape. The caller may supply amount/currency/
    # counterparty in `facts`; I11 then applies to them too, which is the point: a
    # money challenge minted by hand is no more entitled to omit its unit than one
    # minted by the gate.
    _sup = dict(body.facts or {})
    _amt = _sup.pop("amount", None)
    if _amt is not None:
        # VALIDATE numerically, then hand on the ORIGINAL. Converting to float here
        # would undo `money_str` one layer up: "42.50" became 42.5 became "42.5", so
        # the desk rendered a different number from the one the caller declared.
        from decimal import Decimal as _Dec, InvalidOperation as _IOp
        try:
            _Dec(str(_amt))
        except (_IOp, TypeError, ValueError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="facts.amount must be numeric")
    facts, _err = liab.build_facts_v2(
        verb=body.action_type, action_ref=body.action_ref, mandate_id=m.id,
        agent_did=m.agent_did, amount=_amt,
        currency=_sup.pop("currency", None),
        counterparty_did=_sup.pop("counterparty_did", liab._UNSET if _amt is not None else None),
        counterparty_home_registry=_sup.pop("counterparty_home_registry", None),
        auto_stepped_up=False, extra=_sup)
    if facts is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail={
            "error": _err,
            "hint": ("a challenge carrying an amount must also declare `currency` and "
                     "`counterparty_did` (use null when the action genuinely has no "
                     "counterparty yet) — an amount with no unit is not signable"),
        })
    nonce = secrets.token_hex(16)
    chid = liab.new_id("lch")
    _pname, _pb = await cp.for_agent(db, m.agent_did)
    ttl = _posture_ttl(_pb)
    ch = models.LiabilityChallenge(
        id=chid, mandate_id=m.id, developer_id=dev.id, action_type=body.action_type,
        action_ref=body.action_ref, facts=facts, nonce=nonce,
        challenge_hash=liab.challenge_hash_for(facts, nonce), status="pending",
        expires_at=_now() + _dt.timedelta(seconds=ttl))
    db.add(ch)
    await db.flush()
    await liab.append_evidence(db, m.id, "challenge_created",
                               {"challenge_id": chid, "action_type": body.action_type,
                                "challenge_hash": ch.challenge_hash, "ttl_seconds": ttl},
                               action_ref=body.action_ref)
    await db.commit()
    asyncio.create_task(_push_challenge(dev.id, chid, body.action_type))
    asyncio.create_task(_cue(dev.id, "liability.cue", {
        "challenge_id": chid, "action_type": body.action_type, "action_ref": body.action_ref}))
    return {"id": chid, "mandate_id": m.id, "challenge_hash": ch.challenge_hash,
            "facts": facts, "expires_at": ch.expires_at, "ttl_seconds": ttl}


class PreviewCreateIn(BaseModel):
    """A PRE-FLIGHT preview: "here is what I am about to be asked to underwrite."

    Same field shape as `ChallengeCreateIn` on purpose — the preview is built through
    the SAME `build_facts_v2`, so "did the human already read these facts" is a digest
    comparison rather than a second, drifting notion of sameness.
    """
    mandate_id: str
    action_type: str = Field(min_length=3, max_length=48)
    action_ref: Optional[str] = Field(default=None, max_length=128)
    facts: Dict[str, Any] = Field(default_factory=dict)
    # CLIENT-ASSERTED, stored and labelled, never used to decide a refusal (R5).
    first_presented_at: Optional[_dt.datetime] = None
    presentation_hash: Optional[str] = Field(default=None, pattern="^[0-9a-f]{64}$")
    render_version: Optional[str] = Field(default=None, max_length=64)
    locale: Optional[str] = Field(default=None, max_length=16)


@router.post("/api/v1/liability/previews", status_code=status.HTTP_201_CREATED,
             summary="Pre-flight: record that these facts were shown before any ask exists")
async def create_preview(body: PreviewCreateIn,
                         dev: models.Developer = Depends(get_current_developer),
                         db: AsyncSession = Depends(get_db)):
    """
    Record that these facts were shown to the human before any ask exists (the pre-flight). A later challenge whose
    facts match a preview can be consented at once; a divergent one cannot. Creating a preview moves nothing and
    grants nothing by itself.

    \f
    P4 ships the RAIL; P8 owns the intent UX that drives it.

    It exists here because the read floor's R9 rule is unverifiable without it: a
    battery cannot show that a matching preview grants immediate consent, and a
    divergent one does not, unless previews can be made. Minting one is Δ-irrelevant
    and grants nothing by itself — it only ever starts a clock that a later challenge
    may or may not match.
    """
    _require_enabled()
    m = await _load_mandate(db, body.mandate_id)
    if m.developer_id != dev.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your mandate")
    if m.status != "signed":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Mandate is {m.status}")

    _sup = dict(body.facts or {})
    _amt = _sup.pop("amount", None)
    if _amt is not None:
        from decimal import Decimal as _Dec, InvalidOperation as _IOp
        try:
            _Dec(str(_amt))
        except (_IOp, TypeError, ValueError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="facts.amount must be numeric")
    facts, _err = liab.build_facts_v2(
        verb=body.action_type, action_ref=body.action_ref, mandate_id=m.id,
        agent_did=m.agent_did, amount=_amt,
        currency=_sup.pop("currency", None),
        counterparty_did=_sup.pop("counterparty_did", liab._UNSET if _amt is not None else None),
        counterparty_home_registry=_sup.pop("counterparty_home_registry", None),
        auto_stepped_up=False, extra=_sup)
    if facts is None:
        # I11 applies here for the same reason it applies to a challenge: a preview
        # that cannot name its unit would grant read-credit for a fact nobody could
        # have read honestly.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail={
            "error": _err,
            "hint": ("a preview carrying an amount must also declare `currency` and "
                     "`counterparty_did` (null when the action genuinely has none)"),
        })
    digest = liab.facts_comparable_digest(facts)
    row = (await db.execute(text(
        "INSERT INTO consent_previews (developer_id, mandate_id, verb, action_ref, facts, "
        "facts_digest, first_presented_at, presentation_hash, render_version, locale) "
        "VALUES (:d, :m, :v, :r, CAST(:f AS JSONB), :dg, :fp, :ph, :rv, :lo) "
        "RETURNING id, created_at"),
        {"d": dev.id, "m": m.id, "v": body.action_type, "r": body.action_ref,
         "f": json.dumps(facts), "dg": digest, "fp": body.first_presented_at,
         "ph": body.presentation_hash, "rv": body.render_version,
         "lo": body.locale})).mappings().first()
    await db.commit()
    pname, pb = await cp.for_agent(db, m.agent_did)
    age = int(pb.get("preview_credit_max_age_s") or 0)
    return {
        "id": row["id"], "mandate_id": m.id, "facts": facts, "facts_digest": digest,
        # SERVER-attested: this is the clock a later read floor will actually use.
        "created_at": row["created_at"],
        "posture": pname,
        "read_floor_ms": int(pb.get("read_floor_ms") or 0),
        "credit_seconds": age if pb.get("preflight") else 0,
        "trust": {"created_at": "attested",
                  "first_presented_at": "client_asserted",
                  "presentation_hash": "client_asserted"},
    }


@router.get("/api/v1/liability/posture", summary="Which consent posture binds me here")
async def get_posture(agent_did: Optional[str] = None,
                      dev: models.Developer = Depends(get_current_developer),
                      db: AsyncSession = Depends(get_db)):
    """
    The consent posture in force for the caller (or for `agent_did`), so the client can show it rather than learn it
    by being refused; the server enforces it. Read-only; the registry floor is reported beside the effective value
    so an organization admin can see which one binds.

    \f
    The dials in force, so the desk can WEAR the posture rather than discover it
    by being refused (§8: "the client renders the posture in force; the server
    enforces it"). Read-only; the registry floor is reported beside the effective
    value so an org admin can see which one is binding.
    """
    _require_enabled()
    reg = cp.registry_posture()
    name, b = await cp.for_agent(db, agent_did)
    return {
        "posture": name,
        "registry_posture": reg,
        "source": "organization" if name != reg else "registry",
        "agent_did": agent_did,
        "dials": {k: b.get(k) for k in (
            "method_floor", "method_preferred", "totp_only_while_unenrolled",
            "read_floor_ms", "challenge_ttl_seconds", "preflight",
            "preview_credit_max_age_s", "presence_gated_raise", "device_render",
            "ceilings", "ceiling_decay_hours", "four_eyes", "overflow",
            "streak_badge_at", "streak_method_escalate_at", "streak_propose_ceiling_at",
            "quiet_hours")},
        "effective_challenge_ttl_seconds": _posture_ttl(b),
        "order": list(cp.ORDER),
    }


@router.get("/api/v1/liability/challenges/pending", summary="My pending confirms")
async def pending_challenges(dev: models.Developer = Depends(get_current_developer),
                             db: AsyncSession = Depends(get_db)):
    # Serves BOTH mandate confirms and step-up confirms — see _require_enabled_for_challenges.
    _require_enabled_for_challenges()
    rows = (await db.execute(text("""
        SELECT id, mandate_id, action_type, action_ref, facts, challenge_hash, created_at, expires_at
        FROM liability_challenges WHERE developer_id=:d AND status='pending' AND expires_at > now()
        ORDER BY created_at DESC LIMIT 50
    """), {"d": dev.id})).mappings().all()
    # `facts_digest` is the SERVER's own "is this the same thing" key — the very digest
    # the read floor matches previews on and the streak counts identical confirms with.
    # It ships to the client so a surface can render "identical to the one you approved
    # 40 s ago" WITHOUT a second implementation of sameness in TypeScript. Two copies of
    # that predicate is what §ORGLEAK was: they agree until the day they do not, and the
    # day they do not, a badge tells a human two different asks are the same one.
    # The posture is PER ROW, not per response. Two pending confirms can belong to two
    # mandates in two organizations with two different postures, and reporting one
    # posture for the list would be a label that is wrong for some of what it labels —
    # the §FOREIGNACT failure in miniature. Resolved once per DISTINCT mandate, because
    # each resolution costs an org lookup and a list is usually one or two mandates.
    _by_mandate: dict = {}
    out = []
    for r in rows:
        d = dict(r)
        d["facts_digest"] = liab.facts_comparable_digest(d.get("facts") or {})
        mid = d.get("mandate_id")
        if mid not in _by_mandate:
            agent_did = None
            if mid:
                mr = (await db.execute(text(
                    "SELECT agent_did FROM liability_mandates WHERE id = :m LIMIT 1"), {"m": mid})).first()
                agent_did = mr[0] if mr else None
            _by_mandate[mid] = await cp.for_agent(db, agent_did)
        pname, pb = _by_mandate[mid]
        # A LABEL, never a gate: the server still decides, and refuses with a body that
        # says why. Rendering it lets a surface wear the dials instead of discovering
        # them by being refused (§8).
        d["posture"] = pname
        # A step-up confirm (mandate_id NULL) is account security, not liability — the
        # posture does not bind it, and reporting a floor for it would make a surface
        # disable a button the server would have accepted.
        d["read_floor_ms"] = int(pb.get("read_floor_ms") or 0) if mid else 0
        out.append(d)
    return {"challenges": out, "count": len(out)}


class ChallengeAckIn(BaseModel):
    """What a surface says it PUT IN FRONT OF A HUMAN."""
    surface: str = Field(pattern="^(desk|device)$")
    render_version: Optional[str] = Field(default=None, max_length=64)
    locale: Optional[str] = Field(default=None, max_length=16)
    # sha256 hex of the canonicalised lines actually rendered. CLIENT-ASSERTED.
    presentation_hash: Optional[str] = Field(default=None, pattern="^[0-9a-f]{64}$")
    # CLIENT-ASSERTED paint time. Never used to compute read_ms (R5).
    first_presented_at: Optional[_dt.datetime] = None


@router.post("/api/v1/liability/challenges/{chid}/ack",
             summary="Record that a surface presented this confirm to its human")
async def ack_challenge(chid: str, body: ChallengeAckIn,
                        dev: models.Developer = Depends(get_current_developer),
                        db: AsyncSession = Depends(get_db)):
    """
    Record that a surface presented this confirmation to its human, and what was shown. Idempotent: the first ack
    per surface wins, so a later re-render cannot overwrite it. `delivery_acked_at` is stamped by the server on
    arrival; `first_presented_at` and `presentation_hash` are what the client reports, and are labelled so.

    \f
    §SHOWN — the delivery truth, and the record of WHAT was shown.

    Idempotent, FIRST ACK PER SURFACE WINS. A second ack does not overwrite the first
    because the question a receipt answers is "what did they see when it arrived"; a
    later re-render (a locale switch, a reload) is a different question and must not
    quietly become the answer to this one.

    ⚠ Two trust levels leave here in the same row and must never be conflated:
    `delivery_acked_at` is stamped by THIS server on arrival; `first_presented_at`
    and `presentation_hash` are what the client says. The projection labels each.
    """
    _require_enabled_for_challenges()
    ch = await db.get(models.LiabilityChallenge, chid)
    if not ch or ch.developer_id != dev.id:
        # Same answer for "no such challenge" and "not yours": an ack is unauthenticated
        # about the target beyond ownership, so distinguishing them would enumerate.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Challenge not found")

    ins = await db.execute(text("""
        INSERT INTO challenge_presentations
            (challenge_id, developer_id, surface, first_presented_at, render_version, locale, presentation_hash)
        VALUES (:c, :d, :s, :fp, :rv, :lo, :ph)
        ON CONFLICT (challenge_id, surface) DO NOTHING
        RETURNING id, delivery_acked_at
    """), {"c": chid, "d": dev.id, "s": body.surface, "fp": body.first_presented_at,
           "rv": body.render_version, "lo": body.locale, "ph": body.presentation_hash})
    row = ins.mappings().first()
    first = row is not None

    # Denormalised onto the challenge for the pending list and the P4 read floor —
    # only when still unset, so the FIRST surface to show it owns the timestamp.
    await db.execute(text(
        "UPDATE liability_challenges SET delivery_acked_at = now() "
        "WHERE id = :c AND delivery_acked_at IS NULL"), {"c": chid})
    await db.commit()

    got = (await db.execute(text(
        "SELECT delivery_acked_at, presentation_hash, render_version, locale "
        "FROM challenge_presentations WHERE challenge_id=:c AND surface=:s"),
        {"c": chid, "s": body.surface})).mappings().first()
    return {
        "ok": True, "challenge_id": chid, "surface": body.surface,
        "first_ack_for_surface": first,
        "delivery_acked_at": got["delivery_acked_at"] if got else None,
        "presentation_hash": got["presentation_hash"] if got else None,
        "trust": {"delivery_acked_at": "attested",
                  "first_presented_at": "client_asserted",
                  "presentation_hash": "client_asserted"},
    }


@router.post("/api/v1/liability/challenges/{chid}/approve",
             summary="Approve: enclave signature (preferred) or TOTP fallback")
async def approve_challenge(chid: str, body: ChallengeApproveIn, request: Request,
                            dev: models.Developer = Depends(get_current_developer),
                            db: AsyncSession = Depends(get_db)):
    _require_enabled_for_challenges()
    ch = await db.get(models.LiabilityChallenge, chid)
    if not ch or ch.developer_id != dev.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Challenge not found")
    if ch.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Challenge is {ch.status} (single-use)")
    if ch.expires_at <= _now():
        await db.execute(text("UPDATE liability_challenges SET status='expired', resolved_at=now() "
                              "WHERE id=:c AND status='pending'"), {"c": chid})
        await liab.append_evidence(db, ch.mandate_id, "challenge_denied",
                                   {"challenge_id": chid, "reason": "expired"}, action_ref=ch.action_ref)
        await db.commit()
        raise HTTPException(status.HTTP_410_GONE, detail="Challenge expired — expiry is a denial")

    # ── §POSTURE P4: the READ FLOOR ─────────────────────────────────────────
    # A signature that arrives sooner than the posture's floor after the human could
    # first have had these facts is refused 425 and the challenge STAYS PENDING —
    # this is "not yet", not "no". Deliberately checked before any crypto: the
    # question "may we hear an answer yet" does not depend on the answer.
    #
    # No evidence row is written here, and that asymmetry is on purpose. A 401
    # (`presence_failed`) records a human attempt that failed and already appends;
    # a 425 records a client that will retry in 400 ms by design, and appending on
    # every poll would flood the one chain a dispute has to read.
    posture_name, pb, _posture_agent = await _posture_for_challenge(db, ch)
    # 🔴 THE POSTURE BINDS MANDATE CHALLENGES ONLY. This endpoint serves TWO features
    # (§DISCREFINE): a Cockpit confirm, and a plain account-security step-up for an
    # agent credential reset, which carries `mandate_id IS NULL` and must work on every
    # registry whether or not liability is switched on. Applying a LIABILITY posture to
    # it would make a credential reset slower and stricter because a different feature
    # was configured — the same indefensible coupling `_require_enabled_for_challenges`
    # exists to refuse. It would also have crashed: the refusal path appends to a
    # mandate's evidence chain, and there is no mandate here.
    posture_binds = ch.mandate_id is not None
    floor_ms = int(pb.get("read_floor_ms") or 0) if posture_binds else 0
    if floor_ms > 0:
        clock, clock_src, prev_id, divergence = await _read_floor_clock(db, ch, pb)
        waited_ms = int((_now() - clock).total_seconds() * 1000)
        if waited_ms < floor_ms:
            remaining = floor_ms - waited_ms
            logger.info("[POSTURE] read floor: chid=%s posture=%s waited=%sms floor=%sms src=%s",
                        chid, posture_name, waited_ms, floor_ms, clock_src)
            raise HTTPException(425, detail={
                "error": "read_floor_not_met",
                "posture": posture_name,
                "read_floor_ms": floor_ms,
                "waited_ms": max(0, waited_ms),
                "retry_after_ms": remaining,
                # WHICH clock, so the desk can say "you previewed this 9 s ago" or
                # "the amount changed since your preview, so the clock restarted".
                "clock_source": clock_src,
                "matched_preview_id": prev_id,
                "diverged_from_preview": divergence or None,
                "challenge_still_pending": True,
                "remedy": (f"confirm in {remaining} ms — this posture asks for "
                           f"{floor_ms} ms with the facts on screen"),
            }, headers={
                # Integer seconds per RFC 7231; `retry_after_ms` above carries the
                # precision a UI countdown needs. Ceil, never floor: a client that
                # rounds down retries into the same refusal.
                "Retry-After": str(max(1, math.ceil(remaining / 1000))),
            })

    method: Optional[str] = None
    device_id: Optional[int] = None
    deny_reason: Optional[str] = None
    # PREFERRED: a WebAuthn assertion. The authenticator refuses to sign without a fingerprint or
    # device PIN and reports that fact in the UV flag, which we require — so "a human approved
    # this" is verified server-side rather than asserted by the page.
    if body.authenticator_data and body.client_data_json and body.signature and body.device_id:
        drow = await db.get(models.DevicePushRegistration, body.device_id)
        if drow and drow.developer_id == dev.id and drow.webauthn_public_key and drow.key_revoked_at is None:
            from agentvault_registry.services import webauthn as wa
            ok_sig, reason, sign_count = wa.verify_assertion(
                cose_public_key_b64u=drow.webauthn_public_key,
                client_data_json_b64u=body.client_data_json,
                authenticator_data_b64u=body.authenticator_data,
                signature_b64u=body.signature,
                expected_challenge_b64u=liab.b64u_from_hex(ch.challenge_hash),
                expected_rp_ids=_rp_id_candidates(request),
                require_uv=True,
            )
            if ok_sig:
                # A sign_count that goes backwards is the documented clone signal. Authenticators
                # that always report 0 are common and legitimate, so only a genuine regression counts.
                prev = drow.webauthn_sign_count or 0
                if sign_count and prev and sign_count <= prev:
                    deny_reason = "sign_count_regression"
                else:
                    method, device_id = "webauthn_uv", drow.id
                    if sign_count:
                        await db.execute(text("UPDATE device_push_registrations SET webauthn_sign_count=:c WHERE id=:i"),
                                         {"c": sign_count, "i": drow.id})
            else:
                deny_reason = reason
    # Legacy raw-ES256 path (pre-WebAuthn devices). Kept so an enrolled device is not stranded,
    # but it proves possession of a key, NOT the presence of a human — recorded distinctly.
    elif body.signature and body.device_id:
        drow = await db.get(models.DevicePushRegistration, body.device_id)
        if (drow and drow.developer_id == dev.id and drow.pubkey_jwk
                and drow.key_revoked_at is None
                and liab.verify_es256_signature(drow.pubkey_jwk, ch.challenge_hash, body.signature)):
            method, device_id = "enclave", drow.id
    if method is None and body.totp_code:
        if liab.verify_totp_for_dev(dev, body.totp_code):
            method = "totp"
    if method is None:
        await liab.append_evidence(db, ch.mandate_id, "challenge_denied",
                                   {"challenge_id": chid, "reason": deny_reason or "presence_failed"},
                                   action_ref=ch.action_ref)
        await log_liability_action(db, action="challenge_denied", actor_type="dev",
                                 actor_id=str(dev.id), target_type="liability_challenge",
                                 target_id=chid, outcome="denied", severity="warning",
                                 details={"reason": "presence_failed"})
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Presence check failed")

    # ── §POSTURE P4: the METHOD FLOOR ───────────────────────────────────────
    # Checked AFTER the method is established, because what was OFFERED is only known
    # once verification has run: a caller sending a bad WebAuthn assertion and a good
    # TOTP code offered TOTP, and a refusal naming WebAuthn would be a lie.
    # Like the read floor, this does NOT consume the challenge: single-use is a
    # property of ANSWERS, not of refusals-to-hear.
    esc_floor, streak = (await _streak_escalated_floor(db, ch, pb)) if posture_binds else (None, 0)
    if ch.action_type == CEILING_RAISE_VERB:
        # §CEILING — THE STRONGEST PATH GUARDS ITS OWN DIALS. Granting standing consent
        # is the moment a human stops being asked; it takes an enrolled device in EVERY
        # posture, including `swift`, where ordinary confirms still accept TOTP.
        esc_floor = "webauthn_uv"
    m_ok, m_code, m_floor = (True, None, "n/a") if not posture_binds else cp.method_allowed(
        pb, method,
        has_webauthn_credential=(await _has_webauthn_credential(db, dev.id)
                                 if (method == "totp" and pb.get("totp_only_while_unenrolled")) else False),
        escalated_floor=esc_floor)
    if not m_ok:
        detail = cp.method_refusal_detail(pb, method, m_code, m_floor)
        if esc_floor:
            detail["escalated_by_streak"] = streak
            detail["remedy"] = (f"{detail['remedy']} — the floor rose because this is the "
                                f"{streak + 1}th identical confirm in a row")
        # The chain DOES record this one: it is a human attempt that was turned away,
        # exactly like the 401 path above, and a mandate's history should show that the
        # posture bit rather than that nothing happened.
        await liab.append_evidence(db, ch.mandate_id, "challenge_refused",
                                   {"challenge_id": chid, "reason": m_code,
                                    "posture": posture_name, "method_floor": m_floor,
                                    "method_offered": method, "streak": streak},
                                   action_ref=ch.action_ref)
        await log_liability_action(db, action="challenge_refused", actor_type="dev",
                                   actor_id=str(dev.id), target_type="liability_challenge",
                                   target_id=chid, outcome="refused", severity="warning",
                                   details={"reason": m_code, "posture": posture_name,
                                            "method_floor": m_floor, "method_offered": method})
        await db.commit()
        logger.info("[POSTURE] method floor: chid=%s posture=%s offered=%s floor=%s code=%s",
                    chid, posture_name, method, m_floor, m_code)
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=detail)

    claimed = await db.execute(text(
        "UPDATE liability_challenges SET status='approved', method=:me, device_id=:dv, "
        "signature=:sig, resolved_at=now() WHERE id=:c AND status='pending'"),
        {"c": chid, "me": method, "dv": device_id, "sig": body.signature})
    if getattr(claimed, "rowcount", 0) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Challenge already resolved (single-use)")
    if ch.action_type == CEILING_RAISE_VERB and ch.mandate_id:
        # The ceiling is written HERE and nowhere else: it exists only as the consequence
        # of a signature, so the challenge that carried it is stamped into the grant.
        # `granted_by_decision` is what lets a later reader ask "who said I could stop
        # being asked, and when" and get an answer from the same chain.
        newc = dict(((ch.facts or {}).get("ceiling_new")) or {})
        if newc:
            newc["granted_at"] = _now().isoformat()
            newc["granted_by_decision"] = chid
            mrow = await db.get(models.LiabilityMandate, ch.mandate_id)
            # ⚠ JSONB on an ORM attribute: a shallow copy shares the inner dicts, the
            # flush comparator sees no change and emits NO UPDATE (§POCKETBRIDGE3). Write
            # it with explicit SQL rather than trusting the mutation to be noticed.
            lim = dict((mrow.limits if isinstance(mrow.limits, dict) else {}) or {})
            lim["auto_ceiling"] = newc
            await db.execute(text("UPDATE liability_mandates SET limits = CAST(:l AS JSONB) WHERE id = :m"),
                             {"l": json.dumps(lim), "m": ch.mandate_id})
            await liab.append_evidence(db, ch.mandate_id, "ceiling_granted",
                                       {"challenge_id": chid, "ceiling": newc,
                                        "method": method, "posture": posture_name},
                                       action_ref=ch.action_ref,
                                       presence={"method": method, "device_id": device_id,
                                                 "challenge_id": chid})
    await liab.append_evidence(db, ch.mandate_id, "challenge_approved",
                               {"challenge_id": chid, "challenge_hash": ch.challenge_hash,
                                # WHICH posture was in force when this was accepted. A
                                # receipt read a year later must not have to guess the
                                # dials the deployment ran that day.
                                "posture": posture_name, "method_floor": m_floor,
                                "read_floor_ms": int(pb.get("read_floor_ms") or 0),
                                "identical_streak": streak},
                               action_ref=ch.action_ref,
                               presence={"method": method, "device_id": device_id, "challenge_id": chid})
    await log_liability_action(db, action="challenge_approved", actor_type="dev",
                             actor_id=str(dev.id), target_type="liability_challenge", target_id=chid,
                             details={"method": method, "action_type": ch.action_type})
    await db.commit()
    asyncio.create_task(_cue(dev.id, "liability.resolved", {
        "challenge_id": chid, "status": "approved", "method": method}))
    return {"ok": True, "id": chid, "status": "approved", "method": method}


class ChallengeDenyIn(BaseModel):
    """Why the human said no.

    Optional, and absent means `user_denied` — the pre-§SHOWN behaviour, so an old
    client keeps working. The vocabulary is CLOSED because these four are the ones the
    system can act on later: `wrong_amount` and `wrong_counterparty` say the FACTS were
    wrong (P8's pre-flight diff is the fix), `not_now` says the timing was wrong, and
    `never` says the standing arrangement is wrong (P7's ceilings read it).
    A free-text field would collect sentences nothing can consume.
    """
    reason: Optional[str] = Field(default=None,
                                  pattern="^(wrong_amount|wrong_counterparty|not_now|never)$")


@router.post("/api/v1/liability/challenges/{chid}/deny", summary="Deny a pending confirm")
async def deny_challenge(chid: str, body: Optional[ChallengeDenyIn] = None,
                         dev: models.Developer = Depends(get_current_developer),
                         db: AsyncSession = Depends(get_db)):
    # A human must always be able to REFUSE a confirm, on either feature. Denying is
    # the safe direction, so it is never the thing a mode flag switches off.
    _require_enabled_for_challenges()
    ch = await db.get(models.LiabilityChallenge, chid)
    if not ch or ch.developer_id != dev.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Challenge not found")
    claimed = await db.execute(text("UPDATE liability_challenges SET status='denied', resolved_at=now() "
                                    "WHERE id=:c AND status='pending'"), {"c": chid})
    if getattr(claimed, "rowcount", 0) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Challenge is {ch.status}")
    _why = (body.reason if body and body.reason else None)
    await liab.append_evidence(db, ch.mandate_id, "challenge_denied",
                               {"challenge_id": chid, "reason": _why or "user_denied",
                                "denial_reason": _why},
                               action_ref=ch.action_ref)
    await db.commit()
    asyncio.create_task(_cue(dev.id, "liability.resolved", {
        "challenge_id": chid, "status": "denied", "reason": _why or "user_denied"}))
    return {"ok": True, "id": chid, "status": "denied", "reason": _why or "user_denied"}


# ---------------------------------------------------------------------------
# Phone enclave key enrolment (rides the existing Pocket device row)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# §SHOWN — the receipts projection
# ---------------------------------------------------------------------------
# ONE CHAIN, ONE TRUTH (strategy §15.5). This is a PROJECTION over the evidence chain
# that already exists, joined to the challenge and to what a surface says it showed.
# It is deliberately not a second chain: a parallel record of the same decisions is a
# second thing that can be wrong, and no way to tell which.
#
# A receipt answers three separate questions, and says which is which (R10/R5):
#
#   challenge_hash     these facts existed on the server        ATTESTED
#   presentation_hash  these words were on the human's screen    CLIENT-ASSERTED
#   signature          this device, this human, consented        ATTESTED
#
# Latency legs are computed from SERVER timestamps only. `first_presented_at` is
# returned, clearly labelled, and never used arithmetically — a chain whose claim is
# provable intent cannot let a client-supplied clock set its numbers.

_RECEIPT_SQL = """
SELECT e.id AS ev_id, e.mandate_id, e.seq, e.event_type, e.created_at AS ev_at, e.action_ref,
       e.payload, e.presence, e.digest, e.prev_hash, e.chain_hash,
       c.id AS ch_id, c.action_type, c.facts, c.challenge_hash, c.status AS ch_status,
       c.method, c.device_id, c.signature IS NOT NULL AS has_signature,
       c.created_at AS ch_created_at, c.expires_at, c.resolved_at, c.delivery_acked_at,
       pres.presentations
  FROM liability_evidence e
  LEFT JOIN liability_challenges c
         ON c.id = COALESCE(e.payload->>'challenge_id', e.payload->>'presence_challenge_id')
  -- Presentations are AGGREGATED per challenge, not joined row-for-row. A challenge
  -- shown on both the desk and a device has two of them, and a plain join would
  -- silently duplicate the evidence row — turning one decision into two receipts.
  LEFT JOIN LATERAL (
      SELECT json_agg(json_build_object(
                 'surface', p.surface,
                 'delivery_acked_at', p.delivery_acked_at,
                 'first_presented_at', p.first_presented_at,
                 'render_version', p.render_version,
                 'locale', p.locale,
                 'presentation_hash', p.presentation_hash)
             ORDER BY p.delivery_acked_at) AS presentations
        FROM challenge_presentations p WHERE p.challenge_id = c.id
  ) pres ON TRUE
 WHERE e.mandate_id = ANY(:mids)
   -- ⚠ asyncpg binds ONE TYPE PER PARAMETER. The obvious form,
   --     (:since IS NULL OR e.created_at >= CAST(:since AS timestamptz))
   -- uses the same $n as untyped-in-IS-NULL and as timestamptz, and asyncpg answers
   -- `AmbiguousParameterError: could not determine data type of parameter $2`.
   -- One use, one cast, and COALESCE carries the "no filter" case.
   AND e.created_at >= COALESCE(CAST(:since AS timestamptz), '-infinity'::timestamptz)
 ORDER BY e.created_at DESC, e.id DESC
 LIMIT :lim
"""


def _ms(a, b) -> Optional[int]:
    """Milliseconds between two SERVER timestamps, or None when either is missing.
    None is the honest answer for a leg that was never observed — a zero would read
    as 'instant'."""
    if not a or not b:
        return None
    return int((a - b).total_seconds() * 1000)


async def _receipts(db: AsyncSession, mandate_ids: List[str], since: Optional[str], limit: int) -> List[dict]:
    if not mandate_ids:
        return []
    rows = (await db.execute(text(_RECEIPT_SQL),
                             {"mids": mandate_ids, "since": since, "lim": limit})).mappings().all()
    out: List[dict] = []
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:  # noqa: BLE001
                payload = {"raw": payload[:200]}
        payload = payload or {}
        facts = r["facts"] or {}
        pres = r["presentations"]
        if isinstance(pres, str):
            try:
                pres = json.loads(pres)
            except Exception:  # noqa: BLE001
                pres = None
        pres = pres or []
        # 🔴 §COCKPITBOOK — THIS USED TO COMPARE HASHES ACROSS LANGUAGES AND CALL THE
        # DIFFERENCE TAMPERING. `mismatch = len(distinct hashes) > 1` fired on every
        # receipt the Commander signed, because he reads the desk in German and approved on
        # a phone he had deliberately switched to English. Measured: 10 of 10 flagged
        # receipts were `desk`/de vs `device`/en at the SAME render_version — not one
        # mismatch has ever occurred between two surfaces in the same locale.
        #
        # The presentation hash covers THE WORDS THAT WERE ON SCREEN, which is the whole
        # point of it (hashing the facts instead is what `facts_digest` already does). So
        # two languages MUST hash differently, and a bilingual human was being told his own
        # signature was suspect — the §RAT failure exactly: one signal that cannot tell
        # "someone showed different terms" from "the reader speaks German".
        #
        # Comparison is therefore only meaningful WITHIN a (locale, render_version) group.
        # Across groups the honest answer is not "mismatch" and not "fine" — it is that we
        # hold renderings we cannot compare, which is its own state and gets its own field.
        _groups: Dict[tuple, set] = {}
        for _p in pres:
            _h = _p.get("presentation_hash")
            if not _h:
                continue
            _groups.setdefault((_p.get("locale") or "?", _p.get("render_version") or "?"), set()).add(_h)
        mismatch = any(len(v) > 1 for v in _groups.values())
        # True when surfaces exist in more than one comparable group: nothing is wrong, and
        # nothing has been verified either. Silence about that would be the third lie.
        incomparable = len(_groups) > 1
        comparable_groups = [
            {"locale": k[0], "render_version": k[1], "surfaces": len(v), "agree": len(v) == 1}
            for k, v in sorted(_groups.items())
        ]
        # `required` = presence was the BLOCKING reason (the gate auto-stepped it);
        # `courtesy` = a confirm that was asked for without being demanded.
        ask_reason = None
        if r["ch_id"]:
            ask_reason = "required" if facts.get("auto_stepped_up") else "courtesy"
        out.append({
            "evidence_id": r["ev_id"],
            "mandate_id": r["mandate_id"],
            "event_type": r["event_type"],
            "at": r["ev_at"],
            "action_ref": r["action_ref"],
            "payload": payload,
            "seq": r["seq"],
            "chain": {"seq": r["seq"], "digest": r["digest"],
                      "prev_hash": r["prev_hash"], "chain_hash": r["chain_hash"]},
            "challenge": None if not r["ch_id"] else {
                "id": r["ch_id"], "action_type": r["action_type"], "facts": facts,
                "status": r["ch_status"], "method": r["method"], "device_id": r["device_id"],
                "created_at": r["ch_created_at"], "expires_at": r["expires_at"],
                "resolved_at": r["resolved_at"], "delivery_acked_at": r["delivery_acked_at"],
                # Same key as the pending list: one server-side notion of sameness, so a
                # streak counted over receipts and a floor matched over previews can
                # never mean two different things.
                "facts_digest": liab.facts_comparable_digest(facts or {}),
            },
            "presentations": pres,
            # 🔴 THE SERVER CANNOT RE-RENDER, AND DELIBERATELY DOES NOT TRY.
            # The plan asked for a receipt to be flagged when its presentation_hash
            # disagrees with "a server re-render of the same facts". Building that
            # re-render would mean a SECOND implementation of "what we showed", in
            # Python, drifting from the TypeScript one — which is precisely the
            # divergence the hash exists to detect. So the server makes the comparison
            # it can actually make honestly: when TWO surfaces reported hashes for the
            # same challenge and they DISAGREE, one of them showed something the other
            # did not, and that is the finding. Flagged, never dropped.
            "presentation_mismatch": mismatch,
            # ⚠ NOT a milder mismatch — a DIFFERENT fact. Two surfaces in two languages
            # cannot be compared, so this receipt carries no cross-surface corroboration
            # either way, and the reader is told that rather than reassured.
            "presentation_incomparable": incomparable,
            "presentation_groups": comparable_groups,
            "presentation_attested": False,   # always: this is a client claim (R5)
            # The three claims, each carrying its own trust level so a reader can never
            # mistake what the client said for what the server attested.
            "proves": {
                "facts_existed": {"hash": r["challenge_hash"], "trust": "attested"},
                # The FIRST surface's hash is the canonical claim (first-ack-wins);
                # `presentation_mismatch` says whether a later surface disagreed.
                "words_on_screen": {"hash": (pres[0].get("presentation_hash") if pres else None),
                                    "trust": "client_asserted",
                                    "surfaces": len(pres), "mismatch": mismatch,
                                    "incomparable": incomparable},
                "device_consented": {"present": bool(r["has_signature"]), "method": r["method"],
                                     "trust": "attested"},
            },
            "legs_ms": {
                # ARRIVE is an ARRIVAL, not a send (R6): the cue and the push are both
                # best-effort, so the ack is the only delivery truth we hold.
                "arrive": _ms(r["delivery_acked_at"], r["ch_created_at"]),
                # READ from server timestamps ONLY (R5).
                "read": _ms(r["resolved_at"], r["delivery_acked_at"]),
                "consent": _ms(r["resolved_at"], r["ch_created_at"]),
            },
            "presence": r["presence"] if not isinstance(r["presence"], str) else json.loads(r["presence"] or "null"),
            "ask_reason": ask_reason,
        })
    return out


@router.get("/api/v1/liability/receipts",
            summary="Receipts across every mandate this human underwrites")
async def my_receipts(mandate_id: Optional[str] = None, since: Optional[str] = None,
                      limit: int = 100,
                      dev: models.Developer = Depends(get_current_developer),
                      db: AsyncSession = Depends(get_db)):
    """Developer-scoped, so the Latency and Telemetry panes make ONE call instead of
    one per mandate. The per-mandate path below stays as the drill-down."""
    _require_enabled()
    lim = max(1, min(int(limit or 100), 500))
    ids = [r[0] for r in (await db.execute(text(
        "SELECT id FROM liability_mandates WHERE developer_id = :d"), {"d": dev.id})).fetchall()]
    if mandate_id:
        # Scoped to what this human underwrites either way — a mandate_id they do not
        # own simply yields nothing, rather than an error that confirms it exists.
        ids = [m for m in ids if m == mandate_id]
    rows = await _receipts(db, ids, since, lim)
    return {"receipts": rows, "count": len(rows), "mandates": len(ids)}


@router.get("/api/v1/liability/mandates/{mid}/receipts",
            summary="Receipts for one mandate (owner or admin)")
async def mandate_receipts(mid: str, since: Optional[str] = None, limit: int = 200,
                           dev: models.Developer = Depends(get_current_developer),
                           db: AsyncSession = Depends(get_db)):
    _require_enabled()
    m = await _load_mandate(db, mid)
    if m.developer_id != dev.id and not admin_credential(dev):   # §POCKETPAIR
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your mandate")
    chain_ok, break_at = await liab.verify_chain(db, mid)
    rows = await _receipts(db, [mid], since, max(1, min(int(limit or 200), 500)))
    return {"mandate_id": mid, "chain_ok": chain_ok, "chain_break_at": break_at,
            "receipts": rows, "count": len(rows)}


@router.post("/api/v1/liability/devices/{device_id}/enroll-key",
             summary="Enrol a biometric-gated P-256 signing key on a registered device")
async def enroll_device_key(device_id: int, body: KeyEnrollIn,
                            dev: models.Developer = Depends(get_current_developer),
                            db: AsyncSession = Depends(get_db)):
    _require_enabled_for_device_keys()
    drow = await db.get(models.DevicePushRegistration, device_id)
    if not drow or drow.developer_id != dev.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Device not found")
    jwk = body.pubkey_jwk or {}
    if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256" or not jwk.get("x") or not jwk.get("y"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="pubkey_jwk must be an EC P-256 key")
    await db.execute(text("""
        UPDATE device_push_registrations
        SET pubkey_jwk = CAST(:j AS JSONB), key_alg = 'ES256',
            attestation = CAST(:a AS JSONB), key_enrolled_at = now(), key_revoked_at = NULL
        WHERE id = :i
    """), {"j": json.dumps(jwk), "a": json.dumps(body.attestation) if body.attestation else None, "i": device_id})
    await log_liability_action(db, action="device_key_enrolled", actor_type="dev",
                             actor_id=str(dev.id), target_type="device", target_id=str(device_id),
                             details={"alg": "ES256", "attested": body.attestation is not None})
    await db.commit()
    return {"ok": True, "device_id": device_id, "key_alg": "ES256"}


@router.get("/api/v1/liability/webauthn/options", summary="Registration options for THIS device")
async def webauthn_options_self(request: Request,
                                dev: models.Developer = Depends(get_current_developer)):
    """Device-agnostic registration options.

    The per-device variant required a push-device row to exist first, which forced a second,
    separate enrolment on top of the Pocket biometric lock: two credentials on one phone, two
    prompts, and a browser passkey picker when the wrong one was requested.
    ONE credential per device now serves the lock, confirmations and sign-in approval alike.
    """
    _require_enabled_for_device_keys()
    import secrets as _s
    return {
        "rp": {"id": _rp_id(request), "name": "TheProtocol"},
        "user": {"id": liab.b64u(str(dev.id).encode()), "name": dev.email,
                 "displayName": getattr(dev, "name", None) or dev.email},
        "challenge": liab.b64u(_s.token_bytes(32)),
        "pubKeyCredParams": [{"type": "public-key", "alg": -7}],   # ES256 only — what we verify
        "timeout": 120000,
        "attestation": "none",
        "authenticatorSelection": {
            "authenticatorAttachment": "platform",
            "userVerification": "required",
            "residentKey": "preferred",
        },
    }


@router.post("/api/v1/liability/webauthn/register",
             summary="Bind THIS device's biometric credential (creates the device row if needed)")
async def webauthn_register_self(body: WebAuthnRegisterIn, request: Request,
                                 dev: models.Developer = Depends(get_current_developer),
                                 db: AsyncSession = Depends(get_db)):
    """Register the credential the Pocket biometric lock just created.

    Attaches to an existing push-device row where there is one (so a phone keeps ONE row for push
    AND signing); otherwise creates a credential-only row; `rail='local'` is deliberately not a
    push rail, so a desktop browser can hold a signing credential without pretending to be
    reachable by notification.
    """
    _require_enabled_for_device_keys()
    from agentvault_registry.services import webauthn as wa
    try:
        cred_id, cose_key, rp_hash = wa.parse_attestation_public_key(body.attestation_object)
    except Exception as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unsupported credential: {exc}")
    # Refuse a credential bound to an origin we do not serve. Without this it would enrol
    # cleanly and then fail every signature with an opaque rp_id_mismatch, months later.
    bound_to = wa.match_rp_id(rp_hash, _rp_id_candidates(request))
    if not bound_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Credential was created for a different origin")

    # Attach ONLY to a row that does not already hold a credential (a phone then keeps ONE row for
    # push and signing), and otherwise create a fresh one. Taking the account's first row outright
    # meant a second device silently OVERWROTE the first device's credential — the phone kept its
    # private key, the server no longer had the matching public key, and every later signature
    # failed. Re-enrolling the SAME device is covered: it updates the row its credential is on.
    # A REVOKED credential is already retired, so reusing its row destroys nothing — that lets a
    # phone whose key was revoked re-enrol back onto its own push row instead of leaving a dead
    # row behind and starting a second one.
    row = (await db.execute(text(
        "SELECT id FROM device_push_registrations WHERE developer_id=:d AND enabled "
        "AND (webauthn_credential_id IS NULL OR webauthn_credential_id = :c "
        "     OR key_revoked_at IS NOT NULL) "
        "ORDER BY (webauthn_credential_id = :c) DESC, (rail='webpush') DESC, id LIMIT 1"),
        {"d": dev.id, "c": cred_id})).first()
    if row:
        device_id = row[0]
        await db.execute(text(
            "UPDATE device_push_registrations SET webauthn_credential_id=:c, webauthn_public_key=:k, "
            "webauthn_sign_count=0, webauthn_enrolled_at=now(), key_revoked_at=NULL WHERE id=:i"),
            {"c": cred_id, "k": cose_key, "i": device_id})
    else:
        import secrets as _s
        device_id = (await db.execute(text(
            "INSERT INTO device_push_registrations (developer_id, platform, rail, target, label, enabled, "
            "webauthn_credential_id, webauthn_public_key, webauthn_sign_count, webauthn_enrolled_at) "
            "VALUES (:d,'web','local',:t,'This device',true,:c,:k,0,now()) RETURNING id"),
            {"d": dev.id, "t": f"device:{_s.token_hex(8)}", "c": cred_id, "k": cose_key})).scalar()
    await log_liability_action(db, action="device_webauthn_enrolled", actor_type="dev",
                               actor_id=str(dev.id), target_type="device", target_id=str(device_id),
                               details={"user_verification": "required", "unified": True,
                                        "rp_id": bound_to})
    await db.commit()
    return {"ok": True, "device_id": device_id, "credential_id": cred_id}


@router.get("/api/v1/liability/devices/{device_id}/webauthn/options",
            summary="Registration options for a biometric device credential")
async def webauthn_options(device_id: int, request: Request,
                           dev: models.Developer = Depends(get_current_developer),
                           db: AsyncSession = Depends(get_db)):
    _require_enabled_for_device_keys()
    drow = await db.get(models.DevicePushRegistration, device_id)
    if not drow or drow.developer_id != dev.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Device not found")
    import secrets as _s
    challenge = liab.b64u(_s.token_bytes(32))
    return {
        "rp": {"id": _rp_id(request), "name": "TheProtocol"},
        "user": {"id": liab.b64u(str(dev.id).encode()), "name": dev.email,
                 "displayName": getattr(dev, "name", None) or dev.email},
        "challenge": challenge,
        "pubKeyCredParams": [{"type": "public-key", "alg": -7}],   # ES256 only — what we verify
        "timeout": 120000,
        "attestation": "none",
        "authenticatorSelection": {
            "authenticatorAttachment": "platform",   # the phone itself, not a roaming key
            "userVerification": "required",          # THE point: no signature without a human
            "residentKey": "preferred",
        },
    }


@router.post("/api/v1/liability/devices/{device_id}/webauthn/register",
             summary="Bind a biometric credential to this device")
async def webauthn_register(device_id: int, body: WebAuthnRegisterIn, request: Request,
                            dev: models.Developer = Depends(get_current_developer),
                            db: AsyncSession = Depends(get_db)):
    _require_enabled_for_device_keys()
    drow = await db.get(models.DevicePushRegistration, device_id)
    if not drow or drow.developer_id != dev.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Device not found")
    from agentvault_registry.services import webauthn as wa
    try:
        cred_id, cose_key, rp_hash = wa.parse_attestation_public_key(body.attestation_object)
    except Exception as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Unsupported credential: {exc}")
    bound_to = wa.match_rp_id(rp_hash, _rp_id_candidates(request))
    if not bound_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Credential was created for a different origin")
    await db.execute(text("""
        UPDATE device_push_registrations
        SET webauthn_credential_id=:c, webauthn_public_key=:k, webauthn_sign_count=0,
            webauthn_enrolled_at=now(), key_revoked_at=NULL
        WHERE id=:i
    """), {"c": cred_id, "k": cose_key, "i": device_id})
    await log_liability_action(db, action="device_webauthn_enrolled", actor_type="dev",
                               actor_id=str(dev.id), target_type="device", target_id=str(device_id),
                               details={"user_verification": "required"})
    await db.commit()
    return {"ok": True, "device_id": device_id, "credential_id": cred_id, "user_verification": "required"}


@router.post("/api/v1/liability/devices/{device_id}/revoke-key",
             summary="Revoke a device signing key (falls back to TOTP)")
async def revoke_device_key(device_id: int, dev: models.Developer = Depends(get_current_developer),
                            db: AsyncSession = Depends(get_db)):
    _require_enabled_for_device_keys()
    drow = await db.get(models.DevicePushRegistration, device_id)
    if not drow or drow.developer_id != dev.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Device not found")
    await db.execute(text("UPDATE device_push_registrations SET key_revoked_at = now() WHERE id = :i"),
                     {"i": device_id})
    await log_liability_action(db, action="device_key_revoked", actor_type="dev",
                             actor_id=str(dev.id), target_type="device", target_id=str(device_id),
                             severity="warning")
    await db.commit()
    return {"ok": True, "device_id": device_id, "key_revoked": True}


# ═══════════════════════════════════════════════════════════════════════════
# §PREFLIGHT (P8) — the agent ANNOUNCES, the human READS, only then is anything signed
#
# 🔴 THE TRUST SPLIT IS THE WHOLE DESIGN. An intent is what an AGENT says it is about
# to do. It is unverified by construction: nothing in it has been checked against a
# mandate, a balance, a counterparty or a ceiling, and it must never be signable.
# The desk renders it greyed, labelled, and with NO approve affordance in the DOM at
# all — absent, not disabled, because a disabled control is one CSS mistake away from
# being a live one (I9).
#
# 🔴 AND AN INTENT GRANTS NO READ-FLOOR CREDIT. The credit comes from a
# `consent_previews` row, which is written when the DESK renders the facts to a human
# and is stamped with the SERVER's clock (P4/R9). An agent asserting "I showed this"
# would make the floor advisory — claim you previewed an hour ago, skip the floor.
# So: intent (agent-asserted, Redis, disposable) ≠ preview (human-shown, attested).
# Both exist; only one pays.
#
# Redis, not a table: an intent is an announcement with a deadline, it is worthless
# thirty seconds after it expires, and giving it a table would mean a sweeper, a
# migration and a second place where "what is this agent about to do" is recorded.
# ═══════════════════════════════════════════════════════════════════════════

INTENT_TTL_MAX = 300
INTENT_TTL_DEFAULT = 120
INTENT_PER_AGENT_MAX = 20          # live intents one agent may hold at once
INTENT_RATE_PER_MIN = 30           # announcements per agent per minute


def _intent_key(dev_id: int, action_ref: str) -> str:
    return f"cockpit:intent:{dev_id}:{action_ref}"


def _intent_index(dev_id: int) -> str:
    return f"cockpit:intents:{dev_id}"


def _intent_rate_key(agent_did: str) -> str:
    return f"cockpit:intentrate:{agent_did}"


async def _redis():
    """The ONE redis handle, borrowed from ws_manager so presence and intents cannot
    drift onto two different connections or two spellings of the same key."""
    try:
        # ⚠ `manager` — the same wrong-name bug that had silently disabled presence_state.
        from agentvault_registry.routers.websocket import manager as _ws
        return await _ws._get_redis()
    except Exception:  # noqa: BLE001
        return None


class IntentIn(BaseModel):
    action_type: str = Field(..., max_length=64)
    action_ref: str = Field(..., max_length=200)
    facts_preview: Dict[str, Any] = Field(default_factory=dict)
    ttl: int = Field(INTENT_TTL_DEFAULT, ge=5, le=INTENT_TTL_MAX)


# ⚠ The FULL path. This router is included with NO prefix (main.py:751), so every route
# spells its own /api/v1 — and the two that did not mounted at /liability/intents, where
# nothing routes. Caught only by comparing against an EXISTING route: my first probe and
# its control BOTH returned 404, which distinguishes nothing.
@router.post("/api/v1/liability/intents", status_code=201,
             summary="Announce an action before attempting it (pre-flight)")
@limiter.limit("120/minute")
async def announce_intent(
    request: Request,                       # ⚠ slowapi passes the request ONLY if the
    response: Response,                     #    parameter is literally named `request`,
    body: IntentIn,                         #    and 500s injecting headers without a
    agent: models.Agent = Depends(get_current_agent),   # `response` — both §RATEFIX classes.
    db: AsyncSession = Depends(get_db),
):
    """The acting agent tells its underwriters what it is about to do.

    Answers 202-shaped truth: this is an ANNOUNCEMENT, not a request for permission.
    It never moves units, never creates a challenge, and never grants read-floor credit.
    """
    _require_enabled()
    agent_did = getattr(agent, "did", None) or getattr(agent, "agent_did", None)
    if not agent_did:
        raise HTTPException(400, detail={"error": "agent_has_no_did"})

    # WHO may hear this: only the humans who actually underwrite this agent. An intent
    # is addressed to the people liable for it, never broadcast — an agent must not be
    # able to put text on a stranger's desk.
    # ⚠ `status = 'signed'`, NOT 'active'. The column holds signed|revoked and I invented
    # 'active' from the shape of other tables — a value the column never holds, so the
    # query matched nothing and EVERY announcement answered `no_underwriter` while
    # looking like correct policy. Same predicate the gate itself uses
    # (services/liability.py `_mandate_for_agent`), never a second spelling of "live".
    rows = (await db.execute(text(
        "SELECT id, developer_id FROM liability_mandates "
        "WHERE agent_did = CAST(:d AS VARCHAR) AND status = 'signed' "
        "AND (expires_at IS NULL OR expires_at > now())"), {"d": agent_did})).mappings().all()
    if not rows:
        # Not 403: there is no permission to grant here. There is simply nobody who has
        # taken responsibility for this agent, so there is no desk this belongs on.
        raise HTTPException(404, detail={
            "error": "no_underwriter",
            "agent_did": agent_did,
            "remedy": "no live mandate underwrites this agent, so no human is answerable for it"})

    r = await _redis()
    if r is None:
        # Pre-flight is an OPTIMISATION. Losing it must never block the agent — it will
        # simply take the ordinary challenge path and pay the full read floor.
        logger.info("[PREFLIGHT] redis unavailable; intent dropped for %s", agent_did)
        raise HTTPException(503, detail={
            "error": "preflight_unavailable",
            "remedy": "announce is best-effort; proceed with the action and answer the challenge"})

    # Per-AGENT rate, not per-IP: many agents share one egress address, and the thing
    # worth bounding is one chatty agent, not one busy host.
    try:
        n = await r.incr(_intent_rate_key(agent_did))
        if n == 1:
            await r.expire(_intent_rate_key(agent_did), 60)
        if n > INTENT_RATE_PER_MIN:
            raise HTTPException(429, detail={
                "error": "intent_rate_exceeded", "limit_per_minute": INTENT_RATE_PER_MIN,
                "remedy": "announce fewer actions, or stop announcing and just act"})
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        pass

    now = _now()
    iid = liab.new_id("lin")
    ttl = max(5, min(INTENT_TTL_MAX, int(body.ttl or INTENT_TTL_DEFAULT)))
    rec = {
        "id": iid,
        "agent_did": agent_did,
        "action_type": body.action_type,
        "action_ref": body.action_ref,
        # The desk shows this to a human, so it carries the same comparable shape the
        # diff will later use — one definition of "the facts", never two.
        "facts_preview": liab.facts_comparable(body.facts_preview or {}),
        "facts_digest": liab.facts_comparable_digest(body.facts_preview or {}),
        "created_at": now.isoformat(),
        "expires_at": (now + _dt.timedelta(seconds=ttl)).isoformat(),
        # Said out loud, in the payload, so no renderer has to remember it.
        "unverified": True,
        "signable": False,
    }
    delivered = []
    for row in rows:
        dev_id = int(row["developer_id"])
        try:
            idx = _intent_index(dev_id)
            if await r.scard(idx) >= INTENT_PER_AGENT_MAX * 4:
                await r.spop(idx)                     # keep the index bounded, oldest-ish out
            await r.setex(_intent_key(dev_id, body.action_ref), ttl, json.dumps(rec))
            await r.sadd(idx, body.action_ref)
            await r.expire(idx, INTENT_TTL_MAX * 2)
            delivered.append(dev_id)
        except Exception:  # noqa: BLE001
            logger.debug("[PREFLIGHT] intent store failed for dev %s", dev_id, exc_info=True)
    for dev_id in delivered:
        asyncio.create_task(_cue(dev_id, "liability.intent", {
            "intent_id": iid, "action_type": body.action_type,
            "action_ref": body.action_ref, "agent_did": agent_did,
            "expires_at": rec["expires_at"]}))
    return {"intent_id": iid, "announced_to": len(delivered), "expires_at": rec["expires_at"],
            "unverified": True, "signable": False, "ttl_seconds": ttl}


@router.get("/api/v1/liability/intents/pending", summary="Pre-flight announcements awaiting a challenge")
async def pending_intents(dev: models.Developer = Depends(get_current_developer)):
    """What agents have SAID they are about to do. Re-poll for a desk that missed a cue.

    Redis expiry is the only lifecycle: an intent that never became a challenge simply
    stops being listed, which is exactly what "it expired" means here.
    """
    _require_enabled()
    r = await _redis()
    if r is None:
        # An honest gap, never an empty list: "I cannot see them" and "there are none"
        # are different answers and the desk renders them differently.
        return {"items": [], "count": 0, "available": False,
                "note": "pre-flight is unavailable; challenges are unaffected"}
    out, stale = [], []
    try:
        refs = await r.smembers(_intent_index(dev.id))
        for ref in list(refs or [])[:200]:
            ref_s = ref.decode() if isinstance(ref, (bytes, bytearray)) else str(ref)
            raw = await r.get(_intent_key(dev.id, ref_s))
            if not raw:
                stale.append(ref_s)                   # expired: drop it from the index
                continue
            try:
                out.append(json.loads(raw.decode() if isinstance(raw, (bytes, bytearray)) else raw))
            except (TypeError, ValueError):
                stale.append(ref_s)
        if stale:
            await r.srem(_intent_index(dev.id), *stale)
    except Exception:  # noqa: BLE001
        logger.debug("[PREFLIGHT] pending read failed for dev %s", dev.id, exc_info=True)
        return {"items": [], "count": 0, "available": False,
                "note": "pre-flight is unavailable; challenges are unaffected"}
    out.sort(key=lambda i: i.get("created_at") or "")
    return {"items": out, "count": len(out), "available": True}
