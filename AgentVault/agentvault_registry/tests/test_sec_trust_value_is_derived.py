"""SEC-20 (2026-10-17, his word: "no, not set. it has to be dervied in a meaningful way. setting it manually doesnt make
sense to me."): the trust value a frame registry holds for a peer (bayesian_discount), which the frame's event store
multiplies the peer's federation votes by, is DERIVED from the peer's record and the clock, never set.

The derivation (services/bayesian_trust.derived_trust): no record gives 0.5; otherwise the Beta(1,1) posterior mean
(1 + settlements) / (2 + settlements + lost disputes), drawn toward 0.5 by 5 % a day past 30 idle days, held to
[0.1, 1.0]. What these tests pin, each RED on 453cc8b8:
  1. an admin's resync of a peer frame registers the peer's DERIVED value with the store (the base reset it to 0.5);
  2. the trust sync (SF-5B) posts the derived value, never the row's column (the base posted the column, so whatever
     wrote the column decided the peer's vote weight);
  3. an administrator's decision on a peer's slash request, a rejection or an approval that slashed nothing, records
     nothing about the peer (the base counted either as a clean interaction, raising the peer's value);
  4. the daily recompute is a function of the record: run twice it gives the same value, and it replaces a value
     written into the column (the base re-applied its idle factor to the stored value on every pass, and left a
     recently active peer's column as it found it);
  5. the recorder writes the derivation, floor included (the base wrote the raw posterior mean, 1/22 for twenty lost
     disputes).
Control: a dispute the peer lost (its registry confirmed the slash) still records one negative observation.

Through FastAPI on the real routers for 1 and 3 (doubles: the database session, the store's HTTP call, the emitter and
the trust recorder); 2, 4 and 5 drive the background pass and the service themselves (they have no route). The expected
values are written out here, so the base fails on a value, never on an import.
"""
from __future__ import annotations

import asyncio
import types
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.background_tasks import federation_sync as fs
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from agentvault_registry.database import get_db
from agentvault_registry.routers import federation_disputes as fd
from agentvault_registry.routers import frame_invitations as fi
from agentvault_registry.services import frame_data_plane_sync as dps
from agentvault_registry.services.bayesian_trust import BayesianTrustService
from tests._doubles import StrictEmitter  # noqa: E402

NOW = datetime.now(timezone.utc)
EU = "eu.theprotocol.cloud"
ASIA = "asia.theprotocol.cloud"
ASIA_URL = "https://asia.theprotocol.cloud"

ADMIN = types.SimpleNamespace(id=7, email="admin@example.test", name="Admin", is_admin=True,
                              must_change_password=False, admin_treasury=False, admin_support=False,
                              admin_enforcement=True, admin_federation=True, admin_platform=False)


def beta(total, lost):
    """The Beta(1,1) posterior mean of a record."""
    return (1 + total - lost) / (2 + total)


def idle(p, days):
    """The posterior mean p after `days` without a recorded outcome: 5 % a day of its pull past 30 days."""
    return 0.5 + (p - 0.5) * 0.95 ** max(0.0, days - 30)


def peer_row(name, record=(0, 0), idle_days=1.0, column=1.0, **kw):
    total, lost = record
    return types.SimpleNamespace(
        name=name, total_interactions=total, disputes_lost_with=lost,
        last_interaction_at=(NOW - timedelta(days=idle_days)) if total else None,
        registered_at=NOW - timedelta(days=400), bayesian_discount=column, status="ACTIVE", **kw)


class _Res:
    def __init__(self, one=None, rows=()):
        self._one, self._rows = one, list(rows)

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return types.SimpleNamespace(first=lambda: self._one, all=lambda: list(self._rows))

    def all(self):
        return list(self._rows)

    def first(self):
        return self._one


class _Db:
    """Answers each read by the table it names: `rows` maps a table to the row a lookup there finds."""

    def __init__(self, rows):
        self.rows, self.commits = dict(rows), 0

    async def execute(self, stmt, *a, **k):
        sql = " ".join(str(stmt).split())
        for table, row in self.rows.items():
            if f"FROM {table}" in sql:
                return _Res(one=row)
        return _Res()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None

    async def refresh(self, _obj):
        return None

    async def flush(self):
        return None

    def add(self, _obj):
        return None


def _client(router, db):
    app = FastAPI()
    app.include_router(router)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[require_mainframe_only] = lambda: None
    app.dependency_overrides[security.get_current_developer] = lambda: ADMIN
    return TestClient(app, raise_server_exceptions=False)


