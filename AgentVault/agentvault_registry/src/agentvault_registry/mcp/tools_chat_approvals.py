"""MCP tools: approvals in the chat (V0650 (l), 2026-10-31, agentvault2-14; routers/chat.py, services/chat_approvals.py).

    requestChatApproval       agent JWT: ask the org's owner for a decision, in the agent's org room
    getChatApprovalStatus     agent JWT or developer key: one request, its decision and the proof; wait_seconds holds
                              the answer up to 20 seconds while it is pending (the fastest way for a session to learn
                              the decision)
    decideChatApproval        developer key or JWT: approve or deny one request, several, or every pending one (the
                              org's owner or a named approver; an agent context is refused)

A refusal carries its reason INSIDE `error` (the dispatcher renders a result carrying `error` as `Error: <error>` and
drops every other key, §BATCH3). A decision that waits for a phone confirmation answers `status: step_up_required`
WITHOUT an `error` key, so the challenge reaches the caller (castVote's rule).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .auth_bridge import MCPAuthContext, format_tool_exception, mcp_forwarded_headers, require_agent_auth, \
    require_developer_auth
from .auth_bridge import mcp_http_client  # D6-514: every client to this registry carries the MCP relay proof
from .refusal import refusal_reason
from .tools_agent import REGISTRY_SELF_URL
from ..core.path_segment import seg

logger = logging.getLogger(__name__)
_TIMEOUT = 15.0
WAIT_MAX_S = 20

_AGENT_JWT = {"type": "string", "description": "Optional: the asking agent's JWT (getAgentToken), when this "
                                               "connection holds a developer key"}


async def _call(method: str, path: str, *, token: str, params: Optional[dict] = None, body: Optional[dict] = None,
                timeout: float = _TIMEOUT) -> Tuple[Optional[httpx.Response], Optional[Dict[str, Any]]]:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}", **mcp_forwarded_headers()}
    try:
        async with mcp_http_client(timeout=timeout) as client:
            r = await client.request(method, f"{REGISTRY_SELF_URL}{path}", params=params, json=body, headers=headers)
        return r, None
    except httpx.TimeoutException:
        return None, {"error": f"{method} {path} timed out"}
    except Exception as e:  # noqa: BLE001 — every failure reaches the caller as a sentence
        logger.error("chat approvals %s %s error: %s", method, path, e, exc_info=True)
        return None, {"error": format_tool_exception(e)}


def _answer(r: httpx.Response, op: str) -> Dict[str, Any]:
    if r.status_code in (200, 201):
        try:
            data = r.json()
        except ValueError:
            return {"error": f"{op} returned HTTP {r.status_code}: the registry's answer was not JSON"}
        return data if isinstance(data, dict) else {"items": data}
    return {"error": f"{op} returned HTTP {r.status_code}: {refusal_reason(r)}"}


def _token(auth: MCPAuthContext) -> Optional[Dict[str, Any]]:
    if auth.auth_type == "anonymous" or not auth.raw_token:
        return {"error": "This tool requires authentication (an agent JWT or a developer key)."}
    return None


async def request_chat_approval(auth: MCPAuthContext, conversation_id: str, title: str, client_ref: str,
                                reason: str = "", unlocks: str = "", expires_in_seconds: int = 3600,
                                artifact_sha256: str = "", artifact_label: str = "",
                                production_impact: bool = False) -> Dict[str, Any]:
    """Ask the organization's owner (or a named approver) to approve something, in the org's room. The request shows
    pinned above the room's history with Approve and Deny; the decision arrives as an approval.decided card, on
    /chat/sync, and through getChatApprovalStatus. A repeat client_ref returns the original request (agent JWT)."""
    require_agent_auth(auth)
    if (miss := _token(auth)):
        return miss
    if not conversation_id or not title or not client_ref:
        return {"error": "conversation_id, title and client_ref are required"}
    body: Dict[str, Any] = {"client_ref": str(client_ref), "title": str(title),
                            "expires_in_seconds": int(expires_in_seconds or 3600),
                            "production_impact": bool(production_impact)}
    for k, v in (("reason", reason), ("unlocks", unlocks), ("artifact_sha256", artifact_sha256),
                 ("artifact_label", artifact_label)):
        if v:
            body[k] = str(v)
    r, err = await _call("POST", f"/api/v1/chat/conversations/{seg(conversation_id)}/approvals",
                         token=auth.raw_token, body=body)
    return err or _answer(r, "requestChatApproval")


async def get_chat_approval_status(auth: MCPAuthContext, approval_id: str, wait_seconds: int = 0) -> Dict[str, Any]:
    """One approval request: its status (pending, approved, denied, expired), and once decided who decided, when, in
    which role, how, the presence proof when one was asked for, and the registry's signed statement. wait_seconds
    (0 to 20) holds the answer while it is pending. Any member of the room may read it (agent JWT or developer key)."""
    if (miss := _token(auth)):
        return miss
    if not approval_id:
        return {"error": "approval_id is required"}
    try:
        w = max(0, min(WAIT_MAX_S, int(wait_seconds or 0)))
    except (TypeError, ValueError):
        return {"error": f"wait_seconds must be a whole number from 0 to {WAIT_MAX_S}"}
    r, err = await _call("GET", f"/api/v1/chat/approvals/{seg(approval_id)}", token=auth.raw_token,
                         params={"wait": w}, timeout=w + 10.0)
    return err or _answer(r, "getChatApprovalStatus")


async def decide_chat_approval(auth: MCPAuthContext, conversation_id: str, decision: str,
                               approval_ids: Optional[List[str]] = None, note: str = "",
                               challenge_id: str = "") -> Dict[str, Any]:
    """Approve or deny approval requests in an org room: the ids given, or with none given every request pending
    there now (read first, so the registry always decides an explicit set). The org's owner or a named approver only;
    an agent context is refused. Where the room asks for a phone confirmation the answer is status step_up_required
    with a challenge: approve it in Pocket, Approvals, then call again with challenge_id (developer key or JWT)."""
    require_developer_auth(auth)
    if (miss := _token(auth)):
        return miss
    if decision not in ("approve", "deny"):
        return {"error": "decision must be approve or deny"}
    if not conversation_id:
        return {"error": "conversation_id is required"}
    ids = [str(i) for i in (approval_ids or []) if str(i).strip()]
    if not ids:
        r, err = await _call("GET", f"/api/v1/chat/conversations/{seg(conversation_id)}/approvals",
                             token=auth.raw_token, params={"status": "pending", "limit": 50})
        if err:
            return err
        listing = _answer(r, "decideChatApproval")
        if "error" in listing:
            return listing
        ids = [i["id"] for i in listing.get("items") or [] if i.get("status") == "pending"]
        if not ids:
            return {"decision": decision, "decided": [], "skipped": {}, "note": "nothing is pending in this room"}
    body: Dict[str, Any] = {"decision": decision, "approval_ids": ids[:50], "surface": "mcp"}
    if note:
        body["note"] = str(note)[:500]
    if challenge_id:
        body["challenge_id"] = str(challenge_id)[:44]
    r, err = await _call("POST", f"/api/v1/chat/conversations/{seg(conversation_id)}/approvals/decide",
                         token=auth.raw_token, body=body)
    if err:
        return err
    if r.status_code == 428:
        try:
            pending = r.json()
        except ValueError:
            pending = None
        if isinstance(pending, dict) and pending.get("error") == "step_up_required":
            return {
                "status": "step_up_required",
                "message": pending.get("message") or "Confirm this decision on your phone.",
                "step_up": pending.get("step_up"),
                "next": ("Approve the challenge in Pocket, Approvals, then call decideChatApproval again with the "
                         "same conversation_id, decision and approval_ids plus challenge_id."),
            }
    return _answer(r, "decideChatApproval")


_CONV = {"type": "string", "description": "The organization room's conversation id"}

CHAT_APPROVAL_AGENT_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "theprotocol_requestChatApproval",
        "description": ("Ask your organization's owner (or a named approver) for a decision, in the org's room: what "
                        "you ask, why, what it unlocks, how long it stays open. It shows pinned above the room's "
                        "history with Approve and Deny; the decision arrives as a card, on /chat/sync and through "
                        "getChatApprovalStatus. A repeat client_ref returns the original request. Agent JWT."),
        "inputSchema": {"type": "object", "properties": {
            "conversation_id": _CONV,
            "title": {"type": "string", "description": "What is asked, in one line (1 to 200 characters)"},
            "client_ref": {"type": "string", "description": "Your idempotency key (8 to 64 characters)"},
            "reason": {"type": "string", "description": "Why (up to 2000 characters)", "default": ""},
            "unlocks": {"type": "string", "description": "The action an approval unlocks", "default": ""},
            "expires_in_seconds": {"type": "integer", "description": "60 s to 7 days (default 3600)",
                                   "default": 3600},
            "artifact_sha256": {"type": "string", "description": "sha256 of the artifact the approval is about; the "
                                                                 "decision repeats it", "default": ""},
            "artifact_label": {"type": "string", "description": "A human name for that artifact", "default": ""},
            "production_impact": {"type": "boolean", "description": "The action touches production (you declare "
                                                                    "it; a room may ask for a phone confirmation)",
                                  "default": False},
            "agent_jwt": _AGENT_JWT,
        }, "required": ["conversation_id", "title", "client_ref"]},
    },
    {
        "name": "theprotocol_getChatApprovalStatus",
        "description": ("One approval request: pending, approved, denied or expired; once decided, who decided, when, "
                        "in which role, how (credential kind, MCP relay), the phone proof when one was asked for, and "
                        "the registry's signed statement. wait_seconds (0 to 20) holds the answer while it is "
                        "pending. Any member of the room may read it. Agent JWT or developer key."),
        "inputSchema": {"type": "object", "properties": {
            "approval_id": {"type": "string", "description": "The request's id (apr_...)"},
            "wait_seconds": {"type": "integer", "description": "Wait up to this many seconds while it is pending "
                                                               "(0 to 20)", "default": 0},
            "agent_jwt": _AGENT_JWT,
        }, "required": ["approval_id"]},
    },
]

CHAT_APPROVAL_DEVELOPER_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "theprotocol_decideChatApproval",
        "description": ("Approve or deny approval requests in an organization room: the ids given, or with none given "
                        "every request pending there now. Only pending, unexpired requests are decided; the rest are "
                        "listed in skipped by name. The org's owner or a named approver only; agents never decide. "
                        "Where the room asks for a phone confirmation the answer is status step_up_required with a "
                        "challenge to approve in Pocket, Approvals; call again with challenge_id. Developer key or "
                        "JWT."),
        "inputSchema": {"type": "object", "properties": {
            "conversation_id": _CONV,
            "decision": {"type": "string", "enum": ["approve", "deny"]},
            "approval_ids": {"type": "array", "items": {"type": "string"},
                             "description": "The requests to decide (1 to 50); omit for every pending one"},
            "note": {"type": "string", "description": "Optional: a note kept with the decision", "default": ""},
            "challenge_id": {"type": "string", "description": "Optional: the challenge you approved on your phone "
                                                              "for THIS decision", "default": ""},
        }, "required": ["conversation_id", "decision"]},
    },
]
