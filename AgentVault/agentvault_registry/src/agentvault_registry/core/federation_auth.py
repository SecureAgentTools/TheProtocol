"""Federation Authentication Dependencies

Provides flexible auth for federation endpoints (three modes):
1. Production (HTTPS): mTLS with SPIFFE SVIDs from client certificates
2. Development (HTTP): Shared federation secret + SPIFFE ID header
3. Federated operators: X-Federation-License key (tp_fed_...) validated via DB

Modes are tried in order. First successful auth wins.

OWL18: Created to fix federation sync failure when registries use HTTP internally.
f043: Added federation license key auth for external operators.
"""

import contextvars
import hashlib
import logging
import os
import secrets
from typing import Optional
from urllib.parse import urlparse
from fastapi import HTTPException, Request, status, Depends, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import func, select
from ..core.mtls_auth import get_client_spiffe_id, extract_spiffe_id_from_cert
from ..core.client_ip import is_internal_request

logger = logging.getLogger(__name__)

# §S3BIND: the synthetic identity the licence path (mode 3) produced for THIS request. S3 skips exactly that
# identity (the licence check already bound it to an ACTIVE licence row); a ContextVar is per request task.
_LICENSE_IDENTITY: contextvars.ContextVar = contextvars.ContextVar("federation_license_identity", default=None)

# findings row 195 — a refusal nobody counts is a refusal nobody notices. If some rail we could
# not see does depend on presenting the internal secret from outside, this counter is how it
# announces itself instead of failing silently (the §VITALS rule: attempt and outcome are
# separate clocks). Guarded import: a standalone image without prometheus_client stays unaffected.
try:  # pragma: no cover - import guard
    from prometheus_client import Counter as _Counter

    _EXTERNAL_SECRET_REFUSED = _Counter(
        "registry_federation_external_secret_refused_total",
        "X-Federation-Secret presented by a caller that did not come from inside this host",
    )
except Exception:  # pragma: no cover - prometheus_client absent
    _EXTERNAL_SECRET_REFUSED = None


def _inc_external_secret_refused() -> None:
    if _EXTERNAL_SECRET_REFUSED is not None:
        try:
            _EXTERNAL_SECRET_REFUSED.inc()
        except Exception:  # never let bookkeeping fail an auth decision
            pass

# §pass52 PR-15: spec-side declaration of the three federation auth modes.
# These APIKeyHeader instances surface the relevant header in the OpenAPI
# `security` block for every route that uses federation auth — without
# changing runtime behavior (auto_error=False; the actual auth resolution
# happens inside get_federation_identity below).
_federation_license_scheme = APIKeyHeader(
    name="X-Federation-License",
    description="Federation operator license key (tp_fed_...). Issued via /admin/federation-licenses.",
    auto_error=False,
)
_federation_secret_scheme = APIKeyHeader(
    name="X-Federation-Secret",
    description="Internal cluster shared secret (dev/HTTP only). NOT exposed in production — mTLS is required there.",
    auto_error=False,
)

# Shared federation secret for internal (HTTP) dev mode
# In production, this is not used — mTLS is required
FEDERATION_INTERNAL_SECRET = os.environ.get(
    "FEDERATION_INTERNAL_SECRET",
    ""
)


def internal_secret_verified(request: Request) -> bool:
    """D6-716: did this request present this registry's internal federation secret, from inside this host?

    The terms get_federation_identity's Mode 2 accepts (an internal request, a configured secret, a constant-time match),
    without its side effects, so a middleware may ask it before the route runs. The header's mere presence verifies
    nothing."""
    presented = request.headers.get("X-Federation-Secret")
    if not presented or not FEDERATION_INTERNAL_SECRET or not is_internal_request(request):
        return False
    return secrets.compare_digest(str(presented).encode(), FEDERATION_INTERNAL_SECRET.encode())


