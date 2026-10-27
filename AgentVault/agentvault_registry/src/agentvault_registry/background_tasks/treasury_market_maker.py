"""§P2.1 Treasury market-maker — productized soft-peg, 2026-06-21.

A leader-elected worker that, for each opted-in listing, maintains a two-sided TREASURY
quote (bid via a BUY, ask via a SELL — both placed on-behalf-of the keyless treasury via
place_order, exactly as treasury_buyback does) around a reference price, within the listing
band, inventory-floored. This is the in-product version of the demand-director soft-peg:
liquidity without the sim. Δ-safe — every quote rides place_order (BUY escrows cash, SELL
locks shares) settling through the exref mover → Δ=0.

Gating (ALL must be on): env `EXCHANGE_ENABLED` AND `TREASURY_MM_ENABLED` (per-frame, default
false) AND the per-listing DB row `treasury_mm_config.enabled`. Leader-elected; config re-read
each cycle (live retune, no redeploy). Default OFF everywhere.

A resting quote is kept while it sits within half the spread of its target (re-quote only on
drift); a filled quote is replaced. The BUY-side escrow refund on cancel is async (settlement
batch C), so on a tight treasury a new bid may skip a cycle until the prior escrow returns.

THE REFERENCE (ref_mode "last", the default) IS THE MARKET'S PRICE, NOT THE MARKET MAKER'S OWN
PRINTS (§AGORASIM-2, 2026-09-22): the median of the recent trades with neither side the
treasury, else the median of all recent prints (`market_reference`). It used to be the last
print, and a fill of the market maker's own quote lands exactly one spread from the reference
while the drift tolerance is half a spread, so every such fill cancelled and re-posted BOTH
quotes around the market maker's own print, and the next taker hit the new quote. Measured on
the sandbox that day: every treasury quote placed was cancelled (958 of 958 on sbx-alpha in two
hours, 913 on sbx-beta), the quotes flipped between two levels 3% apart almost every cycle, and
ALFW walked from about 47 to 42.79 in seven minutes on the market maker's own buys.
"""
from __future__ import annotations

import logging
import os
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_UP, ROUND_DOWN
import statistics
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from sqlalchemy import select

from ..database import get_db_context
from ._worker_base import BackgroundWorker

logger = logging.getLogger(__name__)

try:  # §S4 pass 4 (2026-09-05): a quote or cancel that fails was a DEBUG line — a market maker dead for weeks looked quiet
    from prometheus_client import Counter as _MMCounter
    TREASURY_MM_OP_FAILED_TOTAL = _MMCounter("treasury_mm_op_failed_total", "Treasury market-maker quote/cancel operations that failed (they used to log at DEBUG)", labelnames=["op"])
except Exception:  # pragma: no cover
    TREASURY_MM_OP_FAILED_TOTAL = None


def _note_skip(op: str, symbol: str, exc: BaseException) -> None:
    """A failed quote/cancel leaves a WARNING and a counted reason. The loop goes on (a bad listing must not stop the
    others) — that part was right; the silence was not."""
    logger.warning("[treasury_mm] %s FAILED for %s: %s: %s", op, symbol or "?", exc.__class__.__name__, str(exc)[:120])
    try:
        if TREASURY_MM_OP_FAILED_TOTAL is not None:
            TREASURY_MM_OP_FAILED_TOTAL.labels(op=op).inc()
    except Exception:  # noqa: BLE001
        pass


def _truthy(v: str) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def _D(v, default="0") -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _to_tick(px: Decimal, tick: Decimal, rounding=ROUND_HALF_UP) -> Decimal:
    """Round px to the nearest multiple of the tick STEP. NOTE: a naive
    px.quantize(tick) rounds to the tick's DECIMAL PLACES (18 for a Numeric(36,18)
    tick), not the 0.01 step — which yields non-multiples place_order rejects."""
    if tick is None or tick <= 0:
        return px
    return (px / tick).to_integral_value(rounding=rounding) * tick


def quote_is_fresh(price: Optional[Decimal], target: Decimal, tol: Decimal) -> bool:
    """A resting quote at `price` still serves a `target` when it is within `tol` (a fraction) of it."""
    return price is not None and target > 0 and abs(price - target) / target <= tol


