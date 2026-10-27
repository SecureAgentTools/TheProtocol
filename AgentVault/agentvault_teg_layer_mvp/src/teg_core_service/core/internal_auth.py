"""Unified internal-caller authentication for the TEG — §2026-06-16 TEG-mTLS migration, Phase 1.

ONE place that authenticates internal/admin callers (registry->TEG admin routes + the legacy
shared-key callers) with **mTLS SPIFFE as the PRIMARY** mechanism and the shared admin key as a
**GATED fallback**. Mirrors the EventStore's EVENTSTORE_MTLS_REQUIRED model.

  Mode 1 (mTLS): SPIFFE id from the X-SSL-Client-Cert header injected by the nginx-teg sidecar;
    accepted if its trust domain is in TRUSTED_SPIFFE_DOMAINS AND its path is an internal service
    class — see is_internal_service_identity() (§MONEY-R51: path-anchored, ONE copy).
  Mode 2 (shared key): the admin api key (constant-time compare). ONLY honored while
    TEG_MTLS_REQUIRED is false (shadow). Every Mode-2 acceptance logs a [TEG-AUTH-SHADOW] line —
    that telemetry is the gate for the Phase-2 enforce flip (key-fallback must reach 0 for real
    callers before flipping).

Flip TEG_MTLS_REQUIRED=true -> Mode 2 disabled (enforce). Sub-30s rollback: unset + recreate TEG.
This module is additive + non-breaking while TEG_MTLS_REQUIRED is false: everything that
authenticated by key before still does (and is logged); mTLS is now ALSO accepted (preferred).
"""
import hmac
import logging
import os
import time
import urllib.parse
from typing import Optional, Tuple

from cryptography import x509
from cryptography.x509.oid import ExtensionOID
from fastapi import HTTPException, Request, status

from .config import get_settings

logger = logging.getLogger(__name__)

# §MONEY-R51 (2026-09-04, his word "widen the rule") — WHICH trusted SPIFFE identities are internal
# callers. The old rule was three SUBSTRINGS ("/service/registry-", "/service/teg-", "/operator/"),
# written for prod's naming (registry-a, teg-a, teg-core-a) and copied into FIVE files. A frame the
# frame provisioner stands up names its registry `/service/registry` and its svid-writer identity
# `/service/<name>-registry`, so the moment TEG_MTLS_REQUIRED=true its own registry was refused by
# its own TEG and by every peer's cross-TEG router — no operator could ever be treasury-seeded
# (agentvault2-07's B8, measured on the sandbox frames, masked there only while TEG_MTLS_REQUIRED is
# unset). TRUST is not decided here: nginx-teg's client verification against the SPIRE bundle and
# TRUSTED_SPIFFE_DOMAINS (extract_spiffe_from_request) decide WHO may present a certificate; this
# predicate decides which ROLE a trusted identity plays. Path-ANCHORED on the segment after
# `/service/` — never a substring anywhere in the id — and it is the only copy: every site calls it.
_SERVICE_PREFIXES = ("teg-", "registry-")


def is_internal_service_identity(spiffe_id: Optional[str]) -> bool:
    """True iff `spiffe_id` names an internal service caller: `/service/teg-*`, `/service/registry-*`,
    the bare `/service/registry`, `/service/<name>-registry` (a provisioned frame's svid-writer
    identity) or `/operator/<op>/…`. Agents, the SPIRE agent, the event store and anything not
    under `/service/` or `/operator/` are not."""
    if not spiffe_id or not spiffe_id.startswith("spiffe://"):
        return False
    trust_domain, _, path = spiffe_id[len("spiffe://"):].partition("/")
    if not trust_domain or not path:
        return False
    segments = path.split("/")
    if len(segments) < 2 or not segments[1]:
        return False
    kind, name = segments[0], segments[1]
    if kind == "operator":
        return True
    if kind != "service":
        return False
    if name.startswith(_SERVICE_PREFIXES) or name == "registry":
        return True
    return name.endswith("-registry") and len(name) > len("-registry")


