"""
Enhanced Tokenomics endpoints for TEG Core Service

This module provides endpoints for rewards, transaction history, and treasury information.

Created as part of the TEG integration enhancement.
"""
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional, List, Dict, Any
from uuid import uuid4
import uuid

from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request, Security
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, desc, func, or_, text
from starlette.status import HTTP_403_FORBIDDEN, HTTP_404_NOT_FOUND, HTTP_400_BAD_REQUEST

from ...api.auth import get_current_agent
from ...core.config import get_settings
from ...database.db_session import get_db
from ...database.models import (
    AgentTEGProfile, TEGTransaction, TransactionStatus, TransactionType,
    TEGRewardDistribution, TEGRewardConfig, StakingRewardDistribution,
    Stake
)
from pydantic import BaseModel, Field

import logging

logger = logging.getLogger(__name__)

router = APIRouter()
settings = get_settings()


class PendingRewardsResponse(BaseModel):
    """Response for pending rewards query"""
    pending_rewards: Decimal
    last_claim_timestamp: Optional[datetime] = None
    reward_sources: List[Dict[str, Any]] = Field(default_factory=list)


class TransactionHistoryItem(BaseModel):
    """Single transaction in history"""
    transaction_id: str
    transaction_type: str
    amount: str
    sender_agent_id: Optional[str]
    receiver_agent_id: str
    timestamp: datetime
    status: str
    fee_amount: str
    attached_message: Optional[str] = None


class TransactionHistoryResponse(BaseModel):
    """Response for transaction history query"""
    transactions: List[TransactionHistoryItem]


class TreasuryInfoResponse(BaseModel):
    """Response for treasury information"""
    total_supply: str
    circulating_supply: str
    treasury_balance: str
    locked_supply: str
    burned_supply: str
    reward_pool: str
    last_updated: datetime


class StakeBalanceResponse(BaseModel):
    """Response for staking balance query"""
    agent_id: str
    staked_balance: str
    locked_balance: str
    available_to_unstake: str
    tier: str
    apy: float
    active_stakes: List[Dict[str, Any]]


class StakingHistoryResponse(BaseModel):
    """Response for staking history query"""
    transactions: List[Dict[str, Any]]
    total: int


class APYTiersResponse(BaseModel):
    """Response for APY tiers query"""
    tiers: List[Dict[str, Any]]


class RewardsClaimResponse(BaseModel):
    """Response for rewards claim"""
    claimed_amount: str
    transaction_id: str
    new_balance: str
    timestamp: str


class RewardsHistoryResponse(BaseModel):
    """Response for rewards history query"""
    rewards: List[Dict[str, Any]]
    total_earned: str


def verify_registry_service_token(token: str, request=None) -> bool:
    """Verify an internal registry caller.

    §2026-06-17 Phase 4 — mTLS SVID (presented via the nginx-teg sidecar) is PRIMARY; the
    legacy shared key is a fallback honored ONLY while TEG_MTLS_REQUIRED is false (shadow).
    Under enforce, only an accepted internal SVID passes. Pass the FastAPI Request for mTLS.
    """
    if request is not None:
        try:
            from ...core.internal_auth import (
                extract_spiffe_from_request, is_internal_service_identity, teg_mtls_required,
            )
            spiffe = extract_spiffe_from_request(request)
            if spiffe and is_internal_service_identity(spiffe):  # §MONEY-R51: the ONE rule
                return True
            if teg_mtls_required():
                return False
        except Exception:
            pass
    from ...core.internal_auth import admin_key_ok  # §MONEY-M3a R26
    return admin_key_ok(token)


