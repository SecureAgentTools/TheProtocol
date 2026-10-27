"""
EigenTrust++ background worker — Phase 2

Periodic task: runs eigentrust_engine.run_epoch() every EIGENTRUST_EPOCH_HOURS.
Follows the same pattern as staking_distributor.py.

Registration in main.py startup_event:
    from agentvault_registry.background_tasks.eigentrust_worker import (
        start_eigentrust_worker, stop_eigentrust_worker
    )
    asyncio.create_task(start_eigentrust_worker())

And in shutdown_event:
    await stop_eigentrust_worker()
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..database import get_db_context
from ..services import eigentrust_engine

logger = logging.getLogger(__name__)

# Configurable epoch interval (default 1 hour; set EIGENTRUST_EPOCH_HOURS env var to override)
_EPOCH_HOURS = float(os.environ.get("EIGENTRUST_EPOCH_HOURS", "1"))
_EPOCH_SECONDS = _EPOCH_HOURS * 3600


class EigenTrustWorker:
    """Background task for periodic EigenTrust++ computation."""

    def __init__(self):
        self.running = False
        self.task: Optional[asyncio.Task] = None

    async def run_epoch_now(self) -> dict:
        """Execute a single epoch and store result."""
        async with get_db_context() as db:
            try:
                result = await eigentrust_engine.run_epoch(db)
                await eigentrust_engine.set_last_epoch_result(result)
                return result
            except Exception as e:
                logger.error(f"EigenTrust++ epoch failed: {e}", exc_info=True)
                return {"error": str(e)}

    async def run_forever(self):
        """Loop: sleep epoch_seconds then compute."""
        logger.info(
            f"EigenTrust++ worker started "
            f"(epoch every {_EPOCH_HOURS}h = {_EPOCH_SECONDS}s)"
        )
        self.running = True

        # Run first epoch shortly after startup (30s delay to let registry initialize)
        await asyncio.sleep(30)

        from .leader import try_acquire_leadership
        from . import vitals as _vitals
        await _vitals.register("eigentrust_worker", module=__name__, pattern="hand-rolled",
                               interval_sec=_EPOCH_SECONDS, enabled=True)
        while self.running:
            try:
                if not await try_acquire_leadership("eigentrust_worker"):
                    await asyncio.sleep(_EPOCH_SECONDS)
                    continue
                logger.info("EigenTrust++ epoch starting...")
                async with _vitals.cycle("eigentrust_worker") as _ctx:
                    result = await self.run_epoch_now()
                    _ctx.note(epoch=result.get("epoch"),
                              agents=result.get("agents_computed"),
                              converged=result.get("converged"))
                logger.info(
                    f"EigenTrust++ epoch done: "
                    f"epoch={result.get('epoch', '?')}, "
                    f"agents={result.get('agents_computed', '?')}, "
                    f"converged={result.get('converged', '?')}, "
                    f"{result.get('computation_time_ms', '?')}ms"
                )

                # Schedule next
                next_at = datetime.now(timezone.utc) + timedelta(seconds=_EPOCH_SECONDS)
                await eigentrust_engine.set_next_scheduled_at(next_at)

                await asyncio.sleep(_EPOCH_SECONDS)

            except asyncio.CancelledError:
                logger.info("EigenTrust++ worker cancelled")
                break
            except Exception as e:
                logger.error(
                    f"Unexpected error in EigenTrust++ worker: {e}",
                    exc_info=True,
                )
                # Wait 5 minutes before retrying on unexpected error
                await asyncio.sleep(300)

    async def start(self):
        """Start the background task."""
        if self.task and not self.task.done():
            logger.warning("EigenTrust++ worker already running")
            return
        self.task = asyncio.create_task(self.run_forever())
        logger.info("EigenTrust++ worker task created")

    async def stop(self):
        """Stop the background task."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        logger.info("EigenTrust++ worker stopped")


# Singleton
_worker: Optional[EigenTrustWorker] = None


def get_eigentrust_worker() -> EigenTrustWorker:
    global _worker
    if _worker is None:
        _worker = EigenTrustWorker()
    return _worker


async def start_eigentrust_worker():
    """Start the EigenTrust++ worker background task."""
    worker = get_eigentrust_worker()
    await worker.start()


async def stop_eigentrust_worker():
    """Stop the EigenTrust++ worker background task."""
    worker = get_eigentrust_worker()
    await worker.stop()


async def trigger_manual_epoch() -> dict:
    """Trigger an immediate epoch computation outside the normal schedule."""
    worker = get_eigentrust_worker()
    return await worker.run_epoch_now()
