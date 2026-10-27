"""SVID Manager for TEG Core Service

This module handles SPIFFE SVID acquisition and management for the TEG Core Service.
It provides functionality to fetch X.509 SVIDs from the SPIRE Agent and manage
certificate rotation for mTLS server configuration.
"""

import logging
import os
import ssl
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple
import threading
import time

from pyspiffe.workloadapi import default_workload_api_client
from pyspiffe.exceptions import PySpiffeError

logger = logging.getLogger(__name__)


class SVIDManager:
    """Manages SPIFFE SVIDs for the TEG Core Service"""
    
    def __init__(self):
        self.spiffe_id: Optional[str] = None
        self.cert_path: Optional[Path] = None
        self.key_path: Optional[Path] = None
        self.bundle_path: Optional[Path] = None
        self._lock = threading.Lock()
        self._update_thread: Optional[threading.Thread] = None
        self._running = False
        
    def initialize(self) -> bool:
        """Initialize SVID manager and fetch initial certificates"""
        try:
            logger.info("Initializing SVID Manager for TEG Core Service")
            
            # Check if SPIFFE endpoint socket is configured
            spiffe_socket = os.environ.get('SPIFFE_ENDPOINT_SOCKET')
            if not spiffe_socket:
                logger.warning("SPIFFE_ENDPOINT_SOCKET not set, mTLS will not be available")
                return False
                
            logger.info(f"Using SPIFFE endpoint: {spiffe_socket}")
            
            # Fetch initial SVID
            if not self._fetch_and_store_svid():
                logger.error("Failed to fetch initial SVID")
                return False
                
            # Start SVID watcher thread
            self._start_svid_watcher()
            
            logger.info("SVID Manager initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize SVID Manager: {e}")
            return False
    
    def _fetch_and_store_svid(self) -> bool:
        """Fetch X.509 SVID and store to temporary files"""
        try:
            with default_workload_api_client() as client:
                # Fetch X.509 context
                x509_context = client.fetch_x509_context()
                
                # Get default SVID
                svid = x509_context.default_svid()
                self.spiffe_id = str(svid.spiffe_id)
                
                # Get trust bundle
                bundle = x509_context.x509_bundle_set
                
                logger.info(f"Fetched SVID with SPIFFE ID: {self.spiffe_id}")
                logger.info(f"Certificate expires: {svid.leaf.not_valid_after}")
                
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
                
                # Write trust bundle to file
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
                
                return True
                
        except PySpiffeError as e:
            logger.error(f"SPIFFE error while fetching SVID: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error fetching SVID: {e}")
            return False
    
    def _start_svid_watcher(self):
        """Start background thread to watch for SVID updates"""
        self._running = True
        self._update_thread = threading.Thread(
            target=self._watch_svid_updates,
            name="svid-watcher",
            daemon=True
        )
        self._update_thread.start()
        logger.info("Started SVID watcher thread")
    
    def _watch_svid_updates(self):
        """Watch for SVID updates and refresh certificates"""
        logger.info("SVID watcher thread started")
        
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
                            
                            logger.info("SVID update detected, refreshing certificates")
                            
                            if self._fetch_and_store_svid():
                                logger.info("Successfully updated SVID certificates")
                                
                                # Clean up old files
                                if old_cert_path and old_cert_path.exists():
                                    old_cert_path.unlink()
                                if old_key_path and old_key_path.exists():
                                    old_key_path.unlink()
                                if old_bundle_path and old_bundle_path.exists():
                                    old_bundle_path.unlink()
                            else:
                                logger.error("Failed to update SVID certificates")
                                
            except Exception as e:
                logger.error(f"Error in SVID watcher: {e}")
                if self._running:
                    time.sleep(30)  # Wait before retrying
    
    def get_tls_config(self) -> Optional[dict]:
        """Get TLS configuration for Uvicorn server"""
        with self._lock:
            if not all([self.cert_path, self.key_path, self.bundle_path]):
                return None
                
            return {
                'certfile': str(self.cert_path),
                'keyfile': str(self.key_path),
                'ca_certs': str(self.bundle_path),
                'cert_reqs': ssl.CERT_REQUIRED,  # Require client certificates
                'ssl_version': ssl.PROTOCOL_TLS_SERVER,
                'ciphers': 'TLSv1.2:!aNULL:!eNULL:!EXPORT:!DES:!MD5:!PSK:!RC4'
            }
    
    def get_spiffe_id(self) -> Optional[str]:
        """Get current SPIFFE ID"""
        return self.spiffe_id
    
    def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up SVID Manager")
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


# Global SVID manager instance
svid_manager = SVIDManager()
