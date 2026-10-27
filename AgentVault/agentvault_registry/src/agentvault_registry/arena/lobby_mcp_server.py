"""
Game Lobby MCP Server — Shared lobby system at /mcp/lobby

Tools:
  lobby_create  — Create a new lobby for any game type
  lobby_join    — Join an existing lobby
  lobby_invite  — Invite an agent by DID (fires webhook)
  lobby_status  — Check lobby status (players, countdown)
  lobby_list    — List open lobbies
"""

import json
import logging
import uuid
import asyncio
from typing import Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from ..core.public_url import public_base_url

from .lobby import lobby_manager, register_game_starter, Lobby
from .game_persistence import resolve_agent_did
from .player_identity import resolve_player_id, refused_response  # D6-633

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Game Lobby MCP"])

LOBBY_SERVER_INFO = {
    "name": "GameLobby",
    "version": "1.0.0",
    "description": "Game Lobby — Create lobbies, invite agents by DID, set countdowns. Supports Robo Wars, Tower Defense, Snake Arena, and Market Mayhem.",
    "capabilities": {"tools": {"listChanged": False}},
    "protocolVersion": "2025-11-25",
}

LOBBY_TOOL_SCHEMAS = [
    {
        "name": "lobby_create",
        "description": "Create a new game lobby. Set the game type, max players, countdown timer, and whether to fill empty slots with bots. Other agents can join before the countdown expires.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "game_type": {"type": "string", "enum": ["robowars", "tower_defense", "snake", "trading"], "description": "Which game to play"},
                "agent_name": {"type": "string", "description": "Your display name", "default": "Host"},
                "max_players": {"type": "integer", "description": "Maximum players (2-8)", "default": 4},
                "countdown_seconds": {"type": "integer", "description": "Seconds to wait before starting (10-600)", "default": 120},
                "fill_bots": {"type": "boolean", "description": "Fill empty slots with AI bots when countdown expires", "default": True},
                "agent_token": {"type": "string", "description": "Not needed: a call made with an agent token of this registry in the Authorization header links its results to that agent's DID"},
            },
            "required": ["game_type"]
        }
    },
    {
        "name": "lobby_join",
        "description": "Join an existing lobby by ID. You'll be placed in the next available slot.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lobby_id": {"type": "string", "description": "The lobby ID to join"},
                "agent_name": {"type": "string", "description": "Your display name", "default": "Player"},
                "agent_token": {"type": "string", "description": "Not needed: a call made with an agent token of this registry in the Authorization header links its results to that agent's DID"},
            },
            "required": ["lobby_id"]
        }
    },
    {
        "name": "lobby_invite",
        "description": "Invite another agent to your lobby by their DID. They'll receive a webhook notification if they have one registered.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lobby_id": {"type": "string", "description": "Your lobby ID"},
                "agent_did": {"type": "string", "description": "DID of the agent to invite (e.g., did:cos:abc-123)"},
            },
            "required": ["lobby_id", "agent_did"]
        }
    },
    {
        "name": "lobby_status",
        "description": "Check the status of a lobby: who's joined, time remaining, whether the game has started.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lobby_id": {"type": "string", "description": "The lobby ID to check"},
            },
            "required": ["lobby_id"]
        }
    },
    {
        "name": "lobby_list",
        "description": "List all open lobbies waiting for players. Optionally filter by game type.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "game_type": {"type": "string", "enum": ["robowars", "tower_defense", "snake", "trading"], "description": "Filter by game type (omit for all)"},
            },
        }
    },
]


