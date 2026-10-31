"""§MCPTEST30 (V0650, tester batch 1 item 1a, agentvault2-d3, Guild order gwo_2015b757c94ce69138500df6):
earn_ephemeral_value, units returned and paid out by hand to an agent of the run's own (funded first through fund-agent),
only where the target is torn down after its run (MCP_TESTER_EPHEMERAL_TARGET), each step read back on the registry AND on
the ledger's projection. tegTreasuryIssue is never run: minting is never automated (his decision D9).

Also the defect the lifecycle found in the code before it ever ran: distributeFromFeeCollector's MCP tool never sent
`target_agent_did`, which its route has always required (400 "Missing target_agent_did"), so no call through MCP could
succeed; the route reads a raw body, so the request-shape gate could not see it. RED on V0649's code: the lifecycle does
not exist, and the tool's body carries no target_agent_did.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import pytest

from agentvault_registry.api_tests.contracts import earned_admin_dev
from agentvault_registry.api_tests.contracts import earned_ad_ephemeral as eph
from agentvault_registry.api_tests.contracts.earned_fixtures import effect_name

DID = "did:theprotocol:sandbox-a:mcp-earn-value-agent"


class _World:
    """The registry's book and the ledger's projection of one agent, the treasury's mint, receive and payout routes."""

    def __init__(self, *, held: str = "0", fee: str = "3", ledger_skips: str = "", fund_refused: bool = False):
        self.reg = {DID: Decimal(held)}
        self.led = {DID: Decimal(held)}
        self.fee = Decimal(fee)
        self.ledger_skips, self.fund_refused = ledger_skips, fund_refused
        self.events: List[str] = []
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    def _book(self, tool: str, did: str, delta: Decimal) -> None:
        self.reg[did] = self.reg.get(did, Decimal(0)) + delta
        if tool != self.ledger_skips:
            self.led[did] = self.led.get(did, Decimal(0)) + delta

    async def public(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        self.calls.append((tool, dict(args)))
        assert tool == eph.BALANCES, f"the value lifecycle called {tool} on the public bridge"
        return True, {"result": {"balances": {d: {"balance": str(self.reg.get(d, 0))} for d in args["agent_dids"]}}}, "200"

    async def admin(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        self.calls.append((tool, dict(args)))
        ok, result, code = self._admin(tool, dict(args))
        return ok, {"result": result}, code

    def _admin(self, tool: str, a: Dict[str, Any]) -> Tuple[bool, Any, str]:
        if tool == eph.ES_QUERY:
            did = a["path"].rsplit("/", 1)[-1]
            return True, {"path": a["path"], "status_code": 200, "ok": True,
                          "response": {"agent_did": did, "liquid_balance": float(self.led.get(did, 0))}}, "200"
        if tool == eph.FEE_INFO:
            return True, {"balance": str(self.fee), "did": "teg:system:fee_collector"}, "200"
        if tool == eph.FUND:
            assert a["endpoint"] == "/api/v1/teg/treasury/fund-agent" and a["body"]["reason"] == "admin_grant"
            if self.fund_refused:
                return False, {"_text": "Error: HTTP 403: the scripted refusal"}, "403"
            self._book("fund", a["body"]["target_agent_did"], Decimal(a["body"]["amount"]))
            return True, {"status_code": 200, "ok": True, "response": {"status": "completed"}}, "200"
        assert tool != "theprotocol_tegTreasuryIssue", "the lifecycle minted: his decision D9 says never"
        if tool == eph.RECEIVE:
            self._book(tool, a["source_agent_did"], -Decimal(a["amount"]))
            self.events.append("TreasurySlashReceived")
            return True, {"status": "completed"}, "200"
        if tool == eph.DISTRIBUTE:
            assert a.get("target_agent_did"), "the payout names no agent"
            self.fee -= Decimal(a["amount"])
            self._book(tool, a["target_agent_did"], Decimal(a["amount"]))
            return True, {"status": "completed"}, "200"
        return False, {"_text": f"Error: HTTP 404: no such tool {tool}"}, "404"


class _Throwaways:
    closed = 0

    def __init__(self, rpc, parse, bag, tag):
        pass

    async def developer(self, role: str, verify: bool = True) -> Dict[str, Any]:
        return {"developer_id": 9, "access_token": "dev-jwt"}

    async def agent(self, dev: Dict[str, Any], label: str = "") -> Dict[str, Any]:
        return {"did": DID, "owner_jwt": "owner-jwt", "agent_jwt": "agent-jwt"}

    async def close(self) -> None:
        type(self).closed += 1


def _parse(body: Dict[str, Any]) -> Any:
    return body.get("result") if isinstance(body, dict) else {}


def _run(world: _World, monkeypatch) -> Dict[str, dict]:
    from agentvault_registry.api_tests.contracts.mcp_contracts import McpFixtureBag
    monkeypatch.setattr(eph, "Throwaways", _Throwaways)

    async def fast(_s):
        return None
    monkeypatch.setattr(eph.asyncio, "sleep", fast)
    bag = McpFixtureBag(sentinel_did="did:theprotocol:offline-sentinel", sentinel_jwt="sentinel-jwt",
                        developer_jwt="runner-dev-jwt", developer_id="1")
    bag.rpc_admin = world.admin            # type: ignore[attr-defined]
    bag.admin_lifecycle_rows = {}          # type: ignore[attr-defined]

    async def event_verifier(types: List[str], tool: str) -> Tuple[bool, Optional[str]]:
        missing = [t for t in types if t not in world.events]
        return (not missing), (f"no {missing} after {tool}" if missing else None)
    bag.event_verifier = event_verifier    # type: ignore[attr-defined]
    outcomes: Dict[str, dict] = {}
    asyncio.run(eph.lifecycle_earn_ephemeral_value(world.public, _parse, bag, outcomes))
    return outcomes


def _ok(row: dict) -> bool:
    return bool(row.get("healthy")) and not row.get("skip_reason") and not row.get("fail_reason")


def test_it_is_registered_with_the_earned_admin_lifecycles():
    assert "earn_ephemeral_value" in [lc["name"] for lc in earned_admin_dev.LIFECYCLES]


def test_a_standing_frame_moves_nothing_and_says_why(monkeypatch):
    monkeypatch.delenv(eph.EPHEMERAL_ENV, raising=False)
    w = _World()
    out = _run(w, monkeypatch)
    assert w.calls == []
    assert sorted(out) == sorted(effect_name(t) for t in eph.VALUE_TOOLS)
    assert all(eph.EPHEMERAL_ENV in str(r.get("skip_reason")) for r in out.values())


def test_an_ephemeral_frame_earns_both_and_mints_nothing(monkeypatch):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, "true")
    _Throwaways.closed = 0
    w = _World()
    out = _run(w, monkeypatch)
    for tool in eph.VALUE_TOOLS:
        assert _ok(out[effect_name(tool)]), (tool, out[effect_name(tool)])
        assert "both moved" in out[effect_name(tool)].get("read_back", "")
    assert [t for t, _a in w.calls if t in eph.VALUE_TOOLS] == list(eph.VALUE_TOOLS)
    assert w.reg[DID] == Decimal("0.01") and w.fee == Decimal("2.99"), "funded 1, returned 1, paid 0.01"
    assert "theprotocol_tegTreasuryIssue" not in [t for t, _a in w.calls]
    assert _Throwaways.closed == 1, "the agent and its developer are cleared away"


def test_a_payout_the_ledger_never_recorded_is_red(monkeypatch):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, "true")
    out = _run(_World(ledger_skips=eph.DISTRIBUTE), monkeypatch)
    row = out[effect_name(eph.DISTRIBUTE)]
    assert not row["healthy"] and "the event store did not record" in str(row.get("fail_reason")), row
    assert _ok(out[effect_name(eph.RECEIVE)])


