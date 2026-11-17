"""V0664 (order gwo_5374cd3a0eed96d787c4f813): this registry tells its Directory when its own card epoch moves, so the
index reads the card again at once instead of at its next cycle (the push half of Directory freshness; the Directory's
POST /push/card-changed, stack 98488854).

The epoch is the card's own serve etag (registry_card_builder.compute_serve_etag: the operator's edits and every coarse
epoch the card carries, the policy, the catalog, solvency, the market, the jurisdiction, the licence), so a leader reads
it every DIRECTORY_PUSH_INTERVAL seconds (60) and pushes only when it moved; an admin's card edit nudges at once.
The push carries the registry's federation name and the epoch, nothing else; the Directory reads the card from the
address it already holds. It goes to DIRECTORY_MTLS_URL over the read path's own client (routers/public_directory:
the SVID, the target the operator sets; core/outbound_guard leaves operator-set addresses to their own clients).

Best effort: no Directory named, nothing; an epoch the Directory took is not pushed again; a refusal (5xx) or no
answer is tried on the next tick; a Directory that does not know this registry (404, its crawl has not reached it) is
not asked every minute. A failure is counted (registry_directory_push_total{outcome}) and logged, never raised, and the
card write never waits for it. Reads only from the database; moves no money. Off switch: DIRECTORY_PUSH_ENABLED=false.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

ENABLED = (os.getenv("DIRECTORY_PUSH_ENABLED", "true") or "true").strip().lower() not in ("0", "false", "no", "off")
INTERVAL = max(15.0, float(os.getenv("DIRECTORY_PUSH_INTERVAL", "60")))
TIMEOUT = float(os.getenv("DIRECTORY_PUSH_TIMEOUT_S", "5"))
LAST_KEY = "registry:directory_push:last_epoch"

try:  # pragma: no cover - import guard, as elsewhere in this codebase
    from prometheus_client import Counter as _Counter

    PUSH_TOTAL = _Counter("registry_directory_push_total",
                          "This registry's pushes of a new card epoch to its Directory, by outcome", ["outcome"])
except Exception:  # pragma: no cover - metrics never decide a push
    PUSH_TOTAL = None


def _count(outcome: str) -> None:
    if PUSH_TOTAL is not None:
        try:
            PUSH_TOTAL.labels(outcome=outcome.split(":", 1)[0]).inc()
        except Exception:  # noqa: BLE001
            pass


class _RedisMemo:
    """The last epoch the Directory took, shared by every worker (Redis); kept in-process when Redis is absent."""
    _local: Optional[str] = None

    async def get(self) -> Optional[str]:
        try:
            from .leader import get_redis
            r = await get_redis()
            if r is not None:
                v = await r.get(LAST_KEY)
                return v.decode() if isinstance(v, bytes) else v
        except Exception:  # noqa: BLE001
            pass
        return _RedisMemo._local

    async def set(self, value: str) -> None:
        _RedisMemo._local = value
        try:
            from .leader import get_redis
            r = await get_redis()
            if r is not None:
                await r.set(LAST_KEY, value, ex=7 * 86400)
        except Exception:  # noqa: BLE001
            pass


async def _read_epoch() -> Tuple[str, str]:
    """This registry's federation name and its card's current serve etag."""
    from agentvault_registry.database import get_db_context
    from agentvault_registry.services.registry_card_builder import compute_serve_etag, federation_name
    async with get_db_context() as db:
        return federation_name(), await compute_serve_etag(db)


def _client(url: str) -> httpx.AsyncClient:
    from agentvault_registry.routers.public_directory import _client_kwargs
    kwargs = _client_kwargs(url)
    kwargs["timeout"] = TIMEOUT
    return httpx.AsyncClient(**kwargs)


async def push_once(*, read_epoch: Optional[Callable[[], Awaitable[Tuple[str, str]]]] = None, memo: Any = None,
                    client_factory: Optional[Callable[[str], httpx.AsyncClient]] = None) -> str:
    """One check: push the card epoch when it moved since the Directory last took one. Never raises; answers
    pushed, unchanged, no_directory, no_epoch, unknown_to_directory, refused:<status> or failed."""
    from agentvault_registry.routers.public_directory import _upstream
    url = _upstream()
    if not url:
        return "no_directory"
    memo = memo or _RedisMemo()
    try:
        name, etag = await (read_epoch or _read_epoch)()
    except Exception as e:  # noqa: BLE001
        logger.warning("[directory-push] the card epoch could not be read: %s", e)
        _count("no_epoch")
        return "no_epoch"
    if not etag or not name:
        return "no_epoch"
    if etag == await memo.get():
        return "unchanged"
    try:
        async with (client_factory or _client)(url) as client:
            r = await client.post(f"{url}/push/card-changed", json={"registry": name, "card_etag": etag})
    except Exception as e:  # noqa: BLE001
        logger.warning("[directory-push] the Directory at %s did not answer: %s: %s", url, type(e).__name__, e)
        _count("failed")
        return "failed"
    if 200 <= r.status_code < 300:
        await memo.set(etag)
        _count("pushed")
        logger.info("[directory-push] told the Directory the card epoch moved (%s)", etag[:20])
        return "pushed"
    if r.status_code == 404:
        await memo.set(etag)   # its crawl has not reached this registry: it will read the card then; no push every tick
        _count("unknown_to_directory")
        return "unknown_to_directory"
    _count(f"refused:{r.status_code}")
    logger.warning("[directory-push] the Directory answered %s; tried again next tick", r.status_code)
    return f"refused:{r.status_code}"


def nudge() -> None:
    """After a card write commits: push now, in a task of its own. Returns at once; never raises; the write never waits."""
    if not ENABLED:
        return
    try:
        asyncio.get_running_loop().create_task(push_once())
    except Exception as e:  # noqa: BLE001
        logger.debug("[directory-push] nudge skipped: %s", e)


async def start_directory_push() -> None:
    """Long-running coroutine: leader-elected, every INTERVAL seconds."""
    if not ENABLED:
        logger.info("[directory-push] disabled (DIRECTORY_PUSH_ENABLED=false)")
        return
    from .leader import run_with_leadership
    await asyncio.sleep(30)   # let the database pool and the card settle after boot
    try:
        async for _ in run_with_leadership("directory_push", interval=INTERVAL):
            out = await push_once()
            if out not in ("unchanged", "no_directory"):
                logger.info("[directory-push] %s", out)
    except asyncio.CancelledError:
        logger.info("[directory-push] stopped (cancellation)")
        raise
