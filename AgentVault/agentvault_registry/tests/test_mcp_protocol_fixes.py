"""§MCPTEST30 (2026-10-01) — the MCP protocol defects the conformance lifecycle found, fixed and pinned.

Measured live on sbx-alpha by lifecycle_mcp_protocol_conformance:
  * a posted notification was answered 200 (public) or with an error (admin, any notification but `initialized`);
    MCP Streamable HTTP accepts one with 202 and no body;
  * prompts/get without a required argument rendered the prompt with empty holes; MCP answers -32602;
  * every resources/read error was HTTP 500, an unknown URI included; a resource that is not there is the client's miss
    (-32002, HTTP 404), an upstream failure stays a server failure (-32603, HTTP 500);
  * theprotocol://registry/openapi was unreadable everywhere: it fetched /openapi.json, which answers 308 to
    /api/v1/openapi.json since §pass52 PR-12, and the fetch follows no redirect.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from starlette.requests import Request

from agentvault_registry.mcp import prompts, resources
from agentvault_registry.mcp import server as S
from agentvault_registry.mcp import server_admin as A


def _req(body, *, path="/mcp/rpc", bearer=None, accept="application/json"):
    raw = (body if isinstance(body, str) else json.dumps(body)).encode()
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


def _json(resp):
    return json.loads(resp.body.decode()) if getattr(resp, "body", b"") else None


def test_missing_required_prompt_arguments_are_named():
    assert prompts.missing_required("fund_agent", {"agent_did": "did:x"}) == ["amount"]
    assert prompts.missing_required("fund_agent", {"agent_did": "did:x", "amount": "  "}) == ["amount"]
    assert prompts.missing_required("fund_agent", {"agent_did": "did:x", "amount": 5}) == []
    assert prompts.missing_required("no_such_prompt", {}) == []


def test_prompts_get_without_a_required_argument_is_minus_32602():
    resp = asyncio.run(S.handle_rpc(_req({"jsonrpc": "2.0", "id": 1, "method": "prompts/get",
                                          "params": {"name": "fund_agent", "arguments": {"agent_did": "did:x"}}})))
    body = _json(resp)
    assert resp.status_code == 400 and body["error"]["code"] == -32602 and "amount" in body["error"]["message"]
    ok = asyncio.run(S.handle_rpc(_req({"jsonrpc": "2.0", "id": 2, "method": "prompts/get",
                                        "params": {"name": "fund_agent", "arguments": {"agent_did": "did:x", "amount": "3"}}})))
    assert ok.status_code == 200 and "did:x" in json.dumps(_json(ok)["result"])


def test_a_resource_that_is_not_there_is_404_and_an_upstream_failure_stays_500():
    nf = resources.ResourceNotFound("unknown resource URI: theprotocol://x")
    assert resources.error_code(nf) == -32002 and resources.error_code("fetch failed") == -32603
    assert S._jsonrpc_error(1, -32002, "x").status_code == 404 and S._jsonrpc_error(1, -32603, "x").status_code == 500
    assert A._err(1, -32002, "x").status_code == 404 and A._err(1, -32603, "x").status_code == 500
    resp = asyncio.run(S.handle_rpc(_req({"jsonrpc": "2.0", "id": 3, "method": "resources/read",
                                          "params": {"uri": "theprotocol://mcp-tester/none"}})))
    assert resp.status_code == 404 and _json(resp)["error"]["code"] == -32002


def test_the_openapi_resource_reads_the_canonical_route():
    route = resources._WELL_KNOWN_ROUTES["theprotocol://registry/openapi"]
    assert route.endswith("/openapi.json") and route != "/openapi.json" and route.startswith("/api/")


@pytest.mark.parametrize("module,wrapper,handler,path,bearer", [
    (S, "mcp_streamable_post", "handle_rpc", "/mcp", None),
    (A, "admin_streamable_post", "handle_admin_rpc", "/mcp/admin", "an-admin-bearer"),
])
def test_a_notification_is_accepted_with_202_and_no_body(monkeypatch, module, wrapper, handler, path, bearer):
    seen = []

    async def fake_handler(request):
        seen.append((await request.json()).get("method"))
        from fastapi.responses import JSONResponse
        return JSONResponse(content={"jsonrpc": "2.0", "id": None, "result": {}})
    monkeypatch.setattr(module, handler, fake_handler)
    note = _req({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}}, path=path,
                bearer=bearer, accept="application/json, text/event-stream")
    resp = asyncio.run(getattr(module, wrapper)(note))
    assert resp.status_code == 202 and not resp.body and seen == ["notifications/cancelled"], "handled, then 202"
    # control: a REQUEST (it has an id) still gets its answer
    reqm = _req({"jsonrpc": "2.0", "id": 7, "method": "ping"}, path=path, bearer=bearer)
    resp = asyncio.run(getattr(module, wrapper)(reqm))
    assert resp.status_code == 200 and _json(resp)["jsonrpc"] == "2.0"


def test_the_admin_handler_accepts_every_notification(monkeypatch):
    """The /mcp/admin/rpc handler itself: notifications/cancelled was -32601 + HTTP 404 (only `initialized` was known)."""
    src = open(A.__file__).read()
    assert 'elif method.startswith("notifications/"):' in src and 'elif method == "notifications/initialized":' not in src


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
