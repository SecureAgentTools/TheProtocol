"""Registry-side AgentCard JWS verifier (Option C Phase 9.a, §pass36).

Three-flag staircase via env (default-off = shadow-friendly):

  - JWS_VERIFY_ENABLED      (default false)  — master kill; skip all work
  - JWS_ENFORCE             (default false)  — reject on invalid sig (else log only)
  - JWS_REQUIRE_SIGNATURE   (default false)  — unsigned cards also reject

Wire format + sign/verify primitive live in `theprotocol.auth.jws_card`.

Public surface:

  await verify_card_signature(card_data, db) -> (valid: bool, reason: str | None)

Honors the grace window (expires_at): a rotated key still verifies until its
expires_at, and verifies nothing from that moment on.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import a2a_v1  # noqa: F401 — package import for namespacing
from ... import models

logger = logging.getLogger(__name__)


try:
    from prometheus_client import Counter as _JCounter
    AGENT_CARD_JWS_VERIFY_TOTAL = _JCounter(
        "agent_card_jws_verify_total",
        "JWS verification outcomes for AgentCard signatures",
        labelnames=["outcome", "reason", "source"],
    )
except Exception:  # pragma: no cover
    AGENT_CARD_JWS_VERIFY_TOTAL = None


# Set once the missing verifier has been logged (a pull-sync cycle asks for every card; one line says it, the metric counts).
_VERIFIER_MISSING_LOGGED = False


def jws_verify_enabled() -> bool:
    return os.environ.get("JWS_VERIFY_ENABLED", "false").lower() == "true"


def jws_enforce() -> bool:
    return os.environ.get("JWS_ENFORCE", "false").lower() == "true"


def jws_require_signature() -> bool:
    return os.environ.get("JWS_REQUIRE_SIGNATURE", "false").lower() == "true"


def _extract_kids(card_data: Dict[str, Any]) -> List[str]:
    """Pull the list of distinct kids referenced in the card's signatures."""
    import base64
    import json

    sigs = card_data.get("signatures") or []
    out: List[str] = []
    for s in sigs:
        if not isinstance(s, dict):
            continue
        prot = s.get("protected")
        if not isinstance(prot, str):
            continue
        padding = "=" * (-len(prot) % 4)
        try:
            hdr = json.loads(base64.urlsafe_b64decode(prot + padding).decode("utf-8"))
        except Exception:
            continue
        kid = hdr.get("kid")
        if isinstance(kid, str):
            out.append(kid)
    return out


def _parse_kid(kid: str) -> Tuple[Optional[str], Optional[int]]:
    """Split `did#seq` into (did, rotation_seq). Returns Nones on malformed."""
    if "#" not in kid:
        return None, None
    did, _, seq_str = kid.rpartition("#")
    try:
        seq = int(seq_str)
    except (TypeError, ValueError):
        return did, None
    return did, seq


def _inc_metric(outcome: str, reason: str, source: str) -> None:
    if AGENT_CARD_JWS_VERIFY_TOTAL is None:
        return
    try:
        AGENT_CARD_JWS_VERIFY_TOTAL.labels(
            outcome=outcome, reason=reason, source=source,
        ).inc()
    except Exception:
        pass