@router.get(
    "/tokenomics/rewards/{agent_did}",
    response_model=PendingRewardsResponse,
    responses={
        403: {"description": "Forbidden"},
        404: {"description": "Agent not found"},
    }
)
async def get_pending_rewards(
    http_request: Request,
    agent_did: str,
    db: Session = Depends(get_db),
    service_token: str = Header(None, alias="X-Service-Token")
):
    """
    Get pending (unclaimed) rewards for an agent.
    
    This includes:
    - Staking rewards
    - Attestation rewards
    - Governance participation rewards
    - Other protocol rewards
    """
    # Verify Registry service token
    if not verify_registry_service_token(service_token, http_request):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Invalid service token"
        )
    
    # Get agent profile
    agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == agent_did
    ).first()
    
    if not agent:
        return PendingRewardsResponse(
            pending_rewards=Decimal("0"),
            reward_sources=[]
        )
    
    # Calculate pending rewards from different sources
    pending_total = Decimal("0")
    reward_sources = []
    
    # 1. Check unclaimed staking rewards
    try:
        staking_rewards = db.query(
            func.sum(StakingRewardDistribution.amount)
        ).filter(
            StakingRewardDistribution.agent_id == agent_did,
            StakingRewardDistribution.transaction_id.is_(None)  # Unclaimed
        ).scalar()
        
        if staking_rewards:
            pending_total += staking_rewards
            reward_sources.append({
                "type": "staking",
                "amount": str(staking_rewards),
                "description": "Unclaimed staking rewards"
            })
    except Exception as e:
        logger.warning(f"Could not query staking rewards: {e}")
    
    # 2. Check general reward distributions
    try:
        general_rewards = db.query(
            TEGRewardDistribution.reward_type,
            func.sum(TEGRewardDistribution.amount).label('total')
        ).filter(
            TEGRewardDistribution.agent_id == agent_did,
            TEGRewardDistribution.transaction_id.is_(None)  # Unclaimed
        ).group_by(
            TEGRewardDistribution.reward_type
        ).all()
        
        for reward_type, amount in general_rewards:
            if amount:
                pending_total += amount
                reward_sources.append({
                    "type": reward_type,
                    "amount": str(amount),
                    "description": f"Unclaimed {reward_type} rewards"
                })
    except Exception as e:
        logger.warning(f"Could not query general rewards: {e}")
    
    # Get last claim timestamp
    last_claim = None
    try:
        # Find most recent reward claim transaction
        last_claim_tx = db.query(TEGTransaction).filter(
            TEGTransaction.receiver_agent_id == agent_did,
            TEGTransaction.transaction_type == "reward_claim"
        ).order_by(
            desc(TEGTransaction.timestamp)
        ).first()
        
        if last_claim_tx:
            last_claim = last_claim_tx.timestamp
    except Exception as e:
        logger.warning(f"Could not query last claim: {e}")
    
    return PendingRewardsResponse(
        pending_rewards=pending_total,
        last_claim_timestamp=last_claim,
        reward_sources=reward_sources
    )


@router.get(
    "/tokenomics/transactions/{agent_did}",
    response_model=TransactionHistoryResponse,
    responses={
        403: {"description": "Forbidden"},
    }
)
async def get_transaction_history(
    http_request: Request,
    agent_did: str,
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    transaction_type: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    service_token: str = Header(None, alias="X-Service-Token")
):
    """
    Get recent transaction history for an agent.
    
    Returns transactions where the agent is either sender or receiver,
    ordered by most recent first.
    """
    # Verify Registry service token
    if not verify_registry_service_token(service_token, http_request):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Invalid service token"
        )
    
    # Build query for transactions
    query = db.query(TEGTransaction).filter(
        (TEGTransaction.sender_agent_id == agent_did) |
        (TEGTransaction.receiver_agent_id == agent_did)
    )
    
    # Filter by transaction type if specified
    if transaction_type:
        query = query.filter(TEGTransaction.transaction_type == transaction_type)
    
    # Order by most recent first and apply pagination
    transactions = query.order_by(
        desc(TEGTransaction.timestamp)
    ).offset(offset).limit(limit).all()
    
    # Format transactions
    transaction_list = []
    for tx in transactions:
        transaction_list.append(TransactionHistoryItem(
            transaction_id=tx.transaction_id,
            transaction_type=tx.transaction_type,
            amount=str(tx.amount),
            sender_agent_id=tx.sender_agent_id,
            receiver_agent_id=tx.receiver_agent_id,
            timestamp=tx.timestamp,
            status=tx.status.value,
            fee_amount=str(tx.fee_amount or 0),
            attached_message=tx.attached_message
        ))
    
    return TransactionHistoryResponse(transactions=transaction_list)


