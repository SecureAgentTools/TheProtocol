"""§MCPTEST30 (V0552): the admin developer detail names its agents with one read per chunk, not one query per agent.

GET /api/v1/admin/developers/{id} ran a query per agent for the agent's card name. The sandbox tester's developer owns
6,685 agents on sbx-alpha, so its detail issued about 6,700 queries and timed out (the MCP tester's
getAdminDeveloperDetail in round 17: "ReadTimeout"). The names now come from one statement per 5,000 agents: the latest
active card of each agent (DISTINCT ON agent_did, newest first), best-effort as before.
"""
from __future__ import annotations

import ast
import asyncio
import inspect

from sqlalchemy.dialects import postgresql

from agentvault_registry.routers import admin_developers as R


def test_the_statement_takes_each_agents_latest_active_card():
    sql = str(R._agent_card_names_stmt(["did:a", "did:b"]).compile(dialect=postgresql.dialect()))
    assert "DISTINCT ON (agent_cards.agent_did)" in sql
    assert "agent_cards.is_active IS true" in sql
    assert "ORDER BY agent_cards.agent_did, agent_cards.created_at DESC" in sql
    assert "agent_cards.agent_did IN" in sql


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    async def execute(self, stmt):
        self.calls += 1
        if self.fail:
            raise RuntimeError("connection lost")
        dids = list(stmt.compile().params.values())[0]
        return _Rows([(d, f"name-{d}") for d in dids if not d.endswith("-nocard")])


def test_thousands_of_agents_cost_one_read_per_chunk():
    dids = [f"did:x:{i}" for i in range(12001)] + ["did:x:z-nocard"]
    db = _Session()
    names = asyncio.run(R._agent_card_names(db, dids))
    assert db.calls == 3, "5,000 + 5,000 + 2,002 agents: three reads, never one per agent"
    assert names["did:x:0"] == "name-did:x:0" and names["did:x:12000"] == "name-did:x:12000"
    assert names.get("did:x:z-nocard") is None, "an agent without a card has no name, as before"
    assert asyncio.run(R._agent_card_names(_Session(), [])) == {}


def test_unreadable_names_leave_the_agents_listed_without_them():
    db = _Session(fail=True)
    assert asyncio.run(R._agent_card_names(db, ["did:a", "did:b"])) == {}
    assert db.calls == 1, "a failed read is not retried agent by agent"


def test_the_detail_no_longer_queries_inside_its_agent_loop():
    tree = ast.parse(inspect.getsource(R.get_developer_detail))
    loops = [n for n in ast.walk(tree) if isinstance(n, (ast.For, ast.AsyncFor))]
    awaited_in_loop = [c for loop in loops for c in ast.walk(loop) if isinstance(c, ast.Await)]
    assert loops and not awaited_in_loop, "no query (no await) inside a loop over the developer's agents"
    assert "_agent_card_names" in inspect.getsource(R.get_developer_detail)


def test_the_tester_holds_the_detail_to_its_answer():
    from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS
    c = MCP_CONTRACTS["theprotocol_getAdminDeveloperDetail"]
    assert c.override_coverage_fan and c.excerpt_shape_only and c.expect_status == "success"
    assert {"id", "agent_count", "agents", "api_keys", "organizations"} <= set(c.expect_keys)