def _trusted_domains() -> list:
    raw = os.environ.get("TRUSTED_SPIFFE_DOMAINS") or os.environ.get(
        "SPIRE_TRUST_DOMAIN", "agentvault.com"
    )
    return [d.strip() for d in raw.split(",") if d.strip()]


def teg_mtls_required() -> bool:
    return os.environ.get("TEG_MTLS_REQUIRED", "false").strip().lower() in ("1", "true", "yes", "on")


# §SECFIX-3 (2026-09-25) — WHO may credit this TEG's treasury over /cross-teg/treasury-fund. The route credits the local
# treasury with the amount the caller states, and it accepted any internal-service identity of ANY trusted domain: a
# federated peer frame's registry or TEG could credit this frame's treasury (the architecture audit of 2026-09-25).
# Treasury-to-treasury funding flows from a frame to its own operators, and an operator shares its frame's trust domain,
# so the default is this TEG's own domain. CROSS_TEG_TREASURY_FUND_SOURCES widens it: a comma list of trust domains or
# exact SPIFFE ids (a fiat-genesis frame that routes funding to another frame names that frame here, on the receiver).
def treasury_fund_sources() -> list:
    raw = os.environ.get("CROSS_TEG_TREASURY_FUND_SOURCES")
    if raw is not None and raw.strip():
        return [s.strip() for s in raw.split(",") if s.strip()]
    own = (os.environ.get("SPIRE_TRUST_DOMAIN") or "").strip()
    return [own] if own else []


def treasury_fund_source_ok(spiffe_id: Optional[str]) -> bool:
    """True iff `spiffe_id` may credit this treasury: its trust domain, or the exact id, is a configured source. A caller
    that authenticated with the shared key has no identity and is never a source."""
    if not spiffe_id or not spiffe_id.startswith("spiffe://"):
        return False
    domain = spiffe_id[len("spiffe://"):].split("/", 1)[0]
    for src in treasury_fund_sources():
        if src.startswith("spiffe://"):
            if spiffe_id == src:
                return True
        elif domain == src:
            return True
    return False


def trust_domain_of(spiffe_id: Optional[str]) -> Optional[str]:
    if not spiffe_id or not spiffe_id.startswith("spiffe://"):
        return None
    return spiffe_id[len("spiffe://"):].split("/", 1)[0] or None


# §SECFIX-11 (2026-09-25) — WHO may call the cross-TEG legs that are LOCAL by design. The async legs (lock-async,
# credit-async, credit-async-bulk, refund-async, reverse-async) are called by this TEG's own frame: the sender's registry
# locks on its own TEG, the receiver's registry credits its own TEG after the replicated event, the saga refunds on its
# own. The one-shot /accept has no production caller. They accepted any internal-service identity of ANY trusted domain,
# and the frame's nginx-federation forwards the whole /api/v1/cross-teg/ prefix, so a federated peer frame's registry or
# TEG could debit or credit any agent here (measured 2026-09-25 on the sandbox pair: a peer's certificate passed the auth
# of all five async legs and /accept; nothing moved, the probe's empty body failed validation). Measured the same day:
# no peer called any of them (operators share their frame's domain). Default: this TEG's own trust domain;
# CROSS_TEG_LOCAL_LEG_SOURCES widens it (trust domains or exact SPIFFE ids). A shared key names no identity and is never
# a local caller (under TEG_MTLS_REQUIRED, set on every running TEG, it never reaches this rule at all).
def local_leg_sources() -> list:
    raw = os.environ.get("CROSS_TEG_LOCAL_LEG_SOURCES")
    if raw is not None and raw.strip():
        return [s.strip() for s in raw.split(",") if s.strip()]
    own = (os.environ.get("SPIRE_TRUST_DOMAIN") or "").strip()
    return [own] if own else []