@router.get(
    "/tokenomics/treasury",
    response_model=TreasuryInfoResponse,
    responses={
        403: {"description": "Forbidden"},
    }
)
async def get_treasury_info(
    http_request: Request,
    db: Session = Depends(get_db),
    service_token: str = Header(None, alias="X-Service-Token")
):
    """
    Get treasury and token supply information.
    
    Returns global metrics about the token economy.
    """
    # Verify Registry service token
    if not verify_registry_service_token(service_token, http_request):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Invalid service token"
        )
    
    try:
        # Calculate total supply (sum of all agent balances)
        total_balance = db.query(
            func.sum(AgentTEGProfile.token_balance)
        ).scalar() or Decimal("0")
        
        total_locked = db.query(
            func.sum(AgentTEGProfile.locked_balance)
        ).scalar() or Decimal("0")
        
        total_supply = total_balance + total_locked
        
        # Calculate circulating supply (unlocked tokens)
        circulating_supply = total_balance
        
        # Calculate locked supply
        locked_supply = total_locked
        
        # Calculate treasury balance (system accounts + real treasury DID)
        treasury_accounts = [
            "SYSTEM", "TREASURY", "REWARD_POOL", "GOVERNANCE",
            settings.teg_system_treasury_did  # "did:theprotocol:teg_system_treasury"
        ]
        treasury_balance = db.query(
            func.sum(AgentTEGProfile.token_balance)
        ).filter(
            AgentTEGProfile.agent_id.in_(treasury_accounts)
        ).scalar() or Decimal("0")
        
        # Calculate burned tokens (sent to BURN address)
        burned_supply = db.query(
            func.sum(TEGTransaction.amount)
        ).filter(
            TEGTransaction.receiver_agent_id == "BURN",
            TEGTransaction.status == TransactionStatus.COMPLETED
        ).scalar() or Decimal("0")
        
        # Calculate reward pool
        reward_pool = db.query(
            func.sum(TEGRewardDistribution.amount)
        ).filter(
            TEGRewardDistribution.transaction_id.is_(None)  # Unclaimed
        ).scalar() or Decimal("0")
        
        return TreasuryInfoResponse(
            total_supply=str(total_supply),
            circulating_supply=str(circulating_supply),
            treasury_balance=str(treasury_balance),
            locked_supply=str(locked_supply),
            burned_supply=str(burned_supply),
            reward_pool=str(reward_pool),
            last_updated=datetime.now(timezone.utc)
        )
        
    except Exception as e:
        logger.error(f"Error calculating treasury info: {e}")
        # Return default values on error
        return TreasuryInfoResponse(
            total_supply="1000000",
            circulating_supply="500000",
            treasury_balance="300000",
            locked_supply="0",
            burned_supply="0",
            reward_pool="0",
            last_updated=datetime.now(timezone.utc)
        )


# ============================================================================
# NEW ENDPOINTS ADDED FOR STAKING/REWARDS INTEGRATION
# ============================================================================