async def get_federation_identity(
    request: Request,
    # §pass52 PR-15: spec-side declarations. These don't change runtime
    # behavior — the actual auth happens via the headers below extracted
    # from request — but they surface in OpenAPI as security schemes.
    _license_marker: Optional[str] = Security(_federation_license_scheme),
    _secret_marker: Optional[str] = Security(_federation_secret_scheme),
) -> str:
    """Extract federation peer identity from mTLS, internal secret, or license key.

    Authentication modes (tried in order):
    1. mTLS: Extract SPIFFE ID from client certificate (production)
    2. Internal: Validate X-Federation-Secret header + read X-Federation-SPIFFE-ID (dev)
    3. Federation license: Validate X-Federation-License key against DB (external operators)

    Returns:
        SPIFFE ID string (modes 1-2) or synthetic identity string (mode 3)

    Raises:
        HTTPException 401: If no valid authentication found
        HTTPException 403: If identity is from untrusted domain or license is invalid
    """
    # Mode 1: Try mTLS (client certificate)
    try:
        spiffe_id = await get_client_spiffe_id(request)
        logger.info(f"Federation peer authenticated via mTLS: {spiffe_id}")
        return spiffe_id
    except HTTPException:
        # No client cert — fall through to next mode
        pass

    # Mode 2: Internal federation auth (shared secret + SPIFFE ID header)
    fed_secret = request.headers.get("X-Federation-Secret")
    fed_spiffe_id = request.headers.get("X-Federation-SPIFFE-ID")

    mode2_refusal: Optional[str] = None
    # 🔴 findings row 195 — MODE 2 IS AN INTERNAL RAIL AND MUST ONLY BE REACHABLE FROM INSIDE.
    # It is a SHARED BEARER SECRET whose identity the CALLER declares: the check below reads
    # X-Federation-SPIFFE-ID out of the request and only tests its trust DOMAIN, so one leaked
    # secret authenticates as any identity in a trusted domain — on EU that is both
    # eu.theprotocol.cloud and asia.theprotocol.cloud, i.e. it can impersonate the peer frame.
    # It exists (OWL18) because internal rails talk plain HTTP on the container network, where
    # there is no client certificate; it was never meant to be presentable from the internet.
    # MEASURED 2026-09-07 across four live nodes: 1,414 federation authentications, ALL of them
    # via mTLS — Mode 2 carried none of them, so this gate costs nothing real.
    # ⚠ Deliberately NOT gated on the peer being internal for Mode 1 or Mode 3: a genuine peer
    # arrives through the mTLS lane with the real external address in X-Forwarded-For, so an
    # "internal only" rule would refuse exactly the traffic that should pass.
    if fed_secret and fed_spiffe_id and not is_internal_request(request):
        # `is_internal_request` is the EXISTING predicate for exactly this question (no edge
        # headers AND a private/loopback peer) — reused rather than reinvented, so there is one
        # answer to "did this traverse our edge", not two that can drift apart.
        logger.warning(
            "X-Federation-Secret presented by a NON-INTERNAL caller — refusing the internal rail "
            "(mTLS or a federation license are the credentials for an external peer)"
        )
        _inc_external_secret_refused()
        fed_secret = None
        mode2_refusal = "the internal-secret rail is not reachable from outside this host"

    if fed_secret and fed_spiffe_id:
        # Validate shared secret (P21-001: constant-time compare to prevent timing oracle).
        # Reject when the configured secret is empty so an unauthenticated
        # caller can't authenticate by sending an empty value.
        if not FEDERATION_INTERNAL_SECRET or not secrets.compare_digest(fed_secret, FEDERATION_INTERNAL_SECRET):
            # 🔴 findings row 193 — A WRONG SECRET IS NOT AN ANSWER TO THE WHOLE QUESTION.
            # This used to RAISE, which contradicts this function's own contract twenty lines up
            # ("Authentication modes (tried in order)") and, worse, makes a caller WORSE OFF for
            # presenting a credential it legitimately holds. `_fx_route_delegate` sends
            # X-Federation-Secret whenever it has one — every frame has one, for its OWN cluster —
            # AND X-Federation-License. Against a SOVEREIGN peer the secret cannot match (different
            # cluster, different secret), so Mode 2 refused and the valid licence in Mode 3 was
            # never read. MEASURED LIVE 2026-09-07: EU → ASIA POST /teg/fx/route-hop → 401 "Invalid
            # federation secret" on a call that was carrying a licence, on the leg that had just
            # converted currency. The refusal named the credential that failed instead of the one
            # that was never tried, and it cost an hour because it was precise and confident.
            #
            # ⚠ THIS GRANTS NOTHING. A caller who simply OMITS the secret header already reaches
            # Mode 3 today; falling through only stops punishing a caller for sending it. The
            # secret still authenticates nobody unless it matches, and Mode 3 still has to pass
            # on its own merits.
            logger.warning("Federation internal secret did not match — falling through to license auth")
            mode2_refusal = "internal secret did not match"
        else:
            # Validate SPIFFE ID format (supports cross-frame federation)
            # ⚠ this one still RAISES, deliberately: the secret DID authenticate, so an untrusted
            # trust domain is an AUTHORIZATION refusal about a caller we recognised — not a reason
            # to go looking for a second credential from the same request.
            from ..core.mtls_auth import is_trusted_spiffe_id, refresh_peer_trust_domains, trusted_spiffe_domains
            await refresh_peer_trust_domains()
            if not is_trusted_spiffe_id(fed_spiffe_id):
                logger.warning(f"Federation SPIFFE ID from untrusted domain: {fed_spiffe_id} (trusted: {', '.join(trusted_spiffe_domains())})")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Federation identity from untrusted domain"
                )

            logger.info(f"Federation peer authenticated via internal secret: {fed_spiffe_id}")
            return fed_spiffe_id

    # Mode 3: Federation license key (external operators)
    fed_license_key = request.headers.get("X-Federation-License")
    if fed_license_key:
        identity = await _verify_license_key(fed_license_key, request)
        if identity:
            _LICENSE_IDENTITY.set(identity)
            return identity

    # No valid auth found. Name the modes that were TRIED, so a refusal can never again be
    # precise about one credential while silently having ignored another (findings row 193).
    logger.warning("No federation authentication found (no mTLS cert, no internal headers, no license key)")
    _why = "Federation authentication required (mTLS certificate, internal secret, or federation license)"
    if mode2_refusal:
        _why += f" — the presented internal secret was tried and refused ({mode2_refusal})"
    if fed_license_key:
        _why += " — a license key was presented and did not verify"
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_why)


