"""§MCPTEST30 (V0641): a tool switched off on an operator that passed its own contract on the refusal is not measured.

The operator sweep's gate classifier reads only rows that FAILED their contract, and the healthy-refusal branch beside it
(cloudop_by_design_refusal) takes the mainframe-only words only, so a tool the operator says is off passed on its
refusal alone: oauthIntrospect, oauthRevoke and oauthTokenExchange on both sandbox operators, 501 "Cross-registry OAuth
federation is not enabled on this registry (no active trusted registries configured)" (V0639's read, 2026-10-25).
Pinned: such a row becomes NOT MEASURED with the classifier's own flag-gated sentence; a mainframe-only refusal, a
refusal naming no such phrase, a 2xx, a row already skipped or failing, and a `refusal: ` row are left to the rest of
the loop; the loop calls it after the by-design branch.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.routers import mcp_tester as mt

_OAUTH_501 = ("Error: HTTP 501: Cross-registry OAuth federation is not enabled on this registry (no active trusted "
              "registries configured).")


def _o(tool="theprotocol_oauthIntrospect", healthy=True, status=501, skip=None, text=_OAUTH_501):
    return F.ContractOutcome(tool_name=tool, contract_tier="3", healthy=healthy, status_code=status, elapsed_ms=5,
                             skip_reason=skip, fail_reason=None, has_explicit_contract=True, args_used={},
                             result_excerpt={"_text": text})


def test_a_passing_refusal_that_says_the_feature_is_off_is_not_measured():
    out = F.cloudop_switched_off_refusal(_o())
    assert out is not None and out.healthy is False and out.status_code == 501
    assert out.skip_reason == F.cloudop_flag_gated_reason("is not enabled on this registry", 501)
    assert "the feature is off on this node" in out.skip_reason
    assert out.result_excerpt["_text"] == _OAUTH_501


@pytest.mark.parametrize("o", [
    _o(text="Error: HTTP 404: mainframe_only: revokeFrame runs on a frame's mainframe"),  # the by-design branch's
    _o(text="Error: HTTP 501: not implemented"),                                           # no phrase: left as it is
    _o(status=200, text="is not enabled on this registry, but answered 200"),
    _o(skip="NOT MEASURED: something else"),
    _o(healthy=False),
    _o(tool="refusal: oauthIntrospect a token that was never issued"),
])
def test_everything_else_is_left_as_it_is(o):
    assert F.cloudop_switched_off_refusal(o) is None


def test_the_phrases_are_the_gate_classifiers_own():
    assert set(F.CLOUDOP_SWITCHED_OFF_MARKERS) <= set(F.CLOUDOP_GATE_MARKERS)
    assert not set(F.CLOUDOP_SWITCHED_OFF_MARKERS) & set(F.CLOUDOP_BY_CONSTRUCTION_MARKERS)


def test_the_router_leaves_its_reason():
    row = F.cloudop_switched_off_refusal(_o())
    as_router_reads = {"tool": row.tool_name, "tier": "3", "healthy": row.healthy, "status": row.status_code,
                       "skip_reason": row.skip_reason, "switched_off": None}
    assert mt._refusal_only([as_router_reads]) == []


def test_the_loop_calls_it_after_the_by_design_branch_and_both_say_the_same_sentence():
    tree = ast.parse(textwrap.dedent(inspect.getsource(F.TestFlowMcpLifecycle._run_cloudop_mcp_sweep)))
    calls = {n.lineno: getattr(n.func, "id", "") for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") in ("cloudop_by_design_refusal", "cloudop_switched_off_refusal",
                                                "cloudop_flag_gated_reason")}
    names = sorted(calls.values())
    assert names.count("cloudop_switched_off_refusal") == 1 and names.count("cloudop_flag_gated_reason") == 1
    by_design = next(k for k, v in calls.items() if v == "cloudop_by_design_refusal")
    switched = next(k for k, v in calls.items() if v == "cloudop_switched_off_refusal")
    assert by_design < switched
    for n in ast.walk(tree):
        if isinstance(n, ast.If) and "not o.healthy" in ast.unparse(n.test) and "not o.skip_reason" in ast.unparse(n.test):
            assert any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "cloudop_switched_off_refusal"
                       for e in n.orelse for c in ast.walk(e))


@pytest.mark.parametrize("tool,status,text,phrase", [
    ("theprotocol_executeTutorial", 503,
     "Error: HTTP 503: No tutorial sandbox is configured on this registry (API_TEST_TARGET_URL is unset); the "
     "Tutorials run on a frame that has one", "no tutorial sandbox is configured"),
    ("theprotocol_adminGrafanaQuery", 400,
     "Error: Grafana credentials not configured: set GRAFANA_ADMIN_PASS (the password of Grafana's admin user) in this "
     "registry's environment. No request was sent.", "grafana credentials not configured"),
])
def test_the_v0641_preview_switched_off_words_are_not_measured(tool, status, text, phrase):
    """§MCPTEST30 (V0641): the V0641 operator preview's two rows that pass on a refusal saying the feature is not
    configured on the operator (the words as measured, 2026-10-25 09:5xZ)."""
    out = F.cloudop_switched_off_refusal(_o(tool=tool, status=status, text=text))
    assert out is not None and out.healthy is False
    assert out.skip_reason == F.cloudop_flag_gated_reason(phrase, status)
