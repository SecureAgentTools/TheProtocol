"""Registry Card v0.3 — card composer.

Builds a complete v0.3 card from system state at serve time.

Composition order (per PLAN_2026-05-21 §3 Phase 2 step list):
  1. Load operator-editable subset from `registry_card.card_json`.
  2. Overlay LOCKED identity.* from env (SPIRE_TRUST_DOMAIN + REGISTRY_NAME).
  3. Overlay DERIVED capabilities.* from env-var snapshot.
  4. Overlay DERIVED federation.* from RegistryEnforcementPolicy + peer counts.
  5. Overlay DERIVED policy.* from LOCKED_PARAMS + BOUNDED_PARAMS + hash.
  6. Overlay DERIVED economic.* from EventStore /projections/supply-audit (cached 30s).
  7. Overlay DERIVED fees.fee_collector_address from TEG /teg/fees/config (LIVE — do NOT hardcode).
  8. Overlay DERIVED stats.* from cheap DB counts (cached 60s).
  10. Overlay LOCKED lifecycle.* (served_at = now), recompute card_etag.
  11. Apply SOVEREIGN_VISUAL_PINS for sovereign-frame SPIFFE IDs (Phase 6).
  12. Attach signature.* via registry_card_signer (Phase 6).

Per CLAUDE.md PART 1 rule 13: this module makes HTTP calls to TEG + EventStore
for live economic data — it does NOT touch balance tables directly.

NB: do NOT add `from __future__ import annotations` here — same reason as
serve_well_known_card (FastAPI handler introspection). See
feedback_serve_well_known_card_pattern.md.
"""
import asyncio
import datetime
import hashlib
import json
import logging
import os
import re
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from .developer_population import a_developer_of_this_registry
from ..es_ssl_helper import get_httpx_verify
from ..config import settings
from ..core.base_network_params import BOUNDED_PARAMS, LOCKED_PARAMS

logger = logging.getLogger(__name__)


# Spec §0 row 4: canonical 8 bounded params surfaced in the card.
_CANONICAL_BOUNDED_PARAM_KEYS = (
    "transaction_fees.base_rate_percent",       # LOCKED today, may move
    "transaction_fees.max_rate_percent",        # LOCKED today
    "transaction_fees.velocity_scaling_factor", # LOCKED today
    "staking_rewards.max_apy_percent",          # LOCKED today
    "enforcement.reputation_bond_min_avt",      # BOUNDED
    "enforcement.bond_maturity_min_age_days",   # BOUNDED
    "governance.standard_quorum_percent",       # BOUNDED
    "governance.standard_pass_percent",         # BOUNDED
)


# Simple in-process cache for derived blocks. Cache keys are stable per-worker,
# so all workers refresh independently; that is fine because lifecycle.served_at
# is NOT in the canonical ETag inputs (per feedback_agent_card_pullsync_worker.md
# gotcha #3 — per-worker divergence is acceptable for time-varying fields, but
# the canonical signed fields MUST stay stable).
_CACHE: Dict[str, Tuple[float, Any]] = {}
_CACHE_TTL_ECONOMIC = 30.0   # seconds — supply-audit
_CACHE_TTL_FEES = 60.0       # TEG fee config
_CACHE_TTL_STATS = 60.0      # DB counts


def _cache_get(key: str, ttl: float) -> Optional[Any]:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    timestamp, value = entry
    if time.monotonic() - timestamp > ttl:
        return None
    return value


def _cache_set(key: str, value: Any) -> None:
    _CACHE[key] = (time.monotonic(), value)


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# ---------------------------------------------------------------------------
# v0.4 ETag — operator-edits-only (shared by full build + cheap-serve 304)
# ---------------------------------------------------------------------------

def _policy_hash(resolved_doc: Optional[Dict[str, Any]]) -> str:
    """sha256 over the RESOLVED policy document — shared by federation block + ETag.

    §FRAMEPOLICY (2026-09-11): this used to hash `policy_row.policy_json if
    policy_row else {}`. Measured on EU and ASIA, neither of which has ever had
    a policy row: the signed card published sha256("{}") =
    44136fa3... while /federation/policy-compliance published
    sha256(DEFAULT_POLICY_JSON) — ONE frame, TWO hashes for ONE policy, and the
    card's described a document the frame was not running. Both peers published
    the same empty-document hash, so a peer-to-peer policy comparison compared
    nothing with nothing and matched every time.

    The hash now comes from services.frame_policy.policy_hash over the resolved
    document, which is the same function the compliance endpoints call. The
    'sha256:' prefix is the card's shape and is kept; the endpoints publish the
    bare hex, which is the shape the poller has always compared.
    """
    from .frame_policy import policy_hash as _fp_hash
    return "sha256:" + _fp_hash(resolved_doc or {})


