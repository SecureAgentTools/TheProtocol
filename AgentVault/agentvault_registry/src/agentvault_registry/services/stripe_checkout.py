"""
stripe_checkout.py — Stripe Checkout Session helper for fiat → AVT (PB-1).

PB-1 commitment (Business Model Part 6): user pays EUR via Stripe Checkout,
TheProtocol receives EUR via Kontist SEPA payout, AVT credited to user's
agent via existing /admin/reward-fund waterfall.

This is Stripe Checkout / Payment Intents API, **NOT** Stripe Crypto Onramp.
Onramp delivers public-blockchain crypto to user's wallet (wrong product for
an internal utility token). See feedback_stripe_checkout_not_onramp.md.

Pricing is **DB-driven and versioned** (table: `fiat_pricing_config`). The
helpers in this module are pure functions that take a config dict — the
config-loading + caching live in `_load_active_config()` below. Operators
update pricing via admin endpoint; every change is auditable.

Mainframe-only: this module is imported by routers/fiat_onramp.py which
returns HTTP 403 on federated registries (FIAT_GENESIS_REGISTRY=false).
"""
from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hard-coded fallback (used ONLY if DB load fails)
# ---------------------------------------------------------------------------
# These are the v1 defaults from migration 0032. They exist solely as a
# defense-in-depth fallback so the public /tiers + /quote endpoints stay
# usable if the DB query fails. The active config is the AUTHORITATIVE
# source — never edit these constants to change live pricing.

FALLBACK_CONFIG: Dict[str, Any] = {
    "tiers": [
        {"floor_eur": "1.00",   "avt_per_eur": "2000", "tier_label": "tier_1_base",    "bonus_label": ""},
        {"floor_eur": "20.00",  "avt_per_eur": "2500", "tier_label": "tier_2_value",   "bonus_label": "+25%"},
        {"floor_eur": "100.00", "avt_per_eur": "3000", "tier_label": "tier_3_premium", "bonus_label": "+50%"},
    ],
    "min_eur": "1.00",
    "max_eur": "500.00",
    "currency": "EUR",
}


# ---------------------------------------------------------------------------
# Config loading + caching (60s TTL)
# ---------------------------------------------------------------------------
# Cluster runs N uvicorn workers; each worker has its own cache. A pricing
# update via admin endpoint takes up to 60s to propagate to all workers.
# That's an acceptable trade-off for not hammering the DB on every /quote.

_CACHE: Dict[str, Any] = {"config": None, "version": None, "loaded_at": 0.0}
_CACHE_TTL_SECONDS = 60.0
_CACHE_LOCK = asyncio.Lock()


async def _load_active_config(db: AsyncSession) -> Tuple[Dict[str, Any], Optional[int]]:
    """
    Load the currently-active pricing config from DB.

    Returns (config_dict, version). Falls back to FALLBACK_CONFIG if the DB
    query fails or no active row exists. version is None for fallback.
    """
    # Lazy import — avoid circular dep at module-load time.
    from ..models import FiatPricingConfig
    try:
        row = await db.execute(
            select(FiatPricingConfig).where(FiatPricingConfig.is_active == True).limit(1)
        )
        active = row.scalar_one_or_none()
        if active and isinstance(active.config, dict):
            return active.config, active.version
    except Exception as exc:
        logger.warning("[fiat] active config load failed, using fallback: %s", exc)
    return FALLBACK_CONFIG, None


async def get_active_pricing(db: AsyncSession, *, bypass_cache: bool = False) -> Dict[str, Any]:
    """
    Cached accessor for the active pricing config.

    Pass bypass_cache=True when you've just updated the config (admin
    endpoint does this to ensure the immediately-following /tiers call
    reflects the new state).
    """
    now = time.monotonic()
    if (
        not bypass_cache
        and _CACHE["config"] is not None
        and (now - _CACHE["loaded_at"]) < _CACHE_TTL_SECONDS
    ):
        return _CACHE["config"]

    async with _CACHE_LOCK:
        # Double-check inside the lock (another coroutine may have loaded it)
        now2 = time.monotonic()
        if (
            not bypass_cache
            and _CACHE["config"] is not None
            and (now2 - _CACHE["loaded_at"]) < _CACHE_TTL_SECONDS
        ):
            return _CACHE["config"]
        config, version = await _load_active_config(db)
        _CACHE["config"] = config
        _CACHE["version"] = version
        _CACHE["loaded_at"] = now2
        return config


