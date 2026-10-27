"""
Algorithmic Auditor Background Worker

This module implements the background task that periodically runs
auditor rules to detect and flag suspicious economic behavior.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

from ..database import get_db
from ..core import auditor_rules
from ..config import settings

logger = logging.getLogger(__name__)


class AuditorWorker:
    """
    Background worker for the Algorithmic Auditor system.
    
    This worker periodically executes audit rules to monitor
    agent behavior and flag suspicious activities.
    """
    
    def __init__(self, interval_seconds: int = 600):  # Default 10 minutes
        """
        Initialize the auditor worker.
        
        Args:
            interval_seconds: Time between audit runs (default: 600 seconds / 10 minutes)
        """
        self.interval_seconds = interval_seconds
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        
    async def _run_audit_cycle(self):
        """Execute one cycle of audit rules."""
        try:
            logger.info("Starting auditor cycle...")
            
            async for db in get_db():
                try:
                    results = await auditor_rules.run_all_auditor_rules(db)
                    logger.info(f"Auditor cycle completed: {results}")
                except Exception as e:
                    # Not a per-item failure — `run_all_auditor_rules` IS this cycle's
                    # single unit of work, so its failure is the cycle's failure.
                    logger.error(f"Error during audit cycle: {str(e)}")
                    raise
                finally:
                    await db.close()
                    
        except Exception as e:
            # §VITALS: re-raised so the cycle stamps `error`. `run_single_audit()` is
            # the only other caller and nothing calls it.
            logger.error(f"Fatal error in audit cycle: {str(e)}")
            raise
    
    async def run_audits(self):
        """
        Main loop for the auditor worker.
        
        This function runs continuously, executing audit rules
        at the configured interval.
        """
        self.is_running = True
        logger.info(
            f"Auditor worker started. Running audits every {self.interval_seconds} seconds"
        )
        
        from .leader import try_acquire_leadership
        from . import vitals as _vitals
        await _vitals.register("auditor_worker", module=__name__, pattern="hand-rolled",
                               interval_sec=self.interval_seconds, enabled=True)
        while self.is_running:
            try:
                if not await try_acquire_leadership("auditor_worker"):
                    await asyncio.sleep(self.interval_seconds)
                    continue
                # Run the audit cycle. An EMPTY rule set is the correct steady state
                # (core/auditor_rules.py is a deliberately empty registration point),
                # so the stamp records the fact rather than judging it.
                async with _vitals.cycle("auditor_worker") as _ctx:
                    await self._run_audit_cycle()
                    _ctx.note(rules="see core/auditor_rules.py")

                # Wait for the next cycle
                await asyncio.sleep(self.interval_seconds)

            except asyncio.CancelledError:
                logger.info("Auditor worker cancelled")
                break
            except Exception as e:
                logger.error(f"Unexpected error in auditor worker: {str(e)}")
                # Continue running after unexpected errors
                await asyncio.sleep(self.interval_seconds)
        
        logger.info("Auditor worker stopped")
    
    def start(self):
        """Start the auditor worker as a background task."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run_audits())
            logger.info("Auditor worker task created")
        else:
            logger.warning("Auditor worker already running")
    
    def stop(self):
        """Stop the auditor worker."""
        self.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("Auditor worker stop requested")


# Global worker instance
auditor_worker = AuditorWorker(interval_seconds=600)  # 10 minutes default


async def run_audits():
    """
    Entry point for the auditor background task.
    
    This function is called by the main application startup
    to begin monitoring agent behavior.
    """
    await auditor_worker.run_audits()


async def run_single_audit():
    """
    Run a single audit cycle immediately.
    
    Useful for testing or manual triggering of audits.
    """
    worker = AuditorWorker()
    await worker._run_audit_cycle()
