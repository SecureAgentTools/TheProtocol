"""Server-side EdDSA keypair generation for did-jwt-self-signed extension.

Q-C W5 (2026-05-12) — per Commander Q3 (server-generated, shown ONCE) +
Q4 (EdDSA) signoff.

When an agent opts into did-jwt at create time AND the caller did NOT supply
their own ``public_key_jwk``, the server:
  1. Generates an Ed25519 keypair via ``cryptography``.
  2. Stores the PUBLIC key as a JWK on the agent row.
  3. Returns the PRIVATE key (PKCS#8 PEM) to the caller ONCE.
  4. Auto-adds the ``did_jwt_self_signed`` extension URI to AgentCard.extensions[].

The private key is NEVER persisted server-side — same lifecycle as
``client_secret``. The agent stores it locally and signs JWTs offline.

Gated by env ``A2A_DID_JWT_AUTOGEN`` (default ``false`` in prod, ``true`` in
sandbox-A). Phase rollout per Q15.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


EXT_URI_DID_JWT = "https://theprotocol.cloud/extensions/v1/auth/did-jwt-self-signed"


def autogen_enabled() -> bool:
    """Master env gate for server-side EdDSA keypair generation."""
    return os.environ.get("A2A_DID_JWT_AUTOGEN", "false").strip().lower() in ("true", "1", "yes", "on")


def _b64url_encode(b: bytes) -> str:
    """Base64-URL-encode without padding (per RFC 7515 / JWK)."""
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def generate_eddsa_keypair() -> Tuple[Dict[str, Any], str]:
    """Generate an Ed25519 keypair.

    Returns:
        (public_jwk, private_key_pem) — public is a JWK dict ready for
        ``Agent.public_key_jwk``; private is a PKCS#8 PEM string returned to
        the caller ONCE.

    Raises:
        ImportError: cryptography library missing (should never happen in
            registry container).
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    public_raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    public_jwk = {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": _b64url_encode(public_raw),
        "alg": "EdDSA",
        "use": "sig",
        "key_ops": ["verify"],
    }

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")

    return public_jwk, private_pem


def ensure_did_jwt_extension(card_data: Dict[str, Any]) -> Dict[str, Any]:
    """Idempotently add the did-jwt-self-signed extension to ``extensions[]``.

    Returns a new dict (does not mutate input). Used when the server
    auto-generates an EdDSA keypair for a card that didn't declare the
    extension explicitly.
    """
    if not isinstance(card_data, dict):
        return card_data
    result = dict(card_data)
    extensions = list(result.get("extensions") or [])
    for ext in extensions:
        if isinstance(ext, dict) and ext.get("uri") == EXT_URI_DID_JWT:
            return result  # already declared
    extensions.append({
        "uri": EXT_URI_DID_JWT,
        "description": "EdDSA-signed JWT using agent's DID private key; offline-capable",
        "required": False,
        "params": {"lifetimeSec": 300, "supportedAlgos": ["EdDSA"]},
    })
    result["extensions"] = extensions
    return result


__all__ = [
    "EXT_URI_DID_JWT",
    "autogen_enabled",
    "generate_eddsa_keypair",
    "ensure_did_jwt_extension",
]
