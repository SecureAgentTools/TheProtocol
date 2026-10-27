"""AGORA order escrow → cancel → refund, driven, with the money and the ledger.

`ExchangeOrderPlaced` and `ExchangeOrderCancelled` were among the thirty event
types this suite only PINNED: it asserted rows exist, never that placing an
order produces one. On sbx-alpha they show exactly one row each across four org
aggregates — the shape of a fixture someone seeded once, not of a rail anything
exercises.

The round trip asserted here is deliberately net-zero: place a resting limit BUY
(escrows the notional), then cancel it (refunds). A rail that escrowed and did
not refund, or refunded more than it took, is a money defect that no read-only
test can see — and both halves are checked against the SAME balance, so a
symmetric bug cannot hide in the difference.

Three instruments, because each is blind to a different failure:
  * the agent's BALANCE          — did the money actually move, and come back
  * the supply invariant Δ       — did the frame's books stay whole
  * `exchange/admin/invariant`   — I-X1..I-X4, the venue's OWN conservation
    check (escrow vs open orders vs positions). Δ can sit at 0 while the venue's
    internal escrow accounting is wrong, because Δ does not know what an order
    book is.
  * the EventStore               — did the ledger RECORD both legs

⚠ NO LISTING IS CREATED. A listing is org-owned, admin-approved and permanent;
minting one per run would litter the venue forever. This trades against whatever
is already listed and TRADING, and raises `PreconditionUnmet` — a loud skip, not
a pass — when nothing is. On a fresh frame that skip IS the finding: it says the
venue has no market yet, which is exactly what a standup wants to know.

⚠ PRICE MUST REST, NOT CROSS. A crossing order fills, and a filled order cannot
be cancelled — the test would then be measuring a trade, not an escrow round
trip. The price is placed below the last trade and below any live bid, rounded
DOWN onto the listing's own tick, and kept inside the price band (`band_pct` is
PERCENT here; its neighbour `cb_pct` is basis points — two adjacent admin knobs
both spelled `*_pct`).

⚠ Writes: one agent and one cancelled order per run, tagged `fedsuite-agora-*`.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
    ensure_bonded,
)

_FUND = "50.0"
_QTY = 1


def _soft(r: Any) -> Optional[str]:
    if isinstance(r, dict) and set(r.keys()) == {"_text"} and isinstance(r["_text"], str):
        return r["_text"]
    if isinstance(r, str):
        return r
    return None


async def _call(rig, label: str, tool: str, args: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    try:
        r = await rig.mcp(label).call(tool, args, timeout=60)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    # adminRequest / adminQueryEventStore WRAP the upstream call and return HTTP
    # 200 for the MCP call itself, so a 422 upstream reads as success unless the
    # wrapper's own status is checked here.
    if isinstance(r, dict) and isinstance(r.get("status_code"), int) and r["status_code"] >= 400:
        return r, f"wrapped HTTP {r['status_code']}: {json.dumps(r.get('response'))[:180]}"
    return r, _soft(r)


async def _rest(rig, method: str, endpoint: str, *, label: str = "sandbox-A-admin",
                body: Optional[Dict[str, Any]] = None,
                jwt: Optional[str] = None) -> Tuple[int, Any]:
    """One REST call through adminRequest → (status_code, unwrapped body).

    ⚠ Returns a TUPLE; `isinstance(tuple, dict)` is False, so a caller that
    treats it as a body falls through to its own not-found branch silently.
    ⚠ adminRequest sends NO BODY on DELETE (tools_admin.py) — any DELETE needing
    one is undriveable through this proxy. Cancel takes its id in the PATH, so
    this rail is reachable; that is luck, not design.
    """
    args: Dict[str, Any] = {"method": method, "endpoint": endpoint}
    if body is not None:
        args["body"] = body
    if jwt:
        args["developer_jwt"] = jwt
    try:
        r = await rig.mcp(label).call("adminRequest", args, timeout=60)
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"
    if not isinstance(r, dict):
        return -1, r
    code = r.get("status_code")
    return (code if isinstance(code, int) else -1), r.get("response")


def _num(v: Any) -> float:
    """Balances come back in SCIENTIFIC NOTATION ('1E+3') — int() RAISES."""
    if v is None:
        return 0.0
    try:
        return float(str(v))
    except Exception:
        return 0.0


async def _delta(rig) -> Optional[float]:
    r, refused = await _call(rig, "sandbox-A-admin", "adminQueryEventStore",
                             {"path": "/api/v1/projections/supply-audit"})
    if refused or not isinstance(r, dict):
        return None
    body = r.get("response") if isinstance(r.get("response"), dict) else r
    d = body.get("delta")
    return None if d is None else _num(d)


async def _venue_ok(rig) -> Optional[bool]:
    """I-X1..I-X4. None = could not read, which is not the same as not ok."""
    st, body = await _rest(rig, "GET", "/api/v1/agora/admin/invariant")
    if st != 200 or not isinstance(body, dict):
        return None
    ok = body.get("ok")
    return None if ok is None else bool(ok)


def _invariant_breaches(body: Any) -> List[str]:
    """Which of I-X1..I-X5 the venue's own report says failed (names, not a boolean): a skip must say which."""
    out: List[str] = []
    if not isinstance(body, dict):
        return out
    for k, v in body.items():
        if k.startswith("I-X") and isinstance(v, dict) and v.get("ok") is False:
            out.append(f"{k} {json.dumps(v, default=str)[:160]}")
    for row in body.get("listings") or []:
        if isinstance(row, dict):
            bad = [k for k, v in row.items() if k.startswith("I-X") and v is False]
            if bad:
                out.append(f"{row.get('symbol')}: {','.join(bad)}")
    return out


