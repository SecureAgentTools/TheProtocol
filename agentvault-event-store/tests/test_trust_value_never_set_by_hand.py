"""SEC-20, the store's remaining setters (2026-10-17, his word on the trust value: "it has to be dervied in a meaningful
way. setting it manually doesnt make sense to me"; and on an operator's record: "record must exist first").

The federation vote multiplies an agent vote's power by the submitting registry's trust value (bayesian_discount). This
frame's registry derives that value from what it measured of each peer and writes it (the upsert at a frame invitation
approve or resync, and its trust sync). What these tests pin, through FastAPI on the real routers (only the database
replaced, and the caller's authentication where a test names the caller):
- there is no manual trust route: POST /api/v1/admin/federation-operators/{id}/update-trust is not served, and the
  record keeps its value;
- the admin upsert never invents or overwrites a trust value: without one, a new record starts at 0.5 (the registry's
  value with no evidence) and an existing record keeps its own; with one, it writes it;
- the licence sync's new record without a value starts at 0.5, not 1.0;
- a federation vote weighs by the caller's own active record, whichever way the caller authenticated (an operator of
  this frame by its identity, a peer frame by its bare trust domain, a licence by its record id); the frame's own
  services vote at full weight; a caller with no active record here is refused 403 and nothing is written.
RED on 5c789ca: the manual route answers 200 and writes; an upsert without a value writes 1.0 over the record's value and
starts a new record at 1.0; the sync's new record starts at 1.0; a vote from a peer frame or from an operator of this
frame counts at full weight; a vote from a caller with no record is written, at full weight.
Run: python -m pytest tests/test_trust_value_never_set_by_hand.py -q   (needs pytest and httpx)
"""
import datetime
import hashlib
import os
import re
import sys
import types
import uuid
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@127.0.0.1:1/ci")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.database.connection import get_db  # noqa: E402
from src.models.federation_governance import FederationVote  # noqa: E402
from src.models.federation_operator import FederationOperator  # noqa: E402
from src.routers import admin_federation_operators, events  # noqa: E402
from src.routers import federation_governance as governance  # noqa: E402

EU, ASIA = "eu.theprotocol.cloud", "asia.theprotocol.cloud"
AMS_ROW, LIS_ROW, ASIA_ROW, PORTO_ROW = "ams-row-0001", "lis-row-0001", "asia-frame-row-0001", "porto-licence-0001"
AMS_WRITER = f"spiffe://{EU}/operator/amsterdam/svid-writer"
AMS_REGISTRY = f"spiffe://{EU}/operator/amsterdam/registry"
LIS_REGISTRY = f"spiffe://{EU}/operator/lisbon/registry"
FARO_REGISTRY = f"spiffe://{EU}/operator/faro/registry"          # an operator of this frame with no record here
ASIA_REGISTRY = f"spiffe://{ASIA}/service/asia-registry"
LANTERN_REGISTRY = "spiffe://lantern.theprotocol.cloud/service/lantern-registry"   # a peer frame with no record here
ADMIN, VOTE = "/api/v1/admin/federation-operators", "/api/v1/federation-governance/proposals/{}/vote"


def row(id_, name, spiffe_id, discount, status="active"):
    return FederationOperator(id=id_, operator_name=name, license_key_hash=hashlib.sha256(id_.encode()).hexdigest(),
                              spiffe_id=spiffe_id, status=status, max_events_per_minute=1000, event_count=0,
                              bayesian_discount=discount)


def eu_rows():
    return [
        row(AMS_ROW, "amsterdam", AMS_WRITER, 0.8125),
        row(LIS_ROW, "lisbon", LIS_REGISTRY, 0.9, status="suspended"),
        row(ASIA_ROW, "ASIA", f"spiffe://{ASIA}", 0.625),
        row(PORTO_ROW, "porto", None, 0.4375),
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
    """federation_operators as objects and one open proposal: answers the vote's read of the records, the proposal
    read, the lookups by id, SPIFFE id and licence hash; takes an insert; every other statement finds nothing."""

    def __init__(self, rows):
        self.rows, self.votes = rows, []
        self.proposal = types.SimpleNamespace(
            id=uuid.uuid4(), status="VOTING", ballot_mode=False,
            end_timestamp=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1))

    async def execute(self, stmt, params=None):
        try:
            sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        except Exception:  # noqa: BLE001  a statement literal binds cannot render is read as written
            sql = str(stmt)
        sql = " ".join(sql.split())
        if sql.startswith("SELECT federation_operators.id, federation_operators.spiffe_id, "
                          "federation_operators.operator_name, federation_operators.status, "
                          "federation_operators.bayesian_discount"):
            return _Result(tuples=[(r.id, r.spiffe_id, r.operator_name, r.status, r.bayesian_discount)
                                   for r in self.rows])
        if "FROM federation_proposals" in sql:
            return _Result(one=self.proposal)
        m = re.search(r"WHERE federation_operators\.(spiffe_id|id|license_key_hash) = '([^']*)'", sql)
        if not m:
            return _Result()
        col, val = m.groups()
        return _Result(one=next((r for r in self.rows if getattr(r, col) == val), None))

    def add(self, obj):
        (self.votes if isinstance(obj, FederationVote) else self.rows).append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass

    def by_id(self, id_):
        return next((r for r in self.rows if r.id == id_), None)


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("ES_OWN_TRUST_DOMAIN", EU)
    return Store(eu_rows())


