"""§MCPTEST30 (V0525, 2026-10-01) — the read-only probes ask their targets a few at a time (api_tests/contracts/
probe_pool.py). Round 8's complete flow took 18+ minutes with every probe call one after another."""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.api_tests.contracts import probe_pool as PP


def test_never_more_than_the_limit_at_once_and_every_item_runs():
    seen, live, peak = [], [0], [0]

    async def fn(i):
        live[0] += 1
        peak[0] = max(peak[0], live[0])
        await asyncio.sleep(0.01)
        seen.append(i)
        live[0] -= 1
    asyncio.run(PP.each(range(20), fn))
    assert sorted(seen) == list(range(20))
    assert peak[0] == PP.PROBE_CONCURRENCY == 2   # V0527: 4 -> 2 (round 9 saturated sbx-alpha-db)


def test_one_failure_lets_the_others_finish_then_raises():
    done = []

    async def fn(i):
        await asyncio.sleep(0.005 * i)
        if i == 2:
            raise ValueError("boom")
        done.append(i)
    with pytest.raises(ValueError):
        asyncio.run(PP.each(range(8), fn))
    assert sorted(done) == [0, 1, 3, 4, 5, 6, 7], "nothing is left half-run"


def test_a_limit_of_one_is_the_old_sequential_order():
    order = []

    async def fn(i):
        await asyncio.sleep(0.001 * (5 - i))
        order.append(i)
    asyncio.run(PP.each(range(5), fn, limit=1))
    assert order == [0, 1, 2, 3, 4]
