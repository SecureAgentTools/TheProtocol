"""§FEDLICENCE improvement 8 (2026-09-28): the licence routes' suspend, reinstate and delete reach the store and emit.

Measured in routers/federation_licenses.py: only revoke synced its status to the store's federation_operators row. Suspend
wrote only `status` (no suspended_at/by/reason, and no body at all, so the admin MCP tool's `reason` was dropped); a
reinstate never undid a revoke's "revoked" in the store; a delete left the store's row "active"; and neither suspend nor
reinstate emitted the FederationLicenseSuspended / FederationLicenseReinstated events the operator routes emit and the MCP
tester expects. The route functions are driven here with a fake session, a recording sync and a recording emitter.
"""
from __future__ import annotations

import types

import pytest
from pydantic import ValidationError

from agentvault_registry.routers import federation_licenses as fl
from tests._doubles import StrictEmitter  # noqa: E402


class _Result:
    def __init__(self, value):
        self._v = value

    def scalar_one_or_none(self):
        return self._v


class _Db:
    """execute() answers the queued values in order: the licence lookup, then the operator-application lookup."""

    def __init__(self, *values):
        self.values = list(values)
        self.commits = 0
        self.deleted = []

    async def execute(self, _stmt):
        return _Result(self.values.pop(0) if self.values else None)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        return None

    async def delete(self, obj):
        self.deleted.append(obj)


def _licence(status="active", name="b1opd"):
    return types.SimpleNamespace(id="lic-1", operator_name=name, operator_did=f"did:theprotocol:op:{name}",
                                 license_key_hash="h" * 64, status=status, revoked_at=None, revoked_reason=None,
                                 suspended_at=None, suspended_by=None, suspended_reason=None)


ADMIN = types.SimpleNamespace(id=7, email="admin@test.sandbox")


@pytest.fixture
def rec(monkeypatch):
    # the STRICT double (tests/_doubles.py): each emit is bound against EventEmitter's real signature, and the tests
    # assert RECEIPT (a permissive recorder is the §EMITKEY shape the doubles ratchet refuses)
    out = {"sync": [], "em": StrictEmitter()}

    async def fake_sync(**kw):
        out["sync"].append(kw)
        return True

    async def no_push(*a, **k):
        return None

    import agentvault_registry.event_emitter as ee
    import agentvault_registry.background_tasks.push_notify as pn
    monkeypatch.setattr(fl, "_sync_license_to_eventstore", fake_sync)
    monkeypatch.setattr(ee, "get_event_emitter", lambda: out["em"])
    monkeypatch.setattr(pn, "notify_audience", no_push)
    return out


async def test_suspend_writes_the_suspension_syncs_the_store_and_emits(rec):
    lic = _licence()
    db = _Db(lic, "b1opd")
    await fl.suspend_federation_license("lic-1", fl.FederationLicenseSuspendRequest(reason="probe"), ADMIN, db)
    assert lic.status == "suspended" and lic.suspended_by == 7 and lic.suspended_reason == "probe" and lic.suspended_at
    assert rec["sync"] == [{"license_id": "lic-1", "operator_name": "b1opd", "license_key_hash": "h" * 64,
                            "op_status": "suspended"}]
    ev = rec["em"].assert_received("FederationLicenseSuspended")
    assert ev["aggregate_id"] == "federation_license:lic-1" and len(rec["em"].received) == 1
    assert ev["data"]["reason"] == "probe" and ev["data"]["teg_id"] == "teg-b1opd" and ev["data"]["actor_developer_id"] == 7


async def test_control_a_suspend_with_no_body_still_works(rec):
    lic = _licence()
    await fl.suspend_federation_license("lic-1", None, ADMIN, _Db(lic, "b1opd"))
    assert lic.status == "suspended" and lic.suspended_reason is None
    assert rec["sync"][0]["op_status"] == "suspended"
    assert rec["em"].assert_received("FederationLicenseSuspended")["data"]["reason"] is None


async def test_control_a_frame_licence_carries_no_teg_id(rec):
    lic = _licence(name="sbx-beta")
    await fl.suspend_federation_license("lic-1", None, ADMIN, _Db(lic, None))   # no operator application of that name
    assert "teg_id" not in rec["em"].assert_received("FederationLicenseSuspended")["data"]


async def test_reinstate_clears_both_states_syncs_active_and_emits(rec):
    lic = _licence(status="suspended")
    lic.suspended_by, lic.suspended_reason, lic.revoked_reason = 7, "probe", "old"
    await fl.reinstate_federation_license("lic-1", ADMIN, _Db(lic, "b1opd"))
    assert lic.status == "active" and lic.suspended_by is None and lic.suspended_reason is None
    assert lic.revoked_reason is None
    assert rec["sync"][0]["op_status"] == "active"
    rec["em"].assert_received("FederationLicenseReinstated")


async def test_delete_closes_the_store_row_as_revoked(rec):
    lic = _licence()
    db = _Db(lic, "b1opd")
    await fl.delete_federation_license("lic-1", ADMIN, db)
    assert db.deleted == [lic]
    assert rec["sync"] == [{"license_id": "lic-1", "operator_name": "b1opd", "license_key_hash": "h" * 64,
                            "op_status": "revoked"}]
    # D6-800: a delete emits what a revoke emits, so the TEG drops the operator as a partner. This line asserted that
    # nothing was emitted, on the belief that revoke had an event of its own; revoke had none, so neither path did.
    data = rec["em"].assert_received("FederationLicenseSuspended")["data"]
    assert data["licence_status"] == "revoked" and data["teg_id"] == "teg-b1opd"


async def test_control_an_emit_failure_never_undoes_the_suspend(monkeypatch, rec):
    class _Broken:
        async def emit(self, **kw):
            raise RuntimeError("store down")

    import agentvault_registry.event_emitter as ee
    monkeypatch.setattr(ee, "get_event_emitter", lambda: _Broken())
    lic = _licence()
    await fl.suspend_federation_license("lic-1", None, ADMIN, _Db(lic, "b1opd"))
    assert lic.status == "suspended" and rec["sync"][0]["op_status"] == "suspended"


def test_the_suspend_body_takes_its_old_shape_and_refuses_an_unknown_key():
    assert fl.FederationLicenseSuspendRequest().reason is None
    assert fl.FederationLicenseSuspendRequest(reason="x").reason == "x"
    with pytest.raises(ValidationError):
        fl.FederationLicenseSuspendRequest(reasn="typo")
