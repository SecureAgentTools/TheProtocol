"""§SUITES1018 batch 8 (2026-10-19): a row that names a developer account acts on the sweep's own, never another's.

Four layers filled {developer_id}, and every fallback named a real account: the admin_developers prereq registered a
throwaway but read its id from the registration answer, which is {message, recovery_keys} and never carries one, so it
fell back to "2"; the organizations prereq wrote "2" (its member fixture's id on the retired tier) over the same slot;
with the slot empty after the sweep's reset, the router sent "1" and the contract runner "1". On sbx-alpha developer 2 is
the tester's own sandbox admin and developer 1 the frame admin, and the rows sent there include revoke-api-keys, a quota
write and a provisioning gift (read 2026-10-19: none of developer 2's 771 API keys active, none of developer 1's 5).
Now a row naming {developer_id} acts on a throwaway the sweep registered for itself (consent fields sent, its id read
back from the admin list by its email), the org member rows on the member fixture's OWN id (read from its own token),
and with neither the row is NOT MEASURED; base's own category run writes to an id no account holds.

RED on e1e1ff52 (batch 7): every test_red_* fails there; the test_control_* ones pass on both.
"""
from __future__ import annotations

import asyncio
import json

import httpx

from agentvault_registry.api_tests import base as B

EMAIL_KEY = "apitest-dev-target-"


class _SharedValues(dict):
    async def refresh_from_redis(self):
        return None


class _Frame:
    """Registration, the admin developer list and the routes a row calls; records every request."""

    def __init__(self, monkeypatch, register_status=201, listed_id=9001):
        self.seen, self.registered = [], []
        self.register_status, self.listed_id = register_status, listed_id
        real = httpx.AsyncClient

        def _client(*a, **k):
            k["transport"] = httpx.MockTransport(self._handle)
            return real(*a, **k)
        monkeypatch.setattr(httpx, "AsyncClient", _client)

    def _handle(self, req):
        self.seen.append(req)
        p = req.url.path
        if p == "/api/v1/auth/register":
            self.registered.append(json.loads(req.content))
            return httpx.Response(self.register_status, json={"message": "ok", "recovery_keys": ["x"]})
        if p == "/api/v1/admin/developers":
            email = req.url.params.get("search")
            return httpx.Response(200, json={"developers": [{"id": self.listed_id, "email": email}], "total": 1,
                                             "limit": 5, "offset": 0})
        return httpx.Response(200, json={"items": []})

    def asked(self, fragment):
        return [r.url.path for r in self.seen if fragment in r.url.path]


def _router(monkeypatch, **values):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(**values))
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    monkeypatch.setattr(R, "_delegation_target", lambda: None)
    return R


def test_red_the_sweep_registers_its_own_developer_and_reads_its_id_back(monkeypatch):
    R = _router(monkeypatch)
    f = _Frame(monkeypatch)
    dev_id = asyncio.run(R._ensure_sweep_developer("admin-token"))
    assert dev_id == "9001" and R.DYNAMIC_VALUES["target_dev_own"] is True
    body = f.registered[0]
    assert body["email"].startswith(EMAIL_KEY) and body["age_confirmed"] is True and body["tos_accepted"] is True
    from agentvault_registry.input_validators import validate_password_strength
    validate_password_strength(body["password"])   # the rule the route applies
    # once made, the sweep keeps it: no second registration
    assert asyncio.run(R._ensure_sweep_developer("admin-token")) == "9001" and len(f.registered) == 1


def test_red_an_account_row_names_the_sweeps_own_developer(monkeypatch):
    R = _router(monkeypatch)
    _Frame(monkeypatch)
    out = asyncio.run(R.replace_path_placeholders("/admin/developers/{developer_id}/revoke-api-keys", "admin-token",
                                                  "agent-token", method="POST"))
    assert out == "/admin/developers/9001/revoke-api-keys"


