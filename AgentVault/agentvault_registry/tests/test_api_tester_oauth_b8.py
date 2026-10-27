"""§SUITES1018 batch 8 (2026-10-19): OAuth introspection and revocation reach their handlers and say what they found.

Both routes take FORM fields, the calling client's own credentials among them (routers/oauth_federation: introspect_token
and revoke_token, client_id and client_secret are Form(...)). In the V0625 sweep (2026-10-19) both read NOT MEASURED
"runner gap": their AAA+ contracts send JSON only (core/contract.py), and the sandbox-mode introspection body dropped
the client fields and carried the sweep's live developer JWT, to a route that reads a token's claims back. Now neither
runs a contract (a form route goes the legacy way, which sends form bodies), both send a well-formed form body naming
a token that is none, and the answer a frame with no trusted registry gives by design (501, fail-closed) is recorded as
the capability it is. The sweep adds no trust entry of its own: one would switch the frame's OAuth surface on for every
caller.

RED on e1e1ff52 (batch 7): every test_red_* fails there; the test_control_* ones pass on both.
"""
from __future__ import annotations

import asyncio
from urllib.parse import parse_qs

import httpx

from agentvault_registry.api_tests import base as B
from agentvault_registry.api_tests.request_bodies import RequestBodies


def test_red_neither_oauth_form_route_runs_a_contract():
    from agentvault_registry.api_tests.contracts import load_all
    from agentvault_registry.api_tests.core.contract import get_contract
    from agentvault_registry.routers import admin_api_test as R
    load_all()
    for path in ("/oauth/introspect", "/oauth/revoke"):
        assert get_contract("POST", path) is not None, path       # the contract exists; the router skips it
        assert R._contract_for("POST", path) is None, path


def test_control_a_json_route_beside_them_keeps_its_contract():
    from agentvault_registry.api_tests.contracts import load_all
    from agentvault_registry.routers import admin_api_test as R
    load_all()
    assert R._contract_for("POST", "/oauth/token/exchange") is not None


def _form_ok(body):
    return (isinstance(body, dict) and body.get("client_id") and body.get("client_secret") and body.get("token")
            and not str(body.get("token")).startswith("eyJ") and body.get("token") != "SANDBOX_DEV_TOKEN_PLACEHOLDER")


def test_red_both_send_a_well_formed_form_body_with_a_token_that_is_none():
    rb = RequestBodies()
    assert rb.is_form_data("/oauth/revoke") and rb.is_form_data("/oauth/introspect")
    assert _form_ok(rb.get_body("/oauth/revoke")), rb.get_body("/oauth/revoke")
    rb.enable_sandbox_mode(agent_did="did:theprotocol:sweep", agent_002_did="did:theprotocol:counterparty")
    assert _form_ok(rb.get_body("/oauth/introspect")), rb.get_body("/oauth/introspect")


def test_red_the_fail_closed_501_is_the_capability_it_is():
    reason, bucket = B._classify_capability_gate("/oauth/introspect", 501)
    assert "not enabled" in reason and bucket == "capability_absent"
    assert B._classify_capability_gate("/oauth/revoke", 501)[1] == "capability_absent"


def test_control_a_refused_client_on_a_configured_federation_is_not_stamped():
    assert B._classify_capability_gate("/oauth/introspect", 401) == ("", "")


class _SharedValues(dict):
    async def refresh_from_redis(self):
        return None


def test_red_the_router_sends_revocation_as_a_form_and_records_the_501(monkeypatch):
    from agentvault_registry.api_tests.core import catalog_sync as CS
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(agent_did="did:theprotocol:sweep"))
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    monkeypatch.setattr(R, "_delegation_target", lambda: None)

    async def _catalog(*a, **k):
        return {"oauth_federation": [{"method": "POST", "path": "/oauth/revoke", "auth": "none",
                                      "category": "oauth_federation"}]}
    monkeypatch.setattr(CS, "build_catalog", _catalog)
    seen = []
    real = httpx.AsyncClient

    def _handle(req):
        seen.append(req)
        if req.url.path == "/api/v1/oauth/revoke":
            return httpx.Response(501, json={"detail": "Cross-registry OAuth federation is not enabled on this registry "
                                                       "(no active trusted registries configured)."})
        return httpx.Response(200, json={"items": []})

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(_handle)
        return real(*a, **k)
    monkeypatch.setattr(httpx, "AsyncClient", _client)
    out = asyncio.run(R.test_endpoint(request=None, endpoint_test={"method": "POST", "path": "/oauth/revoke",
                                                                   "auth": "none"}, current_developer=None))
    calls = [r for r in seen if r.url.path == "/api/v1/oauth/revoke"]
    assert calls, (out, [r.url.path for r in seen])
    form = parse_qs(calls[-1].content.decode())
    assert form.get("client_id") and form.get("client_secret") and form.get("token"), form
    assert out.get("statusCode") == 501 and out.get("expected_failure") is True, out
    assert "not enabled" in (out.get("expected_failure_reason") or ""), out