async def _venue_ok_settled(rig, reads: int = 5, gap_s: float = 3.0) -> Tuple[Optional[bool], List[str]]:
    """§MCPTEST30 (2026-09-30): the venue invariant read on a tier where the sandbox sim trades all the time.
    One read can land between an order's escrow lock and its book row, so a single not-ok refused this test on a
    healthy venue (measured: breached at 20:5xZ on 2026-09-30, ok on every read a minute later). Re-read a few
    times: ok on any read is ok; not ok on every read is a breach, and the answer names what the venue reported."""
    last: List[str] = []
    seen_none = False
    for i in range(reads):
        st, body = await _rest(rig, "GET", "/api/v1/agora/admin/invariant")
        if st == 200 and isinstance(body, dict) and body.get("ok") is not None:
            if bool(body.get("ok")):
                return True, []
            last = _invariant_breaches(body) or ["ok=false with no failing check named"]
        else:
            seen_none = True
        if i + 1 < reads:
            await asyncio.sleep(gap_s)
    return (None if (seen_none and not last) else False), last


async def _new_agent(rig, tag: str) -> Dict[str, str]:
    r, refused = await _call(rig, "sandbox-A", "createAgent", {
        "name": f"fedsuite-agora-{tag}-{uuid.uuid4().hex[:8]}",
        "description": "federation suite AGORA order probe",
    })
    if refused or not isinstance(r, dict):
        raise PreconditionUnmet(f"createAgent refused for {tag}: {refused}")
    if r.get("error"):
        raise PreconditionUnmet(f"createAgent error for {tag}: {r['error']}")
    cid = r.get("client_id") or (r.get("credentials") or {}).get("client_id")
    sec = r.get("client_secret") or (r.get("credentials") or {}).get("client_secret")
    did = r.get("did") or r.get("agent_did") or (r.get("agent") or {}).get("did")
    throwaways.made("sandbox-A", did)  # V0641: retired once its test's verdict is in (throwaways)
    if not (cid and sec and did):
        raise PreconditionUnmet(f"createAgent for {tag} returned no credential triple")
    t, tref = await _call(rig, "sandbox-A", "getAgentToken",
                          {"client_id": cid, "client_secret": sec})
    if tref or not isinstance(t, dict):
        raise PreconditionUnmet(f"getAgentToken refused for {tag}: {tref}")
    jwt = t.get("access_token") or t.get("agent_jwt")
    if not jwt:
        raise PreconditionUnmet(f"no agent JWT for {tag}")
    # §REPBOND: creation does NOT bond, so on an enforcing tier this fixture
    # is born refused at discovery/listing/pricing/guild/contract/a2a-payee.
    await ensure_bonded(rig, "sandbox-A", did)
    return {"did": did, "jwt": jwt}


