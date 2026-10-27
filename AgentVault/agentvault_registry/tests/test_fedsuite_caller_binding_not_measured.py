"""§NIGHTPROV (2026-09-27): the caller-binding flow's listing leg is NOT MEASURED when sandbox-B holds no live
cross-registry credential, as its docstring always said; it was counted as a failure. Measured on a fresh nightly pair
(nt260927x3): seven legs passed and the run went red on the one leg that had nothing to compare.

The flow is driven end to end with its host reach faked (the psql reads, the in-container callers, the log read), so
the verdict below is the one the suite computes. Each case keeps a control: a MEASURED leg that fails still fails.
"""
from __future__ import annotations

import types

from agentvault_registry.api_tests.federation_suite.tests import test_federation_caller_binding as cb

HOME, PEER = "https://sbx-alpha.example", "https://sbx-beta.example"
RUN_HEX = "0123456789abcdef0123456789abcdef"
ORDER = f"fs-bind-{RUN_HEX[:12]}"
REFUSALS = {"state": "not that participant's home registry", "join": "not that participant's home registry",
            "deliver": "not this thread's host", "relay-send": "not the sender's home registry",
            "guild-bid": "vouches only for its own agents"}


class _Rig:
    def mcp(self, _label):
        class _C:
            async def call(self, _tool, arguments=None, **_k):
                return {"response": {"host_base_url": HOME if _label == "sandbox-A-admin" else PEER}}
        return _C()


def _rows(stranger: bool, home_lists: int, broken_leg: str = ""):
    rows = {}
    for name, words in REFUSALS.items():
        refused = stranger and name != broken_leg
        rows[name] = {"name": name, "status": 403 if refused else 200, "detail": words if refused else "accepted"}
    rows["delegations-for-issuer"] = {"name": "delegations-for-issuer", "status": 200,
                                      "lists": {"credentials": 0 if stranger else home_lists}}
    rows["delegation-revoke"] = {"name": "delegation-revoke", "status": 200, "flags": {"revoked": False}}
    rows["guild-stake"] = {"name": "guild-stake", "status": 200, "flags": {"already": True}}
    return rows


def _wire(monkeypatch, live: bool, home_lists: int = 0, broken_leg: str = ""):
    third = cb.SANDBOX_REGISTRIES[cb._THIRD].container

    def fake_psql(_container, sql):
        if "FROM peer_registries" in sql:
            return [[PEER + ":8443"]]
        if "FROM agent_delegation_credentials" in sql:
            return [["did:theprotocol:issuer", "did:theprotocol:delegate", HOME]] if live else []
        if "FROM security_audit_logs" in sql:
            return [["1"]]
        raise AssertionError(sql)

    def fake_run_calls(container, _calls, _target):
        return _rows(stranger=(container == third), home_lists=home_lists, broken_leg=broken_leg)

    class _Container:
        def logs(self, **_k):
            return f"remote stake slash on {ORDER}/x refused".encode()

    monkeypatch.setattr(cb, "_psql", fake_psql)
    monkeypatch.setattr(cb, "_run_calls", fake_run_calls)
    monkeypatch.setattr(cb, "_get_container", lambda _name: _Container())
    monkeypatch.setattr(cb, "uuid", types.SimpleNamespace(uuid4=lambda: types.SimpleNamespace(hex=RUN_HEX)))


async def test_no_live_credential_is_not_measured_and_the_seven_measured_legs_decide(monkeypatch):
    _wire(monkeypatch, live=False)
    r = await cb.test_caller_binding(_Rig())
    assert r.passed is True, r.failure_detail
    assert r.last_state["not_measured"] == ["delegations-for-issuer"]
    assert "NOT MEASURED: delegations-for-issuer" in r.description
    assert r.last_state["evidence"]["delegations-for-issuer"]["fixture"] == "NOT MEASURED: none"


async def test_control_without_a_credential_a_measured_leg_that_fails_still_fails(monkeypatch):
    _wire(monkeypatch, live=False, broken_leg="relay-send")   # the stranger got past the binding: a real finding
    r = await cb.test_caller_binding(_Rig())
    assert r.passed is False and '"relay-send"' in r.failure_detail
    assert "delegations-for-issuer" not in r.failure_detail.split('"evidence"')[0]


async def test_with_a_live_credential_the_listing_leg_is_measured(monkeypatch):
    _wire(monkeypatch, live=True, home_lists=2)
    r = await cb.test_caller_binding(_Rig())
    assert r.passed is True and r.last_state["not_measured"] == []


async def test_control_with_a_live_credential_an_empty_home_listing_fails(monkeypatch):
    _wire(monkeypatch, live=True, home_lists=0)                # the home should see its credential: it did not
    r = await cb.test_caller_binding(_Rig())
    assert r.passed is False and '"delegations-for-issuer"' in r.failure_detail
