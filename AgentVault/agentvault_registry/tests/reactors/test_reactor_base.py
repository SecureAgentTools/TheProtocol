"""Tests for the EventStoreReactor base class.

Covers parsing/dispatch correctness of `_on_event` and the validation
guarantees of the constructor (required class attrs, leader_key uniqueness).

The full WS lifecycle (connect, subscribe, reconnect, leadership renewal)
is exercised in the sandbox integration test, not here, to keep this suite
hermetic and fast.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import List

import pytest

from agentvault_registry.background_tasks import reactor_base
from agentvault_registry.background_tasks.reactor_base import EventStoreReactor


# ---------------------------------------------------------------------------- helpers

def _fresh_registry():
    """Reset the module-level leader_key registry between tests so subclass
    instantiations don't pollute each other."""
    reactor_base._registered_leader_keys.clear()


@pytest.fixture(autouse=True)
def reset_leader_key_registry():
    _fresh_registry()
    yield
    _fresh_registry()


def _make_reactor(event_type="TestEvent", leader_key="reactor_test", name="Test",
                  dispatch_mode="serial"):
    """Build a one-off concrete subclass at runtime and return an instance.

    §CHATCOHERE-CI (2026-09-01) — `dispatch_mode="serial"` is the fix for fourteen
    failures in this file, and it is a real seam rather than a workaround.

    §reactor-cqrs (2026-06-24) made the default dispatch CONCURRENT: `_dispatch_event`
    ends in `asyncio.create_task(_dispatch())`, so `await r._on_event(...)` returns
    BEFORE the handler has run. Every test here asserts on `captured` immediately
    afterwards, so they had been asserting on an empty list ever since — red, and
    unnoticed because nothing ran them.

    `serial` is the mode the class already offers for ordering-sensitive reactors and
    it awaits the handler inline, which is exactly what a unit test needs: a
    deterministic result instead of a race against a background task. The concurrent
    path keeps its own coverage in `test_dispatch_mode_concurrent_returns_before_handler`
    below, so the DEFAULT behaviour is still pinned — the fix does not quietly stop
    testing the shipping mode.
    """
    captured: List[dict] = []

    class _R(EventStoreReactor):
        async def handle_event(self, event_data: dict) -> None:
            captured.append(event_data)

    _R.event_type = event_type
    _R.leader_key = leader_key
    _R.name = name
    _R.dispatch_mode = dispatch_mode
    return _R(), captured


@pytest.mark.asyncio
async def test_dispatch_mode_concurrent_returns_before_handler():
    """The SHIPPING default must stay non-blocking — that is the whole point of
    §reactor-cqrs's concurrent mode (a 30ms handler otherwise caps a reactor at
    ~33 events/s and overflows the EventStore's per-client queue).

    Asserting it here means the `serial` harness above cannot hide a regression in
    the mode production actually runs.
    """
    r, captured = _make_reactor(leader_key="reactor_mode_concurrent",
                                dispatch_mode="concurrent")
    await r._on_event(_evt("evt-concurrent"))
    assert captured == []          # handler has NOT run yet — dispatch is a task
    await asyncio.sleep(0.05)      # let the loop run it
    assert len(captured) == 1


# ---------------------------------------------------------------------------- constructor guards

def test_missing_event_type_raises():
    class Incomplete(EventStoreReactor):
        leader_key = "x"
        async def handle_event(self, event_data):
            pass

    with pytest.raises(RuntimeError, match="event_type"):
        Incomplete()


def test_missing_leader_key_raises():
    class Incomplete(EventStoreReactor):
        event_type = "X"
        async def handle_event(self, event_data):
            pass

    with pytest.raises(RuntimeError, match="event_type and leader_key"):
        Incomplete()


def test_duplicate_leader_key_raises():
    a, _ = _make_reactor(leader_key="reactor_dupe")
    with pytest.raises(RuntimeError, match="leader_key collision"):
        _, _ = _make_reactor(leader_key="reactor_dupe")


# ---------------------------------------------------------------------------- _on_event dispatch

@pytest.mark.asyncio
async def test_on_event_dispatches_to_handler():
    r, captured = _make_reactor(event_type="TestEvent")
    payload = {
        "type": "event",
        "event": {"event_type": "TestEvent", "data": {"k": "v"}},
    }
    await r._on_event(json.dumps(payload))
    assert captured == [{"k": "v"}]


