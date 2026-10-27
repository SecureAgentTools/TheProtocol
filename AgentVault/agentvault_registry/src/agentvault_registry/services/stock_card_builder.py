"""Federated Stock Card — signed per-registry AGORA listing catalog.

Companion to the Registry Card. Publishes THIS registry's AGORA listing
CATALOG (slow-changing identity of each stock) as a small EdDSA-signed JSON
doc, so the catalog can federate network-wide while live prices stay local.

Design (STRATEGY_2026-06-17_FEDERATED_STOCK_CARDS.md §3):
  - CATALOG ONLY (symbol/display_name/organization_id/total_shares/ipo_price/
    fee_bps/status/created_at). Live data (last/bid/ask/volume/ipo_sold) is
    DELIBERATELY EXCLUDED so the `digest` changes only on add/delist/rename/
    price-of-record/fee change — never on a live tick (the OWL24 churn lesson).
  - `digest` = sha256 over the canonical catalog → tamper-evidence anchor +
    cache-invalidation lever (also folded into the registry card ETag, P2).
  - SIGNED by the SAME EdDSA keystore as the registry card → reuse
    get_or_mint_signing_key + sign_with_keypair; consumers verify with the
    SAME verify_with_jwk against the registry's existing /.well-known/
    registry-jwks.json. No new key material, no new transport.

Δ-irrelevant: read-only metadata. Trading still settles via passport + escrow
+ signed DevCard, so a forged catalog cannot move money.

NB: do NOT add `from __future__ import annotations` here — mirrors the
registry_card_builder/serve_well_known_card convention (this module is imported
by a FastAPI route module; stringified annotations leak into schema gen).
"""
import datetime
import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models

logger = logging.getLogger(__name__)

STOCK_CARD_VERSION = "0.1"

# The signed canonical paths. `digest` commits to the entire catalog, so signing
# {registry_spiffe_id, currency, digest} binds identity + frame currency + the
# full catalog content. `updated_at`/`count`/`listings` are excluded from the
# signature (digest already covers the catalog; updated_at is volatile).
# AUDIT M2 — `market_digest` added so the EdDSA signature now COMMITS to the
# market block (last/change_24h/spark). It is built (line ~206) BEFORE signing
# (line ~215) so it is always present when present; absent market → None, signed
# consistently. Binding the digest stops a free swap; consumers ALSO recompute
# market_digest == sha256(market) via verify_market_block() to catch a tampered
# market block whose digest wasn't updated.
STOCK_CARD_SIGNED_PATHS = ["registry_spiffe_id", "currency", "digest", "market_digest"]


