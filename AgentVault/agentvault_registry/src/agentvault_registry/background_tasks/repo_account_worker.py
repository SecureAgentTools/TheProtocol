"""One leader drains `repo_account_ops`: the pause, restore and close legs of developers' repository accounts on the public code
host (V0667, order gwo_662c03447bcd627afa4a11e5; services/repo_accounts).

  * SINGLE WRITER: `try_acquire_leadership` acquires the lock (the read-only leader check never does, so it is not used here);
    the other workers sleep the cycle.
  * Only while REPO_ACCOUNTS_ENABLED: with the switch off nothing is linked, so nothing is queued and nothing is drained.
  * Each leg commits on its own (DbStore.commit per leg), so a failure halfway keeps what already landed; a failed leg waits its
    backoff and its developer's later legs wait for it.
  * OUTCOME, not only liveness (vitals): every drain is one `vitals.cycle`; a cycle that leaves a leg stuck (past MAX_ATTEMPTS)
    reports a failure, so a loop that turns while nothing lands never reads as healthy.
"""
from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

CYCLE_SECONDS = int(os.getenv("REPO_ACCOUNT_WORKER_INTERVAL", "30"))
_stop = False


async def _drain_once() -> tuple:
    from agentvault_registry.database import AsyncSessionLocal
    from agentvault_registry.services import repo_accounts
    async with AsyncSessionLocal() as db:
        flow = repo_accounts.RepoAccounts(repo_accounts.DbStore(db), repo_accounts.ForgejoClient())
        landed = await flow.drain_once()
        stuck = len(await flow.stuck_ops())
        return landed, stuck


async def repo_account_worker_loop():
    from agentvault_registry.services import repo_accounts
    from .leader import try_acquire_leadership
    from . import vitals as _vitals
    await _vitals.register("repo_account_worker", module=__name__, pattern="hand-rolled", interval_sec=CYCLE_SECONDS,
                           enabled=repo_accounts.enabled())
    await asyncio.sleep(15)
    while not _stop:
        try:
            if repo_accounts.enabled() and await try_acquire_leadership("repo_account_worker"):
                async with _vitals.cycle("repo_account_worker") as ctx:
                    landed, stuck = await _drain_once()
                    ctx.note(landed=landed, stuck=stuck)
                    if landed:
                        logger.info("[repo_account_worker] %d leg(s) landed", landed)
                    if stuck:
                        ctx.fail(f"{stuck} repository account leg(s) stuck past their tries: GET /api/v1/admin/repo-accounts/stuck")
        except Exception as exc:  # noqa: BLE001 - the loop must outlive one bad cycle (vitals.cycle stamped it an error)
            logger.error("[repo_account_worker] cycle failed: %s", exc)
        await asyncio.sleep(CYCLE_SECONDS)


def stop_repo_account_worker():
    global _stop
    _stop = True
