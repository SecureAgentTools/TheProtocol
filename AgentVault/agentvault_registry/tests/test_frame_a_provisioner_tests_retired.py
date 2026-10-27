"""§NIGHTLYPROV 2026-09-27: the Frame-A-era provisioner tests are RETIRED, never revived (his decision, "1 yes").

The sandbox provisioner-lifecycle test, the chained-frame and dual-frame lifecycle tests and the cross-registry transfer
test drove retired Frame-A hosts, bypassed the rails (psql writes, a direct TEG mint: the delta-breach shape) and could
not pass today's template validation. Their routers, their 11 MCP admin tools, the API tester's proxies and three flows
built on them, the two tester tabs and their ENABLE_SANDBOX_PROVISIONER_TEST gate went together. Provisioning is now
tested every night on a throwaway pair (stack scripts/nightly/). This gate keeps each half from coming back alone:
it reads string CONSTANTS and imports on the AST (a comment or a docstring that names the history is allowed), and the
dispatch tables through the modules themselves.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
FE = SRC / "static" / "new_registry_frontend" / "src"

RETIRED_MODULES = ("sandbox_provisioner_test", "chained_frame_lifecycle_test", "dual_frame_lifecycle_test",
                   "cross_reg_transfer_test")
RETIRED_PATHS = ("/admin/sandbox/provisioner-lifecycle-test", "/admin/sandbox/operator-teardown",
                 "/admin/frame/chained-lifecycle-", "/admin/frame/dual-frame-", "/admin/frame/cross-reg-transfer-test",
                 "/admin/api-test/chained-lifecycle-", "/admin/api-test/dual-frame-")
RETIRED_TOOLS = ("sandboxProvisionerLifecycleTest", "chainedLifecycleTest", "chainedLifecycleTeardown",
                 "chainedLifecycleStatus", "dualFrameLifecycleTest", "dualFrameLifecycleTeardown",
                 "getDualFrameLifecycleStatus", "dualFrameApiTester", "getDualFrameApiTesterStatus",
                 "crossRegTransferTest", "sandboxOperatorTeardown")
RETIRED_FLOWS = ("flow_provisioned_operator_reactors", "flow_operator_lifecycle_destructive_reactors",
                 "flow_provisioning_status_healthcheck")
RETIRED_FLAG = "ENABLE_SANDBOX_PROVISIONER_TEST"


def _is_retired_path(value: str) -> bool:
    v = value.strip()
    v = v[len("/api/v1"):] if v.startswith("/api/v1/") else v
    return any(v.startswith(p) for p in RETIRED_PATHS)


def offences(source: str) -> list:
    """Every string constant that IS a retired route, tool, flow or the flag, and every import of a retired router."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value.strip()
            name = v[len("theprotocol_"):] if v.startswith("theprotocol_") else v
            if _is_retired_path(v) or name in RETIRED_TOOLS or v in RETIRED_FLOWS or v == RETIRED_FLAG:
                out.append((node.lineno, v))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
            if any(n.split(".")[-1] in RETIRED_MODULES for n in names if n):
                out.append((node.lineno, f"import {names}"))
    return out


def test_the_retired_routers_are_gone():
    for m in RETIRED_MODULES:
        assert not (SRC / "routers" / f"{m}.py").exists(), m


def test_no_python_source_serves_calls_or_gates_on_a_retired_test():
    found = {}
    for p in sorted(SRC.rglob("*.py")):
        if "/static/" in str(p) or "/alembic/" in str(p):
            continue
        hits = offences(p.read_text(encoding="utf-8"))
        if hits:
            found[str(p.relative_to(SRC))] = hits
    assert not found, found


def test_the_admin_mcp_server_offers_none_of_the_retired_tools():
    from agentvault_registry.mcp import server_admin, tools_admin
    names = set(server_admin.ADMIN_TOOL_DISPATCH)
    schemas = {s["name"] for s in tools_admin.ADMIN_TOOL_SCHEMAS}
    assert len(names) > 200 and len(schemas) > 200, (len(names), len(schemas))  # the tables were read, not empty
    for t in RETIRED_TOOLS:
        assert f"theprotocol_{t}" not in names and f"theprotocol_{t}" not in schemas, t


def test_the_frontend_neither_mounts_nor_calls_them():
    for c in ("ChainedFrameLifecycleTab.vue", "DualFrameLifecycleTab.vue"):
        assert not (FE / "components" / c).exists(), c
    found = []
    for p in list(FE.rglob("*.ts")) + list(FE.rglob("*.vue")):
        text = p.read_text(encoding="utf-8")
        found += [(str(p.relative_to(FE)), r) for r in RETIRED_PATHS if r in text]
    assert not found, found


@pytest.mark.parametrize("planted", [
    'x = "/api/v1/admin/frame/chained-lifecycle-test"',
    'router = APIRouter(prefix="/admin/sandbox/provisioner-lifecycle-test")',
    'DISPATCH = {"theprotocol_crossRegTransferTest": f}',
    'FLOWS = ("flow_provisioned_operator_reactors",)',
    'import os\nos.getenv("ENABLE_SANDBOX_PROVISIONER_TEST")',
    "from agentvault_registry.routers import dual_frame_lifecycle_test",
])
def test_control_each_shape_is_caught(planted):
    assert offences(planted), planted


def test_control_history_in_prose_is_allowed():
    """A comment or a docstring that names the retired tests is the record of why they are gone, not a revival."""
    src = ('"""The retired `sandboxProvisionerLifecycleTest` and ENABLE_SANDBOX_PROVISIONER_TEST=true."""\n'
           "# /admin/frame/chained-lifecycle-test was retired\n")
    assert offences(src) == []
