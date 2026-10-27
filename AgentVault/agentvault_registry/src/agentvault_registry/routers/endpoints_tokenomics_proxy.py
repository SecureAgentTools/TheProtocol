"""
Tokenomics Proxy Endpoints for TEG Layer Integration

This module provides proxy endpoints that forward tokenomics-related requests
from the Registry Layer to the TEG Layer, following the established pattern
of other TEG integrations.

Created as part of fixing the tokenomics test failures (2025-07-29).
"""

from typing import Optional, Dict, Any, List
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, Security
from pydantic import BaseModel, Field

from ..models import Agent, Developer
from ..security import get_current_agent
from ..teg_client import get_teg_client, TEGClient, TEGClientError
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tokenomics",
    # §pass56 PR-5+PR-6: tags= dropped; main.py:include_router supplies ["Tokenomics", "TEG Integration"]
)


# Response Models
class PendingRewardsResponse(BaseModel):
    """Response model for pending rewards"""
    agent_did: str = Field(..., description="Agent DID")
    pending_rewards: str = Field(..., description="Pending rewards amount as string")
    last_claim_timestamp: Optional[str] = Field(None, description="Last claim timestamp")
    reward_sources: List[Dict[str, Any]] = Field(default_factory=list, description="Sources of rewards")


class TransactionInfo(BaseModel):
    """Transaction information model"""
    transaction_id: str = Field(..., description="Unique transaction identifier")
    type: str = Field(..., description="Transaction type")
    amount: str = Field(..., description="Transaction amount as string")
    sender: Optional[str] = Field(None, description="Sender agent DID")
    receiver: str = Field(..., description="Receiver agent DID")
    timestamp: str = Field(..., description="Transaction timestamp")
    status: str = Field(..., description="Transaction status")
    fee: str = Field(..., description="Transaction fee as string")
    message: Optional[str] = Field(None, description="Optional transaction message")


class TransactionHistoryResponse(BaseModel):
    """Response model for transaction history"""
    agent_did: str = Field(..., description="Agent DID")
    transactions: List[TransactionInfo] = Field(..., description="List of transactions")
    total: int = Field(..., description="Total number of transactions")


class TreasuryInfoResponse(BaseModel):
    """Response model for treasury information"""
    total_supply: str = Field(..., description="Total token supply")
    circulating_supply: str = Field(..., description="Circulating supply")
    treasury_balance: str = Field(..., description="Treasury balance")
    locked_supply: str = Field(..., description="Locked supply")
    burned_supply: str = Field(..., description="Burned tokens")
    reward_pool: str = Field(..., description="Payout pool balance")
    last_updated: Optional[str] = Field(None, description="Last update timestamp")


# Endpoints

@router.get("/rewards/{agent_did}", response_model=PendingRewardsResponse, summary="Pending payouts on locked units")
async def get_pending_rewards(
    agent_did: str,
    current_agent: Agent = Security(get_current_agent),
    teg_client: TEGClient = Depends(get_teg_client)
) -> PendingRewardsResponse:
    """
    Get pending payouts on locked units for an agent.
    
    This endpoint proxies the request to the TEG Layer to retrieve
    pending payout information. The agent_did parameter should match
    the authenticated agent's DID.
    
    Args:
        agent_did: DID of the agent to query (should match authenticated agent)
        current_agent: Authenticated agent
        
    Returns:
        PendingRewardsResponse with payout information
        
    Raises:
        HTTPException: If the TEG Layer request fails or agent mismatch
    """
    # Verify the agent_did matches the authenticated agent
    if agent_did != current_agent.did:
        raise HTTPException(
            status_code=403,
            detail="Can only query your own payouts"
        )
    
    try:
        logger.info(f"Fetching pending rewards for agent {agent_did}")
        
        # Call TEG Layer via TEGClient
        result = await teg_client.get_pending_rewards(agent_did)
        
        # Format response
        return PendingRewardsResponse(
            agent_did=agent_did,
            pending_rewards=str(result.get("pending_rewards", 0)),
            last_claim_timestamp=result.get("last_claim_timestamp"),
            reward_sources=result.get("reward_sources", [])
        )
        
    except TEGClientError as e:
        logger.error(f"TEG Layer error getting pending rewards: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get pending payouts from the TEG: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error getting pending rewards: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal error getting pending payouts: {str(e)}"
        )


