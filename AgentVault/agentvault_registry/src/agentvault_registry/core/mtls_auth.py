"""mTLS Authentication Dependencies for FastAPI

This module provides FastAPI dependencies for extracting and validating
SPIFFE IDs from client certificates in mTLS connections.
"""

import hmac
import logging
import os
import time
from typing import Optional
from fastapi import HTTPException, Request, status, Depends
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.x509.oid import NameOID, ExtensionOID

TRUSTED_SPIFFE_DOMAIN = os.getenv("SPIRE_TRUST_DOMAIN", "agentvault.com")


def get_trusted_spiffe_domains() -> list:
    """Return list of trusted SPIFFE trust domains.

    Reads from TRUSTED_SPIFFE_DOMAINS (comma-separated) first,
    falls back to SPIRE_TRUST_DOMAIN (single domain).
    """
    raw = os.getenv("TRUSTED_SPIFFE_DOMAINS", "")
    if raw:
        return [d.strip() for d in raw.split(",") if d.strip()]
    return [TRUSTED_SPIFFE_DOMAIN]


TRUSTED_SPIFFE_DOMAINS = get_trusted_spiffe_domains()

logger = logging.getLogger(__name__)


# ── §HELLOFRAME (2026-09-18): the trust list follows the ACTIVE frame peer rows, not only the env.
# Measured on a runner-built frame federated with the sandbox through the invitation rail: the approve wrote the peer
# row and the SPIRE relationship on both sides, every mTLS handshake passed, and BOTH registries answered 401
# "Client SPIFFE ID from untrusted domain" to each other, because TRUSTED_SPIFFE_DOMAINS is a static env list that
# only a standup driver ever filled (the sandbox pair's and EU/ASIA's name each other by hand). A stranger's frame
# holds only its own domain, the network's frames do not hold the stranger's, and nobody edits either env at an
# approve, so card mirrors were 0 both ways for as long as the pair existed. The trust domain of every ACTIVE
# `peer_registries` row of type `frame` is now trusted too (an approve inserts or revives such a row, a revoke sets
# it INACTIVE, so a revoke also stops trusting within one refresh), read at most once per PEER_TRUST_TTL_SECONDS.
PEER_TRUST_TTL_SECONDS = float(os.getenv("PEER_TRUST_TTL_SECONDS", "60"))
_PEER_TRUST_DOMAINS: frozenset = frozenset()
_PEER_TRUST_READ_AT: float = 0.0
_PEER_TRUST_LAST_ERROR: str = ""


def domains_from_peer_rows(rows) -> frozenset:
    """The trust domains of ACTIVE frame rows. `rows` are (peer_type, status, trust_domain[, licence_state]) tuples."""
    out = set()
    for row in rows:
        peer_type, status_, td = row[0], row[1], row[2]
        if str(peer_type or "").lower() == "frame" and str(status_ or "").upper() == "ACTIVE":
            td = (td or "").strip().lower().removeprefix("spiffe://").strip("/")
            if td:
                out.add(td)
    return frozenset(out)


def _verdict_rank(v: str) -> int:
    from ..services.federation_licence import PASSING_STATES, REFUSED_STATES
    return 0 if v in REFUSED_STATES else (1 if v in PASSING_STATES else 2)


def licence_states_from_peer_rows(rows) -> dict:
    """§FEDLICENCE: trust domain -> the licence verdict this registry last reached about it. ACTIVE `frame` rows decide
    (other row types only when a trust domain has no frame row), and several rows for one trust domain resolve the
    same way whatever order the query returns them in (agentvault2-41's review): a refused verdict wins, then a passing
    one, then anything else. Rows without the 4th element contribute nothing."""
    by_td: dict = {}
    for row in rows:
        if len(row) < 4 or not row[3]:
            continue
        peer_type, status_, td, lic = row[0], row[1], row[2], row[3]
        if str(status_ or "").upper() != "ACTIVE":
            continue
        td = (td or "").strip().lower().removeprefix("spiffe://").strip("/")
        if td:
            by_td.setdefault(td, {"frame": [], "other": []})[
                "frame" if str(peer_type or "").lower() == "frame" else "other"].append(str(lic))
    out: dict = {}
    for td, groups in by_td.items():
        pool = groups["frame"] or groups["other"]
        out[td] = sorted(pool, key=lambda v: (_verdict_rank(v), v))[0]
    return out


