"""
Event Store Integration Module for Registry
This module initializes the Event Store integration when the Registry service starts
"""

import logging
# Import removed - patch_agent_crud not implemented in crud_agent_enhanced

logger = logging.getLogger(__name__)


def patch_agent_crud():
    """Actually patch the agent CRUD module with enhanced version"""
    import sys
    from . import crud_agent_enhanced
    from . import crud
    
    # Replace the agent module in crud package with enhanced version
    crud.agent = crud_agent_enhanced
    
    # Update sys.modules so ALL imports get the enhanced version
    # This ensures that any import of 'agentvault_registry.crud.agent' gets the enhanced version
    sys.modules['agentvault_registry.crud.agent'] = crud_agent_enhanced
    
    # Also patch any direct function references that might be cached
    # Replace the create_agent function specifically
    crud.agent.create_agent = crud_agent_enhanced.create_agent
    
    logger.info("✅ Agent CRUD patched with Event Store integration - all agent operations will now emit events")


def initialize_event_store_integration():
    """
    Initialize Event Store integration for Registry service.
    
    This function:
    1. Patches Agent CRUD to emit events for agent operations
    2. Configures the event emitter with proper settings
    """
    try:
        # Patch the Agent CRUD
        patch_agent_crud()
        logger.info("✅ Agent CRUD patched with Event Store integration")
        
        logger.info("🚀 Event Store integration initialized successfully!")
        
        # Log integration details
        logger.info("Event Store integration will emit the following events:")
        logger.info("  - AgentCreated: When new agents are registered")
        logger.info("  - AgentUpdated: When agent profiles are updated")
        logger.info("  - AttestationSubmitted: When attestations are submitted")
        logger.info("  - ReputationChanged: When reputation scores change")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize Event Store integration: {e}")
        # Don't fail the entire service startup
        return False


def get_event_store_status():
    """The event store block of the public GET /health: what the registry writes to its ledger, never where.

    §SECFIX D6-254 (2026-10-16): it carried EVENT_STORE_URL, the store's internal address, to whoever reads /health.
    The block never tested the store; whether the registry reaches its ledger is GET /api/v1/public/supply-invariant."""
    return {
        "enabled": True,
        "source_service": "registry",
        "events_supported": [
            "AgentCreated",
            "AgentUpdated",
            "AttestationSubmitted",
            "ReputationChanged"
        ]
    }
