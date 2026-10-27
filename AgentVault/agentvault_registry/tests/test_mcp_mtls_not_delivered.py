"""§MCPTEST30 (V0639): enableMtls answering `not_enrolled` is the route keeping its word, not a flip that did not land.

routers/agent_mtls.py (§EXTMTLS-C) answers 200 {"status": "not_enrolled", "delivery": ...} for an agent it calls
external when inline delivery is off or the mint failed, and writes nothing. lifecycle_mtls_toggle read that 200 as an
enrolment and its read-back (enrolled=False) as "the flip did not land": a red row on both cloud operators (the wide
list, 2026-10-24 13:39-13:46Z). Pinned: on `not_enrolled` the enrolment and the disable are NOT MEASURED with the
reason, disableMyMtls is not called, and the promise has its own row (the status read must say not enrolled; a read
that says enrolled is a BUG-FIND); an enrolment that did happen runs the toggle as before.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from agentvault_registry.api_tests.contracts import mcp_lifecycles as M

ROW = "refusal: enableMtls an identity this target cannot deliver"


def _run(enable, reads, read_ok=True):
    calls = []
    reads = list(reads)

    async def rpc(tool, args, jwt="", timeout=20):
        calls.append(tool)
        if tool == "theprotocol_enableMtls":
            return True, {"result": enable}, "200"
        if tool == "theprotocol_getMyMtlsStatus":
            if not read_ok:
                return False, {"result": {"_text": "Error: upstream timed out"}}, "504"
            return True, {"result": reads.pop(0)}, "200"
        return True, {"result": {"status": "disabled"}}, "200"

    def parse(body):
        r = body.get("result") if isinstance(body, dict) else None
        return r if isinstance(r, dict) else {}

    bag = SimpleNamespace(developer_jwt="dev-jwt", sentinel_jwt="agent-jwt")
    outcomes = {}
    asyncio.run(M.lifecycle_mtls_toggle(rpc, parse, bag, outcomes))
    return calls, outcomes


NOT_ENROLLED = {"status": "not_enrolled", "deployment": "external", "delivery": "unavailable", "spiffe_id": None}


def test_not_enrolled_is_said_and_the_promise_is_measured():
    calls, outcomes = _run(NOT_ENROLLED, [{"enrolled": False}])
    assert "theprotocol_disableMyMtls" not in calls
    enable = outcomes["theprotocol_enableMtls"]
    assert enable["healthy"] is False and enable["skip_reason"].startswith("NOT MEASURED")
    assert "delivery: unavailable" in enable["skip_reason"]
    assert outcomes["theprotocol_disableMyMtls"]["skip_reason"].startswith("NOT MEASURED")
    assert outcomes[ROW]["healthy"] is True and outcomes[ROW]["tool_name"] == ROW


def test_a_read_that_claims_the_identity_is_a_bug_find():
    _calls, outcomes = _run(NOT_ENROLLED, [{"enrolled": True}])
    assert outcomes[ROW]["healthy"] is False and "BUG-FIND" in outcomes[ROW]["fail_reason"]


def test_a_failed_read_measures_nothing():
    _calls, outcomes = _run(NOT_ENROLLED, [], read_ok=False)
    assert outcomes[ROW]["skip_reason"].startswith("NOT MEASURED") and outcomes[ROW]["healthy"] is False


def test_a_read_without_the_field_measures_nothing():
    _calls, outcomes = _run(NOT_ENROLLED, [{"status": "ok"}])
    assert outcomes[ROW]["skip_reason"].startswith("NOT MEASURED")


def test_control_an_enrolment_runs_the_toggle_as_before():
    calls, outcomes = _run({"status": "enrolled", "spiffe_id": "spiffe://x/agent/1"},
                           [{"enrolled": True}, {"enrolled": False}])
    assert calls == ["theprotocol_enableMtls", "theprotocol_getMyMtlsStatus", "theprotocol_disableMyMtls",
                     "theprotocol_getMyMtlsStatus"]
    assert ROW not in outcomes
    assert outcomes["theprotocol_enableMtls"]["healthy"] is True
