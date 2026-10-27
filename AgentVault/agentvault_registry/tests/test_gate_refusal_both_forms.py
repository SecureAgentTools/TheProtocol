"""§MCPTEST30 V0639 (agentvault2-aa, 2026-10-24): the two pins on a registry-kind gate read its refusal in both forms.

D6-820 (V0640, agentvault2-d6) answers a rail that does not run on this kind of registry 404 instead of 503: the frame's
gate on an operator says "mainframe_only: <its sentence>", an operator's self-service rail on a frame "operator_only:
<its sentence>", each sentence kept whole after the code word. Frames and operators run mixed versions while a release
rolls, so requestFrame (a frame refuses the empty request 422, an operator answers the gate) and operatorPortalSelfLogs
(a frame answers the reverse guard) are judged by the sentence at either class (expect_status "error"). On the old pins
(error_4xx, error_5xx) the V0640 or the V0639 form fails, the control.
"""
from __future__ import annotations

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS, McpFixtureBag

_BAG = McpFixtureBag(sentinel_did="did:theprotocol:test", sentinel_jwt="x")
MAINFRAME = ("This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the "
             "bilateral trust chain{sep} they don't independently provision sub-operators, issue federation licenses, "
             "configure cross-frame bridges, or mint {unit}. Use your federated mainframe's UI for these actions.")
SELF_LOGS = "Operator self-logs is for cloud-ops only. Mainframe admins use /admin/cloud-operators/{id}/logs."


def _wrapped(text: str) -> dict:
    return {"result": {"content": [{"type": "text", "text": text}]}}


def _judge(tool: str, code: str, text: str, ok: bool = False):
    return F._evaluate_contract({"name": tool}, MCP_CONTRACTS[tool], ok, code, _wrapped(text), _BAG)


def test_request_frame_reads_the_gate_in_both_forms_and_the_frames_own_refusal():
    tool = "theprotocol_requestFrame"
    v0639 = MAINFRAME.format(sep=" —", unit="AVT")
    v0640 = "mainframe_only: " + MAINFRAME.format(sep=":", unit="units")
    assert _judge(tool, "503", f"Error: HTTP 503: {v0639}") == (True, None)            # an operator up to V0639
    assert _judge(tool, "404", f"Error: HTTP 404: {v0640}") == (True, None)            # an operator from V0640
    assert _judge(tool, "422", "Error: HTTP 422: Field required") == (True, None)      # a frame
    ok, fail = _judge(tool, "404", "Error: HTTP 404: Not Found")                       # a missing route is no gate
    assert ok is False and "expected error message" in fail
    ok, fail = _judge(tool, "200", '{"status": "submitted"}', ok=True)                 # a request taken is no refusal
    assert ok is False


def test_operator_self_logs_reads_the_reverse_guard_in_both_forms():
    tool = "theprotocol_operatorPortalSelfLogs"
    assert _judge(tool, "503", f"Error: HTTP 503: {SELF_LOGS}") == (True, None)        # a frame up to V0639
    assert _judge(tool, "404", f"Error: HTTP 404: operator_only: {SELF_LOGS}") == (True, None)   # from V0640
    ok, fail = _judge(tool, "404", "Error: HTTP 404: Not Found")
    assert ok is False and "expected error message" in fail


def test_both_pins_take_either_class():
    assert MCP_CONTRACTS["theprotocol_requestFrame"].expect_status == "error"
    assert MCP_CONTRACTS["theprotocol_operatorPortalSelfLogs"].expect_status == "error"