@router.get(
    "/tokenomics/staking/balance/{agent_did}",
    response_model=StakeBalanceResponse,
    summary="Get staking balance for an agent"
)
async def get_staking_balance(
    http_request: Request,
    agent_did: str,
    db: Session = Depends(get_db),
    service_token: str = Header(None, alias="X-Service-Token")
):
    """Get detailed staking balance information for an agent."""
    
    # Verify service token for inter-service calls
    if service_token and not verify_registry_service_token(service_token, http_request):
        raise HTTPException(status_code=403, detail="Invalid service token")
    
    # Get agent profile
    agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == agent_did
    ).first()
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Get active stakes
    active_stakes = db.query(Stake).filter(
        and_(
            Stake.agent_id == agent_did,
            Stake.is_active == True
        )
    ).all()
    
    # Calculate total staked
    total_staked = sum(stake.amount for stake in active_stakes) if active_stakes else Decimal('0')
    locked_amount = getattr(agent, 'locked_balance', Decimal('0'))
    
    # Get APY tier based on staked amount
    apy_tier = "bronze"  # Default
    current_apy = 5.0
    
    if total_staked >= Decimal('100000'):
        apy_tier = "platinum"
        current_apy = 15.0
    elif total_staked >= Decimal('10000'):
        apy_tier = "gold"
        current_apy = 12.0
    elif total_staked >= Decimal('1000'):
        apy_tier = "silver"
        current_apy = 8.0
    
    return StakeBalanceResponse(
        agent_id=agent_did,
        staked_balance=str(total_staked),
        locked_balance=str(locked_amount),
        available_to_unstake=str(max(Decimal('0'), total_staked - locked_amount)),
        tier=apy_tier,
        apy=current_apy,
        active_stakes=[
            {
                "stake_id": stake.stake_id,
                "amount": str(stake.amount),
                "staked_at": stake.staked_at.isoformat() if stake.staked_at else None,
                "lock_period_days": stake.lock_period_days,
                "unlock_date": stake.unlock_date.isoformat() if stake.unlock_date else None,
                "is_locked": (
                    stake.unlock_date > datetime.now(timezone.utc).replace(tzinfo=stake.unlock_date.tzinfo)
                ) if stake.unlock_date else False
            }
            for stake in active_stakes
        ]
    )


@router.get(
    "/tokenomics/staking/history/{agent_did}",
    response_model=StakingHistoryResponse,
    summary="Get staking transaction history"
)
async def get_staking_history(
    http_request: Request,
    agent_did: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    service_token: str = Header(None, alias="X-Service-Token")
):
    """Get staking transaction history for an agent."""
    
    # Verify service token
    if service_token and not verify_registry_service_token(service_token, http_request):
        raise HTTPException(status_code=403, detail="Invalid service token")
    
    # Get all stakes (active and inactive)
    stakes_query = db.query(Stake).filter(
        Stake.agent_id == agent_did
    ).order_by(desc(Stake.staked_at))
    
    total = stakes_query.count()
    stakes = stakes_query.offset(offset).limit(limit).all()
    
    transactions = []
    for stake in stakes:
        transactions.append({
            "transaction_type": "stake" if stake.is_active else "unstake",
            "stake_id": stake.stake_id,
            "amount": str(stake.amount),
            "timestamp": stake.staked_at.isoformat() if stake.staked_at else None,
            "unstaked_at": stake.unstaked_at.isoformat() if stake.unstaked_at else None,
            "status": "active" if stake.is_active else "completed"
        })
    
    return StakingHistoryResponse(
        transactions=transactions,
        total=total
    )


@router.get(
    "/tokenomics/apy-tiers",
    response_model=APYTiersResponse,
    summary="Get APY tier configuration"
)
async def get_apy_tiers(
    db: Session = Depends(get_db)
):
    """Get current APY tier configuration."""
    
    # Canonical APY tier configuration.
    # No teg_apy_tiers DB table exists yet — these are the authoritative values.
    # To make dynamic: create migration for teg_apy_tiers table, then query here.
    tiers = [
        {
            "name": "bronze",
            "min_stake": "100",
            "max_stake": "999",
            "base_apy": 5.0,
            "lock_bonus_apy": 0.0,
            "lock_period_days": 0
        },
        {
            "name": "silver",
            "min_stake": "1000",
            "max_stake": "9999",
            "base_apy": 8.0,
            "lock_bonus_apy": 2.0,
            "lock_period_days": 30
        },
        {
            "name": "gold",
            "min_stake": "10000",
            "max_stake": "99999",
            "base_apy": 12.0,
            "lock_bonus_apy": 3.0,
            "lock_period_days": 60
        },
        {
            "name": "platinum",
            "min_stake": "100000",
            "max_stake": None,
            "base_apy": 15.0,
            "lock_bonus_apy": 5.0,
            "lock_period_days": 90
        }
    ]
    
    return APYTiersResponse(tiers=tiers)


