"""The federation slash routes bind the addresses they name to their caller (2026-10-17).

POST /api/v1/federation/disputes/slash-request (this registry is the defendant's home) took `origin_registry_url` and
`callback_url` from its body: any federated registry could name another peer as the origin (and so have the defendant
slashed under that peer's auto-slash allowance, recorded as that peer's settlement) and send the confirmation, with this
registry's identity, to any peer's address. POST /api/v1/federation/disputes/slash-confirmation (the complainant's home)
paid the complainant whatever amount the confirmation reported, for whichever federated registry presented it. Now a
peer names only itself:

  * a slash request's origin must be the peer row of the registry presenting it, and its callback must lie under that
    origin's address (a path under it, not a longer host name);
  * a confirmation must come from the registry the settlement's slash request was sent to, and reports at most the
    amount the settlement requested; the origin records the registry it asks before the request goes out, because the
    defendant's home calls the confirmation back while it is still answering;
  * this frame's own registry (its own trust domain, a frame-class identity) may still name another peer.

Through FastAPI on the real router (the federation identity, the TEG and the reward payment supplied; the database a
double answering each read by its statement); the origin's sender (crud_disputes) with a recording client.
RED on 453cc8b8: every test but the controls (the base takes the addresses from the body and the amount from the
caller, and records the registry asked only after it answered).
"""
from __future__ import annotations

import asyncio
import types
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.crud import crud_disputes
from agentvault_registry.database import get_db
from agentvault_registry.routers import federation_disputes as fd
from agentvault_registry.services import federation_license_gate as gate

OWN = "eu.example.invalid"
OUR_URL = "https://eu.example.invalid:8443"
ASIA_URL, ASIA_TD = "https://asia.example.invalid:8443", "asia.example.invalid"
LISBON_URL = "https://lisbon.op.example.invalid:8443"
ASIA_ID = f"spiffe://{ASIA_TD}/service/registry"
LISBON_ID = f"spiffe://{OWN}/operator/lisbon/registry"
OWN_ID = f"spiffe://{OWN}/service/registry"
LICENCE_ID = "spiffe://theprotocol.cloud/service/registry-did:theprotocol:cloud:somebody"


def _row(name, url, td, kind, *, auto=True):
    return types.SimpleNamespace(id=hash(name) % 1000, name=name, base_url=url, trust_domain=td, peer_type=kind,
                                 spiffe_id=None, status="ACTIVE", auto_slash_enabled=auto,
                                 auto_slash_max_avt=Decimal("1000"))


ASIA = _row("ASIA", ASIA_URL, ASIA_TD, "frame")
LISBON = _row("Lisbon", LISBON_URL, OWN, "cloud_operator")
PEERS = [ASIA, LISBON]
DEFENDANT = types.SimpleNamespace(did="did:theprotocol:defendant-1", liquid_balance=Decimal("50"))


