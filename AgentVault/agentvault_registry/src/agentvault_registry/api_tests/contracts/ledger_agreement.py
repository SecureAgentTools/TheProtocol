"""§MCPTEST30 (2026-10-01) — the TEG and the EventStore agree on what the run moved.

CLAUDE.md PART 4: Δ=0 settles conservation as the ledger understands it, not that a move was recorded. The store derives
both legs of a transfer from ONE TokensTransferred, so a DROPPED emit moves total_circulating and transit_net by zero:
Δ reads 0.0 while the store's balances drift from the TEG's truth (§S4: "balances moved AND Δ=0 is NOT proof"). Nothing
in the tester compared the two ledgers. The run's sentinel pays and is paid by many lifecycles; this reads its TEG
balance (getMyBalance) and its EventStore projection (adminQueryEventStore /api/v1/projections/balance/<did>, refresh)
before the lifecycle phase and after it. The CHANGE must agree, liquid and staked, whatever drift the agent carried
before the run. The store is written a moment after the TEG, so the after-read waits for it (a few refreshed reads).
Measured by hand on sbx-alpha (V0526) before the probe existed: its canary sender read 1015.375979 in both, 2877 events.
Row `ledger: the run's sentinel over the lifecycle phase`; it keeps the changes and the events the store added.

§MCPTEST30 (V0545): the BEFORE-read must wait for the store too. Round 13 (run 6aa4b0ed5e9a42df, 2026-10-02) read "TEG
-41.207024 vs store -45.207024" while the two journals matched one for one (33 entries, every one emitted, the same
amounts): the setup phase's last guild escrows (-1.0 each, TEG 04:02:51-04:03:00Z) reached the store 2-4 s later, after
the before-read, so the store's change over the phase carried 4.0 the TEG's had already counted. The before-read now
waits until both ledgers hold still across two reads (settled_snapshot), and says so when they never do.

§MCPTEST30 (V0585): holding still is not catching up. The 03:00Z run of 2026-10-08 (V0584, sbx-alpha) read "TEG -26.207523
vs store -30.207523" with the journals again one for one (37 rows, every one emitted, the same txids): the TEG emits in
batches, 3 to 8 s after a change (the setup's guild escrows changed 03:00:51-57Z, reached the store 03:00:55 and 03:01:04Z),
so two store reads 2 s apart agreed while four escrows waited in the TEG's outbox. A before-read is now settled when the
store has CAUGHT UP (the two ledgers' balances agree, liquid and staked), or, for an agent that carried drift before the
run (they never agree), when nothing moved for STILL_SPAN seconds, longer than the emitter's lag.
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Optional, Tuple

ROW = "ledger: the run's sentinel over the lifecycle phase"
TOLERANCE = Decimal("0.000001")   # the store's projection travels as a float (to_dict): a micro-unit of slack
WAITS = (0, 3, 5, 8, 12)          # seconds before each after-read: the store is written just after the TEG
SETTLE_WAITS = (2, 3, 4, 6, 8)    # seconds between before-reads
STILL_SPAN = 12                   # seconds unchanged that settle a drifted reading: longer than the TEG's 3-8 s emit lag


def _dec(v: Any) -> Optional[Decimal]:
    try:
        d = Decimal(str(v))
        return d if d.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


async def _teg(rpc: Callable, parse: Callable, bag: Any) -> Optional[Dict[str, Decimal]]:
    ok, body, _code = await rpc("theprotocol_getMyBalance", {"agent_jwt": bag.sentinel_jwt},
                                jwt=bag.developer_jwt, timeout=30)
    inner = parse(body) if ok else None
    if not isinstance(inner, dict) or inner.get("error"):
        return None
    liquid, staked = _dec(inner.get("liquid_balance")), _dec(inner.get("staked_balance"))
    return None if liquid is None or staked is None else {"liquid": liquid, "staked": staked}


async def _store(raw: Callable, bag: Any) -> Optional[Dict[str, Any]]:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "theprotocol_adminQueryEventStore",
        "arguments": {"path": f"/api/v1/projections/balance/{bag.sentinel_did}", "params": {"refresh": "true"}}}})
    _code, parsed, _x = await raw(body, path="/mcp/admin/rpc", jwt=bag.developer_jwt, timeout=30)
    try:
        res = parsed.get("result") or {}
        out = json.loads((res.get("content") or [{}])[0].get("text", "{}")) if not res.get("isError") else {}
    except Exception:  # noqa: BLE001
        return None
    r = out.get("response") if isinstance(out, dict) and out.get("status_code") == 200 else None
    if not isinstance(r, dict):
        return None
    liquid, staked = _dec(r.get("liquid_balance")), _dec(r.get("staked_balance"))
    if liquid is None or staked is None:
        return None
    return {"liquid": liquid, "staked": staked, "events": int(r.get("event_count") or 0)}


async def snapshot(rpc: Callable, parse: Callable, bag: Any) -> Optional[Dict[str, Any]]:
    """Both ledgers' view of the sentinel now, or None when either could not be read (never a guess)."""
    raw = getattr(bag, "rpc_raw", None)
    did, jwt = getattr(bag, "sentinel_did", None), getattr(bag, "sentinel_jwt", None)
    if raw is None or not did or not jwt or str(did).startswith("${"):
        return None
    teg = await _teg(rpc, parse, bag)
    store = await _store(raw, bag) if teg is not None else None
    return None if teg is None or store is None else {"teg": teg, "store": store}