def local_leg_caller_ok(caller: Optional[str]) -> bool:
    """True iff `caller` (what the cross-TEG auth returned: a SPIFFE id, or the label "shared-key") may call a local leg."""
    domain = trust_domain_of(caller)
    if not domain:
        return False
    for src in local_leg_sources():
        if src.startswith("spiffe://"):
            if caller == src:
                return True
        elif domain == src:
            return True
    return False


# §TEGSCOPE (2026-10-07, his word "2. yes fix"; sessionlogs2026/FINDINGS_2026-10-02_TEG_ADMIN_SCOPE.md) — the admin ROLE
# follows the caller's RELATION to this TEG, not only its identity class. is_internal_service_identity() names which
# identities are internal callers; it never asked WHOSE: a peer frame's registry (any trusted domain) was an admin on every
# admin route here (treasury transfer and receive, fee-collector distribute, burns, suspensions), measured 200 on the
# sandbox pair for treasury/info and fee-collector/info. Its designed use is the FX pool: GET fx/reserve and POST fx/move
# (the cross-TEG 2PC is a separate router with its own checks). Measured 2026-10-07 on every production and sandbox TEG
# (the [TEG-AUTH] lines since their start, 9-17 h): a frame TEG's admin callers were its own frame's /service/ identities
# and the peer frame's registry on exactly those two routes; an operator TEG's were its own /operator/<op>/ identities
# only; no operator called its frame's admin routes and no frame its operators'.
# THIS TEG's own identity is the URI in its own SVID (SVID_CERT_DIR/svid.0.pem): spiffe://<td>/service/teg-layer for a frame,
# spiffe://<td>/operator/<op>/svid-writer for an operator (TEG_OWN_SPIFFE_ID names it explicitly). Relations:
#   own         : the same trust domain and the same owner (the frame's /service/ ids; an operator's /operator/<op>/ ids)
#   peer        : another trusted domain                   -> TEG_PEER_ADMIN_ROUTES (default the two FX routes)
#   local-other : the same domain, another owner           -> TEG_LOCAL_OTHER_ADMIN_ROUTES (default none)
# Route lists are comma-separated "METHOD /path" (exact path, no query). TEG_ADMIN_SCOPE_MODE: enforce (default; the
# §SECFIX-11 precedent of this module: tighten by default, an env widens) | shadow (log WOULD-DENY, allow) | off.
_PEER_ADMIN_ROUTES_DEFAULT = "GET /api/v1/admin/fx/reserve,POST /api/v1/admin/fx/move"
_OWN_ID = {"value": None, "read_at": 0.0, "error": ""}


def admin_scope_mode() -> str:
    mode = (os.environ.get("TEG_ADMIN_SCOPE_MODE") or "enforce").strip().lower()
    return mode if mode in ("enforce", "shadow", "off") else "enforce"


def _routes(env_name: str, default: str) -> frozenset:
    raw = os.environ.get(env_name)
    raw = default if raw is None else raw
    out = set()
    for item in raw.split(","):
        method, _, path = item.strip().partition(" ")
        if method and path.strip():
            out.add((method.upper(), path.strip().rstrip("/") or "/"))
    return frozenset(out)


def peer_admin_routes() -> frozenset:
    return _routes("TEG_PEER_ADMIN_ROUTES", _PEER_ADMIN_ROUTES_DEFAULT)


def local_other_admin_routes() -> frozenset:
    return _routes("TEG_LOCAL_OTHER_ADMIN_ROUTES", "")