async def _handle_lobby_tool(tool_name: str, args: Dict, agent_id: str) -> Dict:

    if tool_name == "lobby_list":
        game_type = args.get("game_type")
        lobbies = lobby_manager.list_lobbies(game_type)
        return {"lobbies": lobbies, "count": len(lobbies)}

    if tool_name == "lobby_create":
        game_type = args.get("game_type", "robowars")
        agent_name = args.get("agent_name", "Host")
        max_players = int(args.get("max_players", 4))
        countdown = int(args.get("countdown_seconds", 120))
        fill_bots = args.get("fill_bots", True)

        agent_did = resolve_agent_did(agent_id)  # D6-629: the verified player links its results

        try:
            lobby = lobby_manager.create_lobby(
                game_type=game_type,
                creator_id=agent_id,
                creator_name=agent_name,
                creator_did=agent_did,
                max_players=max_players,
                fill_bots=fill_bots if isinstance(fill_bots, bool) else True,
                countdown_seconds=countdown,
            )
        except ValueError as e:
            return {"error": str(e)}

        return {
            "lobby_id": lobby.lobby_id,
            "game_type": game_type,
            "max_players": lobby.max_players,
            "countdown_seconds": lobby.countdown_seconds,
            "fill_bots": lobby.fill_bots,
            "identified_as": agent_did,
            "message": f"Lobby created! Others can join with lobby_join(lobby_id='{lobby.lobby_id}'). Game starts in {lobby.countdown_seconds}s or when full.",
        }

    if tool_name == "lobby_join":
        lobby_id = args.get("lobby_id", "")
        agent_name = args.get("agent_name", "Player")
        agent_did = resolve_agent_did(agent_id)  # D6-629: the verified player links its results

        result = lobby_manager.join_lobby(lobby_id, agent_id, agent_name, agent_did)
        return result or {"error": "Failed to join lobby"}

    if tool_name == "lobby_invite":
        lobby_id = args.get("lobby_id", "")
        agent_did = args.get("agent_did", "")
        if not agent_did:
            return {"error": "agent_did is required"}

        result = lobby_manager.invite_to_lobby(lobby_id, agent_did)
        return result or {"error": "Failed to invite"}

    if tool_name == "lobby_status":
        lobby_id = args.get("lobby_id", "")
        lobby = lobby_manager.get_lobby(lobby_id)
        if not lobby:
            return {"error": "Lobby not found"}
        return lobby

    return {"error": f"Unknown tool: {tool_name}"}


# ── Game Starters — called when lobby countdown expires ──

async def _start_robowars(lobby: Lobby) -> str:
    from .match_manager import match_manager
    match = await match_manager.create_match(
        mode="battle_royale",
        max_agents=len(lobby.slots),
        min_agents=len(lobby.slots),
    )
    for slot in lobby.slots:
        if slot.is_bot:
            await match_manager.add_bot(match.match_id)
        else:
            await match_manager.join_match(match.match_id, slot.agent_id, slot.agent_name)
            if slot.agent_did and not hasattr(match, '_agent_dids'):
                match._agent_dids = {}
            if slot.agent_did:
                match._agent_dids[slot.agent_id] = slot.agent_did
    # Persist the agent_dids mapping back to Redis
    await match_manager.matches.aset(match.match_id, match)
    return match.match_id


async def _start_tower_defense(lobby: Lobby) -> str:
    from .td_mcp_server import _td_games, _agent_to_game
    from .td_engine import TDGameState
    game_id = f"TD-{uuid.uuid4().hex[:8].upper()}"
    game = TDGameState(match_id=game_id)
    # TD is single-player — use the first human player
    human = next((s for s in lobby.slots if not s.is_bot), lobby.slots[0])
    game.set_agent(human.agent_id, human.agent_name)
    if human.agent_did:
        game._agent_did = human.agent_did
    _td_games[game_id] = game
    _agent_to_game[human.agent_id] = game_id
    game.start_match() if hasattr(game, 'start_match') else None
    from .redis_state import game_registry
    await game_registry.register_game(game_id, "tower_defense", [human.agent_id])
    return game_id


async def _start_snake(lobby: Lobby) -> str:
    from .snake_mcp_server import _snake_games, _agent_to_game
    from .snake_engine import SnakeGameState
    game_id = f"SN-{uuid.uuid4().hex[:8].upper()}"
    game = SnakeGameState(match_id=game_id)
    for slot in lobby.slots:
        game.add_snake(slot.agent_id, slot.agent_name)
        if not slot.is_bot:
            _agent_to_game[slot.agent_id] = game_id
    if not hasattr(game, '_agent_dids'):
        game._agent_dids = {}
    for slot in lobby.slots:
        if slot.agent_did:
            game._agent_dids[slot.agent_id] = slot.agent_did
    _snake_games[game_id] = game
    if len(game.snakes) >= 2:
        game.start_match()
    from .redis_state import game_registry
    await game_registry.register_game(game_id, "snake", list(game.snakes.keys()))
    return game_id


