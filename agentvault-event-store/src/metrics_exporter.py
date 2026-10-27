"""
Custom Prometheus Metrics Exporter for EventStore

Exposes domain-specific metrics as Prometheus gauges/counters:
- Total event count
- Events by type (TokensIssued, TokensTransferred, etc.)
- Unique agent count
- Ledger time span (oldest/newest event)

These are collected on each /metrics scrape via a background
refresh loop (every 60s) so they don't hit the DB on every scrape.

Also maintains a process-local stats cache (`_stats_cache`) that the
/api/v1/projections/stats handler reads instantly — eliminates the
60+ second blocking SQL the handler used to do per request.
"""
import asyncio
import logging
import os
import time as _time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from prometheus_client import Gauge, Counter, Histogram

from .database.connection import AsyncSessionLocal
from .models.db_models import EventModel
from sqlalchemy import select, func, distinct, text

logger = logging.getLogger(__name__)

# ── Stats cache (read by routers/projections.py:get_projection_stats) ──
# Populated by refresh_eventstore_metrics(); read instantly by the API.
_stats_cache: Dict[str, Any] = {
    "total_events": 0,
    "unique_agents": 0,
    "event_counts": {},
    "oldest_event": None,
    "newest_event": None,
    "last_refresh_ts": 0.0,
}


def get_cached_stats() -> Dict[str, Any]:
    """Return the latest cached stats snapshot. Safe to call from API handlers."""
    return dict(_stats_cache)

# ========================================
# PROMETHEUS METRIC DEFINITIONS
# ========================================

# Gauges (current values that can go up/down).
# multiprocess_mode='livemostrecent' — under uvicorn --workers N each worker has
# its own refresh loop writing the same DB-derived value; we want the freshest
# live worker's write to be authoritative. Dead workers are ignored.
EVENTS_TOTAL = Gauge(
    'eventstore_events_total',
    'Total number of events in the immutable ledger',
    multiprocess_mode='livemostrecent',
)

EVENTS_BY_TYPE = Gauge(
    'eventstore_events_by_type',
    'Number of events per event type',
    ['event_type'],
    multiprocess_mode='livemostrecent',
)

UNIQUE_AGENTS = Gauge(
    'eventstore_unique_agents',
    'Number of unique agents (aggregate_ids) in the ledger',
    multiprocess_mode='livemostrecent',
)

# §LEDGERGATE E (2026-10-11): the projection trigger marks an agent whose projected balance is below zero
# (materialized_balances.negative_since). Under one writer that is a balance change not landed yet (behind) or a broken
# projection; the auditor tells the two apart against the TEG. Read in the cheap part of the refresh (a partial index).
PROJECTION_NEGATIVE_AGENTS = Gauge(
    'eventstore_projection_negative_agents',
    'Agents whose projected balance is below zero now (marked by the projection trigger)',
    multiprocess_mode='livemostrecent',
)
PROJECTION_NEGATIVE_OLDEST_SECONDS = Gauge(
    'eventstore_projection_negative_oldest_seconds',
    'How long the longest-running negative projection has been below zero (0 when none)',
    multiprocess_mode='livemostrecent',
)

LEDGER_AGE_SECONDS = Gauge(
    'eventstore_ledger_age_seconds',
    'Age of the oldest event in the ledger (seconds)',
    multiprocess_mode='livemostrecent',
)

LEDGER_FRESHNESS_SECONDS = Gauge(
    'eventstore_ledger_freshness_seconds',
    'Time since the newest event in the ledger (seconds)',
    multiprocess_mode='livemostrecent',
)

# Service metadata — was Info(), converted to labeled Gauge set=1 for
# multiprocess safety (Info is not supported in multiproc mode).
# Any Grafana query on eventstore_info{service="..."} keeps working.
EVENTSTORE_INFO = Gauge(
    'eventstore_info',
    'EventStore service metadata',
    ['service', 'version', 'ledger_type'],
    multiprocess_mode='livemostrecent',
)
EVENTSTORE_INFO.labels(
    service='agentvault-event-store',
    version='1.0.0',
    ledger_type='immutable_append_only',
).set(1)

