"""
API endpoints for staking functionality in the economic engine.

UPDATED: Now integrates with TEG Layer for real token operations.
"""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status, Security
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal

from ..database import get_db
from ..crud import crud_staking_integrated as crud_staking  # Now integrated with TEG
from ..schemas import (
    StakeRequest,
    UnstakeRequest,
    StakeTransactionRead,
    StakeBalanceResponse
)
from ..models import Agent, StakeTransaction
from .utils import get_current_agent
from ..teg_client import get_teg_client, TEGClientError
from ..event_emitter import get_event_emitter
from ..core.frame_currency import frame_currency
from sqlalchemy import select, func
import logging

# Import WebSocket notification function
try:
    from .websocket import notify_clients
except ImportError:
    # WebSocket might not be available in all contexts
    async def notify_clients(*args, **kwargs):
        pass

logger = logging.getLogger(__name__)

event_emitter = get_event_emitter()

router = APIRouter()


@router.post("/stake", response_model=StakeTransactionRead)
async def stake_tokens(
    stake_request: StakeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_agent: Annotated[Agent, Security(get_current_agent)]
) -> StakeTransactionRead:
    """
    Stake tokens by locking them in the TEG Layer.
    
    This endpoint allows an authenticated agent to stake their AVT tokens.
    The tokens are locked in the TEG Layer and cannot be used for transfers
    while staked. Staking may provide benefits like increased reputation
    or voting power in the system.
    
    Process:
    1. Checks available balance in TEG Layer
    2. Locks the tokens in TEG
    3. Records the staking in Registry
    
    Returns:
        StakeTransactionRead: Details of the stake transaction
        
    Raises:
        HTTPException: If insufficient balance or TEG communication fails
    """
    try:
        transaction = await crud_staking.stake_tokens(
            db=db,
            agent_did=current_agent.did,
            amount=stake_request.amount
        )
        
        if transaction is None:
            # Get the actual TEG balance for a more informative error
            try:
                teg_client = get_teg_client()
                teg_balance = await teg_client.get_balance(current_agent.did)
                detail = f"Insufficient balance to lock. Available: {teg_balance} {frame_currency()}, Requested: {stake_request.amount} {frame_currency()}"
            except:
                detail = "Insufficient balance to lock"
                
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=detail
            )
        
        # Send WebSocket notification for successful stake
        await notify_clients({
            "type": "staking.position_updated",
            "data": {
                "agent_did": current_agent.did,
                "action": "stake",
                "amount": str(stake_request.amount),
                "transaction_id": transaction.transaction_id,
                "timestamp": transaction.created_at.isoformat()
            }
        })
        
        # Also send balance update notification
        await notify_clients({
            "type": "balance.updated",
            "data": {
                "agent_did": current_agent.did,
                "staked_balance": str(current_agent.staked_balance + stake_request.amount)
            }
        })

        # Emit TokensStaked event to EventStore for supply invariant tracking
        try:
            await event_emitter.emit_tokens_staked(
                agent_did=current_agent.did,
                amount=str(int(stake_request.amount)),
                pool_id=transaction.transaction_id,
                lock_period_days=getattr(stake_request, 'lock_period', 0),
            )
            logger.info(f"Emitted TokensStaked event: {current_agent.did} amount={stake_request.amount}")
        except Exception as e:
            logger.warning(f"Failed to emit TokensStaked event: {e}")

        return transaction

    except HTTPException:
        # Re-raise HTTPExceptions without wrapping them
        raise
    except ValueError as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An internal error occurred"
        )
    except Exception as e:
        logger.error(f"Staking error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process the lock request. Please try again later."
        )


@router.post("/unstake", response_model=StakeTransactionRead)
async def unstake_tokens(
    unstake_request: UnstakeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_agent: Annotated[Agent, Security(get_current_agent)]
) -> StakeTransactionRead:
    """
    Unstake tokens by unlocking them in the TEG Layer.
    
    This endpoint allows an authenticated agent to unstake their tokens,
    making them available again for transfers and other uses.
    
    Process:
    1. Checks staked balance in Registry
    2. Unlocks the tokens in TEG
    3. Updates the Registry records
    
    Returns:
        StakeTransactionRead: Details of the unstake transaction
        
    Raises:
        HTTPException: If insufficient staked balance or TEG communication fails
    """
    try:
        transaction = await crud_staking.unstake_tokens(
            db=db,
            agent_did=current_agent.did,
            amount=unstake_request.amount
        )
        
        if transaction is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient locked balance. Currently locked: {current_agent.staked_balance} {frame_currency()}"
            )
        
        # Send WebSocket notification for successful unstake
        await notify_clients({
            "type": "staking.position_updated",
            "data": {
                "agent_did": current_agent.did,
                "action": "unstake",
                "amount": str(unstake_request.amount),
                "transaction_id": transaction.transaction_id,
                "timestamp": transaction.created_at.isoformat()
            }
        })
        
        # Also send balance update notification
        await notify_clients({
            "type": "balance.updated",
            "data": {
                "agent_did": current_agent.did,
                "staked_balance": str(current_agent.staked_balance - unstake_request.amount)
            }
        })

        # Emit TokensUnstaked event to EventStore for supply invariant tracking
        try:
            await event_emitter.emit_tokens_unstaked(
                agent_did=current_agent.did,
                amount=str(int(unstake_request.amount)),
                pool_id=transaction.transaction_id,
            )
            logger.info(f"Emitted TokensUnstaked event: {current_agent.did} amount={unstake_request.amount}")
        except Exception as e:
            logger.warning(f"Failed to emit TokensUnstaked event: {e}")

        return transaction

    except HTTPException:
        # Re-raise HTTPExceptions without wrapping them
        raise
    except ValueError as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An internal error occurred"
        )
    except Exception as e:
        logger.error(f"Unstaking error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process the unlock request. Please try again later."
        )


