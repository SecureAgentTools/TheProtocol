"""
MCP Tier 3 — Developer Operation Tools (developer JWT or API key required).

These 4 tools give developers programmatic control over their agents
and participation in TheProtocol governance and dispute systems.

To get a developer JWT:
    POST /api/v1/auth/login
    Content-Type: application/x-www-form-urlencoded
    Body: username=<email>&password=<password>

Tools:
  theprotocol.getMyAgents     — List all agents you own (via /developers/me/agents)
  theprotocol.createAgent     — Register a new agent on TheProtocol (via /onboard/*)
  theprotocol.submitDispute   — File a dispute against an agent (via /disputes/)
  theprotocol.createProposal  — Create a new governance proposal (via /governance/proposals)

§pass70 (2026-05-24) — Sprint 1 migration:
  - get_my_agents: direct DB SELECT replaced with httpx GET /developers/me/agents.
  - Removed dead imports: developer_crud, crud_disputes, crud_governance (none
    were called), event_emitter (never invoked), AgentCard / Developer /
    GovernanceProposal models (only Agent kept for type hints — actually no
    model imports needed at all now).
"""
import base64
import binascii
import logging
import uuid
from typing import Dict, Any, List, Optional

import httpx

from ..config import settings
from .auth_bridge import MCPAuthContext, require_developer_auth, require_agent_auth, MCPAuthError, format_tool_exception
from .auth_bridge import mcp_http_client  # D6-514: every client to this registry carries the MCP relay proof
from .refusal import http_refusal, refusal_reason  # §MCPTEST30: a refusal carries its reason
from .binary_answers import file_manifest, is_file  # §MCPTEST30 V0640: a file is answered by its manifest
from ..core.path_segment import seg  # §MCPTEST30 V0523: a caller's value is one path segment, encoded

logger = logging.getLogger(__name__)

REGISTRY_SELF_URL = getattr(settings, "REGISTRY_SELF_URL", "http://localhost:8000")
HTTPX_TIMEOUT_SHORT = 15.0
HTTPX_TIMEOUT_MUTATE = 30.0


# ---------------------------------------------------------------------------
# Tool: theprotocol.getMyAgents
# ---------------------------------------------------------------------------

