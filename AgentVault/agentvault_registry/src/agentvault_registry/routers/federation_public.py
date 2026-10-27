"""Public federation endpoints for peer registries.

This module contains endpoints that are exposed for inter-registry communication,
including health checks and future federation protocol endpoints.

UPDATED (OWL17 FIX-007): mTLS authentication re-enabled with graceful fallback.
When SPIRE is available, client SPIFFE IDs are extracted and logged.
When SPIRE is unavailable, requests are still allowed (with warning).
"""
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from .. import models

from ..config import settings
from ..database import get_db

# FIX-007 (OWL17): Re-enable mTLS auth with graceful fallback
try:
    from ..core.mtls_auth import extract_spiffe_id_from_cert, forwarded_client_cert
    MTLS_AUTH_AVAILABLE = True
except ImportError:
    MTLS_AUTH_AVAILABLE = False
    logging.warning("mTLS auth module not available — federation health checks will not verify client identity")

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/federation",
    tags=["Federation - Public"]
)


async def get_optional_client_spiffe_id(request: Request) -> Optional[str]:
    """Graceful mTLS authentication — extracts SPIFFE ID if available, returns None otherwise.
    
    FIX-007 (OWL17): This is a non-blocking dependency. It attempts to extract
    the client's SPIFFE ID from mTLS but does not raise 401/403 if the client
    certificate is missing. This allows health checks to work during the
    transition to full mTLS while still logging authenticated clients.
    
    In STRICT mode (set FEDERATION_REQUIRE_MTLS=true), this will enforce mTLS.
    """
    require_mtls = (
        getattr(settings, 'FEDERATION_REQUIRE_MTLS', 'false') 
        if hasattr(settings, 'FEDERATION_REQUIRE_MTLS') 
        else 'false'
    )
    strict = str(require_mtls).lower() == 'true'
    
    if not MTLS_AUTH_AVAILABLE:
        if strict:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="mTLS authentication module not available"
            )
        return None
    
    # Try to extract client certificate from various sources
    client_cert_der = None
    
    # Method 1: TLS extensions (direct TLS termination)
    tls_info = request.scope.get("extensions", {}).get("tls", {}) if request.scope.get("extensions") else {}
    if tls_info and "client_cert_chain" in tls_info:
        client_cert_chain = tls_info.get("client_cert_chain", [])
        if client_cert_chain:
            client_cert_der = client_cert_chain[0]
    
    # Method 2: X-SSL headers (reverse proxy), only what this frame's terminator vouched for (§MTLSHOPS G2)
    if not client_cert_der:
        client_cert_header = forwarded_client_cert(request.headers)
        if client_cert_header:
            import urllib.parse
            from cryptography import x509
            from cryptography.hazmat.backends import default_backend
            from cryptography.hazmat.primitives import serialization
            try:
                client_cert_pem = urllib.parse.unquote(client_cert_header)
                cert = x509.load_pem_x509_certificate(client_cert_pem.encode(), default_backend())
                client_cert_der = cert.public_bytes(serialization.Encoding.DER)
            except Exception as e:
                logger.debug(f"Could not parse X-SSL-Client-Cert header: {e}")
    
    # Method 3: Transport info
    if not client_cert_der:
        transport = request.scope.get("transport", {})
        if isinstance(transport, dict) and "peercert_bin" in transport:
            client_cert_der = transport["peercert_bin"]
    
    if not client_cert_der:
        if strict:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Client certificate required for mTLS authentication"
            )
        logger.debug("No client certificate found in federation request")
        return None
    
    # Extract SPIFFE ID
    spiffe_id = extract_spiffe_id_from_cert(client_cert_der)
    
    if not spiffe_id:
        if strict:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid SPIFFE ID required in client certificate"
            )
        logger.warning("Client certificate present but no SPIFFE ID found")
        return None
    
    # Validate trust domain
    if not spiffe_id.startswith("spiffe://agentvault.com/"):
        if strict:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Client certificate from untrusted SPIFFE domain"
            )
        logger.warning(f"Federation request from untrusted SPIFFE domain: {spiffe_id}")
        return None
    
    logger.info(f"Federation request authenticated via mTLS: {spiffe_id}")
    return spiffe_id