async def _balance(rig, jwt: str) -> float:
    r, refused = await _call(rig, "sandbox-A", "getMyBalance", {"agent_jwt": jwt})
    if refused or not isinstance(r, dict):
        return 0.0
    for k in ("balance", "liquid_balance", "token_balance", "available"):
        if r.get(k) is not None:
            return _num(r[k])
    return 0.0


async def _order_event_types(rig, listing_id: str, order_id: str) -> Optional[List[str]]:
    """Event types on THIS listing's aggregate that name THIS order.

    ⚠ Exchange events are keyed on the LISTING id, not the order id, and the
    order is identified inside the payload. Querying the order id returns zero
    and reads exactly like a rail that never emitted. Returns None when the ES
    cannot be read — "could not check" is its own state.
    """
    if not (listing_id and order_id):
        return None
    r, refused = await _call(rig, "sandbox-A-admin", "adminQueryEventStore",
                             {"path": f"/api/v1/events/aggregate/{listing_id}"})
    if refused:
        return None
    # /events/aggregate/{id} answers with a LIST; unwrapping only a dict makes
    # the guard fall through to the wrapper and report an empty ledger.
    body = r.get("response", r) if isinstance(r, dict) and "response" in r else r
    if isinstance(body, list):
        events = body
    elif isinstance(body, dict):
        events = body.get("events") or body.get("items") or []
    else:
        return None
    out: List[str] = []
    for e in events:
        if not isinstance(e, dict):
            continue
        d = e.get("data") or e.get("payload") or {}
        if not isinstance(d, dict) or d.get("order_id") != order_id:
            continue
        t = str(e.get("event_type") or e.get("type") or "")
        if t:
            out.append(t)
    return out


async def _order_status(rig, jwt: str, order_id: str) -> Optional[str]:
    """This order's status as the venue reports it, or None if unreadable.

    ⚠ MEASURED ORDERING ON THIS RAIL, and it is not the obvious one. After the
    cancel returns HTTP 200: the status reads `cancelled` and BOTH events are
    already in the EventStore within ~0.4s, and **the money comes back ~6s
    later** (sampled at 0.7s intervals: 0.4→5.1s balance still down, 6.1s
    restored). Status, ledger and money settle at three different times, in that
    order.

    So this status is NOT the anchor for the money check — it is true five
    seconds too early — and a control that demanded "the refund did not happen"
    passed twice: once against the raw balance, and again after gating on
    `cancelled`. The negation of an eventually-claim is transiently true, so it
    can never be a valid control for one. The valid control is a WRONG SETTLED
    VALUE (assert the balance returned to b0 + 1), which is true at no instant.

    Kept because it states the ordering explicitly and fails informatively if a
    cancel never settles at all.
    """
    st, body = await _rest(rig, "GET", "/api/v1/agora/orders/mine", jwt=jwt)
    if st != 200:
        return None
    rows = body.get("orders") if isinstance(body, dict) else body
    if not isinstance(rows, list):
        return None
    for o in rows:
        if isinstance(o, dict) and (o.get("id") == order_id or o.get("order_id") == order_id):
            return str(o.get("status") or "")
    return ""          # readable, and this order is not in the list


