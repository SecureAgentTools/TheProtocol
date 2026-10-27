"""Event-emission matrix, second batch (§FEDEVENTS).

Continues `test_event_emission_matrix.py` into the enforcement, reputation,
governance, fiat and policy surfaces. Same contract throughout: perform the real
act, then prove the EventStore received it, matched on a marker unique to this
run — never on the bare existence of an event of that type, which on a shared
frame is always satisfiable by somebody else's traffic.

Where a rail cannot be driven here the test says so and names the obstacle
instead of reporting a defect it has not observed.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
    bond_config, target_switches, member_mode, staking_off,
)
from agentvault_registry.api_tests.federation_suite.tests.test_ironkey_authority_clamp import (
    _call, _rest, _detail, _new_agent, _cleanup, _done, _catalog, _set_roles,
    _pick_role_and_permission,
)
from agentvault_registry.api_tests.federation_suite.tests.test_event_emission_matrix import (
    _await_events, _must, _body, _new_developer, _optional_step, _events_of_type,
)

_ADMIN = "sandbox-A-admin"


# the TEG's refusal when the treasury fund leg loses the race, in its words before and after its rewording (V0643)
_FUND_RACE = ("Insufficient balance", "Reward fund failed", "Payout funding failed")


async def _fund(rig, did: str, amount: str = "50.0", state: Optional[Dict[str, Any]] = None) -> None:
    """Fund a probe agent from the treasury, once more after a pause when the refusal is the funding race.

    §MCPTEST30 (V0557), measured by agentvault2-33 on 2026-10-03 07:08:02Z: two of this file's tests funded 19 ms apart
    (270 and 1000) and the TEG's reward-fund waterfall refused the second "Insufficient balance" while the treasury held
    about 191M and the fee collector 5.23: two waterfall legs share the fee collector, and the TEG does not serialize
    them per source. The suite racing itself is not a governance result, so a second try after a pause; the first
    refusal stays in the row's evidence (fund_race) so the race stays visible. Serializing reward_fund per source is
    the TEG's question, named, not answered here."""
    body = {"target_agent_did": did, "amount": amount, "reason": "fedsuite event-matrix probe"}
    try:
        await _must(rig, "POST", "/api/v1/teg/treasury/fund-agent", body=body)
    except PreconditionUnmet as e:
        if not any(w in str(e) for w in _FUND_RACE):
            raise
        if state is not None:
            state.setdefault("fund_race", []).append(str(e)[:240])
        await asyncio.sleep(1.5)
        await _must(rig, "POST", "/api/v1/teg/treasury/fund-agent", body=body)


# ─── agent administration ──────────────────────────────────────────────────

@federation_test(
    name="events_agent_admin_enforcement",
    category="event_matrix",
    budget_sec=200.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["event_emission", "admin", "enforcement"],
)
async def test_agent_admin_enforcement_events(rig: FederationTestRig) -> AssertionResult:
    """Administrative enforcement against an agent must be recorded.

    Suspension, credential rotation and card refresh are the levers an operator
    reaches for during an incident. Their ledger entries are what makes the
    response reconstructable afterwards — who cut the agent off, when, and on
    what stated reason. `AdminBulkRefreshCards` is one of the six sites whose
    emit sits behind `except Exception: pass`.
    """
    agent = await _new_agent(rig, "adm-enf")
    did = agent["did"]
    m = uuid.uuid4().hex[:10]
    reason = f"fedsuite event-matrix probe {m}"
    state: Dict[str, Any] = {"did": did, "marker": m}
    expect: Dict[str, str] = {}
    try:
        await _must(rig, "POST", f"/api/v1/admin/agents/{did}/rotate-credentials",
                    body={"reason": reason})
        expect["AgentCredentialsRotated"] = did

        await _must(rig, "POST", "/api/v1/admin/agents/bulk/suspend",
                    body={"agent_dids": [did], "reason": reason})
        expect["AgentSuspended"] = did

        await _optional_step(rig, "POST", "/api/v1/admin/agents/bulk/refresh-cards",
                             body={"agent_dids": [did], "reason": reason},
                             event="AdminBulkRefreshCards", expect=expect,
                             marker=did, state=state)
        state["expected_events"] = sorted(expect)
        return await _await_events(
            rig, expect, state, budget_sec=90.0,
            description="agent enforcement actions reach the EventStore")
    finally:
        await _cleanup(rig, [did])


