"""D6-111 (2026-10-16): a rail that accepts a federation licence checks who the licence was issued to.

Frames and cloud operators hold their keys in one table, told apart by `licensee_type`. `require_licensee_type` was
defined and used by no route, so every place that accepted a key took a frame's admission key on an operator's rail.
The operator rails (routed fiat's reconciler read and checkout, an operator's own logs and restart through its parent)
now refuse a key of the other class with 403 `licensee_type_mismatch`; an operator key, and a row written before the
type column existed, pass as before.

Through FastAPI on the real routers; only the database (the licence row, the purchase) is a double, and the
mainframe gate is lifted for the cloud-operator router (it reads this host's identity).
RED on 7140a4a6: test_routed_fiat_read_refuses_a_frame_key (200 on the base), test_operator_self_logs_refuses_a_frame_key
(404 on the base: the type was never read).
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.core.mainframe_gate import require_mainframe_only
from agentvault_registry.database import get_db
from agentvault_registry.routers import cloud_operators, fiat_onramp

PURCHASE_ID = "fp-0001"


def _licence(kind, did):
    return SimpleNamespace(id="lic-1", operator_name=f"{kind}-holder", operator_did=did, licensee_type=kind,
                           status="active", last_seen_at=None, event_count=0)


class _Purchase:
    """A routed purchase; every field the read returns is present (None unless set)."""

    def __init__(self, target_did):
        self.id = PURCHASE_ID
        self.routed = True
        self.target_operator_did = target_did
        self.status = "completed"
        self.amount_eur = "10.00"
        self.amount_avt = "20000"

    def __getattr__(self, name):
        return None


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _Db:
    def __init__(self, licence, purchase=None):
        self.licence, self.purchase = licence, purchase

    async def execute(self, *a, **k):
        return _Result(self.licence)

    async def get(self, model, key):
        return self.purchase if key == PURCHASE_ID else None

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def close(self):
        pass


def _fiat_client(db):
    app = FastAPI()
    app.include_router(fiat_onramp.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def genesis(monkeypatch):
    monkeypatch.setenv("FIAT_GENESIS_REGISTRY", "true")


def test_routed_fiat_read_refuses_a_frame_key(genesis):
    """A frame's admission key whose DID matches the purchase's target must not read an operator's purchase."""
    did = "spiffe://asia.example.invalid"
    r = _fiat_client(_Db(_licence("frame", did), _Purchase(did))).get(
        f"/api/v1/fiat/admin/fiat/routed/{PURCHASE_ID}", headers={"X-Federation-License": "tp_fed_frame"})
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert "licensee_type_mismatch" in r.text


def test_routed_fiat_read_still_serves_the_operator(genesis):
    """CONTROL: the operator whose purchase it is reads it, as before."""
    did = "did:theprotocol:cloud:amsterdam"
    r = _fiat_client(_Db(_licence("operator", did), _Purchase(did))).get(
        f"/api/v1/fiat/admin/fiat/routed/{PURCHASE_ID}", headers={"X-Federation-License": "tp_fed_op"})
    assert r.status_code == 200, (r.status_code, r.text[:300])
    assert r.json()["id"] == PURCHASE_ID


def test_a_row_without_a_type_reads_as_an_operator(genesis):
    """CONTROL: a licence row written before the type column existed is an operator licence (the backfill)."""
    did = "did:theprotocol:cloud:london"
    lic = _licence("operator", did)
    del lic.licensee_type
    r = _fiat_client(_Db(lic, _Purchase(did))).get(
        f"/api/v1/fiat/admin/fiat/routed/{PURCHASE_ID}", headers={"X-Federation-License": "tp_fed_old"})
    assert r.status_code == 200, (r.status_code, r.text[:300])


def _self_logs(monkeypatch, licence):
    async def _license_ok(key, request):
        return "spiffe://theprotocol.cloud/service/registry-x"

    async def _no_application(row, db):
        return None

    monkeypatch.setattr(cloud_operators, "_verify_license_key", _license_ok)
    monkeypatch.setattr(cloud_operators, "_resolve_application_from_license", _no_application)
    app = FastAPI()
    app.include_router(cloud_operators.router)
    app.dependency_overrides[get_db] = lambda: _Db(licence)
    app.dependency_overrides[require_mainframe_only] = lambda: None
    return TestClient(app, raise_server_exceptions=False).get(
        "/api/v1/admin/cloud-operators/self-logs", params={"service": "registry"},
        headers={"X-Federation-License": "tp_fed_x"})


def test_operator_self_logs_refuses_a_frame_key(monkeypatch):
    r = _self_logs(monkeypatch, _licence("frame", "spiffe://asia.example.invalid"))
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert "licensee_type_mismatch" in r.text


def test_operator_self_logs_passes_an_operator_key_to_the_next_check(monkeypatch):
    """CONTROL: an operator key passes the type check and meets the next one (no matching application here: 404)."""
    r = _self_logs(monkeypatch, _licence("operator", "did:theprotocol:cloud:amsterdam"))
    assert r.status_code == 404, (r.status_code, r.text[:300])
    assert "licensee_type_mismatch" not in r.text
