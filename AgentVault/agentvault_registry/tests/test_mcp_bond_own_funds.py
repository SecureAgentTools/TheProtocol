"""§MCPTEST30 (V0652, agentvault2-d3, 2026-11-01): an agent of the runner's that cannot have a backstop bond bonds from its
own funds on a pair (tester batch 3's follow-up, Guild order gwo_5b6bc38b2e17c317754d6e29).

V0651's pair proof (nt261101x1) ran production's posture, the treasury backstop off, so earned_agent_public._backstop met
"This registry does not backstop bonds from its treasury" and 14 contract and Guild rows went NOT MEASURED. RED before:
_backstop answers that refusal and nothing is funded or bonded.
"""
from __future__ import annotations

import asyncio
from typing import Any, List, Optional, Tuple

import pytest

from agentvault_registry.api_tests.contracts import earned_agent_public as EP

DID = "did:theprotocol:nt261101x1a.theprotocol.cloud:provider-1"
OFF = {"error": {"detail": "This registry does not backstop bonds from its treasury"}}


class _Registry:
    def __init__(self, *, backstop_on: bool = False, amount: Any = "250", fund_status: int = 200,
                 deposit_status: str = "locked", other_refusal: bool = False):
        self.backstop_on, self.amount, self.fund_status = backstop_on, amount, fund_status
        self.deposit_status, self.other_refusal = deposit_status, other_refusal
        self.calls: List[Tuple[str, str, Any]] = []

    async def rest(self, bag: Any, parse: Any, method: str, endpoint: str, body: Any = None, **_kw: Any):
        self.calls.append((method, endpoint, body))
        if endpoint.endswith("/reputation-bond/backstop"):
            if self.backstop_on:
                return 200, {"status": "locked"}
            if self.other_refusal:
                return 403, {"error": {"detail": "only the agent's owner may bond it"}}
            return 403, OFF
        if endpoint == "/api/v1/reputation-bond/config":
            return 200, {"amount": self.amount, "mode": "enforce", "treasury_backstop": False}
        if endpoint == "/api/v1/teg/treasury/fund-agent":
            return self.fund_status, ({"ok": True} if self.fund_status < 300 else {"error": {"detail": "no"}})
        if endpoint == f"/api/v1/developers/me/agents/{DID}/reputation-bond":
            return 200, {"status": self.deposit_status}
        raise AssertionError(endpoint)


def _bond(reg: _Registry, monkeypatch, *, ephemeral: bool) -> Optional[str]:
    monkeypatch.setattr(EP, "_rest", reg.rest)
    if ephemeral:
        monkeypatch.setenv("MCP_TESTER_EPHEMERAL_TARGET", "true")
    else:
        monkeypatch.delenv("MCP_TESTER_EPHEMERAL_TARGET", raising=False)
    return asyncio.run(EP._backstop(object(), lambda b: b, DID))


def test_a_backstop_bond_is_taken_as_before(monkeypatch):
    reg = _Registry(backstop_on=True)
    assert _bond(reg, monkeypatch, ephemeral=True) is None
    assert [c[1] for c in reg.calls] == [f"/api/v1/developers/me/agents/{DID}/reputation-bond/backstop"]


def test_on_a_pair_without_the_backstop_the_agent_bonds_from_its_own_funds(monkeypatch):
    reg = _Registry()
    assert _bond(reg, monkeypatch, ephemeral=True) is None
    fund = next(c for c in reg.calls if c[1] == "/api/v1/teg/treasury/fund-agent")
    assert fund[0] == "POST" and fund[2]["target_agent_did"] == DID and fund[2]["reason"] == "admin_grant"
    assert fund[2]["amount"] == "252.500000", "the bond and 1 % for a fee"
    dep = reg.calls[-1]
    assert dep == ("POST", f"/api/v1/developers/me/agents/{DID}/reputation-bond", {"funder_did": DID})


def test_on_a_standing_frame_the_refusal_stands_and_nothing_moves(monkeypatch):
    reg = _Registry()
    why = _bond(reg, monkeypatch, ephemeral=False)
    assert why and "does not backstop bonds" in why and "torn down after its run" in why
    assert all(c[1].endswith("/backstop") for c in reg.calls), "no funding and no deposit on a standing frame"


def test_another_refusal_is_not_read_as_the_backstop_being_off(monkeypatch):
    reg = _Registry(other_refusal=True)
    why = _bond(reg, monkeypatch, ephemeral=True)
    assert why and "only the agent's owner" in why and len(reg.calls) == 1


@pytest.mark.parametrize("kw,needle", [
    ({"amount": None}, "names no amount"),
    ({"amount": "0"}, "names no amount"),
    ({"fund_status": 403}, "funding the provider's bond from the treasury answered HTTP 403"),
    ({"deposit_status": "pending"}, "bond from its own funds answered HTTP 200"),
])
def test_each_failed_leg_is_said(monkeypatch, kw, needle):
    why = _bond(_Registry(**kw), monkeypatch, ephemeral=True)
    assert why and needle in why, why


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