@router.post(
    "/tokenomics/rewards/claim",
    response_model=RewardsClaimResponse,
    summary="Claim all pending rewards"
)
async def claim_rewards(
    current_agent: str = Security(get_current_agent),
    db: Session = Depends(get_db)
):
    """Claim all pending rewards for the authenticated agent.

    2026-07-16 fix: get_current_agent returns the agent DID **string** (see
    api/auth.py `-> str`, and every sibling handler in this file using
    `... == current_agent` directly). This handler alone was written against a
    phantom `AgentTEGProfile` object — `current_agent.agent_id` crashed with
    `AttributeError: 'str' object has no attribute 'agent_id'` → 500 for EVERY
    caller before the rewards logic even ran. Load the profile row explicitly
    (same pattern as unstake below).
    """
    agent_profile = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == current_agent
    ).first()
    if not agent_profile:
        raise HTTPException(
            status_code=404,
            detail="Agent profile not found"
        )

    # Calculate pending rewards
    # Get unclaimed rewards
    unclaimed_staking_rewards = db.query(StakingRewardDistribution).filter(
        and_(
            StakingRewardDistribution.agent_id == current_agent,
            StakingRewardDistribution.transaction_id == None
        )
    ).all()

    unclaimed_general_rewards = db.query(TEGRewardDistribution).filter(
        and_(
            TEGRewardDistribution.agent_id == current_agent,
            TEGRewardDistribution.transaction_id == None
        )
    ).all()
    
    if not unclaimed_staking_rewards and not unclaimed_general_rewards:
        raise HTTPException(
            status_code=404,
            detail="No pending rewards to claim"
        )
    
    total_rewards = Decimal('0')
    
    # Sum staking rewards
    if unclaimed_staking_rewards:
        total_rewards += sum(reward.amount for reward in unclaimed_staking_rewards)
    
    # Sum general rewards
    if unclaimed_general_rewards:
        total_rewards += sum(reward.amount for reward in unclaimed_general_rewards)
    
    # Create transaction for reward payment
    transaction_id = str(uuid.uuid4())
    transaction = TEGTransaction(
        transaction_id=transaction_id,
        sender_agent_id="SYSTEM_REWARDS",
        receiver_agent_id=current_agent,
        amount=total_rewards,
        fee_amount=Decimal("0"),
        status=TransactionStatus.COMPLETED,
        transaction_type="reward_claim",
        attached_message="Staking rewards claim",
        timestamp=datetime.now(timezone.utc)
    )
    db.add(transaction)

    # Tag the balance change for supply-audit classification (same pattern as
    # the unstake handler below) — reward claims are Δ-neutral transit.
    db.execute(text("SELECT set_config('teg.entry_type','reward_claim',true)"))
    # Update agent balance
    agent_profile.token_balance += total_rewards
    # Keep audited_balance in sync (reward claim is legitimate)
    agent_profile.audited_balance = agent_profile.token_balance

    # Mark staking rewards as claimed
    for reward in unclaimed_staking_rewards:
        reward.transaction_id = transaction_id
    
    # Mark general rewards as claimed
    for reward in unclaimed_general_rewards:
        reward.transaction_id = transaction_id
    
    db.commit()
    
    return RewardsClaimResponse(
        claimed_amount=str(total_rewards),
        transaction_id=transaction_id,
        new_balance=str(agent_profile.token_balance),
        timestamp=transaction.timestamp.isoformat()
    )


