"""§MCPTEST30 (V0650, tester batch 1 item 3, agentvault2-d3, Guild order gwo_2015b757c94ce69138500df6): after the
deposit, getMyReputationBondStatus names the bond the deposit made.

The external test's run 1 read `bond_id: null` from the bond status of a bonded agent (GET
/api/v1/agents/reputation-bond/status returned a literal None; fixed in V0649, 3cc665f53). lifecycle_earned_bond already
read the status after its deposit, for `status` only; it now holds bond_id to the deposit's. RED on V0649's code: a
status naming bond_id None passed.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

import pytest

from agentvault_registry.api_tests.contracts import earned_agent_public as P


def _drive(monkeypatch, status_bond_id: Optional[int]) -> Dict[str, dict]:
    async def rest(bag, parse, method, endpoint, body=None, **_k):
        assert endpoint == "/api/v1/reputation-bond/config"
        return 200, {"amount": "250"}
    monkeypatch.setattr(P, "_rest", rest)

    def body(obj: Any) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}],
                                                       "structuredContent": obj}}

    async def rpc(tool: str, args: dict, jwt: str = "", timeout: int = 15):
        if tool == "theprotocol_depositReputationBond":
            if float(args.get("amount") or 0) < 250:
                return False, body({"detail": "the bond must be at least 250"}), "400"
            return True, body({"bond_id": 7, "status": "locked"}), "200"
        if tool == "theprotocol_getMyReputationBondStatus":
            return True, body({"bond_id": status_bond_id, "status": "locked", "amount": "250"}), "200"
        raise AssertionError(tool)

    def parse(b: Dict[str, Any]) -> Any:
        try:
            return json.loads(b["result"]["content"][0]["text"])
        except Exception:                                              # noqa: BLE001
            return {}

    class Bag:
        developer_jwt, sentinel_jwt = "dev", "agent"
    out: Dict[str, dict] = {}
    asyncio.run(P.lifecycle_earned_bond(rpc, parse, Bag(), out))
    return out


def test_the_status_naming_the_deposits_bond_passes(monkeypatch):
    row = _drive(monkeypatch, 7)["theprotocol_depositReputationBond"]
    assert row["healthy"] and not row.get("fail_reason"), row


def test_a_status_that_names_no_bond_is_a_finding_on_the_deposit(monkeypatch):
    row = _drive(monkeypatch, None)["theprotocol_depositReputationBond"]
    assert not row["healthy"] and "bond_id None" in str(row.get("fail_reason")), row


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
