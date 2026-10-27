"""§MCPTEST30 (V0525, 2026-10-01) — two spends at once that the balance can cover only one of: one moves, never both.

The idempotency probes race ONE key; nothing raced two DIFFERENT keys against one balance, which is the overdraft (a
double spend): each request reads the balance, both see enough, both move. Measured by hand on sbx-alpha (V0523) before
this probe existed: a throwaway agent funded 0.05 sent two transfers of 0.03 at once, one moved and the other was refused
"Insufficient balance: have 0.01985, need 0.030150" (the TEG serializes the spender), and the ledger held one. This holds
that line on every run.

The spender is a THROWAWAY agent the probe creates (nobody else knows its DID, so nothing else pays it while it races),
funded 0.05 by the run's sentinel. It sends the sentinel two transfers AT ONCE, each 60% of its balance, with different
idempotency keys and one message. Right: one answered, one refused, the spender's ledger holds one, its balance never
below zero. Two answered, two in the spender's ledger, or a negative balance is the finding. Afterwards the spender
sends what it holds back to the sentinel (less the fee) and is deleted. Dust between the run's own agents; Delta-neutral.
Row `overdraft: transferUnits`; it keeps counts and statuses, never a value.

V0545: one strict run (2026-10-02 04:05Z) lost the spender's token: the registry answered /auth/agent/token 200 and
the tester's call came back with no HTTP status at all, and the row said only "could not be had". A lost answer (no
status) is asked once more, a refusal is not, and the row now names which of the two it met.
"""
from __future__ import annotations

import asyncio
import secrets
import time
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any, Callable, Dict, Optional

PREFIX = "overdraft: "
ROW = PREFIX + "transferUnits"
FUND = Decimal("0.05")
SHARE = Decimal("0.6")
FEE_BOUND = Decimal("1.005")   # the base fee is 0.5%: a sender needs amount x 1.005


def _dec(v: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(v)) if v is not None else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def answer_lost(code: Any) -> bool:
    """No HTTP status came back: the call's own transport lost the answer (curl's 000, an exec that ended without it)."""
    c = str(code or "").strip()
    return not (len(c) == 3 and c.isdigit()) or c == "000"


# §MCPTEST30 (V0553): a completed funding transfer is read back up to BALANCE_READS times, BALANCE_READ_WAIT seconds apart,
# before the spender's balance is judged (round 19 read it once and printed "could not be funded" over a completed transfer)
BALANCE_READS = 3
BALANCE_READ_WAIT = 1.0


def funding_shortfall(funded: bool, answer: str, balance: Optional[Decimal], reads: int) -> Optional[str]:
    """None when the funded spender holds a balance; else the NOT MEASURED sentence naming what was SEEN (a refused
    transfer, a balance that could not be read, a balance that read zero or less), never a cause."""
    if not funded:
        return f"NOT MEASURED: the spender could not be funded (the transfer answered: {answer[:100]})"
    if balance is None:
        return f"NOT MEASURED: the funding transfer completed, but the spender's balance could not be read ({reads} read(s))"
    if balance <= 0:
        return f"NOT MEASURED: the funding transfer completed, but the spender's balance read {balance}, {reads} time(s)"
    return None


def race_amount(balance: Decimal) -> Decimal:
    """Each of the two transfers: 60% of the balance (one fits with its fee, two cannot), to the micro-unit."""
    return (balance * SHARE).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)


def verdict(answered: int, own_out: Optional[int], after: Optional[Decimal], refusals: list) -> tuple:
    """(healthy, fail, skip). `answered` of the two transfers came back accepted; `own_out` = the spender's ledger rows
    with the race message; `after` = its balance after."""
    if answered == 2 or (own_out is not None and own_out > 1) or (after is not None and after < 0):
        return False, (f"BUG-FIND: overdraft: two transfers sent at once that the balance covered only one of BOTH moved "
                       f"(answered {answered}, ledger rows {own_out}, balance after {'below zero' if after is not None and after < 0 else 'not below zero'}): "
                       "the spender's balance check and its debit are not one step"), None
    if answered == 0:
        return False, None, ("NOT MEASURED: neither transfer moved (" + "; ".join(refusals)[:160] + ")")
    if own_out is None or after is None:
        return False, None, "NOT MEASURED: the spender's ledger or balance could not be read after the race"
    if own_out == 0:
        return False, None, "NOT MEASURED: the spender's ledger holds no row with the race message (the list may lag)"
    return True, None, None


