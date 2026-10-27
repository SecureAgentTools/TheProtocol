"""
velocity_snapshot.py — Economic Engine Sprint 9

Hourly background task that queries EventStore for TokensTransferred events
(prior hour window) and writes/upserts VelocityMetrics rows per agent.

TransactionFeeService._get_velocity_index() reads the sender's latest row (rows older
than 7 days are pruned); without one the index is 0 and the base rate applies.

Registration in main.py startup_event:
    from agentvault_registry.background_tasks.velocity_snapshot import (
        start_velocity_snapshot, stop_velocity_snapshot
    )
    asyncio.create_task(start_velocity_snapshot())

Shutdown in main.py shutdown_event:
    await stop_velocity_snapshot()
"""
import asyncio
import logging
import math
import httpx
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import select, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..core import ledger_names   # W4: an event's old and new names are one event
from ..database import get_db_context
from ..es_ssl_helper import get_httpx_verify

logger = logging.getLogger(__name__)

# `/api/v1/events/export` caps `limit` at 1000; 200 pages covers 200k transfers
# in one hourly window, far above anything the fleet has produced.
_EXPORT_PAGE_SIZE = 1000
_MAX_EXPORT_PAGES = 200


class VelocitySnapshotFailed(RuntimeError):
    """The cycle did not complete. Never swallowed: the stamp must say `error`."""


class VelocityQueryFailed(VelocitySnapshotFailed):
    """The window could not be computed. Distinct from 'the window was empty'."""


_SNAPSHOT_INTERVAL_SECONDS = float(
    os.environ.get("VELOCITY_SNAPSHOT_INTERVAL_SECONDS", str(3600))  # default: 1 hour
)


def _env_number(name: str, default, cast):
    try:
        return cast(os.environ.get(name, str(default)))
    except (TypeError, ValueError, InvalidOperation):
        logger.warning("[VelocitySnapshot] %s is not a number; using %s", name, default)
        return cast(str(default))


# The fee's velocity index (services/transaction_fee_service.py adds a surcharge above 0.7) marks a sender that moved
# far more than the typical sender of the same hour. It used to be the agent's volume over the hour's LARGEST volume,
# so the busiest sender always read 1.0 and paid the maximum fee, a lone sender on a quiet frame included. Now:
#   * fewer than VELOCITY_MIN_ACTIVE_SENDERS agents sent in the hour: there is no population to compare with, and
#     every index is 0;
#   * the baseline is the median of the hour's volumes, never below VELOCITY_BASELINE_MIN_VOLUME units, so a crowd of
#     tiny transfers does not make an ordinary one look like an outlier;
#   * an agent at or below the baseline reads 0; above it the index grows with log(volume / baseline) and reaches 1.0
#     at VELOCITY_SATURATION_RATIO times the baseline. With the defaults the surcharge starts at about 25 times the
#     baseline (log 25.1 / log 100 = 0.7) and the maximum fee needs 100 times it.
_MIN_ACTIVE_SENDERS = max(1, _env_number("VELOCITY_MIN_ACTIVE_SENDERS", 10, int))
_BASELINE_MIN_VOLUME = max(Decimal("0.000001"), _env_number("VELOCITY_BASELINE_MIN_VOLUME", 100, Decimal))
_SATURATION_RATIO = max(1.000001, _env_number("VELOCITY_SATURATION_RATIO", 100, float))


def velocity_indices(volumes: dict) -> dict:
    """Map {agent_did: volume sent in the hour} to {agent_did: velocity index in [0, 1]} by the rule above."""
    out = {did: 0.0 for did in volumes}
    active = {did: Decimal(v) for did, v in volumes.items() if v and Decimal(v) > 0}
    if len(active) < _MIN_ACTIVE_SENDERS:
        return out
    ordered = sorted(active.values())
    n = len(ordered)
    median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    baseline = max(median, _BASELINE_MIN_VOLUME)
    for did, volume in active.items():
        if volume > baseline:
            out[did] = min(1.0, math.log(float(volume / baseline)) / math.log(_SATURATION_RATIO))
    return out


