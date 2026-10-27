"""§MCPTEST30 (V0638): the bundle lifecycle clears what its fork made.

A fork is a restore under fresh DIDs plus a child bundle (routers/bundles.py fork_bundle). lifecycle_bundle_full_crud
forked its bundle and never cleared the copy: each run left the restored agent and its card, 187 on sbx-alpha since
2026-09-03, and one per operator per sweep once the operator sweeps ran this lifecycle (2026-10-24 12:22Z and 12:26Z).
Pinned: _clear_fork deletes every produced agent and the child bundle, without writing a row, and the lifecycle hands
it the fork's own answer.
"""
from __future__ import annotations

import ast
import asyncio
import inspect

from agentvault_registry.api_tests.contracts import mcp_lifecycles as M


def _calls():
    seen = []

    async def rpc(tool, args, jwt="", timeout=20):
        seen.append((tool, dict(args)))
        return True, {"result": {"content": [{"type": "text", "text": "{}"}]}}, "200"

    return seen, rpc


def _parse(body):
    return {}


def test_a_fork_is_cleared_agent_by_agent_and_its_child_bundle():
    seen, rpc = _calls()
    fork = {"produced_agents": [{"did": "did:theprotocol:x:a1"}, {"did": "did:theprotocol:x:a2"}],
            "forked_bundle_id": "child-1"}
    asyncio.run(M._clear_fork(rpc, _parse, fork, "dev-jwt"))
    assert seen == [("theprotocol_deleteMyAgentByDev", {"agent_did": "did:theprotocol:x:a1"}),
                    ("theprotocol_deleteMyAgentByDev", {"agent_did": "did:theprotocol:x:a2"}),
                    ("theprotocol_deleteBundle", {"bundle_id": "child-1"})]


def test_an_answer_that_names_nothing_clears_nothing():
    for fork in (None, {}, {"produced_agents": [{"name": "no did"}]}, "not a dict"):
        seen, rpc = _calls()
        asyncio.run(M._clear_fork(rpc, _parse, fork, "dev-jwt"))
        assert seen == [], fork


def test_the_lifecycle_hands_the_fork_its_answer():
    fn = ast.parse(inspect.getsource(M.lifecycle_bundle_full_crud)).body[0]
    fork_targets = [n.targets[0] for n in ast.walk(fn) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Await)
                    and isinstance(n.value.value, ast.Call) and any(
                        isinstance(a, ast.Constant) and a.value == "theprotocol_forkBundle" for a in n.value.value.args)]
    assert fork_targets, "the fork's answer is not kept"
    answer = fork_targets[0].elts[1].id
    clears = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "_clear_fork"]
    assert clears and any(isinstance(a, ast.Name) and a.id == answer for a in clears[0].args)
