"""Authentication utilities for TEG Core Service

This module provides authentication verification functions for:
- Admin API key authentication
- TEG access token verification
- AVTP system authentication

ENHANCED: Supports admin impersonation via X-Act-As-Agent header
"""
from typing import Optional, Annotated
from fastapi import Depends, HTTPException, Header, Request, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN, HTTP_400_BAD_REQUEST

from ..core.config import get_settings
from ..core.jwt_auth import jwt_service
from ..core.internal_auth import admin_key_ok  # §MONEY-M3a R26
import logging

settings = get_settings()
logger = logging.getLogger(__name__)

# Security schemes
security = HTTPBearer()


def verify_admin_key(
    request: Request,
    authorization: Annotated[Optional[str], Header(alias="Authorization")] = None,
) -> bool:
    """
    Verify an admin / internal-caller request.

    §2026-06-16 TEG-mTLS migration (Phase 1): delegates to the unified resolver — mTLS SPIFFE
    primary, shared admin key gated fallback (env TEG_MTLS_REQUIRED). NON-BREAKING in shadow;
    every key-fallback emits [TEG-AUTH-SHADOW]. Legacy format still accepted: Bearer <admin_api_key>.
    """
    from ..core.internal_auth import resolve_internal_caller
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):]
    resolve_internal_caller(request, token=token, route=request.url.path)
    return True


def verify_avtp_system_key(x_avtp_system_key: Optional[str] = Header(None)) -> bool:
    """
    Verify AVTP system API key from X-AVTP-System-Key header.
    """
    if not x_avtp_system_key:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Missing AVTP system key"
        )
    
    # Constant-time, and closed when no key is configured. 2026-09-25.
    import hmac as _hmac
    _expected = str(settings.avtp_system_api_key or "")
    if not _expected or not _hmac.compare_digest(str(x_avtp_system_key), _expected):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Invalid AVTP system key"
        )
    
    return True


async def verify_token(token: str) -> bool:
    """Helper function to verify token validity"""
    if not token or token == "invalid_token":
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    return True


def verify_teg_access_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    x_act_as_agent: Annotated[Optional[str], Header(description="Admin: Agent ID to impersonate")] = None
) -> str:
    """
    Verify TEG access token and return the agent_id.
    
    ENHANCED: Supports admin impersonation in development mode.
    
    Admin Override (DEV ONLY):
    - Use admin API key as Bearer token
    - Add header: X-Act-As-Agent: did:cos:0a8daad0-c902-7878-d51c
    - Admin can then act as any agent
    
    This function enforces strict JWT validation unless admin override is used:
    - Verifies JWT signature
    - Checks token expiration
    - Validates token type
    - Extracts agent_id from token claims
    
    Returns:
        str: The agent_id (either from JWT or admin override)
    
    Raises:
        HTTPException: 401 if token is invalid, expired, or not a proper JWT
    """
    token = credentials.credentials
    
    # Basic validation
    if not token or len(token) < 10:
        logger.warning("Rejected token: too short or missing")
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
        )
    
    # ADMIN OVERRIDE CHECK (Same logic as in core/security.py)
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
    
    # NORMAL JWT VALIDATION - strict mode only
    agent_id = jwt_service.verify_token(token)
    
    if agent_id:
        return agent_id
    else:
        # Log the rejection for debugging
        logger.warning(f"Rejected invalid JWT token: {token[:20]}...")
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token"
        )


# Enhanced get_current_agent with admin impersonation support
def get_current_agent(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    x_act_as_agent: Annotated[Optional[str], Header(description="Admin: Agent ID to impersonate")] = None
) -> str:
    """
    Get current agent ID with admin impersonation support.
    
    This is an alias for verify_teg_access_token that includes
    the X-Act-As-Agent header for admin impersonation.
    """
    return verify_teg_access_token(credentials, x_act_as_agent)


# Dependency aliases for cleaner imports
AdminAuth = Annotated[bool, Security(verify_admin_key)]
AVTPAuth = Annotated[bool, Security(verify_avtp_system_key)]
AgentAuth = Annotated[str, Security(verify_teg_access_token)]
