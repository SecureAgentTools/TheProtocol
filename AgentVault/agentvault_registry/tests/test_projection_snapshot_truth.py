"""D6-818 (2026-10-24) — the projection snapshot route answers "snapshot_taken" only for a snapshot the store took.

Found by agentvault2-aa's MCP History run on sbx-alpha (6166c97b, 2026-10-24): sbx-alpha's snapshot of 10,254 agents
(1,074,935 bytes) was refused by the store's bus every time ("Kafka publish failed: MessageSizeTooLargeError", 503); the
emitter parked it in es_emit_outbox, the drainer retried it for 12 hours and parked it dead (5 dead rows, 2 pending), and the
route answered "snapshot_taken" each time. Now a snapshot that cannot fit is refused before anything is sent (422), one the
store refuses for now answers 503 and is never queued, a policy block answers 409, and only a stored one is "snapshot_taken".
"""
from __future__ import annotations

import asyncio
import os
import uuid
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/t")
os.environ.setdefault("API_KEY_SECRET", "test-only-secret-value-0123456789abcdef")

from fastapi import HTTPException  # noqa: E402

STORE_SAYS = "503 - Kafka publish failed: MessageSizeTooLargeError"


def _rows(n):
    return [SimpleNamespace(did=f"did:theprotocol:{uuid.UUID(int=i + 1)}", liquid_balance=1234.567891, staked_balance=0)
            for i in range(n)]


class _DB:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, stmt):
        return SimpleNamespace(all=lambda: self.rows)


class _Client:
    """The TEG's treasury info answers 200."""

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        return SimpleNamespace(status_code=200)


class _Emitter:
    """emit() as event_emitter.EventEmitter.emit behaves for a store that answers `store_status`: 201 takes the event; a
    5xx is parked in the outbox (True) when defer is on, as V0637's route asked, and reported in `outcome` (False) when it
    is off; a policy block returns True and, since D6-818, says so in `outcome`."""

    def __init__(self, store_status=201, blocked=False):
        self.store_status, self.blocked, self.received = store_status, blocked, []

    async def emit(self, event_type, aggregate_id, data, aggregate_type="Agent", metadata=None, idempotency_key=None,
                   max_retries=3, defer=True, outcome=None):
        self.received.append({"event_type": event_type, "defer": defer, "agents": len(data.get("agents", []))})
        if self.blocked:
            if outcome is not None:
                outcome.update({"blocked_by_policy": True, "retryable": False, "status": None, "error": None})
            return True
        if self.store_status in (201, 202, 409):
            return True
        retryable = self.store_status >= 500
        if outcome is not None:
            outcome.update({"retryable": retryable, "status": self.store_status, "error": STORE_SAYS})
        return bool(defer and retryable)   # parked in es_emit_outbox, as the real emitter does


@pytest.fixture
def snap(monkeypatch):
    monkeypatch.setenv("ENABLE_PROJECTION_SNAPSHOTS", "true")
    monkeypatch.delenv("PROJECTION_SNAPSHOT_MAX_BYTES", raising=False)
    from agentvault_registry.routers import admin_health as ah
    import agentvault_registry.event_emitter as ee
    monkeypatch.setattr(ah.httpx, "AsyncClient", _Client)

    def call(emitter, n):
        monkeypatch.setattr(ee, "get_event_emitter", lambda: emitter)
        return asyncio.run(ah.take_projection_snapshot(current_developer=SimpleNamespace(id=1), db=_DB(_rows(n))))
    return call


def test_a_stored_snapshot_is_taken(snap):
    em = _Emitter(201)
    out = snap(em, 3)
    assert out["status"] == "snapshot_taken" and out["agent_count"] == 3 and out["event_bytes"] > 0
    assert em.received == [{"event_type": "ProjectionSnapshot", "defer": False, "agents": 3}]


def test_a_store_refusal_answers_503_and_nothing_is_queued(snap):
    em = _Emitter(503)
    with pytest.raises(HTTPException) as ei:
        snap(em, 3)
    assert ei.value.status_code == 503 and ei.value.headers == {"Retry-After": "60"}
    assert ei.value.detail.startswith("snapshot_not_stored:") and "MessageSizeTooLargeError" in ei.value.detail
    assert "nothing was queued" in ei.value.detail
    assert [c["defer"] for c in em.received] == [False], "the route let the emitter park the snapshot in the outbox"


def test_control_the_v0637_call_read_a_parked_refusal_as_success():
    """Control: the same store refusal, sent the way V0637's route sent it (defer left on), came back True: the route read
    that as "snapshot_taken". So the 503 above is the route's new call, not the fake."""
    em = _Emitter(503)
    assert asyncio.run(em.emit("ProjectionSnapshot", "system", {"agents": []}, aggregate_type="System")) is True


def test_sbx_alphas_snapshot_is_refused_before_anything_is_sent(snap):
    """The real case: 10,254 agents do not fit under the default limit; nothing reaches the emitter."""
    em = _Emitter(201)
    with pytest.raises(HTTPException) as ei:
        snap(em, 10_254)
    assert ei.value.status_code == 422 and ei.value.detail.startswith("snapshot_too_large:")
    assert "10254 agents" in ei.value.detail and "1000000 bytes" in ei.value.detail
    assert em.received == []


def test_sbx_betas_snapshot_still_fits(snap):
    """Control: 1,432 agents (sbx-beta's) are well under the limit and are taken."""
    em = _Emitter(201)
    assert snap(em, 1_432)["status"] == "snapshot_taken"


def test_the_limit_is_a_setting(snap, monkeypatch):
    monkeypatch.setenv("PROJECTION_SNAPSHOT_MAX_BYTES", "200")
    em = _Emitter(201)
    with pytest.raises(HTTPException) as ei:
        snap(em, 3)
    assert ei.value.status_code == 422 and "limit of 200 bytes" in ei.value.detail and em.received == []


def test_a_policy_block_is_not_a_snapshot(snap):
    em = _Emitter(201, blocked=True)
    with pytest.raises(HTTPException) as ei:
        snap(em, 3)
    assert ei.value.status_code == 409 and ei.value.detail.startswith("snapshot_blocked_by_policy:")


def test_a_refusal_the_store_will_keep_is_502(snap):
    em = _Emitter(400)
    with pytest.raises(HTTPException) as ei:
        snap(em, 3)
    assert ei.value.status_code == 502 and ei.value.detail.startswith("snapshot_refused_by_store:")


def test_the_emitter_names_a_policy_block_in_outcome(monkeypatch):
    """The real emitter: a policy block still returns True (its other callers rely on that) and now says so when asked."""
    import agentvault_registry.event_emitter as ee
    monkeypatch.setattr(ee, "_get_emission_policy", lambda event_type, source: False)
    monkeypatch.setattr(ee, "_emission_policy_cache_ts", ee._time.monotonic())
    em = ee.EventEmitter(source_service="registry")

    async def _nothing():
        return None
    monkeypatch.setattr(em, "_refresh_ssl_if_needed", _nothing)
    monkeypatch.setattr(em, "_ensure_session", _nothing)
    outcome = {}
    assert asyncio.run(em.emit("ProjectionSnapshot", "system", {"agents": []}, outcome=outcome)) is True
    assert outcome.get("blocked_by_policy") is True
    assert asyncio.run(em.emit("ProjectionSnapshot", "system", {"agents": []})) is True   # no outcome asked: unchanged