async def _fetch_peer_rows():
    from sqlalchemy import text
    from ..database import get_db_context
    async with get_db_context() as db:
        global _LICENCE_VERDICTS_AVAILABLE
        try:
            res = await db.execute(text("SELECT peer_type, status, trust_domain, licence_state FROM peer_registries "
                                        "WHERE trust_domain IS NOT NULL"))
            _LICENCE_VERDICTS_AVAILABLE = True
        except Exception as exc:
            # ONLY a database without 0182 (the column is missing) falls back, so the trust set still refreshes; any
            # other failure propagates and the caller keeps the last set, as before (agentvault2-41's review: a broad
            # fallback would load no verdicts and let enforce allow everyone, silently)
            if "licence_state" not in str(exc) or ("does not exist" not in str(exc) and "UndefinedColumn" not in type(exc).__name__
                                                   and "UndefinedColumn" not in repr(getattr(exc, "orig", ""))):
                raise
            await db.rollback()
            _LICENCE_VERDICTS_AVAILABLE = False
            logger.warning("[fedlicence] peer_registries has no licence_state column (migration 0182 not applied): "
                           "the trust set refreshes, NO licence verdicts are loaded, enforce refuses nobody")
            res = await db.execute(text("SELECT peer_type, status, trust_domain FROM peer_registries WHERE trust_domain IS NOT NULL"))
        return [tuple(r) for r in res.all()]


async def refresh_peer_trust_domains(*, fetch=_fetch_peer_rows, now=time.monotonic, force: bool = False) -> frozenset:
    """Refresh the peer-row trust domains at most once per TTL. A failed read keeps the last set (and says so once per TTL)."""
    global _PEER_TRUST_DOMAINS, _PEER_TRUST_READ_AT, _PEER_TRUST_LAST_ERROR
    t = now()
    if not force and _PEER_TRUST_READ_AT and (t - _PEER_TRUST_READ_AT) < PEER_TRUST_TTL_SECONDS:
        return _PEER_TRUST_DOMAINS
    _PEER_TRUST_READ_AT = t
    try:
        _rows = await fetch()
        _PEER_TRUST_DOMAINS = domains_from_peer_rows(_rows)
        _LICENCE_STATE_BY_TD.clear()
        _LICENCE_STATE_BY_TD.update(licence_states_from_peer_rows(_rows))
        _PEER_TRUST_LAST_ERROR = ""
    except Exception as exc:  # the last set stands; a registry with no database is not a registry that trusts nobody new
        _PEER_TRUST_LAST_ERROR = f"{type(exc).__name__}: {str(exc)[:160]}"
        logger.warning(f"[mtls-auth] peer trust domains not refreshed, keeping {len(_PEER_TRUST_DOMAINS)}: {_PEER_TRUST_LAST_ERROR}")
    return _PEER_TRUST_DOMAINS


def trusted_spiffe_domains() -> tuple:
    """The env list plus the ACTIVE frame peers' trust domains, as last refreshed."""
    return tuple(TRUSTED_SPIFFE_DOMAINS) + tuple(sorted(_PEER_TRUST_DOMAINS - set(TRUSTED_SPIFFE_DOMAINS)))


def is_trusted_spiffe_id(spiffe_id: str) -> bool:
    if not any(str(spiffe_id or "").startswith(f"spiffe://{d}/") for d in trusted_spiffe_domains()):
        return False
    return licence_allows(spiffe_id)


