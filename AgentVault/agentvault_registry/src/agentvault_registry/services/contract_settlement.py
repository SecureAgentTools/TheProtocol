"""CONTRACT SPINE — settlement core (P2, 2026-07-25).

Everything that moves money for a contract lives HERE, on the shared escrow rail
(`services/escrow.py`, `ctrref:{cid}:{leg}` legs → TEG treasury, zero-sum, Δ=0 by construction).

Doctrine (the §HARDENING invariants, restated where they bite):
  I-C2  claim-first — callers CLAIM the status transition (guarded UPDATE, committed) BEFORE any
        function here runs a leg. The reaper may re-drive `releasing` because of exactly that.
  I-C3  every leg's Idempotency-Key == its ref; amounts derive from SNAPSHOTS (fee_bps,
        template_royalty_bps, milestone.amount) so a re-drive replays byte-identical params.
  I-C6  Σ milestone.amount == total_amount (validated at create; asserted in E2E).
  I-C9  a missing optional payee (template author gone, org treasury absent) DROPS that leg and
        the payout re-sums to the full remainder — settlement never blocks on a royalty.

Leg map for milestone `m` of contract `c` (gross = m.amount):
    fee      = gross · c.fee_bps/10000          → stays in treasury (NOT a leg — guild-identical)
    royalty  = gross · c.template_royalty_bps/10000  → template author   leg  m{seq}:settle_tpl
    payout   = gross − fee − royalty            → payee (or provider)   leg  m{seq}:settle
    forge lineage carve (FORGE_ROYALTY_ENABLED) further splits `payout` via
    forge_royalty.compute_legs (legs sum EXACTLY to payout) — combined template+forge carve is
    clamped to CONTRACT_ROYALTY_STACK_CAP_BPS (D2, default 750) with the overflow returned to the
    payee leg, re-summed exactly.
"""
from __future__ import annotations

import json
import logging
import os
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.services import escrow

logger = logging.getLogger(__name__)

_Q = Decimal("0.0000000001")


# ── shared row/audit helpers (router + reaper both use these) ─────────────────────────────────

async def load_contract(db: AsyncSession, cid: str) -> Optional[dict]:
    row = (await db.execute(text("SELECT * FROM contracts WHERE id=:c"), {"c": cid})).mappings().first()
    return dict(row) if row else None


async def load_milestone(db: AsyncSession, cid: str, seq: int) -> Optional[dict]:
    row = (await db.execute(text(
        "SELECT * FROM contract_milestones WHERE contract_id=:c AND seq=:s"),
        {"c": cid, "s": seq})).mappings().first()
    return dict(row) if row else None


async def next_seq(db: AsyncSession, cid: str) -> int:
    n = (await db.execute(text(
        "SELECT COALESCE(MAX(seq),0)+1 FROM contract_events WHERE contract_id=:c"), {"c": cid})).scalar()
    return int(n or 1)


async def audit(db: AsyncSession, cid: str, seq: int, etype: str,
                actor: Optional[str], payload: Optional[dict]) -> None:
    await db.execute(text("""
        INSERT INTO contract_events (contract_id, seq, event_type, actor_did, payload)
        VALUES (:c, :q, :e, :a, CAST(:p AS JSONB))
    """), {"c": cid, "q": seq, "e": etype, "a": actor, "p": json.dumps(payload or {})})


def emit(event_type: str, cid: str, data: dict) -> None:
    """Fire-and-forget ES event (guild `_emit` twin; registry emitter is fail-open — no policy
    rows needed for the new Contract* types, and they never emit from TEG)."""
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        get_event_emitter().emit_background(event_type=event_type, aggregate_id=cid, data=data)
    except Exception:  # noqa: BLE001
        # §S4: a ledger event on a money path at debug level is invisible in
        # production (prod logs at INFO). Best-effort, but not unobservable.
        logger.warning("[CONTRACT] emit %s skipped for %s", event_type, cid, exc_info=True)


