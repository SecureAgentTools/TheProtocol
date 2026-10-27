"""§VITALS — the worker liveness contract.

The bug this suite exists to make impossible: a worker that fails every cycle and
reports a quiet, healthy-looking result. `velocity_snapshot` did exactly that for
the life of its deployment — its EventStore read died in a redirect, it logged
"No transfer events in window", and `velocity_metrics` stayed empty while the
IRONKEY rolling-24h spend cap summed 0 forever.

Every test here fails on the pre-2026-09-04 code.
"""
from __future__ import annotations

import time

import pytest

from agentvault_registry.background_tasks import vitals


# --------------------------------------------------------------------------- fakes
class FakeRedis:
    """Just enough Redis: hashes, counters, expiry, and a pipeline."""

    def __init__(self):
        self.h: dict[str, dict[str, str]] = {}
        self.expires: dict[str, int] = {}

    async def hset(self, key, field=None, value=None, mapping=None):
        d = self.h.setdefault(key, {})
        if mapping:
            d.update({k: str(v) for k, v in mapping.items()})
        if field is not None:
            d[field] = str(value)
        return 1

    async def hincrby(self, key, field, amount=1):
        d = self.h.setdefault(key, {})
        d[field] = str(int(d.get(field, 0)) + amount)
        return int(d[field])

    async def hsetnx(self, key, field, value):
        d = self.h.setdefault(key, {})
        if field in d:
            return 0
        d[field] = str(value)
        return 1

    async def hgetall(self, key):
        return dict(self.h.get(key, {}))

    async def expire(self, key, ttl):
        self.expires[key] = ttl
        return True

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, r: FakeRedis):
        self.r = r
        self.ops: list = []

    def hset(self, key, field=None, value=None, mapping=None):
        self.ops.append(("hset", key, field, value, mapping)); return self

    def hincrby(self, key, field, amount=1):
        self.ops.append(("hincrby", key, field, amount)); return self

    def expire(self, key, ttl):
        self.ops.append(("expire", key, ttl)); return self

    async def execute(self):
        for op in self.ops:
            if op[0] == "hset":
                await self.r.hset(op[1], op[2], op[3], mapping=op[4])
            elif op[0] == "hincrby":
                await self.r.hincrby(op[1], op[2], op[3])
            elif op[0] == "expire":
                await self.r.expire(op[1], op[2])
        self.ops = []
        return []


@pytest.fixture
def fake_redis(monkeypatch):
    r = FakeRedis()

    async def _r():
        return r

    monkeypatch.setattr(vitals, "_redis", _r)
    vitals._last_turn_write.clear()
    return r


def _state(r: FakeRedis, worker: str) -> dict:
    return r.h.get(f"{vitals.STATE_PREFIX}{worker}", {})


# --------------------------------------------------------------------------- cycle
async def test_a_clean_cycle_stamps_ok_and_a_success_time(fake_redis):
    async with vitals.cycle("w1") as ctx:
        ctx.note(processed=3)
    st = _state(fake_redis, "w1")
    assert st["last_outcome"] == vitals.OUTCOME_OK
    assert st["last_success_at"] == st["last_cycle_at"]
    assert st["cycles"] == "1"
    assert "processed" in st["last_stats"]


async def test_a_raising_cycle_stamps_error_and_re_raises(fake_redis):
    with pytest.raises(ValueError):
        async with vitals.cycle("w2"):
            raise ValueError("boom")
    st = _state(fake_redis, "w2")
    assert st["last_outcome"] == vitals.OUTCOME_ERROR
    assert "ValueError: boom" in st["last_error"]
    assert "last_success_at" not in st          # a failure never moves the success clock
    assert st["errors"] == "1"


async def test_a_handled_failure_is_still_a_failure(fake_redis):
    """THE velocity_snapshot CASE. The worker catches its own error and carries
    on, so no exception escapes — and the cycle is still not a success."""
    async with vitals.cycle("w3") as ctx:
        ctx.fail("event store unreachable")     # no raise
    st = _state(fake_redis, "w3")
    assert st["last_outcome"] == vitals.OUTCOME_ERROR
    assert st["last_error"] == "event store unreachable"
    assert "last_success_at" not in st


