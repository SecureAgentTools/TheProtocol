"""Enhanced Authentication Module with Multi-Issuer Support

This module provides both single-issuer (backward compatible) and multi-issuer
authentication for the TEG Core Service, supporting OAuth federation.
"""
from typing import Optional, Annotated, Union
from fastapi import Depends, HTTPException, Header, Request, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials  
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

from ..core.secure_config import get_settings
from ..core.jwt_auth import jwt_service as single_issuer_jwt_service
from ..core.oauth import MultiIssuerJWTService, MultiIssuerAuthMiddleware, create_multi_issuer_jwt_service
import logging
import asyncio

settings = get_settings()
logger = logging.getLogger(__name__)

# Security schemes
security = HTTPBearer()

# Global multi-issuer JWT service (initialized on startup)
_multi_issuer_jwt_service: Optional[MultiIssuerJWTService] = None
_multi_issuer_auth_middleware: Optional[MultiIssuerAuthMiddleware] = None


async def initialize_multi_issuer_auth():
    """Initialize multi-issuer authentication if enabled"""
    global _multi_issuer_jwt_service, _multi_issuer_auth_middleware
    
    if settings.oauth_federation_enabled and settings.parsed_trusted_registries:
        logger.info("Initializing multi-issuer OAuth federation support")
        logger.info(f"Trusted registries: {[r['name'] for r in settings.parsed_trusted_registries]}")
        
        _multi_issuer_jwt_service = await create_multi_issuer_jwt_service(
            settings.parsed_trusted_registries
        )
        _multi_issuer_auth_middleware = MultiIssuerAuthMiddleware(_multi_issuer_jwt_service)
        
        # Start periodic JTI cleanup task
        asyncio.create_task(_jti_cleanup_task())
    else:
        logger.info("OAuth federation disabled - using single-issuer authentication")


async def _jti_cleanup_task():
    """Periodic cleanup of used JWT IDs"""
    while True:
        await asyncio.sleep(3600)  # Run every hour
        if _multi_issuer_jwt_service:
            await _multi_issuer_jwt_service.cleanup_expired_jtis()


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
    
    if x_avtp_system_key != settings.avtp_system_api_key.get_secret_value():
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


def verify_teg_access_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """
    Verify TEG access token and return the agent_id.
    
    OWL-BRIDGE FIX: Always try single-issuer (local HS256 TEG tokens) first,
    then fall back to multi-issuer error if OAuth is enabled.
    Sync version — for async multi-issuer support, use verify_teg_access_token_async.
    
    Returns:
        str: The agent_id extracted from the token
    
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
    
    # ALWAYS try single-issuer first (local TEG tokens from /auth/token)
    agent_id = single_issuer_jwt_service.verify_token(token)
    if agent_id:
        return agent_id
    
    # Single-issuer failed — if OAuth federation is enabled, must use async version
    if settings.oauth_federation_enabled:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Multi-issuer auth requires async dependency - use verify_teg_access_token_async"
        )
    
    # Nothing worked
    logger.warning(f"Rejected invalid JWT token: {token[:20]}...")
    raise HTTPException(
        status_code=HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token"
    )


async def verify_teg_access_token_async(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """
    Async version of token verification supporting multi-issuer mode.
    
    OWL-BRIDGE FIX: Always try single-issuer (local HS256 TEG tokens) first,
    then fall back to multi-issuer (cross-registry RS256 OAuth tokens) if
    OAuth federation is enabled. Previously, enabling OAuth federation caused
    single-issuer validation to be completely skipped, breaking cross-TEG
    transfer initiation from the local registry's own proxy endpoint.
    """
    token = credentials.credentials
    
    # Basic validation
    if not token or len(token) < 10:
        logger.warning("Rejected token: too short or missing")
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
        )
    
    # ALWAYS try single-issuer first (local TEG tokens from /auth/token)
    agent_id = single_issuer_jwt_service.verify_token(token)
    if agent_id:
        return agent_id
    
    # Single-issuer failed — if OAuth federation is enabled, try multi-issuer
    if settings.oauth_federation_enabled:
        if not _multi_issuer_auth_middleware:
            logger.error("OAuth federation enabled but not initialized")
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Authentication system not ready"
            )
        return await _multi_issuer_auth_middleware(credentials)
    
    # Nothing worked
    logger.warning(f"Rejected invalid JWT token: {token[:20]}...")
    raise HTTPException(
        status_code=HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token"
    )


# Dependency aliases for cleaner imports
AdminAuth = Annotated[bool, Security(verify_admin_key)]
AVTPAuth = Annotated[bool, Security(verify_avtp_system_key)]

# Use async version when OAuth federation is enabled
if settings.oauth_federation_enabled:
    AgentAuth = Annotated[str, Security(verify_teg_access_token_async)]
    get_current_agent = verify_teg_access_token_async
else:
    AgentAuth = Annotated[str, Security(verify_teg_access_token)]
    get_current_agent = verify_teg_access_token


# Cleanup function for shutdown
async def cleanup_multi_issuer_auth():
    """Cleanup multi-issuer authentication resources"""
    global _multi_issuer_jwt_service, _multi_issuer_auth_middleware
    
    if _multi_issuer_jwt_service:
        await _multi_issuer_jwt_service.__aexit__(None, None, None)
        _multi_issuer_jwt_service = None
        _multi_issuer_auth_middleware = None