# §NOTIFV2 — which PARTY a contract notification is FOR. This piggybacks on webhook()
# deliberately: it is the one function every transition already calls POST-COMMIT from every
# surface (router, reaper, settlement driver, legacy adapter, guild mirror), so wiring here
# means a rolled-back transition can never phantom-notify and no new surface can forget to.
# contract.created is absent on purpose (draft noise); contract.accepted is the legacy-adapter
# alias of agreed and maps to the same type.
_NOTIFY_TARGET = {
    "contract.offered": ("contract.offered", "provider"),      # a private offer landed on you
    "contract.agreed": ("contract.agreed", "both"),
    "contract.accepted": ("contract.agreed", "both"),
    "contract.milestone_submitted": ("contract.milestone_submitted", "client"),
    "contract.milestone_released": ("contract.milestone_released", "provider"),
    "contract.disputed": ("contract.disputed", "both"),
    "contract.completed": ("contract.completed", "both"),
    "contract.cancelled": ("contract.cancelled", "both"),
}

_NOTIFY_TITLE = {
    "contract.offered": "Contract offer received",
    "contract.agreed": "Contract agreed - escrow funded",
    "contract.milestone_submitted": "Milestone delivered - your review",
    "contract.milestone_released": "Milestone released - you were paid",
    "contract.disputed": "Contract disputed",
    "contract.completed": "Contract completed",
    "contract.cancelled": "Contract cancelled",
}


def webhook(event: str, c: dict, extra: Optional[dict] = None) -> None:
    """Owner-scoped fan-out to both parties' developers; fire-and-forget. Reads never call this
    (I-C8). §NOTIFV2: also fans out the typed PUSH notification for the party the event is FOR
    — dark until NOTIFY_V2_MODE=on because these keys have no legacy default (new types are
    silent under legacy verdicts, by design)."""
    try:
        import asyncio as _aio
        from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
        data = {"contract_id": c["id"], "status": c.get("status"),
                "client_did": c.get("client_did"), "provider_did": c.get("provider_did"),
                **(extra or {})}
        dids = [d for d in (c.get("client_did"), c.get("provider_did")) if d]
        _aio.create_task(dispatch_webhook_for_agents(event, data, dids, source_label="contracts_v2"))
    except Exception:  # noqa: BLE001
        logger.debug("[CONTRACT] webhook %s skipped", event, exc_info=True)
    try:
        target = _NOTIFY_TARGET.get(event)
        if not target:
            return
        type_key, party = target
        if party == "client":
            n_dids = [c.get("client_did")]
        elif party == "provider":
            n_dids = [c.get("provider_did")]
        else:
            n_dids = [c.get("client_did"), c.get("provider_did")]
        n_dids = [d for d in n_dids if d]
        if not n_dids:
            return
        import asyncio as _aio
        from agentvault_registry.background_tasks.push_notify import notify_agent_owners
        cid_short = str(c.get("id") or "")[:16]
        amt = c.get("total_amount")
        ccy = c.get("currency") or ""
        seq = (extra or {}).get("seq")
        bits = [str(c.get("title") or cid_short)]
        if seq is not None:
            bits.append(f"milestone {seq}")
        if amt is not None:
            bits.append(f"{amt} {ccy}".strip())
        _aio.create_task(notify_agent_owners(
            type_key, n_dids,
            title=_NOTIFY_TITLE.get(event, "Contract update"),
            message=" - ".join(bits)[:180],
            tags="scroll",
            priority="high" if type_key == "contract.disputed" else "default",
            click="/ui/#/contracts",
        ))
    except Exception:  # noqa: BLE001
        logger.debug("[CONTRACT] notify %s skipped", event, exc_info=True)


# ── leg computation (pure, deterministic) ─────────────────────────────────────────────────────

