"""§MCPSWEEP 2026-09-27: a lifecycle step must not fail the answer its tool's contract declares correct.

Measured on sbx-alpha (V0465 sweep, run 17d77598dd46419c): oauthIntrospect and oauthTokenExchange were the only two
hard failures. Both routes answer 501 "Cross-registry OAuth federation is not enabled on this registry" on a frame with
no trusted registry (a documented fail-closed fence), and both hand-curated contracts pin exactly that answer by its
sentence (`expect_status="error_5xx"`). But a lifecycle step called the same tools under `expect_status="any"`, which
fails every 5xx, and a lifecycle row decides the tool's result unless the contract sets `override_coverage_fan`. The
contract never ran. The step had read green only while its probe was malformed (the dispatcher refused it before the
tool ran); correcting the probe (WP-M3d) turned a declared answer into a hard failure.

The rule: no `_exec_step(..., expect_status="any")` may decide the row of a tool whose contract expects a 5xx, unless
that contract opts out of the lifecycle's verdict with `override_coverage_fan`. Tool names reach `_exec_step` either as
literals or through a loop over literal tool lists in the same function; both are collected.
"""
from __future__ import annotations

import ast
import pathlib

from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS

_CONTRACTS_DIR = (pathlib.Path(__file__).resolve().parent.parent
                  / "src" / "agentvault_registry" / "api_tests" / "contracts")
_LIFECYCLE_FILES = ("mcp_lifecycles.py", "mcp_admin_lifecycles.py")


def _any_status_tools(src: str) -> set:
    """Tools some `_exec_step` call runs under expect_status="any" and records as its own row."""
    out = set()
    tree = ast.parse(src)
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        # string literals naming tools anywhere in this function (the loops' tool lists)
        fn_tools = {n.value for n in ast.walk(fn)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("theprotocol_")}
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call)
                    and getattr(call.func, "id", getattr(call.func, "attr", "")) == "_exec_step"):
                continue
            kw = {k.arg: k.value for k in call.keywords}
            es = kw.get("expect_status")
            if not (isinstance(es, ast.Constant) and es.value == "any"):
                continue
            ras = kw.get("record_as_separate")
            if isinstance(ras, ast.Constant) and ras.value is False:
                continue  # a verification call that writes no row of its own
            if "verify_against_check" in kw:
                continue  # a probe is recorded only when it succeeded; a 5xx writes no row
            tool = call.args[2] if len(call.args) > 2 else kw.get("tool")
            if isinstance(tool, ast.Constant) and isinstance(tool.value, str):
                out.add(tool.value)
            else:
                out |= fn_tools
    return out


def _violations(any_tools: set) -> list:
    bad = []
    for tool in sorted(any_tools):
        c = MCP_CONTRACTS.get(tool)
        if c is not None and c.expect_status == "error_5xx" and not c.override_coverage_fan:
            bad.append(tool)
    return bad


def test_no_any_status_lifecycle_step_fails_a_declared_5xx():
    any_tools = set()
    for f in _LIFECYCLE_FILES:
        any_tools |= _any_status_tools((_CONTRACTS_DIR / f).read_text())
    assert len(any_tools) > 100, f"the scan found only {len(any_tools)} tools; it is not reading the lifecycles"
    bad = _violations(any_tools)
    assert not bad, (
        "these tools' contracts declare a 5xx as the correct answer, but a lifecycle step calls them under "
        "expect_status='any' (which fails every 5xx) and its row wins over the contract: "
        f"{bad}. Let the contract decide (drop the step, or set override_coverage_fan on the contract).")


def test_the_scan_sees_a_violation_when_one_exists():
    """Control: a synthetic lifecycle calling a tool whose contract expects a 5xx is reported."""
    declared = sorted(t for t, c in MCP_CONTRACTS.items()
                      if c.expect_status == "error_5xx" and not c.override_coverage_fan)
    assert declared, "no contract expects a 5xx without override; the control has nothing to plant"
    tool = declared[0]
    literal = (
        "async def lifecycle_x(rpc, parse, bag, outcomes):\n"
        f"    await _exec_step(rpc, parse, {tool!r}, '3', {{}}, bag.developer_jwt, outcomes, expect_status='any')\n")
    looped = (
        "async def lifecycle_y(rpc, parse, bag, outcomes):\n"
        f"    for tool, args in [({tool!r}, {{}})]:\n"
        "        await _exec_step(rpc, parse, tool, 'admin', args, bag.developer_jwt, outcomes, expect_status='any')\n")
    assert _violations(_any_status_tools(literal)) == [tool]
    assert _violations(_any_status_tools(looped)) == [tool]
    # and a step that asks the contract's own question is not reported
    asked = literal.replace("expect_status='any'", "expect_status='error_5xx'")
    assert _violations(_any_status_tools(asked)) == []
