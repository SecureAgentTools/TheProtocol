"""
Enhanced Staking API endpoints for Operation Beta Forge.

This module implements the Economic Engine (Strike Package 1) with:
- Idempotent operations
- Atomic transactions
- Governance integration hooks
- Comprehensive error handling
- Real-time TEG Layer integration
"""
from typing import Annotated, Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status, Header, BackgroundTasks, Query, Security
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from decimal import Decimal
from datetime import datetime, timedelta, timezone
import uuid
import logging

from ..database import get_db
from ..core.network_profile import money_knob  # §MONEY-M2: the profile owns this amount
from ..core.staking_gate import (  # §BAFIN
    require_staking_enabled, require_staking_rewards_enabled, staking_rewards_enabled, disabled_tiers_payload,
    staking_enabled,
)
from ..models import (
    Agent,
    Developer,
    IdempotencyKey,
    Stake,
    StakeTransaction,
    StakingReward,
    StakingApyTier
)

from ..schemas_enhanced import (
    StakeRequest,
    UnstakeRequest,
    StakeTransactionRead,
    StakeBalanceResponse,
    StakingStatusResponse
)
from .utils import get_current_agent
from agentvault_registry.security import require_agent_permission  # IRONKEY
from agentvault_registry.core.frame_currency import frame_currency
from ..teg_client import get_teg_client, TEGClientError
from ..event_emitter import get_event_emitter
# from ..crud import crud_governance  # For voting power calculations - TODO: Implement

logger = logging.getLogger(__name__)

# OWL20-PREP: Event Store integration for bank-grade ledger
event_emitter = get_event_emitter()

router = APIRouter()


def get_agent_staked_balance(agent) -> Decimal:
    """Get staked balance from agent, with fallback for missing attribute."""
    return Decimal(str(getattr(agent, 'staked_balance', 0)))


class StakingService:
    """Service class for staking operations with idempotency and atomicity."""
    
    @staticmethod
    async def check_idempotency(
        db: AsyncSession,
        idempotency_key: str,
        agent_id: str
    ) -> Optional[Dict[str, Any]]:
        """Check if this operation was already performed."""
        result = await db.execute(
            select(IdempotencyKey).where(
                and_(
                    IdempotencyKey.key == idempotency_key,
                    IdempotencyKey.agent_id == agent_id,
                    IdempotencyKey.created_at > datetime.now(timezone.utc) - timedelta(hours=24)
                )
            )
        )
        key_record = result.scalar_one_or_none()
        if key_record:
            return key_record.response_data
        return None
    
    @staticmethod
    async def save_idempotency(
        db: AsyncSession,
        idempotency_key: str,
        agent_id: str,
        response_data: Dict[str, Any]
    ):
        """Save idempotency key and response for future requests."""
        key_record = IdempotencyKey(
            key=idempotency_key,
            agent_id=agent_id,
            response_data=response_data,
            created_at=datetime.now(timezone.utc)
        )
        db.add(key_record)
        await db.commit()


