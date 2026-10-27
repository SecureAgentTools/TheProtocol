"""THE OPERATOR↔PARENT-FRAME MONEY RAIL, driven in both directions (§FEDSKIPS).

A cloud operator is a satellite registry with its OWN TEG, inside its parent
frame's trust domain and currency. Value moving between an operator-homed agent
and a frame-homed agent therefore crosses a REGISTRY boundary but not a currency
boundary — the commonest shape in this topology (13 operators in prod, 2 here),
and the suite drove it nowhere.

WHAT WAS THERE BEFORE. Two `critical` rows named
`cross_cloud_op_transfer_alpha_to_delta` / `_delta_to_alpha` read as if they
moved money. They do not: they poll `getCanaryStatus` for "path active + ≥1
passed run in 24h". On a tier with no canary paths they skip, and on a tier WITH
them they assert that a background fixture fired — never that this rail carries
value. A test named for an act it does not perform is worse than no test,
because the row reads green and the rail is unmeasured.

WHY BOTH DIRECTIONS. They do not take the same code path, which is only visible
if you drive both:
  frame → operator  routes the synchronous 2PC (prepare/commit against the
                    peer TEG) and settles inside a second;
  operator → frame  falls back to the ASYNC saga (`/cross-teg/lock-async`),
                    which debits the sender immediately and leaves delivery to
                    events crossing to the receiver's frame.

⚠ AND THE ASYNC LEG IS WHERE Δ CANNOT HELP YOU. The lock debits into a
cross-frame escrow system account, which the invariant files under `transit_net`
— Δ-neutral by construction. So an async transfer that never arrives shows a
debited sender, an uncredited receiver, and Δ = 0.0 on both frames. Asserting
the RECEIVER's balance is the only thing that can see it (§S4: balances moved
AND Δ=0 is not proof of settlement).

⚠ A FRESH REMOTE AGENT IS UNRESOLVABLE UNTIL ITS CARD FEDERATES. The sender's
registry resolves receiver DID → home registry from federated cards, so a
receiver created seconds earlier answers "Cannot resolve registry for receiver"
— a timing fact, not a broken rail. Measured on this tier: the card lands within
~25 s when the sync rail is nudged. Handled as a precondition with its own
budget, never as a failure.

Sandbox treasury funding is APPROVED for sandbox mainframes (2026-09-04) and
explicitly NOT for prod; `requires`-gated to the sandbox labels and funded
through the canonical admin rail (FLOW 4), never a direct TEG mint. Dust only.
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
import re
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, DeferredCheck, PreconditionUnmet, SANDBOX_REGISTRIES,
)
from agentvault_registry.api_tests.federation_suite.tests.test_ironkey_authority_clamp import (
    _cleanup, _new_agent, _rest, _detail,
)

_SEED = "40.0"
_AMOUNT = 2.0
_FEE_RATE = 0.005          # 0.5% cross-registry fee, charged to the sender
_EXPECTED_CREDIT = _AMOUNT * (1 - _FEE_RATE)


def _num(v: Any) -> Optional[float]:
    """Balances come back in SCIENTIFIC NOTATION ('1E+3') — int() RAISES."""
    if v is None:
        return None
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return None


async def _bal(rig, label: str, jwt: str) -> Optional[float]:
    """Agent's own balance, or None for UNREADABLE.

    None is a third state on purpose: a probe that cannot read must never be
    allowed to read as "checked, and it is zero" — that is the exact shape that
    turns an instrument failure into a fabricated defect report.
    """
    code, body = await _rest(rig, "GET", "/api/v1/teg/balance",
                             label=label + "-admin", jwt=jwt)
    if code != 200 or not isinstance(body, dict):
        return None
    return _num(body.get("balance"))


async def _fund(rig, label: str, did: str) -> None:
    code, body = await _rest(rig, "POST", "/api/v1/teg/treasury/fund-agent",
                             label=label + "-admin",
                             body={"target_agent_did": did, "amount": _SEED,
                                   "reason": "fedsuite operator money-rail probe"})
    if code != 200:
        raise PreconditionUnmet(
            f"cannot seed the sender on {label}: HTTP {code} {_detail(body)[:160]}")


async def _delta(rig, label: str) -> Optional[float]:
    """Supply invariant on `label`'s frame. None = unreadable, its own state."""
    try:
        r = await rig.mcp(label + "-admin").call(
            "adminQueryEventStore", {"path": "/api/v1/projections/supply-audit"},
            timeout=40)
    except Exception:                                        # noqa: BLE001
        return None
    body = r.get("response") if isinstance(r, dict) and isinstance(r.get("response"), dict) else r
    if not isinstance(body, dict):
        return None
    return _num(body.get("delta"))


async def _nudge(rig, labels) -> None:
    """Ask the frames to federate NOW rather than waiting out the interval.

    Dual-auth admin rail, rate limited 1 per 30 s, so a 429 is expected and
    every outcome is ignored: this only accelerates the poll that decides.
    """
    for lab in labels:
        try:
            await _rest(rig, "POST", "/api/v1/federation/sync/trigger", label=lab, body={})
        except Exception:                                    # noqa: BLE001
            pass


