"""CB-097, CB-221 (2026-10-16): an operator of this frame's own trust domain is authenticated by its certificate, and its
federation_operators rows decide whether it may still act.

The store authenticated /operator/<name>/ of its own trust domain by identity alone: it never read the operator's row,
so after the frame suspended or revoked the operator (the registry suspends or revokes that row with the licence, at an
operator revoke and at a teardown) the operator kept appending until its last SVID expired, up to four hours later,
and the row's max_events_per_minute never applied. What these tests pin, through FastAPI on the real events router
(only the database and the store's writer are replaced, nothing connects anywhere):
- an operator whose rows are suspended or revoked is refused on an append and on a read, whichever of its workloads
  presents the certificate (its registry, its svid-writer), and nothing is stored;
- a row created from the licence alone (no SPIFFE id) still names the operator by its name;
- another operator's row, or a peer frame's row with the same name, does not touch this operator;
- a live operator keeps working: an active row (in any case: the provisioner writes 'ACTIVE'), an operator that also
  holds an older revoked row, an active row made from the licence alone;
- 2026-10-17 (his word: "no operator accepted without record ... record must exist first"): an operator that no row
  names is refused like a suspended one, on an append and on a read, with a reason that says there is no record, and
  named in the log; another operator's record, or a peer frame's record with the same name, is not its record; and a
  record created after a refusal takes effect within the same cache window (a refusal is not kept longer than an
  acceptance). The test that stood here before pinned the opposite (an operator with no row accepted by its
  certificate), the choice wave 2 made so operators provisioned before their licence sync kept working;
- the row's events per minute apply to changes and not to reads;
- the verdict is cached, and a suspension reaches the operator once the cache turns over;
- a store that cannot read the row answers 503 (retryable), never a silent accept;
- this frame's own services are not asked about any row.
Run: python -m pytest tests/test_operator_status_at_the_store.py -q   (needs pytest, httpx and cryptography)
"""
import datetime
import logging
import os
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
from src.routers import events  # noqa: E402

MARKER = "cb-097-test-proxy-marker-not-a-secret-000000"   # test fixture, longer than the 32 characters a marker needs
OWN = "eu.theprotocol.cloud"
ORIGIN = f"spiffe://{OWN}/service/eu-registry"
OP_REGISTRY = f"spiffe://{OWN}/operator/amsterdam/registry"
OP_WRITER = f"spiffe://{OWN}/operator/amsterdam/svid-writer"
APPEND = "/api/v1/events/"
READ = "/api/v1/events/aggregate/did:theprotocol:cb-097-agent"


def _escaped_cert(spiffe_id: str) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "cb-097-test")])
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


def _event(n: int = 0) -> dict:
    return {"event_type": "AgentUpdated", "aggregate_id": "did:theprotocol:cb-097-agent", "data": {"n": n},
            "source_service": "registry", "idempotency_key": f"cb-097-{n}"}


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def scalars(self):
        return self

    def all(self):
        return []

    def scalar_one_or_none(self):
        return None


class Ledger:
    """The store's database: federation_operators holds `rows` as (spiffe_id, operator_name, status,
    max_events_per_minute); every statement is recorded, and `fail` makes the row read raise."""

    def __init__(self):
        self.rows = []
        self.statements = []
        self.fail = False

    def operator_reads(self):
        return [s for s in self.statements if "federation_operators" in s]

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.statements.append(sql)
        if "federation_operators" in sql:
            if self.fail:
                raise RuntimeError("the database is gone")
            return _Result(self.rows)
        return _Result([])

    async def commit(self):
        pass


class _Writer:
    stored = []

    def __init__(self, db):
        pass

    async def append_event(self, event, source_operator_id=None):
        _Writer.stored.append(event)
        return event

    async def get_events_for_aggregate(self, aggregate_id, types=None, limit=None, sort_order="asc"):
        return []


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(internal_key, "_CURRENT", "cb-097-test-internal-key-not-a-secret")
    monkeypatch.setattr(internal_key, "_PREVIOUS", "")
    monkeypatch.setattr(events, "MTLS_REQUIRED", True)
    monkeypatch.setattr(events, "PROXY_TRUST_SECRET", MARKER)
    monkeypatch.setattr(events, "EVENTSTORE_HTTP_VIA_KAFKA", False)
    monkeypatch.setattr(events, "EventStore", _Writer)
    monkeypatch.setenv("TRUSTED_SPIFFE_DOMAINS", f"{OWN},asia.theprotocol.cloud")
    monkeypatch.setenv("KNOWN_INTERNAL_SERVICES", "eu-registry")
    monkeypatch.setenv("ES_OWN_TRUST_DOMAIN", OWN)
    getattr(events, "_OPERATOR_STANDING", {}).clear()   # the verdict cache is per process
    monkeypatch.setattr(events, "_OPERATOR_WINDOW", events.MinuteWindow() if hasattr(events, "MinuteWindow") else None,
                        raising=False)
    _Writer.stored = []
    ledger = Ledger()
    app = FastAPI()
    app.include_router(events.router)

    async def _db():
        yield ledger

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        yield client, ledger