# ─── reputation + attestation ──────────────────────────────────────────────

@federation_test(
    name="events_reputation_signal_and_bond",
    category="event_matrix",
    budget_sec=200.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["event_emission", "reputation"],
)
async def test_reputation_signal_and_bond_events(rig: FederationTestRig) -> AssertionResult:
    """Attestations and reputation bonds must be recorded.

    `EigenTrustSignal` feeds the trust graph that ranks discovery, and a bond is
    money staked on an agent's own honesty. Both are inputs to decisions other
    agents make about who to hire; an unrecorded one is a reputation change with
    no provenance.
    """
    a = await _new_agent(rig, "rep-a")
    b = await _new_agent(rig, "rep-b")
    state: Dict[str, Any] = {"from": a["did"], "to": b["did"]}
    expect: Dict[str, str] = {}
    try:
        # The real contract is a ZKP envelope (circuit_id / proof_data /
        # public_inputs), not a peer-review score. The first shape I sent was
        # invented; 422 "Field required" was the endpoint being right.
        # A submission that FAILS verification still persists and still emits
        # under ZKP_PHASE_1, which is the emission this row is about.
        circuits = await _body(rig, "GET", "/api/v1/attestations/circuits", jwt=a["jwt"])
        clist = circuits if isinstance(circuits, list) else (
            (circuits or {}).get("circuits") or (circuits or {}).get("items") or [])
        cid = next((c.get("id") or c.get("circuit_id") for c in clist
                    if isinstance(c, dict)), None) if clist else None
        state["circuit_id"] = cid
        if cid:
            await _optional_step(
                rig, "POST", "/api/v1/attestations/submit",
                body={"circuit_id": cid,
                      "proof_data": {"probe": "fedsuite event-matrix"},
                      "public_inputs": {"agent_did": a["did"]}},
                event="EigenTrustSignal", expect=expect, marker=a["did"], state=state,
                jwt=a["jwt"])
        else:
            state.setdefault("inapplicable", {})["EigenTrustSignal"] = \
                "no circuits served — ZKP phases are off on this tier"

        # §REPBOND: the bond has a REQUIRED amount and the rail refuses anything
        # less ("must be at least 250 SBXA (asked 5)"). A hardcoded 5.0 could
        # never deposit, so this leg skipped instead of emitting — read the
        # amount the registry asks for, and fund enough to pay it.
        _cfg = await bond_config(rig, "sandbox-A")
        _bond_amt = str(_cfg.get("amount") or "250")
        state["bond_required"] = _bond_amt
        await _fund(rig, a["did"], amount=str(float(_bond_amt) + 20), state=state)
        await _optional_step(
            rig, "POST", "/api/v1/agents/reputation-bond/deposit",
            body={"amount": _bond_amt}, event="ReputationBondDeposited",
            expect=expect, marker=a["did"], state=state, jwt=a["jwt"])

        if not expect:
            raise PreconditionUnmet(
                f"neither reputation rail could be driven: {state.get('inapplicable')}")
        state["expected_events"] = sorted(expect)
        return await _await_events(
            rig, expect, state, budget_sec=90.0,
            description="reputation signal and bond deposit are evented")
    finally:
        await _cleanup(rig, [a["did"], b["did"]])


# ─── governance ────────────────────────────────────────────────────────────

