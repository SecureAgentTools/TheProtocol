"""EventStore SSL context helper — prod-aligned dual-mode pattern.

Mirrors the canonical pattern from `event_emitter.py:_build_ssl_context()` so
that ANY code path connecting to the EventStore (reactor WS, supply auditor
polling, projection snapshot calls, etc.) gets the right SSL context for
both prod and sandbox without per-call branching.

Trust model: a single context that trusts BOTH the SPIRE bundle
(/certs/bundle.0.pem — internal mTLS targets like nginx-event-store) AND the
public/system CA roots (Let's Encrypt — public targets). One get_httpx_verify()
therefore serves internal EventStore traffic AND public peer fetches (CONSUL's
policy-compliance hits public peer URLs such as https://api.theprotocol.cloud)
without per-target branching. Always presents the SPIRE SVID for client mTLS
when both files exist. (The earlier either/or keyed off EVENT_STORE_URL's
hostname meant a registry with an INTERNAL ES URL got a SPIRE-only store, so
CONSUL's public-peer fetches failed with "unable to get local issuer
certificate" — registry-a, 2026-05-29.)

Self-healing: the SVID material's stamp (svid_stamp: the cert, the key and the bundle) is checked on each call; the
context rebuilds when the SPIRE cert-writer rewrites any of them (every ~5 min).

Prod-safety: prod EVENT_STORE_URL hostnames have dots → behavior IDENTICAL
to today (system CA, optional client cert). The no-dot branch only activates
on internal/sandbox URLs.
"""
from __future__ import annotations

import logging
import os
import ssl
from typing import Optional

logger = logging.getLogger(__name__)

_CACHED_CTX: Optional[ssl.SSLContext] = None
_CACHED_STAMP: tuple = ()


def _build_es_ssl_context() -> Optional[ssl.SSLContext]:
    """Construct an SSL context for EventStore connections.

    Returns None when EVENT_STORE_URL is plain HTTP (no SSL needed) or when
    the URL is unparseable. Otherwise returns a context with:
      - public hostname (dot present)  → system CA store
      - internal hostname (no dot)     → SPIRE bundle CA store
      - client SVID loaded for mTLS    → when /certs/svid.0.{pem,key} exist
    """
    # §XFRAMEMTLS (2026-09-04) — THIS USED TO RETURN None WHENEVER
    # `EVENT_STORE_URL` WAS NOT https/wss, AND THAT GATED FAR MORE THAN THE
    # EVENTSTORE. `get_httpx_verify()` is the verify argument for a dozen-plus
    # callers that never touch the ES — the TEG client, the token bridge, the
    # federation blocklist, operator self-service, balance reconciliation,
    # developers, flare shop, admin agents. On a frame whose ES is reached over
    # INTERNAL plain HTTP (`http://<frame>-event-store:8200`, which is what the
    # frame-test template configures and is perfectly correct for a single-host
    # frame) every one of them silently fell back to the system CA store and
    # could no longer verify a SPIRE-served peer.
    #
    # Measured on the sandbox pair: a cross-registry transfer answered 503
    # "FX pool: reserve read failed: [SSL: CERTIFICATE_VERIFY_FAILED] unable to
    # get local issuer certificate" — the federation's core money rail, dead,
    # because a TLS helper was keyed on ONE caller's URL scheme. Every cloud
    # operator has an https ES URL and therefore never showed it; the defect was
    # invisible until a frame with an internal ES tried to speak mTLS outward.
    #
    # ⚠ ADDITIVE: the context is now built from the SVID MATERIAL, which is what
    # it was always made of. A plain-HTTP ES call passes it to httpx and httpx
    # ignores verify for http, so that caller is unchanged; public HTTPS callers
    # keep the system roots via `load_default_certs` below. Nodes with no
    # `/certs` still get None exactly as before. Live census 2026-09-04: all 7
    # cloud operators already received this context (https ES), registry-a too;
    # only the two sandbox frames changed, and only from broken to working.
    cert_dir = os.getenv("SVID_CERT_DIR", os.getenv("CERT_DIR", "/certs"))
    cert_path = os.path.join(cert_dir, "svid.0.pem")
    key_path = os.path.join(cert_dir, "svid.0.key")
    bundle_path = os.path.join(cert_dir, "bundle.0.pem")

    try:
        # Trust BOTH the SPIRE bundle (internal mTLS: nginx-event-store, no-dot Docker DNS)
        # AND public/system CAs (Let's Encrypt). A single dual-trust context lets callers
        # reuse get_httpx_verify() for internal ES traffic AND public peer fetches — CONSUL's
        # policy-compliance hits public peer URLs (https://api.theprotocol.cloud, etc.). The
        # old either/or, keyed off EVENT_STORE_URL's hostname, gave a registry with an INTERNAL
        # ES URL a SPIRE-only store → CONSUL public-peer fetches failed "unable to get local
        # issuer certificate" (registry-a, 2026-05-29). Mirrors event_emitter._build_ssl_context.
        if os.path.exists(bundle_path):
            ctx = ssl.create_default_context(cafile=bundle_path)   # SPIRE trust anchors
            try:
                ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)    # + public/system roots
            except Exception:
                pass
        else:
            ctx = ssl.create_default_context()                     # system CAs only
        if os.path.exists(cert_path) and os.path.exists(key_path):
            ctx.load_cert_chain(cert_path, key_path)               # client SVID for mTLS
        return ctx
    except Exception as e:
        logger.warning(
            f"[es_ssl_helper] failed to build SSL context (fallback to default): {e}"
        )
        return None


