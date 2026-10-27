"""D6-801 / SEC-18 (2026-10-17): a cross-TEG treasury fund asks the receiving peer's licence and quarantine first.

A routed fiat purchase settles through POST /api/v1/teg/treasury/cross-teg-fund (routers/fiat_onramp._handle_routed_settle
calls it in-process): this frame's treasury funds the operator's. The checkout asked the operator's licence and the
quarantine (wave 6), but the fund itself re-read only that the peer row is ACTIVE: a peer quarantined, or whose licence
was suspended, between the checkout and the payment's webhook was funded all the same, and so was any admin fund to
such a peer. Now the fund asks both, as the cross-registry transfer does, before anything moves:

  * quarantine: 403 naming the registry and its state while this registry holds the peer in quarantine, soft quarantine
    or blacklisted (503 when the compliance state cannot be read), whatever FEDERATION_ENFORCEMENT_ACTIVE says;
  * licence: for a peer whose operator DID this registry can name, a licence that is not active is refused where
    FEDERATION_ENFORCEMENT_ACTIVE is set, and recorded (CrossRegistryBlockedBySuspension) where it is not.

(The routed webhook already treats a first attempt's 4xx as final and refunds the purchase, and leaves a 5xx
PROCESSING for a retry: those are the answers it now gets.)

Through FastAPI on the real TEG router, the admin dependency supplied. Doubles: the database (the peer row, the
operator's application and licence, the compliance read), the local TEG (a recorder of the balance read and the send)
and the event emitter (a recorder). RED on 453cc8b8: every test but the control (the base funds the peer regardless).
"""
from __future__ import annotations

import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import event_emitter
from agentvault_registry.config import settings
from agentvault_registry.database import get_db
from agentvault_registry.routers import teg_integration as ti
from agentvault_registry.services import federation_license_gate as gate

OWN = "eu.example.invalid"
LISBON = types.SimpleNamespace(id=4, name="Lisbon", base_url="https://lisbon.op.example.invalid:8443", status="ACTIVE",
                               peer_type="cloud_operator", trust_domain=OWN)
APPLICATION = types.SimpleNamespace(name="Lisbon", docker_registry_username="operator-lisbon", cloud_hosted=True)
OPERATOR_DID = "did:theprotocol:cloud:lisbon"
BODY = {"target_registry": "Lisbon", "amount": "100", "reason": "fiat_routed_settle", "correlation_id": "purchase-1"}


def _licence(state):
    return types.SimpleNamespace(id=9, operator_did=OPERATOR_DID, operator_name="Lisbon", status=state)


class _Res:
    def __init__(self, rows=(), one=None):
        self._rows, self._one = list(rows), one

    def all(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return types.SimpleNamespace(all=lambda: list(self._rows), first=lambda: (self._rows or [None])[0])


class _Db:
    def __init__(self, quarantined=(), *, fail=False, licence=None):
        self.quarantined, self.fail, self.licence = list(quarantined), fail, licence or _licence("active")

    async def execute(self, stmt, *a, **k):
        sql = " ".join(str(stmt).split())
        if "federated_registry_compliance" in sql:
            if self.fail:
                raise RuntimeError("database unreachable")
            return _Res(rows=self.quarantined)
        if "FROM operator_applications" in sql:
            return _Res(one=APPLICATION)
        if "FROM federation_licenses" in sql:
            return _Res(one=self.licence)
        if "FROM peer_registries" in sql:
            return _Res(rows=[LISBON])
        return _Res()

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.fixture
def wires(monkeypatch):
    calls = {"teg": [], "emitter_calls": []}

    class _Teg:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None, timeout=None):
            calls["teg"].append(("balance", url))
            return types.SimpleNamespace(status_code=200, text="",
                                         json=lambda: {"balance": "1000000", "treasury_did": "did:theprotocol:t"})

        async def post(self, url, json=None, headers=None, timeout=None):
            calls["teg"].append((url.rsplit("/", 1)[-1], dict(json or {})))
            return types.SimpleNamespace(status_code=200, text="",
                                         json=lambda: {"status": "completed", "transaction_id": "tx-fund",
                                                       "new_treasury_balance": "999900", "peer_response": {}})

    class _Emitter:
        async def emit(self, *, event_type, **k):
            calls["emitter_calls"].append(event_type)

    monkeypatch.setattr(ti.httpx, "AsyncClient", _Teg)
    monkeypatch.setattr(ti, "fund_origin_allowed", lambda *a, **k: True)
    monkeypatch.setattr(event_emitter, "get_event_emitter", lambda: _Emitter())
    monkeypatch.setattr(gate, "get_event_emitter", lambda: _Emitter())
    monkeypatch.setattr(settings, "FEDERATION_ENFORCEMENT_ACTIVE", False)
    return calls


def _fund(db):
    app = FastAPI()
    app.include_router(ti.router, prefix="/api/v1")

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    # the route's own admin dependency (the router keeps its routes; an app includes them lazily)
    route = next(r for r in ti.router.routes if getattr(r, "path", "") == "/teg/treasury/cross-teg-fund")
    admin_dep = next(d.call for d in route.dependant.dependencies if d.name == "current_admin")
    app.dependency_overrides[admin_dep] = lambda: types.SimpleNamespace(id=1, email="admin@example.invalid",
                                                                        is_admin=True)
    return TestClient(app, raise_server_exceptions=False).post("/api/v1/teg/treasury/cross-teg-fund", json=BODY)


def _sent(wires):
    return [c for c in wires["teg"] if c[0] == "cross-teg-fund-send"]


@pytest.mark.parametrize("state", ["quarantined", "soft_quarantined", "blacklisted"])
def test_a_fund_to_a_quarantined_peer_is_refused_before_anything_moves(wires, state):
    r = _fund(_Db([("Lisbon", OWN, "cloud_operator", state)]))
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert f"registry Lisbon is {state} on this registry" in r.text and "(no funds moved)" in r.text
    assert wires["teg"] == [], "the treasury was read or sent before the refusal"


def test_an_unreadable_compliance_state_refuses_the_fund_retryably(wires):
    r = _fund(_Db(fail=True))
    assert r.status_code == 503 and "(no funds moved)" in r.text, (r.status_code, r.text[:300])
    assert wires["teg"] == []


def test_where_enforcement_is_on_a_suspended_licence_refuses_the_fund(wires, monkeypatch):
    monkeypatch.setattr(settings, "FEDERATION_ENFORCEMENT_ACTIVE", True)
    r = _fund(_Db(licence=_licence("suspended")))
    assert r.status_code == 403 and "suspended" in r.text, (r.status_code, r.text[:300])
    assert wires["teg"] == []
    assert wires["emitter_calls"] == ["CrossRegistryBlockedBySuspension"]


def test_where_enforcement_is_off_a_suspended_licence_is_recorded_and_the_fund_goes_on(wires):
    r = _fund(_Db(licence=_licence("suspended")))
    assert r.status_code == 200, (r.status_code, r.text[:300])
    assert len(_sent(wires)) == 1
    assert wires["emitter_calls"] == ["CrossRegistryBlockedBySuspension", "CrossTEGTreasuryFunded"]


def test_control_a_fund_to_a_peer_in_good_standing_moves(wires):
    r = _fund(_Db([("Orbit", "orbit.example.invalid", "frame", "quarantined")]))   # another registry's quarantine
    assert r.status_code == 200, (r.status_code, r.text[:300])
    ((_ep, body),) = _sent(wires)
    assert body["target_url"] == LISBON.base_url and body["correlation_id"] == "purchase-1"
    assert wires["emitter_calls"] == ["CrossTEGTreasuryFunded"]
