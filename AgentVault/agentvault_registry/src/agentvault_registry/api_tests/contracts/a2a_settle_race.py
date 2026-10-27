"""§MCPTEST30 (2026-10-01) — one A2A payment token pays at most once: two settles at once, and a settle racing a release.

settle claims its token with a compare-and-set (CONSUMED/AUTHORIZED -> SETTLING) before its background transfer
(routers/a2a_payment.py: "closes the double-pay race (two settles both reading CONSUMED, both firing the TEG transfer)"),
and release moves the same two states to RELEASED. Nothing in the tester raced either: the settle lifecycles settle a
self-payment once. A throwaway payer funded with dust by the run's sentinel authorizes 0.01 to the sentinel, the sentinel
verifies (consumes) it, then:
- `a2a_race: settle twice at once`: two settles at the same moment. Right: the token ends SETTLED and the payer's ledger
  holds ONE row carrying the token's settlement message (`A2A service payment (token=<id[:8]>, ...)`). The finding: two.
- `a2a_race: settle and release at once`: Right: SETTLED with one row, or RELEASED with none. The finding: RELEASED with
  a row (paid AND released), or two rows.
A token that ends FAILED (its transfer failed: a busy registry) or a ledger that cannot be read measures nothing. The
payer returns what it holds to the sentinel (less the fee) and is deleted. Dust between the run's own agents; Delta-
neutral. Rows keep counts and statuses, never a value.
"""
from __future__ import annotations

import asyncio
import secrets
import time
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any, Callable, Dict, Optional, Tuple

PREFIX = "a2a_race: "
ROW_TWICE = PREFIX + "settle twice at once"
ROW_RELEASE = PREFIX + "settle and release at once"
FUND = Decimal("0.05")
AMOUNT = "0.01"
FEE_BOUND = Decimal("1.05")   # the fee is velocity-scaled up to 5%: a sender needs at most amount x 1.05
SETTLE_WAIT_S = 20.0          # the transfer runs as a background task after the claim


def _dec(v: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(v)) if v is not None else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def settlement_marker(token_id: str) -> str:
    """The text every settlement transfer of this token carries (routers/a2a_payment.py settle_payment)."""
    return f"token={str(token_id)[:8]}"


def rows_for(transactions: Any, token_id: str) -> Optional[int]:
    """How many of the payer's ledger rows carry this token's settlement message (None: the ledger was not readable)."""
    if not isinstance(transactions, list):
        return None
    mark = settlement_marker(token_id)
    return sum(1 for t in transactions if isinstance(t, dict) and mark in str(t.get("attached_message") or ""))


def twice_verdict(status: Optional[str], rows: Optional[int]) -> Tuple[Optional[bool], Optional[str], Optional[str]]:
    """(healthy, fail, skip) for two settles at once."""
    if rows is not None and rows > 1:
        return False, (f"BUG-FIND: a2a_race: two settles of ONE payment token sent at once paid {rows} times (token "
                       f"{status or 'unread'}): the settle claim is not a single step, so a payer is charged twice"), None
    if status is None or rows is None:
        return None, None, "NOT MEASURED: the token's status or the payer's ledger could not be read after the race"
    if status == "failed":
        return None, None, "NOT MEASURED: the settlement transfer failed (a busy registry), so the race decided nothing"
    if status != "settled":
        return None, None, f"NOT MEASURED: the token ended '{status}' within {int(SETTLE_WAIT_S)} s, not settled"
    if rows == 0:
        return None, None, "NOT MEASURED: the token is settled but no ledger row carries its message yet (the list may lag)"
    return True, None, None


