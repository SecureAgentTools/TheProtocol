"""§MCPTEST30 (V0552) — a tool whose own call to its route timed out did not refuse its arguments.

The rpc layer turned any inner text starting "Error:" into a synthetic 400 (the wrapper refused the call), so a tool that
answered "Error: ReadTimeout" read as a refusal, and an any-status probe counted it healthy: testApiEndpoint in rounds 16
and 17, getAdminWorkersStatus on an operator in round 17. A timeout is now 504 and a broken connection 502; a read is
asked once more first, a write never is. And the api-tester tools wait as long as their routes take: one test-endpoint
call seeds the tester's fixtures every time (28 s and 36 s measured on sbx-alpha), past the admin helper's 30 s.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F  # noqa: E402
from agentvault_registry.api_tests.contracts import mcp_lifecycles as L  # noqa: E402
from agentvault_registry.mcp import tools_admin as ta  # noqa: E402


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _envelope(text):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}]}}


@pytest.mark.parametrize("text,status", [
    ("Error: ReadTimeout", 504),
    ("Error: ConnectTimeout", 504),
    ("Error: PoolTimeout: no connection available", 504),
    ("Error: ConnectError: [Errno 111] Connection refused", 502),
    ("Error: RemoteProtocolError: Server disconnected without sending a response.", 502),
    # controls: the wrapper refusing its arguments stays 400, a backend status stays itself
    ("Error: agent_dids (list) is required", 400),
    ("Error: ", 400),
    ("Error: HTTP 404: Agent not found", 404),
    ("Error: HTTP 503: api-tester execution is disabled on this registry", 503),
])
def test_the_inner_text_names_the_status(text, status):
    assert F._wrapped_http_status(_envelope(text)) == status


@pytest.mark.parametrize("payload,status", [
    ({"error": "Request timed out after 30.0s"}, 504),
    ({"error": "EventStore request timed out after 30.0s", "path": "/x"}, 504),
    ({"error": "endpoint_path is required"}, 400),
])
def test_the_tools_own_timeout_sentence_is_a_timeout(payload, status):
    assert F._wrapped_http_status(_envelope(json.dumps(payload))) == status


def test_prose_that_mentions_a_timeout_is_not_one():
    long_note = ("the worker recovered after a ReadTimeout on its first poll and has reported healthy since; this is "
                 "the cycle summary and not an error at all")
    assert F._inner_transport_status(long_note) is None
    assert F._wrapped_http_status(_envelope(json.dumps({"summary": long_note, "ok": True}))) is None
    assert F._inner_transport_status("Bootstrap token timed out") is None, "only the tools' 'after N s' sentence"


READ, WRITE = "theprotocol_getAdminWorkersStatus", "theprotocol_testApiEndpoint"
TIMED_OUT = (False, _envelope("Error: ReadTimeout"), "504")


def _answer(obj, code):
    return code.startswith("2"), _envelope(json.dumps(obj)), code


def _step(tool, answers):
    calls = []

    async def rpc(t, args, jwt="", timeout=15):
        calls.append(t)
        return answers[min(len(calls), len(answers)) - 1]
    out = {}
    asyncio.run(L._exec_step(rpc, F._parse_rpc_result, tool, "admin", {}, "jwt", out, expect_status="any"))
    return out[tool], calls


def test_the_server_marks_the_two_tools_as_this_test_needs_them():
    assert L._reads_only(READ) is True and L._reads_only(WRITE) is False


def test_a_read_that_timed_out_is_asked_once_more():
    row, calls = _step(READ, [TIMED_OUT, _answer({"workers": []}, "200")])
    assert calls == [READ, READ] and row["healthy"] is True and row["status_code"] == 200


def test_a_read_that_timed_out_twice_fails_as_the_routes_timeout():
    row, calls = _step(READ, [TIMED_OUT, TIMED_OUT, _answer({}, "200")])
    assert calls == [READ, READ] and row["healthy"] is False and row["status_code"] == 504
    assert row["fail_reason"].startswith(f"step '{READ}' server error: HTTP 504")


def test_a_write_that_timed_out_is_never_repeated_and_never_a_pass():
    row, calls = _step(WRITE, [TIMED_OUT, _answer({}, "200")])
    assert calls == [WRITE] and row["healthy"] is False and row["status_code"] == 504


def test_a_refusal_under_any_still_passes_and_is_not_repeated():
    row, calls = _step(READ, [(False, _envelope("Error: HTTP 404: no such worker"), "404")])
    assert calls == [READ] and row["healthy"] is True and row["status_code"] == 404


class _Resp:
    status_code = 200

    def json(self):
        return {"statusCode": 404, "healthy": False}


def _capture(monkeypatch):
    seen = []

    class _Client:
        def __init__(self, *a, **k):
            seen.append(k.get("timeout"))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            return _Resp()

    monkeypatch.setattr(ta.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(ta, "require_admin_auth", lambda auth: None)
    monkeypatch.setattr(ta, "_get_effective_jwt", lambda auth: "jwt")
    return seen


def test_the_api_tester_tools_wait_as_long_as_their_routes_take(monkeypatch):
    seen = _capture(monkeypatch)
    asyncio.run(ta.test_api_endpoint(object(), "/api/v1/phase6-no-such-endpoint"))
    asyncio.run(ta.test_api_category(object(), "phase6-no-such-category"))
    asyncio.run(ta.test_api_flow(object(), "phase6-no-such-flow"))
    asyncio.run(ta.test_api_federation(object()))
    assert seen[0] == ta.API_TEST_ENDPOINT_TIMEOUT >= 120, "a single endpoint seeds ~40 fixtures first (28-36 s measured)"
    assert seen[1:] == [ta.API_TEST_RUN_TIMEOUT] * 3 and ta.API_TEST_RUN_TIMEOUT >= 900


def test_every_other_admin_post_keeps_the_helpers_ceiling(monkeypatch):
    seen = _capture(monkeypatch)
    asyncio.run(ta.reset_api_test_flow_values(object()))
    assert seen == [ta.HTTPX_TIMEOUT] and ta.HTTPX_TIMEOUT == 30.0
