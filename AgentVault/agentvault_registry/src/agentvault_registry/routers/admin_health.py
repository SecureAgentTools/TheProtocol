"""Admin health check endpoints for monitoring system health"""

from fastapi import APIRouter, Depends, HTTPException, Request, Body, Security
from typing import Dict, List, Optional, Any, Tuple
import httpx
from ..es_ssl_helper import get_httpx_verify
import asyncio
import time
import os
import re
from agentvault_registry.core.observability_urls import prometheus_url
from agentvault_registry.services.active_alerts import read_active_alerts  # §ALERTS: vmalert's state, via VictoriaMetrics
import uuid
from datetime import datetime, timedelta, timezone
from agentvault_registry import models, security
from agentvault_registry.security import admin_credential, get_current_developer
from agentvault_registry.database import get_db
from agentvault_registry.core import zkp_verifier as _zkp
from agentvault_registry.core import ledger_names   # W4: an event's old and new names are one event
from agentvault_registry.core.path_segment import seg  # §MCPTEST30 V0526: a value in a store/TEG URL path is one encoded segment (round 9: a malformed id read as an outage)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    # §pass56 PR-5: tags= dropped; main.py:include_router supplies "Admin"
    # Fix 1 (2026-04-21): per-endpoint admin flag gates. Each endpoint below
    # gates on either admin_treasury (ledger/financial controls) or admin_platform
    # (system infrastructure). Router-level gate removed because treasury vs
    # platform endpoints now route to different sub-flags.
)

# Store for endpoint definitions - BASIC HEALTH CHECK ONLY
ENDPOINTS_TO_TEST = {
    "auth": [
        {"method": "GET", "path": "/developers/me", "auth": "developer"},
    ],
    "teg": [
        {"method": "GET", "path": "/teg/balance", "auth": "agent"},
        {"method": "GET", "path": "/teg/treasury/balance", "auth": "developer"},
    ],
    "staking": [
        {"method": "GET", "path": "/staking/balance", "auth": "agent"},
        {"method": "GET", "path": "/staking/status", "auth": "agent"},
        {"method": "GET", "path": "/staking/my-positions", "auth": "agent"},
        {"method": "GET", "path": "/staking/apy-tiers", "auth": "none"},
    ],
    "governance": [
        {"method": "GET", "path": "/governance/proposals", "auth": "none"},
        {"method": "GET", "path": "/governance/stats", "auth": "none"},
        {"method": "GET", "path": "/governance/voting-power", "auth": "agent"},
    ],
    "agents": [
        {"method": "GET", "path": "/agent-cards", "auth": "none"},
        {"method": "GET", "path": "/developers/me", "auth": "developer"},
        {"method": "GET", "path": "/developers/me/agents", "auth": "developer"},
        {"method": "GET", "path": "/developers/stats", "auth": "developer"},
    ],
    "federation": [
        {"method": "GET", "path": "/federation/health-check", "auth": "none"},
        {"method": "GET", "path": "/federation/info", "auth": "none"},
    ],
    "metrics": [
        {"method": "GET", "path": "/metrics/agent-activity", "auth": "developer"},
        {"method": "GET", "path": "/metrics/network-health", "auth": "none"},
    ]
}

async def test_endpoint(
    method: str, 
    path: str, 
    auth_type: str,
    developer_token: Optional[str] = None,
    agent_token: Optional[str] = None,
    base_url: str = "http://localhost:8000"
) -> dict:
    """Test a single endpoint and return health status"""
    start_time = time.time()
    
    # Prepare headers based on auth type
    headers = {}
    if auth_type == "developer" and developer_token:
        headers["Authorization"] = f"Bearer {developer_token}"
    elif auth_type == "agent" and agent_token:
        headers["Authorization"] = f"Bearer {agent_token}"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.request(
                method=method,
                url=f"{base_url}/api/v1{path}",
                headers=headers
            )
            
            response_time = int((time.time() - start_time) * 1000)
            
            # Consider 2xx and 3xx as healthy
            healthy = 200 <= response.status_code < 400
            
            return {
                "path": path,
                "method": method,
                "authRequired": auth_type,
                "healthy": healthy,
                "statusCode": response.status_code,
                "responseTime": response_time,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": None if healthy else f"HTTP {response.status_code}"
            }
            
    except httpx.TimeoutException:
        return {
            "path": path,
            "method": method,
            "authRequired": auth_type,
            "healthy": False,
            "statusCode": None,
            "responseTime": 5000,  # Timeout
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": "Timeout (5s)"
        }
    except Exception as e:
        return {
            "path": path,
            "method": method,
            "authRequired": auth_type,
            "healthy": False,
            "statusCode": None,
            "responseTime": int((time.time() - start_time) * 1000),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e)
        }

@router.get("/test-tokens", summary="Issue a short-lived access token for the health checks (admin)")
async def generate_test_tokens(
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform")),
    include_sample_agent: bool = True
) -> Dict[str, Any]:
    """Issue a developer access token, valid for 30 minutes, for the calling administrator, to run the authenticated
    health checks with. `include_sample_agent` adds no agent token (`agent_token` is null, with a note): an agent's
    token needs that agent's own credentials. Needs an admin token with the `admin_platform` flag.
    """
    from agentvault_registry.security import create_access_token
    
    # Generate developer token
    developer_token = create_access_token(
        data={"sub": str(current_developer.id)},
        expires_delta=timedelta(minutes=30)
    )
    
    result = {
        "developer_token": developer_token,
        "developer_id": current_developer.id,
        "developer_email": current_developer.email,
        "token_expiry": "30 minutes",
        "usage": {
            "health_check_authenticated": "Use developer_token automatically for developer endpoints",
            "combined_health": "Set include_auth_tests=true to use developer token",
            "manual_testing": "Add 'Authorization: Bearer {token}' header"
        }
    }
    
    if include_sample_agent:
        # Note: In production, agent tokens require proper agent credentials
        # This is a simplified example for testing
        result["note"] = "Agent token generation requires agent credentials. Use agent registration flow for proper agent tokens."
        result["agent_token"] = None  # Would need actual agent credentials
        result["agent_registration_endpoint"] = "/api/v1/agents/register"
    
    return result

@router.post("/health-check/composite", summary="Composite Health Check with Dual Auth")
async def composite_health_check(
    request: Request,
    agent_token: Optional[str] = Body(None, description="Agent JWT token (optional)", embed=True),
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform"))
) -> Dict[str, Any]:
    """
    Composite health check accepting dual authentication.
    
    Accepts:
    - Developer token in Authorization header (validated by Depends)
    - Agent token in request body
    
    This solves the HTTP single-Authorization-header limitation.
    Frontend can send developer token in header and agent token in body.
    """
    logger.info(f"Composite health check requested by {current_developer.email}")
    
    # Extract developer token from header
    auth_header = request.headers.get("authorization", "")
    developer_token = None
    if auth_header.startswith("Bearer "):
        developer_token = auth_header.replace("Bearer ", "")
    
    # We have both tokens now!
    tokens = {
        "developer": developer_token,
        "agent": agent_token
    }
    
    logger.info(f"Running health check with dual authentication")
    logger.info(f"Developer token: {'Present' if developer_token else 'Missing'}")
    logger.info(f"Agent token: {'Present' if agent_token else 'Missing'}")
    
    # Run comprehensive health check with both tokens
    result = await comprehensive_health_check(
        request=request,
        tokens=tokens,
        current_developer=current_developer,
        include_auth_tests=True
    )
    
    # Add authentication details to result
    result["authentication_used"] = {
        "developer": "From Authorization header",
        "agent": "From request body",
        "dual_auth": True
    }
    
    # Calculate real percentages
    total = result["overallStatus"]["total"]
    healthy = result["overallStatus"]["healthy"]
    percentage = round((healthy / total * 100) if total > 0 else 0, 1)
    
    # Add detailed breakdown
    result["detailed_status"] = {
        "developer_endpoints": 0,
        "agent_endpoints": 0,
        "public_endpoints": 0,
        "developer_success": 0,
        "agent_success": 0,
        "public_success": 0
    }
    
    # Count endpoint types and successes
    for group_name, endpoints in result["results"].items():
        for endpoint in endpoints:
            auth_type = endpoint.get("authRequired", "none")
            if auth_type == "developer":
                result["detailed_status"]["developer_endpoints"] += 1
                if endpoint.get("healthy", False):
                    result["detailed_status"]["developer_success"] += 1
            elif auth_type == "agent":
                result["detailed_status"]["agent_endpoints"] += 1
                if endpoint.get("healthy", False):
                    result["detailed_status"]["agent_success"] += 1
            else:
                result["detailed_status"]["public_endpoints"] += 1
                if endpoint.get("healthy", False):
                    result["detailed_status"]["public_success"] += 1
    
    # Log the summary
    logger.info(f"Health check complete: {healthy}/{total} endpoints healthy ({percentage}%)")
    logger.info(f"Developer endpoints: {result['detailed_status']['developer_success']}/{result['detailed_status']['developer_endpoints']}")
    logger.info(f"Agent endpoints: {result['detailed_status']['agent_success']}/{result['detailed_status']['agent_endpoints']}")
    logger.info(f"Public endpoints: {result['detailed_status']['public_success']}/{result['detailed_status']['public_endpoints']}")
    
    return result

@router.get("/health-check/authenticated", summary="Authenticated Health Check")
async def authenticated_health_check(
    request: Request,
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform")),
    use_current_token: bool = True,
    additional_agent_token: Optional[str] = None,
    agent_client_id: Optional[str] = None,
    agent_client_secret: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run health checks with automatic authentication.
    Automatically uses your current authentication token (developer or agent).
    
    For agent endpoints, you can provide:
    - additional_agent_token: A pre-generated agent JWT token
    - OR agent_client_id + agent_client_secret: Agent credentials to generate a token
    """
    from agentvault_registry.security import create_access_token
    
    # Extract the current authorization token from the request
    auth_header = request.headers.get("authorization", "")
    current_token = None
    if auth_header.startswith("Bearer "):
        current_token = auth_header.replace("Bearer ", "")
    
    tokens = {}
    
    # Set developer token
    if use_current_token and current_token:
        tokens["developer"] = current_token
    else:
        # Generate a fresh developer token
        developer_token = create_access_token(
            data={"sub": str(current_developer.id)},
            expires_delta=timedelta(minutes=5)
        )
        tokens["developer"] = developer_token
    
    # Handle agent authentication
    if additional_agent_token:
        tokens["agent"] = additional_agent_token
    elif agent_client_id and agent_client_secret:
        # Generate agent token from credentials
        try:
            # Call the agent auth endpoint to get a token
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8000/api/v1/auth/agent/token",
                    data={
                        "grant_type": "password",
                        "username": agent_client_id,
                        "password": agent_client_secret
                    }
                )
                if response.status_code == 200:
                    auth_data = response.json()
                    tokens["agent"] = auth_data.get("access_token")
                    logger.info(f"Generated agent token for {agent_client_id}")
                else:
                    logger.warning(f"Failed to authenticate agent: {response.status_code}")
        except Exception as e:
            logger.error(f"Error authenticating agent: {e}")
    else:
        # No agent auth provided, will use developer token (will fail for agent endpoints)
        tokens["agent"] = tokens.get("developer")
    
    # Run the comprehensive health check with tokens
    result = await comprehensive_health_check(
        request=request,
        tokens=tokens,
        current_developer=current_developer,
        include_auth_tests=True
    )
    
    # Add note about authentication used
    result["authentication_note"] = (
        "Using current session token for all endpoints" if use_current_token and current_token
        else "Generated fresh developer token for testing"
    )
    
    return result

@router.get("/health-check/public-only", summary="Public Endpoints Health Check")
async def public_health_check(
    request: Request,
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform"))
) -> Dict[str, Any]:
    """
    Test only public endpoints that don't require authentication.
    This will show 100% healthy if all public endpoints are working.
    """
    # Filter to only test public endpoints
    public_endpoints = {}
    for group, endpoints in ENDPOINTS_TO_TEST.items():
        public_only = [ep for ep in endpoints if ep.get("auth") == "none"]
        if public_only:
            public_endpoints[group] = public_only

    result = await comprehensive_health_check(
        request=request,
        tokens=None,
        current_developer=current_developer,
        include_auth_tests=False,
        endpoints_override=public_endpoints
    )
    result["note"] = "Testing public endpoints only"
    return result

# Standalone function for comprehensive health checks
async def comprehensive_health_check(
    request: Request,
    tokens: Optional[Dict[str, str]] = None,
    current_developer: models.Developer = None,
    include_auth_tests: bool = True,
    agent_client_id: Optional[str] = None,
    agent_client_secret: Optional[str] = None,
    endpoints_override: Optional[Dict[str, list]] = None
):
    """
    Run comprehensive health checks on all system endpoints.
    
    Can accept tokens in request body:
    {
        "developer_token": "...",
        "agent_token": "..."
    }
    
    Returns detailed health status for each endpoint group.
    """
    logger.info(f"Running health check requested by developer {current_developer.email}")
    
    # Get tokens for testing authenticated endpoints
    developer_token = None
    agent_token = None
    
    if include_auth_tests:
        # Fallback to env vars if no credentials provided
        if not agent_client_id:
            agent_client_id = os.environ.get("HEALTH_CHECK_AGENT_CLIENT_ID", "")
        if not agent_client_secret:
            agent_client_secret = os.environ.get("HEALTH_CHECK_AGENT_CLIENT_SECRET", "")

        # First try to get tokens from request body
        if tokens:
            developer_token = tokens.get("developer_token") or tokens.get("developer")
            agent_token = tokens.get("agent_token") or tokens.get("agent")
            if agent_token:
                logger.info("Using provided agent token for auth tests")
        
        # Get developer token from header if not provided
        if not developer_token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                developer_token = auth_header.split(" ")[1]
                logger.info("Using current developer token from header")
        
        # If no agent token yet and we have agent credentials, authenticate to get one
        if not agent_token and agent_client_id and agent_client_secret:
            try:
                logger.info(f"Authenticating as agent {agent_client_id}")
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "http://localhost:8000/api/v1/auth/agent/token",
                        data={
                            "grant_type": "password",
                            "username": agent_client_id,
                            "password": agent_client_secret
                        }
                    )
                    if response.status_code == 200:
                        auth_data = response.json()
                        agent_token = auth_data.get("access_token")
                        logger.info(f"Successfully authenticated as agent {agent_client_id}")
                    else:
                        logger.warning(f"Failed to authenticate agent: {response.status_code}")
            except Exception as e:
                logger.error(f"Error authenticating agent: {e}")
    
    # Test all endpoints in parallel within each group
    results = {}
    all_tasks = []
    
    endpoints_to_use = endpoints_override if endpoints_override is not None else ENDPOINTS_TO_TEST
    for group_name, endpoints in endpoints_to_use.items():
        group_tasks = []
        for endpoint in endpoints:
            task = test_endpoint(
                method=endpoint["method"],
                path=endpoint["path"],
                auth_type=endpoint["auth"],
                developer_token=developer_token,
                agent_token=agent_token
            )
            group_tasks.append(task)
        
        # Run all tests for this group in parallel
        group_results = await asyncio.gather(*group_tasks)
        results[group_name] = group_results
    
    # Calculate summary statistics
    total = sum(len(endpoints) for endpoints in results.values())
    healthy = sum(
        1 for group in results.values() 
        for endpoint in group 
        if endpoint["healthy"]
    )
    unhealthy = total - healthy
    
    # Determine overall status
    if unhealthy == 0:
        status = "Healthy"
        status_emoji = "✅"
    elif healthy > unhealthy:
        status = "Degraded"
        status_emoji = "⚠️"
    else:
        status = "Critical"
        status_emoji = "❌"
    
    # Calculate group summaries
    group_summaries = {}
    for group_name, group_results in results.items():
        group_healthy = sum(1 for r in group_results if r["healthy"])
        group_total = len(group_results)
        group_summaries[group_name] = {
            "healthy": group_healthy,
            "total": group_total,
            "percentage": round((group_healthy / group_total * 100) if group_total > 0 else 0, 1)
        }
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overallStatus": {
            "status": status,
            "emoji": status_emoji,
            "healthy": healthy,
            "unhealthy": unhealthy,
            "total": total,
            "percentage": round((healthy / total * 100) if total > 0 else 0, 1)
        },
        "groupSummaries": group_summaries,
        "results": results,
        "metadata": {
            "checkedBy": current_developer.email,
            "includesAuthTests": include_auth_tests,
            "note": "Some auth-required endpoints may show as unhealthy if tokens not provided"
        }
    }

@router.post("/health-check", summary="Comprehensive Health Check POST")
async def comprehensive_health_check_post(
    request: Request,
    tokens: Optional[Dict[str, str]] = Body(None, description="Optional tokens dict"),
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform")),
    include_auth_tests: bool = True
) -> Dict[str, Any]:
    """The comprehensive health check, with the access tokens to test with in the body:
    `{"developer_token": "...", "agent_token": "..."}`. Needs an admin token with the `admin_platform` flag.
    """
    return await comprehensive_health_check(
        request=request,
        tokens=tokens,
        current_developer=current_developer,
        include_auth_tests=include_auth_tests
    )

@router.get("/health-check", summary="Simple Health Check")
async def simple_health_check_get(
    request: Request,
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform")),
    include_auth_tests: bool = True,
    agent_client_id: Optional[str] = None,
    agent_client_secret: Optional[str] = None
):
    """
    Simple GET health check with automatic agent authentication.
    Pass agent credentials or set HEALTH_CHECK_AGENT_CLIENT_ID/SECRET env vars.
    """
    return await comprehensive_health_check(
        request=request,
        tokens=None,
        current_developer=current_developer,
        include_auth_tests=include_auth_tests,
        agent_client_id=agent_client_id,
        agent_client_secret=agent_client_secret
    )

@router.get("/health-check/simple", summary="Basic Health Check")
async def simple_health_check(
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Quick health check that just verifies the service is running.
    Fix 1 note: retained admin-gated (was router-level admin; now explicit)."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "agentvault-registry",
        "version": "1.0.0"
    }

@router.get("/health-check/with-agent-auth", summary="Health Check with Agent Credentials")
async def health_check_with_agent_auth(
    request: Request,
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform")),
    agent_client_id: Optional[str] = None,
    agent_client_secret: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run health check with specific agent credentials.
    Pass agent credentials or set HEALTH_CHECK_AGENT_CLIENT_ID/SECRET env vars.
    """
    # Get developer token from current session
    auth_header = request.headers.get("authorization", "")
    developer_token = None
    if auth_header.startswith("Bearer "):
        developer_token = auth_header.replace("Bearer ", "")
    
    # Get agent token
    agent_token = None
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/api/v1/auth/agent/token",
                data={
                    "grant_type": "password",
                    "username": agent_client_id,
                    "password": agent_client_secret
                }
            )
            if response.status_code == 200:
                auth_data = response.json()
                agent_token = auth_data.get("access_token")
                logger.info(f"Authenticated as agent {agent_client_id}")
            else:
                logger.warning(f"Agent auth failed: {response.status_code}")
    except Exception as e:
        logger.error(f"Agent auth error: {e}")
    
    # Run health check with both tokens
    tokens = {
        "developer": developer_token,
        "agent": agent_token
    }
    
    result = await comprehensive_health_check(
        request=request,
        tokens=tokens,
        current_developer=current_developer,
        include_auth_tests=True
    )
    
    result["authentication_used"] = {
        "developer": "From current session" if developer_token else "None",
        "agent": f"Authenticated as {agent_client_id}" if agent_token else "Failed to authenticate"
    }
    
    return result

