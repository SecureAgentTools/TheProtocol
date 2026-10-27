"""
AGORA — organization stock exchange: REST surface (2026-06-12).

Contract: sessionlogs2026/STRATEGY_2026-06-12_AGORA_LOCKED_IMPLEMENTATION.md.
All money mechanics live in services/exchange_service.py; this router is a thin
auth + validation + idempotency shell. Tag 'exchange' is load-bearing: the
api-tester auto-builds its catalog from OpenAPI tags.

Auth tiers:
  public        : listings / stats / book / trades / candles / top-traders
  agent JWT     : orders (place/cancel/mine), IPO buy, portfolio
  developer JWT : create listing (org OWNER), declare dividend (org admin)
  admin         : approve / halt / resume / delist / global-halt / invariant
"""
import logging
import os
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Security
from pydantic import BaseModel, Field
from sqlalchemy import select, text  # text: IRONKEY ipo price lookup
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.database import get_db
from agentvault_registry.models import Agent, Developer, ExchangeListing
from agentvault_registry.security import get_current_agent, get_current_developer, require_admin_flag, require_agent_permission, enforce_agent_spend
from agentvault_registry.services import exchange_service as svc
from agentvault_registry.services.idempotency import idempotency_lookup, idempotency_store
from agentvault_registry.services.idempotency.cache import agent_caller, developer_caller  # D6-777

logger = logging.getLogger(__name__)
# §RATEFIX: THE shared, Redis-backed limiter — the same object main.py puts on
# app.state, so these decorations are both enforced and shared across workers.
# A router-local Limiter() would be in-memory per worker AND invisible to the
# middleware; that is what made all 65 limits here meaningless.
from agentvault_registry.middleware.rate_limiter import shared_limiter as limiter

# §AGORAWORDS (V0419): no prefix here. main.py mounts this router TWICE: at /api/v1/agora (the documented
# names, in the OpenAPI schema) and at /api/v1/exchange (the old names, kept live and hidden from the schema,
# because a roll mixes versions and cross-frame callers keep the old paths until every frame runs V0419+).
# §AGORAWORDS Phase 5: a peer venue is read under /api/v1/agora first (core/agora_paths.py)
from ..core.agora_paths import peer_request  # noqa: E402

router = APIRouter(tags=["exchange"])


def _err(e: svc.ExchangeError) -> HTTPException:
    # §LEDGERGATE (V0598): the TEG's Retry-After rides along when its ledger refused
    return HTTPException(status_code=e.status_code, detail=e.detail, headers=getattr(e, "headers", None))


def _dec(v: str, name: str) -> Decimal:
    try:
        d = Decimal(str(v))
    except (InvalidOperation, TypeError):
        raise HTTPException(status_code=422, detail=f"{name} must be a decimal string")
    return d


