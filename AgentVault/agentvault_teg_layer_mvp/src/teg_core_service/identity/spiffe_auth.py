"""mTLS Middleware for extracting client SPIFFE IDs

This middleware extracts and validates client SPIFFE IDs from mTLS connections,
making them available to request handlers for authorization decisions.
"""

import logging
import ssl
from typing import Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from fastapi import HTTPException
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtensionOID

logger = logging.getLogger(__name__)


class SPIFFEAuthMiddleware(BaseHTTPMiddleware):
    """Middleware to extract and validate SPIFFE IDs from client certificates"""
    
    async def dispatch(self, request: Request, call_next):
        """Process request and extract client SPIFFE ID"""
        try:
            # Extract client SPIFFE ID from TLS connection
            client_spiffe_id = self._extract_client_spiffe_id(request)
            
            if client_spiffe_id:
                # Store SPIFFE ID in request state for use by handlers
                request.state.client_spiffe_id = client_spiffe_id
                logger.debug(f"Request from client SPIFFE ID: {client_spiffe_id}")
            else:
                # No client certificate or SPIFFE ID found
                request.state.client_spiffe_id = None
                logger.debug("Request without client SPIFFE ID")
            
            # Process request
            response = await call_next(request)
            return response
            
        except Exception as e:
            logger.error(f"Error in SPIFFE auth middleware: {e}")
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal authentication error"}
            )
    
    def _extract_client_spiffe_id(self, request: Request) -> Optional[str]:
        """Extract SPIFFE ID from client certificate"""
        try:
            # Get client certificate from request
            # Note: This requires Uvicorn to be configured with client cert info
            # The exact method depends on ASGI server implementation
            
            # For Uvicorn with --client-ca, certificates are available via transport
            transport = request.scope.get("transport")
            if not transport:
                return None
            
            # Get SSL object from transport
            ssl_object = transport.get_extra_info("ssl_object")
            if not ssl_object:
                return None
            
            # Get peer certificate
            peer_cert_der = ssl_object.getpeercert(binary_form=True)
            if not peer_cert_der:
                return None
            
            # Parse certificate
            cert = x509.load_der_x509_certificate(peer_cert_der)
            
            # Extract SPIFFE ID from SAN extension
            try:
                san_ext = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
                for san in san_ext.value:
                    if isinstance(san, x509.UniformResourceIdentifier):
                        uri = san.value
                        if uri.startswith("spiffe://"):
                            logger.info(f"Extracted SPIFFE ID from certificate: {uri}")
                            return uri
            except x509.ExtensionNotFound:
                logger.debug("No SAN extension found in client certificate")
            
            # Fallback: Try to construct SPIFFE ID from CN
            subject = cert.subject
            cn = None
            for attribute in subject:
                if attribute.oid == NameOID.COMMON_NAME:
                    cn = attribute.value
                    break
            
            if cn and cn.startswith("spiffe://"):
                logger.info(f"Extracted SPIFFE ID from CN: {cn}")
                return cn
            
            logger.warning("Client certificate does not contain valid SPIFFE ID")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting client SPIFFE ID: {e}")
            return None


def get_client_spiffe_id(request: Request) -> Optional[str]:
    """Helper function to get client SPIFFE ID from request state"""
    return getattr(request.state, "client_spiffe_id", None)


def require_spiffe_id(allowed_ids: Optional[list[str]] = None):
    """Dependency to require client SPIFFE ID
    
    Args:
        allowed_ids: Optional list of allowed SPIFFE IDs. If None, any valid SPIFFE ID is accepted.
    """
    def _require_spiffe_id(request: Request) -> str:
        client_id = get_client_spiffe_id(request)
        
        if not client_id:
            raise HTTPException(
                status_code=401,
                detail="Client certificate required"
            )
        
        if allowed_ids and client_id not in allowed_ids:
            logger.warning(f"Unauthorized SPIFFE ID: {client_id}")
            raise HTTPException(
                status_code=403,
                detail="Unauthorized client identity"
            )
        
        return client_id
    
    return _require_spiffe_id