async def _start_trading(lobby: Lobby) -> str:
    from .trading_mcp_server import _trading_games, _agent_to_game
    from .trading_engine import TradingGameState
    game_id = f"MM-{uuid.uuid4().hex[:8].upper()}"
    game = TradingGameState(match_id=game_id)
    for slot in lobby.slots:
        game.add_trader(slot.agent_id, slot.agent_name)
        if not slot.is_bot:
            _agent_to_game[slot.agent_id] = game_id
    if not hasattr(game, '_agent_dids'):
        game._agent_dids = {}
    for slot in lobby.slots:
        if slot.agent_did:
            game._agent_dids[slot.agent_id] = slot.agent_did
    _trading_games[game_id] = game
    if len(game.traders) >= 2:
        game.start_game()
    from .redis_state import game_registry
    await game_registry.register_game(game_id, "trading", list(game.traders.keys()))
    return game_id


# Register all game starters
register_game_starter("robowars", _start_robowars)
register_game_starter("tower_defense", _start_tower_defense)
register_game_starter("snake", _start_snake)
register_game_starter("trading", _start_trading)


# ── JSON-RPC ──

@router.post("", summary="Lobby MCP Streamable HTTP")
async def lobby_post(request: Request):
    try:
        raw = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
    if not isinstance(raw, dict):
        return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Body must be JSON"}})

    rid = raw.get("id")
    method = raw.get("method", "")
    params = raw.get("params", {}) or {}
    if isinstance(params, list):
        params = {}

    if method == "initialize":
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2025-11-25",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "GameLobby", "version": "1.0.0", "description": LOBBY_SERVER_INFO["description"]},
            "instructions": "Game Lobby — use lobby_create to create a lobby, lobby_invite to invite agents by DID, lobby_join to join. Games auto-start when countdown expires.",
        }})
    if method == "ping":
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {}})
    if method.startswith("notifications/"):
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {}}) if rid else JSONResponse({})
    if method == "tools/list":
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"tools": LOBBY_TOOL_SCHEMAS}})
    if method == "resources/list":
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"resources": []}})
    if method == "prompts/list":
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"prompts": []}})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        valid = {t["name"] for t in LOBBY_TOOL_SCHEMAS}
        if tool_name not in valid:
            return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown: {tool_name}"}})
        agent_id = await resolve_player_id(request)  # D6-633: a verified agent token of this registry, or none
        if agent_id is None:
            return refused_response(rid)
        result = await _handle_lobby_tool(tool_name, arguments, agent_id)
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}], "isError": "error" in result}})

    return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown method: {method}"}})


@router.get("", summary="Lobby MCP GET")
async def lobby_get(request: Request):
    async def _s():
        yield f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'method': 'notifications/serverInfo', 'params': LOBBY_SERVER_INFO})}\n\n"
        try:
            while True:
                await asyncio.sleep(30)
                yield "event: ping\ndata: {}\n\n"
        except:
            pass
    return StreamingResponse(_s(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@router.post("/rpc")
async def lobby_rpc(request: Request):
    return await lobby_post(request)


@router.post("/sse")
async def lobby_sse_post(request: Request):
    resp = await lobby_post(request)
    body = resp.body.decode("utf-8")
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        async def _s():
            yield f"event: message\ndata: {body}\n\n"
        return StreamingResponse(_s(), status_code=200, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})
    return resp


@router.get("/sse")
async def lobby_sse(request: Request):
    async def _s():
        # §DOCSFIX D6-631 (2026-10-16): the registry the client reached, never one fixed host (an operator may still name one)
        yield f"event: endpoint\ndata: {public_base_url(request)}/mcp/lobby/rpc\n\n"
        yield f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'method': 'notifications/serverInfo', 'params': LOBBY_SERVER_INFO})}\n\n"
        try:
            while True:
                await asyncio.sleep(30)
                yield "event: ping\ndata: {}\n\n"
        except:
            pass
    return StreamingResponse(_s(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@router.get("/tools")
async def lobby_tools():
    return {"server": "GameLobby", "tools": LOBBY_TOOL_SCHEMAS, "total": len(LOBBY_TOOL_SCHEMAS)}


@router.get("/health")
async def lobby_health():
    active = sum(1 for l in lobby_manager.lobbies.values() if not l.started and not l.expired)
    return {"status": "ok", "server": "GameLobby", "active_lobbies": active, "total_lobbies": len(lobby_manager.lobbies)}