@router.post("/stake", summary="Lock units in a position", response_model=StakeTransactionRead, dependencies=[Depends(require_staking_enabled)])  # §BAFIN
async def stake_tokens(
    stake_request: StakeRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_agent: Annotated[Agent, Security(require_agent_permission("staking.manage"))],
    idempotency_key: Annotated[Optional[str], Header()] = None
) -> StakeTransactionRead:
    """
    Lock units in a position (an amount and a lock period in days) for the calling agent.

    Locking is a switch per registry (`STAKING_ENABLED`): where it is off, as on the public network, this answers
    403 and nothing is locked. Where a registry counts votes by locked units, the position carries voting weight. A
    payout on locked units is a separate switch (`STAKING_REWARDS_ENABLED`): discretionary, paid in platform units,
    off on the public network; with it off the position carries no rate.

    The amount must be at least the registry's minimum (`STAKING_MIN_STAKE_AMOUNT`, 10 by default) and at most the
    agent's liquid balance (400 otherwise); 503 when the TEG cannot be reached. An `Idempotency-Key` header makes a
    retry answer the first result for 24 hours. Needs an agent token with the `staking.manage` permission.
    """
    # Check idempotency if key provided
    if idempotency_key:
        existing_response = await StakingService.check_idempotency(
            db, idempotency_key, current_agent.did
        )
        if existing_response is not None:
            logger.info(f"Idempotent request detected for key: {idempotency_key}")
            return StakeTransactionRead(**existing_response)
    
    # Validate stake amount
    if stake_request.amount <= Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lock amount must be positive"
        )
    
    # Check minimum stake requirement
    MIN_STAKE_AMOUNT = money_knob("STAKING_MIN_STAKE_AMOUNT", "10.0")
    if stake_request.amount < MIN_STAKE_AMOUNT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Minimum lock amount is {MIN_STAKE_AMOUNT} {frame_currency()}"
        )
    
    # Begin atomic transaction
    try:
        # Get current TEG balance
        teg_client = get_teg_client()
        current_balance = await teg_client.get_balance(current_agent.did)
        
        if current_balance < stake_request.amount:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient balance. Available: {current_balance} {frame_currency()}, Requested: {stake_request.amount} {frame_currency()}"
            )
        
        # Compute dynamic APY for this lock period. §BAFIN (2026-10-01): a position opened while staking rewards are
        # switched off carries no rate (it is a lock for governance weight, nothing more), so none is stored.
        # §DOCSFIX review (CB-124): computed BEFORE the TEG locks anything. It reads the policy document, the
        # registry's locked total and the TEG treasury, none of which this lock changes, and a read that fails after the
        # lock left locked units on the TEG with no position here to unstake them from.
        if staking_rewards_enabled():
            from ..services.dynamic_apy_engine import policy_apy_engine   # §DOCSFIX CB-124: the rate the policy pays
            apy_engine = await policy_apy_engine(db)
            dynamic_apy = await apy_engine.calculate_current_apy(
                db, stake_request.lock_period
            )
        else:
            dynamic_apy = 0.0

        # Lock tokens in TEG Layer
        stake_result = await teg_client.stake_tokens(
            agent_id=current_agent.did,
            amount=stake_request.amount
        )
        
        # Create stake record in Registry
        # P3/D2: Compute lock_expiry_at and ve_power_snapshot
        stake_time = datetime.now(timezone.utc)
        lock_expiry = stake_time + timedelta(days=stake_request.lock_period) if stake_request.lock_period > 0 else None
        
        from ..services.vetoken_calculator import vetoken_calculator
        ve_snapshot = vetoken_calculator.calculate_position_power(
            amount=stake_request.amount,
            lock_period_days=stake_request.lock_period,
            staked_at=stake_time,
            now=stake_time
        )
        
        stake = Stake(
            id=str(uuid.uuid4()),
            agent_id=current_agent.id,
            agent_did=current_agent.did,
            amount=stake_request.amount,
            staked_at=stake_time,
            is_active=True,
            teg_stake_id=stake_result.get("stake_id"),
            lock_period_days=stake_request.lock_period,
            apy_rate=Decimal(str(dynamic_apy)),
            lock_expiry_at=lock_expiry,
            ve_power_snapshot=ve_snapshot
        )
        db.add(stake)
        
        # Create transaction record
        transaction = StakeTransaction(
            id=str(uuid.uuid4()),
            agent_id=current_agent.id,
            stake_id=stake.id,
            transaction_type="stake",
            amount=stake_request.amount,
            timestamp=datetime.now(timezone.utc),
            teg_transaction_id=stake_result.get("transaction_id")
        )
        db.add(transaction)
        
        # Update agent's staked balance
        current_staked = get_agent_staked_balance(current_agent)
        new_staked_balance = current_staked + stake_request.amount
        
        if hasattr(current_agent, 'staked_balance'):
            current_agent.staked_balance = new_staked_balance
        # Also update liquid_balance cache so DB stays in sync with ES/TEG
        if hasattr(current_agent, 'liquid_balance'):
            current_agent.liquid_balance = max(Decimal("0"), Decimal(str(current_agent.liquid_balance)) - stake_request.amount)

        # Commit database changes
        await db.commit()
        await db.refresh(stake)
        await db.refresh(transaction)
        
        # Prepare response
        response_data = {
            "transaction_id": transaction.id,
            "stake_id": stake.id,
            "agent_did": current_agent.did,
            "amount": str(stake_request.amount),
            "transaction_type": "stake",
            "timestamp": transaction.timestamp.isoformat(),
            "status": "completed",
            "new_staked_balance": str(new_staked_balance),
            "new_liquid_balance": str(current_balance - stake_request.amount)
        }
        
        # Save idempotency key if provided
        if idempotency_key:
            await StakingService.save_idempotency(
                db, idempotency_key, current_agent.did, response_data
            )
        
        # OWL20-PREP: Emit TokensStaked to Event Store (async)
        background_tasks.add_task(
            emit_staking_event,
            event_type="stake.completed",
            agent_did=current_agent.did,
            amount=stake_request.amount,
            # §PlanB-① (2026-06-01): emit the TEG transaction id (what getMyTegTransactions
            # returns — the lock movement), NOT the local StakeTransaction.id, so
            # getTegTransactionDetail resolves the id the user actually sees.
            transaction_id=(transaction.teg_transaction_id or transaction.id),
            stake_id=stake.id,
            # §MEMBERSHIP (agentvault2-15's finding): every TokensStaked said 7 days, the helper's default.
            lock_period_days=stake.lock_period_days,
        )
        
        logger.info(f"Stake completed: {transaction.id} for agent {current_agent.did}")
        # A1 (2026-07-24): staking.position_created was subscribable but never fired.
        import asyncio as _aio
        from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
        _aio.create_task(dispatch_webhook_for_agents(
            "staking.position_created",
            {"agent_did": current_agent.did, "amount": str(stake_request.amount),
             "stake_id": stake.id, "transaction_id": transaction.teg_transaction_id or transaction.id},
            [current_agent.did], source_label="staking.stake"))
        return StakeTransactionRead(**response_data)
        
    except TEGClientError as e:
        logger.error(f"TEG communication error during staking: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TEG Layer temporarily unavailable. Please try again."
        )
    except Exception as e:
        logger.exception(f"Unexpected error during staking: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process the lock request"
        )


def _positions_for_unstake(active_stakes, position_id, amount, now):
    """§FESUITE: the positions an unstake may touch.

    The console lists positions and offers Unstake on each, while this endpoint took only an amount and released it from
    the unlocked positions oldest first: a person who pressed Unstake on a locked position saw "Unstaked." while a
    different position was released. Without position_id the original contract stands (every existing caller). With
    it, only that position: a locked one is refused with its unlock date, an amount above it is refused, and an id that
    is not an active position of this agent is a 404. Nothing is touched on any refusal.
    """
    if not position_id:
        return list(active_stakes)
    chosen = [s for s in active_stakes if str(s.id) == str(position_id)]
    if not chosen:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active lock position with that id for this agent. Nothing was unlocked.",
        )
    pos = chosen[0]
    lock_days = getattr(pos, "lock_period_days", 0) or 0
    if lock_days > 0:
        unlock_at = pos.staked_at + timedelta(days=lock_days)
        if now < unlock_at:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This position is locked until {unlock_at.date().isoformat()} ({lock_days}-day lock). "
                    "Nothing was unlocked."
                ),
            )
    if amount > pos.amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"This position holds {pos.amount} {frame_currency()}; {amount} {frame_currency()} was asked. "
                "Nothing was unlocked."
            ),
        )
    return [pos]


