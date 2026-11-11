"""V0658 (p): a restart must not re-act on events it already handled.

MEASURED ON PRODUCTION, 2026-11-07. EU's V0657 recreate at 18:55:15Z had its
reactors act again on history: AgentSuspended dispatched 390 times inside 17 s
(re-running the cross-frame block fanout to 5 peers), AgentReinstated 78,
ProposalTallied 130, PeerUrlSelfHeal 286, and PushNotify:AgentSpawned 52 — the
last of those re-notifying the maintainer's devices about spawns from
23 September. ASIA repeated it at 18:58:17Z. Nothing new happened, but a fanout's
final state depends on replay order and a push for a September event is noise.

WHY IT HAPPENS, and it is not a missing mechanism. `reactor_base` already keeps a
durable seen-id set and a durable polling cursor, written for EVERY reactor. Both
EXPIRE: the seen set after 24 h, the cursor after 7 days. So the guard holds for a
BUSY reactor, which rewrites its key constantly, and expires for a RARE one — and
the rare ones are the ones whose side effects reach other frames and other people.
The guard was strongest exactly where the harm was smallest.

WHAT THESE TESTS PIN, in session-lead's order (room seq 2161, 2167):
  - neither durable key carries an expiry;
  - a restart after a long quiet period still warms and dispatches NOTHING;
  - a replay arriving TWICE dispatches nothing either time;
  - the guard's window is per reactor, not one shared number;
  - an opt-out must NAME ITS REASON, so "this reactor must see every delivery" is
    a recorded decision rather than an omission;
  - a stale-age fallback still refuses an ancient event when the ring is empty;
  - and each replaying reconnect LOGS the worker, the replay size and how many of
    those ids were already handled — so the next restart explains the 390 from the
    log instead of from anybody's theory.

They assert ZERO side effects for ANY N rather than for 390: once the ids are
durable and unexpiring, whatever multiplies the replay stops mattering, and the
multiplier is still open (the 300 s polling lookback and a 4-worker gunicorn both
fail to explain 26x the 15-event window).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import List, Optional

import pytest

from agentvault_registry.background_tasks import reactor_base
from agentvault_registry.background_tasks.reactor_base import EventStoreReactor


# ---------------------------------------------------------------------------- helpers

@pytest.fixture(autouse=True)
def _reset_leader_keys():
    reactor_base._registered_leader_keys.clear()
    yield
    reactor_base._registered_leader_keys.clear()


def _evt(event_id: str, etype: str = "TestEvent", data: Optional[dict] = None) -> str:
    return json.dumps({
        "type": "event",
        "event": {"event_type": etype, "event_id": event_id, "data": data or {"k": "v"}},
    })


class _Redis:
    """A Redis shim that remembers EXPIRIES, because the absence of one is the fix.

    The suite's existing shim knows only hashes and strings, so the durable seen-set
    writes landed in `_record_last_event`'s own except-and-log and no test ever saw
    them. Sorted-set ops and `expire`/`ttl` are here so a test can assert that no
    expiry was set at all.
    """

    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}
        self.strings: dict[str, str] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.expiries: dict[str, int] = {}          # key -> seconds, when one is set
        self.set_kwargs: list[tuple] = []

    async def hincrby(self, key, field, amount=1):
        h = self.hashes.setdefault(key, {})
        h[field] = str(int(h.get(field, "0")) + amount)
        return int(h[field])

    async def hset(self, key, *args, mapping=None, **kw):
        h = self.hashes.setdefault(key, {})
        if mapping:
            for k, v in mapping.items():
                h[k] = str(v)
        if len(args) >= 2 and not mapping:
            h[args[0]] = str(args[1])
        return 1

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def set(self, key, value, **kwargs):
        self.strings[key] = str(value)
        self.set_kwargs.append((key, kwargs))
        if "ex" in kwargs and kwargs["ex"]:
            self.expiries[key] = int(kwargs["ex"])
        return True

    async def get(self, key):
        return self.strings.get(key)

    async def zadd(self, key, mapping):
        z = self.zsets.setdefault(key, {})
        z.update({str(m): float(s) for m, s in mapping.items()})
        return len(mapping)

    async def zremrangebyrank(self, key, start, stop):
        z = self.zsets.get(key) or {}
        ordered = sorted(z.items(), key=lambda kv: kv[1])
        # emulate Redis: negative stop counts from the end
        n = len(ordered)
        s = start if start >= 0 else n + start
        e = stop if stop >= 0 else n + stop
        for m, _ in ordered[max(0, s):e + 1]:
            z.pop(m, None)
        return 1

    async def zrevrange(self, key, start, stop):
        z = self.zsets.get(key) or {}
        ordered = [m for m, _ in sorted(z.items(), key=lambda kv: kv[1], reverse=True)]
        return ordered[start:(stop + 1 if stop >= 0 else None)]

    async def zcard(self, key):
        return len(self.zsets.get(key) or {})

    async def expire(self, key, seconds):
        self.expiries[key] = int(seconds)
        return True

    async def ttl(self, key):
        return self.expiries.get(key, -1)

    def advance(self, seconds: int) -> list:
        """Let time pass, and drop every key whose expiry has elapsed.

        ⚠ THIS IS WHAT MAKES THE ACCEPTANCE TEST ABLE TO FAIL. Written without it,
        the restart tests below PASSED ON THE UNFIXED CODE: the real defect is a
        24-hour expiry, and a shim that never expires anything models a Redis in
        which the defect does not exist. A test that cannot fail measures nothing,
        so the quiet period is simulated here rather than assumed away.
        """
        dropped = []
        for key, ttl in list(self.expiries.items()):
            if ttl <= seconds:
                self.zsets.pop(key, None)
                self.strings.pop(key, None)
                self.expiries.pop(key, None)
                dropped.append(key)
        return dropped

    def pipeline(self, transaction: bool = True):
        return _Pipe(self)


class _Pipe:
    def __init__(self, parent: _Redis):
        self.parent = parent
        self.queued: list = []

    def hincrby(self, key, field, amount=1):
        self.queued.append(("hincrby", key, field, amount)); return self

    def hset(self, key, *args, mapping=None):
        self.queued.append(("hset", key, args, mapping)); return self

    def get(self, key):
        self.queued.append(("get", key)); return self

    def hgetall(self, key):
        self.queued.append(("hgetall", key)); return self

    async def execute(self):
        out = []
        for op in self.queued:
            if op[0] == "hincrby":
                out.append(await self.parent.hincrby(op[1], op[2], op[3]))
            elif op[0] == "hset":
                out.append(await self.parent.hset(op[1], *op[2], mapping=op[3]))
            elif op[0] == "get":
                out.append(await self.parent.get(op[1]))
            elif op[0] == "hgetall":
                out.append(await self.parent.hgetall(op[1]))
        self.queued.clear()
        return out

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.fixture
def redis(monkeypatch):
    r = _Redis()

    async def _get_redis():
        return r

    monkeypatch.setattr(reactor_base, "get_redis", _get_redis)
    monkeypatch.setenv("REGISTRY_NAME", "registry-test")
    return r


def _restart() -> None:
    """What a process restart does to the leader_key registry: empties it.

    `EventStoreReactor.__init__` refuses a duplicate leader_key, and rightly so —
    two reactors claiming one key in one process is a bug. That registry is
    PER-PROCESS, so a restart starts empty, and a test that simulates a restart has
    to say so rather than reuse a live registration.
    """
    reactor_base._registered_leader_keys.clear()


def _reactor(leader_key: str, captured: Optional[List[dict]] = None, **attrs):
    """A one-off concrete subclass. `serial` dispatch so a test can assert
    immediately after `_on_event` instead of racing a background task."""
    seen: List[dict] = captured if captured is not None else []

    class _R(EventStoreReactor):
        async def handle_event(self, event_data: dict) -> None:
            seen.append(event_data)

    _R.event_type = attrs.pop("event_type", "TestEvent")
    _R.leader_key = leader_key
    _R.name = attrs.pop("name", "Test")
    _R.dispatch_mode = "serial"
    for k, v in attrs.items():
        setattr(_R, k, v)
    return _R(), seen


# ---------------------------------------------------------------------------- the two expiries

@pytest.mark.asyncio
async def test_red_the_seen_set_is_written_without_an_expiry(redis):
    """The 24-hour expiry is the defect: it removes the guard from any reactor
    quiet for a day, which is every rare, high-consequence one."""
    r, _ = _reactor("reactor_p_seen_noexpiry")

    await r._on_event(_evt("p-1"))

    seen_key = r._redis_seen_key
    assert redis.zsets.get(seen_key), "the id was not persisted at all"
    assert seen_key not in redis.expiries, (
        f"the seen set carries an expiry of {redis.expiries.get(seen_key)}s; a guard "
        "that expires is no guard for a reactor that fires rarely"
    )


@pytest.mark.asyncio
async def test_red_the_cursor_is_written_without_an_expiry(redis):
    """The cursor's 7-day expiry has the same shape: when it goes, the polling
    backstop falls back to its lookback and re-fetches."""
    from datetime import datetime, timezone

    r, _ = _reactor("reactor_p_cursor_noexpiry")
    await r._save_cursor_to_redis(datetime.now(timezone.utc))

    key = r._redis_cursor_key
    assert redis.strings.get(key), "the cursor was not persisted"
    assert key not in redis.expiries, (
        f"the cursor carries an expiry of {redis.expiries.get(key)}s"
    )


# ---------------------------------------------------------------------------- a restart replays nothing

@pytest.mark.asyncio
async def test_red_a_restart_after_a_long_quiet_period_dispatches_nothing(redis):
    """THE ACCEPTANCE TEST. A reactor handles N events, the process dies, and a
    NEW instance (the restart) is handed the same N by the stream. Zero side
    effects, for any N — this is the property, not the number 390."""
    first, dispatched_a = _reactor("reactor_p_restart")
    ids = [f"p-restart-{i}" for i in range(12)]
    for eid in ids:
        await first._on_event(_evt(eid))
    assert len(dispatched_a) == 12                      # the genuine deliveries

    # THE QUIET PERIOD, which is the whole defect: this reactor sees nothing for a
    # week, and anything with an expiry shorter than that is gone when it restarts.
    dropped = redis.advance(7 * 24 * 3600)
    assert dropped == [], (
        f"these keys expired over a quiet week and will not be there to guard the "
        f"restart: {dropped}"
    )

    # the restart: a new process, so an empty registry and an empty in-memory ring,
    # with the same Redis behind it
    _restart()
    second, dispatched_b = _reactor("reactor_p_restart")
    assert second._seen_event_ids == {}
    await second._warm_dedup_from_redis()
    for eid in ids:
        await second._on_event(_evt(eid))

    assert dispatched_b == [], (
        f"the restart re-acted on {len(dispatched_b)} already-handled events"
    )
    # THE CONTROL: a genuinely new event after the replay is still handled, once.
    await second._on_event(_evt("p-restart-new"))
    assert len(dispatched_b) == 1


@pytest.mark.asyncio
async def test_red_a_replay_arriving_twice_dispatches_nothing_either_time(redis):
    """session-lead's ask: 390 is 26x the 15-event window, so something replayed
    many times over. Whatever it is, the second arrival must be as quiet as the
    first."""
    first, _ = _reactor("reactor_p_twice")
    for eid in ("p-t-1", "p-t-2", "p-t-3"):
        await first._on_event(_evt(eid))

    redis.advance(7 * 24 * 3600)        # a quiet week, as above
    _restart()
    second, dispatched = _reactor("reactor_p_twice")
    await second._warm_dedup_from_redis()
    for _round in range(2):
        for eid in ("p-t-1", "p-t-2", "p-t-3"):
            await second._on_event(_evt(eid))

    assert dispatched == []


# ---------------------------------------------------------------------------- per-reactor window

@pytest.mark.asyncio
async def test_red_the_dedup_window_is_per_reactor(redis):
    """One shared 256 is wrong in both directions: too small for a reactor whose
    replay is large, pointless for one that sees an event a month."""
    r, dispatched = _reactor("reactor_p_window", dedup_ring_cap=4)
    assert r.dedup_ring_cap == 4

    for i in range(6):
        await r._on_event(_evt(f"p-w-{i}"))
    assert len(r._seen_event_ids) == 4, "the ring did not honour the reactor's own cap"
    # the oldest two were evicted, so they are no longer deduped
    assert "p-w-0" not in r._seen_event_ids
    assert "p-w-5" in r._seen_event_ids


# ---------------------------------------------------------------------------- the opt-out names its reason

def test_red_an_opt_out_must_name_its_reason():
    """A reactor that must see every delivery is a decision. Without a reason it
    is indistinguishable from someone forgetting the guard."""
    with pytest.raises(ValueError, match="dedup_disabled_reason"):
        _reactor("reactor_p_optout_bad", dedup_disabled=True)

    # with a reason it constructs, and the reason is readable
    r, _ = _reactor("reactor_p_optout_ok", dedup_disabled=True,
                    dedup_disabled_reason="counts every delivery, including replays")
    assert "every delivery" in r.dedup_disabled_reason


@pytest.mark.asyncio
async def test_red_an_opt_out_reactor_really_sees_the_replay(redis):
    """The control on the opt-out: it must actually turn the guard off, or the
    named reason is a comment on behaviour that does not exist."""
    r, dispatched = _reactor("reactor_p_optout_live", dedup_disabled=True,
                             dedup_disabled_reason="sees every delivery on purpose")
    await r._on_event(_evt("p-o-1"))
    await r._on_event(_evt("p-o-1"))
    assert len(dispatched) == 2


# ---------------------------------------------------------------------------- the stale-age fallback

@pytest.mark.asyncio
async def test_red_an_ancient_event_is_refused_even_with_an_empty_ring(redis):
    """The fallback for the day Redis itself is wiped: an event far older than the
    guard's horizon is a replay whatever the ring says."""
    from datetime import datetime, timedelta, timezone

    r, dispatched = _reactor("reactor_p_stale")
    # Production ALWAYS warms at startup, and the fallback deliberately acts only
    # after a warm came back empty — "we asked Redis and it had nothing" is a
    # different state from "we have not asked", and only the first licenses
    # treating an absent id as a replay. A test that skipped the warm was asking
    # the guard to act in a state the process never occupies; loosening the guard
    # to satisfy it would have made a fresh reactor silently drop genuine old work.
    await r._warm_dedup_from_redis()
    assert r._dedup_warmed_empty is True

    old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    msg = json.dumps({
        "type": "event",
        "event": {"event_type": "TestEvent", "event_id": "p-ancient",
                  "timestamp": old, "data": {}},
    })

    await r._on_event(msg)
    assert dispatched == [], "a 45-day-old event was dispatched from an empty ring"

    # THE CONTROL: a fresh event with a timestamp is still handled.
    fresh = json.dumps({
        "type": "event",
        "event": {"event_type": "TestEvent", "event_id": "p-fresh",
                  "timestamp": datetime.now(timezone.utc).isoformat(), "data": {}},
    })
    await r._on_event(fresh)
    assert len(dispatched) == 1


# ---------------------------------------------------------------------------- the line that answers the 390

@pytest.mark.asyncio
async def test_red_a_replaying_reconnect_logs_worker_size_and_how_many_were_known(redis, caplog):
    """session-lead, seq 2167: instrument it rather than theorise. The next
    restart then says who replayed, how much, and how much of it was already
    handled — which is what the open 26x question needs."""
    first, _ = _reactor("reactor_p_log")
    for eid in ("p-l-1", "p-l-2"):
        await first._on_event(_evt(eid))

    _restart()
    second, _ = _reactor("reactor_p_log")
    await second._warm_dedup_from_redis()
    caplog.clear()
    with caplog.at_level(logging.INFO):
        await second.note_replay_window(["p-l-1", "p-l-2", "p-l-3"])

    line = "\n".join(m for m in caplog.messages if "replay" in m.lower())
    assert line, "a replaying reconnect logged nothing"
    assert "3" in line, "the replay size is not in the line"
    assert "2" in line, "how many were already handled is not in the line"
    assert "worker" in line.lower(), "the worker is not named"