async def _template_royalty_payee(db: AsyncSession, c: dict) -> Optional[str]:
    """Resolve the template author payee: owner agent if it still exists, else the maintaining
    org's AGORA treasury agent, else None (drop the leg — I-C9)."""
    if not c.get("template_version_id"):
        return None
    row = (await db.execute(text("""
        SELECT t.owner_agent_did, t.maintained_by_org_id
        FROM contract_template_versions v JOIN contract_templates t ON t.id = v.template_id
        WHERE v.id = :v
    """), {"v": c["template_version_id"]})).first()
    if not row:
        return None
    owner, org = row[0], row[1]
    if owner and (await db.execute(text(
            "SELECT 1 FROM agents WHERE did=:d AND status='active'"), {"d": owner})).first():
        return owner
    if org:
        # §ORGTREASURY (Track C): the ONE resolver — prefers the org's own treasury, falls back
        # to its first AGORA listing (deterministically; this site used to LIMIT 1 unordered).
        from agentvault_registry.services.org_treasury import resolve_org_treasury_did
        t = await resolve_org_treasury_did(db, str(org))
        if t:
            return t
    return None


async def compute_release_legs(db: AsyncSession, c: dict, m: dict
                               ) -> Tuple[Decimal, List[Tuple[str, Decimal, str]]]:
    """→ (fee, [(did, amount, leg_name), …]). Deterministic from snapshots; legs sum to
    gross − fee EXACTLY. Zero-amount milestones → (0, [])."""
    gross = Decimal(str(m["amount"]))
    if gross <= 0:
        return Decimal("0"), []
    seq = int(m["seq"])
    fee = (gross * Decimal(int(c.get("fee_bps") or 0)) / Decimal(10000)).quantize(_Q)

    royalty = Decimal("0")
    tpl_payee = None
    tpl_bps = int(c.get("template_royalty_bps") or 0)
    if tpl_bps > 0:
        tpl_payee = await _template_royalty_payee(db, c)
        if tpl_payee:
            royalty = (gross * Decimal(tpl_bps) / Decimal(10000)).quantize(_Q)

    payout = gross - fee - royalty
    payee = c.get("payee_did") or c["provider_did"]
    legs: List[Tuple[str, Decimal, str]] = []

    # forge lineage carve on the payout (guild's _payout_with_royalty twin), stack-capped (D2)
    carve: List[Tuple[str, Decimal]] = [(payee, payout)]
    try:
        from agentvault_registry.forge_flags import royalty_enabled
        if royalty_enabled() and payout > 0:
            from agentvault_registry.services import forge_royalty
            carve = await forge_royalty.compute_legs(db, payout, payee)
    except Exception as e:  # noqa: BLE001
        logger.warning("[CONTRACT] forge carve unavailable (%s) — paying undivided", e)
        carve = [(payee, payout)]
    if len(carve) > 1:
        # D2 stack cap: template royalty + forge lineage carve together never exceed
        # CONTRACT_ROYALTY_STACK_CAP_BPS of gross; overflow returns to the payee head leg.
        cap_bps = int(os.getenv("CONTRACT_ROYALTY_STACK_CAP_BPS", "750"))
        cap_amt = (gross * Decimal(cap_bps) / Decimal(10000)).quantize(_Q) - royalty
        forge_amt = sum((a for (_d, a) in carve[1:]), Decimal("0"))  # head leg = payee (compute_legs contract)
        if cap_amt < 0:
            cap_amt = Decimal("0")
        if forge_amt > cap_amt > 0:
            scale = cap_amt / forge_amt
            scaled = [(d, (a * scale).quantize(_Q)) for d, a in carve[1:]]
            head = payout - sum((a for _, a in scaled), Decimal("0"))  # exact re-sum
            carve = [(carve[0][0], head)] + scaled
        elif forge_amt > 0 and cap_amt == 0:
            carve = [(payee, payout)]

    for i, (did, amt) in enumerate(carve):
        if amt <= 0:
            continue
        name = f"m{seq}:settle" if (i == 0 and did == payee) else f"m{seq}:settle_roy{i}"
        legs.append((did, amt, name))
    if royalty > 0 and tpl_payee:
        legs.append((tpl_payee, royalty, f"m{seq}:settle_tpl"))
    return fee, legs