def _frame_currency() -> str:
    """Cross-Frame FX (2026-06-02): frame-scoped settlement currency. Frame-level
    property via FRAME_CURRENCY env (default AVT). Frame A = AVT; Frame B = JDAY; Frame C = BVT.
    Sourced (not hardcoded) so the card declares its frame's currency; signed +
    in the ETag basis so a change is tamper-evident + invalidates cross-frame caches."""
    return (os.getenv("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"


def _fee_commitments() -> Dict[str, Any]:
    """The (stable) fee-commitment values that participate in the ETag.

    All constants — NO HTTP — so the cheap-serve path can compute the ETag without
    calling TEG. Must mirror the constant rate values _build_fees_block emits. The
    intra-registry rates are not here: the card publishes the ones the fee service
    charges (_charged_intra_rates), which come from the frame's policy document, and
    the policy hash in the same basis already changes with that document.
    """
    return {
        "xr":         0.5,    # cross_registry.base_rate_percent (cross_teg/protocol.py)
        "host_en":    False,  # hosting.enabled (beta default)
        "host_rate":  0.0,    # hosting.rate_percent_of_agent_service_fee
        "ccy":        _frame_currency(),
    }


# The derived fields this builder adds on its own (the founding date, the software licence row) are not in the
# operator subset the ETag hashes, so a change to how they are derived bumps this revision: every peer re-reads once.
# 3 (§DOCSFIX, 2026-10-16): the fee block states what the fee service charges and the FX caps by the codes the engine
# applies; capabilities.bridge_capability follows the bridge's own switch; federation.uptime_started_at falls back to
# the founding date, never a fixed one; an UNKNOWN supply publishes no numbers; a regulated action declared without
# a scope publishes the scope the gate applies.
_BUILDER_REV = 3
SOFTWARE_LICENCE = "AGPL-3.0-or-later"
_FOUNDED_AT_CACHE: Optional[str] = None


async def _founded_at_fallback(db: AsyncSession) -> Optional[str]:
    """When the operator has not stated identity.founded_at: the created_at of this registry's first account (the
    standup's frame admin, the same source as the operator block's operator_since). One read per process; the
    value cannot move once a registry has an account. None on a registry with no account yet."""
    global _FOUNDED_AT_CACHE
    if _FOUNDED_AT_CACHE is None:
        first = (await db.execute(select(func.min(models.Developer.created_at)))).scalar_one_or_none()
        if first is not None:
            if first.tzinfo is None:
                first = first.replace(tzinfo=datetime.timezone.utc)
            _FOUNDED_AT_CACHE = first.isoformat()
    return _FOUNDED_AT_CACHE


def _with_software_licence(commitments: Dict[str, Any]) -> Dict[str, Any]:
    """The software licence is a fact about the code this registry runs, not an operator promise, so a commitments
    block that states other things but not this one still carries it (EU's and ASIA's cards left the row empty
    while their operators' cards said AGPL-3.0-or-later). An operator's own value wins; nothing else is filled."""
    if commitments.get("open_source_license"):
        return commitments
    return {**commitments, "open_source_license": SOFTWARE_LICENCE}


def _id_subset(identity: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The stable identity fields that participate in the ETag (excludes software_version).

    §DOCSFIX CB-426: federation_base_url joins them. It is derived from the environment (BILATERAL_PEER_URL), it is
    the address a peer federates through, and a changed address behind an unchanged tag stayed on every peer's copy."""
    identity = identity or {}
    return {k: identity.get(k) for k in (
        "spiffe_id", "registry_name", "trust_domain", "tier",
        "display_name", "public_url", "founded_at", "did_namespace", "federation_base_url",
    )}


def _etag_from_basis(
    operator_card: Optional[Dict[str, Any]],
    identity_subset: Dict[str, Any],
    policy_hash: Optional[str],
    stock_digest: Optional[str] = None,
    solvency_epoch_token: Optional[str] = None,
    market_epoch_token: Optional[str] = None,
    jurisdiction_token: Optional[str] = None,
    licence_token: Optional[str] = None,
) -> str:
    """The single ETag definition. Operator-edits-only: hashes the operator-editable
    subset + stable LOCKED fields (identity, policy_hash, fee commitments). Excludes
    ALL volatile data (economic/stats, active_peer_count, peer roster, every *_at) so
    the etag changes only on an operator edit or a stable LOCKED-input change.

    §2026-06-17 — `stock_digest` folds the AGORA catalog digest into the exchange
    fingerprint so an add/delist/rename bumps lifecycle.card_etag → peers re-pull
    (same lever as fx/exchange). Catalog-only digest (excludes live fields) → no
    churn on trades. None on non-venue registries (signal absent).

    §2026-06-22 (P4) — `solvency_epoch_token` folds ONLY a COARSE solvency signal
    (`se:<floor(checked_at/300)>|x3:<ix3_ok>`) — deliberately NOT the live solvency
    digest. The solvency digest moves on every balance change; folding it raw would
    re-pull every peer on every trade (the OWL24 churn the spec forbids). The coarse
    token bumps the ETag at most once per 5-min epoch OR on an ix3 OK→breach flip, so
    a solvency shift still propagates to peers without per-tick thrash. None on
    non-venue / solvency-flag-off (signal absent)."""
    basis = {
        "v":           "0.6",
        "builder":     _BUILDER_REV,
        "op":          operator_card or {},
        "id":          identity_subset,
        "policy_hash": policy_hash,
        "fees":        _fee_commitments(),
        "fx":          _fx_etag_fingerprint(),
        "exchange":    (_exchange_etag_fingerprint()
                        + "|sc:" + (stock_digest or "")
                        + "|sv:" + (solvency_epoch_token or "")
                        + "|mk:" + (market_epoch_token or "")),
        # 2026-07-31: the jurisdiction declaration is an ATTESTATION on this card, so a
        # change to it must invalidate peer + body caches immediately. It is a hash of a
        # rarely-edited document (not live data), so it cannot cause OWL24-style churn.
        "jurisdiction": jurisdiction_token or "",
        # §FEDLICENCE (2026-09-28): the licence state and hashes (network + operator), so a rotation, a revocation or a
        # verdict change is never hidden behind a 304 (services/federation_licence.etag_token; BOTH etag paths).
        "licence": licence_token or "",
        # §DOCSFIX CB-426: the capabilities block (SIGNED whole) and the SPIRE bundle endpoint are derived from the
        # environment like the FX and market fingerprints above, so a switch flipped at a recreate (the bridge, the
        # euro lane, a ZKP phase, a new bundle address) answered 304 and every peer kept the old signed values.
        # Pure env reads: the cheap 304 path computes them exactly as the full build does.
        "caps":     _build_capabilities_block(),
        "spire":    _spire_bundle_endpoint() or "",
    }
    canonical = json.dumps(basis, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _stock_card_digest(db: AsyncSession) -> Optional[str]:
    """AGORA catalog digest for the ETag basis (P2). Venue-only (gated EXCHANGE_ENABLED)
    so non-venue registries never pay the SELECT. Fail-safe: any error → None, so the
    ETag path is never broken by the exchange schema."""
    if (os.getenv("EXCHANGE_ENABLED", "false") or "false").strip().lower() not in ("1", "true", "yes", "on"):
        return None
    try:
        from .stock_card_builder import stock_card_digest_and_count
        digest, _count = await stock_card_digest_and_count(db)
        return digest
    except Exception as e:
        logger.debug("[RegistryCardBuilder] stock-card digest failed: %s", e)
        return None


# --- P4 (2026-06-22) AGORA Solvency Card federation link --------------------
# The solvency card advertises a LINK on the federated registry card so peers can
# fetch+verify a venue's signed solvency attestation cross-frame (reuses the V0107
# fanout-carry — no new transport). CRITICAL FRESHNESS RULE: the solvency digest
# changes on EVERY balance move, so it must NOT enter the registry-card ETag basis
# (that would re-pull every peer on every trade — the OWL24 churn lesson). The
# *link's* `digest`/`as_of` are display-only; only a COARSE token (5-min epoch +
# ix3_ok flag) is folded into the ETag, so peers re-pull at most every 5 min OR on
# an OK→breach flip — never per tick. Consumers wanting LIVE solvency fetch the
# well-known card directly (its own ETag is the full live digest).
_SOLVENCY_EPOCH_SECONDS = 300  # 5-minute coarse bucket for the ETag fold
_CACHE_TTL_SOLVENCY = 45.0     # derived-link cache (build the unsigned card at most ~once/45s)


def _solvency_card_link_enabled() -> bool:
    """Double-gated like the well-known route: venue (EXCHANGE_ENABLED) AND the P4
    flag (EXCHANGE_SOLVENCY_CARD_ENABLED, default OFF). The link stays absent — and
    the coarse epoch stays out of the ETag — until both are on (consumers skip)."""
    ex = (os.getenv("EXCHANGE_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes", "on")
    sc = (os.getenv("EXCHANGE_SOLVENCY_CARD_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes", "on")
    return ex and sc


def _solvency_epoch(as_of: Optional[str]) -> Optional[int]:
    """floor(checked_at_unix / 300) — the coarse 5-min bucket. Parses the ISO-8601
    `checked_at` compute_invariants stamps. None when unparseable (the ETag then
    omits the epoch component rather than thrash)."""
    if not as_of:
        return None
    try:
        ts = datetime.datetime.fromisoformat(str(as_of))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.timezone.utc)
        return int(ts.timestamp()) // _SOLVENCY_EPOCH_SECONDS
    except Exception:
        return None


async def _solvency_link_data(db: AsyncSession) -> Optional[Dict[str, Any]]:
    """Cached derived solvency-link data: {digest, as_of, epoch, ix3_ok, count}.

    Venue+flag-gated (returns None otherwise → link absent, ETag unaffected). Builds
    the UNSIGNED solvency card (no keystore) to read digest + as_of + venue.ix3, then
    caches the small derived dict ~45s so composing the registry card doesn't run a
    full solvency computation on every serve. Fail-safe: any error → None."""
    if not _solvency_card_link_enabled():
        return None
    cached = _cache_get("solvency_link", _CACHE_TTL_SOLVENCY)
    if cached is not None:
        return cached
    try:
        from .solvency_card_builder import build_solvency_card
        # sign=False → no keystore round-trip; we only need digest/as_of/venue here.
        card = await build_solvency_card(db, sign=False)
        venue = card.get("venue") or {}
        as_of = card.get("as_of")
        data = {
            "digest":  card.get("digest"),
            "as_of":   as_of,
            "count":   card.get("count"),
            "epoch":   _solvency_epoch(as_of),
            "ix3_ok":  venue.get("ix3"),  # bool|None — the venue escrow invariant
        }
        _cache_set("solvency_link", data)
        return data
    except Exception as e:
        logger.debug("[RegistryCardBuilder] solvency-link data failed: %s", e)
        return None


async def _solvency_epoch_token(db: AsyncSession) -> Optional[str]:
    """COARSE solvency token for the ETag basis (P4) — `se:<epoch>|x3:<bool>`, NOT
    the live digest. Changes at most every 5 min OR on an ix3 OK→breach flip, so a
    solvency shift propagates to peers without per-tick churn. None on non-venue /
    flag-off (signal absent). Derives from the same ~45s-cached link data."""
    data = await _solvency_link_data(db)
    if not data:
        return None
    return "se:" + str(data.get("epoch")) + "|x3:" + str(data.get("ix3_ok"))


def _market_epoch_token() -> Optional[str]:
    """COARSE market token for the ETag basis (§2026-06-25 Federated Market Card) —
    `mk:<epoch>` where epoch = floor(now / MARKET_EPOCH_SECONDS). NOT the live market
    digest (folding that would re-pull every peer on every trade — the OWL24 lesson).
    Pure time-based + query-free, so it is safe on the compute_serve_etag 304 path.
    None on non-venue / market-flag-off (signal absent → ETag unaffected)."""
    try:
        from .stock_card_builder import market_enabled, market_epoch
        if not market_enabled():
            return None
        return "mk:" + str(market_epoch())
    except Exception:
        return None


async def compute_serve_etag(db: AsyncSession) -> str:
    """CHEAP path for the well-known 304 short-circuit — NO economic/stats/peer
    queries, NO TEG/ES HTTP, NO sign. Reads the singleton row + the active policy
    only (+ a small catalog digest on venues). Produces the identical etag the full
    build will embed in lifecycle.card_etag."""
    row = (await db.execute(
        select(models.RegistryCard).where(models.RegistryCard.id == 1)
    )).scalar_one_or_none()
    operator_card = row.card_json if (row and isinstance(row.card_json, dict)) else {}
    identity = _build_identity_block(operator_card, founded_fallback=await _founded_at_fallback(db))  # cheap: one cached read
    from .frame_policy import load as _load_frame_policy
    ph = _policy_hash((await _load_frame_policy(db)).doc)
    sc_digest = await _stock_card_digest(db)
    sv_token = await _solvency_epoch_token(db)  # P4: coarse epoch only (NOT live digest)
    mk_token = _market_epoch_token()            # §2026-06-25: coarse market epoch (NOT live digest)
    ju_token = await _jurisdiction_etag_token(db)
    from . import federation_licence as _fl
    try:
        lic_block = await _fl.card_block(db, is_operator=_is_operator_registry(), for_card=True)
    except Exception:  # noqa: BLE001 — the SAME fallback the full build puts on the card, so the two etags agree
        lic_block = {"state": "unverified", "hash": None}
    lic_token = _fl.etag_token(lic_block)
    return _etag_from_basis(
        operator_card, _id_subset(identity), ph,
        stock_digest=sc_digest, solvency_epoch_token=sv_token, market_epoch_token=mk_token,
        jurisdiction_token=ju_token, licence_token=lic_token,
    )


def _compliance_token(profile_hash: Optional[str], auth_digest: Optional[str]) -> Optional[str]:
    """ONE token shape for the compliance material in the ETag basis, used by BOTH
    etag paths (compute_serve_etag and build_registry_card) so the served card's
    embedded etag and the cheap 304 path can never diverge. None when neither a
    profile nor a live authorization exists (signal absent)."""
    if not profile_hash and not auth_digest:
        return None
    return f"{profile_hash or ''}|ra:{auth_digest or ''}"


async def _jurisdiction_etag_token(db: AsyncSession) -> Optional[str]:
    """Compliance token (declared profile hash + live regulatory-authorizations
    digest) for the ETag basis, or None when neither exists. Recording/revoking an
    authorization turns the card ETag (and the signed lifecycle.card_etag) over —
    both are rare operator acts, so no churn risk. Fail-safe: any error yields
    None so the ETag path is never broken by the compliance layer."""
    ph: Optional[str] = None
    ad: Optional[str] = None
    try:
        from . import jurisdiction as _juris
        prof = await _juris.get_profile(db, fresh=True)
        ph = _juris.profile_hash(prof) if prof else None
    except Exception as e:
        logger.debug("[RegistryCardBuilder] jurisdiction etag token failed: %s", e)
    try:
        from . import regulatory_auth as _regauth
        auths = await _regauth.active_card_authorizations(db)
        ad = _regauth.authorizations_digest(auths) if auths else None
    except Exception as e:
        logger.debug("[RegistryCardBuilder] regauth etag token failed: %s", e)
    return _compliance_token(ph, ad)


# ---------------------------------------------------------------------------
# Identity / capabilities / endpoints — pure-derivation helpers
# ---------------------------------------------------------------------------

def _build_spiffe_id() -> str:
    """spiffe://<trust_domain>/registry/<name>, the name the card publishes (federation_name()).

    §MEMBERSHIP (V0560, his word 2026-10-03 "do the one more place left"): this was settings.REGISTRY_NAME, which on a
    cloud operator is its container label, so the card key of sbxbetaop was spiffe://sandbox-b.theprotocol.cloud/registry/
    cloud-op-sbxbetaop while its card, SVID and parent's row say sbxbetaop. A frame is unchanged (it sets no
    REGISTRY_FEDERATION_NAME). On an operator the change is a KEY MIGRATION, deliberate: the keystore is keyed by this
    string, so the first signature after it mints a new key under the new kid; the old key keeps no expiry and stays in
    /.well-known/registry-jwks.json (every unexpired key is published), so everything it signed (cards cached by peers,
    cross-frame contract messages, agent card signatures, recorded ballots) still verifies. The card's asset slug moves
    with it and self-heals (normalize_card_asset_url, _ensure_card_assets_on_disk)."""
    trust_domain = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")
    return f"spiffe://{trust_domain}/registry/{federation_name()}"


def card_asset_slug() -> str:
    """URL-safe directory slug for this registry's card assets.

    Derived from the SPIFFE id, which carries the registry NAME — so this value
    MOVES when the registry is renamed. Anything that stores it must be
    normalised at serve time (see `normalize_card_asset_url`), never frozen.
    Collapses anything outside [A-Za-z0-9._-] to '-' because the name may
    contain spaces and `/static/.../Hetzner Frame/icon.png` is not fetchable.
    """
    raw = _build_spiffe_id().replace("spiffe://", "").replace("/", "_")
    return re.sub(r"[^A-Za-z0-9._-]", "-", raw)


#: `/static/registry-cards/<slug>/<file>` — the slug segment is group 2.
_ASSET_URL_RE = re.compile(r"^(/static/registry-cards/)([^/]+)(/[^/]+)$")


async def _ensure_card_assets_on_disk(db, *urls: Optional[str]) -> None:
    """Self-heal: an advertised asset whose file is gone gets rewritten from the
    durable DB copy.

    The static dir is a serving CACHE that a rebuild, a recreate, or a botched
    dist swap can empty (2026-08-10: a `mv` across a bind mount took two
    operators' logos with it). Startup rehydration already covers a boot; this
    covers a card served by a container that is already up. Costs one `stat`
    per advertised asset in the common case and never raises: a missing logo
    must not break the card.
    """
    wanted = [u for u in urls if u and _ASSET_URL_RE.match(str(u))]
    if not wanted:
        return
    try:
        from ..main import STATIC_DIR  # late import: circular at module load
        missing = [u for u in wanted
                   if not (STATIC_DIR / str(u).replace("/static/", "", 1)).is_file()]
        if not missing:
            return
        from ..routers.admin_registry_card import rehydrate_card_assets
        restored = await rehydrate_card_assets(db)
        logger.warning(
            "[RegistryCard] %d advertised asset(s) missing from the static dir "
            "(%s); rehydrated %d from the durable copy.",
            len(missing), ", ".join(missing), restored,
        )
    except Exception as e:  # noqa: BLE001 — never break a card over a logo
        logger.debug("[RegistryCard] asset self-heal skipped: %s", e)


def normalize_card_asset_url(url: Optional[str]) -> Optional[str]:
    """Re-point a stored asset URL at the CURRENT asset slug.

    Upload freezes `/static/registry-cards/<slug-at-upload-time>/icon.png` into
    the card row, while the file itself is written and rehydrated to a slug
    derived live from the registry name. Rename the registry and the two drift:
    the file follows, the advertised URL does not, and the card points at a 404
    until someone re-uploads. Measured on hetzner-frame 2026-07-29 (21 x 404).

    Only rewrites URLs that match our own same-origin asset shape; an absolute
    URL, an unexpected shape, or None is returned untouched.
    """
    if not url:
        return url
    m = _ASSET_URL_RE.match(str(url))
    if not m:
        return url
    return f"{m.group(1)}{card_asset_slug()}{m.group(3)}"


def _public_web_url() -> str:
    """Browser-reachable public URL for the card's `public_url` (the FE 'full
    card' / well-known link).

    §2026-06-15 — `PUBLIC_URL` carries the `:fed_port` (the nginx-federation
    mTLS port, `port_base+43`) for cloud-ops. A browser cannot reach that port
    (mTLS-required → SSL handshake error). The browser-reachable card is served
    on :443 by the per-op HOST nginx vhost (`{slug}.op.theprotocol.cloud` /
    `{slug}.frame-b.theprotocol.cloud`). So strip any explicit port from
    `PUBLIC_URL` → the :443 web URL. Mainframes (PUBLIC_URL has no port) and any
    already-portless value pass through unchanged. Regressed in §pass69.4 when
    `public_url` started sourcing from `PUBLIC_URL` env (which includes the port).
    """
    pu = (os.environ.get("PUBLIC_URL") or "").strip()
    if pu:
        m = re.match(r"^(https?://[^/:]+)(?::\d+)?(/.*)?$", pu)
        if m:
            return m.group(1) + (m.group(2) or "")
        return pu
    return f"https://{os.environ.get('SPIRE_TRUST_DOMAIN', 'agentvault.com')}"


def _build_tier() -> str:
    """sovereign-mainframe | regional-mainframe | cloud-operator | sandbox | standalone.

    §pass73 (2026-05-26) — sandbox-A and sandbox-B are full sovereign mainframes
    in their own trust tier (own SPIRE trust domain, own EventStore, own economy,
    own bilateral peer). They must self-report as `sovereign-mainframe` so the
    5-signal `useMainframe` composable opens mainframe-gated views; the sandbox
    string check below is preserved as the fallback for other test-flavored
    container names (legacy fixtures, ad-hoc test stacks) that lack
    IS_CENTRAL_REGISTRY=true.
    """
    name = (settings.REGISTRY_NAME or "").lower()
    is_central = (os.environ.get("IS_CENTRAL_REGISTRY", "false").lower() == "true")
    # §TIERFLAG (2026-09-04) — THE FLAG IS THE DECLARATION; THE NAME LIST WAS A
    # ROSTER, AND ROSTERS GO STALE WHILE STILL SOUNDING CONFIDENT.
    #
    # This used to require membership in a hardcoded six-name allowlist IN
    # ADDITION to the flag, so a sovereign frame the list had never heard of was
    # silently demoted. Measured on the two fresh sandbox frames: both set
    # IS_CENTRAL_REGISTRY=true and both have everything the docstring above calls
    # a sovereign mainframe — own SPIRE trust domain, own EventStore, own
    # economy, own bilateral peer — and both published `tier: sandbox`, because
    # their REGISTRY_NAME is the DISPLAY name "Sandbox Alpha", which the
    # `"sandbox" in name` fallback below then caught. Five federation tests read
    # that tier and failed; the tier was wrong, not the tests.
    #
    # ⚠ ADDITIVE BY CONSTRUCTION, verified before changing it rather than after:
    # only a node that explicitly declares IS_CENTRAL_REGISTRY=true is affected,
    # and every node that already answers `sovereign-mainframe` still does.
    # Live census 2026-09-04 — flag TRUE on registry-a, frame-b, frame-c,
    # registry-test{,-b,-c} (all already in the old allowlist, so unchanged) and
    # on sbx-alpha/sbx-beta (the two this fixes). UNSET on all 13 cloud-ops, so
    # no operator can be promoted by it. Nothing is demoted.
    #
    # The substring fallbacks stay for test-flavoured stacks that lack the flag.
    if is_central:
        return "sovereign-mainframe"
    # ⚠ OPERATOR BEFORE SUBSTRING. These two were the other way round, so a
    # cloud operator whose NAME merely contains "test" or "sandbox" was published
    # as tier `sandbox` in its SIGNED registry card. Measured live 2026-09-04:
    # `qatest16` — a real Frame-A cloud operator — advertised `tier: sandbox`,
    # while `op-berlin` and `sbxalphaop`, structurally identical, said
    # `cloud-operator`. The only difference was four letters in the name. Being
    # an operator is STRUCTURAL (`op-` prefix / `cloud-op` container naming);
    # a substring anywhere in a free-text name is the weakest possible evidence
    # and must not outrank it.
    if name.startswith("op-") or "cloud-op" in name:
        return "cloud-operator"
    if name.startswith("registry-test") or "test" in name or "sandbox" in name:
        return "sandbox"
    if os.environ.get("STANDALONE_MODE", "false").lower() == "true":
        return "standalone"
    return "regional-mainframe"


def federation_name() -> str:
    """The name this registry is known by in the federation: its card's identity.registry_name, its SPIFFE path and its
    parent's peer row. A cloud operator's REGISTRY_NAME is its container label ("cloud-op-op-tokyo", for cache keys,
    redis channels and seeds); REGISTRY_FEDERATION_NAME carries the canonical name ("op-tokyo"). A mainframe sets only
    REGISTRY_NAME. ONE rule for every surface that names this registry to a peer (§MCPTEST30, V0559: the federal
    ballot named the label, and an operator's own parent refused its ballot)."""
    return os.environ.get("REGISTRY_FEDERATION_NAME") or settings.REGISTRY_NAME


def _build_identity_block(operator_card: Dict[str, Any], *, include_internal: bool = False,
                          founded_fallback: Optional[str] = None) -> Dict[str, Any]:
    trust_domain = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")
    # §pass66 — Path 3 / Bug A. Single source of truth for deploy tag.
    # Same helper that cloud_provisioner uses to pin VERSION= in .env.operator,
    # so a fresh cloud-op pulls exactly the tag the parent reg is on.
    from agentvault_registry.core.registry_identity import get_software_version
    # §pass69.5 (2026-05-24) — Cloud-ops set REGISTRY_NAME to the Docker
    # container name (e.g. "cloud-op-op-tokyo") for internal use (cache keys,
    # redis channels, DB seeds). The CARD's published registry_name MUST be
    # the canonical federation name (e.g. "op-tokyo") from REGISTRY_FEDERATION_NAME.
    # Mismatched names made fanout receivers store duplicate peer rows under the
    # Docker name, overshadowing the canonical "op-X" rows in topology display.
    # Mainframes don't set REGISTRY_FEDERATION_NAME so fall back to REGISTRY_NAME.
    _federation_name = federation_name()
    # §DIDWIDEN item 1: the issuer namespace this registry mints agent DIDs under (= its trust domain).
    # Absent while DID_ISSUER_NAMESPACE is unset; peers verify it against the SVID-proven trust domain.
    try:
        from agentvault_registry.identifiers import registry_issuer as _registry_issuer
        _did_ns = _registry_issuer()
    except Exception:  # noqa: BLE001 — a malformed value refuses boot elsewhere; never breaks the card
        _did_ns = None
    ident = {
        "spiffe_id": _build_spiffe_id(),
        "registry_name": _federation_name,
        "display_name": operator_card.get("display_name") or _federation_name,
        "trust_domain": trust_domain,
        # §pass69.4 (2026-05-24) — REMOVED the operator_card.public_url fallback.
        # On cloud-ops, operator_card is the PARENT FRAME's card, so this fallback
        # made every cloud-op falsely advertise its parent frame's URL as its own
        # public_url (e.g., op-tokyo → https://frame-b.theprotocol.cloud). That
        # poisoned federation_sync fanout and tripped Frame-B's sovereign defense
        # because fetching the bad URL returned Frame-B's own card. The correct
        # value MUST come from PUBLIC_URL env var (set per-cloud-op by
        # cloud_provisioner.py and .env.operator). Last-resort fallback is the
        # own trust_domain — still not externally-routable for cloud-ops, but at
        # least it's NOT a sibling's URL.
        "public_url": _public_web_url(),
        # §FRAMELIC (2026-09-07, findings row 154) — PUBLISH THE ADDRESS A STRANGER CAN DIAL.
        # `FEDERATION_BASE_URL` answers "how do I reach my own federation endpoint from
        # inside this stack" — it is a docker name (`http://eu-nginx-federation:8443`) and
        # it is used as such for container-to-container dispute callbacks and the
        # self-echo guard. Publishing it on a SIGNED card answered a different question
        # with the same string: a peer reading EU's card to learn how to federate got an
        # internal hostname over http.
        #
        # MEASURED: EU and ASIA each learned the other's two cloud operators through the
        # registry-card fan-out, could not derive a federation address from the card, fell
        # back to the 443 console (`https://shenzhen.op.theprotocol.cloud`), and never
        # synced from them — `last_synced_at` NULL, four `peer_url_misconfigured` drift
        # events, exactly the cause the drift monitor names in its own comment ("landing on
        # the public-cert nginx which doesn't do ssl_verify_client → 401"). Same family as
        # §LOCTRUTH: a value true in one context, published where it reads as another fact.
        #
        # `BILATERAL_PEER_URL` is the public mTLS address the standup already sets and
        # validates (https, and refused if it is the plain 443 console), so prefer it and
        # keep the internal value as the fallback for stacks that set neither. Both pass the
        # same filter: the standup's validation is not the only writer. The frame template
        # rendered the retired sandbox tier's http://agentvault_registry_test:8000, so every
        # runner-built frame signed that docker name (agentvault2-09 2026-10-15, fixed at the
        # template in the stack's 6febb66; a card does not trust its carrier either).
        "federation_base_url": federation_base_url(),
        # The operator's own statement wins. Unstated, the card says when THIS registry came into being (its first
        # account, the standup's frame admin: _founded_at_fallback), never the network's founding date: a frame born
        # in September is not six months old. The literal is left only for a registry with no account at all.
        "founded_at": (operator_card.get("identity", {}).get("founded_at")
                       or founded_fallback
                       or "2026-03-18T00:00:00+00:00"),
        "tier": _build_tier(),
        # §2026-05-30 (Commander decision) — publish the deploy tag on the PUBLIC
        # card so peers/operators/auditors can see what code a registry runs.
        # Sourced from get_software_version() = IMAGE_TAG env -> BUNDLED_IMAGE_TAG.
        # Unsigned + excluded from the ETag identity subset, so it never churns
        # the signature or the cheap-304 path.
        "software_version": get_software_version() or None,
    }
    if _did_ns:
        ident["did_namespace"] = _did_ns
    return ident


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")


def _build_capabilities_block() -> Dict[str, Any]:
    """DERIVED — snapshot of env-var capability flags. Operator cannot lie."""
    from ..core.legacy_surfaces import surface_enabled
    fiat_providers: List[str] = []
    if _env_bool("FIAT_ONRAMP_ENABLED"):
        if _env_bool("STRIPE_API_KEY_PRESENT", True) or os.environ.get("STRIPE_API_KEY"):
            fiat_providers.append("stripe")
        if _env_bool("FIAT_PROVIDER_MOLLIE_ENABLED"):
            fiat_providers.append("mollie")

    zkp_phases: List[int] = []
    for phase in (2, 6):
        if _env_bool(f"ZKP_PHASE_{phase}_ENABLED"):
            zkp_phases.append(phase)

    # v0.4 — curated, peer/buyer-relevant capabilities only. Internal toggles
    # (kafka / astraeus[ripped] / opa / saga_adaptive_conc / canary /
    # revocation_drill / auto_tally / event_store / oauth_token_exchange /
    # routed_fiat_proxy / federation_card_gc / federation_enforcement_active /
    # is_central_registry) and the always-0 supports_event_types are NOT
    # published — they leaked internal architecture and churned the card on
    # every flag flip. See Registry_Card_v0.4.md §5.
    return {
        "federation_enabled":             _env_bool("FEDERATION_ENABLED", True),
        "fiat_onramp_enabled":            _env_bool("FIAT_ONRAMP_ENABLED"),
        "fiat_providers":                 fiat_providers,
        # §2026-06-14 — a central registry IS a sovereign mainframe that mints
        # its OWN frame currency (Frame A=AVT, Frame B=JDAY, Frame C=BVT) on an
        # ongoing basis, not merely a one-time genesis grant. The card already
        # signs `federation.is_sovereign_frame=true` for all three; the old
        # "genesis_only" label contradicted that and read as "can't really mint".
        # Federated cloud-ops still cannot mint → "disabled".
        "minting_capability":             "sovereign" if _env_bool("IS_CENTRAL_REGISTRY") else "disabled",
        # §DOCSFIX CB-277: the bridge's routes are mounted only where TOKEN_BRIDGE_ENABLED is on (main.py asks
        # surface_enabled, as registry-config's token_bridge_enabled does). The card said frame_to_frame on every
        # federated registry, EU's included, where /api/v1/bridge/* is not mounted.
        "bridge_capability":              ("frame_to_frame" if _env_bool("FEDERATION_ENABLED", True)
                                           and surface_enabled("TOKEN_BRIDGE_ENABLED") else "none"),
        "a2a_versions_supported":         ["1.0"],
        "registry_card_versions_served":  ["0.6"],
        "supports_payment_protocol":      ["a2a-payment-v1"],
        "zkp_phases_enabled":             zkp_phases,
    }


# ---------------------------------------------------------------------------
# Federation / policy — DB-derived
# ---------------------------------------------------------------------------

async def _build_federation_block(db: AsyncSession, frame_policy=None) -> Dict[str, Any]:
    """Counts of ACTIVE peers + trust-domain list + license fields."""
    if frame_policy is None:
        from .frame_policy import load as _load_frame_policy
        frame_policy = await _load_frame_policy(db)
    policy_version = frame_policy.version
    policy_modified_at = frame_policy.modified_at

    policy_hash = _policy_hash(frame_policy.doc)

    active_count_row = await db.execute(
        select(func.count(models.PeerRegistry.id))
        .where(models.PeerRegistry.status == "ACTIVE")
    )
    active_count = int(active_count_row.scalar() or 0)

    trust_domains_row = await db.execute(
        select(models.PeerRegistry.trust_domain)
        .where(
            models.PeerRegistry.status == "ACTIVE",
            models.PeerRegistry.trust_domain.is_not(None),
        )
        .distinct()
    )
    # v0.4 — sorted for ETag stability (DISTINCT has no guaranteed order; the
    # unsorted list churned the etag across workers — audit B1).
    trust_domains = sorted(td for (td,) in trust_domains_row.all() if td)

    block: Dict[str, Any] = {
        "protocol_version": "1.0",
        "supported_auth_methods": ["mtls", "jwt_svid", "federation_license"],
        "trust_domains_accepted": trust_domains,
        "spire_bundle_endpoint": _spire_bundle_endpoint(),
        "policy_hash": policy_hash,
        "policy_version": policy_version,
        "policy_updated_at": policy_modified_at.isoformat() if policy_modified_at else None,
        # §FRAMEPOLICY — the THIRD state. policy_version 0 means "never amended",
        # not "unknown"; without this a peer cannot tell a frame running the
        # shipped defaults from one whose policy failed to load.
        "policy_source": frame_policy.source,
        "is_genesis_registry": _env_bool("IS_CENTRAL_REGISTRY"),
        "is_sovereign_frame": _build_tier() == "sovereign-mainframe",
        # §DOCSFIX CB-397: unset, when this registry came into being (its first account, as identity.founded_at),
        # null on a registry with no account; never the network's founding date, which EU and ASIA (founded
        # 2026-09-07) published, six months before either existed
        "uptime_started_at": (os.environ.get("UPTIME_STARTED_AT")
                              or await _founded_at_fallback(db)),
        "active_peer_count": active_count,
        "license_id": os.environ.get("FEDERATION_LICENSE_ID"),
        "license_status": os.environ.get("FEDERATION_LICENSE_STATUS"),
    }

    # §FEDLICENCE (2026-09-28, his word: "display the license hash on the registry card ... a derived field also so it
    # cant be tricked"). DERIVED from the certificates this registry holds and its own last verdict, never from the
    # operator-editable card JSON; its state and hashes are signed leaves and part of the ETag. The certificate rides
    # along so anyone can check the issuer's signature without trusting this card.
    from . import federation_licence as _fl
    try:
        _lic = await _fl.card_block(db, is_operator=_is_operator_registry(), for_card=True)
        if _lic is not None:  # no network configured and nothing held: no block (see federation_licence.configured)
            block["licence"] = _lic
    except Exception as exc:  # noqa: BLE001 — a licence read must never cost the card; the state says what happened
        logger.warning("[RegistryCardBuilder] licence block unavailable: %s", exc)
        block["licence"] = {"state": "unverified", "hash": None, "reason": "the licence block could not be built"}

    # v0.4 — peer roster is OPT-IN (topology privacy). Default: omit the full
    # SPIFFE list; publish only active_peer_count + trust_domains_accepted.
    # Operators who want the transparency set RC_PUBLISH_PEER_ROSTER=true.
    # Dropped vs v0.3: is_fiat_genesis (dupe of capabilities.fiat_*) +
    # license_key_prefix (secret-adjacent, no consumer value).
    if _env_bool("RC_PUBLISH_PEER_ROSTER"):
        peer_rows = await db.execute(
            select(models.PeerRegistry.name, models.PeerRegistry.trust_domain)
            .where(models.PeerRegistry.status == "ACTIVE")
            .limit(64)
        )
        block["trusted_peer_spiffe_ids"] = sorted(
            f"spiffe://{td}/registry/{name}" for name, td in peer_rows.all() if td
        )

    return block


def _build_policy_block(frame_policy=None) -> Dict[str, Any]:
    """THIS FRAME'S DECLARED POSTURE — the rules it actually applies, plus the
    network constants it is pinned to.

    §FRAMEPOLICY (2026-09-11). What this used to do, and why it had to stop:
    for every bounded parameter it published `bounds["min"]` — the LOWEST value
    the network permits — under a comment calling that the operator's chosen
    value and describing itself as standing in until per-registry overrides
    existed. Measured live, EU's signed card therefore told every peer that this frame
    required a 5% quorum and a 40% pass rate. The running code used 10% and 50%,
    and the one frame in the fleet with a real policy document had declared 20%
    since April. Three numbers for one rule, and the one on the signed card was
    the only one nobody had chosen.

    A value invented for legibility must never be written where it is read as
    fact (§LOCTRUTH). The card now publishes what `frame_policy` resolves, and
    says for each entry whether the FRAME set it or whether it is the shipped
    default — because "unset" and "set to the default value" are different facts
    and a peer deciding whether to federate is entitled to both.
    """
    if frame_policy is None:
        # No DB in scope (cheap/synchronous callers): publish the factory
        # default honestly rather than inventing a number.
        from .frame_policy import ResolvedPolicy, resolve
        frame_policy = ResolvedPolicy(doc=resolve(None), version=0,
                                      source="factory_default", _row_json=None)

    # §BAFIN (2026-10-01): a registry whose staking rewards are switched off (core/staking_gate.py) applies no
    # staking rate, so its signed card publishes none. EU and ASIA published max_apy_percent 15.0 here while no
    # staking reward had ever been paid on either. Omitting the entry is schema-valid (declared_params is open).
    from ..core.staking_gate import staking_rewards_enabled
    rewards_on = staking_rewards_enabled()
    declared: Dict[str, Any] = {}
    for key in _CANONICAL_BOUNDED_PARAM_KEYS:
        if key.startswith("staking_rewards.") and not rewards_on:
            continue
        e = frame_policy.explain(key)
        if e["value"] is None:
            continue
        entry: Dict[str, Any] = {"value": e["value"], "source": e["source"]}
        if e["bounds"]:
            entry["allowed"] = e["bounds"]
        declared[key] = entry

    canonical_json = json.dumps(LOCKED_PARAMS, sort_keys=True, separators=(",", ":"))
    locked_hash = "sha256:" + hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    # v0.4 — drift_status / consul_compliance_state are OMITTED until derived
    # from real compliance state (were hardcoded "compliant"/"active" — a
    # quarantined registry would still have claimed compliant). policy_change_history_url
    # dropped (admin-only URL on a public doc).
    return {
        "locked_params_hash": locked_hash,
        "policy_source": frame_policy.source,
        "policy_version": frame_policy.version,
        # Each entry: {value, source: "policy"|"default", allowed: {min,max}}.
        "declared_params": declared,
        # Retained under its v0.4 name for peers that already parse it: same
        # keys, but the frame's REAL values instead of the minimum of the range.
        "bounded_params": {k: v["value"] for k, v in declared.items()},
    }


# ---------------------------------------------------------------------------
# Economic — HTTP to EventStore / TEG (cached)
# ---------------------------------------------------------------------------

def _spire_bundle_endpoint() -> Optional[str]:
    """The public SPIRE bundle endpoint of this frame: EXPLICIT, no default (§EXTREACH, agentvault2-5b, 2026-10-14).

    The card used to fall back to https://<SPIRE_TRUST_DOMAIN>:8443/.well-known/spire-bundle. That path is on the
    federation terminator, which requires a client certificate, so the frame a card is written FOR (one that is not
    federated yet, and so holds no certificate the frame trusts) got 400 "No required SSL certificate was sent":
    measured on EU, ASIA and sandbox-b, where frame-federate.py stops at step 3. And where SPIRE_TRUST_DOMAIN kept
    its legacy default the card named https://agentvault.com:8443, a domain we do not own: a peer following it
    would import a trust bundle from a third party. Same rule as _auditor_endpoint: a claim must be configured.
    Frames set SPIRE_BUNDLE_ENDPOINT to their bundle endpoint (the standup's --bundle-public-url, e.g.
    https://sandbox-a.theprotocol.cloud:8465/); unset, the card names none, and frame-federate.py then asks for
    --peer-bundle-endpoint instead of failing on a wrong address.
    """
    value = (os.environ.get("SPIRE_BUNDLE_ENDPOINT", "") or "").strip()
    return value or None


def federation_base_url() -> Optional[str]:
    """The federation address this registry's card publishes (identity.federation_base_url), the one its peers hold:
    BILATERAL_PEER_URL where a stranger could dial it, else FEDERATION_BASE_URL where one could, else none.
    core/settlement_origin names a cross-registry settlement's origin by this same function (§MCPTEST30 V0639), so
    the card and the settlement cannot name two addresses."""
    return (_dialable_from_outside(os.environ.get("BILATERAL_PEER_URL"))
            or _dialable_from_outside(os.environ.get("FEDERATION_BASE_URL")))


def _dialable_from_outside(url: Optional[str]) -> Optional[str]:
    """`url` when a stranger could dial it, else None (§EXTREACH, 2026-10-14).

    FEDERATION_BASE_URL is the INTERNAL address of the stack's own federation proxy (https://nginx-federation:8443,
    http://eu-nginx-federation:8443): right for container-to-container callbacks, wrong on a signed card a stranger
    reads (findings row 154). BILATERAL_PEER_URL wins when it passes too (since 2026-10-15: runner-built frames set it to
    a docker name, http://agentvault_registry_test:8000); where a stack sets only the internal one (the two sandbox
    operators did, 2026-10-14), the card now names no address rather than a docker name nobody outside can resolve.
    A dialable name has a dot and is not a loopback or private literal.
    """
    import ipaddress
    from urllib.parse import urlsplit
    value = (url or "").strip()
    if not value:
        return None
    try:
        host = (urlsplit(value).hostname or "").lower()
    except ValueError:
        return None
    if not host or "." not in host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return value
    return None if (ip.is_private or ip.is_loopback or ip.is_link_local) else value


def _auditor_endpoint() -> str:
    """The external independent auditor base URL — EXPLICIT OPT-IN, no default.

    §HETZNERLOCK-17 (2026-07-30). This used to default to OUR prod auditor "for
    backward-compat", which meant any frame that never set the env published a
    SIGNED, publicly-served registry card asserting that auditor.theprotocol.cloud
    attests to it. Verified live on the Hetzner frame — a sovereign frame owned by
    someone else was making a cryptographic claim about our auditor auditing it.

    A claim about a third party is not a sane fallback: it must be configured. Our
    own nodes set EXTERNAL_AUDITOR_ENDPOINT explicitly (mainframe compose env, and
    cloud_provisioner inherits it from the parent frame for children), so their
    cards are unchanged; everyone else now correctly asserts nothing.
    """
    return (os.environ.get("EXTERNAL_AUDITOR_ENDPOINT", "") or "").strip()


async def _fetch_supply_audit() -> Dict[str, Any]:
    """Supply-invariant numbers for the economic block (cached 30s).

    2026-05-30 — two-source resolution:
      1. PRIMARY: the external INDEPENDENT auditor's public per-frame endpoint
         (`{EXTERNAL_AUDITOR_ENDPOINT}/api/auditor/latest`), keyed by
         `AUDITOR_FRAME_KEY` (e.g. "frame-a"/"frame-b"). This is reachable by
         FEDERATED cloud-ops where the ES is NOT (the federation mTLS proxy only
         serves federation/cross-teg endpoints, never `/projections/*`), AND it
         is an independent verdict rather than registry self-attestation.
         Gated on AUDITOR_FRAME_KEY so it stays inert until a deployment opts in
         (and until a sandbox auditor exists, sandbox leaves it unset → ES).
      2. FALLBACK: the local EventStore `/projections/supply-audit` (mainframes
         with their own ES; ops can't reach this → returns {} → FEDERATED).
    """
    cached = _cache_get("supply_audit", _CACHE_TTL_ECONOMIC)
    if cached is not None:
        return cached

    data: Dict[str, Any] = {}

    # 1. PRIMARY — external auditor, per-frame (independent, public, op-reachable).
    auditor = _auditor_endpoint()
    frame_key = (os.environ.get("AUDITOR_FRAME_KEY") or "").strip()
    if auditor and frame_key:
        try:
            async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
                resp = await client.get(f"{auditor.rstrip('/')}/api/auditor/latest")
            if resp.status_code == 200:
                j = resp.json()
                fr = j.get(frame_key) if isinstance(j, dict) else None
                if isinstance(fr, dict) and fr.get("tokens_issued") is not None:
                    ed = fr.get("extra_data") or {}
                    data = {
                        "status":                fr.get("status") or "UNKNOWN",
                        "delta":                 fr.get("delta", 0.0),
                        "tokens_issued":         fr.get("tokens_issued"),
                        "total_circulating":     fr.get("total_circulating"),
                        "tokens_destroyed":      ed.get("tokens_destroyed", 0),
                        "tokens_fees_collected": ed.get("tokens_fees_collected", 0),
                        "audited_at":            fr.get("timestamp"),
                        "_source":               "auditor",
                    }
        except Exception as e:
            logger.warning("[RegistryCardBuilder] auditor fetch failed: %s — falling back to ES", e)

    # 2. FALLBACK — local EventStore projection (mainframes only; ops 404 via proxy).
    if not data:
        url = (os.environ.get("EVENT_STORE_URL")
               or os.environ.get("EVENT_STORE_INTERNAL_URL")
               or "http://event-store-test:8200") + "/api/v1/projections/supply-audit"
        try:
            async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
                resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                data["_source"] = "eventstore"
            else:
                logger.warning("[RegistryCardBuilder] supply-audit HTTP %s — returning stub", resp.status_code)
        except Exception as e:
            logger.warning("[RegistryCardBuilder] supply-audit fetch failed: %s — returning stub", e)

    _cache_set("supply_audit", data)
    return data


def _is_federated_operator() -> bool:
    """A federated cloud operator does not issue/own a token supply — minting is
    disabled and the supply invariant is governed at its parent sovereign frame."""
    return (os.environ.get("MINTING_AUTHORITY") or "").strip().lower() == "disabled"


async def _build_economic_block() -> Dict[str, Any]:
    audit = await _fetch_supply_audit()
    auditor = _auditor_endpoint()
    has_data = bool(audit) and audit.get("tokens_issued") is not None

    # #1 (2026-05-30) — FEDERATED, not UNKNOWN, for cloud-ops with no own supply.
    # Honest: a federated op doesn't mint or hold a supply invariant; the parent
    # sovereign frame does (and independently audits it). Avoids the misleading
    # all-zeros "UNKNOWN" that read like a broken/empty registry.
    if not has_data and _is_federated_operator():
        block: Dict[str, Any] = {
            "supply_invariant_status":   "FEDERATED",
            "supply_invariant_delta":    "0.0",
            "supply_last_audited_at":    None,
            "tokens_issued":             None,
            "total_circulating":         None,
            "tokens_destroyed":          None,
            "tokens_fees_collected":     None,
            "supply_note": ("Federated cloud operator: minting is disabled. The supply of "
                            "units is issued, governed and independently audited at the "
                            "parent frame, not at this registry."),
        }
    elif not has_data:
        # §DOCSFIX CB-413: no measurement, no numbers. When the supply read failed the block carried "0" in every
        # term and "0.0" as the delta beside UNKNOWN, while the spec says a registry publishes a measured value or
        # omits it: the terms are null (as on a FEDERATED block) and the delta is left out.
        block = {
            "supply_invariant_status":   "UNKNOWN",
            "supply_last_audited_at":    None,
            "tokens_issued":             None,
            "total_circulating":         None,
            "tokens_destroyed":          None,
            "tokens_fees_collected":     None,
        }
    else:
        # ES/auditor returns: tokens_issued, total_circulating, tokens_destroyed,
        # tokens_fees_collected, delta, status ("OK"|"BREACH"). Block is unsigned
        # + ETag-excluded.
        status = audit.get("status") or audit.get("supply_invariant_status") or "UNKNOWN"
        block = {
            "supply_invariant_status":   status,
            "supply_invariant_delta":    str(audit.get("delta", "0.0")),
            "supply_last_audited_at":    audit.get("audited_at") or audit.get("computed_at") or None,
            "tokens_issued":             str(audit.get("tokens_issued", "0")),
            "total_circulating":         str(audit.get("total_circulating", "0")),
            "tokens_destroyed":          str(audit.get("tokens_destroyed", "0")),
            "tokens_fees_collected":     str(audit.get("tokens_fees_collected", "0")),
        }
        if audit.get("_source"):
            block["supply_source"] = audit["_source"]  # "auditor" (independent) | "eventstore" (self)

    if auditor:
        block["external_auditor_endpoint"] = auditor
    return block


async def _fetch_fee_config() -> Dict[str, Any]:
    """GET /teg/fees/config via the registry's TEG proxy (cached 60s).

    Returns canonical fee_collector_address (NOT hardcoded — see PLAN gotcha #7).
    """
    cached = _cache_get("fee_config", _CACHE_TTL_FEES)
    if cached is not None:
        return cached

    # §pass69 audit fix (2026-05-24) — env var name mismatch (TEG_API_URL ≠
    # compose's TEG_API_BASE_URL). Now reads canonical TEG_API_BASE_URL
    # (post-T1.2 it's https://nginx-teg-a:8443 / https://frame-b-nginx-teg:8443).
    # §pass69.3 (2026-05-24) — fallback was "teg-layer-test:8080" (sandbox-only
    # Docker DNS); cloud-ops resolve "teg-layer" (their TEG sidecar alias).
    # Mainframes set TEG_API_BASE_URL explicitly so this fallback is for
    # cloud-ops where the env var is absent.
    url = (os.environ.get("TEG_API_BASE_URL")
           or os.environ.get("TEG_API_URL")
           or "http://teg-layer:8080") + "/api/v1/token/fees/config"
    try:
        async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
            resp = await client.get(url)
        if resp.status_code == 200:
            data = resp.json()
        else:
            logger.warning("[RegistryCardBuilder] fee-config HTTP %s", resp.status_code)
            data = {}
    except Exception as e:
        logger.warning("[RegistryCardBuilder] fee-config fetch failed: %s", e)
        data = {}

    _cache_set("fee_config", data)
    return data


def _fx_card_block() -> Dict[str, Any]:
    """Cross-Frame FX transparency (P2-4) — UNSIGNED + ETag-excluded (display-only,
    like software_version: NOT in registry_card_signer.SIGNED_CANONICAL_PATHS, and the
    ETag hashes _fee_commitments() not this full block). Publishes THIS frame's live
    swap-booth policy so peers + the AgentWorld UI can read the fee + split + guards
    without a side channel. `fee_split` is THIS frame's policy for trades it HOSTS as
    the destination (the fee lands in this frame's fee_collector); the source frame
    reads this published value and applies it (dest-defined authority — see
    teg_integration._resolve_peer_fx_pool_pct)."""
    enabled = (os.getenv("FX_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes", "on")
    # route_enabled = this registry can ROUTE FX by delegating to an FX-booth gateway
    # (cloud-ops do this via FX_ROUTE_ENABLED; mainframe booths inherently route too). A
    # consumer is FX-CAPABLE iff (enabled OR route_enabled). Publishing it makes the card
    # AUTHORITATIVE for FX capability — not just booth presence — so consumers (IRONHAND
    # cockpit, FE) read the federated card instead of guessing env/trust-domain:
    #   registry-a / frame-c → enabled:true   (FX booths, west + middle-east)
    #   op-paris / op-doha    → enabled:false, route_enabled:true   (west/ME ops, delegate)
    #   frame-b + east ops    → enabled:false, route_enabled:false  (Frame-B is non-FX)
    route_enabled = (os.getenv("FX_ROUTE_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        blk: Dict[str, Any] = {"enabled": False, "route_enabled": route_enabled}
        if route_enabled:
            blk["route_gateway_registry_id"] = (os.getenv("FX_ROUTE_GATEWAY_REGISTRY_ID", "") or "").strip()
        return blk

    def _f(env: str, dflt: str) -> float:
        try:
            return float(os.getenv(env, dflt) or dflt)
        except (TypeError, ValueError):
            return float(dflt)

    def _per_unit(prefix: str) -> Dict[str, float]:
        # §DOCSFIX D6-459/CB-415: keyed by the unit codes the engine applies. routers/teg_integration.py reads
        # <prefix><CODE> for any code (_fx_size_cap, _fx_reserve_floor), so the card publishes this frame's own unit
        # always (0 = no cap, no floor) and every other code the environment sets. It used to publish two fixed
        # entries read from <prefix>AVT and <prefix>BVT: the former network's units on every frame, at 0 on EU and
        # ASIA, and never the cap or floor a frame applies to its own unit.
        own = _frame_currency()
        out = {own: _f(prefix + own, "0")}
        for key in sorted(os.environ):
            code = key[len(prefix):]
            if key.startswith(prefix) and re.fullmatch(r"[A-Z]{2,8}", code):
                out[code] = _f(key, "0")
        return out

    rate_mode = (os.getenv("FX_RATE_MODE", "fixed") or "fixed").strip().lower()
    raw = os.getenv("FX_FEE_POOL_PCT")
    if raw is None or str(raw).strip() == "":
        pool_pct = 100.0 if rate_mode == "pool" else 0.0   # mode default (mirrors _fx_fee_pool_pct)
    else:
        try:
            pool_pct = max(0.0, min(100.0, float(raw)))
        except (TypeError, ValueError):
            pool_pct = 100.0 if rate_mode == "pool" else 0.0
    return {
        "enabled":       True,
        "currency":      _frame_currency(),
        "rate_mode":     rate_mode,
        "fee_pct":       _f("FX_FEE_PCT", "0.5"),
        "fee_split": {
            "pool_retained_pct": round(pool_pct, 6),
            "fee_collector_pct": round(100.0 - pool_pct, 6),
        },
        "route_enabled": route_enabled,
        "size_cap":      _per_unit("FX_SIZE_CAP_"),
        "slippage_max":  _f("FX_SLIPPAGE_MAX", "0"),
        "breaker_pct":   _f("FX_BREAKER_PCT", "0"),
        "reserve_floor": _per_unit("FX_RESERVE_FLOOR_"),
        "note": ("Cross-frame FX swap booth. fee_split is THIS frame's policy for trades it "
                 "hosts as destination; published unsigned (display-only, authoritative for "
                 "swaps the counterparty sources into this frame)."),
    }


def _exchange_card_block() -> Dict[str, Any]:
    """AGORA venue advertisement (§V0064, 2026-06-13) — UNSIGNED + display-layer,
    exactly the `fx` block's contract: env-driven so it needs no DB, ETag-excluded,
    NOT in SIGNED_CANONICAL_PATHS (no signature/version churn — same reasoning as
    software_version). Publishing makes the federated card AUTHORITATIVE for venue
    capability: peers/GCC/Passport homes read `exchange.enabled` off the card
    instead of probing /api/v1/exchange/listings for a 404. Spec addendum:
    PRODUCTION_DOCS/SPECS/Registry_Card_v0.4.md (§exchange)."""
    enabled = (os.getenv("EXCHANGE_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes", "on")
    passport = (os.getenv("EXCHANGE_PASSPORT_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        # passport_enabled still published when dark: a HOME registry can relay
        # its agents to foreign venues without hosting a venue itself.
        return {"enabled": False, "passport_enabled": passport}
    return {
        "enabled":          True,
        "currency":         _frame_currency(),
        "passport_enabled": passport,
        "endpoints": {
            "listings": "/api/v1/agora/listings",
            "order":    "/api/v1/agora/orders",
            "passport_inbound": "/api/v1/federation/agora-order",
        },
        "fee_bps_default":  30,
        "note": ("AGORA organization points market. Points are registry-ledger entries; every money "
                 "leg settles through teg:system:exchange_escrow (supply Δ=0 by construction). "
                 "Foreign agents participate via the DevCard Passport when passport_enabled."),
    }


def _fx_etag_fingerprint() -> str:
    """Compact env fingerprint of the authority-bearing fx fields (enabled / mode /
    fee_pct / fee_split). Folded into the ETag so a fee-split or mode change bumps
    lifecycle.card_etag → the change propagates via the normal ETag-gated federation
    sync (the fx block is signature-EXCLUDED but must still INVALIDATE the cache, else
    peers 304 and never see the new split). Read in BOTH the full build and the cheap
    compute_serve_etag path (both via _etag_from_basis) so the 304 short-circuit stays
    exact. Does NOT change the signed-path SET → no A+B+C lockstep."""
    return "|".join([
        (os.getenv("FX_ENABLED", "") or ""),
        (os.getenv("FX_ROUTE_ENABLED", "") or ""),               # route capability → card.fx.route_enabled
        (os.getenv("FX_ROUTE_GATEWAY_REGISTRY_ID", "") or ""),   # route gateway → card.fx.route_gateway_registry_id
        (os.getenv("FX_RATE_MODE", "") or ""),
        (os.getenv("FX_FEE_PCT", "") or ""),
        (os.getenv("FX_FEE_POOL_PCT", "") or ""),
    ])


def _exchange_etag_fingerprint() -> str:
    """§2026-06-15 — env fingerprint of the authority-bearing AGORA exchange fields
    (enabled / passport / currency) folded into the card ETag so a passport/venue
    flip bumps lifecycle.card_etag → peers re-pull instead of 304-ing on a stale
    card. Same reasoning as _fx_etag_fingerprint: the exchange block is signature-
    EXCLUDED but must still INVALIDATE the federation cache, else peer globe/GCC
    AGORA badges freeze at the old passport state (the gap that left Frame A/B
    showing passport=OFF on peers after the canary→triangle-wide promotion).
    Activates on the next registry image roll (env-only flips already flip each
    frame's OWN served card + env-direct /admin/exchange/overview immediately)."""
    return "|".join([
        (os.getenv("EXCHANGE_ENABLED", "") or ""),
        (os.getenv("EXCHANGE_PASSPORT_ENABLED", "") or ""),
        (os.getenv("FRAME_CURRENCY", "") or ""),
    ])


async def _charged_intra_rates(db: AsyncSession) -> Dict[str, float]:
    """§DOCSFIX CB-103: the intra-registry rates as the fee service charges them, read through its own reader of the
    frame's policy document (TransactionFeeService.get_current_rate), never LOCKED_PARAMS. An admin policy edit or a
    passed policy_change moves the rate charged, and the card printed the network's locked values whatever was
    charged. Whether the network's lock may be changed at all is the compliance check's business (the card keeps
    `locked_by_network`). Read on the shared session, so the caller awaits it before starting concurrent work."""
    from . import transaction_fee_service as _tfs
    try:
        rate = await _tfs.get_transaction_fee_service().get_current_rate(db)
        return {"base_rate_percent": float(rate["base_rate_percent"]),
                "max_rate_percent": float(rate["max_rate_percent"])}
    except Exception as e:  # noqa: BLE001 — the fee service charges its own defaults when it cannot read the policy
        logger.warning("[RegistryCardBuilder] the fee service's rates could not be read (%s); "
                       "publishing its defaults", e)
        return {"base_rate_percent": float(_tfs.DEFAULT_BASE_RATE_PCT),
                "max_rate_percent": float(_tfs.DEFAULT_MAX_RATE_PCT)}


async def _build_fees_block(intra_rates: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    from .transaction_fee_service import FEE_FLOOR_AVT, DEFAULT_BASE_RATE_PCT, DEFAULT_MAX_RATE_PCT
    rates = intra_rates or {"base_rate_percent": float(DEFAULT_BASE_RATE_PCT),
                            "max_rate_percent": float(DEFAULT_MAX_RATE_PCT)}
    fee_cfg = await _fetch_fee_config()
    fee_collector_address = fee_cfg.get("fee_collection_address") or "teg:system:fee_collector"
    return {
        "intra_registry": {
            "base_rate_percent":         rates["base_rate_percent"],
            "max_rate_percent":          rates["max_rate_percent"],
            "velocity_scaling_factor":   LOCKED_PARAMS.get("transaction_fees.velocity_scaling_factor", 1.0),
            "destination":               LOCKED_PARAMS.get("transaction_fees.destination", "treasury_recycle"),
            "customizable":              False,
            "locked_by_network":         True,
        },
        "cross_registry": {
            "base_rate_percent":         0.5,  # Hardcoded at cross_teg/protocol.py:270
            "fee_recipient":             "receiver_registry",
            "customizable":              False,
            "locked_by_network":         True,
            "future_customization_in_bounded_params": [0.1, 2.0],
        },
        "hosting": {
            "enabled":                   False,
            "rate_percent_of_agent_service_fee": 0.0,
            "min_avt":                   "0",
            "applies_to_agent_dids":     None,
            # §DOCSFIX CB-423: the text promised a PUT that cannot set it (the admin PUT has no fees key, and
            # this builder fixes hosting off)
            "description":               "No hosting fee: this registry takes no share of its agents' service fees.",
        },
        "fee_collector_address":         fee_collector_address,
        # §DOCSFIX D6-394: the TEG's funding waterfall knows two sources (endpoints_treasury.DEFAULT_WATERFALL);
        # the label named a third, operator_pull, that does not exist
        "fee_waterfall_policy":          "fee_collector → treasury",
        "settlement_currency":           _frame_currency(),
        "economic_disclosure": {
            "spec_version":              "v0.3",
            # §DOCSFIX D6-458: the floor the fee service applies (FEE_FLOOR_AVT, 0: no minimum fee), not 0.000001; the
            # key keeps its v0.6 schema name
            "fee_floor_avt":             str(FEE_FLOOR_AVT),
            "rounding":                  "ROUND_HALF_EVEN",
            "fees_emit_event_types":     ["TransactionFeeCollected", "CrossRegistryTransferCompleted"],
        },
        "fx":                            _fx_card_block(),
        "exchange":                      _exchange_card_block(),
    }


# ---------------------------------------------------------------------------
# Sovereign agents / stats — DB-derived, cached 60s
# ---------------------------------------------------------------------------

# v0.4 — `_build_sovereign_agents_block` REMOVED. A registry card describes the
# registry, not its agents; agents are discoverable at /api/v1/agent-cards/ +
# /.well-known/agent-card.json. The old block's subdomain derivation was broken
# (bare domain / null / a different personal domain) and every sovereign_variant
# was null. See Registry_Card_v0.4.md §0 + audit §7.4.


async def _build_stats_block(db: AsyncSession) -> Dict[str, Any]:
    cached = _cache_get("stats", _CACHE_TTL_STATS)
    if cached is not None:
        return cached

    from sqlalchemy import text as _t
    agent_total = (await db.execute(select(func.count(models.Agent.id)))).scalar() or 0
    # Federated cards: agent_cards rows where card_data has federation_metadata key.
    # Native = total agent_cards - federated.
    # Use `card_data::jsonb->>'federation_metadata' IS NOT NULL` so the query
    # works on BOTH json (cloud-op DBs) and jsonb (Frame A / sandbox-A DBs).
    # The ? operator is jsonb-only and breaks on cloud-op DBs that still have
    # the original `json` column type.
    federated = (await db.execute(
        _t("SELECT COUNT(*) FROM agent_cards WHERE card_data::jsonb->>'federation_metadata' IS NOT NULL")
    )).scalar() or 0
    card_total = (await db.execute(
        _t("SELECT COUNT(*) FROM agent_cards")
    )).scalar() or 0
    native = max(0, int(card_total) - int(federated))
    sovereign = (await db.execute(
        select(func.count(models.Agent.id))
        .where(models.Agent.flare_tier == "sovereign")
    )).scalar() or 0
    # §NIGHTLYTRUTH-2 (2026-10-11): the developers of this registry, not every row: sandbox-A's card said 2,163 for
    # 1,326 (711 deleted accounts, 126 federation placeholders); services/developer_population.py
    dev_count = (await db.execute(
        select(func.count(models.Developer.id)).where(a_developer_of_this_registry())
    )).scalar() or 0
    peers = (await db.execute(
        select(func.count(models.PeerRegistry.id))
        .where(models.PeerRegistry.status == "ACTIVE")
    )).scalar() or 0

    # v0.4 — real counts only. Dropped the placeholders that shipped as if live:
    # service_agent_count(0), active_disputes(0), active_proposals(0),
    # uptime_pct_30d(99.5), canary_pass_rate_24h(99.5). Re-add only when wired
    # to a truthful source (R2). Block is unsigned + ETag-excluded.
    block = {
        "agent_count":           int(agent_total),
        "native_agent_count":    int(native),
        "federated_agent_count": int(federated),
        "sovereign_agent_count": int(sovereign),
        "developer_count":       int(dev_count),
        "active_peers":          int(peers),
        "computed_at":           _now_utc().isoformat(),
    }
    _cache_set("stats", block)
    return block


# ---------------------------------------------------------------------------
# Master assembly
# ---------------------------------------------------------------------------

def _operator_card_subset(card_json: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Pull operator-editable subset; default to empty dict for greenfield serve."""
    return card_json or {}


def _compute_card_etag(
    card: Dict[str, Any],
    operator_card_json: Optional[Dict[str, Any]] = None,
    stock_digest: Optional[str] = None,
    solvency_epoch_token: Optional[str] = None,
    market_epoch_token: Optional[str] = None,
    jurisdiction_token: Optional[str] = None,
) -> str:
    """v0.4 — operator-edits-only ETag (delegates to _etag_from_basis).

    Hashes ONLY the operator-editable subset + stable LOCKED fields (identity,
    federation.policy_hash, fee commitments) + the AGORA catalog digest + the COARSE
    solvency epoch token (P4 — NOT the live solvency digest). Excludes ALL volatile
    data (economic/stats, federation.active_peer_count, peer roster, every *_at) so
    the etag changes only on an operator edit, a stable LOCKED-input change, a catalog
    add/delist, or a 5-min solvency epoch / ix3-flip → real 304s + stable cross-worker
    signatures."""
    return _etag_from_basis(
        operator_card_json,
        _id_subset(card.get("identity")),
        (card.get("federation") or {}).get("policy_hash"),
        stock_digest=stock_digest,
        solvency_epoch_token=solvency_epoch_token,
        market_epoch_token=market_epoch_token,
        jurisdiction_token=jurisdiction_token,
        licence_token=_licence_token_of(card),
    )


def _licence_token_of(card: Dict[str, Any]) -> str:
    from .federation_licence import etag_token as _lic_etag
    return _lic_etag((card.get("federation") or {}).get("licence"))


def _is_operator_registry() -> bool:
    """§FEDLICENCE: an operator shows the network licence of the frame it rides plus its own operator licence
    (OPERATOR_DID is written by the provisioner on operators only, the same test federation_sync uses)."""
    return bool((os.environ.get("OPERATOR_DID") or "").strip())


def _persona_needs_admin(stored: Dict[str, Any]) -> bool:
    """Whether the operator block needs the admin row: a card nobody edited, or one that lacks "operator since"."""
    return ("developer_id" not in stored and "contact_email" not in stored) or not stored.get("operator_since")


def operator_persona(stored: Optional[Dict[str, Any]], admin: Any) -> Dict[str, Any]:
    """The operator block before the public sanitising: what the operator set, over the admin's persona.

    The persona fills in a card nobody edited (the operator's own fields WIN, e.g. a same-origin avatar upload, so the
    fallback never wipes them). "operator_since" is not editable (the card PUT forbids it), so it is DERIVED whenever the
    block lacks it: derived only while the stored block had neither developer_id nor contact_email, the first save
    through the card editor (which writes both) dropped it from the published card for good (§FESUITE 2026-10-10,
    lifecycle 87: sbx-beta's card lost it on the suite's first edit; EU, ASIA and sbx-alpha still carried it).
    """
    block = dict(stored or {})
    if admin is None:
        return block
    if "developer_id" not in block and "contact_email" not in block:
        block = {
            **{
                "developer_id": admin.id,
                "display_name": admin.name,
                "bio": getattr(admin, "bio", None),
                "contact_email": admin.email,
                "company": None,
                "url": None,
                "github_url": None,
                "twitter_handle": None,
                "timezone": None,
                "location_label": None,
                "operator_since": admin.created_at.isoformat() if getattr(admin, "created_at", None) else None,
                "operator_avatar_url": None,  # v0.4 — no external hotlink; upload same-origin
                "successor_contact": None,
                "support_contact": None,
            },
            **block,
        }
    if not block.get("operator_since") and getattr(admin, "created_at", None):
        block["operator_since"] = admin.created_at.isoformat()
    return block


async def build_registry_card(
    db: AsyncSession,
    *,
    sign: bool = True,
    include_internal: bool = False,
) -> Dict[str, Any]:
    """Compose a complete v0.6 registry card. include_internal=True adds non-public
    fields (e.g. raw identity.software_version) for the admin/ops view.

    Returns a plain dict ready to be dumped to JSON. Caller is responsible for
    setting HTTP ETag header from `card['lifecycle']['card_etag']`.
    """
    # 1. Operator-editable subset from singleton table.
    row = await db.execute(
        select(models.RegistryCard).where(models.RegistryCard.id == 1)
    )
    rc_row = row.scalar_one_or_none()
    operator_card: Dict[str, Any] = _operator_card_subset(rc_row.card_json if rc_row else None)

    # Build derived blocks. HTTP-bound blocks (economic, fees) can race
    # safely since they don't touch the shared DB session; DB-bound blocks
    # must run sequentially because asyncpg sessions can't multiplex queries
    # without poisoning the transaction on first failure.
    # The fee service's rates are a DB read on the shared session: read before the HTTP-bound tasks start.
    intra_rates = await _charged_intra_rates(db)
    economic_task = asyncio.create_task(_build_economic_block())
    fees_task = asyncio.create_task(_build_fees_block(intra_rates))

    identity = _build_identity_block(operator_card, include_internal=include_internal,
                                     founded_fallback=await _founded_at_fallback(db))
    capabilities = _build_capabilities_block()
    # §FRAMEPOLICY — resolve ONCE and hand the same document to both blocks,
    # so policy.declared_params and federation.policy_hash can never describe
    # two different policies.
    from .frame_policy import load as _load_frame_policy
    frame_pol = await _load_frame_policy(db)
    policy = _build_policy_block(frame_pol)

    # Sequential DB reads on the shared session.
    federation = await _build_federation_block(db, frame_pol)
    stats = await _build_stats_block(db)

    economic = await economic_task
    fees = await fees_task

    # P2 (2026-06-17) — AGORA Stock Card link on the federated card. Venue-only
    # (fees.exchange.enabled ⇔ EXCHANGE_ENABLED). Unsigned/display-layer like the
    # rest of fees.exchange, but `digest` is folded into the ETag (below) so a
    # catalog change re-pulls peers. Catalog-only digest → no churn on trades.
    # Best-effort: a failure leaves the card link absent, never breaks the build.
    sc_digest: Optional[str] = None
    if isinstance(fees.get("exchange"), dict) and fees["exchange"].get("enabled"):
        try:
            from .stock_card_builder import stock_card_digest_and_count
            sc_digest, sc_count = await stock_card_digest_and_count(db)
            _sc_link = {
                "url":        "/.well-known/stock-card.json",
                "digest":     sc_digest,
                "count":      sc_count,
                "updated_at": _now_utc().isoformat(),
            }
            # §2026-06-25 — advertise the COARSE market epoch so a consumer re-fetches
            # the stock card when the sparkline refreshes (the catalog digest is
            # trade-invariant, so it alone would never trigger a market refresh).
            from .stock_card_builder import market_enabled as _mk_en, market_epoch as _mk_ep
            if _mk_en():
                _sc_link["market_epoch"] = _mk_ep()
                _sc_link["market_freshness"] = "epoch"
            fees["exchange"]["stock_card"] = _sc_link
        except Exception as e:
            logger.warning("[RegistryCardBuilder] stock_card link build failed: %s", e)

    # P4 (2026-06-22) — AGORA Solvency Card link on the federated card. Sits beside
    # stock_card; double-gated (venue + EXCHANGE_SOLVENCY_CARD_ENABLED) inside
    # _solvency_link_data. The V0107 fanout-carry then ships this link to peers, so
    # a venue's signed solvency attestation is discoverable cross-frame WITHOUT direct
    # reachability — v1 advertises the LINK only; the peer fetches+verifies the card
    # itself against the origin JWKS (a separate solvency-card fanout-carry is v2). The
    # link carries the live `digest`/`as_of` for display, but ONLY the coarse `epoch`
    # (5-min bucket) + `ix3_ok` enter the ETag (sv_token below) — folding the live
    # digest would re-pull every peer on every balance move (OWL24 churn). Best-effort:
    # a failure leaves the link absent and the ETag unaffected, never breaks the build.
    sv_token: Optional[str] = None
    sv_data = await _solvency_link_data(db)  # ~45s-cached; None unless venue + flag on
    if sv_data and isinstance(fees.get("exchange"), dict) and fees["exchange"].get("enabled"):
        fees["exchange"]["solvency_card"] = {
            "url":      "/.well-known/solvency-card.json",
            "digest":   sv_data.get("digest"),
            "as_of":    sv_data.get("as_of"),
            "epoch":    sv_data.get("epoch"),   # floor(checked_at/300) — coarse freshness, what the ETag folds
            "count":    sv_data.get("count"),
            "freshness": "epoch",               # the LINK is coarse; fetch the card directly for live solvency
        }
        sv_token = "se:" + str(sv_data.get("epoch")) + "|x3:" + str(sv_data.get("ix3_ok"))

    # Operator persona — falls back to Developer row for the registry owner.
    operator_block = dict(operator_card.get("operator") or {})
    admin = None
    if _persona_needs_admin(operator_block):
        dev_row = await db.execute(
            select(models.Developer).where(models.Developer.is_admin.is_(True)).limit(1)
        )
        admin = dev_row.scalar_one_or_none()
    operator_block = operator_persona(operator_block, admin)

    # v0.4 — sanitize the served operator block: never publish the internal
    # developer_id; never publish an external (non same-origin) avatar hotlink
    # (audit §7.0 — a LinkedIn URL with an expiry param was rotting on the card);
    # treat contact_email as opt-in (drop the auto-filled admin login email unless
    # the operator explicitly set one in their saved card).
    operator_block = dict(operator_block or {})
    operator_block.pop("developer_id", None)
    _av = operator_block.get("operator_avatar_url")
    if _av and not str(_av).startswith("/static/"):
        operator_block["operator_avatar_url"] = None
    else:
        # A stored slug goes stale the moment the registry is renamed.
        operator_block["operator_avatar_url"] = normalize_card_asset_url(_av)
    if "contact_email" not in (operator_card.get("operator") or {}):
        operator_block.pop("contact_email", None)

    # 2026-05-30 — publish the operator's geo location (lat/lng + label) on the
    # card so federated peers can place this registry on the AgentWorld globe
    # WITHOUT a cross-origin /agents/locations/operator fetch. That endpoint is
    # unreachable across the federation (the mTLS proxy serves only federation/
    # cross-teg endpoints, and internal/sandbox hostnames aren't browser- or
    # peer-reachable — the server-side fetch SNI-falls-through to the genesis
    # frame and returns the WRONG operator's coords). The card sync is the one
    # channel that reliably reaches the right peer. Same source as
    # /agents/locations/operator (first admin developer). The operator block is
    # UNSIGNED (not in SIGNED_CANONICAL_PATHS) so this does not affect the JWS
    # signature. Operator-set values win (only fill when absent).
    if operator_block.get("latitude") is None or operator_block.get("longitude") is None:
        try:
            _loc = (await db.execute(
                select(
                    models.Developer.latitude,
                    models.Developer.longitude,
                    models.Developer.location_label,
                )
                .where(models.Developer.is_admin.is_(True))
                .order_by(models.Developer.id.asc())
                .limit(1)
            )).first()
            if _loc and _loc.latitude is not None and _loc.longitude is not None:
                operator_block.setdefault("latitude", _loc.latitude)
                operator_block.setdefault("longitude", _loc.longitude)
                if not operator_block.get("location_label"):
                    operator_block["location_label"] = _loc.location_label
        except Exception:
            pass

    # Apply sovereign visual pins (Phase 6 expansion point).
    # MERGE partial operator visual onto defaults so a partial PUT (e.g.,
    # icon upload only sets icon_url) doesn't drop orb_color from the served
    # card — every field in the visual block must always have a value at
    # serve time even when the operator only edited one of them.
    visual_defaults: Dict[str, Any] = {
        "icon_url": None, "icon_etag": None, "icon_size_bytes": None,
        "orb_color": "#00d2d2", "orb_glow_color": "#00ffff",
        "orb_pulse_speed_hz": 1.4, "orb_size_px": 16,
        "halo_enabled": True, "halo_thickness": 1.4,
        "theme": "neural", "sovereign_variant": None,
        "flare_corner_variant": None,
        "flare_encirclement_variant": None,
        "flare_encirclement_overlay": None,
        "schema_compat": "v0.3",
    }
    operator_visual = operator_card.get("visual") or {}
    visual_block = {**visual_defaults, **operator_visual}
    try:
        from ..core.registry_identity import apply_sovereign_visual_pin  # Phase 6
        visual_block = apply_sovereign_visual_pin(identity["spiffe_id"], visual_block)
    except ImportError:
        pass  # Phase 6 not yet wired; operator values win.
    # v0.4 — drop fields removed from the visual body: icon_etag + icon_size_bytes
    # move to HTTP headers; schema_compat is redundant with registry_card_version.
    for _vk in ("icon_etag", "icon_size_bytes", "schema_compat"):
        visual_block.pop(_vk, None)
    # The stored icon_url froze the asset slug at upload time; the file lives at
    # a slug derived live from the registry name. Re-point at serve time so a
    # rename can never leave the card advertising a 404.
    visual_block["icon_url"] = normalize_card_asset_url(visual_block.get("icon_url"))
    await _ensure_card_assets_on_disk(db, visual_block.get("icon_url"),
                                      operator_block.get("operator_avatar_url"))

    description = operator_card.get("description") or (
        f"{identity['display_name']} — TheProtocol federation registry."
    )
    tags = operator_card.get("tags") or []

    links = operator_card.get("links") or {}
    commitments = operator_card.get("commitments") or {
        "data_residency": None,
        "gdpr_compliant": False,
        "incident_disclosure_sla_hours": 72,
        "uptime_sla_pct": 99.0,
        "support_response_hours": 72,
        "deprecation_notice_days": 30,
        "open_source_license": "AGPL-3.0-or-later",
        "breach_disclosure_policy": None,
        "key_rotation_max_days": 90,
        "card_refresh_max_minutes": 5,
        "legally_binding_disclaimer": (
            "Declarations above are operator-stated; receivers may enforce "
            "contractually. Operator commits to disclosed values for 90 days "
            "minimum before reduction."
        ),
    }

    commitments = _with_software_licence(commitments)

    endpoints_block = {
        "openapi_spec":          "/api/v1/openapi.json",
        "agent_discovery":       "/api/v1/agent-cards/",
        # §EXTREACH: a registry serves no agent card of its own (404 on every frame and operator, 2026-10-14), and a
        # card promises only what its own console answers. Agents publish theirs at /.well-known/agent-card.json on
        # THEIR hosts; that is the A2A convention, not an endpoint of this registry.
        "agent_card_well_known": None,
        "topology":              "/api/v1/public/topology",
        "network_stats":         "/api/v1/federation/network-stats",
        "federation_info":       "/api/v1/federation/info",
        "policy_compliance":     "/api/v1/federation/policy-compliance",
        "health_check":          "/api/v1/federation/health-check",
        "registry_card":         "/.well-known/registry-card.json",
        "registry_jwks":         "/.well-known/registry-jwks.json",
        # §EXTREACH: the relative /.well-known/spire-bundle exists only on the federation terminator, behind a client
        # certificate (404 on the console); the endpoint a stranger can read is the configured one, or none.
        "spire_bundle":          _spire_bundle_endpoint(),
        "fee_config":            "/api/v1/teg/fees/config",
        "external_auditor":      _auditor_endpoint() or None,
        "public_status_page":    operator_card.get("endpoints", {}).get("public_status_page"),
    }

    # When the singleton row hasn't been PUT yet, use the registry's founded_at
    # as a stable card_updated_at sentinel — otherwise we'd leak now() into the
    # ETag input on every greenfield serve.
    if rc_row and rc_row.updated_at:
        card_updated_at = rc_row.updated_at.isoformat()
    else:
        card_updated_at = identity.get("founded_at") or "1970-01-01T00:00:00+00:00"

    lifecycle_block = {
        "status":                "active",
        "quarantine_reason":     None,
        "card_updated_at":       card_updated_at,
        "card_etag":             "",  # filled below
        "served_at":             _now_utc().isoformat(),
        "next_card_refresh":     (_now_utc() + datetime.timedelta(minutes=5)).isoformat(),
    }

    # Jurisdiction Profile (SPEC 2026-07-31) — the operator's own declaration of which feature
    # surfaces the law applicable to THEM permits here. Published because a compliance claim that
    # only exists in this deployment's database is not verifiable by anyone: on the signed card it
    # is an attestation peers, the auditor, and the public can check. Absent profile omits the
    # block entirely (no profile declared is a different statement from "everything allowed").
    # Best-effort: a failure must never break card generation.
    compliance_block: Optional[Dict[str, Any]] = None
    try:
        from . import jurisdiction as _juris
        # fresh=True on purpose: card builds are infrequent, but the card is the PUBLIC
        # attestation of the declaration. Serving a stale "no profile" from the request-path
        # cache would publish a claim the operator has already changed, which is the one
        # thing an attestation may not do. Correctness beats a saved DB read here.
        _profile = await _juris.get_profile(db, fresh=True)
        if _profile:
            _jp: Dict[str, Any] = {
                "name":            _profile.get("name"),
                "version":         _profile.get("version"),
                "features_denied": _juris.features_denied(_profile),
                "declared_at":     _profile.get("declared_at"),
                "profile_hash":    _juris.profile_hash(_profile),
                "declared_by":     "operator",
            }
            # REGAUTH (card v0.6): publish WHICH lifecycle acts this deployment
            # declares as requiring state approval (authority/scope/mode only;
            # notes stay private). Part of the same operator attestation.
            _req = _profile.get("requires_authorization")
            if isinstance(_req, dict) and _req:
                # §DOCSFIX CB-412: an entry without a scope publishes the scope the gate applies to it
                # (regulatory_auth.declared_scope), not 'registry' whatever the action
                from .regulatory_auth import declared_scope as _declared_scope
                _jp["regulated_actions"] = {
                    a: {"authority": (e or {}).get("authority"),
                        "scope": _declared_scope(a, e or {}),
                        "mode": (e or {}).get("mode", "shadow")}
                    for a, e in sorted(_req.items()) if isinstance(e, dict)
                }
            compliance_block = {"jurisdiction_profile": _jp}
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("[RegistryCardBuilder] jurisdiction profile block skipped: %s", e)

    # REGAUTH (card v0.6): LIVE recorded regulatory authorizations are public proof
    # in their own right, so they publish even when no profile is declared. The
    # `digest` leaf is recomputable from this block's own bytes and is the ONE
    # compliance path in the v0.6 signed set — tamper coverage without whole-block
    # canonicalization risk (the stock_card.digest pattern). Best-effort: a failure
    # must never break card generation.
    _regauth_digest: Optional[str] = None
    try:
        from . import regulatory_auth as _regauth
        _auths = await _regauth.active_card_authorizations(db)
        if _auths:
            if compliance_block is None:
                compliance_block = {}
            compliance_block["regulatory_authorizations"] = _auths
            _regauth_digest = _regauth.authorizations_digest(_auths)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("[RegistryCardBuilder] regulatory authorizations block skipped: %s", e)
    # §DOCSFIX CB-425: the digest has its own step. Inside the authorization read's try, a read that raised while a
    # profile was declared left a compliance block without its digest: schema-invalid, and its signed leaf null. A
    # block whose digest cannot be computed is not published at all.
    if compliance_block is not None:
        try:
            from .regulatory_auth import compliance_digest as _compliance_digest
            compliance_block["digest"] = _compliance_digest(compliance_block)
        except Exception as e:  # noqa: BLE001 — never break the card; never publish the block without its digest
            logger.warning("[RegistryCardBuilder] compliance block omitted, its digest failed: %s", e)
            compliance_block = None

    card: Dict[str, Any] = {
        "registry_card_version": "0.6",
        "identity":     identity,
        "operator":     operator_block,
        "description":  description,
        "tags":         tags,
        "visual":       visual_block,
        "capabilities": capabilities,
        "fees":         fees,
        "federation":   federation,
        "policy":       policy,
        "economic":     economic,
        "stats":        stats,
        "endpoints":    endpoints_block,
        "links":        links,
        "commitments":  commitments,
        "lifecycle":    lifecycle_block,
    }
    if compliance_block:
        card["compliance"] = compliance_block

    etag = _compute_card_etag(card, operator_card, stock_digest=sc_digest, solvency_epoch_token=sv_token,
                              market_epoch_token=_market_epoch_token(),
                              # Same token shape as _jurisdiction_etag_token (compute_serve_etag
                              # path) — the two MUST stay identical or 304s break.
                              jurisdiction_token=_compliance_token(
                                  (compliance_block or {}).get("jurisdiction_profile", {}).get("profile_hash"),
                                  _regauth_digest))
    card["lifecycle"]["card_etag"] = etag

    if sign:
        try:
            from .registry_card_signer import sign_registry_card  # Phase 6 wires real signing
            card["signature"] = await sign_registry_card(card, db=db)
        except Exception as e:
            logger.warning("[RegistryCardBuilder] sign failed (Phase 6 wire-up pending?): %s", e)
            card["signature"] = None

    return card


__all__ = [
    "build_registry_card",
    "_compute_card_etag",
    "_build_spiffe_id",
    "_build_tier",
]
