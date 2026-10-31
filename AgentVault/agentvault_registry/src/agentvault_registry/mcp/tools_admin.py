"""
MCP Admin Tools — Commander-only sovereign gateway.

Eight tools exposing full access to:
  1. theprotocol.adminGetDeveloperToken  — Get developer JWT (no auth needed)
  2. theprotocol.adminRequest            — Any registry endpoint (~200+ routes)
  3. theprotocol.adminQueryEventStore    — EventStore immutable ledger
  4. theprotocol.adminPromQuery          — Prometheus PromQL queries
  5. theprotocol.adminGrafanaQuery       — Grafana HTTP API (dashboards, search, annotations)
  6. theprotocol.supportListTickets      — List support tickets by status
  7. theprotocol.supportReplyTicket      — Reply to a support ticket as admin
  8. theprotocol.supportCloseTicket      — Close/resolve a support ticket

All tools require is_admin=True on the MCPAuthContext.
Auth gate: require_admin_auth() raises MCPAuthError(-32001) if not admin.

Note: getDeveloperToken requires NO auth — it IS the auth step.
Pass its returned access_token as developer_jwt to adminRequest.

Usage:
    # Get developer JWT (step 1 — call this first, pass result to adminRequest)
    getDeveloperToken(email="commander@theprotocol.cloud", password="...")

    # Full registry proxy (pass developer_jwt inline to avoid bridge token limitation)
    adminRequest(method="GET", endpoint="/api/v1/admin/dashboard", developer_jwt="eyJ...")
    adminRequest(method="POST", endpoint="/api/v1/governance/proposals",
                 body={"title": "...", "description": "...", "duration_days": 7})

    # EventStore ledger query
    adminQueryEventStore(path="/api/v1/events/", params={"limit": 50})
    adminQueryEventStore(path="/api/v1/projections/stats")

    # Prometheus PromQL
    adminPromQuery(query="up")
    adminPromQuery(query="rate(http_requests_total[5m])", start="2026-03-06T00:00:00Z",
                   end="2026-03-06T01:00:00Z", step="60")

    # Grafana HTTP API
    adminGrafanaQuery(path="/api/health")
    adminGrafanaQuery(path="/api/search", params={"query": "system"})
    adminGrafanaQuery(path="/api/dashboards/uid/abc123")
    adminGrafanaQuery(path="/api/admin/stats")
"""
import base64
import binascii
import hashlib
import logging
import os
from datetime import timedelta
from typing import Dict, Any, Optional, List

import httpx

from ..config import settings
from ..core.observability_urls import grafana_url, prometheus_url
from ..es_ssl_helper import get_httpx_verify
from ..security import create_access_token
from .auth_bridge import MCPAuthContext, MCPAuthError, format_tool_exception
from .refusal import http_refusal, refusal_reason  # §MCPTEST30: a refusal carries its reason
from ..core.path_segment import seg  # §MCPTEST30 V0523: a caller's value is one path segment, encoded

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service URLs
# ---------------------------------------------------------------------------

REGISTRY_SELF_URL = getattr(settings, "REGISTRY_SELF_URL", "http://localhost:8000")
EVENT_STORE_URL   = getattr(settings, "EVENT_STORE_URL",   "http://event-store:8200")
EVENT_STORE_KEY   = getattr(settings, "EVENT_STORE_API_KEY",
                            "")
# §DOCSFIX D6-251 (2026-10-16): Prometheus and Grafana are read from the environment when a tool runs. Settings
# declares none of PROMETHEUS_URL, GRAFANA_URL, GRAFANA_ADMIN_USER or GRAFANA_ADMIN_PASS (it ignores unknown keys),
# so getattr(settings, ...) always answered its literal default and a registry's own values changed nothing.
# §SECBATCH wave 3 (2026-10-16): there is no default Grafana password. GRAFANA_ADMIN_PASS is read when the tool runs
# (_grafana_password), and while it is not configured the tool refuses and sends nothing.
GRAFANA_NOT_CONFIGURED = ("Grafana credentials not configured: set GRAFANA_ADMIN_PASS (the password of Grafana's admin "
                          "user) in this registry's environment. No request was sent.")


def _grafana_user() -> str:
    """The Grafana user adminGrafanaQuery signs in as: GRAFANA_ADMIN_USER (empty is unset), else admin."""
    return (os.getenv("GRAFANA_ADMIN_USER", "") or "").strip() or "admin"


def _grafana_password() -> str:
    """The password adminGrafanaQuery authenticates with: GRAFANA_ADMIN_PASS in the registry's environment; "" when it
    is not set or blank, and the tool then refuses."""
    return (os.getenv("GRAFANA_ADMIN_PASS", "") or "").strip()


HTTPX_TIMEOUT = 30.0
# §MCPTEST30 (V0552): the api-tester's routes outlast the 30 s above. One test-endpoint call seeds the tester's fixtures
# every time (APITestBase._populate_dynamic_ids, ~40 calls): 28 s and 36 s measured on sbx-alpha for a path that does not
# exist, so testApiEndpoint timed out on every endpoint (rounds 16 and 17: "Error: ReadTimeout"). A category, a flow or
# the federation suite runs for minutes (the MCP tester's own flow: 858 s); those are the task-capable tools.
API_TEST_ENDPOINT_TIMEOUT = 180.0
API_TEST_RUN_TIMEOUT = 1800.0
# §MCPTEST30 (V0554): the composite health checks call many endpoints of the same registry, so under load they outlast
# the 30 s above. Measured on the sandbox operators during the MCP tester's sweeps (rounds 18 and 19): getCombinedHealth
# 18-20 s and twice past 30 s (an idle call: 1.9 s), getAdminHealthCheckAuthenticated 32.8-37.9 s, getAdminWorkersStatus
# 25-35.6 s, getAdminHealthCheckPublicOnly 21-22 s. Until V0552 a timeout read as a refusal and passed; since, it reads 504.
# 55 s stays below the 60 s a caller's docker exec waits for an answer (docker-py's default socket timeout).
DIAGNOSTIC_TIMEOUT = 55.0


# ---------------------------------------------------------------------------
# Auth Guard
# ---------------------------------------------------------------------------

def require_admin_auth(ctx: MCPAuthContext) -> None:
    """Raise MCPAuthError if ctx is not an authenticated admin developer."""
    if not ctx.is_developer or not ctx.is_admin:
        raise MCPAuthError(
            "Admin access required. "
            "Provide an admin developer JWT from POST /api/v1/auth/login "
            "(account must have is_admin=True)."
        )


def _get_effective_jwt(ctx: MCPAuthContext) -> str:
    """
    Get a valid developer JWT from the auth context.

    If the raw_token is already a JWT, return it directly.
    If it's an API key (avreg_...), mint a short-lived JWT from the
    authenticated developer_id — safe because the API key was already validated.
    """
    if ctx.raw_token and not ctx.raw_token.startswith("avreg_"):
        return ctx.raw_token
    # API key auth — mint a short-lived JWT for internal calls
    return create_access_token(
        data={"sub": str(ctx.developer_id)},
        expires_delta=timedelta(minutes=5),
    )


# ---------------------------------------------------------------------------
# Tool 1: adminRequest — full registry proxy
# ---------------------------------------------------------------------------