@router.post("/unstake", summary="Release locked units", response_model=StakeTransactionRead)
async def unstake_tokens(
    unstake_request: UnstakeRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_agent: Annotated[Agent, Security(require_agent_permission("staking.manage"))],
    idempotency_key: Annotated[Optional[str], Header()] = None
) -> StakeTransactionRead:
    """
    Release locked units of the calling agent back to its liquid balance.

    Without `position_id`, the amount is taken from the agent's positions whose lock has ended, oldest first, and
    may span several positions (a partly released position keeps the rest locked); 403 when the unlocked positions
    hold less than the amount. With `position_id`, only that position is touched: a position still locked is refused
    (403, with its unlock date), an amount above the position is refused (400), and an id that is not an active
    position of this agent answers 404. Nothing is released on any refusal.

    This works where locking is switched off, so locked units are never stuck. An `Idempotency-Key` header makes a
    retry answer the first result for 24 hours. Needs an agent token with the `staking.manage` permission.
    """
    # Check idempotency if key provided
    if idempotency_key:
        existing_response = await StakingService.check_idempotency(
            db, idempotency_key, current_agent.did
        )
        if existing_response is not None:
            return StakeTransactionRead(**existing_response)
    
    # Validate unstake amount
    if unstake_request.amount <= Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unlock amount must be positive"
        )
    
    # Check current staked balance
    current_staked = get_agent_staked_balance(current_agent)
    if current_staked < unstake_request.amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient locked balance. Locked: {current_staked} {frame_currency()}, Requested: {unstake_request.amount} {frame_currency()}"
        )
    
    try:
        # Get active stakes for partial unstaking
        result = await db.execute(
            select(Stake).where(
                and_(
                    Stake.agent_id == current_agent.id,
                    Stake.is_active == True
                )
            ).order_by(Stake.staked_at.asc())  # FIFO unstaking
        )
        active_stakes = result.scalars().all()
        
        if not active_stakes:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active locks found"
            )
        
        # Pre-validate: check which positions are unlocked and available (dry run)
        now = datetime.now(timezone.utc)
        # §FESUITE: one named position, or the original oldest-first walk (refusals touch nothing)
        active_stakes = _positions_for_unstake(active_stakes, unstake_request.position_id, unstake_request.amount, now)
        available_unlocked = Decimal("0")
        for stake in active_stakes:
            lock_days = getattr(stake, 'lock_period_days', 0) or 0
            if lock_days > 0:
                unlock_at = stake.staked_at + timedelta(days=lock_days)
                if now < unlock_at:
                    continue  # Still locked, skip
            available_unlocked += stake.amount
        
        if available_unlocked < unstake_request.amount:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient unlocked balance. Available: {available_unlocked} {frame_currency()}, Requested: {unstake_request.amount} {frame_currency()}. Some positions are still locked."
            )
        
        # Unlock tokens in TEG Layer (safe — we validated above)
        teg_client = get_teg_client()
        unstake_result = await teg_client.unstake_tokens(
            agent_id=current_agent.did,
            amount=unstake_request.amount
        )
        
        # Process unstaking (FIFO) — lock_period_days controls cooldown per position
        remaining_to_unstake = unstake_request.amount
        unstaked_stakes = []
        
        for stake in active_stakes:
            if remaining_to_unstake <= 0:
                break
            
            # Check this position's lock period (flexible = 0 = no cooldown)
            lock_days = getattr(stake, 'lock_period_days', 0) or 0
            if lock_days > 0:
                unlock_at = stake.staked_at + timedelta(days=lock_days)
                if now < unlock_at:
                    continue  # Skip locked positions, try next in FIFO
                
            if stake.amount <= remaining_to_unstake:
                # Fully unstake this stake
                stake.is_active = False
                stake.unstaked_at = now
                remaining_to_unstake -= stake.amount
                unstaked_stakes.append(stake)
            else:
                # Partially unstake
                unstake_amount = remaining_to_unstake
                # §V0048 F6 fix: `remaining_amount` was referenced below but NEVER defined
                # → NameError → 500 on EVERY partial unstake (any unstake that splits a
                # larger FIFO position), AFTER the TEG unlock had already committed → the
                # registry stake was rolled back while TEG/ES decremented → staked drift.
                # It is the staked amount left in this position after the partial removal.
                remaining_amount = stake.amount - unstake_amount

                # Create new stake for remaining amount
                # P3/D2: Preserve lock_expiry_at, recalculate ve_power for reduced amount
                # (ve scales linearly with the remaining principal: V_new = V * remaining/original).
                new_stake = Stake(
                    id=str(uuid.uuid4()),
                    agent_id=current_agent.id,
                    agent_did=current_agent.did,
                    amount=remaining_amount,
                    staked_at=stake.staked_at,
                    is_active=True,
                    teg_stake_id=stake.teg_stake_id,
                    lock_period_days=stake.lock_period_days,
                    apy_rate=stake.apy_rate,
                    lock_expiry_at=getattr(stake, 'lock_expiry_at', None),
                    ve_power_snapshot=float(remaining_amount) * (getattr(stake, 've_power_snapshot', 0.0) / max(float(stake.amount), 1.0))
                )
                db.add(new_stake)
                
                # Update original stake
                stake.amount = unstake_amount
                stake.is_active = False
                stake.unstaked_at = now
                unstaked_stakes.append(stake)
                
                remaining_to_unstake = Decimal("0")
        
        # Create unstake transaction
        transaction = StakeTransaction(
            id=str(uuid.uuid4()),
            agent_id=current_agent.id,
            stake_id=unstaked_stakes[0].id if unstaked_stakes else None,
            transaction_type="unstake",
            amount=unstake_request.amount,
            timestamp=datetime.now(timezone.utc),
            teg_transaction_id=unstake_result.get("transaction_id")
        )
        db.add(transaction)
        
        # Update agent's staked balance
        new_staked_balance = get_agent_staked_balance(current_agent) - unstake_request.amount
        if hasattr(current_agent, 'staked_balance'):
            current_agent.staked_balance = new_staked_balance
        # Also update liquid_balance cache so DB stays in sync with ES/TEG
        if hasattr(current_agent, 'liquid_balance'):
            current_agent.liquid_balance = Decimal(str(current_agent.liquid_balance)) + unstake_request.amount

        # Commit changes
        await db.commit()
        await db.refresh(transaction)

        # Get new liquid balance from TEG
        new_liquid_balance = await teg_client.get_balance(current_agent.did)
        
        # Prepare response
        response_data = {
            "transaction_id": transaction.id,
            "stake_id": transaction.stake_id,
            "agent_did": current_agent.did,
            "amount": str(unstake_request.amount),
            "transaction_type": "unstake",
            "timestamp": transaction.timestamp.isoformat(),
            "status": "completed",
            "new_staked_balance": str(new_staked_balance),
            "new_liquid_balance": str(new_liquid_balance)
        }
        
        # Save idempotency key if provided
        if idempotency_key:
            await StakingService.save_idempotency(
                db, idempotency_key, current_agent.did, response_data
            )
        
        # OWL20-PREP: Emit TokensUnstaked to Event Store (async)
        background_tasks.add_task(
            emit_staking_event,
            event_type="unstake.completed",
            agent_did=current_agent.did,
            amount=unstake_request.amount,
            # §PlanB-① (2026-06-01): emit the TEG transaction id (what getMyTegTransactions shows), not the local row id.
            transaction_id=(transaction.teg_transaction_id or transaction.id),
            stake_id=unstaked_stakes[0].id if unstaked_stakes else None
        )
        
        logger.info(f"Unstake completed: {transaction.id} for agent {current_agent.did}")
        # A1 (2026-07-24): staking.position_closed was subscribable but never fired.
        import asyncio as _aio
        from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
        _aio.create_task(dispatch_webhook_for_agents(
            "staking.position_closed",
            {"agent_did": current_agent.did, "amount": str(unstake_request.amount),
             "transaction_id": transaction.teg_transaction_id or transaction.id},
            [current_agent.did], source_label="staking.unstake"))
        return StakeTransactionRead(**response_data)
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        logger.exception(f"Unexpected error during unstaking: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process the unlock request"
        )


