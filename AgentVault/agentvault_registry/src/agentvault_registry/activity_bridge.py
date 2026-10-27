"""
Activity Feed Bridge — Maps Event Store events to human-readable system_events
================================================================================
OWL20-PREP: Populates the activity feed (system_events table) from live events.

Usage in any router:
    from ..activity_bridge import record_activity
    
    # After successful operation:
    await record_activity(db, "TokensStaked", agent_did, {"amount": 50})

The bridge maps technical event types to user-friendly activity feed entries.
"""
import logging
from typing import Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from .crud import system_event as system_event_crud
from .core import ledger_names   # W4: an event's old and new names are one event

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════
# Event Type → Activity Feed Mapping
# ═══════════════════════════════════════════════
# Each entry: (event_type_for_db, title_template, description_template)
# Templates use {agent_did} and {data[key]} placeholders

ACTIVITY_MAP = {
    # Tier 1: Balance-affecting (visible to all users)
    "TokensStaked": {
        "event_type": "TOKENS_STAKED",
        "title": "Agent Locked Units",
        "description": "Agent {agent_did_short} locked {amount} {unit}.",
        "icon": "🔒"
    },
    "TokensUnstaked": {
        "event_type": "TOKENS_UNSTAKED",
        "title": "Agent Unlocking Units",
        "description": "Agent {agent_did_short} began unlocking {amount} {unit}.",
        "icon": "🔓"
    },
    "TokensTransferred": {
        "event_type": "TOKENS_TRANSFERRED",
        "title": "Units Transferred",
        "description": "Transfer of {amount} {unit} completed between agents.",
        "icon": "💸"
    },
    "TokensIssued": {
        "event_type": "TOKENS_ISSUED",
        "title": "Units Issued",
        "description": "{amount} {unit} issued to {agent_did_short}. Reason: {reason}.",
        "icon": "🏦"
    },

    # Tier 2: Audit trail (governance & contracts)
    "ContractCreated": {
        "event_type": "CONTRACT_CREATED",
        "title": "New Contract Created",
        "description": "A new upgrade contract was created by {agent_did_short}.",
        "icon": "📝"
    },
    "ContractAccepted": {
        "event_type": "CONTRACT_ACCEPTED",
        "title": "Contract Accepted",
        "description": "An upgrade contract was accepted by an upgrader agent.",
        "icon": "🤝"
    },
    "ContractCompleted": {
        "event_type": "CONTRACT_COMPLETED",
        "title": "Contract Completed",
        "description": "An upgrade contract was completed and payment released.",
        "icon": "✅"
    },
    "DisputeFiled": {
        "event_type": "DISPUTE_FILED",
        "title": "Dispute Filed",
        "description": "A formal dispute was filed by {agent_did_short}.",
        "icon": "⚖️"
    },
    "ProposalCreated": {
        "event_type": "GOVERNANCE_PROPOSAL",
        "title": "New Governance Proposal",
        "description": "Agent {agent_did_short} created a new governance proposal: {title}.",
        "icon": "🏛️"
    },
    "VoteCast": {
        "event_type": "GOVERNANCE_VOTE",
        "title": "Vote Cast",
        "description": "Agent {agent_did_short} voted on a governance proposal.",
        "icon": "🗳️"
    },
    "ProposalTallied": {
        "event_type": "GOVERNANCE_TALLY",
        "title": "Proposal Tallied",
        "description": "A governance proposal was tallied. Result: {result}.",
        "icon": "📊"
    },

    # Tier 3: Operational
    "AgentOnboarded": {
        "event_type": "AGENT_ONBOARDED",
        "title": "New Agent Onboarded",
        "description": "Agent {agent_did_short} joined the AgentVault ecosystem.",
        "icon": "🚀"
    },
    "AgentHeartbeat": None,  # Too noisy for activity feed — skip
    "AgentStatusChanged": {
        "event_type": "AGENT_STATUS_CHANGED",
        "title": "Agent Status Changed",
        "description": "Agent {agent_did_short} status changed to {new_status}.",
        "icon": "🔄"
    },

    # Rewards
    "RewardsDistributed": {
        "event_type": "REWARD_CYCLE",
        "title": "Payout on Locked Units",
        "description": "Payout on locked units: {amount} {unit} to {agent_did_short}.",
        "icon": "💰"
    },
    "RewardsAutoCompounded": {
        "event_type": "REWARD_COMPOUNDED",
        "title": "Payout Re-locked",
        "description": "{amount} {unit} re-locked for {agent_did_short}.",
        "icon": "📈"
    },

    # Attestations (regression)
    "AttestationSubmitted": {
        "event_type": "ATTESTATION_SUBMITTED",
        "title": "ZKP Attestation Verified",
        "description": "Agent {agent_did_short} submitted a verified attestation (circuit: {circuit_id}).",
        "icon": "🔐"
    },
}


