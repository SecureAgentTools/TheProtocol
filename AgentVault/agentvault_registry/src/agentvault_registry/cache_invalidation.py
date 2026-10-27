"""
Cache invalidation via Redis Pub/Sub.

Per-uvicorn-worker module-level caches (`_emission_policy_cache` etc.) only
land mutations on ONE worker. Other workers self-heal at TTL but can serve
stale views for up to TTL seconds — visible as the "block 4× to cover all
workers" hack in flow_blocklist_enforcement.

This module gives writers a one-call invalidation primitive and readers a
background subscriber that drops the local copy when an invalidation
message arrives, so the next access triggers a refresh.

Pattern:
  # On admin write that changes ground truth:
  await publish_invalidation("emission_policy")

  # In each worker's startup wiring:
  start_invalidation_listener("emission_policy", on_invalidate=lambda: drop_my_cache())

Channels are namespaced per registry instance using REGISTRY_NAME so prod
and sandbox sharing the same Redis don't cross-contaminate.

Idempotent + best-effort: if Redis is down, publish silently no-ops, the
listener reconnects, and TTL-based refresh is the safety net.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)


def _channel_prefix() -> str:
    """Namespace channel names by registry instance."""
    name = os.getenv("REGISTRY_NAME", "default").lower().replace(" ", "-")
    return f"cache_invalidate:{name}"


def channel_name(cache_name: str) -> str:
    """Public — return the full channel name for a cache."""
    return f"{_channel_prefix()}:{cache_name}"


# Track active listener tasks per cache_name so start_listener is idempotent
_listener_tasks: Dict[str, asyncio.Task] = {}


async def publish_invalidation(cache_name: str) -> bool:
    """Publish an invalidation message to all workers subscribed to `cache_name`.

    Returns True on successful publish, False if Redis was unreachable or any
    other transient failure (best-effort — caller should not block on this).
    The TTL-based refresh on each cache is the safety net.
    """
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            logger.debug(
                f"[CacheInvalidate] Redis unavailable, skipping publish for {cache_name}"
            )
            return False
        channel = channel_name(cache_name)
        recipients = await r.publish(channel, "invalidate")
        logger.info(
            f"[CacheInvalidate] Published {cache_name} invalidation "
            f"(channel={channel}, recipients={recipients})"
        )
        return True
    except Exception as e:
        logger.warning(
            f"[CacheInvalidate] Failed to publish {cache_name} invalidation: {e}"
        )
        return False


async def _listen_loop(cache_name: str, on_invalidate: Callable[[], Awaitable[None]]):
    """Background task: subscribe and drive `on_invalidate` for each message.

    Reconnects on transient failure with exponential-ish backoff. Cleanly
    exits on CancelledError.
    """
    from agentvault_registry.background_tasks.leader import get_redis
    from agentvault_registry.services.pubsub_backoff import jittered
    backoff = 1.0
    channel = channel_name(cache_name)

    while True:
        try:
            r = await get_redis()
            if r is None:
                # Redis offline; wait and retry. TTL-refresh is the safety net.
                await asyncio.sleep(jittered(backoff))
                backoff = min(backoff * 2, 30.0)
                continue
            backoff = 1.0

            pubsub = r.pubsub()
            try:
                await pubsub.subscribe(channel)
                logger.info(
                    f"[CacheInvalidate] Listener subscribed to {channel}"
                )

                async for message in pubsub.listen():
                    if message is None:
                        continue
                    if message.get("type") != "message":
                        continue  # Skip subscribe-ack and pattern messages
                    try:
                        await on_invalidate()
                        logger.info(
                            f"[CacheInvalidate] Drop applied for {cache_name}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"[CacheInvalidate] on_invalidate raised for {cache_name}: {e}"
                        )
            finally:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.aclose()
                except Exception:
                    pass

        except asyncio.CancelledError:
            logger.info(f"[CacheInvalidate] Listener for {cache_name} cancelled")
            raise
        except Exception as e:
            # Jittered — an un-jittered retry put every worker back on the wire together.
            wait = jittered(backoff)
            logger.warning(
                f"[CacheInvalidate] Listener error for {cache_name}: {e} "
                f"— reconnecting in {wait:.2f}s (ceiling {backoff}s)"
            )
            await asyncio.sleep(wait)
            backoff = min(backoff * 2, 30.0)


def start_invalidation_listener(
    cache_name: str,
    on_invalidate: Callable[[], Awaitable[None]],
) -> Optional[asyncio.Task]:
    """Start a background task that subscribes to the cache's invalidation
    channel and runs `on_invalidate()` when a message arrives. Idempotent —
    second call for the same cache_name is a no-op.

    Returns the started Task, or the existing one if already running. Safe
    to call from FastAPI startup hook on every worker.
    """
    existing = _listener_tasks.get(cache_name)
    if existing is not None and not existing.done():
        return existing
    task = asyncio.create_task(
        _listen_loop(cache_name, on_invalidate),
        name=f"cache_invalidation:{cache_name}",
    )
    _listener_tasks[cache_name] = task
    return task


async def stop_invalidation_listener(cache_name: str) -> None:
    """Cancel the background listener for `cache_name` if running."""
    task = _listener_tasks.pop(cache_name, None)
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


async def stop_all_listeners() -> None:
    """Cancel every running invalidation listener (shutdown hook)."""
    names = list(_listener_tasks.keys())
    for name in names:
        await stop_invalidation_listener(name)
