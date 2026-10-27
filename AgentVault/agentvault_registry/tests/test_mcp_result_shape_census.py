"""§MCPTEST30 (2026-10-01) — the result shape census: every tools/call answer read for the protocol's own promises.

Two questions per answer, findings without values: a success reported as a failure (isError with `Error: None`, the
dispatchers' old reading of an `"error": null` body), and an answer that does not validate against the outputSchema
its tool declares (mcp/tool_metadata.OUTPUT_SCHEMAS, imported by the census).
"""
from __future__ import annotations

import json

import pytest

from agentvault_registry.api_tests.contracts import result_shape as RS
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F

SECRETISH = "zq-7781-distinctive-value-never-recorded"


def _ok(structured, text=None):
    return {"jsonrpc": "2.0", "id": 1, "result": {
        "content": [{"type": "text", "text": text if text is not None else json.dumps(structured)}],
        "isError": False, "structuredContent": structured}}


def _err(text):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}], "isError": True}}


@pytest.mark.parametrize("text", ["Error: None", "Error: ", "Error: False", "Error:null"])
def test_a_success_reported_as_a_failure_is_a_finding(text):
    assert RS.check("theprotocol_executeTutorial", _err(text)) == [
        "success reported as failure: isError with an empty error (`Error: None`)"]


def test_a_real_failure_is_no_finding():
    assert RS.check("theprotocol_executeTutorial", _err("Error: HTTP 404: Not Found")) == []
    assert RS.check("theprotocol_getMyBalance", _err("Error: token is required")) == []


def test_answers_this_census_does_not_read():
    assert RS.check("theprotocol_getNetworkStats", {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602}}) == []
    assert RS.check("theprotocol_getNetworkStats", {"_raw": "x"}) == []
    assert RS.check("mcp:tools/list", {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}) == []


def test_a_declared_schema_is_validated_and_the_value_never_recorded():
    assert RS.check("theprotocol_getNetworkStats", _ok({"total_agents": 3, "active_agents": 1, "extra": "ok"})) == []
    found = RS.check("theprotocol_getNetworkStats", _ok({"total_agents": SECRETISH, "active_agents": 1}))
    assert found == ["outputSchema violation: `type` at total_agents"]
    assert SECRETISH not in json.dumps(found)


def test_a_declared_schema_with_no_structured_content_is_a_finding():
    body = _ok({"x": 1})
    del body["result"]["structuredContent"]
    assert RS.check("theprotocol_getLockPayoutTiers", body) == ["outputSchema declared, no structuredContent on a success"]
    assert RS.check("theprotocol_getWebhook", body) == [], "no declared schema: structuredContent is optional"


def test_the_census_reads_the_products_own_schemas():
    from agentvault_registry.mcp.tool_metadata import OUTPUT_SCHEMAS
    assert RS.schema_for("theprotocol_getTrustScore") is OUTPUT_SCHEMAS["getTrustScore"]
    assert RS.schema_for("getTrustScore") is None and RS.schema_for("theprotocol_noSuchTool") is None


def test_a_run_collects_and_closes_into_rows():
    token = RS.begin()
    RS.record("theprotocol_getNetworkStats", _ok({"total_agents": 3}))
    RS.record("theprotocol_executeTutorial", _err("Error: None"))
    RS.record("theprotocol_getTrustScore", _ok({"agent_did": "d", "trust_score": [SECRETISH]}))
    tool_row = F.ContractOutcome(tool_name="theprotocol_executeTutorial", contract_tier="admin-bridge", healthy=True,
                                 status_code=200, elapsed_ms=1, skip_reason=None, fail_reason=None,
                                 has_explicit_contract=True, args_used={}, result_excerpt={})
    outcomes = [tool_row]
    summary = F._result_shape_close(outcomes, token)
    assert summary["responses_scanned"] == 3 and summary["schema_checked"] == 2
    assert sorted(summary["findings"]) == ["theprotocol_executeTutorial", "theprotocol_getTrustScore"]
    assert tool_row.healthy is False and tool_row.fail_reason.startswith("BUG-FIND: result shape")
    census = outcomes[-1]
    assert census.tool_name == RS.CENSUS_ROW and census.healthy is False and "2 tool(s)" in census.fail_reason
    assert SECRETISH not in json.dumps(census.result_excerpt)


def test_an_empty_run_is_not_measured_rather_than_green():
    outcomes = []
    F._result_shape_close(outcomes, RS.begin())
    assert outcomes[-1].healthy is False and outcomes[-1].skip_reason.startswith("result shape census NOT MEASURED")


def test_record_outside_a_run_is_a_no_op_and_never_raises():
    RS.record("theprotocol_getNetworkStats", object())
    RS.record("theprotocol_getNetworkStats", _ok({"total_agents": "x"}))


def test_every_answer_the_sweep_receives_is_read():
    import inspect
    src = inspect.getsource(F)
    assert src.count("result_shape.record(") == src.count("credential_exposure.record(") == 4
    assert src.count("_result_shape_close(outcomes, _shape_token)") == 2, "the frame flow and the cloud-op flow"