def client(db, caller=None):
    app = FastAPI()
    for module in (admin_federation_operators, events, governance):
        app.include_router(module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[events.require_origin_auth] = lambda: {"auth_type": "mtls", "operator": "origin"}
    if caller is not None:
        app.dependency_overrides[events.verify_event_auth] = lambda: caller
    return TestClient(app)


# ─── no manual trust route ─────────────────────────────────────────

def test_the_manual_trust_route_is_not_served(db):
    r = client(db).post(f"{ADMIN}/{AMS_ROW}/update-trust", json={"bayesian_discount": 1.0})
    assert r.status_code in (404, 405), (r.status_code, r.text)
    assert db.by_id(AMS_ROW).bayesian_discount == 0.8125


# ─── the upsert never invents or overwrites a trust value ──────────

def test_an_upsert_without_a_value_keeps_the_records_own(db):
    r = client(db).post(ADMIN, json={"spiffe_id": f"spiffe://{ASIA}", "operator_name": "ASIA"})
    assert r.status_code == 200, r.text
    assert db.by_id(ASIA_ROW).bayesian_discount == 0.625 and r.json()["bayesian_discount"] == 0.625


def test_a_new_record_without_a_value_starts_where_the_registry_starts(db):
    r = client(db).post(ADMIN, json={"spiffe_id": "spiffe://orchard.theprotocol.cloud", "operator_name": "orchard"})
    assert r.status_code == 200, r.text
    assert r.json()["bayesian_discount"] == 0.5


def test_an_upsert_with_the_derived_value_writes_it(db):   # control: the registry's own write
    r = client(db).post(ADMIN, json={"spiffe_id": f"spiffe://{ASIA}", "operator_name": "ASIA",
                                     "bayesian_discount": 0.75})
    assert r.status_code == 200, r.text
    assert db.by_id(ASIA_ROW).bayesian_discount == 0.75


def test_the_licence_syncs_new_record_without_a_value_starts_at_one_half(db):
    r = client(db).post("/api/v1/events/operators/sync", json={
        "id": "faro-licence-0001", "operator_name": "faro", "license_key_hash": "ab" * 32, "status": "active"})
    assert r.status_code == 200, r.text
    assert db.by_id("faro-licence-0001").bayesian_discount == 0.5


# ─── a vote weighs by the caller's own record ──────────────────────

def _vote(db, caller, power=10000):
    return client(db, caller).post(VOTE.format(db.proposal.id), json={
        "voter_did": "did:theprotocol:voter-0001", "vote_in_favor": True, "voting_power": power})


@pytest.mark.parametrize("caller,weighted", [
    ({"auth_type": "mtls", "operator": "amsterdam", "spiffe_id": AMS_REGISTRY}, 8125),          # by its identity
    ({"auth_type": "mtls", "operator": f"peer:{ASIA}", "peer_frame": ASIA, "spiffe_id": ASIA_REGISTRY}, 6250),
    ({"auth_type": "federation", "operator": "porto", "operator_id": PORTO_ROW}, 4375),        # by its record id
])
def test_a_vote_weighs_by_the_callers_own_record(db, caller, weighted):
    r = _vote(db, caller)
    assert r.status_code == 201, r.text
    assert r.json()["voting_power"] == weighted and r.json()["raw_voting_power"] == 10000


def test_this_frames_own_services_vote_at_full_weight(db):   # control
    r = _vote(db, {"auth_type": "mtls", "operator": "origin", "spiffe_id": f"spiffe://{EU}/service/eu-registry"})
    assert r.status_code == 201, r.text
    assert r.json()["voting_power"] == 10000


@pytest.mark.parametrize("caller", [
    {"auth_type": "mtls", "operator": "faro", "spiffe_id": FARO_REGISTRY},                     # no record
    {"auth_type": "mtls", "operator": "lisbon", "spiffe_id": LIS_REGISTRY},                    # suspended record
    {"auth_type": "mtls", "operator": "peer:lantern.theprotocol.cloud", "peer_frame": "lantern.theprotocol.cloud",
     "spiffe_id": LANTERN_REGISTRY},                                                           # a peer with no record
])
def test_a_caller_without_an_active_record_casts_nothing(db, caller):
    r = _vote(db, caller)
    assert r.status_code == 403, (r.status_code, r.text)
    assert db.votes == []
