"""§MCPTEST30 (V0641): a mainframe-only tool that passed its own contract on an operator's refusal is said by design.

The operator sweep's gate classifier reads only rows that FAILED their contract, and since a3fd8761 it says a
mainframe-only refusal by construction NOT MEASURED by design. A tool whose contract accepts the refusal passed on it
alone instead, and the tester router gave it the generic refusal-only sentence: most of the 45 admin rows per operator
left after V0640's second preview (2026-10-25 01:56-02:05Z). Pinned: such a row becomes NOT MEASURED by design with
the operator's words and keeps its verified refusal; a refusal naming no such phrase, a 2xx, a row already skipped or
failing, and every lifecycle-family row (a `refusal: ` row is a measurement) are left as they are; the classifier
loop calls it for the rows it does not otherwise read.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.routers import mcp_tester as mt


def _o(tool="theprotocol_revokeFrame", healthy=True, status=404, skip=None,
       excerpt=None):
    return F.ContractOutcome(tool_name=tool, contract_tier="admin", healthy=healthy, status_code=status,
                             elapsed_ms=5, skip_reason=skip, fail_reason=None, has_explicit_contract=True,
                             args_used={}, result_excerpt=excerpt if excerpt is not None else {
                                 "_text": "Error: HTTP 404: mainframe_only: revokeFrame runs on a frame's mainframe"})


def test_a_passing_refusal_by_construction_is_said_by_design():
    out = F.cloudop_by_design_refusal(_o())
    assert out is not None and out.healthy is False
    assert out.skip_reason == F.cloudop_by_construction_reason("mainframe_only:", 404)
    assert "verified_refusal" in out.result_excerpt and out.result_excerpt["_text"].startswith("Error: HTTP 404")


@pytest.mark.parametrize("o", [
    _o(excerpt={"_text": "Error: HTTP 503: service unavailable"}),   # a bare 503: its cause cannot be told
    _o(status=200, excerpt={"_text": "mainframe_only: but answered 200"}),
    _o(skip="NOT MEASURED: something else"),
    _o(healthy=False),
    _o(tool="refusal: revokeFrame a frame that does not exist"),
    _o(tool="earned: revokeFrame"),
])
def test_everything_else_is_left_as_it_is(o):
    assert F.cloudop_by_design_refusal(o) is None


def test_the_phrases_are_the_gate_classifiers_own():
    assert set(F.CLOUDOP_BY_CONSTRUCTION_MARKERS) <= set(F.CLOUDOP_GATE_MARKERS) | {
        "sovereign mainframe", "runs on mainframe", "mainframe admins", "cloud-operators federate",
        "fiat onramp is mainframe", "mainframe-only", "this feature runs on"}
    assert "mainframe_only:" in F.CLOUDOP_BY_CONSTRUCTION_MARKERS


def test_the_router_leaves_its_reason():
    row = F.cloudop_by_design_refusal(_o())
    as_router_reads = {"tool": row.tool_name, "tier": "admin-bridge", "healthy": row.healthy,
                       "status": row.status_code, "skip_reason": row.skip_reason, "switched_off": None}
    assert mt._refusal_only([as_router_reads]) == []


def test_the_classifier_loop_calls_it_for_the_rows_it_does_not_otherwise_read():
    tree = ast.parse(textwrap.dedent(inspect.getsource(F.TestFlowMcpLifecycle._run_cloudop_mcp_sweep)))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "cloudop_by_design_refusal"]
    assert len(calls) == 1
    # it sits in the `else` of the loop's `if (not o.healthy) and (not o.skip_reason)`
    hits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.If) and "not o.healthy" in ast.unparse(n.test) and "not o.skip_reason" in ast.unparse(n.test):
            hits.append(any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "cloudop_by_design_refusal"
                            for e in n.orelse for c in ast.walk(e)))
    assert hits == [True]