async def _verify_license_key(key: str, request: Request) -> Optional[str]:
    """Verify a federation license key against the DB.

    Returns a synthetic SPIFFE-like identity string on success,
    or raises HTTPException on failure.
    """
    from ..database import AsyncSessionLocal
    from .. import models
    from sqlalchemy.sql import func

    key_hash = hashlib.sha256(key.encode()).hexdigest()

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(models.FederationLicense).where(
                    models.FederationLicense.license_key_hash == key_hash,
                    models.FederationLicense.status == "active",
                )
            )
            license_obj = result.scalar_one_or_none()

            if not license_obj:
                logger.warning(f"Federation license auth failed: hash prefix {key_hash[:8]}...")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid or revoked federation license",
                )

            # §FEDLICENCE (2026-09-28, found preparing the kit dry run): a FRAME that authenticates with its legacy
            # admission key is still a crossing between two trust domains, so its network licence decides here exactly
            # as on the mTLS lane. get_federation_identity's Mode 1 swallows the licence refusal (a 403) and falls through
            # to this lane, and federation_sync sends X-Federation-License beside its client certificate, so without this
            # a revoked or suspended frame kept every crossing under `enforce`. An operator's key is a login to its own
            # parent (one trust domain): nothing to check.
            if (getattr(license_obj, "licensee_type", None) or "operator") == "frame":
                from .mtls_auth import refresh_peer_trust_domains
                await refresh_peer_trust_domains()   # the verdicts, as fresh as the mTLS lane's (the same TTL)
                refusal = frame_licence_refusal(license_obj.operator_did)
                if refusal:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=refusal)

            # Update usage tracking
            license_obj.last_seen_at = func.now()
            license_obj.event_count = models.FederationLicense.event_count + 1
            await db.commit()

            # Return synthetic identity — matches the pattern expected by
            # require_peer_registry_identity (contains "/service/registry-")
            synthetic_id = f"spiffe://theprotocol.cloud/service/registry-{license_obj.operator_did}"
            logger.info(
                f"Federation peer authenticated via license: operator={license_obj.operator_name}, "
                f"did={license_obj.operator_did}, identity={synthetic_id}"
            )
            return synthetic_id

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying federation license: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="License verification error",
        )