def _spec(label: str):
    return SANDBOX_REGISTRIES.get(label) or SANDBOX_REGISTRIES.get(label.replace("-admin", ""))


def _gateway_label_for(send: str) -> Optional[str]:
    """The PARENT frame of an operator (None for a frame): where its route converts, or where it is delivered.

    An operator holds no reserves: it ingresses 1:1 to its PARENT frame's
    @fx_router and the parent converts. The parent then DELEGATES delivery to the
    receiver's parent frame (§FXPOSTCONV, 2026-09-26: an earlier reading said the
    parent delivers, and a receiver on the peer's OPERATOR was waited for at the
    wrong frame). So the sender's parent resolves the receiver to choose the
    currency, and the receiver's parent must resolve it to deliver: a receiver
    on the peer's operator is TWO federation hops from each.
    """
    sp = _spec(send)
    if not sp or getattr(sp, "role", "") != "cloud-op":
        return None
    return "sandbox-A" if getattr(sp, "frame", "") == "frame-a" else "sandbox-B"


# THREE federation-sync cycles. The interval is 120 s on this tier (measured on
# both a frame and an operator), the card must cross TWO hops, and the worst
# direction measured 166 s ≈ 1.4 cycles on an idle tier — under a full suite the
# sync competes with everything else. 240 s (2 cycles) was not enough on the
# first run after the wait landed: one direction reported "never reached". The
# cost of the larger budget is paid ONLY when the card genuinely has not
# arrived, which is exactly the case where the old code spent 8.0 finding out.
_CARD_WAIT_SEC = float(os.environ.get("FEDSUITE_CARD_WAIT_SEC", "360") or 360)


def _card_path(did: str) -> str:
    """The one card read by DID (`GET /agent-cards/{did}`): the resolver every lookup uses, mirrors and unlisted cards
    included, 404 until the frame holds the card."""
    return "/api/v1/agent-cards/" + urllib.parse.quote(did, safe=":")


async def _await_card_at(rig, label: str, did: str, state: Dict[str, Any],
                         budget_sec: float = _CARD_WAIT_SEC) -> bool:
    """Wait for `did`'s card to reach `label`, by reading that card — no money.

    §FXROUTEWAIT 2026-09-06 — THE MEASUREMENT THAT MADE THIS NECESSARY. An
    operator-homed card takes 58 s to become resolvable on one peer frame and
    166 s on the other (measured both directions on this tier, 2026-09-06). The
    drive's FX retry loop sleeps ~42 s in total, so it was ALWAYS going to run
    out — and every one of its four attempts moved 2.0 into the gateway's
    @fx_router that nothing gives back (findings row 86). Both directions of the
    federation suite reported `sender is SHORT by 8.0` on the run that first
    measured it.

    So the waiting is done HERE, where it is free: one read of the card by DID
    asks the gateway "do you have this card yet", which is exactly the state the
    FX route will need. Wait first, spend once.

    §ECHO-2 (2026-09-28): this read used to be ONE page of the index feed
    (`limit=200&updated_since=now-30min`, oldest first), and a page is blind past
    its cap. The daily digest read-repair walk rewrote ~4,500 mirrors on sbx-beta
    at 14:11Z, the page then ended at 14:11:19, and a card that had arrived at
    14:29:39 (20 s after its birth) read as "never reached within 360 s" (V0484
    nightly, federation run 4dba8bdad0234627). A read by DID has no cap for a
    burst to fill.
    """
    t0 = time.time()
    cycles = 0
    while time.time() - t0 < budget_sec:
        cycles += 1
        code, body = await _rest(rig, "GET", _card_path(did), label=label + "-admin")
        # ATTRIBUTE THE WAIT. Without this, a broken probe (wrong label, a 401, a
        # transport error) is indistinguishable from a card that never arrived —
        # and the test would report "the card never reached the gateway" while
        # measuring itself. 404 is the one answer that means "not here yet".
        state["card_probe_last_status"] = code
        if (code == 200 and isinstance(body, dict) and body.get("agent_did") == did
                and body.get("is_active") is not False):
            state["card_reached_gateway_after_sec"] = round(time.time() - t0, 1)
            state["card_wait_cycles"] = cycles
            return True
        if cycles % 2 == 0:
            await _nudge(rig, [label + "-admin"])
        await asyncio.sleep(12)
    state["card_reached_gateway_after_sec"] = None
    state["card_wait_cycles"] = cycles
    return False


