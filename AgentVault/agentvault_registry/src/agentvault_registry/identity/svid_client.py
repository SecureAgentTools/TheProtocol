# APEX PREDATOR SPIFFE FALLBACK SOLUTION
# File: svid_client_with_fallback.py
# Purpose: Allow development on Docker Desktop for Windows with mock SVIDs

"""SVID Client with Mock Fallback for AgentVault Registry

This module handles SPIFFE SVID acquisition with a fallback to mock SVIDs
for development environments where Docker attestation doesn't work properly.
"""

import logging
import os
import ssl
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import threading
import time
import random
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtensionOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ..core.tls_client import client_cert_verify

try:
    from spiffe import WorkloadApiClient
    from spiffe.errors import PySpiffeError as SpiffeError
    PYSPIFFE_AVAILABLE = True
    default_workload_api_client = WorkloadApiClient
except ImportError:
    PYSPIFFE_AVAILABLE = False
    default_workload_api_client = None
    SpiffeError = Exception

logger = logging.getLogger(__name__)
from pathlib import Path as pathlib_Path  # noqa: E402

# §BATCH8 item 5 — the watcher's gauges (best-effort; a registry without prometheus_client keeps running).
try:
    from prometheus_client import Gauge as _G, Counter as _C
    _SVID_LAST_POLL = _G("registry_svid_last_poll_unixtime", "When the SVID watcher last polled the Workload API")
    _SVID_BUNDLE_ROOTS = _G("registry_svid_bundle_roots", "PEM roots in the SVID watcher's last trust-bundle snapshot")
    _SVID_POLLS = _C("registry_svid_polls_total", "SVID watcher polls by outcome", ["outcome"])
except Exception:  # pragma: no cover — no prometheus, no gauges
    class _Noop:
        def set(self, *a, **k): pass
        def inc(self, *a, **k): pass
        def labels(self, *a, **k): return self
    _SVID_LAST_POLL = _SVID_BUNDLE_ROOTS = _SVID_POLLS = _Noop()


