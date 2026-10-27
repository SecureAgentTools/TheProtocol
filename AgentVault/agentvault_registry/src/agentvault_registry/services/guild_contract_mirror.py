"""P3a — THE GUILD mints CONTRACTS (mirror mode, 2026-07-25 · GUILD_MINTS_CONTRACTS, default off).

An awarded guild order mints a spine contract as a LEDGER VIEW: `origin_surface='guild'`,
`origin_ref=<gwo id>`, status `agreed` directly, ONE milestone = the bounty, `fee_bps` = the
order's quoted snapshot, and — the load-bearing detail — **`escrow_ref` ADOPTS the existing
`guildref:{oid}`**: the money was escrowed at post under guild keys and those keys NEVER change
mid-flight, so the P3b cutover (spine drives the settle with the SAME `guildref:…:settle` refs)
produces byte-identical TEG legs.

MIRROR MODE ONLY: guild money paths are untouched; every function here is idempotent,
flag-gated, wrapped, and NEVER raises into a guild flow. The contract_reaper's convergence sweep
re-syncs any order the inline hooks missed — a persistent order↔contract disagreement is the
P3b no-go signal, which is the whole point of running the mirror first.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import secrets
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# guild order status → (contract status, milestone-1 status)
_MAP = {
    "awarded":   ("agreed",      "pending"),
    "submitted": ("in_progress", "submitted"),
    "settling":  ("in_progress", "releasing"),
    "resolving": ("disputed",    "rejected"),
    "settled":   ("completed",   "released"),
    "verified":  ("completed",   "released"),
    "disputed":  ("disputed",    "rejected"),
    "cancelled": ("cancelled",   "cancelled"),
    "refunded":  ("cancelled",   "cancelled"),
    "expired":   ("cancelled",   "cancelled"),
}


def enabled() -> bool:
    return os.getenv("GUILD_MINTS_CONTRACTS", "false").strip().lower() == "true"


def map_order_status(order_status: str) -> Optional[tuple]:
    return _MAP.get(order_status)


async def sync_from_order(db: AsyncSession, oid: str) -> None:
    """Idempotent order→contract convergence. Safe to call after ANY guild transition commit;
    also driven by the contract_reaper convergence sweep. Never raises."""
    if not enabled():
        return
    try:
        o = (await db.execute(text(
            "SELECT * FROM guild_work_orders WHERE id=:o"), {"o": oid})).mappings().first()
        if not o:
            return
        o = dict(o)
        mapped = map_order_status(o["status"])
        if not mapped:            # 'open' etc. — nothing to mirror yet
            return
        cst, mst = mapped
        cid = o.get("contract_id")
        if not cid:
            cid = await _ensure_contract(db, o)
            if not cid:
                return
        now_completed = "completed_at=now()," if cst == "completed" else ""
        now_cancelled = "cancelled_at=now()," if cst == "cancelled" else ""
        await db.execute(text(f"""
            UPDATE contracts SET status=:st, {now_completed} {now_cancelled}
                   provider_did=COALESCE(:w, provider_did),
                   payee_did=COALESCE(:pd, payee_did), payee_org_id=COALESCE(:po, payee_org_id),
                   fee_charged=COALESCE(:fc, fee_charged),
                   counterparty_home_registry=COALESCE(:hr, counterparty_home_registry),
                   updated_at=now()
            WHERE id=:c AND status != :st
        """), {"st": cst, "w": o.get("worker_did"), "pd": o.get("payee_did"),
               "po": o.get("payee_org_id"), "fc": o.get("fee_charged"),
               "hr": o.get("worker_home_registry"), "c": cid})
        ts = {"submitted": "submitted_at=COALESCE(submitted_at, now()),",
              "released": "released_at=COALESCE(released_at, now()),"}.get(mst, "")
        await db.execute(text(f"""
            UPDATE contract_milestones SET status=:m, {ts} deliverable=COALESCE(CAST(:d AS JSONB), deliverable)
            WHERE contract_id=:c AND seq=1 AND status != :m
        """), {"m": mst, "c": cid,
               "d": json.dumps(o["deliverable"]) if o.get("deliverable") else None})
        await db.commit()
    except Exception:  # noqa: BLE001 — the mirror must never break a guild flow
        # WARNING, not debug — a silently-broken mirror is exactly what the P3b gate must see
        # (it still never raises into the guild flow; the convergence sweep will retry).
        logger.warning("[GUILD-MIRROR] sync %s failed (will re-converge)", oid, exc_info=True)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass


async def _ensure_contract(db: AsyncSession, o: dict) -> Optional[str]:
    """Mint the ledger-view contract for an awarded order. ORDERING MATTERS: the contracts row
    must exist BEFORE the guild_work_orders.contract_id claim (mig 0130's FK rejects a link to a
    not-yet-inserted contract — found by the E2E probe). Insert first (fresh random id → no
    conflict), then claim the link; a lost race deletes the orphan (cascade wipes its
    milestone/event) and adopts the winner's id."""
    cid = "ctr_" + secrets.token_hex(12)
    terms = {"spec": (o.get("spec") or "")[:5000], "guild_order_id": o["id"],
             "required_skills": o.get("required_skills")}
    await db.execute(text("""
        INSERT INTO contracts (id, contract_type, origin_surface, origin_ref, client_did,
            provider_did, payee_did, payee_org_id, title, terms, currency, total_amount,
            fee_bps, escrow_ref, status, deadline, counterparty_home_registry,
            created_at, agreed_at, updated_at)
        VALUES (:id,'work_order','guild',:orf,:cd,:pd,:pyd,:po,:t,CAST(:tm AS JSONB),:cy,:ta,
                :fb,:er,'agreed',:dl,:hr,:ca, COALESCE(:aa, now()), now())
        ON CONFLICT (id) DO NOTHING
    """), {"id": cid, "orf": o["id"], "cd": o["poster_did"], "pd": o.get("worker_did"),
           "pyd": o.get("payee_did"), "po": o.get("payee_org_id"),
           "t": (o.get("title") or "Guild order")[:200], "tm": json.dumps(terms),
           "cy": o["currency"], "ta": o["bounty"], "fb": int(o.get("fee_bps") or 0),
           "er": o.get("escrow_ref") or f"guildref:{o['id']}",   # ADOPTED guild keys (P3b continuity)
           "dl": o.get("deadline"), "hr": o.get("worker_home_registry"),
           "ca": o.get("created_at") or _dt.datetime.now(_dt.timezone.utc),
           "aa": o.get("awarded_at")})
    await db.execute(text("""
        INSERT INTO contract_milestones (id, contract_id, seq, title, amount, due_at)
        VALUES (:id,:c,1,'Bounty delivery',:a,:d) ON CONFLICT (contract_id, seq) DO NOTHING
    """), {"id": "ctm_" + secrets.token_hex(12), "c": cid, "a": o["bounty"], "d": o.get("deadline")})
    await db.execute(text("""
        INSERT INTO contract_events (contract_id, seq, event_type, actor_did, payload)
        VALUES (:c, 1, 'created', :a, CAST(:p AS JSONB))
    """), {"c": cid, "a": o["poster_did"],
           "p": json.dumps({"origin": "guild", "order_id": o["id"], "mirror": True})})
    # claim the link AFTER the row exists (FK-satisfied); a lost race cleans up the orphan
    claimed = await db.execute(text(
        "UPDATE guild_work_orders SET contract_id=:c WHERE id=:o AND contract_id IS NULL"),
        {"c": cid, "o": o["id"]})
    if getattr(claimed, "rowcount", 0) == 0:
        await db.execute(text("DELETE FROM contracts WHERE id=:c"), {"c": cid})
        winner = (await db.execute(text(
            "SELECT contract_id FROM guild_work_orders WHERE id=:o"), {"o": o["id"]})).scalar()
        return winner
    logger.info("[GUILD-MIRROR] order %s minted contract %s (adopted %s)",
                o["id"], cid, o.get("escrow_ref") or f"guildref:{o['id']}")
    return cid