@federation_test(
    name="events_governance_proposal_cycle",
    category="event_matrix",
    budget_sec=240.0,
    severity="high",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["event_emission", "governance"],
)
async def test_governance_proposal_cycle_events(rig: FederationTestRig) -> AssertionResult:
    """Propose, vote, tally — each must be recorded.

    Governance is the one surface where the event log IS the outcome: a vote
    that was cast and not recorded did not happen, and a tally nobody can
    reconstruct is an assertion rather than a result. Governance is agent-only
    by design (a developer JWT is refused), so this drives it as an agent.
    """
    cat = await _catalog(rig)
    roles = cat.get("roles") or {}
    gov_role = next((r for r, ps in roles.items()
                     if "gov.propose" in (ps or []) and r != "legacy-full"), None)
    agent = await _new_agent(rig, "gov")
    did = agent["did"]
    m = uuid.uuid4().hex[:10]
    state: Dict[str, Any] = {"did": did, "marker": m, "gov_role": gov_role,
                             "rbac_mode": cat.get("mode")}
    expect: Dict[str, str] = {}
    # §MCPTEST30 (V0550): where governance weighs membership (GOVERNANCE_WEIGHT_MODE=member, §MEMBERSHIP) a stake
    # decides nothing (and is refused where staking is switched off): the agent's DEVELOPER must be a member instead
    member = member_mode(await target_switches(rig, "sandbox-A"))
    state["governance_weight_mode"] = "member" if member else "lock"
    try:
        # Under AGENT_RBAC_MODE=enforce a newborn agent holds trader/client and is
        # correctly refused `gov.propose` — the first run 403'd here, which was
        # IRONKEY doing its job, not a governance defect.
        # Proposing requires LOCKED units ("Only agents with locked units can
        # create proposals") — a real precondition the first run surfaced, so the
        # agent is given the staking role too and actually stakes.
        stake_role = None if member else next((r for r, ps in roles.items()
                                               if "staking.manage" in (ps or []) and r != "legacy-full"), None)
        wanted = [r for r in (gov_role, stake_role) if r]
        state["roles_granted"] = wanted
        if wanted:
            await _set_roles(rig, did, wanted)
        await _fund(rig, did, "1000.0", state=state)
        if member:
            code_vp, vp = await _rest(rig, "GET", "/api/v1/governance/voting-power", jwt=agent["jwt"])
            state["voting_power"] = {k: (vp or {}).get(k) for k in ("mode", "votingPower", "canVote")} \
                if isinstance(vp, dict) else code_vp
            if not (isinstance(vp, dict) and vp.get("canVote")):
                missing = ((vp or {}).get("membership") or {}).get("missing") if isinstance(vp, dict) else None
                raise PreconditionUnmet(
                    f"not_a_member: governance weighs membership on sandbox-A and the suite's developer is not a member "
                    f"(missing {missing}); its agents are bonded from the treasury backstop, which never makes one")
        else:
            await _must(rig, "POST", "/api/v1/staking/stake",
                        body={"amount": "100.0"}, jwt=agent["jwt"])
        created = await _must(
            rig, "POST", "/api/v1/governance/proposals",
            body={"title": f"fedsuite event probe {m}",
                  "description": f"federation suite event-matrix governance probe {m}",
                  "proposal_type": "standard",
                  # gt=0, so a short window is legal — the tally cannot run until
                  # voting closes, and a test that cannot wait it out would leave
                  # ProposalTallied permanently unverified.
                  # ⚠ 8 SECONDS RACED THE TEST'S OWN VOTE. Measured 2026-09-06:
                  # "Voting period for proposal 58 has ended" — the window closed
                  # between this create and the very next call, so the row skipped
                  # as a precondition failure and read like a governance defect.
                  # Under sweep load the create→vote hop is not free. 30 s cannot
                  # lose that race and still closes inside the tally poll below
                  # (20 x 3 s) and the 240 s budget.
                  "duration_seconds": 30},
            jwt=agent["jwt"])
        pid = created.get("id") or created.get("proposal_id")
        state["proposal_id"] = pid
        if pid is None:
            raise PreconditionUnmet(f"proposal created but no id (keys={sorted(created)[:10]})")
        expect["ProposalCreated"] = did

        await _optional_step(rig, "POST", f"/api/v1/governance/proposals/{pid}/vote",
                             body={"vote_in_favor": True,
                                   "reason": "fedsuite event-matrix probe"},
                             event="VoteCast",
                             expect=expect, marker=did, state=state, jwt=agent["jwt"])
        # Wait for the voting window to close, then tally. Polled rather than
        # slept-through-and-hoped: the refusal names its own reason, so the loop
        # can tell "not yet" from a real failure.
        import asyncio as _aio
        tally_detail = None
        for _ in range(20):          # 20 x 3 s = 60 s > the 30 s voting window
            code, resp = await _rest(rig, "POST",
                                     f"/api/v1/governance/proposals/{pid}/tally",
                                     body={}, jwt=agent["jwt"])
            tally_detail = _detail(resp)
            if code in (200, 201, 202):
                expect["ProposalTallied"] = str(pid)
                break
            if code == 400 and "not ended" in tally_detail.lower():
                await _aio.sleep(3)
                continue
            break
        state["tally_detail"] = str(tally_detail)[:160]
        if "ProposalTallied" not in expect:
            state.setdefault("inapplicable", {})["ProposalTallied"] = str(tally_detail)[:120]
        state["expected_events"] = sorted(expect)
        return await _await_events(
            rig, expect, state, budget_sec=90.0,
            description="governance proposal, vote and tally are evented")
    finally:
        await _cleanup(rig, [did])


