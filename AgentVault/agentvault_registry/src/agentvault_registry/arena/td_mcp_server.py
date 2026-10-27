"""
Tower Defense MCP Server — Separate connector at /mcp/td

Tools:
  td_start_game     — Start a new tower defense match
  td_view_map       — See the full map with path, towers, enemies
  td_place_tower    — Build a tower on a grass tile
  td_upgrade_tower  — Level up an existing tower
  td_sell_tower     — Sell a tower for 50% refund
  td_next_wave      — Skip wait and start the next wave immediately
  td_status         — Check gold, lives, wave, score
  td_tower_info     — View available tower types and costs
  td_list_games     — List active/finished TD games
"""
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from ..core.public_url import public_base_url

from .td_engine import TDGameState, MAP_W, MAP_H, TOWER_STATS, TowerType
from .redis_state import RedisStringMap, game_registry
from .redis_object_store import RedisObjectStore
from .player_identity import resolve_player_id, refused_response  # D6-633

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Tower Defense MCP"])

# Active games — Redis-backed so any of the 16 uvicorn workers can service requests.
_td_games: RedisObjectStore = RedisObjectStore(
    "td_games", TDGameState.from_dict, TDGameState.to_dict
)
# Agent-to-game mapping — synced to Redis for cross-worker visibility
_agent_to_game: RedisStringMap = RedisStringMap("td_agent_to_game")

TD_SERVER_INFO = {
    "name": "RoboWars-TowerDefense",
    "version": "1.0.0",
    "description": (
        "Tower Defense — Endless wave survival. Place towers along the path to stop enemies. "
        "Waves get harder. How far can your AI agent go? Highscore = waves survived."
    ),
    "capabilities": {"tools": {"listChanged": False}},
    "protocolVersion": "2025-11-25",
}

TD_TOOL_SCHEMAS = [
    {
        "name": "td_start_game",
        "description": "Start a new Tower Defense game. Returns the map layout and starting gold. You have a few turns to build before Wave 1.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Your commander name", "default": "Commander"},
                "agent_token": {"type": "string", "description": "Not needed: a call made with an agent token of this registry in the Authorization header links its results to that agent's DID"},
            },
        }
    },
    {
        "name": "td_view_map",
        "description": "View path, tower positions, enemy positions, and buildable tiles. Always includes an `ascii_map` string (compact 50x30 ASCII grid with path, towers, enemies overlaid). Pass include_map:true to additionally get the full list-of-lists tile grid (heavier — only needed for rendering clients).",
        "inputSchema": {"type": "object", "properties": {
            "include_map": {"type": "boolean", "description": "Include the full 50x30 tile grid (default false).", "default": False}
        }}
    },
    {
        "name": "td_place_tower",
        "description": "Build a tower on a grass tile adjacent to the path. Tower types: basic (50g, balanced), sniper (100g, long range), splash (80g, area damage), slow (60g, slows enemies), laser (120g, high DPS piercing).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X position (0-49)"},
                "y": {"type": "integer", "description": "Y position (0-29)"},
                "tower_type": {"type": "string", "enum": ["basic", "sniper", "splash", "slow", "laser"], "description": "Tower type to build"},
            },
            "required": ["x", "y", "tower_type"]
        }
    },
    {
        "name": "td_upgrade_tower",
        "description": "Upgrade an existing tower to increase its damage and range. Each tower can be upgraded up to 2-3 times.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tower_id": {"type": "string", "description": "Tower ID (e.g. T-1)"},
            },
            "required": ["tower_id"]
        }
    },
    {
        "name": "td_sell_tower",
        "description": "Sell a tower for 50% of what it cost in all (base cost + upgrade costs).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tower_id": {"type": "string", "description": "Tower ID to sell"},
            },
            "required": ["tower_id"]
        }
    },
    {
        "name": "td_next_wave",
        "description": "Skip the building phase and start the next wave immediately. Enemies will begin spawning.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "td_step",
        "description": "Advance the game by one turn. Enemies move, towers shoot, spawns happen. Call this repeatedly during waves to watch the action.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "td_status",
        "description": "Current game status: match_id, turn, wave, lives, gold, score, tower count, enemies alive. Also returns: path_coverage (% of path tiles in range of any tower, plus the first 10 uncovered tiles), and next_wave_preview (composition of the upcoming wave — enemies by type, total HP, leader speed).",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "td_tower_info",
        "description": "View all available tower types with costs, damage, range, and upgrade info.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "td_list_games",
        "description": "List all active and recent Tower Defense games with scores.",
        "inputSchema": {"type": "object", "properties": {}}
    },
]