@router.get(
    "/tokenomics/rewards/history/{agent_did}",
    response_model=RewardsHistoryResponse,
    summary="Get rewards history for an agent"
)
async def get_rewards_history(
    http_request: Request,
    agent_did: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    service_token: str = Header(None, alias="X-Service-Token")
):
    """Get complete rewards history for an agent."""
    
    # Verify service token
    if service_token and not verify_registry_service_token(service_token, http_request):
        raise HTTPException(status_code=403, detail="Invalid service token")
    
    # Get all rewards
    rewards_query = db.query(StakingRewardDistribution).filter(
        StakingRewardDistribution.agent_id == agent_did
    ).order_by(desc(StakingRewardDistribution.distributed_at))
    
    total = rewards_query.count()
    rewards = rewards_query.offset(offset).limit(limit).all()
    
    total_earned = db.query(func.sum(StakingRewardDistribution.amount)).filter(
        StakingRewardDistribution.agent_id == agent_did
    ).scalar() or Decimal('0')
    
    rewards_list = []
    for reward in rewards:
        rewards_list.append({
            "distribution_id": reward.distribution_id,
            "amount": str(reward.amount),
            "reward_type": reward.reward_type,
            "distributed_at": reward.distributed_at.isoformat() if reward.distributed_at else None,
            "claimed": reward.transaction_id is not None,
            "transaction_id": reward.transaction_id
        })
    
    return RewardsHistoryResponse(
        rewards=rewards_list,
        total_earned=str(total_earned)
    )


# ============================================================================
# STAKING OPERATIONS - MAIN ENDPOINTS FOR ECONOMIC CONSOLIDATION
# ============================================================================

class StakeRequest(BaseModel):
    """Request model for staking tokens"""
    amount: Decimal = Field(..., gt=0, description="Amount to stake")
    lock_period_days: Optional[int] = Field(None, ge=0, le=365, description="Optional lock period in days")


class StakeResponse(BaseModel):
    """Response model for stake operation"""
    stake_id: str
    agent_id: str
    amount: str
    staked_at: datetime
    lock_period_days: Optional[int]
    unlock_date: Optional[datetime]
    transaction_id: str
    new_staked_balance: str
    new_available_balance: str


class UnstakeRequest(BaseModel):
    """Request model for unstaking tokens"""
    stake_id: str = Field(..., description="ID of the stake to unstake")
    amount: Optional[Decimal] = Field(None, gt=0, description="Optional partial unstake amount")


class UnstakeResponse(BaseModel):
    """Response model for unstake operation"""
    stake_id: str
    agent_id: str
    amount: str
    unstaked_at: datetime
    transaction_id: str
    new_staked_balance: str
    new_available_balance: str


@router.post(
    "/tokenomics/stake",
    response_model=StakeResponse,
    summary="Stake tokens for rewards"
)
async def stake_tokens(
    request: StakeRequest,
    current_agent = Security(get_current_agent),
    db: Session = Depends(get_db)
):
    """Stake tokens to earn rewards based on APY tiers.
    
    This endpoint handles the core staking functionality:
    - Locks tokens from the agent's available balance
    - Creates a stake record with optional lock period
    - Returns stake details including the stake_id for future unstaking
    """
    import uuid
    from ...database.models import Stake
    
    # Get agent profile
    agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == current_agent
    ).first()
    
    if not agent:
        raise HTTPException(
            status_code=404,
            detail="Agent profile not found"
        )
    
    # Check available balance
    if agent.token_balance < request.amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient balance. Available: {agent.token_balance}, Requested: {request.amount}"
        )
    
    # Create stake record
    stake_id = str(uuid.uuid4())
    stake = Stake(
        stake_id=stake_id,
        agent_id=current_agent,
        amount=request.amount,
        staked_at=datetime.now(timezone.utc),
        is_active=True,
        lock_period_days=request.lock_period_days,
        unlock_date=datetime.now(timezone.utc) + timedelta(days=request.lock_period_days) if request.lock_period_days else None
    )
    
    # §pass77 Phase B: tag staking lock (enhanced path) — distinguishable from escrow.
    db.execute(text("SELECT set_config('teg.entry_type','stake_lock',true)"))
    # Move tokens from available to locked
    agent.token_balance -= request.amount
    agent.locked_balance = getattr(agent, 'locked_balance', Decimal('0')) + request.amount
    # Keep audited_balance in sync (staking is legitimate)
    agent.audited_balance = agent.token_balance
    
    # Create transaction record
    transaction_id = str(uuid.uuid4())
    transaction = TEGTransaction(
        transaction_id=transaction_id,
        sender_agent_id=current_agent,
        receiver_agent_id="STAKING_POOL",
        amount=request.amount,
        fee_amount=Decimal("0"),
        status=TransactionStatus.COMPLETED,
        transaction_type="stake",
        attached_message=f"Staking {request.amount} tokens" + (f" for {request.lock_period_days} days" if request.lock_period_days else ""),
        timestamp=datetime.now(timezone.utc)
    )
    
    db.add(stake)
    db.add(transaction)
    db.commit()
    db.refresh(stake)
    db.refresh(agent)
    
    return StakeResponse(
        stake_id=stake_id,
        agent_id=current_agent,
        amount=str(request.amount),
        staked_at=stake.staked_at,
        lock_period_days=request.lock_period_days,
        unlock_date=stake.unlock_date,
        transaction_id=transaction_id,
        new_staked_balance=str(agent.locked_balance),
        new_available_balance=str(agent.token_balance)
    )


