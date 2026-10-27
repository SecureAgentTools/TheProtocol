"""
WebSocket Publisher Service - Broadcasts events to connected clients.

Multi-worker support: uses Redis Pub/Sub so events processed by ANY worker
are broadcast to WebSocket clients connected to ANY other worker.
Pattern: Registry's routers/websocket.py ConnectionManager (2026-04-12).
"""

import json
import logging
import os
import asyncio
from typing import Dict, Set, Optional
from fastapi import WebSocket, WebSocketDisconnect
from src.models.events import Event
from src.personal_ids import carries_personal_id, withhold_personal_ids

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections and subscriptions.
    Uses Redis Pub/Sub for cross-worker broadcast when REDIS_URL is set.
    Falls back to local-only broadcast if Redis is unavailable.
    """

    # pass73.3.19 (2026-05-28) — CRITICAL infra fix: prior single channel
    # `es:ws:broadcast` was shared across ALL EventStore instances reaching
    # the same Redis container. Redis pub/sub channels are GLOBAL (not
    # scoped by DB index), so prod ES events leaked into sandbox ES WS
    # subscribers and vice-versa. Now namespaced via env var so each
    # frame/sandbox gets its own broadcast channel.
    #
    # Default preserves backwards compatibility for single-instance
    # deployments. In multi-instance (prod + sandbox + frame-b), set
    # EVENTSTORE_WS_CHANNEL_NAMESPACE per service (e.g. "prod-a",
    # "sandbox-a", "sandbox-b", "frame-b") so each broadcast stays
    # within its own topology.
    REDIS_WS_CHANNEL = (
        f"es:ws:broadcast:{os.getenv('EVENTSTORE_WS_CHANNEL_NAMESPACE', 'default')}"
    )

    # Per-client send queue size. Bounded so a slow consumer drops old
    # messages instead of stalling the broadcaster (2026-05-03 — fixed
    # under-load WS drop seen during async-cross-frame canary). Bumped
    # 1000→10000 after canary burst showed 1000 drains too fast under
    # extreme load (1000+ events/s × multiple channels).
    PER_CLIENT_QUEUE_MAXSIZE = int(os.getenv("WS_PER_CLIENT_QUEUE_MAX", "10000"))
    # If a client's queue fills up this many times in a row, force-disconnect.
    # Bumped to 500 — gives a slow client several seconds to catch up before
    # we boot it (which then forces a 15-event-replay-only reconnect).
    PER_CLIENT_OVERFLOW_LIMIT = int(os.getenv("WS_PER_CLIENT_OVERFLOW_LIMIT", "500"))

    def __init__(self):
        # Local in-memory connection tracking (per-worker)
        self.channels: Dict[str, Set[WebSocket]] = {}
        self.subscriptions: Dict[WebSocket, Set[str]] = {}
        # Per-WS send queue + sender task — decouples slow consumers from the
        # broadcast fan-out (Phase: WS overload fix, 2026-05-03).
        self._send_queues: Dict[WebSocket, asyncio.Queue] = {}
        self._send_tasks: Dict[WebSocket, asyncio.Task] = {}
        self._overflow_counts: Dict[WebSocket, int] = {}
        # §SECBATCH wave 2: the connections that presented no credential (every console, through the frame's public
        # /ws/events lane). They are sent each event with its personal ids withheld (src/personal_ids.py); a reactor
        # that presented this store's key or its JWT-SVID gets the event as stored.
        self._public: Set[WebSocket] = set()
        # Redis Pub/Sub state (cross-worker broadcast)
        self._redis_url = os.getenv("REDIS_URL")
        self._redis = None
        self._pubsub = None
        self._pubsub_task: Optional[asyncio.Task] = None
        self._pubsub_lock = asyncio.Lock()
        logger.info("WebSocket ConnectionManager initialized (Redis Pub/Sub: %s, per-client queue=%d)",
                     "enabled" if self._redis_url else "disabled",
                     self.PER_CLIENT_QUEUE_MAXSIZE)

    # ── Redis helpers ──────────────────────────────────────────

    async def _get_redis(self):
        """Get or create async Redis connection."""
        if not self._redis_url:
            return None
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(
                    self._redis_url, decode_responses=True,
                    socket_connect_timeout=3, socket_timeout=3,
                )
                await self._redis.ping()
                # §MTLSHOPS G3: REDIS_URL carries this client's Redis password; log the host part only
                logger.info("[WS] Redis connected: %s", self._redis_url.rsplit("@", 1)[-1])
            except Exception as e:
                logger.warning("[WS] Redis connection failed: %s — local-only mode", e)
                self._redis = None
        return self._redis

    async def _ensure_pubsub(self):
        """Lazy-start the Pub/Sub listener on first WebSocket connection."""
        if self._pubsub_task is not None and not self._pubsub_task.done():
            return  # Already running
        async with self._pubsub_lock:
            # Double-check after acquiring lock
            if self._pubsub_task is not None and not self._pubsub_task.done():
                return
            r = await self._get_redis()
            if r is None:
                return
            try:
                self._pubsub = r.pubsub()
                await self._pubsub.subscribe(self.REDIS_WS_CHANNEL)
                self._pubsub_task = asyncio.create_task(self._pubsub_listener())
                logger.info("[WS] Redis Pub/Sub listener started on %s", self.REDIS_WS_CHANNEL)
            except Exception as e:
                logger.warning("[WS] Failed to start Pub/Sub listener: %s", e)
                self._pubsub = None

    async def _handle_pubsub_message(self, msg: dict):
        """Fan out a single Redis Pub/Sub message to local WS clients."""
        data = msg.get("data", "")
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            return
        channel = parsed.get("channel", "")
        message = parsed.get("message", {})
        if channel and message:
            await self._local_broadcast_to_channel(channel, message)

    async def _pubsub_listener(self):
        """Background task: read from Redis Pub/Sub and deliver to local WS clients.

        Drains all pending messages per iteration so throughput tracks the event
        production rate instead of the previous ~10 ms/msg cap (which produced a
        growing backlog and 30-150 s broadcast delay under sustained sim load).
        """
        DRAIN_CEILING = 200  # yield every N to avoid starving other coroutines
        IDLE_TIMEOUT = 0.1   # cooperative block when no messages pending
        while True:
            try:
                if self._pubsub is None:
                    await asyncio.sleep(5)
                    continue

                # Drain: pull everything currently buffered in Redis without yielding.
                drained = 0
                while drained < DRAIN_CEILING:
                    msg = await self._pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=0.0
                    )
                    if msg is None:
                        break
                    if msg.get("type") == "message":
                        await self._handle_pubsub_message(msg)
                    drained += 1

                if drained == 0:
                    # No pending messages — block briefly (event-loop friendly).
                    msg = await self._pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=IDLE_TIMEOUT
                    )
                    if msg is not None and msg.get("type") == "message":
                        await self._handle_pubsub_message(msg)
                else:
                    # Drained a batch — yield once so other tasks can run.
                    await asyncio.sleep(0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[WS] Pub/Sub listener error: %s — retrying in 5s", e)
                await asyncio.sleep(5)

    # ── Connection lifecycle ───────────────────────────────────

    async def connect(self, websocket: WebSocket, public: bool = True):
        """Accept a new WebSocket connection.

        Spawns a per-client send task with a bounded queue so a slow consumer
        drops messages instead of stalling the broadcast fan-out.

        `public` (the default, so a caller that forgets says less, not more): this connection presented no credential
        of this store, and is sent every event with its personal ids withheld.
        """
        await websocket.accept()
        if public:
            self._public.add(websocket)
        self.subscriptions[websocket] = set()
        self._send_queues[websocket] = asyncio.Queue(maxsize=self.PER_CLIENT_QUEUE_MAXSIZE)
        self._overflow_counts[websocket] = 0
        self._send_tasks[websocket] = asyncio.create_task(self._client_sender_loop(websocket))
        # Start Redis listener if not already running
        await self._ensure_pubsub()
        logger.info(f"WebSocket connected: {id(websocket)}")

    def is_public(self, websocket: WebSocket) -> bool:
        return websocket in self._public

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection and all its subscriptions."""
        self._public.discard(websocket)
        if websocket in self.subscriptions:
            for channel in self.subscriptions[websocket]:
                if channel in self.channels:
                    self.channels[channel].discard(websocket)
                    if not self.channels[channel]:
                        del self.channels[channel]
            del self.subscriptions[websocket]
            # Cancel + drop the per-client send task & queue.
            task = self._send_tasks.pop(websocket, None)
            if task and not task.done():
                task.cancel()
            self._send_queues.pop(websocket, None)
            self._overflow_counts.pop(websocket, None)
            logger.info(f"WebSocket disconnected: {id(websocket)}")

    async def _client_sender_loop(self, websocket: WebSocket):
        """Drain a single client's send queue. One task per WS — slow clients
        only block themselves, never the broadcast fan-out."""
        q = self._send_queues.get(websocket)
        if q is None:
            return
        try:
            while True:
                message = await q.get()
                try:
                    await websocket.send_json(message)
                except Exception as e:
                    logger.warning(f"WS send failed (client={id(websocket)}): {e}")
                    self.disconnect(websocket)
                    return
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"Client sender loop crashed (client={id(websocket)}): {e}")
            self.disconnect(websocket)

    async def subscribe(self, websocket: WebSocket, channel: str) -> bool:
        """Subscribe a WebSocket to a channel. A public connection may not subscribe to a channel named by a personal id
        (agent:<an e-mail-derived account id>): that channel is one account's activity, and asking for it by a guessed
        address would tell whether the address holds an account. Answers whether it subscribed."""
        if websocket in self._public and carries_personal_id(channel):
            logger.info(f"WebSocket {id(websocket)} refused a personal channel (public connection)")
            await self.send_personal_message(websocket, {
                "type": "error",
                "message": "subscription refused: a channel named by a personal id needs this store's credentials",
            })
            return False
        if channel not in self.channels:
            self.channels[channel] = set()
        self.channels[channel].add(websocket)
        self.subscriptions[websocket].add(channel)
        logger.info(f"WebSocket {id(websocket)} subscribed to {channel}")
        await self.send_personal_message(websocket, {
            "type": "subscription_confirmed",
            "channel": channel
        })
        return True

    async def unsubscribe(self, websocket: WebSocket, channel: str):
        """Unsubscribe a WebSocket from a channel."""
        if channel in self.channels:
            self.channels[channel].discard(websocket)
            if not self.channels[channel]:
                del self.channels[channel]
        if websocket in self.subscriptions:
            self.subscriptions[websocket].discard(channel)
        logger.info(f"WebSocket {id(websocket)} unsubscribed from {channel}")
        await self.send_personal_message(websocket, {
            "type": "unsubscription_confirmed",
            "channel": channel
        })

    async def send_personal_message(self, websocket: WebSocket, message: dict):
        """Send a message to a specific WebSocket."""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error sending personal message: {e}")
            self.disconnect(websocket)

    # ── Broadcasting ───────────────────────────────────────────

    async def broadcast_to_channel(self, channel: str, message: dict):
        """Broadcast via Redis Pub/Sub (cross-worker) with local fallback."""
        r = await self._get_redis()
        if r is not None:
            try:
                payload = json.dumps({"channel": channel, "message": message})
                await r.publish(self.REDIS_WS_CHANNEL, payload)
                return  # Redis delivers to ALL workers including this one
            except Exception as e:
                logger.warning(f"Redis publish failed, falling back to local: {e}")
        # Fallback: local only (single-worker or Redis down)
        await self._local_broadcast_to_channel(channel, message)

    async def _local_broadcast_to_channel(self, channel: str, message: dict):
        """Enqueue message into each subscribed client's send queue.

        Non-blocking: returns as soon as all queues are written to. A slow
        client drops its OLDEST message on overflow rather than blocking the
        broadcaster (under burst, this is the difference between losing the
        oldest in-flight event for one client vs. stalling the entire WS
        fan-out for all clients). After PER_CLIENT_OVERFLOW_LIMIT consecutive
        overflows, the client is force-disconnected.
        """
        if channel not in self.channels:
            return
        public_message = None  # made once per message, and only when a public connection is on the channel
        for ws in list(self.channels[channel]):
            q = self._send_queues.get(ws)
            if q is None:
                continue
            if ws in self._public:
                if public_message is None:
                    public_message = withhold_personal_ids(message)
                outgoing = public_message
            else:
                outgoing = message
            try:
                q.put_nowait(outgoing)
                # Reset overflow counter on successful enqueue.
                if self._overflow_counts.get(ws, 0) > 0:
                    self._overflow_counts[ws] = 0
            except asyncio.QueueFull:
                # Drop oldest, enqueue new (best-effort live-stream semantics).
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(outgoing)
                except asyncio.QueueFull:
                    pass
                self._overflow_counts[ws] = self._overflow_counts.get(ws, 0) + 1
                if self._overflow_counts[ws] >= self.PER_CLIENT_OVERFLOW_LIMIT:
                    logger.warning(
                        f"WS client={id(ws)} exceeded {self.PER_CLIENT_OVERFLOW_LIMIT} "
                        f"consecutive queue overflows — force disconnecting"
                    )
                    self.disconnect(ws)

    async def _send_safe(self, websocket: WebSocket, message: dict):
        """Legacy direct send (kept for any non-broadcast paths)."""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error broadcasting to websocket: {e}")
            self.disconnect(websocket)

    def get_stats(self, public: bool = True) -> dict:
        """Get connection statistics. The channel names are other connections' subscriptions, and an agent:<id> channel
        can be named by a personal id, so a public answer withholds it (the default)."""
        stats = {
            "total_connections": len(self.subscriptions),
            "total_channels": len(self.channels),
            "redis_pubsub": self._pubsub_task is not None and not self._pubsub_task.done(),
            "channels": {
                channel: len(connections)
                for channel, connections in self.channels.items()
            }
        }
        return withhold_personal_ids(stats) if public else stats