# ── §FEDLICENCE (2026-09-28): crossing between two trust domains needs a network licence on the other side. This is the
# one check every frame-to-frame call already passes (mTLS here, the internal-secret lane in federation_auth), so it is
# where FEDERATION_LICENCE_MODE acts: `observe` counts and names every crossing whose peer's verdict would be refused
# and refuses nothing, `enforce` refuses those. Inside one trust domain (a frame and its own operators) nothing is
# checked, and `unverified` / not-yet-evaluated peers are NOT refused: a genesis outage must never partition the
# network. The verdicts come from the peer rows (written by the sync worker), refreshed with the trust set.
_LICENCE_STATE_BY_TD: dict = {}
_LICENCE_VERDICTS_AVAILABLE: Optional[bool] = None   # False = the trust refresh could not read verdicts (no 0182)
_LICENCE_WARNED: dict = {}
_LICENCE_WARN_WINDOW = 600.0
try:
    from prometheus_client import Counter as _LicCounter
    FEDERATION_LICENCE_CROSSINGS_TOTAL = _LicCounter(
        "federation_licence_crossings_total",
        "Frame-to-frame crossings seen by the trust check, by the peer's licence verdict and what the mode did",
        labelnames=["verdict", "outcome"],
    )
except Exception:  # pragma: no cover — no metrics library, no counter
    FEDERATION_LICENCE_CROSSINGS_TOTAL = None


def licence_allows(spiffe_id: str) -> bool:
    mode = (os.getenv("FEDERATION_LICENCE_MODE", "off") or "off").strip().lower()
    if mode not in ("observe", "enforce"):
        return True
    m = str(spiffe_id or "")
    td = m[len("spiffe://"):].split("/", 1)[0].strip().lower() if m.startswith("spiffe://") else ""
    local = (os.getenv("SPIRE_TRUST_DOMAIN", "") or "").strip().lower().removeprefix("spiffe://").strip("/")
    if not td or td == local:
        return True
    from ..services.federation_licence import REFUSED_STATES
    verdict = _LICENCE_STATE_BY_TD.get(td) or "unevaluated"
    refused = verdict in REFUSED_STATES
    outcome = ("refused" if mode == "enforce" else "would_refuse") if refused else "allowed"
    if FEDERATION_LICENCE_CROSSINGS_TOTAL is not None:
        try:
            FEDERATION_LICENCE_CROSSINGS_TOTAL.labels(verdict=verdict, outcome=outcome).inc()
        except Exception:  # noqa: BLE001 — a metric never decides a request
            pass
    if refused:
        t = time.monotonic()
        if t - _LICENCE_WARNED.get(td, -1e9) > _LICENCE_WARN_WINDOW:
            _LICENCE_WARNED[td] = t
            logger.warning(f"[fedlicence] {outcome.upper()}: {spiffe_id} (trust domain {td}, licence verdict {verdict}, "
                           f"mode {mode})")
    return not (refused and mode == "enforce")


