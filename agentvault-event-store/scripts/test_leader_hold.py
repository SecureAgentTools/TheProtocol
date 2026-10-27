#!/usr/bin/env python3
"""
Regression test for the 2026-07-31 EventStore metrics scan pile-up (task #106).

WHAT IT PROVES
    When the guarded work outlives LOCK_TTL:
      OLD  try_acquire_leadership alone  -> lock lapses mid-work -> OVERLAP
      NEW  hold_leadership (heartbeat)   -> lock stays held      -> NO OVERLAP

NEGATIVE CONTROL — the point of the whole file:
    The OLD path must be observed to overlap. If it does not, this harness is not
    reproducing the bug and the NEW result means nothing, so we FAIL rather than
    report a pass. A test that cannot detect the bug is not evidence.
    (Doctrine: two pieces of my own code agreeing is not a test.)

Timings are scaled down ~30x from prod (TTL 90s / renew 30s / scan ~26-150s) so
the whole thing runs in ~25s of real time instead of needing a patched clock.

    python3 scripts/test_leader_hold.py
"""
import asyncio
import importlib.util
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub `redis.asyncio` so this runs on any host without the driver installed.
# Safe: the test monkeypatches leader.get_redis, so the real client is never
# constructed. leader.py uses `from __future__ import annotations`, so the
# `aioredis.Redis` annotations stay unevaluated strings.
if "redis" not in sys.modules:
    _m = types.ModuleType("redis")
    _a = types.ModuleType("redis.asyncio")
    _a.Redis = object
    _a.from_url = lambda *a, **k: None
    _m.asyncio = _a
    sys.modules["redis"] = _m
    sys.modules["redis.asyncio"] = _a

from src import leader  # noqa: E402

LEADER_PATH = os.path.join(os.path.dirname(__file__), "..", "src", "leader.py")

# Scaled-down prod ratios: work (7s) > TTL (3s), renew at 1s = 3x margin.
leader.LOCK_TTL = 3
leader.RENEW_INTERVAL = 1
WORK_SECONDS = 7.0
TICK_SECONDS = 2.0
N_WORKERS = 8
N_TICKS = 6


class FakeRedis:
    """Minimal TTL-aware Redis. Only the calls leader.py actually makes.

    NOTE: `eval` emulates the compare-and-extend semantics rather than running
    real Lua. The Lua itself is verified separately against a live Redis.
    """

    def __init__(self):
        self._v = {}          # key -> value
        self._exp = {}        # key -> monotonic deadline

    def _live(self, key):
        exp = self._exp.get(key)
        if exp is not None and asyncio.get_event_loop().time() >= exp:
            self._v.pop(key, None)
            self._exp.pop(key, None)
            return False
        return key in self._v

    async def ping(self):
        return True

    async def set(self, key, value, nx=False, ex=None):
        if nx and self._live(key):
            return None
        self._v[key] = value
        if ex:
            self._exp[key] = asyncio.get_event_loop().time() + ex
        return True

    async def get(self, key):
        return self._v.get(key) if self._live(key) else None

    async def expire(self, key, ttl):
        if not self._live(key):
            return 0
        self._exp[key] = asyncio.get_event_loop().time() + ttl
        return 1

    async def eval(self, script, numkeys, *args):
        key, worker_id = args[0], args[1]
        ttl = int(args[2]) if len(args) > 2 else leader.LOCK_TTL
        if self._live(key) and self._v.get(key) == worker_id:
            self._exp[key] = asyncio.get_event_loop().time() + ttl
            return 1
        return 0


class Tracker:
    """Counts how many workers are inside the guarded section at once."""

    def __init__(self):
        self.now = 0
        self.peak = 0
        self.entries = 0

    async def work(self):
        self.now += 1
        self.entries += 1
        self.peak = max(self.peak, self.now)
        try:
            await asyncio.sleep(WORK_SECONDS)
        finally:
            self.now -= 1


def _fresh_leader(idx: int, fake: "FakeRedis"):
    """A private copy of leader.py per worker.

    WORKER_ID (and the connection globals) are MODULE-level. In prod each uvicorn
    worker is a separate PROCESS, so each has its own copy. Rebinding one shared
    module's WORKER_ID from 8 coroutines instead makes the workers stomp on each
    other's identity and every renewal fails — which looks exactly like the bug
    and is purely a harness artifact. Load the module N times so each worker gets
    genuinely independent globals, while sharing the one FakeRedis.
    """
    spec = importlib.util.spec_from_file_location(f"_leader_w{idx}", LEADER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.LOCK_TTL = leader.LOCK_TTL
    mod.RENEW_INTERVAL = leader.RENEW_INTERVAL
    mod.WORKER_ID = f"es-worker-{idx}"

    async def _fake_get_redis():
        return fake

    mod.get_redis = _fake_get_redis
    return mod


async def _run(use_hold: bool) -> Tracker:
    """Drive N_WORKERS each ticking every TICK_SECONDS, like the real loop."""
    fake = FakeRedis()
    tracker = Tracker()
    task_name = "eventstore_events_by_type_refresh"
    mods = [_fresh_leader(i, fake) for i in range(N_WORKERS)]

    async def worker(mod):
        for _ in range(N_TICKS):
            if use_hold:
                async with mod.hold_leadership(task_name) as is_leader:
                    if is_leader:
                        await tracker.work()
            else:
                # The OLD code path, verbatim in shape.
                if await mod.try_acquire_leadership(task_name):
                    await tracker.work()
            await asyncio.sleep(TICK_SECONDS)

    await asyncio.gather(*(worker(m) for m in mods))
    return tracker


async def main() -> int:
    print(f"config: TTL={leader.LOCK_TTL}s renew={leader.RENEW_INTERVAL}s "
          f"work={WORK_SECONDS}s tick={TICK_SECONDS}s workers={N_WORKERS}\n")

    old = await _run(use_hold=False)
    print(f"OLD try_acquire_leadership : peak_concurrent={old.peak}  entries={old.entries}")

    new = await _run(use_hold=True)
    print(f"NEW hold_leadership        : peak_concurrent={new.peak}  entries={new.entries}\n")

    ok = True
    # NEGATIVE CONTROL: the harness must actually reproduce the bug.
    if old.peak < 2:
        print(f"FAIL: harness did not reproduce the overlap (old peak={old.peak}). "
              f"Test proves nothing — do NOT trust the NEW result.")
        ok = False
    else:
        print(f"PASS: negative control — old code overlapped at {old.peak} concurrent")

    if new.peak != 1:
        print(f"FAIL: hold_leadership allowed {new.peak} concurrent (expected exactly 1)")
        ok = False
    else:
        print("PASS: hold_leadership held the lock — never more than 1 concurrent")

    if new.entries < 1:
        print("FAIL: hold_leadership never ran the work at all (over-corrected)")
        ok = False
    else:
        print(f"PASS: work still ran under hold_leadership ({new.entries} executions)")

    print("\n" + ("ALL PASS" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
