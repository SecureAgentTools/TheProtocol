"""§MCPTEST30 (2026-09-30) — the console's emission axis may not report work that the call itself says it did not do,
and it must read the store the flow's events actually land in.

Measured on the 2026-09-30 cloud-op sweeps from EU's console:
  * sandboxalpha: importAgent (a dry run: `success: false`) and cloneAgent (a missing agent answered 200 +
    `success: false` until the route was fixed) were reported "REAL MISS ... silent NO-OP" — the calls did nothing, so
    there was nothing to emit;
  * sandboxdelta: 8 emitters "missed" (createOrganization, submitFundingRequest, ...) while their events sat in
    sbx-beta's store — the operator is parented under sandbox-B, and the console polled sbx-alpha's.
Both are fixed in routers/mcp_tester.py (live on a console once it runs this image).
"""
from __future__ import annotations

import pytest

import agentvault_registry.routers.mcp_tester as mt


def test_a_success_false_answer_did_no_work():
    why = mt._did_no_work({"response_excerpt": {"success": False, "errors": ["Missing agent data"]}})
    assert why and "success=false" in why and "Missing agent data" in why


@pytest.mark.parametrize("row", [
    {"response_excerpt": {"success": True}},
    {"response_excerpt": {"agent_did": "did:x"}},
    {"response_excerpt": {"_truncated": True}},
    {"response_excerpt": None},
    {},
])
def test_control_anything_else_is_not_read_as_no_work(row):
    assert mt._did_no_work(row) is None


def test_the_delta_flow_reads_the_parent_store(monkeypatch):
    monkeypatch.setattr(mt, "_EMIT_ES_URL", "http://a-store:8200")
    monkeypatch.setattr(mt, "_EMIT_ES_KEY", "key-a")
    monkeypatch.setattr(mt, "_EMIT_ES_B_URL", "http://b-store:8200")
    monkeypatch.setattr(mt, "_EMIT_ES_B_KEY", "key-b")
    assert mt._emission_store_for("flow_mcp_lifecycle_cloudop_sandboxdelta_complete") == ("http://b-store:8200", "key-b")
    # controls: every other flow, and a console with no B store, read the target's own
    for flow in ("flow_mcp_lifecycle_complete", "flow_mcp_lifecycle_cloudop_sandboxalpha_complete",
                 "flow_federation_suite_complete", ""):
        assert mt._emission_store_for(flow) == ("http://a-store:8200", "key-a")
    monkeypatch.setattr(mt, "_EMIT_ES_B_URL", "")
    assert mt._emission_store_for("flow_mcp_lifecycle_cloudop_sandboxdelta_complete") == ("http://a-store:8200", "key-a")
