from fastapi import APIRouter, HTTPException, Depends, Header, Query, Request, Security
from fastapi.security import APIKeyHeader
from typing import Dict, List, Optional

# §pass53 PR-4: spec-side scheme declarations. auto_error=False keeps runtime
# unchanged (handler still reads Header() below). These markers cause FastAPI
# to emit `security: [...]` on every route using verify_event_auth.
_internal_key_scheme = APIKeyHeader(
    name="X-Internal-Key",
    description="Shared secret for in-cluster service-to-service calls.",
    auto_error=False,
)
_federation_license_scheme = APIKeyHeader(
    name="X-Federation-License",
    description="Operator license key (tp_fed_...). For external federated operators.",
    auto_error=False,
)
from ..models.events import Event
from ..models.federation_operator import FederationOperator
from ..services.event_store import EventStore
from ..database.connection import get_db
from ..metrics_exporter import EVENTS_INGESTED_TOTAL
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, select
from sqlalchemy.sql import func
import hashlib
import os
import logging
import time
import uuid

logger = logging.getLogger(__name__)

from ..es_auth import (
    DEFAULT_SERVICES, READ_METHODS, MinuteWindow, classify, internal_key_may_change, minute_window_count,
    operator_identity_prefix, operator_standing, own_trust_domain, parse_list, proxy_trusted, reserved_operator_name,
    secret_usable, shared_domain_id, spiffe_id_from_dn, spiffe_id_from_forwarded_cert, sync_identity_refusal,
    trust_value_ok, NO_RECORD_TRUST,
)

router = APIRouter(prefix="/api/v1/events", tags=["events"])
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
# §SOVKIT T2 (2026-09-14, his word: "make this required on because its a big trap not enabling it"): the licence
# fallback is refused unless a store is explicitly configured EVENTSTORE_MTLS_REQUIRED=false.
MTLS_REQUIRED = os.getenv("EVENTSTORE_MTLS_REQUIRED", "true").strip().lower() not in ("false", "0", "no", "off")
EVENTSTORE_HTTP_VIA_KAFKA = os.getenv("EVENTSTORE_HTTP_VIA_KAFKA", "false").lower() == "true"
# §SECFIX-7 (2026-09-25): "allow" lets the internal key change the store again under EVENTSTORE_MTLS_REQUIRED (break-glass).
INTERNAL_KEY_WRITES = os.getenv("EVENTSTORE_INTERNAL_KEY_WRITES", "")
PROXY_TRUST_SECRET = os.getenv("ES_PROXY_TRUST_SECRET", "")
METHOD1_PROXY_TRUST = secret_usable(PROXY_TRUST_SECRET)
if not INTERNAL_API_KEY:
    logger.warning("INTERNAL_API_KEY not set! Event append endpoint will reject all requests.")
if MTLS_REQUIRED:
    logger.info("EVENTSTORE_MTLS_REQUIRED on: external operators MUST use mTLS (X-Federation-License rejected)")
else:
    logger.warning("EVENTSTORE_MTLS_REQUIRED=false: this store still accepts X-Federation-License (the licence fallback)")
if METHOD1_PROXY_TRUST:
    logger.info("mTLS (method 1) on: X-SSL-* headers count only with X-ES-Proxy-Auth from this frame's TLS terminators")
else:
    logger.error(
        "mTLS (method 1) OFF: ES_PROXY_TRUST_SECRET is unset or shorter than 32 characters, so operators and peer "
        "replicators are refused until it is set and the frame's TLS terminators send X-ES-Proxy-Auth"
    )

_UNPROXIED = {"count": 0, "last_log": 0.0}


def _note_unproxied_cert_headers() -> None:
    """Certificate headers without a valid proxy marker are never trusted. Logged at most once a minute with a count:
    a direct caller forging them is what the marker exists for, and a frame whose terminators lack the marker shows
    up here too."""
    import time

    _UNPROXIED["count"] += 1
    now = time.monotonic()
    if now - _UNPROXIED["last_log"] >= 60:
        logger.warning(
            "[mTLS] ignored X-SSL-* headers without a valid X-ES-Proxy-Auth (%d since the last line; method 1 %s)",
            _UNPROXIED["count"], "on" if METHOD1_PROXY_TRUST else "OFF: ES_PROXY_TRUST_SECRET unset",
        )
        _UNPROXIED["count"] = 0
        _UNPROXIED["last_log"] = now


_KEY_REFUSED = {"count": 0, "last_log": 0.0}


def _note_internal_key_change_refused(request: Request) -> None:
    """A change presented with only the internal key, refused. Logged at most once a minute with a count and the last
    caller, so a writer still using the key is named rather than silently dropped."""
    import time

    _KEY_REFUSED["count"] += 1
    now = time.monotonic()
    if now - _KEY_REFUSED["last_log"] >= 60:
        client = request.client.host if request.client else "?"
        logger.warning(
            "[Auth] REFUSED %d change(s) authenticated only by the internal key since the last line "
            "(EVENTSTORE_MTLS_REQUIRED; last: %s %s from %s). Send them through this frame's TLS terminator.",
            _KEY_REFUSED["count"], request.method, request.url.path, client,
        )
        _KEY_REFUSED["count"] = 0
        _KEY_REFUSED["last_log"] = now


# CB-097, CB-221 (2026-10-16): an operator of this frame's own trust domain was authenticated by its certificate alone.
# Its federation_operators rows (which the registry suspends or revokes with the licence, at an operator revoke and at
# a teardown) were never read, so a suspended or revoked operator kept writing until its last SVID expired, up to four
# hours later, and its max_events_per_minute never applied. Now every request from such an operator asks its rows
# (es_auth.operator_standing), through a verdict cached OPERATOR_STANDING_TTL seconds per worker: a suspension stops the
# operator within a minute without a database read on every event.
# 2026-10-17 (his word: "no operator accepted without record ... record must exist first"): an operator that no row
# names is refused like a suspended one. Every verdict, a refusal included, lives the same OPERATOR_STANDING_TTL, so a
# record created after a refusal takes effect within the same window a suspension does.
OPERATOR_STANDING_TTL = 30.0
_OPERATOR_STANDING: Dict[str, tuple] = {}
_OPERATOR_WINDOW = MinuteWindow()
_OPERATOR_WITHOUT_ROW = {"count": 0, "last_log": 0.0, "names": set()}


