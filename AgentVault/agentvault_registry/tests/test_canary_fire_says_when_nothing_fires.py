"""§MCPTEST30 V0637 (agentvault2-aa, 2026-10-24): a manual canary fire says so when no runner on this registry would
fire the path, instead of promising a fire within 5 s.

The MCP tester's operator sweep (agentvault2-66, 2026-10-24) read no fire within 30 s on either sandbox operator: both
run CANARY_RUNNER_MODE=follower, whose runner cycle returns before firing anything (followers fire only on their
master's dispatch), as every production cloud operator does. The route answered "Path will fire on next runner cycle
(within 5s)" all the same. It now answers 409 with the reason on a follower, on a registry without a runner and on a
paused fleet, and publishes nothing; a runner that fires local paths is answered as before (the control).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.background_tasks import canary_runner, leader
from agentvault_registry.routers import admin_canary


class _Db:
    async def execute(self, stmt):
        pid = next(iter(stmt.compile().params.values()))
        return SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(id=pid) if pid == 7 else None)


class _Redis:
    def __init__(self, paused=False):
        self.paused, self.published = paused, []

    async def get(self, key):
        return b"2026-10-24T08:00:00+00:00" if self.paused and key == canary_runner.CANARY_FLEET_PAUSED_KEY else None

    async def publish(self, channel, message):
        self.published.append((channel, message))


def _runner(monkeypatch, *, mode="master", enabled=True, runner_enabled=True, paused=False):
    monkeypatch.setattr(canary_runner, "CANARY_RUNNER_MODE", mode)
    monkeypatch.setattr(canary_runner, "CANARY_ENABLED", enabled)
    monkeypatch.setattr(canary_runner, "CANARY_RUNNER_ENABLED", runner_enabled)
    redis = _Redis(paused)

    async def _get_redis():
        return redis
    monkeypatch.setattr(leader, "get_redis", _get_redis)
    return redis


async def _fire(path_id=7):
    return await admin_canary.canary_fire({"path_id": path_id}, db=_Db(), _admin=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("setting, words", [
    ({"mode": "follower"}, "follower: it fires a path only when its master dispatches it"),
    ({"runner_enabled": False}, "No canary runner runs on this registry"),
    ({"enabled": False}, "No canary runner runs on this registry"),
    ({"paused": True}, "The canary fleet is paused"),
])
async def test_a_fire_no_runner_here_would_run_is_refused_with_the_reason(monkeypatch, setting, words):
    redis = _runner(monkeypatch, **setting)
    with pytest.raises(HTTPException) as e:
        await _fire()
    assert e.value.status_code == 409 and words in e.value.detail
    assert redis.published == []          # nothing was asked of a runner that would not answer


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["master", "local"])
async def test_control_a_runner_that_fires_local_paths_is_answered_as_before(monkeypatch, mode):
    redis = _runner(monkeypatch, mode=mode)
    answer = await _fire()
    assert answer["scheduled"] is True and answer["path_id"] == 7
    assert redis.published == [("canary_runner_force_fire", "7")]


@pytest.mark.asyncio
async def test_an_unknown_path_is_still_404_on_a_follower(monkeypatch):
    _runner(monkeypatch, mode="follower")
    with pytest.raises(HTTPException) as e:
        await _fire(path_id=8)
    assert e.value.status_code == 404