async def _drive(rig, send: str, recv: str, state: Dict[str, Any]) -> Dict[str, str]:
    """Create both agents, seed the sender, and POST the transfer.

    Returns the two agents. Raises PreconditionUnmet for anything the ENVIRONMENT
    could not supply (unfederated card, absent FX booth on a cross-currency pair);
    a transfer the rail ACCEPTS and then fails to deliver is not a precondition —
    it is what the caller asserts on.
    """
    b = await _new_agent(rig, "opmoney-recv", label=recv)
    a = await _new_agent(rig, "opmoney-send", label=send)
    state["sender"], state["receiver"] = a["did"], b["did"]
    await _fund(rig, send, a["did"])
    await _nudge(rig, [send + "-admin", recv + "-admin"])

    # §FXROUTEWAIT — for an operator's CROSS-FRAME leg, the sender's PARENT frame
    # is what resolves and delivers the receiver. Wait for the card to reach it
    # before any money moves: the wait is free and each money attempt is not.
    _gw = _gateway_label_for(send)
    if _gw and getattr(_spec(send), "frame", "") != getattr(_spec(recv), "frame", ""):
        state["gateway_label"] = _gw
        state["card_at_gateway"] = await _await_card_at(rig, _gw, b["did"], state)
        if not state["card_at_gateway"]:
            raise PreconditionUnmet(
                f"{b['did']} (on {recv}) never reached its delivering frame {_gw} within "
                f"the wait; the FX route would refuse with a 409 that is indistinguishable "
                f"from a broken leg, and each attempt would park an ingress at "
                f"{_gw}'s @fx_router. NO FUNDS MOVED — this is the wait, not the transfer. "
                f"Measured 2026-09-06 on this tier: an operator-homed card reaches one peer "
                f"frame in 58 s and the other in 166 s, so a slower cycle here is a "
                f"federation-sync question, not a money one.")

    # §FXPOSTCONV (2026-09-26): the parent CONVERTS, but the PEER frame DELIVERS: the parent delegates the egress
    # to it (`_fx_route_delegate(gd_url, ...)` in routers/teg_integration.py). A receiver homed on the peer's
    # OPERATOR must therefore ALSO have reached the peer frame, or the delivery fails after the conversion.
    # Measured: every nightly since 09-23 stranded one alpha->delta route exactly so (the retry 14 s later
    # settled, so the row read green), and until V0454 the peer then refunded the origin in the wrong currency.
    _gd = _gateway_label_for(recv)
    if _gw and _gd and _gd != _gw and getattr(_spec(send), "frame", "") != getattr(_spec(recv), "frame", ""):
        state["card_wait_at_gateway"] = {k: state.get(k) for k in ("card_reached_gateway_after_sec", "card_wait_cycles")}
        state["delivering_label"] = _gd
        state["card_at_delivering_frame"] = await _await_card_at(rig, _gd, b["did"], state)
        if not state["card_at_delivering_frame"]:
            raise PreconditionUnmet(
                f"{b['did']} (on {recv}) never reached the frame that delivers it ({_gd}) within the wait; "
                f"the route would convert and then fail at delivery. NO FUNDS MOVED: this is the wait, "
                f"not the transfer.")

    state["sender_before"] = await _bal(rig, send, a["jwt"])
    state["receiver_before"] = await _bal(rig, recv, b["jwt"])

    code, body = -1, None
    for attempt in range(10):
        code, body = await _rest(rig, "POST", "/api/v1/teg/cross-registry-transfer",
                                 label=send + "-admin", jwt=a["jwt"],
                                 body={"receiver_did": b["did"], "amount": str(_AMOUNT),
                                       "message": "fedsuite operator money-rail probe"})
        state["transfer_attempts"] = attempt + 1
        if code in (200, 201, 202):
            break
        d = _detail(body).lower()
        if code == 400 and "cannot resolve registry" in d:
            await asyncio.sleep(14)
            if attempt % 3 == 2:
                await _nudge(rig, [send + "-admin", recv + "-admin"])
            continue
        # §SBXFXROUTE 2026-09-06 — a CROSS-CURRENCY leg from an operator routes
        # through its parent frame, and the parent must resolve the receiver's DID
        # to deliver the egress. The receiver was created seconds ago, so on the
        # first attempt the parent frequently has not pulled its card yet and the
        # whole route answers one generic 409. Measured by hand on this tier: the
        # identical transfer settled (3 SBXA -> 2.951249 SBXB) once the card had
        # reached the gateway, so a single 409 says "too early", not "broken".
        #
        # ⚠ The bound is 3, not 10 like the branch above, and the difference is
        # MONEY. A 400 refuses before anything moves; this 409 arrives AFTER the
        # 1:1 ingress has already moved funds to the gateway's @fx_router, and a
        # transport-or-resolution failure there has no compensation path — every
        # extra attempt parks another ingress (measured: router_liquid 0 -> 1.99
        # -> 4.975 -> 6.965, with Δ=0.0 on both frames throughout, which is
        # exactly what a supply invariant cannot see). Three is enough to clear
        # propagation and cheap enough to leave behind.
        # §FXROUTEWAIT — WAS `attempt < 3`, NOW 1. The retries existed to outlast
        # card propagation, and they could not: they sleep ~42 s against a 58-166 s
        # arrival, so all four failed and parked 2.0 each (SHORT by 8.0, measured
        # both directions). The wait above now does that job for free, and this
        # single retry covers only the jitter between "the card is listed" and
        # "the gateway's resolver sees it". Lowering the bound is the safe
        # direction: NEVER raise it to make a row green — that is paid for in
        # money nothing sweeps.
        if code == 409 and "fx route did not settle" in d and attempt < 1:
            state["fx_route_retried"] = attempt + 1
            await _nudge(rig, [send + "-admin", recv + "-admin"])
            await asyncio.sleep(14)
            continue
        break

    state["transfer_status"] = code
    # §SBXFXROUTE 2026-09-06 — the rail states what it credited; take that instead of
    # re-deriving it. `_EXPECTED_CREDIT` is amount less the 0.5% cross-registry fee,
    # which is the SAME-CURRENCY answer. A cross-currency leg arrives CONVERTED, so
    # the figure is a market quantity: measured, a settled 2.0 SBXB delivered
    # 1.983240 SBXA, and the assertion below polled 29 times past money that was
    # already in the receiver's TEG (credited at 17:55:09.31, the same instant the
    # route reported SETTLED) purely because 1.98324 < 1.99. Re-deriving the rate
    # here would just be a second implementation of the pool's arithmetic.
    if isinstance(body, dict):
        _cred = body.get("credited_amount")
        if _cred is not None:
            try:
                _credf = float(str(_cred))
                if _credf > 0:
                    state["settled_credited"] = _credf
            except (TypeError, ValueError):
                pass
    state["transfer_detail"] = _detail(body)[:240]
    if code not in (200, 201, 202):
        d = _detail(body)
        if "fx route did not settle" in d.lower():
            # Distinct from the "no booth configured" case below: the route RAN
            # and did not complete. Name what the caller can and cannot tell
            # apart, because the 409 is identical for a card that has not
            # propagated and for a genuinely broken leg — the gateway's own log
            # is the only place the two separate ([FX-ROUTE] delegate ... -> 401
            # / 409 "cannot resolve <did> from this frame").
            #
            # §FXREFUND 2026-09-06 — AND READ WHAT THE FAILURE COST THE SENDER.
            # The rail answers "the gateway compensates pre-conversion" and the
            # origin emits FxRouteRefunded carrying a hop noted "ingress refunded
            # by gateway (pre-conversion failure)". That claim is true only when
            # the gateway failed INSIDE the FX core, where it calls
            # _fx_route_refund_to_origin (which refunds, or writes a dead-letter
            # the keeper drains). Every raise ABOVE that point refunds nothing and
            # writes no dead-letter — including the commonest one, "FX route
            # egress: cannot resolve <did> from this frame", which is what a
            # receiver whose card has not reached the gateway produces. The
            # ingress has already moved by then.
            #
            # Measured on this tier (route 877bb279-..., 2026-09-06): sender funded
            # 50, transferred 2, holds 48; ONE TokensTransferred exists for the
            # route (the ingress) and the FxRouteRefunded beside it claims the
            # reversal. Δ=0 on both frames throughout — both legs are within-frame
            # and file under transit_net, which is exactly what the invariant
            # cannot see (§S4: balances moved AND Δ=0 is not proof).
            #
            # One balance read costs the run nothing (the failure already
            # happened) and turns a skip that says "did not settle" into a skip
            # that says whether the money came back.
            _after = await _bal(rig, send, a["jwt"])
            state["sender_after_failed_route"] = _after
            _before = state.get("sender_before")
            _whole = None
            if _after is not None and _before is not None:
                _whole = abs(_after - _before) < 1e-6
                state["sender_made_whole"] = _whole
                state["sender_short_by"] = round(_before - _after, 6)
            raise PreconditionUnmet(
                f"{send}→{recv} is cross-currency and its FX route did not settle in "
                f"{state.get('transfer_attempts')} attempts: {d[:160]} — read the "
                f"parent frame's [FX-ROUTE] log lines to tell propagation from a "
                f"broken leg; the ingress of each attempt is parked at the gateway's "
                f"@fx_router (GET /api/v1/teg/fx/route/status)"
                + ("" if _whole is None else
                   (" — the sender WAS made whole" if _whole else
                    f" — ⚠ the sender is SHORT by {state.get('sender_short_by')}, and the "
                    f"FxRouteRefunded this route emitted claims the gateway compensated "
                    f"it; no reversing transfer exists")))
        if "fx route ingress failed (no funds moved)" in d.lower():
            # §FXREFUND 2026-09-06 — the THIRD shape this rail produces, and the only
            # clean one: the ingress 2pc leg was refused BEFORE any value moved, so
            # nothing is parked at the gateway's @fx_router and no phantom refund
            # reaches the ledger. It used to arrive as `unclassified`, a word that
            # says nothing about the most informative outcome the rail has.
            # Whatever the leg's own status was, "no funds moved" is the fact that
            # distinguishes it, so it is what the code is named for.
            raise PreconditionUnmet(
                f"{send}→{recv} FX route ingress was refused before any funds moved "
                f"(HTTP {code}): {d[:180]} — nothing is parked at the gateway's "
                f"@fx_router for this attempt. The leg's own status is the reason: "
                f"402 = the sender holds no balance; a 4xx from the target TEG = a "
                f"posture on the GATEWAY's TEG (bond, allowlist, suspension), which "
                f"is read in that TEG's log, not the sender's")
        if "fx swap booth" in d.lower() or "FX_ENABLED" in d:
            # Cross-CURRENCY pair. Every cloud operator ships FX_ENABLED,
            # FX_ROUTE_PEERS and TEG_SIDECAR_MAP unset (measured 2026-09-04 on
            # all 7 running operators, prod included), so an operator can never
            # originate a swap. A config absence, not a broken rail.
            raise PreconditionUnmet(
                f"{send}→{recv} is cross-currency and the sending registry has no FX "
                f"booth configured (operators ship FX_ENABLED unset): HTTP {code} {d[:140]}")
        if code == 400 and "cannot resolve registry" in d.lower():
            raise PreconditionUnmet(
                f"receiver card never federated to {send} in "
                f"{state.get('transfer_attempts')} attempts: {d[:140]}")
        raise PreconditionUnmet(
            f"{send}→{recv} transfer refused: HTTP {code} {d[:180]}")
    return {"a": a, "b": b}


