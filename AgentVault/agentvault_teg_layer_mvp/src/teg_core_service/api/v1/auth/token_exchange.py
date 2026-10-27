"""JWT Bearer Grant Token Exchange Endpoint for TEG Layer

Implements OAuth 2.0 JWT Bearer Token Grant (RFC 7523) for AgentVault v1.0.0 integration.
Part of REQ-INT-V1AUTH-001: Enterprise-Grade Authentication Bridge.

This module provides a token exchange endpoint that:
1. Accepts JWT-SVIDs from AgentVault Registry as bearer assertions
2. Validates the assertions against SPIRE trust bundles
3. Issues short-lived TEG-specific access tokens
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Form, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.status import (
    HTTP_400_BAD_REQUEST, 
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN
)

from ....core.secure_config import get_settings
from ....core.internal_auth import admin_key_ok  # §MONEY-M3a R26
from ....core.jwt_svid import JWTSVIDValidator, get_validator
from ....database.db_session import get_db
from ....database.crud import AgentCRUD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])
settings = get_settings()
bearer_scheme = HTTPBearer()

# Token configuration
TEG_TOKEN_EXPIRY_SECONDS = 3600  # 1 hour
TEG_TOKEN_ISSUER = "spiffe://agentvault.com/service/teg-core"
TEG_TOKEN_ALGORITHM = "HS256"

# Grant types
GRANT_TYPE_JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"


class TokenRequest(BaseModel):
    """OAuth 2.0 JWT Bearer Grant Token Request"""
    grant_type: str = Field(
        ..., 
        description="Must be 'urn:ietf:params:oauth:grant-type:jwt-bearer'"
    )
    assertion: str = Field(
        ..., 
        description="JWT-SVID assertion from AgentVault v1.0.0"
    )
    scope: Optional[str] = Field(
        default="teg:read teg:transfer",
        description="Requested scopes (space-separated)"
    )


class TokenResponse(BaseModel):
    """OAuth 2.0 Token Response"""
    access_token: str = Field(..., description="TEG Layer access token")
    token_type: str = Field(default="Bearer", description="Token type")
    expires_in: int = Field(..., description="Token lifetime in seconds")
    scope: str = Field(..., description="Granted scopes")


class TokenIntrospectionResponse(BaseModel):
    """OAuth 2.0 Token Introspection Response (RFC 7662)"""
    active: bool = Field(..., description="Whether the token is active")
    scope: Optional[str] = Field(None, description="Token scopes")
    client_id: Optional[str] = Field(None, description="Client identifier")
    username: Optional[str] = Field(None, description="Agent identifier")
    exp: Optional[int] = Field(None, description="Expiration timestamp")
    iat: Optional[int] = Field(None, description="Issued at timestamp")
    sub: Optional[str] = Field(None, description="Subject (agent SPIFFE ID)")
    aud: Optional[str] = Field(None, description="Audience")
    iss: Optional[str] = Field(None, description="Issuer")


class TEGTokenManager:
    """Manages TEG-specific access tokens"""
    
    def __init__(self):
        """Initialize token manager with signing key"""
        # In production, this should be loaded from secure storage
        # For now, using settings-based configuration
        _key = getattr(settings, 'teg_token_signing_key', None)
        self.signing_key = _key.get_secret_value() if hasattr(_key, 'get_secret_value') else (_key or secrets.token_urlsafe(32))
        # In-memory token store for MVP
        # Production should use Redis or similar
        self._active_tokens: Dict[str, Dict[str, Any]] = {}
    
    def create_access_token(
        self,
        agent_id: str,
        agent_spiffe_id: str,
        scopes: str = "teg:read teg:transfer",
        additional_claims: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create a TEG-specific access token.
        
        Args:
            agent_id: AgentVault agent identifier (e.g., email-based)
            agent_spiffe_id: Full SPIFFE ID of the agent
            scopes: Space-separated list of granted scopes
            additional_claims: Optional additional JWT claims
        
        Returns:
            Signed JWT access token
        """
        now = datetime.now(timezone.utc)
        exp = now + timedelta(seconds=TEG_TOKEN_EXPIRY_SECONDS)
        
        # Token ID for tracking
        jti = secrets.token_urlsafe(16)
        
        # Build claims
        claims = {
            "iss": TEG_TOKEN_ISSUER,
            "sub": agent_id,  # Use agent_id as subject for easier handling
            "aud": TEG_TOKEN_ISSUER,  # Audience is TEG itself
            "exp": int(exp.timestamp()),
            "iat": int(now.timestamp()),
            "jti": jti,
            "scope": scopes,
            "agent_spiffe_id": agent_spiffe_id,  # Include SPIFFE ID for audit
            "token_type": "teg_access"
        }
        
        # Add any additional claims
        if additional_claims:
            claims.update(additional_claims)
        
        # Sign token
        token = jwt.encode(claims, self.signing_key, algorithm=TEG_TOKEN_ALGORITHM)
        
        # Store token metadata for introspection
        self._active_tokens[jti] = {
            "agent_id": agent_id,
            "agent_spiffe_id": agent_spiffe_id,
            "scopes": scopes,
            "issued_at": now,
            "expires_at": exp,
            "active": True
        }
        
        logger.info(f"Issued TEG access token for agent: {agent_id} (jti: {jti})")
        
        return token
    
    def validate_access_token(self, token: str) -> Dict[str, Any]:
        """
        Validate a TEG access token.
        
        Args:
            token: JWT access token
        
        Returns:
            Validated token claims
        
        Raises:
            HTTPException: If token is invalid
        """
        try:
            # Decode and verify token
            claims = jwt.decode(
                token,
                self.signing_key,
                algorithms=[TEG_TOKEN_ALGORITHM],
                audience=TEG_TOKEN_ISSUER
            )
            
            # Check token type
            if claims.get("token_type") != "teg_access":
                raise ValueError("Invalid token type")
            
            # Check if token is still active (not revoked)
            jti = claims.get("jti")
            if jti and jti in self._active_tokens:
                if not self._active_tokens[jti]["active"]:
                    raise ValueError("Token has been revoked")
            
            return claims
            
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"}
            )
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"}
            )
        except Exception as e:
            logger.error(f"Token validation error: {e}")
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Token validation failed",
                headers={"WWW-Authenticate": "Bearer"}
            )
    
    def introspect_token(self, token: str) -> TokenIntrospectionResponse:
        """
        Introspect a token (RFC 7662).
        
        Args:
            token: Token to introspect
        
        Returns:
            Token introspection response
        """
        try:
            claims = self.validate_access_token(token)
            
            return TokenIntrospectionResponse(
                active=True,
                scope=claims.get("scope"),
                username=claims.get("sub"),
                exp=claims.get("exp"),
                iat=claims.get("iat"),
                sub=claims.get("agent_spiffe_id"),
                aud=claims.get("aud"),
                iss=claims.get("iss")
            )
        except:
            # Invalid tokens return inactive
            return TokenIntrospectionResponse(active=False)
    
    def revoke_token(self, jti: str):
        """Revoke a token by its JTI"""
        if jti in self._active_tokens:
            self._active_tokens[jti]["active"] = False
            logger.info(f"Revoked token: {jti}")


