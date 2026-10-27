"""§MCPTEST30 (V0636): a pass that was only a refusal counts as not measured.

His question of 2026-10-19 ("is this like second calls on an endpoint that was already successfully tested ... because
this seems completely cheated otherwise") and his word of 2026-10-24 to close the gaps. V0635's run 9bc6416cf52d41c5
passed 204 tools on a refusal alone (a 404 for an agent that does not exist, and nothing else): 1207 of 1242 rows read
97.18%, 970 read 78.1%. A tool row that passed on a refusal while no passing row of the run answered 2xx for the same
tool (its own row, an `admin_effect:` row, a probe family's row) now counts as not measured, on the row, in the
not-measured list and in the summary, with the target's own count kept beside it.
"""
from __future__ import annotations

import inspect

from agentvault_registry.routers import mcp_tester
from agentvault_registry.routers.mcp_tester import (
    _REFUSAL_ONLY_REASON, _apply_refusal_only, _pass_depth, _refusal_only, _tool_base,
)


def _row(tool, status=200, healthy=True, skipped=False, skip_reason=None, switched_off=None, explicit=True):
    return {"tool": tool, "status": status, "healthy": healthy, "skipped": skipped, "skip_reason": skip_reason,
            "switched_off": switched_off, "has_explicit_contract": explicit}


def test_a_row_speaks_for_its_tool_whatever_its_family():
    assert _tool_base("theprotocol_rotateAgentCredentials") == "rotateAgentCredentials"
    assert _tool_base("admin_effect: rotateAgentCredentials") == "rotateAgentCredentials"
    assert _tool_base("refusal: rotateAgentCredentials unknown agent") == "rotateAgentCredentials"
    assert _tool_base("amount: transferUnits -0.01") == "transferUnits"
    assert _tool_base("hygiene: theprotocol_getOrgTrackRecord") == "getOrgTrackRecord"
    assert _tool_base("") == ""


def test_a_tool_whose_only_pass_is_a_refusal_is_refusal_only():
    rows = [
        _row("theprotocol_rotateAgentCredentials", 404),                      # its only test: refusal only
        _row("theprotocol_suspendAgent", 404), _row("admin_effect: suspendAgent", 200),   # the effect row earns it
        _row("theprotocol_getOrgTrackRecord", 404), _row("hygiene: getOrgTrackRecord", 200),
        _row("theprotocol_transferUnits", 200), _row("amount: transferUnits -0.01", 422),
        _row("theprotocol_forceMtlsEnroll", 422), _row("refusal: forceMtlsEnroll unknown agent", 404),
        _row("theprotocol_lockUnits", 403, switched_off="staking_enabled=false"),   # its switch's own account
        _row("theprotocol_failedTool", 500, healthy=False),                   # a failure stays a failure
        _row("theprotocol_skippedTool", 0, skip_reason="NOT MEASURED: no fixture"),
        _row("theprotocol_lostTool", 0),                                       # no 2xx: a refusal as _pass_depth reads it
        _row("theprotocol_noisyTool", 404), _row("theprotocol_noisyTool", 200, healthy=False),  # a failed 2xx earns nothing
    ]
    flagged = [rows[i]["tool"] for i in _refusal_only(rows)]
    assert flagged == ["theprotocol_rotateAgentCredentials", "theprotocol_forceMtlsEnroll", "theprotocol_lostTool",
                       "theprotocol_noisyTool"]
    assert _refusal_only(None) == [] and _refusal_only([]) == []


def test_the_summary_counts_them_as_not_measured_and_keeps_the_targets_count():
    rows = [_row("theprotocol_a", 404), _row("theprotocol_b", 200), _row("theprotocol_c", 404),
            _row("admin_effect: c", 200), _row("theprotocol_d", 422), _row("theprotocol_e", 500, healthy=False)]
    summary = {"tool_count": 6, "passed": 5, "skipped": 0, "failed": 1, "policy_denied": 0, "pass_pct": 83.33}
    skipped = [{"tool": "theprotocol_x", "reason": "NOT MEASURED: no fixture"}]
    assert _apply_refusal_only(rows, summary, skipped) == 2
    assert summary["refusal_only"] == 2
    assert (summary["passed"], summary["skipped"], summary["pass_pct"]) == (3, 2, 50.0)
    assert summary["target_counts"] == {"passed": 5, "skipped": 0, "pass_pct": 83.33}
    moved = [r for r in rows if r.get("refusal_only")]
    assert [r["tool"] for r in moved] == ["theprotocol_a", "theprotocol_d"]
    assert all(r["skipped"] and r["skip_reason"] == _REFUSAL_ONLY_REASON for r in moved)
    assert [s["tool"] for s in skipped] == ["theprotocol_x", "theprotocol_a", "theprotocol_d"]
    # pass_depth, read after, counts only the passes that remain: b's 2xx and c's refusal (c earned its 2xx through
    # its effect row, which is no tool row of pass_depth's)
    assert _pass_depth(rows) == {"success_contract": 1, "success_default": 0, "refusal_contract": 1,
                                 "refusal_default": 0}


def test_nothing_to_move_changes_no_count():
    rows = [_row("theprotocol_a", 200), _row("theprotocol_b", 404), _row("hygiene: b", 200)]
    summary = {"tool_count": 3, "passed": 3, "skipped": 0, "pass_pct": 100.0}
    assert _apply_refusal_only(rows, summary, []) == 0
    assert (summary["passed"], summary["skipped"], summary["pass_pct"], summary["refusal_only"]) == (3, 0, 100.0, 0)
    assert not any(r.get("refusal_only") for r in rows)


def test_the_sweep_applies_it_before_pass_depth_reads_the_passes():
    src = inspect.getsource(mcp_tester)
    call = "_apply_refusal_only(slim_results, summary, skipped)"
    depth = 'summary["pass_depth"] = _pass_depth(slim_results)'
    assert src.count(call) == 1 and src.count(depth) == 1
    assert src.index(call) < src.index(depth)
