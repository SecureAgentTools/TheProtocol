"""§DOCSFIX D6-604 + D6-602 (2026-10-16): the reputation routes answer the same from every worker, and the trust score's
integer is the one the engine published.

D6-604: the last epoch's result, the next scheduled run and the cross-frame reputation cache were module globals of
the process that ran the epoch (the leader). A gunicorn worker that did not run it answered /computation-status with
`next_scheduled_at` and `last_epoch_converged` null and /cross-frame with an empty list. They now live in Redis, which
every worker reads; without Redis they stay in the process that ran the epoch, and both routes say which (`state_store`
on /computation-status, `store` on /cross-frame: `shared` or `process`).

D6-602: GET /{did}/trust-score answered `integer_projection = int(global_trust * 1000)` whatever the registry's
`EIGENTRUST_PROJECTION`; under `log` the engine wrote a different `reputation_score`. The route now projects with the
engine's own function and the epoch's own floor, so the two agree (linear answers exactly what it did).

Routes through FastAPI's TestClient; "another worker" is this process with the engine's module state cleared.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.background_tasks import leader as LEADER
from agentvault_registry.database import get_db
from agentvault_registry.routers import reputation_trust as RT
from agentvault_registry.services import eigentrust_engine as E

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


class _FakeRedis:
    def __init__(self):
        self.kv = {}

    async def get(self, key):
        return self.kv.get(key)

    async def set(self, key, value, **kw):
        self.kv[key] = value
        return True


class _Res:
    def __init__(self, scalar=None, one=None):
        self._scalar, self._one = scalar, one

    def scalar(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._one


class _StatusDB:
    """Answers /computation-status's three reads: the latest epoch, the vector count, one row of that epoch."""

    def __init__(self):
        self._answers = [_Res(scalar=7), _Res(scalar=42),
                         _Res(one=SimpleNamespace(computed_at=NOW, computation_time_ms=1234))]

    async def execute(self, stmt):
        return self._answers.pop(0)


def _call(maybe):
    """The setters became coroutines with this fix; on the code before it they are plain functions."""
    out = maybe
    if inspect.isawaitable(out):
        out = asyncio.run(out)
    return out


def _forget_this_process(monkeypatch):
    monkeypatch.setattr(E, "_last_epoch_result", None)
    monkeypatch.setattr(E, "_next_scheduled_at", None)
    monkeypatch.setattr(E, "_foreign_reputation_cache", {})


def _client(db=None):
    app = FastAPI()
    app.include_router(RT.router)
    app.dependency_overrides[security.get_current_developer] = lambda: SimpleNamespace(id=3, is_admin=False)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    return TestClient(app)


@pytest.fixture
def redis(monkeypatch):
    r = _FakeRedis()

    async def _get():
        return r

    monkeypatch.setattr(LEADER, "get_redis", _get)
    _forget_this_process(monkeypatch)
    return r


def test_computation_status_from_a_worker_that_did_not_run_the_epoch(monkeypatch, redis):
    nxt = NOW + timedelta(hours=1)
    _call(E.set_last_epoch_result({"epoch": 7, "agents_computed": 42, "converged": True}))
    _call(E.set_next_scheduled_at(nxt))
    _forget_this_process(monkeypatch)                    # the read lands on another worker
    body = _client(_StatusDB()).get("/api/v1/reputation/computation-status").json()
    assert body["epoch"] == 7 and body["agents_computed"] == 42
    assert body["next_scheduled_at"] == nxt.isoformat()
    assert body["last_epoch_converged"] is True
    assert body["state_store"] == "shared"


def test_cross_frame_from_a_worker_that_did_not_fetch(monkeypatch, redis):
    entry = {"agent_did": "did:theprotocol:asia.theprotocol.cloud:abc", "global_trust": 0.42, "frame_id": "asia"}

    class _Http:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return SimpleNamespace(status_code=200, json=lambda: {"foreign_reputation": [entry]})

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _Http)
    monkeypatch.setenv("EVENT_STORE_API_KEY", "ci-dummy")
    assert asyncio.run(E._fetch_foreign_reputation(None)) == 1
    _forget_this_process(monkeypatch)
    body = _client().get("/api/v1/reputation/cross-frame").json()
    assert body["foreign_reputation"] == [entry] and body["agent_count"] == 1
    assert body["store"] == "shared"


def test_without_redis_the_routes_say_the_state_is_this_process(monkeypatch):
    async def _none():
        return None

    monkeypatch.setattr(LEADER, "get_redis", _none)
    _forget_this_process(monkeypatch)
    body = _client(_StatusDB()).get("/api/v1/reputation/computation-status").json()
    assert body["state_store"] == "process" and body["next_scheduled_at"] is None
    assert _client().get("/api/v1/reputation/cross-frame").json()["store"] == "process"


class _ScoreDB:
    def __init__(self, gt, floor):
        self._answers = [_Res(one=SimpleNamespace(agent_did="did:x", global_trust=gt, similarity_score=0.5,
                                                  epoch=7, computed_at=NOW)),
                         _Res(scalar=floor)]

    async def execute(self, stmt):
        return self._answers.pop(0)


@pytest.mark.parametrize("mode,gt,floor", [("log", 1e-4, 1e-7), ("log", 0.02, 1e-6), ("linear", 0.4567, 1e-7)])
def test_the_trust_score_integer_is_the_published_projection(monkeypatch, mode, gt, floor):
    monkeypatch.setattr(E, "PROJECTION_MODE", mode)
    body = _client(_ScoreDB(gt, floor)).get("/api/v1/reputation/did:x/trust-score").json()
    assert body["integer_projection"] == E._project(gt, floor)
    if mode == "log":
        assert body["integer_projection"] != min(1000, int(gt * 1000)), "the log projection differs from linear here"
    else:
        assert body["integer_projection"] == 456, "linear answers what it always did"