async def _assert_credited(rig, send: str, recv: str, agents, state, budget: float):
    """The RECEIVER is credited — the only assertion the async leg cannot fake."""
    a, b = agents["a"], agents["b"]

    async def predicate():
        state["sender_after"] = await _bal(rig, send, a["jwt"])
        got = await _bal(rig, recv, b["jwt"])
        state["receiver_after"] = got
        if got is None:
            return False                       # unreadable — keep polling, never pass
        before = state.get("receiver_before") or 0.0
        # The rail's own `credited_amount` when it gave one (the only figure that is
        # right for a converted cross-currency leg), else the same-currency
        # arithmetic. Never zero: an expectation of 0 would pass on arrival of
        # nothing, which is the shape of a test that cannot fail.
        expected = state.get("settled_credited") or _EXPECTED_CREDIT
        state["expected_credit"] = expected
        return (got - before) >= expected - 1e-6

    res = await rig.assert_within(
        budget_sec=budget, predicate=predicate, poll_interval_sec=5.0,
        description=f"{send}→{recv}: receiver credited ≥"
                    f"{state.get('settled_credited') or _EXPECTED_CREDIT} "
                    f"({'the amount the rail says it credited' if state.get('settled_credited') else f'amount {_AMOUNT} less the 0.5% cross-registry fee'})",
        capture_state=lambda: state,
    )
    # Δ is recorded on BOTH frames but is NOT the verdict: the escrow leg is
    # transit-neutral, so Δ reads 0.0 whether or not the money ever arrives.
    state["delta_send_frame"] = await _delta(rig, send)
    state["delta_recv_frame"] = await _delta(rig, recv)
    return res


