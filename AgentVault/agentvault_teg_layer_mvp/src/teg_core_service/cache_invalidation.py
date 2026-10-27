"""
TEG cache invalidation via Redis Pub/Sub.

Mirror of the registry's `cache_invalidation.py`. Namespaced per TEG instance
so prod and sandbox sharing the same Redis don't cross-contaminate.

Pattern:
  # Writer (e.g., admin endpoint that mutates ground truth):
  await publish_invalidation("teg_emission_policy")

  # Reader (e.g., worker startup):
  start_invalidation_listener("teg_emission_policy", drop_my_cache)

Idempotent + best-effort. If Redis is down, publish silently no-ops, the
listener reconnects on a backoff, and TTL refresh is the safety net.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)


def _channel_prefix() -> str:
    """Namespace channel names by TEG instance. TEG_ID is the most stable
    identifier; falls back to TEG_NAME or 'default'."""
    name = (
        os.getenv("TEG_ID")
        or os.getenv("TEG_NAME")
        or "default"
    ).lower().replace(" ", "-")
    return f"teg_cache_invalidate:{name}"


def channel_name(cache_name: str) -> str:
    return f"{_channel_prefix()}:{cache_name}"


_listener_tasks: Dict[str, asyncio.Task] = {}


async def publish_invalidation(cache_name: str) -> bool:
    """Publish an invalidation message. Best-effort — Redis errors swallowed."""
    try:
        from .redis_client import get_redis
        r = await get_redis()
        if r is None:
            return False
        channel = channel_name(cache_name)
        recipients = await r.publish(channel, "invalidate")
        logger.info(
            f"[TEG-CacheInvalidate] Published {cache_name} "
            f"(channel={channel}, recipients={recipients})"
        )
        return True
    except Exception as e:
        logger.warning(f"[TEG-CacheInvalidate] Publish failed for {cache_name}: {e}")
        return False


async def _listen_loop(cache_name: str, on_invalidate: Callable[[], Awaitable[None]]):
    from .redis_client import get_redis
    backoff = 1.0
    channel = channel_name(cache_name)

    while True:
        try:
            r = await get_redis()
            if r is None:
                await asyncio.sleep(min(backoff, 30.0))
                backoff = min(backoff * 2, 30.0)
                continue
            backoff = 1.0

            pubsub = r.pubsub()
            try:
                await pubsub.subscribe(channel)
                logger.info(f"[TEG-CacheInvalidate] Listener subscribed to {channel}")

                async for message in pubsub.listen():
                    if message is None:
                        continue
                    if message.get("type") != "message":
                        continue
                    try:
                        await on_invalidate()
                        logger.info(f"[TEG-CacheInvalidate] Drop applied for {cache_name}")
                    except Exception as e:
                        logger.warning(
                            f"[TEG-CacheInvalidate] on_invalidate raised for {cache_name}: {e}"
                        )
            finally:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.aclose()
                except Exception:
                    pass

        except asyncio.CancelledError:
            logger.info(f"[TEG-CacheInvalidate] Listener for {cache_name} cancelled")
            raise
        except Exception as e:
            logger.warning(
                f"[TEG-CacheInvalidate] Listener error for {cache_name}: {e} "
                f"— reconnecting in {backoff}s"
            )
            await asyncio.sleep(min(backoff, 30.0))
            backoff = min(backoff * 2, 30.0)


def start_invalidation_listener(
    cache_name: str,
    on_invalidate: Callable[[], Awaitable[None]],
) -> Optional[asyncio.Task]:
    """Idempotent — second call for the same cache_name returns the existing
    task if still running."""
    existing = _listener_tasks.get(cache_name)
    if existing is not None and not existing.done():
        return existing
    task = asyncio.create_task(
        _listen_loop(cache_name, on_invalidate),
        name=f"teg_cache_invalidation:{cache_name}",
    )
    _listener_tasks[cache_name] = task
    return task


async def stop_invalidation_listener(cache_name: str) -> None:
    task = _listener_tasks.pop(cache_name, None)
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


async def stop_all_listeners() -> None:
    for name in list(_listener_tasks.keys()):
        await stop_invalidation_listener(name)
