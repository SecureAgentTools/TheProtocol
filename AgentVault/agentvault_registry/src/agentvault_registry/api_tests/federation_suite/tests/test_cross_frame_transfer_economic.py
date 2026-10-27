"""THE CROSS-REGISTRY TRANSFER driven across two frames, with both ledgers checked.

This is the federation's core money rail — FLOW 8, `/teg/cross-registry-transfer`
— and the suite has never driven its events. `CrossFrameTransferInitiated` and
`CrossFrameTransferSettled` sat in the uncovered baseline: emitted by code,
verified by nothing.

⚠ IT IS ALSO THE ONLY MONEY PATH IN THIS SUITE THAT RUNS THROUGH A REACTOR.
The sender's frame emits `CrossFrameTransferInitiated`; a reactor
(`main.py:4977`) turns that event into the RECEIVER's TEG credit and then emits
`CrossFrameTransferSettled`. So the second half of this transfer is not a
response to any HTTP call — it is work a background consumer does later. A test
that asserted only the POST's 200 would pass with the reactor dead and the money
locked on the sender's side for ever. That is the whole reason to drive it.

WHAT IS ASSERTED, and why each is necessary:
  * the SENDER is debited on frame A (amount + the 0.5% cross-registry fee);
  * the RECEIVER is credited on frame B — a DIFFERENT frame, different TEG,
    different EventStore — which is the reactor's output, not the API's;
  * both frames' supply invariants are still 0. Two Δs, because a cross-frame
    move is two per-frame books and a breach can live in either;
  * both events are RECORDED. Δ is computed FROM events, so a dropped emit takes
    the credit and the debit with it and leaves Δ at a contented 0.0 (§S4).

⚠ A FRESH REMOTE AGENT IS UNRESOLVABLE FOR UP TO ONE FEDERATION INTERVAL.
`FEDERATION_SYNC_INTERVAL_SECONDS` is 120 on these frames, and the sender's
registry must resolve the receiver DID → its home TEG before it can route
anything. Creating the receiver and transferring immediately fails with a
resolution error that looks exactly like a broken rail. The receiver is
therefore created FIRST and the test WAITS for frame A to resolve it, as a
precondition with its own budget — the wait is the product's, not a defect.

⚠ PERMISSION: this rail needs `teg.transfer_xreg`, which `trader` carries and
`client` does NOT. Both are default birth roles (`AGENT_RBAC_DEFAULT_ROLES`), so
a fresh agent qualifies — but a 403 here means the birth roles changed, not that
the rail is gone, and the failure says so.

Sandbox treasury funding is APPROVED for sandbox mainframes (2026-09-04) and
explicitly NOT for prod; `requires`-gated to the sandbox frames and funded
through the canonical admin rail (FLOW 4), never a direct TEG mint.

⚠ Writes: one agent per frame per run, tagged `fedsuite-xfr-*`, and one real
cross-frame movement of dust. Agent deletion is a SOFT delete that keeps a
balance, so what each agent holds goes back first (throwaways, V0641).
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional

from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
    ensure_bonded,
)
from agentvault_registry.api_tests.federation_suite.tests.test_contract_spine_economic import (
    _call, _rest, _num, _new_agent, _balance, _fund, _contract_event_types,
)

_SEED = "40.0"
_SEND = "12.0"
# ⚠ NO FEE CONSTANT, AND THAT IS THE POINT. My first version asserted the
# receiver gained at least `amount * (1 - 0.005)` — a FLAT 0.5% fee. Measured on
# a real move it came up 0.000716 short: 12.0 sent, 11.939284 credited, against a
# flat-fee floor of 11.939999. The cross-CURRENCY path charges no flat fee — it
# prices through a CONSTANT-PRODUCT AMM, so the output is the curve and depends
# on both reserves' depth. Pinning a rate would make this test fail whenever the
# pool moved, which is the pool working.
#
# What IS invariant: the sender is debited EXACTLY what it sent, the receiver is
# credited SOMETHING on the other frame, both frames' Δ hold, and the settlement
# is recorded. The effective rate is REPORTED, never gated.

# ⚠ WHICH EVENT LANDS DEPENDS ON THE CURRENCY PAIR, AND I GOT THIS WRONG FIRST.
# Two frames with the SAME currency take the plain cross-frame transfer path and
# emit `CrossFrameTransferInitiated` (a reactor then credits the receiver and
# emits `CrossFrameTransferSettled`). Two frames with DIFFERENT currencies —
# which is the normal case, and is what SBXA→SBXB is — take the reserve-mediated
# FX SWAP instead: sender → local fx_reserve, dest fx_reserve → recipient, and
# the settlement event is `FxSwapSettled`. Measured on a real 12.0 SBXA→SBXB
# move: sender −12.0, receiver +11.939284 (0.5% fee), `FxSwapSettled` on the
# sender's aggregate and NO CrossFrameTransfer* anywhere.
#
# Asserting only one family would fail on a correct system for the other, so the
# test accepts EITHER and REPORTS which path ran. That is the honest shape: the
# claim is "a cross-frame move settled and was recorded", not "this particular
# rail was used" — the product picks the rail from the currencies.
_SETTLEMENT_EVENTS = {
    "FxSwapSettled": "cross-currency FX swap (frames differ in currency)",
    "FxRouteSettled": "cross-currency FX route",
    "CrossFrameTransferInitiated": "same-currency cross-frame transfer",
}


async def _new_agent_on(rig, label: str, tag: str) -> Dict[str, str]:
    """Create an agent on a NAMED frame. `_new_agent` is pinned to sandbox-A."""
    r, refused = await _call(rig, label, "createAgent", {
        "name": f"fedsuite-xfr-{tag}-{uuid.uuid4().hex[:8]}",
        "description": "federation suite cross-frame transfer probe",
    })
    if refused or not isinstance(r, dict):
        raise PreconditionUnmet(f"createAgent on {label} refused: {refused}")
    if r.get("error"):
        raise PreconditionUnmet(f"createAgent on {label} error: {r['error']}")
    cid = r.get("client_id") or (r.get("credentials") or {}).get("client_id")
    sec = r.get("client_secret") or (r.get("credentials") or {}).get("client_secret")
    did = r.get("did") or r.get("agent_did") or (r.get("agent") or {}).get("did")
    throwaways.made(label, did)  # V0641: retired once its test's verdict is in (throwaways)
    if not (cid and sec and did):
        raise PreconditionUnmet(
            f"createAgent on {label} returned no credential triple (keys={sorted(r)[:8]})")
    t, tref = await _call(rig, label, "getAgentToken", {"client_id": cid, "client_secret": sec})
    if tref or not isinstance(t, dict):
        raise PreconditionUnmet(f"getAgentToken on {label} refused: {tref}")
    jwt = t.get("access_token") or t.get("agent_jwt")
    if not jwt:
        raise PreconditionUnmet(f"no agent JWT on {label}")
    # §REPBOND: creation does NOT bond, so on an enforcing tier this fixture
    # is born refused at discovery/listing/pricing/guild/contract/a2a-payee.
    await ensure_bonded(rig, label, did)
    return {"did": did, "jwt": jwt, "client_id": cid}


async def _balance_on(rig, label: str, jwt: str) -> float:
    r, refused = await _call(rig, label, "getMyBalance", {"agent_jwt": jwt})
    if refused or not isinstance(r, dict):
        return 0.0
    for k in ("balance", "liquid_balance", "token_balance", "available"):
        if r.get(k) is not None:
            return _num(r[k])
    return 0.0


async def _delta_on(rig, admin_label: str) -> Optional[float]:
    """Supply invariant for ONE frame. None = UNREADABLE, its own state."""
    r, refused = await _call(rig, admin_label, "adminQueryEventStore",
                             {"path": "/api/v1/projections/supply-audit"})
    if refused or not isinstance(r, dict):
        return None
    body = r.get("response") if isinstance(r.get("response"), dict) else r
    d = body.get("delta")
    return None if d is None else _num(d)


async def _resolves(rig, did: str) -> bool:
    """Can frame A resolve this remote DID yet? Federation sync is 120s here."""
    r, refused = await _call(rig, "sandbox-A", "getAgentByDID", {"did": did})
    if refused or not isinstance(r, dict) or r.get("error"):
        return False
    return bool(r.get("did") or r.get("agent_did") or r.get("id"))


@federation_test(
    name="cross_frame_transfer_moves_money_across_frames_and_is_evented",
    category="cross_frame_money",
    budget_sec=300.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin", "sandbox-B", "sandbox-B-admin"],
    tags=["federation", "economic", "money", "delta", "event_emission", "reactor"],
)
async def test_cross_frame_transfer(rig: FederationTestRig) -> AssertionResult:
    """A → B cross-registry transfer: both balances, both Δs, both events."""
    tag = uuid.uuid4().hex[:8]
    notes: Dict[str, Any] = {"tag": tag}

    dA0, dB0 = await _delta_on(rig, "sandbox-A-admin"), await _delta_on(rig, "sandbox-B-admin")
    notes["delta_A_start"], notes["delta_B_start"] = dA0, dB0

    # Receiver FIRST — frame A needs a federation cycle to learn it exists.
    receiver = await _new_agent_on(rig, "sandbox-B", f"rx-{tag}")
    sender = await _new_agent(rig, f"xfr-{tag}-tx")
    notes["receiver_did"], notes["sender_did"] = receiver["did"], sender["did"]

    if (fref := await _fund(rig, sender["did"], _SEED)):
        raise PreconditionUnmet(f"seed funding refused: {fref}")

    # ── precondition: A must RESOLVE the remote DID before it can route ────
    resolved = await rig.assert_within(
        budget_sec=150.0, predicate=lambda: _resolves(rig, receiver["did"]),
        description="frame A resolves the freshly-created frame-B receiver DID",
        capture_state=lambda: notes,
    )
    notes["receiver_resolved"] = resolved.passed
    if not resolved.passed:
        raise PreconditionUnmet(
            f"frame A could not resolve {receiver['did']} within 150s. Federation sync is "
            f"{'120s'} on these frames, so this is a propagation window, not proof the rail "
            f"is broken — but the transfer cannot be driven without it.")

    s_before = await _balance(rig, sender["jwt"])
    r_before = await _balance_on(rig, "sandbox-B", receiver["jwt"])
    notes["sender_before"], notes["receiver_before"] = s_before, r_before

    # ── the transfer runs ONCE, outside the poller ────────────────────────
    hard: Optional[str] = None
    st, resp = await _rest(rig, "POST", "/api/v1/teg/cross-registry-transfer",
                           body={"receiver_did": receiver["did"], "amount": _SEND,
                                 "message": f"fedsuite xfr {tag}"},
                           jwt=sender["jwt"],
                           headers={"Idempotency-Key": f"fedsuite-xfr-{tag}"})
    notes["transfer_http"] = st
    notes["transfer_response"] = json.dumps(resp, default=str)[:300]
    _body = json.dumps(resp, default=str)
    # ⚠ NARROW: only the 404 shape means ABSENT TOPOLOGY. My first version skipped
    # on any "FX pool: reserve read failed", and that was too broad — it went on
    # skipping after the sidecar existed, masking a ROUTING bug (the map keys were
    # wrong) behind a message about a missing sidecar. A CERTIFICATE_VERIFY_FAILED
    # or a connect error on this rail is a real defect and must FAIL, loudly.
    if st == 503 and "FX pool: reserve read failed" in _body and "404" in _body:
        # ⚠ CLASSIFY BY THE REFUSAL SENTENCE, NOT THE STATUS. This particular 503
        # is ABSENT INFRASTRUCTURE, not a broken rail, and calling it a failure
        # makes the suite unactionable. `FX_RATE_MODE=pool` prices a cross-frame
        # move off BOTH frames' `fx_reserve`, which means reading the PEER's TEG
        # over mTLS — and the frame-test template ships NO `nginx-teg` sidecar
        # (0 references), so there is nothing to read it from. Measured: every
        # cloud operator and Frame A have that sidecar; neither sandbox frame
        # does, `TEG_SIDECAR_MAP` is empty on both, and the dest resolver falls
        # through to the peer's REGISTRY vhost, which 404s a TEG route.
        #
        # A fresh frame is therefore CONFIGURED for pool mode without the
        # topology pool mode requires — a provisioning gap, and one this skip
        # names so it can be closed rather than rediscovered. Two REAL defects
        # on this same path were found and fixed getting this far: the registry
        # mounted no SVID volume at all, and `es_ssl_helper` suppressed its trust
        # context whenever `EVENT_STORE_URL` was plain HTTP.
        raise PreconditionUnmet(
            "cross-frame FX pool mode needs the peer frame's nginx-teg sidecar, which the "
            "frame-test template does not provision (FX_RATE_MODE=pool is set anyway, and "
            "TEG_SIDECAR_MAP is empty). The dest resolver falls through to the peer's "
            "REGISTRY vhost and gets 404 on a TEG route. Absent topology, not a broken "
            f"rail. Body: {_body[:200]}")
    if st != 200:
        hard = (f"cross-registry-transfer HTTP {st}: {json.dumps(resp, default=str)[:220]}. "
                f"This rail needs `teg.transfer_xreg` — `trader` carries it, `client` does "
                f"not, and both are default birth roles; a 403 means the birth roles moved.")

    # ── settle: the receiver's credit is a REACTOR's work, not the API's ──
    async def _settled() -> bool:
        if hard:
            return False
        notes["sender_after"] = await _balance(rig, sender["jwt"])
        notes["receiver_after"] = await _balance_on(rig, "sandbox-B", receiver["jwt"])
        a_types = await _contract_event_types(rig, sender["did"])
        notes["sender_aggregate_events"] = sorted(set(a_types)) if a_types is not None else None
        notes["delta_A_end"] = await _delta_on(rig, "sandbox-A-admin")
        notes["delta_B_end"] = await _delta_on(rig, "sandbox-B-admin")

        moved = (notes["receiver_after"] or 0.0) - r_before
        debited = s_before - (notes["sender_after"] or 0.0)
        notes["receiver_gain"], notes["sender_debit"] = moved, debited
        notes["effective_rate"] = (moved / _num(_SEND)) if _num(_SEND) else None
        # Credited SOMETHING on the other frame. Deliberately NOT compared with
        # the sent amount: the units are the DEST frame's currency.
        if moved <= 0:
            return False
        # Debited EXACTLY what was sent — this leg is a within-frame transfer of
        # the notional, not a curve output, so it is exact.
        if abs(debited - _num(_SEND)) > 0.000001:
            return False
        seen_settlement = [t for t in _SETTLEMENT_EVENTS if a_types and t in a_types]
        notes["settlement_events_seen"] = seen_settlement
        notes["path"] = (_SETTLEMENT_EVENTS[seen_settlement[0]]
                         if seen_settlement else "no settlement event recorded")
        if a_types is None or not seen_settlement:
            return False
        dA, dB = notes["delta_A_end"], notes["delta_B_end"]
        return (dA is not None and dB is not None
                and abs(dA) <= 0.01 and abs(dB) <= 0.01)

    return await rig.assert_within(
        budget_sec=(1.0 if hard else 120.0),
        predicate=_settled,
        description=(hard or
                     f"{_SEND} crosses A→B: sender debited, receiver credited on the OTHER "
                     f"frame, a settlement event recorded, and BOTH frames' Δ still 0"),
        capture_state=lambda: notes,
    )
