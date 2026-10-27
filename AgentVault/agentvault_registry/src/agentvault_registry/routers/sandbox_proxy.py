"""
Sandbox proxy — forwards requests to internal sandbox registries.

Allows downloaded agent templates (e.g. GeraldShip) to run sandbox missions
without direct Docker-network access to sandbox containers.

Routes:
  ANY /api/v1/sandbox/a/{path}  -> forwards to sandbox registry A
  ANY /api/v1/sandbox/b/{path}  -> forwards to sandbox registry B

Security:
  - Path whitelist: only allowed API paths are forwarded
  - Explicit blocklist: admin/test/mcp endpoints are always blocked
  - Rate limited: 60 req/min per IP
  - The sandbox itself is disposable data (resettable at any time)

Headers from the caller (Authorization, Bootstrap-Token, Content-Type, etc.)
are forwarded to the sandbox as-is. The sandbox validates them independently.
"""
import logging
import os
import re

import httpx
from fastapi import APIRouter, Request, Response, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sandbox")  # §pass56 PR-5: tags via main.py "Sandbox Proxy"

# §RATEFIX: THE shared, Redis-backed limiter — the same object main.py puts on
# app.state, so these decorations are both enforced and shared across workers.
# A router-local Limiter() would be in-memory per worker AND invisible to the
# middleware; that is what made all 65 limits here meaningless.
from agentvault_registry.middleware.rate_limiter import shared_limiter as limiter

# ── Sandbox target URLs (Docker-internal) ─────────────────────────────────
# §FESUITE (2026-10-10, the operator batch): no default here either. The old defaults named registry-test and
# registry-test-b, the tier torn down at §BATCH3, so every registry that does not set these (every cloud operator)
# answered 502 "Cannot reach sandbox registry" from a dial that could never work, and the console's Federation Test page
# read that as a broken sandbox. Unset means "no sandbox registry here": the proxy says so (503 with the reason) and
# /api/v1/public/registry-config lists only the proxies that exist (`sandbox_proxy`), so the console never asks.
SANDBOX_A_URL = os.getenv("SANDBOX_A_INTERNAL_URL", "").rstrip("/")
SANDBOX_B_URL = os.getenv("SANDBOX_B_INTERNAL_URL", "").rstrip("/")
# §TRUSTCHAIN P4.6: no default — the old default named a tier torn down at §BATCH3, so an
# unconfigured registry dialed a hostname that does not resolve. Unset means "no sandbox event
# store on this registry", and the proxy says so.
SANDBOX_ES_URL = os.getenv("SANDBOX_ES_INTERNAL_URL", "").rstrip("/")

# ── Path whitelist (regex patterns) ───────────────────────────────────────
# Only these paths are forwarded. Everything else is blocked.
_ALLOWED_PATTERNS = [
    r"^api/v1/auth/register$",
    r"^api/v1/auth/login$",
    r"^api/v1/auth/agent/token$",
    r"^api/v1/onboard/bootstrap/request-token$",
    r"^api/v1/onboard/create_agent$",
    r"^api/v1/teg/balance$",
    r"^api/v1/teg/transfer$",
    r"^api/v1/teg/cross-registry-transfer$",
    r"^api/v1/teg/treasury/fund-agent$",
    r"^api/v1/staking/stake$",
    r"^api/v1/staking/my-positions$",
    r"^api/v1/governance/proposals$",
    r"^api/v1/governance/proposals/[^/]+/vote$",
    r"^api/v1/governance/proposals/[^/]+/tally$",
    r"^api/v1/disputes/?$",
    r"^api/v1/federation/peers/?$",
    r"^api/v1/federation/network-stats$",
    r"^api/v1/agents/by-did/[^/]+$",
    r"^api/v1/agents/?$",
    r"^api/v1/agent-cards/?$",
    r"^api/v1/admin/federation/peers/[^/]+/approve$",
    r"^(api/v1/)?stack-health$",
    r"^(api/v1/)?federation/sync/trigger$",
    r"^(api/v1/)?teg/treasury/mint$",
    r"^health$",
]
_COMPILED_PATTERNS = [re.compile(p) for p in _ALLOWED_PATTERNS]

# EventStore whitelist — read-only queries
_ES_ALLOWED_PATTERNS = [
    r"^api/v1/events/?$",
    r"^api/v1/events/aggregate/[^/]+$",
    r"^api/v1/projections/stats$",
    r"^api/v1/projections/supply-audit$",
    r"^api/v1/projections/balances$",
    r"^health$",
]
_ES_COMPILED_PATTERNS = [re.compile(p) for p in _ES_ALLOWED_PATTERNS]


def _is_es_path_allowed(path: str) -> bool:
    clean = path.lstrip("/")
    for wp in _ES_COMPILED_PATTERNS:
        if wp.match(clean):
            return True
    return False

# Explicit blocklist (checked before whitelist for safety)
_BLOCKED_PATTERNS = [
    r"admin/api-test",
    r"admin/tutorial",
    r"admin/event-emission",
    r"admin/projection-snapshot",
    r"admin/broadcast",
    r"admin/enforcement",
    r"admin/funding",
    r"mcp/",
]
_COMPILED_BLOCKED = [re.compile(p) for p in _BLOCKED_PATTERNS]

# Headers to forward from the caller to the sandbox
_FORWARD_HEADERS = {
    "authorization",
    "bootstrap-token",
    "content-type",
    "accept",
    "x-api-key",
    "x-idempotency-key",
}

