"""§SECFIX-1 (2026-09-25): the IRONKEY policy reads fail CLOSED under enforce.

The architecture audit of 2026-09-25 found the agent-permission resolver and the spend check returning "allow" when
their own read raised, in every mode: a database error while resolving an agent's permissions, its spend policy, its
org's ceiling or a cross-registry delegation's caveats authorized the request. Under ``enforce`` each of those reads
now refuses with a 503 (nothing is done, the caller may retry); ``shadow`` still observes and allows, which is its
job and the kill switch for enforce. An issuer-set ``max_per_tx`` that cannot be read binds instead of passing, and a
capability budget is never debited with an amount it could not read.

RED on the pre-change tree: the six refusals (measured: 6 failed, 6 passed); the two shadow tests and the controls
at the end pass before and after.
"""
from __future__ import annotations

import asyncio
import importlib
import types

import pytest
from fastapi import HTTPException

security = importlib.import_module("agentvault_registry.security")
authz = importlib.import_module("agentvault_registry.agent_authz")
org_policy = importlib.import_module("agentvault_registry.services.org_policy")
admin_audit = importlib.import_module("agentvault_registry.services.admin_audit")

AGENT = "did:theprotocol:sandbox-a.theprotocol.cloud:agent-0000"
ISSUER = "did:theprotocol:sandbox-b.theprotocol.cloud:issuer-0000"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _boom(*a, **k):
    raise RuntimeError("database went away")


async def _quiet(*a, **k):
    return None


def _modes(monkeypatch, mode):
    monkeypatch.setenv("AGENT_RBAC_MODE", mode)
    monkeypatch.setenv("AGENT_DELEGATION_MODE", mode)
    monkeypatch.setattr(admin_audit, "log_ironkey_action", _quiet)


# ── the permission gate ───────────────────────────────────────────────────────────────────────────────────────────

def _gate(perms_or_raise):
    check = security.require_agent_permission("teg.transfer")
    agent = types.SimpleNamespace(did=AGENT)
    request = types.SimpleNamespace(headers={}, state=types.SimpleNamespace())
    return _run(check(request=request, current_agent=agent, agent_info={"did": AGENT}, db=object())), agent


def test_a_permission_read_that_raises_refuses_under_enforce(monkeypatch):
    _modes(monkeypatch, "enforce")
    monkeypatch.setattr(authz, "resolve_agent_permissions", _boom)
    with pytest.raises(HTTPException) as e:
        _gate(None)
    assert e.value.status_code == 503 and e.value.detail.startswith("authz_unavailable")


def test_a_permission_read_that_raises_is_observed_and_allowed_in_shadow(monkeypatch):
    _modes(monkeypatch, "shadow")
    monkeypatch.setattr(authz, "resolve_agent_permissions", _boom)
    out, agent = _gate(None)
    assert out is agent


# ── the spend check ───────────────────────────────────────────────────────────────────────────────────────────────

async def _policy_ok(*a, **k):
    return True, None


async def _no_org(db, did):
    return {}


def _spend(db=None, request=None):
    return _run(security.enforce_agent_spend(db or types.SimpleNamespace(execute=_boom), AGENT, "1",
                                             currency="SBXA", request=request))


def test_a_spend_policy_read_that_raises_refuses_under_enforce(monkeypatch):
    _modes(monkeypatch, "enforce")
    monkeypatch.setattr(authz, "check_spend_policy", _boom)
    with pytest.raises(HTTPException) as e:
        _spend()
    assert e.value.status_code == 503 and "spend policy" in e.value.detail


def test_a_spend_policy_read_that_raises_is_observed_and_allowed_in_shadow(monkeypatch):
    _modes(monkeypatch, "shadow")
    monkeypatch.setattr(authz, "check_spend_policy", _boom)
    assert _spend() is None


class _SavepointThenBoom:
    """A session whose org-settings read fails as a lost connection does, read by the REAL org_policy reader.

    §SECFIX D6-491 (2026-10-16): this test used to replace get_org_settings with a stand-in that raised, while the real
    reader caught every error and answered {} (no organization). The refusal it pinned could therefore never fire, and
    the test passed over the defect; it runs the real reader now."""

    def begin_nested(self):
        class _Sp:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False
        return _Sp()

    execute = staticmethod(_boom)


