"""V0657 (a), session-code 2026-11-06: one settlement authority for a dispute about a Guild order, the ruling's
preview, and the notices a ruling sends.

The Guild order and its dispute record did not know each other (the discovery, room seq 1441, items 1 and 2): the
Guild's resolve paid the split and left the record open; the ruling route closed the record, never touched the escrow,
and ran wallet compensation from whatever amount a party's evidence carried. Dispute 1 is what that allowed: its order
was resolved and the worker paid, its record stayed open, and a ruling against the worker that had delivered followed.
The contract spine solved the same for contracts (services/contract_settlement.py, settle_linked_contract_for_ruling and
close_linked_dispute); this is the Guild's twin:
- settle_guild_for_ruling(): a ruling on a record linked to an order splits the order's escrow by the ruling (or the
  ruler's split), through the Guild's own split_disputed_order, BEFORE the ruling is written: the ruling lands only when
  its money did. An order no longer disputed is left alone (settled elsewhere: the single-authority invariant).
- close_record_for_guild_resolve(): the Guild's resolve closes the order's record with the ruling its split implies.
- preview(): what a ruling would do, read only, from the same rules the ruling applies (services/dispute_rules.py and
  the enforcement engine's plan).
Wallet compensation never runs for a dispute about an escrow (crud_disputes.is_escrow_dispute).
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import dispute_rules as rules

logger = logging.getLogger(__name__)

_Q = Decimal("0.0000000001")


async def linked_guild_order(db: AsyncSession, dispute) -> Optional[dict]:
    """The Guild order a dispute is about: its guild_order_id, else (a record filed before V0657 whose backfill did not
    reach it) the order that names the record as its dispute."""
    oid = getattr(dispute, "guild_order_id", None)
    if oid:
        row = (await db.execute(text("SELECT * FROM guild_work_orders WHERE id=:o"), {"o": oid})).mappings().first()
    else:
        row = (await db.execute(text("SELECT * FROM guild_work_orders WHERE dispute_id=:d"),
                                {"d": str(getattr(dispute, "id", ""))})).mappings().first()
    return dict(row) if row else None


def handed_in(o: dict) -> bool:
    """Whether the worker handed something in (a dismissal leaves that status quo: paid when it did)."""
    return bool(o.get("deliverable")) or o.get("submitted_at") is not None


async def held_stake(db: AsyncSession, o: dict) -> Optional[Decimal]:
    """The worker's collateral still held on the order, if any."""
    if not o.get("worker_did"):
        return None
    v = (await db.execute(text(
        "SELECT stake_amount FROM guild_bids WHERE order_id=:o AND bidder_did=:w AND stake_status='held'"),
        {"o": o["id"], "w": o["worker_did"]})).scalar()
    return Decimal(str(v)) if v is not None else None


