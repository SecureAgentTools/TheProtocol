"""SEC-20 (2026-10-17, his decision on the trust value: "it has to be dervied in a meaningful way. setting it manually
doesnt make sense to me"): on /operators/sync only this frame's own services (origin) change a record, the trust value
(bayesian_discount) included. Its registry derives that value from what it measured of each peer itself; no other
caller sets it.

The federation vote multiplies an agent vote's power by the submitting registry's bayesian_discount
(services/federation_governance.py). The day before (59e7548), a caller that was not origin (an operator of this frame,
a peer frame's service, a registered federation operator, a licence) could still change ONE field here: any existing
record's bayesian_discount, from 0 to 1, its own record included, and so the weight of its own registry's votes. Earlier
still (cbb98f7 and before) it could also reinstate a suspended record, raise a record's events per minute and rename a
record. Measured on every running store before the change (30 minutes): every call to this route came from the frame's
own registry, as origin, and no record or running operator is named "origin".

What these tests pin, through FastAPI on the real events router (only the database and the store's writer replaced):
- a caller that is not origin is refused 403 whatever its payload, and nothing is written: a trust value for another
  record or for its own (an operator of this frame, a peer frame's service, a registered federation operator, a licence),
  a payload that only names a record, a status (a reinstatement included), an events per minute, a rename, a licence
  hash, an identity, a record that does not exist;
- origin keeps every field, and is the one that refreshes a record's trust value (by its licence id, or by the identity
  the vote reads);
- a trust value outside 0 to 1, or not a number, is refused 422 whoever sends it, and nothing is written;
- a caller named "origin" is refused at authentication, for every path that names a caller from data, and can neither
  change a record here nor append a mint-class event.
RED on 59e7548: every refusal of a trust value, and of a payload that only names a record, from a caller that is not
origin (59e7548 answered 200 and wrote the value); origin's trust value outside 0 to 1 (59e7548 wrote it).
Run: python -m pytest tests/test_operator_sync_non_origin.py -q   (needs pytest, httpx and cryptography)
"""
import datetime
import hashlib
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

MARKER = "nonorigin-test-proxy-marker-not-a-secret-0000"   # test fixture, longer than the 32 characters a marker needs
EU, ASIA = "eu.theprotocol.cloud", "asia.theprotocol.cloud"
ORIGIN = f"spiffe://{EU}/service/eu-registry"
ASIA_REGISTRY = f"spiffe://{ASIA}/service/asia-registry"           # a peer frame's service (peer_service)
AMS_WRITER = f"spiffe://{EU}/operator/amsterdam/svid-writer"
LIS_WRITER = f"spiffe://{EU}/operator/lisbon/svid-writer"
NAMED_ORIGIN = f"spiffe://{EU}/operator/origin/svid-writer"      # an operator whose name is the origin marker
FOREIGN_REPLICATOR = f"spiffe://{ASIA}/service/asia-replicator"   # registered by its SPIFFE id, not a known service
ASIA_INDEXER = f"spiffe://{ASIA}/service/asia-indexer"            # a registered federation operator with its own name
AMS_LIC, LIS_LIC = "fa43d7b6-a25b-48fc-a7a5-5afc52357a67", "d2197a61-7d0f-423a-8aa5-b01649057dd6"
ASIA_FRAME_ROW, ASIA_LIC = "a9d3f8d0-66e2-4030-8898-a4feac553a88", "73f0193f-64fb-454f-abac-004693f274e1"
ORIGIN_OP_LIC, REPLICATOR_ROW, LICENCE_ROW = "0rigin-op-licence-0001", "replicator-row-0001", "licence-row-0001"
INDEXER_ROW, PORTO_LIC = "indexer-row-0001", "porto-licence-0001"
LICENCE_KEY = "nonorigin-test-licence-key-not-a-secret"
PORTO_KEY = "nonorigin-test-porto-licence-key-not-a-secret"
SYNC, APPEND = "/api/v1/events/operators/sync", "/api/v1/events/"


def _escaped_cert(spiffe_id: str) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "nonorigin-test")])
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


def row(id_, name, spiffe_id, discount=1.0, status="active", limit=1000, hash_=None):
    return FederationOperator(id=id_, operator_name=name, license_key_hash=hash_ or hashlib.sha256(id_.encode()).hexdigest(),
                              spiffe_id=spiffe_id, status=status, max_events_per_minute=limit,
                              bayesian_discount=discount)