async def convergence_scan(db: AsyncSession, limit: int = 20) -> int:
    """Reaper sweep: (a) awarded+ orders with NO contract yet → mint; (b) order↔contract status
    disagreements → re-sync. Returns rows touched. The nightly P3b gate reads the same mapping."""
    if not enabled():
        return 0
    touched = 0
    rows = (await db.execute(text("""
        SELECT id FROM guild_work_orders
        WHERE contract_id IS NULL AND status NOT IN ('open') LIMIT :l
    """), {"l": limit})).fetchall()
    for (oid,) in rows:
        await sync_from_order(db, oid)
        touched += 1
    rows = (await db.execute(text("""
        SELECT o.id FROM guild_work_orders o JOIN contracts c ON c.id = o.contract_id
        WHERE o.status NOT IN ('open') LIMIT :l
    """), {"l": limit * 5})).fetchall()
    for (oid,) in rows:
        o_st = (await db.execute(text(
            "SELECT status FROM guild_work_orders WHERE id=:o"), {"o": oid})).scalar()
        c_st = (await db.execute(text(
            "SELECT c.status FROM contracts c JOIN guild_work_orders o ON o.contract_id=c.id "
            "WHERE o.id=:o"), {"o": oid})).scalar()
        mapped = map_order_status(o_st or "")
        if mapped and c_st != mapped[0]:
            await sync_from_order(db, oid)
            touched += 1
    return touched
