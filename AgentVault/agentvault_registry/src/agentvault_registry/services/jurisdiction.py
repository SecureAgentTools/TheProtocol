"""Jurisdiction Profiles v1 (SPEC 2026-07-31).

An operator-declared, per-deployment restriction of feature surfaces (AGORA, FX,
Guild, Forge, fiat, cross-registry transfers) plus optional limits, so a frame or
operator runs only what the law applicable to THEM permits, with the declaration
public (signed registry card block) and the responsibility on the deployment's
operator. The Provider ships mechanism, never legal conclusions: there is no
per-country profile library here by design.

Enforcement is python-primary and deny-only, evaluated BEFORE any escrow or money
movement (delta-irrelevant by construction). OPA stays off the request critical
path (§V0119); `identity-fabric/policies/agentvault_jurisdiction.rego` mirrors
these semantics as the auditable artifact + simulator input, and adds the
coherence check that CAN disagree with reality (declared-deny vs live flag).

Modes (settings.JURISDICTION_MODE, house pattern like LIABILITY_MODE):
  off     -> byte-inert (single settings read per gated request)
  shadow  -> evaluate, log '[JURISDICTION] decision=...' and count, never block
  enforce -> HTTP 403 (RFC 7807 via the central error handler)

Profile storage: exchange_flags key 'jurisdiction_profile' (generic per-frame TEXT
flag store, zero migration). Absent/null profile = unrestricted = allow everything.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.config import settings

logger = logging.getLogger(__name__)

FLAG_KEY = "jurisdiction_profile"

# The closed feature vocabulary. Adding a feature here is an additive change;
# profiles referencing unknown features are rejected at PUT time (422), so an
# old deployment can never misread a newer profile silently.
FEATURES = (
    "exchange",        # AGORA venue: orders + IPO purchases
    "fx",              # cross-frame currency exchange
    "guild",           # work exchange (posting funded tasks)
    "forge",           # eval/evolution arena runs
    "fiat",            # fiat purchase lane (mainframe-only by architecture anyway)
    "cross_transfer",  # cross-registry transfers
)

LIMIT_KEYS = ("max_transfer_amount",)

try:  # metrics are best-effort; never let observability break the gate
    from prometheus_client import Counter
    _DECISIONS = Counter(
        "jurisdiction_decisions_total",
        "Jurisdiction profile gate decisions",
        ["feature", "decision", "mode"],
    )
except Exception:  # pragma: no cover
    _DECISIONS = None

# Tiny in-process cache so hot paths (order placement under load) do not pay a DB
# read per request. The TTL is deliberately SHORT: this is a compliance gate, and a
# stale cache means a window where a newly-tightened profile is not yet enforced (or
# a relaxed one still denies). A PUT/DELETE clears the cache in its own worker
# immediately; every other worker converges within the TTL. 2s bounds that window to
# something an operator can reason about, while still absorbing request bursts.
# Measured live on frame-c (32 workers): a 10s TTL left denials in place for seconds
# after a profile was cleared, which is exactly the behaviour a compliance surface
# must not have.
_CACHE: Dict[str, Any] = {"value": None, "loaded_at": 0.0}
_CACHE_TTL_S = 2.0


def mode() -> str:
    return (getattr(settings, "JURISDICTION_MODE", "off") or "off").lower()


def validate_profile(doc: Any) -> List[str]:
    """Return a list of problems; empty list = valid. Never raises."""
    errs: List[str] = []
    if not isinstance(doc, dict):
        return ["profile must be a JSON object"]
    name = doc.get("name")
    if not isinstance(name, str) or not (1 <= len(name.strip()) <= 120):
        errs.append("name: required string (1-120 chars)")
    version = doc.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        errs.append("version: required integer >= 1")
    features = doc.get("features", {})
    if not isinstance(features, dict):
        errs.append("features: must be an object of feature -> bool")
    else:
        for k, v in features.items():
            if k not in FEATURES:
                errs.append(f"features.{k}: unknown feature (known: {', '.join(FEATURES)})")
            elif not isinstance(v, bool):
                errs.append(f"features.{k}: must be boolean")
    limits = doc.get("limits") or {}
    if not isinstance(limits, dict):
        errs.append("limits: must be an object")
    else:
        for k, v in limits.items():
            if k not in LIMIT_KEYS:
                errs.append(f"limits.{k}: unknown limit (known: {', '.join(LIMIT_KEYS)})")
            elif not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
                errs.append(f"limits.{k}: must be a positive number")
    # REGAUTH (SPEC 2026-08-15): optional block declaring which lifecycle acts
    # require a recorded regulatory authorization. Validated by the rail's own
    # module (closed action vocabulary, per-entry shadow/enforce mode). Late
    # import: regulatory_auth imports this module for the profile/mode.
    if "requires_authorization" in doc:
        from agentvault_registry.services.regulatory_auth import validate_requirements_block
        errs.extend(validate_requirements_block(doc.get("requires_authorization")))
    for k in doc.keys():
        if k not in ("name", "version", "features", "limits", "declared_at", "note",
                     "requires_authorization"):
            errs.append(f"{k}: unknown top-level key")
    return errs


def profile_hash(doc: Dict[str, Any]) -> str:
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def features_denied(doc: Dict[str, Any]) -> List[str]:
    feats = doc.get("features") or {}
    return sorted(k for k, v in feats.items() if v is False)


def clear_cache() -> None:
    _CACHE["value"] = None
    _CACHE["loaded_at"] = 0.0


async def get_profile(db: AsyncSession, *, fresh: bool = False) -> Optional[Dict[str, Any]]:
    """Load the declared profile (or None). Cached per worker for _CACHE_TTL_S."""
    now = time.monotonic()
    if not fresh and _CACHE["loaded_at"] and (now - _CACHE["loaded_at"]) < _CACHE_TTL_S:
        return _CACHE["value"]
    from agentvault_registry.services.exchange_service import get_flag
    raw = await get_flag(db, FLAG_KEY)
    value: Optional[Dict[str, Any]] = None
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and not validate_profile(parsed):
                value = parsed
            else:
                logger.error(
                    "[JURISDICTION] stored profile invalid; treating as ABSENT "
                    "(fail-open by design: a broken declaration must not freeze a frame)"
                )
        except (ValueError, TypeError):
            logger.error("[JURISDICTION] stored profile is not JSON; treating as ABSENT")
    _CACHE["value"] = value
    _CACHE["loaded_at"] = now
    return value


def evaluate(profile: Optional[Dict[str, Any]], feature: str, amount: Optional[float] = None) -> Tuple[bool, str]:
    """Pure decision: (allowed, reason). Absent profile allows everything.

    Features omitted from a declared profile default to ALLOWED: declaring a
    profile restricts, it never silently widens (absent-profile already allows).
    """
    if profile is None:
        return True, "no_profile_declared"
    feats = profile.get("features") or {}
    if feats.get(feature) is False:
        return False, f"feature_denied:{feature}"
    limits = profile.get("limits") or {}
    if feature == "cross_transfer" and amount is not None:
        cap = limits.get("max_transfer_amount")
        if isinstance(cap, (int, float)) and not isinstance(cap, bool) and float(amount) > float(cap):
            return False, f"limit_exceeded:max_transfer_amount:{cap}"
    return True, "allowed"


async def check_jurisdiction(
    db: AsyncSession,
    feature: str,
    *,
    amount: Optional[float] = None,
    actor: str = "",
) -> None:
    """The gate. Call BEFORE escrow/money moves. off = no-op; shadow = observe;
    enforce = HTTPException 403 (dual-emitted as RFC 7807 by the central handler)."""
    m = mode()
    if m == "off":
        return
    profile = await get_profile(db)
    allowed, reason = evaluate(profile, feature, amount)
    decision = "ALLOW" if allowed else "DENY"
    if _DECISIONS is not None:
        try:
            _DECISIONS.labels(feature=feature, decision=decision, mode=m).inc()
        except Exception:
            pass
    if allowed:
        return
    pname = (profile or {}).get("name", "?")
    logger.warning(
        "[JURISDICTION] decision=DENY mode=%s feature=%s reason=%s profile=%s actor=%s",
        m, feature, reason, pname, actor or "-",
    )
    if m == "enforce":
        raise HTTPException(
            status_code=403,
            detail=(
                f"jurisdiction_restricted: the '{feature}' feature is not permitted under this "
                f"deployment's declared jurisdiction profile ('{pname}', {reason}). "
                "The profile is declared by this deployment's operator; contact them for scope."
            ),
        )
