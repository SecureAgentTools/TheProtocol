"""SVID Server Configuration for mTLS Server Endpoints

This module provides server-side mTLS configuration using SPIFFE SVIDs,
enabling services to act as mTLS servers that require and validate client certificates.
"""

import logging
import os
import ssl
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import threading
import time

from pyspiffe.workloadapi import default_workload_api_client
from pyspiffe.exceptions import PySpiffeError
from pyspiffe.bundle.x509_bundle.x509_bundle_set import X509BundleSet
from pyspiffe.svid.x509_svid import X509Svid

logger = logging.getLogger(__name__)


class SVIDServer:
    """Manages SPIFFE SVIDs for server-side mTLS configuration"""
    
    def __init__(self):
        self.spiffe_id: Optional[str] = None
        self.cert_path: Optional[Path] = None
        self.key_path: Optional[Path] = None
        self.bundle_path: Optional[Path] = None
        self.ssl_context: Optional[ssl.SSLContext] = None
        self._lock = threading.Lock()
        self._update_thread: Optional[threading.Thread] = None
        self._running = False
        self._initialized = False
        
    def initialize(self) -> bool:
        """Initialize SVID server and fetch initial certificates"""
        try:
            logger.info("Initializing SVID Server for mTLS server endpoints")
            
            # Check if SPIFFE endpoint socket is configured
            spiffe_socket = os.environ.get('SPIFFE_ENDPOINT_SOCKET')
            if not spiffe_socket:
                logger.info("SPIFFE_ENDPOINT_SOCKET not set, mTLS server functionality disabled")
                return False
                
            logger.info(f"Using SPIFFE endpoint: {spiffe_socket}")
            
            # Fetch initial SVID and create SSL context
            if not self._fetch_and_configure_server():
                logger.error("Failed to fetch initial SVID for server")
                return False
                
            # Start SVID watcher thread
            self._start_svid_watcher()
            
            self._initialized = True
            logger.info("SVID Server initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize SVID Server: {e}")
            return False
    
    def _fetch_and_configure_server(self) -> bool:
        """Fetch X.509 SVID and configure SSL context for server"""
        try:
            with default_workload_api_client() as client:
                # Fetch X.509 context
                x509_context = client.fetch_x509_context()
                
                # Get default SVID
                svid = x509_context.default_svid()
                self.spiffe_id = str(svid.spiffe_id)
                
                # Get trust bundle
                bundle = x509_context.x509_bundle_set
                
                logger.info(f"Fetched server SVID with SPIFFE ID: {self.spiffe_id}")
                logger.info(f"Server certificate expires: {svid.leaf.not_valid_after}")
                
                # Write certificate chain to file
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.crt') as cert_file:
                    # Write leaf certificate
                    cert_file.write(svid.leaf.public_bytes(ssl.PEM).decode())
                    # Write intermediate certificates if any
                    for intermediate in svid.intermediates:
                        cert_file.write(intermediate.public_bytes(ssl.PEM).decode())
                    self.cert_path = Path(cert_file.name)
                
                # Write private key to file
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.key') as key_file:
                    key_file.write(svid.private_key.private_bytes(
                        encoding=ssl.PEM,
                        format=ssl.PrivateFormat.PKCS8,
                        encryption_algorithm=ssl.NoEncryption()
                    ).decode())
                    self.key_path = Path(key_file.name)
                
                # Write trust bundle to file (for client verification)
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.bundle') as bundle_file:
                    # Write all CA certificates from the trust domain
                    for trust_domain, x509_bundle in bundle.bundles.items():
                        logger.info(f"Adding trust bundle for domain: {trust_domain}")
                        for ca_cert in x509_bundle.x509_authorities:
                            bundle_file.write(ca_cert.public_bytes(ssl.PEM).decode())
                    self.bundle_path = Path(bundle_file.name)
                
                # Set restrictive permissions
                os.chmod(self.cert_path, 0o600)
                os.chmod(self.key_path, 0o600)
                os.chmod(self.bundle_path, 0o600)
                
                # Create SSL context for server
                self._create_ssl_context()
                
                return True
                
        except PySpiffeError as e:
            logger.error(f"SPIFFE error while fetching server SVID: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error fetching server SVID: {e}")
            return False
    
    def _create_ssl_context(self):
        """Create SSL context for mTLS server"""
        try:
            # Create SSL context
            context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            
            # Load server certificate and key
            context.load_cert_chain(
                certfile=str(self.cert_path),
                keyfile=str(self.key_path)
            )
            
            # Load CA bundle for client certificate verification
            context.load_verify_locations(cafile=str(self.bundle_path))
            
            # Require client certificates
            context.verify_mode = ssl.CERT_REQUIRED
            
            # Set minimum TLS version
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            
            # Store the context
            self.ssl_context = context
            
            logger.info("Created SSL context for mTLS server")
            
        except Exception as e:
            logger.error(f"Failed to create SSL context: {e}")
            raise
    
    def _start_svid_watcher(self):
        """Start background thread to watch for SVID updates"""
        self._running = True
        self._update_thread = threading.Thread(
            target=self._watch_svid_updates,
            name="registry-server-svid-watcher",
            daemon=True
        )
        self._update_thread.start()
        logger.info("Started server SVID watcher thread")
    
    def _watch_svid_updates(self):
        """Watch for SVID updates and refresh certificates"""
        logger.info("Server SVID watcher thread started")
        
        while self._running:
            try:
                with default_workload_api_client() as client:
                    for x509_context in client.watch_x509_context():
                        if not self._running:
                            break
                            
                        with self._lock:
                            old_cert_path = self.cert_path
                            old_key_path = self.key_path
                            old_bundle_path = self.bundle_path
                            
                            logger.info("Server SVID update detected, refreshing certificates")
                            
                            if self._fetch_and_configure_server():
                                logger.info("Successfully updated server SVID certificates")
                                
                                # Clean up old files
                                if old_cert_path and old_cert_path.exists():
                                    old_cert_path.unlink()
                                if old_key_path and old_key_path.exists():
                                    old_key_path.unlink()
                                if old_bundle_path and old_bundle_path.exists():
                                    old_bundle_path.unlink()
                            else:
                                logger.error("Failed to update server SVID certificates")
                                
            except Exception as e:
                logger.error(f"Error in server SVID watcher: {e}")
                if self._running:
                    time.sleep(30)  # Wait before retrying
    
    def get_server_cert_paths(self) -> Optional[Tuple[str, str]]:
        """Get server certificate and key file paths
        
        Returns:
            Tuple of (cert_path, key_path) or None if not available
        """
        with self._lock:
            if not all([self.cert_path, self.key_path]):
                return None
            return (str(self.cert_path), str(self.key_path))
    
    def get_ca_bundle_path(self) -> Optional[str]:
        """Get CA bundle path for client certificate verification
        
        Returns:
            Path to CA bundle file or None if not available
        """
        with self._lock:
            if not self.bundle_path:
                return None
            return str(self.bundle_path)
    
    def get_ssl_context(self) -> Optional[ssl.SSLContext]:
        """Get configured SSL context for server
        
        Returns:
            Configured SSLContext or None if not available
        """
        with self._lock:
            return self.ssl_context
    
    def get_spiffe_id(self) -> Optional[str]:
        """Get current SPIFFE ID"""
        return self.spiffe_id
    
    def is_initialized(self) -> bool:
        """Check if SVID server is initialized and ready"""
        return self._initialized and self.get_ssl_context() is not None
    
    def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up SVID Server")
        self._running = False
        
        if self._update_thread and self._update_thread.is_alive():
            self._update_thread.join(timeout=5)
        
        # Remove temporary files
        with self._lock:
            if self.cert_path and self.cert_path.exists():
                self.cert_path.unlink()
            if self.key_path and self.key_path.exists():
                self.key_path.unlink()
            if self.bundle_path and self.bundle_path.exists():
                self.bundle_path.unlink()


# Global SVID server instance
svid_server = SVIDServer()