def get_es_ssl_context() -> Optional[ssl.SSLContext]:
    """Cached SSL context with self-healing on SPIRE cert rotation.

    The context rebuilds on the next call whenever the SVID material's stamp moves (svid_stamp: the cert, the key or
    the bundle), and after a build that failed (None while the SVID is on disk), so a read taken while the
    cert-writer was mid-publish lasts one call.
    """
    global _CACHED_CTX, _CACHED_STAMP
    stamp = svid_stamp()
    if not stamp:
        if _CACHED_CTX is None:
            _CACHED_CTX = _build_es_ssl_context()
        return _CACHED_CTX

    if _CACHED_CTX is None or stamp != _CACHED_STAMP:
        _CACHED_CTX = _build_es_ssl_context()
        _CACHED_STAMP = stamp
    return _CACHED_CTX


def get_httpx_verify():
    """Return a value suitable for httpx.AsyncClient(verify=...).

    httpx accepts an ssl.SSLContext OR a bool/path. We return the context
    when one is available, else True (= use httpx's default system CA bundle).
    """
    ctx = get_es_ssl_context()
    if ctx is None:
        return True
    return ctx


def file_stamp(*paths: str) -> tuple:
    """(mtime_ns, size) of each path, in order; () when the FIRST is missing (no SVID: nothing to rotate). A later
    path that is missing counts as (0, -1), so its appearance moves the stamp."""
    out = []
    for i, path in enumerate(paths):
        try:
            st = os.stat(path)
        except OSError:
            if i == 0:
                return ()
            out.append((0, -1))
            continue
        out.append((st.st_mtime_ns, st.st_size))
    return tuple(out)


def svid_stamp() -> tuple:
    """§SVIDRACE (V0639): the identity of the SVID material a cached client was built from: the stamps of svid.0.pem,
    svid.0.key and bundle.0.pem; () when there is no SVID.

    The cert-writer rewrites the three files IN PLACE, one after another, on every refresh (every 5 minutes). A cached
    client keyed on the certificate's mtime alone rebuilt as soon as the certificate was copied, could read the key or
    the bundle mid-copy, and then kept whatever it built until the next refresh: on cloud-op-sbxbetaop 2026-10-24
    17:15:27-17:20:21Z some workers' TEG calls failed CERTIFICATE_VERIFY_FAILED ("unable to get local issuer
    certificate") between two refreshes while a fresh process verified the sidecar against every trust file. Keyed on
    all three files, a read taken mid-publish differs from the finished files, so the next call rebuilds."""
    cert_dir = os.getenv("SVID_CERT_DIR", os.getenv("CERT_DIR", "/certs"))
    return file_stamp(os.path.join(cert_dir, "svid.0.pem"), os.path.join(cert_dir, "svid.0.key"),
                      os.path.join(cert_dir, "bundle.0.pem"))


def spire_trust_loaded(verify, stamp: tuple) -> bool:
    """§SVIDRACE (V0639): may a cached client keep what it was built with? Yes when there is no SVID (stamp ()), or
    when it holds a context built from the SPIRE material. No when the SVID is on disk and the build fell back
    (get_httpx_verify() answered True, get_es_ssl_context() None: the system CAs only, which verify no SPIRE-served
    peer and present no certificate): such a client records no stamp, so the next call rebuilds it."""
    return not stamp or isinstance(verify, ssl.SSLContext)


def svid_mtime() -> float:
    """The modification time of the SVID a client presents (0.0 when there is none). A long-lived client keeps the
    SSLContext it was built with, and a loaded context keeps the certificate it read: a singleton compares this value
    and rebuilds after a rotation (§MTLSHOPS V0378; teg_integration._get_teg_client follows the same pattern)."""
    cert_dir = os.getenv("SVID_CERT_DIR", os.getenv("CERT_DIR", "/certs"))
    try:
        return os.path.getmtime(os.path.join(cert_dir, "svid.0.pem"))
    except OSError:
        return 0.0
