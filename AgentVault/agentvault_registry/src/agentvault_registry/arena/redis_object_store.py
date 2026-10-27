"""
Redis-backed object store for arena game state.

Each game is serialized to JSON via engine-provided to_dict/from_dict codecs
and stored under `arena:{namespace}:{game_id}`. Every MCP tool call reads the
game out of Redis, mutates it in memory, and writes it back — so any of the
16 uvicorn workers can service any request without losing state.

Keys carry a 24h TTL (refreshed on every write) so abandoned games don't
accumulate. SET is atomic; last writer wins if two workers race on the same
game (a rare case in practice because each agent has exactly one game and
makes calls sequentially).
"""
import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from .redis_state import get_redis

logger = logging.getLogger(__name__)

DEFAULT_TTL = 86400  # 24 hours


class RedisObjectStore:
    """
    Async dict-like Redis-backed store keyed on game_id.

    Parameters
    ----------
    namespace:
        Namespace segment in the Redis key (e.g. "td_games").
    decode:
        Callable that takes the decoded JSON dict and returns a game object.
    encode:
        Callable that takes a game object and returns a JSON-serializable dict.
    ttl:
        Per-key TTL in seconds (default 24h). Refreshed on every aset().

    All methods are async and hit Redis directly — there is no local cache,
    because games mutate on every tool call and stale local copies would
    cause the exact bug this store is replacing.
    """

    def __init__(
        self,
        namespace: str,
        decode: Callable[[Dict[str, Any]], Any],
        encode: Callable[[Any], Dict[str, Any]],
        ttl: int = DEFAULT_TTL,
    ):
        self.namespace = namespace
        self._decode = decode
        self._encode = encode
        self._ttl = ttl
        self._prefix = f"arena:{namespace}:"

    def _key(self, game_id: str) -> str:
        return f"{self._prefix}{game_id}"

    async def _r(self):
        try:
            return await get_redis()
        except Exception:
            return None

    async def aget(self, game_id: str, default=None):
        r = await self._r()
        if not r:
            return default
        try:
            raw = await r.get(self._key(game_id))
            if raw is None:
                return default
            return self._decode(json.loads(raw))
        except Exception as e:
            logger.warning(f"[RedisObjectStore:{self.namespace}] decode failed for {game_id}: {e}")
            return default

    async def aset(self, game_id: str, value: Any):
        r = await self._r()
        if not r:
            logger.warning(f"[RedisObjectStore:{self.namespace}] Redis unavailable; dropping write for {game_id}")
            return
        try:
            payload = json.dumps(self._encode(value))
            await r.set(self._key(game_id), payload, ex=self._ttl)
        except Exception as e:
            logger.warning(f"[RedisObjectStore:{self.namespace}] encode/write failed for {game_id}: {e}")

    async def adel(self, game_id: str):
        r = await self._r()
        if not r:
            return
        try:
            await r.delete(self._key(game_id))
        except Exception:
            pass

    async def acontains(self, game_id: str) -> bool:
        r = await self._r()
        if not r:
            return False
        try:
            return bool(await r.exists(self._key(game_id)))
        except Exception:
            return False

    async def akeys(self) -> List[str]:
        r = await self._r()
        if not r:
            return []
        out: List[str] = []
        try:
            cursor = 0
            while True:
                cursor, batch = await r.scan(cursor, match=f"{self._prefix}*", count=100)
                for k in batch:
                    # redis.asyncio returns strings when decode_responses=True; guard otherwise
                    key = k.decode() if isinstance(k, (bytes, bytearray)) else k
                    out.append(key[len(self._prefix):])
                if cursor == 0:
                    break
        except Exception as e:
            logger.warning(f"[RedisObjectStore:{self.namespace}] scan failed: {e}")
        return out

    async def aitems(self) -> List[Tuple[str, Any]]:
        keys = await self.akeys()
        out: List[Tuple[str, Any]] = []
        for k in keys:
            v = await self.aget(k)
            if v is not None:
                out.append((k, v))
        return out

    async def avalues(self) -> List[Any]:
        return [v for _, v in await self.aitems()]
