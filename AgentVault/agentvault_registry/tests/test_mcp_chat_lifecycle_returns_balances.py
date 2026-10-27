"""§MCPTEST30 (V0641): the chat lifecycle returns what its agents hold before deleting them, and runs on an operator.

lifecycle_chat_requests_blocks_and_leave makes four agents (a knocker of the second owner's, three recipients of the
sweep's) and deleted them in its `finally` with the owner's delete, a soft delete that keeps the balance: 432 deleted
chat agents on sbx-alpha held 1,050.00 on 2026-10-25, and an operator pays each new agent a grant. On an operator the
lifecycle never ran at all, for want of a second owner (the frame's bootstrap logs in a second seeded developer), so
sendChatMessage and respondChatRequest passed on a made-up conversation alone there. Pinned: each agent's balance goes
back through tegTreasuryReceive before its delete, an unread balance is said and nothing is returned; the operator
sweep registers a second owner, hands it to the lifecycle and has it ask for its own deletion after the lifecycles.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import textwrap
from types import SimpleNamespace

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts import mcp_lifecycles as L


def _answer(payload):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


def _error(text):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "Error: " + text}],
                                                    "isError": True}}


def _run(balance="1000"):
    log, made = [], []

    async def rpc(tool, args, jwt="", timeout=20):
        if tool == "theprotocol_createAgent":
            did = f"did:theprotocol:chat-{len(made) + 1}"
            made.append(did)
            return True, _answer({"did": did, "client_id": "cid", "client_secret": "sec"}), "201"
        if tool == "theprotocol_getAgentToken":
            return True, _answer({"access_token": "agent-jwt"}), "200"
        if tool == "theprotocol_createWebhook":
            return False, _error("HTTP 400: refused"), "400"        # the lifecycle stops here: only the cleanup runs
        if tool == "theprotocol_getBatchAgentBalances":
            did = args["agent_dids"][0]
            return True, _answer({"balances": {did: ({"balance": balance} if balance is not None else
                                                      {"balance": "0", "error": "Balance fetch failed"})}}), "200"
        if tool == "theprotocol_deleteMyAgentByDev":
            log.append(("delete", args["agent_did"], jwt))
            return True, _answer({}), "204"
        raise AssertionError(tool)

    async def rpc_admin(tool, args, jwt="", timeout=25):
        assert tool == "theprotocol_tegTreasuryReceive"
        log.append(("receive", args["source_agent_did"], args["amount"]))
        return True, _answer({"status": "received"}), "200"

    bag = SimpleNamespace(developer_jwt="dev-a", developer_jwt_nonadmin2="dev-b", rpc_admin=rpc_admin,
                          throwaway_balances=[], flow_values={}, event_verifier=None)
    asyncio.run(L.lifecycle_chat_requests_blocks_and_leave(rpc, F._parse_rpc_result, bag, {}))
    return log, made, bag


def test_each_agents_balance_goes_back_before_its_delete():
    log, made, bag = _run()
    assert len(made) == 4
    for did in made:
        i_recv = log.index(("receive", did, "1000"))
        i_del = next(i for i, e in enumerate(log) if e[0] == "delete" and e[1] == did)
        assert i_recv < i_del, did
    assert bag.throwaway_balances == []
    owners = {e[1]: e[2] for e in log if e[0] == "delete"}
    assert owners[made[0]] == "dev-b" and {owners[d] for d in made[1:]} == {"dev-a"}, "each owner deletes its own"


def test_an_unread_balance_is_said_and_nothing_is_returned():
    log, made, bag = _run(balance=None)
    assert not [e for e in log if e[0] == "receive"]
    assert len([e for e in log if e[0] == "delete"]) == 4
    assert len(bag.throwaway_balances) == 4 and all("could not be read" in s for s in bag.throwaway_balances)


def test_the_operator_sweep_gives_the_lifecycle_a_second_owner_and_retires_it():
    tree = ast.parse(textwrap.dedent(inspect.getsource(F.TestFlowMcpLifecycle._run_cloudop_mcp_sweep)))
    mints = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_mint_throwaway_developer"
             and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant) and n.args[1].value == "chat"]
    assert len(mints) == 1
    sets = [n for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Attribute) and t.attr == "developer_jwt_nonadmin2" for t in n.targets)]
    assert len(sets) == 1
    deletions = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_schedule_own_deletion"
                 and any(isinstance(a, ast.Constant) and a.value == "chat second owner" for a in n.args)]
    assert len(deletions) == 1
    sweep_line = next(n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call)
                      and getattr(n.func, "id", "") == "_bounded_sweep" and n.args and ast.unparse(n.args[0]) == "_cop_lcs")
    assert mints[0].lineno < sweep_line < deletions[0].lineno, "minted before the lifecycles, retired after them"
