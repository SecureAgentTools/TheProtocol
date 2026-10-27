"""CONTRACT SPINE — reaper (P2, 2026-07-25). guild_order_reaper's twin, four sweeps, all claim-first:

  1. `offered` past offer_expires_at            → expired            (no money)
  2. `agreed` with NULL escrow_ref older than CONTRACT_STUCK_ESCROW_MINUTES
                                                → revert to offered  (crash between claim+deposit;
       a raced deposit is harmless — its idempotent replay would have set escrow_ref)
       EXEMPT: total_amount = 0 (agreement-only never escrows) and origin_surface='legacy'
       (migrated history carries no escrow by design).
  3. milestone `releasing` older than CONTRACT_STUCK_MONEY_MINUTES (aged on the `releasing`
     contract_event — GA1)                      → RE-DRIVE the legs  (TEG rail dedups already-ran
       legs, runs missing ones — exactly-once either way) → released.
  4. `agreed`/`in_progress` past deadline + CONTRACT_DEADLINE_GRACE_HOURS
                                                → disputed           (NEVER auto-refund mid-work —
       a split is a judgment call; mirrors the guild's abandoned-submitted sweep). The status and
       its audit row only: no dispute record is filed (D6-443).

Δ-neutral by construction (sweeps move existing escrow legs or no money at all).
Gated CONTRACTS_V2_ENABLED. Leader election is inherited from the single-task launch in main.py
(same pattern as the guild reaper).
"""
from __future__ import annotations

import asyncio
import logging
import os

from sqlalchemy import text

from agentvault_registry.database import get_db_context
from agentvault_registry.services import contract_settlement as cs

logger = logging.getLogger(__name__)

_INTERVAL = int(os.getenv("CONTRACT_REAPER_INTERVAL_SECONDS", "60"))


async def _sweep_expired_offers(db) -> int:
    rows = (await db.execute(text(
        "UPDATE contracts SET status='expired', updated_at=now() "
        "WHERE status='offered' AND offer_expires_at IS NOT NULL AND offer_expires_at < now() "
        "RETURNING id, client_did"))).fetchall()
    for cid, client in rows:
        await cs.audit(db, cid, await cs.next_seq(db, cid), "expired", None, {})
        cs.emit("ContractExpired", cid, {"client": client})
    if rows:
        await db.commit()
    return len(rows)


async def _sweep_stuck_escrow(db) -> int:
    """agreed + NULL escrow_ref + total>0 + not legacy, older than the window → back to offered."""
    mins = int(os.getenv("CONTRACT_STUCK_ESCROW_MINUTES", "30"))
    rows = (await db.execute(text(f"""
        UPDATE contracts SET status='offered', provider_did=NULL, agreed_at=NULL, updated_at=now()
        WHERE status='agreed' AND escrow_ref IS NULL AND total_amount > 0
          AND origin_surface != 'legacy'
          AND agreed_at < now() - interval '{mins} minutes'
        RETURNING id
    """))).fetchall()
    for (cid,) in rows:
        await cs.audit(db, cid, await cs.next_seq(db, cid), "escrow_reverted", None,
                       {"note": "claim without deposit aged out — offer reopened"})
        logger.warning("[CONTRACT-REAPER] %s: agreed-without-escrow reverted to offered", cid)
    if rows:
        await db.commit()
    return len(rows)