# ─── §SENDEARLY (2026-09-26): send at the start of the run, judge at its end ───────────────────────────────────────
#
# His words: "fix the test so the transfer goes out at the beginning of the test run and success is measured later in
# the test run", then, on the three choices put to him, "1. yes 2. yes 3. yes". For the two cross-frame OPERATOR
# pairs (test_cross_frame_economic_flows), so:
#   1. send as soon as the CONVERTING frame (the sender's parent) knows the new receiver, and do NOT wait for the
#      delivering frame. A payment to an agent created a minute ago is the case that broke every night from 09-23 to
#      09-25; whether the delivering frame knows the receiver yet decides only WHICH way the money arrives (delivered
#      at once, or parked after the conversion and re-delivered by that frame's keeper), never WHETHER.
#   2. the keeper re-delivers a parked route once it is FX_REMOTE_RECOVERY_MIN_AGE_SEC old: 300 s on the sandbox pair
#      (his word; EU and ASIA keep 900 s), which the window below covers.
#   3. both directions.
# ONE send and no retry: the retry is what hid the stranded routes for three nights.

# How long after the send the verdict may still wait. The parked path takes the age gate (300 s) plus up to one 60 s
# keeper cycle; ten minutes covers it with room. On the nightly the rest of the suite (10 to 12.5 minutes) has usually
# used the window up by the time the verdict runs, so it reads once, at the end.
_SEND_EARLY_WINDOW_SEC = float(os.environ.get("FEDSUITE_SEND_EARLY_WINDOW_SEC", "600") or 600)
_ROUTE_ID_RE = re.compile(r"route_id=([0-9a-fA-F-]{36})")
# the GATEWAY's sentence, carried inside the origin's 409 (routers/teg_integration.py, the delegate after the FX core)
_PARKED_RE = re.compile(r"failed post-conversion; (\S+) (\w+) parked at (\S+) \(route_id=")