@router.get("/balance", response_model=StakeBalanceResponse, summary="Get the locked balance")
async def get_stake_balance(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_agent: Annotated[Agent, Security(get_current_agent)]
) -> StakeBalanceResponse:
    """
    The calling agent's balance in the frame's units: liquid (from the TEG), locked and total, with the number of
    active locks and any pending payout on locked units.

    `voting_power` is computed from locked units only; where the registry counts votes by membership, as on the
    public network, read GET /api/v1/governance/voting-power instead. When the TEG cannot be reached, the answer
    carries a `warning` and a liquid balance of 0.
    """
    try:
        # Get liquid balance from TEG Layer
        teg_client = get_teg_client()
        liquid_balance = await teg_client.get_balance(current_agent.did)
        
        # Get staking rewards (if any)
        try:
            rewards_info = await teg_client.get_pending_rewards(current_agent.did)
            pending_rewards = rewards_info.get("pending_rewards", Decimal("0"))
        except Exception:
            pending_rewards = Decimal("0")
        
        # Get staked balance safely
        staked_balance = get_agent_staked_balance(current_agent)
        
        # Calculate voting power based on stake
        voting_power = calculate_voting_power(staked_balance)
        
        # Get active stakes count
        result = await db.execute(
            select(Stake).where(
                and_(
                    Stake.agent_id == current_agent.id,
                    Stake.is_active == True
                )
            )
        )
        active_stakes = result.scalars().all()
        
        return StakeBalanceResponse(
            agent_did=current_agent.did,
            liquid_balance=liquid_balance,
            staked_balance=staked_balance,
            total_balance=liquid_balance + staked_balance,
            pending_rewards=pending_rewards,
            voting_power=voting_power,
            active_stakes_count=len(active_stakes),
            last_updated=datetime.now(timezone.utc)
        )
        
    except TEGClientError as e:
        logger.error(f"Failed to get TEG balance: {str(e)}")
        # Return cached data if TEG is unavailable
        return StakeBalanceResponse(
            agent_did=current_agent.did,
            liquid_balance=Decimal("0"),  # Unknown
            staked_balance=staked_balance,
            total_balance=staked_balance,  # Minimum known
            pending_rewards=Decimal("0"),
            voting_power=calculate_voting_power(staked_balance),
            active_stakes_count=0,
            last_updated=datetime.now(timezone.utc),
            warning="TEG Layer temporarily unavailable. Showing cached data."
        )


