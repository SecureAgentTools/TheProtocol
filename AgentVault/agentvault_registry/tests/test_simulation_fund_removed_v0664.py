"""V0664 (order gwo_40f159d2a945a7070df20933, room seq 3638): /admin/simulation/fund and fundSimulationAgents
are removed, as simulationFundingPreview was in V0663.

POST /admin/simulation/fund ran the retired network's host script (sim_fund_agents.py) through a docker socket the new
registries do not have; GET /admin/simulation/fund-status only read the progress file that script wrote under the host
stack, which they do not mount either (removed with it: session-code's scope note, room seq 3649). Gone: both routes,
both admin MCP tools (fundSimulationAgents, getAdminSimulationFundStatus: function, schema, dispatch entry, category),
their contract, request-body and endpoint rows, the tester's side-effect marker and its timeout rows, the generated
admin-route entries, the console's calls and its Top up / Depleted Only / FUND controls with their progress log and
confirm. Not gone (the controls): the simulation's other routes and tools, and the console's issue bar with its own
confirmed button. The published journal text that once showed the tool (BlogView.vue) is history and stays.
Red on v0663/cut b7ca684e9: the routes, the tools and every row still exist.
"""
from __future__ import annotations

import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
NAMES = ("fundSimulationAgents", "fund_simulation_agents", "getAdminSimulationFundStatus",
         "get_admin_simulation_fund_status", "sim_fund_agents", "sim_fund_progress", "fundAgents", "getFundStatus")
ROUTE = re.compile(r"/simulation/fund(?!ing)")
# the console's own guard names them to assert they are gone; the journal's published text is history
KEEP = {"EigenTrustCommand.noSimFund.test.ts", "BlogView.vue"}


def test_both_routes_are_gone_and_their_neighbours_stay():
    from agentvault_registry.routers import admin_simulation
    paths = {getattr(r, "path", "") for r in admin_simulation.router.routes}
    assert not any(p.endswith("/fund") or p.endswith("/fund-status") for p in paths), sorted(paths)
    assert any(p.endswith("/agents") for p in paths) and any(p.endswith("/mint-frame-b") for p in paths), "the controls"


def test_both_admin_tools_are_gone_and_their_neighbours_stay():
    from agentvault_registry.mcp import server_admin, tool_categories, tools_admin
    for name in ("theprotocol_fundSimulationAgents", "theprotocol_getAdminSimulationFundStatus"):
        assert name not in server_admin.ADMIN_TOOL_DISPATCH, name
        assert name not in {s["name"] for s in tools_admin.ADMIN_TOOL_SCHEMAS}, name
    assert not hasattr(tools_admin, "fund_simulation_agents")
    assert not hasattr(tools_admin, "get_admin_simulation_fund_status")
    assert "fundSimulationAgents" not in str(vars(tool_categories))
    assert "getAdminSimulationFundStatus" not in str(vars(tool_categories))
    assert "theprotocol_issueFrameBSimulation" in server_admin.ADMIN_TOOL_DISPATCH, "the control stays"


def test_their_contract_body_endpoint_and_marker_rows_are_gone():
    from agentvault_registry.api_tests import base, endpoints_registry, request_bodies
    from agentvault_registry.api_tests.contracts import mcp_admin_lifecycles
    assert "fundSimulationAgents" not in str(vars(mcp_admin_lifecycles))
    assert "getAdminSimulationFundStatus" not in str(vars(mcp_admin_lifecycles))
    assert not ROUTE.search(str(vars(request_bodies))) and not ROUTE.search(str(vars(endpoints_registry)))
    assert "/simulation/fund" not in base._SIDE_EFFECT_MARKERS
    assert "/simulation/start" in base._SIDE_EFFECT_MARKERS, "the control: the other mutators stay withheld"


def test_nothing_in_the_source_tree_names_them():
    """Every file under src/ (the registry, the contracts, the console, the generated route lists): no mention left."""
    hits = []
    for p in SRC.rglob("*"):
        if not p.is_file() or p.name in KEEP or "node_modules" in p.parts or "dist" in p.parts or p.suffix not in (
                ".py", ".ts", ".vue", ".json", ".md", ".js"):
            continue
        text = p.read_text(errors="ignore")
        for n in NAMES:
            if n in text:
                hits.append(f"{p.relative_to(SRC)}: {n}")
        if ROUTE.search(text):
            hits.append(f"{p.relative_to(SRC)}: /simulation/fund")
    assert hits == []
