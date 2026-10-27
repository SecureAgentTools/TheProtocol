"""§POCKETBRIDGE3 (D3-4) — server half of Pocket session price alerts.

The in-session half is the client: while Pocket is open it watches the tickers
it already polls and banners instantly. THIS task exists for the closed app:
it reads every developer's `pocket.price_alerts` pref rows (mig 0152), checks
the LOCAL venue's last trade against each armed rule, and fires the typed
`exchange.price_alert` notification — inapp by default, push only for
developers who opted the category in (default OFF, the Commander's D3-4 call).

Honesty boundaries, stated in the alert copy too:
  - LOCAL venue only. Rules created against a federation venue carry a
    `venue` field and are skipped here (the session client covers them while
    the app is open). Cross-venue server watching is a later batch.
  - An alert fires ONCE (fired_at written back), then stays visible in the
    client until dismissed. Expired rules (default 24h) are skipped.

Single-writer discipline: only the leader runs, and the write-back merges
fired_at by alert id into a FRESH read of the row rather than overwriting
with this cycle's snapshot — the FE may have edited the list mid-cycle.
Δ-irrelevant: reads trades, writes prefs + notifications; no money moves.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from ..database import AsyncSessionLocal as async_session_factory
from .. import models

logger = logging.getLogger(__name__)

_running = False

CYCLE_SECONDS = int(os.getenv("PRICE_ALERT_WATCHER_INTERVAL", "60"))
PREF_KEY = "pocket.price_alerts"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def evaluate_rule(rule: Dict[str, Any], last: Optional[Decimal], now: Optional[datetime] = None) -> Optional[str]:
    """Pure: does this rule fire against `last`? Returns 'up'/'down' or None.

    A rule: {id, symbol, venue?, baseline, pct, created_at, expires_at, fired_at?}.
    Skips: already fired, expired, venue-scoped (not local), unpriced listing.
    """
    now = now or _now()
    if rule.get("fired_at"):
        return None
    if rule.get("venue"):
        return None  # local watcher only — stated in the module docstring + UI
    exp = _parse_ts(rule.get("expires_at"))
    if exp and now > exp:
        return None
    if last is None:
        return None
    try:
        baseline = Decimal(str(rule.get("baseline")))
        pct = Decimal(str(rule.get("pct")))
    except Exception:  # noqa: BLE001 — malformed rule is skipped, never crashes the cycle
        return None
    if baseline <= 0 or pct <= 0:
        return None
    up = baseline * (Decimal(1) + pct / Decimal(100))
    down = baseline * (Decimal(1) - pct / Decimal(100))
    if last >= up:
        return "up"
    if last <= down:
        return "down"
    return None


async def _watch_once() -> None:
    from ..services import exchange_service as svc
    from .push_notify import notify

    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(models.DeveloperPref).where(models.DeveloperPref.key == PREF_KEY)
            )
        ).scalars().all()
        if not rows:
            return

        # One listing map + one last-price read per referenced symbol per cycle.
        listings = (
            await db.execute(
                select(models.ExchangeListing).where(
                    models.ExchangeListing.approved.is_(True),
                    models.ExchangeListing.status != "delisted",
                )
            )
        ).scalars().all()
        by_symbol = {l.symbol.upper(): l for l in listings}
        price_cache: Dict[str, Optional[Decimal]] = {}

        async def last_for(symbol: str) -> Optional[Decimal]:
            s = symbol.upper()
            if s not in price_cache:
                listing = by_symbol.get(s)
                if listing is None:
                    price_cache[s] = None
                else:
                    px = await svc._last_price(db, listing.id)
                    if px is None and getattr(listing, "ipo_price", None) is not None:
                        px = Decimal(str(listing.ipo_price))
                    price_cache[s] = px
            return price_cache[s]

        now = _now()
        for row in rows:
            value = row.value or {}
            rules: List[Dict[str, Any]] = list(value.get("rules") or [])
            if not rules:
                continue
            fired_ids: Dict[str, Dict[str, Any]] = {}
            for rule in rules:
                sym = str(rule.get("symbol") or "").upper()
                if not sym:
                    continue
                last = await last_for(sym)
                direction = evaluate_rule(rule, last, now)
                if not direction:
                    continue
                pct = rule.get("pct")
                # Human-facing price: the raw ledger Decimal prints 18 trailing
                # zeros on a phone notification.
                try:
                    last_disp = f"{float(last):,.4f}".rstrip("0").rstrip(".")
                except (TypeError, ValueError):
                    last_disp = str(last)
                try:
                    await notify(
                        "exchange.price_alert",
                        [row.developer_id],
                        title=f"${sym} moved {'▲' if direction == 'up' else '▼'} past ±{pct}%",
                        message=(
                            f"${sym} last traded at {last_disp}, "
                            f"{'above' if direction == 'up' else 'below'} your ±{pct}% band "
                            f"around {rule.get('baseline')}. (Local venue watch.)"
                        ),
                        tags="warning",
                        priority="high",
                        click=f"/ui#/pocket/trade?sym={sym}",
                    )
                    fired_ids[str(rule.get("id"))] = {
                        "fired_at": now.isoformat(),
                        "fired_price": str(last),
                        "fired_direction": direction,
                    }
                except Exception:  # noqa: BLE001
                    logger.error("[PRICE-ALERT] notify failed dev=%s sym=%s", row.developer_id, sym, exc_info=True)
            if fired_ids:
                # Merge into a FRESH read — the FE may have rewritten the list
                # since this cycle's snapshot. Only fired_at fields are ours.
                fresh = (
                    await db.execute(
                        select(models.DeveloperPref).where(
                            models.DeveloperPref.developer_id == row.developer_id,
                            models.DeveloperPref.key == PREF_KEY,
                        )
                    )
                ).scalar_one_or_none()
                if fresh is None:
                    continue
                # DEEP copy, not dict()/list(): shallow copies share the inner
                # rule dicts with the ORM-loaded value, so mutating them makes
                # old == new at flush time and NO UPDATE is emitted — measured
                # live as a double-fire with fired_at never persisting.
                import json as _json
                fresh_value = _json.loads(_json.dumps(fresh.value or {}))
                fresh_rules = list(fresh_value.get("rules") or [])
                changed = False
                for r in fresh_rules:
                    hit = fired_ids.get(str(r.get("id")))
                    if hit and not r.get("fired_at"):
                        r.update(hit)
                        changed = True
                if changed:
                    fresh_value["rules"] = fresh_rules
                    fresh.value = fresh_value
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(fresh, "value")
                    await db.commit()


async def price_alert_watcher_loop():
    """Background loop — leader-elected, default 60s cycle."""
    from .leader import try_acquire_leadership
    global _running
    _running = True
    logger.info("[PRICE-ALERT] watcher started (%ds cycle, local venue only)", CYCLE_SECONDS)
    from . import vitals as _vitals
    await _vitals.register("price_alert_watcher", module=__name__, pattern="hand-rolled",
                           interval_sec=CYCLE_SECONDS, enabled=True)
    while _running:
        try:
            if await try_acquire_leadership("price_alert_watcher"):
                async with _vitals.cycle("price_alert_watcher"):
                    await _watch_once()
        except Exception:
            logger.error("[PRICE-ALERT] cycle error", exc_info=True)
        await asyncio.sleep(CYCLE_SECONDS)


def stop_price_alert_watcher():
    global _running
    _running = False