def frame_licence_refusal(licensee_did: Optional[str]) -> Optional[str]:
    """The refusal sentence when the network licence of the frame a legacy key names forbids the crossing, else None.
    A frame's key row names it as spiffe://<trust domain> (frame_invitations._issue_frame_license)."""
    from .mtls_auth import licence_allows
    did = str(licensee_did or "").strip()
    td = did[len("spiffe://"):].split("/", 1)[0].strip().lower() if did.startswith("spiffe://") else ""
    if not td or licence_allows(f"spiffe://{td}/service/registry"):
        return None
    return (f"federation licence required: {td} holds no network licence this frame accepts (its admission key "
            f"authenticates it, the network licence decides the crossing)")


def _norm_slug(s: str) -> str:
    """Normalize an operator name/slug for matching (mirrors cloud_provisioner's safe-name
    semantics: lowercase, non-alnum → '-'). Both the SVID path segment and the license
    row's operator_name pass through this so display-name vs slug drift can't dodge the bite."""
    return "".join(c if c.isalnum() else "-" for c in (s or "").lower()).strip("-")


# 60s verdict cache: (normalized slug) → (denied: bool, checked_monotonic: float).
# Keeps the license bite off the DB for repeated calls from the same operator.
_LICENSE_BITE_CACHE: dict = {}
_LICENSE_BITE_TTL = 60.0


async def _assert_operator_license_not_revoked(spiffe_id: str) -> None:
    """S4 (2026-07-24 wiring audit): make license revoke bite mTLS/secret-authenticated
    operators. Mode-3 (X-Federation-License) already checks status=active on every call;
    an operator authenticating with its SPIRE SVID previously never consulted the license
    table — a REVOKED operator with a still-valid SVID kept full federation access.

    Rule: if ANY FederationLicense row matches this operator identity and NONE of the
    matching rows is active → 403. No matching row (frames, internal registry SVIDs,
    unlicensed test operators) → unchanged behavior. Infrastructure errors fail OPEN —
    the SVID itself already proved trust-domain membership; this is a revocation ratchet,
    not the primary authentication."""
    import time as _time
    try:
        slug = spiffe_id.split("/operator/", 1)[1].split("/", 1)[0]
    except (IndexError, AttributeError):
        return
    nslug = _norm_slug(slug)
    if not nslug:
        return
    cached = _LICENSE_BITE_CACHE.get(nslug)
    now = _time.monotonic()
    if cached and (now - cached[1]) < _LICENSE_BITE_TTL:
        denied = cached[0]
    else:
        from ..database import AsyncSessionLocal
        from .. import models
        try:
            async with AsyncSessionLocal() as db:
                res = await db.execute(select(models.FederationLicense))
                rows = res.scalars().all()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[FED-AUTH] S4 license lookup failed for {spiffe_id}: {e}")
            return
        matching = [
            l for l in rows
            if _norm_slug(getattr(l, "operator_name", "")) == nslug
        ]
        denied = bool(matching) and not any(
            (getattr(l, "status", "") or "").lower() == "active" for l in matching
        )
        _LICENSE_BITE_CACHE[nslug] = (denied, now)
    if denied:
        logger.error(
            f"[FED-AUTH] operator '{slug}' SVID auth DENIED — federation license not active "
            f"(S4 revoke-bites-mTLS)"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator federation license is not active",
        )


