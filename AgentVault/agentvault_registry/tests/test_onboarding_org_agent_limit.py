"""§DOCSFIX D6-501 (2026-10-16): onboarding's auto-assignment honours the organization's agent limit.

`POST /organizations/{org_id}/agents/{agent_did}/assign` refuses an agent once the organization holds `limits.max_agents`
agents (100 when unset). Onboarding auto-assigns a new agent to its developer's one organization, and did so with no
look at the limit, so a full organization kept filling. The rule is one helper, `org_agent_limit_reached`, asked by the
auto-assignment before it writes the agent's organization; a full organization leaves the new agent unassigned (the
agent is created either way). Pinned by the helper's answers and by the call site, read off the AST.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
from types import SimpleNamespace

import pytest

from agentvault_registry.routers import onboarding as O

ONBOARDING = pathlib.Path(O.__file__)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Session:
    def __init__(self, limits, count):
        self._answers = [limits, count]

    async def execute(self, stmt):
        value = self._answers.pop(0)
        return SimpleNamespace(scalar_one_or_none=lambda: value, scalar=lambda: value)


@pytest.mark.parametrize("limits,count,full", [
    ({"max_agents": 2}, 1, False),
    ({"max_agents": 2}, 2, True),
    ({"max_agents": 2}, 5, True),
    (None, 99, False),                 # limits NULL on an old row: the default 100, as the assign route reads it
    (None, 100, True),
    ({}, 100, True),
])
def test_the_limit_reads_like_the_assign_route(limits, count, full):
    assert _run(O.org_agent_limit_reached(_Session(limits, count), "org-1")) is full


def _parents(tree):
    out = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[child] = node
    return out


def test_the_auto_assignment_asks_the_limit_before_it_writes():
    tree = ast.parse(ONBOARDING.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "create_agent")
    writes = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Attribute) and t.attr == "organization_id"
                      and isinstance(t.value, ast.Name) and t.value.id == "created_agent" for t in n.targets)]
    assert len(writes) == 1, "one place assigns the new agent to an organization"
    parents = _parents(fn)
    node, guarded = writes[0], False
    while node in parents:
        node = parents[node]
        if isinstance(node, ast.If) and any(
                isinstance(c, ast.Call) and getattr(c.func, "id", None) == "org_agent_limit_reached"
                for c in ast.walk(node.test)):
            guarded = True
            break
    assert guarded, "the auto-assignment must be decided by org_agent_limit_reached"