class _Res:
    def __init__(self, rows=(), one=None, rowcount=0):
        self._rows, self._one, self.rowcount = list(rows), one, rowcount

    def all(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return types.SimpleNamespace(all=lambda: list(self._rows))


class _Db:
    """Answers each read by its statement: no registry in quarantine, the active peers, the peer at an address, the
    defendant, a settlement; every write recorded (a settlement claim answers one row)."""

    def __init__(self, settlement=None):
        self.settlement, self.added, self.updates = settlement, [], []

    async def execute(self, stmt, *a, **k):
        sql = " ".join(str(stmt.compile(compile_kwargs={"literal_binds": True})).split())
        if "federated_registry_compliance" in sql:
            return _Res(rows=[])
        if sql.startswith("UPDATE"):
            self.updates.append(sql)
            return _Res(rowcount=1)
        if sql.startswith("SELECT peer_registries.base_url"):
            return _Res(rows=[(p.base_url,) for p in PEERS])
        if "FROM peer_registries" in sql:
            hit = next((p for p in PEERS if f"'{p.base_url}'" in sql), None)
            return _Res(rows=PEERS if hit is None else [hit], one=hit)
        if "FROM agents" in sql:
            return _Res(one=DEFENDANT if DEFENDANT.did in sql else None)
        if "FROM cross_registry_settlements" in sql:
            return _Res(one=self.settlement)
        return _Res()

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def refresh(self, obj):
        pass


@pytest.fixture
def wires(monkeypatch):
    """The defendant's TEG and every outbound call recorded (each answers 200); the reward payment of a confirmation
    recorded; nothing else of the process reached."""
    calls = {"teg": [], "callback": [], "paid": [], "emitter_calls": []}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            (calls["teg"] if "/treasury/receive" in url else calls["callback"]).append((url, json))
            return types.SimpleNamespace(status_code=200, text="", json=lambda: {"new_source_balance": "40"})

    class _Emitter:
        async def emit_dispute_slash(self, **k):
            calls["emitter_calls"].append("DisputeSlash")
            return True

        async def emit_dispute_compensation_minted(self, **k):
            calls["emitter_calls"].append("DisputeCompensationMinted")

    async def _pay(db, **kw):
        calls["paid"].append(kw["amount"])
        return {"status": "completed", "raw": {"new_target_balance": "10"}, "first_transaction_id": "tx-comp"}

    async def _no_operator(db, peer):
        return None
    import agentvault_registry.input_validators as iv
    from agentvault_registry.services import reward_funding
    monkeypatch.setattr(iv, "validate_webhook_url", lambda url, **kw: url)
    monkeypatch.setattr(fd.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(fd, "get_event_emitter", lambda: _Emitter())
    monkeypatch.setattr(gate, "resolve_peer_operator_did", _no_operator)
    monkeypatch.setattr(reward_funding, "fund_reward_via_waterfall", _pay)
    monkeypatch.setattr(fd.svid_client, "get_client_cert_config", lambda *a, **k: None)
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", OWN)
    return calls


def _client(db, presenter):
    app = FastAPI()
    app.include_router(fd.router)

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[fd.get_federation_identity] = lambda: presenter
    return TestClient(app, raise_server_exceptions=False)


def _request(db, presenter, *, origin=ASIA_URL, callback=None):
    body = {"settlement_id": "set-1", "dispute_id": 7, "ruling": "IN_FAVOR_OF_COMPLAINANT", "amount": 10,
            "complainant_did": "did:theprotocol:complainant-1", "defendant_did": DEFENDANT.did,
            "origin_registry_url": origin,
            "callback_url": callback or f"{origin}/api/v1/federation/disputes/slash-confirmation"}
    return _client(db, presenter).post("/api/v1/federation/disputes/slash-request", json=body)


# ── slash-request: the origin and the callback are the caller's ────────────────────────────────────────────────────

def test_a_peer_naming_another_registry_as_the_origin_is_refused(wires):
    """Lisbon names ASIA, whose auto-slash allowance would move the defendant's units at once."""
    db = _Db()
    r = _request(db, LISBON_ID, origin=ASIA_URL)
    assert r.status_code == 403 and "origin_registry_url" in r.text, (r.status_code, r.text[:300])
    assert db.added == [] and wires["teg"] == [] and wires["callback"] == []


def test_a_callback_to_another_peer_is_refused(wires):
    db = _Db()
    r = _request(db, ASIA_ID, origin=ASIA_URL, callback=f"{LISBON_URL}/api/v1/federation/disputes/slash-confirmation")
    assert r.status_code == 403 and "callback_url" in r.text, (r.status_code, r.text[:300])
    assert db.added == [] and wires["teg"] == [] and wires["callback"] == []


def test_a_callback_under_a_longer_host_name_is_not_under_the_origin(wires):
    db = _Db()
    evil = "https://asia.example.invalid:8443.evil.example/api/v1/federation/disputes/slash-confirmation"
    r = _request(db, ASIA_ID, origin=ASIA_URL, callback=evil)
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert db.added == [] and wires["teg"] == []


def test_a_licence_identity_names_no_origin(wires):
    db = _Db()
    r = _request(db, LICENCE_ID, origin=ASIA_URL)
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert db.added == [] and wires["teg"] == []


def test_control_a_peer_naming_itself_is_slashed_and_called_back(wires):
    db = _Db()
    r = _request(db, ASIA_ID, origin=ASIA_URL)
    assert r.status_code == 200 and r.json()["status"] == "slashed", (r.status_code, r.text[:300])
    assert [s.id for s in db.added] == ["set-1"] and len(wires["teg"]) == 1
    [(url, body)] = wires["callback"]
    assert url.startswith(ASIA_URL) and body["status"] == "slashed"
    assert wires["emitter_calls"] == ["DisputeSlash"]


def test_control_this_frames_own_registry_may_name_another_peer(wires):
    db = _Db()
    r = _request(db, OWN_ID, origin=ASIA_URL)
    assert r.status_code == 200, (r.status_code, r.text[:300])
    assert [s.id for s in db.added] == ["set-1"]


# ── slash-confirmation: from the registry asked, for at most the amount requested ──────────────────────────────────

def _settlement(defendant_url=ASIA_URL):
    return types.SimpleNamespace(id="set-9", dispute_id=9, origin_registry_url=OUR_URL,
                                 defendant_registry_url=defendant_url, status="PENDING_SLASH",
                                 requested_amount=Decimal("10.000000"), complainant_did="did:theprotocol:complainant-9",
                                 defendant_did=DEFENDANT.did, error_message=None, saga_state=None)


def _confirm(db, presenter, amount=10):
    return _client(db, presenter).post("/api/v1/federation/disputes/slash-confirmation",
                                       json={"settlement_id": "set-9", "status": "slashed", "amount": amount,
                                             "slash_tx_id": "slash-tx"})


def test_a_confirmation_from_a_registry_the_request_was_not_sent_to_pays_nothing(wires):
    db = _Db(_settlement(ASIA_URL))
    r = _confirm(db, LISBON_ID)
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert db.updates == [] and wires["paid"] == []


def test_a_confirmation_reporting_more_than_was_requested_pays_nothing(wires):
    db = _Db(_settlement(ASIA_URL))
    r = _confirm(db, ASIA_ID, amount=1000)
    assert r.status_code == 422 and "requested" in r.text, (r.status_code, r.text[:300])
    assert db.updates == [] and wires["paid"] == []


def test_a_confirmation_of_a_settlement_no_registry_took_pays_nothing(wires):
    db = _Db(_settlement(""))
    r = _confirm(db, ASIA_ID)
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert db.updates == [] and wires["paid"] == []


def test_control_the_registry_asked_confirms_and_the_complainant_is_paid(wires):
    db = _Db(_settlement(ASIA_URL))
    r = _confirm(db, ASIA_ID, amount=10)
    assert r.status_code == 200 and r.json()["status"] == "settled", (r.status_code, r.text[:300])
    claims = [u for u in db.updates if u.startswith("UPDATE cross_registry_settlements")]
    assert wires["paid"] == ["10.0"] and len(claims) == 1, db.updates
    assert wires["emitter_calls"] == ["DisputeCompensationMinted"]


# ── the origin's sender: the registry asked is recorded before the request goes out ────────────────────────────────

def _send(monkeypatch, answers):
    """Run the origin's sender over the active peers ASIA then Lisbon; each POST answers from `answers` (by peer URL)
    and records what the settlement said its defendant's registry was while that request was open."""
    seen = []
    db = _Db()

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            peer = next(p for p in PEERS if url.startswith(p.base_url))
            [settlement] = [o for o in db.added if type(o).__name__ == "CrossRegistrySettlement"]
            seen.append((peer.name, settlement.defendant_registry_url))
            code = answers[peer.name]
            return types.SimpleNamespace(status_code=code, text="", json=lambda: {"status": "pending_admin_approval"})

    class _Emitter:
        async def emit_dispute_compensation_request(self, **k):
            return True
    from agentvault_registry.identity import svid_client
    monkeypatch.setattr(crud_disputes.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(crud_disputes, "get_event_emitter", lambda: _Emitter())
    monkeypatch.setattr(svid_client, "get_client_cert_config", lambda *a, **k: None)
    for p in PEERS:
        p.federation_access_token = None
    dispute = types.SimpleNamespace(id=9, complainant_did="did:theprotocol:complainant-9", defendant_did=DEFENDANT.did)
    out = asyncio.run(crud_disputes._process_cross_registry_compensation(db, dispute, "IN_FAVOR_OF_COMPLAINANT", 10, {}))
    [settlement] = [o for o in db.added if type(o).__name__ == "CrossRegistrySettlement"]
    return seen, settlement, out


def test_the_origin_records_the_registry_it_asks_before_the_request_goes_out(wires, monkeypatch):
    seen, settlement, _ = _send(monkeypatch, {"ASIA": 404, "Lisbon": 200})
    assert seen == [("ASIA", ASIA_URL), ("Lisbon", LISBON_URL)], seen
    assert settlement.defendant_registry_url == LISBON_URL


def test_control_when_no_registry_takes_the_request_none_is_recorded(wires, monkeypatch):
    seen, settlement, _ = _send(monkeypatch, {"ASIA": 404, "Lisbon": 404})
    assert settlement.defendant_registry_url == ""