def own_spiffe_id() -> Optional[str]:
    """This TEG's own SPIFFE id: TEG_OWN_SPIFFE_ID, else the URI SAN of SVID_CERT_DIR/svid.0.pem (read once, re-read every
    60 s while unknown). The id never changes across rotations; only the certificate does."""
    explicit = (os.environ.get("TEG_OWN_SPIFFE_ID") or "").strip()
    if explicit:
        return explicit
    if _OWN_ID["value"] or time.time() - _OWN_ID["read_at"] < 60:
        return _OWN_ID["value"]
    _OWN_ID["read_at"] = time.time()
    path = os.path.join(os.getenv("SVID_CERT_DIR", "/certs"), "svid.0.pem")
    try:
        with open(path, "rb") as fh:
            cert = x509.load_pem_x509_certificate(fh.read())
        san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        for entry in san.value:
            if isinstance(entry, x509.UniformResourceIdentifier) and entry.value.startswith("spiffe://"):
                _OWN_ID["value"], _OWN_ID["error"] = entry.value, ""
                logger.info(f"[TEG-AUTH-SCOPE] this TEG is {entry.value} (from {path}); admin scope mode={admin_scope_mode()}")
                return entry.value
        _OWN_ID["error"] = f"{path} carries no spiffe URI"
    except Exception as exc:  # noqa: BLE001
        _OWN_ID["error"] = f"{path}: {type(exc).__name__}: {str(exc)[:120]}"
    logger.error(f"[TEG-AUTH-SCOPE] this TEG's own identity is UNKNOWN ({_OWN_ID['error']}): the admin scope cannot be "
                 f"applied and every internal identity keeps the full admin role until it is known")
    return None


def _owner(spiffe_id: Optional[str]) -> Optional[Tuple[str, str]]:
    """(trust domain, owner prefix): ("eu.theprotocol.cloud", "service/") or (td, "operator/<op>/"); None otherwise."""
    if not spiffe_id or not spiffe_id.startswith("spiffe://"):
        return None
    td, _, path = spiffe_id[len("spiffe://"):].partition("/")
    segs = path.split("/")
    if not td or not segs or not segs[0]:
        return None
    if segs[0] == "operator" and len(segs) >= 2 and segs[1]:
        return td, f"operator/{segs[1]}/"
    if segs[0] == "service":
        return td, "service/"
    return None


def caller_relation(caller: Optional[str], own: Optional[str]) -> str:
    """'own' | 'peer' | 'local-other' | 'unknown' (this TEG's own identity, or the caller's, cannot be read)."""
    mine, theirs = _owner(own), _owner(caller)
    if not mine or not theirs:
        return "unknown"
    if theirs[0] != mine[0]:
        return "peer"
    return "own" if theirs[1] == mine[1] else "local-other"


def admin_scope_allows(relation: str, method: str, path: str) -> bool:
    if relation in ("own", "unknown"):
        return True
    key = ((method or "").upper(), (path or "").rstrip("/") or "/")
    if relation == "peer":
        return key in peer_admin_routes()
    return key in local_other_admin_routes()


# §MTLSHOPS G1 (2026-09-15) — THE TERMINATOR VOUCHES FOR THE CERTIFICATE HEADERS. nginx terminates mTLS and forwards its
# verdict (X-SSL-Client-Verify) and the certificate (X-SSL-Client-Cert). Headers are only as trustworthy as their sender, so
# these count only beside X-TEG-Proxy-Auth equal to TEG_PROXY_TRUST_SECRET, which only this frame's TLS terminators set
# (nginx-teg, and nginx-federation's /api/v1/cross-teg/), and only with the verdict SUCCESS. Without a usable secret (32+
# characters) the header path is OFF: a caller presenting a certificate is refused, never believed, and /health says so.
# The event store's rule (§SOVKIT T2), one copy for the TEG.
PROXY_MARKER_HEADER = "X-TEG-Proxy-Auth"
_MIN_PROXY_SECRET_LEN = 32
_UNVOUCHED = {"count": 0, "last": 0.0}


def proxy_secret_usable(value: Optional[str]) -> bool:
    """A marker secret counts only when it is long enough to be one; a short or trivial value counts as unset."""
    v = (value or "").strip()
    return len(v) >= _MIN_PROXY_SECRET_LEN and len(set(v)) > 4


