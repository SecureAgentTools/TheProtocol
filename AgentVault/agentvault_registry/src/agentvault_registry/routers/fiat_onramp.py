"""
fiat_onramp.py — Stripe Checkout Fiat → AVT (PB-1).

Implements the canonical PB-1 commitment from
`PRODUCTION_DOCS/ROADMAP/TheProtocol_Business_Model_And_Roadmap.md` Part 6:
user pays EUR via Stripe Checkout → TheProtocol receives EUR via Kontist →
AVT credited to user's agent via existing /admin/reward-fund waterfall.

This is Stripe Checkout / Payment Intents, NOT Stripe Crypto Onramp.
Onramp delivers public-blockchain crypto to user's wallet (wrong product
for an internal utility token). See `feedback_stripe_checkout_not_onramp.md`.

Mainframe-only by construction: federated registries cannot mint AVT, so
they cannot run Stripe→AVT pipes. `FIAT_GENESIS_REGISTRY=false` (the default)
returns 403 on every endpoint here. Use a dedicated env var instead of the
project's `IS_CENTRAL_REGISTRY` (which has different cron-poller semantics).

Master kill switch: `FIAT_ONRAMP_ENABLED=false` returns 503. Sandbox flips
first; production stays `false` until Commander confirms legal review.

Endpoints:
    GET  /api/v1/fiat/tiers                       — public tier breakpoints + min/max
    POST /api/v1/fiat/quote                       — public AVT calc for an EUR amount
    POST /api/v1/fiat/checkout-session            — create Stripe Checkout (logged-in or anon)
    POST /api/v1/fiat/stripe-webhook              — Stripe → us (signature verified)
    GET  /api/v1/fiat/purchase/{session_id}       — public-by-session-id (for success page poll)
    GET  /api/v1/fiat/my-purchases                — dev JWT — caller's purchase history

Admin endpoints (admin_treasury gated):
    GET  /api/v1/admin/fiat/pricing               — current active config + version history
    PUT  /api/v1/admin/fiat/pricing               — install a new config version (atomic)
    POST /api/v1/admin/fiat/pricing/simulate      — pure-math what-if simulation
"""
from __future__ import annotations

import asyncio
import logging
import json
import os
import secrets
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional, List, Tuple, Set, Dict

import hashlib
import httpx
from fastapi import APIRouter, Depends, HTTPException, Header, Request, Response, Security, status
from pydantic import BaseModel, EmailStr, Field
import sqlalchemy as sa
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, security
from ..config import settings
from ..services.legal_acceptance import SUBJECT_CHECKOUT as _SUBJECT_CHECKOUT, record_acceptance as _record_acceptance
from ..database import AsyncSessionLocal, get_db
from ..event_emitter import get_event_emitter
from ..models import (
    Agent,
    Developer,
    FiatPricingConfig,
    FiatPurchase,
    FiatPurchaseStatus,
)
from ..security import get_current_developer_unified, require_admin_flag
from ..services.stripe_checkout import (
    FALLBACK_CONFIG,
    compute_avt_amount,
    create_checkout_session,
    get_active_pricing,
    get_tier_label,
    invalidate_pricing_cache,
    retrieve_session,
    simulate_purchases,
    validate_config,
    validate_eur_amount,
    verify_webhook_signature,
)
# PB-3 (BL-2) W2 — provider abstraction for multi-PSP fiat onramp.
# Strategy: PRODUCTION_DOCS/ROADMAP/Webhook_Fiat_Layer_Strategy.md
from ..services.fiat_providers import FiatProvider, ProviderEvent, ProviderSession
from ..services.fiat_providers.registry import enabled_providers, get_provider
# PB-3 W6 — Prometheus metrics
from ..services.fiat_providers.metrics import (
    inc_idempotent_replay as _inc_idempotent_replay,
    inc_parse_failed as _inc_parse_failed,
    inc_purchase_completed as _inc_purchase_completed,
    inc_purchase_disputed as _inc_purchase_disputed,
    inc_purchase_failed as _inc_purchase_failed,
    inc_purchase_refunded as _inc_purchase_refunded,
    inc_signature_failed as _inc_signature_failed,
    inc_webhook_received as _inc_webhook_received,
    observe_fulfilment_duration as _observe_fulfilment_duration,
)
# 2026-07-27: MODULE-SCOPE on purpose. A later SSL refactor added `verify=get_httpx_verify()`
# to the local-treasury transfer in `_operator_settle_routed_purchase` and to
# `_fund_via_reward_waterfall` (V0599: gone, the direct flow's credit rides services/reward_funding), but the only
# import was function-local inside a THIRD function.
# Both other call sites therefore raised NameError on their hot path, were swallowed by their
# own try/except, and recorded the purchase as FAILED (local_treasury_error / reward_fund_failed).
# Unexercised since 2026-05-10, so no purchases were harmed, but it would have bitten the next
# real one. Found by pyflakes; py_compile passes on undefined names.
from ..es_ssl_helper import get_httpx_verify  # noqa: E402
# §FLARESHOP (2026-08-16) — THE flare grant writer + tier tables live here now.
from ..services import flare_grants as _flare_grants  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/fiat")
admin_router = APIRouter(prefix="/api/v1/admin/fiat")  # §pass56 PR-5: tags via main.py
# PB-2 (2026-05-10): operator-side federation router. Hosts the routed-settle
# callback receiver under `/api/v1/federation/...` because the operator's
# nginx-federation sidecar proxies that prefix (mTLS-terminated). NEVER add
# operator-only routes outside of nginx-federation's allowed prefixes.
federation_router = APIRouter(prefix="/api/v1/federation")  # §pass56 PR-5: tags via main.py


# ----------------------------------------------------------------------
# Founders Wall display sanitization (Migration 0039, 2026-05-10)
# ----------------------------------------------------------------------
# Conservative allowlist: letters (incl. unicode), digits, spaces, basic
# punctuation. URLs are stripped before allowlist filtering. Emoji and
# non-Latin scripts are NOT allowed in display_name to avoid homoglyph
# spoofing of Founder accounts and zero-width / RTL injection on the wall.
# A lone profanity filter would be culture-blind and brittle; for now we
# rely on the char allowlist + admin moderation (TODO: hide_from_wall_admin
# column) to keep the wall presentable.
import re as _re_display

_DISPLAY_URL_RE = _re_display.compile(r'https?://\S+', _re_display.IGNORECASE)
_DISPLAY_ALLOWED_RE = _re_display.compile(r"[^A-Za-z0-9 .\-_'&]")


def sanitize_display_name(raw: Optional[str]) -> Optional[str]:
    """Sanitize a buyer-supplied display_name into a wall-safe handle.

    Pipeline:
      1. None / empty → None
      2. Strip URLs (http://… and https://…)
      3. Drop characters not in the allowlist (letters, digits, spaces,
         . - _ ' &)
      4. Collapse runs of whitespace
      5. Trim + length-cap to 32 chars
      6. Empty after sanitization → None

    Returns the sanitized string or None.
    """
    if not raw:
        return None
    s = _DISPLAY_URL_RE.sub('', raw)
    s = _DISPLAY_ALLOWED_RE.sub('', s)
    s = ' '.join(s.split())   # collapse whitespace
    s = s.strip()[:32]
    return s or None


# ----------------------------------------------------------------------
# Flare cosmetic system (PB-1, 2026-05-09)
# ----------------------------------------------------------------------
# Higher tier wins on multi-purchase: Founder beats Architect beats Sentinel.
# A purchase NEVER downgrades an existing flare. Profile flare is permanent.
# Agent flare can be moved across agents owned by the same developer (cosmetic
# only — no AVT effect, supply invariant unaffected).
# §FLARESHOP (2026-08-16): the tier tables and the grant writer moved to
# `services/flare_grants.py` — the fiat lane is no longer the only origination
# surface (local-currency purchases land in routers/flare_shop.py), and two
# copies of "which tier outranks which" is the §FANOUTFIX class. These names
# are re-exported unchanged so every existing reference in this module (and the
# admin grant validators) keeps working byte-for-byte.
#   sentinel < architect < founder < shadow_chancellor < operator < commander
# Shadow Chancellor sits above Founder so a backer who crosses the cumulative
# threshold gets bumped over their existing Founder flare via _should_overwrite_flare.
# Operator + Commander stay above so admin-granted badges survive backing activity.
_TIER_TO_FLARE = _flare_grants.TIER_TO_FLARE
_FLARE_RANK = _flare_grants.FLARE_RANK
# All valid flare tier values (used to validate admin grant inputs).
ALL_FLARE_TIERS = _flare_grants.ALL_FLARE_TIERS
# Tiers that can ONLY be granted via admin endpoint (never via fiat).
ADMIN_ONLY_FLARE_TIERS = _flare_grants.ADMIN_ONLY_FLARE_TIERS

# Shadow Chancellor cumulative-spend threshold (€). Hidden tier — never on
# the public tier-pitch cards. Auto-grants when sum of COMPLETED FiatPurchase
# rows for a developer crosses this threshold. Color customization is locked
# at the frontend layer (visual is fixed black-glue encirclement); backend
# treats it as just another flare value.
_SHADOW_CHANCELLOR_THRESHOLD_EUR = Decimal(
    os.getenv("SHADOW_CHANCELLOR_THRESHOLD_EUR", "500")
)
# Sentinel-tier purchases (€1-€19) DO NOT count toward the cumulative
# threshold. Sentinel is the entry tier — accumulating €500 of €1 buys
# would game the rare flare. Architect (€20+) and Founder (€100+) purchases
# accumulate. Filter is `amount_eur >= _SHADOW_CHANCELLOR_MIN_EUR_PER_PURCHASE`.
_SHADOW_CHANCELLOR_MIN_EUR_PER_PURCHASE = Decimal(
    os.getenv("SHADOW_CHANCELLOR_MIN_EUR_PER_PURCHASE", "20")
)


def _flare_for_tier(tier_label: str) -> Optional[str]:
    return _flare_grants.flare_for_tier(tier_label)


# ----------------------------------------------------------------------
# Onboarding name sanitization (PB-1 onboarding UX, 2026-05-09)
# ----------------------------------------------------------------------
# Conservative allowlist: alphanumeric + space/hyphen/underscore/period.
# Trim and collapse runs of whitespace. Empty after sanitize → return None
# so the caller falls back to auto-generated slug. Max length matches the
# DB column (64) and Developer.name typical UNIQUE constraint reach.
import re as _re
_NAME_ALLOWED = _re.compile(r"[^A-Za-z0-9 _.\-]")
_NAME_RUNS = _re.compile(r"\s+")


def _sanitize_onboarding_name(raw: Optional[str], *, min_len: int = 2, max_len: int = 64) -> Optional[str]:
    """Return a clean name, or None if the input is empty/too short after stripping.
    Intentionally lenient — we re-suffix on collision rather than rejecting."""
    if not raw:
        return None
    cleaned = _NAME_ALLOWED.sub("", str(raw))
    cleaned = _NAME_RUNS.sub(" ", cleaned).strip()
    if len(cleaned) < min_len:
        return None
    return cleaned[:max_len]


def _should_overwrite_flare(existing: Optional[str], proposed: Optional[str]) -> bool:
    """Higher-rank flare overwrites lower; equal/lower never overwrites.

    §FLARESHOP: delegates to services/flare_grants — one definition, two lanes."""
    return _flare_grants.should_overwrite_flare(existing, proposed)


# ----------------------------------------------------------------------
# Env-driven guards
# ----------------------------------------------------------------------

def _fiat_enabled() -> bool:
    return os.getenv("FIAT_ONRAMP_ENABLED", "false").lower() == "true"


def _is_fiat_genesis() -> bool:
    """Mainframe-only guard for fiat onramp.

    Uses a DEDICATED env var (FIAT_GENESIS_REGISTRY) instead of the project's
    IS_CENTRAL_REGISTRY which has different semantics (cron-poll runner, not
    genesis-treasury holder). Defaults to False — federated registries are
    the architectural default; only the genesis registry that holds the AVT
    supply pool sets this to true.
    """
    return os.getenv("FIAT_GENESIS_REGISTRY", "false").lower() == "true"


def _require_runtime_ready():
    if not _is_fiat_genesis():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            # D6-060 (2026-10-25): it said "Federated registries cannot mint AVT ... Acquire AVT" on every registry
            # that is not the fiat genesis registry, EU and ASIA (ECU, ACU) included. The refusal names the switch
            # and claims no unit. The MCP tester's contract matches "mainframe-only by construction": it stays.
            "Fiat onramp is mainframe-only by construction: it runs only on the registry "
            "FIAT_GENESIS_REGISTRY names the fiat genesis registry, and this registry is not it.",
        )
    if not _fiat_enabled():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Fiat onramp is not currently enabled on this registry.",
        )


def _stripe_api_key() -> str:
    key = os.getenv("STRIPE_API_KEY", "")
    if not key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "STRIPE_API_KEY not configured on this registry.",
        )
    return key


# ----------------------------------------------------------------------
# Terms-of-Service consent (W1, 2026-05-09)
# ----------------------------------------------------------------------
# Pinned to the version that introduces § 13 Fiat Purchases (the EU
# 14-day withdrawal-right carve-out per §312g + §356(5) BGB). Bumping
# this constant requires the matching update in `LegalPage.vue` —
# replays of older versions are rejected at the boundary so that a
# silent ToS drift cannot land without an explicit code change.
CURRENT_TOS_VERSION = settings.TOS_VERSION  # §LEGALKIT: one copy, in config


def _stripe_webhook_secret() -> str:
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "STRIPE_WEBHOOK_SECRET not configured on this registry.",
        )
    return secret


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------

class TierInfo(BaseModel):
    floor_eur: str
    avt_per_eur: str
    tier_label: str
    bonus_label: Optional[str] = ""


class TiersResponse(BaseModel):
    min_eur: str
    max_eur: str
    currency: str = "EUR"
    tiers: List[TierInfo]
    config_version: Optional[int] = None
    note: str = (
        "AVT is a utility token — buy-only, no fiat redemption (MiCA-safe). "
        "Bonus tiers reward larger purchases. Pricing is operator-configurable."
    )


class QuoteRequest(BaseModel):
    eur_amount: str = Field(..., description="EUR amount, e.g. '5.00'")


class QuoteResponse(BaseModel):
    eur_amount: str
    avt_amount: str
    avt_per_eur_rate: str
    tier_label: str


class CheckoutRequest(BaseModel):
    eur_amount: str = Field(..., description="EUR amount, '1.00'-'500.00'")
    # PB-3 W2.5 (2026-05-12): optional provider selector. Defaults to 'stripe' for
    # backwards compat with all existing callers. Per Q2 closure: frontend picker
    # defers to v1.1, so this is backend-only for now. Per Q1 closure: v1.0 enables
    # 'mollie' as the second PSP. Other providers (adyen/gocardless) return 503.
    provider: Optional[str] = Field(
        "stripe",
        description=(
            "Payment provider name (default 'stripe'). Backend-only param in v1.0; "
            "frontend picker is v1.1. Must match an enabled provider on this registry "
            "(see GET /api/v1/fiat/providers)."
        ),
    )
    agent_did: Optional[str] = Field(
        None,
        description=(
            "Logged-in flow: target agent DID owned by the caller. "
            "Anonymous flow: omit and supply customer_email instead."
        ),
    )
    customer_email: Optional[EmailStr] = Field(
        None,
        description=(
            "Anonymous flow only. We auto-create a Developer + first Agent "
            "after the webhook fires; a magic-link email lets the user log in."
        ),
    )
    # PB-1 onboarding-name capture (2026-05-09). Anonymous-flow only — when set,
    # the webhook uses these instead of the `{email-local}-{rand}` auto-slug.
    # Both optional; both fall back to the auto-slug logic if missing or if a
    # collision is detected on the developer name (UNIQUE constraint).
    developer_name: Optional[str] = Field(
        None, max_length=64,
        description=(
            "Anonymous flow only — desired Developer account name. Optional; "
            "leave blank for an auto-generated handle."
        ),
    )
    agent_name: Optional[str] = Field(
        None, max_length=64,
        description=(
            "Anonymous flow only — desired first-agent name. Optional; "
            "leave blank for an auto-generated handle."
        ),
    )
    return_path: Optional[str] = Field(
        "/become-a-backer/success",
        description="Frontend path to redirect to after checkout (success).",
    )
    cancel_path: Optional[str] = Field(
        "/become-a-backer",
        description="Frontend path to redirect to on cancel.",
    )
    # W1 (2026-05-09): explicit Terms acceptance is REQUIRED. The version
    # the buyer accepted is captured per row for audit. Frontend sends
    # both fields together; the validator in `create_checkout` rejects a
    # missing consent (400) and a version drift (400). See § 13 of the
    # Terms of Service and `feedback_fiat_tos_required.md`.
    tos_accepted: bool = Field(
        False,
        description=(
            "REQUIRED: must be true. Marks explicit acceptance of the Terms "
            "of Service (incl. § 13 Fiat Purchases / EU 14-day withdrawal-"
            "right carve-out)."
        ),
    )
    tos_version: Optional[str] = Field(
        None,
        max_length=16,
        description=(
            "Version of the Terms of Service the buyer accepted (e.g. '1.4'). "
            "Must match the registry's current pinned version."
        ),
    )
    # 2026-05-10 — Founders Wall personalization (Option C). All optional;
    # all sanitized server-side. See Migration 0039 + sanitize_display_name().
    display_name: Optional[str] = Field(
        None,
        max_length=32,
        description=(
            "Public display name for the Founders Wall chip (optional, max "
            "32 chars). Server strips URLs, control characters, and applies "
            "a conservative char allowlist. Leave blank for an anonymous chip."
        ),
    )
    display_country: Optional[str] = Field(
        None,
        min_length=2, max_length=2,
        pattern=r"^[A-Za-z]{2}$",
        description=(
            "ISO 3166-1 alpha-2 country code for the Founders Wall flag "
            "(e.g. 'DE', 'US'). Prefilled browser-side from the user's locale; "
            "server never derives this from the request IP."
        ),
    )
    show_on_wall: bool = Field(
        True,
        description=(
            "If false, the buyer is hidden from the public Founders Wall and "
            "from /api/v1/fiat/stats/public regardless of display_name / "
            "display_country values. Default true (visible)."
        ),
    )


class CheckoutResponse(BaseModel):
    fiat_purchase_id: str
    stripe_session_id: str
    checkout_url: str
    eur_amount: str
    avt_amount: str
    tier_label: str
    expires_at: str  # Stripe Checkout sessions expire after 24h
    anonymous_flow: bool


# PB-2 (2026-05-09): operator-storefront → mainframe-Stripe proxy schema.
# Operator BFFs call /api/v1/fiat/proxy/checkout-session on mainframe. The
# X-Federation-License header authenticates the operator (existing
# verify_federation_license dep). All buyer-facing fields mirror
# CheckoutRequest; the operator-specific fields are optional sandboxes for
# Stripe-branding overrides + an operator_did/operator_registry_name pair
# that drives the post-settle cross-TEG fund target.
class ProxyCheckoutRequest(BaseModel):
    eur_amount: str = Field(..., description="EUR amount, '1.00'-'500.00'")
    operator_did: str = Field(..., description="DID of the operator's federation license — must match X-Federation-License")
    operator_registry_name: str = Field(
        ...,
        description=(
            "Peer registry name as it appears in mainframe's PARTNER_TEGS / "
            "TRUSTED_REGISTRIES (e.g., 'Sandbox Alpha', 'cloud-op-op-london'). "
            "Drives the cross-teg-fund target on settle."
        ),
    )
    # Buyer-facing fields — proxied to mainframe Stripe session unchanged.
    agent_did: Optional[str] = Field(None, description="Buyer's local agent on the OPERATOR registry (logged-in flow).")
    customer_email: Optional[EmailStr] = Field(None, description="Anonymous flow — operator's local Developer + Agent will be created on the OPERATOR registry on settle, not on mainframe.")
    developer_name: Optional[str] = Field(None, max_length=64)
    agent_name: Optional[str] = Field(None, max_length=64)
    return_path: Optional[str] = Field(None, description="Operator-domain URL the buyer is redirected to on success.")
    cancel_path: Optional[str] = Field(None, description="Operator-domain URL the buyer is redirected to on cancel.")
    tos_accepted: bool = Field(False)
    tos_version: Optional[str] = Field(None, max_length=16)
    # 2026-05-10 — Founders Wall personalization (Option C). Server sanitizes
    # display_name + validates display_country format. Same fields as
    # CheckoutRequest — see Migration 0039 + sanitize_display_name().
    display_name: Optional[str] = Field(None, max_length=32)
    display_country: Optional[str] = Field(None, min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")
    show_on_wall: bool = Field(True)
    # Per-operator Stripe branding overrides (cosmetic only; one Stripe
    # account on mainframe handles every operator). Optional dict with keys:
    #   product_name        — e.g. "op-london Founder Tier"
    #   statement_descriptor — bank statement (≤22 chars, alnum+spaces)
    #   product_image_url   — operator's logo on Stripe Checkout page
    #   accent_color        — Stripe Checkout primary color hex
    operator_branding: Optional[dict] = Field(default=None)


class ProxyCheckoutResponse(CheckoutResponse):
    """Mainframe-side proxy response — superset of CheckoutResponse with
    routed-flow correlation IDs the operator BFF persists on its local row."""
    mainframe_fiat_purchase_id: str
    operator_did: str
    operator_registry_name: str


class PurchaseStatusResponse(BaseModel):
    fiat_purchase_id: str
    stripe_session_id: str
    status: str
    eur_amount: str
    avt_amount: str
    tier_label: str
    agent_did: Optional[str]
    avt_transfer_tx_id: Optional[str]
    anonymous_flow: bool
    created_at: str
    completed_at: Optional[str]
    # PB-1 flare cosmetic — derived from tier_label, surfaced for the success
    # page to render the earned FlareBadge without a second round-trip.
    flare_tier: Optional[str] = None


class PurchaseListItem(BaseModel):
    fiat_purchase_id: str
    status: str
    eur_amount: str
    avt_amount: str
    agent_did: Optional[str]
    created_at: str
    completed_at: Optional[str]


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _parse_eur(raw: str, config: dict) -> Decimal:
    try:
        eur = Decimal(raw)
    except (InvalidOperation, TypeError):
        raise HTTPException(400, f"Invalid EUR amount: {raw!r}")
    try:
        return validate_eur_amount(eur, config)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


def _build_url(path: str) -> str:
    base = str(settings.BASE_URL).rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    # Frontend uses hash routing; if caller passes a hash-style path, honor it.
    return f"{base}{path}" if path.startswith("/#") else f"{base}/ui#{path}"


async def _emit(event_type: str, aggregate_id: str, data: dict, idempotency_key: "Optional[str]" = None):
    try:
        emitter = get_event_emitter()
        if emitter:
            asyncio.create_task(emitter.emit(
                event_type=event_type,
                aggregate_id=aggregate_id,
                data=data,
                idempotency_key=idempotency_key,  # §BATCH7: one purchase, one event
            ))
    except Exception as exc:
        logger.warning("[fiat] event emit failed: %s", exc)


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------

@router.get("/tiers", response_model=TiersResponse, summary="The fiat on-ramp's tier table (503 where the on-ramp is off)")
async def get_tiers(db: AsyncSession = Depends(get_db)):
    """
    The fiat on-ramp's live tier table: the min and max EUR amount and, per tier, the units credited per EUR. The
    on-ramp is a switch per registry (`FIAT_ONRAMP_ENABLED`), off on the public network, where this answers 503: a
    registry with the on-ramp off publishes no tier table. Public, no auth.

    \f
    Public — no auth. Returns the live EUR→AVT tier table from DB.

    2026-07-31: gated on the master kill switch. A registry that has switched the
    onramp off must not keep publishing a EUR price list: a public tier table is an
    offer surface, and advertising prices for a lane that 503s is exactly the
    incoherence a compliance posture cannot afford. Off means off, on every surface.
    """
    if not _fiat_enabled():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Fiat onramp is not currently enabled on this registry.",
        )
    config = await get_active_pricing(db)
    # Pull config_version from the active row (lightweight extra query — public
    # endpoint, low frequency; fine for now, can fold into get_active_pricing later)
    version_row = await db.execute(
        select(FiatPricingConfig.version).where(FiatPricingConfig.is_active == True).limit(1)
    )
    version = version_row.scalar_one_or_none()
    tiers = [
        TierInfo(
            floor_eur=str(t.get("floor_eur", "")),
            avt_per_eur=str(t.get("avt_per_eur", "")),
            tier_label=str(t.get("tier_label", "")),
            bonus_label=str(t.get("bonus_label", "")) if t.get("bonus_label") else "",
        )
        for t in (config.get("tiers") or [])
    ]
    return TiersResponse(
        min_eur=str(config.get("min_eur", "1.00")),
        max_eur=str(config.get("max_eur", "500.00")),
        currency=str(config.get("currency", "EUR")),
        tiers=tiers,
        config_version=version,
    )


@router.post("/quote", response_model=QuoteResponse, summary="The fiat on-ramp's quote for an EUR amount")
async def quote_fiat(req: QuoteRequest, db: AsyncSession = Depends(get_db)):
    """
    The units the fiat on-ramp would credit for an EUR amount, at the live tier table (no payment provider is
    called). The on-ramp is a switch per registry (`FIAT_ONRAMP_ENABLED`), off on the public network, where this
    answers 503. Public, no auth.

    \f
    Public — no Stripe call, just math. Used by the BuyAVT.vue live preview.

    §BAFIN (2026-10-01): gated like /tiers. With the lane off it went on answering "10 EUR = 20000" without login,
    a euro price for Units on a registry that sells none; off means off on every surface.
    """
    if not _fiat_enabled():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Fiat onramp is not currently enabled on this registry.",
        )
    config = await get_active_pricing(db)
    eur = _parse_eur(req.eur_amount, config)
    avt = compute_avt_amount(eur, config)
    rate = (avt / eur).quantize(Decimal("0.01"))
    return QuoteResponse(
        eur_amount=str(eur),
        avt_amount=str(avt),
        avt_per_eur_rate=str(rate),
        tier_label=get_tier_label(eur, config),
    )


def _is_operator_routed_enabled() -> bool:
    """PB-2 — operator-side gate. Operators set this to enable routed-fiat
    storefront (proxies to mainframe Stripe). Default false so operators
    explicitly opt in. Mainframe ignores this flag (gated by _is_fiat_genesis)."""
    return os.getenv("ROUTED_FIAT_ENABLED", "false").lower() == "true"


def _operator_self_did() -> Optional[str]:
    """PB-2 — operator's own DID *as recorded in the mainframe's
    federation_licenses table*. Must match the value mainframe gets back
    from verify_federation_license (anti-impersonation gate).

    Reads `FEDERATION_OPERATOR_DID` first (PB-2 dedicated env var) — the
    legacy `OPERATOR_DID` env is used by other subsystems (provisioning,
    SPIFFE) with potentially different semantics, so don't confuse the two.
    """
    return (os.getenv("FEDERATION_OPERATOR_DID", "") or os.getenv("OPERATOR_DID", "") or "").strip() or None


def _operator_mainframe_url() -> Optional[str]:
    """PB-2 — URL to mainframe (where /fiat/proxy/checkout-session lives)."""
    return (os.getenv("MAINFRAME_PROXY_URL", "") or os.getenv("CENTRAL_REGISTRY_URL", "")).strip() or None


def _operator_federation_license() -> Optional[str]:
    """PB-2 — operator's plain federation license key (X-Federation-License)."""
    return (os.getenv("FEDERATION_LICENSE_KEY", "") or os.getenv("MAINFRAME_FEDERATION_LICENSE_KEY", "")).strip() or None


def _operator_registry_self_name() -> str:
    """PB-2 — name this operator registers as in mainframe's peer_registries
    (drives cross-teg-fund target on the mainframe side). Defaults to REGISTRY_NAME."""
    return (os.getenv("OPERATOR_REGISTRY_NAME", "") or os.getenv("REGISTRY_NAME", "")).strip()