async def settle_guild_for_ruling(db: AsyncSession, dispute, ruling: str, *, worker_share: Optional[Decimal] = None,
                                  actor: str, note: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Run the order's split for a ruling. None when the record is about no Guild order. A summary otherwise: the split
    (its legs and the stake), or why nothing moved (the order is settled or cancelled). Raises the split's HTTPException
    (502 when a remote park fails, the order back to disputed; 409 while the order is 'resolving', a settlement in
    flight): the caller writes no ruling then."""
    o = await linked_guild_order(db, dispute)
    if o is None:
        return None
    share = rules.guild_worker_share(ruling, handed_in(o), worker_share)
    out: Dict[str, Any] = {"kind": "guild_split", "guild_order_id": o["id"], "worker_share": str(share),
                           "currency": o.get("currency"), "escrow_is_settlement": True}
    if o.get("status") == "resolving":
        # a settlement in flight, not one that is over (session-lead's review, room seq 1598): another split (the Guild's
        # resolve, a payout, a ruling) holds the order and may be moving the money now; writing "nothing moved" beside
        # it would be a ruling about a split nobody knows the end of
        from fastapi import HTTPException
        raise HTTPException(409, detail=f"A settlement of Guild order {o['id']} is in flight; try again in a moment")
    if o.get("status") != "disputed":
        out.update({"order_status": o.get("status"),
                    "split": f"nothing moved: the order is {o.get('status')}, its escrow settled already"})
        return out
    from agentvault_registry.routers import guild
    paid = await guild.split_disputed_order(db, o, share, actor=actor, note=note, via="ddr_ruling")
    out.update({"order_status": "settled", "split": paid})
    return out


async def close_record_for_guild_resolve(db: AsyncSession, o: dict, worker_share: Decimal, *, ruled_by: Optional[int],
                                         note: Optional[str], money: Optional[dict]) -> Optional[Dict[str, Any]]:
    """After the Guild's resolve split an order: its dispute record, if still open, closes with the ruling the split
    implies (the money already moved; no wallet compensation runs). Never raises into the resolve (the money is final);
    returns what it did, or None when the order has no open record."""
    from agentvault_registry.crud import crud_disputes
    try:
        rid = o.get("dispute_id")
        if rid is None:
            return None
        d = await crud_disputes.get_dispute_by_id(db, int(str(rid)))
        if d is None or getattr(d, "status", "") == "CLOSED":
            return None
        ruling = rules.implied_ruling(worker_share)
        words = (note or "").strip() or f"Resolved on the Guild board: the worker's share was {worker_share}."
        closed = await crud_disputes.update_dispute_ruling(db, d.id, ruling, ruled_by=ruled_by, note=words,
                                                           money={"kind": "guild_split", "guild_order_id": o["id"],
                                                                  "worker_share": str(worker_share), "split": money})
        notify_ruled(closed, money=None)
        return {"dispute_id": d.id, "ruling": ruling}
    except Exception as e:  # noqa: BLE001 — the split is final; the record is told separately
        logger.warning("[GUILD] the order %s was resolved but its dispute record was not closed: %s", o.get("id"), e)
        return {"error": "the order was resolved; its dispute record was not closed", "dispute_id": o.get("dispute_id")}


def notify_ruled(dispute, money: Optional[dict]) -> None:
    """Both parties hear the ruling, in words and with the ruler's reason (item 5); best effort, never raises."""
    try:
        import asyncio as _aio
        from agentvault_registry.background_tasks.push_notify import notify_agent_owners
        note = (getattr(dispute, "ruling_note", None) or "").strip()
        msg = f"Dispute #{dispute.id} was ruled {rules.ruling_words(dispute.ruling)}."
        if note:
            msg += f" The ruler's reason: {note[:300]}"
        if money and money.get("applied"):
            msg += f" Compensation: {money.get('amount', 0)}."
        elif money and money.get("cross_registry") and money.get("reason"):
            # V0660 (k): what happens to a cross-registry compensation, in its own words (delivered, retried, not
            # delivered, refused), so nobody is told a payout is coming that is not
            msg += " " + str(money["reason"])[:400]
        _aio.create_task(notify_agent_owners(
            "dispute.resolved", [dispute.complainant_did, dispute.defendant_did],
            title="Dispute ruled", message=msg, tags="scales", priority="high",
            click=f"/ui/#/disputes?id={int(dispute.id)}"))
    except Exception:  # noqa: BLE001
        logger.debug("dispute.resolved notify skipped", exc_info=True)


async def _names(db: AsyncSession, dids) -> Dict[str, Optional[str]]:
    """Agent names for display (a local agent's name, else a mirrored card's)."""
    from agentvault_registry.services.dispute_parties import names_for
    return await names_for(db, dids)


async def preview(db: AsyncSession, dispute, ruling: str, worker_share: Optional[Decimal] = None) -> Dict[str, Any]:
    """What a ruling would do, read only: who gets what, each reputation change, the enforcement step. The ruling
    applies the same rules (services/dispute_rules.py) and the enforcement engine acts on the same plan."""
    from agentvault_registry.crud import crud_disputes
    if ruling not in rules.RULINGS:
        raise ValueError(f"ruling must be one of {', '.join(rules.RULINGS)}")
    filed_by, reason = getattr(dispute, "filed_by", None), getattr(dispute, "reason", None)
    names = await _names(db, [dispute.complainant_did, dispute.defendant_did])

    money: Dict[str, Any]
    o = await linked_guild_order(db, dispute)
    if o is not None:
        share = rules.guild_worker_share(ruling, handed_in(o), worker_share)
        bounty = Decimal(str(o.get("bounty") or 0))
        worker_amt = (bounty * share).quantize(_Q)
        stake = await held_stake(db, o)
        money = {"kind": "guild_split", "guild_order_id": o["id"], "order_status": o.get("status"),
                 "currency": o.get("currency"), "handed_in": handed_in(o), "worker_share": str(share)}
        if o.get("status") != "disputed":
            money["moves"] = False
            money["why"] = f"The order is {o.get('status')}: its escrow settled already, and this ruling moves nothing."
        else:
            money.update({"moves": True, "escrow": str(bounty), "worker_gets": str(worker_amt),
                          "poster_gets": str(bounty - worker_amt), "fee": "none (a dispute split pays the whole bounty)",
                          "stake": None if stake is None else {
                              "amount": str(stake), "goes_to": "the worker (released)" if share >= 1
                              else "the poster (slashed)"}})
    elif getattr(dispute, "contract_ref", None) or getattr(dispute, "contract_id", None):
        from agentvault_registry.services import contract_settlement as cs
        c = await cs.find_linked_contract(db, dispute)
        if c is None:
            money = {"kind": "none", "moves": False, "why": "No linked contract was found."}
        else:
            pct = cs.ruling_to_provider_pct(c, dispute, ruling)
            remainder = (await db.execute(text(
                "SELECT COALESCE(SUM(amount),0) FROM contract_milestones WHERE contract_id=:c "
                "AND status NOT IN ('released','cancelled')"), {"c": c["id"]})).scalar() or 0
            remainder = Decimal(str(remainder))
            prov = (remainder * Decimal(pct) / Decimal(100)).quantize(_Q)
            money = {"kind": "contract_split", "contract_id": c["id"], "contract_status": c.get("status"),
                     "moves": c.get("status") == "disputed", "provider_pct": pct, "remainder": str(remainder),
                     "provider_gets": str(prov), "client_gets": str(remainder - prov)}
    else:
        claimed = getattr(dispute, "amount_claimed", None)
        amount = Decimal(str(claimed)) if (claimed is not None and ruling == "IN_FAVOR_OF_COMPLAINANT") else Decimal(0)
        money = {"kind": "wallet_compensation", "moves": amount > 0, "amount": str(amount),
                 "from_did": dispute.defendant_did, "to_did": dispute.complainant_did,
                 "why": None if amount > 0 else ("No amount was claimed when the dispute was filed."
                                                if ruling == "IN_FAVOR_OF_COMPLAINANT" else "This ruling moves no money.")}

    reputation = [{"did": did, "name": names.get(did), "change": change, "why": why}
                  for did, change, why in rules.reputation_deltas(ruling, dispute.complainant_did,
                                                                  dispute.defendant_did, filed_by, reason)]
    enforcement: Optional[Dict[str, Any]] = None
    if rules.enforcement_applies(ruling, filed_by, reason):
        from agentvault_registry.services.enforcement_engine import get_enforcement_engine
        plan = await get_enforcement_engine().plan_dispute_outcome(
            db, dispute.defendant_did, crud_disputes.enforcement_amount(dispute))
        enforcement = {**plan, "agent_did": dispute.defendant_did, "agent_name": names.get(dispute.defendant_did),
                       "slash_amount": None if plan.get("slash_amount") is None else str(plan["slash_amount"])}
    return {"dispute_id": dispute.id, "ruling": ruling, "ruling_words": rules.ruling_words(ruling),
            "filed_by": filed_by, "reason": reason, "money": money, "reputation": reputation,
            "enforcement": enforcement}