@router.get("/status", response_model=StakingStatusResponse, summary="Get the lock status")
async def get_staking_status(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_agent: Annotated[Agent, Security(get_current_agent)]
) -> StakingStatusResponse:
    """
    Get the detailed lock status for debugging and monitoring.
    
    This endpoint provides comprehensive information about:
    - System integration status
    - Agent's balance across systems
    - Active locks and their details
    - Lock parameters and limits
    - Recent lock activity
    
    Returns:
        StakingStatusResponse: Detailed system and agent status
    """
    teg_client = get_teg_client()
    
    # Get active stakes
    result = await db.execute(
        select(Stake).where(
            and_(
                Stake.agent_id == current_agent.id,
                Stake.is_active == True
            )
        ).order_by(Stake.staked_at.desc())
    )
    active_stakes = result.scalars().all()
    
    # Get recent transactions
    tx_result = await db.execute(
        select(StakeTransaction).where(
            StakeTransaction.agent_id == current_agent.id
        ).order_by(StakeTransaction.timestamp.desc()).limit(10)
    )
    recent_transactions = tx_result.scalars().all()
    
    # Check TEG connection
    teg_status = {
        "connected": False,
        "balance": None,
        "error": None
    }
    
    try:
        teg_balance = await teg_client.get_balance(current_agent.did)
        teg_status["connected"] = True
        teg_status["balance"] = str(teg_balance)
    except Exception as e:
        teg_status["error"] = str(e)
    
    # Get staked balance safely
    staked_balance = get_agent_staked_balance(current_agent)
    
    # Calculate statistics
    total_staked = sum(stake.amount for stake in active_stakes)
    oldest_stake = min((stake.staked_at for stake in active_stakes), default=None)
    
    return StakingStatusResponse(
        # §MEMBERSHIP (2026-10-02, agentvault2-15's finding): these were literals (staking always on, a 10.0
        # minimum, a 7-day cooldown nothing enforces, daily rewards). They now say what this registry does:
        # the switches, the minimum knob, and no cooldown beyond each position's own lock period.
        system_status={
            "integration_active": True,
            "teg_connection": teg_status,
            "staking_enabled": staking_enabled(),
            "staking_rewards_enabled": staking_rewards_enabled(),
            "min_stake_amount": str(money_knob("STAKING_MIN_STAKE_AMOUNT", "10.0")),
            "unstake_cooldown_days": None,
            "lock_period_enforced_per_position": True,
            "reward_distribution_frequency": "daily" if staking_rewards_enabled() else None
        },
        agent_status={
            "agent_did": current_agent.did,
            "registry_staked_balance": str(staked_balance),
            "teg_liquid_balance": teg_status["balance"],
            "active_stakes_count": len(active_stakes),
            "total_staked": str(total_staked),
            "oldest_stake_date": oldest_stake.isoformat() if oldest_stake else None,
            "voting_power": str(calculate_voting_power(staked_balance))
        },
        recent_activity={
            "transactions": [
                {
                    "id": tx.id,
                    "type": tx.transaction_type,
                    "amount": str(tx.amount),
                    "timestamp": tx.timestamp.isoformat()
                }
                for tx in recent_transactions
            ]
        },
        active_stakes_detail=[
            {
                "stake_id": stake.id,
                "amount": str(stake.amount),
                "staked_at": stake.staked_at.isoformat(),
                "days_staked": (datetime.now(timezone.utc) - stake.staked_at).days,
                "can_unstake": (datetime.now(timezone.utc) - stake.staked_at).days >= (getattr(stake, 'lock_period_days', 0) or 0)
            }
            for stake in active_stakes
        ]
    )


# Background task functions — OWL20-PREP: Real Event Store emission
async def emit_staking_event(event_type: str, agent_did: str, amount: Decimal, transaction_id: str, **kwargs):
    """Emit staking event to Event Store for immutable ledger."""
    try:
        if event_type == "stake.completed":
            success = await event_emitter.emit_tokens_staked(
                agent_did=agent_did,
                amount=str(amount),
                pool_id=kwargs.get("stake_id", transaction_id),
                lock_period_days=kwargs.get("lock_period_days", 7),
                expected_apy=kwargs.get("expected_apy"),
                transaction_id=transaction_id,  # §PlanB-① carry tx id → detail resolves
            )
        elif event_type == "unstake.completed":
            success = await event_emitter.emit_tokens_unstaked(
                agent_did=agent_did,
                amount=str(amount),
                pool_id=kwargs.get("stake_id", transaction_id),
                rewards_earned=kwargs.get("rewards_earned"),
                transaction_id=transaction_id,  # §PlanB-① carry tx id → detail resolves
            )
        elif event_type == "claim_reward.completed":
            success = await event_emitter.emit_tokens_issued(
                agent_did=agent_did,
                amount=str(amount),
                transaction_id=transaction_id,
                issued_by="staking_rewards",
                reason="reward_claim"
            )
        else:
            success = await event_emitter.emit(
                event_type=event_type,
                aggregate_id=agent_did,
                data={"amount": str(amount), "transaction_id": transaction_id}
            )
        
        if success:
            logger.info(f"✅ Event Store: {event_type} for {agent_did}, amount={amount}")
        else:
            logger.error(f"❌ Event Store: Failed to emit {event_type} for {agent_did}")
    except Exception as e:
        logger.error(f"❌ Event Store emission error ({event_type}): {str(e)}")


async def update_voting_power(agent_id: str, new_stake_amount: Decimal):
    """Legacy no-op. Governance now uses VeTokenCalculator for time-weighted power."""
    pass