# ── 1. POST /api/v1/admin/federation/frames/{peer_id}/resync-eventstore ─────────────────────────────────────────────

def test_red_a_resync_registers_the_peers_derived_value_with_the_store(monkeypatch):
    posted = []

    async def _post(path, body):
        posted.append((path, body))
        return True, "ok", None

    monkeypatch.setattr(dps, "_post", _post)
    peer = peer_row("ASIA", record=(20, 2), idle_days=1, column=1.0, id=5, peer_type="frame", trust_domain=ASIA)
    r = _client(fi.router, _Db({"peer_registries": peer})).post("/api/v1/admin/federation/frames/5/resync-eventstore")
    assert r.status_code == 200, r.text
    assert r.json()["sf5_registered"] is True, r.text
    ops = [body for path, body in posted if path == "/api/v1/admin/federation-operators"]
    assert len(ops) == 1, posted
    assert ops[0]["spiffe_id"] == f"spiffe://{ASIA}" and ops[0]["operator_name"] == "ASIA"
    # 19/22 from twenty settlements and two lost disputes: neither the prior the base sent nor the column's 1.0
    assert ops[0]["bayesian_discount"] == pytest.approx(beta(20, 2)), ops[0]


# ── 2. the trust sync, SF-5B (FederationSyncWorker._sync_trust_to_eventstore) ───────────────────────────────────────

LICENCES = [
    ("73f0193f-64fb-454f-abac-004693f274e1", "ASIA", "active"),
    ("fa43d7b6-a25b-48fc-a7a5-5afc52357a67", "amsterdam", "active"),
    ("d2197a61-7d0f-423a-8aa5-b01649057dd6", "lisbon", "active"),
]


class _LicenceDb:
    async def execute(self, _stmt):
        return _Res(rows=LICENCES)

    async def commit(self):
        return None


class _Client:
    posted = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        _Client.posted.append((url, json))
        return types.SimpleNamespace(status_code=200)


