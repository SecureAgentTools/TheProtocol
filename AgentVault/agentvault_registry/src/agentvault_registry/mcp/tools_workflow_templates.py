"""MCP tools: the workflow (migration) template library (V0664 "Migrate a system", M4, gwo_e97a483512cfaf2151f17b7a).

    listWorkflowTemplates            public: the public templates (kind, from, to, pricing, q, sort)
    getWorkflowTemplate              public: one template's listing, versions and structure (never its files)
    getWorkflowTemplateVersion       agent JWT: a version with its files (free, the owner or a buyer)
    purchaseWorkflowTemplate         agent JWT: buy a purchase-priced template once
    forkWorkflowTemplate             agent JWT: a private free fork (the right to the files needed)
    instantiateWorkflowTemplate      agent JWT: a V0663 workflow draft from the template's workflow steps
    createWorkflowTemplate           agent JWT: a new template with a draft v1 (its kit's files)
    publishWorkflowTemplateVersion   agent JWT: publish a draft version (immutable after)

Every rule is the registry's (routers/workflow_templates over services/workflow_templates): these forward the call, and a
refusal's sentence reaches the caller inside `error`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from .auth_bridge import MCPAuthContext, format_tool_exception, mcp_http_client, require_agent_auth
from .refusal import refusal_reason
from .tools_agent import _chat_request
from .tools_discovery import REGISTRY_SELF_URL
from ..core.path_segment import seg

logger = logging.getLogger(__name__)
_TIMEOUT = 20.0
_BASE = "/api/v1/workflow-templates"
_AGENT_JWT = {"type": "string", "description": "Optional: an agent JWT from getAgentToken (speak as that agent)"}
_TID = {"type": "string", "description": "The template's id (wtpl_...)"}


async def _public_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        async with mcp_http_client(timeout=_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}{path}", params={k: v for k, v in (params or {}).items()
                                                                         if v not in (None, "")})
    except httpx.TimeoutException:
        return {"error": f"GET {path} timed out"}
    except Exception as e:  # noqa: BLE001: every failure reaches the caller as a sentence
        logger.error("workflow template tool GET %s error: %s", path, e, exc_info=True)
        return {"error": format_tool_exception(e)}
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}
    try:
        return r.json()
    except ValueError:
        return {"error": "HTTP 200: the registry's answer was not JSON"}


async def list_workflow_templates(kind: Optional[str] = None, from_kind: Optional[str] = None,
                                  to_kind: Optional[str] = None, pricing: Optional[str] = None, q: Optional[str] = None,
                                  sort: str = "new", limit: int = 50) -> Dict[str, Any]:
    """The public templates, with their counts (kit downloads, agents that instantiated, certified runs, forks).

    A TIER-1 tool: the dispatcher calls it as `tool_fn(**arguments)`, with no auth context, so it takes none (an `auth` parameter here
    made every call fail with "missing a required argument: 'auth'"). It reads only the public list route."""
    return await _public_get(_BASE, {"kind": kind, "from": from_kind, "to": to_kind, "pricing": pricing, "q": q,
                                     "sort": sort, "limit": limit})


async def get_workflow_template(template_id: str) -> Dict[str, Any]:
    """One template: its listing, its versions index and its structure (never its files). A TIER-1 tool: it takes no auth, as above."""
    if not str(template_id or "").strip():
        return {"error": "template_id is required"}
    return await _public_get(f"{_BASE}/{seg(template_id)}")


async def list_my_workflow_templates(auth: MCPAuthContext) -> Dict[str, Any]:
    """The acting agent's own templates: drafts, unlisted and public, every version, and the buyers of each."""
    return await _chat_request(auth, "GET", f"{_BASE}/mine", op_name="listMyWorkflowTemplates")


async def get_workflow_template_version(auth: MCPAuthContext, template_id: str, version: int) -> Dict[str, Any]:
    """A version with its manifest and files: a free template's for anyone who may see it, a paid one's for the owner
    and buyers (402 otherwise)."""
    if not str(template_id or "").strip():
        return {"error": "template_id is required"}
    return await _chat_request(auth, "GET", f"{_BASE}/{seg(template_id)}/versions/{int(version)}",
                               op_name="getWorkflowTemplateVersion")


async def purchase_workflow_template(auth: MCPAuthContext, template_id: str) -> Dict[str, Any]:
    """Buy a purchase-priced template once (the author is paid through the escrow; a fork's parent author their share)."""
    require_agent_auth(auth)
    return await _chat_request(auth, "POST", f"{_BASE}/{seg(template_id)}/purchase", json_body={},
                               op_name="purchaseWorkflowTemplate")


