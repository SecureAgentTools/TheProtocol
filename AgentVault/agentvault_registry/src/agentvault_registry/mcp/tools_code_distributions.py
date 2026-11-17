"""MCP tools: an organization's code distributions (V0666 D1, gwo_f1c05b131b9208a94074beae). A code distribution is an
organization's release line on top of our release, `<base_release>_<slug>`: never an AGORA payout (AGORA's distributions
are payouts to holders, a different thing that shares the word).

    getCodeDistribution                  developer: one line (its organization's members, platform admins)
    listOrganizationCodeDistributions    developer: an organization's lines
    proposeCodeDistributionChange        agent JWT: propose a code change into a line (POST /api/v1/code-changes with
                                         code_distribution)
    voteCodeDistributionChange           agent JWT (gov.vote): a decider's vote on a line's change

Every rule is the registry's (routers/code_distributions, routers/code_changes over services/code_distributions); a
refusal's sentence reaches the caller inside `error`. While CODE_DISTRIBUTIONS_ENABLED is off every route answers 404.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .auth_bridge import MCPAuthContext, require_agent_auth
from .tools_agent import _chat_request
from ..core.path_segment import seg

WHAT = "An organization's code distribution (its release line on top of our release), not an AGORA payout."
_AGENT_JWT = {"type": "string", "description": "Optional: an agent JWT from getAgentToken (speak as that agent)"}
_SLUG = {"type": "string", "description": "The line's name (its slug, e.g. lyceum: the release name is <base>_<slug>)"}


async def get_code_distribution(auth: MCPAuthContext, slug: str) -> Dict[str, Any]:
    """One code distribution: its organization, open paths, deciders' rule, state and how many decide now."""
    if not str(slug or "").strip():
        return {"error": "slug is required"}
    return await _chat_request(auth, "GET", f"/api/v1/code-distributions/{seg(slug)}", op_name="getCodeDistribution")


async def list_organization_code_distributions(auth: MCPAuthContext, organization_id: str) -> Dict[str, Any]:
    """An organization's code distributions (its release lines)."""
    if not str(organization_id or "").strip():
        return {"error": "organization_id is required"}
    return await _chat_request(auth, "GET", f"/api/v1/organizations/{seg(organization_id)}/code-distributions",
                               op_name="listOrganizationCodeDistributions")


async def propose_code_distribution_change(auth: MCPAuthContext, code_distribution: str, title: str, problem: str,
                                           paths: List[str], repository: str = "theprotocol/AgentVault",
                                           branch: Optional[str] = None, commit: Optional[str] = None,
                                           bounty: Optional[float] = None, currency: Optional[str] = None,
                                           room_id: Optional[str] = None) -> Dict[str, Any]:
    """Propose a code change into an organization's line, as a member of the organization (never a guest): its paths
    inside the line's open paths; a branch with its commit (the code written) or a bounty (a normal Guild order)."""
    require_agent_auth(auth)
    body: Dict[str, Any] = {"code_distribution": code_distribution, "title": title, "problem": problem,
                            "paths": list(paths or []), "repository": repository}
    for k, v in (("branch", branch), ("commit", commit), ("bounty", bounty), ("currency", currency), ("room_id", room_id)):
        if v not in (None, ""):
            body[k] = v
    return await _chat_request(auth, "POST", "/api/v1/code-changes", json_body=body,
                               op_name="proposeCodeDistributionChange")


async def vote_code_distribution_change(auth: MCPAuthContext, code_change_id: str, vote: bool) -> Dict[str, Any]:
    """A decider's vote (true for, false against) on a line's change in its ballot: one per developer, never changed."""
    require_agent_auth(auth)
    if not str(code_change_id or "").strip():
        return {"error": "code_change_id is required"}
    if not isinstance(vote, bool):
        return {"error": "vote is true (for) or false (against)"}
    return await _chat_request(auth, "POST", f"/api/v1/code-changes/{seg(code_change_id)}/code-distribution-vote",
                               json_body={"vote": vote}, op_name="voteCodeDistributionChange")


CODE_DISTRIBUTION_DEVELOPER_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "theprotocol_getCodeDistribution",
        "description": f"{WHAT} One line: its organization, open paths, its deciders' rule and state. A member of the "
                       f"organization or a platform admin. Needs a developer credential.",
        "inputSchema": {"type": "object", "properties": {"slug": _SLUG}, "required": ["slug"]},
    },
    {
        "name": "theprotocol_listOrganizationCodeDistributions",
        "description": f"{WHAT} An organization's lines. A member of the organization. Needs a developer credential.",
        "inputSchema": {"type": "object", "properties": {
            "organization_id": {"type": "string", "description": "The organization's id"}},
            "required": ["organization_id"]},
    },
]

CODE_DISTRIBUTION_AGENT_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "theprotocol_proposeCodeDistributionChange",
        "description": f"{WHAT} Propose a code change into the line as a member of its organization (not a guest): the "
                       f"paths inside the line's open paths; a branch with its full commit, or a bounty (a Guild order). "
                       f"Its organization's deciders vote on it, never the frame's members. Needs an agent JWT.",
        "inputSchema": {"type": "object", "properties": {
            "code_distribution": {**_SLUG, "maxLength": 40},
            "title": {"type": "string", "maxLength": 160},
            "problem": {"type": "string", "maxLength": 6000},
            "paths": {"type": "array", "items": {"type": "string"}, "maxItems": 50},
            "repository": {"type": "string", "default": "theprotocol/AgentVault", "maxLength": 120},
            "branch": {"type": "string", "maxLength": 200},
            "commit": {"type": "string", "description": "The branch's full commit id", "maxLength": 64},
            "bounty": {"type": "number", "description": "A positive amount: the code to be written, as a Guild order"},
            "currency": {"type": "string", "maxLength": 12},
            "room_id": {"type": "string", "maxLength": 36, "description": "Optional: a room of the line's organization "
                        "your agent takes part in; the change's live card and its state lines go there"},
            "agent_jwt": _AGENT_JWT},
            "required": ["code_distribution", "title", "problem", "paths"]},
    },
    {
        "name": "theprotocol_voteCodeDistributionChange",
        "description": f"{WHAT} A decider's vote on a line's change in its ballot (the organization's owners and admins "
                       f"and the deciding team's leads): true for, false against; one per developer, never changed. "
                       f"Needs an agent JWT with gov.vote.",
        "inputSchema": {"type": "object", "properties": {
            "code_change_id": {"type": "string", "description": "The change's id (cc_...)"},
            "vote": {"type": "boolean"},
            "agent_jwt": _AGENT_JWT},
            "required": ["code_change_id", "vote"]},
    },
]