def _resting_bid_price(listing: Dict[str, Any]) -> Optional[str]:
    """A limit BUY price that rests instead of crossing, on tick, inside the band.

    Returns None when no such price exists — a listing whose band floor sits at
    or above the best ask has no resting room, and inventing a price there would
    produce a fill and a test that measures the wrong thing.
    """
    stats = listing.get("stats") or {}
    ref = None
    for k in ("last", "ipo_price"):
        v = stats.get(k) if k in stats else listing.get(k)
        if v is not None:
            ref = Decimal(str(v))
            break
    if ref is None or ref <= 0:
        return None
    tick = Decimal(str(listing.get("tick") or "0.01"))
    if tick <= 0:
        tick = Decimal("0.01")
    band = Decimal(str(listing.get("band_pct") or 25))       # PERCENT, not bps
    floor = ref * (Decimal(1) - band / Decimal(100))
    target = ref * Decimal("0.80")
    if target < floor:
        target = floor
    # Stay strictly under any live bid so the order rests at the top of nothing
    # rather than joining or crossing.
    best_bid = stats.get("best_bid")
    if best_bid is not None:
        bb = Decimal(str(best_bid))
        if target >= bb:
            target = bb - tick
    best_ask = stats.get("best_ask")
    if best_ask is not None and target >= Decimal(str(best_ask)):
        return None                                           # would cross → fill
    price = (target / tick).to_integral_value(rounding=ROUND_DOWN) * tick
    if price <= 0 or price < floor:
        return None
    return format(price.normalize(), "f")


