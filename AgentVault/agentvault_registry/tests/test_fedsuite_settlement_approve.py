"""§MCPTEST30 (tester batch 2 item 4, part 2, agentvault2-d3, Guild order gwo_e3bad842b1a5943022b01d40): the
cross-frame settlement's approve leg (federation_suite/tests/test_cross_registry_settlement_approve.py), on the pairs
only, against throwaway agents of the run's own.

The flow's body is driven against two scripted frames (as the rejection's own harness does): the home funds the run's
defendant, parks the request, its administrator approves, the defendant is slashed in full into the home's treasury and
the origin settles and pays the complainant. A standing frame skips it with the pair_only code. RED on the code before:
the flow and the code do not exist.
"""
from __future__ import annotations

import asyncio
from typing import Dict

import pytest

from agentvault_registry.api_tests.federation_suite import skip_codes
from agentvault_registry.api_tests.federation_suite.rig import PreconditionUnmet
from agentvault_registry.api_tests.federation_suite.tests import test_cross_registry_settlement_approve as flow
from agentvault_registry.api_tests.federation_suite.tests import test_cross_registry_settlement_reject as reject

SID = "5d1c2b0e-3f9a-4c8e-9b7d-2a6f1e0c4d33"


class _Legs:
    def __init__(self):
        self.seen: Dict[str, bool] = {}

    def check(self, name, ok, evidence=None):
        self.seen[name] = bool(ok)
        return bool(ok)


def _drive(monkeypatch, *, insufficient=False, unpaid=False, mirror_after=0, polls=1) -> Dict[str, bool]:
    """mirror_after: how many of the origin's reads go by before the defendant's mirror is there (-1: never); polls:
    how many times the patched _until asks before its budget is out (1: once, as before V0654)."""
    st = {"home": "PENDING_ADMIN_APPROVAL", "origin": "PENDING_SLASH"}
    bal = {"d": 0.0, "c": 3.0}
    amount = 6       # one over the home's highest threshold, 5
    reads = {"n": 0}
    filed = []

    def mirrored():
        return mirror_after >= 0 and reads["n"] > mirror_after

    def row(where):
        return {"id": SID, "status": st[where], "requested_amount": f"{amount}.000000", "defendant_did": "did:theprotocol:d",
                "dispute_id": 276, "origin_registry_url": "https://sandbox-a.theprotocol.cloud"}

    async def call(rig, label, tool, args):
        a = label.startswith(reject._A)
        if tool == "getPeerSlashConfig":
            return {"peers": [{"name": "sbx-alpha", "auto_slash_enabled": True, "auto_slash_max_avt": 5}]}, None
        if tool == "createAgent":
            tag = "c" if a else "d"
            return {"did": f"did:theprotocol:{tag}", "client_id": "c", "client_secret": "s"}, None
        if tool == "getAgentToken":
            return {"access_token": "jwt-c" if a else "jwt-d"}, None
        if tool == "adminRequest":
            assert label == reject._ADMIN[reject._B] and args["endpoint"] == "/api/v1/teg/treasury/fund-agent"
            assert args["body"]["target_agent_did"] == "did:theprotocol:d" and args["body"]["amount"] == str(amount)
            bal["d"] += amount
            return {"status_code": 200, "ok": True}, None
        if tool == "submitDispute":
            filed.append(mirrored())
            if not mirrored():
                # what V0653's recut pair nt261102x2 answered while the mirror was on its way (12:45:46Z)
                return None, "Dispute filing request timed out"
            return {"id": 276}, None
        if tool == "submitDisputeEvidence":
            return {"ok": True}, None
        if tool == "updateDisputeRuling":
            return {"compensation": {"settlement_status": "pending_remote_slash", "settlement_id": SID}}, None
        if tool == "getFederationDisputeSettlements":
            return {"settlements": [row("home")]}, None
        if tool == "getFederationDisputeSettlement":
            return {"settlement": row("origin" if a else "home")}, None
        if tool == "approveDisputeSettlement":
            assert label == reject._B
            if insufficient:
                st["home"], st["origin"] = "FAILED", "FAILED"
                return {"settlement_id": SID, "status": "FAILED", "slashed_amount": 0, "slash_type": "insufficient",
                        "origin_notified": True}, None
            st["home"], st["origin"] = "SLASHED", "SETTLED"
            bal["d"] -= amount
            if not unpaid:
                bal["c"] += amount
            return {"settlement_id": SID, "status": "SLASHED", "slashed_amount": float(amount), "slash_type": "full",
                    "origin_notified": True}, None
        raise AssertionError(f"unexpected call {label} {tool}")

    async def balance(rig, label, jwt):
        return bal["d"] if jwt == "jwt-d" else bal["c"]

    async def until(fn, sec):
        for _ in range(polls):
            last = await fn()
            if last:
                return last
        return last

    async def rest(rig, method, endpoint, label, body=None, jwt=None):
        assert (method, endpoint, label) == ("GET", "/api/v1/agent-cards/did:theprotocol:d", reject._ADMIN[reject._A])
        reads["n"] += 1
        if not mirrored():
            return 404, {"detail": "Agent Card not found"}
        return 200, {"agent_did": "did:theprotocol:d", "is_active": True}

    legs = _Legs()

    async def run(rig, planned, title, body):
        await body(legs, [], None)
        return legs

    for mod in (flow, reject):
        monkeypatch.setattr(mod, "_call", call)
    monkeypatch.setattr(reject, "_rest", rest, raising=False)   # raising=False: V0653's module has no _rest
    monkeypatch.setattr(flow, "_balance", balance)
    monkeypatch.setattr(flow, "_until", until)
    monkeypatch.setattr(flow, "_run", run)
    monkeypatch.setattr(reject.throwaways, "made", lambda label, did: None)
    monkeypatch.setenv(flow.EPHEMERAL_ENV, "true")
    asyncio.run(flow.test_xframe_settlement_approve(None))
    legs.seen["_filed_before_the_mirror"] = any(not m for m in filed)
    return legs.seen


