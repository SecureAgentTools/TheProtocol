"""
Configuration settings for the AgentVault CLI.

This module provides centralized configuration management for the CLI,
allowing environment variable overrides for all settings.
"""

import os
from typing import Optional

# OAuth 2.0 Configuration
OAUTH_CLIENT_ID: str = os.getenv("AGENTVAULT_OAUTH_CLIENT_ID", "agentvault-cli")
OAUTH_DEVICE_AUTH_URL: str = os.getenv(
    "AGENTVAULT_OAUTH_DEVICE_AUTH_URL",
    "https://registry.theprotocol.cloud/oauth/device/code"
)
OAUTH_TOKEN_URL: str = os.getenv(
    "AGENTVAULT_OAUTH_TOKEN_URL",
    "https://registry.theprotocol.cloud/oauth/token"
)

# Registry API Configuration
REGISTRY_API_BASE: str = os.getenv(
    "AGENTVAULT_REGISTRY_URL",
    "https://registry.theprotocol.cloud"
)

# HTTP Request Configuration
HTTP_TIMEOUT: float = float(os.getenv("AGENTVAULT_HTTP_TIMEOUT", "30.0"))

# CLI Behavior Configuration
AUTO_OPEN_BROWSER: bool = os.getenv("AGENTVAULT_AUTO_OPEN_BROWSER", "true").lower() == "true"