async def get_developer_token(
    email: str,
    password: str,
) -> Dict[str, Any]:
    """
    Obtain a developer JWT via OAuth2 password flow.

    Calls POST /api/v1/auth/login with form-encoded credentials.
    No authentication required — this IS the authentication step.
    Pass the returned access_token as developer_jwt to adminRequest.

    Args:
        email    : Developer account email
        password : Developer account password

    Returns:
        { "access_token": <str>, "token_type": "bearer",
          "developer_id": <int>, "note": <str> }
    """
    url = f"{REGISTRY_SELF_URL}/api/v1/auth/login"
    logger.info(f"[AdminMCP] getDeveloperToken: email={email}")

    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            resp = await client.post(
                url,
                data={"username": email, "password": password},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        try:
            data = resp.json()
        except Exception:
            return {"error": f"Non-JSON response: {resp.text[:200]}"}

        if resp.status_code != 200:
            return {
                "error": f"Login failed (HTTP {resp.status_code})",
                "detail": data,
            }

        return {
            "access_token": data.get("access_token"),
            "token_type":   data.get("token_type", "bearer"),
            "developer_id": data.get("developer_id"),
            "note": (
                "JWT obtained. Pass access_token as the developer_jwt parameter "
                "to adminRequest to access all 200+ registry endpoints. "
                "Token valid for the session — no bridge reconfiguration needed."
            ),
        }

    except httpx.TimeoutException:
        return {"error": f"Login request timed out after {HTTPX_TIMEOUT}s"}
    except Exception as e:
        logger.error(f"[AdminMCP] getDeveloperToken error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# Headers a CALLER may set on the proxied request. ALLOWLIST, never passthrough.
# This proxy already carries an ADMIN bearer, so an arbitrary header dict would
# let a caller overwrite Authorization, or inject `X-Internal-Key` /
# `X-Mint-Proxy-Secret` and reach an internal-only surface with admin standing.
# Each entry earns its place:
#   idempotency-key    5 money rails REQUIRE it (`_require_idem`) and 400 without
#                      it — the org treasury's fund/remit/sweep and the org
#                      procurement rail. Until this existed, NO MCP caller could
#                      reach any of them, and the other 27 idempotency-AWARE
#                      routes could only be called unkeyed, so a retry moved
#                      money twice. Measured 2026-09-04 while driving the org
#                      treasury loop from the federation suite.
#   x-capability-token IRONKEY L4 attenuation. Can only NARROW authority —
#                      `resolve_capability` intersects caveats with the ISSUER's
#                      CURRENT authority — so it is safe to let a caller present.
#   if-none-match /    conditional reads (the agent-card pull-sync ETag path).
#   if-match           Cheap to allow, and a 304 is a real answer worth reaching.
_CALLER_HEADER_ALLOWLIST = frozenset({
    "idempotency-key", "x-capability-token", "if-none-match", "if-match",
})


def _upstream_error(status_code: int, response_data) -> Optional[str]:
    """Envelope key is `upstream_error`, never `error`: the admin dispatcher
    (server_admin._admin_result_payload / _format_result) renders any dict that carries
    `error` as a pure tool failure - isError:true, text only, structuredContent dropped -
    which is exactly how the V0221 envelope reached MCP clients as a bare string
    (found by agentvault2-07, 2026-09-05). The status_code/response/ok envelope IS the result.
    """
    """§B6 (2026-09-05, agentvault2-07's finding): the three escape-hatch wrappers returned
    HTTP 200 with the upstream failure INSIDE the envelope (`ok: false, status_code: 422`),
    so a caller that checks for an `error` key — every other tool's convention — believed a
    refused write had happened. A non-2xx now ALSO carries `upstream_error`, built from the upstream
    RFC 7807 body (`detail` / `title` / `message`) or its text, so "switched off", "not
    allowed" and "broken" read as three different sentences."""
    if status_code < 400:
        return None
    detail = None
    if isinstance(response_data, dict):
        for k in ("detail", "title", "message", "error"):
            v = response_data.get(k)
            if isinstance(v, str) and v.strip():
                detail = v.strip(); break
            if isinstance(v, (list, dict)) and v:
                detail = str(v)[:300]; break
    elif isinstance(response_data, str) and response_data.strip():
        detail = response_data.strip()[:300]
    return f"upstream HTTP {status_code}" + (f": {detail}" if detail else "")


async def admin_request(
    auth: MCPAuthContext,
    method: str,
    endpoint: str,
    body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    developer_jwt: Optional[str] = None,
    headers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Proxy any HTTP request to the registry API with admin authorization.

    Args:
        auth     : Must be admin developer context
        method   : HTTP method — GET | POST | PUT | DELETE | PATCH
        endpoint : Registry path, e.g. /api/v1/admin/dashboard
        body     : Optional JSON request body (for POST/PUT/PATCH)
        params   : Optional query parameters dict

    Returns:
        { "status_code": <int>, "endpoint": <str>, "method": <str>,
          "response": <JSON or text>, "ok": <bool> }
    """
    # If inline developer_jwt is provided, use it directly (OAuth connector flow).
    # Otherwise require admin auth from the bridge token.
    if developer_jwt:
        effective_token = developer_jwt
    elif auth:
        require_admin_auth(auth)
        effective_token = auth.raw_token
    else:
        raise MCPAuthError(
            "Admin authentication required. Either pass developer_jwt parameter "
            "(from adminGetDeveloperToken) or authenticate via bridge token."
        )

    method = method.upper()
    if method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
        return {"error": f"Unsupported HTTP method: {method}"}

    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint

    url = f"{REGISTRY_SELF_URL}{endpoint}"
    caller_headers = headers if isinstance(headers, dict) else {}
    headers = {
        "Authorization": f"Bearer {effective_token}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }
    # Merge AFTER the base so the allowlist decides what is settable, then report
    # what was dropped — a silently ignored header is how a caller comes to
    # believe it sent an idempotency key when it did not.
    _dropped = []
    for k, v in caller_headers.items():
        if str(k).lower() in _CALLER_HEADER_ALLOWLIST:
            headers[str(k)] = str(v)
        else:
            _dropped.append(str(k))
    if _dropped:
        logger.warning(
            "[AdminMCP] adminRequest dropped non-allowlisted header(s): %s "
            "(allowed: %s)", sorted(_dropped), sorted(_CALLER_HEADER_ALLOWLIST))

    logger.info(f"[AdminMCP] adminRequest: {method} {endpoint}")

    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            if method == "GET":
                resp = await client.get(url, params=params, headers=headers)
            elif method == "DELETE":
                resp = await client.delete(url, params=params, headers=headers)
            elif method == "POST":
                resp = await client.post(url, json=body, params=params, headers=headers)
            elif method == "PUT":
                resp = await client.put(url, json=body, params=params, headers=headers)
            elif method == "PATCH":
                resp = await client.patch(url, json=body, params=params, headers=headers)

        try:
            response_data = resp.json()
        except Exception:
            response_data = resp.text

        out = {
            "status_code": resp.status_code,
            "endpoint":    endpoint,
            "method":      method,
            "response":    response_data,
            "ok":          resp.status_code < 400,
        }
        err = _upstream_error(resp.status_code, response_data)
        if err:
            out["upstream_error"] = err
        return out

    except httpx.TimeoutException:
        logger.error(f"[AdminMCP] adminRequest timeout: {method} {endpoint}")
        return {"error": f"Request timed out after {HTTPX_TIMEOUT}s", "endpoint": endpoint}
    except Exception as e:
        logger.error(f"[AdminMCP] adminRequest error: {e}", exc_info=True)
        return {"error": str(e), "endpoint": endpoint}


# ---------------------------------------------------------------------------
# Tool 2: adminQueryEventStore — EventStore immutable ledger
# ---------------------------------------------------------------------------

async def admin_query_event_store(
    auth: MCPAuthContext,
    path: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Query the EventStore immutable ledger directly.

    Common paths:
        /api/v1/events/                              — all events (add ?limit=N)
        /api/v1/events/{id}                          — single event by ID
        /api/v1/events/aggregate/{aggregate_id}      — events for a DID
        /api/v1/projections/stats                    — global stats
        /api/v1/projections/balances                 — all agent balances
        /api/v1/projections/transactions/{agent_id}  — transaction history

    Args:
        auth   : Must be admin developer context
        path   : EventStore API path
        params : Optional query parameters dict
    """
    require_admin_auth(auth)

    if not path.startswith("/"):
        path = "/" + path

    url = f"{EVENT_STORE_URL}{path}"
    headers = {"X-Internal-Key": EVENT_STORE_KEY}

    logger.info(f"[AdminMCP] adminQueryEventStore: GET {path}")

    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            resp = await client.get(url, params=params, headers=headers)

        try:
            response_data = resp.json()
        except Exception:
            response_data = resp.text

        out = {
            "path":        path,
            "status_code": resp.status_code,
            "response":    response_data,
            "ok":          resp.status_code < 400,
        }
        err = _upstream_error(resp.status_code, response_data)
        if err:
            out["upstream_error"] = err
        return out

    except httpx.TimeoutException:
        return {"error": f"EventStore request timed out after {HTTPX_TIMEOUT}s", "path": path}
    except Exception as e:
        logger.error(f"[AdminMCP] adminQueryEventStore error: {e}", exc_info=True)
        return {"error": str(e), "path": path}


# ---------------------------------------------------------------------------
# Tool 3: adminPromQuery — Prometheus PromQL
# ---------------------------------------------------------------------------

async def admin_prom_query(
    auth: MCPAuthContext,
    query: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    step: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute a PromQL query against Prometheus.

    Instant query (no start/end): adminPromQuery(query="up")
    Range query: adminPromQuery(query="up", start="2026-03-06T00:00:00Z",
                                end="2026-03-06T01:00:00Z", step="60")

    Args:
        auth  : Must be admin developer context
        query : PromQL expression string
        start : ISO8601 start time (range query only)
        end   : ISO8601 end time (range query only)
        step  : Step in seconds as string (range query only, default "60")
    """
    require_admin_auth(auth)

    is_range = bool(start and end)

    if is_range:
        prom_path = "/api/v1/query_range"
        prom_params: Dict[str, Any] = {
            "query": query,
            "start": start,
            "end":   end,
            "step":  step or "60",
        }
    else:
        prom_path = "/api/v1/query"
        prom_params = {"query": query}

    url = f"{prometheus_url()}{prom_path}"
    logger.info(f"[AdminMCP] adminPromQuery: {'range' if is_range else 'instant'} — {query}")

    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            resp = await client.get(url, params=prom_params)

        if resp.status_code != 200:
            return {
                "error": f"Prometheus returned HTTP {resp.status_code}",
                "query": query,
                "raw":   resp.text[:500],
                "ok":    False,
            }

        data = resp.json()
        prom_status = data.get("status", "unknown")
        result_data = data.get("data", {})

        return {
            "query":       query,
            "query_type":  "range" if is_range else "instant",
            "status":      prom_status,
            "result_type": result_data.get("resultType", "unknown"),
            "result":      result_data.get("result", []),
            "ok":          prom_status == "success",
        }

    except httpx.TimeoutException:
        return {"error": f"Prometheus request timed out after {HTTPX_TIMEOUT}s", "query": query}
    except Exception as e:
        logger.error(f"[AdminMCP] adminPromQuery error: {e}", exc_info=True)
        return {"error": str(e), "query": query}


# ---------------------------------------------------------------------------
# Tool 4: adminGrafanaQuery — Grafana HTTP API
# ---------------------------------------------------------------------------

async def admin_grafana_query(
    auth: MCPAuthContext,
    path: str,
    method: str = "GET",
    body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Query the Grafana HTTP API using admin Basic Auth credentials.

    Common GET paths:
        /api/health                        — Grafana health status
        /api/admin/stats                   — Server statistics (users, dashboards, orgs, etc.)
        /api/search                        — Search all dashboards (?query=keyword)
        /api/dashboards/home               — Home dashboard
        /api/dashboards/uid/{uid}          — Full dashboard JSON by UID
        /api/annotations                   — All annotations
        /api/datasources                   — All configured datasources
        /api/org/users                     — Organisation users
        /api/folders                       — Dashboard folders

    Common POST paths:
        /api/ds/query                      — Run raw datasource query (PromQL or SQL)

    Args:
        auth   : Must be admin developer context
        path   : Grafana API path, e.g. /api/search
        method : HTTP method — GET (default), POST, DELETE
        body   : Optional JSON body for POST requests
        params : Optional query parameters dict, e.g. {"query": "system"} for /api/search

    Returns:
        { "path": <str>, "status_code": <int>, "response": <JSON or text>, "ok": <bool> }
    """
    require_admin_auth(auth)

    password = _grafana_password()
    if not password:
        return {"error": GRAFANA_NOT_CONFIGURED, "path": path}

    method = method.upper()
    if not path.startswith("/"):
        path = "/" + path

    url = f"{grafana_url()}{path}"
    # Grafana HTTP API accepts HTTP Basic Auth
    auth_tuple = (_grafana_user(), password)

    logger.info(f"[AdminMCP] adminGrafanaQuery: {method} {path}")

    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, auth=auth_tuple) as client:
            if method == "GET":
                resp = await client.get(url, params=params)
            elif method == "POST":
                resp = await client.post(url, json=body, params=params)
            elif method == "DELETE":
                resp = await client.delete(url, params=params)
            else:
                return {
                    "error": f"Unsupported method: {method}. Use GET, POST, or DELETE.",
                    "path":  path,
                }

        try:
            response_data = resp.json()
        except Exception:
            response_data = resp.text

        out = {
            "path":        path,
            "status_code": resp.status_code,
            "response":    response_data,
            "ok":          resp.status_code < 400,
        }
        err = _upstream_error(resp.status_code, response_data)
        if err:
            out["upstream_error"] = err
        return out

    except httpx.TimeoutException:
        return {"error": f"Grafana request timed out after {HTTPX_TIMEOUT}s", "path": path}
    except Exception as e:
        logger.error(f"[AdminMCP] adminGrafanaQuery error: {e}", exc_info=True)
        return {"error": str(e), "path": path}


# ---------------------------------------------------------------------------
# Tool 5: supportListTickets — List support tickets
# ---------------------------------------------------------------------------

async def support_list_tickets(
    auth: MCPAuthContext,
    status: str = "open",
) -> Dict[str, Any]:
    """
    List support tickets. Filter by status or show all.

    Args:
        auth   : Must be admin developer context
        status : Filter — "open", "in_progress", "resolved", "closed", "all" (default "open")

    Returns:
        List of tickets with key fields.
    """
    require_admin_auth(auth)

    valid_statuses = ("open", "in_progress", "resolved", "closed", "all")
    if status not in valid_statuses:
        return {"error": f"Invalid status '{status}'. Must be one of: {', '.join(valid_statuses)}"}

    endpoint = "/api/v1/admin/support/tickets"
    params = {}
    if status != "all":
        params["status"] = status

    url = f"{REGISTRY_SELF_URL}{endpoint}"
    effective_token = _get_effective_jwt(auth)
    headers = {
        "Authorization": f"Bearer {effective_token}",
        "Accept": "application/json",
    }

    logger.info(f"[AdminMCP] supportListTickets: status={status}")

    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            resp = await client.get(url, params=params, headers=headers)

        try:
            response_data = resp.json()
        except Exception:
            response_data = resp.text

        if resp.status_code >= 400:
            return {
                "error": f"Failed to list tickets (HTTP {resp.status_code})",
                "detail": response_data,
                "ok": False,
            }

        # Format ticket summaries for readability
        tickets = response_data if isinstance(response_data, list) else response_data.get("tickets", response_data)
        if isinstance(tickets, list):
            summaries = []
            for t in tickets:
                summaries.append({
                    "id": t.get("id"),
                    "subject": t.get("subject"),
                    "category": t.get("category"),
                    "status": t.get("status"),
                    "priority": t.get("priority"),
                    "developer_email": t.get("developer_email") or t.get("developer", {}).get("email") if isinstance(t.get("developer"), dict) else t.get("developer_email"),
                    "message_count": t.get("message_count", t.get("reply_count", 0)),
                    "last_activity": t.get("last_activity") or t.get("updated_at"),
                    "created_at": t.get("created_at"),
                })
            return {
                "status_filter": status,
                "total": len(summaries),
                "tickets": summaries,
                "ok": True,
            }

        return {
            "status_filter": status,
            "response": response_data,
            "ok": True,
        }

    except httpx.TimeoutException:
        return {"error": f"Request timed out after {HTTPX_TIMEOUT}s"}
    except Exception as e:
        logger.error(f"[AdminMCP] supportListTickets error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ---------------------------------------------------------------------------
# Tool 6: supportReplyTicket — Reply to a support ticket as admin
# ---------------------------------------------------------------------------

async def support_reply_ticket(
    auth: MCPAuthContext,
    ticket_id: int,
    message: str,
) -> Dict[str, Any]:
    """
    Reply to a support ticket as admin. Automatically notifies the user via broadcast.

    Args:
        auth      : Must be admin developer context
        ticket_id : ID of the ticket to reply to
        message   : Reply message text

    Returns:
        Confirmation with ticket status.
    """
    require_admin_auth(auth)

    if not message or not message.strip():
        return {"error": "Message cannot be empty"}

    endpoint = f"/api/v1/admin/support/tickets/{seg(ticket_id)}/reply"
    url = f"{REGISTRY_SELF_URL}{endpoint}"
    effective_token = _get_effective_jwt(auth)
    headers = {
        "Authorization": f"Bearer {effective_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {"message": message}

    logger.info(f"[AdminMCP] supportReplyTicket: ticket_id={ticket_id}")

    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            resp = await client.post(url, json=body, headers=headers)

        try:
            response_data = resp.json()
        except Exception:
            response_data = resp.text

        if resp.status_code >= 400:
            return {
                "error": f"Failed to reply to ticket #{ticket_id} (HTTP {resp.status_code})",
                "detail": response_data,
                "ok": False,
            }

        return {
            "ticket_id": ticket_id,
            "action": "reply_sent",
            "response": response_data,
            "ok": True,
        }

    except httpx.TimeoutException:
        return {"error": f"Request timed out after {HTTPX_TIMEOUT}s"}
    except Exception as e:
        logger.error(f"[AdminMCP] supportReplyTicket error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ---------------------------------------------------------------------------
# Tool 7: supportCloseTicket — Close or resolve a support ticket
# ---------------------------------------------------------------------------

async def support_close_ticket(
    auth: MCPAuthContext,
    ticket_id: int,
    status: str = "resolved",
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Close or resolve a support ticket. Optionally send a final reply before closing.

    Args:
        auth      : Must be admin developer context
        ticket_id : ID of the ticket to close
        status    : Target status — "resolved" or "closed" (default "resolved")
        message   : Optional final reply message (sent before status change)

    Returns:
        Confirmation with final ticket status.
    """
    require_admin_auth(auth)

    valid_statuses = ("resolved", "closed")
    if status not in valid_statuses:
        return {"error": f"Invalid status '{status}'. Must be one of: {', '.join(valid_statuses)}"}

    effective_token = _get_effective_jwt(auth)
    headers = {
        "Authorization": f"Bearer {effective_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    logger.info(f"[AdminMCP] supportCloseTicket: ticket_id={ticket_id} status={status} with_message={bool(message)}")

    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            # Step 1: Send reply if message provided
            if message and message.strip():
                reply_url = f"{REGISTRY_SELF_URL}/api/v1/admin/support/tickets/{seg(ticket_id)}/reply"
                reply_resp = await client.post(reply_url, json={"message": message}, headers=headers)

                if reply_resp.status_code >= 400:
                    try:
                        reply_data = reply_resp.json()
                    except Exception:
                        reply_data = reply_resp.text
                    return {
                        "error": f"Failed to send reply before closing ticket #{ticket_id} (HTTP {reply_resp.status_code})",
                        "detail": reply_data,
                        "ok": False,
                    }

            # Step 2: Update ticket status
            status_url = f"{REGISTRY_SELF_URL}/api/v1/admin/support/tickets/{seg(ticket_id)}/status"
            status_resp = await client.post(status_url, json={"status": status}, headers=headers)

        try:
            status_data = status_resp.json()
        except Exception:
            status_data = status_resp.text

        if status_resp.status_code >= 400:
            return {
                "error": f"Failed to update ticket #{ticket_id} status to '{status}' (HTTP {status_resp.status_code})",
                "detail": status_data,
                "reply_sent": bool(message and message.strip()),
                "ok": False,
            }

        return {
            "ticket_id": ticket_id,
            "action": f"ticket_{status}",
            "reply_sent": bool(message and message.strip()),
            "response": status_data,
            "ok": True,
        }

    except httpx.TimeoutException:
        return {"error": f"Request timed out after {HTTPX_TIMEOUT}s"}
    except Exception as e:
        logger.error(f"[AdminMCP] supportCloseTicket error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ===========================================================================
# §pass70 Sprint 3 — Admin tools (10 new — first-class versions of hot adminRequest paths)
# ===========================================================================

async def _admin_get(auth: MCPAuthContext, path: str, params: Optional[Dict[str, Any]] = None,
                     timeout: float = HTTPX_TIMEOUT) -> Dict[str, Any]:
    """Internal helper: GET against registry API with admin JWT."""
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    url = f"{REGISTRY_SELF_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=get_httpx_verify()) as client:
            r = await client.get(url, params=params, headers={"Authorization": f"Bearer {effective_token}"})
        if r.status_code != 200:
            # B6 (§BATCH4 addendum, found by agentvault2-07 on a740cab7b297): the dispatcher renders
            # ANY dict carrying `error` as a pure tool failure and DROPS the rest, so `detail` (the
            # RFC 7807 body, the gate phrase a caller classifies on) never reached anyone. The same
            # contract as adminRequest: status + message + body, under a key the dispatcher leaves alone.
            return {"status_code": r.status_code, "upstream_error": http_refusal(f"{path}", r),
                    "detail": r.text[:300], "path": path}
        return r.json()
    except Exception as e:
        logger.error(f"_admin_get({path}) error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_reactor_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Live reactor framework status — per-reactor enabled flag, last fired, error counts, throttle state."""
    return await _admin_get(auth, "/api/v1/admin/reactor/status")


async def get_event_emission_policies(auth: MCPAuthContext) -> Dict[str, Any]:
    """List all event_emission_policies rows (f037 partition gate). Per event_type: emit_from_teg, emit_from_registry, skip_in_projection."""
    body = await _admin_get(auth, "/api/v1/admin/event-emission-policies")
    if isinstance(body, list):
        return {"policies": body, "total": len(body)}
    return body


async def set_event_emission_policy(
    auth: MCPAuthContext,
    event_type: str,
    emit_from_teg: Optional[bool] = None,
    emit_from_registry: Optional[bool] = None,
    skip_in_projection: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Update an event-type's emission policy (f037). DANGEROUS — wrong values can cause supply invariant drift.
    Only set fields you intend to change (others left unchanged). Requires admin treasury flag.
    """
    require_admin_auth(auth)
    if not event_type:
        return {"error": "event_type is required"}
    body: Dict[str, Any] = {}
    if emit_from_teg is not None:
        body["emit_from_teg"] = emit_from_teg
    if emit_from_registry is not None:
        body["emit_from_registry"] = emit_from_registry
    if skip_in_projection is not None:
        body["skip_in_projection"] = skip_in_projection
    if not body:
        return {"error": "at least one of emit_from_teg, emit_from_registry, skip_in_projection must be provided"}
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            r = await client.put(
                f"{REGISTRY_SELF_URL}/api/v1/admin/event-emission-policies/{seg(event_type)}",
                json=body,
                headers={"Authorization": f"Bearer {effective_token}", "Content-Type": "application/json"},
            )
        if r.status_code in (200, 201):
            return r.json()
        return {"error": f"setPolicy failed HTTP {r.status_code}: {r.text[:300]}"}
    except Exception as e:
        logger.error(f"setEventEmissionPolicy error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_cloud_operators(auth: MCPAuthContext) -> Dict[str, Any]:
    """List cloud-provisioned operator registries (status, region, public_url, mTLS state)."""
    return await _admin_get(auth, "/api/v1/admin/cloud-operators")


async def get_admin_agents(auth: MCPAuthContext, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """Admin view of all agents (cross-developer). Paginated."""
    return await _admin_get(auth, "/api/v1/admin/agents", params={"limit": min(max(limit,1),200), "offset": max(offset,0)})


async def get_admin_dashboard(auth: MCPAuthContext) -> Dict[str, Any]:
    """High-level dashboard counts: developers, agents, bootstrap tokens, recent activity."""
    return await _admin_get(auth, "/api/v1/admin/dashboard")


async def get_treasury_aggregate(auth: MCPAuthContext) -> Dict[str, Any]:
    """Frame-aware treasury + fee_collector aggregate snapshot (Build #7 surface)."""
    return await _admin_get(auth, "/api/v1/admin/treasury/aggregate")


async def trigger_projection_snapshot(auth: MCPAuthContext) -> Dict[str, Any]:
    """
    Take a ProjectionSnapshot event from current TEG balances as new baseline.
    Requires ENABLE_PROJECTION_SNAPSHOTS=true env var. Operational tool — only run when needed to eliminate
    drift from historical pollution. Requires admin_treasury flag.
    """
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/admin/projection-snapshot",
                headers={"Authorization": f"Bearer {effective_token}", "Content-Type": "application/json"},
                json={},
            )
        if r.status_code in (200, 201):
            return r.json()
        return {"error": f"projection-snapshot failed HTTP {r.status_code}: {r.text[:300]}"}
    except Exception as e:
        logger.error(f"triggerProjectionSnapshot error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def trigger_supply_audit(auth: MCPAuthContext) -> Dict[str, Any]:
    """Run the self-consistent supply invariant audit. Returns tokens_issued vs total_circulating + delta + OK/BREACH status."""
    return await _admin_get(auth, "/api/v1/admin/simulation/supply-audit")


async def get_admin_broadcasts(auth: MCPAuthContext) -> Dict[str, Any]:
    """List admin broadcasts (system-wide notices and recent platform activity feed)."""
    return await _admin_get(auth, "/api/v1/admin/broadcasts")


# ===========================================================================
# §pass70 Sprint 4 — Admin (14 new): canary, federation, email, developers
# ===========================================================================

async def _admin_post(auth: MCPAuthContext, path: str, json_body: Optional[Dict[str, Any]] = None,
                      timeout: float = HTTPX_TIMEOUT) -> Dict[str, Any]:
    """Internal helper: POST against registry API with admin JWT."""
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=get_httpx_verify()) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}{path}",
                json=json_body or {},
                headers={"Authorization": f"Bearer {effective_token}", "Content-Type": "application/json"},
            )
        if r.status_code in (200, 201, 204):
            try:
                return r.json()
            except Exception:
                return {"status": "ok"}
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    except Exception as e:
        logger.error(f"_admin_post({path}) error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_admin_developers(auth: MCPAuthContext, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """List all developers (admin view). Paginated."""
    return await _admin_get(auth, "/api/v1/admin/developers", params={"limit": min(max(limit,1),200), "offset": max(offset,0)})


async def get_canary_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Full canary system dashboard: per-path stats, 24h/5m pass rates, frame deltas, recent failures."""
    return await _admin_get(auth, "/api/v1/admin/canary/status")


async def get_canary_results(auth: MCPAuthContext, limit: int = 50, path_id: Optional[int] = None) -> Dict[str, Any]:
    """Recent canary test results, filterable by path_id."""
    params: Dict[str, Any] = {"limit": min(max(limit,1),500)}
    if path_id is not None:
        params["path_id"] = path_id
    return await _admin_get(auth, "/api/v1/admin/canary/results", params=params)


async def fire_canary_path(auth: MCPAuthContext, path_id: int) -> Dict[str, Any]:
    """Manually fire a canary transfer for a given path_id (bypasses normal interval). Useful for on-demand health checks."""
    if path_id is None:
        return {"error": "path_id is required"}
    return await _admin_post(auth, "/api/v1/admin/canary/fire", json_body={"path_id": path_id})


async def toggle_canary_path(auth: MCPAuthContext, path_id: int) -> Dict[str, Any]:
    """Toggle a canary path's active state (pause / unpause)."""
    if path_id is None:
        return {"error": "path_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/canary/path/{seg(path_id)}/toggle")


async def set_canary_maintenance(
    auth: MCPAuthContext,
    enable: bool,
    scope: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """
    Set canary path active state. enable=False puts paths into maintenance (paused);
    enable=True returns them to normal firing. scope='all' (default) or list of path_ids.
    """
    body: Dict[str, Any] = {
        "enable": enable,
        "scope": scope if scope is not None else "all",
    }
    return await _admin_post(auth, "/api/v1/admin/canary/maintenance", json_body=body)


# ── §V0047 Canary Cockpit fleet tools (V0045 backend) ──────────────────────
# registry-a (CANARY_RUNNER_MODE=master) schedules the whole fleet's canaries;
# these wrap the cockpit control plane: one-button fleet pause/resume, the fleet
# scheduling status (federated paths + last dispatch + 24h outcomes), and the
# master schedule upsert for peer-homed paths.

async def admin_canary_fleet_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Cockpit single pane: mode, fleet-pause flag, local path counts, every federated
    schedule row with its last dispatch, and 24h dispatch outcomes per home."""
    return await _admin_get(auth, "/api/v1/admin/canary/fleet/status")


async def admin_canary_fleet_pause(auth: MCPAuthContext) -> Dict[str, Any]:
    """Pause ALL canary scheduling fleet-wide (the one-button silent box). New cycles
    stop within one runner tick; the in-flight dispatch tail drains in under ~30s.
    Symmetric — never touches canary_paths.is_active."""
    return await _admin_post(auth, "/api/v1/admin/canary/fleet/pause", json_body={})


async def admin_canary_fleet_resume(auth: MCPAuthContext) -> Dict[str, Any]:
    """Resume canary scheduling fleet-wide (clears the master pause flag)."""
    return await _admin_post(auth, "/api/v1/admin/canary/fleet/resume", json_body={})


async def admin_canary_fleet_upsert_remote_paths(
    auth: MCPAuthContext,
    paths: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Upsert master schedule rows for peer-homed canary paths. Each item:
    {home_registry, remote_path_id, path_label?, interval_sec?, is_active?, notes?} —
    home_registry must match a peer_registries.name (dispatch target resolution)."""
    if not isinstance(paths, list) or not paths:
        return {"error": "paths (non-empty list) is required"}
    return await _admin_post(auth, "/api/v1/admin/canary/fleet/remote-paths", json_body={"paths": paths})


async def preview_admin_email(auth: MCPAuthContext, template: str) -> Dict[str, Any]:
    """Preview an admin email template (rendered HTML). Useful for verifying template changes."""
    if not template:
        return {"error": "template is required (e.g. 'welcome', 'funding_approved')"}
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/admin/email/preview/{seg(template)}",
                headers={"Authorization": f"Bearer {effective_token}", "Accept": "text/html"},
            )
        if r.status_code == 200:
            return {"template": template, "content_type": r.headers.get("content-type"), "html_length_bytes": len(r.text), "html_preview": r.text[:1500]}
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    except Exception as e:
        logger.error(f"previewAdminEmail error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_pending_peer_registries(auth: MCPAuthContext) -> Dict[str, Any]:
    """List peer registry applications awaiting admin approval."""
    return await _admin_get(auth, "/api/v1/admin/federation/peers/pending")


async def approve_peer_registry(auth: MCPAuthContext, peer_id: str) -> Dict[str, Any]:
    """Approve a pending peer registry application. Activates federation sync."""
    if not peer_id:
        return {"error": "peer_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/federation/peers/{seg(peer_id)}/approve")


async def reject_peer_registry(auth: MCPAuthContext, peer_id: str) -> Dict[str, Any]:
    """Reject a pending peer registry application."""
    if not peer_id:
        return {"error": "peer_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/federation/peers/{seg(peer_id)}/reject")


async def deactivate_peer_registry(auth: MCPAuthContext, peer_id: str) -> Dict[str, Any]:
    """Deactivate an active peer registry (stops federation sync, keeps row). Reversible via reactivate."""
    if not peer_id:
        return {"error": "peer_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/federation/peers/{seg(peer_id)}/deactivate")


async def reactivate_peer_registry(auth: MCPAuthContext, peer_id: str) -> Dict[str, Any]:
    """Reactivate a previously-deactivated peer registry."""
    if not peer_id:
        return {"error": "peer_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/federation/peers/{seg(peer_id)}/reactivate")


async def get_federation_sync_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Federation sync subsystem health: last sync timestamps, per-peer status, drift counters."""
    return await _admin_get(auth, "/api/v1/admin/federation-sync/status")


async def get_federation_sync_peers(auth: MCPAuthContext) -> Dict[str, Any]:
    """Per-peer federation sync detail (compliance score, drift events, last successful sync)."""
    body = await _admin_get(auth, "/api/v1/admin/federation-sync/peers")
    if isinstance(body, list):
        return {"peers": body, "total": len(body)}
    return body


# ===========================================================================
# §pass70 Sprint 5 — Admin (12 new)
# ===========================================================================

async def get_enforcement_policy(auth: MCPAuthContext) -> Dict[str, Any]:
    """Active enforcement policy (offense thresholds, slash multipliers, version, modified_by). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/enforcement/policy")


async def get_enforcement_pending(auth: MCPAuthContext) -> Dict[str, Any]:
    """List pending enforcement actions awaiting admin approval (warn/suspend/slash queue). Admin only."""
    body = await _admin_get(auth, "/api/v1/admin/enforcement/pending")
    if isinstance(body, dict) and "items" in body:
        return body
    if isinstance(body, list):
        return {"items": body, "total": len(body)}
    return body


async def get_enforcement_agent_status(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Full enforcement status summary for an agent: offense history, current state, rewards-paused flag, stake at risk. Admin only."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _admin_get(auth, f"/api/v1/admin/enforcement/agents/{seg(agent_did)}/status")


async def get_collusion_rings(
    auth: MCPAuthContext,
    severity: Optional[str] = None,
    agent_did: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """List detected collusion rings (Tarjan SCC analysis). Optional severity/agent_did/since/limit filters. Admin only."""
    params: Dict[str, Any] = {"limit": min(max(int(limit), 1), 200)}
    if severity:
        params["severity"] = severity
    if agent_did:
        params["agent_did"] = agent_did
    if since:
        params["since"] = since
    return await _admin_get(auth, "/api/v1/admin/collusion/rings", params=params)


async def get_cross_teg_sweeper_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Cross-TEG 2PC sweeper subsystem status: fleet-wide cycles, aborts, resumes, pending count, per-op breakdown. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/cross-teg-sweeper/status")


async def get_canary_judge_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Canary judge worker status: 24h pass/fail, per-path stats, in-flight count, by-failure-type breakdown. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/canary-judge/status")


async def get_canary_rebalancer_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Canary fund rebalancer status: cycles, AVT disbursed 24h, agents under floor, per-home-kind breakdown. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/canary-rebalancer/status")


async def get_saga_timeout_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Saga timeout worker status: settlements timed out 24h, cross-frame refunds, settlement/cross-frame cycles, errors. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/saga-timeout/status")


async def get_agent_card_drift_list(auth: MCPAuthContext, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """List agent-card drift state across the federated mesh (paginated). Returns {items: [...]} with per-agent drift records. Admin only."""
    return await _admin_get(
        auth, "/api/v1/admin/agent-card-drift",
        params={"limit": min(max(int(limit), 1), 200), "offset": max(int(offset), 0)},
    )


async def get_invite_codes(
    auth: MCPAuthContext,
    status_filter: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """List invite codes for developer signup gating. Optional status_filter (active / used / expired). Admin only."""
    params: Dict[str, Any] = {"limit": min(max(int(limit), 1), 500), "offset": max(int(offset), 0)}
    if status_filter:
        params["status_filter"] = status_filter
    body = await _admin_get(auth, "/api/v1/admin/invite-codes", params=params)
    if isinstance(body, list):
        return {"invite_codes": body, "total": len(body)}
    return body


async def get_admin_funding_pending(auth: MCPAuthContext) -> Dict[str, Any]:
    """List pending agent funding requests awaiting admin approval. Admin only."""
    body = await _admin_get(auth, "/api/v1/admin/funding/pending")
    if isinstance(body, list):
        return {"pending": body, "total": len(body)}
    return body


async def get_eventstore_balances(auth: MCPAuthContext) -> Dict[str, Any]:
    """EventStore-derived agent balance projections (vs TEG ledger). Useful for reconciliation checks. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/eventstore-balances")


# ===========================================================================
# §pass70 Sprint 6 — Admin (13 new)
# ===========================================================================

async def get_canary_ironhand_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """IRONHAND mTLS canary status (active paths, 24h pass/fail, pass_rate, registries reporting). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/canary-ironhand/status")


async def get_canary_ironhand_events(auth: MCPAuthContext, limit: int = 50) -> Dict[str, Any]:
    """IRONHAND mTLS canary fire history (paginated). Each event has test_id, path_human, transport, fired_iso, outcome. Admin only."""
    return await _admin_get(
        auth, "/api/v1/admin/canary-ironhand/events",
        params={"limit": min(max(int(limit), 1), 500)},
    )


async def get_agent_health_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Agent-health worker status: 24h cycles, probes, state_changes, registries_reporting, agent counts by health state. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/agent-health/status")


async def get_cicd_summary(auth: MCPAuthContext) -> Dict[str, Any]:
    """CI/CD fleet summary: pipeline/version/deployment counts over a 24h window. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/cicd/summary")


async def get_cicd_deployments(auth: MCPAuthContext, limit: int = 50) -> Dict[str, Any]:
    """Recent CI/CD deployments fleet-wide: agent_did, deployment_type, environment, status, timestamps. Admin only."""
    return await _admin_get(
        auth, "/api/v1/admin/cicd/deployments",
        params={"limit": min(max(int(limit), 1), 200)},
    )


async def get_webhook_aggregate(auth: MCPAuthContext) -> Dict[str, Any]:
    """Cluster-wide webhook health snapshot: total/active/inactive webhooks, developers with webhooks, deliveries_in_window. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/webhooks/aggregate")


async def get_recent_webhook_deliveries(
    auth: MCPAuthContext,
    status: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Recent webhook delivery attempts (success/failure) across the cluster. Optional status / event_type filters. Admin only."""
    params: Dict[str, Any] = {"limit": min(max(int(limit), 1), 500)}
    if status:
        params["status_filter"] = status   # §MCPTEST30 (2026-10-01): the survey's UNDECLARED class: the route reads `status_filter`
    if event_type:
        params["event_type"] = event_type
    return await _admin_get(auth, "/api/v1/admin/webhooks/recent-deliveries", params=params)


async def get_reward_funding_policy(auth: MCPAuthContext) -> Dict[str, Any]:
    """Reward funding waterfall policy: per-reason ordered list of funding sources (fee_collector / treasury). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/reward-funding/policy")


async def get_eventstore_stats(auth: MCPAuthContext) -> Dict[str, Any]:
    """EventStore projection stats: total_events, unique_agents, per-event-type counts. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/eventstore-stats")


async def get_eventstore_recent(auth: MCPAuthContext, limit: int = 15) -> Dict[str, Any]:
    """The most recent events the registry keeps in its cache (the last 15): type, aggregate_id, payload. Admin only.

    §MCPTEST30 (2026-10-01): the survey's UNDECLARED class: the route takes no `limit` (it serves its cache's last 15), so the tool's
    `limit` was dropped and 500 was promised; the tool now trims what the route serves, and says how many it keeps."""
    body = await _admin_get(auth, "/api/v1/admin/eventstore-recent")
    if isinstance(body, list):
        events = body[:min(max(int(limit), 1), 15)]
        return {"events": events, "total": len(events), "cache_window": 15}
    return body


async def get_admin_audit_logs(
    auth: MCPAuthContext,
    event_type: Optional[str] = None,
    actor_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    since_hours: Optional[int] = None,
) -> Dict[str, Any]:
    """List security audit log entries (all actors, all event types). Optional filters: event_type, actor_type, and the
    window since_hours (1-720; the route reads 24 when it is not given). Paginated. Admin only.

    §MCPTEST30 V0614 (2026-10-14): the route always took since_hours and the tool never passed it, so a caller could not
    look past one day: the tester's partition probe over the system actor read NOT MEASURED whenever the day held fewer
    than its rows (sbx-alpha's only system rows are the sandbox sim's breaker trips, and the sim stopped 10-12)."""
    params: Dict[str, Any] = {"limit": min(max(int(limit), 1), 500), "offset": max(int(offset), 0)}
    if event_type:
        params["event_type"] = event_type
    if actor_type:
        params["actor_type"] = actor_type
    if since_hours is not None:
        params["since_hours"] = min(max(int(since_hours), 1), 720)
    return await _admin_get(auth, "/api/v1/admin/audit-logs", params=params)


async def get_fee_collector_info(auth: MCPAuthContext) -> Dict[str, Any]:
    """Fee collector dashboard: balance, recent_distributions, total_collected_7d, per-asset breakdown. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/fee-collector/info")


async def get_diagnostic_checks(auth: MCPAuthContext) -> Dict[str, Any]:
    """List the Command Center's diagnostic checks (check_id, title, description, category, cost_ms): supply-audit,
    leader-election, svid-expiry, frame-trust-bundle and frame-teg-health on this registry itself, and the container
    checks (identity network, nginx config, pgbouncer, SPIRE rotation, DNS errors) on operators it can reach. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/diagnostics/checks")


# ===========================================================================
# §pass70 Sprint 7 — Admin (10 new)
# ===========================================================================

async def get_diagnostic_targets(auth: MCPAuthContext) -> Dict[str, Any]:
    """List diagnostic targets: this registry itself (is_self: role "frame", or "operator" on an operator registry), then
    its operators (from its own peer rows, and their containers under fleet scope).
    Each entry: operator_id, display_name, frame, role, status, last_snapshot_at; reason/reason_code say why no operator
    is listed, containers_reason/containers_reason_code why the container checks cannot run here. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/diagnostics/targets")


async def get_diagnostic_actions(auth: MCPAuthContext) -> Dict[str, Any]:
    """List the remediation actions (nginx-reload, teg-restart: this frame's own operators only) with their destructive
    flag and the check each re-runs afterwards. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/diagnostics/actions")


async def get_broadcast_templates(auth: MCPAuthContext) -> Dict[str, Any]:
    """List admin broadcast email templates (id, name, subject, body preview). Admin only."""
    body = await _admin_get(auth, "/api/v1/admin/broadcast-templates")
    if isinstance(body, list):
        return {"templates": body, "total": len(body)}
    return body


async def get_agent_card_pullsync_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Agent-card pull-sync worker status: last cycle, duration_ms, last_stats, leader status. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/agent-card-pullsync/status")


async def get_agent_card_pullsync_events(auth: MCPAuthContext, limit: int = 50) -> Dict[str, Any]:
    """Recent AgentCardPulled events from federated peers (paginated). Admin only."""
    return await _admin_get(
        auth, "/api/v1/admin/agent-card-pullsync/events",
        params={"limit": min(max(int(limit), 1), 200)},
    )


async def get_admin_mcp_audit_log_by_actor(
    auth: MCPAuthContext,
    actor_id: str,
    limit: int = 50,
    cursor: Optional[str] = None,
) -> Dict[str, Any]:
    """Admin view of MCP tool call audit log for a specific actor (developer_id or agent DID). Required actor_id. Paged by
    `cursor` (the id of the last row of the previous page). Admin only.

    §MCPTEST30 (2026-10-01): the survey's UNDECLARED class: it sent `offset` to a route paged by `cursor`, so every page was the first."""
    if not actor_id:
        return {"error": "actor_id is required"}
    params: Dict[str, Any] = {"actor_id": actor_id, "limit": min(max(int(limit), 1), 200)}
    if cursor:
        params["cursor"] = cursor
    return await _admin_get(auth, "/api/v1/admin/mcp-audit-log", params=params)


async def get_admin_health_check_simple(auth: MCPAuthContext) -> Dict[str, Any]:
    """Simple registry health-check (status, timestamp, service, version). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/health-check/simple")


async def get_admin_health_check_public_only(auth: MCPAuthContext) -> Dict[str, Any]:
    """Health check across public endpoints only. Returns overall + per-group + per-endpoint status. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/health-check/public-only", timeout=DIAGNOSTIC_TIMEOUT)


async def get_admin_health_check_authenticated(auth: MCPAuthContext) -> Dict[str, Any]:
    """Health check across authenticated endpoints (developer + admin). Returns overall + per-group + per-endpoint status. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/health-check/authenticated", timeout=DIAGNOSTIC_TIMEOUT)


async def get_admin_test_tokens(auth: MCPAuthContext) -> Dict[str, Any]:
    """Generate short-lived test tokens (developer + agent JWT) for health-check + smoke-test usage. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/test-tokens")


# ===========================================================================
# §pass70 Sprint 8 — Admin (10 new — 3 read-only + 7 destructive-with-warnings)
# ===========================================================================

# ── SAFE (read-only) ─────────────────────────────────────────────────────

async def get_admin_funding_all(auth: MCPAuthContext) -> Dict[str, Any]:
    """List ALL agent funding requests (pending + approved + rejected + funded). Extends Sprint 5's pending-only view. Admin only."""
    body = await _admin_get(auth, "/api/v1/admin/funding/all")
    if isinstance(body, list):
        return {"requests": body, "total": len(body)}
    return body


async def get_agent_health_transitions(auth: MCPAuthContext, limit: int = 100) -> Dict[str, Any]:
    """List recent agent health state transitions (healthy→unhealthy/unreachable→…). Paginated. Admin only."""
    return await _admin_get(
        auth, "/api/v1/admin/agent-health/transitions",
        params={"limit": min(max(int(limit), 1), 200)},
    )


async def get_combined_health(auth: MCPAuthContext) -> Dict[str, Any]:
    """Composite registry+downstream health snapshot. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/combined-health", timeout=DIAGNOSTIC_TIMEOUT)


async def get_cloud_operator_health(auth: MCPAuthContext, application_id: str) -> Dict[str, Any]:
    """Detailed health check for a cloud operator (mainframe-only: a cloud operator answers 404 mainframe_only). Admin only."""
    if not application_id:
        return {"error": "application_id is required"}
    return await _admin_get(auth, f"/api/v1/admin/cloud-operators/{seg(application_id)}/health")


# ── DESTRUCTIVE (with warnings in docstrings) ────────────────────────────

async def approve_funding(
    auth: MCPAuthContext,
    request_id: int,
    approved_amount: Optional[str] = None,
) -> Dict[str, Any]:
    """DESTRUCTIVE: approve a pending agent funding request. Transfers units from the treasury to the requesting agent; optional
    approved_amount (defaults to the requested amount). Admin only — verify request_id from getAdminFundingPending first.

    §MCPTEST30 (2026-10-01): the survey's BODY_UNDECLARED class: it sent `notes`, which the route never read (it reads `approved_amount`)."""
    if request_id is None:
        return {"error": "request_id is required"}
    body: Dict[str, Any] = {}
    if approved_amount:
        body["approved_amount"] = str(approved_amount)
    return await _admin_post(auth, f"/api/v1/admin/funding/{int(request_id)}/approve", json_body=body)


async def reject_funding(
    auth: MCPAuthContext,
    request_id: int,
    reason: str,
) -> Dict[str, Any]:
    """DESTRUCTIVE: reject a pending agent funding request. reason is required (visible to requester). Admin only — verify request_id from getAdminFundingPending first."""
    if request_id is None:
        return {"error": "request_id is required"}
    if not reason:
        return {"error": "reason is required"}
    return await _admin_post(auth, f"/api/v1/admin/funding/{int(request_id)}/reject", json_body={"reason": reason})


async def trigger_eigentrust_computation(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE: force-trigger an immediate EigenTrust++ epoch computation. Heavy compute (~500ms for sandbox-scale). Admin only — normally runs on a fixed schedule. Use sparingly."""
    return await _admin_post(auth, "/api/v1/reputation/admin/trigger-computation")


async def svid_refresh(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE: force-rotate this registry's SPIFFE SVID + trust bundle (IRONHAND mTLS identity). Other peers will need ~1-2 min to reconcile. Admin only — use only when debugging mTLS issues."""
    return await _admin_post(auth, "/api/v1/admin/svid/refresh")


async def run_all_diagnostics(
    auth: MCPAuthContext,
    target: str,
    force: bool = False,
) -> Dict[str, Any]:
    """Run all applicable diagnostic checks against ONE target operator. target = operator_id from getDiagnosticTargets. force=true bypasses cache. May take several seconds. Admin only."""
    if not target:
        return {"error": "target is required (operator_id from getDiagnosticTargets)"}
    return await _admin_post(
        auth, "/api/v1/admin/diagnostics/run-all",
        json_body={"target": target, "force": bool(force)},
    )


async def trigger_diagnostic_action(
    auth: MCPAuthContext,
    action_id: str,
    target: str,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """DESTRUCTIVE (when dry_run=false): execute a remediation action against a target. action_id from getDiagnosticActions. target = operator_id from getDiagnosticTargets. Defaults to dry_run=True for safety; set False to actually execute. Admin only."""
    if not action_id:
        return {"error": "action_id is required (from getDiagnosticActions)"}
    if not target:
        return {"error": "target is required (operator_id from getDiagnosticTargets)"}
    return await _admin_post(
        auth, f"/api/v1/admin/diagnostics/actions/{seg(action_id)}",
        json_body={"target": target, "dry_run": bool(dry_run)},
    )


# ===========================================================================
# §pass70 Sprint 9 — Admin (15 new — observability + detail readouts)
# ===========================================================================

async def get_docker_stats(auth: MCPAuthContext) -> Dict[str, Any]:
    """Docker container stats snapshot for this registry host (CPU/RAM/disk per container)."""
    return await _admin_get(auth, "/api/v1/admin/docker-stats")


async def get_prometheus_metrics(auth: MCPAuthContext) -> Dict[str, Any]:
    """Raw Prometheus metric scrape (all registered metrics for this registry). Useful for ad-hoc PromQL composition."""
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/admin/prometheus-metrics",
                headers={"Authorization": f"Bearer {effective_token}"},
            )
        if r.status_code == 200:
            return {"content_type": r.headers.get("content-type"), "metric_count_lines": r.text.count('\n'), "size_bytes": len(r.text), "preview": r.text[:1500]}
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    except Exception as e:
        logger.error(f"getPrometheusMetrics error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_operator_lifecycle(auth: MCPAuthContext) -> Dict[str, Any]:
    """Local operator lifecycle state (operator self-view: pull-token, license, last-activity, frame)."""
    return await _admin_get(auth, "/api/v1/admin/operator-lifecycle")


async def get_admin_flags(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get fleet-wide admin feature flags (rollout toggles, A/B test gates)."""
    return await _admin_get(auth, "/api/v1/admin/flags")


async def get_admin_registry_card(auth: MCPAuthContext) -> Dict[str, Any]:
    """View this registry's full Registry Card v0.6 (admin view incl. all editable fields)."""
    return await _admin_get(auth, "/api/v1/admin/registry-card")


async def get_system_resources(auth: MCPAuthContext) -> Dict[str, Any]:
    """System-level CPU/RAM/disk/network stats for the registry host (psutil snapshot)."""
    return await _admin_get(auth, "/api/v1/admin/system-resources")


async def get_canary_judge_events(auth: MCPAuthContext, limit: int = 50) -> Dict[str, Any]:
    """Recent canary judge events (per-path pass/fail with timestamps + reason). Paginated."""
    return await _admin_get(
        auth, "/api/v1/admin/canary-judge/events",
        params={"limit": min(max(int(limit), 1), 200)},
    )


async def get_canary_rebalancer_events(auth: MCPAuthContext, limit: int = 50) -> Dict[str, Any]:
    """Recent canary rebalancer events (top-up actions on agents under floor). Paginated."""
    return await _admin_get(
        auth, "/api/v1/admin/canary-rebalancer/events",
        params={"limit": min(max(int(limit), 1), 200)},
    )


async def get_saga_timeout_events(auth: MCPAuthContext, limit: int = 50) -> Dict[str, Any]:
    """Recent saga-timeout events (cross-frame settlement timeouts + refund actions). Paginated."""
    return await _admin_get(
        auth, "/api/v1/admin/saga-timeout/events",
        params={"limit": min(max(int(limit), 1), 200)},
    )


async def get_cross_teg_sweeper_events(auth: MCPAuthContext, limit: int = 50) -> Dict[str, Any]:
    """Recent cross-TEG sweeper events (2PC stuck-transfer compensation actions). Paginated."""
    return await _admin_get(
        auth, "/api/v1/admin/cross-teg-sweeper/events",
        params={"limit": min(max(int(limit), 1), 200)},
    )


async def get_email_templates(auth: MCPAuthContext) -> Dict[str, Any]:
    """List all admin email templates available for preview (resolves the 'unknown template name' question from Sprint 4)."""
    return await _admin_get(auth, "/api/v1/admin/email/preview")


async def get_admin_agent_detail(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Full admin view of one agent (owner, credentials, status, enforcement state, audit timeline)."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _admin_get(auth, f"/api/v1/admin/agents/{seg(agent_did)}")


async def get_admin_developer_detail(auth: MCPAuthContext, developer_id: int) -> Dict[str, Any]:
    """Full admin view of one developer (account, agents, balances, admin flags, suspension state)."""
    if developer_id is None:
        return {"error": "developer_id is required"}
    return await _admin_get(auth, f"/api/v1/admin/developers/{int(developer_id)}")


async def list_ironhand_identities(auth: MCPAuthContext) -> Dict[str, Any]:
    """List all IRONHAND SPIRE agent identities (mTLS enrollments). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/ironhand/identities")


async def get_admin_fiat_stats(auth: MCPAuthContext) -> Dict[str, Any]:
    """KPI aggregates for the fiat onramp dashboard (purchase count, EUR volume, conversion rate)."""
    return await _admin_get(auth, "/api/v1/admin/fiat/stats")


# ===========================================================================
# §pass70 Sprint 10 — Admin (20 new: enforcement + broadcasts + agent admin)
# ===========================================================================

# ── ENFORCEMENT — destructive agent-level actions ─────────────────────────

async def suspend_agent(auth: MCPAuthContext, agent_did: str, reason: str) -> Dict[str, Any]:
    """DESTRUCTIVE: suspend an agent (freezes all operations: transfers, staking, dispute participation). Triggers coordinated suspension flow. Admin only."""
    if not agent_did or not reason:
        return {"error": "agent_did and reason are required"}
    return await _admin_post(auth, f"/api/v1/admin/enforcement/agents/{seg(agent_did)}/suspend", json_body={"reason": reason})


async def reinstate_agent_enforcement(auth: MCPAuthContext, agent_did: str, reason: str) -> Dict[str, Any]:
    """DESTRUCTIVE: reinstate a suspended agent (reverses suspendAgent + coordinated reinstate flow). Admin only."""
    if not agent_did or not reason:
        return {"error": "agent_did and reason are required"}
    return await _admin_post(auth, f"/api/v1/admin/enforcement/agents/{seg(agent_did)}/reinstate", json_body={"reason": reason})


async def pause_agent_rewards(
    auth: MCPAuthContext,
    agent_did: str,
    reason: str,
    duration_days: Optional[int] = None,
) -> Dict[str, Any]:
    """DESTRUCTIVE: pause staking rewards for an agent. Optional duration_days (default: indefinite). Admin only."""
    if not agent_did or not reason:
        return {"error": "agent_did and reason are required"}
    body: Dict[str, Any] = {"reason": reason}
    if duration_days is not None:
        body["duration_days"] = int(duration_days)
    return await _admin_post(auth, f"/api/v1/admin/enforcement/agents/{seg(agent_did)}/pause-rewards", json_body=body)


async def resume_agent_rewards(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """DESTRUCTIVE: resume paused staking rewards for an agent. Admin only."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _admin_post(auth, f"/api/v1/admin/enforcement/agents/{seg(agent_did)}/resume-rewards")


async def slash_agent_stake(
    auth: MCPAuthContext,
    agent_did: str,
    amount: int,
    reason: str,
) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: force-unstake (slash) AVT from an agent's staked balance. amount is integer AVT units. Admin only."""
    if not agent_did or amount is None or not reason:
        return {"error": "agent_did, amount, reason are required"}
    return await _admin_post(
        auth, f"/api/v1/admin/enforcement/agents/{seg(agent_did)}/slash-stake",
        json_body={"amount": int(amount), "reason": reason},
    )


async def preview_slash_stake(auth: MCPAuthContext, agent_did: str, amount: int) -> Dict[str, Any]:
    """Preview the impact of slashing N AVT from an agent's stake (dry run — no state change). Returns projected balances + reputation delta. Admin only."""
    if not agent_did or amount is None:
        return {"error": "agent_did and amount are required"}
    return await _admin_get(
        auth, f"/api/v1/admin/enforcement/agents/{seg(agent_did)}/slash-preview",
        params={"amount": int(amount)},
    )


async def record_agent_offense(
    auth: MCPAuthContext,
    agent_did: str,
    offense_type: Optional[str] = None,
    severity: Optional[int] = None,
    reference: Optional[str] = None,
    disputed_amount: Optional[int] = None,
) -> Dict[str, Any]:
    """DESTRUCTIVE: manually record an offense against an agent (triggers enforcement escalation). offense_type is enum; severity 1-10. Admin only."""
    if not agent_did:
        return {"error": "agent_did is required"}
    body: Dict[str, Any] = {}
    if offense_type: body["offense_type"] = offense_type
    if severity is not None: body["severity"] = int(severity)
    if reference: body["reference"] = reference
    if disputed_amount is not None: body["disputed_amount"] = int(disputed_amount)
    return await _admin_post(auth, f"/api/v1/admin/enforcement/agents/{seg(agent_did)}/record-offense", json_body=body)


async def approve_pending_enforcement(auth: MCPAuthContext, action_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: approve and execute a pending enforcement action (from getEnforcementPending queue). Admin only."""
    if not action_id:
        return {"error": "action_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/enforcement/pending/{seg(action_id)}/approve")


async def reject_pending_enforcement(auth: MCPAuthContext, action_id: str, reason: str) -> Dict[str, Any]:
    """Reject a pending enforcement action (cancels it). Admin only."""
    if not action_id or not reason:
        return {"error": "action_id and reason are required"}
    return await _admin_post(auth, f"/api/v1/admin/enforcement/pending/{seg(action_id)}/reject", json_body={"reason": reason})


async def list_quarantined_registries(auth: MCPAuthContext) -> Dict[str, Any]:
    """List all currently quarantined federated registries (federation-level enforcement). Admin only."""
    body = await _admin_get(auth, "/api/v1/admin/enforcement/registries/quarantined")
    if isinstance(body, list):
        return {"registries": body, "total": len(body)}
    return body


# ── BROADCASTS — admin notification CRUD ──────────────────────────────────

async def compose_broadcast(
    auth: MCPAuthContext,
    title: str,
    body: str,
    broadcast_type: str = "info",
    send_email: bool = False,
    cta_url: Optional[str] = None,
    cta_label: Optional[str] = None,
    requires_ack: bool = False,
    target_org_id: Optional[str] = None,
    target_developer_id: Optional[int] = None,
) -> Dict[str, Any]:
    """DESTRUCTIVE: compose + send an admin broadcast notification to developers. broadcast_type enum (info/warning/maintenance). send_email=True also dispatches email. target_developer_id sends a direct notice to that one developer instead (in-app only, never copied to a peer). Admin only."""
    if not title or not body:
        return {"error": "title and body are required"}
    request_body: Dict[str, Any] = {
        "title": title, "body": body, "broadcast_type": broadcast_type,
        "send_email": bool(send_email), "requires_ack": bool(requires_ack),
    }
    if cta_url: request_body["cta_url"] = cta_url
    if cta_label: request_body["cta_label"] = cta_label
    if target_org_id: request_body["target_org_id"] = target_org_id
    # §MCPTEST30 V0645 (agentvault2-66, 2026-10-26): the route has taken a developer-targeted notice since V0397; the
    # tool could not send one, so every broadcast the MCP tester composed reached every developer of the federation
    if target_developer_id is not None: request_body["target_developer_id"] = int(target_developer_id)
    return await _admin_post(auth, "/api/v1/admin/broadcasts", json_body=request_body)


async def get_admin_broadcasts_overview(auth: MCPAuthContext) -> Dict[str, Any]:
    """Aggregate broadcast metrics for the admin dashboard (counts by type, read rates, latest activity). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/broadcasts/overview")


async def get_broadcast_stats(auth: MCPAuthContext, broadcast_id: int) -> Dict[str, Any]:
    """Per-broadcast read/dismiss statistics. broadcast_id from getAdminBroadcasts. Admin only."""
    if broadcast_id is None:
        return {"error": "broadcast_id is required"}
    return await _admin_get(auth, f"/api/v1/admin/broadcasts/{int(broadcast_id)}/stats")


async def retract_broadcast(auth: MCPAuthContext, broadcast_id: int) -> Dict[str, Any]:
    """DESTRUCTIVE: retract / soft-delete an admin broadcast. Reversible via reinstateBroadcast. Admin only."""
    if broadcast_id is None:
        return {"error": "broadcast_id is required"}
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            r = await client.delete(
                f"{REGISTRY_SELF_URL}/api/v1/admin/broadcasts/{int(broadcast_id)}",
                headers={"Authorization": f"Bearer {effective_token}"},
            )
        if r.status_code in (200, 201, 204):
            try: return r.json()
            except Exception: return {"status": "retracted"}
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    except Exception as e:
        logger.error(f"retractBroadcast error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def update_broadcast(
    auth: MCPAuthContext,
    broadcast_id: int,
    title: Optional[str] = None,
    body: Optional[str] = None,
    broadcast_type: Optional[str] = None,
) -> Dict[str, Any]:
    """DESTRUCTIVE: edit a broadcast's title/body/type after send. Admin only."""
    if broadcast_id is None:
        return {"error": "broadcast_id is required"}
    update_body: Dict[str, Any] = {}
    if title is not None: update_body["title"] = title
    if body is not None: update_body["body"] = body
    if broadcast_type is not None: update_body["broadcast_type"] = broadcast_type
    if not update_body:
        return {"error": "at least one field to update is required"}
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            r = await client.put(
                f"{REGISTRY_SELF_URL}/api/v1/admin/broadcasts/{int(broadcast_id)}",
                json=update_body,
                headers={"Authorization": f"Bearer {effective_token}", "Content-Type": "application/json"},
            )
        if r.status_code in (200, 201, 204):
            try: return r.json()
            except Exception: return {"status": "updated"}
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    except Exception as e:
        logger.error(f"updateBroadcast error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def reinstate_broadcast(auth: MCPAuthContext, broadcast_id: int) -> Dict[str, Any]:
    """Reinstate a previously-retracted broadcast. Admin only."""
    if broadcast_id is None:
        return {"error": "broadcast_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/broadcasts/{int(broadcast_id)}/reinstate")


# ── ADMIN AGENT READS ─────────────────────────────────────────────────────

async def get_admin_agents_by_developer(auth: MCPAuthContext, developer_id: int) -> Dict[str, Any]:
    """List all agents owned by a given developer (cascade preview for suspend UX). Admin only."""
    if developer_id is None:
        return {"error": "developer_id is required"}
    return await _admin_get(auth, f"/api/v1/admin/agents/by-developer/{int(developer_id)}")


async def get_admin_agent_orphans(auth: MCPAuthContext) -> Dict[str, Any]:
    """List orphaned agents (no living developer owner — typically post-developer-soft-delete). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/agents/orphans")


async def get_admin_agent_flags(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """List moderation flags for an agent (rule violations, drift, etc.). Admin only."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _admin_get(auth, f"/api/v1/admin/agents/{seg(agent_did)}/flags")


async def get_admin_agent_signing_keys(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """List agent signing keys (Phase 2 Ed25519 — for audit + rotation tracking). Admin only."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _admin_get(auth, f"/api/v1/admin/agents/{seg(agent_did)}/signing-keys")


# ===========================================================================
# §pass70 Sprint 11 — Admin (28 new — fiat + simulation + dev mgmt)
# ===========================================================================

# ── FIAT admin (mostly safe reads + a few destructive) ────────────────────

async def get_admin_fiat_pricing(auth: MCPAuthContext) -> Dict[str, Any]:
    """Active fiat pricing config + version history. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/fiat/pricing")


async def get_admin_fiat_purchases(auth: MCPAuthContext, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """List FiatPurchase rows with filters + pagination. Admin only."""
    return await _admin_get(
        auth, "/api/v1/admin/fiat/purchases",
        params={"limit": min(max(int(limit), 1), 500), "offset": max(int(offset), 0)},
    )


async def get_admin_fiat_purchase_detail(auth: MCPAuthContext, purchase_id: str) -> Dict[str, Any]:
    """Drill into a single FiatPurchase — joined Developer + Agent + Stripe metadata. Admin only."""
    if not purchase_id:
        return {"error": "purchase_id is required"}
    return await _admin_get(auth, f"/api/v1/admin/fiat/purchases/{seg(purchase_id)}")


async def get_admin_fiat_flares(auth: MCPAuthContext) -> Dict[str, Any]:
    """List all developers with a flare (admin Flare Ops UI feed). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/fiat/flares")


async def simulate_fiat_pricing(
    auth: MCPAuthContext, purchases_eur: List[str], starting_treasury_avt: str, starting_fee_collector_avt: str,
    config: Optional[Dict[str, Any]] = None, waterfall: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """What-if simulation — run the given EUR purchases through a pricing config (dry run, no DB write). Admin only."""
    if not purchases_eur or starting_treasury_avt in (None, "") or starting_fee_collector_avt in (None, ""):
        return {"error": "purchases_eur, starting_treasury_avt and starting_fee_collector_avt are required"}
    body: Dict[str, Any] = {"purchases_eur": [str(p) for p in purchases_eur],
                            "starting_treasury_avt": str(starting_treasury_avt),
                            "starting_fee_collector_avt": str(starting_fee_collector_avt)}
    if isinstance(config, dict):
        body["config"] = config
    if waterfall:
        body["waterfall"] = waterfall
    return await _admin_post(auth, "/api/v1/admin/fiat/pricing/simulate", json_body=body)


async def validate_fiat_pricing(auth: MCPAuthContext, config: Dict[str, Any], note: str) -> Dict[str, Any]:
    """Dry-run config validation for a proposed fiat pricing config. Admin only."""
    if not isinstance(config, dict) or not note:
        return {"error": "a config object and a note are required"}
    return await _admin_post(auth, "/api/v1/admin/fiat/pricing/validate", json_body={"config": config, "note": note})


async def refund_fiat_purchase(auth: MCPAuthContext, purchase_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: issue a Stripe refund + flag the FiatPurchase as refunded. Does NOT auto-claw AVT. Admin only."""
    if not purchase_id:
        return {"error": "purchase_id is required"}
    body: Dict[str, Any] = {}
    if reason:
        body["reason"] = reason
    return await _admin_post(auth, f"/api/v1/admin/fiat/purchases/{seg(purchase_id)}/refund", json_body=body)


async def replay_fiat_purchase(auth: MCPAuthContext, purchase_id: str) -> Dict[str, Any]:
    """Re-run the Stripe webhook handler for a stuck pending/failed purchase. Admin only."""
    if not purchase_id:
        return {"error": "purchase_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/fiat/purchases/{seg(purchase_id)}/replay")


async def grant_fiat_flare(auth: MCPAuthContext, developer_id: int, flare_tier: str, agent_did: Optional[str] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: admin-grant a flare tier to a developer (incl. operator/commander). Admin only."""
    if developer_id is None or not flare_tier:
        return {"error": "developer_id and flare_tier are required"}
    body: Dict[str, Any] = {"developer_id": int(developer_id), "tier": flare_tier}
    if agent_did:
        body["agent_did"] = agent_did
    return await _admin_post(auth, "/api/v1/admin/fiat/flare/grant", json_body=body)


async def revoke_fiat_flare(auth: MCPAuthContext, developer_id: int) -> Dict[str, Any]:
    """DESTRUCTIVE: admin-revoke a developer's flare (cosmetic-only). Admin only."""
    if developer_id is None:
        return {"error": "developer_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/fiat/flare/revoke/{int(developer_id)}")


# ── SIMULATION admin (read + control) ─────────────────────────────────────

async def get_admin_simulation_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get simulation framework status (running? phase? next-cycle?). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/simulation/status")


async def get_admin_simulation_agents(auth: MCPAuthContext) -> Dict[str, Any]:
    """List simulation agents (synthetic agents used in load testing). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/simulation/agents")


async def get_admin_simulation_supply_audit(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get supply audit from simulation framework's perspective. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/simulation/supply-audit")


async def get_admin_simulation_topology(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get federation topology from simulation framework. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/simulation/topology")


async def get_admin_simulation_deadman_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get deadman-switch status (simulation auto-halt guard). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/simulation/deadman-status")


async def get_admin_simulation_fund_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get simulation agent fund status. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/simulation/fund-status")


async def get_admin_simulation_logs(auth: MCPAuthContext, limit: int = 100) -> Dict[str, Any]:
    """Get simulation execution logs (paginated). Admin only."""
    return await _admin_get(
        auth, "/api/v1/admin/simulation/logs",
        params={"tail": min(max(int(limit), 1), 500)},   # §MCPTEST30 (2026-10-01): the survey's UNDECLARED class: the route reads `tail`
    )


# the simulation start request's own fields (routers/admin_simulation.SimStartRequest; pinned by a test)
SIM_START_FIELDS = ("mode", "pairs", "cycle_interval", "cycles", "instances", "concurrency", "backend_mode", "rate_tps",
                    "dynamic", "target_settle_ms", "target_metric", "min_concurrency", "max_concurrency", "max_backlog",
                    "venue_balance", "passport_share", "spawn_subagents", "xreg_delegation", "spawn_frames", "xreg_only",
                    "clerk_anchored")


async def start_simulation(auth: MCPAuthContext, **params: Any) -> Dict[str, Any]:
    """DESTRUCTIVE: start a simulation run on this registry (loads synthetic agents, fires synthetic transfers). Admin only.
    Use sparingly; the go-to shape is BOUNDED dynamic (dynamic=true with max_concurrency set: CLAUDE.md rule 13).

    §MCPTEST30 (2026-10-01): the survey's BODY_UNDECLARED class: it took `scenario` and `n_agents`, which the route never read, so every start ran the
    route's defaults and the payload the doctrine names could not even be passed. It takes the route's own fields now."""
    unknown = sorted(set(params) - set(SIM_START_FIELDS))
    if unknown:
        return {"error": f"unknown simulation fields {unknown}: the start request reads {list(SIM_START_FIELDS)}"}
    body: Dict[str, Any] = {k: v for k, v in params.items() if v is not None}
    return await _admin_post(auth, "/api/v1/admin/simulation/start", json_body=body)


async def stop_simulation(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE: stop a running simulation. Admin only."""
    return await _admin_post(auth, "/api/v1/admin/simulation/stop")


async def mint_frame_b_simulation(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE: mint Frame B simulation tokens (genesis-equivalent for sim). Admin only — sandbox/Frame-B only."""
    return await _admin_post(auth, "/api/v1/admin/simulation/mint-frame-b")


async def fund_simulation_agents(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE: bulk-fund simulation agents from treasury. Admin only."""
    return await _admin_post(auth, "/api/v1/admin/simulation/fund")


async def simulation_funding_preview(auth: MCPAuthContext) -> Dict[str, Any]:
    """Dry-run preview of simulation funding (what would be funded, total cost). Admin only."""
    return await _admin_post(auth, "/api/v1/admin/simulation/funding-preview")


# ── DEVELOPER ADMIN MUTATIONS ─────────────────────────────────────────────

async def suspend_developer(auth: MCPAuthContext, developer_id: int, reason: str) -> Dict[str, Any]:
    """DESTRUCTIVE: suspend a developer account (locks login, freezes all agents). Admin only."""
    if developer_id is None or not reason:
        return {"error": "developer_id and reason are required"}
    return await _admin_post(auth, f"/api/v1/admin/developers/{int(developer_id)}/suspend", json_body={"reason": reason})


async def reinstate_developer(auth: MCPAuthContext, developer_id: int) -> Dict[str, Any]:
    """DESTRUCTIVE: reinstate a suspended developer account. Admin only."""
    if developer_id is None:
        return {"error": "developer_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/developers/{int(developer_id)}/reinstate")


async def get_admin_developer_activity(auth: MCPAuthContext, developer_id: int) -> Dict[str, Any]:
    """Recent EventStore activity concerning this developer (login, agent ops, transfers). Admin only."""
    if developer_id is None:
        return {"error": "developer_id is required"}
    return await _admin_get(auth, f"/api/v1/admin/developers/{int(developer_id)}/activity")


async def get_admin_developer_quota(auth: MCPAuthContext, developer_id: int) -> Dict[str, Any]:
    """Get developer's resource quotas (max agents, max API keys, rate limits). Admin only."""
    if developer_id is None:
        return {"error": "developer_id is required"}
    return await _admin_get(auth, f"/api/v1/admin/developers/{int(developer_id)}/quota")


async def force_email_verify(auth: MCPAuthContext, developer_id: int) -> Dict[str, Any]:
    """DESTRUCTIVE: force-verify a developer's email (manual override — bypasses email verification). Admin only."""
    if developer_id is None:
        return {"error": "developer_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/developers/{int(developer_id)}/force-email-verify")


async def revoke_developer_api_keys(auth: MCPAuthContext, developer_id: int) -> Dict[str, Any]:
    """DESTRUCTIVE: revoke ALL programmatic API keys for a developer (kicks out bridges + integrations). Admin only."""
    if developer_id is None:
        return {"error": "developer_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/developers/{int(developer_id)}/revoke-api-keys")


async def disable_developer_2fa(auth: MCPAuthContext, developer_id: int, reason: str) -> Dict[str, Any]:
    """DESTRUCTIVE: disable 2FA on a developer account (emergency unlock — use only when user lost TOTP device). Admin only."""
    if developer_id is None or not reason:
        return {"error": "developer_id and reason are required"}
    return await _admin_post(auth, f"/api/v1/admin/developers/{int(developer_id)}/disable-2fa", json_body={"reason": reason})


# ===========================================================================
# §pass70 Sprint 12 — Admin (15 new — operators + frame + signing keys + EventStore)
# ===========================================================================

async def get_operators_lifecycle_overview(auth: MCPAuthContext) -> Dict[str, Any]:
    """Overview of operator lifecycle states (pending/approved/active/suspended/revoked counts + drilldown). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/operators/lifecycle-overview")


async def get_bridge_aggregate(auth: MCPAuthContext) -> Dict[str, Any]:
    """Cross-frame bridge aggregate metrics (in-flight transfers, settlement latency). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/bridge/aggregate")


async def rotate_registry_signing_key(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE: rotate this registry's EdDSA signing key (Registry Card v0.6 signing key). 7-day grace window. Admin only."""
    return await _admin_post(auth, "/api/v1/admin/registry-signing-key/rotate")


async def get_cloud_operator_logs(auth: MCPAuthContext, application_id: str, service: Optional[str] = None, lines: int = 100) -> Dict[str, Any]:
    """Tail logs from a service in a cloud-hosted operator's compose stack (mainframe-only: a cloud operator answers 404 mainframe_only). Admin only."""
    if not application_id:
        return {"error": "application_id is required"}
    params: Dict[str, Any] = {"tail": int(lines)}   # §MCPTEST30 (2026-10-01): the survey's UNDECLARED class: the route reads `tail`, not `lines`
    if service:
        params["service"] = service
    return await _admin_get(auth, f"/api/v1/admin/cloud-operators/{seg(application_id)}/logs", params=params)


async def restart_cloud_operator_service(auth: MCPAuthContext, application_id: str, service: Optional[str] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: restart one service (or all) in a cloud-hosted operator stack. Mainframe-only: a cloud operator answers 404 mainframe_only. Admin only."""
    if not application_id:
        return {"error": "application_id is required"}
    body: Dict[str, Any] = {}
    if service:
        body["service"] = service
    return await _admin_post(auth, f"/api/v1/admin/cloud-operators/{seg(application_id)}/restart-service", json_body=body)


async def provision_cloud_operator(auth: MCPAuthContext, application_id: str) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: provision a new cloud-hosted operator registry from an approved application. Mainframe-only. Real infrastructure. Admin only."""
    if not application_id:
        return {"error": "application_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/cloud-operators/{seg(application_id)}/provision")


async def teardown_cloud_operator(auth: MCPAuthContext, application_id: str) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: tear down a cloud-hosted operator registry. Mainframe-only. Real infrastructure. Admin only."""
    if not application_id:
        return {"error": "application_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/cloud-operators/{seg(application_id)}/teardown")


async def get_cloud_operator_self_logs(auth: MCPAuthContext, lines: int = 100) -> Dict[str, Any]:
    """Answers an error to every MCP caller (§MCPTEST30, V0549): the route takes a cloud operator's own licence header,
    which this tool does not send; getCloudOperatorLogs (frame admin) and operatorPortalSelfLogs (operator) read logs."""
    return await _admin_get(auth, "/api/v1/admin/cloud-operators/self-logs", params={"tail": int(lines)})   # the route reads `tail`


async def cloud_operator_self_restart(auth: MCPAuthContext, service: Optional[str] = None) -> Dict[str, Any]:
    """Answers an error to every MCP caller (§MCPTEST30, V0549): the route takes a cloud operator's own licence header,
    which this tool does not send; restartCloudOperatorService (frame admin) and operatorPortalSelfRestart restart."""
    body: Dict[str, Any] = {}
    if service:
        body["service"] = service
    return await _admin_post(auth, "/api/v1/admin/cloud-operators/self-restart", json_body=body)


async def update_dispute_ruling(auth: MCPAuthContext, dispute_id: str, ruling: str) -> Dict[str, Any]:
    """DESTRUCTIVE: admin updates a dispute ruling (IN_FAVOR_OF_COMPLAINANT / IN_FAVOR_OF_DEFENDANT / DISMISSED). Triggers enforcement on the loser. Admin only."""
    if not dispute_id or not ruling:
        return {"error": "dispute_id and ruling are required"}
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            # the route reads the ruling from the query string, not a body
            r = await client.put(
                f"{REGISTRY_SELF_URL}/api/v1/admin/disputes/{seg(dispute_id)}/ruling",
                params={"ruling": ruling},
                headers={"Authorization": f"Bearer {effective_token}"},
            )
        if r.status_code in (200, 201, 204):
            try: return r.json()
            except Exception: return {"status": "ruled"}
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    except Exception as e:
        logger.error(f"updateDisputeRuling error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_event_store_cross_frame_peers(auth: MCPAuthContext) -> Dict[str, Any]:
    """List cross-frame peers known to EventStore (sovereign-mainframe-only: 404 mainframe_only elsewhere). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/eventstore/cross-frame-peers")


async def get_event_store_federation_operators(auth: MCPAuthContext) -> Dict[str, Any]:
    """List federation operators known to EventStore (sovereign-mainframe-only: 404 mainframe_only elsewhere). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/eventstore/federation-operators")


async def composite_health_check(auth: MCPAuthContext, agent_token: Optional[str] = None) -> Dict[str, Any]:
    """Composite health check (developer + agent auth combined); pass an agent JWT (getAgentToken) as agent_token for the
    full check. Admin only. §MCPTEST30 (2026-10-01): the survey's BODY_UNDECLARED class: it sent `agent_credentials`, the route reads `agent_token`."""
    body: Dict[str, Any] = {}
    if agent_token:
        body["agent_token"] = agent_token
    return await _admin_post(auth, "/api/v1/admin/health-check/composite", json_body=body, timeout=DIAGNOSTIC_TIMEOUT)


# ===========================================================================
# §pass70 Sprint 13 — Admin (25 new — treasury, bulk agent ops, enforcement, federation admin)
# ===========================================================================

async def teg_treasury_mint(
    auth: MCPAuthContext,
    amount: str,
    reason: str,
    target_agent_did: Optional[str] = None,
) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: mint new AVT tokens (sovereign-mainframe-only). Increases total supply. Admin only — extreme caution."""
    if not amount or not reason:
        return {"error": "amount and reason are required"}
    body: Dict[str, Any] = {"amount": amount, "reason": reason}
    if target_agent_did:
        body["target_agent_did"] = target_agent_did
    return await _admin_post(auth, "/api/v1/teg/treasury/mint", json_body=body)


async def teg_treasury_receive(
    auth: MCPAuthContext,
    source_agent_did: str,
    amount: str,
    reason: str,
    reference_id: Optional[str] = None,
) -> Dict[str, Any]:
    """DESTRUCTIVE: return AVT to treasury (from an agent). Admin only."""
    if not source_agent_did or not amount or not reason:
        return {"error": "source_agent_did, amount, reason are required"}
    body: Dict[str, Any] = {"source_agent_did": source_agent_did, "amount": amount, "reason": reason}
    if reference_id:
        body["reference_id"] = reference_id
    return await _admin_post(auth, "/api/v1/teg/treasury/receive", json_body=body)


async def teg_cross_teg_fund(
    auth: MCPAuthContext,
    target_registry: str,
    amount: str,
    reason: str,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: fund a satellite TEG treasury from origin TEG (one-way cross-TEG capital move). Admin only."""
    if not target_registry or not amount or not reason:
        return {"error": "target_registry, amount, reason are required"}
    body: Dict[str, Any] = {"target_registry": target_registry, "amount": amount, "reason": reason}
    if correlation_id:
        body["correlation_id"] = correlation_id
    return await _admin_post(auth, "/api/v1/teg/treasury/cross-teg-fund", json_body=body)


async def get_enforcement_policy_defaults(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get factory default enforcement policy (baseline thresholds before admin overrides). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/enforcement/policy/defaults")


async def update_enforcement_policy(auth: MCPAuthContext, policy_json: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: replace the active enforcement policy (offense thresholds, slash multipliers, etc.). Admin override. Affects all agents fleet-wide. Admin only."""
    if not isinstance(policy_json, dict) or not reason:
        return {"error": "policy_json object and reason are required"}
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            r = await client.put(
                f"{REGISTRY_SELF_URL}/api/v1/admin/enforcement/policy",
                json={"policy_json": policy_json, "reason": reason},
                headers={"Authorization": f"Bearer {effective_token}", "Content-Type": "application/json"},
            )
        if r.status_code in (200, 201, 204):
            try: return r.json()
            except Exception: return {"status": "updated"}
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    except Exception as e:
        logger.error(f"updateEnforcementPolicy error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def quarantine_registry(auth: MCPAuthContext, peer_id: str, reason: str, grace_hours: Optional[int] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: manually quarantine a federated registry (suspends federation sync). Reversible via liftQuarantine. Admin only."""
    if not peer_id or not reason:
        return {"error": "peer_id and reason are required"}
    body: Dict[str, Any] = {"reason": reason}
    if grace_hours is not None:
        body["grace_hours"] = int(grace_hours)
    return await _admin_post(auth, f"/api/v1/admin/enforcement/registries/{seg(peer_id)}/quarantine", json_body=body)


async def lift_quarantine(auth: MCPAuthContext, peer_id: str, new_policy_hash: str) -> Dict[str, Any]:
    """DESTRUCTIVE: lift quarantine on a federated registry after operator submits corrected policy. new_policy_hash is the SHA-256 of the corrected policy bundle. Admin only."""
    if not peer_id or not new_policy_hash:
        return {"error": "peer_id and new_policy_hash are required"}
    return await _admin_post(auth, f"/api/v1/admin/enforcement/registries/{seg(peer_id)}/lift-quarantine", json_body={"new_policy_hash": new_policy_hash})


async def accept_compliance_baseline(auth: MCPAuthContext, peer_id: str, expected_hash: str, reason: str) -> Dict[str, Any]:
    """Make a federated peer's CURRENT policy its compliance baseline, after a drift you reviewed (§MCPTEST30, V0561).
    Refused unless expected_hash is exactly the hash the peer publishes now; the reason is kept on the ledger
    (ComplianceBaselineAccepted). Admin only."""
    if not peer_id or not expected_hash or not reason:
        return {"error": "peer_id, expected_hash and reason are required"}
    return await _admin_post(auth, f"/api/v1/admin/federation/compliance/peers/{seg(peer_id)}/accept-baseline",
                             json_body={"expected_hash": expected_hash, "reason": reason})


async def blacklist_registry(auth: MCPAuthContext, peer_id: str, reason: str) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE + IRREVERSIBLE FROM API: permanently blacklist a federated registry. Admin only."""
    if not peer_id or not reason:
        return {"error": "peer_id and reason are required"}
    return await _admin_post(auth, f"/api/v1/admin/enforcement/registries/{seg(peer_id)}/blacklist", json_body={"reason": reason})


async def bulk_suspend_agents(auth: MCPAuthContext, agent_dids: list, reason: str, soft_suspend: bool = False) -> Dict[str, Any]:
    """DESTRUCTIVE: bulk-suspend up to 50 agents in one call. Admin only."""
    if not agent_dids or not reason:
        return {"error": "agent_dids (list) and reason are required"}
    return await _admin_post(
        auth, "/api/v1/admin/agents/bulk/suspend",
        json_body={"agent_dids": agent_dids, "reason": reason, "soft_suspend": bool(soft_suspend)},
    )


async def bulk_reinstate_agents(auth: MCPAuthContext, agent_dids: list, reason: Optional[str] = None, soft_reinstate: bool = False) -> Dict[str, Any]:
    """DESTRUCTIVE: bulk-reinstate suspended agents. Admin only."""
    if not agent_dids:
        return {"error": "agent_dids (list) is required"}
    body: Dict[str, Any] = {"agent_dids": agent_dids, "soft_reinstate": bool(soft_reinstate)}
    if reason:
        body["reason"] = reason
    return await _admin_post(auth, "/api/v1/admin/agents/bulk/reinstate", json_body=body)


async def bulk_refresh_agent_cards(auth: MCPAuthContext, agent_dids: list, reason: Optional[str] = None) -> Dict[str, Any]:
    """Bulk-refresh agent-card pull state from /.well-known/agent-card.json. Admin only."""
    if not agent_dids:
        return {"error": "agent_dids (list) is required"}
    body: Dict[str, Any] = {"agent_dids": agent_dids}
    if reason:
        body["reason"] = reason
    return await _admin_post(auth, "/api/v1/admin/agents/bulk/refresh-cards", json_body=body)


async def transfer_agent_ownership(
    auth: MCPAuthContext,
    agent_did: str,
    new_creator_developer_id: int,
    reason: str,
) -> Dict[str, Any]:
    """DESTRUCTIVE: transfer agent ownership to a new developer. Admin only."""
    if not agent_did or new_creator_developer_id is None or not reason:
        return {"error": "agent_did, new_creator_developer_id, reason are required"}
    return await _admin_post(
        auth, f"/api/v1/admin/agents/{seg(agent_did)}/transfer-ownership",
        json_body={"new_creator_developer_id": int(new_creator_developer_id), "reason": reason},
    )


async def rotate_agent_credentials(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """DESTRUCTIVE: rotate an agent's client_secret (shown ONCE in response). Admin only."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _admin_post(auth, f"/api/v1/admin/agents/{seg(agent_did)}/rotate-credentials")


async def rotate_agent_signing_key(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """DESTRUCTIVE: rotate an agent's Ed25519 signing key. Admin only."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _admin_post(auth, f"/api/v1/admin/agents/{seg(agent_did)}/rotate-signing-key")


async def force_mtls_enroll(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """DESTRUCTIVE: admin-initiated IRONHAND mTLS enrolment for an agent. Admin only."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _admin_post(auth, f"/api/v1/admin/agents/{seg(agent_did)}/force-mtls-enrol")


async def delete_admin_agent(auth: MCPAuthContext, agent_did: str, reason: str, confirm_did: str) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: hard-delete an agent (final audit event). Admin only. The route takes the DID twice (confirm_did)."""
    if not agent_did or not reason or not confirm_did:
        return {"error": "agent_did, reason and confirm_did are required"}
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            r = await client.request(
                "DELETE",
                f"{REGISTRY_SELF_URL}/api/v1/admin/agents/{seg(agent_did)}",
                json={"reason": reason, "confirm_did": confirm_did},
                headers={"Authorization": f"Bearer {effective_token}", "Content-Type": "application/json"},
            )
        if r.status_code in (200, 201, 204):
            try: return r.json()
            except Exception: return {"status": "deleted"}
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    except Exception as e:
        logger.error(f"deleteAdminAgent error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def acknowledge_agent_flag(
    auth: MCPAuthContext,
    agent_did: str,
    flag_id: str,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Acknowledge an agent moderation flag (admin processed it). Admin only."""
    if not agent_did or not flag_id:
        return {"error": "agent_did and flag_id are required"}
    body: Dict[str, Any] = {}
    if notes:
        body["notes"] = notes
    return await _admin_post(auth, f"/api/v1/admin/agents/{seg(agent_did)}/flags/{seg(flag_id)}/acknowledge", json_body=body)


async def update_developer_admin_flags(auth: MCPAuthContext, developer_id: int, admin_flags: Dict[str, Any]) -> Dict[str, Any]:
    """DESTRUCTIVE: update granular admin flags on a developer (admin_treasury / admin_support / admin_platform / etc.). Admin only."""
    if developer_id is None or not isinstance(admin_flags, dict):
        return {"error": "developer_id and admin_flags object are required"}
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            r = await client.put(
                f"{REGISTRY_SELF_URL}/api/v1/admin/developers/{int(developer_id)}/admin-flags",
                json=admin_flags,
                headers={"Authorization": f"Bearer {effective_token}", "Content-Type": "application/json"},
            )
        if r.status_code in (200, 201, 204):
            try: return r.json()
            except Exception: return {"status": "updated"}
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    except Exception as e:
        logger.error(f"updateDeveloperAdminFlags error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def soft_delete_developer(auth: MCPAuthContext, developer_id: int, reason: str, confirm_email: str) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: soft-delete a developer (PII scrub, row retained). Admin only. The route takes the email as a confirmation."""
    if developer_id is None or not reason or not confirm_email:
        return {"error": "developer_id, reason and confirm_email are required"}
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            r = await client.request(
                "DELETE",
                f"{REGISTRY_SELF_URL}/api/v1/admin/developers/{int(developer_id)}",
                json={"reason": reason, "confirm_email": confirm_email},
                headers={"Authorization": f"Bearer {effective_token}", "Content-Type": "application/json"},
            )
        if r.status_code in (200, 201, 204):
            try: return r.json()
            except Exception: return {"status": "soft_deleted"}
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    except Exception as e:
        logger.error(f"softDeleteDeveloper error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def force_developer_password_reset(auth: MCPAuthContext, developer_id: int) -> Dict[str, Any]:
    """DESTRUCTIVE: force-send a password reset email to a developer. Admin only."""
    if developer_id is None:
        return {"error": "developer_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/developers/{int(developer_id)}/force-password-reset")


async def gift_provisioning(auth: MCPAuthContext, developer_id: int, months: int, reason: str) -> Dict[str, Any]:
    """DESTRUCTIVE: gift cloud-op provisioning months to a developer. Admin only."""
    if developer_id is None or months is None or not reason:
        return {"error": "developer_id, months and reason are required"}
    return await _admin_post(
        auth, f"/api/v1/admin/developers/{int(developer_id)}/gift-provisioning",
        json_body={"months": int(months), "reason": reason},
    )


async def patch_developer_quota(auth: MCPAuthContext, developer_id: int, quota_updates: Dict[str, Any]) -> Dict[str, Any]:
    """DESTRUCTIVE: update developer resource quotas. Admin only."""
    if developer_id is None or not isinstance(quota_updates, dict):
        return {"error": "developer_id and quota_updates object are required"}
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            r = await client.patch(
                f"{REGISTRY_SELF_URL}/api/v1/admin/developers/{int(developer_id)}/quota",
                json=quota_updates,
                headers={"Authorization": f"Bearer {effective_token}", "Content-Type": "application/json"},
            )
        if r.status_code in (200, 201, 204):
            try: return r.json()
            except Exception: return {"status": "patched"}
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    except Exception as e:
        logger.error(f"patchDeveloperQuota error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def block_federation_agent(auth: MCPAuthContext, agent_did: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: block a federated agent (cross-registry block — adds to local blocklist). Admin only."""
    if not agent_did:
        return {"error": "agent_did is required"}
    body: Dict[str, Any] = {}
    if reason:
        body["reason"] = reason
    return await _admin_post(auth, f"/api/v1/federation/admin/agents/{seg(agent_did)}/block", json_body=body)


async def unblock_federation_agent(auth: MCPAuthContext, agent_did: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: unblock a federated agent (removes from local blocklist). Admin only."""
    if not agent_did:
        return {"error": "agent_did is required"}
    body: Dict[str, Any] = {}
    if reason:
        body["reason"] = reason
    return await _admin_post(auth, f"/api/v1/federation/admin/agents/{seg(agent_did)}/unblock", json_body=body)


async def federation_cli_audit(
    auth: MCPAuthContext, action: str, cli_version: str, actor_host: str, actor_user: str,
    dry_run: bool = False, exit_code: int = 0, duration_ms: float = 0.0, extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Answers an error to every MCP caller (§MCPTEST30, V0549): the route takes the operator CLI's federation licence
    header, which this tool does not send; the CLI (tp-operator) calls the route itself."""
    if not action or not cli_version or not actor_host or not actor_user:
        return {"error": "action, cli_version, actor_host and actor_user are required"}
    body: Dict[str, Any] = {"action": action, "cli_version": cli_version, "actor_host": actor_host,
                            "actor_user": actor_user, "dry_run": bool(dry_run), "exit_code": int(exit_code),
                            "duration_ms": float(duration_ms)}
    if extra:
        body["extra"] = extra
    return await _admin_post(auth, "/api/v1/federation/cli-audit", json_body=body)


# ===========================================================================
# §pass70 Sprint 14 — Admin (20 new — operator-applications + api-test + peer card + health-check variant)
# ===========================================================================

# ── OPERATOR APPLICATIONS (10 — all sovereign-mainframe-only; 404 mainframe_only on a cloud operator) ──

async def list_admin_operator_applications(auth: MCPAuthContext, status: Optional[str] = None) -> Dict[str, Any]:
    """List operator applications (pending/approved/rejected/active). Sovereign-mainframe-only. Admin only."""
    params: Dict[str, Any] = {}
    if status:
        params["status"] = status
    return await _admin_get(auth, "/api/v1/admin/operator-applications", params=params)


async def get_admin_operator_application(auth: MCPAuthContext, application_id: str) -> Dict[str, Any]:
    """Get full detail of a single operator application. Sovereign-mainframe-only. Admin only."""
    if not application_id:
        return {"error": "application_id is required"}
    return await _admin_get(auth, f"/api/v1/admin/operator-applications/{seg(application_id)}")


async def approve_operator_application(auth: MCPAuthContext, application_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: approve an operator application (next step: provisionCloudOperator). Sovereign-mainframe-only."""
    if not application_id:
        return {"error": "application_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/operator-applications/{seg(application_id)}/approve")


async def reject_operator_application(auth: MCPAuthContext, application_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: reject an operator application. Sovereign-mainframe-only."""
    if not application_id:
        return {"error": "application_id is required"}
    body: Dict[str, Any] = {}
    if reason:
        body["notes"] = reason   # §MCPTEST30 (2026-10-01): the survey's BODY_UNDECLARED class: the route records the rejection reason as `notes`
    return await _admin_post(auth, f"/api/v1/admin/operator-applications/{seg(application_id)}/reject", json_body=body)


async def suspend_operator(auth: MCPAuthContext, application_id: str, reason: str) -> Dict[str, Any]:
    """DESTRUCTIVE: suspend an operator (freezes registry, keeps data). Sovereign-mainframe-only."""
    if not application_id or not reason:
        return {"error": "application_id and reason are required"}
    return await _admin_post(auth, f"/api/v1/admin/operator-applications/{seg(application_id)}/suspend-operator", json_body={"reason": reason})


async def reinstate_operator(auth: MCPAuthContext, application_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: reinstate a suspended operator. Sovereign-mainframe-only."""
    if not application_id:
        return {"error": "application_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/operator-applications/{seg(application_id)}/reinstate-operator")


async def revoke_operator_access(auth: MCPAuthContext, application_id: str, reason: str) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: revoke operator access (license invalidation — followed by teardown). Sovereign-mainframe-only."""
    if not application_id or not reason:
        return {"error": "application_id and reason are required"}
    return await _admin_post(auth, f"/api/v1/admin/operator-applications/{seg(application_id)}/revoke-operator", json_body={"reason": reason})


async def rotate_operator_pull_token(auth: MCPAuthContext, application_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: rotate operator's pull-token (forces operator to re-fetch new image-registry token). Sovereign-mainframe-only."""
    if not application_id:
        return {"error": "application_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/operator-applications/{seg(application_id)}/rotate-pull-token")


async def backfill_pull_tokens(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE: backfill pull-tokens for all operators (one-off migration helper). Sovereign-mainframe-only."""
    return await _admin_post(auth, "/api/v1/admin/operator-applications/backfill-pull-tokens")


async def admin_download_operator_bundle(auth: MCPAuthContext, application_id: str) -> Dict[str, Any]:
    """Admin: download an operator's bundle (signed config + license).

    §MCPTEST30 (V0650, agentvault2-d3): the answer names the bundle (type, size, its sha256), never its bytes. It carried
    the first 100 bytes as hex (encoded_preview_hex): the start of a gzip of the operator's credentials, decompressible,
    in every MCP caller's transcript. A digest lets a caller check a download it makes through the route itself."""
    if not application_id:
        return {"error": "application_id is required"}
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/admin/operator-applications/{seg(application_id)}/bundle",
                headers={"Authorization": f"Bearer {effective_token}"},
            )
        if r.status_code == 200:
            return {"application_id": application_id, "content_type": r.headers.get("content-type"),
                    "size_bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest()}
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    except Exception as e:
        logger.error(f"adminDownloadOperatorBundle error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ── API TESTER admin (8) ──────────────────────────────────────────────────

async def get_api_test_archive_runs(auth: MCPAuthContext) -> Dict[str, Any]:
    """List archived API test runs (history of past full-suite executions)."""
    return await _admin_get(auth, "/api/v1/admin/api-test/archive/runs")


async def get_api_test_endpoints(auth: MCPAuthContext) -> Dict[str, Any]:
    """List all API endpoints covered by the api-tester framework (organized by category)."""
    return await _admin_get(auth, "/api/v1/admin/api-test/endpoints")


async def get_api_test_flow_values(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get current api-tester flow values (state for chained test scenarios)."""
    return await _admin_get(auth, "/api/v1/admin/api-test/flow-values")


async def reset_api_test_flow_values(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE: reset api-tester flow values (clears chained-scenario state)."""
    return await _admin_post(auth, "/api/v1/admin/api-test/reset-flow-values")


async def test_api_endpoint(
    auth: MCPAuthContext,
    endpoint_path: str,
    method: str = "GET",
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Test a single API endpoint through the api-tester framework. Returns response code + body + auth path used."""
    if not endpoint_path:
        return {"error": "endpoint_path is required"}
    # §MCPTEST30 (V0550): the route reads `path` (endpoint_test.get("path", "")); the tool sent "endpoint_path", so every
    # call tested an empty path (round 15: a bare 404; a ReadTimeout when called again). The survey's BODY_UNREAD class.
    request_body: Dict[str, Any] = {"path": endpoint_path, "method": method}
    if body is not None:
        request_body["body"] = body
    return await _admin_post(auth, "/api/v1/admin/api-test/test-endpoint", json_body=request_body,
                             timeout=API_TEST_ENDPOINT_TIMEOUT)


async def eager_bootstrap_api_test(auth: MCPAuthContext) -> Dict[str, Any]:
    """Eagerly bootstrap all api-tester session fixtures (warm up test data)."""
    return await _admin_post(auth, "/api/v1/admin/api-test/eager-bootstrap")


async def get_api_test_sandbox_credentials(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get sandbox test credentials (developer + agent JWT scaffolds for api-tester)."""
    return await _admin_get(auth, "/api/v1/admin/api-test/sandbox-credentials")


async def get_api_test_bucket_classification(auth: MCPAuthContext) -> Dict[str, Any]:
    """Per-category bucket classification (how api-tester partitions endpoints into parallel buckets)."""
    return await _admin_get(auth, "/api/v1/admin/api-test/bucket-classification")


# ── REMAINING ──────────────────────────────────────────────────────────────

async def get_peer_registry_card(auth: MCPAuthContext, peer_id: str) -> Dict[str, Any]:
    """View a federated peer's cached Registry Card v0.6. Admin only."""
    if not peer_id:
        return {"error": "peer_id is required"}
    return await _admin_get(auth, f"/api/v1/admin/peer-registries/{seg(peer_id)}/card")


async def get_health_check_with_agent_auth(auth: MCPAuthContext) -> Dict[str, Any]:
    """Health check using bundled agent credentials (tests full stack: dev + agent auth + TEG + ES). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/health-check/with-agent-auth", timeout=DIAGNOSTIC_TIMEOUT)


# ===========================================================================
# §pass70 Sprint 15 — Admin (30 new — federation admin + ironhand + attestation admin)
# ===========================================================================

# ── FEDERATION ADMIN (20) ─────────────────────────────────────────────────

async def get_admission_status(auth: MCPAuthContext, admission_id: str) -> Dict[str, Any]:
    """Status of a federation admission request (in-progress workflow)."""
    if not admission_id:
        return {"error": "admission_id is required"}
    return await _admin_get(auth, f"/api/v1/admin/federation/admission-status/{seg(admission_id)}")


async def complete_admission(auth: MCPAuthContext, admission_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: complete an admission workflow (finalize peer onboarding). Admin only."""
    if not admission_id:
        return {"error": "admission_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/federation/complete-admission/{seg(admission_id)}")


async def get_federation_compliance_drifts(auth: MCPAuthContext) -> Dict[str, Any]:
    """List federation compliance drift events (peer drift from declared policy). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/federation/compliance/drifts")


async def get_federation_compliance_enforcement_mode(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get current federation compliance enforcement mode (observe/enforce). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/federation/compliance/enforcement-mode")


async def set_federation_compliance_enforcement_mode(auth: MCPAuthContext, mode: str, reason: str) -> Dict[str, Any]:
    """DESTRUCTIVE: set federation compliance enforcement mode (off / dry_run / enforcing). Admin only."""
    if not mode or not reason:
        return {"error": "mode ('off', 'dry_run' or 'enforcing') and reason are required"}
    return await _admin_post(auth, "/api/v1/admin/federation/compliance/enforcement-mode", json_body={"mode": mode, "reason": reason})


async def get_federation_compliance_events(auth: MCPAuthContext, limit: int = 50) -> Dict[str, Any]:
    """Federation compliance event stream (policy violations, drift detected). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/federation/compliance/events", params={"limit": min(max(int(limit), 1), 500)})


async def get_federation_compliance_overview(auth: MCPAuthContext) -> Dict[str, Any]:
    """Federation compliance overview (per-peer adherence, drift count, last-poll). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/federation/compliance/overview")


async def get_federation_compliance_peer_by_operator(auth: MCPAuthContext, operator_id: str) -> Dict[str, Any]:
    """Get federation compliance peer detail by operator_id."""
    if not operator_id:
        return {"error": "operator_id is required"}
    return await _admin_get(auth, f"/api/v1/admin/federation/compliance/peers/by-operator/{seg(operator_id)}")


async def get_federation_compliance_peer_by_id(auth: MCPAuthContext, peer_id: str) -> Dict[str, Any]:
    """Get federation compliance peer detail by peer_id."""
    if not peer_id:
        return {"error": "peer_id is required"}
    return await _admin_get(auth, f"/api/v1/admin/federation/compliance/peers/{seg(peer_id)}")


async def poll_peer_compliance_now(auth: MCPAuthContext, peer_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: force-poll a peer's compliance now (out-of-band from scheduler). Admin only."""
    if not peer_id:
        return {"error": "peer_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/federation/compliance/peers/{seg(peer_id)}/poll-now")


async def preview_quarantine(auth: MCPAuthContext) -> Dict[str, Any]:
    """Preview which peers would be quarantined if enforce mode were enabled (dry-run). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/federation/compliance/preview-quarantine")


async def federation_drift_scan(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE: trigger an immediate drift scan across all federated peers. Admin only."""
    return await _admin_post(auth, "/api/v1/admin/federation/drift-scan")


async def list_admin_frame_invitations(auth: MCPAuthContext) -> Dict[str, Any]:
    """List frame invitations (incoming cross-frame federation handshakes). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/federation/frame-invitations")


async def get_admin_frame_invitation(auth: MCPAuthContext, invitation_id: str) -> Dict[str, Any]:
    """Get a single frame invitation detail. Admin only."""
    if not invitation_id:
        return {"error": "invitation_id is required"}
    return await _admin_get(auth, f"/api/v1/admin/federation/frame-invitations/{seg(invitation_id)}")


async def approve_frame_invitation(auth: MCPAuthContext, invitation_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: approve a frame invitation (admit cross-frame peer). Admin only."""
    if not invitation_id:
        return {"error": "invitation_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/federation/frame-invitations/{seg(invitation_id)}/approve")


async def reject_frame_invitation(auth: MCPAuthContext, invitation_id: str, reason: str) -> Dict[str, Any]:
    """DESTRUCTIVE: reject a frame invitation. Admin only."""
    if not invitation_id or not reason:
        return {"error": "invitation_id and reason are required"}
    return await _admin_post(auth, f"/api/v1/admin/federation/frame-invitations/{seg(invitation_id)}/reject", json_body={"reason": reason})


async def finalize_retry_frame_invitation(auth: MCPAuthContext, invitation_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: retry finalization of a frame invitation (use when initial finalize failed). Admin only."""
    if not invitation_id:
        return {"error": "invitation_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/federation/frame-invitations/{seg(invitation_id)}/finalize-retry")


async def get_frames_spire_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Cross-frame SPIRE status (mTLS handshake health per remote frame). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/federation/frames/spire-status")


async def resync_frame_eventstore(auth: MCPAuthContext, peer_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: resync EventStore from a cross-frame peer (re-fetches missing events). Admin only."""
    if not peer_id:
        return {"error": "peer_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/federation/frames/{seg(peer_id)}/resync-eventstore")


async def revoke_frame(auth: MCPAuthContext, peer_id: str, reason: str) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: revoke a cross-frame peer (severs federation, halts cross-frame transfers). Admin only."""
    if not peer_id or not reason:
        return {"error": "peer_id and reason are required"}
    return await _admin_post(auth, f"/api/v1/admin/federation/frames/{seg(peer_id)}/revoke", json_body={"reason": reason})


# ── FEDERATION LICENSES + ADMIN MISC (5) ──────────────────────────────────

async def list_federation_licenses(auth: MCPAuthContext) -> Dict[str, Any]:
    """List federation licenses issued by this registry (peer admission tokens). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/federation/licenses")


async def generate_federation_license(
    auth: MCPAuthContext, operator_name: str, operator_did: str, max_agents: Optional[int] = None,
    max_events_per_minute: Optional[int] = None, federation_tier: Optional[str] = None,
    min_image_version: Optional[str] = None, licensee_type: Optional[str] = None,
) -> Dict[str, Any]:
    """DESTRUCTIVE: generate a new federation license (peer admission token). Admin only."""
    if not operator_name or not operator_did:
        return {"error": "operator_name and operator_did are required"}
    body: Dict[str, Any] = {"operator_name": operator_name, "operator_did": operator_did}
    for k, v in (("max_agents", max_agents), ("max_events_per_minute", max_events_per_minute),
                 ("federation_tier", federation_tier), ("min_image_version", min_image_version),
                 ("licensee_type", licensee_type)):
        if v is not None:
            body[k] = v
    return await _admin_post(auth, "/api/v1/admin/federation/licenses/generate", json_body=body)


async def get_federation_topology_overview(auth: MCPAuthContext) -> Dict[str, Any]:
    """Federation topology overview (peer graph, frame chains, mesh health). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/federation/topology-overview")


async def probe_topology_peer(auth: MCPAuthContext, peer_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: actively probe a peer (HTTP+SPIFFE handshake + topology fetch). Admin only."""
    if not peer_id:
        return {"error": "peer_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/federation/topology/peers/{seg(peer_id)}/probe")


async def validate_federation_policy(auth: MCPAuthContext, policy: Dict[str, Any]) -> Dict[str, Any]:
    """Dry-run validate a federation policy JSON. Admin only."""
    if not isinstance(policy, dict):
        return {"error": "policy must be an object"}
    return await _admin_post(auth, "/api/v1/admin/federation/validate-policy", json_body={"policy_json": policy})


# ── ATTESTATIONS ADMIN (3) + IRONHAND (3) ─────────────────────────────────

async def run_attestation_expiry_sweep(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE: run one attestation expiry sweep now (sandbox registries only; elsewhere 403). It emits one
    AttestationExpired event for each unrevoked attestation past its expires_at and marks it, so a second run emits
    nothing; it revokes nothing. Admin only."""
    return await _admin_post(auth, "/api/v1/attestations/admin/run-expiry-sweep")


async def run_attestation_schedule_cron(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE: force-run attestation schedule cron (out-of-band). Admin only."""
    return await _admin_post(auth, "/api/v1/attestations/admin/run-schedule-cron")


async def admin_revoke_attestation(auth: MCPAuthContext, attestation_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: admin-revoke an attestation by id (override agent self-revoke). Re-verify then answers verified
    false; the reputation point is taken back only from the attestation that got it. Admin only."""
    if not attestation_id:
        return {"error": "attestation_id is required"}
    body: Dict[str, Any] = {}
    if reason:
        body["reason"] = reason
    return await _admin_post(auth, f"/api/v1/attestations/admin/{seg(attestation_id)}/revoke", json_body=body)


async def ironhand_enroll_agent(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """DESTRUCTIVE: admin enroll/re-enroll an agent in IRONHAND mTLS. Admin only."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _admin_post(auth, f"/api/v1/admin/ironhand/enroll/{seg(agent_did)}")


async def ironhand_revoke_agent(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """DESTRUCTIVE: admin revoke an agent's IRONHAND mTLS identity. Admin only."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _admin_post(auth, f"/api/v1/admin/ironhand/revoke/{seg(agent_did)}")


async def delete_spire_orphan(auth: MCPAuthContext, spiffe_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: delete an orphan SPIRE entry (cleanup after agent deletion). Admin only. Agent entries only."""
    if not spiffe_id:
        return {"error": "spiffe_id is required"}
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            r = await client.request(
                "DELETE",
                f"{REGISTRY_SELF_URL}/api/v1/admin/ironhand/spire-entry",
                json={"spiffe_id": spiffe_id},
                headers={"Authorization": f"Bearer {effective_token}", "Content-Type": "application/json"},
            )
        if r.status_code in (200, 201, 204):
            try: return r.json()
            except Exception: return {"status": "deleted"}
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    except Exception as e:
        logger.error(f"deleteSpireOrphan error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ===========================================================================
# §pass70 Sprint 16 — Admin (20 new — federation remainder + ironhand proxy + sandbox + frame lifecycle)
# ===========================================================================

async def get_federation_local_events(auth: MCPAuthContext, limit: int = 50) -> Dict[str, Any]:
    """Federation local-events stream (federation activity originated from this registry). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/federation/local-events", params={"limit": min(max(int(limit), 1), 200)})


async def get_all_federation_peers_admin(auth: MCPAuthContext) -> Dict[str, Any]:
    """List ALL federation peers (incl. inactive/deleted — admin variant of listFederationPeers). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/federation/peers/all")


async def get_admin_federation_policy_compliance(auth: MCPAuthContext) -> Dict[str, Any]:
    """Admin federation policy compliance overview. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/federation/policy-compliance")


async def federation_policy_update_request(
    auth: MCPAuthContext, peer_did: str, proposed_policy_json: Dict[str, Any],
    change_summary: str = "", effective_date: Optional[str] = None,
) -> Dict[str, Any]:
    """DESTRUCTIVE: request a peer to update their policy. Admin only."""
    if not peer_did or not isinstance(proposed_policy_json, dict):
        return {"error": "peer_did and proposed_policy_json object are required"}
    body: Dict[str, Any] = {"peer_did": peer_did, "proposed_policy_json": proposed_policy_json, "change_summary": change_summary or ""}
    if effective_date:
        body["effective_date"] = effective_date
    return await _admin_post(auth, "/api/v1/admin/federation/policy-update-request", json_body=body)


async def federation_request_admission(
    auth: MCPAuthContext, registry_name: str, registry_operator_did: str, registry_public_url: str,
    admin_contact_email: str, policy_json: Dict[str, Any], operator_identity_proof: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """DESTRUCTIVE: request admission to a foreign federated network. Admin only."""
    if not registry_name or not registry_operator_did or not registry_public_url or not admin_contact_email \
            or not isinstance(policy_json, dict):
        return {"error": "registry_name, registry_operator_did, registry_public_url, admin_contact_email and a policy_json object are required"}
    body: Dict[str, Any] = {"registry_name": registry_name, "registry_operator_did": registry_operator_did,
                            "registry_public_url": registry_public_url, "admin_contact_email": admin_contact_email,
                            "policy_json": policy_json}
    if operator_identity_proof:
        body["operator_identity_proof"] = operator_identity_proof
    return await _admin_post(auth, "/api/v1/admin/federation/request-admission", json_body=body)


async def get_admin_federation_self_health(auth: MCPAuthContext) -> Dict[str, Any]:
    """Self-health from federation perspective (am I being seen as healthy by peers?). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/federation/self-health")


async def get_topology_peer_events(auth: MCPAuthContext, peer_id: str, limit: int = 50) -> Dict[str, Any]:
    """Events for a single peer in the federation topology. Admin only."""
    if not peer_id:
        return {"error": "peer_id is required"}
    return await _admin_get(auth, f"/api/v1/admin/federation/topology/peers/{seg(peer_id)}/events", params={"limit": min(max(int(limit), 1), 100)})


async def get_federation_license_detail(auth: MCPAuthContext, license_id: str) -> Dict[str, Any]:
    """Get detail for a single federation license. Admin only."""
    if not license_id:
        return {"error": "license_id is required"}
    return await _admin_get(auth, f"/api/v1/admin/federation/licenses/{seg(license_id)}")


async def delete_federation_license(auth: MCPAuthContext, license_id: str) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: hard-delete a federation license. Admin only."""
    if not license_id:
        return {"error": "license_id is required"}
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            r = await client.delete(
                f"{REGISTRY_SELF_URL}/api/v1/admin/federation/licenses/{seg(license_id)}",
                headers={"Authorization": f"Bearer {effective_token}"},
            )
        if r.status_code in (200, 201, 204):
            try: return r.json()
            except Exception: return {"status": "deleted"}
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    except Exception as e:
        logger.error(f"deleteFederationLicense error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def reinstate_federation_license(auth: MCPAuthContext, license_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: reinstate a suspended/revoked federation license. Admin only."""
    if not license_id:
        return {"error": "license_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/federation/licenses/{seg(license_id)}/reinstate")


async def revoke_federation_license(auth: MCPAuthContext, license_id: str, reason: str) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: revoke a federation license (peer drops from federation). Admin only."""
    if not license_id or not reason:
        return {"error": "license_id and reason are required"}
    return await _admin_post(auth, f"/api/v1/admin/federation/licenses/{seg(license_id)}/revoke", json_body={"reason": reason})


async def suspend_federation_license(auth: MCPAuthContext, license_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: suspend a federation license (temporary, reversible via reinstate). Admin only."""
    if not license_id:
        return {"error": "license_id is required"}
    body: Dict[str, Any] = {}
    if reason: body["reason"] = reason
    return await _admin_post(auth, f"/api/v1/admin/federation/licenses/{seg(license_id)}/suspend", json_body=body)


async def ironhand_delete_agent_proxy(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """DESTRUCTIVE (federation-auth): delete an agent's SPIRE entry on behalf of a peer operator. Admin only."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _admin_post(auth, "/api/v1/admin/ironhand/delete-agent-proxy", json_body={"agent_did": agent_did})


async def ironhand_register_agent_proxy(auth: MCPAuthContext, agent_did: str, spire_data: Dict[str, Any]) -> Dict[str, Any]:
    """DESTRUCTIVE (federation-auth): register an agent's SPIRE entry on behalf of a peer operator. Admin only."""
    if not agent_did or not isinstance(spire_data, dict):
        return {"error": "agent_did and spire_data object are required"}
    body: Dict[str, Any] = {"agent_did": agent_did, **spire_data}
    return await _admin_post(auth, "/api/v1/admin/ironhand/register-agent-proxy", json_body=body)


# ===========================================================================
# §pass70 Sprint 17 — Admin (12 new — agent-card-drift mutations + broadcast variants + api-test extra)
# ===========================================================================

async def get_agent_card_drift_detail(auth: MCPAuthContext, did: str) -> Dict[str, Any]:
    """Get drift diff for one agent. Admin only."""
    if not did:
        return {"error": "did is required"}
    return await _admin_get(auth, f"/api/v1/admin/agent-card-drift/{seg(did)}")


async def force_register_agent_card(auth: MCPAuthContext, did: str) -> Dict[str, Any]:
    """DESTRUCTIVE: force-register drift state (mark as canonical). Admin only."""
    if not did:
        return {"error": "did is required"}
    return await _admin_post(auth, f"/api/v1/admin/agent-card-drift/{seg(did)}/force-register")


async def refresh_agent_card_drift(auth: MCPAuthContext, did: str) -> Dict[str, Any]:
    """Refresh drift state by re-pulling agent card from /.well-known. Admin only."""
    if not did:
        return {"error": "did is required"}
    return await _admin_post(auth, f"/api/v1/admin/agent-card-drift/{seg(did)}/refresh")


async def get_broadcast_template_detail(auth: MCPAuthContext, template_id: str) -> Dict[str, Any]:
    """Get one admin broadcast email template's full content (id, label, title_template,
    body_template, broadcast_type, send_email, requires_ack, cta_url, cta_label, created_at).
    There is NO GET-by-id route server-side (only LIST + DELETE), so this fetches the
    template LIST (scoped to the calling admin, same as DELETE's owner-only rule) and
    returns the one matching template_id. Admin only."""
    if not template_id:
        return {"error": "template_id is required"}
    body = await _admin_get(auth, "/api/v1/admin/broadcast-templates")
    if isinstance(body, dict) and body.get("error"):
        return body
    items = body if isinstance(body, list) else (body.get("templates") or [] if isinstance(body, dict) else [])
    for t in items:
        if isinstance(t, dict) and str(t.get("id")) == str(template_id):
            return t
    return {"error": f"Broadcast template {template_id} not found"}


async def get_broadcast_email_retry_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Broadcast email retry queue status (pending retries, success rate). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/broadcast-email-retry/status")


async def get_broadcast_email_retry_dead_letter(auth: MCPAuthContext) -> Dict[str, Any]:
    """Broadcast email dead-letter queue (emails that failed all retries). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/broadcast-email-retry/dead-letter")


async def get_broadcast_scheduler_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Broadcast scheduler subsystem status. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/broadcast-scheduler/status")


async def reset_api_test_sandbox(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE: reset the api-tester sandbox database (clears test pollution). Admin only."""
    return await _admin_post(auth, "/api/v1/admin/api-test/reset-sandbox")


async def run_all_api_tests(auth: MCPAuthContext) -> Dict[str, Any]:
    """Run the full API-test suite (heavy — sequential through all 600+ endpoints). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/api-test/run-all")


async def test_api_category(auth: MCPAuthContext, category: str) -> Dict[str, Any]:
    """Test all endpoints in a given category (e.g. 'auth', 'staking', 'teg'). Admin only."""
    if not category:
        return {"error": "category is required"}
    return await _admin_post(auth, "/api/v1/admin/api-test/test-category", json_body={"category": category},
                             timeout=API_TEST_RUN_TIMEOUT)


async def test_api_flow(auth: MCPAuthContext, flow_name: str) -> Dict[str, Any]:
    """Test a complete API flow (multi-step scenario by name). Admin only."""
    if not flow_name:
        return {"error": "flow_name is required"}
    return await _admin_post(auth, "/api/v1/admin/api-test/test-flow", json_body={"flow_name": flow_name},
                             timeout=API_TEST_RUN_TIMEOUT)


async def get_attestations_analytics(auth: MCPAuthContext) -> Dict[str, Any]:
    """Aggregate attestation analytics for the admin dashboard. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/attestations/analytics")


# ===========================================================================
# §pass70 Sprint 18 — Admin (4 new — bridge mutations)
# ===========================================================================

async def bridge_mint_wrapped(auth: MCPAuthContext, agent_did: str, amount: str, source_frame: str) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: mint wrapped AVT on this frame after cross-frame bridge transfer (sovereign-mainframe-only). Admin only."""
    if not agent_did or not amount or not source_frame:
        return {"error": "agent_did, amount, source_frame are required"}
    return await _admin_post(auth, "/api/v1/bridge/mint-wrapped", json_body={"agent_did": agent_did, "amount": amount, "source_frame": source_frame})


async def bridge_redeem(auth: MCPAuthContext, bridge_tx_id: str, agent_did: str) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: redeem wrapped units (burns wrapped, unlocks original). Admin only."""
    if not bridge_tx_id or not agent_did:
        return {"error": "bridge_tx_id and agent_did are required"}
    return await _admin_post(auth, "/api/v1/bridge/redeem", json_body={"bridge_tx_id": bridge_tx_id, "agent_did": agent_did})


async def bridge_unlock(auth: MCPAuthContext, bridge_tx_id: str) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: unlock bridged AVT on source frame after redeem confirmation. Admin only."""
    if not bridge_tx_id:
        return {"error": "bridge_tx_id is required"}
    return await _admin_post(auth, "/api/v1/bridge/unlock", json_body={"bridge_tx_id": bridge_tx_id})


async def get_bridge_status(auth: MCPAuthContext, bridge_tx_id: str) -> Dict[str, Any]:
    """Get status of a cross-frame bridge transfer by tx_id. Admin only."""
    if not bridge_tx_id:
        return {"error": "bridge_tx_id is required"}
    return await _admin_get(auth, f"/api/v1/bridge/status/{seg(bridge_tx_id)}")


# ===========================================================================
# §pass70 Sprint 19 — Admin (8 new)
# ===========================================================================

async def list_admin_bundles_reports(auth: MCPAuthContext) -> Dict[str, Any]:
    """List pending bundle moderation reports. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/bundles/reports")


async def dismiss_bundle_report(auth: MCPAuthContext, report_id: str, resolution: str, note: Optional[str] = None) -> Dict[str, Any]:
    """Dismiss a bundle report (clear from queue without taking action). Admin only."""
    if not report_id or not resolution:
        return {"error": "report_id and resolution are required"}
    body: Dict[str, Any] = {"resolution": resolution}
    if note:
        body["note"] = note
    return await _admin_post(auth, f"/api/v1/admin/bundles/reports/{seg(report_id)}/dismiss", json_body=body)


async def hide_bundle(auth: MCPAuthContext, bundle_id: str, reason: str) -> Dict[str, Any]:
    """DESTRUCTIVE: hide a bundle from marketplace (soft-removal — keeps row). Admin only."""
    if not bundle_id or not reason:
        return {"error": "bundle_id and reason are required"}
    return await _admin_post(auth, f"/api/v1/admin/bundles/{seg(bundle_id)}/hide", json_body={"reason": reason})


async def unhide_bundle(auth: MCPAuthContext, bundle_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: unhide a previously-hidden bundle (restores to marketplace). Admin only."""
    if not bundle_id:
        return {"error": "bundle_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/bundles/{seg(bundle_id)}/unhide")


async def get_canary_ironhand_svids(auth: MCPAuthContext) -> Dict[str, Any]:
    """IRONHAND canary SVID health crossref (which SPIRE entries match active canary paths). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/canary-ironhand/svids")


async def get_collusion_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Collusion detector worker status (last cycle, agents under review). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/collusion/status")


async def get_admin_metrics_agent_activity(auth: MCPAuthContext) -> Dict[str, Any]:
    """Aggregate agent-activity metrics (TPS, registries with active load, error rate). Admin only."""
    return await _admin_get(auth, "/api/v1/metrics/agent-activity")


async def get_admin_collusion_by_agent(auth: MCPAuthContext, agent_did: str, limit: int = 50) -> Dict[str, Any]:
    """Collusion rings flagged for one agent (the rings feed filtered by agent_did). Admin only."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _admin_get(auth, "/api/v1/admin/collusion/rings",
                            params={"agent_did": agent_did, "limit": min(max(int(limit), 1), 200)})


# ===========================================================================
# §pass70 Sprint 20 — Admin (20 new)
# ===========================================================================

async def get_supply_auditor_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Supply auditor worker status. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/supply-auditor/status")


async def get_supply_auditor_events(auth: MCPAuthContext, limit: int = 50) -> Dict[str, Any]:
    """Recent supply auditor events (any drift incidents). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/supply-auditor/events", params={"limit": min(max(int(limit), 1), 200)})


async def get_admin_workers_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Status of all background workers (leader status, last cycle). Admin only."""
    return await _admin_get(auth, "/api/v1/admin/workers/status", timeout=DIAGNOSTIC_TIMEOUT)


async def search_admin_events(auth: MCPAuthContext, event_type: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    """Search admin events with filters. Admin only."""
    params: Dict[str, Any] = {"limit": min(max(int(limit), 1), 500)}
    if event_type: params["event_type"] = event_type   # §MCPTEST30 (2026-10-01): the survey's UNDECLARED class: there is no free-text `query`; it was dropped
    return await _admin_get(auth, "/api/v1/admin/events/search", params=params)


async def get_events_aggregate(auth: MCPAuthContext, aggregate_id: str) -> Dict[str, Any]:
    """Get all events for a specific aggregate_id (agent_did or other). Admin only."""
    if not aggregate_id:
        return {"error": "aggregate_id is required"}
    return await _admin_get(auth, f"/api/v1/admin/events/aggregate/{seg(aggregate_id)}")


async def upload_registry_card_icon(auth: MCPAuthContext, icon_b64: str, content_type: str = "image/png") -> Dict[str, Any]:
    """DESTRUCTIVE: upload icon for this registry's Registry Card. Admin only.

    §MCPSWEEP 2026-09-27: the route takes a MULTIPART `file` (PNG or JPEG, <= 500 KB, checked before it is written),
    and this tool used to POST JSON, so every call answered 422 and no icon could ever be set through MCP. The base64
    is decoded here and sent as the file; the route's own validation is unchanged."""
    if not icon_b64:
        return {"error": "icon_b64 is required"}
    try:
        raw = base64.b64decode(icon_b64, validate=True)
    except (binascii.Error, ValueError):
        return {"error": "icon_b64 is not valid base64"}
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    ctype = content_type or "image/png"
    ext = "jpg" if ("jpeg" in ctype.lower() or "jpg" in ctype.lower()) else "png"
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/admin/registry-card/icon",
                files={"file": (f"icon.{ext}", raw, ctype)},
                headers={"Authorization": f"Bearer {effective_token}"},
            )
        if r.status_code in (200, 201, 204):
            try:
                return r.json()
            except Exception:
                return {"status": "ok"}
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    except Exception as e:
        logger.error(f"upload_registry_card_icon error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def distribute_from_fee_collector(auth: MCPAuthContext, target_agent_did: str, amount: str, reason: str,
                                        reference_id: Optional[str] = None) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: pay units from this frame's fee account to an agent, by hand (one TEG transfer, no fee).
    Admin only (admin_treasury).

    V0650 (agentvault2-d3, tester batch 1): the route has always required `target_agent_did` (400 "Missing
    target_agent_did") and this tool never sent it, so no call through MCP could succeed; the route reads a raw body, so
    the request-shape gate (tests/test_mcp_tool_requests_meet_their_routes.py) could not see it."""
    if not target_agent_did or not amount or not reason:
        return {"error": "target_agent_did, amount and reason are required"}
    body: Dict[str, Any] = {"target_agent_did": target_agent_did, "amount": amount, "reason": reason}
    if reference_id:
        body["reference_id"] = reference_id
    return await _admin_post(auth, "/api/v1/admin/fee-collector/distribute", json_body=body)


async def generate_invite_codes(auth: MCPAuthContext, count: int = 1, note: Optional[str] = None) -> Dict[str, Any]:
    """Generate N new invite codes for developer signup. Admin only."""
    body: Dict[str, Any] = {"count": int(count)}
    if note: body["note"] = note
    return await _admin_post(auth, "/api/v1/admin/invite-codes/generate", json_body=body)


async def validate_invite_code_admin(auth: MCPAuthContext, code: str) -> Dict[str, Any]:
    """Validate an invite code (admin variant — same as public but admin context)."""
    if not code:
        return {"error": "code is required"}
    return await _admin_get(auth, f"/api/v1/admin/invite-codes/validate/{seg(code)}")


async def revoke_invite_code(auth: MCPAuthContext, code: str) -> Dict[str, Any]:
    """DESTRUCTIVE: revoke an invite code. Admin only."""
    if not code:
        return {"error": "code is required"}
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            r = await client.delete(
                f"{REGISTRY_SELF_URL}/api/v1/admin/invite-codes/{seg(code)}",
                headers={"Authorization": f"Bearer {effective_token}"},
            )
        if r.status_code in (200, 201, 204):
            try: return r.json()
            except Exception: return {"status": "revoked"}
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    except Exception as e:
        logger.error(f"revokeInviteCode error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def disable_webhook_admin(auth: MCPAuthContext, webhook_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: admin-disable any webhook. Admin only."""
    if not webhook_id:
        return {"error": "webhook_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/webhooks/{seg(webhook_id)}/disable")


async def enable_webhook_admin(auth: MCPAuthContext, webhook_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: admin-re-enable any webhook. Admin only."""
    if not webhook_id:
        return {"error": "webhook_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/webhooks/{seg(webhook_id)}/enable")


async def test_webhook_admin(auth: MCPAuthContext, webhook_id: str) -> Dict[str, Any]:
    """Admin: send test event to ANY webhook. Admin only."""
    if not webhook_id:
        return {"error": "webhook_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/webhooks/{seg(webhook_id)}/test")


async def get_tutorial_health(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get tutorial sandbox health. Admin only."""
    return await _admin_get(auth, "/api/v1/admin/tutorial/health")


_TUTORIAL_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_TUTORIAL_AUTH = ("none", "developer", "agent", "bootstrap", "admin")


async def execute_tutorial(auth: MCPAuthContext, method: str = "", path: str = "",
                           body: Optional[Dict[str, Any]] = None, auth_type: str = "none",
                           auth_token: Optional[str] = None, tutorial_id: Optional[str] = None,
                           args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Execute ONE API call against the tutorial sandbox (this frame's API test target) as the token passed (auth_type
    "none": anonymous): POST /admin/tutorial/execute, the route the Tutorials pages drive. DESTRUCTIVE when the call
    writes. Returns the sandbox's status_code, response and response_time.

    §MCPTEST30 (2026-10-01): this tool sent {tutorial_id, args}, which the route never reads (it takes method, path,
    body, auth_type and auth_token), so every call ran GET <sandbox>/api/v1 whatever was asked; its success then
    reached the client as `Error: None` (mcp/tool_result.py). `tutorial_id` and `args` are refused by name."""
    if tutorial_id is not None or args is not None:
        return {"error": "executeTutorial executes one API call: name `method` and `path` (and `body`, `auth_type`, "
                         "`auth_token` as needed); the route has no tutorial id"}
    m = (method or "").upper()
    if m not in _TUTORIAL_METHODS:
        return {"error": f"method must be one of {', '.join(_TUTORIAL_METHODS)}"}
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        return {"error": "path is the API path after /api/v1 and starts with a single / (e.g. /public/registry-config)"}
    if auth_type not in _TUTORIAL_AUTH:
        return {"error": f"auth_type must be one of {', '.join(_TUTORIAL_AUTH)}"}
    payload: Dict[str, Any] = {"method": m, "path": path, "auth_type": auth_type}
    if body is not None:
        payload["body"] = body
    if auth_token:
        payload["auth_token"] = auth_token
    return await _admin_post(auth, "/api/v1/admin/tutorial/execute", json_body=payload)


async def generate_tutorial_proof(
    auth: MCPAuthContext, circuit_id: str = "", tutorial_id: str = "", agent_did: str = "",
) -> Dict[str, Any]:
    """Generate a real UltraHonk proof for a tutorial circuit: any of the four v2.0.0 circuits
    (fairMarkupPolicy, accurateResourceUsagePolicy, fairCrossRegistryFee, contentSafetyAttestation; the v1.0.0 ids
    are answered with the v2.0.0 proof). agent_did is required (the route answers 400 without it): the proof's
    reference is derive_reference(agent_did, a random label), so only that agent can submit it. The registry runs
    nargo and bb with fixed example figures, a random salt and a random label, so every call yields a new proof.
    Answers with {circuit_id, proof_bytes_base64, public_inputs (with reference_label), public_outputs,
    generation_time_ms}, ready for submitAttestation from that agent (proof_data = {"proof_bytes":
    proof_bytes_base64, "format": "ultra_honk"}). Admin only.

    §MCPTEST30 (V0550): the route reads `circuit_id` and nothing else; the tool sent {"tutorial_id"}, so every call
    answered "Unknown circuit: ." (agentvault2-45 found it; the survey's BODY_UNREAD class). `tutorial_id` stays as the
    older name of the same argument."""
    cid = circuit_id or tutorial_id
    if not cid:
        return {"error": "circuit_id is required"}
    if not agent_did:
        return {"error": "agent_did is required: the proof's reference names the agent that will submit it"}
    return await _admin_post(
        auth, "/api/v1/admin/tutorial/generate-proof", json_body={"circuit_id": cid, "agent_did": agent_did},
    )


async def run_diagnostics_subset(auth: MCPAuthContext, checks: list, targets: list) -> Dict[str, Any]:
    """Run a subset of (checks × targets) diagnostics. Admin only."""
    if not isinstance(checks, list) or not isinstance(targets, list):
        return {"error": "checks and targets must be lists"}
    # §MCPTEST30 (2026-10-01): the survey's BODY_UNDECLARED class: the route reads `check_ids`, and an absent one runs EVERY known check: the subset a
    # caller named was never the subset that ran
    return await _admin_post(auth, "/api/v1/admin/diagnostics/run", json_body={"check_ids": checks, "targets": targets})


async def get_diagnostic_config(auth: MCPAuthContext, target_id: str) -> Dict[str, Any]:
    """Read masked config slices for a target. Admin only."""
    if not target_id:
        return {"error": "target_id is required"}
    return await _admin_get(auth, f"/api/v1/admin/diagnostics/config/{seg(target_id)}")


# ===========================================================================
# §pass70 Sprint 21 — Admin (5 new — final gap fillers)
# ===========================================================================

async def test_api_federation(auth: MCPAuthContext) -> Dict[str, Any]:
    """Run federation protocol conformance tests (api-tester variant). Admin only."""
    return await _admin_post(auth, "/api/v1/admin/api-test/test-federation", timeout=API_TEST_RUN_TIMEOUT)


async def delete_oauth_federation_trust(auth: MCPAuthContext, registry_url: str) -> Dict[str, Any]:
    """DESTRUCTIVE: revoke OAuth federation trust with a peer registry. Admin only."""
    if not registry_url:
        return {"error": "registry_url is required"}
    require_admin_auth(auth)
    effective_token = _get_effective_jwt(auth)
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT, verify=get_httpx_verify()) as client:
            r = await client.delete(
                f"{REGISTRY_SELF_URL}/api/v1/oauth/federation/trust/{seg(registry_url)}",
                headers={"Authorization": f"Bearer {effective_token}"},
            )
        if r.status_code in (200, 201, 204):
            try: return r.json()
            except Exception: return {"status": "revoked"}
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    except Exception as e:
        logger.error(f"deleteOauthFederationTrust error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def reconcile_fiat_provisioning(auth: MCPAuthContext, developer_id: int) -> Dict[str, Any]:
    """DESTRUCTIVE: reconcile a developer's provisioning months from purchase history. Admin only."""
    if developer_id is None:
        return {"error": "developer_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/fiat/provisioning/reconcile/{int(developer_id)}")


async def resend_fiat_magic_link(auth: MCPAuthContext, purchase_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: re-issue magic-link login email for an anonymous fiat purchase. Admin only."""
    if not purchase_id:
        return {"error": "purchase_id is required"}
    return await _admin_post(auth, f"/api/v1/admin/fiat/purchases/{seg(purchase_id)}/resend-magic-link")


async def update_support_ticket_status(auth: MCPAuthContext, ticket_id: str, status: str) -> Dict[str, Any]:
    """DESTRUCTIVE: admin updates a support ticket's status (open, in_progress, resolved or closed). Admin only.

    §MCPTEST30 (2026-10-01): the survey's BODY_UNDECLARED class: it sent a `reason` the route never stored (it reads `status` alone); dropped.
    §MCPTEST30 (V0548): the schema offered "escalated" and "pending", which the route refuses with 422; it offers the route's own four."""
    if not ticket_id or not status:
        return {"error": "ticket_id and status are required"}
    body: Dict[str, Any] = {"status": status}
    return await _admin_post(auth, f"/api/v1/admin/support/tickets/{seg(ticket_id)}/status", json_body=body)


# ===========================================================================
# AGORA exchange — venue-ops admin tools (Phase-2 B.2). First-class wrappers of
# /api/v1/agora/admin/* (routers/exchange.py) so venue ops run from any Claude
# session — audited + tier-classified — without the /admin/exchange UI.
# ===========================================================================

async def admin_exchange_overview(auth: MCPAuthContext) -> Dict[str, Any]:
    """AGORA venue cockpit aggregate (the /admin/exchange overview): listings + lifecycle
    states, escrow, 24h orders/trades/notional, settlement lag, top participants. Read-only."""
    return await _admin_get(auth, "/api/v1/agora/admin/overview")


async def admin_exchange_invariant(auth: MCPAuthContext) -> Dict[str, Any]:
    """AGORA live conservation RUN CHECK (I-X1..I-X4): escrow expected==actual @18dp, share
    supply, no-negative-positions, books==ledger, computed against current state while
    trading. Read-only; the venue-side analogue of the supply auditor."""
    return await _admin_get(auth, "/api/v1/agora/admin/invariant")


async def admin_exchange_participants(auth: MCPAuthContext, status: Optional[str] = None) -> Dict[str, Any]:
    """AGORA compliance registry (D25 'no anonymous ghosts') — the venue's known participants.
    Optional status filter: verified | pending | blocked. Read-only."""
    params = {"status": status} if status in ("verified", "pending", "blocked") else None
    return await _admin_get(auth, "/api/v1/agora/admin/participants", params=params)


async def admin_exchange_approve_listing(auth: MCPAuthContext, listing_ref: str) -> Dict[str, Any]:
    """Approve a funding→open AGORA listing (admin lifecycle). listing_ref = listing id or
    $TICKER. Returns the updated listing."""
    if not listing_ref:
        return {"error": "listing_ref is required"}
    return await _admin_post(auth, f"/api/v1/agora/admin/listings/{seg(listing_ref)}/approve")


async def admin_exchange_halt_listing(auth: MCPAuthContext, listing_ref: str, halted: bool = True) -> Dict[str, Any]:
    """Halt (halted=true) or resume (halted=false) trading on ONE AGORA listing. Halted
    listings reject new orders (409); resting orders stay until cancelled/TTL. listing_ref =
    listing id or $TICKER."""
    if not listing_ref:
        return {"error": "listing_ref is required"}
    return await _admin_post(auth, f"/api/v1/agora/admin/listings/{seg(listing_ref)}/halt", {"halted": bool(halted)})


async def admin_exchange_delist_listing(auth: MCPAuthContext, listing_ref: str) -> Dict[str, Any]:
    """Delist an AGORA listing — cancel ALL open orders + refund escrow, then remove from
    trading. listing_ref = listing id or $TICKER. Δ-neutral (refunds are conserved)."""
    if not listing_ref:
        return {"error": "listing_ref is required"}
    return await _admin_post(auth, f"/api/v1/agora/admin/listings/{seg(listing_ref)}/delist")


async def admin_exchange_global_halt(auth: MCPAuthContext, halted: bool = True) -> Dict[str, Any]:
    """VENUE-WIDE halt: set (halted=true) or clear (halted=false) the global_halt flag — when
    set, the WHOLE venue rejects new orders. DANGEROUS (the typed-confirm GLOBAL HALT in the
    UI). Existing escrow/positions untouched; Δ unaffected."""
    return await _admin_post(auth, "/api/v1/agora/admin/global-halt", {"halted": bool(halted)})


# ---------------------------------------------------------------------------
# JSON Schemas for MCP tools/list
# ---------------------------------------------------------------------------

# ── §MCPFIRM (2026-08-28): the consent-gated support desk (§CHATDESK C4) ────

async def admin_review_grants(auth, ticket_id: int):
    """Review grants on a ticket: which conversations the desk may read."""
    if ticket_id is None:
        return {"error": "ticket_id is required"}
    return await admin_request(auth, "GET",
                               f"/api/v1/admin/support/tickets/{int(ticket_id)}/review-grants")


async def admin_review_messages(auth, grant_id: str, limit: int = 100, before_seq=None):
    """READ-ONLY transcript for a LIVE review grant. Every call lands an
    `admin.chatdesk.review_read` audit row and a visible in-thread system row —
    reading through this tool is never invisible to the participants."""
    if not grant_id:
        return {"error": "grant_id is required"}
    params = {"limit": max(1, min(200, int(limit)))}
    if before_seq is not None:
        params["before_seq"] = int(before_seq)
    return await admin_request(auth, "GET",
                               f"/api/v1/admin/support/review/{seg(grant_id)}/messages",
                               params=params)


ADMIN_TOOL_SCHEMAS = [
    {
        "name": "theprotocol_adminReviewGrants",
        "description": "Review grants on a support ticket: which conversations the desk may read, granted by whom, live or revoked (§CHATDESK C4).",
        "inputSchema": {"type": "object", "properties": {"ticket_id": {"type": "integer"}}, "required": ["ticket_id"]}
    },
    {
        "name": "theprotocol_adminReviewMessages",
        "description": "READ-ONLY transcript for a LIVE review grant. Every call is audited (admin.chatdesk.review_read) and visible to the thread's participants.",
        "inputSchema": {"type": "object", "properties": {
            "grant_id": {"type": "string"},
            "limit": {"type": "integer", "default": 100},
            "before_seq": {"type": "integer"}}, "required": ["grant_id"]}
    },
    {
        "name": "theprotocol_adminAgoraOverview",
        "description": "AGORA market cockpit aggregate: listings + lifecycle, escrow, 24h orders/trades/notional, settlement lag, top participants. Read-only. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_adminAgoraInvariant",
        "description": "AGORA live conservation RUN CHECK (I-X1..I-X4): escrow expected==actual @18dp, point supply, no-negative-positions, books==ledger, computed against current state while trading. Read-only. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_adminAgoraParticipants",
        "description": "AGORA compliance registry (D25 no-anonymous-ghosts). Optional status filter. Read-only. Admin only.",
        "inputSchema": {"type": "object", "properties": {"status": {"type": "string", "description": "verified | pending | blocked"}}}
    },
    {
        "name": "theprotocol_adminAgoraApproveListing",
        "description": "Approve a funding→open AGORA listing. listing_ref = listing id or $TICKER. Admin only.",
        "inputSchema": {"type": "object", "properties": {"listing_ref": {"type": "string", "description": "Listing id or $TICKER"}}, "required": ["listing_ref"]}
    },
    {
        "name": "theprotocol_adminAgoraHaltListing",
        "description": "Halt (halted=true) or resume (halted=false) ONE AGORA listing — halted = new orders rejected. Admin only.",
        "inputSchema": {"type": "object", "properties": {"listing_ref": {"type": "string", "description": "Listing id or $TICKER"}, "halted": {"type": "boolean", "description": "true=halt, false=resume (default true)"}}, "required": ["listing_ref"]}
    },
    {
        "name": "theprotocol_adminAgoraDelistListing",
        "description": "Delist an AGORA listing — cancel all open orders + refund escrow + remove from trading. Δ-neutral. Admin only.",
        "inputSchema": {"type": "object", "properties": {"listing_ref": {"type": "string", "description": "Listing id or $TICKER"}}, "required": ["listing_ref"]}
    },
    {
        "name": "theprotocol_adminAgoraGlobalHalt",
        "description": "MARKET-WIDE halt: set/clear the global_halt flag (the whole AGORA market rejects new orders). DANGEROUS. Admin only.",
        "inputSchema": {"type": "object", "properties": {"halted": {"type": "boolean", "description": "true=halt the market, false=resume (default true)"}}, "required": ["halted"]}
    },
    {
        "name": "theprotocol_adminGetDeveloperToken",
        "description": (
            "Obtain a developer JWT via OAuth2 password flow. "
            "No authentication required — this IS the authentication step. "
            "Call this first, then pass the returned access_token as developer_jwt "
            "to adminRequest to unlock all 200+ registry endpoints. "
            "Same inline pattern as getAgentToken → getMyBalance."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": "Developer account email"
                },
                "password": {
                    "type": "string",
                    "description": "Developer account password"
                }
            },
            "required": ["email", "password"]
        }
    },
    {
        "name": "theprotocol_adminRequest",
        "description": (
            (
                "Commander-only: proxy any HTTP request to the TheProtocol registry API. Provides full access to all "
                "~200+ registry endpoints. Requires admin developer JWT. Example endpoints: /api/v1/admin/dashboard, "
                "/api/v1/agent-cards, /api/v1/governance/proposals, /api/v1/teg/transactions, /api/v1/disputes, "
                "/api/v1/federation/peers"
            )
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                    "description": "HTTP method"
                },
                "endpoint": {
                    "type": "string",
                    "description": "Registry API path, e.g. /api/v1/admin/dashboard"
                },
                "body": {
                    "type": "object",
                    "description": "JSON request body (for POST/PUT/PATCH)"
                },
                "params": {
                    "type": "object",
                    "description": "Query parameters dict"
                },
                "developer_jwt": {
                    "type": "string",
                    "description": "Optional: developer JWT from adminGetDeveloperToken. Overrides bridge token for registry endpoints."
                }
            },
            "required": ["method", "endpoint"]
        }
    },
    {
        "name": "theprotocol_adminQueryEventStore",
        "description": (
            "Commander-only: query the EventStore immutable ledger directly. "
            "Common paths: /api/v1/events/ (all events, add ?limit=N), "
            "/api/v1/events/aggregate/{did} (events for a DID), "
            "/api/v1/projections/stats (global stats), "
            "/api/v1/projections/balances (all agent balances), "
            "/api/v1/projections/transactions/{agent_id}. "
            "Requires admin developer JWT."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "EventStore API path, e.g. /api/v1/events/"
                },
                "params": {
                    "type": "object",
                    "description": "Query parameters, e.g. {\"limit\": 50}"
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "theprotocol_adminPromQuery",
        "description": (
            "Commander-only: execute PromQL queries against Prometheus. "
            "Instant query (no start/end): query='up', query='rate(http_requests_total[5m])'. "
            "Range query: also provide start (ISO8601), end (ISO8601), step (seconds string). "
            "Requires admin developer JWT."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "PromQL expression, e.g. 'up' or 'rate(http_requests_total[5m])'"
                },
                "start": {
                    "type": "string",
                    "description": "ISO8601 start time for range query, e.g. 2026-03-06T00:00:00Z"
                },
                "end": {
                    "type": "string",
                    "description": "ISO8601 end time for range query"
                },
                "step": {
                    "type": "string",
                    "description": "Step in seconds for range query, default '60'"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "theprotocol_adminGrafanaQuery",
        "description": (
            "Commander-only: query the Grafana HTTP API using admin credentials (Basic Auth). "
            "Common GET paths: /api/health, /api/admin/stats, /api/search (?query=keyword), "
            "/api/dashboards/uid/{uid} (full dashboard JSON), /api/annotations, "
            "/api/datasources, /api/org/users, /api/folders. "
            "POST /api/ds/query to run raw datasource queries (PromQL or SQL). "
            "Requires admin developer JWT."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Grafana API path, e.g. /api/search or /api/dashboards/uid/abc123"
                },
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "DELETE"],
                    "description": "HTTP method (default GET)"
                },
                "body": {
                    "type": "object",
                    "description": "JSON body for POST requests"
                },
                "params": {
                    "type": "object",
                    "description": "Query parameters, e.g. {\"query\": \"system\"} for /api/search"
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "theprotocol_supportListTickets",
        "description": (
            "List support tickets. Filter by status (open/in_progress/resolved/closed) "
            "or show all. Returns ticket id, subject, category, status, priority, "
            "developer email, message count, and last activity."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["open", "in_progress", "resolved", "closed", "all"],
                    "description": "Filter by ticket status (default 'open')"
                }
            },
            "required": []
        }
    },
    {
        "name": "theprotocol_supportReplyTicket",
        "description": (
            "Reply to a support ticket as admin. Automatically notifies the user "
            "via broadcast. Use this to respond to developer support requests."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "integer",
                    "description": "ID of the support ticket to reply to"
                },
                "message": {
                    "type": "string",
                    "description": "Reply message text"
                }
            },
            "required": ["ticket_id", "message"]
        }
    },
    {
        "name": "theprotocol_supportCloseTicket",
        "description": (
            "Close or resolve a support ticket. Notifies the user via broadcast. "
            "Optionally send a final reply message before closing. "
            "Use status 'resolved' for fixed issues, 'closed' for won't-fix or duplicates."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "integer",
                    "description": "ID of the support ticket to close"
                },
                "status": {
                    "type": "string",
                    "enum": ["resolved", "closed"],
                    "description": "Target status — 'resolved' (default) or 'closed'"
                },
                "message": {
                    "type": "string",
                    "description": "Optional final reply message sent before closing"
                }
            },
            "required": ["ticket_id"]
        }
    },
    # ─── §pass70 Sprint 3 — Admin (10 new) ────────────────────────────────
    {
        "name": "theprotocol_getReactorStatus",
        "description": "Live reactor framework status — per-reactor enabled flag, last fired, error counts, throttle state. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getEventEmissionPolicies",
        "description": "List all event_emission_policies rows (f037 partition gate). Critical for supply invariant work. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_setEventEmissionPolicy",
        "description": (
            "Update an event-type's emission policy (f037). DANGEROUS — wrong values can cause supply invariant drift. "
            "Only set fields you intend to change. Admin treasury required."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_type": {"type": "string", "description": "Event type name (e.g. 'TokensTransferred')"},
                "emit_from_teg": {"type": "boolean"},
                "emit_from_registry": {"type": "boolean"},
                "skip_in_projection": {"type": "boolean"}
            },
            "required": ["event_type"]
        }
    },
    {
        "name": "theprotocol_getCloudOperators",
        "description": "List cloud-provisioned operator registries (status, region, public URL, mTLS state). Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getAdminAgents",
        "description": "Admin view of all agents across developers. Paginated. Admin only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"maximum": 200, "minimum": 1, "type": "integer", "default": 50},
                "offset": {"type": "integer", "default": 0}
            }
        }
    },
    {
        "name": "theprotocol_getAdminDashboard",
        "description": "High-level platform counts: developers, agents, bootstrap tokens, active accounts. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getTreasuryAggregate",
        "description": "Frame-aware treasury + fee_collector aggregate snapshot (Build #7 surface). Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_triggerProjectionSnapshot",
        "description": (
            "Take a ProjectionSnapshot event from current TEG balances as new baseline. "
            "Operational tool — only run when needed to eliminate drift. "
            "Requires ENABLE_PROJECTION_SNAPSHOTS=true env var. Admin treasury required."
        ),
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_triggerSupplyAudit",
        "description": "Run the self-consistent supply invariant audit. Returns tokens_issued vs total_circulating + delta + OK/BREACH status. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getAdminBroadcasts",
        "description": "List admin broadcasts (system-wide notices + recent platform activity feed). Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    # ─── §pass70 Sprint 4 — Admin (14 new) ────────────────────────────────
    {
        "name": "theprotocol_getAdminDevelopers",
        "description": "List all developers (admin view). Paginated. Admin only.",
        "inputSchema": {"type": "object", "properties": {"limit": {"maximum": 200, "minimum": 1, "type": "integer", "default": 50}, "offset": {"type": "integer", "default": 0}}}
    },
    {
        "name": "theprotocol_getCanaryStatus",
        "description": "Full canary system dashboard: per-path stats, 24h/5m pass rates, frame deltas, recent failures. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getCanaryResults",
        "description": "Recent canary test results, filterable by path_id. Admin only.",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50}, "path_id": {"type": "integer"}}}
    },
    {
        "name": "theprotocol_fireCanaryPath",
        "description": "Manually fire a canary transfer for a path_id (bypasses normal interval). On-demand health check. Admin only.",
        "inputSchema": {"type": "object", "properties": {"path_id": {"type": "integer"}}, "required": ["path_id"]}
    },
    {
        "name": "theprotocol_toggleCanaryPath",
        "description": "Toggle a canary path's active state (pause / unpause). Admin only.",
        "inputSchema": {"type": "object", "properties": {"path_id": {"type": "integer"}}, "required": ["path_id"]}
    },
    {
        "name": "theprotocol_setCanaryMaintenance",
        "description": (
            "Set canary path active state. enable=false puts paths into maintenance (paused); "
            "enable=true returns them to normal firing. scope='all' (default) or list of integer path_ids."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "enable": {"type": "boolean", "description": "true to enable canary firing; false to pause"},
                "scope": {"description": "Optional: 'all' (default) or list of canary path ids"}
            },
            "required": ["enable"]
        }
    },
    {
        "name": "theprotocol_adminCanaryFleetStatus",
        "description": (
            "Canary Cockpit single pane (V0045): scheduling mode (master/follower/local), fleet-pause flag, "
            "local path counts, every federated schedule row with its last dispatch outcome/latency, and "
            "24h dispatch outcomes per home registry."
        ),
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_adminCanaryFleetPause",
        "description": (
            "Pause ALL canary scheduling fleet-wide — the one-button silent box (Canary Cockpit). New cycles "
            "stop within one tick; the in-flight dispatch tail drains in <30s. Never touches canary_paths.is_active. Admin only."
        ),
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_adminCanaryFleetResume",
        "description": "Resume canary scheduling fleet-wide (clears the Cockpit master pause flag). Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_adminCanaryFleetUpsertRemotePaths",
        "description": (
            "Canary Cockpit: upsert master schedule rows for peer-homed canary paths. Items: "
            "{home_registry, remote_path_id, path_label?, interval_sec?, is_active?, notes?}. "
            "home_registry must match a peer_registries.name. Admin only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "description": "List of schedule-row upserts", "items": {"type": "object"}}
            },
            "required": ["paths"]
        }
    },
    {
        "name": "theprotocol_previewAdminEmail",
        "description": "Preview an admin email template (rendered HTML). Useful for verifying template changes. Admin only.",
        "inputSchema": {"type": "object", "properties": {"template": {"type": "string", "description": "Template name (e.g. 'welcome', 'funding_approved')"}}, "required": ["template"]}
    },
    {
        "name": "theprotocol_getPendingPeerRegistries",
        "description": "List peer registry applications awaiting admin approval. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_approvePeerRegistry",
        "description": "Approve a pending peer registry application. Activates federation sync. Admin only.",
        "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}}, "required": ["peer_id"]}
    },
    {
        "name": "theprotocol_rejectPeerRegistry",
        "description": "Reject a pending peer registry application. Admin only.",
        "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}}, "required": ["peer_id"]}
    },
    {
        "name": "theprotocol_deactivatePeerRegistry",
        "description": "Deactivate an active peer registry (stops federation sync). Reversible via reactivatePeerRegistry. Admin only.",
        "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}}, "required": ["peer_id"]}
    },
    {
        "name": "theprotocol_reactivatePeerRegistry",
        "description": "Reactivate a previously-deactivated peer registry. Admin only.",
        "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}}, "required": ["peer_id"]}
    },
    {
        "name": "theprotocol_getFederationSyncStatus",
        "description": "Federation sync subsystem health: last sync timestamps, per-peer status, drift counters. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getFederationSyncPeers",
        "description": "Per-peer federation sync detail (compliance score, drift events, last successful sync). Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    # ─── §pass70 Sprint 5 (Admin) ─────────────────────────────────────────
    {
        "name": "theprotocol_getEnforcementPolicy",
        "description": "Active enforcement policy (offense thresholds, slash multipliers, version, modified_by). Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getEnforcementPending",
        "description": "List pending enforcement actions awaiting admin approval (warn/suspend/slash queue). Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getEnforcementAgentStatus",
        "description": (
            "Full enforcement status summary for an agent: offense history, current state, payouts-paused flag, "
            "locked units at risk. Admin only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"agent_did": {"type": "string"}},
            "required": ["agent_did"]
        }
    },
    {
        "name": "theprotocol_getCollusionRings",
        "description": "List detected collusion rings via Tarjan SCC analysis on transfer graph. Optional severity/agent_did/since/limit filters. Admin only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": ["low","medium","high","critical"]},
                "agent_did": {"type": "string"},
                "since": {"type": "string", "description": "ISO 8601 timestamp (filter rings detected after)"},
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}
            }
        }
    },
    {
        "name": "theprotocol_getCrossTegSweeperStatus",
        "description": "Cross-TEG 2PC sweeper fleet status: cycles, aborts, resumes, pending, per-op breakdown. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getCanaryJudgeStatus",
        "description": "Canary judge worker: 24h pass/fail, per-path stats, in-flight count, by-failure-type breakdown. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getCanaryRebalancerStatus",
        "description": "Canary fund rebalancer: cycles, units disbursed 24h, agents under floor, per-home-kind breakdown. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getSagaTimeoutStatus",
        "description": "Saga timeout worker: settlements timed out 24h, cross-frame refunds, cycle counts, errors. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getAgentCardDriftList",
        "description": "List agent-card drift state across federated mesh (paginated). Tracks last_pulled_at + etag per agent. Admin only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
                "offset": {"type": "integer", "default": 0, "minimum": 0}
            }
        }
    },
    {
        "name": "theprotocol_getInviteCodes",
        "description": "List invite codes for developer signup gating. Optional status_filter (active/revoked/used). Admin only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status_filter": {"type": "string", "enum": ["active","used","expired"]},
                "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
                "offset": {"type": "integer", "default": 0, "minimum": 0}
            }
        }
    },
    {
        "name": "theprotocol_getAdminFundingPending",
        "description": "List pending agent funding requests awaiting admin approval. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getEventStoreBalances",
        "description": "EventStore-derived agent balance projections (vs TEG ledger). Useful for reconciliation. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    # ─── §pass70 Sprint 6 (Admin — 13 new) ────────────────────────────────
    {
        "name": "theprotocol_getCanaryIronhandStatus",
        "description": "IRONHAND mTLS canary status: active paths, 24h pass/fail counts, pass_rate, registries reporting. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getCanaryIronhandEvents",
        "description": "IRONHAND mTLS canary fire history (paginated). Each event: test_id, path_human, transport, fired_iso, outcome. Admin only.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500}}
        }
    },
    {
        "name": "theprotocol_getAgentHealthStatus",
        "description": "Agent-health worker status: 24h cycles, probes, state_changes, registries_reporting, agent counts by health state. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getCicdSummary",
        "description": "CI/CD fleet summary: pipeline/version/deployment counts (24h window). Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getCicdDeployments",
        "description": "Recent CI/CD deployments fleet-wide: agent_did, deployment_type, environment, status, timestamps. Admin only.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}}
        }
    },
    {
        "name": "theprotocol_getWebhookAggregate",
        "description": "Cluster-wide webhook health snapshot: total/active/inactive webhooks, developers with webhooks, deliveries_in_window. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getRecentWebhookDeliveries",
        "description": "Recent webhook delivery attempts across the cluster. Optional status/event_type filters. Admin only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["all","success","failed","pending","retried"]},
                "event_type": {"type": "string"},
                "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500}
            }
        }
    },
    {
        "name": "theprotocol_getPayoutFundingPolicy",
        "description": (
            "Payout funding waterfall policy: per-reason ordered list of funding sources (fee_collector/treasury). "
            "Admin only."
        ),
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getEventStoreStats",
        "description": "EventStore projection stats: total_events, unique_agents, per-event-type counts. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getEventStoreRecent",
        "description": "The most recent events the registry keeps in its cache (the last 15): type, aggregate_id, payload. Admin only.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 15, "minimum": 1, "maximum": 15}}
        }
    },
    {
        "name": "theprotocol_getAdminAuditLogs",
        "description": "List security audit log entries (all actors, all event types). Paginated. Optional event_type/actor_type filters and the window (since_hours, the route's default 24). Admin only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_type": {"type": "string"},
                "actor_type": {"type": "string", "enum": ["developer","agent","admin","anonymous","system"]},
                "since_hours": {"type": "integer", "minimum": 1, "maximum": 720, "description": "How far back to read, in hours (1-720); the route reads 24 when it is not given."},
                "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
                "offset": {"type": "integer", "default": 0, "minimum": 0}
            }
        }
    },
    {
        "name": "theprotocol_getFeeCollectorInfo",
        "description": "Fee collector dashboard: balance, recent_distributions, total_collected_7d, per-asset breakdown. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getDiagnosticChecks",
        "description": "List the Command Center's diagnostic checks (check_id, title, description, category, cost_ms): supply-audit, leader-election, svid-expiry, frame-trust-bundle and frame-teg-health on this registry itself, and the container checks (identity network, nginx config, pgbouncer, SPIRE rotation, DNS errors) on operators it can reach. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    # ─── §pass70 Sprint 7 (Admin — 10 new) ────────────────────────────────
    {
        "name": "theprotocol_getDiagnosticTargets",
        "description": "List diagnostic targets: this registry itself (is_self: role frame, or operator on an operator registry), then its operators (from its own peer rows, and their containers under fleet scope). Each: operator_id, display_name, frame, role, status, last_snapshot_at; reason/reason_code say why no operator is listed, containers_reason/containers_reason_code why the container checks cannot run here. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getDiagnosticActions",
        "description": "List the remediation actions (nginx-reload, teg-restart: this frame's own operators only) with their destructive flag and the check each re-runs afterwards. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getBroadcastTemplates",
        "description": "List admin broadcast email templates (id, name, subject, body preview). Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getAgentCardPullsyncStatus",
        "description": "Agent-card pull-sync worker status: last cycle, duration_ms, last_stats, leader status. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getAgentCardPullsyncEvents",
        "description": "Recent AgentCardPulled events from federated peers (paginated). Admin only.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}}
        }
    },
    {
        "name": "theprotocol_getAdminMcpAuditLogByActor",
        "description": "Admin view of MCP tool call audit log for a specific actor (developer_id or agent DID). Required actor_id. Paged by cursor (the id of the previous page's last row). Admin only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "actor_id": {"type": "string"},
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
                "cursor": {"type": "string", "description": "the id of the last row of the previous page"}
            },
            "required": ["actor_id"]
        }
    },
    {
        "name": "theprotocol_getAdminHealthCheckSimple",
        "description": "Simple registry health-check (status, timestamp, service, version). Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getAdminHealthCheckPublicOnly",
        "description": "Health check across public endpoints only. Returns overall + per-group + per-endpoint status. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getAdminHealthCheckAuthenticated",
        "description": "Health check across authenticated endpoints (developer + admin). Returns overall + per-group + per-endpoint status. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getAdminTestTokens",
        "description": "Generate short-lived test tokens (developer + agent JWT) for health-check + smoke-test usage. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    # ─── §pass70 Sprint 8 (Admin — 10 new: 4 safe + 6 destructive) ────────
    {
        "name": "theprotocol_getAdminFundingAll",
        "description": "List ALL agent funding requests (pending + approved + rejected + funded). Extends Sprint 5's pending-only view. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getAgentHealthTransitions",
        "description": "List recent agent health state transitions (healthy→unhealthy/unreachable/...). Paginated. Admin only.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 200}}
        }
    },
    {
        "name": "theprotocol_getCombinedHealth",
        "description": "Composite registry+downstream health snapshot. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getCloudOperatorHealth",
        "description": "Detailed health check for a cloud operator (mainframe-only: a cloud operator answers 404 mainframe_only). Admin only.",
        "inputSchema": {
            "type": "object",
            "properties": {"application_id": {"type": "string"}},
            "required": ["application_id"]
        }
    },
    {
        "name": "theprotocol_approveFunding",
        "description": "DESTRUCTIVE: approve a pending agent funding request. Transfers units from the treasury to the requesting agent; optional approved_amount (defaults to the requested amount). Admin only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "integer"},
                "approved_amount": {"type": "string", "description": "the amount to approve; omit for the requested amount"}
            },
            "required": ["request_id"]
        }
    },
    {
        "name": "theprotocol_rejectFunding",
        "description": "DESTRUCTIVE: reject a pending agent funding request. reason is required (visible to requester). Admin only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "integer"},
                "reason": {"type": "string"}
            },
            "required": ["request_id", "reason"]
        }
    },
    {
        "name": "theprotocol_triggerEigentrustComputation",
        "description": "DESTRUCTIVE: force-trigger an immediate EigenTrust++ epoch computation. Heavy compute (~500ms+). Use sparingly. Admin only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_svidRefresh",
        "description": "DESTRUCTIVE: force-rotate this registry's SPIFFE SVID + trust bundle (IRONHAND mTLS identity). Peers need ~1-2 min to reconcile. Admin only — debugging mTLS issues only.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_runAllDiagnostics",
        "description": "Run all applicable diagnostic checks against ONE target operator. May take several seconds. force=true bypasses cache. Admin only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "operator_id from getDiagnosticTargets"},
                "force": {"type": "boolean", "default": False}
            },
            "required": ["target"]
        }
    },
    {
        "name": "theprotocol_triggerDiagnosticAction",
        "description": "DESTRUCTIVE (when dry_run=false): execute a remediation action against a target. Defaults to dry_run=True for safety. Admin only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string", "description": "From getDiagnosticActions"},
                "target": {"type": "string", "description": "operator_id from getDiagnosticTargets"},
                "dry_run": {"type": "boolean", "default": True}
            },
            "required": ["action_id", "target"]
        }
    },
    # ─── §pass70 Sprint 9 (Admin — 15 new) ────────────────────────────────
    {"name": "theprotocol_getDockerStats", "description": "Docker container stats snapshot (CPU/RAM/disk per container). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getPrometheusMetrics", "description": "Raw Prometheus metric scrape for this registry. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getOperatorLifecycle", "description": "Local operator lifecycle state (operator self-view: pull-token, license, last-activity, frame). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAdminFlags", "description": "Fleet-wide admin feature flags (rollout toggles, A/B test gates). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAdminRegistryCard", "description": "View this registry's full Registry Card v0.6 (admin view incl. all editable fields). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getSystemResources", "description": "System-level CPU/RAM/disk/network stats for the registry host (psutil snapshot). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getCanaryJudgeEvents", "description": "Recent canary judge events (per-path pass/fail with timestamps + reason). Paginated. Admin only.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}}}},
    {"name": "theprotocol_getCanaryRebalancerEvents", "description": "Recent canary rebalancer events (top-up actions on agents under floor). Paginated. Admin only.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}}}},
    {"name": "theprotocol_getSagaTimeoutEvents", "description": "Recent saga-timeout events (cross-frame settlement timeouts + refund actions). Paginated. Admin only.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}}}},
    {"name": "theprotocol_getCrossTegSweeperEvents", "description": "Recent cross-TEG sweeper events (2PC stuck-transfer compensation). Paginated. Admin only.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}}}},
    {"name": "theprotocol_getEmailTemplates", "description": "List all admin email templates available for preview (resolves Sprint 4 'unknown template name' question). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAdminAgentDetail", "description": "Full admin view of one agent (owner, credentials, status, enforcement state, audit timeline). Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_getAdminDeveloperDetail", "description": "Full admin view of one developer (account, agents, balances, admin flags, suspension). Admin only.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}}, "required": ["developer_id"]}},
    {"name": "theprotocol_listIronhandIdentities", "description": "List all IRONHAND SPIRE agent identities (mTLS enrollments). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAdminFiatStats", "description": "KPI aggregates for the fiat onramp dashboard (purchase count, EUR volume, conversion rate). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    # ─── §pass70 Sprint 10 (Admin — 20 new) ───────────────────────────────
    {"name": "theprotocol_suspendAgent", "description": "DESTRUCTIVE: suspend an agent (freezes operations). Triggers coordinated suspension. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "reason": {"type": "string"}}, "required": ["agent_did", "reason"]}},
    {"name": "theprotocol_reinstateAgentEnforcement", "description": "DESTRUCTIVE: reinstate a suspended agent. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "reason": {"type": "string"}}, "required": ["agent_did", "reason"]}},
    {"name": "theprotocol_pauseAgentPayouts", "description": "DESTRUCTIVE: pause the payouts on locked units for an agent. Optional duration_days. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "reason": {"type": "string"}, "duration_days": {"type": "integer"}}, "required": ["agent_did", "reason"]}},
    {"name": "theprotocol_resumeAgentPayouts", "description": "DESTRUCTIVE: resume the paused payouts on locked units for an agent. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_slashAgent", "description": (
        "HIGHLY DESTRUCTIVE: force-release units from an agent's locked units (a slash). amount integer. Admin "
        "only."
    ), "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "amount": {"type": "integer"}, "reason": {"type": "string"}}, "required": ["agent_did", "amount", "reason"]}},
    {"name": "theprotocol_previewSlash", "description": "Preview impact of slashing N units (dry run). Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "amount": {"type": "integer"}}, "required": ["agent_did", "amount"]}},
    {"name": "theprotocol_recordAgentOffense", "description": "DESTRUCTIVE: record an offense (escalates enforcement). offense_type enum; severity 1-10. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "offense_type": {"type": "string"}, "severity": {"type": "integer"}, "reference": {"type": "string"}, "disputed_amount": {"type": "integer"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_approvePendingEnforcement", "description": "DESTRUCTIVE: approve + execute a pending enforcement action. Admin only.", "inputSchema": {"type": "object", "properties": {"action_id": {"type": "string"}}, "required": ["action_id"]}},
    {"name": "theprotocol_rejectPendingEnforcement", "description": "Reject a pending enforcement action. The route requires a reason. Admin only.", "inputSchema": {"type": "object", "properties": {"action_id": {"type": "string"}, "reason": {"type": "string", "minLength": 1, "maxLength": 500}}, "required": ["action_id", "reason"]}},
    {"name": "theprotocol_listQuarantinedRegistries", "description": "List all currently quarantined federated registries. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_composeBroadcast", "description": "DESTRUCTIVE: compose + send admin broadcast to developers. broadcast_type enum (info/warning/maintenance). send_email also dispatches email. Admin only.", "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"}, "broadcast_type": {"type": "string", "default": "info"}, "send_email": {"type": "boolean", "default": False}, "cta_url": {"type": "string"}, "cta_label": {"type": "string"}, "requires_ack": {"type": "boolean", "default": False}, "target_org_id": {"type": "string"}, "target_developer_id": {"type": "integer", "minimum": 1, "description": "A direct notice to this one developer: in-app only (no send_email, no schedule), never copied to a peer; exclusive with target_org_id."}}, "required": ["title", "body"]}},
    {"name": "theprotocol_getAdminBroadcastsOverview", "description": "Aggregate broadcast metrics (counts by type, read rates). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getBroadcastStats", "description": "Per-broadcast read/dismiss statistics. Admin only.", "inputSchema": {"type": "object", "properties": {"broadcast_id": {"type": "integer"}}, "required": ["broadcast_id"]}},
    {"name": "theprotocol_retractBroadcast", "description": "DESTRUCTIVE: retract / soft-delete a broadcast. Reversible. Admin only.", "inputSchema": {"type": "object", "properties": {"broadcast_id": {"type": "integer"}}, "required": ["broadcast_id"]}},
    {"name": "theprotocol_updateBroadcast", "description": "DESTRUCTIVE: edit a broadcast's title/body/type after send. Admin only.", "inputSchema": {"type": "object", "properties": {"broadcast_id": {"type": "integer"}, "title": {"type": "string"}, "body": {"type": "string"}, "broadcast_type": {"type": "string"}}, "required": ["broadcast_id"]}},
    {"name": "theprotocol_reinstateBroadcast", "description": "Reinstate a previously-retracted broadcast. Admin only.", "inputSchema": {"type": "object", "properties": {"broadcast_id": {"type": "integer"}}, "required": ["broadcast_id"]}},
    {"name": "theprotocol_getAdminAgentsByDeveloper", "description": "List all agents owned by a developer (cascade preview). Admin only.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}}, "required": ["developer_id"]}},
    {"name": "theprotocol_getAdminAgentOrphans", "description": "List orphaned agents (no living dev owner). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAdminAgentFlags", "description": "List moderation flags for an agent. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_getAdminAgentSigningKeys", "description": "List agent Ed25519 signing keys. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    # ─── §pass70 Sprint 11 (Admin — 28 new: fiat + simulation + dev mgmt) ─
    {"name": "theprotocol_getAdminFiatPricing", "description": "Active fiat pricing config + version history. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAdminFiatPurchases", "description": "List FiatPurchase rows. Admin only.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500}, "offset": {"type": "integer", "default": 0, "minimum": 0}}}},
    {"name": "theprotocol_getAdminFiatPurchaseDetail", "description": "Drill into one FiatPurchase. Admin only.", "inputSchema": {"type": "object", "properties": {"purchase_id": {"type": "string"}}, "required": ["purchase_id"]}},
    {"name": "theprotocol_getAdminFiatFlares", "description": "List all developers with a flare. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_simulateFiatPricing", "description": "What-if simulation of EUR purchases through a pricing config (the active one when config is omitted; dry run). Amounts are decimal strings. Admin only.", "inputSchema": {"type": "object", "properties": {"purchases_eur": {"type": "array", "items": {"type": "string"}}, "starting_treasury_avt": {"type": "string"}, "starting_fee_collector_avt": {"type": "string"}, "config": {"type": "object"}, "waterfall": {"type": "array", "items": {"type": "string"}}}, "required": ["purchases_eur", "starting_treasury_avt", "starting_fee_collector_avt"]}},
    {"name": "theprotocol_validateFiatPricing", "description": "Dry-run config validation for fiat pricing. The route requires a note (4-500 characters). Admin only.", "inputSchema": {"type": "object", "properties": {"config": {"type": "object"}, "note": {"type": "string", "minLength": 4, "maxLength": 500}}, "required": ["config", "note"]}},
    {"name": "theprotocol_refundFiatPurchase", "description": "DESTRUCTIVE: issue Stripe refund + flag FiatPurchase as refunded. Admin only.", "inputSchema": {"type": "object", "properties": {"purchase_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["purchase_id"]}},
    {"name": "theprotocol_replayFiatPurchase", "description": "Re-run Stripe webhook handler for stuck pending/failed purchase. Admin only.", "inputSchema": {"type": "object", "properties": {"purchase_id": {"type": "string"}}, "required": ["purchase_id"]}},
    {"name": "theprotocol_grantFiatFlare", "description": "DESTRUCTIVE: admin-grant flare tier to a developer (sent to the route as `tier`); agent_did pins it to one agent. Admin only.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}, "flare_tier": {"type": "string"}, "agent_did": {"type": "string"}}, "required": ["developer_id", "flare_tier"]}},
    {"name": "theprotocol_revokeFiatFlare", "description": "DESTRUCTIVE: revoke a developer's flare. Admin only.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}}, "required": ["developer_id"]}},
    {"name": "theprotocol_getAdminSimulationStatus", "description": "Simulation framework status. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAdminSimulationAgents", "description": "List simulation agents. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAdminSimulationSupplyAudit", "description": "Simulation-perspective supply audit. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAdminSimulationTopology", "description": "Federation topology from sim. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAdminSimulationDeadmanStatus", "description": "Deadman-switch status. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAdminSimulationFundStatus", "description": "Sim agent fund status. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAdminSimulationLogs", "description": "Sim execution logs. Admin only.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500}}}},
    {"name": "theprotocol_startSimulation", "description": "DESTRUCTIVE: start a sim run (synthetic load) with the route's own fields; the go-to shape is BOUNDED dynamic (dynamic=true with max_concurrency set). Admin only.", "inputSchema": {"type": "object", "properties": {"mode": {"type": "string", "enum": ["mixed", "local-only", "cross-only", "cross-frame-only", "fx", "market", "delegation"]}, "pairs": {"type": "integer", "minimum": 1, "maximum": 500}, "cycle_interval": {"type": "integer", "minimum": 0, "maximum": 3600}, "cycles": {"type": "integer", "minimum": 0}, "instances": {"type": "integer", "minimum": 1, "maximum": 16}, "concurrency": {"type": "integer", "minimum": 1, "maximum": 1000}, "backend_mode": {"type": "string", "enum": ["mixed", "async", "2pc", "intra"]}, "rate_tps": {"type": "number"}, "dynamic": {"type": "boolean"}, "target_settle_ms": {"type": "integer", "minimum": 200, "maximum": 120000}, "target_metric": {"type": "string", "enum": ["p50", "p95", "avg"]}, "min_concurrency": {"type": "integer", "minimum": 1, "maximum": 1000}, "max_concurrency": {"type": "integer", "minimum": 1, "maximum": 1000}, "max_backlog": {"type": "integer", "minimum": 0, "maximum": 1000000}, "venue_balance": {"type": "string", "enum": ["currency", "venue"]}, "passport_share": {"type": "number", "minimum": 0, "maximum": 0.95}, "spawn_subagents": {"type": "boolean"}, "xreg_delegation": {"type": "boolean"}, "spawn_frames": {"type": "string"}, "xreg_only": {"type": "boolean"}, "clerk_anchored": {"type": "boolean"}}}},
    {"name": "theprotocol_stopSimulation", "description": "DESTRUCTIVE: stop a running simulation. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_issueFrameBSimulation", "description": "DESTRUCTIVE: issue Frame B simulation units. Sandbox/Frame-B only. Admin.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_fundSimulationAgents", "description": "DESTRUCTIVE: bulk-fund sim agents from treasury. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_simulationFundingPreview", "description": "Dry-run preview of sim funding. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_suspendDeveloper", "description": "DESTRUCTIVE: suspend a developer account. The route requires a reason (10-500 characters). Admin only.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}, "reason": {"type": "string", "minLength": 10, "maxLength": 500}}, "required": ["developer_id", "reason"]}},
    {"name": "theprotocol_reinstateDeveloper", "description": "DESTRUCTIVE: reinstate a suspended developer. Admin only.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}}, "required": ["developer_id"]}},
    {"name": "theprotocol_getAdminDeveloperActivity", "description": "Recent EventStore activity for this dev. Admin only.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}}, "required": ["developer_id"]}},
    {"name": "theprotocol_getAdminDeveloperQuota", "description": "Get developer resource quotas. Admin only.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}}, "required": ["developer_id"]}},
    {"name": "theprotocol_forceEmailVerify", "description": "DESTRUCTIVE: force-verify developer email. Admin only.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}}, "required": ["developer_id"]}},
    {"name": "theprotocol_revokeDeveloperApiKeys", "description": "DESTRUCTIVE: revoke ALL programmatic API keys for a dev. Admin only.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}}, "required": ["developer_id"]}},
    {"name": "theprotocol_disableDeveloper2FA", "description": "DESTRUCTIVE: disable 2FA on a dev account (emergency unlock). The route requires a reason. Admin only.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}, "reason": {"type": "string", "minLength": 1, "maxLength": 500}}, "required": ["developer_id", "reason"]}},
    # ─── §pass70 Sprint 12 (Admin — 15 new) ───────────────────────────────
    {"name": "theprotocol_getOperatorsLifecycleOverview", "description": "Overview of operator lifecycle states with counts + drilldown. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getBridgeAggregate", "description": "Cross-frame bridge aggregate metrics. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_rotateRegistrySigningKey", "description": "DESTRUCTIVE: rotate the registry's EdDSA signing key (the Registry Card v0.6 signing key). 7d grace. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getCloudOperatorLogs", "description": "Tail logs from cloud-op service. Mainframe-only. Admin only.", "inputSchema": {"type": "object", "properties": {"application_id": {"type": "string"}, "service": {"type": "string"}, "lines": {"type": "integer", "default": 100}}, "required": ["application_id"]}},
    {"name": "theprotocol_restartCloudOperatorService", "description": "DESTRUCTIVE: restart service in cloud-op stack. Mainframe-only. Admin only.", "inputSchema": {"type": "object", "properties": {"application_id": {"type": "string"}, "service": {"type": "string"}}, "required": ["application_id"]}},
    {"name": "theprotocol_provisionCloudOperator", "description": "HIGHLY DESTRUCTIVE: provision new cloud-op registry from approved app. Real infra. Admin only.", "inputSchema": {"type": "object", "properties": {"application_id": {"type": "string"}}, "required": ["application_id"]}},
    {"name": "theprotocol_teardownCloudOperator", "description": "HIGHLY DESTRUCTIVE: tear down cloud-op registry. Real infra. Admin only.", "inputSchema": {"type": "object", "properties": {"application_id": {"type": "string"}}, "required": ["application_id"]}},
    {"name": "theprotocol_getCloudOperatorSelfLogs", "description": "Answers an error to every MCP caller: the route reads a cloud operator's own logs through that operator's federation licence (the X-Federation-License header), which this tool does not send (401 on a frame, 404 mainframe_only on an operator, where the route does not run). A frame admin reads an operator's logs with getCloudOperatorLogs; an operator's own admin with operatorPortalSelfLogs.", "inputSchema": {"type": "object", "properties": {"lines": {"type": "integer", "default": 100}}}},
    {"name": "theprotocol_cloudOperatorSelfRestart", "description": "Answers an error to every MCP caller: the route restarts a cloud operator's service through that operator's own federation licence (X-Federation-License), which this tool does not send (401 on a frame, 404 mainframe_only on an operator). A frame admin restarts one with restartCloudOperatorService; an operator's own admin with operatorPortalSelfRestart.", "inputSchema": {"type": "object", "properties": {"service": {"type": "string"}}}},
    {"name": "theprotocol_updateDisputeRuling", "description": "DESTRUCTIVE: admin updates dispute ruling. Triggers enforcement. Admin only.", "inputSchema": {"type": "object", "properties": {"dispute_id": {"type": "integer"}, "ruling": {"type": "string", "enum": ["IN_FAVOR_OF_COMPLAINANT", "IN_FAVOR_OF_DEFENDANT", "DISMISSED"]}}, "required": ["dispute_id", "ruling"]}},
    {"name": "theprotocol_getEventStoreCrossFramePeers", "description": "Cross-frame peers in EventStore (sovereign-mainframe-only). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getEventStoreFederationOperators", "description": "Federation operators in EventStore (sovereign-mainframe-only). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_compositeHealthCheck", "description": "Composite health check (dev + agent auth combined). Admin only.", "inputSchema": {"type": "object", "properties": {"agent_token": {"type": "string", "description": "an agent JWT (getAgentToken) to include the agent-auth leg"}}}},
    # ─── §pass70 Sprint 13 (Admin — 25 new: treasury + bulk agent + enforcement + federation admin) ──
    {"name": "theprotocol_tegTreasuryIssue", "description": "HIGHLY DESTRUCTIVE: issue new units of the frame's currency (sovereign-mainframe-only). Increases supply. Admin only.", "inputSchema": {"type": "object", "properties": {"amount": {"type": "string"}, "reason": {"type": "string"}, "target_agent_did": {"type": "string"}}, "required": ["amount", "reason"]}},
    {"name": "theprotocol_tegTreasuryReceive", "description": "DESTRUCTIVE: return units to the treasury from an agent. Admin only.", "inputSchema": {"type": "object", "properties": {"source_agent_did": {"type": "string"}, "amount": {"type": "string"}, "reason": {"type": "string"}, "reference_id": {"type": "string"}}, "required": ["source_agent_did", "amount", "reason"]}},
    {"name": "theprotocol_tegCrossTegFund", "description": "HIGHLY DESTRUCTIVE: fund satellite TEG treasury from origin. Admin only.", "inputSchema": {"type": "object", "properties": {"target_registry": {"type": "string"}, "amount": {"type": "string"}, "reason": {"type": "string"}, "correlation_id": {"type": "string"}}, "required": ["target_registry", "amount", "reason"]}},
    {"name": "theprotocol_getEnforcementPolicyDefaults", "description": "Factory default enforcement policy. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_updateEnforcementPolicy", "description": "HIGHLY DESTRUCTIVE: replace active enforcement policy fleet-wide. Admin only.", "inputSchema": {"type": "object", "properties": {"policy_json": {"type": "object"}, "reason": {"type": "string"}}, "required": ["policy_json", "reason"]}},
    {"name": "theprotocol_quarantineRegistry", "description": "DESTRUCTIVE: quarantine a federated registry. Reversible. Admin only.", "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}, "reason": {"type": "string"}, "grace_hours": {"type": "integer"}}, "required": ["peer_id", "reason"]}},
    {"name": "theprotocol_liftQuarantine", "description": "DESTRUCTIVE: lift quarantine after corrected policy. Admin only.", "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}, "new_policy_hash": {"type": "string"}}, "required": ["peer_id", "new_policy_hash"]}},
    {"name": "theprotocol_acceptComplianceBaseline", "description": "Accept a federated peer's CURRENT policy as its compliance baseline after reviewing a drift (its hash moved, e.g. a release changed a shipped default). Refused unless expected_hash is exactly the hash the peer publishes now (read it from the peer's compliance detail or the drift event); the reason is recorded on the ledger. A quarantined peer returns through liftQuarantine instead. Admin only.", "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string", "description": "The peer_registries id"}, "expected_hash": {"type": "string", "description": "The 64-character lowercase hex policy hash you reviewed"}, "reason": {"type": "string", "description": "Why this policy is accepted (kept on the ledger)"}}, "required": ["peer_id", "expected_hash", "reason"]}},
    {"name": "theprotocol_blacklistRegistry", "description": "HIGHLY DESTRUCTIVE + IRREVERSIBLE from API: permanently blacklist a federated registry. The route requires a reason (10-500 characters). Admin only.", "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}, "reason": {"type": "string", "minLength": 10, "maxLength": 500}}, "required": ["peer_id", "reason"]}},
    {"name": "theprotocol_bulkSuspendAgents", "description": "DESTRUCTIVE: bulk-suspend up to 50 agents. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_dids": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}, "soft_suspend": {"type": "boolean", "default": False}}, "required": ["agent_dids", "reason"]}},
    {"name": "theprotocol_bulkReinstateAgents", "description": "DESTRUCTIVE: bulk-reinstate suspended agents. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_dids": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}, "soft_reinstate": {"type": "boolean", "default": False}}, "required": ["agent_dids"]}},
    {"name": "theprotocol_bulkRefreshAgentCards", "description": "Bulk-refresh agent-card pull state. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_dids": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}}, "required": ["agent_dids"]}},
    {"name": "theprotocol_transferAgentOwnership", "description": "DESTRUCTIVE: transfer agent ownership to new developer. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "new_creator_developer_id": {"type": "integer"}, "reason": {"type": "string"}}, "required": ["agent_did", "new_creator_developer_id", "reason"]}},
    {"name": "theprotocol_rotateAgentCredentials", "description": "DESTRUCTIVE: rotate agent client_secret (shown ONCE). Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_rotateAgentSigningKey", "description": "DESTRUCTIVE: rotate agent Ed25519 signing key. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_forceMtlsEnroll", "description": "DESTRUCTIVE: admin-initiated IRONHAND mTLS enrolment. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_deleteAdminAgent", "description": "HIGHLY DESTRUCTIVE: hard-delete an agent. confirm_did must repeat agent_did (the route refuses a mismatch). Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "reason": {"type": "string", "minLength": 20, "maxLength": 500}, "confirm_did": {"type": "string"}}, "required": ["agent_did", "reason", "confirm_did"]}},
    {"name": "theprotocol_acknowledgeAgentFlag", "description": "Acknowledge an agent moderation flag. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "flag_id": {"type": "string"}, "notes": {"type": "string"}}, "required": ["agent_did", "flag_id"]}},
    {"name": "theprotocol_updateDeveloperAdminFlags", "description": "DESTRUCTIVE: update granular admin flags on a developer. Admin only.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}, "admin_flags": {"type": "object"}}, "required": ["developer_id", "admin_flags"]}},
    {"name": "theprotocol_softDeleteDeveloper", "description": "HIGHLY DESTRUCTIVE: soft-delete developer (PII scrub). confirm_email must be the developer's email (the route refuses a mismatch). Admin only.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}, "reason": {"type": "string", "minLength": 20, "maxLength": 500}, "confirm_email": {"type": "string"}}, "required": ["developer_id", "reason", "confirm_email"]}},
    {"name": "theprotocol_forceDeveloperPasswordReset", "description": "DESTRUCTIVE: force password reset email. Admin only.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}}, "required": ["developer_id"]}},
    {"name": "theprotocol_giftProvisioning", "description": "DESTRUCTIVE: gift cloud-op provisioning months (1-120). The route requires a reason (10-500 characters). Admin only.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}, "months": {"type": "integer", "minimum": 1, "maximum": 120}, "reason": {"type": "string", "minLength": 10, "maxLength": 500}}, "required": ["developer_id", "months", "reason"]}},
    {"name": "theprotocol_patchDeveloperQuota", "description": "DESTRUCTIVE: update developer resource quotas. Admin only.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}, "quota_updates": {"type": "object"}}, "required": ["developer_id", "quota_updates"]}},
    {"name": "theprotocol_blockFederationAgent", "description": "DESTRUCTIVE: block federated agent (cross-registry). Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "reason": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_unblockFederationAgent", "description": "DESTRUCTIVE: unblock federated agent. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "reason": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_federationCliAudit", "description": "Answers an error to every MCP caller: the route records an operator CLI's audit event under that operator's federation licence (X-Federation-License), which this tool does not send (400, or 503 where OPERATOR_CLI_AUDIT_EMIT_ENABLED is off). The operator CLI calls the route itself.", "inputSchema": {"type": "object", "properties": {"action": {"type": "string", "maxLength": 64}, "cli_version": {"type": "string", "maxLength": 20}, "actor_host": {"type": "string", "maxLength": 120}, "actor_user": {"type": "string", "maxLength": 64}, "dry_run": {"type": "boolean", "default": False}, "exit_code": {"type": "integer", "default": 0}, "duration_ms": {"type": "number", "default": 0}, "extra": {"type": "object"}}, "required": ["action", "cli_version", "actor_host", "actor_user"]}},
    # ─── §pass70 Sprint 14 (Admin — 20 new) ───────────────────────────────
    {"name": "theprotocol_listAdminOperatorApplications", "description": "List operator applications (sovereign-mainframe-only). Admin only.", "inputSchema": {"type": "object", "properties": {"status": {"type": "string"}}}},
    {"name": "theprotocol_getAdminOperatorApplication", "description": "Get operator application detail. Sovereign-mainframe-only. Admin only.", "inputSchema": {"type": "object", "properties": {"application_id": {"type": "string"}}, "required": ["application_id"]}},
    {"name": "theprotocol_approveOperatorApplication", "description": "DESTRUCTIVE: approve operator application. Sovereign-mainframe-only. Admin only.", "inputSchema": {"type": "object", "properties": {"application_id": {"type": "string"}}, "required": ["application_id"]}},
    {"name": "theprotocol_rejectOperatorApplication", "description": "DESTRUCTIVE: reject operator application. Sovereign-mainframe-only. Admin only.", "inputSchema": {"type": "object", "properties": {"application_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["application_id"]}},
    {"name": "theprotocol_suspendOperator", "description": "DESTRUCTIVE: suspend an operator. Sovereign-mainframe-only. The route requires a reason. Admin only.", "inputSchema": {"type": "object", "properties": {"application_id": {"type": "string"}, "reason": {"type": "string", "minLength": 1, "maxLength": 1000}}, "required": ["application_id", "reason"]}},
    {"name": "theprotocol_reinstateOperator", "description": "DESTRUCTIVE: reinstate suspended operator. Sovereign-mainframe-only. Admin only.", "inputSchema": {"type": "object", "properties": {"application_id": {"type": "string"}}, "required": ["application_id"]}},
    {"name": "theprotocol_revokeOperatorAccess", "description": "HIGHLY DESTRUCTIVE: revoke operator access. Sovereign-mainframe-only. The route requires a reason. Admin only.", "inputSchema": {"type": "object", "properties": {"application_id": {"type": "string"}, "reason": {"type": "string", "minLength": 1, "maxLength": 1000}}, "required": ["application_id", "reason"]}},
    {"name": "theprotocol_rotateOperatorPullToken", "description": "DESTRUCTIVE: rotate operator pull-token. Sovereign-mainframe-only. Admin only.", "inputSchema": {"type": "object", "properties": {"application_id": {"type": "string"}}, "required": ["application_id"]}},
    {"name": "theprotocol_backfillPullTokens", "description": "DESTRUCTIVE: backfill pull-tokens for all ops (one-off migration). Sovereign-mainframe-only. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_adminDownloadOperatorBundle", "description": "Download operator bundle (signed config + license). Admin only.", "inputSchema": {"type": "object", "properties": {"application_id": {"type": "string"}}, "required": ["application_id"]}},
    {"name": "theprotocol_getApiTestArchiveRuns", "description": "List archived API test runs. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getApiTestEndpoints", "description": "List all API endpoints covered by api-tester. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getApiTestFlowValues", "description": "Current api-tester flow values (chained-test state). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_resetApiTestFlowValues", "description": "DESTRUCTIVE: reset api-tester flow values. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_testApiEndpoint", "description": "Test a single API endpoint via api-tester framework. Admin only.", "inputSchema": {"type": "object", "properties": {"endpoint_path": {"type": "string"}, "method": {"type": "string", "default": "GET"}, "body": {"type": "object"}}, "required": ["endpoint_path"]}},
    {"name": "theprotocol_eagerBootstrapApiTest", "description": "Eagerly bootstrap api-tester session fixtures. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getApiTestSandboxCredentials", "description": "Sandbox test credentials for api-tester. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getApiTestBucketClassification", "description": "Per-category bucket classification for api-tester. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getPeerRegistryCard", "description": "View a federated peer's cached Registry Card v0.6. Admin only.", "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}}, "required": ["peer_id"]}},
    {"name": "theprotocol_getHealthCheckWithAgentAuth", "description": "Health check with bundled agent creds (full stack test). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    # ─── §pass70 Sprint 15 (Admin — 30 new) ───────────────────────────────
    {"name": "theprotocol_getAdmissionStatus", "description": "Status of federation admission request. Admin only.", "inputSchema": {"type": "object", "properties": {"admission_id": {"type": "string"}}, "required": ["admission_id"]}},
    {"name": "theprotocol_completeAdmission", "description": "DESTRUCTIVE: complete admission workflow (finalize peer onboarding). Admin only.", "inputSchema": {"type": "object", "properties": {"admission_id": {"type": "string"}}, "required": ["admission_id"]}},
    {"name": "theprotocol_getFederationComplianceDrifts", "description": "List federation compliance drift events. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getFederationComplianceEnforcementMode", "description": "Current federation compliance enforcement mode. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_setFederationComplianceEnforcementMode", "description": "DESTRUCTIVE: set compliance enforcement mode (off / dry_run / enforcing). The route requires a reason (5-500 characters). Admin only.", "inputSchema": {"type": "object", "properties": {"mode": {"type": "string", "enum": ["off", "dry_run", "enforcing"]}, "reason": {"type": "string", "minLength": 5, "maxLength": 500}}, "required": ["mode", "reason"]}},
    {"name": "theprotocol_getFederationComplianceEvents", "description": "Federation compliance event stream. Admin only.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500}}}},
    {"name": "theprotocol_getFederationComplianceOverview", "description": "Federation compliance overview (per-peer adherence). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getFederationCompliancePeerByOperator", "description": "Federation compliance peer by operator_id. Admin only.", "inputSchema": {"type": "object", "properties": {"operator_id": {"type": "string"}}, "required": ["operator_id"]}},
    {"name": "theprotocol_getFederationCompliancePeerByID", "description": "Federation compliance peer by peer_id. Admin only.", "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}}, "required": ["peer_id"]}},
    {"name": "theprotocol_pollPeerComplianceNow", "description": "DESTRUCTIVE: force-poll peer compliance. Admin only.", "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}}, "required": ["peer_id"]}},
    {"name": "theprotocol_previewQuarantine", "description": "Dry-run preview of which peers would be quarantined. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_federationDriftScan", "description": "DESTRUCTIVE: trigger immediate drift scan across all peers. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_listAdminFrameInvitations", "description": "List incoming cross-frame federation handshakes. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAdminFrameInvitation", "description": "Single frame invitation detail. Admin only.", "inputSchema": {"type": "object", "properties": {"invitation_id": {"type": "string"}}, "required": ["invitation_id"]}},
    {"name": "theprotocol_approveFrameInvitation", "description": "DESTRUCTIVE: approve frame invitation (admit cross-frame peer). Admin only.", "inputSchema": {"type": "object", "properties": {"invitation_id": {"type": "string"}}, "required": ["invitation_id"]}},
    {"name": "theprotocol_rejectFrameInvitation", "description": "DESTRUCTIVE: reject frame invitation. The route requires a reason. Admin only.", "inputSchema": {"type": "object", "properties": {"invitation_id": {"type": "string"}, "reason": {"type": "string", "minLength": 1, "maxLength": 2000}}, "required": ["invitation_id", "reason"]}},
    {"name": "theprotocol_finalizeRetryFrameInvitation", "description": "DESTRUCTIVE: retry finalization of frame invitation. Admin only.", "inputSchema": {"type": "object", "properties": {"invitation_id": {"type": "string"}}, "required": ["invitation_id"]}},
    {"name": "theprotocol_getFramesSpireStatus", "description": "Cross-frame SPIRE handshake status. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_resyncFrameEventStore", "description": "DESTRUCTIVE: resync EventStore from cross-frame peer. Admin only.", "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}}, "required": ["peer_id"]}},
    {"name": "theprotocol_revokeFrame", "description": "HIGHLY DESTRUCTIVE: revoke a cross-frame peer. peer_id is the integer peer row id. The route requires a reason. Admin only.", "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}, "reason": {"type": "string", "minLength": 1, "maxLength": 2000}}, "required": ["peer_id", "reason"]}},
    {"name": "theprotocol_listFederationLicenses", "description": "List federation licenses (peer admission credentials). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_generateFederationLicense", "description": "DESTRUCTIVE: generate new federation license. Admin only.", "inputSchema": {"type": "object", "properties": {"operator_name": {"type": "string", "minLength": 1, "maxLength": 200}, "operator_did": {"type": "string", "minLength": 1, "maxLength": 255}, "max_agents": {"type": "integer", "minimum": 1, "maximum": 100000}, "max_events_per_minute": {"type": "integer", "minimum": 1, "maximum": 1000000}, "federation_tier": {"type": "string"}, "min_image_version": {"type": "string", "maxLength": 20}, "licensee_type": {"type": "string", "enum": ["operator", "frame"]}}, "required": ["operator_name", "operator_did"]}},
    {"name": "theprotocol_getFederationTopologyOverview", "description": "Federation topology overview (peer graph, mesh health). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_probeTopologyPeer", "description": "DESTRUCTIVE: actively probe a peer (HTTP+SPIFFE handshake). Admin only.", "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}}, "required": ["peer_id"]}},
    {"name": "theprotocol_validateFederationPolicy", "description": "Dry-run validate federation policy JSON. Admin only.", "inputSchema": {"type": "object", "properties": {"policy": {"type": "object"}}, "required": ["policy"]}},
    {"name": "theprotocol_runAttestationExpirySweep", "description": "DESTRUCTIVE: run one attestation expiry sweep now (sandbox registries only). Emits one AttestationExpired event per unrevoked attestation past its expiry, once; it revokes nothing. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_runAttestationScheduleCron", "description": "DESTRUCTIVE: force-run attestation schedule cron. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_adminRevokeAttestation", "description": "DESTRUCTIVE: admin-revoke an attestation. Re-verify then answers verified false; the reputation point is taken back only from the attestation that got it. Admin only.", "inputSchema": {"type": "object", "properties": {"attestation_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["attestation_id"]}},
    {"name": "theprotocol_ironhandEnrollAgent", "description": "DESTRUCTIVE: admin enroll/re-enroll agent in IRONHAND mTLS. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_ironhandRevokeAgent", "description": "DESTRUCTIVE: admin revoke agent's IRONHAND mTLS. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_deleteSpireOrphan", "description": "DESTRUCTIVE: delete an orphan SPIRE agent entry by its SPIFFE ID (spiffe://<trust domain>/agent/...). Admin only.", "inputSchema": {"type": "object", "properties": {"spiffe_id": {"type": "string"}}, "required": ["spiffe_id"]}},
    # ─── §pass70 Sprint 16 (Admin — 20 new) ───────────────────────────────
    {"name": "theprotocol_getFederationLocalEvents", "description": "Federation local-events stream (activity originating here). Admin only.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}}}},
    {"name": "theprotocol_getAllFederationPeersAdmin", "description": "List ALL federation peers (incl. inactive/deleted). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAdminFederationPolicyCompliance", "description": "Admin federation policy compliance overview. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_federationPolicyUpdateRequest", "description": "DESTRUCTIVE: request peer to update their policy. Admin only.", "inputSchema": {"type": "object", "properties": {"peer_did": {"type": "string"}, "proposed_policy_json": {"type": "object"}, "change_summary": {"type": "string"}, "effective_date": {"type": "string"}}, "required": ["peer_did", "proposed_policy_json"]}},
    {"name": "theprotocol_federationRequestAdmission", "description": "DESTRUCTIVE: request admission to foreign federated network. Admin only.", "inputSchema": {"type": "object", "properties": {"registry_name": {"type": "string"}, "registry_operator_did": {"type": "string"}, "registry_public_url": {"type": "string"}, "admin_contact_email": {"type": "string"}, "policy_json": {"type": "object"}, "operator_identity_proof": {"type": "object"}}, "required": ["registry_name", "registry_operator_did", "registry_public_url", "admin_contact_email", "policy_json"]}},
    {"name": "theprotocol_getAdminFederationSelfHealth", "description": "Self-health from federation perspective. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getTopologyPeerEvents", "description": "Events for single peer in topology. Admin only.", "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}, "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 100}}, "required": ["peer_id"]}},
    {"name": "theprotocol_getFederationLicenseDetail", "description": "Get detail for single federation license. Admin only.", "inputSchema": {"type": "object", "properties": {"license_id": {"type": "string"}}, "required": ["license_id"]}},
    {"name": "theprotocol_deleteFederationLicense", "description": "HIGHLY DESTRUCTIVE: hard-delete federation license. Admin only.", "inputSchema": {"type": "object", "properties": {"license_id": {"type": "string"}}, "required": ["license_id"]}},
    {"name": "theprotocol_reinstateFederationLicense", "description": "DESTRUCTIVE: reinstate suspended/revoked federation license. Admin only.", "inputSchema": {"type": "object", "properties": {"license_id": {"type": "string"}}, "required": ["license_id"]}},
    {"name": "theprotocol_revokeFederationLicense", "description": "HIGHLY DESTRUCTIVE: revoke federation license. The route requires a reason. Admin only.", "inputSchema": {"type": "object", "properties": {"license_id": {"type": "string"}, "reason": {"type": "string", "minLength": 1, "maxLength": 500}}, "required": ["license_id", "reason"]}},
    {"name": "theprotocol_suspendFederationLicense", "description": "DESTRUCTIVE: suspend federation license (temp, reversible). Admin only.", "inputSchema": {"type": "object", "properties": {"license_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["license_id"]}},
    {"name": "theprotocol_ironhandDeleteAgentProxy", "description": "DESTRUCTIVE: delete agent SPIRE entry (federation-auth proxy). Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_ironhandRegisterAgentProxy", "description": "DESTRUCTIVE: register agent SPIRE entry (federation-auth proxy). Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "spire_data": {"type": "object"}}, "required": ["agent_did", "spire_data"]}},
    # ─── §pass70 Sprint 17 (Admin — 12 new) ───────────────────────────────
    {"name": "theprotocol_getAgentCardDriftDetail", "description": "Drift diff for one agent. Admin only.", "inputSchema": {"type": "object", "properties": {"did": {"type": "string"}}, "required": ["did"]}},
    {"name": "theprotocol_forceRegisterAgentCard", "description": "DESTRUCTIVE: force-register drift state. Admin only.", "inputSchema": {"type": "object", "properties": {"did": {"type": "string"}}, "required": ["did"]}},
    {"name": "theprotocol_refreshAgentCardDrift", "description": "Refresh drift state by re-pulling agent card. Admin only.", "inputSchema": {"type": "object", "properties": {"did": {"type": "string"}}, "required": ["did"]}},
    {"name": "theprotocol_getBroadcastTemplateDetail", "description": "Broadcast email template full content. Admin only.", "inputSchema": {"type": "object", "properties": {"template_id": {"type": "string"}}, "required": ["template_id"]}},
    {"name": "theprotocol_getBroadcastEmailRetryStatus", "description": "Broadcast email retry queue status. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getBroadcastEmailRetryDeadLetter", "description": "Broadcast email dead-letter queue. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getBroadcastSchedulerStatus", "description": "Broadcast scheduler status. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_resetApiTestSandbox", "description": "DESTRUCTIVE: reset api-tester sandbox database. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_runAllApiTests", "description": "Run full API-test suite (heavy). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_testApiCategory", "description": "Test all endpoints in a category. Admin only.", "inputSchema": {"type": "object", "properties": {"category": {"type": "string"}}, "required": ["category"]}},
    {"name": "theprotocol_testApiFlow", "description": "Test a complete API flow scenario. Admin only.", "inputSchema": {"type": "object", "properties": {"flow_name": {"type": "string"}}, "required": ["flow_name"]}},
    {"name": "theprotocol_getAttestationsAnalytics", "description": "Aggregate attestation analytics. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    # ─── §pass70 Sprint 18 (Admin — 4 new) ────────────────────────────────
    {"name": "theprotocol_bridgeIssueWrapped", "description": "HIGHLY DESTRUCTIVE: issue wrapped units after a cross-frame bridge transfer. Sovereign-mainframe-only. Admin.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "amount": {"type": "string"}, "source_frame": {"type": "string"}}, "required": ["agent_did", "amount", "source_frame"]}},
    {"name": "theprotocol_bridgeRedeem", "description": "HIGHLY DESTRUCTIVE: redeem wrapped units (burns wrapped, unlocks original). Admin.", "inputSchema": {"type": "object", "properties": {"bridge_tx_id": {"type": "string", "minLength": 1, "maxLength": 64}, "agent_did": {"type": "string"}}, "required": ["bridge_tx_id", "agent_did"]}},
    {"name": "theprotocol_bridgeUnlock", "description": "HIGHLY DESTRUCTIVE: unlock bridged units on the source frame. Admin.", "inputSchema": {"type": "object", "properties": {"bridge_tx_id": {"type": "string", "minLength": 1, "maxLength": 64}}, "required": ["bridge_tx_id"]}},
    {"name": "theprotocol_getBridgeStatus", "description": "Get cross-frame bridge transfer status. Admin.", "inputSchema": {"type": "object", "properties": {"bridge_tx_id": {"type": "string"}}, "required": ["bridge_tx_id"]}},
    # ─── §pass70 Sprint 19 (Admin — 8 new) ────────────────────────────────
    {"name": "theprotocol_listAdminBundlesReports", "description": "List pending bundle moderation reports. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_dismissBundleReport", "description": "Dismiss a bundle report. resolution is a short word or phrase (1-40 characters), note optional. Admin only.", "inputSchema": {"type": "object", "properties": {"report_id": {"type": "integer"}, "resolution": {"type": "string", "minLength": 1, "maxLength": 40}, "note": {"type": "string", "maxLength": 500}}, "required": ["report_id", "resolution"]}},
    {"name": "theprotocol_hideBundle", "description": "DESTRUCTIVE: hide bundle from marketplace (soft-remove). The route requires a reason. Admin only.", "inputSchema": {"type": "object", "properties": {"bundle_id": {"type": "string"}, "reason": {"type": "string", "minLength": 1, "maxLength": 500}}, "required": ["bundle_id", "reason"]}},
    {"name": "theprotocol_unhideBundle", "description": "DESTRUCTIVE: unhide bundle (restore to marketplace). Admin only.", "inputSchema": {"type": "object", "properties": {"bundle_id": {"type": "string"}}, "required": ["bundle_id"]}},
    {"name": "theprotocol_getCanaryIronhandSvids", "description": "IRONHAND canary SVID health crossref. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getCollusionStatus", "description": "Collusion detector worker status. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAdminMetricsAgentActivity", "description": "Aggregate agent-activity metrics. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAdminCollusionByAgent", "description": "Collusion rings flagged for one agent. Admin only.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}}, "required": ["agent_did"]}},
    # ─── §pass70 Sprint 20 (Admin — 20 new) ───────────────────────────────
    {"name": "theprotocol_getSupplyAuditorStatus", "description": "Supply auditor worker status. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getSupplyAuditorEvents", "description": "Recent supply auditor events. Admin only.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}}}},
    {"name": "theprotocol_getAdminWorkersStatus", "description": "All background workers status. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_searchAdminEvents", "description": "Search admin events by event type. Admin only.", "inputSchema": {"type": "object", "properties": {"event_type": {"type": "string"}, "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500}}}},
    {"name": "theprotocol_getEventsAggregate", "description": "All events for a specific aggregate_id. Admin only.", "inputSchema": {"type": "object", "properties": {"aggregate_id": {"type": "string"}}, "required": ["aggregate_id"]}},
    {"name": "theprotocol_uploadRegistryCardIcon", "description": "DESTRUCTIVE: upload icon for Registry Card. Admin only.", "inputSchema": {"type": "object", "properties": {"icon_b64": {"type": "string"}, "content_type": {"type": "string", "default": "image/png"}}, "required": ["icon_b64"]}},
    {"name": "theprotocol_distributeFromFeeCollector", "description": "HIGHLY DESTRUCTIVE: pay units from this frame's fee account to an agent, by hand (one TEG transfer, no fee). Admin only (admin_treasury).", "inputSchema": {"type": "object", "properties": {"target_agent_did": {"type": "string", "description": "The agent paid"}, "amount": {"type": "string"}, "reason": {"type": "string", "description": "manual_payout, staking_reward, dispute_compensation, ..."}, "reference_id": {"type": "string"}}, "required": ["target_agent_did", "amount", "reason"]}},
    {"name": "theprotocol_generateInviteCodes", "description": "Generate N invite codes. Admin only.", "inputSchema": {"type": "object", "properties": {"count": {"type": "integer", "default": 1, "minimum": 1, "maximum": 100}, "note": {"type": "string"}}}},
    {"name": "theprotocol_validateInviteCodeAdmin", "description": "Validate invite code (admin context). Admin only.", "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
    {"name": "theprotocol_revokeInviteCode", "description": "DESTRUCTIVE: revoke an invite code. Admin only.", "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
    {"name": "theprotocol_disableWebhookAdmin", "description": "DESTRUCTIVE: admin-disable any webhook. Admin only.", "inputSchema": {"type": "object", "properties": {"webhook_id": {"type": "string"}}, "required": ["webhook_id"]}},
    {"name": "theprotocol_enableWebhookAdmin", "description": "DESTRUCTIVE: admin-re-enable any webhook. Admin only.", "inputSchema": {"type": "object", "properties": {"webhook_id": {"type": "string"}}, "required": ["webhook_id"]}},
    {"name": "theprotocol_testWebhookAdmin", "description": "Admin: send test event to ANY webhook. Admin only.", "inputSchema": {"type": "object", "properties": {"webhook_id": {"type": "string"}}, "required": ["webhook_id"]}},
    {"name": "theprotocol_getTutorialHealth", "description": "Tutorial sandbox health. Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_executeTutorial", "description": "DESTRUCTIVE when the call writes: execute ONE API call against the tutorial sandbox (this frame's API test target) as the token you pass (auth_type none = anonymous), the route the Tutorials pages drive. Returns the sandbox's status_code, response and response_time.", "inputSchema": {"type": "object", "properties": {"method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]}, "path": {"type": "string", "description": "API path after /api/v1, starting with / (e.g. /public/registry-config)"}, "body": {"type": "object", "description": "JSON body for POST/PUT/PATCH (form-encoded for /auth/login and /auth/agent/token)"}, "auth_type": {"type": "string", "enum": ["none", "developer", "agent", "bootstrap", "admin"]}, "auth_token": {"type": "string", "description": "the bearer (or bootstrap token) to forward; never stored"}}, "required": ["method", "path"]}},
    {"name": "theprotocol_generateTutorialProof", "description": (
        "Generate a real UltraHonk proof for a tutorial circuit (any of the four v2.0.0 circuits: "
        "fairMarkupPolicy, accurateResourceUsagePolicy, fairCrossRegistryFee, contentSafetyAttestation; the "
        "v1.0.0 ids get the v2.0.0 proof) with fixed example figures. agent_did is required: the proof's "
        "reference is derived from it and a random label, so only that agent can submit the proof. Every call "
        "uses a random salt and label, so each call gives a new proof. Answers with circuit_id, "
        "proof_bytes_base64, public_inputs (with reference_label), public_outputs (the commitment) and "
        "generation_time_ms, ready for submitAttestation from that agent. The route names the circuits it proves "
        "when the id is not one. Admin only."
    ), "inputSchema": {"type": "object", "properties": {"circuit_id": {"type": "string", "description": "the tutorial circuit, for example fairMarkupPolicy/v2.0.0 (any of the four v2.0.0 circuits)"}, "tutorial_id": {"type": "string", "description": "the older name of circuit_id"}, "agent_did": {"type": "string", "description": "required: the DID of the agent that will submit the proof"}}}},
    {"name": "theprotocol_runDiagnosticsSubset", "description": "Run a subset of (check ids × targets) diagnostics. Admin only.", "inputSchema": {"type": "object", "properties": {"checks": {"type": "array", "items": {"type": "string"}}, "targets": {"type": "array", "items": {"type": "string"}}}, "required": ["checks", "targets"]}},
    {"name": "theprotocol_getDiagnosticConfig", "description": "Read masked config slices for a target. Admin only.", "inputSchema": {"type": "object", "properties": {"target_id": {"type": "string"}}, "required": ["target_id"]}},
    # ─── §pass70 Sprint 21 (Admin — 5 new: final gap fillers) ─────────────
    {"name": "theprotocol_testApiFederation", "description": "Federation protocol conformance tests (api-tester). Admin only.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_deleteOauthFederationTrust", "description": "DESTRUCTIVE: revoke OAuth federation trust with peer. Admin only.", "inputSchema": {"type": "object", "properties": {"registry_url": {"type": "string"}}, "required": ["registry_url"]}},
    {"name": "theprotocol_reconcileFiatProvisioning", "description": "DESTRUCTIVE: reconcile dev's provisioning months from purchases. Admin only.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}}, "required": ["developer_id"]}},
    {"name": "theprotocol_resendFiatMagicLink", "description": "DESTRUCTIVE: re-issue magic-link login for anon fiat purchase. Admin only.", "inputSchema": {"type": "object", "properties": {"purchase_id": {"type": "string"}}, "required": ["purchase_id"]}},
    {"name": "theprotocol_updateSupportTicketStatus", "description": "DESTRUCTIVE: admin updates support ticket status. ticket_id is integer (or stringified integer). status: open, in_progress, resolved or closed (the route's own values). Admin only.", "inputSchema": {"type": "object", "properties": {"ticket_id": {"type": ["integer","string"], "description": "Integer ticket id (e.g. 1)"}, "status": {"type": "string", "enum": ["open","in_progress","resolved","closed"]}}, "required": ["ticket_id", "status"]}}
]