def _is_peer_registry_identity(spiffe_id: str) -> bool:
    """True when an (already trust-domain-validated) SPIFFE id names a registry.

    Structure-aware rather than substring-based:
      spiffe://<td>/service/<name>     → <name> tokenised on '-' must include 'registry'
      spiffe://<td>/ns/<ns>/sa/<name>  → same rule applied to <name>
      spiffe://<td>/operator/...       → federated operator registries

    Passes:  registry · registry-a · registry-frame-b · hetzner-frame-registry ·
             central-registry · any /operator/… identity
    Refuses: teg-layer · event-store · any non-registry service in the domain
    """
    try:
        path = urlparse(spiffe_id).path or ""
    except Exception:
        return False
    if "/operator/" in path:
        return True
    segs = [s for s in path.split("/") if s]
    name = None
    if len(segs) >= 2 and segs[0] == "service":
        name = segs[1]
    elif len(segs) >= 4 and segs[0] == "ns" and segs[2] == "sa":
        name = segs[3]
    if not name:
        return False
    return "registry" in name.split("-")


async def require_peer_registry_identity(
    spiffe_id: str = Depends(get_federation_identity)
) -> str:
    """Require a valid peer registry identity (from mTLS, internal secret, or license).

    Validates that the identity represents a valid peer registry.

    Expected identity formats:
    - spiffe://agentvault.com/service/registry-a          (mTLS / internal)
    - spiffe://agentvault.com/service/registry-b          (mTLS / internal)
    - spiffe://agentvault.com/ns/agentvault/sa/registry-* (mTLS)
    - spiffe://agentvault.com/service/central-registry    (mTLS)
    - spiffe://theprotocol.cloud/service/registry-*       (federation license)

    S3 (2026-07-24): the identity is now also BOUND to a peer row when we have the
    data. `peer_registries.spiffe_id` (migration 0127) is stamped at cloud-operator
    provisioning; when an incoming SVID matches a row, that row must be ACTIVE or
    the request is refused. Legacy rows are NULL, so an unstamped fleet keeps
    working and only logs — set FEDERATION_REQUIRE_PEER_SPIFFE_BIND=true to demand
    a stamped, active row (the Commander-scheduled ratchet, once the fleet is
    backfilled). Endpoints with per-peer semantics should still resolve their own
    peer for authorization decisions.
    """
    # 2026-07-29 — this was a substring match on "/service/registry-", so whether a
    # frame could federate at all depended on an ACCIDENT OF NAMING: Frame A passes
    # only because its service is called "registry-a" (the trailing hyphen is
    # load-bearing), frame-b/c because of "registry-frame-b"/"-frame-c". A frame
    # whose registry service is named plain "registry" — which is exactly what the
    # frame-test template emits — matched NOTHING and was refused "Identity is not
    # a valid peer registry" one line after mTLS had authenticated it perfectly.
    # Now the service NAME is tokenised on "-" and must genuinely contain the token
    # "registry". Trust-domain validation already happened upstream; this is the
    # identity CLASS check only.
    is_valid_peer = _is_peer_registry_identity(spiffe_id)

    if not is_valid_peer:
        logger.error(f"Identity does not represent a valid peer registry: {spiffe_id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Identity is not a valid peer registry"
        )

    # S4: a revoked/suspended operator's SVID must stop working at THIS shared gate —
    # one fix, every federation surface (sync, agora relays, blocklist, IRONHAND proxies).
    if "/operator/" in spiffe_id:
        await _assert_operator_license_not_revoked(spiffe_id)

    # S3: bind the identity to an ACTIVE peer row. A licence-authenticated identity is already bound to an ACTIVE
    # licence row by the licence check itself, and no peer row can ever carry its synthetic id (§S3BIND).
    if _LICENSE_IDENTITY.get() == spiffe_id:
        logger.debug(f"[S3] licence-authenticated identity {spiffe_id}: bound by its licence, S3 not applied")
    else:
        await _assert_peer_spiffe_binding(spiffe_id)

    logger.info(f"Validated peer registry: {spiffe_id}")
    return spiffe_id


