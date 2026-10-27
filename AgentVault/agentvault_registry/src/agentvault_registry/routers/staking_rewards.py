"""
API endpoints for staking rewards and auto-distribution management.
"""
from typing import Annotated, List, Dict, Any, Optional
from datetime import date, datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, Query, Security
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from pydantic import BaseModel, Field

from ..database import get_db
from ..models import Agent, StakingDistribution, StakingRewardRecord, StakingApyConfig
from ..security import admin_credential, get_current_developer
from ..services.staking_rewards_service import get_staking_rewards_service
from ..background_tasks.staking_distributor import trigger_manual_distribution
from ..core.staking_gate import require_staking_rewards_enabled, staking_rewards_enabled, disabled_tiers_payload  # §BAFIN

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/staking/rewards")  # §pass56 PR-5+PR-6: tags via main.py ("Staking Rewards")


# Pydantic schemas
class ApyTierResponse(BaseModel):
    """APY tier configuration response."""
    tier_name: str
    min_stake: Decimal
    max_stake: Optional[Decimal]
    base_apy: Decimal
    lock_period_days: int
    lock_bonus_apy: Decimal
    is_active: bool


class DistributionStatus(BaseModel):
    """Distribution run status."""
    id: str
    distribution_date: date
    distribution_type: str
    total_distributed: Decimal
    total_stakers: int
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    error_message: Optional[str]
    distribution_metadata: Optional[Dict[str, Any]]


class RewardRecord(BaseModel):
    """Individual reward record."""
    id: str
    agent_did: str
    staked_amount: Decimal
    apy_rate: Decimal
    reward_amount: Decimal
    days_staked: int
    tier_name: str
    status: str
    distributed_at: Optional[datetime]
    error_message: Optional[str]


class RewardEstimate(BaseModel):
    """Estimated reward calculation."""
    staked_amount: Decimal
    tier_name: str
    base_apy: Decimal
    lock_bonus_apy: Decimal
    total_apy: Decimal
    daily_reward: Decimal
    monthly_reward: Decimal
    yearly_reward: Decimal


class AutoCompoundSettings(BaseModel):
    """Auto-compound settings for an agent."""
    enabled: bool


# Endpoints
@router.get("/apy-tiers", summary="The configured payout tiers (none where the payout switch is off)", response_model=List[ApyTierResponse])
async def get_apy_tiers(
    db: Annotated[AsyncSession, Depends(get_db)],
    active_only: bool = Query(True, description="Only return active tiers")
):
    """
    The payout tiers configured on this registry: minimum and maximum locked amount, lock period, base rate and lock
    bonus. A payout on locked units is a switch per registry (`STAKING_REWARDS_ENABLED`): discretionary, paid in
    platform units, off on the public network, where this answers no tiers. Public, no auth.
    """
    # §BAFIN: a registry with staking rewards switched off publishes no rate at all.
    if not staking_rewards_enabled():
        return disabled_tiers_payload("list")

    stmt = select(StakingApyConfig)
    if active_only:
        stmt = stmt.where(StakingApyConfig.is_active == True)
    stmt = stmt.order_by(StakingApyConfig.min_stake)
    
    result = await db.execute(stmt)
    tiers = result.scalars().all()
    
    return [
        ApyTierResponse(
            tier_name=tier.tier_name,
            min_stake=tier.min_stake,
            max_stake=tier.max_stake,
            base_apy=tier.base_apy,
            lock_period_days=tier.lock_period_days,
            lock_bonus_apy=tier.lock_bonus_apy,
            is_active=tier.is_active
        )
        for tier in tiers
    ]


