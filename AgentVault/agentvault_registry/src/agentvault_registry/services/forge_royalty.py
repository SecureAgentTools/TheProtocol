"""GÖDEL FORGE — Δ-neutral fork-royalty carve (2026-07-19).

When a variant earns (eval pay-per-suite, or a Guild eval_bounty settle), a slice flows UP its
bundle fork lineage to the organizations that authored the ancestor variants it was forked from —
so publishing a strong improvement makes your lineage an annuity, and hoarding loses to sharing.

Δ=0 BY CONSTRUCTION (the AGORA maker-rebate pattern): the carve only re-partitions a payout that
was going to be made anyway. ``compute_legs`` returns a list of (recipient_did, Decimal) whose
amounts SUM EXACTLY to the base — the earner's leg is `base − Σ(ancestor shares)`, so however the
caller funds the legs (all from the same treasury source, via the existing reward waterfall), the
total leaving the treasury is unchanged and the supply invariant cannot move. Fork edges ONLY (never
spawn edges); nearest ROYALTY_MAX_DEPTH ancestors; per-child ``royalty_bps`` (cap 500). Idempotent
is the caller's responsibility (reference ``roy-{ref}:{n}``). Gated by FORGE_ROYALTY_ENABLED — off ⇒
one undivided leg to the earner (today's behavior, byte-equivalent).
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..forge_flags import royalty_enabled, ROYALTY_MAX_BPS, ROYALTY_MAX_DEPTH

logger = logging.getLogger(__name__)

Leg = Tuple[str, Decimal]


async def _earner_org(db: AsyncSession, earner_did: str) -> Optional[str]:
    row = (await db.execute(text(
        "SELECT organization_id FROM agents WHERE did = :d LIMIT 1"
    ), {"d": earner_did})).first()
    return str(row[0]) if row and row[0] is not None else None


async def _champion_bundle(db: AsyncSession, org_id: str) -> Optional[dict]:
    """The org's representative (most-recent) bundle — the lineage's fork node."""
    row = (await db.execute(text(
        "SELECT id, forked_from_bundle_id, COALESCE(royalty_bps, 0) "
        "FROM agent_bundles WHERE source_org_id = CAST(:o AS UUID) "
        "ORDER BY created_at DESC LIMIT 1"
    ), {"o": org_id})).first()
    if not row:
        return None
    return {"id": str(row[0]), "forked_from": (str(row[1]) if row[1] else None), "royalty_bps": int(row[2] or 0)}


async def _bundle(db: AsyncSession, bundle_id: str) -> Optional[dict]:
    row = (await db.execute(text(
        "SELECT id, forked_from_bundle_id, COALESCE(royalty_bps,0), source_org_id "
        "FROM agent_bundles WHERE id = CAST(:b AS UUID) LIMIT 1"
    ), {"b": bundle_id})).first()
    if not row:
        return None
    return {"id": str(row[0]), "forked_from": (str(row[1]) if row[1] else None),
            "royalty_bps": int(row[2] or 0), "org_id": (str(row[3]) if row[3] else None)}


async def _org_treasury_did(db: AsyncSession, org_id: str) -> Optional[str]:
    """§ORGTREASURY (Track C): the ONE resolver. Previously this was a private copy of the
    listing query with LIMIT 1 and no ORDER BY — nondeterministic for a multi-listing org, and
    blind to the org-level treasury. The resolver compares organization_id as text, which this
    site needs (exchange_listings.organization_id is VARCHAR; agent_bundles.source_org_id is UUID)."""
    from agentvault_registry.services.org_treasury import resolve_org_treasury_did
    return await resolve_org_treasury_did(db, org_id)


async def notify_royalty_legs(legs: List[Leg], *, source: str) -> None:
    """§NOTIFV2 forge.royalty_received — tell ancestor lineage holders they were paid.

    `compute_legs` only COMPUTES the carve; three different callers then move the money
    (routers/guild.py settle, background_tasks/eval_runner.py eval-pay, services/
    contract_settlement.py). There is therefore no post-payment choke point to wire, so this
    helper exists instead and every caller invokes it AFTER its payout loop — never before, so a
    failed payout can't phantom-notify.

    `legs[0]` is the earner's own head leg (that is the compute_legs contract) and is skipped:
    this type is about receiving a royalty from someone else's work, not about being paid for
    your own. Best-effort and silent on failure; a royalty is already recorded on the ledger.
    """
    try:
        if not legs or len(legs) < 2:
            return
        import asyncio as _aio_n
        from agentvault_registry.background_tasks.push_notify import notify_agent_owners
        for rdid, amt in legs[1:]:
            try:
                famt = float(amt)
            except (TypeError, ValueError):
                continue
            if famt <= 0 or not rdid:
                continue
            _aio_n.create_task(notify_agent_owners(
                "forge.royalty_received", [rdid],
                title="Royalty received",
                message=f"{famt:.4f} royalty from {source}.",
                amount=famt, tags="moneybag", priority="default",
                click="/ui/#/forge"))
    except Exception:  # noqa: BLE001
        logger.debug("[NOTIFY] forge.royalty_received emit failed", exc_info=True)


async def compute_legs(db: AsyncSession, base_amount, earner_did: str) -> List[Leg]:
    """Return payout legs summing EXACTLY to ``base_amount``. Off/no-lineage → [(earner, base)].

    Walks the earner's champion-bundle fork chain up to ROYALTY_MAX_DEPTH; at each hop the CHILD's
    ``royalty_bps`` (capped) carves a share to the PARENT bundle's org treasury. Shares that can't
    be routed (no ancestor org treasury, or self-referential) fold back into the earner's leg, so
    the sum is invariant."""
    base = Decimal(str(base_amount))
    if not royalty_enabled() or base <= 0:
        return [(earner_did, base)]
    try:
        org = await _earner_org(db, earner_did)
        if not org:
            return [(earner_did, base)]
        champ = await _champion_bundle(db, org)
        if not champ or not champ.get("forked_from"):
            return [(earner_did, base)]
        shares: dict[str, Decimal] = {}
        cur = champ
        seen_bundles: set[str] = {champ["id"]}
        for _ in range(ROYALTY_MAX_DEPTH):
            parent_id = cur.get("forked_from")
            if not parent_id or parent_id in seen_bundles:
                break
            seen_bundles.add(parent_id)
            bps = max(0, min(ROYALTY_MAX_BPS, int(cur.get("royalty_bps", 0))))
            parent = await _bundle(db, parent_id)
            if parent is None:
                break
            # Intra-org hops DO carve (batch-3): the lineage org's treasury is the royalty sink —
            # a descendant earning pays the lineage's shareholders (e.g. $FORGE holders), which
            # is the arena's economic loop, not a self-payment (earner-as-payee is still barred).
            if bps > 0 and parent.get("org_id"):
                tdid = await _org_treasury_did(db, parent["org_id"])
                if tdid and tdid != earner_did:
                    share = (base * Decimal(bps) / Decimal(10000)).quantize(Decimal("0.000000000000000001"))
                    if share > 0:
                        shares[tdid] = shares.get(tdid, Decimal(0)) + share
            cur = parent
        total_share = sum(shares.values(), Decimal(0))
        if total_share <= 0 or total_share >= base:
            return [(earner_did, base)]  # nothing routable, or would over-carve → pay earner in full
        legs: List[Leg] = [(earner_did, base - total_share)]
        legs.extend((did, amt) for did, amt in shares.items())
        # Invariant guard: legs MUST sum to base (Δ=0). If drift, collapse to a single leg.
        if sum((a for _, a in legs), Decimal(0)) != base:
            logger.error("[FORGE] royalty leg sum drift (earner=%s) — paying in full", earner_did)
            return [(earner_did, base)]
        return legs
    except Exception as e:  # noqa: BLE001
        logger.warning("[FORGE] royalty carve failed for %s: %s — paying in full", earner_did, e)
        return [(earner_did, base)]
