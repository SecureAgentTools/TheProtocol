"""V0666 Tests package A (session-lead seq 4442, his rule "failed is failed"): a pinned tool's failed lifecycle row
is never dropped.

A sweep consults a lifecycle row by tool name, and where the tool's contract pins a refusal (override_coverage_fan) it
runs that contract instead; kept_lifecycle_rows (V0636) kept the lifecycle's row beside it only when it was a real
success, so a failure was dropped with no red anywhere. Measured on the V0664 pair (nt261115x3): triggerDiagnosticAction's
dry run on an operator was judged by the wrong rule, the check downgraded the row, and the run read "refusal only, by
design" with 0 failed. Now a failed row (not healthy, no named skip) is kept as `earned: <tool>` and reads FAIL; where a
pin exists to quiet a known red, the contract declares it (`known_red`), and the row carries the declaration into the
run's expected reds, visible with its reason. A named skip is still not counted (the pinned refusal row stands).
Red on 146acef6c.
"""
from __future__ import annotations

import inspect

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as runner
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import (
    ContractOutcome, kept_lifecycle_rows,
)
from agentvault_registry.api_tests.contracts.mcp_contracts import McpContract


def _row(code=200, healthy=True, skip=None, fail=None):
    return {"healthy": healthy, "status_code": code, "skip_reason": skip, "fail_reason": fail}


PINNED = {"theprotocol_triggerDiagnosticAction", "theprotocol_suspendAgent", "theprotocol_runAllDiagnostics"}


def test_a_pinned_tools_failed_lifecycle_row_is_kept_and_reads_fail():
    rows = {"theprotocol_triggerDiagnosticAction": _row(200, healthy=False, fail="BUG-FIND: the dry run acted")}
    kept = dict(kept_lifecycle_rows(rows, set(rows), set(), lambda n: n in PINNED))
    assert list(kept) == ["earned: triggerDiagnosticAction"]
    assert kept["earned: triggerDiagnosticAction"]["healthy"] is False
    assert "the dry run acted" in kept["earned: triggerDiagnosticAction"]["fail_reason"]
    assert not kept["earned: triggerDiagnosticAction"].get("expected_red")


def test_a_named_skip_is_still_not_counted():
    rows = {"theprotocol_triggerDiagnosticAction": _row(0, healthy=False, skip="NOT MEASURED: no operator target")}
    assert kept_lifecycle_rows(rows, set(rows), set(), lambda n: n in PINNED) == []


def test_a_declared_known_red_travels_with_the_failed_row():
    rows = {"theprotocol_suspendAgent": _row(200, healthy=False, fail="the agent still reads active")}
    known = {"theprotocol_suspendAgent": "D6-999: the suspension is read from a cache for 60 s"}
    kept = dict(kept_lifecycle_rows(rows, set(rows), set(), lambda n: n in PINNED, known_red=known.get))
    assert kept["earned: suspendAgent"]["expected_red"] == known["theprotocol_suspendAgent"]
    assert kept["earned: suspendAgent"]["healthy"] is False


def test_a_success_is_never_given_a_known_red():
    rows = {"theprotocol_runAllDiagnostics": _row(200)}
    kept = dict(kept_lifecycle_rows(rows, set(rows), set(), lambda n: n in PINNED, known_red=lambda n: "a finding"))
    assert kept["earned: runAllDiagnostics"]["healthy"] is True and not kept["earned: runAllDiagnostics"].get("expected_red")


def test_the_contract_declares_it_and_the_result_row_carries_it_where_the_router_reads_it():
    assert "known_red" in McpContract.__dataclass_fields__
    assert "expected_red" in ContractOutcome.__dataclass_fields__
    src = inspect.getsource(runner)
    # every sweep that keeps lifecycle rows passes the contracts' declarations and keeps them on the outcome
    assert src.count("known_red=lambda n: get_contract(n).known_red") == src.count("kept_lifecycle_rows(") - 1
    assert src.count('expected_red=_d.get("expected_red")') == src.count("kept_lifecycle_rows(") - 1
    # the router lists a failed row as red by design when responseData carries the declaration (mcp_tester._hard_fail_row)
    assert '"expected_red": o.expected_red' in src
