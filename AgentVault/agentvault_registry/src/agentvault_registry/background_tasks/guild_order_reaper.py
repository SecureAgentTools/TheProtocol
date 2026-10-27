"""THE GUILD — order reaper (2026-07-07).

Leader-elected worker that auto-refunds OPEN orders past their deadline that never got awarded
(bounty returns to the poster via the escrow path). AWARDED orders past their ETA are flagged
'disputed' for admin resolution (never auto-paid — a stalled worker must not be paid, and the
poster must not silently lose the bounty). Δ-neutral (refund = zero-sum escrow leg). Gated GUILD_ENABLED.
"""
import asyncio
import json
import logging
import os
from decimal import Decimal

from sqlalchemy import text

from agentvault_registry.database import AsyncSessionLocal
from agentvault_registry.services import guild_escrow

logger = logging.getLogger(__name__)
_task = None
_stop = False
_INTERVAL = int(os.getenv("GUILD_REAPER_INTERVAL_SECONDS", "60"))


async def _sweep_once() -> int:
    n = 0
    async with AsyncSessionLocal() as db:
        # v2 (0119) SAFETY NET: home-held remote stakes whose host never sent release/slash
        # (host crash, peer unreachable) go back to the bidder after 14 days. Deterrent intact
        # for the normal path; nobody's collateral is ever stranded. Δ-neutral.
        stranded = (await db.execute(text(
            "SELECT id, order_id, bidder_did, amount FROM guild_remote_stakes "
            "WHERE status='held' AND created_at <= now() - interval '14 days' LIMIT 20"
        ))).mappings().all()
        for r in stranded:
            try:
                await guild_escrow.escrow_payout(db, r["bidder_did"], Decimal(str(r["amount"])),
                                                 r["order_id"], f"xfstake_timeout:{r['bidder_did'][-12:]}")
                await db.execute(text(
                    "UPDATE guild_remote_stakes SET status='released', resolved_at=now() WHERE id=:i"), {"i": r["id"]})
                await db.commit()
                n += 1
                logger.info("[GUILD-REAPER] stranded remote stake released: %s/%s %s",
                            r["order_id"], r["bidder_did"][-12:], r["amount"])
            except Exception as e:  # noqa: BLE001
                logger.warning("[GUILD-REAPER] stranded stake release failed %s: %s", r["order_id"], e)
        # OPEN past deadline, no award → refund poster + expire.
        # FIX (2026-07-23 drain): CLAIM the terminal transition FIRST (guarded + committed), THEN
        # move money. The old order (refund → then flip → then a `:true` JSONB-literal INSERT that
        # SQLAlchemy misparsed as a bind param → threw → rolled the flip back) left the row 'open'
        # while the refund had already committed → the SAME order was re-refunded every sweep,
        # draining the treasury (one order looped 7.2k× / ~14k). Claim-first makes the refund run
        # exactly once: a failed claim = we never touched it; a failed refund = the order is already
        # 'expired' (fail-closed — the bounty stays in treasury, recoverable, NEVER re-drained).
        stale = (await db.execute(text(
            "SELECT id, poster_did, bounty FROM guild_work_orders "
            "WHERE status='open' AND deadline IS NOT NULL AND deadline <= now() LIMIT 50"
        ))).mappings().all()
        for o in stale:
            try:
                # 1) CLAIM: only one actor transitions open→expired (kills the loop + cancel/reaper race).
                claimed = await db.execute(text(
                    "UPDATE guild_work_orders SET status='expired', settled_at=now() WHERE id=:o AND status='open'"
                ), {"o": o["id"]})
                if getattr(claimed, "rowcount", 0) == 0:
                    continue  # a cancel / another sweep already transitioned it
                seq = (await db.execute(text("SELECT COALESCE(MAX(seq),0)+1 FROM guild_order_events WHERE order_id=:o"), {"o": o["id"]})).scalar()
                # payload as a BOUND param (json.dumps) — never an inline literal: `:true` in a text()
                # literal is parsed as a bind parameter. Matches routers/guild.py::_audit.
                await db.execute(text(
                    "INSERT INTO guild_order_events (order_id, seq, event_type, actor_did, payload) "
                    "VALUES (:o,:q,'expired','reaper', CAST(:p AS JSONB))"
                ), {"o": o["id"], "q": int(seq or 1), "p": json.dumps({"auto_refund": True})})
                await db.commit()  # claim durable BEFORE any money moves → refund can never re-run
                # 2) MONEY (exactly once, post-claim): refund the bounty + every held bidder stake.
                await guild_escrow.escrow_payout(db, o["poster_did"], Decimal(str(o["bounty"])), o["id"], "refund")
                held = (await db.execute(text(
                    "SELECT bidder_did, stake_amount FROM guild_bids WHERE order_id=:o AND stake_status='held'"
                ), {"o": o["id"]})).mappings().all()
                for b in held:
                    await guild_escrow.escrow_payout(db, b["bidder_did"], Decimal(str(b["stake_amount"])), o["id"], f"stake_refund:{b['bidder_did'][-12:]}")
                    await db.execute(text("UPDATE guild_bids SET stake_status='released' WHERE order_id=:o AND bidder_did=:d"), {"o": o["id"], "d": b["bidder_did"]})
                await db.commit()
                n += 1
            except Exception as e:  # noqa: BLE001
                await db.rollback()
                logger.warning("[GUILD-REAPER] expire/refund %s failed (order already 'expired' — no re-drain): %s", o["id"], e)
        # AWARDED past ETA (deadline reused as a soft ceiling) with no submit → flag disputed
        # + file a DDR dispute for the audit trail (contracts precedent; DDR moves no money).
        overdue = (await db.execute(text(
            "SELECT id, poster_did, worker_did FROM guild_work_orders "
            "WHERE status='awarded' AND deadline IS NOT NULL AND deadline <= now() - interval '1 hour' LIMIT 50"
        ))).mappings().all()
        for o in overdue:
            ddr_id = None
            try:
                from agentvault_registry.crud import crud_disputes
                d = await crud_disputes.create_dispute(db, complainant_did=o["poster_did"], defendant_did=o["worker_did"])
                ddr_id = str(getattr(d, "id", None))
            except Exception as e:  # noqa: BLE001 — dispute filing must not block the flag
                logger.warning("[GUILD-REAPER] DDR filing failed for %s: %s", o["id"], e)
            await db.execute(text("UPDATE guild_work_orders SET status='disputed', dispute_id=:d WHERE id=:o AND status='awarded'"),
                             {"d": ddr_id, "o": o["id"]})
            await db.commit()
            n += 1
        n += await _sweep_stuck_money_states(db)
        n += await _sweep_abandoned_submitted(db)
    return n