def eu_rows(lisbon_status="active"):
    return [
        row(AMS_LIC, "amsterdam", AMS_WRITER, 0.9375),
        row(LIS_LIC, "lisbon", LIS_WRITER, 0.9996, status=lisbon_status),
        row(ASIA_LIC, "ASIA", None, 0.974, limit=100000),
        row(ASIA_FRAME_ROW, "ASIA", f"spiffe://{ASIA}", 0.9996),
        row(ORIGIN_OP_LIC, "origin", NAMED_ORIGIN, 1.0),
        row(REPLICATOR_ROW, "origin", FOREIGN_REPLICATOR, 1.0),
        row(LICENCE_ROW, "origin", None, 1.0, hash_=hashlib.sha256(LICENCE_KEY.encode()).hexdigest()),
        row(INDEXER_ROW, "asia-indexer", ASIA_INDEXER, 0.5),
        row(PORTO_LIC, "porto", None, 0.5, hash_=hashlib.sha256(PORTO_KEY.encode()).hexdigest()),
    ]


def snapshot(db):
    return {r.id: (r.operator_name, r.spiffe_id, r.status, r.max_events_per_minute, r.bayesian_discount,
                   r.license_key_hash) for r in db.rows}


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
    """federation_operators as objects: answers the operator-standing read, the lookups by id, SPIFFE id and licence
    hash, takes an insert; every other statement finds nothing."""

    def __init__(self):
        self.rows = []

    def by_id(self, id_):
        return next((r for r in self.rows if r.id == id_), None)

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
        m = re.search(r"WHERE federation_operators\.(spiffe_id|id|license_key_hash) = '([^']*)'", sql)
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
    monkeypatch.setattr(internal_key, "_CURRENT", "nonorigin-test-internal-key-not-a-secret")
    monkeypatch.setattr(internal_key, "_PREVIOUS", "")
    monkeypatch.setattr(events, "MTLS_REQUIRED", True)
    monkeypatch.setattr(events, "PROXY_TRUST_SECRET", MARKER)
    monkeypatch.setattr(events, "EVENTSTORE_HTTP_VIA_KAFKA", False)
    monkeypatch.setattr(events, "EventStore", _Writer)
    monkeypatch.setenv("TRUSTED_SPIFFE_DOMAINS", f"{EU},{ASIA}")
    monkeypatch.setenv("KNOWN_INTERNAL_SERVICES", "eu-registry,asia-registry")
    monkeypatch.setenv("ES_OWN_TRUST_DOMAIN", EU)
    events._OPERATOR_STANDING.clear()   # the verdict cache is per process
    monkeypatch.setattr(events, "_OPERATOR_WINDOW", events.MinuteWindow())
    _Writer.stored = []
    db = Store()
    db.rows = eu_rows()
    app = FastAPI()
    app.include_router(events.router)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        yield client, db


def sync(client, payload, caller):
    return client.post(SYNC, json=payload, headers=through_terminator(caller))


def licence_sync(client, payload, key):
    return client.post(SYNC, json=payload, headers={"X-Federation-License": key})


def _refused(r) -> None:
    assert r.status_code == 403, r.text


def _refused_as_not_origin(r) -> None:
    """The refusal every caller that is not origin gets here (require_origin_auth), whatever it sent."""
    _refused(r)
    assert r.json()["detail"] == "Only this frame's own services may change cross-frame peers or federation operators", r.text


# --- the trust value: only origin sets it --------------------------------------------------------------------------

@pytest.mark.parametrize("caller, payload", [
    # an operator of this frame: another operator's record, and its own (its own vote weight)
    (AMS_WRITER, {"id": LIS_LIC, "operator_name": "lisbon", "bayesian_discount": 0.42}),
    (AMS_WRITER, {"id": AMS_LIC, "operator_name": "amsterdam", "bayesian_discount": 1.0}),
    (AMS_WRITER, {"id": LIS_LIC, "operator_name": "lisbon", "spiffe_id": LIS_WRITER, "bayesian_discount": 0.0}),
    # a peer frame's service: the row the vote reads for its own frame
    (ASIA_REGISTRY, {"id": ASIA_LIC, "operator_name": "ASIA", "spiffe_id": f"spiffe://{ASIA}", "bayesian_discount": 1.0}),
    # a registered federation operator (by its SPIFFE id): its own record and another
    (ASIA_INDEXER, {"id": INDEXER_ROW, "operator_name": "asia-indexer", "bayesian_discount": 1.0}),
    (ASIA_INDEXER, {"id": AMS_LIC, "operator_name": "amsterdam", "bayesian_discount": 0.1}),
])
def test_red_a_caller_that_is_not_origin_may_not_set_a_trust_value(store, caller, payload):
    client, db = store
    before = snapshot(db)
    r = sync(client, payload, caller)
    _refused_as_not_origin(r)
    assert snapshot(db) == before