# ── execution (caller has ALREADY claimed the status — I-C2) ─────────────────────────────────

async def drive_release(db: AsyncSession, c: dict, m: dict, *, actor_did: Optional[str],
                        stars: Optional[int] = None, auth_header: Optional[str] = None) -> dict:
    """Run the legs for a CLAIMED (`releasing`) milestone, flip it `released`, and complete the
    contract when it was the last one. Idempotent under re-drive: legs dedup on the TEG rail,
    the released-flip is guarded. Returns a summary dict.

    CROSS-REGISTRY provider (`counterparty_home_registry` set): the guild verify saga, verbatim —
    the escrow can't credit a remote TEG directly, so STAGE payout through the CLIENT
    (treasury→client, `m{seq}:xf_stage`) then the client's own /teg/cross-registry-transfer →
    remote payee (their JWT is on THIS request; 2PC; stable Idempotency-Key ⇒ retries
    exactly-once). Transfer failure → compensating re-deposit + revert `releasing`→`submitted`
    so the client's retry works. Requires `auth_header`; the reaper skips xreg rows."""
    cid, seq = c["id"], int(m["seq"])
    fee, legs = await compute_release_legs(db, c, m)
    if c.get("counterparty_home_registry") and legs:
        payee = c.get("payee_did") or c["provider_did"]
        remote = [(d, a, n) for d, a, n in legs if d == payee]
        local = [(d, a, n) for d, a, n in legs if d != payee]   # template-royalty leg stays local
        stage_amt = sum((a for _d, a, _n in remote), Decimal("0"))
        if stage_amt > 0:
            if not auth_header:
                raise escrow.EscrowError(409, "cross-registry release requires the client's own "
                                              "authenticated request (retry as the client)")
            import httpx as _httpx
            import secrets as _secrets
            nonce = _secrets.token_hex(3)
            await escrow.escrow_payout(db, c["client_did"], stage_amt,
                                       f"ctrref:{cid}:m{seq}:xf_stage:{nonce}",
                                       reason="contract_settle")
            xf_ok, xf_err, xf_unknown, xf_why = False, "", False, ""
            xr, xf_exc = None, None
            try:
                async with _httpx.AsyncClient(timeout=30.0) as xc:
                    xr = await xc.post(
                        "http://localhost:8000/api/v1/teg/cross-registry-transfer",
                        json={"receiver_did": payee, "amount": str(stage_amt)},
                        headers={"Authorization": auth_header, "Content-Type": "application/json",
                                 "Idempotency-Key": f"ctr-{cid}-m{seq}-xfsettle"})
                    xf_ok = xr.status_code in (200, 201)
                    if not xf_ok:
                        xf_err = f"HTTP {xr.status_code}: {xr.text[:200]}"
                    else:
                        # §DOCSFIX D6-456: the transfer answers one the TEGs did not complete with 200 and "status":
                        # "failed"; that is no payment (the milestone was recorded released while the units stayed
                        # with the client), so it takes the failure path below
                        try:
                            _xb = xr.json()
                        except ValueError:
                            _xb = {}
                        if isinstance(_xb, dict) and str(_xb.get("status") or "").strip().lower() == "failed":
                            xf_ok = False
                            xf_err = f"status failed: {str(_xb.get('error_message') or '')[:200]}"
            except Exception as e:  # noqa: BLE001
                xf_err = str(e)
                xf_exc = e
            if not xf_ok:
                # §DOCSFIX review (D6-456) and D6-776: the staged units go back to escrow, and the milestone reopens,
                # only after an answer that PROVES nothing moved (a "failed" that says so, a refusal made before the
                # transfer ran, a connection never made). Any other (a partial commit, a read timeout, a 5xx, an answer
                # that says its outcome is not known) may have paid the provider; the endpoint keeps that answer under
                # the stable key for 24 h and runs the transfer afresh after it, so a reopened milestone could be paid
                # twice. "The client still holds the units" is no proof: a client may hold units of its own.
                from .payout_outcome import RETRY, stage_failure_outcome
                _xo = stage_failure_outcome(xr if xf_exc is None else None, xf_exc)
                xf_unknown, xf_why = _xo.kind != RETRY, _xo.reason
                # §MONEY-R28: reopen for a fresh stage ONLY when the previous stage was fully
                # reversed. `xf_stage:{nonce}` is random per attempt, so reopening after a
                # timed-out-but-committed transfer stages a SECOND payout under a new key while the
                # transfer replays from its stable key and moves nothing. Held milestones stay
                # 'releasing'; the contract reaper deliberately EXCLUDES xreg contracts
                # (counterparty_home_registry IS NULL), so nothing auto-pays or auto-refunds them.
                compensated = False
                if xf_unknown:   # held as it stands: nothing is returned for a transfer that may have paid
                    logger.error("[CONTRACT] XF settle for %s m%s failed without proof that nothing moved (%s); "
                                 "held for admin review: %s", cid, seq, xf_why, xf_err)
                else:
                    try:  # compensate: re-escrow the staged funds (the client just received them)
                        await escrow.escrow_deposit(c["client_did"], stage_amt,
                                                    f"ctrref:{cid}:m{seq}:xf_stage_return:{nonce}",
                                                    reason="contract_escrow")
                        compensated = True
                    except escrow.EscrowError as ce:
                        logger.error("[CONTRACT] XF compensation FAILED for %s m%s (funds staged with "
                                     "client): %s", cid, seq, ce.message)
                if compensated:
                    await db.execute(text(
                        "UPDATE contract_milestones SET status='submitted' WHERE contract_id=:c "
                        "AND seq=:s AND status='releasing'"), {"c": cid, "s": seq})
                await audit(db, cid, await next_seq(db, cid), "release_failed", actor_did,
                            {"seq": seq, "error": xf_err[:300], "compensated": compensated,
                             "held_for": None if compensated else "admin",
                             **({"outcome_unknown": True, "outcome": xf_why[:120]} if xf_unknown else {})})
                await db.commit()
                if xf_unknown:
                    raise escrow.EscrowError(502, f"cross-registry settle failed: {xf_err}; the answer does not say "
                                                  f"that nothing moved, so the provider may have been paid: milestone "
                                                  f"{seq} is held for admin review and its staged funds are not "
                                                  f"returned to escrow")
                raise escrow.EscrowError(502, f"cross-registry settle failed: {xf_err}" if compensated
                                         else f"cross-registry settle failed: {xf_err}; the staged funds are "
                                              f"still with the client and milestone {seq} is held for admin review")
        legs = local  # remote leg is done via the saga; only local legs remain below
    for did, amt, leg in legs:
        await escrow.escrow_payout(db, did, amt, f"ctrref:{cid}:{leg}", reason="contract_settle")
    res = await db.execute(text(
        "UPDATE contract_milestones SET status='released', released_at=now() "
        "WHERE contract_id=:c AND seq=:s AND status='releasing'"), {"c": cid, "s": seq})
    flipped = getattr(res, "rowcount", 0) > 0
    if fee > 0 and flipped:
        # fee accrues once per released milestone — guarded by the released-flip so a re-drive
        # of already-released legs (rowcount 0) cannot double-count it
        await db.execute(text(
            "UPDATE contracts SET fee_charged = COALESCE(fee_charged,0) + :f, updated_at=now() WHERE id=:c"
        ), {"f": fee, "c": cid})

    remaining = (await db.execute(text(
        "SELECT COUNT(*) FROM contract_milestones WHERE contract_id=:c "
        "AND status NOT IN ('released','cancelled')"), {"c": cid})).scalar() or 0
    completed = False
    if remaining == 0:
        done = await db.execute(text(
            "UPDATE contracts SET status='completed', completed_at=now(), updated_at=now() "
            "WHERE id=:c AND status IN ('agreed','in_progress')"), {"c": cid})
        completed = getattr(done, "rowcount", 0) > 0
    # Only the driver that actually FLIPPED the milestone writes the released audit row. A losing
    # concurrent driver (e.g. the reaper re-driving the same milestone a client just released)
    # already no-ops on money — its legs dedup on the TEG rail and the fee is `flipped`-guarded —
    # but it used to leave a second `milestone_released` event, which reads like a double payment
    # in the audit trail. (2026-07-25: caught by an E2E flake, money was never at risk.)
    if flipped or completed:
        q = await next_seq(db, cid)
        await audit(db, cid, q, "milestone_released", actor_did,
                    {"seq": seq, "fee": str(fee), "legs": [[d, str(a), n] for d, a, n in legs],
                     "completed": completed, "driver": actor_did or "unknown"})
    await db.commit()

    # §NOTIFV2 forge.royalty_received — post-commit, so the legs above have actually been paid.
    # `_plan_legs` names forge-lineage legs `m{seq}:settle_roy{i}`; the head `settle` leg is the
    # payee's own money and the `settle_tpl` leg is the TEMPLATE author's royalty, which is a
    # different relationship than the forge fork lineage this type describes.
    try:
        from agentvault_registry.services import forge_royalty as _fr
        _roy = [(d, a) for d, a, n in legs if ":settle_roy" in n]
        if _roy:
            await _fr.notify_royalty_legs(
                [(payee, 0)] + _roy, source=f"contract {cid} milestone {seq}")
    except Exception:  # noqa: BLE001
        logger.debug("[NOTIFY] contract royalty notify failed", exc_info=True)

    if completed:
        await _on_completed(db, c, actor_did=actor_did, stars=stars)
    emit("ContractMilestoneReleased", cid,
         {"seq": seq, "amount": str(m["amount"]), "fee": str(fee), "by": actor_did})
    if completed:
        emit("ContractCompleted", cid, {"total": str(c["total_amount"]), "currency": c["currency"]})
    announce_release(c, seq, completed)
    # §DEALTHREADS — the terminal receipt, from THE settle choke point (v2 and
    # legacy release both drive through here; cross-frame included). Only the
    # driver that actually flipped the milestone posts — a losing re-drive
    # would dedup on client_ref anyway, but not asking twice is cleaner.
    if flipped or completed:
        from agentvault_registry.services import deal_thread_events as dte
        await dte.post_settled(db, c, seq, m["amount"], completed=completed)
    return {"released_seq": seq, "fee": str(fee), "completed": completed,
            "legs": [[d, str(a), n] for d, a, n in legs]}


