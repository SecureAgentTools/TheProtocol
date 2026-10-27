"""Registry Card v0.3 — JWS signer implementation.

EdDSA signature over the 13 canonical fields per spec §2. Detached JWS
(payload not embedded — verifier reconstructs payload from card itself).

Verifier flow:
  1. Fetch /.well-known/registry-card.json → get card body + signature block
  2. Fetch /.well-known/registry-jwks.json → JWKS for that registry's SPIFFE
  3. Extract canonical payload from card (extract_canonical_payload in signer.py)
  4. Re-canonicalize → bytes
  5. Verify EdDSA signature against JWK keyed by `kid`

NB: do NOT add `from __future__ import annotations` here.
"""
import base64
import json
import logging
from typing import Any, Dict

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from .. import models
from .registry_card_keystore import load_private_key

logger = logging.getLogger(__name__)


def _canonical_bytes(payload: Dict[str, Any]) -> bytes:
    """Sort_keys + tight separators → deterministic bytes for signing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sign_with_keypair(
    payload: Dict[str, Any],
    key_row: models.RegistrySigningKey,
) -> str:
    """Sign the canonical payload with the private key in `key_row`.

    Returns the URL-safe base64-encoded signature (no padding).
    """
    private_key: Ed25519PrivateKey = load_private_key(key_row)
    msg = _canonical_bytes(payload)
    sig = private_key.sign(msg)
    return base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")


def verify_with_jwk(
    payload: Dict[str, Any],
    signature_value: str,
    public_jwk: Dict[str, Any],
) -> bool:
    """Verify a v0.3 card signature against a public JWK.

    Used by federation_sync's signature_verified flag (Phase 6+).
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey,
    )
    from cryptography.exceptions import InvalidSignature

    try:
        x_b64 = public_jwk["x"]
        pad = "=" * (-len(x_b64) % 4)
        raw = base64.urlsafe_b64decode(x_b64 + pad)
        public_key = Ed25519PublicKey.from_public_bytes(raw)
    except Exception as e:
        logger.warning("[RegistryCardSignerImpl] JWK decode failed: %s", e)
        return False

    try:
        pad = "=" * (-len(signature_value) % 4)
        sig_bytes = base64.urlsafe_b64decode(signature_value + pad)
    except Exception:
        return False

    try:
        public_key.verify(sig_bytes, _canonical_bytes(payload))
        return True
    except InvalidSignature:
        return False


__all__ = ["sign_with_keypair", "verify_with_jwk"]
