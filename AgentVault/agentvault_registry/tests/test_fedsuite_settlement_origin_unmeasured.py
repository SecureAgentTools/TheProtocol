"""§MCPTEST30 V0639 (agentvault2-aa, 2026-10-24): the federation suite's settlement flow is NOT MEASURED where the origin
names an address no peer holds.

The defendant's home takes a slash request only when its callback lies under an ACTIVE peer's base_url; an origin that
names its internal federation proxy (CROSS_REGISTRY_SETTLEMENT_DELIVERY off, the default; core/settlement_origin) is
refused by every peer, as dispute 50 on sbx-beta was at 17:36Z. On such a pair the home's half of the path cannot run:
the flow says so after the ruling, and clears its throwaways, rather than reading the environment as a red. A dialable
origin goes on to the home as before. The first test fails on 24df2e05's flow, which waited out its budget (the control).
"""
from __future__ import annotations

import asyncio
import itertools
from typing import Any, Dict, List, Tuple

import pytest

from agentvault_registry.api_tests.federation_suite.rig import PreconditionUnmet
from agentvault_registry.api_tests.federation_suite.tests import test_cross_registry_settlement_reject as flow

_ids = itertools.count(1)


class _Client:
    def __init__(self, label: str, rig: "_Rig"):
        self.label, self.rig = label, rig

    async def call(self, tool: str, args: Dict[str, Any], timeout: int = 60):
        self.rig.calls.append((self.label, tool))
        if tool == "createAgent":
            return {"client_id": "c", "client_secret": "s", "did": f"did:theprotocol:test:{next(_ids)}"}
        if tool == "getAgentToken":
            return {"access_token": "agent-jwt"}
        if tool == "getMyBalance":
            return {"balance": "0"}
        if tool == "getPeerSlashConfig":
            return {"peers": [{"name": "Sandbox Alpha", "auto_slash_enabled": True, "auto_slash_max_avt": 0}]}
        if tool == "submitDispute":
            return {"id": 50}
        if tool == "updateDisputeRuling":
            return {"compensation": {"settlement_status": "pending_remote_slash", "settlement_id": "bcc7ae9e"}}
        if tool == "getFederationDisputeSettlement":
            return {"settlement": {"id": "bcc7ae9e", "status": "PENDING_SLASH", "origin_registry_url": self.rig.origin}}
        if tool == "getFederationDisputeSettlements":
            return {"settlements": []}
        return {"ok": True}


class _Rig:
    def __init__(self, origin: str):
        self.origin, self.calls = origin, []

    def mcp(self, label: str) -> _Client:
        return _Client(label, self)


async def _once(fn, budget, every=0.0):
    return await fn()


def _run(monkeypatch, origin: str):
    monkeypatch.setattr(flow, "_until", _once)
    rig = _Rig(origin)
    test = getattr(flow.test_xframe_settlement_reject, "__wrapped__", flow.test_xframe_settlement_reject)
    return rig, asyncio.run(test(rig))


def test_an_origin_no_peer_holds_is_not_measured(monkeypatch):
    with pytest.raises(PreconditionUnmet) as e:
        _run(monkeypatch, "http://sbx-alpha-nginx-federation:8443")
    assert "an address no peer holds" in str(e.value) and "CROSS_REGISTRY_SETTLEMENT_DELIVERY" in str(e.value)


def test_the_throwaways_are_cleared_when_it_is_not_measured(monkeypatch):
    seen: List[Tuple[str, str]] = []
    real = _Client.call

    async def spy(self, tool, args, timeout=60):
        seen.append((self.label, tool))
        return await real(self, tool, args, timeout)
    monkeypatch.setattr(_Client, "call", spy)
    with pytest.raises(PreconditionUnmet):
        _run(monkeypatch, "http://sbx-alpha-nginx-federation:8443")
    assert ("sandbox-A", "deleteMyAgentByDev") in seen and ("sandbox-B", "deleteMyAgentByDev") in seen


def test_a_dialable_origin_goes_on_to_the_home(monkeypatch):
    rig, result = _run(monkeypatch, "https://sandbox-a.theprotocol.cloud:8443")
    assert ("sandbox-B", "getFederationDisputeSettlements") in rig.calls   # it went on to ask the home
