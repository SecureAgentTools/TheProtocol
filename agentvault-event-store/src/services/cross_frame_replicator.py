"""SF-4: Cross-Frame Event Replicator (WS3.5 refactor — 2026-04-21).

Polls remote frames' EventStores for new events and stores them in the local
foreign_events table. Runs as a background task.

**Architecture change (WS3.5):** replaced the static env-var-only loop with
a DB-backed supervisor that spawns per-peer asyncio tasks from the new
`cross_frame_peers` table. Adding / suspending / removing a peer is now
live — no EventStore restart required. Watermarks are persisted to the DB
so restarts resume from the last replicated timestamp.

**Back-compat:** on startup, the `CROSS_FRAME_PEERS` env var is upserted
into the DB table (idempotent). Existing deployments keep working; new
deployments can skip the env var entirely and rely on admin-API-driven
registration via the WS3 invitation handshake.

**Pub/Sub bridge (2026-05-03):** for the async cross-frame transfer path
(TEG_CROSS_FRAME_BACKEND=async), foreign events with whitelisted
event_types are also published to the Redis `es:ws:broadcast` channel
after they're INSERTed into foreign_events. This makes them visible to
the local WebSocket subscribers (registry reactors), enabling sub-second
cross-frame event propagation. Whitelist is narrow (3 coordination event
types) so existing reactors like BalanceSyncReactor are not affected by
foreign TokensTransferred events.

Configuration:
  CROSS_FRAME_PEERS: "frame-id|event-store-url" (legacy bootstrap, comma-separated)
  CROSS_FRAME_POLL_INTERVAL: seconds between cycles per peer (default 30; lower
    on async-cross-frame deployments — see plan)
  CROSS_FRAME_SUPERVISOR_INTERVAL: seconds between peer-list reloads (default 15)
  CROSS_FRAME_REPLICATION_ENABLED: true/false master switch
"""
import asyncio
import json
import logging
import os
import ssl
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from ..database.connection import AsyncSessionLocal as async_session_maker
from ..leader import try_acquire_leadership
from ..models.db_models import ForeignEventModel, CrossFramePeerModel
from .websocket_publisher import connection_manager as _ws_connection_manager

# Whitelist of event types that cross-frame replication should also
# publish to the local WS broadcast channel. Narrow by design — broadcasting
# every foreign event would re-trigger reactors like BalanceSyncReactor for
# remote-frame transfers, which is wrong. Add types only when a paired
# reactor exists that's expected to react to the foreign event.
CROSS_FRAME_BROADCAST_TYPES = {
    "CrossFrameTransferInitiated",
    "CrossFrameTransferSettled",
    "CrossFrameTransferRefunded",
    # §pass47 A5 (2026-05-19) — Peer-topology lifecycle events. Previously
    # only the originating frame's reactor saw these; sibling frames kept
    # stale partner entries on their TEGs. Broadcast so every frame's local
    # reactor (PeerRegistryDeactivated / FederationLicenseSuspended /
    # RegistryQuarantined / OperatorApplicationRevoked / FederationLicenseReinstated)
    # can run its TEG cleanup or re-add against the now-shared event stream.
    "PeerRegistryDeactivated",
    "FrameFederationRevoked",
    "OperatorApplicationRevoked",
    "FederationLicenseSuspended",
    "FederationLicenseReinstated",
    "RegistryQuarantined",
    # §bc3 T3.1 (2026-05-19) — Admin broadcast lifecycle. Federated broadcasts
    # let admins on Frame A reach developers connected to Frame B (and vice
    # versa) without sharing a DB. The receiver-side reactor
    # `reactor_admin_broadcast_received.py` materializes the foreign event
    # as a LOCAL AdminBroadcast row using `(source_frame, idempotency_key)`
    # UNIQUE for dedup. Default audience: Local (per Commander lock); admin
    # opts in to Federation-wide by setting `source_frame!=local_frame` on
    # the broadcast — which is the natural shape since each registry stamps
    # its own REGISTRY_NAME on every POST.
    "AdminBroadcastSent",
    "AdminBroadcastEdited",
    "AdminBroadcastRetracted",
}