def announce_release(c: dict, seq: int, completed: bool) -> None:
    """§TWOAGENT (2026-09-23): a milestone's release is its own fact, whether or not it completed the contract. It was
    either/or: the FINAL milestone sent only `contract.completed`, so for the common one-milestone contract the
    provider's owner never heard "you were paid" for it (measured on EU and ASIA, V0432, `ctr_046d2b3a…`; the ledger had
    both events). Every release now announces itself, and a completion announces itself as well."""
    webhook("contract.milestone_released", c, {"seq": seq, "completed": bool(completed)})
    if completed:
        webhook("contract.completed", {**c, "status": "completed"})


async def _on_completed(db: AsyncSession, c: dict, *, actor_did: Optional[str],
                        stars: Optional[int]) -> None:
    """Completion side-effects, all non-blocking: work-reputation fold (the Guild's signal) +
    template usage_count (real agreements metric counts at agreed; settle-rate uses completed)."""
    try:
        if c.get("provider_did") and Decimal(str(c["total_amount"])) > 0:
            from agentvault_registry.services import guild_reputation
            await guild_reputation.fold_work_reputation(
                db, c["client_did"], c.get("payee_did") or c["provider_did"],
                int(stars or 5), float(c["total_amount"]))
    except Exception as e:  # noqa: BLE001
        logger.warning("[CONTRACT] reputation fold failed for %s: %s", c["id"], e)