def test_red_an_org_member_row_names_the_member_fixtures_own_id(monkeypatch):
    R = _router(monkeypatch, member_developer_id="4242", org_id="7")
    f = _Frame(monkeypatch)
    out = asyncio.run(R.replace_path_placeholders("/organizations/{org_id}/members/{developer_id}", "admin-token",
                                                  "agent-token", method="DELETE"))
    assert out.endswith("/members/4242") and f.registered == []   # {org_id} is the router's, later


def test_red_with_no_developer_of_its_own_the_row_is_not_measured_and_names_no_account(monkeypatch):
    R = _router(monkeypatch, agent_did="did:theprotocol:sweep")
    f = _Frame(monkeypatch, register_status=400)
    out = asyncio.run(R.test_endpoint(request=None, endpoint_test={
        "method": "POST", "path": "/admin/developers/{developer_id}/revoke-api-keys", "auth": "developer"},
        current_developer=None))
    assert out["not_measured"] is True and out["failure_bucket"] == "not_measured_fixture", out
    assert [p for p in f.asked("/admin/developers/") if p.endswith("/revoke-api-keys")] == []


def test_red_the_org_prereq_reads_its_member_fixtures_own_id_and_leaves_the_sweeps_slot(monkeypatch):
    R = _router(monkeypatch, org_id="7", target_dev_id="9001", target_dev_own=True)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(R, "_ensure_org", _noop)
    monkeypatch.setattr(R, "_ensure_team", _noop)
    seen = []
    real = httpx.AsyncClient

    def _handle(req):
        seen.append((req.method, req.url.path))
        p = req.url.path
        if p == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "dev2-token"})
        if p == "/api/v1/developers/me":
            return httpx.Response(200, json={"id": 4242, "email": "developer@test.sandbox"})
        if p == "/api/v1/organizations/7/members":
            return httpx.Response(200, json={"members": [{"developer_email": "developer@test.sandbox",
                                                          "developer_id": 4242}]})
        if p == "/api/v1/organizations/7/invite":
            return httpx.Response(200, json={"token": "inv-1"})
        return httpx.Response(200, json={})

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(_handle)
        return real(*a, **k)
    monkeypatch.setattr(httpx, "AsyncClient", _client)
    asyncio.run(R._setup_organizations("admin-token", "agent-token"))
    assert R.DYNAMIC_VALUES["member_developer_id"] == "4242"
    assert R.DYNAMIC_VALUES["target_dev_id"] == "9001"          # the sweep's own, untouched
    assert ("DELETE", "/api/v1/organizations/7/members/4242") in seen
    assert ("DELETE", "/api/v1/organizations/7/members/2") not in seen


def test_red_base_writes_name_no_account(monkeypatch):
    seen = []
    real = httpx.AsyncClient

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(lambda req: seen.append(req) or httpx.Response(200, json={}))
        return real(*a, **k)
    monkeypatch.setattr(httpx, "AsyncClient", _client)
    t = B.APITestBase(base_url="http://registry-test:8000")
    t._dynamic_ids.update(_populated=True, developer_id="3290")   # the first non-admin developer of the frame
    asyncio.run(t.test_endpoint(method="PATCH", path="/admin/developers/{developer_id}/quota", auth_type="developer",
                                developer_token="admin-token", body={"max_bundles": 5}))
    assert [r.url.path for r in seen] == ["/api/v1/admin/developers/2147483647/quota"]


def test_control_base_reads_may_name_any_developer(monkeypatch):
    seen = []
    real = httpx.AsyncClient

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(lambda req: seen.append(req) or httpx.Response(200, json={}))
        return real(*a, **k)
    monkeypatch.setattr(httpx, "AsyncClient", _client)
    t = B.APITestBase(base_url="http://registry-test:8000")
    t._dynamic_ids.update(_populated=True, developer_id="3290")
    asyncio.run(t.test_endpoint(method="GET", path="/admin/developers/{developer_id}/activity", auth_type="developer",
                                developer_token="admin-token"))
    assert [r.url.path for r in seen] == ["/api/v1/admin/developers/3290/activity"]
