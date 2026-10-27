"""§MCPSWEEP 2026-09-27 — a probe the MCP dispatcher refused never reached the tool, so it measured nothing.

Measured from sbx-alpha's audit rows of the 03:00Z nightly: 57 admin-lifecycle probes sent arguments their tools never
declared, or omitted required ones. The dispatcher answered -32602 "Invalid params" inside an HTTP 200, the sweep's
parser keeps only `result`, and expect_status="any" counted every one of them healthy. The rule pinned here: such a row
is a NAMED SKIP (a tester defect, its own census family), an internal error (-32603) is a server error, and an ordinary
refusal (an auth refusal, a wrapped 404) still counts as a measured refusal, exactly as before.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentvault_registry.api_tests.contracts import mcp_lifecycles as ml  # noqa: E402
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import (  # noqa: E402
    _SELF_HARMING_DEV_TOOLS, _parse_rpc_result, _resolve_developer_id_param, _wrong_tier_refused_before_gate,
    _wrong_tier_rejected, classify_tool_skip,
)

TOOL = "theprotocol_reinstateDeveloper"


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    # This file drives coroutines with asyncio.run(), which leaves the thread with no current loop; put one back, or the
    # next file's get_event_loop() fails and the red lands in a file this one never touched.
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _run(envelope: dict, code: str = "200", expect: str = "any", tier: str = "admin") -> dict:
    async def rpc(tool, args, jwt="", timeout=15):
        return code.startswith("2") and "error" not in envelope, envelope, code
    outcomes: dict = {}
    asyncio.run(ml._exec_step(rpc, _parse_rpc_result, TOOL, tier, {"developer_id": 999999}, "jwt", outcomes,
                              expect_status=expect))
    return outcomes[TOOL]


def _rpc_error(code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "error": {"code": code, "message": message}}


def test_invalid_params_is_a_named_skip_not_a_pass():
    row = _run(_rpc_error(-32602, "Invalid params: reinstate_developer() got an unexpected keyword argument 'reason'"))
    assert row["healthy"] is False and row["fail_reason"] is None
    assert row["skip_reason"].startswith("probe never reached the tool")
    assert "invalid params" in row["skip_reason"] and "unexpected keyword argument 'reason'" in row["skip_reason"]


def test_tool_not_found_is_a_named_skip():
    row = _run(_rpc_error(-32601, "Tool not found: 'theprotocol_reinstateDeveloper'. Use tools/list"))
    assert row["healthy"] is False and row["fail_reason"] is None
    assert "tool not found" in row["skip_reason"] and "admin bridge" in row["skip_reason"]


def test_a_malformed_probe_is_a_skip_in_success_mode_too():
    row = _run(_rpc_error(-32602, "Invalid params: missing 1 required positional argument: 'developer_id'"),
               expect="success")
    assert row["healthy"] is False and row["fail_reason"] is None and row["skip_reason"]


def test_an_internal_error_is_a_server_error():
    row = _run(_rpc_error(-32603, "Internal error: boom"))
    assert row["healthy"] is False and row["skip_reason"] is None
    assert "internal error" in row["fail_reason"]


def test_an_internal_error_answers_a_5xx_expectation():
    row = _run(_rpc_error(-32603, "Internal error: boom"), expect="error_5xx")
    assert row["healthy"] is True and row["fail_reason"] is None


def test_an_auth_refusal_is_still_a_measured_refusal():
    # -32001 is the dispatcher's auth refusal: the probe reached the gate it was sent to, as before this change
    row = _run(_rpc_error(-32001, "Authentication required"))
    assert row["healthy"] is True and row["skip_reason"] is None and row["fail_reason"] is None


def test_a_tier1_tool_refused_by_the_endpoint_never_reached_it():
    # a public tool takes no credential, so "authentication required" is the MCP endpoint's refusal, before dispatch:
    # 21 tier-1 lifecycle steps sent no bearer and read green on exactly this (§BEARER4 fixed one of them)
    row = _run(_rpc_error(-32001, "Authentication required. Use OAuth or pass Bearer token."), code="401", tier="1")
    assert row["healthy"] is False and row["fail_reason"] is None
    assert row["skip_reason"].startswith("probe never reached the tool") and "bearer" in row["skip_reason"]
    assert classify_tool_skip(row["skip_reason"]) == "probe_never_reached_tool"


def test_control_the_same_refusal_of_a_tier3_tool_is_its_measured_answer():
    row = _run(_rpc_error(-32001, "Authentication required. Use OAuth or pass Bearer token."), code="401", tier="3")
    assert row["healthy"] is True and row["skip_reason"] is None and row["fail_reason"] is None


def test_a_wrapped_404_is_still_a_measured_refusal():
    env = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "Error: HTTP 404: Developer 999999 not found"}]}}
    row = _run(env, code="404")
    assert row["healthy"] is True and row["skip_reason"] is None


def test_the_census_names_the_family():
    row = _run(_rpc_error(-32602, "Invalid params: x() got an unexpected keyword argument 'y'"))
    assert classify_tool_skip(row["skip_reason"]) == "probe_never_reached_tool"


def _wrapped(text: str) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}]}}


def test_the_auth_matrix_names_a_refusal_before_the_gate():
    # the matrix calls with {} on purpose; a tool with required arguments never reaches its tier check
    before = [_rpc_error(-32602, "Invalid params: x() missing 1 required positional argument: 'agent_did'"),
              _wrapped("Error: agent_did is required"),
              _wrapped("Error: peer_id and reason are required")]
    for body in before:
        assert _wrong_tier_refused_before_gate(body), body
        assert _wrong_tier_rejected(200, body), "still never scored as an accept"


def test_control_a_refusal_at_the_gate_stays_a_measured_refusal():
    at_gate = [_rpc_error(-32001, "Authentication required. Use OAuth or pass Bearer token."),
               _wrapped("Error: admin auth required"),
               _wrapped("Error: Missing authorization header"),
               _wrapped("Error: Agent JWT is required for this tool"),
               {}]
    for body in at_gate:
        assert not _wrong_tier_refused_before_gate(body), body


def test_a_developer_mutating_tool_never_falls_back_to_a_real_developer():
    # the fallback id was 2, "deliberately NOT the runner"; on the tester frame id 2 IS the runner
    assert _SELF_HARMING_DEV_TOOLS, "the guarded set is empty: the test would pass over nothing"
    for tool in _SELF_HARMING_DEV_TOOLS:
        assert _resolve_developer_id_param(tool) >= 900000, tool


def test_control_a_read_keeps_the_first_developer():
    assert _resolve_developer_id_param("theprotocol_getAdminDeveloperDetail") == 1
