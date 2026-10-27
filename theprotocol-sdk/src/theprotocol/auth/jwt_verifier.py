"""Agent JWT verifier (Q-C BL-3, 2026-05-12).

The agent-side complement to the registry's ``get_current_agent`` dependency.
Verifies a caller's ``Authorization: Bearer <agent_jwt>`` against the issuing
registry by calling ``GET /api/v1/agents/me`` (which itself requires a valid
agent JWT and returns the caller's DID).

Why call the registry rather than verify locally?
  - Registry uses HS256 with a server-only secret (``settings.API_KEY_SECRET``).
    The secret is not — and must not be — distributed to agent containers.
  - A future v1.1 may add RS256/EdDSA + JWKS publication for offline verify;
    that path is the v1.1 ``did_jwt_self_signed`` extension (Q-C W5).

Bounded TTL cache (5s) prevents hot-path round-trips while keeping revocation
window tight.

Usage:
    from theprotocol.auth import AgentJwtVerifier, A2AAuthenticator
    from theprotocol.payment import PaymentVerifier

    jwt_verifier = AgentJwtVerifier(registry_url="https://api.theprotocol.cloud")
    payment_verifier = PaymentVerifier(registry_url=..., agent_did=...)
    auth = A2AAuthenticator(
        payment_verifier=payment_verifier,
        agent_jwt_verifier=jwt_verifier,
        trust_domain="eu.theprotocol.cloud",
        required=True,
    )

    @app.post("/a2a", dependencies=[Depends(auth)])
    async def handle_a2a(request: Request):
        info = request.state.mtls_auth
        ...
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import httpx

try:
    from starlette.requests import Request as StarletteRequest
except ImportError:  # the SDK without its server extra
    StarletteRequest = Any  # type: ignore

logger = logging.getLogger(__name__)


# Module-level bounded TTL cache — keyed by SHA-256(token).
_verify_cache: Dict[str, tuple] = {}  # token_hash -> (result_dict, expire_time)
_CACHE_DEFAULT_TTL = 5      # seconds
_CACHE_MAX_ENTRIES = 256    # eviction LRU-by-expire when exceeded


def _evict_cache_if_full() -> None:
    if len(_verify_cache) >= _CACHE_MAX_ENTRIES:
        # Drop the entry that expires soonest (or already expired).
        try:
            oldest_key = min(_verify_cache.items(), key=lambda kv: kv[1][1])[0]
            _verify_cache.pop(oldest_key, None)
        except ValueError:
            pass


def _token_cache_key(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


class AgentJwtVerifier:
    """FastAPI-compatible verifier for ``Authorization: Bearer <agent_jwt>``.

    Returns ``{"verified": True, "caller_did": "...", "client_id": "..."}`` on
    success; ``{"verified": False, "reason": "..."}`` on failure.

    NOT a FastAPI Depends() directly — meant to be composed inside
    ``A2AAuthenticator`` which fans out across mTLS / JWT / payment surfaces.
    """

    def __init__(
        self,
        registry_url: str,
        *,
        cache_ttl: int = _CACHE_DEFAULT_TTL,
        verify_path: str = "/api/v1/agents/me",
        trusted_registries: Optional[List[str]] = None,
        timeout: float = 5.0,
    ):
        self.registry_url = registry_url.rstrip("/")
        self.cache_ttl = cache_ttl
        self.verify_path = verify_path
        self.timeout = timeout
        # Cross-registry trust set (for `iss`-based routing in v1.1).
        self._trusted: set[str] = {self.registry_url}
        if trusted_registries:
            for url in trusted_registries:
                self._trusted.add(url.rstrip("/"))

    async def verify(self, token: str) -> Dict[str, Any]:
        if not token or not isinstance(token, str):
            return {"verified": False, "reason": "missing_token"}

        # Cache lookup
        cache_key = _token_cache_key(token)
        now = time.time()
        cached = _verify_cache.get(cache_key)
        if cached and cached[1] > now:
            return cached[0]

        # Remote verify via /agents/me
        verify_url = f"{self.registry_url}{self.verify_path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    verify_url,
                    headers={"Authorization": f"Bearer {token}"},
                )
        except Exception as e:
            logger.debug("[AgentJwtVerifier] HTTP error verifying JWT: %s", e)
            return {"verified": False, "reason": f"transport_error: {e}"}

        if resp.status_code == 200:
            try:
                payload = resp.json()
            except Exception:
                payload = {}
            result = {
                "verified": True,
                "caller_did": payload.get("did") or payload.get("agent_did"),
                "client_id": payload.get("client_id"),
                "status": payload.get("status"),
                "registry": self.registry_url,
            }
            _evict_cache_if_full()
            _verify_cache[cache_key] = (result, now + self.cache_ttl)
            return result

        if resp.status_code in (401, 403):
            try:
                body = resp.json()
                reason = body.get("error", {}).get("detail") or body.get("detail") or "invalid_jwt"
            except Exception:
                reason = f"http_{resp.status_code}"
            return {"verified": False, "reason": reason}

        logger.debug("[AgentJwtVerifier] unexpected status %s from /agents/me", resp.status_code)
        return {"verified": False, "reason": f"unexpected_status_{resp.status_code}"}

    async def __call__(self, request: StarletteRequest) -> Dict[str, Any]:
        """FastAPI-compatible callable form — pulls the Bearer token from the
        Authorization header itself. ``request`` is annotated as a Request so FastAPI passes the
        request (until 0.7.6, annotated ``Any``, it read a query parameter and refused with 422).

        Returns a verification result dict; does NOT raise on failure (raising
        is the caller's responsibility based on ``required`` policy).
        """
        token = ""
        try:
            auth_header = request.headers.get("Authorization") or request.headers.get("authorization") or ""
        except Exception:
            auth_header = ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
        if not token:
            return {"verified": False, "reason": "missing_authorization_bearer"}
        return await self.verify(token)


__all__ = ["AgentJwtVerifier"]
