"""§MCPTEST30 (V0524, 2026-10-01) — a tools/call argument of a JSON type its tool cannot take is -32602, before the tool.

The dispatchers handed arguments to the tool unchecked: the MCP tester's type-confusion probe (every read tool, one
mistyped argument per call, sbx-alpha on V0521) counted 72 of 107 calls answering -32603 "Internal error" (an integer
sent as "abc" reached the tool's int() or max()), 20 answering -32602 and 2 crashing inside the tool.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from starlette.requests import Request

from agentvault_registry.mcp.arguments import argument_problems

SCHEMA = {"properties": {
    "limit": {"type": "integer"}, "amount": {"type": "number"}, "flag": {"type": "boolean"},
    "items": {"type": "array"}, "body": {"type": "object"}, "name": {"type": "string"},
    "maybe": {"type": ["string", "null"]}, "client_secret": {"type": "string"},
}}


@pytest.mark.parametrize("args", [
    {"limit": 10}, {"limit": "10"}, {"limit": 10.0}, {"limit": " -3 "}, {"limit": None},
    {"amount": 1.5}, {"amount": "1.5"}, {"amount": 7},
    {"flag": True}, {"flag": "false"}, {"flag": 0},
    {"items": ["a"]}, {"items": "a,b"}, {"body": {"k": 1}}, {"body": '{"k": 1}'},
    {"name": "x"}, {"name": 5}, {"maybe": None}, {"undeclared": [1, 2]},
])
def test_what_a_caller_can_mean_is_taken(args):
    assert argument_problems(SCHEMA, args) == []


@pytest.mark.parametrize("args,want", [
    ({"limit": "abc"}, "limit: expected integer, got str 'abc'"),
    ({"limit": True}, "limit: expected integer, got bool True"),
    ({"limit": 1.5}, "limit: expected integer, got float 1.5"),
    ({"limit": [1]}, "limit: expected integer, got list [1]"),
    ({"amount": "NaN"}, "amount: expected number, got str 'NaN'"),
    ({"amount": "inf"}, "amount: expected number, got str 'inf'"),
    ({"flag": "maybe"}, "flag: expected boolean, got str 'maybe'"),
    ({"items": 5}, "items: expected array, got int 5"),
    ({"body": ["x"]}, "body: expected object, got list ['x']"),
    ({"name": {"a": 1}}, "name: expected string, got dict {'a': 1}"),
    ({"maybe": [1]}, "maybe: expected string or null, got list [1]"),
    ({"client_secret": {"s": "do-not-echo"}}, "client_secret: expected string, got dict"),
])
def test_what_nothing_can_mean_is_named(args, want):
    assert argument_problems(SCHEMA, args) == [want]


def _req(path, body):
    raw = json.dumps(body).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    return Request({"type": "http", "method": "POST", "path": path, "query_string": b"",
                    "headers": [(b"content-type", b"application/json"), (b"authorization", b"Bearer phase6-token")]},
                   receive)


def _call(handler, path, tool, args):
    resp = asyncio.run(handler(_req(path, {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                            "params": {"name": tool, "arguments": args}})))
    return json.loads(resp.body)


def test_the_public_dispatcher_answers_invalid_params_before_the_tool():
    from agentvault_registry.mcp import server
    out = _call(server.handle_rpc, "/mcp/rpc", "theprotocol_discoverAgents", {"limit": "abc"})
    assert out["error"]["code"] == -32602
    assert out["error"]["message"] == "Invalid params: limit: expected integer, got str 'abc'"


def test_the_admin_dispatcher_answers_invalid_params_before_the_tool():
    from agentvault_registry.mcp import server_admin
    out = _call(server_admin.handle_admin_rpc, "/mcp/admin/rpc", "theprotocol_getAdminAuditLogs", {"limit": "abc"})
    assert out["error"]["code"] == -32602
    assert "limit: expected integer, got str 'abc'" in out["error"]["message"]


def test_every_tool_schema_is_reachable_by_name():
    from agentvault_registry.mcp import server, server_admin
    assert server._input_schema("theprotocol_guildListOrders") is not None      # extended after the definition
    assert server_admin._input_schema("theprotocol_searchTools") is not None    # the gateway, extended too
