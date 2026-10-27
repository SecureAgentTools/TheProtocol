"""2026-10-17 (his word: "no operator accepted without record ... record must exist first"): /operators/sync never moves
an operator's record onto the wrong identity.

The store finds a federation_operators row by the payload's spiffe_id first and by its licence id second (§TRUSTROW),
and it overwrote the row's identity with whatever the payload named. The registry's trust sync named every operator of
a frame by the frame's BARE trust domain, so the row that first carried that id took every same-domain operator's
update every two minutes (its name flipping, its identity the bare domain), and the operator it belonged to lost its
record: lisbon's row on EU, shenzhen's on ASIA, sbxalphaop's and sbxbetaop's on the sandbox (measured read-only on the
live stores). A store that accepts no operator without its record refuses those operators. What these tests pin,
through FastAPI on the real events router (only the database and the store's writer are replaced, nothing connects):
- this frame's bare trust domain finds no row and is never written, on an update or an insert: a sync from a registry
  that still sends it updates the licence's own row (its name and trust value) and leaves every identity as it was,
  so it can neither corrupt a repaired row nor go on renaming a corrupt one;
- a row that is an operator's record keeps that operator's identity: another operator's identity or a service
  identity is refused (409) and nothing is written;
- only this frame's own registry moves an identity: an operator's certificate may not (403), on a repaired row or on
  a corrupt one (since SEC-20 a caller that is not origin changes nothing here at all; the 403 no longer names the
  field, tests/test_operator_sync_non_origin.py pins the wording);
- what keeps working: the fixed registry's sync (the operator's own svid-writer identity) repairs a corrupt row by its
  licence id and the operator is accepted again; a peer frame is still found by its domain identity; the provisioner's
  two licence syncs (registry, then svid-writer) still leave the svid-writer identity.
RED on 912d9bc: the bare domain is written and found, another operator's identity replaces a record, and an operator
may move any row's identity.
Run: python -m pytest tests/test_operator_sync_keeps_identities.py -q   (needs pytest, httpx and cryptography)
"""
import datetime
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@127.0.0.1:1/ci")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src import internal_key  # noqa: E402
from src.database.connection import get_db  # noqa: E402
from src.models.federation_operator import FederationOperator  # noqa: E402
from src.routers import events  # noqa: E402

MARKER = "opsync-test-proxy-marker-not-a-secret-00000000"   # test fixture, longer than the 32 characters a marker needs
EU = "eu.theprotocol.cloud"
ASIA = "asia.theprotocol.cloud"
BARE_EU = f"spiffe://{EU}"
ORIGIN = f"spiffe://{EU}/service/eu-registry"
AMS_WRITER = f"spiffe://{EU}/operator/amsterdam/svid-writer"
AMS_REGISTRY = f"spiffe://{EU}/operator/amsterdam/registry"
LIS_WRITER = f"spiffe://{EU}/operator/lisbon/svid-writer"
AMS_LIC = "fa43d7b6-a25b-48fc-a7a5-5afc52357a67"   # the licence ids measured on EU
LIS_LIC = "d2197a61-7d0f-423a-8aa5-b01649057dd6"
ASIA_FRAME_ROW = "a9d3f8d0-66e2-4030-8898-a4feac553a88"
ASIA_LIC = "73f0193f-64fb-454f-abac-004693f274e1"
NEW_LIC = "11111111-2222-3333-4444-555555555555"
SYNC = "/api/v1/events/operators/sync"
APPEND = "/api/v1/events/"


def _escaped_cert(spiffe_id: str) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "opsync-test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1)).not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(spiffe_id)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return quote(cert.public_bytes(serialization.Encoding.PEM).decode())


_CERTS = {}


def through_terminator(spiffe_id: str) -> dict:
    """What this frame's TLS terminator forwards for a client certificate it verified."""
    if spiffe_id not in _CERTS:
        _CERTS[spiffe_id] = _escaped_cert(spiffe_id)
    return {"X-SSL-Client-Verify": "SUCCESS", "X-SSL-Client-Cert": _CERTS[spiffe_id], "X-ES-Proxy-Auth": MARKER}


