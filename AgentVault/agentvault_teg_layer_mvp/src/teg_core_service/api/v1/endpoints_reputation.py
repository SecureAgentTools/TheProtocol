"""Reputation-related API endpoints"""
from decimal import Decimal
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from starlette.status import HTTP_404_NOT_FOUND

from ...database.db_session import get_db
from ...database.crud import ReputationService
from ...core.reputation_logic import get_reputation_tier
from .schemas import (
    AgentReputationResponse,
    ErrorResponse
)

router = APIRouter()


@router.get(
    "/agents/{agent_id}/reputation",
    response_model=AgentReputationResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Agent not found"},
    }
)
async def get_agent_reputation(
    agent_id: str,
    include_attestations: bool = True,
    db: Session = Depends(get_db)
):
    """
    Get an agent's reputation score with attestation-based factors.
    
    Returns the current reputation score, tier, and contributing factors including:
    - Base reputation score
    - Attestation submissions count
    - Successful ZKP verifications
    - Failed ZKP attempts
    - Total rewards earned from attestations
    """
    # Get or create agent profile automatically
    score, last_updated = ReputationService.get_reputation(db, agent_id)
    
    response = AgentReputationResponse(
        agent_id=agent_id,
        reputation_score=score,
        reputation_tier=get_reputation_tier(score),
        last_updated=last_updated
    )
    
    # Include attestation-based reputation factors if requested
    if include_attestations:
        from ...database.crud import AttestationCRUD
        from ...database.models import TEGAttestationLog
        
        # Count total attestations
        total_attestations = db.query(TEGAttestationLog).filter(
            TEGAttestationLog.agent_did == agent_id
        ).count()
        
        # Count successful ZKP attestations
        successful_zkp = AttestationCRUD.count_successful_zkp_attestations(db, agent_id)
        
        # Count failed ZKP attestations
        failed_zkp = AttestationCRUD.count_failed_zkp_attestations(db, agent_id)
        
        # Calculate total rewards earned from attestations
        attestations_with_rewards = db.query(TEGAttestationLog).filter(
            TEGAttestationLog.agent_did == agent_id,
            TEGAttestationLog.reward_issued_tx_id.isnot(None)
        ).all()
        
        total_attestation_rewards = Decimal("0")
        for att in attestations_with_rewards:
            if att.policy and att.policy.reward_amount:
                total_attestation_rewards += att.policy.reward_amount
        
        # Add attestation factors to response
        response.attestation_factors = {
            "total_attestations": total_attestations,
            "successful_zkp_attestations": successful_zkp,
            "failed_zkp_attestations": failed_zkp,
            "zkp_success_rate": (
                (successful_zkp / (successful_zkp + failed_zkp)) * 100 
                if (successful_zkp + failed_zkp) > 0 else 0
            ),
            "total_rewards_earned": str(total_attestation_rewards),
            "reputation_boost_from_attestations": calculate_attestation_reputation_boost(
                total_attestations, successful_zkp, failed_zkp
            )
        }
    
    return response


def calculate_attestation_reputation_boost(
    total_attestations: int,
    successful_zkp: int,
    failed_zkp: int
) -> int:
    """
    Calculate reputation boost from attestation activity.
    
    Rewards:
    - +1 point per attestation (max 50)
    - +5 points per successful ZKP attestation (max 100)
    - -10 points per failed ZKP attestation
    """
    boost = 0
    
    # Basic attestation points (capped at 50)
    boost += min(total_attestations, 50)
    
    # Successful ZKP bonus (capped at 100)
    boost += min(successful_zkp * 5, 100)
    
    # Failed ZKP penalty
    boost -= failed_zkp * 10
    
    # Don't let attestations create negative reputation
    return max(boost, 0)


@router.get(
    "/rankings",
    summary="Get reputation rankings",
    description="Get reputation rankings across all agents"
)
async def get_reputation_rankings(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    min_score: Optional[int] = Query(None, description="Minimum reputation score"),
    db: Session = Depends(get_db)
):
    """Get reputation rankings across all agents."""
    from ...database.models import AgentTEGProfile
    
    query = db.query(AgentTEGProfile).filter(
        AgentTEGProfile.reputation_score != None
    )
    
    if min_score is not None:
        query = query.filter(AgentTEGProfile.reputation_score >= min_score)
    
    # Order by reputation score descending
    query = query.order_by(desc(AgentTEGProfile.reputation_score))
    
    total = query.count()
    agents = query.offset(offset).limit(limit).all()
    
    rankings = []
    for i, agent in enumerate(agents, start=offset + 1):
        # Determine tier based on score
        score = agent.reputation_score
        if score >= 1000:
            tier = "legendary"
        elif score >= 500:
            tier = "expert"
        elif score >= 100:
            tier = "trusted"
        elif score >= 0:
            tier = "standard"
        else:
            tier = "restricted"
        
        rankings.append({
            "rank": i,
            "agent_id": agent.agent_id,
            "reputation_score": score,
            "reputation_tier": tier,
            "total_transactions": getattr(agent, 'transaction_count', 0)
        })
    
    return {
        "rankings": rankings,
        "total_agents": total,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
