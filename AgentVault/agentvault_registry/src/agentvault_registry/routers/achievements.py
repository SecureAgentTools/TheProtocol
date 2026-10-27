"""
f038: Developer Achievement System
===================================
Rewards for completing tutorials and platform milestones.
Achievements are REWARDS, not GATES — never block any functionality.
Payouts are idempotent — UNIQUE(developer_id, achievement_type) prevents duplicates.
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Security
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry.security import get_current_developer

logger = logging.getLogger(__name__)

router = APIRouter()  # §pass56 PR-5: tags= via main.py "Achievements"


class RecordAchievementRequest(BaseModel):
    achievement_type: str = Field(..., description="Achievement type key (e.g., tutorial_agent_lifecycle)")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Extra data: completion time, steps, etc.")
    agent_did: Optional[str] = Field(None, description="Agent DID for payout (if payout enabled)")


async def _owns_agent(db: AsyncSession, developer: models.Developer, agent_did: str) -> bool:
    """D6-056: an achievement pays its developer's OWN agent (one this developer created), never whatever DID a request
    names: the payout comes from the treasury's reward funding, once per (developer, achievement)."""
    row = (await db.execute(
        select(models.Agent.creator_developer_id).where(models.Agent.did == agent_did))).first()
    return row is not None and row[0] == developer.id


