"""
Event Store Integration Module for TEG
This module initializes the Event Store integration when the TEG service starts
"""

import logging
from .transfer_service_enhanced import patch_transfer_service
from .staking_crud_enhanced import patch_staking_crud

logger = logging.getLogger(__name__)


def initialize_event_store_integration():
    """
    Initialize Event Store integration for TEG service.
    
    This function:
    1. Patches TransferService to emit events for transfers and issuance
    2. Patches StakingCRUD to emit events for staking operations
    3. Configures the event emitter with proper settings
    """
    try:
        # Patch the TransferService
        patch_transfer_service()
        logger.info("✅ TransferService patched with Event Store integration")
        
        # Patch the StakingCRUD
        patch_staking_crud()
        logger.info("✅ StakingCRUD patched with Event Store integration")
        
        logger.info("🚀 Event Store integration initialized successfully!")
        
        # Log integration details
        logger.info("Event Store integration will emit the following events:")
        logger.info("  - TokensIssued: When new tokens are minted")
        logger.info("  - TokensTransferred: When tokens are transferred between agents")
        logger.info("  - TokensStaked: When tokens are staked")
        logger.info("  - TokensUnstaked: When tokens are unstaked")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize Event Store integration: {e}")
        # Don't fail the entire service startup
        return False


def get_event_store_status():
    """Get the current status of Event Store integration"""
    from .core.config import get_settings
    
    settings = get_settings()
    
    return {
        "enabled": True,
        "event_store_url": getattr(settings, 'event_store_url', "http://localhost:8200"),
        "source_service": "teg",
        "events_supported": [
            "TokensIssued",
            "TokensTransferred", 
            "TokensStaked",
            "TokensUnstaked"
        ]
    }
