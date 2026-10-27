"""§MCPTEST30 (V0545) — a distribution's reward records page in a unique order, and the tester reads one.

The records route paged with `.limit().offset()` and no ORDER BY: Postgres hands back rows in whatever order each plan
produces, so two pages are not a partition of the list (§DIRFEED-2). Pinned by compiling the STATEMENT: a fixture of
a few rows pages "correctly" with or without an order, which is how the class survives. And
getLockPayoutRecords stood skipped for want of a distribution id, while the frame runs a distribution a day:
the id is now a read-only pick of one the target already ran.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.dialects import postgresql

from agentvault_registry.routers.staking_rewards import distribution_records_stmt
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_the_page_has_a_unique_order_before_its_bounds():
    sql = _sql(distribution_records_stmt("d-1", 3, 6))
    assert "ORDER BY staking_reward_records.agent_did, staking_reward_records.id" in sql, sql
    assert sql.index("ORDER BY") < sql.index("LIMIT") < sql.index("OFFSET"), sql
    assert "staking_reward_records.distribution_id = 'd-1'" in sql


def test_the_route_pages_through_the_ordered_statement():
    import inspect
    from agentvault_registry.routers import staking_rewards as sr
    src = inspect.getsource(sr.get_distribution_records)
    assert "distribution_records_stmt(distribution_id, limit, offset)" in src
    assert ".limit(limit).offset(offset)" not in src, "a second, unordered copy of the page"


def _pick(answer):
    seen = []

    async def call(tool, args, jwt):
        seen.append((tool, args, jwt))
        return answer
    return asyncio.run(F.staking_distribution_pick(call, "dev")), seen


@pytest.mark.parametrize("answer,want", [
    ({"distributions": [{"id": "9dfd"}, {"id": "d866"}], "total": 2}, "9dfd"),
    ([{"id": None}, {"id": "84a0"}], "84a0"),            # a bare list is read too, an empty id skipped
    ({"distributions": [], "total": 0}, None),
    ({"error": "HTTP 503"}, None),
    (None, None),
])
def test_the_pick_reads_one_the_target_already_ran(answer, want):
    got, seen = _pick(answer)
    assert got == want
    assert seen == [("theprotocol_getLockPayoutRuns", {"limit": 5}, "dev")], "one read, nothing made"


def test_the_records_contract_waits_on_the_picked_id():
    c = MCP_CONTRACTS["theprotocol_getLockPayoutRecords"]
    assert c.skip_reason is None and c.arguments == {"distribution_id": "${distribution_id}"}
    assert "distribution_id" in c.requires_fixtures


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_the_tool_states_a_shape_the_contract_can_check(monkeypatch):
    """V0546: the route answers a bare list and the tool passed it through, so no contract could state the answer (round
    14's cloud-op sweep: "contract gap"). The tool wraps it the way getMyWebhooks does; an error passes untouched."""
    from agentvault_registry.mcp import tools_developer as TD
    answers = {"list": [{"agent_did": "did:theprotocol:a", "amount": "1.0"}], "error": {"error": "HTTP 404: no such distribution"}}
    seen = []

    async def fake(auth, method, path, **kw):
        seen.append((method, path))
        return answers[auth]
    monkeypatch.setattr(TD, "_dev_request", fake)
    out = asyncio.run(TD.get_staking_distribution_records("list", "d-1"))
    assert out == {"records": answers["list"], "total": 1}
    assert seen == [("GET", "/api/v1/staking/rewards/distributions/d-1/records")]
    assert asyncio.run(TD.get_staking_distribution_records("error", "d-1")) == answers["error"]
    c = MCP_CONTRACTS["theprotocol_getLockPayoutRecords"]
    assert c.expect_keys == ["records", "total"] and c.expect_types == {"records": list, "total": int}
    healthy, fail = F._evaluate_contract({"name": "theprotocol_getLockPayoutRecords"}, c, True, "200",
                                         {"result": {"content": [{"type": "text", "text": '{"records": [], "total": 0}'}]}},
                                         None, has_explicit_contract=True)
    assert healthy is True and fail is None, fail