def _listing_public(l: ExchangeListing, stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = {
        "id": l.id,
        "symbol": l.symbol,
        "display_name": l.display_name,
        "organization_id": l.organization_id,
        "currency": l.currency,
        "total_shares": l.total_shares,
        "ipo_price": str(l.ipo_price),
        "ipo_float": l.ipo_float,
        "ipo_sold": l.ipo_sold,
        "fee_bps": l.fee_bps,
        "tick": str(l.tick),
        "band_pct": l.band_pct,
        "approved": l.approved,
        "status": l.status,
        "cb_pct": l.cb_pct,  # §#84 circuit-breaker threshold (bps; 0 = off)
        "cb_halted_until": l.cb_halted_until.isoformat() if l.cb_halted_until else None,
        "treasury_agent_did": l.treasury_agent_did,
        "created_at": l.created_at.isoformat() if l.created_at else None,
    }
    if stats is not None:
        out["stats"] = stats
    return out


# ── schemas ───────────────────────────────────────────────────────────────
class CreateListingRequest(BaseModel):
    organization_id: str = Field(..., max_length=255)
    symbol: str = Field(..., min_length=2, max_length=6, pattern=r"^[A-Z0-9]{2,6}$")
    total_shares: int = Field(..., gt=0, le=1_000_000_000_000)
    ipo_float: int = Field(..., ge=0)
    ipo_price: str = Field(..., description="decimal string, frame currency per share")
    funding_agent_did: str = Field(..., max_length=120, description="your agent that pays the listing fee")
    display_name: Optional[str] = Field(default=None, max_length=255)


class PlaceOrderRequest(BaseModel):
    listing: str = Field(..., description="listing id or symbol")
    side: str = Field(..., pattern="^(buy|sell)$")
    order_type: str = Field("limit", pattern="^(limit|market)$")
    qty: int = Field(..., gt=0)
    price: Optional[str] = Field(default=None, description="decimal string (required for limit)")
    client_order_id: Optional[str] = Field(default=None, max_length=64)
    ttl_seconds: Optional[int] = Field(default=None, ge=10, le=7 * 86400)
    # §2026-06-22 P5.1 advanced order types (opt-in; defaults = today's behavior).
    # tif: gtc (rest, default) | ioc (match then cancel remainder) | fok (all-or-nothing,
    # reject pre-escrow if not fully fillable). post_only: reject if a limit would cross
    # the best opposite (forces pure maker — pairs with the P2.2 maker rebate).
    tif: str = Field("gtc", pattern="^(gtc|ioc|fok)$")
    post_only: bool = Field(False)
    # §#86 P5.1 stop / stop-limit: stop_price set ⇒ the order rests 'armed' until `last` crosses it,
    # then activates as a market (price omitted) or limit (price set = stop-limit) order. The far-side
    # rule applies (buy-stop ABOVE last, sell-stop BELOW). Δ-neutral while armed (escrow at trigger).
    stop_price: Optional[str] = Field(default=None, description="decimal string; arms a stop/stop-limit order")


class IpoBuyRequest(BaseModel):
    qty: int = Field(..., gt=0)


class DeclareDividendRequest(BaseModel):
    per_share: str = Field(..., description="decimal string per share")


class TreasuryBuybackRequest(BaseModel):
    qty: int = Field(..., gt=0)
    limit_price: str = Field(..., description="decimal string, limit price per share")


class TreasuryTransferRequest(BaseModel):
    dest_did: str = Field(..., max_length=120)
    amount: str = Field(..., description="decimal string")
    reserve_floor: Optional[str] = Field(default=None, description="decimal string; treasury never drains below this")


class TreasurySweepRequest(BaseModel):
    to_symbol: str = Field(..., min_length=2, max_length=6, pattern=r"^[A-Z0-9]{2,6}$")
    amount: str = Field(..., description="decimal string")


class TreasuryRefloatRequest(BaseModel):
    qty: int = Field(..., gt=0, description="shares to release from treasury into the buyable float")
    offer_price: Optional[str] = Field(default=None, description="decimal string; default = current market last")
    min_retained: Optional[int] = Field(default=0, ge=0, description="never re-float treasury below this")


class TreasurySellRequest(BaseModel):
    qty: int = Field(..., gt=0)
    order_type: str = Field(default="limit", pattern=r"^(limit|market)$")
    limit_price: Optional[str] = Field(default=None, description="decimal string (required for limit)")
    min_retained: Optional[int] = Field(default=0, ge=0, description="never sell treasury below this")


class TreasuryMMConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    spread_bps: Optional[int] = Field(default=None, ge=1, le=5000)
    quote_qty: Optional[int] = Field(default=None, ge=1)
    reserve_shares: Optional[int] = Field(default=None, ge=0)
    cash_floor: Optional[str] = Field(default=None, description="decimal string")
    ref_mode: Optional[str] = Field(default=None, pattern=r"^(last|fair)$")


# §2026-06-22 P2.2 — designated external MM + maker rebate
class MakerRebateRequest(BaseModel):
    maker_rebate_bps: int = Field(..., ge=0, le=10000, description="rebate carved from the protocol fee slice; service rejects if it would eat the org split")
    rebate_requires_registration: Optional[bool] = Field(default=None, description="when true (default), only a granted+active MM seat gets the rebate")


class MarketMakerGrantRequest(BaseModel):
    agent_did: str = Field(..., min_length=3, max_length=120)
    status: str = Field(default="active", pattern=r"^(active|suspended|revoked)$")
    min_uptime_pct: Optional[int] = Field(default=None, ge=0, le=100)
    max_spread_bps: Optional[int] = Field(default=None, ge=1, le=10000)


# §2026-06-22 P5 (5.6) — admin fee-edit (all optional; only provided fields update)
class ListingFeesRequest(BaseModel):
    fee_bps: Optional[int] = Field(default=None, ge=0, le=1000, description="total trade fee in bps (≤10%)")
    fee_org_split_bps: Optional[int] = Field(default=None, ge=0, le=10000, description="org's share of the fee in bps")
    maker_rebate_bps: Optional[int] = Field(default=None, ge=0, le=10000, description="maker rebate; service re-validates it still fits the protocol slice after the fee change")


class ProposalCreateRequest(BaseModel):
    symbol: str = Field(..., min_length=2, max_length=8)
    title: str = Field(..., min_length=3, max_length=255)
    description: str = Field(..., min_length=3)
    duration_seconds: int = Field(..., ge=60, le=2592000)
    quorum_pct: float = Field(default=20.0, ge=0, le=100)
    pass_pct: float = Field(default=50.0, ge=0, le=100)
    # §2026-06-22 P1.4: "advisory" (default) | "dilution" (+action_params {new_shares,destination})
    proposal_type: str = Field(default="advisory", max_length=16)
    action_params: Optional[Dict[str, Any]] = Field(default=None)


class SplitRequest(BaseModel):
    factor: int = Field(..., ge=2, le=1000, description="forward split N:1 (each share becomes N)")


class ShareVoteRequest(BaseModel):
    in_favor: bool
    reason: Optional[str] = Field(default=None, max_length=255)
    # §2026-06-22 cross-frame: when voting on a proposal whose LISTING lives on a peer frame,
    # the caller's FE passes the listing's home registry/frame name here; this (home) frame then
    # relays the vote over the federation mTLS channel. Omit/None/self ⇒ local vote (unchanged).
    home_registry: Optional[str] = Field(default=None, max_length=64)


class HaltRequest(BaseModel):
    halted: bool = True


# ── public reads ─────────────────────────────────────────────────────────
@router.get("/listings", summary="List all AGORA listings with live stats")
@limiter.limit("600/minute")
async def list_listings(request: Request, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select

    listings = (await db.execute(select(ExchangeListing))).scalars().all()
    # §COCKPITDESK (2026-10-15): five grouped reads for every listing, not five per listing (875 on sbx-alpha's 175, and
    # the AGORA desk asks every 30 s); the answer is listing_stats' to the character. A failed read leaves every
    # listing without stats, as one failed listing read used to leave the transaction aborted for the rest.
    try:
        batch = await svc.listings_stats(db, listings)
    except Exception:
        logger.warning("[AGORA] listings stats read failed", exc_info=True)
        batch = {}
    out = [_listing_public(l, batch.get(l.id)) for l in listings]
    return {"listings": out, "count": len(out)}


@router.get("/listings/{listing_ref}", summary="One listing + stats")
@limiter.limit("600/minute")
async def get_listing(listing_ref: str, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        l = await svc._get_listing(db, listing_ref)
        return _listing_public(l, await svc.listing_stats(db, l))
    except svc.ExchangeError as e:
        raise _err(e)


@router.get("/organizations/{org_id}/treasury", summary="Org consolidated treasury (org member)")
@limiter.limit("120/minute")
async def org_treasury(
    org_id: str,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """
    The organization's treasury roll-up: the balance of each listing's treasury account and the raised and available
    totals. Organization members only (checked by the service).

    \f
    §V0113 — holding-company treasury roll-up: per-listing keyless treasury balances
    + raised/available totals for the org. Org-member gated (in the service).
    """
    try:
        return await svc.get_org_treasury(db, org_id, developer)
    except svc.ExchangeError as e:
        raise _err(e)


@router.get("/listings/{listing_ref}/book", summary="Aggregated order book")
@limiter.limit("600/minute")
async def get_book(
    listing_ref: str,
    request: Request,
    depth: int = Query(12, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    try:
        l = await svc._get_listing(db, listing_ref)
        return await svc.order_book(db, l, depth=depth)
    except svc.ExchangeError as e:
        raise _err(e)


@router.get("/listings/{listing_ref}/trades", summary="Recent trade tape")
@limiter.limit("600/minute")
async def get_trades(
    listing_ref: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    try:
        l = await svc._get_listing(db, listing_ref)
        return {"trades": await svc.recent_trades(db, l, limit=limit)}
    except svc.ExchangeError as e:
        raise _err(e)


@router.get("/listings/{listing_ref}/candles", summary="OHLCV candles")
@limiter.limit("600/minute")
async def get_candles(
    listing_ref: str,
    request: Request,
    tf: str = Query("1h", pattern="^(1m|15m|1h|1d)$"),
    limit: int = Query(120, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    try:
        l = await svc._get_listing(db, listing_ref)
        return {"tf": tf, "candles": await svc.candles(db, l, tf=tf, limit=limit)}
    except svc.ExchangeError as e:
        raise _err(e)


# §2026-06-22 P5 (5.4) — public cap-table (excludes the keyless org treasury)
@router.get("/listings/{listing_ref}/distributions",
            summary="Distribution history for a listing (public records only)")
@router.get("/listings/{listing_ref}/dividends", include_in_schema=False)
@limiter.limit("240/minute")
async def listing_dividends(listing_ref: str, request: Request,
                            db: AsyncSession = Depends(get_db)):
    """
    Distribution history for a listing, records only: epoch, amount per point, total, status and dates, one row for
    each distribution declared on the listing. Declaring stays with the organization's admins. Public, no auth.

    \f
    §TICKERFUND (O-E) — the fundamentals a holder prices on. RECORDS only:
    epoch, per-point, total, status, dates: every row is a distribution that was
    actually declared on the rail (the pot funds and pays via the settlement
    worker; §REPATAGG handles the cross-frame legs — none of that is touched
    here). The declare door stayed org-admin; reading history is what a public
    ticker page is FOR.
    """
    try:
        l = await svc._get_listing(db, listing_ref)
    except svc.ExchangeError as e:
        raise _err(e)
    rows = (await db.execute(text(
        "SELECT epoch, per_share, total_amount, status, created_at, paid_at "
        "FROM exchange_dividends WHERE listing_id = :l ORDER BY epoch DESC LIMIT 24"
    ), {"l": l.id})).mappings().all()
    return {"listing_id": l.id, "symbol": l.symbol, "currency": l.currency,
            "dividends": [{
                "epoch": r["epoch"], "per_share": str(r["per_share"]),
                "total_amount": str(r["total_amount"]), "status": r["status"],
                "declared_at": r["created_at"].isoformat() if r["created_at"] else None,
                "paid_at": r["paid_at"].isoformat() if r["paid_at"] else None,
            } for r in rows]}


@router.get("/listings/{listing_ref}/holders", summary="Public holder register: external holders (excl treasury)")
@limiter.limit("600/minute")
async def get_holders(
    listing_ref: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await svc.listing_holders(db, listing_ref, limit=limit, offset=offset)
    except svc.ExchangeError as e:
        raise _err(e)


# §2026-06-22 P5 (5.4) — public market-cap-weighted "AGORA 10" index (computed on serve)
@router.get("/index", summary="AGORA index over the top-N listings, weighted by listing value")
@limiter.limit("300/minute")
async def get_index(
    request: Request,
    top_n: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    return await svc.agora_index(db, top_n=top_n)


@router.get("/top-traders", summary="Top traders by 24h notional volume")
@limiter.limit("120/minute")
async def get_top_traders(
    request: Request,
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    return {"traders": await svc.top_traders(db, hours=hours, limit=limit)}


# ── developer (org) surface ──────────────────────────────────────────────
@router.post("/listings", summary="List your organization on AGORA (org OWNER)")
@limiter.limit("10/minute")
async def create_listing(
    body: CreateListingRequest,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    me = developer_caller(developer.id)   # D6-777: the key is this caller's
    cached, err = await idempotency_lookup("exchange.listings", idempotency_key, body.model_dump(), principal=me)
    if err:
        raise HTTPException(status_code=422, detail=err)
    if cached is not None:
        return cached
    try:
        l = await svc.create_listing(
            db,
            developer,
            organization_id=body.organization_id,
            symbol=body.symbol,
            total_shares=body.total_shares,
            ipo_float=body.ipo_float,
            ipo_price=_dec(body.ipo_price, "ipo_price"),
            funding_agent_did=body.funding_agent_did,
            display_name=body.display_name,
        )
    except svc.ExchangeError as e:
        raise _err(e)
    resp = _listing_public(l)
    resp["note"] = "listing awaits admin approval (D15); IPO + trading open on approve"
    await idempotency_store("exchange.listings", idempotency_key, body.model_dump(), resp, principal=me)
    return resp


@router.post("/listings/{listing_ref}/distributions", summary="Declare a distribution (org admin)")
@router.post("/listings/{listing_ref}/dividends", include_in_schema=False)
@limiter.limit("10/minute")
async def declare_dividend(
    listing_ref: str,
    body: DeclareDividendRequest,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    payload = {"listing": listing_ref, **body.model_dump()}
    me = developer_caller(developer.id)   # D6-777: the key is this caller's
    cached, err = await idempotency_lookup("exchange.dividends", idempotency_key, payload, principal=me)
    if err:
        raise HTTPException(status_code=422, detail=err)
    if cached is not None:
        return cached
    try:
        d = await svc.declare_dividend(db, developer, listing_ref, _dec(body.per_share, "per_share"))
    except svc.ExchangeError as e:
        raise _err(e)
    resp = {
        "dividend_id": d.id,
        "listing_id": d.listing_id,
        "epoch": d.epoch,
        "per_share": str(d.per_share),
        "total_amount": str(d.total_amount),
        "status": d.status,
        "note": "settlement worker funds the pot and pays holders",
    }
    await idempotency_store("exchange.dividends", idempotency_key, payload, resp, principal=me)
    # §CHATDESK C5 — the org room's receipt, post-commit, best-effort.
    from agentvault_registry.services.org_room_events import post_dividend_receipt
    await post_dividend_receipt(db, d)
    return resp


# ── org treasury spend (org admin) — §V0113 Phase 2 ──────────────────────
# All four ride the Δ-safe spend spine (svc.treasury_move / place_order /
# declare_dividend); ES kinds exchange_treasury_{dividend|buyback|transfer|sweep}.
async def _resolve_org_listing(db: AsyncSession, org_id: str, symbol: str) -> ExchangeListing:
    l = (
        await db.execute(
            select(ExchangeListing).where(
                ExchangeListing.organization_id == org_id,
                ExchangeListing.symbol == symbol.upper(),
            )
        )
    ).scalar_one_or_none()
    if l is None:
        raise HTTPException(status_code=404, detail="listing not found for this organization")
    return l


@router.post("/organizations/{org_id}/treasury/{symbol}/distribution", summary="Treasury: declare a distribution (org admin)")
@router.post("/organizations/{org_id}/treasury/{symbol}/dividend", include_in_schema=False)
@limiter.limit("10/minute")
async def treasury_dividend(
    org_id: str,
    symbol: str,
    body: DeclareDividendRequest,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """
    Declare a distribution on the organization's listing named by (org_id, symbol). The service checks that the
    caller is an admin of the organization.

    \f
    §V0113: declares a distribution on the org's listing resolved by (org_id, symbol).
    Delegates to svc.declare_dividend (which does its own org-admin gate).
    """
    payload = {"org_id": org_id, "symbol": symbol, **body.model_dump()}
    me = developer_caller(developer.id)   # D6-777: the key is this caller's
    cached, err = await idempotency_lookup("exchange.dividends", idempotency_key, payload, principal=me)
    if err:
        raise HTTPException(status_code=422, detail=err)
    if cached is not None:
        return cached
    listing = await _resolve_org_listing(db, org_id, symbol)
    try:
        d = await svc.declare_dividend(db, developer, listing.id, _dec(body.per_share, "per_share"))
    except svc.ExchangeError as e:
        raise _err(e)
    resp = {
        "dividend_id": d.id,
        "listing_id": d.listing_id,
        "epoch": d.epoch,
        "per_share": str(d.per_share),
        "total_amount": str(d.total_amount),
        "status": d.status,
        "note": "settlement worker funds the pot and pays holders",
    }
    await idempotency_store("exchange.dividends", idempotency_key, payload, resp, principal=me)
    # §CHATDESK C5 — the org room's receipt, post-commit, best-effort.
    from agentvault_registry.services.org_room_events import post_dividend_receipt
    await post_dividend_receipt(db, d)
    return resp


@router.post("/organizations/{org_id}/treasury/{symbol}/buy", summary="Treasury buy: the organization buys its own points (org admin)")
@router.post("/organizations/{org_id}/treasury/{symbol}/buyback", include_in_schema=False)
@limiter.limit("30/minute")
async def treasury_buyback(
    org_id: str,
    symbol: str,
    body: TreasuryBuybackRequest,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    payload = {"org_id": org_id, "symbol": symbol, **body.model_dump()}
    me = developer_caller(developer.id)   # D6-777: the key is this caller's
    cached, err = await idempotency_lookup("exchange.treasury_buyback", idempotency_key, payload, principal=me)
    if err:
        raise HTTPException(status_code=422, detail=err)
    if cached is not None:
        return cached
    try:
        resp = await svc.treasury_buyback(
            db, org_id, symbol, body.qty, _dec(body.limit_price, "limit_price"), developer
        )
    except svc.ExchangeError as e:
        raise _err(e)
    await idempotency_store("exchange.treasury_buyback", idempotency_key, payload, resp, principal=me)
    return resp


@router.post("/organizations/{org_id}/treasury/{symbol}/transfer", summary="Treasury: transfer/grant (org admin)")
@limiter.limit("30/minute")
async def treasury_transfer(
    org_id: str,
    symbol: str,
    body: TreasuryTransferRequest,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    payload = {"org_id": org_id, "symbol": symbol, **body.model_dump()}
    me = developer_caller(developer.id)   # D6-777: the key is this caller's
    cached, err = await idempotency_lookup("exchange.treasury_transfer", idempotency_key, payload, principal=me)
    if err:
        raise HTTPException(status_code=422, detail=err)
    if cached is not None:
        return cached
    try:
        resp = await svc.treasury_move(
            db, org_id, symbol, body.dest_did, _dec(body.amount, "amount"), "transfer",
            developer, reserve_floor=_dec(body.reserve_floor or "0", "reserve_floor"),
            idempotency_key=idempotency_key,
        )
    except svc.ExchangeError as e:
        raise _err(e)
    await idempotency_store("exchange.treasury_transfer", idempotency_key, payload, resp, principal=me)
    return resp


@router.post("/organizations/{org_id}/treasury/{from_symbol}/sweep", summary="Treasury: sweep to a sibling listing (org admin)")
@limiter.limit("30/minute")
async def treasury_sweep(
    org_id: str,
    from_symbol: str,
    body: TreasurySweepRequest,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    payload = {"org_id": org_id, "from_symbol": from_symbol, **body.model_dump()}
    me = developer_caller(developer.id)   # D6-777: the key is this caller's
    cached, err = await idempotency_lookup("exchange.treasury_sweep", idempotency_key, payload, principal=me)
    if err:
        raise HTTPException(status_code=422, detail=err)
    if cached is not None:
        return cached
    try:
        resp = await svc.treasury_sweep(
            db, org_id, from_symbol, body.to_symbol, _dec(body.amount, "amount"), developer,
            idempotency_key=idempotency_key,
        )
    except svc.ExchangeError as e:
        raise _err(e)
    await idempotency_store("exchange.treasury_sweep", idempotency_key, payload, resp, principal=me)
    return resp


@router.post("/organizations/{org_id}/treasury/{symbol}/refloat", summary="Treasury: re-release points to the market (org admin)")
@limiter.limit("30/minute")
async def treasury_refloat(
    org_id: str,
    symbol: str,
    body: TreasuryRefloatRequest,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    payload = {"org_id": org_id, "symbol": symbol, **body.model_dump()}
    me = developer_caller(developer.id)   # D6-777: the key is this caller's
    cached, err = await idempotency_lookup("exchange.treasury_refloat", idempotency_key, payload, principal=me)
    if err:
        raise HTTPException(status_code=422, detail=err)
    if cached is not None:
        return cached
    try:
        resp = await svc.treasury_refloat(
            db, org_id, symbol, body.qty, developer,
            offer_price=_dec(body.offer_price, "offer_price") if body.offer_price else None,
            min_retained=body.min_retained or 0,
            idempotency_key=idempotency_key,
        )
    except svc.ExchangeError as e:
        raise _err(e)
    await idempotency_store("exchange.treasury_refloat", idempotency_key, payload, resp, principal=me)
    return resp


@router.post("/organizations/{org_id}/treasury/{symbol}/sell", summary="Treasury: sell points to the market (org admin)")
@limiter.limit("30/minute")
async def treasury_sell(
    org_id: str,
    symbol: str,
    body: TreasurySellRequest,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    payload = {"org_id": org_id, "symbol": symbol, **body.model_dump()}
    me = developer_caller(developer.id)   # D6-777: the key is this caller's
    cached, err = await idempotency_lookup("exchange.treasury_sell", idempotency_key, payload, principal=me)
    if err:
        raise HTTPException(status_code=422, detail=err)
    if cached is not None:
        return cached
    try:
        resp = await svc.treasury_sell(
            db, org_id, symbol, body.qty, developer,
            order_type=body.order_type,
            limit_price=_dec(body.limit_price, "limit_price") if body.limit_price else None,
            min_retained=body.min_retained or 0,
        )
    except svc.ExchangeError as e:
        raise _err(e)
    await idempotency_store("exchange.treasury_sell", idempotency_key, payload, resp, principal=me)
    return resp


@router.put("/organizations/{org_id}/treasury/{symbol}/mm", summary="Treasury: configure market-maker (org admin)")
@limiter.limit("30/minute")
async def treasury_mm_config_set(
    org_id: str,
    symbol: str,
    body: TreasuryMMConfigRequest,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    try:
        resp = await svc.set_mm_config(
            db, org_id, symbol, developer,
            enabled=body.enabled, spread_bps=body.spread_bps, quote_qty=body.quote_qty,
            reserve_shares=body.reserve_shares,
            cash_floor=_dec(body.cash_floor, "cash_floor") if body.cash_floor else None,
            ref_mode=body.ref_mode,
        )
    except svc.ExchangeError as e:
        raise _err(e)
    return resp


@router.get("/organizations/{org_id}/treasury/{symbol}/mm", summary="Treasury: read market-maker config")
async def treasury_mm_config_get(
    org_id: str,
    symbol: str,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    try:
        resp = await svc.get_mm_config(db, org_id, symbol)
    except svc.ExchangeError as e:
        raise _err(e)
    return resp


# ── §2026-06-22 P2.2 — designated external MM + maker rebate ──────────────
@router.put("/organizations/{org_id}/treasury/{symbol}/maker-rebate", summary="Maker-taker: set the maker rebate (org admin)")
@limiter.limit("30/minute")
async def set_maker_rebate(
    org_id: str,
    symbol: str,
    body: MakerRebateRequest,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """Set the per-listing maker rebate (carved from the PROTOCOL fee slice at settlement,
    Δ=0). The service enforces the config bound (rebate can't eat the org split)."""
    payload = {"org_id": org_id, "symbol": symbol, **body.model_dump()}
    me = developer_caller(developer.id)   # D6-777: the key is this caller's
    cached, err = await idempotency_lookup("exchange.maker_rebate", idempotency_key, payload, principal=me)
    if err:
        raise HTTPException(status_code=422, detail=err)
    if cached is not None:
        return cached
    try:
        resp = await svc.set_maker_rebate(
            db, org_id, symbol, developer,
            maker_rebate_bps=body.maker_rebate_bps,
            rebate_requires_registration=body.rebate_requires_registration,
        )
    except svc.ExchangeError as e:
        raise _err(e)
    await idempotency_store("exchange.maker_rebate", idempotency_key, payload, resp, principal=me)
    return resp


# ── §2026-06-22 P5 (5.6) — admin fee-edit ─────────────────────────────────
@router.put("/organizations/{org_id}/treasury/{symbol}/fees", summary="Set the listing fee schedule (org admin)")
@limiter.limit("30/minute")
async def set_listing_fees(
    org_id: str,
    symbol: str,
    body: ListingFeesRequest,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """Set fee_bps / fee_org_split_bps / maker_rebate_bps on an org's listing (org admin;
    only provided fields update). Δ-NEUTRAL: new trades stamp the new schedule at match; no
    existing trade/escrow/balance is touched. The service re-validates the maker-rebate config
    bound against the resulting fee schedule (422 if a fee cut would make the stored rebate eat
    the protocol slice)."""
    payload = {"org_id": org_id, "symbol": symbol, **body.model_dump()}
    me = developer_caller(developer.id)   # D6-777: the key is this caller's
    cached, err = await idempotency_lookup("exchange.listing_fees", idempotency_key, payload, principal=me)
    if err:
        raise HTTPException(status_code=422, detail=err)
    if cached is not None:
        return cached
    try:
        resp = await svc.set_listing_fees(
            db, org_id, symbol, developer,
            fee_bps=body.fee_bps,
            fee_org_split_bps=body.fee_org_split_bps,
            maker_rebate_bps=body.maker_rebate_bps,
        )
    except svc.ExchangeError as e:
        raise _err(e)
    await idempotency_store("exchange.listing_fees", idempotency_key, payload, resp, principal=me)
    return resp


@router.post("/organizations/{org_id}/listings/{symbol}/market-makers", summary="Maker-taker: grant/revoke a designated MM seat (org admin)")
@limiter.limit("30/minute")
async def grant_market_maker(
    org_id: str,
    symbol: str,
    body: MarketMakerGrantRequest,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """Grant/update/revoke a third-party agent's designated market-maker seat on this
    listing (writes ExchangeMarketMaker + reflects the participant flag)."""
    payload = {"org_id": org_id, "symbol": symbol, **body.model_dump()}
    me = developer_caller(developer.id)   # D6-777: the key is this caller's
    cached, err = await idempotency_lookup("exchange.market_makers", idempotency_key, payload, principal=me)
    if err:
        raise HTTPException(status_code=422, detail=err)
    if cached is not None:
        return cached
    try:
        resp = await svc.grant_market_maker(
            db, org_id, symbol, developer,
            agent_did=body.agent_did, status=body.status,
            min_uptime_pct=body.min_uptime_pct, max_spread_bps=body.max_spread_bps,
        )
    except svc.ExchangeError as e:
        raise _err(e)
    await idempotency_store("exchange.market_makers", idempotency_key, payload, resp, principal=me)
    return resp


@router.get("/listings/{listing_ref}/market-makers", summary="Public: designated market-makers + obligations for a listing")
@limiter.limit("600/minute")
async def list_market_makers(listing_ref: str, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        return await svc.list_market_makers(db, listing_ref)
    except svc.ExchangeError as e:
        raise _err(e)


# ── P3.1 share-weighted shareholder governance ────────────────────────────
@router.post("/organizations/{org_id}/proposals", summary="Open a point-weighted holder proposal (org admin)")
@limiter.limit("20/minute")
async def exchange_create_proposal(
    org_id: str,
    body: ProposalCreateRequest,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    try:
        resp = await svc.create_proposal(
            db, org_id, body.symbol, developer,
            title=body.title, description=body.description, duration_seconds=body.duration_seconds,
            quorum_pct=body.quorum_pct, pass_pct=body.pass_pct,
            proposal_type=body.proposal_type, action_params=body.action_params,
        )
    except svc.ExchangeError as e:
        raise _err(e)
    return resp


@router.post("/proposals/{proposal_id}/vote", summary="Cast a point-weighted vote (holder agent)")
@limiter.limit("60/minute")
async def exchange_cast_vote(
    proposal_id: str,
    body: ShareVoteRequest,
    request: Request,
    current_agent: Agent = Security(require_agent_permission("exchange.vote")),
    db: AsyncSession = Depends(get_db),
):
    # §2026-06-22 cross-frame: if the proposal's listing lives on a PEER frame, the voter
    # authenticates HERE (their home) and we relay the vote to the listing's home over the
    # federation mTLS channel (mirrors governance.py federation vote → ES; here the listing's
    # home frame plays the central role). Local listings keep the direct path unchanged.
    # §AGORASIM-2 (2026-09-22): the federation name is "self" too (on a cloud operator REGISTRY_NAME is the stack label)
    from agentvault_registry.services.contract_xframe import self_federation_name as _self_fed
    _self = {(os.getenv("FEDERATION_NAME") or "").lower(), (os.getenv("REGISTRY_NAME") or "").lower(), (_self_fed() or "").lower()} - {""}
    home = (body.home_registry or "").strip()
    if home and home.lower() not in _self and home.lower() != "local":
        if os.getenv("EXCHANGE_CROSSFRAME_VOTE_ENABLED", "false").lower() not in ("1", "true", "yes"):
            raise HTTPException(409, "cross-frame AGORA voting disabled on this registry")
        from agentvault_registry.services import exchange_passport as passport
        try:
            status_code, data = await passport.peer_request(
                db, home, "POST", "/api/v1/federation/agora-vote",
                {"proposal_id": proposal_id, "voter_did": current_agent.did,
                 "in_favor": body.in_favor, "reason": body.reason},
            )
        except passport.PassportError as e:
            raise HTTPException(e.status_code, e.detail)
        if status_code >= 300:
            raise HTTPException(status_code, f"cross-frame vote relay to '{home}' failed: {data}")
        return data
    try:
        resp = await svc.cast_share_vote(db, current_agent.did, proposal_id, body.in_favor, body.reason)
    except svc.ExchangeError as e:
        raise _err(e)
    return resp


@router.post("/proposals/{proposal_id}/tally", summary="Tally a point-weighted proposal")
@limiter.limit("30/minute")
async def exchange_tally_proposal(
    proposal_id: str,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    try:
        resp = await svc.tally_proposal(db, proposal_id)
    except svc.ExchangeError as e:
        raise _err(e)
    return resp


@router.post("/proposals/{proposal_id}/execute", summary="Execute a PASSED proposal to issue more points (org admin)")
@limiter.limit("20/minute")
async def exchange_execute_proposal(
    proposal_id: str,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    # §2026-06-22 P1.4 — on-chain effect of a passed governance proposal (currently: share dilution).
    try:
        resp = await svc.execute_dilution(db, proposal_id, developer)
    except svc.ExchangeError as e:
        raise _err(e)
    return resp


@router.post("/organizations/{org_id}/listings/{symbol}/split", summary="Forward split N:1 (org admin)")
@limiter.limit("10/minute")
async def exchange_split_listing(
    org_id: str,
    symbol: str,
    body: SplitRequest,
    request: Request,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    # §2026-06-22 P1.3 — forward stock split: rescale positions + listing ×N, Δ-neutral (no vote).
    try:
        resp = await svc.split_listing(db, org_id, symbol, developer, factor=body.factor)
    except svc.ExchangeError as e:
        raise _err(e)
    return resp


@router.get("/listings/{listing_ref}/proposals", summary="List holder proposals for a listing")
async def exchange_list_proposals(listing_ref: str, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        resp = await svc.list_proposals(db, listing_ref)
    except svc.ExchangeError as e:
        raise _err(e)
    return resp


@router.get("/proposals/{proposal_id}", summary="Get a holder proposal + live tally")
async def exchange_get_proposal(proposal_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        prop = await svc.get_proposal(db, proposal_id)
        prop["tally"] = await svc.tally_proposal(db, proposal_id, finalize=False)
    except svc.ExchangeError as e:
        raise _err(e)
    return prop


# ── agent surface ────────────────────────────────────────────────────────
@router.post("/orders", summary="Place a limit/market order (agent)")
@limiter.limit("600/minute")
async def place_order(
    body: PlaceOrderRequest,
    request: Request,
    current_agent: Agent = Security(require_agent_permission("exchange.trade")),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    # Jurisdiction Profiles (SPEC 2026-07-31): operator-declared feature restriction.
    # Deny-only, pre-escrow, before any money moves. Byte-inert while JURISDICTION_MODE=off.
    from agentvault_registry.services import jurisdiction as _juris
    await _juris.check_jurisdiction(db, "exchange", actor=current_agent.did)
    me = agent_caller(current_agent.did)   # D6-777: the key is this caller's
    cached, err = await idempotency_lookup("exchange.orders", idempotency_key, body.model_dump(), principal=me)
    if err:
        raise HTTPException(status_code=422, detail=err)
    if cached is not None:
        return cached
    # §29 OPA I10 `venue_order_ok` — LIVE CALL SITE. A halt exists for exactly the moment things
    # are going wrong, which is also when retry loops and workers are most likely to keep
    # submitting; making it a policy means every order path honours it identically, including any
    # path added later that forgets to check. Shadow-mode observes only (Δ-irrelevant, cannot
    # block while OPA_ENFORCE=false) and is fire-and-forget so it never sits on the trade path.
    # NOTE the rule keeps CANCEL legal during a halt on purpose — a halt must let people OUT.
    try:
        from agentvault_registry import opa_shadow
        await opa_shadow.shadow_check(
            "agentvault/invariants/venue_order_ok",
            {"global_halt": False, "listing_status": "approved", "action": "place"},
            True,
            label="place_order",
        )
    except Exception as exc:  # never let observability break a money path
        logger.debug(f"[OPA] venue_order check skipped: {exc!r}")
    # §SPAWN-ANCHOR (v2, 2026-08-12): an anchored (walletless) child places orders funded by —
    # and OWNED by — its parent's purse (the desk/clerk model: the clerk places, the desk holds
    # the collateral AND the resulting position). Default off / non-anchored ⇒ (purse_agent,
    # purse_did) == (current_agent, its did), so the order is byte-for-byte unchanged. Resolving
    # HERE (pre-escrow) means the deposit leg, fills, position, refund and cancel all key on the
    # purse via ExchangeOrder.agent_did → one redirect keeps Δ=0 correct across the whole
    # order lifecycle. Requires the child to present its birth token on X-Capability-Token
    # (exchange.trade); without it the resolver returns self (walletless) and the deposit fails
    # cleanly (Δ-safe).
    from agentvault_registry.services.spawn_anchor import resolve_spend_purse_agent
    purse_agent, purse_did = await resolve_spend_purse_agent(db, current_agent, request)
    _anchored_spend = purse_did != current_agent.did

    # IRONKEY L2 spend gate (pre-escrow, Δ-safe): a limit-BUY order's notional (qty×price) is
    # exposure. Market/sell skip (no known notional / no outflow). 403 must propagate — compute
    # in a guarded block, then enforce outside it. For an ANCHORED spend we pass `request` so the
    # child's L4 capability budget/max_per_tx caveat binds the draw on the parent's purse (scoped:
    # a non-anchored order passes request=None → today's behaviour exactly). NOTE: a MARKET buy
    # has no known notional so this gate does not fire — an anchored market buy is bounded by the
    # parent's live balance, not the token budget (documented v2 limitation).
    if body.side == "buy" and body.price is not None:
        try:
            _notional = Decimal(str(body.qty)) * Decimal(str(body.price))
        except (InvalidOperation, ValueError, TypeError):
            _notional = None
        if _notional is not None:
            await enforce_agent_spend(db, current_agent.did, _notional, same_registry=True,
                                      request=request if _anchored_spend else None)
    try:
        if body.stop_price is not None:  # §#86 stop / stop-limit → armed intent (escrow at trigger)
            placed = await svc.place_stop_order(
                db,
                agent_did=purse_did,  # §SPAWN-ANCHOR: order owned+funded by the purse
                listing_ref=body.listing,
                side=body.side,
                order_type=body.order_type,
                qty=body.qty,
                stop_price=_dec(body.stop_price, "stop_price"),
                price=_dec(body.price, "price") if body.price is not None else None,
                client_order_id=body.client_order_id,
                tif=body.tif,
            )
        else:
            placed = await svc.place_order(
                db,
                agent_did=purse_did,  # §SPAWN-ANCHOR: order owned+funded by the purse
                listing_ref=body.listing,
                side=body.side,
                order_type=body.order_type,
                qty=body.qty,
                price=_dec(body.price, "price") if body.price is not None else None,
                client_order_id=body.client_order_id,
                ttl_seconds=body.ttl_seconds,
                tif=body.tif,
                post_only=body.post_only,
            )
    except svc.ExchangeError as e:
        raise _err(e)
    o = placed.order
    resp = {
        "order_id": o.id,
        "status": o.status,
        "side": o.side,
        "order_type": o.order_type,
        "tif": o.tif,
        "post_only": o.post_only,
        "price": str(o.price) if o.price is not None else None,
        "qty": o.qty,
        "remaining": o.remaining,
        "escrow_amount": str(o.escrow_amount),
        "fills": [
            {"trade_id": t.id, "price": str(t.price), "qty": t.qty, "notional": str(t.notional)}
            for t in placed.fills
        ],
    }
    await idempotency_store("exchange.orders", idempotency_key, body.model_dump(), resp, principal=me)
    return resp


@router.delete("/orders/{order_id}", summary="Cancel my order (agent)")
@limiter.limit("600/minute")
async def cancel_order(
    order_id: str,
    request: Request,
    current_agent: Agent = Security(require_agent_permission("exchange.trade")),
    db: AsyncSession = Depends(get_db),
):
    # §SPAWN-ANCHOR (v2): an anchored child cancels its PURSE-owned order — resolve the purse so
    # the DID matches the order owner (refund routes back to the purse regardless). Non-anchored /
    # no-token ⇒ resolves to self = today's behaviour. (A child that omits its birth token here
    # can't address a purse-owned order; the parent, which owns it, always can.)
    from agentvault_registry.services.spawn_anchor import resolve_spend_purse_agent
    _purse_agent, _purse_did = await resolve_spend_purse_agent(db, current_agent, request)
    try:
        o = await svc.cancel_order(db, _purse_did, order_id)
    except svc.ExchangeError as e:
        raise _err(e)
    return {"order_id": o.id, "status": o.status, "remaining": o.remaining,
            "note": "buy-side residual escrow refunds via the settlement worker"}


@router.get("/orders/mine", summary="My orders (agent)")
@limiter.limit("240/minute")
async def my_orders(
    request: Request,
    listing: Optional[str] = Query(default=None),
    current_agent: Agent = Security(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    try:
        return {"orders": await svc.my_orders(db, current_agent.did, listing)}
    except svc.ExchangeError as e:
        raise _err(e)


@router.get("/portfolio", summary="My holdings + P&L + distributions (agent)")
@limiter.limit("240/minute")
async def my_portfolio(
    request: Request,
    current_agent: Agent = Security(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    return await svc.portfolio(db, current_agent.did)


@router.get("/certificate", summary="A signed certificate for one of my holdings (agent)")
@limiter.limit("120/minute")
async def my_share_certificate(
    request: Request,
    symbol: str,
    current_agent: Agent = Security(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    An Ed25519-signed attestation that the calling agent holds N points of a listing (`symbol`), from the same
    signer as the Guild work credentials, so the in-browser verifier can check it. It answers only for the caller's
    own holding; the public holder list is GET /api/v1/agora/listings/{ref}/holders. Needs an agent token.

    \f
    §SHOWCASESTOCKS — an Ed25519 attestation that this agent holds N of a
    symbol, on the SAME signer behind guild work credentials, so §AGENTDISC's
    in-browser verifier already knows how to check it.

    Scoped to the CALLER's own holding on purpose: a certificate rail that
    answered for any DID would be a public holder-lookup oracle, and the
    holder register already has its own deliberately-shaped public endpoint
    (`/listings/{ref}/holders`).
    """
    from agentvault_registry.services.share_certificate import build_certificate
    from agentvault_registry.config import settings as _st
    cert = await build_certificate(db, current_agent.did, symbol,
                                   getattr(_st, "REGISTRY_NAME", "") or "")
    if cert is None:
        # Holding none of it is a clean absence, not an error.
        return {"held": False, "symbol": symbol.upper(),
                "note": "You hold no points of this symbol on this registry."}
    # The pubkey travels ALONGSIDE the signed object, never inside it: anything
    # added to the bundle after signing changes the canonical bytes and breaks
    # verification (measured — see share_certificate.py's self-check).
    try:
        from agentvault_registry.services.attestation_signer import get_pubkey_b64, get_pubkey_id
        signer = {"pubkey_b64": get_pubkey_b64(), "pubkey_id": get_pubkey_id(), "alg": "Ed25519"}
    except Exception:  # noqa: BLE001
        signer = {}
    return {"held": True, "certificate": cert, "signer": signer}


@router.post("/listings/{listing_ref}/launch/buy", summary="Buy at launch, from the launch allocation (agent)")
@router.post("/listings/{listing_ref}/ipo/buy", include_in_schema=False)
@limiter.limit("30/minute")
async def ipo_buy(
    listing_ref: str,
    body: IpoBuyRequest,
    request: Request,
    current_agent: Agent = Security(require_agent_permission("exchange.ipo")),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    # Jurisdiction Profiles (SPEC 2026-07-31): operator-declared feature restriction.
    # Deny-only, pre-escrow, before any money moves. Byte-inert while JURISDICTION_MODE=off.
    from agentvault_registry.services import jurisdiction as _juris
    await _juris.check_jurisdiction(db, "exchange", actor=current_agent.did)
    payload = {"listing": listing_ref, **body.model_dump()}
    me = agent_caller(current_agent.did)   # D6-777: the key is this caller's
    cached, err = await idempotency_lookup("exchange.ipo", idempotency_key, payload, principal=me)
    if err:
        raise HTTPException(status_code=422, detail=err)
    if cached is not None:
        return cached
    # IRONKEY L2 spend gate (pre-escrow, Δ-safe): IPO notional = qty × listing ipo_price.
    try:
        _ipx = (await db.execute(text(
            "SELECT ipo_price FROM exchange_listings WHERE symbol = :ref OR id = :ref LIMIT 1"
        ), {"ref": listing_ref})).scalar()
    except Exception:
        _ipx = None
    if _ipx is not None:
        await enforce_agent_spend(
            db, current_agent.did, Decimal(str(_ipx)) * Decimal(str(body.qty)), same_registry=True
        )
    try:
        p = await svc.ipo_buy(db, current_agent.did, listing_ref, body.qty)
    except svc.ExchangeError as e:
        raise _err(e)
    resp = {
        "purchase_id": p.id,
        "status": p.status,
        "qty": p.qty,
        "amount": str(p.amount),
        "note": "proceeds settle to the org treasury via the worker",
    }
    await idempotency_store("exchange.ipo", idempotency_key, payload, resp, principal=me)
    return resp


# ── admin surface ────────────────────────────────────────────────────────
@router.post("/admin/listings/{listing_ref}/approve", summary="Approve a listing (admin)")
async def admin_approve(
    listing_ref: str,
    request: Request,
    _admin=Security(require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    try:
        l = await svc._get_listing(db, listing_ref)
    except svc.ExchangeError as e:
        raise _err(e)
    # REGAUTH (SPEC 2026-08-15): if the operator's jurisdiction profile declares
    # that listing approval / IPO opening requires a recorded regulatory
    # authorization, park this approval (409 + blockers checklist) until one is
    # on file. Approval IS the act that opens the market, so BOTH acts gate at
    # this one seam: exchange.listing always, exchange.ipo additionally when the
    # listing carries an IPO float. Byte-inert while JURISDICTION_MODE=off or
    # nothing is declared; parks BEFORE any state change (delta-irrelevant).
    from agentvault_registry.services import regulatory_auth as _regauth
    _actor = f"dev:{getattr(_admin, 'id', '?')}"
    await _regauth.check_regulatory_authorization(
        db, "exchange.listing", subject_ref=l.symbol, actor=_actor)
    if (l.ipo_float or 0) > 0:
        await _regauth.check_regulatory_authorization(
            db, "exchange.ipo", subject_ref=l.symbol, actor=_actor)
    try:
        l = await svc.approve_listing(db, l.id)
    except svc.ExchangeError as e:
        raise _err(e)
    return _listing_public(l)


@router.post("/admin/listings/{listing_ref}/halt", summary="Halt/resume a listing (admin)")
async def admin_halt(
    listing_ref: str,
    body: HaltRequest,
    request: Request,
    _admin=Security(require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    try:
        l = await svc._get_listing(db, listing_ref)
        l = await svc.set_listing_halt(db, l.id, body.halted)
    except svc.ExchangeError as e:
        raise _err(e)
    return _listing_public(l)


class CircuitBreakerRequest(BaseModel):
    cb_pct: int = Field(..., ge=0, le=10000, description="circuit-breaker threshold in bps (0 disables); ~1500-2000 = 15-20%")


@router.post("/admin/listings/{listing_ref}/circuit-breaker", summary="Set a listing's circuit-breaker threshold (admin)")
async def admin_circuit_breaker(
    listing_ref: str,
    body: CircuitBreakerRequest,
    request: Request,
    _admin=Security(require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    try:
        l = await svc._get_listing(db, listing_ref)
        l = await svc.set_circuit_breaker(db, l.id, body.cb_pct)
    except svc.ExchangeError as e:
        raise _err(e)
    return _listing_public(l)


class PriceBandRequest(BaseModel):
    # ⚠ PERCENT. The circuit-breaker route above takes BASIS POINTS. Ceiling 500 so that
    # sending a bps value (e.g. 2500 for "25%") is refused loudly instead of silently
    # widening the band to +/-2500%. See `svc.set_price_band` for the whole argument.
    band_pct: int = Field(..., ge=1, le=500,
                          description="price band as +/- PERCENT around the last trade "
                                      "(NOT bps — cb_pct above is bps). 25 = +/-25%. "
                                      "No disable value: widen it instead.")


@router.post("/admin/listings/{listing_ref}/price-band", summary="Set a listing's price band (admin)")
async def admin_price_band(
    listing_ref: str,
    body: PriceBandRequest,
    request: Request,
    _admin=Security(require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """§PRICEBAND — the guard that actually rejects orders was the one with no admin route.

    `POST .../circuit-breaker` existed; the price band did not, so tuning it meant a direct
    DB write. Same shape, same admin flag, same Δ-irrelevance (config only).
    """
    try:
        l = await svc._get_listing(db, listing_ref)
        l = await svc.set_price_band(db, l.id, body.band_pct)
    except svc.ExchangeError as e:
        raise _err(e)
    return _listing_public(l)


@router.post("/admin/listings/{listing_ref}/delist", summary="Delist (cancel-all + refunds) (admin)")
async def admin_delist(
    listing_ref: str,
    request: Request,
    _admin=Security(require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    try:
        l = await svc._get_listing(db, listing_ref)
        return await svc.delist(db, l.id)
    except svc.ExchangeError as e:
        raise _err(e)


@router.post("/admin/global-halt", summary="Market-wide halt flag (admin)")
async def admin_global_halt(
    body: HaltRequest,
    request: Request,
    _admin=Security(require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    await svc.set_flag(db, "global_halt", "true" if body.halted else "false")
    return {"global_halt": body.halted}


# ── §2026-06-17 per-stock DEMAND DIRECTOR (sim testing; stored in the ExchangeFlag KV,
#    no migration). The sim polls the public GET each cycle to bias a stock's order flow
#    UP/DOWN. Δ-safe — it only tilts order side/price; money still flows via the escrow mover.
class DemandDirectorRequest(BaseModel):
    """enabled + {SYMBOL: {dir: -1..1 (▼..▲), strength: 0..1, [v2] intensity: 0..1,
    volatility: 0..1, regime: calm|breakout|panic|euphoria}}. v2 fields optional."""
    enabled: bool = True
    tickers: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


@router.get("/demand-director", summary="AGORA per-listing demand director (sim-readable)")
async def get_demand_director(request: Request, db: AsyncSession = Depends(get_db)):
    """Public read: the market-mode sim polls this each cycle to push configured listings
    up (dir>0 → buy-side + higher limits) or down (dir<0). Δ-safe (no new path for units)."""
    import json as _json
    raw = await svc.get_flag(db, "demand_director")
    if not raw:
        return {"enabled": False, "tickers": {}}
    try:
        cfg = _json.loads(raw)
    except Exception:
        return {"enabled": False, "tickers": {}}
    return {"enabled": bool(cfg.get("enabled", True)), "tickers": cfg.get("tickers", {})}


@router.put("/admin/demand-director", summary="Set the per-listing demand director (admin)")
async def set_demand_director(
    body: DemandDirectorRequest,
    request: Request,
    _admin=Security(require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """Admin: point each listing ▲ up (dir>0) / ▼ down (dir<0) / neutral (0), strength 0..1.
    The market-mode sim biases that ticker's order flow accordingly. Δ-safe."""
    import json as _json
    clean: Dict[str, Dict[str, Any]] = {}
    for sym, c in (body.tickers or {}).items():
        c = c or {}
        try:
            dir_ = max(-1.0, min(1.0, float(c.get("dir", 0))))
            strength = max(0.0, min(1.0, float(c.get("strength", 0.7))))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"bad director entry for {sym}")
        entry = {"dir": dir_, "strength": strength}
        # §2026-06-25 v2 — preserve optional enrichment fields (omitted → sim defaults = v1)
        try:
            if c.get("intensity") is not None:  entry["intensity"] = max(0.0, min(1.0, float(c["intensity"])))
            if c.get("volatility") is not None: entry["volatility"] = max(0.0, min(1.0, float(c["volatility"])))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"bad director enrichment for {sym}")
        if c.get("regime"):
            entry["regime"] = str(c["regime"])[:16]
        clean[str(sym).upper()] = entry
    cfg = {"enabled": bool(body.enabled), "tickers": clean}
    await svc.set_flag(db, "demand_director", _json.dumps(cfg))
    logger.info(f"[AGORA] demand-director set by {getattr(_admin,'email','?')}: {cfg}")
    return {"status": "updated", **cfg}


# ── §2026-06-25 Director "Campaign Engine" v1 — scripted, timed demand-director
#    campaigns (a configurable trading-scenario game). The settlement worker steps
#    the active campaign each cycle (svc.step_active_campaign) and writes the live
#    demand_director the sim already polls. Δ-irrelevant (biases sim order-gen only).
class CampaignStartRequest(BaseModel):
    """Start a campaign by named `preset` OR an inline `campaign` dict (one required)."""
    preset: Optional[str] = None
    campaign: Optional[Dict[str, Any]] = None


class CampaignStopRequest(BaseModel):
    restore_softpeg: bool = True


@router.get("/campaign/presets", summary="AGORA director campaign presets (public)")
async def get_campaign_presets(request: Request):
    """Public: the built-in scenario library (bull run, flash crash, pump & dump, soft peg)."""
    return {"presets": [
        {"key": k, "name": v.get("name", k), "description": v.get("description", ""),
         "phases": len(v.get("phases", [])),
         "duration_sec": sum(float(p.get("duration_sec", 0) or 0) for p in v.get("phases", []))}
        for k, v in svc.CAMPAIGN_PRESETS.items()
    ]}


@router.get("/campaign/status", summary="AGORA director campaign status (public)")
async def get_campaign_status(request: Request, db: AsyncSession = Depends(get_db)):
    """Public read: current campaign progress (phase, elapsed, live direction and strength)."""
    return await svc.campaign_status(db)


@router.post("/admin/campaign/start", summary="Start a director campaign (admin)")
async def start_campaign_endpoint(
    body: CampaignStartRequest,
    request: Request,
    _admin=Security(require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """Admin: begin a scripted demand-director campaign (a preset or an inline campaign).
    The settlement worker drives the live demand_director from it each cycle. Δ-safe."""
    if body.preset:
        camp = svc.CAMPAIGN_PRESETS.get(body.preset)
        if not camp:
            raise HTTPException(status_code=404, detail=f"unknown preset '{body.preset}'")
    elif body.campaign:
        camp = body.campaign
    else:
        raise HTTPException(status_code=422, detail="provide a preset name or a campaign dict")
    try:
        res = await svc.start_campaign(db, camp)
    except svc.ExchangeError as e:
        raise _err(e)
    logger.info(f"[AGORA-campaign] started by {getattr(_admin,'email','?')}: {res}")
    return {"status": "started", **res}


@router.post("/admin/campaign/stop", summary="Stop the active director campaign (admin)")
async def stop_campaign_endpoint(
    body: CampaignStopRequest,
    request: Request,
    _admin=Security(require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """Admin: stop the active campaign; optionally restore the uniform soft-peg director."""
    res = await svc.stop_campaign(db, restore_softpeg=body.restore_softpeg)
    logger.info(f"[AGORA-campaign] stopped by {getattr(_admin,'email','?')}: {res}")
    return {"status": "stopped", **res}


@router.get("/admin/invariant", summary="I-X1..I-X4 live conservation check (admin)")
async def admin_invariant(
    request: Request,
    _admin=Security(require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    return await svc.compute_invariants(db)


@router.get("/admin/gateway-keeper", summary="Gateway Float Keeper status + repat-credit health (admin)")
async def admin_gateway_keeper(
    request: Request,
    _admin=Security(require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """Read-only status for the AGORA Gateway Float Keeper (2026-06-19) + the
    repatriation sub-ledger health. Surfaces what the keeper auto-heals (the
    pending float, via treasury→gateway top-up) AND what it does NOT — the
    terminal `abandoned` credits (re-armed to the max generation, genuinely
    undeliverable = real stranded value) and the sub-`REPAT_DUST` credits the
    worker skips. Powers the Ledger Forensics Stuck-Funds board. Pure read."""
    import os as _os

    from sqlalchemy import func

    from agentvault_registry.models import ExchangeGatewayCredit, GatewayFloatKeeperConfig

    cfg = (
        await db.execute(
            select(GatewayFloatKeeperConfig).where(GatewayFloatKeeperConfig.id == "singleton")
        )
    ).scalar_one_or_none()

    rows = (
        await db.execute(
            select(
                ExchangeGatewayCredit.status,
                func.count(ExchangeGatewayCredit.id),
                func.coalesce(func.sum(ExchangeGatewayCredit.amount), 0),
            ).group_by(ExchangeGatewayCredit.status)
        )
    ).all()
    by_status = {str(s): {"count": int(c), "sum": float(t)} for (s, c, t) in rows}

    dust_n, dust_sum = (
        await db.execute(
            select(func.count(ExchangeGatewayCredit.id), func.coalesce(func.sum(ExchangeGatewayCredit.amount), 0)).where(
                ExchangeGatewayCredit.status == "pending",
                ExchangeGatewayCredit.amount < svc.REPAT_DUST,
            )
        )
    ).one()
    deliv_n, deliv_sum = (
        await db.execute(
            select(func.count(ExchangeGatewayCredit.id), func.coalesce(func.sum(ExchangeGatewayCredit.amount), 0)).where(
                ExchangeGatewayCredit.status == "pending",
                ExchangeGatewayCredit.amount >= svc.REPAT_DUST,
            )
        )
    ).one()

    gw_balance = None
    try:
        gw_balance = float(await svc.mover.agent_balance(svc.GATEWAY_DID))
    except Exception:  # noqa: BLE001 — balance read is best-effort telemetry
        gw_balance = None

    env_enabled = (_os.getenv("GATEWAY_KEEPER_ENABLED", "false") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    # §VENUEGW — read the currency from the frame, never by parsing the DID. The
    # scoped shape still ends in the currency so this would have kept working, which
    # is precisely why it was worth removing: a naming choice should not be load-bearing.
    currency = (_os.getenv("FRAME_CURRENCY", "AVT") or "AVT").strip().upper()

    return {
        "enabled": bool(cfg.enabled) if cfg else False,
        "env_enabled": env_enabled,
        "buffer": float(cfg.buffer) if cfg else 0.0,
        "deadband_pct": float(cfg.deadband_pct) if cfg else None,
        "max_move_per_cycle": float(cfg.max_move_per_cycle) if cfg else None,
        "source": cfg.source if cfg else None,
        "check_interval_sec": cfg.check_interval_sec if cfg else None,
        "operator_mode": cfg.operator_mode if cfg else None,
        "updated_at": cfg.updated_at.isoformat() if (cfg and cfg.updated_at) else None,
        "updated_by": cfg.updated_by if cfg else None,
        "gateway_did": svc.GATEWAY_DID,
        "currency": currency,
        "gateway_balance": gw_balance,
        # §REPATLANE (V0603): the keeper's own figure (every credit still owed, of every size; 'unresolved' apart)
        "outstanding_obligation": sum(by_status.get(s, {}).get("sum", 0.0) for s in svc.REPAT_OWED_STATUSES),
        "repat_dust": float(svc.REPAT_DUST),
        "credits": {
            "by_status": by_status,
            "dust": {"count": int(dust_n), "sum": float(dust_sum)},
            "abandoned": by_status.get("abandoned", {"count": 0, "sum": 0.0}),
            "deliverable_pending": {"count": int(deliv_n), "sum": float(deliv_sum)},
            # §REPATLANE (V0603): payouts that may have moved and are never sent again on their own (a ledger read
            # releases each), and sends whose answer is being applied
            "unresolved": by_status.get(svc.REPAT_UNRESOLVED, {"count": 0, "sum": 0.0}),
            "in_flight": {
                "count": sum(by_status.get(s, {}).get("count", 0) for s in (svc.REPAT_SENDING, svc.REPAT_BATCHED)),
                "sum": sum(by_status.get(s, {}).get("sum", 0.0) for s in (svc.REPAT_SENDING, svc.REPAT_BATCHED)),
            },
        },
    }


@router.get("/admin/participants", summary="Compliance registry (admin)")
async def admin_participants(
    request: Request,
    status: Optional[str] = Query(default=None, pattern="^(verified|pending|blocked)$"),
    _admin=Security(require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select

    from agentvault_registry.models import ExchangeParticipant

    q = select(ExchangeParticipant).order_by(ExchangeParticipant.first_seen.desc()).limit(500)
    if status:
        q = q.where(ExchangeParticipant.compliance_status == status)
    rows = (await db.execute(q)).scalars().all()
    return {
        "participants": [
            {
                "agent_did": p.agent_did,
                "home_registry": p.home_registry,
                "owner_dev_ref": p.owner_dev_ref,
                "owner_dev_name": p.owner_dev_name,
                "owner_dev_contact": p.owner_dev_contact,
                "verification_source": p.verification_source,
                "compliance_status": p.compliance_status,
                "first_seen": p.first_seen.isoformat() if p.first_seen else None,
                "verified_at": p.verified_at.isoformat() if p.verified_at else None,
            }
            for p in rows
        ],
        "count": len(rows),
    }


# ── §V0064 federation tickers (2026-06-13) ──────────────────────────────
# The landing/MissionControl ticker needs EVERY live venue in the federation
# (parent frame's + own), but browsers can't cross-origin the mainframes (the
# §V-1r lesson — that's why the event ledger runs same-origin WS proxies).
# So the REGISTRY aggregates server-side: probe the three mainframe venues
# (public URLs, fixed for this deployment; override via env), cache 15s
# per-worker. Public endpoint — it serves guest landings.
import json
import os as _os
import asyncio
import time as _time
from datetime import datetime, timezone

import httpx

_FED_TICKER_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_FED_TICKER_TTL = 15.0


def _is_cluster_mainframe_slug(slug: str) -> bool:
    """True only for THIS cluster's three mainframes, by exact name — never by what the
    deployment happens to configure (§BATCH9; the old EventStore-B/C signal is gone)."""
    return slug in ("", "registry-a", "frame-b", "frame-c")


def _card_public_url(card: Any, base_url: Optional[str]) -> str:
    """A peer's browser-reachable base: the cached card's identity.public_url, else its
    federation base_url with the mTLS gateway port stripped (the convention network_listings
    already relies on)."""
    pub = ""
    if isinstance(card, dict):
        ident = card.get("identity") or {}
        pub = str(ident.get("public_url") or ident.get("registry_url") or "").strip()
    if not pub and base_url:
        import re as _re_pu
        pub = _re_pu.sub(r":\d+$", "", str(base_url).strip().rstrip("/"))
    return pub.rstrip("/")


async def _venue_probe_urls_federated(db: AsyncSession) -> Dict[str, str]:
    """The honest venue list for a registry that is NOT one of the cluster's mainframes and
    carries no explicit EXCHANGE_TICKER_SOURCES_JSON: itself, plus every ACTIVE peer whose
    cached registry card advertises `fees.exchange.enabled` — probed at the card's public url.
    A network where nothing lists anything yields only SELF, and federation_tickers then
    renders nothing, which is what an empty market looks like (§BATCH9)."""
    urls = _venue_probe_urls()
    raw = (_os.getenv("EXCHANGE_TICKER_SOURCES_JSON", "") or "").strip()
    import re as _re_vf
    _slug = _re_vf.sub(r"[^a-z0-9]+", "-", (_os.getenv("REGISTRY_NAME", "") or "").lower()).strip("-")
    if raw or _is_cluster_mainframe_slug(_slug):
        return urls
    try:
        from sqlalchemy import select as _select
        from agentvault_registry.models import PeerRegistry
        rows = (await db.execute(_select(PeerRegistry).where(PeerRegistry.status == "ACTIVE"))).scalars().all()
        for p in rows:
            card = getattr(p, "cached_registry_card", None)
            if isinstance(card, str):
                try:
                    card = json.loads(card)
                except Exception:
                    card = None
            if not isinstance(card, dict):
                continue
            ex = (card.get("fees") or {}).get("exchange") or {}
            if not bool(ex.get("enabled")):
                continue
            pub = _card_public_url(card, getattr(p, "base_url", None))
            name = str(getattr(p, "name", "") or "").strip()
            if pub and name and name not in urls:
                urls[name] = pub
    except Exception as e:  # noqa: BLE001 — a failed peer read leaves SELF, never the cluster map
        logger.warning("[AGORA] federated venue resolution failed, SELF only: %s", e)
    return urls


def _venue_probe_urls() -> Dict[str, str]:
    urls: Dict[str, str] = {}
    raw = _os.getenv("EXCHANGE_TICKER_SOURCES_JSON", "").strip()
    if raw:
        try:
            m = json.loads(raw)
            if isinstance(m, dict) and m:
                urls = {str(k): str(v).rstrip("/") for k, v in m.items()}
        except Exception:
            logger.warning("[AGORA] bad EXCHANGE_TICKER_SOURCES_JSON — using defaults")
    if not urls:
        # §HETZNERLOCK-13 (2026-07-29) — this default used to be UNCONDITIONAL, so ANY
        # registry with EXCHANGE_TICKER_SOURCES_JSON unset reached out over the public
        # internet and rendered THE CLUSTER's live markets as "the federation". On a
        # sovereign frame handed to an outside party that is wrong twice over: it
        # advertises another organisation's order books as if they were federated, and
        # it makes uninvited outbound calls to theprotocol.cloud. It never consulted
        # peer_registries at all.
        #
        # The cluster map is now only the default FOR THE CLUSTER's own mainframes.
        # Everyone else defaults to SELF ONLY, which is the honest answer for a frame
        # whose peers do not run venues. Explicit EXCHANGE_TICKER_SOURCES_JSON still
        # wins, so federating a frame into the triangle stays a one-env-var change.
        # "Part of THIS cluster" = the three mainframes, their cloud-ops (which ARE
        # federated into the triangle and legitimately show its venues), and the
        # sandbox replicas. Everything else is somebody else's sovereign frame.
        import re as _re_vp
        _slug = _re_vp.sub(r"[^a-z0-9]+", "-", (_os.getenv("REGISTRY_NAME", "") or "").lower()).strip("-")
        # §HETZNERLOCK-18 (2026-07-30) — SAME SIGNAL AS registry-config.multi_frame.
        # My first cut keyed this on `_slug.startswith("cloud-op-")`, which is the exact
        # mistake the FE made with `is_federated_operator`: it cannot tell a CLUSTER op
        # from an op under somebody else's sovereign frame. op-demo (slug
        # cloud-op-op-demo) matched, so it kept probing and displaying registry-a /
        # frame-b / frame-c. Ask the deployment, not the name: a Frame B/C EventStore is
        # configured here iff those frames exist in THIS deployment.
        # §BATCH9 (2026-09-06, his bug report "agora strips on landingpage of juice is registry-a") —
        # the EventStore-B/C shortcut was WRONG for any deployment that names a PEER's EventStore
        # as its "B": the frame template renders FT_REG_EVENT_STORE_B_URL for the FX peer, so
        # JUICE (EVENT_STORE_B_URL=https://brrr-es…) rendered THE CLUSTER's markets on its own
        # landing page. Measured 2026-09-06: every production node carries
        # EXCHANGE_TICKER_SOURCES_JSON explicitly, so the shortcut was load-bearing for nobody.
        # The cluster map now applies to the three cluster mainframes BY NAME only; everyone
        # else is answered by _venue_probe_urls_federated(): SELF + the venues its own
        # peer_registries advertise — EMPTY when nothing on the network lists anything.
        _in_cluster = _is_cluster_mainframe_slug(_slug)
        if _in_cluster:
            urls = {
                "registry-a": "https://api.theprotocol.cloud",
                "frame-b": "https://frame-b.theprotocol.cloud",
                "frame-c": "https://frame-c.theprotocol.cloud",
            }
        else:
            urls = {(_slug or "local"): "http://localhost:8000"}
    # §2026-06-18 — cloud-op SELF-INCLUDE: a cloud-op venue isn't in the mainframe
    # map, so it probes ITSELF (localhost) → its own listings render on its own
    # /stocks as a LOCAL venue (Desk button + live data), consistent with how the
    # mainframes self-include (they're already in the map by name). Guarded to
    # cloud-ops + EXCHANGE_ENABLED → mainframes unchanged (no double-probe); a
    # non-venue op adds nothing (federation-tickers skips empty listings). The FE
    # auto-detects localVenue by symbol match, so the venue name is irrelevant.
    try:
        if (_os.getenv("REGISTRY_NAME", "") or "").startswith("cloud-op-") and \
           (_os.getenv("EXCHANGE_ENABLED", "false") or "").strip().lower() in ("1", "true", "yes", "on"):
            self_name = (_os.getenv("REGISTRY_FEDERATION_NAME") or _os.getenv("REGISTRY_NAME") or "").strip()
            if self_name and self_name not in urls:
                urls[self_name] = "http://localhost:8000"
    except Exception:
        pass

    # §HETZNERLOCK-15 (2026-07-29) — a mainframe's entry in the map above is its PUBLIC url,
    # so registry-a probed ITSELF over the public internet: nginx, TLS, the whole round trip,
    # against this aggregator's 4.0s budget. Measured 3.05s — inside the budget but close, so
    # under load it timed out, yielded no listings, and `if not ls: continue` silently DROPPED
    # registry-a from its own federation ticker list. Observed flapping between 2 and 3 venues
    # on consecutive polls. Point our own entry at localhost, exactly as cloud-ops already do:
    # a server-side aggregation has no business leaving the box to read its own database.
    try:
        import re as _re_vp2
        _self_slug = _re_vp2.sub(r"[^a-z0-9]+", "-", (_os.getenv("REGISTRY_NAME", "") or "").lower()).strip("-")
        for _k in list(urls.keys()):
            if _re_vp2.sub(r"[^a-z0-9]+", "-", _k.lower()).strip("-") == _self_slug and _self_slug:
                urls[_k] = "http://localhost:8000"
    except Exception:
        pass
    return urls


@router.get("/federation-tickers", summary="All live AGORA markets in the federation (public, cached)")
async def federation_tickers(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Every live AGORA market in the federation, read from each venue concurrently (a venue that does not answer
    within its budget is left out). Cached for 15 seconds. Public, no auth.

    \f
    Every live AGORA market in the federation.

    §BRIDGE R2b (2026-08-19) — THE FAN-OUT IS CONCURRENT.

    Measured before this change on frame-c: 7.3s / 7.9s / 8.2s (11.5s cold),
    against 0.05-0.18s for every other call the landing page makes. The cause
    was not the amount of work, it was its SHAPE: one sequential loop over the
    venues, and inside each venue up to eight further SEQUENTIAL candle calls
    plus a trades call. N venues x 9 serial round trips, each with a 4s budget.

    Every one of those requests is independent, so they now run together. The
    wall clock becomes the SLOWEST single probe instead of the SUM of all of
    them. Nothing else changes: same output shape, same 4s per-request budget, a
    dark venue is still invisible by design, and `gather` preserves input order
    so the venue list stays stable.

    NOTE ON THE CACHE (deliberately left alone): `_FED_TICKER_CACHE` is a module
    global, i.e. PER GUNICORN WORKER. This registry runs 32 workers, so a 15s TTL
    is 15s per worker, not per registry, and any worker that has not served this
    route recently pays full price. That is why a browser sees fast/slow/fast on
    consecutive loads. Making it shared would mean putting it in Redis, which is
    a bigger change to a public endpoint than this refinement should carry —
    filed rather than smuggled in.
    """
    now = _time.monotonic()
    if _FED_TICKER_CACHE["data"] is not None and now - _FED_TICKER_CACHE["ts"] < _FED_TICKER_TTL:
        return _FED_TICKER_CACHE["data"]

    async def _one_venue(c: httpx.AsyncClient, name: str, base: str):
        """One venue, probed concurrently within itself. Returns None if dark."""
        try:
            r = await peer_request(c, "GET", base, "/listings")
            if r.status_code != 200:
                return None
            raw_listings = r.json().get("listings") or []
            ls = [
                {
                    "symbol": x.get("symbol"),
                    "display_name": x.get("display_name"),
                    "organization_id": x.get("organization_id"),
                    "last": (x.get("stats") or {}).get("last"),
                    # 🔴 THE ASK, WHICH THIS DROPPED. A buyer must MEET the ask;
                    # `last` is what somebody else already paid. Without this a
                    # foreign listing was always bought at its last trade, so any
                    # venue with a spread never filled — measured 2026-08-26:
                    # FLUX last 21.38 vs ask 23.00, BSEA 27.06 vs 28.75, both
                    # relayed and neither filled. Every venue already publishes
                    # stats.best_ask on /exchange/listings; this only forwards it.
                    "best_ask": (x.get("stats") or {}).get("best_ask"),
                    "best_bid": (x.get("stats") or {}).get("best_bid"),
                    "change_24h_pct": (x.get("stats") or {}).get("change_24h_pct"),
                    "market_cap": (x.get("stats") or {}).get("market_cap"),
                    "volume_24h_notional": (x.get("stats") or {}).get("volume_24h_notional"),
                    "trades_24h": (x.get("stats") or {}).get("trades_24h"),
                    "ipo_remaining": (x.get("stats") or {}).get("ipo_remaining"),
                    "ipo_price": x.get("ipo_price"),
                    "status": x.get("status"),
                    "currency": x.get("currency"),
                }
                for x in raw_listings
                if x.get("approved")
            ]
            if not ls:
                return None

            # sparklines (1h closes) — server-side so the Stocks view never
            # cross-origins a foreign venue; bounded + cached with the rest.
            spark_targets = ls[:8]

            async def _spark(li):
                try:
                    cr = await peer_request(c, "GET", base, f"/listings/{li['symbol']}/candles",
                                            params={"tf": "1h", "limit": 24})
                    if cr.status_code == 200:
                        li["spark"] = [float(k["c"]) for k in (cr.json().get("candles") or [])][-24:]
                except Exception:
                    pass

            async def _trades():
                try:
                    # the marquee feed: recent prints from the venue's most active book
                    top = max(
                        raw_listings,
                        key=lambda x: float((x.get("stats") or {}).get("volume_24h_notional") or 0),
                    )
                    tr = await peer_request(c, "GET", base, f"/listings/{top['symbol']}/trades", params={"limit": 8})
                    if tr.status_code == 200:
                        return [
                            {"symbol": top["symbol"], "price": t.get("price"), "qty": t.get("qty"), "at": t.get("at")}
                            for t in (tr.json().get("trades") or [])
                        ]
                except Exception:
                    pass
                return []

            results = await asyncio.gather(
                *[_spark(li) for li in spark_targets], _trades(), return_exceptions=True
            )
            trades = results[-1] if results and not isinstance(results[-1], BaseException) else []
            return {"venue": name, "currency": ls[0]["currency"], "listings": ls, "trades": trades}
        except Exception:
            return None  # dark/unreachable venue — invisible by design

    probes = list((await _venue_probe_urls_federated(db)).items())   # §BATCH9: SELF + own federation
    # Bounded pool: venues x their sparkline calls can be ~120 requests in flight
    # on a wide federation, and an unbounded client would happily try all of them.
    limits = httpx.Limits(max_connections=32, max_keepalive_connections=16)
    async with httpx.AsyncClient(timeout=4.0, verify=True, limits=limits) as c:
        settled = await asyncio.gather(
            *[_one_venue(c, name, base) for name, base in probes], return_exceptions=True
        )
    venues = [v for v in settled if v and not isinstance(v, BaseException)]

    data = {"venues": venues, "fetched_at": datetime.now(timezone.utc).isoformat()}
    _FED_TICKER_CACHE["ts"] = now
    _FED_TICKER_CACHE["data"] = data
    return data


@router.get("/network-listings", summary="Network-wide AGORA catalog (local ∪ federated AGORA cards)")
@limiter.limit("300/minute")
async def network_listings(request: Request, db: AsyncSession = Depends(get_db)):
    """Local union: THIS market's approved listings + every cached peer AGORA card
    (federated_stock_cards). NO live cross-frame probe → fast + offline-tolerant.
    Catalog only (no live prices); each entry carries `origin` (source registry)
    + `is_local`. To trade a remote listing, route via the owning market's Passport.
    Degrades to the local catalog if the federated cache is empty/absent."""
    from agentvault_registry.models import FederatedStockCard, PeerRegistry

    self_name = _os.getenv("REGISTRY_FEDERATION_NAME") or _os.getenv("REGISTRY_NAME") or "self"
    out: List[Dict[str, Any]] = []

    # Venue deep-link: federation base_url is the mTLS gateway (:8443, not browser-
    # navigable). Strip the port → the venue's public UI host (:443). FE appends
    # /ui#/stocks so a remote card can deep-link to the owning venue's own screener
    # (live price/book live there; the federated card is catalog-only by design).
    def _venue_public_url(base_url: Optional[str]) -> Optional[str]:
        try:
            from urllib.parse import urlsplit, urlunsplit
            s = urlsplit(base_url or "")
            if not s.hostname:
                return None
            return urlunsplit((s.scheme or "https", s.hostname, "", "", ""))
        except Exception:
            return None
    try:
        peer_urls = {p.name: _venue_public_url(p.base_url)
                     for p in (await db.execute(select(PeerRegistry))).scalars().all()}
    except Exception:
        peer_urls = {}

    local = (await db.execute(
        select(ExchangeListing).where(ExchangeListing.approved.is_(True))
    )).scalars().all()
    for l in local:
        out.append({
            "symbol": l.symbol, "display_name": l.display_name,
            "organization_id": l.organization_id, "currency": l.currency,
            "total_shares": l.total_shares, "ipo_price": str(l.ipo_price),
            "fee_bps": l.fee_bps, "status": l.status,
            "created_at": l.created_at.isoformat() if l.created_at else None,
            "origin": self_name, "is_local": True, "signature_verified": True,
        })

    sources: List[Dict[str, Any]] = []
    try:
        rows = (await db.execute(select(FederatedStockCard))).scalars().all()
    except Exception:
        rows = []  # table absent (pre-migration) → degrade to local-only
    for r in rows:
        listings = r.listings_json if isinstance(r.listings_json, list) else []
        v_url = peer_urls.get(r.source_registry_name)
        sources.append({
            "registry": r.source_registry_name, "spiffe_id": r.source_spiffe_id,
            "currency": r.currency, "count": len(listings),
            "signature_verified": r.signature_verified,
            "venue_url": v_url,
            "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
        })
        mkt = r.market_json if isinstance(getattr(r, "market_json", None), dict) else {}
        for c in listings:
            if not isinstance(c, dict):
                continue
            e = dict(c)
            e["origin"] = r.source_registry_name
            e["is_local"] = False
            e["signature_verified"] = r.signature_verified
            e["venue_url"] = v_url
            m = mkt.get(c.get("symbol"))  # §2026-06-25 coarse federated market block (last + spark[≤24])
            if isinstance(m, dict):
                e["market"] = m
            out.append(e)

    return {
        "listings": out,
        "sources": sources,
        "count": len(out),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/equity-map", summary="LOCAL org→listing map (public): AGORA chips on agent surfaces")
async def equity_map(request: Request, db: AsyncSession = Depends(get_db)):
    """{organization_id: {symbol, currency, last, status}} for THIS market's
    approved listings. Lets /my-agents + Discovery chip an agent whose org is
    listed (Agent.organization_id, f040) with one cheap cached call."""
    rows = (
        await db.execute(select(ExchangeListing).where(ExchangeListing.approved.is_(True)))
    ).scalars().all()
    out = {}
    lasts = await svc.last_prices(db, [l.id for l in rows])   # §COCKPITDESK (2026-10-15): one read, not one per listing
    for l in rows:
        last = lasts.get(l.id)
        out[str(l.organization_id)] = {
            "symbol": l.symbol,
            "currency": l.currency,
            "status": l.status,
            "last": str(last) if last is not None else None,
            "agent_dids": [],
        }
    if out:
        # member agents per listed org → lets MyAgents/Discovery chip an agent
        # by plain DID join, no public-schema widening (cap is a sanity bound).
        members = (
            await db.execute(
                select(Agent.did, Agent.organization_id)
                .where(Agent.organization_id.in_(list(out.keys())))
                .limit(2000)
            )
        ).all()
        for did, org_id in members:
            entry = out.get(str(org_id))
            if entry is not None and len(entry["agent_dids"]) < 500:
                entry["agent_dids"].append(did)
    return {"orgs": out, "count": len(out)}


@router.get("/admin/overview", summary="Market cockpit aggregate (admin): the AGORA admin view")
async def admin_overview(
    request: Request,
    _admin=Security(require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """One call powering the AdminExchange hero/stat strip: listing + order +
    trade + participant counts, settlement drain health, escrow balance, halt
    state. Heavy invariant math stays on GET /admin/invariant (button-driven)."""
    import os
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, select

    from agentvault_registry.models import (
        ExchangeDividend,
        ExchangeListing,
        ExchangeOrder,
        ExchangeParticipant,
        ExchangeTrade,
    )

    def _count_by(rows):
        return {str(k): int(v) for k, v in rows}

    listings_by = _count_by(
        (await db.execute(select(ExchangeListing.status, func.count()).group_by(ExchangeListing.status))).all()
    )
    orders_by = _count_by(
        (await db.execute(select(ExchangeOrder.status, func.count()).group_by(ExchangeOrder.status))).all()
    )
    day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    trades_total = (await db.execute(select(func.count(ExchangeTrade.id)))).scalar_one()
    t24 = (
        await db.execute(
            select(func.count(ExchangeTrade.id), func.coalesce(func.sum(ExchangeTrade.notional), 0)).where(
                ExchangeTrade.created_at >= day_ago
            )
        )
    ).one()
    pending = (
        await db.execute(
            select(func.count(ExchangeTrade.id), func.min(ExchangeTrade.created_at)).where(
                ExchangeTrade.settle_status == "pending_settlement"
            )
        )
    ).one()
    participants = (
        await db.execute(
            select(ExchangeParticipant.verification_source, func.count()).group_by(
                ExchangeParticipant.verification_source
            )
        )
    ).all()
    div_pending = (
        await db.execute(select(func.count(ExchangeDividend.id)).where(ExchangeDividend.status != "paid"))
    ).scalar_one()
    halted = await svc.get_flag(db, "global_halt")
    oldest = pending[1]
    lag_s = (datetime.now(timezone.utc) - oldest).total_seconds() if oldest else 0.0
    try:
        escrow = str(await svc.mover.escrow_balance())
    except Exception as e:
        escrow = None
        logger.warning(f"[AGORA-admin] escrow read failed for overview: {e}")
    return {
        "venue_enabled": svc.EXCHANGE_ENABLED,
        "passport_enabled": os.getenv("EXCHANGE_PASSPORT_ENABLED", "false").lower() == "true",
        "global_halt": (halted or "false") == "true",
        "currency": os.getenv("FRAME_CURRENCY", "AVT"),
        "listings_by_status": listings_by,
        "orders_by_status": orders_by,
        "trades_total": int(trades_total),
        "trades_24h": int(t24[0]),
        "notional_24h": str(t24[1]),
        "settlement": {"pending": int(pending[0]), "oldest_lag_seconds": round(lag_s, 1)},
        "participants_by_source": {str(k): int(v) for k, v in participants},
        "dividends_unpaid": int(div_pending),
        "escrow_balance": escrow,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════
# AGORA PASSPORT — home-side outbound relay (agent → foreign venue)
# ═══════════════════════════════════════════════════════════════════════
import os as _os

from pydantic import BaseModel as _BM


class PassportOrderRequest(_BM):
    venue_registry: str = Field(..., max_length=128, description="venue registry name (peer_registries.name)")
    listing: str = Field(..., max_length=64)
    qty: int = Field(..., gt=0)
    price: str = Field(..., description="decimal string (limit only)")
    side: str = Field("buy", pattern="^(buy|sell)$", description="buy (fund gateway upfront) or sell (proceeds repatriate home); defaults buy for back-compat")
    fx_buffer_pct: int = Field(3, ge=0, le=15, description="over-send buffer for cross-currency funding")


@router.post("/passport/orders", summary="Place an order on a FOREIGN AGORA market (Passport)")
@limiter.limit("300/minute")
async def passport_place_order(
    body: PassportOrderRequest,
    request: Request,
    current_agent: Agent = Security(require_agent_permission("exchange.trade")),
    db: AsyncSession = Depends(get_db),
):
    """①  relay the order to the foreign AGORA market over federation mTLS (home-vouched)
    ②  fund that market's gateway via /teg/send (auto-FX cross-frame)
    ③  notify that market; its sweeper opens the order on arrival."""
    if _os.getenv("EXCHANGE_PASSPORT_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=503, detail="AGORA Passport disabled on this registry")
    from agentvault_registry.services import exchange_passport as passport

    # Build + sign OUR dev's card and push it with the relay (consent-bound:
    # the dev's own agent initiated; disclosure row written here at home).
    from agentvault_registry.routers.dev_card import build_signed_devcard

    # IRONKEY L2 spend gate (pre-relay, Δ-safe): passport BUY notional (qty×price) is
    # exposure on a FOREIGN venue → same_registry=False.
    if body.side == "buy":
        try:
            _pn = Decimal(str(body.qty)) * Decimal(str(body.price))
        except (InvalidOperation, ValueError, TypeError):
            _pn = None
        if _pn is not None:
            await enforce_agent_spend(db, current_agent.did, _pn, same_registry=False)

    dev_card_env = await build_signed_devcard(db, current_agent, requested_by=f"venue:{body.venue_registry}")
    try:
        code, venue = await passport.peer_request(
            db, body.venue_registry, "POST", "/api/v1/federation/agora-order",
            {"agent_did": current_agent.did, "listing": body.listing, "side": body.side,
             "qty": body.qty, "price": body.price, "dev_card": dev_card_env},
        )
    except svc.ExchangeError as e:
        raise _err(e)
    if code != 200:
        raise HTTPException(status_code=502, detail=f"the foreign AGORA market rejected the order relay (HTTP {code}): {str(venue)[:200]}")

    if body.side == "sell":
        # §2026-06-20 PASSPORT SELL (bidirectional): NO home-side funding — the agent sold
        # shares it already holds on the venue; the venue opened + matched immediately and
        # any proceeds repatriate home automatically via the gateway-credit rail
        # (settle_pending_trades → _add_gateway_credit → repat worker, reverse FX). Relay
        # the venue result and return; the buy-only funding path below is skipped.
        return {
            "order_id": venue.get("order_id"),
            "venue_registry": body.venue_registry,
            "side": "sell",
            "status": venue.get("status", "open"),
            "remaining": venue.get("remaining"),
            "note": "passport sell — proceeds repatriate home automatically on fill (reverse FX via gateway credit)",
        }

    required = Decimal(str(venue["required_amount"]))
    venue_ccy = venue.get("currency", "?")
    gateway = venue["gateway_did"]
    home_ccy = _os.getenv("FRAME_CURRENCY", "AVT")

    # cross-currency: oversend by buffer; same-ccy exact. §2026-06-15 — price the
    # home→venue leg off the ALL-PAIRS triangle /fx/rates (the singular /fx/rate is
    # AVT/BVT-only and 502'd JDAY funding once Frame-B relabelled AVT→JDAY). Each
    # pair = {a,b,a_per_b,b_per_a}; "home per 1 venue" = a_per_b when a==home else b_per_a.
    # 🔴 §VENUEGW 2026-08-26 — the buffer is NOT only an FX concern. /teg/send charges the
    # transfer fee on the way, so sending EXACTLY `required` delivers less than the order
    # needs and the venue's sweeper — which only opens orders the gateway float covers —
    # never opens it. Measured on op-doha: required 12.00 BVT, gateway credited 11.94, order
    # stuck in 'funding'. Cross-currency never showed it because the FX buffer happened to
    # absorb the fee. Invisible until now because a SAME-currency passport buy needs a venue
    # that shares the buyer's currency and is not the buyer's own registry — which is exactly
    # what per-venue gateways just made possible (a frame's cloud-ops share its currency).
    # Overage is not lost: it rests in the gateway float and repatriates on the existing rail.
    send_amount = svc.q18(required * (Decimal(100 + body.fx_buffer_pct) / Decimal(100)))
    if venue_ccy != home_ccy:
        rate = Decimal("0")
        try:
            import httpx as _hx

            async with _hx.AsyncClient() as c:
                rr = await c.get("http://127.0.0.1:8000/api/v1/teg/fx/rates", timeout=8.0)
            for _pr in ((rr.json() or {}).get("pairs") or []):
                _a = str(_pr.get("a", "")).upper()
                _b = str(_pr.get("b", "")).upper()
                if {_a, _b} == {home_ccy.upper(), venue_ccy.upper()}:
                    rate = Decimal(str((_pr.get("a_per_b") if _a == home_ccy.upper() else _pr.get("b_per_a")) or "0"))
                    break
        except Exception:
            pass
        if rate <= 0:
            raise HTTPException(status_code=502, detail=f"FX rate unavailable for cross-currency funding ({home_ccy}->{venue_ccy})")
        send_amount = svc.q18(required * rate * (Decimal(100 + body.fx_buffer_pct) / Decimal(100)))

    # §2026-06-15 COLD-START FIX: cache the venue's frame-specific gateway card
    # locally BEFORE the cross-frame funding send so the send-resolver can route to
    # it. Without this the FIRST passport order to a venue 409s until periodic
    # federation sync (≤300s). Separate session + the proven federated-card upsert
    # path; ANY failure falls through to the pre-existing self-healing behavior.
    _gw_card = venue.get("gateway_card") if isinstance(venue, dict) else None
    if _gw_card:
        try:
            from agentvault_registry.database import AsyncSessionLocal as _ASL
            from agentvault_registry.crud import crud_peer_registry as _cpr
            from agentvault_registry.models import AgentCard as _AC
            _peer_svid = ((_gw_card.get("card_data") or {}).get("federation_metadata") or {}).get("spiffe_id") or ""
            async with _ASL() as _db2:
                _exists = (
                    await _db2.execute(select(_AC.id).where(_AC.agent_did == gateway))
                ).scalar_one_or_none()
                if _exists is None:
                    await _cpr.upsert_agent_cards_from_peer(_db2, _peer_svid, _gw_card)
                    # 🔴 §VENUEGW 2026-08-26 — upsert_agent_cards_from_peer does NOT commit;
                    # it is written for callers that own the transaction. This one opened its
                    # own session and never did, so the entire cold-start cache was discarded
                    # on close WHILE LOGGING SUCCESS. It went unseen for two months because the
                    # gateway DID was frame-wide and already federated by the periodic sync —
                    # there was never a genuine cold start to fail. Giving each venue its own
                    # gateway made every cloud-op a first buy, and every one 409'd
                    # "receiver unknown". Commit, then say only what is true.
                    await _db2.commit()
                    _cached = (
                        await _db2.execute(select(_AC.id).where(_AC.agent_did == gateway))
                    ).scalar_one_or_none()
                    if _cached is None:
                        logger.warning(
                            "[AGORA-passport] gateway pre-cache did NOT persist for %s — funding "
                            "will 409 until federation sync catches up", gateway)
                    else:
                        logger.info("[AGORA-passport] cached venue gateway %s before funding (cold-start fix)", gateway)
        except Exception as _pce:
            logger.warning("[AGORA-passport] gateway pre-cache failed (relying on periodic sync): %s", _pce)

    # fund the gateway AS the calling agent via our own smart-send surface
    auth_header = request.headers.get("authorization", "")
    # §SUBAGENT-LIABILITY-V3 — forward the anchored birth token so a WALLETLESS hand's passport buy
    # funds from its PRINCIPAL's purse (smart_send → inner rail → resolve_spend_purse_agent). Byte-inert
    # when absent.
    _cap_header = request.headers.get("x-capability-token", "")
    _fund_headers = {"Authorization": auth_header, "Content-Type": "application/json"}
    if _cap_header:
        _fund_headers["X-Capability-Token"] = _cap_header
    import httpx as _hx2

    try:
        async with _hx2.AsyncClient() as c:
            sr = await c.post(
                "http://127.0.0.1:8000/api/v1/teg/send",
                json={"receiver_did": gateway, "amount": str(send_amount),
                      "message": f"agdep:{venue['order_id']}"},
                headers=_fund_headers,
                timeout=60.0,
            )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"funding send failed: {e}")
    if sr.status_code not in (200, 201, 202):
        # Insufficient balance (the calling agent can't cover the funding leg) is a
        # client/business condition → surface a clean 402, NOT an alarming 502. The
        # downstream FX/cross-TEG path now returns 402 + "Insufficient balance…" for this.
        _sr_txt = (sr.text or "")
        if sr.status_code == 402 or "insufficient balance" in _sr_txt.lower():
            raise HTTPException(status_code=402,
                                detail=f"passport funding: insufficient balance — {_sr_txt[:200]}")
        raise HTTPException(status_code=502, detail=f"funding send HTTP {sr.status_code}: {_sr_txt[:200]}")
    send_env = sr.json()

    try:
        await passport.peer_request(
            db, body.venue_registry, "POST", "/api/v1/federation/agora-order-funded",
            {"order_id": venue["order_id"], "sent_amount": str(send_amount),
             "send_tx_id": str(send_env.get("transfer_id") or send_env.get("transaction_id") or "")},
        )
    except svc.ExchangeError:
        pass  # informational only

    return {
        "order_id": venue["order_id"],
        "venue_registry": body.venue_registry,
        "required_amount": str(required),
        "required_currency": venue_ccy,
        "sent_amount": str(send_amount),
        "sent_currency": home_ccy,
        "send_envelope": send_env,
        "status": "funding",
        "note": "venue sweeper opens the order when the deposit lands (cross-frame FX settles in seconds)",
    }


class PassportOrderStatusRequest(_BM):
    venue_registry: str = Field(..., max_length=128)
    order_ids: list[str] = Field(..., min_length=1, max_length=50)


@router.post("/passport/order-status", summary="Status of YOUR orders on a FOREIGN AGORA market (Passport, batched)")
@limiter.limit("300/minute")
async def passport_order_status(
    body: PassportOrderStatusRequest,
    request: Request,
    current_agent: Agent = Security(require_agent_permission("exchange.trade")),
    db: AsyncSession = Depends(get_db),
):
    """
    Read-only relay to a foreign AGORA market's order-status view, scoped to the calling agent: the market is asked
    about the caller, and no DID travels in the request. A passport buy's 200 means accepted, not filled; this is
    how the fill is learned. Needs an agent token with the `exchange.trade` permission.

    \f
    §PASSPORTSELL P1 (2026-08-22): read-only relay to the foreign market's federation
    order-status view, scoped BY CONSTRUCTION to the caller (the market is asked about
    current_agent.did; no DID travels in the request). This is the poller's truth
    source: a passport buy's 200 is acceptance, not a fill.
    """
    if _os.getenv("EXCHANGE_PASSPORT_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=503, detail="AGORA Passport disabled on this registry")
    from agentvault_registry.services import exchange_passport as passport

    try:
        code, venue = await passport.peer_request(
            db, body.venue_registry, "POST", "/api/v1/federation/agora-order-status",
            {"agent_did": current_agent.did, "order_ids": [str(o)[:64] for o in body.order_ids][:50]},
        )
    except svc.ExchangeError as e:
        raise _err(e)
    if code != 200:
        raise HTTPException(status_code=502, detail=f"the foreign AGORA market status relay failed (HTTP {code}): {str(venue)[:200]}")
    return venue


@router.get("/passport/portfolio", summary="YOUR holdings on a FOREIGN AGORA market (Passport)")
@limiter.limit("300/minute")
async def passport_portfolio(
    request: Request,
    venue_registry: str = Query(..., max_length=128),
    current_agent: Agent = Security(require_agent_permission("exchange.trade")),
    db: AsyncSession = Depends(get_db),
):
    """
    Read-only relay to a foreign AGORA market's holdings view (`venue_registry`), scoped to the calling agent: the
    source for rebuilding passport holdings after a restart. Needs an agent token with the `exchange.trade`
    permission.

    \f
    §PASSPORTSELL P1: read-only relay to the foreign market's federation holdings view
    (scoped to the caller). The restart-proof rebuild source for passport holdings.
    """
    if _os.getenv("EXCHANGE_PASSPORT_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=503, detail="AGORA Passport disabled on this registry")
    from agentvault_registry.services import exchange_passport as passport

    try:
        code, venue = await passport.peer_request(
            db, venue_registry, "POST", "/api/v1/federation/agora-portfolio",
            {"agent_did": current_agent.did},
        )
    except svc.ExchangeError as e:
        raise _err(e)
    if code != 200:
        raise HTTPException(status_code=502, detail=f"the foreign AGORA market holdings relay failed (HTTP {code}): {str(venue)[:200]}")
    return venue