def _same(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return all(a[side][k] == b[side][k] for side, keys in (("teg", ("liquid", "staked")),
                                                           ("store", ("liquid", "staked", "events"))) for k in keys)


def _caught_up(s: Dict[str, Any]) -> bool:
    """The store holds every move the TEG has made: the two ledgers' balances agree (the projection is a float)."""
    return all(abs(s["teg"][k] - s["store"][k]) <= TOLERANCE for k in ("liquid", "staked"))


async def settled_snapshot(rpc: Callable, parse: Callable, bag: Any,
                           sleep: Callable = asyncio.sleep) -> Optional[Dict[str, Any]]:
    """A snapshot the store has caught up under: the two ledgers' balances agree. An agent that carried drift before the
    run never agrees, so for it a reading that stays unchanged (TEG balances, store balances and event count) for
    STILL_SPAN seconds settles instead. A reading that does neither within SETTLE_WAITS is returned marked
    `settled: False` (the row then says so), never passed off as a quiet one; None when a ledger could not be read."""
    s0 = await snapshot(rpc, parse, bag)
    if s0 is None:
        return None
    if _caught_up(s0):
        return {**s0, "settled": True}
    still = 0
    for wait in SETTLE_WAITS:
        await sleep(wait)
        s1 = await snapshot(rpc, parse, bag)
        if s1 is None:
            return None
        if _caught_up(s1):
            return {**s1, "settled": True}
        still = still + wait if _same(s0, s1) else 0
        if still >= STILL_SPAN:
            return {**s1, "settled": True}
        s0 = s1
    return {**s0, "settled": False}


def verdict(t0: Dict[str, Any], t1: Dict[str, Any]) -> Tuple[Optional[bool], Optional[str], Dict[str, Any]]:
    """(healthy | None for NOT MEASURED, the sentence, evidence) for the change between two snapshots."""
    d = {f"{side}_{k}": t1[side][k] - t0[side][k] for side in ("teg", "store") for k in ("liquid", "staked")}
    added = t1["store"]["events"] - t0["store"]["events"]
    ev = {k: str(v) for k, v in d.items()}
    ev["store_events_added"] = added
    if t0.get("settled") is False:
        ev["before_settled"] = False
    if d["teg_liquid"] == 0 and d["teg_staked"] == 0 and added == 0:
        return None, "NOT MEASURED: the lifecycle phase moved nothing for the run's sentinel", ev
    gaps = {k: abs(d[f"teg_{k}"] - d[f"store_{k}"]) for k in ("liquid", "staked")}
    if all(g <= TOLERANCE for g in gaps.values()):
        return True, None, ev
    if t0.get("settled") is False:
        # the before-read never held still: a gap here can be the store catching up, not a lost move
        return None, ("NOT MEASURED: the ledgers were still moving for the run's sentinel when the lifecycle phase began "
                      "(two before-reads never agreed), so a gap in the change cannot be told from the store catching "
                      "up"), ev
    return False, ("BUG-FIND: ledger: the TEG and the EventStore disagree about what the run moved for its sentinel ("
                   + ", ".join(f"{k}: TEG {d['teg_' + k]:+} vs store {d['store_' + k]:+}" for k in ("liquid", "staked"))
                   + "): a move the TEG made has no event (a dropped emit) or an event moved nothing; the supply delta "
                   "cannot see either"), ev


async def close(rpc: Callable, parse: Callable, bag: Any, t0: Optional[Dict[str, Any]], outcomes: Dict[str, dict],
                make_outcome: Callable, sleep: Callable = asyncio.sleep) -> None:
    """Read the after-snapshot (waiting for the store) and write the row."""
    if t0 is None:
        outcomes[ROW] = make_outcome(ROW, "ledger", False, "0", 0, None, {}, expect_status="any",
                                     skip_reason="NOT MEASURED: the ledgers could not be read before the lifecycle phase")
        return
    healthy, sentence, ev = None, "NOT MEASURED: the ledgers could not be read after the lifecycle phase", {}
    for wait in WAITS:
        await sleep(wait)
        t1 = await snapshot(rpc, parse, bag)
        if t1 is None:
            continue
        healthy, sentence, ev = verdict(t0, t1)
        if healthy is not False:
            break
    outcomes[ROW] = make_outcome(ROW, "ledger", bool(healthy), "0", 0, sentence if healthy is False else None, {},
                                 expect_status="any", skip_reason=sentence if healthy is None else None)
    outcomes[ROW]["result_excerpt"] = ev
