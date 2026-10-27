"""
Liability / push-login expiry sweeper — COCKPIT CARD (2026-07-26)

Two tables hold short-lived rows that only ever reached a terminal state if a human happened to
touch them again:

  * `liability_challenges` — a confirmation lapses after 120 seconds. The approve path expires it
    lazily on the next attempt, so a challenge nobody returned to stayed `pending` forever. The
    read endpoint filters on `expires_at`, so this was never visible to a user — but the DOCTRINE
    is that **expiry is a denial**, and a denial that leaves no evidence is not a denial, it is a
    gap. A lapsed confirmation now appends `challenge_denied(reason=expired)` to the mandate's
    hash chain exactly as an attempted-approve-after-expiry would have.

  * `login_approvals` — same shape, no evidence chain. Left pending, they made every operational
    query about "who is waiting on an approval" wrong.

Status-only writes. No balances, no authority, Δ-irrelevant. Leader-elected like every other
worker here, so exactly one instance sweeps.
"""
import asyncio
import logging

from sqlalchemy import text

from ..database import AsyncSessionLocal as async_session_factory
from ..services import liability as liab

logger = logging.getLogger(__name__)

_running = False

CYCLE_SECONDS = 60
# Bounded per cycle: the first sweep on a registry with months of history should not open one
# enormous transaction. Whatever is left is picked up on the next pass a minute later.
BATCH = 200


async def _sweep_challenges(db) -> int:
    """Expire lapsed confirmations, appending the denial each one is entitled to."""
    rows = (await db.execute(text("""
        SELECT id, mandate_id, action_ref FROM liability_challenges
        WHERE status = 'pending' AND expires_at <= now()
        ORDER BY expires_at LIMIT :lim
    """), {"lim": BATCH})).mappings().all()
    if not rows:
        return 0

    for r in rows:
        # Guarded on status so a human approving in this exact window still wins the race.
        res = await db.execute(text(
            "UPDATE liability_challenges SET status='expired', resolved_at=now() "
            "WHERE id = :c AND status = 'pending'"), {"c": r["id"]})
        if not res.rowcount:
            continue
        try:
            await liab.append_evidence(db, r["mandate_id"], "challenge_denied",
                                       {"challenge_id": r["id"], "reason": "expired",
                                        "swept": True},
                                       action_ref=r["action_ref"])
        except Exception:
            # An unwritable evidence link must not strand the row as pending forever; the
            # status change is still correct and the failure is loud enough here.
            logger.warning("[LIAB-SWEEP] evidence append failed for %s", r["id"], exc_info=True)
    return len(rows)


async def _sweep_login_approvals(db) -> int:
    res = await db.execute(text("""
        UPDATE login_approvals SET status='expired', resolved_at=now()
        WHERE id IN (
            SELECT id FROM login_approvals
            WHERE status = 'pending' AND expires_at <= now()
            ORDER BY expires_at LIMIT :lim
        )
    """), {"lim": BATCH})
    return res.rowcount or 0


async def _sweep_once():
    try:
        async with async_session_factory() as db:
            challenges = await _sweep_challenges(db)
            approvals = await _sweep_login_approvals(db)
            await db.commit()
            if challenges or approvals:
                logger.info("[LIAB-SWEEP] expired %d confirmation(s), %d sign-in approval(s)",
                            challenges, approvals)
            else:
                logger.debug("[LIAB-SWEEP] nothing to expire")
    except Exception:
        # §VITALS: covers the whole sweep — re-raised into the loop below.
        logger.error("[LIAB-SWEEP] sweep error", exc_info=True)
        raise


async def liability_expiry_loop():
    """Background loop — 60s cycle, leader-elected."""
    from .leader import try_acquire_leadership
    from . import vitals as _vitals
    global _running
    _running = True
    logger.info("[LIAB-SWEEP] Liability/login expiry worker started (%ds cycle)", CYCLE_SECONDS)
    await _vitals.register("liability_expiry", module=__name__, pattern="hand-rolled",
                           interval_sec=CYCLE_SECONDS, enabled=True)
    while _running:
        try:
            if await try_acquire_leadership("liability_expiry"):
                async with _vitals.cycle("liability_expiry"):
                    await _sweep_once()
        except Exception:
            logger.error("[LIAB-SWEEP] cycle error", exc_info=True)
        await asyncio.sleep(CYCLE_SECONDS)


def stop_liability_expiry():
    global _running
    _running = False