async def _flag_disputed(db, oid: str, poster_did: str, worker_did: str, note: dict, from_status: str) -> bool:
    """Guarded flip `from_status`→'disputed' (+ best-effort DDR + audit event carrying `note`) —
    the surfacing path for states the reaper must NOT auto-pay. The status guard means a
    concurrent legitimate transition wins and the reaper backs off (returns False)."""
    claimed = await db.execute(text(
        "UPDATE guild_work_orders SET status='disputed' WHERE id=:o AND status=:s"),
        {"o": oid, "s": from_status})
    if getattr(claimed, "rowcount", 0) == 0:
        await db.rollback()
        return False
    seq = (await db.execute(text("SELECT COALESCE(MAX(seq),0)+1 FROM guild_order_events WHERE order_id=:o"), {"o": oid})).scalar()
    await db.execute(text(
        "INSERT INTO guild_order_events (order_id, seq, event_type, actor_did, payload) "
        "VALUES (:o,:q,'disputed','reaper', CAST(:p AS JSONB))"
    ), {"o": oid, "q": int(seq or 1), "p": json.dumps(note)})
    await db.commit()
    try:
        from agentvault_registry.crud import crud_disputes
        d = await crud_disputes.create_dispute(db, complainant_did=poster_did, defendant_did=worker_did or poster_did)
        await db.execute(text("UPDATE guild_work_orders SET dispute_id=COALESCE(dispute_id, :d) WHERE id=:o"),
                         {"d": str(getattr(d, "id", None)), "o": oid})
        await db.commit()
    except Exception as e:  # noqa: BLE001 — dispute filing must not block the flag
        await db.rollback()
        logger.warning("[GUILD-REAPER] DDR filing failed for %s: %s", oid, e)
    return True