async def refund_remainder(db: AsyncSession, c: dict, *, leg: str) -> Decimal:
    """Refund every unreleased milestone's amount to the CLIENT in one leg. Caller claimed the
    terminal status first. Zero-total/all-released → no-op."""
    cid = c["id"]
    remainder = (await db.execute(text(
        "SELECT COALESCE(SUM(amount),0) FROM contract_milestones WHERE contract_id=:c "
        "AND status NOT IN ('released','cancelled')"), {"c": cid})).scalar() or 0
    remainder = Decimal(str(remainder))
    if remainder > 0 and c.get("escrow_ref"):
        await escrow.escrow_payout(db, c["client_did"], remainder,
                                   f"ctrref:{cid}:{leg}", reason="contract_refund")
    await db.execute(text(
        "UPDATE contract_milestones SET status='cancelled' WHERE contract_id=:c "
        "AND status NOT IN ('released','cancelled')"), {"c": cid})
    return remainder


# ── DDR ⇄ CONTRACT wiring (2026-07-25, Commander-directed) ───────────────────────────────────
# ONE settlement authority per grievance: when a dispute is linked to a spine contract, the money
# at issue is the ESCROWED REMAINDER — the escrow split IS the settlement, and the DDR's wallet
# compensation (process_compensation) must be SKIPPED, or the defendant pays twice.

