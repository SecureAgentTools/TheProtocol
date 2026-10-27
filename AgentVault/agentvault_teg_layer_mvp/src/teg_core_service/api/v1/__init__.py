# API v1 Package

from . import (
    endpoints_admin,
    endpoints_admin_enhanced,
    endpoints_agent,
    endpoints_attestation,
    endpoints_auditor,
    endpoints_avtp,
    endpoints_dispute,
    endpoints_governance,
    endpoints_reputation,
    endpoints_token,
    endpoints_onboarding,
    schemas,
    api  # OPERATION ARCHITECT'S RAZOR - Master Router
)

__all__ = [
    "endpoints_admin",
    "endpoints_admin_enhanced",
    "endpoints_agent",
    "endpoints_attestation",
    "endpoints_auditor",
    "endpoints_avtp",
    "endpoints_dispute",
    "endpoints_governance",
    "endpoints_reputation",
    "endpoints_token",
    "endpoints_onboarding",
    "schemas",
    "api"  # Master router module
]
