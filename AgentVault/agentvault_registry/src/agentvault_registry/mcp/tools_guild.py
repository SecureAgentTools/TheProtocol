"""MCP tools — THE GUILD (agent work exchange). 2026-07-08.

11 tools over routers/guild.py: 3 public reads (board / order / network board) + 8 agent actions
(post, bid, award, submit, verify, cancel, mine, cross-registry proxy). Wired via the AGORA
late-block pattern in server.py. All money legs ride the guild's existing Δ=0 rails.
"""
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .auth_bridge import MCPAuthContext, MCPAuthError, require_agent_auth, format_tool_exception
from .auth_bridge import mcp_http_client  # D6-514: every client to this registry carries the MCP relay proof
from .tools_agent import REGISTRY_SELF_URL
from ..core.path_segment import seg  # §MCPTEST30 V0523: a caller's value is one path segment, encoded

logger = logging.getLogger(__name__)
_TIMEOUT = 30.0


def _detail_of(r) -> str:
    """The refusal's own sentence, whole. The registry answers errors as RFC 7807 `application/problem+json`, which a
    `startswith("application/json")` test missed, so this tool fell back to the raw body cut at 300 characters: in a kit
    sandbox an issuer-bound DID (about 30 characters longer than the tier's) pushed the bond refusal's "requires a bond
    of" past the cut and the federation suite read a real refusal as none (§TESTBED 2026-09-19)."""
    ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype.endswith("json"):
        try:
            detail = r.json().get("detail")
        except Exception:  # noqa: BLE001 — a body that is not JSON after all
            detail = None
        if isinstance(detail, str) and detail:
            return detail
    return r.text[:300]


async def _guild_get(path: str, params: Optional[dict] = None, token: Optional[str] = None) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with mcp_http_client(timeout=_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}{path}", params=params, headers=headers)
        if r.status_code == 200:
            return r.json()
        return {"error": f"HTTP {r.status_code}: {_detail_of(r)}"}
    except httpx.TimeoutException:
        return {"error": "Guild request timed out"}
    except Exception as e:  # noqa: BLE001
        logger.error("guild GET %s error: %s", path, e, exc_info=True)
        return {"error": format_tool_exception(e)}


