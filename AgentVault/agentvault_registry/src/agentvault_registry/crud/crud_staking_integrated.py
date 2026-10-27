"""
CRUD operations for staking functionality in the economic engine.

UPDATED: Now integrates with TEG Layer for real token operations.
"""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from decimal import Decimal

from ..models import Agent, StakeTransaction
from ..teg_client import get_teg_client, TEGBalanceError, TEGClientError

import logging
logger = logging.getLogger(__name__)


async def stake_tokens(
    db: AsyncSession,
    agent_did: str,
    amount: int
) -> Optional[StakeTransaction]:
    """
    Stake tokens by locking them in TEG and recording in Registry.
    
    This function now:
    1. Checks the agent's available balance in TEG
    2. Locks the tokens in TEG
    3. Updates the Registry's staking records
    4. Creates a transaction record
    
    Args:
        db: Database session
        agent_did: DID of the agent staking tokens
        amount: Amount of tokens to stake
        
    Returns:
        StakeTransaction record if successful, None if insufficient balance
        
    Raises:
        ValueError: If amount is non-positive or other validation fails
        TEGClientError: If TEG Layer communication fails
    """
    if amount <= 0:
        raise ValueError("Lock amount must be positive")
    
    # Get the agent from Registry
    stmt = select(Agent).where(Agent.did == agent_did)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise ValueError(f"Agent with DID {agent_did} not found")
    
    # Get TEG client
    teg_client = get_teg_client()
    
    try:
        # Check available balance in TEG
        teg_balance = await teg_client.get_balance(agent_did)
        logger.info(f"Agent {agent_did} TEG balance: {teg_balance}")
        
        if teg_balance < Decimal(str(amount)):
            logger.warning(f"Insufficient TEG balance for staking: {teg_balance} < {amount}")
            return None
        
        # Lock tokens in TEG
        lock_response = await teg_client.lock_tokens(agent_did, Decimal(str(amount)))
        logger.info(f"Tokens locked in TEG: {lock_response}")
        
        # Update Registry balance cache (both staked and liquid for DB consistency)
        agent.staked_balance += amount
        agent.liquid_balance = max(Decimal("0"), agent.liquid_balance - Decimal(str(amount)))
        
        # Create stake transaction record
        stake_transaction = StakeTransaction(
            agent_did=agent_did,
            transaction_type="STAKE",
            amount=amount
        )
        
        db.add(stake_transaction)
        
        try:
            await db.commit()
            await db.refresh(stake_transaction)
            logger.info(f"Staking recorded in Registry: {amount} tokens for {agent_did}")
            return stake_transaction
        except IntegrityError:
            await db.rollback()
            # If Registry update fails, we need to unlock tokens in TEG
            try:
                await teg_client.unlock_tokens(agent_did, Decimal(str(amount)))
                logger.error("Registry update failed, tokens unlocked in TEG")
            except Exception as unlock_error:
                logger.critical(f"CRITICAL: Failed to unlock tokens after Registry error: {unlock_error}")
            raise
            
    except TEGBalanceError as e:
        logger.error(f"TEG balance error during staking: {str(e)}")
        return None
    except TEGClientError as e:
        logger.error(f"TEG client error during staking: {str(e)}")
        raise ValueError(f"Failed to communicate with TEG Layer: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error during staking: {str(e)}")
        raise


async def unstake_tokens(
    db: AsyncSession,
    agent_did: str,
    amount: int
) -> Optional[StakeTransaction]:
    """
    Unstake tokens by unlocking them in TEG and updating Registry records.
    
    This function now:
    1. Checks the agent's staked balance in Registry
    2. Unlocks the tokens in TEG
    3. Updates the Registry's staking records
    4. Creates a transaction record
    
    Args:
        db: Database session
        agent_did: DID of the agent unstaking tokens
        amount: Amount of tokens to unstake
        
    Returns:
        StakeTransaction record if successful, None if insufficient staked balance
        
    Raises:
        ValueError: If amount is non-positive or other validation fails
        TEGClientError: If TEG Layer communication fails
    """
    if amount <= 0:
        raise ValueError("Unlock amount must be positive")
    
    # Get the agent from Registry
    stmt = select(Agent).where(Agent.did == agent_did)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise ValueError(f"Agent with DID {agent_did} not found")
    
    # Check if agent has sufficient staked balance
    if agent.staked_balance < amount:
        logger.warning(f"Insufficient staked balance: {agent.staked_balance} < {amount}")
        return None
    
    # Get TEG client
    teg_client = get_teg_client()
    
    try:
        # Unlock tokens in TEG
        unlock_response = await teg_client.unlock_tokens(agent_did, Decimal(str(amount)))
        logger.info(f"Tokens unlocked in TEG: {unlock_response}")
        
        # Update Registry balance cache (both staked and liquid for DB consistency)
        agent.staked_balance -= amount
        agent.liquid_balance += Decimal(str(amount))
        
        # Create unstake transaction record
        unstake_transaction = StakeTransaction(
            agent_did=agent_did,
            transaction_type="UNSTAKE",
            amount=amount
        )
        
        db.add(unstake_transaction)
        
        try:
            await db.commit()
            await db.refresh(unstake_transaction)
            logger.info(f"Unstaking recorded in Registry: {amount} tokens for {agent_did}")
            return unstake_transaction
        except IntegrityError:
            await db.rollback()
            # If Registry update fails, we need to re-lock tokens in TEG
            try:
                await teg_client.lock_tokens(agent_did, Decimal(str(amount)))
                logger.error("Registry update failed, tokens re-locked in TEG")
            except Exception as lock_error:
                logger.critical(f"CRITICAL: Failed to re-lock tokens after Registry error: {lock_error}")
            raise
            
    except TEGBalanceError as e:
        logger.error(f"TEG balance error during unstaking: {str(e)}")
        return None
    except TEGClientError as e:
        logger.error(f"TEG client error during unstaking: {str(e)}")
        raise ValueError(f"Failed to communicate with TEG Layer: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error during unstaking: {str(e)}")
        raise


async def get_agent_stake(
    db: AsyncSession,
    agent_did: str
) -> Optional[int]:
    """
    Get the current staked balance for an agent.
    
    Args:
        db: Database session
        agent_did: DID of the agent
        
    Returns:
        Current staked balance, or None if agent not found
    """
    stmt = select(Agent.staked_balance).where(Agent.did == agent_did)
    result = await db.execute(stmt)
    staked_balance = result.scalar_one_or_none()
    
    return staked_balance


async def get_agent_balances(
    db: AsyncSession,
    agent_did: str
) -> Optional[dict]:
    """
    Get comprehensive balance information for an agent.
    
    This includes:
    - Available balance (from TEG)
    - Staked balance (from Registry)
    - Total balance (available + staked)
    
    Args:
        db: Database session
        agent_did: DID of the agent
        
    Returns:
        Dictionary with balance information, or None if agent not found
    """
    # Get staked balance from Registry
    stmt = select(Agent).where(Agent.did == agent_did)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    
    if not agent:
        return None
    
    # Get available balance from TEG
    teg_client = get_teg_client()
    try:
        available_balance = await teg_client.get_balance(agent_did)
    except Exception as e:
        logger.error(f"Failed to get TEG balance: {str(e)}")
        available_balance = Decimal("0")
    
    return {
        "agent_did": agent_did,
        "available_balance": available_balance,  # TEG balance (Decimal)
        "staked_balance": agent.staked_balance,      # Registry balance
        "total_balance": available_balance + agent.staked_balance
    }
