"""
Spectator API — WebSocket state broadcast + REST endpoints for arena frontend.
"""
import asyncio
import json
import logging
from typing import Dict, List, Set

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse

from .match_manager import match_manager
from .betting import betting_manager
from .redis_state import RedisStringMap
from .. import models
from ..security import require_admin_flag

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/arena", tags=["Arena Spectator"])

# Active WebSocket connections per match — stays local (WebSocket objects are not serializable)
_spectators: Dict[str, Set[WebSocket]] = {}


@router.get("/matches")
async def list_matches():
    """List all matches."""
    return {"matches": await match_manager.list_matches()}


@router.post("/matches")
async def create_match(
    mode: str = "battle_royale",
    max_agents: int = 6,
    add_bots: int = 5,
    admin: models.Developer = Depends(require_admin_flag("admin_platform")),
):
    """Create a new match filled with bots (admin/testing).

    D6-634 (2026-10-16): an administrator's call only (an admin, or the admin_platform flag, on a credential that
    may act as an admin). It answered anyone, with no credential at all, and every call started a match of bots
    on the registry's game workers. The MCP tool createArenaMatch forwards the caller's developer credential here.
    """
    total = min(7, max(2, add_bots))
    match = await match_manager.create_match(mode=mode, max_agents=total, min_agents=total)
    for _ in range(total):
        await match_manager.add_bot(match.match_id)
    return {
        "match_id": match.match_id,
        "mode": mode,
        "agents": len(match.game.agents),
        "started": match.game.started,
    }


@router.get("/matches/{match_id}")
async def get_match(match_id: str):
    """Get full match state (spectator view — no fog of war)."""
    match = await match_manager.get_match(match_id)
    if not match:
        return JSONResponse(status_code=404, content={"error": "Match not found"})
    return {
        "state": match.game.get_spectator_state(),
        "map": match.game.get_map_data(),
    }


@router.get("/matches/{match_id}/map")
async def get_map(match_id: str):
    """Get map data for rendering."""
    match = await match_manager.get_match(match_id)
    if not match:
        return JSONResponse(status_code=404, content={"error": "Match not found"})
    return {"map": match.game.get_map_data(), "size": 40}


@router.get("/matches/{match_id}/bets")
async def get_bets(match_id: str):
    """Get betting pool status for a match. Where arena betting is off (ARENA_BETTING_ENABLED, a retired surface, D8)
    the read is refused with the surface's own sentence (404, as a route that is not mounted)."""
    from agentvault_registry.core.legacy_surfaces import surface_enabled, retired_sentence
    if not surface_enabled("ARENA_BETTING_ENABLED"):
        return JSONResponse(status_code=404, content={"detail": retired_sentence("ARENA_BETTING_ENABLED")})
    status = betting_manager.get_pool_status(match_id)
    if not status:
        return {"match_id": match_id, "total_pool": 0, "bets": [], "odds": {}}
    return status


@router.websocket("/ws/{match_id}")
async def spectator_ws(websocket: WebSocket, match_id: str):
    """WebSocket for live spectator updates."""
    await websocket.accept()

    if match_id not in _spectators:
        _spectators[match_id] = set()
    _spectators[match_id].add(websocket)

    logger.info(f"[Arena] Spectator connected to {match_id}")

    try:
        match = await match_manager.get_match(match_id)
        if match:
            # Send initial state
            await websocket.send_json({
                "type": "initial_state",
                "state": match.game.get_spectator_state(),
                "map": match.game.get_map_data(),
            })

        # Keep alive + push updates
        last_turn = 0
        while True:
            await asyncio.sleep(0.5)

            match = await match_manager.get_match(match_id)
            if not match:
                await websocket.send_json({"type": "match_not_found"})
                break

            # Force-advance timed out turns
            await match_manager.force_advance_turn(match_id)

            if match.game.turn > last_turn:
                last_turn = match.game.turn
                state = match.game.get_spectator_state()
                await websocket.send_json({"type": "turn_update", "state": state})

            if match.game.finished:
                await websocket.send_json({
                    "type": "match_end",
                    "state": match.game.get_spectator_state(),
                })
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"[Arena] Spectator WS error: {e}")
    finally:
        _spectators.get(match_id, set()).discard(websocket)
        logger.info(f"[Arena] Spectator disconnected from {match_id}")


# ── Leaderboards & Stats (from game_results DB) ──

@router.get("/leaderboard/{game_type}")
async def game_leaderboard(game_type: str, limit: int = 20):
    """Get all-time leaderboard for a game type."""
    from .game_persistence import get_leaderboard
    entries = await get_leaderboard(game_type, limit=min(limit, 100))
    return {"game_type": game_type, "leaderboard": entries}


@router.get("/agent-stats/{agent_did:path}")
async def agent_game_stats(agent_did: str):
    """Get aggregate game stats for an agent by DID."""
    from .game_persistence import get_agent_game_stats
    stats = await get_agent_game_stats(agent_did)
    return {"agent_did": agent_did, "stats": stats}
