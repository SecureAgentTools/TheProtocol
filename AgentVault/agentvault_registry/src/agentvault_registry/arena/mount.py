"""V0666 the games switch: the ONE place the six game routers are mounted (main.py calls mount_games(app)).

On (GAMES_ENABLED, core/games.py; the default) it mounts what main.py mounted before V0666: the Robo Wars MCP server
(/mcp/arena), its spectator API (/api/v1/arena/*), Tower Defense (/mcp/td), Snake (/mcp/snake), Market Mayhem
(/mcp/trading) and the lobby (/mcp/lobby). Off, nothing is added: every game path is an unknown route, and the game loops
(the lobby's countdown task, the games' result writers) never start, since only those routers start them.
"""
from __future__ import annotations

from fastapi import FastAPI

from ..core.games import games_enabled


def mount_games(app: FastAPI) -> bool:
    """Mounts the six game routers when the switch is on and says whether it did."""
    if not games_enabled():
        return False
    from .lobby_mcp_server import router as lobby_mcp_router
    from .mcp_server import router as arena_mcp_router
    from .snake_mcp_server import router as snake_mcp_router
    from .spectator import router as arena_spectator_router
    from .td_mcp_server import router as td_mcp_router
    from .trading_mcp_server import router as trading_mcp_router
    app.include_router(arena_mcp_router, prefix="/mcp/arena")
    app.include_router(arena_spectator_router)
    app.include_router(td_mcp_router, prefix="/mcp/td")
    app.include_router(snake_mcp_router, prefix="/mcp/snake")
    app.include_router(trading_mcp_router, prefix="/mcp/trading")
    app.include_router(lobby_mcp_router, prefix="/mcp/lobby")
    return True
