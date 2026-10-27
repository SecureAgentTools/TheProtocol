"""
Authentication Manager for API Testing

Centralized authentication handling with intelligent token selection and caching.
"""

import os
import logging
from typing import Dict, Optional, List
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


_TESTER_KEY_ROUTES = ("/admin/mcp-tester/peer-es-facts", "/admin/mcp-tester/emissions-via-target",
                      "/admin/mcp-tester/es-mtls-handshake")


# §SUITES1018: the peer-only routes an OPERATOR of this frame calls (its licence, the mail it cannot send itself). Every
# other peer-only route answers a peer FRAME.
_OWN_OPERATOR_ROUTES = ("/federation/licence/mine", "/federation/mail-relay")


async def federation_spiffe_id(path: str = "") -> str:
    """§SUITES1018 (2026-10-18): the identity the tester declares on the internal federation rail (Mode 2 of
    core/federation_auth.get_federation_identity), so a peer-only route answers the tester the way it answers a peer:
    API_TEST_FEDERATION_SPIFFE_ID when configured; for the routes an operator of this frame calls, that ACTIVE
    operator's own stamped SVID; for every other route the registry of an ACTIVE peer FRAME,
    `spiffe://<its trust domain>/service/registry`. Both are read from this registry's own peer_registries, the rows the
    S3 binding binds those identities to. This frame's own identity binds to no row, and a frame with
    FEDERATION_REQUIRE_PEER_SPIFFE_BIND refuses it. Empty when no such row exists (the call then carries no identity and
    is refused, which the row reports as it is)."""
    explicit = os.environ.get("API_TEST_FEDERATION_SPIFFE_ID")
    if explicit:
        return explicit
    own = (os.environ.get("SPIRE_TRUST_DOMAIN") or "").strip().lower()
    operator = any((path or "").rstrip("/").endswith(r) for r in _OWN_OPERATOR_ROUTES)
    try:
        from sqlalchemy import func, select
        from agentvault_registry import models
        from agentvault_registry.database import AsyncSessionLocal
        PR = models.PeerRegistry
        q = (select(PR.trust_domain, PR.spiffe_id)
             .where(PR.peer_type == ("cloud_operator" if operator else "frame"))
             .where(func.upper(PR.status) == "ACTIVE")
             .where(PR.trust_domain.isnot(None))
             .order_by(PR.id))
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(q)).all()
    except Exception as exc:  # noqa: BLE001 - no peer read: no identity; the refusal is the row's evidence
        logger.warning(f"federation_spiffe_id: could not read this registry's peers: {exc!r}")
        return ""
    for td, spiffe_id in rows:
        td = (td or "").strip().lower()
        if operator:
            if td == own and spiffe_id:
                return spiffe_id
        elif td and td != own:
            return f"spiffe://{td}/service/registry"
    return ""


