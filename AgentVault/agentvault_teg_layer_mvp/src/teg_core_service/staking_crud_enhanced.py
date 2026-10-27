"""
Enhanced StakingCRUD with Event Store integration
This module patches the StakingCRUD to emit events after successful staking operations
"""

from decimal import Decimal
from typing import Optional, Tuple
from sqlalchemy.orm import Session
import asyncio
import logging

from .database.models import Stake
from .database.crud import StakingCRUD as OriginalStakingCRUD, AgentCRUD
from .event_emitter import EventEmitter
from .core.config import get_settings

logger = logging.getLogger(__name__)

# Initialize Event Emitter
settings = get_settings()
event_emitter = EventEmitter(
    event_store_url=settings.event_store_url if hasattr(settings, 'event_store_url') else "http://localhost:8200",
    internal_api_key=settings.event_store_api_key if hasattr(settings, 'event_store_api_key') else "",
    source_service="teg"
)


class EnhancedStakingCRUD(OriginalStakingCRUD):
    """Enhanced StakingCRUD that emits events to the Event Store"""
    
    @staticmethod
    def create_stake(
        db: Session,
        agent_id: str,
        amount: Decimal
    ) -> Stake:
        """Create a new stake by locking agent's tokens and emit event"""
        # Execute the original staking logic
        stake = OriginalStakingCRUD.create_stake(
            db=db,
            agent_id=agent_id,
            amount=amount
        )
        
        # Emit event if staking was successful
        try:
            # Run event emission in a fire-and-forget manner
            asyncio.create_task(_emit_staking_event(
                agent_did=agent_id,
                amount=str(amount),
                stake_id=stake.stake_id
            ))
            logger.info(f"Scheduled TokensStaked event emission for stake {stake.stake_id}")
        except Exception as e:
            # Don't fail the staking if event emission fails
            logger.error(f"Failed to schedule staking event emission: {e}")
        
        return stake
    
    @staticmethod
    def unstake(
        db: Session,
        stake_id: str,
        agent_id: str
    ) -> Tuple[Stake, Decimal]:
        """Unstake tokens and return them to the agent with event emission"""
        # Execute the original unstaking logic
        stake, total_return = OriginalStakingCRUD.unstake(
            db=db,
            stake_id=stake_id,
            agent_id=agent_id
        )
        
        # Calculate rewards (total_return - original stake amount)
        rewards_earned = total_return - stake.amount
        
        # Emit event if unstaking was successful
        try:
            # Run event emission in a fire-and-forget manner
            asyncio.create_task(_emit_unstaking_event(
                agent_did=agent_id,
                amount=str(stake.amount),
                stake_id=stake_id,
                rewards_earned=str(rewards_earned) if rewards_earned > 0 else None
            ))
            logger.info(f"Scheduled TokensUnstaked event emission for stake {stake_id}")
        except Exception as e:
            # Don't fail the unstaking if event emission fails
            logger.error(f"Failed to schedule unstaking event emission: {e}")
        
        return stake, total_return


async def _emit_staking_event(
    agent_did: str,
    amount: str,
    stake_id: str
):
    """Helper function to emit staking event asynchronously"""
    try:
        success = await event_emitter.emit_tokens_staked(
            agent_did=agent_did,
            amount=amount,
            pool_id=f"stake_{stake_id}",  # Use stake ID as pool ID for tracking
            lock_period_days=30  # Default lock period
        )
        if success:
            logger.info(f"Successfully emitted TokensStaked event for stake {stake_id}")
        else:
            logger.error(f"Failed to emit TokensStaked event for stake {stake_id}")
    except Exception as e:
        logger.error(f"Error emitting staking event: {e}")


async def _emit_unstaking_event(
    agent_did: str,
    amount: str,
    stake_id: str,
    rewards_earned: Optional[str] = None
):
    """Helper function to emit unstaking event asynchronously"""
    try:
        success = await event_emitter.emit_tokens_unstaked(
            agent_did=agent_did,
            amount=amount,
            pool_id=f"stake_{stake_id}",  # Use stake ID as pool ID for tracking
            rewards_earned=rewards_earned
        )
        if success:
            logger.info(f"Successfully emitted TokensUnstaked event for stake {stake_id}")
        else:
            logger.error(f"Failed to emit TokensUnstaked event for stake {stake_id}")
    except Exception as e:
        logger.error(f"Error emitting unstaking event: {e}")


# Monkey patch the original StakingCRUD with our enhanced version
def patch_staking_crud():
    """Replace the original StakingCRUD with the enhanced version"""
    import sys
    from . import database
    
    # Replace in the crud module
    database.crud.StakingCRUD = EnhancedStakingCRUD
    
    # Also update any already imported references
    for name, module in sys.modules.items():
        if hasattr(module, 'StakingCRUD'):
            if getattr(module, 'StakingCRUD') == OriginalStakingCRUD:
                setattr(module, 'StakingCRUD', EnhancedStakingCRUD)
    
    logger.info("StakingCRUD patched with Event Store integration")
