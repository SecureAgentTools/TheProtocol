"""§MCPTEST30 (V0650, tester batch 1 item 4, agentvault2-d3, Guild order gwo_2015b757c94ce69138500df6): the federation
suite bonds its fixtures on a tier that enforces the bond WITHOUT the treasury backstop.

Production runs that posture from V0649 on (REPUTATION_BOND_TREASURY_BACKSTOP=false); until this change rig.ensure_bonded
raised PreconditionUnmet there, so the suite could not measure a frame posed as production is, and sbx-beta had to keep
the backstop on. Now the fixture is funded with its bond from the treasury (fund-agent, admin_grant) and bonds itself
(the developer's deposit rail, funder_did = the agent). RED on V0649's code: the backstop-off tier raises.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

import pytest

from agentvault_registry.api_tests.federation_suite import rig as R


class _Rig:
    def __init__(self, cfg: Dict[str, Any], *, fund_ok: bool = True, deposit_status: str = "locked"):
        self.cfg, self.fund_ok, self.deposit_status = cfg, fund_ok, deposit_status
        self.calls: List[Tuple[str, str, Dict[str, Any]]] = []

    def mcp(self, label: str):
        outer = self

        class _C:
            async def call(self, tool: str, arguments: Dict[str, Any] = None, **_k):
                a = arguments or {}
                outer.calls.append((label, a.get("method", ""), dict(a)))
                ep = a.get("endpoint", "")
                if ep == "/api/v1/reputation-bond/config":
                    return {"status_code": 200, "ok": True, "response": outer.cfg}
                if ep == "/api/v1/teg/treasury/fund-agent":
                    if not outer.fund_ok:
                        return {"status_code": 403, "ok": False, "response": {"detail": "refused"}}
                    return {"status_code": 200, "ok": True, "response": {"status": "completed"}}
                if ep.endswith("/reputation-bond"):
                    return {"status_code": 200, "ok": True, "response": {"status": outer.deposit_status, "bond_id": 7}}
                if ep.endswith("/reputation-bond/backstop"):
                    return {"status_code": 200, "ok": True, "response": {"status": "locked"}}
                raise AssertionError(f"unexpected call {ep}")
        return _C()


@pytest.fixture(autouse=True)
def _fresh_config_cache():
    R._BOND_CONFIG.clear()
    yield
    R._BOND_CONFIG.clear()


def _bond(rig: _Rig, did: str = "did:theprotocol:sandbox-b:fixture-1") -> Any:
    return asyncio.run(R.ensure_bonded(rig, "sandbox-B", did))


def test_without_the_backstop_the_fixture_is_funded_then_bonds_itself():
    rig = _Rig({"mode": "enforce", "amount": "250", "treasury_backstop": False})
    assert _bond(rig) == "locked"
    eps = [c[2]["endpoint"] for c in rig.calls]
    assert eps == ["/api/v1/reputation-bond/config", "/api/v1/teg/treasury/fund-agent",
                   "/api/v1/developers/me/agents/did:theprotocol:sandbox-b:fixture-1/reputation-bond"]
    fund = rig.calls[1][2]["body"]
    assert fund["target_agent_did"].endswith("fixture-1") and fund["reason"] == "admin_grant"
    assert fund["amount"] == "252.500000", "the bond plus a 1 % margin"
    assert rig.calls[2][2]["body"] == {"funder_did": "did:theprotocol:sandbox-b:fixture-1"}, "the agent funds itself"
    assert all(c[0] == "sandbox-B-admin" for c in rig.calls)


def test_with_the_backstop_nothing_is_funded():
    rig = _Rig({"mode": "enforce", "amount": "250", "treasury_backstop": True})
    assert _bond(rig) == "locked"
    assert [c[2]["endpoint"] for c in rig.calls][-1].endswith("/reputation-bond/backstop")
    assert not any(c[2]["endpoint"] == "/api/v1/teg/treasury/fund-agent" for c in rig.calls)


def test_a_refused_funding_or_an_unbonded_deposit_is_a_precondition_never_a_pass():
    with pytest.raises(R.PreconditionUnmet, match="was refused"):
        _bond(_Rig({"mode": "enforce", "amount": "250", "treasury_backstop": False}, fund_ok=False))
    R._BOND_CONFIG.clear()
    with pytest.raises(R.PreconditionUnmet, match="status='pending'"):
        _bond(_Rig({"mode": "enforce", "amount": "250", "treasury_backstop": False}, deposit_status="pending"))
    R._BOND_CONFIG.clear()
    with pytest.raises(R.PreconditionUnmet, match="names no amount"):
        _bond(_Rig({"mode": "enforce", "amount": None, "treasury_backstop": False}))


def test_a_tier_that_does_not_enforce_moves_nothing():
    rig = _Rig({"mode": "shadow", "amount": "250", "treasury_backstop": False})
    assert _bond(rig) == "skipped:mode=shadow"
    assert len(rig.calls) == 1