def release_verdict(status: Optional[str], rows: Optional[int]) -> Tuple[Optional[bool], Optional[str], Optional[str]]:
    """(healthy, fail, skip) for a settle racing a release."""
    if rows is not None and rows > 1:
        return False, (f"BUG-FIND: a2a_race: a settle racing a release paid {rows} times: one token, more than one "
                       "payment"), None
    if status == "released" and rows:
        return False, ("BUG-FIND: a2a_race: a settle and a release sent at once BOTH took effect: the token reads "
                       "released while the payer's ledger holds its payment (the payee was paid for a released token)"), None
    if status is None or rows is None:
        return None, None, "NOT MEASURED: the token's status or the payer's ledger could not be read after the race"
    if status == "settled" and rows == 1:
        return True, None, None
    if status == "released" and rows == 0:
        return True, None, None
    if status == "failed":
        return None, None, "NOT MEASURED: the settlement transfer failed (a busy registry), so the race decided nothing"
    return None, None, f"NOT MEASURED: the token ended '{status}' with {rows} ledger rows within {int(SETTLE_WAIT_S)} s"


async def run_a2a_race(rpc: Callable, parse: Callable, bag: Any, outcomes: Dict[str, dict], make_outcome: Callable,
                       answered: Callable, said: Callable, sleep: Callable = asyncio.sleep) -> None:
    t0 = time.time()
    dev = getattr(bag, "developer_jwt", "") or ""
    sentinel_jwt = getattr(bag, "sentinel_jwt", None)
    sentinel_did = getattr(bag, "sentinel_did", None)

    def row(name, healthy, fail=None, skip=None, ev=None):
        outcomes[name] = make_outcome(name, "a2a_race", bool(healthy), "0", int((time.time() - t0) * 1000), fail, {},
                                      expect_status="any", skip_reason=skip)
        outcomes[name]["result_excerpt"] = ev or {}

    def skip_both(why):
        for name in (ROW_TWICE, ROW_RELEASE):
            row(name, None, skip=why)

    if not dev or not sentinel_jwt or not sentinel_did or str(sentinel_did).startswith("${"):
        return skip_both("NOT MEASURED: the run has no sentinel agent to fund the payer and receive its payments")

    async def call(tool, args, timeout=40):
        ok, body, code = await rpc(tool, args, jwt=dev, timeout=timeout)
        inner = parse(body)
        return answered(ok, inner, code), inner, code

    tag = secrets.token_hex(6)
    ok, inner, code = await call("theprotocol_createAgent", {"name": f"mcp-a2arace-{tag}",
                                                             "description": "MCP tester A2A settle race (throwaway, deleted after)"})
    did = cid = sec = None
    if ok and isinstance(inner, dict):
        did, cid, sec = inner.get("agent_did") or inner.get("did"), inner.get("client_id"), inner.get("client_secret")
    if not (did and cid and sec):
        return skip_both(f"NOT MEASURED: no throwaway payer could be created ({said(inner)[:90]})")
    try:
        ok, tinner, code = await call("theprotocol_getAgentToken", {"client_id": cid, "client_secret": sec}, timeout=20)
        payer = (tinner.get("access_token") or tinner.get("agent_jwt")) if ok and isinstance(tinner, dict) else None
        sec = None
        if not payer:
            return skip_both("NOT MEASURED: the throwaway payer's token could not be had")
        okf, fi, _c = await call("theprotocol_transferUnits", {
            "agent_jwt": sentinel_jwt, "recipient_did": did, "amount": str(FUND),
            "message": f"MCP tester: funds an A2A settle race {tag}", "idempotency_key": f"mcptest-a2arace-fund-{tag}"})
        if not okf:
            return skip_both(f"NOT MEASURED: the payer could not be funded ({said(fi)[:90]})")

        async def authorize_and_consume() -> Tuple[Optional[str], str]:
            """(token|token_id, "") or (None, which step refused and what it said)."""
            oka, ai, _c = await call("theprotocol_authorizePayment", {
                "agent_jwt": payer, "target_agent_did": sentinel_did, "amount": AMOUNT, "ttl_seconds": 300})
            token = ai.get("token") if oka and isinstance(ai, dict) else None
            token_id = ai.get("token_id") if oka and isinstance(ai, dict) else None
            if not (token and token_id):
                return None, f"authorize refused ({said(ai)[:90]})"
            okv, vi, _c = await call("theprotocol_verifyPayment", {
                "token": token, "expected_target_did": sentinel_did, "agent_jwt": sentinel_jwt})
            if not (okv and isinstance(vi, dict) and vi.get("valid")):
                return None, f"verify refused ({said(vi)[:90]})"
            return f"{token}|{token_id}", ""

        async def settle(token):
            return await call("theprotocol_settlePayment", {"agent_jwt": payer, "token": token, "success": True})

        async def release(token):
            return await call("theprotocol_releasePayment", {"agent_jwt": payer, "token": token})

        async def outcome(token_id) -> Tuple[Optional[str], Optional[int]]:
            """The token's status once it leaves 'settling' (or the wait ends), and its ledger rows."""
            status = None
            deadline = time.time() + SETTLE_WAIT_S
            while True:
                okt, ti, _c = await call("theprotocol_getMyPaymentAuthorizations", {"agent_jwt": payer, "limit": 50}, timeout=20)
                items = ti if isinstance(ti, list) else (ti.get("tokens") or ti.get("items") if isinstance(ti, dict) else None)
                if okt and isinstance(items, list):
                    mine = [t for t in items if isinstance(t, dict) and str(t.get("token_id")) == str(token_id)]
                    status = str(mine[0].get("status")).lower() if mine else None
                if status not in ("settling", "consumed", "authorized") or time.time() > deadline:
                    break
                await sleep(2)
            await sleep(2)   # the ledger row is written by the same transfer; a moment for the list
            okl, li, _c = await call("theprotocol_getMyTegTransactions", {"agent_jwt": payer, "limit": 50}, timeout=30)
            txs = li.get("transactions") if okl and isinstance(li, dict) else None
            return status, rows_for(txs, token_id)

        # 1. two settles at once
        t1, why1 = await authorize_and_consume()
        if t1 is None:
            row(ROW_TWICE, None, skip=f"NOT MEASURED: no consumed payment token to race: {why1}")
        else:
            token, token_id = t1.split("|", 1)
            (o1, i1, c1), (o2, i2, c2) = await asyncio.gather(settle(token), settle(token))
            status, rows = await outcome(token_id)
            healthy, fail, skip = twice_verdict(status, rows)
            row(ROW_TWICE, healthy, fail, skip, {"answers": [int(o1), int(o2)], "codes": [str(c1), str(c2)],
                                                 "status": status, "ledger_rows": rows})
        # 2. a settle racing a release
        t2, why2 = await authorize_and_consume()
        if t2 is None:
            row(ROW_RELEASE, None, skip=f"NOT MEASURED: no consumed payment token to race: {why2}")
        else:
            token, token_id = t2.split("|", 1)
            (o1, i1, c1), (o2, i2, c2) = await asyncio.gather(settle(token), release(token))
            status, rows = await outcome(token_id)
            healthy, fail, skip = release_verdict(status, rows)
            row(ROW_RELEASE, healthy, fail, skip, {"settle_answered": bool(o1), "release_answered": bool(o2),
                                                   "status": status, "ledger_rows": rows})
        # what the payer holds goes back to the sentinel, less the fee
        okb, ib, _c = await call("theprotocol_getMyBalance", {"agent_jwt": payer}, timeout=20)
        held = _dec(ib.get("liquid_balance", ib.get("balance"))) if okb and isinstance(ib, dict) else None
        if held is not None and held > 0:
            back = (held / FEE_BOUND).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
            if back > 0:
                await call("theprotocol_transferUnits", {"agent_jwt": payer, "recipient_did": sentinel_did,
                                                          "amount": str(back), "message": f"MCP tester: returns {tag}",
                                                          "idempotency_key": f"mcptest-a2arace-back-{tag}"})
    finally:
        await call("theprotocol_deleteMyAgentByDev", {"agent_did": did}, timeout=30)