def invalidate_pricing_cache() -> None:
    """Forcibly drop the cache. Call after admin PUTs."""
    _CACHE["config"] = None
    _CACHE["version"] = None
    _CACHE["loaded_at"] = 0.0


# ---------------------------------------------------------------------------
# Pure-math helpers (take config explicitly — no globals, no side effects)
# ---------------------------------------------------------------------------

def _sorted_tiers_desc(config: Dict[str, Any]) -> List[Dict[str, str]]:
    """Tiers sorted by floor_eur DESC (highest tier first — match-by-floor logic)."""
    tiers = config.get("tiers") or []
    return sorted(tiers, key=lambda t: Decimal(t["floor_eur"]), reverse=True)


def compute_avt_amount(eur_amount: Decimal, config: Dict[str, Any]) -> Decimal:
    """Apply tiered AVT-per-EUR rate. Returns AVT (whole units)."""
    eur = eur_amount.quantize(Decimal("0.01"))
    for tier in _sorted_tiers_desc(config):
        floor = Decimal(tier["floor_eur"])
        rate = Decimal(tier["avt_per_eur"])
        if eur >= floor:
            return (eur * rate).quantize(Decimal("1"), rounding=ROUND_DOWN)
    raise ValueError(f"EUR amount {eur} is below all tier floors")


def validate_eur_amount(eur_amount: Decimal, config: Dict[str, Any]) -> Decimal:
    """Clamp + validate. Raises ValueError on out-of-range. Returns 2-decimal Decimal."""
    eur = eur_amount.quantize(Decimal("0.01"))
    min_eur = Decimal(config.get("min_eur", "1.00"))
    max_eur = Decimal(config.get("max_eur", "500.00"))
    if eur < min_eur:
        raise ValueError(f"Minimum purchase is {config.get('currency', 'EUR')} {min_eur}")
    if eur > max_eur:
        raise ValueError(
            f"Maximum purchase is {config.get('currency', 'EUR')} {max_eur} (KYC threshold)"
        )
    return eur


def get_tier_label(eur_amount: Decimal, config: Dict[str, Any]) -> str:
    """Human-readable tier identifier for an EUR amount."""
    eur = eur_amount.quantize(Decimal("0.01"))
    for tier in _sorted_tiers_desc(config):
        if eur >= Decimal(tier["floor_eur"]):
            return tier["tier_label"]
    # Below the lowest floor — shouldn't happen post-validate, but be explicit.
    return "below_minimum"


# ---------------------------------------------------------------------------
# Config validation (used by admin PUT)
# ---------------------------------------------------------------------------