@router.get("/transactions/{agent_did}", response_model=TransactionHistoryResponse)
async def get_transaction_history(
    agent_did: str,
    limit: int = Query(10, ge=1, le=100, description="Maximum number of transactions to return"),
    current_agent: Agent = Security(get_current_agent),
    teg_client: TEGClient = Depends(get_teg_client)
) -> TransactionHistoryResponse:
    """
    Get transaction history for an agent.
    
    This endpoint proxies the request to the TEG Layer to retrieve
    recent transaction history. The agent_did parameter should match
    the authenticated agent's DID.
    
    Args:
        agent_did: DID of the agent to query (should match authenticated agent)
        limit: Maximum number of transactions to return (1-100)
        current_agent: Authenticated agent
        
    Returns:
        TransactionHistoryResponse with transaction list
        
    Raises:
        HTTPException: If the TEG Layer request fails or agent mismatch
    """
    # Verify the agent_did matches the authenticated agent
    if agent_did != current_agent.did:
        raise HTTPException(
            status_code=403,
            detail="Can only query your own transactions"
        )
    
    try:
        logger.info(f"Fetching transaction history for agent {agent_did} (limit: {limit})")
        
        # Call TEG Layer via TEGClient
        transactions = await teg_client.get_recent_transactions(agent_did, limit=limit)
        
        # Convert to response model format
        transaction_models = []
        for tx in transactions:
            transaction_models.append(TransactionInfo(
                transaction_id=tx.get("transaction_id", ""),
                type=tx.get("type", "transfer"),
                amount=tx.get("amount", "0"),
                sender=tx.get("sender"),
                receiver=tx.get("receiver", ""),
                timestamp=tx.get("timestamp", ""),
                status=tx.get("status", "completed"),
                fee=tx.get("fee", "0"),
                message=tx.get("message")
            ))
        
        # Format response
        return TransactionHistoryResponse(
            agent_did=agent_did,
            transactions=transaction_models,
            total=len(transaction_models)
        )
        
    except TEGClientError as e:
        logger.error(f"TEG Layer error getting transaction history: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get transaction history from TEG Layer: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error getting transaction history: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal error getting transaction history: {str(e)}"
        )


@router.get("/treasury", response_model=TreasuryInfoResponse)
async def get_treasury_info(
    current_agent: Agent = Security(get_current_agent),
    teg_client: TEGClient = Depends(get_teg_client)
) -> TreasuryInfoResponse:
    """
    Get treasury information.
    
    This endpoint proxies the request to the TEG Layer to retrieve
    current treasury metrics and token supply information.
    
    Args:
        current_agent: Authenticated agent
        
    Returns:
        TreasuryInfoResponse with treasury metrics
        
    Raises:
        HTTPException: If the TEG Layer request fails
    """
    try:
        logger.info("Fetching treasury information")
        
        # Call TEG Layer via TEGClient
        result = await teg_client.get_treasury_info()
        
        # Format response
        return TreasuryInfoResponse(
            total_supply=result.get("total_supply", "0"),
            circulating_supply=result.get("circulating_supply", "0"),
            treasury_balance=result.get("treasury_balance", "0"),
            locked_supply=result.get("locked_supply", "0"),
            burned_supply=result.get("burned_supply", "0"),
            reward_pool=result.get("reward_pool", "0"),
            last_updated=result.get("last_updated")
        )
        
    except TEGClientError as e:
        logger.error(f"TEG Layer error getting treasury info: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get treasury info from TEG Layer: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error getting treasury info: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal error getting treasury info: {str(e)}"
        )