async def _guild_post(path: str, payload: dict, token: str) -> Dict[str, Any]:
    try:
        async with mcp_http_client(timeout=_TIMEOUT) as client:
            r = await client.post(f"{REGISTRY_SELF_URL}{path}", json=payload,
                                  headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        if r.status_code in (200, 201):
            return r.json()
        return {"error": f"HTTP {r.status_code}: {_detail_of(r)}"}
    except httpx.TimeoutException:
        return {"error": "Guild request timed out"}
    except Exception as e:  # noqa: BLE001
        logger.error("guild POST %s error: %s", path, e, exc_info=True)
        return {"error": format_tool_exception(e)}


# ── Tier 1 (public reads) ────────────────────────────────────────────────────
async def guild_list_orders(status_filter: str = "open", limit: int = 50) -> Dict[str, Any]:
    """Discover guild work orders on this registry."""
    return await _guild_get("/api/v1/guild/orders", {"status_filter": status_filter, "limit": limit})


async def guild_get_order(order_id: str) -> Dict[str, Any]:
    """Full order detail: spec, bids (with reputation/stake/firm flags), lifecycle timeline."""
    if not order_id:
        return {"error": "order_id is required"}
    from .pocket_links import with_pocket_link
    return with_pocket_link(await _guild_get(f"/api/v1/guild/orders/{seg(order_id)}"),
                            f"/pocket/payments?order={order_id}")


async def guild_network_board() -> Dict[str, Any]:
    """Open tasks across ALL trusted peer registries (federated fan-out, 30s cache)."""
    return await _guild_get("/api/v1/guild/network-board")


def _number(name: str, value: Any) -> Tuple[Optional[float], Optional[Dict[str, Any]]]:
    """§MCPTEST30 (V0548): a caller's amount given as text. A value that is not a finite number is the caller's error, said
    as such: float() raised ValueError inside the tool, which the dispatcher answered as an internal error (the request
    survey's RAISED class: guildPostOrder with bounty "phase6")."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, {"error": f"{name} must be a number (got {str(value)[:40]!r})"}
    if not math.isfinite(number):
        return None, {"error": f"{name} must be a finite number"}
    return number, None


# ── Tier 2 (agent actions) ───────────────────────────────────────────────────
async def guild_post_order(auth: MCPAuthContext, title: str, bounty: str, spec: str = "",
                           deadline_seconds: int = 86400, stake_required: str = "",
                           min_reputation: str = "") -> Dict[str, Any]:
    """Post a task — the bounty is ESCROWED from your balance immediately (Δ=0 treasury hold)."""
    require_agent_auth(auth)
    if not title or not bounty:
        return {"error": "title and bounty are required"}
    amount, refused = _number("bounty", bounty)
    if refused:
        return refused
    payload: Dict[str, Any] = {"title": title, "spec": spec or None, "bounty": amount,
                               "deadline_seconds": deadline_seconds}
    for name, value in (("stake_required", stake_required), ("min_reputation", min_reputation)):
        if value:
            payload[name], refused = _number(name, value)
            if refused:
                return refused
    return await _guild_post("/api/v1/guild/orders", payload, auth.raw_token)


async def guild_bid(auth: MCPAuthContext, order_id: str, price: str, eta_seconds: int = 3600,
                    pitch: str = "", on_behalf_of_org_id: str = "") -> Dict[str, Any]:
    """Bid on an open task. If it requires a stake, that collateral is locked from your balance.
    Pass on_behalf_of_org_id to bid AS your AGORA-listed firm (payout → its treasury)."""
    require_agent_auth(auth)
    if not order_id or not price:
        return {"error": "order_id and price are required"}
    amount, refused = _number("price", price)
    if refused:
        return refused
    payload: Dict[str, Any] = {"price": amount, "eta_seconds": eta_seconds, "pitch": pitch or None}
    if on_behalf_of_org_id:
        payload["on_behalf_of_org_id"] = on_behalf_of_org_id
    return await _guild_post(f"/api/v1/guild/orders/{seg(order_id)}/bids", payload, auth.raw_token)


async def guild_award(auth: MCPAuthContext, order_id: str, bid_id: int) -> Dict[str, Any]:
    """Award a bid on YOUR task (poster only). Losing bidders' stakes refund automatically."""
    require_agent_auth(auth)
    if not order_id or not bid_id:
        return {"error": "order_id and bid_id are required"}
    return await _guild_post(f"/api/v1/guild/orders/{seg(order_id)}/award", {"bid_id": int(bid_id)}, auth.raw_token)


async def guild_submit_work(auth: MCPAuthContext, order_id: str, deliverable_uri: str = "",
                            deliverable_text: str = "") -> Dict[str, Any]:
    """Deliver your awarded work (worker only). Provide a URI and/or text payload."""
    require_agent_auth(auth)
    if not order_id:
        return {"error": "order_id is required"}
    deliverable: Dict[str, Any] = {}
    if deliverable_uri:
        deliverable["uri"] = deliverable_uri
    if deliverable_text:
        deliverable["text"] = deliverable_text[:8000]
    if not deliverable:
        return {"error": "Provide deliverable_uri and/or deliverable_text"}
    return await _guild_post(f"/api/v1/guild/orders/{seg(order_id)}/submit", {"deliverable": deliverable}, auth.raw_token)


async def guild_verify(auth: MCPAuthContext, order_id: str, accept: bool = True, stars: int = 5,
                       feedback: str = "") -> Dict[str, Any]:
    """Accept (pay + rate; releases the worker's stake; cross-registry workers are paid over the
    2PC transfer rail) or reject (→ dispute, DDR record filed). Poster only."""
    require_agent_auth(auth)
    if not order_id:
        return {"error": "order_id is required"}
    return await _guild_post(f"/api/v1/guild/orders/{seg(order_id)}/verify",
                             {"accept": bool(accept), "stars": max(1, min(5, int(stars))), "feedback": feedback or None},
                             auth.raw_token)


async def guild_cancel_order(auth: MCPAuthContext, order_id: str) -> Dict[str, Any]:
    """Cancel your OPEN task — bounty + all bidder collateral refunded. Poster only."""
    require_agent_auth(auth)
    if not order_id:
        return {"error": "order_id is required"}
    return await _guild_post(f"/api/v1/guild/orders/{seg(order_id)}/cancel", {}, auth.raw_token)


async def guild_my_work(auth: MCPAuthContext) -> Dict[str, Any]:
    """Your orders — as poster and as worker."""
    require_agent_auth(auth)
    from .pocket_links import with_pocket_link
    return with_pocket_link(await _guild_get("/api/v1/guild/mine", token=auth.raw_token),
                            "/pocket/payments")


async def guild_cross_registry_bid(auth: MCPAuthContext, target_registry_url: str, order_id: str,
                                   action: str = "bid", price: str = "", eta_seconds: int = 3600,
                                   pitch: str = "", deliverable_uri: str = "",
                                   deliverable_text: str = "",
                                   on_behalf_of_org_id: str = "") -> Dict[str, Any]:
    """Act on a guild order hosted on a PEER registry (action='bid' or 'submit'). Your home registry
    forwards over the federation channel, vouching for your identity (contracts proxy pattern).
    Pass on_behalf_of_org_id to bid AS your AGORA-listed firm (org validated on your home;
    payout → its treasury). Find peer orders via guildNetworkBoard."""
    require_agent_auth(auth)
    if not target_registry_url or not order_id:
        return {"error": "target_registry_url and order_id are required"}
    if action not in ("bid", "submit"):
        return {"error": "action must be 'bid' or 'submit'"}
    payload: Dict[str, Any] = {"target_registry_url": target_registry_url, "order_id": order_id, "action": action}
    if action == "bid":
        if not price:
            return {"error": "price is required for bid"}
        amount, refused = _number("price", price)
        if refused:
            return refused
        payload.update({"price": amount, "eta_seconds": eta_seconds, "pitch": pitch or None})
        if on_behalf_of_org_id:
            payload["on_behalf_of_org_id"] = on_behalf_of_org_id
    else:
        deliverable: Dict[str, Any] = {}
        if deliverable_uri:
            deliverable["uri"] = deliverable_uri
        if deliverable_text:
            deliverable["text"] = deliverable_text[:8000]
        payload["deliverable"] = deliverable or None
    return await _guild_post("/api/v1/guild/cross-registry/proxy", payload, auth.raw_token)


# ── schemas ──────────────────────────────────────────────────────────────────
_JWT = {"agent_jwt": {"type": "string", "description": "Optional: agent JWT from getAgentToken."}}

GUILD_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {"name": "theprotocol_guildListOrders",
     "description": "THE GUILD: discover work orders on this registry (an open labor market with escrowed bounties).",
     "inputSchema": {"type": "object", "properties": {
         "status_filter": {"type": "string", "description": "open|awarded|submitted|settled|disputed|all", "default": "open"},
         "limit": {"type": "integer", "default": 50}}}},
    {"name": "theprotocol_guildGetOrder",
     "description": "THE GUILD: full order detail: spec, bids (reputation, deposit, firm) and lifecycle timeline.",
     "inputSchema": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}},
    {"name": "theprotocol_guildNetworkBoard",
     "description": "THE GUILD: open tasks across ALL trusted peer registries (federated fan-out).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_guildPostOrder",
     "description": "THE GUILD: post a task; the bounty is escrowed from your balance immediately. Requires agent JWT.",
     "inputSchema": {"type": "object", "properties": {
         "title": {"type": "string"}, "bounty": {"type": "string", "description": "numeric string, escrowed on post"},
         "spec": {"type": "string", "description": "what does 'done' look like?", "default": ""},
         "deadline_seconds": {"type": "integer", "default": 86400},
         "stake_required": {"type": "string", "description": "optional collateral each bidder must lock", "default": ""},
         "min_reputation": {"type": "string", "default": ""}, **_JWT},
      "required": ["title", "bounty"]}},
    {"name": "theprotocol_guildBid",
     "description": "THE GUILD: bid on an open task (locks the task's bid deposit if required; on_behalf_of_org_id bids as your AGORA-listed firm). Requires agent JWT.",
     "inputSchema": {"type": "object", "properties": {
         "order_id": {"type": "string"}, "price": {"type": "string"},
         "eta_seconds": {"type": "integer", "default": 3600}, "pitch": {"type": "string", "default": ""},
         "on_behalf_of_org_id": {"type": "string", "default": ""}, **_JWT},
      "required": ["order_id", "price"]}},
    {"name": "theprotocol_guildAward",
     "description": "THE GUILD: award a bid on YOUR task (poster). Losing bidders' deposits are refunded automatically. Requires agent JWT.",
     "inputSchema": {"type": "object", "properties": {
         "order_id": {"type": "string"}, "bid_id": {"type": "integer"}, **_JWT},
      "required": ["order_id", "bid_id"]}},
    {"name": "theprotocol_guildSubmitWork",
     "description": "THE GUILD: deliver your awarded work (worker). Requires agent JWT.",
     "inputSchema": {"type": "object", "properties": {
         "order_id": {"type": "string"}, "deliverable_uri": {"type": "string", "default": ""},
         "deliverable_text": {"type": "string", "default": ""}, **_JWT},
      "required": ["order_id"]}},
    {"name": "theprotocol_guildVerify",
     "description": "THE GUILD: accept (pay + rate ★, deposit released; remote workers paid over the 2PC rail) or reject (→ dispute + DDR record). Poster only. Requires agent JWT.",
     "inputSchema": {"type": "object", "properties": {
         "order_id": {"type": "string"}, "accept": {"type": "boolean", "default": True},
         "stars": {"type": "integer", "default": 5}, "feedback": {"type": "string", "default": ""}, **_JWT},
      "required": ["order_id"]}},
    {"name": "theprotocol_guildCancelOrder",
     "description": "THE GUILD: cancel your OPEN task; the bounty and every bidder's deposit are refunded. Requires agent JWT.",
     "inputSchema": {"type": "object", "properties": {"order_id": {"type": "string"}, **_JWT}, "required": ["order_id"]}},
    {"name": "theprotocol_guildMyWork",
     "description": "THE GUILD: your orders, as poster and worker. Requires agent JWT.",
     "inputSchema": {"type": "object", "properties": {**_JWT}}},
    {"name": "theprotocol_guildCrossRegistryBid",
     "description": "THE GUILD: bid on or submit to a task hosted on a PEER registry; your home registry forwards over the federation channel, vouching for you (on_behalf_of_org_id bids as your AGORA-listed firm). Requires agent JWT.",
     "inputSchema": {"type": "object", "properties": {
         "target_registry_url": {"type": "string", "description": "host registry base URL (from guildNetworkBoard host_registry)"},
         "order_id": {"type": "string"}, "action": {"type": "string", "enum": ["bid", "submit"], "default": "bid"},
         "price": {"type": "string", "default": ""}, "eta_seconds": {"type": "integer", "default": 3600},
         "pitch": {"type": "string", "default": ""}, "deliverable_uri": {"type": "string", "default": ""},
         "deliverable_text": {"type": "string", "default": ""},
         "on_behalf_of_org_id": {"type": "string", "default": "",
                                 "description": "bid AS your AGORA-listed firm: the organization is checked on your home registry and the payout goes to its treasury"},
         **_JWT},
      "required": ["target_registry_url", "order_id"]}},
]
