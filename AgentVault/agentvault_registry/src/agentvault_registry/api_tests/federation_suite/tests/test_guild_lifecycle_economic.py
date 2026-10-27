"""Guild work order driven END TO END, with the money checked (§FEDGUILD-2).

Every other guild/contract/dispute test in this suite READS. None of them moves
value, so none of them can tell a working exchange from a well-formed façade:
each step could 200 while the bounty never leaves the poster.

This drives the real loop — create → fund → post → bid → award → submit →
verify — and then asserts the thing that actually matters: **the worker's
balance went UP by the bounty and the poster's went DOWN, and the supply
invariant did not move.** Δ is the prime directive, so an economic test that
does not check it is not finished.

Sandbox treasury funding is APPROVED for sandbox mainframes (2026-09-04) and
explicitly NOT for prod. This test is `requires`-gated to the sandbox frames and
funds through the CANONICAL admin rail (FLOW 4 `/teg/treasury/fund-agent`),
never a direct TEG mint — minting on the TEG bypasses the registry's
`TokensIssued` emission and is an instant Δ breach.

⚠ Writes: creates two agents per run, tagged `fedsuite-lifecycle-*`, and
best-effort deletes them at the end. Agent deletion is a SOFT delete that keeps
a balance, so what each holds goes back to the treasury first (throwaways, V0641).
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional, Tuple

from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
    ensure_bonded,
)

_BOUNTY = "5.0"          # dust; large enough to see, small enough to be nothing
_FUND = "50.0"


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
    # adminRequest / adminQueryEventStore WRAP the upstream call as
    # {status_code, response, ...} and return HTTP 200 for the MCP call itself.
    # Without this, a 422 from the wrapped endpoint reads as success — which is
    # exactly how a broken fund call looked like a funded agent here.
    if isinstance(r, dict) and isinstance(r.get("status_code"), int) and r["status_code"] >= 400:
        return r, f"wrapped HTTP {r['status_code']}: {json.dumps(r.get('response'))[:180]}"
    return r, _soft(r)


def _num(v: Any) -> float:
    """Balances come back in SCIENTIFIC NOTATION ('1E+3') — int() RAISES on those."""
    if v is None:
        return 0.0
    try:
        return float(str(v))
    except Exception:
        return 0.0


async def _delta(rig) -> Optional[float]:
    """Supply invariant via the EventStore. The REGISTRY does not serve
    /projections/supply-audit — that 404 is what makes the suite's existing
    treasury_supply_invariant test look like a Δ breach when it is not."""
    r, refused = await _call(rig, "sandbox-A-admin", "adminQueryEventStore",
                             {"path": "/api/v1/projections/supply-audit"})
    if refused or not isinstance(r, dict):
        return None
    # adminQueryEventStore WRAPS the payload: {ok, path, status_code, response}.
    # Reading `delta` off the wrapper yields None, which this test correctly
    # treated as "cannot guard Δ" and refused to move money — failing safe, but
    # for the wrong reason.
    body = r.get("response") if isinstance(r.get("response"), dict) else r
    d = body.get("delta")
    return None if d is None else _num(d)


async def _new_agent(rig, tag: str) -> Dict[str, str]:
    r, refused = await _call(rig, "sandbox-A", "createAgent", {
        "name": f"fedsuite-lifecycle-{tag}-{uuid.uuid4().hex[:8]}",
        "description": "federation suite guild lifecycle probe",
    })
    if refused or not isinstance(r, dict):
        raise PreconditionUnmet(f"createAgent refused for {tag}: {refused}")
    # createAgent reports its own failures as {"error": ...} with HTTP 200, so a
    # shape check alone would mislabel a real refusal as a missing credential.
    if r.get("error"):
        raise PreconditionUnmet(f"createAgent error for {tag}: {r['error']}")
    cid = r.get("client_id") or (r.get("credentials") or {}).get("client_id")
    sec = r.get("client_secret") or (r.get("credentials") or {}).get("client_secret")
    did = r.get("did") or r.get("agent_did") or (r.get("agent") or {}).get("did")
    throwaways.made("sandbox-A", did)  # V0641: retired once its test's verdict is in (throwaways)
    if not (cid and sec and did):
        raise PreconditionUnmet(
            f"createAgent for {tag} returned no usable credential triple "
            f"(keys={sorted(r)[:8]})")
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
    return {"did": did, "jwt": jwt, "client_id": cid}


async def _balance(rig, jwt: str) -> float:
    r, refused = await _call(rig, "sandbox-A", "getMyBalance", {"agent_jwt": jwt})
    if refused or not isinstance(r, dict):
        return 0.0
    for k in ("balance", "liquid_balance", "token_balance", "available"):
        if r.get(k) is not None:
            return _num(r[k])
    return 0.0



async def _order_events(rig, order_id: str) -> Optional[list]:
    """Did the EventStore actually RECORD the settlement?

    §FEDSUITE 2026-09-04 — Δ=0 is NECESSARY BUT NOT SUFFICIENT. The invariant is
    computed FROM events: drop the emit and the credit and the debit vanish
    together, circulating never moves, and Δ sits at a contented 0.0 while money
    genuinely moved in the TEG. The §VITALS session found exactly that shape live
    in `TEGBulkProxy._flush`, the ONLY site emitting TokensTransferred for
    coalesced transfers, wrapped in `except Exception: pass`.

    ⚠ QUERY BY THE ORDER, NOT BY THE WORKER. The first version of this asked for
    `/events/aggregate/{worker_did}` and got zero on BOTH frames — which looked
    exactly like "money moved unrecorded" and was very nearly filed as one.
    `TokensTransferred` is keyed on the SENDER's aggregate (the treasury), so the
    receiver's DID matches nothing; `GuildOrderSettled` is keyed on the order and
    carries payee/payout/fee. The control that caught it: the same query against
    a frame with 18,602 events returned real data, so the probe worked and the
    aggregate choice was the fault. A zero is a claim about the query until the
    query has returned non-zero.

    Returns None when the ES is unreadable — "could not check" is its own state
    and must never read as "checked and fine".

    Returns the RAW event list rather than a yes/no, so one query answers both
    questions this test asks: did the settlement name our worker, and did the
    whole lifecycle get recorded. It used to answer only the first, which left
    GuildOrderPosted / BidPlaced / OrderAwarded / WorkSubmitted uncovered even
    though this test already drives every one of them.
    """
    if not order_id:
        return None
    r, refused = await _call(rig, "sandbox-A-admin", "adminQueryEventStore",
                             {"path": f"/api/v1/events/aggregate/{order_id}"})
    if refused:
        return None
    # ⚠ Unwrap `response` WHATEVER its type. My first two attempts only unwrapped
    # a dict, but /events/aggregate/{id} answers with a LIST — so the guard fell
    # through to the wrapper, found no "events" key, and returned False. Twice
    # that read as "money moved unrecorded", which is a false alarm of the worst
    # kind: alarming, plausible, and entirely mine. Third bug from this same
    # wrapper (backlog item 2) in one session.
    body = r.get("response", r) if isinstance(r, dict) and "response" in r else r
    if isinstance(body, list):
        events = body
    elif isinstance(body, dict):
        events = body.get("events") or body.get("items") or []
    else:
        return None
    return [e for e in events if isinstance(e, dict)]


def _settled_names_worker(events: list, worker_did: str) -> bool:
    """The settlement must name THIS worker as payee, not merely exist."""
    for e in events:
        if "GuildOrderSettled" not in str(e.get("event_type") or e.get("type") or ""):
            continue
        d = e.get("data") or e.get("payload") or {}
        if isinstance(d, dict) and worker_did in (d.get("payee"), d.get("worker")):
            return True
    return False


# Every event the loop this test drives is supposed to leave behind, all keyed
# on the order id (verified against the live ES: 35 Posted / 25 BidPlaced /
# 18 Awarded / 14 WorkSubmitted / 14 Settled on sbx-alpha, all on gwo_* aggregates).
_GUILD_LIFECYCLE_EVENTS = ["GuildOrderPosted", "GuildBidPlaced", "GuildOrderAwarded",
                           "GuildWorkSubmitted", "GuildOrderSettled"]


@federation_test(
    name="guild_lifecycle_bounty_moves_end_to_end",
    category="guild_lifecycle",
    budget_sec=150.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["guild", "economic", "money", "delta"],
)
async def test_guild_lifecycle(rig: FederationTestRig) -> AssertionResult:
    """Post → bid → award → submit → verify, and the bounty actually moves.

    The assertion is on BALANCES and on Δ, not on status codes. Every step of
    this loop can return 200 while nothing settles; that is precisely the
    failure a read-only suite cannot see.
    """
    state: Dict[str, Any] = {}

    # ── arrange (outside the poller: assert_within swallows raises) ────────
    d0 = await _delta(rig)
    state["delta_before"] = d0
    if d0 is None:
        raise PreconditionUnmet("supply audit unreadable — cannot guard Δ, refusing to move money")
    if abs(d0) > 1e-9:
        # Do not add motion to a ledger that is already inconsistent.
        raise PreconditionUnmet(f"Δ is already {d0}, not 0 — refusing to run an economic test")

    poster = await _new_agent(rig, "poster")
    worker = await _new_agent(rig, "worker")
    state["poster"] = poster["did"]
    state["worker"] = worker["did"]

    fund, fref = await _call(rig, "sandbox-A-admin", "adminRequest", {
        "method": "POST", "endpoint": "/api/v1/teg/treasury/fund-agent",
        # FLOW 4's field is target_agent_did — `agent_did` 422s with
        # "Field required: body -> target_agent_did".
        "body": {"target_agent_did": poster["did"], "amount": _FUND,
                 "reason": "federation suite guild lifecycle probe"},
    })
    if fref:
        raise PreconditionUnmet(f"treasury funding refused: {fref}")

    p0 = await _balance(rig, poster["jwt"])
    w0 = await _balance(rig, worker["jwt"])
    state["poster_before"], state["worker_before"] = p0, w0
    if p0 <= 0:
        raise PreconditionUnmet(f"poster funded but balance reads {p0} — nothing to spend")

    # ── act ───────────────────────────────────────────────────────────────
    order, oref = await _call(rig, "sandbox-A", "guildPostOrder", {
        "title": f"fedsuite lifecycle {uuid.uuid4().hex[:6]}",
        "bounty": _BOUNTY, "spec": "federation suite probe", "agent_jwt": poster["jwt"]})
    if oref or not isinstance(order, dict):
        state["verdict"] = f"guildPostOrder refused: {oref}"
        return await rig.assert_within(
            budget_sec=1.0, predicate=lambda: _false(), description="post failed",
            capture_state=lambda: state)
    # guildPostOrder returns {"order_id": ...}; guildGetOrder returns
    # {"order": {"id": ...}}. Reading only `id` yielded None, so every later
    # step ran against a null order while the bounty sat escrowed — the run
    # LOOKED like "worker never paid" when the real fault was this line.
    oid = (order.get("order_id") or order.get("id")
           or (order.get("order") or {}).get("id"))
    state["order_id"] = oid
    if not oid:
        state["verdict"] = f"no order id in guildPostOrder response: {sorted(order)[:8]}"
        await _release_escrow(rig, None, poster["jwt"])
        return await rig.assert_within(
            budget_sec=1.0, predicate=_false,
            description="guildPostOrder returned no order id",
            capture_state=lambda: state)

    bid, bref = await _call(rig, "sandbox-A", "guildBid", {
        "order_id": oid, "price": _BOUNTY, "pitch": "fedsuite", "agent_jwt": worker["jwt"]})
    # ⚠ guildBid returns {ok, order_id, bidder, firm, stake_locked} — it does
    # NOT return the bid id that guildAward requires. The id is only visible by
    # re-reading the order (routers/guild.py:212 returns {order, bids, events}).
    # A read-only suite can never surface that; the award simply fails with
    # "order_id and bid_id are required" and looks like a caller mistake.
    bid_id = None
    detail, dref = await _call(rig, "sandbox-A", "guildGetOrder", {"order_id": oid})
    if isinstance(detail, dict):
        for b in (detail.get("bids") or []):
            if isinstance(b, dict) and (
                b.get("bidder_did") == worker["did"] or b.get("bidder") == worker["did"]
            ):
                bid_id = b.get("id")
                break
        if bid_id is None:                      # single-bid order: take the only one
            bids = [b for b in (detail.get("bids") or []) if isinstance(b, dict)]
            if len(bids) == 1:
                bid_id = bids[0].get("id")
    state["bid"] = {"id": bid_id, "post_refused": bref, "lookup_refused": dref,
                    "bids_seen": len((detail or {}).get("bids") or [])}

    aw, aref = await _call(rig, "sandbox-A", "guildAward",
                           {"order_id": oid, "bid_id": bid_id, "agent_jwt": poster["jwt"]})
    state["award_refused"] = aref
    sub, sref = await _call(rig, "sandbox-A", "guildSubmitWork", {
        "order_id": oid, "deliverable_text": "fedsuite deliverable", "agent_jwt": worker["jwt"]})
    state["submit_refused"] = sref
    ver, vref = await _call(rig, "sandbox-A", "guildVerify", {
        "order_id": oid, "accept": True, "stars": 5, "agent_jwt": poster["jwt"]})
    state["verify_refused"] = vref

    # ── assert: the MONEY, and Δ ──────────────────────────────────────────
    async def predicate():
        w1 = await _balance(rig, worker["jwt"])
        p1 = await _balance(rig, poster["jwt"])
        d1 = await _delta(rig)
        state["worker_after"], state["poster_after"], state["delta_after"] = w1, p1, d1
        state["worker_gain"] = round(w1 - w0, 6)
        state["poster_spend"] = round(p0 - p1, 6)
        bounty = _num(_BOUNTY)
        # Worker gains the bounty net of fee, so require a real gain bounded by
        # the bounty rather than an exact equality the fee would break.
        gained = 0 < (w1 - w0) <= bounty + 1e-9
        paid = (p0 - p1) > 0
        delta_ok = d1 is not None and abs(d1) < 1e-9
        # The ledger must have SEEN it. Δ alone cannot tell a settled transfer
        # from a silently un-emitted one — both leave Δ at 0.
        evs = await _order_events(rig, oid) if gained else None
        if evs is None:
            evented = missing = seen = None      # unreadable ≠ absent
        else:
            seen = sorted({str(e.get("event_type") or e.get("type") or "") for e in evs})
            missing = [t for t in _GUILD_LIFECYCLE_EVENTS if t not in seen]
            # the settlement must additionally NAME our worker
            evented = (not missing) and _settled_names_worker(evs, worker["did"])
        state["verdict"] = {"worker_gained": gained, "poster_paid": paid,
                            "delta_zero": delta_ok, "events_seen": seen,
                            "events_missing": missing, "evented": evented}
        return bool(gained and paid and delta_ok and evented is True)

    result = await rig.assert_within(
        budget_sec=90.0, predicate=predicate, poll_interval_sec=3.0,
        description="guild bounty moves poster→worker and Δ stays 0",
        capture_state=lambda: state,
    )

    # If the bounty never reached the worker the order did not settle — release
    # the escrow rather than leaving it parked.
    if not result.passed:
        await _release_escrow(rig, oid, poster["jwt"])

    # ── best-effort cleanup: V0641, what each holds goes back to the treasury, then the soft delete ──
    # deleteMyAgent is AUTH-SCOPED and takes no DID — deleting a named agent as
    # the developer is deleteMyAgentByDev. Passing agent_did to the former would
    # have silently done nothing and left this run's agents behind every time.
    for who in (poster, worker):
        await throwaways.retire(rig, "sandbox-A", who["did"])
    return result


async def _false() -> bool:
    return False


async def _release_escrow(rig, order_id: Optional[str], poster_jwt: str) -> None:
    """Cancel an unsettled order so its bounty leaves escrow.

    A test that escrows real value and then bails must hand it back; otherwise
    every failing run strands a little more money in `open` orders and the next
    person reads the residue as product behaviour.
    """
    if not order_id:
        return
    await _call(rig, "sandbox-A", "guildCancelOrder",
                {"order_id": order_id, "agent_jwt": poster_jwt})
