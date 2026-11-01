"""A cross-frame dispute settlement the defendant's home APPROVES (tester batch 2 item 4, part 2, agentvault2-d3,
2026-10-31, Guild order gwo_e3bad842b1a5943022b01d40; the sibling of agentvault2-aa's V0639 rejection).

The settlement path's other half: approveDisputeSettlement slashes the defendant on its home and the home confirms the
slash to the complainant's home (/federation/disputes/slash-confirmation), which pays the complainant. Both halves are
peer routes no MCP caller can reach, and the rejection measures only the first. Here, ONLY on a target torn down after
its run (MCP_TESTER_EPHEMERAL_TARGET: the nightly and proof pairs) and only against throwaway agents of the run's own
(session-lead's limit for this order): sandbox-B's administrator funds the run's defendant with the amount from its
treasury (a transfer), the complainant on sandbox-A files the dispute, A's administrator rules for the complainant,
B holds the request for an administrator (the amount is over every auto-slash threshold B holds) and B's administrator
approves it. Read back: B's settlement SLASHED in full and the defendant's balance down by the amount (its home's
treasury/receive: a transfer, never a burn); A's settlement SETTLED and the complainant paid the amount through A's
payout funding (the fee collector, then the treasury: a transfer, never an issuance; his D9, no mint). A standing frame
skips it, named (pair_only).

⚠ Writes, on the pair only: two throwaway agents named `fedsuite-settle-*` (retired at the end), one dispute on
sandbox-A and one settlement row on each frame; the amount moves B's treasury -> the defendant -> B's treasury, and A's
payout pools -> the complainant. Both frames' ledgers read 0.0 after (the nightly reads them).
"""
from __future__ import annotations

import os

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import AssertionResult, FederationTestRig, PreconditionUnmet
from agentvault_registry.api_tests.federation_suite.tests.test_cross_registry_settlement_reject import (
    _A, _ADMIN, _B, _MIRROR_SEC, _PENDING, _REQUIRES, _SETTLE_SEC, _agent, _num, _settlements,
    amount_over_every_threshold, ours, settlement_of,
)
from agentvault_registry.api_tests.federation_suite.tests.test_twoagent_contract_xframe import (
    _balance, _call, _run, _until,
)
from agentvault_registry.services.registry_card_builder import _dialable_from_outside

EPHEMERAL_ENV = "MCP_TESTER_EPHEMERAL_TARGET"
PAIR_ONLY = (f"a slash of the run's own throwaway moves units, so the approve path runs only where its target is torn "
             f"down after its run ({EPHEMERAL_ENV}=true: the nightly and proof pairs)")


def on_a_pair() -> bool:
    return str(os.environ.get(EPHEMERAL_ENV, "")).strip().lower() in ("1", "true", "yes", "on")


