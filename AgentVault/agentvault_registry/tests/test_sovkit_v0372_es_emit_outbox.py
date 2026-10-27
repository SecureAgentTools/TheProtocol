"""§SOVKIT K1 / V0372 (2026-09-14) — the registry's ledger emits get a durable outbox.

K1 deleted the registry's Kafka producer; agentvault2-85 then measured what it had been doing besides bypassing the
store's checks: buffering the registry's writes through a store restart. Without it the emitter's fast attempts lost every
emit during a store outage longer than ~4 s. Now: an emit the store could not take for a reason it may recover from
(a connection error, a timeout, 429, 5xx) is written to `es_emit_outbox` (migration 0178) and reported as deferred, never
lost; a 4xx is never deferred; when the table refuses too, the emit is lost as before (EMIT-LOST); the drainer re-emits
due rows, closes delivered ones and parks a row past its budget or refused for good.

The emitter is driven with a fake session (the exact shape `emit()` uses: `async with session.post(...) as response`),
one attempt per test so no backoff sleeps; the outbox write is recorded, never performed.
"""
from __future__ import annotations

import datetime
import logging
import os
import pathlib
import time

import pytest

from agentvault_registry import event_emitter as ee
from agentvault_registry.background_tasks import es_emit_outbox_drainer as od


