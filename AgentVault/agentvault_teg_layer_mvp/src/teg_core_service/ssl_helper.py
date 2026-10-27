"""TEG-side SSL helper for outbound HTTPS to the local Registry — dual-mode pattern.

Mirrors the canonical pattern from `agentvault_registry/es_ssl_helper.py` and
`event_emitter.py:_build_ssl_context()` so that ANY TEG → Registry code path
(home-frame callbacks today, future internal RPCs) gets the right SSL context
for both prod and sandbox without per-call branching.

Heuristic: dot in REGISTRY_URL hostname → public domain (e.g.,
api.theprotocol.cloud) → system CA bundle. No dot → internal Docker DNS
(e.g., registry-a, frame-b-registry) → SPIRE bundle from /certs/bundle.0.pem.
Always presents SPIRE SVID for client mTLS when both files exist.

Self-healing: cert mtime is checked on each call; rebuilds context when the
SPIRE cert-writer rotates the SVID (every ~1h).

Prod-safety: today's REGISTRY_URL on prod is `http://registry-a:8000` →
verify= is effectively unused (httpx doesn't TLS-verify plain http). The HTTPS
branches only activate if a future pass flips Registry behind an mTLS sidecar.
This file ships dormant; the wrap exists so the flip is a one-line env change.

§pass69.1 (2026-05-24): T1.2c — closes the mTLS loop opened by §pass69 T1.2
on the Registry → TEG direction.
"""
from __future__ import annotations

import logging
import os
import ssl
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_CACHED_CTX: Optional[ssl.SSLContext] = None
_CACHED_CERT_MTIME: float = 0.0


def _build_registry_ssl_context() -> Optional[ssl.SSLContext]:
    """Construct an SSL context for outbound TEG → Registry connections.

    Returns None when REGISTRY_URL is plain HTTP (no SSL needed) or when
    the URL is unparseable. Otherwise returns a context with:
      - public hostname (dot present)  → system CA store
      - internal hostname (no dot)     → SPIRE bundle CA store
      - client SVID loaded for mTLS    → when /certs/svid.0.{pem,key} exist
    """
    reg_url = os.getenv("REGISTRY_URL", "")
    if not reg_url:
        return None
    parsed = urlparse(reg_url)
    if parsed.scheme not in ("https", "wss"):
        return None

    cert_dir = os.getenv("SVID_CERT_DIR", os.getenv("CERT_DIR", "/certs"))
    cert_path = os.path.join(cert_dir, "svid.0.pem")
    key_path = os.path.join(cert_dir, "svid.0.key")
    bundle_path = os.path.join(cert_dir, "bundle.0.pem")

    hostname = parsed.hostname or ""
    uses_public_ca = "." in hostname

    try:
        if uses_public_ca:
            ctx = ssl.create_default_context()
        else:
            if not os.path.exists(bundle_path):
                return ssl.create_default_context()
            ctx = ssl.create_default_context(cafile=bundle_path)
        if os.path.exists(cert_path) and os.path.exists(key_path):
            ctx.load_cert_chain(cert_path, key_path)
        return ctx
    except Exception as e:
        logger.warning(
            f"[ssl_helper] failed to build SSL context (fallback to default): {e}"
        )
        return None


def get_registry_ssl_context() -> Optional[ssl.SSLContext]:
    """Cached SSL context with self-healing on SPIRE cert rotation.

    Same mtime-based refresh as event_emitter.py — when cert-writer rotates
    the SVID, mtime changes and the context rebuilds on the next call.
    """
    global _CACHED_CTX, _CACHED_CERT_MTIME
    cert_dir = os.getenv("SVID_CERT_DIR", os.getenv("CERT_DIR", "/certs"))
    cert_path = os.path.join(cert_dir, "svid.0.pem")

    if not os.path.exists(cert_path):
        if _CACHED_CTX is None:
            _CACHED_CTX = _build_registry_ssl_context()
        return _CACHED_CTX

    try:
        current_mtime = os.path.getmtime(cert_path)
    except OSError:
        return _CACHED_CTX

    if _CACHED_CTX is None or current_mtime != _CACHED_CERT_MTIME:
        _CACHED_CTX = _build_registry_ssl_context()
        _CACHED_CERT_MTIME = current_mtime
    return _CACHED_CTX


def get_httpx_verify():
    """Return a value suitable for httpx.AsyncClient(verify=...).

    httpx accepts an ssl.SSLContext OR a bool/path. We return the context
    when one is available, else True (= use httpx's default system CA bundle).
    """
    ctx = get_registry_ssl_context()
    if ctx is None:
        return True
    return ctx


def client_cert_verify(verify, cert):
    """What to pass as httpx `verify=` beside a client `cert` (§DEPS, 2026-09-27).

    httpx 0.28 returns the context it builds from a CA PATH before it reaches the client-certificate step, so `cert=`
    beside a path is silently dropped and the TEG dials a peer that requires a client certificate with none. A CA path
    with a certificate becomes one SSLContext holding both (the context httpx 0.28 builds from the path, plus the
    chain); any other combination is returned unchanged, because httpx still loads the certificate beside True, False
    or an SSLContext. The same rule as the registry's core/tls_client.py.
    """
    if not cert or not isinstance(verify, str):
        return verify
    ctx = ssl.create_default_context(capath=verify) if os.path.isdir(verify) else ssl.create_default_context(cafile=verify)
    if isinstance(cert, (tuple, list)):
        ctx.load_cert_chain(*cert)
    else:
        ctx.load_cert_chain(cert)
    return ctx
