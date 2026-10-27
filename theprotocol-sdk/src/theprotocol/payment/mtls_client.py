"""
f052: MtlsAgentClient — SPIRE SVID-based mTLS Client for Agent-to-Agent Calls (IRONHAND)

Wraps httpx.AsyncClient with the agent's SVID certificate for outbound mTLS calls.
The agent fetches its SVID from SPIRE via the workload API and stores the cert/key/bundle
to disk. This client reads those files for TLS configuration.

Usage:
    client = MtlsAgentClient(cert_dir="/tmp/svid")
    result = await client.call_agent(
        "https://bravo:8152/a2a",
        method="tasks/send",
        params={"message": {"role": "user", "parts": [{"text": "Hello"}]}},
    )
"""
import json
import logging
from typing import Any, Dict, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

try:
    import httpx

    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


def _extract_spiffe_id_from_cert(cert_path: str) -> Optional[str]:
    """Read a PEM certificate file and extract the SPIFFE ID from the URI SAN."""
    try:
        from cryptography import x509
        from cryptography.x509.oid import ExtensionOID

        with open(cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        san_ext = cert.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        )
        for name in san_ext.value.get_values_for_type(
            x509.UniformResourceIdentifier
        ):
            if name.startswith("spiffe://"):
                return name
    except Exception as e:
        logger.debug(f"[MtlsAgentClient] Failed to read SPIFFE ID from {cert_path}: {e}")
    return None


class MtlsAgentClient:
    """httpx client with SPIRE SVID for outbound mTLS agent-to-agent calls.

    Reads certificate, key, and CA bundle from a directory populated by the
    SVID fetcher (svid_fetcher.py) or cert-writer sidecar.

    Args:
        cert_dir: Directory containing svid.pem, key.pem, bundle.pem.
        timeout: Request timeout in seconds.
    """

    def __init__(self, cert_dir: str = "/tmp/svid", timeout: float = 30.0):
        if not _HTTPX_AVAILABLE:
            raise ImportError("httpx is required for MtlsAgentClient")

        self.cert_path = f"{cert_dir}/svid.pem"
        self.key_path = f"{cert_dir}/key.pem"
        self.bundle_path = f"{cert_dir}/bundle.pem"
        self.timeout = timeout
        self._own_spiffe_id: Optional[str] = None

    @property
    def cert(self) -> tuple:
        """Certificate + key tuple for httpx."""
        return (self.cert_path, self.key_path)

    def get_own_spiffe_id(self) -> Optional[str]:
        """Read own SPIFFE ID from the SVID certificate SAN."""
        if self._own_spiffe_id is None:
            self._own_spiffe_id = _extract_spiffe_id_from_cert(self.cert_path)
        return self._own_spiffe_id

    async def call_agent(
        self,
        url: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        payment_token: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a JSON-RPC 2.0 request to another agent over mTLS.

        Args:
            url: Target agent's mTLS endpoint (https://...)
            method: JSON-RPC method (e.g., "tasks/send")
            params: Method parameters
            payment_token: Optional payment token (belt-and-suspenders)
            request_id: Optional JSON-RPC request ID

        Returns:
            Parsed JSON response from the target agent.
        """
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if payment_token:
            headers["X-Payment-Token"] = payment_token

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": request_id or str(uuid4()),
        }

        logger.debug(
            f"[MtlsAgentClient] mTLS call → {url} method={method} "
            f"spiffe_id={self.get_own_spiffe_id()}"
        )

        async with httpx.AsyncClient(
            cert=self.cert,
            verify=self._verify(),
            timeout=self.timeout,
        ) as client:
            response = await client.post(
                url, content=json.dumps(payload), headers=headers
            )
            response.raise_for_status()
            return response.json()

    def _verify(self) -> Any:
        """What httpx gets as `verify=`: the bundle and the SVID in ONE SSLContext.

        httpx >= 0.28 drops `cert=` when `verify=` is a CA file path (it returns the context built from the path before
        it reaches the client-certificate step), so with a current httpx this client presented NO certificate. A
        context holding the chain is honoured by every httpx version and is the only form httpx 1.0 accepts.
        """
        import ssl
        ctx = ssl.create_default_context(cafile=self.bundle_path)
        ctx.load_cert_chain(*self.cert)
        return ctx

    async def health_check(self, url: str) -> Dict[str, Any]:
        """Check an agent's health endpoint over mTLS."""
        async with httpx.AsyncClient(
            cert=self.cert,
            verify=self._verify(),
            timeout=10.0,
        ) as client:
            response = await client.get(url)
            return response.json()