def row(id_, name, spiffe_id, discount=1.0, status="active", hash_="h"):
    return FederationOperator(id=id_, operator_name=name, license_key_hash=hash_ * 64 if len(hash_) == 1 else hash_,
                              spiffe_id=spiffe_id, status=status, max_events_per_minute=1000,
                              bayesian_discount=discount)


def eu_rows(lisbon_identity):
    """EU's federation_operators: its two operators (lisbon's identity as given), and ASIA's frame and licence rows."""
    return [
        row(AMS_LIC, "amsterdam", AMS_WRITER, 0.9375, hash_="a"),
        row(LIS_LIC, "lisbon", lisbon_identity, 0.9996, hash_="b"),
        row(ASIA_LIC, "ASIA", None, 0.974, hash_="c"),
        row(ASIA_FRAME_ROW, "ASIA", f"spiffe://{ASIA}", 0.9996, hash_="d"),
    ]


class _Result:
    def __init__(self, one=None, tuples=()):
        self._one, self._tuples = one, list(tuples)

    def scalar_one_or_none(self):
        return self._one

    def fetchall(self):
        return list(self._tuples)

    def scalars(self):
        return self

    def all(self):
        return []


class Store:
    """The store's federation_operators as objects: answers the operator-standing read (the auth's) and the two lookups
    the sync makes (by spiffe_id, by id), takes an insert, and records nothing else."""

    def __init__(self, rows=()):
        self.rows = list(rows)

    def by_id(self, id_):
        return next(r for r in self.rows if r.id == id_)

    async def execute(self, stmt, params=None):
        try:
            sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        except Exception:  # noqa: BLE001  a statement literal binds cannot render is read as written
            sql = str(stmt)
        sql = " ".join(sql.split())
        if sql.startswith("SELECT federation_operators.spiffe_id, federation_operators.operator_name, "
                          "federation_operators.status, federation_operators.max_events_per_minute"):
            return _Result(tuples=[(r.spiffe_id, r.operator_name, r.status, r.max_events_per_minute)
                                   for r in self.rows])
        m = re.search(r"WHERE federation_operators\.(spiffe_id|id) = '([^']*)'", sql)
        if not m:
            return _Result()
        col, val = m.groups()
        return _Result(one=next((r for r in self.rows if getattr(r, col) == val), None))

    def add(self, obj):
        self.rows.append(obj)

    async def commit(self):
        pass


class _Writer:
    stored = []

    def __init__(self, db):
        pass

    async def append_event(self, event, source_operator_id=None):
        _Writer.stored.append(event)
        return event


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(internal_key, "_CURRENT", "opsync-test-internal-key-not-a-secret")
    monkeypatch.setattr(internal_key, "_PREVIOUS", "")
    monkeypatch.setattr(events, "MTLS_REQUIRED", True)
    monkeypatch.setattr(events, "PROXY_TRUST_SECRET", MARKER)
    monkeypatch.setattr(events, "EVENTSTORE_HTTP_VIA_KAFKA", False)
    monkeypatch.setattr(events, "EventStore", _Writer)
    monkeypatch.setenv("TRUSTED_SPIFFE_DOMAINS", f"{EU},{ASIA}")
    monkeypatch.setenv("KNOWN_INTERNAL_SERVICES", "eu-registry")
    monkeypatch.setenv("ES_OWN_TRUST_DOMAIN", EU)
    events._OPERATOR_STANDING.clear()   # the verdict cache is per process
    monkeypatch.setattr(events, "_OPERATOR_WINDOW", events.MinuteWindow())
    _Writer.stored = []
    db = Store()
    app = FastAPI()
    app.include_router(events.router)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        yield client, db