@router.get("/health-check", response_model=Dict[str, Any])
async def federation_health_check(
    db: AsyncSession = Depends(get_db),
    # FIX-007 (OWL17): Graceful mTLS — logs client identity when available
    client_spiffe_id: Optional[str] = Depends(get_optional_client_spiffe_id)
) -> Dict[str, Any]:
    """Health check endpoint for peer registries.
    
    This endpoint is called by other TheProtocol registries (particularly the central registry)
    to verify that this registry instance is operational and reachable.
    
    Supports mTLS authentication: if a valid SPIFFE client certificate is
    presented, the client's identity is logged and included in the response.
    
    Returns:
        JSON response with health status and metadata
    """
    if client_spiffe_id:
        logger.info(f"Health check request from authenticated peer: {client_spiffe_id}")
    else:
        logger.info("Health check request received (unauthenticated)")
    
    registry_name = getattr(settings, 'REGISTRY_NAME', 'AgentVault Registry')
    
    try:
        result = await db.execute(select(func.count()).select_from(models.Developer))
        developer_count = result.scalar()
        db_healthy = True
        logger.info(f"Database health check passed, developer count: {developer_count}")
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_healthy = False
    
    # Check SPIRE/SVID status
    svid_status = "unknown"
    try:
        from ..identity.svid_client import svid_client
        if svid_client.is_initialized():
            svid_status = "mock" if svid_client.is_using_mock() else "real"
        else:
            svid_status = "not_initialized"
    except ImportError:
        svid_status = "module_unavailable"
    
    response = {
        "status": "healthy" if db_healthy else "degraded",
        "registry_name": registry_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "components": {
            "database": "healthy" if db_healthy else "unhealthy",
            "identity_fabric": svid_status
        },
    }
    
    # Include authenticated client info if available
    if client_spiffe_id:
        response["authenticated_by"] = client_spiffe_id
    
    if not db_healthy:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=response
        )
    
    return response


@router.get("/info", response_model=Dict[str, Any])
async def federation_info() -> Dict[str, Any]:
    """Public information about this registry instance.
    
    This endpoint provides basic information about the registry that can be
    accessed without authentication. Used for discovery and initial federation setup.
    
    Returns:
        JSON response with registry information
    """
    # FIX-008 (OWL17): Dynamically report supported auth methods
    # bearer_token removed — deprecated federation auth method
    auth_methods = []
    
    try:
        from ..identity.svid_client import svid_client
        if svid_client.is_initialized():
            if svid_client.is_using_mock():
                auth_methods.append("mtls_mock")
            else:
                auth_methods.append("mtls")
                auth_methods.append("jwt_svid")
    except ImportError:
        auth_methods.append("mtls_planned")
    
    # §pass66 (2026-05-22) — surface `is_mainframe` + `tier` for frontend
    # gating. usePermissions.ts consumes this at app boot to derive `isMainframe`
    # + mainframe-only gates (canMintAvt / canManageFrames / canIssueLicenses /
    # canProvisionOperators). Single endpoint = single source of truth for
    # client-side feature gating decisions; the backend independently enforces
    # via require_mainframe_only dependency.
    from agentvault_registry.core.mainframe_gate import is_mainframe as _is_mainframe
    from agentvault_registry.services.registry_card_builder import _build_tier as _builder_tier
    return {
        "registry_name": getattr(settings, 'REGISTRY_NAME', 'AgentVault Registry'),
        "api_version": "1.0.0",
        "federation_protocol_version": "1.0",
        "supported_auth_methods": auth_methods,
        "health_check_endpoint": "/api/v1/federation/health-check",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        # §FEFRAME W2: this registry's trust domain or nothing; the old default named the retired Frame A, so a
        # registry without SPIRE_TRUST_DOMAIN classified itself (and was classified by every console) as Frame A
        "spiffe_trust_domain": (os.environ.get("SPIRE_TRUST_DOMAIN", "") or "").strip(),
        # §pass66 — frontend gating signal
        "is_mainframe": _is_mainframe(),
        "tier": _builder_tier(),
    }


