"""D6-725 (2026-10-16): a successful enableToolset or disableToolset sends notifications/tools/list_changed.

Both servers advertise `tools.listChanged: true` (the stored toolset selection changes what tools/list returns), and no
notification was ever sent: a client that trusted the capability kept a stale listing. Where the answer travels as an
event stream (POST /mcp or /mcp/admin with Accept: text/event-stream, POST /mcp/sse and /mcp/admin/sse), MCP lets the
server send messages that belong to the request before its answer; the notification goes there, first. A plain JSON
answer has no room for one, and a refused selection (an unknown bucket) changed nothing, so neither carries it.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.responses import JSONResponse
from starlette.requests import Request

from agentvault_registry.mcp import server as S
from agentvault_registry.mcp import server_admin as A
from agentvault_registry.mcp import tools_gateway as G

LIST_CHANGED = {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
SSE = "application/json, text/event-stream"


def _req(body, *, path, bearer="a-credential", accept=SSE):
    raw = json.dumps(body).encode()
    headers = [(b"content-type", b"application/json"), (b"accept", accept.encode())]
    if bearer:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": raw, "more_body": False}
    scope = {"type": "http", "method": "POST", "path": path, "raw_path": path.encode(), "headers": headers,
             "query_string": b"", "client": ("127.0.0.1", 40000), "server": ("testserver", 80), "scheme": "http",
             "root_path": "", "http_version": "1.1"}
    return Request(scope, receive)


def _answer(handler, request):
    """(the response, the server-sent events it streamed as parsed messages; None for a plain JSON answer)"""
    async def go():
        resp = await handler(request)
        if not hasattr(resp, "body_iterator"):
            return resp, None
        text = "".join([c if isinstance(c, str) else c.decode() async for c in resp.body_iterator])
        return resp, [json.loads(line[len("data: "):]) for line in text.splitlines() if line.startswith("data: ")]
    return asyncio.run(go())


def _call(name, toolsets, rid=5):
    return {"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": {"toolsets": toolsets}}}


@pytest.fixture(autouse=True)
def _selection_in_process(monkeypatch):
    """The stored selection without Redis: the module's own in-process fallback."""
    async def no_redis():
        return None
    monkeypatch.setattr(G, "_redis", no_redis)
    G._local_sessions.clear()
    yield
    G._local_sessions.clear()


@pytest.mark.parametrize("wrapper", [S.mcp_streamable_post, S.mcp_streamable_http])
def test_a_selection_change_announces_list_changed_before_its_answer(wrapper):
    _, events = _answer(wrapper, _req(_call("theprotocol_enableToolset", ["wallet"]), path="/mcp"))
    assert events[0] == LIST_CHANGED
    assert events[1]["id"] == 5 and events[1]["result"]["isError"] is False and len(events) == 2
    _, events = _answer(wrapper, _req(_call("theprotocol_disableToolset", [], rid=6), path="/mcp"))
    assert events[0] == LIST_CHANGED and events[1]["id"] == 6


def test_the_listing_it_announces_is_the_one_tools_list_now_returns():
    _answer(S.mcp_streamable_post, _req(_call("theprotocol_enableToolset", ["wallet"]), path="/mcp"))
    _, events = _answer(S.mcp_streamable_post, _req({"jsonrpc": "2.0", "id": 9, "method": "tools/list"}, path="/mcp"))
    listed = {t["name"] for t in events[-1]["result"]["tools"]}
    assert "theprotocol_getMyBalance" in listed and "theprotocol_guildPostOrder" not in listed
    assert LIST_CHANGED not in events, "a read changes nothing"


def test_controls_a_refused_selection_another_method_and_a_json_answer_carry_no_notification():
    _, events = _answer(S.mcp_streamable_post, _req(_call("theprotocol_enableToolset", ["no-such-bucket"]), path="/mcp"))
    assert len(events) == 1 and events[0]["result"]["isError"] is True
    _, events = _answer(S.mcp_streamable_post, _req({"jsonrpc": "2.0", "id": 2, "method": "ping"}, path="/mcp"))
    assert events == [{"jsonrpc": "2.0", "id": 2, "result": {}}]
    resp, events = _answer(S.mcp_streamable_post,
                           _req(_call("theprotocol_enableToolset", ["wallet"]), path="/mcp", accept="application/json"))
    assert events is None and json.loads(resp.body)["result"]["isError"] is False


@pytest.mark.parametrize("wrapper", [A.admin_streamable_post, A.admin_mcp_streamable_http])
def test_the_admin_server_announces_its_selection_changes_too(monkeypatch, wrapper):
    async def answered(request):
        body = await request.json()
        return JSONResponse(content={"jsonrpc": "2.0", "id": body["id"], "result": {"content": [], "isError": False}})
    monkeypatch.setattr(A, "handle_admin_rpc", answered)
    _, events = _answer(wrapper, _req(_call("theprotocol_enableToolset", ["canary"]), path="/mcp/admin"))
    assert events[0] == LIST_CHANGED and events[1]["id"] == 5
    _, events = _answer(wrapper, _req(_call("theprotocol_getAdminDashboard", None, rid=8), path="/mcp/admin"))
    assert events == [{"jsonrpc": "2.0", "id": 8, "result": {"content": [], "isError": False}}]


def test_changed_the_listing_reads_both_the_request_and_the_answer():
    ok = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"isError": False}})
    bad = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"isError": True}})
    assert G.changed_the_listing(_call(G.ENABLE_TOOLSET_TOOL, ["wallet"]), ok) is True
    assert G.changed_the_listing(_call(G.DISABLE_TOOLSET_TOOL, []), ok) is True
    assert G.changed_the_listing(_call(G.ENABLE_TOOLSET_TOOL, ["wallet"]), bad) is False
    assert G.changed_the_listing(_call("theprotocol_getMyBalance", None), ok) is False
    assert G.changed_the_listing(None, ok) is False and G.changed_the_listing(_call(G.ENABLE_TOOLSET_TOOL, []), "x") is False


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