def validate_config(config: Dict[str, Any]) -> List[str]:
    """
    Returns a list of validation errors (empty list = valid).

    Run before persisting a new pricing config. Catches:
      • Missing keys
      • Empty / non-list tiers
      • Non-numeric or non-positive rates / floors
      • Tier floors not strictly increasing
      • Tier floors below min_eur or above max_eur
      • min_eur >= max_eur
      • Currency not in supported set
    """
    errors: List[str] = []

    if not isinstance(config, dict):
        return ["config must be a JSON object"]

    # min/max EUR
    try:
        min_eur = Decimal(config.get("min_eur", "1.00")).quantize(Decimal("0.01"))
    except Exception:
        errors.append("min_eur must be a decimal-string")
        return errors
    try:
        max_eur = Decimal(config.get("max_eur", "500.00")).quantize(Decimal("0.01"))
    except Exception:
        errors.append("max_eur must be a decimal-string")
        return errors
    if min_eur <= 0:
        errors.append(f"min_eur must be > 0 (got {min_eur})")
    if max_eur <= min_eur:
        errors.append(f"max_eur ({max_eur}) must be > min_eur ({min_eur})")
    if max_eur > Decimal("10000"):
        errors.append(f"max_eur {max_eur} exceeds prudential ceiling of 10000 (KYC review required for higher)")

    # currency
    supported = {"EUR"}  # extendable
    cur = config.get("currency", "EUR")
    if cur not in supported:
        errors.append(f"currency {cur!r} not supported (allowed: {sorted(supported)})")

    # tiers
    tiers = config.get("tiers")
    if not isinstance(tiers, list) or not tiers:
        errors.append("tiers must be a non-empty list")
        return errors

    seen_floors: List[Decimal] = []
    for i, t in enumerate(tiers):
        if not isinstance(t, dict):
            errors.append(f"tier[{i}] must be an object")
            continue
        for k in ("floor_eur", "avt_per_eur", "tier_label"):
            if k not in t:
                errors.append(f"tier[{i}] missing required field {k!r}")
        try:
            floor = Decimal(t["floor_eur"]).quantize(Decimal("0.01"))
        except Exception:
            errors.append(f"tier[{i}].floor_eur must be a decimal-string")
            continue
        try:
            rate = Decimal(t["avt_per_eur"])
        except Exception:
            errors.append(f"tier[{i}].avt_per_eur must be a decimal-string")
            continue
        if rate <= 0:
            errors.append(f"tier[{i}].avt_per_eur must be > 0 (got {rate})")
        if floor < min_eur:
            errors.append(f"tier[{i}].floor_eur {floor} is below min_eur {min_eur}")
        if floor > max_eur:
            errors.append(f"tier[{i}].floor_eur {floor} is above max_eur {max_eur}")
        seen_floors.append(floor)

    # Floors must be strictly increasing when sorted ascending (== unique).
    sorted_floors = sorted(seen_floors)
    for j in range(1, len(sorted_floors)):
        if sorted_floors[j] <= sorted_floors[j - 1]:
            errors.append(
                f"tier floors must be strictly increasing — duplicate or non-increasing at {sorted_floors[j]}"
            )
            break

    # Lowest floor should equal min_eur (otherwise min_eur..lowest_floor is unreachable).
    if seen_floors and min(seen_floors) != min_eur:
        errors.append(
            f"lowest tier floor ({min(seen_floors)}) must equal min_eur ({min_eur}) "
            f"or amounts in [min_eur, lowest_floor) would have no rate"
        )

    return errors


# ---------------------------------------------------------------------------
# Simulation engine — pure math, no DB writes
# ---------------------------------------------------------------------------

