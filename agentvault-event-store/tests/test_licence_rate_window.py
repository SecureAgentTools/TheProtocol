"""SEC-07 (2026-10-17): a licence and a registered federation operator get their events per minute in each calendar
minute: a steady stream under the limit is always admitted, and a stream above it is refused only past the limit.

They count on their federation_operators row (event_count, last_event_at), which every store worker shares. The counter
reset only after a minute WITHOUT a request: it compared now with the last admitted request, so a stream that kept
coming within a minute of its last admitted request (limit 3, one request every 25 seconds, 2.4 a minute) grew the count
1, 2, 3, 4 and was refused at the fourth request, and from then on whenever it reached the limit; and a caller refused in
one minute stayed refused in the next while it kept within 60 seconds of its last admitted request.

What these tests pin, through FastAPI on the real events router (the database, the store's writer and the clock are
replaced; nothing connects anywhere):
- a steady stream under the limit is admitted, request after request, over five minutes: from a licence
  (X-Federation-License, on a store configured to take it) and from a registered federation operator (its SPIFFE id
  through the frame's TLS terminator);
- above the limit in one calendar minute, the requests past it are refused 429, nothing is stored, and a refused request
  does not count;
- the next calendar minute admits again, even within 60 seconds of the last admitted request;
- the row says what was counted: event_count is the requests admitted in the minute of last_event_at, and last_event_at
  is the store's own clock;
- the rule itself, at the minute's edges.
RED on 59e7548: the two steady streams (refused at their fourth request), the next minute (refused within 60 s of the
last admitted request) and the limit in every minute (the second minute refused whole); the rule's own test (the helper
is new).
Run: python -m pytest tests/test_licence_rate_window.py -q   (needs pytest, httpx and cryptography)
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
from sqlalchemy.sql import ClauseElement  # noqa: E402

from src import internal_key  # noqa: E402
from src.database.connection import get_db  # noqa: E402
from src.models.federation_operator import FederationOperator  # noqa: E402
from src.routers import events  # noqa: E402

MARKER = "sec-07-test-proxy-marker-not-a-secret-00000"   # test fixture, longer than the 32 characters a marker needs
EU, ASIA = "eu.theprotocol.cloud", "asia.theprotocol.cloud"
INDEXER = f"spiffe://{ASIA}/service/asia-indexer"          # a registered federation operator, not a known service
LICENCE_KEY = "sec-07-test-licence-key-not-a-secret"
LIMIT = 3
APPEND = "/api/v1/events/"
UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)
_REAL_DATETIME = datetime.datetime


def _escaped_cert(spiffe_id: str) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sec-07-test")])
    now = _REAL_DATETIME.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1)).not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(spiffe_id)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return quote(cert.public_bytes(serialization.Encoding.PEM).decode())


_CERT = _escaped_cert(INDEXER)
INDEXER_HEADERS = {"X-SSL-Client-Verify": "SUCCESS", "X-SSL-Client-Cert": _CERT, "X-ES-Proxy-Auth": MARKER}
LICENCE_HEADERS = {"X-Federation-License": LICENCE_KEY}


class Clock:
    """The time datetime.now() answers inside the request (the counter reads it as datetime.now(timezone.utc)), moved
    by hand. The database's now() (a server default the old counter stamped) is this clock as well."""
    now = T0


class _ClockedDatetime(_REAL_DATETIME):
    @classmethod
    def now(cls, tz=None):
        return Clock.now.astimezone(tz) if tz is not None else Clock.now.replace(tzinfo=None)


class _Result:
    def __init__(self, one=None):
        self._one = one

    def scalar_one_or_none(self):
        return self._one

    def fetchall(self):
        return []

    def scalars(self):
        return self

    def all(self):
        return []


COUNTER = ("event_count", "last_event_at")


class Ledger:
    """federation_operators as objects, answering the lookups by SPIFFE id and licence hash. A request's session sees the
    row as last committed and loses what it did not commit (get_db closes without a commit); a database default
    (func.now()) is stamped with the clock at commit."""

    def __init__(self, rows):
        self.rows = rows
        self.commits = 0
        self._committed = {r.id: tuple(getattr(r, f) for f in COUNTER) for r in rows}

    def begin(self):
        for r in self.rows:
            for f, v in zip(COUNTER, self._committed[r.id]):
                setattr(r, f, v)

    async def execute(self, stmt, params=None):
        try:
            sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        except Exception:  # noqa: BLE001  a statement literal binds cannot render is read as written
            sql = str(stmt)
        m = re.search(r"WHERE federation_operators\.(spiffe_id|license_key_hash) = '([^']*)'", " ".join(sql.split()))
        if not m:
            return _Result()
        col, val = m.groups()
        return _Result(next((r for r in self.rows if getattr(r, col) == val), None))

    async def commit(self):
        self.commits += 1
        for r in self.rows:
            if isinstance(r.last_event_at, ClauseElement):
                r.last_event_at = Clock.now
            self._committed[r.id] = tuple(getattr(r, f) for f in COUNTER)

    def counter(self, row_id):
        return self._committed[row_id]


