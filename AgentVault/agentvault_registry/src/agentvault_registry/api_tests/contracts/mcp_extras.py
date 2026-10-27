"""MCP server + MCP OAuth extras (AAA+ Phase IV-A, 2026-05-21).

NOTE: MCP game subservers (/mcp/td/*, /mcp/snake/*, etc.) are EXCLUDED via overrides.yaml.
This module covers the core MCP server (rpc/sse/tools) + MCP OAuth discovery.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="POST", path="/mcp/rpc", auth="none", category="mcp_server", idempotent=True)
class MCPRpc:
    """MCP JSON-RPC entrypoint."""
    def body(self, ctx):
        return {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    expected_status = [200, 401, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (401, 422),
            reason="MCP RPC may require auth context or specific request shape",
        ),
    ]


@Endpoint(method="GET", path="/mcp/sse", auth="none", category="mcp_server", idempotent=True)
class MCPSSE:
    """MCP Server-Sent Events stream."""
    expected_status = [200, 406, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (406, 422),
            reason="SSE requires Accept: text/event-stream",
        ),
    ]


@Endpoint(method="POST", path="/mcp/sse", auth="none", category="mcp_server", idempotent=False)
class MCPSSEPost:
    """MCP SSE write endpoint."""
    def body(self, ctx):
        return {}
    expected_status = [200, 400, 405, 422]
