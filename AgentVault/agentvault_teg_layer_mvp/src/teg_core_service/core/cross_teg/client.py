"""
Cross-TEG Client for inter-TEG communication.

Handles HTTP communication between separated TEG layers.
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import httpx
import asyncio

from ..config import get_settings

# Get settings instance
settings = get_settings()
from ..oauth.multi_issuer_jwt import MultiIssuerJWTService
from .messages import (
    CrossTEGTransferRequest,
    CrossTEGTransferResponse,
    TransferAcceptRequest,
    TransferAcceptResponse,
    TransferStatus
)

logger = logging.getLogger(__name__)


class CrossTEGClient:
    """
    Client for communicating with other TEG layers.
    
    Handles:
    - HTTP communication with retries
    - Authentication using cross-registry OAuth tokens
    - Message serialization/deserialization
    - Circuit breaking for failed TEGs
    """
    
    def __init__(
        self,
        teg_id: str,
        teg_url: str,
        timeout: int = 20,
        max_retries: int = 2
    ):
        self.teg_id = teg_id
        self.teg_url = teg_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        
        # Circuit breaker state
        self.failure_count = 0
        self.circuit_open = False
        self.circuit_opened_at: Optional[datetime] = None
        self.circuit_breaker_threshold = 15
        self.circuit_breaker_timeout = 15  # seconds

        # SPIRE cert tracking for auto-refresh
        import os
        self._cert_dir = os.getenv("SVID_CERT_DIR", "/certs")
        self._bundle_mtime = 0

        # Create initial HTTP client
        self.client = self._build_http_client()

    def _build_http_client(self) -> httpx.AsyncClient:
        """Build httpx client with current SPIRE certs. Called on init and cert rotation."""
        import os, glob
        client_kwargs = {
            "base_url": self.teg_url,
            "timeout": httpx.Timeout(self.timeout),
            "limits": httpx.Limits(max_keepalive_connections=5, max_connections=10),
        }
        if self.teg_url.startswith("https://"):
            from urllib.parse import urlparse
            parsed = urlparse(self.teg_url)
            bundle_path = os.path.join(self._cert_dir, "bundle.0.pem")
            cert_path = os.path.join(self._cert_dir, "svid.0.pem")
            key_path = os.path.join(self._cert_dir, "svid.0.key")
            if parsed.port and parsed.port != 443 and os.path.exists(bundle_path):
                # Non-standard port = SPIRE mTLS endpoint
                # Combine local + federated trust bundles for cross-frame mTLS
                fed_bundles = glob.glob(os.path.join(self._cert_dir, "federated_bundle.*.pem"))
                if fed_bundles:
                    combined = open(bundle_path).read()
                    for fb in fed_bundles:
                        combined += "\n" + open(fb).read()
                    combined_path = os.path.join("/tmp", f".combined_bundle_{id(self)}.pem")
                    with open(combined_path, "w") as f:
                        f.write(combined)
                    client_kwargs["verify"] = combined_path
                else:
                    client_kwargs["verify"] = bundle_path
                if os.path.exists(cert_path) and os.path.exists(key_path):
                    client_kwargs["cert"] = (cert_path, key_path)
                    # §DEPS: httpx 0.28 drops `cert` beside a bundle PATH; the chain rides inside the context instead
                    from ...ssl_helper import client_cert_verify
                    client_kwargs["verify"] = client_cert_verify(client_kwargs["verify"], client_kwargs["cert"])
                # Track bundle mtime for rotation detection
                try:
                    self._bundle_mtime = os.path.getmtime(bundle_path)
                except: pass
            elif os.path.exists(cert_path) and os.path.exists(key_path):
                # Standard HTTPS (Let's Encrypt) — present SPIRE client cert only
                client_kwargs["cert"] = (cert_path, key_path)
        return httpx.AsyncClient(**client_kwargs)

    def _refresh_ssl_if_needed(self):
        """Rebuild combined trust bundle and recreate httpx client if SPIRE certs rotated."""
        import os
        if not self.teg_url.startswith("https://"):
            return
        try:
            current_mtime = os.path.getmtime(os.path.join(self._cert_dir, "bundle.0.pem"))
            if current_mtime <= self._bundle_mtime:
                return  # No change
        except:
            return
        # Bundle changed — rebuild and recreate client
        logger.info(f"SPIRE bundle rotated for TEG {self.teg_id}, recreating mTLS client")
        self.client = self._build_http_client()
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
    
    async def initiate_transfer(
        self,
        request: CrossTEGTransferRequest
    ) -> CrossTEGTransferResponse:
        """Initiate a transfer to this TEG."""
        return await self._make_request(
            method="POST",
            endpoint="/api/v1/cross-teg/transfer",
            data=request.dict(),
            response_model=CrossTEGTransferResponse,
            auth_token=request.authorization_token
        )
    
    async def accept_transfer(
        self,
        request: TransferAcceptRequest
    ) -> TransferAcceptResponse:
        """Request this TEG to accept an incoming transfer."""
        return await self._make_request(
            method="POST",
            endpoint="/api/v1/cross-teg/accept",
            data=request.dict(),
            response_model=TransferAcceptResponse,
            auth_token=request.authorization_token
        )
    
    async def prepare_transfer(
        self,
        transfer_id: str,
        request_data: Dict[str, Any],
        auth_token: str
    ) -> Dict[str, Any]:
        """Send prepare request for two-phase commit."""
        return await self._make_request(
            method="POST",
            endpoint=f"/api/v1/cross-teg/prepare/{transfer_id}",
            data=request_data,
            auth_token=auth_token
        )
    
    async def commit_transfer(
        self,
        transfer_id: str,
        auth_token: str
    ) -> Dict[str, Any]:
        """Send commit request for two-phase commit."""
        return await self._make_request(
            method="POST",
            endpoint=f"/api/v1/cross-teg/commit/{transfer_id}",
            auth_token=auth_token
        )
    
    async def abort_transfer(
        self,
        transfer_id: str,
        reason: str,
        auth_token: str
    ) -> Dict[str, Any]:
        """Send abort request for two-phase commit."""
        return await self._make_request(
            method="POST",
            endpoint=f"/api/v1/cross-teg/abort/{transfer_id}",
            data={"reason": reason},
            auth_token=auth_token
        )
    
    async def get_transfer_status(
        self,
        transfer_id: str,
        auth_token: str
    ) -> Dict[str, Any]:
        """Query transfer status from this TEG."""
        return await self._make_request(
            method="GET",
            endpoint=f"/api/v1/cross-teg/transfer/{transfer_id}",
            auth_token=auth_token
        )
    
    async def treasury_fund(
        self,
        amount: str,
        source_teg_id: str,
        correlation_id: str,
        reason: str = "cross_teg_fund",
        auth_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """PB-2 (2026-05-10): Send treasury-to-treasury fund to peer TEG via mTLS.

        Calls peer's POST /api/v1/cross-teg/treasury-fund. Architecturally
        fee-exempt — treasury-to-treasury moves are protocol primitives, not
        market transactions. Idempotent on correlation_id.

        auth_token is optional; mTLS SPIFFE is the primary auth, API key
        fallback is only needed when nginx-federation isn't in path
        (e.g., direct internal Docker network calls without sidecar).
        """
        return await self._make_request(
            method="POST",
            endpoint="/api/v1/cross-teg/treasury-fund",
            data={
                "amount": str(amount),
                "source_teg_id": source_teg_id,
                "correlation_id": correlation_id,
                "reason": reason,
            },
            auth_token=auth_token,
        )

    async def health_check(self) -> bool:
        """Check if the TEG is healthy."""
        try:
            response = await self._make_request(
                method="GET",
                endpoint="/health",
                skip_circuit_breaker=True  # Always try health checks
            )
            return response.get("status") == "healthy"
        except Exception:
            return False
    
    def _check_circuit_breaker(self):
        """Check if circuit breaker is open."""
        if not self.circuit_open:
            return
        
        # Check if enough time has passed to retry
        if self.circuit_opened_at:
            elapsed = (datetime.now(timezone.utc) - self.circuit_opened_at).total_seconds()
            if elapsed > self.circuit_breaker_timeout:
                logger.info(f"Circuit breaker for TEG {self.teg_id} half-open, allowing retry")
                self.circuit_open = False
                self.failure_count = 0
            else:
                raise Exception(
                    f"Circuit breaker open for TEG {self.teg_id}. "
                    f"Retry in {self.circuit_breaker_timeout - elapsed:.0f} seconds"
                )
    
    def _record_success(self):
        """Record successful request."""
        self.failure_count = 0
        self.circuit_open = False
        self.circuit_opened_at = None
    
    def _record_failure(self):
        """Record failed request and potentially open circuit."""
        self.failure_count += 1
        
        if self.failure_count >= self.circuit_breaker_threshold:
            self.circuit_open = True
            self.circuit_opened_at = datetime.now(timezone.utc)
            logger.error(
                f"Circuit breaker opened for TEG {self.teg_id} "
                f"after {self.failure_count} failures"
            )
    
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        auth_token: Optional[str] = None,
        response_model: Optional[type] = None,
        skip_circuit_breaker: bool = False
    ) -> Dict[str, Any]:
        """Make HTTP request with retries and circuit breaking."""

        # Auto-refresh SSL if SPIRE certs rotated (cheap stat() check)
        self._refresh_ssl_if_needed()

        # Check circuit breaker unless skipped
        if not skip_circuit_breaker:
            self._check_circuit_breaker()
        
        headers = {}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        
        last_error = None
        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    # Exponential backoff
                    await asyncio.sleep(0.3 * attempt)
                
                logger.debug(
                    f"Making {method} request to TEG {self.teg_id} "
                    f"endpoint {endpoint} (attempt {attempt + 1})"
                )
                
                response = await self.client.request(
                    method=method,
                    url=endpoint,
                    json=data,
                    headers=headers
                )
                
                response.raise_for_status()
                
                # Record success
                self._record_success()
                
                result = response.json()
                
                # Convert to response model if provided
                if response_model:
                    return response_model(**result)
                
                return result
                
            except httpx.HTTPStatusError as e:
                last_error = e
                logger.error(
                    f"HTTP error from TEG {self.teg_id}: "
                    f"{e.response.status_code} - {e.response.text}"
                )
                
                # Don't retry client errors (4xx)
                if 400 <= e.response.status_code < 500:
                    self._record_failure()
                    raise
                    
            except Exception as e:
                last_error = e
                logger.error(
                    f"Error communicating with TEG {self.teg_id}: {str(e)}"
                )
        
        # All retries failed
        self._record_failure()
        raise Exception(
            f"Failed to communicate with TEG {self.teg_id} "
            f"after {self.max_retries} attempts: {last_error}"
        )


class CrossTEGClientFactory:
    """Factory for creating Cross-TEG clients."""
    
    def __init__(self):
        self.clients: Dict[str, CrossTEGClient] = {}
    
    def get_client(self, teg_id: str, teg_url: str) -> CrossTEGClient:
        """Get or create a client for a TEG. Recreates if URL changed (self-healing)."""
        existing = self.clients.get(teg_id)
        if existing and existing.teg_url == teg_url:
            return existing
        self.clients[teg_id] = CrossTEGClient(teg_id, teg_url)
        return self.clients[teg_id]

    async def remove_client(self, teg_id: str) -> bool:
        """Drop a cached client (used by /config/remove-partner). Returns True if a client existed."""
        existing = self.clients.pop(teg_id, None)
        if existing is None:
            return False
        try:
            await existing.close()
        except Exception:
            pass
        return True

    async def close_all(self):
        """Close all clients."""
        for client in self.clients.values():
            await client.close()
        self.clients.clear()