def simulate_purchases(
    *,
    config: Dict[str, Any],
    purchases_eur: List[Decimal],
    starting_treasury_avt: Decimal,
    starting_fee_collector_avt: Decimal,
    waterfall: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Pure-math what-if simulation of N fiat purchases against a pricing config.

    Models the reward-fund waterfall (default: fee_collector → treasury) on a
    fixed pool. No DB writes; safe to call repeatedly.

    Returns:
        {
          "summary": {
            "total_eur": "...", "total_avt_distributed": "...",
            "fee_collector_consumed": "...", "treasury_consumed": "...",
            "treasury_remaining": "...", "fee_collector_remaining": "...",
            "purchases_settled": N, "purchases_partial_or_failed": N,
            "exhaustion_at_purchase": Optional[int]
          },
          "tier_breakdown": [ { tier_label, count, total_eur, total_avt }, ... ],
          "warnings": [ "...", ... ]
        }

    The simulation honors the same waterfall semantics as
    teg_core_service/api/v1/endpoints_treasury.py:reward_fund:
      • Drain source 1 first; if amount remains, advance to source 2; etc.
      • Partial fund is recorded but does NOT abort the simulation — caller
        decides whether partials are acceptable.
    """
    waterfall = waterfall or ["fee_collector", "treasury"]
    pools = {
        "fee_collector": Decimal(starting_fee_collector_avt),
        "treasury": Decimal(starting_treasury_avt),
    }
    starting_pools = dict(pools)

    total_eur = Decimal("0")
    total_avt_distributed = Decimal("0")
    settled = 0
    partial = 0
    exhaustion_at: Optional[int] = None
    tier_counters: Dict[str, Dict[str, Decimal]] = {}
    warnings: List[str] = []

    min_eur = Decimal(config.get("min_eur", "1.00"))
    max_eur = Decimal(config.get("max_eur", "500.00"))

    for idx, eur_raw in enumerate(purchases_eur):
        try:
            eur = Decimal(eur_raw).quantize(Decimal("0.01"))
        except Exception:
            warnings.append(f"purchase[{idx}] non-numeric, skipped")
            continue
        if eur < min_eur:
            warnings.append(f"purchase[{idx}]={eur} below min_eur, skipped")
            continue
        if eur > max_eur:
            warnings.append(f"purchase[{idx}]={eur} above max_eur, skipped")
            continue

        try:
            avt_target = compute_avt_amount(eur, config)
        except Exception as exc:
            warnings.append(f"purchase[{idx}] tier resolution failed: {exc}")
            continue

        tier_label = get_tier_label(eur, config)

        # Drain waterfall
        remaining = avt_target
        funded = Decimal("0")
        for source in waterfall:
            if remaining <= 0:
                break
            avail = pools.get(source, Decimal("0"))
            if avail <= 0:
                continue
            drawn = min(avail, remaining)
            pools[source] = avail - drawn
            funded += drawn
            remaining -= drawn

        if remaining > 0 and funded > 0:
            partial += 1
            warnings.append(
                f"purchase[{idx}] partially funded: needed {avt_target}, got {funded}"
            )
            if exhaustion_at is None:
                exhaustion_at = idx
        elif funded == avt_target:
            settled += 1
        else:
            partial += 1
            warnings.append(f"purchase[{idx}] failed entirely (no source had funds)")
            if exhaustion_at is None:
                exhaustion_at = idx

        total_eur += eur
        total_avt_distributed += funded

        tc = tier_counters.setdefault(
            tier_label, {"count": Decimal("0"), "total_eur": Decimal("0"), "total_avt": Decimal("0")}
        )
        tc["count"] += 1
        tc["total_eur"] += eur
        tc["total_avt"] += funded

    return {
        "summary": {
            "total_eur": str(total_eur),
            "total_avt_distributed": str(total_avt_distributed),
            "fee_collector_consumed": str(starting_pools["fee_collector"] - pools["fee_collector"]),
            "treasury_consumed": str(starting_pools["treasury"] - pools["treasury"]),
            "fee_collector_remaining": str(pools["fee_collector"]),
            "treasury_remaining": str(pools["treasury"]),
            "purchases_settled": settled,
            "purchases_partial_or_failed": partial,
            "exhaustion_at_purchase": exhaustion_at,
            "waterfall": waterfall,
        },
        "tier_breakdown": [
            {
                "tier_label": label,
                "count": int(c["count"]),
                "total_eur": str(c["total_eur"]),
                "total_avt": str(c["total_avt"]),
            }
            for label, c in tier_counters.items()
        ],
        "warnings": warnings[:50],  # cap noise; partials past 50 are obvious anyway
    }


# ---------------------------------------------------------------------------
# Stripe SDK wrapper
# ---------------------------------------------------------------------------
#
# §DEPS stripe15 (2026-09-29): every function below hands its caller a PLAIN dict, never an SDK object. stripe-python
# 15.0 made StripeObject stop being a dict: no .get()/.items(), and dict(obj) raises TypeError, while every caller
# (the webhook normaliser, the admin drill-down, the proxy checkout, the provider) reads these results dict-style.
# .to_dict() is recursive on 15 (native dicts and lists all the way down) and shallow on 12 (whose nested values
# are dict subclasses), so the callers read the same shapes on both.

def _get_stripe():
    """Lazy import of stripe SDK; raises if FIAT_ONRAMP_ENABLED but SDK missing."""
    try:
        import stripe  # type: ignore
        return stripe
    except ImportError as exc:
        raise RuntimeError(
            "stripe SDK not installed. Add `stripe>=8.0.0` to Dockerfile and rebuild."
        ) from exc


def create_checkout_session(
    *,
    api_key: str,
    eur_amount: Decimal,
    avt_amount: Decimal,
    success_url: str,
    cancel_url: str,
    customer_email: Optional[str] = None,
    metadata: Optional[Dict[str, str]] = None,
    locale: str = "auto",
) -> Dict[str, Any]:
    """
    Create a Stripe Checkout Session in EUR.

    Returns the full session as a plain dict (id, url, payment_intent, etc.).
    Raises stripe.StripeError on API failure.

    Metadata travels with the session and is echoed back in the webhook —
    use it to thread our own correlation IDs (fiat_purchase_id, agent_did).
    """
    stripe = _get_stripe()
    stripe.api_key = api_key

    eur_cents = int((eur_amount * Decimal("100")).quantize(Decimal("1")))
    avt_int = int(avt_amount.quantize(Decimal("1"), rounding=ROUND_DOWN))
    tier_name = (metadata or {}).get("tier_display_name") or "Backer Tier"
    line_item_name = f"TheProtocol — {tier_name} (€{eur_amount} support · {avt_int:,} AVT bonus)"

    # Payment methods — let Stripe determine from the merchant dashboard.
    # When `payment_method_types` is omitted, Stripe Checkout shows ALL
    # methods activated under Settings → Payment methods for the merchant
    # account, filtered by buyer country/currency. This avoids hard-coding
    # methods that aren't activated (would 400 InvalidRequestError).
    # Operators activate Klarna / SEPA / Link / etc. in the Stripe dashboard.
    session_kwargs: Dict[str, Any] = {
        "mode": "payment",
        "line_items": [
            {
                "price_data": {
                    "currency": "eur",
                    "unit_amount": eur_cents,
                    "product_data": {
                        "name": line_item_name,
                        "description": (
                            "Become a TheProtocol Backer. Your contribution funds open-source "
                            "infrastructure for sovereign AI agents. As a thank-you you receive "
                            "AVT utility credits + supporter flare on your developer profile. "
                            "AVT is buy-only (no fiat redemption — MiCA-safe utility model)."
                        ),
                    },
                },
                "quantity": 1,
            }
        ],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "locale": locale,
        "metadata": metadata or {},
        "payment_intent_data": {"metadata": metadata or {}},
        # SEPA mandate requires billing address; collect in checkout (auto-displayed if needed)
        "billing_address_collection": "auto",
    }
    if customer_email:
        session_kwargs["customer_email"] = customer_email

    session = stripe.checkout.Session.create(**session_kwargs).to_dict()
    logger.info(
        "[fiat] Created Stripe Checkout Session id=%s url=%s eur=%s avt=%s",
        session.get("id"), session.get("url"), eur_amount, avt_amount,
    )
    return session


def verify_webhook_signature(
    *,
    payload: bytes,
    signature_header: str,
    webhook_secret: str,
) -> Dict[str, Any]:
    """
    Verify Stripe webhook signature and parse the event.

    Raises stripe.SignatureVerificationError on mismatch.
    Returns the parsed event as a plain dict.
    """
    stripe = _get_stripe()
    return stripe.Webhook.construct_event(
        payload=payload,
        sig_header=signature_header,
        secret=webhook_secret,
    ).to_dict()


def retrieve_session(*, api_key: str, session_id: str) -> Dict[str, Any]:
    """
    Fetch a Checkout Session by id. Used by admin drill-down + /my-purchases.

    The Stripe SDK is synchronous — callers in async context should wrap
    this in `asyncio.to_thread(...)` + `asyncio.wait_for(..., timeout=N)`
    so a slow Stripe API call doesn't tie up a uvicorn worker.
    """
    stripe = _get_stripe()
    stripe.api_key = api_key
    return stripe.checkout.Session.retrieve(session_id).to_dict()