async def test_the_success_clock_does_not_move_on_a_later_failure(fake_redis):
    async with vitals.cycle("w4"):
        pass
    good = _state(fake_redis, "w4")["last_success_at"]
    async with vitals.cycle("w4") as ctx:
        ctx.fail("still broken")
    st = _state(fake_redis, "w4")
    assert st["last_success_at"] == good        # stale, which is what the alert reads
    assert st["last_cycle_at"] != good          # but the attempt clock did move
    assert st["cycles"] == "2" and st["errors"] == "1"


# --------------------------------------------------------------------------- liveness
async def test_stamp_turn_records_liveness_and_throttles(fake_redis):
    await vitals.stamp_turn("w5")
    assert "last_turn_at" in _state(fake_redis, "w5")
    first = _state(fake_redis, "w5")["last_turn_at"]
    await vitals.stamp_turn("w5")               # inside the throttle window
    assert _state(fake_redis, "w5")["last_turn_at"] == first
    vitals._last_turn_write["w5"] = time.time() - (vitals._TURN_THROTTLE_SEC + 1)
    await vitals.stamp_turn("w5")
    assert _state(fake_redis, "w5")["last_turn_at"] != first


async def test_a_turn_is_not_a_success(fake_redis):
    """Liveness and health are different questions: a loop that faithfully turns
    while every cycle fails is exactly the shape that hid the defect."""
    await vitals.stamp_turn("w6")
    st = _state(fake_redis, "w6")
    assert "last_turn_at" in st
    assert "last_success_at" not in st and "last_outcome" not in st


# --------------------------------------------------------------------------- roster
async def test_a_disabled_worker_is_a_row_not_an_absence(fake_redis):
    await vitals.register("w7", module="m", pattern="BackgroundWorker",
                          interval_sec=60, enabled=False, gate="X_ENABLED")
    snap = await vitals.snapshot()
    row = [w for w in snap["workers"] if w["worker_id"] == "w7"]
    assert row and row[0]["enabled"] is False and row[0]["gate"] == "X_ENABLED"
    assert row[0]["state"] == {}                # declared, never ran — and visible


async def test_a_worker_nobody_declared_still_joins_the_roster(fake_redis):
    """The old rail printed "(undocumented worker)" for 27 of the 50 it found,
    because its list was hand-maintained. Any leader-elected worker registers
    itself on its first turn."""
    await vitals.stamp_turn("w9")
    snap = await vitals.snapshot()
    row = [w for w in snap["workers"] if w["worker_id"] == "w9"]
    assert row and row[0]["pattern"] == "auto(leader)"


async def test_an_explicit_declaration_beats_the_auto_entry(fake_redis):
    await vitals.register("w10", module="m", pattern="BackgroundWorker", interval_sec=300)
    await vitals.stamp_turn("w10")
    snap = await vitals.snapshot()
    row = [w for w in snap["workers"] if w["worker_id"] == "w10"][0]
    assert row["pattern"] == "BackgroundWorker" and row["interval_sec"] == 300


async def test_a_leader_key_collapses_onto_its_worker(fake_redis):
    """Measured on the first live roster: five workers declare a leader_key that
    decorates their worker_id, so the turn stamp and the cycle stamp landed on
    two different rows — one ALIVE with no turn, one turning with no cycles."""
    assert vitals.canonical_worker_id("fx_reserve_keeper:leader") == "fx_reserve_keeper"
    assert vitals.canonical_worker_id("leader:bundle_retention") == "bundle_retention"
    assert vitals.canonical_worker_id("supply_auditor") == "supply_auditor"
    await vitals.stamp("gateway_float_keeper", vitals.OUTCOME_OK)
    await vitals.stamp_turn("gateway_float_keeper:leader")
    st = _state(fake_redis, "gateway_float_keeper")
    assert st["last_outcome"] == vitals.OUTCOME_OK and "last_turn_at" in st   # ONE row
    assert f"{vitals.STATE_PREFIX}gateway_float_keeper:leader" not in fake_redis.h


async def test_vitals_never_raises_when_redis_is_gone(monkeypatch):
    async def _none():
        return None
    monkeypatch.setattr(vitals, "_redis", _none)
    await vitals.stamp("w8", vitals.OUTCOME_OK)          # must not raise
    await vitals.stamp_turn("w8")
    await vitals.register("w8")
    snap = await vitals.snapshot()
    assert snap["error"] == "redis_unavailable"          # says so, never pretends
