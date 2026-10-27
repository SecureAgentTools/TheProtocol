"""AGORA Solvency Card — signed per-registry solvency / float attestation (P4).

Companion to the Stock Card. Where the Stock Card publishes the slow-changing
CATALOG identity of each AGORA listing, the Solvency Card publishes a SIGNED,
FRESH attestation over the live invariants: that the float is real (I-X1), that
each org treasury can back its obligations (declared-unpaid dividends + open
treasury buyback escrow + MM cash floor), that a declared dividend is covered,
and the venue-global escrow invariant (I-X3/I-X4/I-X5 + delta).

Design (SPEC_2026-06-22_AGORA_P2.2_P4_P5_DESIGN.md §PHASE 4):
  - Near-verbatim clone of stock_card_builder.py. Reuses the SAME EdDSA keystore
    as the registry card → get_or_mint_signing_key + sign_with_keypair; consumers
    verify with the SAME /.well-known/registry-jwks.json. No new key material.
  - The signed canonical = {registry_spiffe_id, currency, digest} — `digest`
    commits to the full per-listing + venue-global solvency payload, so signing
    those three binds identity + frame currency + the attested content.
  - Built ON-SERVE so it is never stale at read. UNLIKE the catalog digest (which
    is invariant under trading), the solvency digest CHANGES on every balance
    move — so the well-known card serves live (its own ETag = full digest, short
    max-age) but the federated registry-card link must fold only a COARSE epoch
    (handled by the card builder, not here) to avoid OWL24-style churn.

Δ-irrelevant: pure read-of-state + sign. Reads compute_invariants (the auditor's
own function) + treasury balances via the mover's read-only agent_balance. Moves
no money, mutates no share/order/balance row, runs no migration. A forged
solvency card cannot move money (trading still settles via escrow + signed
DevCard + passport — the stock-card threat model).

NB: do NOT add `from __future__ import annotations` here — mirrors the
registry_card_builder/serve_well_known_card convention (this module is imported
by a FastAPI route module; stringified annotations leak into schema gen).
"""
import asyncio
import datetime
import hashlib
import json
import logging
import os
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models

logger = logging.getLogger(__name__)

SOLVENCY_CARD_VERSION = "0.1"

# The signed canonical paths. `digest` commits to the entire solvency payload, so
# signing {registry_spiffe_id, currency, digest} binds identity + frame currency
# + the full attested content. `as_of`/`count`/`listings`/`venue` are excluded
# from the signature (digest already covers them; as_of is volatile).
SOLVENCY_CARD_SIGNED_PATHS = ["registry_spiffe_id", "currency", "digest"]

_ZERO = Decimal("0")


