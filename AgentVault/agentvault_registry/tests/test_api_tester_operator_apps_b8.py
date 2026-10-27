"""§SUITES1018 batch 8 (part 6, 2026-10-19): the operator application rows act on a test application, never a person's.

The operators_admin prereq seeded {application_id} with the admin list's first row: the newest application of ANY
applicant. The sweep then approved it and rotated its pull token (V0625, 06:21Z: the federation suite's fixture, by
luck of the order), and the health, logs and restart rows named it too. A stranger's fresh application would have been
approved, and a running operator's (sbx-alpha's own sbxalphaop is in the same list) could have lost its pull token.
Now only a TEST application qualifies: the testers' reserved domain, already approved, neither activated nor
cloud-hosted; with none, nothing is named. Restarting a running operator's service and provisioning one are no call a
sweep makes, whatever they name.

RED on 907294c3 (batch 8 parts 2-4): every test_red_* fails there; the ones below the part 6b marker also fail on
48dee5ef (parts 5-6: the router left the placeholder to base, whose own seed named the newest application). The
test_control_* ones pass on all three.
"""
from __future__ import annotations

import asyncio

import httpx

from agentvault_registry.api_tests import base as B


class _SharedValues(dict):
    async def refresh_from_redis(self):
        return None


def _prereq(monkeypatch, apps):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues())
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    real = httpx.AsyncClient

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(lambda req: httpx.Response(200, json={"applications": apps}))
        return real(*a, **k)
    monkeypatch.setattr(httpx, "AsyncClient", _client)
    asyncio.run(R._setup_operators_admin("admin-token", "agent-token"))
    return R.DYNAMIC_VALUES.get("application_id")


STRANGER = {"id": "stranger", "email": "someone@example.com", "status": "pending"}
OPERATOR = {"id": "running-op", "email": "admin@sbx-alpha.dev", "status": "approved", "cloud_hosted": True,
            "activated_developer_id": 1}
ACTIVATED = {"id": "activated", "email": "candidate@test.sandbox", "status": "approved", "activated_developer_id": 9}
FIXTURE = {"id": "fixture", "email": "candidate@test.sandbox", "status": "approved", "cloud_hosted": False}


def test_red_the_newest_strangers_or_operators_application_is_never_named(monkeypatch):
    assert _prereq(monkeypatch, [STRANGER, OPERATOR, ACTIVATED, FIXTURE]) == "fixture"


def test_red_with_no_test_application_nothing_is_named(monkeypatch):
    assert _prereq(monkeypatch, [STRANGER, OPERATOR, ACTIVATED]) is None


def test_red_restarting_or_provisioning_an_operator_is_no_call_a_sweep_makes():
    for route, kind in (("/admin/cloud-operators/a1/restart-service", "frame_control"),
                        ("/admin/cloud-operators/a1/provision", "suite_launch")):
        assert B._classify_frame_control("POST", route)[0] == kind, route


def test_control_reading_an_operators_health_stays_a_call(monkeypatch):
    assert B._classify_frame_control("GET", "/admin/cloud-operators/a1/health") == ("", "")
    assert B._classify_frame_control("POST", "/admin/operator-applications/a1/rotate-pull-token") == ("", "")


# ── the second half (part 6b): the router left the placeholder to base, and base's own seed named the newest ─────────

def test_red_base_seeds_a_test_application_or_none(monkeypatch):
    seen = []
    real = httpx.AsyncClient

    def _handle(req):
        seen.append((req.method, req.url.path))
        if req.url.path == "/api/v1/admin/operator-applications":
            return httpx.Response(200, json={"applications": [STRANGER, OPERATOR, FIXTURE]})
        return httpx.Response(200, json={"items": []})

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(_handle)
        return real(*a, **k)
    monkeypatch.setattr(httpx, "AsyncClient", _client)
    t = B.APITestBase(base_url="http://registry-test:8000")
    asyncio.run(t.test_endpoint(method="POST", path="/admin/operator-applications/{application_id}/approve",
                                auth_type="developer", developer_token="admin-token", agent_token="agent-token"))
    approves = [p for m, p in seen if p.endswith("/approve")]
    assert approves == ["/api/v1/admin/operator-applications/fixture/approve"], approves


def test_red_the_router_never_leaves_the_application_placeholder_to_base(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(application_id=None, agent_did="did:theprotocol:x"))
    out = asyncio.run(R.replace_path_placeholders("/admin/operator-applications/{application_id}/approve",
                                                  "admin-token", "agent-token", method="POST"))
    assert out == "/admin/operator-applications/00000000-0000-0000-0000-0000000ffead/approve", out


def test_red_the_prereq_runs_under_the_catalogs_category_names():
    from agentvault_registry.routers import admin_api_test as R
    for cat in ("operator_applications", "cloud_operators_admin", "operators_admin"):
        assert R.CATEGORY_PREREQS.get(cat) is R._setup_operators_admin, cat


def test_red_the_test_application_rule_is_one_predicate():
    assert B.is_test_operator_application(FIXTURE)
    for app in (STRANGER, OPERATOR, ACTIVATED, {**FIXTURE, "status": "pending"}, None, "x"):
        assert not B.is_test_operator_application(app), app


def test_control_the_testers_dicts_hold_each_key_once():
    import ast
    import collections
    import pathlib
    from agentvault_registry.api_tests import request_bodies as RB
    from agentvault_registry.routers import admin_api_test as R
    dups = []
    for mod in (R, B, RB):
        for node in ast.walk(ast.parse(pathlib.Path(mod.__file__).read_text())):
            if isinstance(node, ast.Dict):
                c = collections.Counter(repr(k.value) for k in node.keys if isinstance(k, ast.Constant))
                dups += [(mod.__name__, k) for k, n in c.items() if n > 1]
    assert dups == [], dups