@router.get("/balance", response_model=StakeBalanceResponse)
async def get_stake_balance(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_agent: Annotated[Agent, Security(get_current_agent)]
) -> StakeBalanceResponse:
    """
    Get comprehensive balance information for the authenticated agent.
    
    Returns:
    - liquid_balance: Available tokens in TEG Layer (can be used for transfers)
    - staked_balance: Tokens locked for staking (from Registry)
    - total_balance: Sum of liquid and locked
    
    The liquid balance is fetched in real-time from the TEG Layer,
    while the staked balance is maintained in the Registry.
    
    Returns:
        StakeBalanceResponse: Balance information including liquid, staked, and total
    """
    # Get comprehensive balances
    balances = await crud_staking.get_agent_balances(db, current_agent.did)
    
    if not balances:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    
    # Return in the expected format
    return StakeBalanceResponse(
        agent_did=current_agent.did,
        liquid_balance=balances["available_balance"],  # From TEG
        staked_balance=balances["staked_balance"],     # From Registry
        total_balance=balances["total_balance"]
    )


@router.get("/status")
async def get_staking_status(
    current_agent: Annotated[Agent, Security(get_current_agent)]
) -> dict:
    """
    Get detailed staking system status for debugging.
    
    This endpoint provides comprehensive information about the staking
    system integration status and the agent's balances across both systems.
    
    Returns:
        Dictionary with system status and balance information
    """
    teg_client = get_teg_client()
    
    status = {
        "integration_active": True,
        "agent_did": current_agent.did,
        "registry_balances": {
            "liquid_balance": current_agent.liquid_balance,
            "staked_balance": current_agent.staked_balance
        },
        "teg_connection": "unknown",
        "teg_balance": None,
        "message": "Locks are now integrated with the TEG"
    }
    
    # Try to get TEG balance
    try:
        teg_balance = await teg_client.get_balance(current_agent.did)
        status["teg_connection"] = "active"
        status["teg_balance"] = float(teg_balance)
        status["balances_synced"] = current_agent.liquid_balance == 0  # Should be 0 in integrated system
    except Exception as e:
        status["teg_connection"] = "error"
        status["teg_error"] = str(e)
        
    return status


@router.get("/my-positions")
async def get_my_positions(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_agent: Annotated[Agent, Security(get_current_agent)]
) -> dict:
    """
    Get staking positions for the authenticated agent.
    
    Returns:
        Dictionary with positions array and total staked amount
    """
    # For now, return a simplified view based on staked balance
    positions = []
    
    if current_agent.staked_balance > 0:
        # Create a single position representing all staked tokens
        positions.append({
            "id": f"stake-{current_agent.did}",
            "agent_did": current_agent.did,
            "amount": str(current_agent.staked_balance),
            "rewards_earned": "0",  # TODO: Implement rewards tracking
            "staked_at": current_agent.created_at.isoformat(),
            "lock_period": 0,  # Flexible staking for now
            "apy": 10.0,  # Default APY
            "status": "active"
        })
    
    return {
        "positions": positions,
        "total_staked": str(current_agent.staked_balance),
        "total_positions": len(positions)
    }


@router.get("/apy-tiers")
async def get_apy_tiers() -> list:
    """
    Get APY tiers for different lock periods.
    
    Returns:
        List of APY tier configurations
    """
    # Return default APY tiers
    # TODO: Make this configurable
    return [
        {
            "lockPeriod": 0,
            "apy": 5.0,
            "minAmount": "100",
            "description": "Flexible - unlock anytime"
        },
        {
            "lockPeriod": 30,
            "apy": 8.0,
            "minAmount": "100",
            "description": "30 days lock period"
        },
        {
            "lockPeriod": 90,
            "apy": 12.0,
            "minAmount": "500",
            "description": "90 days lock period"
        },
        {
            "lockPeriod": 180,
            "apy": 18.0,
            "minAmount": "1000",
            "description": "180 days lock period"
        },
        {
            "lockPeriod": 365,
            "apy": 25.0,
            "minAmount": "5000",
            "description": "365 days lock period"
        }
    ]


@router.get("/history")
async def get_staking_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_agent: Annotated[Agent, Security(get_current_agent)],
    limit: int = 100,
    offset: int = 0
) -> dict:
    """
    Get staking transaction history for the authenticated agent.
    
    Query Parameters:
        limit: Maximum number of transactions to return (default: 100)
        offset: Number of transactions to skip (default: 0)
    
    Returns:
        Dictionary with transaction history and pagination info
    """
    # Query stake transactions from database
    from sqlalchemy import and_, or_
    query = select(StakeTransaction).where(
        StakeTransaction.agent_id == current_agent.id
    ).order_by(
        StakeTransaction.created_at.desc()
    ).offset(offset).limit(limit)
    
    result = await db.execute(query)
    transactions = result.scalars().all()
    
    # Count total transactions
    count_query = select(func.count()).where(
        StakeTransaction.agent_id == current_agent.id
    )
    count_result = await db.execute(count_query)
    total_count = count_result.scalar()
    
    # Format transactions for response
    history = []
    for tx in transactions:
        history.append({
            "id": str(tx.id),
            "type": tx.transaction_type,  # 'stake' or 'unstake'
            "amount": str(tx.amount),
            "timestamp": tx.created_at.isoformat(),
            "txHash": tx.transaction_id or f"{tx.transaction_type}-{tx.id}",
            "status": "completed"  # All recorded transactions are completed
        })
    
    return {
        "history": history,
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + limit) < total_count
    }