# Docker Container Monitoring Endpoints - NEW FUNCTIONALITY
# NOTE: These endpoints require docker and psutil packages to be installed

# Check if Docker monitoring is available
try:
    import docker
    import psutil
    DOCKER_MONITORING_AVAILABLE = True
except ImportError:
    DOCKER_MONITORING_AVAILABLE = False

def _listed_name(container) -> str:
    """A container's name from what the LIST answered (§DOCKERSTATSRACE, 2026-09-28).

    A sparse docker-py entry carries `Names` ('/name') and no `Name`, so its `.name` is None; a full entry
    carries `Name`; a runner row (services/host_observe.RunnerContainer) and the tests' stand-ins carry a plain
    `.name`. One answer for all three, and no inspect call per container.
    """
    attrs = getattr(container, "attrs", None)
    if isinstance(attrs, dict):
        raw = attrs.get("Name") or next(iter(attrs.get("Names") or []), None)
        if raw:
            return str(raw).lstrip("/")
    return str(getattr(container, "name", None) or "")


def _stats_for_one_container(container) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Collect stats for a single container. Blocks ~1-2s on Docker daemon.

    Returns (container_name, stats_dict) or None if collection fails.
    Extracted as a worker function so the outer collector can parallelize
    across containers via a ThreadPoolExecutor.
    """
    try:
        container_stats = container.stats(stream=False)

        # CPU percentage
        cpu_delta = container_stats["cpu_stats"]["cpu_usage"]["total_usage"] - \
                    container_stats["precpu_stats"]["cpu_usage"]["total_usage"]
        system_cpu_delta = container_stats["cpu_stats"]["system_cpu_usage"] - \
                           container_stats["precpu_stats"]["system_cpu_usage"]
        number_cpus = len(container_stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [])) or 1
        cpu_percentage = 0.0
        if system_cpu_delta > 0 and cpu_delta > 0:
            cpu_percentage = (cpu_delta / system_cpu_delta) * number_cpus * 100.0

        # Memory
        memory_usage = container_stats["memory_stats"].get("usage", 0)
        memory_limit = container_stats["memory_stats"].get("limit", 1)
        memory_percentage = (memory_usage / memory_limit) * 100 if memory_limit > 0 else 0

        # Network
        networks = container_stats.get("networks", {})
        network_rx = sum(net.get("rx_bytes", 0) for net in networks.values())
        network_tx = sum(net.get("tx_bytes", 0) for net in networks.values())

        # Block I/O
        blkio_stats = container_stats.get("blkio_stats", {})
        io_service_bytes = blkio_stats.get("io_service_bytes_recursive", []) or []
        disk_read = sum(stat.get("value", 0) for stat in io_service_bytes if stat.get("op") == "Read")
        disk_write = sum(stat.get("value", 0) for stat in io_service_bytes if stat.get("op") == "Write")

        return _listed_name(container), {
            "id": container.short_id,
            "status": container.status,
            "cpu": {"percentage": round(cpu_percentage, 2), "cores": number_cpus},
            "memory": {
                "usage_bytes": memory_usage,
                "limit_bytes": memory_limit,
                "percentage": round(memory_percentage, 2),
                "usage_mb": round(memory_usage / (1024 * 1024), 2),
                "limit_mb": round(memory_limit / (1024 * 1024), 2),
            },
            "network": {
                "rx_bytes": network_rx,
                "tx_bytes": network_tx,
                "rx_mb": round(network_rx / (1024 * 1024), 2),
                "tx_mb": round(network_tx / (1024 * 1024), 2),
            },
            "disk": {
                "read_bytes": disk_read,
                "write_bytes": disk_write,
                "read_mb": round(disk_read / (1024 * 1024), 2),
                "write_mb": round(disk_write / (1024 * 1024), 2),
            },
        }
    except Exception as exc:
        logger.warning(f"[docker-stats] container {_listed_name(container) or '?'} stats failed: {exc!r}")
        return None


def _collect_docker_stats_sync() -> Dict[str, Any]:
    """Synchronous helper — runs in a thread pool to avoid blocking the event loop.

    §pass63 follow-up (2026-05-22) — parallelized via ThreadPoolExecutor.
    Previously iterated containers serially; with 46 agentvault containers @
    ~2s each, the call took ~90s wall-clock and blew past every reasonable
    timeout. ThreadPoolExecutor(max_workers=16) brings wall-clock to
    ~max(per-container-latency) + thread overhead ≈ 3-5s.

    psutil.cpu_percent(interval=0) drops the obligatory 1s sample window
    (returns the value calculated since last call); harmless when polled
    every refresh tick (>1s apart) which is the common dashboard cadence.
    """
    from concurrent.futures import ThreadPoolExecutor
    from agentvault_registry.services import host_observe as _ho

    # §F6 WP6.2 slice 2: CONTAINER_OBSERVE_VIA=runner reads THIS frame's own compose project through the frame runner (it
    # binds the project to the caller); unset keeps the socket read below, whose 'agentvault' filter matches the legacy
    # Frame A containers on the live frames and none of the frame's own. The runner route fails closed (the route's 503).
    source = _ho.observe_via()
    if source == "runner":
        candidates = [_ho.RunnerContainer(row) for row in (_ho.stats().get("containers") or [])]
    else:
        client = docker.from_env()
        # §DOCKERSTATSRACE (2026-09-28): list SPARSE and filter on the list's own names. The plain `list()`
        # inspects EVERY container on the host (~300 here) before the filter runs, outside the per-container
        # try, so one removed in between (a CI job, a `docker run --rm`) raised NotFound out of the listing and
        # the whole route answered 503 (sbx-alpha during a build: "404 ... No such container"). Now a container
        # that vanished fails only its own stats() read, inside _stats_for_one_container, and is skipped.
        candidates = [c for c in client.containers.list(sparse=True) if 'agentvault' in _listed_name(c).lower()]

    stats: Dict[str, Any] = {}
    if candidates:
        with ThreadPoolExecutor(max_workers=min(16, len(candidates))) as pool:
            for outcome in pool.map(_stats_for_one_container, candidates):
                if outcome is None:
                    continue
                name, container_stats = outcome
                stats[name] = container_stats

    # Host system stats — psutil.cpu_percent(interval=0) is non-blocking.
    host_stats = {
        "cpu_percent": psutil.cpu_percent(interval=0),
        "memory": {
            "total": psutil.virtual_memory().total,
            "available": psutil.virtual_memory().available,
            "percent": psutil.virtual_memory().percent,
            "used": psutil.virtual_memory().used
        },
        "disk": {
            "total": psutil.disk_usage('/').total,
            "used": psutil.disk_usage('/').used,
            "free": psutil.disk_usage('/').free,
            "percent": psutil.disk_usage('/').percent
        }
    }
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "containers": stats,
        "host": host_stats,
        "container_count": len(stats),
        # named only on the runner route, so the default answer stays today's to the byte
        **({"source": "runner (this frame's own compose project)"} if source == "runner" else {}),
    }


@router.get("/docker-stats", summary="Get Docker Container Statistics")
async def get_docker_stats(
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform"))
) -> Dict[str, Any]:
    """Get resource statistics for all TheProtocol Docker containers.
    
    All blocking Docker SDK and psutil calls run in a thread pool
    so the async event loop stays responsive.
    """
    
    if not DOCKER_MONITORING_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Docker monitoring is not available. Required packages (docker, psutil) are not installed."
        )
    
    try:
        # Run all blocking I/O in a thread — event loop stays free
        return await asyncio.to_thread(_collect_docker_stats_sync)
        
    except Exception as e:
        # §pass73.3.21: a docker-stats failure is "service unavailable on this node"
        # (e.g. a consumer cloud-op has no docker socket mounted), NOT an internal
        # server error. Return a self-identifying 503 so callers (and the cloud-op
        # MCP sweep tier-gate) treat it as a node-capability gap, not a 500 bug.
        logger.warning(f"Docker stats unavailable on this node: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Docker stats unavailable on this node (docker socket not reachable — e.g. a consumer cloud-op): {str(e)}",
        )


@router.get("/combined-health", summary="Get Combined Health and Resource Status")
async def get_combined_health(
    request: Request,
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform")),
    include_auth_tests: bool = False,
    agent_token: Optional[str] = None
) -> Dict[str, Any]:
    """Get both health check results and Docker resource statistics in one call.
    
    Args:
        include_auth_tests: If True, will test authenticated endpoints using current developer token
        agent_token: Optional token for testing agent-authenticated endpoints
    """
    
    if not DOCKER_MONITORING_AVAILABLE:
        # Return just health results if Docker monitoring is not available
        health_results = await comprehensive_health_check(
            request=request,
            tokens=None,
            current_developer=current_developer,
            include_auth_tests=False
        )
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "health": health_results,
            "resources": {"error": "Docker monitoring not available"},
            "summary": {
                "services_healthy": health_results["overallStatus"]["healthy"],
                "services_total": health_results["overallStatus"]["total"],
                "docker_monitoring": False
            }
        }
    
    try:
        # Build tokens if auth tests are requested
        tokens = None
        if include_auth_tests:
            from agentvault_registry.security import create_access_token
            developer_token = create_access_token(
                data={"sub": str(current_developer.id)},
                expires_delta=timedelta(minutes=5)
            )
            tokens = {
                "developer": developer_token,
                "agent": agent_token
            }
        
        # Get health check results
        health_results = await comprehensive_health_check(
            request=request,
            tokens=tokens,
            current_developer=current_developer,
            include_auth_tests=include_auth_tests
        )
        
        # Get Docker stats — best-effort. On a node without docker access (e.g. a
        # consumer cloud-op) get_docker_stats now raises 503; combined-health must
        # still return health (its primary purpose), degrading `resources` to
        # health-only rather than 500ing the whole call. §pass73.3.21.
        try:
            docker_stats = await get_docker_stats(current_developer)
        except HTTPException as _de:
            logger.warning(
                f"combined-health: docker stats unavailable ({getattr(_de, 'detail', '')}); "
                f"returning health-only"
            )
            docker_stats = None

        if docker_stats is not None:
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "health": health_results,
                "resources": docker_stats,
                "summary": {
                    "services_healthy": health_results["overallStatus"]["healthy"],
                    "services_total": health_results["overallStatus"]["total"],
                    "containers_running": docker_stats["container_count"],
                    "host_cpu_percent": docker_stats["host"]["cpu_percent"],
                    "host_memory_percent": docker_stats["host"]["memory"]["percent"]
                }
            }
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "health": health_results,
            "resources": {"error": "Docker stats unavailable on this node", "docker_monitoring": False},
            "summary": {
                "services_healthy": health_results["overallStatus"]["healthy"],
                "services_total": health_results["overallStatus"]["total"],
                "docker_monitoring": False
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting combined health status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve combined health status: {str(e)}")


def _collect_system_resources_sync() -> Dict[str, Any]:
    """Synchronous helper — runs in a thread pool to avoid blocking the event loop.
    
    psutil.cpu_percent(interval=1) blocks for 1 full second per call.
    This function calls it twice (global + per-cpu) = 2 seconds of blocking.
    """
    # CPU information
    cpu_info = {
        "percent": psutil.cpu_percent(interval=1),
        "count": psutil.cpu_count(),
        "count_physical": psutil.cpu_count(logical=False),
        "freq": {
            "current": psutil.cpu_freq().current if psutil.cpu_freq() else None,
            "min": psutil.cpu_freq().min if psutil.cpu_freq() else None,
            "max": psutil.cpu_freq().max if psutil.cpu_freq() else None
        },
        "per_cpu": psutil.cpu_percent(interval=1, percpu=True)
    }
    
    # Memory information
    mem = psutil.virtual_memory()
    memory_info = {
        "total": mem.total,
        "available": mem.available,
        "percent": mem.percent,
        "used": mem.used,
        "free": mem.free,
        "total_gb": round(mem.total / (1024**3), 2),
        "available_gb": round(mem.available / (1024**3), 2),
        "used_gb": round(mem.used / (1024**3), 2)
    }
    
    # Disk information
    disk = psutil.disk_usage('/')
    disk_info = {
        "total": disk.total,
        "used": disk.used,
        "free": disk.free,
        "percent": disk.percent,
        "total_gb": round(disk.total / (1024**3), 2),
        "used_gb": round(disk.used / (1024**3), 2),
        "free_gb": round(disk.free / (1024**3), 2)
    }
    
    # Network information
    net_io = psutil.net_io_counters()
    network_info = {
        "bytes_sent": net_io.bytes_sent,
        "bytes_recv": net_io.bytes_recv,
        "packets_sent": net_io.packets_sent,
        "packets_recv": net_io.packets_recv,
        "errin": net_io.errin,
        "errout": net_io.errout,
        "dropin": net_io.dropin,
        "dropout": net_io.dropout
    }
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cpu": cpu_info,
        "memory": memory_info,
        "disk": disk_info,
        "network": network_info
    }


@router.get("/system-resources", summary="Get System Resource Usage")
async def get_system_resources(
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform"))
) -> Dict[str, Any]:
    """Get detailed system resource usage including CPU, memory, disk, and network.
    
    All blocking psutil calls run in a thread pool so the async event loop stays responsive.
    """
    
    if not DOCKER_MONITORING_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="System resource monitoring is not available. Required package (psutil) is not installed."
        )
    
    try:
        # Run all blocking I/O in a thread — event loop stays free
        return await asyncio.to_thread(_collect_system_resources_sync)
        
    except Exception as e:
        logger.error(f"Error getting system resources: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve system resources: {str(e)}")

def _format_event_title(event_type: str) -> str:
    """Map EventStore event_type to human-readable title."""
    mapping = {
        "AgentRegistered":              "Agent Registered",
        "AgentUpdated":                 "Agent Updated",
        "AgentExported":                "Agent Exported",
        "AgentImported":                "Agent Imported",
        "AgentCloned":                  "Agent Cloned",
        # the console's words (§VOCAB, agentvault2-56, 2026-10-23: locked and units, not staked and tokens; his word
        # 2026-10-25 to agentvault2-69: "i dont want the critical wording. only compliant ones"); the type stays the ledger's
        "TokenTransferred":             "Units Transferred",
        "TokensTransferred":            "Units Transferred",
        "TokensIssued":                 "Units Issued",
        "TokensStaked":                 "Units Locked",
        "TokensUnstaked":               "Units Unlocked",
        "RewardDistributed":            "Payout on Locked Units",
        "RewardsDistributed":           "Payout on Locked Units",
        "CrossRegistryTransferCompleted": "Cross-Registry Transfer",
        "DisputeFiled":                 "Dispute Filed",
        "DisputeResolved":              "Dispute Resolved",
        "ProposalCreated":              "Governance Proposal",
        "VoteCast":                     "Vote Cast",
        "ProposalTallied":              "Proposal Tallied",
        "AttestationSubmitted":         "ZKP Attestation",
        "FederationSyncCompleted":      "Federation Sync",
    }
    event_type = ledger_names.old_name(event_type) if event_type else event_type   # W4: a new name titles as its event
    if event_type in mapping:
        return mapping[event_type]
    # any other type as words, with the same swaps (TokensBurned reads "Units Burned"; a snake_case name splits too)
    swap = {"Tokens": "Units", "Token": "Unit", "Staked": "Locked", "Unstaked": "Unlocked", "Stake": "Lock",
            "Unstake": "Unlock", "Staking": "Locking", "Rewards": "Payouts", "Reward": "Payout"}
    words = re.findall(r"[A-Z0-9]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+", event_type) or [event_type]
    return " ".join(swap.get(w, w if w.isupper() else w[:1].upper() + w[1:]) for w in words)


@router.get("/system-activity", summary="System Activity Feed from EventStore")
async def get_system_activity(
    limit: int = 60,
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform"))
) -> Dict[str, Any]:
    """Fetch recent system activity events from EventStore."""
    event_store_url = os.getenv("EVENT_STORE_URL", "http://event-store:8200")
    internal_key = os.getenv("EVENT_STORE_API_KEY", "")

    try:
        async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
            response = await client.get(
                f"{event_store_url}/api/v1/events/",
                headers={"X-Internal-Key": internal_key},
                params={"limit": limit}
            )
            if response.status_code == 200:
                data = response.json()
                raw = data.get("events", data) if isinstance(data, dict) else data
                if not isinstance(raw, list):
                    raw = []
                events = []
                for e in raw[:limit]:
                    etype = e.get("event_type", "system")
                    events.append({
                        "id":          e.get("id") or str(uuid.uuid4()),
                        "event_type":  etype,
                        "title":       _format_event_title(etype),
                        "description": (e.get("description")
                                        or e.get("payload", {}).get("message", "")
                                        or ""),
                        "timestamp":   e.get("timestamp", datetime.now(timezone.utc).isoformat()),
                        "agent_did":   (e.get("aggregate_id")
                                        or e.get("payload", {}).get("agent_id", "")),
                        "severity":    "info",
                    })
                return {"events": events, "total": len(events)}
            return {"events": [], "total": 0, "error": f"EventStore {response.status_code}"}
    except Exception as e:
        logger.error(f"Failed to fetch system activity: {e}")
        return {"events": [], "total": 0, "error": str(e)}


@router.get("/eventstore-stats", summary="EventStore Projection Stats")
async def get_eventstore_stats(
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """Proxy for EventStore /projections/stats.
    Returns total_events, unique_agents, event_counts breakdown.
    Fix 1 note: docstring previously said "no auth required" but router-level
    admin gate made it effectively admin-only. Current: explicit admin_platform.
    Revisit if Mission Control needs truly-public access to aggregate stats."""
    event_store_url = os.getenv("EVENT_STORE_URL", "http://event-store:8200")
    internal_key = os.getenv("EVENT_STORE_API_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
            response = await client.get(
                f"{event_store_url}/api/v1/projections/stats",
                headers={"X-Internal-Key": internal_key},
            )
            if response.status_code == 200:
                return response.json()
            return {"total_events": 0, "unique_agents": 0, "event_counts": {}}
    except Exception as e:
        logger.error(f"Failed to fetch EventStore stats: {e}")
        return {"total_events": 0, "unique_agents": 0, "event_counts": {}}



@router.get("/eventstore-recent", summary="Recent Events (cached)")
async def get_recent_events(
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> List[Dict[str, Any]]:
    """Returns last 15 events from Redis cache. No ES hit. O(1).
    Fix 1 note: same latent-intent mismatch as /eventstore-stats — revisit for true public access.
    Used by landing page to seed the event feed before WebSocket connects."""
    try:
        import json as _json
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r:
            raw = await r.lrange("recent_events", 0, 14)
            return [_json.loads(item) for item in raw]
    except Exception as e:
        logger.error(f"Failed to fetch recent events from Redis: {e}")
    return []


def _own_frame_name() -> str:
    """This registry's own name as the frame manifest keys it (REGISTRY_FEDERATION_NAME, else REGISTRY_NAME), lower
    case; "" when neither is set."""
    return (os.getenv("REGISTRY_FEDERATION_NAME") or os.getenv("REGISTRY_NAME") or "").strip().lower()


def _is_local_frame(frame: str) -> bool:
    """True when `frame` means THIS registry: the 'local' sentinel the console sends, empty, or this registry's own
    name.

    §FEFRAME W4 residue (V0521, his "improvements also approved" 2026-10-01): the retired frames' letters (A/B/C) are
    not frames any more. They were read from SPIRE_TRUST_DOMAIN or LOCAL_FRAME/FRAME_ID, every EU/ASIA registry and
    operator resolved to "A" by the default, and a foreign letter looked for an EVENT_STORE_{A,B,C}_URL that no
    current node sets. Each frame serves its own ledger; a console reads another frame's from that frame's registry
    (useAdminFrames), and old bookmarks' letters are mapped to local in the console before they are sent.
    """
    f = (frame or "").strip().lower()
    own = _own_frame_name()
    return f in ("local", "") or (bool(own) and f == own)


def _reported_frame(frame: str) -> str:
    """The frame to REPORT: this registry's own name (a request past _resolve_event_store is always for it)."""
    return _own_frame_name() or "local"


