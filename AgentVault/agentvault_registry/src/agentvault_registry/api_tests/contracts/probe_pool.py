"""§MCPTEST30 (V0525, 2026-10-01) — the read-only probes ask their targets a few at a time.

Round 8 (V0523 on sbx-alpha): the complete flow took 18+ minutes against round 7's 13, because the hostile-input probe
asks ~137 read tools three times each, one call after another (~1 call/s); type_confusion and value_range add ~300 more.
Every probe call is read only and the probes judge each target on its own answers, so a target never depends on
another: they can run side by side. V0525 ran four at a time; round 9 then saturated sbx-alpha-db (100 of 100 backends,
all idle in the registry's pools, which keep up to 40 per worker: database.pool_settings), so V0527 runs two.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Iterable, List

PROBE_CONCURRENCY = 2   # V0527: 4 -> 2. Round 9 (V0525) saturated sbx-alpha-db: the registry's pools keep up to 40 idle
                        # connections per worker, so every burst the tester adds stays parked (database.pool_settings)


async def each(items: Iterable[Any], fn: Callable[[Any], Awaitable[None]], limit: int = PROBE_CONCURRENCY) -> None:
    """Await fn(item) for every item, at most `limit` at once. Every item runs even when another raised; the first
    exception is raised after all of them finished (a sequential loop stopped at it; here nothing is left half-run)."""
    sem = asyncio.Semaphore(max(1, int(limit)))

    async def _one(item: Any) -> None:
        async with sem:
            await fn(item)
    results: List[Any] = await asyncio.gather(*(_one(it) for it in items), return_exceptions=True)
    for r in results:
        if isinstance(r, BaseException):
            raise r
