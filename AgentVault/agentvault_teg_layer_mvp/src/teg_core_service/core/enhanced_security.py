"""
Enhanced security utilities for TEG Core Service

Provides:
- Token authentication and validation
- Security headers middleware
- Request validation
- Admin authentication
"""
import secrets
from typing import Optional, Dict

from fastapi import HTTPException, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from ..core.secure_config import get_settings

security = HTTPBearer()
settings = get_settings()


class SecurityHeaders:
    """Security headers to apply to all responses"""
    
    @staticmethod
    def get_headers() -> Dict[str, str]:
        """Get security headers based on environment"""
        headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()"
        }
        
        # Add HSTS in production
        if settings.environment == "production":
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        return headers


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to all responses"""
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Add security headers
        for header, value in SecurityHeaders.get_headers().items():
            response.headers[header] = value
        
        return response


def verify_agent_token(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    """
    Verify agent authentication token.
    
    For MVP: Simple bearer token that contains the agent_id directly.
    In production, this would validate against AgentVault v1.0.0.
    
    Args:
        credentials: HTTP authorization credentials
    
    Returns:
        str: The authenticated agent_id
    
    Raises:
        HTTPException: If authentication fails
    """
    token = credentials.credentials
    
    # Basic token validation
    if not token:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Authentication token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # MVP: Token IS the agent_id (prefixed with "agent_")
    # In production, this would validate the token and extract agent_id
    if not token.startswith("agent_"):
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token format",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Additional validation could include:
    # - Token length checks
    # - Character validation
    # - Cache/DB lookup for valid tokens
    
    agent_id = token
    return agent_id


def verify_admin_token(credentials: HTTPAuthorizationCredentials = Security(security)) -> bool:
    """
    Verify admin authentication token with constant-time comparison.
    
    Args:
        credentials: HTTP authorization credentials
    
    Returns:
        bool: True if authenticated as admin
    
    Raises:
        HTTPException: If authentication fails
    """
    token = credentials.credentials
    
    if not token:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Admin authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Use constant-time comparison to prevent timing attacks
    from .internal_auth import admin_key_ok  # §MONEY-M3a R26
    if not admin_key_ok(token):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return True


def verify_avtp_system_token(credentials: HTTPAuthorizationCredentials = Security(security)) -> bool:
    """
    Verify AVTP system integration token with constant-time comparison.
    
    Args:
        credentials: HTTP authorization credentials
    
    Returns:
        bool: True if authenticated as AVTP system
    
    Raises:
        HTTPException: If authentication fails
    """
    token = credentials.credentials
    
    if not token:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="AVTP system authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Use constant-time comparison to prevent timing attacks
    avtp_key = settings.avtp_system_api_key.get_secret_value()
    if not secrets.compare_digest(token, avtp_key):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Invalid AVTP system credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return True


def get_optional_agent_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security)
) -> Optional[str]:
    """
    Get agent token if provided, otherwise return None.
    Used for endpoints that support both authenticated and anonymous access.
    
    Args:
        credentials: Optional HTTP authorization credentials
    
    Returns:
        Optional[str]: The authenticated agent_id or None
    """
    if credentials is None:
        return None
    
    try:
        return verify_agent_token(credentials)
    except HTTPException:
        return None


def validate_agent_id_format(agent_id: str) -> bool:
    """
    Validate agent ID format.
    
    Args:
        agent_id: Agent identifier to validate
    
    Returns:
        bool: True if valid format
    """
    if not agent_id:
        return False
    
    # MVP: Simple validation for agent_ prefix
    # Production would have more sophisticated validation
    if not agent_id.startswith("agent_"):
        return False
    
    # Check minimum length
    if len(agent_id) < 7:  # "agent_" + at least 1 char
        return False
    
    # Check for valid characters (alphanumeric and underscore)
    suffix = agent_id[6:]  # After "agent_"
    if not suffix.replace("_", "").replace("-", "").isalnum():
        return False
    
    return True


def validate_did_format(did: str) -> bool:
    """
    Validate DID format.
    
    Args:
        did: DID to validate
    
    Returns:
        bool: True if valid format
    """
    if not did:
        return False
    
    # Basic DID validation
    if not did.startswith("did:"):
        return False
    
    parts = did.split(":")
    if len(parts) < 3:
        return False
    
    # Validate AgentVault DIDs specifically
    if parts[1] == "agentvault":
        # Check for valid identifier
        identifier = ":".join(parts[2:])
        if not identifier or not identifier.replace("_", "").replace("-", "").isalnum():
            return False
    
    return True
