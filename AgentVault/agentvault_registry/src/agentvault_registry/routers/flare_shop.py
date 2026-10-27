"""§FLARESHOP (2026-08-16) — buy a cosmetic flare with the FRAME's own currency.

The problem this closes, in the Commander's words: "if fiat onramp is off we
have no way to distribute them properly". Every frame runs with
FIAT_ONRAMP_ENABLED=false, so the euro lane — the only way to obtain a cosmetic
flare, and with `shadow_chancellor` the only key to the 37 encirclement variants
and 21 broken-machine overlays — is shut. This router opens a second lane that
needs no payment processor at all: the buyer's own agent pays the registry in
AVT / JDAY / BVT.

Design constraints it holds to, all pre-existing doctrine:

  * ONE grant writer. The rows are written by `services/flare_grants`, shared
    with the fiat lane. This module never touches a flare column itself.
  * ONE money shape. The debit is the `_pay_for_template` treasury branch
    (agent_cicd_service.py): buyer agent -> system treasury on the fee-free
    admin rail, exactly-once via a durable Idempotency-Key claimed inside the
    money transaction. No new TEG endpoint, no escrow, no fee, no mint.
    Δ-neutral by construction: in-circulation to in-circulation.
  * TIERS, not per-item entitlements. The unlock model is already
    tier-wholesale (shadow_chancellor unlocks the whole encirclement catalog,
    corner tiers cascade by rank), so the shop sells the SAME four tiers the
    fiat lane grants and the existing selection machinery does the rest.
  * Byte-inert when off. FLARE_LOCAL_PURCHASE_ENABLED defaults false; the
    purchase endpoint 503s exactly like the fiat lane's `_fiat_enabled` gate,
    and the catalog still renders (as a gallery) so an operator can see what
    enabling it would offer.

What it deliberately does NOT sell: earned marks. Track-record rings, verified
job counts and stars come from the registry's own ledger and are not obtainable
here or anywhere else for money. The catalog says so in as many words.
"""
from __future__ import annotations

import logging
import os
import uuid as _uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

