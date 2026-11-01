"""§OURSTATE-3b — the host's delivery worker for federated chat.

One leader drains `chat_federation_outbox`: POST each queued envelope to the
resident registry, mark delivered, or back off. That is the whole job.

Three properties it is built for, each earned somewhere in this project:

  * SINGLE WRITER. `try_acquire_leadership` ACQUIRES (the §BRIDGE R7-B lesson:
    `is_leader()` does not, and a task that gates on it runs forever without
    ever running once). Two workers delivering the same row would double-post,
    which the receiver would dedup — but "correct because someone else cleans
    up" is not a design.
  * IT SAYS WHAT IT DID. Every cycle logs considered/delivered/failed, and the
    counters are readable through the admin status endpoint. A delivery worker
    whose only signal is silence cannot be distinguished from one that never
    started.
  * IT GIVES UP LOUDLY. After MAX_ATTEMPTS a row stops being retried and stays
    in the table with its last error — visible, diagnosable, and not silently
    dropped. A dead peer costs one row, not an infinite loop.

Δ-irrelevant: it moves messages, never value.
"""
import asyncio
import logging
import os

from ..database import AsyncSessionLocal as async_session_factory
from ..services import chat_federation as fed

logger = logging.getLogger(__name__)

CYCLE_SECONDS = int(os.getenv("CHAT_FEDERATION_OUTBOX_INTERVAL", "20"))
# V0652 (q) gwo_1939f34c31a297ffdd56c51c: between cycles the LEADER looks for a due row this often (one indexed probe,
# ix_chat_fed_outbox_due) and drains at once when it finds one. The nightly nt261101 measured the host's cycles 40 s
# apart (the 20 s sleep plus a drain under load): a message queued just after a cycle waited up to 40 s before it left,
# and the federation suite's 45 s window (chat_g1, the owner's hook on the other registry) heard it late. Still one
# writer: only the leader probes and drains; the others keep sleeping the whole cycle.
DUE_POLL_SECONDS = float(os.getenv("CHAT_FEDERATION_OUTBOX_POLL", "1"))

_running = False

# The cycle summary lives in REDIS, not in module memory. This registry runs 32
# gunicorn workers: the leader that drains the outbox is ONE of them, so a
# status request served by any other worker would read its own untouched zeros
# and report "never ran" about a worker that is running fine. That is the
# per-worker-dict class this project has now met three times (the showcase
# relay limiter, the §POCKETBRIDGE3 alert state, this). Shared state goes in
# the shared store.
STATS_KEY = "chatfed:outbox:last_cycle"


async def _publish_stats(out: dict) -> None:
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
        logger.debug("[CHATFED] could not publish outbox stats: %s", e)


async def outbox_stats() -> dict:
    """What the last cycle actually did, read from the shared store.

    `cycles: 0` means it has never run — a different fact from "nothing to
    deliver", and the two must never look the same. When Redis cannot answer we
    say `unknown`, because reporting zeros we did not measure would be the same
    lie in a different costume."""
    import json
    try:
        from .leader import get_redis
        r = await get_redis()
        if r is None:
            return {"cycles": None, "note": "no shared store — worker state unknown"}
        raw = await r.get(STATS_KEY)
        if not raw:
            return {"cycles": 0, "considered": 0, "delivered": 0, "failed": 0, "at": None}
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return {"cycles": None, "note": f"worker state unreadable: {type(e).__name__}"}


async def _drain_once() -> None:
    async with async_session_factory() as db:
        out = await fed.drain_outbox(db)
    await _publish_stats(out)
    if out["considered"]:
        logger.info("[CHATFED] outbox: considered=%s delivered=%s failed=%s",
                    out["considered"], out["delivered"], out["failed"])


async def _due_rows() -> bool:
    """Whether a queued row is due now (the drain's own condition, through ix_chat_fed_outbox_due)."""
    from sqlalchemy import text as sa_text
    async with async_session_factory() as db:
        return (await db.execute(sa_text(
            "SELECT 1 FROM chat_federation_outbox WHERE delivered_at IS NULL AND next_attempt_at <= now() "
            "AND attempts < :m LIMIT 1"), {"m": fed.MAX_ATTEMPTS})).first() is not None


async def _rest(seconds: float, may_wake: bool) -> None:
    """The pause between cycles. A worker that is not the leader sleeps it whole; the leader ends it as soon as a row
    is due (a message just queued for another registry), so delivery waits about a second, not a cycle."""
    if not may_wake or DUE_POLL_SECONDS <= 0:
        await asyncio.sleep(seconds)
        return
    loop = asyncio.get_running_loop()
    end = loop.time() + seconds
    while _running and loop.time() < end:
        await asyncio.sleep(min(DUE_POLL_SECONDS, max(0.0, end - loop.time())))
        try:
            if await _due_rows():
                return
        except Exception as e:  # noqa: BLE001 — a probe that fails costs the cycle's ordinary wait, nothing else
            logger.debug("[CHATFED] outbox due-probe failed: %s", e)
            await asyncio.sleep(max(0.0, end - loop.time()))
            return


async def chat_federation_outbox_loop():
    from .leader import try_acquire_leadership
    global _running
    _running = True
    if not fed.federation_enabled():
        logger.info("[CHATFED] outbox worker idle — CHAT_FEDERATION_ENABLED is off")
        return
    logger.info("[CHATFED] outbox worker started (%ds cycle)", CYCLE_SECONDS)
    from . import vitals as _vitals
    await _vitals.register("chat_federation_outbox", module=__name__,
                           pattern="hand-rolled", interval_sec=CYCLE_SECONDS,
                           enabled=fed.federation_enabled())
    while _running:
        # the rest may end early only after a cycle the leader drained cleanly: a cycle that raised waits the whole
        # cycle, so a failing database costs one error line a cycle, never one a second
        woke = False
        try:
            if await try_acquire_leadership("chat_federation_outbox"):
                async with _vitals.cycle("chat_federation_outbox"):
                    await _drain_once()
                woke = True
        except Exception:
            logger.error("[CHATFED] outbox cycle error", exc_info=True)
        await _rest(CYCLE_SECONDS, woke)


def stop_chat_federation_outbox():
    global _running
    _running = False