@pytest.mark.parametrize("workload", [OP_REGISTRY, OP_WRITER])
@pytest.mark.parametrize("status", ["suspended", "revoked", "REVOKED"])
def test_a_suspended_or_revoked_operator_may_not_append(store, workload, status):
    client, ledger = store
    ledger.rows = [(OP_WRITER, "Amsterdam", status, 1000)]
    r = client.post(APPEND, json=_event(), headers=through_terminator(workload))
    assert r.status_code == 403, r.text
    assert "suspended or revoked" in r.text
    assert _Writer.stored == []


def test_a_suspended_operator_may_not_read_either(store):
    client, ledger = store
    ledger.rows = [(OP_REGISTRY, "Amsterdam", "suspended", 1000)]
    r = client.get(READ, headers=through_terminator(OP_REGISTRY))
    assert r.status_code == 403, r.text


def test_a_row_made_from_the_licence_alone_names_the_operator_by_name(store):
    client, ledger = store
    ledger.rows = [(None, "Amsterdam", "revoked", 1000)]
    r = client.post(APPEND, json=_event(), headers=through_terminator(OP_REGISTRY))
    assert r.status_code == 403, r.text
    assert _Writer.stored == []


def test_other_identities_rows_do_not_touch_this_operator(store):
    client, ledger = store
    ledger.rows = [
        (f"spiffe://{OWN}/operator/amsterdam2/registry", "amsterdam2", "revoked", 1000),   # another operator
        ("spiffe://asia.theprotocol.cloud", "amsterdam", "revoked", 1000),               # a peer frame, same name
        (OP_WRITER, "Amsterdam", "active", 1000),
    ]
    r = client.post(APPEND, json=_event(), headers=through_terminator(OP_REGISTRY))
    assert r.status_code == 201, r.text
    assert len(_Writer.stored) == 1


@pytest.mark.parametrize("status", ["active", "ACTIVE"])
def test_a_live_operator_keeps_appending_and_reading(store, status):
    client, ledger = store
    ledger.rows = [(OP_WRITER, "Amsterdam", status, 1000)]
    r = client.post(APPEND, json=_event(), headers=through_terminator(OP_WRITER))
    assert r.status_code == 201, r.text
    assert r.json()["aggregate_id"] == "did:theprotocol:cb-097-agent"
    r = client.get(READ, headers=through_terminator(OP_REGISTRY))
    assert r.status_code == 200, r.text


def test_a_reprovisioned_operator_with_an_old_revoked_row_keeps_working(store):
    client, ledger = store
    ledger.rows = [(OP_REGISTRY, "Amsterdam", "revoked", 1000), (OP_WRITER, "Amsterdam", "active", 1000)]
    r = client.post(APPEND, json=_event(), headers=through_terminator(OP_REGISTRY))
    assert r.status_code == 201, r.text


def test_an_active_record_made_from_the_licence_alone_admits_the_operator(store):
    client, ledger = store
    ledger.rows = [(None, "Amsterdam", "active", 1000)]
    r = client.post(APPEND, json=_event(), headers=through_terminator(OP_REGISTRY))
    assert r.status_code == 201, r.text


def _refused_for_no_record(r) -> None:
    assert r.status_code == 403, r.text
    assert "Operator is not active in this frame's federation" in r.text, r.text   # the shape a revoked one gets
    assert "no federation operator record" in r.text, r.text


@pytest.mark.parametrize("workload", [OP_REGISTRY, OP_WRITER])
@pytest.mark.parametrize("call", ["append", "read"])
def test_an_operator_with_no_record_is_refused_and_named_in_the_log(store, caplog, monkeypatch, workload, call):
    client, ledger = store
    ledger.rows = []
    monkeypatch.setattr(events, "_OPERATOR_WITHOUT_ROW", {"count": 0, "last_log": 0.0, "names": set()})
    with caplog.at_level(logging.WARNING, logger=events.logger.name):
        if call == "append":
            r = client.post(APPEND, json=_event(), headers=through_terminator(workload))
        else:
            r = client.get(READ, headers=through_terminator(workload))
    _refused_for_no_record(r)
    assert _Writer.stored == []
    assert ledger.operator_reads(), "the store did not ask for the operator's row"
    assert any("no federation_operators row" in m and "amsterdam" in m for m in caplog.messages), caplog.messages


def test_another_identitys_record_is_not_this_operators_record(store):
    client, ledger = store
    ledger.rows = [
        (f"spiffe://{OWN}/operator/amsterdam2/registry", "amsterdam2", "active", 1000),      # another operator
        ("spiffe://asia.theprotocol.cloud/operator/amsterdam/registry", "Amsterdam", "active", 1000),  # a peer's
        (ORIGIN, "Amsterdam", "active", 1000),   # a row naming another identity never matches by its name
    ]
    r = client.post(APPEND, json=_event(), headers=through_terminator(OP_REGISTRY))
    _refused_for_no_record(r)
    assert _Writer.stored == []


