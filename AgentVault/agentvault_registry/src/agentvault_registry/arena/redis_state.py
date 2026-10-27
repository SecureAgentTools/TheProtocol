"""
Redis-backed state for Arena games.

Provides two primitives:
1. RedisStringMap - simple string->string mapping (agent_to_game, agent_to_match)
2. GameRegistry - tracks which games exist and which worker owns them

Game engine objects stay in local memory (too complex to serialize).
Redis provides cross-worker visibility so requests can be routed correctly.
"""
import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Worker ID and Redis connection from leader module
try:
    from ..background_tasks.leader import WORKER_ID, get_redis
except ImportError:
    WORKER_ID = f"worker-{os.getpid()}"

    async def get_redis():
        return None


class RedisStringMap:
    """
    A dict-like object backed by a Redis hash.
    Falls back to local dict if Redis unavailable.

    Used for simple string->string mappings like agent_to_game.

    Sync access (.get(), [], del, in, len, keys, values, items) uses the local
    cache only -- no blocking I/O. Call the async variants (aget, aset, adel)
    to sync with Redis when inside an async context.
    """

    def __init__(self, name: str):
        self.name = name
        self._local: Dict[str, str] = {}
        self._redis_key = f"arena:{name}"

    # ---- async Redis helpers ------------------------------------------------

    async def _redis(self):
        try:
            return await get_redis()
        except Exception:
            return None

    # ---- sync dict-like interface (local cache only) ------------------------

    def get(self, key: str, default=None) -> Optional[str]:
        """Sync get from local cache."""
        return self._local.get(key, default)

    def __getitem__(self, key: str) -> str:
        return self._local[key]

    def __setitem__(self, key: str, value: str):
        """Sync set to local cache. Call aset() for Redis sync."""
        self._local[key] = value

    def __delitem__(self, key: str):
        """Sync delete from local."""
        self._local.pop(key, None)

    def __contains__(self, key: str) -> bool:
        return key in self._local

    def __len__(self):
        return len(self._local)

    def keys(self):
        return self._local.keys()

    def values(self):
        return self._local.values()

    def items(self):
        return self._local.items()

    def pop(self, key: str, *args):
        """dict.pop() compatible."""
        return self._local.pop(key, *args)

    def __iter__(self):
        return iter(self._local)

    # ---- async interface (syncs with Redis) ---------------------------------

    async def aget(self, key: str, default=None) -> Optional[str]:
        """Async get -- checks Redis first, falls back to local."""
        r = await self._redis()
        if r:
            try:
                val = await r.hget(self._redis_key, key)
                if val is not None:
                    self._local[key] = val
                    return val
            except Exception:
                pass
        return self._local.get(key, default)

    async def aset(self, key: str, value: str):
        """Async set to both local and Redis."""
        self._local[key] = value
        r = await self._redis()
        if r:
            try:
                await r.hset(self._redis_key, key, value)
            except Exception:
                pass

    async def adel(self, key: str):
        """Async delete from both local and Redis."""
        self._local.pop(key, None)
        r = await self._redis()
        if r:
            try:
                await r.hdel(self._redis_key, key)
            except Exception:
                pass


class GameRegistry:
    """
    Tracks game existence across workers via Redis.

    Each game is registered with:
    - game_id -> {worker_id, game_type, status, created_at, players}

    Game engine objects stay in local memory on the creating worker.
    Other workers can see games exist but can't access the engine.
    """

    def __init__(self):
        self._redis_key = "arena:games"

    async def _get_redis(self):
        try:
            return await get_redis()
        except Exception:
            return None

    async def register_game(self, game_id: str, game_type: str, players: list = None):
        """Register a new game in Redis."""
        r = await self._get_redis()
        if not r:
            return
        try:
            data = json.dumps({
                "worker_id": WORKER_ID,
                "game_type": game_type,
                "status": "active",
                "created_at": time.time(),
                "players": players or [],
            })
            await r.hset(self._redis_key, game_id, data)
        except Exception as e:
            logger.debug(f"[GameRegistry] Failed to register {game_id}: {e}")

    async def update_status(self, game_id: str, status: str):
        """Update game status (active, finished, expired)."""
        r = await self._get_redis()
        if not r:
            return
        try:
            raw = await r.hget(self._redis_key, game_id)
            if raw:
                data = json.loads(raw)
                data["status"] = status
                await r.hset(self._redis_key, game_id, json.dumps(data))
        except Exception:
            pass

    async def unregister_game(self, game_id: str):
        """Remove game from registry."""
        r = await self._get_redis()
        if not r:
            return
        try:
            await r.hdel(self._redis_key, game_id)
        except Exception:
            pass

    async def get_game_info(self, game_id: str) -> Optional[dict]:
        """Get game info from Redis."""
        r = await self._get_redis()
        if not r:
            return None
        try:
            raw = await r.hget(self._redis_key, game_id)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def is_local(self, game_id: str) -> bool:
        """Check if this game is owned by this worker."""
        info = await self.get_game_info(game_id)
        if not info:
            return True  # No Redis info = assume local (single-worker mode)
        return info.get("worker_id") == WORKER_ID

    async def cleanup_old(self, max_age: float = 7200):
        """Remove games older than max_age seconds."""
        r = await self._get_redis()
        if not r:
            return
        try:
            all_games = await r.hgetall(self._redis_key)
            now = time.time()
            for game_id, raw in all_games.items():
                data = json.loads(raw)
                if now - data.get("created_at", 0) > max_age:
                    await r.hdel(self._redis_key, game_id)
        except Exception:
            pass


# Singletons
game_registry = GameRegistry()
