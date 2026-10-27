"""
Server-side KeyManager configuration for federated registry discovery.

This module provides a centralized way to configure and access the KeyManager
instance used by the registry server to authenticate to peer registries.
"""

import os
import logging
from typing import Optional

# Mock KeyManager for Docker deployment without agentvault package
class KeyManager:
    def __init__(self, use_env_vars=True, use_keyring=False, env_prefix="", oauth_env_prefix=""):
        self.use_env_vars = use_env_vars
        self.use_keyring = use_keyring
        self.env_prefix = env_prefix
        self.oauth_env_prefix = oauth_env_prefix

logger = logging.getLogger(__name__)

# Global server-side KeyManager instance
_server_keymanager: Optional[KeyManager] = None


def get_server_keymanager() -> KeyManager:
    """
    Get or create the server-side KeyManager instance.
    
    The KeyManager is configured to load peer registry credentials from
    environment variables following the pattern:
    - API Keys: AV_PEER_{PEER_ID}_API_KEY
    - OAuth Client ID: AV_PEER_{PEER_ID}_OAUTH_CLIENT_ID
    - OAuth Client Secret: AV_PEER_{PEER_ID}_OAUTH_CLIENT_SECRET
    
    Returns:
        KeyManager: The configured KeyManager instance
    """
    global _server_keymanager
    
    if _server_keymanager is None:
        logger.info("Initializing server-side KeyManager for federated discovery")
        
        # Create KeyManager with custom environment variable prefixes
        _server_keymanager = KeyManager(
            use_env_vars=True,
            use_keyring=False,  # Server should not use OS keyring
            env_prefix="AV_PEER_",  # For API keys: AV_PEER_{SERVICE}_API_KEY
            oauth_env_prefix="AV_PEER_"  # For OAuth: AV_PEER_{SERVICE}_OAUTH_CLIENT_ID/SECRET
        )
        
        # Log available credentials (without exposing sensitive data)
        _log_available_credentials()
    
    return _server_keymanager


def _log_available_credentials() -> None:
    """Log which peer registry credentials are available (for debugging)."""
    # Check environment variables for peer credentials
    peer_configs = {}
    
    for env_var in os.environ:
        if env_var.startswith("AV_PEER_"):
            # Extract peer identifier
            parts = env_var[8:].split("_")  # Remove "AV_PEER_" prefix
            
            if len(parts) >= 2:
                # Handle API keys
                if parts[-2:] == ["API", "KEY"]:
                    peer_id = "_".join(parts[:-2])
                    if peer_id not in peer_configs:
                        peer_configs[peer_id] = {"api_key": False, "oauth": False}
                    peer_configs[peer_id]["api_key"] = True
                
                # Handle OAuth client ID
                elif parts[-2:] == ["CLIENT", "ID"]:
                    peer_id = "_".join(parts[:-2])
                    if peer_id not in peer_configs:
                        peer_configs[peer_id] = {"api_key": False, "oauth": False}
                    peer_configs[peer_id]["oauth"] = True
    
    if peer_configs:
        logger.info("Server-side peer registry credentials found for:")
        for peer_id, config in peer_configs.items():
            auth_types = []
            if config["api_key"]:
                auth_types.append("API Key")
            if config["oauth"]:
                auth_types.append("OAuth")
            logger.info(f"  - {peer_id}: {', '.join(auth_types)}")
    else:
        logger.warning("No peer registry credentials found in environment variables")
        logger.info("To configure peer credentials, set environment variables like:")
        logger.info("  - AV_PEER_ACME_CORP_API_KEY=<api_key>")
        logger.info("  - AV_PEER_ACME_CORP_OAUTH_CLIENT_ID=<client_id>")
        logger.info("  - AV_PEER_ACME_CORP_OAUTH_CLIENT_SECRET=<client_secret>")


def reset_server_keymanager() -> None:
    """
    Reset the server-side KeyManager instance.
    
    This is mainly useful for testing or when environment variables change.
    """
    global _server_keymanager
    _server_keymanager = None
    logger.info("Server-side KeyManager has been reset")
