"""Multi-Issuer JWT Authentication Service

This module implements JWT validation for tokens from multiple registries,
supporting the OAuth federation model where agents authenticate to their
home registry but can transact across registry boundaries.
"""
import jwt
import httpx
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Set
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import BaseModel
import logging
import json
from functools import lru_cache
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.status import HTTP_401_UNAUTHORIZED

logger = logging.getLogger(__name__)

# Security scheme for FastAPI
security = HTTPBearer()


class JWKSKey(BaseModel):
    """JSON Web Key representation"""
    kty: str  # Key type (RSA)
    use: str  # Key use (sig)
    kid: str  # Key ID
    n: str    # RSA modulus
    e: str    # RSA exponent
    alg: Optional[str] = "RS256"  # Algorithm


class JWKSResponse(BaseModel):
    """JWKS endpoint response"""
    keys: List[JWKSKey]


class TrustedRegistry(BaseModel):
    """Configuration for a trusted registry"""
    name: str
    issuer: str  # The issuer URL that appears in JWT 'iss' claim
    jwks_uri: str  # URL to fetch public keys
    allowed_audiences: Set[str] = {"teg", "cross-registry"}  # Valid 'aud' claims
    cache_ttl: int = 3600  # Cache JWKS for 1 hour


class TokenClaims(BaseModel):
    """Standard JWT claims we expect"""
    iss: str  # Issuer
    sub: str  # Subject (agent DID)
    aud: str  # Audience
    exp: datetime  # Expiration
    iat: datetime  # Issued at
    jti: Optional[str] = None  # JWT ID (for single-use tokens)
    scope: Optional[str] = None  # OAuth scope
    token_type: Optional[str] = None  # Token type
    
    # For cross-registry tokens
    actor: Optional[Dict[str, Any]] = None  # Original token info
    constraints: Optional[Dict[str, Any]] = None  # Transfer constraints


