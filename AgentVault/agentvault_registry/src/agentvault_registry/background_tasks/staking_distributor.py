"""
Background task for automatic staking reward distribution.

This task runs daily to distribute staking rewards to all eligible agents.
"""
import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from ..database import get_db_context
from ..services.staking_rewards_service import get_staking_rewards_service

logger = logging.getLogger(__name__)


class StakingDistributor:
    """Background task for running daily staking distributions."""
    
    def __init__(self):
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self.service = get_staking_rewards_service()
        # Distribution time (UTC) - default to 00:00 UTC
        self.distribution_hour = 0
        self.distribution_minute = 0
    
    async def run_distribution(self) -> str:
        """Execute the daily distribution. Returns the outcome for §VITALS.

        'completed' | 'skipped' | 'failed:<reason>'. The manual trigger ignores the
        return value, so its behaviour is unchanged; the scheduler loop turns a
        non-success into an `error` stamp instead of a cycle that looks healthy.
        """
        # §BAFIN (2026-10-01): a registry with staking rewards switched off pays no staking reward at all.
        # 'skipped' is not a failure for §VITALS (only 'failed:*' is), and a skipped run never counts.
        from ..core.staking_gate import staking_rewards_enabled
        if not staking_rewards_enabled():
            logger.info("Distribution skipped: staking rewards are switched off on this registry (STAKING_ENABLED / STAKING_REWARDS_ENABLED)")
            return "skipped"

        logger.info("Starting daily staking reward distribution...")

        async with get_db_context() as db:
            try:
                result = await self.service.run_daily_distribution(
                    db=db,
                    initiated_by='system_scheduler'
                )

                outcome = "failed:unknown"
                if result['status'] == 'completed':
                    outcome = "completed"
                    logger.info(
                        f"Distribution completed successfully. "
                        f"Distributed {result['total_distributed']} tokens to "
                        f"{result['successful']} agents."
                    )
                elif result['status'] == 'skipped':
                    outcome = "skipped"
                    logger.info(f"Distribution skipped: {result['reason']}")
                else:
                    outcome = f"failed:{result.get('error', 'unknown')}"
                    logger.error(f"Distribution failed: {result.get('error', 'Unknown error')}")

                # Phase 2a — D-FED-10: Treasury bankruptcy tracking. Evaluated after every run;
                # §FEELOCK: the monitor re-derives the streak from the completed distributions,
                # so a skipped, failed or repeated run is context for its log line and can
                # never count (a skipped run used to count as a zero day).
                try:
                    from ..services.federation_compliance_monitor import (
                        get_federation_compliance_monitor,
                    )
                    monitor = get_federation_compliance_monitor()
                    await monitor.check_and_update_treasury_health(db=db, run_result=result)
                except Exception as treasury_exc:
                    # Treasury health check must never kill the distribution task
                    logger.error(
                        f"[StakingDistributor] Treasury health check failed "
                        f"(non-blocking): {treasury_exc}",
                        exc_info=True,
                    )

                return outcome

            except Exception as e:
                logger.error(f"Error in distribution task: {e}", exc_info=True)
                return f"failed:{type(e).__name__}: {e}"

    async def wait_until_next_distribution(self):
        """Calculate and wait until the next distribution time."""
        now = datetime.now(timezone.utc)
        
        # Calculate next distribution time
        next_run = now.replace(
            hour=self.distribution_hour,
            minute=self.distribution_minute,
            second=0,
            microsecond=0
        )
        
        # If we've already passed today's distribution time, schedule for tomorrow
        if next_run <= now:
            next_run += timedelta(days=1)
        
        # Calculate wait time
        wait_seconds = (next_run - now).total_seconds()
        
        logger.info(
            f"Next distribution scheduled for {next_run.isoformat()}. "
            f"Waiting {wait_seconds:.0f} seconds..."
        )
        
        await asyncio.sleep(wait_seconds)
    
    async def run_forever(self):
        """Run the distribution task forever."""
        from .leader import try_acquire_leadership, release_leadership
        from . import vitals as _vitals
        logger.info("Staking distributor started")
        self.running = True
        await _vitals.register(
            "staking_distributor", module=__name__, pattern="hand-rolled",
            interval_sec=86400, enabled=True,
        )

        while self.running:
            try:
                # Wait until next distribution time
                await self.wait_until_next_distribution()

                if not self.running:
                    break

                # Leader election: only one worker runs the distribution
                if not await try_acquire_leadership("staking_distributor"):
                    logger.debug("Staking distributor: not leader, skipping cycle")
                    continue

                # Run distribution
                async with _vitals.cycle("staking_distributor") as _ctx:
                    _outcome = await self.run_distribution()
                    _ctx.note(outcome=_outcome)
                    if _outcome and _outcome.startswith("failed"):
                        # The service reported failure without raising — exactly the
                        # shape no exception-based instrument can see.
                        _ctx.fail(_outcome)
                
            except asyncio.CancelledError:
                logger.info("Staking distributor cancelled")
                break
            except Exception as e:
                logger.error(f"Unexpected error in distributor loop: {e}", exc_info=True)
                # Wait 1 hour before retrying on unexpected error
                await asyncio.sleep(3600)
    
    async def start(self):
        """Start the background distributor task."""
        if self.task and not self.task.done():
            logger.warning("Staking distributor already running")
            return
        
        self.task = asyncio.create_task(self.run_forever())
        logger.info("Staking distributor task created")
    
    async def stop(self):
        """Stop the background distributor task."""
        self.running = False
        
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        
        logger.info("Staking distributor stopped")
    
    async def run_manual_distribution(self):
        """Trigger a manual distribution immediately."""
        logger.info("Manual distribution triggered")
        await self.run_distribution()


# Singleton instance
_distributor: Optional[StakingDistributor] = None


def get_staking_distributor() -> StakingDistributor:
    """Get singleton instance of staking distributor."""
    global _distributor
    if _distributor is None:
        _distributor = StakingDistributor()
    return _distributor


async def start_staking_distributor():
    """Start the staking distributor background task."""
    distributor = get_staking_distributor()
    await distributor.start()


async def stop_staking_distributor():
    """Stop the staking distributor background task."""
    distributor = get_staking_distributor()
    await distributor.stop()


async def trigger_manual_distribution():
    """Trigger a manual distribution immediately."""
    distributor = get_staking_distributor()
    await distributor.run_manual_distribution()
