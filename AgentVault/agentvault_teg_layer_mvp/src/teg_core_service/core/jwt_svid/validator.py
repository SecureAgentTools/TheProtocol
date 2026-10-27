"""JWT-SVID validation utilities for TEG Core Service

This module provides functionality to validate JWT-SVIDs issued by SPIRE
for agent authentication.

Part of REQ-INT-V1AUTH-001 implementation.
"""

import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# §DEPS (2026-09-27, his words "the no jwt fallback path trap needs deletion. shouldnt be possible"): there is NO
# fallback. Until then, a missing pyspiffe sent every token to an HS256 check against JWT_SVID_SIGNING_KEY, whose
# default was "" — and PyJWT accepts an empty HMAC key, so anyone could sign a JWT-SVID for any agent. The images ship
# the `spiffe` package, never `pyspiffe`, so that branch was the ONLY one any TEG could take with USE_JWT_SVID_AUTH=true
# (unset on all 13 TEGs on 2026-09-27, so it never ran). Without a real JWT-SVID validator every token is refused.
try:
    from pyspiffe import workload_api
    from pyspiffe.bundle import JwtBundle
    from pyspiffe.svid import JwtSvid
    PYSPIFFE_AVAILABLE = True
except ImportError:
    PYSPIFFE_AVAILABLE = False
    logging.warning("pySpiffe not available - JWT-SVID authentication refuses every token (there is no fallback)")

logger = logging.getLogger(__name__)

# Security scheme for JWT Bearer tokens
security = HTTPBearer()

# Expected audience for JWT-SVIDs
EXPECTED_AUDIENCE = "spiffe://agentvault.com/service/teg-core"

# Trust domain
TRUST_DOMAIN = "agentvault.com"


class JWTSVIDValidator:
    """Validator for JWT-SVIDs using SPIRE trust bundles"""
    
    def __init__(self, workload_api_socket: Optional[str] = None):
        """
        Initialize JWT-SVID validator.
        
        Args:
            workload_api_socket: Path to SPIRE Agent workload API socket.
                                Defaults to SPIRE_AGENT_SOCKET env var.
        """
        self.socket_path = workload_api_socket or os.environ.get(
            'SPIRE_AGENT_SOCKET', 
            '/tmp/spire-agent/public/api.sock'
        )
        self._jwt_bundle = None
        self._workload_client = None
        
    def _get_jwt_bundle(self) -> Any:
        """Get JWT bundle for trust domain"""
        if not PYSPIFFE_AVAILABLE:
            raise RuntimeError("pySpiffe is not installed - cannot validate JWT-SVIDs")
        
        if self._jwt_bundle is None:
            try:
                # Create workload API client
                self._workload_client = workload_api.WorkloadApiClient(
                    spiffe_socket=self.socket_path
                )
                
                # Fetch JWT bundles
                jwt_bundles = self._workload_client.fetch_jwt_bundles()
                
                # Get bundle for our trust domain
                self._jwt_bundle = jwt_bundles.get(TRUST_DOMAIN)
                
                if not self._jwt_bundle:
                    raise RuntimeError(f"No JWT bundle found for trust domain: {TRUST_DOMAIN}")
                
                logger.info(f"Loaded JWT bundle for trust domain: {TRUST_DOMAIN}")
                
            except Exception as e:
                logger.error(f"Failed to fetch JWT bundle: {e}")
                raise RuntimeError(f"Cannot fetch SPIRE JWT bundle: {e}")
        
        return self._jwt_bundle
    
    def validate_jwt_svid(self, token: str, expected_audience: str = EXPECTED_AUDIENCE) -> Dict[str, Any]:
        """
        Validate a JWT-SVID token.
        
        Args:
            token: JWT-SVID token string
            expected_audience: Expected audience claim
        
        Returns:
            Dict containing validated claims, including 'sub' (agent SPIFFE ID)
        
        Raises:
            HTTPException: If validation fails
        """
        if PYSPIFFE_AVAILABLE:
            try:
                # Get JWT bundle
                jwt_bundle = self._get_jwt_bundle()
                
                # Parse and validate JWT-SVID
                jwt_svid = JwtSvid.parse_insecure(token, [expected_audience])
                
                # Validate using bundle
                # Note: pyspiffe's validate method checks signature, expiry, and audience
                jwt_svid.validate(jwt_bundle)
                
                # Extract claims
                claims = {
                    "sub": jwt_svid.spiffe_id.to_string(),
                    "aud": jwt_svid.audience,
                    "exp": jwt_svid.expiry.timestamp() if jwt_svid.expiry else None
                }
                
                logger.info(f"Successfully validated JWT-SVID for: {claims['sub']}")
                
                return claims
                
            except Exception as e:
                logger.error(f"JWT-SVID validation failed: {e}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authentication token",
                    headers={"WWW-Authenticate": "Bearer"}
                )
        # §DEPS: no JWT-SVID validator, no authentication. Refused, never downgraded to a weaker check.
        logger.error("JWT-SVID token refused: pySpiffe is not installed, so no token can be validated")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT-SVID validation is unavailable on this TEG",
            headers={"WWW-Authenticate": "Bearer"}
        )

    def close(self):
        """Close workload API client"""
        if self._workload_client:
            try:
                self._workload_client.close()
                logger.info("Closed SPIRE Workload API client")
            except Exception as e:
                logger.error(f"Error closing Workload API client: {e}")
            finally:
                self._workload_client = None
                self._jwt_bundle = None