async def _operator_standing(db: AsyncSession, own: str, name: str) -> tuple:
    """(standing, events per minute) for the operator /operator/<name>/ of this frame (es_auth.operator_standing), cached
    per worker for OPERATOR_STANDING_TTL whatever the verdict (a refusal is never kept longer than an acceptance). Reads
    the rows that carry one of the operator's identities, and the rows that carry none (a licence synced without one),
    which operator_standing matches by name. A failed read raises and is not cached."""
    key = f"{own}/{name}".lower()
    now = time.monotonic()
    cached = _OPERATOR_STANDING.get(key)
    if cached and now - cached[0] < OPERATOR_STANDING_TTL:
        return cached[1], cached[2]
    prefix = operator_identity_prefix(own, name)
    sid = func.lower(FederationOperator.spiffe_id)
    stmt = select(
        FederationOperator.spiffe_id, FederationOperator.operator_name, FederationOperator.status,
        FederationOperator.max_events_per_minute,
    ).where(or_(
        sid.startswith(prefix, autoescape=True), sid == prefix.rstrip("/"),
        FederationOperator.spiffe_id.is_(None), FederationOperator.spiffe_id == "",
    ))
    rows = (await db.execute(stmt)).fetchall()
    standing, limit = operator_standing(rows, own, name)
    _OPERATOR_STANDING[key] = (now, standing, limit)
    return standing, limit


def _note_operator_without_row(name: str) -> None:
    """An operator of this frame with no federation_operators row: refused (no operator is accepted without its
    record), and named in the log at most once a minute with a count, since a writer retries."""
    _OPERATOR_WITHOUT_ROW["count"] += 1
    _OPERATOR_WITHOUT_ROW["names"].add(name)
    now = time.monotonic()
    if now - _OPERATOR_WITHOUT_ROW["last_log"] >= 60:
        logger.warning(
            "[mTLS] REFUSED %d request(s) from operator(s) %s with no federation_operators row: this store accepts no "
            "operator without its record. The registry's licence sync writes it (provisioning, the licence routes).",
            _OPERATOR_WITHOUT_ROW["count"], sorted(_OPERATOR_WITHOUT_ROW["names"]),
        )
        _OPERATOR_WITHOUT_ROW.update(count=0, last_log=now, names=set())


_OPERATOR_OVER_LIMIT: Dict[str, list] = {}


def _note_operator_over_limit(name: str, limit: int) -> None:
    """A change refused for an operator's events per minute, logged at most once a minute per operator with a count (a
    writer that retries would otherwise write one line per refusal)."""
    entry = _OPERATOR_OVER_LIMIT.setdefault(name, [0, 0.0])
    entry[0] += 1
    now = time.monotonic()
    if now - entry[1] >= 60:
        logger.warning(f"[RateLimit] Operator {name} exceeded {limit} events/min: {entry[0]} change(s) refused with 429 "
                       f"since the last line")
        entry[0], entry[1] = 0, now


def _reserved_name_refusal(who: str, name: str) -> HTTPException:
    """2026-10-17: a caller authenticated as an operator, a registered federation operator or a licence whose NAME is
    the "origin" marker (es_auth.reserved_operator_name). Every decision that means "this frame's own services" reads
    auth_context["operator"] == "origin" (es_auth.is_origin, require_origin_auth, the MONEY-R10 mint rule), and these
    paths put the caller's name in that field, so such a caller would have passed as this frame's own service. Refused
    before anything is written (the rate counter included)."""
    logger.warning(f"[Auth] REFUSED {who}: its name {name!r} is reserved for this frame's own services")
    return HTTPException(status_code=403, detail="This caller's name is reserved for this frame's own services")


async def _count_on_the_row(db: AsyncSession, op: FederationOperator) -> None:
    """The events per minute of a registered federation operator and of a licence, counted on its federation_operators
    row (event_count, last_event_at), which every store worker shares: a fixed window per calendar minute (UTC,
    es_auth.minute_window_count). A request past the row's max_events_per_minute in its minute is refused 429 and changes
    nothing; an admitted one stores the minute's count and this store's own clock, so the next request's minute is read
    from the same clock it is decided by.

    SEC-07 (2026-10-17): the counter reset only after a minute WITHOUT a request (it compared now with the last success,
    stamped by the database's clock), so a steady stream under the limit kept growing it and was refused for as long as
    it kept coming within a minute of its last admitted request. (Two workers counting at the same instant can still both
    read the same count; the limit then admits slightly more, never less.)"""
    from datetime import datetime as _dt, timezone as _tz

    now = _dt.now(_tz.utc)
    count = minute_window_count(op.last_event_at, op.event_count, now)
    if count > (op.max_events_per_minute or 1000):
        logger.warning(f"[RateLimit] Operator {op.operator_name} exceeded {op.max_events_per_minute} events/min")
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    op.event_count = count
    op.last_event_at = now
    await db.commit()


async def verify_internal_key(x_internal_key: str = Header(...)):
    """Original internal key check -- used by read endpoints (GET /events, GET /aggregate)."""
    from ..internal_key import internal_key_ok  # §KEYROT: current OR previous during a rotation window
    if not internal_key_ok(x_internal_key):
        raise HTTPException(status_code=403, detail="Invalid internal key")