async def get_my_agents(auth: MCPAuthContext) -> Dict[str, Any]:
    """
    List all agents registered under your developer account.

    §pass70 — migrated to GET /api/v1/developers/me/agents (developer-tier).
    HTTP endpoint enforces developer JWT via Depends(get_current_developer).
    """
    require_developer_auth(auth)

    if not auth.raw_token:
        return {"error": "No authentication token available"}

    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/developers/me/agents",
                headers={"Authorization": f"Bearer {auth.raw_token}"},
            )
        if r.status_code != 200:
            return {"error": f"developers/me/agents returned HTTP {r.status_code}: {r.text[:200]}"}

        agents_raw = r.json()
        if not isinstance(agents_raw, list):
            return {"error": "unexpected response shape from developers/me/agents"}

        agents_list = []
        for agent in agents_raw:
            agents_list.append({
                "id": agent.get("id"),
                "did": agent.get("did"),
                "client_id": agent.get("client_id"),
                "status": agent.get("status"),
                "name": agent.get("name"),
                "description": agent.get("description"),
                "reputation_score": float(agent.get("reputation_score") or 0),
                "liquid_balance": str(agent.get("liquid_balance") or 0),
                "staked_balance": str(agent.get("staked_balance") or 0),
                "created_at": agent.get("created_at"),
                "last_active_at": agent.get("last_active_at"),
            })

        return {
            "developer_id": auth.developer_id,
            "agents": agents_list,
            "total": len(agents_list),
        }

    except MCPAuthError:
        raise
    except httpx.TimeoutException:
        return {"error": "getMyAgents timed out"}
    except Exception as e:
        logger.error(f"getMyAgents error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ---------------------------------------------------------------------------
# Tool: theprotocol.createAgent
# ---------------------------------------------------------------------------

async def create_agent(
    auth: MCPAuthContext,
    name: str,
    description: str,
    capabilities: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Register a new AI agent on TheProtocol.

    Two-step bootstrap + create flow via /onboard/* endpoints.
    The client_secret is returned ONCE and cannot be retrieved again.
    """
    require_developer_auth(auth)

    if not name or not name.strip():
        return {"error": "name is required"}
    if not description or not description.strip():
        return {"error": "description is required"}

    if not auth.raw_token:
        return {"error": "No authentication token available"}

    capabilities = capabilities or []

    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            # Step 1: request bootstrap token
            bootstrap_r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/onboard/bootstrap/request-token",
                json={"agent_type_hint": "mcp_created", "requested_by": "mcp_createAgent"},
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json"},
            )
            if bootstrap_r.status_code not in (200, 201):
                detail = bootstrap_r.text[:300]
                return {"error": f"Bootstrap token request failed (HTTP {bootstrap_r.status_code}): {detail}"}

            bootstrap_token = bootstrap_r.json().get("bootstrap_token", "")
            if not bootstrap_token:
                return {"error": "Bootstrap token response missing bootstrap_token field"}

            # Step 2: create agent
            safe_name = name.strip()[:100]
            human_readable_id = safe_name.lower().replace(" ", "-")[:50]
            # §TESTBED (2026-09-19): THIS frame's public address, never the network's apex. The literal sent every
            # frame's MCP-made cards to theprotocol.cloud, so a stranger's kit frame advertised our apex and its own
            # health checker probed it for each such agent (measured from a kit sandbox: HEAD/GET
            # https://theprotocol.cloud/agents/<slug> -> 404 every cycle). The literal stays only as the last resort
            # for a node whose public address is unknown.
            from ..core.public_url import public_base_url_static
            _base = public_base_url_static() or "https://theprotocol.cloud"
            service_url = f"{_base}/agents/{human_readable_id}"
            token_url = f"{_base}/api/v1/auth/agent/token"
            agent_card = {
                "protocolVersion": "1.0",
                "agentVersion": "1.0",
                "name": safe_name,
                "description": description.strip(),
                "humanReadableId": human_readable_id,
                "provider": {
                    "name": "TheProtocol MCP",
                    "url": "https://www.theprotocol.cloud",
                    "support_contact": "support@theprotocol.cloud",
                },
                "supportedInterfaces": [
                    {"url": service_url, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
                ],
                "securitySchemes": {
                    "agent_jwt": {
                        "type": "oauth2",
                        "flows": {"clientCredentials": {"tokenUrl": token_url, "scopes": {}}},
                        "description": "Agent JWT via OAuth2 client-credentials grant",
                    }
                },
                "security": [{"agent_jwt": []}],
                "capabilities": {
                    "streaming": False,
                    "pushNotifications": True,
                    "extendedAgentCard": False,
                    "tags": capabilities,
                },
                "url": service_url,
                "preferredTransport": "JSONRPC",
                "authSchemes": [{"scheme": "oauth2", "tokenUrl": token_url}],
                "metadata": {"status": "active", "teg_enabled": True},
            }

            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/onboard/create_agent",
                json={"agent_did_method": "theprotocol", "agent_card": agent_card},
                headers={"Bootstrap-Token": bootstrap_token, "Content-Type": "application/json"},
            )

            if r.status_code in (200, 201):
                data = r.json()
                return {
                    "did": data.get("agent_did", ""),
                    "client_id": data.get("client_id", ""),
                    "client_secret": data.get("client_secret", ""),
                    "name": safe_name,
                    "status": "active",
                    "message": (
                        f"Agent '{safe_name}' created successfully. "
                        f"STORE client_secret — it will not be shown again."
                    ),
                }
            detail = refusal_reason(r)   # §MCPTEST30: the registry refuses as application/problem+json
            return {"error": f"Agent creation failed (HTTP {r.status_code}): {detail}"}

    except MCPAuthError:
        raise
    except httpx.TimeoutException:
        return {"error": "Agent creation request timed out"}
    except Exception as e:
        logger.error(f"createAgent error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ---------------------------------------------------------------------------
# Tool: theprotocol.submitDispute
# ---------------------------------------------------------------------------

async def submit_dispute(
    auth: MCPAuthContext,
    defendant_did: str,
    description: str = "",
    complainant_did: str = "",
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    File a dispute against another agent, as the calling agent. Routes through /disputes/.
    Requires agent authentication. The description is optional: the dispute itself has no field for one.

    D6-784 (2026-10-17): the route files the dispute as the agent of the token and has no complainant field, so
    `complainant_did` is not sent and decides nothing. The result names the complainant the route recorded (never the
    argument) and says so when the argument named another DID; the self-dispute check is the route's, on the caller.
    """
    require_agent_auth(auth)

    if not defendant_did:
        return {"error": "defendant_did is required"}
    if auth.agent_did and auth.agent_did == defendant_did:
        return {"error": "complainant and defendant cannot be the same agent"}

    if not auth.raw_token:
        return {"error": "No authentication token available"}

    body: Dict[str, Any] = {"defendant_did": defendant_did}

    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/disputes/",
                json=body,
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json"},
            )
        if r.status_code in (200, 201):
            data = r.json()
            dispute_id = data.get("id")
            # §FINDINGS-A4 3c (2026-09-27, his "fix 1-4 approved"): the dispute route has no field for a description,
            # so what the caller wrote was silently discarded (the `evidence` argument too). Both are now recorded as
            # the dispute's FIRST EVIDENCE (the complainant may file evidence on its own dispute), and the result says
            # whether that landed. `evidence_error`, never `error`: a result carrying `error` is rendered as a failed
            # tool call, and the dispute itself WAS filed. Since the route has no such field, the description is
            # optional (D6-444): a dispute filed without one records no evidence and is no error.
            evidence_recorded, evidence_error = False, None
            if not (description or evidence):
                pass   # nothing to record
            elif dispute_id is not None:
                ev: Dict[str, Any] = {"description": description} if description else {}
                if evidence:
                    ev["evidence"] = evidence
                try:
                    async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as ev_client:
                        er = await ev_client.post(
                            f"{REGISTRY_SELF_URL}/api/v1/disputes/{seg(dispute_id)}/evidence",
                            json={"evidence_data": ev},
                            headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json"},
                        )
                    evidence_recorded = er.status_code in (200, 201)
                    if not evidence_recorded:
                        evidence_error = f"recording the description as evidence answered HTTP {er.status_code}: {er.text[:200]}"
                except MCPAuthError:
                    raise
                except Exception as ev_exc:  # noqa: BLE001 — reported in the result, never swallowed
                    evidence_error = f"recording the description as evidence failed: {format_tool_exception(ev_exc)}"
            else:
                evidence_error = "the dispute reply carried no id, so the description could not be recorded as evidence"
            recorded = ("the description" if description else "your evidence") if evidence_recorded else None
            filed_as = data.get("complainant_did")   # D6-784: the filer the route recorded, never the argument
            out = {
                "dispute_id": dispute_id,
                "status": data.get("status", ""),
                "complainant_did": filed_as,
                "defendant_did": data.get("defendant_did") or defendant_did,
                "created_at": data.get("created_at", ""),
                "description_recorded_as_evidence": evidence_recorded and bool(description),
                "evidence_recorded": evidence_recorded,
                "next_steps": (
                    f"Dispute #{dispute_id} filed"
                    + (f" with {recorded} recorded as its first evidence. " if recorded else ". ")
                    + "Both parties may submit additional evidence. An admin will review and issue a ruling."
                ),
            }
            if evidence_error:
                out["evidence_error"] = evidence_error
            if complainant_did and complainant_did != filed_as:
                out["note"] = (f"complainant_did {complainant_did} was not used: a dispute is filed as the calling agent"
                               + (f", {filed_as}." if filed_as else "."))
            return out
        error_detail = refusal_reason(r)
        return {"error": f"Dispute filing failed (HTTP {r.status_code}): {error_detail}"}

    except MCPAuthError:
        raise
    except httpx.TimeoutException:
        return {"error": "Dispute filing request timed out"}
    except Exception as e:
        logger.error(f"submitDispute error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ---------------------------------------------------------------------------
# Tool: theprotocol.createProposal
# ---------------------------------------------------------------------------

async def create_proposal(
    auth: MCPAuthContext,
    title: str,
    description: str,
    duration_days: int = 7,
    proposal_type: str = "standard",
    agent_jwt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new governance proposal in the Agent Senate.
    Requires agent authentication (pass agent_jwt inline from getAgentToken).
    """
    require_agent_auth(auth)

    if not title or not title.strip():
        return {"error": "title is required"}
    if not description or not description.strip():
        return {"error": "description is required"}
    if not 1 <= duration_days <= 30:
        return {"error": "duration_days must be between 1 and 30"}
    if proposal_type not in ("standard", "policy_change"):
        return {"error": "proposal_type must be 'standard' or 'policy_change'"}

    if not auth.raw_token:
        return {"error": "No authentication token available"}

    try:
        duration_seconds = duration_days * 86400
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/governance/proposals",
                json={
                    "title": title.strip()[:200],
                    "description": description.strip(),
                    "duration_seconds": duration_seconds,
                    "proposal_type": proposal_type,
                },
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json"},
            )

        if r.status_code in (200, 201):
            data = r.json()
            deadline_str = (
                data.get("end_timestamp").isoformat()
                if hasattr(data.get("end_timestamp"), "isoformat")
                else str(data.get("end_timestamp", ""))
            )
            quorum_percent = data.get("quorum_percent", 10.0)
            pass_percent = data.get("pass_percent", 50.0)
            return {
                "proposal_id": data.get("id"),
                "title": data.get("title", title),
                "status": data.get("status", "VOTING"),
                "proposal_type": data.get("proposal_type", proposal_type),
                "proposer_did": data.get("proposer_did", ""),
                "voting_deadline": deadline_str,
                "duration_days": duration_days,
                "quorum_required": quorum_percent,
                "pass_threshold": pass_percent,
                "message": (
                    f"Proposal '{title}' created (ID #{data.get('id')}). "
                    f"Open for voting until {deadline_str}. "
                    f"Needs {quorum_percent}% quorum and {pass_percent}% approval to pass."
                ),
            }
        error_detail = refusal_reason(r)
        return {"error": f"Proposal creation failed (HTTP {r.status_code}): {error_detail}"}

    except MCPAuthError:
        raise
    except httpx.TimeoutException:
        return {"error": "Proposal creation request timed out"}
    except Exception as e:
        logger.error(f"createProposal error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ===========================================================================
# §pass70 Sprint 2 — Wave 2 (Tier 3 developer tools): 5 new
# ===========================================================================

async def get_my_developer_profile(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get your developer account profile (id, email, admin flags, verification status)."""
    require_developer_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/developers/me",
                headers={"Authorization": f"Bearer {auth.raw_token}"},
            )
        if r.status_code != 200:
            return {"error": http_refusal("developers/me", r)}
        return r.json()
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"getMyDeveloperProfile error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_my_api_keys(auth: MCPAuthContext) -> Dict[str, Any]:
    """List your developer API keys (id, prefix, description, active status). Plain key values are NOT returned (hashed at rest)."""
    require_developer_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/auth/api-keys",
                headers={"Authorization": f"Bearer {auth.raw_token}"},
            )
        if r.status_code != 200:
            return {"error": http_refusal("auth/api-keys", r)}
        body = r.json()
        return {"api_keys": body if isinstance(body, list) else [], "total": len(body) if isinstance(body, list) else 0}
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"getMyApiKeys error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def create_api_key(
    auth: MCPAuthContext,
    key_name: str,
) -> Dict[str, Any]:
    """
    Generate a new developer API key for programmatic access.
    The plain key value is returned ONCE — store it immediately, it cannot be retrieved again.
    """
    require_developer_auth(auth)
    if not key_name or not key_name.strip():
        return {"error": "key_name is required (10-200 chars)"}
    if len(key_name) > 200:
        return {"error": "key_name must be at most 200 chars"}
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/auth/api-keys",
                json=key_name.strip(),
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json"},
            )
        if r.status_code in (200, 201):
            data = r.json()
            data["warning"] = "STORE plain_api_key immediately — it cannot be retrieved again."
            return data
        detail = refusal_reason(r)
        return {"error": f"createApiKey failed (HTTP {r.status_code}): {detail}"}
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"createApiKey error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_my_organizations(auth: MCPAuthContext) -> Dict[str, Any]:
    """List organizations this developer is a member of."""
    require_developer_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/organizations",
                headers={"Authorization": f"Bearer {auth.raw_token}"},
            )
        if r.status_code != 200:
            return {"error": http_refusal("organizations", r)}
        body = r.json()
        return {"organizations": body if isinstance(body, list) else [], "total": len(body) if isinstance(body, list) else 0}
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"getMyOrganizations error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_my_agent_bundles(
    auth: MCPAuthContext,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List your agent bundles (signed .tpb archives for snapshot/template/migration)."""
    require_developer_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/bundles",
                params={"limit": limit, "offset": offset},
                headers={"Authorization": f"Bearer {auth.raw_token}"},
            )
        if r.status_code != 200:
            return {"error": http_refusal("bundles", r)}
        return r.json()
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"getMyAgentBundles error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ===========================================================================
# §pass70 Sprint 3 — Wave 4 (Tier 3 developer): 4 new
# ===========================================================================

async def submit_support_ticket(
    auth: MCPAuthContext,
    subject: str,
    message: str,
    category: str = "general",
    priority: str = "normal",
) -> Dict[str, Any]:
    """
    File a support ticket.
    category: 'bug' | 'question' | 'feature' | 'account' | 'general'
    priority: 'low' | 'normal' | 'high' | 'urgent'
    """
    require_developer_auth(auth)
    if not subject or not subject.strip():
        return {"error": "subject is required"}
    if len(subject) > 200:
        return {"error": "subject must be at most 200 chars"}
    if not message or not message.strip():
        return {"error": "message is required"}
    if category not in ("bug", "question", "feature", "account", "general"):
        return {"error": "category must be one of: bug, question, feature, account, general"}
    if priority not in ("low", "normal", "high", "urgent"):
        return {"error": "priority must be one of: low, normal, high, urgent"}
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/support/tickets",
                json={"subject": subject, "message": message, "category": category, "priority": priority},
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json"},
            )
        if r.status_code in (200, 201):
            return r.json()
        detail = refusal_reason(r)
        return {"error": f"submitSupportTicket failed (HTTP {r.status_code}): {detail}"}
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"submitSupportTicket error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_my_support_tickets(
    auth: MCPAuthContext,
    ticket_status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List your support tickets. Filter by status (open/in_progress/resolved/closed)."""
    require_developer_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    params: Dict[str, Any] = {"limit": min(max(limit, 1), 200), "offset": max(offset, 0)}
    if ticket_status:
        if ticket_status not in ("open", "in_progress", "resolved", "closed"):
            return {"error": "ticket_status must be one of: open, in_progress, resolved, closed"}
        params["status"] = ticket_status
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/support/tickets",
                params=params,
                headers={"Authorization": f"Bearer {auth.raw_token}"},
            )
        if r.status_code != 200:
            return {"error": http_refusal("support/tickets", r)}
        body = r.json()
        return {"tickets": body if isinstance(body, list) else [], "total": len(body) if isinstance(body, list) else 0}
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"getMySupportTickets error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def revoke_api_key(
    auth: MCPAuthContext,
    key_id: int,
) -> Dict[str, Any]:
    """
    Revoke a developer API key by ID. The key becomes inactive immediately.
    DESTRUCTIVE — only revoke keys you own and intend to retire.
    """
    require_developer_auth(auth)
    if key_id is None:
        return {"error": "key_id is required"}
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.delete(
                f"{REGISTRY_SELF_URL}/api/v1/auth/api-keys/{seg(key_id)}",
                headers={"Authorization": f"Bearer {auth.raw_token}"},
            )
        if r.status_code in (200, 204):
            return {"key_id": key_id, "status": "revoked", "message": f"API key {key_id} has been revoked and is no longer active."}
        detail = refusal_reason(r)
        return {"error": f"revokeApiKey failed (HTTP {r.status_code}): {detail}"}
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"revokeApiKey error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_my_disputes(
    auth: MCPAuthContext,
    dispute_status: Optional[str] = None,
    defendant_did: Optional[str] = None,
    complainant_did: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """List disputes (developer-tier view). Filter by status / defendant / complainant DID."""
    require_developer_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    params: Dict[str, Any] = {"limit": min(max(limit, 1), 200), "offset": max(offset, 0)}
    if dispute_status:
        params["status"] = dispute_status
    if defendant_did:
        params["defendant_did"] = defendant_did
    if complainant_did:
        params["complainant_did"] = complainant_did
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/disputes/",
                params=params,
                headers={"Authorization": f"Bearer {auth.raw_token}"},
            )
        if r.status_code != 200:
            return {"error": http_refusal("disputes", r)}
        body = r.json()
        return {"disputes": body if isinstance(body, list) else [], "total": len(body) if isinstance(body, list) else 0}
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"getMyDisputes error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ===========================================================================
# §pass70 Sprint 4 — Tier 3 developer (12 new: 8 webhook + 1 stats + 3 cicd)
# ===========================================================================

async def _dev_request(auth: MCPAuthContext, method: str, path: str, *, params=None, json_body=None, raw=False,
                       binary_content: bool = False) -> Any:
    """Internal helper: HTTP request with developer JWT. A file the route answers comes back as its manifest
    (mcp/binary_answers.file_manifest); its content too only with `binary_content` (generated code, capped)."""
    require_developer_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE if method != "GET" else HTTPX_TIMEOUT_SHORT) as client:
            r = await client.request(
                method,
                f"{REGISTRY_SELF_URL}{path}",
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json"},
            )
        # §MCPTEST30 (2026-09-30): 202 Accepted is a success. POST /api/v1/account/request-deletion answers 202 with
        # {"ok": true, "message": "Account scheduled for anonymization ..."}, and this helper returned it as
        # "Error: HTTP 202: ..." — so every MCP client asking for its account's deletion was told it failed while the
        # deletion was scheduled (measured live on sbx-alpha by the self-account lifecycle, on a throwaway account).
        if r.status_code in (200, 201, 202):
            if raw:
                return r.text
            # §MCPTEST30 (V0640): a file was answered as its first 300 characters decoded as text, which no caller
            # could use; it is answered by its manifest now, its content only where the tool asks for it
            headers, data = getattr(r, "headers", None) or {}, getattr(r, "content", b"") or b""
            if is_file(headers.get("content-type", ""), data):
                return file_manifest(data, headers.get("content-type", ""), headers.get("content-disposition", ""),
                                     content=binary_content)
            try:
                return r.json()
            except Exception:
                return {"status": "ok", "raw": r.text[:300]}
        if r.status_code == 204:
            return {"status": "deleted"}
        detail = r.text[:300]
        try:
            j = r.json()
            detail = j.get("detail", detail) if isinstance(j, dict) else detail
        except Exception:
            pass
        return {"error": f"HTTP {r.status_code}: {detail}"}
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"_dev_request({method} {path}) error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_my_webhooks(auth: MCPAuthContext) -> Dict[str, Any]:
    """List your registered webhook subscriptions."""
    body = await _dev_request(auth, "GET", "/api/v1/webhooks")
    if isinstance(body, list):
        return {"webhooks": body, "total": len(body)}
    return body


async def create_webhook(
    auth: MCPAuthContext,
    url: str,
    events: List[str],
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Register a new webhook subscription. Events fired on the listed event types will POST to url.
    Use getSupportedWebhookEvents to see valid event types.
    """
    if not url:
        return {"error": "url is required"}
    if not events or not isinstance(events, list):
        return {"error": "events must be a non-empty list of event type strings"}
    body: Dict[str, Any] = {"url": url, "events": events}
    if description:
        body["description"] = description
    return await _dev_request(auth, "POST", "/api/v1/webhooks", json_body=body)


async def get_webhook(auth: MCPAuthContext, webhook_id: str) -> Dict[str, Any]:
    """Get details for a single webhook subscription."""
    if not webhook_id:
        return {"error": "webhook_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/webhooks/{seg(webhook_id)}")


async def update_webhook(
    auth: MCPAuthContext,
    webhook_id: str,
    url: Optional[str] = None,
    events: Optional[List[str]] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Dict[str, Any]:
    """Update fields on an existing webhook subscription. Only supplied fields change."""
    if not webhook_id:
        return {"error": "webhook_id is required"}
    body: Dict[str, Any] = {}
    if url is not None:
        body["url"] = url
    if events is not None:
        body["events"] = events
    if description is not None:
        body["description"] = description
    if is_active is not None:
        body["is_active"] = is_active
    if not body:
        return {"error": "at least one field must be provided to update"}
    return await _dev_request(auth, "PUT", f"/api/v1/webhooks/{seg(webhook_id)}", json_body=body)


async def delete_webhook(auth: MCPAuthContext, webhook_id: str) -> Dict[str, Any]:
    """Delete a webhook subscription. Future events will no longer fire to its URL."""
    if not webhook_id:
        return {"error": "webhook_id is required"}
    return await _dev_request(auth, "DELETE", f"/api/v1/webhooks/{seg(webhook_id)}")


async def get_webhook_deliveries(auth: MCPAuthContext, webhook_id: str, limit: int = 50) -> Dict[str, Any]:
    """Get recent delivery attempts (success + retry history) for a webhook."""
    if not webhook_id:
        return {"error": "webhook_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/webhooks/{seg(webhook_id)}/deliveries", params={"limit": min(max(limit,1),100)})


async def test_webhook(auth: MCPAuthContext, webhook_id: str) -> Dict[str, Any]:
    """Fire a test event to the webhook URL — verifies your receiver is reachable + accepting signatures."""
    if not webhook_id:
        return {"error": "webhook_id is required"}
    return await _dev_request(auth, "POST", f"/api/v1/webhooks/{seg(webhook_id)}/test", json_body={})


async def get_supported_webhook_events(auth: MCPAuthContext) -> Dict[str, Any]:
    """List all event types you can subscribe to via createWebhook."""
    return await _dev_request(auth, "GET", "/api/v1/webhooks/events/supported")


async def get_developer_stats(auth: MCPAuthContext) -> Dict[str, Any]:
    """Aggregate stats for your developer account (agents, revenue, activity)."""
    return await _dev_request(auth, "GET", "/api/v1/developers/stats")


async def get_my_cicd_pipelines(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """List CI/CD pipelines for one of your agents."""
    if not agent_did:
        return {"error": "agent_did is required"}
    body = await _dev_request(auth, "GET", f"/api/v1/agents/{seg(agent_did)}/pipelines")
    if isinstance(body, list):
        return {"pipelines": body, "total": len(body)}
    return body


async def get_my_cicd_versions(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """List versions deployed for one of your agents.

    Returns {versions: [...], total: N}. The underlying endpoint returns
    {versions: [...]} (no total); we add `total` here so the MCP surface
    is consistent with other list-returning tools.
    """
    if not agent_did:
        return {"error": "agent_did is required"}
    body = await _dev_request(auth, "GET", f"/api/v1/agents/{seg(agent_did)}/versions")
    if isinstance(body, list):
        return {"versions": body, "total": len(body)}
    if isinstance(body, dict) and "versions" in body and "total" not in body:
        body["total"] = len(body.get("versions") or [])
    return body


async def get_my_cicd_deployments(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """List deployment history for one of your agents.

    Returns {deployments: [...], total: N}. The underlying endpoint returns
    {deployments: [...]} (no total); we add `total` here for consistency.
    """
    if not agent_did:
        return {"error": "agent_did is required"}
    body = await _dev_request(auth, "GET", f"/api/v1/agents/{seg(agent_did)}/deployments")
    if isinstance(body, list):
        return {"deployments": body, "total": len(body)}
    if isinstance(body, dict) and "deployments" in body and "total" not in body:
        body["total"] = len(body.get("deployments") or [])
    return body


# ===========================================================================
# §pass70 Sprint 5 — Tier 3 dev (8 new)
# ===========================================================================

async def get_my_mcp_audit_log(auth: MCPAuthContext, limit: int = 50, cursor: Optional[str] = None) -> Dict[str, Any]:
    """Get your own MCP tool-call audit log, newest first, paged by `cursor` (the id of the last row of the previous
    page). §MCPTEST30 (2026-10-01): the survey's UNDECLARED class: it sent `offset` to a route paged by `cursor`, so every page was the first."""
    params: Dict[str, Any] = {"limit": min(max(int(limit), 1), 200)}
    if cursor:
        params["cursor"] = cursor
    return await _dev_request(auth, "GET", "/api/v1/me/mcp-audit-log", params=params)


async def get_my_deletion_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Check whether you've requested account deletion. Returns deletion_status, requested_at, anonymizes_at, cooling_off_days."""
    return await _dev_request(auth, "GET", "/api/v1/account/deletion-status")


async def get_my_achievements(auth: MCPAuthContext) -> Dict[str, Any]:
    """List achievements (badges + payouts) earned by your developer account. Returns achievements[], total, total_payout, pending_count."""
    return await _dev_request(auth, "GET", "/api/v1/achievements/me")


async def get_my_unread_notifications(auth: MCPAuthContext) -> Dict[str, Any]:
    """List broadcast notifications you haven't read yet. Returns list of {id, title, body, broadcast_type, created_at}."""
    body = await _dev_request(auth, "GET", "/api/v1/notifications/unread")
    from .pocket_links import pocket_link
    if isinstance(body, list):
        return {"unread": body, "total": len(body), "open_in_app": pocket_link("/pocket/home?attention=1")}
    return body


async def mark_notification_read(auth: MCPAuthContext, broadcast_id: str) -> Dict[str, Any]:
    """Mark a broadcast notification as read/dismissed by your developer account. broadcast_id from getMyUnreadNotifications."""
    if not broadcast_id:
        return {"error": "broadcast_id is required"}
    res = await _dev_request(auth, "POST", f"/api/v1/notifications/{seg(broadcast_id)}/read")
    # Helper maps 204 No Content → {"status":"deleted"}. Re-label for clarity (notification is marked read, not deleted).
    if isinstance(res, dict) and res.get("status") == "deleted":
        return {"status": "marked_read", "broadcast_id": broadcast_id}
    return res


async def get_organization(auth: MCPAuthContext, org_id: str) -> Dict[str, Any]:
    """Get a single organization by id. Returns name, slug, owner_id, description, website, member_count, agent_count."""
    if not org_id:
        return {"error": "org_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/organizations/{seg(org_id)}")


async def list_organization_members(auth: MCPAuthContext, org_id: str) -> Dict[str, Any]:
    """List members of an organization with their roles. Returns array of {id, developer_id, developer_name, role, joined_at}."""
    if not org_id:
        return {"error": "org_id is required"}
    body = await _dev_request(auth, "GET", f"/api/v1/organizations/{seg(org_id)}/members")
    if isinstance(body, list):
        return {"members": body, "total": len(body)}
    return body


async def get_featured_bundles(auth: MCPAuthContext) -> Dict[str, Any]:
    """List Bundle marketplace featured entries (templates/snapshots curated for discovery). Returns featured[] with id/name/slug/description."""
    return await _dev_request(auth, "GET", "/api/v1/bundles/marketplace/featured")


# ===========================================================================
# §pass70 Sprint 6 — Tier 3 dev (7 new)
# ===========================================================================

async def list_my_attestations(
    auth: MCPAuthContext,
    agent_did: Optional[str] = None,
    circuit_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """List the ZKP attestations stored on this registry, every agent's (attestations are public). Optional filters:
    agent_did (any agent), circuit_id."""
    params: Dict[str, Any] = {"limit": min(max(int(limit), 1), 200), "offset": max(int(offset), 0)}
    if agent_did:
        params["agent_did"] = agent_did
    if circuit_id:
        params["circuit_id"] = circuit_id
    return await _dev_request(auth, "GET", "/api/v1/attestations", params=params)


async def get_attestation_detail(auth: MCPAuthContext, attestation_id: str) -> Dict[str, Any]:
    """Get the attestation record by id: circuit_id and circuit_version, agent_did, public_inputs, proof_hash (sha256
    of the proof bytes), verified, failure_reason, submitted/verified/expiry times and revocation fields. Requires
    developer JWT."""
    if not attestation_id:
        return {"error": "attestation_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/attestations/{seg(attestation_id)}")


async def get_attestation_bundle(auth: MCPAuthContext, attestation_id: str) -> Dict[str, Any]:
    """Get the registry-signed bundle of an attestation (proof_b64, proof_hash, public_inputs, verified, revoked,
    valid_until and an Ed25519 signature). Check the signature with getAttestationSigningPubkey and the proof itself
    with `bb verify` against the circuit's verification key (/api/v1/circuits/{id}/vk)."""
    if not attestation_id:
        return {"error": "attestation_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/attestations/{seg(attestation_id)}/bundle")


async def get_trust_score(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """An agent's EigenTrust trust score from the latest computation: did, global_trust, similarity_score,
    integer_projection, epoch and computed_at. 404 while no computation has scored the agent."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _dev_request(auth, "GET", f"/api/v1/reputation/{seg(agent_did)}/trust-score")


async def get_volume_profile(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Get transaction volume profile for an agent: total_volume, unique_peers, avg_per_peer, volume_rank."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _dev_request(auth, "GET", f"/api/v1/reputation/{seg(agent_did)}/volume-profile")


async def get_cross_frame_reputation(auth: MCPAuthContext) -> Dict[str, Any]:
    """List cross-frame reputation scores (foreign-frame agents seen by this registry). Returns {foreign_reputation:[], agent_count, status}."""
    return await _dev_request(auth, "GET", "/api/v1/reputation/cross-frame")


async def get_reputation_computation_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """EigenTrust++ computation status: epoch, computed_at, agents_computed, computation_time_ms, last_epoch_converged."""
    return await _dev_request(auth, "GET", "/api/v1/reputation/computation-status")


# ===========================================================================
# §pass70 Sprint 7 — Tier 3 dev (10 new — org/team CRUD)
# ===========================================================================

async def create_organization(
    auth: MCPAuthContext,
    name: str,
    description: Optional[str] = None,
    website: Optional[str] = None,
    logo_url: Optional[str] = None,
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a new organization under your developer account. Returns the new org row with auto-generated slug + id."""
    if not name:
        return {"error": "name is required"}
    body: Dict[str, Any] = {"name": name}
    if description:
        body["description"] = description
    if website:
        body["website"] = website
    if logo_url:
        body["logo_url"] = logo_url
    if settings:
        body["settings"] = settings
    return await _dev_request(auth, "POST", "/api/v1/organizations", json_body=body)


async def update_organization(
    auth: MCPAuthContext,
    org_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    website: Optional[str] = None,
    logo_url: Optional[str] = None,
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Update fields on an organization. Pass only the fields you want to change. Owner-only."""
    if not org_id:
        return {"error": "org_id is required"}
    body: Dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if website is not None:
        body["website"] = website
    if logo_url is not None:
        body["logo_url"] = logo_url
    if settings is not None:
        body["settings"] = settings
    if not body:
        return {"error": "at least one field to update is required"}
    return await _dev_request(auth, "PUT", f"/api/v1/organizations/{seg(org_id)}", json_body=body)


async def delete_organization(auth: MCPAuthContext, org_id: str) -> Dict[str, Any]:
    """Delete an organization (owner only, irreversible). Cascades to teams + memberships + agent assignments."""
    if not org_id:
        return {"error": "org_id is required"}
    return await _dev_request(auth, "DELETE", f"/api/v1/organizations/{seg(org_id)}")


async def invite_organization_member(
    auth: MCPAuthContext,
    org_id: str,
    email: str,
    role: str = "member",
) -> Dict[str, Any]:
    """Invite a developer (by email) to an organization. Role defaults to 'member'. Returns invite token + URL."""
    if not org_id:
        return {"error": "org_id is required"}
    if not email:
        return {"error": "email is required"}
    return await _dev_request(
        auth, "POST", f"/api/v1/organizations/{seg(org_id)}/invite",
        json_body={"email": email, "role": role or "member"},
    )


async def list_organization_teams(auth: MCPAuthContext, org_id: str) -> Dict[str, Any]:
    """List all teams under an organization."""
    if not org_id:
        return {"error": "org_id is required"}
    body = await _dev_request(auth, "GET", f"/api/v1/organizations/{seg(org_id)}/teams")
    if isinstance(body, list):
        return {"teams": body, "total": len(body)}
    return body


async def create_organization_team(
    auth: MCPAuthContext,
    org_id: str,
    name: str,
    description: Optional[str] = None,
    permissions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a new team within an organization. permissions is a list of permission names (e.g. read_agents)."""
    if not org_id:
        return {"error": "org_id is required"}
    if not name:
        return {"error": "name is required"}
    body: Dict[str, Any] = {"name": name}
    if description:
        body["description"] = description
    if permissions:
        body["permissions"] = permissions
    return await _dev_request(auth, "POST", f"/api/v1/organizations/{seg(org_id)}/teams", json_body=body)


async def get_organization_team(auth: MCPAuthContext, org_id: str, team_id: str) -> Dict[str, Any]:
    """Get a single team by id (within an organization). Returns name, description, permissions, member_count."""
    if not org_id or not team_id:
        return {"error": "org_id and team_id are required"}
    return await _dev_request(auth, "GET", f"/api/v1/organizations/{seg(org_id)}/teams/{seg(team_id)}")


async def add_team_member(
    auth: MCPAuthContext,
    org_id: str,
    team_id: str,
    developer_id: int,
    role: str = "member",
) -> Dict[str, Any]:
    """Add a developer to a team. developer_id is the integer id (from listOrganizationMembers). Role defaults to 'member'."""
    if not org_id or not team_id:
        return {"error": "org_id and team_id are required"}
    if developer_id is None:
        return {"error": "developer_id is required"}
    return await _dev_request(
        auth, "POST", f"/api/v1/organizations/{seg(org_id)}/teams/{seg(team_id)}/members",
        json_body={"developer_id": int(developer_id), "role": role or "member"},
    )


async def assign_agent_to_org(auth: MCPAuthContext, org_id: str, agent_did: str) -> Dict[str, Any]:
    """Assign one of your agents (by DID) to an organization. The agent must already be owned by you."""
    if not org_id or not agent_did:
        return {"error": "org_id and agent_did are required"}
    return await _dev_request(auth, "POST", f"/api/v1/organizations/{seg(org_id)}/agents/{seg(agent_did)}/assign")


async def get_organization_by_slug(auth: MCPAuthContext, slug: str) -> Dict[str, Any]:
    """Look up an organization by its slug (human-readable identifier from listOrganizations)."""
    if not slug:
        return {"error": "slug is required"}
    return await _dev_request(auth, "GET", f"/api/v1/organizations/slug/{seg(slug)}")


async def get_dispute_by_id(auth: MCPAuthContext, dispute_id: str) -> Dict[str, Any]:
    """Get a single dispute by id (full record with status, ruling, parties, evidence). Requires developer JWT."""
    if not dispute_id:
        return {"error": "dispute_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/disputes/{seg(dispute_id)}")


# ===========================================================================
# §pass70 Sprint 8 — Tier 3 dev (14 new)
# ===========================================================================

async def get_fee_current_rate(auth: MCPAuthContext) -> Dict[str, Any]:
    """Current fleet-wide transaction fee rate (base + max + velocity-adjusted). Requires developer JWT."""
    return await _dev_request(auth, "GET", "/api/v1/fees/current-rate")



async def request_account_deletion(
    auth: MCPAuthContext,
    password: str,
    confirmation: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Request account deletion (cooling-off period applies). password + confirmation are required guards. WARNING: starts the deletion timer for your developer account."""
    if not password or not confirmation:
        return {"error": "password and confirmation are required"}
    body: Dict[str, Any] = {"password": password, "confirmation": confirmation}
    if reason:
        body["reason"] = reason
    return await _dev_request(auth, "POST", "/api/v1/account/request-deletion", json_body=body)


async def cancel_account_deletion(auth: MCPAuthContext) -> Dict[str, Any]:
    """Cancel a pending account deletion (must be within cooling-off window)."""
    return await _dev_request(auth, "POST", "/api/v1/account/cancel-deletion")


async def claim_pending_achievements(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Pay your pending achievement payouts to agent_did (the route does not check the agent is yours)."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _dev_request(auth, "POST", "/api/v1/achievements/claim-pending", json_body={"agent_did": agent_did})


async def record_achievement(
    auth: MCPAuthContext,
    achievement_type: str,
    agent_did: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Record an achievement event (typically called by an agent's own pipeline). achievement_type must be from the achievement catalog (see getAchievementCatalog)."""
    if not achievement_type:
        return {"error": "achievement_type is required"}
    body: Dict[str, Any] = {"achievement_type": achievement_type}
    if agent_did:
        body["agent_did"] = agent_did
    if metadata:
        body["metadata"] = metadata
    return await _dev_request(auth, "POST", "/api/v1/achievements/record", json_body=body)


async def list_organization_agents(auth: MCPAuthContext, org_id: str) -> Dict[str, Any]:
    """List all agents assigned to an organization. Returns {organization_id, team_id?, agents:[], count}."""
    if not org_id:
        return {"error": "org_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/organizations/{seg(org_id)}/agents")


async def get_organization_cicd_summary(auth: MCPAuthContext, org_id: str) -> Dict[str, Any]:
    """Aggregate CI/CD activity for an organization (agent count, pipelines, deployments_24h)."""
    if not org_id:
        return {"error": "org_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/organizations/{seg(org_id)}/cicd-summary")


async def remove_organization_member(auth: MCPAuthContext, org_id: str, developer_id: int) -> Dict[str, Any]:
    """Remove a developer from an organization (owner only). developer_id is the integer id from listOrganizationMembers."""
    if not org_id or developer_id is None:
        return {"error": "org_id and developer_id are required"}
    return await _dev_request(auth, "DELETE", f"/api/v1/organizations/{seg(org_id)}/members/{int(developer_id)}")


async def update_organization_team(
    auth: MCPAuthContext,
    org_id: str,
    team_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    permissions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Update fields on a team (name/description/permissions). Pass only the fields you want changed. permissions is a
    list of permission names; the route refused the object the schema used to ask for (422)."""
    if not org_id or not team_id:
        return {"error": "org_id and team_id are required"}
    body: Dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if permissions is not None:
        body["permissions"] = permissions
    if not body:
        return {"error": "at least one field to update is required"}
    return await _dev_request(auth, "PUT", f"/api/v1/organizations/{seg(org_id)}/teams/{seg(team_id)}", json_body=body)


async def delete_organization_team(auth: MCPAuthContext, org_id: str, team_id: str) -> Dict[str, Any]:
    """Delete a team within an organization (owner only). Cascades to team memberships."""
    if not org_id or not team_id:
        return {"error": "org_id and team_id are required"}
    return await _dev_request(auth, "DELETE", f"/api/v1/organizations/{seg(org_id)}/teams/{seg(team_id)}")


async def remove_team_member(auth: MCPAuthContext, org_id: str, team_id: str, developer_id: int) -> Dict[str, Any]:
    """Remove a developer from a team within an organization. developer_id is the integer id."""
    if not org_id or not team_id or developer_id is None:
        return {"error": "org_id, team_id, and developer_id are required"}
    return await _dev_request(
        auth, "DELETE",
        f"/api/v1/organizations/{seg(org_id)}/teams/{seg(team_id)}/members/{int(developer_id)}",
    )


async def unassign_agent_from_org(auth: MCPAuthContext, org_id: str, agent_did: str) -> Dict[str, Any]:
    """Unassign an agent (by DID) from an organization. Inverse of assignAgentToOrg."""
    if not org_id or not agent_did:
        return {"error": "org_id and agent_did are required"}
    return await _dev_request(auth, "POST", f"/api/v1/organizations/{seg(org_id)}/agents/{seg(agent_did)}/unassign")


async def get_auto_compound_for_agent(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Get auto-compound settings for any of YOUR agents (dev-tier variant of getMyPayoutRelock). Returns {enabled}."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _dev_request(auth, "GET", f"/api/v1/staking/rewards/agents/{seg(agent_did)}/auto-compound")


# ===========================================================================
# §pass70 Sprint 9 — Tier 3 dev (12 new)
# ===========================================================================

async def get_my_agent_cicd_stats(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """CI/CD stats for one of your agents (pipeline_count, deployment_count, last_deploy_at)."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _dev_request(auth, "GET", f"/api/v1/agents/{seg(agent_did)}/cicd-stats")


async def get_my_agent_logs(
    auth: MCPAuthContext,
    agent_did: str,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """Get agent logs (pipeline/deployment output) for one of your agents. Paginated.

    Returns {logs: [...], total: N, limit, offset}.
    """
    if not agent_did:
        return {"error": "agent_did is required"}
    body = await _dev_request(
        auth, "GET", f"/api/v1/agents/{seg(agent_did)}/logs",
        params={"limit": min(max(int(limit), 1), 500), "offset": max(int(offset), 0)},
    )
    if isinstance(body, list):
        return {"logs": body, "total": len(body), "limit": limit, "offset": offset}
    if isinstance(body, dict):
        if "logs" in body:
            body.setdefault("total", len(body.get("logs") or []))
            return body
        return body  # §MCPTEST30 (V0548): the failure as it came; it used to read as an empty list
    return {"error": "getMyAgentLogs: the route answered neither a list nor an object"}


async def list_agent_templates(auth: MCPAuthContext) -> Dict[str, Any]:
    """List agent templates (starter scaffolds) registered on this registry."""
    body = await _dev_request(auth, "GET", "/api/v1/agents/templates")
    if isinstance(body, list):
        return {"templates": body, "total": len(body)}
    return body


async def get_agent_template(auth: MCPAuthContext, template_id: str) -> Dict[str, Any]:
    """Get a single agent template by id (full manifest + acceptance criteria)."""
    if not template_id:
        return {"error": "template_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/agents/templates/{seg(template_id)}")


async def get_my_developer_activity(auth: MCPAuthContext, limit: int = 50, days: int = 30) -> Dict[str, Any]:
    """Get your developer-account activity stream (recent registry/agent events) over the last `days`.

    Returns {activity: [...], total: N}. §MCPTEST30 (2026-10-01): the survey's UNDECLARED class: the route reads `days`, not `limit`; the
    count is now taken here."""
    body = await _dev_request(
        auth, "GET", "/api/v1/developers/activity",
        params={"days": min(max(int(days), 1), 365)},
    )
    if isinstance(body, list):
        body = body[:min(max(int(limit), 1), 500)]
        return {"activity": body, "total": len(body)}
    if isinstance(body, dict):
        if "activity" in body:
            body.setdefault("total", len(body.get("activity") or []))
            return body
        return body  # §MCPTEST30 (V0548): the failure as it came; it used to read as an empty list
    return {"error": "getMyDeveloperActivity: the route answered neither a list nor an object"}


async def get_my_developer_teg_summary(auth: MCPAuthContext) -> Dict[str, Any]:
    """Totals across your agents (liquid, locked, total, average reputation, agent counts) from the registry's balance cache."""
    return await _dev_request(auth, "GET", "/api/v1/developers/me/teg-summary")


async def get_my_treasury_balance(auth: MCPAuthContext) -> Dict[str, Any]:
    """The registry's system treasury balance (the same for every developer)."""
    return await _dev_request(auth, "GET", "/api/v1/developers/me/teg-summary/treasury")


async def get_my_notification_prefs(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get your notification preferences (email_on/off for broadcast types, webhook digest cadence)."""
    return await _dev_request(auth, "GET", "/api/v1/developers/me/notification-prefs")


async def get_notification_catalog(auth: MCPAuthContext) -> Dict[str, Any]:
    """§NOTIFV2: the notification type catalog (audience-filtered) — categories, severities, per-channel defaults, mandatory flags."""
    return await _dev_request(auth, "GET", "/api/v1/notifications/catalog")


async def get_my_notification_matrix(auth: MCPAuthContext) -> Dict[str, Any]:
    """§NOTIFV2: your full effective notification matrix (catalog defaults + wildcard + explicit rows + legacy keys)."""
    return await _dev_request(auth, "GET", "/api/v1/notifications/prefs/effective")


async def update_notification_prefs(auth: MCPAuthContext, rows: list) -> Dict[str, Any]:
    """§NOTIFV2: bulk sparse upsert of notification preferences.

    rows: [{type_key, channel, enabled?, threshold_num?, reset?}] — channel one of
    inapp|email|push_desktop|push_mobile; reset=true deletes the row (back to catalog
    default). Mandatory and legacy-managed types are rejected by the backend.
    """
    return await _dev_request(auth, "PUT", "/api/v1/notifications/prefs",
                              json_body={"rows": rows})


async def get_my_signing_keys(auth: MCPAuthContext) -> Dict[str, Any]:
    """List your developer signing keys (Ed25519 keypairs for signing claim payloads)."""
    body = await _dev_request(auth, "GET", "/api/v1/developers/me/signing-keys")
    if isinstance(body, list):
        return {"signing_keys": body, "total": len(body)}
    return body


async def get_my_flare_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get your full flare state (earned tier + unlocked sets + active selection). Used by fiat-onramp flare-gated features."""
    return await _dev_request(auth, "GET", "/api/v1/fiat/flare/status")


async def get_my_fiat_purchases(auth: MCPAuthContext) -> Dict[str, Any]:
    """Your fiat on-ramp purchase history; 403 or 503 where the on-ramp is off (fiat_onramp_enabled)."""
    body = await _dev_request(auth, "GET", "/api/v1/fiat/my-purchases")
    if isinstance(body, list):
        return {"purchases": body, "total": len(body)}
    return body


async def get_my_2fa_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get current 2FA (TOTP) status for your developer account."""
    return await _dev_request(auth, "GET", "/api/v1/auth/2fa/status")


# ===========================================================================
# §pass70 Sprint 10 — Tier 3 dev (13 new — agent CI/CD mutations)
# ===========================================================================

async def create_pipeline(
    auth: MCPAuthContext,
    agent_did: str,
    pipeline_name: str,
    pipeline_config: Dict[str, Any],
    trigger_type: Optional[str] = None,
    webhook_url: Optional[str] = None,
    is_active: Optional[bool] = None,
    environment_vars: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a CI/CD pipeline on one of your agents. pipeline_config is free-form; trigger_type is enum (push/webhook/manual)."""
    if not agent_did or not pipeline_name or not isinstance(pipeline_config, dict):
        return {"error": "agent_did, pipeline_name, and pipeline_config (object) are required"}
    body: Dict[str, Any] = {"pipeline_name": pipeline_name, "pipeline_config": pipeline_config}
    if trigger_type: body["trigger_type"] = trigger_type
    if webhook_url: body["webhook_url"] = webhook_url
    if is_active is not None: body["is_active"] = bool(is_active)
    if environment_vars: body["environment_vars"] = environment_vars
    return await _dev_request(auth, "POST", f"/api/v1/agents/{seg(agent_did)}/pipelines", json_body=body)


async def update_pipeline(
    auth: MCPAuthContext,
    agent_did: str,
    pipeline_id: str,
    pipeline_name: Optional[str] = None,
    pipeline_config: Optional[Dict[str, Any]] = None,
    is_active: Optional[bool] = None,
) -> Dict[str, Any]:
    """Update fields on an existing pipeline (only the fields you want changed)."""
    if not agent_did or not pipeline_id:
        return {"error": "agent_did and pipeline_id are required"}
    body: Dict[str, Any] = {}
    if pipeline_name is not None: body["pipeline_name"] = pipeline_name
    if pipeline_config is not None: body["pipeline_config"] = pipeline_config
    if is_active is not None: body["is_active"] = bool(is_active)
    if not body: return {"error": "at least one field to update is required"}
    return await _dev_request(auth, "PUT", f"/api/v1/agents/{seg(agent_did)}/pipelines/{seg(pipeline_id)}", json_body=body)


async def delete_pipeline(auth: MCPAuthContext, agent_did: str, pipeline_id: str) -> Dict[str, Any]:
    """Delete a pipeline from one of your agents."""
    if not agent_did or not pipeline_id:
        return {"error": "agent_did and pipeline_id are required"}
    return await _dev_request(auth, "DELETE", f"/api/v1/agents/{seg(agent_did)}/pipelines/{seg(pipeline_id)}")


async def create_version(
    auth: MCPAuthContext,
    agent_did: str,
    version: str,
    commit_hash: Optional[str] = None,
    release_notes: Optional[str] = None,
    is_stable: Optional[bool] = None,
) -> Dict[str, Any]:
    """Create a new code version for one of your agents. version is semver string."""
    if not agent_did or not version:
        return {"error": "agent_did and version are required"}
    body: Dict[str, Any] = {"version": version}
    if commit_hash: body["commit_hash"] = commit_hash
    if release_notes: body["release_notes"] = release_notes
    if is_stable is not None: body["is_stable"] = bool(is_stable)
    return await _dev_request(auth, "POST", f"/api/v1/agents/{seg(agent_did)}/versions", json_body=body)


async def delete_version(auth: MCPAuthContext, agent_did: str, version_id: str) -> Dict[str, Any]:
    """Delete a version from one of your agents."""
    if not agent_did or not version_id:
        return {"error": "agent_did and version_id are required"}
    return await _dev_request(auth, "DELETE", f"/api/v1/agents/{seg(agent_did)}/versions/{seg(version_id)}")


async def activate_version(auth: MCPAuthContext, agent_did: str, version_id: str) -> Dict[str, Any]:
    """Activate a version (make it the canonical/active version for the agent)."""
    if not agent_did or not version_id:
        return {"error": "agent_did and version_id are required"}
    return await _dev_request(auth, "POST", f"/api/v1/agents/{seg(agent_did)}/versions/{seg(version_id)}/activate")


async def rollback_version(auth: MCPAuthContext, agent_did: str, version_id: str) -> Dict[str, Any]:
    """Roll back to a specific version. Sets it active + may trigger redeploy depending on agent config."""
    if not agent_did or not version_id:
        return {"error": "agent_did and version_id are required"}
    return await _dev_request(auth, "POST", f"/api/v1/agents/{seg(agent_did)}/versions/{seg(version_id)}/rollback")


async def trigger_deployment(
    auth: MCPAuthContext,
    agent_did: str,
    environment: str,
    pipeline_id: Optional[str] = None,
    version_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Trigger a deployment of one of your agents. environment is enum (production/staging/etc). Optional pipeline_id + version_id."""
    if not agent_did or not environment:
        return {"error": "agent_did and environment are required"}
    body: Dict[str, Any] = {"environment": environment}
    if pipeline_id: body["pipeline_id"] = pipeline_id
    if version_id: body["version_id"] = version_id
    return await _dev_request(auth, "POST", f"/api/v1/agents/{seg(agent_did)}/deployments", json_body=body)


async def get_deployment(auth: MCPAuthContext, agent_did: str, deployment_id: str) -> Dict[str, Any]:
    """Get a single deployment record by id."""
    if not agent_did or not deployment_id:
        return {"error": "agent_did and deployment_id are required"}
    return await _dev_request(auth, "GET", f"/api/v1/agents/{seg(agent_did)}/deployments/{seg(deployment_id)}")


async def append_deployment_logs(
    auth: MCPAuthContext,
    agent_did: str,
    deployment_id: str,
    logs: str,
) -> Dict[str, Any]:
    """Append log lines to a deployment (typically called by CI runner)."""
    if not agent_did or not deployment_id:
        return {"error": "agent_did and deployment_id are required"}
    return await _dev_request(
        auth, "POST", f"/api/v1/agents/{seg(agent_did)}/deployments/{seg(deployment_id)}/logs",
        json_body={"logs": logs},
    )


async def update_deployment_status(
    auth: MCPAuthContext,
    agent_did: str,
    deployment_id: str,
    status: str,
    error_message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Update deployment status (pending/running/success/failed/cancelled). Typically called by CI runner."""
    if not agent_did or not deployment_id or not status:
        return {"error": "agent_did, deployment_id, status are required"}
    body: Dict[str, Any] = {"status": status}
    if error_message: body["error_message"] = error_message
    if metadata: body["metadata"] = metadata
    return await _dev_request(
        auth, "POST", f"/api/v1/agents/{seg(agent_did)}/deployments/{seg(deployment_id)}/status",
        json_body=body,
    )


async def clone_agent(auth: MCPAuthContext, agent_did: str, new_name: Optional[str] = None) -> Dict[str, Any]:
    """Clone an agent (creates a copy under your developer account). Optional new_name (default: '<original_name>_clone')."""
    if not agent_did:
        return {"error": "agent_did is required"}
    params: Dict[str, Any] = {}
    if new_name:
        params["new_name"] = new_name
    return await _dev_request(auth, "POST", f"/api/v1/agents/{seg(agent_did)}/clone", params=params)


async def delete_my_agent(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE: agent self-delete (revoke) via DELETE /agents/me.

    Tier 2 — this is an AGENT-context operation: pass the agent's own JWT
    (inline `agent_jwt` arg or bearer). The endpoint authenticates the caller
    via get_current_agent, so a developer JWT is rejected with 401. Distinct
    from deleteMyAgentByDev (developer deletes one of its owned agents by DID).
    """
    from agentvault_registry.mcp.tools_agent import _agent_delete
    return await _agent_delete(auth, "/api/v1/agents/me", op_name="deleteMyAgent")


async def export_agent_dev(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Export an agent's configuration (snapshot: card, settings). Owner-only. Requires developer JWT."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _dev_request(auth, "GET", f"/api/v1/agents/{seg(agent_did)}/export")


async def update_my_developer_location(auth: MCPAuthContext, location_data: Dict[str, Any]) -> Dict[str, Any]:
    """Update authenticated developer's location (for globe visualization). location_data MUST include `latitude` and `longitude` (decimal degrees). Optional `location_label` (free-text) and `update_agents` (bool, default True — propagate to agents lacking explicit coords). Requires developer JWT."""
    if not isinstance(location_data, dict) or not location_data:
        return {"error": "location_data must be a non-empty object"}
    return await _dev_request(auth, "PUT", "/api/v1/agents/locations/me", json_body=location_data)


# ===========================================================================
# §pass70 Sprint 11 — Tier 3 dev (7 new)
# ===========================================================================

async def get_transactions_analytics(auth: MCPAuthContext) -> Dict[str, Any]:
    """Aggregate transaction analytics for your developer account (volume, fees, counts by type)."""
    return await _dev_request(auth, "GET", "/api/v1/teg/transactions/analytics")


async def get_agent_rewards_history(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Lifetime history of an agent's payouts on locked units as the TEG reports it (any agent DID)."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _dev_request(auth, "GET", f"/api/v1/teg/rewards/history/{seg(agent_did)}")


async def get_agent_pending_rewards(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Pending rewards of an agent as the TEG reports them (any agent DID)."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _dev_request(auth, "GET", f"/api/v1/teg/rewards/pending/{seg(agent_did)}")


async def get_agent_staking_balance(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Locked balance of an agent as the TEG reports it (any agent DID)."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _dev_request(auth, "GET", f"/api/v1/teg/staking/balance/{seg(agent_did)}")


async def get_agent_staking_history(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Lock and release history of an agent as the TEG reports it (any agent DID)."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _dev_request(auth, "GET", f"/api/v1/teg/staking/history/{seg(agent_did)}")


async def list_teg_policies(auth: MCPAuthContext) -> Dict[str, Any]:
    """List active TEG governance/compliance policies (fee schedules, velocity caps, etc.)."""
    body = await _dev_request(auth, "GET", "/api/v1/teg/policies")
    if isinstance(body, list):
        return {"policies": body, "total": len(body)}
    return body


async def get_teg_policies_compliance_dashboard(auth: MCPAuthContext) -> Dict[str, Any]:
    """TEG policy compliance dashboard (per-policy adherence scores + recent violations)."""
    return await _dev_request(auth, "GET", "/api/v1/teg/policies/compliance/dashboard")


# ===========================================================================
# §pass70 Sprint 12 — Tier 3 dev (15 new — federation + auth + bundle CRUD)
# ===========================================================================

# Federation peer management (5)

async def list_federation_peers(auth: MCPAuthContext) -> Dict[str, Any]:
    """List this registry's directly-peered (ACTIVE, non-child) federation peers.

    Sources the PUBLIC /api/v1/federation/peers/ endpoint (TRAILING SLASH — no auth
    required), which advertises only this registry's directly peered ACTIVE registries
    (chain-discovered + child peers are excluded by §audit-T8 single-hop rule). Use the
    admin getAllFederationPeersAdmin tool for the full set including discovered/chain peers.

    GOTCHA (do not "simplify" the path): the NO-trailing-slash /api/v1/federation/peers
    resolves to a DIFFERENT, federation-auth-gated endpoint (federation_sync, returns
    List[FederationPeerInfo]) that rejects developer/admin JWT with 401 — pointing the
    wrapper there silently swallowed every result to empty. The trailing slash is load-bearing.

    Normalizes the public {items, pagination} response to the {peers, total} envelope MCP
    clients expect; embeds any upstream error without raising a missing-key surprise.
    """
    body = await _dev_request(auth, "GET", "/api/v1/federation/peers/")
    if isinstance(body, dict) and body.get("error"):
        return {"peers": [], "total": 0, **body}
    if isinstance(body, list):
        return {"peers": body, "total": len(body)}
    if isinstance(body, dict):
        items = body.get("items")
        if items is None:
            items = body.get("peers") or []
        pag = body.get("pagination") or {}
        total = pag.get("total_items", len(items)) if isinstance(pag, dict) else len(items)
        return {"peers": items, "total": total, "pagination": pag}
    return {"peers": [], "total": 0}


async def get_my_federation_registrations(auth: MCPAuthContext) -> Dict[str, Any]:
    """List the federation peer registrations created by your developer account."""
    return await _dev_request(auth, "GET", "/api/v1/federation/peers/my/registrations")


async def trigger_federation_sync(auth: MCPAuthContext) -> Dict[str, Any]:
    """Trigger an on-demand federation sync cycle (out-of-band from the cron schedule)."""
    return await _dev_request(auth, "POST", "/api/v1/federation/sync/trigger")


async def get_federation_sync_status_dev(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get federation sync status (dev view — different from admin variant)."""
    return await _dev_request(auth, "GET", "/api/v1/federation/sync-status")


async def rotate_federation_license_self(
    auth: MCPAuthContext, federation_license_key: str, reason: str, idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """DESTRUCTIVE: rotate the federation license you present (forces all peers to re-handshake). Use only when the
    license is compromised. The route authenticates the license itself (X-Federation-License) and requires an
    X-Idempotency-Key: pass the same idempotency_key again to replay a rotation whose answer was lost (the old key
    then fetches the new one); one is generated when none is given. The license key is redacted from the MCP audit log."""
    require_developer_auth(auth)
    if not federation_license_key or not reason:
        return {"error": "federation_license_key and reason are required"}
    idem = idempotency_key or str(uuid.uuid4())
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/federation/license/rotate-self",
                json={"reason": reason},
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json",
                         "X-Federation-License": federation_license_key, "X-Idempotency-Key": idem},
            )
        if r.status_code in (200, 201):
            try:
                out = r.json()
            except Exception:
                out = {"status": "ok", "raw": r.text[:300]}
            if isinstance(out, dict):
                out.setdefault("idempotency_key", idem)
            return out
        return {"error": f"HTTP {r.status_code}: {r.text[:300]}", "idempotency_key": idem}
    except Exception as e:
        logger.error(f"rotateFederationLicenseSelf error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# Auth (5)

async def logout_session(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE: log out current session (revokes the JWT). Use carefully — kills your own session."""
    return await _dev_request(auth, "POST", "/api/v1/auth/logout")


async def get_auth_profile(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get full auth profile for current user (id, email, is_admin, is_verified, granular flags)."""
    return await _dev_request(auth, "GET", "/api/v1/auth/profile")


async def setup_2fa(auth: MCPAuthContext, password: str) -> Dict[str, Any]:
    """Initialize 2FA (TOTP) setup; the route requires your password. Returns QR-code-shaped seed + backup codes. Call verify2FA next to complete."""
    if not password:
        return {"error": "password is required"}
    return await _dev_request(auth, "POST", "/api/v1/auth/2fa/setup", json_body={"password": password})


async def verify_2fa(auth: MCPAuthContext, code: str) -> Dict[str, Any]:
    """Complete 2FA setup by verifying a TOTP code from your authenticator. Required before 2FA becomes active."""
    if not code:
        return {"error": "code is required"}
    return await _dev_request(auth, "POST", "/api/v1/auth/2fa/verify", json_body={"code": code})


async def disable_2fa_self(auth: MCPAuthContext, password: str, code: Optional[str] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: disable your own 2FA. The route requires your password and a current code (D6-233)."""
    if not password:
        return {"error": "password is required"}
    if not code:
        return {"error": "code is required: a current 6-digit authenticator code or an unused backup code"}
    return await _dev_request(auth, "POST", "/api/v1/auth/2fa/disable", json_body={"password": password, "code": code})


async def change_password(auth: MCPAuthContext, current_password: str, new_password: str) -> Dict[str, Any]:
    """DESTRUCTIVE: change your account password. Requires current password as confirmation."""
    if not current_password or not new_password:
        return {"error": "current_password and new_password are required"}
    return await _dev_request(auth, "POST", "/api/v1/auth/change-password", json_body={"current_password": current_password, "new_password": new_password})


# Bundle CRUD (5)

async def get_bundle_manifest(auth: MCPAuthContext, bundle_id: str) -> Dict[str, Any]:
    """Get a bundle's manifest (composition, version, dependencies, license)."""
    if not bundle_id:
        return {"error": "bundle_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/bundles/{seg(bundle_id)}/manifest")


async def rate_bundle(auth: MCPAuthContext, bundle_id: str, rating: int, comment: Optional[str] = None) -> Dict[str, Any]:
    """Rate a bundle (1-5 stars). Optional comment."""
    if not bundle_id or rating is None:
        return {"error": "bundle_id and rating are required"}
    body: Dict[str, Any] = {"rating": int(rating)}
    if comment:
        body["comment"] = comment
    return await _dev_request(auth, "POST", f"/api/v1/bundles/{seg(bundle_id)}/rating", json_body=body)


async def report_bundle(auth: MCPAuthContext, bundle_id: str, reason: str, details: Optional[str] = None) -> Dict[str, Any]:
    """Report a bundle for review (admin moderation queue). reason is enum (spam/malware/copyright/other)."""
    if not bundle_id or not reason:
        return {"error": "bundle_id and reason are required"}
    body: Dict[str, Any] = {"reason_code": reason}
    if details:
        body["comment"] = details
    return await _dev_request(auth, "POST", f"/api/v1/bundles/{seg(bundle_id)}/report", json_body=body)


async def fork_bundle(auth: MCPAuthContext, bundle_id: str, new_name: Optional[str] = None) -> Dict[str, Any]:
    """Fork a bundle (create your own copy). Optional new_name.

    §MCPTEST30 (2026-10-01): the survey's BODY_UNDECLARED class: the route names the fork from `name`; `new_name` was dropped and every fork kept the
    source's name."""
    if not bundle_id:
        return {"error": "bundle_id is required"}
    body: Dict[str, Any] = {}
    if new_name:
        body["name"] = new_name
    return await _dev_request(auth, "POST", f"/api/v1/bundles/{seg(bundle_id)}/fork", json_body=body)


async def delete_bundle(auth: MCPAuthContext, bundle_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: delete one of your bundles. Cascades to ratings + downloads. Owner-only."""
    if not bundle_id:
        return {"error": "bundle_id is required"}
    return await _dev_request(auth, "DELETE", f"/api/v1/bundles/{seg(bundle_id)}")


# ===========================================================================
# §pass70 Sprint 13 — Tier 3 dev (12 new — TEG reads + policies + federation peer mutations + frame inv)
# ===========================================================================

async def get_teg_transaction_detail(auth: MCPAuthContext, transaction_id: str) -> Dict[str, Any]:
    """Full TEG transaction detail by id."""
    if not transaction_id:
        return {"error": "transaction_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/teg/transaction/{seg(transaction_id)}")


async def get_agent_transaction_history(auth: MCPAuthContext, agent_id: str, limit: int = 50) -> Dict[str, Any]:
    """TEG-side transaction history for one of your agents by DID (a treasury administrator: any account)."""
    if not agent_id:
        return {"error": "agent_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/teg/transactions/history/{seg(agent_id)}", params={"limit": min(max(int(limit), 1), 500)})


async def export_teg_transactions(auth: MCPAuthContext, fmt: str = "json") -> Dict[str, Any]:
    """Export TEG transactions for your account (CSV/JSON). format = 'json' or 'csv'."""
    return await _dev_request(auth, "GET", "/api/v1/teg/transactions/export", params={"format": fmt})


async def create_teg_policy(
    auth: MCPAuthContext,
    policy_code: str,
    policy_name: str,
    policy_type: str,
    description: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
    enforcement_level: Optional[str] = None,
) -> Dict[str, Any]:
    """DESTRUCTIVE: create a TEG policy (fee/velocity/compliance rule). Requires admin_treasury flag."""
    if not policy_code or not policy_name or not policy_type:
        return {"error": "policy_code, policy_name, policy_type are required"}
    body: Dict[str, Any] = {"policy_code": policy_code, "policy_name": policy_name, "policy_type": policy_type}
    for k, v in [("description", description), ("parameters", parameters), ("enforcement_level", enforcement_level)]:
        if v is not None: body[k] = v
    return await _dev_request(auth, "POST", "/api/v1/teg/policies", json_body=body)


async def update_teg_policy(auth: MCPAuthContext, policy_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """DESTRUCTIVE: update a TEG policy. Pass only the fields you want changed in `updates`."""
    if not policy_id or not isinstance(updates, dict):
        return {"error": "policy_id and updates object are required"}
    return await _dev_request(auth, "PUT", f"/api/v1/teg/policies/{seg(policy_id)}", json_body=updates)


async def delete_teg_policy(auth: MCPAuthContext, policy_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: delete a TEG policy."""
    if not policy_id:
        return {"error": "policy_id is required"}
    return await _dev_request(auth, "DELETE", f"/api/v1/teg/policies/{seg(policy_id)}")


async def get_teg_policy(auth: MCPAuthContext, policy_id: str) -> Dict[str, Any]:
    """Get one TEG policy's details by id."""
    if not policy_id:
        return {"error": "policy_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/teg/policies/{seg(policy_id)}")


async def resolve_teg_dispute(
    auth: MCPAuthContext,
    dispute_id: str,
    resolution: str,
    resolution_details: Optional[str] = None,
    penalty_amount: Optional[float] = None,
) -> Dict[str, Any]:
    """Resolve a TEG dispute: REFUSED for every caller since V0545 (403 "Not authorized to resolve disputes").
    The TEG's resolutions are RESOLVED_FAVOR_INITIATOR / RESOLVED_FAVOR_RESPONDENT / RESOLVED_NO_ACTION / REJECTED (the
    UPHELD/DISMISSED/SETTLED this tool advertised were never the TEG's). Agent JWT.

    §MCPTEST30 (V0545): the TEG accepts the REGISTRY's mTLS identity as its admin, so this route's own gate was the only
    one, and it was `disputes.file`, which every agent holds from its `client` birth role. Only a transport slip stood in
    between (the route sent `resolution` in a JSON body, the TEG reads it from the query: every call met the TEG's 422).
    The route now refuses before it forwards; who may resolve a TEG dispute through the registry is his decision.

    §MCPTEST30 (V0538): POST /teg/disputes/{id}/resolve authenticates an AGENT (require_agent_permission) and this tool
    sent the developer's token, so every call answered 401 "Could not validate agent credentials", the answer its
    contract pinned. Tier 2 now. ⚠ Beyond the tool: the TEG resolves a dispute only for its admin key and reads the
    resolution from the query, while the route forwards the agent's own TEG token in a JSON body, so no caller resolves
    one through the registry yet (named for him, not changed here)."""
    if not dispute_id or not resolution:
        return {"error": "dispute_id and resolution are required"}
    body: Dict[str, Any] = {"resolution": resolution}
    if resolution_details: body["resolution_details"] = resolution_details
    # the route reads the penalty as a decimal string; a number was refused (422)
    if penalty_amount is not None: body["penalty_amount"] = str(penalty_amount)
    from agentvault_registry.mcp.tools_agent import _agent_post
    return await _agent_post(auth, f"/api/v1/teg/disputes/{seg(dispute_id)}/resolve", json_body=body,
                             op_name="resolveTegDispute", refusal_reason=True)


async def get_teg_dispute_detail(auth: MCPAuthContext, dispute_log_id: str) -> Dict[str, Any]:
    """Get a single TEG dispute's full record, as a PARTY to it. Agent JWT.

    §MCPTEST30 (2026-10-01): GET /teg/disputes/{id} takes an agent token (only the parties read a dispute) and this tool
    sent the developer's, so every call answered 401; it is Tier 2 now, the getAgentReputation fix of §pass73.3.19."""
    if not dispute_log_id:
        return {"error": "dispute_log_id is required"}
    from agentvault_registry.mcp.tools_agent import _agent_get
    return await _agent_get(auth, f"/api/v1/teg/disputes/{seg(dispute_log_id)}", op_name="getTegDisputeDetail",
                            refusal_reason=True)


async def get_agent_reputation(auth: MCPAuthContext, agent_id: str) -> Dict[str, Any]:
    """Get the EigenTrust reputation score for any agent by TEG agent_id. Agent JWT."""
    if not agent_id:
        return {"error": "agent_id is required"}
    # The /teg/agents/{id}/reputation endpoint is AGENT-authed ("any authenticated
    # agent can view reputation scores"). This tool is therefore Tier 2 — use the
    # agent helper, NOT _dev_request (which forces developer auth → 401). (§pass73.3.19)
    from agentvault_registry.mcp.tools_agent import _agent_get
    return await _agent_get(auth, f"/api/v1/teg/agents/{seg(agent_id)}/reputation", op_name="getAgentReputation")


async def create_frame_invitation(
    auth: MCPAuthContext,
    trust_domain: str,
    bundle_endpoint_url: str,
    federation_endpoint_url: str,
    name: str,
    contact_email: str,
    initiator_nonce: str,
    event_store_url: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """DESTRUCTIVE: create a frame invitation (initiate cross-frame federation handshake). Only callable on sovereign mainframes."""
    if not all([trust_domain, bundle_endpoint_url, federation_endpoint_url, name, contact_email, initiator_nonce]):
        return {"error": "trust_domain, bundle_endpoint_url, federation_endpoint_url, name, contact_email, initiator_nonce are required"}
    body: Dict[str, Any] = {
        "trust_domain": trust_domain, "bundle_endpoint_url": bundle_endpoint_url,
        "federation_endpoint_url": federation_endpoint_url, "name": name,
        "contact_email": contact_email, "initiator_nonce": initiator_nonce,
    }
    if event_store_url: body["event_store_url"] = event_store_url
    if description: body["description"] = description
    return await _dev_request(auth, "POST", "/api/v1/federation/frame-invitations", json_body=body)


async def finalize_frame_invitation(
    auth: MCPAuthContext, invitation_id: str, approver_trust_domain: str, approver_bundle_endpoint_url: str,
    approver_name: str, approver_bundle_pem: str, nonce_echo: str,
    approver_federation_endpoint_url: Optional[str] = None,
) -> Dict[str, Any]:
    """DESTRUCTIVE: finalize a frame invitation (complete cross-frame federation handshake) with the approver's facts.
    The route's optional federation_license_key is not taken here: tool arguments are recorded in the MCP audit log."""
    if not invitation_id or not approver_trust_domain or not approver_bundle_endpoint_url or not approver_name \
            or not approver_bundle_pem or not nonce_echo:
        return {"error": "invitation_id, approver_trust_domain, approver_bundle_endpoint_url, approver_name, "
                         "approver_bundle_pem and nonce_echo are required"}
    body: Dict[str, Any] = {"approver_trust_domain": approver_trust_domain,
                            "approver_bundle_endpoint_url": approver_bundle_endpoint_url,
                            "approver_name": approver_name, "approver_bundle_pem": approver_bundle_pem,
                            "nonce_echo": nonce_echo}
    if approver_federation_endpoint_url:
        body["approver_federation_endpoint_url"] = approver_federation_endpoint_url
    return await _dev_request(auth, "POST", f"/api/v1/federation/frame-invitations/{seg(invitation_id)}/finalize", json_body=body)


# ===========================================================================
# §pass70 Sprint 14 — Tier 3 dev (15 new — federation dispute settlements + slash + peer mgmt + onboard + utils)
# ===========================================================================

async def validate_agent_card(auth: MCPAuthContext, card: Dict[str, Any]) -> Dict[str, Any]:
    """Validate an Agent Card JSON against the canonical schema. Returns {valid, errors[]}."""
    if not isinstance(card, dict):
        return {"error": "card must be an object"}
    return await _dev_request(auth, "POST", "/api/v1/utils/validate-card", json_body={"card_data": card})


async def download_bundle_via_onboard(auth: MCPAuthContext, bundle_data: Dict[str, Any]) -> Dict[str, Any]:
    """Download an operator bundle via the onboarding flow."""
    if not isinstance(bundle_data, dict):
        return {"error": "bundle_data must be an object"}
    return await _dev_request(auth, "POST", "/api/v1/onboard/download-bundle", json_body=bundle_data)


async def reset_agent_credentials_onboard(
    auth: MCPAuthContext, agent_did: str, password: str, totp_code: Optional[str] = None, challenge_id: Optional[str] = None,
) -> Dict[str, Any]:
    """DESTRUCTIVE: reset agent OAuth credentials via onboarding flow (issues new client_secret — shown ONCE). Requires your password."""
    if not agent_did or not password:
        return {"error": "agent_did and password are required"}
    body: Dict[str, Any] = {"password": password}
    if totp_code:
        body["totp_code"] = totp_code
    if challenge_id:
        body["challenge_id"] = challenge_id
    return await _dev_request(auth, "POST", f"/api/v1/onboard/agents/{seg(agent_did)}/reset-credentials", json_body=body)


async def get_federation_dispute_settlements(auth: MCPAuthContext, limit: int = 50, offset: int = 0,
                                             status_filter: Optional[str] = None) -> Dict[str, Any]:
    """List cross-frame dispute settlements (federation-level adjudication queue), newest first.

    §MCPTEST30 (2026-10-01): the survey's UNDECLARED class: the route serves the 100 newest (optionally one status) and reads no `limit` or
    `offset`, so both were dropped; the window is now taken here, from what the route served."""
    lim, off = min(max(int(limit), 1), 500), max(int(offset), 0)
    body = await _dev_request(auth, "GET", "/api/v1/federation/disputes/settlements",
                              params={"status_filter": status_filter} if status_filter else None)
    rows = body if isinstance(body, list) else (body.get("settlements") if isinstance(body, dict) else None)
    if isinstance(rows, list):
        page = rows[off:off + lim]
        out = dict(body) if isinstance(body, dict) else {}
        out.update(settlements=page, total=len(rows), limit=lim, offset=off, served_window=100)
        return out
    return body


async def get_federation_dispute_settlement(auth: MCPAuthContext, settlement_id: str) -> Dict[str, Any]:
    """Get a single federation dispute settlement by id."""
    if not settlement_id:
        return {"error": "settlement_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/federation/disputes/settlements/{seg(settlement_id)}")


async def approve_dispute_settlement(auth: MCPAuthContext, settlement_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: approve a cross-frame dispute settlement (triggers cross-frame slash on the defendant frame)."""
    if not settlement_id:
        return {"error": "settlement_id is required"}
    return await _dev_request(auth, "POST", f"/api/v1/federation/disputes/settlements/{seg(settlement_id)}/approve")


async def reject_dispute_settlement(auth: MCPAuthContext, settlement_id: str) -> Dict[str, Any]:
    """Reject a cross-frame dispute settlement (cancels the cross-frame action)."""
    if not settlement_id:
        return {"error": "settlement_id is required"}
    return await _dev_request(auth, "POST", f"/api/v1/federation/disputes/settlements/{seg(settlement_id)}/reject")


async def get_peer_slash_config(auth: MCPAuthContext) -> Dict[str, Any]:
    """Per-peer slash configuration (max_slash_amount, requires_callback, dispute_ttl). Used by the cross-frame slash workflow."""
    return await _dev_request(auth, "GET", "/api/v1/federation/disputes/peer-slash-config")


async def update_peer_slash_config(auth: MCPAuthContext, peer_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """DESTRUCTIVE: update a peer's slash configuration (max amounts, callbacks, TTL)."""
    if not peer_id or not isinstance(config, dict):
        return {"error": "peer_id and config object are required"}
    return await _dev_request(auth, "PUT", f"/api/v1/federation/disputes/peer-slash-config/{seg(peer_id)}", json_body=config)


async def get_federation_peer_by_id(auth: MCPAuthContext, peer_id: str) -> Dict[str, Any]:
    """Get federation peer detail by id."""
    if not peer_id:
        return {"error": "peer_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/federation/peers/{seg(peer_id)}")


async def update_federation_peer(auth: MCPAuthContext, peer_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """DESTRUCTIVE: update a federation peer registration (URL, name, trust_domain, etc.)."""
    if not peer_id or not isinstance(updates, dict):
        return {"error": "peer_id and updates object are required"}
    return await _dev_request(auth, "PUT", f"/api/v1/federation/peers/{seg(peer_id)}", json_body=updates)


async def delete_federation_peer_self(auth: MCPAuthContext, peer_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: delete a federation peer registration (own peer, not admin variant)."""
    if not peer_id:
        return {"error": "peer_id is required"}
    return await _dev_request(auth, "DELETE", f"/api/v1/federation/peers/{seg(peer_id)}")


async def create_federation_peer(auth: MCPAuthContext, peer_data: Dict[str, Any]) -> Dict[str, Any]:
    """DESTRUCTIVE: create a federation peer registration (initiates federation handshake with another registry)."""
    if not isinstance(peer_data, dict):
        return {"error": "peer_data must be an object"}
    return await _dev_request(auth, "POST", "/api/v1/federation/peers/", json_body=peer_data)


async def federation_slash_request(auth: MCPAuthContext, settlement_id: str, dispute_id: int, ruling: str, amount: int, complainant_did: str, defendant_did: str, origin_registry_url: str, callback_url: str) -> Dict[str, Any]:
    """DESTRUCTIVE (peer-to-peer): receive a slash request from a peer registry. Typically called by another registry, not directly."""
    if not all([settlement_id, dispute_id, ruling, amount, complainant_did, defendant_did, origin_registry_url, callback_url]):
        return {"error": "all 8 fields required for slash-request"}
    return await _dev_request(
        auth, "POST", "/api/v1/federation/disputes/slash-request",
        json_body={"settlement_id": settlement_id, "dispute_id": int(dispute_id), "ruling": ruling,
                   "amount": int(amount), "complainant_did": complainant_did, "defendant_did": defendant_did,
                   "origin_registry_url": origin_registry_url, "callback_url": callback_url},
    )


async def federation_slash_confirmation(auth: MCPAuthContext, settlement_id: str, status: str, amount: int, slash_event_id: Optional[str] = None, slash_tx_id: Optional[str] = None, error_message: Optional[str] = None) -> Dict[str, Any]:
    """Submit slash confirmation back to originating peer (after executing a peer's slash request locally). Federation peer-to-peer."""
    if not settlement_id or not status or amount is None:
        return {"error": "settlement_id, status, amount are required"}
    body: Dict[str, Any] = {"settlement_id": settlement_id, "status": status, "amount": int(amount)}
    for k, v in [("slash_event_id", slash_event_id), ("slash_tx_id", slash_tx_id), ("error_message", error_message)]:
        if v: body[k] = v
    return await _dev_request(auth, "POST", "/api/v1/federation/disputes/slash-confirmation", json_body=body)


# ===========================================================================
# §pass70 Sprint 15 — Tier 3 dev (12 new — flare management)
# ===========================================================================

async def set_flare_corner_variant(auth: MCPAuthContext, agent_did: str, variant: str) -> Dict[str, Any]:
    """Set the corner-badge variant on one of your agents (admin-only granular control)."""
    if not agent_did or not variant:
        return {"error": "agent_did and variant are required"}
    return await _dev_request(auth, "PATCH", f"/api/v1/fiat/flare/agent/{seg(agent_did)}/corner-variant", json_body={"variant": variant})


async def set_flare_overlay(auth: MCPAuthContext, agent_did: str, overlay: str) -> Dict[str, Any]:
    """Set the broken-machine overlay variant on one of your agents."""
    if not agent_did or not overlay:
        return {"error": "agent_did and overlay are required"}
    return await _dev_request(auth, "PATCH", f"/api/v1/fiat/flare/agent/{seg(agent_did)}/overlay", json_body={"overlay": overlay})


async def set_flare_variant(auth: MCPAuthContext, agent_did: str, variant: str) -> Dict[str, Any]:
    """Set the encirclement variant on one of your agents."""
    if not agent_did or not variant:
        return {"error": "agent_did and variant are required"}
    return await _dev_request(auth, "PATCH", f"/api/v1/fiat/flare/agent/{seg(agent_did)}/variant", json_body={"variant": variant})


async def flare_celebration_acknowledge(auth: MCPAuthContext) -> Dict[str, Any]:
    """Acknowledge the Shadow Chancellor upgrade modal (one-shot)."""
    return await _dev_request(auth, "POST", "/api/v1/fiat/flare/celebration-acknowledge")


async def customize_flare(auth: MCPAuthContext, customizations: Dict[str, Any]) -> Dict[str, Any]:
    """Customize the caller's flare (display name, tagline, logo, link, etc.)."""
    if not isinstance(customizations, dict):
        return {"error": "customizations must be an object"}
    return await _dev_request(auth, "PATCH", "/api/v1/fiat/flare/customize", json_body=customizations)


async def equip_flare(auth: MCPAuthContext, slot: str, agent_did: str, variant: Optional[str] = None) -> Dict[str, Any]:
    """Equip a single flare slot (corner|encirclement) on one of your agents."""
    if not slot or not agent_did:
        return {"error": "slot ('corner' or 'encirclement') and agent_did are required"}
    body: Dict[str, Any] = {}
    if variant:
        body["variant"] = variant
    return await _dev_request(auth, "POST", f"/api/v1/fiat/flare/equip/{seg(slot)}/{seg(agent_did)}", json_body=body)


async def move_flare(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Move the caller's agent flare to one of their agents."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _dev_request(auth, "POST", f"/api/v1/fiat/flare/move/{seg(agent_did)}")


async def select_flare(auth: MCPAuthContext, selection: Dict[str, Any]) -> Dict[str, Any]:
    """Switch which flare(s) the caller is wearing (corner + encirclement)."""
    if not isinstance(selection, dict):
        return {"error": "selection must be an object"}
    return await _dev_request(auth, "PATCH", "/api/v1/fiat/flare/selection", json_body=selection)


async def unequip_flare(auth: MCPAuthContext, slot: str, agent_did: str) -> Dict[str, Any]:
    """Unequip a single flare slot (corner|encirclement) from one of your agents."""
    if not slot or not agent_did:
        return {"error": "slot ('corner' or 'encirclement') and agent_did are required"}
    return await _dev_request(auth, "POST", f"/api/v1/fiat/flare/unequip/{seg(slot)}/{seg(agent_did)}")


async def preview_slash_reduction_attestation(auth: MCPAuthContext, dispute_id: str) -> Dict[str, Any]:
    """Preview slash reduction (via attestation admin path) — see how much a dispute slash would be reduced by attestations."""
    if not dispute_id:
        return {"error": "dispute_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/attestations/admin/disputes/{seg(dispute_id)}/preview-slash-reduction")


async def preview_voting_power_attestation(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Preview the governance attestation bonus for an agent (sandbox registries only; elsewhere 403). Answers with the
    agent's verified, unrevoked attestations counted as distinct (circuit, UTC day) pairs over the window
    (recent_verified_attestations), the threshold, bonus_eligible and the multiplier (x1.05 at 10 in 30 days by
    default). Several proofs of one circuit on one day count once."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _dev_request(auth, "GET", "/api/v1/attestations/admin/governance/preview-voting-power", params={"agent_did": agent_did})


async def mcp_passthrough_get_agent_profile(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """MCP passthrough wrapper for getAgentProfile (forwards via attestation admin path)."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _dev_request(auth, "GET", "/api/v1/attestations/admin/mcp-passthrough/get-agent-profile", params={"agent_did": agent_did})


# ===========================================================================
# §pass70 Sprint 16 — Tier 3 dev (10 new)
# ===========================================================================

async def get_staking_distribution_records(auth: MCPAuthContext, distribution_id: str) -> Dict[str, Any]:
    """Per-agent payout records for a specific staking distribution: {"records": [...], "total": n}.

    §MCPTEST30 (V0546): the route answers a bare list, which this tool passed through, so nothing could state the
    answer's shape (round 14's cloud-op sweep: "contract gap" once V0545 gave the row its distribution). Wrapped the way
    getMyWebhooks wraps its list."""
    if not distribution_id:
        return {"error": "distribution_id is required"}
    body = await _dev_request(auth, "GET", f"/api/v1/staking/rewards/distributions/{seg(distribution_id)}/records")
    if isinstance(body, list):
        return {"records": body, "total": len(body)}
    return body


async def update_auto_compound(auth: MCPAuthContext, agent_did: str, enabled: bool) -> Dict[str, Any]:
    """Update auto-compound setting for one of your agents."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _dev_request(auth, "PUT", f"/api/v1/staking/rewards/agents/{seg(agent_did)}/auto-compound", json_body={"enabled": bool(enabled)})


async def trigger_manual_distribution(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE: manually trigger staking reward distribution. Admin-only (admin_treasury flag)."""
    return await _dev_request(auth, "POST", "/api/v1/staking/rewards/distribute/manual")


async def download_bundle(auth: MCPAuthContext, bundle_id: str) -> Dict[str, Any]:
    """Download bundle artifact. Returns metadata + signed-URL or base64 preview."""
    if not bundle_id:
        return {"error": "bundle_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/bundles/{seg(bundle_id)}/download")


async def restore_bundle(
    auth: MCPAuthContext, bundle_id: str, conflict_resolution: Optional[str] = None, mode: Optional[str] = None,
    include_cicd: Optional[bool] = None,
) -> Dict[str, Any]:
    """DESTRUCTIVE: restore (re-apply) a snapshot bundle to your account state."""
    if not bundle_id:
        return {"error": "bundle_id is required"}
    body: Dict[str, Any] = {}
    for k, v in (("conflict_resolution", conflict_resolution), ("mode", mode), ("include_cicd", include_cicd)):
        if v is not None:
            body[k] = v
    # the route requires a body even when every field takes its default
    return await _dev_request(auth, "POST", f"/api/v1/bundles/{seg(bundle_id)}/restore", json_body=body)


async def restore_from_upload(
    auth: MCPAuthContext, bundle_b64: str, filename: str = "bundle.zip", conflict_resolution: Optional[str] = None,
    mode: Optional[str] = None, include_cicd: Optional[bool] = None,
) -> Dict[str, Any]:
    """DESTRUCTIVE: restore from an uploaded bundle file (e.g. exported from another registry), sent as the
    multipart upload the route takes; bundle_b64 is the file's bytes in base64."""
    require_developer_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        raw = base64.b64decode(bundle_b64 or "", validate=True)
    except (binascii.Error, ValueError):
        return {"error": "bundle_b64 is not valid base64"}
    if not raw:
        return {"error": "bundle_b64 is required"}
    data: Dict[str, Any] = {}
    for k, v in (("conflict_resolution", conflict_resolution), ("mode", mode)):
        if v is not None:
            data[k] = v
    if include_cicd is not None:
        data["include_cicd"] = "true" if include_cicd else "false"
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/bundles/restore-from-upload",
                files={"file": (filename or "bundle.zip", raw, "application/octet-stream")},
                data=data,
                headers={"Authorization": f"Bearer {auth.raw_token}"},
            )
        if r.status_code in (200, 201):
            try:
                return r.json()
            except Exception:
                return {"status": "ok", "raw": r.text[:300]}
        return {"error": f"HTTP {r.status_code}: {r.text[:300]}"}
    except Exception as e:
        logger.error(f"restoreFromUpload error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def patch_bundle(auth: MCPAuthContext, bundle_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """DESTRUCTIVE: update fields on one of your bundles."""
    if not bundle_id or not isinstance(updates, dict):
        return {"error": "bundle_id and updates object are required"}
    return await _dev_request(auth, "PATCH", f"/api/v1/bundles/{seg(bundle_id)}", json_body=updates)


async def create_bundle(auth: MCPAuthContext, bundle_data: Dict[str, Any]) -> Dict[str, Any]:
    """DESTRUCTIVE: create a new bundle (snapshot/template/migration). bundle_data follows the create-bundle schema."""
    if not isinstance(bundle_data, dict):
        return {"error": "bundle_data must be an object"}
    return await _dev_request(auth, "POST", "/api/v1/bundles", json_body=bundle_data)


async def preview_admin_email_with_context(auth: MCPAuthContext, template: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Preview an admin email template with custom context (for testing template rendering)."""
    if not template or not isinstance(context, dict):
        return {"error": "template and context object are required"}
    return await _dev_request(auth, "POST", f"/api/v1/admin/email/preview/{seg(template)}", json_body=context)


async def preview_admin_email_text(auth: MCPAuthContext, template: str) -> Dict[str, Any]:
    """Preview the plain-text variant of an admin email template."""
    if not template:
        return {"error": "template is required"}
    return await _dev_request(auth, "GET", f"/api/v1/admin/email/preview/{seg(template)}/text")


# ===========================================================================
# §pass70 Sprint 17 — Tier 3 dev (12 new — dev /me variants + operator self-mgmt)
# ===========================================================================

async def rotate_my_signing_key(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE: rotate your developer signing key (Ed25519). 7-day grace window."""
    return await _dev_request(auth, "POST", "/api/v1/developers/me/signing-key/rotate")


async def get_my_api_key_detail(auth: MCPAuthContext, key_id: str) -> Dict[str, Any]:
    """Detail for one of your API keys (id, key_prefix, description, is_active,
    created_at, last_used_at). There is NO GET-by-id route server-side (only LIST +
    DELETE), so this fetches your key LIST and returns the one matching key_id —
    non-secret metadata only; the key value itself is never returned (hashed at rest)."""
    if not key_id:
        return {"error": "key_id is required"}
    body = await _dev_request(auth, "GET", "/api/v1/developers/me/apikeys")
    if isinstance(body, dict) and body.get("error"):
        return body
    items = body if isinstance(body, list) else (body.get("api_keys") or [] if isinstance(body, dict) else [])
    for k in items:
        if isinstance(k, dict) and str(k.get("id")) == str(key_id):
            return k
    return {"error": f"API key {key_id} not found"}


async def delete_my_api_key(auth: MCPAuthContext, key_id: str) -> Dict[str, Any]:
    """DESTRUCTIVE: deactivate (delete) one of your API keys. Owner-only."""
    if not key_id:
        return {"error": "key_id is required"}
    return await _dev_request(auth, "DELETE", f"/api/v1/developers/me/apikeys/{seg(key_id)}")


async def get_batch_agent_balances(auth: MCPAuthContext, agent_dids: list) -> Dict[str, Any]:
    """Get balances for multiple of your agents in one call."""
    if not agent_dids or not isinstance(agent_dids, list):
        return {"error": "agent_dids list is required"}
    return await _dev_request(auth, "POST", "/api/v1/developers/me/agents/balances", json_body={"agent_dids": agent_dids})


async def get_my_agent_balance(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Get the balance for one of your agents (canonical AVT total)."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _dev_request(auth, "GET", f"/api/v1/developers/me/agents/{seg(agent_did)}/balance")


async def delete_my_agent_by_dev(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: delete one of your agents from your developer account (distinct from /agents/me self-delete)."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _dev_request(auth, "DELETE", f"/api/v1/developers/me/agents/{seg(agent_did)}")


async def get_operator_my_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get your operator status (your own cloud-op registry state, if you have one)."""
    return await _dev_request(auth, "GET", "/api/v1/operators/my-status")


async def get_operator_my_bundle(auth: MCPAuthContext) -> Dict[str, Any]:
    """Download your operator bundle (signed config + license + bootstrap data)."""
    return await _dev_request(auth, "GET", "/api/v1/operators/my-bundle")


async def get_operator_my_lifecycle(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get your operator's full lifecycle stack (state transitions, last-action, pending-renew)."""
    return await _dev_request(auth, "GET", "/api/v1/operators/me/lifecycle")


async def activate_operator(auth: MCPAuthContext, activation_code: str) -> Dict[str, Any]:
    """DESTRUCTIVE: activate your operator with the activation code from its approval (approved -> active)."""
    if not activation_code:
        return {"error": "activation_code is required"}
    return await _dev_request(auth, "POST", "/api/v1/operators/activate", json_body={"activation_code": activation_code})


async def request_frame(auth: MCPAuthContext, request_data: Dict[str, Any]) -> Dict[str, Any]:
    """DESTRUCTIVE: submit a sovereign-frame request (review-only — Commander reviews). Goes through public-review pipeline."""
    if not isinstance(request_data, dict):
        return {"error": "request_data must be an object"}
    return await _dev_request(auth, "POST", "/api/v1/operators/request-frame", json_body=request_data)


async def self_provision_operator(auth: MCPAuthContext, provisioning_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: self-service cloud-op provisioning (flare-gated — requires Architect+ tier). Spins up real infra."""
    body = provisioning_data if isinstance(provisioning_data, dict) else {}
    return await _dev_request(auth, "POST", "/api/v1/operators/self-provision", json_body=body)


# ===========================================================================
# §pass70 Sprint 18 — Tier 3 dev (7 new — import/export + auth + operator-portal)
# ===========================================================================

async def import_agent(auth: MCPAuthContext, agent_config: Dict[str, Any], options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: import an agent from its export (creates the agent). Requires developer JWT. agent_config is the export JSON; a body that already carries export_data is sent as it is."""
    if not isinstance(agent_config, dict):
        return {"error": "agent_config must be an object"}
    body: Dict[str, Any] = dict(agent_config) if "export_data" in agent_config else {"export_data": agent_config}
    if isinstance(options, dict):
        body["options"] = options
    return await _dev_request(auth, "POST", "/api/v1/agents/import", json_body=body)


async def validate_agent_import(auth: MCPAuthContext, agent_config: Dict[str, Any], options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Validate an agent export for import without creating anything (dry run). agent_config is the export JSON; a body that already carries export_data is sent as it is."""
    if not isinstance(agent_config, dict):
        return {"error": "agent_config must be an object"}
    body: Dict[str, Any] = dict(agent_config) if "export_data" in agent_config else {"export_data": agent_config}
    if isinstance(options, dict):
        body["options"] = options
    return await _dev_request(auth, "POST", "/api/v1/agents/import/validate", json_body=body)


async def agent_bulk_export(auth: MCPAuthContext, agent_dids: list) -> Dict[str, Any]:
    """Bulk-export agents (returns signed export bundles). Owner-only."""
    if not agent_dids or not isinstance(agent_dids, list):
        return {"error": "agent_dids list is required"}
    return await _dev_request(auth, "POST", "/api/v1/agents/export/bulk", json_body={"agent_dids": agent_dids})


async def auth_refresh(auth: MCPAuthContext, refresh_token: str) -> Dict[str, Any]:
    """Refresh access token via refresh token. Returns new access_token + refresh_token."""
    if not refresh_token:
        return {"error": "refresh_token is required"}
    return await _dev_request(auth, "POST", "/api/v1/auth/refresh", json_body={"refresh_token": refresh_token})


async def regenerate_backup_codes(auth: MCPAuthContext, password: str, current_code: str) -> Dict[str, Any]:
    """DESTRUCTIVE: regenerate 2FA backup codes (invalidates old ones). Requires your password and a current TOTP code."""
    if not password or not current_code:
        return {"error": "password and current_code are required"}
    return await _dev_request(auth, "POST", "/api/v1/auth/2fa/backup-codes",
                              json_body={"password": password, "current_code": current_code})


async def operator_portal_self_logs(auth: MCPAuthContext, lines: int = 100) -> Dict[str, Any]:
    """Cloud-op admin self-logs via own federation license (operator BFF proxies to mainframe)."""
    return await _dev_request(auth, "GET", "/api/v1/operator-portal/self-logs", params={"tail": int(lines)})   # the route reads `tail`


async def operator_portal_self_restart(auth: MCPAuthContext, service: Optional[str] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: cloud-op admin self-restart via own federation license. Owner-only."""
    body: Dict[str, Any] = {}
    if service:
        body["service"] = service
    return await _dev_request(auth, "POST", "/api/v1/operator-portal/self-restart", json_body=body)


# ===========================================================================
# §pass70 Sprint 19 — Tier 3 dev (8 new)
# ===========================================================================

async def get_my_developer_jwks(auth: MCPAuthContext, developer_id: int) -> Dict[str, Any]:
    """Get JWKS for a developer (for verifying their signing-key payloads)."""
    if developer_id is None:
        return {"error": "developer_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/developers/{int(developer_id)}/jwks.json")


async def get_oauth_federation_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get OAuth federation status (cross-registry OAuth trust mesh)."""
    return await _dev_request(auth, "GET", "/api/v1/oauth/federation/status")


async def _dev_form_request(auth: MCPAuthContext, path: str, form: Dict[str, Any]) -> Any:
    """POST an application/x-www-form-urlencoded body with the developer JWT.

    RFC 7662 introspection and RFC 7009 revocation are Form endpoints; posting JSON
    to them 422s, which is what the previous oauthIntrospect wrapper did.
    """
    require_developer_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}{path}",
                data={k: v for k, v in form.items() if v is not None},
                headers={"Authorization": f"Bearer {auth.raw_token}"},
            )
        if r.status_code in (200, 201):
            try:
                return r.json()
            except Exception:
                return {"status": "ok", "raw": r.text[:300]}
        detail = r.text[:300]
        try:
            j = r.json()
            detail = j.get("detail", detail) if isinstance(j, dict) else detail
        except Exception:
            pass
        return {"error": f"HTTP {r.status_code}: {detail}"}
    except MCPAuthError:
        raise
    except Exception as e:  # noqa: BLE001
        return {"error": f"request failed: {e}"}


async def oauth_introspect(auth: MCPAuthContext, token: str, client_id: str, client_secret: str,
                           consume: bool = False, amount: Optional[str] = None) -> Dict[str, Any]:
    """OAuth 2.0 token introspection (RFC 7662) for an exchanged federation token.

    Answers from the exchange ledger: `active` plus `inactive_reason` (revoked /
    expired / already_used / amount_exceeds_max). `consume=true` burns a
    single-use token — that is the enforcement point, so do not pass it casually.
    """
    if not token:
        return {"error": "token is required"}
    if not client_id or not client_secret:
        return {"error": "client_id and client_secret are required (peer registry credentials)"}
    return await _dev_form_request(auth, "/api/v1/oauth/introspect", {
        "token": token, "client_id": client_id, "client_secret": client_secret,
        "consume": "true" if consume else "false", "amount": amount,
    })


async def oauth_revoke(auth: MCPAuthContext, client_id: str, client_secret: str,
                       token: Optional[str] = None, jti: Optional[str] = None,
                       reason: Optional[str] = None) -> Dict[str, Any]:
    """Revoke an exchanged federation token (RFC 7009). Accepts the token or its jti.

    Always returns 200, including for an unknown token — revocation must not become
    an oracle for which tokens exist.
    """
    if not token and not jti:
        return {"error": "pass either token or jti"}
    if not client_id or not client_secret:
        return {"error": "client_id and client_secret are required (peer registry credentials)"}
    return await _dev_form_request(auth, "/api/v1/oauth/revoke", {
        "token": token, "jti": jti, "reason": reason,
        "client_id": client_id, "client_secret": client_secret,
    })


async def oauth_federation_trust_list(auth: MCPAuthContext) -> Dict[str, Any]:
    """List this registry's OAuth federation trust entries (admin). Secrets are never returned."""
    return await _dev_request(auth, "GET", "/api/v1/oauth/federation/trust")


async def oauth_token_exchange(auth: MCPAuthContext, subject_token: str, subject_token_type: str,
                               client_id: str, client_secret: str,
                               audience: Optional[str] = None, scope: Optional[str] = None) -> Dict[str, Any]:
    """OAuth 2.0 token exchange (RFC 8693) against a trusted peer registry.

    The subject token is verified against the peer's published JWKS, so it must be
    a real token issued by the registry whose client credentials you present.
    """
    if not subject_token or not subject_token_type:
        return {"error": "subject_token and subject_token_type are required"}
    if not client_id or not client_secret:
        return {"error": "client_id and client_secret are required (peer registry credentials)"}
    body: Dict[str, Any] = {
        "subject_token": subject_token,
        "subject_token_type": subject_token_type,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if audience:
        body["audience"] = audience
    if scope:
        body["scope"] = scope
    return await _dev_request(auth, "POST", "/api/v1/oauth/token/exchange", json_body=body)


async def accept_org_invitation(auth: MCPAuthContext, token: str) -> Dict[str, Any]:
    """Accept an organization invitation via emailed token."""
    if not token:
        return {"error": "token is required"}
    return await _dev_request(auth, "POST", f"/api/v1/organizations/invitations/{seg(token)}/accept")


async def get_support_ticket_detail(auth: MCPAuthContext, ticket_id: str) -> Dict[str, Any]:
    """Get detail for one of your support tickets (full message history)."""
    if not ticket_id:
        return {"error": "ticket_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/support/tickets/{seg(ticket_id)}")


async def reply_support_ticket(auth: MCPAuthContext, ticket_id: str, message: str) -> Dict[str, Any]:
    """Reply to a support ticket (adds message to thread)."""
    if not ticket_id or not message:
        return {"error": "ticket_id and message are required"}
    return await _dev_request(auth, "POST", f"/api/v1/support/tickets/{seg(ticket_id)}/reply", json_body={"message": message})


async def request_self_revocation(auth: MCPAuthContext, reason: str) -> Dict[str, Any]:
    """DESTRUCTIVE: request self-revocation of operator credentials (initiates revoke workflow). The route requires a reason."""
    if not reason:
        return {"error": "reason is required"}
    return await _dev_request(auth, "POST", "/api/v1/operators/request-revocation", json_body={"reason": reason})


# ===========================================================================
# §pass70 Sprint 20 — Tier 3 dev (12 new)
# ===========================================================================

async def get_my_developer_activity_eventstore(auth: MCPAuthContext, limit: int = 50) -> Dict[str, Any]:
    """Get your developer's EventStore activity (rich event detail per developer)."""
    return await _dev_request(auth, "GET", "/api/v1/developers/me/activity", params={"limit": min(max(int(limit), 1), 200)})


async def list_developer_apikeys_me(auth: MCPAuthContext) -> Dict[str, Any]:
    """List API keys for your dev account via /developers/me path.

    Returns {api_keys: [...], total: N}.
    """
    body = await _dev_request(auth, "GET", "/api/v1/developers/me/apikeys")
    if isinstance(body, list):
        return {"api_keys": body, "total": len(body)}
    if isinstance(body, dict):
        if "api_keys" in body:
            body.setdefault("total", len(body.get("api_keys") or []))
            return body
        return body  # §MCPTEST30 (V0548): the failure as it came; it used to read as an empty list
    return {"error": "listDeveloperApikeysMe: the route answered neither a list nor an object"}


async def create_developer_apikey_me(auth: MCPAuthContext, description: str) -> Dict[str, Any]:
    """DESTRUCTIVE: create a programmatic API key (alt path under /developers/me)."""
    if not description:
        return {"error": "description is required"}
    return await _dev_request(auth, "POST", "/api/v1/developers/me/apikeys", json_body={"description": description})


async def list_developer_webhooks(auth: MCPAuthContext) -> Dict[str, Any]:
    """List your developer webhooks via /developers/webhooks (alt path).

    Returns {webhooks: [...], total: N}.
    """
    body = await _dev_request(auth, "GET", "/api/v1/developers/webhooks")
    if isinstance(body, list):
        return {"webhooks": body, "total": len(body)}
    if isinstance(body, dict):
        if "webhooks" in body:
            body.setdefault("total", len(body.get("webhooks") or []))
            return body
        return body  # §MCPTEST30 (V0548): the failure as it came; it used to read as an empty list
    return {"error": "listDeveloperWebhooks: the route answered neither a list nor an object"}


async def get_proposal_detail(auth: MCPAuthContext, proposal_id: int) -> Dict[str, Any]:
    """Get governance proposal detail by id."""
    if proposal_id is None:
        return {"error": "proposal_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/governance/proposals/{int(proposal_id)}")


async def get_proposal_votes(auth: MCPAuthContext, proposal_id: int) -> Dict[str, Any]:
    """List all votes cast on a governance proposal.

    Returns {votes: [...], total: N}.
    """
    if proposal_id is None:
        return {"error": "proposal_id is required"}
    body = await _dev_request(auth, "GET", f"/api/v1/governance/proposals/{int(proposal_id)}/votes")
    if isinstance(body, list):
        return {"votes": body, "total": len(body)}
    if isinstance(body, dict):
        if "votes" in body:
            body.setdefault("total", len(body.get("votes") or []))
            return body
        return body  # §MCPTEST30 (V0548): the failure as it came; it used to read as an empty list
    return {"error": "getProposalVotes: the route answered neither a list nor an object"}


async def get_auto_tally_config(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get auto-tally configuration (how proposals are automatically tallied)."""
    return await _dev_request(auth, "GET", "/api/v1/governance/auto-tally/config")


async def federation_propose_raise(auth: MCPAuthContext, proposal_id: int) -> Dict[str, Any]:
    """DESTRUCTIVE: elevate local proposal to federation tier."""
    if proposal_id is None:
        return {"error": "proposal_id is required"}
    # §MCPGOVFIX 2026-09-07 — the body key was `proposal_id`; the route's model is
    # `FederationProposeRequest(local_proposal_id: int, …)` (governance.py:764) and
    # reads `body.local_proposal_id`, so every call answered 422 "Field required"
    # and the tool could never succeed. The ARGUMENT name stays `proposal_id` —
    # that is the caller-facing wire contract and it is not wrong, only the mapping
    # was. Measured by a prior session (EVTYPES2) and re-read from the model here.
    return await _dev_request(auth, "POST", "/api/v1/governance/federation/propose",
                              json_body={"local_proposal_id": int(proposal_id)})


async def federation_veto_proposal(auth: MCPAuthContext, proposal_id: str, reason: str) -> Dict[str, Any]:
    """HIGHLY DESTRUCTIVE: commander-only veto on a federation proposal."""
    if proposal_id is None or not reason:
        return {"error": "proposal_id and reason are required"}
    # §MCPGOVFIX 2026-09-07 — this took `proposal_id: int` and sent `int(proposal_id)`
    # into a path the EventStore parses as a UUID (measured: 422 uuid_parsing on
    # path.proposal_id), so NO argument could satisfy both and the tool was
    # unreachable. Its own sibling `federationVoteProposal` already takes the UUID as
    # a string — the type was answerable from the code all along.
    return await _dev_request(auth, "POST",
                              f"/api/v1/governance/federation/proposals/{seg(proposal_id)}/veto",
                              json_body={"reason": reason})


async def get_dev_trust_graph(auth: MCPAuthContext, did: str) -> Dict[str, Any]:
    """Get local trust relationships for an agent (graph view)."""
    if not did:
        return {"error": "did is required"}
    return await _dev_request(auth, "GET", f"/api/v1/reputation/{seg(did)}/trust-graph")


async def get_agent_metrics(auth: MCPAuthContext, agent_id: str) -> Dict[str, Any]:
    """Get detailed metrics for an agent (request rate, errors, latency percentiles)."""
    if not agent_id:
        return {"error": "agent_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/agent-metrics/{seg(agent_id)}")


async def agent_builder_generate(auth: MCPAuthContext, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Use the agent builder to generate an agent template from spec."""
    if not isinstance(spec, dict):
        return {"error": "spec must be an object"}
    return await _dev_request(auth, "POST", "/api/v1/agent-builder/generate", json_body=spec, binary_content=True)


# ===========================================================================
# §pass70 Sprint 21 — Tier 3 dev (9 new — fill remaining gaps)
# ===========================================================================

async def list_agent_builder_templates(auth: MCPAuthContext) -> Dict[str, Any]:
    """List agent-builder templates (UI scaffolds for agent creation)."""
    return await _dev_request(auth, "GET", "/api/v1/agent-builder/templates")


async def agent_builder_generate_template(auth: MCPAuthContext, template_spec: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a new agent-builder template from a spec (creates reusable template)."""
    if not isinstance(template_spec, dict):
        return {"error": "template_spec must be an object"}
    return await _dev_request(auth, "POST", "/api/v1/agent-builder/generate-template", json_body=template_spec,
                              binary_content=True)


async def update_my_developer_profile(auth: MCPAuthContext, profile_updates: Dict[str, Any]) -> Dict[str, Any]:
    """DESTRUCTIVE: update your developer profile. Pass only fields you want changed.

    Accepted fields (per backend DeveloperProfileUpdate schema; unknown fields
    are silently dropped by the backend's `extra=ignore` Pydantic policy):
      display_name (NOT "name") · bio · avatar_url · website_url ·
      github_url · twitter_handle · company · timezone ·
      notification_prefs (dict) · profile_visibility ("public"|"private"|"team")

    BUG-FIND-25 ergonomics shim: callers commonly send "name" (matching the
    READ field on DeveloperRead). We rewrite it to "display_name" so the
    update lands instead of silently being dropped.
    """
    if not isinstance(profile_updates, dict):
        return {"error": "profile_updates must be an object"}
    # BUG-FIND-25 normalize: "name" → "display_name"
    if "name" in profile_updates and "display_name" not in profile_updates:
        profile_updates = dict(profile_updates)  # don't mutate caller's dict
        profile_updates["display_name"] = profile_updates.pop("name")
    return await _dev_request(auth, "PUT", "/api/v1/developers/me", json_body=profile_updates)


async def list_developer_webhooks_alt(auth: MCPAuthContext) -> Dict[str, Any]:
    """List your developer webhooks (alt path under /developers/webhooks)."""
    body = await _dev_request(auth, "GET", "/api/v1/developers/webhooks")
    if isinstance(body, list):
        return {"webhooks": body, "total": len(body)}
    return body


async def get_developer_webhook_deliveries_alt(auth: MCPAuthContext, webhook_id: str, limit: int = 50) -> Dict[str, Any]:
    """List webhook deliveries (alt path under /developers/webhooks/{id}/deliveries)."""
    if not webhook_id:
        return {"error": "webhook_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/developers/webhooks/{seg(webhook_id)}/deliveries", params={"limit": min(max(int(limit), 1), 100)})


async def test_developer_webhook_alt(auth: MCPAuthContext, webhook_id: str) -> Dict[str, Any]:
    """Send test event to webhook (alt path under /developers/webhooks/{id}/test)."""
    if not webhook_id:
        return {"error": "webhook_id is required"}
    return await _dev_request(auth, "POST", f"/api/v1/developers/webhooks/{seg(webhook_id)}/test")


async def download_pipeline_template(auth: MCPAuthContext, template_id: str) -> Dict[str, Any]:
    """Download a pipeline template (returns config + manifest)."""
    if not template_id:
        return {"error": "template_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/pipeline-templates/{seg(template_id)}/download")


async def purchase_pipeline_template(auth: MCPAuthContext, template_id: str, buyer_did: str) -> Dict[str, Any]:
    """DESTRUCTIVE: purchase a pipeline template for one of your agents (charges that agent, unlocks the license)."""
    if not template_id or not buyer_did:
        return {"error": "template_id and buyer_did are required"}
    return await _dev_request(auth, "POST", f"/api/v1/pipeline-templates/{seg(template_id)}/purchase", json_body={"buyer_did": buyer_did})


async def create_teg_policies_batch(auth: MCPAuthContext, policies: list) -> Dict[str, Any]:
    """DESTRUCTIVE: create multiple TEG policies in one call. policies is a list of policy objects."""
    if not isinstance(policies, list) or not policies:
        return {"error": "policies (non-empty list) is required"}
    return await _dev_request(auth, "POST", "/api/v1/teg/policies/batch", json_body={"policies": policies})


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

# ── §MCPFIRM (2026-08-28): support-review grants (§CHATDESK C4) + org invitations (§ORGINVITE) ──

async def get_support_review_state(auth: MCPAuthContext, conversation_id: str) -> Dict[str, Any]:
    """Review-grant state on one of YOUR conversations: whether the support desk may read it, for which ticket, until when."""
    if not conversation_id:
        return {"error": "conversation_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/chat/conversations/{seg(conversation_id)}/support-review")


async def grant_support_review(auth: MCPAuthContext, conversation_id: str, ticket_id: int) -> Dict[str, Any]:
    """Grant the support desk READ-ONLY access to one conversation for ONE open ticket (§CHATDESK law: the grant dies with the ticket; every desk read is audited and visible in-thread)."""
    if not conversation_id or ticket_id is None:
        return {"error": "conversation_id and ticket_id are required"}
    return await _dev_request(auth, "POST", f"/api/v1/chat/conversations/{seg(conversation_id)}/support-review",
                              json_body={"ticket_id": int(ticket_id)})


async def revoke_support_review(auth: MCPAuthContext, conversation_id: str, grant_id: str) -> Dict[str, Any]:
    """Withdraw a support-review grant you issued (revoke-never-delete: the audit survives)."""
    if not conversation_id or not grant_id:
        return {"error": "conversation_id and grant_id are required"}
    return await _dev_request(auth, "DELETE", f"/api/v1/chat/conversations/{seg(conversation_id)}/support-review/{seg(grant_id)}")


async def list_organization_invitations(auth: MCPAuthContext, org_id: str) -> Dict[str, Any]:
    """Invitations this organization has sent (owner/admin; §ORGINVITE — the token itself is never in the payload)."""
    if not org_id:
        return {"error": "org_id is required"}
    return await _dev_request(auth, "GET", f"/api/v1/organizations/{seg(org_id)}/invitations")


async def withdraw_organization_invitation(auth: MCPAuthContext, org_id: str, invitation_id: str) -> Dict[str, Any]:
    """Withdraw a pending invitation (frees the address; 409 on an already-accepted one, naming the member-removal route)."""
    if not org_id or not invitation_id:
        return {"error": "org_id and invitation_id are required"}
    return await _dev_request(auth, "DELETE", f"/api/v1/organizations/{seg(org_id)}/invitations/{seg(invitation_id)}")


DEVELOPER_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "theprotocol_getSupportReviewState",
        "description": "Review-grant state on one of your conversations: whether the support desk may read it, for which ticket, until when.",
        "inputSchema": {"type": "object", "properties": {"conversation_id": {"type": "string"}}, "required": ["conversation_id"]}
    },
    {
        "name": "theprotocol_grantSupportReview",
        "description": "Grant the support desk READ-ONLY access to one conversation for ONE open ticket. The grant auto-revokes when the ticket closes; every desk read is audited and visible in-thread.",
        "inputSchema": {"type": "object", "properties": {
            "conversation_id": {"type": "string"},
            "ticket_id": {"type": "integer"}}, "required": ["conversation_id", "ticket_id"]}
    },
    {
        "name": "theprotocol_revokeSupportReview",
        "description": "Withdraw a support-review grant you issued (revoke-never-delete: the audit survives).",
        "inputSchema": {"type": "object", "properties": {
            "conversation_id": {"type": "string"},
            "grant_id": {"type": "string"}}, "required": ["conversation_id", "grant_id"]}
    },
    {
        "name": "theprotocol_listOrganizationInvitations",
        "description": "Invitations this organization has sent, with status and withdraw-ability (owner/admin). The bearer token is never in the payload.",
        "inputSchema": {"type": "object", "properties": {"org_id": {"type": "string"}}, "required": ["org_id"]}
    },
    {
        "name": "theprotocol_withdrawOrganizationInvitation",
        "description": "Withdraw a pending organization invitation: frees the address for a re-invite. 409 on an accepted invitation.",
        "inputSchema": {"type": "object", "properties": {
            "org_id": {"type": "string"},
            "invitation_id": {"type": "string"}}, "required": ["org_id", "invitation_id"]}
    },
    {
        "name": "theprotocol_getMyAgents",
        "description": (
            "List all AI agents registered under your developer account. "
            "Returns each agent's DID, client_id (never the secret), status, name, description, reputation score "
            "and its liquid and locked balance in the frame's units. "
            "Requires developer JWT or API key authentication."
        ),
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_createAgent",
        "description": (
            "Register a new AI agent on TheProtocol. Creates a DID, generates OAuth 2.0 "
            "credentials (client_id + client_secret), and sets up the Agent Card. "
            "The client_secret is shown ONCE: store it immediately. "
            "Requires developer JWT authentication."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Agent display name (max 100 chars)"},
                "description": {"type": "string", "description": "Description of the agent's purpose and capabilities"},
                "capabilities": {"type": "array", "items": {"type": "string"}, "description": "Optional list of capability tags", "default": []}
            },
            "required": ["name", "description"]
        }
    },
    {
        "name": "theprotocol_submitDispute",
        "description": ((
            "File a dispute against an agent in the name of the calling agent (the agent the JWT names); the result "
            "names that agent as the complainant. An administrator reviews the dispute and rules. Requires agent JWT "
            "authentication."
        )),
        "inputSchema": {
            "type": "object",
            "properties": {
                "complainant_did": {"type": "string", "description": "Not used: a dispute is always filed as the calling agent. Accepted so that older callers are not refused; the result says when it named another DID"},
                "defendant_did": {"type": "string", "description": "DID of the accused agent"},
                "description": {"type": "string", "description": "Optional: the grievance in your words. The dispute itself has no description field, so it is recorded as the dispute's first evidence"},
                "evidence": {"type": "object", "description": "Optional additional evidence data, recorded with the description", "default": {}}
            },
            "required": ["defendant_did"]
        }
    },
    {
        "name": "theprotocol_createProposal",
        "description": (
            "Create a new governance proposal in the Agent Senate. "
            "IMPORTANT: Requires an agent JWT (not a developer JWT): call getAgentToken first, then pass the "
            "result as agent_jwt. Where the registry counts votes by membership (the public network), the "
            "agent's developer must be a member; elsewhere the agent needs locked units (at least the frame's "
            "minimum). A policy_change proposal needs a policy_diff, which this tool does not send: such a "
            "call is refused (400)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short proposal title (max 200 chars)"},
                "description": {"type": "string", "description": "Detailed description of the proposal"},
                "duration_days": {"type": "integer", "description": "Voting duration in days (1–30, default 7)", "default": 7, "minimum": 1, "maximum": 30},
                "proposal_type": {"type": "string", "description": "'standard' or 'policy_change'", "default": "standard", "enum": ["standard", "policy_change"]},
                "agent_jwt": {"type": "string", "description": "Agent JWT from getAgentToken. REQUIRED."}
            },
            "required": ["title", "description", "agent_jwt"]
        }
    },
    # ─── §pass70 Sprint 2 Wave 2 ─────────────────────────────────────────
    {
        "name": "theprotocol_getMyDeveloperProfile",
        "description": "Get your developer account profile (id, email, admin/treasury/support flags, verification status, created_at).",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getMyApiKeys",
        "description": "List your developer API keys (id, prefix, description, last_used_at, active status). Plain key values are NOT returned (hashed at rest).",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_createApiKey",
        "description": (
            "Generate a new developer API key for programmatic access. "
            "The plain key value (avreg_...) is returned ONCE: store it immediately; it cannot be retrieved again."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "key_name": {"type": "string", "description": "Descriptive name for this key (e.g. 'CI/CD bot', 'MCP bridge')"}
            },
            "required": ["key_name"]
        }
    },
    {
        "name": "theprotocol_getMyOrganizations",
        "description": "List organizations this developer is a member of. Returns id, name, slug, owner_id, website per org.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getMyAgentBundles",
        "description": "List your agent bundles (signed .tpb archives for snapshot/template/migration modes). Paginated.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max results (default 20, max 100)", "default": 20},
                "offset": {"type": "integer", "description": "Pagination offset", "default": 0}
            }
        }
    },
    # ─── §pass70 Sprint 3 Wave 4 (Tier 3 developer) ──────────────────────
    {
        "name": "theprotocol_submitSupportTicket",
        "description": (
            "File a support ticket. Categories: bug | question | feature | account | general. "
            "Priorities: low | normal | high | urgent. Requires developer JWT."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Short subject line (1-200 chars)"},
                "message": {"type": "string", "description": "Body of the ticket"},
                "category": {"type": "string", "default": "general", "enum": ["bug", "question", "feature", "account", "general"]},
                "priority": {"type": "string", "default": "normal", "enum": ["low", "normal", "high", "urgent"]}
            },
            "required": ["subject", "message"]
        }
    },
    {
        "name": "theprotocol_getMySupportTickets",
        "description": "List your support tickets. Optional status filter (open/in_progress/resolved/closed).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticket_status": {"type": "string", "enum": ["open", "in_progress", "resolved", "closed"]},
                "limit": {"type": "integer", "default": 20},
                "offset": {"type": "integer", "default": 0}
            }
        }
    },
    {
        "name": "theprotocol_revokeApiKey",
        "description": (
            "Revoke a developer API key by ID. The key becomes inactive immediately. "
            "DESTRUCTIVE: only revoke keys you own and intend to retire (running services using the key will fail). "
            "Use getMyApiKeys to find the key_id first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "key_id": {"type": "integer", "description": "Numeric ID of the API key to revoke (from getMyApiKeys)"}
            },
            "required": ["key_id"]
        }
    },
    {
        "name": "theprotocol_getMyDisputes",
        "description": "List disputes (developer-tier view). Optional filters: status, defendant_did, complainant_did.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dispute_status": {"type": "string", "description": "Status filter (e.g. 'open', 'resolved')"},
                "defendant_did": {"type": "string"},
                "complainant_did": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
                "offset": {"type": "integer", "default": 0}
            }
        }
    },
    # ─── §pass70 Sprint 4 (Tier 3 — 12 new) ───────────────────────────────
    {
        "name": "theprotocol_getMyWebhooks",
        "description": "List your registered webhook subscriptions.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_createWebhook",
        "description": "Register a new webhook subscription. Events fired on listed event types POST to your URL. Use getSupportedWebhookEvents for valid types.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Receiver endpoint URL (must accept POST + signature header)"},
                "events": {"type": "array", "items": {"type": "string"}, "description": "Event type list, e.g. ['agent.created', 'agent.updated']"},
                "description": {"type": "string", "description": "Optional human-readable description"}
            },
            "required": ["url", "events"]
        }
    },
    {
        "name": "theprotocol_getWebhook",
        "description": "Get details for a single webhook subscription.",
        "inputSchema": {"type": "object", "properties": {"webhook_id": {"type": "string"}}, "required": ["webhook_id"]}
    },
    {
        "name": "theprotocol_updateWebhook",
        "description": "Update fields on an existing webhook. Only supplied fields change.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "webhook_id": {"type": "string"},
                "url": {"type": "string"},
                "events": {"type": "array", "items": {"type": "string"}},
                "description": {"type": "string"},
                "is_active": {"type": "boolean"}
            },
            "required": ["webhook_id"]
        }
    },
    {
        "name": "theprotocol_deleteWebhook",
        "description": "Delete a webhook subscription. Future events will not fire to it.",
        "inputSchema": {"type": "object", "properties": {"webhook_id": {"type": "string"}}, "required": ["webhook_id"]}
    },
    {
        "name": "theprotocol_getWebhookDeliveries",
        "description": "Get recent delivery attempts (success + retry history) for a webhook.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "webhook_id": {"type": "string"},
                "limit": {"maximum": 100, "minimum": 1, "type": "integer", "default": 50}
            },
            "required": ["webhook_id"]
        }
    },
    {
        "name": "theprotocol_testWebhook",
        "description": "Fire a test event to the webhook URL: verifies your receiver is reachable and accepts the signatures.",
        "inputSchema": {"type": "object", "properties": {"webhook_id": {"type": "string"}}, "required": ["webhook_id"]}
    },
    {
        "name": "theprotocol_getSupportedWebhookEvents",
        "description": "List all event types you can subscribe to via createWebhook (42+ types).",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getDeveloperStats",
        "description": "Aggregate stats for your developer account (agents, income, activity).",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getMyCicdPipelines",
        "description": "List CI/CD pipelines for one of your agents.",
        "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}
    },
    {
        "name": "theprotocol_getMyCicdVersions",
        "description": "List code versions deployed for one of your agents.",
        "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}
    },
    {
        "name": "theprotocol_getMyCicdDeployments",
        "description": "List deployment history for one of your agents.",
        "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}
    },
    # ─── §pass70 Sprint 5 (Tier 3) ────────────────────────────────────────
    {
        "name": "theprotocol_getMyMcpAuditLog",
        "description": "Get your own MCP tool-call audit log, newest first, paged by cursor (the id of the previous page's last row). Requires developer JWT or API key.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
                "cursor": {"type": "string", "description": "the id of the last row of the previous page"}
            }
        }
    },
    {
        "name": "theprotocol_getMyDeletionStatus",
        "description": "Check your account deletion state: deletion_status, requested_at, anonymizes_at, cooling_off_days. Returns nulls if no deletion request open.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getMyAchievements",
        "description": "List the achievements your developer account has reached, each with its payout in the frame's units (`payout_avt`) and payout status. Returns achievements[], total, total_payout, pending_count.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getMyUnreadNotifications",
        "description": "List broadcast notifications you haven't read yet. Returns {unread:[{id,title,body,broadcast_type,created_at}], total}.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_markNotificationRead",
        "description": "Mark a broadcast notification as read/dismissed by your developer account.",
        "inputSchema": {
            "type": "object",
            "properties": {"broadcast_id": {"type": "string"}},
            "required": ["broadcast_id"]
        }
    },
    {
        "name": "theprotocol_getOrganization",
        "description": "Get a single organization by id (name, slug, owner_id, description, website, counts).",
        "inputSchema": {
            "type": "object",
            "properties": {"org_id": {"type": "string"}},
            "required": ["org_id"]
        }
    },
    {
        "name": "theprotocol_listOrganizationMembers",
        "description": "List members of an organization with their roles. Returns {members:[{id, developer_id, developer_name, role, joined_at}], total}.",
        "inputSchema": {
            "type": "object",
            "properties": {"org_id": {"type": "string"}},
            "required": ["org_id"]
        }
    },
    {
        "name": "theprotocol_getFeaturedBundles",
        "description": "List Bundle marketplace featured entries (templates/snapshots). Returns {featured:[...]}. Works with developer JWT or unauth.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    # ─── §pass70 Sprint 6 (Tier 3) ────────────────────────────────────────
    {
        "name": "theprotocol_listMyAttestations",
        "description": "List the ZKP attestations stored on this registry: every agent's, not only your own (attestations are public). Optional filters: agent_did (any agent), circuit_id. Paginated with limit and offset; count is the total. Requires developer JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_did": {"type": "string"},
                "circuit_id": {"type": "string"},
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
                "offset": {"type": "integer", "default": 0, "minimum": 0}
            }
        }
    },
    {
        "name": "theprotocol_getAttestationDetail",
        "description": "Get a single attestation by id: circuit_id and version, agent_did, public_inputs, proof_hash (sha256 of the proof bytes), verified and failure_reason, its times and revocation fields. Requires developer JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {"attestation_id": {"type": "string"}},
            "required": ["attestation_id"]
        }
    },
    {
        "name": "theprotocol_getAttestationBundle",
        "description": "Get the registry-signed bundle of an attestation (proof_b64, proof_hash, public_inputs, verified, revoked, valid_until, Ed25519 signature) for offline checks: the signature with getAttestationSigningPubkey, the proof with bb verify against the circuit's verification key (/api/v1/circuits/{id}/vk).",
        "inputSchema": {
            "type": "object",
            "properties": {"attestation_id": {"type": "string"}},
            "required": ["attestation_id"]
        }
    },
    {
        "name": "theprotocol_getTrustScore",
        "description": "An agent's EigenTrust trust score from the latest computation: did, global_trust, similarity_score, integer_projection, epoch and computed_at. 404 while no computation has scored the agent. Requires developer JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {"agent_did": {"type": "string"}},
            "required": ["agent_did"]
        }
    },
    {
        "name": "theprotocol_getVolumeProfile",
        "description": "Transaction volume profile for an agent: total_volume, unique_peers, avg_per_peer, volume_rank.",
        "inputSchema": {
            "type": "object",
            "properties": {"agent_did": {"type": "string"}},
            "required": ["agent_did"]
        }
    },
    {
        "name": "theprotocol_getCrossFrameReputation",
        "description": "Cross-frame reputation scores (foreign-frame agents seen by this registry). Returns {foreign_reputation, agent_count, status}.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getReputationComputationStatus",
        "description": "EigenTrust++ computation status: epoch, computed_at, agents_computed, computation_time_ms, last_epoch_converged.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    # ─── §pass70 Sprint 7 (Tier 3 — 10 new — org/team CRUD) ───────────────
    {
        "name": "theprotocol_createOrganization",
        "description": "Create a new organization under your developer account. Returns the new org with auto-generated slug + id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "website": {"type": "string"},
                "logo_url": {"type": "string"},
                "settings": {"type": "object"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "theprotocol_updateOrganization",
        "description": "Update fields on an organization (name/description/website/logo_url/settings). Pass only the fields you want changed. Owner only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org_id": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "website": {"type": "string"},
                "logo_url": {"type": "string"},
                "settings": {"type": "object"}
            },
            "required": ["org_id"]
        }
    },
    {
        "name": "theprotocol_deleteOrganization",
        "description": "Delete an organization (owner only, irreversible). Cascades to teams + memberships + agent assignments.",
        "inputSchema": {
            "type": "object",
            "properties": {"org_id": {"type": "string"}},
            "required": ["org_id"]
        }
    },
    {
        "name": "theprotocol_inviteOrganizationMember",
        "description": "Invite a developer (by email) to an organization. Role defaults to 'member'. Returns invite token + URL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org_id": {"type": "string"},
                "email": {"type": "string"},
                "role": {"type": "string", "default": "member"}
            },
            "required": ["org_id", "email"]
        }
    },
    {
        "name": "theprotocol_listOrganizationTeams",
        "description": "List all teams under an organization. Returns {teams:[], total}.",
        "inputSchema": {
            "type": "object",
            "properties": {"org_id": {"type": "string"}},
            "required": ["org_id"]
        }
    },
    {
        "name": "theprotocol_createOrganizationTeam",
        "description": "Create a new team within an organization. permissions is a list of permission names (e.g. read_agents).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org_id": {"type": "string"},
                "name": {"type": "string", "minLength": 3, "maxLength": 255},
                "description": {"type": "string", "maxLength": 1000},
                "permissions": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["org_id", "name"]
        }
    },
    {
        "name": "theprotocol_getOrganizationTeam",
        "description": "Get a single team by id within an organization (name, description, permissions, member_count).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org_id": {"type": "string"},
                "team_id": {"type": "string"}
            },
            "required": ["org_id", "team_id"]
        }
    },
    {
        "name": "theprotocol_addTeamMember",
        "description": "Add a developer to a team. developer_id is the integer id (from listOrganizationMembers). Role defaults to 'member'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org_id": {"type": "string"},
                "team_id": {"type": "string"},
                "developer_id": {"type": "integer"},
                "role": {"type": "string", "default": "member"}
            },
            "required": ["org_id", "team_id", "developer_id"]
        }
    },
    {
        "name": "theprotocol_assignAgentToOrg",
        "description": "Assign one of your agents (by DID) to an organization. The agent must already be owned by you.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org_id": {"type": "string"},
                "agent_did": {"type": "string"}
            },
            "required": ["org_id", "agent_did"]
        }
    },
    {
        "name": "theprotocol_getOrganizationBySlug",
        "description": "Look up an organization by its slug (human-readable identifier from listOrganizations).",
        "inputSchema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"]
        }
    },
    {
        "name": "theprotocol_getDisputeById",
        "description": "Get a single dispute by id (full record with status, ruling, parties, evidence). Requires developer JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {"dispute_id": {"type": "string"}},
            "required": ["dispute_id"]
        }
    },
    # ─── §pass70 Sprint 8 (Tier 3 — 14 new) ───────────────────────────────
    {
        "name": "theprotocol_getFeeCurrentRate",
        "description": "Current fleet-wide transaction fee rate (base + max + velocity-adjusted). Requires developer JWT.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_requestAccountDeletion",
        "description": "WARNING: starts the deletion timer for your developer account. Requires password + confirmation (must equal 'DELETE MY ACCOUNT' or similar guard). Optional reason. Use cancelAccountDeletion to abort within cooling-off window.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "password": {"type": "string"},
                "confirmation": {"type": "string", "description": "Confirmation guard string (e.g. 'DELETE MY ACCOUNT')"},
                "reason": {"type": "string"}
            },
            "required": ["password", "confirmation"]
        }
    },
    {
        "name": "theprotocol_cancelAccountDeletion",
        "description": "Cancel a pending account deletion (must be within cooling-off window). No body required.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_claimPendingAchievements",
        "description": "Pay all your pending achievement payouts, in the frame's units, to the agent you name (agent_did). The payouts go to that agent as given: name one of your own agents.",
        "inputSchema": {
            "type": "object",
            "properties": {"agent_did": {"type": "string"}},
            "required": ["agent_did"]
        }
    },
    {
        "name": "theprotocol_recordAchievement",
        "description": "Record an achievement event (typically called by an agent's own pipeline). achievement_type must be from the achievement catalog.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "achievement_type": {"type": "string"},
                "agent_did": {"type": "string"},
                "metadata": {"type": "object"}
            },
            "required": ["achievement_type"]
        }
    },
    {
        "name": "theprotocol_listOrganizationAgents",
        "description": "List all agents assigned to an organization. Returns {organization_id, team_id?, agents:[], count}.",
        "inputSchema": {
            "type": "object",
            "properties": {"org_id": {"type": "string"}},
            "required": ["org_id"]
        }
    },
    {
        "name": "theprotocol_getOrganizationCicdSummary",
        "description": "Aggregate CI/CD activity for an organization (agent count, pipelines total, deployments_24h).",
        "inputSchema": {
            "type": "object",
            "properties": {"org_id": {"type": "string"}},
            "required": ["org_id"]
        }
    },
    {
        "name": "theprotocol_removeOrganizationMember",
        "description": "Remove a developer from an organization (owner only). developer_id is the integer id from listOrganizationMembers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org_id": {"type": "string"},
                "developer_id": {"type": "integer"}
            },
            "required": ["org_id", "developer_id"]
        }
    },
    {
        "name": "theprotocol_updateOrganizationTeam",
        "description": "Update fields on a team (name/description/permissions). Pass only the fields you want changed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org_id": {"type": "string"},
                "team_id": {"type": "string"},
                "name": {"type": "string", "minLength": 3, "maxLength": 255},
                "description": {"type": "string", "maxLength": 1000},
                "permissions": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["org_id", "team_id"]
        }
    },
    {
        "name": "theprotocol_deleteOrganizationTeam",
        "description": "Delete a team within an organization (owner only). Cascades to team memberships.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org_id": {"type": "string"},
                "team_id": {"type": "string"}
            },
            "required": ["org_id", "team_id"]
        }
    },
    {
        "name": "theprotocol_removeTeamMember",
        "description": "Remove a developer from a team within an organization. developer_id is the integer id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org_id": {"type": "string"},
                "team_id": {"type": "string"},
                "developer_id": {"type": "integer"}
            },
            "required": ["org_id", "team_id", "developer_id"]
        }
    },
    {
        "name": "theprotocol_unassignAgentFromOrg",
        "description": "Unassign an agent (by DID) from an organization. Inverse of assignAgentToOrg.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org_id": {"type": "string"},
                "agent_did": {"type": "string"}
            },
            "required": ["org_id", "agent_did"]
        }
    },
    {
        "name": "theprotocol_getPayoutRelockForAgent",
        "description": "Get the auto-compound setting of an agent by DID (any agent DID; the developer-tier variant of getMyPayoutRelock). Returns {enabled}.",
        "inputSchema": {
            "type": "object",
            "properties": {"agent_did": {"type": "string"}},
            "required": ["agent_did"]
        }
    },
    # ─── §pass70 Sprint 9 (Tier 3 — 12 new) ───────────────────────────────
    {
        "name": "theprotocol_getMyAgentCicdStats",
        "description": "CI/CD stats for one of your agents (pipeline_count, deployment_count, last_deploy_at).",
        "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}
    },
    {
        "name": "theprotocol_getMyAgentLogs",
        "description": "Get agent logs (pipeline/deployment output) for one of your agents. Paginated.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_did": {"type": "string"},
                "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
                "offset": {"type": "integer", "default": 0, "minimum": 0}
            },
            "required": ["agent_did"]
        }
    },
    {
        "name": "theprotocol_listAgentTemplates",
        "description": "List agent templates (starter scaffolds) registered on this registry.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getAgentTemplate",
        "description": "Get a single agent template by id (full manifest + acceptance criteria).",
        "inputSchema": {"type": "object", "properties": {"template_id": {"type": "string"}}, "required": ["template_id"]}
    },
    {
        "name": "theprotocol_getMyDeveloperActivity",
        "description": "Your developer-account activity stream (recent registry/agent events) over the last `days`.",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500}, "days": {"type": "integer", "default": 30, "minimum": 1, "maximum": 365}}}
    },
    {
        "name": "theprotocol_getMyDeveloperTegSummary",
        "description": "Totals across your agents from this registry's balance cache: liquid, locked and total balance in the frame's units (with the currency), average reputation, agent count and active agent count.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getMyTreasuryBalance",
        "description": "The balance of this registry's system treasury, in the frame's units, with any further detail the TEG reports. It is the registry's treasury, not your account: every developer reads the same figure.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getMyNotificationPrefs",
        "description": "Get your notification preferences (email_on/off per broadcast type, webhook digest cadence).",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getNotificationCatalog",
        "description": "The notification type catalog, filtered to your audience (it drives the settings matrix).",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getMyNotificationMatrix",
        "description": "Your full effective notification matrix (catalog defaults, wildcard, your rows and legacy keys).",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_updateNotificationPrefs",
        "description": "DESTRUCTIVE: bulk sparse upsert of notification preferences (per type x channel; reset=true reverts a row to catalog default).",
        "inputSchema": {"type": "object", "properties": {"rows": {"type": "array", "items": {"type": "object", "properties": {"type_key": {"type": "string"}, "channel": {"type": "string", "enum": ["inapp", "email", "push_desktop", "push_mobile"]}, "enabled": {"type": "boolean"}, "threshold_num": {"type": "number"}, "reset": {"type": "boolean"}}, "required": ["type_key", "channel"]}}}, "required": ["rows"]}
    },
    {
        "name": "theprotocol_getMySigningKeys",
        "description": "List your developer Ed25519 signing keys.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getMyFlareStatus",
        "description": "Get your full flare state (the tier reached + unlocked sets + active selection).",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getMyFiatPurchases",
        "description": "Your fiat on-ramp purchase history (Stripe or Mollie checkouts), where a registry runs the on-ramp. The on-ramp is a switch per registry (`fiat_onramp_enabled`), off on the public network, where this answers 403 or 503.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getMy2FAStatus",
        "description": "Get current 2FA (TOTP) status for your developer account.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    # ─── §pass70 Sprint 10 (Tier 3 — 13 new: CI/CD mutations) ─────────────
    {"name": "theprotocol_createPipeline", "description": "Create a CI/CD pipeline on one of your agents. pipeline_config is free-form; trigger_type enum (push/webhook/manual).", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "pipeline_name": {"type": "string"}, "pipeline_config": {"type": "object"}, "trigger_type": {"type": "string"}, "webhook_url": {"type": "string"}, "is_active": {"type": "boolean"}, "environment_vars": {"type": "object"}}, "required": ["agent_did", "pipeline_name", "pipeline_config"]}},
    {"name": "theprotocol_updatePipeline", "description": "Update fields on an existing pipeline.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "pipeline_id": {"type": "string"}, "pipeline_name": {"type": "string"}, "pipeline_config": {"type": "object"}, "is_active": {"type": "boolean"}}, "required": ["agent_did", "pipeline_id"]}},
    {"name": "theprotocol_deletePipeline", "description": "Delete a pipeline from one of your agents.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "pipeline_id": {"type": "string"}}, "required": ["agent_did", "pipeline_id"]}},
    {"name": "theprotocol_createVersion", "description": "Create a new code version for an agent. version is semver string.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "version": {"type": "string"}, "commit_hash": {"type": "string"}, "release_notes": {"type": "string"}, "is_stable": {"type": "boolean"}}, "required": ["agent_did", "version"]}},
    {"name": "theprotocol_deleteVersion", "description": "Delete a version from an agent.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "version_id": {"type": "string"}}, "required": ["agent_did", "version_id"]}},
    {"name": "theprotocol_activateVersion", "description": "Activate a version (make it canonical).", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "version_id": {"type": "string"}}, "required": ["agent_did", "version_id"]}},
    {"name": "theprotocol_rollbackVersion", "description": "Roll back to a specific version. May trigger redeploy.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "version_id": {"type": "string"}}, "required": ["agent_did", "version_id"]}},
    {"name": "theprotocol_triggerDeployment", "description": "Trigger deployment of one of your agents. environment enum.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "environment": {"type": "string"}, "pipeline_id": {"type": "string"}, "version_id": {"type": "string"}}, "required": ["agent_did", "environment"]}},
    {"name": "theprotocol_getDeployment", "description": "Get a single deployment record by id.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "deployment_id": {"type": "string"}}, "required": ["agent_did", "deployment_id"]}},
    {"name": "theprotocol_appendDeploymentLogs", "description": "Append log lines to a deployment (CI runner).", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "deployment_id": {"type": "string"}, "logs": {"type": "string"}}, "required": ["agent_did", "deployment_id", "logs"]}},
    {"name": "theprotocol_updateDeploymentStatus", "description": "Update deployment status (pending/running/success/failed/cancelled).", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "deployment_id": {"type": "string"}, "status": {"type": "string"}, "error_message": {"type": "string"}, "metadata": {"type": "object"}}, "required": ["agent_did", "deployment_id", "status"]}},
    {"name": "theprotocol_cloneAgent", "description": "Clone an agent. Optional new_name.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "new_name": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_deleteMyAgent", "description": "DESTRUCTIVE: delete the calling agent (self-delete via /agents/me).", "inputSchema": {"type": "object", "properties": {}}},
    # Re-tiered from Sprint 10 Tier 2:
    {"name": "theprotocol_exportAgentDev", "description": "Export an agent's configuration (snapshot: card, settings). Owner-only. Requires developer JWT.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_updateMyDeveloperLocation", "description": "Update authenticated developer's location for globe visualization. location_data MUST include `latitude` and `longitude` (decimal degrees). Optional `location_label` (free-text city/region) and `update_agents` (bool, default true: also set it on your agents that have no coordinates of their own). Requires developer JWT.", "inputSchema": {"type": "object", "properties": {"location_data": {"type": "object", "properties": {"latitude": {"type": "number"}, "longitude": {"type": "number"}, "location_label": {"type": "string"}, "update_agents": {"type": "boolean"}}, "required": ["latitude", "longitude"]}}, "required": ["location_data"]}},
    # ─── §pass70 Sprint 11 (Tier 3 — 7 new) ───────────────────────────────
    {"name": "theprotocol_getTransactionsAnalytics", "description": "Aggregate transaction analytics for your dev account.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAgentPayoutHistory", "description": "Lifetime history of an agent's payouts on locked units as the TEG reports it (any agent DID). Requires developer JWT.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_getAgentPendingPayouts", "description": "Pending payouts on locked units of an agent as the TEG reports them (any agent DID). Requires developer JWT.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_getAgentLockedBalance", "description": "Locked balance of an agent as the TEG reports it (any agent DID). Requires developer JWT.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_getAgentLockHistory", "description": "Lock and release history of an agent as the TEG reports it (any agent DID). Requires developer JWT.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_listTegPolicies", "description": "List active TEG governance/compliance policies.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getTegPoliciesComplianceDashboard", "description": "TEG policy compliance dashboard.", "inputSchema": {"type": "object", "properties": {}}},
    # ─── §pass70 Sprint 12 (Tier 3 — 15 new: federation + auth + bundle) ──
    {"name": "theprotocol_listFederationPeers", "description": "List federation peers from your dev's perspective.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getMyFederationRegistrations", "description": "List the federation peer registrations created by your dev account.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_triggerFederationSync", "description": "Trigger an on-demand federation sync cycle.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getFederationSyncStatusDev", "description": "Federation sync status (dev view).", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_rotateFederationLicenseSelf", "description": "DESTRUCTIVE: rotate the federation license you present (forces all peers to re-handshake). Use only when it is compromised. Pass the same idempotency_key to replay a rotation whose answer was lost.", "inputSchema": {"type": "object", "properties": {"federation_license_key": {"type": "string"}, "reason": {"type": "string", "enum": ["leak_suspected", "post_incident", "scheduled_rotation"]}, "idempotency_key": {"type": "string"}}, "required": ["federation_license_key", "reason"]}},
    {"name": "theprotocol_logoutSession", "description": "DESTRUCTIVE: log out current session (revokes JWT).", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAuthProfile", "description": "Full auth profile for current user (id, email, is_admin, granular flags).", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_setup2FA", "description": "Initialize 2FA (TOTP) setup. Requires your password. Call verify2FA next to complete.", "inputSchema": {"type": "object", "properties": {"password": {"type": "string"}}, "required": ["password"]}},
    {"name": "theprotocol_verify2FA", "description": "Complete 2FA setup with TOTP code.", "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
    {"name": "theprotocol_disable2FASelf", "description": "DESTRUCTIVE: disable your own 2FA. Requires your password and a current code: a 6-digit authenticator code or an unused backup code (XXXX-XXXX).", "inputSchema": {"type": "object", "properties": {"password": {"type": "string"}, "code": {"type": "string", "pattern": "^(?:[0-9]{6}|[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{4})$"}}, "required": ["password", "code"]}},
    {"name": "theprotocol_changePassword", "description": "DESTRUCTIVE: change account password.", "inputSchema": {"type": "object", "properties": {"current_password": {"type": "string"}, "new_password": {"type": "string"}}, "required": ["current_password", "new_password"]}},
    {"name": "theprotocol_getBundleManifest", "description": "Get a bundle's manifest.", "inputSchema": {"type": "object", "properties": {"bundle_id": {"type": "string"}}, "required": ["bundle_id"]}},
    {"name": "theprotocol_rateBundle", "description": "Rate a bundle (1-5 stars) with optional comment.", "inputSchema": {"type": "object", "properties": {"bundle_id": {"type": "string"}, "rating": {"type": "integer", "minimum": 1, "maximum": 5}, "comment": {"type": "string"}}, "required": ["bundle_id", "rating"]}},
    {"name": "theprotocol_reportBundle", "description": "Report a bundle (admin moderation queue). reason enum (spam/malware/copyright/other).", "inputSchema": {"type": "object", "properties": {"bundle_id": {"type": "string"}, "reason": {"type": "string"}, "details": {"type": "string"}}, "required": ["bundle_id", "reason"]}},
    {"name": "theprotocol_forkBundle", "description": "Fork a bundle (own copy).", "inputSchema": {"type": "object", "properties": {"bundle_id": {"type": "string"}, "new_name": {"type": "string"}}, "required": ["bundle_id"]}},
    {"name": "theprotocol_deleteBundle", "description": "DESTRUCTIVE: delete one of your bundles. Owner-only.", "inputSchema": {"type": "object", "properties": {"bundle_id": {"type": "string"}}, "required": ["bundle_id"]}},
    # ─── §pass70 Sprint 13 (Tier 3 — 12 new: TEG mutations + federation peer mutations + frame inv) ──
    {"name": "theprotocol_getTegTransactionDetail", "description": "Full TEG transaction detail by id.", "inputSchema": {"type": "object", "properties": {"transaction_id": {"type": "string"}}, "required": ["transaction_id"]}},
    {"name": "theprotocol_getAgentTransactionHistory", "description": "TEG-side transaction history for one of your agents (a treasury administrator: any account).", "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}, "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500}}, "required": ["agent_id"]}},
    {"name": "theprotocol_exportTegTransactions", "description": "Export TEG transactions (CSV/JSON).", "inputSchema": {"type": "object", "properties": {"fmt": {"type": "string", "enum": ["json","csv"], "default": "json"}}}},
    {"name": "theprotocol_createTegPolicy", "description": "DESTRUCTIVE: create a TEG policy. Requires admin_treasury flag.", "inputSchema": {"type": "object", "properties": {"policy_code": {"type": "string"}, "policy_name": {"type": "string"}, "policy_type": {"type": "string"}, "description": {"type": "string"}, "parameters": {"type": "object"}, "enforcement_level": {"type": "string"}}, "required": ["policy_code", "policy_name", "policy_type"]}},
    {"name": "theprotocol_updateTegPolicy", "description": "DESTRUCTIVE: update a TEG policy.", "inputSchema": {"type": "object", "properties": {"policy_id": {"type": "string"}, "updates": {"type": "object"}}, "required": ["policy_id", "updates"]}},
    {"name": "theprotocol_deleteTegPolicy", "description": "DESTRUCTIVE: delete a TEG policy.", "inputSchema": {"type": "object", "properties": {"policy_id": {"type": "string"}}, "required": ["policy_id"]}},
    {"name": "theprotocol_getTegPolicy", "description": "Get one TEG policy by id.", "inputSchema": {"type": "object", "properties": {"policy_id": {"type": "string"}}, "required": ["policy_id"]}},
    {"name": "theprotocol_resolveTegDispute", "description": "Resolve a TEG dispute: the registry refuses it for every caller (403; who may resolve a TEG dispute through the registry is undecided). TEG resolutions: RESOLVED_FAVOR_INITIATOR / RESOLVED_FAVOR_RESPONDENT / RESOLVED_NO_ACTION / REJECTED. Agent JWT.", "inputSchema": {"type": "object", "properties": {"dispute_id": {"type": "string"}, "resolution": {"type": "string"}, "resolution_details": {"type": "string"}, "penalty_amount": {"type": "number"}, "agent_jwt": {"type": "string"}}, "required": ["dispute_id", "resolution"]}},
    {"name": "theprotocol_getTegDisputeDetail", "description": "TEG dispute full record by id.", "inputSchema": {"type": "object", "properties": {"dispute_log_id": {"type": "string"}}, "required": ["dispute_log_id"]}},
    {"name": "theprotocol_getAgentReputation", "description": "EigenTrust reputation for any agent by TEG agent_id.", "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}}, "required": ["agent_id"]}},
    {"name": "theprotocol_createFrameInvitation", "description": "DESTRUCTIVE: initiate cross-frame federation handshake. Sovereign-mainframe-only.", "inputSchema": {"type": "object", "properties": {"trust_domain": {"type": "string"}, "bundle_endpoint_url": {"type": "string"}, "federation_endpoint_url": {"type": "string"}, "name": {"type": "string"}, "contact_email": {"type": "string"}, "initiator_nonce": {"type": "string"}, "event_store_url": {"type": "string"}, "description": {"type": "string"}}, "required": ["trust_domain","bundle_endpoint_url","federation_endpoint_url","name","contact_email","initiator_nonce"]}},
    {"name": "theprotocol_finalizeFrameInvitation", "description": "DESTRUCTIVE: finalize frame invitation (complete cross-frame federation handshake) with the approver's trust domain, bundle endpoint, name, bundle PEM and the nonce it echoes.", "inputSchema": {"type": "object", "properties": {"invitation_id": {"type": "string"}, "approver_trust_domain": {"type": "string", "minLength": 3, "maxLength": 255}, "approver_bundle_endpoint_url": {"type": "string", "minLength": 8, "maxLength": 500}, "approver_name": {"type": "string", "minLength": 1, "maxLength": 255}, "approver_bundle_pem": {"type": "string", "minLength": 16}, "nonce_echo": {"type": "string", "pattern": "^[a-fA-F0-9]{16,64}$"}, "approver_federation_endpoint_url": {"type": "string", "maxLength": 500}}, "required": ["invitation_id", "approver_trust_domain", "approver_bundle_endpoint_url", "approver_name", "approver_bundle_pem", "nonce_echo"]}},
    # ─── §pass70 Sprint 14 (Tier 3 — 15 new: federation slash + peer mgmt + onboard + utils) ──
    {"name": "theprotocol_validateAgentCard", "description": "Validate an Agent Card against canonical schema. Returns {valid, errors[]}.", "inputSchema": {"type": "object", "properties": {"card": {"type": "object"}}, "required": ["card"]}},
    {"name": "theprotocol_downloadBundleViaOnboard", "description": "Download an operator bundle via onboarding flow.", "inputSchema": {"type": "object", "properties": {"bundle_data": {"type": "object"}}, "required": ["bundle_data"]}},
    {"name": "theprotocol_resetAgentCredentialsOnboard", "description": "DESTRUCTIVE: reset agent OAuth credentials (new client_secret shown ONCE). Requires your password; totp_code or challenge_id when 2FA asks for them.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "password": {"type": "string"}, "totp_code": {"type": "string", "maxLength": 16}, "challenge_id": {"type": "string", "maxLength": 44}}, "required": ["agent_did", "password"]}},
    {"name": "theprotocol_getFederationDisputeSettlements", "description": "List cross-frame dispute settlements (federation adjudication queue), newest first; the route serves the 100 newest and the window is taken from those.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500}, "offset": {"type": "integer", "default": 0, "minimum": 0}, "status_filter": {"type": "string"}}}},
    {"name": "theprotocol_getFederationDisputeSettlement", "description": "Get a single federation dispute settlement.", "inputSchema": {"type": "object", "properties": {"settlement_id": {"type": "string"}}, "required": ["settlement_id"]}},
    {"name": "theprotocol_approveDisputeSettlement", "description": "DESTRUCTIVE: approve cross-frame dispute settlement (triggers cross-frame slash).", "inputSchema": {"type": "object", "properties": {"settlement_id": {"type": "string"}}, "required": ["settlement_id"]}},
    {"name": "theprotocol_rejectDisputeSettlement", "description": "Reject cross-frame dispute settlement.", "inputSchema": {"type": "object", "properties": {"settlement_id": {"type": "string"}}, "required": ["settlement_id"]}},
    {"name": "theprotocol_getPeerSlashConfig", "description": "Per-peer slash configuration (max amounts, callbacks, TTL).", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_updatePeerSlashConfig", "description": "DESTRUCTIVE: update peer slash configuration.", "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}, "config": {"type": "object"}}, "required": ["peer_id", "config"]}},
    {"name": "theprotocol_getFederationPeerByID", "description": "Get federation peer detail by id.", "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}}, "required": ["peer_id"]}},
    {"name": "theprotocol_updateFederationPeer", "description": "DESTRUCTIVE: update federation peer registration.", "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}, "updates": {"type": "object"}}, "required": ["peer_id", "updates"]}},
    {"name": "theprotocol_deleteFederationPeerSelf", "description": "DESTRUCTIVE: delete a federation peer registration (own peer).", "inputSchema": {"type": "object", "properties": {"peer_id": {"type": "string"}}, "required": ["peer_id"]}},
    {"name": "theprotocol_createFederationPeer", "description": "DESTRUCTIVE: create federation peer registration (initiates handshake).", "inputSchema": {"type": "object", "properties": {"peer_data": {"type": "object"}}, "required": ["peer_data"]}},
    {"name": "theprotocol_federationSlashRequest", "description": "DESTRUCTIVE (peer-to-peer): receive a slash request from a peer.", "inputSchema": {"type": "object", "properties": {"settlement_id": {"type": "string"}, "dispute_id": {"type": "integer"}, "ruling": {"type": "string"}, "amount": {"type": "integer"}, "complainant_did": {"type": "string"}, "defendant_did": {"type": "string"}, "origin_registry_url": {"type": "string"}, "callback_url": {"type": "string"}}, "required": ["settlement_id","dispute_id","ruling","amount","complainant_did","defendant_did","origin_registry_url","callback_url"]}},
    {"name": "theprotocol_federationSlashConfirmation", "description": "Submit slash confirmation back to originating peer (federation peer-to-peer).", "inputSchema": {"type": "object", "properties": {"settlement_id": {"type": "string"}, "status": {"type": "string"}, "amount": {"type": "integer"}, "slash_event_id": {"type": "string"}, "slash_tx_id": {"type": "string"}, "error_message": {"type": "string"}}, "required": ["settlement_id", "status", "amount"]}},
    # ─── §pass70 Sprint 15 (Tier 3 — 12 new: flare mgmt + attestation admin previews) ──
    {"name": "theprotocol_setFlareCornerVariant", "description": "Set corner-badge variant on one of your agents.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "variant": {"type": "string"}}, "required": ["agent_did", "variant"]}},
    {"name": "theprotocol_setFlareOverlay", "description": "Set broken-machine overlay variant on one of your agents.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "overlay": {"type": "string"}}, "required": ["agent_did", "overlay"]}},
    {"name": "theprotocol_setFlareVariant", "description": "Set encirclement variant on one of your agents.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "variant": {"type": "string"}}, "required": ["agent_did", "variant"]}},
    {"name": "theprotocol_flareCelebrationAcknowledge", "description": "Acknowledge the Shadow Chancellor upgrade modal (one-shot).", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_customizeFlare", "description": "Customize the caller's flare (display name, tagline, logo, link).", "inputSchema": {"type": "object", "properties": {"customizations": {"type": "object"}}, "required": ["customizations"]}},
    {"name": "theprotocol_equipFlare", "description": "Equip a flare slot (corner|encirclement) on one of your agents.", "inputSchema": {"type": "object", "properties": {"slot": {"type": "string", "enum": ["corner","encirclement"]}, "agent_did": {"type": "string"}, "variant": {"type": "string"}}, "required": ["slot", "agent_did"]}},
    {"name": "theprotocol_moveFlare", "description": "Move the caller's agent flare to one of their agents.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_selectFlare", "description": "Switch which flare(s) the caller is wearing.", "inputSchema": {"type": "object", "properties": {"selection": {"type": "object"}}, "required": ["selection"]}},
    {"name": "theprotocol_unequipFlare", "description": "Unequip a single flare slot from one of your agents.", "inputSchema": {"type": "object", "properties": {"slot": {"type": "string", "enum": ["corner","encirclement"]}, "agent_did": {"type": "string"}}, "required": ["slot", "agent_did"]}},
    {"name": "theprotocol_previewSlashReductionAttestation", "description": "Preview, without applying it, the slash reduction a dispute would get from the attestations it references. A sandbox debug route: a registry that is not a sandbox answers 403. Requires developer JWT.", "inputSchema": {"type": "object", "properties": {"dispute_id": {"type": "string"}}, "required": ["dispute_id"]}},
    {"name": "theprotocol_previewVotingPowerAttestation", "description": "Preview the governance attestation bonus for an agent (sandbox registries only): verified, unrevoked attestations counted as distinct (circuit, UTC day) pairs over the window, the threshold, bonus_eligible and the multiplier (x1.05 at 10 in 30 days by default). Several proofs of one circuit on one day count once.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_mcpPassthroughGetAgentProfile", "description": "MCP passthrough wrapper for getAgentProfile (via attestation admin).", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    # ─── §pass70 Sprint 16 (Tier 3 — 10 new) ──────────────────────────────
    {"name": "theprotocol_getLockPayoutRecords", "description": "Per-agent records of one payout on locked units: {records, total}.", "inputSchema": {"type": "object", "properties": {"distribution_id": {"type": "string"}}, "required": ["distribution_id"]}},
    {"name": "theprotocol_updatePayoutRelock", "description": "Turn the relock of payouts on locked units on or off for one of your agents (each payout is locked again as it comes). A payout on locked units is a switch per registry (`staking_rewards_enabled`), off on the public network, where this answers 403.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "enabled": {"type": "boolean"}}, "required": ["agent_did", "enabled"]}},
    {"name": "theprotocol_triggerLockPayoutRun", "description": "DESTRUCTIVE: run the payout on locked units now. Administrators only, and only where the payout switch (`staking_rewards_enabled`) is on: it is off on the public network, where this answers 403.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_downloadBundle", "description": "Download bundle artifact.", "inputSchema": {"type": "object", "properties": {"bundle_id": {"type": "string"}}, "required": ["bundle_id"]}},
    {"name": "theprotocol_restoreBundle", "description": "DESTRUCTIVE: restore (re-apply) a snapshot bundle to your account state.", "inputSchema": {"type": "object", "properties": {"bundle_id": {"type": "string"}, "conflict_resolution": {"type": "string", "enum": ["rename", "skip", "overwrite"]}, "mode": {"type": "string", "enum": ["copy", "mirror"]}, "include_cicd": {"type": "boolean"}}, "required": ["bundle_id"]}},
    {"name": "theprotocol_restoreFromUpload", "description": "DESTRUCTIVE: restore from an uploaded bundle file (e.g. exported from another registry); bundle_b64 is the file in base64.", "inputSchema": {"type": "object", "properties": {"bundle_b64": {"type": "string"}, "filename": {"type": "string", "default": "bundle.zip"}, "conflict_resolution": {"type": "string", "enum": ["rename", "skip", "overwrite"]}, "mode": {"type": "string", "enum": ["copy", "mirror"]}, "include_cicd": {"type": "boolean"}}, "required": ["bundle_b64"]}},
    {"name": "theprotocol_patchBundle", "description": "DESTRUCTIVE: update fields on one of your bundles.", "inputSchema": {"type": "object", "properties": {"bundle_id": {"type": "string"}, "updates": {"type": "object"}}, "required": ["bundle_id", "updates"]}},
    {"name": "theprotocol_createBundle", "description": "DESTRUCTIVE: create new bundle (snapshot/template/migration).", "inputSchema": {"type": "object", "properties": {"bundle_data": {"type": "object"}}, "required": ["bundle_data"]}},
    {"name": "theprotocol_previewAdminEmailWithContext", "description": "Preview admin email template with custom context.", "inputSchema": {"type": "object", "properties": {"template": {"type": "string"}, "context": {"type": "object"}}, "required": ["template", "context"]}},
    {"name": "theprotocol_previewAdminEmailText", "description": "Preview plain-text variant of admin email template.", "inputSchema": {"type": "object", "properties": {"template": {"type": "string"}}, "required": ["template"]}},
    # ─── §pass70 Sprint 17 (Tier 3 — 12 new) ──────────────────────────────
    {"name": "theprotocol_rotateMySigningKey", "description": "DESTRUCTIVE: rotate your developer Ed25519 signing key (7d grace).", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getMyApiKeyDetail", "description": "Detail for one of your API keys.", "inputSchema": {"type": "object", "properties": {"key_id": {"type": "string"}}, "required": ["key_id"]}},
    {"name": "theprotocol_deleteMyApiKey", "description": "DESTRUCTIVE: deactivate one of your API keys.", "inputSchema": {"type": "object", "properties": {"key_id": {"type": "string"}}, "required": ["key_id"]}},
    {"name": "theprotocol_getBatchAgentBalances", "description": "Batch get balances for multiple of your agents.", "inputSchema": {"type": "object", "properties": {"agent_dids": {"type": "array", "items": {"type": "string"}}}, "required": ["agent_dids"]}},
    {"name": "theprotocol_getMyAgentBalance", "description": "Get balance for one of your agents.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_deleteMyAgentByDev", "description": "HIGHLY DESTRUCTIVE: delete one of your agents from dev account.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_getOperatorMyStatus", "description": "Your operator status (own cloud-op registry).", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getOperatorMyBundle", "description": "Download your operator bundle.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getOperatorMyLifecycle", "description": "Your operator's full lifecycle stack.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_activateOperator", "description": "DESTRUCTIVE: activate your operator with the activation code from its approval (approved -> active).", "inputSchema": {"type": "object", "properties": {"activation_code": {"type": "string", "minLength": 10, "maxLength": 100}}, "required": ["activation_code"]}},
    {"name": "theprotocol_requestFrame", "description": "DESTRUCTIVE: submit sovereign-frame request (Commander reviews). request_data.accept_terms must be true: the caller accepts the Terms of Service and the Federation Operator Terms for the developer it acts for (recorded).", "inputSchema": {"type": "object", "properties": {"request_data": {"type": "object"}}, "required": ["request_data"]}},
    {"name": "theprotocol_selfProvisionOperator", "description": "HIGHLY DESTRUCTIVE: self-service cloud-op provisioning (flare-gated: requires the Architect tier or above). Spins up real infra. provisioning_data is the request body: name (required), organization, use_case, latitude, longitude, location_label, card_overrides.", "inputSchema": {"type": "object", "properties": {"provisioning_data": {"type": "object"}}, "required": ["provisioning_data"]}},
    # ─── §pass70 Sprint 18 (Tier 3 — 7 new) ───────────────────────────────
    {"name": "theprotocol_importAgent", "description": "DESTRUCTIVE: import an agent from its export (creates the agent). Requires developer JWT. agent_config is the export JSON (or a body already carrying export_data).", "inputSchema": {"type": "object", "properties": {"agent_config": {"type": "object"}, "options": {"type": "object"}}, "required": ["agent_config"]}},
    {"name": "theprotocol_validateAgentImport", "description": "Validate an agent export for import without creating anything (dry run). agent_config is the export JSON (or a body already carrying export_data).", "inputSchema": {"type": "object", "properties": {"agent_config": {"type": "object"}, "options": {"type": "object"}}, "required": ["agent_config"]}},
    {"name": "theprotocol_agentBulkExport", "description": "Bulk-export agents (signed export bundles). Owner-only.", "inputSchema": {"type": "object", "properties": {"agent_dids": {"type": "array", "items": {"type": "string"}}}, "required": ["agent_dids"]}},
    {"name": "theprotocol_authRefresh", "description": "Refresh access token via refresh token.", "inputSchema": {"type": "object", "properties": {"refresh_token": {"type": "string"}}, "required": ["refresh_token"]}},
    {"name": "theprotocol_regenerateBackupCodes", "description": "DESTRUCTIVE: regenerate 2FA backup codes (invalidates old ones). Requires your password and a current 6-digit TOTP code.", "inputSchema": {"type": "object", "properties": {"password": {"type": "string"}, "current_code": {"type": "string", "pattern": "^[0-9]{6}$"}}, "required": ["password", "current_code"]}},
    {"name": "theprotocol_operatorPortalSelfLogs", "description": "Cloud-op admin self-logs.", "inputSchema": {"type": "object", "properties": {"lines": {"type": "integer", "default": 100}}}},
    {"name": "theprotocol_operatorPortalSelfRestart", "description": "DESTRUCTIVE: cloud-op admin self-restart.", "inputSchema": {"type": "object", "properties": {"service": {"type": "string"}}}},
    # ─── §pass70 Sprint 19 (Tier 3 — 8 new) ───────────────────────────────
    {"name": "theprotocol_getMyDeveloperJwks", "description": "Get JWKS for a developer (verify signing-key payloads).", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}}, "required": ["developer_id"]}},
    {"name": "theprotocol_getOAuthFederationStatus", "description": "OAuth federation status (cross-registry trust mesh).", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_oauthIntrospect", "description": "OAuth 2.0 token introspection (RFC 7662) for an exchanged federation token. Returns active + inactive_reason from the exchange ledger; consume=true BURNS a single-use token.", "inputSchema": {"type": "object", "properties": {"token": {"type": "string"}, "client_id": {"type": "string"}, "client_secret": {"type": "string"}, "consume": {"type": "boolean"}, "amount": {"type": "string"}}, "required": ["token", "client_id", "client_secret"]}},
    {"name": "theprotocol_oauthRevoke", "description": "Revoke an exchanged OAuth federation token (RFC 7009). Pass token or jti. Always 200.", "inputSchema": {"type": "object", "properties": {"client_id": {"type": "string"}, "client_secret": {"type": "string"}, "token": {"type": "string"}, "jti": {"type": "string"}, "reason": {"type": "string"}}, "required": ["client_id", "client_secret"]}},
    {"name": "theprotocol_oauthFederationTrustList", "description": "List OAuth federation trust entries (admin). Client secrets are never returned.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_oauthTokenExchange", "description": "OAuth 2.0 token exchange (RFC 8693) against a trusted peer registry. The subject token is verified against the peer's JWKS.", "inputSchema": {"type": "object", "properties": {"subject_token": {"type": "string"}, "subject_token_type": {"type": "string"}, "client_id": {"type": "string"}, "client_secret": {"type": "string"}, "audience": {"type": "string"}, "scope": {"type": "string"}}, "required": ["subject_token", "subject_token_type", "client_id", "client_secret"]}},
    {"name": "theprotocol_acceptOrgInvitation", "description": "Accept an organization invitation via emailed token.", "inputSchema": {"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]}},
    {"name": "theprotocol_getSupportTicketDetail", "description": "Detail for one of your support tickets.", "inputSchema": {"type": "object", "properties": {"ticket_id": {"type": "string"}}, "required": ["ticket_id"]}},
    {"name": "theprotocol_replySupportTicket", "description": "Reply to a support ticket.", "inputSchema": {"type": "object", "properties": {"ticket_id": {"type": "string"}, "message": {"type": "string"}}, "required": ["ticket_id", "message"]}},
    {"name": "theprotocol_requestSelfRevocation", "description": "DESTRUCTIVE: request self-revocation of operator credentials (initiates revoke workflow). The route requires a reason.", "inputSchema": {"type": "object", "properties": {"reason": {"type": "string", "minLength": 1, "maxLength": 1000}}, "required": ["reason"]}},
    # ─── §pass70 Sprint 20 (Tier 3 — 12 new) ──────────────────────────────
    {"name": "theprotocol_getMyDeveloperActivityEventstore", "description": "Your developer EventStore activity (richer per-developer events).", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}}}},
    {"name": "theprotocol_listDeveloperApikeysMe", "description": "List API keys for your dev account via /developers/me path.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_createDeveloperApikeyMe", "description": "DESTRUCTIVE: create API key (alt path).", "inputSchema": {"type": "object", "properties": {"description": {"type": "string"}}, "required": ["description"]}},
    {"name": "theprotocol_listDeveloperWebhooks", "description": "List developer webhooks (alt path).", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getProposalDetail", "description": "Governance proposal detail by id.", "inputSchema": {"type": "object", "properties": {"proposal_id": {"type": "integer"}}, "required": ["proposal_id"]}},
    {"name": "theprotocol_getProposalVotes", "description": "List all votes cast on a proposal.", "inputSchema": {"type": "object", "properties": {"proposal_id": {"type": "integer"}}, "required": ["proposal_id"]}},
    {"name": "theprotocol_getAutoTallyConfig", "description": "Auto-tally configuration.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_federationProposeRaise", "description": "DESTRUCTIVE: elevate local proposal to federation tier.", "inputSchema": {"type": "object", "properties": {"proposal_id": {"type": "integer"}}, "required": ["proposal_id"]}},
    # §MCPGOVFIX 2026-09-07 — proposal_id was advertised as an integer; federation
    # proposal ids are UUIDs (the ES path parses one, and federationVoteProposal
    # below already declares a string). An integer could not address any real
    # proposal, so this schema described a tool that could not be called.
    {"name": "theprotocol_federationVetoProposal", "description": "HIGHLY DESTRUCTIVE: commander-only veto on federation proposal.", "inputSchema": {"type": "object", "properties": {"proposal_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["proposal_id", "reason"]}},
    {"name": "theprotocol_getDevTrustGraph", "description": "Local trust relationships for an agent (graph).", "inputSchema": {"type": "object", "properties": {"did": {"type": "string"}}, "required": ["did"]}},
    {"name": "theprotocol_getAgentMetrics", "description": "Detailed metrics for an agent.", "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}}, "required": ["agent_id"]}},
    {"name": "theprotocol_agentBuilderGenerate", "description": "Use agent builder to generate agent template.", "inputSchema": {"type": "object", "properties": {"spec": {"type": "object"}}, "required": ["spec"]}},
    # ─── §pass70 Sprint 21 (Tier 3 — 9 new: fill remaining gaps) ──────────
    {"name": "theprotocol_listAgentBuilderTemplates", "description": "List agent-builder templates (UI scaffolds).", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_agentBuilderGenerateTemplate", "description": "Generate a new agent-builder template from spec.", "inputSchema": {"type": "object", "properties": {"template_spec": {"type": "object"}}, "required": ["template_spec"]}},
    {"name": "theprotocol_updateMyDeveloperProfile", "description": "DESTRUCTIVE: update developer profile fields.", "inputSchema": {"type": "object", "properties": {"profile_updates": {"type": "object"}}, "required": ["profile_updates"]}},
    {"name": "theprotocol_listDeveloperWebhooksAlt", "description": "List developer webhooks (alt path).", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getDeveloperWebhookDeliveriesAlt", "description": "List webhook deliveries (alt path).", "inputSchema": {"type": "object", "properties": {"webhook_id": {"type": "string"}, "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 100}}, "required": ["webhook_id"]}},
    {"name": "theprotocol_testDeveloperWebhookAlt", "description": "Send test event to webhook (alt path).", "inputSchema": {"type": "object", "properties": {"webhook_id": {"type": "string"}}, "required": ["webhook_id"]}},
    {"name": "theprotocol_downloadPipelineTemplate", "description": "Download a pipeline template (config + manifest).", "inputSchema": {"type": "object", "properties": {"template_id": {"type": "string"}}, "required": ["template_id"]}},
    {"name": "theprotocol_purchasePipelineTemplate", "description": "DESTRUCTIVE: purchase a pipeline template for one of your agents (buyer_did pays).", "inputSchema": {"type": "object", "properties": {"template_id": {"type": "string"}, "buyer_did": {"type": "string"}}, "required": ["template_id", "buyer_did"]}},
    {"name": "theprotocol_createTegPoliciesBatch", "description": "DESTRUCTIVE: create multiple TEG policies in one call.", "inputSchema": {"type": "object", "properties": {"policies": {"type": "array", "items": {"type": "object"}}}, "required": ["policies"]}}
]


# ═══════════════════════════════════════════════════════════════════════
# AGORA exchange — Tier 3 developer tools (2026-06-12)
# ═══════════════════════════════════════════════════════════════════════

async def create_exchange_listing(
    auth: MCPAuthContext,
    organization_id: str,
    symbol: str,
    total_shares: int,
    ipo_float: int,
    ipo_price: str,
    funding_agent_did: str,
    display_name: str = "",
) -> Dict[str, Any]:
    """List your organization on AGORA (org OWNER). Creates the org treasury
    agent + charges the listing fee from funding_agent_did. Awaits admin approval."""
    body: Dict[str, Any] = {
        "organization_id": organization_id,
        "symbol": symbol,
        "total_shares": int(total_shares),
        "ipo_float": int(ipo_float),
        "ipo_price": str(ipo_price),
        "funding_agent_did": funding_agent_did,
    }
    if display_name:
        body["display_name"] = display_name[:255]
    return await _dev_request(auth, "POST", "/api/v1/agora/listings", json_body=body)


async def declare_exchange_dividend(auth: MCPAuthContext, listing: str, per_share: str) -> Dict[str, Any]:
    """Declare a distribution on your org's listing (org admin): per_share (the amount per point) × holdings
    at snapshot, paid from the org treasury agent via the venue escrow."""
    return await _dev_request(
        auth, "POST", f"/api/v1/agora/listings/{seg(listing)}/distributions", json_body={"per_share": str(per_share)}
    )


DEVELOPER_TOOL_SCHEMAS.extend([
    {"name": "theprotocol_createAgoraListing", "description": "DESTRUCTIVE: list your organization on the AGORA market (org OWNER; charges the listing fee in frame currency from one of your agents; creates the org treasury agent). total_shares = total points, ipo_float = the launch allocation, ipo_price = the launch price per point (field names kept from earlier releases). Requires developer JWT.", "inputSchema": {"type": "object", "properties": {"organization_id": {"type": "string"}, "symbol": {"type": "string", "description": "ticker, ^[A-Z0-9]{2,6}$"}, "total_shares": {"type": "integer", "minimum": 1}, "ipo_float": {"type": "integer", "minimum": 0}, "ipo_price": {"type": "string", "description": "launch price per point, decimal string"}, "funding_agent_did": {"type": "string", "description": "your agent that pays the listing fee"}, "display_name": {"type": "string"}}, "required": ["organization_id", "symbol", "total_shares", "ipo_float", "ipo_price", "funding_agent_did"]}},
    {"name": "theprotocol_declareAgoraDistribution", "description": "DESTRUCTIVE: declare a distribution on your org's AGORA listing (org admin; pays from the org treasury agent pro-rata to holders). (Old name declareExchangeDividend still works.)", "inputSchema": {"type": "object", "properties": {"listing": {"type": "string", "description": "listing id or ticker"}, "per_share": {"type": "string", "description": "amount per point, decimal string"}}, "required": ["listing", "per_share"]}},
])