def test_on_a_pair_the_home_slashes_and_the_origin_pays(monkeypatch):
    seen = _drive(monkeypatch)
    assert not seen.pop("_filed_before_the_mirror")
    assert seen and all(seen.values()), seen
    assert set(seen) == {"the_amount_is_over_every_threshold_the_home_holds", "the_home_funds_the_defendant_the_amount",
                         "the_origin_mirrors_the_defendant",
                         "the_origin_takes_the_dispute", "the_evidence_names_the_amount",
                         "the_origin_rules_for_the_complainant", "the_home_holds_it_for_an_administrator",
                         "approveDisputeSettlement_slashes_it_in_full", "the_defendant_lost_the_amount",
                         "the_origin_settles", "the_complainant_was_paid_the_amount"}


def test_a_late_mirror_is_waited_for_and_the_dispute_filed_once(monkeypatch):
    """V0654 (at), item 21 (Guild order gwo_a4be529fdaa3e5f38143606e): the origin knows the defendant only after a few
    reads (the mirror arrived about 21 s after the defendant on nt261102x2). The flow waits for the mirror, then files
    once, and every leg holds. RED on V0653's flow: it filed at once, took "Dispute filing request timed out" for the
    answer and stopped at the_origin_takes_the_dispute."""
    seen = _drive(monkeypatch, mirror_after=3, polls=10)
    assert not seen.pop("_filed_before_the_mirror"), "it filed before the origin held the defendant's mirror"
    assert seen and all(seen.values()), seen


def test_a_mirror_that_never_arrives_is_red_and_nothing_is_filed(monkeypatch):
    seen = _drive(monkeypatch, mirror_after=-1, polls=4)
    assert seen["the_origin_mirrors_the_defendant"] is False
    assert "the_origin_takes_the_dispute" not in seen and not seen.pop("_filed_before_the_mirror")


def test_a_slash_that_takes_nothing_is_red(monkeypatch):
    seen = _drive(monkeypatch, insufficient=True)
    assert not seen["approveDisputeSettlement_slashes_it_in_full"] and not seen["the_defendant_lost_the_amount"]
    assert not seen["the_origin_settles"]


def test_a_complainant_the_origin_never_paid_is_red(monkeypatch):
    seen = _drive(monkeypatch, unpaid=True)
    assert seen["the_origin_settles"] and not seen["the_complainant_was_paid_the_amount"]


def test_a_standing_frame_skips_it_named(monkeypatch):
    monkeypatch.delenv(flow.EPHEMERAL_ENV, raising=False)
    with pytest.raises(PreconditionUnmet) as e:
        asyncio.run(flow.test_xframe_settlement_approve(None))
    assert skip_codes.classify_skip(str(e.value)) == "pair_only"
    assert skip_codes.BASELINE_SKIPS["pair_only"] == 1


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
