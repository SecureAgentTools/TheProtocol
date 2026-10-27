"""§SECBATCH wave 2 (2026-10-16): the per-agent projection reads ask the store's own authentication.

GET /api/v1/projections/balance/{did}, /transactions/{did} and /balance/{did}/at/{ts} answered any caller: one account's
balance, its full history with every counterparty, and its balance at any past moment, for any id a caller named
(an account id built from an e-mail address can be guessed from the address). D6-200 gated the bulk dumps beside
them; these three were left open. What these tests pin, through FastAPI on the real router (only the database and the
projection service are replaced, nothing connects anywhere):
- each of the three refuses an anonymous caller, and a caller whose certificate headers did not come from this frame's
  TLS terminator, and the projection is never computed for it;
- each answers the internal key (the registry's read, routers/teg_transactions.py), this frame's own certificate and an
  operator's certificate (an operator the store holds an active record for: since 2026-10-17 it accepts no operator
  without its record, so the stand-in database carries the operator's row).
Run: python -m pytest tests/test_projection_per_agent_reads_require_auth.py -q   (needs pytest, httpx and cryptography)
"""
import datetime
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@127.0.0.1:1/ci")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src import internal_key  # noqa: E402
from src.database.connection import get_db  # noqa: E402
from src.routers import events, projections  # noqa: E402

KEY = "sec2-test-internal-key-not-a-secret"              # test fixtures, not real secrets
MARKER = "sec2-test-proxy-marker-not-a-secret-0000000"   # longer than the 32 characters a marker needs
OWN = "eu.theprotocol.cloud"
ORIGIN = f"spiffe://{OWN}/service/eu-registry"
OPERATOR = f"spiffe://{OWN}/operator/amsterdam/registry"
DID = "did:theprotocol:alice_at_example.com"
READS = [
    f"/api/v1/projections/balance/{DID}",
    f"/api/v1/projections/transactions/{DID}",
    f"/api/v1/projections/balance/{DID}/at/2026-10-01T00:00:00Z",
]


def _escaped_cert(spiffe_id: str) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sec2-test")])
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
    return {"X-SSL-Client-Verify": "SUCCESS", "X-SSL-Client-Cert": _escaped_cert(spiffe_id), "X-ES-Proxy-Auth": MARKER}


class _Result:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        return None


class _Ledger:
    async def execute(self, stmt, params=None):
        if "FROM federation_operators" in " ".join(str(stmt).split()):
            return _Result([(OPERATOR, "Amsterdam", "active", 1000)])   # the operator's record
        return _Result()

    async def commit(self):
        pass


class _Projections:
    """Stands in for the projection service; records each account it was asked to compute."""

    def __init__(self):
        self.asked = []

    def _row(self, did):
        return SimpleNamespace(to_dict=lambda: {"agent_did": did, "liquid_balance": 100.0, "staked_balance": 0.0})

    async def calculate_balance(self, did):
        self.asked.append(did)
        return self._row(did)

    async def get_transaction_history(self, agent_did, limit=50, event_types=None):
        self.asked.append(agent_did)
        return [SimpleNamespace(to_dict=lambda: {"amount": "5", "details": {"from": agent_did}})]

    async def get_balance_at_timestamp(self, did, ts):
        self.asked.append(did)
        return self._row(did)


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(internal_key, "_CURRENT", KEY)
    monkeypatch.setattr(internal_key, "_PREVIOUS", "")
    monkeypatch.setattr(events, "MTLS_REQUIRED", True)
    monkeypatch.setattr(events, "PROXY_TRUST_SECRET", MARKER)
    monkeypatch.setenv("TRUSTED_SPIFFE_DOMAINS", OWN)
    monkeypatch.setenv("KNOWN_INTERNAL_SERVICES", "eu-registry")
    monkeypatch.setenv("ES_OWN_TRUST_DOMAIN", OWN)
    getattr(events, "_OPERATOR_STANDING", {}).clear()
    service = _Projections()
    app = FastAPI()
    app.include_router(projections.router)

    async def _db():
        yield _Ledger()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[projections.get_projection_service] = lambda: service
    with TestClient(app) as client:
        yield client, service


@pytest.mark.parametrize("path", READS)
def test_an_anonymous_caller_is_refused_and_nothing_is_computed(store, path):
    client, service = store
    r = client.get(path)
    assert r.status_code == 403, r.text
    assert "alice" not in r.text
    assert service.asked == []


@pytest.mark.parametrize("path", READS)
def test_certificate_headers_that_did_not_come_from_the_terminator_are_refused(store, path):
    client, service = store
    forged = through_terminator(ORIGIN)
    forged.pop("X-ES-Proxy-Auth")
    r = client.get(path, headers=forged)
    assert r.status_code == 403, r.text
    assert service.asked == []


@pytest.mark.parametrize("path", READS)
def test_the_key_and_the_frames_certificates_still_read(store, path):
    client, service = store
    for who, headers in (("internal key", {"X-Internal-Key": KEY}), ("origin", through_terminator(ORIGIN)),
                         ("operator", through_terminator(OPERATOR))):
        r = client.get(path, headers=headers)
        assert r.status_code == 200, (who, r.text)
        assert DID in r.text, who
    assert service.asked == [DID, DID, DID]