class MultiIssuerJWTService:
    """Service for validating JWT tokens from multiple registries"""
    
    def __init__(self, trusted_registries: List[TrustedRegistry]):
        """
        Initialize with a list of trusted registries.
        
        Args:
            trusted_registries: List of registry configurations
        """
        self.trusted_registries = {reg.issuer: reg for reg in trusted_registries}
        self._jwks_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
        self._client = httpx.AsyncClient(timeout=10.0)
        self._used_jtis: Set[str] = set()  # Track used single-use tokens
        
    async def __aenter__(self):
        """Async context manager entry"""
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup HTTP client"""
        await self._client.aclose()
        
    async def _fetch_jwks(self, jwks_uri: str) -> Dict[str, Any]:
        """
        Fetch JWKS from registry endpoint.
        
        Args:
            jwks_uri: URL to JWKS endpoint
            
        Returns:
            Dict mapping key ID to public key
        """
        try:
            response = await self._client.get(jwks_uri)
            response.raise_for_status()
            
            jwks_data = response.json()
            jwks = JWKSResponse(**jwks_data)
            
            # Convert JWKS to dict of kid -> public_key
            keys = {}
            for key in jwks.keys:
                if key.kty == "RSA" and key.use == "sig":
                    # Convert JWK to PEM format for PyJWT
                    public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key.model_dump())
                    keys[key.kid] = public_key
                    
            return keys
            
        except Exception as e:
            logger.error(f"Failed to fetch JWKS from {jwks_uri}: {e}")
            raise
            
    async def _get_public_keys(self, issuer: str) -> Dict[str, Any]:
        """
        Get public keys for an issuer, using cache if available.
        
        Args:
            issuer: Token issuer
            
        Returns:
            Dict mapping key ID to public key
        """
        registry = self.trusted_registries.get(issuer)
        if not registry:
            raise ValueError(f"Unknown issuer: {issuer}")
            
        # Check cache
        cache_key = registry.jwks_uri
        if cache_key in self._jwks_cache:
            cache_time = self._cache_timestamps.get(cache_key)
            if cache_time and (datetime.now(timezone.utc) - cache_time).seconds < registry.cache_ttl:
                logger.debug(f"Using cached JWKS for {issuer}")
                return self._jwks_cache[cache_key]
                
        # Fetch fresh JWKS
        logger.info(f"Fetching JWKS for {issuer} from {registry.jwks_uri}")
        keys = await self._fetch_jwks(registry.jwks_uri)
        
        # Update cache
        self._jwks_cache[cache_key] = keys
        self._cache_timestamps[cache_key] = datetime.now(timezone.utc)
        
        return keys
        
    async def verify_token(self, token: str) -> Optional[TokenClaims]:
        """
        Verify JWT token from any trusted registry.
        
        Args:
            token: JWT token string
            
        Returns:
            TokenClaims if valid, None if invalid
        """
        try:
            # Decode without verification first to get the issuer
            unverified = jwt.decode(token, options={"verify_signature": False})
            issuer = unverified.get("iss")
            
            if not issuer or issuer not in self.trusted_registries:
                logger.warning(f"Token from unknown issuer: {issuer}")
                return None
                
            registry = self.trusted_registries[issuer]
            
            # Get public keys for this issuer
            public_keys = await self._get_public_keys(issuer)
            
            # Try to verify with each key (key rotation support)
            last_error = None
            for kid, public_key in public_keys.items():
                try:
                    # Verify token with public key
                    payload = jwt.decode(
                        token,
                        public_key,
                        algorithms=["RS256"],
                        audience=list(registry.allowed_audiences),
                        issuer=issuer
                    )
                    
                    # Check single-use token
                    jti = payload.get("jti")
                    if jti:
                        if jti in self._used_jtis:
                            logger.warning(f"Single-use token already used: {jti}")
                            return None
                        self._used_jtis.add(jti)
                    
                    # Convert to TokenClaims
                    claims = TokenClaims(
                        iss=payload["iss"],
                        sub=payload["sub"],
                        aud=payload["aud"],
                        exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
                        iat=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
                        jti=jti,
                        scope=payload.get("scope"),
                        token_type=payload.get("token_type"),
                        actor=payload.get("actor"),
                        constraints=payload.get("constraints")
                    )
                    
                    logger.info(f"Successfully verified token from {issuer} for {claims.sub}")
                    return claims
                    
                except jwt.InvalidTokenError as e:
                    last_error = e
                    continue
                    
            # If we get here, no key could verify the token
            logger.error(f"Token verification failed for {issuer}: {last_error}")
            return None
            
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            return None
            
    async def cleanup_expired_jtis(self):
        """
        Periodic cleanup of used JTI set to prevent memory growth.
        Should be called periodically (e.g., every hour).
        """
        # In production, you'd want to track expiration times
        # For now, we'll clear JTIs older than 1 hour
        logger.info(f"Cleaning up JTI cache, current size: {len(self._used_jtis)}")
        # Simple implementation - in production, track timestamps
        if len(self._used_jtis) > 10000:
            self._used_jtis.clear()


class MultiIssuerAuthMiddleware:
    """
    FastAPI dependency for multi-issuer JWT authentication.
    
    This replaces the single-issuer verify_teg_access_token function
    to support tokens from multiple registries.
    """
    
    def __init__(self, jwt_service: MultiIssuerJWTService):
        self.jwt_service = jwt_service
        
    async def __call__(
        self, 
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ) -> str:
        """
        Verify token and return agent_id.
        
        Args:
            credentials: Bearer token from Authorization header
            
        Returns:
            str: Agent ID (DID) from token subject
            
        Raises:
            HTTPException: 401 if token is invalid
        """
        token = credentials.credentials
        
        # Basic validation
        if not token or len(token) < 10:
            logger.warning("Rejected token: too short or missing")
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token"
            )
            
        # Verify token with multi-issuer support
        claims = await self.jwt_service.verify_token(token)
        
        if claims:
            # For cross-registry tokens, the subject is the agent DID
            return claims.sub
        else:
            logger.warning(f"Rejected invalid token: {token[:20]}...")
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication token"
            )


# Factory function to create the service from configuration
async def create_multi_issuer_jwt_service(trusted_registries_config: List[Dict[str, Any]]) -> MultiIssuerJWTService:
    """
    Create MultiIssuerJWTService from configuration.
    
    Args:
        trusted_registries_config: List of registry configurations
        
    Returns:
        Configured MultiIssuerJWTService instance
    """
    registries = []
    for config in trusted_registries_config:
        registry = TrustedRegistry(
            name=config["name"],
            issuer=config["issuer"],
            jwks_uri=config["jwks_uri"],
            allowed_audiences=set(config.get("allowed_audiences", ["teg", "cross-registry"]))
        )
        registries.append(registry)
        
    return MultiIssuerJWTService(registries)


# Example usage in FastAPI:
# 
# from fastapi import FastAPI, Depends
# from ..core.oauth.multi_issuer_jwt import (
#     create_multi_issuer_jwt_service, 
#     MultiIssuerAuthMiddleware
# )
# 
# app = FastAPI()
# 
# # During startup
# @app.on_event("startup")
# async def startup():
#     config = [
#         {
#             "name": "Registry A",
#             "issuer": "http://registry-a:8000",
#             "jwks_uri": "http://registry-a:8000/api/v1/oauth/.well-known/jwks.json"
#         },
#         {
#             "name": "Registry B", 
#             "issuer": "http://registry-b:8000",
#             "jwks_uri": "http://registry-b:8000/api/v1/oauth/.well-known/jwks.json"
#         }
#     ]
#     jwt_service = await create_multi_issuer_jwt_service(config)
#     app.state.jwt_service = jwt_service
#     app.state.multi_auth = MultiIssuerAuthMiddleware(jwt_service)
# 
# # In endpoints
# @app.get("/protected")
# async def protected_endpoint(
#     agent_id: str = Depends(app.state.multi_auth)
# ):
#     return {"agent_id": agent_id}