class _Clock:
    """The events module's own clock (its module-level `time`), moved by hand; everything else keeps the real one."""

    def __init__(self):
        import time as _time

        self._time = _time
        self.now = 10_000.0

    def monotonic(self):
        return self.now

    def __getattr__(self, name):
        return getattr(self._time, name)


def test_a_record_created_after_a_refusal_takes_effect_within_the_same_window(store, monkeypatch):
    """A refusal is not kept longer than an acceptance: both turn over after OPERATOR_STANDING_TTL."""
    client, ledger = store
    clock = _Clock()
    monkeypatch.setattr(events, "time", clock)
    ttl = events.OPERATOR_STANDING_TTL
    assert 0 < ttl <= 60, ttl
    ledger.rows = []
    _refused_for_no_record(client.post(APPEND, json=_event(1), headers=through_terminator(OP_WRITER)))
    ledger.rows = [(OP_WRITER, "Amsterdam", "ACTIVE", 1000)]   # the frame's licence sync writes the record
    clock.now += ttl + 0.5
    r = client.post(APPEND, json=_event(2), headers=through_terminator(OP_WRITER))
    assert r.status_code == 201, r.text
    ledger.rows = [(OP_WRITER, "Amsterdam", "suspended", 1000)]   # and an acceptance turns over in the same time
    clock.now += ttl + 0.5
    r = client.post(APPEND, json=_event(3), headers=through_terminator(OP_WRITER))
    assert r.status_code == 403, r.text
    assert len(_Writer.stored) == 1


def test_the_rows_events_per_minute_apply_to_changes_not_to_reads(store):
    client, ledger = store
    ledger.rows = [(OP_WRITER, "Amsterdam", "active", 2)]
    for n in range(2):
        r = client.post(APPEND, json=_event(n), headers=through_terminator(OP_WRITER))
        assert r.status_code == 201, (n, r.text)
    for _ in range(3):
        assert client.get(READ, headers=through_terminator(OP_REGISTRY)).status_code == 200
    r = client.post(APPEND, json=_event(9), headers=through_terminator(OP_REGISTRY))
    assert r.status_code == 429, r.text
    assert len(_Writer.stored) == 2


def test_the_window_turns_over_every_minute():
    from src.es_auth import MinuteWindow

    w = MinuteWindow()
    t = 600.0
    assert [w.hit("op", 2, now=t + i) for i in range(3)] == [False, False, True]
    assert w.hit("op", 2, now=t + 60) is False   # the next minute starts a fresh window
    # a steady stream under the limit never runs into it (the licence path's counter does)
    w2 = MinuteWindow()
    assert not any(w2.hit("op", 2, now=t + 30 * i) for i in range(200))


def test_the_verdict_is_cached_and_a_suspension_arrives_when_it_turns_over(store, monkeypatch):
    client, ledger = store
    ledger.rows = [(OP_WRITER, "Amsterdam", "active", 1000)]
    assert client.post(APPEND, json=_event(1), headers=through_terminator(OP_WRITER)).status_code == 201
    assert client.post(APPEND, json=_event(2), headers=through_terminator(OP_WRITER)).status_code == 201
    assert len(ledger.operator_reads()) == 1, "every event read the row: the verdict is not cached"
    ledger.rows = [(OP_WRITER, "Amsterdam", "suspended", 1000)]
    assert events.OPERATOR_STANDING_TTL <= 60, "a suspension must reach the operator within a minute"
    monkeypatch.setattr(events, "OPERATOR_STANDING_TTL", 0.0)
    r = client.post(APPEND, json=_event(3), headers=through_terminator(OP_WRITER))
    assert r.status_code == 403, r.text


def test_a_store_that_cannot_read_the_row_refuses_retryably(store):
    client, ledger = store
    ledger.fail = True
    r = client.post(APPEND, json=_event(), headers=through_terminator(OP_REGISTRY))
    assert r.status_code == 503, r.text
    assert _Writer.stored == []


def test_this_frames_own_services_are_not_asked_about_any_row(store):
    client, ledger = store
    ledger.rows = [(None, "eu-registry", "revoked", 1)]
    r = client.post(APPEND, json=_event(), headers=through_terminator(ORIGIN))
    assert r.status_code == 201, r.text
    assert ledger.operator_reads() == []


def test_the_standing_rule():
    from src.es_auth import operator_standing

    def s(rows):
        return operator_standing(rows, OWN, "amsterdam")

    assert s([]) == ("unregistered", None)
    assert s([(OP_WRITER, "x", "Suspended", 5)]) == ("inactive", None)
    assert s([(OP_WRITER, "x", "active", None)]) == ("active", 1000)
    assert s([(OP_WRITER, "x", "active", 50), (OP_REGISTRY, "x", "active", 20)]) == ("active", 20)
    assert s([(f"spiffe://{OWN}/operator/amsterdam", "x", "revoked", 5)]) == ("inactive", None)
    assert s([("", "op amsterdam", "revoked", 5)]) == ("unregistered", None)   # 'op-amsterdam' is another name
    assert s([("", "Amsterdam", "revoked", 5)]) == ("inactive", None)