async def _sweep_stuck_money_states(db) -> int:
    """GA1 (2026-07-24): recover orders stranded in 'settling'/'resolving' by a crash between the
    status CLAIM and the terminal flip. Age-gated on the order's NEWEST audit event (the claim now
    writes one in its own commit) — a live settle finishes in seconds, so quiet-for-30-min = stuck.

    LOCAL 'settling' is RE-DRIVEN: every escrow leg carries a durable TEG Idempotency-Key
    (guildref:{oid}:{leg}), so already-ran legs return cached and missing legs run — exactly-once
    regardless of where the crash landed. Anything the reaper cannot re-drive deterministically
    (cross-registry legs need the poster's JWT; amount drift 409s on the rail's param-hash) is
    flipped to 'disputed' for admin_resolve — surfaced, never silently frozen, never auto-paid.
    'resolving' is REVERTED to its retryable pre-state (resolved_worker_amt set ⇒ came from
    dispute-payout ⇒ 'resolved'; else admin_resolve ⇒ 'disputed'); the rail keys make the human
    retry exactly-once too. Δ-neutral by construction."""
    stuck_min = int(os.getenv("GUILD_STUCK_MONEY_MINUTES", "30"))
    recovered = 0
    rows = (await db.execute(text(
        "SELECT o.id, o.status, o.poster_did, o.worker_did, o.payee_did, o.bounty, o.fee_bps, "
        "       o.worker_home_registry, o.resolved_worker_amt "
        "FROM guild_work_orders o "
        "WHERE o.status IN ('settling','resolving') "
        "AND COALESCE((SELECT MAX(e.created_at) FROM guild_order_events e WHERE e.order_id=o.id), o.created_at) "
        "    <= now() - (:m * interval '1 minute') LIMIT 10"
    ), {"m": stuck_min})).mappings().all()
    for o in rows:
        oid = o["id"]
        try:
            if o["status"] == "resolving":
                # §MONEY-R28: an xreg dispute payout stages through the poster. Reverting it to
                # 'resolved' lets the payout run again under a NEW `xfd_stage:{nonce}` while the
                # transfer replays from its stable key — the same double-drain the settle branch
                # below already avoids by flagging xreg orders for admin. Mirror that here (the
                # contract reaper excludes xreg for the identical reason).
                if o["worker_home_registry"]:
                    if await _flag_disputed(db, oid, o["poster_did"], o["worker_did"],
                                            {"stuck": "resolving", "xreg": True,
                                             "refs_to_check": f"guildref:{oid}:xfd_stage:* / guild-{oid}-xfdispute"},
                                            from_status="resolving"):
                        recovered += 1
                        logger.warning("[GUILD-REAPER] stuck xreg 'resolving' %s flagged disputed for admin", oid)
                    continue
                back = "resolved" if o["resolved_worker_amt"] is not None else "disputed"
                await db.execute(text("UPDATE guild_work_orders SET status=:s WHERE id=:o AND status='resolving'"),
                                 {"s": back, "o": oid})
                seq = (await db.execute(text("SELECT COALESCE(MAX(seq),0)+1 FROM guild_order_events WHERE order_id=:o"), {"o": oid})).scalar()
                await db.execute(text(
                    "INSERT INTO guild_order_events (order_id, seq, event_type, actor_did, payload) "
                    "VALUES (:o,:q,'stuck_reverted','reaper', CAST(:p AS JSONB))"
                ), {"o": oid, "q": int(seq or 1), "p": json.dumps({"from": "resolving", "to": back})})
                await db.commit()
                recovered += 1
                logger.warning("[GUILD-REAPER] stuck 'resolving' %s reverted to '%s' (retry is rail-idempotent)", oid, back)
                continue
            # status == 'settling'
            if o["worker_home_registry"]:
                # Cross-registry settle needs the poster's JWT — cannot re-drive here. Surface it.
                if await _flag_disputed(db, oid, o["poster_did"], o["worker_did"],
                                        {"stuck": "settling", "xreg": True,
                                         "refs_to_check": f"guildref:{oid}:xf_stage:* / guild-{oid}-xfsettle"},
                                        from_status="settling"):
                    recovered += 1
                    logger.warning("[GUILD-REAPER] stuck xreg 'settling' %s flagged disputed for admin", oid)
                continue
            # LOCAL re-drive, mirroring verify()'s settle exactly (stored fee snapshot → same
            # amounts → same rail param-hash → dedup). Import inside to avoid module cycles.
            from decimal import Decimal as D
            from agentvault_registry.routers.guild import _payout_with_royalty, _resolve_worker_stake, _order_fee_bps
            bounty = D(str(o["bounty"]))
            fee = (bounty * D(_order_fee_bps(dict(o))) / D(10000)).quantize(D("0.0000000001"))
            payout = bounty - fee
            payee = o["payee_did"] or o["worker_did"]
            await _payout_with_royalty(db, payee, payout, oid)
            await db.execute(text(
                "UPDATE guild_work_orders SET status='settled', fee_charged=:f, settled_at=now() "
                "WHERE id=:o AND status='settling'"), {"f": fee, "o": oid})
            await _resolve_worker_stake(db, oid, o["worker_did"], o["worker_did"], "release")
            seq = (await db.execute(text("SELECT COALESCE(MAX(seq),0)+1 FROM guild_order_events WHERE order_id=:o"), {"o": oid})).scalar()
            await db.execute(text(
                "INSERT INTO guild_order_events (order_id, seq, event_type, actor_did, payload) "
                "VALUES (:o,:q,'settled','reaper', CAST(:p AS JSONB))"
            ), {"o": oid, "q": int(seq or 1),
                "p": json.dumps({"recovered": "stuck_settling", "payout": str(payout), "fee": str(fee), "payee": payee})})
            await db.commit()
            recovered += 1
            logger.warning("[GUILD-REAPER] stuck 'settling' %s RE-DRIVEN to settled (payout=%s payee=%s)", oid, payout, payee)
        except Exception as e:  # noqa: BLE001 — a 409 here = rail param-mismatch or in-flight; surface, never re-pay
            await db.rollback()
            try:
                await _flag_disputed(db, oid, o["poster_did"], o["worker_did"],
                                     {"stuck": o["status"], "redrive_error": str(e)[:300]},
                                     from_status=o["status"])
                logger.warning("[GUILD-REAPER] stuck %s %s re-drive failed → disputed: %s", o["status"], oid, e)
            except Exception as e2:  # noqa: BLE001
                await db.rollback()
                logger.warning("[GUILD-REAPER] stuck-order %s flagging ALSO failed: %s", oid, e2)
    return recovered


