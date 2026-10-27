"""§MCPTEST30 (V0545) — a lifecycle step whose call came back with no HTTP status measured nothing.

`_exec_step` judged "any" as `status < 500`, and a missing status read as 0: the strict run started from EU's page at
03:19Z (3e49fcef) recorded getArenaMatchMap healthy with no status and an empty answer. The next run lost the overdraft
probe's spender token the same way (the registry had answered 200). The federation rig has handled this since
2026-10-01 (a read asked once more, the test NOT MEASURED); the lifecycle steps now do the same: a read whose answer never
arrived is asked once more, a write never is, and a step that still has no status is a named NOT MEASURED, never a pass.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from agentvault_registry.api_tests.contracts import mcp_lifecycles as L

READ, WRITE = "theprotocol_getArenaMatchMap", "theprotocol_transferUnits"


def _parse(body):
    try:
        return json.loads(body["result"]["content"][0]["text"])
    except Exception:
        return {"_text": str(body)} if body else {}


def _answer(obj, code):
    return code.startswith("2"), {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}]}}, code


def _step(tool, answers, expect_status="any"):
    calls = []

    async def rpc(t, args, jwt="", timeout=15):
        calls.append(t)
        return answers[min(len(calls), len(answers)) - 1]
    out = {}
    asyncio.run(L._exec_step(rpc, _parse, tool, "1", {"match_id": "x"}, "jwt", out, expect_status=expect_status))
    return out[tool], calls


LOST = (False, {"_raw": ""}, "")


def test_the_server_marks_the_two_tools_as_this_test_needs_them():
    assert L._reads_only(READ) is True and L._reads_only(WRITE) is False


def test_a_lost_answer_under_any_is_not_measured_never_a_pass():
    row, calls = _step(WRITE, [LOST])
    assert row["healthy"] is False and row["fail_reason"] is None
    assert row["skip_reason"] == ("NOT MEASURED: no HTTP status came back for theprotocol_transferUnits (the answer "
                                  "was lost in transit; the server may have answered)")
    assert calls == [WRITE], "a write is never repeated"


def test_a_read_whose_answer_was_lost_is_asked_once_more():
    row, calls = _step(READ, [LOST, _answer({"detail": "Match not found"}, "404")])
    assert calls == [READ, READ] and row["healthy"] is True and row["status_code"] == 404 and not row["skip_reason"]


def test_a_read_lost_twice_is_named_and_asked_no_third_time():
    row, calls = _step(READ, [LOST, LOST, _answer({}, "200")])
    assert calls == [READ, READ] and row["skip_reason"].startswith("NOT MEASURED: no HTTP status came back")


def test_curl_reaching_no_server_is_named_as_such():
    row, _ = _step(WRITE, [(False, {}, "000")], expect_status="success")
    assert row["skip_reason"].endswith("(curl reached no server: 000)") and row["fail_reason"] is None


def test_an_answer_with_a_status_is_judged_as_before():
    row, calls = _step(READ, [_answer({"detail": "boom"}, "500")])
    assert calls == [READ] and row["healthy"] is False and row["fail_reason"].startswith("step 'theprotocol_getArenaMatchMap' server error")
    row, _ = _step(READ, [_answer({"detail": "Match not found"}, "404")])
    assert row["healthy"] is True and not row["skip_reason"]


def test_the_skip_census_names_the_family():
    from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import classify_tool_skip
    assert classify_tool_skip(L.lost_answer_sentence(READ, "")) == "transport_lost"
    assert classify_tool_skip("NOT MEASURED: 0 row(s), no second page of 3 to compare") == "probe_not_measured"


@pytest.mark.parametrize("code,lost", [("", True), (None, True), ("000", True), ("0", True), ("200", False),
                                       ("404", False), ("599", False), ("600", True), (" 201 ", False)])
def test_what_counts_as_no_status(code, lost):
    assert L.no_http_status(code) is lost


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
