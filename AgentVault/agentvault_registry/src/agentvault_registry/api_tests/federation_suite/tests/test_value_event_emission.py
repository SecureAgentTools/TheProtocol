"""Value-moving rails must reach the ledger, not merely return 200 (§FEDEVENTS).

Measured 2026-09-04 across the whole registry: **151 distinct event types are
emitted; the federation suite names 13.** Of the 138 nobody verifies, 35 touch
value — the settlement saga, the bridge lock/unlock pair, stake/unstake, the
dispute and settlement compensation mints, the funding lifecycle.

That is not a documentation gap, it is a Δ-blindness surface. The supply
invariant is computed FROM events (`projections.py:492` derives BOTH legs of a
transfer from the same `TokensTransferred`), so a dropped emit moves
`total_circulating` and `transit_net` by exactly zero: money moves in the TEG,
the EventStore never hears about it, and Δ sits at a contented 0.0. §VITALS
found that shape live in `TEGBulkProxy._flush` — the only site emitting for
coalesced transfers — wrapped in `except Exception: pass`.

So "balances moved AND Δ=0" is not proof of settlement. This file asserts the
missing half on the funding rail, which is the cheapest value-moving lifecycle
that can be driven end to end from a test: an agent asks, an admin approves,
money leaves the treasury.

⚠ Writes: creates a throwaway agent per run and moves DUST (1 AVT) through the
approved funding path on the SANDBOX tier only. Δ is asserted unchanged around
the movement — a transfer is Δ-neutral by construction, and if it is not, that
is the finding.
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
    _call, _rest, _detail, _new_agent, _cleanup, _events_for, _saw, _event_types, _done,
)

_DUST = "1.0"


async def _delta(rig) -> Optional[float]:
    """The supply invariant, from the EventStore. The REGISTRY does not serve
    /projections/supply-audit — asking it there returns 404, which reads like a
    breach and is really a wrong address."""
    r, refused = await _call(rig, "sandbox-A-admin", "adminQueryEventStore",
                             {"path": "/api/v1/projections/supply-audit"})
    if refused or not isinstance(r, dict):
        return None
    body = r.get("response") if isinstance(r.get("response"), dict) else r
    d = body.get("delta")
    if d is None:
        return None
    try:
        return float(str(d))
    except Exception:
        return None


@federation_test(
    name="value_event_funding_lifecycle_is_evented",
    category="value_events",
    budget_sec=180.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["event_emission", "money", "funding"],
)
async def test_funding_lifecycle_is_evented(rig: FederationTestRig) -> AssertionResult:
    """Request → approve must emit `FundingRequestCreated` AND `FundingRequestApproved`.

    Approval is the moment value leaves the treasury. Both events key on the
    REQUESTER's aggregate (`funding_requests.py:250` and `:437`) — checked in
    the source rather than assumed, because the last time an aggregate was
    guessed in this suite the query returned zero on both frames and very
    nearly got filed as money moving unrecorded.

    Δ is read before and after. A funding approval is a treasury→agent
    TRANSFER, so the invariant must not move; if it does, the rail is minting.
    """
    agent = await _new_agent(rig, "fund")
    state: Dict[str, Any] = {"did": agent["did"], "amount": _DUST}
    try:
        d0 = await _delta(rig)
        state["delta_before"] = d0

        code, created = await _rest(
            rig, "POST", "/api/v1/funding/request",
            body={"amount": _DUST,
                  "reason": "federation suite value-event probe: dust, sandbox only"},
            jwt=agent["jwt"])
        state["create_status"] = code
        if code not in (200, 201) or not isinstance(created, dict):
            raise PreconditionUnmet(f"funding request refused: HTTP {code} {_detail(created)}")
        req_id = created.get("id") or created.get("request_id")
        state["request_id"] = req_id
        if req_id is None:
            raise PreconditionUnmet(f"funding request returned no id (keys={sorted(created)[:8]})")

        code, approved = await _rest(
            rig, "POST", f"/api/v1/admin/funding/{req_id}/approve",
            body={"reason": "federation suite value-event probe"})
        state["approve_status"] = code
        if code not in (200, 201):
            # A refusal here is a real finding about the approve rail, not an
            # absent fixture — the request demonstrably exists.
            return _done(False, "funding approval succeeded", {
                **state, "approve_detail": _detail(approved)[:300]})
        if isinstance(approved, dict):
            state["funded"] = approved.get("status") or approved.get("funded")

        expected = {
            "FundingRequestCreated": {"request_id": req_id},
            "FundingRequestApproved": {"request_id": req_id},
        }

        async def predicate() -> bool:
            events = await _events_for(rig, agent["did"])
            if events is None:
                state["eventstore"] = "unreadable"
                return False
            state["eventstore"] = "readable"
            state["event_types"] = sorted(set(_event_types(events)))[:15]
            seen = {t: _saw(events, t, m) for t, m in expected.items()}
            state["seen"] = seen
            state["missing"] = sorted(t for t, ok in seen.items() if not ok)
            return all(seen.values())

        result = await rig.assert_within(
            budget_sec=75.0, poll_interval_sec=3.0, predicate=predicate,
            description="funding request + approval both reach the EventStore",
            capture_state=lambda: state,
        )
        d1 = await _delta(rig)
        state["delta_after"] = d1
        # Δ is a SEPARATE verdict from the emission. A transfer that moved the
        # invariant is a breach whether or not the event landed, and it must not
        # be able to hide behind a green emission check.
        state["delta_unchanged"] = (d0 is not None and d1 is not None and abs(d1 - d0) < 1e-9)
        if not result.passed and state.get("eventstore") == "unreadable":
            raise PreconditionUnmet("EventStore unreadable — emission not measured")
        if d0 is not None and d1 is not None and abs(d1 - d0) >= 1e-9:
            return _done(False, "funding approval is Δ-neutral", state)
        return result
    finally:
        await _cleanup(rig, [agent["did"]])


@federation_test(
    name="value_event_a2a_authorize_is_evented",
    category="value_events",
    budget_sec=150.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["event_emission", "money", "a2a"],
)
async def test_a2a_authorize_is_evented(rig: FederationTestRig) -> AssertionResult:
    """`A2APaymentAuthorized` must reach the ledger.

    Authorization reserves value rather than moving it, which is exactly why
    its emission is easy to lose and worth pinning: the token it mints is a
    claim on funds that a later settle will honour, and the authorize event is
    the only record of when that claim came into existence. Keyed on the
    CALLER's aggregate (`a2a_payment.py:510`).
    """
    payer = await _new_agent(rig, "a2a-payer")
    payee = await _new_agent(rig, "a2a-payee")
    state: Dict[str, Any] = {"payer": payer["did"], "payee": payee["did"]}
    try:
        # Authorize reserves funds, so the payer needs some. Funded through the
        # CANONICAL admin rail (FLOW 4) — never a direct TEG mint, which bypasses
        # the registry's `TokensIssued` emission and is an instant Δ breach.
        # ⚠ the field is `target_agent_did`; `agent_did` 422s.
        code, funded = await _rest(
            rig, "POST", "/api/v1/teg/treasury/fund-agent",
            body={"target_agent_did": payer["did"], "amount": "10.0",
                  "reason": "federation suite a2a authorize probe"})
        state["fund_status"] = code
        if code not in (200, 201):
            raise PreconditionUnmet(
                f"treasury funding refused: HTTP {code} {_detail(funded)}")

        code, auth = await _rest(
            rig, "POST", "/api/v1/a2a-payment/authorize",
            body={"target_agent_did": payee["did"], "amount": _DUST},
            jwt=payer["jwt"])
        state["authorize_status"] = code
        if code not in (200, 201) or not isinstance(auth, dict):
            raise PreconditionUnmet(f"a2a authorize refused: HTTP {code} {_detail(auth)}")
        tok_id = auth.get("token_id") or auth.get("id")
        state["token_id"] = tok_id

        async def predicate() -> bool:
            events = await _events_for(rig, payer["did"])
            if events is None:
                state["eventstore"] = "unreadable"
                return False
            state["eventstore"] = "readable"
            state["event_types"] = sorted(set(_event_types(events)))[:15]
            match = {"token_id": tok_id} if tok_id is not None else None
            return _saw(events, "A2APaymentAuthorized", match)

        result = await rig.assert_within(
            budget_sec=60.0, poll_interval_sec=3.0, predicate=predicate,
            description="A2APaymentAuthorized reaches the EventStore",
            capture_state=lambda: state,
        )
        if not result.passed and state.get("eventstore") == "unreadable":
            raise PreconditionUnmet("EventStore unreadable — emission not measured")
        return result
    finally:
        await _cleanup(rig, [payer["did"], payee["did"]])