async def fork_workflow_template(auth: MCPAuthContext, template_id: str, slug: Optional[str] = None,
                                 title: Optional[str] = None) -> Dict[str, Any]:
    """Fork a template you may use (free, yours or bought): a private free copy that names its parent. With no slug the
    registry derives one (the parent's slug and -fork, then -fork-2 ...) and names it in the answer."""
    require_agent_auth(auth)
    body: Dict[str, Any] = {"slug": slug} if slug else {}
    if title:
        body["title"] = title
    return await _chat_request(auth, "POST", f"{_BASE}/{seg(template_id)}/fork", json_body=body,
                               op_name="forkWorkflowTemplate")


async def instantiate_workflow_template(auth: MCPAuthContext, template_id: str, total_budget: Any,
                                        version: Optional[int] = None, title: Optional[str] = None,
                                        currency: Optional[str] = None) -> Dict[str, Any]:
    """Start a V0663 workflow draft from the template's workflow steps (each step's budget is its share of
    total_budget); the workflow carries the template's id, version and content hash. Nothing is posted yet."""
    require_agent_auth(auth)
    body: Dict[str, Any] = {"total_budget": str(total_budget)}
    for k, v in (("version", version), ("title", title), ("currency", currency)):
        if v not in (None, ""):
            body[k] = v
    return await _chat_request(auth, "POST", f"{_BASE}/{seg(template_id)}/instantiate", json_body=body,
                               op_name="instantiateWorkflowTemplate")


async def create_workflow_template(auth: MCPAuthContext, slug: str, title: str, files: Dict[str, str],
                                   summary: Optional[str] = None, visibility: str = "private",
                                   pricing_model: str = "free", price: Any = None, fork_share_bps: Optional[int] = None,
                                   changelog: Optional[str] = None) -> Dict[str, Any]:
    """Create a template with a draft v1 from a kit's files (migration.yaml, proxy.yaml, README.md, samples)."""
    require_agent_auth(auth)
    body: Dict[str, Any] = {"slug": slug, "title": title, "files": files, "visibility": visibility,
                            "pricing_model": pricing_model}
    for k, v in (("summary", summary), ("price", price), ("fork_share_bps", fork_share_bps), ("changelog", changelog)):
        if v not in (None, ""):
            body[k] = v
    return await _chat_request(auth, "POST", _BASE, json_body=body, op_name="createWorkflowTemplate")


async def publish_workflow_template_version(auth: MCPAuthContext, template_id: str, version: int) -> Dict[str, Any]:
    """Publish a draft version: it becomes the template's current version and never changes again."""
    require_agent_auth(auth)
    return await _chat_request(auth, "POST", f"{_BASE}/{seg(template_id)}/versions/{int(version)}/publish",
                               json_body={}, op_name="publishWorkflowTemplateVersion")


WORKFLOW_TEMPLATE_PUBLIC_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "theprotocol_listWorkflowTemplates",
        "description": ("The public workflow templates (migration templates: move a legacy system's data into another, "
                        "with a free dry run on your own machine): from and to, pricing, counts (kit downloads, agents "
                        "that instantiated, certified runs, forks). No auth."),
        "inputSchema": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["migration"], "maxLength": 20},
            "from_kind": {"type": "string", "enum": ["sql", "file", "rest"]},
            "to_kind": {"type": "string", "enum": ["sql", "file", "rest"]},
            "pricing": {"type": "string", "enum": ["free", "purchase"], "maxLength": 12},
            "q": {"type": "string", "maxLength": 80},
            "sort": {"type": "string", "enum": ["new", "uses", "certified"], "default": "new", "maxLength": 12},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
        }},
    },
    {
        "name": "theprotocol_getWorkflowTemplate",
        "description": ("One workflow template: its listing, its versions and its structure (steps, parameter names, "
                        "connector kinds, field counts), never its files. No auth for a public one."),
        "inputSchema": {"type": "object", "properties": {"template_id": _TID}, "required": ["template_id"]},
    },
]

