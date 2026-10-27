"""§MCPTEST30 (2026-10-01) — a tool result is a failure when its `error` holds a value, never because the key exists.

Both MCP dispatchers called any result dict carrying an `error` KEY a failure. A route whose success body says
`"error": null` (VerifyResponse, the tutorial proxy, the api-test runners, the health probes) reached every MCP client
as the text `Error: None` with isError true and no structuredContent: the MCP tester read exactly that on
executeTutorial in every round. The executeTutorial tool itself sent {tutorial_id, args} to a route that reads
{method, path, body, auth_type, auth_token}.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from agentvault_registry.mcp import server, server_admin, tools_admin
from agentvault_registry.mcp.tool_result import is_failure


@pytest.mark.parametrize("result,failed", [
    ({"error": None, "status_code": 200}, False),
    ({"error": "", "valid": True}, False),
    ({"error": "  "}, False),
    ({"error": False}, False),
    ({"ok": True}, False),
    ([1, 2], False),
    ("text", False),
    ({"error": "token is required"}, True),
    ({"error": "HTTP 404: not found", "upstream_error": {"detail": "x"}}, True),
    ({"error": {"code": 7}}, True),
])
def test_the_rule(result, failed):
    assert is_failure(result) is failed


@pytest.mark.parametrize("payload_of,format_of", [
    (server._tool_result_payload, server._format_tool_result),
    (server_admin._admin_result_payload, server_admin._format_result),
])
def test_both_dispatchers_report_a_null_error_success_as_a_success(payload_of, format_of):
    ok = {"status_code": 200, "response": {"a": 1}, "response_time": 3.1, "error": None}
    p = payload_of(ok)
    assert p["isError"] is False and p["structuredContent"] == ok
    assert json.loads(p["content"][0]["text"]) == ok and not format_of(ok).startswith("Error:")
    bad = {"error": "tutorial_id is required"}
    p = payload_of(bad)
    assert p["isError"] is True and "structuredContent" not in p
    assert p["content"][0]["text"] == "Error: tutorial_id is required" == format_of(bad)


class _Auth:
    raw_token = "dev-jwt"


@pytest.fixture
def posted(monkeypatch):
    seen = []

    async def fake_post(auth, path, json_body=None, **kw):
        seen.append((path, json_body))
        return {"status_code": 200, "response": {}, "response_time": 1.0, "error": None}
    monkeypatch.setattr(tools_admin, "_admin_post", fake_post)
    return seen


def test_execute_tutorial_sends_the_routes_own_fields(posted):
    out = asyncio.run(tools_admin.execute_tutorial(_Auth(), method="get", path="/public/registry-config"))
    assert out["error"] is None and not is_failure(out)
    assert posted == [("/api/v1/admin/tutorial/execute",
                       {"method": "GET", "path": "/public/registry-config", "auth_type": "none"})]
    asyncio.run(tools_admin.execute_tutorial(_Auth(), method="POST", path="/auth/login", body={"username": "u"},
                                             auth_type="developer", auth_token="t"))
    assert posted[-1][1] == {"method": "POST", "path": "/auth/login", "auth_type": "developer",
                             "body": {"username": "u"}, "auth_token": "t"}


@pytest.mark.parametrize("kw,needle", [
    (dict(tutorial_id="t1"), "no tutorial id"),
    (dict(method="GET", path="/x", args={"a": 1}), "no tutorial id"),
    (dict(method="TRACE", path="/x"), "method must be"),
    (dict(method="GET", path="public"), "starts with a single /"),
    (dict(method="GET", path="//evil"), "starts with a single /"),
    (dict(method="GET", path="/x", auth_type="root"), "auth_type must be"),
])
def test_execute_tutorial_refuses_what_the_route_cannot_run_and_calls_nothing(posted, kw, needle):
    out = asyncio.run(tools_admin.execute_tutorial(_Auth(), **kw))
    assert is_failure(out) and needle in out["error"] and posted == []


def test_the_schema_declares_what_the_wrapper_takes():
    schema = next(s for s in tools_admin.ADMIN_TOOL_SCHEMAS if s["name"] == "theprotocol_executeTutorial")
    props = schema["inputSchema"]["properties"]
    assert set(props) == {"method", "path", "body", "auth_type", "auth_token"}
    assert schema["inputSchema"]["required"] == ["method", "path"]


def test_the_tutorial_proxy_has_no_literal_sandbox():
    import inspect
    from agentvault_registry.routers import admin_tutorial
    src = inspect.getsource(admin_tutorial)
    assert "registry-test:8000" not in src.replace('"http://registry-test:8000" named', ""), \
        "an unset API_TEST_TARGET_URL must mean 'no tutorial sandbox', never a Frame A hostname"


def test_an_unconfigured_tutorial_proxy_says_so(monkeypatch):
    from fastapi import HTTPException
    from agentvault_registry.routers import admin_tutorial
    monkeypatch.setattr(admin_tutorial, "SANDBOX_URL", "")
    with pytest.raises(HTTPException) as e:
        asyncio.run(admin_tutorial.execute_tutorial_call(request={"method": "GET", "path": "/x"}, developer=None))
    assert e.value.status_code == 503 and "No tutorial sandbox is configured" in e.value.detail
    out = asyncio.run(admin_tutorial.tutorial_sandbox_health(developer=None))
    assert out["healthy"] is False and "No tutorial sandbox" in out["reason"]


def test_the_dispute_detail_tool_is_agent_tier_everywhere():
    from agentvault_registry.mcp import audit
    name = "theprotocol_getTegDisputeDetail"
    assert name in server.TIER2_TOOLS and name not in server.TIER3_TOOLS
    assert name in audit._TIER_2_TOOLS and name not in audit._TIER_3_TOOLS


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
