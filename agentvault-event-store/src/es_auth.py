"""Event-store authentication posture (§SOVKIT T2, 2026-09-14): pure helpers with no FastAPI and no database, so the rules
are testable on their own.

Three facts decide how far a caller with a client certificate is trusted:

1. WHERE THE CERTIFICATE HEADERS CAME FROM. nginx terminates mTLS and forwards its verdict as X-SSL-Client-Verify and
   X-SSL-Client-Cert. Anything that reaches the store's port directly (every container on the frame's networks) can
   write those headers itself, so they count only when the request also carries X-ES-Proxy-Auth equal to
   ES_PROXY_TRUST_SECRET, which only this frame's TLS terminators (the event-store sidecar and the public ES vhost)
   set. Without a usable secret the headers are ignored: method 1 is off, and /health says so.
2. WHAT NGINX DECIDED. Only SUCCESS counts; FAILED (a certificate nginx could not verify) never does.
3. WHOSE IDENTITY IT IS. In this frame's own trust domain a known service is "origin" and /operator/<name>/ is that
   operator, while its federation_operators rows let it (operator_standing: no row, or none of them active, refuses it;
   an active one sets its events per minute). A known service of a trusted PEER domain is authenticated but is not this frame: it may read (replication),
   it may not mint and may not change federation records. Anything else needs a registered federation_operators row.
"""
import hmac
import os
from datetime import timezone
from typing import Dict, Iterable, Optional, Tuple
from urllib.parse import unquote

MIN_SECRET_LEN = 32

# The service names a frame's own identities carry. Frames add theirs through KNOWN_INTERNAL_SERVICES; a name listed
# there grants "origin" only inside this frame's own trust domain.
DEFAULT_SERVICES: Tuple[str, ...] = (
    "registry-a", "registry-b", "registry-frame-b",
    "teg-a", "teg-b", "event-store",
    "registry-test", "registry-test-b",
    "teg-layer-test", "teg-layer-test-b",
    "event-store-test", "event-store-test-b",
)


# §SECFIX-7 (2026-09-25): methods that only read. Under EVENTSTORE_MTLS_REQUIRED the internal key still authenticates
# these (monitoring and the manual reconcile tools read with it) and no longer authenticates anything that changes the
# store: an append, a federation-operator or cross-frame-peer change, a governance write.
READ_METHODS = ("GET", "HEAD", "OPTIONS")


def internal_key_may_change(method: Optional[str], mtls_required: bool, setting: Optional[str]) -> bool:
    """May a caller that authenticated ONLY with the internal key change this store? The key was "origin" for every
    method even under EVENTSTORE_MTLS_REQUIRED, so anything on the frame's networks holding it could append events or
    register a federation operator directly, around the TLS terminators (the architecture audit of 2026-09-25). This
    frame's own services reach the store through its terminator, which clears the key and presents the service's
    certificate; the key is left to readers. EVENTSTORE_INTERNAL_KEY_WRITES=allow restores the old behaviour."""
    if (setting or "").strip().lower() == "allow":
        return True
    if not mtls_required:
        return True
    return (method or "").upper() in READ_METHODS


def secret_usable(value: Optional[str]) -> bool:
    """A proxy-trust secret counts only when it is long enough to be one; a short or trivial value counts as unset."""
    v = (value or "").strip()
    return len(v) >= MIN_SECRET_LEN and len(set(v)) > 4


def proxy_trusted(presented: Optional[str], configured: Optional[str]) -> bool:
    """True only when a usable secret is configured and the request carries exactly that value (constant time)."""
    if not secret_usable(configured) or not presented:
        return False
    return hmac.compare_digest(str(presented).encode(), str(configured).strip().encode())


def parse_list(raw: Optional[str]) -> Tuple[str, ...]:
    return tuple(s.strip() for s in (raw or "").split(",") if s.strip())


def _spiffe_uris(cert) -> Tuple[str, ...]:
    from cryptography import x509

    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return ()
    return tuple(u for u in san.get_values_for_type(x509.UniformResourceIdentifier) if u.startswith("spiffe://"))


def spiffe_id_from_forwarded_cert(escaped_pem: Optional[str]) -> Optional[str]:
    """The spiffe:// URI SAN of the certificate nginx forwarded ($ssl_client_escaped_cert, a URL-escaped PEM)."""
    if not escaped_pem:
        return None
    try:
        from cryptography import x509

        pem = unquote(escaped_pem)
        if "BEGIN CERTIFICATE" not in pem:
            return None
        uris = _spiffe_uris(x509.load_pem_x509_certificate(pem.encode()))
        return uris[0] if uris else None
    except Exception:
        return None


