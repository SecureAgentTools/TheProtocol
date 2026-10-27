"""D6-200 (2026-10-16): the projection routes that dump or rewrite balances ask the store's own authentication.

POST /api/v1/projections/resync-agent set one account's projected balance and moved supply_summary with it (so the
supply audit stayed at 0) with no authentication at all, and /balances and /materialized-balances listed every account
to any caller. What these tests pin, through FastAPI on the real router (only the database and the projection service
are replaced, nothing connects anywhere):
- resync-agent refuses a caller without credentials, the internal key alone while EVENTSTORE_MTLS_REQUIRED is on (as
  every change to this store, §SECFIX-7), an operator's certificate, and certificate headers that did not come from
  this frame's TLS terminator; and nothing is written when it refuses,
- this frame's own service still resyncs (its certificate through the terminator; the key where the store lets the
  key change),
- the two balance dumps refuse an anonymous caller and answer the internal key, an origin certificate and an operator
  certificate (the registry's supply auditor reads its parent's dump with an operator certificate; the stand-in database
  carries the operator's active record, which the store asks for since 2026-10-17),
- the public supply audit stays open.
Run: python -m pytest tests/test_projection_routes_require_auth.py -q   (needs pytest, httpx and cryptography)
"""
import datetime
import os
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

# The database module builds its engine at import; nothing here connects to it.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@127.0.0.1:1/ci")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src import internal_key  # noqa: E402
from src.database.connection import get_db  # noqa: E402
from src.routers import events, projections  # noqa: E402

KEY = "d6-200-test-internal-key-not-a-secret"            # test fixtures, not real secrets
MARKER = "d6-200-test-proxy-marker-not-a-secret-00000"   # longer than the 32 characters a marker needs
OWN = "eu.theprotocol.cloud"
ORIGIN = f"spiffe://{OWN}/service/eu-registry"
OPERATOR = f"spiffe://{OWN}/operator/amsterdam/registry"
DID = "did:theprotocol:d6-200-account"
RESYNC = "/api/v1/projections/resync-agent"
BODY = {"agent_did": DID, "liquid_balance": "250", "staked_balance": "0"}
DUMPS = ["/api/v1/projections/balances", "/api/v1/projections/materialized-balances"]


def _escaped_cert(spiffe_id: str) -> str:
    """A certificate carrying spiffe_id as its URI SAN, URL-escaped as nginx forwards $ssl_client_escaped_cert."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "d6-200-test")])
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


def through_terminator(spiffe_id: str) -> dict:
    """What this frame's TLS terminator forwards for a client certificate it verified."""
    return {"X-SSL-Client-Verify": "SUCCESS", "X-SSL-Client-Cert": _escaped_cert(spiffe_id), "X-ES-Proxy-Auth": MARKER}


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class FakeLedger:
    """Stands in for the store's database: answers the projection routes' queries and records every statement."""

    def __init__(self):
        self.statements = []
        self.commits = 0

    @property
    def writes(self):
        return [s for s in self.statements if s.upper().startswith(("INSERT", "UPDATE", "DELETE"))]

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.statements.append(sql)
        if "FROM supply_summary" in sql:
            return _Result([SimpleNamespace(issued=Decimal("100"), destroyed=Decimal("0"), fees=Decimal("0"),
                                            transit_net=Decimal("0"), circ=Decimal("100"), agent_count=1,
                                            neg_accounts=0, neg_sum=Decimal("0"))])
        if sql.startswith("SELECT agent_did, liquid_balance, staked_balance FROM materialized_balances"):
            return _Result([(DID, Decimal("100"), Decimal("0"))])
        if sql.startswith("SELECT liquid_balance, staked_balance FROM materialized_balances WHERE"):
            return _Result([(Decimal("100"), Decimal("0"))])
        if "FROM federation_operators" in sql:
            return _Result([(OPERATOR, "Amsterdam", "active", 1000)])   # the operator's record
        return _Result([])

    async def commit(self):
        self.commits += 1