@router.post("/record", summary="Record an achievement")
async def record_achievement(
    request: RecordAchievementRequest,
    current_developer: models.Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """
    Record an achievement of the calling developer. Idempotent: an achievement already recorded is returned as it
    is, and a payout is made once at most. Where the achievement carries a payout and `agent_did` is given, the
    payout in the frame's units is paid to that agent from the treasury's payout funding; otherwise it stays pending
    (see claim-pending).
    """
    # Check if already earned (idempotent — no duplicate payouts ever)
    existing = await db.execute(
        select(models.DeveloperAchievement).where(
            models.DeveloperAchievement.developer_id == current_developer.id,
            models.DeveloperAchievement.achievement_type == request.achievement_type,
        )
    )
    existing_achievement = existing.scalar_one_or_none()
    if existing_achievement:
        logger.info(f"[Achievement] Already earned: {request.achievement_type} by dev {current_developer.id}")
        return {
            "status": "already_earned",
            "achievement": {
                "type": existing_achievement.achievement_type,
                "name": existing_achievement.achievement_name,
                "awarded_at": existing_achievement.awarded_at.isoformat(),
                "payout_avt": existing_achievement.payout_avt,
                "payout_status": existing_achievement.payout_status,
            }
        }

    # Look up reward config
    reward_result = await db.execute(
        select(models.AchievementReward).where(
            models.AchievementReward.achievement_type == request.achievement_type
        )
    )
    reward = reward_result.scalar_one_or_none()
    if not reward:
        raise HTTPException(status_code=404, detail=f"Unknown achievement type: {request.achievement_type}")

    if not reward.enabled:
        return {"status": "disabled", "message": "This achievement is currently disabled"}

    # Attempt payout if configured and agent_did provided
    payout_avt = 0.0
    payout_tx_id = None
    payout_held = None
    # D6-056: the payout goes only to one of the caller's own agents. The console records with the agent selected at
    # the top, which may be an agent the developer acts as and did not create (an organisation's): the achievement is
    # recorded all the same and its payout stays pending, for claim-pending to one of the developer's own agents.
    if reward.payout_avt > 0 and request.agent_did and not await _owns_agent(db, current_developer, request.agent_did):
        payout_held = ("agent_did is not one of your own agents: the payout stays pending; claim it to one of yours "
                       "(POST /achievements/claim-pending)")
        logger.info(f"[Achievement] {request.agent_did} is not one of developer {current_developer.id}'s agents: "
                    f"the payout for {request.achievement_type} stays pending")
    if reward.payout_avt > 0 and request.agent_did and payout_held is None:
        try:
            # §REWARDEVENTS: shared rail — per-leg TokensTransferred emission +
            # cache sync; same deterministic per-logical-op key as before (a
            # given (developer, achievement_type) pays once, ever).
            from ..services.reward_funding import fund_reward_via_waterfall
            res = await fund_reward_via_waterfall(
                db,
                target_agent_did=request.agent_did,
                amount=str(reward.payout_avt),
                reason="achievement",
                reference_id=request.achievement_type,
                idempotency_key=f"achievement-{current_developer.id}-{request.achievement_type}",
            )
            if res["status"] == "completed":
                payout_avt = reward.payout_avt
                payout_tx_id = res["first_transaction_id"]
                logger.info(
                    f"[Achievement] Payout {payout_avt} AVT → {request.agent_did} "
                    f"(tx={payout_tx_id}, via={[l.get('source') for l in res['legs']]}) "
                    f"for {request.achievement_type}"
                )
            else:
                logger.warning(
                    f"[Achievement] Payout PARTIAL for {request.achievement_type}: "
                    f"funded {res['funded_amount']} of {reward.payout_avt} — "
                    f"legs committed + emitted; record stays pending")
        except Exception as e:
            logger.warning(f"[Achievement] Payout error (non-fatal): {e}")

    # Determine payout status
    if payout_avt > 0:
        payout_status = "paid"
    elif request.agent_did:
        payout_status = "pending"  # had agent but payout failed
    else:
        payout_status = "pending"  # no agent — can claim later

    # Record achievement (UNIQUE constraint is the safety net)
    achievement = models.DeveloperAchievement(
        developer_id=current_developer.id,
        achievement_type=request.achievement_type,
        achievement_name=reward.achievement_name,
        payout_avt=payout_avt,
        payout_transaction_id=payout_tx_id,
        payout_status=payout_status,
        metadata_json=request.metadata,
    )
    db.add(achievement)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        # Race condition — another request beat us. Return existing.
        existing2 = await db.execute(
            select(models.DeveloperAchievement).where(
                models.DeveloperAchievement.developer_id == current_developer.id,
                models.DeveloperAchievement.achievement_type == request.achievement_type,
            )
        )
        existing_ach = existing2.scalar_one_or_none()
        if existing_ach:
            return {
                "status": "already_earned",
                "achievement": {
                    "type": existing_ach.achievement_type,
                    "name": existing_ach.achievement_name,
                    "awarded_at": existing_ach.awarded_at.isoformat(),
                    "payout_avt": existing_ach.payout_avt,
                }
            }
        raise HTTPException(status_code=500, detail=f"Failed to record achievement: {e}")

    logger.info(
        f"[Achievement] Awarded: {request.achievement_type} ({reward.achievement_name}) "
        f"to dev {current_developer.id}, payout={payout_avt} AVT"
    )

    out = {
        "status": "awarded",
        "achievement": {
            "type": achievement.achievement_type,
            "name": achievement.achievement_name,
            "awarded_at": achievement.awarded_at.isoformat(),
            "payout_avt": achievement.payout_avt,
            "payout_transaction_id": achievement.payout_transaction_id,
        }
    }
    if payout_held:
        out["payout_held"] = payout_held
    return out


@router.get("/me", summary="My achievements")
async def get_my_achievements(
    current_developer: models.Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """List all achievements the current developer has reached."""
    result = await db.execute(
        select(models.DeveloperAchievement)
        .where(models.DeveloperAchievement.developer_id == current_developer.id)
        .order_by(models.DeveloperAchievement.awarded_at.desc())
    )
    achievements = result.scalars().all()

    pending_count = sum(1 for a in achievements if a.payout_status == 'pending')
    return {
        "achievements": [
            {
                "type": a.achievement_type,
                "name": a.achievement_name,
                "awarded_at": a.awarded_at.isoformat(),
                "payout_avt": a.payout_avt,
                "payout_status": a.payout_status,
                "metadata": a.metadata_json,
            }
            for a in achievements
        ],
        "total": len(achievements),
        "total_payout": sum(a.payout_avt for a in achievements),
        "pending_count": pending_count,
    }


class ClaimPendingRequest(BaseModel):
    agent_did: str = Field(..., description="Agent DID to receive pending payouts")


@router.post("/claim-pending", summary="Claim pending achievement payouts")
async def claim_pending_payouts(
    request: ClaimPendingRequest,
    current_developer: models.Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """
    Claim all pending achievement payouts for the current developer.
    Pays out to the specified agent_did, one of the developer's own agents (D6-056). Idempotent: already-paid
    achievements are skipped.
    """
    if not await _owns_agent(db, current_developer, request.agent_did):
        raise HTTPException(status_code=403, detail=("agent_did must name one of your own agents: an achievement's payout goes "
                                                     "to an agent of the developer who holds it"))
    # Get all pending achievements
    result = await db.execute(
        select(models.DeveloperAchievement).where(
            models.DeveloperAchievement.developer_id == current_developer.id,
            models.DeveloperAchievement.payout_status == 'pending',
        )
    )
    pending = result.scalars().all()

    if not pending:
        return {"status": "no_pending", "message": "No pending payouts to claim", "claimed": 0}

    claimed = []
    total_paid = 0.0

    for achievement in pending:
        # Look up reward amount from catalog
        reward_result = await db.execute(
            select(models.AchievementReward).where(
                models.AchievementReward.achievement_type == achievement.achievement_type
            )
        )
        reward = reward_result.scalar_one_or_none()
        if not reward or not reward.enabled or reward.payout_avt <= 0:
            continue

        # Transfer from treasury
        try:
            # §REWARDEVENTS: shared rail — per-leg TokensTransferred emission +
            # cache sync; same per-logical-op key as the record path → a given
            # (developer, achievement_type) pays once, ever.
            from ..services.reward_funding import fund_reward_via_waterfall
            res = await fund_reward_via_waterfall(
                db,
                target_agent_did=request.agent_did,
                amount=str(reward.payout_avt),
                reason="achievement_claim",
                reference_id=achievement.achievement_type,
                idempotency_key=f"achievement-{achievement.developer_id}-{achievement.achievement_type}",
            )
            if res["status"] == "completed":
                tx_id = res["first_transaction_id"]
                achievement.payout_avt = reward.payout_avt
                achievement.payout_transaction_id = tx_id
                achievement.payout_status = "paid"
                total_paid += reward.payout_avt
                claimed.append({
                    "type": achievement.achievement_type,
                    "name": achievement.achievement_name,
                    "payout_avt": reward.payout_avt,
                    "transaction_id": tx_id,
                    "funded_via": [l.get("source") for l in res["legs"]],
                })
                logger.info(f"[Achievement] Claimed: {achievement.achievement_type} → {reward.payout_avt} AVT to {request.agent_did} via {[l.get('source') for l in res['legs']]}")
            else:
                logger.warning(
                    f"[Achievement] Claim PARTIAL for {achievement.achievement_type}: "
                    f"funded {res['funded_amount']} of {reward.payout_avt} — "
                    f"legs committed + emitted; claim stays pending")
        except Exception as e:
            logger.warning(f"[Achievement] Claim failed for {achievement.achievement_type}: {e}")

    await db.commit()

    return {
        "status": "claimed",
        "agent_did": request.agent_did,
        "claimed": len(claimed),
        "total_paid": total_paid,
        "details": claimed,
    }


@router.get("/catalog", summary="Achievement catalog")
async def get_achievement_catalog(
    db: AsyncSession = Depends(get_db),
):
    """List all available achievements with payout info. Public endpoint."""
    result = await db.execute(
        select(models.AchievementReward)
        .where(models.AchievementReward.enabled == True)
        .order_by(models.AchievementReward.payout_avt.desc())
    )
    rewards = result.scalars().all()

    return {
        "achievements": [
            {
                "type": r.achievement_type,
                "name": r.achievement_name,
                "payout_avt": r.payout_avt,
                "description": r.description,
            }
            for r in rewards
        ],
        "total": len(rewards),
    }
