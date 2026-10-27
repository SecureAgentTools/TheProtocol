"""§SUITES1018 batch 8 (part 4, 2026-10-19): the developer-account actions are measured on accounts of the sweep's own.

Suspend, force-password-reset, the emergency 2FA unlock and DELETE were withheld as destructive while {developer_id}
could name a real account (developer 2, the tester's own admin, or 1, the frame admin: finding 47). Since part 1 it
names the sweep's own throwaway or nothing, so the router marks the one call that acts on it and base lets that call
through; DELETE gets a throwaway made for it alone (it soft-deletes what it names, and the category's later rows still
act on the target), with its confirmation read from the flow values (the catalog dict is per worker). PUT admin-flags
sends False: True went to the tester's own admin (400 "cannot modify your own flags") and on a throwaway would make an
admin of an account nobody signs in to.

RED on 9669b622 (batch 8 part 1): every test_red_* fails there; the test_control_* ones pass on both.
"""
from __future__ import annotations

import asyncio
import itertools
import json

import httpx
import pytest

from agentvault_registry.api_tests import base as B

ADMIN = "admin-token"


class _SharedValues(dict):
    async def refresh_from_redis(self):
        return None


class _Frame:
    """Registration, the admin list, and the developer-account routes; records every request."""

    def __init__(self, monkeypatch):
        self.seen, self.devs = [], {}
        self.ids = itertools.count(7001)
        real = httpx.AsyncClient

        def _client(*a, **k):
            k["transport"] = httpx.MockTransport(self._handle)
            return real(*a, **k)
        monkeypatch.setattr(httpx, "AsyncClient", _client)

    def _handle(self, req):
        self.seen.append(req)
        p = req.url.path
        body = json.loads(req.content) if req.content else {}
        if p == "/api/v1/auth/register":
            i = next(self.ids)
            self.devs[i] = {"id": i, "email": body["email"], "deleted": False, "suspended": False}
            return httpx.Response(201, json={"message": "ok", "recovery_keys": ["x"]})
        if p == "/api/v1/admin/developers":
            q = req.url.params.get("search", "")
            rows = [{"id": d["id"], "email": d["email"]} for d in self.devs.values() if q in d["email"]]
            return httpx.Response(200, json={"developers": rows, "total": len(rows)})
        if p.startswith("/api/v1/admin/developers/"):
            seg = p.split("/")
            d = self.devs.get(int(seg[5])) if seg[5].isdigit() else None
            if not d:
                return httpx.Response(404, json={"detail": "Developer not found"})
            if req.method == "DELETE":
                if body.get("confirm_email") != d["email"]:
                    return httpx.Response(400, json={"detail": "confirm_email does not match"})
                d["deleted"] = True
                return httpx.Response(200, json={"developer_id": d["id"], "status": "deleted"})
            if p.endswith("/suspend"):
                d["suspended"] = True
            if p.endswith("/disable-2fa"):
                return httpx.Response(400, json={"detail": "Developer does not have 2FA enabled"})
            return httpx.Response(200, json={"developer_id": d["id"], "status": "ok"})
        return httpx.Response(200, json={"items": []})

    def calls(self, suffix=""):
        return [(r.method, r.url.path, json.loads(r.content) if r.content else None) for r in self.seen
                if r.url.path.startswith("/api/v1/admin/developers/") and r.url.path.endswith(suffix)]


def _router(monkeypatch):
    from agentvault_registry.api_tests.core import catalog_sync as CS
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(agent_did="did:theprotocol:sweep"))
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    monkeypatch.setattr(R, "_delegation_target", lambda: None)

    async def _tokens():
        return ADMIN, "agent-token"
    monkeypatch.setattr(R, "get_sandbox_tokens", _tokens)

    async def _catalog(*a, **k):
        return {"admin_developer_management": [
            {"method": m, "path": p, "auth": "developer", "category": "admin_developer_management"}
            for m, p in (("POST", "/admin/developers/{developer_id}/suspend"),
                         ("POST", "/admin/developers/{developer_id}/force-password-reset"),
                         ("POST", "/admin/developers/{developer_id}/disable-2fa"),
                         ("DELETE", "/admin/developers/{developer_id}"),
                         ("PUT", "/admin/developers/{developer_id}/admin-flags"))]}
    monkeypatch.setattr(CS, "build_catalog", _catalog)
    return R