def classify_send(code: int, body: Any) -> Dict[str, Any]:
    """What ONE send did, read from the rail's own answer. Pure, so every shape is pinned by a unit test.

      delivered   2xx: the route settled when it was sent (`credited` = the rail's own figure)
      parked      409 after the conversion: the converted money waits at the delivering frame's @fx_router for
                  that frame's keeper (`parked_amount`, `parked_currency`, `parked_at`)
      refunded    409 before the conversion: the gateway gave the sender its money back; nothing is on its way
      stranded    409, neither refunded nor parked: the ingress moved and nobody reported where it went
      no_funds    refused before any funds moved (the sender's balance, or a posture on the gateway's TEG)
      no_booth    cross-currency and the sender has no FX booth
      unresolved  400: the sending registry has no route to the receiver at all
      refused     anything else
    """
    d = _detail(body)
    low = d.lower()
    out: Dict[str, Any] = {"status": code, "detail": d}
    m = _ROUTE_ID_RE.search(d)
    if m:
        out["route_id"] = m.group(1)
    if code in (200, 201, 202):
        out["kind"] = "delivered"
        if isinstance(body, dict):
            out["credited"] = body.get("credited_amount")
            if body.get("transfer_id"):
                out.setdefault("route_id", str(body.get("transfer_id")))
        return out
    if code == 402 or "fx route ingress failed (no funds moved)" in low:
        out["kind"] = "no_funds"
    elif "fx swap booth" in low or "FX_ENABLED" in d:
        out["kind"] = "no_booth"
    elif "fx route did not settle" in low:
        p = _PARKED_RE.search(d)
        if p:
            out.update(kind="parked", parked_amount=p.group(1), parked_currency=p.group(2), parked_at=p.group(3))
        elif "compensates pre-conversion" in low:
            out["kind"] = "refunded"
        else:
            out["kind"] = "stranded"
    elif code == 400 and "cannot resolve registry" in low:
        out["kind"] = "unresolved"
    else:
        out["kind"] = "refused"
    return out


async def _card_listed(rig, label: str, did: str) -> Optional[bool]:
    """ONE read of `did`'s card on `label`: is it listed there now? None = the read failed (never read as "no").
    By DID, not a capped page of the feed (see _await_card_at: a burst of rewrites fills the page)."""
    code, body = await _rest(rig, "GET", _card_path(did), label=label + "-admin")
    if code == 404:
        return False
    if code != 200 or not isinstance(body, dict) or body.get("agent_did") != did:
        return None
    return body.get("is_active") is not False and not bool(body.get("unlisted"))


async def _dead_letter(rig, label: str, route_id: Optional[str]):
    """The converting frame's dead-letter row for this route: a dict, None when it holds none, or a sentence saying the
    read failed (an unreadable queue is never read as an empty one)."""
    if not route_id:
        return "no route id to look for"
    code, body = await _rest(rig, "GET", "/api/v1/teg/fx/dead-letters?status=all&limit=200", label=label + "-admin")
    if code != 200 or not isinstance(body, dict):
        return f"unreadable (HTTP {code})"
    for r in body.get("rows") or []:
        if r.get("route_id") == route_id:
            return {"status": r.get("status"), "phase": r.get("phase"), "amount": r.get("amount"),
                    "currency": r.get("currency"), "retries": r.get("retries"), "resolved_at": r.get("resolved_at"),
                    "last_error": (r.get("last_error") or "")[:160] or None}
    return None


async def _clear_pair(rig, send: str, recv: str, state: Dict[str, Any]) -> None:
    """The pair a drive made is cleared once its verdict is in (V0639, agentvault2-aa): each agent's balance back to its
    frame's treasury, then the owner's delete (`_cleanup`). Neither rail cleared its pair before: on sbx-alpha alone 296
    opmoney agents held 5,876.73 (2026-10-24). A credit or a refund that lands after the clear (the operator's async
    saga refunds at its 30-minute timeout) stays on the deleted agent: the one residue left."""
    if state.get("sender"):
        await _cleanup(rig, [state["sender"]], label=send)
    if state.get("receiver"):
        await _cleanup(rig, [state["receiver"]], label=recv)


async def _send_early(rig, send: str, recv: str, state: Dict[str, Any]):
    """`_send_early_act`, then its pair cleared once its verdict is in: at once for a refusal or a verdict judged on
    the spot, after the deferred judgment otherwise (V0639)."""
    try:
        out = await _send_early_act(rig, send, recv, state)
    except Exception:
        await _clear_pair(rig, send, recv, state)
        raise
    if not isinstance(out, DeferredCheck):
        await _clear_pair(rig, send, recv, state)
        return out
    judge = out.check

    async def judged_then_cleared() -> AssertionResult:
        try:
            return await judge()
        finally:
            await _clear_pair(rig, send, recv, state)
    return DeferredCheck(check=judged_then_cleared)