def test_a_return_the_ledger_never_recorded_is_red(monkeypatch):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, "true")
    out = _run(_World(ledger_skips=eph.RECEIVE), monkeypatch)
    assert not out[effect_name(eph.RECEIVE)]["healthy"]


def test_a_refused_funding_and_an_empty_fee_account_are_said(monkeypatch):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, "true")
    out = _run(_World(held="0.5", fee="0", fund_refused=True), monkeypatch)
    assert "under the 1 unit" in str(out[effect_name(eph.RECEIVE)].get("skip_reason"))
    assert "fee account holds 0" in str(out[effect_name(eph.DISTRIBUTE)].get("skip_reason"))


def test_the_payout_tool_names_the_agent_its_route_requires(monkeypatch):
    from agentvault_registry.mcp import tools_admin as T
    sent: List[Tuple[str, Dict[str, Any]]] = []

    async def post(_auth, path, json_body=None, **_k):
        sent.append((path, dict(json_body or {})))
        return {"ok": True}
    monkeypatch.setattr(T, "_admin_post", post)
    asyncio.run(T.distribute_from_fee_collector(None, target_agent_did=DID, amount="0.01", reason="manual_payout",
                                                reference_id="r-1"))
    assert sent == [("/api/v1/admin/fee-collector/distribute",
                     {"target_agent_did": DID, "amount": "0.01", "reason": "manual_payout", "reference_id": "r-1"})]
    refused = asyncio.run(T.distribute_from_fee_collector(None, target_agent_did="", amount="1", reason="x"))
    assert "target_agent_did" in str(refused.get("error"))
    schema = next(t for t in T.ADMIN_TOOL_SCHEMAS if t["name"] == "theprotocol_distributeFromFeeCollector")["inputSchema"]
    assert "target_agent_did" in schema["required"]


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