import httpx
import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Security, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..es_ssl_helper import get_httpx_verify
from ..models import Agent, Developer, FlareShopPurchase
from ..security import get_current_developer_unified
from ..services import flare_grants
from ..core.registry_identity import (
    FLARE_CORNER_VARIANTS,
    FLARE_ENCIRCLEMENT_OVERLAYS,
    FLARE_ENCIRCLEMENT_VARIANTS,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/flare-shop", tags=["Flare Shop"])

# ---------------------------------------------------------------------------
# Env gates
# ---------------------------------------------------------------------------
# Default FALSE: on a registry that never sets it, every endpoint below behaves
# exactly as it did before this module existed (catalog says disabled, purchase
# 503s). Operators opt in.
def _shop_enabled() -> bool:
    return (os.getenv("FLARE_LOCAL_PURCHASE_ENABLED", "false") or "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _local_currency() -> str:
    """This frame's settlement currency — same single source of truth as the FX
    desk and the registry card builder (FRAME_CURRENCY env). A/B=AVT, C=BVT."""
    return (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"


# Prices in LOCAL units, overridable per registry with FLARE_SHOP_PRICES (JSON).
# Defaults are deliberately reachable: the genesis grant a new developer's first
# agent receives already covers the entry rung, so the lane is not decorative on
# a registry that turns it on.
_DEFAULT_PRICES = {
    "sentinel": Decimal("500"),
    "architect": Decimal("2500"),
    "founder": Decimal("10000"),
    "shadow_chancellor": Decimal("25000"),
}


def _prices() -> dict:
    """Resolved price table. A malformed override is IGNORED with a loud log —
    a typo in an env var must not price a flare at zero."""
    raw = (os.getenv("FLARE_SHOP_PRICES", "") or "").strip()
    prices = dict(_DEFAULT_PRICES)
    if not raw:
        return prices
    try:
        import json as _json
        parsed = _json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("not an object")
        for tier, amount in parsed.items():
            if tier not in _DEFAULT_PRICES:
                logger.warning("[flareshop] FLARE_SHOP_PRICES: unknown tier %r ignored", tier)
                continue
            value = Decimal(str(amount))
            if value <= 0:
                logger.warning("[flareshop] FLARE_SHOP_PRICES: non-positive price for %r ignored", tier)
                continue
            prices[tier] = value
    except (ValueError, TypeError, ArithmeticError, InvalidOperation) as e:
        logger.error("[flareshop] FLARE_SHOP_PRICES is malformed (%s) — using defaults", e)
        return dict(_DEFAULT_PRICES)
    return prices


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class FlarePurchaseRequest(BaseModel):
    tier: str = Field(..., description="sentinel | architect | founder | shadow_chancellor")
    buyer_agent_did: str = Field(..., description="DID of YOUR agent that pays. Developers hold no balance.")
    target_agent_did: Optional[str] = Field(
        None, description="Agent that wears the flare. Defaults to the buyer.")


def _tier_copy(tier: str, currency: str) -> dict:
    """What each tier actually lights up, in plain words. Kept server-side so
    the shop view and any future surface (MCP, operator console) tell the same
    story from one place."""
    corners = flare_grants.corner_flares_unlocked_by(tier)
    encircle = flare_grants.unlocks_encirclements(tier)
    return {
        "tier": tier,
        "rank": flare_grants.FLARE_RANK.get(tier, 0),
        "unlocks_corner_flares": corners,
        "unlocks_encirclements": encircle,
        "encirclement_variant_count": len(FLARE_ENCIRCLEMENT_VARIANTS) if encircle else 0,
        "overlay_count": len(FLARE_ENCIRCLEMENT_OVERLAYS) if encircle else 0,
        "currency": currency,
    }


async def _founder_tier_full(db: AsyncSession) -> bool:
    """§DOCSFIX D6-396: are all founder flares taken? Counted as the grant writer counts them (developers bearing
    founder; flare_grants.grant_flare_tier), so the purchase and the grant agree."""
    cap_q = await db.execute(
        select(sa.func.count()).select_from(Developer).where(Developer.flare_tier == "founder")
    )
    return int(cap_q.scalar() or 0) >= flare_grants.FOUNDER_CAP


# ---------------------------------------------------------------------------
# GET /catalog — public
# ---------------------------------------------------------------------------
@router.get("/catalog")
async def flare_shop_catalog(
    db: AsyncSession = Depends(get_db),
):
    """The shop window. PUBLIC and always answers 200, even with the lane
    disabled, so a visitor (and an operator deciding whether to enable it) can
    see the whole catalog. `enabled` is the honest signal the UI gates on."""
    currency = _local_currency()
    prices = _prices()
    enabled = _shop_enabled()

    founder_taken = 0
    try:
        cap_q = await db.execute(
            select(sa.func.count()).select_from(Developer).where(Developer.flare_tier == "founder")
        )
        founder_taken = int(cap_q.scalar() or 0)
    except Exception as e:  # noqa: BLE001 — a catalog must never 500 on a count
        logger.warning("[flareshop] founder count unavailable: %s", e)

    return {
        "enabled": enabled,
        "currency": currency,
        "tiers": [
            {
                **_tier_copy(tier, currency),
                "price": str(prices[tier]),
                # Founder is capped at 100 bearers forever; over the cap the
                # grant falls back to architect (the buyer is told up front).
                "capped": tier == "founder",
                "cap_total": flare_grants.FOUNDER_CAP if tier == "founder" else None,
                "cap_taken": founder_taken if tier == "founder" else None,
                "cap_full": (tier == "founder" and founder_taken >= flare_grants.FOUNDER_CAP),
            }
            for tier in flare_grants.PURCHASABLE_FLARE_TIERS
        ],
        "encirclement_variants": sorted(FLARE_ENCIRCLEMENT_VARIANTS),
        "encirclement_overlays": sorted(FLARE_ENCIRCLEMENT_OVERLAYS),
        "corner_variants": sorted(FLARE_CORNER_VARIANTS),
        "encirclement_unlock_tier": flare_grants.ENCIRCLEMENT_UNLOCK_TIER,
        # The line that cannot move (post 37's thesis, and a product rule):
        # cosmetics are for sale, earned marks are not.
        "earned_marks_notice": (
            "Cosmetic flares only. Track-record marks (verified jobs, stars, "
            "cross-registry orbits) are earned on this registry's ledger and "
            "cannot be purchased here or anywhere else."
        ),
    }


# ---------------------------------------------------------------------------
# POST /purchase — developer JWT
# ---------------------------------------------------------------------------
@router.post("/purchase", status_code=status.HTTP_201_CREATED)
async def purchase_flare(
    body: FlarePurchaseRequest,
    db: AsyncSession = Depends(get_db),
    current_dev: Developer = Security(get_current_developer_unified),
):
    """Buy `tier` for this frame's currency, paid by one of your own agents.

    Order of operations is deliberate and survives a crash at any point:
      1. validate (tier purchasable, agents owned, not already outranked)
      2. INSERT the row as `pending`  <- never "paid but unrecorded"
      3. debit on the existing fee-free treasury rail with Idempotency-Key
         `flareshop-{row id}`  <- exactly-once, replay-safe
      4. mark `completed` + grant through the shared writer
    A failure at (3) marks the row `failed` and grants nothing; a retry is a NEW
    row with a NEW key, so a declined attempt can never be replayed into a grant.
    """
    if not _shop_enabled():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Local-currency flare purchases are not enabled on this registry.",
        )

    tier = (body.tier or "").strip().lower()
    if tier not in flare_grants.PURCHASABLE_FLARE_TIERS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown or non-purchasable tier {body.tier!r}. "
            f"Purchasable: {', '.join(flare_grants.PURCHASABLE_FLARE_TIERS)}.",
        )
    if tier in flare_grants.ADMIN_ONLY_FLARE_TIERS:  # defence in depth
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That flare is admin-granted only.")

    prices = _prices()
    price = prices[tier]
    currency = _local_currency()

    # ---- buyer agent must belong to the caller (developers hold no balance)
    buyer_q = await db.execute(select(Agent).where(Agent.did == body.buyer_agent_did))
    buyer = buyer_q.scalar_one_or_none()
    if not buyer:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Agent {body.buyer_agent_did} not found")
    if buyer.creator_developer_id != current_dev.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "The paying agent must be one of your own agents.",
        )
    if (buyer.status or "").lower() != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "The paying agent is not active.")

    target_did = (body.target_agent_did or body.buyer_agent_did).strip()
    if target_did != buyer.did:
        tgt_q = await db.execute(select(Agent).where(Agent.did == target_did))
        target = tgt_q.scalar_one_or_none()
        if not target:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Agent {target_did} not found")
        if target.creator_developer_id != current_dev.id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "The agent that wears the flare must be one of your own agents.",
            )

    # ---- 2. RESUME a stranded purchase, else refuse-if-pointless, else new row
    #
    # A crash (or a bug) between the debit and the grant leaves a `pending` row
    # whose money has ALREADY moved. Creating a fresh row on the next attempt
    # would mint a fresh Idempotency-Key and charge the buyer a second time for
    # a flare they already paid for. So a matching pending row is RESUMED
    # instead: the same key replays against the TEG, which returns the cached
    # result and moves nothing, and the grant then completes. This is what made
    # "write the row before the money" worth doing.
    #
    # The lookup runs BEFORE the already-outranked refusal on purpose. If the
    # grant half succeeded and only the row write failed, the buyer holds the
    # tier AND a pending row; refusing with "nothing was charged" would then be
    # a lie, and the row would stay pending forever. Resuming settles it (the
    # grant itself is a no-op by rank, which is exactly right).
    resumed_q = await db.execute(
        select(FlareShopPurchase)
        .where(
            FlareShopPurchase.developer_id == current_dev.id,
            FlareShopPurchase.buyer_agent_did == buyer.did,
            FlareShopPurchase.tier == tier,
            FlareShopPurchase.status == "pending",
        )
        .order_by(FlareShopPurchase.created_at.asc())
        .limit(1)
    )
    row = resumed_q.scalar_one_or_none()
    resumed = row is not None
    if resumed:
        # honour the caller's current target choice; everything else is the
        # stranded row's, above all its id (which IS the idempotency key).
        row.target_agent_did = target_did
        db.add(row)
        await db.commit()
        logger.info("[flareshop] resuming stranded pending purchase %s (%s, %s)",
                    row.id, tier, buyer.did)
    elif not flare_grants.should_overwrite_flare(current_dev.flare_tier, tier):
        # Nothing stranded to settle and the tier would convey nothing: refuse
        # BEFORE any money moves. This message can honestly say "not charged".
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Your profile already carries {current_dev.flare_tier!r}, which ranks at or "
            f"above {tier!r}. Buying it would grant nothing, so nothing was charged.",
        )
    elif tier == "founder" and await _founder_tier_full(db):
        # §DOCSFIX D6-396: past the cap the grant writer gives architect, so a founder purchase would be charged the
        # founder price for an architect flare; refuse it BEFORE any money moves, as the catalog's cap_full says
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"All {flare_grants.FOUNDER_CAP} founder flares are taken, so a founder purchase would grant "
            f"architect. Nothing was charged; buy architect instead.",
        )
    else:
        row = FlareShopPurchase(
            id=str(_uuid.uuid4()),
            developer_id=current_dev.id,
            buyer_agent_did=buyer.did,
            target_agent_did=target_did,
            tier=tier,
            price=price,
            currency=currency,
            status="pending",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

    # ---- 3. money leg: buyer agent -> system treasury, fee-free, exactly-once
    tx_id, post_balance = await _charge_buyer(
        buyer=buyer, amount=price, purchase_id=row.id, tier=tier, db=db, row=row)

    # ---- 4. complete + grant (the shared writer, never a local copy)
    grant = await flare_grants.grant_flare_tier(
        db,
        developer_id=current_dev.id,
        target_agent_did=target_did,
        proposed=tier,
        source_kind="flareshop",
        source_id=row.id,
    )
    row.status = "completed"
    row.teg_tx_id = tx_id
    row.completed_at = datetime.now(timezone.utc)
    db.add(row)
    # Cache sync, never a source of truth: the TEG is the book of record and its
    # post-debit figure is what we mirror. Failure here must not fail a paid,
    # granted purchase, so it is best-effort and logged.
    if post_balance is not None:
        try:
            buyer_row = await db.execute(select(Agent).where(Agent.did == buyer.did))
            ba = buyer_row.scalar_one_or_none()
            if ba is not None:
                ba.liquid_balance = Decimal(str(post_balance))
                db.add(ba)
        except Exception as e:  # noqa: BLE001
            logger.error("[flareshop] cached balance sync failed for %s: %s", buyer.did, e)
    await db.commit()

    logger.info(
        "[flareshop] %s bought %s for %s %s (buyer=%s target=%s tx=%s granted=%s)",
        current_dev.email, tier, price, currency, buyer.did, target_did, tx_id, grant.get("granted"),
    )
    return {
        "purchase_id": row.id,
        "resumed": resumed,
        "tier": tier,
        "granted": grant.get("granted"),
        "founder_cap_fallback": grant.get("founder_cap_fallback", False),
        "price": str(price),
        "currency": currency,
        "transaction_id": tx_id,
        "buyer_agent_did": buyer.did,
        "target_agent_did": target_did,
        "unlocks": _tier_copy(grant.get("granted") or tier, currency),
    }


async def _charge_buyer(*, buyer: Agent, amount: Decimal, purchase_id: str, tier: str,
                        db: AsyncSession, row: FlareShopPurchase) -> tuple:
    """Debit the buyer agent into the system treasury on the fee-free admin rail.

    Cloned in shape from `agent_cicd_service._pay_for_template`'s registry-sold
    branch (the guild escrow-deposit pattern), including the durable
    Idempotency-Key claimed inside the TEG's money transaction. On any decline
    the pending row is marked `failed` and 402 is returned — the caller is never
    charged without a completed row, and never granted without a charge."""
    from agentvault_registry.routers.teg_integration import (
        TEG_API_BASE_URL, TEG_API_V1_PREFIX, TEG_ADMIN_API_KEY,
    )
    idem = f"flareshop-{purchase_id}"

    async def _fail(reason: str, code: int, detail: str, headers=None):
        row.status = "failed"
        row.failure_reason = reason[:500]
        db.add(row)
        await db.commit()
        raise HTTPException(status_code=code, detail=detail, headers=headers)

    try:
        async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
            resp = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/admin/treasury/receive",
                json={
                    "source_agent_id": buyer.did,
                    "amount": str(amount),
                    "reason": "flare_shop",
                    "reference_id": f"flareshop:{purchase_id}",
                },
                headers={"Authorization": f"Bearer {TEG_ADMIN_API_KEY}", "Idempotency-Key": idem},
                timeout=20.0,
            )
    except httpx.RequestError as e:
        logger.error("[flareshop] TEG unreachable for purchase %s: %s", purchase_id, e)
        await _fail(f"ledger_unreachable: {e}", 502,
                    "Flare purchase failed: ledger unreachable. You were not charged, retry.")

    if resp.status_code not in (200, 201):
        # §LEDGERGATE (V0598): the TEG's ledger gate refused the charge (nothing moved): 503, the sentence, Retry-After,
        # never 402 (the buyer's purse is not the reason)
        from agentvault_registry.services.ledger_unavailable import ledger_refusal
        _refusal = ledger_refusal(resp)
        if _refusal is not None:
            await _fail("ledger_unavailable", 503, _refusal.detail, headers=_refusal.headers)
        try:
            detail = resp.json().get("detail") or resp.json().get("message") or resp.text[:160]
        except Exception:  # noqa: BLE001
            detail = resp.text[:160]
        logger.warning("[flareshop] payment declined for %s (%s): %s %s",
                       purchase_id, buyer.did, resp.status_code, detail)
        await _fail(f"declined: {detail}", 402, f"Flare purchase failed: {detail}")

    data = resp.json()
    # §FLARESHOP: the treasury rail reports the source's post-debit balance.
    # Hand it back so the caller can sync the registry's CACHED
    # agents.liquid_balance to TEG truth — the same courtesy
    # services/reward_funding.py does after its legs. Without it the buyer's
    # balance in the agent picker (and on My Agents) stays at the pre-purchase
    # figure until some other flow happens to refresh it; the money is right,
    # the number on screen is stale. Found by the #207 battery.
    return (data.get("transaction_id") or "unknown"), data.get("new_source_balance")


# ---------------------------------------------------------------------------
# GET /my-purchases — developer JWT
# ---------------------------------------------------------------------------
@router.get("/my-purchases")
async def my_flare_purchases(
    db: AsyncSession = Depends(get_db),
    current_dev: Developer = Security(get_current_developer_unified),
):
    """This developer's local-currency flare purchases, newest first. Failed
    attempts are included on purpose: a lane that hides its declines is not a
    receipt."""
    q = await db.execute(
        select(FlareShopPurchase)
        .where(FlareShopPurchase.developer_id == current_dev.id)
        .order_by(FlareShopPurchase.created_at.desc())
        .limit(100)
    )
    rows = q.scalars().all()
    return {
        "currency": _local_currency(),
        "current_flare_tier": current_dev.flare_tier,
        "purchases": [
            {
                "purchase_id": r.id,
                "tier": r.tier,
                "price": str(r.price),
                "currency": r.currency,
                "status": r.status,
                "failure_reason": r.failure_reason,
                "buyer_agent_did": r.buyer_agent_did,
                "target_agent_did": r.target_agent_did,
                "transaction_id": r.teg_tx_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in rows
        ],
    }