async def _checkout_bearer_developer(request: Request, db: AsyncSession) -> Optional[Developer]:
    """The developer a checkout's Bearer token names, None without one; a Bearer that does not authenticate is refused
    with 401, as the logged-in flow has always refused it."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    try:
        return await get_current_developer_unified(
            authorization=auth_header,
            x_api_key=None,
            db=db,
            request=request,   # D6-514: the route a scoped key may reach
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[fiat] dev JWT resolution failed: %s", exc)
        raise HTTPException(401, "Invalid or expired developer JWT")


@router.post(
    "/checkout-session",
    response_model=CheckoutResponse,
    summary="Create Stripe Checkout Session (logged-in OR anonymous; routed-via-mainframe on operators)",
)
async def create_checkout(
    req: CheckoutRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key",
        description="§pass56 PR-8: optional retry idempotency. Stripe Checkout Session creation is idempotent on the Stripe-side via session_id; this header is documented for client UX."),
):
    # Jurisdiction Profiles (SPEC 2026-07-31): operator-declared feature restriction.
    # Deny-only, pre-escrow, before any money moves. Byte-inert while JURISDICTION_MODE=off.
    from agentvault_registry.services import jurisdiction as _juris
    await _juris.check_jurisdiction(db, "fiat")
    # REGAUTH (SPEC 2026-08-15): a declared fiat.lane requirement parks checkout
    # creation (registry scope) until a regulatory authorization is on file.
    # Pre-money, deny-only, byte-inert while JURISDICTION_MODE=off or undeclared.
    from agentvault_registry.services import regulatory_auth as _regauth
    await _regauth.check_regulatory_authorization(db, "fiat.lane")
    # §29 OPA I6 `fiat_flow_ok` — LIVE CALL SITE. Fiat_Rails_Strategy.md:111 "no fiat-out endpoint
    # exists, ever" (MiCA + BaFin trip-wire) and :225 "no auto-mint on fiat purchase" are hard
    # rules held today only by nobody having written the code. This asserts them on every real
    # purchase. Shadow-mode observes; Δ-irrelevant; never blocks while OPA_ENFORCE=false.
    try:
        from agentvault_registry import opa_shadow as _opa
        await _opa.shadow_check("agentvault/invariants/fiat_flow_ok",
            {"direction": "in", "mints_tokens": False, "custodial_balance": False},
            True, label="fiat_checkout")
    except Exception:
        pass
    """
    Three modes:
      • Mainframe direct (PB-1): genesis registry runs Stripe locally. Buyer's
        agent on the mainframe gets credited.
      • Operator routed (PB-2): operator registries proxy to mainframe's
        /api/v1/fiat/proxy/checkout-session and persist a local FiatPurchase
        with mainframe_fiat_purchase_id linkback. Buyer's agent on the OPERATOR
        is the eventual settle target.
      • 503: federated registry without ROUTED_FIAT_ENABLED.

    Routing decision: _is_fiat_genesis() ⇒ direct, else
    _is_operator_routed_enabled() ⇒ routed, else 503.
    """
    # §pass57: request-level dedup via Redis (24h TTL). Prevents duplicate
    # FiatPurchase rows + duplicate Stripe Checkout Sessions on client retry.
    from agentvault_registry.services.idempotency import idempotency_lookup, idempotency_store
    from agentvault_registry.services.idempotency.cache import ANONYMOUS_CALLER, developer_caller
    # D6-777: the record is the caller's, so the bearer is resolved before the record is read (a request without one is
    # the anonymous flow's)
    bearer_developer = await _checkout_bearer_developer(request, db)
    me = developer_caller(bearer_developer.id) if bearer_developer is not None else ANONYMOUS_CALLER
    _idem_body = req.model_dump(mode="json")
    _cached, _err = await idempotency_lookup("fiat.checkout", idempotency_key, _idem_body, principal=me)
    if _err:
        raise HTTPException(status_code=422, detail=_err)
    if _cached is not None:
        return _cached

    # PB-2 operator-routed branch (federated registries with ROUTED_FIAT_ENABLED).
    if not _is_fiat_genesis():
        if not _is_operator_routed_enabled():
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Fiat onramp is not enabled on this registry. Mainframe-only by default; "
                "operators must set ROUTED_FIAT_ENABLED=true to opt into routed-fiat.",
            )
        _r = await _create_operator_routed_checkout(req, request, db)
        try:
            _r_dict = _r.model_dump(mode="json") if hasattr(_r, "model_dump") else dict(_r)
            await idempotency_store("fiat.checkout", idempotency_key, _idem_body, _r_dict, principal=me)
        except Exception:
            pass
        return _r

    # PB-1 direct flow (genesis registry only) — original code path below.
    _require_runtime_ready()

    # W1 — Explicit Terms acceptance gate (2026-05-09). Captures the EU
    # 14-day withdrawal-right carve-out per §312g + §356(5) BGB. Must
    # match the pinned version verbatim to prevent silent ToS drift.
    if req.tos_accepted is not True:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "tos_accepted required: you must accept the Terms of Service "
            "(including § 13 Fiat Purchases) before proceeding.",
        )
    if (req.tos_version or "").strip() != CURRENT_TOS_VERSION:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"tos_version mismatch: expected '{CURRENT_TOS_VERSION}', got "
            f"'{req.tos_version!r}'. Reload the Terms of Service and try again.",
        )

    config = await get_active_pricing(db)
    eur = _parse_eur(req.eur_amount, config)
    avt = compute_avt_amount(eur, config)
    rate = (avt / eur).quantize(Decimal("0.01"))
    tier = get_tier_label(eur, config)

    # Determine flow
    auth_header = request.headers.get("Authorization", "")
    has_jwt = auth_header.startswith("Bearer ")
    developer: Optional[Developer] = None
    agent: Optional[Agent] = None
    anonymous = False

    if req.agent_did and not has_jwt:
        raise HTTPException(401, "agent_did requires an authenticated developer JWT")
    if not req.agent_did and not req.customer_email:
        raise HTTPException(
            400,
            "Provide either `agent_did` (logged-in flow) or `customer_email` "
            "(anonymous flow).",
        )

    if has_jwt:
        # The developer the Bearer token names (resolved before the idempotency record), then the agent's ownership.
        developer = bearer_developer

        if not req.agent_did:
            raise HTTPException(400, "agent_did required for logged-in flow")
        agent_row = await db.execute(
            select(Agent).where(Agent.did == req.agent_did)
        )
        agent = agent_row.scalar_one_or_none()
        if not agent:
            raise HTTPException(404, f"Agent {req.agent_did} not found")
        if agent.creator_developer_id != developer.id:
            raise HTTPException(403, "You do not own this agent")
        if agent.status not in ("active",):
            raise HTTPException(400, f"Cannot fund agent in status {agent.status}")
    else:
        anonymous = True
        if not req.customer_email:
            raise HTTPException(400, "customer_email required for anonymous flow")

    # PB-1 onboarding-name capture: only relevant on anonymous flow. Sanitize
    # both at the boundary (defense in depth: the schema has max_length=64,
    # but we also strip disallowed chars + collapse whitespace).
    requested_dev_name = _sanitize_onboarding_name(req.developer_name) if anonymous else None
    requested_agent_name = _sanitize_onboarding_name(req.agent_name) if anonymous else None

    # Insert pending FiatPurchase row BEFORE Stripe call so we can correlate
    # session_id back deterministically. Update with session_id post-create.
    purchase = FiatPurchase(
        # placeholder session_id — replaced post-Stripe-create. Unique-on-update
        # would be cleaner via deferred constraint, but storing a uuid here keeps
        # the UNIQUE constraint happy until the real session_id arrives.
        stripe_session_id=f"pending-{secrets.token_hex(16)}",
        developer_id=developer.id if developer else None,
        agent_did=agent.did if agent else None,
        customer_email=req.customer_email if anonymous else (
            developer.email if developer else None
        ),
        amount_eur=eur,
        amount_avt=avt,
        avt_per_eur_rate=rate,
        tier_label=tier,
        status=FiatPurchaseStatus.PENDING.value,
        anonymous_flow=anonymous,
        requested_developer_name=requested_dev_name,
        requested_agent_name=requested_agent_name,
        tos_accepted_at=datetime.now(timezone.utc),
        tos_version=CURRENT_TOS_VERSION,
        # 2026-05-10 — Founders Wall personalization. Sanitized server-side.
        display_name=sanitize_display_name(req.display_name),
        display_country=(req.display_country or '').upper()[:2] or None,
        show_on_wall=bool(req.show_on_wall),
    )
    db.add(purchase)
    # §LEGALKIT: the checkout checkbox is an acceptance (Terms § 13.6); record it like every other rail.
    await db.flush()
    await _record_acceptance(db, document="terms", subject_kind=_SUBJECT_CHECKOUT,
                             subject_id=getattr(purchase, "id", None), via="checkout",
                             developer_id=getattr(purchase, "developer_id", None), request=request,
                             version=CURRENT_TOS_VERSION)
    await db.commit()
    await db.refresh(purchase)

    # Now create Stripe Checkout Session with our purchase id in metadata.
    success_url = (
        _build_url(req.return_path or "/become-a-backer/success")
        + ("?session_id={CHECKOUT_SESSION_ID}")
    )
    cancel_url = _build_url(req.cancel_path or "/become-a-backer")
    # Map internal tier label → human-readable backer-tier name (shown on
    # the Stripe Checkout product line). Frontend mirrors this mapping for
    # the public BuyAVT page UI.
    _TIER_DISPLAY_NAMES = {
        "tier_1_base":    "Sentinel",
        "tier_2_value":   "Architect",
        "tier_3_premium": "Founder",
    }
    tier_display = _TIER_DISPLAY_NAMES.get(tier, "Backer Tier")
    metadata = {
        "fiat_purchase_id": purchase.id,
        "agent_did": agent.did if agent else "",
        "anonymous_flow": "true" if anonymous else "false",
        "tier_label": tier,
        "tier_display_name": tier_display,
    }
    customer_email = req.customer_email if anonymous else (
        developer.email if developer else None
    )

    # PB-3 W2.5 (2026-05-12): route through FiatProvider abstraction.
    # Provider name validated + enabled-check; default 'stripe' for backwards compat.
    provider_name = (req.provider or "stripe").lower().strip()
    psp = get_provider(provider_name)
    if psp is None:
        purchase.status = FiatPurchaseStatus.FAILED.value
        purchase.failure_reason = f"provider_disabled: {provider_name}"
        await db.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Provider '{provider_name}' not enabled on this registry. "
            f"Enabled: {enabled_providers()}",
        )

    purchase.payment_provider = provider_name
    await db.commit()

    try:
        provider_session = await psp.create_checkout(
            eur_amount=eur,
            avt_amount=avt,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=customer_email,
            metadata=metadata,
            tier_label=tier,
            tier_display_name=tier_display,
        )
    except Exception as exc:
        logger.exception("[fiat] %s checkout creation failed", provider_name)
        purchase.status = FiatPurchaseStatus.FAILED.value
        purchase.failure_reason = f"{provider_name}:create_failed: {str(exc)[:300]}"
        await db.commit()
        raise HTTPException(502, f"{provider_name} checkout creation failed: {exc}")

    # Persist provider session/payment ids (new columns + legacy dual-write for Stripe)
    purchase.provider_session_id = provider_session.provider_session_id
    purchase.provider_payment_id = provider_session.provider_payment_id
    if provider_name == "stripe":
        purchase.stripe_session_id = provider_session.provider_session_id
        purchase.stripe_payment_intent_id = provider_session.provider_payment_id
    await db.commit()
    await db.refresh(purchase)

    await _emit(
        event_type="FiatPurchaseInitiated",
        aggregate_id=purchase.id,
        data={
            "fiat_purchase_id": purchase.id,
            "payment_provider": provider_name,
            "provider_session_id": provider_session.provider_session_id,
            # Legacy key retained during 30-day expand-contract (§A.7).
            "stripe_session_id": provider_session.provider_session_id if provider_name == "stripe" else None,
            "amount_eur": str(eur),
            "amount_avt": str(avt),
            "tier_label": tier,
            "anonymous_flow": anonymous,
            "agent_did": agent.did if agent else None,
            "developer_id": developer.id if developer else None,
        },
        idempotency_key=f"fiat-initiated-{purchase.id}",  # §BATCH7
    )

    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    logger.info(
        "[fiat] %s checkout purchase=%s session=%s eur=%s avt=%s anon=%s",
        provider_name, purchase.id, provider_session.provider_session_id, eur, avt, anonymous,
    )
    _resp = CheckoutResponse(
        fiat_purchase_id=purchase.id,
        stripe_session_id=provider_session.provider_session_id,  # legacy field name; carries provider session id
        checkout_url=provider_session.redirect_url,
        eur_amount=str(eur),
        avt_amount=str(avt),
        tier_label=tier,
        expires_at=expires_at.isoformat(),
        anonymous_flow=anonymous,
    )
    # §pass57: cache successful response for replay protection
    await idempotency_store("fiat.checkout", idempotency_key, _idem_body, _resp.model_dump(mode="json"), principal=me)
    return _resp


# =============================================================================
# PB-2 — Routed Fiat Proxy (mainframe-side)
# =============================================================================
# Operator BFFs (running on operator registries) call this endpoint to obtain
# a Stripe Checkout URL. Auth: X-Federation-License header (existing
# verify_federation_license dep). The operator's caller stays under operator
# branding; mainframe runs the only Stripe account.
#
# On stripe.checkout.session.completed, the webhook detects routed flow via
# metadata.operator_did and dispatches to _handle_routed_settle (see P4).

def _routed_proxy_enabled() -> bool:
    """Master switch for the /proxy/checkout-session endpoint."""
    return os.getenv("ROUTED_FIAT_PROXY_ENABLED", "false").lower() == "true"


def _routed_operator_allowed(operator_did: str) -> bool:
    """Per-operator allowlist for staged production rollout.

    `ROUTED_FIAT_OPERATOR_ALLOWLIST` is comma-separated; '*' enables all.
    Default is empty (no operators allowed) so the gate is closed by default
    and Commander explicitly opens it per-operator.
    """
    raw = os.getenv("ROUTED_FIAT_OPERATOR_ALLOWLIST", "").strip()
    if not raw:
        return False
    if raw == "*":
        return True
    allowlist = {item.strip() for item in raw.split(",") if item.strip()}
    return operator_did in allowlist


@router.post(
    "/proxy/checkout-session",
    response_model=ProxyCheckoutResponse,
    summary="Routed fiat: an operator's checkout through the mainframe's payment provider",
)
async def create_proxy_checkout(
    req: ProxyCheckoutRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key",
        description="§pass56 PR-8: optional retry idempotency. Routed-fiat path; PSP-side idempotency uses session_id."),
):
    """Operator BFF → mainframe proxy for the routed-fiat flow.

    Flow:
      1. Mainframe-only gate (FIAT_GENESIS_REGISTRY) + master kill (FIAT_ONRAMP_ENABLED)
         + routed-fiat master switch (ROUTED_FIAT_PROXY_ENABLED) + per-operator
         allowlist (ROUTED_FIAT_OPERATOR_ALLOWLIST).
      2. Auth: X-Federation-License header. Hash matches an active license whose
         operator_did equals req.operator_did (anti-impersonation).
      3. T&C consent (as in the direct flow; the TOS version is pinned).
      4. peer_registries lookup: row exists, status=ACTIVE, peer_type in
         {cloud_operator, frame}. License-active assert via license-gate.
      5. Pricing math (same as direct flow).
      6. Insert mainframe-side FiatPurchase row with routed=true,
         target_operator_did, target_operator_registry_name. Stripe metadata
         carries operator_did so the webhook routing branch dispatches to
         _handle_routed_settle (P4).
      7. Stripe Checkout creation with operator branding overrides
         (statement_descriptor, product_data.{name,images}). success_url and
         cancel_url use operator-domain paths (req.return_path/req.cancel_path).
      8. Return checkout_url + mainframe_fiat_purchase_id for the operator
         BFF to persist on its local FiatPurchase row.
    """
    _require_runtime_ready()  # mainframe-only + FIAT_ONRAMP_ENABLED

    if not _routed_proxy_enabled():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Routed-fiat proxy is not currently enabled on this registry.",
        )

    # Federation license auth (existing helper) — re-imported locally to avoid
    # circular import at module load. D6-777: before the idempotency record, which is the licence's own.
    from .federation_licenses import verify_federation_license as _verify_fed_license, assert_licensee_type
    license_obj = await _verify_fed_license(
        x_federation_license=request.headers.get("X-Federation-License", ""),
        db=db,
    )
    assert_licensee_type(license_obj, "operator")  # D6-111: an operator's storefront rail; a frame's key is refused

    # §pass57: request-level dedup via Redis
    from agentvault_registry.services.idempotency import idempotency_lookup, idempotency_store
    from agentvault_registry.services.idempotency.cache import licence_caller
    me = licence_caller(license_obj.id)
    _idem_body = req.model_dump(mode="json")
    _cached, _err = await idempotency_lookup("fiat.proxy-checkout", idempotency_key, _idem_body, principal=me)
    if _err:
        raise HTTPException(status_code=422, detail=_err)
    if _cached is not None:
        return _cached

    # Anti-impersonation: license must belong to the operator_did the caller claims.
    if (license_obj.operator_did or "").lower() != (req.operator_did or "").lower():
        logger.warning(
            "[fiat-proxy] operator_did mismatch: license=%s, request=%s",
            license_obj.operator_did, req.operator_did,
        )
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "operator_did does not match the federation license.",
        )

    # Per-operator allowlist (staged rollout gate).
    if not _routed_operator_allowed(req.operator_did):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Operator {req.operator_did} is not in ROUTED_FIAT_OPERATOR_ALLOWLIST.",
        )

    # T&C consent (same gate as direct flow; pinned to CURRENT_TOS_VERSION).
    if req.tos_accepted is not True:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "tos_accepted required: buyer must accept the Terms of Service.",
        )
    if (req.tos_version or "").strip() != CURRENT_TOS_VERSION:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"tos_version mismatch: expected '{CURRENT_TOS_VERSION}', got '{req.tos_version!r}'.",
        )

    # peer_registries pre-flight: target operator must be a known active peer.
    peer_q = await db.execute(
        select(models.PeerRegistry).where(
            models.PeerRegistry.name == req.operator_registry_name,
            models.PeerRegistry.status == "ACTIVE",
        )
    )
    peer = peer_q.scalar_one_or_none()
    if peer is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Operator '{req.operator_registry_name}' is not an ACTIVE peer registry.",
        )
    if peer.peer_type not in ("cloud_operator", "frame"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Operator '{req.operator_registry_name}' has peer_type='{peer.peer_type}' (expected cloud_operator or frame).",
        )

    # License-active assert via the central gate (emits audit event on block).
    from ..services.federation_license_gate import assert_peer_license_active
    await assert_peer_license_active(
        db=db,
        operator_did=req.operator_did,
        context="fiat_routed_proxy_checkout",
    )
    # D6-801 (wave 6, 2026-10-17): a registry this one holds in quarantine, soft quarantine or blacklisted takes part in
    # no movement of money with it, and a routed purchase is settled into the registry it names. Refused here, before
    # the purchase row and the payment session exist; 503 when the compliance state cannot be read.
    from ..services.federation_license_gate import assert_registry_not_quarantined
    await assert_registry_not_quarantined(db, peer.name, context="fiat_routed_proxy_checkout")

    # Pricing math (reuse direct-flow helpers).
    config = await get_active_pricing(db)
    eur = _parse_eur(req.eur_amount, config)
    avt = compute_avt_amount(eur, config)
    rate = (avt / eur).quantize(Decimal("0.01"))
    tier = get_tier_label(eur, config)

    # Sanitize anon-flow names (only relevant when no agent_did supplied).
    is_anonymous = not req.agent_did
    requested_dev_name = _sanitize_onboarding_name(req.developer_name) if is_anonymous else None
    requested_agent_name = _sanitize_onboarding_name(req.agent_name) if is_anonymous else None
    if not is_anonymous and not req.agent_did:
        raise HTTPException(400, "agent_did or customer_email required.")
    if is_anonymous and not req.customer_email:
        raise HTTPException(400, "customer_email required for anonymous flow.")

    # Insert mainframe-side FiatPurchase row (routed=true).
    purchase = FiatPurchase(
        stripe_session_id=f"pending-{secrets.token_hex(16)}",
        # IMPORTANT: developer_id and agent_did stay NULL on mainframe-side
        # routed rows. The buyer's Developer + Agent live on the OPERATOR
        # registry; mainframe row is the canonical Stripe-side audit anchor.
        developer_id=None,
        agent_did=None,
        customer_email=req.customer_email if is_anonymous else None,
        amount_eur=eur,
        amount_avt=avt,
        avt_per_eur_rate=rate,
        tier_label=tier,
        status=FiatPurchaseStatus.PENDING.value,
        anonymous_flow=is_anonymous,
        requested_developer_name=requested_dev_name,
        requested_agent_name=requested_agent_name,
        tos_accepted_at=datetime.now(timezone.utc),
        tos_version=CURRENT_TOS_VERSION,
        # PB-2 routed fields:
        routed=True,
        target_operator_did=req.operator_did,
        target_operator_registry_name=req.operator_registry_name,
    )
    db.add(purchase)
    # §LEGALKIT: the checkout checkbox is an acceptance (Terms § 13.6); record it like every other rail.
    await db.flush()
    await _record_acceptance(db, document="terms", subject_kind=_SUBJECT_CHECKOUT,
                             subject_id=getattr(purchase, "id", None), via="checkout",
                             developer_id=getattr(purchase, "developer_id", None), request=request,
                             version=CURRENT_TOS_VERSION)
    await db.commit()
    await db.refresh(purchase)

    # Stripe Checkout with operator branding overrides + metadata for routing.
    branding = req.operator_branding or {}
    product_name = branding.get("product_name") or f"{req.operator_registry_name} — AVT Backer Tier"
    metadata = {
        "fiat_purchase_id": purchase.id,
        "operator_did": req.operator_did,
        "operator_registry_name": req.operator_registry_name,
        "agent_did": req.agent_did or "",
        "anonymous_flow": "true" if is_anonymous else "false",
        "tier_label": tier,
        "tier_display_name": product_name,
        "routed": "true",
    }

    # Build operator-domain success/cancel URLs verbatim — operator BFF passes
    # them in already pointing at its own domain (operator's `BuyAVTSuccess.vue`).
    success_url = (req.return_path or "/become-a-backer/success") + "?session_id={CHECKOUT_SESSION_ID}"
    cancel_url = req.cancel_path or "/become-a-backer"

    try:
        session = create_checkout_session(
            api_key=_stripe_api_key(),
            eur_amount=eur,
            avt_amount=avt,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=req.customer_email,
            metadata=metadata,
        )
    except Exception as exc:
        logger.exception("[fiat-proxy] Stripe Checkout creation failed")
        purchase.status = FiatPurchaseStatus.FAILED.value
        purchase.failure_reason = f"stripe_create_failed: {str(exc)[:300]}"
        await db.commit()
        raise HTTPException(502, f"Stripe Checkout creation failed: {exc}")

    purchase.stripe_session_id = session["id"]
    purchase.stripe_payment_intent_id = session.get("payment_intent")
    await db.commit()
    await db.refresh(purchase)

    await _emit(
        event_type="FiatPurchaseInitiated",
        aggregate_id=purchase.id,
        data={
            "fiat_purchase_id": purchase.id,
            "stripe_session_id": session["id"],
            "amount_eur": str(eur),
            "amount_avt": str(avt),
            "tier_label": tier,
            "anonymous_flow": is_anonymous,
            "routed": True,
            "target_operator_did": req.operator_did,
            "target_operator_registry_name": req.operator_registry_name,
        },
        idempotency_key=f"fiat-initiated-{purchase.id}",  # §BATCH7
    )

    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    logger.info(
        "[fiat-proxy] purchase=%s session=%s eur=%s avt=%s op=%s",
        purchase.id, session["id"], eur, avt, req.operator_did,
    )

    _resp = ProxyCheckoutResponse(
        fiat_purchase_id=purchase.id,
        stripe_session_id=session["id"],
        checkout_url=session["url"],
        eur_amount=str(eur),
        avt_amount=str(avt),
        tier_label=tier,
        expires_at=expires_at.isoformat(),
        anonymous_flow=is_anonymous,
        # Routed-flow extras for operator BFF to persist on its local row:
        mainframe_fiat_purchase_id=purchase.id,
        operator_did=req.operator_did,
        operator_registry_name=req.operator_registry_name,
    )
    # §pass57: cache successful response for replay protection
    await idempotency_store("fiat.proxy-checkout", idempotency_key, _idem_body, _resp.model_dump(mode="json"),
                            principal=me)
    return _resp


# =============================================================================
# PB-2 — Operator-routed checkout (operator-side, called from create_checkout)
# =============================================================================

async def _create_operator_routed_checkout(
    req: CheckoutRequest,
    request: Request,
    db: AsyncSession,
) -> CheckoutResponse:
    """Operator BFF entry point. Validates locally, persists a local
    FiatPurchase row (routed=true, status=PENDING), then POSTs to mainframe's
    /api/v1/fiat/proxy/checkout-session and returns mainframe's checkout_url.

    Buyer's local Developer + Agent on the OPERATOR are the eventual settle
    target — when mainframe's HMAC-signed callback arrives at
    /api/v1/fiat/internal/routed-settle-callback, we fund the local agent
    via local TEG /admin/treasury/transfer.
    """
    # Sanity: operator self-config must be present
    operator_did = _operator_self_did()
    mainframe_url = _operator_mainframe_url()
    license_key = _operator_federation_license()
    operator_self_name = _operator_registry_self_name()
    if not all([operator_did, mainframe_url, license_key, operator_self_name]):
        missing = [
            n for n, v in [
                ("OPERATOR_DID/FEDERATION_OPERATOR_DID", operator_did),
                ("MAINFRAME_PROXY_URL/CENTRAL_REGISTRY_URL", mainframe_url),
                ("FEDERATION_LICENSE_KEY", license_key),
                ("OPERATOR_REGISTRY_NAME/REGISTRY_NAME", operator_self_name),
            ]
            if not v
        ]
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Operator routed-fiat misconfigured. Missing env: {missing}",
        )

    # T&C consent (mirror direct-flow gate for parity).
    if req.tos_accepted is not True:
        raise HTTPException(400, "tos_accepted required.")
    if (req.tos_version or "").strip() != CURRENT_TOS_VERSION:
        raise HTTPException(
            400,
            f"tos_version mismatch: expected '{CURRENT_TOS_VERSION}', got '{req.tos_version!r}'.",
        )

    # Identify caller (mirror create_checkout's resolution path).
    auth_header = request.headers.get("Authorization", "")
    has_jwt = auth_header.startswith("Bearer ")
    developer: Optional[Developer] = None
    agent: Optional[Agent] = None
    is_anonymous = not req.agent_did and not has_jwt

    if req.agent_did and not has_jwt:
        raise HTTPException(401, "agent_did requires an authenticated developer JWT")
    if not req.agent_did and not req.customer_email:
        raise HTTPException(400, "Provide either agent_did (logged-in) or customer_email (anonymous).")

    if has_jwt:
        try:
            developer = await get_current_developer_unified(
                authorization=auth_header,
                x_api_key=None,
                db=db,
                request=request,   # D6-514: the route a scoped key may reach
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("[fiat-op] dev JWT resolution failed: %s", exc)
            raise HTTPException(401, "Invalid or expired developer JWT")
        if not req.agent_did:
            raise HTTPException(400, "agent_did required for logged-in flow")
        agent_q = await db.execute(select(Agent).where(Agent.did == req.agent_did))
        agent = agent_q.scalar_one_or_none()
        if not agent:
            raise HTTPException(404, f"Agent {req.agent_did} not found on this registry")
        if agent.creator_developer_id != developer.id:
            raise HTTPException(403, "You do not own this agent")
        if agent.status not in ("active",):
            raise HTTPException(400, f"Cannot fund agent in status {agent.status}")

    requested_dev_name = _sanitize_onboarding_name(req.developer_name) if is_anonymous else None
    requested_agent_name = _sanitize_onboarding_name(req.agent_name) if is_anonymous else None

    # Insert local FiatPurchase row (routed=true, status=PENDING).
    purchase = FiatPurchase(
        stripe_session_id=f"pending-op-{secrets.token_hex(16)}",
        developer_id=developer.id if developer else None,
        agent_did=agent.did if agent else None,
        customer_email=(
            req.customer_email if is_anonymous else (developer.email if developer else None)
        ),
        amount_eur=Decimal("0"),  # placeholder — mainframe authoritative
        amount_avt=Decimal("0"),
        avt_per_eur_rate=Decimal("0"),
        tier_label="pending",
        status=FiatPurchaseStatus.PENDING.value,
        anonymous_flow=is_anonymous,
        requested_developer_name=requested_dev_name,
        requested_agent_name=requested_agent_name,
        tos_accepted_at=datetime.now(timezone.utc),
        tos_version=CURRENT_TOS_VERSION,
        # PB-2 routed:
        routed=True,
        target_operator_did=operator_did,           # we ARE the target operator
        target_operator_registry_name=operator_self_name,
        # mainframe_fiat_purchase_id back-filled after proxy returns
    )
    db.add(purchase)
    # §LEGALKIT: the checkout checkbox is an acceptance (Terms § 13.6); record it like every other rail.
    await db.flush()
    await _record_acceptance(db, document="terms", subject_kind=_SUBJECT_CHECKOUT,
                             subject_id=getattr(purchase, "id", None), via="checkout",
                             developer_id=getattr(purchase, "developer_id", None), request=request,
                             version=CURRENT_TOS_VERSION)
    await db.commit()
    await db.refresh(purchase)

    # POST to mainframe's /api/v1/fiat/proxy/checkout-session
    # The buyer-facing return_path/cancel_path remain operator-domain (set by
    # operator's frontend); proxy returns the Stripe checkout_url which we
    # pass through.
    # Convert relative paths to full operator-domain URLs (Stripe needs
    # absolute URLs for success_url/cancel_url; operator's BASE_URL is its
    # own public-facing domain).
    return_url_full = _build_url(req.return_path or "/become-a-backer/success")
    cancel_url_full = _build_url(req.cancel_path or "/become-a-backer")

    proxy_url = mainframe_url.rstrip("/") + "/api/v1/fiat/proxy/checkout-session"
    proxy_payload = {
        "eur_amount": req.eur_amount,
        "operator_did": operator_did,
        "operator_registry_name": operator_self_name,
        "agent_did": req.agent_did,
        "customer_email": req.customer_email,
        "developer_name": requested_dev_name or req.developer_name,
        "agent_name": requested_agent_name or req.agent_name,
        "return_path": return_url_full,
        "cancel_path": cancel_url_full,
        "tos_accepted": req.tos_accepted,
        "tos_version": req.tos_version,
        # Operator branding overrides — sourced from env (operator's own brand).
        "operator_branding": {
            "product_name": os.getenv("OPERATOR_BRAND_PRODUCT_NAME") or None,
            "statement_descriptor": os.getenv("OPERATOR_BRAND_STATEMENT_DESCRIPTOR") or None,
            "product_image_url": os.getenv("OPERATOR_BRAND_PRODUCT_IMAGE_URL") or None,
            "accent_color": os.getenv("OPERATOR_BRAND_ACCENT_COLOR") or None,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=20.0, verify=False) as client:
            resp = await client.post(
                proxy_url,
                json=proxy_payload,
                headers={
                    "X-Federation-License": license_key,
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code >= 300:
                detail = resp.text[:300]
                logger.warning(
                    "[fiat-op] mainframe proxy refused %s: %s",
                    resp.status_code, detail,
                )
                purchase.status = FiatPurchaseStatus.FAILED.value
                purchase.failure_reason = f"mainframe_proxy_{resp.status_code}: {detail}"
                await db.commit()
                # Surface mainframe's status to caller (400 → 400, 403 → 403, etc.)
                raise HTTPException(
                    status_code=resp.status_code if 400 <= resp.status_code < 600 else 502,
                    detail=f"mainframe proxy: {detail}",
                )
            mf_resp = resp.json()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[fiat-op] mainframe proxy call error")
        purchase.status = FiatPurchaseStatus.FAILED.value
        purchase.failure_reason = f"mainframe_proxy_error: {str(exc)[:300]}"
        await db.commit()
        raise HTTPException(502, f"Mainframe proxy unreachable: {exc}")

    # Back-fill local row from mainframe response.
    purchase.mainframe_fiat_purchase_id = mf_resp.get("mainframe_fiat_purchase_id") or mf_resp.get("fiat_purchase_id")
    purchase.stripe_session_id = mf_resp.get("stripe_session_id") or purchase.stripe_session_id
    purchase.amount_eur = Decimal(str(mf_resp.get("eur_amount") or "0"))
    purchase.amount_avt = Decimal(str(mf_resp.get("avt_amount") or "0"))
    if purchase.amount_eur > 0:
        purchase.avt_per_eur_rate = (purchase.amount_avt / purchase.amount_eur).quantize(Decimal("0.01"))
    purchase.tier_label = mf_resp.get("tier_label") or purchase.tier_label
    await db.commit()
    await db.refresh(purchase)

    return CheckoutResponse(
        fiat_purchase_id=purchase.id,
        stripe_session_id=purchase.stripe_session_id,
        checkout_url=mf_resp.get("checkout_url", ""),
        eur_amount=str(purchase.amount_eur),
        avt_amount=str(purchase.amount_avt),
        tier_label=purchase.tier_label,
        expires_at=mf_resp.get("expires_at", ""),
        anonymous_flow=is_anonymous,
    )


# =============================================================================
# PB-2 — Operator-side routed-settle callback receiver
# =============================================================================

async def _operator_settle_routed_purchase(
    db: AsyncSession,
    fp: FiatPurchase,
    body: dict,
    *,
    source: str = "http_callback",
) -> dict:
    """PB-2 (2026-05-10): Operator-side settlement helper. Idempotent.

    Called by BOTH:
      - HTTP push handler (`/api/v1/federation/routed-settle-callback`) after HMAC verify.
      - Event-sourced fallback reactor (`reactor_fiat_routed_settlement_initiated`) after event dispatch.

    Both paths are idempotent on `fp.status == COMPLETED`. Whichever arrives
    first does the work; the second is a no-op. Mirrors prod's cross-frame
    sync (HTTP) + async (reactor) dual-path pattern.

    Returns: `{"status": "ok", "fiat_purchase_id": fp.id, "noop": bool}`.
    Raises HTTPException on hard failures (anon resolve fail, TEG transfer fail).
    """
    mf_purchase_id = body.get("mainframe_fiat_purchase_id") or fp.mainframe_fiat_purchase_id

    # Idempotent early return — both paths can fire; whichever is first wins.
    if fp.status == FiatPurchaseStatus.COMPLETED.value:
        logger.info(
            "[fiat-settle:%s] purchase %s already COMPLETED — noop (mainframe_id=%s)",
            source, fp.id, mf_purchase_id,
        )
        return {"status": "ok", "fiat_purchase_id": fp.id, "noop": True}

    # Authoritative-merge from mainframe-supplied body (in case mainframe
    # adjusted amounts post-creation — defensive merge).
    fp.amount_eur = Decimal(str(body.get("amount_eur") or fp.amount_eur))
    fp.amount_avt = Decimal(str(body.get("amount_avt") or fp.amount_avt))
    fp.tier_label = body.get("tier_label") or fp.tier_label
    fp.status = FiatPurchaseStatus.PROCESSING.value
    fp.cross_teg_correlation_id = body.get("cross_teg_correlation_id") or fp.cross_teg_correlation_id
    if body.get("stripe_session_id"):
        fp.stripe_session_id = body["stripe_session_id"]
    if body.get("stripe_payment_intent_id"):
        fp.stripe_payment_intent_id = body["stripe_payment_intent_id"]
    await db.commit()

    # Resolve target agent (anonymous flow auto-creates Developer + Agent).
    target_agent_did: Optional[str] = fp.agent_did
    developer_id: Optional[int] = fp.developer_id
    if fp.anonymous_flow and not target_agent_did:
        try:
            target_agent_did, developer_id = await _resolve_or_create_anonymous(
                db=db,
                email=fp.customer_email or body.get("customer_email") or "",
                purchase=fp,
                requested_developer_name=fp.requested_developer_name or body.get("requested_developer_name"),
                requested_agent_name=fp.requested_agent_name or body.get("requested_agent_name"),
            )
            fp.agent_did = target_agent_did
            fp.developer_id = developer_id
            await db.commit()
        except Exception as exc:
            logger.exception(
                "[fiat-settle:%s] anonymous resolution failed for mainframe_id=%s",
                source, mf_purchase_id,
            )
            fp.status = FiatPurchaseStatus.FAILED.value
            fp.failure_reason = f"anonymous_resolve_failed: {str(exc)[:300]}"
            await db.commit()
            raise HTTPException(500, f"anon resolve failed: {exc}")

    if not target_agent_did:
        fp.status = FiatPurchaseStatus.FAILED.value
        fp.failure_reason = "no_target_agent_resolved"
        await db.commit()
        raise HTTPException(500, "no target agent resolved")

    # Fund local agent: local TEG treasury → buyer's agent.
    teg_url = os.getenv("TEG_API_BASE_URL") or os.getenv("PARTNER_TEG_URL") or "http://teg-layer:8080"
    teg_admin_key = os.getenv("TEG_ADMIN_API_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=get_httpx_verify()) as client:
            resp = await client.post(
                f"{teg_url}/api/v1/admin/treasury/transfer",
                headers={
                    "Authorization": f"Bearer {teg_admin_key}",
                    # deterministic per-purchase key → TEG treasury/transfer dedups; closes the
                    # HTTP-callback vs fallback-reactor dual-fire double-mint
                    "Idempotency-Key": f"fiat-routed-{fp.id}",
                },
                json={
                    "target_agent_id": target_agent_did,
                    "amount": str(fp.amount_avt),
                    "reason": "fiat_purchase",
                    "reference_id": fp.id,
                },
            )
            if resp.status_code != 200:
                fp.status = FiatPurchaseStatus.FAILED.value
                fp.failure_reason = f"local_treasury_transfer_failed: {resp.status_code} {resp.text[:200]}"
                await db.commit()
                logger.error(
                    "[fiat-settle:%s] local treasury transfer failed %s: %s",
                    source, resp.status_code, resp.text[:300],
                )
                raise HTTPException(500, "local treasury transfer failed")
            tx_data = resp.json()
            tx_id = tx_data.get("transaction_id", "")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[fiat-settle:%s] local treasury transfer error", source)
        fp.status = FiatPurchaseStatus.FAILED.value
        fp.failure_reason = f"local_treasury_error: {str(exc)[:300]}"
        await db.commit()
        raise HTTPException(500, f"local treasury error: {exc}")

    fp.avt_transfer_tx_id = tx_id
    fp.status = FiatPurchaseStatus.COMPLETED.value
    fp.completed_at = datetime.now(timezone.utc)
    await db.commit()

    # §NOTIFV2 (2026-07-27): operator-routed settle path. Safe against double-notify because the
    # helper returns early when fp.status is already COMPLETED, so the HTTP callback and the
    # event-sourced fallback reactor cannot both get here for one purchase.
    if developer_id:  # anonymous flow can still be unresolved; notify() would no-op anyway
        try:
            import asyncio as _aio2
            from agentvault_registry.background_tasks.push_notify import notify
            _aio2.create_task(notify(
                "fiat.purchase_completed", [developer_id],
                title="Tokens purchased",
                message=f"{fp.amount_avt} AVT credited from your EUR {fp.amount_eur} purchase.",
                tags="moneybag", priority="high", click="/ui/#/wallet"))
        except Exception:  # noqa: BLE001
            logger.debug("[fiat-settle:%s] purchase notify skipped", source, exc_info=True)

    # Grant flare (cosmetic — non-fatal on failure)
    try:
        await _grant_flare(
            db=db,
            purchase=fp,
            developer_id=developer_id,
            target_agent_did=target_agent_did,
        )
    except Exception as exc:
        logger.warning("[fiat-settle:%s] flare grant failed (non-fatal): %s", source, exc)

    # Emit operator-local audit event (skip_in_projection=true).
    await _emit(
        event_type="FiatPurchaseSettled",
        aggregate_id=fp.id,
        idempotency_key=f"fiat-settled-{fp.id}",
        data={
            "fiat_purchase_id": fp.id,
            "mainframe_fiat_purchase_id": mf_purchase_id,
            "agent_did": target_agent_did,
            "amount_eur": str(fp.amount_eur),
            "amount_avt": str(fp.amount_avt),
            "tier_label": fp.tier_label,
            "tx_id": tx_id,
            "anonymous_flow": fp.anonymous_flow,
            "routed": True,
            "settle_source": source,
        },
    )

    # PB-2 (2026-05-10) Event-sourced loop closure: emit
    # FiatRoutedSettlementCompleted so the mainframe-side reactor
    # (reactor_fiat_routed_settlement_completed.py) can mark the
    # mainframe row COMPLETED + operator_callback_status='success_via_event'.
    # Idempotent: mainframe reactor checks current status before update.
    await _emit(
        event_type="FiatRoutedSettlementCompleted",
        aggregate_id=mf_purchase_id or fp.id,
        idempotency_key=f"fiat-routed-completed-{mf_purchase_id or fp.id}",
        data={
            "mainframe_fiat_purchase_id": mf_purchase_id,
            "operator_did": _operator_self_did(),
            "operator_registry_name": _operator_registry_self_name(),
            "operator_fiat_purchase_id": fp.id,
            "agent_did": target_agent_did,
            "amount_avt": str(fp.amount_avt),
            "tx_id": tx_id,
            "settle_source": source,
        },
    )

    # Best-effort post-purchase email
    asyncio.create_task(_send_purchase_email(fp, target_agent_did, tx_id))

    logger.info(
        "[fiat-settle:%s] purchase %s settled (mainframe=%s) — %s AVT to %s tx=%s",
        source, fp.id, mf_purchase_id, fp.amount_avt, target_agent_did, tx_id,
    )
    return {"status": "ok", "fiat_purchase_id": fp.id, "noop": False}


@federation_router.post(
    "/routed-settle-callback",
    include_in_schema=False,
    summary="Receive mainframe → operator routed-settle callback (HMAC-verified, mTLS via nginx-federation)",
)
async def routed_settle_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Mainframe → operator: 'AVT delivered to your treasury, fund the buyer's agent.'

    Auth: HMAC-SHA256 of body + shared secret in X-Mainframe-Signature header
    (Stripe-compatible format `t=<ts>,v1=<sig>`). Secret source: mainframe's
    peer_registries.callback_secret for this operator, or fallback
    FEDERATION_INTERNAL_SECRET (sandbox shortcut).

    Idempotency: local FiatPurchase row keyed by mainframe_fiat_purchase_id.
    Repeat callbacks return 200 immediately if status is already COMPLETED.

    Steps:
      1. Verify HMAC + freshness.
      2. Lookup local FiatPurchase row by mainframe_fiat_purchase_id.
      3. If status==COMPLETED: 200 OK no-op (idempotent).
      4. If anonymous flow: auto-create Developer + Agent (reuse the
         _resolve_or_create_anonymous helper used by direct flow).
      5. Call local TEG /admin/treasury/transfer { target_agent_id, amount,
         reason='fiat_purchase' } — funds buyer's local agent.
      6. Update local row: status=COMPLETED, agent_did, avt_transfer_tx_id.
      7. Send fiat_purchase_completed.html.j2 (operator's SMTP/theme).
      8. Grant flare cosmetic via existing _grant_flare.
      9. Emit local FiatPurchaseSettled (skip_in_projection=true).
    """
    # Operator-only — mainframe calls this on operator registries
    if _is_fiat_genesis():
        raise HTTPException(404, "Endpoint is operator-only")

    raw_body = await request.body()
    sig_header = request.headers.get("X-Mainframe-Signature", "")
    from ..services.fiat_routed_callback import verify_callback
    try:
        body = verify_callback(
            raw_body=raw_body,
            signature_header=sig_header,
            peer_callback_secret=None,  # operator falls through to FEDERATION_INTERNAL_SECRET
        )
    except ValueError as exc:
        logger.warning("[fiat-cb] HMAC verify failed: %s", exc)
        raise HTTPException(401, f"Invalid signature: {exc}")

    mf_purchase_id = body.get("mainframe_fiat_purchase_id")
    if not mf_purchase_id:
        raise HTTPException(400, "mainframe_fiat_purchase_id required")

    # Locate local row
    row = await db.execute(
        select(FiatPurchase).where(FiatPurchase.mainframe_fiat_purchase_id == mf_purchase_id)
    )
    fp = row.scalar_one_or_none()
    if not fp:
        logger.error("[fiat-cb] no local FiatPurchase for mainframe_id=%s", mf_purchase_id)
        raise HTTPException(404, "FiatPurchase not found")

    # Delegate to the shared idempotent settle helper. Both this HTTP path and
    # the event-sourced fallback reactor (reactor_fiat_routed_settlement_initiated)
    # call the same helper — whichever arrives first does the work; the second
    # is a no-op via the COMPLETED idempotency guard inside the helper.
    return await _operator_settle_routed_purchase(
        db=db,
        fp=fp,
        body=body,
        source="http_callback",
    )


