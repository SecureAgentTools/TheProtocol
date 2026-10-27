"""Security utilities for TEG Core Service"""
import secrets
from typing import Optional
import logging

from fastapi import HTTPException, Request, Security, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN, HTTP_400_BAD_REQUEST

from ..core.config import get_settings
from .internal_auth import admin_key_ok  # §MONEY-M3a R26

security = HTTPBearer()
# §2026-06-16 TEG-mTLS: admin/internal checks must accept mTLS-only callers (no Bearer), so the
# bearer is OPTIONAL on those — the unified resolver decides (mTLS primary, key gated fallback).
security_optional = HTTPBearer(auto_error=False)
settings = get_settings()
logger = logging.getLogger(__name__)


def verify_agent_token(
    credentials: HTTPAuthorizationCredentials = Security(security),
    x_act_as_agent: Optional[str] = Header(None, description="Admin override: Agent ID to act as")
) -> str:
    """
    Verify agent authentication token with admin override capability.
    
    For MVP: Simple bearer token that contains the agent_id directly.
    In production, this would validate against AgentVault v1.0.0.
    
    Admin Override (DEV ONLY):
    - Use admin API key as Bearer token
    - Add header: X-Act-As-Agent: did:cos:0a8daad0-c902-7878-d51c
    - Admin can then act as any agent
    
    Returns:
        str: The authenticated agent_id
    
    Raises:
        HTTPException: If authentication fails
    """
    token = credentials.credentials
    
    # ADMIN OVERRIDE CHECK
    # Check if this is the admin API key being used
    if admin_key_ok(token):  # §MONEY-M3a R26: shape-aware, constant-time
        # Admin API key detected - check for impersonation
        if x_act_as_agent:
            # Admin wants to act as a specific agent
            # Check if admin impersonation is enabled (default to True for backward compatibility)
            enable_impersonation = getattr(settings, 'enable_admin_impersonation', True)
            
            # Safety check: Only allow in development environment
            if settings.environment != "development":
                raise HTTPException(
                    status_code=HTTP_403_FORBIDDEN,
                    detail="Admin impersonation is disabled in production environment"
                )
            
            if not enable_impersonation:
                raise HTTPException(
                    status_code=HTTP_403_FORBIDDEN,
                    detail="Admin impersonation feature is disabled"
                )
            
            # Log this action for security audit
            logger.warning(
                f"ADMIN IMPERSONATION: Admin acting as agent {x_act_as_agent}",
                extra={
                    "event": "admin_impersonation",
                    "target_agent": x_act_as_agent,
                    "environment": settings.environment
                }
            )
            
            # Return the agent ID that admin wants to act as
            return x_act_as_agent
        else:
            # Admin key used on agent endpoint without impersonation target
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="Admin API key requires X-Act-As-Agent header on agent endpoints. "
                       "Example: X-Act-As-Agent: did:cos:0a8daad0-c902-7878-d51c"
            )
    
    # NORMAL AGENT AUTHENTICATION
    # This is not the admin key, so proceed with normal agent authentication

    # OWL-FIX (2026-03-07): Try JWT decode first.
    # When OAUTH_FEDERATION_ENABLED=true, the registry proxy exchanges its JWT
    # for a proper TEG HS256 access token and sends it as a Bearer token.
    # Endpoints that import from core.security (not api.auth_enhanced) would
    # otherwise return the raw "eyJ..." string as agent_id, breaking the
    # claimant-match check in disputes and any other endpoint that compares
    # agent_id to a DID. Decode here so all legacy endpoints benefit.
    if token and len(token) > 20 and token.startswith("eyJ"):
        try:
            from .jwt_auth import jwt_service as _jwt_svc
            decoded_agent_id = _jwt_svc.verify_token(token)
            if decoded_agent_id:
                return decoded_agent_id
        except Exception:
            pass  # Not a valid local JWT — fall through to MVP prefix logic
    
    # MVP: Token IS the agent_id
    # Accept tokens that are either:
    # 1. Already prefixed with "agent_" (e.g., "agent_test1")
    # 2. Other test prefixes (e.g., "test_", "dispute_", "avtp_")
    # 3. DID format (e.g., "did:agentvault:alice")
    # 4. Simple alphanumeric IDs
    
    if not token:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Accept known DID formats only — reject arbitrary strings
    if (token.startswith("did:theprotocol:") or
        token.startswith("did:cos:") or
        token.startswith("did:agentvault:") or
        token.startswith("teg:system:") or
        token.startswith("teg_system_")):
        return token

    # Accept agent- prefixed client_ids (used by registry proxy via X-Act-As-Agent)
    if token.startswith("agent-"):
        return token

    # Reject all other tokens
    logger.warning(f"TEG auth rejected unknown token format (length={len(token)}, prefix={token[:10]})")
    raise HTTPException(
        status_code=HTTP_401_UNAUTHORIZED,
        detail="Invalid agent token format",
        headers={"WWW-Authenticate": "Bearer"},
    )


def verify_admin_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_optional),
) -> bool:
    """
    Verify an admin / internal-caller request.

    §2026-06-16 TEG-mTLS migration (Phase 1): delegates to the unified resolver, which makes
    mTLS SPIFFE the PRIMARY authenticator and the shared admin key a GATED fallback
    (env TEG_MTLS_REQUIRED). NON-BREAKING while TEG_MTLS_REQUIRED=false — the key still works
    and every key-fallback emits [TEG-AUTH-SHADOW] so we can prove key-fallback->0 before enforce.
    Flip TEG_MTLS_REQUIRED=true to disable the key fallback (enforce).

    Returns:
        bool: True if authenticated.
    Raises:
        HTTPException: 403 if neither a valid SVID nor (in shadow) the admin key is presented.
    """
    from .internal_auth import resolve_internal_caller
    token = credentials.credentials if credentials else ""
    resolve_internal_caller(request, token=token, route=request.url.path)
    return True


def get_optional_agent_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    x_act_as_agent: Optional[str] = Header(None)
) -> Optional[str]:
    """
    Get agent token if provided, otherwise return None.
    Used for endpoints that support both authenticated and anonymous access.
    
    Now supports admin impersonation via X-Act-As-Agent header.
    """
    if credentials is None:
        return None
    
    try:
        # Use the enhanced verify_agent_token that supports admin override
        return verify_agent_token(credentials, x_act_as_agent)
    except HTTPException:
        return None
