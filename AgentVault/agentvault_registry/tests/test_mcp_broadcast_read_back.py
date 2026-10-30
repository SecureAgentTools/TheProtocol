"""V0649 (agentvault2-13, 2026-10-30): the admin sweep's composeBroadcast row is a pass only when the run's own
developer reads the notice back (GET /api/v1/notifications/{id}); on V0647 it passed on the compose call's 2xx alone
("PASS ON SEND", BACKLOG_2026-10-19_MCP_REFUSAL_ONLY_PASSES.md). Fails on V0647's sweep (the control)."""
from __future__ import annotations

import asyncio
import json

from agentvault_registry.api_tests.contracts import mcp_admin_lifecycles as A

TOOL = "theprotocol_composeBroadcast"


def _row():
    return {"tool_name": TOOL, "healthy": True, "skip_reason": None, "fail_reason": None, "status_code": 200}


class _Bag:
    def __init__(self, http):
        self.http_in_target = http


def _http(code, body, seen):
    async def call(method, path, *, bearer="", **kw):
        seen.append((method, path, bearer))
        return code, json.dumps(body) if body is not None else ""
    return call


def _go(bag, bid=42):
    out = {TOOL: _row()}
    asyncio.run(A.broadcast_read_back(bag, bid, "dev-jwt", out))
    return out[TOOL]


def test_the_notice_read_back_keeps_the_pass():
    seen = []
    row = _go(_Bag(_http("200", {"read": False, "read_at": None, "broadcast": {"id": 42, "title": "phase6 sweep"}}, seen)))
    assert row["healthy"] is True and "reads the notice" in row["read_back"]
    assert seen == [("GET", "/api/v1/notifications/42", "dev-jwt")], "the receipt route, as the run's own developer"


def test_a_notice_the_developer_cannot_read_is_a_failure():
    row = _go(_Bag(_http("404", {"detail": "Broadcast not found"}, [])))
    assert row["healthy"] is False and "cannot read the notice back" in row["fail_reason"] and "HTTP 404" in row["fail_reason"]


def test_another_broadcast_answering_is_a_failure():
    row = _go(_Bag(_http("200", {"read": False, "broadcast": {"id": 41, "title": "phase6 sweep"}}, [])))
    assert row["healthy"] is False


def test_no_id_and_no_transport_are_said():
    assert _go(_Bag(_http("200", {}, [])), bid=None)["healthy"] is False
    row = _go(_Bag(None))
    assert row["healthy"] is False and row["skip_reason"].startswith("NOT MEASURED: composed (HTTP 2xx), but this flow")


def test_a_row_that_did_not_pass_is_left_alone():
    out = {TOOL: dict(_row(), healthy=False, fail_reason="refused")}
    asyncio.run(A.broadcast_read_back(_Bag(None), 42, "dev-jwt", out))
    assert out[TOOL]["fail_reason"] == "refused"


def test_the_sweep_reads_back_what_it_composed():
    import inspect
    src = inspect.getsource(A)
    assert "await broadcast_read_back(bag, composed, dev_jwt, outcomes)" in src
    assert '"title": SWEEP_BROADCAST_TITLE' in src