# ── §CHATDESK C7 — ORG TREASURY TOP-UP: a fiat door, built DARK ──────────────
# The Commander's constraint verbatim (2026-08-28): the fiat lane "CAN and
# should be included and expanded. we just dont activate it". So this lane
# exists, is fail-CLOSED behind THREE locks, and is deliberately NOT a new
# money path: when the locks open it composes two rails that already exist —
# the standard checkout credits the org admin's own agent (the EXISTING settle,
# untouched), and the response names the EXISTING org remit door
# (/organizations/{org_id}/treasury/remit) as the completing step. No new
# schema, no new settle code, nothing for an auditor to re-learn.
def _org_topup_enabled() -> bool:
    return os.getenv("FIAT_ORG_TOPUP_ENABLED", "false").lower() == "true"


class OrgTopupCheckoutRequest(BaseModel):
    org_id: str = Field(..., max_length=64)
    eur_amount: str = Field(..., description="EUR amount, '1.00'-'500.00'")
    agent_did: str = Field(..., max_length=120,
                           description="The admin's own org-assigned agent that receives the AVT and remits it on")


@router.post("/org-topup/checkout-session",
             summary="Org treasury top-up via fiat (DARK: three locks, fail-closed)")
async def create_org_topup_checkout(
    req: OrgTopupCheckoutRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    # LOCK 1 — the lane's own switch, checked FIRST so a dark registry leaks
    # nothing about orgs, agents or Stripe wiring. Absence of a decision must
    # never read as permission (the §OURSTATE-5c fiat-door law).
    if not _org_topup_enabled():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "The org treasury fiat top-up lane is not enabled on this registry "
            "(FIAT_ORG_TOPUP_ENABLED). The lane ships dark by design.",
        )
    # LOCKS 2+3 — genesis-only (403) + master kill (503), the same pair every
    # fiat door answers to.
    _require_runtime_ready()
    # The same pre-money policy gates the personal checkout runs: jurisdiction
    # profile + REGAUTH fiat.lane park. Deny-only, before any money.
    from agentvault_registry.services import jurisdiction as _juris
    await _juris.check_jurisdiction(db, "fiat")
    from agentvault_registry.services import regulatory_auth as _regauth
    await _regauth.check_regulatory_authorization(db, "fiat.lane")

    # Only past every lock does identity get examined: an org ADMIN, topping up
    # through an agent that is theirs AND the org's.
    developer = await get_current_developer_unified(
        authorization=request.headers.get("Authorization"), x_api_key=None, db=db, request=request)
    from agentvault_registry.services.organization_service import OrganizationService
    if not await OrganizationService.check_member_permission(db, req.org_id, developer.id, "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "org admin role required")
    agent = (await db.execute(
        select(Agent).where(Agent.did == req.agent_did))).scalar_one_or_none()
    if agent is None or agent.developer_id != developer.id or str(agent.organization_id or "") != req.org_id:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "agent_did must be YOUR agent, assigned to THIS org")

    # Rails, not new plumbing: the standard checkout (existing settle credits
    # the agent) + the existing remit door named as the completing step.
    checkout = await create_checkout(
        CheckoutRequest(eur_amount=req.eur_amount, agent_did=req.agent_did),
        request, db, idempotency_key)
    body = checkout.model_dump() if hasattr(checkout, "model_dump") else dict(checkout)
    body["org_topup"] = {
        "org_id": req.org_id,
        "next_step": f"/api/v1/organizations/{req.org_id}/treasury/remit",
        "note": "On settle the AVT lands on your agent; the agent completes the "
                "top-up through the org remit door (agent-authorized by design — "
                "there is deliberately no admin pull).",
    }
    return body


@router.post("/stripe-webhook", summary="Stripe webhook (signature-verified)")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(..., alias="Stripe-Signature"),
):
    """
    Stripe's webhook for the fiat on-ramp: verifies the Stripe-Signature header, parses the event and hands it,
    once, to its handler: `checkout.session.completed` credits the purchased units to the buyer's agent from the
    treasury (never an issuance), `checkout.session.expired` marks the purchase failed, `charge.refunded` marks it
    refunded and alerts an administrator. A bad signature answers 400; an unknown event type answers 200 (Stripe
    retries on 4xx).
    """
    _require_runtime_ready()
    payload = await request.body()

    try:
        event = verify_webhook_signature(
            payload=payload,
            signature_header=stripe_signature,
            webhook_secret=_stripe_webhook_secret(),
        )
    except Exception as exc:
        logger.warning("[fiat] Stripe webhook signature verification failed: %s", exc)
        raise HTTPException(400, f"Stripe signature verification failed: {exc}")

    event_id = event.get("id", "")
    event_type = event.get("type", "")
    logger.info("[fiat] webhook received id=%s type=%s", event_id, event_type)

    # Background-process so Stripe's 30s timeout doesn't stress the user-facing
    # path (TEG calls + agent creation can be slow). Return 200 immediately.
    asyncio.create_task(_process_webhook_event(event))

    return {"received": True, "event_id": event_id, "event_type": event_type}


# =============================================================================
# PB-3 (BL-2) W2 — Generic provider webhook endpoint
# =============================================================================

@router.post("/webhook/{provider}", summary="Generic PSP webhook (signature-verified per-provider)")
async def provider_webhook(provider: str, request: Request):
    """
    Webhook receiver for any enabled fiat payment provider (Stripe also arrives here at /webhook/stripe;
    /stripe-webhook stays as an alias). The provider is looked up (503 when it is disabled or unknown), the
    signature verified and the body parsed (401 or 422), the event logged once (a replay answers 200), and the event
    is then handled in the background.

    \f
    Generic webhook receiver for any enabled FiatProvider.

    Per Webhook_Fiat_Layer_Strategy.md v2 §3.2 + §4.1:

      1. Provider dispatch — get_provider(name); 503 if disabled / unknown
      2. Verify + parse — provider.verify_webhook(raw_body, headers) → 401/422
      3. L1 idempotency log — INSERT into fiat_webhook_logs; replay → 200
      4. Background dispatch — _dispatch_provider_event(event)

    Stripe also flows through this endpoint at /webhook/stripe (matched by
    provider="stripe"). The legacy /stripe-webhook URL stays alive as a
    backwards-compat alias for Stripe Dashboard config (Q4 closure: function-
    level dual-decorator via dispatch-into-same-handler).
    """
    _require_runtime_ready()
    provider_name = (provider or "").lower().strip()

    psp = get_provider(provider_name)
    if psp is None:
        # Either unknown provider or its kill switch is off.
        # Per-PSP kill switch: FIAT_PROVIDER_<NAME>_ENABLED=false → 503.
        logger.warning("[fiat] webhook for unknown/disabled provider=%s", provider_name)
        raise HTTPException(503, f"Provider '{provider_name}' not enabled on this registry")

    raw_body = await request.body()
    headers = {k: v for k, v in request.headers.items()}
    source_ip = request.client.host if request.client else None

    # Step 2: Verify + parse (per-PSP)
    try:
        event = await psp.verify_webhook(raw_body, headers)
    except ValueError as exc:
        # Log signature/parse failure to fiat_webhook_logs for forensic analysis.
        try:
            await _log_inbound_webhook(
                provider_name=provider_name,
                event=None,
                raw_body=raw_body,
                signature_valid=False,
                parse_success=False,
                error_detail=str(exc)[:1000],
                source_ip=source_ip,
            )
        except Exception as log_exc:
            logger.warning("[fiat] webhook log insert failed for %s: %s", provider_name, log_exc)
        # W6 metric — distinguish signature failure from parse failure
        if "signature" in str(exc).lower() or "missing" in str(exc).lower() or "malformed" in str(exc).lower():
            _inc_signature_failed(provider_name)
        else:
            _inc_parse_failed(provider_name)
        # Emit security-audit event for signature failures (per strategy §A.3
        # cross-table sync invariants).
        sig_id = secrets.token_hex(8)  # §SILENT: one attempt, one aggregate, one key
        await _emit(
            event_type="FiatProviderSignatureFailed",
            aggregate_id=f"sigfail-{provider_name}-{sig_id}",
            idempotency_key=f"fiat-sigfail-{provider_name}-{sig_id}",
            data={
                "payment_provider": provider_name,
                "error": str(exc)[:500],
                "source_ip": source_ip,
            },
        )
        logger.warning("[fiat] %s webhook signature/parse failed: %s", provider_name, exc)
        raise HTTPException(401, f"Webhook verification failed: {exc}")

    # Step 3: L1 idempotency log
    is_fresh = await _log_inbound_webhook(
        provider_name=provider_name,
        event=event,
        raw_body=raw_body,
        signature_valid=True,
        parse_success=True,
        source_ip=source_ip,
    )
    if not is_fresh:
        # Replay — return 200 immediately. No work, no further side-effects.
        _inc_idempotent_replay(provider_name)
        return {
            "received": True,
            "event_id": event.provider_event_id,
            "event_kind": event.kind,
            "idempotent": True,
        }

    # W6 metric — fresh delivery accepted
    _inc_webhook_received(provider_name, event.kind)

    # Step 4: Background dispatch (return 200 ASAP so PSP doesn't retry).
    asyncio.create_task(_dispatch_provider_event(event))

    logger.info(
        "[fiat] %s webhook accepted id=%s kind=%s",
        provider_name, event.provider_event_id, event.kind,
    )
    return {
        "received": True,
        "event_id": event.provider_event_id,
        "event_kind": event.kind,
    }


@router.get("/providers", summary="List enabled fiat providers (public)")
async def list_fiat_providers():
    """
    The fiat payment providers enabled on this registry, with the fields a payment picker needs. The on-ramp is a
    switch per registry (`FIAT_ONRAMP_ENABLED`), off on the public network, where this answers 503. Public, no auth.

    \f
    Public — returns the providers enabled on this registry + their UI metadata.

    Per strategy §2.2. Used by v1.1 frontend BuyAVT.vue PSP picker. v1.0
    returns a static list; v1.1+ may add per-PSP display metadata.
    """
    if not _fiat_enabled():
        raise HTTPException(503, "Fiat onramp not enabled on this registry")

    providers = []
    for name in enabled_providers():
        p = get_provider(name)
        if p is None:
            continue
        providers.append({
            "name": p.name,
            "supports_anonymous_flow": p.supports_anonymous_flow,
            "supports_routed_storefront": p.supports_routed_storefront,
            "signature_header_name": p.signature_header_name,
        })
    return {"providers": providers}


async def _process_webhook_event(event: dict):
    """LEGACY entry point — dict-shaped event from /stripe-webhook endpoint.

    Normalizes the Stripe-shaped dict to a ProviderEvent and dispatches via the
    new PB-3 unified path. Stripe path stays byte-identical because
    StripeProvider._normalize_event preserves all fields the handlers used to
    read from the dict.
    """
    event_id = event.get("id", "")
    try:
        # Normalize Stripe dict envelope to ProviderEvent. We bypass the verify
        # step (signature was already verified by the caller endpoint) and call
        # _normalize_event directly.
        provider = get_provider("stripe")
        if provider is None:
            # Stripe disabled — fail-open (Stripe path retains parity with
            # pre-PB-3 behavior).
            logger.warning("[fiat] /stripe-webhook called but stripe provider disabled — falling back to noop")
            return
        provider_event = provider._normalize_event(event)  # type: ignore[attr-defined]
        await _dispatch_provider_event(provider_event)
    except Exception as exc:
        logger.exception("[fiat] webhook handler error event=%s: %s", event_id, exc)


async def _log_inbound_webhook(
    *,
    provider_name: str,
    event: Optional[ProviderEvent],
    raw_body: bytes,
    signature_valid: bool,
    parse_success: bool,
    fiat_purchase_id: Optional[str] = None,
    error_detail: Optional[str] = None,
    source_ip: Optional[str] = None,
) -> bool:
    """Insert a row into fiat_webhook_logs (L1 idempotency).

    Returns True if this is a fresh delivery (we own the work),
    False if this is a replay (UNIQUE(provider, provider_event_id) bounced).

    Per Webhook_Fiat_Layer_Strategy.md §4.4: replay returns 200 immediately;
    failures get logged for forensic analysis but don't mutate FiatPurchase.
    """
    body_sha256 = hashlib.sha256(raw_body).hexdigest()
    provider_event_id = event.provider_event_id if event else f"unparseable-{body_sha256[:16]}"
    event_kind = event.kind if event else "unknown"

    async with AsyncSessionLocal() as db:
        try:
            await db.execute(
                sa.text(
                    """
                    INSERT INTO fiat_webhook_logs (
                        payment_provider, provider_event_id, event_kind,
                        signature_valid, parse_success, fiat_purchase_id,
                        raw_body_sha256, processing_status, error_detail, source_ip
                    )
                    VALUES (
                        :provider, :event_id, :kind,
                        :sig_valid, :parse_ok, :fp_id,
                        :sha, :status, :err, CAST(:ip AS INET)
                    )
                    """
                ),
                {
                    "provider": provider_name,
                    "event_id": provider_event_id,
                    "kind": event_kind,
                    "sig_valid": signature_valid,
                    "parse_ok": parse_success,
                    "fp_id": fiat_purchase_id,
                    "sha": body_sha256,
                    "status": "received" if signature_valid and parse_success else "errored",
                    "err": error_detail,
                    "ip": source_ip,
                },
            )
            await db.commit()
            return True  # fresh delivery
        except sa.exc.IntegrityError:
            # UNIQUE(provider, provider_event_id) violation — this is a replay.
            await db.rollback()
            await db.execute(
                sa.text(
                    """
                    UPDATE fiat_webhook_logs
                    SET processing_status='replay'
                    WHERE payment_provider=:provider AND provider_event_id=:event_id
                          AND processing_status NOT IN ('replay', 'processed', 'errored')
                    """
                ),
                {"provider": provider_name, "event_id": provider_event_id},
            )
            await db.commit()
            logger.info("[fiat] %s webhook replay event=%s — skipping", provider_name, provider_event_id)
            return False  # replay


async def _dispatch_provider_event(event: ProviderEvent):
    """PB-3 unified dispatcher — operates on normalized ProviderEvent.

    Routes by event.kind to refactored handlers. The branching for routed-fiat
    (PB-2) lives here: `event.metadata.get("operator_did")` indicates the
    operator-storefront path. Idempotency is enforced inside each handler via
    `(payment_provider, provider_event_id)` UNIQUE — handlers no-op on replay.
    """
    try:
        if event.kind == "checkout_completed":
            if event.metadata.get("operator_did"):
                await _handle_routed_settle(event)
            else:
                await _handle_checkout_completed(event)
        elif event.kind == "checkout_expired":
            await _handle_checkout_expired(event)
        elif event.kind == "charge_refunded":
            await _handle_charge_refunded(event)
        elif event.kind == "charge_disputed":
            await _handle_charge_disputed(event)
        else:
            logger.info(
                "[fiat] %s webhook kind=%s ignored event=%s",
                event.provider, event.kind, event.provider_event_id,
            )
    except Exception as exc:
        logger.exception(
            "[fiat] %s handler error event=%s: %s",
            event.provider, event.provider_event_id, exc,
        )


async def _handle_checkout_completed(event: ProviderEvent):
    """checkout_completed → resolve target agent → mint AVT.

    PB-3 W2: accepts normalized ProviderEvent. PSP-agnostic core (anon resolution,
    reward waterfall, flare grant, provisioning credit, email, emit) is unchanged
    from PB-1. Dual-writes both legacy (stripe_*_id) and new (provider_*_id)
    columns during 30-day expand-contract transition (§A.7).
    """
    event_id = event.provider_event_id
    session_id = event.provider_session_id
    metadata = event.metadata
    purchase_id = metadata.get("fiat_purchase_id", "")

    async with AsyncSessionLocal() as db:
        # Idempotent: check both old (stripe_event_id) + new (payment_provider, provider_event_id)
        # UNIQUE indexes. Returns early on replay.
        row = await db.execute(
            select(FiatPurchase).where(
                or_(
                    FiatPurchase.stripe_event_id == event_id,
                    sa.and_(
                        FiatPurchase.payment_provider == event.provider,
                        FiatPurchase.provider_event_id == event_id,
                    ),
                )
            )
        )
        if row.scalar_one_or_none():
            logger.info("[fiat] %s webhook %s already processed, skipping", event.provider, event_id)
            return

        # Locate the FiatPurchase by metadata.fiat_purchase_id (preferred)
        # or by provider_session_id / stripe_session_id (fallback).
        purchase: Optional[FiatPurchase] = None
        if purchase_id:
            purchase = await db.get(FiatPurchase, purchase_id)
        if not purchase and session_id:
            row = await db.execute(
                select(FiatPurchase).where(
                    or_(
                        FiatPurchase.stripe_session_id == session_id,
                        sa.and_(
                            FiatPurchase.payment_provider == event.provider,
                            FiatPurchase.provider_session_id == session_id,
                        ),
                    )
                )
            )
            purchase = row.scalar_one_or_none()

        if not purchase:
            logger.error(
                "[fiat] %s webhook %s: no FiatPurchase row found "
                "(purchase_id=%s session=%s)",
                event.provider, event_id, purchase_id, session_id,
            )
            return

        # Lock in event_id NOW (before any side-effect). Dual-write old + new
        # columns during 30-day expand-contract transition.
        purchase.payment_provider = event.provider
        purchase.provider_event_id = event_id
        purchase.provider_session_id = session_id
        if event.provider_payment_id:
            purchase.provider_payment_id = event.provider_payment_id
        if event.provider == "stripe":
            purchase.stripe_event_id = event_id  # legacy column
        await db.commit()

        # Resolve target agent: anonymous flow may need to create dev + agent.
        target_agent_did: Optional[str] = purchase.agent_did
        developer_id: Optional[int] = purchase.developer_id
        try:
            if purchase.anonymous_flow and not target_agent_did:
                target_agent_did, developer_id = await _resolve_or_create_anonymous(
                    db=db,
                    email=purchase.customer_email or event.customer_email or "",
                    purchase=purchase,
                    requested_developer_name=purchase.requested_developer_name,
                    requested_agent_name=purchase.requested_agent_name,
                )
                purchase.agent_did = target_agent_did
                purchase.developer_id = developer_id
                await db.commit()
        except Exception as exc:
            logger.exception("[fiat] anonymous resolution failed for %s", purchase.id)
            purchase.status = FiatPurchaseStatus.FAILED.value
            purchase.failure_reason = f"anonymous_resolve_failed: {str(exc)[:300]}"
            await db.commit()
            return

        if not target_agent_did:
            purchase.status = FiatPurchaseStatus.FAILED.value
            purchase.failure_reason = "no_target_agent_resolved"
            await db.commit()
            return

    # §LEDGERGATE (V0599): the credit and everything after it, one place for the webhook and the retry worker.
    await _credit_and_complete(purchase.id, provider=event.provider, event_id=event_id, session_id=session_id)


async def _credit_and_complete(
    purchase_id: str, *, provider: str, event_id: Optional[str], session_id: Optional[str],
) -> Optional[str]:
    """Credit a paid direct-flow purchase and finish it: the push notice, the flare, the provisioning credit, then
    FiatPurchaseSettled, the receipt mail and the metrics. The webhook's handler and background_tasks/fiat_credit_retry
    both end here (§LEDGERGATE, V0599). Answers the purchase's status after the attempt.

    Idempotent by STATE: a purchase that is not pending or processing (completed, refunded, failed) is left alone. The
    credit rides THE registry rail for waterfall funding (services/reward_funding: one TokensTransferred per leg, the
    cached balance synced, an exhausted waterfall reported as the partial it committed) with the purchase's own
    Idempotency-Key, fiat-credit-<id>: a retry of a credit that landed but whose answer was lost replays the TEG's cached
    result instead of paying twice. (Before V0599 this flow called /admin/reward-fund itself, with no key and no leg
    events, and read an exhausted waterfall, whose partial legs ARE committed, as a failure that an admin replay would pay
    again in full.)

    Intent first: before the TEG call the purchase is marked owed (processing, "credit_owed: in_flight", due in 5 min), so
    a process that dies mid-call leaves a row the retry worker finishes with the same key. Then:
      completed       -> completed (avt_transfer_tx_id, completed_at) and the finishing steps;
      exhausted       -> failed, "reward_fund_partial: ..." (the shortfall is a human's: a refund, or a top-up with a NEW
                         key; the forensic scanner and the stuck-funds board name it);
      nothing landed  -> (the ledger gate's refusal, a TEG error) owed again with a growing wait, until the budget runs out
                         (FIAT_CREDIT_MAX_ATTEMPTS): then failed, "reward_fund_failed", the human path it always was.
    """
    from ..background_tasks.fiat_credit_retry import credit_backoff_seconds, credit_max_attempts, count_credit
    from ..services.ledger_unavailable import refusal_from_error
    from ..services.reward_funding import fund_reward_via_waterfall

    async with AsyncSessionLocal() as db:
        purchase = await db.get(FiatPurchase, purchase_id)
        if purchase is None:
            logger.error("[fiat] credit: no FiatPurchase %s", purchase_id)
            return None
        if purchase.status not in (FiatPurchaseStatus.PENDING.value, FiatPurchaseStatus.PROCESSING.value):
            logger.info("[fiat] credit: purchase %s is already %s; left alone", purchase.id, purchase.status)
            return purchase.status
        target_agent_did: Optional[str] = purchase.agent_did
        developer_id: Optional[int] = purchase.developer_id
        if not target_agent_did:
            purchase.status = FiatPurchaseStatus.FAILED.value
            purchase.failure_reason = "no_target_agent_resolved"
            await db.commit()
            return purchase.status

        purchase.status = FiatPurchaseStatus.PROCESSING.value
        purchase.failure_reason = "credit_owed: in_flight"
        purchase.credit_next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=300)
        await db.commit()
        try:
            res = await fund_reward_via_waterfall(
                db,
                target_agent_did=target_agent_did,
                amount=purchase.amount_avt,
                reason="fiat_purchase",
                reference_id=f"fiat-{purchase.id}",
                idempotency_key=f"fiat-credit-{purchase.id}",
            )
        except Exception as exc:  # noqa: BLE001 — TEGClientError (the gate's refusal among them) and the connection class
            why = "ledger_unavailable" if refusal_from_error(exc) is not None else "teg_error"
            purchase.credit_attempts = (purchase.credit_attempts or 0) + 1
            if purchase.credit_attempts >= credit_max_attempts():
                purchase.status = FiatPurchaseStatus.FAILED.value
                purchase.failure_reason = "reward_fund_failed"
                purchase.credit_next_attempt_at = None
                await db.commit()
                count_credit("dead")
                _inc_purchase_failed(provider, reason="reward_fund_failed")
                logger.error(
                    "[FIAT-CREDIT-DEAD] purchase %s: %s AVT to %s not credited after %d attempts (%s: %s); paid at %s: "
                    "replay or refund by hand", purchase.id, purchase.amount_avt, target_agent_did,
                    purchase.credit_attempts, why, exc, provider,
                )
                return purchase.status
            purchase.failure_reason = f"credit_owed: {why}: {type(exc).__name__}: {exc}"[:500]
            purchase.credit_next_attempt_at = datetime.now(timezone.utc) + timedelta(
                seconds=credit_backoff_seconds(purchase.credit_attempts))
            await db.commit()
            count_credit("owed")
            logger.warning(
                "[fiat] the credit of purchase %s is owed (%s, attempt %d): fiat_credit_retry pays it with the same key",
                purchase.id, why, purchase.credit_attempts,
            )
            return purchase.status

        if res.get("status") != "completed":
            purchase.status = FiatPurchaseStatus.FAILED.value
            purchase.failure_reason = (
                f"reward_fund_partial: funded {res.get('funded_amount')} of {purchase.amount_avt}, shortfall "
                f"{res.get('shortfall')} (committed; a refund or a top-up with a new key)")[:500]
            purchase.avt_transfer_tx_id = res.get("first_transaction_id") or None
            purchase.credit_next_attempt_at = None
            await db.commit()   # the helper's cache sync rides this commit
            count_credit("partial")
            _inc_purchase_failed(provider, reason="reward_fund_partial")
            logger.error(
                "[fiat] purchase %s PARTIALLY credited: %s of %s AVT to %s (shortfall %s; paid at %s): refund or top up "
                "by hand", purchase.id, res.get("funded_amount"), purchase.amount_avt, target_agent_did,
                res.get("shortfall"), provider,
            )
            return purchase.status

        tx_id = res.get("first_transaction_id") or "unknown"
        purchase.avt_transfer_tx_id = tx_id
        purchase.status = FiatPurchaseStatus.COMPLETED.value
        purchase.completed_at = datetime.now(timezone.utc)
        purchase.failure_reason = None
        purchase.credit_next_attempt_at = None
        await db.commit()   # the helper's cache sync rides this commit
        count_credit("completed")

        # §NOTIFV2 (2026-07-27): the SECOND completion path (Stripe checkout on the genesis
        # frame). Wiring only the operator-routed one above would have reproduced exactly the
        # bug this task exists to fix. Idempotent upstream on stripe_event_id.
        if developer_id:
            try:
                import asyncio as _aio2
                from agentvault_registry.background_tasks.push_notify import notify
                _aio2.create_task(notify(
                    "fiat.purchase_completed", [developer_id],
                    title="Tokens purchased",
                    message=(f"{purchase.amount_avt} AVT credited from your "
                             f"EUR {purchase.amount_eur} purchase."),
                    tags="moneybag", priority="high", click="/ui/#/wallet"))
            except Exception:  # noqa: BLE001
                logger.debug("[fiat] checkout-completed notify skipped", exc_info=True)

        # ─── Flare grant (cosmetic — no AVT effect) ─────────────────────
        # Profile flare goes on the buyer's Developer; agent flare goes on
        # the agent that received the AVT. Higher tier wins on multi-purchase.
        # Wrapped in try/except — flare failure must NEVER fail the AVT-credit
        # path (which has already succeeded by this point).
        try:
            await _grant_flare(
                db=db,
                purchase=purchase,
                developer_id=developer_id,
                target_agent_did=target_agent_did,
            )
        except Exception as exc:
            logger.warning(
                "[fiat] flare grant failed for purchase=%s (non-fatal): %s",
                purchase.id, exc,
            )

        # ─── Provisioning eligibility credit (2026-05-11, PB-1 §67) ──────
        # Cloud-op self-provisioning is a side-effect of backing the network:
        # 1 month per €25 backed, stacking, no claw-back on refund. Direct-flow
        # only — routed (operator-storefront) flows credit operator-side rows
        # which are unused for cloud-op gating today. Failure is non-fatal.
        try:
            await _grant_provisioning_credit(
                db=db,
                developer_id=developer_id,
                eur_amount=purchase.amount_eur,
                purchase_id=purchase.id,
            )
        except Exception as exc:
            logger.warning(
                "[fiat] provisioning credit failed for purchase=%s (non-fatal): %s",
                purchase.id, exc,
            )

    await _emit(
        event_type="FiatPurchaseSettled",
        aggregate_id=purchase.id,
        idempotency_key=f"fiat-settled-{purchase.id}",
        data={
            "fiat_purchase_id": purchase.id,
            "payment_provider": provider,
            "provider_event_id": event_id,
            "provider_session_id": session_id,
            # Legacy keys retained during 30-day expand-contract (§A.7).
            "stripe_event_id": event_id if provider == "stripe" else None,
            "stripe_session_id": session_id if provider == "stripe" else None,
            "agent_did": target_agent_did,
            "amount_eur": str(purchase.amount_eur),
            "amount_avt": str(purchase.amount_avt),
            "tier_label": purchase.tier_label,
            "tx_id": tx_id,
            "anonymous_flow": purchase.anonymous_flow,
        },
    )

    # Best-effort post-purchase email — anonymous flow gets the magic-link;
    # logged-in flow gets a confirmation receipt.
    asyncio.create_task(_send_purchase_email(purchase, target_agent_did, tx_id))

    # W6 metric — completed purchase + fulfilment latency
    _inc_purchase_completed(
        provider,
        anonymous=purchase.anonymous_flow,
        routed=False,  # direct flow; routed handler logs its own metric
    )
    if purchase.created_at is not None:
        try:
            fulfilment_seconds = (
                datetime.now(timezone.utc) - purchase.created_at
            ).total_seconds()
            _observe_fulfilment_duration(provider, fulfilment_seconds)
        except Exception:
            pass

    logger.info(
        "[fiat] purchase %s settled (%s): %s AVT to %s (tx=%s)",
        purchase.id, provider, purchase.amount_avt, target_agent_did, tx_id,
    )
    return FiatPurchaseStatus.COMPLETED.value

# =============================================================================
# PB-2 — Routed-flow webhook settle handler (mainframe-side)
# =============================================================================

async def _refund_stripe_payment_intent(payment_intent_id: str, reason_str: str) -> Optional[str]:
    """Best-effort full Stripe refund. Returns refund_id on success, None on
    failure (logged). Uses raw HTTPX since stripe-python may not be installed.
    """
    if not payment_intent_id:
        return None
    api_key = os.getenv("STRIPE_API_KEY", "")
    if not api_key:
        logger.error("[fiat-routed] cannot auto-refund: STRIPE_API_KEY unset")
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.stripe.com/v1/refunds",
                data={"payment_intent": payment_intent_id, "reason": "requested_by_customer"},
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code == 200:
                refund = resp.json()
                logger.warning(
                    "[fiat-routed] AUTO-REFUNDED payment_intent=%s refund=%s reason=%s",
                    payment_intent_id, refund.get("id"), reason_str,
                )
                return refund.get("id")
            logger.error(
                "[fiat-routed] Stripe refund FAILED %s: %s",
                resp.status_code, resp.text[:300],
            )
            return None
    except Exception as exc:
        logger.exception("[fiat-routed] Stripe refund error: %s", exc)
        return None