@federation_test(
    name="exchange_order_escrows_places_and_refunds_on_cancel",
    category="exchange_economic",
    budget_sec=120.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["exchange", "agora", "economic", "money", "delta", "event_emission"],
)
async def test_exchange_order_round_trip(rig: FederationTestRig) -> AssertionResult:
    """Place a resting limit buy, cancel it, and prove the money came back."""
    state: Dict[str, Any] = {}

    # ── arrange (OUTSIDE the poller: assert_within swallows raises) ────────
    d0 = await _delta(rig)
    v0, v0_breaches = await _venue_ok_settled(rig)
    state["delta_before"], state["venue_ok_before"] = d0, v0
    if d0 is None:
        raise PreconditionUnmet("supply audit unreadable — cannot guard Δ, refusing to move money")
    if abs(d0) > 1e-9:
        raise PreconditionUnmet(f"Δ is already {d0}, not 0 — refusing to run an economic test")
    if v0 is None:
        raise PreconditionUnmet("exchange invariant unreadable — cannot guard the venue")
    if v0 is not True:
        raise PreconditionUnmet("exchange invariant breached on every one of 5 reads over ~12 s — refusing to "
                                f"add orders; the venue reports: {'; '.join(v0_breaches)[:400]}")

    st, listings = await _rest(rig, "GET", "/api/v1/agora/listings")
    if st != 200:
        raise PreconditionUnmet(f"listings HTTP {st}")
    rows = listings if isinstance(listings, list) else (
        (listings or {}).get("listings") or (listings or {}).get("items") or [])
    tradable = [l for l in rows if isinstance(l, dict) and l.get("status") == "trading"]
    state["listings_seen"], state["listings_trading"] = len(rows), len(tradable)
    if not tradable:
        # On a fresh frame this is the answer, not a failure: no market yet.
        raise PreconditionUnmet(
            f"no listing is TRADING on this venue ({len(rows)} listed) — nothing to place against")

    listing = price = None
    for cand in tradable:
        p = _resting_bid_price(cand)
        if p:
            listing, price = cand, p
            break
    if not listing:
        raise PreconditionUnmet(
            "no trading listing has room for a resting bid inside its price band")
    lid, symbol = listing.get("id"), listing.get("symbol")
    state["listing"] = {"id": lid, "symbol": symbol, "price": price,
                        "tick": listing.get("tick"), "band_pct": listing.get("band_pct")}

    trader = await _new_agent(rig, "trader")
    state["trader"] = trader["did"]
    fst, fbody = await _rest(rig, "POST", "/api/v1/teg/treasury/fund-agent",
                             body={"target_agent_did": trader["did"], "amount": _FUND,
                                   "reason": "federation suite AGORA order probe"})
    if fst != 200:
        raise PreconditionUnmet(f"treasury funding HTTP {fst}: {json.dumps(fbody, default=str)[:180]}")
    b0 = await _balance(rig, trader["jwt"])
    state["balance_before"] = b0
    if b0 <= 0:
        raise PreconditionUnmet(f"trader funded but balance reads {b0}")

    # ── act: place ────────────────────────────────────────────────────────
    pst, placed = await _rest(rig, "POST", "/api/v1/agora/orders", jwt=trader["jwt"], body={
        "listing": symbol, "side": "buy", "order_type": "limit",
        "qty": _QTY, "price": price, "tif": "gtc",
    })
    state["place_status"] = pst
    if pst != 200 or not isinstance(placed, dict):
        raise PreconditionUnmet(
            f"place order HTTP {pst}: {json.dumps(placed, default=str)[:220]}")
    oid = placed.get("order_id") or placed.get("id") or (placed.get("order") or {}).get("id")
    state["order_id"] = oid
    state["order_status"] = placed.get("status") or (placed.get("order") or {}).get("status")
    if not oid:
        raise PreconditionUnmet(f"place returned no order id (keys={sorted(placed)[:10]})")
    # A filled order cannot be cancelled; the escrow round trip would not exist.
    if str(state["order_status"]).lower() in ("filled", "closed"):
        raise PreconditionUnmet(
            f"order filled immediately at {price} — this listing has no resting room today")

    b_escrow = await _balance(rig, trader["jwt"])
    state["balance_after_place"] = b_escrow
    state["escrow_debit"] = round(b0 - b_escrow, 8)

    # ── act: cancel ───────────────────────────────────────────────────────
    cst, cancelled = await _rest(rig, "DELETE", f"/api/v1/agora/orders/{oid}", jwt=trader["jwt"])
    state["cancel_status"] = cst
    if cst != 200:
        state["cancel_body"] = json.dumps(cancelled, default=str)[:220]

    # ── assert: money back, books whole, both legs recorded ───────────────
    async def predicate():
        status = await _order_status(rig, trader["jwt"], oid)
        b1 = await _balance(rig, trader["jwt"])
        d1 = await _delta(rig)
        v1 = await _venue_ok(rig)
        types = await _order_event_types(rig, lid, oid)
        state["order_status_now"] = status
        state["balance_after_cancel"] = b1
        state["delta_after"], state["venue_ok_after"] = d1, v1
        state["net_balance_change"] = round(b1 - b0, 8)
        escrowed = state["escrow_debit"] > 0
        # SETTLED first: only then does a balance comparison mean anything.
        settled = status is not None and status.lower() in ("cancelled", "canceled")
        refunded = abs(b1 - b0) < 1e-6
        delta_ok = d1 is not None and abs(d1) < 1e-9
        venue_ok = v1 is True
        if types is None:
            seen = missing = evented = None
        else:
            seen = sorted(set(types))
            missing = [e for e in ("ExchangeOrderPlaced", "ExchangeOrderCancelled")
                       if e not in types]
            evented = not missing
        state["verdict"] = {"escrowed_on_place": escrowed, "cancel_settled": settled,
                            "refunded_on_cancel": refunded,
                            "delta_zero": delta_ok, "venue_invariant_ok": venue_ok,
                            "events_seen": seen, "events_missing": missing, "evented": evented}
        return bool(escrowed and settled and refunded and delta_ok
                    and venue_ok and evented is True)

    return await rig.assert_within(
        budget_sec=75.0, predicate=predicate, poll_interval_sec=3.0,
        description="an AGORA limit order escrows on place and, once the cancel is "
                    "SETTLED, refunds in full with Δ, the venue invariant and both "
                    "events intact",
        capture_state=lambda: state,
    )
