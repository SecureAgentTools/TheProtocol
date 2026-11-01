"""V0652 (q) (order gwo_1939f34c31a297ffdd56c51c, agentvault2-14, 2026-11-01): a hosted message leaves for the other
registry about a second after it is queued, not at the outbox's next cycle.

The nightly nt261101 (00:48-00:56Z): federation_chat/chat_g1_block_is_silent_on_both_legs failed its leg
control_n_to_w_reaches_ws_owner, "heard late, after the window" (45 s): the host's message reached the other registry's
owner hook, late. The host's log has the outbox cycles at 00:48:53, 00:49:33 and 00:50:13, 40 s apart (the 20 s sleep
plus a drain under the suite's load), so a message queued just after a cycle waited up to 40 s before it left. Between
cycles the leader now probes for a due row every DUE_POLL_SECONDS and drains at once; the others keep sleeping; still
one writer. Measured here on the real loop with a short cycle: a row that becomes due mid-rest is drained within the
probe interval. BASE (V0650/V0651): the loop sleeps the whole cycle; the first case fails there (one drain, not two).
"""
from __future__ import annotations

import asyncio
import contextlib

import pytest

from agentvault_registry.background_tasks import chat_federation_outbox as ob
from agentvault_registry.background_tasks import leader, vitals
from agentvault_registry.services import chat_federation as fed


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def loop_env(monkeypatch):
    state = {"drains": 0, "probes": 0, "due": [], "led": True}

    async def _lead(name):
        return state["led"]

    async def _drain():
        state["drains"] += 1
        if state.get("drain_raises"):
            raise RuntimeError("database gone")

    async def _register(*a, **k):
        return None

    @contextlib.asynccontextmanager
    async def _cycle(name):
        yield

    async def _due():
        state["probes"] += 1
        nxt = state["due"].pop(0) if state["due"] else False
        if isinstance(nxt, Exception):
            raise nxt
        return nxt
    monkeypatch.setattr(fed, "federation_enabled", lambda: True)
    monkeypatch.setattr(leader, "try_acquire_leadership", _lead)
    monkeypatch.setattr(vitals, "register", _register)
    monkeypatch.setattr(vitals, "cycle", _cycle)
    monkeypatch.setattr(ob, "_drain_once", _drain)
    monkeypatch.setattr(ob, "_due_rows", _due, raising=False)          # raising=False: the base has no probe
    monkeypatch.setattr(ob, "CYCLE_SECONDS", 5)
    monkeypatch.setattr(ob, "DUE_POLL_SECONDS", 0.05, raising=False)
    return state


async def _run_for(seconds: float):
    task = asyncio.create_task(ob.chat_federation_outbox_loop())
    await asyncio.sleep(seconds)
    ob.stop_chat_federation_outbox()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def test_a_row_due_mid_rest_is_drained_within_the_probe_not_the_cycle(loop_env):
    loop_env["due"] = [False, False, True]          # a message queued about 0.15 s after the first drain
    run(_run_for(0.6))
    assert loop_env["drains"] == 2, loop_env         # BASE: 1 (the loop slept its whole 5 s cycle)


def test_nothing_due_keeps_the_ordinary_cycle(loop_env):
    run(_run_for(0.6))
    assert loop_env["drains"] == 1 and loop_env["probes"] >= 5      # probing, never draining for nothing


def test_a_worker_that_is_not_the_leader_neither_probes_nor_drains(loop_env):
    loop_env["led"] = False
    run(_run_for(0.4))
    assert loop_env["drains"] == 0 and loop_env["probes"] == 0


def test_a_failing_probe_costs_the_ordinary_wait_not_a_tight_loop(loop_env):
    loop_env["due"] = [RuntimeError("db down")] * 50
    run(_run_for(0.6))
    assert loop_env["drains"] == 1 and loop_env["probes"] == 1


def test_a_cycle_that_raised_waits_the_whole_cycle_even_with_a_row_due(loop_env):
    loop_env["drain_raises"] = True
    loop_env["due"] = [True] * 50
    run(_run_for(0.6))
    assert loop_env["drains"] == 1 and loop_env["probes"] == 0      # one error line a cycle, never one a second