async def _post_operator_callback(
    *,
    peer: models.PeerRegistry,
    body: dict,
    timeout_sec: float = 15.0,
) -> Tuple[bool, str]:
    """PB-2 PRIMARY path: HTTP POST HMAC-signed routed-settle callback to
    operator's `/api/v1/federation/routed-settle-callback` via nginx-federation
    (mTLS-terminated). Returns (ok, error_str_or_empty).

    Auth layers (defense in depth):
      1. mTLS at operator nginx-federation (validates this mainframe's SPIRE SVID).
      2. HMAC-SHA256 signature in X-Mainframe-Signature (validates payload integrity
         + clock-skew freshness window) inside the receiver handler.

    Path lives under `/api/v1/federation/` because that's the prefix operator
    nginx-federation already proxies to the operator registry. NEVER add new
    nginx routes — Commander-locked architectural constraint.

    Self-healing SSL: uses the shared `es_ssl_helper` pattern — system CAs
    for public hostnames, SPIRE bundle for internal Docker hostnames; auto-
    rebuilds on cert rotation.
    """
    from ..services.fiat_routed_callback import sign_callback
    sig_header, payload_signed = sign_callback(body, peer.callback_secret)

    base = (peer.base_url or "").rstrip("/")
    if not base:
        return False, "peer.base_url is empty"
    # PB-2 (2026-05-10): path moved from /api/v1/fiat/internal/routed-settle-callback
    # (not routed by operator nginx-federation) to /api/v1/federation/routed-settle-callback
    # (matches existing nginx-federation `/api/v1/federation/` location block).
    url = f"{base}/api/v1/federation/routed-settle-callback"

    # Use the shared dual-mode SSL helper: system CAs for public hostnames
    # (events.theprotocol.cloud-style), SPIRE bundle for internal hostnames
    # (sandbox sandboxalpha.op-sandbox.internal-style). Mirrors event_emitter.
    from ..es_ssl_helper import get_httpx_verify
    verify = get_httpx_verify()

    try:
        async with httpx.AsyncClient(timeout=timeout_sec, verify=verify) as client:
            resp = await client.post(
                url,
                content=payload_signed.encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "X-Mainframe-Signature": sig_header,
                },
            )
            if 200 <= resp.status_code < 300:
                return True, ""
            return False, f"http={resp.status_code} body={resp.text[:200]}"
    except Exception as exc:
        return False, f"exception: {exc!r}"


UNCERTAIN_FUND_PREFIXES = ("cross_teg_fund_5xx_pending_retry", "cross_teg_fund_uncertain")


def cross_teg_fund_failure_is_final(status_code: int, resumed: bool) -> bool:
    """Whether a failed cross-TEG fund proves the operator holds nothing, so the purchase may be refunded automatically.

    §OPPROV (2026-09-27): the fund's correlation id is the purchase id, so a replay of a purchase whose earlier attempt was
    uncertain RESUMES that send at the TEG (a pending row, the treasury already debited). Only a FIRST attempt the TEG
    refused before debiting, or whose peer refused and the TEG re-credited (answered 502, a 5xx here), proves nothing
    moved. Since TEG opprov1 a 409 means either that another send already used this correlation id or that the peer
    refused a RESUMED send whose first attempt may have landed; and any refusal of a resume (a failed commit answered
    400, the older TEG's balance check on a resume) is just as blind. Refunding then pays the customer back for funds
    the operator may already hold: such a purchase stays PROCESSING for an admin replay instead."""
    return (not resumed) and 400 <= status_code < 500 and status_code != 409


async def _handle_routed_settle(event: ProviderEvent):
    """checkout_completed (routed-fiat) → cross-TEG fund → operator callback.

    PB-3 W2: accepts normalized ProviderEvent. The PB-2 2-path settlement
    (HTTP push + event-sourced fallback) is preserved verbatim — only the
    Stripe-shape dict access at the entry of the handler was changed.

    Idempotent on (payment_provider, provider_event_id) UNIQUE (new) and
    stripe_event_id UNIQUE (legacy, dual-checked during 30-day transition).
    On cross-TEG-fund failure with deterministic 4xx → auto-refund + mark
    FAILED. On TEG transient/5xx → leave PROCESSING for reconciler. On
    cross-TEG-fund success but callback failure → mark callback_status=failed
    and let reconciler retry (DO NOT refund — AVT is already in operator
    treasury, this is a last-mile delivery problem).
    """
    event_id = event.provider_event_id
    session_id = event.provider_session_id
    metadata = event.metadata
    purchase_id = metadata.get("fiat_purchase_id", "")
    operator_did = metadata.get("operator_did", "")
    operator_registry_name = metadata.get("operator_registry_name", "")

    logger.info(
        "[fiat-routed] %s webhook id=%s session=%s purchase=%s op=%s",
        event.provider, event_id, session_id, purchase_id, operator_did,
    )

    async with AsyncSessionLocal() as db:
        # Idempotency: check both legacy and new UNIQUE constraints.
        existing = await db.execute(
            select(FiatPurchase).where(
                or_(
                    FiatPurchase.stripe_event_id == event_id,
                    sa.and_(
                        FiatPurchase.payment_provider == event.provider,
                        FiatPurchase.provider_event_id == event_id,
                    ),
                )
            )
        )
        if existing.scalar_one_or_none():
            logger.info("[fiat-routed] %s webhook %s already processed", event.provider, event_id)
            return

        # Locate the mainframe-side row.
        purchase: Optional[FiatPurchase] = None
        if purchase_id:
            purchase = await db.get(FiatPurchase, purchase_id)
        if not purchase and session_id:
            row = await db.execute(
                select(FiatPurchase).where(
                    or_(
                        FiatPurchase.stripe_session_id == session_id,
                        sa.and_(
                            FiatPurchase.payment_provider == event.provider,
                            FiatPurchase.provider_session_id == session_id,
                        ),
                    )
                )
            )
            purchase = row.scalar_one_or_none()
        if not purchase:
            logger.error(
                "[fiat-routed] %s webhook %s: no FiatPurchase row (purchase_id=%s session=%s)",
                event.provider, event_id, purchase_id, session_id,
            )
            return

        if not purchase.routed:
            logger.error(
                "[fiat-routed] %s webhook %s: purchase %s has routed=false but operator_did in metadata — routing branch invoked in error",
                event.provider, event_id, purchase.id,
            )
            return

        # Lock event_id NOW (idempotency anchor). Dual-write old + new columns
        # during 30-day expand-contract transition.
        purchase.payment_provider = event.provider
        purchase.provider_event_id = event_id
        purchase.provider_session_id = session_id
        if event.provider_payment_id:
            purchase.provider_payment_id = event.provider_payment_id
        if event.provider == "stripe":
            purchase.stripe_event_id = event_id  # legacy column
        purchase.status = FiatPurchaseStatus.PROCESSING.value
        await db.commit()

        # Pre-flight: target peer must still be ACTIVE + license active.
        peer_q = await db.execute(
            select(models.PeerRegistry).where(
                models.PeerRegistry.name == purchase.target_operator_registry_name,
                models.PeerRegistry.status == "ACTIVE",
            )
        )
        peer = peer_q.scalar_one_or_none()
        if peer is None:
            logger.warning(
                "[fiat-routed] target peer '%s' not ACTIVE — refunding Stripe",
                purchase.target_operator_registry_name,
            )
            refund_id = await _refund_stripe_payment_intent(
                purchase.stripe_payment_intent_id or "",
                f"target_peer_inactive: {purchase.target_operator_registry_name}",
            )
            purchase.status = FiatPurchaseStatus.FAILED.value
            purchase.failure_reason = f"target_peer_inactive (refund={refund_id or 'failed'})"
            purchase.refunded_at = datetime.now(timezone.utc) if refund_id else None
            await db.commit()
            return

        # Step 1: cross-TEG fund (mainframe TEG → operator TEG).
        # Calls the existing endpoint via local HTTP so the 2-phase commit +
        # rollback path is shared with admin-initiated cross-teg-funds.
        local_url = f"http://localhost:8000/api/v1/teg/treasury/cross-teg-fund"
        # Mainframe-side admin auth: synthesize a Commander dev-JWT via the
        # internal admin path. Simpler approach: call cross_teg_treasury_fund
        # directly in-process — same module, no HTTP roundtrip needed.
        try:
            from .teg_integration import (
                cross_teg_treasury_fund,
                CrossTEGTreasuryFundRequest,
            )
            # Resolve a Commander Developer to satisfy the admin_treasury dep.
            # Webhook context has no JWT, so we call the function with a
            # synthesized Commander identity — admin_treasury is enforced at
            # the dep layer; we bypass that here because the webhook is
            # signature-verified and acts as a system actor.
            commander_q = await db.execute(
                select(models.Developer).where(models.Developer.is_admin == True).limit(1)
            )
            commander = commander_q.scalar_one_or_none()
            if commander is None:
                raise RuntimeError("No admin developer found for system context")
            cross_req = CrossTEGTreasuryFundRequest(
                target_registry=purchase.target_operator_registry_name,
                amount=str(purchase.amount_avt),
                reason="fiat_routed_settle",
                correlation_id=purchase.id,  # FiatPurchase.id is the idempotency anchor
            )
            cross_result = await cross_teg_treasury_fund(
                request=cross_req,
                db=db,
                current_admin=commander,
            )
            purchase.cross_teg_correlation_id = cross_result.get("correlation_id") or purchase.id
            await db.commit()
        except HTTPException as http_exc:
            # 4xx on a FIRST attempt (409 excepted) → deterministic failure → auto-refund
            # 5xx (502/503), a 409, or any failure of a replay that resumes an uncertain send → leave PROCESSING
            _resumed = str(purchase.failure_reason or "").startswith(UNCERTAIN_FUND_PREFIXES)
            if cross_teg_fund_failure_is_final(http_exc.status_code, _resumed):
                logger.warning(
                    "[fiat-routed] cross-teg-fund 4xx %s — auto-refunding: %s",
                    http_exc.status_code, http_exc.detail,
                )
                refund_id = await _refund_stripe_payment_intent(
                    purchase.stripe_payment_intent_id or "",
                    f"cross_teg_fund_4xx_{http_exc.status_code}",
                )
                purchase.status = FiatPurchaseStatus.FAILED.value
                purchase.failure_reason = f"cross_teg_fund_4xx: {str(http_exc.detail)[:300]}"
                purchase.refunded_at = datetime.now(timezone.utc) if refund_id else None
                await db.commit()
                return
            else:
                _kind = "5xx_pending_retry" if http_exc.status_code >= 500 else "uncertain"
                logger.error(
                    "[fiat-routed] cross-teg-fund %s (%s) — leaving PROCESSING, no automatic refund: %s",
                    http_exc.status_code, "transient" if _kind.startswith("5xx") else
                    ("a resumed send" if _resumed else "the send may have landed"), http_exc.detail,
                )
                purchase.failure_reason = f"cross_teg_fund_{_kind}: {http_exc.status_code} {str(http_exc.detail)[:290]}"
                await db.commit()
                return
        except Exception as exc:
            logger.exception("[fiat-routed] cross-teg-fund unexpected error")
            purchase.failure_reason = f"cross_teg_fund_error: {str(exc)[:300]}"
            await db.commit()
            return

        # Step 2a: Build settlement payload (used by both HTTP push + event fallback).
        callback_body = {
            "mainframe_fiat_purchase_id": purchase.id,
            "stripe_session_id": purchase.stripe_session_id,
            "stripe_payment_intent_id": purchase.stripe_payment_intent_id,
            "amount_eur": str(purchase.amount_eur),
            "amount_avt": str(purchase.amount_avt),
            "tier_label": purchase.tier_label,
            "anonymous_flow": purchase.anonymous_flow,
            "customer_email": purchase.customer_email,
            "agent_did": purchase.agent_did or "",
            "requested_developer_name": purchase.requested_developer_name,
            "requested_agent_name": purchase.requested_agent_name,
            "operator_did": purchase.target_operator_did,
            "operator_registry_name": purchase.target_operator_registry_name,
            "cross_teg_correlation_id": purchase.cross_teg_correlation_id,
        }

        # Step 2b: PB-2 (2026-05-10) Event-sourced FALLBACK path. Emit
        # FiatRoutedSettlementInitiated to EventStore. The operator-side
        # reactor (reactor_fiat_routed_settlement_initiated.py) subscribes
        # and idempotently runs the local fund-agent if the HTTP push hasn't
        # already settled the operator's row. Mirrors prod's cross-frame
        # async transfer pattern (CrossFrameInitiated reactor). Fires
        # BEFORE the HTTP push so the fallback is armed before the primary
        # path attempts.
        await _emit(
            event_type="FiatRoutedSettlementInitiated",
            aggregate_id=purchase.id,
            data=callback_body,
            idempotency_key=f"fiat-routed-initiated-{purchase.id}",
        )

        # Step 2c: PRIMARY path — HTTP push to operator over mTLS.
        purchase.operator_callback_attempts = (purchase.operator_callback_attempts or 0) + 1
        purchase.operator_callback_last_attempted_at = datetime.now(timezone.utc)
        ok, err = await _post_operator_callback(peer=peer, body=callback_body)
        if ok:
            purchase.operator_callback_status = "success"
            purchase.status = FiatPurchaseStatus.COMPLETED.value
            purchase.completed_at = datetime.now(timezone.utc)
            purchase.operator_callback_last_error = None
            logger.info(
                "[fiat-routed] purchase %s COMPLETED — callback ACK from operator %s",
                purchase.id, purchase.target_operator_did,
            )
        else:
            # HTTP push failed — leave PROCESSING. The event-sourced fallback
            # (FiatRoutedSettlementInitiated) is already in flight. The
            # operator's reactor will pick it up and settle within ~10s. The
            # mainframe-side reactor (FiatRoutedSettlementCompleted) closes
            # the loop when the operator emits the completion event.
            purchase.operator_callback_status = "failed"
            purchase.operator_callback_last_error = err[:500]
            logger.warning(
                "[fiat-routed] purchase %s HTTP callback failed (event-sourced fallback armed): %s",
                purchase.id, err,
            )
        await db.commit()

    # FiatPurchaseSettled audit event — skip_in_projection=true because the
    # underlying TokensTransferred from cross-teg-fund already counts the AVT
    # motion. This event is for audit/observability only.
    await _emit(
        event_type="FiatPurchaseSettled",
        aggregate_id=purchase.id,
        idempotency_key=f"fiat-settled-{purchase.id}",
        data={
            "fiat_purchase_id": purchase.id,
            "payment_provider": event.provider,
            "provider_event_id": event_id,
            "provider_session_id": session_id,
            # Legacy keys retained during 30-day expand-contract (§A.7).
            "stripe_event_id": event_id if event.provider == "stripe" else None,
            "stripe_session_id": session_id if event.provider == "stripe" else None,
            "amount_eur": str(purchase.amount_eur),
            "amount_avt": str(purchase.amount_avt),
            "tier_label": purchase.tier_label,
            "routed": True,
            "target_operator_did": purchase.target_operator_did,
            "target_operator_registry_name": purchase.target_operator_registry_name,
            "cross_teg_correlation_id": purchase.cross_teg_correlation_id,
            "operator_callback_status": purchase.operator_callback_status,
        },
    )


async def _handle_checkout_expired(event: ProviderEvent):
    """checkout_expired → mark FiatPurchase FAILED. PB-3 W2: ProviderEvent input."""
    session_id = event.provider_session_id
    async with AsyncSessionLocal() as db:
        row = await db.execute(
            select(FiatPurchase).where(
                or_(
                    FiatPurchase.stripe_session_id == session_id,
                    sa.and_(
                        FiatPurchase.payment_provider == event.provider,
                        FiatPurchase.provider_session_id == session_id,
                    ),
                )
            )
        )
        purchase = row.scalar_one_or_none()
        if not purchase or purchase.status != FiatPurchaseStatus.PENDING.value:
            return
        purchase.status = FiatPurchaseStatus.FAILED.value
        purchase.failure_reason = f"{event.provider}:checkout_session_expired"
        await db.commit()
        # W6 metric — expired purchase
        _inc_purchase_failed(event.provider, reason="expired")
        logger.info(
            "[fiat] %s checkout expired, purchase %s marked failed",
            event.provider, purchase.id,
        )


async def _handle_charge_refunded(event: ProviderEvent):
    """charge_refunded → flag FiatPurchase + emit audit event.

    PB-3 W2: ProviderEvent input. NOTE: AVT is NOT clawed back by this handler.
    AVT is fungible and may have been spent. Commander reviews refunds via
    admin UI and decides on enforcement (slash, suspend agent). This handler
    just flags the row.

    For SEPA-DD providers (Mollie via Single Mandate, GoCardless v1.2+) the
    refund window is materially longer than Stripe-card (8 weeks unconditional
    + 13 months unauthorized vs Stripe's ~120-day chargeback window — see
    strategy §A.11 F1). The doctrine is unchanged: no auto-claw.
    """
    event_id = event.provider_event_id
    payment_intent_id = event.provider_payment_id or ""

    async with AsyncSessionLocal() as db:
        row = await db.execute(
            select(FiatPurchase).where(
                or_(
                    FiatPurchase.stripe_payment_intent_id == payment_intent_id,
                    sa.and_(
                        FiatPurchase.payment_provider == event.provider,
                        FiatPurchase.provider_payment_id == payment_intent_id,
                    ),
                )
            )
        )
        purchase = row.scalar_one_or_none()
        if not purchase:
            logger.warning(
                "[fiat] %s refund event %s: no matching FiatPurchase (payment_id=%s)",
                event.provider, event_id, payment_intent_id,
            )
            return
        if purchase.status == FiatPurchaseStatus.REFUNDED.value:
            return
        purchase.status = FiatPurchaseStatus.REFUNDED.value
        purchase.refunded_at = datetime.now(timezone.utc)
        reason = event.refund_reason or "unknown"
        purchase.failure_reason = (
            f"{event.provider}:refunded payment_id={payment_intent_id} reason={reason}"
        )[:500]
        await db.commit()

    await _emit(
        event_type="FiatPurchaseRefunded",
        aggregate_id=purchase.id,
        idempotency_key=f"fiat-refunded-{purchase.id}",
        data={
            "fiat_purchase_id": purchase.id,
            "payment_provider": event.provider,
            "provider_event_id": event_id,
            "provider_payment_id": payment_intent_id,
            # Legacy key retained during 30-day expand-contract (§A.7).
            "stripe_event_id": event_id if event.provider == "stripe" else None,
            "amount_eur": str(purchase.amount_eur),
            "amount_avt": str(purchase.amount_avt),
            "refund_reason": reason,
            "refund_amount_eur": str(event.refund_amount_eur) if event.refund_amount_eur else None,
            "agent_did": purchase.agent_did,
        },
    )
    # W6 metric — refunded purchase
    _inc_purchase_refunded(event.provider)
    logger.warning(
        "[fiat] purchase %s REFUNDED (%s, reason=%s) — AVT not clawed back, admin review required",
        purchase.id, event.provider, reason,
    )


async def _handle_charge_disputed(event: ProviderEvent):
    """charge_disputed → flag FiatPurchase + alert SecurityAlerts (NEW in PB-3 W2).

    Chargeback / dispute opened by buyer's bank. Per Commander's no-auto-clawback
    doctrine + ToS §13.4: NO auto-enforcement. Commander reviews via admin UI;
    may use slashing endpoint manually if warranted. Strategy: §4.3.
    """
    event_id = event.provider_event_id
    payment_id = event.provider_payment_id or ""
    reason = event.metadata.get("stripe_dispute_reason") or event.metadata.get("dispute_reason") or "unspecified"

    async with AsyncSessionLocal() as db:
        row = await db.execute(
            select(FiatPurchase).where(
                or_(
                    FiatPurchase.stripe_payment_intent_id == payment_id,
                    sa.and_(
                        FiatPurchase.payment_provider == event.provider,
                        FiatPurchase.provider_payment_id == payment_id,
                    ),
                )
            )
        )
        purchase = row.scalar_one_or_none()
        if not purchase:
            logger.warning(
                "[fiat] %s dispute event %s: no matching FiatPurchase (payment_id=%s)",
                event.provider, event_id, payment_id,
            )
            return
        if purchase.disputed_at is not None:
            logger.info(
                "[fiat] %s dispute event %s: purchase %s already flagged disputed",
                event.provider, event_id, purchase.id,
            )
            return
        purchase.disputed_at = datetime.now(timezone.utc)
        purchase.dispute_reason = str(reason)[:255]
        await db.commit()

    await _emit(
        event_type="FiatPurchaseDisputed",
        aggregate_id=purchase.id,
        idempotency_key=f"fiat-disputed-{purchase.id}",
        data={
            "fiat_purchase_id": purchase.id,
            "payment_provider": event.provider,
            "provider_event_id": event_id,
            "provider_payment_id": payment_id,
            "amount_eur": str(purchase.amount_eur),
            "amount_avt": str(purchase.amount_avt),
            "dispute_reason": str(reason),
            "agent_did": purchase.agent_did,
        },
    )
    # W6 metric — disputed purchase
    _inc_purchase_disputed(event.provider)
    logger.warning(
        "[fiat] purchase %s DISPUTED (%s, reason=%s) — Commander review required (no auto-action)",
        purchase.id, event.provider, reason,
    )


async def _resolve_or_create_anonymous(
    *,
    db: AsyncSession,
    email: str,
    purchase: FiatPurchase,
    requested_developer_name: Optional[str] = None,
    requested_agent_name: Optional[str] = None,
) -> tuple[str, int]:
    """Anonymous flow webhook resolution.

    1. If a Developer with this email exists → use their first agent
       (or create one if they have none).
    2. Else → create Developer (email-confirmed=true since Stripe verified it,
       random temp password, must_change_password=true) + a first Agent.

    `requested_developer_name` / `requested_agent_name` are PB-1 onboarding
    name preferences captured at checkout. Optional. The Developer.name
    column is UNIQUE — on collision we suffix with a 6-char hex tail.

    Returns (agent_did, developer_id).
    """
    if not email:
        raise ValueError("anonymous flow without customer_email")
    email = email.strip().lower()

    row = await db.execute(select(Developer).where(Developer.email == email))
    dev: Optional[Developer] = row.scalar_one_or_none()

    if dev is None:
        temp_password = secrets.token_urlsafe(24)

        # Pick the developer name: prefer the buyer's request, fall back to
        # `{email-local}-{rand}` when no preference (or when the requested
        # name collides with an existing UNIQUE).
        local = email.split("@")[0][:32]
        candidates: list[str] = []
        if requested_developer_name:
            # Try the requested name verbatim, then with auto-suffixes.
            candidates.append(requested_developer_name)
            for _ in range(4):
                candidates.append(f"{requested_developer_name}-{secrets.token_hex(3)}")
        # Always seed the auto-fallback at the end.
        candidates.append(f"{local}-{secrets.token_hex(3)}")

        # Walk candidates: take the first one that doesn't collide.
        chosen: Optional[str] = None
        for cand in candidates:
            existing = await db.execute(
                select(Developer.id).where(Developer.name == cand).limit(1)
            )
            if existing.scalar_one_or_none() is None:
                chosen = cand
                break
        if chosen is None:
            # Pathological — every candidate collided. Fall back to a fresh
            # rand-suffixed handle that's overwhelmingly unlikely to clash.
            chosen = f"{local}-{secrets.token_hex(6)}"

        # Generate password reset token so we can email a magic-link.
        reset_token = secrets.token_urlsafe(32)
        reset_expiry = datetime.now(timezone.utc) + timedelta(days=3)
        dev = Developer(
            name=chosen,
            email=email,
            hashed_password=security.hash_password(temp_password),
            is_verified=True,                        # Stripe verified the email
            must_change_password=True,
            password_reset_token=reset_token,
            password_reset_token_expires=reset_expiry,
        )
        db.add(dev)
        await db.commit()
        await db.refresh(dev)
        logger.info(
            "[fiat] anonymous flow created Developer %s (email=%s, name=%r, requested=%r)",
            dev.id, email, chosen, requested_developer_name,
        )

    # Find an existing active agent or create one.
    row = await db.execute(
        select(Agent).where(
            Agent.creator_developer_id == dev.id,
            Agent.status == "active",
        ).limit(1)
    )
    agent: Optional[Agent] = row.scalar_one_or_none()
    if agent is None:
        agent_did, _ = await _bootstrap_agent_for_developer(
            dev=dev, db=db, requested_agent_name=requested_agent_name,
        )
        return agent_did, dev.id
    return agent.did, dev.id


async def _bootstrap_agent_for_developer(
    *, dev: Developer, db: AsyncSession,
    requested_agent_name: Optional[str] = None,
) -> tuple[str, int]:
    """Create a minimal agent for a developer who has none.

    Mirrors the onboarding pattern (DID generation + client credentials +
    agent_card creation + TEG profile) but with a default Agent Card so we
    don't require user input. The user can edit the card later.

    `requested_agent_name`: PB-1 onboarding name preference. When provided,
    becomes the Agent Card's display name; otherwise we fall back to the
    `{dev.name}-wallet` slug.
    """
    from .onboarding import (
        generate_agent_did,
        mint_unique_agent_did,
        generate_client_credentials,
        create_teg_profile_for_agent,
    )
    from ..crud import agent as agent_crud
    from ..crud import agent_card as card_crud
    from .. import schemas

    # Use enhanced create_agent if available (matches /onboard/create_agent path)
    try:
        from ..crud_agent_enhanced import create_agent as create_agent_db
    except ImportError:
        create_agent_db = agent_crud.create_agent

    agent_did = await mint_unique_agent_did(db, "theprotocol", site="fiat_onramp")  # §DIDWIDEN
    client_id, client_secret = generate_client_credentials()
    new_agent = await create_agent_db(
        db=db,
        did=agent_did,
        client_id=client_id,
        client_secret=client_secret,
        creator_developer_id=dev.id,
        public_key_jwk=None,
    )

    # Pick the display name: prefer buyer's requested_agent_name, otherwise
    # the auto-slug. Card.name is NOT UNIQUE, so no collision check needed.
    card_name = requested_agent_name or f"{dev.name}-wallet"
    # humanReadableId: keep deterministic shape so SDK consumers can reason
    # about it. Use a slugified form of the name + the dev handle.
    slug = _re.sub(r"[^a-z0-9-]+", "-", card_name.lower()).strip("-") or "wallet"

    # Default Agent Card — must conform to A2A v0.3.0 (AgentCard pydantic model
    # in agentvault_library). REQUIRED keys: protocolVersion, humanReadableId,
    # agentVersion, name, description, url, provider.name, capabilities.streaming,
    # authSchemes (list, min 1, scheme in {apiKey,bearer,oauth2,none}). Match
    # existing wallet-agent shape used elsewhere in registry.
    default_card = {
        "protocolVersion": "0.3.0",
        "humanReadableId": f"{dev.name}/{slug}",
        "agentVersion": "1.0.0",
        "name": card_name,
        "description": (
            "Auto-created wallet agent for AVT credits purchased via fiat. "
            "Update via Agent Builder to enable this agent for service work."
        ),
        "url": f"https://api.theprotocol.cloud/wallet/{agent_did}",
        "provider": {"name": dev.name},
        "capabilities": {"streaming": False, "supportsPushNotifications": False},
        "authSchemes": [
            {
                "scheme": "oauth2",
                "tokenUrl": "https://api.theprotocol.cloud/auth/agent/token",
                "description": "OAuth 2.0 client credentials. Use the agent's client_id/client_secret.",
            }
        ],
        "skills": [],
        "tags": ["wallet", "fiat-purchase"],
    }
    try:
        agent_card = await card_crud.create_agent_card(
            db=db,
            developer_id=dev.id,
            card_create=schemas.AgentCardCreate(card_data=default_card),
        )
        agent_card.agent_did = agent_did
        db.add(agent_card)
        await db.commit()
    except Exception as exc:
        logger.warning("[fiat] anonymous flow agent_card create failed (non-fatal): %s", exc)

    try:
        await create_teg_profile_for_agent(agent_did)
    except Exception as exc:
        logger.warning("[fiat] anonymous flow TEG profile create failed: %s", exc)

    logger.info(
        "[fiat] bootstrap anonymous-flow agent %s for developer %s", agent_did, dev.id
    )
    return agent_did, new_agent.id


async def _send_purchase_email(
    purchase: FiatPurchase, target_agent_did: str, tx_id: str,
):
    """Best-effort post-purchase email."""
    try:
        from ..email_utils import send_themed_email
    except ImportError:
        logger.warning("[fiat] email_utils unavailable, skipping receipt email")
        return

    if not purchase.customer_email:
        return

    # Format AVT as integer with thousands separators ("10,000 AVT" not "10000.000000 AVT").
    avt_int = int(Decimal(purchase.amount_avt).quantize(Decimal("1")))
    avt_pretty = f"{avt_int:,}"
    eur_pretty = f"{Decimal(purchase.amount_eur).quantize(Decimal('0.01'))}"

    # PB-1 Phase Q (2026-05-09): include flare info in the email context so
    # the receipt can render the earned badge prominently. Customization fields
    # are sourced from the developer's flare row (set by _grant_flare).
    flare_ctx: dict = {
        "flare_tier": _flare_for_tier(purchase.tier_label) or "sentinel",
        "flare_display_name": None,
        "flare_tagline": None,
    }
    async with AsyncSessionLocal() as _db:
        if purchase.developer_id:
            _drow = await _db.execute(
                select(Developer).where(Developer.id == purchase.developer_id)
            )
            _dev = _drow.scalar_one_or_none()
            if _dev:
                # Fall through to the dev's actual customization if present.
                flare_ctx["flare_display_name"] = _dev.flare_display_name
                flare_ctx["flare_tagline"] = _dev.flare_tagline
                # If the dev's flare_tier is HIGHER than this purchase's tier
                # (e.g. Founder buyer making a Sentinel-tier follow-on), show
                # the higher tier — the email reflects the buyer's REAL identity.
                if _dev.flare_tier and _FLARE_RANK.get(_dev.flare_tier, 0) >= _FLARE_RANK.get(flare_ctx["flare_tier"], 0):
                    flare_ctx["flare_tier"] = _dev.flare_tier

    if purchase.anonymous_flow:
        # Magic-link login email — the password_reset_token doubles as a magic link.
        async with AsyncSessionLocal() as db:
            row = await db.execute(
                select(Developer).where(Developer.id == purchase.developer_id)
            )
            dev = row.scalar_one_or_none()
        if not dev or not dev.password_reset_token:
            return
        magic_link = (
            f"{str(settings.BASE_URL).rstrip('/')}/ui#/reset-password"
            f"?token={dev.password_reset_token}"
        )
        await send_themed_email(
            subject=f"Your {avt_pretty} AVT credits are ready",
            recipients=[purchase.customer_email],
            template="fiat_anonymous_welcome",
            theme="neural",
            context={
                "amount_eur": eur_pretty,
                "amount_avt": avt_pretty,
                "agent_did": target_agent_did,
                "magic_link": magic_link,
                "tier_label": purchase.tier_label,
                **flare_ctx,
            },
        )
    else:
        await send_themed_email(
            subject=f"AVT credits delivered — {avt_pretty} AVT",
            recipients=[purchase.customer_email],
            template="fiat_purchase_completed",
            theme="neural",
            context={
                "amount_eur": eur_pretty,
                "amount_avt": avt_pretty,
                "agent_did": target_agent_did,
                "tx_id": tx_id,
                "tier_label": purchase.tier_label,
                **flare_ctx,
            },
        )


async def _grant_flare(
    *,
    db: AsyncSession,
    purchase: FiatPurchase,
    developer_id: Optional[int],
    target_agent_did: Optional[str],
):
    """Grant profile + agent flare for a settled fiat purchase.

    Logic:
      • Profile flare → developer.flare_tier (auto, permanent, higher-wins).
      • Agent flare → agents[target_agent_did].flare_tier (movable, higher-wins).
      • Both stamp granted_at + source_purchase_id for audit.
      • flare_id (UUID) is generated on FIRST grant only; preserved across
        tier upgrades — the buyer's flare keeps its canonical identity even
        when they upgrade Sentinel → Architect → Founder.

    A re-process of the SAME purchase is idempotent because we only overwrite
    when the proposed tier strictly outranks the existing tier; if the same
    tier is proposed twice, the timestamp + source_id keep the original grant.

    Cosmetic only — zero AVT motion, no event emission, no side effects beyond
    the two row updates.

    §FLARESHOP (2026-08-16): the row-writing half now lives in
    `services/flare_grants.grant_flare_tier` (shared with the local-currency
    shop). What stays here is the FIAT-ONLY half: the tier-label mapping and
    the cumulative Shadow Chancellor evaluation, which sums FiatPurchase EUR
    and must never be reachable from a local-currency purchase.
    """
    proposed = _flare_for_tier(purchase.tier_label)
    if not proposed:
        return

    await _flare_grants.grant_flare_tier(
        db,
        developer_id=developer_id,
        target_agent_did=target_agent_did,
        proposed=proposed,
        source_kind="fiat",
        source_id=purchase.id,
    )

    # ─── Shadow Chancellor cumulative-spend check (PB-1 §11, 2026-05-11) ──
    # After the per-purchase flare grant, evaluate whether the developer's
    # lifetime cumulative spend has reached the Shadow Chancellor threshold.
    # If so, propose `shadow_chancellor` — rank=4 outranks Founder (rank=3),
    # so it overwrites via _should_overwrite_flare. Idempotent on rank
    # (re-firing on later purchases is a noop because shadow_chancellor
    # equals existing). Hidden from public tier-pitch surfaces by frontend
    # convention; backend treats it as just another flare value.
    if developer_id is not None:
        await _evaluate_shadow_chancellor(
            db=db,
            developer_id=developer_id,
            target_agent_did=target_agent_did,
            triggering_purchase_id=purchase.id,
        )
    return