def _resolve_event_store(frame: str) -> tuple[str, str]:
    """(URL, internal key) of THIS registry's EventStore: the only frame an admin ledger read can name.

    Any other value is refused by name (404) instead of answered empty: an empty read on a forensics or treasury
    surface is indistinguishable from "nothing found", which is how the retired letters misled before.
    """
    if not _is_local_frame(frame):
        raise HTTPException(
            status_code=404,
            detail=(
                f"frame {frame!r} is not this registry: each frame serves its own ledger, "
                "so read that frame's from its own registry"
            ),
        )
    return (
        os.getenv("EVENT_STORE_URL", "http://event-store:8200"),
        os.getenv("EVENT_STORE_API_KEY", ""),
    )


@router.get("/events/search", summary="Search this registry's ledger (admin)")
async def get_events_search(
    limit: int = 100,
    offset: int = 0,
    event_type: Optional[str] = None,
    # §FEDSUITE 2026-09-04: see get_treasury_aggregate — same class. A
    # frame-aware endpoint defaulting to "A" resolves as FOREIGN on frame-b /
    # frame-c and yields an EMPTY result, which on a forensics surface is
    # indistinguishable from "nothing found". Byte-identical on frame A.
    frame: str = "local",
    sort_order: str = "desc",
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """
    Search this registry's ledger (its event store's GET /api/v1/events/): `limit` (at most 10,000), `offset`,
    `event_type`, newest first unless `sort_order` is `asc`. `frame` is `local` (the default) or this registry's own
    name; any other frame's ledger is read from that frame's own registry (404 here). Needs an admin token with the
    `admin_platform` flag.

    \f
    Build #6 (2026-05-07): proxy EventStore GET /api/v1/events/ for admin UI.
    Build #6.1 (2026-05-07): added `frame` parameter so admins can browse Frame B's
    sovereign EventStore from the same UI. Both frames are accessible because:
      (1) registry-a is attached to frame_b_network (compose change)
      (2) EVENT_STORE_B_URL + EVENT_STORE_B_API_KEY are set in registry-a env
    Bug fix #2 (2026-05-07): added `sort_order` (default 'desc') so the admin
    UI surfaces newest-first by default. Commander reported genesis-period
    events on the unfiltered first page; root cause was EventStore's legacy
    ASC default. EventStore now accepts `sort_order=desc` (additive change);
    legacy SF-4 callers omit the param and still get ASC.

    Mirrors the EventStore endpoint signature with one wrapper concession:
    returns a dict {events, count} so the frontend can extend later with
    pagination metadata without breaking the contract.
    """
    event_store_url, internal_key = _resolve_event_store(frame)
    sort_order = (sort_order or "desc").lower()
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"
    params: Dict[str, Any] = {
        # ES route caps at le=10000; allow the full per-request window so the
        # Event Ledger "All"/export loop-fetch reaches large sets in few hops.
        "limit": min(limit, 10000),
        "offset": max(offset, 0),
        "sort_order": sort_order,
    }
    if event_type:
        params["event_type"] = event_type
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=get_httpx_verify()) as client:
            response = await client.get(
                f"{event_store_url}/api/v1/events/",
                params=params,
                headers={"X-Internal-Key": internal_key},
            )
            if response.status_code == 200:
                events = response.json()
                return {"events": events, "count": len(events), "frame": _reported_frame(frame)}
            logger.warning(f"EventStore search (frame={frame}) returned {response.status_code}")
            return {"events": [], "count": 0, "frame": _reported_frame(frame)}
    except Exception as e:
        logger.error(f"Failed to query EventStore (frame={frame}): {e}")
        return {"events": [], "count": 0, "frame": _reported_frame(frame), "error": str(e)}


@router.get("/events/aggregate/{aggregate_id}", summary="EventStore by aggregate (Build #6, frame-aware)")
async def get_events_by_aggregate(
    aggregate_id: str,
    # §FEDSUITE 2026-09-04: see get_treasury_aggregate — same class. A
    # frame-aware endpoint defaulting to "A" resolves as FOREIGN on frame-b /
    # frame-c and yields an EMPTY result, which on a forensics surface is
    # indistinguishable from "nothing found". Byte-identical on frame A.
    frame: str = "local",
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """Build #6.1: proxy EventStore GET /events/aggregate/{aggregate_id} with frame switch."""
    event_store_url, internal_key = _resolve_event_store(frame)
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=get_httpx_verify()) as client:
            response = await client.get(
                f"{event_store_url}/api/v1/events/aggregate/{seg(aggregate_id)}",
                headers={"X-Internal-Key": internal_key},
            )
            if response.status_code == 200:
                events = response.json()
                return {"events": events, "count": len(events), "frame": _reported_frame(frame)}
            return {"events": [], "count": 0, "frame": _reported_frame(frame)}
    except Exception as e:
        logger.error(f"Failed to query EventStore aggregate (frame={frame}): {e}")
        return {"events": [], "count": 0, "frame": _reported_frame(frame), "error": str(e)}