@pytest.mark.asyncio
async def test_on_event_filters_by_event_type():
    r, captured = _make_reactor(event_type="TestEvent")
    other = {
        "type": "event",
        "event": {"event_type": "DifferentEvent", "data": {"k": "v"}},
    }
    await r._on_event(json.dumps(other))
    assert captured == []


@pytest.mark.asyncio
async def test_on_event_ignores_non_event_messages():
    r, captured = _make_reactor()
    # WS protocol may push non-event control messages (subscribe acks, etc.)
    await r._on_event(json.dumps({"type": "subscribed", "channel": "events:TestEvent"}))
    assert captured == []


@pytest.mark.asyncio
async def test_on_event_ignores_malformed_json(caplog):
    r, captured = _make_reactor()
    with caplog.at_level(logging.DEBUG, logger="agentvault_registry.background_tasks.reactor_base"):
        await r._on_event("not-json-at-all")
    assert captured == []


@pytest.mark.asyncio
async def test_on_event_swallows_handler_exceptions(caplog):
    """A handler that raises must not crash the WS loop. The error is logged
    and the next event still dispatches."""
    captured: List[dict] = []

    class _Boom(EventStoreReactor):
        # §CHATCOHERE-CI — serial seam: see `_make_reactor`. Without it the
        # handler runs in a task created after this call returns.
        dispatch_mode = "serial"
        event_type = "TestEvent"
        leader_key = "reactor_boom"
        name = "Boom"

        async def handle_event(self, event_data):
            captured.append(event_data)
            if event_data.get("explode"):
                raise RuntimeError("kaboom")

    r = _Boom()
    bad = {"type": "event", "event": {"event_type": "TestEvent", "data": {"explode": True}}}
    good = {"type": "event", "event": {"event_type": "TestEvent", "data": {"explode": False}}}

    with caplog.at_level(logging.WARNING, logger="agentvault_registry.background_tasks.reactor_base"):
        await r._on_event(json.dumps(bad))
        await r._on_event(json.dumps(good))

    assert captured == [{"explode": True}, {"explode": False}]
    assert any("Handler error" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_on_event_handles_missing_event_field():
    r, captured = _make_reactor()
    # type=event but no event payload
    await r._on_event(json.dumps({"type": "event"}))
    assert captured == []


# ---------------------------------------------------------------------------- backlog-replay dedup

def _evt(event_id: str, etype="TestEvent", data=None):
    return json.dumps({
        "type": "event",
        "event": {
            "event_type": etype,
            "event_id": event_id,
            "data": data or {"k": "v"},
        },
    })


@pytest.mark.asyncio
async def test_dedup_skips_duplicate_event_id():
    """EventStore replays last 15 events on every reconnect — without dedup,
    handlers re-fire on every restart. The ring tracks event_ids of successfully
    handled events; replays match and are skipped, dedup_count increments."""
    r, captured = _make_reactor(leader_key="reactor_dedup_dup")
    msg = _evt("evt-001")

    await r._on_event(msg)
    assert len(captured) == 1
    assert r._dispatch_count == 1
    assert r._dedup_count == 0

    # Second emission of same event_id (simulates backlog replay)
    await r._on_event(msg)
    assert len(captured) == 1, "handler must NOT see replayed event"
    assert r._dispatch_count == 1, "dispatch_count must NOT increment on replay"
    assert r._dedup_count == 1, "dedup_count must increment on replay"


@pytest.mark.asyncio
async def test_dedup_does_not_skip_distinct_events():
    """Different event_ids are always handled — dedup must not over-fire."""
    r, captured = _make_reactor(leader_key="reactor_dedup_distinct")

    await r._on_event(_evt("evt-A"))
    await r._on_event(_evt("evt-B"))
    await r._on_event(_evt("evt-C"))

    assert len(captured) == 3
    assert r._dispatch_count == 3
    assert r._dedup_count == 0


@pytest.mark.asyncio
async def test_dedup_records_only_after_successful_handler():
    """If the handler raises, the event_id is NOT recorded — the next replay
    will retry. This is the safety net for transient failures."""
    captured: List[dict] = []

    class _Flaky(EventStoreReactor):
        # §CHATCOHERE-CI — serial seam: see `_make_reactor`. Without it the
        # handler runs in a task created after this call returns.
        dispatch_mode = "serial"
        event_type = "TestEvent"
        leader_key = "reactor_dedup_flaky"
        name = "Flaky"

        def __init__(self):
            super().__init__()
            self._calls = 0

        async def handle_event(self, event_data):
            self._calls += 1
            captured.append(event_data)
            if self._calls == 1:
                raise RuntimeError("transient")

    r = _Flaky()
    msg = _evt("evt-retry")

    # First call: handler raises, event_id NOT remembered, error_count++
    await r._on_event(msg)
    assert len(captured) == 1
    assert r._error_count == 1
    assert r._dedup_count == 0
    assert "evt-retry" not in r._seen_event_ids

    # Second call (replay): handler succeeds, event_id remembered
    await r._on_event(msg)
    assert len(captured) == 2
    assert r._dispatch_count == 1
    assert r._dedup_count == 0
    assert "evt-retry" in r._seen_event_ids


@pytest.mark.asyncio
async def test_dedup_ring_evicts_fifo_at_cap():
    """Ring is bounded — entries beyond _DEDUP_RING_CAP get evicted FIFO so
    memory stays bounded even under sustained load."""
    from agentvault_registry.background_tasks import reactor_base as rb

    r, captured = _make_reactor(leader_key="reactor_dedup_cap")

    # Fill the ring past the cap
    fill = rb._DEDUP_RING_CAP + 5
    for i in range(fill):
        await r._on_event(_evt(f"evt-{i:04d}"))

    assert r._dispatch_count == fill
    assert len(r._seen_event_ids) == rb._DEDUP_RING_CAP
    # Earliest entries should be evicted
    assert "evt-0000" not in r._seen_event_ids
    assert "evt-0004" not in r._seen_event_ids
    # Last entries should still be present
    assert f"evt-{fill - 1:04d}" in r._seen_event_ids


@pytest.mark.asyncio
async def test_dedup_status_exposes_count():
    """status() includes dedup_count so /admin/reactor/status surfaces it."""
    r, _ = _make_reactor(leader_key="reactor_dedup_status")
    msg = _evt("evt-status-1")

    await r._on_event(msg)
    await r._on_event(msg)
    await r._on_event(msg)

    s = r.status()
    assert s["dedup_count"] == 2
    assert s["dispatch_count"] == 1


@pytest.mark.asyncio
async def test_dedup_skips_events_without_event_id_gracefully():
    """Some legacy WS payloads omit event_id. Dedup should still let the
    handler fire — we just can't track these, which is acceptable."""
    r, captured = _make_reactor(leader_key="reactor_dedup_noid")

    msg = json.dumps({
        "type": "event",
        "event": {"event_type": "TestEvent", "data": {"k": "v"}},
    })
    await r._on_event(msg)
    await r._on_event(msg)

    assert len(captured) == 2
    assert r._dispatch_count == 2
    assert r._dedup_count == 0


# ---------------------------------------------------------------------------- ws_url derivation

def _clear_ws_token_env(monkeypatch):
    """Phase 10 #5: token env vars are auto-appended to the URL — clear them
    so the URL-shape tests stay deterministic across environments."""
    for k in (
        "EVENT_STORE_INTERNAL_API_KEY",
        "EVENT_STORE_API_KEY",
        "INTERNAL_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)


def test_ws_url_replaces_http_with_ws(monkeypatch):
    _clear_ws_token_env(monkeypatch)
    monkeypatch.setenv("EVENT_STORE_URL", "http://event-store-test:8200/")
    assert EventStoreReactor._ws_url() == "ws://event-store-test:8200/ws/events"


def test_ws_url_replaces_https_with_wss(monkeypatch):
    _clear_ws_token_env(monkeypatch)
    monkeypatch.setenv("EVENT_STORE_URL", "https://events.example.com")
    assert EventStoreReactor._ws_url() == "wss://events.example.com/ws/events"


def test_ws_url_default_when_env_unset(monkeypatch):
    _clear_ws_token_env(monkeypatch)
    monkeypatch.delenv("EVENT_STORE_URL", raising=False)
    assert EventStoreReactor._ws_url() == "ws://event-store:8200/ws/events"


def test_ws_url_includes_token_when_internal_key_set(monkeypatch):
    """Phase 10 #5: when an internal API key is configured, the WS handshake
    URL must carry it as ?token= so the EventStore side can validate when
    EVENTSTORE_WS_AUTH_REQUIRED=true."""
    _clear_ws_token_env(monkeypatch)
    monkeypatch.setenv("EVENT_STORE_URL", "http://event-store:8200")
    monkeypatch.setenv("EVENT_STORE_INTERNAL_API_KEY", "secret-key-abc")
    assert (
        EventStoreReactor._ws_url()
        == "ws://event-store:8200/ws/events?token=secret-key-abc"
    )


def test_ws_url_url_encodes_token(monkeypatch):
    """Tokens with special chars must be URL-encoded so they don't break the
    handshake parser."""
    _clear_ws_token_env(monkeypatch)
    monkeypatch.setenv("EVENT_STORE_URL", "http://event-store:8200")
    monkeypatch.setenv("EVENT_STORE_INTERNAL_API_KEY", "abc/def+ghi=")
    url = EventStoreReactor._ws_url()
    assert url == "ws://event-store:8200/ws/events?token=abc%2Fdef%2Bghi%3D"


# ---------------------------------------------------------------------------- Phase C3: Redis-backed cross-worker counter unification

class _FakeRedis:
    """Minimal Redis HASH shim — supports HSET / HINCRBY / HGETALL + a pipeline
    that defers HSET / HINCRBY until execute(). Everything decoded as str so
    the shim mirrors `decode_responses=True` from leader.py:get_redis()."""

    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}
        self.strings: dict[str, str] = {}
        self.calls: list[tuple] = []  # for assertion convenience

    async def hincrby(self, key: str, field: str, amount: int = 1) -> int:
        self.calls.append(("hincrby", key, field, amount))
        h = self.hashes.setdefault(key, {})
        new = int(h.get(field, "0")) + amount
        h[field] = str(new)
        return new

    async def hset(self, key: str, *args, mapping: dict | None = None, **kwargs) -> int:
        self.calls.append(("hset", key, mapping, args, kwargs))
        h = self.hashes.setdefault(key, {})
        if mapping:
            for k, v in mapping.items():
                h[k] = str(v)
        # Also support hset(key, field, value) signature
        if len(args) >= 2 and not mapping:
            h[args[0]] = str(args[1])
        return 1

    async def hgetall(self, key: str) -> dict:
        return dict(self.hashes.get(key, {}))

    # --- plain string keys -------------------------------------------------
    # §CHATCOHERE-CI (2026-09-01): status_async() GETs the leader LEASE key
    # ("leader:<leader_key>") alongside the status HASH. The shim knew only
    # hashes, so a test that pre-seeded the hash could never be read back.
    async def set(self, key: str, value: str, **kwargs) -> bool:
        self.calls.append(("set", key, value))
        self.strings[key] = str(value)
        return True

    async def get(self, key: str):
        return self.strings.get(key)

    def pipeline(self, transaction: bool = True):
        return _FakePipeline(self)


class _FakePipeline:
    """Pipeline accumulator that flushes on execute(). Async context-manager
    matches `redis.asyncio.Redis.pipeline()` usage in reactor_base."""

    def __init__(self, parent: _FakeRedis):
        self.parent = parent
        self.queued: list[tuple] = []

    def hincrby(self, key, field, amount=1):
        self.queued.append(("hincrby", key, field, amount))
        return self

    def hset(self, key, *args, mapping=None):
        self.queued.append(("hset", key, args, mapping))
        return self

    def get(self, key):
        self.queued.append(("get", key))
        return self

    def hgetall(self, key):
        self.queued.append(("hgetall", key))
        return self

    async def execute(self):
        results = []
        for op in self.queued:
            if op[0] == "hincrby":
                _, k, f, n = op
                results.append(await self.parent.hincrby(k, f, n))
            elif op[0] == "hset":
                _, k, args, mapping = op
                results.append(await self.parent.hset(k, *args, mapping=mapping))
            elif op[0] == "get":
                results.append(await self.parent.get(op[1]))
            elif op[0] == "hgetall":
                results.append(await self.parent.hgetall(op[1]))
        self.queued.clear()
        return results

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture
def fake_redis(monkeypatch):
    """Replace reactor_base.get_redis with a fake that returns a _FakeRedis."""
    fake = _FakeRedis()

    async def _get_redis():
        return fake

    monkeypatch.setattr(reactor_base, "get_redis", _get_redis)
    return fake


@pytest.fixture
def no_redis(monkeypatch):
    """Replace reactor_base.get_redis with a stub that returns None
    (Redis unconfigured / unreachable). Verifies the local fallback path."""

    async def _get_redis():
        return None

    monkeypatch.setattr(reactor_base, "get_redis", _get_redis)


@pytest.mark.asyncio
async def test_record_dispatch_writes_redis_hash(fake_redis, monkeypatch):
    """Successful dispatch writes dispatch_count + last_dispatch_ms to Redis HASH
    AND increments the in-memory fallback counter."""
    monkeypatch.setenv("REGISTRY_NAME", "registry-test")
    r, captured = _make_reactor(leader_key="reactor_c3_dispatch")

    await r._on_event(_evt("c3-evt-1"))

    expected_key = "reactor_status:registry-test:reactor_c3_dispatch"
    assert expected_key in fake_redis.hashes
    h = fake_redis.hashes[expected_key]
    assert h["dispatch_count"] == "1"
    assert "last_dispatch_ms" in h
    assert h["last_event_id"] == "c3-evt-1"
    assert "last_event_iso" in h
    # Local fallback fields also updated
    assert r._dispatch_count == 1
    assert r._last_event_id == "c3-evt-1"


@pytest.mark.asyncio
async def test_record_dispatch_falls_back_local_when_redis_none(no_redis):
    """When get_redis() returns None, local in-memory counters still increment."""
    r, captured = _make_reactor(leader_key="reactor_c3_no_redis")

    await r._on_event(_evt("c3-evt-noredis"))

    assert r._dispatch_count == 1
    assert r._dedup_count == 0
    assert r._last_event_id == "c3-evt-noredis"
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_record_dedup_writes_redis(fake_redis, monkeypatch):
    """Replay-dedup hit increments dedup_count in both Redis and local."""
    monkeypatch.setenv("REGISTRY_NAME", "registry-test")
    r, _ = _make_reactor(leader_key="reactor_c3_dedup")
    msg = _evt("c3-dedup-evt")

    await r._on_event(msg)  # first: dispatched, recorded
    await r._on_event(msg)  # second: replay, dedup hit
    await r._on_event(msg)  # third: replay, dedup hit

    h = fake_redis.hashes["reactor_status:registry-test:reactor_c3_dedup"]
    assert h["dedup_count"] == "2"
    assert h["dispatch_count"] == "1"
    assert r._dedup_count == 2
    assert r._dispatch_count == 1


@pytest.mark.asyncio
async def test_record_error_writes_redis(fake_redis, monkeypatch):
    """Handler exceptions increment error_count + set last_error in Redis."""
    monkeypatch.setenv("REGISTRY_NAME", "registry-test")

    class _Boom(EventStoreReactor):
        # §CHATCOHERE-CI — serial seam: see `_make_reactor`. Without it the
        # handler runs in a task created after this call returns.
        dispatch_mode = "serial"
        event_type = "TestEvent"
        leader_key = "reactor_c3_err"
        name = "Err"

        async def handle_event(self, event_data):
            raise RuntimeError("kaboom")

    r = _Boom()
    await r._on_event(_evt("c3-err-evt"))

    h = fake_redis.hashes["reactor_status:registry-test:reactor_c3_err"]
    assert h["error_count"] == "1"
    assert "kaboom" in h["last_error"]
    assert r._error_count == 1


@pytest.mark.asyncio
async def test_status_async_merges_redis_with_local_state(fake_redis, monkeypatch):
    """status_async() overlays Redis counter values on the local view.

    §CHATCOHERE-CI (2026-09-01) — this test's original contract was "per-worker
    fields (running, is_leader, ws_connected) win from local". Phase C4 changed
    that DELIBERATELY: `is_leader` is now a CLUSTER fact read from the lease key
    (`leader:<leader_key>`), not this worker's local flag, and `ws_connected` is
    forced False when there is no lease ("no leader → no live WS by definition").

    The product is right and the old assertion was wrong: a worker whose local
    `_is_leader` outlived its lease is exactly the lapsed-lock second-writer
    hazard, and reporting it as leader would hide that. So the test now seeds the
    lease to claim leadership, and `test_status_async_stale_local_leader_flag_
    loses_to_absent_lease` below pins the opposite direction.
    """
    monkeypatch.setenv("REGISTRY_NAME", "registry-test")
    r, _ = _make_reactor(leader_key="reactor_c3_merge")
    # The lease is what makes a reactor the leader — claim it.
    await fake_redis.set("leader:reactor_c3_merge", "worker-1")

    # Pre-seed Redis HASH with cross-worker counters
    fake_redis.hashes["reactor_status:registry-test:reactor_c3_merge"] = {
        "dispatch_count": "42",
        "error_count": "3",
        "dedup_count": "7",
        "last_event_id": "evt-from-other-worker",
        "last_event_iso": "2026-04-29T00:00:00+00:00",
        "last_dispatch_ms": "12.34",
        "last_error": "handler: ValueError: x",
    }
    # This worker's local state is fresh
    assert r._dispatch_count == 0
    r._is_leader = True
    r._ws_connected = True

    s = await r.status_async()

    # Counter + last-event fields come from Redis
    assert s["dispatch_count"] == 42
    assert s["error_count"] == 3
    assert s["dedup_count"] == 7
    assert s["last_event_id"] == "evt-from-other-worker"
    assert s["last_event_at"] == "2026-04-29T00:00:00+00:00"
    assert s["last_dispatch_ms"] == 12.34
    assert s["last_error"] == "handler: ValueError: x"
    # Leadership from the LEASE (Phase C4), not the local flag
    assert s["is_leader"] is True
    assert s["leader_worker"] == "worker-1"
    assert s["ws_connected"] is True
    assert s["leader_key"] == "reactor_c3_merge"


@pytest.mark.asyncio
async def test_status_async_falls_back_when_redis_empty(fake_redis):
    """Cold reactor (no Redis HASH yet) returns local in-memory view."""
    r, _ = _make_reactor(leader_key="reactor_c3_empty")
    r._dispatch_count = 5  # worker has handled some events but never wrote to Redis

    s = await r.status_async()

    # Falls back to local since Redis HASH is empty
    assert s["dispatch_count"] == 5


@pytest.mark.asyncio
async def test_status_async_falls_back_when_redis_none(no_redis):
    """When Redis is unconfigured, status_async returns local view."""
    r, _ = _make_reactor(leader_key="reactor_c3_none")
    r._dispatch_count = 11

    s = await r.status_async()

    assert s["dispatch_count"] == 11


@pytest.mark.asyncio
async def test_snapshot_status_async_aggregates_all_instances(fake_redis, monkeypatch):
    """snapshot_status_async() returns one entry per live reactor, each with
    its Redis-merged view."""
    monkeypatch.setenv("REGISTRY_NAME", "registry-test")
    r1, _ = _make_reactor(event_type="EvtA", leader_key="reactor_c3_agg_a", name="A")
    r2, _ = _make_reactor(event_type="EvtB", leader_key="reactor_c3_agg_b", name="B")

    fake_redis.hashes["reactor_status:registry-test:reactor_c3_agg_a"] = {"dispatch_count": "1"}
    fake_redis.hashes["reactor_status:registry-test:reactor_c3_agg_b"] = {"dispatch_count": "2"}

    snap = await EventStoreReactor.snapshot_status_async()

    assert len(snap) >= 2
    by_key = {s["leader_key"]: s for s in snap}
    assert by_key["reactor_c3_agg_a"]["dispatch_count"] == 1
    assert by_key["reactor_c3_agg_b"]["dispatch_count"] == 2


@pytest.mark.asyncio
async def test_redis_status_key_uses_registry_name_env(monkeypatch):
    """The HASH key embeds the REGISTRY_NAME env so each frame's Redis is namespaced."""
    monkeypatch.setenv("REGISTRY_NAME", "frame-b-registry")
    r, _ = _make_reactor(leader_key="reactor_c3_keytest")

    assert r._redis_status_key == "reactor_status:frame-b-registry:reactor_c3_keytest"


# ---------------------------------------------------------------------------- start/stop lifecycle

@pytest.mark.asyncio
async def test_start_is_idempotent(monkeypatch):
    """start() called twice should not spawn two WS loops."""
    r, _ = _make_reactor(leader_key="reactor_idem")

    # Make _ws_loop a no-op that completes immediately so we don't hang on the
    # initial 15s sleep. Use a very short sleep to give create_task a tick.
    async def fake_loop(self):
        await asyncio.sleep(0)

    monkeypatch.setattr(EventStoreReactor, "_ws_loop", fake_loop)

    await r.start()
    first_task = r._task
    await r.start()
    assert r._task is first_task  # second call did not spawn another task
    await r.stop()


@pytest.mark.asyncio
async def test_status_async_stale_local_leader_flag_loses_to_absent_lease(fake_redis, monkeypatch):
    """The other direction, and the one that matters for safety.

    A worker can hold `_is_leader = True` after its lease has expired — the lapsed
    lock that makes a SECOND WRITER. `status_async` must report the lease's answer
    (no lease ⇒ not leader, and no live WS), never the stale local belief.
    """
    monkeypatch.setenv("REGISTRY_NAME", "registry-test")
    r, _ = _make_reactor(leader_key="reactor_c3_stale")
    r._is_leader = True          # stale local belief
    r._ws_connected = True       # and a socket it thinks is live
    # No lease key seeded: the lock has lapsed.

    s = await r.status_async()

    assert s["is_leader"] is False
    assert s["leader_worker"] is None
    assert s["ws_connected"] is False
