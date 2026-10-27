"""
SPIRE mTLS Client for secure service-to-service communication.

OWL17 FIX-005: Replaced stub with real implementation.
Uses the global svid_client instance to build mTLS-enabled HTTP clients
for Registry → TEG and Registry → Registry communication.
"""
import logging
import httpx
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class SPIREMTLSClient:
    """SPIRE mTLS client for secure service-to-service communication.
    
    Uses the SVIDClient's certificate configuration to create HTTPX
    clients with mutual TLS authentication. Falls back to unverified
    HTTPS when SPIRE SVIDs are not available.
    """
    
    def __init__(self):
        self._cert_config: Optional[Dict[str, Any]] = None
        self._initialized = False
        self._mtls_available = False
        self._initialize()
    
    def _initialize(self):
        """Load certificate configuration from the global SVID client."""
        try:
            from agentvault_registry.identity.svid_client import svid_client
            
            if svid_client.is_initialized():
                cert_config = svid_client.get_client_cert_config()
                if cert_config:
                    self._cert_config = cert_config
                    self._mtls_available = True
                    spiffe_id = svid_client.get_spiffe_id() or "unknown"
                    is_mock = svid_client.is_using_mock()
                    mode = "mock" if is_mock else "real"
                    logger.info(
                        f"SPIRE mTLS client initialized ({mode} SVIDs): "
                        f"SPIFFE ID={spiffe_id}"
                    )
                else:
                    logger.warning("SVID client initialized but no cert config available")
            else:
                logger.warning("SVID client not initialized — mTLS not available")
                
        except ImportError:
            logger.warning("svid_client module not available — mTLS disabled")
        except Exception as e:
            logger.error(f"Failed to initialize SPIRE mTLS client: {e}")
        
        self._initialized = True
    
    async def get_async_client(self, timeout: float = 10.0) -> httpx.AsyncClient:
        """Get an async HTTP client with mTLS configuration.
        
        If SPIRE SVIDs are available, the client will use:
        - Client certificate + key for mutual authentication
        - Trust bundle for server verification
        
        If unavailable, returns a client with SSL verification disabled
        (development mode only).
        
        Args:
            timeout: Request timeout in seconds
            
        Returns:
            httpx.AsyncClient configured for mTLS or basic HTTPS
        """
        if self._mtls_available and self._cert_config:
            # Refresh cert config in case SVIDs have rotated
            try:
                from agentvault_registry.identity.svid_client import svid_client
                fresh_config = svid_client.get_client_cert_config()
                if fresh_config:
                    self._cert_config = fresh_config
            except Exception as e:
                logger.debug(f"Could not refresh cert config: {e}")
            
            logger.debug("Creating mTLS-enabled HTTPX client")
            return httpx.AsyncClient(
                cert=self._cert_config.get('cert'),     # (cert_path, key_path) tuple
                verify=self._cert_config.get('verify'),  # CA bundle path
                timeout=timeout
            )
        else:
            logger.debug("Creating standard HTTPX client (no mTLS)")
            return httpx.AsyncClient(
                verify=False,  # Development fallback — no SSL verification
                timeout=timeout
            )
    
    def get_client_config(self) -> Optional[Dict[str, Any]]:
        """Get raw client certificate configuration.
        
        Returns:
            Dict with 'cert' and 'verify' keys for HTTPX, or None
        """
        if self._mtls_available and self._cert_config:
            # Refresh
            try:
                from agentvault_registry.identity.svid_client import svid_client
                fresh_config = svid_client.get_client_cert_config()
                if fresh_config:
                    self._cert_config = fresh_config
            except Exception:
                pass
            return self._cert_config
        return None
    
    def is_available(self) -> bool:
        """Check if mTLS is available."""
        return self._mtls_available
