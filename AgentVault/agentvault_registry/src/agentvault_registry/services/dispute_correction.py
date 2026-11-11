"""V0657 (a), session-code 2026-11-06: the correction rail (the Commander's approval, room seq 1473 and 1482).

An administrator corrects a ruling: the record's ruling becomes the corrected one; the reputation changes the old
ruling made are reversed, and the enforcement actions it opened are marked reversed (the offense leaves the count, the
escalation level follows the offenses that remain); the corrected ruling's reputation rule is applied; why is required
and kept (dispute_corrections), told to both parties and to the ledger (DisputeRulingCorrected).

A correction moves no money: the escrow of a Guild order or a contract settled when it settled, and a correction does
not re-split it. Two effects it reports instead of undoing, because undoing them is its own decision:
- a suspension the old ruling's enforcement reached (escalation level 4) stays: the enforcement rail's reinstate lifts it;
- a slash the old ruling's enforcement executed is not returned.

Its first use (after V0657 is on production) is dispute 1: session-tester lost 10 reputation and gained a warning
although it delivered and was paid. A ruling made before V0657 kept no record of its changes, so they are reversed as
the rules made them then (a party's filing: the loser -10, the winner +2, a dismissal -3 each).

CLAIM FIRST (session-lead's review, room seq 1597). A second correction sent at the same moment (a double click, a
retry after a timeout) must never read the old ruling, plan it again and reverse its reputation twice. So:
1. the record changes ruling in ONE guarded UPDATE (from the ruling the correction read to the corrected one, refused
   while another correction of the record is still applying), committed with the correction's row ('applying', the
   plan) BEFORE any effect. The loser of a race finds the ruling moved: CorrectionInFlight, a 409;
2. every effect is then committed together with its own step on the correction's row (the row locked FOR UPDATE, a
   step already recorded is skipped), so a failure midway leaves the steps done on the record, and finish() does the
   rest from the stored plan, never one twice;
3. the last step writes the record's outcome and marks the correction 'applied' in the same commit; the ledger line
   and the notices follow that commit, once.

plan() is read only (the console shows it before the click); apply() acts on the same plan, stored at the claim.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from . import dispute_rules as rules

logger = logging.getLogger(__name__)

MIN_NOTE = 10
APPLYING, APPLIED = "applying", "applied"


class CorrectionRefused(ValueError):
    """The correction cannot be made (the message says why)."""


class CorrectionInFlight(CorrectionRefused):
    """Another correction holds the record, or its ruling moved under this one: read the record again (a 409)."""

    def __init__(self, message: str, correction_id: Optional[int] = None):
        super().__init__(message)
        self.correction_id = correction_id


def _recorded_reputation(dispute) -> Optional[List[Dict[str, Any]]]:
    rep = (getattr(dispute, "outcome", None) or {}).get("reputation")
    return rep if isinstance(rep, list) else None


def reputation_to_reverse(dispute) -> List[Dict[str, Any]]:
    """The old ruling's reputation changes, as they were made: the record's own (V0657 rulings keep the effective
    change, after the floor at 0), else the rules of the time (a ruling before V0657 was a party's rule)."""
    recorded = _recorded_reputation(dispute)
    if recorded is not None:
        out = []
        for e in recorded:
            before, after = e.get("before"), e.get("after")
            change = (after - before) if isinstance(before, (int, float)) and isinstance(after, (int, float)) \
                else e.get("change", 0)
            out.append({"did": e["did"], "change": int(change or 0), "why": e.get("why"), "source": "the record"})
        return out
    return [{"did": did, "change": change, "why": why, "source": "the rules at the time (no record was kept)"}
            for did, change, why in rules.reputation_deltas(dispute.ruling, dispute.complainant_did,
                                                            dispute.defendant_did, None, None)]


async def _actions(db: AsyncSession, dispute_id: int):
    from ..models import EnforcementAction
    return list((await db.execute(select(EnforcementAction).where(
        EnforcementAction.trigger == "dispute_ruling",
        EnforcementAction.trigger_reference == str(dispute_id),
        EnforcementAction.status.in_(["executed", "pending_approval"]),
    ))).scalars().all())


async def applying_correction_id(db: AsyncSession, dispute_id: int) -> Optional[int]:
    """The id of a correction of this record that is still being applied, or None."""
    row = (await db.execute(text(
        "SELECT id FROM dispute_corrections WHERE dispute_id = :d AND status = 'applying' ORDER BY id LIMIT 1"),
        {"d": int(dispute_id)})).first()
    return int(row[0]) if row else None


def _finish_hint(dispute_id: int, cid: int) -> str:
    return (f"A correction of dispute {dispute_id} is still being applied (correction {cid}); finish it first: "
            f"POST /api/v1/admin/disputes/{dispute_id}/corrections/{cid}/finish")


async def plan(db: AsyncSession, dispute, new_ruling: str) -> Dict[str, Any]:
    """What correcting `dispute` to `new_ruling` would do. Read only. Raises CorrectionRefused (CorrectionInFlight while
    another correction of the record is applying)."""
    if new_ruling not in rules.RULINGS:
        raise CorrectionRefused(f"ruling must be one of {', '.join(rules.RULINGS)}")
    if getattr(dispute, "status", None) != "CLOSED" or not getattr(dispute, "ruling", None):
        raise CorrectionRefused("Only a ruled dispute is corrected; rule on an open one")
    cid = await applying_correction_id(db, dispute.id)
    if cid is not None:
        raise CorrectionInFlight(_finish_hint(dispute.id, cid), cid)
    if new_ruling == dispute.ruling:
        raise CorrectionRefused(f"The dispute already carries this ruling ({rules.ruling_words(new_ruling)})")
    enforcement = []
    for a in await _actions(db, dispute.id):
        e = {"action_id": a.id, "agent_did": a.agent_did, "action": a.action_type, "status": a.status,
             "escalation_level": a.escalation_level, "becomes": "reversed"}
        if a.action_type in ("slash_liquid", "slash_stake") and a.amount and a.status == "executed":
            e["not_returned"] = f"a slash of {a.amount} was executed; a correction moves no money"
        if (a.escalation_level or 0) >= 4:
            e["suspension_stays"] = ("the agent may be suspended by this level; the enforcement rail's reinstate "
                                     f"(POST /api/v1/admin/enforcement/agents/{a.agent_did}/reinstate) lifts it")
        enforcement.append(e)
    filed_by, reason = getattr(dispute, "filed_by", None), getattr(dispute, "reason", None)
    return {
        "dispute_id": dispute.id, "from_ruling": dispute.ruling, "to_ruling": new_ruling,
        "from_words": rules.ruling_words(dispute.ruling), "to_words": rules.ruling_words(new_ruling),
        "reverse_reputation": reputation_to_reverse(dispute),
        "reverse_enforcement": enforcement,
        "apply_reputation": [{"did": did, "change": change, "why": why}
                             for did, change, why in rules.reputation_deltas(
                                 new_ruling, dispute.complainant_did, dispute.defendant_did, filed_by, reason)],
        "trust_signal": rules.trust_signal_applies(new_ruling, filed_by, reason),
        "money": "none: a correction moves no money (the escrow settled when it settled)",
    }


# ── the claim ───────────────────────────────────────────────────────────────────────────────────────────────────────
_CLAIM = (
    "UPDATE disputes SET ruling = :new, updated_at = now() "
    "WHERE id = :id AND status = 'CLOSED' AND ruling = :old "
    "AND NOT EXISTS (SELECT 1 FROM dispute_corrections c WHERE c.dispute_id = :id AND c.status = 'applying')"
)


async def apply(db: AsyncSession, dispute_id: int, new_ruling: str, *, note: str,
                corrected_by: Optional[int]) -> Dict[str, Any]:
    """Correct the ruling (see the module's text). Raises CorrectionRefused (CorrectionInFlight when another correction
    holds the record or its ruling moved under this one), LookupError (no such dispute)."""
    from ..models import Dispute, DisputeCorrection
    note = (note or "").strip()
    if len(note) < MIN_NOTE:
        raise CorrectionRefused(f"Say why the ruling is corrected (at least {MIN_NOTE} characters): it is kept and told")
    d = (await db.execute(select(Dispute).where(Dispute.id == dispute_id))).scalar_one_or_none()
    if d is None:
        raise LookupError(f"Dispute {dispute_id} not found")
    p = await plan(db, d, new_ruling)
    old = d.ruling
    claimed = await db.execute(text(_CLAIM), {"new": new_ruling, "id": int(d.id), "old": old})
    if int(claimed.rowcount or 0) != 1:
        await db.rollback()
        cid = await applying_correction_id(db, d.id)
        if cid is not None:
            raise CorrectionInFlight(_finish_hint(d.id, cid), cid)
        raise CorrectionInFlight(f"Dispute {d.id} changed while this correction was being made (its ruling is no longer "
                                 f"{rules.ruling_words(old)}); read the record again before correcting it")
    corr = DisputeCorrection(dispute_id=d.id, from_ruling=old, to_ruling=new_ruling, note=note,
                             corrected_by=corrected_by, status=APPLYING, plan=p, steps={})
    db.add(corr)
    await db.commit()          # the claim, with its plan, before any effect
    d.ruling = new_ruling      # what the claim wrote (the session keeps its objects across a commit)
    return await _run(db, corr, d)


async def finish(db: AsyncSession, dispute_id: int, correction_id: int) -> Dict[str, Any]:
    """Finish a correction a failure left 'applying': the steps it recorded are kept, the rest are done once, from the
    plan stored at its claim. Raises LookupError (no such correction of this dispute), CorrectionRefused (not applying)."""
    from ..models import Dispute, DisputeCorrection
    corr = (await db.execute(select(DisputeCorrection).where(
        DisputeCorrection.id == int(correction_id),
        DisputeCorrection.dispute_id == int(dispute_id)))).scalar_one_or_none()
    if corr is None:
        raise LookupError(f"Dispute {dispute_id} has no correction {correction_id}")
    if corr.status != APPLYING:
        raise CorrectionRefused(f"Correction {correction_id} of dispute {dispute_id} is {corr.status}; nothing to finish")
    d = (await db.execute(select(Dispute).where(Dispute.id == int(dispute_id)))).scalar_one_or_none()
    if d is None:
        raise LookupError(f"Dispute {dispute_id} not found")
    return await _run(db, corr, d)


# ── the steps: each effect and its record in ONE commit ─────────────────────────────────────────────────────────────
async def _step(db: AsyncSession, cid: int, key: str, effect: Callable[[Any], Awaitable[Any]]) -> Tuple[Any, bool]:
    """Run `effect(row)` once for correction `cid`. Its row is locked and read fresh; a step it already records is
    returned as recorded (False: not done now); else the effect commits together with its record (True). A failing
    effect is rolled back with the lock, effect and record both. (Plain values only cross a step: a rollback expires
    the session's objects, and an async session cannot reload one on access.)"""
    from ..models import DisputeCorrection
    row = (await db.execute(select(DisputeCorrection).where(DisputeCorrection.id == int(cid)).with_for_update()
                            .execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        await db.commit()
        raise LookupError(f"Correction {cid} not found")
    done = dict(row.steps or {})
    if key in done:
        await db.commit()       # nothing written: the commit only releases the lock (and expires nothing)
        return done[key], False
    if row.status != APPLYING:
        status = row.status
        await db.commit()
        raise CorrectionRefused(f"Correction {cid} is {status}; its steps are closed")
    try:
        result = await effect(row)
    except Exception:
        await db.rollback()     # neither the effect nor its record; the lock goes with the transaction
        raise
    done[key] = result
    row.steps = done
    await db.commit()
    return result, True


async def _reputation(db: AsyncSession, did: str, change: int, why: Optional[str]) -> Dict[str, Any]:
    """One reputation change inside the step's transaction (the floor at 0, as update_reputation keeps it)."""
    before = (await db.execute(text("SELECT reputation_score FROM agents WHERE did = :d FOR UPDATE"),
                               {"d": did})).scalar()
    if before is None:
        return {"did": did, "change": int(change), "why": why, "skipped": "no such agent on this registry"}
    after = max(0, int(before) + int(change))
    await db.execute(text("UPDATE agents SET reputation_score = :s WHERE did = :d"), {"s": after, "d": did})
    return {"did": did, "change": int(change), "why": why, "before": int(before), "after": after}


def _tell_ledger_reputation(r: Dict[str, Any], reason: str) -> None:
    """The ReputationChanged line update_reputation emits, after the step's commit; best effort, never raises."""
    if "after" not in r:
        return
    try:
        import asyncio as _aio
        from ..event_emitter import get_event_emitter
        _aio.create_task(get_event_emitter().emit_reputation_changed(
            agent_did=r["did"], old_score=r["before"], new_score=r["after"], reason=reason))
    except Exception as e:  # noqa: BLE001
        logger.error("ReputationChanged for %s not emitted: %s", r.get("did"), e)


async def _reverse_action(db: AsyncSession, action_id: str, agent_did: str, why: str, engine, policy) -> Dict[str, Any]:
    """One enforcement action reversed inside the step's transaction, guarded on its status (reversed once)."""
    res = await db.execute(text(
        "UPDATE enforcement_actions SET status = 'reversed', rejected_reason = :why "
        "WHERE id = :id AND status IN ('executed', 'pending_approval')"), {"why": why[:2000], "id": action_id})
    row: Dict[str, Any] = {"action_id": action_id, "agent_did": agent_did}
    if int(res.rowcount or 0) != 1:
        row["skipped"] = "the action was no longer executed or pending"
        return row
    a = (await db.execute(text(
        "SELECT offense_count, rewards_paused_until, enforcement_status FROM agents WHERE did = :d FOR UPDATE"),
        {"d": agent_did})).first()
    if a is None:
        return row
    offenses = max(0, int(a[0] or 0) - 1)
    remaining = await engine._count_recent_offenses(db, agent_did, policy)
    level = min(4, remaining) if remaining > 0 else 0
    lift = remaining == 0 and a[1] is not None
    await db.execute(text(
        "UPDATE agents SET offense_count = :o, enforcement_level = :l, "
        "rewards_paused_until = CASE WHEN :lift THEN NULL ELSE rewards_paused_until END WHERE did = :d"),
        {"o": offenses, "l": level, "lift": bool(lift), "d": agent_did})
    row.update({"offense_count": offenses, "enforcement_level": level, "agent_status": a[2]})
    if lift:
        row["rewards_pause"] = "lifted"
    return row


async def _run(db: AsyncSession, corr, d) -> Dict[str, Any]:
    """Every step of the stored plan not yet recorded, then the close; the ledger line and the notices once."""
    from ..models import Dispute
    from ..services.enforcement_engine import get_enforcement_engine
    # plain values, read once while the objects are fresh (see _step)
    cid, did_ = int(corr.id), int(d.id)
    complainant, defendant, by = d.complainant_did, d.defendant_did, corr.corrected_by
    p = dict(corr.plan or {})
    note, old, new_ruling = corr.note, corr.from_ruling, corr.to_ruling
    reversed_rep: List[Dict[str, Any]] = []
    for i, e in enumerate(p.get("reverse_reputation") or []):
        if not e.get("change"):
            continue

        async def _undo(_row, e=e):
            return await _reputation(db, e["did"], -int(e["change"]), e.get("why"))
        r, now_done = await _step(db, cid, f"reverse_reputation:{i}", _undo)
        if now_done:
            _tell_ledger_reputation(r, f"Dispute #{did_}: ruling corrected, {e.get('why') or 'its change'} undone")
        reversed_rep.append({**e, "undone": -int(e["change"]), "after": r.get("after"),
                             **({"skipped": r["skipped"]} if r.get("skipped") else {})})
    engine = get_enforcement_engine()
    policy = await engine._load_policy(db)
    reversed_enf: List[Dict[str, Any]] = []
    for e in p.get("reverse_enforcement") or []:
        async def _rev(_row, e=e):
            return await _reverse_action(db, e["action_id"], e["agent_did"],
                                         f"Dispute #{did_} ruling corrected: {note}", engine, policy)
        r, _ = await _step(db, cid, f"reverse_enforcement:{e['action_id']}", _rev)
        reversed_enf.append({**r, "action": e.get("action"),
                             **{k: e[k] for k in ("not_returned", "suspension_stays") if e.get(k)}})
    applied: List[Dict[str, Any]] = []
    for j, e in enumerate(p.get("apply_reputation") or []):
        async def _do(_row, e=e):
            return await _reputation(db, e["did"], int(e["change"]), e.get("why"))
        r, now_done = await _step(db, cid, f"apply_reputation:{j}", _do)
        if now_done:
            _tell_ledger_reputation(r, f"Dispute #{did_}: {e.get('why')}")
        applied.append(r)
    if p.get("trust_signal"):
        async def _signal(_row):
            from ..services import local_trust_updater
            await local_trust_updater.on_dispute_resolved(db, complainant_did=complainant, defendant_did=defendant,
                                                          ruling=new_ruling)
            return "sent"
        try:
            await _step(db, cid, "trust_signal", _signal)
        except (CorrectionRefused, LookupError):
            raise
        except Exception as e:  # noqa: BLE001 — a trust signal is a garnish: kept as not sent, the correction goes on
            logger.warning("dispute %s correction %s: the trust signal was not sent: %s", did_, cid, e)

            async def _not_sent(_row, why=str(e)[:200]):
                return f"not sent: {why}"
            await _step(db, cid, "trust_signal", _not_sent)
    # the close: the record's outcome, the correction's summary and 'applied', in one commit
    summary = {"reversed": {"reputation": reversed_rep, "enforcement": reversed_enf}, "applied": {"reputation": applied}}

    async def _close(row):
        at = datetime.now(timezone.utc)
        dd = (await db.execute(select(Dispute).where(Dispute.id == did_).with_for_update()
                               .execution_options(populate_existing=True))).scalar_one()
        dd.updated_at = at
        dd.outcome = {**(dd.outcome or {}), "reputation": applied,
                      "corrected": {"from": old, "to": new_ruling, "note": note, "by": by, "at": at.isoformat(),
                                    "correction_id": cid}}
        row.reversed, row.applied = summary["reversed"], summary["applied"]
        row.status, row.finished_at = APPLIED, at
        return {"at": at.isoformat()}
    closed, now_done = await _step(db, cid, "close", _close)
    if now_done:
        await _tell(did_, complainant, defendant, old, new_ruling, note, cid, by, closed["at"],
                    len(reversed_rep), len(reversed_enf))
    return {**p, **summary, "note": note, "corrected_by": by, "correction_id": cid, "status": APPLIED,
            "corrected_at": closed.get("at") if isinstance(closed, dict) else None}


async def _tell(dispute_id: int, complainant: str, defendant: str, old: str, new_ruling: str, note: str, cid: int,
                by: Optional[int], at: str, n_rep: int, n_enf: int) -> None:
    """The ledger line and both parties' notice, after the close's commit; best effort, never raises."""
    import asyncio as _aio
    try:
        from ..event_emitter import get_event_emitter
        await get_event_emitter().emit(
            event_type="DisputeRulingCorrected", aggregate_id=f"dispute:{dispute_id}", aggregate_type="Dispute",
            data={"dispute_id": dispute_id, "correction_id": cid, "from_ruling": old, "to_ruling": new_ruling,
                  "note": note, "corrected_by": by, "corrected_at": at,
                  "reputation_reversed": n_rep, "enforcement_reversed": n_enf})
    except Exception as e:  # noqa: BLE001 — the correction stands; the ledger line is logged as missing
        logger.error("DisputeRulingCorrected for dispute %s not emitted: %s", dispute_id, e)
    try:
        from ..background_tasks.push_notify import notify_agent_owners
        _aio.create_task(notify_agent_owners(
            "dispute.resolved", [complainant, defendant], title="Dispute ruling corrected",
            message=(f"Dispute #{dispute_id}: the ruling was corrected from {rules.ruling_words(old)} to "
                     f"{rules.ruling_words(new_ruling)}. Why: {note[:300]}"),
            tags="scales", priority="high", click=f"/ui/#/disputes?id={int(dispute_id)}"))
    except Exception:  # noqa: BLE001
        logger.debug("dispute correction notify skipped", exc_info=True)
