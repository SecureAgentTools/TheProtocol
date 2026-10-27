"""
f052: A2AAuthenticator — Hybrid mTLS + Payment Token Authentication (IRONHAND)

FastAPI Depends() middleware that authenticates A2A callers via:
  1. mTLS client certificate (SPIFFE SVID) — extracted from X-SSL-Client-Cert header
     (behind nginx) or TLS connection info (direct connection)
  2. Payment token (X-Payment-Token header) — delegated to PaymentVerifier

Both can coexist on the same request (belt-and-suspenders).

Revocation enforcement:
  - Maintains a shared blocklist of revoked SPIFFE IDs
  - Polls GET /api/v1/agent/revoked-identities every 60 seconds (fallback)
  - Rejects any mTLS call from a blocklisted SPIFFE ID immediately

Usage:
    from theprotocol.payment.authenticator import A2AAuthenticator
    authenticator = A2AAuthenticator(payment_verifier=my_verifier)
    @app.post("/a2a", dependencies=[Depends(authenticator)])
"""
import asyncio
import logging
import os
import threading
import time
import urllib.parse
from typing import Any, ClassVar, Dict, Optional, Set

try:
    from starlette.requests import Request as StarletteRequest
except ImportError:
    StarletteRequest = Any  # type: ignore

logger = logging.getLogger(__name__)

# ── Shared revocation blocklist (class-level, all instances) ──────────
_revoked_spiffe_ids: Set[str] = set()
_blocklist_poller_started = False
_blocklist_ws_started = False
_blocklist_lock = threading.Lock()

from ..dids import did_from_spiffe_path

def _extract_spiffe_id_from_pem(pem_str: str) -> Optional[str]:
    """Parse a PEM certificate and extract the SPIFFE ID from the URI SAN."""
    try:
        from cryptography import x509
        from cryptography.x509.oid import ExtensionOID

        cert = x509.load_pem_x509_certificate(pem_str.encode("utf-8"))
        try:
            san_ext = cert.extensions.get_extension_for_oid(
                ExtensionOID.SUBJECT_ALTERNATIVE_NAME
            )
            for name in san_ext.value.get_values_for_type(
                x509.UniformResourceIdentifier
            ):
                if name.startswith("spiffe://"):
                    return name
        except x509.ExtensionNotFound:
            pass
    except ImportError:
        logger.warning(
            "[A2AAuthenticator] cryptography library not installed — "
            "cannot parse client certs"
        )
    except Exception as e:
        logger.debug(f"[A2AAuthenticator] Failed to parse PEM cert: {e}")
    return None


def _did_from_spiffe_id(spiffe_id: str, trust_domain: str) -> Optional[str]:
    """Extract agent DID from SPIFFE ID path.

    spiffe://eu.theprotocol.cloud/agent/did-theprotocol-eu.theprotocol.cloud-<uuid4>
    → did:theprotocol:eu.theprotocol.cloud:<uuid4>   (the issuer's colon restored, since 0.7.5)
    spiffe://agentvault.com/agent/did-theprotocol-4c78...
    → did:theprotocol:4c78...
    """
    prefix = f"spiffe://{trust_domain}/agent/"
    if not spiffe_id.startswith(prefix):
        return None
    return did_from_spiffe_path(spiffe_id[len(prefix):])


def _start_blocklist_poller(registry_url: str, poll_interval: int = 60):
    """Start a background thread that polls the revoked-identities endpoint.

    This is the fallback mechanism. The primary is EventStore WebSocket (future).
    Runs as a daemon thread — dies with the process.
    """
    global _blocklist_poller_started
    with _blocklist_lock:
        if _blocklist_poller_started:
            return
        _blocklist_poller_started = True

    def _poll():
        import urllib.request
        import json

        url = f"{registry_url}/api/v1/agent/revoked-identities"
        while True:
            try:
                time.sleep(poll_interval)
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                    revoked = data.get("revoked", [])
                    new_ids = {r["spiffe_id"] for r in revoked if r.get("spiffe_id")}
                    if new_ids != _revoked_spiffe_ids:
                        added = new_ids - _revoked_spiffe_ids
                        removed = _revoked_spiffe_ids - new_ids
                        _revoked_spiffe_ids.clear()
                        _revoked_spiffe_ids.update(new_ids)
                        if added:
                            logger.info(
                                f"[A2AAuthenticator] Blocklist updated: "
                                f"+{len(added)} revoked, -{len(removed)} restored, "
                                f"total={len(_revoked_spiffe_ids)}"
                            )
            except Exception as e:
                logger.debug(f"[A2AAuthenticator] Blocklist poll failed: {e}")

    t = threading.Thread(target=_poll, daemon=True, name="ironhand-blocklist-poller")
    t.start()
    logger.info(
        f"[A2AAuthenticator] Blocklist poller started "
        f"(registry={registry_url}, interval={poll_interval}s)"
    )