def calculate_voting_power(staked_amount: Decimal) -> Decimal:
    """
    LEGACY: Calculate voting power based on staked amount (simple sqrt).
    
    P3/D2 NOTE: Governance now uses VeTokenCalculator for time-weighted
    quadratic power. This function is kept for backwards compatibility
    in staking stats display only. Governance endpoints use vetoken_calculator.
    """
    if staked_amount <= 0:
        return Decimal("0")
    
    # Square root curve with multiplier (native Decimal sqrt, no float conversion)
    voting_power = staked_amount.sqrt()
    
    # Round to 2 decimal places
    return voting_power.quantize(Decimal("0.01"))


@router.get("/my-stats", summary="Get my lock figures")
async def get_my_staking_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_agent: Annotated[Agent, Security(get_current_agent)]
) -> Dict[str, Any]:
    """
    Get the lock figures of the current agent.
    
    Returns aggregate statistics including:
    - Total locked amount
    - Payouts on locked units available
    - Active locks summary
    - Projected payouts (where this registry pays one)
    
    Returns:
        Dict containing the lock figures
    """
    logger.info(f"Getting staking stats for agent {current_agent.did}")
    
    # Get active stakes for this agent
    result = await db.execute(
        select(Stake).where(
            and_(
                Stake.agent_id == current_agent.id,
                Stake.is_active == True
            )
        )
    )
    active_stakes = result.scalars().all()
    
    # Calculate total staked
    total_staked = sum(stake.amount for stake in active_stakes)
    
    # Get unclaimed rewards
    rewards_result = await db.execute(
        select(StakingReward).where(
            and_(
                StakingReward.agent_id == current_agent.id,
                StakingReward.is_claimed == False
            )
        )
    )
    unclaimed_rewards = rewards_result.scalars().all()
    available_rewards = sum(reward.amount for reward in unclaimed_rewards)
    
    # Create position summaries
    positions = [
        {
            "id": stake.id,
            "amount": str(stake.amount),
            "startDate": stake.staked_at.isoformat(),
            "lockPeriod": stake.lock_period_days,
            # §BAFIN: no rate and no projected reward where staking rewards are switched off.
            "apy": float(stake.apy_rate) if staking_rewards_enabled() else 0.0,
            "rewards": str(stake.amount * stake.apy_rate / 100 / 12) if staking_rewards_enabled() else "0"  # Monthly rewards estimate
        }
        for stake in active_stakes
    ]
    
    return {
        "totalStaked": str(total_staked),
        "availableRewards": str(available_rewards),
        "stakingPositions": positions,
        "agent_did": current_agent.did
    }


@router.get("/global-stats", summary="Get the network-wide lock figures")
async def get_global_staking_stats(
    db: Annotated[AsyncSession, Depends(get_db)]
) -> Dict[str, Any]:
    """
    Network-wide lock figures of this registry: the units locked in active locks (`totalValueLocked`), the
    number of agents with a lock (`totalStakers`), the payout units marked claimed (`rewardsDistributed`) and
    `averageApy`, the lock-weighted payout share, which is 0 where the payout switch (`STAKING_REWARDS_ENABLED`) is off,
    as on the public network. Public, no auth.
    """
    # SQL aggregation — avoids loading all rows into Python

    agg_result = await db.execute(
        select(
            func.coalesce(func.sum(Stake.amount), 0),
            func.count(func.distinct(Stake.agent_id)),
            func.coalesce(func.sum(Stake.amount * Stake.apy_rate), 0),
        ).where(Stake.is_active == True)
    )
    row = agg_result.one()
    total_value_locked = row[0]
    unique_stakers = row[1]
    total_weighted_apy = row[2]
    average_apy = float(total_weighted_apy / total_value_locked) if total_value_locked > 0 else 0
    if not staking_rewards_enabled():
        average_apy = 0  # §BAFIN: no rate is shown where staking rewards are switched off

    # Get total distributed rewards via SQL
    rewards_agg = await db.execute(
        select(func.coalesce(func.sum(StakingReward.amount), 0)).where(
            StakingReward.is_claimed == True
        )
    )
    rewards_distributed = rewards_agg.scalar()
    
    return {
        "totalValueLocked": str(total_value_locked),
        "averageApy": average_apy,
        "totalStakers": unique_stakers,
        "rewardsDistributed": str(rewards_distributed)
    }


@router.get("/apy-tiers", summary="The lock tiers (none where locking or its payouts are off)")
async def get_apy_tiers(
    db: Annotated[AsyncSession, Depends(get_db)]
) -> Dict[str, Any]:
    """
    The lock tiers a registry publishes: lock periods with the rate its payout program would pay on each,
    computed from how much of the supply is locked.

    A payout on locked units is a switch per registry (`STAKING_REWARDS_ENABLED`): discretionary, paid in platform
    units, off on the public network, where this answers no tiers. Public, no auth.
    """
    # §BAFIN: a registry with staking rewards switched off publishes no rate at all.
    if not staking_rewards_enabled():
        return disabled_tiers_payload()
    from ..services.dynamic_apy_engine import policy_apy_engine   # §DOCSFIX CB-124: the tiers the policy pays
    engine = await policy_apy_engine(db)
    return await engine.get_current_tiers(db)


