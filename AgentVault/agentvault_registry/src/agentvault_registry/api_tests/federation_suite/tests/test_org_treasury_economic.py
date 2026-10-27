"""THE ORG TREASURY LOOP driven end to end — remit in, fund out, sweep dry.

Three of the money-shaped event types the suite has never driven live on this
one rail: `OrganizationTreasuryRemitted` (money IN, authorised by the agent),
`OrganizationTreasuryFunded` (money OUT to an org agent, authorised by an org
admin) and `OrganizationTreasurySwept` (the exit rail, owner only). Until now
nothing in the suite touched them at all — not even a pin.

⚠ WHY A DRIVEN TEST IS THE ONLY THING THAT CAN CHECK THIS RAIL.
`org_treasury._emit_org_money_event` ends in a bare `except Exception` with the
comment "Emission must never break a money path, hence the swallow". That is a
defensible product decision and it is also §S4's exact shape: the money moves
through the escrow mover's own ledger legs, so a dead emitter costs the org its
audit trail while every balance and the supply invariant stay perfectly happy.
Δ CANNOT SEE THIS. Reading rows that happen to exist cannot either — a pin
cannot tell a live emitter from one that last fired a week ago. Performing the
act and then demanding the row is the only instrument that distinguishes them.

The loop is also a conservation check with a shape Δ does not provide: money
leaves an agent, sits in a keyless account no JWT can ever spend from, comes
back, and is drained. If any leg silently half-executed, the closing balances
would not reconcile even though Δ stayed 0.0.

⚠ AGGREGATE KEY IS THE ORG, NOT A DID — `_emit_org_money_event` passes
`aggregate_id=str(org_id)`, `aggregate_type="Organization"`. Querying a DID
aggregate for these returns zero and reads exactly like a dead emitter, which is
the §MONEY aggregate-key trap this suite has now hit on three separate rails.

Sandbox treasury funding is APPROVED for sandbox mainframes (2026-09-04) and
explicitly NOT for prod; `requires`-gated to the sandbox frames and funded
through the canonical admin rail (FLOW 4), never a direct TEG mint.

⚠ Writes: one org, its keyless treasury, and two agents per run, all tagged
`fedsuite-orgt-*`. The treasury is swept dry by the last step, so the residue is
the two soft-deleted agents and the org row — bounded and identifiable rather
than swept, stated rather than pretended.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
)
from agentvault_registry.api_tests.federation_suite.tests.test_contract_spine_economic import (
    _call, _rest, _num, _delta, _new_agent, _balance, _fund, _contract_event_types,
)

_FUND = "60.0"     # dust; enough to see three moves against, nothing on its own
_REMIT = "25.0"
_BACK = "10.0"

_TREASURY_EVENTS = [
    "OrganizationTreasuryRemitted",
    "OrganizationTreasuryFunded",
    "OrganizationTreasurySwept",
]


async def _org_events(rig, org_id: str) -> Optional[List[str]]:
    """Every event type the ES holds for this ORG's aggregate.

    Delegates to the contract spine's reader: `/api/v1/events/aggregate/{id}` is
    aggregate-TYPE-agnostic, so one implementation serves both and there is one
    place for its two traps rather than two places to get them wrong.

    ⚠ MY FIRST VERSION GOT BOTH TRAPS. It queried `/api/v1/events/aggregate` with
    `params={"aggregate_id": ...}` — the id is a PATH SEGMENT — and it unwrapped
    only a dict when that route answers with a LIST. It returned None, the test
    reported "audit trail incomplete", and every balance in the same run was
    provably correct. A null here is a claim about the QUERY until the query has
    returned non-zero for something.
    """
    return await _contract_event_types(rig, org_id)


async def _treasury_balance(rig, org_id: str) -> Optional[float]:
    """The keyless treasury's live balance, via the org's own rail.

    No JWT can be minted for a treasury by construction, so `getMyBalance` is not
    available for it — the org rail is the only reader. None = unreadable.
    """
    st, resp = await _rest(rig, "GET", f"/api/v1/organizations/{org_id}/treasury")
    if st != 200 or not isinstance(resp, dict):
        return None
    for k in ("balance", "treasury_balance", "liquid_balance", "token_balance"):
        if resp.get(k) is not None:
            return _num(resp[k])
    return None


@federation_test(
    name="org_treasury_loop_moves_money_and_is_evented",
    category="org_treasury",
    budget_sec=180.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["organizations", "treasury", "economic", "money", "delta", "event_emission"],
)
async def test_org_treasury_loop(rig: FederationTestRig) -> AssertionResult:
    """remit in → fund out → sweep dry, with money, Δ and the org's audit trail."""
    tag = uuid.uuid4().hex[:8]
    notes: Dict[str, Any] = {"tag": tag}

    d0 = await _delta(rig)
    notes["delta_start"] = d0

    # ── the org ───────────────────────────────────────────────────────────
    # ⚠ NO `slug` — `create_organization` derives it. Passing one is HTTP 400
    # "unexpected keyword argument 'slug'", which the precondition reports by
    # name rather than as a bare refusal.
    r, refused = await _call(rig, "sandbox-A", "createOrganization", {
        "name": f"Fedsuite OrgTreasury {tag}",
        "description": "federation suite org treasury probe",
    })
    if refused or not isinstance(r, dict):
        raise PreconditionUnmet(f"createOrganization refused: {refused}")
    org_id = r.get("id") or r.get("organization_id") or (r.get("organization") or {}).get("id")
    if not org_id:
        raise PreconditionUnmet(f"createOrganization returned no id (keys={sorted(r)[:8]})")
    notes["org_id"] = org_id

    st, resp = await _rest(rig, "POST", f"/api/v1/organizations/{org_id}/treasury")
    if st not in (200, 201):
        raise PreconditionUnmet(f"create treasury HTTP {st}: {json.dumps(resp, default=str)[:200]}")
    notes["treasury_created_http"] = st

    # ── the agents ────────────────────────────────────────────────────────
    member = await _new_agent(rig, f"orgt-{tag}-m")
    dest = await _new_agent(rig, f"orgt-{tag}-d")
    for a, who in ((member, "member"), (dest, "dest")):
        # ⚠ The DID is a PATH segment, not a body field — `POST /agents` with a
        # body is 405 Method Not Allowed, which reads like a missing rail.
        st, resp = await _rest(
            rig, "POST", f"/api/v1/organizations/{org_id}/agents/{a['did']}/assign")
        notes[f"assign_{who}_http"] = st
        if st not in (200, 201, 204):
            raise PreconditionUnmet(
                f"assign {who} to org HTTP {st}: {json.dumps(resp, default=str)[:180]}")

    if (fref := await _fund(rig, member["did"], _FUND)):
        raise PreconditionUnmet(f"seed funding refused: {fref}")

    b_member_0 = await _balance(rig, member["jwt"])
    t0 = await _treasury_balance(rig, org_id)
    notes["member_after_seed"] = b_member_0
    notes["treasury_start"] = t0
    if t0 is None:
        raise PreconditionUnmet("treasury balance unreadable — cannot measure the loop")

    # ── the three money steps run ONCE, OUTSIDE the poller ───────────────
    # `assert_within` re-invokes its predicate until the budget runs out. remit,
    # fund and sweep are NOT idempotent reads — driving them from inside a poll
    # loop would move real money on every attempt. Arrange here, assert there.
    # ⚠ ALL THREE RAILS REQUIRE AN `Idempotency-Key` HEADER (`_require_idem`) and
    # answer 400 without one — correct for money movement, and the reason this
    # test drove the discovery that `adminRequest` had NO way to send headers.
    # Five idempotency-REQUIRED rails were unreachable from MCP entirely, and the
    # other 27 idempotency-aware routes could only be called unkeyed, so a retry
    # moved money twice. Keys are per-run so a re-run is a fresh movement.
    hard: Optional[str] = None

    # 1. REMIT — the agent moves its OWN money in (agent-tier, its own JWT).
    st, resp = await _rest(rig, "POST", f"/api/v1/organizations/{org_id}/treasury/remit",
                           body={"amount": _REMIT}, jwt=member["jwt"],
                           headers={"Idempotency-Key": f"fedsuite-orgt-remit-{tag}"})
    notes["remit_http"] = st
    if st != 200:
        hard = (f"remit HTTP {st}: {json.dumps(resp, default=str)[:200]}. The remitting DID is "
                f"taken from the authenticated agent and needs `teg.transfer`, which the default "
                f"birth role `client` carries — a 403 means the birth roles changed, not that "
                f"the rail is gone.")

    # 2. FUND — the org ADMIN moves some back out to the same agent.
    if hard is None:
        st, resp = await _rest(rig, "POST", f"/api/v1/organizations/{org_id}/treasury/fund",
                               body={"agent_did": member["did"], "amount": _BACK},
                               headers={"Idempotency-Key": f"fedsuite-orgt-fund-{tag}"})
        notes["fund_http"] = st
        if st != 200:
            hard = f"fund HTTP {st}: {json.dumps(resp, default=str)[:200]}"

    # 3. SWEEP — the OWNER drains it. Full balance; there is no amount field.
    if hard is None:
        st, resp = await _rest(rig, "POST", f"/api/v1/organizations/{org_id}/treasury/sweep",
                               body={"dest_agent_did": dest["did"]},
                               headers={"Idempotency-Key": f"fedsuite-orgt-sweep-{tag}"})
        notes["sweep_http"] = st
        if st != 200:
            hard = f"sweep HTTP {st}: {json.dumps(resp, default=str)[:200]}"

    # ── settle, then judge everything in one predicate ────────────────────
    async def _settled() -> bool:
        if hard:
            return False
        types = await _org_events(rig, org_id)
        notes["org_event_types"] = sorted(set(types)) if types is not None else None
        notes["treasury_end"] = await _treasury_balance(rig, org_id)
        notes["dest_end"] = await _balance(rig, dest["jwt"])
        notes["member_end"] = await _balance(rig, member["jwt"])
        notes["delta_end"] = await _delta(rig)

        # The org's audit trail — the ONLY thing that can see a swallowed emit.
        if types is None or not all(t in types for t in _TREASURY_EVENTS):
            return False
        # A sweep drains by definition.
        t_end = notes["treasury_end"]
        if t_end is None or t_end > 0.000001:
            return False
        # The destination must hold what the loop left behind.
        if (notes["dest_end"] or 0.0) <= 0:
            return False
        # Δ is computed FROM events, so it cannot see a dropped emit — it is a
        # necessary check, never a sufficient one.
        d_end = notes["delta_end"]
        return d_end is not None and abs(d_end) <= 0.01

    return await rig.assert_within(
        budget_sec=(1.0 if hard else 60.0),
        predicate=_settled,
        description=(hard or
                     f"remit {_REMIT} in, fund {_BACK} out, sweep dry — money conserved, "
                     f"Δ still 0, and all three events on the ORG aggregate"),
        capture_state=lambda: notes,
    )
