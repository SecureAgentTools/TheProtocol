"""§F6 stage 3 (2026-09-27): a central registry's licence sync reaches a store that refuses the internal key for a change.

Every store of this network runs EVENTSTORE_MTLS_REQUIRED, and since §SECFIX-7 the internal key there authenticates reads
only: the direct port ANSWERS, 403 "mtls_required: ...". The provisioner's direct-DB upsert hid it on a registry holding
the docker socket; through the frame runner an operator got no federation_operators row at all (sbx-beta, b1opa and
b1opb). That refusal now retries over EVENT_STORE_URL with the registry's SVID, where the store keeps the frame's own
licensing rights (§SOVKIT T5). Any other refusal is about authority, not transport, and is never retried.
"""
import httpx
import pytest

from agentvault_registry.routers import federation_licenses as fl

DIRECT = "http://sbx-beta-event-store:8200"
GATEWAY = "https://sbx-beta-nginx-event-store:8443"
MTLS_REQUIRED = {"detail": "mtls_required: the internal key no longer authenticates a change to this store; send it "
                           "through this frame's TLS terminator with the service's SPIRE certificate",
                 "type": "about:blank", "title": "Forbidden", "status": 403}


class _Client:
    calls = []        # (url, the client's kwargs)
    answers = {}      # url prefix -> httpx.Response

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        _Client.calls.append((url, self.kwargs))
        for prefix, resp in _Client.answers.items():
            if url.startswith(prefix):
                return resp
        return httpx.Response(200, json={"status": "created"})


@pytest.fixture
def client(monkeypatch):
    _Client.calls, _Client.answers = [], {}
    monkeypatch.setattr(fl.httpx, "AsyncClient", _Client)
    monkeypatch.setattr("agentvault_registry.es_ssl_helper.get_httpx_verify", lambda: "the-svid-context")
    monkeypatch.setenv("IS_CENTRAL_REGISTRY", "true")
    monkeypatch.setenv("EVENT_STORE_URL", GATEWAY)
    monkeypatch.delenv("EVENT_STORE_INTERNAL_URL", raising=False)
    return _Client


def _urls(client):
    return [u for u, _ in client.calls]


async def _sync(status="active"):
    return await fl._sync_license_to_eventstore("lic-1", "b1opb", "h" * 64, status,
                                                spiffe_id="spiffe://sandbox-b.theprotocol.cloud/operator/b1opb/registry")


async def test_a_store_that_refuses_the_key_for_a_change_takes_it_over_its_gateway(client):
    client.answers = {DIRECT: httpx.Response(403, json=MTLS_REQUIRED)}
    assert await _sync() is True
    assert _urls(client) == [f"{DIRECT}/api/v1/events/operators/sync", f"{GATEWAY}/api/v1/events/operators/sync"]
    direct_kwargs, gateway_kwargs = client.calls[0][1], client.calls[1][1]
    assert "cert" not in direct_kwargs, "the internal path never presents a certificate"
    assert gateway_kwargs.get("verify") == "the-svid-context", "the gateway gets the registry's SVID context"


async def test_a_status_change_takes_the_same_way(client):
    client.answers = {DIRECT: httpx.Response(403, json=MTLS_REQUIRED)}
    assert await _sync("revoked") is True
    assert len(client.calls) == 2


async def test_a_refusal_about_authority_is_not_retried(client):
    """Control: a 403 that is not the transport refusal (here the store's own licensing rule) stays a refusal."""
    client.answers = {DIRECT: httpx.Response(403, json={"detail": "license_key_hash updates require internal auth "
                                                                  "(mainframe registry only)"})}
    assert await _sync() is False
    assert _urls(client) == [f"{DIRECT}/api/v1/events/operators/sync"]


async def test_a_403_that_is_not_json_is_not_retried(client):
    """Control: an nginx error page is not the store's refusal."""
    client.answers = {DIRECT: httpx.Response(403, text="<html>403 Forbidden</html>")}
    assert await _sync() is False
    assert len(client.calls) == 1


async def test_a_store_that_takes_the_key_is_asked_once(client):
    """Control: a store that still accepts the key (EVENTSTORE_INTERNAL_KEY_WRITES=allow) is not asked twice."""
    assert await _sync() is True
    assert _urls(client) == [f"{DIRECT}/api/v1/events/operators/sync"]


async def test_the_gateway_refusing_too_reports_false_once(client):
    """No loop: the gateway's own refusal is the answer."""
    client.answers = {DIRECT: httpx.Response(403, json=MTLS_REQUIRED),
                      GATEWAY: httpx.Response(403, json={"detail": "Unknown SPIFFE ID"})}
    assert await _sync() is False
    assert len(client.calls) == 2


async def test_no_gateway_to_fall_back_to_reports_false(client, monkeypatch):
    """Control: a plain store (EVENT_STORE_URL is the direct port itself) has nowhere else to go."""
    monkeypatch.setenv("EVENT_STORE_URL", DIRECT)
    client.answers = {DIRECT: httpx.Response(403, json=MTLS_REQUIRED)}
    assert await _sync() is False
    assert len(client.calls) == 1


async def test_off_mainframe_the_first_call_is_already_the_gateway(client, monkeypatch):
    """Control: an operator's own registry (not central) syncs over the gateway from the start; a refusal there is
    not retried against itself."""
    monkeypatch.delenv("IS_CENTRAL_REGISTRY", raising=False)
    client.answers = {GATEWAY: httpx.Response(403, json=MTLS_REQUIRED)}
    assert await _sync() is False
    assert _urls(client) == [f"{GATEWAY}/api/v1/events/operators/sync"]