def ruling_to_provider_pct(c: dict, dispute, ruling: str) -> int:
    """Map a DDR ruling onto the escrow split. The provider is the party whose payout is at
    stake; 'complainant wins' means the complainant's side of the escrow claim prevails."""
    complainant_is_client = getattr(dispute, "complainant_did", None) == c.get("client_did")
    if ruling == "IN_FAVOR_OF_COMPLAINANT":
        return 0 if complainant_is_client else 100
    if ruling == "IN_FAVOR_OF_DEFENDANT":
        return 100 if complainant_is_client else 0
    # DISMISSED: the complaint fails — the status quo (delivered work claim) stands.
    return 100 if complainant_is_client else 0


async def find_linked_contract(db: AsyncSession, dispute) -> Optional[dict]:
    """Resolve the spine contract a dispute is about: `contract_ref` (spine id) first, then the
    legacy int `contract_id` via legacy_ruc_id."""
    ref = getattr(dispute, "contract_ref", None)
    if ref:
        c = await load_contract(db, ref)
        if c:
            return c
    legacy = getattr(dispute, "contract_id", None)
    if legacy is not None:
        row = (await db.execute(text(
            "SELECT * FROM contracts WHERE legacy_ruc_id=:i"), {"i": int(legacy)})).mappings().first()
        if row:
            return dict(row)
    return None


async def settle_linked_contract_for_ruling(db: AsyncSession, dispute, ruling: str
                                            ) -> Optional[dict]:
    """Called by the DDR ruling endpoint AFTER the ruling commits. If the dispute is linked to a
    spine contract: the contract's escrow rails own the money — return a summary (caller SKIPS
    wallet compensation). Splits only when the contract is still `disputed` (claim-first; a prior
    manual /admin/contracts resolve leaves nothing to move — compensation stays skipped either
    way, that is the single-authority invariant). Returns None ⇔ no linked contract."""
    c = await find_linked_contract(db, dispute)
    if not c:
        return None
    out: dict = {"contract_id": c["id"], "escrow_is_settlement": True,
                 "contract_status": c["status"]}
    if c["status"] != "disputed":
        out["split"] = "skipped (contract not in disputed — already settled elsewhere)"
        return out
    pct = ruling_to_provider_pct(c, dispute, ruling)
    claimed = await db.execute(text(
        "UPDATE contracts SET status='completed', completed_at=now(), updated_at=now() "
        "WHERE id=:c AND status='disputed'"), {"c": c["id"]})
    if getattr(claimed, "rowcount", 0) == 0:
        out["split"] = "skipped (lost the claim race)"
        return out
    await audit(db, c["id"], await next_seq(db, c["id"]), "resolving",
                f"ddr:{getattr(dispute, 'id', '?')}", {"ruling": ruling, "provider_pct": pct})
    await db.commit()
    split = await resolve_split(db, c, pct, actor=f"ddr_ruling:{getattr(dispute, 'id', '?')}")
    webhook("contract.completed", {**c, "status": "completed"},
            {"resolution": split, "via": "ddr_ruling", "ruling": ruling})
    out.update({"split": split, "provider_pct": pct})
    logger.info("[CONTRACT] DDR ruling %s on dispute %s settled linked contract %s (pct=%s)",
                ruling, getattr(dispute, "id", "?"), c["id"], pct)
    return out


