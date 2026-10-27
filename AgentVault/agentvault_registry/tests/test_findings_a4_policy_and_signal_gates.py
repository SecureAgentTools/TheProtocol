"""§FINDINGS-A4 3a + 3b (2026-09-27, his "fix 1-4 approved"): who may write TEG policies, and who may signal.

3a: every TEG policy WRITE (create, batch, update, delete) took any developer and forwarded the registry's own TEG admin
key, so any account could rewrite the reward an admin's attestation verification pays from the treasury. They now require
`admin_treasury`; the reads stay developer-level.
3b: the reputation-signal route asked for `reputation.signal` (service-provider only) while the TEG accepts a signal only
from the transfer's SENDER (the paying client): the §BUYSERVICE class. It now asks for `teg.transfer`, what the caller did.
"""
import ast
import os
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.agent_authz import ROLE_PERMISSIONS
from agentvault_registry.routers import teg_integration as ti

SRC = os.path.join(os.path.dirname(ti.__file__), "teg_integration.py")


def _deps(name):
    fn = next(n for n in ast.walk(ast.parse(open(SRC).read())) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    defaults = fn.args.defaults + [k for k in fn.args.kw_defaults if k is not None]
    return [ast.unparse(d) for d in defaults if "Depends(" in ast.unparse(d) or "Security(" in ast.unparse(d)]


@pytest.mark.parametrize("name", ["create_teg_policy", "create_teg_policies_batch", "update_teg_policy", "delete_teg_policy"])
def test_every_policy_write_requires_admin_treasury(name):
    assert _deps(name) == ["Security(security.require_admin_flag('admin_treasury'))"]


@pytest.mark.parametrize("name", ["list_teg_policies", "get_teg_policy", "get_policy_compliance_dashboard"])
def test_control_policy_reads_stay_developer_level(name):
    assert _deps(name) == ["Depends(security.get_current_developer)"]


def test_the_signal_route_asks_what_its_caller_did():
    assert _deps("apply_reputation_signal") == ["Security(require_agent_permission('teg.transfer'))"]


def test_control_attestation_keeps_its_own_permission():
    assert _deps("submit_attestation") == ["Security(require_agent_permission('reputation.signal'))"]


def test_every_natural_sender_may_signal_and_attestation_is_not_widened():
    for role in ("client", "trader"):
        assert "teg.transfer" in ROLE_PERMISSIONS[role], role
        assert "reputation.signal" not in ROLE_PERMISSIONS[role], role


def _client(dev):
    app = FastAPI()
    app.include_router(ti.router, prefix="/api/v1")
    app.dependency_overrides[security.get_current_developer] = lambda: dev
    return TestClient(app, raise_server_exceptions=False)


def _dev(**flags):
    base = dict(id=5, email="d@example.invalid", is_admin=False, admin_treasury=False, must_change_password=False)
    base.update(flags)
    return types.SimpleNamespace(**base)


BODY = {"policy_code": "a4-gate", "policy_name": "a4 gate", "policy_type": "governance"}


@pytest.mark.parametrize("method,path,body", [("post", "/api/v1/teg/policies", BODY),
                                              ("put", "/api/v1/teg/policies/some-id", {"policy_name": "x"}),
                                              ("delete", "/api/v1/teg/policies/some-id", None)])
def test_a_plain_developer_is_refused_before_the_teg_is_asked(monkeypatch, method, path, body):
    called = []
    monkeypatch.setattr(ti.httpx, "AsyncClient", lambda *a, **k: called.append(1) or (_ for _ in ()).throw(AssertionError("dialed")))
    kw = {"json": body} if body is not None else {}
    r = getattr(_client(_dev()), method)(path, **kw)
    assert r.status_code == 403, (r.status_code, r.text[:200])
    assert called == []


def test_control_a_treasury_admin_passes_the_gate(monkeypatch):
    class _NoNet:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            raise RuntimeError("no TEG in this test")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(ti.httpx, "AsyncClient", _NoNet)
    r = _client(_dev(admin_treasury=True)).post("/api/v1/teg/policies", json=BODY)
    assert r.status_code != 403, r.text[:200]
