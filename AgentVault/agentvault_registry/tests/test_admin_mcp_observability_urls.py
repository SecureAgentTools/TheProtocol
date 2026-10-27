"""§DOCSFIX D6-251 (2026-10-16): adminPromQuery and adminGrafanaQuery dial the Prometheus and Grafana a registry names.

The two admin MCP tools read `getattr(settings, "PROMETHEUS_URL" / "GRAFANA_URL", <default>)`. Settings declares neither
field (it ignores unknown environment keys), so the getattr always answered its literal default: the tools dialed
http://prometheus:9090 and http://grafana:3000 whatever the registry set, while every other Prometheus reader honours
PROMETHEUS_URL through core/observability_urls.prometheus_url(). Prometheus now goes through that one reader, Grafana
through its sibling grafana_url(), both at call time.
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.mcp import tools_admin as T
from agentvault_registry.mcp.auth_bridge import MCPAuthContext

ADMIN = MCPAuthContext(auth_type="developer", developer_id=1, is_admin=True, raw_token="x")
GRAFANA_TEST_PASSWORD = "grafana-test-credential-not-a-secret"


class _Resp:
    status_code = 200
    text = "{}"

    def json(self):
        return {"status": "success", "data": {"resultType": "vector", "result": []}}


@pytest.fixture
def dialed(monkeypatch):
    urls = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            urls.append(url)
            return _Resp()

    monkeypatch.setattr(T.httpx, "AsyncClient", _Client)
    return urls


def test_prometheus_is_the_one_the_registry_names(monkeypatch, dialed):
    monkeypatch.setenv("PROMETHEUS_URL", "http://prometheus.frame.internal:9091/")
    out = asyncio.run(T.admin_prom_query(ADMIN, query="up"))
    assert out["ok"] is True
    assert dialed == ["http://prometheus.frame.internal:9091/api/v1/query"]


def test_grafana_is_the_one_the_registry_names(monkeypatch, dialed):
    monkeypatch.setenv("GRAFANA_ADMIN_PASS", GRAFANA_TEST_PASSWORD)   # without one the tool refuses (wave 3)
    monkeypatch.setenv("GRAFANA_URL", "http://grafana.frame.internal:3001")
    out = asyncio.run(T.admin_grafana_query(ADMIN, path="/api/health"))
    assert out["status_code"] == 200
    assert dialed == ["http://grafana.frame.internal:3001/api/health"]


def test_unset_falls_back_to_the_shared_defaults(monkeypatch, dialed):
    monkeypatch.delenv("PROMETHEUS_URL", raising=False)
    monkeypatch.setenv("GRAFANA_URL", "")                 # empty is unset, never a dial of ""
    monkeypatch.setenv("GRAFANA_ADMIN_PASS", GRAFANA_TEST_PASSWORD)
    asyncio.run(T.admin_prom_query(ADMIN, query="up"))
    asyncio.run(T.admin_grafana_query(ADMIN, path="/api/health"))
    from agentvault_registry.core.observability_urls import DEFAULT_PROMETHEUS_URL
    assert dialed == [f"{DEFAULT_PROMETHEUS_URL}/api/v1/query", "http://grafana:3000/api/health"]