async def run_overdraft(rpc: Callable, parse: Callable, bag: Any, outcomes: Dict[str, dict], make_outcome: Callable,
                        answered: Callable, said: Callable) -> None:
    t0 = time.time()
    dev = getattr(bag, "developer_jwt", "") or ""
    sentinel_jwt = getattr(bag, "sentinel_jwt", None)
    sentinel_did = getattr(bag, "sentinel_did", None)

    def row(ok, fail=None, skip=None, code="0", ev=None):
        outcomes[ROW] = make_outcome(ROW, "overdraft", ok, str(code), int((time.time() - t0) * 1000), fail, {},
                                     expect_status="success", skip_reason=skip)
        outcomes[ROW]["result_excerpt"] = ev or {}

    if not dev or not sentinel_jwt or not sentinel_did or str(sentinel_did).startswith("${"):
        return row(False, skip="NOT MEASURED: the run has no sentinel agent to fund the spender")

    async def call(tool, args, timeout=40):
        ok, body, code = await rpc(tool, args, jwt=dev, timeout=timeout)
        inner = parse(body)
        return answered(ok, inner, code), inner, code

    tag = secrets.token_hex(6)
    ok, inner, code = await call("theprotocol_createAgent", {"name": f"mcp-ovr-{tag}",
                                                             "description": "MCP tester overdraft race (throwaway, deleted after)"})
    did = cid = sec = None
    if ok and isinstance(inner, dict):
        did, cid, sec = inner.get("agent_did") or inner.get("did"), inner.get("client_id"), inner.get("client_secret")
    if not (did and cid and sec):
        return row(False, skip=f"NOT MEASURED: no throwaway spender could be created ({said(inner)[:100]})", code=code)
    ev: Dict[str, Any] = {}
    try:
        spender, attempts = None, 0
        while attempts < 2:
            attempts += 1
            ok, tinner, code = await call("theprotocol_getAgentToken", {"client_id": cid, "client_secret": sec}, timeout=20)
            spender = (tinner.get("access_token") or tinner.get("agent_jwt")) if ok and isinstance(tinner, dict) else None
            if spender or not answer_lost(code):
                break          # a token, or the registry's own answer: a refusal is an answer and is not asked twice
        sec = None
        if attempts > 1:
            ev["token_attempts"] = attempts
        if not spender:
            got = (f"HTTP {code}: {said(tinner)[:100]}" if not answer_lost(code)
                   else f"no HTTP status came back, {attempts} time(s): {said(tinner)[:100]}")
            return row(False, skip=f"NOT MEASURED: the throwaway spender's token could not be had ({got})", code=code,
                       ev=ev)

        async def balance() -> Optional[Decimal]:
            okb, ib, _c = await call("theprotocol_getMyBalance", {"agent_jwt": spender}, timeout=20)
            return _dec(ib.get("liquid_balance", ib.get("balance"))) if okb and isinstance(ib, dict) else None

        okf, fi, codef = await call("theprotocol_transferUnits", {
            "agent_jwt": sentinel_jwt, "recipient_did": did, "amount": str(FUND),
            "message": f"MCP tester: funds an overdraft race {tag}", "idempotency_key": f"mcptest-ovr-fund-{tag}"})
        ev["funded"] = bool(okf)
        b0, reads = None, 0
        while okf and reads < BALANCE_READS:
            if reads:
                await asyncio.sleep(BALANCE_READ_WAIT)
            reads += 1
            b0 = await balance()
            if b0 is not None and b0 > 0:
                break
        if reads > 1:
            ev["balance_reads"] = reads
        shortfall = funding_shortfall(bool(okf), said(fi), b0, reads)
        if shortfall:
            return row(False, skip=shortfall, code=codef, ev=ev)
        amount = race_amount(b0)
        message = f"MCP tester: an overdraft race {tag}"
        legs = [{"agent_jwt": spender, "recipient_did": sentinel_did, "amount": str(amount), "message": message,
                 "idempotency_key": f"mcptest-ovr-{tag}-{i}"} for i in (1, 2)]
        (o1, i1, c1), (o2, i2, c2) = await asyncio.gather(call("theprotocol_transferUnits", legs[0]),
                                                          call("theprotocol_transferUnits", legs[1]))
        after = await balance()
        okl, li, _c = await call("theprotocol_getMyTegTransactions", {"agent_jwt": spender, "limit": 50}, timeout=30)
        rows = li.get("transactions") if okl and isinstance(li, dict) else None
        own_out = (sum(1 for t in rows if isinstance(t, dict) and t.get("attached_message") == message)
                   if isinstance(rows, list) else None)
        refusals = [said(i)[:80] for o, i in ((o1, i1), (o2, i2)) if not o]
        ev.update({"answered": int(o1) + int(o2), "ledger_rows": own_out,
                   "balance_after_not_negative": None if after is None else after >= 0,
                   "refused_for_balance": sum(1 for r in refusals if "nsufficient" in r)})
        healthy, fail, skip = verdict(int(o1) + int(o2), own_out, after, refusals)
        row(healthy, fail=fail, skip=skip, code=c1 if o1 else c2, ev=ev)
        # what the spender holds goes back to the sentinel, less the fee
        if after is not None and after > 0:
            back = (after / FEE_BOUND).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
            if back > 0:
                await call("theprotocol_transferUnits", {"agent_jwt": spender, "recipient_did": sentinel_did,
                                                          "amount": str(back), "message": f"MCP tester: returns {tag}",
                                                          "idempotency_key": f"mcptest-ovr-back-{tag}"})
    finally:
        okd, di, _c = await call("theprotocol_deleteMyAgentByDev", {"agent_did": did}, timeout=30)
        ev["spender_deleted"] = bool(okd)
        if ROW in outcomes:
            outcomes[ROW]["result_excerpt"] = ev
