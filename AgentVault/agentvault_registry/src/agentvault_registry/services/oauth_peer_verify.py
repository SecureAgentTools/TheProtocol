"""Peer-registry token verification for OAuth federation — RA1 (2026-07-24).

The subject token in an RFC 8693 exchange is the *whole* claim of identity: it
says "this agent, on that registry, is who I say they are." The previous
implementation decoded it with ``options={"verify_signature": False}`` and a
comment reading "In production, verify with public key" — so any caller holding
the client credentials could assert **any** agent DID on **any** peer registry.

This module does the verification for real: fetch the peer's JWKS (cached),
select the key by ``kid``, verify the signature, and enforce ``iss`` / ``exp`` /
``aud``. Anything that does not verify is rejected — there is no fall-through to
an unverified decode.

Both RS256 (federation keys, see ``oauth_keystore``) and EdDSA (the registry-card
key family) are accepted so a peer can publish either.
"""
import json
import logging
import time
from typing import Any, Dict, List, Optional

import httpx
import jwt  # PyJWT

logger = logging.getLogger(__name__)

ACCEPTED_ALGORITHMS = ["RS256", "RS384", "RS512", "EdDSA", "ES256"]

# issuer/jwks_uri -> (fetched_at_monotonic, jwks document)
_JWKS_CACHE: Dict[str, tuple] = {}
_DEFAULT_TTL_SECONDS = 300


class PeerTokenError(Exception):
    """Raised when a peer-registry token cannot be trusted. Never soft-fails."""


def _jwk_to_key(jwk_dict: Dict[str, Any]):
    kty = (jwk_dict.get("kty") or "").upper()
    raw = json.dumps(jwk_dict)
    if kty == "RSA":
        return jwt.algorithms.RSAAlgorithm.from_jwk(raw)
    if kty == "OKP":
        return jwt.algorithms.OKPAlgorithm.from_jwk(raw)
    if kty == "EC":
        return jwt.algorithms.ECAlgorithm.from_jwk(raw)
    raise PeerTokenError(f"unsupported JWK key type: {kty or '(missing)'}")


def clear_cache() -> None:
    """Drop the JWKS cache (tests, and admin trust-config changes)."""
    _JWKS_CACHE.clear()


async def fetch_peer_jwks(jwks_uri: str, *, ttl_seconds: int = _DEFAULT_TTL_SECONDS, force: bool = False) -> Dict[str, Any]:
    """Fetch and cache a peer's JWKS document."""
    cached = _JWKS_CACHE.get(jwks_uri)
    if cached and not force and (time.monotonic() - cached[0]) < ttl_seconds:
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(jwks_uri)
            response.raise_for_status()
            document = response.json()
    except Exception as exc:  # noqa: BLE001
        logger.error("[OAuthPeerVerify] JWKS fetch failed uri=%s err=%s", jwks_uri, exc)
        raise PeerTokenError(f"could not fetch peer JWKS from {jwks_uri}") from exc

    if not isinstance(document, dict) or not isinstance(document.get("keys"), list) or not document["keys"]:
        raise PeerTokenError(f"peer JWKS at {jwks_uri} is empty or malformed")

    _JWKS_CACHE[jwks_uri] = (time.monotonic(), document)
    return document


async def verify_peer_token(
    token: str,
    *,
    jwks_uri: str,
    expected_issuer: str,
    audience: Optional[Any] = None,
    leeway_seconds: int = 30,
) -> Dict[str, Any]:
    """Verify a token issued by a trusted peer registry. Returns its claims.

    Raises PeerTokenError on anything short of a full verification.
    """
    if not token or token.count(".") != 2:
        raise PeerTokenError("subject token is not a JWS")

    try:
        header = jwt.get_unverified_header(token)
    except Exception as exc:  # noqa: BLE001
        raise PeerTokenError("subject token header is unreadable") from exc

    alg = header.get("alg")
    if alg not in ACCEPTED_ALGORITHMS:
        # Blocks alg=none and HS* confusion (an attacker signing with a public key).
        raise PeerTokenError(f"subject token algorithm not accepted: {alg}")

    kid = header.get("kid")
    jwks = await fetch_peer_jwks(jwks_uri)

    def _candidates(document: Dict[str, Any]) -> List[Dict[str, Any]]:
        keys = [k for k in document.get("keys", []) if isinstance(k, dict)]
        if kid:
            matched = [k for k in keys if k.get("kid") == kid]
            if matched:
                return matched
        return keys

    attempts = [(_candidates(jwks), jwks)]
    if kid and not any(k.get("kid") == kid for k in jwks.get("keys", [])):
        # kid unknown: the peer may have just rotated — refetch once, bypassing cache.
        refreshed = await fetch_peer_jwks(jwks_uri, force=True)
        attempts.append((_candidates(refreshed), refreshed))

    last_error: Optional[Exception] = None
    for candidates, _document in attempts:
        for jwk_dict in candidates:
            try:
                key = _jwk_to_key(jwk_dict)
                return jwt.decode(
                    token,
                    key,
                    algorithms=ACCEPTED_ALGORITHMS,
                    audience=audience,
                    issuer=expected_issuer,
                    leeway=leeway_seconds,
                    options={
                        "verify_signature": True,
                        "verify_exp": True,
                        "verify_iss": True,
                        "verify_aud": audience is not None,
                    },
                )
            except Exception as exc:  # noqa: BLE001 — try the next key before failing
                last_error = exc

    logger.warning(
        "[OAuthPeerVerify] subject token rejected issuer=%s kid=%s err=%s",
        expected_issuer, kid, last_error,
    )
    raise PeerTokenError(f"subject token verification failed: {last_error}")