@router.get("/my-positions", summary="Get my locks")
async def get_my_staking_positions(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_agent: Annotated[Agent, Security(get_current_agent)]
) -> List[Dict[str, Any]]:
    """
    Get the detailed locks of the current agent.
    
    Returns detailed information for each position:
    - Position ID and amount
    - Lock period and unlock date
    - Payouts on locked units made and claimable
    - Current status
    
    Returns:
        List of locks with details
    """
    # Compute current dynamic APY for display (§DOCSFIX CB-124: the policy's engine, the rate the distribution pays)
    from ..services.dynamic_apy_engine import policy_apy_engine
    apy_engine = await policy_apy_engine(db)
    current_tvl = await apy_engine.get_current_tvl_pct(db)
    
    # Get all stakes for this agent (both active and inactive)
    result = await db.execute(
        select(Stake).where(
            Stake.agent_id == current_agent.id
        ).order_by(Stake.staked_at.desc())
    )
    stakes = result.scalars().all()

    # Batch-load all rewards for this agent's stakes in one query
    all_stake_ids = [s.id for s in stakes]
    rewards_by_stake = {}
    if all_stake_ids:
        all_rewards_result = await db.execute(
            select(StakingReward).where(StakingReward.stake_id.in_(all_stake_ids))
        )
        for r in all_rewards_result.scalars().all():
            rewards_by_stake.setdefault(r.stake_id, []).append(r)

    positions = []
    for stake in stakes:
        stake_rewards = rewards_by_stake.get(stake.id, [])

        earned_rewards = sum(r.amount for r in stake_rewards)
        claimed_rewards = sum(r.amount for r in stake_rewards if r.is_claimed)
        available_rewards = earned_rewards - claimed_rewards

        # Calculate unlock date
        unlock_date = stake.staked_at + timedelta(days=stake.lock_period_days)
        can_unstake = datetime.now(timezone.utc) >= unlock_date and stake.is_active
        
        # Use dynamic APY based on position's lock period + current TVL
        dynamic_apy = apy_engine.calculate_apy(stake.lock_period_days, current_tvl)
        if not staking_rewards_enabled():
            dynamic_apy = 0.0  # §BAFIN: no rate is shown where staking rewards are switched off
        
        position = {
            "id": stake.id,
            "agent_did": stake.agent_did,
            "amount": str(stake.amount),
            "startDate": stake.staked_at.isoformat(),
            "lockPeriod": stake.lock_period_days,
            "unlockDate": unlock_date.isoformat(),
            "apy": dynamic_apy,
            "apy_at_creation": float(stake.apy_rate) if staking_rewards_enabled() else 0.0,
            "status": "active" if stake.is_active else "unstaked",
            "canUnstake": can_unstake,
            "rewards": {
                "earned": str(earned_rewards),
                "claimed": str(claimed_rewards),
                "available": str(available_rewards)
            }
        }
        positions.append(position)
    
    return positions