def method1_proxy_trust() -> bool:
    """True when the header path is on: this TEG holds a usable TEG_PROXY_TRUST_SECRET."""
    return proxy_secret_usable(os.environ.get("TEG_PROXY_TRUST_SECRET"))


def proxy_vouched(headers) -> bool:
    """True only when this frame's own terminator vouched for the forwarded certificate: X-TEG-Proxy-Auth equals a usable
    TEG_PROXY_TRUST_SECRET (constant time) and nginx's verdict is SUCCESS."""
    configured = (os.environ.get("TEG_PROXY_TRUST_SECRET") or "").strip()
    if not proxy_secret_usable(configured):
        return False
    presented = headers.get(PROXY_MARKER_HEADER)
    if not presented or not hmac.compare_digest(str(presented).encode(), configured.encode()):
        return False
    return (headers.get("X-SSL-Client-Verify") or "").strip() == "SUCCESS"


def _note_unvouched() -> None:
    _UNVOUCHED["count"] += 1
    now = time.monotonic()
    if now - _UNVOUCHED["last"] >= 60.0:
        logger.warning(
            "[TEG-AUTH] ignored X-SSL-Client-Cert without this frame's terminator marker and SUCCESS "
            "(%d since the last line; header path %s)",
            _UNVOUCHED["count"], "on" if method1_proxy_trust() else "OFF: TEG_PROXY_TRUST_SECRET unset",
        )
        _UNVOUCHED["count"] = 0
        _UNVOUCHED["last"] = now


def extract_spiffe_from_request(request: Request) -> Optional[str]:
    """SPIFFE URI from the X-SSL-Client-Cert this frame's terminator forwarded, iff it vouched for it (proxy_vouched: the
    marker and SUCCESS), the URI's trust domain is trusted, and (§FEDLICENCE) that domain's network licence is not
    refused by this frame's registry while enforcing (core/licence_gate). The TEG's ONE reader of that header.

    A licence refusal returns None like any identity this TEG does not accept, never an exception: some callers wrap this
    reader in a broad except and would read an exception as "no answer" and fall through to the shared key. The reason
    is left on request.state.fedlicence_refused so the refusal can name it."""
    cert_header = request.headers.get("X-SSL-Client-Cert")
    if not cert_header:
        return None
    if not proxy_vouched(request.headers):
        _note_unvouched()
        return None
    try:
        cert = x509.load_pem_x509_certificate(urllib.parse.unquote(cert_header).encode())
        san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        domains = _trusted_domains()
        for entry in san.value:
            if isinstance(entry, x509.UniformResourceIdentifier):
                uri = entry.value
                if any(uri.startswith(f"spiffe://{d}/") for d in domains):
                    from .licence_gate import refusal
                    why = refusal(uri)
                    if why:
                        try:
                            request.state.fedlicence_refused = why
                        except Exception:  # noqa: BLE001
                            pass
                        return None
                    return uri
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[TEG-AUTH] SPIFFE extract failed: {e}")
    return None


def licence_refusal_of(request: Request) -> Optional[str]:
    """The §FEDLICENCE reason extract_spiffe_from_request left on this request, if it refused the caller's licence."""
    try:
        return getattr(request.state, "fedlicence_refused", None)
    except Exception:  # noqa: BLE001
        return None


def _admin_key() -> str:
    s = get_settings()
    k = getattr(s, "admin_api_key", "") or ""
    return k.get_secret_value() if hasattr(k, "get_secret_value") else str(k)

# §MONEY-M3a (R26, 2026-09-03) — a configured admin key that is EMPTY or PLACEHOLDER-SHAPED
# never authenticates. Measured 2026-09-03: the retired non-secret marker string was the
# configured ADMIN_API_KEY on 15 of 16 TEGs, and the code compared bearers against it in ten
# places, which made a public string in the repo an admin credential wherever a compare was
# reachable without mTLS. A SHAPE rule, not a denylist (a denylist would carry the literals it
# exists to refuse): shorter than 32 chars, or carrying a word no generated secret contains.
_PLACEHOLDER_WORDS = ("change", "default", "deprecated", "retired", "placeholder", "example",
                      "sample", "dummy", "changeme")