# ── §S3BIND (2026-09-24) ─────────────────────────────────────────────────────────────────────────────────────────────
# Measured before this: the exact-string match bound nothing on the running cluster. A frame stamps a spiffe_id only
# on its OWN cloud operators' rows, so every call from the peer frame, from the peer frame's operators, from an
# operator's svid-writer, and every licence-authenticated call "matched no stamped peer row" and was allowed with a
# warning: about 4,200 an hour across EU, ASIA and the sandbox pair, and strict mode would have refused all frame-to-frame
# traffic. The row's trust_domain is authoritative (services/spiffe_canonical.py) and every real peer row carries it,
# so the binding is now canonical: a frame's registry SVID (any variant) binds to that trust domain's FRAME row, an
# /operator/<op>/* SVID to the row named <op> in that trust domain, /registry/<name> to the row named <name>. A warning
# names each unbound identity once an hour, with a count of what it held back.

_S3_CACHE: dict = {}          # spiffe_id -> (verdict, checked_monotonic); verdict: "bound" | "inactive" | "unbound"
_S3_CACHE_TTL = 60.0          # a deactivation reaches the canonical path within a minute (S4's licence cache is 60 s too)
_S3_CACHE_MAX = 1024
_S3_WARNED: dict = {}         # (verdict, spiffe_id) -> [last_emitted_monotonic, held_back]
_S3_WARN_WINDOW = 3600.0
_S3_WARNED_MAX = 512


def _s3_warn_once_an_hour(verdict: str, spiffe_id: str, message: str, *args) -> None:
    import time as _time
    key = (verdict, spiffe_id)
    now = _time.monotonic()
    seen = _S3_WARNED.get(key)
    if seen is not None and now - seen[0] < _S3_WARN_WINDOW:
        seen[1] += 1
        return
    held_back = seen[1] if seen is not None else 0
    if seen is None and len(_S3_WARNED) >= _S3_WARNED_MAX:
        _S3_WARNED.pop(next(iter(_S3_WARNED)))
    _S3_WARNED[key] = [now, 0]
    if held_back:
        logger.warning(message + " (%d more like it held back in the last hour)", *args, held_back)
    else:
        logger.warning(message, *args)


def _s3_canonical(spiffe_id: str) -> Optional[tuple]:
    """(trust_domain, kind, name) for a registry-class identity, else None.

    kind "operator": spiffe://<td>/operator/<op>/<component>   (the operator's registry, its svid-writer, ...)
    kind "named"   : spiffe://<td>/registry/<name>             (the Registry Card canonical form)
    kind "frame"   : any other registry-class path in <td>     (/service/registry, /service/<frame>-registry, ...)"""
    try:
        u = urlparse(spiffe_id or "")
    except Exception:
        return None
    if u.scheme != "spiffe" or not u.netloc:
        return None
    td = u.netloc.lower()
    segs = [x for x in (u.path or "").split("/") if x]
    if len(segs) >= 2 and segs[0] == "operator":
        return (td, "operator", _norm_slug(segs[1]))
    if len(segs) == 2 and segs[0] == "registry":
        return (td, "named", _norm_slug(segs[1]))
    if _is_peer_registry_identity(spiffe_id):
        return (td, "frame", "")
    return None


def _s3_canonical_query(canon: tuple):
    from agentvault_registry import models
    td, kind, _name = canon
    q = select(models.PeerRegistry).where(func.lower(models.PeerRegistry.trust_domain) == td)
    if kind == "frame":
        q = q.where(models.PeerRegistry.peer_type == "frame")
    return q