class SVIDClient:
    """Manages SPIFFE SVIDs for the Registry backend client connections"""
    
    def __init__(self):
        # §BATCH8 item 5 (2026-09-06) — the watcher's own clock. Measured on the fresh pair: the 30-minute
        # poll never replaced a 1-root boot snapshot in 2 h 15 min and nothing said so. Every poll now
        # stamps these (read by watcher_state(), exported as gauges), and logs the root count.
        self.last_poll_at: float = 0.0
        self.last_poll_ok: Optional[bool] = None
        self.last_poll_roots: int = 0
        self.last_poll_error: str = ""
        self.spiffe_id: Optional[str] = None
        self.cert_path: Optional[Path] = None
        self.key_path: Optional[Path] = None
        self.bundle_path: Optional[Path] = None
        self._lock = threading.Lock()
        self._update_thread: Optional[threading.Thread] = None
        self._running = False
        self._initialized = False
        self._using_mock = False
        
    def initialize(self) -> bool:
        """Initialize SVID client and fetch initial certificates"""
        try:
            logger.info("Initializing SVID Client for Registry backend")
            
            if not PYSPIFFE_AVAILABLE:
                logger.warning("spiffe library not available, falling back to mock SVIDs")
                return self._initialize_mock_svid()
            
            # Check if SPIFFE endpoint socket is configured
            spiffe_socket = os.environ.get('SPIFFE_ENDPOINT_SOCKET')
            if not spiffe_socket:
                logger.info("SPIFFE_ENDPOINT_SOCKET not set, falling back to mock SVIDs")
                return self._initialize_mock_svid()
                
            logger.info(f"Using SPIFFE endpoint (raw): {spiffe_socket}")
            
            # FIX-001 (OWL17): Normalize the SPIFFE socket path.
            # PySpiffe's WorkloadApiClient expects the env var to be in
            # 'unix:/path/to/socket' format (single slash after colon).
            # Docker-compose often sets 'unix:///path' (triple slash) which
            # causes PySpiffe to look for file '///path' (does not exist).
            # We normalize to the canonical 'unix:/absolute/path' format.
            normalized_socket = spiffe_socket
            if normalized_socket.startswith('unix://'):
                # unix:///opt/spire/sockets/agent.sock → /opt/spire/sockets/agent.sock
                socket_path = normalized_socket[len('unix://'):]
                # Remove any extra leading slashes but keep one absolute /
                socket_path = '/' + socket_path.lstrip('/')
                normalized_socket = f'unix:{socket_path}'
            elif normalized_socket.startswith('unix:') and not normalized_socket.startswith('unix:/'):
                # unix:opt/... → unix:/opt/...
                socket_path = normalized_socket[len('unix:'):]
                normalized_socket = f'unix:/{socket_path}'
            elif not normalized_socket.startswith('unix:'):
                # Plain path: /opt/spire/sockets/agent.sock → unix:/opt/spire/sockets/agent.sock
                normalized_socket = f'unix:{normalized_socket}'
            
            logger.info(f"Normalized SPIFFE endpoint: {normalized_socket}")
            
            # Extract the file path to verify the socket exists
            socket_file_path = normalized_socket.replace('unix:', '')
            
            # Set the normalized environment variable for PySpiffe
            os.environ['SPIFFE_ENDPOINT_SOCKET'] = normalized_socket
            
            # FIX-001 (OWL17): Retry loop — SPIRE agent socket may not be
            # ready when the registry container starts (depends_on only
            # waits for container start, not socket creation).
            max_retries = 5
            retry_delay = 3  # seconds
            svid_acquired = False
            
            for attempt in range(1, max_retries + 1):
                # Check if socket file exists before trying PySpiffe
                if not os.path.exists(socket_file_path):
                    logger.warning(
                        f"SPIFFE socket not yet available at {socket_file_path} "
                        f"(attempt {attempt}/{max_retries}), waiting {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
                    continue
                
                logger.info(f"SPIFFE socket found at {socket_file_path}, fetching SVID (attempt {attempt})")
                if self._fetch_and_store_svid():
                    svid_acquired = True
                    break
                else:
                    logger.warning(f"SVID fetch failed (attempt {attempt}/{max_retries})")
                    if attempt < max_retries:
                        time.sleep(retry_delay)
            
            if not svid_acquired:
                logger.warning("Failed to fetch real SVID after retries, falling back to mock SVIDs")
                return self._initialize_mock_svid()
                
            # Start SVID watcher thread
            self._start_svid_watcher()
            
            self._initialized = True
            logger.info("SVID Client initialized successfully with real SVIDs")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize SVID Client: {e}")
            logger.warning("Falling back to mock SVIDs")
            return self._initialize_mock_svid()
    
    def _initialize_mock_svid(self) -> bool:
        """Initialize with mock SVIDs for development environments"""
        try:
            logger.info("Initializing mock SVIDs for development")
            self._using_mock = True
            
            # Determine SPIFFE ID based on registry name
            registry_name = os.environ.get('REGISTRY_NAME', 'unknown').lower()
            if 'registry-a' in registry_name:
                self.spiffe_id = "spiffe://agentvault.com/registry-a"
            elif 'registry-b' in registry_name:
                self.spiffe_id = "spiffe://agentvault.com/registry-b"
            else:
                self.spiffe_id = f"spiffe://agentvault.com/registry-{registry_name}"
            
            logger.info(f"Using mock SPIFFE ID: {self.spiffe_id}")
            
            # Generate mock certificate and key
            self._generate_mock_svid()
            
            self._initialized = True
            logger.info("Mock SVID Client initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize mock SVID: {e}")
            return False
    
    def _generate_mock_svid(self):
        """Generate a mock X.509 SVID for development"""
        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )
        
        # Create certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "Mock SVID"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AgentVault Development"),
        ])
        
        # Add SPIFFE ID as SAN
        san = x509.SubjectAlternativeName([
            x509.UniformResourceIdentifier(self.spiffe_id),
        ])
        
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.now(timezone.utc)
        ).not_valid_after(
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).add_extension(
            san,
            critical=False,
        ).sign(private_key, hashes.SHA256())
        
        # Write certificate to file
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.crt') as cert_file:
            cert_file.write(cert.public_bytes(serialization.Encoding.PEM))
            self.cert_path = Path(cert_file.name)
        
        # Write private key to file
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.key') as key_file:
            key_file.write(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ))
            self.key_path = Path(key_file.name)
        
        # Write trust bundle (same cert for mock)
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.bundle') as bundle_file:
            bundle_file.write(cert.public_bytes(serialization.Encoding.PEM))
            self.bundle_path = Path(bundle_file.name)
        
        # Set restrictive permissions
        os.chmod(self.cert_path, 0o600)
        os.chmod(self.key_path, 0o600)
        os.chmod(self.bundle_path, 0o600)
        
        logger.info(f"Generated mock SVID, expires: {cert.not_valid_after}")
    
    def _fetch_and_store_svid(self) -> bool:
        """Fetch X.509 SVID and store to temporary files"""
        if not PYSPIFFE_AVAILABLE or not default_workload_api_client:
            return False
            
        try:
            with default_workload_api_client() as client:
                # Fetch X.509 context
                x509_context = client.fetch_x509_context()
                
                # FIX-009 (OWL17): PySpiffe API compatibility.
                # In newer PySpiffe (>=0.8), default_svid is a PROPERTY, not a method.
                # In older versions it was callable. Handle both.
                if callable(getattr(x509_context, 'default_svid', None)):
                    svid = x509_context.default_svid()
                else:
                    svid = x509_context.default_svid
                
                self.spiffe_id = str(svid.spiffe_id)
                
                # Get trust bundle set
                # Also handle property vs method for x509_bundle_set
                if callable(getattr(x509_context, 'x509_bundle_set', None)):
                    bundle_set = x509_context.x509_bundle_set()
                else:
                    bundle_set = x509_context.x509_bundle_set
                
                # Get leaf certificate — handle both .leaf and .cert_chain[0]
                leaf_cert = getattr(svid, 'leaf', None)
                if leaf_cert is None and hasattr(svid, 'cert_chain') and svid.cert_chain:
                    leaf_cert = svid.cert_chain[0]
                
                if leaf_cert is None:
                    logger.error("Could not extract leaf certificate from SVID")
                    return False
                
                logger.info(f"Fetched SVID with SPIFFE ID: {self.spiffe_id}")
                logger.info(f"Certificate expires: {leaf_cert.not_valid_after}")
                
                # Get intermediate certificates
                intermediates = getattr(svid, 'intermediates', [])
                if not intermediates and hasattr(svid, 'cert_chain') and len(svid.cert_chain) > 1:
                    intermediates = svid.cert_chain[1:]
                
                # Write certificate chain to file
                with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.crt') as cert_file:
                    # Write leaf certificate
                    cert_file.write(leaf_cert.public_bytes(serialization.Encoding.PEM))
                    # Write intermediate certificates if any
                    for intermediate in intermediates:
                        cert_file.write(intermediate.public_bytes(serialization.Encoding.PEM))
                    self.cert_path = Path(cert_file.name)
                
                # Write private key to file
                with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.key') as key_file:
                    key_file.write(svid.private_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption()
                    ))
                    self.key_path = Path(key_file.name)
                
                # Write trust bundle to file
                with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.bundle') as bundle_file:
                    bundle_written = False
                    
                    # FIX-010 (OWL17): Robust trust bundle extraction.
                    # PySpiffe X509BundleSet API varies across versions.
                    # Try multiple approaches to extract CA certificates.
                    
                    # Approach 1: bundle_set._bundles (internal dict, most reliable)
                    bundles_dict = getattr(bundle_set, '_bundles', None)
                    if bundles_dict is None:
                        bundles_dict = getattr(bundle_set, 'bundles', None)
                    
                    if isinstance(bundles_dict, dict) and bundles_dict:
                        for trust_domain, x509_bundle in bundles_dict.items():
                            logger.info(f"Adding trust bundle for domain: {trust_domain}")
                            # Try multiple attribute names for CA authorities
                            authorities = (
                                getattr(x509_bundle, '_x509_authorities', None) or
                                getattr(x509_bundle, 'x509_authorities', None) or
                                getattr(x509_bundle, 'authorities', None) or
                                []
                            )
                            for ca_cert in authorities:
                                bundle_file.write(ca_cert.public_bytes(serialization.Encoding.PEM))
                                bundle_written = True
                    
                    # Approach 2: get_bundle_for_trust_domain
                    if not bundle_written:
                        try:
                            from spiffe import TrustDomain
                            td = TrustDomain('agentvault.com')
                            bundle = bundle_set.get_bundle_for_trust_domain(td)
                            if bundle:
                                authorities = (
                                    getattr(bundle, '_x509_authorities', None) or
                                    getattr(bundle, 'x509_authorities', None) or
                                    []
                                )
                                for ca_cert in authorities:
                                    bundle_file.write(ca_cert.public_bytes(serialization.Encoding.PEM))
                                    bundle_written = True
                                    logger.info("Extracted trust bundle via get_bundle_for_trust_domain")
                        except Exception as e:
                            logger.debug(f"Approach 2 failed: {e}")
                    
                    # Fallback: use leaf cert as self-signed CA
                    if not bundle_written:
                        logger.warning(
                            "Could not extract trust bundles from PySpiffe "
                            f"(bundle_set type: {type(bundle_set).__name__}, "
                            f"attrs: {[a for a in dir(bundle_set) if not a.startswith('__')]}). "
                            "Using leaf cert as CA fallback."
                        )
                        bundle_file.write(leaf_cert.public_bytes(serialization.Encoding.PEM))
                    
                    self.bundle_path = Path(bundle_file.name)
                
                # Set restrictive permissions
                os.chmod(self.cert_path, 0o600)
                os.chmod(self.key_path, 0o600)
                os.chmod(self.bundle_path, 0o600)
                
                return True
                
        except SpiffeError as e:
            logger.error(f"SPIFFE error while fetching SVID: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error fetching SVID: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    def _start_svid_watcher(self):
        """Start background thread to watch for SVID updates"""
        if self._using_mock:
            # Start a thread to refresh mock SVIDs periodically
            self._running = True
            self._update_thread = threading.Thread(
                target=self._watch_mock_svid_expiry,
                name="registry-mock-svid-watcher",
                daemon=True
            )
            self._update_thread.start()
            logger.info("Started mock SVID watcher thread")
        else:
            # Original SVID watcher
            self._running = True
            self._update_thread = threading.Thread(
                target=self._watch_svid_updates,
                name="registry-svid-watcher",
                daemon=True
            )
            self._update_thread.start()
            logger.info("Started SVID watcher thread")
    
    def _watch_mock_svid_expiry(self):
        """Watch for mock SVID expiry and refresh"""
        logger.info("Mock SVID watcher thread started")
        
        while self._running:
            try:
                # Refresh mock SVID every 45 minutes (before 1-hour expiry)
                time.sleep(45 * 60)
                
                if not self._running:
                    break
                
                with self._lock:
                    old_cert_path = self.cert_path
                    old_key_path = self.key_path
                    old_bundle_path = self.bundle_path
                    
                    logger.info("Refreshing mock SVID")
                    self._generate_mock_svid()
                    
                    # Clean up old files
                    if old_cert_path and old_cert_path.exists():
                        old_cert_path.unlink()
                    if old_key_path and old_key_path.exists():
                        old_key_path.unlink()
                    if old_bundle_path and old_bundle_path.exists():
                        old_bundle_path.unlink()
                        
            except Exception as e:
                logger.error(f"Error in mock SVID watcher: {e}")
                if self._running:
                    time.sleep(30)  # Wait before retrying
    
    def refresh_now(self) -> Tuple[bool, str]:
        """Synchronously force-refresh SVID + trust bundle from the Workload API.

        Used after bilateral SPIRE bundle exchange (WS3 frame onboarding) so
        the local registry's mTLS verify chain picks up newly federated peer
        bundles without waiting for the 30-minute poll cycle. Holds `self._lock`
        to avoid racing the polling thread. Old cert/key/bundle paths are
        cleaned up only on successful refresh.

        Returns (ok, message). Safe to call when running on mock SVID — falls
        through to fail with an explanatory message.
        """
        if not self._running:
            return False, "SVID client not running"
        if self._using_mock:
            return False, "Running on mock SVID — refresh_now is a SPIRE-only operation"
        if not PYSPIFFE_AVAILABLE or not default_workload_api_client:
            return False, "spiffe library not available"

        with self._lock:
            old_cert_path = self.cert_path
            old_key_path = self.key_path
            old_bundle_path = self.bundle_path

            logger.info("SVID refresh_now: explicit refresh requested")
            if not self._fetch_and_store_svid():
                return False, "fetch_and_store_svid failed"

            # Clean up old files only after a successful refresh
            for old in (old_cert_path, old_key_path, old_bundle_path):
                if old and old.exists():
                    try:
                        old.unlink()
                    except Exception:
                        pass

            return True, f"Rotated SVID for {self.spiffe_id}"

    def _watch_svid_updates(self):
        """Watch for SVID updates and refresh certificates.

        FIX-010 (OWL17): Replaced streaming watcher with polling.
        PySpiffe's watch_x509_context() is not available in all versions.
        Instead, we poll every 30 minutes (SVID TTL is 1 hour) and
        re-fetch from the Workload API.
        """
        logger.info("SVID watcher thread started (polling mode, 30min interval)")
        
        if not PYSPIFFE_AVAILABLE or not default_workload_api_client:
            logger.warning("SVID watcher cannot run without spiffe")
            return
        
        # Poll interval: refresh well before the 1-hour TTL expires
        poll_interval = 30 * 60  # 30 minutes

        # Part 19a: initial jitter to prevent thundering-herd SVID rotation.
        # 20 uvicorn workers are forked from the same parent with identical
        # timer state, so without jitter they all hit their poll interval at
        # the exact same wall-clock instant and rotate simultaneously
        # (observed: 20 rotations in 7 seconds on 2026-04-11 03:23:20).
        # Randomizing the initial offset spreads rotations over 60 seconds.
        _initial_jitter = random.uniform(0, 60)
        logger.info(f"SVID watcher: applying initial jitter of {_initial_jitter:.1f}s")
        time.sleep(_initial_jitter)

        while self._running:
            try:
                # Sleep first — initial SVID was already fetched during init
                for _ in range(poll_interval):
                    if not self._running:
                        return
                    time.sleep(1)
                
                if not self._running:
                    break
                
                with self._lock:
                    old_cert_path = self.cert_path
                    old_key_path = self.key_path
                    old_bundle_path = self.bundle_path
                    
                    logger.info("SVID rotation: refreshing certificates from SPIRE")
                    
                    if self._fetch_and_store_svid():
                        self._note_poll(True)
                        logger.info(
                            f"[SVID] poll ok: rotated {self.spiffe_id} bundle_roots={self.last_poll_roots} "
                            f"disk_roots={self._disk_bundle_roots()}"
                        )
                        
                        # Clean up old files
                        if old_cert_path and old_cert_path.exists():
                            old_cert_path.unlink()
                        if old_key_path and old_key_path.exists():
                            old_key_path.unlink()
                        if old_bundle_path and old_bundle_path.exists():
                            old_bundle_path.unlink()
                    else:
                        self._note_poll(False, "fetch_and_store_svid failed")
                        logger.error("[SVID] poll FAILED: fetch_and_store_svid returned False — continuing with the existing snapshot")
                                
            except Exception as e:
                self._note_poll(False, repr(e))
                logger.error(f"[SVID] poll FAILED: {e}")
                if self._running:
                    time.sleep(60)  # Wait before retrying
    
    @staticmethod
    def count_roots(path) -> int:
        """PEM certificates in a bundle file (0 when unreadable) — the number a federation changes."""
        try:
            return str(pathlib_Path(path).read_text(errors="replace")).count("BEGIN CERTIFICATE")
        except Exception:
            return 0

    def _disk_bundle_roots(self) -> int:
        cert_dir = os.getenv("SVID_CERT_DIR", os.getenv("CERT_DIR", "/certs"))
        return self.count_roots(os.path.join(cert_dir, "bundle.0.pem"))

    def _note_poll(self, ok: bool, error: str = "") -> None:
        """§BATCH8 item 5 — one place the watcher reports; gauges are best-effort (no prometheus, no crash)."""
        self.last_poll_at = time.time()
        self.last_poll_ok = ok
        self.last_poll_error = "" if ok else (error or "unknown")[:200]
        self.last_poll_roots = self.count_roots(self.bundle_path) if self.bundle_path else 0
        try:
            _SVID_LAST_POLL.set(self.last_poll_at)
            _SVID_BUNDLE_ROOTS.set(self.last_poll_roots)
            _SVID_POLLS.labels(outcome="ok" if ok else "failed").inc()
        except Exception:
            pass

    def watcher_state(self) -> Dict[str, Any]:
        """What the poller last did — for /admin/workers/status and any vitals reader. `never` when the
        thread has not polled since boot (the first poll is 30 min + jitter after start)."""
        return {
            "last_poll_at": self.last_poll_at or None,
            "last_poll_ok": self.last_poll_ok,
            "last_poll_roots": self.last_poll_roots,
            "last_poll_error": self.last_poll_error,
            "snapshot_roots": self.count_roots(self.bundle_path) if self.bundle_path else 0,
            "disk_roots": self._disk_bundle_roots(),
            "age_sec": (time.time() - self.last_poll_at) if self.last_poll_at else None,
        }

    def _freshest_bundle_path(self) -> str:
        """§BATCH7 (2026-09-05) — the trust bundle peers are VERIFIED against: the boot-time
        Workload-API snapshot (a temp file, re-fetched by the 30-minute poll) or the cert-writer's
        on-disk `$SVID_CERT_DIR/bundle.0.pem`, whichever is NEWER.

        A federation established AFTER boot (the fresh pair: frames up 20:4xZ, JUICE↔BRRR
        approved 21:02Z) reaches the on-disk bundle on the cert-writer's next cycle but the
        snapshot only at the next poll — up to 30 minutes in which every RegistryCardFanout and
        agent-card pull failed CERTIFICATE_VERIFY_FAILED and parked the peer 33 minutes, while a
        fresh context built from the on-disk file verified every peer (measured 21:16–21:21Z).
        The SVID (cert/key) stays the snapshot's: identity rotates on the poll, trust follows the
        freshest file. No on-disk bundle (mock SVID, a node without a cert-writer) → the snapshot."""
        snap = str(self.bundle_path)
        cert_dir = os.getenv("SVID_CERT_DIR", os.getenv("CERT_DIR", "/certs"))
        disk = os.path.join(cert_dir, "bundle.0.pem")
        try:
            if os.path.exists(disk) and os.path.getsize(disk) > 0 and (
                not os.path.exists(snap) or os.path.getmtime(disk) >= os.path.getmtime(snap)
            ):
                return disk
        except OSError:
            pass
        return snap

    def get_client_cert_config(self, target_url: str = "") -> Optional[Dict[str, Any]]:
        """Get client certificate configuration for HTTPX

        Args:
            target_url: The URL being connected to. If the hostname contains a dot
                        (public domain), uses system CAs for server verification.
                        If no dot (Docker-internal hostname), uses SPIRE trust bundle.

        Returns:
            Dict with cert and verify paths for HTTPX client, or None if not available
        """
        with self._lock:
            if not all([self.cert_path, self.key_path, self.bundle_path]):
                return None

            # Determine verify mode by port:
            # - Port 443 (or default HTTPS): server has Let's Encrypt cert → system CAs
            # - Non-standard port (8443, 12443, etc.): server has SPIRE cert → SPIRE bundle
            # This correctly handles: A→B (nginx:8443, SPIRE), A→operator (domain:13443, SPIRE),
            # operator→A (domain:443, Let's Encrypt)
            verify = self._freshest_bundle_path()
            if target_url:
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(target_url)
                    port = parsed.port  # None if default (443 for https)
                    if port is None or port == 443:
                        verify = True  # Standard HTTPS = Let's Encrypt = system CAs
                except Exception:
                    pass

            cert = (str(self.cert_path), str(self.key_path))  # SPIRE SVID client cert
            # §DEPS: a bundle PATH beside a client cert becomes one SSLContext holding both. httpx 0.28 drops `cert`
            # beside a path (core/tls_client.py), so every SPIRE-verified peer (a non-443 port) would get no client
            # certificate. 'cert' stays in the dict for the callers that read it (the prober's raw TLS, public_directory).
            return {
                'cert': cert,
                'verify': client_cert_verify(verify, cert)
            }
    
    def get_spiffe_id(self) -> Optional[str]:
        """Get current SPIFFE ID"""
        return self.spiffe_id
    
    def get_client_spiffe_id(self) -> Optional[str]:
        """Get client SPIFFE ID (for compatibility)"""
        # In a real implementation, this would extract the client's SPIFFE ID
        # from the TLS connection context. For now, return None to indicate
        # no client authentication.
        return None
    
    def is_initialized(self) -> bool:
        """Check if SVID client is initialized and ready"""
        return self._initialized and self.get_client_cert_config() is not None
    
    def is_using_mock(self) -> bool:
        """Check if using mock SVIDs"""
        return self._using_mock
    
    def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up SVID Client")
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

    # ------------------------------------------------------------------
    # Phase 11.2 (2026-04-28): JWT-SVID minting
    # ------------------------------------------------------------------
    # Audience-scoped JWT-SVID for client identity on internal-network calls
    # where mTLS isn't viable (e.g., the EventStore /ws/events handshake — the
    # FastAPI WebSocket route can't terminate mTLS upstream of the ASGI handler
    # without bespoke nginx config, but it CAN read a `?token=<jwt>` query).
    #
    # Returns a freshly-minted JWT-SVID string each call. PySpiffe's workload
    # API caches under the hood — this method does not cache to keep semantics
    # simple. Callers should batch one mint per WS reconnect, not per message.
    #
    # Returns None when:
    #   - PySpiffe is unavailable (mock mode)
    #   - The workload API returns no JWT-SVID for the requested audience
    #   - Any exception occurred (best-effort, never raises)
    def get_jwt_svid(self, audience: str) -> Optional[str]:
        """Mint a JWT-SVID for the given audience.

        Backwards-compat: returns None on mock SVID, missing pyspiffe, or
        unreachable workload API. Caller should fall back to shared-secret
        in that case.
        """
        if self._using_mock:
            return None
        if not PYSPIFFE_AVAILABLE or not default_workload_api_client:
            return None
        try:
            with default_workload_api_client() as client:
                # pyspiffe expects audience as Set[str], NOT a single str.
                # Passing a bare string makes it iterate char-by-char into
                # a multi-audience list (`['s', 'p', 'i', ...]`) which then
                # fails JWT validation. Wrap in a single-element set.
                jwt_svid = client.fetch_jwt_svid(audience={audience})
                if jwt_svid is None:
                    return None
                # PySpiffe's JwtSvid.token holds the JWS-encoded string in
                # current versions; some return strings directly. Handle both.
                token = getattr(jwt_svid, "token", None)
                if isinstance(token, str) and token:
                    return token
                if isinstance(jwt_svid, str):
                    return jwt_svid
                token_method = getattr(jwt_svid, "as_token", None)
                if callable(token_method):
                    out = token_method()
                    return out if isinstance(out, str) else None
                return None
        except Exception as e:
            logger.warning(f"get_jwt_svid({audience!r}) failed: {e}")
            return None


# Global SVID client instance
svid_client = SVIDClient()
