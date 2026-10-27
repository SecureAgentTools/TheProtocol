"""§DOCSFIX D6-567 + CB-239 (2026-10-16): the auto-tally configuration reaches the loop that tallies.

PUT /api/v1/governance/auto-tally/config kept its overrides in module globals of the one gunicorn worker that answered
it, while the tally loop runs in whichever worker holds the leader lock; and the loop read its interval once, when it
started. So an interval change never reached the running loop, an `enabled` change only where the PUT happened to land
on the leader, and `enabled: false` did not stop the federation sweep the same loop runs. The overrides now live in
Redis, which every worker reads (a registry without Redis keeps them in the answering process and the config says so:
`store` is `shared` or `process`); the loop reads the configuration on every turn, and the switch covers both sweeps.

The route is driven through FastAPI's TestClient against an in-memory Redis double; "another worker" is this process
with its module globals cleared, which is all a second gunicorn worker has.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.background_tasks import auto_tally as AT
from agentvault_registry.background_tasks import leader as LEADER
from agentvault_registry.routers import governance as GOV


class _FakeRedis:
    def __init__(self):
        self.hashes = {}

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def hset(self, key, mapping=None, **kw):
        self.hashes.setdefault(key, {}).update({k: str(v) for k, v in (mapping or {}).items()})
        return len(mapping or {})


def _forget_this_process(monkeypatch):
    """What a second worker process holds: none of this process's module globals."""
    monkeypatch.setattr(AT, "_runtime_enabled", None)
    monkeypatch.setattr(AT, "_runtime_interval", None)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTO_TALLY_ENABLED", "true")
    monkeypatch.setenv("AUTO_TALLY_INTERVAL_SECONDS", "60")
    _forget_this_process(monkeypatch)
    app = FastAPI()
    app.include_router(GOV.router, prefix="/api/v1/governance")
    app.dependency_overrides[security.get_current_developer] = lambda: SimpleNamespace(
        id=1, email="admin@frame.example", is_admin=True, must_change_password=False)
    return TestClient(app)


def test_a_change_reaches_every_worker(monkeypatch, client):
    redis = _FakeRedis()

    async def _get_redis():
        return redis

    monkeypatch.setattr(LEADER, "get_redis", _get_redis)
    r = client.put("/api/v1/governance/auto-tally/config", json={"interval_seconds": 120, "enabled": False})
    assert r.status_code == 200, r.text
    assert r.json() == {"enabled": False, "interval_seconds": 120, "source": "runtime", "store": "shared"}
    _forget_this_process(monkeypatch)                    # the GET lands on another worker
    got = client.get("/api/v1/governance/auto-tally/config").json()
    assert (got["enabled"], got["interval_seconds"], got["store"]) == (False, 120, "shared")


def test_without_redis_the_config_says_it_holds_in_this_process_only(monkeypatch, client):
    async def _no_redis():
        return None

    monkeypatch.setattr(LEADER, "get_redis", _no_redis)
    r = client.put("/api/v1/governance/auto-tally/config", json={"interval_seconds": 90})
    assert r.json() == {"enabled": True, "interval_seconds": 90, "source": "runtime", "store": "process"}
    got = client.get("/api/v1/governance/auto-tally/config").json()
    assert (got["interval_seconds"], got["store"]) == (90, "process")


def _drive(monkeypatch, configs):
    """Run the worker loop for len(configs) turns, each turn reading the next configuration (the start reads the
    first one too)."""
    reads = [configs[0]] + list(configs)
    slept, cycles = [], []

    async def _config():
        return reads.pop(0) if len(reads) > 1 else reads[0]

    async def _leader(name):
        return True

    class _Cycle:
        async def __aenter__(self):
            return SimpleNamespace(note=lambda **k: None)

        async def __aexit__(self, *a):
            return False

    async def _register(*a, **k):
        return None

    worker = AT.AutoTallyWorker()

    async def _sleep(seconds):
        slept.append(seconds)
        if len(slept) >= len(configs):
            worker.running = False

    async def _tally():
        cycles.append("tally")

    async def _federation():
        cycles.append("federation")

    from agentvault_registry.background_tasks import vitals
    monkeypatch.setattr(AT, "get_config", _config)
    monkeypatch.setattr(LEADER, "try_acquire_leadership", _leader)
    monkeypatch.setattr(vitals, "register", _register)
    monkeypatch.setattr(vitals, "cycle", lambda name: _Cycle())
    monkeypatch.setattr(AT.asyncio, "sleep", _sleep)
    monkeypatch.setattr(worker, "_tally_cycle", _tally)
    monkeypatch.setattr(worker, "_federation_cycle", _federation)
    asyncio.run(worker.run_forever())
    return slept, cycles


def _cfg(enabled, interval):
    return {"enabled": enabled, "interval_seconds": interval, "source": "runtime", "store": "shared"}


def test_the_running_loop_takes_a_new_interval(monkeypatch):
    slept, cycles = _drive(monkeypatch, [_cfg(True, 60), _cfg(True, 60), _cfg(True, 300), _cfg(True, 300)])
    assert slept[-2:] == [300, 300], slept


def test_disabled_stops_both_sweeps(monkeypatch):
    slept, cycles = _drive(monkeypatch, [_cfg(True, 60), _cfg(False, 60), _cfg(False, 60)])
    assert cycles == ["tally", "federation"], "only the first, enabled turn sweeps"