async def verify_event_auth(
    request: Request,
    # §pass53 PR-4: spec-side declarations for the three auth modes.
    # auto_error=False keeps runtime behavior unchanged — the function still
    # checks each Header(None) value below and decides which mode to use.
    # SDK generators now see security: [{InternalAPIKey:[]}, {FederationLicense:[]}, {mTLSPeer:[]}]
    # closing 16 of 16 mutator-no-security gap (E-P0-1 from swagger audit).
    _internal_key_marker: Optional[str] = Security(_internal_key_scheme),
    _federation_license_marker: Optional[str] = Security(_federation_license_scheme),
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key"),
    x_federation_license: Optional[str] = Header(None, alias="X-Federation-License"),
    x_ssl_client_verify: Optional[str] = Header(None, alias="X-SSL-Client-Verify"),
    x_ssl_client_s_dn: Optional[str] = Header(None, alias="X-SSL-Client-S-DN"),
    x_ssl_client_cert: Optional[str] = Header(None, alias="X-SSL-Client-Cert"),
    x_es_proxy_auth: Optional[str] = Header(None, alias="X-ES-Proxy-Auth"),
    db: AsyncSession = Depends(get_db),
) -> Dict:
    """Verify event append authentication.

    Three methods (checked in priority order):
    1. mTLS, as decided by this frame's own TLS terminator (the event-store sidecar or the public ES vhost)
    2. X-Internal-Key (this frame's own services; under EVENTSTORE_MTLS_REQUIRED it authenticates reads only, §SECFIX-7)
    3. X-Federation-License (refused while EVENTSTORE_MTLS_REQUIRED, which is the code default)

    Returns auth context dict with operator info; operator == "origin" means one of THIS frame's own services.
    """
    # Method 1 (§SOVKIT T2, 2026-09-14). The X-SSL-* headers are nginx's verdict on the client certificate, and anything
    # that reaches this port directly can write them itself (measured: 31 containers on eu_network, 28 on
    # fresh-identity). They count only with X-ES-Proxy-Auth, which only this frame's TLS terminators set; only SUCCESS
    # counts; and "origin" belongs to this frame's own trust domain (a federated peer's registry was "origin" on EU's
    # ledger, 710 times in 24 h). The rules and their reasons live in es_auth.py.
    if x_ssl_client_verify or x_ssl_client_cert or x_ssl_client_s_dn:
        if not proxy_trusted(x_es_proxy_auth, PROXY_TRUST_SECRET):
            _note_unproxied_cert_headers()
        elif x_ssl_client_verify == "SUCCESS":
            spiffe_id = spiffe_id_from_forwarded_cert(x_ssl_client_cert) or spiffe_id_from_dn(x_ssl_client_s_dn)
            if spiffe_id:
                trusted = parse_list(os.getenv("TRUSTED_SPIFFE_DOMAINS", "agentvault.com"))
                services = DEFAULT_SERVICES + parse_list(os.getenv("KNOWN_INTERNAL_SERVICES"))
                own, _own_source = own_trust_domain(os.getenv("ES_OWN_TRUST_DOMAIN"), os.getenv("CERT_DIR", "/certs"))
                who = classify(spiffe_id, own, trusted, services)
                if who["kind"] == "origin":
                    logger.info(f"[mTLS] Internal service authenticated: {spiffe_id}")
                    return {"auth_type": "mtls", "operator": "origin", "spiffe_id": spiffe_id}
                if who["kind"] == "operator":
                    if reserved_operator_name(who["name"]):
                        raise _reserved_name_refusal(spiffe_id, who["name"])
                    # CB-097, CB-221: the certificate says who; the operator's rows say whether it may still act.
                    try:
                        standing, limit = await _operator_standing(db, own, who["name"])
                    except Exception as exc:  # noqa: BLE001  fail closed, and retryable: both writers retry a 503
                        logger.error(f"[mTLS] could not read the federation status of operator {who['name']}: "
                                     f"{type(exc).__name__}: {exc}")
                        raise HTTPException(status_code=503,
                                            detail="This store could not read the operator's federation status; retry")
                    if standing == "inactive":
                        logger.warning(f"[mTLS] REFUSED operator {who['name']} ({spiffe_id}): its federation "
                                       f"operator status here is suspended or revoked")
                        raise HTTPException(status_code=403,
                                            detail="Operator is not active in this frame's federation "
                                                   "(suspended or revoked)")
                    if standing == "unregistered":
                        _note_operator_without_row(who["name"])
                        raise HTTPException(status_code=403,
                                            detail="Operator is not active in this frame's federation "
                                                   "(no federation operator record)")
                    if (request.method or "").upper() not in READ_METHODS and _OPERATOR_WINDOW.hit(
                            f"{own}/{who['name']}".lower(), limit):
                        _note_operator_over_limit(who["name"], limit)
                        raise HTTPException(status_code=429, detail="Rate limit exceeded")
                    logger.info(f"[mTLS] Trusted operator authenticated: {spiffe_id}")
                    return {"auth_type": "mtls", "operator": who["name"], "spiffe_id": spiffe_id}
                if who["kind"] == "peer_service":
                    logger.info(f"[mTLS] Peer frame service authenticated (not this frame): {spiffe_id}")
                    return {"auth_type": "mtls", "operator": f"peer:{who['domain']}", "peer_frame": who["domain"],
                            "spiffe_id": spiffe_id}
                if who["kind"] == "untrusted":
                    logger.warning(f"[mTLS] REJECTED SPIFFE ID from an untrusted trust domain: {spiffe_id}")
                    raise HTTPException(status_code=403,
                                        detail=f"SPIFFE trust domain not trusted by this event store: {spiffe_id}")

                # Anything else must be a registered federation operator (the row carries its own rate limit).
                result = await db.execute(
                    select(FederationOperator).where(
                        FederationOperator.spiffe_id == spiffe_id
                    )
                )
                op = result.scalar_one_or_none()
                if op and op.status == "active":
                    if reserved_operator_name(op.operator_name):
                        raise _reserved_name_refusal(spiffe_id, op.operator_name)
                    await _count_on_the_row(db, op)   # SEC-07: its events per minute, per calendar minute
                    logger.info(f"[mTLS] Federated operator authenticated: {op.operator_name} ({spiffe_id})")
                    return {
                        "auth_type": "mtls",
                        "operator": op.operator_name,
                        "operator_id": op.id,
                        "spiffe_id": spiffe_id,
                    }

                # Unknown SPIFFE ID: reject. Operators must be registered before sending events.
                logger.warning(f"[mTLS] REJECTED unknown SPIFFE ID: {spiffe_id}")
                raise HTTPException(
                    status_code=403,
                    detail=f"Unknown SPIFFE ID: {spiffe_id}. Register as a federation operator first."
                )

    # Method 2: Internal key (backward compatible — internal Docker services)
    from ..internal_key import internal_key_ok  # §KEYROT: current OR previous during a rotation window
    if x_internal_key and internal_key_ok(x_internal_key):
        # §SECFIX-7: under EVENTSTORE_MTLS_REQUIRED the key authenticates reads only.
        if not internal_key_may_change(request.method, MTLS_REQUIRED, INTERNAL_KEY_WRITES):
            _note_internal_key_change_refused(request)
            raise HTTPException(
                status_code=403,
                detail="mtls_required: the internal key no longer authenticates a change to this store; send it "
                       "through this frame's TLS terminator with the service's SPIRE certificate",
            )
        return {"auth_type": "internal", "operator": "origin"}

    # Method 3: Federation license key (fallback — blocked when MTLS_REQUIRED=true)
    if x_federation_license and MTLS_REQUIRED:
        logger.warning(f"[Auth] Rejected X-Federation-License — EVENTSTORE_MTLS_REQUIRED=true. Operator must use mTLS.")
        raise HTTPException(status_code=403, detail="mTLS required — X-Federation-License is no longer accepted. Present a valid SPIRE SVID client certificate.")
    if x_federation_license:
        key_hash = hashlib.sha256(x_federation_license.encode()).hexdigest()
        result = await db.execute(
            select(FederationOperator).where(
                FederationOperator.license_key_hash == key_hash
            )
        )
        op = result.scalar_one_or_none()

        if op and op.status == "active":
            if reserved_operator_name(op.operator_name):
                raise _reserved_name_refusal(f"licence of record {op.id}", op.operator_name)
            await _count_on_the_row(db, op)   # SEC-07: its events per minute, per calendar minute
            return {
                "auth_type": "federation",
                "operator": op.operator_name,
                "operator_id": op.id,
            }

        raise HTTPException(
            status_code=403, detail="Invalid or revoked federation license"
        )

    raise HTTPException(
        status_code=403,
        detail="Authentication required: provide X-Internal-Key, X-Federation-License, or mTLS client certificate",
    )