async def close_linked_dispute(db: AsyncSession, c: dict, provider_pct: int, *, actor: str) -> Optional[str]:
    """Called by the CONTRACT admin resolve AFTER its split. Closes the linked DDR with the
    ruling the split implies (reputation folds ride the crud; wallet compensation is NEVER run
    from here — the split already settled the money). Non-blocking; idempotent via D6."""
    did_ = c.get("dispute_id")
    if not did_:
        return None
    try:
        from agentvault_registry.crud import crud_disputes
        complainant_is_client = None
        d = await crud_disputes.get_dispute_by_id(db, int(did_))
        if not d or getattr(d, "status", "") == "CLOSED":
            return None
        complainant_is_client = d.complainant_did == c.get("client_did")
        if provider_pct == 0:
            ruling = "IN_FAVOR_OF_COMPLAINANT" if complainant_is_client else "IN_FAVOR_OF_DEFENDANT"
        elif provider_pct == 100:
            ruling = "IN_FAVOR_OF_DEFENDANT" if complainant_is_client else "IN_FAVOR_OF_COMPLAINANT"
        else:
            ruling = "DISMISSED"   # a split has no clear winner; the audit trail carries the pct
        await crud_disputes.update_dispute_ruling(db, int(did_), ruling)
        logger.info("[CONTRACT] %s resolve closed linked DDR %s as %s (pct=%s)",
                    c["id"], did_, ruling, provider_pct)
        return ruling
    except Exception as e:  # noqa: BLE001 — closing the dispute must never block a settlement
        logger.warning("[CONTRACT] linked-DDR close failed for %s (dispute %s): %s",
                       c["id"], did_, e)
        return None


async def resolve_split(db: AsyncSession, c: dict, provider_pct: int, *,
                        actor: str) -> dict:
    """Admin dispute resolution: split the UNRELEASED remainder provider/client (guild resolve
    twin). Caller claimed disputed→(resolving) first. Legs: resolve_provider / resolve_client."""
    cid = c["id"]
    remainder = (await db.execute(text(
        "SELECT COALESCE(SUM(amount),0) FROM contract_milestones WHERE contract_id=:c "
        "AND status NOT IN ('released','cancelled')"), {"c": cid})).scalar() or 0
    remainder = Decimal(str(remainder))
    prov_amt = (remainder * Decimal(max(0, min(100, provider_pct))) / Decimal(100)).quantize(_Q)
    cli_amt = remainder - prov_amt
    payee = c.get("payee_did") or c.get("provider_did")
    if c.get("escrow_ref") and remainder > 0:
        if prov_amt > 0 and payee:
            await escrow.escrow_payout(db, payee, prov_amt,
                                       f"ctrref:{cid}:resolve_provider", reason="contract_settle")
        if cli_amt > 0:
            await escrow.escrow_payout(db, c["client_did"], cli_amt,
                                       f"ctrref:{cid}:resolve_client", reason="contract_refund")
    await db.execute(text(
        "UPDATE contract_milestones SET status='cancelled' WHERE contract_id=:c "
        "AND status NOT IN ('released','cancelled')"), {"c": cid})
    q = await next_seq(db, cid)
    await audit(db, cid, q, "resolved", actor,
                {"provider_pct": provider_pct, "provider_amt": str(prov_amt), "client_amt": str(cli_amt)})
    await db.commit()
    emit("ContractResolved", cid, {"provider_pct": provider_pct, "by": actor})
    return {"provider_amt": str(prov_amt), "client_amt": str(cli_amt)}
