"""§MCPTEST30 (V0536, 2026-10-01): every outcome the cloud-op sweep counts is a row the console shows.

Measured on round 10's cloud-op alpha run (9b5d52c12a3048ea): the summary counted 750 rows and 658 passes, the run held
749 rows and 657 passes. The missing one was token_scope_row (V0529: an operator admin's token asked at its parent frame,
which must refuse it). `_run_cloudop_mcp_sweep` formats `outcomes` into `results` at its step 6 and the console shows
`results`; the token-scope outcome was appended after that loop, so it was counted and never shown, and a BUG-FIND there
would have read as one failure with no row naming it.

The sweep now formats a late outcome where it appends it, through one formatter. Test 2 is the class: after the
formatting loop, every outcome appended has its own formatted row (an extend or a reassignment there has none); test 3
is its control, the V0535 shape, which the same check refuses.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F


def _is_row_call(node) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_cloudop_result_row"


def _method_call(node, obj: str, meths):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
            and node.func.value.id == obj and node.func.attr in meths)


def late_outcomes_without_rows(func_src: str):
    """Lines that change `outcomes` after the formatting loop without a formatted row of their own."""
    fn = ast.parse(textwrap.dedent(func_src)).body[0]
    loops = [n.lineno for n in ast.walk(fn)
             if isinstance(n, ast.For) and isinstance(n.iter, ast.Name) and n.iter.id == "outcomes"
             and any(_method_call(c, "results", ("append",)) and c.args and _is_row_call(c.args[0]) for c in ast.walk(n))]
    assert loops, "no loop formats `outcomes` into `results` through _cloudop_result_row"
    loop_line = max(loops)
    rows = [(n.lineno, ast.dump(n.args[0].args[1])) for n in ast.walk(fn)
            if _method_call(n, "results", ("append",)) and n.args and _is_row_call(n.args[0]) and len(n.args[0].args) > 1]
    missing = []
    for n in ast.walk(fn):
        if getattr(n, "lineno", 0) <= loop_line:
            continue
        if _method_call(n, "outcomes", ("append",)) and n.args:
            arg = ast.dump(n.args[0])
            if not any(line > n.lineno and a == arg for line, a in rows):
                missing.append(n.lineno)
        elif _method_call(n, "outcomes", ("extend", "insert")):
            missing.append(n.lineno)
        elif isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            if any(isinstance(t, ast.Name) and t.id == "outcomes" for t in targets):
                missing.append(n.lineno)
    return missing


def test_the_formatter_carries_the_outcome():
    o = F.ContractOutcome(tool_name=F.TOKEN_SCOPE_ROW, contract_tier="protocol", healthy=True, status_code=401,
                          elapsed_ms=12, skip_reason=None, fail_reason=None, has_explicit_contract=True, args_used={},
                          result_excerpt={"answered": False, "refused": True})
    row = F._cloudop_result_row("sandboxalpha", o, 750)
    assert row["step"] == 750 and row["healthy"] is True and row["statusCode"] == 401
    assert row["responseData"]["tool"] == F.TOKEN_SCOPE_ROW and row["responseData"]["operator"] == "sandboxalpha"
    assert row["expected_failure"] is False and row["error"] is None and row["authRequired"] == "admin"
    skipped = F._cloudop_result_row("sandboxalpha", F.ContractOutcome(
        tool_name="theprotocol_getMyAgents", contract_tier="3", healthy=False, status_code=0, elapsed_ms=0,
        skip_reason="NOT MEASURED: x", fail_reason=None, has_explicit_contract=False, args_used={}, result_excerpt={}), 1)
    assert skipped["expected_failure"] is True and skipped["authRequired"] == "developer"


def test_every_outcome_after_the_formatting_loop_has_its_row():
    """THE CLASS: the console shows `results`, the summary counts `outcomes`; nothing counted goes unshown."""
    src = inspect.getsource(F.TestFlowMcpLifecycle._run_cloudop_mcp_sweep)
    assert late_outcomes_without_rows(src) == []
    assert "token_scope_row(op, dev_jwt)" in src


def test_the_v0535_shape_is_refused():
    """The control: the token-scope outcome appended after the loop with no row of its own (V0529 to V0535)."""
    old = '''
    async def _run_cloudop_mcp_sweep(self, operator_label):
        outcomes = []
        results = []
        outcomes.extend(bucket)
        for o in outcomes:
            results.append(_cloudop_result_row(op.label, o, len(results) + 1))
        outcomes.append(await token_scope_row(op, dev_jwt))
    '''
    assert len(late_outcomes_without_rows(old)) == 1
    fixed = old.replace("        outcomes.append(await token_scope_row(op, dev_jwt))\n",
                        "        _s = await token_scope_row(op, dev_jwt)\n        outcomes.append(_s)\n"
                        "        results.append(_cloudop_result_row(op.label, _s, len(results) + 1))\n")
    assert late_outcomes_without_rows(fixed) == []
