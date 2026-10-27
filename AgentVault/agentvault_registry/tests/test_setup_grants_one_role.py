"""§MCPTEST30 (V0551): the tester's setup grants governor through the one-role rail, never the whole-set PUT.

PUT /agents/{did}/authz replaces an agent's role set and stamps every grant with the call's one expiry, so a setup that
read the roles and PUT their union back could make a time-limited role permanent (agentvault2-0f's finding; the rail
POST /agents/{did}/authz/roles, agentvault2-33, V0551 (2), grants one role and leaves every other grant as it is). The
setup's helper is read from the flow's own source.
"""
from __future__ import annotations

import ast
from pathlib import Path

FLOW = (Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "api_tests" / "categories"
        / "flow_mcp_lifecycle" / "test_flow_mcp_lifecycle.py")


def _helper_source(src: str, name: str) -> str:
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    return ""


def test_the_setup_grants_governor_through_the_one_role_rail():
    body = _helper_source(FLOW.read_text(), "_ensure_governor")
    assert body, "the setup's governor helper is gone"
    assert "/authz/roles" in body and '"role": "governor"' in body
    assert "-X PUT" not in body, "the whole-set PUT is back in the setup"
    src = FLOW.read_text()
    assert src.count("await _ensure_governor(") == 2, "the sentinel and the second agent"


def test_the_control_tells_a_put_apart():
    put = 'async def _ensure_governor(did):\n    cmd = "curl -X PUT http://localhost:8000/api/v1/agents/x/authz"\n'
    body = _helper_source(put, "_ensure_governor")
    assert body and "-X PUT" in body and "/authz/roles" not in body
