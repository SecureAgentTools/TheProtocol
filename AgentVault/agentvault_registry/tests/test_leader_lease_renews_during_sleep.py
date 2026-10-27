"""§LEASE: the leader lease must survive the loop's own sleep.

Measured on ASIA 2026-09-18 (V0396, 20.78 h): `peer_revival_prober` declares 120 s and acquired the lease 2,203
times, one per 34 s, and `federation_card_gc` declares 24 h and acquired 6 times. `run_with_leadership` renewed the
lease once after the cycle and then slept the whole interval with nothing renewing, so the lease lapsed at LOCK_TTL
and a non-leader poller (LEADER_CHECK_INTERVAL) took the task early.

What one process can pin is the MECHANISM: no single sleep may outlast the renewal interval, and the lease is renewed
while the loop sleeps. The cadence collapse itself is a property of several workers and is measured live, by
worker_leader_acquisitions_total{outcome="acquired"} per task, not here.
"""
import pytest

from agentvault_registry.background_tasks import leader as L
from agentvault_registry.background_tasks import vitals as V


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def harness(monkeypatch):
    clock = _Clock()
    state = {"acquired": 0, "renewed": 0, "renew_ok": True, "sleeps": []}

    async def fake_sleep(sec):
        state["sleeps"].append(sec)
        clock.t += sec

    async def fake_acquire(task_name):
        state["acquired"] += 1
        return True

    async def fake_renew(task_name):
        state["renewed"] += 1
        return state["renew_ok"]

    async def fake_stamp(*a, **k):
        return None

    async def fake_redis():
        return None

    monkeypatch.setattr(L.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(L, "_monotonic", clock)
    monkeypatch.setattr(L, "_spread", lambda x: x)
    monkeypatch.setattr(L, "try_acquire_leadership", fake_acquire)
    monkeypatch.setattr(L, "renew_leadership", fake_renew)
    monkeypatch.setattr(L, "get_redis", fake_redis)
    monkeypatch.setattr(V, "stamp", fake_stamp)
    return clock, state


@pytest.mark.asyncio
async def test_the_lease_is_renewed_while_the_loop_sleeps(harness):
    clock, state = harness
    gen = L.run_with_leadership("lease_probe", interval=120)
    await gen.__anext__()
    t_after_first = clock.t
    renewed_after_first = state["renewed"]
    await gen.__anext__()
    await gen.aclose()

    slept = clock.t - t_after_first
    assert 119 <= slept <= 121, f"the loop waited {slept}s between cycles, want the declared 120s"
    assert max(state["sleeps"]) <= L.RENEW_INTERVAL, (
        f"one sleep of {max(state['sleeps'])}s outlasts the {L.LOCK_TTL}s lease "
        f"(renewal interval {L.RENEW_INTERVAL}s): the lease lapses and a poller takes the task early"
    )
    during_sleep = state["renewed"] - renewed_after_first
    want = 120 // L.RENEW_INTERVAL - 1
    assert during_sleep >= want, f"the lease was renewed {during_sleep} times across a 120s sleep, want at least {want}"


@pytest.mark.asyncio
async def test_a_lease_lost_while_sleeping_returns_to_acquiring_without_waiting_out_the_interval(harness):
    """The guard on the fix, not a red control: failover must not get slower."""
    clock, state = harness
    gen = L.run_with_leadership("lease_probe", interval=120)
    await gen.__anext__()
    state["renew_ok"] = False
    t0 = clock.t
    await gen.__anext__()
    await gen.aclose()
    waited = clock.t - t0
    assert waited <= L.LOCK_TTL + L.LEADER_CHECK_INTERVAL, (
        f"after losing the lease the loop waited {waited}s before running again, want at most "
        f"{L.LOCK_TTL + L.LEADER_CHECK_INTERVAL}s"
    )