# ── Event-flow counters (Kafka batching observability) ──
# HTTP counter `http_requests_total` undercounts real event throughput
# after the Phase-2 Kafka dual-write fix, because most events now flow
# via Kafka → consumer → DB without hitting an HTTP handler. These three
# metrics close that gap. Counters/Histograms in prometheus_client's
# multiproc mode aggregate via MultiProcessCollector automatically — no
# `multiprocess_mode` kwarg needed (that's a Gauge-only parameter).

EVENTS_INGESTED_TOTAL = Counter(
    'eventstore_events_ingested_total',
    'Events persisted to the ledger, by ingest source and event type',
    ['source', 'event_type'],  # source: kafka | http
)

KAFKA_CONSUMER_BATCHES_TOTAL = Counter(
    'eventstore_kafka_consumer_batches_total',
    'Kafka consumer batches committed to the ledger',
)

# §SOVKIT-2 R1 (2026-09-14): records without this store's valid record signature. reason: missing | invalid | nokey |
# undecodable; action: stored (shadow) | dropped (enforce, and every undecodable value). Anything above zero under enforce is
# a writer on the broker that is not this store.
KAFKA_RECORDS_UNVERIFIED_TOTAL = Counter(
    'eventstore_kafka_records_unverified_total',
    "Kafka records without this store's valid record signature, by reason and what the consumer did",
    ['reason', 'action'],
)

KAFKA_CONSUMER_BATCH_SIZE_HIST = Histogram(
    'eventstore_kafka_batch_size',
    'Events per Kafka consumer batch (post idempotent dedup)',
    buckets=(1, 2, 5, 10, 20, 50, 100, 150, 200, 300, 500),
)


# Known event types from the codebase
KNOWN_EVENT_TYPES = [
    'TokensIssued',
    'TokensTransferred',
    'TokensStaked',
    'TokensUnstaked',
    'AgentCreated',
    'AgentUpdated',
    'AttestationSubmitted',
    'ReputationChanged',
    'DisputeOpened',
    'DisputeResolved',
    'StakeRewardDistributed',
    'ContractCreated',
    'ContractExecuted',
    'FederationSyncCompleted',
    'CrossRegistryTransfer',
    'GenesisGrant',
    'TreasuryFunding',
]

# Initialize all known types to 0 so they appear even if no events exist
for event_type in KNOWN_EVENT_TYPES:
    EVENTS_BY_TYPE.labels(event_type=event_type).set(0)


