"""§MCPTEST30 (V0548) — an MCP tool's inputSchema states what its route enforces.

An MCP caller reads the tool's schema and nothing else. On V0546, 168 arguments of 85 tools carried a constraint their
route enforces (an enum written as a pattern, a minimum length, a maximum) that their schema did not state, and one
schema contradicted its route: updateSupportTicketStatus offered "escalated" and "pending", which the route refuses
with 422. mcp/route_constraints.py carries the routes' constraints into the advertised schemas; this gate runs the
census (tests/mcp_schema_census.py, in a fresh process like the request survey) and holds the table equal to what the
routes state: a constraint missing from it, one the route no longer states, or a tool schema looser than its route
(a bound above the route's, an enum value the route refuses) fails the build. Regenerate the table with
`python tests/mcp_schema_census.py --write src/agentvault_registry/mcp/route_constraints.py` and read the diff.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from agentvault_registry.mcp import route_constraints as RC

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def census():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "census.json"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(HERE.parent / "src") + os.pathsep + env.get("PYTHONPATH", "")
        r = subprocess.run([sys.executable, str(HERE / "mcp_schema_census.py"), "--json", str(out)],
                           env=env, cwd=str(HERE), capture_output=True, text=True, timeout=900)
        assert r.returncode == 0, f"the census did not run:\n{r.stderr[-3000:]}"
        return json.loads(out.read_text())


def test_the_census_reached_the_routes(census):
    assert census["tools"] >= 700, census["tools"]
    assert census["stated_fields"] >= 250, f"only {census['stated_fields']} arguments read a route constraint"


def test_no_route_constraint_is_missing_from_the_advertised_schemas(census):
    assert census["missing"] == {}, (
        "the route states these and the tool's schema does not (re-render the table, read the diff):\n"
        + json.dumps(census["missing"], indent=1, sort_keys=True)[:4000])


def test_no_tool_schema_is_looser_than_its_route(census):
    assert census["conflict"] == {}, ("a tool's own schema allows what its route refuses (fix the schema):\n"
                                      + json.dumps(census["conflict"], indent=1, sort_keys=True)[:4000])


def test_the_table_carries_nothing_the_routes_no_longer_state(census):
    assert census["stale"] == {}, ("the table states what no route does any more (re-render it):\n"
                                   + json.dumps(census["stale"], indent=1, sort_keys=True)[:4000])


def test_the_census_reads_an_alternation_as_an_enum_and_drops_a_meaningless_format():
    sys.path.insert(0, str(HERE))
    try:
        import mcp_schema_rules as C   # noqa: PLC0415  (the census's rules alone: importing the census patches httpx)
    finally:
        sys.path.remove(str(HERE))
    assert C.route_constraints({"type": "string", "pattern": "^(buy|sell)$"}) == ("string", {"enum": ["buy", "sell"]})
    assert C.route_constraints({"type": "string", "pattern": "^[A-Z0-9]{2,6}$", "minLength": 2}) == (
        "string", {"pattern": "^[A-Z0-9]{2,6}$", "minLength": 2})
    assert C.route_constraints({"type": "string", "format": "password", "minLength": 12}) == ("string", {"minLength": 12})
    assert C.route_constraints({"type": "integer", "maximum": 365.0}) == ("integer", {"maximum": 365})
    # a schema stricter than its route is a tool narrowing on purpose; only a looser one misleads a caller
    assert C.looser("maximum", 500, 200) and not C.looser("maximum", 50, 120)
    assert C.looser("minLength", 1, 10) and not C.looser("minLength", 12, 12)
    assert C.looser("enum", ["open", "escalated"], ["open", "closed"]) and not C.looser("enum", ["closed"], ["open", "closed"])


def test_apply_adds_only_where_the_tool_states_nothing_and_is_idempotent(monkeypatch):
    monkeypatch.setattr(RC, "ROUTE_CONSTRAINTS", {"theprotocol_x": {
        "side": {"enum": ["buy", "sell"]}, "limit": {"maximum": 200}, "rows": {"items": {"type": "object"}}}})
    monkeypatch.setattr(RC, "APPLIED", {})
    sc = {"name": "theprotocol_x", "inputSchema": {"type": "object", "properties": {
        "side": {"type": "string"}, "limit": {"type": "integer", "maximum": 50}, "rows": {"type": "array"}}}}
    assert RC.apply_route_constraints([sc, sc]) == 2
    props = sc["inputSchema"]["properties"]
    assert props["side"]["enum"] == ["buy", "sell"] and props["rows"]["items"] == {"type": "object"}
    assert props["limit"]["maximum"] == 50, "a key the tool states itself is never changed"
    assert RC.APPLIED == {"theprotocol_x": {"side": ["enum"], "rows": ["items"]}}


def test_the_advertised_schemas_carry_what_the_routes_state():
    from agentvault_registry.mcp import server, server_admin
    pub = {sc["name"]: sc for sc in server.ALL_TOOL_SCHEMAS if isinstance(sc, dict) and "name" in sc}
    adm = {sc["name"]: sc for sc in server_admin.ADMIN_TOOL_SCHEMAS if isinstance(sc, dict) and "name" in sc}
    order = pub["theprotocol_placeAgoraOrder"]["inputSchema"]["properties"]
    assert order["side"]["enum"] == ["buy", "sell"] and order["order_type"]["enum"] == ["limit", "market"]
    assert adm["theprotocol_bulkSuspendAgents"]["inputSchema"]["properties"]["reason"]["minLength"] == 10
    assert adm["theprotocol_updateSupportTicketStatus"]["inputSchema"]["properties"]["status"]["enum"] == [
        "open", "in_progress", "resolved", "closed"]