WORKFLOW_TEMPLATE_AGENT_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "theprotocol_getWorkflowTemplateVersion",
        "description": ("A workflow template version with its manifest and files (the kit): a free template's for anyone "
                        "who may see it, a paid one's for its owner and buyers (402 otherwise). Agent JWT."),
        "inputSchema": {"type": "object", "properties": {"template_id": _TID,
                                                          "version": {"type": "integer", "minimum": 1},
                                                          "agent_jwt": _AGENT_JWT},
                        "required": ["template_id", "version"]},
    },
    {
        "name": "theprotocol_purchaseWorkflowTemplate",
        "description": ("Buy a purchase-priced workflow template once: the price goes through the escrow to its author "
                        "(and a fork's parent author their share); a second call answers already. Agent JWT."),
        "inputSchema": {"type": "object", "properties": {"template_id": _TID, "agent_jwt": _AGENT_JWT},
                        "required": ["template_id"]},
    },
    {
        "name": "theprotocol_forkWorkflowTemplate",
        "description": ("Fork a workflow template you may use (free, yours or bought): a private free copy of its current "
                        "version that names its parent; a sale of the fork later pays the parent's author the parent's "
                        "share. Any agent JWT: the fork starts private and free. Without a slug the registry derives one "
                        "(the parent's slug and -fork, then -fork-2 ...) and names it in the answer."),
        "inputSchema": {"type": "object", "properties": {
            "template_id": _TID,
            "slug": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{1,118}$"},
            "title": {"type": "string", "maxLength": 200},
            "agent_jwt": _AGENT_JWT,
        }, "required": ["template_id"]},
    },
    {
        "name": "theprotocol_instantiateWorkflowTemplate",
        "description": ("Start a V0663 workflow draft from a template's workflow steps: each step's budget is its share "
                        "of total_budget, and the workflow carries the template's id, version and content hash. Nothing "
                        "is posted until the workflow is advanced. Agent JWT."),
        "inputSchema": {"type": "object", "properties": {
            "template_id": _TID,
            "total_budget": {"type": ["string", "number"], "description": "The whole workflow's budget, above zero"},
            "version": {"type": "integer", "minimum": 1, "description": "Default: the current published version"},
            "title": {"type": "string", "maxLength": 200},
            "currency": {"type": "string", "maxLength": 12},
            "agent_jwt": _AGENT_JWT,
        }, "required": ["template_id", "total_budget"]},
    },
    {
        "name": "theprotocol_createWorkflowTemplate",
        "description": ("Create a workflow (migration) template with a draft v1 from a kit's files: migration.yaml (schema "
                        "theprotocol.migration/v1), proxy.yaml (credentials as env:NAME or file:/path references only), "
                        "README.md and synthetic samples. Publish it with publishWorkflowTemplateVersion. Any agent JWT "
                        "drafts privately; a visible (public, unlisted, org) or priced template needs a reputation bond "
                        "where this registry enforces bonds."),
        "inputSchema": {"type": "object", "properties": {
            "slug": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{1,118}$"},
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "summary": {"type": "string", "maxLength": 500},
            "files": {"type": "object", "additionalProperties": {"type": "string"},
                      "description": "path to text: at most 64 files, 256 KiB each, 2 MiB in all"},
            "visibility": {"type": "string", "enum": ["private", "org", "unlisted", "public"], "default": "private"},
            "pricing_model": {"type": "string", "enum": ["free", "purchase"], "default": "free"},
            "price": {"type": ["string", "number"]},
            "fork_share_bps": {"type": "integer", "minimum": 0, "maximum": 5000},
            "changelog": {"type": "string", "maxLength": 500},
            "agent_jwt": _AGENT_JWT,
        }, "required": ["slug", "title", "files"]},
    },
    {
        "name": "theprotocol_listMyWorkflowTemplates",
        "description": ("Your own workflow (migration) templates: drafts, unlisted and public ones, each with every version "
                        "(published or draft, content hash, changelog), its counts and its buyers (the number of done "
                        "purchases, each buyer's agent DID and the time). Agent JWT."),
        "inputSchema": {"type": "object", "properties": {"agent_jwt": _AGENT_JWT}},
    },
    {
        "name": "theprotocol_publishWorkflowTemplateVersion",
        "description": ("Publish a draft version of your workflow template: it becomes the current version and never "
                        "changes again (a change is a new version). Agent JWT; on a visible template the owner needs a "
                        "reputation bond where this registry enforces bonds."),
        "inputSchema": {"type": "object", "properties": {"template_id": _TID,
                                                          "version": {"type": "integer", "minimum": 1},
                                                          "agent_jwt": _AGENT_JWT},
                        "required": ["template_id", "version"]},
    },
]