logger = logging.getLogger(__name__)

# 2026-05-01: leader-elected via Redis. Without this, every uvicorn worker
# spawns its own supervisor and per-peer poll tasks, multiplying outbound
# /events/export polling N×. Mirrors the morning's metrics_exporter fix.
LEADER_KEY = "cross_frame_replicator"
LEADER_CHECK_INTERVAL = 5  # seconds between leadership re-checks while non-leader

# Active per-peer polling tasks — supervisor manages this dict.
_active_tasks: Dict[str, asyncio.Task] = {}
_shutdown_event: Optional[asyncio.Event] = None


# ─── Env-var bootstrap (back-compat) ───────────────────────────────

def _parse_env_peers() -> List[Dict[str, str]]:
    """Parse legacy CROSS_FRAME_PEERS env var.

    Format: "frame-id|event-store-url" comma-separated.
    Used only on startup to seed the DB table for existing deployments.
    """
    raw = os.getenv("CROSS_FRAME_PEERS", "")
    if not raw:
        return []
    out = []
    for entry in raw.split(","):
        entry = entry.strip()
        if "|" not in entry:
            continue
        fid, url = entry.split("|", 1)
        out.append({"frame_id": fid.strip(), "url": url.strip()})
    return out


async def _seed_peers_from_env():
    """Idempotent UPSERT of CROSS_FRAME_PEERS entries into cross_frame_peers.

    Runs once at startup. Rows seeded here are tagged `added_by='env-bootstrap'`
    so admins can distinguish auto-seeded peers from admin-API-added ones.
    """
    env_peers = _parse_env_peers()
    if not env_peers:
        logger.info("[Replicator] No CROSS_FRAME_PEERS env var to seed")
        return
    async with async_session_maker() as db:
        for peer in env_peers:
            stmt = (
                pg_insert(CrossFramePeerModel)
                .values(
                    frame_id=peer["frame_id"],
                    url=peer["url"],
                    status="active",
                    added_by="env-bootstrap",
                    added_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_nothing(index_elements=["frame_id"])
            )
            await db.execute(stmt)
        await db.commit()
    logger.info(f"[Replicator] Seeded {len(env_peers)} peer(s) from env var → cross_frame_peers table")


# ─── Remote fetch ──────────────────────────────────────────────────

async def _fetch_remote_events(
    url: str,
    since: Optional[datetime] = None,
    since_seq: Optional[int] = None,
    limit: int = 1000,
) -> List[dict]:
    """Fetch events from remote EventStore via HTTP GET /events/export.

    2026-05-02 (Round 4): prefers `since_seq` (monotonic INSERT-time cursor) over
    `since` (timestamp). The legacy timestamp path is vulnerable to a race under
    Kafka-async persistence — events whose `timestamp` predates a watermark
    that already advanced get skipped. The seq cursor is set by the DB sequence
    at commit time, so it's strictly monotonic in commit order.

    Uses mTLS via SPIRE SVIDs when certs are available; falls back to
    X-Internal-Key (dev / same-network setups) otherwise.
    """
    cert_dir = os.getenv("CERT_DIR", "/certs")
    cert_file = os.path.join(cert_dir, "svid.0.pem")
    key_file = os.path.join(cert_dir, "svid.0.key")
    bundle_file = os.path.join(cert_dir, "bundle.0.pem")

    client_kwargs: dict = {"timeout": 15}
    if os.path.exists(cert_file) and os.path.exists(key_file):
        client_kwargs["cert"] = (cert_file, key_file)
        # DUAL TRUST (2026-09-04). `verify=bundle_file` trusted the SPIRE roots
        # ONLY, which works for an internal peer on Docker DNS and fails every
        # peer reached over a PUBLIC hostname — those serve Let's Encrypt, so the
        # fetch died with CERTIFICATE_VERIFY_FAILED before a request was ever
        # sent. Measured on the sandbox pair: peer URL is
        # https://sandbox-events-b.theprotocol.cloud, `verify=bundle` →
        # CERTIFICATE_VERIFY_FAILED, the same call with system CAs → 200. The
        # peer row therefore sat `status: active` with `last_seq: 0` forever.
        #
        # This is the same either/or the REGISTRY side already fixed — see
        # `es_ssl_helper._build_es_ssl_context`, whose docstring records the
        # identical bug hitting CONSUL's public-peer fetches on registry-a
        # (2026-05-29). Trust BOTH: SPIRE anchors for internal targets, system
        # roots for public ones. We still PRESENT the SVID either way, so the
        # peer's mTLS identity check is unchanged.
        if os.path.exists(bundle_file):
            try:
                ctx = ssl.create_default_context(cafile=bundle_file)
                ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
                client_kwargs["verify"] = ctx
            except Exception as e:  # never let trust-building kill the poll
                logger.warning(
                    f"[Replicator] dual-trust context failed ({e}); "
                    f"falling back to system CAs"
                )
                client_kwargs["verify"] = True
        else:
            client_kwargs["verify"] = True

    if since_seq is not None:
        params: dict = {"since_seq": since_seq, "limit": limit}
    elif since is not None:
        params = {"since": since.isoformat(), "limit": limit}
    else:
        # Both None — defensive default to "events from 7 days ago" as before.
        params = {"since": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(), "limit": limit}

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            headers = {}
            if "cert" not in client_kwargs:
                headers["X-Internal-Key"] = os.getenv("INTERNAL_API_KEY", "")
            resp = await client.get(
                f"{url}/api/v1/events/export",
                params=params,
                headers=headers,
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"[Replicator] Export failed from {url}: HTTP {resp.status_code}")
            return []
    except Exception as e:
        logger.debug(f"[Replicator] Fetch failed from {url}: {e}")
        return []


async def _publish_foreign_event_to_ws(frame_id: str, event: dict, ts: datetime) -> None:
    """Publish a whitelisted foreign event to the local Redis Pub/Sub WS bus.

    2026-05-03: foreign events do NOT fire WS broadcasts by default (they
    only land in the audit-only foreign_events table). This bridge enables
    the async cross-frame transfer path: whitelisted coordination event
    types are republished to `events:{event_type}` so registry reactors
    subscribed to the local WS see foreign events as if they were local.

    The whitelist is narrow (CROSS_FRAME_BROADCAST_TYPES) so existing
    reactors like BalanceSyncReactor stay unaffected by foreign
    TokensTransferred events.

    Best-effort — failures here don't abort the foreign-event store.
    SF-4 polling remains the safety net (next reactor reconnect re-replays
    the last 15 events from EventStore's local broadcast cache, but those
    are LOCAL events; for foreign events the safety net is the row in
    foreign_events itself, which a future audit/reconciliation worker can
    sweep if real reactors miss the WS broadcast).
    """
    event_type = event.get("event_type", "")
    if event_type not in CROSS_FRAME_BROADCAST_TYPES:
        return
    try:
        message = {
            "type": "event",
            "event": {
                "id": str(event.get("id", "")),
                "event_type": event_type,
                "aggregate_id": event.get("aggregate_id", ""),
                "aggregate_type": event.get("aggregate_type", "Transfer"),
                "data": event.get("data", {}),
                "timestamp": ts.isoformat(),
                "version": event.get("version", 1),
                "source_frame": frame_id,  # mark as foreign so reactors can debug
            },
        }
        await _ws_connection_manager.broadcast_to_channel(
            f"events:{event_type}", message
        )
        logger.info(
            f"[Replicator] Bridged foreign {event_type} from {frame_id} → "
            f"local WS (event_id={event.get('id', '?')[:12]})"
        )
    except Exception as e:
        logger.warning(
            f"[Replicator] WS bridge publish failed for {event_type} "
            f"from {frame_id}: {e}"
        )


async def _store_foreign_event(frame_id: str, event: dict) -> bool:
    """Insert a foreign event. Returns True if new, False if duplicate.

    Uses INSERT ... ON CONFLICT (frame_id, source_event_id) DO NOTHING.
    Also publishes whitelisted event types to the local WS Pub/Sub bus so
    registry reactors see cross-frame coordination events sub-second.

    NOTE: Per-event INSERT path. Used by callers that handle one event at a
    time. The replicator poll loop uses `_store_foreign_events_bulk` for
    saturation-grade throughput (one INSERT round-trip per batch instead of
    N round-trips per N events).
    """
    async with async_session_maker() as db:
        try:
            source_id = event.get("id")
            if not source_id:
                return False
            ts_str = event.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                ts = datetime.now(timezone.utc)

            stmt = (
                pg_insert(ForeignEventModel)
                .values(
                    id=uuid.uuid4(),
                    frame_id=frame_id,
                    source_event_id=source_id,
                    event_type=event.get("event_type", "unknown"),
                    aggregate_id=event.get("aggregate_id", ""),
                    data=event.get("data", {}),
                    timestamp=ts,
                    source_service=event.get("source_service"),
                    idempotency_key=event.get("idempotency_key"),
                    verified=False,
                )
                .on_conflict_do_nothing(index_elements=["frame_id", "source_event_id"])
                .returning(ForeignEventModel.id)
            )
            result = await db.execute(stmt)
            inserted_id = result.scalar_one_or_none()
            await db.commit()
            if inserted_id is not None:
                # Bridge to local WS for whitelisted cross-frame coordination
                # event types (async cross-frame transfer path).
                await _publish_foreign_event_to_ws(frame_id, event, ts)
                return True
            return False
        except IntegrityError:
            await db.rollback()
            return False
        except Exception as e:
            await db.rollback()
            logger.error(f"[Replicator] Store error: {e}")
            return False


async def _store_foreign_events_bulk(frame_id: str, events: list) -> int:
    """Bulk-insert foreign events in a single round-trip. Returns count of
    newly-inserted rows.

    2026-05-02: replaces the per-event _store_foreign_event call inside the
    poll loop. Under saturation, the per-event path was the dominant
    bottleneck — N events meant N session opens + N INSERTs + N commits =
    ~5-10s of pure DB time per 1000-event batch. With one multi-row INSERT,
    the same batch lands in ~50-100ms.

    WS-bridge for whitelisted event types is fanned out via asyncio.gather
    AFTER the bulk insert succeeds, so we publish only events that actually
    landed (and de-dupe via the same `(frame_id, source_event_id)` unique
    constraint that the per-event path relied on).
    """
    if not events:
        return 0

    rows = []
    parsed = []  # (event_dict, source_id, computed_id, ts) — for later WS bridging
    for event in events:
        source_id = event.get("id")
        if not source_id:
            continue
        ts_str = event.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            ts = datetime.now(timezone.utc)
        new_id = uuid.uuid4()
        rows.append({
            "id": new_id,
            "frame_id": frame_id,
            "source_event_id": source_id,
            "event_type": event.get("event_type", "unknown"),
            "aggregate_id": event.get("aggregate_id", ""),
            "data": event.get("data", {}),
            "timestamp": ts,
            "source_service": event.get("source_service"),
            "idempotency_key": event.get("idempotency_key"),
            "verified": False,
        })
        parsed.append((event, source_id, new_id, ts))

    if not rows:
        return 0

    inserted_ids: set = set()
    async with async_session_maker() as db:
        try:
            stmt = (
                pg_insert(ForeignEventModel)
                .values(rows)
                .on_conflict_do_nothing(index_elements=["frame_id", "source_event_id"])
                .returning(ForeignEventModel.id)
            )
            result = await db.execute(stmt)
            inserted_ids = {row[0] for row in result.fetchall()}
            await db.commit()
        except IntegrityError as e:
            await db.rollback()
            logger.warning(f"[Replicator] Bulk store IntegrityError, falling back to per-event: {e}")
            # Fallback: try each event one at a time so a single bad row
            # doesn't lose the whole batch.
            count = 0
            for event in events:
                if await _store_foreign_event(frame_id, event):
                    count += 1
            return count
        except Exception as e:
            await db.rollback()
            logger.error(f"[Replicator] Bulk store error: {e}")
            return 0

    if not inserted_ids:
        return 0

    # WS bridge for whitelisted event types — fan out concurrently so the
    # per-broadcast latency doesn't serialise the whole batch.
    publish_coros = []
    for event, source_id, new_id, ts in parsed:
        if new_id in inserted_ids:
            publish_coros.append(_publish_foreign_event_to_ws(frame_id, event, ts))
    if publish_coros:
        await asyncio.gather(*publish_coros, return_exceptions=True)

    return len(inserted_ids)


# ─── Per-peer polling task ─────────────────────────────────────────

async def _peer_poll_loop(frame_id: str):
    """Long-running task: poll one peer on its own cadence.

    Watermark is persisted to cross_frame_peers.last_seq (Round-4 monotonic
    cursor) AND cross_frame_peers.last_timestamp (legacy display) at the end
    of each successful batch. Task exits cleanly when peer goes
    suspended/removed (checked each iteration).

    2026-05-02 (Round 4): switched from `last_timestamp > since` cursor to
    `last_seq > since_seq` cursor. The timestamp cursor was vulnerable to a
    race under Kafka-async persistence — events committed out-of-order by
    timestamp would advance the watermark past events that arrived later
    with earlier timestamps, causing them to be permanently skipped.
    """
    interval = int(os.getenv("CROSS_FRAME_POLL_INTERVAL", "30"))
    logger.info(f"[Replicator:{frame_id}] Poll task started (interval={interval}s, cursor=seq)")
    try:
        while True:
            # Re-read peer from DB each cycle — respects live status changes.
            async with async_session_maker() as db:
                row = (await db.execute(
                    select(CrossFramePeerModel).where(CrossFramePeerModel.frame_id == frame_id)
                )).scalar_one_or_none()
                if row is None or row.status != "active":
                    logger.info(f"[Replicator:{frame_id}] Peer no longer active (status={row.status if row else 'missing'}), exiting task")
                    return
                url = row.url
                last_seq = int(row.last_seq or 0)

            try:
                events = await _fetch_remote_events(url, since_seq=last_seq)
            except Exception as e:
                logger.warning(f"[Replicator:{frame_id}] Fetch failed: {e}")
                events = []

            if events:
                # 2026-05-02: bulk INSERT instead of N per-event round-trips.
                # Drops batch DB time from ~5-10s to ~50-100ms for a 1000-event
                # batch, lifting effective replication throughput from
                # ~150 events/s to ~1000 events/s under saturation.
                new_count = await _store_foreign_events_bulk(frame_id, events)

                # Compute latest seq + timestamp from the batch.
                latest_seq = last_seq
                latest_ts = row.last_timestamp or datetime.fromtimestamp(0, tz=timezone.utc)
                for event in events:
                    s = event.get("seq")
                    if s is not None and int(s) > latest_seq:
                        latest_seq = int(s)
                    ts_str = event.get("timestamp", "")
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if ts > latest_ts:
                            latest_ts = ts
                    except (ValueError, AttributeError):
                        pass

                # Persist watermark — both seq (primary) and timestamp (legacy display)
                if latest_seq > last_seq:
                    async with async_session_maker() as db:
                        await db.execute(
                            update(CrossFramePeerModel)
                            .where(CrossFramePeerModel.frame_id == frame_id)
                            .values(
                                last_seq=latest_seq,
                                last_timestamp=latest_ts,
                                updated_at=datetime.now(timezone.utc),
                            )
                        )
                        await db.commit()

                if new_count > 0:
                    logger.info(
                        f"[Replicator:{frame_id}] Stored {new_count} new / {len(events)} fetched "
                        f"(seq watermark {last_seq} → {latest_seq})"
                    )

            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info(f"[Replicator:{frame_id}] Poll task cancelled")
        raise
    except Exception as e:
        logger.error(f"[Replicator:{frame_id}] Task crashed: {e}", exc_info=True)


# ─── Supervisor loop (peer list diff → task management) ────────────

async def _supervisor_loop():
    """Reconcile the active-task set against the DB's `active` peer list.

    Re-reads cross_frame_peers every CROSS_FRAME_SUPERVISOR_INTERVAL seconds.
    Spawns tasks for new peers, cancels tasks for removed/suspended peers.
    """
    global _shutdown_event
    _shutdown_event = asyncio.Event()
    interval = int(os.getenv("CROSS_FRAME_SUPERVISOR_INTERVAL", "15"))
    logger.info(f"[Replicator Supervisor] Started, reconcile every {interval}s")

    was_leader = False  # tracks transitions so we can cancel local tasks on loss
    while not _shutdown_event.is_set():
        # Leader gate: only one worker per cluster runs the supervisor + peer
        # tasks. Non-leaders sleep and recheck. On loss-of-leadership, cancel
        # any peer tasks we previously spawned so we stop polling.
        is_leader = await try_acquire_leadership(LEADER_KEY)
        if not is_leader:
            if was_leader and _active_tasks:
                logger.info(
                    f"[Replicator Supervisor] Lost leadership; cancelling "
                    f"{len(_active_tasks)} peer task(s)"
                )
                for fid, task in list(_active_tasks.items()):
                    if not task.done():
                        task.cancel()
                _active_tasks.clear()
            was_leader = False
            try:
                await asyncio.wait_for(_shutdown_event.wait(), timeout=LEADER_CHECK_INTERVAL)
            except asyncio.TimeoutError:
                pass
            continue
        if not was_leader:
            logger.info(f"[Replicator Supervisor] Acquired leadership '{LEADER_KEY}'")
        was_leader = True

        try:
            async with async_session_maker() as db:
                rows = (await db.execute(
                    select(CrossFramePeerModel).where(CrossFramePeerModel.status == "active")
                )).scalars().all()
            desired = {r.frame_id for r in rows}
            running = set(_active_tasks.keys())

            # Spawn tasks for newly-active peers
            for fid in desired - running:
                _active_tasks[fid] = asyncio.create_task(_peer_poll_loop(fid), name=f"xframe-{fid}")
                logger.info(f"[Replicator Supervisor] Spawned task for peer: {fid}")

            # Cancel tasks for peers no longer active
            for fid in running - desired:
                task = _active_tasks.pop(fid, None)
                if task and not task.done():
                    task.cancel()
                    logger.info(f"[Replicator Supervisor] Cancelled task for peer: {fid}")

            # Reap completed tasks (peers that self-exited due to status change)
            done_fids = [fid for fid, t in _active_tasks.items() if t.done()]
            for fid in done_fids:
                _active_tasks.pop(fid, None)
        except Exception as e:
            logger.error(f"[Replicator Supervisor] Reconcile cycle error: {e}", exc_info=True)

        try:
            await asyncio.wait_for(_shutdown_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass  # normal cycle

    # Shutdown: cancel all active tasks
    for fid, task in list(_active_tasks.items()):
        if not task.done():
            task.cancel()
    _active_tasks.clear()
    logger.info("[Replicator Supervisor] Stopped")


# ─── Entry points ──────────────────────────────────────────────────

async def start_replication():
    """Entry point — called from main.py startup.

    1. Seed DB from CROSS_FRAME_PEERS env var (back-compat, idempotent).
    2. Start supervisor loop which spawns per-peer tasks dynamically.
    """
    await _seed_peers_from_env()
    await _supervisor_loop()


async def stop_replication():
    """Graceful shutdown — signal supervisor + wait for task drain."""
    global _shutdown_event
    if _shutdown_event:
        _shutdown_event.set()
    await asyncio.sleep(0.1)  # yield so supervisor can cancel tasks
