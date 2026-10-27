"""§TESTBED (2026-09-19): a kit frame's licence sync reaches a store that serves only its mTLS gateway.

A central registry sends licence control-plane syncs to the store's direct port (derived http://<name>-event-store:8200);
a kit store listens only behind its gateway, so every cloud operator of a kit frame was missing from the parent's
federation_operators. A refused connection (nothing sent) now retries over EVENT_STORE_URL with the registry's SVID.
"""
import httpx
import pytest

from agentvault_registry.routers import federation_licenses as fl


class _Client:
    calls = []
    refuse = set()

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        _Client.calls.append(url)
        if any(url.startswith(r) for r in _Client.refuse):
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"status": "created"})


@pytest.fixture
def client(monkeypatch):
    _Client.calls, _Client.refuse = [], set()
    monkeypatch.setattr(fl.httpx, "AsyncClient", _Client)
    monkeypatch.setattr("agentvault_registry.es_ssl_helper.get_httpx_verify", lambda: True)
    monkeypatch.setenv("IS_CENTRAL_REGISTRY", "true")
    monkeypatch.setenv("EVENT_STORE_URL", "https://larchsbx-nginx-event-store:8443")
    monkeypatch.delenv("EVENT_STORE_INTERNAL_URL", raising=False)
    return _Client


async def test_a_kit_store_takes_the_sync_over_its_gateway(client):
    client.refuse = {"http://larchsbx-event-store:8200"}
    ok = await fl._sync_license_to_eventstore("lic-1", "larchsbxop", "h" * 64, "active", spiffe_id="spiffe://x/operator/o/registry")
    assert ok is True
    assert client.calls == ["http://larchsbx-event-store:8200/api/v1/events/operators/sync",
                            "https://larchsbx-nginx-event-store:8443/api/v1/events/operators/sync"]


async def test_a_store_that_listens_on_its_direct_port_is_not_asked_twice(client):
    ok = await fl._sync_license_to_eventstore("lic-1", "op", "h" * 64, "active")
    assert ok is True and client.calls == ["http://larchsbx-event-store:8200/api/v1/events/operators/sync"]


async def test_no_gateway_to_fall_back_to_reports_false(client, monkeypatch):
    monkeypatch.setenv("EVENT_STORE_URL", "http://larchsbx-event-store:8200")   # a plain store: derived == configured
    client.refuse = {"http://larchsbx-event-store:8200"}
    assert await fl._sync_license_to_eventstore("lic-1", "op", "h" * 64, "active") is False
    assert len(client.calls) == 1
