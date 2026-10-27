"""
Enhanced Agent CRUD with Event Store integration.

P2-008: Wire remaining event types beyond AgentCreated.

This module patches Agent CRUD operations to emit events after successful
database operations. Events are emitted fire-and-forget so they never
block or fail the primary operation.

Emits:
  - AgentCreated (on create_agent)
  - AgentUpdated (on update_agent)
  - AttestationSubmitted (on attestation submission)
  - ReputationChanged (on reputation score change)
"""

import asyncio
import logging
from typing import Optional, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Agent
from .event_emitter import EventEmitter
from .config import settings

logger = logging.getLogger(__name__)

# Store the original function BEFORE any patching
from .crud.agent import create_agent as _original_create_agent

# P2-008 FIX: Re-export ALL original functions so the module replacement
# in patch_agent_crud() doesn't lose them. Without these, any code that
# imports get_agent_by_did, verify_agent_credentials etc. from crud.agent
# will break after patching.
from .crud.agent import (
    get_agent_by_client_id,
    get_agent_by_did,
    verify_agent_credentials,
    update_agent_last_active,
)

# Initialize Event Emitter
event_emitter = EventEmitter(
    event_store_url=getattr(settings, 'EVENT_STORE_URL', "http://localhost:8200"),
    internal_api_key=getattr(settings, 'EVENT_STORE_API_KEY', ""),
    source_service="registry"
)


# ============================================================
# Helper: fire-and-forget event emission
# ============================================================

def _fire_event(coro):
    """Schedule an event emission coroutine as a fire-and-forget task."""
    try:
        asyncio.create_task(coro)
    except Exception as e:
        logger.error(f"Failed to schedule event emission: {e}")


# ============================================================
# AgentCreated
# ============================================================

async def enhanced_create_agent(
    db: AsyncSession,
    did: str,
    client_id: str,
    client_secret: str,
    creator_developer_id: int,
    public_key_jwk: Optional[dict] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    capabilities: Optional[list] = None,
    commit: bool = True,
) -> Agent:
    """
    Enhanced create_agent that emits AgentCreated event.

    §FRAMELIC (2026-09-07, findings row 156) — `commit` is FORWARDED, not swallowed.
    This module is exported as `create_agent = enhanced_create_agent` (bottom of file) and
    `routers/onboarding.py` imports THAT name, so the wrapper — not `crud/agent.py` — is what
    the onboard rail actually calls. A parameter added to the callee and not to its wrapper is
    a TypeError at the first real use, which is exactly how row 151's fix took a standup down.
    """
    logger.info(f"Enhanced create_agent called for DID: {did}")

    agent = await _original_create_agent(
        db=db,
        did=did,
        client_id=client_id,
        client_secret=client_secret,
        creator_developer_id=creator_developer_id,
        public_key_jwk=public_key_jwk,
        commit=commit,
    )

    _fire_event(_emit_agent_created(
        agent_did=agent.did,
        name=name or agent.did,
        description=description or "",
        developer_id=str(creator_developer_id),
        capabilities=capabilities or []
    ))

    return agent


async def _emit_agent_created(
    agent_did: str,
    name: str,
    description: str,
    developer_id: str,
    capabilities: list
):
    try:
        success = await event_emitter.emit_agent_created(
            agent_did=agent_did,
            name=name,
            description=description,
            developer_id=developer_id,
            registry_id=settings.REGISTRY_NAME,
            capabilities=capabilities,
            initial_reputation=100
        )
        if success:
            logger.info(f"✅ Emitted AgentCreated for {agent_did}")
        else:
            logger.error(f"❌ Failed to emit AgentCreated for {agent_did}")
    except Exception as e:
        logger.error(f"Error emitting AgentCreated: {e}")


# ============================================================
# AgentUpdated
# ============================================================

async def enhanced_update_agent(
    db: AsyncSession,
    agent: Agent,
    updates: dict
) -> Agent:
    """
    Enhanced update_agent that emits AgentUpdated event.
    """
    # Apply updates
    for key, value in updates.items():
        if hasattr(agent, key):
            setattr(agent, key, value)

    await db.commit()
    await db.refresh(agent)

    _fire_event(_emit_agent_updated(agent.did, updates))
    return agent


async def _emit_agent_updated(agent_did: str, changes: dict):
    try:
        # Filter out non-serializable fields
        safe_changes = {
            k: str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v
            for k, v in changes.items()
        }
        success = await event_emitter.emit_agent_updated(
            agent_did=agent_did,
            changes=safe_changes
        )
        if success:
            logger.info(f"✅ Emitted AgentUpdated for {agent_did}")
        else:
            logger.error(f"❌ Failed to emit AgentUpdated for {agent_did}")
    except Exception as e:
        logger.error(f"Error emitting AgentUpdated: {e}")


# ============================================================
# AttestationSubmitted
# ============================================================

async def emit_attestation_event(
    agent_did: str,
    attestation_type: str,
    attestation_data: Dict
):
    """
    Emit an AttestationSubmitted event. Call this after a successful
    attestation submission in the TEG integration or attestation router.
    
    Usage:
        from agentvault_registry.crud_agent_enhanced import emit_attestation_event
        await emit_attestation_event(agent.did, "zkp_identity", {...})
    """
    _fire_event(_emit_attestation(agent_did, attestation_type, attestation_data))


async def _emit_attestation(
    agent_did: str,
    attestation_type: str,
    attestation_data: Dict
):
    try:
        success = await event_emitter.emit_attestation_submitted(
            agent_did=agent_did,
            attestation_type=attestation_type,
            attestation_data=attestation_data
        )
        if success:
            logger.info(f"✅ Emitted AttestationSubmitted for {agent_did}")
        else:
            logger.error(f"❌ Failed to emit AttestationSubmitted for {agent_did}")
    except Exception as e:
        logger.error(f"Error emitting AttestationSubmitted: {e}")


# ============================================================
# ReputationChanged
# ============================================================

async def emit_reputation_changed_event(
    agent_did: str,
    old_score: int,
    new_score: int,
    reason: str
):
    """
    Emit a ReputationChanged event. Call this after a reputation
    recalculation in the TEG layer or reputation service.
    
    Usage:
        from agentvault_registry.crud_agent_enhanced import emit_reputation_changed_event
        await emit_reputation_changed_event(agent.did, 100, 95, "failed_attestation")
    """
    _fire_event(_emit_reputation_changed(agent_did, old_score, new_score, reason))


async def _emit_reputation_changed(
    agent_did: str,
    old_score: int,
    new_score: int,
    reason: str
):
    try:
        success = await event_emitter.emit_reputation_changed(
            agent_did=agent_did,
            old_score=old_score,
            new_score=new_score,
            reason=reason
        )
        if success:
            logger.info(f"✅ Emitted ReputationChanged for {agent_did}: {old_score} → {new_score}")
        else:
            logger.error(f"❌ Failed to emit ReputationChanged for {agent_did}")
    except Exception as e:
        logger.error(f"Error emitting ReputationChanged: {e}")


# ============================================================
# Module Exports
# ============================================================

# These can be used as drop-in replacements for the original CRUD functions
create_agent = enhanced_create_agent
update_agent = enhanced_update_agent