def _row(R, method, path):
    return asyncio.run(R.test_endpoint(request=None, endpoint_test={"method": method, "path": path,
                                                                    "auth": "developer"}, current_developer=None))


@pytest.mark.parametrize("suffix", ["/suspend", "/force-password-reset"])
def test_red_an_account_action_is_measured_on_the_sweeps_own_throwaway(monkeypatch, suffix):
    R = _router(monkeypatch)
    f = _Frame(monkeypatch)
    out = _row(R, "POST", "/admin/developers/{developer_id}" + suffix)
    assert out.get("statusCode") == 200 and out.get("healthy") is True and not out.get("not_measured"), out
    (call,) = f.calls(suffix)
    target = int(R.DYNAMIC_VALUES["target_dev_id"])
    assert call[1] == f"/api/v1/admin/developers/{target}{suffix}"
    assert f.devs[target]["email"].startswith("apitest-dev-target-")


def test_red_the_2fa_unlock_on_the_throwaway_is_an_accepted_refusal(monkeypatch):
    R = _router(monkeypatch)
    _Frame(monkeypatch)
    out = _row(R, "POST", "/admin/developers/{developer_id}/disable-2fa")
    assert out.get("statusCode") == 400 and out.get("expected_failure") is True, out
    assert "no second factor" in (out.get("expected_failure_reason") or ""), out


def test_red_delete_acts_on_a_throwaway_made_for_it_alone_with_its_confirmation(monkeypatch):
    R = _router(monkeypatch)
    f = _Frame(monkeypatch)
    assert _row(R, "POST", "/admin/developers/{developer_id}/suspend")["healthy"] is True   # the target exists first
    out = _row(R, "DELETE", "/admin/developers/{developer_id}")
    assert out.get("statusCode") == 200 and out.get("healthy") is True, out
    (call,) = [c for c in f.calls() if c[0] == "DELETE"]
    victim = int(R.DYNAMIC_VALUES["delete_dev_id"])
    assert call[1] == f"/api/v1/admin/developers/{victim}" and call[2]["confirm_email"] == f.devs[victim]["email"]
    assert f.devs[victim]["email"].startswith("apitest-dev-delete-")
    assert victim != int(R.DYNAMIC_VALUES["target_dev_id"]) and not f.devs[int(R.DYNAMIC_VALUES["target_dev_id"])]["deleted"]


def test_red_admin_flags_is_measured_and_grants_nothing(monkeypatch):
    R = _router(monkeypatch)
    f = _Frame(monkeypatch)
    out = _row(R, "PUT", "/admin/developers/{developer_id}/admin-flags")
    assert out.get("statusCode") == 200, out
    (call,) = f.calls("/admin-flags")
    assert call[2] == {"admin_support": False}


def test_control_an_unmarked_account_action_stays_withheld():
    B._VERIFIED_SWEEP_OWN.clear()
    for m, p in (("POST", "/admin/developers/2/suspend"), ("POST", "/admin/developers/1/force-password-reset"),
                 ("DELETE", "/admin/developers/2")):
        assert B._classify_destructive(m, p), (m, p)


def test_red_a_marked_call_is_let_through_and_only_that_one():
    B.mark_sweep_own("POST", "/admin/developers/7001/suspend")
    assert B._classify_destructive("POST", "/admin/developers/7001/suspend") == ""
    assert B._classify_destructive("POST", "/admin/developers/7002/suspend")       # another account: withheld
    assert B._classify_destructive("POST", "/admin/developers/7001/revoke-key")   # another action: by its own rules
    B._VERIFIED_SWEEP_OWN.clear()