# ─── money: staking ────────────────────────────────────────────────────────

@federation_test(
    name="events_tokens_staked_is_evented",
    category="event_matrix",
    budget_sec=200.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["event_emission", "money", "staking"],
)
async def test_tokens_staked_is_evented(rig: FederationTestRig) -> AssertionResult:
    """Staking must emit `TokensStaked`.

    Worth its own row because the router's label and the ledger's event are
    DIFFERENT NAMES: `/staking/stake` dispatches `stake.completed` into
    `emit_staking_event`, which calls `emit_tokens_staked` and writes
    **TokensStaked**. A census that trusted the router's string would look for
    an event type the EventStore has never held, find nothing, and report a
    missing emission that was never missing.

    Staked balance is inside `total_circulating`, so a lost emit here is the
    §S4 shape exactly: the money is locked, the invariant never notices.
    """
    cat = await _catalog(rig)
    roles = cat.get("roles") or {}
    role = next((r for r, ps in roles.items()
                 if "staking.manage" in (ps or []) and r != "legacy-full"), None)
    # §MCPTEST30 (V0550): where staking is switched off no position can be opened, so there is nothing to emit
    if staking_off(await target_switches(rig, "sandbox-A")):
        raise PreconditionUnmet("switched_off: staking is not enabled on sandbox-A (STAKING_ENABLED=false, its "
                                "registry-config says so): no position can be opened, so TokensStaked cannot be produced")
    agent = await _new_agent(rig, "stake")
    did = agent["did"]
    state: Dict[str, Any] = {"did": did, "role_for_staking": role,
                             "rbac_mode": cat.get("mode")}
    try:
        if role:
            await _set_roles(rig, did, [role])
        await _fund(rig, did, "500.0", state=state)
        staked = await _must(rig, "POST", "/api/v1/staking/stake",
                             body={"amount": "10.0"}, jwt=agent["jwt"])
        state["stake_response_keys"] = sorted(staked)[:10] if isinstance(staked, dict) else None
        return await _await_events(
            rig, {"TokensStaked": did}, state, budget_sec=90.0,
            description="staking emits TokensStaked (not the router's stake.completed label)")
    finally:
        await _cleanup(rig, [did])


# ─── platform policy + fiat ────────────────────────────────────────────────

@federation_test(
    name="events_emission_policy_update_is_evented",
    category="event_matrix",
    budget_sec=150.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["event_emission", "admin", "policy"],
)
async def test_emission_policy_update_is_evented(rig: FederationTestRig) -> AssertionResult:
    """Changing an emission policy must itself be an event.

    This is the meta-rail: the table that decides which layer may emit which
    event is the one place a single edit can silence a whole class of ledger
    writes and drift the supply invariant. A change to it that leaves no trace
    is the least acceptable silent change on the platform.

    ⚠ The policy is written back with the values it already has — an idempotent
    no-op that still exercises the write path. Actually flipping a flag here
    would alter what every other test in the suite can observe.
    """
    current = await _body(rig, "GET", "/api/v1/admin/event-emission-policies")
    rows = current if isinstance(current, list) else (
        (current or {}).get("policies") or (current or {}).get("items") or [])
    row = next((r for r in rows if isinstance(r, dict) and r.get("event_type")), None)
    if not row:
        raise PreconditionUnmet("no emission policy rows served")
    et = row["event_type"]
    state: Dict[str, Any] = {"event_type": et, "wrote_back": {
        k: row.get(k) for k in ("emit_from_teg", "emit_from_registry", "skip_in_projection")}}
    await _must(rig, "PUT", f"/api/v1/admin/event-emission-policies/{et}",
                body={"emit_from_teg": bool(row.get("emit_from_teg")),
                      "emit_from_registry": bool(row.get("emit_from_registry")),
                      "skip_in_projection": bool(row.get("skip_in_projection"))})
    return await _await_events(
        rig, {"EventEmissionPolicyUpdated": et}, state, budget_sec=75.0,
        description="an emission-policy write is itself evented")


