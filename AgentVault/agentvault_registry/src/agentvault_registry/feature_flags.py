"""Feature flags for gradual rollout of authentication enhancements

This module manages feature flags that allow controlled rollout of new
authentication features without disrupting existing functionality.
"""

import os
from typing import Dict, Any

# Feature flag environment variables with sensible defaults
FEATURE_FLAGS = {
    # OAuth 2.0 JWT Bearer Grant authentication (Phase 2)
    "oauth_authentication": os.getenv("FF_OAUTH_AUTH", "false").lower() == "true",
    
    # JWT-SVID with SPIFFE/SPIRE support (Phase 2)
    "jwt_svid_enabled": os.getenv("FF_JWT_SVID", "false").lower() == "true",
    
    # mTLS requirement for service-to-service communication (Phase 2)
    "mtls_required": os.getenv("FF_MTLS", "false").lower() == "true",
    
    # Attestation proxy endpoints (Phase 1 - NOW ACTIVE)
    "attestation_proxy": os.getenv("FF_ATTESTATION", "true").lower() == "true",
    
    # Policy management CRUD operations (Phase 1)
    "policy_management": os.getenv("FF_POLICY_MGMT", "false").lower() == "true",
    
    # Enhanced monitoring and metrics (Phase 3)
    "enhanced_monitoring": os.getenv("FF_MONITORING", "false").lower() == "true",
    
    # Performance optimization features (Phase 3)
    "performance_optimizations": os.getenv("FF_PERF_OPT", "false").lower() == "true",
}


def get_feature_flag(flag_name: str) -> bool:
    """
    Get the current value of a feature flag.
    
    Args:
        flag_name: Name of the feature flag
        
    Returns:
        Boolean value of the flag, False if not found
    """
    return FEATURE_FLAGS.get(flag_name, False)


def get_all_flags() -> Dict[str, bool]:
    """
    Get all feature flags and their current values.
    
    Returns:
        Dictionary of all feature flags
    """
    return FEATURE_FLAGS.copy()


def is_oauth_enabled() -> bool:
    """Check if OAuth authentication is enabled."""
    return FEATURE_FLAGS["oauth_authentication"]


def is_jwt_svid_enabled() -> bool:
    """Check if JWT-SVID authentication is enabled."""
    return FEATURE_FLAGS["jwt_svid_enabled"]


def is_mtls_required() -> bool:
    """Check if mTLS is required for service communication."""
    return FEATURE_FLAGS["mtls_required"]


def is_attestation_proxy_enabled() -> bool:
    """Check if attestation proxy endpoints are enabled."""
    return FEATURE_FLAGS["attestation_proxy"]


def get_enabled_features() -> list[str]:
    """
    Get a list of currently enabled features.
    
    Returns:
        List of enabled feature names
    """
    return [name for name, enabled in FEATURE_FLAGS.items() if enabled]


# Log current feature flags on module import
if __name__ != "__main__":
    import logging
    logger = logging.getLogger(__name__)
    enabled_features = get_enabled_features()
    if enabled_features:
        logger.info(f"Feature flags enabled: {', '.join(enabled_features)}")
    else:
        logger.info("No feature flags currently enabled")
