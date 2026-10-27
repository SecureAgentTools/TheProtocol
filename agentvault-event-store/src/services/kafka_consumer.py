"""
Kafka Consumer for EventStore -- Phase 1 Scaling

Consumes events from Redpanda/Kafka topics and persists them to the EventStore
database.  Replaces the synchronous HTTP POST ingestion path while the HTTP
endpoint remains as a fallback.

Design decisions
----------------
* Manual offset commit -- only committed AFTER the event is safely in Postgres.
* Idempotency -- exact same logic as the HTTP path: SELECT-then-INSERT with a
  UNIQUE constraint safety net on `idempotency_key`.
* Lockdown -- respects the global lockdown flag (Phase 2b circuit breaker).
* WebSocket fan-out -- publishes stored events to connected WS clients, matching
  the HTTP path behaviour.
* Reconnect loop -- if the broker goes away the consumer backs off and retries
  every 5 s instead of crashing the process.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

from ..metrics_exporter import (
    EVENTS_INGESTED_TOTAL,
    KAFKA_CONSUMER_BATCH_SIZE_HIST,
    KAFKA_CONSUMER_BATCHES_TOTAL,
    KAFKA_RECORDS_UNVERIFIED_TOTAL,
)
from ..kafka_record_auth import key_source as record_key_source, mode as record_auth_mode, mode_word_known, screen
from ..kafka_security import client_security_kwargs

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (env-var driven, off by default)
# ---------------------------------------------------------------------------
KAFKA_ENABLED = os.getenv("KAFKA_ENABLED", "false").lower() == "true"
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")
KAFKA_GROUP = os.getenv("KAFKA_CONSUMER_GROUP", "eventstore-consumer")
KAFKA_TOPICS = [
    "theprotocol.events.financial",
    "theprotocol.events.governance",
    "theprotocol.events.system",
]
KAFKA_BATCH_SIZE = int(os.getenv("KAFKA_CONSUMER_BATCH_SIZE", "50"))
KAFKA_BATCH_TIMEOUT_MS = int(os.getenv("KAFKA_CONSUMER_BATCH_TIMEOUT_MS", "100"))

_consumer_task = None
_watchdog_task = None


# ---------------------------------------------------------------------------
# Public lifecycle API (called from main.py)
# ---------------------------------------------------------------------------

async def start_kafka_consumer():
    """Start the Kafka consumer with watchdog. Called on app startup."""
    global _watchdog_task
    if not KAFKA_ENABLED:
        logger.info("[Kafka] Consumer disabled (KAFKA_ENABLED != 'true')")
        return

    _watchdog_task = asyncio.create_task(_watchdog())
    logger.info(
        "[Kafka] Consumer task started  group=%s  topics=%s  brokers=%s",
        KAFKA_GROUP,
        KAFKA_TOPICS,
        KAFKA_BOOTSTRAP,
    )
    # §SOVKIT-2 R1: the ledger takes a record only when this store signed it (src/kafka_record_auth.py).
    logger.info("[Kafka] record auth %s (key %s)", record_auth_mode(), record_key_source())
    if not mode_word_known():
        logger.error("[Kafka] ES_KAFKA_RECORD_AUTH=%r is not enforce, shadow or off; it is treated as enforce",
                     os.getenv("ES_KAFKA_RECORD_AUTH"))
    if record_auth_mode() == "enforce" and record_key_source() == "missing":
        logger.error("[Kafka] record auth is enforced but this store holds no record key: every record will be refused")


async def _watchdog():
    """Monitor the consumer task and restart if it dies silently."""
    global _consumer_task
    while True:
        if _consumer_task is None or _consumer_task.done():
            if _consumer_task and _consumer_task.done():
                try:
                    exc = _consumer_task.exception()
                except (asyncio.CancelledError, asyncio.InvalidStateError):
                    exc = None
                logger.error(f"[Kafka] Consumer task died! Exception: {exc}. Restarting...")
            _consumer_task = asyncio.create_task(_consume_loop())
        await asyncio.sleep(10)


async def stop_kafka_consumer():
    """Gracefully stop the Kafka consumer and watchdog. Called on app shutdown."""
    global _consumer_task, _watchdog_task
    if _watchdog_task is not None:
        _watchdog_task.cancel()
        try:
            await _watchdog_task
        except asyncio.CancelledError:
            pass
        _watchdog_task = None
    if _consumer_task is not None:
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
        _consumer_task = None
        logger.info("[Kafka] Consumer stopped")


# ---------------------------------------------------------------------------
# Internal: consumer loop
# ---------------------------------------------------------------------------

async def _consume_loop():
    """
    Main consumer loop.

    Outer ``while True`` handles broker disconnections with a 5-second back-off.
    Inner ``async for msg`` processes individual Kafka records.
    """
    from aiokafka import AIOKafkaConsumer  # deferred import -- only needed when enabled

    consumer = None
    while True:
        try:
            consumer = AIOKafkaConsumer(
                *KAFKA_TOPICS,
                bootstrap_servers=KAFKA_BOOTSTRAP,
                group_id=KAFKA_GROUP,
                auto_offset_reset="earliest",      # don't miss events on first join
                enable_auto_commit=False,           # manual commit after DB write
                # §SOVKIT-2 R1: no value_deserializer. The record signature covers the raw bytes, so screen() verifies them
                # first and decodes after; an undecodable value is dropped and counted instead of crash-looping the reader.
                max_poll_records=KAFKA_BATCH_SIZE,  # poll up to N records at once
                session_timeout_ms=30000,
                heartbeat_interval_ms=10000,
                **client_security_kwargs(),
            )
            await consumer.start()
            logger.info(
                "[Kafka] Consumer connected to %s (batch_size=%d, timeout=%dms)",
                KAFKA_BOOTSTRAP, KAFKA_BATCH_SIZE, KAFKA_BATCH_TIMEOUT_MS,
            )

            import time as _time
            _hb_time = _time.time()
            _hb_msgs = 0

            while True:
                # Heartbeat: log every 60s to prove consumer is alive
                _now = _time.time()
                if _now - _hb_time > 60:
                    logger.info(f"[Kafka] Heartbeat: {_hb_msgs} msgs in last 60s")
                    _hb_time = _now
                    _hb_msgs = 0

                # Poll a batch of messages (up to KAFKA_BATCH_SIZE in KAFKA_BATCH_TIMEOUT_MS)
                batch = await consumer.getmany(
                    timeout_ms=KAFKA_BATCH_TIMEOUT_MS,
                    max_records=KAFKA_BATCH_SIZE,
                )

                if not batch:
                    continue

                # Flatten all topic-partition messages into one list
                messages = []
                for tp, msgs in batch.items():
                    messages.extend(msgs)

                if not messages:
                    continue

                try:
                    # §SOVKIT-2 R1: only records this store signed reach the ledger (enforce); shadow stores the rest and
                    # counts them. A refused record is committed with the batch: it is refused, not pending.
                    kept, unverified, tally = screen(messages)
                    _report_screen(tally, unverified)
                    stored_events = await _process_batch(kept) if kept else []
                    # Commit offsets only after the entire batch is persisted
                    await consumer.commit()
                    _hb_msgs += len(messages)

                    # Fan out via WebSocket (best-effort).
                    # 2026-05-04: parallelise the per-event publish via
                    # asyncio.gather. Previously the loop was `for evt:
                    # await publish_event(evt)` which serialised the entire
                    # batch fanout — at ~5-10 ms per event x N events, a
                    # 100-event batch took 500-1000 ms, capping cluster WS
                    # throughput at ~100-200/sec. With gather, fan-out is
                    # bounded by the slowest single publish, lifting the
                    # ceiling to ~1000+/sec. Mirrors the pattern already
                    # used by cross_frame_replicator._store_foreign_events_bulk.
                    if stored_events:
                        try:
                            from .websocket_publisher import event_publisher
                            await asyncio.gather(
                                *(event_publisher.publish_event(evt) for evt in stored_events),
                                return_exceptions=True,
                            )
                        except Exception as ws_err:
                            logger.debug(
                                "[Kafka] WebSocket publish failed (non-fatal): %s", ws_err
                            )

                except asyncio.CancelledError:
                    raise
                except Exception as proc_err:
                    logger.error(
                        "[Kafka] Batch processing failed: %s", proc_err, exc_info=True
                    )
                    # aiokafka advances the in-memory fetch position on getmany()
                    # regardless of commit, so merely not committing does NOT
                    # redeliver: the next successful batch's commit() seals
                    # offsets PAST these messages and they are gone (exactly one
                    # ledger event was lost this way on 2026-08-02 -- the frame-a
                    # AuditorPerUserConservationBreach). Rewind every partition of
                    # the failed batch to its last COMMITTED offset so the batch
                    # is genuinely re-fetched; idempotency (batch ON CONFLICT +
                    # per-event key check) makes the replay exactly-once. A poison
                    # message therefore retries loudly instead of vanishing
                    # silently -- for a ledger that is the correct trade.
                    try:
                        for _tp in batch:
                            _committed = await consumer.committed(_tp)
                            if _committed is not None:
                                consumer.seek(_tp, _committed)
                            elif batch[_tp]:
                                consumer.seek(_tp, batch[_tp][0].offset)
                    except Exception as seek_err:
                        logger.error(
                            "[Kafka] seek-back failed (%s) -- restarting consumer "
                            "so fetch positions reset to committed offsets",
                            seek_err,
                        )
                        raise
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            raise  # let stop_kafka_consumer() finish cleanly
        except Exception as loop_err:
            logger.error(
                "[Kafka] Consumer error, reconnecting in 5 s: %s", loop_err
            )
        finally:
            if consumer is not None:
                try:
                    await consumer.stop()
                except Exception:
                    pass
                consumer = None

        # Back-off before reconnect attempt
        await asyncio.sleep(5)


def _report_screen(tally, unverified) -> None:
    """Count what screen() did not verify and say it once per batch, with up to three examples (never the event data)."""
    if not tally:
        return
    for (reason, action), n in tally.items():
        try:
            KAFKA_RECORDS_UNVERIFIED_TOTAL.labels(reason=reason, action=action).inc(n)
        except Exception:
            pass
    sample = "; ".join(
        f"{e['verdict']} {e['event_type']} key={e['idempotency_key']} {e['topic']}[{e['partition']}]@{e['offset']}"
        for e in unverified[:3]
    )
    dropped = sum(n for (_, action), n in tally.items() if action == "dropped")
    stored = sum(n for (_, action), n in tally.items() if action == "stored")
    if dropped:
        logger.error("[Kafka] REFUSED %d record(s) this store did not sign (record auth %s): %s",
                     dropped, record_auth_mode(), sample)
    if stored:
        logger.warning("[Kafka] stored %d record(s) this store did not sign (record auth shadow; enforce refuses them): %s",
                       stored, sample)


# ---------------------------------------------------------------------------
# Internal: batch processing (Phase 1 scaling — N events per DB transaction)
# ---------------------------------------------------------------------------

async def _process_batch(events: list[dict]) -> list:
    """
    Process a batch of Kafka messages in a SINGLE database transaction.

    This is the key scaling optimization: instead of 1 INSERT + 1 COMMIT per
    event, we do N INSERTs + 1 COMMIT.  PostgreSQL commits are the expensive
    part (~2-5 ms each due to WAL fsync); batching amortises that cost.

    Returns a list of stored Event objects (for WebSocket fan-out).
    """
    from ..database.connection import AsyncSessionLocal
    from ..models.db_models import EventModel
    from ..models.events import Event
    from .lockdown_state import GLOBAL_LOCKDOWN
    from sqlalchemy import text as _sa_text
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    if await GLOBAL_LOCKDOWN.is_locked():   # the shared row: a lockdown taken by any worker (D6-298)
        raise RuntimeError(f"EventStore locked down: {GLOBAL_LOCKDOWN.reason}")

    stored = []
    skipped = 0

    async with AsyncSessionLocal() as session:
        session.sync_session.autoflush = False
        try:
            seen_keys = set()
            unique_events = []
            for ed in events:
                key = ed.get("idempotency_key")
                if key and key in seen_keys:
                    skipped += 1
                    continue
                if key:
                    seen_keys.add(key)
                unique_events.append(ed)

            # Build rows for a single bulk INSERT.
            # Uses Postgres ON CONFLICT (idempotency_key) DO NOTHING so cross-batch
            # duplicates are filtered at row level without rolling back the batch.
            # Replaces the old per-event SELECT-then-INSERT pattern; previous attempt
            # to rely on IntegrityError + per-event fallback melted the DB (70%
            # batch failure under Kafka producer retries).
            rows = []
            for event_data in unique_events:
                event_id = event_data.get("id") or str(uuid.uuid4())
                ts_raw = event_data.get("timestamp")
                if isinstance(ts_raw, str):
                    ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    timestamp = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
                else:
                    timestamp = datetime.now(timezone.utc)
                rows.append({
                    "id": event_id,
                    "event_type": event_data.get("event_type"),
                    "aggregate_id": event_data.get("aggregate_id"),
                    "aggregate_type": event_data.get("aggregate_type", "Agent"),
                    "data": event_data.get("data", {}),
                    "event_metadata": event_data.get("metadata", {}),
                    "timestamp": timestamp,
                    "version": event_data.get("version", 1),
                    "source_service": event_data.get("source_service", "unknown"),
                    "idempotency_key": event_data.get("idempotency_key"),
                    "source_operator_id": event_data.get("source_operator_id"),
                })

            if rows:
                # Pre-acquire per-agent advisory locks in lex-sorted order
                # BEFORE the bulk INSERT. The materialized_balances trigger
                # calls the same pg_advisory_xact_lock(42002, hashtext(did))
                # per row; because these are session-scoped and idempotent,
                # the trigger's calls become no-ops once the session already
                # holds the lock. All workers acquire in sorted order here,
                # so the combined wait-for graph has no cycle ⇒ no deadlocks
                # on the accumulated per-batch lock set.
                _single_agent = {
                    "TokensIssued", "TokensStaked", "TokensUnstaked",
                    "RewardsAutoCompounded", "DisputeSlash",
                    "DisputeCompensationMinted", "BalanceCorrected",
                }
                lock_dids: set[str] = set()
                for r in rows:
                    et = r.get("event_type")
                    aid = r.get("aggregate_id")
                    data = r.get("data") or {}
                    if et in _single_agent:
                        if aid:
                            lock_dids.add(aid)
                    elif et == "TokensTransferred":
                        frm = data.get("from")
                        to_ = data.get("to")
                        if frm:
                            lock_dids.add(frm)
                        if to_:
                            lock_dids.add(to_)
                    elif et == "TransactionFeeCollected":
                        # 2026-05-02: lock-free path. Trigger handles fee_collector
                        # and sender via ON CONFLICT DO UPDATE row-level locking.
                        # No upfront advisory locks needed — both INSERTs target
                        # distinct rows (sender vs fee_collector) in deterministic
                        # order, so no deadlock cycle is possible. This eliminates
                        # the universal contention on hashtext('teg:system:fee_collector')
                        # that had been the cluster-wide TX/s ceiling.
                        pass
                    elif et == "LedgerBalanceChanged":
                        # 2026-06-06: single-writer balance path. The materialized_balances
                        # trigger locks pg_advisory_xact_lock(42002, hashtext(agent_did)) per
                        # entry in RAW entries-array order (materialized_balances.sql:106-111).
                        # This was the ONE balance path missing from the sorted pre-lock set →
                        # concurrent cross-frame FX writes deadlocked on the shared accounts
                        # (@fx_router/@fx_reserve/fee_collector) when two batches ordered them
                        # oppositely (963 deadlocks observed at ~36 routes/s). Pre-lock every
                        # entry DID here in global sorted order so the trigger's later same-
                        # namespace locks become no-ops and no wait-for cycle can form.
                        for _e in (data.get("entries") or []):
                            _ed = _e.get("agent_did") if isinstance(_e, dict) else None
                            if _ed:
                                lock_dids.add(_ed)
                for _did in sorted(lock_dids):
                    await session.execute(
                        _sa_text(
                            "SELECT pg_advisory_xact_lock(42002, hashtext(:did))"
                        ),
                        {"did": _did},
                    )

                stmt = (
                    pg_insert(EventModel)
                    .values(rows)
                    .on_conflict_do_nothing(index_elements=["idempotency_key"])
                    .returning(EventModel)
                )
                result = await session.execute(stmt)
                inserted = result.scalars().all()
                skipped += len(rows) - len(inserted)

                for db_event in inserted:
                    stored.append(Event(
                        id=str(db_event.id),
                        event_type=db_event.event_type,
                        aggregate_id=db_event.aggregate_id,
                        aggregate_type=db_event.aggregate_type,
                        data=db_event.data,
                        metadata=db_event.event_metadata or {},
                        timestamp=db_event.timestamp,
                        version=db_event.version,
                        source_service=db_event.source_service,
                        idempotency_key=db_event.idempotency_key,
                    ))

            await session.commit()

            # Emit batch-path metrics. Observe only on successful commits
            # (the IntegrityError fallback below uses _process_message, which
            # has its own per-event EVENTS_INGESTED_TOTAL increment).
            if stored:
                KAFKA_CONSUMER_BATCHES_TOTAL.inc()
                KAFKA_CONSUMER_BATCH_SIZE_HIST.observe(len(stored))
                for _ev in stored:
                    EVENTS_INGESTED_TOTAL.labels(
                        source="kafka", event_type=_ev.event_type
                    ).inc()

            if stored or skipped:
                logger.info(
                    "[Kafka] Batch committed: %d stored, %d skipped (idempotent)",
                    len(stored), skipped,
                )
            return stored

        except Exception as batch_err:
            # IntegrityError (duplicate key), OperationalError (deadlock),
            # or autoflush-wrapped deadlock — fall back to per-event processing.
            # Per-event handler has its own idempotency + error handling.
            await session.rollback()
            logger.warning(
                "[Kafka] Batch failed (%s) — falling back to per-event processing",
                type(batch_err).__name__,
            )
            results = []
            for event_data in events:
                evt = await _process_message(event_data)
                if evt is not None:
                    results.append(evt)
            return results


# ---------------------------------------------------------------------------
# Internal: per-message processing (fallback for IntegrityError in batch)
# ---------------------------------------------------------------------------

async def _process_message(event_data: dict):
    """
    Process a single Kafka message and persist it to the EventStore DB.

    Returns the stored ``Event`` (Pydantic model) on success, or ``None``
    when the event was an idempotent duplicate.
    """
    # Local imports to avoid circular references at module load time
    from ..database.connection import AsyncSessionLocal
    from ..models.db_models import EventModel
    from ..models.events import Event
    from .lockdown_state import GLOBAL_LOCKDOWN
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    # ── Phase 2b: Global Lockdown Check (the shared row, every worker: D6-298) ──
    if await GLOBAL_LOCKDOWN.is_locked():
        logger.warning(
            "[Kafka] Append rejected -- lockdown active: %s", GLOBAL_LOCKDOWN.reason
        )
        # Raise so the outer loop does NOT commit the offset; the message will
        # be re-delivered once the lockdown is cleared.
        raise RuntimeError(
            f"EventStore locked down: {GLOBAL_LOCKDOWN.reason}"
        )

    event_type = event_data.get("event_type")
    aggregate_id = event_data.get("aggregate_id")
    idempotency_key = event_data.get("idempotency_key")

    logger.debug(
        "[Kafka] Processing %s for %s (key=%s)", event_type, aggregate_id, idempotency_key
    )

    async with AsyncSessionLocal() as session:
        try:
            # ── Idempotency check (matches HTTP path logic) ──────────────
            if idempotency_key:
                existing = await session.execute(
                    select(EventModel).where(
                        EventModel.idempotency_key == idempotency_key
                    )
                )
                if existing.scalar_one_or_none() is not None:
                    logger.debug(
                        "[Kafka] Idempotent skip: %s key=%s", event_type, idempotency_key
                    )
                    return None  # already stored -- nothing to do

            # ── Build DB model ───────────────────────────────────────────
            event_id = event_data.get("id", str(uuid.uuid4()))
            timestamp_raw = event_data.get("timestamp")
            if isinstance(timestamp_raw, str):
                # Parse ISO-8601 timestamp from the message
                ts = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
                timestamp = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)

            db_event = EventModel(
                id=event_id,
                event_type=event_type,
                aggregate_id=aggregate_id,
                aggregate_type=event_data.get("aggregate_type", "Agent"),
                data=event_data.get("data", {}),
                event_metadata=event_data.get("metadata", {}),
                timestamp=timestamp,
                version=event_data.get("version", 1),
                source_service=event_data.get("source_service", "unknown"),
                idempotency_key=idempotency_key,
                source_operator_id=event_data.get("source_operator_id"),
            )
            session.add(db_event)
            await session.commit()

            EVENTS_INGESTED_TOTAL.labels(
                source="kafka", event_type=event_type or "unknown"
            ).inc()

            logger.info(
                "[Kafka] Stored %s for %s (key=%s)", event_type, aggregate_id, idempotency_key
            )

            # Return a Pydantic Event so callers (WebSocket publisher) can use it
            return Event(
                id=str(db_event.id),
                event_type=db_event.event_type,
                aggregate_id=db_event.aggregate_id,
                aggregate_type=db_event.aggregate_type,
                data=db_event.data,
                metadata=db_event.event_metadata or {},
                timestamp=db_event.timestamp,
                version=db_event.version,
                source_service=db_event.source_service,
                idempotency_key=db_event.idempotency_key,
            )

        except IntegrityError:
            # Race condition safety net -- another consumer instance or the HTTP
            # fallback path stored the same idempotency_key concurrently.
            await session.rollback()
            logger.debug(
                "[Kafka] Duplicate event (IntegrityError): %s key=%s",
                event_type,
                idempotency_key,
            )
            return None

        except Exception:
            await session.rollback()
            raise
