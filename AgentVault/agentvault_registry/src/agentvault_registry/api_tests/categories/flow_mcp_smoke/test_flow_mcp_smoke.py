"""MCP Smoke Flow.

Verifies the MCP server's HTTP surface is up + each shipped tier-1 tool
returns a valid response. The MCP server is mounted at /mcp (NOT /api/v1/mcp)
per main.py:612.

Catches:
  • MCP route regressions (tool added but route never registered)
  • Tool schema regressions (rename → silent break for Claude Desktop / claude.ai)
  • MCP server crash/down

Sandbox-only.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict

from agentvault_registry.api_tests.base import APITestBase
from agentvault_registry.api_tests.multiframe_helpers import (
    SANDBOX_TARGET, get_target,
    exec_in_container, _split_http_body_code, _HTTP_MARKER,
)

logger = logging.getLogger(__name__)


# Tier-1 (no auth) MCP tools — these should be callable by any client.
# Tool names are prefixed with `theprotocol_` per the MCP server's tool
# registration; verified via GET /mcp/rpc tools/list response.
# searchTools added 2026-07-14: the gateway is the flagship connect path
# post-V0151, so the smoke must prove discovery works, not just legacy reads.
TIER_1_TOOLS = [
    {"name": "theprotocol_discoverAgents", "args": {"query": "test", "limit": 5}},
    {"name": "theprotocol_discoverRegistries", "args": {}},
    {"name": "theprotocol_getNetworkStats", "args": {}},
    {"name": "theprotocol_getLockPayoutTiers", "args": {}},
    {"name": "theprotocol_searchTools", "args": {"query": "transfer tokens"}},
]


async def _mcp_get(target, path: str, jwt: str = "") -> tuple[bool, dict, str]:
    """GET to MCP server (mounted at /mcp on registry-test).
    Includes optional Bearer auth — MCP server requires it for /tools and /rpc."""
    auth_header = f"-H 'Authorization: Bearer {jwt}'" if jwt else ""
    rc, out = await asyncio.to_thread(
        exec_in_container, target.a_registry_container, [
            "sh", "-c",
            f"curl -sS {auth_header} -w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            f"http://localhost:8000{path}",
        ], 15,
    )
    body, code = _split_http_body_code(out)
    if rc != 0:
        return False, {"_raw": body[:200]}, code
    if not (code and code.startswith("2")):
        return False, {"_raw": body[:200]}, code
    try:
        return True, json.loads(body), code
    except Exception:
        return True, {"_raw": body[:200]}, code


async def _mcp_rpc_call(target, tool_name: str, arguments: dict, jwt: str = "") -> tuple[bool, dict, str]:
    """JSON-RPC tools/call against the MCP server. Authenticated."""
    auth_header = f"-H 'Authorization: Bearer {jwt}'" if jwt else ""
    rpc_body = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
        "id": int(time.time() * 1000) % 1_000_000,
    }
    body_b64 = base64.b64encode(json.dumps(rpc_body).encode()).decode()
    rc, out = await asyncio.to_thread(
        exec_in_container, target.a_registry_container, [
            "sh", "-c",
            f"echo '{body_b64}' | base64 -d > /tmp/mcp_rpc.json && "
            f"curl -sS -X POST {auth_header} "
            f"-H 'Content-Type: application/json' "
            f"-d @/tmp/mcp_rpc.json "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            "http://localhost:8000/mcp/rpc",
        ], 20,
    )
    body, code = _split_http_body_code(out)
    if rc != 0:
        return False, {"_raw": body[:200]}, code
    try:
        parsed = json.loads(body) if body else {}
    except Exception:
        parsed = {"_raw": body[:200]}
    # Honesty (2026-07-14): success = 2xx AND no JSON-RPC "error" AND the
    # CallToolResult itself does not report isError — since the reference-
    # grade pass the server sets isError:true on tool-level failures, so
    # "reachable" no longer masquerades as "working".
    has_error = isinstance(parsed, dict) and "error" in parsed
    tool_errored = (
        isinstance(parsed, dict)
        and isinstance(parsed.get("result"), dict)
        and parsed["result"].get("isError") is True
    )
    ok = code.startswith("2") and not has_error and not tool_errored
    return ok, parsed, code


class TestFlowMcpSmoke(APITestBase):
    CATEGORY_NAME = "flow_mcp_smoke"
    flow_values: Dict[str, Any] = {}

    async def setup(self):
        await self.setup_category(self.CATEGORY_NAME)
        self.flow_values = {}

    async def teardown(self):
        return

    async def test_all(self, developer_token=None, agent_token=None):
        std = await self.test_category_endpoints(
            category=self.CATEGORY_NAME,
            developer_token=developer_token,
            agent_token=agent_token,
            priority_only=False,
        )
        std["flow_tests"] = await self.test_mcp_smoke_flow(developer_token)
        return std

    async def test_mcp_smoke_flow(self, developer_token: str) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info("Starting MCP Smoke Flow")
        logger.info("=" * 60)

        target = get_target("sandbox")
        results = []

        # Login as sandbox admin to get a developer JWT for MCP auth
        from agentvault_registry.api_tests.multiframe_helpers import login_admin
        ok_a, dev_jwt, det = await login_admin(target, "a")
        if not ok_a:
            results.append({
                "step": 0, "name": "Sandbox-A admin login (for MCP auth)",
                "path": "/auth/login", "method": "POST", "authRequired": "none",
                "healthy": False, "statusCode": 500,
                "responseData": {"detail": det}, "error": det,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return self._summarize(results, False)

        # Step 1: GET /mcp/health (no auth needed for health)
        ok, body, code = await _mcp_get(target, "/mcp/health")
        results.append({
            "step": 1, "name": "GET /mcp/health",
            "path": "/mcp/health", "method": "GET", "authRequired": "none",
            "healthy": ok, "statusCode": int(code) if code.isdigit() else 500,
            "responseData": body if isinstance(body, dict) else {"raw": str(body)[:200]},
            "error": None if ok else f"http={code}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not ok:
            return self._summarize(results, False)

        # Step 2: GET /mcp/tools — honest floor: the catalog is ~410 tools;
        # ≥100 still tolerates bucket drift but catches a real listing
        # regression (the old ≥10 floor would have green-lit a catalog wipe).
        ok, body, code = await _mcp_get(target, "/mcp/tools", jwt=dev_jwt)
        tool_list = []
        if isinstance(body, dict):
            tool_list = body.get("tools") or body.get("result", {}).get("tools") or []
        elif isinstance(body, list):
            tool_list = body
        tool_count = len(tool_list) if isinstance(tool_list, list) else 0
        tool_names = [t.get("name") for t in tool_list if isinstance(t, dict)] if isinstance(tool_list, list) else []
        list_ok = ok and tool_count >= 100
        results.append({
            "step": 2, "name": "GET /mcp/tools (≥100 tools registered)",
            "path": "/mcp/tools", "method": "GET", "authRequired": "none",
            "healthy": list_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "tool_count": tool_count,
                "expected_min": 100,
                "tool_names_sample": tool_names[:8],
            },
            "error": None if list_ok else f"only {tool_count} tools, expected ≥100",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Step 3-N: invoke each tier-1 tool via JSON-RPC
        all_passed = True
        for idx, tool in enumerate(TIER_1_TOOLS):
            ok, body, code = await _mcp_rpc_call(target, tool["name"], tool["args"], jwt=dev_jwt)
            # Some tools may legitimately require sandbox-A to have data;
            # accept any 2xx with non-error JSON-RPC body as "tool reachable".
            results.append({
                "step": 3 + idx, "name": f"MCP tool: {tool['name']}",
                "path": "/mcp/rpc", "method": "POST", "authRequired": "none",
                "healthy": ok,
                "statusCode": int(code) if code.isdigit() else 500,
                "responseData": {
                    "tool": tool["name"],
                    "args": tool["args"],
                    "result_excerpt": str(body)[:200],
                },
                "error": None if ok else f"tool {tool['name']} unreachable: {code}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            if not ok:
                all_passed = False

        self.flow_values = {
            "tool_count": tool_count,
            "tier_1_tools_passed": sum(1 for r in results[2:] if r.get("healthy")),
            "tier_1_tools_total": len(TIER_1_TOOLS),
        }
        return self._summarize(results, True)

    def _summarize(self, results, flow_success: bool) -> Dict[str, Any]:
        total = len(results)
        ok = sum(1 for r in results if r.get("healthy"))
        return {
            "flow_name": "flow_mcp_smoke_complete",
            "success": flow_success and ok == total,
            "total_steps": total,
            "successful_steps": ok,
            "results": results,
            "flow_values": dict(self.flow_values),
        }