class _Writer:
    stored = []

    def __init__(self, db):
        pass

    async def append_event(self, event, source_operator_id=None):
        _Writer.stored.append(event)
        return event


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(internal_key, "_CURRENT", "sec-07-test-internal-key-not-a-secret")
    monkeypatch.setattr(internal_key, "_PREVIOUS", "")
    monkeypatch.setattr(events, "MTLS_REQUIRED", False)     # the licence path answers only on a store configured so
    monkeypatch.setattr(events, "PROXY_TRUST_SECRET", MARKER)
    monkeypatch.setattr(events, "EVENTSTORE_HTTP_VIA_KAFKA", False)
    monkeypatch.setattr(events, "EventStore", _Writer)
    monkeypatch.setenv("TRUSTED_SPIFFE_DOMAINS", f"{EU},{ASIA}")
    monkeypatch.setenv("KNOWN_INTERNAL_SERVICES", "eu-registry,asia-registry")
    monkeypatch.setenv("ES_OWN_TRUST_DOMAIN", EU)
    monkeypatch.setattr(datetime, "datetime", _ClockedDatetime)
    Clock.now = T0
    _Writer.stored = []
    ledger = Ledger([
        FederationOperator(id="licence-row-sec07", operator_name="porto", status="active", max_events_per_minute=LIMIT,
                           license_key_hash=hashlib.sha256(LICENCE_KEY.encode()).hexdigest(), spiffe_id=None,
                           event_count=0, last_event_at=None, bayesian_discount=0.5),
        FederationOperator(id="indexer-row-sec07", operator_name="asia-indexer", status="active",
                           max_events_per_minute=LIMIT, license_key_hash="c" * 64, spiffe_id=INDEXER,
                           event_count=0, last_event_at=None, bayesian_discount=0.5),
    ])
    app = FastAPI()
    app.include_router(events.router)

    async def _db():
        ledger.begin()
        try:
            yield ledger
        finally:
            ledger.begin()   # what the request did not commit is gone

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        yield client, ledger


_N = [0]


def append(client, headers):
    _N[0] += 1
    return client.post(APPEND, headers=headers, json={
        "event_type": "AgentUpdated", "aggregate_id": "did:theprotocol:sec-07-agent", "data": {"n": _N[0]},
        "source_service": "registry", "idempotency_key": f"sec-07-{_N[0]}"})


CALLERS = [pytest.param(LICENCE_HEADERS, "licence-row-sec07", id="licence"),
           pytest.param(INDEXER_HEADERS, "indexer-row-sec07", id="registered-operator")]


@pytest.mark.parametrize("headers, row_id", CALLERS)
def test_red_a_steady_stream_under_the_limit_is_never_refused(store, headers, row_id):
    """One request every 25 seconds for five minutes: 2.4 a minute against a limit of 3, never more than 3 in any
    calendar minute."""
    client, ledger = store
    statuses = []
    for i in range(12):
        Clock.now = T0 + datetime.timedelta(seconds=5 + 25 * i)
        statuses.append(append(client, headers).status_code)
    assert statuses == [201] * 12, statuses
    assert len(_Writer.stored) == 12


@pytest.mark.parametrize("headers, row_id", CALLERS)
def test_red_above_the_limit_only_the_excess_is_refused_and_the_next_minute_admits_again(store, headers, row_id):
    client, ledger = store
    statuses = []
    for s in range(5):                                   # five requests in the first seconds of 12:00
        Clock.now = T0 + datetime.timedelta(seconds=s)
        statuses.append(append(client, headers).status_code)
    assert statuses == [201, 201, 201, 429, 429], statuses
    assert len(_Writer.stored) == LIMIT, "a refused request was stored"
    assert ledger.counter(row_id) == (LIMIT, T0 + datetime.timedelta(seconds=2)), \
        "a refused request counted, or moved the window"
    Clock.now = T0 + datetime.timedelta(seconds=60.5)    # 12:00:60.5, 58.5 s after the last admitted request
    r = append(client, headers)
    assert r.status_code == 201, r.text
    assert ledger.counter(row_id) == (1, Clock.now), "the new minute does not start a new count"
    assert len(_Writer.stored) == LIMIT + 1


@pytest.mark.parametrize("headers, row_id", CALLERS)
def test_the_limit_holds_in_every_minute(store, headers, row_id):
    client, ledger = store
    for minute in range(3):
        statuses = []
        for s in (1, 20, 40, 59):
            Clock.now = T0 + datetime.timedelta(minutes=minute, seconds=s)
            statuses.append(append(client, headers).status_code)
        assert statuses == [201, 201, 201, 429], (minute, statuses)
    assert len(_Writer.stored) == 3 * LIMIT


def test_the_rule_itself():
    from src.es_auth import minute_window_count

    t = datetime.datetime(2026, 10, 17, 12, 0, 30, tzinfo=UTC)
    assert minute_window_count(None, 0, t) == 1
    assert minute_window_count(None, 7, t) == 1
    assert minute_window_count(t.replace(second=0), 2, t) == 3              # the same calendar minute counts on
    assert minute_window_count(t.replace(second=59, microsecond=999999), 2, t) == 3
    assert minute_window_count(t - datetime.timedelta(seconds=31), 2, t) == 1   # 11:59:59: the minute before
    assert minute_window_count(t + datetime.timedelta(minutes=1), 2, t) == 1    # a later minute (the clock moved back)
    assert minute_window_count(t.replace(second=5, tzinfo=None), 2, t) == 3     # a naive time is UTC
    plus2 = datetime.timezone(datetime.timedelta(hours=2))
    assert minute_window_count(t.astimezone(plus2).replace(second=10), 4, t) == 5   # the same instant's minute in +02:00
    assert minute_window_count(t.replace(second=10), None, t) == 1
