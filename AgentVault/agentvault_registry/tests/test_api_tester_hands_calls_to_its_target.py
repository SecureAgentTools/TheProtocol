"""§SUITES1018 (2026-10-18): a console whose api-tester targets ANOTHER registry hands each call to that registry.

Measured 2026-10-18 on EU, whose tester targets sbx-alpha: the api-tester ran every endpoint HERE with tokens it can
only mint for its own sandbox (the sandbox token path keys on the `registry-test` alias and logs in with SANDBOX_ADMIN_*,
which a production console does not carry), so sbx-alpha refused 6,607 calls with 401 in one sweep and then 429 once
its admin throttle counted them; 870 of the 2026-09-09 baseline's 1,189 rows were 401 (807 filed as expected
failures). Now the catalog, the flow values, the reset, the bootstrap, each test-endpoint call and each flow are sent
to the target's same route with the tester key, which runs them with its own credentials, as it already did for the
MCP tester's flows. A console whose tester targets itself (every sandbox frame) runs them here, as before.

RED on 9ac0925c: there is no hand-off (the handlers execute here with the console's own bearer).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agentvault_registry.routers import admin_api_test as aat

KEY = "q" * 43
TARGET = "http://sbx-alpha-registry:8000"


class _Client:
    """Stands in for httpx.AsyncClient: records the one forwarded request, answers like the target."""
    sent = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, params=None, content=None, headers=None):
        _Client.sent.append({"method": method, "url": url, "params": params,
                             "json": json.loads(content) if content else None, "headers": dict(headers or {})})
        return SimpleNamespace(status_code=200, json=lambda: {"success": True, "status_code": 200}, text="")


def _request(path, method="POST", query=None, payload=None):
    """The request as the route receives it: the console's own bearer, and the body bytes FastAPI parsed."""
    raw = json.dumps(payload).encode() if payload is not None else b""

    async def body():
        return raw
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path), query_params=query or {}, body=body,
                           headers={"Authorization": "Bearer console.own.jwt", "content-type": "application/json"})


@pytest.fixture()
def console(monkeypatch):
    """A console whose tester targets sbx-alpha and that holds the tester key (EU's configuration)."""
    monkeypatch.setattr(aat, "API_TEST_TARGET_URL", TARGET)
    monkeypatch.setenv("API_TEST_PROXY_INTERNAL_KEY", KEY)
    _Client.sent = []
    monkeypatch.setattr(aat.httpx, "AsyncClient", _Client)


def test_red_a_console_targeting_another_registry_hands_its_calls_over(console):   # BASE: no _delegation_target
    assert aat._delegation_target() == TARGET


async def test_red_a_test_endpoint_call_goes_to_the_target_with_the_key_and_without_the_consoles_bearer(console):
    body = {"method": "GET", "path": "/admin/developers", "body": None}
    r = await aat.test_endpoint(_request("/api/v1/admin/api-test/test-endpoint", payload=body), body, None)
    assert len(_Client.sent) == 1, _Client.sent
    sent = _Client.sent[0]
    assert sent["url"] == TARGET + "/api/v1/admin/api-test/test-endpoint" and sent["method"] == "POST", sent
    assert sent["json"] == body, sent
    # the console's own bearer is not forwarded: the tester key and the body's type, nothing else
    assert sent["headers"] == {"X-Internal-Key": KEY, "Content-Type": "application/json"}, sent
    assert r.status_code == 200 and b'"delegated_to"' in r.body, r.body


async def test_red_the_catalog_and_the_reset_go_to_the_target(console):
    await aat.get_all_endpoints(_request("/api/v1/admin/api-test/endpoints", "GET", {"source": "openapi"}), "openapi",
                                False, None)
    await aat.reset_flow_values(_request("/api/v1/admin/api-test/reset-flow-values"), None)
    urls = [s["url"] for s in _Client.sent]
    assert urls == [TARGET + "/api/v1/admin/api-test/endpoints", TARGET + "/api/v1/admin/api-test/reset-flow-values"], urls
    assert _Client.sent[0]["params"] == {"source": "openapi"}, _Client.sent[0]


async def test_a_target_that_does_not_answer_is_a_502_naming_it(console, monkeypatch):
    class _Down(_Client):
        async def request(self, *a, **k):
            raise aat.httpx.ConnectError("refused")
    monkeypatch.setattr(aat.httpx, "AsyncClient", _Down)
    r = await aat.get_flow_values(_request("/api/v1/admin/api-test/flow-values", "GET"), None)
    assert r.status_code == 502 and TARGET.encode() in r.body, r.body


@pytest.mark.parametrize("target", ["http://registry-test:8000", "http://localhost:8000", "http://127.0.0.1:8000"])
def test_control_a_console_whose_tester_targets_itself_runs_here(console, monkeypatch, target):
    monkeypatch.setattr(aat, "API_TEST_TARGET_URL", target)
    assert aat._delegation_target() is None


def test_control_without_the_key_nothing_is_handed_over(console, monkeypatch):
    monkeypatch.delenv("API_TEST_PROXY_INTERNAL_KEY")
    assert aat._delegation_target() is None


def test_control_a_refused_key_shape_hands_nothing_over(console, monkeypatch):
    monkeypatch.setenv("API_TEST_PROXY_INTERNAL_KEY", "short")
    assert aat._delegation_target() is None
