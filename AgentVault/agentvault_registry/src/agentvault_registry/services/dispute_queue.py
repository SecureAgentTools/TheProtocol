"""V0657 (a), item 3: one ruler's queue for every dispute, wherever it lives.

Disputes lived in three places and the Disputes page showed one: dispute records; Guild orders in `disputed`; contracts
in `disputed` (the contract reaper files no record, by design D6-443, and POST /admin/contracts/{cid}/resolve had no
screen). The queue lists:
- every OPEN dispute record (with the order or contract it is about and what is at stake);
- every Guild order in `disputed` with no open record, and every contract in `disputed` with no open record (a Guild
  order's contract mirror is the order's, never listed twice).
file_record() gives an order or a contract without one its record (filed by the system, linked), so every dispute is
ruled from the same screen, by the same rules, through the same settlement authority.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .dispute_rules import REASONS


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


async def queue(db: AsyncSession) -> Dict[str, Any]:
    from .dispute_parties import names_for
    items: List[Dict[str, Any]] = []
    recs = (await db.execute(text(
        "SELECT d.id, d.complainant_did, d.defendant_did, d.reason, d.filed_by, d.guild_order_id, d.contract_ref, "
        "d.contract_id, d.amount_claimed, d.created_at, o.bounty AS order_bounty, o.currency AS order_currency, "
        "o.title AS order_title, o.status AS order_status, c.title AS contract_title "
        "FROM disputes d LEFT JOIN guild_work_orders o ON o.id = d.guild_order_id "
        "LEFT JOIN contracts c ON c.id = d.contract_ref "
        "WHERE d.status = 'OPEN' ORDER BY d.created_at, d.id"))).mappings().all()
    for r in recs:
        stake = None
        if r["order_bounty"] is not None:
            stake = {"amount": str(r["order_bounty"]), "currency": r["order_currency"], "what": "the order's escrow"}
        elif r["amount_claimed"] is not None:
            stake = {"amount": str(r["amount_claimed"]), "what": "the complainant's claim"}
        items.append({"kind": "dispute", "id": r["id"], "dispute_id": r["id"], "reason": r["reason"],
                      "reason_text": REASONS.get(r["reason"] or ""), "filed_by": r["filed_by"],
                      "complainant_did": r["complainant_did"], "defendant_did": r["defendant_did"],
                      "guild_order_id": r["guild_order_id"], "contract_ref": r["contract_ref"],
                      # every row names its subject (session-watch, seq 1582): the order's title, the contract's, or
                      # the record itself for a party's filing about neither
                      "title": r["order_title"] or r.get("contract_title") or f"Dispute #{r['id']}",
                      "at_stake": stake, "opened_at": _iso(r["created_at"])})
    orders = (await db.execute(text(
        "SELECT o.id, o.title, o.poster_did, o.worker_did, o.bounty, o.currency, o.dispute_id, o.created_at "
        "FROM guild_work_orders o LEFT JOIN disputes d ON CAST(d.id AS TEXT) = o.dispute_id "
        "WHERE o.status = 'disputed' AND (o.dispute_id IS NULL OR d.id IS NULL OR d.status <> 'OPEN') "
        "ORDER BY o.created_at"))).mappings().all()
    for o in orders:
        items.append({"kind": "guild", "id": o["id"], "dispute_id": None, "title": o["title"],
                      "complainant_did": o["poster_did"], "defendant_did": o["worker_did"],
                      "guild_order_id": o["id"], "reason": None, "reason_text": "No open dispute record",
                      "at_stake": {"amount": str(o["bounty"]), "currency": o["currency"], "what": "the order's escrow"},
                      "opened_at": _iso(o["created_at"])})
    contracts = (await db.execute(text(
        "SELECT c.id, c.title, c.client_did, c.provider_did, c.currency, c.dispute_id, c.updated_at, "
        "(SELECT COALESCE(SUM(m.amount),0) FROM contract_milestones m WHERE m.contract_id = c.id "
        " AND m.status NOT IN ('released','cancelled')) AS remainder "
        "FROM contracts c LEFT JOIN disputes d ON CAST(d.id AS TEXT) = c.dispute_id "
        "WHERE c.status = 'disputed' AND c.origin_surface <> 'guild' "
        "AND (c.dispute_id IS NULL OR d.id IS NULL OR d.status <> 'OPEN') ORDER BY c.updated_at"))).mappings().all()
    for c in contracts:
        items.append({"kind": "contract", "id": c["id"], "dispute_id": None, "title": c["title"],
                      "complainant_did": c["client_did"], "defendant_did": c["provider_did"],
                      "contract_ref": c["id"], "reason": None, "reason_text": "No open dispute record",
                      "at_stake": {"amount": str(c["remainder"]), "currency": c["currency"],
                                   "what": "the contract's unreleased escrow"},
                      "opened_at": _iso(c["updated_at"])})
    names = await names_for(db, [x for i in items for x in (i.get("complainant_did"), i.get("defendant_did")) if x])
    for i in items:
        i["complainant_name"] = names.get(i.get("complainant_did"))
        i["defendant_name"] = names.get(i.get("defendant_did"))
    counts = {k: sum(1 for i in items if i["kind"] == k) for k in ("dispute", "guild", "contract")}
    return {"items": items, "counts": counts, "total": len(items)}


class QueueRefused(ValueError):
    """The record cannot be filed (the message says why)."""


async def _guild_reason(db: AsyncSession, oid: str) -> str:
    """Why an order was disputed, from its own first 'disputed' event (the reaper's note, a poster's reject), else the
    deadline sweep, which wrote none before V0657."""
    ev = (await db.execute(text(
        "SELECT actor_did, payload FROM guild_order_events WHERE order_id=:o AND event_type='disputed' "
        "ORDER BY seq LIMIT 1"), {"o": oid})).mappings().first()
    if ev is None:
        return "deadline_missed"
    if ev["actor_did"] != "reaper":
        return "rejected_by_poster"
    payload = ev["payload"] or {}
    if payload.get("reason") in ("deadline_missed",):
        return "deadline_missed"
    return "poster_silent" if payload.get("reason") == "submitted_timeout" else "stuck_payout"


async def file_record(db: AsyncSession, kind: str, ref: str) -> int:
    """A record for a disputed order or contract that has none open: filed by the system, linked, its parties told.
    Returns the new record's id. Raises QueueRefused."""
    from ..crud import crud_disputes
    if kind == "guild":
        o = (await db.execute(text("SELECT id, poster_did, worker_did, status, dispute_id FROM guild_work_orders "
                                   "WHERE id=:o"), {"o": ref})).mappings().first()
        if o is None or o["status"] != "disputed":
            raise QueueRefused(f"Order {ref} is not disputed")
        if await _open_record(db, o["dispute_id"]):
            raise QueueRefused(f"Order {ref} has an open dispute record (#{o['dispute_id']})")
        reason = await _guild_reason(db, ref)
        filed_by = "party" if reason == "rejected_by_poster" else "system"
        d = await crud_disputes.create_dispute(db, complainant_did=o["poster_did"],
                                               defendant_did=o["worker_did"] or o["poster_did"],
                                               guild_order_id=ref, reason=reason, filed_by=filed_by)
        await db.execute(text("UPDATE guild_work_orders SET dispute_id=:d WHERE id=:o"), {"d": str(d.id), "o": ref})
        await db.commit()
        return int(d.id)
    if kind == "contract":
        c = (await db.execute(text("SELECT id, client_did, provider_did, status, origin_surface, dispute_id "
                                   "FROM contracts WHERE id=:c"), {"c": ref})).mappings().first()
        if c is None or c["status"] != "disputed":
            raise QueueRefused(f"Contract {ref} is not disputed")
        if c["origin_surface"] == "guild":
            raise QueueRefused(f"Contract {ref} mirrors a Guild order: rule on the order's record")
        if not c["provider_did"]:
            raise QueueRefused(f"Contract {ref} has no provider to name as the defendant")
        if await _open_record(db, c["dispute_id"]):
            raise QueueRefused(f"Contract {ref} has an open dispute record (#{c['dispute_id']})")
        d = await crud_disputes.create_dispute(db, complainant_did=c["client_did"], defendant_did=c["provider_did"],
                                               contract_ref=ref, reason="deadline_missed", filed_by="system")
        await db.execute(text("UPDATE contracts SET dispute_id=:d WHERE id=:c"), {"d": str(d.id), "c": ref})
        await db.commit()
        return int(d.id)
    raise QueueRefused("kind must be guild or contract")


async def _open_record(db: AsyncSession, rid: Optional[str]) -> bool:
    if not rid:
        return False
    try:
        n = int(str(rid))
    except ValueError:
        return False
    st = (await db.execute(text("SELECT status FROM disputes WHERE id=:i"), {"i": n})).scalar()
    return st == "OPEN"

