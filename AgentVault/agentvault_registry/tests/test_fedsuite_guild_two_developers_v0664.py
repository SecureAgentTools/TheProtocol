"""V0664 (session-tester, session-lead seq 4287): the federation suite's Guild lifecycle runs between TWO developers.

The pair proof on nt261115x1 (V0664 cut-4) failed guild_lifecycle_bounty_moves_end_to_end: the flow made its poster and
its worker as the same rig principal (the frame's admin), and V0664's self-dealing gate refuses that ("this order would
pay or rate the poster's own developer ... a Guild order is for someone else's work"). The gate is right; the suite
modelled one person paying himself. The poster is now an agent of a developer the flow registers for itself
(api_tests/federation_suite/own_developer.py: no Terms acceptance, session-lead seq 3281), funded through the admin's
treasury rail; the worker stays the admin's agent (bonded as before: a bid is the provider's act). The flow's developer
sends its own deletion request at the end, also when the flow ends early. Red on 653824d1d: no own_developer module,
and both agents made as "sandbox-A".
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

from agentvault_registry.api_tests.federation_suite import rig as R
from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.tests import test_guild_lifecycle_economic as G


class _Client:
    def __init__(self, label: str, rig: "_Rig"):
        self.label, self.rig = label, rig

    async def call(self, tool: str, args: Dict[str, Any], timeout: int = 60):
        tool = tool.replace("theprotocol_", "")
        self.rig.calls.append((self.label, tool, dict(args or {})))
        self.rig.n += 1
        n = self.rig.n
        if tool == "adminRequest":
            if args.get("endpoint") == "/api/v1/public/registry-config":
                return {"status_code": 200, "response": {"environment": "sandbox"}}      # a stated sandbox (seq 4292)
            if args.get("endpoint") == "/api/v1/auth/register":
                return {"status_code": 201, "response": {"message": "registered"}}
            return {"status_code": 200, "response": {}}
        if tool == "adminQueryEventStore":
            return {"status_code": 200, "response": {"delta": 0.0}}
        if tool == "guildPostOrder":
            return {"_text": "Error: HTTP 403: refused in this test"}     # ends the flow early: cleanup must still run
        return {
            "createAgent": {"did": f"did:theprotocol:{n:08d}", "client_id": f"c{n}", "client_secret": f"s{n}"},
            "getAgentToken": {"access_token": f"jwt{n}"},
            "getMyBalance": {"balance": "50"},
            "getMyDeveloperProfile": {"id": n, "email": "x"},
            "requestAccountDeletion": {"status": "scheduled"},
        }.get(tool, {"ok": True})


class _Rig(R.FederationTestRig):
    def __init__(self):
        super().__init__()
        self.calls: List[Tuple[str, str, Dict[str, Any]]] = []
        self.n = 0

    def mcp(self, label: str) -> _Client:
        assert label in R.SANDBOX_REGISTRIES or label in getattr(self, "_principals", {}), f"unknown label {label!r}"
        return _Client(label, self)

    async def assert_within(self, **kw):
        return R.AssertionResult(passed=False, description=kw.get("description", ""), budget_sec=0.0, elapsed_sec=0.0,
                                 polling_attempts=1, last_state=kw["capture_state"]() if kw.get("capture_state") else {})


def _run(monkeypatch) -> _Rig:
    rig = _Rig()

    async def _bonded(_rig, label, did):
        _rig.calls.append((label, "ensure_bonded", {"did": did}))
        return "locked"

    async def _retire(_rig, label, did):
        _rig.calls.append((label, "retire", {"did": did}))

    monkeypatch.setattr(G, "ensure_bonded", _bonded)
    monkeypatch.setattr(throwaways, "retire", _retire)
    monkeypatch.setattr(throwaways, "made", lambda *_a, **_k: None)
    asyncio.run(G.test_guild_lifecycle.__wrapped__(rig) if hasattr(G.test_guild_lifecycle, "__wrapped__")
                else G.test_guild_lifecycle(rig))
    return rig


def _made(rig: _Rig) -> List[str]:
    return [label for label, tool, _ in rig.calls if tool == "createAgent"]


def test_the_poster_and_the_worker_belong_to_two_developers(monkeypatch):
    rig = _run(monkeypatch)
    makers = _made(rig)
    assert len(makers) == 2, makers
    poster_maker, worker_maker = makers
    assert poster_maker.startswith("sandbox-A~"), "the poster is an agent of the flow's own developer"
    assert worker_maker == "sandbox-A", "the worker stays the admin's agent"
    assert rig.base_of(poster_maker) == "sandbox-A"


def test_the_flow_registers_its_developer_with_no_terms_acceptance(monkeypatch):
    rig = _run(monkeypatch)
    reg = [a for label, tool, a in rig.calls if tool == "adminRequest" and a.get("endpoint") == "/api/v1/auth/register"]
    assert len(reg) == 1 and reg[0]["body"]["email"].endswith("@fedsuite-probe.dev")
    assert not any(k.startswith("tos") or "terms" in k for k in reg[0]["body"]), reg[0]["body"]


def test_only_the_worker_is_bonded_and_the_poster_is_funded_by_the_treasury(monkeypatch):
    rig = _run(monkeypatch)
    bonded = [(label, a.get("did")) for label, tool, a in rig.calls if tool == "ensure_bonded"]
    assert [label for label, _ in bonded] == ["sandbox-A"], "only the worker (the admin's agent) is bonded"
    worker_did = bonded[0][1]
    funds = [a["body"] for label, tool, a in rig.calls
             if tool == "adminRequest" and a.get("endpoint") == "/api/v1/teg/treasury/fund-agent"]
    assert len(funds) == 1 and funds[0]["target_agent_did"] != worker_did, "the treasury funds the poster"


def test_the_flows_developer_is_retired_even_when_the_flow_ends_early(monkeypatch):
    rig = _run(monkeypatch)
    dels = [label for label, tool, _ in rig.calls if tool == "requestAccountDeletion"]
    assert dels == [_made(rig)[0]], dels
    assert [a.get("confirmation") for label, tool, a in rig.calls if tool == "requestAccountDeletion"] == ["DELETE MY ACCOUNT"]
