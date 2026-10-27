"""D6-800 (2026-10-17): a licence revoke reaches the store and the partner list the way a suspend does.

The licence routes' revoke synced "revoked" to the store's federation_operators row and emitted nothing, so nothing
removed the operator from the TEG's partner list: only a suspend emits FederationLicenseSuspended, the event the
partner-cleanup reactor (and, through the store's broadcast, every peer frame's) reacts to. A delete, which closes the
store row as revoked by the same path, emitted nothing either. Both now emit that event with licence_status "revoked";
a reinstate emits FederationLicenseReinstated, which adds the partner back.

Through FastAPI on the real router. The database session, the store sync (a network call) and the emitter are the
doubles; the admin dependency runs for real on an administrator. RED on b49fc6ad: the revoke and the delete (no event).
"""
from __future__ import annotations

import types
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from agentvault_registry.database import get_db
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
    return types.SimpleNamespace(
        id="lic-1", operator_name=name, operator_did=f"did:theprotocol:cloud:{name}", licensee_type="operator",
        license_key_prefix="tp_fed_abcd", license_key_hash="h" * 64, status=status,
        issued_at=datetime(2026, 10, 1, tzinfo=timezone.utc), revoked_at=None, revoked_reason=None,
        suspended_at=None, suspended_by=None, suspended_reason=None, max_agents=100, max_events_per_minute=1000,
        federation_tier="standard", last_seen_at=None, event_count=0, min_image_version=None)


ADMIN = types.SimpleNamespace(id=7, email="admin@example.test", name="Admin", is_admin=True,
                              must_change_password=False, admin_treasury=False, admin_support=False,
                              admin_enforcement=False, admin_federation=True, admin_platform=False)


@pytest.fixture
def rec(monkeypatch):
    out = {"sync": [], "em": StrictEmitter()}

    async def fake_sync(**kw):
        out["sync"].append(kw)
        return True

    import agentvault_registry.event_emitter as ee
    monkeypatch.setattr(fl, "_sync_license_to_eventstore", fake_sync)
    monkeypatch.setattr(ee, "get_event_emitter", lambda: out["em"])
    return out


def _client(db):
    app = FastAPI()
    app.include_router(fl.router)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[require_mainframe_only] = lambda: None
    app.dependency_overrides[security.get_current_developer] = lambda: ADMIN
    return TestClient(app)


def test_a_revoke_syncs_the_store_and_emits_the_event_a_suspend_emits(rec):
    lic = _licence()
    r = _client(_Db(lic, "b1opd")).post("/api/v1/admin/federation/licenses/lic-1/revoke", json={"reason": "probe"})
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json()["status"] == "revoked" and lic.revoked_reason == "probe" and lic.revoked_at
    assert rec["sync"] == [{"license_id": "lic-1", "operator_name": "b1opd", "license_key_hash": "h" * 64,
                            "op_status": "revoked"}]
    ev = rec["em"].assert_received("FederationLicenseSuspended")
    assert ev["aggregate_id"] == "federation_license:lic-1" and len(rec["em"].received) == 1
    data = ev["data"]
    # the reactor removes the TEG partner by teg_id; the payload says what happened to the licence
    assert data["teg_id"] == "teg-b1opd" and data["licence_status"] == "revoked" and data["reason"] == "probe"
    assert data["actor_developer_id"] == 7 and data["revoked_at"]


def test_control_a_frame_licence_revoke_carries_no_teg_id(rec):
    lic = _licence(name="sbx-beta")
    r = _client(_Db(lic, None)).post("/api/v1/admin/federation/licenses/lic-1/revoke", json={"reason": "probe"})
    assert r.status_code == 200, (r.status_code, r.text)
    assert "teg_id" not in rec["em"].assert_received("FederationLicenseSuspended")["data"]


def test_control_a_second_revoke_is_refused_and_emits_nothing(rec):
    r = _client(_Db(_licence(status="revoked"))).post("/api/v1/admin/federation/licenses/lic-1/revoke",
                                                     json={"reason": "probe"})
    assert r.status_code == 409, (r.status_code, r.text)
    assert rec["sync"] == []
    rec["em"].assert_nothing_received()


def test_a_reinstate_after_a_revoke_adds_the_partner_back(rec):
    lic = _licence(status="revoked")
    lic.revoked_reason = "probe"
    r = _client(_Db(lic, "b1opd")).post("/api/v1/admin/federation/licenses/lic-1/reinstate")
    assert r.status_code == 200, (r.status_code, r.text)
    assert lic.status == "active" and lic.revoked_reason is None
    assert rec["sync"][0]["op_status"] == "active"
    assert rec["em"].assert_received("FederationLicenseReinstated")["data"]["teg_id"] == "teg-b1opd"


def test_a_delete_closes_the_store_row_and_emits_what_a_revoke_emits(rec):
    lic = _licence()
    db = _Db(lic, "b1opd")
    r = _client(db).delete("/api/v1/admin/federation/licenses/lic-1")
    assert r.status_code == 204, (r.status_code, r.text)
    assert db.deleted == [lic]
    assert rec["sync"][0]["op_status"] == "revoked"
    data = rec["em"].assert_received("FederationLicenseSuspended")["data"]
    assert data["license_id"] == "lic-1" and data["teg_id"] == "teg-b1opd" and data["licence_status"] == "revoked"


def test_control_an_emit_failure_never_undoes_the_revoke(monkeypatch, rec):
    class _Broken:
        async def emit(self, **kw):
            raise RuntimeError("store down")

    import agentvault_registry.event_emitter as ee
    monkeypatch.setattr(ee, "get_event_emitter", lambda: _Broken())
    lic = _licence()
    r = _client(_Db(lic, "b1opd")).post("/api/v1/admin/federation/licenses/lic-1/revoke", json={"reason": "probe"})
    assert r.status_code == 200, (r.status_code, r.text)
    assert lic.status == "revoked" and rec["sync"][0]["op_status"] == "revoked"
