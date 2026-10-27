"""D6-801, wave 6 (2026-10-17; his word on the quarantine check for the remaining money routes: "yes please"): a
registry this one holds in quarantine, soft quarantine or blacklisted takes no part in a cross-registry slash or a
routed fiat purchase with it.

Wave 4 put the quarantine check beside the licence check on the cross-registry transfer, the FX booth, every FX route
leg and the FX route hop. The two federation slash routes and the routed fiat checkout kept only their licence check,
which is audit-only unless FEDERATION_ENFORCEMENT_ACTIVE: a quarantined peer could still have a local defendant's
units moved by its slash request, have this registry pay a complainant on its confirmation, and have a fiat purchase
routed to it. Now each refuses before anything is recorded or moves: 403 naming the registry and its state, 503 when the
compliance state cannot be read. The slash routes ask about the registry presenting the request as well as the ones
its body names by address, because the body's address is not bound to the caller; a blacklisted peer, whose row is
REJECTED, is found by its address too.

Through FastAPI on the real routers. Doubles: the database session (it answers each read by its statement; the
compliance read answers the quarantined rows, or fails), the federation identity (the registry presenting the request),
the callback address check, the routed checkout's switches and licence key, and a sentinel on the first step past each
refusal point: the slash request's settlement record, the confirmation's claim (its UPDATE), the checkout's pricing.
RED on 8b70d2f4: every case that expects a refusal (the base reaches the sentinel).
"""
from __future__ import annotations

import types
from decimal import Decimal

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agentvault_registry.database import get_db
from agentvault_registry.routers import federation_disputes as fd
from agentvault_registry.routers import federation_licenses as fl
from agentvault_registry.routers import fiat_onramp as fo

OWN = "eu.theprotocol.cloud"
OUR_URL = f"https://{OWN}"
ASIA_URL = "https://asia.theprotocol.cloud"
LISBON_URL = "https://lisbon.op.theprotocol.cloud"
HANSA_URL = "https://hansa.op.theprotocol.cloud"
ASIA_ID = "spiffe://asia.theprotocol.cloud/service/registry"
LISBON_ID = f"spiffe://{OWN}/operator/lisbon/registry"
# A licence-key caller's identity names no peer row (core/federation_auth._verify_license_key).
LICENCE_ID = "spiffe://theprotocol.cloud/service/registry-did:theprotocol:cloud:somebody"

# (name, trust domain, peer type, state, base URL) of a row this registry holds in quarantine
LISBON_Q = ("Lisbon", OWN, "cloud_operator", "quarantined", LISBON_URL)
ASIA_SOFT = ("ASIA", "asia.theprotocol.cloud", "frame", "soft_quarantined", ASIA_URL)
HANSA_BL = ("Hansa Freight", OWN, "cloud_operator", "blacklisted", HANSA_URL)   # its peer row is REJECTED