def test_red_a_licence_may_not_set_a_trust_value(store, monkeypatch):
    client, db = store
    monkeypatch.setattr(events, "MTLS_REQUIRED", False)     # the licence path answers only on a store configured so
    before = snapshot(db)
    r = licence_sync(client, {"id": PORTO_LIC, "operator_name": "porto", "bayesian_discount": 1.0}, PORTO_KEY)
    _refused_as_not_origin(r)
    assert snapshot(db) == before


@pytest.mark.parametrize("caller", [AMS_WRITER, ASIA_REGISTRY, ASIA_INDEXER])
def test_red_a_caller_that_is_not_origin_is_refused_even_a_payload_that_only_names_a_record(store, caller):
    client, db = store
    before = snapshot(db)
    r = sync(client, {"id": LIS_LIC, "operator_name": "lisbon", "spiffe_id": LIS_WRITER}, caller)
    _refused_as_not_origin(r)
    assert snapshot(db) == before


# --- everything else a caller that is not origin asks: refused, nothing written -------------------------------------

def test_an_operator_may_not_reinstate_a_suspended_record(store):
    client, db = store
    db.rows = eu_rows(lisbon_status="suspended")
    before = snapshot(db)
    r = sync(client, {"id": LIS_LIC, "operator_name": "lisbon", "status": "active"}, AMS_WRITER)
    _refused(r)
    assert snapshot(db) == before


@pytest.mark.parametrize("payload", [
    {"id": LIS_LIC, "operator_name": "lisbon", "max_events_per_minute": 1_000_000},
    {"id": AMS_LIC, "operator_name": "amsterdam", "status": "ACTIVE", "bayesian_discount": 0.9},
    {"id": AMS_LIC, "operator_name": "amsterdam", "event_count": 0},
    {"id": LIS_LIC, "operator_name": "renamed"},
    {"id": LIS_LIC, "operator_name": "lisbon", "spiffe_id": AMS_WRITER},
    {"id": LIS_LIC, "operator_name": "lisbon", "spiffe_id": f"spiffe://{EU}/operator/porto/svid-writer"},
    {"id": LIS_LIC, "operator_name": "lisbon", "license_key_hash": "e" * 64},
    {"id": "no-such-licence", "operator_name": "porto", "license_key_hash": "e" * 64, "status": "active"},
])
def test_an_operator_may_change_nothing(store, payload):
    client, db = store
    before = snapshot(db)
    r = sync(client, payload, AMS_WRITER)
    _refused(r)
    assert snapshot(db) == before
    assert db.by_id("no-such-licence") is None


def test_a_peer_frames_service_may_change_nothing(store):
    client, db = store
    before = snapshot(db)
    r = sync(client, {"id": ASIA_LIC, "operator_name": "ASIA", "spiffe_id": f"spiffe://{ASIA}",
                      "max_events_per_minute": 100000}, ASIA_REGISTRY)
    _refused(r)
    assert snapshot(db) == before


# --- origin: every field, and the trust value it derives -----------------------------------------------------------

def test_origin_refreshes_a_records_trust_value_and_nothing_else(store):
    client, db = store
    before = snapshot(db)
    r = sync(client, {"id": LIS_LIC, "operator_name": "lisbon", "bayesian_discount": 0.42}, ORIGIN)
    assert r.status_code == 200, r.text
    after = snapshot(db)
    assert after[LIS_LIC][4] == 0.42
    assert after[LIS_LIC][:4] == before[LIS_LIC][:4] and after[LIS_LIC][5] == before[LIS_LIC][5]
    assert {k: v for k, v in after.items() if k != LIS_LIC} == {k: v for k, v in before.items() if k != LIS_LIC}


def test_origin_refreshes_the_row_the_vote_reads(store):
    client, db = store
    r = sync(client, {"id": ASIA_LIC, "operator_name": "ASIA", "spiffe_id": f"spiffe://{ASIA}",
                      "bayesian_discount": 0.98}, ORIGIN)
    assert r.status_code == 200, r.text
    assert db.by_id(ASIA_FRAME_ROW).bayesian_discount == 0.98
    assert db.by_id(ASIA_LIC).bayesian_discount == 0.974