async def require_origin_auth(auth_context: Dict = Security(verify_event_auth)) -> Dict:
    """For routes that change this ledger's federation records (cross-frame peers, federation operators): only this
    frame's own services, i.e. the internal key or an origin SVID of this frame's own trust domain (§SOVKIT T2). A peer
    frame or an operator authenticates here but may not change who this ledger trusts; every registry call measured
    on 2026-09-14 used the internal key."""
    if (auth_context or {}).get("operator") != "origin":
        logger.warning(
            "[Auth] REFUSED a federation-record change from a caller that is not this frame's own service: %s (%s)",
            (auth_context or {}).get("spiffe_id") or (auth_context or {}).get("operator"),
            (auth_context or {}).get("auth_type"),
        )
        raise HTTPException(
            status_code=403,
            detail="Only this frame's own services may change cross-frame peers or federation operators",
        )
    return auth_context


@router.post(
    "/",
    response_model=Event,
    status_code=201,
    responses={
        201: {"description": "Event accepted (also returned on idempotent replay — same key, same payload)"},
        400: {"description": "Bad request — missing required fields"},
        401: {"description": "Unauthenticated"},
        403: {"description": "Forbidden — wrong auth scheme for this event type"},
        409: {"description": "Idempotent conflict — same Idempotency-Key already used with a DIFFERENT payload"},
        422: {"description": "Validation error — schema mismatch"},
    },
)
async def append_event(
    event: Event,
    db: AsyncSession = Depends(get_db),
    auth_context: Dict = Security(verify_event_auth),
):
    """Append a new event. Accepts internal key, federation license, or mTLS peer SVID.

    When EVENTSTORE_HTTP_VIA_KAFKA=true, publishes to Kafka (returns 202)
    instead of writing to DB directly. The Kafka consumer persists the event.

    **Idempotency contract (§pass52 PR-11 partial):**
    The request body MUST include an `idempotency_key` field (string, ≤255 chars).
    EventStore enforces UNIQUE(idempotency_key) at the database level. If a second
    request arrives with the same key + same payload, the response is **identical
    to the first** (201 with the original stored event) — exactly-once semantics.
    Different payload + same key → 409 Conflict. NULL idempotency_key is currently
    permitted for non-financial events; balance-moving events MUST carry a
    deterministic key (Phase D enforcement). See:
    - `event_emitter.py:319` — 2026-04-09 Kafka return-after-success fix (NEVER REVERT)
    - `materialized_balances.sql:69` — 2026-04-12 TokensIssued-only trigger fix (NEVER REVERT)
    - `auditor.theprotocol.cloud/api/auditor/breaches` — 6 historical breach events
    - `project_supply_invariant_breach_history.md` memory — verification commands
    """
    # ── §MONEY-R10 (2026-09-04): ORIGIN RULE ON MINT-CLASS EVENTS ────────────
    # The ledger authenticated the caller and then never asked whether THIS
    # caller may emit THIS type. A federated operator holding a valid mTLS SVID
    # could POST TokensIssued and mint supply into the frame's books.
    #
    # ⚠ The rule reads auth_context, NEVER event.source_service: source_service
    # comes from the REQUEST BODY and is caller-supplied, so a rule keyed on it
    # would be theatre — the same shape as trusting the first X-Forwarded-For
    # element (§XFFTRUST). verify_event_auth sets operator == "origin" for an
    # internal service (mTLS SVID in KNOWN_INTERNAL_SERVICES, or the internal
    # key) and an operator NAME for anyone federated.
    #
    # MEASURED on this ledger before enforcing (106,650,475 events):
    #   · mint-class events: 847 total — TokensIssued 841 from source_service
    #     'registry' + 4 from 'teg' (2026-03-29, pre-policy), and 2
    #     DisputeCompensationMinted from 'registry'. ZERO from any operator.
    #   · operators DO write here — teg-teg-op-{paris,london,berlin,washington}
    #     account for 23,686+ events — so this is a real capability, not a
    #     theoretical one; they have simply never used it to mint.
    #   · source_operator_id is a LIVE field (populated on 9 events, two distinct
    #     operator ids), so "NULL on all 847" is evidence and not an unused column.
    # ⇒ enforcing breaks no historical caller.
    _MINT_CLASS_TYPES = {"TokensIssued", "DisputeCompensationMinted"}
    _is_mint_class = event.event_type in _MINT_CLASS_TYPES or (
        event.event_type == "LedgerBalanceChanged"
        and isinstance(event.data, dict)
        and event.data.get("kind") in ("mint", "dispute_comp")
    )
    if _is_mint_class and (auth_context or {}).get("operator") != "origin":
        _who = (auth_context or {}).get("spiffe_id") or (auth_context or {}).get("operator") or "unknown"
        logger.error(
            "[MONEY-R10] REFUSED %s from non-origin caller %s (auth_type=%s). Minting is "
            "the mainframe registry's alone; a federated identity may not add supply to "
            "this frame's books.",
            event.event_type, _who, (auth_context or {}).get("auth_type"),
        )
        raise HTTPException(
            status_code=403,
            detail=(
                f"'{event.event_type}' may only be appended by this frame's own registry. "
                f"Federated operators cannot emit mint-class events."
            ),
        )

    # ── §pass52 Phase H — write-time validators ──────────────────────────────
    # Catch misconfigurations BEFORE they hit the immutable ledger.
    from ..services.projections import (
        BALANCE_MOVING_EVENT_TYPES,
        _skip_in_projection,
        _is_known_event_type,
    )

    # §pass53 PR-11b: defensive event_type validator. Closed-set comes from the
    # policy table (synced via _refresh_skip_policies — incl. Phase F Redis
    # pub/sub invalidation when wired). Default: warn (Prom counter via
    # Phase A) without blocking. Strict mode (env EVENTSTORE_STRICT_EVENT_TYPES=true)
    # rejects with 422 — flip after the policy table is comprehensive AND the
    # auditor's "unknown event types" Prom counter has been zero for 7+ days.
    if not _is_known_event_type(event.event_type):
        logger.warning(
            f"[PHASE-K] Unknown event_type '{event.event_type}' written to ledger. "
            f"Add a row to event_emission_policies if this is a legitimate new type. "
            f"Strict mode (env EVENTSTORE_STRICT_EVENT_TYPES=true) will reject this with 422."
        )
        if os.environ.get("EVENTSTORE_STRICT_EVENT_TYPES", "false").lower() == "true":
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unknown event_type '{event.event_type}' — not registered in "
                    f"event_emission_policies. Add a policy row "
                    f"(PUT /api/v1/admin/event-emission-policies/{event.event_type}) "
                    f"and retry. See §pass53 PR-11b."
                ),
            )

    # V1: balance-moving events MUST carry a deterministic idempotency_key.
    # Without it, dedupe fails between callers (e.g. Registry + TEG both
    # emit TokensTransferred → both insert → balance doubles in projection).
    # See `DESIGN_2026-05-20 §1 T1` threat model.
    if event.event_type in BALANCE_MOVING_EVENT_TYPES and not event.idempotency_key:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Balance-moving event '{event.event_type}' requires a deterministic "
                f"idempotency_key. NULL keys break dedupe and risk supply-invariant drift. "
                f"Pass idempotency_key on the request body."
            ),
        )

    # V2: balance-moving events MUST NOT be flagged skip_in_projection=true.
    # If we get an event whose type is in the policy skip set, it means an
    # admin (or buggy migration) set skip_in_projection=true on a balance-moving
    # type — silently dropping it from the projection would create supply drift.
    if event.event_type in BALANCE_MOVING_EVENT_TYPES and event.event_type in _skip_in_projection:
        logger.error(
            f"[PHASE-H V2] CRITICAL: balance-moving event '{event.event_type}' is "
            f"flagged skip_in_projection=true. REJECTING write — fix the policy first."
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Policy violation: '{event.event_type}' is a balance-moving event but "
                f"has skip_in_projection=true in the policy table. This would create supply "
                f"drift. Fix the policy (PATCH /api/v1/admin/event-emission-policies/{event.event_type} "
                f"with skip_in_projection=false) before retrying."
            ),
        )

    if EVENTSTORE_HTTP_VIA_KAFKA:
        # D6-298: the lockdown refuses here as it does on the direct path (EventStore.append_event). Accepted with 202,
        # the event would wait in the broker and be stored the moment the lockdown is cleared.
        from ..services.lockdown_state import GLOBAL_LOCKDOWN
        if await GLOBAL_LOCKDOWN.is_locked():
            logger.warning(f"[EventStore] Publish refused — lockdown active: {GLOBAL_LOCKDOWN.reason}")
            raise HTTPException(status_code=503, detail=GLOBAL_LOCKDOWN.detail())

        from ..services.kafka_publisher import get_publisher
        publisher = get_publisher()
        if publisher is None:
            raise HTTPException(status_code=503, detail="Kafka publisher not initialized")

        event_dict = {
            "id": event.id or str(uuid.uuid4()),
            "event_type": event.event_type,
            "aggregate_id": event.aggregate_id,
            "aggregate_type": event.aggregate_type,
            "data": event.data,
            "metadata": event.metadata or {},
            "source_service": event.source_service,
            "idempotency_key": event.idempotency_key,
            "timestamp": event.timestamp.isoformat() if hasattr(event.timestamp, "isoformat") else str(event.timestamp),
            "version": event.version,
        }
        if auth_context.get("operator_id"):
            event_dict["source_operator_id"] = auth_context["operator_id"]

        try:
            await publisher.publish(event_dict)
        except Exception as e:
            logger.error(f"Failed to publish event to Kafka: {e}")
            raise HTTPException(status_code=503, detail=f"Kafka publish failed: {e}")

        # §ESDUP 2026-08-22 — the accept-time websocket broadcast USED TO LIVE HERE and
        # was REMOVED. It made every event ingested over this HTTP route reach clients
        # TWICE: once here at accept, and again from services/kafka_consumer.py after the
        # Kafka consumer had actually stored it. Measured on frame-c before removal:
        # 207 `events:all` deliveries / 117 unique ids = 1.77x.
        #
        # The consumer's broadcast is the correct one and is kept: it fires only once the
        # event is DURABLE. Announcing an event here, before it is stored, tells clients a
        # thing happened that may still fail to persist.
        #
        # Do not reinstate this without also removing the consumer's broadcast — one
        # storage path, one announcement. The non-Kafka branch below already does exactly
        # that (store, then publish once).

        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "idempotency_key": event.idempotency_key,
                "event_id": event_dict["id"],
            },
        )

    try:
        logger.info(f"Received event: {event} (auth={auth_context['auth_type']})")
        event_store = EventStore(db)
        stored_event = await event_store.append_event(
            event,
            source_operator_id=auth_context.get("operator_id"),
        )
        EVENTS_INGESTED_TOTAL.labels(
            source="http", event_type=stored_event.event_type or "unknown"
        ).inc()
        logger.info(f"Stored event: {stored_event}")

        try:
            from ..services.websocket_publisher import event_publisher
            await event_publisher.publish_event(stored_event)
        except Exception as ws_error:
            logger.error(f"Failed to publish event via WebSocket: {ws_error}")

        return stored_event
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error storing event: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# P1-004: Raw event endpoints required internal key authentication originally.
# §pass71.2 (2026-05-25) — widened to verify_event_auth (mTLS / X-Internal-Key /
# X-Federation-License) so callers going through nginx-event-store sidecar
# (which strips X-Internal-Key per "mTLS is the authority" §pass69 doctrine)
# can still authenticate via SPIFFE SVID. Mirrors the 2026-05-02 widening on
# /export and /foreign that closed the same gap for reactor polling.
@router.get("/aggregate/{aggregate_id}", response_model=List[Event])
async def get_aggregate_events(
    aggregate_id: str,
    event_types: Optional[str] = None,
    # §POCKETBRIDGE5 W-G — the unbounded contract was a landmine: the busiest
    # frame-c aggregate holds 1.1M events (measured 2026-08-23), so "all events
    # for an aggregate" is a request nothing should be able to make by accident.
    # Defaults preserve the legacy contract EXACTLY (no limit, ASC) for the
    # existing replay/projection callers; a bounded caller opts in.
    limit: Optional[int] = Query(None, ge=1, le=1000),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    auth: Dict = Security(verify_event_auth),
):
    """Get events for an aggregate. Auth: mTLS / X-Internal-Key / X-Federation-License.

    Default (no `limit`): the full ASC history — the legacy replay contract.
    With `limit` (+ `sort_order=desc`): the newest N of that aggregate, for
    per-agent activity views that must never pull a million rows.
    """
    event_store = EventStore(db)
    types_list = event_types.split(",") if event_types else None
    return await event_store.get_events_for_aggregate(
        aggregate_id, types_list, limit=limit, sort_order=sort_order
    )