@router.get("/estimate/{agent_did}", response_model=RewardEstimate, summary="Estimate payouts on locked units", dependencies=[Depends(require_staking_rewards_enabled)])  # §BAFIN
async def estimate_rewards(
    agent_did: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = Query(1, ge=1, le=365, description="Number of days to calculate")
):
    """Estimate payouts for an agent from its current locked amount."""
    
    # Get agent
    stmt = select(Agent).where(Agent.did == agent_did)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    
    staked_amount = Decimal(str(agent.staked_balance or 0))
    if staked_amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent has no locked balance"
        )
    
    # Get APY tier
    service = get_staking_rewards_service()
    tier_info = await service.get_apy_tier(db, staked_amount)
    
    # Calculate rewards
    total_apy = tier_info['base_apy'] + tier_info.get('lock_bonus_apy', Decimal('0'))
    daily_reward = await service.calculate_daily_reward(staked_amount, total_apy, 1)
    monthly_reward = await service.calculate_daily_reward(staked_amount, total_apy, 30)
    yearly_reward = await service.calculate_daily_reward(staked_amount, total_apy, 365)
    
    return RewardEstimate(
        staked_amount=staked_amount,
        tier_name=tier_info['tier_name'],
        base_apy=tier_info['base_apy'],
        lock_bonus_apy=tier_info.get('lock_bonus_apy', Decimal('0')),
        total_apy=total_apy,
        daily_reward=daily_reward,
        monthly_reward=monthly_reward,
        yearly_reward=yearly_reward
    )


@router.post("/distribute/manual", dependencies=[Depends(require_staking_rewards_enabled)])  # §BAFIN
async def trigger_distribution(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_developer: Annotated[Any, Security(get_current_developer)],
    distribution_date: Optional[date] = Query(None, description="Date to run distribution for (default: today)")
):
    """Manually trigger a payout distribution (admin only)."""
    
    # Check if developer is admin (D6-057, §POCKETPAIR: on this request's credential, so a scoped key is not admin)
    if not admin_credential(current_developer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can trigger manual distribution"
        )
    
    # Run distribution
    service = get_staking_rewards_service()
    result = await service.run_daily_distribution(
        db=db,
        distribution_date=distribution_date,
        initiated_by=current_developer.email or 'admin'
    )
    
    return result


@router.get("/distributions", response_model=List[DistributionStatus])
async def get_distribution_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """Get distribution run history."""
    
    stmt = select(StakingDistribution).order_by(
        StakingDistribution.distribution_date.desc()
    ).limit(limit).offset(offset)
    
    result = await db.execute(stmt)
    distributions = result.scalars().all()
    
    return [
        DistributionStatus(
            id=dist.id,
            distribution_date=dist.distribution_date,
            distribution_type=dist.distribution_type,
            total_distributed=dist.total_distributed,
            total_stakers=dist.total_stakers,
            status=dist.status,
            started_at=dist.started_at,
            completed_at=dist.completed_at,
            error_message=dist.error_message,
            distribution_metadata=dist.distribution_metadata
        )
        for dist in distributions
    ]


def distribution_records_stmt(distribution_id: str, limit: int, offset: int):
    """One page of a distribution's reward records, in a UNIQUE order.

    §MCPTEST30 (V0545): the page was `.limit().offset()` with no ORDER BY, so Postgres returned rows in whatever order
    each plan produced and two pages were not a partition of the list (a row on both, another on neither: §DIRFEED-2,
    found by a census of routes that page without an order). Ordered by the agent, then the record's own id."""
    return (select(StakingRewardRecord)
            .where(StakingRewardRecord.distribution_id == distribution_id)
            .order_by(StakingRewardRecord.agent_did, StakingRewardRecord.id)
            .limit(limit).offset(offset))