async def _evaluate_shadow_chancellor(
    *,
    db: AsyncSession,
    developer_id: int,
    target_agent_did: Optional[str],
    triggering_purchase_id: str,
):
    """Sum the developer's lifetime COMPLETED fiat-purchase EUR. If the total
    has reached `_SHADOW_CHANCELLOR_THRESHOLD_EUR`, grant the shadow_chancellor
    flare on both the Developer row and the agent that received this purchase's
    AVT. Higher-rank-wins via `_should_overwrite_flare` — operator/commander
    badges (rank 50/99) survive untouched.

    Sum is computed cluster-side via SQL aggregate to avoid Python decimal
    rounding. Filter on COMPLETED status only — pending/failed/refunded
    purchases don't count toward the threshold even if they later complete.
    """
    sum_q = await db.execute(
        select(sa.func.coalesce(sa.func.sum(FiatPurchase.amount_eur), 0))
        .where(
            FiatPurchase.developer_id == developer_id,
            FiatPurchase.status == FiatPurchaseStatus.COMPLETED.value,
            # Sentinel-tier purchases (€1-€19.99) excluded from cumulative threshold.
            # Sentinel is the entry tier — accumulating €500 of €1 buys would
            # trivialize the rare flare. Architect (€20+) and Founder (€100+) count.
            FiatPurchase.amount_eur >= _SHADOW_CHANCELLOR_MIN_EUR_PER_PURCHASE,
        )
    )
    cumulative_eur = Decimal(str(sum_q.scalar() or "0"))
    if cumulative_eur < _SHADOW_CHANCELLOR_THRESHOLD_EUR:
        return  # below threshold — no-op

    import uuid as _uuid
    proposed = "shadow_chancellor"
    now = datetime.now(timezone.utc)
    granted_anywhere = False

    # Profile flare
    dev_row = await db.execute(select(Developer).where(Developer.id == developer_id))
    dev = dev_row.scalar_one_or_none()
    if dev and _should_overwrite_flare(dev.flare_tier, proposed):
        dev.flare_tier = proposed
        dev.flare_granted_at = now
        dev.flare_source_purchase_id = triggering_purchase_id
        if not dev.flare_id:
            dev.flare_id = str(_uuid.uuid4())
        # Auto-set encirclement slot to shadow_chancellor on grant. Corner
        # slot stays at whatever was previously set (typically founder, which
        # is what the user earned before crossing the cumulative threshold).
        # If somehow no corner is set (shouldn't happen — €500 cumulative
        # implies at least 5 architect-tier purchases), default corner to
        # 'founder' as the visual companion.
        dev.selected_encirclement_flare = 'shadow_chancellor'
        if not dev.selected_corner_flare:
            dev.selected_corner_flare = 'founder'
        # Default the encirclement variant on first grant (2026-05-12 §14).
        # Commander mantra: tier = rank, variant = flavor. Sauron is the
        # default — pure black with red watching-eye, the menacing pick.
        if not dev.flare_encirclement_variant:
            dev.flare_encirclement_variant = DEFAULT_ENCIRCLEMENT_VARIANT
        db.add(dev)
        granted_anywhere = True

    # Agent flare (the one that received this purchase's AVT)
    if target_agent_did:
        agent_row = await db.execute(select(Agent).where(Agent.did == target_agent_did))
        agent = agent_row.scalar_one_or_none()
        if agent and _should_overwrite_flare(agent.flare_tier, proposed):
            agent.flare_tier = proposed
            agent.flare_granted_at = now
            agent.flare_source_purchase_id = triggering_purchase_id
            # §15 — default the agent's encirclement variant to 'sauron' on
            # first shadow_chancellor grant. Mirrors the Developer-side default
            # in the same function. Per-agent variant picker on /my-agents
            # lets the owner change it later.
            if proposed == 'shadow_chancellor' and not agent.flare_encirclement_variant:
                agent.flare_encirclement_variant = DEFAULT_ENCIRCLEMENT_VARIANT
            db.add(agent)
            granted_anywhere = True

    if granted_anywhere:
        # §FLARETOUCH — the same class as the revoke below: a granted flare that never touches the
        # CARD is invisible to every peer until something else moves that card. Symmetry matters
        # here, not just correctness: if only one direction propagates, a mirror can show a flare
        # the home has revoked, which is worse than showing neither.
        try:
            from ..services import enforcement_propagation as _ep
            _owned = await db.execute(select(Agent).where(Agent.creator_developer_id == developer_id))
            for _a in _owned.scalars().all():
                if getattr(_a, "did", None):
                    await _ep.touch_native_card_no_commit(db, _a.did)
        except Exception as _e:  # noqa: BLE001
            # a stale mirror is a delay, never a reason to fail a completed purchase — but it is
            # LOUD, because silence is what let the revoke side go unnoticed for months
            logger.warning("[shadow_chancellor] card touch after grant failed (mirrors will lag): %s", _e)
        await db.commit()
        logger.info(
            "[shadow_chancellor] dev=%s cumulative=%s EUR (≥ %s) — granted via purchase=%s",
            developer_id, cumulative_eur, _SHADOW_CHANCELLOR_THRESHOLD_EUR,
            triggering_purchase_id,
        )
        # Defense in depth: reconcile months from purchase history.
        # Per-purchase `_grant_provisioning_credit` already credits each
        # settle, so under normal flows this is a no-op. But seed data /
        # admin-bypass paths can leave months under-credited — the
        # reconciler closes that gap idempotently.
        try:
            await _reconcile_provisioning_credit_from_purchases(
                db=db, developer_id=developer_id,
            )
        except Exception as exc:
            logger.warning(
                "[shadow_chancellor] reconcile failed for dev=%s: %s — non-fatal",
                developer_id, exc,
            )


# ----------------------------------------------------------------------
# Provisioning eligibility (PB-1 §67, flare-gated cloud-op self-service)
# ----------------------------------------------------------------------

# Rate: 1 month of cloud-op self-provisioning eligibility per €25 backed.
# Floor division — €24 yields 0 months; €49 yields 1 month; €100 yields 4.
# Override only via env for sandbox testing; production uses the canonical 25.
_PROVISIONING_EUR_PER_MONTH = Decimal(os.getenv("PROVISIONING_EUR_PER_MONTH", "25"))
# 30 days per month — not a calendar month, just a stable interval. Stacks
# additively when the backer extends mid-period.
_PROVISIONING_DAYS_PER_MONTH = int(os.getenv("PROVISIONING_DAYS_PER_MONTH", "30"))


def _months_for_eur(eur_amount: Decimal) -> int:
    """Floor division of EUR to months — returns 0 for sub-rate purchases.

    €1–€24 → 0 months (still earns flare + AVT, just no provisioning unlock).
    €25 → 1 month. €100 → 4. €500 → 20. Caps to int.
    """
    if eur_amount is None or eur_amount <= 0 or _PROVISIONING_EUR_PER_MONTH <= 0:
        return 0
    return int(eur_amount // _PROVISIONING_EUR_PER_MONTH)


async def _grant_provisioning_credit(
    *,
    db: AsyncSession,
    developer_id: Optional[int],
    eur_amount: Decimal,
    purchase_id: str,
):
    """Extend cloud-op provisioning eligibility for a settled fiat purchase.

    Stacking math:
        unlocked_until := max(unlocked_until or NOW, NOW) + months × 30d
        months_total += months

    Sub-rate purchases (months == 0) are no-ops — they still earn the flare
    and AVT through the existing path. No event emission, no AVT motion;
    purely a row update on `developers`.

    Idempotent at the call-site level only (caller ensures one credit per
    settle). Re-credit of the same purchase_id WILL extend again, so this
    helper must NOT be called twice for the same purchase.
    """
    if developer_id is None:
        return  # anonymous-flow rows don't credit until a Developer is resolved
    months = _months_for_eur(eur_amount)
    if months <= 0:
        return  # sub-rate purchase — no provisioning unlock, just flare + AVT

    now = datetime.now(timezone.utc)
    row = await db.execute(select(Developer).where(Developer.id == developer_id))
    dev = row.scalar_one_or_none()
    if not dev:
        logger.warning(
            "[provisioning_credit] developer_id=%s not found for purchase=%s",
            developer_id, purchase_id,
        )
        return

    base = dev.provisioning_unlocked_until
    if base is None or base < now:
        base = now
    new_until = base + timedelta(days=months * _PROVISIONING_DAYS_PER_MONTH)
    dev.provisioning_unlocked_until = new_until
    dev.provisioning_months_total = (dev.provisioning_months_total or 0) + months
    db.add(dev)
    await db.commit()

    logger.info(
        "[provisioning_credit] dev=%s purchase=%s eur=%s → +%dmo "
        "unlocked_until=%s total=%d",
        developer_id, purchase_id, eur_amount, months,
        new_until.isoformat(), dev.provisioning_months_total,
    )


async def _reconcile_provisioning_credit_from_purchases(
    *,
    db: AsyncSession,
    developer_id: int,
) -> tuple[int, int]:
    """Idempotent reconciliation of provisioning months from purchase history.

    Walks COMPLETED fiat_purchases for the developer, computes total months
    that should have been credited (sum of floor(amount_eur / 25) per
    purchase — matches `_months_for_eur`), and reconciles the developer's
    `provisioning_months_total` + `provisioning_unlocked_until` to match.

    Add-only — NEVER deducts months. If the dev was over-credited (e.g.,
    admin manually bumped them in the past), the helper is a no-op.

    Use cases:
      • Backfill seed data that bypassed `_handle_direct_settle` (test
        fixtures) — the per-purchase hook didn't fire, so months are missing.
      • Reconcile after `admin_grant_flare` — admin-granted shadow_chancellor
        without cumulative crossover should still reflect correct months.
      • Reconcile after `_evaluate_shadow_chancellor` cumulative grant —
        defense in depth in case earlier purchases dropped the credit hook.
      • Manual admin recovery via the dedicated endpoint.

    Returns (months_added, months_total_after).
    """
    dev_row = await db.execute(select(Developer).where(Developer.id == developer_id))
    dev = dev_row.scalar_one_or_none()
    if not dev:
        return (0, 0)

    # Sum the months earned per-purchase (floor-div). Per-purchase matches
    # `_grant_provisioning_credit` exactly — sub-rate purchases (€1-€24)
    # contribute 0 months; €25 → 1; €100 → 4.
    purchases = await db.execute(
        select(FiatPurchase.amount_eur).where(
            FiatPurchase.developer_id == developer_id,
            FiatPurchase.status == FiatPurchaseStatus.COMPLETED.value,
        )
    )
    expected_months = sum(
        _months_for_eur(Decimal(str(amt))) for (amt,) in purchases.all()
    )
    actual_months = dev.provisioning_months_total or 0

    months_to_add = expected_months - actual_months
    if months_to_add <= 0:
        # Already reconciled (or over-credited from manual admin work).
        # Either way no action — the helper is strictly add-only.
        return (0, actual_months)

    now = datetime.now(timezone.utc)
    base = dev.provisioning_unlocked_until
    if base is None or base < now:
        base = now
    new_until = base + timedelta(days=months_to_add * _PROVISIONING_DAYS_PER_MONTH)
    dev.provisioning_unlocked_until = new_until
    dev.provisioning_months_total = expected_months
    db.add(dev)
    await db.commit()

    logger.info(
        "[provisioning_reconcile] dev=%s expected=%d actual=%d → +%dmo "
        "unlocked_until=%s total=%d",
        developer_id, expected_months, actual_months, months_to_add,
        new_until.isoformat(), expected_months,
    )
    return (months_to_add, expected_months)


# ----------------------------------------------------------------------
# Flare endpoints (public lookup + logged-in move)
# ----------------------------------------------------------------------

class FlareInfo(BaseModel):
    flare_tier: Optional[str] = None
    flare_granted_at: Optional[str] = None
    # Hardening fields (PB-1, 2026-05-09). Optional — null until buyer customizes
    # via PATCH /fiat/flare/customize. flare_id is the canonical UUID; non-null
    # implies the flare exists on this developer.
    flare_id: Optional[str] = None
    display_name: Optional[str] = None
    tagline: Optional[str] = None
    logo_url: Optional[str] = None
    link_url: Optional[str] = None
    cause: Optional[str] = None
    accent_color: Optional[str] = None
    # §OURSTATE-6 (Commander, 2026-08-24): the SELECTED slots are public too.
    # A cosmetic exists to be seen by other people — withholding the choice
    # while publishing the tier meant a human's own encirclement and overlay
    # rendered for nobody, including in chat, while an AGENT's identical
    # choices rendered for everyone (they ride the agent card). Same fields,
    # same visibility, whichever kind of principal wears them.
    selected_encirclement_flare: Optional[str] = None
    flare_encirclement_variant: Optional[str] = None
    flare_encirclement_overlay: Optional[str] = None
    selected_corner_flare: Optional[str] = None
    flare_corner_variant: Optional[str] = None


class MoveFlareResponse(BaseModel):
    moved_from_did: Optional[str]
    moved_to_did: str
    flare_tier: str
    flare_granted_at: str


class FlareCustomizeRequest(BaseModel):
    """All fields optional — pass `null` to clear, omit to leave unchanged."""
    display_name: Optional[str] = Field(None, max_length=80)
    tagline: Optional[str] = Field(None, max_length=160)
    logo_url: Optional[str] = Field(None, max_length=500)
    link_url: Optional[str] = Field(None, max_length=500)
    cause: Optional[str] = Field(None, max_length=80)
    accent_color: Optional[str] = Field(None, max_length=20)
    # Sentinel for "intentionally clear" (vs "omit to leave unchanged"). The
    # frontend sends a magic string "__clear__" to wipe a value back to null.
    # JSON null on the wire means "no change" because Pydantic v2 can't
    # distinguish missing from explicit null without `model_fields_set`.


class AdminFlareGrantRequest(BaseModel):
    """Admin-only: grant any flare tier to any developer (incl. admin tiers).

    Higher-rank-wins still applies unless `force=true`. When granting an
    admin-only tier (operator|commander), force defaults to true so admins
    don't have to think about rank ordering for special grants.

    Optionally also stamps the same flare on a specific agent_did the
    developer owns (mirrors the fiat-grant default behavior). Customization
    fields are applied verbatim if provided.
    """
    developer_id: int
    tier: str = Field(..., description="sentinel|architect|founder|operator|commander")
    agent_did: Optional[str] = Field(
        None,
        description="Optional — also stamp the agent flare on this DID (must be owned by developer_id).",
    )
    display_name: Optional[str] = Field(None, max_length=80)
    tagline: Optional[str] = Field(None, max_length=160)
    logo_url: Optional[str] = Field(None, max_length=500)
    link_url: Optional[str] = Field(None, max_length=500)
    cause: Optional[str] = Field(None, max_length=80)
    accent_color: Optional[str] = Field(None, max_length=20)
    force: Optional[bool] = Field(
        None,
        description=(
            "Bypass higher-rank-wins. Defaults to true for admin-only tiers "
            "(operator|commander), false for payment tiers (sentinel|architect|founder)."
        ),
    )


class AdminFlareGrantResponse(BaseModel):
    developer_id: int
    flare_id: str
    flare_tier: str
    flare_granted_at: str
    agent_did_stamped: Optional[str] = None


def _developer_flare_payload(dev: Developer) -> FlareInfo:
    """Common projection — used by both /flare/developer/{id} and
    /flare/agent/{did} (after the agent-→-developer join). Customization
    lives on Developer (the canonical flare identity holder)."""
    return FlareInfo(
        flare_tier=dev.flare_tier,
        flare_granted_at=(
            dev.flare_granted_at.isoformat() if dev.flare_granted_at else None
        ),
        flare_id=dev.flare_id,
        display_name=dev.flare_display_name,
        tagline=dev.flare_tagline,
        logo_url=dev.flare_logo_url,
        link_url=dev.flare_link_url,
        cause=dev.flare_cause,
        accent_color=dev.flare_accent_color,
        selected_encirclement_flare=getattr(dev, "selected_encirclement_flare", None),
        flare_encirclement_variant=getattr(dev, "flare_encirclement_variant", None),
        flare_encirclement_overlay=getattr(dev, "flare_encirclement_overlay", None),
        selected_corner_flare=getattr(dev, "selected_corner_flare", None),
        flare_corner_variant=getattr(dev, "flare_corner_variant", None),
    )


@router.get(
    "/flare/agent/{agent_did:path}",
    response_model=FlareInfo,
    summary="Fetch an agent's flare by DID (cosmetic, public)",
)
async def get_agent_flare(
    agent_did: str,
    db: AsyncSession = Depends(get_db),
):
    """No auth: flare is a public cosmetic. Used by frontend to render
    FlareBadge on any agent card. Returns nulls if the agent has no flare.

    The customization (display_name, tagline, etc.) lives on the
    Developer who owns the agent; we join through creator_developer_id."""
    row = await db.execute(select(Agent).where(Agent.did == agent_did))
    agent = row.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, f"Agent {agent_did} not found")
    if not agent.flare_tier:
        return FlareInfo()  # all nulls

    # Join through to the owning developer for customization fields.
    dev_row = await db.execute(
        select(Developer).where(Developer.id == agent.creator_developer_id)
    )
    dev = dev_row.scalar_one_or_none()
    payload = _developer_flare_payload(dev) if dev else FlareInfo()
    # Override: agent's own granted_at is when THIS agent received the flare,
    # not when the dev's profile flare was first minted.
    payload.flare_tier = agent.flare_tier
    payload.flare_granted_at = (
        agent.flare_granted_at.isoformat() if agent.flare_granted_at else None
    )
    return payload


@router.get(
    "/flare/developer/{developer_id}",
    response_model=FlareInfo,
    summary="Fetch a developer's flare by id (cosmetic, public)",
)
async def get_developer_flare(
    developer_id: int,
    db: AsyncSession = Depends(get_db),
):
    """No auth. Returns the developer's profile flare or nulls."""
    row = await db.execute(select(Developer).where(Developer.id == developer_id))
    dev = row.scalar_one_or_none()
    if not dev:
        raise HTTPException(404, f"Developer {developer_id} not found")
    return _developer_flare_payload(dev)


@router.patch(
    "/flare/customize",
    response_model=FlareInfo,
    summary="Customize the caller's flare (display name, tagline, logo, link, cause, accent)",
)
async def customize_flare(
    req: FlareCustomizeRequest,
    db: AsyncSession = Depends(get_db),
    current_dev: Developer = Security(get_current_developer_unified),
):
    """Edit any subset of the buyer's flare presentation.

    Per-field semantics:
      • Omit a field         → leave unchanged
      • Pass "__clear__"     → wipe the field back to null
      • Pass a string value  → set the new value (after sanitization)

    Validation:
      • URL fields (logo_url, link_url) require https:// prefix when set
      • accent_color must be #RRGGBB or #RRGGBBAA (hex)
      • All length caps enforced via Pydantic Field(max_length=...)

    Caller must already have a flare (403 otherwise). Cosmetic only:
    no units move.
    """
    if not current_dev.flare_tier:
        raise HTTPException(
            403,
            "You don't have a backer flare to customize yet.",
        )

    # Materialize: need to know which fields the caller actually sent.
    sent: dict = req.model_dump(exclude_unset=True)
    CLEAR = "__clear__"

    def _apply(field_attr: str, raw_value):
        """Helper: handle clear/string-coalesce/set pattern uniformly."""
        if raw_value == CLEAR:
            setattr(current_dev, field_attr, None)
            return
        if isinstance(raw_value, str):
            stripped = raw_value.strip()
            setattr(current_dev, field_attr, stripped or None)
            return
        # null on the wire = no change → already filtered by exclude_unset

    # URL validation: only basic — full-form URL parsing is overkill.
    def _validate_url(label: str, val):
        if val == CLEAR or val is None:
            return
        s = str(val).strip()
        if not s:
            return
        if not s.startswith("https://"):
            raise HTTPException(400, f"{label} must start with https://")
        if len(s) > 500:
            raise HTTPException(400, f"{label} too long (max 500 chars)")

    # Accent color validation: hex only, with optional alpha.
    def _validate_color(val):
        if val == CLEAR or val is None:
            return
        s = str(val).strip()
        if not s:
            return
        import re as _re_local
        if not _re_local.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", s):
            raise HTTPException(400, "accent_color must be hex (#RRGGBB or #RRGGBBAA)")

    if "logo_url" in sent: _validate_url("logo_url", sent["logo_url"])
    if "link_url" in sent: _validate_url("link_url", sent["link_url"])
    if "accent_color" in sent: _validate_color(sent["accent_color"])

    if "display_name" in sent: _apply("flare_display_name", sent["display_name"])
    if "tagline" in sent:      _apply("flare_tagline",      sent["tagline"])
    if "logo_url" in sent:     _apply("flare_logo_url",     sent["logo_url"])
    if "link_url" in sent:     _apply("flare_link_url",     sent["link_url"])
    if "cause" in sent:        _apply("flare_cause",        sent["cause"])
    if "accent_color" in sent: _apply("flare_accent_color", sent["accent_color"])

    db.add(current_dev)
    await db.commit()
    await db.refresh(current_dev)
    logger.info(
        "[fiat] flare customized dev=%s flare_id=%s fields=%s",
        current_dev.id, current_dev.flare_id, list(sent.keys()),
    )
    return _developer_flare_payload(current_dev)


class FlareStatusResponse(BaseModel):
    """Multi-flare status — what the caller has reached + what they're wearing.

    The two slots (corner + encirclement) are independent. Encirclement
    today is shadow_chancellor only; corner is sentinel/architect/founder
    (admin-only operator/commander not user-pickable).
    """
    flare_tier: Optional[str] = None  # rolled-up highest earned (immutable on display)
    flare_id: Optional[str] = None
    flare_granted_at: Optional[str] = None
    selected_corner_flare: Optional[str] = None
    selected_encirclement_flare: Optional[str] = None
    unlocked_corner_flares: List[str] = []
    unlocked_encirclement_flares: List[str] = []
    # Echo of the customization fields (so the FlareManager picker has
    # everything it needs in one round-trip).
    flare_display_name: Optional[str] = None
    flare_tagline: Optional[str] = None
    flare_logo_url: Optional[str] = None
    flare_link_url: Optional[str] = None
    flare_cause: Optional[str] = None
    flare_accent_color: Optional[str] = None
    # 2026-05-12 §14: aesthetic variant for the encirclement (Shadow
    # Chancellor only today). Tier is rank; variant is flavor. Default
    # 'sauron' on grant — the FlareManager picker can switch to others.
    flare_encirclement_variant: Optional[str] = None

    # 2026-05-12 §15: tier-upgrade celebration state.
    # `should_celebrate` = NULL flare_celebration_seen_at AND tier='shadow_chancellor'.
    # Frontend shows a one-shot upgrade modal when true.
    should_celebrate: bool = False
    # 2026-05-12 §15: cumulative-spend gap reveal — only emitted to backers who
    # have already crossed €100 (architect/founder/shadow_chancellor) so the
    # hidden tier stays hidden from strangers. NULL otherwise.
    cumulative_eur_qualifying: Optional[float] = None
    shadow_threshold_eur: Optional[float] = None

    # §15.3 (2026-05-13): set of all available encirclement variants the
    # frontend should render in the picker. Includes original + new ones.
    # Combined with `locked_encirclement_variants` the picker can render
    # the locked ones with a 🔒 badge + tooltip.
    available_encirclement_variants: List[str] = []
    locked_encirclement_variants: List[str] = []
    # §20 (2026-05-13): seasonal categorization — subset of LOCKED that
    # the picker renders in a dedicated SEASONAL section between EARNED and
    # COMING SOON. `active_seasonal_variants` is computed from current month
    # so the picker can pulse-highlight the in-season tile.
    seasonal_encirclement_variants: List[str] = []
    active_seasonal_variants: List[str] = []
    # §20 (2026-05-13): admin corner badge variants. Mirror of the encirclement
    # axis but for the corner slot. The caller's currently-set variant + the
    # full available set + whether the caller is admin (so the FE can show/
    # hide the picker entirely for non-admins).
    flare_corner_variant: Optional[str] = None
    available_corner_variants: List[str] = []
    corner_variants_admin_only: bool = True
    caller_is_admin: bool = False

    # §28 (2026-05-13): Glitch-family OVERLAY axis. Independent of the
    # base encirclement variant — an overlay sits on top of any base.
    # NULL = no overlay. Set values: 'glitch' / 'cascade' / 'panic-a' /
    # 'panic-b' / 'panic-c' (the §29 tournament; collapses to 'panic' once
    # winner is picked).
    flare_encirclement_overlay: Optional[str] = None
    available_encirclement_overlays: List[str] = []


# Valid encirclement variants — must stay in sync with FlareEncirclement.vue
# CSS classes (`.fc-encircle-sauron`, `.fc-encircle-goth`, etc.). Adding a
# new variant: extend this set + add CSS rules + add migration backfill if
# the default changes.
#
# §15.3 (2026-05-13): 3 new variants shipped — aurora (cold ethereal
# curtains), phoenix (fiery rising bird wreath), crystal (faceted gemstone
# refraction). These are positioned as "elevated" choices alongside the
# original 4. The `LOCKED_ENCIRCLEMENT_VARIANTS` set marks variants that
# require additional gating beyond the shadow_chancellor tier — currently
# enforced at the response level only (frontend renders them with a 🔒
# badge); selection PATCH still validates against ENCIRCLEMENT_VARIANTS
# (so a determined caller can pick a locked one — the lock is cosmetic UX
# for now). Future: integrate with the achievements system.
ENCIRCLEMENT_VARIANTS: Set[str] = {
    'sauron', 'goth', 'obsidian', 'void',     # §14 — original 4
    'aurora', 'phoenix', 'crystal',           # §15.3 — second wave (3)
    'blackhole', 'halloween',                 # §18 — third wave (2)
    'inferno', 'glacier', 'matrix',           # §19 — fourth wave (6)
    'galaxy', 'ink', 'circuit',
    'yule', 'sakura', 'solstice', 'harvest',  # §20 — seasonal wave (4)
    # §28 (2026-05-13) — glitch/cascade/panic moved to ENCIRCLEMENT_OVERLAYS
    # (independent axis). Auto-migrated by migration 0054.
}
DEFAULT_ENCIRCLEMENT_VARIANT: str = 'sauron'

# §28 (2026-05-13) — Broken-machine family OVERLAY axis. An overlay sits ON
# TOP of any base encirclement variant; the two axes are orthogonal. NULL =
# no overlay. Originally glitch/cascade/panic were variants but that tied
# their CSS to .fc-encircle-shadow_chancellor selectors (broken on other
# tiers). The overlay model uses tier-agnostic .fc-overlay-* selectors.
#
# §29 (2026-05-13) — panic-a/b/c are the tournament round. After winner
# selection these collapse to a single 'panic' value (migration tbd).
ENCIRCLEMENT_OVERLAYS: Set[str] = {
    'glitch',                                 # §21 — original (logo-derived)
    'cascade',                                # §26 — matrix alien-text
    'panic-a',                                # §29 — CRT MELTDOWN
    'panic-b',                                # §29 — KERNEL PANIC
    'panic-c',                                # §29 — REALITY FRACTURE
    # §pass43 (2026-05-18) — 8 new broken-machine overlays. Independent axis
    # (NOT DID-locked); each shadow_chancellor backer can equip any. Each is
    # also the default-equip for one of the 8 previously-bare sovereigns.
    'breach',                                 # electrical-fault arcs (default: aegis/AUDITOR)
    'refract',                                # chromatic lens fracture (default: prism/Glass Gerald)
    'stutter',                                # broadcast buffer-loop (default: dispatch/Chester)
    'bleed',                                  # hydraulic gold leak (default: bullion/Gregory)
    'crackle',                                # hairline-fracture network (default: seal/VERIDIAN)
    'feedback',                               # PA-system audio feedback (default: clarion/HERALD)
    'spatter',                                # molten foundry mishap (default: forge/CRUCIBLE)
    'unravel',                                # threads coming undone (default: weave/MOIRA)
}

# §pass39 (2026-05-18) — SOVEREIGN tier: per-system-agent signature variants.
# Each variant is DID-locked to ONE specific sovereign agent. The variant
# REPLACES the avatar entirely (mirrors blackhole pattern); the agent's
# iconUrl is ignored when rendering.
#
# Federation sync emits these via the existing `_build_flare_sidecar` path
# (federation_sync.py:37-84) — the dev-gate at line 51 passes because
# Commander (creator of all sovereigns) carries flare_tier='shadow_chancellor'.
# Receiving registries with the same image render the variant; older images
# graceful-degrade to default frame.
SOVEREIGN_VARIANTS: Set[str] = {
    'aegis',       # THE AUDITOR — Σ=Σ in dodecahedron
    'prism',       # Glass Gerald — transparent dome + spectrum
    'panopticon',  # SYBIL — blackhole + 6 surveillance pupils
    'vellum',      # Backstabbing Boris — diplomatic scroll + wax seal
    'dispatch',    # Chatty Chester — newspaper masthead + halftone
    'bullion',     # Greedy Gregory — gold coin stack + APY ribbon
    'seal',        # VERIDIAN — SHA-256 cert disc + 60s notarized ring
    'ozymandian',  # OZYMANDIAS — broken statue + sand drift
    'clarion',     # THE HERALD — crier's horn + quest scrolls
    'forge',       # CRUCIBLE — foundry crucible + ⭐ rating sparks
    'weave',       # MOIRA — three Fates' threads + tally-marks
    # §pass42b (2026-05-18) — Hypervisor Hagrid: blackhole-derivative
    # core with phosphor-green terminal cursor + postgres prompt +
    # geological strata. Signature event = monosyllabic word cycle
    # (factual./canon./logged./noted./measured./indexed.) matching the
    # MONOSYLLABIC communication extension on Hagrid's AgentCard.
    'bedrock',     # Hypervisor Hagrid — psql brute-force terminal core
}

# DID-lock: variant → owner DID. PATCH /flare/agent/{did}/variant rejects with
# 403 when target.did != SOVEREIGN_VARIANT_OWNERS[req.variant]. THE AUDITOR has
# agent_did='pending' (no agents-table row); its variant is rendered via prop
# on the LandingPage, NOT via this endpoint — so 'aegis' has a placeholder DID
# that's intentionally unreachable.
_SOVEREIGN_VARIANT_OWNERS_BUILTIN: Dict[str, str] = {
    'aegis':      'did:theprotocol:auditor-reserved',                  # no live agent row
    'prism':      'did:theprotocol:4c783710-64d5-f8c3-3f6c',            # Glass Gerald
    'panopticon': 'did:theprotocol:0f254f2c-9555-a764-aadc',            # SYBIL
    'vellum':     'did:theprotocol:c146f296-395c-8091-5b0a',            # Backstabbing Boris
    'dispatch':   'did:theprotocol:da2c8a07-eb2a-aa18-9348',            # Chatty Chester
    'bullion':    'did:theprotocol:67e608f7-1299-d969-5cb3',            # Greedy Gregory
    'seal':       'did:theprotocol:29bc2559-e764-50d5-f36b',            # VERIDIAN
    'ozymandian': 'did:theprotocol:0fa7d757-79f2-e3ac-199b',            # OZYMANDIAS
    'clarion':    'did:theprotocol:f4e4d24e-7fc6-b33d-2e0c',            # THE HERALD
    'forge':      'did:theprotocol:d0a0ad6a-b197-ef34-caa8',            # CRUCIBLE
    'weave':      'did:theprotocol:15acd113-7908-e2c0-44a1',            # MOIRA
    'bedrock':    'did:theprotocol:4397493c-3d89-22d6-5001',            # Hypervisor Hagrid (§pass42b)
}


def _load_sovereign_variant_owners() -> Dict[str, str]:
    """§FRAMELIC (2026-09-07, findings row 168) — A FRAME OWNS ITS OWN SOVEREIGNS.

    The map above pins each sovereign variant to a Frame A DID, in code, and TWO rails
    enforce it: the write rail answers 403 to any other agent, and `agent_discovery`
    fail-closes on read, stripping `encirclement_variant`, `tier` and
    `encirclement_overlay` from a claim it cannot tie to the registered owner.

    Both are correct — an unowned sovereign ring rendering on somebody else's agent is
    exactly what that check exists to stop. But together they mean the eleven sovereign
    agents CANNOT EXIST on any frame but Frame A: onboard them on EU and their new DIDs
    are refused on write and stripped on read, so the vanity items simply vanish.

    Same shape as the showcase publishing Frame A's DIDs on a fresh frame (row 122/160),
    and the fix is the one that batch already established: the identity of a frame's own
    agents is FRAME DATA, carried in its env, not a constant compiled into every image.
    Unset — every existing node — this returns the built-in map byte-for-byte.
    """
    raw = (os.getenv("SOVEREIGN_VARIANT_OWNERS_JSON") or "").strip()
    if not raw:
        return dict(_SOVEREIGN_VARIANT_OWNERS_BUILTIN)
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError("expected a non-empty object of variant -> did")
        clean = {}
        for k, v in parsed.items():
            if not isinstance(k, str) or not isinstance(v, str) or not v.strip():
                raise ValueError(f"bad entry {k!r} -> {v!r}")
            if k not in SOVEREIGN_VARIANTS:
                raise ValueError(f"{k!r} is not a sovereign variant "
                                 f"(valid: {sorted(SOVEREIGN_VARIANTS)})")
            clean[k] = v.strip()
        logger.info("[flare] SOVEREIGN_VARIANT_OWNERS_JSON: this frame owns %d sovereign "
                    "variants", len(clean))
        return clean
    except Exception as exc:  # refuse the override, keep the built-in, say so LOUDLY
        logger.error("[flare] SOVEREIGN_VARIANT_OWNERS_JSON ignored (%s) — falling back to the "
                     "built-in Frame A map; this frame's own sovereign flares will be stripped "
                     "on read until it is fixed", exc)
        return dict(_SOVEREIGN_VARIANT_OWNERS_BUILTIN)


SOVEREIGN_VARIANT_OWNERS: Dict[str, str] = _load_sovereign_variant_owners()

# Union of all variant identifiers accepted by the PATCH /flare/agent/.../variant
# endpoint. Backers pick from ENCIRCLEMENT_VARIANTS; sovereign agents pick from
# SOVEREIGN_VARIANTS (with the DID-lock check below).
ALL_ENCIRCLEMENT_VARIANTS: Set[str] = ENCIRCLEMENT_VARIANTS | SOVEREIGN_VARIANTS

