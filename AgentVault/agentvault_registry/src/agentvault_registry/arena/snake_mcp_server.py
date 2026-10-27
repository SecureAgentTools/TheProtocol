"""
Snake Arena MCP Server — Separate connector at /mcp/snake

Tools:
  snake_join       — Join/create a snake match
  snake_look       — View the full board
  snake_turn       — Set direction (north/south/east/west)
  snake_status     — Score, length, alive
  snake_list_games — List matches
"""
import json
import logging
import os
import uuid
import time
from typing import Dict, List, Optional, Union

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from ..core.public_url import public_base_url

from .snake_engine import SnakeGameState, MAP_SIZE, DIRECTIONS
from .redis_state import RedisStringMap, game_registry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Snake Arena MCP"])

# Game engine objects stay in local memory (not serializable)
from .redis_object_store import RedisObjectStore
from .player_identity import resolve_player_id, refused_response  # D6-633
_snake_games: RedisObjectStore = RedisObjectStore(
    "snake_games", SnakeGameState.from_dict, SnakeGameState.to_dict
)
# Agent-to-game mapping — synced to Redis for cross-worker visibility
_agent_to_game: RedisStringMap = RedisStringMap("snake_agent_to_game")
_bot_counter = 0

SNAKE_SERVER_INFO = {
    "name": "RoboWars-Snake",
    "version": "1.0.0",
    "description": "Snake Arena — Multiplayer snake on a 30x30 grid. Eat food to grow. Crash = death. Last snake alive wins.",
    "capabilities": {"tools": {"listChanged": False}},
    "protocolVersion": "2025-11-25",
}

SNAKE_TOOL_SCHEMAS = [
    {
        "name": "snake_join",
        "description": "Join or create a snake match. Add AI bots to play against. Returns your starting position.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Your snake name", "default": "Snek"},
                "match_id": {"type": "string", "description": "Match to join (omit for new game)"},
                "add_bots": {"type": "integer", "description": "Number of AI bot snakes (1-5)", "default": 2},
                "agent_token": {"type": "string", "description": "Not needed: a call made with an agent token of this registry in the Authorization header links its results to that agent's DID"},
            },
        }
    },
    {
        "name": "snake_look",
        "description": "View the entire board: your body, other snakes, food positions, walls. Call this before choosing your direction.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "snake_turn",
        "description": "Set your snake's direction for this turn. Can't reverse (e.g., can't go west if heading east). After setting direction, the turn auto-advances.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["north", "south", "east", "west"]}
            },
            "required": ["direction"]
        }
    },
    {
        "name": "snake_status",
        "description": "Check your score, length, alive status, and match info.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "snake_step",
        "description": "Advance the game by one turn without changing direction. Your snake continues in its current direction. Bots move automatically.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "snake_list_games",
        "description": "List all active and recent snake matches.",
        "inputSchema": {"type": "object", "properties": {}}
    },
]


class SnakeBot:
    """Simple greedy snake AI."""

    @staticmethod
    def choose_direction(game: SnakeGameState, snake_id: str) -> str:
        import random as rng
        snake = game.snakes.get(snake_id)
        if not snake or not snake.alive:
            return "east"

        hx, hy = snake.head
        body_set = set()
        for s in game.snakes.values():
            if s.alive:
                body_set.update(s.body)

        # Find nearest food
        best_dir = snake.direction
        if game.food:
            nearest = min(game.food, key=lambda f: abs(f.x - hx) + abs(f.y - hy))
            dx = nearest.x - hx
            dy = nearest.y - hy

            candidates = []
            if dx > 0: candidates.append("east")
            elif dx < 0: candidates.append("west")
            if dy > 0: candidates.append("south")
            elif dy < 0: candidates.append("north")
            if not candidates:
                candidates = list(DIRECTIONS.keys())

            # Filter safe directions
            from .snake_engine import OPPOSITES
            safe = []
            for d in candidates:
                if d == OPPOSITES.get(snake.direction):
                    continue
                ddx, ddy = DIRECTIONS[d]
                nx, ny = hx + ddx, hy + ddy
                if (nx, ny) not in game.walls and (nx, ny) not in body_set:
                    safe.append(d)

            if safe:
                best_dir = safe[0]
            else:
                # Any safe direction
                from .snake_engine import OPPOSITES
                for d in DIRECTIONS:
                    if d == OPPOSITES.get(snake.direction):
                        continue
                    ddx, ddy = DIRECTIONS[d]
                    nx, ny = hx + ddx, hy + ddy
                    if (nx, ny) not in game.walls and (nx, ny) not in body_set:
                        best_dir = d
                        break

        return best_dir


