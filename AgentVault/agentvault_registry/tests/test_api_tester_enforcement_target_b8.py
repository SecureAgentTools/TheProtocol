"""§SUITES1018 batch 8 (part 8, 2026-10-19): the enforcement rows act on an agent the sweep made for them alone.

They acted on the sweep's PRIMARY agent. In the V0625 sweep (2026-10-19) the contract row POST
/admin/enforcement/agents/{agent_did}/suspend suspended it at 06:17:35Z, two seconds after the reinstate row, so it
stayed suspended (read on sbx-alpha: the agent made at 06:05:48Z, the sweep's start, is suspended still), and every
later row acting as that agent was refused: the delegation grant (POST /agents/{did}/delegations) and POST
/agents/act-token, the sweep's two FAILs no isolated rehearsal reproduced. The approve and reject flows charged it with
offenses too (approve escalates to a level-3 action and approves it), and the category prereq funded and staked it.
Now an enforcement target is made once per sweep through the onboarding flow, funded and staked at birth (the slash
preview reads its position), and named by the router, the contract runner and both flows; with none, a DID of nothing.

RED on 893f9f70 (batch 8 part 7): every test_red_* fails there; the part 8b ones (below its marker) also fail on
f2d0a566 (part 8). The test_control_* ones pass on all three.
"""
from __future__ import annotations

import asyncio
import json

import httpx

PRIMARY = "did:theprotocol:sweep-primary"
TARGET = "did:theprotocol:enforcement-target"
NOTHING = "did:theprotocol:apitest-no-enforcement-target"


class _SharedValues(dict):
    async def refresh_from_redis(self):
        return None


def _frame(monkeypatch):
    seen = []
    real = httpx.AsyncClient

    def _handle(req):
        seen.append((req.method, req.url.path, json.loads(req.content) if req.content and req.headers.get(
            "content-type", "").startswith("application/json") else None))
        p = req.url.path
        if p == "/api/v1/onboard/bootstrap/request-token":
            return httpx.Response(200, json={"bootstrap_token": "bt"})
        if p == "/api/v1/onboard/create_agent":
            return httpx.Response(201, json={"agent_did": TARGET, "client_id": "c", "client_secret": "s"})
        if p == "/api/v1/auth/agent/token":
            return httpx.Response(200, json={"access_token": "target-token"})
        if p.endswith("/record-offense"):
            return httpx.Response(200, json={"action_id": "act-1", "status": "pending_approval"})
        return httpx.Response(200, json={"ok": True, "items": []})

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(_handle)
        return real(*a, **k)
    monkeypatch.setattr(httpx, "AsyncClient", _client)
    return seen


def _router(monkeypatch, **values):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(agent_did=PRIMARY, **values))
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    monkeypatch.setattr(R, "_delegation_target", lambda: None)

    async def _tokens():
        return "admin-token", "primary-token"
    monkeypatch.setattr(R, "get_sandbox_tokens", _tokens)
    return R


def test_red_the_target_is_made_once_funded_and_staked(monkeypatch):
    R = _router(monkeypatch)
    seen = _frame(monkeypatch)
    assert asyncio.run(R._ensure_enforcement_target("admin-token")) == TARGET
    assert asyncio.run(R._ensure_enforcement_target("admin-token")) == TARGET
    assert [p for m, p, b in seen if p == "/api/v1/onboard/create_agent"] == ["/api/v1/onboard/create_agent"]
    fund = [b for m, p, b in seen if p == "/api/v1/teg/treasury/fund-agent"]
    assert fund and fund[0]["target_agent_did"] == TARGET
    assert [p for m, p, b in seen if p == "/api/v1/staking/stake"] == ["/api/v1/staking/stake"]


def test_red_the_router_names_the_target_never_the_primary(monkeypatch):
    R = _router(monkeypatch, enforcement_target_did=TARGET)
    _frame(monkeypatch)
    out = asyncio.run(R.replace_path_placeholders("/admin/enforcement/agents/{agent_did}/suspend", "admin-token",
                                                  "primary-token", method="POST"))
    assert out == f"/admin/enforcement/agents/{TARGET}/suspend"