def _canonical_bytes(payload: Any) -> bytes:
    """Deterministic bytes — identical convention to registry_card_signer_impl
    (sort_keys + tight separators) so digests/signatures are reproducible."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def exchange_enabled() -> bool:
    return (os.getenv("EXCHANGE_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes", "on")


# ─────────────────────────────────────────────────────────────────────────────
# §2026-06-25 FEDERATED MARKET CARD — a COARSE per-symbol price/sparkline block
# carried ON the stock card (the rail that already auto-discovers every venue,
# mainframe + op, with no manual probe list and no inbound reachability). Each
# venue self-publishes its OWN sparkline from its OWN local trades. ADVISORY:
# NOT folded into the signed catalog `digest` (cosmetic — a forged sparkline
# cannot move money; trading settles via passport+escrow+signed DevCard), and
# the catalog signature is unchanged so older consumers keep verifying. Churn is
# bounded by a COARSE market_epoch folded into the registry-card ETag (NEVER the
# live digest) — see registry_card_builder (the V0125 solvency-epoch precedent).
# ─────────────────────────────────────────────────────────────────────────────
MARKET_EPOCH_SECONDS = int(os.getenv("EXCHANGE_MARKET_EPOCH_SECONDS", "900") or "900")
_MARKET_TTL = 45.0
_MARKET_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None, "digest": None}


def market_enabled() -> bool:
    """Gate for the market block. OFF → the card is byte-identical to the
    catalog-only form. Requires EXCHANGE_ENABLED (only venues publish prices)."""
    return exchange_enabled() and \
        (os.getenv("EXCHANGE_MARKET_CARD_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes", "on")


def market_epoch(now: Optional[float] = None) -> int:
    """Coarse epoch for ETag folding — floor(now / MARKET_EPOCH_SECONDS). The
    registry-card ETag folds THIS (not the live market digest) so peers re-pull
    at most ~3600/EPOCH times/hr regardless of trade volume (no OWL24 storm)."""
    return int((now if now is not None else time.time()) // MARKET_EPOCH_SECONDS)


def market_digest(market: Dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(market)).hexdigest()


async def build_market_block(db: AsyncSession) -> Dict[str, Any]:
    """COARSE per-symbol snapshot {SYMBOL: {last, change_24h_pct, spark[≤24], as_of}}
    over the approved catalog, built from the SAME helpers the Desk uses. Cached
    per-worker (_MARKET_TTL) so it never lands on the cheap-304 path; one bad
    listing is skipped, never sinks the block."""
    now = time.time()
    cached = _MARKET_CACHE.get("data")
    if cached is not None and (now - float(_MARKET_CACHE.get("ts") or 0)) < _MARKET_TTL:
        return cached
    from . import exchange_service as svc  # local import — avoid heavy/cyclic import at module load
    rows = (await db.execute(
        select(models.ExchangeListing).where(
            models.ExchangeListing.approved.is_(True),
            models.ExchangeListing.status != "delisted",
        )
    )).scalars().all()
    as_of = datetime.datetime.now(datetime.timezone.utc).isoformat()
    market: Dict[str, Any] = {}
    for l in rows:
        try:
            st = await svc.listing_stats(db, l)
            cs = await svc.candles(db, l, tf="1h", limit=24)
            spark = [float(k["c"]) for k in (cs or []) if k.get("c") is not None][-24:]
            market[l.symbol] = {
                "last":           (str(st.get("last")) if st.get("last") is not None else None),
                "change_24h_pct": (str(st.get("change_24h_pct")) if st.get("change_24h_pct") is not None else None),
                "spark":          spark,
                "as_of":          as_of,
            }
        except Exception as e:  # one bad listing never sinks the whole block
            logger.debug("[StockCardBuilder] market skip %s: %s", getattr(l, "symbol", "?"), e)
    _MARKET_CACHE.update({"ts": now, "data": market, "digest": market_digest(market)})
    return market


def _catalog_from_rows(rows: List[models.ExchangeListing]) -> List[Dict[str, Any]]:
    """Stable catalog subset, sorted by symbol for a deterministic digest.

    EXCLUDES every live/volatile field (ipo_sold, updated_at, tick, band, stats)
    so the digest is invariant under trading."""
    catalog: List[Dict[str, Any]] = []
    for l in rows:
        catalog.append({
            "symbol":          l.symbol,
            "display_name":    l.display_name,
            "organization_id": l.organization_id,
            "currency":        l.currency,
            "total_shares":    l.total_shares,
            "ipo_price":       str(l.ipo_price),
            "fee_bps":         l.fee_bps,
            "status":          l.status,
            "created_at":      l.created_at.isoformat() if l.created_at else None,
        })
    catalog.sort(key=lambda c: (c.get("symbol") or ""))
    return catalog


async def get_stock_catalog(db: AsyncSession) -> List[Dict[str, Any]]:
    """The publishable catalog: approved, non-delisted listings."""
    rows = (await db.execute(
        select(models.ExchangeListing).where(
            models.ExchangeListing.approved.is_(True),
            models.ExchangeListing.status != "delisted",
        )
    )).scalars().all()
    return _catalog_from_rows(list(rows))


def catalog_digest(catalog: List[Dict[str, Any]]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(catalog)).hexdigest()


async def stock_card_digest_and_count(db: AsyncSession) -> Tuple[str, int]:
    """(digest, count) for the registry-card link + the ETag fingerprint.

    Cheap: a single small SELECT of the catalog columns. Only called when
    EXCHANGE_ENABLED, so non-venue registries never pay for it."""
    catalog = await get_stock_catalog(db)
    return catalog_digest(catalog), len(catalog)


def verify_market_block(card: Dict[str, Any]) -> bool:
    """AUDIT M2 — True iff the card's market block matches its signed
    `market_digest` (or there is no market block). Consumers call this AFTER the
    EdDSA verify so a tampered market block (prices / sparkline) is rejected even
    when the catalog signature is intact: signing market_digest binds the digest,
    this recompute binds the digest to the actual market content."""
    mkt = card.get("market")
    md = card.get("market_digest")
    if mkt is None and md is None:
        return True
    if md is None:
        return False
    try:
        return market_digest(mkt) == md
    except Exception:
        return False


def extract_stock_canonical(card: Dict[str, Any]) -> Dict[str, Any]:
    """Pull only the signed paths, in deterministic order (mirrors
    registry_card_signer.extract_canonical_payload)."""
    return {p: card.get(p) for p in STOCK_CARD_SIGNED_PATHS}


async def build_stock_card(db: AsyncSession, *, sign: bool = True) -> Dict[str, Any]:
    """Compose (and EdDSA-sign) this registry's stock card."""
    # Local imports: registry_card_builder must be free to import THIS module for
    # the P2 link/ETag without a cycle (it imports our digest helpers locally too).
    from .registry_card_builder import _build_spiffe_id, _frame_currency

    catalog = await get_stock_catalog(db)
    digest = catalog_digest(catalog)
    spiffe_id = _build_spiffe_id()
    currency = _frame_currency()

    card: Dict[str, Any] = {
        "stock_card_version": STOCK_CARD_VERSION,
        "registry_spiffe_id": spiffe_id,
        "currency":           currency,
        "count":              len(catalog),
        "digest":             digest,
        "updated_at":         datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "listings":           catalog,
    }

    if market_enabled():
        try:
            mkt = await build_market_block(db)
            card["market"] = mkt
            card["market_digest"] = market_digest(mkt)
        except Exception as e:  # market is advisory — never fail the card serve on it
            logger.warning("[StockCardBuilder] market block failed: %s", e)

    if sign:
        try:
            from .registry_card_keystore import get_or_mint_signing_key
            from .registry_card_signer_impl import sign_with_keypair
            key_row = await get_or_mint_signing_key(db, spiffe_id)
            value = sign_with_keypair(extract_stock_canonical(card), key_row)
            card["signature"] = {
                "alg":              "EdDSA",
                "kid":              f"{spiffe_id}#{key_row.rotation_seq}",
                "jwks_url":         "/.well-known/registry-jwks.json",
                "signed_canonical": STOCK_CARD_SIGNED_PATHS,
                "value":            value,
            }
        except Exception as e:  # pragma: no cover — never fail the serve on sign error
            logger.warning("[StockCardBuilder] sign failed: %s", e)
            card["signature"] = None

    return card


__all__ = [
    "STOCK_CARD_VERSION",
    "STOCK_CARD_SIGNED_PATHS",
    "exchange_enabled",
    "get_stock_catalog",
    "catalog_digest",
    "stock_card_digest_and_count",
    "extract_stock_canonical",
    "build_stock_card",
    "MARKET_EPOCH_SECONDS",
    "market_enabled",
    "market_epoch",
    "market_digest",
    "build_market_block",
]
