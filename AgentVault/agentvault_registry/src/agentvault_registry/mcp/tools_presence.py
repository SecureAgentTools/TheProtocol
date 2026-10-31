"""MCP tools: an agent's status line and an organization's presence (V0650 (a), 2026-10-31, agentvault2-14).

    setMyAgentStatus          agent JWT: one line (1 to 140 characters) that expires on its own (ttl 1 s to a day)
    getOrganizationPresence   agent JWT or developer JWT: the organization's agents, their owners, last activity and
                              live status lines (whoever the organization's room admits)

Both forward whatever token the context holds through the chat tools' helper (tools_agent._chat_request), so a refusal's
sentence reaches the caller inside `error` (the dispatcher drops every other key of a result carrying one).
"""
from __future__ import annotations

from typing import Any, Dict, List

from .auth_bridge import MCPAuthContext, require_agent_auth
from .tools_agent import _chat_request
from ..core.path_segment import seg

_AGENT_JWT = {"type": "string", "description": "Optional: an agent JWT from getAgentToken (speak as that agent)"}


async def set_my_agent_status(auth: MCPAuthContext, text: str, ttl_seconds: int = 3600) -> Dict[str, Any]:
    """Set this agent's status line: what it is doing, in one line that expires after ttl_seconds (agent JWT)."""
    require_agent_auth(auth)
    if not str(text or "").strip():
        return {"error": "text is required: what the agent is doing, in one line (1 to 140 characters)"}
    return await _chat_request(auth, "PUT", "/api/v1/agents/me/status",
                               json_body={"text": str(text), "ttl_seconds": int(ttl_seconds or 3600)},
                               op_name="setMyAgentStatus")


async def get_organization_presence(auth: MCPAuthContext, org_id: str) -> Dict[str, Any]:
    """The organization's agents with their live status lines (a member's or an assigned agent's token)."""
    if not str(org_id or "").strip():
        return {"error": "org_id is required"}
    return await _chat_request(auth, "GET", f"/api/v1/organizations/{seg(org_id)}/presence",
                               op_name="getOrganizationPresence")


PRESENCE_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "theprotocol_setMyAgentStatus",
        "description": ("Set this agent's status line: what it is doing, in one line that expires on its own "
                        "(ttl_seconds, 1 second to a day, an hour by default). A new line replaces the old one. Every "
                        "member and agent of its organization reads it (getOrganizationPresence), so it may carry no "
                        "credential. Agent JWT."),
        "inputSchema": {"type": "object", "properties": {
            "text": {"type": "string", "minLength": 1, "maxLength": 140,
                     "description": "One line, no newline (1 to 140 characters)"},
            "ttl_seconds": {"type": "integer", "minimum": 1, "maximum": 86400, "default": 3600,
                            "description": "How long the line stands"},
            "agent_jwt": _AGENT_JWT,
        }, "required": ["text"]},
    },
    {
        "name": "theprotocol_getOrganizationPresence",
        "description": ("An organization's agents: DID, card name, owner, last activity, account status and live "
                        "status line (null once it expired, and for a suspended agent). For whoever the organization's "
                        "room admits: an active member or an agent assigned to it. Agent JWT or developer JWT."),
        "inputSchema": {"type": "object", "properties": {
            "org_id": {"type": "string", "description": "The organization's id"},
            "agent_jwt": _AGENT_JWT,
        }, "required": ["org_id"]},
    },
]
