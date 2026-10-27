"""Reputation calculation logic for TEG MVP

This module implements the core reputation scoring algorithm for agents in the TEG system.
Reputation is calculated based on multiple weighted factors including stake, attestations,
AVTP transaction success rates, auditor flags, and dispute outcomes.

The reputation score directly impacts an agent's trustworthiness and may influence
future interactions within the AgentVault ecosystem.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import and_

from ..core.config import get_settings
from ..database.crud import (
    ReputationService, AgentCRUD, AVTPLogCRUD, 
    AttestationCRUD, AuditorFlagCRUD
)
from ..database.models import (
    TEGAttestationLog, AuditorFlagLog, TEGDisputeLog
)

settings = get_settings()


def get_reputation_tier(reputation_score: int) -> str:
    """
    Determine reputation tier based on score.
    
    Args:
        reputation_score: The agent's reputation score
        
    Returns:
        str: Reputation tier (BRONZE, SILVER, or GOLD)
    """
    if reputation_score >= settings.rep_tier_gold_min_score:
        return "GOLD"
    elif reputation_score >= settings.rep_tier_silver_min_score:
        return "SILVER"
    else:
        return "BRONZE"


def calculate_and_update_reputation(agent_id: str, db_session: Session) -> int:
    """
    Calculate and update an agent's reputation score.
    
    Implements the enhanced MVP reputation formula:
    Score = (w1 * normalized_stake) + (w2 * num_attestations) + 
            (w3 * num_successful_txns) - (w4 * num_failed_txns) - 
            (w5 * num_critical_flags) - (w6 * num_negative_ddr_rulings) +
            (w7 * num_successful_zkp_attestations) - (w8 * num_failed_zkp_attestations)
            
    The formula rewards positive contributions (stake, attestations, successful transactions,
    valid ZKP proofs) and penalizes negative behaviors (failed transactions, audit flags, 
    lost disputes, invalid ZKP proofs).
    
    Args:
        agent_id: The DID of the agent whose reputation to calculate
        db_session: SQLAlchemy database session
        
    Returns:
        int: The newly calculated reputation score (minimum 0)
        
    Note:
        This function performs database updates atomically. In production,
        consider implementing optimistic locking for concurrent updates.
    """
    # Get agent profile
    agent = AgentCRUD.get_or_create(db_session, agent_id)
    
    # 1. Get stake level (from token balance for MVP)
    # In production, this might query a separate staking contract
    agent_stake = float(agent.token_balance)
    # Normalize stake to 0-1 range, capping at configured maximum
    normalized_stake = min(agent_stake, settings.max_stake_effective_for_rep) / settings.max_stake_effective_for_rep
    
    # 2. Count valid attestations
    # Only count attestations that have been logged or validated
    # Future versions might weight different attestation types differently
    num_attestations = db_session.query(TEGAttestationLog).filter(
        and_(
            TEGAttestationLog.agent_did == agent_id,
            TEGAttestationLog.status.in_(["logged", "basic_validated"])
        )
    ).count()
    
    # 3. AVTP transaction counts (now using real data)
    # Counts all transactions where agent was involved, regardless of role
    num_successful_txns = AVTPLogCRUD.count_successful_transactions(db_session, agent_id)
    num_failed_txns = AVTPLogCRUD.count_failed_transactions(db_session, agent_id)
    
    # 4. Count confirmed critical flags (including automated high-severity flags)
    # Now using the enhanced method that includes auto-flagged high-severity issues
    num_critical_flags = AuditorFlagCRUD.count_critical_flags(db_session, agent_id)
    
    # 5. Count negative DDR rulings (where agent was defendant and lost)
    # Being a successful claimant doesn't affect reputation in MVP
    # Future versions might add positive reputation for successful claims
    num_negative_ddr_rulings = db_session.query(TEGDisputeLog).filter(
        and_(
            TEGDisputeLog.defendant_agent_did == agent_id,
            TEGDisputeLog.status == "resolved_penalty_applied"
        )
    ).count()
    
    # 6. Count ZKP attestations by type
    # Different ZKP types get different weights
    # Fair Markup ZKP
    num_successful_fair_markup_zkp = db_session.query(TEGAttestationLog).filter(
        and_(
            TEGAttestationLog.agent_did == agent_id,
            TEGAttestationLog.attestation_type == "ProofOfFairMarkup_ZKP_v1",
            TEGAttestationLog.status == "zkp_verified_true"
        )
    ).count()
    
    num_failed_fair_markup_zkp = db_session.query(TEGAttestationLog).filter(
        and_(
            TEGAttestationLog.agent_did == agent_id,
            TEGAttestationLog.attestation_type == "ProofOfFairMarkup_ZKP_v1",
            TEGAttestationLog.status == "zkp_verified_false"
        )
    ).count()
    
    # Resource Usage ZKP
    num_successful_resource_zkp = db_session.query(TEGAttestationLog).filter(
        and_(
            TEGAttestationLog.agent_did == agent_id,
            TEGAttestationLog.attestation_type == "ProofOfAccurateResourceUsage_ZKP_v1",
            TEGAttestationLog.status == "zkp_verified_true"
        )
    ).count()
    
    num_failed_resource_zkp = db_session.query(TEGAttestationLog).filter(
        and_(
            TEGAttestationLog.agent_did == agent_id,
            TEGAttestationLog.attestation_type == "ProofOfAccurateResourceUsage_ZKP_v1",
            TEGAttestationLog.status == "zkp_verified_false"
        )
    ).count()
    
    # 7. Count collusion flags
    # Check if agent has any active collusion detection flags
    num_collusion_flags = db_session.query(AuditorFlagLog).filter(
        and_(
            AuditorFlagLog.flagged_agent_did == agent_id,
            AuditorFlagLog.rule_violated_code == "BASIC_COLLUSION_PRICE_SYNC_V1",
            AuditorFlagLog.status.in_([
                "auto_flagged_manual_review",
                "manual_review_confirmed",
                "resolved_action_taken_critical_flag"
            ])
        )
    ).count()
    
    # 8. Calculate score using weighted formula
    # Each weight is configurable via environment variables
    score = (
        (settings.w1_stake_weight * normalized_stake) +            # Stake contribution
        (settings.w2_attestation_weight * num_attestations) +      # Attestation contribution
        (settings.w3_successful_txn_weight * num_successful_txns) -  # Success bonus
        (settings.w4_failed_txn_weight * num_failed_txns) -        # Failure penalty
        (settings.w5_critical_flag_penalty * num_critical_flags) -  # Audit penalty
        (settings.w6_negative_ddr_penalty * num_negative_ddr_rulings) -  # Dispute penalty
        (settings.w7_successful_zkp_attestation_bonus * num_successful_fair_markup_zkp) -  # Fair markup ZKP bonus
        (settings.w8_failed_zkp_attestation_penalty * num_failed_fair_markup_zkp) +  # Fair markup ZKP penalty
        (settings.w9_successful_resource_zkp * num_successful_resource_zkp) -  # Resource ZKP bonus
        (settings.w10_failed_resource_zkp * num_failed_resource_zkp) -  # Resource ZKP penalty
        (settings.w11_collusion_flag_penalty * num_collusion_flags)  # Collusion penalty
    )
    
    # Ensure score doesn't go below minimum
    final_score = max(int(score), settings.min_reputation_score)
    
    # Update reputation in database
    ReputationService.update_reputation(db_session, agent_id, final_score)
    
    # Run automated auditor checks for reputation changes
    try:
        from ..core.automated_auditor import AutomatedAuditorRules
        AutomatedAuditorRules.run_reputation_checks(db_session, agent_id)
    except Exception:
        # Don't fail reputation update if auditor checks fail
        pass
    
    return final_score


def get_reputation_factors(agent_id: str, db_session: Session) -> dict:
    """
    Get detailed breakdown of reputation factors for an agent.
    
    This function provides transparency into how an agent's reputation
    score is calculated by returning all contributing factors.
    
    Args:
        agent_id: The DID of the agent
        db_session: SQLAlchemy database session
    
    Returns:
        dict: Detailed breakdown containing:
            - attestation_count: Number of valid attestations submitted
            - violation_count: Number of confirmed audit violations
            - dispute_wins: Disputes where agent was successful claimant
            - dispute_losses: Disputes where agent lost as defendant
            - transaction_success_rate: Ratio of successful to total AVTP transactions
            - last_activity: Timestamp of most recent activity
            - current_stake: Current token balance (used as stake)
            - reputation_score: Current reputation score
            
    Note:
        This is useful for debugging reputation issues and providing
        transparency to agents about their reputation calculation.
    """
    # Get agent profile
    agent = AgentCRUD.get_or_create(db_session, agent_id)
    
    # Count attestations
    attestation_count = db_session.query(TEGAttestationLog).filter(
        and_(
            TEGAttestationLog.agent_did == agent_id,
            TEGAttestationLog.status.in_(["logged", "basic_validated"])
        )
    ).count()
    
    # Count violations (confirmed flags)
    violation_count = db_session.query(AuditorFlagLog).filter(
        and_(
            AuditorFlagLog.flagged_agent_did == agent_id,
            AuditorFlagLog.status == "resolved_action_taken"
        )
    ).count()
    
    # Count dispute wins (as claimant with penalty applied to defendant)
    dispute_wins = db_session.query(TEGDisputeLog).filter(
        and_(
            TEGDisputeLog.claimant_agent_did == agent_id,
            TEGDisputeLog.status == "resolved_penalty_applied"
        )
    ).count()
    
    # Count dispute losses (as defendant with penalty applied)
    dispute_losses = db_session.query(TEGDisputeLog).filter(
        and_(
            TEGDisputeLog.defendant_agent_did == agent_id,
            TEGDisputeLog.status == "resolved_penalty_applied"
        )
    ).count()
    
    # Get last activity (most recent of attestation, flag, or dispute)
    last_attestation = db_session.query(TEGAttestationLog.submitted_at).filter(
        TEGAttestationLog.agent_did == agent_id
    ).order_by(TEGAttestationLog.submitted_at.desc()).first()
    
    last_flag = db_session.query(AuditorFlagLog.timestamp).filter(
        AuditorFlagLog.flagged_agent_did == agent_id
    ).order_by(AuditorFlagLog.timestamp.desc()).first()
    
    last_dispute = db_session.query(TEGDisputeLog.created_at).filter(
        (TEGDisputeLog.claimant_agent_did == agent_id) |
        (TEGDisputeLog.defendant_agent_did == agent_id)
    ).order_by(TEGDisputeLog.created_at.desc()).first()
    
    # Find most recent activity
    activities = []
    if last_attestation:
        activities.append(last_attestation[0])
    if last_flag:
        activities.append(last_flag[0])
    if last_dispute:
        activities.append(last_dispute[0])
    
    last_activity = max(activities) if activities else None
    
    # Get AVTP transaction counts for success rate
    num_successful_txns = AVTPLogCRUD.count_successful_transactions(db_session, agent_id)
    num_failed_txns = AVTPLogCRUD.count_failed_transactions(db_session, agent_id)
    
    # Calculate transaction success rate
    if num_successful_txns + num_failed_txns > 0:
        transaction_success_rate = num_successful_txns / (num_successful_txns + num_failed_txns)
    else:
        transaction_success_rate = 0.0
    
    # Get ZKP attestation counts by type
    successful_fair_markup_zkp = db_session.query(TEGAttestationLog).filter(
        and_(
            TEGAttestationLog.agent_did == agent_id,
            TEGAttestationLog.attestation_type == "ProofOfFairMarkup_ZKP_v1",
            TEGAttestationLog.status == "zkp_verified_true"
        )
    ).count()
    
    failed_fair_markup_zkp = db_session.query(TEGAttestationLog).filter(
        and_(
            TEGAttestationLog.agent_did == agent_id,
            TEGAttestationLog.attestation_type == "ProofOfFairMarkup_ZKP_v1",
            TEGAttestationLog.status == "zkp_verified_false"
        )
    ).count()
    
    successful_resource_zkp = db_session.query(TEGAttestationLog).filter(
        and_(
            TEGAttestationLog.agent_did == agent_id,
            TEGAttestationLog.attestation_type == "ProofOfAccurateResourceUsage_ZKP_v1",
            TEGAttestationLog.status == "zkp_verified_true"
        )
    ).count()
    
    failed_resource_zkp = db_session.query(TEGAttestationLog).filter(
        and_(
            TEGAttestationLog.agent_did == agent_id,
            TEGAttestationLog.attestation_type == "ProofOfAccurateResourceUsage_ZKP_v1",
            TEGAttestationLog.status == "zkp_verified_false"
        )
    ).count()
    
    # Get collusion flag count
    collusion_flags = db_session.query(AuditorFlagLog).filter(
        and_(
            AuditorFlagLog.flagged_agent_did == agent_id,
            AuditorFlagLog.rule_violated_code == "BASIC_COLLUSION_PRICE_SYNC_V1",
            AuditorFlagLog.status.in_([
                "auto_flagged_manual_review",
                "manual_review_confirmed",
                "resolved_action_taken_critical_flag"
            ])
        )
    ).count()
    
    return {
        "attestation_count": attestation_count,
        "violation_count": violation_count,
        "dispute_wins": dispute_wins,
        "dispute_losses": dispute_losses,
        "transaction_success_rate": transaction_success_rate,
        "successful_fair_markup_zkp": successful_fair_markup_zkp,
        "failed_fair_markup_zkp": failed_fair_markup_zkp,
        "successful_resource_zkp": successful_resource_zkp,
        "failed_resource_zkp": failed_resource_zkp,
        "collusion_flags": collusion_flags,
        "last_activity": last_activity,
        "current_stake": float(agent.token_balance),
        "reputation_score": agent.reputation_score,
        "reputation_tier": get_reputation_tier(agent.reputation_score)
    }