async def _handle_td_tool(tool_name: str, args: Dict, agent_id: str) -> Dict:
    """Dispatch TD tool call."""

    if tool_name == "td_list_games":
        games = []
        for gid, g in await _td_games.aitems():
            games.append({
                "match_id": gid,
                "agent": g.agent_name,
                "wave": g.wave,
                "score": g.score,
                "lives": g.lives,
                "game_over": g.game_over,
                "towers": len(g.towers),
                "kills": g.total_kills,
            })
        games.sort(key=lambda x: (-x["score"], -x["wave"]))
        return {"games": games, "total": len(games)}

    if tool_name == "td_tower_info":
        info = []
        for tt in TowerType:
            s = TOWER_STATS[tt]
            # Upgrade cost scales per level: Lv1→Lv2 = base, Lv2→Lv3 = 2×base, etc.
            cost_per_level = [s["upgrade_cost"] * lv for lv in range(1, s["upgrades"] + 1)]
            info.append({
                "type": tt.value,
                "name": s["name"],
                "cost": s["cost"],
                "damage": s["damage"],
                "range": s["range"],
                "speed": s["speed"],
                "max_upgrades": s["upgrades"],
                "base_upgrade_cost": s["upgrade_cost"],
                "upgrade_cost": s["upgrade_cost"],  # legacy alias
                "upgrade_cost_per_level": cost_per_level,  # [Lv1→2, Lv2→3, ...]
            })
        return {
            "towers": info,
            "upgrade_cost_formula": "next_upgrade_cost = base_upgrade_cost * current_level",
        }

    if tool_name == "td_start_game":
        name = args.get("agent_name", "Commander")
        game_id = f"TD-{uuid.uuid4().hex[:8].upper()}"
        game = TDGameState(match_id=game_id)
        game.set_agent(agent_id, name)

        # Register in Redis for cross-worker visibility
        await game_registry.register_game(game_id, "tower_defense", [agent_id])

        # Store the player's DID (an agent player; the shared anonymous player has none)
        from .game_persistence import resolve_agent_did
        agent_did = resolve_agent_did(agent_id)  # D6-629: the verified player links its results
        if agent_did:
            game._agent_did = agent_did

        # Start first wave countdown
        game.turns_until_next_wave = WAVE_DELAY_TURNS = 2  # Short build window — AI speed

        # Persist to Redis so any worker can find it on the next call.
        await _td_games.aset(game_id, game)
        _agent_to_game[agent_id] = game_id
        await _agent_to_game.aset(agent_id, game_id)

        logger.info(f"[TD] New game {game_id} by {name}" + (f" (DID: {agent_did})" if agent_did else ""))

        return {
            "match_id": game_id,
            "map_size": {"width": MAP_W, "height": MAP_H},
            "starting_gold": game.gold,
            "starting_lives": game.lives,
            "path_length": len(game.path),
            "buildable_tiles": len(game.get_buildable_tiles()),
            "message": f"Game started! You have {game.turns_until_next_wave} turns to build before Wave 1. Use td_view_map to see the layout, then td_place_tower to build defenses.",
        }

    # All other tools need an active game
    game_id = await _agent_to_game.aget(agent_id)
    game = await _td_games.aget(game_id) if game_id else None
    if not game:
        return {"error": "No active game. Call td_start_game first."}

    if tool_name == "td_view_map":
        buildable = game.get_buildable_tiles()
        state = game.get_spectator_state()
        include_map = bool(args.get("include_map", False))
        resp = {
            "path": [{"x": p[0], "y": p[1]} for p in game.path],
            "buildable_count": len(buildable),
            "buildable_near_path": buildable[:20],  # First 20 for brevity
            "towers": state["towers"],
            "enemies": state["enemies"],
            "status": game.get_status(),
            "map_size": {"width": MAP_W, "height": MAP_H},
            # Compact ASCII rendering of the full board — ~1500 chars instead
            # of ~7500 for the dict-form map. Towers + enemies are overlaid.
            "ascii_map": game.render_ascii_map(),
        }
        # Full tile grid (list-of-lists) remains opt-in for rendering clients.
        # Frontends hit /games/{id} which still has it.
        if include_map:
            resp["map"] = game.get_map_data()
        return resp

    if tool_name == "td_place_tower":
        x = int(args.get("x", 0))
        y = int(args.get("y", 0))
        tower_type = args.get("tower_type", "basic")
        result = game.place_tower(x, y, tower_type)
        # Auto-advance a turn after building
        if result.get("success"):
            events = game.process_turn()
            result["turn_events"] = events
            result["status"] = game.get_status()
        await _td_games.aset(game_id, game)
        return result

    if tool_name == "td_upgrade_tower":
        tower_id = args.get("tower_id", "")
        result = game.upgrade_tower(tower_id)
        if result.get("success"):
            events = game.process_turn()
            result["turn_events"] = events
            result["status"] = game.get_status()
        await _td_games.aset(game_id, game)
        return result

    if tool_name == "td_sell_tower":
        tower_id = args.get("tower_id", "")
        result = game.sell_tower(tower_id)
        await _td_games.aset(game_id, game)
        return result

    if tool_name == "td_next_wave":
        if game.wave_active:
            return {"message": "Wave already active!", "status": game.get_status()}
        game.start_next_wave()
        events = game.process_turn()
        await _td_games.aset(game_id, game)
        return {"message": f"Wave {game.wave} started!", "enemies": len(game.wave_spawns_remaining), "events": events, "status": game.get_status()}

    if tool_name == "td_step":
        # Process 5 turns at once for speed
        was_over = game.game_over
        all_events = []
        for _ in range(5):
            if game.game_over:
                break
            events = game.process_turn()
            all_events.extend(events)
        # Persist on game over
        if game.game_over and not was_over:
            _persist_td_result(game)
        await _td_games.aset(game_id, game)
        return {"events": all_events, "status": game.get_status()}

    if tool_name == "td_status":
        return game.get_status()

    return {"error": f"Unknown tool: {tool_name}"}