class VelocitySnapshotWorker:
    """
    Background task: compute per-agent velocity metrics every hour.

    Strategy:
      1. Determine the last completed hour window (window_start = now - 1h, truncated).
      2. Query EventStore for TokensTransferred events in that window.
      3. Aggregate per-agent: tx_count, tx_volume.
      4. Compute velocity_index by velocity_indices(): 0 without a population, else log(volume / baseline).
      5. Upsert into velocity_metrics (one row per agent per window).
    """

    def __init__(self):
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self._last_truncated = False

    async def _run_snapshot(self):
        """Execute one snapshot cycle."""
        now = datetime.now(timezone.utc)
        # Truncate to the start of the LAST completed hour
        window_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        window_end = window_start + timedelta(hours=1)

        logger.info(
            f"[VelocitySnapshot] Computing window "
            f"{window_start.isoformat()} – {window_end.isoformat()}"
        )

        self._last_truncated = False
        try:
            # Query EventStore for transfer events in the window
            agent_stats = await self._query_event_store_transfers(window_start, window_end)
            if agent_stats is None:
                # NOT an empty window — the query failed. Saying so is the whole
                # point: the previous version logged "No transfer events in
                # window" for a dead connection and left the table empty for the
                # life of the deployment.
                raise VelocityQueryFailed("EventStore query failed; window not computed")
            if not agent_stats:
                logger.info("[VelocitySnapshot] No transfer events in window; skipping upsert")
                return

            indices = velocity_indices({did: stats["volume"] for did, stats in agent_stats.items()})

            async with get_db_context() as db:
                from ..models import VelocityMetrics
                for agent_did, stats in agent_stats.items():
                    # velocity_index is a double precision column, so a float is the right
                    # type THERE; the volume it derives from is not.
                    velocity_index = indices[agent_did]
                    # Upsert: if row exists for this (agent_did, window_start), update it
                    stmt = pg_insert(VelocityMetrics).values(
                        agent_did=agent_did,
                        window_start=window_start,
                        tx_count=stats["count"],
                        tx_volume=stats["volume"],
                        velocity_index=velocity_index,
                        computed_at=now,
                    # §VITALS 2026-09-04, the FIFTH defect in this worker, and the one
                    # that only became visible once the other four were fixed:
                    # `constraint=` compiles to ON CONFLICT ON CONSTRAINT, which
                    # resolves ONLY against pg_constraint. The model declares a
                    # sa.UniqueConstraint but the DB carries `ix_velocity_agent_window`
                    # as a UNIQUE INDEX (pg_indexes), so every upsert died with
                    # `constraint "ix_velocity_agent_window" does not exist`.
                    # `index_elements` compiles to ON CONFLICT (cols), which a unique
                    # INDEX satisfies — no migration, and it keeps working either way.
                    ).on_conflict_do_update(
                        index_elements=['agent_did', 'window_start'],
                        set_={
                            'tx_count': stats["count"],
                            'tx_volume': stats["volume"],
                            'velocity_index': velocity_index,
                            'computed_at': now,
                        }
                    )
                    await db.execute(stmt)
                await db.commit()
                logger.info(
                    f"[VelocitySnapshot] Upserted {len(agent_stats)} agent rows "
                    f"for window {window_start.isoformat()}"
                )

            # Prune rows older than 7 days to keep the table bounded
            await self._prune_old_rows()

        except VelocityQueryFailed:
            raise
        except Exception as e:
            # §VITALS: re-raised, NOT swallowed. The first wiring of this worker
            # only reported VelocityQueryFailed, so when the upsert failed on a
            # missing constraint the cycle still stamped `ok` — the exact defect
            # class this contract exists to kill, reproduced by its own author
            # within the hour. A worker's catch-all must reach the cycle stamp.
            logger.error(f"[VelocitySnapshot] Snapshot failed: {e}", exc_info=True)
            raise VelocitySnapshotFailed(str(e)) from e

    async def _query_event_store_transfers(
        self, window_start: datetime, window_end: datetime
    ) -> Optional[dict]:
        """Aggregate TokensTransferred volume per sender for [start, end).

        Returns ``{did: {"count": int, "volume": float}}``, ``{}`` when the window
        is genuinely empty, and **None when the query FAILED** — the caller must
        not treat a failure as an empty window.

        §VITALS 2026-09-04 — this function had FOUR independent silent defects,
        every one of which produced "no events" and an empty `velocity_metrics`:

          1. it asked ``/api/v1/events`` (no trailing slash). The ES vhost answers
             FastAPI's slash redirect with an ABSOLUTE Location that loses the
             scheme and port (`https://…:8443` -> `http://…:80`), and nothing
             listens on 80. Every cycle died in ConnectError.
          2. it read ``ev["event_data"]`` and a sender named
             ``sender_did|from_did|sender``. The ES ships ``ev["data"]["from"]``.
             All four names were wrong, so every event would have been skipped.
          3. it passed ``from=``/``to=`` to an endpoint that HAS NO SUCH
             PARAMETERS (`GET /api/v1/events/` takes limit/offset/event_type/
             sort_order). FastAPI drops unknown query params, so the window was
             silently ignored.
          4. ``limit=10000`` is that endpoint's hard maximum and the type-filtered
             path is DESC, so it would have aggregated the most recent 10k events
             regardless of the requested window — and the last hour alone returns
             10,000.

        The rail that actually answers this question is ``/api/v1/events/export``:
        an ASC cursor (`since`) with an `event_type` filter, ≤1000 per page. Paged
        here with an explicit page ceiling, and a truncated window is REPORTED,
        never silently under-counted (an under-counted velocity feeds the IRONKEY
        rolling-24h spend cap).
        """
        from ..config import settings

        event_store_url = getattr(settings, 'EVENT_STORE_URL', 'http://event-store:8080')
        internal_key = getattr(settings, 'EVENT_STORE_API_KEY', '')

        stats: dict = {}
        cursor = window_start
        pages = 0
        seen_ids: set = set()
        try:
            async with httpx.AsyncClient(
                timeout=30.0, follow_redirects=False, verify=get_httpx_verify()
            ) as client:
                # W4 (agentvault2-aa, 2026-10-25): the transfers under either name (an emitter may write
                # UnitsTransferred once phase 2 switches it), each paged from the window's start
                for _name in ledger_names.live_names("TokensTransferred"):
                    cursor = window_start
                    pages = 0
                    while pages < _MAX_EXPORT_PAGES:
                        pages += 1
                        resp = await client.get(
                            f"{event_store_url}/api/v1/events/export",
                            params={
                                "since": cursor.isoformat(),
                                "event_type": _name,
                                "limit": _EXPORT_PAGE_SIZE,
                            },
                            headers={"X-Internal-Key": internal_key},
                        )
                        # follow_redirects=False on purpose: a 3xx here is the vhost
                        # losing the scheme, and following it turns a real defect into
                        # an empty result. Say so instead.
                        if resp.status_code in (301, 302, 307, 308):
                            logger.warning(
                                "[VelocitySnapshot] EventStore answered %s -> %s; refusing to "
                                "follow a redirect that drops the scheme",
                                resp.status_code, resp.headers.get("location", "?"),
                            )
                            return None
                        if resp.status_code != 200:
                            logger.warning(
                                "[VelocitySnapshot] EventStore export returned %s", resp.status_code
                            )
                            return None

                        data = resp.json()
                        events = data if isinstance(data, list) else data.get("events", [])
                        if not events:
                            break

                        newest = cursor
                        past_window = False
                        for ev in events:
                            ts_raw = ev.get("timestamp") or ""
                            try:
                                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                            except ValueError:
                                continue
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            if ts >= window_end:
                                past_window = True
                                break
                            if ts > newest:
                                newest = ts
                            ev_id = ev.get("id")
                            if ev_id is not None:
                                if ev_id in seen_ids:
                                    continue        # `since` is exclusive-by-timestamp, not by id
                                seen_ids.add(ev_id)
                            payload = ev.get("data") or ev.get("event_data") or {}
                            sender = (payload.get("from") or payload.get("sender_did")
                                      or payload.get("from_did") or payload.get("sender"))
                            if not sender:
                                continue
                            try:
                                # Decimal, not float: this number is summed against
                                # agent_spend_policies.max_per_day (NUMERIC(36,18)).
                                # Binary floats do not belong in a money comparison.
                                amount = Decimal(str(payload.get("amount", 0) or 0))
                            except (TypeError, ValueError, InvalidOperation):
                                continue
                            row = stats.setdefault(sender, {"count": 0, "volume": Decimal(0)})
                            row["count"] += 1
                            row["volume"] += amount

                        if past_window or len(events) < _EXPORT_PAGE_SIZE:
                            break
                        if newest <= cursor:
                            # No forward progress — refuse to spin.
                            logger.warning("[VelocitySnapshot] export cursor stalled at %s", cursor)
                            break
                        cursor = newest
                    else:
                        logger.warning(
                            "[VelocitySnapshot] window truncated at %d pages (%d events/page); "
                            "velocity for this window UNDER-counts",
                            _MAX_EXPORT_PAGES, _EXPORT_PAGE_SIZE,
                        )
                        self._last_truncated = True

            return stats

        except Exception as e:
            logger.warning(f"[VelocitySnapshot] EventStore query failed: {e}")
            return None

    async def _prune_old_rows(self):
        """Delete velocity_metrics rows older than 7 days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        try:
            async with get_db_context() as db:
                from ..models import VelocityMetrics
                await db.execute(
                    text(
                        "DELETE FROM velocity_metrics WHERE window_start < :cutoff"
                    ),
                    {"cutoff": cutoff},
                )
                await db.commit()
        except Exception as e:
            logger.warning(f"[VelocitySnapshot] Prune failed (non-fatal): {e}")

    async def run_forever(self):
        """Loop: wait interval then snapshot."""
        logger.info(
            f"[VelocitySnapshot] Worker started "
            f"(interval={_SNAPSHOT_INTERVAL_SECONDS}s)"
        )
        self.running = True

        # Initial delay: stagger 60s after startup to let registry settle
        await asyncio.sleep(60)

        from .leader import try_acquire_leadership
        from . import vitals as _vitals
        await _vitals.register(
            "velocity_snapshot", module=__name__, pattern="hand-rolled",
            interval_sec=_SNAPSHOT_INTERVAL_SECONDS, enabled=True,
        )
        while self.running:
            try:
                if not await try_acquire_leadership("velocity_snapshot"):
                    await asyncio.sleep(_SNAPSHOT_INTERVAL_SECONDS)
                    continue
                # §VITALS: the outcome of the cycle is recorded, not just the fact
                # that the loop turned. A window this worker could not compute is
                # an `error`, never a quiet `ok`.
                async with _vitals.cycle("velocity_snapshot") as _ctx:
                    try:
                        await self._run_snapshot()
                    except VelocitySnapshotFailed as qe:
                        _ctx.fail(str(qe))
                    if self._last_truncated:
                        _ctx.note(truncated=True)
            except asyncio.CancelledError:
                logger.info("[VelocitySnapshot] Worker cancelled")
                break
            except Exception as e:
                logger.error(f"[VelocitySnapshot] Unexpected error: {e}", exc_info=True)

            try:
                await asyncio.sleep(_SNAPSHOT_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break

    async def start(self):
        if self.task and not self.task.done():
            logger.warning("[VelocitySnapshot] Already running")
            return
        self.task = asyncio.create_task(self.run_forever())
        logger.info("[VelocitySnapshot] Task created")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        logger.info("[VelocitySnapshot] Stopped")


# Singleton
_worker: Optional[VelocitySnapshotWorker] = None


def get_velocity_snapshot_worker() -> VelocitySnapshotWorker:
    global _worker
    if _worker is None:
        _worker = VelocitySnapshotWorker()
    return _worker


async def start_velocity_snapshot():
    """Start the velocity snapshot background task."""
    worker = get_velocity_snapshot_worker()
    await worker.start()


async def stop_velocity_snapshot():
    """Stop the velocity snapshot background task."""
    worker = get_velocity_snapshot_worker()
    await worker.stop()