def test_red_the_trust_sync_posts_the_derived_value_never_the_column(monkeypatch):
    monkeypatch.setenv("EVENT_STORE_API_KEY", "trust-sync-test-key-not-a-secret")
    monkeypatch.setenv("EVENT_STORE_URL", "https://nginx-event-store:8443")
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", EU)
    monkeypatch.setattr(fs.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(fs, "get_httpx_verify", lambda: True)
    _Client.posted = []
    peers = [
        # a column someone wrote (1.0) over a record of ten clean settlements
        peer_row("amsterdam", record=(10, 0), idle_days=1, column=1.0, peer_type="cloud_operator",
                 trust_domain=EU, spiffe_id=f"spiffe://{EU}/operator/amsterdam/registry"),
        # no record at all, and a column that claims 0.97
        peer_row("lisbon", record=(0, 0), column=0.97, peer_type="cloud_operator",
                 trust_domain=EU, spiffe_id=f"spiffe://{EU}/operator/lisbon/registry"),
        # a peer frame last heard from 40 days ago, its column still the posterior mean of that day
        peer_row("ASIA", record=(30, 3), idle_days=40, column=beta(30, 3), peer_type="frame", trust_domain=ASIA,
                 spiffe_id=None),
    ]
    asyncio.run(fs.FederationSyncWorker._sync_trust_to_eventstore(None, _LicenceDb(), peers))
    sent = {body["operator_name"]: body["bayesian_discount"] for _url, body in _Client.posted}
    assert set(sent) == {"amsterdam", "lisbon", "ASIA"}, sent
    assert sent["amsterdam"] == pytest.approx(beta(10, 0)), sent      # 11/12, not 1.0
    assert sent["lisbon"] == pytest.approx(0.5), sent                 # unmeasured, not 0.97
    # (NOW is read at import; the value moves about 1e-5 a minute while a long suite runs)
    assert sent["ASIA"] == pytest.approx(idle(beta(30, 3), 40), abs=1e-3), sent
    assert all(0.1 <= v <= 1.0 for v in sent.values()), sent


# ── 3. a decision on a peer's slash request is not evidence about the peer ──────────────────────────────────────────

def _settlement():
    return types.SimpleNamespace(
        id="set-sec20", status="PENDING_ADMIN_APPROVAL", origin_registry_url=ASIA_URL,
        defendant_did="did:theprotocol:defendant-sec20", requested_amount=Decimal("10"), dispute_id=20,
        callback_url=None, error_message=None, slashed_amount=None, slashed_at=None, slash_tx_id=None)


@pytest.fixture
def trust_recorder(monkeypatch):
    recorded = []

    async def _record(self, db, peer_id, success=True):
        recorded.append((peer_id, success))

    monkeypatch.setattr(BayesianTrustService, "record_interaction", _record)
    return recorded


def _dispute_db():
    return _Db({
        "cross_registry_settlements": _settlement(),
        "peer_registries": types.SimpleNamespace(id=3, name="ASIA", base_url=ASIA_URL, status="ACTIVE"),
        "agents": types.SimpleNamespace(did="did:theprotocol:defendant-sec20", liquid_balance=Decimal("0")),
    })


def test_red_rejecting_a_peers_slash_request_records_nothing_about_the_peer(trust_recorder, monkeypatch):
    em = StrictEmitter()
    monkeypatch.setattr(fd, "get_event_emitter", lambda: em)
    r = _client(fd.router, _dispute_db()).post("/api/v1/federation/disputes/settlements/set-sec20/reject",
                                               json={"reason": "not ours to pay"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "REJECTED", r.text
    assert trust_recorder == [], f"a rejection moved the peer's trust record: {trust_recorder}"
    em.assert_nothing_received()


def test_red_an_approval_that_slashed_nothing_records_nothing_about_the_peer(trust_recorder, monkeypatch):
    em = StrictEmitter()
    monkeypatch.setattr(fd, "get_event_emitter", lambda: em)
    r = _client(fd.router, _dispute_db()).post("/api/v1/federation/disputes/settlements/set-sec20/approve", json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "FAILED" and r.json()["slash_type"] == "insufficient", r.text
    assert trust_recorder == [], f"an approval moved the peer's trust record: {trust_recorder}"
    assert [rec["_method"] for rec in em.received] == ["emit_dispute_slash"], em.received


def test_control_a_dispute_the_peer_lost_is_still_one_negative_observation(trust_recorder):
    """On the complainant's registry the defendant's registry confirmed the slash: the one negative evidence."""
    asyncio.run(fd._update_peer_trust_metrics(_dispute_db(), ASIA_URL, outcome="settled"))
    assert trust_recorder == [(3, False)]


# ── 4. the daily recompute (BayesianTrustService.run_decay_pass) ────────────────────────────────────────────────────

class _PeerDb:
    def __init__(self, peers):
        self.peers, self.commits = list(peers), 0

    async def execute(self, _stmt):
        return _Res(rows=self.peers)

    async def commit(self):
        self.commits += 1


def test_red_the_daily_recompute_is_a_function_of_the_record():
    p = beta(10, 0)
    idle_33 = peer_row("asia", record=(10, 0), idle_days=33, column=p)      # what the recorder left 33 days ago
    written = peer_row("lisbon", record=(10, 0), idle_days=1, column=1.0)   # a column nothing derived
    unmeasured = peer_row("hansa", record=(0, 0), column=1.0)
    db = _PeerDb([idle_33, written, unmeasured])
    svc = BayesianTrustService()
    asyncio.run(svc.run_decay_pass(db))
    asyncio.run(svc.run_decay_pass(db))   # a second pass on the same day changes nothing
    assert idle_33.bayesian_discount == pytest.approx(idle(p, 33), abs=1e-3)
    assert written.bayesian_discount == pytest.approx(p, abs=1e-3)
    assert unmeasured.bayesian_discount == pytest.approx(0.5)


# ── 5. the recorder (BayesianTrustService.record_interaction) ───────────────────────────────────────────────────────

class _RecorderDb:
    def __init__(self, counters):
        self.counters, self.writes = counters, []

    async def execute(self, stmt, params=None):
        if "RETURNING" in str(stmt):
            return _Res(one=self.counters)
        self.writes.append(dict(params or {}))
        return _Res()

    async def commit(self):
        return None

    async def rollback(self):
        return None


def test_red_the_recorder_writes_the_derivation_floor_included():
    db = _RecorderDb((20, 20))   # the counters after this observation: twenty interactions, twenty lost disputes
    asyncio.run(BayesianTrustService().record_interaction(db, 7, success=False))
    assert db.writes and db.writes[-1]["peer_id"] == 7
    assert db.writes[-1]["d"] == pytest.approx(0.1), db.writes   # the raw posterior mean is 1/22
    db = _RecorderDb((12, 1))
    asyncio.run(BayesianTrustService().record_interaction(db, 7, success=True))
    assert db.writes[-1]["d"] == pytest.approx(beta(12, 1)), db.writes