# Global validator instance
_validator: Optional[JWTSVIDValidator] = None


def get_validator() -> JWTSVIDValidator:
    """Get or create the global JWT-SVID validator"""
    global _validator
    
    if _validator is None:
        _validator = JWTSVIDValidator()
    
    return _validator


def verify_jwt_svid(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    """
    FastAPI dependency to verify JWT-SVID authentication.
    
    This replaces the simple bearer token validation with proper
    JWT-SVID validation against SPIRE trust bundles.
    
    Args:
        credentials: Bearer token from Authorization header
    
    Returns:
        str: The authenticated agent's SPIFFE ID
    
    Raises:
        HTTPException: If authentication fails
    """
    token = credentials.credentials
    
    # Get validator
    validator = get_validator()
    
    # Validate JWT-SVID
    try:
        claims = validator.validate_jwt_svid(token)
        
        # Extract agent SPIFFE ID from subject claim
        agent_spiffe_id = claims["sub"]
        
        # Convert SPIFFE ID to agent ID format used by TEG
        # spiffe://agentvault.com/agent/test_at_example.com -> agent_test_at_example.com
        if agent_spiffe_id.startswith(f"spiffe://{TRUST_DOMAIN}/agent/"):
            agent_local_id = agent_spiffe_id.split("/agent/")[1]
            # Convert back from safe format to email format if needed
            agent_id = f"agent_{agent_local_id}"
        else:
            # Shouldn't happen if validation passed
            raise ValueError(f"Invalid agent SPIFFE ID format: {agent_spiffe_id}")
        
        logger.debug(f"Authenticated agent via JWT-SVID: {agent_id} (SPIFFE ID: {agent_spiffe_id})")
        
        return agent_id
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"JWT-SVID verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"}
        )


def get_optional_jwt_svid(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security)
) -> Optional[str]:
    """
    Get agent ID from JWT-SVID if provided, otherwise return None.
    
    Used for endpoints that support both authenticated and anonymous access.
    """
    if credentials is None:
        return None
    
    try:
        return verify_jwt_svid(credentials)
    except HTTPException:
        return None


# Enhanced admin verification that checks mTLS client certificate
def verify_admin_with_mtls(
    credentials: HTTPAuthorizationCredentials = Security(security),
    # In a real implementation, we'd also check the client cert from the request context
) -> bool:
    """
    Verify admin authentication with enhanced security.
    
    In production, this would also verify the mTLS client certificate
    to ensure the request comes from an authorized service.
    """
    from ..internal_auth import admin_key_ok  # §MONEY-M3a R26

    token = credentials.credentials

    if not admin_key_ok(token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # TODO: Also verify mTLS client certificate is from registry-backend
    # This would check the SPIFFE ID from the client cert
    
    return True