async def _handle_snake_tool(tool_name: str, args: Dict, agent_id: str) -> Dict:
    global _bot_counter

    if tool_name == "snake_list_games":
        games = []
        for gid, g in await _snake_games.aitems():
            games.append({
                "match_id": gid, "snakes": len(g.snakes),
                "turn": g.turn, "finished": g.finished,
                "winner": g.snakes.get(g.winner, None) and g.snakes[g.winner].name if g.winner else None,
            })
        return {"games": games}

    if tool_name == "snake_join":
        name = args.get("agent_name", "Snek")
        match_id = args.get("match_id")
        add_bots = min(5, max(0, int(args.get("add_bots", 2))))

        from .game_persistence import resolve_agent_did
        agent_did = resolve_agent_did(agent_id)  # D6-629: the verified player links its results

        if not match_id:
            match_id = f"SN-{uuid.uuid4().hex[:8].upper()}"
            game = SnakeGameState(match_id=match_id)
        else:
            game = await _snake_games.aget(match_id)
            if not game:
                return {"error": "Game not found"}

        if game.started:
            return {"error": "Game already started"}

        snake = game.add_snake(agent_id, name)

        # Register in Redis for cross-worker visibility
        player_ids = list(game.snakes.keys())
        await game_registry.register_game(match_id, "snake", player_ids)

        # Store DID for persistence
        if agent_did:
            if not hasattr(game, '_agent_dids'):
                game._agent_dids = {}
            game._agent_dids[agent_id] = agent_did

        # Add bots
        bot_names = ["Cobra", "Viper", "Python", "Mamba", "Rattler"]
        for i in range(add_bots):
            _bot_counter += 1
            bot_id = f"bot:snake:{uuid.uuid4().hex[:6]}"
            bot_name = f"BOT-{bot_names[_bot_counter % len(bot_names)]}"
            game.add_snake(bot_id, bot_name)

        # Auto-start
        if len(game.snakes) >= 2:
            game.start_match()

        # Persist to Redis so any worker can find it.
        await _snake_games.aset(match_id, game)
        _agent_to_game[agent_id] = match_id
        await _agent_to_game.aset(agent_id, match_id)

        view = game.get_view(agent_id)
        return {
            "match_id": match_id,
            "started": game.started,
            "your_snake": name,
            "position": {"x": snake.head[0], "y": snake.head[1]},
            "length": snake.length,
            "snakes_in_game": len(game.snakes),
            "view": view,
        }

    # Need active game
    game_id = await _agent_to_game.aget(agent_id)
    game = await _snake_games.aget(game_id) if game_id else None
    if not game:
        return {"error": "Not in a game. Call snake_join first."}

    if tool_name == "snake_look":
        return game.get_view(agent_id)

    if tool_name == "snake_status":
        snake = game.snakes.get(agent_id)
        if not snake:
            return {"error": "Not in game"}
        return {
            "alive": snake.alive, "score": snake.score, "length": snake.length,
            "direction": snake.direction, "head": {"x": snake.head[0], "y": snake.head[1]},
            "turn": game.turn, "snakes_alive": sum(1 for s in game.snakes.values() if s.alive),
            "finished": game.finished,
        }

    if tool_name == "snake_turn":
        direction = args.get("direction", "")

        # Set player direction
        result = game.set_direction(agent_id, direction)
        if not result.get("success"):
            return result

        # Move bots + advance turn
        _advance_snake_turn(game)
        await _snake_games.aset(game_id, game)

        view = game.get_view(agent_id)
        snake = game.snakes.get(agent_id)
        return {
            "success": True,
            "direction": direction,
            "events": game._last_events if hasattr(game, '_last_events') else [],
            "view": view,
            "status": {
                "alive": snake.alive if snake else False,
                "score": snake.score if snake else 0,
                "length": snake.length if snake else 0,
                "turn": game.turn,
                "finished": game.finished,
            }
        }

    if tool_name == "snake_step":
        # Advance without changing direction — bots still move
        _advance_snake_turn(game)
        await _snake_games.aset(game_id, game)
        view = game.get_view(agent_id)
        snake = game.snakes.get(agent_id)
        return {
            "events": game._last_events if hasattr(game, '_last_events') else [],
            "view": view,
            "status": {
                "alive": snake.alive if snake else False,
                "score": snake.score if snake else 0,
                "length": snake.length if snake else 0,
                "turn": game.turn,
                "finished": game.finished,
            }
        }

    return {"error": f"Unknown tool: {tool_name}"}


def _advance_snake_turn(game: SnakeGameState):
    """Move all bots and process one turn."""
    was_finished = game.finished
    for sid, snake in game.snakes.items():
        if sid.startswith("bot:") and snake.alive:
            bot_dir = SnakeBot.choose_direction(game, sid)
            game.set_direction(sid, bot_dir)
    events = game.process_turn()
    game._last_events = events

    # Persist on game end
    if game.finished and not was_finished:
        _persist_snake_result(game)


