"""The developer passport's standing pull (V0667, order gwo_fb84e57318de0802725ab511, phase 4; services/code_passport).

On the registry that governs code only: for each contributor from another registry whose code host account is not closed, one leader
asks their home for a fresh card and applies its standing by the one rule (services/code_passport.standing_change). A git push needs no
act on the registry, so this pull is how a suspension or a deletion at home reaches the code host account (pause, close; a
reinstatement restores). The account's legs are drained by background_tasks/repo_account_worker as a member's are.

  * SINGLE WRITER: `try_acquire_leadership` acquires the lock; the other workers sleep the cycle.
  * Idle where this registry does not govern code (code_authority.is_governing()): one sleep per cycle.
  * OUTCOME (vitals): every pull is one `vitals.cycle`; a cycle where a contributor's home could not be read reports a failure, so a
    loop that turns while no standing arrives never reads as healthy.
"""
from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

CYCLE_SECONDS = int(os.getenv("CODE_PASSPORT_STANDING_INTERVAL", "900"))
_stop = False


async def _pull_once() -> tuple:
    from sqlalchemy import func, select
    from agentvault_registry import models
    from agentvault_registry.database import AsyncSessionLocal
    from agentvault_registry.services import code_passport
    async with AsyncSessionLocal() as db:
        C, A = models.CodeContributor, models.ContributorRepoAccount
        due = (await db.execute(select(func.count()).select_from(C).join(A, A.contributor_id == C.id)
                                .where(A.state != "closed", C.standing != "closed", C.agent_did.is_not(None)))).scalar() or 0
        read = await code_passport.pull_standing_once(db)
        return int(due), int(read)


async def code_passport_standing_loop():
    from agentvault_registry.services import code_authority
    from .leader import try_acquire_leadership
    from . import vitals as _vitals
    await _vitals.register("code_passport_standing", module=__name__, pattern="hand-rolled", interval_sec=CYCLE_SECONDS,
                           enabled=code_authority.is_governing())
    await asyncio.sleep(60)
    while not _stop:
        try:
            if code_authority.is_governing() and await try_acquire_leadership("code_passport_standing"):
                async with _vitals.cycle("code_passport_standing") as ctx:
                    due, read = await _pull_once()
                    ctx.note(due=due, read=read)
                    if read < due:
                        ctx.fail(f"{due - read} contributor home(s) not read: their code host accounts keep their last standing")
        except Exception as exc:  # noqa: BLE001 - the loop must outlive one bad cycle (vitals.cycle stamped it an error)
            logger.error("[code_passport_standing] cycle failed: %s", exc)
        await asyncio.sleep(CYCLE_SECONDS)


def stop_code_passport_standing():
    global _stop
    _stop = True
