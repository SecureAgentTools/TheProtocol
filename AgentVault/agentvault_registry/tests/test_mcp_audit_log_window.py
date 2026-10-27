"""§MCPTEST30 V0614 (2026-10-14): getAdminAuditLogs passes the route's window.

`GET /admin/audit-logs` always took `since_hours` (1-720, default 24) and the MCP tool never sent it, so no MCP caller could
look past one day: the tester's partition probe over the system actor read NOT MEASURED whenever a day held too few system
rows (on sbx-alpha those are the sandbox sim's breaker trips, and the sim stopped 2026-10-12). The tool now passes it, clamped
to the route's bounds, and sends nothing when it is not given (the route's own default stands).
"""
from __future__ import annotations

import asyncio

from agentvault_registry.mcp import server_admin, tools_admin


def _params(monkeypatch, **kw):
    seen = {}

    async def fake_get(auth, path, params=None, **_k):
        seen["path"], seen["params"] = path, dict(params or {})
        return {"items": []}
    monkeypatch.setattr(tools_admin, "_admin_get", fake_get)
    asyncio.run(tools_admin.get_admin_audit_logs(None, **kw))
    assert seen["path"] == "/api/v1/admin/audit-logs"
    return seen["params"]


def test_the_window_reaches_the_route(monkeypatch):
    assert _params(monkeypatch, actor_type="system", since_hours=720)["since_hours"] == 720


def test_the_window_is_clamped_to_the_routes_bounds(monkeypatch):
    assert _params(monkeypatch, since_hours=5000)["since_hours"] == 720
    assert _params(monkeypatch, since_hours=0)["since_hours"] == 1


def test_no_window_asked_sends_none(monkeypatch):
    assert "since_hours" not in _params(monkeypatch, actor_type="system")


def test_the_schema_declares_it_within_the_routes_bounds():
    schema = next(t for t in server_admin.ADMIN_TOOL_SCHEMAS if t["name"] == "theprotocol_getAdminAuditLogs")["inputSchema"]
    prop = schema["properties"]["since_hours"]
    assert prop["type"] == "integer" and prop["minimum"] == 1 and prop["maximum"] == 720