def _canonical_bytes(payload: Any) -> bytes:
    """Deterministic bytes — identical convention to registry_card_signer_impl
    (sort_keys + tight separators) so digests/signatures are reproducible."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def exchange_enabled() -> bool:
    return (os.getenv("EXCHANGE_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes", "on")


async def _open_buyback_escrow(db: AsyncSession, listing_id: str, treasury_did: str) -> Decimal:
    """Σ live escrow still held by the treasury's own OPEN/PARTIAL buy orders
    (treasury buybacks ride place_order as a keyless-treasury BUY — exchange_service
    treasury_buyback:709). Held money = escrow_amount - matched_notional -
    escrow_refunded for orders that actually deposited (mirrors the I-X3 buy-hold
    expression, exchange_service:2318-2339)."""
    val = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(
                        models.ExchangeOrder.escrow_amount
                        - models.ExchangeOrder.matched_notional
                        - models.ExchangeOrder.escrow_refunded
                    ),
                    0,
                )
            ).where(
                models.ExchangeOrder.listing_id == listing_id,
                models.ExchangeOrder.agent_did == treasury_did,
                models.ExchangeOrder.side == "buy",
                models.ExchangeOrder.escrow_amount > 0,
                models.ExchangeOrder.status.notin_(("rejected", "funding")),
            )
        )
    ).scalar_one()
    return Decimal(val or 0)


async def _unpaid_dividend_legs(db: AsyncSession, listing_id: str) -> Decimal:
    """Σ pending dividend legs for FUNDED dividends of this listing (the I-X3
    component, exchange_service:2354-2361 — restricted here to one listing)."""
    val = (
        await db.execute(
            select(func.coalesce(func.sum(models.ExchangeDividendLeg.amount), 0))
            .select_from(models.ExchangeDividendLeg)
            .join(models.ExchangeDividend, models.ExchangeDividend.id == models.ExchangeDividendLeg.dividend_id)
            .where(
                models.ExchangeDividend.listing_id == listing_id,
                models.ExchangeDividendLeg.status == "pending",
                models.ExchangeDividend.pot_funded.is_(True),
            )
        )
    ).scalar_one()
    return Decimal(val or 0)


async def _unfunded_declared_dividends(db: AsyncSession, listing_id: str) -> Decimal:
    """Σ remaining UNFUNDED liability — dividends declared but whose pot has NOT
    yet been moved treasury→escrow (pot_funded=False, not yet paid). This is the
    real forward liability the treasury must still fund FROM its liquid balance,
    so it MUST count against `treasury_balance` (audit H2: previously excluded —
    `_unpaid_dividend_legs` only counts pot_funded=True legs, whose money has
    already left the treasury into escrow). Funded vs unfunded are disjoint, so
    summing both does not double-count."""
    val = (
        await db.execute(
            select(func.coalesce(func.sum(models.ExchangeDividend.total_amount), 0)).where(
                models.ExchangeDividend.listing_id == listing_id,
                models.ExchangeDividend.pot_funded.is_(False),
                models.ExchangeDividend.status != "paid",
            )
        )
    ).scalar_one()
    return Decimal(val or 0)


async def _mm_cash_floor(db: AsyncSession, listing_id: str) -> Decimal:
    """The treasury market-maker cash floor — money the MM keeps un-bid-below
    (TreasuryMMConfig.cash_floor, models.py:5162). 0 when no MM row / disabled."""
    val = (
        await db.execute(
            select(models.TreasuryMMConfig.cash_floor).where(
                models.TreasuryMMConfig.listing_id == listing_id
            )
        )
    ).scalar_one_or_none()
    return Decimal(val or 0)


async def _latest_unpaid_dividend(db: AsyncSession, listing_id: str) -> Optional[models.ExchangeDividend]:
    """The most-recently-declared dividend that is not yet fully paid."""
    return (
        await db.execute(
            select(models.ExchangeDividend)
            .where(
                models.ExchangeDividend.listing_id == listing_id,
                models.ExchangeDividend.status != "paid",
            )
            .order_by(models.ExchangeDividend.epoch.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _dividend_pending_sum(db: AsyncSession, dividend_id: str) -> Decimal:
    val = (
        await db.execute(
            select(func.coalesce(func.sum(models.ExchangeDividendLeg.amount), 0)).where(
                models.ExchangeDividendLeg.dividend_id == dividend_id,
                models.ExchangeDividendLeg.status == "pending",
            )
        )
    ).scalar_one()
    return Decimal(val or 0)


async def _build_listings_payload(db: AsyncSession) -> List[Dict[str, Any]]:
    """Per-listing solvency block, sorted by symbol for a deterministic digest.

    Uses compute_invariants for I-X1/positions/expected (the auditor's own
    numbers), then reads treasury balance + obligations. Every obligation
    component is best-effort: a failed read defaults that component to 0 and adds
    a note — it NEVER throws (the serve must not fail on a transient mover/DB
    blip)."""
    from .exchange_service import compute_invariants, mover

    # Auditor's own per-listing I-X1 + positions/expected, keyed by symbol.
    inv: Dict[str, Any] = {}
    try:
        inv = await compute_invariants(db)
    except Exception as e:  # pragma: no cover — never fail the serve
        logger.warning("[SolvencyCardBuilder] compute_invariants failed: %s", e)
        inv = {}
    ix1_by_symbol: Dict[str, Dict[str, Any]] = {
        li.get("symbol"): li for li in (inv.get("listings") or []) if li.get("symbol")
    }

    rows = (
        await db.execute(
            select(models.ExchangeListing).where(
                models.ExchangeListing.approved.is_(True),
                models.ExchangeListing.status != "delisted",
            )
        )
    ).scalars().all()

    listings: List[Dict[str, Any]] = []
    for l in rows:
        notes: List[str] = []
        li = ix1_by_symbol.get(l.symbol) or {}

        float_integrity = {
            "ix1": bool(li.get("I-X1_share_conservation")) if li else None,
            "positions_sum": int(li["positions_sum"]) if li.get("positions_sum") is not None else None,
            "expected_shares": int(li["expected"]) if li.get("expected") is not None else None,
        }
        if not li:
            notes.append("float_integrity_unavailable")

        # treasury balance (read-only mover call) — best-effort.
        treasury_balance = _ZERO
        treasury_balance_known = False
        try:
            treasury_balance = await mover.agent_balance(l.treasury_agent_did)
            treasury_balance_known = True
        except Exception as e:
            notes.append("treasury_balance_unavailable")
            logger.debug("[SolvencyCard] treasury balance read failed for %s: %s", l.symbol, e)

        # obligation components — each defaults to 0 with a note on failure.
        # AUDIT H1: track completeness. If ANY component read fails the obligation
        # SUM is understated, so `backed` must be UNKNOWN (None) — NOT computed
        # against a partial sum (which silently yields a false `backed:true`).
        obligations_complete = True
        try:
            div_obl = await _unpaid_dividend_legs(db, l.id)
        except Exception as e:
            div_obl = _ZERO; obligations_complete = False
            notes.append("dividend_obligation_unavailable")
            logger.debug("[SolvencyCard] dividend obligation read failed for %s: %s", l.symbol, e)
        try:
            unfunded_div = await _unfunded_declared_dividends(db, l.id)  # AUDIT H2
        except Exception as e:
            unfunded_div = _ZERO; obligations_complete = False
            notes.append("unfunded_dividend_obligation_unavailable")
            logger.debug("[SolvencyCard] unfunded dividend read failed for %s: %s", l.symbol, e)
        try:
            buyback_obl = await _open_buyback_escrow(db, l.id, l.treasury_agent_did)
        except Exception as e:
            buyback_obl = _ZERO; obligations_complete = False
            notes.append("buyback_obligation_unavailable")
            logger.debug("[SolvencyCard] buyback obligation read failed for %s: %s", l.symbol, e)
        try:
            mm_floor = await _mm_cash_floor(db, l.id)
        except Exception as e:
            mm_floor = _ZERO; obligations_complete = False
            notes.append("mm_cash_floor_unavailable")
            logger.debug("[SolvencyCard] MM cash floor read failed for %s: %s", l.symbol, e)

        # AUDIT H2: unfunded declared dividends are a forward liability against the
        # LIQUID treasury balance, so they count toward obligations.
        obligations = div_obl + unfunded_div + buyback_obl + mm_floor
        # backed only meaningful when we read the treasury balance AND every
        # obligation component succeeded (AUDIT H1).
        backed = (
            (treasury_balance >= obligations)
            if (treasury_balance_known and obligations_complete)
            else None
        )

        treasury_solvency = {
            "treasury_did": l.treasury_agent_did,
            "treasury_balance": str(treasury_balance) if treasury_balance_known else None,
            "obligations": str(obligations),
            "obligations_complete": obligations_complete,
            "obligation_breakdown": {
                "unpaid_dividend_legs": str(div_obl),
                "unfunded_declared_dividends": str(unfunded_div),
                "open_buyback_escrow": str(buyback_obl),
                "mm_cash_floor": str(mm_floor),
            },
            "backed": backed,
        }

        # dividend_coverage — latest declared-but-unpaid dividend, best-effort.
        dividend_coverage: Dict[str, Any] = {"has_unpaid": False}
        try:
            div = await _latest_unpaid_dividend(db, l.id)
            if div is not None:
                pending_sum = await _dividend_pending_sum(db, div.id)
                dividend_coverage = {
                    "has_unpaid": True,
                    "dividend_id": div.id,
                    "epoch": int(div.epoch),
                    "status": div.status,
                    "pot_funded": bool(div.pot_funded),
                    "total_amount": str(div.total_amount),
                    "pending_legs_sum": str(pending_sum),
                    # escrow holds the pending legs once the pot is funded (I-X3
                    # component); covered = the pot is funded for what remains.
                    "covered": bool(div.pot_funded) if pending_sum > _ZERO else True,
                }
        except Exception as e:
            dividend_coverage = {"has_unpaid": None, "error": "dividend_coverage_unavailable"}
            notes.append("dividend_coverage_unavailable")
            logger.debug("[SolvencyCard] dividend coverage read failed for %s: %s", l.symbol, e)

        listings.append({
            "symbol":            l.symbol,
            "organization_id":   l.organization_id,
            "currency":          l.currency,
            "status":            l.status,
            "float_integrity":   float_integrity,
            "treasury_solvency": treasury_solvency,
            "dividend_coverage": dividend_coverage,
            "notes":             notes,
        })

    listings.sort(key=lambda c: (c.get("symbol") or ""))
    return listings


def _venue_global(inv: Dict[str, Any]) -> Dict[str, Any]:
    """The venue-wide escrow invariant (I-X3/I-X4/I-X5 + delta) lifted straight
    from compute_invariants. All values already str/bool there."""
    ix3 = inv.get("I-X3_escrow") or {}
    ix4 = inv.get("I-X4_settlement_liveness") or {}
    ix5 = inv.get("I-X5_gateway_solvency") or {}
    return {
        "ix3": bool(ix3.get("ok")) if "ok" in ix3 else None,
        "ix4": bool(ix4.get("ok")) if "ok" in ix4 else None,
        "ix5": bool(ix5.get("ok")) if "ok" in ix5 else None,
        "delta": ix3.get("delta"),
        "ok": bool(inv.get("ok")) if "ok" in inv else None,
    }


async def _payload_for_digest(db: AsyncSession) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Optional[str]]:
    """(listings, venue_global, as_of) — the content the digest commits to.

    Runs compute_invariants ONCE for both the per-listing I-X1 (inside
    _build_listings_payload) and the venue-global block; checked_at → as_of."""
    from .exchange_service import compute_invariants

    listings = await _build_listings_payload(db)
    inv: Dict[str, Any] = {}
    try:
        inv = await compute_invariants(db)
        # §2026-06-22 transient escrow read-skew guard (Commander-reported "I-X3 red"):
        # compute_invariants reads escrow-held vs Σ open-order notionals NON-ATOMICALLY, so
        # on a busy venue a read can land mid-deposit/mid-settle → a MOMENTARY I-X3 false that
        # clears on the very next read (the atomic single-statement delta is the truth=0 —
        # CLAUDE.md PART 4). This card is an external CREDIBILITY signal, so a transient red
        # falsely reads as insolvency. Re-check ONCE before publishing a red: a transient
        # clears, a genuine drift persists. Cheap (only on the rare false), still read-only.
        if (inv.get("I-X3_escrow") or {}).get("ok") is False:
            await asyncio.sleep(0.15)
            inv = await compute_invariants(db)
    except Exception as e:  # pragma: no cover — never fail the serve
        logger.warning("[SolvencyCardBuilder] compute_invariants (venue) failed: %s", e)
        inv = {}
    venue = _venue_global(inv)
    as_of = inv.get("checked_at")
    return listings, venue, as_of


def _digest(listings: List[Dict[str, Any]], venue: Dict[str, Any]) -> str:
    """Commit to the full attested content (per-listing solvency + venue-global).
    Excludes `as_of` (volatile timestamp) so the digest changes on a substantive
    solvency move, not merely on the clock."""
    return "sha256:" + hashlib.sha256(_canonical_bytes({"listings": listings, "venue": venue})).hexdigest()


async def solvency_digest_and_count(db: AsyncSession) -> Tuple[str, int]:
    """(digest, count) for the cheap 304 / ETag fold + the (coarse) registry-card
    link. Builds the full solvency payload — the digest MUST reflect live state,
    so unlike the catalog there is no cheaper short-cut. Only called when
    EXCHANGE_ENABLED + the solvency-card flag, so non-venue registries never pay
    for it."""
    listings, venue, _as_of = await _payload_for_digest(db)
    return _digest(listings, venue), len(listings)


def extract_solvency_canonical(card: Dict[str, Any]) -> Dict[str, Any]:
    """Pull only the signed paths, in deterministic order (mirrors
    registry_card_signer.extract_canonical_payload)."""
    return {p: card.get(p) for p in SOLVENCY_CARD_SIGNED_PATHS}


async def build_solvency_card(db: AsyncSession, *, sign: bool = True) -> Dict[str, Any]:
    """Compose (and EdDSA-sign) this registry's solvency card."""
    # Local imports: avoid an import cycle (registry_card_builder may import this
    # module's digest helpers for the P4 link/ETag).
    from .registry_card_builder import _build_spiffe_id, _frame_currency

    listings, venue, as_of = await _payload_for_digest(db)
    digest = _digest(listings, venue)
    spiffe_id = _build_spiffe_id()
    currency = _frame_currency()

    card: Dict[str, Any] = {
        "solvency_card_version": SOLVENCY_CARD_VERSION,
        "registry_spiffe_id":    spiffe_id,
        "currency":              currency,
        "count":                 len(listings),
        "digest":                digest,
        "as_of":                 as_of,
        "freshness":             "live",  # the well-known card always serves live; the federated link is coarse-epoch
        "updated_at":            datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "venue":                 venue,
        "listings":              listings,
    }

    if sign:
        try:
            from .registry_card_keystore import get_or_mint_signing_key
            from .registry_card_signer_impl import sign_with_keypair
            key_row = await get_or_mint_signing_key(db, spiffe_id)
            value = sign_with_keypair(extract_solvency_canonical(card), key_row)
            card["signature"] = {
                "alg":              "EdDSA",
                "kid":              f"{spiffe_id}#{key_row.rotation_seq}",
                "jwks_url":         "/.well-known/registry-jwks.json",
                "signed_canonical": SOLVENCY_CARD_SIGNED_PATHS,
                "value":            value,
            }
        except Exception as e:  # pragma: no cover — never fail the serve on sign error
            logger.warning("[SolvencyCardBuilder] sign failed: %s", e)
            card["signature"] = None

    return card


__all__ = [
    "SOLVENCY_CARD_VERSION",
    "SOLVENCY_CARD_SIGNED_PATHS",
    "exchange_enabled",
    "solvency_digest_and_count",
    "extract_solvency_canonical",
    "build_solvency_card",
]
