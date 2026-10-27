"""§OURSTATE-6 — the retention sweeper: the half of a timer that makes it true.

A disappearing timer that only hides messages in a client is a claim, not a
mechanism. This deletes them, on the server, on a schedule, and reports what it
did — so "messages here disappear after 24 hours" is a statement about the
database rather than about a stylesheet.

Three properties, each earned somewhere in this project:

  * **Single writer.** `try_acquire_leadership` ACQUIRES (§BRIDGE R7-B: the
    `is_leader()` docstring says it does not, and a task gating on it runs
    forever without ever running once).
  * **It says what it did.** Cycle counters live in REDIS, not module memory —
    this registry runs 32 gunicorn workers and a status read served by any
    other one would report zeros about a worker that is running fine
    (§OURSTATE-3b, the same lesson, third time).
  * **It never deletes more than it was told to.** The window comes from the
    conversation row; a thread with `retention_hours IS NULL` is not visited at
    all, and the DELETE is bounded per cycle so a huge backlog degrades into
    several quiet cycles rather than one long lock.

Δ-irrelevant: it removes conversation text and never touches a balance, a
receipt row, or the ledger those receipts point at.
"""
import asyncio
import logging
import os

from sqlalchemy import text as sa_text

from ..database import AsyncSessionLocal as async_session_factory

logger = logging.getLogger(__name__)

CYCLE_SECONDS = int(os.getenv("CHAT_RETENTION_INTERVAL", "900"))     # 15 min
BATCH = int(os.getenv("CHAT_RETENTION_BATCH", "2000"))
STATS_KEY = "chat:retention:last_cycle"

_running = False


async def sweep_once() -> dict:
    """Delete every message older than its own thread's window. Returns counts."""
    async with async_session_factory() as db:
        res = await db.execute(sa_text("""
            WITH doomed AS (
                SELECT m.id
                FROM chat_messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE c.retention_hours IS NOT NULL
                  AND m.created_at < now() - (c.retention_hours || ' hours')::interval
                LIMIT :batch
            )
            DELETE FROM chat_messages WHERE id IN (SELECT id FROM doomed)
            RETURNING conversation_id
        """), {"batch": BATCH})
        rows = res.fetchall()
        await db.commit()
    return {"deleted": len(rows), "threads": len({r[0] for r in rows})}


async def _publish(out: dict) -> None:
    import datetime
    import json
    payload = dict(out)
    payload["at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        from .leader import get_redis
        r = await get_redis()
        if r is None:
            return
        prev = await r.get(STATS_KEY)
        cycles = 0
        if prev:
            try:
                cycles = int(json.loads(prev).get("cycles") or 0)
            except Exception:  # noqa: BLE001
                cycles = 0
        payload["cycles"] = cycles + 1
        await r.set(STATS_KEY, json.dumps(payload), ex=86400)
    except Exception as e:  # noqa: BLE001
        logger.debug("[CHATRET] could not publish sweep stats: %s", e)


async def retention_stats() -> dict:
    """What the last sweep did. `cycles: None` means the shared store could not
    answer — which is a different fact from "it never ran", and reporting zeros
    we did not measure would be the same lie in a different costume."""
    import json
    try:
        from .leader import get_redis
        r = await get_redis()
        if r is None:
            return {"cycles": None, "note": "no shared store — sweeper state unknown"}
        raw = await r.get(STATS_KEY)
        if not raw:
            return {"cycles": 0, "deleted": 0, "threads": 0, "at": None}
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return {"cycles": None, "note": f"sweeper state unreadable: {type(e).__name__}"}


async def chat_retention_loop():
    from .leader import try_acquire_leadership
    global _running
    _running = True
    logger.info("[CHATRET] retention sweeper started (%ds cycle, batch %d)",
                CYCLE_SECONDS, BATCH)
    from . import vitals as _vitals
    await _vitals.register("chat_retention_sweeper", module=__name__,
                           pattern="hand-rolled", interval_sec=CYCLE_SECONDS, enabled=True)
    while _running:
        try:
            if await try_acquire_leadership("chat_retention_sweeper"):
                async with _vitals.cycle("chat_retention_sweeper") as _ctx:
                    out = await sweep_once()
                    _ctx.note(**{k: out[k] for k in ("deleted", "threads") if k in out})
                    await _publish(out)
                if out["deleted"]:
                    logger.info("[CHATRET] swept %s message(s) across %s thread(s)",
                                out["deleted"], out["threads"])
        except Exception:
            logger.error("[CHATRET] sweep cycle error", exc_info=True)
        await asyncio.sleep(CYCLE_SECONDS)


def stop_chat_retention():
    global _running
    _running = False
