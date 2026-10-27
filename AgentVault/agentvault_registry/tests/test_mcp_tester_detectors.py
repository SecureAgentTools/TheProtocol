"""§MCPTEST30 (V0541): a drift detector a suite did not run is recorded as not measured, never as clean.

The run's summary defaulted every detector's count to 0 whatever the suite ran, and the tester page read 0 as clean:
on EU's history (2026-10-02) a federation run read "wrong-tier accepts: 0 of 0" under "every tool rejects the wrong
tier", the cloud-op sweeps (which declare F3 and F4 off) read "wrappers match their routes", and every row of every
run carried "rejected all 3 wrong-tier credentials" (586 of 586 on the federation run, which probes none). The suite
now says what each detector measured, the summary names it (`detectors`), and a row passes an axis only where its
detector measured that tool.
"""
from __future__ import annotations

import ast
import pathlib

from agentvault_registry.routers import mcp_tester as mt

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
FLOW = SRC / "api_tests" / "categories" / "flow_mcp_lifecycle" / "test_flow_mcp_lifecycle.py"
ROUTER = SRC / "routers" / "mcp_tester.py"

STRICT = {"wrapper_drift_measured": True, "wrapper_drift": 0, "cross_frame_compared": 23, "cross_frame_drift": 0,
          "auth_matrix_total": 396}
CLOUD_OP = {"skip_axes_disabled": ["lifecycles", "F3_wrapper_drift", "F4_cross_frame_parity"], "auth_matrix_total": 396}


def test_each_detector_counts_as_measured_only_by_its_own_evidence():
    assert mt._detectors_measured(STRICT) == {"wrapper_route": True, "cross_frame": True, "auth_matrix": True}
    # the cloud-op sweep runs the matrix and declares the other two off
    assert mt._detectors_measured(CLOUD_OP) == {"wrapper_route": False, "cross_frame": False, "auth_matrix": True}
    # the federation suite runs none: no count of its own, the 0 the summary wrote was a default
    assert mt._detectors_measured({"auth_matrix_total": 0}) == {"wrapper_route": False, "cross_frame": False,
                                                                 "auth_matrix": False}
    assert mt._detectors_measured(None) == {"wrapper_route": False, "cross_frame": False, "auth_matrix": False}


def test_a_check_that_could_not_read_the_routes_and_a_walk_that_compared_nothing_measured_nothing():
    assert mt._detectors_measured({**STRICT, "wrapper_drift_measured": False})["wrapper_route"] is False
    assert mt._detectors_measured({**STRICT, "cross_frame_compared": 0})["cross_frame"] is False


def test_a_target_before_v0541_is_read_the_way_the_router_read_it_then():
    """The control: a target that does not name what it measured keeps the old reading (a key present = it ran)."""
    old_strict = {"wrapper_drift": 0, "cross_frame_drift": 0, "auth_matrix_total": 396}
    assert mt._detectors_measured(old_strict) == {"wrapper_route": True, "cross_frame": True, "auth_matrix": True}


def _axes(tool, fv, violators=(), cross=(), wrapper=()):
    return mt._detector_axes(tool, fv, mt._detectors_measured(fv), set(violators), set(cross), set(wrapper))


def test_a_row_passes_the_wrong_tier_axis_only_where_the_matrix_probed_it():
    fv = {**STRICT, "auth_matrix_probed_tools": ["theprotocol_getMyBalance"]}
    assert _axes("theprotocol_getMyBalance", fv)["wrong_tier_rejection"]["state"] == "pass"
    # a public tool has no wrong tier and is never probed
    assert _axes("theprotocol_discoverAgents", fv)["wrong_tier_rejection"]["state"] == "na"
    assert _axes("theprotocol_getMyBalance", fv, violators=["theprotocol_getMyBalance"])["wrong_tier_rejection"]["state"] == "fail"
    # a suite with no matrix: no row passes it
    assert _axes("theprotocol_getMyBalance", {"auth_matrix_total": 0})["wrong_tier_rejection"]["state"] == "na"


def test_a_row_passes_the_cross_frame_axis_only_where_the_walk_compared_it():
    fv = {**STRICT, "cross_frame_compared_tools": ["theprotocol_getNetworkStats"]}
    assert _axes("theprotocol_getNetworkStats", fv)["cross_frame_parity"]["state"] == "pass"
    assert _axes("theprotocol_getMyBalance", fv)["cross_frame_parity"]["state"] == "na"
    assert _axes("theprotocol_getNetworkStats", fv, cross=["theprotocol_getNetworkStats"])["cross_frame_parity"]["state"] == "fail"
    assert _axes("theprotocol_getNetworkStats", CLOUD_OP)["cross_frame_parity"]["state"] == "na"


def test_a_row_passes_the_wrapper_axis_only_in_a_run_that_checked_wrappers():
    assert _axes("theprotocol_createAgent", STRICT)["wrapper_route_drift"]["state"] == "pass"
    assert _axes("theprotocol_createAgent", STRICT, wrapper=["theprotocol_createAgent"])["wrapper_route_drift"]["state"] == "fail"
    assert _axes("theprotocol_createAgent", CLOUD_OP)["wrapper_route_drift"]["state"] == "na"
    assert _axes("theprotocol_createAgent", {"auth_matrix_total": 0})["wrapper_route_drift"]["state"] == "na"


def test_the_three_axes_keep_their_keys_and_order():
    assert list(_axes("t", STRICT)) == ["wrong_tier_rejection", "cross_frame_parity", "wrapper_route_drift"]


def _dict_keys(tree: ast.AST) -> list[str]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            out += [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    return out


def test_the_suites_name_what_they_measured():
    keys = _dict_keys(ast.parse(FLOW.read_text()))
    assert keys.count("auth_matrix_probed_tools") == 2        # the strict sweep and the cloud-op sweep
    # the strict sweep, the one suite that checks wrappers, spreads the request survey's values (§MCPTEST30 V0547: the
    # keys live in api_tests/contracts/wrapper_route_survey.flow_values, test_wrapper_route_survey.py pins the spread)
    spreads = [v for n in ast.walk(ast.parse(FLOW.read_text())) if isinstance(n, ast.Dict)
               for k, v in zip(n.keys, n.values) if k is None and getattr(v, "id", None) == "wrapper_drift_summary"]
    assert len(spreads) == 1
    assert keys.count("cross_frame_compared_tools") == 1      # the strict sweep's summary
    assert keys.count("compared_tools") == 2                  # the walk, both of its returns


def test_the_router_records_the_detectors_and_builds_the_axes_from_them():
    tree = ast.parse(ROUTER.read_text())
    assert _dict_keys(tree).count("detectors") == 1
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_detector_axes"]
    assert len(calls) == 1
    # the control: no row detail says the sentence every unprobed row carried (read on the AST: the docstrings quote it)
    details = [v.value for n in ast.walk(tree) if isinstance(n, ast.Dict)
               for k, v in zip(n.keys, n.values)
               if isinstance(k, ast.Constant) and k.value == "detail" and isinstance(v, ast.Constant)]
    assert details and not [d for d in details if "rejected all 3 wrong-tier credentials" in str(d)]
    assert "rejected every wrong-tier credential it was probed with (401/403)" in details
