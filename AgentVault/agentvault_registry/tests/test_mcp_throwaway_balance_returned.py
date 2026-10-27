"""§MCPTEST30 (V0638): a throwaway agent's balance goes back to the treasury before its owner deletes it.

earned_fixtures.Throwaways.close() deleted each throwaway agent through its owner's deleteMyAgentByDev, a soft delete
that keeps the balance, so the genesis grant a throwaway developer's first agent is paid from the treasury stayed on the
revoked agent. The operator sweeps of 2026-10-24 left 135,000 on sbxalphaop and 100,524 on sbxbetaop that way, and
sbxbetaop's treasury fell to 7,858.72, a single grant. Pinned: the owner reads the balance and the admin bridge returns
exactly what the read showed (tegTreasuryReceive) before the delete; a read that failed, or an entry carrying an error
(the batch route answers "0" beside it), returns nothing and is said; a zero returns nothing and says nothing; a refused
return is said with the amount; the delete runs in every case; both run summaries carry what was said.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
from types import SimpleNamespace

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts import earned_fixtures as ef
from agentvault_registry.api_tests.contracts.mcp_contracts import McpFixtureBag

DID = "did:theprotocol:sandbox-a.theprotocol.cloud:0abf5d3a-0a45-450c-9741-500e3dd7a08c"
RECEIVED = (True, {"inner": {"transaction_id": "t1"}}, "200")


def _parse(body):
    return body.get("inner", {}) if isinstance(body, dict) else {}


def _read(entry, ok=True, code="200"):
    return ok, {"inner": {"balances": {DID: entry}}}, code


def _close(read, receive=RECEIVED, admin=True, bag=None):
    calls = []

    async def rpc(tool, args, jwt="", timeout=20):
        calls.append(("dev", tool, dict(args), jwt))
        if tool == "theprotocol_getBatchAgentBalances":
            if isinstance(read, Exception):
                raise read
            return read
        return True, {"inner": {}}, "200"

    async def rpc_admin(tool, args, jwt="", timeout=25):
        calls.append(("admin", tool, dict(args), jwt))
        return receive

    bag = bag if bag is not None else SimpleNamespace(developer_jwt="admin-jwt", throwaway_balances=[])
    if admin:
        bag.rpc_admin = rpc_admin
    t = ef.Throwaways(rpc, _parse, bag, "contracts")
    t._agents.append((DID, "owner-jwt"))
    asyncio.run(t.close())
    return calls, getattr(bag, "throwaway_balances", None)


def _tools(calls):
    return [c[1] for c in calls]


def test_the_balance_the_read_showed_goes_back_before_the_delete():
    calls, said = _close(_read({"balance": "5000.000000000000000000", "currency": "SBXA"}))
    assert _tools(calls) == ["theprotocol_getBatchAgentBalances", "theprotocol_tegTreasuryReceive",
                             "theprotocol_deleteMyAgentByDev"]
    read, receive, delete = calls
    assert read[0] == "dev" and read[3] == "owner-jwt" and read[2] == {"agent_dids": [DID]}
    assert receive[0] == "admin" and receive[3] == "admin-jwt"
    assert receive[2]["source_agent_did"] == DID and receive[2]["amount"] == "5000.000000000000000000"
    assert receive[2]["reason"] == "mcp_tester_fixture_retired"
    assert delete[0] == "dev" and delete[3] == "owner-jwt" and delete[2] == {"agent_did": DID}
    assert said == []


def test_a_balance_in_scientific_notation_is_returned_as_the_same_number():
    calls, _said = _close(_read({"balance": "1E+3", "currency": "SBXA"}))
    assert calls[1][2]["amount"] == "1000"


def test_an_entry_carrying_an_error_is_unread_not_zero():
    calls, said = _close(_read({"balance": "0", "currency": "SBXA", "error": "Agent is revoked"}))
    assert _tools(calls) == ["theprotocol_getBatchAgentBalances", "theprotocol_deleteMyAgentByDev"]
    assert len(said) == 1
    assert DID in said[0] and "could not be read" in said[0] and "Agent is revoked" in said[0]


def test_a_failed_read_returns_nothing_and_says_so():
    calls, said = _close((False, {"inner": {"detail": "Not authenticated"}}, "401"))
    assert _tools(calls) == ["theprotocol_getBatchAgentBalances", "theprotocol_deleteMyAgentByDev"]
    assert len(said) == 1 and DID in said[0] and "HTTP 401" in said[0]


def test_a_read_that_is_not_a_number_is_unread():
    for value in (None, "", "abc", "NaN"):
        calls, said = _close(_read({"balance": value, "currency": "SBXA"}))
        assert "theprotocol_tegTreasuryReceive" not in _tools(calls), value
        assert len(said) == 1 and "could not be read" in said[0], value


def test_a_zero_balance_returns_nothing_and_says_nothing():
    for zero in ("0", "0E-18", "0.000000"):
        calls, said = _close(_read({"balance": zero, "currency": "SBXA"}))
        assert _tools(calls) == ["theprotocol_getBatchAgentBalances", "theprotocol_deleteMyAgentByDev"], zero
        assert said == [], zero


def test_a_refused_return_is_said_with_the_amount_and_the_delete_still_runs():
    calls, said = _close(_read({"balance": "5000.5", "currency": "SBXA"}),
                         receive=(False, {"inner": {"detail": "Treasury receive failed: insufficient"}}, "400"))
    assert _tools(calls)[-1] == "theprotocol_deleteMyAgentByDev"
    assert len(said) == 1 and DID in said[0] and "5000.5 held" in said[0] and "HTTP 400" in said[0]


def test_without_an_admin_bridge_the_balance_is_said():
    calls, said = _close(_read({"balance": "1000", "currency": "SBXA"}), admin=False)
    assert _tools(calls) == ["theprotocol_getBatchAgentBalances", "theprotocol_deleteMyAgentByDev"]
    assert len(said) == 1 and "1000 held" in said[0] and "no admin bridge" in said[0]


def test_a_read_that_raises_is_said_and_the_delete_still_runs():
    calls, said = _close(RuntimeError("the transport broke"))
    assert _tools(calls) == ["theprotocol_getBatchAgentBalances", "theprotocol_deleteMyAgentByDev"]
    assert len(said) == 1 and DID in said[0] and "RuntimeError" in said[0]


def test_a_bag_without_the_list_still_closes():
    bag = SimpleNamespace(developer_jwt="admin-jwt")
    calls, said = _close(_read({"balance": "0", "currency": "SBXA", "error": "Agent is revoked"}), admin=False,
                         bag=bag)
    assert _tools(calls)[-1] == "theprotocol_deleteMyAgentByDev" and said is None


def test_the_bag_starts_with_nothing_said():
    assert McpFixtureBag(sentinel_did="did:theprotocol:test", sentinel_jwt="x").throwaway_balances == []


def test_both_run_summaries_carry_what_was_said():
    tree = ast.parse(inspect.getsource(F))
    carried = [k for node in ast.walk(tree) if isinstance(node, ast.Dict) for k, v in zip(node.keys, node.values)
               if isinstance(k, ast.Constant) and k.value == "throwaway_balances_not_returned"
               and "throwaway_balances" in ast.unparse(v)]
    assert len(carried) == 2, "the frame run and the operator sweep each carry the list in their summary"