class _Res:
    def __init__(self, rows=(), one=None, rowcount=0):
        self._rows, self._one, self.rowcount = list(rows), one, rowcount

    def all(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return types.SimpleNamespace(all=lambda: [], first=lambda: None)

    def scalar(self):
        return 0


class _Db:
    """The compliance reads answer the quarantined rows (or fail); `one` maps a table to the row a lookup there finds;
    the active peers' addresses are ASIA's and Lisbon's; every write is recorded."""

    def __init__(self, quarantined=(), *, fail=False, one=None):
        self.quarantined, self.fail, self.one = list(quarantined), fail, dict(one or {})
        self.added, self.updates = [], []

    async def execute(self, stmt, *a, **k):
        sql = " ".join(str(stmt).split())
        if "federated_registry_compliance" in sql:
            if self.fail:
                raise RuntimeError("database unreachable")
            if "peer_registries.base_url" in sql:        # name, address, state
                return _Res(rows=[(q[0], q[4], q[3]) for q in self.quarantined])
            return _Res(rows=[q[:4] for q in self.quarantined])   # name, trust domain, peer type, state
        if sql.startswith("UPDATE"):
            self.updates.append(sql)
            return _Res(rowcount=0)
        if sql.startswith("SELECT peer_registries.base_url"):
            return _Res(rows=[(ASIA_URL,), (LISBON_URL,)])
        for table, row in self.one.items():
            if f"FROM {table} " in sql + " ":
                return _Res(one=row)
        return _Res()

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def flush(self):
        return None

    async def refresh(self, obj):
        return None


def _client(router, db, monkeypatch, presenter=None):
    import agentvault_registry.input_validators as iv
    monkeypatch.setattr(iv, "validate_webhook_url", lambda url, **kw: url)   # its own tests cover it
    app = FastAPI()
    app.include_router(router)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    if presenter is not None:
        app.dependency_overrides[fd.get_federation_identity] = lambda: presenter
    return TestClient(app, raise_server_exceptions=False)


def _refused(r, name, state):
    assert r.status_code == 403, r.text
    assert f"registry {name} is {state} on this registry" in r.text, r.text
    assert "(no funds moved)" in r.text, r.text


# ── POST /api/v1/federation/disputes/slash-request (this registry is the defendant's home) ─────────────────────────

# ASIA's peer row; its identity fields are what binds a request's addresses to the registry presenting it (2026-10-17)
ASIA_ROW = types.SimpleNamespace(name="ASIA", auto_slash_enabled=False, auto_slash_max_avt=Decimal("0"),
                                 base_url=ASIA_URL, trust_domain="asia.theprotocol.cloud", peer_type="frame",
                                 spiffe_id=None, status="ACTIVE")
DEFENDANT = types.SimpleNamespace(did="did:theprotocol:defendant-w6", liquid_balance=Decimal("50"))


def _slash_request(db, monkeypatch, presenter, origin_url):
    body = {"settlement_id": "set-w6", "dispute_id": 7, "ruling": "IN_FAVOR_OF_COMPLAINANT", "amount": 10,
            "complainant_did": "did:theprotocol:complainant-w6", "defendant_did": DEFENDANT.did,
            "origin_registry_url": origin_url,
            "callback_url": f"{ASIA_URL}/api/v1/federation/disputes/slash-confirmation"}
    return _client(fd.router, db, monkeypatch, presenter).post("/api/v1/federation/disputes/slash-request", json=body)


def _request_db(quarantined=(), *, origin=ASIA_ROW, fail=False):
    return _Db(quarantined, fail=fail, one={"agents": DEFENDANT, "peer_registries": origin})


def test_a_slash_request_presented_by_a_quarantined_registry_is_refused(monkeypatch):
    db = _request_db([LISBON_Q])
    r = _slash_request(db, monkeypatch, LISBON_ID, ASIA_URL)   # it names a registry in good standing as the origin
    _refused(r, "Lisbon", "quarantined")
    assert db.added == [], "the settlement was recorded"


def test_a_slash_request_naming_a_soft_quarantined_origin_is_refused(monkeypatch):
    db = _request_db([ASIA_SOFT])
    r = _slash_request(db, monkeypatch, LICENCE_ID, ASIA_URL)
    _refused(r, "ASIA", "soft_quarantined")
    assert db.added == []


def test_a_slash_request_naming_a_blacklisted_origin_whose_row_is_rejected_is_refused(monkeypatch):
    db = _request_db([HANSA_BL], origin=None)   # no ACTIVE row at its address: the licence check never sees it
    r = _slash_request(db, monkeypatch, LICENCE_ID, HANSA_URL)
    _refused(r, "Hansa Freight", "blacklisted")
    assert db.added == []


def test_a_slash_request_is_refused_retryably_when_the_compliance_state_cannot_be_read(monkeypatch):
    db = _request_db(fail=True)
    r = _slash_request(db, monkeypatch, ASIA_ID, ASIA_URL)
    assert r.status_code == 503, r.text
    assert "(no funds moved)" in r.text
    assert db.added == []


def test_control_a_slash_request_from_a_registry_in_good_standing_is_recorded(monkeypatch):
    db = _request_db([HANSA_BL, LISBON_Q])   # other registries' quarantines do not touch ASIA's request
    r = _slash_request(db, monkeypatch, ASIA_ID, ASIA_URL)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending_admin_approval"
    assert [s.id for s in db.added] == ["set-w6"]


# ── POST /api/v1/federation/disputes/slash-confirmation (this registry is the complainant's home) ──────────────────

def _settlement(defendant_url):
    return types.SimpleNamespace(id="set-w6", dispute_id=7, origin_registry_url=OUR_URL,
                                 defendant_registry_url=defendant_url, status="SLASH_REQUESTED",
                                 complainant_did="did:theprotocol:complainant-w6", requested_amount=10)


def _confirm(db, monkeypatch, presenter):
    return _client(fd.router, db, monkeypatch, presenter).post(
        "/api/v1/federation/disputes/slash-confirmation",
        json={"settlement_id": "set-w6", "status": "slashed", "amount": 10})


def _confirmation_db(defendant_url, quarantined=(), *, fail=False):
    return _Db(quarantined, fail=fail,
               one={"cross_registry_settlements": _settlement(defendant_url), "peer_registries": ASIA_ROW})


def test_a_confirmation_presented_by_a_quarantined_registry_pays_nothing(monkeypatch):
    db = _confirmation_db(ASIA_URL, [LISBON_Q])
    r = _confirm(db, monkeypatch, LISBON_ID)
    _refused(r, "Lisbon", "quarantined")
    assert db.updates == [], "the settlement was claimed for payment"


def test_a_confirmation_for_a_settlement_with_a_blacklisted_registry_pays_nothing(monkeypatch):
    db = _confirmation_db(HANSA_URL, [HANSA_BL])
    r = _confirm(db, monkeypatch, LICENCE_ID)
    _refused(r, "Hansa Freight", "blacklisted")
    assert db.updates == []


def test_a_confirmation_is_refused_retryably_when_the_compliance_state_cannot_be_read(monkeypatch):
    db = _confirmation_db(ASIA_URL, fail=True)
    r = _confirm(db, monkeypatch, ASIA_ID)
    assert r.status_code == 503, r.text
    assert db.updates == []


def test_control_a_confirmation_from_a_registry_in_good_standing_reaches_the_claim(monkeypatch):
    db = _confirmation_db(ASIA_URL, [HANSA_BL, LISBON_Q])
    r = _confirm(db, monkeypatch, ASIA_ID)
    assert r.status_code == 200, r.text
    assert len(db.updates) == 1, db.updates   # the claim ran (the double answers it as already claimed)


# ── POST /api/v1/fiat/proxy/checkout-session (the routed fiat checkout, on the mainframe) ──────────────────────────

LISBON_PEER = types.SimpleNamespace(name="Lisbon", peer_type="cloud_operator", status="ACTIVE")
LICENCE = types.SimpleNamespace(id="lic-lisbon", operator_did="did:theprotocol:cloud:lisbon", licensee_type="operator",
                                operator_name="Lisbon", status="active")


@pytest.fixture
def checkout(monkeypatch):
    """The checkout's switches on, the operator's key accepted, and a sentinel on the pricing read that comes right
    after the refusal point: it records that the checkout went on towards the purchase row and the payment session."""
    reached = []

    async def key(x_federation_license, db):
        return LICENCE

    async def pricing(db):
        reached.append("pricing")
        raise HTTPException(status_code=418, detail="sentinel: the checkout went on to price the purchase")

    monkeypatch.setattr(fo, "_require_runtime_ready", lambda: None)
    monkeypatch.setattr(fo, "_routed_proxy_enabled", lambda: True)
    monkeypatch.setattr(fo, "_routed_operator_allowed", lambda did: True)
    monkeypatch.setattr(fl, "verify_federation_license", key)
    monkeypatch.setattr(fo, "get_active_pricing", pricing)

    def post(db):
        body = {"eur_amount": "10.00", "operator_did": LICENCE.operator_did, "operator_registry_name": "Lisbon",
                "customer_email": "buyer@theprotocol.cloud", "tos_accepted": True,
                "tos_version": fo.CURRENT_TOS_VERSION}
        return _client(fo.router, db, monkeypatch).post("/api/v1/fiat/proxy/checkout-session", json=body,
                                                         headers={"X-Federation-License": "tp_fed_test_not_a_key"})
    return post, reached


def _checkout_db(quarantined=(), *, fail=False):
    return _Db(quarantined, fail=fail, one={"peer_registries": LISBON_PEER, "federation_licenses": LICENCE})


@pytest.mark.parametrize("state", ["quarantined", "soft_quarantined", "blacklisted"])
def test_a_routed_checkout_for_a_quarantined_registry_is_refused(checkout, state):
    post, reached = checkout
    db = _checkout_db([("Lisbon", OWN, "cloud_operator", state, LISBON_URL)])
    _refused(post(db), "Lisbon", state)
    assert reached == [] and db.added == []


def test_a_routed_checkout_is_refused_retryably_when_the_compliance_state_cannot_be_read(checkout):
    post, reached = checkout
    db = _checkout_db(fail=True)
    r = post(db)
    assert r.status_code == 503, r.text
    assert reached == [] and db.added == []


def test_control_a_routed_checkout_for_a_registry_in_good_standing_goes_on(checkout):
    post, reached = checkout
    r = post(_checkout_db([HANSA_BL, ASIA_SOFT]))
    assert r.status_code == 418, r.text
    assert reached == ["pricing"]