_MIN_ADMIN_KEY_LEN = 32


def looks_like_placeholder(key: Optional[str]) -> bool:
    """True when `key` is empty, shorter than 32 chars, or carries a placeholder word."""
    k = (key or "").strip()
    if len(k) < _MIN_ADMIN_KEY_LEN:
        return True
    low = k.lower()
    return any(w in low for w in _PLACEHOLDER_WORDS)


def configured_admin_key() -> str:
    """The configured shared admin key, or "" when it is unset or placeholder-shaped."""
    k = _admin_key()
    return "" if looks_like_placeholder(k) else k


def admin_key_ok(token: Optional[str]) -> bool:
    """True iff `token` equals a REAL configured admin key (constant-time compare). Never
    true for an empty token, an empty configured key or a placeholder-shaped configured key."""
    admin = configured_admin_key()
    if not token or not admin:
        return False
    return hmac.compare_digest(str(token), admin)


def resolve_internal_caller(request: Request, token: str = "", route: str = "") -> Tuple[str, str]:
    """Authenticate an internal/admin caller. Returns (auth_mode, identity).

    Raises 403 if neither a valid SVID nor (in shadow) a valid key is presented, or if a key-only
    caller arrives while TEG_MTLS_REQUIRED is true. Emits shadow telemetry on every decision.
    """
    path = route or request.url.path
    spiffe = extract_spiffe_from_request(request)

    if spiffe and is_internal_service_identity(spiffe):
        mode = admin_scope_mode()
        relation = caller_relation(spiffe, own_spiffe_id()) if mode != "off" else "unscoped"
        method = getattr(request, "method", "") or ""
        if mode != "off" and not admin_scope_allows(relation, method, path):
            if mode == "enforce":
                logger.warning(f"[TEG-AUTH-SCOPE] DENY relation={relation} route={method} {path} spiffe={spiffe}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"admin scope: a {relation} identity may not call {method} {path} on this TEG",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            logger.warning(f"[TEG-AUTH-SCOPE] WOULD-DENY relation={relation} route={method} {path} spiffe={spiffe}")
        logger.info(f"[TEG-AUTH] mode=mtls route={path} spiffe={spiffe} relation={relation}")
        return ("mtls", spiffe)
    if spiffe:
        logger.warning(f"[TEG-AUTH] cert present but identity not an internal class: {spiffe} route={path}")

    if teg_mtls_required():
        licence = licence_refusal_of(request)
        logger.warning(f"[TEG-AUTH] DENY route={path} reason={'federation_licence' if licence else 'mtls_required'} "
                       f"cert_present={bool(spiffe)}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(f"federation licence refused: {licence}" if licence else "mTLS identity required"),
            headers={"WWW-Authenticate": "Bearer"},
        )

    admin = configured_admin_key()
    if token and admin and hmac.compare_digest(token, admin):
        logger.warning(
            f"[TEG-AUTH-SHADOW] mode=key-fallback route={path} cert_present={bool(spiffe)} "
            f"-- would FAIL under TEG_MTLS_REQUIRED; caller should present an accepted SVID"
        )
        return ("key", "shared-key")

    logger.warning(f"[TEG-AUTH] DENY route={path} cert_present={bool(spiffe)} key_present={bool(token)}")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid internal credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


if method1_proxy_trust():
    logger.info("[TEG-AUTH] header path on: X-SSL-Client-* counts only with X-TEG-Proxy-Auth from this frame's terminators and SUCCESS")
else:
    logger.warning(
        "[TEG-AUTH] header path OFF: TEG_PROXY_TRUST_SECRET is unset or shorter than 32 characters, so a caller presenting "
        "a certificate through nginx-teg is refused until it is set and the terminators send X-TEG-Proxy-Auth"
    )
