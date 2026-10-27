"""§MCPTEST30 (V0549): the run summary says how deep its passes reach.

Round 15's strict run on V0547 counted 1,160 passes. Its 705 passing tool rows were four different readings: a 2xx
against a contract a person wrote (374), a 2xx against the default contract (132: the tool answered, its shape went
unchecked), a refusal a written contract pins (100), and a refusal under the default contract (99: §FANCLAIM's thin
coverage, the tool dispatched and its route refused the sweep's nonexistent target). `pass_depth` counts each, so the
headline can say which.
"""
from __future__ import annotations

from agentvault_registry.routers.mcp_tester import _pass_depth


def _row(tool="theprotocol_x", status=200, explicit=True, healthy=True, skipped=False, skip_reason=None):
    return {"tool": tool, "status": status, "has_explicit_contract": explicit, "healthy": healthy,
            "skipped": skipped, "skip_reason": skip_reason}


def test_each_kind_of_pass_is_counted_once():
    rows = [_row(), _row(status=201), _row(explicit=False), _row(status=404), _row(status=401),
            _row(status=422, explicit=False), _row(status=0, explicit=False)]
    assert _pass_depth(rows) == {"success_contract": 2, "success_default": 1, "refusal_contract": 2,
                                 "refusal_default": 2}


def test_what_is_not_a_passing_tool_row_is_outside_it():
    rows = [_row(healthy=False), _row(skipped=True), _row(skip_reason="NOT MEASURED: no fixture"),
            _row(tool="federation_suite: c/t"), _row(tool="filter: getCollusionRings"), {}]
    assert _pass_depth(rows) == {"success_contract": 0, "success_default": 0, "refusal_contract": 0,
                                 "refusal_default": 0}
    assert _pass_depth(None) == _pass_depth([])
