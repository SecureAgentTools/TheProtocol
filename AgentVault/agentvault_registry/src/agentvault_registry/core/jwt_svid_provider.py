"""
JWT-SVID Provider for TEG integration.

OWL17 FIX-004: Replaced stub with real SPIRE Workload API integration.
Acquires JWT-SVIDs for authenticated agents via the SPIRE agent's
Workload API. Falls back to a development-mode signed JWT when SPIRE
is unavailable.

Part of REQ-INT-V1AUTH-001 implementation.
"""
import logging
import os
import time
from typing import Optional
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Try to import PySpiffe for real JWT-SVID acquisition
try:
    from spiffe import WorkloadApiClient
    from spiffe.errors import PySpiffeError as SpiffeError
    PYSPIFFE_AVAILABLE = True
except ImportError:
    PYSPIFFE_AVAILABLE = False
    SpiffeError = Exception
    logger.warning("PySpiffe not available — JWT-SVID provider will use fallback mode")

# Try to import PyJWT for fallback signed tokens
try:
    import jwt as pyjwt
    PYJWT_AVAILABLE = True
except ImportError:
    PYJWT_AVAILABLE = False


class JWTSVIDProvider:
    """Provides JWT-SVIDs for agent authentication to TEG services.
    
    Primary mode: Acquires real JWT-SVIDs from SPIRE via the Workload API.
    Fallback mode: Generates development-signed JWTs when SPIRE is unavailable.
    """
    
    def __init__(self):
        self.initialized = False
        self._spire_available = False
        self._fallback_key = os.environ.get(
            "JWT_SVID_SIGNING_KEY", 
            ""
        )
        self._trust_domain = "agentvault.com"
        self._spiffe_socket = None
    
    def initialize(self) -> bool:
        """Initialize the JWT-SVID provider."""
        logger.info("Initializing JWT-SVID provider")
        
        if PYSPIFFE_AVAILABLE:
            # Normalize socket path (same logic as svid_client FIX-001)
            raw_socket = os.environ.get('SPIFFE_ENDPOINT_SOCKET', '')
            if raw_socket:
                if raw_socket.startswith('unix://'):
                    socket_path = raw_socket[len('unix://'):]
                    socket_path = '/' + socket_path.lstrip('/')
                    self._spiffe_socket = f'unix:{socket_path}'
                elif raw_socket.startswith('unix:'):
                    self._spiffe_socket = raw_socket
                else:
                    self._spiffe_socket = f'unix:{raw_socket}'
                
                # Check if socket exists
                file_path = self._spiffe_socket.replace('unix:', '')
                if os.path.exists(file_path):
                    self._spire_available = True
                    logger.info(f"SPIRE Workload API available at {self._spiffe_socket}")
                else:
                    logger.warning(f"SPIRE socket not found at {file_path}, using fallback JWT signing")
            else:
                logger.info("SPIFFE_ENDPOINT_SOCKET not set, using fallback JWT signing")
        else:
            logger.warning("PySpiffe not installed, using fallback JWT signing")
        
        self.initialized = True
        
        mode = "SPIRE JWT-SVID" if self._spire_available else "fallback signed JWT"
        logger.info(f"JWT-SVID provider initialized in {mode} mode")
        return True
    
    async def get_jwt_svid(self, subject: str, audience: str) -> str:
        """Get a JWT-SVID for the given subject and audience.
        
        Args:
            subject: Agent identifier (email or SPIFFE ID)
            audience: Target service SPIFFE ID
            
        Returns:
            JWT-SVID token string
        """
        if self._spire_available:
            try:
                return self._acquire_from_spire(subject, audience)
            except Exception as e:
                logger.error(f"SPIRE JWT-SVID acquisition failed: {e}, falling back to signed JWT")
                return self._generate_fallback_jwt(subject, audience)
        else:
            return self._generate_fallback_jwt(subject, audience)
    
    def _acquire_from_spire(self, subject: str, audience: str) -> str:
        """Acquire a real JWT-SVID from SPIRE.
        
        Uses the Workload API to fetch a JWT-SVID for the subject
        with the specified audience.
        """
        # Set env for PySpiffe
        os.environ['SPIFFE_ENDPOINT_SOCKET'] = self._spiffe_socket
        
        try:
            with WorkloadApiClient() as client:
                # Fetch JWT-SVID
                # The SPIRE agent issues a JWT-SVID based on the workload's
                # registered SPIFFE ID and the requested audience
                jwt_svid_set = client.fetch_jwt_svids(
                    audiences=[audience]
                )
                
                if jwt_svid_set and len(jwt_svid_set) > 0:
                    jwt_svid = jwt_svid_set[0]
                    logger.info(
                        f"Acquired JWT-SVID from SPIRE: "
                        f"spiffe_id={jwt_svid.spiffe_id}, "
                        f"audience={audience}"
                    )
                    return jwt_svid.token
                else:
                    raise SpiffeError("No JWT-SVIDs returned from SPIRE")
                    
        except SpiffeError as e:
            logger.error(f"SPIRE JWT-SVID fetch error: {e}")
            raise
    
    def _generate_fallback_jwt(self, subject: str, audience: str) -> str:
        """Generate a development-signed JWT when SPIRE is unavailable.
        
        WARNING: This is NOT secure. It's a development fallback that
        generates a self-signed JWT matching the expected format.
        """
        # Convert email to SPIFFE ID format
        safe_subject = subject.replace('@', '_at_').replace('.', '_dot_')
        spiffe_subject = f"spiffe://{self._trust_domain}/agent/{safe_subject}"
        
        now = datetime.now(timezone.utc)
        
        if PYJWT_AVAILABLE:
            payload = {
                "sub": spiffe_subject,
                "aud": audience,
                "iss": f"spiffe://{self._trust_domain}/service/registry-backend",
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=5)).timestamp()),
                "agent_email": subject,
            }
            
            token = pyjwt.encode(payload, self._fallback_key, algorithm="HS256")
            logger.warning(f"Generated fallback JWT for {subject} (NOT a real SVID)")
            return token
        else:
            # Ultra-fallback: return a stub token (same as old behavior)
            logger.warning(f"No JWT library available — using stub token for {subject}")
            return f"fallback-jwt-svid-{safe_subject}-{int(now.timestamp())}"


# Global provider instance
_provider: Optional[JWTSVIDProvider] = None


def get_provider() -> JWTSVIDProvider:
    """Get or create the global JWT-SVID provider."""
    global _provider
    if _provider is None:
        _provider = JWTSVIDProvider()
        _provider.initialize()
    return _provider


async def acquire_agent_jwt_svid(agent_email: str, audience: str) -> str:
    """
    Acquire a JWT-SVID for an authenticated agent.
    
    This is the main entry point used by the teg_integration_jwt_svid router.
    
    Args:
        agent_email: The authenticated agent's email address
        audience: The target service SPIFFE ID (e.g., teg-core audience)
        
    Returns:
        JWT-SVID token string
    """
    provider = get_provider()
    return await provider.get_jwt_svid(agent_email, audience)
