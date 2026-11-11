"""
Reputation Manager for the AgentVault Registry.

This module handles the calculation and management of agent reputation scores
based on their actions within the ecosystem, including dispute resolutions
and ZKP attestations.
"""

import logging
import asyncio
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from ..models import Agent, Dispute
from ..event_emitter import get_event_emitter
from ..services import local_trust_updater  # EigenTrust++ Phase 2

logger = logging.getLogger(__name__)


async def update_reputation(
    db: AsyncSession,
    agent_did: str,
    change_amount: int,
    reason: str
) -> Optional[int]:
    """
    Update an agent's reputation score.
    
    Args:
        db: Database session
        agent_did: The DID of the agent to update
        change_amount: The amount to change the reputation by (positive or negative)
        reason: The reason for the reputation change
        
    Returns:
        The new reputation score, or None if agent not found
    """
    try:
        # Find the agent by DID
        result = await db.execute(
            select(Agent).where(Agent.did == agent_did)
        )
        agent = result.scalar_one_or_none()
        
        if not agent:
            logger.warning(f"Agent with DID {agent_did} not found for reputation update")
            return None
            
        # Calculate new reputation score (ensure it doesn't go below 0)
        new_score = max(0, agent.reputation_score + change_amount)
        
        old_score = agent.reputation_score
        
        # Update the agent's reputation
        await db.execute(
            update(Agent)
            .where(Agent.did == agent_did)
            .values(reputation_score=new_score)
        )
        
        await db.commit()
        
        logger.info(
            f"Updated reputation for agent {agent_did}: "
            f"{old_score} -> {new_score} "
            f"(change: {change_amount}, reason: {reason})"
        )
        
        # Emit ReputationChanged event for audit trail
        try:
            event_emitter = get_event_emitter()
            asyncio.create_task(event_emitter.emit_reputation_changed(
                agent_did=agent_did,
                old_score=old_score,
                new_score=new_score,
                reason=reason
            ))
        except Exception as e:
            logger.error(f"Failed to emit ReputationChanged event: {e}")
        
        return new_score
        
    except Exception as e:
        logger.error(f"Error updating reputation for agent {agent_did}: {str(e)}")
        await db.rollback()
        raise


async def record_dispute_outcome(db: AsyncSession, dispute: Dispute) -> list:
    """
    Update reputation scores based on dispute outcome.

    V0657 (a): the changes come from services/dispute_rules.reputation_deltas, the one rule the ruling preview reads
    too; a system-filed dispute (filed_by='system') has rules of its own (nobody accused anybody). Returns what was
    applied: [{"did", "change", "why", "before", "after"}], which the ruling keeps in the record's outcome.

    Args:
        db: Database session
        dispute: The resolved Dispute object
    """
    if not dispute.ruling:
        logger.warning(f"Dispute {dispute.id} has no ruling, skipping reputation update")
        return []

    from ..services.dispute_rules import reputation_deltas
    applied: list = []
    try:
        for did, change, why in reputation_deltas(dispute.ruling, dispute.complainant_did, dispute.defendant_did,
                                                  getattr(dispute, "filed_by", None), getattr(dispute, "reason", None)):
            before = (await db.execute(select(Agent.reputation_score).where(Agent.did == did))).scalar()
            after = await update_reputation(db, did, change, f"Dispute #{dispute.id}: {why}")
            applied.append({"did": did, "change": change, "why": why, "before": before, "after": after})

        # EigenTrust++ Phase 2: update bilateral local trust signal. V0657 (a): on a system-filed dispute a ruling for
        # the complainant is no fault of the worker's unless it missed its deadline (a stuck payout, a silent poster),
        # so no negative signal travels then, as no reputation changes
        from ..services.dispute_rules import trust_signal_applies
        if trust_signal_applies(dispute.ruling, getattr(dispute, "filed_by", None), getattr(dispute, "reason", None)):
            try:
                await local_trust_updater.on_dispute_resolved(
                    db,
                    complainant_did=dispute.complainant_did,
                    defendant_did=dispute.defendant_did,
                    ruling=dispute.ruling,
                )
            except Exception as lt_err:
                logger.warning(f"LocalTrust update failed for dispute {dispute.id} (non-fatal): {lt_err}")

    except Exception as e:
        logger.error(f"Error recording dispute outcome for dispute {dispute.id}: {str(e)}")
        raise
    return applied


async def record_attestation_success(db: AsyncSession, agent_did: str) -> Optional[int]:
    """
    Grant a small reputation boost for successful ZKP attestation.

    Args:
        db: Database session
        agent_did: The DID of the agent that successfully attested

    Returns:
        The new reputation score, or None if agent not found
    """
    return await update_reputation(
        db,
        agent_did,
        1,
        "Successful ZKP attestation"
    )


async def record_attestation_revocation(
    db: AsyncSession, agent_did: str, attestation_id: str
) -> Optional[int]:
    """
    Reverse the +1 reputation boost when an attestation is revoked.
    Phase 3 claw-back coupling. Floors at 0 (never goes negative).
    """
    return await update_reputation(
        db,
        agent_did,
        -1,
        f"ZKP attestation revoked ({attestation_id})",
    )
