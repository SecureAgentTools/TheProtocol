"""§REPATLANE-8 (V0610, 2026-10-13) — the sweeper of the durable Idempotency-Key records (idempotency_kept, migration 0191).

services/idempotency/durable.py keeps each key's record for IDEMPOTENCY_TTL_SECONDS (24 h, as Redis does) and every read
already ignores a record past its expiry; this worker deletes those rows so the table holds about one day of keys.
Leader-elected through `_worker_base.BackgroundWorker`; each cycle deletes in batches until no expired row is left or its
batch budget is spent (the next cycle takes the rest).

Env: IDEMPOTENCY_KEPT_SWEEP_ENABLED (default true), IDEMPOTENCY_KEPT_SWEEP_INTERVAL_SEC (900),
IDEMPOTENCY_KEPT_SWEEP_BATCH (5000), IDEMPOTENCY_KEPT_SWEEP_BATCHES (20).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from ._worker_base import BackgroundWorker

logger = logging.getLogger(__name__)


def sweep_enabled() -> bool:
    return (os.getenv("IDEMPOTENCY_KEPT_SWEEP_ENABLED") or "true").strip().lower() == "true"


class IdempotencyKeptSweeper(BackgroundWorker):
    worker_id = "idempotency_kept_sweeper"
    leader_key = "idempotency_kept_sweeper"
    interval_sec = int(os.getenv("IDEMPOTENCY_KEPT_SWEEP_INTERVAL_SEC", "900") or 900)
    cold_start_delay_sec = 60

    def __init__(self) -> None:
        super().__init__()
        self.batch = int(os.getenv("IDEMPOTENCY_KEPT_SWEEP_BATCH", "5000") or 5000)
        self.batches = int(os.getenv("IDEMPOTENCY_KEPT_SWEEP_BATCHES", "20") or 20)
        self._stats: Dict[str, Any] = {}

    def _should_run(self) -> bool:
        return sweep_enabled()

    async def _cycle_once(self) -> None:
        from agentvault_registry.services.idempotency import durable
        gone = 0
        for _ in range(self.batches):
            n = await durable.sweep(self.batch)
            gone += n
            if n < self.batch:
                break
        if gone:
            durable.count("sweep", "deleted")
            logger.info("[idempotency-kept-sweeper] deleted %d expired Idempotency-Key record(s)", gone)
        self._stats = {"deleted_this_cycle": gone}

    def _last_stats(self) -> Dict[str, Any]:
        return dict(self._stats or {})


_worker: "IdempotencyKeptSweeper | None" = None


def get_idempotency_kept_sweeper() -> IdempotencyKeptSweeper:
    global _worker
    if _worker is None:
        _worker = IdempotencyKeptSweeper()
    return _worker