@router.get("/", response_model=List[Event])
async def get_all_events(
    limit: int = Query(100, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    event_type: Optional[str] = Query(
        None,
        description="If set, returns the most recent N events of this type (DESC) instead of paginated all-events ASC.",
    ),
    sort_order: str = Query(
        "asc",
        description="Order for the no-filter pagination path. 'asc' (default) preserves legacy chronological order; 'desc' returns newest-first (admin UIs / incident response).",
        pattern="^(asc|desc)$",
    ),
    db: AsyncSession = Depends(get_db),
    auth: Dict = Security(verify_event_auth),
):
    """Get events with pagination (max 10000). Auth: mTLS / X-Internal-Key / X-Federation-License (§pass71.2).

    Default: ASC by timestamp, no filter (legacy behavior — preserved for SF-4
    replicators + projection bootstrap that depend on chronological replay).
    With `event_type`: DESC by timestamp, filtered to that single type, and
    `offset`-paginated (so the admin Event Ledger can page / loop-fetch the
    full set of a type, not just the recent window).
    With `sort_order=desc` and no `event_type`: DESC by timestamp, paginated.
    """
    event_store = EventStore(db)
    if event_type:
        return await event_store.get_events_by_type(event_type, limit, offset)
    return await event_store.get_all_events(limit, offset, sort_order=sort_order)

@router.get("/by-transaction/{transaction_id}", response_model=List[Event])
async def get_events_by_transaction(
    transaction_id: str,
    db: AsyncSession = Depends(get_db),
    auth: Dict = Security(verify_event_auth),
):
    """Get all events carrying this `data.transaction_id` (indexed lookup).

    A single TEG transaction id (the id returned by /teg/transactions →
    getMyTegTransactions) can map to several ledger events, e.g.
    TokensTransferred + TransactionFeeCollected. Returns newest-first; empty
    list if the id is not on the ledger (TEG-only bookkeeping such as locks
    never reaches the EventStore). Auth: mTLS / X-Internal-Key /
    X-Federation-License (§pass71.2)."""
    event_store = EventStore(db)
    return await event_store.get_events_by_transaction(transaction_id)

@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "event-store"}

