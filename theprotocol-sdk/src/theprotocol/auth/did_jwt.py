"""DID-JWT self-signed extension — SDK-side issue + verify helpers.

Q-C W5 (2026-05-12). Implements the
``https://theprotocol.cloud/extensions/v1/auth/did-jwt-self-signed``
A2A v1.0 extension (Commander Q3 + Q4 + Q9 signoff).

Usage (agent-side, signing):

    from theprotocol.auth.did_jwt import mint_did_jwt
    # private_pem returned ONCE from POST /onboard/create_agent
    token = mint_did_jwt(
        private_pem="-----BEGIN PRIVATE KEY-----\\n...",
        iss="did:theprotocol:my-agent",
        aud="did:theprotocol:target-agent",
        lifetime_sec=300,
    )
    # POST to target with `Authorization: Bearer <token>`

Usage (verifier-side):

    from theprotocol.auth.did_jwt import verify_did_jwt
    # public_jwk fetched from `GET /api/v1/agents/{did}/public-key`
    claims = verify_did_jwt(
        jwt_token=token,
        public_jwk={"kty":"OKP","crv":"Ed25519","x":"...","alg":"EdDSA"},
        expected_aud="did:theprotocol:my-agent",
    )
    print(claims["iss"])  # caller DID

The extension is declared on AgentCard.extensions[] via
``EXT_URI_DID_JWT``. Receivers MAY require this extension via
``AgentExtension(required=True)``.
"""
from __future__ import annotations

import base64
import json
import secrets
import time
from typing import Any, Dict, Optional


EXT_URI_DID_JWT = "https://theprotocol.cloud/extensions/v1/auth/did-jwt-self-signed"
SUPPORTED_ALGOS = ("EdDSA",)


# ─── base64url helpers (no padding, per RFC 7515) ─────────────────────────────


def _b64url_enc(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_dec(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


# ─── Sign ────────────────────────────────────────────────────────────────────


def mint_did_jwt(
    *,
    private_pem: str,
    iss: str,
    aud: str,
    lifetime_sec: int = 300,
    nonce: Optional[str] = None,
    additional_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """Issue an EdDSA-signed JWT for the did-jwt-self-signed extension.

    Args:
        private_pem: PKCS#8 PEM Ed25519 private key (returned by the registry
            at agent create time, shown ONCE).
        iss: Issuer DID (caller's own DID).
        aud: Audience DID (target agent's DID).
        lifetime_sec: TTL in seconds. Default 300 (5 min); MAX 3600.
        nonce: Replay-protection nonce. Auto-generated when omitted (16-byte
            hex). Receivers SHOULD track ``(iss, nonce)`` in an LRU for 2× TTL.
        additional_claims: Optional extra claims to merge into payload.

    Returns:
        Compact JWT (header.payload.signature).
    """
    if lifetime_sec < 1 or lifetime_sec > 3600:
        raise ValueError("lifetime_sec must be 1..3600 seconds")

    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as e:
        raise RuntimeError("`cryptography` package required to issue a did-jwt") from e

    priv_obj = serialization.load_pem_private_key(private_pem.encode("utf-8"), password=None)
    if not isinstance(priv_obj, Ed25519PrivateKey):
        raise ValueError("private_pem is not an Ed25519 PKCS#8 key")

    now = int(time.time())
    nonce_hex = nonce or secrets.token_hex(16)
    payload: Dict[str, Any] = {
        "iss": iss,
        "aud": aud,
        "iat": now,
        "exp": now + lifetime_sec,
        "nonce": nonce_hex,
    }
    if additional_claims:
        payload.update(additional_claims)

    header = {"alg": "EdDSA", "typ": "JWT"}
    h_b64 = _b64url_enc(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    p_b64 = _b64url_enc(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    sig = priv_obj.sign(signing_input)
    s_b64 = _b64url_enc(sig)
    return f"{h_b64}.{p_b64}.{s_b64}"


# ─── Verify ──────────────────────────────────────────────────────────────────


class DidJwtError(Exception):
    """Raised when a did-jwt fails any verification step."""


def verify_did_jwt(
    jwt_token: str,
    public_jwk: Dict[str, Any],
    *,
    expected_aud: Optional[str] = None,
    expected_iss: Optional[str] = None,
    leeway_sec: int = 30,
) -> Dict[str, Any]:
    """Verify an EdDSA-signed did-jwt and return decoded claims on success.

    Raises:
        DidJwtError: invalid signature, expired, wrong audience, wrong issuer,
            unsupported algorithm.

    Returns:
        Decoded payload dict with iss/aud/iat/exp/nonce + any additional claims.
    """
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as e:
        raise RuntimeError("`cryptography` package required for did-jwt verify") from e

    parts = jwt_token.split(".")
    if len(parts) != 3:
        raise DidJwtError("malformed JWT — expected header.payload.signature")
    h_b64, p_b64, s_b64 = parts

    try:
        header = json.loads(_b64url_dec(h_b64).decode("utf-8"))
        payload = json.loads(_b64url_dec(p_b64).decode("utf-8"))
        sig = _b64url_dec(s_b64)
    except (ValueError, json.JSONDecodeError) as e:
        raise DidJwtError(f"could not decode JWT segments: {e}") from e

    if header.get("alg") not in SUPPORTED_ALGOS:
        raise DidJwtError(f"unsupported alg: {header.get('alg')} (need EdDSA)")
    if header.get("typ") not in ("JWT", None):
        raise DidJwtError(f"unsupported typ: {header.get('typ')}")

    if public_jwk.get("kty") != "OKP" or public_jwk.get("crv") != "Ed25519":
        raise DidJwtError("public_jwk must be OKP/Ed25519")
    pub_raw = _b64url_dec(public_jwk["x"])
    try:
        pub_obj = Ed25519PublicKey.from_public_bytes(pub_raw)
    except Exception as e:
        raise DidJwtError(f"invalid public key bytes: {e}") from e

    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    try:
        pub_obj.verify(sig, signing_input)
    except InvalidSignature as e:
        raise DidJwtError("signature verification failed") from e

    now = int(time.time())
    exp = payload.get("exp")
    iat = payload.get("iat")
    if exp is None or now > int(exp) + leeway_sec:
        raise DidJwtError("token expired")
    if iat is not None and int(iat) > now + leeway_sec:
        raise DidJwtError("token issued in the future")

    if expected_aud is not None and payload.get("aud") != expected_aud:
        raise DidJwtError(f"audience mismatch: got {payload.get('aud')!r}, want {expected_aud!r}")
    if expected_iss is not None and payload.get("iss") != expected_iss:
        raise DidJwtError(f"issuer mismatch: got {payload.get('iss')!r}, want {expected_iss!r}")

    return payload


__all__ = [
    "EXT_URI_DID_JWT",
    "SUPPORTED_ALGOS",
    "DidJwtError",
    "mint_did_jwt",
    "verify_did_jwt",
]
