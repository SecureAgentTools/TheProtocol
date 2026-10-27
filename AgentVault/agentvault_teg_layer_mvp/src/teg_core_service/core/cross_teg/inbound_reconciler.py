"""§SECFIX-15 (2026-09-25) — every inbound cross-TEG credit is checked against the source's own ledger record.

The receiving TEG credits the amount its caller states (the 2PC commit mints it; nothing on this side can see whether the
source debited anything). The source's registry records the transfer as a TokensTransferred event whose
data.transaction_id is the transfer id (idempotency key xfer-<id>) in its frame's event store. Every completed inbound
credit measured on 2026-09-25 came from the TEG's own trust domain (a frame and its operators), and an operator writes to
its parent's store, so the store this TEG already writes to holds the source's record: on EU, ASIA and the sandbox pair
the last 50 credits each (200) all found a TokensTransferred with the same amount, and an operator's TEG reads its parent's
store by transaction id with its own SVID (amsterdam, 200).

OBSERVE ONLY. Per completed target row, once its grace has passed:
    verified     the store holds a TokensTransferred for the id with the same amount
    mismatch     it holds one, with a different amount                        (ERROR, counted)
    unrecorded   it holds none after CROSS_TEG_INBOUND_RECONCILE_MAX_WAIT_SEC (ERROR, counted)
    unreachable  the store did not answer (WARNING, counted; asked again next cycle)
    skipped      the row names no source TEG (an async credit: its source is another frame's store)
Counter teg_cross_teg_inbound_reconcile_total{result}; nothing is reversed automatically. A final result is remembered in
Redis for three days (teg:xteg:reconciled:<teg>:<id>), so each credit is judged once.

    CROSS_TEG_INBOUND_RECONCILE_ENABLED       default true
    CROSS_TEG_INBOUND_RECONCILE_INTERVAL_SEC  default 600
    CROSS_TEG_INBOUND_RECONCILE_GRACE_SEC     default 300   (a credit younger than this is not asked about yet)
    CROSS_TEG_INBOUND_RECONCILE_MAX_WAIT_SEC  default 3600  (after this an absent record is final: unrecorded)
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

LEADER_KEY_PREFIX = "teg_inbound_reconciler"
DONE_TTL_SEC = 3 * 86400
BATCH = 200
_FINAL = ("verified", "mismatch", "unrecorded", "skipped")

try:
    from prometheus_client import Counter as _C

    INBOUND_RECONCILE_TOTAL = _C(
        "teg_cross_teg_inbound_reconcile_total",
        "Inbound cross-TEG credits checked against the source's TokensTransferred in this TEG's event store",
        ["result"],
    )
except Exception:  # pragma: no cover
    INBOUND_RECONCILE_TOTAL = None


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def enabled() -> bool:
    return (os.getenv("CROSS_TEG_INBOUND_RECONCILE_ENABLED") or "true").strip().lower() in ("1", "true", "yes", "on")


def classify(row_amount, events: List[Dict[str, Any]]) -> str:
    """verified | mismatch | missing, from the store's events for one transfer id (a pure function, tested alone)."""
    try:
        want = Decimal(str(row_amount))
    except (InvalidOperation, TypeError):
        return "mismatch"
    seen = []
    for e in events or []:
        if (e or {}).get("event_type") != "TokensTransferred":
            continue
        try:
            seen.append(Decimal(str(((e or {}).get("data") or {}).get("amount"))))
        except (InvalidOperation, TypeError):
            seen.append(None)
    if not seen:
        return "missing"
    return "verified" if any(a is not None and a == want for a in seen) else "mismatch"


def _teg_id() -> str:
    return (os.getenv("TEG_ID") or os.getenv("TEG_NAME") or "default").lower().replace(" ", "-")


def _count(result: str) -> None:
    if INBOUND_RECONCILE_TOTAL is not None:
        try:
            INBOUND_RECONCILE_TOTAL.labels(result=result).inc()
        except Exception:  # pragma: no cover
            pass


