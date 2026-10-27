"""Registry Card EdDSA signature verification (SDK reference impl).

Works for v0.3 and newer cards: verification always runs over the card's OWN
declared ``signature.signed_canonical`` path list (a v0.5 card declares 23
paths), so new card versions verify without SDK changes. Mirrors the
registry's own verifier (registry_card_signer_impl.verify_with_jwk + the
federation_sync consumption flow) byte-for-byte:

  1. take the card's OWN declared ``signature.signed_canonical`` path list
     (falls back to the 13-path v0.3 baseline only when a card declares
     nothing) and extract those paths from the card in declared order;
  2. re-inject the signature block's ``signed_at``/``expires_at`` freshness
     window as ``_signed_at``/``_expires_at`` payload keys;
  3. canonicalize with ``json.dumps(sort_keys=True, separators=(",", ":"),
     default=str)`` and verify the detached EdDSA (Ed25519) signature against
     the JWKS key whose ``kid`` matches the signature block;
  4. reject expired signatures.

Requires the ``cryptography`` package (``pip install theprotocol-sdk[anp]`` or
``cryptography>=42.0``).
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .cost_composition import SIGNED_CANONICAL_PATHS

__all__ = ["verify_registry_card", "extract_paths"]


def extract_paths(card: Dict[str, Any], paths: Optional[List[str]]) -> Dict[str, Any]:
    """Pull the given dotted paths out of a card, in the given order.

    Missing paths resolve to ``None`` (they are still part of the signed
    payload — the signer includes them the same way).
    """
    out: Dict[str, Any] = {}
    for path in (paths or []):
        cursor: Any = card
        for part in path.split("."):
            if isinstance(cursor, dict) and part in cursor:
                cursor = cursor[part]
            else:
                cursor = None
                break
        out[path] = cursor
    return out


def _canonical_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def verify_registry_card(
    card: Dict[str, Any],
    jwks: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> bool:
    """Verify a Registry Card EdDSA signature (v0.3+ cards). Returns True iff valid.

    Args:
        card: the full registry card dict (as served at
            ``/.well-known/registry-card.json``), including its ``signature``
            block.
        jwks: the registry's JWKS dict (as served at
            ``/.well-known/registry-jwks.json``); the key is selected by the
            signature block's ``kid``.
        now: override the clock for the expiry check (tests); defaults to
            ``datetime.now(timezone.utc)``.

    Never raises on malformed input — any structural problem returns False.
    Raises ImportError only when ``cryptography`` is not installed.
    """
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError as e:  # pragma: no cover - env-dependent
        raise ImportError(
            "verify_registry_card requires the 'cryptography' package "
            "(pip install 'theprotocol-sdk[anp]' or cryptography>=42.0)"
        ) from e

    if not isinstance(card, dict) or not isinstance(jwks, dict):
        return False
    sig = card.get("signature") or {}
    sig_value = sig.get("value")
    kid = sig.get("kid")
    if not sig_value or not kid:
        return False

    matching = next(
        (k for k in jwks.get("keys", []) if isinstance(k, dict) and k.get("kid") == kid),
        None,
    )
    if not matching or not matching.get("x"):
        return False

    declared = sig.get("signed_canonical") or SIGNED_CANONICAL_PATHS
    payload = extract_paths(card, declared)
    if sig.get("signed_at") is not None:
        payload["_signed_at"] = sig.get("signed_at")
    if sig.get("expires_at") is not None:
        payload["_expires_at"] = sig.get("expires_at")

    try:
        public_key = Ed25519PublicKey.from_public_bytes(_b64url_decode(matching["x"]))
        sig_bytes = _b64url_decode(sig_value)
    except Exception:
        return False

    try:
        public_key.verify(sig_bytes, _canonical_bytes(payload))
    except InvalidSignature:
        return False
    except Exception:
        return False

    expires_at = sig.get("expires_at")
    if expires_at:
        try:
            exp = datetime.fromisoformat(str(expires_at))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < (now or datetime.now(timezone.utc)):
                return False
        except Exception:
            return False

    return True