async def _send_early_act(rig, send: str, recv: str, state: Dict[str, Any]):
    """ACT: create the pair, send ONCE as soon as the converting frame knows the receiver, and hand the runner the
    verdict to run after the rest of the suite (a DeferredCheck). A refusal that moved nothing is a precondition (there
    is no verdict to wait for); a refund or a stranding is judged at once (nothing is on its way)."""
    gw, gd = _gateway_label_for(send), _gateway_label_for(recv)
    if not gw or not gd or gw == gd:
        raise PreconditionUnmet(
            f"{send}->{recv} is not a pair of operators on two frames: nothing converts on the way, so there is no "
            f"send-early path to judge (the operator-to-frame rails are driven in test_operator_money_rails)")
    state.update(converting_frame=gw, delivering_frame=gd, gateway_label=gw)
    b = await _new_agent(rig, "opmoney-recv", label=recv)
    a = await _new_agent(rig, "opmoney-send", label=send)
    state["sender"], state["receiver"] = a["did"], b["did"]
    await _fund(rig, send, a["did"])
    await _nudge(rig, [send + "-admin", recv + "-admin"])

    # The ONE wait. Until the converting frame knows the receiver nothing can route: the gateway refunds the ingress
    # before converting, and no rail is measured. Nothing is waited for at the delivering frame, on purpose (above).
    if not await _await_card_at(rig, gw, b["did"], state):
        raise PreconditionUnmet(
            f"{b['did']} (on {recv}) never reached the frame that converts its payment ({gw}) within "
            f"{_CARD_WAIT_SEC:.0f} s. NO FUNDS MOVED: this is the wait, not the transfer. The card crosses two "
            f"federation hops, so a slower cycle here is a sync question, not a money one.")
    # informative: which way the money will have to arrive (None = the read failed)
    state["delivering_frame_listed_the_receiver_at_send"] = await _card_listed(rig, gd, b["did"])
    state["sender_before"] = await _bal(rig, send, a["jwt"])
    state["receiver_before"] = await _bal(rig, recv, b["jwt"])

    t_sent = time.time()
    code, body = await _rest(rig, "POST", "/api/v1/teg/cross-registry-transfer", label=send + "-admin", jwt=a["jwt"],
                             body={"receiver_did": b["did"], "amount": str(_AMOUNT),
                                   "message": "fedsuite send-early probe"})
    sent = classify_send(code, body)
    state["sent_at"] = datetime.fromtimestamp(t_sent, timezone.utc).isoformat()
    state["send"] = {k: v for k, v in sent.items() if k != "detail"}
    state["transfer_detail"] = sent["detail"][:300]
    kind = sent["kind"]
    if kind in ("no_funds", "no_booth", "unresolved", "refused"):
        raise PreconditionUnmet(
            f"{send}->{recv}: the send was refused before anything could be judged ({kind}, HTTP {code}): "
            f"{sent['detail'][:180]}")
    if kind in ("refunded", "stranded"):
        # Nothing is on its way to the receiver, so there is nothing to wait for: judged now.
        after = await _bal(rig, send, a["jwt"])
        state["sender_after"] = after
        before = state.get("sender_before")
        whole = (abs(after - before) < 1e-6) if (after is not None and before is not None) else None
        state["sender_made_whole"] = whole
        why = ("the converting frame refunded the sender before converting, although its index listed the receiver "
               "when the payment left" if kind == "refunded" else
               "the ingress moved and neither a refund nor a parking was reported")
        return AssertionResult(
            passed=False, description=f"{send}->{recv}: the payment sent at the start of the run arrives",
            budget_sec=0.0, elapsed_sec=0.0, polling_attempts=1, last_state=state,
            failure_detail=(f"{why} (HTTP {code}; the sender "
                            + ("was made whole" if whole else "is SHORT" if whole is False else "could not be read")
                            + f"): {sent['detail'][:200]}"))
    return DeferredCheck(check=lambda: _judge_delivery(rig, send, recv, b, state, sent, t_sent))