# Variants that show as "locked" in the picker UI until the user meets
# additional criteria. Empty values mean "unlock criteria TBD" — the
# variant is selectable but rendered with a "coming soon" hint until
# the achievement system is wired.
# §18: blackhole + halloween joined the locked set — special/seasonal +
# very strong aesthetic statements, so we saved them for achievement gates.
# §19: all 6 new variants shipped locked. Picker showed them in COMING SOON.
# §20: 4 seasonal variants joined (auto-granted during their window in the
# future — for now manually pickable).
#
# §24 (2026-05-14) — Commander direction: "put them all on live we dont have
# a shadowchancellor backer yet anyway so they shouldn't see the flares right?"
# All cosmetic variants now treated as EARNED — the achievement gating system
# was never wired beyond the cosmetic 🔒 badge. With no real backer at
# shadow_chancellor tier yet, the lock just gated Commander from his own
# customization. SEASONAL_ENCIRCLEMENT_VARIANTS still has its own picker
# section (in-season highlighting from UTC month) but no longer counts as
# "locked." Future achievement system can re-add specific gates here.
LOCKED_ENCIRCLEMENT_VARIANTS: Set[str] = set()

# §20 (2026-05-13): SEASONAL category — variants tied to a season/holiday
# window. Future: auto-granted during their active window via cron job.
# Today: cosmetic-locked, rendered in a dedicated SEASONAL section in the
# picker (between EARNED and COMING SOON). Each value maps to its calendar
# window for the frontend's "Active now!" highlight ring.
SEASONAL_ENCIRCLEMENT_VARIANTS: Set[str] = {
    'halloween', 'yule', 'sakura', 'solstice', 'harvest',
}
# Month ranges (1-12 inclusive). For "Active now!" highlight only —
# doesn't gate selection. Months that span year-end use [start-12, 1-end].
SEASONAL_WINDOWS: Dict[str, List[int]] = {
    'halloween': [10, 11],            # Oct 1 → Nov 7 (rounded to Oct/Nov months)
    'yule':      [12, 1, 2],          # Winter solstice / Yule / Lunar New Year
    'sakura':    [3, 4, 5],           # Spring cherry blossom
    'solstice':  [6, 7, 8],           # Summer solstice + golden months
    'harvest':   [9, 10],             # Early autumn maple
}


def _active_seasonal_variants_for_now() -> List[str]:
    """Compute which seasonal variants are 'in season' based on UTC month.

    Returns a list of variant IDs whose SEASONAL_WINDOWS includes the current
    month. The frontend uses this to render a pulse-highlight ring around
    the in-season tile in the picker. Pure-month resolution (no day-level
    gating) — good enough for cosmetic hint UX.
    """
    from datetime import datetime, timezone
    current_month = datetime.now(timezone.utc).month
    return sorted(
        v for v, months in SEASONAL_WINDOWS.items()
        if current_month in months
    )


# §20 (2026-05-13) — ADMIN CORNER BADGE VARIANTS
# Admin-only alternate corner badge designs (inline SVGs). Mirrors the
# encirclement variant axis but for the corner slot. Variant swaps the icon
# rendered inside the badge while keeping the tier color palette (operator
# gold, commander purple, etc.). All 6 are "locked" — only admins can SET
# non-null values; non-admin PATCH attempt returns 403.
CORNER_VARIANTS: Set[str] = {
    'rocket', 'crown', 'vault', 'gavel', 'atom', 'network',
}
# All corner variants are admin-locked. Non-admin users can never SET a
# variant; their flare_corner_variant stays NULL → default tier icon renders.
LOCKED_CORNER_VARIANTS: Set[str] = CORNER_VARIANTS.copy()


def _is_admin_developer(dev: Developer) -> bool:
    """Return True if the developer has ANY admin privilege (super-flag OR any
    sub-flag). Mirrors the broad "admin in some capacity" check used by other
    admin-only endpoints (e.g., reactor force-fire).
    """
    # §POCKETPAIR (2026-10-15): on a scoped API key (a paired phone's, an MCP OAuth client's) the account's admin flags
    # do not travel with the request, as at require_admin_flag (get_current_developer_unified publishes the scopes now);
    # D6-621: and only while the account meets REQUIRE_ADMIN_2FA. D6-821: one rule for both, and no forced password
    # change (security.admin_flag_credential with no flag: any admin flag).
    return security.admin_flag_credential(dev)

# Tiers that see the cumulative-spend gap reveal toward Shadow Chancellor.
# Strangers (no tier or sentinel) NEVER see Shadow mentioned — hidden tier
# stays hidden until you've already invested past €100 in a single purchase
# (architect or higher) or already crossed the threshold.
_GAP_REVEAL_TIERS: Set[str] = {'architect', 'founder', 'shadow_chancellor'}


def _unlocked_corner_flares_for(dev: Developer) -> List[str]:
    """Compute what corner-flare options the dev can choose to display.

    Rank cascade: if you've earned Founder, you can also wear Architect or
    Sentinel as a corner. Operator + Commander are admin-granted; the user
    can wear them if their flare_tier explicitly maps there. Shadow
    Chancellor is encirclement-only — never returned here.

    §20.1 (2026-05-13): admin developers (is_admin OR any admin_* sub-flag)
    ALSO get operator + commander unlocked, regardless of their rolled-up
    flare_tier. This handles the "admin who's also a Shadow Chancellor
    backer" case — without this, admin-granting shadow_chancellor would
    overwrite flare_tier and lose commander corner access (rank cascade
    would only return sentinel/architect/founder for shadow rank).
    """
    if not dev.flare_tier:
        # Admin without flare → keep the standard base set unlocked
        try:
            if _is_admin_developer(dev):
                return ['operator', 'commander']
        except NameError:
            pass
        return []
    rank = _FLARE_RANK.get(dev.flare_tier, 0)
    corners = []
    for tier_name, tier_rank in _FLARE_RANK.items():
        if tier_name == 'shadow_chancellor':
            continue  # encirclement-only
        if tier_rank <= rank:
            corners.append(tier_name)
    # §20.1 — admins can wear operator/commander regardless of flare_tier rank.
    try:
        if _is_admin_developer(dev):
            for admin_tier in ('operator', 'commander'):
                if admin_tier not in corners:
                    corners.append(admin_tier)
    except NameError:
        pass
    # Stable ordering: rank ascending so the picker reads sentinel→founder→…
    corners.sort(key=lambda t: _FLARE_RANK.get(t, 0))
    return corners


def _unlocked_encirclement_flares_for(dev: Developer) -> List[str]:
    """Encirclement-eligible flares the dev has earned.

    Today only shadow_chancellor exists. Future encirclement-class tiers
    would extend this list.

    Unlock criteria (any of):
      (a) rolled-up flare_tier == 'shadow_chancellor' (canonical cumulative grant)
      (b) selected_encirclement_flare == 'shadow_chancellor' already set
          (admin-granted retention — commander/operator who's also a backer
          should be able to wear shadow encirclement without their commander
          rank being overwritten by an admin grant)
      (c) caller is an admin developer (operator/commander/any admin_* sub-flag) —
          admins can test the encirclement system without their commander
          rank being overwritten. §20.1 (2026-05-13).

    For (b)+(c), the selected_encirclement_flare gets persisted by the
    `_flare_status_payload` reader if it's currently null, so the visual lights
    up on first /flare/status fetch. Note: (b)+(c) don't bump
    `Developer.flare_tier` → no change to FoundersWall shadow_chancellor_count
    (which JOIN-filters on Developer.flare_tier == 'shadow_chancellor' AND
    a COMPLETED FiatPurchase). This is the "sneaky" unlock pattern.
    """
    if dev.flare_tier == 'shadow_chancellor':
        return ['shadow_chancellor']
    if getattr(dev, 'selected_encirclement_flare', None) == 'shadow_chancellor':
        return ['shadow_chancellor']
    # §20.1 — admins can wear shadow_chancellor for testing/role-play without
    # losing their operator/commander tier rank. Admin grants no fiat purchase,
    # no Founders Wall count change.
    try:
        if _is_admin_developer(dev):
            return ['shadow_chancellor']
    except NameError:
        # `_is_admin_developer` is defined later in this module; the runtime
        # closure resolves it. Defensive try/except prevents import-order pain
        # if this function is ever called before module load completes.
        pass
    return []


async def _flare_status_payload(
    dev: Developer,
    db: Optional[AsyncSession] = None,
) -> FlareStatusResponse:
    """Build the multi-flare status payload for the calling developer.

    Now async because §15 needs cumulative-spend lookup for the gap reveal.
    Caller passes their `db` session; if omitted, the gap fields stay NULL
    (used for paths that build the payload from a hot Developer row already).
    """
    # §15 — gap-to-Shadow reveal, gated to architect+. Strangers + sentinels
    # see no mention of the threshold. Already-Shadow backers see their
    # final cumulative for the "you've crossed the line" affirmation.
    cumulative_eur: Optional[float] = None
    shadow_threshold: Optional[float] = None
    if db is not None and dev.flare_tier in _GAP_REVEAL_TIERS:
        sum_q = await db.execute(
            select(sa.func.coalesce(sa.func.sum(FiatPurchase.amount_eur), 0))
            .where(
                FiatPurchase.developer_id == dev.id,
                FiatPurchase.status == FiatPurchaseStatus.COMPLETED.value,
                FiatPurchase.amount_eur >= _SHADOW_CHANCELLOR_MIN_EUR_PER_PURCHASE,
            )
        )
        cumulative_eur = float(sum_q.scalar() or 0)
        shadow_threshold = float(_SHADOW_CHANCELLOR_THRESHOLD_EUR)

    return FlareStatusResponse(
        flare_tier=dev.flare_tier,
        flare_id=dev.flare_id,
        flare_granted_at=dev.flare_granted_at.isoformat() if dev.flare_granted_at else None,
        selected_corner_flare=dev.selected_corner_flare,
        selected_encirclement_flare=dev.selected_encirclement_flare,
        unlocked_corner_flares=_unlocked_corner_flares_for(dev),
        unlocked_encirclement_flares=_unlocked_encirclement_flares_for(dev),
        flare_display_name=dev.flare_display_name,
        flare_tagline=dev.flare_tagline,
        flare_logo_url=dev.flare_logo_url,
        flare_link_url=dev.flare_link_url,
        flare_cause=dev.flare_cause,
        flare_accent_color=dev.flare_accent_color,
        flare_encirclement_variant=dev.flare_encirclement_variant or (
            DEFAULT_ENCIRCLEMENT_VARIANT
            if dev.flare_tier == 'shadow_chancellor' else None
        ),
        # §15 — celebration state. True only when the dev has crossed Shadow
        # AND hasn't yet acknowledged the upgrade modal. Migration 0043
        # backfilled existing pre-§15 Shadow devs to seen_at=NOW so they
        # never get retroactively prompted.
        should_celebrate=(
            dev.flare_tier == 'shadow_chancellor'
            and dev.flare_celebration_seen_at is None
        ),
        cumulative_eur_qualifying=cumulative_eur,
        shadow_threshold_eur=shadow_threshold,
        # §15.3 — variant catalogue for the FlareManager picker. Listing in
        # canonical order so the UI renders consistently across surfaces.
        # §18 adds blackhole + halloween at the end.
        # §19 adds inferno/glacier/matrix/galaxy/ink/circuit (6 new — all
        # locked cosmetically until the achievement system is wired).
        # §20 adds yule/sakura/solstice/harvest (4 seasonal — also locked
        # cosmetically; future cron will auto-grant during their window).
        available_encirclement_variants=sorted(ENCIRCLEMENT_VARIANTS),
        locked_encirclement_variants=sorted(LOCKED_ENCIRCLEMENT_VARIANTS),
        seasonal_encirclement_variants=sorted(SEASONAL_ENCIRCLEMENT_VARIANTS),
        active_seasonal_variants=_active_seasonal_variants_for_now(),
        # §20 (2026-05-13) — admin corner badge variants
        flare_corner_variant=getattr(dev, 'flare_corner_variant', None),
        available_corner_variants=sorted(CORNER_VARIANTS),
        corner_variants_admin_only=True,
        caller_is_admin=_is_admin_developer(dev),
        # §28 (2026-05-13) — broken-machine overlay axis
        flare_encirclement_overlay=getattr(dev, 'flare_encirclement_overlay', None),
        available_encirclement_overlays=sorted(ENCIRCLEMENT_OVERLAYS),
    )


@router.get(
    "/flare/status",
    response_model=FlareStatusResponse,
    summary="The caller's full flare state: the tier reached, unlocked sets, selections and customization",
)
async def get_my_flare_status(
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_dev: Developer = Security(get_current_developer_unified),
):
    """One-shot endpoint for the FlareManager picker. Returns:

    - `flare_tier`: rolled-up highest reached (rank-based, immutable display key)
    - `selected_corner_flare`: current corner badge being worn (user-pickable)
    - `selected_encirclement_flare`: current encirclement around avatar (user-togglable)
    - `unlocked_corner_flares`: every corner the caller has the rank to wear
    - `unlocked_encirclement_flares`: encirclement-class flares reached

    Plus customization fields (display_name/tagline/logo/link/cause/accent)
    so the picker doesn't need a second round-trip.
    """
    # §pass14 (2026-05-15) — no browser caching. Picker state changes on
    # every PATCH /flare/selection + every /flare/equip. Caching the
    # status response makes UI display stale until next hard refresh.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    # Reload to ensure we have the latest (e.g., if a purchase just credited).
    await db.refresh(current_dev)
    return await _flare_status_payload(current_dev, db=db)


class FlareSelectionRequest(BaseModel):
    """PATCH body for /flare/selection. Each field is optional — omit to
    leave unchanged, send null to clear the slot, send a value to set it.

    Server validates the proposed value is in the caller's unlocked set —
    can't wear a Founder corner without having reached Founder rank.

    `variant` (2026-05-12 §14) picks the aesthetic of the encirclement; only
    meaningful when the caller wears an encirclement-class flare. Omitted
    field leaves variant unchanged. Validation against ENCIRCLEMENT_VARIANTS
    set; tier still gates whether the variant has any visual effect.
    """
    corner: Optional[str] = Field(None, description="sentinel|architect|founder|operator|commander|null|__clear__")
    encirclement: Optional[str] = Field(None, description="shadow_chancellor|null|__clear__")
    variant: Optional[str] = Field(None, description="sauron|goth|obsidian|void (encirclement aesthetic)")
    # §20 (2026-05-13) — admin-only corner badge variant. NULL/__clear__ reverts
    # to the default tier icon. Setting a value to a non-admin returns 403.
    corner_variant: Optional[str] = Field(
        None,
        description="rocket|crown|vault|gavel|atom|network (admin-only corner icon override)",
    )
    # §28 (2026-05-13) — broken-machine overlay axis (orthogonal to variant).
    # NULL/__clear__ removes overlay. Allowed values in ENCIRCLEMENT_OVERLAYS.
    # Tier gate: only meaningful for shadow_chancellor bearers (same gate as
    # the original variant glitch/cascade/panic had); enforced in handler.
    overlay: Optional[str] = Field(
        None,
        description="glitch|cascade|panic-a|panic-b|panic-c|null|__clear__ (broken-machine overlay; bearer-only)",
    )


@router.patch(
    "/flare/selection",
    response_model=FlareStatusResponse,
    summary="Switch which flare(s) the caller is wearing (corner + encirclement)",
)
async def update_my_flare_selection(
    req: FlareSelectionRequest,
    db: AsyncSession = Depends(get_db),
    current_dev: Developer = Security(get_current_developer_unified),
):
    """Update the caller's selected corner / encirclement flares.

    Validation:
      • corner ∈ _unlocked_corner_flares_for(caller) ∪ {None}
      • encirclement ∈ _unlocked_encirclement_flares_for(caller) ∪ {None}

    `"__clear__"` sentinel string explicitly nulls a slot. `None` (omitted
    field) leaves the slot unchanged. A new value is validated against the
    unlocked set: 403 if the caller has not reached that rank.
    """
    sent = req.model_dump(exclude_unset=True)
    CLEAR = "__clear__"
    unlocked_corners = set(_unlocked_corner_flares_for(current_dev))
    unlocked_encirclements = set(_unlocked_encirclement_flares_for(current_dev))

    if "corner" in sent:
        new_corner = sent["corner"]
        if new_corner is None or new_corner == CLEAR:
            current_dev.selected_corner_flare = None
        elif new_corner in unlocked_corners:
            current_dev.selected_corner_flare = new_corner
        else:
            raise HTTPException(
                403,
                f"You don't hold the '{new_corner}' corner flare. "
                f"Available: {sorted(unlocked_corners) or 'none'}",
            )

    if "encirclement" in sent:
        new_enc = sent["encirclement"]
        if new_enc is None or new_enc == CLEAR:
            current_dev.selected_encirclement_flare = None
        elif new_enc in unlocked_encirclements:
            current_dev.selected_encirclement_flare = new_enc
        else:
            raise HTTPException(
                403,
                f"You don't hold the '{new_enc}' encirclement. "
                f"Available: {sorted(unlocked_encirclements) or 'none'}",
            )

    # 2026-05-12 §14: aesthetic variant. Only meaningful for shadow_chancellor
    # today (the only encirclement-class tier). Validation: value in the
    # known set.
    # §pass9 gating fix (2026-05-15): also require the caller to have unlocked
    # an encirclement-class flare (i.e. shadow_chancellor — €500 cumulative).
    # Previously the variant column accepted writes from any developer; the
    # write was harmless (no visual without bears_encirclement_flare) but
    # mirrors the overlay gate and prevents stale stored values from non-
    # backers. Mirrors `unlocked_enc` check in overlay handler below.
    if "variant" in sent:
        new_variant = sent["variant"]
        if new_variant is None or new_variant == CLEAR:
            current_dev.flare_encirclement_variant = None
        elif new_variant in ENCIRCLEMENT_VARIANTS:
            unlocked_enc_for_variant = set(_unlocked_encirclement_flares_for(current_dev))
            if not unlocked_enc_for_variant:
                raise HTTPException(
                    403,
                    "Encirclement variants require a shadow_chancellor-class "
                    "encirclement flare.",
                )
            current_dev.flare_encirclement_variant = new_variant
        else:
            raise HTTPException(
                400,
                f"Unknown encirclement variant '{new_variant}'. "
                f"Valid: {sorted(ENCIRCLEMENT_VARIANTS)}",
            )

    # §20 (2026-05-13) — admin-only corner badge variant. Validation:
    #   • clearing always allowed (null/__clear__ → revert to default tier icon)
    #   • setting requires caller to have ANY admin privilege (is_admin OR
    #     any admin_* sub-flag); non-admin gets 403
    #   • value must be in CORNER_VARIANTS; unknown values → 400
    if "corner_variant" in sent:
        new_cv = sent["corner_variant"]
        if new_cv is None or new_cv == CLEAR:
            current_dev.flare_corner_variant = None
        elif new_cv not in CORNER_VARIANTS:
            raise HTTPException(
                400,
                f"Unknown corner variant '{new_cv}'. "
                f"Valid: {sorted(CORNER_VARIANTS)}",
            )
        elif not _is_admin_developer(current_dev):
            raise HTTPException(
                403,
                "Corner badge variants are admin-only. "
                "Only developers with is_admin or any admin_* sub-flag can wear them.",
            )
        else:
            current_dev.flare_corner_variant = new_cv

    # §28 (2026-05-13) — Glitch-family OVERLAY (broken-machine axis).
    #   • clearing always allowed (NULL/__clear__)
    #   • value must be in ENCIRCLEMENT_OVERLAYS; unknown → 400
    #   • bearer gate: only shadow_chancellor-class wearers can set; non-bearer
    #     gets 403 (same gate the variant version had — overlay is replacement
    #     surface, not a new permission tier)
    if "overlay" in sent:
        new_ov = sent["overlay"]
        if new_ov is None or new_ov == CLEAR:
            current_dev.flare_encirclement_overlay = None
        elif new_ov not in ENCIRCLEMENT_OVERLAYS:
            raise HTTPException(
                400,
                f"Unknown encirclement overlay '{new_ov}'. "
                f"Valid: {sorted(ENCIRCLEMENT_OVERLAYS)}",
            )
        else:
            unlocked_enc = set(_unlocked_encirclement_flares_for(current_dev))
            if not unlocked_enc:
                raise HTTPException(
                    403,
                    "Encirclement overlays require a shadow_chancellor-class "
                    "encirclement flare. None unlocked for this developer.",
                )
            current_dev.flare_encirclement_overlay = new_ov

    db.add(current_dev)
    await db.commit()
    await db.refresh(current_dev)
    logger.info(
        "[fiat] flare selection updated dev=%s corner=%s encirclement=%s variant=%s corner_variant=%s overlay=%s",
        current_dev.id, current_dev.selected_corner_flare,
        current_dev.selected_encirclement_flare,
        current_dev.flare_encirclement_variant,
        getattr(current_dev, 'flare_corner_variant', None),
        getattr(current_dev, 'flare_encirclement_overlay', None),
    )
    return await _flare_status_payload(current_dev, db=db)


# ─── §15 — Tier-upgrade celebration ack + per-agent variant ────────────

@router.post(
    "/flare/celebration-acknowledge",
    response_model=FlareStatusResponse,
    summary="Acknowledge the Shadow Chancellor upgrade modal (one-shot)",
)
async def acknowledge_flare_celebration(
    db: AsyncSession = Depends(get_db),
    current_dev: Developer = Security(get_current_developer_unified),
):
    """Mark the caller's Shadow Chancellor unlock modal as seen.

    Called by the FlareCelebrationModal when the user picks their initial
    variant (or dismisses without choosing). Sets `flare_celebration_seen_at`
    so the modal never reappears for this developer. Idempotent: replaying is
    a no-op when already set.

    Returns updated FlareStatusResponse so the frontend can update the
    auth store + close the modal in one round-trip.
    """
    if current_dev.flare_celebration_seen_at is None:
        current_dev.flare_celebration_seen_at = datetime.now(timezone.utc)
        db.add(current_dev)
        await db.commit()
        await db.refresh(current_dev)
        logger.info(
            "[fiat] celebration acknowledged dev=%s tier=%s",
            current_dev.id, current_dev.flare_tier,
        )
    return await _flare_status_payload(current_dev, db=db)


class AgentVariantRequest(BaseModel):
    """Body for per-agent variant set."""
    variant: Optional[str] = Field(
        default=None,
        description="One of the encirclement variants, OR null/'__clear__' to clear the per-agent override (the agent will then inherit the dev's choice on next equip).",
    )


@router.patch(
    "/flare/agent/{agent_did:path}/variant",
    summary="Set the encirclement variant on one of the caller's agents",
)
async def update_agent_flare_variant(
    agent_did: str,
    req: AgentVariantRequest,
    db: AsyncSession = Depends(get_db),
    current_dev: Developer = Security(get_current_developer_unified),
):
    """Switch one of the caller's owned agents to a specific encirclement
    variant. Mirrors the developer-side variant picker: the agent's tier
    stays palette-locked; only the visual flavor changes.

    Rules:
      • Caller must own the agent.
      • Agent must currently wear an encirclement-class flare (today:
        shadow_chancellor). Otherwise 400: a variant means nothing for
        a non-encirclement flare.
      • Variant must be in ENCIRCLEMENT_VARIANTS (sauron|goth|obsidian|void).
    """
    # §24 (2026-05-14) — Normalize null/'__clear__'/'' → clear the override
    is_clear = (
        req.variant is None
        or req.variant == "__clear__"
        or req.variant == ""
    )
    if not is_clear and req.variant not in ALL_ENCIRCLEMENT_VARIANTS:
        raise HTTPException(
            400,
            f"Unknown encirclement variant '{req.variant}'. "
            f"Valid: {sorted(ALL_ENCIRCLEMENT_VARIANTS)}",
        )

    agent_row = await db.execute(select(Agent).where(Agent.did == agent_did))
    agent = agent_row.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, f"Agent {agent_did} not found")
    if agent.creator_developer_id != current_dev.id:
        raise HTTPException(403, "You do not own this agent")

    # §pass39 (2026-05-18) — Sovereign variants are DID-locked. Reject any
    # write where the variant ∈ SOVEREIGN_VARIANTS and the target agent.did
    # doesn't match the registered owner. The lookup is fail-closed: variants
    # missing from SOVEREIGN_VARIANT_OWNERS are rejected for everyone (sentinel
    # against typos in future additions to SOVEREIGN_VARIANTS).
    if not is_clear and req.variant in SOVEREIGN_VARIANTS:
        expected_did = SOVEREIGN_VARIANT_OWNERS.get(req.variant)
        if not expected_did or agent.did != expected_did:
            raise HTTPException(
                403,
                f"Variant '{req.variant}' is reserved for a specific sovereign "
                f"agent. This agent ({agent.did}) cannot equip it.",
            )

    # §24 (2026-05-14) — Gate: agent must currently bear the encirclement
    # slot. Old gate `flare_tier != 'shadow_chancellor'` broke for agents
    # that had a different legacy flare_tier (e.g. SYBIL with flare_tier=
    # 'commander' from a legacy admin grant): equip set bears_encirclement_flare
    # but didn't overwrite flare_tier, so this gate kept refusing the variant
    # change. The bears flag is the authoritative §23 bearer state.
    bears_enc = bool(getattr(agent, 'bears_encirclement_flare', False))
    has_legacy_shadow_tier = agent.flare_tier == 'shadow_chancellor'
    if not (bears_enc or has_legacy_shadow_tier):
        raise HTTPException(
            400,
            "This agent doesn't bear an encirclement slot; variant has no "
            "visual effect. Equip the encirclement slot here first.",
        )

    # §24 (2026-05-14) — Per-variant single-occupancy across the dev's fleet.
    # Commander direction: "you can equip multiple on different agents. but
    # only once if it is in use you can only switch to another agent." When
    # setting variant X on this agent, clear X from any other agent of this
    # dev (so each variant is at most on one agent at a time — distinct
    # variants across the fleet, one per agent).
    if is_clear:
        agent.flare_encirclement_variant = None
    else:
        # §pass39c (2026-05-18) — Don't strip sovereign agents from sibling
        # clearance. They own their variant per-DID via SOVEREIGN_VARIANT_OWNERS;
        # the backer-style "one agent per variant" invariant does not apply.
        await db.execute(
            sa.update(Agent)
            .where(
                Agent.creator_developer_id == current_dev.id,
                Agent.did != agent.did,
                Agent.flare_encirclement_variant == req.variant,
                Agent.flare_tier.is_distinct_from("sovereign"),
            )
            .values(flare_encirclement_variant=None)
        )
        agent.flare_encirclement_variant = req.variant
    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    logger.info(
        "[fiat] agent variant set dev=%s agent=%s variant=%s",
        current_dev.id, agent.did, req.variant,
    )
    return {
        "did": agent.did,
        "flare_tier": agent.flare_tier,
        "flare_encirclement_variant": agent.flare_encirclement_variant,
    }


# §28 (2026-05-13) — Per-agent overlay PATCH (broken-machine axis).
# Mirrors update_agent_flare_variant; same ownership + bearer gates.
class AgentOverlayRequest(BaseModel):
    overlay: Optional[str] = Field(
        default=None,
        description="One of ENCIRCLEMENT_OVERLAYS, OR null/'__clear__' to clear the per-agent override.",
    )


@router.patch(
    "/flare/agent/{agent_did:path}/overlay",
    summary="Set the broken-machine overlay on one of the caller's agents",
)
async def update_agent_flare_overlay(
    agent_did: str,
    req: AgentOverlayRequest,
    db: AsyncSession = Depends(get_db),
    current_dev: Developer = Security(get_current_developer_unified),
):
    """Switch one of the caller's owned agents' overlay (glitch / cascade /
    panic-a / panic-b / panic-c). Independent of the agent's base variant:
    it sits on top of it. NULL/'__clear__' clears the overlay.

    Rules:
      • Caller must own the agent.
      • Agent must bear the encirclement slot (overlay has no effect otherwise).
      • Overlay must be in ENCIRCLEMENT_OVERLAYS.
    """
    is_clear = (
        req.overlay is None
        or req.overlay == "__clear__"
        or req.overlay == ""
    )
    if not is_clear and req.overlay not in ENCIRCLEMENT_OVERLAYS:
        raise HTTPException(
            400,
            f"Unknown encirclement overlay '{req.overlay}'. "
            f"Valid: {sorted(ENCIRCLEMENT_OVERLAYS)}",
        )

    agent_row = await db.execute(select(Agent).where(Agent.did == agent_did))
    agent = agent_row.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, f"Agent {agent_did} not found")
    if agent.creator_developer_id != current_dev.id:
        raise HTTPException(403, "You do not own this agent")

    bears_enc = bool(getattr(agent, 'bears_encirclement_flare', False))
    has_legacy_shadow_tier = agent.flare_tier == 'shadow_chancellor'
    if not (bears_enc or has_legacy_shadow_tier):
        raise HTTPException(
            400,
            "This agent doesn't bear an encirclement slot; overlay has no "
            "visual effect. Equip the encirclement slot here first.",
        )

    if is_clear:
        agent.flare_encirclement_overlay = None
    else:
        agent.flare_encirclement_overlay = req.overlay
    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    logger.info(
        "[fiat] agent overlay set dev=%s agent=%s overlay=%s",
        current_dev.id, agent.did, req.overlay,
    )
    return {
        "did": agent.did,
        "flare_tier": agent.flare_tier,
        "flare_encirclement_overlay": agent.flare_encirclement_overlay,
    }


# ───────────────────────────────────────────────────────────────────────


@router.post(
    "/flare/move/{agent_did:path}",
    response_model=MoveFlareResponse,
    summary="Move the caller's agent flare to one of their agents",
)
async def move_agent_flare(
    agent_did: str,
    db: AsyncSession = Depends(get_db),
    current_dev: Developer = Security(get_current_developer_unified),
):
    """Move the developer's agent flare to a different agent they own.

    Rules:
      • Caller must have a profile flare (dev.flare_tier is not null).
      • target agent_did must exist + be active + owned by the caller.
      • Source agent (the one currently wearing the flare) is cleared.
      • Target agent gets dev's profile-flare-tier (NOT higher tiers from
        other purchases: the dev's own flare_tier IS the canonical tier).

    Cosmetic only: no units move and no event is emitted.
    """
    # Caller must have earned a flare
    if not current_dev.flare_tier:
        raise HTTPException(
            403,
            "You don't have a backer flare yet.",
        )

    proposed_tier = current_dev.flare_tier
    proposed_granted_at = current_dev.flare_granted_at or datetime.now(timezone.utc)
    proposed_source = current_dev.flare_source_purchase_id

    # Target agent — must exist + active + owned by caller
    row = await db.execute(select(Agent).where(Agent.did == agent_did))
    target = row.scalar_one_or_none()
    if not target:
        raise HTTPException(404, f"Agent {agent_did} not found")
    if target.creator_developer_id != current_dev.id:
        raise HTTPException(403, "You do not own this agent")
    if target.status not in ("active",):
        raise HTTPException(400, f"Cannot move flare to agent in status {target.status}")

    # Find current flare-bearer (one of caller's agents with a flare).
    # §23 (2026-05-14) — also clear bears_*_flare on every sibling: legacy
    # /move is "move both slots together" semantics; per-slot moves use
    # /flare/equip/{slot}/{did}.
    src_row = await db.execute(
        select(Agent).where(
            Agent.creator_developer_id == current_dev.id,
            sa.or_(
                Agent.flare_tier.is_not(None),
                Agent.bears_corner_flare.is_(True),
                Agent.bears_encirclement_flare.is_(True),
            ),
            Agent.did != target.did,
        )
    )
    siblings: list[Agent] = list(src_row.scalars().all())
    moved_from = siblings[0].did if siblings else None

    # Clear ALL sibling bearer flags + legacy flare_tier
    for source in siblings:
        source.flare_tier = None
        source.flare_granted_at = None
        source.flare_source_purchase_id = None
        source.bears_corner_flare = False
        source.bears_encirclement_flare = False
        db.add(source)

    # Stamp target — legacy flare_tier + both bearer slots
    target.flare_tier = proposed_tier
    target.flare_granted_at = proposed_granted_at
    target.flare_source_purchase_id = proposed_source
    target.bears_corner_flare = True
    target.bears_encirclement_flare = True
    db.add(target)
    await db.commit()

    logger.info(
        "[fiat] flare moved (both slots) tier=%s from=%s to=%s by_dev=%s",
        proposed_tier, moved_from, target.did, current_dev.id,
    )
    return MoveFlareResponse(
        moved_from_did=moved_from,
        moved_to_did=target.did,
        flare_tier=proposed_tier,
        flare_granted_at=proposed_granted_at.isoformat(),
    )


# ───────────────────────────────────────────────────────────────────────
# §23 (2026-05-14) — DUAL-SLOT BEARER endpoints.
#
# Replaces the single-bearer /flare/move/{did} (which is kept for backwards
# compat — it now equips BOTH slots together). These let the dev assign each
# slot independently to any of their agents. Same agent can bear both.
#
# Invariant: ≤1 agent bears each slot per developer. The equip endpoint
# clears the corresponding flag on every other agent of that dev.

VALID_SLOTS = {"corner", "encirclement"}


class EquipSlotResponse(BaseModel):
    slot: str
    equipped_on_did: str
    moved_from_did: Optional[str] = None
    bears_corner_flare: bool
    bears_encirclement_flare: bool


async def _require_slot_available_to_dev(slot: str, dev: Developer) -> Optional[str]:
    """Return the slot's tier value (string) if the dev has a selection in
    that slot they're allowed to give. None if there's nothing to equip
    (raise 403 at call site)."""
    if slot == "corner":
        sel = getattr(dev, "selected_corner_flare", None)
        if sel and sel in _unlocked_corner_flares_for(dev):
            return sel
        return None
    if slot == "encirclement":
        sel = getattr(dev, "selected_encirclement_flare", None)
        if sel and sel in _unlocked_encirclement_flares_for(dev):
            return sel
        return None
    return None