class AuthManager:
    """Centralized authentication handling for API tests"""
    
    def __init__(self):
        self._token_cache = {}
        self._token_expiry = {}
        self._auth_patterns = self._initialize_auth_patterns()
        
    def _initialize_auth_patterns(self) -> Dict[str, List[str]]:
        """Initialize path patterns for auth type inference"""
        return {
            "developer": [
                "/admin/",
                "/developers/",
                "/auth/profile",
                "/auth/api-keys",
            ],
            "agent": [
                "/staking/",
                "/governance/vote",
                "/governance/proposals/{proposal_id}/",
                "/teg/",
                "/agent-builder/",
                "/disputes/",
                "/contracts/{contract_id}/accept",
                "/contracts/{contract_id}/submit",
                "/agents/me",
                "/agents/health",
                "/agents/heartbeat",
                "/attestations/submit",
                "/teg-jwt-svid/",
                "/teg-mtls/", 
                "/teg-oauth/",
                "/reputation-signal",
                "/agent-cards/",
                "/agent-logs/",
            ],
            "service": [
                "/federation/peers",
                "/federation/agent-cards",
                "/federation/sync-status",
                "/federation/sync-request",
            ],
            "token": [
                "/internal/federation",
            ],
            "none": [
                "/auth/login",
                "/auth/register",
                "/auth/request-password-reset",
                "/health",
                "/docs",
                "/openapi.json",
            ]
        }
    
    async def get_headers(
        self,
        auth_type: str = "none",
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None,
        path: str = "",
        extra_headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, str]:
        """
        Get headers with appropriate authentication.
        
        Implements intelligent token selection based on auth_type and path.
        """
        headers = {
            "accept": "application/json",
        }
        
        # Add extra headers if provided
        if extra_headers:
            headers.update(extra_headers)

        # §SUITES1018 (2026-10-18): the tester's own consoles call these with the tester key and nothing else
        # (routers/mcp_tester: "internal key required"); the sweep presents the key this frame holds, so the row measures
        # the route instead of reading its refusal of an admin bearer as a failure.
        if path.rstrip("/").endswith(_TESTER_KEY_ROUTES):
            from agentvault_registry.core.api_test_proxy_key import proxy_headers
            headers.update(proxy_headers())
        
        # Skip auth for none type
        if auth_type == "none":
            return headers
        
        # For service auth (federation endpoints), use the developer token
        # This is used for federation sync endpoints that normally use mTLS
        if auth_type == "service":
            logger.info(f"Using service authentication for {path}")
            # Service auth uses developer token as it represents the registry service
            if developer_token:
                headers["Authorization"] = f"Bearer {developer_token}"
            return headers
        
        # For OAuth federation endpoints, use HTTP Basic auth with sandbox client credentials
        if auth_type == "oauth_basic":
            # AAA+ 2026-05-21 fix: removed local `import os, base64` — `os` is
            # already imported at module level (line 7); the local re-import
            # made `os` a function-local, triggering UnboundLocalError in the
            # mtls + service-auth branches below.
            import base64
            client_id = os.environ.get("OAUTH_TEST_CLIENT_ID", "registry-test-b-at-test")
            client_secret = os.environ.get("OAUTH_TEST_CLIENT_SECRET", "sandbox-secret-shared-between-test-registries")
            credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"
            logger.info(f"Using OAuth Basic auth for {path}")
            return headers

        # For mTLS federation endpoints, use internal secret auth
        # This mirrors production's federation_auth.py Mode 2 (Docker-internal)
        # Production mTLS goes through nginx sidecars; the test tool uses the
        # internal secret fallback which federation_auth.py accepts equally.
        if auth_type == "mtls":
            fed_secret = os.environ.get(
                "FEDERATION_INTERNAL_SECRET",
                ""
            )
            headers["X-Federation-Secret"] = fed_secret
            # §SUITES1018 (2026-10-18): the identity is an ACTIVE peer frame's registry, read from this registry's peer
            # rows. The literal default named Frame A's agentvault.com, which no sandbox frame trusts: Mode 2 accepted
            # the secret and then refused the identity ("Federation identity from untrusted domain"), 403 on every
            # peer-only route of the 2026-10-18 sweep.
            headers["X-Federation-SPIFFE-ID"] = await federation_spiffe_id(path)
            logger.info(f"Using federation internal-secret auth for {path}")
            return headers
        
        # Select appropriate token
        token = self._select_token(auth_type, developer_token, agent_token, path)
        
        if token:
            headers["Authorization"] = f"Bearer {token}"
            logger.debug(f"Added {auth_type} token for {path}")
        else:
            logger.warning(f"No token available for {auth_type} auth on {path}")
        
        return headers
    
    def _select_token(
        self,
        auth_type: str,
        developer_token: Optional[str],
        agent_token: Optional[str],
        path: str
    ) -> Optional[str]:
        """
        Select the appropriate token based on auth type and path.
        
        Implements the discovery that agent endpoints should try agent token first.
        """
        # Try agent token first for agent endpoints
        if auth_type == "agent" and agent_token:
            logger.debug(f"Using agent token for {path}")
            return agent_token
        
        # Try developer token for developer endpoints
        if auth_type == "developer" and developer_token:
            logger.debug(f"Using developer token for {path}")
            return developer_token
        
        # Fallback to any available token
        if developer_token:
            logger.debug(f"Falling back to developer token for {path}")
            return developer_token
        
        if agent_token:
            logger.debug(f"Falling back to agent token for {path}")
            return agent_token
        
        return None
    
    def infer_auth_type(self, method: str, path: str) -> str:
        """
        Infer auth type based on endpoint path patterns.
        
        Used when endpoint is not in the registry.
        """
        # Check each auth type's patterns
        for auth_type, patterns in self._auth_patterns.items():
            for pattern in patterns:
                if pattern in path:
                    logger.info(f"Inferred auth_type={auth_type} for {method} {path}")
                    return auth_type
        
        # Default based on method
        if method == "GET":
            return "none"
        else:
            return "developer"
    
    def cache_token(self, token_type: str, token: str, expires_in: int = 3600):
        """Cache a token with expiration"""
        self._token_cache[token_type] = token
        self._token_expiry[token_type] = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        logger.info(f"Cached {token_type} token, expires in {expires_in}s")
    
    def get_cached_token(self, token_type: str) -> Optional[str]:
        """Get cached token if not expired"""
        if token_type not in self._token_cache:
            return None
        
        if datetime.now(timezone.utc) > self._token_expiry.get(token_type, datetime.min):
            logger.info(f"Cached {token_type} token expired")
            del self._token_cache[token_type]
            del self._token_expiry[token_type]
            return None
        
        return self._token_cache[token_type]
    
    def clear_cache(self):
        """Clear all cached tokens"""
        self._token_cache.clear()
        self._token_expiry.clear()
        logger.info("Cleared token cache")
    
    async def authenticate_developer(
        self,
        base_url: str,
        username: str,
        password: str
    ) -> Optional[str]:
        """
        Authenticate as developer and return token.
        
        This is a placeholder - implement actual auth logic based on your API.
        """
        # Check cache first
        cached = self.get_cached_token("developer")
        if cached:
            return cached
        
        # TODO: Implement actual authentication
        # For now, return None to use provided tokens
        logger.warning("Developer authentication not implemented")
        return None
    
    async def authenticate_agent(
        self,
        base_url: str,
        client_id: str,
        client_secret: str
    ) -> Optional[str]:
        """
        Authenticate as agent and return token.
        
        This is a placeholder - implement actual auth logic based on your API.
        """
        # Check cache first
        cached = self.get_cached_token("agent")
        if cached:
            return cached
        
        # TODO: Implement actual authentication
        # For now, return None to use provided tokens
        logger.warning("Agent authentication not implemented")
        return None
