"""§MCPTEST30 (V0539): an MCP sweep's rows fall in four disjoint classes that add up to its row count.

A tool a standing rule forbids the tester to call (its skip_reason carries core.policy_marks.POLICY_DENIED_MARK) was
counted as a pass whenever the path that skipped it had set `healthy`: the admin lifecycle's guard does, a contract's
skip_reason does not, so 19 of a run's 20 such rows were passes and the 20th was not. Measured on EU's history
2026-10-01: strict run 8a6ad7313a8f4666 recorded passed 1157 of 1184 rows = 1138 called + 19 never called, and its four
counts summed to 1203. `outcome_counts` is the one place both summaries (the strict sweep and the cloud operator sweep)
read, and a row that was not called is never a pass.
"""
from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import outcome_counts
from agentvault_registry.api_tests.contracts.mcp_admin_lifecycles import _record_never_invoke_skip
from agentvault_registry.core.policy_marks import POLICY_DENIED_MARK

FLOW = (pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "api_tests" / "categories"
        / "flow_mcp_lifecycle" / "test_flow_mcp_lifecycle.py")


def _row(healthy: bool, skip_reason: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(healthy=healthy, skip_reason=skip_reason)


def test_a_rule_refusal_is_never_a_pass_whatever_its_healthy_flag():
    rows = [
        _row(True),                                                     # called and passed
        _row(False),                                                    # called and failed
        _row(False, "fixture missing: ['proposal_id']"),                # not measured
        _row(True, f"{POLICY_DENIED_MARK} — provisions real infra"),    # the admin guard's shape: healthy and refused
        _row(False, f"{POLICY_DENIED_MARK} — DESTRUCTIVE"),             # a contract's shape: refused, not healthy
    ]
    c = outcome_counts(rows)
    assert c == {"total": 5, "passed": 1, "skipped": 1, "policy_denied": 2, "failed": 1}
    assert c["passed"] + c["skipped"] + c["policy_denied"] + c["failed"] == c["total"]


def test_the_admin_guard_records_the_shape_that_was_counted_as_a_pass():
    """The control: the guard really does write `healthy=True` beside the mark (so the old `sum(o.healthy)` counted it)."""
    out: dict = {}
    _record_never_invoke_skip("theprotocol_startSimulation", out)
    row = out["theprotocol_startSimulation"]
    assert row["healthy"] is True and POLICY_DENIED_MARK in row["skip_reason"]
    c = outcome_counts([SimpleNamespace(**{"healthy": row["healthy"], "skip_reason": row["skip_reason"]})])
    assert c["passed"] == 0 and c["policy_denied"] == 1


def test_a_skipped_row_that_says_healthy_is_skipped_once():
    c = outcome_counts([_row(True, "NOT MEASURED: one page where two were needed")])
    assert c == {"total": 1, "passed": 0, "skipped": 1, "policy_denied": 0, "failed": 0}


def test_both_summaries_read_the_helper_and_no_other_pass_count():
    """The strict sweep and the cloud operator sweep each set passed/skipped/policy_denied/failed from outcome_counts;
    neither counts `o.healthy` itself any more (an AST walk, so a comment naming the old form cannot satisfy it)."""
    tree = ast.parse(FLOW.read_text())
    helper_reads = 0
    stray = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "outcome_counts":
            helper_reads += 1
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "sum":
            gen = node.args[0] if node.args else None
            if isinstance(gen, ast.GeneratorExp):
                for comp in gen.generators:
                    for cond in comp.ifs:
                        src = ast.unparse(cond)
                        if "o.healthy" in src:
                            stray.append(f"line {node.lineno}: {src}")
    assert helper_reads == 2, f"outcome_counts called {helper_reads} times (want the two summaries)"
    assert stray == [], f"a summary still counts healthy itself: {stray}"
