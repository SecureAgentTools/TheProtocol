"""§MCPTEST30 (V0554): the composite health checks wait DIAGNOSTIC_TIMEOUT (55 s), every other admin read the 30 s default.

Measured on the sandbox operators during the MCP tester's sweeps: getCombinedHealth 18-20 s and twice past 30 s (idle:
1.9 s), getAdminHealthCheckAuthenticated up to 37.9 s, getAdminWorkersStatus up to 35.6 s. Each calls many endpoints of
the same registry. 55 s stays below the 60 s a caller's docker exec waits (docker-py's default socket timeout).
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.mcp import tools_admin as T


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _capture(monkeypatch):
    seen = []

    async def get(auth, path, params=None, timeout=T.HTTPX_TIMEOUT):
        seen.append(("GET", path, timeout))
        return {}

    async def post(auth, path, json_body=None, timeout=T.HTTPX_TIMEOUT):
        seen.append(("POST", path, timeout))
        return {}
    monkeypatch.setattr(T, "_admin_get", get)
    monkeypatch.setattr(T, "_admin_post", post)
    return seen


@pytest.mark.parametrize("fn", ["get_combined_health", "get_admin_health_check_authenticated",
                                "get_admin_health_check_public_only", "get_health_check_with_agent_auth",
                                "get_admin_workers_status", "composite_health_check"])
def test_the_composite_checks_wait_the_diagnostic_budget(monkeypatch, fn):
    seen = _capture(monkeypatch)
    asyncio.run(getattr(T, fn)(None))
    assert seen and seen[0][2] == T.DIAGNOSTIC_TIMEOUT == 55.0, seen


def test_a_simple_read_keeps_the_default(monkeypatch):
    seen = _capture(monkeypatch)
    asyncio.run(T.get_admin_health_check_simple(None))
    assert seen[0][2] == T.HTTPX_TIMEOUT == 30.0


def test_the_budget_stays_below_the_callers_exec_wait():
    assert T.HTTPX_TIMEOUT < T.DIAGNOSTIC_TIMEOUT < 60.0