@router.post("/claim-rewards", summary="Retired payout claim (404; 403 where payouts are off)", dependencies=[Depends(require_staking_rewards_enabled)])  # §BAFIN
async def claim_staking_rewards(
    position_id: Optional[str] = None,
    background_tasks: BackgroundTasks = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_agent: Annotated[Agent, Security(require_agent_permission("staking.manage"))] = None,
    idempotency_key: Annotated[Optional[str], Header()] = None
) -> Dict[str, Any]:
    """
    Retired: claims nothing on a default registry.

    A payout on locked units is not claimed: where a registry pays one, its distributor pays it to the agent's
    liquid balance automatically. This route answers 403 where the payout switch (`STAKING_REWARDS_ENABLED`) is off,
    as on the public network, and 404 otherwise.

    \f
    Claim available staking rewards.
    
    Claims rewards for specified position or all positions.
    Rewards are transferred to the agent's liquid balance.
    
    Args:
        position_id: Optional specific position to claim from
        db: Database session
        current_agent: Authenticated agent
        idempotency_key: Optional key for idempotent operations
        
    Returns:
        Dict containing claim transaction details
        
    Raises:
        HTTPException 404: Position not found
        HTTPException 400: No payouts to claim

    §MONEY-R22 / D9 (2026-09-04): DISABLED BY DEFAULT — this rail is dead AND
    would double-book if it were repaired. It calls `teg_client.claim_rewards`,
    which does not exist (so it 500s today), and on success it would emit
    `TokensIssued reason=reward_claim` for rewards the waterfall has ALREADY paid
    as `TokensTransferred`. That second emit would raise tokens_issued with no
    matching balance movement — a genuine Δ breach, unlike most of this batch.

    Rewards are claimed nowhere because they are paid. Gated rather than deleted
    (D8); set REGISTRY_STAKING_CLAIM_REWARDS_ENABLED=true to restore.
    """
    import os as _os
    if (_os.getenv("REGISTRY_STAKING_CLAIM_REWARDS_ENABLED", "false") or "false").strip().lower() \
            not in ("1", "true", "yes", "on"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=("Payouts on locked units are not claimed: where a registry makes them, the distributor "
                    "pays them automatically from the fee_collector/treasury waterfall."),
        )
    # Check idempotency if key provided
    if idempotency_key:
        existing_response = await StakingService.check_idempotency(
            db, idempotency_key, current_agent.did
        )
        if existing_response is not None:
            return existing_response
    
    try:
        # Build query for rewards
        rewards_query = select(StakingReward).where(
            and_(
                StakingReward.agent_id == current_agent.id,
                StakingReward.is_claimed == False
            )
        )
        
        # If position_id specified, filter by stake
        if position_id:
            # Verify stake ownership
            stake_result = await db.execute(
                select(Stake).where(
                    and_(
                        Stake.id == position_id,
                        Stake.agent_id == current_agent.id
                    )
                )
            )
            stake = stake_result.scalar_one_or_none()
            if not stake:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Position not found"
                )
            
            rewards_query = rewards_query.where(StakingReward.stake_id == position_id)
        
        # Get unclaimed rewards — FOR UPDATE locks the reward rows so a concurrent
        # claim serializes behind this one and finds them already claimed (closes the
        # double-pay race where two claims both read the same unclaimed set and both pay).
        result = await db.execute(rewards_query.with_for_update())
        unclaimed_rewards = result.scalars().all()
        
        if not unclaimed_rewards:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No payouts to claim"
            )
        
        # Calculate total claim amount
        total_claim = sum(reward.amount for reward in unclaimed_rewards)
        
        # Transfer rewards via TEG
        teg_client = get_teg_client()
        claim_result = await teg_client.claim_rewards(
            agent_id=current_agent.did,
            amount=total_claim
        )
        
        # Create claim transaction
        transaction = StakeTransaction(
            id=str(uuid.uuid4()),
            agent_id=current_agent.id,
            stake_id=position_id,
            transaction_type="claim_reward",
            amount=total_claim,
            timestamp=datetime.now(timezone.utc),
            teg_transaction_id=claim_result.get("transaction_id"),
            status="completed",
            transaction_metadata={
                "rewards_claimed": len(unclaimed_rewards),
                "positions": list(set(r.stake_id for r in unclaimed_rewards))
            }
        )
        db.add(transaction)
        
        # Mark rewards as claimed
        for reward in unclaimed_rewards:
            reward.is_claimed = True
            reward.claimed_at = datetime.now(timezone.utc)
            reward.claim_transaction_id = transaction.id
        
        # Update agent's liquid balance (if stored locally)
        if hasattr(current_agent, 'liquid_balance'):
            current_agent.liquid_balance += total_claim
        
        await db.commit()
        
        response_data = {
            "transaction_id": transaction.id,
            "amount_claimed": str(total_claim),
            "timestamp": transaction.timestamp.isoformat(),
            "status": "completed",
            "positions_claimed": transaction.transaction_metadata["positions"]
        }
        
        # Save idempotency key if provided
        if idempotency_key:
            await StakingService.save_idempotency(
                db, idempotency_key, current_agent.did, response_data
            )
        
        # OWL20-PREP: Emit TokensIssued (reward claim) to Event Store
        if background_tasks:
            background_tasks.add_task(
                emit_staking_event,
                event_type="claim_reward.completed",
                agent_did=current_agent.did,
                amount=total_claim,
                transaction_id=transaction.id
            )
        
        logger.info(f"Rewards claimed: {transaction.id} for agent {current_agent.did}")
        # A1 (2026-07-24): staking.rewards_claimed was subscribable but never fired.
        import asyncio as _aio
        from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
        _aio.create_task(dispatch_webhook_for_agents(
            "staking.rewards_claimed",
            {"agent_did": current_agent.did, "amount": str(total_claim), "transaction_id": transaction.id},
            [current_agent.did], source_label="staking.claim"))
        return response_data
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        logger.exception(f"Error claiming rewards: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to claim payouts"
        )


@router.get("/history", summary="Get my lock and release history")
async def get_staking_history(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_agent: Annotated[Agent, Security(get_current_agent)] = None
) -> Dict[str, Any]:
    """
    Get the lock and release history of the current agent.
    
    Returns paginated transaction history including:
    - Lock and release transactions
    - Payout claims
    - Transaction details and status
    
    Args:
        limit: Maximum number of transactions to return
        offset: Number of transactions to skip
        db: Database session
        current_agent: Authenticated agent
        
    Returns:
        Dict containing transactions and pagination info
    """
    # Get total count via SQL (avoid loading all rows)

    count_result = await db.execute(
        select(func.count(StakeTransaction.id)).where(
            StakeTransaction.agent_id == current_agent.id
        )
    )
    total_count = count_result.scalar()
    
    # Get paginated transactions
    result = await db.execute(
        select(StakeTransaction).where(
            StakeTransaction.agent_id == current_agent.id
        ).order_by(
            StakeTransaction.timestamp.desc()
        ).limit(limit).offset(offset)
    )
    transactions = result.scalars().all()
    
    # Batch-load all referenced stakes in one query
    stake_ids = [tx.stake_id for tx in transactions if tx.stake_id]
    stakes_map = {}
    if stake_ids:
        stakes_result = await db.execute(
            select(Stake).where(Stake.id.in_(stake_ids))
        )
        stakes_map = {s.id: s for s in stakes_result.scalars().all()}

    # Format transactions
    formatted_transactions = []
    for tx in transactions:
        # Get associated stake info if available
        stake_info = None
        if tx.stake_id:
            stake = stakes_map.get(tx.stake_id)
            if stake:
                # §MEMBERSHIP (2026-10-02, agentvault2-15's finding): with rewards off no rate leaves this
                # registry, including the rate a position stored when it was opened (the staking_gate rule).
                stake_info = {
                    "apy": float(stake.apy_rate) if staking_rewards_enabled() else 0.0,
                    "lock_period": stake.lock_period_days
                }

        transaction_data = {
            "id": tx.id,
            "type": tx.transaction_type,
            "amount": str(tx.amount),
            "timestamp": tx.timestamp.isoformat(),
            "status": tx.status,
            "position_id": tx.stake_id,
            "details": stake_info or tx.transaction_metadata
        }
        formatted_transactions.append(transaction_data)
    
    return {
        "transactions": formatted_transactions,
        "total": total_count,
        "limit": limit,
        "offset": offset
    }