def _start_ws_listener(event_store_ws_url: str):
    """Start a background thread that listens to EventStore WebSocket for
    real-time revocation/enrollment events. Sub-1s blocklist updates.

    Subscribes to:
      - events:AgentMtlsRevoked → add to blocklist
      - events:AgentMtlsEnrolled → remove from blocklist

    Auto-reconnects with exponential backoff on disconnect.
    """
    global _blocklist_ws_started
    with _blocklist_lock:
        if _blocklist_ws_started:
            return
        _blocklist_ws_started = True

    def _ws_loop():
        import json

        ws_url = f"{event_store_ws_url.rstrip('/')}/ws/events"
        backoff = 1

        while True:
            try:
                import websockets.sync.client as ws_sync
                logger.info(f"[A2AAuthenticator] WS connecting to {ws_url}")

                with ws_sync.connect(ws_url, close_timeout=5) as ws:
                    # Read welcome message
                    welcome = ws.recv(timeout=10)
                    logger.info(f"[A2AAuthenticator] WS connected to EventStore")

                    # Subscribe to revocation + enrollment channels
                    ws.send(json.dumps({"action": "subscribe", "channel": "events:AgentMtlsRevoked"}))
                    ws.recv(timeout=5)  # confirmation
                    ws.send(json.dumps({"action": "subscribe", "channel": "events:AgentMtlsEnrolled"}))
                    ws.recv(timeout=5)  # confirmation

                    logger.info(
                        "[A2AAuthenticator] WS subscribed to AgentMtlsRevoked + AgentMtlsEnrolled"
                    )
                    backoff = 1  # reset on successful connection

                    # Listen for events
                    while True:
                        raw = ws.recv(timeout=300)  # 5min keepalive timeout
                        try:
                            msg = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            continue

                        if msg.get("type") != "event":
                            continue

                        event = msg.get("event", {})
                        event_type = event.get("event_type", "")
                        event_data = event.get("data", {})
                        spiffe_id = event_data.get("spiffe_id", "")

                        if not spiffe_id:
                            continue

                        if event_type == "AgentMtlsRevoked":
                            _revoked_spiffe_ids.add(spiffe_id)
                            logger.info(
                                f"[A2AAuthenticator] WS REVOKED: {spiffe_id} "
                                f"(blocklist={len(_revoked_spiffe_ids)})"
                            )
                        elif event_type == "AgentMtlsEnrolled":
                            _revoked_spiffe_ids.discard(spiffe_id)
                            logger.info(
                                f"[A2AAuthenticator] WS ENROLLED: {spiffe_id} removed from blocklist "
                                f"(blocklist={len(_revoked_spiffe_ids)})"
                            )

            except ImportError:
                logger.warning(
                    "[A2AAuthenticator] websockets library not installed — "
                    "WS listener disabled, using polling only"
                )
                return  # exit thread permanently
            except Exception as e:
                logger.warning(
                    f"[A2AAuthenticator] WS disconnected: {e}. "
                    f"Reconnecting in {backoff}s..."
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)

    t = threading.Thread(target=_ws_loop, daemon=True, name="ironhand-ws-listener")
    t.start()
    logger.info(f"[A2AAuthenticator] WS listener started (url={event_store_ws_url})")