async def _judge_delivery(rig, send: str, recv: str, b: Dict[str, str], state: Dict[str, Any], sent: Dict[str, Any],
                          t_sent: float) -> AssertionResult:
    """VERDICT, after every other test: the receiver holds the money exactly ONCE, and nothing is left parked."""
    gw = state["converting_frame"]
    parked = sent["kind"] == "parked"
    route_id = sent.get("route_id")
    if parked:
        # the keeper re-delivers the parked amount; its delivery leg may carry the 0.5% cross-registry fee
        expected = (_num(sent.get("parked_amount")) or 0.0) * (1 - _FEE_RATE)
    else:
        expected = _num(sent.get("credited")) or 0.0
    description = (f"{send}->{recv}: the payment sent at the start of the run arrives exactly once "
                   f"(>= {expected:.6f}) and nothing is left parked")
    if expected <= 0:
        return AssertionResult(
            passed=False, description=description, budget_sec=0.0, elapsed_sec=0.0, polling_attempts=0,
            last_state=state, failure_detail=f"the send named no amount to look for ({sent['kind']}): "
                                             f"{state.get('transfer_detail')}")
    state["expected_credit_at_least"] = round(expected, 6)
    state["verdict_started_sec_after_send"] = round(time.time() - t_sent, 1)
    budget = max(60.0, t_sent + _SEND_EARLY_WINDOW_SEC - time.time())

    async def predicate():
        got = await _bal(rig, recv, b["jwt"])
        state["receiver_after"] = got
        if got is None:
            return False                       # unreadable: keep polling, never pass
        gain = got - (state.get("receiver_before") or 0.0)
        state["receiver_gain"] = round(gain, 6)
        if gain < expected - 1e-6:
            return False
        if parked:
            row = await _dead_letter(rig, gw, route_id)
            state["dead_letter"] = row
            # Wait for the row to CLOSE: a gain seen while it is still pending may be a late direct delivery the keeper
            # has yet to recognise, and a second delivery could only show after the close. An unreadable queue is
            # recorded in the state and the balance decides alone.
            if isinstance(row, dict) and row.get("status") not in ("delivered", "swept"):
                return False
        state["credited_sec_after_send"] = round(time.time() - t_sent, 1)
        return True

    res = await rig.assert_within(budget_sec=budget, predicate=predicate, poll_interval_sec=10.0,
                                  description=description, capture_state=lambda: state)
    failure = None
    if res.passed:
        got = await _bal(rig, recv, b["jwt"])
        if got is not None:
            gain = got - (state.get("receiver_before") or 0.0)
            state["receiver_gain_final"] = round(gain, 6)
            if gain >= 2 * expected - 1e-6:
                failure = (f"the receiver gained {gain:.6f} for ONE payment (at least {expected:.6f} was due once): "
                           f"the money arrived twice")
        if failure is None and not parked:
            row = await _dead_letter(rig, gw, route_id)
            state["dead_letter"] = row
            if isinstance(row, dict):
                failure = (f"the route settled when it was sent, yet {gw} holds a dead letter for it "
                           f"({row.get('phase')}, {row.get('status')})")
        state["path"] = ((f"parked after the conversion, re-delivered by {state['delivering_frame']}'s keeper "
                          f"{state.get('credited_sec_after_send')} s after the send") if parked else "delivered when sent")
    else:
        waited = round(time.time() - t_sent)
        if parked:
            state["path"] = "parked after the conversion, not re-delivered"
            failure = (f"{sent.get('parked_amount')} {sent.get('parked_currency')} parked at "
                       f"{state['delivering_frame']}'s @fx_router after the conversion (route {route_id}) was not "
                       f"re-delivered within {waited} s of the payment; the keeper there re-delivers a parked route "
                       f"once it is FX_REMOTE_RECOVERY_MIN_AGE_SEC old (300 s on the sandbox pair). "
                       f"Dead letter now: {state.get('dead_letter')}")
        else:
            state["path"] = "reported delivered, not credited"
            failure = (f"the rail answered settled ({sent.get('credited')} credited) and the receiver's balance did "
                       f"not show it within {waited} s of the payment")
    # Δ is recorded on BOTH frames and is NOT the verdict: every leg here is within a frame, so it reads 0.0 either way.
    state["delta_send_frame"] = await _delta(rig, send)
    state["delta_recv_frame"] = await _delta(rig, recv)
    if failure:
        return dataclasses.replace(res, passed=False, failure_detail=failure, last_state=state)
    return dataclasses.replace(res, last_state=state)


@federation_test(
    name="frame_to_operator_transfer_credits_receiver",
    category="operator_money_rails",
    budget_sec=200.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin", "sandboxalpha", "sandboxalpha-admin"],
    tags=["money", "cross_registry", "cloud-op", "driven"],
)
async def test_frame_to_operator(rig: FederationTestRig) -> AssertionResult:
    """A frame-homed agent pays an operator-homed agent, and it ARRIVES."""
    state: Dict[str, Any] = {"direction": "sandbox-A→sandboxalpha"}
    try:
        agents = await _drive(rig, "sandbox-A", "sandboxalpha", state)
        return await _assert_credited(rig, "sandbox-A", "sandboxalpha", agents, state, 120.0)
    finally:
        await _clear_pair(rig, "sandbox-A", "sandboxalpha", state)


@federation_test(
    name="operator_to_frame_transfer_credits_receiver",
    category="operator_money_rails",
    budget_sec=260.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin", "sandboxalpha", "sandboxalpha-admin"],
    tags=["money", "cross_registry", "cloud-op", "driven", "async-saga"],
)
async def test_operator_to_frame(rig: FederationTestRig) -> AssertionResult:
    """An operator-homed agent pays a frame-homed agent, and it ARRIVES.

    ⚠ MEASURED RED 2026-09-04 and filed, not a flake. The POST answers 200 with
    `status: "locked"`, the sender is debited, and the receiver is never
    credited: the operator falls back to the ASYNC saga, whose source and target
    "frames" are the SAME trust domain (an operator lives inside its parent's),
    so the receiving side never learns of it — the parent frame holds no
    `cross_frame_transfers` and no `cross_teg_transfers` row for the id at all.
    Δ stays 0.0 on both frames throughout, which is exactly why this test asserts
    the receiver's balance and not the invariant.

    ⚠ THE MONEY IS NOT LOST — the compensating control fires. At the saga's
    30-minute `timeout_at` the row flips to `refunded` and the sender is made
    whole (measured: 48.0 → 50.0). The defect is therefore "reports success and
    cannot deliver", not "destroys value": the caller is told 200 for a payment
    that can never arrive, and their funds are unusable for half an hour with no
    signal anywhere. Still worth a red row.

    Left RED on purpose. A skip here would be a claim that the environment
    cannot supply something, and that is not what is happening: the rail accepts
    a transfer it cannot complete and reports success.
    """
    state: Dict[str, Any] = {"direction": "sandboxalpha→sandbox-A"}
    try:
        agents = await _drive(rig, "sandboxalpha", "sandbox-A", state)
        return await _assert_credited(rig, "sandboxalpha", "sandbox-A", agents, state, 180.0)
    finally:
        await _clear_pair(rig, "sandboxalpha", "sandbox-A", state)
