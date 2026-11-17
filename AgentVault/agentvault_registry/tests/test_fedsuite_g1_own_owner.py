"""V0662 Wave 1 (gwo_757f07e0ab8193d64b4ed1cf, session-tester; the delivery soak's finding, seq 3091-3095): each chat
flow that reads an owner's webhook record owns its agents and hooks through a developer of its own, per frame.

The soak (scratchpad/soak1113/SOAK_RESULT.md, 200 runs on nt261113x1): the dispatcher sends an event to every active
hook of the agent's OWNER, every g1 flow and the latency flow made their agents as the frame's admin, and every hook
points at an `.invalid` host, so the flows running together filled each other's hooks with failures: 698 of 1,400 suite
hooks auto-disabled (10 failures in a row), in every run, and the block test's own hooks disabled before it ended 243
times. Whether a control was heard was a race against its hook's tenth failure. Owner-wide dispatch is the product's
behaviour (session-lead seq 3095), so the suite changes: a flow registers a throwaway developer on each frame, makes its
agents and hooks as that developer, and retires all of it at the end (agents, hooks, then the developer's own deletion
request). The registration carries no Terms acceptance (session-lead seq 3281: nobody writes a legal acceptance for an
account no person agreed for). The first four tests fail on f569f6a6e's modules (the control).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

import pytest

from agentvault_registry.api_tests.federation_suite import rig as R
from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.tests import test_chat_g1_federation as G1
from agentvault_registry.api_tests.federation_suite.tests import test_chat_latency_federation as LAT


class _Client:
    def __init__(self, label: str, rig: "_Rig"):
        self.label, self.rig = label, rig

    async def call(self, tool: str, args: Dict[str, Any], timeout: int = 60):
        tool = tool.replace("theprotocol_", "")
        self.rig.calls.append((self.label, tool, dict(args or {})))
        self.rig.n += 1
        n = self.rig.n
        if tool == "adminRequest":
            if args.get("endpoint") == "/api/v1/auth/register":
                return self.rig.register_answer
            return {"status_code": 200, "response": {}}
        return {
            "createAgent": {"did": f"did:theprotocol:{n:08d}", "client_id": f"c{n}", "client_secret": f"s{n}"},
            "getAgentToken": {"access_token": f"jwt{n}"},
            "createWebhook": {"id": f"hook{n}"},
            "getBatchAgentBalances": {"balances": {}},
            "getMyDeveloperProfile": {"id": n, "email": "x"},
            "requestAccountDeletion": {"status": "scheduled"},
        }.get(tool, {"ok": True})


class _Rig(R.FederationTestRig):
    """The real rig's principal book-keeping, with MCP clients that answer from a script and record every call."""

    def __init__(self):
        super().__init__()
        self.calls: List[Tuple[str, str, Dict[str, Any]]] = []
        self.n = 0
        self.register_answer: Any = {"status_code": 201, "response": {"message": "registered"}}

    def mcp(self, label: str) -> _Client:
        known = label in R.SANDBOX_REGISTRIES or label in getattr(self, "_principals", {})
        assert known, f"unknown label {label!r}"
        return _Client(label, self)


async def _frames(_rig):
    return {G1._A: "https://a.example", G1._B: "https://b.example"}


async def _no_knock(*_a, **_k):
    return None        # the flow ends right after its fixtures: what this file judges is who made them


def _patch(monkeypatch):
    monkeypatch.setattr(G1, "_frames", _frames)
    monkeypatch.setattr(G1, "_knock_and_find", _no_knock)
    monkeypatch.setattr(LAT, "_frames", _frames)

    async def _send(rig, label, speaker, body, **target):    # the latency flow's knock: refused, so it ends early
        rig.calls.append((label, "sendChatMessage", {"body": body}))
        return None, "refused in this test"
    monkeypatch.setattr(LAT, "_send", _send)


FLOWS = [G1.test_g1_round_trip, G1.test_g1_blocks, G1.test_g1_household, LAT.test_chat_latency]


def _base(label: str) -> str:
    return label.split("~", 1)[0]


def _run_flow(flow, rig):
    return asyncio.run(flow(rig))


@pytest.mark.parametrize("flow", FLOWS, ids=lambda f: f.__name__)
def test_a_flow_makes_its_agents_and_hooks_as_its_own_developer(monkeypatch, flow):
    _patch(monkeypatch)
    rig = _Rig()
    _run_flow(flow, rig)
    makers = [(label, tool) for label, tool, _ in rig.calls if tool in ("createAgent", "createWebhook")]
    assert makers, "the flow made fixtures"
    for label, tool in makers:
        assert "~" in label and _base(label) in (G1._A, G1._B), \
            f"{tool} as {label}: a frame's admin owns it, so every other flow's events fill its hooks"
    owners = {label for label, _ in makers}
    assert {_base(o) for o in owners} <= {G1._A, G1._B}
    assert len({o for o in owners if _base(o) == G1._A}) <= 1 and len({o for o in owners if _base(o) == G1._B}) <= 1, \
        "one developer per frame per flow"