class A2AAuthenticator:
    """Unified A2A authenticator (Q-C BL-3, 2026-05-12).

    Fans out across the three A2A auth surfaces — all expressible in A2A v1.0
    §4.5 SecurityScheme vocabulary:

      Strategy 1 — IRONHAND mTLS (MutualTlsSecurityScheme, §4.5.6 native)
                    SPIFFE x509 SVID via TLS handshake. Header
                    X-SSL-Client-Cert (nginx-forwarded PEM) or raw TLS scope.
      Strategy 2 — Agent JWT (HTTPAuthSecurityScheme bearer/JWT, §4.5.3)
                    Authorization: Bearer <agent_jwt>. Delegated to
                    ``AgentJwtVerifier`` (theprotocol.auth.jwt_verifier).
      Strategy 3 — Payment token (APIKeySecurityScheme + TheProtocol extension)
                    X-Payment-Token: apt_<hex>. Delegated to
                    ``PaymentVerifier`` (theprotocol.payment.verifier).

    All three may coexist on the same request — first one that verifies wins,
    but agents may pin to a single surface by passing only the relevant
    verifier(s).

    Revocation: checks caller's SPIFFE ID against a shared blocklist updated via:
    1. EventStore WebSocket (sub-1s, if EVENT_STORE_WS_URL configured)
    2. Polling GET /agent/revoked-identities (60s fallback)
    A revoked identity gets an immediate 403, even if the SVID cert is still
    cryptographically valid.

    Args:
        payment_verifier: Optional PaymentVerifier instance (Strategy 3).
        agent_jwt_verifier: Optional AgentJwtVerifier instance (Strategy 2,
            BL-3). If absent and ``registry_url`` is set, a default verifier
            pointing at the same registry is created.
        trust_domain: Expected SPIFFE trust domain(s), comma-separated for
            multi-frame federation (e.g. "eu.theprotocol.cloud"). Default: the
            THEPROTOCOL_TRUST_DOMAIN env; with neither set, the legacy
            "agentvault.com" with a warning.
        required: If True, raises 401 when no strategy succeeds.
        registry_url: Registry URL for blocklist polling + default
            AgentJwtVerifier (default: REGISTRY_URL env).
        poll_interval: Blocklist poll interval in seconds (default: 60).
        event_store_ws_url: EventStore WebSocket URL for real-time revocation
            (default: EVENT_STORE_WS_URL env).
        auto_jwt_verifier: If True (default) and ``agent_jwt_verifier`` is None
            and a ``registry_url`` is available, auto-instantiate a default
            ``AgentJwtVerifier`` so callers get JWT auth out of the box.
    """

    def __init__(
        self,
        payment_verifier: Any = None,
        trust_domain: Optional[str] = None,
        required: bool = False,
        registry_url: str = "",
        poll_interval: int = 60,
        event_store_ws_url: str = "",
        agent_jwt_verifier: Any = None,
        auto_jwt_verifier: bool = True,
    ):
        self.payment_verifier = payment_verifier
        self.required = required
        # The caller's, else the environment's, else the legacy default (kept so nothing that worked stops working)
        trust_domain = (trust_domain or os.environ.get("THEPROTOCOL_TRUST_DOMAIN", "")).strip()
        if not trust_domain:
            trust_domain = "agentvault.com"
            logger.warning(
                "[A2AAuthenticator] no trust_domain and no THEPROTOCOL_TRUST_DOMAIN: using the legacy "
                "'agentvault.com'; pass your frame's trust domain (e.g. 'eu.theprotocol.cloud')"
            )
        # Support comma-separated trust domains for cross-frame federation
        if "," in trust_domain:
            self.trusted_domains = [d.strip() for d in trust_domain.split(",") if d.strip()]
        else:
            self.trusted_domains = [trust_domain]
        self.trust_domain = self.trusted_domains[0]  # primary domain (backward compat)

        # Resolve effective registry URL once for reuse below.
        reg_url = registry_url or os.environ.get("REGISTRY_URL", "")

        # Agent JWT verifier (Strategy 2 — BL-3 core). Lazy-construct a default
        # when caller didn't supply one but registry_url is reachable.
        self.agent_jwt_verifier = agent_jwt_verifier
        if self.agent_jwt_verifier is None and auto_jwt_verifier and reg_url:
            try:
                from ..auth.jwt_verifier import AgentJwtVerifier
                self.agent_jwt_verifier = AgentJwtVerifier(registry_url=reg_url)
                logger.debug(
                    "[A2AAuthenticator] Auto-instantiated AgentJwtVerifier (registry=%s)",
                    reg_url,
                )
            except Exception as e:
                logger.debug(
                    "[A2AAuthenticator] Could not auto-instantiate AgentJwtVerifier: %s", e
                )

        # Start blocklist poller if registry URL is available
        if reg_url:
            _start_blocklist_poller(reg_url, poll_interval)

        # Start EventStore WebSocket listener for sub-1s revocation
        es_ws_url = event_store_ws_url or os.environ.get("EVENT_STORE_WS_URL", "")
        if es_ws_url:
            _start_ws_listener(es_ws_url)

    async def __call__(self, request: StarletteRequest) -> Dict[str, Any]:
        """FastAPI Depends() entry point — fans out across mTLS / JWT / Payment."""
        result: Dict[str, Any] = {
            "verified": False,
            "method": None,
            "agent_did": None,
            "spiffe_id": None,
        }

        # --- Strategy 1: mTLS client certificate (SPIFFE SVID) ---
        spiffe_id = self._try_extract_spiffe_id(request)
        if spiffe_id:
            # CHECK BLOCKLIST FIRST — immediate revocation enforcement
            if spiffe_id in _revoked_spiffe_ids:
                logger.warning(
                    f"[A2AAuthenticator] BLOCKED revoked identity: {spiffe_id}"
                )
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=403,
                    detail=f"Agent identity revoked: {spiffe_id}",
                )

            # Validate trust domain (supports cross-frame federation)
            matched_domain = None
            for td in self.trusted_domains:
                if spiffe_id.startswith(f"spiffe://{td}/agent/"):
                    matched_domain = td
                    break

            if matched_domain:
                agent_did = _did_from_spiffe_id(spiffe_id, matched_domain)
                result = {
                    "verified": True,
                    "method": "mtls",
                    "agent_did": agent_did,
                    "spiffe_id": spiffe_id,
                }
                logger.debug(
                    f"[A2AAuthenticator] mTLS verified: {spiffe_id} → {agent_did}"
                )
                if hasattr(request, "state"):
                    request.state.mtls_auth = result
                return result
            else:
                logger.warning(
                    f"[A2AAuthenticator] SPIFFE ID from untrusted domain: {spiffe_id}"
                )

        # --- Strategy 2: Agent JWT (Authorization: Bearer <jwt>) ---
        # Q-C BL-3 (2026-05-12): the unified third surface, mapped to A2A v1.0
        # HTTPAuthSecurityScheme(scheme="bearer", bearerFormat="JWT").
        if self.agent_jwt_verifier is not None:
            try:
                jwt_result = await self.agent_jwt_verifier(request)
                if jwt_result and jwt_result.get("verified"):
                    result = {
                        "verified": True,
                        "method": "agent_jwt",
                        "agent_did": jwt_result.get("caller_did"),
                        "spiffe_id": None,
                        "jwt_info": {
                            "client_id": jwt_result.get("client_id"),
                            "status": jwt_result.get("status"),
                            "registry": jwt_result.get("registry"),
                        },
                    }
                    logger.debug(
                        "[A2AAuthenticator] Agent JWT verified: did=%s registry=%s",
                        jwt_result.get("caller_did"),
                        jwt_result.get("registry"),
                    )
                    if hasattr(request, "state"):
                        request.state.mtls_auth = result
                    return result
            except Exception as e:
                if self.required:
                    raise
                logger.debug(f"[A2AAuthenticator] Agent JWT verification failed: {e}")

        # --- Strategy 3: Payment token (X-Payment-Token: apt_<hex>) ---
        if self.payment_verifier is not None:
            try:
                payment_result = await self.payment_verifier(request)
                if payment_result and payment_result.get("verified"):
                    result = {
                        "verified": True,
                        "method": "payment",
                        "agent_did": payment_result.get("caller_did"),
                        "spiffe_id": None,
                        "payment_info": payment_result,
                    }
                    if hasattr(request, "state"):
                        request.state.mtls_auth = result
                    return result
            except Exception as e:
                if self.required:
                    raise
                logger.debug(f"[A2AAuthenticator] Payment verification failed: {e}")

        # --- No strategy succeeded ---
        if self.required:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=401,
                detail="Authentication required: provide mTLS client cert, agent JWT (Bearer), or payment token",
            )

        if hasattr(request, "state"):
            request.state.mtls_auth = result
        return result

    def _try_extract_spiffe_id(self, request: Any) -> Optional[str]:
        """Try to extract SPIFFE ID from the request."""
        # Method 1: nginx forwards URL-encoded PEM cert
        cert_header = None
        if hasattr(request, "headers"):
            cert_header = request.headers.get("X-SSL-Client-Cert")
            if not cert_header:
                cert_header = request.headers.get("x-ssl-client-cert")

        if cert_header:
            pem_str = urllib.parse.unquote(cert_header)
            spiffe_id = _extract_spiffe_id_from_pem(pem_str)
            if spiffe_id:
                return spiffe_id

        # Method 2: Direct SPIFFE ID header
        if hasattr(request, "headers"):
            direct_id = request.headers.get("X-SPIFFE-ID")
            if direct_id and any(direct_id.startswith(f"spiffe://{d}/") for d in self.trusted_domains):
                return direct_id

        # Method 3: ASGI TLS scope
        if hasattr(request, "scope"):
            tls_info = request.scope.get("extensions", {}).get("tls")
            if tls_info:
                client_certs = tls_info.get("client_cert_chain", [])
                if client_certs:
                    spiffe_id = _extract_spiffe_id_from_pem(client_certs[0])
                    if spiffe_id:
                        return spiffe_id

        return None

    @staticmethod
    def add_to_blocklist(spiffe_id: str):
        """Manually add a SPIFFE ID to the revocation blocklist.

        Used by EventStore WebSocket listener (future) or manual override.
        """
        _revoked_spiffe_ids.add(spiffe_id)
        logger.info(f"[A2AAuthenticator] Added to blocklist: {spiffe_id}")

    @staticmethod
    def remove_from_blocklist(spiffe_id: str):
        """Remove a SPIFFE ID from the blocklist (re-enrollment)."""
        _revoked_spiffe_ids.discard(spiffe_id)
        logger.info(f"[A2AAuthenticator] Removed from blocklist: {spiffe_id}")

    @staticmethod
    def get_blocklist() -> Set[str]:
        """Return current blocklist (for monitoring/debugging)."""
        return set(_revoked_spiffe_ids)