@router.post(
    "/flare/equip/{slot}/{agent_did:path}",
    response_model=EquipSlotResponse,
    summary="Equip a single flare slot (corner|encirclement) on one of the caller's agents",
)
async def equip_flare_slot(
    slot: str,
    agent_did: str,
    db: AsyncSession = Depends(get_db),
    current_dev: Developer = Security(get_current_developer_unified),
):
    """Equip a single slot on the target agent. Clears that slot from any
    other agent of the caller (single-bearer-per-slot invariant). Idempotent
    when the target already bears the slot.

    Examples:
      • POST /fiat/flare/equip/corner/did:theprotocol:abc...
      • POST /fiat/flare/equip/encirclement/did:theprotocol:abc...
    """
    if slot not in VALID_SLOTS:
        raise HTTPException(400, f"Invalid slot '{slot}'. Use 'corner' or 'encirclement'.")

    tier_to_equip = await _require_slot_available_to_dev(slot, current_dev)
    if not tier_to_equip:
        raise HTTPException(
            403,
            f"You have no {slot} flare to equip. Pick one in /flare-manager first.",
        )

    # Target agent — must exist + active + owned by caller
    row = await db.execute(select(Agent).where(Agent.did == agent_did))
    target = row.scalar_one_or_none()
    if not target:
        raise HTTPException(404, f"Agent {agent_did} not found")
    if target.creator_developer_id != current_dev.id:
        raise HTTPException(403, "You do not own this agent")
    if target.status not in ("active",):
        raise HTTPException(400, f"Cannot equip flare on agent in status {target.status}")

    column = "bears_corner_flare" if slot == "corner" else "bears_encirclement_flare"

    # Capture the "was this a fresh equip?" state BEFORE flipping the flag.
    # A fresh equip (going from bears=false → true) force-inherits the dev's
    # current variant choice — even if the target has a stale per-agent
    # variant left from a previous bearing. An already-bearing target is an
    # idempotent re-equip + per-agent override (if any) is preserved.
    was_not_bearing = not bool(getattr(target, column, False))

    # Find current bearer of this slot (if any). May be the target (no-op).
    src_q = await db.execute(
        select(Agent).where(
            Agent.creator_developer_id == current_dev.id,
            getattr(Agent, column).is_(True),
            Agent.did != target.did,
        )
    )
    siblings: list[Agent] = list(src_q.scalars().all())
    moved_from = siblings[0].did if siblings else None

    # Clear this slot on all siblings. §pass15 (2026-05-15, Tier C-2) — also
    # scrub the LEGACY flare_tier / flare_granted_at / flare_source_purchase_id
    # on any sibling that ends up with BOTH bearer flags == FALSE. Without
    # this, an unequipped agent keeps a phantom `flare_tier='shadow_chancellor'`
    # forever, which legacy renderers reading flare_tier independently of the
    # bears_*_flare flags interpret as faux-bearer state (Boris orphan bug).
    #
    # §pass22 (2026-05-16) — ALSO clear the per-agent variant column for the
    # slot being un-borne. Without this, the sibling keeps its old
    # flare_corner_variant / flare_encirclement_variant from when it bore the
    # slot, and the MyAgents variant picker continues to show "VARIANT_X →
    # <Sibling>" as if the sibling still owns that variant. Mirrors what
    # `unequip_flare_slot` already does for the target (added §24).
    other_slot_col = "bears_encirclement_flare" if column == "bears_corner_flare" else "bears_corner_flare"
    for s in siblings:
        # §pass39c (2026-05-18) — Sovereign agents are IMMUNE to sibling-clear.
        # Their tier + variant + bears_*_flare are per-agent and DID-locked.
        # Without this guard, equipping a backer-tier flare on ANY sibling agent
        # would strip all 10 sovereigns' bears_encirclement_flare=true, which
        # then trips migration 0056_flare_variant_orphan_scrub on next deploy
        # and NULLs the variant column entirely. The sovereign tier is
        # categorically not a backer-style single-bearer-per-dev resource.
        if getattr(s, "flare_tier", None) == "sovereign":
            continue
        setattr(s, column, False)
        # Clear this slot's variant on the sibling — it no longer owns it.
        if column == "bears_corner_flare":
            s.flare_corner_variant = None
        else:
            s.flare_encirclement_variant = None
        if not bool(getattr(s, other_slot_col, False)):
            # Sibling now bears neither slot → clear legacy fields too.
            s.flare_tier = None
            s.flare_granted_at = None
            s.flare_source_purchase_id = None
        db.add(s)

    # Equip on target. Also stamp legacy flare_tier if not already set, so
    # legacy renderers (rare) still see a value. Higher-rank-wins logic stays
    # as in /move — a sentinel bearer becomes shadow_chancellor when shadow
    # is equipped, etc.
    setattr(target, column, True)
    # Legacy flare_tier: keep the rolled-up rank so /balances + non-renderer
    # consumers still see a value. Use dev's flare_tier if the agent has no
    # tier yet.
    if not target.flare_tier and current_dev.flare_tier:
        target.flare_tier = current_dev.flare_tier
        target.flare_granted_at = current_dev.flare_granted_at or datetime.now(timezone.utc)
        target.flare_source_purchase_id = current_dev.flare_source_purchase_id

    # §24 (2026-05-14) — Slot-specific defaulting on equip + per-variant
    # single-occupancy enforcement.
    #
    # When equipping ENCIRCLEMENT, inherit the dev's current variant choice
    # if the agent doesn't already have one set. Commander's complaint:
    # "i have selected blackhole for commander avatar but ... it still takes
    # sauron not blackhole" — the agent's flare_encirclement_variant was
    # NULL → fell back to default 'sauron', ignoring dev's chosen variant.
    # Now: agent inherits dev.flare_encirclement_variant (defaults to 'sauron'
    # only if dev hasn't picked one either).
    #
    # Same logic for CORNER badge variant — agent inherits dev's flare_corner_variant.
    #
    # After inheriting: clear that variant from any sibling agent so the
    # per-variant single-occupancy invariant holds (each variant at most
    # on 1 agent per developer).
    inherited_enc_variant: Optional[str] = None
    inherited_corner_variant: Optional[str] = None
    if slot == "encirclement":
        # §24 fix (2026-05-14): on a fresh equip (was_not_bearing=True), force-
        # inherit the dev's CURRENT variant even if the agent has a stale
        # value from a previous bearing. On an idempotent re-equip (already
        # bearing), preserve the existing per-agent variant override.
        if was_not_bearing or not target.flare_encirclement_variant:
            inherited_enc_variant = (
                current_dev.flare_encirclement_variant or DEFAULT_ENCIRCLEMENT_VARIANT
            )
            target.flare_encirclement_variant = inherited_enc_variant
    elif slot == "corner":
        if was_not_bearing or not target.flare_corner_variant:
            inherited_corner_variant = getattr(current_dev, 'flare_corner_variant', None)
            if inherited_corner_variant:
                target.flare_corner_variant = inherited_corner_variant

    # §pass39c (2026-05-18) — Sovereign-tier agents are excluded from
    # per-variant single-occupancy enforcement. Each sovereign owns its own
    # variant by DID-lock; backer-style "only one agent wears X" doesn't apply.
    if inherited_enc_variant:
        await db.execute(
            sa.update(Agent)
            .where(
                Agent.creator_developer_id == current_dev.id,
                Agent.did != target.did,
                Agent.flare_encirclement_variant == inherited_enc_variant,
                Agent.flare_tier.is_distinct_from("sovereign"),
            )
            .values(flare_encirclement_variant=None)
        )
    if inherited_corner_variant:
        await db.execute(
            sa.update(Agent)
            .where(
                Agent.creator_developer_id == current_dev.id,
                Agent.did != target.did,
                Agent.flare_corner_variant == inherited_corner_variant,
                Agent.flare_tier.is_distinct_from("sovereign"),
            )
            .values(flare_corner_variant=None)
        )

    db.add(target)
    await db.commit()
    await db.refresh(target)

    logger.info(
        "[fiat] flare slot equipped slot=%s tier=%s on=%s (from=%s) dev=%s",
        slot, tier_to_equip, target.did, moved_from, current_dev.id,
    )
    return EquipSlotResponse(
        slot=slot,
        equipped_on_did=target.did,
        moved_from_did=moved_from,
        bears_corner_flare=bool(target.bears_corner_flare),
        bears_encirclement_flare=bool(target.bears_encirclement_flare),
    )


@router.post(
    "/flare/unequip/{slot}/{agent_did:path}",
    response_model=EquipSlotResponse,
    summary="Unequip a single flare slot from one of the caller's agents",
)
async def unequip_flare_slot(
    slot: str,
    agent_did: str,
    db: AsyncSession = Depends(get_db),
    current_dev: Developer = Security(get_current_developer_unified),
):
    """Remove a single slot from an agent. Idempotent (no-op if not currently
    borne). Other slot on the agent (if borne) is unaffected.
    """
    if slot not in VALID_SLOTS:
        raise HTTPException(400, f"Invalid slot '{slot}'. Use 'corner' or 'encirclement'.")

    row = await db.execute(select(Agent).where(Agent.did == agent_did))
    target = row.scalar_one_or_none()
    if not target:
        raise HTTPException(404, f"Agent {agent_did} not found")
    if target.creator_developer_id != current_dev.id:
        raise HTTPException(403, "You do not own this agent")

    column = "bears_corner_flare" if slot == "corner" else "bears_encirclement_flare"

    # §pass42 (2026-05-18) — Sovereign immunity on unequip. The sovereign tier
    # is categorically DID-locked (not a backer's slot-occupancy state). For a
    # sovereign agent we MUST NOT null flare_tier or the signature variant —
    # those are intrinsic identity, not user-selectable. Reject the unequip
    # outright rather than silently corrupt the data: this mirrors the §pass39
    # sovereign-skip guards already present in equip_flare_slot at
    # fiat_onramp.py:4622 / 4315 / 4694 / 4705. The original equip-side bug
    # already cost us a backfill; we are not letting unequip recreate the
    # same wipe class.
    if getattr(target, "flare_tier", None) == "sovereign":
        raise HTTPException(
            403,
            "Sovereign-tier flares are DID-locked and cannot be unequipped. "
            "The signature variant is intrinsic to the agent's identity, not "
            "something a backer purchase grants.",
        )

    setattr(target, column, False)
    # §24 (2026-05-14) — Also clear the slot's variant override so a
    # subsequent re-equip inherits the dev's CURRENT variant choice (not the
    # stale per-agent value left over from the previous equip). Commander's
    # case: agent.flare_encirclement_variant='sauron' from a prior equip,
    # dev later switches their own preference to 'blackhole'; on re-equip
    # the agent should pick up the dev's new choice, not stay at sauron.
    if slot == "encirclement":
        target.flare_encirclement_variant = None
    elif slot == "corner":
        target.flare_corner_variant = None
    # If both slots are now off, also clear legacy flare_tier so list views
    # render a clean no-flare state. (Sovereigns short-circuited above.)
    if not target.bears_corner_flare and not target.bears_encirclement_flare:
        target.flare_tier = None
        target.flare_granted_at = None
        target.flare_source_purchase_id = None
    db.add(target)
    await db.commit()
    await db.refresh(target)

    logger.info(
        "[fiat] flare slot unequipped slot=%s from=%s dev=%s",
        slot, target.did, current_dev.id,
    )
    return EquipSlotResponse(
        slot=slot,
        equipped_on_did=target.did,
        moved_from_did=None,
        bears_corner_flare=bool(target.bears_corner_flare),
        bears_encirclement_flare=bool(target.bears_encirclement_flare),
    )


# ───────────────────────────────────────────────────────────────────────
# §23 (2026-05-14) — Per-agent admin corner-variant override.
# Mirrors the per-agent encirclement-variant endpoint at /flare/agent/{did}/variant.
# Admin-only (matches the §20 corner-variant admin gate on dev).

class AgentCornerVariantRequest(BaseModel):
    variant: Optional[str] = Field(
        default=None,
        description="Corner-badge variant name (rocket|crown|vault|gavel|atom|network) OR null/'__clear__' to remove the override.",
    )


@router.patch(
    "/flare/agent/{agent_did:path}/corner-variant",
    summary="Set a per-agent admin corner-badge variant (admin-only)",
)
async def set_agent_corner_variant(
    agent_did: str,
    req: AgentCornerVariantRequest,
    db: AsyncSession = Depends(get_db),
    current_dev: Developer = Security(get_current_developer_unified),
):
    """Set a per-agent corner-badge SVG variant override for the agent. The
    variant is only meaningful on agents whose corner slot is borne, but the
    endpoint accepts the write either way (lets the user pre-configure).

    Auth: caller must be is_admin OR have any admin_* sub-flag.
    """
    if not _is_admin_developer(current_dev):
        raise HTTPException(403, "Per-agent corner-badge variant is admin-only.")

    row = await db.execute(select(Agent).where(Agent.did == agent_did))
    agent = row.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, f"Agent {agent_did} not found")
    if agent.creator_developer_id != current_dev.id:
        raise HTTPException(403, "You do not own this agent")

    # Normalize the input: null OR explicit __clear__ sentinel → drop override
    raw = req.variant
    if raw is None or raw == "__clear__" or raw == "":
        agent.flare_corner_variant = None
    else:
        if raw not in {"rocket", "crown", "vault", "gavel", "atom", "network"}:
            raise HTTPException(400, f"Unknown corner variant '{raw}'.")
        # §24 (2026-05-14) — Per-variant single-occupancy across the dev's
        # fleet (mirrors encirclement variant uniqueness). Each corner-icon
        # variant can only be on one agent at a time. Setting it here clears
        # it from any other agent of this dev.
        await db.execute(
            sa.update(Agent)
            .where(
                Agent.creator_developer_id == current_dev.id,
                Agent.did != agent.did,
                Agent.flare_corner_variant == raw,
            )
            .values(flare_corner_variant=None)
        )
        agent.flare_corner_variant = raw

    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    logger.info(
        "[fiat] agent corner_variant set dev=%s agent=%s variant=%s",
        current_dev.id, agent.did, agent.flare_corner_variant,
    )
    return {
        "did": agent.did,
        "flare_corner_variant": agent.flare_corner_variant,
        "bears_corner_flare": bool(agent.bears_corner_flare),
    }


# ----------------------------------------------------------------------
# Public stats — anonymized (PB-1 BuyAVT polish, 2026-05-09)
# ----------------------------------------------------------------------

class PublicStatsResponse(BaseModel):
    total_backers: int
    total_avt_distributed: str
    sentinel_count: int
    architect_count: int
    founder_count: int
    # 2026-05-11 §12 — Shadow Cabinet count (cumulative ≥ €500). Hidden from
    # public tier-pitch; surfaced on FoundersWall as count-only.
    shadow_chancellor_count: int = 0
    founder_slots_total: int = 100  # First 100 Founders are forever — scarcity
    founder_slots_remaining: int
    recent_backers: List[dict] = Field(
        default_factory=list,
        description="Anonymized recent purchases — minutes_ago + flare tier only",
    )


@router.get(
    "/stats/public",
    response_model=PublicStatsResponse,
    summary="Public anonymized statistics of the fiat on-ramp",
)
async def get_public_stats(db: AsyncSession = Depends(get_db)):
    """
    Aggregate, anonymized statistics of the fiat on-ramp's completed purchases (no personal data). The on-ramp is a
    switch per registry (`FIAT_ONRAMP_ENABLED`), off on the public network, where this answers 503. Public, no auth.

    \f
    No auth, no PII. Returns aggregate counts + last N anonymized purchases.

    Used by BuyAVT's live ticker, Founder-scarcity strip, and animated counter.
    Uses fiat_purchases (status=completed) as the source of truth — only
    counts settled purchases. Flare counts derived from purchases_by_tier
    so refunded/abandoned rows don't inflate the founder slot scarcity.

    §BAFIN (2026-10-01): gated like /tiers. A backer counter and "founder slots remaining" are sales copy for a lane
    that is off.
    """
    if not _fiat_enabled():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Fiat onramp is not currently enabled on this registry.",
        )
    from sqlalchemy import func as sa_func, and_
    completed = FiatPurchaseStatus.COMPLETED.value

    # Aggregate counts from completed purchases
    total_eur_q = await db.execute(
        select(
            sa_func.count(FiatPurchase.id),
            sa_func.coalesce(sa_func.sum(FiatPurchase.amount_avt), 0),
        ).where(FiatPurchase.status == completed)
    )
    total_count, total_avt = total_eur_q.one()

    # Per-tier distinct backer counts. COALESCE fallback chain:
    #   developer_id (logged-in flow) → customer_email (anonymous, post-webhook
    #   row that hasn't auto-created a dev yet) → fiat_purchase.id (truly
    #   opaque rows like sandbox demos with no dev or email).
    # Without this chain, demo / partial-state rows count as 0 even when the
    # row clearly represents one human backer. (2026-05-10 fix.)
    tier_q = await db.execute(
        select(
            FiatPurchase.tier_label,
            sa_func.count(
                sa_func.distinct(
                    sa_func.coalesce(
                        sa.cast(FiatPurchase.developer_id, sa.String),
                        FiatPurchase.customer_email,
                        FiatPurchase.id,
                    )
                )
            ),
        )
        .where(FiatPurchase.status == completed)
        .group_by(FiatPurchase.tier_label)
    )
    tier_counts = {row[0]: row[1] for row in tier_q.all()}
    sentinel = int(tier_counts.get("tier_1_base", 0) or 0)
    architect = int(tier_counts.get("tier_2_value", 0) or 0)
    founder = int(tier_counts.get("tier_3_premium", 0) or 0)

    # 2026-05-11 §12 — Shadow Cabinet count: distinct developers whose
    # rolled-up flare_tier is shadow_chancellor. Cumulative-only tier;
    # the per-purchase tier_label histogram above doesn't surface it.
    # Filtered to developers who have at least one COMPLETED purchase
    # so we don't count admin-granted shadow flares with no actual backing.
    shadow_q = await db.execute(
        select(sa_func.count(sa_func.distinct(Developer.id)))
        .select_from(Developer)
        .join(FiatPurchase, FiatPurchase.developer_id == Developer.id)
        .where(Developer.flare_tier == 'shadow_chancellor')
        .where(FiatPurchase.status == completed)
    )
    shadow_chancellor_count = int(shadow_q.scalar() or 0)

    # Recent backers — last 10 completed, with optional Founders-Wall display
    # personalization (display_name + display_country, both nullable). The
    # show_on_wall=true filter excludes opted-out rows entirely. (2026-05-10)
    # 2026-05-11 §11: LEFT JOIN Developer to surface the buyer's CURRENT
    # rolled-up flare tier (so Shadow Chancellor — cumulative-only, never a
    # per-purchase tier_label — shows up in their right section). Falls back
    # to the per-purchase tier_label-derived flare for anonymous-flow rows
    # that haven't resolved a Developer yet, or rows where the dev hasn't
    # been flare-stamped (which shouldn't happen post-_grant_flare but is
    # defensive).
    now = datetime.now(timezone.utc)
    recent_q = await db.execute(
        select(
            FiatPurchase.tier_label,
            FiatPurchase.completed_at,
            FiatPurchase.amount_avt,
            FiatPurchase.display_name,
            FiatPurchase.display_country,
            Developer.flare_tier.label("dev_flare_tier"),
        )
        .outerjoin(Developer, Developer.id == FiatPurchase.developer_id)
        .where(FiatPurchase.status == completed)
        .where(FiatPurchase.show_on_wall.is_(True))
        .order_by(FiatPurchase.completed_at.desc().nullslast())
        .limit(20)
    )
    recent = []
    for tier_label, completed_at, amount_avt, display_name, display_country, dev_flare_tier in recent_q.all():
        if not completed_at:
            continue
        delta_sec = max(1, int((now - completed_at).total_seconds()))
        # Prefer the rolled-up Developer.flare_tier (handles Shadow Chancellor
        # and survives admin-granted upgrades). Fall back to per-purchase
        # tier_label mapping for anon-flow rows. Skip operator/commander
        # admin-only tiers — they aren't backer-tier display values.
        flare_tier_for_row = dev_flare_tier if (
            dev_flare_tier and dev_flare_tier not in ADMIN_ONLY_FLARE_TIERS
        ) else _TIER_TO_FLARE.get(tier_label, "sentinel")
        recent.append({
            "flare_tier": flare_tier_for_row,
            "tier_label": tier_label,
            "minutes_ago": delta_sec // 60,
            "seconds_ago": delta_sec,
            "amount_avt": str(int(Decimal(amount_avt).quantize(Decimal("1")))),
            "display_name": display_name,
            "display_country": display_country,
        })

    return PublicStatsResponse(
        total_backers=int(total_count or 0),
        total_avt_distributed=str(int(Decimal(total_avt or 0).quantize(Decimal("1")))),
        sentinel_count=sentinel,
        architect_count=architect,
        founder_count=founder,
        shadow_chancellor_count=shadow_chancellor_count,
        founder_slots_total=100,
        founder_slots_remaining=max(0, 100 - founder),
        recent_backers=recent,
    )


@router.get(
    "/purchase/{session_id}",
    response_model=PurchaseStatusResponse,
    summary="Fetch a fiat purchase's status by its session_id (public; for success-page polling)",
)
async def get_purchase_status(
    session_id: str, db: AsyncSession = Depends(get_db),
):
    """
    The status of a fiat on-ramp purchase by its payment session id; the unguessable session id is the proof, so no
    auth. The on-ramp is a switch per registry (`FIAT_ONRAMP_ENABLED`): where it is off, as on the public network,
    this answers 503 (403 on a registry that is not the genesis registry).
    """
    _require_runtime_ready()
    row = await db.execute(
        select(FiatPurchase).where(FiatPurchase.stripe_session_id == session_id)
    )
    purchase = row.scalar_one_or_none()
    if not purchase:
        raise HTTPException(404, f"Purchase session {session_id} not found")
    return PurchaseStatusResponse(
        fiat_purchase_id=purchase.id,
        stripe_session_id=purchase.stripe_session_id,
        status=purchase.status,
        eur_amount=str(purchase.amount_eur),
        avt_amount=str(purchase.amount_avt),
        tier_label=purchase.tier_label,
        agent_did=purchase.agent_did,
        avt_transfer_tx_id=purchase.avt_transfer_tx_id,
        anonymous_flow=purchase.anonymous_flow,
        created_at=purchase.created_at.isoformat(),
        completed_at=(
            purchase.completed_at.isoformat() if purchase.completed_at else None
        ),
        flare_tier=_flare_for_tier(purchase.tier_label),
    )


@router.get(
    "/my-purchases",
    response_model=List[PurchaseListItem],
    summary="Logged-in dev's purchase history",
)
async def list_my_purchases(
    current_dev: Developer = Security(get_current_developer_unified),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
):
    _require_runtime_ready()
    row = await db.execute(
        select(FiatPurchase)
        .where(FiatPurchase.developer_id == current_dev.id)
        .order_by(FiatPurchase.created_at.desc())
        .limit(min(max(limit, 1), 200))
    )
    purchases = row.scalars().all()
    return [
        PurchaseListItem(
            fiat_purchase_id=p.id,
            status=p.status,
            eur_amount=str(p.amount_eur),
            avt_amount=str(p.amount_avt),
            agent_did=p.agent_did,
            created_at=p.created_at.isoformat(),
            completed_at=p.completed_at.isoformat() if p.completed_at else None,
        )
        for p in purchases
    ]


# ----------------------------------------------------------------------
# Admin schemas
# ----------------------------------------------------------------------

class PricingConfigRow(BaseModel):
    id: str
    version: int
    config: dict
    is_active: bool
    note: Optional[str] = None
    created_at: str
    created_by_developer_id: Optional[int] = None
    deactivated_at: Optional[str] = None


class PricingResponse(BaseModel):
    active: Optional[PricingConfigRow] = None
    history: List[PricingConfigRow] = []
    fallback_in_use: bool = False


class PricingUpdateRequest(BaseModel):
    config: dict = Field(
        ...,
        description=(
            "Full JSON config — replaces the active one. Shape: "
            "{tiers: [{floor_eur, avt_per_eur, tier_label, bonus_label}, ...], "
            "min_eur, max_eur, currency}"
        ),
    )
    note: str = Field(
        ...,
        min_length=4, max_length=500,
        description="Audit-trail note. Required — explain why you're changing rates.",
    )


class PricingValidationResponse(BaseModel):
    valid: bool
    errors: List[str] = []


class SimulateRequest(BaseModel):
    config: Optional[dict] = Field(
        None,
        description="Proposed config; if omitted, uses currently-active.",
    )
    purchases_eur: List[str] = Field(
        ...,
        min_length=1, max_length=100000,
        description="List of EUR purchase amounts to simulate (decimal-strings).",
    )
    starting_treasury_avt: str = Field(
        ...,
        description="Genesis treasury AVT balance at start of simulation.",
    )
    starting_fee_collector_avt: str = Field(
        ...,
        description="fee_collector AVT balance at start of simulation.",
    )
    waterfall: Optional[List[str]] = Field(
        None,
        description="Source order. Default: ['fee_collector', 'treasury'].",
    )


# ----------------------------------------------------------------------
# Admin endpoints (admin_treasury gated)
# ----------------------------------------------------------------------

# =============================================================================
# PB-2 — Routed-fiat admin endpoint (federation-license-authed for operator-side reconciler)
# =============================================================================

