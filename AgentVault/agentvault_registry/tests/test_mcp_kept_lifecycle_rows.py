"""§MCPTEST30 (V0636): a sweep keeps what its lifecycles measured, beside its own rows.

The sweeps consult a lifecycle row by tool name, and where the tool's contract pins a refusal (override_coverage_fan)
they run that contract instead: a real success a lifecycle measured under the tool's name was thrown away (V0635: the
command centre's runAllDiagnostics, runDiagnosticsSubset and triggerDiagnosticAction on the frame itself read
refusal-only). And the admin sweep dropped every lifecycle row that names no tool. kept_lifecycle_rows keeps the first
as `earned: <tool>` and the second under its own name, never twice.
"""
from __future__ import annotations

import inspect

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as runner
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import (
    _SYNTHETIC_ROW_PREFIXES, kept_lifecycle_rows,
)


def _row(code=200, healthy=True, skip=None):
    return {"healthy": healthy, "status_code": code, "skip_reason": skip}


def test_a_pinned_tools_real_success_is_kept_as_earned_and_nothing_else_of_a_listed_tool():
    rows = {
        "theprotocol_runAllDiagnostics": _row(200),                     # pinned, a real success: kept as earned
        "theprotocol_runDiagnosticsSubset": _row(404),                  # pinned, a refusal: the pinned row stands alone
        "theprotocol_getAdminDashboard": _row(200),                     # not pinned: the sweep reads it itself
        "theprotocol_triggerDiagnosticAction": _row(200, skip="NOT MEASURED: no target"),
        "theprotocol_suspendAgent": _row(200, healthy=False),
    }
    listed = set(rows)
    pinned = {"theprotocol_runAllDiagnostics", "theprotocol_runDiagnosticsSubset",
              "theprotocol_triggerDiagnosticAction", "theprotocol_suspendAgent"}
    kept = kept_lifecycle_rows(rows, listed, set(), lambda n: n in pinned)
    assert [n for n, _ in kept] == ["earned: runAllDiagnostics"]


def test_a_row_named_for_no_tool_is_kept_once_and_an_unknown_name_never():
    rows = {"admin_effect: suspendAgent": _row(200), "refusal: suspendAgent an agent that does not exist": _row(404),
            "nosuchfamily: x": _row(200), "zk v2: the catalog": _row(200)}
    kept = kept_lifecycle_rows(rows, set(), {"zk v2: the catalog"}, lambda n: False)
    assert [n for n, _ in kept] == ["admin_effect: suspendAgent", "refusal: suspendAgent an agent that does not exist"]


def test_earned_rows_are_kept_by_the_runner_and_both_sweeps_use_the_one_rule():
    assert "earned: " in _SYNTHETIC_ROW_PREFIXES
    src = inspect.getsource(runner)
    # the central sweep and, since V0637, the cloud-operator sweep (its earned lifecycles): each keeps its public and
    # its admin lifecycle rows through the one rule
    assert src.count("kept_lifecycle_rows(lifecycle_outcomes,") == 2
    assert src.count("kept_lifecycle_rows(admin_lifecycle_outcomes,") == 2