# Global token manager instance
_token_manager = TEGTokenManager()


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="OAuth 2.0 JWT Bearer Grant Token Exchange",
    responses={
        400: {"description": "Invalid request"},
        401: {"description": "Invalid assertion"}
    }
)
async def token_exchange(
    request: TokenRequest,
    db: Session = Depends(get_db)
):
    """
    Exchange a JWT-SVID assertion for a TEG-specific access token.
    
    Implements RFC 7523 - JWT Bearer Token Grant Type.
    
    The AgentVault Registry backend calls this endpoint with a JWT-SVID
    assertion on behalf of an authenticated v1.0.0 agent. The TEG Layer
    validates the assertion and issues a short-lived access token specific
    to TEG operations.
    
    Security:
    - Validates JWT-SVID signature against SPIRE trust bundles
    - Checks audience claim matches TEG Core Service
    - Ensures agent exists in TEG database
    - Issues time-limited access tokens with specific scopes
    """
    # Validate grant type
    if request.grant_type != GRANT_TYPE_JWT_BEARER:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Unsupported grant type. Must be '{GRANT_TYPE_JWT_BEARER}'"
        )
    
    # Get JWT-SVID validator
    validator = get_validator()
    
    try:
        # Validate the JWT-SVID assertion
        claims = validator.validate_jwt_svid(
            request.assertion,
            expected_audience="spiffe://agentvault.com/service/teg-core"
        )
        
        # Extract agent SPIFFE ID
        agent_spiffe_id = claims["sub"]
        
        # Convert SPIFFE ID to agent ID
        # spiffe://agentvault.com/agent/test_at_example.com -> test@example.com
        if not agent_spiffe_id.startswith("spiffe://agentvault.com/agent/"):
            raise ValueError(f"Invalid agent SPIFFE ID format: {agent_spiffe_id}")
        
        agent_local_id = agent_spiffe_id.split("/agent/")[1]
        # Convert from safe format back to email
        agent_email = agent_local_id.replace("_at_", "@").replace("_dot_", ".")
        
        # Ensure agent exists in TEG database
        agent = AgentCRUD.get_or_create_agent(
            db,
            agent_id=f"did:agentvault:{agent_local_id}",
            initial_balance=0,
            initial_reputation=0
        )
        
        logger.info(f"Token exchange for agent: {agent_email} ({agent_spiffe_id})")
        
        # Parse requested scopes
        requested_scopes = request.scope.split() if request.scope else ["teg:read"]
        
        # Validate scopes (in production, check against agent permissions)
        allowed_scopes = ["teg:read", "teg:transfer", "teg:reputation"]
        granted_scopes = [s for s in requested_scopes if s in allowed_scopes]
        
        if not granted_scopes:
            granted_scopes = ["teg:read"]  # Default minimal scope
        
        # Issue TEG-specific access token
        access_token = _token_manager.create_access_token(
            agent_id=f"did:agentvault:{agent_local_id}",
            agent_spiffe_id=agent_spiffe_id,
            scopes=" ".join(granted_scopes),
            additional_claims={
                "email": agent_email,
                "registry_backend": True  # Indicates token was issued via registry
            }
        )
        
        return TokenResponse(
            access_token=access_token,
            token_type="Bearer",
            expires_in=TEG_TOKEN_EXPIRY_SECONDS,
            scope=" ".join(granted_scopes)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token exchange failed: {e}")
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid assertion"
        )