def spiffe_id_from_dn(dn: Optional[str]) -> Optional[str]:
    """A spiffe:// URI carried in the subject DN (the fallback when no certificate was forwarded)."""
    if not dn or "spiffe://" not in dn:
        return None
    return dn[dn.find("spiffe://"):].split(",")[0].strip() or None


def split_spiffe_id(spiffe_id: Optional[str]) -> Tuple[str, Tuple[str, ...]]:
    """('eu.theprotocol.cloud', ('service', 'eu-registry')) for spiffe://eu.theprotocol.cloud/service/eu-registry."""
    if not spiffe_id or not spiffe_id.startswith("spiffe://"):
        return "", ()
    domain, _, path = spiffe_id[len("spiffe://"):].partition("/")
    return domain.strip().lower(), tuple(s for s in path.split("/") if s)


def classify(spiffe_id: str, own_domain: str, trusted_domains: Iterable[str], services: Iterable[str]) -> Dict[str, str]:
    """kind: origin | operator | peer_service | untrusted | unregistered (see the module docstring)."""
    domain, segs = split_spiffe_id(spiffe_id)
    trusted = {d.strip().lower() for d in trusted_domains if d and d.strip()}
    if not domain or domain not in trusted:
        return {"kind": "untrusted", "domain": domain}
    service = segs[1] if len(segs) >= 2 and segs[0] == "service" else None
    known = service is not None and service in set(services)
    if own_domain and domain == own_domain.strip().lower():
        if known:
            return {"kind": "origin", "domain": domain, "name": service}
        if len(segs) >= 2 and segs[0] == "operator":
            return {"kind": "operator", "domain": domain, "name": segs[1]}
        return {"kind": "unregistered", "domain": domain}
    if known:
        return {"kind": "peer_service", "domain": domain, "name": service}
    return {"kind": "unregistered", "domain": domain}


# CB-097, CB-221 (2026-10-16): an operator of this frame's own trust domain is authenticated by its certificate, and
# its federation_operators rows decide whether it may still act. The store used to stop at the certificate, so a
# suspended or revoked operator kept appending until its last SVID expired (up to four hours) and the row's
# max_events_per_minute never applied. The rule below is the registry's licence rule (S4,
# core/federation_auth._assert_operator_license_not_revoked) one hop later, read from the rows the registry keeps in
# step with the licence (its licence routes, its operator revoke, its teardown).
DEFAULT_OPERATOR_EVENTS_PER_MINUTE = 1000


def norm_slug(value: Optional[str]) -> str:
    """Lower case, every character that is not a letter or a digit made '-', trimmed of '-': the registry's operator
    name rule (core/federation_auth._norm_slug), so a licence's display name and a certificate's path segment meet."""
    return "".join(c if c.isalnum() else "-" for c in (value or "").lower()).strip("-")


def operator_identity_prefix(own_domain: str, name: str) -> str:
    """spiffe://<own domain>/operator/<name>/ : every workload of the operator (its registry, its svid-writer, ...)."""
    return f"spiffe://{(own_domain or '').strip().lower()}/operator/{(name or '').strip().lower()}/"


def row_names_operator(row_spiffe_id: Optional[str], row_operator_name: Optional[str], own_domain: str,
                       name: str) -> bool:
    """Whether a federation_operators row belongs to the operator /operator/<name>/ of this frame's own trust domain:
    by its SPIFFE id when it carries one (any of the operator's workloads), by its name when it carries none (a row the
    registry's licence sync created from the licence alone). A row naming another identity never matches by name."""
    sid = (row_spiffe_id or "").strip().lower()
    if sid:
        prefix = operator_identity_prefix(own_domain, name)
        return sid.startswith(prefix) or sid == prefix.rstrip("/")
    want = norm_slug(name)
    return bool(want) and norm_slug(row_operator_name) == want


def operator_standing(rows: Iterable[Tuple], own_domain: str, name: str) -> Tuple[str, Optional[int]]:
    """('active', events per minute) | ('inactive', None) | ('unregistered', None) for the operator /operator/<name>/,
    from (spiffe_id, operator_name, status, max_events_per_minute) rows.

    Rows that name the operator and none of them active (suspended, revoked, anything but active, in any case): inactive,
    refused. At least one active: active, within the smallest limit an active row sets (the default when none does).
    No row names it: unregistered, refused as well (2026-10-17: no operator is accepted without its record; the
    registry's licence sync writes the record before the operator is started)."""
    mine = [r for r in rows if row_names_operator(r[0], r[1], own_domain, name)]
    if not mine:
        return "unregistered", None
    active = [r for r in mine if str(r[2] or "").strip().lower() == "active"]
    if not active:
        return "inactive", None
    limits = []
    for r in active:
        try:
            if r[3] is not None and int(r[3]) > 0:
                limits.append(int(r[3]))
        except (TypeError, ValueError):
            continue
    return "active", (min(limits) if limits else DEFAULT_OPERATOR_EVENTS_PER_MINUTE)