def _persist_snake_result(game: SnakeGameState):
    """Persist snake game results to DB (async, fire-and-forget)."""
    try:
        import asyncio
        from .game_persistence import persist_game_results

        agent_dids = getattr(game, '_agent_dids', {})
        sorted_snakes = sorted(game.snakes.values(), key=lambda s: (-s.score, not s.alive))

        results = []
        for idx, snake in enumerate(sorted_snakes):
            results.append({
                "match_id": game.match_id,
                "game_type": "snake",
                "agent_did": agent_dids.get(snake.agent_id),
                "agent_name": snake.name,
                "score": snake.score,
                "placement": idx + 1,
                "turns": game.turn,
                "stats": {
                    "length": snake.length,
                    "alive_at_end": snake.alive,
                    "is_winner": snake.agent_id == game.winner,
                },
                "is_bot": snake.agent_id.startswith("bot:"),
            })

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(persist_game_results(results))
        except RuntimeError:
            asyncio.run(persist_game_results(results))
    except Exception as e:
        logger.error(f"[Snake] Failed to persist result for {game.match_id}: {e}")


# ── JSON-RPC ──────────────────────────────────────────────────────────────

@router.post("", summary="Snake MCP Streamable HTTP")
async def snake_post(request: Request):
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
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2025-11-25", "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "RoboWars-Snake", "version": "1.0.0", "description": SNAKE_SERVER_INFO["description"]}, "instructions": "Snake Arena — call snake_join to start, snake_look to see the board, snake_turn to move. Eat food, avoid walls and other snakes!"}})
    if method == "ping":
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {}})
    if method.startswith("notifications/"):
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {}}) if rid else JSONResponse(status_code=200, content={})
    if method == "tools/list":
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"tools": SNAKE_TOOL_SCHEMAS}})
    if method == "resources/list":
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"resources": []}})
    if method == "prompts/list":
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"prompts": []}})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        valid = {t["name"] for t in SNAKE_TOOL_SCHEMAS}
        if tool_name not in valid:
            return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown: {tool_name}"}})
        agent_id = await resolve_player_id(request)  # D6-633: a verified agent token of this registry, or none
        if agent_id is None:
            return refused_response(rid)
        result = await _handle_snake_tool(tool_name, arguments, agent_id)
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}], "isError": "error" in result}})

    return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown method: {method}"}})


@router.get("", summary="Snake MCP GET")
async def snake_get(request: Request):
    import asyncio
    async def _s():
        yield f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'method': 'notifications/serverInfo', 'params': SNAKE_SERVER_INFO})}\n\n"
        try:
            while True:
                await asyncio.sleep(30)
                yield f"event: ping\ndata: {{}}\n\n"
        except:
            pass
    return StreamingResponse(_s(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@router.post("/rpc")
async def snake_rpc(request: Request):
    return await snake_post(request)


@router.post("/sse")
async def snake_sse_post(request: Request):
    resp = await snake_post(request)
    body = resp.body.decode("utf-8")
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        try:
            p = json.loads(body)
            if p.get("id") is None and not p.get("error"):
                return StreamingResponse(iter([]), status_code=200, media_type="text/event-stream")
        except:
            pass
        async def _s():
            yield f"event: message\ndata: {body}\n\n"
        return StreamingResponse(_s(), status_code=200, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})
    return resp


@router.get("/sse")
async def snake_sse(request: Request):
    import asyncio
    async def _s():
        # §DOCSFIX D6-631 (2026-10-16): the registry the client reached, never one fixed host (an operator may still name one)
        yield f"event: endpoint\ndata: {public_base_url(request)}/mcp/snake/rpc\n\n"
        yield f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'method': 'notifications/serverInfo', 'params': SNAKE_SERVER_INFO})}\n\n"
        try:
            while True:
                await asyncio.sleep(30)
                yield f"event: ping\ndata: {{}}\n\n"
        except:
            pass
    return StreamingResponse(_s(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@router.get("/tools")
async def snake_tools():
    return {"server": "RoboWars-Snake", "tools": SNAKE_TOOL_SCHEMAS, "total": len(SNAKE_TOOL_SCHEMAS)}


@router.get("/health")
async def snake_health():
    games = await _snake_games.avalues()
    return {"status": "ok", "server": "RoboWars-Snake", "active_games": sum(1 for g in games if not g.finished), "total_games": len(games)}


@router.get("/games")
async def list_snake_games():
    games = []
    for gid, g in await _snake_games.aitems():
        w = g.snakes.get(g.winner)
        games.append({"match_id": gid, "snakes": len(g.snakes), "turn": g.turn, "finished": g.finished, "winner": w.name if w else None, "snake_names": [s.name for s in g.snakes.values()]})
    return {"games": games}


@router.get("/games/{game_id}")
async def get_snake_game(game_id: str):
    game = await _snake_games.aget(game_id)
    if not game:
        return JSONResponse(status_code=404, content={"error": "Not found"})

    # Auto-advance if game is active and no human has acted recently
    # This makes bot-only games and spectator-watched games play themselves
    if game.started and not game.finished:
        _advance_snake_turn(game)
        await _snake_games.aset(game_id, game)

    return {"state": game.get_spectator_state(), "walls": game.get_walls()}