def test_an_org_ceiling_read_that_raises_refuses_under_enforce(monkeypatch):
    _modes(monkeypatch, "enforce")
    monkeypatch.setattr(authz, "check_spend_policy", _policy_ok)
    with pytest.raises(HTTPException) as e:
        _spend(db=_SavepointThenBoom())
    assert e.value.status_code == 503 and "org ceiling" in e.value.detail


def test_an_org_ceiling_read_that_raises_is_observed_and_allowed_in_shadow(monkeypatch):
    _modes(monkeypatch, "shadow")
    monkeypatch.setattr(authz, "check_spend_policy", _policy_ok)
    assert _spend(db=_SavepointThenBoom()) is None


def test_a_delegation_caveat_read_that_raises_refuses_under_enforce(monkeypatch):
    _modes(monkeypatch, "enforce")
    monkeypatch.setattr(authz, "check_spend_policy", _policy_ok)
    monkeypatch.setattr(org_policy, "get_org_settings", _no_org)
    token = security._ACT_PRINCIPAL.set(f"agent:{ISSUER}")
    try:
        with pytest.raises(HTTPException) as e:
            _spend(db=types.SimpleNamespace(execute=_boom))
    finally:
        security._ACT_PRINCIPAL.reset(token)
    assert e.value.status_code == 503 and "delegation caveat" in e.value.detail


async def _budget_ok(*a, **k):
    return types.SimpleNamespace(rowcount=1)


def _cap_request(caveats):
    return types.SimpleNamespace(state=types.SimpleNamespace(ironkey_capability={"id": 7, "caveats": caveats}))


def test_an_unreadable_issuer_max_per_tx_binds_instead_of_passing(monkeypatch):
    _modes(monkeypatch, "enforce")
    monkeypatch.setattr(authz, "check_spend_policy", _policy_ok)
    monkeypatch.setattr(org_policy, "get_org_settings", _no_org)
    with pytest.raises(HTTPException) as e:
        _spend(db=types.SimpleNamespace(execute=_budget_ok), request=_cap_request({"max_per_tx": "ten"}))
    assert e.value.status_code == 403 and "max_per_tx" in e.value.detail


def test_a_budget_is_never_debited_with_an_unreadable_amount(monkeypatch):
    _modes(monkeypatch, "enforce")
    monkeypatch.setattr(authz, "check_spend_policy", _policy_ok)
    monkeypatch.setattr(org_policy, "get_org_settings", _no_org)
    with pytest.raises(HTTPException) as e:
        _run(security.enforce_agent_spend(types.SimpleNamespace(execute=_budget_ok), AGENT, "not-a-number",
                                          currency="SBXA", request=_cap_request({})))
    assert e.value.status_code == 403 and "could not be read" in e.value.detail


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_a_held_permission_passes_under_enforce(monkeypatch):
    _modes(monkeypatch, "enforce")

    async def _perms(*a, **k):
        return {"teg.transfer"}
    monkeypatch.setattr(authz, "resolve_agent_permissions", _perms)
    out, agent = _gate(None)
    assert out is agent


def test_control_a_missing_permission_is_still_a_403(monkeypatch):
    _modes(monkeypatch, "enforce")

    async def _perms(*a, **k):
        return {"read.profile"}
    monkeypatch.setattr(authz, "resolve_agent_permissions", _perms)
    with pytest.raises(HTTPException) as e:
        _gate(None)
    assert e.value.status_code == 403


def test_control_a_clean_spend_passes_under_enforce(monkeypatch):
    _modes(monkeypatch, "enforce")
    monkeypatch.setattr(authz, "check_spend_policy", _policy_ok)
    monkeypatch.setattr(org_policy, "get_org_settings", _no_org)
    assert _spend(db=types.SimpleNamespace(execute=_budget_ok), request=_cap_request({"max_per_tx": "5"})) is None


def test_control_off_never_reads_anything(monkeypatch):
    _modes(monkeypatch, "off")
    monkeypatch.setattr(authz, "resolve_agent_permissions", _boom)
    monkeypatch.setattr(authz, "check_spend_policy", _boom)
    out, agent = _gate(None)
    assert out is agent and _spend() is None