def licence_verdicts_snapshot() -> dict:
    """§FEDLICENCE (2026-09-28, his word "cross-teg cut off also approved on revoke"): what this registry decided about its
    peers, for its own TEG. The TEG never evaluates a certificate: it copies this and refuses the `refused` trust domains
    while `mode` is enforce, so the one list of refusing states (REFUSED_STATES) stays here. Read the verdicts as last
    refreshed; the route refreshes first (at most once per PEER_TRUST_TTL_SECONDS)."""
    from ..services.federation_licence import REFUSED_STATES
    mode = (os.getenv("FEDERATION_LICENCE_MODE", "off") or "off").strip().lower()
    if mode not in ("observe", "enforce"):
        mode = "off"
    verdicts = dict(sorted(_LICENCE_STATE_BY_TD.items()))
    return {
        "mode": mode,
        "local_trust_domain": (os.getenv("SPIRE_TRUST_DOMAIN", "") or "").strip().lower().removeprefix("spiffe://").strip("/"),
        "verdicts": verdicts,
        "refused": sorted(td for td, v in verdicts.items() if v in REFUSED_STATES),
        "verdicts_available": _LICENCE_VERDICTS_AVAILABLE,
        "refreshed_seconds_ago": (round(time.monotonic() - _PEER_TRUST_READ_AT, 1) if _PEER_TRUST_READ_AT else None),
        "last_error": _PEER_TRUST_LAST_ERROR or None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# findings row 197 — VERIFY A HEADER-SUPPLIED CERTIFICATE, DO NOT JUST PARSE IT.
#
# `get_client_spiffe_id` accepts a certificate out of the X-SSL-Client-Cert HEADER, because a
# reverse proxy that terminated mTLS has no other way to hand it over. Until now it PARSED that
# certificate and trusted the SPIFFE ID inside it — nothing checked that it chained to a CA we
# trust. That made the app's identity decision entirely dependent on every edge in front of it
# pinning the header (row 194: EU, ASIA and all four operators did not, and a self-signed
# certificate in a plain header authenticated from the internet).
#
# The edges are pinned now. This is the half that means a future vhost mistake is no longer an
# authentication bypass: the certificate must verify against the SPIRE trust bundle.
#
# WHAT THIS VALIDATES, and why that is the whole job HERE (measured 2026-09-07): a real SVID on
# this cluster is a SINGLE leaf signed DIRECTLY by a bundle root — no intermediate, path length
# one. `/certs/bundle.0.pem` holds both federated trust domains' self-signed roots, so an ASIA
# leaf verifies against EU's bundle and vice versa. So: the leaf's validity window, an issuer
# that IS one of those roots, that root being a CA and itself in date, and the leaf's signature
# verifying under that root's public key. A deeper chain cannot be built from what nginx forwards
# (it sends the leaf only), so an unmatched issuer is REFUSED rather than guessed at.
#
# ⚠ THE BUNDLE IS RE-READ FROM DISK, NOT SNAPSHOTTED (§BATCH7). A federation approved after boot
# reaches the cert-writer's bundle on its next cycle; a verifier holding a boot-time copy would
# refuse the new peer for up to 30 minutes. Cached on (path, mtime, size) so the common case is
# still cheap.
# ─────────────────────────────────────────────────────────────────────────────

CERT_CHAIN_MODE = (os.getenv("FEDERATION_CERT_CHAIN_MODE", "enforce") or "enforce").strip().lower()

_BUNDLE_CACHE: dict = {"key": None, "roots": []}

try:  # pragma: no cover - import guard, as elsewhere in this codebase
    from prometheus_client import Counter as _Counter

    _CHAIN_REFUSED = _Counter(
        "registry_federation_cert_chain_refused_total",
        "Header-supplied client certificates refused for not chaining to a trusted SPIFFE root",
    )
except Exception:  # pragma: no cover
    _CHAIN_REFUSED = None


def _inc_chain_refused() -> None:
    if _CHAIN_REFUSED is not None:
        try:
            _CHAIN_REFUSED.inc()
        except Exception:  # never let bookkeeping fail an auth decision
            pass


def _bundle_path() -> Optional[str]:
    """The trust bundle to verify against — the SAME rule the outbound client uses.

    Reuses `svid_client._freshest_bundle_path()` (§BATCH7: the SVID stays the boot snapshot's,
    trust follows the freshest file) so there is ONE answer to "which bundle is current" rather
    than two that drift. Falls back to the cert-writer's on-disk path when the singleton is not
    initialised — a fresh process holds an unloaded singleton, which is its own standing gotcha.
    """
    try:
        from ..identity.svid_client import svid_client
        p = svid_client._freshest_bundle_path()
        if p and os.path.exists(p) and os.path.getsize(p) > 0:
            return p
    except Exception:  # noqa: BLE001 - never let trust-path discovery raise into auth
        pass
    cert_dir = os.getenv("SVID_CERT_DIR", os.getenv("CERT_DIR", "/certs"))
    disk = os.path.join(cert_dir, "bundle.0.pem")
    return disk if os.path.exists(disk) and os.path.getsize(disk) > 0 else None


def _load_trust_roots() -> list:
    """Parse the trust bundle into certificates, re-reading when the file changes."""
    path = _bundle_path()
    if not path:
        return []
    try:
        st = os.stat(path)
        key = (path, st.st_mtime, st.st_size)
    except OSError:
        return []
    if _BUNDLE_CACHE.get("key") == key:
        return _BUNDLE_CACHE["roots"]
    roots = []
    try:
        raw = open(path, "rb").read()
        marker = b"-----END CERTIFICATE-----"
        for blk in raw.split(marker):
            if b"BEGIN CERTIFICATE" in blk:
                try:
                    roots.append(x509.load_pem_x509_certificate(blk + marker + b"\n", default_backend()))
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[cert-chain] skipping an unparseable entry in {path}: {e}")
    except OSError as e:
        logger.warning(f"[cert-chain] cannot read trust bundle {path}: {e}")
        return []
    _BUNDLE_CACHE["key"] = key
    _BUNDLE_CACHE["roots"] = roots
    logger.info(f"[cert-chain] trust bundle loaded: {len(roots)} root(s) from {path}")
    return roots


def _signature_verifies(leaf, issuer) -> bool:
    """Does `issuer`'s public key actually sign `leaf`? Covers the key types SPIRE issues."""
    from cryptography.hazmat.primitives.asymmetric import ec, rsa, ed25519, padding
    pub = issuer.public_key()
    try:
        if isinstance(pub, ec.EllipticCurvePublicKey):
            pub.verify(leaf.signature, leaf.tbs_certificate_bytes,
                       ec.ECDSA(leaf.signature_hash_algorithm))
        elif isinstance(pub, rsa.RSAPublicKey):
            pub.verify(leaf.signature, leaf.tbs_certificate_bytes,
                       padding.PKCS1v15(), leaf.signature_hash_algorithm)
        elif isinstance(pub, ed25519.Ed25519PublicKey):
            pub.verify(leaf.signature, leaf.tbs_certificate_bytes)
        else:
            logger.warning(f"[cert-chain] unsupported issuer key type {type(pub).__name__}")
            return False
        return True
    except Exception:  # noqa: BLE001 - an invalid signature raises; that is the answer
        return False


def _is_ca(cert) -> bool:
    try:
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
        return bool(bc.ca)
    except x509.ExtensionNotFound:
        return False
    except Exception:  # noqa: BLE001
        return False


def verify_cert_against_bundle(cert_der: bytes) -> tuple:
    """(ok, reason) — does this certificate chain to a root in our SPIRE trust bundle?

    Returns (True, "") only when the leaf is in date, its issuer is a CA root we hold that is
    itself in date, and the leaf's signature verifies under that root's key.
    """
    import datetime as _dt
    try:
        leaf = x509.load_der_x509_certificate(cert_der, default_backend())
    except Exception as e:  # noqa: BLE001
        return False, f"unparseable certificate ({e.__class__.__name__})"

    now = _dt.datetime.now(_dt.timezone.utc)
    try:
        not_before = leaf.not_valid_before_utc
        not_after = leaf.not_valid_after_utc
    except AttributeError:  # cryptography < 42 exposes naive UTC datetimes
        not_before = leaf.not_valid_before.replace(tzinfo=_dt.timezone.utc)
        not_after = leaf.not_valid_after.replace(tzinfo=_dt.timezone.utc)
    if now < not_before:
        return False, f"certificate not yet valid (notBefore {not_before.isoformat()})"
    if now > not_after:
        return False, f"certificate expired (notAfter {not_after.isoformat()})"

    roots = _load_trust_roots()
    if not roots:
        # NEVER fail OPEN here. A node with no readable bundle cannot verify anything, and
        # "we could not check" must not read as "it was fine" — that is the whole class this
        # change exists to close.
        return False, "no trust bundle available to verify against"

    candidates = [r for r in roots if r.subject == leaf.issuer]
    if not candidates:
        return False, (f"issuer is not a root in our trust bundle "
                       f"({leaf.issuer.rfc4514_string()[:80]})")
    for root in candidates:
        if not _is_ca(root):
            continue
        try:
            r_after = root.not_valid_after_utc
        except AttributeError:
            r_after = root.not_valid_after.replace(tzinfo=_dt.timezone.utc)
        if now > r_after:
            continue
        if _signature_verifies(leaf, root):
            return True, ""
    return False, "signature does not verify against any trusted root"


def extract_spiffe_id_from_cert(cert_der: bytes) -> Optional[str]:
    """Extract SPIFFE ID from X.509 certificate
    
    Args:
        cert_der: DER-encoded certificate bytes
        
    Returns:
        SPIFFE ID string or None if not found
    """
    try:
        # Parse the certificate
        cert = x509.load_der_x509_certificate(cert_der, default_backend())
        
        # Look for SPIFFE ID in Subject Alternative Names
        try:
            san_ext = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
            for san in san_ext.value:
                if isinstance(san, x509.UniformResourceIdentifier):
                    uri = san.value
                    if uri.startswith("spiffe://"):
                        logger.debug(f"Found SPIFFE ID in SAN: {uri}")
                        return uri
        except x509.ExtensionNotFound:
            pass
        
        # Fallback: Look for SPIFFE ID in Subject CN (less standard but sometimes used)
        for attribute in cert.subject:
            if attribute.oid == NameOID.COMMON_NAME:
                cn = attribute.value
                if cn.startswith("spiffe://"):
                    logger.debug(f"Found SPIFFE ID in CN: {cn}")
                    return cn
        
        logger.warning("No SPIFFE ID found in certificate")
        return None
        
    except Exception as e:
        logger.error(f"Error extracting SPIFFE ID from certificate: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# §MTLSHOPS G2 (2026-09-15) — THE TERMINATOR VOUCHES FOR THE CERTIFICATE HEADERS.
#
# Row 197 made a header-supplied certificate CHAIN to our trust bundle, which proves the certificate is genuine. Whether the
# request came through this frame's own TLS terminator is a second question, answered by a marker: the headers count only
# beside X-Registry-Proxy-Auth equal to REGISTRY_PROXY_TRUST_SECRET, which only this frame's terminators set
# (nginx-federation, and the frame's own registry gateway), and only with the verdict SUCCESS. Without a usable secret (32+
# characters) the header path is OFF: a caller presenting a certificate is refused, never believed. The event store's rule
# (§SOVKIT T2) and the TEG's (G1). A reader asks forwarded_client_cert; a presence check (the admin path throttle's
# exemption, the admission lane) asks forwarded_cert_vouched.
# ─────────────────────────────────────────────────────────────────────────────

PROXY_MARKER_HEADER = "X-Registry-Proxy-Auth"
_MIN_PROXY_SECRET_LEN = 32
_UNVOUCHED = {"count": 0, "last": 0.0}

try:  # pragma: no cover - import guard, as above
    from prometheus_client import Counter as _UCounter

    _UNVOUCHED_TOTAL = _UCounter(
        "registry_forwarded_cert_unvouched_total",
        "Forwarded client certificates ignored because this frame's terminator did not vouch for them (marker and SUCCESS)",
    )
except Exception:  # pragma: no cover
    _UNVOUCHED_TOTAL = None


def proxy_secret_usable(value: Optional[str]) -> bool:
    """A marker secret counts only when it is long enough to be one; a short or trivial value counts as unset."""
    v = (value or "").strip()
    return len(v) >= _MIN_PROXY_SECRET_LEN and len(set(v)) > 4


def method1_proxy_trust() -> bool:
    """True when the header path is on: this registry holds a usable REGISTRY_PROXY_TRUST_SECRET."""
    return proxy_secret_usable(os.getenv("REGISTRY_PROXY_TRUST_SECRET"))


def forwarded_cert_vouched(headers) -> bool:
    """True only when the request carries a forwarded certificate AND this frame's own terminator vouched for it:
    X-Registry-Proxy-Auth equals a usable REGISTRY_PROXY_TRUST_SECRET (constant time) and nginx's verdict is SUCCESS.
    No side effects, so a presence check may ask it on every request."""
    if not headers.get("X-SSL-Client-Cert"):
        return False
    configured = (os.getenv("REGISTRY_PROXY_TRUST_SECRET") or "").strip()
    if not proxy_secret_usable(configured):
        return False
    presented = headers.get(PROXY_MARKER_HEADER)
    if not presented or not hmac.compare_digest(str(presented).encode(), configured.encode()):
        return False
    return (headers.get("X-SSL-Client-Verify") or "").strip() == "SUCCESS"


OPERATOR_LANE_REFUSAL = ("the operator lane is served only through this frame's mTLS federation terminator: a cloud operator "
                         "reaches it at its parent frame's federation address, presenting its SVID")


async def require_vouched_peer_cert(request: Request) -> None:
    """§OPLANE (V0614): the federation-lane aliases of an operator's licence-carrying calls (self-logs, self-restart, the
    IRONHAND proxy) answer only a request this frame's own terminator vouched for. On a public host a licence alone never
    reaches them; the licence stays the route's own check, the certificate is the second factor."""
    if not forwarded_cert_vouched(request.headers):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=OPERATOR_LANE_REFUSAL)


def forwarded_client_cert(headers) -> Optional[str]:
    """The URL-escaped certificate nginx forwarded, only when forwarded_cert_vouched; otherwise None, counted and
    (throttled) logged. The registry's ONE reader of X-SSL-Client-Cert."""
    value = headers.get("X-SSL-Client-Cert")
    if not value:
        return None
    if forwarded_cert_vouched(headers):
        return value
    if _UNVOUCHED_TOTAL is not None:
        try:
            _UNVOUCHED_TOTAL.inc()
        except Exception:  # never let bookkeeping fail an auth decision
            pass
    _UNVOUCHED["count"] += 1
    now = time.monotonic()
    if now - _UNVOUCHED["last"] >= 60.0:
        logger.warning(
            "[mTLS] ignored X-SSL-Client-Cert without this frame's terminator marker and SUCCESS "
            "(%d since the last line; header path %s)",
            _UNVOUCHED["count"], "on" if method1_proxy_trust() else "OFF: REGISTRY_PROXY_TRUST_SECRET unset",
        )
        _UNVOUCHED["count"] = 0
        _UNVOUCHED["last"] = now
    return None


async def get_client_spiffe_id(request: Request) -> str:
    """FastAPI dependency to extract and validate client SPIFFE ID from mTLS connection
    
    Args:
        request: FastAPI request object
        
    Returns:
        Validated SPIFFE ID string
        
    Raises:
        HTTPException: If no valid client certificate or SPIFFE ID found
    """
    # Check if the request has client certificate info
    # This depends on how the ASGI server passes the client cert
    # Common patterns:
    # - Uvicorn with --ssl-cert-reqs: request.headers.get("X-SSL-Client-Cert")
    # - Direct TLS termination: request.scope.get("extensions", {}).get("tls", {})
    
    # Try to get client certificate from various possible locations
    client_cert_pem = None
    client_cert_der = None
    
    # Method 1: Check request extensions (Uvicorn with proper TLS)
    tls_info = request.scope.get("extensions", {}).get("tls", {})
    if tls_info and "client_cert_chain" in tls_info:
        # Get the first certificate in the chain (the client's certificate)
        client_cert_chain = tls_info.get("client_cert_chain", [])
        if client_cert_chain:
            client_cert_der = client_cert_chain[0]
    
    # Method 2: Check for X-SSL headers (reverse proxy setup)
    # ⚠ findings row 197 — THIS IS THE ONLY PATH WHERE THE CERTIFICATE IS HEARSAY. Methods 1 and 3
    # come from a TLS handshake this process took part in, so the certificate was verified by the
    # server that terminated it. A header is a claim, and `from_header` is what tells the check
    # below which of the two it is holding.
    from_header = False
    if not client_cert_der:
        client_cert_header = forwarded_client_cert(request.headers)
        if client_cert_header:
            from_header = True
            # The header usually contains URL-encoded PEM certificate
            import urllib.parse
            client_cert_pem = urllib.parse.unquote(client_cert_header)
            # Convert PEM to DER
            from cryptography.hazmat.primitives import serialization
            try:
                cert = x509.load_pem_x509_certificate(client_cert_pem.encode(), default_backend())
                client_cert_der = cert.public_bytes(serialization.Encoding.DER)
            except Exception as e:
                logger.error(f"Failed to parse client certificate from header: {e}")
    
    # Method 3: Check transport info (some ASGI servers)
    if not client_cert_der:
        transport = request.scope.get("transport", {})
        if "peercert_bin" in transport:
            client_cert_der = transport["peercert_bin"]
    
    if not client_cert_der:
        logger.warning("No client certificate found in request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client certificate required for mTLS authentication"
        )
    
    # findings row 197 — a header-supplied certificate must CHAIN to our trust bundle before any
    # identity is read out of it. `off` disables the check, `shadow` logs what it would have
    # refused (for a roll that wants to watch real traffic first), `enforce` is the default and
    # refuses. Certificates from a real handshake skip this: they were already verified.
    if from_header and CERT_CHAIN_MODE != "off":
        ok, why = verify_cert_against_bundle(client_cert_der)
        if not ok:
            if CERT_CHAIN_MODE == "shadow":
                logger.warning(
                    f"[cert-chain][SHADOW] would refuse a header-supplied certificate: {why}"
                )
            else:
                logger.warning(f"[cert-chain] refusing a header-supplied certificate: {why}")
                _inc_chain_refused()
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Client certificate does not chain to a trusted SPIFFE root",
                )
        elif CERT_CHAIN_MODE == "shadow":
            logger.debug("[cert-chain][SHADOW] header-supplied certificate verified")

    # Extract SPIFFE ID from certificate
    spiffe_id = extract_spiffe_id_from_cert(client_cert_der)
    
    if not spiffe_id:
        logger.warning("No SPIFFE ID found in client certificate")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid SPIFFE ID required in client certificate"
        )
    
    # Validate SPIFFE ID format and trust domain (supports cross-frame federation): the env list plus every ACTIVE
    # frame peer row (§HELLOFRAME: an approve is what makes a peer trusted, a revoke what makes it untrusted)
    await refresh_peer_trust_domains()
    if not is_trusted_spiffe_id(spiffe_id):
        logger.warning(f"Client SPIFFE ID from untrusted domain: {spiffe_id} (trusted: {', '.join(trusted_spiffe_domains())})")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client certificate from untrusted SPIFFE domain"
        )
    
    logger.info(f"Authenticated client with SPIFFE ID: {spiffe_id}")
    return spiffe_id