async def _lookup_public_jwk(
    db: AsyncSession, did: str, rotation_seq: int,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Fetch the public JWK for a (did, rotation_seq), honoring the grace window.

    Returns (jwk, reason). When the key is not usable, jwk is None and reason says why:
    ``unknown_kid`` (no such key) or ``expired_kid`` (its grace window has ended).
    """
    import datetime as _dt
    res = await db.execute(
        select(models.AgentSigningKey).where(
            models.AgentSigningKey.agent_did == did,
            models.AgentSigningKey.rotation_seq == rotation_seq,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        # Fall back to `agents.public_key_jwk` for agents that pre-date the
        # signing-keys table (migration 0063 backfill should have seeded
        # rotation_seq=1, but check anyway).
        agent_res = await db.execute(
            select(models.Agent).where(models.Agent.did == did)
        )
        agent = agent_res.scalar_one_or_none()
        if agent and agent.public_key_jwk and rotation_seq == 1:
            return agent.public_key_jwk, None
        return None, "unknown_kid"

    if row.expires_at is not None:
        expires_at = row.expires_at
        if expires_at.tzinfo is None:  # the column is timezone-aware; a naive value is read as UTC
            expires_at = expires_at.replace(tzinfo=_dt.timezone.utc)
        if expires_at <= _dt.datetime.now(_dt.timezone.utc):
            # The grace window ends at expires_at: from then on the key verifies nothing, so a
            # rotation really retires an old (or leaked) key.
            return None, "expired_kid"
    return row.public_jwk, None


async def verify_card_signature(
    card_data: Dict[str, Any],
    db: AsyncSession,
    *,
    source: str = "unknown",
) -> Tuple[bool, Optional[str]]:
    """Verify the JWS on a card. Shadow-mode-aware.

    Args:
        card_data: full card JSON with `signatures` array (if any).
        db: open SQLAlchemy session for `agent_signing_keys` lookups.
        source: free-form label for Prom counter — typical: "pullsync",
            "federation_sync", "discovery", "card_export".

    Returns:
        (valid, reason).
          - valid=True  → at least one signature in the card verified against
            a known + un-expired public key for that kid.
          - valid=False → reason names the highest-priority failure.

    Callers in SHADOW mode should log/Prom but NOT reject; callers in
    ENFORCE mode may reject on valid=False. The two modes are gated by the
    global env flags above — this function is mode-agnostic by design (it
    always reports the truth; the caller decides what to do).
    """
    if not jws_verify_enabled():
        _inc_metric("disabled", "master_kill", source)
        return True, None  # short-circuit; treat as valid when disabled

    sigs = card_data.get("signatures") or []
    if not sigs:
        if jws_require_signature():
            _inc_metric("invalid", "missing_sig", source)
            return False, "missing_sig"
        _inc_metric("ok", "unsigned_ok_by_policy", source)
        return True, None

    # Fail CLOSED when the verifier itself is missing: a signature nobody checked is not a verified signature. This used to
    # answer (True, None), so with JWS_VERIFY_ENABLED=true on an image without the SDK every signed card passed, a forged
    # one included. The policy for an unsigned card (above) needs no verifier and is unchanged.
    try:
        from theprotocol.auth.jws_card import verify_agent_card
    except Exception as e:  # noqa: BLE001
        global _VERIFIER_MISSING_LOGGED
        if not _VERIFIER_MISSING_LOGGED:
            _VERIFIER_MISSING_LOGGED = True
            logger.error(f"[JWS] the card verifier (theprotocol.auth.jws_card) cannot be imported in this runtime: {e}; "
                         f"every signed card reads as not verified (verifier_unavailable) until it can")
        _inc_metric("error", "sdk_unavailable", source)
        return False, "verifier_unavailable"

    kids = _extract_kids(card_data)
    if not kids:
        _inc_metric("invalid", "no_kid", source)
        return False, "no_kid"

    last_reason: Optional[str] = None
    for kid in kids:
        did, seq = _parse_kid(kid)
        if did is None or seq is None:
            last_reason = "malformed_kid"
            _inc_metric("invalid", last_reason, source)
            continue
        jwk, lookup_reason = await _lookup_public_jwk(db, did, seq)
        if jwk is None:
            last_reason = lookup_reason or "unknown_kid"
            _inc_metric("invalid", last_reason, source)
            continue
        valid, vreason = verify_agent_card(card_data, jwk, expected_kid=kid)
        if valid:
            _inc_metric("ok", "verified", source)
            return True, None
        last_reason = vreason or "invalid_sig"
        _inc_metric("invalid", last_reason, source)

    return False, last_reason or "no_signature_matched"


__all__ = [
    "jws_verify_enabled",
    "jws_enforce",
    "jws_require_signature",
    "verify_card_signature",
    "AGENT_CARD_JWS_VERIFY_TOTAL",
]
