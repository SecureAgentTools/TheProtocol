"""
Master Router for TEG Core Service API v1

This file serves as the single source of truth for all v1 API routing.
All endpoint routers are imported and included here with their proper prefixes.

OPERATION ARCHITECT'S RAZOR: Single Source of Truth Implementation
"""
import os
import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)

# FIX-006 (OWL17): JWT-SVID auth mode toggle.
# When USE_JWT_SVID_AUTH=true, the /token endpoints use SPIRE JWT-SVID
# validation instead of simple bearer tokens. This replaces the need for
# the separate enhanced_main_jwt_svid.py entry point.
USE_JWT_SVID_AUTH = os.environ.get('USE_JWT_SVID_AUTH', 'false').lower() == 'true'

if USE_JWT_SVID_AUTH:
    logger.info("TEG API: Using JWT-SVID authentication for token endpoints")
    from . import endpoints_token_jwt_svid as endpoints_token
else:
    logger.info("TEG API: Using standard bearer authentication for token endpoints")
    from . import endpoints_token  # noqa: F811

# Import all other endpoint modules
from . import (
    endpoints_auth,  # Authentication endpoints
    endpoints_tokenomics,  # New tokenomics endpoints for staking
    endpoints_tokenomics_enhanced,  # Enhanced tokenomics (rewards, transactions, treasury)
    endpoints_admin_enhanced,
    endpoints_governance,
    endpoints_agent,
    endpoints_attestation,
    endpoints_auditor,
    endpoints_dispute,
    endpoints_reputation,
    endpoints_reputation_signal,  # Reputation signal endpoints
    endpoints_avtp,
    endpoints_onboarding,
    endpoints_internal,
    endpoints_treasury,  # OWL26: Treasury transfer/receive endpoints
    endpoints_bridge,  # SF-3: Wrapped token bridge (lock/unlock/mint/burn)
    endpoints_exchange_admin,  # AGORA: exchange escrow mover (2026-06-12)
)

# Create the master router
api_router = APIRouter()

# Include each logical router with its correct prefix and tag
# NOTE: Prefixes are defined ONLY here, not in the individual endpoint files
api_router.include_router(endpoints_auth.router, prefix="/auth", tags=["Authentication"])
# FIX-006 (OWL17): JWT-SVID endpoints already have prefix="/token" internally,
# so we mount them without an additional prefix to avoid /token/token/...
_token_prefix = "" if USE_JWT_SVID_AUTH else "/token"
# §pass58 PR-10 (Q3 resolved YES): /token/* + /tokenomics/* hidden from public OpenAPI.
# Registry proxy at /api/v1/teg/* is the canonical caller-facing edge for these surfaces.
# Cluster-internal callers (sovereign agents, MCP tools, Hagrid) continue to call them
# directly at runtime — only the spec listing is suppressed.
api_router.include_router(endpoints_token.router, prefix=_token_prefix, tags=["Token Management"], include_in_schema=False)
api_router.include_router(endpoints_tokenomics.router, prefix="/tokenomics", tags=["Tokenomics"], include_in_schema=False)
# Mount admin router with correct paths for token operations
api_router.include_router(endpoints_admin_enhanced.router, prefix="/admin", tags=["Administration"])
api_router.include_router(endpoints_governance.router, prefix="/governance", tags=["Governance"])
api_router.include_router(endpoints_agent.router, prefix="/agent", tags=["Agent Management"])
api_router.include_router(endpoints_attestation.router, prefix="/attestation", tags=["Attestations"])
api_router.include_router(endpoints_auditor.router, prefix="/auditor", tags=["Auditor"])
api_router.include_router(endpoints_dispute.router, prefix="/disputes", tags=["Disputes"])
api_router.include_router(endpoints_reputation.router, prefix="/reputation", tags=["Reputation"])
api_router.include_router(endpoints_avtp.router, prefix="/avtp", tags=["AVTP Integration"])
# D8 (2026-09-05): the TEG's own onboarding faucet is a retired money surface behind a flag —
# default ON (every running TEG byte-identical); the fresh frame's template sets it off.
import os as _os_d8
if (_os_d8.getenv("TEG_ONBOARDING_MINT_ENABLED", "true") or "true").strip().lower() not in ("0", "false", "no", "off"):
    api_router.include_router(endpoints_onboarding.router, prefix="/onboarding", tags=["Onboarding Protocol"])
api_router.include_router(endpoints_internal.router, prefix="/internal", tags=["Internal Service Communication"])

# OWL26: Treasury endpoints (mounted under /admin prefix alongside existing admin endpoints)
api_router.include_router(endpoints_treasury.router, prefix="/admin", tags=["Treasury"])

# AGORA (2026-06-12): exchange escrow mover — every stock-exchange money leg
# flows through /admin/exchange/move (escrow-one-side, exref: idempotent replay).
api_router.include_router(endpoints_exchange_admin.router, prefix="/admin", tags=["Exchange"])

# Mount new endpoints at the end to avoid context issues
# Reputation signal endpoints (mounted under existing /reputation prefix)
api_router.include_router(endpoints_reputation_signal.router, tags=["Reputation Signal"])
# Enhanced tokenomics endpoints (mounted under existing /tokenomics prefix)
# §pass53 PR-10: include_in_schema=False — these are duplicate financial surfaces
# of endpoints_tokenomics.router; the Registry proxy at /api/v1/teg/staking/* is
# the canonical edge. Runtime still serves these routes (internal callers OK),
# they're just hidden from the public OpenAPI to prevent SDK generators from
# emitting a parallel client. See swagger audit T-P1-3.
api_router.include_router(endpoints_tokenomics_enhanced.router, tags=["Tokenomics Enhanced"], include_in_schema=False)

# SF-3: Token Bridge endpoints
api_router.include_router(endpoints_bridge.router, tags=["Token Bridge"])