class _ProjectionService:
    async def get_all_balances(self):
        row = {"agent_did": DID, "liquid_balance": 100.0, "staked_balance": 0.0}
        return [SimpleNamespace(to_dict=lambda: dict(row), liquid_balance=100.0, staked_balance=0.0)]


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(internal_key, "_CURRENT", KEY)
    monkeypatch.setattr(internal_key, "_PREVIOUS", "")
    monkeypatch.setattr(events, "MTLS_REQUIRED", True)          # the code default
    monkeypatch.setattr(events, "INTERNAL_KEY_WRITES", "")
    monkeypatch.setattr(events, "PROXY_TRUST_SECRET", MARKER)
    monkeypatch.setenv("TRUSTED_SPIFFE_DOMAINS", OWN)
    monkeypatch.setenv("KNOWN_INTERNAL_SERVICES", "eu-registry")
    monkeypatch.setenv("ES_OWN_TRUST_DOMAIN", OWN)
    getattr(events, "_OPERATOR_STANDING", {}).clear()   # the verdict cache is per process
    ledger = FakeLedger()
    app = FastAPI()
    app.include_router(projections.router)

    async def _db():
        yield ledger

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[projections.get_projection_service] = lambda: _ProjectionService()
    with TestClient(app) as client:
        yield client, ledger


def test_resync_without_credentials_is_refused_and_moves_nothing(store):
    client, ledger = store
    r = client.post(RESYNC, json=BODY)
    assert r.status_code == 403, r.text
    assert ledger.statements == [] and ledger.commits == 0


def test_resync_with_only_the_internal_key_is_refused_while_mtls_is_required(store):
    client, ledger = store
    r = client.post(RESYNC, json=BODY, headers={"X-Internal-Key": KEY})
    assert r.status_code == 403, r.text
    assert "mtls_required" in r.text
    assert ledger.writes == [] and ledger.commits == 0


def test_resync_from_an_operator_or_from_unproxied_certificate_headers_is_refused(store):
    client, ledger = store
    r = client.post(RESYNC, json=BODY, headers=through_terminator(OPERATOR))
    assert r.status_code == 403, r.text
    forged = through_terminator(ORIGIN)
    forged.pop("X-ES-Proxy-Auth")  # the origin identity, written by a caller on the network, not by the terminator
    r = client.post(RESYNC, json=BODY, headers=forged)
    assert r.status_code == 403, r.text
    assert ledger.writes == [] and ledger.commits == 0


def test_resync_from_this_frames_own_service_still_works(store):
    client, ledger = store
    r = client.post(RESYNC, json=BODY, headers=through_terminator(ORIGIN))
    assert r.status_code == 200, r.text
    assert r.json()["resynced"] is True and Decimal(r.json()["delta"]) == Decimal("150")
    assert any(s.startswith("INSERT INTO materialized_balances") for s in ledger.writes)
    assert any("tokens_issued = tokens_issued +" in s for s in ledger.writes)
    assert ledger.commits == 1


def test_resync_with_the_key_where_the_store_lets_the_key_change(store, monkeypatch):
    monkeypatch.setattr(events, "MTLS_REQUIRED", False)
    client, ledger = store
    r = client.post(RESYNC, json=BODY, headers={"X-Internal-Key": KEY})
    assert r.status_code == 200, r.text
    assert ledger.commits == 1


@pytest.mark.parametrize("path", DUMPS)
def test_the_balance_dumps_refuse_an_anonymous_caller(store, path):
    client, ledger = store
    r = client.get(path)
    assert r.status_code == 403, r.text
    assert DID not in r.text
    assert ledger.statements == []


@pytest.mark.parametrize("path", DUMPS)
def test_the_balance_dumps_answer_the_key_and_the_frames_certificates(store, path):
    client, _ = store
    for who, headers in (("internal key", {"X-Internal-Key": KEY}), ("origin", through_terminator(ORIGIN)),
                         ("operator", through_terminator(OPERATOR))):
        r = client.get(path, headers=headers)
        assert r.status_code == 200, (who, r.text)
        assert DID in r.text, who


def test_the_public_supply_audit_stays_open(store):
    client, _ = store
    r = client.get("/api/v1/projections/supply-audit")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "OK"