def _short_did(agent_did: str) -> str:
    """Truncate DID for display: did:cos:abc123... → abc123..."""
    if agent_did and ":" in agent_did:
        suffix = agent_did.split(":")[-1]
        return suffix[:8] + "..." if len(suffix) > 8 else suffix
    return agent_did[:12] + "..." if agent_did and len(agent_did) > 12 else (agent_did or "unknown")


def _frame_unit() -> str:
    from agentvault_registry.core.frame_currency import frame_currency
    return frame_currency()


def _format_template(template: str, agent_did: str, data: Dict) -> str:
    """Safe template formatting — missing keys become '?'."""
    replacements = {
        "agent_did_short": _short_did(agent_did),
        "agent_did": agent_did or "unknown",
        "amount": str(data.get("amount", "?")),
        # D6-835 (2026-10-25): the unit the event names, else this frame's (it said AVT on every frame)
        "unit": str(data.get("currency") or _frame_unit()),
        "reason": str(data.get("reason", data.get("memo", "system"))),
        "title": str(data.get("title", data.get("scope_description", "?"))),
        "result": str(data.get("result", "?")),
        "new_status": str(data.get("new_status", data.get("status", "?"))),
        "circuit_id": str(data.get("circuit_id", data.get("attestation_type", "?"))),
    }
    try:
        return template.format(**replacements)
    except (KeyError, IndexError):
        return template  # Return raw template if formatting fails


async def record_activity(
    db: AsyncSession,
    event_type: str,
    agent_did: str,
    data: Optional[Dict] = None
) -> bool:
    """
    Record an activity feed entry for a given event.
    
    Call this from routers alongside event_emitter.emit().
    Non-blocking: logs errors but never raises.
    
    Args:
        db: Active database session (from the handler's Depends(get_db))
        event_type: Event Store event type (e.g., "TokensStaked")
        agent_did: The agent's DID
        data: Event data dict (amounts, reasons, etc.)
        
    Returns:
        True if recorded, False if skipped or failed
    """
    data = data or {}
    
    mapping = ACTIVITY_MAP.get(ledger_names.old_name(event_type) if event_type else event_type)   # W4
    if mapping is None:
        # Event type not mapped (e.g., AgentHeartbeat — too noisy)
        return False
    
    try:
        title = _format_template(mapping["title"], agent_did, data)
        description = _format_template(mapping["description"], agent_did, data)
        
        await system_event_crud.create_system_event(
            db=db,
            event_type=mapping["event_type"],
            title=f"{mapping.get('icon', '')} {title}",
            description=description,
            event_metadata={
                "agent_did": agent_did,
                "source_event_type": event_type,
                "data": {k: str(v) for k, v in data.items() if k not in ("proof_data", "proof")}  # Strip large blobs
            }
        )
        logger.debug(f"Activity recorded: {mapping['event_type']} for {_short_did(agent_did)}")
        return True
        
    except Exception as e:
        logger.warning(f"Failed to record activity for {event_type}: {e}")
        return False