def test_red_with_no_target_the_row_names_nothing(monkeypatch):
    R = _router(monkeypatch)
    _frame(monkeypatch)
    out = asyncio.run(R.replace_path_placeholders("/admin/enforcement/agents/{agent_did}/reinstate", None,
                                                  "primary-token", method="POST"))
    assert out == f"/admin/enforcement/agents/{NOTHING}/reinstate"


def test_red_the_suspend_contract_suspends_the_target(monkeypatch):
    from agentvault_registry.api_tests.contracts import load_all
    R = _router(monkeypatch, enforcement_target_did=TARGET)
    seen = _frame(monkeypatch)
    load_all()
    asyncio.run(R.test_endpoint(request=None, endpoint_test={
        "method": "POST", "path": "/admin/enforcement/agents/{agent_did}/suspend", "auth": "developer"},
        current_developer=None))
    suspends = [p for m, p, b in seen if p.endswith("/suspend")]
    assert suspends == [f"/api/v1/admin/enforcement/agents/{TARGET}/suspend"], suspends


def test_red_the_reject_flow_charges_the_target(monkeypatch):
    R = _router(monkeypatch, enforcement_target_did=TARGET)
    seen = _frame(monkeypatch)
    asyncio.run(R.test_endpoint(request=None, endpoint_test={
        "method": "POST", "path": "/admin/enforcement/pending/{action_id}/reject", "auth": "developer"},
        current_developer=None))
    offenses = [p for m, p, b in seen if p.endswith("/record-offense")]
    assert offenses and all(TARGET in p for p in offenses), offenses
    assert not [p for p in offenses if PRIMARY in p]


def test_control_other_agent_routes_still_name_the_primary(monkeypatch):
    R = _router(monkeypatch, enforcement_target_did=TARGET)
    _frame(monkeypatch)
    out = asyncio.run(R.replace_path_placeholders("/agents/{agent_did}/reputation", "admin-token", "primary-token",
                                                  method="GET"))
    assert out == f"/agents/{PRIMARY}/reputation", out


# ── part 8b: every admin action on one agent names the target; V0625 moved the agent the sweep acted as ──────────────

def _row(R, method, path):
    return asyncio.run(R.test_endpoint(request=None, endpoint_test={"method": method, "path": path,
                                                                    "auth": "developer"}, current_developer=None))


def test_red_the_ironhand_revoke_and_the_admin_key_rotation_name_the_target(monkeypatch):
    from agentvault_registry.api_tests.contracts import load_all
    R = _router(monkeypatch, enforcement_target_did=TARGET)
    seen = _frame(monkeypatch)
    load_all()
    _row(R, "POST", "/admin/ironhand/revoke/{agent_did}")
    _row(R, "POST", "/admin/agents/{did}/rotate-signing-key")
    hits = [p for m, p, b in seen if p.endswith("/rotate-signing-key") or "/admin/ironhand/revoke/" in p]
    assert hits == [f"/api/v1/admin/ironhand/revoke/{TARGET}", f"/api/v1/admin/agents/{TARGET}/rotate-signing-key"], hits


def test_red_transfer_ownership_moves_the_target_to_the_sweeps_own_developer(monkeypatch):
    R = _router(monkeypatch, enforcement_target_did=TARGET, target_dev_id="9001", target_dev_own=True)
    seen = _frame(monkeypatch)
    _row(R, "POST", "/admin/agents/{agent_did}/transfer-ownership")
    calls = [(p, b) for m, p, b in seen if p.endswith("/transfer-ownership")]
    assert calls and calls[-1][0] == f"/api/v1/admin/agents/{TARGET}/transfer-ownership", calls
    assert calls[-1][1]["new_creator_developer_id"] == 9001, calls


def test_control_an_admin_read_of_the_agent_keeps_the_primary(monkeypatch):
    R = _router(monkeypatch, enforcement_target_did=TARGET)
    _frame(monkeypatch)
    out = asyncio.run(R.replace_path_placeholders("/admin/agents/{agent_did}", "admin-token", "primary-token",
                                                  method="GET"))
    assert out == f"/admin/agents/{PRIMARY}", out
