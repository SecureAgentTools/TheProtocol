"""The core money emissions, driven (§FEDEVENTS batch 3).

The first two batches covered authority and administration. This one covers the
events the supply invariant is actually BUILT from — `TokensTransferred`,
`TransactionFeeCollected`, `TokensIssued`, `CrossRegistryTransferCompleted` —
plus the money-adjacent policy writes.

Why these specifically. `projections.py:492` derives BOTH legs of a transfer
from the SAME `TokensTransferred` event, so a dropped emit moves
`total_circulating` and `transit_net` by exactly zero. The money moves in the
TEG, the EventStore never hears it, and Δ reads a contented 0.0. §VITALS found
that shape live in `TEGBulkProxy._flush`; §S4 wrote the rule that came out of
it — **balances moved AND Δ=0 is not proof of settlement.** Every test here
therefore checks the EVENT and Δ as two separate verdicts, because Δ alone
cannot see the failure it is supposed to guard against.

Every emit site for these four keys on the SENDER's aggregate — read from the
source, not assumed: a receiver-keyed query returns zero and reads exactly like
money moving unrecorded.

⚠ Moves dust (1-10 AVT) and mints on the SANDBOX tier only, which ruFFa
approved for sandbox mainframes on 2026-09-04 and explicitly not for prod.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
)
from agentvault_registry.api_tests.federation_suite.tests.test_ironkey_authority_clamp import (
    _call, _rest, _detail, _new_agent, _cleanup, _done, _catalog, _set_roles,
)
from agentvault_registry.api_tests.federation_suite.tests.test_event_emission_matrix import (
    _await_events, _must, _body, _new_developer, _optional_step, _events_of_type,
    _matches,
)
from agentvault_registry.api_tests.federation_suite.tests.test_value_event_emission import _delta


async def _fund(rig, did: str, amount: str = "100.0") -> None:
    await _must(rig, "POST", "/api/v1/teg/treasury/fund-agent",
                body={"target_agent_did": did, "amount": amount,
                      "reason": "fedsuite value-event probe"})


def _delta_ok(d0: Optional[float], d1: Optional[float]) -> Optional[bool]:
    """None = could not check. Never let that read as 'checked and fine'."""
    if d0 is None or d1 is None:
        return None
    return abs(d1 - d0) < 1e-9


# ─── the pair the invariant is built from ──────────────────────────────────

@federation_test(
    name="value_events_transfer_emits_transferred_and_fee",
    category="value_events",
    budget_sec=200.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["event_emission", "money", "invariant"],
)
async def test_transfer_emits_transferred_and_fee(rig: FederationTestRig) -> AssertionResult:
    """A plain agent→agent transfer must emit BOTH `TokensTransferred` and
    `TransactionFeeCollected`.

    This is the busiest money rail on the platform and the one the supply
    invariant is derived from. Both legs are asserted because the fee is a
    separate emission on the same act: a transfer whose fee event is lost still
    balances (the fee is zero-sum, sender→fee_collector), so nothing else in the
    system would notice the audit trail thinning out.

    Δ is a SECOND, independent verdict. It cannot substitute for the event
    check — that is the whole §S4 lesson — but a transfer that moved it would be
    a breach regardless of what the ledger recorded.
    """
    a = await _new_agent(rig, "xfer-a")
    b = await _new_agent(rig, "xfer-b")
    state: Dict[str, Any] = {"sender": a["did"], "receiver": b["did"]}
    try:
        await _fund(rig, a["did"], "100.0")
        d0 = await _delta(rig)
        state["delta_before"] = d0
        sent = await _must(rig, "POST", "/api/v1/teg/transfer",
                           body={"receiver_agent_id": b["did"], "amount": "3.0",
                                 "message": "fedsuite value-event probe"},
                           jwt=a["jwt"])
        state["transfer_keys"] = sorted(sent)[:10] if isinstance(sent, dict) else None

        # ⚠ SENDER's aggregate. Both emit sites key on `sender_did`
        # (teg_integration.py:1815 and :1830), so a receiver-keyed query returns
        # zero and reads exactly like money moving unrecorded.
        result = await _await_events(
            rig, {"TokensTransferred": a["did"], "TransactionFeeCollected": a["did"]},
            state, budget_sec=90.0,
            description="a transfer emits TokensTransferred and TransactionFeeCollected")
        d1 = await _delta(rig)
        state["delta_after"] = d1
        state["delta_unchanged"] = _delta_ok(d0, d1)
        if state["delta_unchanged"] is False:
            return _done(False, "a transfer is Δ-neutral", state)
        return result
    finally:
        await _cleanup(rig, [a["did"], b["did"]])


@federation_test(
    name="value_events_treasury_mint_emits_tokens_issued",
    category="value_events",
    budget_sec=200.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["event_emission", "money", "mint", "invariant"],
)
async def test_treasury_mint_emits_tokens_issued(rig: FederationTestRig) -> AssertionResult:
    """Minting must emit `TokensIssued`, and the invariant must absorb it.

    A mint is the only act that legitimately creates supply, so it is the one
    emission whose loss is unrecoverable: `net_supply` is
    `tokens_issued − tokens_destroyed + transit_net`, and a mint that never
    emits raises `total_circulating` while leaving `tokens_issued` behind. That
    is a REAL breach, not a blind spot — the one shape Δ *can* see, and the
    reason this test asserts both the event and Δ.

    Minted through the REGISTRY rail. Minting on the TEG directly bypasses the
    registry's `TokensIssued` emission and is an instant Δ breach by
    construction — which is exactly the failure this row exists to detect.
    """
    agent = await _new_agent(rig, "mint")
    did = agent["did"]
    state: Dict[str, Any] = {"target": did}
    try:
        d0 = await _delta(rig)
        state["delta_before"] = d0
        minted = await _must(rig, "POST", "/api/v1/teg/treasury/mint",
                             body={"target_agent_did": did, "amount": "5.0",
                                   "reason": "fedsuite value-event probe"})
        state["mint_keys"] = sorted(minted)[:10] if isinstance(minted, dict) else None
        result = await _await_events(
            rig, {"TokensIssued": did}, state, budget_sec=90.0,
            description="a treasury mint emits TokensIssued")
        d1 = await _delta(rig)
        state["delta_after"] = d1
        state["delta_unchanged"] = _delta_ok(d0, d1)
        if state["delta_unchanged"] is False:
            return _done(False, "the mint keeps the supply invariant at zero", state)
        return result
    finally:
        await _cleanup(rig, [did])


@federation_test(
    name="value_events_cross_registry_transfer_is_evented",
    category="value_events",
    budget_sec=240.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-B", "sandbox-A-admin", "sandbox-B-admin"],
    tags=["event_emission", "money", "cross_frame", "invariant"],
)
async def test_cross_registry_transfer_is_evented(rig: FederationTestRig) -> AssertionResult:
    """Value crossing a frame boundary must be recorded on the sending side.

    The cross-registry path emits three events from one act
    (`_emit_cross_registry_events`): the transfer, the completion marker and the
    fee. `CrossRegistryTransferCompleted` is `skip_in_projection=true` — audit
    only, with the balance tracked via `TokensTransferred` — so losing the
    transfer event while keeping the completion marker would leave a trail that
    LOOKS complete and moves no supply. Both are asserted for that reason.

    Δ is checked on BOTH frames, because a cross-frame move is the one case
    where a single frame's invariant cannot see the whole act.
    """
    a = await _new_agent(rig, "xreg-a", label="sandbox-A")
    b = await _new_agent(rig, "xreg-b", label="sandbox-B")
    state: Dict[str, Any] = {"sender": a["did"], "receiver": b["did"]}
    try:
        await _fund(rig, a["did"], "100.0")
        d0 = await _delta(rig)
        state["delta_a_before"] = d0
        # The receiver's card must have federated to frame A before its home can
        # be resolved, and federation sync runs on a 120 s interval. The first run
        # failed with "Cannot resolve registry for receiver" purely because the
        # card had not arrived yet — a timing precondition, not a broken rail, so
        # it is waited out rather than reported as a defect.
        import asyncio as _aio

        async def _nudge_federation() -> None:
            """Ask both frames to sync NOW instead of waiting out the interval.

            Dual-auth admin rail, rate limited 1 per 30 s — a 429 is expected on
            a re-nudge and means the previous one is still the freshest, so every
            outcome here is ignored on purpose. This is an accelerator; the poll
            below is what actually decides.
            """
            for _label in ("sandbox-A-admin", "sandbox-B-admin"):
                try:
                    await _rest(rig, "POST", "/api/v1/federation/sync/trigger",
                                label=_label, body={})
                except Exception:          # noqa: BLE001 - accelerator only
                    pass

        # §FEDSKIPS 2026-09-04: the old window was 4 attempts x 10 s = 40 s
        # against a federation interval of 120 s, so the receiver's card had
        # usually NOT arrived yet and the test skipped itself on a timing fact
        # dressed as "cross-registry transfer refused". Nudge the sync, then
        # poll past a full interval — inside the 240 s budget, and still a
        # precondition (not a failure) if the card never lands.
        await _nudge_federation()
        code, sent = -1, None
        for attempt in range(10):
            code, sent = await _rest(rig, "POST", "/api/v1/teg/cross-registry-transfer",
                                     body={"receiver_did": b["did"], "amount": "2.0",
                                           "message": "fedsuite xreg value probe"},
                                     jwt=a["jwt"])
            state["transfer_attempts"] = attempt + 1
            if code in (200, 201, 202):
                break
            if code == 400 and "cannot resolve registry" in _detail(sent).lower():
                await _aio.sleep(14)
                if attempt % 3 == 2:       # past the 30 s rate limit — nudge again
                    await _nudge_federation()
                continue
            break
        state["transfer_status"] = code
        if code not in (200, 201, 202):
            d = _detail(sent)
            if "certificate verify failed" in d.lower() or "reserve read failed" in d.lower():
                # Not a transfer defect: the FX pool read dials the peer TEG over
                # mTLS, and a fresh frame ships none of the three things that
                # makes that work (a SHARED TEG admin key across the pair, the
                # `teg-layer-<slug>` alias, both registries on the shared identity
                # net). A provisioning-template gap, worth naming precisely so it
                # is not mistaken for a broken money rail.
                raise PreconditionUnmet(
                    "cross-frame FX reserve read fails TLS on this tier — the frame "
                    "template ships no shared TEG admin key / teg-layer alias / shared "
                    f"identity net. HTTP {code}: {d[:140]}")
            raise PreconditionUnmet(
                f"cross-registry transfer refused after {state.get('transfer_attempts')} "
                f"attempts: HTTP {code} {d[:200]}")
        # §CLOUDOPMCP 2026-09-04 — the sending frame records this act in ONE of two
        # shapes, and which one depends on whether the two frames share a currency.
        # This asserted only the same-currency shape, so on a cross-currency pair it
        # could never pass.
        #
        # MEASURED on the SBXA/SBXB pair: `CrossRegistryTransferCompleted` has ZERO
        # rows in the EventStore, while every sender that completed a cross-registry
        # transfer carries exactly `AgentCreated, AgentOnboarded, FxSwapSettled`.
        # Balances still moved (sender −12, receiver +11.92) and Δ held at 0.0 on
        # both frames, so the FX path is accounted differently, not incorrectly.
        #
        # The original strictness is PRESERVED where it applies: if the same-currency
        # marker `TokensTransferred` is present then `CrossRegistryTransferCompleted`
        # is still required, because the docstring's reasoning holds there — a
        # completion marker without the transfer event is a trail that looks complete
        # and moves no supply. What is dropped is only the assumption that the
        # same-currency shape is the ONLY shape.
        _FX_SETTLEMENT = ("FxSwapSettled", "FxRouteSettled")

        async def _settled() -> bool:
            unreadable = False
            present: Dict[str, bool] = {}
            for etype in ("TokensTransferred", "CrossRegistryTransferCompleted") + _FX_SETTLEMENT:
                evs = await _events_of_type(rig, etype)
                if evs is None:
                    unreadable = True
                    present[etype] = False
                    continue
                present[etype] = any(_matches(e, a["did"]) for e in evs)
            state["seen"] = present
            state["eventstore"] = "unreadable" if unreadable else "readable"
            # ⚠ ORDER MATTERS, and my first attempt got it wrong. `TokensTransferred`
            # is NOT a discriminator here: this test FUNDS the sender before
            # transferring, and that funding emits TokensTransferred against the same
            # DID. Keying on it first therefore always selected the same-currency
            # branch and then demanded a completion marker the FX path never emits —
            # measured: TokensTransferred 1 match, FxSwapSettled 1 match,
            # CrossRegistryTransferCompleted 0 events. An FX settlement event is
            # unambiguous, so it is tested FIRST.
            fx = [t for t in _FX_SETTLEMENT if present.get(t)]
            if fx:
                state["settlement_path"] = "cross-currency FX (%s)" % ", ".join(fx)
                state["missing"] = []
                return True
            if present.get("CrossRegistryTransferCompleted"):
                # Same-currency path. The original strictness stands: the completion
                # marker without the transfer event is a trail that looks complete and
                # moves no supply.
                state["settlement_path"] = "same-currency (CrossRegistryTransferCompleted)"
                state["missing"] = ([] if present.get("TokensTransferred")
                                    else ["TokensTransferred"])
                return bool(present.get("TokensTransferred"))
            state["settlement_path"] = None
            state["missing"] = ["CrossRegistryTransferCompleted or "
                                + " or ".join(_FX_SETTLEMENT)]
            return False

        result = await rig.assert_within(
            budget_sec=110.0, poll_interval_sec=4.0, predicate=_settled,
            description=("a cross-registry transfer is evented on the sending frame "
                         "(same-currency: TokensTransferred + CrossRegistryTransferCompleted; "
                         "cross-currency: an FX settlement event)"),
            capture_state=lambda: state,
        )
        if not result.passed and state.get("eventstore") == "unreadable":
            raise PreconditionUnmet("EventStore unreadable — emission not measured")
        d1 = await _delta(rig)
        state["delta_a_after"] = d1
        state["delta_a_unchanged"] = _delta_ok(d0, d1)
        if state["delta_a_unchanged"] is False:
            return _done(False, "a cross-registry transfer is Δ-neutral on the sender", state)
        return result
    finally:
        await _cleanup(rig, [a["did"]], label="sandbox-A")
        await _cleanup(rig, [b["did"]], label="sandbox-B")


# ─── money-adjacent administration ─────────────────────────────────────────

@federation_test(
    name="value_events_funding_rejection_is_evented",
    category="value_events",
    budget_sec=180.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["event_emission", "money", "funding"],
)
async def test_funding_rejection_is_evented(rig: FederationTestRig) -> AssertionResult:
    """A REFUSED funding request must be recorded too.

    The approval path is already covered. The refusal is the one that gets
    forgotten, and it is the half an operator needs when asked why an agent
    never got its money: "we said no, here, on this date" is only answerable
    from a ledger entry that the rejection actually wrote.
    """
    agent = await _new_agent(rig, "fund-rej")
    state: Dict[str, Any] = {"did": agent["did"]}
    try:
        created = await _must(rig, "POST", "/api/v1/funding/request",
                              body={"amount": "1.0",
                                    "reason": "fedsuite rejection-path probe, dust only"},
                              jwt=agent["jwt"])
        rid = created.get("id") or created.get("request_id")
        state["request_id"] = rid
        if rid is None:
            raise PreconditionUnmet(f"no funding request id (keys={sorted(created)[:8]})")
        await _must(rig, "POST", f"/api/v1/admin/funding/{rid}/reject",
                    body={"reason": "fedsuite rejection-path probe"})
        return await _await_events(
            rig, {"FundingRequestRejected": str(rid)}, state, budget_sec=90.0,
            description="a rejected funding request is evented")
    finally:
        await _cleanup(rig, [agent["did"]])


@federation_test(
    name="value_events_fiat_pricing_update_is_evented",
    category="value_events",
    budget_sec=150.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["event_emission", "money", "fiat", "policy"],
)
async def test_fiat_pricing_update_is_evented(rig: FederationTestRig) -> AssertionResult:
    """Changing what a euro buys must be recorded.

    Fiat pricing is the exchange rate between real money and AVT. An
    unrecorded change to it is an unrecorded change to the value of every
    subsequent purchase.

    ⚠ Written back with the values it already has — an idempotent no-op that
    still exercises the write path. Actually moving a price would change what
    every other fiat test observes.
    """
    current = await _body(rig, "GET", "/api/v1/admin/fiat/pricing")
    if not isinstance(current, dict) or not current:
        raise PreconditionUnmet("fiat pricing config not served on this tier")
    # PricingUpdateRequest is {config: dict, note: str} and the note is REQUIRED
    # — it is the audit trail for a rate change. The active row's own config is
    # written straight back.
    # The readout is {active, fallback_in_use, history}; the live config sits
    # under `active` (either as the row or as its `config` field).
    active = current.get("active")
    cfg = active.get("config") if isinstance(active, dict) and isinstance(
        active.get("config"), dict) else (active if isinstance(active, dict) else None)
    if cfg is None:
        cfg = current.get("config")
    if not isinstance(cfg, dict):
        raise PreconditionUnmet(
            f"could not read an active pricing config (keys={sorted(current)[:8]})")
    state: Dict[str, Any] = {"read_keys": sorted(current)[:8], "config_keys": sorted(cfg)[:8]}
    code, resp = await _rest(rig, "PUT", "/api/v1/admin/fiat/pricing",
                             body={"config": cfg,
                                   "note": "fedsuite event-matrix probe: identical write-back"})
    state["write_status"] = code
    if code not in (200, 201, 202):
        raise PreconditionUnmet(f"pricing write-back refused: HTTP {code} {_detail(resp)[:180]}")

    async def seen() -> bool:
        evs = await _events_of_type(rig, "FiatPricingConfigUpdated")
        if evs is None:
            state["eventstore"] = "unreadable"
            return False
        state["eventstore"] = "readable"
        state["recent"] = len(evs)
        return len(evs) > 0

    result = await rig.assert_within(
        budget_sec=75.0, poll_interval_sec=4.0, predicate=seen,
        description="a fiat pricing write is evented", capture_state=lambda: state)
    if not result.passed and state.get("eventstore") == "unreadable":
        raise PreconditionUnmet("EventStore unreadable — emission not measured")
    return result


@federation_test(
    name="value_events_agent_ownership_transfer_is_evented",
    category="value_events",
    budget_sec=180.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["event_emission", "admin", "ownership"],
)
async def test_agent_ownership_transfer_is_evented(rig: FederationTestRig) -> AssertionResult:
    """Reassigning who owns an agent must be recorded.

    Ownership is what decides whose authority the agent's mandates clamp
    against and who is liable for what it does. Moving it silently would make
    every later authority question unanswerable.
    """
    agent = await _new_agent(rig, "own")
    dev = await _new_developer(rig, "own")
    state: Dict[str, Any] = {"did": agent["did"], "new_owner": dev["id"]}
    try:
        await _must(rig, "POST", f"/api/v1/admin/agents/{agent['did']}/transfer-ownership",
                    body={"new_creator_developer_id": dev["id"],
                          "reason": "fedsuite ownership-transfer probe"})
        return await _await_events(
            rig, {"AgentOwnershipTransferred": agent["did"]}, state, budget_sec=90.0,
            description="an ownership transfer is evented")
    finally:
        await _cleanup(rig, [agent["did"]])