def identity_is_peer_row(spiffe_id: Optional[str], row) -> bool:
    """Is the presented registry identity `spiffe_id` the registry of peer row `row` (of any status)? The row stamped with
    this exact SVID is; otherwise as the S3 binding resolves an identity (_s3_canonical): an operator's identity is the
    row of that name in its trust domain, a frame registry's its trust domain's frame row. A licence identity (Mode 3)
    or a non-registry identity is no row: a route that binds an address to its caller refuses them."""
    if row is None or not spiffe_id:
        return False
    if (getattr(row, "spiffe_id", None) or "") == spiffe_id:
        return True
    if _LICENSE_IDENTITY.get() == spiffe_id:
        return False
    canon = _s3_canonical(spiffe_id)
    if canon is None:
        return False
    td, kind, name = canon
    if (getattr(row, "trust_domain", None) or "").strip().lower() != td:
        return False
    if kind == "frame":
        return (getattr(row, "peer_type", None) or "") == "frame"
    return _norm_slug(getattr(row, "name", "") or "") == name


def is_own_frame_identity(spiffe_id: Optional[str]) -> bool:
    """This frame's own registry: a frame-class registry identity in this registry's own trust domain
    (SPIRE_TRUST_DOMAIN), never a licence identity. An operator of the frame (spiffe://<td>/operator/<name>/...) is
    not."""
    own = (os.environ.get("SPIRE_TRUST_DOMAIN") or "").strip().lower()
    if not own or not spiffe_id or _LICENSE_IDENTITY.get() == spiffe_id:
        return False
    canon = _s3_canonical(spiffe_id)
    return canon is not None and canon[0] == own and canon[1] == "frame"


def _s3_verdict(rows: list, canon: tuple) -> str:
    """bound: an ACTIVE row is this identity; inactive: its rows exist and none is ACTIVE; unbound: no row is it."""
    _td, kind, name = canon
    if kind in ("operator", "named"):
        rows = [r for r in rows if _norm_slug(getattr(r, "name", "") or "") == name]
    if any((getattr(r, "status", "") or "").upper() == "ACTIVE" for r in rows):
        return "bound"
    return "inactive" if rows else "unbound"


async def requester_source_forms(db, spiffe_id: str) -> set:
    """Every SPIFFE form under which a copy of the REQUESTING registry's cards can be recorded here.

    §ECHOFLOOD (2026-10-09, measured on the sandbox): the agent-card feed holds back a relayed card whose recorded
    source is the registry asking for it (OWL24 + OWL30 echo prevention). Since the per-service SVIDs (F5) a frame
    registry presents `spiffe://<td>/service/registry`, which names no registry, so canonical_equals() could not match
    it to the copies recorded under the frame's name (`spiffe://<td>/registry/<name>`, the pull's presenter form):
    4,728 of sbx-alpha's cards on sbxalphaop went back to sbx-alpha on every full read, and sbx-alpha refused each one
    with an OWL24 WARNING (LogWarningStorm). The identity is resolved the way the S3 binding resolves it (the peer ROW
    of that trust domain and kind, never the card), and each row's name becomes a canonical form. The presented id is
    always a form, so a registry we hold no row for keeps the old exact behaviour."""
    forms = {spiffe_id} if spiffe_id else set()
    canon = _s3_canonical(spiffe_id)
    if canon is None:
        return forms
    td, kind, name = canon
    if kind in ("operator", "named") and name:
        forms.add(f"spiffe://{td}/registry/{name}")
    rows = (await db.execute(_s3_canonical_query(canon))).scalars().all()
    if kind in ("operator", "named"):
        rows = [r for r in rows if _norm_slug(getattr(r, "name", "") or "") == name]
    for r in rows:
        row_name = _norm_slug(getattr(r, "name", "") or "")
        if row_name:
            forms.add(f"spiffe://{td}/registry/{row_name}")
        if getattr(r, "spiffe_id", None):
            forms.add(r.spiffe_id)
    return forms


