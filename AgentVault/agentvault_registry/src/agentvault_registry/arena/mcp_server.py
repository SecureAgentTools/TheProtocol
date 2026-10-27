"""
Robo Wars Arena MCP Server — Separate connector at /mcp/arena

8 game tools for agent control:
  robowars_look, robowars_move, robowars_shoot, robowars_pickup,
  robowars_use_item, robowars_swap_weapon, robowars_status, robowars_extract

Plus match management:
  robowars_join_match, robowars_list_matches
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from ..core.public_url import public_base_url
from pydantic import BaseModel, Field

from .match_manager import match_manager
from .betting import betting_manager
from .player_identity import resolve_player_id, refused_response  # D6-633

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Robo Wars Arena MCP"])

ARENA_SERVER_INFO = {
    "name": "RoboWars-Arena",
    "version": "1.0.0",
    "description": (
        "Robo Wars — Top-down turn-based agent battle arena. "
        "AI agents fight, loot, and extract using MCP tool calls. "
        "Spectators watch live and bet AVT tokens."
    ),
    "capabilities": {"tools": {"listChanged": False}},
    "protocolVersion": "2025-11-25",
}

# ── Tool Schemas ──────────────────────────────────────────────────────────

ARENA_TOOL_SCHEMAS = [
    {
        "name": "robowars_list_matches",
        "description": "List active and recent matches in the arena.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "robowars_join_match",
        "description": "Join an existing match or create a new one. Returns your spawn position.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "match_id": {"type": "string", "description": "Match ID to join (omit to create new match)"},
                "agent_name": {"type": "string", "description": "Display name for your agent in the arena"},
                "mode": {"type": "string", "enum": ["battle_royale", "extraction"], "default": "battle_royale"},
                "add_bots": {"type": "integer", "description": "Number of AI bots to add (1-7)", "default": 4},
                "agent_token": {"type": "string", "description": "Not needed: a call made with an agent token of this registry in the Authorization header links its results to that agent's DID"},
            },
            "required": ["agent_name"]
        }
    },
    {
        "name": "robowars_look",
        "description": "Survey your surroundings. Returns visible tiles, enemies, and items within your vision radius. Call this before deciding your next move.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "robowars_move",
        "description": "Move 1 tile in a direction. Directions: north, south, east, west, northeast, northwest, southeast, southwest.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest"]}
            },
            "required": ["direction"]
        }
    },
    {
        "name": "robowars_shoot",
        "description": "Fire your active weapon in a direction. Uses 1 ammo. Damage depends on weapon type and range.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest"]}
            },
            "required": ["direction"]
        }
    },
    {
        "name": "robowars_pickup",
        "description": "Pick up an item at your current position. Items: health_kit, ammo_crate, armor_vest, scope, weapons.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "robowars_use_item",
        "description": "Use a consumable from inventory. Currently: health_kit (restores 40 HP).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item": {"type": "string", "description": "Item to use (e.g. 'health_kit')"}
            },
            "required": ["item"]
        }
    },
    {
        "name": "robowars_swap_weapon",
        "description": "Switch to a different weapon in your inventory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "weapon": {"type": "string", "enum": ["pistol", "shotgun", "rifle", "grenade"]}
            },
            "required": ["weapon"]
        }
    },
    {
        "name": "robowars_status",
        "description": "Check your current status: health, ammo, inventory, position, kills, turn number, agents alive.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "robowars_extract",
        "description": "Attempt extraction (extraction mode only). Must be standing on an extraction zone tile.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "robowars_bet",
        "description": "Place an AVT bet on which agent will win. Betting closes when the match starts. One bet per agent per match. Payouts: 80% to winning bettors, 10% to winning agent, 10% arena fee.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "match_id": {"type": "string", "description": "Match to bet on"},
                "target_agent_name": {"type": "string", "description": "Name of the agent you're betting on"},
                "amount": {"type": "number", "description": "AVT amount to bet"},
            },
            "required": ["match_id", "target_agent_name", "amount"]
        }
    },
    {
        "name": "robowars_match_results",
        "description": "Get detailed results of a finished match including kill stats, placements, and betting payouts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "match_id": {"type": "string", "description": "Match ID to check"}
            },
            "required": ["match_id"]
        }
    },
]


# ── Tool Dispatch ─────────────────────────────────────────────────────────

async def _handle_tool_call(tool_name: str, args: Dict, agent_id: str) -> Dict:
    """Dispatch tool call to game engine."""

    if tool_name == "robowars_list_matches":
        return {"matches": await match_manager.list_matches()}

    if tool_name == "robowars_join_match":
        match_id = args.get("match_id")
        agent_name = args.get("agent_name", "Agent")
        mode = args.get("mode", "battle_royale")
        add_bots = min(7, max(0, int(args.get("add_bots", 4))))

        from .game_persistence import resolve_agent_did
        agent_did = resolve_agent_did(agent_id)  # D6-629: the verified player links its results

        if not match_id:
            # Create new match
            match = await match_manager.create_match(mode=mode, max_agents=1 + add_bots, min_agents=1 + add_bots)
            match_id = match.match_id

        result = await match_manager.join_match(match_id, agent_id, agent_name)
        if result and "error" not in result:
            # Store DID mapping on match for later persistence
            match = await match_manager.get_match(match_id)
            if match and agent_did:
                if not hasattr(match, '_agent_dids'):
                    match._agent_dids = {}
                match._agent_dids[agent_id] = agent_did
                result["identified_as"] = agent_did
                # Persist DID mapping
                await match_manager.matches.aset(match_id, match)

            # Add bots
            for _ in range(add_bots):
                await match_manager.add_bot(match_id)
            result["bots_added"] = add_bots
            # Re-read the match after bots have joined so the top-level
            # response reflects the post-join state (agents_joined + started).
            # Without this, callers see `started: false, agents_joined: 1`
            # while initial_view already shows `turn: 1, agents_alive: 4`.
            match = await match_manager.get_match(match_id)
            if match:
                result["agents_joined"] = len(match.game.agents)
                result["started"] = match.game.started
                if match.game.started:
                    agent_state = match.game.agents.get(agent_id)
                    if agent_state:
                        look = match.game._do_look(agent_state)
                        result["initial_view"] = look
        return result

    if tool_name == "robowars_bet":
        # D8: betting is a retired money surface behind a flag (default on)
        from agentvault_registry.core.legacy_surfaces import surface_enabled as _se, retired_sentence as _rs
        if not _se("ARENA_BETTING_ENABLED"):
            return {"error": _rs("ARENA_BETTING_ENABLED")}
        match_id = args.get("match_id", "")
        target_name = args.get("target_agent_name", "")
        amount = float(args.get("amount", 0))
        if amount <= 0:
            return {"error": "Bet amount must be positive"}

        match = await match_manager.get_match(match_id)
        if not match:
            return {"error": f"Match {match_id} not found"}
        # §DOCSFIX D6-632 (2026-10-16): betting closes when the match starts. The pool's own `closed` flag is set only on
        # a pool that exists (pools open on the first bet, in each worker's memory), so a bet after the start opened a
        # fresh pool and was taken; the match's state is shared, and decides.
        if match.game.started or match.game.finished:
            return {"error": "Betting is closed: this match has already started"}

        # Find target agent by name
        target_id = None
        for a in match.game.agents.values():
            if a.name.lower() == target_name.lower():
                target_id = a.agent_id
                target_name = a.name
                break
        if not target_id:
            names = [a.name for a in match.game.agents.values()]
            return {"error": f"Agent '{target_name}' not in match. Available: {names}"}

        result = betting_manager.place_bet(match_id, agent_id, agent_id[:12], target_id, target_name, amount)
        if not result:
            return {"error": "Could not place bet — betting may be closed or you already bet on this match"}
        return result

    if tool_name == "robowars_match_results":
        match_id = args.get("match_id", "")
        match = await match_manager.get_match(match_id)
        if not match:
            return {"error": "Match not found"}
        state = match.game.get_spectator_state()
        bets = betting_manager.get_pool_status(match_id)
        winner = match.game.agents.get(match.game.winner) if match.game.winner else None
        return {
            "match_id": match_id,
            "finished": match.game.finished,
            "mode": match.game.mode,
            "turns": match.game.turn,
            "winner": {"id": winner.agent_id, "name": winner.name, "kills": winner.kills, "damage_dealt": winner.damage_dealt} if winner else None,
            "placements": [
                {"name": a.name, "alive": a.alive, "kills": a.kills, "damage_dealt": a.damage_dealt, "damage_taken": a.damage_taken}
                for a in sorted(match.game.agents.values(), key=lambda x: (not x.alive, -x.kills, -x.damage_dealt))
            ],
            # damage_taken is CUMULATIVE raw damage received (including from
            # storm), so it can exceed max_health if the agent healed via
            # medkits. A survivor with damage_taken > 100 isn't a bug —
            # they absorbed and healed past it.
            "stats_note": "damage_taken is cumulative raw damage (incl. storm); may exceed max_health when healed.",
            "betting": bets,
        }

    # All other tools need an active match
    match = await match_manager.get_agent_match(agent_id)
    if not match:
        return {"error": "Not in a match. Call robowars_join_match first."}
    if not match.game.started:
        return {"error": "Match hasn't started yet. Waiting for more agents."}
    if match.game.finished:
        winner = match.game.agents.get(match.game.winner)
        return {"error": f"Match is over. Winner: {winner.name if winner else 'none'}"}

    # Force-advance if turn timed out
    await match_manager.force_advance_turn(match.match_id)

    # Read-only tools: resolve directly against the engine without going
    # through submit_action (which would count them as a "turn" because
    # process_action returns success=True for look/status).
    if tool_name == "robowars_look":
        agent_state = match.game.agents.get(agent_id)
        if not agent_state:
            return {"error": "Agent not found"}
        return match.game._do_look(agent_state)
    if tool_name == "robowars_status":
        agent_state = match.game.agents.get(agent_id)
        if not agent_state:
            return {"error": "Agent not found"}
        return match.game._do_status(agent_state)

    # Map remaining tool names to game actions that consume a turn
    action_map = {
        "robowars_move": "move",
        "robowars_shoot": "shoot",
        "robowars_pickup": "pickup",
        "robowars_use_item": "use_item",
        "robowars_swap_weapon": "swap_weapon",
        "robowars_extract": "extract",
    }

    action = action_map.get(tool_name)
    if not action:
        return {"error": f"Unknown tool: {tool_name}"}

    return await match_manager.submit_action(agent_id, action, args)


# ── JSON-RPC Handler ──────────────────────────────────────────────────────

class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    method: str
    params: Optional[Union[Dict, List]] = None


def _ok(request_id, result):
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def _err(request_id, code, message):
    return JSONResponse(
        status_code=400 if code in (-32600, -32602) else 500,
        content={"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    )


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.post("", summary="Arena MCP Streamable HTTP (POST)")
async def arena_streamable_post(request: Request):
    """Streamable HTTP for Arena MCP. Content-negotiates JSON vs SSE."""
    try:
        raw_body = await request.json()
    except Exception:
        return _err(None, -32700, "Parse error")

    if not isinstance(raw_body, dict):
        return _err(None, -32600, "Body must be JSON object")

    try:
        payload = JsonRpcRequest(**raw_body)
    except Exception as e:
        return _err(None, -32600, str(e))

    request_id = payload.id
    method = payload.method
    params = payload.params or {}
    if isinstance(params, list):
        params = {}


    if method == "initialize":
        return _ok(request_id, {
            "protocolVersion": ARENA_SERVER_INFO["protocolVersion"],
            "capabilities": ARENA_SERVER_INFO["capabilities"],
            "serverInfo": {
                "name": ARENA_SERVER_INFO["name"],
                "version": ARENA_SERVER_INFO["version"],
                "description": ARENA_SERVER_INFO["description"],
            },
            "instructions": (
                "Robo Wars Arena — AI agent battle arena.\n"
                "Call robowars_join_match to enter a match, then use robowars_look, "
                "robowars_move, robowars_shoot etc. to play.\n"
                "10 tools available. Turn-based — you have 10 seconds per turn."
            ),
        })

    if method == "ping":
        return _ok(request_id, {})

    if method.startswith("notifications/"):
        return _ok(request_id, {}) if request_id else JSONResponse(status_code=200, content={})

    if method == "tools/list":
        # robowars_bet is listed only where arena betting is on (a retired surface where it is off, D8); a call by name
        # still gets the surface's own refusal below
        from agentvault_registry.core.legacy_surfaces import surface_enabled as _se_list
        _tools = [t for t in ARENA_TOOL_SCHEMAS if t.get("name") != "robowars_bet" or _se_list("ARENA_BETTING_ENABLED")]
        return _ok(request_id, {"tools": _tools})

    if method == "resources/list":
        return _ok(request_id, {"resources": []})

    if method == "prompts/list":
        return _ok(request_id, {"prompts": []})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}

        if not tool_name:
            return _err(request_id, -32602, "name required")

        valid_tools = {t["name"] for t in ARENA_TOOL_SCHEMAS}
        if tool_name not in valid_tools:
            return _err(request_id, -32601, f"Unknown tool: {tool_name}")

        agent_id = await resolve_player_id(request)  # D6-633: a verified agent token of this registry, or none
        if agent_id is None:
            return refused_response(request_id)
        result = await _handle_tool_call(tool_name, arguments, agent_id)

        return _ok(request_id, {
            "content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}],
            "isError": "error" in result,
        })

    return _err(request_id, -32601, f"Method not found: {method}")


@router.get("", summary="Arena MCP Streamable HTTP (GET — notifications)")
async def arena_streamable_get(request: Request):
    """SSE stream for arena notifications."""
    import asyncio

    async def _stream():
        info = {"jsonrpc": "2.0", "method": "notifications/serverInfo", "params": ARENA_SERVER_INFO}
        yield f"event: message\ndata: {json.dumps(info)}\n\n"
        try:
            while True:
                await asyncio.sleep(30)
                yield f"event: ping\ndata: {{}}\n\n"
        except Exception:
            pass

    return StreamingResponse(
        _stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/rpc", summary="Arena MCP JSON-RPC (legacy)")
async def arena_rpc(request: Request):
    """Legacy JSON-RPC endpoint — delegates to Streamable HTTP handler."""
    return await arena_streamable_post(request)


@router.post("/sse", summary="Arena MCP SSE POST transport (mcp-remote)")
async def arena_sse_post(request: Request):
    """mcp-remote POSTs JSON-RPC to the SSE URL. Wrap response as SSE event."""
    json_response = await arena_streamable_post(request)
    response_body = json_response.body.decode("utf-8")

    # Check if client wants SSE
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        try:
            parsed = json.loads(response_body)
            if parsed.get("id") is None and not parsed.get("error"):
                return StreamingResponse(iter([]), status_code=200, media_type="text/event-stream")
        except Exception:
            pass
        sse_payload = f"event: message\ndata: {response_body}\n\n"
        async def _sse():
            yield sse_payload
        return StreamingResponse(
            _sse(), status_code=200, media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )
    return json_response


@router.get("/sse", summary="Arena MCP SSE transport")
async def arena_sse(request: Request):
    """SSE transport — returns endpoint URL then keepalive."""
    import asyncio

    async def _stream():
        # §DOCSFIX D6-631 (2026-10-16): the registry the client reached, never one fixed host (an operator may still name one)
        rpc_url = os.environ.get("MCP_ARENA_PUBLIC_RPC_URL") or f"{public_base_url(request)}/mcp/arena/rpc"
        yield f"event: endpoint\ndata: {rpc_url}\n\n"
        info = {"jsonrpc": "2.0", "method": "notifications/serverInfo", "params": ARENA_SERVER_INFO}
        yield f"event: message\ndata: {json.dumps(info)}\n\n"
        try:
            while True:
                await asyncio.sleep(30)
                yield f"event: ping\ndata: {{}}\n\n"
        except Exception:
            pass

    return StreamingResponse(
        _stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/tools", summary="List arena tools")
async def arena_tools():
    return {"server": "RoboWars-Arena", "tools": ARENA_TOOL_SCHEMAS, "total": len(ARENA_TOOL_SCHEMAS)}


@router.get("/health", summary="Arena health")
async def arena_health():
    matches = await match_manager.matches.avalues()
    return {
        "status": "ok",
        "server": "RoboWars-Arena",
        "active_matches": len([m for m in matches if not m.game.finished]),
        "total_matches": len(matches),
    }


    # Arena is open access — but mcp-remote checks for OAuth.
    # Return metadata that explicitly declares NO auth required.


@router.get("/.well-known/oauth-authorization-server")
async def arena_no_oauth(request: Request):
    """Return empty OAuth metadata — arena is open access."""
    # Return 404 to tell mcp-remote "no OAuth here"
    return JSONResponse(status_code=404, content={"error": "No authentication required for the arena"})
