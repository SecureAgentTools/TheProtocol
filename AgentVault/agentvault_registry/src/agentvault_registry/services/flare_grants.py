"""THE flare-grant writer (§FLARESHOP, 2026-08-16).

Before this module there was exactly one way to receive a cosmetic flare: pay
euros through the Stripe on-ramp. The grant logic lived inside
``routers/fiat_onramp.py`` as ``_grant_flare`` + a tier/rank table. §FLARESHOP
adds a SECOND origination surface (buy the same tier with the frame's own
currency, ``routers/flare_shop.py``) — and a second copy of the grant logic
would be the §FANOUTFIX class: two writers that agree today and drift the first
time one of them learns something (the Founder cap, the dual-slot bearer
invariant, the flare_id-once rule).

So the tier tables and the writer live HERE, once, and both origination
surfaces call in. ``fiat_onramp`` keeps its fiat-only concerns (the cumulative
Shadow Chancellor evaluation reads FiatPurchase rows, which local-currency
purchases must never touch) and delegates the grant itself.

Cosmetic only: this module moves NO value and emits no ledger event. Whatever
paid for the grant (euros or local currency) is settled by the caller BEFORE
it calls in, on the existing rails. Δ is unaffected by construction.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import List, Optional

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Agent, Developer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier tables — the single definition. `fiat_onramp` imports these; do not copy.
# ---------------------------------------------------------------------------
# Fiat tier labels map onto the three purchasable cosmetic flares.
TIER_TO_FLARE = {
    "tier_1_base":    "sentinel",
    "tier_2_value":   "architect",
    "tier_3_premium": "founder",
}

# Rank decides upgrades: a grant NEVER downgrades an existing flare.
#   sentinel < architect < founder < shadow_chancellor < operator < commander
# shadow_chancellor sits above founder (the fiat lane reaches it by cumulative
# spend; the local-currency shop sells it outright — it is the key that unlocks
# the 37 encirclement variants + 21 broken-machine overlays).
# operator/commander stay above so admin-granted badges survive any purchase.
FLARE_RANK = {
    "sentinel":          1,
    "architect":         2,
    "founder":           3,
    "shadow_chancellor": 4,
    "operator":         50,
    "commander":        99,
}

ALL_FLARE_TIERS = frozenset(FLARE_RANK.keys())

# Never purchasable on ANY lane — admin grant only.
ADMIN_ONLY_FLARE_TIERS = frozenset({"operator", "commander"})

# Purchasable through an origination surface (fiat or local currency).
PURCHASABLE_FLARE_TIERS = ("sentinel", "architect", "founder", "shadow_chancellor")

# The encirclement + overlay catalogs are gated behind exactly one tier today.
ENCIRCLEMENT_UNLOCK_TIER = "shadow_chancellor"

# Founder is capped at 100 bearers, forever (2026-05-10). An over-cap grant
# falls back to architect rather than failing — the buyer always gets a flare.
FOUNDER_CAP = 100


def flare_for_tier(tier_label: str) -> Optional[str]:
    """Map a FIAT tier label (tier_1_base…) to its flare name."""
    return TIER_TO_FLARE.get(tier_label)


def should_overwrite_flare(existing: Optional[str], proposed: Optional[str]) -> bool:
    """Higher-rank flare overwrites lower; equal/lower never overwrites."""
    if not proposed:
        return False
    if not existing:
        return True
    return FLARE_RANK.get(proposed, 0) > FLARE_RANK.get(existing, 0)


def corner_flares_unlocked_by(tier: Optional[str]) -> List[str]:
    """Corner-slot options a bearer of `tier` may wear (rank cascade).

    Pure tier-level answer, for catalog display ("what does this tier light
    up?"). The per-Developer readers in fiat_onramp additionally honour admin
    flags (§20.1) and stay where they are — this never replaces them.
    shadow_chancellor is encirclement-only and is never a corner option.
    """
    if not tier:
        return []
    rank = FLARE_RANK.get(tier, 0)
    corners = [
        name for name, r in FLARE_RANK.items()
        if name != ENCIRCLEMENT_UNLOCK_TIER and r <= rank
    ]
    corners.sort(key=lambda t: FLARE_RANK.get(t, 0))
    return corners


def unlocks_encirclements(tier: Optional[str]) -> bool:
    """Does holding `tier` unlock the encirclement + overlay catalogs?"""
    return tier == ENCIRCLEMENT_UNLOCK_TIER


async def grant_flare_tier(
    db: AsyncSession,
    *,
    developer_id: Optional[int],
    target_agent_did: Optional[str],
    proposed: str,
    source_kind: str,
    source_id: str,
    commit: bool = True,
) -> dict:
    """Grant `proposed` on the developer profile and (optionally) one agent.

    Extracted verbatim in behaviour from ``fiat_onramp._grant_flare`` so the
    fiat lane keeps its semantics exactly:
      * Profile flare -> developer.flare_tier (permanent, higher-wins).
      * Agent flare   -> agents[target].flare_tier (movable, higher-wins).
      * Both stamp granted_at + source_purchase_id for audit.
      * flare_id (UUID) minted on FIRST grant only, preserved across upgrades.
      * Founder cap 100 -> architect fallback.
      * Dual-slot bearer invariant: the target agent takes both slots and any
        sibling agent of the same developer is cleared (<=1 bearer per slot).

    PROVENANCE, and why it is not what you would first write:
    `{developers,agents}.flare_source_purchase_id` is varchar(36) AND carries a
    DB-level FOREIGN KEY into `fiat_purchases(id)` (fk_developers_flare_source_
    purchase / fk_agents_flare_source_purchase, ON DELETE SET NULL). The column
    does not mean "what caused this flare" — it means "the EURO purchase that
    caused this flare". So a local-currency grant must leave it alone: a
    decorated "lane:uuid" stamp does not even fit the width, and any non-fiat id
    violates the FK — both discovered by the #202 battery firing against real
    money, which is exactly what a battery is for.
    Non-fiat lanes therefore record provenance in their OWN receipt table
    (flare_shop_purchases holds developer_id, tier, price, tx and timestamps).
    `source_kind`/`source_id` are still logged, so the grant is traceable in the
    journal regardless of lane.

    Idempotent by rank: re-running with the same tier changes nothing. Returns
    what actually happened so callers can report honestly.
    """
    result = {
        "requested": proposed,
        "granted": None,
        "developer_updated": False,
        "agent_updated": False,
        "founder_cap_fallback": False,
    }
    if not proposed:
        return result

    # Founder hard cap — counted on Developer.flare_tier (one person buying
    # three times is still one founder). Best-effort soft serialization.
    if proposed == "founder":
        cap_q = await db.execute(
            select(sa.func.count()).select_from(Developer).where(Developer.flare_tier == "founder")
        )
        current_founder_count = int(cap_q.scalar() or 0)
        if current_founder_count >= FOUNDER_CAP:
            logger.warning(
                "[flare_grant] Founder slots full (%s/%s) — granting Architect instead (%s:%s)",
                current_founder_count, FOUNDER_CAP, source_kind, source_id,
            )
            proposed = "architect"
            result["founder_cap_fallback"] = True

    result["granted"] = proposed
    now = datetime.now(timezone.utc)
    # FK into fiat_purchases: only the euro lane may write this column.
    is_fiat = source_kind == "fiat"
    logger.info("[flare_grant] %s -> %s (source %s:%s, dev=%s agent=%s)",
                result["requested"], proposed, source_kind, source_id, developer_id, target_agent_did)

    # ---- profile flare
    if developer_id is not None:
        dev_row = await db.execute(select(Developer).where(Developer.id == developer_id))
        dev = dev_row.scalar_one_or_none()
        if dev and should_overwrite_flare(dev.flare_tier, proposed):
            dev.flare_tier = proposed
            dev.flare_granted_at = now
            if is_fiat:
                dev.flare_source_purchase_id = source_id
            if not dev.flare_id:
                dev.flare_id = str(_uuid.uuid4())
            # Light the corner slot immediately for corner-class tiers; the
            # encirclement slot is set by the encirclement path (rank 4).
            if proposed in ("sentinel", "architect", "founder", "operator", "commander"):
                dev.selected_corner_flare = proposed
            elif proposed == ENCIRCLEMENT_UNLOCK_TIER and not dev.selected_encirclement_flare:
                dev.selected_encirclement_flare = ENCIRCLEMENT_UNLOCK_TIER
            db.add(dev)
            result["developer_updated"] = True

    # ---- agent flare
    if target_agent_did:
        agent_row = await db.execute(select(Agent).where(Agent.did == target_agent_did))
        agent = agent_row.scalar_one_or_none()
        if agent and should_overwrite_flare(agent.flare_tier, proposed):
            agent.flare_tier = proposed
            agent.flare_granted_at = now
            if is_fiat:
                agent.flare_source_purchase_id = source_id
            if developer_id is not None:
                await db.execute(
                    sa.update(Agent)
                    .where(
                        Agent.creator_developer_id == developer_id,
                        Agent.did != target_agent_did,
                        sa.or_(
                            Agent.bears_corner_flare.is_(True),
                            Agent.bears_encirclement_flare.is_(True),
                        ),
                    )
                    .values(bears_corner_flare=False, bears_encirclement_flare=False)
                )
            agent.bears_corner_flare = True
            agent.bears_encirclement_flare = True
            db.add(agent)
            result["agent_updated"] = True

    if commit:
        await db.commit()
    return result