class _Resp:
    def __init__(self, status, text=""):
        self.status, self._text = status, text

    async def text(self):
        return self._text

    async def json(self):
        return {"id": "e1", "event_id": "e1"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Session:
    """post() answers the next scripted item: a _Resp, or an exception raised at the call (the connection failing)."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), 0

    def post(self, url, data=None, headers=None):
        self.calls += 1
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


async def _noop(*a, **k):
    return None


def _emitter(session, monkeypatch):
    em = object.__new__(ee.EventEmitter)
    em.session = session
    em.source_service = "registry"
    em.federation_operator_id = None
    em.event_store_url = "http://store"
    em._auth_headers = lambda: {"X-Internal-Key": "x"}
    em._refresh_ssl_if_needed = _noop
    em._ensure_session = _noop
    em._broadcast_to_ws = _noop
    monkeypatch.setattr(ee, "_emission_policy_cache_ts", time.monotonic())   # fresh: no policy load from a database
    return em


@pytest.fixture
def enqueue(monkeypatch):
    calls = []

    async def _rec(event_payload, idem_key, last_error):
        calls.append((event_payload, idem_key, last_error))
        return True
    monkeypatch.setattr(ee, "_outbox_enqueue", _rec)
    monkeypatch.delenv("ES_EMIT_OUTBOX_ENABLED", raising=False)
    return calls


async def test_a_connection_error_is_deferred_not_lost(enqueue, monkeypatch, caplog):
    em = _emitter(_Session(ConnectionError("store down")), monkeypatch)
    out = {}
    with caplog.at_level(logging.WARNING, logger=ee.logger.name):
        ok = await em.emit(event_type="TokensTransferred", aggregate_id="did:a", data={"amount": "1"},
                           idempotency_key="xfer-1", max_retries=1, outcome=out)
    assert ok is True
    assert len(enqueue) == 1 and enqueue[0][1] == "xfer-1" and enqueue[0][0]["event_type"] == "TokensTransferred"
    assert enqueue[0][0]["data"] == {"amount": "1"} and enqueue[0][0]["idempotency_key"] == "xfer-1"
    assert out["retryable"] is True and out["status"] is None and "store down" in out["error"]
    assert any("[EMIT-DEFERRED]" in r.getMessage() and "xfer-1" in r.getMessage() for r in caplog.records)
    assert not any("Failed to emit event after" in r.getMessage() for r in caplog.records)


async def test_a_503_is_deferred_and_a_400_is_not(enqueue, monkeypatch):
    em = _emitter(_Session(_Resp(503, "unavailable")), monkeypatch)
    out = {}
    assert await em.emit(event_type="A2APaymentAuthorized", aggregate_id="did:b", data={}, idempotency_key="k503", max_retries=1, outcome=out) is True
    assert len(enqueue) == 1 and out["retryable"] is True and out["status"] == 503
    em = _emitter(_Session(_Resp(400, "bad event")), monkeypatch)
    out = {}
    assert await em.emit(event_type="A2APaymentAuthorized", aggregate_id="did:b", data={}, idempotency_key="k400", max_retries=1, outcome=out) is False
    assert len(enqueue) == 1, "a 4xx is never deferred: the store will never take it"
    assert out["retryable"] is False and out["status"] == 400


async def test_a_refused_outbox_row_leaves_the_emit_lost_as_before(monkeypatch, caplog):
    async def _refuse(event_payload, idem_key, last_error):
        return False
    monkeypatch.setattr(ee, "_outbox_enqueue", _refuse)
    monkeypatch.delenv("ES_EMIT_OUTBOX_ENABLED", raising=False)
    em = _emitter(_Session(ConnectionError("store down")), monkeypatch)
    with caplog.at_level(logging.ERROR, logger=ee.logger.name):
        ok = await em.emit(event_type="TokensBridgeLocked", aggregate_id="btx", data={}, idempotency_key="k-refused", max_retries=1)
    assert ok is False
    assert any("Failed to emit event after 1 attempts" in r.getMessage() for r in caplog.records)


async def test_defer_off_and_the_switch_off_never_enqueue(enqueue, monkeypatch):
    em = _emitter(_Session(ConnectionError("x")), monkeypatch)
    assert await em.emit(event_type="T", aggregate_id="a", data={}, idempotency_key="k1", max_retries=1, defer=False) is False
    assert enqueue == []
    monkeypatch.setenv("ES_EMIT_OUTBOX_ENABLED", "false")
    em = _emitter(_Session(ConnectionError("x")), monkeypatch)
    assert await em.emit(event_type="T", aggregate_id="a", data={}, idempotency_key="k2", max_retries=1) is False
    assert enqueue == []


async def test_a_success_and_a_409_never_touch_the_outbox(enqueue, monkeypatch):
    em = _emitter(_Session(_Resp(201)), monkeypatch)
    assert await em.emit(event_type="T", aggregate_id="a", data={}, idempotency_key="k-201", max_retries=1) is True
    em = _emitter(_Session(_Resp(409, "duplicate")), monkeypatch)
    assert await em.emit(event_type="T", aggregate_id="a", data={}, idempotency_key="k-409", max_retries=1) is True
    assert enqueue == []


def test_the_drainer_decides_by_the_emitters_outcome():
    now = datetime.datetime(2026, 9, 14, 21, 0, tzinfo=datetime.timezone.utc)
    assert od.next_state(3, True, {}, 720, now) == {"delivered_at": now}
    st = od.next_state(0, False, {"retryable": True, "status": 503, "error": "503 - unavailable"}, 720, now)
    assert st["attempts"] == 1 and st["last_error"] == "503 - unavailable" and st["next_attempt_at"] == now + datetime.timedelta(seconds=5)
    assert "dead_at" not in st
    st = od.next_state(4, False, {"retryable": True, "error": "x"}, 720, now)
    assert st["next_attempt_at"] == now + datetime.timedelta(seconds=60)
    st = od.next_state(0, False, {"retryable": False, "status": 400, "error": "400 - bad"}, 720, now)
    assert st["dead_at"] == now and st["attempts"] == 1, "a 4xx parks the row at once"
    st = od.next_state(719, False, {"retryable": True, "error": "still down"}, 720, now)
    assert st["dead_at"] == now and st["attempts"] == 720, "the budget parks the row"
    st = od.next_state(0, False, {}, 720, now)
    assert st["dead_at"] == now, "an empty outcome (refused before any attempt) is not retryable"


def test_the_backoff_ladder():
    assert [od.backoff_seconds(n) for n in (0, 1, 2, 3, 4, 5, 6, 100)] == [5, 5, 10, 20, 40, 60, 60, 60]


def test_the_switch_reads_one_name(monkeypatch):
    monkeypatch.delenv("ES_EMIT_OUTBOX_ENABLED", raising=False)
    assert od.outbox_enabled() is True and ee._outbox_enabled() is True
    monkeypatch.setenv("ES_EMIT_OUTBOX_ENABLED", "false")
    assert od.outbox_enabled() is False and ee._outbox_enabled() is False


def test_the_migration_and_the_model_agree():
    from agentvault_registry import models
    here = pathlib.Path(__file__).resolve().parent
    mig = None
    for p in (here.parent / "alembic" / "versions" / "0178_es_emit_outbox.py", pathlib.Path("/w/alembic/versions/0178_es_emit_outbox.py"),
              pathlib.Path("/app/alembic/versions/0178_es_emit_outbox.py")):
        if p.is_file():
            mig = p.read_text(encoding="utf-8")
            break
    if mig is None:
        pytest.skip("the migration file is not beside the tests here")
    assert 'revision = "0178_es_emit_outbox"' in mig and 'down_revision = "0177_bond_partial_release"' in mig
    assert len("0178_es_emit_outbox") <= 32
    assert models.EsEmitOutbox.__tablename__ == "es_emit_outbox" and '"es_emit_outbox"' in mig
    cols = set(models.EsEmitOutbox.__table__.columns.keys())
    assert {"id", "event_type", "aggregate_id", "aggregate_type", "payload", "idempotency_key", "attempts",
            "next_attempt_at", "created_at", "last_error", "delivered_at", "dead_at"} == cols


def test_main_starts_and_stops_the_drainer():
    here = pathlib.Path(__file__).resolve().parent
    for p in (here.parent / "src" / "agentvault_registry" / "main.py", pathlib.Path("/app/src/agentvault_registry/main.py")):
        if p.is_file():
            src = p.read_text(encoding="utf-8")
            assert "get_es_emit_outbox_drainer().start()" in src and "get_es_emit_outbox_drainer().stop()" in src
            return
    pytest.skip("main.py not found")