def test_origin_by_the_internal_key_where_the_key_may_change_the_store(store, monkeypatch):
    client, db = store
    monkeypatch.setattr(events, "MTLS_REQUIRED", False)     # where the internal key still authenticates a change
    r = client.post(SYNC, json={"id": AMS_LIC, "operator_name": "amsterdam", "bayesian_discount": 0.5},
                    headers={"X-Internal-Key": "nonorigin-test-internal-key-not-a-secret"})
    assert r.status_code == 200, r.text
    assert db.by_id(AMS_LIC).bayesian_discount == 0.5


def test_origin_keeps_every_field(store):
    client, db = store
    r = sync(client, {"id": LIS_LIC, "operator_name": "Lisbon", "status": "suspended", "max_events_per_minute": 50,
                      "license_key_hash": "f" * 64, "bayesian_discount": 1.0}, ORIGIN)
    assert r.status_code == 200, r.text
    lis = db.by_id(LIS_LIC)
    assert (lis.operator_name, lis.status, lis.max_events_per_minute, lis.license_key_hash, lis.bayesian_discount) == \
        ("Lisbon", "suspended", 50, "f" * 64, 1.0)


@pytest.mark.parametrize("value", [1e9, 1.5, -0.5, "0.5", True])
def test_red_a_trust_value_outside_0_to_1_is_refused_even_from_origin(store, value):
    client, db = store
    before = snapshot(db)
    r = sync(client, {"id": AMS_LIC, "operator_name": "amsterdam", "bayesian_discount": value}, ORIGIN)
    assert r.status_code == 422, r.text
    assert snapshot(db) == before


def test_red_a_trust_value_outside_0_to_1_creates_no_record(store):
    client, db = store
    r = sync(client, {"id": "new-licence-0001", "operator_name": "porto2", "license_key_hash": "d" * 64,
                      "status": "active", "bayesian_discount": 7}, ORIGIN)
    assert r.status_code == 422, r.text
    assert db.by_id("new-licence-0001") is None


# --- a caller named "origin" is not this frame's own service -----------------------------------------------------

def test_an_operator_named_origin_is_not_origin(store):
    client, db = store
    before = snapshot(db)
    r = sync(client, {"id": LIS_LIC, "operator_name": "lisbon", "status": "suspended"}, NAMED_ORIGIN)
    assert r.status_code == 403, r.text
    assert snapshot(db) == before


def test_an_operator_named_origin_may_not_mint(store):
    client, db = store
    r = client.post(APPEND, json={"event_type": "TokensIssued", "aggregate_id": "did:theprotocol:nonorigin-agent",
                                  "data": {"amount": 1000, "kind": "mint"}, "source_service": "registry",
                                  "idempotency_key": "nonorigin-mint-1"},
                    headers=through_terminator(NAMED_ORIGIN))
    assert r.status_code == 403, r.text
    assert _Writer.stored == []


def test_a_registered_operator_named_origin_is_not_origin(store):
    client, db = store
    before = snapshot(db)
    r = sync(client, {"id": LIS_LIC, "operator_name": "taken"}, FOREIGN_REPLICATOR)
    assert r.status_code == 403, r.text
    assert snapshot(db) == before


def test_a_licence_named_origin_is_not_origin(store, monkeypatch):
    client, db = store
    monkeypatch.setattr(events, "MTLS_REQUIRED", False)     # the licence path answers only on a store configured so
    before = snapshot(db)
    r = licence_sync(client, {"id": LIS_LIC, "operator_name": "lisbon", "status": "suspended"}, LICENCE_KEY)
    assert r.status_code == 403, r.text
    assert snapshot(db) == before


def test_the_rules_themselves():
    from src.es_auth import reserved_operator_name, trust_value_ok

    for ok in (0, 0.0, 0.5, 1, 1.0):
        assert trust_value_ok(ok), ok
    for bad in (-0.0001, 1.0001, float("nan"), float("inf"), "0.5", True, False, None, [0.5]):
        assert not trust_value_ok(bad), bad
    for name in ("origin", "Origin", " ORIGIN "):
        assert reserved_operator_name(name), name
    for name in ("origins", "origin-labs", "amsterdam", "", None):
        assert not reserved_operator_name(name), name