def test_two_flows_never_share_an_owner(monkeypatch):
    _patch(monkeypatch)
    rig = _Rig()
    seen: List[set] = []
    for flow in FLOWS:
        before = len(rig.calls)
        _run_flow(flow, rig)
        seen.append({label for label, tool, _ in rig.calls[before:] if tool in ("createAgent", "createWebhook")})
    for i in range(len(seen)):
        for j in range(i + 1, len(seen)):
            assert not (seen[i] & seen[j]), f"{FLOWS[i].__name__} and {FLOWS[j].__name__} share {seen[i] & seen[j]}"


def test_the_registration_accepts_no_terms_for_anyone(monkeypatch):
    _patch(monkeypatch)
    rig = _Rig()
    _run_flow(G1.test_g1_round_trip, rig)
    regs = [a for label, tool, a in rig.calls if tool == "adminRequest" and a.get("endpoint") == "/api/v1/auth/register"]
    assert len(regs) == 2, "one developer on each frame"
    for a in regs:
        body = a.get("body") or {}
        assert not body.get("tos_accepted") and not body.get("age_confirmed"), \
            "seq 3281: nobody writes a legal acceptance for an account no person agreed for"
        assert body.get("email", "").endswith(".dev") and body.get("password")


def test_the_flow_retires_its_agents_hooks_and_then_its_developers(monkeypatch):
    _patch(monkeypatch)
    rig = _Rig()
    out = _run_flow(G1.test_g1_blocks, rig)
    owners = sorted({label for label, tool, _ in rig.calls if tool == "createAgent"})
    assert len(owners) == 2
    for o in owners:
        mine = [(i, tool) for i, (label, tool, _) in enumerate(rig.calls) if label == o]
        tools = [t for _, t in mine]
        assert "deleteWebhook" in tools and "deleteMyAgentByDev" in tools, f"{o} removes its own hooks and agents"
        last_delete = max(i for i, t in mine if t in ("deleteWebhook", "deleteMyAgentByDev"))
        asked = [i for i, t in mine if t == "requestAccountDeletion"]
        assert asked and asked[0] > last_delete, f"{o} asks for its own deletion after its fixtures are gone"
        args = next(a for label, t, a in rig.calls if label == o and t == "requestAccountDeletion")
        assert args.get("confirmation") == "DELETE MY ACCOUNT" and args.get("password")
    assert out.last_state["legs"].get("the_flow_removed_what_it_made") is True


def test_a_registration_that_asks_for_the_terms_is_not_measured_never_accepted(monkeypatch):
    _patch(monkeypatch)
    rig = _Rig()
    rig.register_answer = {"status_code": 422, "response": {
        "detail": "You must accept the Terms of Service and Privacy Policy to register."}}
    with pytest.raises(R.PreconditionUnmet) as e:
        _run_flow(G1.test_g1_round_trip, rig)
    assert "Terms" in str(e.value)
    assert not [1 for _, tool, _ in rig.calls if tool in ("createAgent", "createWebhook")]
    regs = [a for _, tool, a in rig.calls if tool == "adminRequest" and a.get("endpoint") == "/api/v1/auth/register"]
    assert len(regs) == 1 and not (regs[0].get("body") or {}).get("tos_accepted"), "asked once, never with an acceptance"


def test_a_principal_is_spoken_as_on_its_registrys_public_path():
    rig = R.FederationTestRig()
    label = rig.add_principal(G1._A, "t1", "p@x.dev", "pw")
    c = rig.mcp(label)
    base = R.SANDBOX_REGISTRIES[G1._A]
    assert c.spec.container == base.container and c.spec.rpc_path == base.rpc_path
    assert c.spec.admin_email == "p@x.dev" and c.spec.admin_password == "pw"
    assert rig.base_of(label) == G1._A and rig.base_of(G1._B) == G1._B
    with pytest.raises(KeyError):
        rig.add_principal(G1._ADMIN[G1._A], "t2", "q@x.dev", "pw")   # never on the admin path
    with pytest.raises(KeyError):
        rig.add_principal(G1._A, "t1", "r@x.dev", "pw")               # one label, one developer


def test_a_principals_balance_goes_back_through_its_registrys_admin():
    rig = _Rig()
    label = rig.add_principal(G1._B, "t3", "p@x.dev", "pw")
    did = "did:theprotocol:00000001"

    async def go():
        rig_calls_before = len(rig.calls)

        async def call(tool, args, timeout=60):
            rig.calls.append((label, tool, dict(args)))
            return {"balances": {did: {"balance": "1000"}}}
        orig = rig.mcp

        def mcp(lbl):
            c = orig(lbl)
            if lbl == label:
                c.call = call
            return c
        rig.mcp = mcp
        await throwaways.return_balance(rig, did, label)
        return rig.calls[rig_calls_before:]
    calls = asyncio.run(go())
    assert (G1._ADMIN[G1._B], "tegTreasuryReceive") in [(lbl, t) for lbl, t, _ in calls]