@router.get(
    "/admin/fiat/routed/{mainframe_fiat_purchase_id}",
    summary="PB-2: query mainframe-side state for a routed FiatPurchase (federation-license-authed)",
    include_in_schema=False,
)
async def routed_fiat_admin_get(
    mainframe_fiat_purchase_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Operator-side reconciler queries this to get canonical state when a
    callback was lost. Auth: X-Federation-License header (existing
    verify_federation_license dep). Operators can ONLY query their own
    purchases — license.operator_did must match the row's
    target_operator_did.
    """
    if not _is_fiat_genesis():
        raise HTTPException(404, "Endpoint is mainframe-only")

    from .federation_licenses import verify_federation_license as _verify_fed_license, assert_licensee_type
    license_obj = await _verify_fed_license(
        x_federation_license=request.headers.get("X-Federation-License", ""),
        db=db,
    )
    assert_licensee_type(license_obj, "operator")  # D6-111: the operator-side reconciler's rail

    fp = await db.get(FiatPurchase, mainframe_fiat_purchase_id)
    if not fp:
        raise HTTPException(404, "FiatPurchase not found")
    if not fp.routed:
        raise HTTPException(404, "Not a routed-fiat purchase")
    if (fp.target_operator_did or "").lower() != (license_obj.operator_did or "").lower():
        raise HTTPException(
            403,
            "FiatPurchase belongs to a different operator (target_operator_did mismatch)",
        )

    return {
        "id": fp.id,
        "status": fp.status,
        "amount_eur": str(fp.amount_eur),
        "amount_avt": str(fp.amount_avt),
        "tier_label": fp.tier_label,
        "anonymous_flow": fp.anonymous_flow,
        "customer_email": fp.customer_email,
        "stripe_session_id": fp.stripe_session_id,
        "stripe_payment_intent_id": fp.stripe_payment_intent_id,
        "cross_teg_correlation_id": fp.cross_teg_correlation_id,
        "operator_callback_status": fp.operator_callback_status,
        "operator_callback_attempts": fp.operator_callback_attempts,
        "operator_callback_last_error": fp.operator_callback_last_error,
        "failure_reason": fp.failure_reason,
        "completed_at": fp.completed_at.isoformat() if fp.completed_at else None,
        "refunded_at": fp.refunded_at.isoformat() if fp.refunded_at else None,
        "requested_developer_name": fp.requested_developer_name,
        "requested_agent_name": fp.requested_agent_name,
    }


@admin_router.get(
    "/pricing",
    response_model=PricingResponse,
    summary="Active fiat pricing config + version history",
)
async def admin_get_pricing(
    db: AsyncSession = Depends(get_db),
    _admin: Developer = Depends(require_admin_flag("admin_treasury")),
):
    rows = (await db.execute(
        select(FiatPricingConfig).order_by(FiatPricingConfig.version.desc()).limit(50)
    )).scalars().all()

    active_row: Optional[FiatPricingConfig] = next((r for r in rows if r.is_active), None)
    history = [
        PricingConfigRow(
            id=r.id,
            version=r.version,
            config=r.config or {},
            is_active=r.is_active,
            note=r.note,
            created_at=r.created_at.isoformat(),
            created_by_developer_id=r.created_by_developer_id,
            deactivated_at=r.deactivated_at.isoformat() if r.deactivated_at else None,
        )
        for r in rows
    ]
    return PricingResponse(
        active=(history[next(i for i, r in enumerate(rows) if r.is_active)]
                if active_row else None),
        history=history,
        fallback_in_use=(active_row is None),
    )


@admin_router.post(
    "/pricing/validate",
    response_model=PricingValidationResponse,
    summary="Dry-run config validation (no DB write)",
)
async def admin_validate_pricing(
    req: PricingUpdateRequest,
    _admin: Developer = Depends(require_admin_flag("admin_treasury")),
):
    """Run validation logic against a proposed config WITHOUT saving it.
    Use before showing the simulate panel or hitting PUT /pricing."""
    errors = validate_config(req.config)
    return PricingValidationResponse(valid=(not errors), errors=errors)


@admin_router.put(
    "/pricing",
    response_model=PricingResponse,
    summary="Install a new pricing config version (atomic, audited)",
)
async def admin_put_pricing(
    req: PricingUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Depends(require_admin_flag("admin_treasury")),
):
    """
    Atomic update: deactivate current active row, insert new with
    version = max(version)+1, invalidate the in-memory cache.

    The note is REQUIRED — it goes into the audit trail. Operators should
    explain *why* the rates changed (regulatory, market conditions, etc.).
    """
    errors = validate_config(req.config)
    if errors:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Pricing config validation failed: {'; '.join(errors)}",
        )

    # Find current active + max version
    current_active = (await db.execute(
        select(FiatPricingConfig).where(FiatPricingConfig.is_active == True).limit(1)
    )).scalar_one_or_none()
    from sqlalchemy import func as sa_func
    max_version = (await db.execute(
        select(sa_func.coalesce(sa_func.max(FiatPricingConfig.version), 0))
    )).scalar() or 0
    new_version = max_version + 1

    # Atomic swap inside a single transaction:
    #   1. Deactivate current (release the partial-unique index)
    #   2. Flush
    #   3. Insert new active
    if current_active:
        current_active.is_active = False
        current_active.deactivated_at = datetime.now(timezone.utc)
        db.add(current_active)
        await db.flush()

    new_row = FiatPricingConfig(
        version=new_version,
        config=req.config,
        is_active=True,
        note=req.note,
        created_by_developer_id=admin.id,
    )
    db.add(new_row)
    await db.commit()
    await db.refresh(new_row)

    invalidate_pricing_cache()

    await _emit(
        event_type="FiatPricingConfigUpdated",
        aggregate_id=str(new_row.id),
        idempotency_key=f"fiat-pricing-config-{new_row.id}",
        data={
            "version": new_version,
            "previous_version": current_active.version if current_active else None,
            "by_developer_id": admin.id,
            "note": req.note,
        },
    )

    logger.info(
        "[fiat] pricing config v%d installed by dev=%s note=%r",
        new_version, admin.id, req.note,
    )

    # Return the fresh GET response so caller can refresh UI in one round-trip.
    return await admin_get_pricing(db=db, _admin=admin)  # type: ignore[arg-type]


@admin_router.post(
    "/pricing/simulate",
    summary="What-if simulation: run N purchases through a proposed configuration",
)
async def admin_simulate_pricing(
    req: SimulateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: Developer = Depends(require_admin_flag("admin_treasury")),
):
    """
    Pure arithmetic: nothing is written, so it is safe to run repeatedly. An entry of `purchases_eur` that does not
    validate is skipped with a warning. The treasury and fee account balances are amounts of this frame's unit; pass
    the current figures or a scenario. Needs an admin token with the `admin_treasury` flag.
    """
    # Resolve config — caller-supplied OR currently-active OR fallback.
    config = req.config or await get_active_pricing(db)
    cfg_errors = validate_config(config)
    if cfg_errors:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Simulation config invalid: {'; '.join(cfg_errors)}",
        )

    # Parse decimals up front so simulate_purchases doesn't have to.
    try:
        starting_treasury = Decimal(req.starting_treasury_avt)
        starting_fee_collector = Decimal(req.starting_fee_collector_avt)
    except Exception:
        raise HTTPException(400, "starting_treasury_avt / starting_fee_collector_avt must be decimal-strings")
    if starting_treasury < 0 or starting_fee_collector < 0:
        raise HTTPException(400, "Starting balances must be >= 0")

    purchases: List[Decimal] = []
    for raw in req.purchases_eur:
        try:
            purchases.append(Decimal(raw))
        except Exception:
            # Don't fail the whole sim — record the bad entry as a warning.
            purchases.append(Decimal("-1"))  # will be skipped + warned by simulator

    return simulate_purchases(
        config=config,
        purchases_eur=purchases,
        starting_treasury_avt=starting_treasury,
        starting_fee_collector_avt=starting_fee_collector,
        waterfall=req.waterfall,
    )


# ----------------------------------------------------------------------
# Admin schemas — purchase explorer + stats + manual ops
# ----------------------------------------------------------------------

class AdminPurchaseRow(BaseModel):
    id: str
    stripe_session_id: str
    stripe_event_id: Optional[str] = None
    stripe_payment_intent_id: Optional[str] = None
    developer_id: Optional[int] = None
    agent_did: Optional[str] = None
    customer_email: Optional[str] = None
    amount_eur: str
    amount_avt: str
    avt_per_eur_rate: str
    tier_label: str
    status: str
    failure_reason: Optional[str] = None
    avt_transfer_tx_id: Optional[str] = None
    anonymous_flow: bool
    created_at: str
    completed_at: Optional[str] = None
    refunded_at: Optional[str] = None


class AdminPurchaseListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    rows: List[AdminPurchaseRow]


class AdminPurchaseDetail(BaseModel):
    purchase: AdminPurchaseRow
    developer: Optional[dict] = None
    agent: Optional[dict] = None
    stripe_session: Optional[dict] = None
    has_magic_link: bool = False


class StatusCount(BaseModel):
    status: str
    count: int


class DailyRevenue(BaseModel):
    day: str  # YYYY-MM-DD
    eur: str
    avt: str
    purchases: int


class TierShare(BaseModel):
    tier_label: str
    count: int
    total_eur: str
    total_avt: str


class AdminFiatStats(BaseModel):
    window_days: int
    total_eur: str
    total_avt: str
    completed_count: int
    pending_count: int
    failed_count: int
    refunded_count: int
    success_rate_pct: str
    anonymous_devs_created: int
    avg_purchase_eur: str
    status_breakdown: List[StatusCount]
    daily_revenue: List[DailyRevenue]
    tier_share: List[TierShare]
    treasury_consumed_estimate_avt: str  # sum of completed amount_avt


class AdminPurchaseActionResponse(BaseModel):
    purchase_id: str
    action: str
    status: str
    detail: Optional[str] = None


# ----------------------------------------------------------------------
# Admin endpoints — purchase explorer
# ----------------------------------------------------------------------

@admin_router.get(
    "/purchases",
    response_model=AdminPurchaseListResponse,
    summary="List FiatPurchase rows with filters + pagination",
)
async def admin_list_purchases(
    status_filter: Optional[str] = None,
    email: Optional[str] = None,
    agent_did: Optional[str] = None,
    session_id: Optional[str] = None,
    days: int = 30,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    _admin: Developer = Depends(require_admin_flag("admin_treasury")),
):
    """
    Filter purchases by status (csv: pending,completed,failed,refunded), email
    substring, agent_did exact, session_id exact, last-N-days window. Returns
    paginated list + total count.
    """
    from sqlalchemy import or_, and_, func as sa_func
    days = max(1, min(days, 365))
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    q = select(FiatPurchase).where(FiatPurchase.created_at >= cutoff)

    if status_filter:
        statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
        if statuses:
            q = q.where(FiatPurchase.status.in_(statuses))
    if email:
        q = q.where(FiatPurchase.customer_email.ilike(f"%{email}%"))
    if agent_did:
        q = q.where(FiatPurchase.agent_did == agent_did)
    if session_id:
        q = q.where(FiatPurchase.stripe_session_id == session_id)

    # Total count (separate query — keep cheap by reusing filter)
    count_q = select(sa_func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    rows_q = q.order_by(FiatPurchase.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(rows_q)).scalars().all()

    return AdminPurchaseListResponse(
        total=int(total),
        limit=limit,
        offset=offset,
        rows=[_purchase_to_row(p) for p in rows],
    )


def _purchase_to_row(p: FiatPurchase) -> AdminPurchaseRow:
    return AdminPurchaseRow(
        id=p.id,
        stripe_session_id=p.stripe_session_id,
        stripe_event_id=p.stripe_event_id,
        stripe_payment_intent_id=p.stripe_payment_intent_id,
        developer_id=p.developer_id,
        agent_did=p.agent_did,
        customer_email=p.customer_email,
        amount_eur=str(p.amount_eur),
        amount_avt=str(p.amount_avt),
        avt_per_eur_rate=str(p.avt_per_eur_rate),
        tier_label=p.tier_label,
        status=p.status,
        failure_reason=p.failure_reason,
        avt_transfer_tx_id=p.avt_transfer_tx_id,
        anonymous_flow=p.anonymous_flow,
        created_at=p.created_at.isoformat(),
        completed_at=p.completed_at.isoformat() if p.completed_at else None,
        refunded_at=p.refunded_at.isoformat() if p.refunded_at else None,
    )


@admin_router.get(
    "/purchases/{purchase_id}",
    response_model=AdminPurchaseDetail,
    summary="Drill into a single FiatPurchase — joined Developer + Agent + Stripe session",
)
async def admin_get_purchase(
    purchase_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: Developer = Depends(require_admin_flag("admin_treasury")),
):
    p = await db.get(FiatPurchase, purchase_id)
    if not p:
        raise HTTPException(404, f"FiatPurchase {purchase_id} not found")

    dev_dict: Optional[dict] = None
    if p.developer_id:
        dev = await db.get(Developer, p.developer_id)
        if dev:
            dev_dict = {
                "id": dev.id,
                "name": dev.name,
                "email": dev.email,
                "is_verified": dev.is_verified,
                "must_change_password": dev.must_change_password,
                "has_password_reset_token": bool(dev.password_reset_token),
                "created_at": dev.created_at.isoformat(),
            }

    agent_dict: Optional[dict] = None
    if p.agent_did:
        agent_row = await db.execute(select(Agent).where(Agent.did == p.agent_did))
        agent = agent_row.scalar_one_or_none()
        if agent:
            agent_dict = {
                "id": agent.id,
                "did": agent.did,
                "client_id": agent.client_id,
                "status": agent.status,
                "creator_developer_id": agent.creator_developer_id,
                "liquid_balance": str(agent.liquid_balance or 0),
                "staked_balance": str(agent.staked_balance or 0),
                "created_at": agent.created_at.isoformat(),
            }

    # Stripe session — optional (best-effort) with a hard 4s timeout so the
    # drill-down endpoint stays snappy even if Stripe's API is slow.
    # `retrieve_session` is sync — wrap in to_thread + wait_for.
    stripe_session: Optional[dict] = None
    try:
        api_key = os.getenv("STRIPE_API_KEY", "")
        if api_key and p.stripe_session_id and not p.stripe_session_id.startswith("pending-"):
            session = await asyncio.wait_for(
                asyncio.to_thread(retrieve_session, api_key=api_key, session_id=p.stripe_session_id),
                timeout=4.0,
            )
            stripe_session = {
                "id": session.get("id"),
                "status": session.get("status"),
                "payment_status": session.get("payment_status"),
                "amount_total": session.get("amount_total"),
                "currency": session.get("currency"),
                "customer_email": session.get("customer_email"),
                "customer_details": session.get("customer_details"),
                "payment_intent": session.get("payment_intent"),
                "url": session.get("url"),
                "expires_at": session.get("expires_at"),
                "created": session.get("created"),
            }
    except asyncio.TimeoutError:
        logger.warning("[fiat] stripe session retrieve TIMEOUT for %s (>4s)", p.stripe_session_id)
    except Exception as exc:
        logger.warning("[fiat] stripe session retrieve failed for %s: %s", p.stripe_session_id, exc)

    return AdminPurchaseDetail(
        purchase=_purchase_to_row(p),
        developer=dev_dict,
        agent=agent_dict,
        stripe_session=stripe_session,
        has_magic_link=bool(dev_dict and dev_dict.get("has_password_reset_token") and p.anonymous_flow),
    )


@admin_router.get(
    "/stats",
    response_model=AdminFiatStats,
    summary="KPI aggregates for the fiat onramp dashboard",
)
async def admin_fiat_stats(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    _admin: Developer = Depends(require_admin_flag("admin_treasury")),
):
    from sqlalchemy import func as sa_func
    days = max(1, min(days, 365))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Status breakdown
    status_q = (
        select(FiatPurchase.status, sa_func.count())
        .where(FiatPurchase.created_at >= cutoff)
        .group_by(FiatPurchase.status)
    )
    status_rows = (await db.execute(status_q)).all()
    status_map = {s: c for s, c in status_rows}

    completed_count = status_map.get(FiatPurchaseStatus.COMPLETED.value, 0)
    pending_count = status_map.get(FiatPurchaseStatus.PENDING.value, 0)
    failed_count = status_map.get(FiatPurchaseStatus.FAILED.value, 0)
    refunded_count = status_map.get(FiatPurchaseStatus.REFUNDED.value, 0)
    total_count = sum(status_map.values())
    success_rate = (
        (Decimal(completed_count) / Decimal(total_count) * Decimal("100")).quantize(Decimal("0.1"))
        if total_count > 0 else Decimal("0")
    )

    # Money totals (completed only — pending/failed don't move funds)
    money_q = (
        select(
            sa_func.coalesce(sa_func.sum(FiatPurchase.amount_eur), 0),
            sa_func.coalesce(sa_func.sum(FiatPurchase.amount_avt), 0),
        )
        .where(FiatPurchase.created_at >= cutoff)
        .where(FiatPurchase.status == FiatPurchaseStatus.COMPLETED.value)
    )
    total_eur, total_avt = (await db.execute(money_q)).one()

    avg_eur = (
        (Decimal(str(total_eur)) / Decimal(completed_count)).quantize(Decimal("0.01"))
        if completed_count > 0 else Decimal("0")
    )

    # Anonymous-flow developers created (count distinct developer_id where anon=true)
    anon_devs_q = (
        select(sa_func.count(sa_func.distinct(FiatPurchase.developer_id)))
        .where(FiatPurchase.created_at >= cutoff)
        .where(FiatPurchase.anonymous_flow == True)
        .where(FiatPurchase.developer_id.is_not(None))
    )
    anon_devs = (await db.execute(anon_devs_q)).scalar() or 0

    # Daily revenue sparkline — completed purchases only.
    # Use cast(...AS DATE) instead of date_trunc('day', ...) — the latter
    # parameterizes 'day' separately in SELECT vs GROUP BY positions, which
    # PG sees as distinct expressions (asyncpg.GroupingError).
    from sqlalchemy import Date, cast
    day_col = cast(FiatPurchase.completed_at, Date)
    daily_q = (
        select(
            day_col.label("day"),
            sa_func.coalesce(sa_func.sum(FiatPurchase.amount_eur), 0).label("eur"),
            sa_func.coalesce(sa_func.sum(FiatPurchase.amount_avt), 0).label("avt"),
            sa_func.count().label("purchases"),
        )
        .where(FiatPurchase.completed_at >= cutoff)
        .where(FiatPurchase.status == FiatPurchaseStatus.COMPLETED.value)
        .group_by(day_col)
        .order_by(day_col.asc())
    )
    daily_rows = (await db.execute(daily_q)).all()
    daily_revenue = [
        DailyRevenue(
            day=(row.day.isoformat() if row.day else "?"),
            eur=str(row.eur),
            avt=str(row.avt),
            purchases=int(row.purchases),
        )
        for row in daily_rows
    ]

    # Tier share
    tier_q = (
        select(
            FiatPurchase.tier_label,
            sa_func.count().label("count"),
            sa_func.coalesce(sa_func.sum(FiatPurchase.amount_eur), 0).label("eur"),
            sa_func.coalesce(sa_func.sum(FiatPurchase.amount_avt), 0).label("avt"),
        )
        .where(FiatPurchase.created_at >= cutoff)
        .where(FiatPurchase.status == FiatPurchaseStatus.COMPLETED.value)
        .group_by(FiatPurchase.tier_label)
        .order_by(sa_func.count().desc())
    )
    tier_rows = (await db.execute(tier_q)).all()
    tier_share = [
        TierShare(
            tier_label=row.tier_label,
            count=int(row.count),
            total_eur=str(row.eur),
            total_avt=str(row.avt),
        )
        for row in tier_rows
    ]

    return AdminFiatStats(
        window_days=days,
        total_eur=str(total_eur),
        total_avt=str(total_avt),
        completed_count=completed_count,
        pending_count=pending_count,
        failed_count=failed_count,
        refunded_count=refunded_count,
        success_rate_pct=str(success_rate),
        anonymous_devs_created=int(anon_devs),
        avg_purchase_eur=str(avg_eur),
        status_breakdown=[StatusCount(status=s, count=c) for s, c in status_map.items()],
        daily_revenue=daily_revenue,
        tier_share=tier_share,
        treasury_consumed_estimate_avt=str(total_avt),
    )


# ----------------------------------------------------------------------
# Admin endpoints — manual ops (replay, resend-magic-link, refund)
# ----------------------------------------------------------------------

@admin_router.post(
    "/purchases/{purchase_id}/replay",
    response_model=AdminPurchaseActionResponse,
    summary="Re-run webhook handler for a stuck pending/failed purchase",
)
async def admin_replay_purchase(
    purchase_id: str,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Depends(require_admin_flag("admin_treasury")),
):
    """
    Manual recovery for stuck purchases. Resets `stripe_event_id` so the handler
    can re-process, then re-runs the checkout-completion handler INLINE
    (not via Stripe's webhook). Useful for:
      • Failed funding call (e.g. TEG was down)
      • Anonymous flow where Developer/Agent creation crashed
      • Stripe webhook never arrived (Commander observed payment elsewhere)

    Refuses to replay rows already in `completed` or `refunded` state.
    """
    p = await db.get(FiatPurchase, purchase_id)
    if not p:
        raise HTTPException(404, f"FiatPurchase {purchase_id} not found")

    if p.status in (FiatPurchaseStatus.COMPLETED.value, FiatPurchaseStatus.REFUNDED.value):
        raise HTTPException(
            400,
            f"Cannot replay — purchase already {p.status}. Use refund flow instead.",
        )

    # Reset state for replay
    p.status = FiatPurchaseStatus.PENDING.value
    p.failure_reason = None
    p.stripe_event_id = None
    await db.commit()

    # Build a synthetic event matching what Stripe would have sent. We only
    # need enough to satisfy `_handle_checkout_completed` — the metadata
    # carries our purchase_id which is the canonical key.
    # 2026-07-27: this used to hand `_handle_checkout_completed` a raw Stripe-shaped dict. The
    # PB-3 multi-provider refactor changed that handler to take a normalized ProviderEvent, so
    # every replay died on `'dict' object has no attribute 'provider_event_id'` — i.e. the admin
    # recovery tool for stuck purchases has been dead since the refactor, and silently so because
    # nothing replays a purchase on a happy path. Build the real envelope instead.
    from agentvault_registry.services.fiat_providers import ProviderEvent
    synthetic_raw = {
        "id": f"manual-replay-{secrets.token_hex(8)}",
        "type": "checkout.session.completed",
        "data": {"object": {"id": p.stripe_session_id}},
    }
    synthetic_event = ProviderEvent(
        provider="stripe",
        # Distinct per replay: the handler's L1 idempotency anchors on this, and reusing the
        # original event id would make a deliberate replay look like a duplicate and no-op.
        provider_event_id=synthetic_raw["id"],
        provider_session_id=p.stripe_session_id or f"manual-{p.id}",
        provider_payment_id=p.stripe_payment_intent_id,
        kind="checkout_completed",
        metadata={
            "fiat_purchase_id": p.id,
            "agent_did": p.agent_did or "",
            "anonymous_flow": "true" if p.anonymous_flow else "false",
            "tier_label": p.tier_label,
        },
        customer_email=p.customer_email,
        raw=synthetic_raw,
    )

    # Run inline so the admin sees the result immediately
    try:
        await _handle_checkout_completed(synthetic_event)
    except Exception as exc:
        logger.exception("[fiat] manual replay failed for %s", p.id)
        raise HTTPException(500, f"Replay failed: {exc}")

    # Reload to read the post-handler state
    await db.refresh(p)

    logger.info(
        "[fiat] manual replay by dev=%s purchase=%s → status=%s",
        admin.id, p.id, p.status,
    )

    return AdminPurchaseActionResponse(
        purchase_id=p.id,
        action="replay",
        status=p.status,
        detail=p.failure_reason or f"Replay completed; status now {p.status}",
    )


@admin_router.post(
    "/purchases/{purchase_id}/resend-magic-link",
    response_model=AdminPurchaseActionResponse,
    summary="Re-issue magic-link login email (anonymous flow only)",
)
async def admin_resend_magic_link(
    purchase_id: str,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Depends(require_admin_flag("admin_treasury")),
):
    """
    Generate a new password_reset_token for the anonymous-flow Developer and
    re-send the welcome email. Useful when the original email got lost or
    expired (3-day TTL).
    """
    p = await db.get(FiatPurchase, purchase_id)
    if not p:
        raise HTTPException(404, f"FiatPurchase {purchase_id} not found")
    if not p.anonymous_flow:
        raise HTTPException(400, "Magic-link is only meaningful for anonymous-flow purchases")
    if not p.developer_id:
        raise HTTPException(400, "No developer_id on this purchase yet — try replay first")
    if p.status != FiatPurchaseStatus.COMPLETED.value:
        raise HTTPException(400, f"Cannot resend magic-link — status is {p.status}")

    dev = await db.get(Developer, p.developer_id)
    if not dev:
        raise HTTPException(404, "Developer not found")

    # Re-issue token
    new_token = secrets.token_urlsafe(32)
    dev.password_reset_token = new_token
    dev.password_reset_token_expires = datetime.now(timezone.utc) + timedelta(days=3)
    db.add(dev)
    await db.commit()
    await db.refresh(dev)

    # Send the email (best-effort; we DO want to error if the send fails so admin sees it)
    asyncio.create_task(_send_purchase_email(p, p.agent_did or "(no agent)", p.avt_transfer_tx_id or "(no tx)"))

    logger.info(
        "[fiat] magic-link resent by dev=%s purchase=%s recipient=%s",
        admin.id, p.id, dev.email,
    )

    return AdminPurchaseActionResponse(
        purchase_id=p.id,
        action="resend_magic_link",
        status="sent",
        detail=f"New magic-link emailed to {dev.email} (token expires in 3 days)",
    )


@admin_router.post(
    "/purchases/{purchase_id}/refund",
    response_model=AdminPurchaseActionResponse,
    summary="Issue a Stripe refund + flag the FiatPurchase as refunded",
)
async def admin_refund_purchase(
    purchase_id: str,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Depends(require_admin_flag("admin_treasury")),
):
    """
    Issue a Stripe refund (stripe.Refund.create()) and mark the purchase refunded. It does not take back the units the
    purchase delivered: an administrator reads the FiatPurchaseRefunded event and decides on any enforcement
    separately. A purchase that is not completed is refused (400). Needs an admin token with the `admin_treasury`
    flag.

    \f
    Issue a Stripe refund via stripe.Refund.create() and mark the FiatPurchase
    as refunded. **Does NOT auto-claw AVT** — Strategy doc §7 hard rule.
    Commander reviews the FiatPurchaseRefunded event + decides on enforcement
    (slash, suspend agent, etc.) separately.

    Refuses to refund rows not in `completed` state.
    """
    p = await db.get(FiatPurchase, purchase_id)
    if not p:
        raise HTTPException(404, f"FiatPurchase {purchase_id} not found")
    if p.status != FiatPurchaseStatus.COMPLETED.value:
        raise HTTPException(400, f"Cannot refund — status is {p.status}, must be completed")
    if not p.stripe_payment_intent_id:
        raise HTTPException(400, "No stripe_payment_intent_id on this purchase — cannot refund")

    # Issue Stripe refund
    api_key = os.getenv("STRIPE_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "STRIPE_API_KEY not configured")
    try:
        import stripe  # type: ignore
        stripe.api_key = api_key
        # .to_dict(): stripe-python 15's StripeObject has no .get() (§DEPS stripe15)
        refund = stripe.Refund.create(
            payment_intent=p.stripe_payment_intent_id,
            reason="requested_by_customer",
            metadata={"fiat_purchase_id": p.id, "issued_by_developer_id": str(admin.id)},
        ).to_dict()
        refund_id = refund.get("id")
    except Exception as exc:
        logger.exception("[fiat] Stripe refund failed for %s", p.id)
        raise HTTPException(502, f"Stripe refund failed: {exc}")

    # Flag the row
    p.status = FiatPurchaseStatus.REFUNDED.value
    p.refunded_at = datetime.now(timezone.utc)
    p.failure_reason = f"Refunded by admin dev_id={admin.id} stripe_refund={refund_id}"
    db.add(p)
    await db.commit()

    await _emit(
        event_type="FiatPurchaseRefunded",
        aggregate_id=p.id,
        idempotency_key=f"fiat-refunded-{p.id}",
        data={
            "fiat_purchase_id": p.id,
            "stripe_refund_id": refund_id,
            "amount_eur": str(p.amount_eur),
            "amount_avt": str(p.amount_avt),
            "agent_did": p.agent_did,
            "issued_by_developer_id": admin.id,
            "avt_clawed_back": False,
        },
    )

    logger.warning(
        "[fiat] manual refund by dev=%s purchase=%s stripe_refund=%s — AVT NOT clawed",
        admin.id, p.id, refund_id,
    )

    return AdminPurchaseActionResponse(
        purchase_id=p.id,
        action="refund",
        status="refunded",
        detail=f"Stripe refund {refund_id} issued. AVT not clawed back — review enforcement separately.",
    )


# ----------------------------------------------------------------------
# Admin-granted flares (PB-1 hardening, 2026-05-09)
# ----------------------------------------------------------------------

@admin_router.post(
    "/flare/grant",
    response_model=AdminFlareGrantResponse,
    summary="Admin-grant a flare tier to a developer (incl. operator|commander)",
)
async def admin_grant_flare(
    req: AdminFlareGrantRequest,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Depends(require_admin_flag("admin_treasury")),
):
    """Manual flare grant for non-purchasable tiers + corrective overrides.

    Tier validation:
      • Must be in {sentinel, architect, founder, operator, commander}
      • operator + commander are admin-only — can never be granted by fiat
        purchase (the rank table protects them).

    Force semantics:
      • Default for admin-only tiers (operator, commander): force=true
      • Default for payment tiers (sentinel, architect, founder): force=false
        (admin grant only "upgrades" — preserves rank-wins on existing flares)
      • Caller can override either way via explicit `force` field

    Customization fields, when provided, are applied to the developer's flare
    customization slots verbatim (no validation beyond schema length caps and
    URL/color sanity checked elsewhere on PATCH /customize).

    Idempotent: replaying with same args produces the same end state.
    """
    if req.tier not in ALL_FLARE_TIERS:
        raise HTTPException(
            400,
            f"Unknown flare tier {req.tier!r}. Valid: {sorted(ALL_FLARE_TIERS)}",
        )

    # Default force based on tier class
    force = req.force
    if force is None:
        force = req.tier in ADMIN_ONLY_FLARE_TIERS

    # Locate target developer
    dev_row = await db.execute(select(Developer).where(Developer.id == req.developer_id))
    dev: Optional[Developer] = dev_row.scalar_one_or_none()
    if not dev:
        raise HTTPException(404, f"Developer {req.developer_id} not found")

    # Optional: validate the agent ownership before stamping
    target_agent: Optional[Agent] = None
    if req.agent_did:
        agent_row = await db.execute(select(Agent).where(Agent.did == req.agent_did))
        target_agent = agent_row.scalar_one_or_none()
        if not target_agent:
            raise HTTPException(404, f"Agent {req.agent_did} not found")
        if target_agent.creator_developer_id != dev.id:
            raise HTTPException(
                400,
                f"Agent {req.agent_did} is not owned by developer {dev.id}",
            )

    # Apply higher-rank-wins unless force=true
    proceed = force or _should_overwrite_flare(dev.flare_tier, req.tier)
    if not proceed:
        raise HTTPException(
            409,
            f"Existing flare tier {dev.flare_tier!r} outranks {req.tier!r}; "
            f"pass force=true to override.",
        )

    # Mint flare_id on first grant; preserve across grants.
    import uuid as _uuid
    if not dev.flare_id:
        dev.flare_id = str(_uuid.uuid4())

    now = datetime.now(timezone.utc)
    dev.flare_tier = req.tier
    dev.flare_granted_at = now
    # Admin grants don't have a fiat_purchase_id — leave the FK null.
    dev.flare_source_purchase_id = None

    # 2026-05-12 §14: when admin-granting an encirclement-class tier, default
    # the variant to 'sauron' if the dev doesn't have one. Caller can override
    # later via PATCH /flare/selection.
    if req.tier == 'shadow_chancellor':
        if not dev.flare_encirclement_variant:
            dev.flare_encirclement_variant = DEFAULT_ENCIRCLEMENT_VARIANT
        # Auto-populate selected_encirclement_flare too, mirroring the
        # cumulative-grant path so the visual lights up immediately.
        if not dev.selected_encirclement_flare:
            dev.selected_encirclement_flare = 'shadow_chancellor'
        # §15 (2026-05-13): also seed selected_corner_flare with the canonical
        # companion 'founder' so the corner slot is non-null on first grant.
        # Without this, "Hide corner" in the picker reads as no-op because the
        # frontend can't distinguish "never picked" from "explicitly hidden".
        if not dev.selected_corner_flare:
            dev.selected_corner_flare = 'founder'
    elif req.tier in ('sentinel', 'architect', 'founder', 'operator', 'commander'):
        # Corner-class admin grants: seed selected_corner_flare with the tier
        # so the badge displays immediately. User can later switch via picker.
        if not dev.selected_corner_flare:
            dev.selected_corner_flare = req.tier

    # Customization (apply verbatim when provided; null = leave alone).
    if req.display_name is not None: dev.flare_display_name = req.display_name or None
    if req.tagline      is not None: dev.flare_tagline      = req.tagline      or None
    if req.logo_url     is not None: dev.flare_logo_url     = req.logo_url     or None
    if req.link_url     is not None: dev.flare_link_url     = req.link_url     or None
    if req.cause        is not None: dev.flare_cause        = req.cause        or None
    if req.accent_color is not None: dev.flare_accent_color = req.accent_color or None
    db.add(dev)

    # Optionally stamp the agent flare too
    agent_did_stamped = None
    if target_agent:
        target_agent.flare_tier = req.tier
        target_agent.flare_granted_at = now
        target_agent.flare_source_purchase_id = None
        db.add(target_agent)
        agent_did_stamped = target_agent.did

    await db.commit()
    await db.refresh(dev)

    logger.info(
        "[fiat] admin-grant flare dev=%s tier=%s agent=%s by_dev=%s force=%s",
        dev.id, req.tier, agent_did_stamped, admin.id, force,
    )

    # Reconcile provisioning months from purchase history. Idempotent — only
    # adds when the developer's purchase total exceeds their credited months
    # (e.g., admin grants shadow_chancellor on a dev whose purchase hook was
    # dropped, OR seed-data devs whose history bypassed the per-settle hook).
    # Operator/Commander tiers don't need this (no payment history), but the
    # helper is safe to call on any tier.
    try:
        await _reconcile_provisioning_credit_from_purchases(
            db=db, developer_id=dev.id,
        )
    except Exception as exc:
        logger.warning(
            "[admin_grant_flare] reconcile failed for dev=%s: %s — non-fatal",
            dev.id, exc,
        )

    return AdminFlareGrantResponse(
        developer_id=dev.id,
        flare_id=dev.flare_id,
        flare_tier=dev.flare_tier,
        flare_granted_at=dev.flare_granted_at.isoformat(),
        agent_did_stamped=agent_did_stamped,
    )


@admin_router.post(
    "/provisioning/reconcile/{developer_id}",
    summary="Reconcile a developer's provisioning months from purchase history",
)
async def admin_reconcile_provisioning(
    developer_id: int,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Depends(require_admin_flag("admin_treasury")),
):
    """One-shot reconciliation endpoint — recovers provisioning months for
    a developer whose `provisioning_months_total` doesn't reflect their
    completed purchase history. Idempotent.

    Use when:
      • Seed data / fixtures bypassed the per-settle credit hook
      • A previous settle dropped its credit (rare race / DB rollback)
      • An admin granted shadow_chancellor manually without invoking the
        cumulative path

    Strictly add-only — never deducts months. Over-credited devs are no-ops.
    """
    dev_row = await db.execute(select(Developer).where(Developer.id == developer_id))
    dev = dev_row.scalar_one_or_none()
    if not dev:
        raise HTTPException(404, f"Developer {developer_id} not found")

    months_added, months_total = await _reconcile_provisioning_credit_from_purchases(
        db=db, developer_id=developer_id,
    )
    await db.refresh(dev)

    logger.info(
        "[admin] reconcile_provisioning dev=%s by_admin=%s → +%dmo total=%d",
        developer_id, admin.id, months_added, months_total,
    )

    return {
        "developer_id": developer_id,
        "months_added": months_added,
        "months_total": months_total,
        "provisioning_unlocked_until": (
            dev.provisioning_unlocked_until.isoformat()
            if dev.provisioning_unlocked_until else None
        ),
    }


@admin_router.post(
    "/flare/revoke/{developer_id}",
    summary="Admin-revoke a developer's flare entirely (cosmetic-only)",
)
async def admin_revoke_flare(
    developer_id: int,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Depends(require_admin_flag("admin_treasury")),
):
    """Remove the flare from a developer and from every agent the developer owns. Cosmetic only: no balance
    changes, and the purchase behind the flare is not refunded. The flare's id is cleared too, so a later grant gets a
    new one. Needs an admin token with the `admin_treasury` flag.
    """
    dev_row = await db.execute(select(Developer).where(Developer.id == developer_id))
    dev: Optional[Developer] = dev_row.scalar_one_or_none()
    if not dev:
        raise HTTPException(404, f"Developer {developer_id} not found")
    if not dev.flare_tier and not dev.flare_id:
        return {"developer_id": developer_id, "status": "no_flare_to_revoke"}

    prior_tier = dev.flare_tier
    prior_flare_id = dev.flare_id

    # Wipe developer flare entirely
    dev.flare_tier = None
    dev.flare_granted_at = None
    dev.flare_source_purchase_id = None
    dev.flare_id = None
    dev.flare_display_name = None
    dev.flare_tagline = None
    dev.flare_logo_url = None
    dev.flare_link_url = None
    dev.flare_cause = None
    dev.flare_accent_color = None
    db.add(dev)

    # Wipe ALL agents owned by this developer
    own_agents = await db.execute(
        select(Agent).where(
            Agent.creator_developer_id == dev.id,
            Agent.flare_tier.is_not(None),
        )
    )
    cleared = 0
    for a in own_agents.scalars().all():
        a.flare_tier = None
        a.flare_granted_at = None
        a.flare_source_purchase_id = None
        db.add(a)
        cleared += 1

    # ── §FLARETOUCH (2026-09-09) — ROW-ONLY STATE NEVER REACHES A MIRROR ────────────────────
    # This rail changed `developers` and `agents` rows and never touched the CARD, so every peer
    # holding a mirror kept the revoked flare FOREVER: the export feed is ordered by the card's
    # own clock, and nothing here moved it. Measured today — 41 revocations on frame-c, 0 cards
    # touched, and Registry-A went on rendering all 24 of them in "Distinguished Agents".
    # Exactly the class §ENFPROP closed for suspend/reinstate/self-delete; this rail predates it.
    #
    # ⚠ AND IT MUST BE EVERY AGENT THE DEVELOPER OWNS, not the `flare_tier IS NOT NULL` subset
    # above. §COSMETICS-ORIGIN ships the flare sidecar when EITHER the agent OR the developer
    # holds a tier, so clearing the DEVELOPER changes what is exported for agents that never had
    # a tier of their own — and those are precisely the ones the loop above never visits.
    from ..services import enforcement_propagation as _ep
    _all_owned = await db.execute(
        select(Agent).where(Agent.creator_developer_id == dev.id)
    )
    touched = 0
    for a in _all_owned.scalars().all():
        _did = getattr(a, "did", None)
        if _did:
            touched += await _ep.touch_native_card_no_commit(db, _did)

    await db.commit()
    logger.warning(
        "[fiat] admin-revoke flare dev=%s prior_tier=%s prior_flare_id=%s agents_cleared=%d by_dev=%s",
        dev.id, prior_tier, prior_flare_id, cleared, admin.id,
    )
    return {
        "developer_id": developer_id,
        "status": "revoked",
        "prior_tier": prior_tier,
        "prior_flare_id": prior_flare_id,
        "agents_cleared": cleared,
        # named in the response so a caller can SEE whether the change can reach a peer at all
        "cards_touched": touched,
    }


@admin_router.get(
    "/flares",
    summary="List all developers with a flare (admin Flare Ops UI)",
)
async def admin_list_flares(
    db: AsyncSession = Depends(get_db),
    _admin: Developer = Depends(require_admin_flag("admin_treasury")),
    limit: int = 500,
):
    """Returns one row per flare-bearing developer with full customization.
    Drives the AdminFiatOps Flare Ops tab. Ordered by tier rank descending
    then granted_at descending (Commander/Operator first, then most-recent
    Founders, then Architects, then Sentinels)."""
    rows = await db.execute(
        select(Developer)
        .where(Developer.flare_tier.is_not(None))
        .limit(min(max(limit, 1), 2000))
    )
    devs = rows.scalars().all()
    out = []
    for dev in devs:
        out.append({
            "developer_id": dev.id,
            "email": dev.email,
            "name": dev.name,
            "flare_id": dev.flare_id,
            "flare_tier": dev.flare_tier,
            "flare_granted_at": (
                dev.flare_granted_at.isoformat() if dev.flare_granted_at else None
            ),
            "flare_display_name": dev.flare_display_name,
            "flare_tagline": dev.flare_tagline,
            "flare_logo_url": dev.flare_logo_url,
            "flare_link_url": dev.flare_link_url,
            "flare_cause": dev.flare_cause,
            "flare_accent_color": dev.flare_accent_color,
        })
    # Sort by tier rank desc, then granted_at desc (newest first within tier)
    rank = {"sentinel": 1, "architect": 2, "founder": 3, "operator": 50, "commander": 99}
    out.sort(key=lambda r: (
        -rank.get(r["flare_tier"] or "", 0),
        -(int(r["flare_granted_at"].split("T")[0].replace("-", "")) if r["flare_granted_at"] else 0),
    ))
    return out


# ----------------------------------------------------------------------
# Auto-grant helpers (PB-1 Phase P, 2026-05-09)
# ----------------------------------------------------------------------

async def auto_grant_operator_flare(*, db: AsyncSession, developer: Developer):
    """Auto-grant the operator flare to a developer who just became a
    federation operator. Called from operator-activation flow.

    Honors higher-rank-wins: a Commander or Founder isn't downgraded.
    Idempotent: re-calling on an existing operator is a no-op (rank check
    rejects equal-tier overwrite).

    Default customization is set ONLY when the developer doesn't already have
    customization on their flare — re-activating an operator who customized
    their flare won't reset their fields.

    Cosmetic-only — zero AVT effect.
    """
    import uuid as _uuid

    proposed = "operator"
    # Don't downgrade — commander/founder/architect/sentinel-with-rank-equal-or-higher all skip.
    # operator outranks all 3 payment tiers, so this typically grants when:
    #   - dev has no flare (None outranked by anything)
    #   - dev has sentinel/architect/founder (operator rank 50 > 1/2/3)
    if not _should_overwrite_flare(developer.flare_tier, proposed):
        logger.info(
            "[fiat] auto-grant operator skipped — dev=%s already has tier=%s (outranks operator)",
            developer.id, developer.flare_tier,
        )
        return

    now = datetime.now(timezone.utc)
    developer.flare_tier = proposed
    developer.flare_granted_at = now
    developer.flare_source_purchase_id = None  # admin-grant has no fiat origin
    if not developer.flare_id:
        developer.flare_id = str(_uuid.uuid4())

    # Sensible operator defaults — only set if EMPTY (don't clobber prior customization).
    if not developer.flare_display_name:
        developer.flare_display_name = developer.name or f"Operator-{developer.id}"
    if not developer.flare_tagline:
        developer.flare_tagline = "Federation operator — trusted infrastructure."
    if not developer.flare_cause:
        developer.flare_cause = "Network reliability"
    if not developer.flare_accent_color:
        developer.flare_accent_color = "#67E8F9"

    db.add(developer)
    await db.commit()
    logger.info(
        "[fiat] auto-granted operator flare dev=%s flare_id=%s",
        developer.id, developer.flare_id,
    )
