"""V0660 (k), Guild order gwo_9230be3d156cc3ce58699aaf: the federation suite's cross-frame settlement tests are NOT
MEASURED where the ruling frame does not deliver the slash request.

Since V0660 (k) a frame with CROSS_REGISTRY_SETTLEMENT_DELIVERY off (or with no address a peer can dial) sends no slash
request at all: the ruling's compensation answers settlement_status "not_delivered" with the reason. The reject and
approve flows read "pending_remote_slash" there and would fail the ruling leg; the home's half of the path cannot run on
such a frame, which is the environment, not the path, so each says so (PreconditionUnmet naming the flag) and clears its
throwaways, under the skip code the undialable origin already has (settlement_origin_internal, ceiling two). A frame
that does deliver goes on to the home as before. RED on 4b79322d7: both flows fail the ruling leg instead.
"""
from __future__ import annotations

import asyncio
from typing import Dict

import pytest

from agentvault_registry.api_tests.federation_suite import skip_codes
from agentvault_registry.api_tests.federation_suite.rig import PreconditionUnmet
from agentvault_registry.api_tests.federation_suite.tests import test_cross_registry_settlement_approve as approve
from agentvault_registry.api_tests.federation_suite.tests import test_cross_registry_settlement_reject as reject

SID = "24ca7222-0000-4000-8000-000000000000"
OFF = {"settlement_status": "not_delivered", "settlement_id": SID, "cross_registry": True,
       "reason": "Cross-registry: no slash request was sent, because CROSS_REGISTRY_SETTLEMENT_DELIVERY is off on this "
                 "registry. Nothing moved, and the complainant is not paid through this settlement."}
SENT = {"settlement_status": "pending_remote_slash", "settlement_id": SID}


class _Legs:
    def __init__(self):
        self.seen: Dict[str, bool] = {}

    def check(self, name, ok, evidence=None):
        self.seen[name] = bool(ok)
        return bool(ok)


def _drive(monkeypatch, flow, compensation):
    calls = []
    legs = _Legs()

    async def call(rig, label, tool, args):
        calls.append((label, tool))
        a = label.startswith(reject._A)
        if tool == "getPeerSlashConfig":
            return {"peers": [{"name": "sbx-alpha", "auto_slash_enabled": True, "auto_slash_max_avt": 5}]}, None
        if tool == "createAgent":
            return {"did": f"did:theprotocol:{'c' if a else 'd'}", "client_id": "c", "client_secret": "s"}, None
        if tool == "getAgentToken":
            return {"access_token": "jwt-c" if a else "jwt-d"}, None
        if tool == "adminRequest":
            return {"status_code": 200, "ok": True}, None
        if tool == "submitDispute":
            return {"id": 276}, None
        if tool == "submitDisputeEvidence":
            return {"ok": True}, None
        if tool == "updateDisputeRuling":
            return {"compensation": dict(compensation)}, None
        if tool == "getFederationDisputeSettlement":
            return {"settlement": {"id": SID, "status": "PENDING_SLASH",
                                   "origin_registry_url": "https://sandbox-a.theprotocol.cloud:8443"}}, None
        if tool == "getFederationDisputeSettlements":
            return {"settlements": []}, None
        return {"ok": True}, None

    async def balance(rig, label, jwt):
        return 6.0

    async def until(fn, sec):
        return await fn()

    async def mirrored(rig, label, did):
        return True

    async def run(rig, planned, title, body):
        await body(legs, [], None)
        return legs

    for mod in (approve, reject):
        monkeypatch.setattr(mod, "_call", call)
        monkeypatch.setattr(mod, "_balance", balance, raising=False)
        monkeypatch.setattr(mod, "_until", until)
        monkeypatch.setattr(mod, "_run", run)
        monkeypatch.setattr(mod, "mirrored_on", mirrored, raising=False)
    monkeypatch.setattr(reject.throwaways, "made", lambda label, did: None)
    monkeypatch.setenv(approve.EPHEMERAL_ENV, "true")
    test = getattr(flow, "__wrapped__", flow)
    out = asyncio.run(test(None))
    return out, legs, calls


@pytest.mark.parametrize("flow", [reject.test_xframe_settlement_reject, approve.test_xframe_settlement_approve])
def test_a_frame_that_does_not_deliver_is_not_measured_naming_the_flag(monkeypatch, flow):
    with pytest.raises(PreconditionUnmet) as e:
        _drive(monkeypatch, flow, OFF)
    said = str(e.value)
    assert "did not deliver the settlement's slash request" in said
    assert "CROSS_REGISTRY_SETTLEMENT_DELIVERY" in said
    # the skip code the undialable origin has: a fresh code would read as unclassified on the pairs
    assert skip_codes.classify_skip("precondition unmet: " + said) == "settlement_origin_internal"


@pytest.mark.parametrize("flow", [reject.test_xframe_settlement_reject, approve.test_xframe_settlement_approve])
def test_the_ruling_leg_is_never_failed_for_it(monkeypatch, flow):
    legs = None
    try:
        _out, legs, _calls = _drive(monkeypatch, flow, OFF)
    except PreconditionUnmet:
        return
    assert legs is not None and legs.seen.get("the_origin_rules_for_the_complainant") is not False


def test_a_frame_that_delivers_goes_on_to_the_home(monkeypatch):
    _out, legs, calls = _drive(monkeypatch, reject.test_xframe_settlement_reject, SENT)
    assert legs.seen["the_origin_rules_for_the_complainant"] is True
    assert ("sandbox-B", "getFederationDisputeSettlements") in calls


def test_still_two_rows_at_most():
    assert skip_codes.BASELINE_SKIPS["settlement_origin_internal"] == 2