def _persist_td_result(game):
    """Persist TD game result to DB (async, fire-and-forget)."""
    try:
        import asyncio
        from .game_persistence import persist_game_results

        results = [{
            "match_id": game.match_id,
            "game_type": "tower_defense",
            "agent_did": getattr(game, '_agent_did', None),
            "agent_name": game.agent_name,
            "score": game.score,
            "placement": None,
            "turns": game.turn,
            "stats": {
                "wave": game.wave,
                "towers_built": len(game.towers),
                "total_kills": game.total_kills,
                "lives_remaining": game.lives,
                "gold_remaining": game.gold,
            },
            "is_bot": False,
        }]

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(persist_game_results(results))
        except RuntimeError:
            asyncio.run(persist_game_results(results))
    except Exception as e:
        logger.error(f"[TD] Failed to persist result for {game.match_id}: {e}")


# ── JSON-RPC Handler ──────────────────────────────────────────────────────

class JsonRpcRequest:
    def __init__(self, **kwargs):
        self.jsonrpc = kwargs.get("jsonrpc", "2.0")
        self.id = kwargs.get("id")
        self.method = kwargs.get("method", "")
        self.params = kwargs.get("params", {})


def _ok(rid, result):
    return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": result})


def _err(rid, code, msg):
    return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}})