@router.get("/network-stats")
async def get_federation_network_stats(
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Get federation network statistics."""
    stmt = select(models.PeerRegistry).where(models.PeerRegistry.status == "ACTIVE")
    result = await db.execute(stmt)
    active_peers = result.scalars().all()
    
    # P2-003: Use SQL COUNT instead of loading all agents into memory
    agent_count_stmt = select(func.count()).select_from(models.Agent)
    agent_count_result = await db.execute(agent_count_stmt)
    total_agents = agent_count_result.scalar() or 0
    
    # Cross-registry agents = locally-cached cards that were federation-synced from a
    # peer (their card_data.federation_metadata.source_registry is set). Portable JSONB
    # count; 0 on any read error (best-effort stat, never blocks the endpoint).
    cross_registry_agents = 0
    try:
        from sqlalchemy import text as _sql_text
        cross_registry_agents = (await db.execute(_sql_text(
            "SELECT COUNT(*) FROM agent_cards "
            "WHERE card_data #>> '{federation_metadata,source_registry}' IS NOT NULL"
        ))).scalar() or 0
    except Exception:
        cross_registry_agents = 0

    # §TOURBLOG-3: network-wide ACTIVE/PAID counts for the discovery stat strip. The
    # strip used to sum the visible page, which reads 0 on a first page of fresh
    # federation mirrors. Local scope (no federation_metadata source) keeps the numbers
    # coherent next to totalAgents. Best-effort like the cross-registry count above.
    active_agents_now = 0
    paid_services = 0
    try:
        from sqlalchemy import text as _sql_text2
        _row = (await db.execute(_sql_text2(
            "SELECT "
            "COUNT(*) FILTER (WHERE is_active AND card_data #>> '{federation_metadata,source_registry}' IS NULL), "
            "COUNT(*) FILTER (WHERE (card_data #> '{pricing,payment_required}')::text = 'true' "
            "AND card_data #>> '{federation_metadata,source_registry}' IS NULL) "
            "FROM agent_cards"
        ))).one()
        active_agents_now = int(_row[0] or 0)
        paid_services = int(_row[1] or 0)
    except Exception:
        pass

    # §DISCFIX (2026-08-03): honest additions for the reworked Discovery strip.
    #   networkAgents  — DISTINCT agent_did over active cards = real network-wide
    #                    agent count as seen from this registry (mirrors of one
    #                    agent collapse; name collisions like the forge lineages
    #                    do NOT). Matches /agent-cards/discover facets.total.
    #   localAgents    — active local (non-mirror) cards.
    #   activeAgents24h/15m — real liveness from agents.last_active_at, not the
    #                    near-vacuous is_active listing flag.
    network_agents = 0
    local_agents = 0
    active_24h = 0
    active_15m = 0
    try:
        from sqlalchemy import text as _sql_text3
        _row3 = (await db.execute(_sql_text3(
            "SELECT COUNT(DISTINCT agent_did) FILTER (WHERE agent_did IS NOT NULL), "
            "COUNT(*) FILTER (WHERE card_data #>> '{federation_metadata,source_registry}' IS NULL) "
            "FROM agent_cards WHERE is_active"
        ))).one()
        network_agents = int(_row3[0] or 0)
        local_agents = int(_row3[1] or 0)
        _row4 = (await db.execute(_sql_text3(
            "SELECT COUNT(*) FILTER (WHERE last_active_at > now() - interval '24 hours'), "
            "COUNT(*) FILTER (WHERE last_active_at > now() - interval '15 minutes') "
            "FROM agents"
        ))).one()
        active_24h = int(_row4[0] or 0)
        active_15m = int(_row4[1] or 0)
    except Exception:
        pass

    # P2-002: Compute real health from peer data instead of mock values
    total_peers = len(active_peers)
    healthy_peers = sum(
        1 for p in active_peers 
        if (p.health_check_failure_count or 0) < 3
    )
    network_health = round((healthy_peers / total_peers * 100), 1) if total_peers > 0 else 100.0
    
    last_sync_times = [
        p.last_synced_at for p in active_peers 
        if p.last_synced_at is not None
    ]
    last_global_sync = (
        max(last_sync_times).isoformat() 
        if last_sync_times 
        else None
    )
    
    return {
        "totalRegistries": total_peers + 1,
        "activeRegistries": total_peers,
        "totalAgents": total_agents,
        "crossRegistryAgents": cross_registry_agents,
        "activeAgents": active_agents_now,
        "paidServices": paid_services,
        # §DISCFIX — honest counts (additive; consumers of the keys above unchanged)
        "networkAgents": network_agents,
        "localAgents": local_agents,
        "activeAgents24h": active_24h,
        "activeAgents15m": active_15m,
        "networkHealth": network_health,
        "lastGlobalSync": last_global_sync
    }