async def _assert_peer_spiffe_binding(spiffe_id: str) -> None:
    """S3: tie an incoming registry identity to an ACTIVE `peer_registries` row.

      * a row carries this exact spiffe_id: it must be ACTIVE, else 403 (unchanged);
      * otherwise the canonical binding (§S3BIND above): an ACTIVE row binds it silently; rows that exist but are all
        INACTIVE, or no row at all, are refused only under FEDERATION_REQUIRE_PEER_SPIFFE_BIND, else a warning once an
        hour per identity;
      * nothing stamped anywhere and no canonical row either: refused under FEDERATION_REQUIRE_PEER_SPIFFE_BIND
        (D6-309), otherwise legacy mode, debug-log only.

    Fail-OPEN on an infrastructure error, deliberately: this gate fronts every federation surface, and a DB blip must
    not sever the corridors. The revoked-licence bite (S4) is the fail-closed half."""
    import time as _time

    strict = (os.getenv("FEDERATION_REQUIRE_PEER_SPIFFE_BIND", "") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    try:
        from agentvault_registry import models
        from agentvault_registry.database import AsyncSessionLocal

        canon = _s3_canonical(spiffe_id)
        verdict: Optional[str] = None
        now = _time.monotonic()
        cached = _S3_CACHE.get(spiffe_id)
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(models.PeerRegistry).where(models.PeerRegistry.spiffe_id == spiffe_id)
            )).scalars().first()

            if row is not None:
                status_val = (row.status or "").upper()
                if status_val != "ACTIVE":
                    logger.error(
                        "[S3] peer SVID %s maps to peer '%s' whose status is %s — refusing",
                        spiffe_id, row.name, status_val or "(none)",
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Peer registry is not active",
                    )
                return

            if canon is not None:
                if cached is not None and now - cached[1] < _S3_CACHE_TTL:
                    verdict = cached[0]
                else:
                    verdict = _s3_verdict((await db.execute(_s3_canonical_query(canon))).scalars().all(), canon)
                    if spiffe_id not in _S3_CACHE and len(_S3_CACHE) >= _S3_CACHE_MAX:
                        _S3_CACHE.pop(next(iter(_S3_CACHE)))
                    _S3_CACHE[spiffe_id] = (verdict, now)
                if verdict == "bound":
                    return

            stamped = (await db.execute(
                select(func.count(models.PeerRegistry.id)).where(
                    models.PeerRegistry.spiffe_id.is_not(None)
                )
            )).scalar() or 0

        # D6-309: the legacy quiet path is for the non-strict mode only. Under strict mode an unbound identity is
        # refused whether or not any row carries a spiffe_id (a frame without its own cloud operators stamps none,
        # and an operator's own rows are never stamped), so the switch means the same on every registry.
        if verdict != "inactive" and stamped == 0 and not strict:
            logger.debug("[S3] no peer rows carry a spiffe_id and no canonical row matched — binding not enforced")
            return

        if strict:
            logger.error("[S3] SVID %s is not bound to an ACTIVE peer row (%s, strict mode) — refusing",
                         spiffe_id, verdict or "not registry-class")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=("Peer registry is not active" if verdict == "inactive"
                        else "Peer identity is not bound to a known registry"),
            )
        if verdict == "inactive":
            _s3_warn_once_an_hour(
                "inactive", spiffe_id,
                "[S3] SVID %s binds only to INACTIVE peer rows — allowing, "
                "set FEDERATION_REQUIRE_PEER_SPIFFE_BIND=true to refuse", spiffe_id)
        else:
            _s3_warn_once_an_hour(
                "unbound", spiffe_id,
                "[S3] SVID %s matches no peer row, exact or canonical (%d rows stamped) — allowing, "
                "set FEDERATION_REQUIRE_PEER_SPIFFE_BIND=true to enforce", spiffe_id, stamped)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("[S3] peer binding check failed (allowing): %s", exc)
