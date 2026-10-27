"""
SPIRE JWT bundle exposed as standard JWKS JSON.

Phase 12.1 (2026-04-28): the EventStore /ws/events handshake authenticates via
JWT-SVID minted by reactors. ES validates against this JWKS endpoint instead
of needing pyspiffe + a SPIRE socket mount.

Pattern is standard OIDC: any party that wants to validate a JWT-SVID can fetch
this JWKS and use a normal JWT library (pyjwt, jose, etc.). No secrets, no
in-band coupling. The endpoint is read-only and intentionally unauthenticated
because the keys it returns are PUBLIC by definition.

Cache-Control: 5 min — clients (e.g., ES) cache locally and refresh on a TTL
to handle SPIRE key rotation.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, List

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import APIRouter, HTTPException, Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/spire", tags=["SPIRE"])  # §pass56 PR-6: TitleCase tag


def _b64url_uint(value: int) -> str:
    """Encode an integer as JWKS-style base64url (no padding)."""
    length = (value.bit_length() + 7) // 8
    raw = value.to_bytes(length, "big") if length else b"\x00"
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _key_to_jwk(kid: str, key: Any) -> Dict[str, Any] | None:
    """Convert a cryptography public key into a JWK dict. Supports RSA + EC,
    which are the algorithms SPIRE issues today (RS256 by default, EC256 on
    request)."""
    try:
        if isinstance(key, rsa.RSAPublicKey):
            numbers = key.public_numbers()
            return {
                "kty": "RSA",
                "kid": kid,
                "use": "sig",
                "alg": "RS256",
                "n": _b64url_uint(numbers.n),
                "e": _b64url_uint(numbers.e),
            }
        if isinstance(key, ec.EllipticCurvePublicKey):
            numbers = key.public_numbers()
            curve_name = key.curve.name
            crv = {"secp256r1": "P-256", "secp384r1": "P-384", "secp521r1": "P-521"}.get(
                curve_name, curve_name
            )
            alg = {"P-256": "ES256", "P-384": "ES384", "P-521": "ES512"}.get(crv, "ES256")
            byte_len = (key.curve.key_size + 7) // 8
            return {
                "kty": "EC",
                "kid": kid,
                "use": "sig",
                "alg": alg,
                "crv": crv,
                "x": base64.urlsafe_b64encode(
                    numbers.x.to_bytes(byte_len, "big")
                ).rstrip(b"=").decode("ascii"),
                "y": base64.urlsafe_b64encode(
                    numbers.y.to_bytes(byte_len, "big")
                ).rstrip(b"=").decode("ascii"),
            }
    except Exception as e:
        logger.warning(f"[SPIRE-JWKS] Failed to convert key {kid}: {e}")
    return None


@router.get("/jwks")
async def get_jwks() -> Response:
    """Standard JWKS endpoint for the local SPIRE trust domain. Public:
    these are public signing keys, not secrets. Cache 5 minutes.

    Used by the EventStore (and any other JWT-SVID consumer) to validate
    JWTs issued by SPIRE workloads in the same trust domain.
    """
    try:
        from spiffe import WorkloadApiClient, TrustDomain
    except ImportError:
        raise HTTPException(503, "pyspiffe unavailable on this registry")

    trust_domain_name = (
        os.getenv("SPIRE_TRUST_DOMAIN")
        or os.getenv("TRUST_DOMAIN")
        or "agentvault.com"
    )
    socket = os.getenv("SPIFFE_ENDPOINT_SOCKET")
    if not socket:
        raise HTTPException(503, "SPIFFE_ENDPOINT_SOCKET not configured")

    keys: List[Dict[str, Any]] = []
    try:
        with WorkloadApiClient() as client:
            bundle_set = client.fetch_jwt_bundles()
            td = TrustDomain(trust_domain_name)
            bundle = bundle_set.get_bundle_for_trust_domain(td)
            if bundle is None:
                logger.warning(
                    f"[SPIRE-JWKS] No JWT bundle for trust_domain={trust_domain_name}"
                )
            else:
                authorities = (
                    bundle.jwt_authorities()
                    if callable(getattr(bundle, "jwt_authorities", None))
                    else bundle.jwt_authorities
                )
                for kid, key in authorities.items():
                    jwk = _key_to_jwk(kid, key)
                    if jwk is not None:
                        keys.append(jwk)
    except Exception as e:
        logger.warning(f"[SPIRE-JWKS] fetch_jwt_bundles failed: {e}")
        raise HTTPException(503, f"SPIRE JWT bundle fetch failed: {e}")

    body = {"keys": keys, "trust_domain": trust_domain_name}
    return Response(
        content=__import__("json").dumps(body),
        media_type="application/json",
        headers={"Cache-Control": "max-age=300, public"},
    )