async def refresh_eventstore_metrics():
    """
    Query the EventStore database and update Prometheus metrics + the
    process-local stats cache (`_stats_cache`).

    Uses FAST sources where possible to avoid 60+s aggregate scans on
    multi-million-row events tables:
    - total_events: pg_class.reltuples (instant Postgres estimate)
    - unique_agents: COUNT(*) FROM materialized_balances (small table)
    - events_by_type: GROUP BY on events (still slow, ~30s, runs in
      background only — does not block API handlers because the
      /api/v1/projections/stats handler reads from the cache)
    - oldest/newest: MIN/MAX(timestamp) on events (slow but indexed)
    """
    try:
        from .database.connection import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            # Total events — fast: Postgres planner estimate from pg_class
            total_result = await db.execute(text(
                "SELECT reltuples::bigint FROM pg_class WHERE relname='events'"
            ))
            total_events = total_result.scalar() or 0
            if total_events < 0:
                # §SOVKIT T2 (2026-09-14): reltuples is -1 until the table is first ANALYZEd, and a fresh frame's ledger
                # stays under autoanalyze's threshold for a while, so the console printed "-1" beside AGENTS (hansa,
                # 26 events). Such a table is small by definition: count it.
                total_events = (await db.execute(text("SELECT count(*) FROM events"))).scalar() or 0
            EVENTS_TOTAL.set(total_events)

            # Unique agents — fast: count from materialized_balances
            # (one row per agent, kept current by trigger; ~hundreds of rows)
            unique_result = await db.execute(text(
                "SELECT COUNT(*) FROM materialized_balances"
            ))
            unique_agents = unique_result.scalar() or 0
            UNIQUE_AGENTS.set(unique_agents)

            # §LEDGERGATE E: the agents the projection marked below zero (none on a store whose trigger predates the
            # mark: the column is missing there, and the gauges stay unset rather than read 0)
            try:
                neg = (await db.execute(text(
                    "SELECT count(*), EXTRACT(EPOCH FROM now() - min(negative_since)) "
                    "FROM materialized_balances WHERE negative_since IS NOT NULL"
                ))).first()
                PROJECTION_NEGATIVE_AGENTS.set(float(neg[0] or 0))
                PROJECTION_NEGATIVE_OLDEST_SECONDS.set(max(0.0, float(neg[1] or 0)))
            except Exception as _neg_exc:  # noqa: BLE001
                await db.rollback()
                logger.debug(f"projection negative marks not read: {_neg_exc}")

            # Events by type — slow GROUP BY, runs in background, cached.
            # Wrapped separately so a long-running query here doesn't block
            # the rest of the refresh from finishing.
            #
            # Leader-elected (added 2026-05-01): with --workers N each worker
            # spawns its own metrics_refresh_loop. Without leader election the
            # 24-second GROUP BY ran N times per cycle and saturated the DB.
            # Now only the worker that holds the Redis lock for
            # `eventstore_events_by_type_refresh` runs the query; non-leaders
            # keep their last cached event_counts. The Prometheus gauge uses
            # `multiprocess_mode='livemostrecent'`, so the leader's values
            # become cluster-visible automatically.
            # §2026-07-31 — `hold_leadership`, not `try_acquire_leadership`.
            # The plain acquire only guards who STARTS: this coroutine then sits
            # inside the GROUP BY without renewing, so any run outliving LOCK_TTL
            # frees the lock mid-scan and the next tick starts a SECOND concurrent
            # 71 GB scan. Each copy evicts more page cache, so the scan gets slower,
            # so more copies overlap. That took frame-b to 16 concurrent scans and
            # the host to load 428. Holding the lock makes overlap impossible.
            from .leader import hold_leadership as _es_hold
            from .leader import get_redis as _es_get_redis
            import json as _json_ec
            _EC_REDIS_KEY = "eventstore:stats:event_counts"

            # Belt-and-braces bound on the scan. With the lock held, overlap can no
            # longer happen however long this runs — but an unbounded scan on a
            # starved box still pins memory for no benefit, and a stale count is
            # cheaper than a stuck one. Default 120s vs ~26s warm on 71 GB.
            try:
                _scan_timeout_ms = int(os.getenv("ES_METRICS_SCAN_TIMEOUT_MS", "120000"))
            except ValueError:
                _scan_timeout_ms = 120000

            event_counts: Dict[str, int] = _stats_cache.get("event_counts", {})
            async with _es_hold("eventstore_events_by_type_refresh") as _is_leader:
                if _is_leader:
                    try:
                        # Run the scan on its OWN session. If statement_timeout fires,
                        # the aborted transaction stays contained here instead of
                        # poisoning `db`, which still has work to do below.
                        fresh_counts: Dict[str, int] = {}
                        seen_types = set()
                        async with AsyncSessionLocal() as _scan_db:
                            async with _scan_db.begin():
                                # SET LOCAL reverts at transaction end, so the timeout
                                # cannot leak onto the next user of this pooled
                                # connection. Interpolated, not bound: Postgres SET
                                # does not accept bind parameters.
                                await _scan_db.execute(
                                    text(f"SET LOCAL statement_timeout = {_scan_timeout_ms}")
                                )
                                type_counts_result = await _scan_db.execute(
                                    select(
                                        EventModel.event_type,
                                        func.count().label("count")
                                    ).group_by(EventModel.event_type)
                                )
                                for row in type_counts_result:
                                    EVENTS_BY_TYPE.labels(event_type=row.event_type).set(row.count)
                                    fresh_counts[row.event_type] = int(row.count)
                                    seen_types.add(row.event_type)

                        # Zero out any KNOWN type not seen this scan
                        for event_type in KNOWN_EVENT_TYPES:
                            if event_type not in seen_types:
                                EVENTS_BY_TYPE.labels(event_type=event_type).set(0)

                        # Only overwrite the cache once the full refresh succeeded
                        event_counts = fresh_counts
                        # Publish to Redis so NON-leader workers (each has its own
                        # process-local _stats_cache) serve the SAME event_counts —
                        # without this, /projections/stats returns {} from whichever
                        # non-leader worker happens to answer the HTTP request.
                        try:
                            _ec_r = await _es_get_redis()
                            if _ec_r is not None:
                                await _ec_r.set(_EC_REDIS_KEY, _json_ec.dumps(fresh_counts), ex=300)
                        except Exception as _ec_pub:
                            logger.debug(f"event_counts redis publish skipped: {_ec_pub}")
                    except Exception as _ec_exc:
                        logger.warning(f"event_counts refresh skipped: {_ec_exc}")
                        # Keep prior cache value rather than blanking it
                        event_counts = _stats_cache.get("event_counts", {})
                else:
                    # Non-leader: read the leader's event_counts from Redis so this
                    # worker's /projections/stats matches the leader instead of a stale {}.
                    try:
                        _ec_r = await _es_get_redis()
                        if _ec_r is not None:
                            _ec_raw = await _ec_r.get(_EC_REDIS_KEY)
                            if _ec_raw:
                                event_counts = _json_ec.loads(_ec_raw)
                    except Exception as _ec_rd:
                        logger.debug(f"event_counts redis read skipped: {_ec_rd}")

            # Ledger timestamps — keep, indexed columns make this OK
            oldest_iso: Optional[str] = None
            newest_iso: Optional[str] = None
            try:
                time_result = await db.execute(
                    select(
                        func.min(EventModel.timestamp).label("oldest"),
                        func.max(EventModel.timestamp).label("newest")
                    )
                )
                time_row = time_result.one_or_none()
                now = datetime.now(timezone.utc)

                if time_row and time_row.oldest:
                    oldest = time_row.oldest
                    if oldest.tzinfo is None:
                        oldest = oldest.replace(tzinfo=timezone.utc)
                    LEDGER_AGE_SECONDS.set((now - oldest).total_seconds())
                    oldest_iso = oldest.isoformat()
                else:
                    LEDGER_AGE_SECONDS.set(0)

                if time_row and time_row.newest:
                    newest = time_row.newest
                    if newest.tzinfo is None:
                        newest = newest.replace(tzinfo=timezone.utc)
                    LEDGER_FRESHNESS_SECONDS.set((now - newest).total_seconds())
                    newest_iso = newest.isoformat()
                else:
                    LEDGER_FRESHNESS_SECONDS.set(0)
            except Exception as _ts_exc:
                logger.warning(f"timestamp refresh skipped: {_ts_exc}")

            # Update stats cache atomically (single-process so no lock needed)
            _stats_cache.update({
                "total_events": int(total_events),
                "unique_agents": int(unique_agents),
                "event_counts": event_counts,
                "oldest_event": oldest_iso,
                "newest_event": newest_iso,
                "last_refresh_ts": _time.time(),
            })

            logger.debug(
                f"Metrics refreshed: {total_events} events, "
                f"{unique_agents} agents, {len(event_counts)} types"
            )

    except Exception as e:
        logger.error(f"Error refreshing EventStore metrics: {e}")


async def metrics_refresh_loop(interval_seconds: int = 60):
    """
    Background loop that refreshes EventStore metrics on a schedule.
    Run as an asyncio task on startup.
    """
    logger.info(f"EventStore metrics refresh loop starting (interval={interval_seconds}s)")
    while True:
        await refresh_eventstore_metrics()
        await asyncio.sleep(interval_seconds)