# ── Ledger Forensics proxies (2026-06-19) — frame-aware passthrough to the ES
#    /api/v1/forensics/* read API (search / txid trace / detector scan). Same
#    admin_platform gate + X-Internal-Key proxy pattern as /events/search above.
@router.get("/forensics/search", summary="Ledger Forensics — time-windowed payload search (frame-aware)")
async def forensics_search(
    start: Optional[str] = None,
    end: Optional[str] = None,
    event_type: Optional[str] = None,
    aggregate_id: Optional[str] = None,
    transaction_id: Optional[str] = None,
    kind: Optional[str] = None,
    source_service: Optional[str] = None,
    idempotency_prefix: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    order: str = "desc",
    # §FEDSUITE 2026-09-04: see get_treasury_aggregate — same class. A
    # frame-aware endpoint defaulting to "A" resolves as FOREIGN on frame-b /
    # frame-c and yields an EMPTY result, which on a forensics surface is
    # indistinguishable from "nothing found". Byte-identical on frame A.
    frame: str = "local",
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    event_store_url, internal_key = _resolve_event_store(frame)
    if not event_store_url:
        return {"events": [], "count": 0, "frame": _reported_frame(frame), "error": "frame not configured"}
    params: Dict[str, Any] = {"limit": min(max(limit, 1), 1000), "offset": max(offset, 0), "order": order}
    for k, v in (
        ("start", start), ("end", end), ("event_type", event_type), ("aggregate_id", aggregate_id),
        ("transaction_id", transaction_id), ("kind", kind), ("source_service", source_service),
        ("idempotency_prefix", idempotency_prefix),
    ):
        if v:
            params[k] = v
    try:
        async with httpx.AsyncClient(timeout=20.0, verify=get_httpx_verify()) as client:
            r = await client.get(
                f"{event_store_url}/api/v1/forensics/search", params=params,
                headers={"X-Internal-Key": internal_key},
            )
            if r.status_code == 200:
                d = r.json()
                d["frame"] = frame.upper()
                return d
            return {"events": [], "count": 0, "frame": _reported_frame(frame), "error": f"eventstore {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        logger.error(f"forensics search (frame={frame}) failed: {e}")
        return {"events": [], "count": 0, "frame": _reported_frame(frame), "error": str(e)}


@router.get("/forensics/trace/{transaction_id}", summary="Ledger Forensics — txid event timeline (frame-aware)")
async def forensics_trace(
    transaction_id: str,
    # §FEDSUITE 2026-09-04: see get_treasury_aggregate — same class. A
    # frame-aware endpoint defaulting to "A" resolves as FOREIGN on frame-b /
    # frame-c and yields an EMPTY result, which on a forensics surface is
    # indistinguishable from "nothing found". Byte-identical on frame A.
    frame: str = "local",
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    event_store_url, internal_key = _resolve_event_store(frame)
    if not event_store_url:
        return {"events": [], "count": 0, "frame": _reported_frame(frame), "error": "frame not configured"}
    try:
        async with httpx.AsyncClient(timeout=20.0, verify=get_httpx_verify()) as client:
            r = await client.get(
                f"{event_store_url}/api/v1/forensics/trace/{transaction_id}",
                headers={"X-Internal-Key": internal_key},
            )
            if r.status_code == 200:
                d = r.json()
                d["frame"] = frame.upper()
                return d
            return {"events": [], "count": 0, "frame": _reported_frame(frame), "error": f"eventstore {r.status_code}"}
    except Exception as e:
        logger.error(f"forensics trace (frame={frame}) failed: {e}")
        return {"events": [], "count": 0, "frame": _reported_frame(frame), "error": str(e)}


@router.get("/forensics/scan", summary="Ledger Forensics — detector scan (frame-aware)")
async def forensics_scan(
    start: Optional[str] = None,
    end: Optional[str] = None,
    # §FEDSUITE 2026-09-04: see get_treasury_aggregate — same class. A
    # frame-aware endpoint defaulting to "A" resolves as FOREIGN on frame-b /
    # frame-c and yields an EMPTY result, which on a forensics surface is
    # indistinguishable from "nothing found". Byte-identical on frame A.
    frame: str = "local",
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    event_store_url, internal_key = _resolve_event_store(frame)
    if not event_store_url:
        return {"findings": [], "frame": _reported_frame(frame), "error": "frame not configured"}
    params: Dict[str, Any] = {}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    try:
        async with httpx.AsyncClient(timeout=30.0, verify=get_httpx_verify()) as client:
            r = await client.get(
                f"{event_store_url}/api/v1/forensics/scan", params=params,
                headers={"X-Internal-Key": internal_key},
            )
            if r.status_code == 200:
                d = r.json()
                d["frame"] = frame.upper()
                return d
            return {"findings": [], "frame": _reported_frame(frame), "error": f"eventstore {r.status_code}"}
    except Exception as e:
        logger.error(f"forensics scan (frame={frame}) failed: {e}")
        return {"findings": [], "frame": _reported_frame(frame), "error": str(e)}


@router.get("/forensics/inventory", summary="Ledger Forensics — registry-DB stuck-funds rails (read-only)")
async def forensics_inventory(
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """On-demand stuck-funds inventory across THIS registry's own DB rails.
    Each rail is a bounded, status-filtered query with a 4s statement_timeout
    seatbelt + isolated try/except (a slow/missing rail degrades, never hangs the
    endpoint or aborts the others). AGORA escrow/gateway (compute_invariants +
    gateway-keeper) and per-user negatives (auditor) are surfaced separately by
    the board; TEG-DB-direct rails (locked_balance / cross_teg FUNDS_LOCKED) need
    TEG credentials and are intentionally NOT queried here."""
    from sqlalchemy import text as _text

    async def _rail(sql: str, *, rail: str, cls: str, severity: str, heal: str,
                    holding: str, detail: str, currency: Optional[str] = None) -> Dict[str, Any]:
        try:
            await db.execute(_text("SET LOCAL statement_timeout = 4000"))
            row = (await db.execute(_text(sql))).first()
            n = int(row[0]) if row else 0
            s = float(row[1]) if (row and row[1] is not None) else 0.0
            samples = [str(x) for x in (row[2] or [])] if (row and len(row) > 2 and row[2]) else []
            return {"rail": rail, "class": cls, "severity": severity, "heal": heal,
                    "holding": holding, "detail": detail, "currency": currency,
                    "count": n, "sum": s, "samples": samples}
        except Exception as e:  # noqa: BLE001 — one rail must never break the rest
            try:
                await db.rollback()
            except Exception:
                pass
            return {"rail": rail, "class": cls, "severity": "info", "heal": heal,
                    "holding": holding, "detail": detail, "currency": currency,
                    "count": None, "sum": None, "samples": [], "error": str(e)[:160]}

    rails: List[Dict[str, Any]] = []
    # Cross-frame async: sender debited, saga past timeout, not yet settled/refunded.
    rails.append(await _rail(
        "SELECT count(*), coalesce(sum(amount),0), (array_agg(id ORDER BY timeout_at))[1:5] "
        "FROM cross_frame_transfers WHERE status='locked' AND timeout_at < now()",
        rail="cross_frame_async", cls="orphan_saga_past_timeout", severity="high", heal="auto",
        holding="sender token_balance (debited at lock)",
        detail="saga_timeout_checker auto-refunds these; a row persisting many cycles means the loop is wedged or the counterparty TEG is unreachable."))
    # A2A: SETTLING stuck (in-flight money state) past the 90s recovery cutoff.
    rails.append(await _rail(
        "SELECT count(*), coalesce(sum(amount),0), (array_agg(id ORDER BY created_at))[1:5] "
        "FROM a2a_payment_authorizations WHERE status='settling' "
        "AND coalesce(consumed_at, created_at) < now() - interval '90 seconds'",
        rail="a2a_payment", cls="settling_stale", severity="warn", heal="auto",
        holding="no escrow (funds only move at settle)",
        detail="a2a_payment_expiry asks each stale SETTLING token's settlement record (§DOCSFIX D6-437): a kept success settles it, a failure or nothing fails it, and a claim still held (a transfer whose answer was lost: up to 24 h) leaves it SETTLING; a row that persists is a settlement whose outcome is not known, so cross-check the payer's transactions before anyone pays again."))
    # A2A: CONSUMED but never settled past TTL — service did paid work, unpaid.
    rails.append(await _rail(
        "SELECT count(*), coalesce(sum(amount),0), (array_agg(id ORDER BY expires_at))[1:5] "
        "FROM a2a_payment_authorizations WHERE status='consumed' AND expires_at < now()",
        rail="a2a_payment", cls="consumed_unsettled", severity="warn", heal="human",
        holding="no escrow",
        detail="agent verified + did the work, payer never called settle; the expiry worker does NOT sweep CONSUMED — service unpaid."))
    # Bridge: LOCKED past expiry (defensive — incl. the inbound blind spot).
    rails.append(await _rail(
        "SELECT count(*), coalesce(sum(amount),0), (array_agg(id ORDER BY expires_at))[1:5] "
        "FROM bridge_transactions WHERE status='LOCKED' AND expires_at < now()",
        rail="bridge", cls="locked_past_expiry", severity="high", heal="auto",
        holding="sender locked_balance (TEG)",
        detail="bridge_expiry unlocks outbound LOCKED; inbound + FAILED-with-stuck-lock are blind spots."))
    # Fiat: captured EUR, credit failed, no auto-refund (direct flow).
    rails.append(await _rail(
        "SELECT count(*), coalesce(sum(amount_eur),0), (array_agg(id ORDER BY created_at DESC))[1:5] "
        "FROM fiat_purchases WHERE status='failed' "
        "AND (coalesce(failure_reason,'') IN ('reward_fund_failed','anonymous_resolve_failed','no_target_agent_resolved') "
        "OR failure_reason LIKE 'reward_fund_partial:%')",
        rail="fiat", cls="paid_failed_no_refund", severity="high", heal="human", currency="EUR",
        holding="captured at Stripe",
        detail="direct-flow buyer paid EUR, the credit (in this registry's unit) failed past fiat_credit_retry's budget or landed only in part "
               "(reward_fund_partial), and (unlike the routed flow) NO Stripe refund was issued."))
    # Fiat: captured EUR, the credit OWED (§LEDGERGATE V0599): fiat_credit_retry asks again with the purchase's own key.
    rails.append(await _rail(
        "SELECT count(*), coalesce(sum(amount_eur),0), (array_agg(id ORDER BY credit_next_attempt_at))[1:5] "
        "FROM fiat_purchases WHERE status='processing' AND routed = false AND failure_reason LIKE 'credit_owed:%'",
        rail="fiat", cls="paid_credit_owed", severity="warn", heal="auto", currency="EUR",
        holding="captured at Stripe",
        detail="direct-flow buyer paid EUR and the credit (in this registry's unit) did not land yet (the ledger gate's refusal or a TEG error); "
               "fiat_credit_retry credits it with the purchase's own idempotency key, then the purchase completes."))

    total_flagged = sum((r.get("count") or 0) for r in rails)
    return {
        "rails": rails,
        "total_flagged": total_flagged,
        "note": "Registry-DB rails only. AGORA escrow/gateway + per-user negatives are on the Stuck Funds board; TEG-direct + cross-frame pairing need the backend verdict engine (deferred).",
    }


@router.get("/forensics/findings", summary="Ledger Forensics — Open Findings inbox (scanner)")
async def forensics_findings(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """Read the forensic_scanner's Open Findings inbox. Degrades to empty +
    scanner_inactive=true when the table doesn't exist (worker never enabled)."""
    from sqlalchemy import text as _text
    try:
        sql = ("SELECT finding_key, source, severity, title, detail, count, amount, currency, frame, "
               "status, first_seen, last_seen, acked_at, acked_by FROM forensic_findings")
        params: Dict[str, Any] = {}
        if status in ("open", "acked"):
            sql += " WHERE status = :st"
            params["st"] = status
        sql += (" ORDER BY (severity='critical') DESC, (severity='high') DESC, "
                "(severity='warn') DESC, last_seen DESC LIMIT 500")
        rows = (await db.execute(_text(sql), params)).mappings().all()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            for k in ("first_seen", "last_seen", "acked_at"):
                if d.get(k) is not None:
                    d[k] = d[k].isoformat()
            if d.get("amount") is not None:
                d["amount"] = float(d["amount"])
            out.append(d)
        return {"findings": out, "count": len(out)}
    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass
        return {"findings": [], "count": 0, "scanner_inactive": True, "detail": str(e)[:140]}


@router.post("/forensics/findings/{finding_key:path}/ack", summary="Acknowledge a forensic finding")
async def forensics_findings_ack(
    finding_key: str,
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    from sqlalchemy import text as _text
    try:
        actor = getattr(_admin, "email", None) or "admin"
        res = await db.execute(_text(
            "UPDATE forensic_findings SET status='acked', acked_at=now(), acked_by=:a WHERE finding_key=:k"
        ), {"a": actor, "k": finding_key})
        await db.commit()
        return {"acked": finding_key, "rows": res.rowcount}
    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=f"ack failed: {str(e)[:140]}")


@router.get("/eventstore-balances", summary="EventStore Agent Balance Projections")
async def get_eventstore_balances(
    current_developer: models.Developer = Security(security.require_admin_flag("admin_treasury"))
) -> Dict[str, Any]:
    """Proxy EventStore /projections/balances for frontend (avoids direct port access).

    §MCPTEST30 (2026-10-01): a store that cannot answer is an error, never an empty list. Any failure used to answer
    {"agents": []}, which reads exactly like "the store holds no agents" to the admin MCP tool (getEventStoreBalances,
    "useful for reconciliation") and to anyone reconciling the two ledgers. The globe view's caller already catches and
    falls back to an empty list, so it renders as before."""
    event_store_url = os.getenv("EVENT_STORE_URL", "http://event-store:8200")
    internal_key = os.getenv("EVENT_STORE_API_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
            response = await client.get(
                f"{event_store_url}/api/v1/projections/balances",
                headers={"X-Internal-Key": internal_key},
            )
    except Exception as e:
        logger.error(f"Failed to fetch EventStore balances: {e}")
        raise HTTPException(status_code=503, detail=f"The EventStore could not be reached ({type(e).__name__})")
    if response.status_code != 200:
        logger.error(f"EventStore balances answered HTTP {response.status_code}")
        raise HTTPException(status_code=502, detail=f"The EventStore answered HTTP {response.status_code}")
    return response.json()


@router.get("/fee-collector/info", summary="The fee account's balance and recent fees (admin)")
async def get_fee_collector_info(
    period: str = "7d",
    _admin: models.Developer = Security(security.require_admin_flag("admin_treasury")),
) -> Dict[str, Any]:
    """
    This frame's fee account (`teg:system:fee_collector` unless configured otherwise): its balance, read from the
    TEG, and the fees the ledger recorded over `period` (`24h`, `7d` by default, `30d` or `all`), as totals, buckets
    for a chart and the latest 50 fee events. Needs an admin token with the `admin_treasury` flag.

    \f
    Phase 1 — Fee collector visibility for the Treasury view.

    Combines:
      - TEG `/admin/fee-collector/info` for live balance + DID
      - EventStore `/events?event_type=TransactionFeeCollected&limit=200` for
        recent inflows (per-bucket sparkline + recent fee event feed)

    Frame B note: this endpoint queries the LOCAL TEG (Frame A on registry-a,
    Frame B on registry-b — sovereign isolation preserved).
    """
    from collections import defaultdict
    from decimal import Decimal, InvalidOperation

    period = (period or "7d").lower()
    now = datetime.now(timezone.utc)
    if period == "24h":
        cutoff = now - timedelta(hours=24)
        bucket_count, bucket_size = 24, timedelta(hours=1)
    elif period == "7d":
        cutoff = now - timedelta(days=7)
        bucket_count, bucket_size = 7, timedelta(days=1)
    elif period == "30d":
        cutoff = now - timedelta(days=30)
        bucket_count, bucket_size = 30, timedelta(days=1)
    elif period == "all":
        cutoff = None
        bucket_count, bucket_size = 30, timedelta(days=1)
    else:
        raise HTTPException(status_code=400, detail=f"Invalid period: {period}")

    def _parse_ts(s: str) -> Optional[datetime]:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def _to_decimal(v: Any) -> Decimal:
        try:
            return Decimal(str(v or "0"))
        except (InvalidOperation, ValueError):
            return Decimal("0")

    # 1. Live balance from TEG admin endpoint
    teg_api_base_url = os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080")
    teg_admin_api_key = os.getenv("TEG_ADMIN_API_KEY", "")
    fee_collector_did: Optional[str] = None
    balance: Optional[str] = None
    teg_error: Optional[str] = None
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
            r = await client.get(
                f"{teg_api_base_url}/api/v1/admin/fee-collector/info",
                headers={"Authorization": f"Bearer {teg_admin_api_key}"},
            )
            if r.status_code == 200:
                d = r.json()
                fee_collector_did = d.get("fee_collector_did")
                balance = str(d.get("balance", "0"))
            else:
                teg_error = f"TEG returned {r.status_code}"
    except Exception as e:
        teg_error = str(e)
        logger.warning(f"fee_collector info: TEG fetch failed: {e}")

    # 2. Recent fee inflows from EventStore (Frame A only here; frame-aware
    #    not yet wired — Phase 1 keeps it local. The EventStore Explorer
    #    Build #6.1 has the frame switch if operator wants Frame B history.)
    event_store_url = os.getenv("EVENT_STORE_URL", "http://event-store:8200")
    internal_key = os.getenv("EVENT_STORE_API_KEY", "")
    all_fees: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=get_httpx_verify()) as client:
            r = await client.get(
                f"{event_store_url}/api/v1/events/",
                params={"event_type": "TransactionFeeCollected", "limit": 200},
                headers={"X-Internal-Key": internal_key},
            )
            if r.status_code == 200:
                all_fees = r.json() or []
    except Exception as e:
        logger.warning(f"fee_collector info: EventStore fetch failed: {e}")

    # 3. Filter to window + aggregate
    fees_in: List[Dict[str, Any]] = []
    for f in all_fees:
        ts = _parse_ts(f.get("timestamp"))
        if ts is None:
            continue
        if cutoff is None or ts >= cutoff:
            fees_in.append(f)

    total_inflow_window = sum(
        (_to_decimal(f.get("data", {}).get("fee_amount")) for f in fees_in),
        Decimal("0"),
    )

    # Sparkline bucket cutoff
    if cutoff is None and fees_in:
        earliest = min(
            (_parse_ts(e.get("timestamp")) or now for e in fees_in),
            default=now - timedelta(days=30),
        )
        cutoff_for_bucket = max(earliest, now - timedelta(days=30))
    else:
        cutoff_for_bucket = cutoff or (now - timedelta(days=30))

    sparkline: List[Dict[str, Any]] = []
    for i in range(bucket_count):
        b_start = cutoff_for_bucket + bucket_size * i
        b_end = cutoff_for_bucket + bucket_size * (i + 1)
        bucket_sum = Decimal("0")
        bucket_count_n = 0
        for f in fees_in:
            ts = _parse_ts(f.get("timestamp"))
            if ts and b_start <= ts < b_end:
                bucket_sum += _to_decimal(f.get("data", {}).get("fee_amount"))
                bucket_count_n += 1
        sparkline.append({
            "t": b_start.isoformat(),
            "amount": str(bucket_sum),
            "count": bucket_count_n,
        })

    # 4. Recent fee events (last 50, period-filtered, sorted DESC)
    sorted_fees = sorted(fees_in, key=lambda x: x.get("timestamp") or "", reverse=True)
    recent = []
    for f in sorted_fees[:50]:
        d = f.get("data") or {}
        # Fee payer fallback chain (matches Treasury aggregate logic):
        # data.agent_did → data.from → event.aggregate_id
        payer = d.get("agent_did") or d.get("from") or f.get("aggregate_id") or "unknown"
        recent.append({
            "id": f.get("id"),
            "timestamp": f.get("timestamp"),
            "payer_did": payer,
            "fee_amount": d.get("fee_amount", "0"),
            "fee_type": d.get("fee_type"),
            "transfer_amount": d.get("transfer_amount"),
            "transaction_id": d.get("transaction_id"),
        })

    return {
        "as_of": now.isoformat(),
        "period": period,
        "fee_collector_did": fee_collector_did,
        "balance": balance,
        "teg_error": teg_error,
        "totals_in_window": {
            "inflow": str(total_inflow_window),
            "fee_count": len(fees_in),
            "fee_truncated": len(all_fees) >= 200,
        },
        "sparkline": sparkline,
        "recent": recent,
    }


@router.get("/reward-funding/policy", summary="Read the payout funding waterfall policy (P3, 2026-05-08)")
async def get_reward_funding_policy(
    _admin: models.Developer = Security(security.require_admin_flag("admin_treasury")),
) -> Dict[str, Any]:
    """
    Phase 3 — proxy to the TEG's funding-policy read.

    Returns the per-reason waterfall config + valid sources + default. Used by the AdminTreasury
    "Funding Policy" tab to render the editor.
    """
    teg_api_base_url = os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080")
    teg_admin_api_key = os.getenv("TEG_ADMIN_API_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
            r = await client.get(
                f"{teg_api_base_url}/api/v1/admin/reward-funding/policy",
                headers={"Authorization": f"Bearer {teg_admin_api_key}"},
            )
            if r.status_code == 200:
                return r.json()
            try:
                detail = r.json().get("detail", r.text[:200])
            except Exception:
                detail = r.text[:200]
            raise HTTPException(status_code=r.status_code, detail=detail)
    except HTTPException:
        raise
    except httpx.RequestError as e:
        logger.error(f"reward_funding policy GET: TEG unreachable: {e}")
        raise HTTPException(status_code=503, detail="TEG service unavailable")


@router.put("/reward-funding/policy", summary="Update the payout funding waterfall policy (P3, 2026-05-08)")
async def put_reward_funding_policy(
    request: Dict[str, Any] = Body(...),
    _admin: models.Developer = Security(security.require_admin_flag("admin_treasury")),
) -> Dict[str, Any]:
    """
    Phase 3 — proxy to the TEG's funding-policy write.

    Body: `{policy: {<reason>: ["fee_collector", "treasury"], ...}}` — must
    include "default". Validation happens TEG-side.
    """
    teg_api_base_url = os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080")
    teg_admin_api_key = os.getenv("TEG_ADMIN_API_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
            r = await client.put(
                f"{teg_api_base_url}/api/v1/admin/reward-funding/policy",
                json=request,
                headers={"Authorization": f"Bearer {teg_admin_api_key}"},
            )
            if r.status_code == 200:
                return r.json()
            try:
                detail = r.json().get("detail", r.text[:200])
            except Exception:
                detail = r.text[:200]
            raise HTTPException(status_code=r.status_code, detail=detail)
    except HTTPException:
        raise
    except httpx.RequestError as e:
        logger.error(f"reward_funding policy PUT: TEG unreachable: {e}")
        raise HTTPException(status_code=503, detail="TEG service unavailable")


@router.post("/fee-collector/distribute", summary="Pay units from the fee account to an agent (admin)")
async def distribute_from_fee_collector(
    request: Dict[str, Any] = Body(...),
    _admin: models.Developer = Security(security.require_admin_flag("admin_treasury")),
) -> Dict[str, Any]:
    """Pay units from this frame's fee account to an agent, by hand: `target_agent_did`, `amount`, `reason` (by
    default `manual_payout`) and an optional `reference_id`. The TEG moves them in one transfer, without a fee. Needs
    an admin token with the `admin_treasury` flag.

    \f
    Phase 1 — admin manual distribute from fee_collector → target agent.

    Body:
      {
        "target_agent_did": "did:theprotocol:...",
        "amount": "10.5",
        "reason": "manual_payout",     // staking_reward / dispute_compensation / etc.
        "reference_id": "optional"
      }

    Proxies to TEG `/admin/fee-collector/distribute`. The TEG executes the
    atomic transfer + emits TokensTransferred. Phase 2's RewardFundingService
    will use this same TEG endpoint internally for the fee-pool waterfall step.
    """
    target = request.get("target_agent_did") or request.get("target_agent_id")
    amount = request.get("amount")
    reason = request.get("reason", "manual_payout")
    reference_id = request.get("reference_id")

    if not target:
        raise HTTPException(status_code=400, detail="Missing target_agent_did")
    if amount is None:
        raise HTTPException(status_code=400, detail="Missing amount")

    teg_api_base_url = os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080")
    teg_admin_api_key = os.getenv("TEG_ADMIN_API_KEY", "")

    try:
        async with httpx.AsyncClient(timeout=15.0, verify=get_httpx_verify()) as client:
            r = await client.post(
                f"{teg_api_base_url}/api/v1/admin/fee-collector/distribute",
                json={
                    "target_agent_id": target,
                    "amount": str(amount),
                    "reason": reason,
                    "reference_id": reference_id,
                },
                headers={"Authorization": f"Bearer {teg_admin_api_key}"},
            )
            if r.status_code == 200:
                return r.json()
            try:
                detail = r.json().get("detail", r.text[:200])
            except Exception:
                detail = r.text[:200]
            raise HTTPException(status_code=r.status_code, detail=detail)
    except HTTPException:
        raise
    except httpx.RequestError as e:
        logger.error(f"fee_collector distribute: TEG unreachable: {e}")
        raise HTTPException(status_code=503, detail="TEG service unavailable")
    except Exception as e:
        logger.error(f"fee_collector distribute: unexpected: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Distribute failed: {e}")


@router.get("/treasury/aggregate", summary="Treasury and fee figures over a period (admin)")
async def get_treasury_aggregate(
    period: str = "7d",
    # §FEDSUITE 2026-09-04: was `frame: str = "A"`. _local_frame() became
    # frame-aware in §2026-06-03, but this default did not follow it. On any
    # registry whose local frame is NOT A, "A" is resolved as a FOREIGN frame;
    # _resolve_event_store finds no EVENT_STORE_A_URL and deliberately returns
    # ("","") so the caller yields an EMPTY result. Net effect on frame-b /
    # frame-c: supply_audit {} labelled frame "A" while the local EventStore is
    # perfectly healthy — it reads as "no data" rather than "wrong frame asked".
    # The MCP tool getTreasuryAggregate takes no frame argument at all, so every
    # MCP admin caller on B/C hit this. "local" is the sentinel this endpoint's
    # own docstring says the FE sends precisely so no deployment guesses its
    # letter. On frame A this is byte-identical (_is_local_frame("local") is
    # True there too); on B/C it returns that frame's OWN data.
    frame: str = "local",
    _admin: models.Developer = Security(security.require_admin_flag("admin_treasury")),
) -> Dict[str, Any]:
    """
    This frame's treasury and fee figures over `period` (`24h`, `7d` by default, `30d` or `all`): the supply audit,
    the treasury's live balance from the TEG, the units issued and the fees collected in the window (as buckets for a
    chart), the agents that paid the most fees, and the latest issuances. `frame` is `local` (the default) or this
    registry's own name (any other answers 404). Needs an admin token with the `admin_treasury` flag.

    \f
    Build #7 (2026-05-07): pre-aggregated treasury & fee metrics for AdminTreasury view.

    Pulls from:
      - EventStore /projections/supply-audit       (invariant + counts)
      - EventStore /events?event_type=TokensIssued (mints in window)
      - EventStore /events?event_type=TransactionFeeCollected (fees in window)
      - TEG /governance/admin/treasury/balance     (live treasury balance, Frame A only)

    `period` ∈ { "24h", "7d", "30d", "all" }
    `frame`  "local" (the default) or this registry's own name; any other value is refused (404):
    each frame serves its own ledger (§FEFRAME W4 residue, V0521).
    """
    from collections import defaultdict
    from decimal import Decimal, InvalidOperation

    now = datetime.now(timezone.utc)
    period = (period or "7d").lower()
    if period == "24h":
        cutoff = now - timedelta(hours=24)
        bucket_count, bucket_size = 24, timedelta(hours=1)
    elif period == "7d":
        cutoff = now - timedelta(days=7)
        bucket_count, bucket_size = 7, timedelta(days=1)
    elif period == "30d":
        cutoff = now - timedelta(days=30)
        bucket_count, bucket_size = 30, timedelta(days=1)
    elif period == "all":
        cutoff = None
        bucket_count, bucket_size = 30, timedelta(days=1)
    else:
        raise HTTPException(status_code=400, detail=f"Invalid period: {period}")

    event_store_url, internal_key = _resolve_event_store(frame)

    def _parse_ts(s: str) -> Optional[datetime]:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def _to_decimal(v: Any) -> Decimal:
        try:
            return Decimal(str(v or "0"))
        except (InvalidOperation, ValueError):
            return Decimal("0")

    # 1. Supply audit
    supply: Dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
            r = await client.get(
                f"{event_store_url}/api/v1/projections/supply-audit",
                headers={"X-Internal-Key": internal_key},
            )
            if r.status_code == 200:
                supply = r.json()
    except Exception as e:
        logger.warning(f"Treasury aggregate (frame={frame}): supply-audit fetch failed: {e}")

    # 2. Mints (TokensIssued)
    MINT_LIMIT = 500
    all_mints: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=get_httpx_verify()) as client:
            for _name in ledger_names.live_names("TokensIssued"):   # W4: the mints under either name
                r = await client.get(
                    f"{event_store_url}/api/v1/events/",
                    params={"event_type": _name, "limit": MINT_LIMIT},
                    headers={"X-Internal-Key": internal_key},
                )
                if r.status_code == 200:
                    _got = r.json() or []
                    if isinstance(_got, list):
                        all_mints.extend(_got)
    except Exception as e:
        logger.warning(f"Treasury aggregate (frame={frame}): TokensIssued fetch failed: {e}")

    # 3. Fees (TransactionFeeCollected)
    FEE_LIMIT = 1000
    all_fees: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=get_httpx_verify()) as client:
            r = await client.get(
                f"{event_store_url}/api/v1/events/",
                params={"event_type": "TransactionFeeCollected", "limit": FEE_LIMIT},
                headers={"X-Internal-Key": internal_key},
            )
            if r.status_code == 200:
                all_fees = r.json() or []
    except Exception as e:
        logger.warning(f"Treasury aggregate (frame={frame}): TransactionFeeCollected fetch failed: {e}")

    # Filter to window
    mints_in: List[Dict[str, Any]] = []
    for m in all_mints:
        ts = _parse_ts(m.get("timestamp"))
        if ts is None:
            continue
        if cutoff is None or ts >= cutoff:
            mints_in.append(m)
    fees_in: List[Dict[str, Any]] = []
    for f in all_fees:
        ts = _parse_ts(f.get("timestamp"))
        if ts is None:
            continue
        if cutoff is None or ts >= cutoff:
            fees_in.append(f)

    # Aggregations
    total_minted = sum((_to_decimal(m.get("data", {}).get("amount")) for m in mints_in), Decimal("0"))
    total_fees = sum((_to_decimal(f.get("data", {}).get("fee_amount")) for f in fees_in), Decimal("0"))

    mints_by_reason: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for m in mints_in:
        reason = (m.get("data") or {}).get("reason") or "unknown"
        mints_by_reason[reason] += _to_decimal(m.get("data", {}).get("amount"))

    # TransactionFeeCollected events come in TWO shapes — fee payer key fallback chain:
    #   1. data.agent_did       (intra-registry transfers)
    #   2. data.from            (cross-registry / cross-frame transfers)
    #   3. event.aggregate_id   (final fallback — aggregate is the payer for shape 2)
    fees_by_agent: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    fee_count_by_agent: Dict[str, int] = defaultdict(int)
    for f in fees_in:
        d = f.get("data") or {}
        agent = (
            d.get("agent_did")
            or d.get("from")
            or f.get("aggregate_id")
            or "unknown"
        )
        fees_by_agent[agent] += _to_decimal(d.get("fee_amount"))
        fee_count_by_agent[agent] += 1

    top_fee_payers = sorted(
        (
            {
                "agent_did": did,
                "total_fees": str(amt),
                "tx_count": fee_count_by_agent[did],
            }
            for did, amt in fees_by_agent.items()
        ),
        key=lambda x: Decimal(x["total_fees"]),
        reverse=True,
    )[:10]

    # Recent mints — top 10 by timestamp DESC
    sorted_mints = sorted(mints_in, key=lambda x: x.get("timestamp") or "", reverse=True)
    recent_mints = [
        {
            "id": m.get("id"),
            "timestamp": m.get("timestamp"),
            "amount": (m.get("data") or {}).get("amount", "0"),
            "reason": (m.get("data") or {}).get("reason"),
            "agent_did": (m.get("data") or {}).get("agent_did"),
            "transaction_id": (m.get("data") or {}).get("transaction_id"),
        }
        for m in sorted_mints[:10]
    ]

    # Sparkline buckets — minted + fees per bucket
    if cutoff is None:
        # all-time: pin to earliest event we have, capped at 30 days back
        all_window = mints_in + fees_in
        if all_window:
            earliest = min(
                (_parse_ts(e.get("timestamp")) or now for e in all_window),
                default=now - timedelta(days=30),
            )
            cutoff_for_bucket = max(earliest, now - timedelta(days=30))
        else:
            cutoff_for_bucket = now - timedelta(days=30)
    else:
        cutoff_for_bucket = cutoff

    sparkline: List[Dict[str, Any]] = []
    for i in range(bucket_count):
        b_start = cutoff_for_bucket + bucket_size * i
        b_end = cutoff_for_bucket + bucket_size * (i + 1)
        m_sum = Decimal("0")
        f_sum = Decimal("0")
        for m in mints_in:
            ts = _parse_ts(m.get("timestamp"))
            if ts and b_start <= ts < b_end:
                m_sum += _to_decimal(m.get("data", {}).get("amount"))
        for f in fees_in:
            ts = _parse_ts(f.get("timestamp"))
            if ts and b_start <= ts < b_end:
                f_sum += _to_decimal(f.get("data", {}).get("fee_amount"))
        sparkline.append(
            {
                "t": b_start.isoformat(),
                "minted": str(m_sum),
                "fees": str(f_sum),
            }
        )

    # 6. Live treasury balance, this registry's own. A frame's TEG admin key is sovereign (never shared across
    # frames), so a registry reads only its own treasury; a request naming another frame was already refused when
    # the store was resolved above (§FEFRAME W4 residue, V0521: the letter-gated branch that labelled it is gone).
    treasury_balance: Optional[str] = None
    treasury_did: Optional[str] = None
    treasury_error: Optional[str] = None
    teg_api_base_url = os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080")
    teg_admin_api_key = os.getenv("TEG_ADMIN_API_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
            tb = await client.get(
                f"{teg_api_base_url}/api/v1/governance/admin/treasury/balance",
                headers={"Authorization": f"Bearer {teg_admin_api_key}"},
            )
            if tb.status_code == 200:
                tbd = tb.json()
                treasury_balance = str(tbd.get("balance", "0"))
                treasury_did = tbd.get("treasury_did")
            else:
                treasury_error = f"TEG returned {tb.status_code}"
    except Exception as e:
        treasury_error = str(e)
        logger.warning(f"Treasury aggregate: TEG balance fetch failed: {e}")

    return {
        "frame": _reported_frame(frame),
        "period": period,
        "as_of": now.isoformat(),
        "supply_audit": supply,
        "treasury": {
            "balance": treasury_balance,
            "treasury_did": treasury_did,
            "error": treasury_error,
        },
        "totals_in_window": {
            "minted": str(total_minted),
            "fees_collected": str(total_fees),
            "mint_count": len(mints_in),
            "fee_count": len(fees_in),
            "mint_truncated": len(all_mints) >= MINT_LIMIT,
            "fee_truncated": len(all_fees) >= FEE_LIMIT,
        },
        "mints_by_reason": {r: str(amt) for r, amt in mints_by_reason.items()},
        "top_fee_payers": top_fee_payers,
        "recent_mints": recent_mints,
        "sparkline": sparkline,
    }


def zkp_phase_state() -> dict:
    """The five ZKP phase switches as the attestation router and its workers read them: unset
    means on. Read with "false" as the default, a registry that never set them was shown as
    running none while every phase ran; a sixth phase has no switch."""
    return {
        f"phase_{i}": os.getenv(f"ZKP_PHASE_{i}_ENABLED", "true").lower() == "true"
        for i in range(1, 6)
    }


@router.get("/attestations/analytics", summary="Attestation analytics (Build #14)")
async def get_attestations_analytics(
    period: str = "30d",
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """
    Build #14 (2026-05-08): ZKP attestation analytics — circuit distribution,
    status breakdown (verified/expired/revoked), submission cadence, recent
    activity. Surfaces the empty state gracefully (ZKP_PHASE_*=false in beta).

    Pulls from: attestations table.
    """
    from sqlalchemy import func as sa_func, and_

    period = (period or "30d").lower()
    now = datetime.now(timezone.utc)
    if period == "24h":
        cutoff = now - timedelta(hours=24)
    elif period == "7d":
        cutoff = now - timedelta(days=7)
    elif period == "30d":
        cutoff = now - timedelta(days=30)
    elif period == "all":
        cutoff = None
    else:
        raise HTTPException(status_code=400, detail=f"Invalid period: {period}")

    # ── Total counts (current state, not period-bound) ──
    # Use lazy attribute access on Attestation model — only the columns
    # available across deployments. expires_at + revoked_at are always
    # present per migration history.
    Att = models.Attestation

    total_q = await db.execute(select(sa_func.count()).select_from(Att))
    total = int(total_q.scalar() or 0)

    verified_q = await db.execute(
        select(sa_func.count()).select_from(Att).where(Att.verified.is_(True))
    )
    verified_count = int(verified_q.scalar() or 0)

    failed_q = await db.execute(
        select(sa_func.count()).select_from(Att).where(Att.verified.is_(False))
    )
    failed_count = int(failed_q.scalar() or 0)

    revoked_q = await db.execute(
        select(sa_func.count()).select_from(Att).where(Att.revoked_at.is_not(None))
    )
    revoked_count = int(revoked_q.scalar() or 0)

    # Expired: expires_at < now AND not revoked
    expired_q = await db.execute(
        select(sa_func.count()).select_from(Att).where(
            Att.expires_at.is_not(None),
            Att.expires_at < now,
            Att.revoked_at.is_(None),
        )
    )
    expired_count = int(expired_q.scalar() or 0)

    # Active: verified AND not revoked AND (no expiry OR expiry in future)
    active_q = await db.execute(
        select(sa_func.count()).select_from(Att).where(
            Att.verified.is_(True),
            Att.revoked_at.is_(None),
            (Att.expires_at.is_(None)) | (Att.expires_at > now),
        )
    )
    active_count = int(active_q.scalar() or 0)

    # Expiring in next 24h
    soon = now + timedelta(hours=24)
    expiring_q = await db.execute(
        select(sa_func.count()).select_from(Att).where(
            Att.verified.is_(True),
            Att.revoked_at.is_(None),
            Att.expires_at.is_not(None),
            Att.expires_at >= now,
            Att.expires_at < soon,
        )
    )
    expiring_count = int(expiring_q.scalar() or 0)

    # ── Distribution by circuit ──
    circuit_q = await db.execute(
        select(Att.circuit_id, Att.circuit_version, sa_func.count())
        .group_by(Att.circuit_id, Att.circuit_version)
        .order_by(sa_func.count().desc())
    )
    by_circuit = [
        {
            "circuit_id": cid,
            "circuit_version": cver,
            "count": int(c),
        }
        for cid, cver, c in circuit_q.all()
    ]

    # ── Distribution by agent (top 10 most-attested) ──
    agent_q = await db.execute(
        select(Att.agent_did, sa_func.count())
        .group_by(Att.agent_did)
        .order_by(sa_func.count().desc())
        .limit(10)
    )
    top_agents = [
        {"agent_did": did, "count": int(c)}
        for did, c in agent_q.all()
    ]

    # ── Recent attestations (last 50, period-filtered) ──
    period_filter = []
    if cutoff is not None:
        period_filter.append(Att.submitted_at >= cutoff)
    recent_q = await db.execute(
        select(Att)
        .where(*period_filter)
        .order_by(Att.submitted_at.desc())
        .limit(50)
    )
    recent = []
    for a in recent_q.scalars().all():
        is_active = (
            a.verified
            and a.revoked_at is None
            and (a.expires_at is None or a.expires_at > now)
        )
        recent.append(
            {
                "id": str(a.id),
                "agent_did": a.agent_did,
                "circuit_id": a.circuit_id,
                "circuit_version": a.circuit_version,
                "verified": a.verified,
                "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
                "verified_at": a.verified_at.isoformat() if a.verified_at else None,
                "expires_at": a.expires_at.isoformat() if a.expires_at else None,
                "revoked_at": a.revoked_at.isoformat() if a.revoked_at else None,
                "revoked_by": a.revoked_by,
                "revoked_reason": a.revoked_reason,
                "failure_reason": a.failure_reason,
                "is_active": is_active,
                "policy_parameters_hash": a.policy_parameters_hash,
            }
        )

    # ── Submission cadence — count per day across period ──
    cadence: List[Dict[str, Any]] = []
    if cutoff is not None and total > 0:
        # Generate buckets per day across period
        bucket_count = 30 if period in ("30d", "all") else (7 if period == "7d" else 24)
        bucket_size = (
            timedelta(days=1) if period in ("7d", "30d", "all") else timedelta(hours=1)
        )
        for i in range(bucket_count):
            b_start = cutoff + bucket_size * i
            b_end = cutoff + bucket_size * (i + 1)
            bq = await db.execute(
                select(sa_func.count()).select_from(Att).where(
                    Att.submitted_at >= b_start,
                    Att.submitted_at < b_end,
                )
            )
            cadence.append(
                {
                    "t": b_start.isoformat(),
                    "submitted": int(bq.scalar() or 0),
                }
            )

    zkp_phases = zkp_phase_state()

    return {
        "as_of": now.isoformat(),
        "period": period,
        "stats": {
            "total": total,
            "verified": verified_count,
            "failed": failed_count,
            "revoked": revoked_count,
            "expired": expired_count,
            "active": active_count,
            "expiring_24h": expiring_count,
            # The zero-knowledge circuits this registry verifies (v2.0.0; the retired v1.0.0
            # only while ZKP_ACCEPT_V1_CIRCUITS is set). proof_of_reputation is input
            # validation, not a proof, so it is not counted.
            "circuits_available": sum(
                1 for c in _zkp.get_supported_circuits() if c not in _zkp._OPTION_B_CIRCUITS
            ),
        },
        "by_circuit": by_circuit,
        "top_agents": top_agents,
        "recent": recent,
        "cadence": cadence,
        "zkp_phases": zkp_phases,
    }


# NOTE (2026-05-08 polish): The previous /admin/peers/health endpoint here
# was REMOVED — it duplicated /admin/federation/topology-overview which
# already exposes all the operational fields (bayesian_discount, drift_flags,
# license_status, BFS reachability, SPIRE bundle state) AND the canonical
# tier-bucketed shape used by Federation.vue. AdminPeers.vue now consumes
# the canonical endpoint directly. See audit doc §48.


@router.get("/bridge/aggregate", summary="Cross-Frame Bridge Health (Build #9)")
async def get_bridge_aggregate(
    period: str = "7d",
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """
    Build #9 (2026-05-07): cross-frame bridge health snapshot.

    Two distinct cross-frame transfer paths in the system:
      1. **Async cross-frame** (cross_frame_transfers + cross_frame_transfers_inbound)
         — high-volume path used by canary + production cross-frame economy.
         Status: locked → settled | refunded
      2. **Sync SF-3 bridge** (bridge_transactions) — legacy escrow + issuance flow.
         Status: `INITIATED` → `LOCKED` → `MINTED` → `COMPLETED` | `FAILED` | `EXPIRED`

    Returns aggregate stats for both, plus recent transfer feeds.
    """
    from sqlalchemy import func as sa_func

    period = (period or "7d").lower()
    now = datetime.now(timezone.utc)
    if period == "24h":
        cutoff = now - timedelta(hours=24)
    elif period == "7d":
        cutoff = now - timedelta(days=7)
    elif period == "30d":
        cutoff = now - timedelta(days=30)
    elif period == "all":
        cutoff = None
    else:
        raise HTTPException(status_code=400, detail=f"Invalid period: {period}")

    # ── Async cross-frame transfers (sender side) ────────────────
    async_filter = []
    if cutoff is not None:
        async_filter.append(models.CrossFrameTransfer.created_at >= cutoff)

    async_status_q = await db.execute(
        select(models.CrossFrameTransfer.status, sa_func.count())
        .where(*async_filter)
        .group_by(models.CrossFrameTransfer.status)
    )
    async_status: Dict[str, int] = {s: int(c) for s, c in async_status_q.all()}

    async_total = sum(async_status.values())
    async_settled = async_status.get("settled", 0)
    async_refunded = async_status.get("refunded", 0)
    async_locked = async_status.get("locked", 0)

    # Recent async transfers — limit 50 most-recent
    recent_async_q = await db.execute(
        select(models.CrossFrameTransfer)
        .where(*async_filter)
        .order_by(models.CrossFrameTransfer.created_at.desc())
        .limit(50)
    )
    recent_async = []
    for t in recent_async_q.scalars().all():
        latency_ms = None
        if t.settled_at and t.created_at:
            latency_ms = int((t.settled_at - t.created_at).total_seconds() * 1000)
        elif t.refunded_at and t.created_at:
            latency_ms = int((t.refunded_at - t.created_at).total_seconds() * 1000)
        recent_async.append(
            {
                "id": t.id,
                "sender_did": t.sender_did,
                "receiver_did": t.receiver_did,
                "target_frame": t.target_frame,
                "amount": str(t.amount),
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "timeout_at": t.timeout_at.isoformat() if t.timeout_at else None,
                "settled_at": t.settled_at.isoformat() if t.settled_at else None,
                "refunded_at": t.refunded_at.isoformat() if t.refunded_at else None,
                "latency_ms": latency_ms,
            }
        )

    # Settled latency (avg / median) — sample from recent_async
    settled_latencies = sorted([t["latency_ms"] for t in recent_async if t["status"] == "settled" and t["latency_ms"] is not None])
    avg_settled_ms = (sum(settled_latencies) // len(settled_latencies)) if settled_latencies else None
    p50_settled_ms = settled_latencies[len(settled_latencies) // 2] if settled_latencies else None
    p95_settled_ms = settled_latencies[int(len(settled_latencies) * 0.95)] if len(settled_latencies) >= 5 else None

    # ── Async inbound (receiver side) ────────────────────────────
    inbound_filter = []
    if cutoff is not None:
        inbound_filter.append(models.CrossFrameTransferInbound.credited_at >= cutoff)
    inbound_status_q = await db.execute(
        select(models.CrossFrameTransferInbound.status, sa_func.count())
        .where(*inbound_filter)
        .group_by(models.CrossFrameTransferInbound.status)
    )
    inbound_status: Dict[str, int] = {s: int(c) for s, c in inbound_status_q.all()}
    inbound_total = sum(inbound_status.values())

    # ── SF-3 sync bridge transactions ────────────────────────────
    sync_filter = []
    if cutoff is not None:
        sync_filter.append(models.BridgeTransaction.created_at >= cutoff)
    sync_status_q = await db.execute(
        select(models.BridgeTransaction.status, sa_func.count())
        .where(*sync_filter)
        .group_by(models.BridgeTransaction.status)
    )
    sync_status: Dict[str, int] = {s: int(c) for s, c in sync_status_q.all()}
    sync_total = sum(sync_status.values())

    recent_sync_q = await db.execute(
        select(models.BridgeTransaction)
        .where(*sync_filter)
        .order_by(models.BridgeTransaction.created_at.desc())
        .limit(20)
    )
    recent_sync = []
    for t in recent_sync_q.scalars().all():
        latency_ms = None
        if t.completed_at and t.created_at:
            latency_ms = int((t.completed_at - t.created_at).total_seconds() * 1000)
        recent_sync.append(
            {
                "id": t.id,
                "source_frame_id": t.source_frame_id,
                "target_frame_id": t.target_frame_id,
                "source_agent_did": t.source_agent_did,
                "target_agent_did": t.target_agent_did,
                "amount": str(t.amount),
                "status": t.status,
                "direction": t.direction,
                "lock_tx_id": t.lock_tx_id,
                "mint_tx_id": t.mint_tx_id,
                "unlock_tx_id": t.unlock_tx_id,
                "burn_tx_id": t.burn_tx_id,
                "expires_at": t.expires_at.isoformat() if t.expires_at else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "error_message": t.error_message,
                "latency_ms": latency_ms,
            }
        )

    # ── Outstanding (in-flight) — locked but not yet settled/refunded ─
    inflight_q = await db.execute(
        select(sa_func.count()).select_from(models.CrossFrameTransfer).where(
            models.CrossFrameTransfer.status == "locked"
        )
    )
    inflight_count = int(inflight_q.scalar() or 0)

    # Expiring soon — locked AND timeout_at within 5 minutes
    soon = now + timedelta(minutes=5)
    expiring_q = await db.execute(
        select(sa_func.count()).select_from(models.CrossFrameTransfer).where(
            models.CrossFrameTransfer.status == "locked",
            models.CrossFrameTransfer.timeout_at < soon,
        )
    )
    expiring_count = int(expiring_q.scalar() or 0)

    # ── Compute settle/refund rates ──
    async_resolved = async_settled + async_refunded
    settle_rate_pct = (async_settled / async_resolved * 100.0) if async_resolved > 0 else None
    refund_rate_pct = (async_refunded / async_resolved * 100.0) if async_resolved > 0 else None

    return {
        "period": period,
        "as_of": now.isoformat(),
        "async": {
            "status_counts": async_status,
            "total": async_total,
            "settled": async_settled,
            "refunded": async_refunded,
            "locked": async_locked,
            "settle_rate_pct": round(settle_rate_pct, 2) if settle_rate_pct is not None else None,
            "refund_rate_pct": round(refund_rate_pct, 2) if refund_rate_pct is not None else None,
            "avg_settled_ms": avg_settled_ms,
            "p50_settled_ms": p50_settled_ms,
            "p95_settled_ms": p95_settled_ms,
            "inflight_locked": inflight_count,
            "expiring_5min": expiring_count,
        },
        "inbound": {
            "status_counts": inbound_status,
            "total": inbound_total,
        },
        "sync_sf3": {
            "status_counts": sync_status,
            "total": sync_total,
        },
        "recent_async": recent_async,
        "recent_sync": recent_sync,
    }


@router.get("/webhooks/aggregate", summary="Webhook Health (Build #8, cluster-wide)")
async def get_webhooks_aggregate(
    period: str = "24h",
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """
    Build #8 (2026-05-07): cluster-wide webhook health snapshot.

    Returns aggregate stats + top-failing webhooks (with developer info).
    Period applies to the delivery window only — webhook counts are always
    current. Source: developer_webhooks + webhook_deliveries tables.
    """
    from sqlalchemy import and_, func as sa_func
    from sqlalchemy.orm import selectinload

    period = (period or "24h").lower()
    now = datetime.now(timezone.utc)
    if period == "24h":
        cutoff = now - timedelta(hours=24)
    elif period == "7d":
        cutoff = now - timedelta(days=7)
    elif period == "30d":
        cutoff = now - timedelta(days=30)
    elif period == "all":
        cutoff = None
    else:
        raise HTTPException(status_code=400, detail=f"Invalid period: {period}")

    # 1. Webhook counts (cluster-wide, current state)
    total_q = await db.execute(select(sa_func.count()).select_from(models.DeveloperWebhook))
    total_webhooks = int(total_q.scalar() or 0)

    active_q = await db.execute(
        select(sa_func.count()).select_from(models.DeveloperWebhook).where(
            models.DeveloperWebhook.is_active.is_(True)
        )
    )
    active_webhooks = int(active_q.scalar() or 0)

    devs_with_q = await db.execute(
        select(sa_func.count(sa_func.distinct(models.DeveloperWebhook.developer_id)))
    )
    developers_with_webhooks = int(devs_with_q.scalar() or 0)

    # 2. Delivery aggregates over the window
    delivery_filter = []
    if cutoff is not None:
        delivery_filter.append(models.WebhookDelivery.delivered_at >= cutoff)

    total_deliv_q = await db.execute(
        select(sa_func.count()).select_from(models.WebhookDelivery).where(*delivery_filter)
    )
    total_deliveries = int(total_deliv_q.scalar() or 0)

    # §DOCSFIX D6-786: the outcomes are the one rule the delivery lists read; success + failed + pending = the window's
    # total (a 3xx counted in none of them while "failed" read only 4xx/5xx)
    from agentvault_registry.services.webhook_service import delivery_outcome_clause

    success_q = await db.execute(
        select(sa_func.count()).select_from(models.WebhookDelivery).where(
            *delivery_filter, delivery_outcome_clause("success"),
        )
    )
    success_deliveries = int(success_q.scalar() or 0)

    failed_q = await db.execute(
        select(sa_func.count()).select_from(models.WebhookDelivery).where(
            *delivery_filter, delivery_outcome_clause("failed"),
        )
    )
    failed_deliveries = int(failed_q.scalar() or 0)

    pending_q = await db.execute(
        select(sa_func.count()).select_from(models.WebhookDelivery).where(
            *delivery_filter, delivery_outcome_clause("pending"),
        )
    )
    pending_deliveries = int(pending_q.scalar() or 0)

    retried_q = await db.execute(
        select(sa_func.count()).select_from(models.WebhookDelivery).where(
            *delivery_filter,
            models.WebhookDelivery.retry_count > 0,
        )
    )
    retried_deliveries = int(retried_q.scalar() or 0)

    # 3. Top event types in window
    top_events_q = await db.execute(
        select(
            models.WebhookDelivery.event_type,
            sa_func.count().label("cnt"),
        )
        .where(*delivery_filter)
        .group_by(models.WebhookDelivery.event_type)
        .order_by(sa_func.count().desc())
        .limit(10)
    )
    top_event_types = [{"event_type": e, "count": int(c)} for e, c in top_events_q.all()]

    # 4. Top failing webhooks — sorted by failure_count DESC, then last_triggered_at
    top_fail_q = await db.execute(
        select(models.DeveloperWebhook)
        .options(selectinload(models.DeveloperWebhook.developer))
        .where(models.DeveloperWebhook.failure_count > 0)
        .order_by(models.DeveloperWebhook.failure_count.desc())
        .limit(10)
    )
    top_failing_webhooks = []
    for wh in top_fail_q.scalars().all():
        dev = wh.developer
        top_failing_webhooks.append(
            {
                "id": wh.id,
                "url": wh.url,
                "is_active": wh.is_active,
                "failure_count": wh.failure_count,
                "events": list(wh.events or []),
                "last_triggered_at": wh.last_triggered_at.isoformat() if wh.last_triggered_at else None,
                "developer_id": wh.developer_id,
                "developer_email": getattr(dev, "email", None) if dev else None,
                "developer_name": getattr(dev, "name", None) if dev else None,
            }
        )

    # 5. Success rate
    deliv_with_status = success_deliveries + failed_deliveries
    success_rate = (success_deliveries / deliv_with_status * 100.0) if deliv_with_status > 0 else None

    return {
        "period": period,
        "as_of": now.isoformat(),
        "webhooks": {
            "total": total_webhooks,
            "active": active_webhooks,
            "inactive": total_webhooks - active_webhooks,
            "developers_with_webhooks": developers_with_webhooks,
        },
        "deliveries_in_window": {
            "total": total_deliveries,
            "success": success_deliveries,
            "failed": failed_deliveries,
            "pending": pending_deliveries,
            "retried": retried_deliveries,
            "success_rate_pct": round(success_rate, 2) if success_rate is not None else None,
        },
        "top_event_types": top_event_types,
        "top_failing_webhooks": top_failing_webhooks,
    }


@router.get("/webhooks/recent-deliveries", summary="Recent webhook deliveries (Build #8, cluster-wide)")
async def get_webhooks_recent_deliveries(
    limit: int = 100,
    status_filter: Optional[str] = None,
    event_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """
    Build #8 (2026-05-07): cluster-wide recent webhook deliveries feed.

    Pulls from webhook_deliveries with optional status/event_type filter.
    Joins to webhook + developer for context (URL, developer email).
    Default order: most-recent first. success, failed and pending partition every row, by the rule a developer's own list
    reads (D6-786: a 3xx answer is a failed attempt).
    """
    from sqlalchemy.orm import selectinload
    from agentvault_registry.services.webhook_service import DELIVERY_OUTCOMES, delivery_outcome_clause

    limit = max(1, min(int(limit or 100), 500))
    query = select(models.WebhookDelivery).options(
        selectinload(models.WebhookDelivery.webhook).selectinload(
            models.DeveloperWebhook.developer
        )
    )

    sf = (status_filter or "").lower() or None
    if sf in DELIVERY_OUTCOMES:
        query = query.where(delivery_outcome_clause(sf))
    elif sf == "retried":
        query = query.where(models.WebhookDelivery.retry_count > 0)
    elif sf and sf != "all":
        raise HTTPException(status_code=400, detail=f"Invalid status: {status_filter}")

    if event_type:
        query = query.where(models.WebhookDelivery.event_type == event_type)

    query = query.order_by(models.WebhookDelivery.delivered_at.desc()).limit(limit)
    result = await db.execute(query)
    deliveries = result.scalars().all()

    items = []
    for d in deliveries:
        wh = d.webhook
        dev = wh.developer if wh else None
        items.append(
            {
                "id": d.id,
                "webhook_id": d.webhook_id,
                "webhook_url": getattr(wh, "url", None) if wh else None,
                "developer_id": getattr(wh, "developer_id", None) if wh else None,
                "developer_email": getattr(dev, "email", None) if dev else None,
                "event_type": d.event_type,
                "response_status": d.response_status,
                "response_body": (d.response_body[:500] if d.response_body else None),
                "retry_count": d.retry_count,
                "next_retry_at": d.next_retry_at.isoformat() if d.next_retry_at else None,
                "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
                "error_message": d.error_message,
            }
        )

    return {
        "count": len(items),
        "deliveries": items,
        "filter": {"status": sf, "event_type": event_type, "limit": limit},
    }


# ── Admin webhook bulk actions (#3, 2026-05-08) ──
# Cluster-wide watchtower (admin_platform) has read-only stats via
# /admin/webhooks/aggregate + /recent-deliveries above. These three POST
# endpoints let cluster admins act on ANY webhook (TEST / DISABLE / ENABLE),
# bypassing the developer-ownership check that the per-developer
# /api/v1/webhooks/{id}/* paths in routers/webhooks.py enforce. Owner-tier
# paths are unchanged — admins use these explicitly through the
# /admin/webhooks-cluster surface.


async def _get_any_webhook_admin(
    webhook_id: str, db: AsyncSession
) -> models.DeveloperWebhook:
    """Admin lookup — no developer-ownership filter."""
    result = await db.execute(
        select(models.DeveloperWebhook).where(
            models.DeveloperWebhook.id == webhook_id
        )
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return webhook


@router.post("/webhooks/{webhook_id}/test", summary="Admin: send test event to ANY webhook")
async def admin_test_webhook(
    webhook_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """
    Build #18 (#3, 2026-05-08): admin-tier test for any webhook.

    Mirrors POST /api/v1/webhooks/{id}/test (developer-tier, owner-only)
    but without the ownership check, so cluster admins can validate webhook
    delivery from the watchtower without impersonating the owning developer.
    Side effect: writes a webhook_delivery row + adjusts failure_count via
    WebhookService.deliver_webhook (same path the test owner-tier uses).
    """
    from agentvault_registry.services.webhook_service import WebhookService

    webhook = await _get_any_webhook_admin(webhook_id, db)
    service = WebhookService()
    async with service:
        delivery = await service.deliver_webhook(
            webhook=webhook,
            event_type="webhook.test",
            data={
                "message": "Admin-initiated test event from TheProtocol",
                "webhook_id": webhook_id,
                "initiated_by": "admin",
            },
            agent_did=None,
            db=db,
        )
    # §DOCSFIX D6-766 (2026-10-16): an admin act on another developer's webhook leaves an audit row
    from agentvault_registry.services.admin_audit import log_admin_action
    await log_admin_action(db, action="webhook.test", actor_id=str(_admin.id), target_type="webhook",
                           target_id=webhook_id, details={"owner_developer_id": webhook.developer_id,
                                                          "status_code": delivery.response_status,
                                                          "delivery_id": delivery.id})

    return {
        "success": bool(delivery.response_status and 200 <= delivery.response_status < 300),
        "status_code": delivery.response_status,
        "delivery_id": delivery.id,
        "developer_id": webhook.developer_id,
    }


@router.post("/webhooks/{webhook_id}/disable", summary="Admin: disable ANY webhook")
async def admin_disable_webhook(
    webhook_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """Admin disable — sets is_active=False on any webhook regardless of owner."""
    from agentvault_registry.services.admin_audit import log_admin_action  # §DOCSFIX D6-766: every act audited
    webhook = await _get_any_webhook_admin(webhook_id, db)
    if not webhook.is_active:
        await log_admin_action(db, action="webhook.disable", actor_id=str(_admin.id), target_type="webhook",
                               target_id=webhook.id, details={"owner_developer_id": webhook.developer_id,
                                                              "changed": False})
        return {"id": webhook.id, "is_active": False, "changed": False}
    webhook.is_active = False
    await db.commit()
    await db.refresh(webhook)
    await log_admin_action(db, action="webhook.disable", actor_id=str(_admin.id), target_type="webhook",
                           target_id=webhook.id, details={"owner_developer_id": webhook.developer_id,
                                                          "changed": True})
    logger.info(
        f"[Webhooks] Admin {_admin.id} disabled webhook {webhook.id} "
        f"(owner={webhook.developer_id})"
    )
    return {
        "id": webhook.id,
        "is_active": False,
        "changed": True,
        "developer_id": webhook.developer_id,
    }


@router.post("/webhooks/{webhook_id}/enable", summary="Admin: re-enable ANY webhook")
async def admin_enable_webhook(
    webhook_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """Admin enable — sets is_active=True + resets failure_count, mirrors the
    owner-tier behaviour (PUT /api/v1/webhooks/{id} with is_active=True)."""
    from agentvault_registry.services.admin_audit import log_admin_action  # §DOCSFIX D6-766: every act audited
    webhook = await _get_any_webhook_admin(webhook_id, db)
    already_active = webhook.is_active
    webhook.is_active = True
    webhook.failure_count = 0
    await db.commit()
    await db.refresh(webhook)
    await log_admin_action(db, action="webhook.enable", actor_id=str(_admin.id), target_type="webhook",
                           target_id=webhook.id, details={"owner_developer_id": webhook.developer_id,
                                                          "changed": not already_active})
    logger.info(
        f"[Webhooks] Admin {_admin.id} enabled webhook {webhook.id} "
        f"(owner={webhook.developer_id}, was_active={already_active})"
    )
    return {
        "id": webhook.id,
        "is_active": True,
        "changed": not already_active,
        "developer_id": webhook.developer_id,
    }


@router.get("/degradation-coverage", summary="Degradation signals the invariant/health checks cannot see")
async def get_degradation_coverage(
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform"))
) -> Dict[str, Any]:
    """The signals that were structurally invisible until 2026-07-26.

    Every other monitor here answers "is it broken": the supply invariant, /health, and the
    stuck-state SLOs. A five-hour DNS degradation moved NONE of them, and all three were right --
    money was safe, services were up, nothing was stuck. What was actually happening was 80-100
    WARNING-level log lines a minute, which nothing measured.

    This endpoint answers the other question: "is it *degrading*" -- working, but worse, and with
    retries. Reads VictoriaMetrics directly (same store vmalert evaluates against) so the numbers
    on screen are the numbers the alerts fire on, not a second implementation that can drift.
    """
    # ── §DEGREASON (2026-09-09) — A LITERAL DEFAULT SHAPED LIKE ONE FRAME ────────────────────
    # This defaulted to `http://victoriametrics:8428` with nothing setting it. That alias exists
    # ONLY on `agentvault_main_network`, so it resolves from Frame A and is a bare `gaierror`
    # from EU and ASIA — measured 2026-09-09. Every signal on the flagship's compliance page has
    # read "metric unreadable" since the day that page existed, and the panel could not say why:
    # DNS failure, 403, timeout and empty result all printed the same four words (§EMITDIAG).
    #
    # UNSET IS NOW ITS OWN STATE. "No metrics backend is configured for this frame" is a posture
    # a reader can act on; a hostname belonging to somebody else's network is not.
    vm_url = (os.getenv("VICTORIA_METRICS_URL", "") or "").strip()
    configured = bool(vm_url)

    # name -> (promql, alert that watches it, threshold shown to the operator)
    QUERIES = {
        "dns_failures_per_min": (
            'sum(rate(registry_log_records_total{category="dns_resolution"}[5m])) * 60',
            "DNSResolutionFailures", 10),
        "settlement_failures_per_min": (
            'sum(rate(registry_log_records_total{category="settlement"}[10m])) * 60',
            "SettlementFailureRate", 2),
        "peer_unresolved_30m": (
            'sum(increase(xframe_peer_unresolved_total[30m]))',
            "XFramePeerUnresolved", 0),
        "warning_rate_per_min": (
            'sum(rate(registry_log_records_total[5m])) * 60',
            # Must match prometheus_alerts.yml::LogWarningStorm. Measured healthy baseline
            # 2026-07-26: 130/min avg, 161/min peak — the first value (150) sat BELOW normal.
            "LogWarningStorm", 400),
    }

    async def _scalar(client, q: str):
        """(value, reason) — the reason is the whole point of this function's shape.

        A probe may report what it observed and what it could not distinguish, never why; so it
        returns the DISTINGUISHING fact (dns / http_<code> / timeout / transport) instead of one
        word that four different failures share.
        """
        try:
            r = await client.get(f"{vm_url}/api/v1/query", params={"query": q})
            if r.status_code != 200:
                return None, f"http_{r.status_code}"
            res = r.json().get("data", {}).get("result", [])
            # an EMPTY result set is a successful read of "nothing happened" — 0.0, readable.
            return (float(res[0]["value"][1]) if res else 0.0), None
        except httpx.ConnectError as e:
            # the EU/ASIA case: the hostname does not resolve on this frame's networks
            return None, ("dns" if "getaddrinfo" in str(e).lower() or "name or service" in str(e).lower()
                          else "connect")
        except httpx.TimeoutException:
            return None, "timeout"
        except Exception as e:  # noqa: BLE001
            return None, f"transport:{type(e).__name__}"

    signals: Dict[str, Any] = {}
    by_category: List[Dict[str, Any]] = []

    def _unreadable(reason: str) -> None:
        """Fill EVERY signal with the same named reason.

        ⚠ This exists because the old code left `signals` as `{}` when the outer client raised.
        The front end then read `readable: undefined !== false` -> TRUE, rendered a blank value,
        and `any_unreadable` was False over an empty dict — so a TOTAL failure rendered quieter
        than a partial one. An absent metric must never look like a healthy one, and an absent
        ANSWER must never look like an absent PROBLEM.
        """
        for k, (_q, alert, thresh) in QUERIES.items():
            signals[k] = {"value": None, "threshold": thresh, "alert": alert,
                          "breaching": False, "readable": False, "reason": reason}

    if not configured:
        _unreadable("not_configured")
    else:
        try:
            async with httpx.AsyncClient(timeout=8.0, verify=get_httpx_verify()) as client:
                for key, (q, alert, thresh) in QUERIES.items():
                    v, reason = await _scalar(client, q)
                    signals[key] = {
                        "value": None if v is None else round(v, 2),
                        "threshold": thresh,
                        "alert": alert,
                        # `None` (unreadable) must never render as healthy.
                        "breaching": (v is not None and v > thresh),
                        "readable": v is not None,
                        "reason": reason,
                    }
                # breakdown so an operator can see WHICH class is noisy without opening a shell
                try:
                    r = await client.get(f"{vm_url}/api/v1/query", params={
                        "query": 'sum by (category) (rate(registry_log_records_total[5m])) * 60'})
                    if r.status_code == 200:
                        for item in r.json().get("data", {}).get("result", []):
                            by_category.append({
                                "category": item.get("metric", {}).get("category", "unknown"),
                                "per_min": round(float(item["value"][1]), 2),
                            })
                        by_category.sort(key=lambda x: x["per_min"], reverse=True)
                except Exception:
                    pass
        except Exception as e:
            logger.error("[DegradationCoverage] metrics store unreachable at %s: %s", vm_url, e)
            if not signals:
                _unreadable(f"transport:{type(e).__name__}")

    return {
        "signals": signals,
        "by_category": by_category,
        "any_breaching": any(s.get("breaching") for s in signals.values()),
        "any_unreadable": any(not s.get("readable") for s in signals.values()),
        # the reader needs to tell "no backend here" from "backend refused us"
        "metrics_configured": configured,
        "unreadable_reason": next((s.get("reason") for s in signals.values()
                                   if not s.get("readable") and s.get("reason")), None),
        "note": ("These are degradation signals, not health. Delta, /health and the stuck-state "
                 "SLOs can all be green while these are red -- that combination is exactly what "
                 "the 2026-07-26 incident looked like."),
    }


@router.get("/alerts/active", summary="Firing and pending alerts (vmalert's state, read from VictoriaMetrics)")
async def get_active_alerts(
    include_sandbox: bool = False,
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """§ALERTS (2026-10-06): what the header strip and the Health Monitor show as alerts. Never answers "none" for a
    read that failed: `configured` / `readable` / `reason` say which; sandbox alerts are withheld unless asked for, and
    counted in `withheld.sandbox`."""
    return await read_active_alerts(include_sandbox=include_sandbox)


@router.get("/prometheus-metrics", summary="Prometheus Targets and Alerts")
async def get_prometheus_metrics(
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform"))
) -> Dict[str, Any]:
    """Fetch Prometheus scrape targets and the active alerts.

    §ALERTS (2026-10-06): the alerts are NOT Prometheus's. Prometheus only scrapes here (rule_files moved to vmalert on
    2026-04-30), so its /api/v1/alerts was empty by construction and this page said "No alerts firing" over 43 firing
    ones. They come from vmalert's state in VictoriaMetrics now (services/active_alerts.py), with `alerts_readable`
    saying whether that read was answered."""
    prometheus_url_ = prometheus_url()   # §FRAMEKIT P3.1: one reader (core/observability_urls.py)

    targets_payload: Dict[str, Any] = {"activeTargets": [], "droppedTargets": []}

    try:
        async with httpx.AsyncClient(timeout=8.0, verify=get_httpx_verify()) as client:
            t_resp = await client.get(f"{prometheus_url_}/api/v1/targets")
            if t_resp.status_code == 200:
                targets_payload = t_resp.json().get("data", targets_payload)
    except Exception as e:
        logger.error(f"Failed to fetch Prometheus data: {e}")

    alert_read = await read_active_alerts()

    active_targets = [
        {
            "job":           t.get("labels", {}).get("job", "unknown"),
            "instance":      t.get("labels", {}).get("instance", "unknown"),
            "instance_name": t.get("labels", {}).get("instance_name", ""),
            "tier":          t.get("labels", {}).get("tier", ""),
            "service":       t.get("labels", {}).get("service", ""),
            "health":        t.get("health", "unknown"),
            "last_scrape":   t.get("lastScrape", ""),
            "scrape_ms":     round(t.get("lastScrapeDuration", 0) * 1000, 1),
        }
        for t in targets_payload.get("activeTargets", [])
    ]

    active_alerts = [
        {
            "alertname":     a["alertname"] or "Unknown",
            "state":         a["state"],
            "severity":      a["severity"],
            "instance":      "",
            "instance_name": a["labels"].get("instance_name", "") or a["labels"].get("device", ""),
            "job":           a["labels"].get("job", ""),
            "service":       a["labels"].get("service", ""),
            "tier":          "",
            "labels":        a["labels"],
            # vmalert's annotations are not in the metrics store; the readable name stands in for the summary
            "annotations":   {"summary": a["title"]},
            "active_at":     a["active_since"] or "",
        }
        for a in alert_read["alerts"]
    ]

    up_count = sum(1 for t in active_targets if t["health"] == "up")

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "targets":   active_targets,
        "alerts":    active_alerts,
        "alerts_configured": alert_read["configured"],
        "alerts_readable":   alert_read["readable"],
        "alerts_reason":     alert_read["reason"],
        "alerts_source":     alert_read["source"],
        "alerts_withheld":   alert_read["withheld"],
        "summary": {
            "total_targets":  len(active_targets),
            "up_count":       up_count,
            "down_count":     len(active_targets) - up_count,
            "firing_alerts":  sum(1 for a in active_alerts if a["state"] == "firing"),
            "pending_alerts": sum(1 for a in active_alerts if a["state"] == "pending"),
        },
    }


# ---------------------------------------------------------------------------
# Reactor Framework Observability (Phase 7 — 2026-04-27)
# ---------------------------------------------------------------------------

@router.get("/reactor/status", summary="Reactor framework status snapshot")
async def reactor_status(
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Snapshot of every running reactor's lifetime counters.

    Returns a list of dicts with: name, event_type, leader_key, running,
    is_leader, ws_connected, started_at, dispatch_count, error_count,
    last_event_at (iso), last_event_id, last_dispatch_ms, last_error.

    Used by the AdminReactors UI for live observability and by ops to
    diagnose stuck/disconnected reactors after a deploy.

    Requires admin_platform flag.
    """
    from agentvault_registry.background_tasks.reactor_base import EventStoreReactor

    # Phase C3 (2026-04-29): use async snapshot — counters merged from Redis
    # so the view is unified across all uvicorn workers (no round-robin
    # flicker). Falls back to per-worker view when Redis is unavailable.
    reactors = await EventStoreReactor.snapshot_status_async()
    leaders = sum(1 for r in reactors if r.get("is_leader"))
    connected = sum(1 for r in reactors if r.get("ws_connected"))
    total_dispatches = sum(r.get("dispatch_count", 0) or 0 for r in reactors)
    total_errors = sum(r.get("error_count", 0) or 0 for r in reactors)

    return {
        "summary": {
            "total_reactors": len(reactors),
            "leaders": leaders,
            "ws_connected": connected,
            "lifetime_dispatches": total_dispatches,
            "lifetime_errors": total_errors,
        },
        "reactors": reactors,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/workers/vitals", summary="Background worker vitals (§VITALS roster + verdict)")
async def workers_vitals(
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Every background worker, its last cycle, and a VERDICT.

    §VITALS (2026-09-04). The sibling rail below (`/workers/status`) keeps its
    roster in a hand-maintained dict that had gone 5 months stale: 27 of the 50
    workers it found printed "(undocumented worker)", and exactly 1 of 50 carried
    a last-run timestamp. This one reads the roster workers DECLARE at launch
    (and join automatically on their first leader turn), so a worker nobody
    remembered to write down is still a row.

    Verdicts:
      DISABLED   — declared, switched off by its env gate. Not a fault.
      WARMING    — declared less than one interval ago and not due yet. Not a fault.
      NEVER_RAN  — declared, past its first interval, still no cycle and no turn.
      ERRORING   — its most recent cycle failed.
      STALE      — no leader turn for > 3x its declared interval (floor 5 min).
      ALIVE      — turning, and its last cycle succeeded.
      UNKNOWN_INTERVAL — turning, but nothing declared how often it should, so
                   staleness cannot be judged. Reported, never guessed.

    ⚠ A verdict is only as good as the interval behind it: a daily worker judged
    against a 5-minute floor would read STALE all day, which is how a rail comes to be ignored.
    """
    from agentvault_registry.background_tasks import vitals as _vitals
    from datetime import datetime as _dt, timezone as _tz

    snap = await _vitals.snapshot()
    now = _dt.now(_tz.utc)

    def _age(iso: str | None) -> float | None:
        if not iso:
            return None
        try:
            t = _dt.fromisoformat(iso)
            if t.tzinfo is None:
                t = t.replace(tzinfo=_tz.utc)
            return (now - t).total_seconds()
        except Exception:
            return None

    rows = []
    counts: dict[str, int] = {}
    for w in snap.get("workers", []):
        st = w.get("state") or {}
        interval = w.get("interval_sec")
        # These two are still REPORTED as ages below; the rest of what this block used to
        # compute moved into worker_verdict() and is not recomputed here — a leftover local
        # that no longer feeds anything reads like a calculation that matters.
        turn_age = _age(st.get("last_turn_at"))
        success_age = _age(st.get("last_success_at"))
        # §FRAMELIC row 167 — ONE definition, shared with /admin/workers/status. Two rails
        # answering the same question with two implementations is how they drift apart.
        verdict = worker_verdict(w, now)
        counts[verdict] = counts.get(verdict, 0) + 1
        rows.append({
            "worker_id": w.get("worker_id"),
            "verdict": verdict,
            "module": w.get("module") or None,
            "pattern": w.get("pattern") or None,
            "interval_sec": interval,
            "enabled": w.get("enabled", True),
            "gate": w.get("gate") or None,
            "registered_at": w.get("registered_at"),
            "last_turn_at": st.get("last_turn_at"),
            "last_cycle_at": st.get("last_cycle_at"),
            "last_success_at": st.get("last_success_at"),
            "last_outcome": st.get("last_outcome"),
            "last_error": st.get("last_error") or None,
            "last_duration_ms": int(st["last_duration_ms"]) if str(st.get("last_duration_ms", "")).isdigit() else None,
            "cycles": int(st["cycles"]) if str(st.get("cycles", "")).isdigit() else 0,
            "errors": int(st["errors"]) if str(st.get("errors", "")).isdigit() else 0,
            "seconds_since_turn": round(turn_age, 1) if turn_age is not None else None,
            "seconds_since_success": round(success_age, 1) if success_age is not None else None,
        })

    order = {"ERRORING": 0, "STALE": 1, "NEVER_RAN": 2, "UNKNOWN_INTERVAL": 3,
             "WARMING": 4, "DISABLED": 5, "ALIVE": 6}
    rows.sort(key=lambda r: (order.get(r["verdict"], 9), r["worker_id"] or ""))
    return {
        "summary": {"total": len(rows), **counts},
        "workers": rows,
        "redis_error": snap.get("error"),
        "snapshot_at": now.isoformat(),
    }


def _schedule_label(interval_sec) -> str:
    try:
        v = float(interval_sec)
    except (TypeError, ValueError):
        return "?"
    if v <= 0:
        return "?"
    if v < 60:
        return f"{int(v)}s"
    if v < 3600:
        return f"{int(v // 60)}min"
    return f"{v / 3600:g}hr"


def worker_verdict(w: dict, now=None) -> str:
    """One word for what a worker row MEANS. Pure, so a test can hand it a row.

    §FRAMELIC (2026-09-07, findings row 167). This logic already existed — inside the vitals
    rail — while `/admin/workers/status`, the rail an operator actually opens, showed three
    raw timestamps and no interpretation. A blank `last_run_at` means five different things
    (off · not due yet · nothing to do · dead · never started) and a reader cannot tell which,
    which is how "4 workers that never turned" read as four faults when three were correct.

    Extracted rather than copied: two rails answering the same question with two
    implementations is the defect this batch kept meeting (rows 154, 157, 166).

      DISABLED          — its gate says no. Terminal and honest; not a fault.
      WARMING           — inside its first interval. A daily worker is not late at boot.
      NEVER_RAN         — past its first interval with nothing recorded. This one IS a fault.
      ERRORING          — it ran and the cycle failed.
      STALE             — it last showed life more than 3 intervals ago.
      UNKNOWN_INTERVAL  — no declared interval, so lateness cannot be judged. Say so.
      ALIVE             — turned or ran recently.
    """
    from datetime import datetime as _dt, timezone as _tz

    now = now or _dt.now(_tz.utc)

    def _age(iso):
        if not iso:
            return None
        try:
            t = _dt.fromisoformat(iso)
            if t.tzinfo is None:
                t = t.replace(tzinfo=_tz.utc)
            return (now - t).total_seconds()
        except Exception:
            return None

    st = w.get("state") or {}
    interval = w.get("interval_sec")
    turn_age = _age(st.get("last_turn_at"))
    cycle_age = _age(st.get("last_cycle_at"))
    liveness_age = min([a for a in (turn_age, cycle_age) if a is not None], default=None)
    reg_age = _age(w.get("registered_at"))
    warming = (reg_age is not None
               and reg_age < (float(interval) if interval else 900.0) + 120.0)

    if not w.get("enabled", True):
        return "DISABLED"
    if not st:
        return "WARMING" if warming else "NEVER_RAN"
    if st.get("last_outcome") == "error":
        return "ERRORING"
    if interval is None:
        return "UNKNOWN_INTERVAL"
    if liveness_age is not None and liveness_age > max(3 * float(interval), 300.0):
        return "STALE"
    if liveness_age is None:
        return "WARMING" if warming else "NEVER_RAN"
    return "ALIVE"


def merge_worker_roster(roster_workers: list, descriptions: dict) -> list:
    """§VITALS S3 — the rows /admin/workers/status lists are the DECLARED roster (what every worker
    registered at launch), decorated with the hand-written description/category where one exists.
    Pure, so a test can hand it a roster and read the rows. A name in `descriptions` that no worker
    declared is NOT a row: the description table cannot resurrect a worker that does not run."""
    rows = []
    for w in sorted(roster_workers, key=lambda w: str(w.get("worker_id") or "")):
        name = str(w.get("worker_id") or "").strip()
        if not name:
            continue
        d = descriptions.get(name) or {}
        st = w.get("state") or {}
        rows.append({
            "name": name,
            "description": d.get("desc") or f"{w.get('module') or 'worker'} ({w.get('pattern') or 'loop'})",
            "schedule_label": d.get("sched") or _schedule_label(w.get("interval_sec")),
            "category": d.get("cat") or "undescribed",
            "module": w.get("module") or "",
            "pattern": w.get("pattern") or "",
            "enabled": bool(w.get("enabled", True)),
            "interval_sec": w.get("interval_sec"),
            # §FRAMELIC (2026-09-07, findings row 166) — carry the VITALS state through.
            # This function used to drop `w["state"]`, so the freshness the base worker had
            # already written was discarded one line before the row that reports it, and the
            # rail fell back to a legacy flat key that only the OLD leadership pattern writes.
            # Result: `last_run_at: null` for every BackgroundWorker on every frame.
            "last_run_at": st.get("last_cycle_at") or None,
            "last_success_at": st.get("last_success_at") or None,
            # A subscriber that has not fired has done no work and MUST read null above —
            # but it is not dead, and this is what says so. `last_turn_at` is stamped inside
            # `try_acquire_leadership`, so any leader-elected worker has one whether or not it
            # had anything to do. Without it, "idle" and "dead" look identical.
            "last_turn_at": st.get("last_turn_at") or None,
            "gate": w.get("gate") or None,
            # One word an operator can act on, instead of three timestamps to interpret.
            "verdict": worker_verdict(w),
            "last_outcome": st.get("last_outcome") or None,
            "last_error": st.get("last_error") or None,
        })
    return rows


@router.get("/workers/status", summary="Background workers status snapshot")
async def workers_status(
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Build #4 (2026-05-07): live snapshot of every background worker task.

    Reads Redis `leader:<task>` keys to derive leader status + remaining lease.
    Filters out reactor framework leases (those have their own /reactor/status
    endpoint). Augments with hardcoded metadata from CLAUDE.md PART 9 so
    operators see schedule + description per task.

    Returns:
        {
          summary: { total, with_leader, no_leader },
          workers: [
            {
              name, description, schedule_label,
              has_leader, leader_worker, lease_ttl_seconds,
              category
            }, ...
          ],
          snapshot_at: iso
        }

    Requires admin_platform flag.
    """
    from agentvault_registry.background_tasks.leader import get_redis
    from agentvault_registry.background_tasks import vitals as _vitals
    # §VITALS S3 (batch 2, 2026-09-05): the ROSTER is what workers DECLARE at launch
    # (vitals.register → workers:roster). The dict below is now only a DESCRIPTION overlay
    # for the names that have one; it no longer decides which workers exist. A hand-kept
    # roster went 5 months stale and printed "(undocumented worker)" for 27 of 50.
    KNOWN_TASKS: dict[str, dict[str, str]] = {
        "a2a_payment_expiry":      {"desc": "Expires stale A2A payment tokens (f045)",            "sched": "60s",   "cat": "payments"},
        "agent_health_checker":    {"desc": "Periodic agent health probes",                      "sched": "60s",   "cat": "operations"},
        "auto_tally":              {"desc": "Auto-tally expired governance proposals",           "sched": "60s",   "cat": "governance"},
        "bridge_expiry":           {"desc": "Token bridge expiry (SF-3 cross-frame transfers)",  "sched": "60s",   "cat": "federation"},
        "canary_judge":            {"desc": "Canary test outcome judge (5s sweep)",              "sched": "5s",    "cat": "monitoring"},
        "canary_runner":           {"desc": "Fires real synthetic transfers across paths",       "sched": "60s",   "cat": "monitoring"},
        "collusion_worker":        {"desc": "Collusion graph analysis (Tarjan SCC)",             "sched": "5min",  "cat": "monitoring"},
        "compliance_poller":       {"desc": "6-hour peer policy poll (CONSUL)",                  "sched": "6hr",   "cat": "federation"},
        "eigentrust_worker":       {"desc": "EigenTrust++ reputation computation",               "sched": "5min",  "cat": "reputation"},
        "es_balance_sync":         {"desc": "EventStore balance sync (legacy alias)",            "sched": "60s",   "cat": "ledger"},
        "eventstore_balance_sync": {"desc": "Keeps registry DB balances in sync with EventStore","sched": "60s",   "cat": "ledger"},
        "federation_card_gc":      {"desc": "Daily defunct-card GC worker (W4)",                 "sched": "daily", "cat": "federation"},
        "federation_sync":         {"desc": "Pull-based bilateral agent card sync",              "sched": "5min",  "cat": "federation"},
        "license_drift_monitor":   {"desc": "Hourly local-DB drift safety net",                  "sched": "1hr",   "cat": "federation"},
        "saga_timeout_checker":    {"desc": "Cross-registry transfer saga timeout sweeper",      "sched": "60s",   "cat": "ledger"},
        "settlement_reconciliation": {"desc": "A2A payment settlement reconciliation",          "sched": "60s",   "cat": "payments"},
        "staking_distributor":     {"desc": "Daily payout on locked units, idle where none is paid", "sched": "daily", "cat": "ledger"},
        "supply_auditor":          {"desc": "Supply invariant audit (zero tolerance)",           "sched": "60s",   "cat": "audit"},
        "tx_flusher":              {"desc": "TEG stream batch flusher (low-latency tx writes)",  "sched": "1s",    "cat": "ledger"},
        "velocity_snapshot":       {"desc": "Fee velocity snapshots (dynamic fee scaling)",      "sched": "5min",  "cat": "ledger"},
        "webhook_retry":           {"desc": "Retries failed webhook deliveries (legacy alias)",  "sched": "60s",   "cat": "webhooks"},
        "webhook_retry_worker":    {"desc": "Retries failed webhook deliveries w/ exp backoff",  "sched": "60s",   "cat": "webhooks"},
    }

    workers: list[dict] = []
    redis = await get_redis()

    # 1. Scan all leader:* keys, filter out reactor_*
    discovered_keys: list[str] = []
    if redis is not None:
        try:
            async for k in redis.scan_iter(match="leader:*", count=200):
                if not k.startswith("leader:reactor_"):
                    discovered_keys.append(k)
        except Exception as e:
            logger.warning(f"[Workers] Redis scan failed: {e}")

    # P5.2 (2026-05-08): the LEGACY flat keys, written by `run_with_leadership` in
    # background_tasks/leader.py. §FRAMELIC row 166 — this is now the FALLBACK, not the
    # source. `BackgroundWorker._run_loop` never calls `run_with_leadership`: it acquires
    # leadership directly and records the cycle with `vitals.stamp()`, so it writes no flat
    # key at all and every worker on that pattern read `last_run_at: null` — 20 of them on
    # these frames, including the supply auditor. The comment on the writer side said the
    # rail was "kept until S3 moves it onto the vitals roster"; this is that move. Vitals is
    # the universal record (the legacy path stamps it too), so it wins and this stays only
    # for anything that writes the flat key and never registered.
    async def _last_run_meta(name: str) -> dict:
        if redis is None:
            return {"last_run_at": None, "last_status": None}
        try:
            iso = await redis.get(f"worker:{name}:last_run_at")
            status = await redis.get(f"worker:{name}:last_status")
            return {
                "last_run_at": iso if isinstance(iso, str) else (iso.decode("utf-8", "ignore") if iso else None),
                "last_status": status if isinstance(status, str) else (status.decode("utf-8", "ignore") if status else None),
            }
        except Exception:
            return {"last_run_at": None, "last_status": None}

    # 2. For each known task: build a row (whether or not it has a leader)
    seen_names: set[str] = set()
    snap = await _vitals.snapshot()
    roster_rows = merge_worker_roster(snap.get("workers") or [], KNOWN_TASKS)
    for row in roster_rows:
        task_name, meta = row["name"], row
        seen_names.add(task_name)
        leader_key = f"leader:{task_name}"
        has_leader = False
        leader_worker = None
        lease_ttl = None
        if redis is not None:
            try:
                val = await redis.get(leader_key)
                if val is not None:
                    has_leader = True
                    leader_worker = val if isinstance(val, str) else val.decode("utf-8", "ignore")
                    lease_ttl = await redis.ttl(leader_key)
            except Exception:
                pass

        # Prefer what the worker itself recorded; only ask the legacy keys if it recorded
        # nothing (a worker on the old pattern that never registered with vitals).
        last_run = {"last_run_at": row.get("last_run_at"), "last_status": row.get("last_outcome")}
        if not last_run["last_run_at"]:
            last_run = await _last_run_meta(task_name)

        workers.append({
            "name": task_name,
            "description": meta["description"],
            "schedule_label": meta["schedule_label"],
            "category": meta["category"],
            "declared": True,
            "module": meta.get("module") or "",
            "pattern": meta.get("pattern") or "",
            "enabled": meta.get("enabled", True),
            "has_leader": has_leader,
            "leader_worker": leader_worker,
            "lease_ttl_seconds": lease_ttl,
            # §VITALS' own lesson, made visible: a worker can TURN faithfully while every
            # cycle fails, so "when did it last run" and "when did it last succeed" are two
            # questions and the rail must answer both.
            "last_success_at": meta.get("last_success_at"),
            "last_turn_at": meta.get("last_turn_at"),
            "verdict": meta.get("verdict"),
            "gate": meta.get("gate"),
            "last_error": meta.get("last_error") or None,
            **last_run,
        })

    # 3. Surface any UNKNOWN leader keys we observed (i.e., new workers not yet
    #    in the static map). They appear with desc="(undocumented)" so ops can
    #    see drift without us silently hiding them.
    for k in discovered_keys:
        name = k.split(":", 1)[1]
        if name in seen_names:
            continue
        leader_worker = None
        lease_ttl = None
        if redis is not None:
            try:
                val = await redis.get(k)
                if val is not None:
                    leader_worker = val if isinstance(val, str) else val.decode("utf-8", "ignore")
                    lease_ttl = await redis.ttl(k)
            except Exception:
                pass
        workers.append({
            "name": name,
            "description": "(holds a leader lease but is NOT in the launch roster — a worker that never called vitals.register)",
            "schedule_label": "?",
            "category": "not_in_roster",
            "declared": False,
            "has_leader": True,
            "leader_worker": leader_worker,
            "lease_ttl_seconds": lease_ttl,
            # same shape as a declared row — a consumer should not have to special-case these
            **(await _last_run_meta(name)),
            "last_success_at": None,
            "last_error": None,
        })

    # Sort: with_leader first, then alphabetically by name
    workers.sort(key=lambda w: (not w["has_leader"], w["name"]))

    with_leader = sum(1 for w in workers if w["has_leader"])
    return {
        "source": "vitals_roster" if snap.get("roster_size") else "vitals_roster_empty",
        "roster_size": snap.get("roster_size", 0),
        "summary": {
            "total": len(workers),
            "with_leader": with_leader,
            "no_leader": len(workers) - with_leader,
            "not_in_roster": sum(1 for w in workers if not w.get("declared", True)),
        },
        "workers": workers,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# f037 — Event Emission Policy Admin Endpoints
# ---------------------------------------------------------------------------
# f037: Projection Snapshot
# ---------------------------------------------------------------------------

_PROJECTION_SNAPSHOT_MAX_BYTES = 1_000_000   # the store's bus takes a message up to 1 MiB; the event envelope needs the rest


def _projection_snapshot_max_bytes() -> int:
    """D6-818: the largest ProjectionSnapshot payload this route sends (PROJECTION_SNAPSHOT_MAX_BYTES, default 1,000,000)."""
    try:
        v = int(os.getenv("PROJECTION_SNAPSHOT_MAX_BYTES", "") or _PROJECTION_SNAPSHOT_MAX_BYTES)
    except ValueError:
        return _PROJECTION_SNAPSHOT_MAX_BYTES
    return v if v > 0 else _PROJECTION_SNAPSHOT_MAX_BYTES


@router.post("/projection-snapshot", summary="Take a projection snapshot from TEG balances")
async def take_projection_snapshot(
    current_developer: models.Developer = Security(security.require_admin_flag("admin_treasury")),
    db: AsyncSession = Depends(get_db),
):
    """
    Takes a snapshot of all agent balances from the local TEG (source of truth)
    and posts it as a ProjectionSnapshot event to the EventStore.

    The ES projection engine will use this snapshot as baseline, only replaying
    events after the snapshot timestamp. This eliminates drift from historical
    pollution.

    Configurable: requires ENABLE_PROJECTION_SNAPSHOTS=true env var.
    Requires admin developer auth.
    """
    if not os.getenv("ENABLE_PROJECTION_SNAPSHOTS", "").lower() in ("true", "1", "yes"):
        raise HTTPException(status_code=403, detail="Projection snapshots disabled. Set ENABLE_PROJECTION_SNAPSHOTS=true to enable.")

    # Step 1: Get all agent balances from local TEG
    teg_url = os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080")
    teg_admin_key = os.getenv("TEG_ADMIN_API_KEY", "")

    try:
        async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
            # Get all agent profiles from TEG
            resp = await client.get(
                f"{teg_url}/api/v1/admin/treasury/info",
                headers={"Authorization": f"Bearer {teg_admin_key}"}
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"TEG treasury info failed: {resp.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach TEG: {e}")

    # Step 2: Get all agent balances from Registry DB (synced from TEG)
    result = await db.execute(
        select(models.Agent.did, models.Agent.liquid_balance, models.Agent.staked_balance)
        .where(models.Agent.status == "active")
    )
    rows = result.all()

    snapshot_agents = []
    for row in rows:
        snapshot_agents.append({
            "did": row.did,
            "liquid": float(row.liquid_balance or 0),
            "staked": float(row.staked_balance or 0),
        })

    # Step 3: Emit ProjectionSnapshot event to EventStore
    from agentvault_registry.event_emitter import get_event_emitter, _emit_safe_dumps
    emitter = get_event_emitter()
    if not emitter:
        raise HTTPException(status_code=500, detail="Event emitter not available")

    from datetime import datetime, timezone
    snapshot_ts = datetime.now(timezone.utc).isoformat()
    data = {
        "agents": snapshot_agents,
        "timestamp": snapshot_ts,
        "agent_count": len(snapshot_agents),
        "source": "registry_admin",
    }

    # D6-818 (2026-10-24): "snapshot_taken" only for a snapshot the store took. The store publishes each event as one bus
    # message, and sbx-alpha's snapshot of 10,254 agents (1,074,935 bytes) was refused every time ("Kafka publish failed:
    # MessageSizeTooLargeError", 503); the emitter parked it in es_emit_outbox, the drainer retried it for 12 hours and
    # parked it dead, and this route answered "snapshot_taken" each time. A snapshot that cannot fit is refused here,
    # before anything is sent; one the store refuses for now is answered as such and never queued: a baseline landing
    # hours late would be a baseline of balances that have moved since.
    limit = _projection_snapshot_max_bytes()
    size = len(_emit_safe_dumps(data).encode("utf-8"))
    if size > limit:
        raise HTTPException(status_code=422, detail=(
            f"snapshot_too_large: the ProjectionSnapshot event would carry {size} bytes for {len(snapshot_agents)} agents, "
            f"over the store bus's limit of {limit} bytes (PROJECTION_SNAPSHOT_MAX_BYTES): nothing was taken"))

    outcome: dict = {}
    success = await emitter.emit(
        event_type="ProjectionSnapshot",
        aggregate_id="system",
        data=data,
        aggregate_type="System",
        defer=False,
        outcome=outcome,
    )

    if outcome.get("blocked_by_policy"):
        raise HTTPException(status_code=409, detail=(
            "snapshot_blocked_by_policy: the event emission policy does not let the registry emit ProjectionSnapshot: "
            "nothing was taken"))
    if not success:
        why = f"{outcome.get('status') or 'no answer'}: {str(outcome.get('error') or '')[:200]}"
        if outcome.get("retryable"):
            raise HTTPException(status_code=503, headers={"Retry-After": "60"}, detail=(
                f"snapshot_not_stored: the store did not take the ProjectionSnapshot event ({why}): nothing was taken "
                "and nothing was queued; take it again"))
        raise HTTPException(status_code=502, detail=(
            f"snapshot_refused_by_store: the store refused the ProjectionSnapshot event ({why}): nothing was taken"))

    total_liquid = sum(a["liquid"] for a in snapshot_agents)
    total_staked = sum(a["staked"] for a in snapshot_agents)

    return {
        "status": "snapshot_taken",
        "event_bytes": size,
        "agent_count": len(snapshot_agents),
        "total_liquid": total_liquid,
        "total_staked": total_staked,
        "total_balance": total_liquid + total_staked,
        "timestamp": snapshot_ts,
    }


@router.get("/event-emission-policies", summary="Get all event emission policies")
async def get_event_emission_policies(
    current_developer: models.Developer = Security(security.require_admin_flag("admin_treasury")),
    db: AsyncSession = Depends(get_db),
):
    """Returns all event emission policies (which layer emits which event)."""
    result = await db.execute(select(models.EventEmissionPolicy).order_by(models.EventEmissionPolicy.event_type))
    rows = result.scalars().all()
    return {
        "policies": [
            {
                "event_type": r.event_type,
                "emit_from_teg": r.emit_from_teg,
                "emit_from_registry": r.emit_from_registry,
                "skip_in_projection": r.skip_in_projection,
                "description": r.description,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/event-emission-policies/effective", summary="The effective emission-policy configuration, per event type")
async def get_effective_emission_policy(
    include_drift: bool = True,
    current_developer: models.Developer = Security(security.require_admin_flag("admin_treasury")),
    db: AsyncSession = Depends(get_db),
):
    """W3 (2026-10-25): what this frame does with every event type: the rows, the types the code emits, the types the
    event store holds, the registry's and the TEG's gate per type, the projection, the registry's shadow counts, the
    findings, and (include_drift) where each peer frame's rows differ. The console page "Emission policy" draws it;
    services/emission_policy_view.py says what each column is derived from."""
    from ..services.emission_policy_view import build_view
    return await build_view(db, include_drift=include_drift)


@router.put("/event-emission-policies/{event_type}", summary="Update event emission policy")
async def update_event_emission_policy(
    event_type: str,
    policy_data: dict,
    current_developer: models.Developer = Security(security.require_admin_flag("admin_treasury")),
    db: AsyncSession = Depends(get_db),
):
    """
    Update emission policy for a specific event type.

    Body: {
      "emit_from_teg": true/false,
      "emit_from_registry": true/false,
      "skip_in_projection": true/false,
      "description": "optional"
    }

    Requires admin developer auth.
    """
    if not admin_credential(current_developer):   # D6-057 (§POCKETPAIR): a scoped key is not admin
        raise HTTPException(status_code=403, detail="Admin access required")

    # §pass52 Phase H V5 — protect the supply invariant from policy misconfiguration.
    # The 6 historical breach events (auditor.theprotocol.cloud/api/auditor/breaches,
    # 2026-04-10/11) demonstrate that supply drift IS possible. The most dangerous
    # misconfiguration is setting skip_in_projection=true on a balance-moving event:
    # the event is stored but balance projection ignores it → SILENT DRIFT.
    # See: DESIGN_2026-05-20_EVENT_EMISSION_POLICY_CONSOLIDATION_AAA.md §1 T2.
    from ..event_emitter import BALANCE_MOVING_EVENT_TYPES
    if (
        event_type in BALANCE_MOVING_EVENT_TYPES
        and policy_data.get('skip_in_projection') is True
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot set skip_in_projection=true on balance-moving event '{event_type}'. "
                f"This would silently drop the event from the balance projection while keeping "
                f"it in the immutable ledger — causing supply-invariant drift identical to the "
                f"2026-04-10/11 breach events. If you NEED to change this, the event must first "
                f"be removed from BALANCE_MOVING_EVENT_TYPES in event_emitter.py (engineering review)."
            ),
        )

    from sqlalchemy import select
    result = await db.execute(
        select(models.EventEmissionPolicy).where(models.EventEmissionPolicy.event_type == event_type)
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail=f"No policy for event type: {event_type}")

    if 'emit_from_teg' in policy_data:
        policy.emit_from_teg = bool(policy_data['emit_from_teg'])
    if 'emit_from_registry' in policy_data:
        policy.emit_from_registry = bool(policy_data['emit_from_registry'])
    if 'skip_in_projection' in policy_data:
        policy.skip_in_projection = bool(policy_data['skip_in_projection'])
    if 'description' in policy_data:
        policy.description = policy_data['description']

    await db.commit()

    # Force policy cache refresh on this worker
    from ..event_emitter import _load_emission_policies, publish_emission_policy_invalidation
    try:
        await _load_emission_policies()
    except Exception:
        pass

    # Phase 10 #3: drop the cache on every other registry worker via Redis
    # pub/sub. Eliminates the per-uvicorn-worker stale-view window.
    # Best-effort — TTL refresh is the safety net.
    try:
        await publish_emission_policy_invalidation()
    except Exception as e:
        logger.warning(f"[admin] Emission policy invalidation publish failed: {e}")

    # Phase 9.2: emit EventEmissionPolicyUpdated so the reactor framework
    # propagates cache invalidation to (a) other registry workers via WS,
    # (b) TEG via the dedicated /admin/emission-policy/refresh endpoint,
    # (c) any subscribed webhooks. Closes the f037 cache TTL window.
    try:
        from ..event_emitter import get_event_emitter
        emitter = get_event_emitter()
        await emitter.emit(
            event_type="EventEmissionPolicyUpdated",
            aggregate_id=f"emission_policy:{policy.event_type}",
            aggregate_type="EventEmissionPolicy",
            data={
                "event_type": policy.event_type,
                "emit_from_teg": policy.emit_from_teg,
                "emit_from_registry": policy.emit_from_registry,
                "skip_in_projection": policy.skip_in_projection,
                "description": policy.description,
                # §DOCSFIX D6-612 (2026-10-16): the admin by developer id only. The event store is immutable (an
                # address written there can never be erased) and the reactor hands this event to webhooks.
                "actor_developer_id": current_developer.id,
            },
        )
    except Exception as exc:
        logger.warning(f"[admin] EventEmissionPolicyUpdated emit failed (non-fatal): {exc}")

    return {
        "event_type": policy.event_type,
        "emit_from_teg": policy.emit_from_teg,
        "emit_from_registry": policy.emit_from_registry,
        "skip_in_projection": policy.skip_in_projection,
        "description": policy.description,
        "status": "updated",
    }


@router.post("/svid/refresh", summary="Force-refresh local SVID + trust bundle")
async def admin_svid_refresh(
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Synchronously force-refresh the registry's SPIFFE SVID + peer trust bundles
    from the Workload API.

    Use case: after bilateral SPIRE bundle exchange (WS3 frame onboarding), the
    local mTLS verify chain doesn't see freshly federated peer bundles until the
    next 30-minute polling cycle. This endpoint shortcuts the wait.

    Returns 200 + {ok, message} on success; 503 if the SVID client is not
    running, on mock mode, or the workload API is unavailable.
    """
    from ..identity.svid_client import svid_client
    ok, message = svid_client.refresh_now()
    if not ok:
        raise HTTPException(status_code=503, detail=message)
    return {"ok": True, "message": message, "spiffe_id": svid_client.spiffe_id}


# Export router
__all__ = ["router"]
