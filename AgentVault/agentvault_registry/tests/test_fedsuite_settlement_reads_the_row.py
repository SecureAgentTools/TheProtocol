"""V0649 (agentvault2-13, 2026-10-30): the cross-frame settlement flow reads the settlement inside the route's answer.

routers/federation_disputes.get_settlement answers {"settlement": {...}}. The flow (api_tests/federation_suite/tests/
test_cross_registry_settlement_reject.py, V0639) unwrapped it once, for the origin's own read, and read id and status at
the top level everywhere else, so three of its nine legs saw None: EU's nightly federation suite was red on this one row
every night since 2026-10-26 while both frames did the right thing (sbx-beta held each request, its administrator
rejected it, nothing moved, and sbx-alpha recorded FAILED: "Slash request rejected by receiving registry admin"). The
fresh nightly pair never ran it (its origin names an internal address: precondition unmet), so only the standing sandbox
showed it. The body is driven here with the route's real shape; on V0647's flow the same drive fails those three legs.
"""
from __future__ import annotations

import asyncio
from typing import Dict

from agentvault_registry.api_tests.federation_suite.tests import test_cross_registry_settlement_reject as flow

SID = "c79178a9-a752-4c86-ad0a-db8cdebce4b9"


def test_settlement_of_unwraps_the_routes_answer():
    row = {"id": SID, "status": "REJECTED"}
    assert flow.settlement_of({"settlement": row}) == row
    assert flow.settlement_of(row) == row                       # a bare row stays as it is
    assert flow.settlement_of(None) == {} and flow.settlement_of("x") == {} and flow.settlement_of([row]) == {}
    assert flow.settlement_of({"settlement": None, "status": "X"}) == {"settlement": None, "status": "X"}


class _Legs:
    def __init__(self):
        self.seen: Dict[str, bool] = {}

    def check(self, name, ok, evidence=None):
        self.seen[name] = bool(ok)
        return bool(ok)


def _drive(monkeypatch) -> Dict[str, bool]:
    """The flow's body against two frames that behave as sbx-alpha and sbx-beta did every night: the home parks the
    request, its administrator rejects it, nothing moves, and the origin hears FAILED. Every read of a single
    settlement answers the route's real shape, {"settlement": {...}}."""
    state = {"home": "PENDING_ADMIN_APPROVAL", "origin": "PENDING_SLASH"}
    amount = 1

    def row(where):
        return {"id": SID, "status": state[where], "requested_amount": f"{amount}.000000", "slashed_amount": "0.000000",
                "defendant_did": "did:theprotocol:d", "dispute_id": 276,
                "origin_registry_url": "https://sandbox-a.theprotocol.cloud"}

    async def call(rig, label, tool, args):
        a = label.startswith(flow._A)
        if tool == "getPeerSlashConfig":
            return {"peers": [{"name": "sbx-alpha", "auto_slash_enabled": False, "auto_slash_max_avt": 0}]}, None
        if tool == "createAgent":
            tag = "complainant" if a else "defendant"
            return {"did": f"did:theprotocol:{tag[0]}", "client_id": "c", "client_secret": "s"}, None
        if tool == "getAgentToken":
            return {"access_token": "jwt"}, None
        if tool == "submitDispute":
            return {"id": 276}, None
        if tool == "submitDisputeEvidence":
            return {"ok": True}, None
        if tool == "updateDisputeRuling":
            return {"compensation": {"settlement_status": "pending_remote_slash", "settlement_id": SID}}, None
        if tool == "getFederationDisputeSettlements":
            return {"settlements": [row("home")]}, None
        if tool == "getFederationDisputeSettlement":
            return {"settlement": row("origin" if a else "home")}, None
        if tool == "rejectDisputeSettlement":
            state["home"], state["origin"] = "REJECTED", "FAILED"
            return {"settlement_id": SID, "status": "REJECTED", "origin_notified": True}, None
        raise AssertionError(f"unexpected call {label} {tool}")

    async def balance(rig, label, jwt):
        return 0.0

    async def until(fn, sec):
        return await fn()

    legs = _Legs()

    async def run(rig, planned, title, body):
        await body(legs, [], None)
        return legs

    monkeypatch.setattr(flow, "_call", call)
    monkeypatch.setattr(flow, "_balance", balance)
    monkeypatch.setattr(flow, "_until", until)
    monkeypatch.setattr(flow, "_run", run)
    monkeypatch.setattr(flow.throwaways, "made", lambda label, did: None)
    asyncio.run(flow.test_xframe_settlement_reject(None))   # @federation_test registers and returns the coroutine itself
    return legs.seen


def test_every_leg_passes_on_the_routes_real_shape(monkeypatch):
    seen = _drive(monkeypatch)
    assert seen == {
        "the_amount_is_over_every_threshold_the_home_holds": True, "the_origin_takes_the_dispute": True,
        "the_evidence_names_the_amount": True, "the_origin_rules_for_the_complainant": True,
        "the_home_holds_it_for_an_administrator": True, "getFederationDisputeSettlement_reads_it": True,
        "rejectDisputeSettlement_rejects_it": True, "nothing_moved_on_the_home": True, "the_origin_hears_failed": True,
    }