@router.post(
    "/introspect",
    response_model=TokenIntrospectionResponse,
    summary="OAuth 2.0 Token Introspection",
    include_in_schema=False  # Internal endpoint
)
async def introspect_token(
    token: str = Form(..., description="Token to introspect"),
    authorization: Optional[str] = Header(None)
):
    """
    Introspect a TEG access token (RFC 7662).
    
    This endpoint allows authorized clients to query the status of a token.
    In production, this would require client authentication.
    """
    # In production, verify the caller is authorized to introspect
    # For MVP, we'll allow introspection with admin key
    if authorization:
        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header"
            )
        
        admin_key = authorization.replace("Bearer ", "")
        if not admin_key_ok(admin_key):  # §MONEY-M3a R26
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail="Not authorized to introspect tokens"
            )
    
    return _token_manager.introspect_token(token)


def verify_teg_access_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)
) -> str:
    """
    FastAPI dependency to verify TEG access tokens.
    
    This replaces the JWT-SVID verification for endpoints that accept
    TEG-issued access tokens from the token exchange.
    
    Returns:
        Agent ID extracted from the token
    """
    token = credentials.credentials
    
    try:
        claims = _token_manager.validate_access_token(token)
        
        # Check required scopes based on endpoint (handled by endpoint decorators)
        # For now, just return the agent ID
        agent_id = claims["sub"]
        
        logger.debug(f"Authenticated agent via TEG token: {agent_id}")
        
        return agent_id
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TEG token verification failed: {e}")
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"}
        )


# Make verify_teg_access_token available as the new default token verifier
verify_token = verify_teg_access_token