class InboundReconciler:
    def __init__(self):
        self.teg_id = _teg_id()
        self.interval = _env_int("CROSS_TEG_INBOUND_RECONCILE_INTERVAL_SEC", 600)
        self.grace = _env_int("CROSS_TEG_INBOUND_RECONCILE_GRACE_SEC", 300)
        self.max_wait = _env_int("CROSS_TEG_INBOUND_RECONCILE_MAX_WAIT_SEC", 3600)
        self.worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self.last: Dict[str, int] = {}
        self._unreachable_warned = False

    async def start(self) -> None:
        if not enabled():
            logger.info("[InboundReconcile] disabled via CROSS_TEG_INBOUND_RECONCILE_ENABLED")
            return
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._run_loop())
        logger.info(f"[InboundReconcile] starting (teg_id={self.teg_id}, interval={self.interval}s, grace={self.grace}s, "
                    f"max_wait={self.max_wait}s, worker={self.worker_id})")

    async def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def _redis(self):
        try:
            from ...redis_client import get_redis
            return await get_redis()
        except Exception:
            return None

    async def _acquire_leader(self, r) -> bool:
        # the lease outlives the sleep (a lease shorter than the sleep sets the cadence); the holder renews it each cycle
        lease = self.interval * 2 + 60
        key = f"{LEADER_KEY_PREFIX}:{self.teg_id}"
        try:
            cur = await r.get(key)
            if cur is None:
                return bool(await r.set(key, self.worker_id, ex=lease, nx=True))
            if cur == self.worker_id:
                await r.expire(key, lease)
                return True
        except Exception as e:
            logger.debug(f"[InboundReconcile] leader acquire failed: {e}")
        return False

    async def _run_loop(self) -> None:
        await asyncio.sleep(30)
        while self.running:
            try:
                r = await self._redis()
                if r is not None and await self._acquire_leader(r):
                    await self._cycle_once(r)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[InboundReconcile] cycle error: {e}", exc_info=True)
            await asyncio.sleep(self.interval)

    async def _rows(self) -> List[Any]:
        from sqlalchemy import text
        from ...database.db_session import AsyncSessionLocal
        if AsyncSessionLocal is None:
            return []
        sql = text("""
            SELECT transfer_id, amount, source_teg_id, completed_at,
                   EXTRACT(EPOCH FROM (now() - completed_at)) AS age
            FROM cross_teg_transfers
            WHERE role = 'target' AND status = 'COMPLETED'
              AND completed_at BETWEEN now() - interval '24 hours' AND now() - make_interval(secs => :grace)
            ORDER BY completed_at DESC
            LIMIT :lim
        """)
        async with AsyncSessionLocal() as db:
            return (await db.execute(sql, {"grace": self.grace, "lim": BATCH})).fetchall()

    async def _events(self, session, base: str, tid: str):
        async with session.get(f"{base}/api/v1/events/by-transaction/{tid}") as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
            return await resp.json()

    async def _cycle_once(self, r) -> None:
        import aiohttp
        try:
            from ...event_emitter import _svid_ssl_context
        except Exception:  # an import that cannot load leaves no client certificate: the store then refuses, counted
            def _svid_ssl_context():
                return None, 0.0
        base = (os.getenv("EVENT_STORE_URL") or "").rstrip("/")
        if not base:
            return
        rows = await self._rows()
        stats: Dict[str, int] = {}
        ctx, _ = _svid_ssl_context()
        connector = aiohttp.TCPConnector(ssl=ctx) if (ctx is not None and base.startswith("https")) else None
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            for tid, amount, source_teg, completed_at, age in rows:
                key = f"teg:xteg:reconciled:{self.teg_id}:{tid}"
                try:
                    if await r.get(key) in _FINAL:
                        continue
                except Exception:
                    pass
                if not source_teg or source_teg == "unknown":
                    result = "skipped"
                else:
                    try:
                        verdict = classify(amount, await self._events(session, base, tid))
                    except Exception as e:
                        verdict = "unreachable"
                        if not self._unreachable_warned:
                            logger.warning(f"[InboundReconcile] the store did not answer for {tid}: {e}")
                            self._unreachable_warned = True
                    if verdict == "missing":
                        result = "unrecorded" if float(age or 0) >= self.max_wait else "pending"
                    else:
                        result = verdict
                stats[result] = stats.get(result, 0) + 1
                if result == "pending":
                    continue
                _count(result)
                if result in ("mismatch", "unrecorded"):
                    logger.error(f"[InboundReconcile] {result.upper()}: transfer {tid} credited {amount} here from "
                                 f"{source_teg} at {completed_at}; the source's TokensTransferred in {base} "
                                 f"{'carries a different amount' if result == 'mismatch' else 'is absent'}")
                if result in _FINAL:
                    try:
                        await r.set(key, result, ex=DONE_TTL_SEC)
                    except Exception:
                        pass
        if stats.get("unreachable", 0) == 0:
            self._unreachable_warned = False
        self.last = stats
        if rows:
            logger.info(f"[InboundReconcile] cycle: {len(rows)} candidates · {stats}")


_reconciler: Optional[InboundReconciler] = None


async def start_inbound_reconciler() -> None:
    global _reconciler
    if _reconciler is None:
        _reconciler = InboundReconciler()
    await _reconciler.start()


async def stop_inbound_reconciler() -> None:
    if _reconciler is not None:
        await _reconciler.stop()
