"""§SUITES1018 batch 8 (part 5, 2026-10-19): reads that named nothing name a real row or a defined name.

In the V0625 sweep (2026-10-19) 47 rows read EF "templated path target doesn't exist in sandbox state (404 after
placeholder substitution)": the path named nothing, so the 404 measured the placeholder. Among the reads: a pref key
and a policy section are NAMES the route defines (any allowed one reads 200), a settlement, a transparent firm's feed
and an email template have a list to take a row from, and the channel and export routes answer only for an agent the
caller made (the sweep's agent is not its admin's). Writes on the same routes get no list fixture: a resolver may name a
real object, and a write would then act on it. The frame invitation DETAIL takes a row of the invitation list (its
prereq runs under a category name the catalog no longer uses, and also writes peer_id, so it stays unmapped); its
/licence-key child, a read that hands a new frame's parked licence key out once, is no call a sweep makes.

RED on 907294c3 (batch 8 parts 2-4): every test_red_* fails there; the test_control_* ones pass on both.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest


class _SharedValues(dict):
    async def refresh_from_redis(self):
        return None


LISTS = {
    "/api/v1/federation/disputes/settlements": {"count": 1, "settlements": [{"id": "stl-1"}]},
    "/api/v1/organizations/public/transparent": {"organizations": [{"id": "org-transparent"}]},
    "/api/v1/admin/email/preview": {"templates": ["welcome", "verify_email"], "themes": ["neural"]},
    "/api/v1/developers/me/agents": [{"did": "did:theprotocol:mine", "id": 1}],
    "/api/v1/admin/federation/frame-invitations": {"invitations": [{"id": "inv-1", "status": "completed"}]},
    "/api/v1/attestations": {"items": [{"id": "att-1", "agent_did": "did:theprotocol:x"}], "count": 1},
    "/api/v1/admin/broadcasts": [{"id": 77, "title": "t"}],
}


def _router(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(agent_did="did:theprotocol:sweep-agent"))
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    seen = []
    real = httpx.AsyncClient

    def _handle(req):
        seen.append(req.url.path)
        return httpx.Response(200, json=LISTS.get(req.url.path, {"items": []}))

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(_handle)
        return real(*a, **k)
    monkeypatch.setattr(httpx, "AsyncClient", _client)
    return R, seen


def _resolve(R, path, method="GET"):
    return asyncio.run(R.replace_path_placeholders(path, "admin-token", "agent-token", method=method))


@pytest.mark.parametrize("path,want", [
    ("/developers/me/prefs/{key}", "/developers/me/prefs/pocket.pulse"),
    ("/admin/enforcement/policy/section/{name}", "/admin/enforcement/policy/section/slash_waterfall"),
    ("/public/eventstore-stats/{key}", "/public/eventstore-stats/local"),
    ("/federation/disputes/settlements/{settlement_id}", "/federation/disputes/settlements/stl-1"),
    ("/organizations/{org_id}/public-feed", "/organizations/org-transparent/public-feed"),
    ("/admin/email/context/{template}", "/admin/email/context/welcome"),
    ("/agents/{did}/channel", "/agents/did:theprotocol:mine/channel"),
    ("/agents/{agent_did}/export", "/agents/did:theprotocol:mine/export"),
    ("/admin/federation/frame-invitations/{invitation_id}", "/admin/federation/frame-invitations/inv-1"),
    ("/attestations/{attestation_id}/bundle", "/attestations/att-1/bundle"),
    ("/attestations/{attestation_id}/verify", "/attestations/att-1/verify"),
    ("/admin/broadcasts/{broadcast_id}/stats", "/admin/broadcasts/77/stats"),
    ("/notifications/{broadcast_id}", "/notifications/77"),
])
def test_red_a_read_names_a_real_row_or_a_defined_name(monkeypatch, path, want):
    R, _ = _router(monkeypatch)
    assert _resolve(R, path) == want


def test_red_the_fixed_names_are_ones_the_routes_define():
    from agentvault_registry.crud import crud_enforcement
    from agentvault_registry.routers import admin_api_test as R
    from agentvault_registry.routers import developers as D
    fixed = {p: v for p, _, v in R._FIXED_READ_VALUES}
    assert fixed["/developers/me/prefs/{key}"] in D._PREF_KEYS
    assert fixed["/admin/enforcement/policy/section/{name}"] in crud_enforcement.DEFAULT_POLICY_JSON


def test_control_a_write_on_the_same_routes_gets_no_list_fixture(monkeypatch):
    R, seen = _router(monkeypatch)
    out = _resolve(R, "/federation/disputes/settlements/{settlement_id}/approve", method="POST")
    assert "stl-1" not in out and "/api/v1/federation/disputes/settlements" not in seen
    assert "pocket.pulse" not in _resolve(R, "/developers/me/prefs/{key}", method="PUT")


def test_control_the_licence_key_child_never_names_a_real_invitation(monkeypatch):
    R, _ = _router(monkeypatch)
    out = _resolve(R, "/admin/federation/frame-invitations/{invitation_id}/licence-key")
    assert "inv-1" not in out, out


def test_red_the_licence_key_handover_is_no_call_a_sweep_makes():
    from agentvault_registry.api_tests import base as B
    kind, why = B._classify_frame_control("GET", "/admin/federation/frame-invitations/inv-1/licence-key")
    assert kind == "credential" and "licence key" in why, (kind, why)


def test_red_the_diagnostics_config_read_names_this_frames_own_target(monkeypatch):
    R, _ = _router(monkeypatch)
    monkeypatch.setattr(R, "_self_diagnostics_target", lambda: "sandbox-alpha")
    assert _resolve(R, "/admin/diagnostics/config/{target_id}") == "/admin/diagnostics/config/sandbox-alpha"


def test_red_an_email_preview_render_names_a_listed_template_whatever_its_verb(monkeypatch):
    R, _ = _router(monkeypatch)
    assert _resolve(R, "/admin/email/preview/{template}/text", method="POST") == "/admin/email/preview/welcome/text"


@pytest.mark.parametrize("method,path", [("POST", "/notifications/{broadcast_id}/read"),
                                         ("POST", "/admin/broadcasts/{broadcast_id}/reinstate"),
                                         ("POST", "/attestations/{attestation_id}/revoke")])
def test_control_writes_on_listed_objects_get_no_fixture(monkeypatch, method, path):
    R, _ = _router(monkeypatch)
    out = _resolve(R, path, method=method)
    assert "77" not in out and "att-1" not in out, out


def test_red_the_admin_webhook_rows_act_on_the_sweeps_own_webhook(monkeypatch):
    from agentvault_registry.api_tests.contracts import load_all
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(agent_did="did:theprotocol:sweep-agent"))
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    monkeypatch.setattr(R, "_delegation_target", lambda: None)

    async def _tokens():
        return "admin-token", "agent-token"
    monkeypatch.setattr(R, "get_sandbox_tokens", _tokens)
    load_all()
    seen = []
    real = httpx.AsyncClient

    def _handle(req):
        seen.append((req.method, req.url.path))
        if req.url.path == "/api/v1/developers/webhooks" and req.method == "GET":
            return httpx.Response(200, json=[{"id": "wh-own", "url": "https://prereq-webhook.test/hook"}])
        if req.url.path == "/api/v1/admin/webhooks/wh-own/disable":
            return httpx.Response(200, json={"id": "wh-own", "is_active": False, "changed": True})
        return httpx.Response(404, json={"detail": "Webhook not found"})

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(_handle)
        return real(*a, **k)
    monkeypatch.setattr(httpx, "AsyncClient", _client)
    out = asyncio.run(R.test_endpoint(request=None, endpoint_test={
        "method": "POST", "path": "/admin/webhooks/{webhook_id}/disable", "auth": "developer"}, current_developer=None))
    assert ("POST", "/api/v1/admin/webhooks/wh-own/disable") in seen, seen
    assert out.get("status_code", out.get("statusCode")) == 200 and out.get("healthy") is True, out