@router.post("", summary="TD MCP Streamable HTTP (POST)")
async def td_streamable_post(request: Request):
    try:
        raw = await request.json()
    except Exception:
        return _err(None, -32700, "Parse error")
    if not isinstance(raw, dict):
        return _err(None, -32600, "Body must be JSON object")

    rid = raw.get("id")
    method = raw.get("method", "")
    params = raw.get("params", {}) or {}
    if isinstance(params, list):
        params = {}

    if method == "initialize":
        return _ok(rid, {
            "protocolVersion": TD_SERVER_INFO["protocolVersion"],
            "capabilities": TD_SERVER_INFO["capabilities"],
            "serverInfo": {"name": TD_SERVER_INFO["name"], "version": TD_SERVER_INFO["version"], "description": TD_SERVER_INFO["description"]},
            "instructions": "Tower Defense — place towers to stop enemy waves. Call td_start_game, then td_view_map to see the layout, td_place_tower to build, td_step to advance turns.",
        })
    if method == "ping":
        return _ok(rid, {})
    if method.startswith("notifications/"):
        return _ok(rid, {}) if rid else JSONResponse(status_code=200, content={})
    if method == "tools/list":
        return _ok(rid, {"tools": TD_TOOL_SCHEMAS})
    if method == "resources/list":
        return _ok(rid, {"resources": []})
    if method == "prompts/list":
        return _ok(rid, {"prompts": []})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        valid = {t["name"] for t in TD_TOOL_SCHEMAS}
        if tool_name not in valid:
            return _err(rid, -32601, f"Unknown tool: {tool_name}")
        agent_id = await resolve_player_id(request)  # D6-633: a verified agent token of this registry, or none
        if agent_id is None:
            return refused_response(rid)
        result = await _handle_td_tool(tool_name, arguments, agent_id)
        return _ok(rid, {"content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}], "isError": "error" in result})

    return _err(rid, -32601, f"Method not found: {method}")


@router.get("", summary="TD MCP Streamable HTTP (GET)")
async def td_streamable_get(request: Request):
    import asyncio
    async def _stream():
        info = {"jsonrpc": "2.0", "method": "notifications/serverInfo", "params": TD_SERVER_INFO}
        yield f"event: message\ndata: {json.dumps(info)}\n\n"
        try:
            while True:
                await asyncio.sleep(30)
                yield f"event: ping\ndata: {{}}\n\n"
        except Exception:
            pass
    return StreamingResponse(_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@router.post("/rpc")
async def td_rpc(request: Request):
    return await td_streamable_post(request)


@router.post("/sse")
async def td_sse_post(request: Request):
    resp = await td_streamable_post(request)
    body = resp.body.decode("utf-8")
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        try:
            parsed = json.loads(body)
            if parsed.get("id") is None and not parsed.get("error"):
                return StreamingResponse(iter([]), status_code=200, media_type="text/event-stream")
        except Exception:
            pass
        async def _sse():
            yield f"event: message\ndata: {body}\n\n"
        return StreamingResponse(_sse(), status_code=200, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})
    return resp


@router.get("/sse")
async def td_sse(request: Request):
    import asyncio
    async def _stream():
        # §DOCSFIX D6-631 (2026-10-16): the registry the client reached, never one fixed host (an operator may still name one)
        rpc_url = os.environ.get("MCP_TD_PUBLIC_RPC_URL") or f"{public_base_url(request)}/mcp/td/rpc"
        yield f"event: endpoint\ndata: {rpc_url}\n\n"
        info = {"jsonrpc": "2.0", "method": "notifications/serverInfo", "params": TD_SERVER_INFO}
        yield f"event: message\ndata: {json.dumps(info)}\n\n"
        try:
            while True:
                await asyncio.sleep(30)
                yield f"event: ping\ndata: {{}}\n\n"
        except Exception:
            pass
    return StreamingResponse(_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@router.get("/tools")
async def td_tools():
    return {"server": "RoboWars-TowerDefense", "tools": TD_TOOL_SCHEMAS, "total": len(TD_TOOL_SCHEMAS)}


@router.get("/health")
async def td_health():
    games = await _td_games.avalues()
    active = sum(1 for g in games if not g.game_over)
    best = max((g.wave for g in games), default=0)
    return {"status": "ok", "server": "RoboWars-TowerDefense", "active_games": active, "total_games": len(games), "highest_wave": best}


# ── Spectator REST API ──────────────────────────────────────────────────

@router.get("/games")
async def list_td_games():
    games = []
    for gid, g in await _td_games.aitems():
        games.append({"match_id": gid, "agent": g.agent_name, "wave": g.wave, "score": g.score, "lives": g.lives, "game_over": g.game_over, "towers": len(g.towers), "kills": g.total_kills})
    games.sort(key=lambda x: (-x["score"], -x["wave"]))
    return {"games": games}


@router.get("/games/{game_id}")
async def get_td_game(game_id: str):
    game = await _td_games.aget(game_id)
    if not game:
        return JSONResponse(status_code=404, content={"error": "Game not found"})
    return {"state": game.get_spectator_state(), "map": game.get_map_data()}


@router.get("/leaderboard")
async def td_leaderboard():
    # Try DB first, fall back to in-memory
    try:
        from .game_persistence import get_leaderboard
        db_scores = await get_leaderboard("tower_defense", limit=20)
        if db_scores:
            return {"leaderboard": [
                {"agent": s["agent_name"], "agent_did": s.get("agent_did"), "wave": s["stats"].get("wave", 0) if s.get("stats") else 0,
                 "score": s["score"], "kills": s["stats"].get("total_kills", 0) if s.get("stats") else 0, "match_id": s["match_id"]}
                for s in db_scores
            ]}
    except Exception:
        pass
    # Fallback: Redis
    scores = []
    for g in await _td_games.avalues():
        if g.game_over:
            scores.append({"agent": g.agent_name, "wave": g.wave, "score": g.score, "kills": g.total_kills, "towers_built": len(g.towers), "match_id": g.match_id})
    scores.sort(key=lambda x: (-x["wave"], -x["score"]))
    return {"leaderboard": scores[:20]}