# Headers to return from the sandbox to the caller
_RETURN_HEADERS = {
    "content-type",
    "x-request-id",
}


def _is_path_allowed(path: str) -> bool:
    """Check path against blocklist then whitelist."""
    clean = path.lstrip("/")
    # Blocklist first
    for bp in _COMPILED_BLOCKED:
        if bp.search(clean):
            return False
    # Whitelist
    for wp in _COMPILED_PATTERNS:
        if wp.match(clean):
            return True
    return False


def configured_sandboxes() -> list:
    """The sandbox registries this registry proxies (`a`, `b`), in order: what registry-config advertises."""
    return [k for k, url in (("a", SANDBOX_A_URL), ("b", SANDBOX_B_URL)) if url]


async def _proxy_to_sandbox(
    sandbox_url: str,
    path: str,
    request: Request,
    frame: str = "",
) -> Response:
    """Forward a request to the sandbox and return the response."""

    if not sandbox_url:
        letter = (frame or "?").upper()
        raise HTTPException(
            status_code=503,
            detail=f"No sandbox registry {letter} is configured on this registry (SANDBOX_{letter}_INTERNAL_URL unset)",
        )
    if not _is_path_allowed(path):
        raise HTTPException(
            status_code=403,
            detail=f"Path not allowed through sandbox proxy: /{path}",
        )

    target_url = f"{sandbox_url}/{path}"

    # Collect headers to forward
    fwd_headers = {}
    for key, value in request.headers.items():
        if key.lower() in _FORWARD_HEADERS:
            fwd_headers[key] = value

    # Read raw body (works for both JSON and form-urlencoded)
    body = await request.body()

    method = request.method.upper()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                method=method,
                url=target_url,
                headers=fwd_headers,
                content=body if body else None,
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Sandbox request timed out")
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Cannot reach sandbox registry")
    except Exception as e:
        logger.error(f"[SANDBOX-PROXY] Upstream error: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Sandbox proxy error: {str(e)[:200]}",
        )

    # Build response headers
    resp_headers = {}
    for key, value in resp.headers.items():
        if key.lower() in _RETURN_HEADERS:
            resp_headers[key] = value

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp_headers,
        media_type=resp.headers.get("content-type"),
    )


# ── Route handlers ────────────────────────────────────────────────────────

# §pass53 (PR-16): split api_route(methods=[…]) into 5 distinct decorators so
# the spec emits 5 unique operationIds (was R-P0-2 — every SDK generator dropped
# 4 of 5 verbs because operationId must be unique per OpenAPI 3.x).
@router.get("/a/{path:path}",    operation_id="proxy_sandbox_a_get")
@router.post("/a/{path:path}",   operation_id="proxy_sandbox_a_post")
@router.put("/a/{path:path}",    operation_id="proxy_sandbox_a_put")
@router.patch("/a/{path:path}",  operation_id="proxy_sandbox_a_patch")
@router.delete("/a/{path:path}", operation_id="proxy_sandbox_a_delete")
@limiter.limit("60/minute")
async def proxy_sandbox_a(path: str, request: Request):
    """Forward request to sandbox registry A."""
    return await _proxy_to_sandbox(SANDBOX_A_URL, path, request, "a")


@router.get("/b/{path:path}",    operation_id="proxy_sandbox_b_get")
@router.post("/b/{path:path}",   operation_id="proxy_sandbox_b_post")
@router.put("/b/{path:path}",    operation_id="proxy_sandbox_b_put")
@router.patch("/b/{path:path}",  operation_id="proxy_sandbox_b_patch")
@router.delete("/b/{path:path}", operation_id="proxy_sandbox_b_delete")
@limiter.limit("60/minute")
async def proxy_sandbox_b(path: str, request: Request):
    """Forward request to sandbox registry B."""
    return await _proxy_to_sandbox(SANDBOX_B_URL, path, request, "b")


@router.api_route("/es/{path:path}", methods=["GET"])
@limiter.limit("30/minute")
async def proxy_sandbox_es(path: str, request: Request):
    """Forward read-only request to sandbox EventStore."""
    if not _is_es_path_allowed(path):
        raise HTTPException(status_code=403, detail=f"Path not allowed: /{path}")

    if not SANDBOX_ES_URL:
        raise HTTPException(status_code=503, detail="No sandbox event store is configured on this registry (SANDBOX_ES_INTERNAL_URL unset)")
    target_url = f"{SANDBOX_ES_URL}/{path}"
    fwd_headers = {}
    for key, value in request.headers.items():
        if key.lower() in _FORWARD_HEADERS or key.lower() == "x-internal-key":
            fwd_headers[key] = value

    # Forward query params
    query_string = str(request.url.query) if request.url.query else ""
    if query_string:
        target_url += f"?{query_string}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(target_url, headers=fwd_headers)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Sandbox EventStore timed out")
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Cannot reach sandbox EventStore")
    except Exception as e:
        logger.error(f"[SANDBOX-PROXY] ES error: {e}")
        raise HTTPException(status_code=502, detail=f"EventStore proxy error: {str(e)[:200]}")

    resp_headers = {}
    for key, value in resp.headers.items():
        if key.lower() in _RETURN_HEADERS:
            resp_headers[key] = value

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp_headers,
        media_type=resp.headers.get("content-type"),
    )