def sync(client, payload, caller=ORIGIN):
    return client.post(SYNC, json=payload, headers=through_terminator(caller))


def old_registry_payload(lic, name, discount):
    """What the registry's trust sync sent for one of this frame's own operators before 2026-10-17."""
    return {"id": lic, "operator_name": name, "bayesian_discount": discount, "spiffe_id": BARE_EU}


def test_red_a_registry_that_still_sends_the_bare_domain_cannot_corrupt_a_repaired_row(store):
    client, db = store
    db.rows = eu_rows(LIS_WRITER)
    for payload in (old_registry_payload(AMS_LIC, "amsterdam", 0.95), old_registry_payload(LIS_LIC, "lisbon", 0.99)):
        r = sync(client, payload)
        assert r.status_code == 200, r.text
    ams, lis = db.by_id(AMS_LIC), db.by_id(LIS_LIC)
    assert (ams.spiffe_id, ams.operator_name, ams.bayesian_discount) == (AMS_WRITER, "amsterdam", 0.95)
    assert (lis.spiffe_id, lis.operator_name, lis.bayesian_discount) == (LIS_WRITER, "lisbon", 0.99)
    assert all(r.spiffe_id != BARE_EU for r in db.rows)


def test_red_the_bare_domain_finds_no_row_in_the_state_production_holds_today(store):
    """lisbon's row carries the bare domain: amsterdam's update must reach amsterdam's row, not rename lisbon's."""
    client, db = store
    db.rows = eu_rows(BARE_EU)
    r = sync(client, old_registry_payload(AMS_LIC, "amsterdam", 0.95))
    assert r.status_code == 200, r.text
    ams, lis = db.by_id(AMS_LIC), db.by_id(LIS_LIC)
    assert (ams.spiffe_id, ams.operator_name, ams.bayesian_discount) == (AMS_WRITER, "amsterdam", 0.95)
    assert (lis.spiffe_id, lis.operator_name, lis.bayesian_discount) == (BARE_EU, "lisbon", 0.9996)


def test_red_the_bare_domain_is_never_written_on_an_insert(store):
    client, db = store
    db.rows = eu_rows(LIS_WRITER)
    r = sync(client, {"id": NEW_LIC, "operator_name": "porto", "license_key_hash": "e" * 64, "status": "active",
                      "spiffe_id": BARE_EU})
    assert r.status_code == 200 and r.json()["status"] == "created", r.text
    assert db.by_id(NEW_LIC).spiffe_id is None


@pytest.mark.parametrize("identity", [AMS_REGISTRY, ORIGIN, f"spiffe://{ASIA}/operator/lisbon/svid-writer"])
def test_red_a_record_keeps_its_operators_identity(store, identity):
    client, db = store
    db.rows = eu_rows(LIS_WRITER)
    r = sync(client, {"id": LIS_LIC, "operator_name": "lisbon", "bayesian_discount": 0.5, "spiffe_id": identity})
    assert r.status_code == 409, r.text
    lis, ams = db.by_id(LIS_LIC), db.by_id(AMS_LIC)
    assert (lis.spiffe_id, lis.operator_name, lis.bayesian_discount) == (LIS_WRITER, "lisbon", 0.9996)
    assert ams.spiffe_id == AMS_WRITER


@pytest.mark.parametrize("lisbon_identity", [LIS_WRITER, BARE_EU, None])
def test_red_an_operator_may_not_move_a_rows_identity(store, lisbon_identity):
    """amsterdam's own certificate (an active operator of this frame) names lisbon's licence with its own identity."""
    client, db = store
    db.rows = eu_rows(lisbon_identity)
    r = sync(client, {"id": LIS_LIC, "operator_name": "lisbon", "spiffe_id": AMS_REGISTRY}, caller=AMS_WRITER)
    assert r.status_code == 403, r.text
    assert db.by_id(LIS_LIC).spiffe_id == lisbon_identity
    assert db.by_id(AMS_LIC).spiffe_id == AMS_WRITER