# ---------------------------------------------------------------------------
# Federation operator sync (Registry -> EventStore, internal only)
# ---------------------------------------------------------------------------

async def find_operator_row(db, op_id, spiffe_id, own_domain: str = ""):
    """§TRUSTROW (2026-09-16, his word "1. approved"): a peer's row, found by the identity it VOTES with first and by
    the licence id second.

    The vote weight resolves a voter by its SPIFFE id (services/federation_governance.py:70-90, whose caller passes
    `auth_context.get("spiffe_id") or operator_id or "origin"`), while the registry's trust sync keys its refresh by the
    licence id this frame issued. A SPIFFE URI never equals a UUID, so the two never met. Measured on the live stores
    2026-09-16: EU held TWO rows for one peer frame, the measured 0.974 on the licence-keyed one and the Beta(1,1) prior
    on the spiffe-keyed one the vote reads; ASIA held no row at its licence id at all, so every refresh fell into the
    insert branch below and answered 400 for want of a hash the sync never sends. Asking by identity first puts the
    value on the row that is read. An operator, whose single row carries both, is unaffected.

    2026-10-17: never by this frame's own bare trust domain (es_auth.shared_domain_id), which every operator of the frame
    shares: the registry's trust sync sent it for each of them, so the row that first carried it took every one's update.
    An operator's row is found by its own identity or by its licence id.
    """
    if spiffe_id and not shared_domain_id(spiffe_id, own_domain):
        result = await db.execute(
            select(FederationOperator)
            .where(FederationOperator.spiffe_id == spiffe_id)
            .order_by(FederationOperator.created_at.asc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            return row
    result = await db.execute(select(FederationOperator).where(FederationOperator.id == op_id))
    return result.scalar_one_or_none()


@router.post("/operators/sync", dependencies=[Depends(require_origin_auth)])
async def sync_federation_operator(
    operator_data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Sync federation operator from Registry. Only this frame's own services (origin) may call it: require_origin_auth,
    the internal key or a service certificate of this frame's own trust domain through its TLS terminator (§SOVKIT T5:
    behind the store's mTLS sidecar the registry's sync arrives as mtls with operator "origin").

    The Registry calls this when a federation license is created, updated, or
    revoked, and its SF-5B trust sync refreshes each licensed peer's
    bayesian_discount here.

    SEC-20 (2026-10-17, his decision: the trust value "has to be dervied in a meaningful way. setting it manually
    doesnt make sense to me"): bayesian_discount is the weight the federation vote multiplies an agent vote by
    (services/federation_governance.cast_federation_vote). This frame's own registry derives it from what it measured of
    each peer itself (its services/bayesian_trust.py: clean settlements raise it, lost disputes lower it, inactivity
    pulls it toward 0.5) and is the only writer. Every other caller (an operator of this frame, a peer frame's service, a
    registered federation operator, a licence key) is refused 403 by require_origin_auth before this handler reads or
    writes anything, whatever its payload. Before, such a caller could still set any record's trust value from 0 to 1,
    its own included, and with it the weight of its own registry's votes (59e7548 had narrowed it to that one field).
    The value itself is a number from 0 to 1 whoever sends it (422, nothing written). Measured before (2026-10-17, every
    running store, 30 minutes): every call here came from the frame's own registry, as origin, so no caller loses a
    write it made.

    2026-05-04: switched from standalone X-Internal-Key check to verify_event_auth, so operators (which carry
    per-license keys, not the shared INTERNAL_API_KEY) could refresh bayesian_discount here; SEC-20 ends that.
    """
    op_id = operator_data.get("id")
    op_name = operator_data.get("operator_name")
    license_key_hash = operator_data.get("license_key_hash")

    # license_key_hash is the IDENTITY ANCHOR for an operator (Commander 2026-04-27).
    # Required on INSERT (must be the real SHA-256 of the operator's plain license key).
    # OPTIONAL on UPDATE — trust-sync calls (bayesian_discount refresh) and SPIFFE-only
    # admin updates legitimately leave it absent. Treat absent/empty/None as "do not
    # touch" to avoid clobbering the real hash with a placeholder.
    if not op_id or not op_name:
        raise HTTPException(
            status_code=400,
            detail="Missing required fields: id, operator_name",
        )

    # SF-5B: bayesian_discount, derived by this frame's own registry from its PeerRegistry trust metrics. Held to the
    # range it is derived in, before anything is read or written (es_auth.trust_value_ok).
    bayesian_discount = operator_data.get("bayesian_discount")
    if bayesian_discount is not None and not trust_value_ok(bayesian_discount):
        raise HTTPException(status_code=422, detail="bayesian_discount must be a number from 0 to 1")

    raw_spiffe = operator_data.get("spiffe_id")
    spiffe_id = str(raw_spiffe).strip() if raw_spiffe else None

    # 2026-10-17 (his word: "no operator accepted without record ... record must exist first"): the identity a row
    # carries is the operator's record (es_auth.row_names_operator). The registry's trust sync sent every operator of
    # this frame the frame's BARE trust domain; the lookup below found the row that first carried it and this handler
    # overwrote its identity, so one row per frame took every same-domain operator's update (name flipping, identity
    # the bare domain) and those operators lost their record. That id names no single operator: it neither finds a row
    # nor is written, and the row is found by its licence id. A sync from a registry that still sends it changes
    # nothing but the name and trust value of the licence's own row.
    own, _own_source = own_trust_domain(os.getenv("ES_OWN_TRUST_DOMAIN"), os.getenv("CERT_DIR", "/certs"))
    if spiffe_id and shared_domain_id(spiffe_id, own):
        logger.warning(f"[operators/sync] spiffe_id {spiffe_id} ignored for {op_id} ({op_name}): this frame's bare trust "
                       f"domain names no single operator; the row is found by its licence id and keeps its identity")
        spiffe_id = None

    # Upsert: the peer's own row, by the identity it votes with first and the licence id second (§TRUSTROW).
    existing = await find_operator_row(db, op_id, spiffe_id, own)

    if existing:
        if spiffe_id and spiffe_id.lower() != (existing.spiffe_id or "").strip().lower():
            # A row's identity decides which operator it records, like the licence hash: never onto another operator
            # (es_auth.sync_identity_refusal). Only origin reaches this handler (require_origin_auth).
            refusal = sync_identity_refusal(existing.spiffe_id, spiffe_id, own)
            if refusal:
                logger.warning(f"[operators/sync] REFUSED spiffe_id {spiffe_id} for {op_id} ({op_name}) on the row "
                               f"carrying {existing.spiffe_id}: {refusal}")
                raise HTTPException(status_code=409, detail=f"spiffe_id not changed: {refusal}")
        # Update mutable fields. license_key_hash is the identity anchor —
        # only overwrite when the caller explicitly supplies a non-empty value.
        existing.operator_name = op_name
        if license_key_hash:
            existing.license_key_hash = license_key_hash
        existing.status = operator_data.get("status", existing.status)
        existing.max_events_per_minute = operator_data.get(
            "max_events_per_minute", existing.max_events_per_minute
        )
        if spiffe_id:
            existing.spiffe_id = spiffe_id
        if bayesian_discount is not None:
            existing.bayesian_discount = float(bayesian_discount)
        await db.commit()
        logger.info(f"Updated federation operator: {op_id} ({op_name})" + (f" spiffe={spiffe_id}" if spiffe_id else "") + (f" trust={bayesian_discount}" if bayesian_discount is not None else "") + (f" hash_updated" if license_key_hash else " hash_preserved"))
        return {"status": "updated", "operator_id": op_id}
    else:
        # Insert new operator — license_key_hash is required for INSERT.
        if not license_key_hash:
            raise HTTPException(
                status_code=400,
                detail="license_key_hash is required when creating a new federation operator",
            )
        new_op = FederationOperator(
            id=op_id,
            operator_name=op_name,
            license_key_hash=license_key_hash,
            status=operator_data.get("status", "active"),
            max_events_per_minute=operator_data.get("max_events_per_minute", 1000),
            spiffe_id=spiffe_id,
            bayesian_discount=float(bayesian_discount) if bayesian_discount is not None else NO_RECORD_TRUST,
        )
        db.add(new_op)
        await db.commit()
        logger.info(f"Created federation operator: {op_id} ({op_name})" + (f" spiffe={spiffe_id}" if spiffe_id else ""))
        return {"status": "created", "operator_id": op_id}


# ─── SF-4: Event Export (for cross-frame replication) ─────────────────────
@router.get("/export", response_model=List[Event])
async def export_events(
    since: Optional[str] = Query(
        None,
        description="ISO timestamp — return events after this time. Legacy "
                    "cursor; vulnerable to Kafka-async-persistence race. Prefer "
                    "since_seq for new callers."
    ),
    since_seq: Optional[int] = Query(
        None,
        description="Monotonic seq cursor — return events with seq > since_seq. "
                    "Race-free under Kafka-async persistence (Round-4 fix). "
                    "When provided, takes precedence over `since`. Order is by "
                    "seq ASC (commit order)."
    ),
    limit: int = Query(100, ge=1, le=1000),
    event_type: Optional[str] = Query(
        None,
        description="Optional event_type filter — used by reactor polling backstop "
                    "to fetch only events of interest. Backwards-compatible: existing "
                    "SF-4 callers omit it and get all event types."
    ),
    db: AsyncSession = Depends(get_db),
    auth: Dict = Security(verify_event_auth),
):
    """Export events for cross-frame replication.

    Called by remote frames' replication daemons to fetch new events.
    Auth: mTLS (SPIFFE SVID), X-Internal-Key, or X-Federation-License.

    Cursor modes:
    - `since_seq` (preferred, Round-4): monotonic INSERT-time cursor. Race-free
      because `seq` is set by the DB sequence at commit time, so events can
      never be skipped due to `timestamp` ordering vs commit ordering races
      under Kafka-async persistence.
    - `since` (legacy timestamp): kept for backwards compatibility with SF-4
      replicators predating Round 4. Will skip events whose timestamp predates
      a watermark that has already advanced past them.
    """
    from datetime import datetime as _dt, timezone as _tz
    from ..models.db_models import EventModel

    if since_seq is None and since is None:
        raise HTTPException(400, "Provide either `since_seq` (preferred) or `since`")

    if since_seq is not None:
        # Round-4 monotonic cursor path
        stmt = select(EventModel).where(
            EventModel.seq.is_not(None), EventModel.seq > since_seq
        )
        if event_type:
            stmt = stmt.where(EventModel.event_type == event_type)
        stmt = stmt.order_by(EventModel.seq.asc()).limit(limit)
    else:
        # Legacy timestamp path
        try:
            since_dt = _dt.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"Invalid timestamp: {since}")
        stmt = select(EventModel).where(EventModel.timestamp > since_dt)
        if event_type:
            stmt = stmt.where(EventModel.event_type == event_type)
        stmt = stmt.order_by(EventModel.timestamp.asc()).limit(limit)

    result = await db.execute(stmt)
    events = result.scalars().all()

    return [
        Event(
            id=str(e.id),
            event_type=e.event_type,
            aggregate_id=e.aggregate_id,
            aggregate_type=e.aggregate_type,
            data=e.data,
            metadata=e.event_metadata or {},
            timestamp=e.timestamp.isoformat(),
            version=e.version,
            source_service=e.source_service,
            idempotency_key=e.idempotency_key,
            seq=e.seq,
        )
        for e in events
    ]


# ─── SF-4: Foreign Events Query ──────────────────────────────────────────
@router.get("/foreign", response_model=List[Dict])
async def get_foreign_events(
    frame_id: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    event_type: Optional[str] = Query(
        None,
        description="Optional event_type filter — used by reactor polling backstop."
    ),
    db: AsyncSession = Depends(get_db),
    auth: Dict = Security(verify_event_auth),
):
    """Query foreign events replicated from other frames.

    2026-05-02: Auth widened from `verify_internal_key` to `verify_event_auth`
    so the reactor polling backstop running on federated operators can read
    foreign events using its X-Federation-License credential, the same auth
    method the registry's event_emitter already uses for POST /events.
    """
    from ..models.db_models import ForeignEventModel

    query = select(ForeignEventModel)
    if frame_id:
        query = query.where(ForeignEventModel.frame_id == frame_id)
    if since:
        from datetime import datetime as _dt
        try:
            since_dt = _dt.fromisoformat(since.replace("Z", "+00:00"))
            query = query.where(ForeignEventModel.timestamp > since_dt)
        except ValueError:
            pass
    if event_type:
        query = query.where(ForeignEventModel.event_type == event_type)
    query = query.order_by(ForeignEventModel.timestamp.asc()).limit(limit)

    result = await db.execute(query)
    events = result.scalars().all()
    return [
        {
            "id": str(e.id),
            "frame_id": e.frame_id,
            "source_event_id": str(e.source_event_id),
            "event_type": e.event_type,
            "aggregate_id": e.aggregate_id,
            "data": e.data,
            "timestamp": e.timestamp.isoformat(),
            "replicated_at": e.replicated_at.isoformat() if e.replicated_at else None,
            "verified": e.verified,
        }
        for e in events
    ]


# Debug endpoint removed for production security (was: POST /api/v1/events/debug)