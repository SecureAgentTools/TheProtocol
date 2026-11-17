"""V0663 (order gwo_be8899e9eb589224813ec90a, his yes at room seq 3182): simulationFundingPreview is removed.

The refusal-only classification (sessionlogs2026/CLASSIFICATION_2026-11-13_MCP_REFUSAL_ONLY.md, A9): POST
/admin/simulation/funding-preview ran the retired network's host script (sim_fund_agents.py --preview) through a
docker socket the new registries do not have, so it answered "Failed to parse output" on every frame and could never
do its job. Gone: the route, the admin MCP tool (its function, schema, dispatch entry and category), its contract,
request body, endpoint row and by-design reason, the federation suite's reachability test and its ceiling, the
console's call and its Preview button, the generated admin-route entry. Not gone (the control): the simulation's other
routes and tools (V0664 removed /admin/simulation/fund and its tool too, tests/test_simulation_fund_removed_v0664.py, so
the controls are /agents and issueFrameBSimulation).
Red on b27f2ebaf: the route, the tool and every row still exist.
"""
from __future__ import annotations

import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
NAMES = ("simulationFundingPreview", "simulation_funding_preview", "/simulation/funding-preview", "fundingPreview")
GUARDS = {"EigenTrustCommand.noFundingPreview.test.ts"}   # the console's own guard names it to assert it is gone


def test_the_route_is_gone_and_its_neighbour_stays():
    from agentvault_registry.routers import admin_simulation
    paths = {getattr(r, "path", "") for r in admin_simulation.router.routes}
    assert not any(p.endswith("/funding-preview") for p in paths), sorted(paths)
    assert any(p.endswith("/agents") for p in paths), "the control: the simulation's other routes stay"


def test_the_admin_tool_is_gone_and_its_neighbour_stays():
    from agentvault_registry.mcp import server_admin, tool_categories, tools_admin
    assert "theprotocol_simulationFundingPreview" not in server_admin.ADMIN_TOOL_DISPATCH
    assert "theprotocol_simulationFundingPreview" not in {s["name"] for s in tools_admin.ADMIN_TOOL_SCHEMAS}
    assert not hasattr(tools_admin, "simulation_funding_preview")
    assert "simulationFundingPreview" not in str(vars(tool_categories))
    assert "theprotocol_issueFrameBSimulation" in server_admin.ADMIN_TOOL_DISPATCH, "the control stays"


def test_its_contract_reason_and_suite_rows_are_gone():
    from agentvault_registry.api_tests.contracts import refusal_reasons
    from agentvault_registry.api_tests.federation_suite import decorator, nothing_ceiling
    import agentvault_registry.api_tests.federation_suite.tests.test_simulation_deadman  # noqa: F401  registers its tests
    assert "theprotocol_simulationFundingPreview" not in refusal_reasons.BY_DESIGN_REFUSAL
    assert "simulation_funding_preview_reachable" not in {t.name for t in decorator.REGISTRY}
    assert "simulation_funding_preview_reachable" not in str(vars(nothing_ceiling))


def test_nothing_in_the_source_tree_names_it():
    """Every file under src/ (the registry, the contracts, the console, the generated route lists): no mention left."""
    hits = []
    for p in SRC.rglob("*"):
        if not p.is_file() or p.name in GUARDS or "node_modules" in p.parts or "dist" in p.parts or p.suffix not in (
                ".py", ".ts", ".vue", ".json", ".md", ".js"):
            continue
        text = p.read_text(errors="ignore")
        for n in NAMES:
            if n in text:
                hits.append(f"{p.relative_to(SRC)}: {n}")
    assert hits == []
