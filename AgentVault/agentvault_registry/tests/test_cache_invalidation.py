"""Tests for the Phase 10 #3 cache_invalidation module.

The module wraps Redis pub/sub for cross-worker cache invalidation.
We mock `get_redis()` so the tests are hermetic — no live Redis required.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentvault_registry import cache_invalidation


@pytest.fixture(autouse=True)
def _reset_listener_registry():
    """Clear the module-level _listener_tasks registry between tests so
    start_invalidation_listener idempotency is observable."""
    # Cancel any leftover tasks
    for t in list(cache_invalidation._listener_tasks.values()):
        if not t.done():
            t.cancel()
    cache_invalidation._listener_tasks.clear()
    yield
    for t in list(cache_invalidation._listener_tasks.values()):
        if not t.done():
            t.cancel()
    cache_invalidation._listener_tasks.clear()


def test_channel_name_namespaced_per_registry(monkeypatch):
    monkeypatch.setenv("REGISTRY_NAME", "Registry-Test-A")
    assert cache_invalidation.channel_name("emission_policy") == (
        "cache_invalidate:registry-test-a:emission_policy"
    )


def test_channel_name_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("REGISTRY_NAME", raising=False)
    assert cache_invalidation.channel_name("xyz") == "cache_invalidate:default:xyz"


def test_channel_name_normalizes_spaces(monkeypatch):
    monkeypatch.setenv("REGISTRY_NAME", "Sandbox B Test")
    assert cache_invalidation.channel_name("foo") == "cache_invalidate:sandbox-b-test:foo"


@pytest.mark.asyncio
async def test_publish_invalidation_returns_false_when_redis_unavailable():
    """When Redis is offline (get_redis returns None), publish silently
    no-ops. The TTL-based refresh on each cache is the safety net."""
    with patch("agentvault_registry.background_tasks.leader.get_redis", new=AsyncMock(return_value=None)):
        ok = await cache_invalidation.publish_invalidation("emission_policy")
    assert ok is False


@pytest.mark.asyncio
async def test_publish_invalidation_calls_redis_publish_with_channel(monkeypatch):
    monkeypatch.setenv("REGISTRY_NAME", "test-reg")
    fake_redis = AsyncMock()
    fake_redis.publish.return_value = 3  # 3 subscribers received
    with patch("agentvault_registry.background_tasks.leader.get_redis", new=AsyncMock(return_value=fake_redis)):
        ok = await cache_invalidation.publish_invalidation("emission_policy")
    assert ok is True
    fake_redis.publish.assert_awaited_once_with(
        "cache_invalidate:test-reg:emission_policy", "invalidate"
    )


@pytest.mark.asyncio
async def test_publish_invalidation_returns_false_on_redis_exception():
    """Best-effort: Redis errors don't propagate to caller."""
    fake_redis = AsyncMock()
    fake_redis.publish.side_effect = ConnectionError("redis down")
    with patch("agentvault_registry.background_tasks.leader.get_redis", new=AsyncMock(return_value=fake_redis)):
        ok = await cache_invalidation.publish_invalidation("emission_policy")
    assert ok is False


@pytest.mark.asyncio
async def test_start_invalidation_listener_is_idempotent():
    """Second call for same cache_name returns the same task (no double-spawn)."""
    async def noop():
        pass

    t1 = cache_invalidation.start_invalidation_listener("test_cache", noop)
    t2 = cache_invalidation.start_invalidation_listener("test_cache", noop)
    assert t1 is t2
    # Cleanup
    t1.cancel()
    try:
        await t1
    except (asyncio.CancelledError, Exception):
        pass


@pytest.mark.asyncio
async def test_start_invalidation_listener_replaces_finished_task():
    """If the previous listener task finished (e.g., crashed), a new call
    spawns a fresh listener — we don't keep handing out a dead reference."""
    async def noop():
        pass

    t1 = cache_invalidation.start_invalidation_listener("test_cache_dead", noop)
    t1.cancel()
    try:
        await t1
    except (asyncio.CancelledError, Exception):
        pass
    assert t1.done()
    t2 = cache_invalidation.start_invalidation_listener("test_cache_dead", noop)
    assert t2 is not t1
    t2.cancel()
    try:
        await t2
    except (asyncio.CancelledError, Exception):
        pass


@pytest.mark.asyncio
async def test_stop_invalidation_listener_cancels_task():
    async def noop():
        await asyncio.sleep(60)

    t = cache_invalidation.start_invalidation_listener("test_cache_stop", noop)
    assert t in cache_invalidation._listener_tasks.values()

    await cache_invalidation.stop_invalidation_listener("test_cache_stop")
    assert "test_cache_stop" not in cache_invalidation._listener_tasks
    assert t.cancelled() or t.done()


@pytest.mark.asyncio
async def test_stop_invalidation_listener_noop_when_not_running():
    """stop is safe to call even if no listener was started."""
    await cache_invalidation.stop_invalidation_listener("never_started")
    # No exception → pass


@pytest.mark.asyncio
async def test_stop_all_listeners_cancels_every_running():
    async def noop():
        await asyncio.sleep(60)

    cache_invalidation.start_invalidation_listener("a", noop)
    cache_invalidation.start_invalidation_listener("b", noop)
    cache_invalidation.start_invalidation_listener("c", noop)
    assert len(cache_invalidation._listener_tasks) == 3

    await cache_invalidation.stop_all_listeners()
    assert len(cache_invalidation._listener_tasks) == 0