async def _sweep_stuck_releasing(db) -> int:
    """Re-drive crash-stranded `releasing` milestones. Age from the dated `releasing` audit event."""
    mins = int(os.getenv("CONTRACT_STUCK_MONEY_MINUTES", "30"))
    rows = (await db.execute(text(f"""
        SELECT m.contract_id, m.seq FROM contract_milestones m
        JOIN contracts c ON c.id = m.contract_id
        WHERE m.status='releasing'
          AND c.counterparty_home_registry IS NULL   -- xreg saga needs the client's JWT; their retry re-drives
          AND EXISTS (SELECT 1 FROM contract_events e
                      WHERE e.contract_id = m.contract_id AND e.event_type='releasing'
                        AND (e.payload->>'seq')::int = m.seq
                        AND e.created_at < now() - interval '{mins} minutes')
        LIMIT 10
    """))).fetchall()
    n = 0
    for cid, seq in rows:
        try:
            c = await cs.load_contract(db, cid)
            m = await cs.load_milestone(db, cid, int(seq))
            if not c or not m or m["status"] != "releasing":
                continue
            out = await cs.drive_release(db, c, m, actor_did="reaper")
            logger.warning("[CONTRACT-REAPER] re-drove stuck release %s m%s: %s", cid, seq, out)
            n += 1
        except Exception as e:  # noqa: BLE001
            logger.error("[CONTRACT-REAPER] re-drive failed %s m%s: %s", cid, seq, e)
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass
    return n


async def _sweep_deadline_disputes(db) -> int:
    hours = int(os.getenv("CONTRACT_DEADLINE_GRACE_HOURS", "24"))
    rows = (await db.execute(text(f"""
        UPDATE contracts SET status='disputed', updated_at=now()
        WHERE status IN ('agreed','in_progress') AND deadline IS NOT NULL
          AND deadline < now() - interval '{hours} hours'
        RETURNING id, client_did, provider_did
    """))).fetchall()
    for cid, client, provider in rows:
        await cs.audit(db, cid, await cs.next_seq(db, cid), "disputed", "reaper",
                       {"reason": f"deadline exceeded by >{hours}h"})
        cs.emit("ContractDisputed", cid, {"by": "reaper", "reason": "deadline"})
        logger.warning("[CONTRACT-REAPER] %s past deadline → disputed", cid)
    if rows:
        await db.commit()
    return len(rows)


async def _sweep_guild_convergence(db) -> int:
    """P3a: keep guild orders and their mirror contracts agreed (mint missing, re-sync drifted).
    Persistent disagreement here is the P3b cutover NO-GO signal."""
    try:
        from agentvault_registry.services import guild_contract_mirror
        return await guild_contract_mirror.convergence_scan(db)
    except Exception as e:  # noqa: BLE001
        logger.debug("[CONTRACT-REAPER] guild convergence skipped: %s", e)
        return 0


async def _sweep_once() -> int:
    total = 0
    async with get_db_context() as db:
        total += await _sweep_expired_offers(db)
        total += await _sweep_stuck_escrow(db)
        total += await _sweep_stuck_releasing(db)
        total += await _sweep_deadline_disputes(db)
        total += await _sweep_guild_convergence(db)
    return total


_task = None
_stop = False


async def _loop():
    """Redis leader-elected (guild reaper twin): 1 worker fleet-wide runs the sweeps; the leader
    library is fail-CLOSED when REDIS_URL is set (CLAUDE.md doctrine)."""
    global _stop
    from .leader import try_acquire_leadership
    logger.info("[CONTRACT-REAPER] started (interval=%ss)", _INTERVAL)
    from . import vitals as _vitals
    await _vitals.register("contract_reaper", module=__name__,
                           pattern="hand-rolled", interval_sec=_INTERVAL, enabled=True)
    while not _stop:
        try:
            if await try_acquire_leadership("contract_reaper"):
                async with _vitals.cycle("contract_reaper") as _ctx:
                    n = await _sweep_once()
                    _ctx.note(touched=n)
                if n:
                    logger.info("[CONTRACT-REAPER] sweep touched %d row(s)", n)
        except Exception as e:  # noqa: BLE001
            logger.error("[CONTRACT-REAPER] sweep failed: %s", e, exc_info=True)
        await asyncio.sleep(_INTERVAL)


async def start_contract_reaper():
    global _task, _stop
    _stop = False
    if _task is None:
        _task = asyncio.create_task(_loop())


async def stop_contract_reaper():
    global _task, _stop
    _stop = True
    if _task:
        _task.cancel()
        _task = None