@federation_test(
    name="xframe_settlement_the_home_approves_and_the_origin_pays",
    category="disputes_xframe",
    budget_sec=600.0,
    severity="critical",
    requires=_REQUIRES,
    tags=["disputes", "xframe", "owl25", "cross_frame", "settlements", "money", "pair_only", "batch2"],
)
async def test_xframe_settlement_approve(rig: FederationTestRig) -> AssertionResult:
    if not on_a_pair():
        raise PreconditionUnmet(f"NOT MEASURED: {PAIR_ONLY}")
    planned = ["the_amount_is_over_every_threshold_the_home_holds", "the_home_funds_the_defendant_the_amount",
               "the_origin_takes_the_dispute", "the_evidence_names_the_amount", "the_origin_rules_for_the_complainant",
               "the_home_holds_it_for_an_administrator", "approveDisputeSettlement_slashes_it_in_full",
               "the_defendant_lost_the_amount", "the_origin_settles", "the_complainant_was_paid_the_amount"]

    async def body(legs, made, hooks):
        cfg, refused = await _call(rig, _B, "getPeerSlashConfig", {})
        peers = cfg.get("peers") if isinstance(cfg, dict) else None
        if refused or not isinstance(peers, list):
            raise PreconditionUnmet(f"getPeerSlashConfig on {_B}: {refused or str(cfg)[:160]}")
        amount = amount_over_every_threshold(peers)
        legs.check("the_amount_is_over_every_threshold_the_home_holds", amount >= 1, {"amount": amount})

        defendant = await _agent(rig, _B, "defendant", made)
        complainant = await _agent(rig, _A, "complainant", made)
        _f, why = await _call(rig, _ADMIN[_B], "adminRequest", {
            "method": "POST", "endpoint": "/api/v1/teg/treasury/fund-agent",
            "body": {"target_agent_did": defendant["did"], "amount": str(amount), "reason": "admin_grant",
                     "reference_id": f"fedsuite-settle-fund-{defendant['did'][-8:]}"}})
        d0 = await _until(lambda: _held(rig, _B, defendant["jwt"], amount), _SETTLE_SEC)
        if not legs.check("the_home_funds_the_defendant_the_amount", not why and d0 is not None,
                          {"refused": why, "balance": d0}):
            return
        c0 = await _balance(rig, _A, complainant["jwt"])

        async def _file():
            r, w = await _call(rig, _A, "submitDispute", {
                "agent_jwt": complainant["jwt"], "defendant_did": defendant["did"],
                "description": "federation suite: a cross-frame settlement the home approves (a pair only)"})
            if w and "not known to this registry" in w:
                return None
            return {"r": r, "refused": w}
        filed = await _until(_file, _MIRROR_SEC)
        r = (filed or {}).get("r")
        dispute_id = str((r or {}).get("id") or (r or {}).get("dispute_id") or "") if isinstance(r, dict) else ""
        if not legs.check("the_origin_takes_the_dispute", bool(dispute_id) and not (filed or {}).get("refused"),
                          {"refused": (filed or {}).get("refused")}):
            return
        _, why = await _call(rig, _A, "submitDisputeEvidence", {
            "agent_jwt": complainant["jwt"], "dispute_id": dispute_id,
            "evidence_data": {"amount_disputed": amount, "note": "federation suite settlement probe (approve)"}})
        if not legs.check("the_evidence_names_the_amount", not why, {"refused": why}):
            return
        ruled, why = await _call(rig, _ADMIN[_A], "updateDisputeRuling",
                                 {"dispute_id": dispute_id, "ruling": "IN_FAVOR_OF_COMPLAINANT"})
        comp = (ruled or {}).get("compensation") if isinstance(ruled, dict) else None
        sent = isinstance(comp, dict) and comp.get("settlement_status") == "pending_remote_slash"
        if not legs.check("the_origin_rules_for_the_complainant", not why and sent, {"refused": why}):
            return
        sid = str(comp.get("settlement_id") or "")
        own, _w = await _call(rig, _A, "getFederationDisputeSettlement", {"settlement_id": sid})
        named = str(settlement_of(own).get("origin_registry_url") or "")
        if named and not _dialable_from_outside(named):
            raise PreconditionUnmet(f"{_A} named itself {named} as the settlement's origin, an address no peer holds, "
                                    f"so the home's half of the path cannot run here")

        async def _pending():
            got, _w2 = await _call(rig, _B, "getFederationDisputeSettlements", {"status_filter": _PENDING, "limit": 100})
            return ours(_settlements(got), defendant["did"], dispute_id) or None
        mine = await _until(_pending, _SETTLE_SEC) or []
        row = mine[0] if len(mine) == 1 else {}
        if not legs.check("the_home_holds_it_for_an_administrator",
                          len(mine) == 1 and row.get("status") == _PENDING and str(row.get("id")) == sid
                          and _num(row.get("requested_amount")) == float(amount), {"rows": mine}):
            return

        ok_a, why = await _call(rig, _B, "approveDisputeSettlement", {"settlement_id": sid})
        ans = ok_a if isinstance(ok_a, dict) else {}
        legs.check("approveDisputeSettlement_slashes_it_in_full",
                   not why and ans.get("status") == "SLASHED" and ans.get("slash_type") == "full"
                   and _num(ans.get("slashed_amount")) == float(amount) and ans.get("origin_notified") is True,
                   {"refused": why, "answer": {k: ans.get(k) for k in ("status", "slash_type", "slashed_amount",
                                                                      "origin_notified")}})
        d1 = await _balance(rig, _B, defendant["jwt"])
        legs.check("the_defendant_lost_the_amount", d0 is not None and d1 is not None and
                   abs((d0 - d1) - float(amount)) < 1e-6, {"before": d0, "after": d1, "amount": amount})

        async def _settled():
            got, _w3 = await _call(rig, _A, "getFederationDisputeSettlement", {"settlement_id": sid})
            st = settlement_of(got).get("status")
            return st if st in ("SETTLED", "FAILED") else None
        st = await _until(_settled, _SETTLE_SEC)
        legs.check("the_origin_settles", st == "SETTLED", {"origin_status": st})
        c1 = await _until(lambda: _held(rig, _A, complainant["jwt"], (c0 or 0) + amount), _SETTLE_SEC)
        legs.check("the_complainant_was_paid_the_amount", c0 is not None and c1 is not None,
                   {"before": c0, "after": c1, "amount": amount})

    return await _run(rig, planned, "a cross-frame settlement: the home approves and slashes, the origin pays", body)


async def _held(rig, label: str, jwt: str, at_least: float):
    """The agent's balance once it reaches `at_least` (a move lands a moment after its answer); None until then."""
    b = await _balance(rig, label, jwt)
    return b if b is not None and b + 1e-6 >= at_least else None