# 2026-10-17: the identity a federation_operators row carries IS the operator's record (row_names_operator), so the
# registry's /operators/sync may never move it onto the wrong operator. The registry's trust sync sent every operator of
# a frame the frame's BARE trust domain, the store found a row by that id first and overwrote the row's identity, and one
# row per frame took every same-domain operator's update (its name flipping every cycle, its identity the bare domain).
def is_bare_trust_domain(spiffe_id: Optional[str]) -> bool:
    """spiffe://<domain> with no path: a frame's trust domain, not one workload's identity."""
    domain, segs = split_spiffe_id((spiffe_id or "").strip())
    return bool(domain) and not segs


def shared_domain_id(spiffe_id: Optional[str], own_domain: Optional[str]) -> bool:
    """THIS frame's bare trust domain: every operator of the frame shares it, so it names none of them. It never finds a
    federation_operators row and is never written onto one. (A peer frame's bare domain is that frame's own identity,
    §TRUSTROW, and stays usable; with no known own domain nothing is called shared.)"""
    own = (own_domain or "").strip().lower()
    return bool(own) and is_bare_trust_domain(spiffe_id) and split_spiffe_id((spiffe_id or "").strip())[0] == own


def operator_of_identity(spiffe_id: Optional[str]) -> Optional[Tuple[str, str]]:
    """(domain, operator name) for spiffe://<domain>/operator/<name>[/...], else None. The name compares in lower case,
    as operator_identity_prefix does."""
    domain, segs = split_spiffe_id((spiffe_id or "").strip())
    if domain and len(segs) >= 2 and segs[0] == "operator":
        return domain, segs[1].lower()
    return None


def sync_identity_refusal(row_spiffe_id: Optional[str], new_spiffe_id: Optional[str],
                          own_domain: Optional[str]) -> Optional[str]:
    """Why /operators/sync may not put new_spiffe_id on a row that carries row_spiffe_id, or None when it may (or when
    nothing would change). Never this frame's bare domain; and a row that is an operator's record (it carries an
    /operator/<name>/ identity) keeps naming that operator, so neither another operator's identity nor a domain or a
    service id replaces it. A row carrying no identity, or a bare domain, may take one: the registry's licence decides
    which row a payload is about, and the caller must be this frame's own registry (the handler's rule)."""
    new = (new_spiffe_id or "").strip()
    cur = (row_spiffe_id or "").strip()
    if not new or new.lower() == cur.lower():
        return None
    if shared_domain_id(new, own_domain):
        return "this frame's bare trust domain names no single operator"
    holder = operator_of_identity(cur)
    if holder and operator_of_identity(new) != holder:
        return f"the row is the record of operator {holder[1]} of {holder[0]} and keeps that operator's identity"
    return None


def trust_value_ok(value) -> bool:
    """A bayesian_discount /operators/sync writes: a finite JSON number from 0 to 1, the range the registry derives (a
    Beta posterior mean, its inactivity decay floored at 0.1, the prior 0.5, the column default 1.0). Only this frame's
    own registry writes it (SEC-20, 2026-10-17: the route is origin-only), and the store still holds the value to that
    range: the federation vote multiplies voting power by it, so a larger number is a larger vote, and NaN or infinity
    breaks the vote's rounding. A boolean or a string is not a number here."""
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and 0.0 <= float(value) <= 1.0


# SEC-20 (2026-10-17, his word on the trust value: "it has to be dervied in a meaningful way. setting it manually
# doesnt make sense to me"). The value a new record starts with when the caller sends none: the registry's own
# derivation for a peer it has measured nothing of yet (services/bayesian_trust.derived_trust), never the full 1.0.
NO_RECORD_TRUST = 0.5


def voter_trust_weight(rows: Iterable[Tuple], auth_context: Optional[Dict[str, str]],
                       own_domain: Optional[str]) -> Optional[float]:
    """The weight a federation vote from this caller carries, from (id, spiffe_id, operator_name, status,
    bayesian_discount) rows: 1.0 for this frame's own services (origin); otherwise the trust value of the caller's own
    ACTIVE record, the one verify_event_auth authenticated it by: the record's id (a licence, a SPIFFE id registered as
    an operator), a peer frame's bare trust domain (§TRUSTROW), or an operator's identity in this frame's own trust
    domain (row_names_operator). Several records of one caller: the smallest value, as with the rate limit.

    None when the caller has no active record here: its vote is refused (2026-10-17, his word: "record must exist
    first"), never weighted 1.0. Before, the vote looked the record up by the caller's full SPIFFE id, which a peer
    frame's record (its bare domain) and an operator's record (often another of its workloads' ids) do not carry, and a
    caller it could not find counted at full weight, above every peer the registry had measured."""
    ctx = auth_context or {}
    if is_origin(ctx):
        return 1.0
    own = (own_domain or "").strip().lower()
    record_id = str(ctx.get("operator_id") or "")
    peer = str(ctx.get("peer_frame") or "").strip().lower()
    ident = operator_of_identity(ctx.get("spiffe_id"))
    values = []
    for rid, sid, name, status, value in rows:
        if str(status or "").strip().lower() != "active":
            continue
        if record_id:
            mine = str(rid) == record_id
        elif peer:
            mine = (sid or "").strip().lower() == f"spiffe://{peer}"
        elif ident and own and ident[0].lower() == own:
            mine = row_names_operator(sid, name, own, ident[1])
        else:
            mine = False
        if mine and trust_value_ok(value):
            values.append(float(value))
    return min(values) if values else None