async def require_central_registry_health_checker(spiffe_id: str = Depends(get_client_spiffe_id)) -> str:
    """FastAPI dependency to require specific SPIFFE ID for health check access
    
    Args:
        spiffe_id: Client SPIFFE ID from mTLS authentication
        
    Returns:
        Validated SPIFFE ID
        
    Raises:
        HTTPException: If SPIFFE ID is not authorized for health checks
    """
    # Check if the SPIFFE ID is authorized for health checks
    # Accept both generic central registry ID and specific health checker ID
    allowed_ids = []
    for domain in TRUSTED_SPIFFE_DOMAINS:
        allowed_ids.append(f"spiffe://{domain}/service/central-registry")
        allowed_ids.append(f"spiffe://{domain}/service/central-registry-health-checker")
    
    if spiffe_id not in allowed_ids:
        logger.warning(f"Unauthorized SPIFFE ID for health check: {spiffe_id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client not authorized for health check access"
        )
    
    return spiffe_id


if method1_proxy_trust():
    logger.info("[mTLS] header path on: X-SSL-Client-* counts only with X-Registry-Proxy-Auth from this frame's terminators and SUCCESS")
else:
    logger.warning(
        "[mTLS] header path OFF: REGISTRY_PROXY_TRUST_SECRET is unset or shorter than 32 characters, so a caller presenting "
        "a certificate through nginx-federation is refused until it is set and the terminators send X-Registry-Proxy-Auth"
    )
