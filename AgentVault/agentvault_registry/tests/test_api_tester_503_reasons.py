"""§SUITES1018 batch 7 (2026-10-19): a 503 is an expected failure only when its own sentence says why.

The router's fallback stamped EVERY 503 "TEG service not implemented - expected". In the V0624 sweep (2026-10-18) six
rows read so and none was a TEG route: the operator self-service routes (a frame answers that they are for cloud
operators only), the showcase session and onboard (switched off, or no payer configured), and the IRONHAND probe. A 503
is also what an outage answers ("Could not issue a showcase session right now.", a store or a pool that is down), and
the stamp passed those as expected too. Each refusal by design is now named by its own sentence and any other 503
stays a finding. The admin IRONHAND probe fires a real transfer of up to 10 units between real agents; on sbx-alpha it
was refused only because no demo fallback is configured there, so it is NOT MEASURED before it is ever called.

RED on 23f0fa76 (batch 7 part 1): every test_red_* fails there; the test_control_* ones pass on both.
"""
from __future__ import annotations

import asyncio
import json

import httpx

from agentvault_registry.api_tests import base as B
from agentvault_registry.api_tests.core import catalog_sync as CS

ROUTES = {
    "/api/v1/operator-portal/self-logs": (503, {"detail": "Operator self-logs is for cloud-ops only. Mainframe admins "
                                                          "use /admin/cloud-operators/{id}/logs."}),
}


class _SharedValues(dict):
    async def refresh_from_redis(self):
        return None


class _Target:
    def __init__(self, monkeypatch, answers):
        self.answers, self.seen = answers, []
        real = httpx.AsyncClient

        def _client(*a, **k):
            k["transport"] = httpx.MockTransport(self._handle)
            return real(*a, **k)
        monkeypatch.setattr(httpx, "AsyncClient", _client)

    def _handle(self, req):
        self.seen.append(req)
        if req.url.path in self.answers:
            st, body = self.answers[req.url.path]
            return httpx.Response(st, content=json.dumps(body), headers={"content-type": "application/json"})
        return httpx.Response(200, json={"items": []})


def _row(monkeypatch, method, path, auth, answers):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(agent_did="did:theprotocol:sweep"))
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    monkeypatch.setattr(R, "_delegation_target", lambda: None)

    async def _catalog(*a, **k):
        return {"rows": [{"method": method, "path": path, "auth": auth, "category": "rows"}]}
    monkeypatch.setattr(CS, "build_catalog", _catalog)
    t = _Target(monkeypatch, answers)
    out = asyncio.run(R.test_endpoint(request=None, endpoint_test={"method": method, "path": path, "auth": auth},
                                      current_developer=None))
    return out, t


def _reason(out):
    return out.get("expected_failure_reason") or out.get("ef_reason") or ""


def test_red_an_operators_own_route_on_a_frame_names_why(monkeypatch):
    out, _ = _row(monkeypatch, "GET", "/operator-portal/self-logs", "developer", ROUTES)
    assert out.get("statusCode") == 503 and out.get("expected_failure") is True, out
    assert "cloud operators only" in _reason(out) and "TEG" not in _reason(out), _reason(out)


def test_red_a_showcase_that_could_not_issue_a_session_is_a_finding(monkeypatch):
    out, _ = _row(monkeypatch, "POST", "/public/showcase/session", "none",
                  {"/api/v1/public/showcase/session": (503, {"error": "Could not issue a showcase session right now."})})
    assert out.get("statusCode") == 503 and not out.get("expected_failure"), out
    assert out.get("healthy") is False, out


def test_red_a_showcase_switched_off_says_so(monkeypatch):
    out, _ = _row(monkeypatch, "POST", "/public/showcase/session", "none",
                  {"/api/v1/public/showcase/session": (503, {"error": "The showcase is disabled on this deployment.",
                                                             "enabled": False})})
    assert out.get("expected_failure") is True and "switched off" in _reason(out), out


def test_control_a_showcase_with_no_payer_says_so(monkeypatch):
    out, _ = _row(monkeypatch, "POST", "/public/showcase/session", "none",
                  {"/api/v1/public/showcase/session": (503, {"error": "This registry has no showcase identity configured, "
                                                                      "so it cannot issue a session.", "configured": False})})
    assert out.get("expected_failure") is True, out


def test_red_the_admin_ironhand_probe_is_not_measured_before_any_call(monkeypatch):
    assert B._classify_frame_control("POST", "/admin/ironhand/probe")[0] == "moves_money"
    out, t = _row(monkeypatch, "POST", "/admin/ironhand/probe", "developer", {})
    assert out["not_measured"] is True and out["failure_bucket"] == "not_measured_moves_money", out
    assert [r for r in t.seen if r.url.path == "/api/v1/admin/ironhand/probe"] == []


def test_control_the_ironhand_reads_are_measured():
    for p in ("/admin/ironhand/status", "/admin/ironhand/identities", "/admin/ironhand/probe/history"):
        assert B._classify_frame_control("GET", p) == ("", ""), p