def test_the_fixed_registry_repairs_a_corrupt_row_and_the_operator_is_accepted_again(store):
    client, db = store
    db.rows = eu_rows(BARE_EU)
    r = client.post(APPEND, json={"event_type": "AgentUpdated", "aggregate_id": "did:theprotocol:opsync-agent",
                                  "data": {}, "source_service": "registry", "idempotency_key": "opsync-1"},
                    headers=through_terminator(LIS_WRITER))
    assert r.status_code == 403 and "no federation operator record" in r.text, r.text
    r = sync(client, {"id": LIS_LIC, "operator_name": "lisbon", "bayesian_discount": 0.99, "spiffe_id": LIS_WRITER})
    assert r.status_code == 200, r.text
    assert (db.by_id(LIS_LIC).spiffe_id, db.by_id(LIS_LIC).operator_name) == (LIS_WRITER, "lisbon")
    events._OPERATOR_STANDING.clear()   # the refusal above is cached for OPERATOR_STANDING_TTL, like any verdict
    r = client.post(APPEND, json={"event_type": "AgentUpdated", "aggregate_id": "did:theprotocol:opsync-agent",
                                  "data": {}, "source_service": "registry", "idempotency_key": "opsync-2"},
                    headers=through_terminator(LIS_WRITER))
    assert r.status_code == 201, r.text


def test_a_peer_frame_is_still_found_by_its_domain_identity(store):
    client, db = store
    db.rows = eu_rows(LIS_WRITER)
    r = sync(client, {"id": ASIA_LIC, "operator_name": "ASIA", "bayesian_discount": 0.98,
                      "spiffe_id": f"spiffe://{ASIA}"})
    assert r.status_code == 200, r.text
    assert db.by_id(ASIA_FRAME_ROW).bayesian_discount == 0.98
    assert db.by_id(ASIA_LIC).bayesian_discount == 0.974


def test_the_provisioners_two_licence_syncs_still_leave_the_svid_writer_identity(store):
    client, db = store
    db.rows = eu_rows(LIS_WRITER)
    for role in ("registry", "svid-writer"):
        r = sync(client, {"id": NEW_LIC, "operator_name": "porto", "license_key_hash": "f" * 64, "status": "active",
                          "max_events_per_minute": 1000, "spiffe_id": f"spiffe://{EU}/operator/porto/{role}"})
        assert r.status_code == 200, r.text
    assert db.by_id(NEW_LIC).spiffe_id == f"spiffe://{EU}/operator/porto/svid-writer"


def test_the_identity_rule_itself():
    from src.es_auth import is_bare_trust_domain, shared_domain_id, sync_identity_refusal

    assert is_bare_trust_domain(BARE_EU) and is_bare_trust_domain(BARE_EU + "/") and not is_bare_trust_domain(LIS_WRITER)
    assert shared_domain_id(BARE_EU, EU) and shared_domain_id("spiffe://EU.theprotocol.cloud", EU)
    assert not shared_domain_id(f"spiffe://{ASIA}", EU)     # a peer frame's own identity
    assert not shared_domain_id(BARE_EU, "")                 # no known own domain: nothing is called shared
    assert sync_identity_refusal(LIS_WRITER, BARE_EU, EU)
    assert sync_identity_refusal(LIS_WRITER, AMS_WRITER, EU)
    assert sync_identity_refusal(LIS_WRITER, f"spiffe://{ASIA}", EU)
    assert sync_identity_refusal(LIS_WRITER, f"spiffe://{EU}/operator/lisbon/registry", EU) is None   # same operator
    assert sync_identity_refusal(BARE_EU, LIS_WRITER, EU) is None      # a corrupt row takes the identity back
    assert sync_identity_refusal(None, LIS_WRITER, EU) is None         # a licence-only row takes one
    assert sync_identity_refusal(LIS_WRITER, LIS_WRITER.upper().replace("SPIFFE", "spiffe"), EU) is None