@router.get("/distributions/{distribution_id}/records", response_model=List[RewardRecord])
async def get_distribution_records(
    distribution_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """Get the individual payout records of a distribution run."""
    
    stmt = distribution_records_stmt(distribution_id, limit, offset)
    
    result = await db.execute(stmt)
    records = result.scalars().all()
    
    return [
        RewardRecord(
            id=record.id,
            agent_did=record.agent_did,
            staked_amount=record.staked_amount,
            apy_rate=record.apy_rate,
            reward_amount=record.reward_amount,
            days_staked=record.days_staked,
            tier_name=record.tier_name,
            status=record.status,
            distributed_at=record.distributed_at,
            error_message=record.error_message
        )
        for record in records
    ]


@router.get("/agents/{agent_did}/history", response_model=List[RewardRecord], summary="The payout history of an agent")
async def get_agent_reward_history(
    agent_did: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """Get the payout history of a specific agent."""
    
    stmt = select(StakingRewardRecord).where(
        StakingRewardRecord.agent_did == agent_did
    ).order_by(
        StakingRewardRecord.created_at.desc()
    ).limit(limit).offset(offset)
    
    result = await db.execute(stmt)
    records = result.scalars().all()
    
    return [
        RewardRecord(
            id=record.id,
            agent_did=record.agent_did,
            staked_amount=record.staked_amount,
            apy_rate=record.apy_rate,
            reward_amount=record.reward_amount,
            days_staked=record.days_staked,
            tier_name=record.tier_name,
            status=record.status,
            distributed_at=record.distributed_at,
            error_message=record.error_message
        )
        for record in records
    ]


@router.get("/agents/{agent_did}/auto-compound", response_model=AutoCompoundSettings)
async def get_auto_compound_settings(
    agent_did: str,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Get auto-compound settings for an agent."""
    
    stmt = select(Agent).where(Agent.did == agent_did)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    
    return AutoCompoundSettings(
        enabled=agent.auto_compound_enabled or False
    )


@router.put("/agents/{agent_did}/auto-compound", response_model=AutoCompoundSettings, dependencies=[Depends(require_staking_rewards_enabled)])  # §BAFIN
async def update_auto_compound_settings(
    agent_did: str,
    settings: AutoCompoundSettings,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_developer: Annotated[Any, Security(get_current_developer)]
):
    """Update auto-compound settings for an agent."""
    
    # Get agent and verify ownership
    stmt = select(Agent).where(
        and_(
            Agent.did == agent_did,
            Agent.creator_developer_id == current_developer.id
        )
    )
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found or you don't have permission"
        )
    
    # Update settings
    agent.auto_compound_enabled = settings.enabled
    await db.commit()
    
    logger.info(f"Auto-compound {'enabled' if settings.enabled else 'disabled'} for agent {agent_did}")
    
    return settings


@router.get("/stats/summary")
async def get_distribution_stats(
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Get summary statistics for payout distributions."""
    
    # Get total distributed
    stmt = select(
        func.sum(StakingDistribution.total_distributed),
        func.count(StakingDistribution.id)
    ).where(StakingDistribution.status == 'completed')
    
    result = await db.execute(stmt)
    total_distributed, distribution_count = result.one()
    
    # Get total stakers rewarded
    stmt = select(func.count(func.distinct(StakingRewardRecord.agent_did))).where(
        StakingRewardRecord.status == 'distributed'
    )
    result = await db.execute(stmt)
    unique_stakers = result.scalar() or 0
    
    # Get last distribution
    stmt = select(StakingDistribution).where(
        StakingDistribution.status == 'completed'
    ).order_by(StakingDistribution.distribution_date.desc()).limit(1)
    
    result = await db.execute(stmt)
    last_distribution = result.scalar_one_or_none()
    
    return {
        'total_distributed': str(total_distributed or 0),
        'distribution_count': distribution_count or 0,
        'unique_stakers_rewarded': unique_stakers,
        'last_distribution': {
            'date': last_distribution.distribution_date if last_distribution else None,
            'amount': str(last_distribution.total_distributed) if last_distribution else '0',
            'stakers': last_distribution.total_stakers if last_distribution else 0
        } if last_distribution else None
    }


@router.post("/admin/reconcile-teg-locks")
async def reconcile_teg_locks(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_developer: Annotated[Any, Security(get_current_developer)],
    payload: Optional[Dict[str, Any]] = None,
):
    """§V0045 F2 repair — reconcile registry `agents.staked_balance` ↔ TEG `locked_balance`.

    Direction = LOCK-UP (Commander-approved 2026-06-09): under-locked agents get a TEG
    lock top-up to match the registry's locked amount (honors the user's auto-compound intent and
    removes the spendable-lock exposure). Over-locks are REPORTED only, unless
    `release_over_locks=true` (quiet-box only: in-flight cross-TEG escrow shares the
    same column and can masquerade as an over-lock).

    Body: {"dry_run": true, "dids": ["did:.."]?, "release_over_locks": false, "tolerance": "0.000001"}
    Returns a per-agent report + totals. Admin only. Never touches DB balances directly —
    all corrections go through the TEG lock/unlock API.
    """
    if not admin_credential(current_developer):   # D6-057 (§POCKETPAIR): a scoped key is not admin
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")

    from ..teg_client import get_teg_client, TEGClientError
    payload = payload or {}
    dry_run = bool(payload.get("dry_run", True))
    release_over_locks = bool(payload.get("release_over_locks", False))
    # §V0046 (Commander-approved): when a lock-up fails for INSUFFICIENT BALANCE the
    # compounded-but-never-locked rewards were already SPENT — that stake never truly
    # existed. write_down_unfundable=true reduces registry staked_balance by the full
    # drift so the books match reality (the SYBIL case). Per-row surfaced + logged.
    write_down_unfundable = bool(payload.get("write_down_unfundable", False))
    tol = Decimal(str(payload.get("tolerance", "0.000001")))
    dids = payload.get("dids")

    q = select(Agent).where(Agent.staked_balance > 0)
    if dids:
        q = select(Agent).where(Agent.did.in_(list(dids)))
    agents = (await db.execute(q)).scalars().all()

    client = get_teg_client()
    report: List[Dict[str, Any]] = []
    locked_up = Decimal("0")
    released = Decimal("0")
    errors = 0
    for agent in agents:
        staked = Decimal(str(agent.staked_balance or 0))
        row: Dict[str, Any] = {"did": agent.did, "registry_staked": str(staked)}
        try:
            teg_locked = await client.get_locked_balance_admin(agent.did)
        except Exception as e:
            errors += 1
            row.update({"action": "error", "error": f"locked read failed: {str(e)[:160]}"})
            report.append(row)
            continue
        drift = staked - teg_locked
        row.update({"teg_locked": str(teg_locked), "drift": str(drift)})
        try:
            if drift > tol:
                row["action"] = "lock_up" if not dry_run else "would_lock_up"
                if not dry_run:
                    try:
                        await client.lock_tokens(agent.did, drift)
                        locked_up += drift
                    except Exception as lock_err:
                        if write_down_unfundable and "insufficient" in str(lock_err).lower():
                            # The drift was spent — un-stake it on paper (registry-side
                            # ledger correction; TEG balances untouched).
                            agent.staked_balance = staked - drift
                            row["action"] = "wrote_down_unfundable"
                            row["staked_after"] = str(agent.staked_balance)
                            logger.warning(
                                f"[StakingReconcile] WROTE DOWN unfundable stake for {agent.did}: "
                                f"{staked} → {agent.staked_balance} (drift {drift} was spent, not lockable)"
                            )
                        else:
                            raise
            elif drift < -tol:
                if release_over_locks and not dry_run:
                    row["action"] = "release_over_lock"
                    await client.unlock_tokens(agent.did, -drift)
                    released += -drift
                else:
                    row["action"] = "over_lock_reported"
            else:
                row["action"] = "in_sync"
        except Exception as e:
            errors += 1
            row.update({"action": "error", "error": str(e)[:200]})
        report.append(row)

    if not dry_run:
        await db.commit()
    logger.warning(
        f"[StakingReconcile] dry_run={dry_run} agents={len(report)} "
        f"locked_up={locked_up} released={released} errors={errors} by={getattr(current_developer, 'email', '?')}"
    )
    return {
        "dry_run": dry_run,
        "agents_checked": len(report),
        "locked_up_total": str(locked_up),
        "released_total": str(released),
        "errors": errors,
        "report": report,
    }