class EventPublisher:
    """
    Publishes events to WebSocket subscribers.
    Integrates with the Event Store to broadcast real-time updates.
    """

    def __init__(self, connection_manager: ConnectionManager):
        self.connection_manager = connection_manager
        logger.info("EventPublisher initialized")

    async def publish_event(self, event: Event):
        """
        Publish an event to relevant WebSocket channels.

        Events are published to:
        - agent:{aggregate_id} - Specific agent channel
        - events:all - Global event stream
        - events:{event_type} - Type-specific channels

        2026-05-03: parallelize the 3-4 channel broadcasts with asyncio.gather
        so a single event isn't bottlenecked by sequential Redis publishes.
        """
        message = {
            "type": "event",
            "event": {
                "id": str(event.id),
                "event_type": event.event_type,
                "aggregate_id": event.aggregate_id,
                "data": event.data,
                "timestamp": event.timestamp.isoformat(),
                "version": event.version
            }
        }

        # Build the channel list — usually 3, 4 if recipient differs from aggregate.
        channels = [
            f"agent:{event.aggregate_id}",
            "events:all",
            f"events:{event.event_type}",
        ]
        if event.event_type == "TokensTransferred":
            to_agent = event.data.get("to")
            if to_agent and to_agent != event.aggregate_id:
                channels.append(f"agent:{to_agent}")

        # Parallel fan-out — Redis publishes are concurrent instead of serial.
        await asyncio.gather(
            *(self.connection_manager.broadcast_to_channel(c, message) for c in channels),
            return_exceptions=True,
        )

        logger.debug(f"Published {event.event_type} event for {event.aggregate_id}")

    # A balance-update channel used to be advertised in the greeting and was never published on (its publisher had no
    # caller); both were removed. A balance change reaches clients as the event that makes it, on the channels above.


# Global instances (initialized in main.py)
connection_manager = ConnectionManager()
event_publisher = EventPublisher(connection_manager)