@router.post(
    "/tokenomics/unstake",
    response_model=UnstakeResponse,
    summary="Unstake tokens"
)
async def unstake_tokens(
    request: UnstakeRequest,
    current_agent = Security(get_current_agent),
    db: Session = Depends(get_db)
):
    """Unstake tokens and return them to available balance.
    
    This endpoint handles unstaking:
    - Validates the stake belongs to the agent
    - Checks lock periods if applicable
    - Returns tokens to available balance
    - Supports partial unstaking
    """
    import uuid
    from ...database.models import Stake
    
    # Get stake record
    stake = db.query(Stake).filter(
        and_(
            Stake.stake_id == request.stake_id,
            Stake.agent_id == current_agent,
            Stake.is_active == True
        )
    ).first()
    
    if not stake:
        raise HTTPException(
            status_code=404,
            detail="Active stake not found"
        )
    
    # Check lock period
    if stake.unlock_date and datetime.now(timezone.utc) < stake.unlock_date:
        raise HTTPException(
            status_code=400,
            detail=f"Stake is locked until {stake.unlock_date.isoformat()}"
        )
    
    # Determine unstake amount
    unstake_amount = request.amount if request.amount else stake.amount
    
    if unstake_amount > stake.amount:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot unstake more than staked amount. Staked: {stake.amount}, Requested: {unstake_amount}"
        )
    
    # Get agent profile
    agent = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.agent_id == current_agent
    ).first()
    
    if not agent:
        raise HTTPException(
            status_code=404,
            detail="Agent profile not found"
        )
    
    # Update stake record
    if unstake_amount == stake.amount:
        # Full unstake
        stake.is_active = False
        stake.unstaked_at = datetime.now(timezone.utc)
    else:
        # Partial unstake
        stake.amount -= unstake_amount
    
    # §pass77 Phase B: tag staking unlock (enhanced path).
    db.execute(text("SELECT set_config('teg.entry_type','stake_unlock',true)"))
    # Move tokens from locked to available
    agent.locked_balance = getattr(agent, 'locked_balance', Decimal('0')) - unstake_amount
    agent.token_balance += unstake_amount
    # Keep audited_balance in sync (unstaking is legitimate)
    agent.audited_balance = agent.token_balance
    
    # Create transaction record
    transaction_id = str(uuid.uuid4())
    transaction = TEGTransaction(
        transaction_id=transaction_id,
        sender_agent_id="STAKING_POOL",
        receiver_agent_id=current_agent,
        amount=unstake_amount,
        fee_amount=Decimal("0"),
        status=TransactionStatus.COMPLETED,
        transaction_type="unstake",
        attached_message=f"Unstaking {unstake_amount} tokens",
        timestamp=datetime.now(timezone.utc)
    )
    
    db.add(transaction)
    db.commit()
    db.refresh(agent)
    
    return UnstakeResponse(
        stake_id=request.stake_id,
        agent_id=current_agent,
        amount=str(unstake_amount),
        unstaked_at=datetime.now(timezone.utc),
        transaction_id=transaction_id,
        new_staked_balance=str(agent.locked_balance),
        new_available_balance=str(agent.token_balance)
    )