def _ref_knob(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def market_reference(prints: Iterable[Sequence[Any]], treasury_did: Optional[str],
                     n: Optional[int] = None, min_external: Optional[int] = None) -> Tuple[Optional[Decimal], str]:
    """(the price to quote around, where it came from) from recent prints, NEWEST FIRST, each (price, buyer, seller).

    The market's own price: the median of the last `n` prints with neither side the treasury ("market"). A thin book
    where the market maker is most of the tape has fewer than `min_external` of those; then the median of the last `n`
    prints of any kind ("all prints"): one fill of its own quote cannot move a median of several. Nothing: (None, "").
    Knobs TREASURY_MM_REF_TRADES (9) and TREASURY_MM_REF_MIN_EXTERNAL (3).
    """
    n = n or _ref_knob("TREASURY_MM_REF_TRADES", 9)
    min_external = min_external or _ref_knob("TREASURY_MM_REF_MIN_EXTERNAL", 3)
    rows = [(_D(p), b, s) for p, b, s in prints if p is not None and _D(p) > 0]
    external = [p for p, b, s in rows if treasury_did is None or (b != treasury_did and s != treasury_did)][:n]
    if len(external) >= min_external:
        return Decimal(statistics.median(external)), f"market median of {len(external)}"
    everything = [p for p, _b, _s in rows][:n]
    if everything:
        return Decimal(statistics.median(everything)), f"median of {len(everything)} prints (thin book)"
    return None, ""


class TreasuryMarketMaker(BackgroundWorker):
    worker_id = "treasury_market_maker"
    leader_key = "treasury_market_maker:leader"
    interval_sec = 15
    cold_start_delay_sec = 20

    def __init__(self) -> None:
        super().__init__()
        self._stats: Dict[str, Any] = {}
        self._ref_src: Dict[str, str] = {}   # listing id -> where this cycle's reference came from (the (re)quote log line)

    # ── gating ───────────────────────────────────────────────────────────────
    def _should_run(self) -> bool:
        return _truthy(os.getenv("EXCHANGE_ENABLED", "false")) and _truthy(
            os.getenv("TREASURY_MM_ENABLED", "false")
        )

    # ── cycle ────────────────────────────────────────────────────────────────
    async def _cycle_once(self) -> None:
        from .. import models
        async with get_db_context() as db:
            auto = await self._ensure_default_configs(db)   # §#82 default-on liquidity backstop
            cfgs = (
                await db.execute(
                    select(models.TreasuryMMConfig).where(models.TreasuryMMConfig.enabled.is_(True))
                )
            ).scalars().all()
            quoted = 0
            for cfg in cfgs:
                try:
                    if await self._quote_one(db, cfg):
                        quoted += 1
                except Exception as e:
                    logger.warning(f"[treasury_mm] {cfg.listing_id} quote failed: {str(e)[:140]}")
            self._stats = {"enabled": True, "listings": len(cfgs), "quoted": quoted,
                           "default_on": _truthy(os.getenv("EXCHANGE_MM_DEFAULT_ON", "false")),
                           "auto_enabled_this_cycle": auto}

    async def _ensure_default_configs(self, db) -> int:
        """§#82 — default-on liquidity backstop. When EXCHANGE_MM_DEFAULT_ON, auto-enable the
        treasury MM for every approved+trading listing that has NO config yet, pegged to FAIR
        (ref_mode=fair = ipo×SIM_EQ_ANCHOR_MULT) so price discovery converges to fair instead of
        pinning at the ipo×80 ceiling (the BSEA/EAST/QCC buy-only freeze). Idempotent — only
        creates MISSING rows, never overrides a hand-tuned OR explicitly-disabled config.
        Δ-irrelevant (creates a config row only; quoting itself rides place_order → Δ=0)."""
        from .. import models
        from ..services import exchange_service as svc
        # Enable via env OR a live DB flag (`mm_default_on`, like the demand-director) so it can
        # be flipped on a running worker with NO recreate, and rolled back instantly.
        _on = _truthy(os.getenv("EXCHANGE_MM_DEFAULT_ON", "false"))
        if not _on:
            try:
                _on = (await svc.get_flag(db, "mm_default_on")) == "true"
            except Exception:
                _on = False
        if not _on:
            return 0
        spread = int(_D(os.getenv("EXCHANGE_MM_DEFAULT_SPREAD_BPS", "200"), "200"))
        qty = int(_D(os.getenv("EXCHANGE_MM_DEFAULT_QUOTE_QTY", "100"), "100"))
        ref = (os.getenv("EXCHANGE_MM_DEFAULT_REF_MODE", "fair") or "fair").strip().lower()
        if ref not in ("last", "fair"):
            ref = "fair"
        have = set((await db.execute(select(models.TreasuryMMConfig.listing_id))).scalars().all())
        approved = (await db.execute(select(models.ExchangeListing.id).where(
            models.ExchangeListing.approved.is_(True),
            models.ExchangeListing.status == "trading",
        ))).scalars().all()
        created = 0
        for lid in approved:
            if lid in have:
                continue
            db.add(models.TreasuryMMConfig(
                listing_id=lid, enabled=True, spread_bps=spread, quote_qty=qty,
                reserve_shares=0, cash_floor=Decimal("0"), ref_mode=ref,
            ))
            created += 1
        if created:
            await db.commit()
            logger.info(f"[treasury_mm] default-on: auto-enabled MM on {created} listing(s) (ref={ref} spread={spread}bps qty={qty})")
        return created

    async def _reference_price(self, db, listing, ref_mode: str) -> Optional[Decimal]:
        import datetime as _dt
        from .. import models
        from ..services import exchange_service as svc
        if ref_mode == "fair":
            anchor = _D(os.getenv("SIM_EQ_ANCHOR_MULT", "20"))
            self._ref_src[listing.id] = "fair"
            return svc.q18(listing.ipo_price * anchor)
        # the market's price from the recent tape, never the market maker's own last print (module docstring)
        window = _ref_knob("TREASURY_MM_REF_WINDOW_S", 3600)
        since = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=window)
        prints = (await db.execute(
            select(models.ExchangeTrade.price, models.ExchangeTrade.buyer_did, models.ExchangeTrade.seller_did)
            .where(models.ExchangeTrade.listing_id == listing.id, models.ExchangeTrade.created_at >= since)
            .order_by(models.ExchangeTrade.seq.desc())
            .limit(_ref_knob("TREASURY_MM_REF_SCAN", 60))
        )).all()
        ref, src = market_reference(prints, listing.treasury_agent_did)
        if ref is not None and ref > svc.ZERO:
            self._ref_src[listing.id] = src
            return svc.q18(ref)
        last = await svc._last_price(db, listing.id)   # a quiet tape: the last print of any age, then the IPO price
        self._ref_src[listing.id] = "last print" if last and last > svc.ZERO else "ipo"
        if last and last > svc.ZERO:
            return svc.q18(last)
        return svc.q18(listing.ipo_price) if listing.ipo_price > svc.ZERO else None

    async def _cancel_quotes(self, db, listing) -> None:
        """Cancel the treasury's existing MM quotes for this listing (cancel-replace)."""
        from .. import models
        from ..services import exchange_service as svc
        existing = (
            await db.execute(
                select(models.ExchangeOrder).where(
                    models.ExchangeOrder.listing_id == listing.id,
                    models.ExchangeOrder.agent_did == listing.treasury_agent_did,
                    models.ExchangeOrder.status.in_(("open", "partial", "funding")),
                    models.ExchangeOrder.client_order_id.like("mm-%"),
                )
            )
        ).scalars().all()
        for o in existing:
            try:
                await svc.cancel_order(db, listing.treasury_agent_did, o.id)
            except Exception as e:
                _note_skip("cancel", getattr(o, "symbol", "") or str(getattr(o, "id", "")), e)

    async def _quote_one(self, db, cfg) -> bool:
        from ..services import exchange_service as svc
        from .. import models
        listing = await svc._get_listing(db, cfg.listing_id)
        if not listing.approved or listing.status != "trading":
            return False
        ref = await self._reference_price(db, listing, (cfg.ref_mode or "last"))
        if ref is None or ref <= svc.ZERO:
            return False
        spread = _D(cfg.spread_bps) / Decimal(10000)
        tick = listing.tick if listing.tick and listing.tick > svc.ZERO else Decimal("0.01")
        bid_px = _to_tick(ref * (Decimal(1) - spread), tick)
        ask_px = _to_tick(ref * (Decimal(1) + spread), tick)
        # clamp into the listing band (±band_pct of last) so place_order won't reject;
        # ceil the floor / floor the ceiling so the clamped price stays strictly in-band.
        last = await svc._last_price(db, listing.id)
        if last and last > svc.ZERO:
            lo, hi = svc._band_bounds(last, listing.band_pct)
            lo_t, hi_t = _to_tick(lo, tick, ROUND_UP), _to_tick(hi, tick, ROUND_DOWN)
            if hi_t <= lo_t:
                return False
            bid_px = max(lo_t, min(hi_t, bid_px))
            ask_px = max(lo_t, min(hi_t, ask_px))
            # §#82 walk-to-fair (productized soft-peg): when `fair` sits OUTSIDE the band the
            # two-sided quotes collapse to one edge (bid>=ask). Quote ONE-SIDED at that edge
            # TOWARD fair so the MM walks `last` toward fair band-by-band, instead of skipping
            # (which leaves a passport-pumped ceiling-pin un-converged). Δ=0 (rides place_order).
            if bid_px >= ask_px:
                if ref <= last:        # fair below market → SELL at the band low (drive down)
                    bid_px, ask_px = None, lo_t
                else:                  # fair above market → BUY at the band high (drive up)
                    bid_px, ask_px = hi_t, None
        if (bid_px is not None and bid_px <= svc.ZERO) or (ask_px is not None and ask_px <= svc.ZERO):
            return False
        if bid_px is not None and ask_px is not None and bid_px >= ask_px:
            return False
        if bid_px is None and ask_px is None:
            return False

        # §P2.1-refine: RE-QUOTE ONLY ON DRIFT. A resting quote within half the spread of
        # target is left alone — no cancel — so a stable market produces ZERO cancel churn.
        # (The old cancel-replace-every-cycle deferred each cancelled BUY's escrow refund to
        # settlement batch C, transiently inflating I-X3.) A FILLED quote is simply gone →
        # replaced; a DRIFTED quote is cancelled + replaced (rare, self-clears before next).
        drift_tol = spread / Decimal(2)
        existing = (
            await db.execute(
                select(models.ExchangeOrder).where(
                    models.ExchangeOrder.listing_id == listing.id,
                    models.ExchangeOrder.agent_did == listing.treasury_agent_did,
                    models.ExchangeOrder.status.in_(("open", "partial", "funding")),
                    models.ExchangeOrder.client_order_id.like("mm-%"),
                )
            )
        ).scalars().all()
        cur_ask = next((o for o in existing if o.side == "sell"), None)
        cur_bid = next((o for o in existing if o.side == "buy"), None)

        def _fresh(o, target) -> bool:
            return o is not None and quote_is_fresh(o.price, target, drift_tol)

        placed_any = False
        # ASK — keep an in-tolerance resting quote; replace only if missing/filled or drifted.
        # ask_px is None ⇒ one-sided drive-UP cycle: cancel any stale ask, place nothing.
        if ask_px is None:
            if cur_ask is not None:
                try:
                    await svc.cancel_order(db, listing.treasury_agent_did, cur_ask.id)
                except Exception as e:
                    _note_skip("ask_cancel_1sided", listing.symbol, e)
        elif not _fresh(cur_ask, ask_px):
            if cur_ask is not None:
                try:
                    await svc.cancel_order(db, listing.treasury_agent_did, cur_ask.id)
                except Exception as e:
                    _note_skip("ask_cancel", listing.symbol, e)
            pos = await svc._get_or_create_position(db, listing.id, listing.treasury_agent_did)
            if (pos.qty - pos.locked_qty) - cfg.quote_qty >= cfg.reserve_shares:
                try:
                    await svc.place_order(
                        db, agent_did=listing.treasury_agent_did, listing_ref=listing.id,
                        side="sell", order_type="limit", qty=cfg.quote_qty, price=ask_px,
                        client_order_id=f"mm-ask-{listing.id}-{uuid.uuid4().hex[:10]}",
                    )
                    placed_any = True
                except Exception as e:
                    _note_skip("ask", listing.symbol, e)
        # BID — the escrow-churn side: drift-gating matters most here.
        # bid_px is None ⇒ one-sided drive-DOWN cycle: cancel any stale bid, place nothing.
        if bid_px is None:
            if cur_bid is not None:
                try:
                    await svc.cancel_order(db, listing.treasury_agent_did, cur_bid.id)
                except Exception as e:
                    _note_skip("bid_cancel_1sided", listing.symbol, e)
        elif not _fresh(cur_bid, bid_px):
            if cur_bid is not None:
                try:
                    await svc.cancel_order(db, listing.treasury_agent_did, cur_bid.id)
                except Exception as e:
                    _note_skip("bid_cancel", listing.symbol, e)
            try:
                bal = await svc.ExchangeMover().agent_balance(listing.treasury_agent_did)
                if _D(bal) - (bid_px * Decimal(cfg.quote_qty)) >= _D(cfg.cash_floor):
                    await svc.place_order(
                        db, agent_did=listing.treasury_agent_did, listing_ref=listing.id,
                        side="buy", order_type="limit", qty=cfg.quote_qty, price=bid_px,
                        client_order_id=f"mm-bid-{listing.id}-{uuid.uuid4().hex[:10]}",
                    )
                    placed_any = True
            except Exception as e:
                _note_skip("bid", listing.symbol, e)
        if placed_any:
            logger.info(f"[treasury_mm] (re)quoted {listing.symbol} bid={bid_px} ask={ask_px} qty={cfg.quote_qty} "
                        f"ref={ref} ({self._ref_src.get(listing.id, '?')})")
        return placed_any


_singleton: Optional[TreasuryMarketMaker] = None


async def start_treasury_market_maker() -> None:
    global _singleton
    if _singleton is not None:
        return
    _singleton = TreasuryMarketMaker()
    if not _singleton._should_run():
        logger.info("[treasury_mm] disabled via env gate (EXCHANGE_ENABLED / TREASURY_MM_ENABLED)")
        return
    await _singleton.start()
    logger.info("[treasury_mm] STARTED (treasury market-maker, two-sided quotes, Δ-safe)")


async def stop_treasury_market_maker() -> None:
    global _singleton
    if _singleton is None:
        return
    await _singleton.stop()
    _singleton = None


def get_treasury_market_maker() -> Optional[TreasuryMarketMaker]:
    return _singleton