async def _sweep_abandoned_submitted(db) -> int:
    """GA2 (2026-07-24): a poster who ghosts after the worker submits must not freeze the bounty in
    escrow forever. 'submitted' with no verify for GUILD_SUBMITTED_TIMEOUT_DAYS → 'disputed' + DDR
    (mirrors the awarded-past-ETA policy: never auto-paid, surfaced for admin_resolve). Moves no money."""
    days = int(os.getenv("GUILD_SUBMITTED_TIMEOUT_DAYS", "7"))
    swept = 0
    rows = (await db.execute(text(
        "SELECT id, poster_did, worker_did FROM guild_work_orders "
        "WHERE status='submitted' AND submitted_at IS NOT NULL "
        "AND submitted_at <= now() - (:d * interval '1 day') LIMIT 20"
    ), {"d": days})).mappings().all()
    for o in rows:
        try:
            if await _flag_disputed(db, o["id"], o["poster_did"], o["worker_did"],
                                    {"reason": "submitted_timeout", "days": days},
                                    from_status="submitted"):
                swept += 1
                logger.info("[GUILD-REAPER] abandoned 'submitted' %s → disputed (poster silent %sd)", o["id"], days)
        except Exception as e:  # noqa: BLE001
            await db.rollback()
            logger.warning("[GUILD-REAPER] submitted-timeout sweep failed %s: %s", o["id"], e)
    return swept


async def _loop():
    global _stop
    from .leader import try_acquire_leadership
    from . import vitals as _vitals
    await _vitals.register("guild_order_reaper", module=__name__,
                           pattern="hand-rolled", interval_sec=_INTERVAL, enabled=True)
    while not _stop:
        try:
            if await try_acquire_leadership("guild_order_reaper"):
                async with _vitals.cycle("guild_order_reaper") as _ctx:
                    swept = await _sweep_once()
                    _ctx.note(swept=swept)
                if swept:
                    logger.info("[GUILD-REAPER] processed %s stale order(s)", swept)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[GUILD-REAPER] sweep error: %s", exc)
        await asyncio.sleep(_INTERVAL)


async def start_guild_order_reaper():
    global _task, _stop
    _stop = False
    if _task is None:
        _task = asyncio.create_task(_loop())


async def stop_guild_order_reaper():
    global _task, _stop
    _stop = True
    if _task:
        _task.cancel()
        _task = None