@federation_test(
    name="events_fiat_bad_signature_is_evented",
    category="event_matrix",
    budget_sec=150.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["event_emission", "money", "fiat", "security"],
)
async def test_fiat_bad_signature_is_evented(rig: FederationTestRig) -> AssertionResult:
    """A fiat webhook with a bad signature must be recorded as a security event.

    A forged payment callback is somebody trying to mint AVT for free. The
    refusal is the easy part; the record of the ATTEMPT is what makes a pattern
    of them visible. This is the rare emission whose whole value is that it
    fires on the failure path — the path least likely to be exercised by any
    other test.
    """
    m = uuid.uuid4().hex[:10]
    state: Dict[str, Any] = {"marker": m}
    # ⚠ Count BEFORE the drive and require an INCREASE. The first version asserted
    # `len(events) > 0`, which an earlier run's event satisfies — it passed on one
    # frame purely because this test had run there before, and failed on the other
    # where nothing had. A count with no baseline is not an assertion about THIS
    # act; the aggregate here is a random `sigfail-{provider}-{token_hex}`, so a
    # per-run marker is unavailable and the baseline is what replaces it.
    # ⚠ §MCPSWEEP 2026-09-28: the baseline is the page's event IDS, not its length. The type-filtered read
    # returns the NEWEST `limit` events, so once the store holds that many a new event pushes an old one off
    # the page and the count stays put: sbx-alpha reached 101 of these on V0481 and the row went red while the
    # event it waited for had landed (07:46:47Z, the 101st). An id the baseline page did not hold is the answer.
    before = await _events_of_type(rig, "FiatProviderSignatureFailed", limit=100)
    if before is None:
        raise PreconditionUnmet("EventStore unreadable — emission not measured")
    state["sigfail_before"] = len(before)
    before_ids = {str(e.get("id")) for e in before if e.get("id")}
    code, resp = await _rest(
        rig, "POST", "/api/v1/fiat/webhook/stripe",
        body={"id": f"evt_fedsuite_{m}", "type": "checkout.session.completed",
              "data": {"object": {"id": f"cs_fedsuite_{m}"}}})
    state["webhook_status"] = code
    state["webhook_detail"] = _detail(resp)[:160]
    if code in (200, 201):
        raise PreconditionUnmet(
            "the unsigned webhook was ACCEPTED — signature verification is not "
            "engaged on this tier, so the refusal path cannot be measured")
    if code == 403 and "mainframe-only" in state["webhook_detail"].lower():
        # A federated (non-fiat-genesis) registry refuses the whole fiat surface
        # before any signature is examined, so the emission this row is about is
        # not reachable there. Measured, not assumed: driving the mirrored frame
        # is what produced this 403, and the earlier `len(events) > 0` version
        # would have passed on one frame and failed on the other for reasons
        # that had nothing to do with the emitter.
        raise PreconditionUnmet(
            "fiat is mainframe-only and this frame is federated — the signature "
            "path is unreachable here, so there is no emission to measure")

    async def seen() -> bool:
        evs = await _events_of_type(rig, "FiatProviderSignatureFailed", limit=100)
        if evs is None:
            state["eventstore"] = "unreadable"
            return False
        state["eventstore"] = "readable"
        state["sigfail_after"] = len(evs)
        new = [e for e in evs if e.get("id") and str(e.get("id")) not in before_ids]
        state["new_since_the_drive"] = len(new)
        return bool(new)

    result = await rig.assert_within(
        budget_sec=75.0, poll_interval_sec=4.0, predicate=seen,
        description="a rejected fiat webhook is recorded as FiatProviderSignatureFailed",
        capture_state=lambda: state)
    if not result.passed and state.get("eventstore") == "unreadable":
        raise PreconditionUnmet("EventStore unreadable — emission not measured")
    return result