def minute_window_count(last_counted_at, count, now) -> int:
    """SEC-07 (2026-10-17): the count a request at `now` makes in its calendar minute (UTC), on the counter a licence and
    a registered federation operator keep on their federation_operators row (event_count, last_event_at): one more than
    `count` when the row's last counted request (`last_counted_at`) fell in the same calendar minute, else 1 (a new
    minute starts a new count). The caller admits the request while the answer is within the row's events per minute and
    stores the answer and `now` for an admitted request only, so a refused request neither counts nor moves the window:
    a steady stream under the limit is never refused, and above it each minute admits the limit. A last_counted_at in any
    other minute (earlier, or later after the clock moved back) starts a new count; a naive time is read as UTC.

    The counter it replaces reset only after a minute WITHOUT a request (it compared now with the last success), so a
    steady stream under the limit kept growing it and was refused whenever it reached the limit, until it paused."""
    def _minute(t) -> int:
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return int(t.timestamp() // 60)

    if last_counted_at is not None and count and _minute(last_counted_at) == _minute(now):
        return int(count) + 1
    return 1


class MinuteWindow:
    """A fixed window per key and per calendar minute, counted in this process. hit() counts one request and answers
    True when it went past the limit. With several store workers each one counts its own requests, so the limit is
    never stricter than configured. (The licence path and a registered federation operator count on their row, shared
    by every worker, with the same calendar-minute window: minute_window_count.)"""

    def __init__(self):
        self._windows: Dict[str, Tuple[int, int]] = {}

    def hit(self, key: str, limit: int, now: Optional[float] = None) -> bool:
        import time

        minute = int((time.time() if now is None else now) // 60)
        start, count = self._windows.get(key, (minute, 0))
        if start != minute:
            start, count = minute, 0
        count += 1
        self._windows[key] = (start, count)
        return count > limit


def reserved_operator_name(name: Optional[str]) -> bool:
    """The name every "this frame's own services" decision reads (is_origin: auth_context["operator"] == "origin"). A
    caller whose context would carry its own name in that field (an operator of this frame named by its certificate
    path, a registered federation operator, a licence) may not be named so, in any case or spacing (2026-10-17)."""
    return (name or "").strip().lower() == "origin"


def is_origin(auth_context: Optional[Dict[str, str]]) -> bool:
    """True when the caller is one of THIS frame's own services, whichever way it authenticated: the internal key
    (auth_type internal) or its certificate through the frame's own terminator (auth_type mtls, operator origin).
    A route that means "only this frame" asks this, never auth_type alone (§SOVKIT T5: behind the store's mTLS sidecar
    the registry's and the TEG's calls arrive as mtls, and the internal key is cleared on the way)."""
    return (auth_context or {}).get("operator") == "origin"


_OWN_DOMAIN_CACHE: Dict[str, str] = {}


def own_trust_domain(env_value: Optional[str], cert_dir: Optional[str]) -> Tuple[str, str]:
    """This frame's own trust domain and its source: 'env' (ES_OWN_TRUST_DOMAIN), 'svid' (the store's own certificate,
    <CERT_DIR>/svid.0.pem) or 'none'. It never guesses: an unknown own domain gives nobody "origin" by certificate (the
    internal key still works), and a failed read is retried on the next call rather than latched."""
    if env_value and env_value.strip():
        return env_value.strip().lower(), "env"
    if "svid" in _OWN_DOMAIN_CACHE:
        return _OWN_DOMAIN_CACHE["svid"], "svid"
    try:
        from cryptography import x509

        with open(os.path.join(cert_dir or "/certs", "svid.0.pem"), "rb") as fh:
            uris = _spiffe_uris(x509.load_pem_x509_certificate(fh.read()))
        domain = split_spiffe_id(uris[0])[0] if uris else ""
        if domain:
            _OWN_DOMAIN_CACHE["svid"] = domain
            return domain, "svid"
    except Exception:
        pass
    return "", "none"
