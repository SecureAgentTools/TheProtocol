"""
Game result persistence — async writes to game_results table.
Non-blocking: failures are logged, never delay gameplay.
"""

import logging
from typing import Dict, List, Optional, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def persist_game_results(results: List[Dict[str, Any]]) -> bool:
    """
    Persist a batch of game results to the database.
    Non-blocking — errors are logged, not raised.

    Each result dict:
      match_id, game_type, agent_did (nullable), agent_name,
      score, placement (nullable), turns, stats (dict), is_bot
    """
    if not results:
        return True

    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                for r in results:
                    await session.execute(text("""
                        INSERT INTO game_results (match_id, game_type, agent_did, agent_name, score, placement, turns, stats, is_bot)
                        VALUES (:match_id, :game_type, :agent_did, :agent_name, :score, :placement, :turns, :stats::jsonb, :is_bot)
                        ON CONFLICT DO NOTHING
                    """), {
                        "match_id": r["match_id"],
                        "game_type": r["game_type"],
                        "agent_did": r.get("agent_did"),
                        "agent_name": r["agent_name"],
                        "score": r.get("score", 0),
                        "placement": r.get("placement"),
                        "turns": r.get("turns", 0),
                        "stats": __import__("json").dumps(r.get("stats", {})),
                        "is_bot": r.get("is_bot", False),
                    })
        logger.info(f"[GamePersist] Saved {len(results)} results for {results[0]['match_id']}")
        return True
    except Exception as e:
        logger.error(f"[GamePersist] Failed to save results: {e}")
        return False


async def get_leaderboard(game_type: str, limit: int = 20) -> List[Dict]:
    """Get top scores for a game type."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("""
                SELECT agent_name, agent_did, score, turns, stats, match_id, is_bot, created_at
                FROM game_results
                WHERE game_type = :game_type AND is_bot = FALSE
                ORDER BY score DESC
                LIMIT :limit
            """), {"game_type": game_type, "limit": limit})
            rows = result.fetchall()
            return [
                {
                    "agent_name": r[0], "agent_did": r[1], "score": r[2],
                    "turns": r[3], "stats": r[4], "match_id": r[5],
                    "is_bot": r[6], "created_at": r[7].isoformat() if r[7] else None,
                }
                for r in rows
            ]
    except Exception as e:
        logger.error(f"[GamePersist] Leaderboard query failed: {e}")
        return []


async def get_agent_game_stats(agent_did: str) -> Dict:
    """Get aggregate game stats for an agent."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("""
                SELECT game_type, COUNT(*) as games, SUM(score) as total_score,
                       MAX(score) as best_score, COUNT(*) FILTER (WHERE placement = 1) as wins
                FROM game_results
                WHERE agent_did = :agent_did AND is_bot = FALSE
                GROUP BY game_type
            """), {"agent_did": agent_did})
            rows = result.fetchall()
            stats = {}
            for r in rows:
                stats[r[0]] = {
                    "games": r[1], "total_score": r[2],
                    "best_score": r[3], "wins": r[4],
                }
            return stats
    except Exception as e:
        logger.error(f"[GamePersist] Agent stats query failed: {e}")
        return {}


def resolve_agent_did(player_id: Optional[str]) -> Optional[str]:
    """D6-629: the DID a game result links to: the player the call acts as, when that player is an agent.

    Since D6-633 a game server takes its player from a verified agent token of this registry in the Authorization header
    (player_identity.resolve_player_id): the player id is that agent's DID, or the shared anonymous player, which links
    nothing. This used to decode a token passed in the tool's arguments with a key the registry's settings do not define,
    and look for claims its agent tokens do not carry, so no result was ever linked. Never raises.
    """
    from .player_identity import ANONYMOUS_PLAYER
    pid = str(player_id or "").strip()
    if not pid or pid == ANONYMOUS_PLAYER or not pid.startswith("did:"):
        return None
    return pid
