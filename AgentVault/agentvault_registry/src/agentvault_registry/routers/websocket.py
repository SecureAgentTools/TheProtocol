"""
WebSocket Router
Handles real-time WebSocket connections for the registry
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException, Depends, Query, HTTPException
from typing import Callable, Dict, List, Set, Optional
import json
import asyncio
import os
import uuid
from datetime import datetime, timezone
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from agentvault_registry.database import get_db, get_db_context
from agentvault_registry.security import SECRET_KEY, ALGORITHM
from agentvault_registry.models import Developer
import jwt  # PyJWT (§DEPS: python-jose is gone)
from jwt import PyJWTError as JWTError

# §RELEASEHARDEN D2 (2026-09-14) — THE JWT RIDES THE SUBPROTOCOL LIST, NEVER THE QUERY STRING.
# A browser cannot set a header on a WebSocket, so the console used to put the developer JWT into
# `?token=`; uvicorn then wrote the whole request line into the container log (the night before, a
# console token was read out of one such line). The client now offers two subprotocols,
# `theprotocol.v1` and `theprotocol.bearer.<jwt>`, and the server selects `theprotocol.v1` (a JWT is
# base64url, so it is a valid subprotocol token; the header is not part of any access line). The query
# form was accepted for one release, counted, so a bundle loaded before that roll kept reconnecting.
# §MTLSHOPS (d), V0377: REMOVED once its counter read zero (0 on all fourteen running registries over the 30 hours
# before the build; the one hit, sbx-beta 2026-09-14 05:43Z, was the V0367 canary's own old-bundle drive). The query
# form is refused with 1008 query_token_not_accepted and still counted, so a stale client stays visible;
# core/access_log_mask.py keeps masking whatever arrives that way.
WS_SUBPROTOCOL = "theprotocol.v1"
WS_BEARER_PREFIX = "theprotocol.bearer."

try:
    from prometheus_client import Counter as _PromCounter
    _WS_QUERY_TOKEN_TOTAL = _PromCounter(
        "registry_ws_query_token_total",
        "WebSocket connections that offered a query-string token (refused since V0377: the transport was removed)",
    )
except Exception:  # noqa: BLE001 — a second import in a test process registers the series twice
    class _NoopCounter:
        def inc(self, *_a, **_k):
            return None
    _WS_QUERY_TOKEN_TOTAL = _NoopCounter()


def _offered_subprotocols(websocket: WebSocket) -> List[str]:
    raw = websocket.headers.get("sec-websocket-protocol") or ""
    return [p.strip() for p in raw.split(",") if p.strip()]


def _token_from_subprotocol(websocket: WebSocket) -> Optional[str]:
    """The JWT the client offered as `theprotocol.bearer.<jwt>`, or None."""
    for p in _offered_subprotocols(websocket):
        if p.startswith(WS_BEARER_PREFIX) and len(p) > len(WS_BEARER_PREFIX):
            return p[len(WS_BEARER_PREFIX):]
    return None


def _select_subprotocol(websocket: WebSocket) -> Optional[str]:
    """What `accept()` must answer: the client that offered subprotocols closes the socket itself if the
    server selects none of them, so every accept (the real one and the reject-then-close one) selects
    `theprotocol.v1` when it was offered, and nothing when it was not."""
    return WS_SUBPROTOCOL if WS_SUBPROTOCOL in _offered_subprotocols(websocket) else None

logger = logging.getLogger(__name__)

router = APIRouter()


def _registry_ws_prefix() -> str:
    """Return a registry-specific prefix for Redis Pub/Sub channels.
    Prevents cross-contamination between prod and sandbox registries
    sharing the same Redis instance (Pub/Sub is global, not DB-scoped)."""
    name = os.getenv("REGISTRY_NAME", "default").lower().replace(" ", "-")
    return f"ws:{name}"


# ──────────────────────────────────────────────────────────────────────────
# Audience-filter predicates (#5, 2026-05-08)
# Each predicate takes the per-user `connection_users` entry (a dict) and
# returns True if the user should receive the broadcast. The Redis Pub/Sub
# layer serializes the audience name string; each worker's _local_broadcast
# resolves it to the predicate locally and applies before delivering.
# Existing callers that don't pass `audience` keep broadcast-to-all
# semantics (default None → no predicate → deliver to everyone).
# ──────────────────────────────────────────────────────────────────────────
_ADMIN_FLAGS = ('treasury', 'platform', 'enforcement', 'federation', 'support')


def _passes_prefs_filter(
    prefs: Optional[dict],
    notif_type: Optional[str],
    target_org_id: Optional[str],
) -> bool:
    """§bc3 T3.2b — per-developer prefs gate.

    Returns False = drop. Pre-conditions: caller has already determined this
    is a notification AND not critical (critical bypasses all mutes).
    """
    if prefs is None:
        return True  # defaults = deliver everything
    # delivery_in_app off → drop all non-critical
    if prefs.get("delivery_in_app", True) is False:
        return False
    # per-type mute
    if notif_type and prefs.get(f"mute_{notif_type}", False) is True:
        return False
    # quiet hours (UTC hours 0-23). Window crosses midnight if start > end.
    qh_start = prefs.get("quiet_hours_start")
    qh_end = prefs.get("quiet_hours_end")
    if qh_start is not None and qh_end is not None:
        try:
            qh_start = int(qh_start)
            qh_end = int(qh_end)
            now_hour = datetime.now(timezone.utc).hour
            in_window = (
                (qh_start <= now_hour < qh_end) if qh_start < qh_end
                else (now_hour >= qh_start or now_hour < qh_end)
            )
            if in_window:
                return False
        except Exception:
            pass
    # §bc4 T4.8 — per-org mute (prefs may carry "mute_org_<org_id>": true)
    if target_org_id is not None and prefs.get(f"mute_org_{target_org_id}", False) is True:
        return False
    # §bc5 T5.4 — CI/CD opt-out toggles (handled at message-emit side, not
    # here, since the reactor knows which agents are owned vs org). This
    # function only sees the broadcast envelope.
    return True


AUDIENCE_PREDICATES: Dict[str, Callable[[dict], bool]] = {
    'admins': lambda u: bool(u.get('is_admin')) or any(
        bool(u.get(f'admin_{flag}')) for flag in _ADMIN_FLAGS
    ),
    'admin_treasury':    lambda u: bool(u.get('is_admin')) or bool(u.get('admin_treasury')),
    'admin_platform':    lambda u: bool(u.get('is_admin')) or bool(u.get('admin_platform')),
    'admin_enforcement': lambda u: bool(u.get('is_admin')) or bool(u.get('admin_enforcement')),
    'admin_federation':  lambda u: bool(u.get('is_admin')) or bool(u.get('admin_federation')),
    'admin_support':     lambda u: bool(u.get('is_admin')) or bool(u.get('admin_support')),
}


def _build_user_data(current_developer: Developer, *, user_id: Optional[str] = None) -> dict:
    """Build the connection_users entry for an authenticated developer.

    #5 (2026-05-08): captures the granular admin sub-flags so audience-
    filtered broadcasts (e.g. AgentSuspended → admin_enforcement) can
    deliver only to the right operators. Without this, the WS manager
    only knew about `is_admin` super-flag.

    §bc4 T4.2 (2026-05-19): also captures `org_ids` — the developer's
    OrganizationMember.org_id list — so org-scoped broadcasts can be
    routed via the `org_<org_id>` dynamic predicate in _local_broadcast.
    Empty list = solo developer. Reads org membership eagerly from the
    Developer's preloaded `organization_memberships` relationship if
    available; falls back to empty list (the org-scoped predicate then
    correctly excludes them).
    """
    org_ids: List[str] = []
    try:
        for mem in getattr(current_developer, 'organization_memberships', []) or []:
            oid = getattr(mem, 'organization_id', None)
            if oid:
                org_ids.append(str(oid))
    except Exception:
        org_ids = []
    # D6-621: the socket's admin audiences follow REQUIRE_ADMIN_2FA like every other admin gate. D6-821: and the rest of
    # what an inline admin check asks (the credential's scope, which a JWT socket always carries, and no forced password
    # change): the flags below are written only while the credential conveys admin authority.
    from agentvault_registry.security import admin_second_factor_ok, api_key_grants_admin
    _adm = (admin_second_factor_ok(current_developer) and api_key_grants_admin()
            and not bool(getattr(current_developer, 'must_change_password', False)))
    return {
        "id": user_id if user_id is not None else str(getattr(current_developer, 'id', '')),
        "email": current_developer.email,
        "name": getattr(current_developer, 'name', current_developer.email) or current_developer.email,
        "role": 'admin' if (_adm and getattr(current_developer, 'is_admin', False)) else 'developer',
        "is_admin": _adm and bool(getattr(current_developer, 'is_admin', False)),
        "admin_treasury":    _adm and bool(getattr(current_developer, 'admin_treasury', False)),
        "admin_platform":    _adm and bool(getattr(current_developer, 'admin_platform', False)),
        "admin_enforcement": _adm and bool(getattr(current_developer, 'admin_enforcement', False)),
        "admin_federation":  _adm and bool(getattr(current_developer, 'admin_federation', False)),
        "admin_support":     _adm and bool(getattr(current_developer, 'admin_support', False)),
        "developer_id": getattr(current_developer, 'id', None),
        "org_ids":           org_ids,
    }


class ConnectionManager:
    """Manages WebSocket connections and message broadcasting.

    Supports Redis Pub/Sub for cross-worker broadcasts: when multiple workers
    run behind a load balancer, a broadcast() on one worker publishes to Redis,
    and all workers (including the sender) receive the message and forward it
    to their local WebSocket connections.  If Redis is unavailable the manager
    gracefully degrades to local-only delivery (original behaviour).

    Channel names are namespaced per registry instance to prevent sandbox
    events from leaking into production feeds (Redis Pub/Sub is global).
    """

    REDIS_BROADCAST_CHANNEL = f"{_registry_ws_prefix()}:broadcast"
    REDIS_TOPIC_PREFIX = f"{_registry_ws_prefix()}:topic:"
    # V0650 (g): the one topic that wakes waiting GET /chat/sync calls. Its `chat:` prefix keeps it off the socket:
    # topic_allowed refuses every chat: topic but a developer's own chat:dev:<id>.
    CHAT_WAKE_TOPIC = "chat:wake"

    def __init__(self):
        # Store connections by user_id
        self.active_connections: Dict[str, WebSocket] = {}
        # Store user details for each connection
        self.connection_users: Dict[str, dict] = {}
        # Track subscriptions (e.g., which agents a user is watching)
        self.subscriptions: Dict[str, Set[str]] = {}
        # Redis Pub/Sub state
        self._pubsub = None
        self._pubsub_task: Optional[asyncio.Task] = None
        self._subscribed_channels: Set[str] = set()
        self._pubsub_lock: asyncio.Lock = asyncio.Lock()
        # V0650 (g): principal key ('dev:<id>' / 'agt:<did>') -> the Futures of this worker's waiting sync calls
        self._chat_waiters: Dict[str, Set[asyncio.Future]] = {}

    # ------------------------------------------------------------------
    # V0650 (g): waiting sync calls (GET /api/v1/chat/sync?wait=)
    # ------------------------------------------------------------------

    def chat_waiter_add(self, key: str) -> asyncio.Future:
        """Arm one waiter for a principal on this worker; the caller removes it (chat_waiter_remove) in a finally."""
        fut = asyncio.get_running_loop().create_future()
        self._chat_waiters.setdefault(key, set()).add(fut)
        return fut

    def chat_waiter_remove(self, key: str, fut: asyncio.Future) -> None:
        waiting = self._chat_waiters.get(key)
        if waiting is not None:
            waiting.discard(fut)
            if not waiting:
                self._chat_waiters.pop(key, None)

    def chat_waiter_count(self, key: str) -> int:
        return len(self._chat_waiters.get(key, ()))

    def _wake_local_chat(self, keys) -> int:
        """Resolve this worker's waiters for these principals; a waiter already resolved stays as it is."""
        woken = 0
        for key in keys or ():
            for fut in list(self._chat_waiters.get(str(key), ())):
                if not fut.done():
                    fut.set_result(True)
                    woken += 1
        return woken

    async def chat_wake_subscribe(self) -> None:
        """Have this worker hear wakes published by the others (once per worker; the listener starts with it)."""
        await self._ensure_topic_subscribed(self.CHAT_WAKE_TOPIC)

    async def wake_chat(self, keys) -> None:
        """A message reached these principals: wake their waiting sync calls here, and publish the keys for every other
        worker. The publisher does not subscribe the channel itself (broadcast_to_subscribers would): a worker hears
        wakes only once one of its own calls waits. A failed publish costs the other workers' waiters their bound."""
        keys = sorted({str(k) for k in (keys or ()) if k})
        if not keys:
            return
        self._wake_local_chat(keys)
        r = await self._get_redis()
        if r is None:
            return
        try:
            await r.publish(f"{self.REDIS_TOPIC_PREFIX}{self.CHAT_WAKE_TOPIC}", json.dumps({"payload": {"keys": keys}}))
        except Exception as e:  # noqa: BLE001
            logger.debug("[WS] chat wake publish failed: %s", e)

    # ------------------------------------------------------------------
    # Redis Pub/Sub helpers
    # ------------------------------------------------------------------

    async def _get_redis(self):
        """Import and return a Redis connection, or None."""
        try:
            from agentvault_registry.background_tasks.leader import get_redis
            return await get_redis()
        except Exception:
            return None

    # ── §PRESENCE ────────────────────────────────────────────────────────
    # `active_connections` is a PER-WORKER dict. Anything that asks it "is this
    # person online?" is really asking "is their socket on THIS worker?", which
    # on registry-a's ~39 workers is true about 1 time in 39. chat_service used
    # exactly that to decide whether to SKIP a notification for a message the
    # recipient had already received live, so the skip almost never happened.
    #
    # THE FAILURE DIRECTIONS ARE NOT SYMMETRIC, and that decides the design:
    #   * a MISSED suppression costs a duplicate bell — mildly annoying.
    #   * a WRONG suppression costs the notification entirely — the message is
    #     silently never announced.
    # So this key is only ever written by a LIVE socket and refreshed by the
    # client's own heartbeat, the TTL is short, and every unknown answer
    # (no Redis, no key, any exception) resolves to NOT PRESENT — i.e. notify.
    PRESENCE_TTL = 90   # seconds; the client pings well inside this

    @staticmethod
    def _presence_key(user_id: str) -> str:
        return f"presence:ws:{user_id}"

    async def mark_present(self, user_id: str) -> None:
        """Called on connect and refreshed on every client heartbeat."""
        try:
            r = await self._get_redis()
            if r is not None:
                await r.setex(self._presence_key(str(user_id)), self.PRESENCE_TTL, "1")
        except Exception as e:  # noqa: BLE001 — presence is an optimisation, never a gate
            logger.debug("[WS] presence set failed for %s: %s", user_id, e)

    async def clear_present(self, user_id: str) -> None:
        try:
            r = await self._get_redis()
            if r is not None:
                await r.delete(self._presence_key(str(user_id)))
        except Exception as e:  # noqa: BLE001
            logger.debug("[WS] presence clear failed for %s: %s", user_id, e)

    async def is_present(self, user_id: str) -> bool:
        """True ONLY on a positive answer from Redis. Unknown ⇒ False ⇒ notify."""
        if str(user_id) in self.active_connections:
            return True          # this worker holds the socket: certain
        try:
            r = await self._get_redis()
            if r is None:
                return False
            return bool(await r.exists(self._presence_key(str(user_id))))
        except Exception:  # noqa: BLE001
            return False

    async def _ensure_pubsub(self):
        """Start Redis Pub/Sub listener if not already running."""
        if self._pubsub_task is not None and not self._pubsub_task.done():
            return  # Already running
        async with self._pubsub_lock:
            await self._ensure_pubsub_locked()

    async def _ensure_pubsub_locked(self):
        """_ensure_pubsub's work, for a caller that already holds _pubsub_lock.

        SEC-02 (§SECBATCH wave 3, 2026-10-16): asyncio.Lock is not reentrant. _ensure_topic_subscribed holds the lock
        and, with no Pub/Sub connection (Redis unreachable since the process started, or a listener that died), called
        _ensure_pubsub, which waited for the same lock: that task waited on itself forever while holding the lock, and
        every later connect, broadcast and topic broadcast of the worker waited behind it. Nothing takes the lock twice
        now: a holder of the lock calls this, everything else calls _ensure_pubsub."""
        if self._pubsub_task is not None and not self._pubsub_task.done():
            return
        r = await self._get_redis()
        if r is None:
            return
        try:
            self._pubsub = r.pubsub()
            await self._pubsub.subscribe(self.REDIS_BROADCAST_CHANNEL)
            self._subscribed_channels = {self.REDIS_BROADCAST_CHANNEL}
            self._pubsub_task = asyncio.create_task(self._pubsub_listener())
            logger.info("[WS] Redis Pub/Sub listener started")
        except Exception as e:
            logger.warning(f"[WS] Failed to start Redis Pub/Sub: {e}")
            self._pubsub = None

    async def _ensure_topic_subscribed(self, topic: str):
        """Subscribe the Pub/Sub connection to a topic channel if needed."""
        channel = f"{self.REDIS_TOPIC_PREFIX}{topic}"
        if channel in self._subscribed_channels:
            return
        async with self._pubsub_lock:
            if channel in self._subscribed_channels:
                return
            if self._pubsub is None:
                await self._ensure_pubsub_locked()
            if self._pubsub is not None:
                try:
                    await self._pubsub.subscribe(channel)
                    self._subscribed_channels.add(channel)
                except Exception as e:
                    logger.warning(f"[WS] Failed to subscribe to Redis channel {channel}: {e}")

    async def _pubsub_listener(self):
        """Background task: read Redis Pub/Sub messages, forward to local connections."""
        try:
            while True:
                if self._pubsub is None:
                    break
                try:
                    async with self._pubsub_lock:
                        message = await self._pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=1.0
                        )
                except Exception as e:
                    if "already waiting" not in str(e):
                        logger.error(f"[WS] Pub/Sub get_message error: {e}")
                    await asyncio.sleep(1)
                    continue

                if message and message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                    except (json.JSONDecodeError, TypeError):
                        continue

                    channel = message.get("channel")
                    if isinstance(channel, bytes):
                        channel = channel.decode()

                    if channel == self.REDIS_BROADCAST_CHANNEL:
                        await self._local_broadcast(
                            data.get("payload", {}),
                            exclude_user=data.get("exclude_user"),
                            audience=data.get("audience"),
                        )
                    elif channel and channel.startswith(self.REDIS_TOPIC_PREFIX):
                        topic = channel[len(self.REDIS_TOPIC_PREFIX):]
                        await self._local_broadcast_to_subscribers(
                            topic, data.get("payload", {})
                        )

                await asyncio.sleep(0.01)  # Prevent busy-loop
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[WS] Pub/Sub listener died: {e}")
        finally:
            # Clean up
            if self._pubsub is not None:
                try:
                    await self._pubsub.unsubscribe()
                    await self._pubsub.close()
                except Exception:
                    pass
                self._pubsub = None
            self._subscribed_channels.clear()
            logger.info("[WS] Redis Pub/Sub listener stopped")

    # ------------------------------------------------------------------
    # Connection lifecycle (unchanged)
    # ------------------------------------------------------------------

    async def connect(self, websocket: WebSocket, user_id: str, user_data: dict):
        """Accept a new WebSocket connection"""
        await websocket.accept(subprotocol=_select_subprotocol(websocket))
        self.active_connections[user_id] = websocket
        self.connection_users[user_id] = user_data
        self.subscriptions[user_id] = set()

        logger.info(f"WebSocket connected: {user_id} ({user_data.get('email', 'unknown')})")

        # §PRESENCE — fleet-visible, so a sibling worker can tell that this
        # person is live and skip a notification they already received.
        await self.mark_present(user_id)

        # Lazily start the Pub/Sub listener on first connection
        await self._ensure_pubsub()

        # Send connection confirmation
        await self.send_personal_message({
            "type": "connected",
            "data": {
                "message": "WebSocket connection established",
                "user": user_data
            }
        }, user_id)

    def disconnect(self, user_id: str):
        """Remove a WebSocket connection"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            del self.connection_users[user_id]
            del self.subscriptions[user_id]
            # §PRESENCE — best effort: this is sync, so the delete is scheduled.
            # If it never runs the key still expires within PRESENCE_TTL, and the
            # only cost of that window is a suppressed duplicate, never a lost
            # notification (an absent key already means "notify").
            try:
                import asyncio as _aio
                _aio.get_running_loop().create_task(self.clear_present(user_id))
            except Exception:  # noqa: BLE001 — no loop, or shutting down
                pass
            logger.info(f"WebSocket disconnected: {user_id}")

    async def send_personal_message(self, message: dict, user_id: str):
        """Send a message to a specific user"""
        if user_id in self.active_connections:
            # Add metadata to message
            message["timestamp"] = datetime.now(timezone.utc).isoformat()
            message["id"] = f"msg_{datetime.now(timezone.utc).timestamp()}"

            try:
                await self.active_connections[user_id].send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to {user_id}: {e}")
                # Remove dead connection
                self.disconnect(user_id)

    # ------------------------------------------------------------------
    # Local-only delivery (called from Pub/Sub listener or as fallback)
    # ------------------------------------------------------------------

    async def _local_broadcast(
        self,
        message: dict,
        exclude_user: Optional[str] = None,
        audience: Optional[str] = None,
    ):
        """Send a message to all local WebSocket connections (no Redis publish).

        #5 (2026-05-08) — audience filter. When `audience` is set and resolves
        to a known predicate in `AUDIENCE_PREDICATES`, only deliver to users
        whose `connection_users` entry passes the predicate. Unknown audience
        names fall back to broadcast-to-all (logged once at warn) so a typo
        doesn't silently swallow notifications.

        §bc3 T3.2b (2026-05-19) — per-user notification prefs filter. Layered
        AFTER the audience predicate. ONLY affects messages with type=='notification'
        — other event types bypass. CRITICAL notifications ALWAYS deliver
        (no opt-out). Prefs are Redis-cached 60s keyed `dev_prefs:{user_id}`.
        Org-scoped (#bc4) prefilter also kicks in here for notifications carrying
        `data.target_org_id`.
        """
        message["timestamp"] = datetime.now(timezone.utc).isoformat()
        message["id"] = f"msg_{datetime.now(timezone.utc).timestamp()}"

        predicate: Optional[Callable[[dict], bool]] = None
        if audience:
            # §bc4 T4.3 — org_<id> audiences are resolved dynamically.
            if audience.startswith("org_"):
                try:
                    org_id = audience[len("org_"):]
                    predicate = lambda u, _oid=org_id: _oid in (u.get('org_ids') or [])
                except Exception:
                    predicate = None
            if predicate is None:
                predicate = AUDIENCE_PREDICATES.get(audience)
            # user_<id> targeted audiences (cross-device sync, org-lifecycle).
            if predicate is None and audience.startswith("user_"):
                try:
                    target_uid = audience[len("user_"):]
                    predicate = lambda u, _uid=target_uid: u.get('id') == _uid
                except Exception:
                    predicate = None
            if predicate is None:
                logger.warning(
                    f"[WS] Unknown audience '{audience}' — falling back to broadcast-to-all"
                )

        is_notification = message.get("type") == "notification"
        notif_data = message.get("data") if is_notification else None
        notif_type = (notif_data or {}).get("type", "info") if is_notification else None
        is_critical_notification = is_notification and notif_type == "critical"
        msg_target_org_id = (notif_data or {}).get("target_org_id") if is_notification else None

        disconnected_users = []

        for user_id, websocket in self.active_connections.items():
            if user_id == exclude_user:
                continue
            user_info = self.connection_users.get(user_id, {})
            if predicate is not None:
                if not predicate(user_info):
                    continue
            # §bc4 T4.4 — org-scoped broadcast: receiver must be in the target org.
            if msg_target_org_id is not None and not is_critical_notification:
                user_org_ids = user_info.get('org_ids') or []
                if msg_target_org_id not in user_org_ids:
                    continue
            # §bc3 T3.2b — per-user notification prefs (only for notification
            # messages, never for critical, never for other event types).
            if is_notification and not is_critical_notification:
                try:
                    prefs = await self._get_dev_prefs(user_id)
                except Exception as e:
                    logger.debug(f"prefs fetch failed for {user_id}: {e} — defaulting to deliver")
                    prefs = None
                if not _passes_prefs_filter(prefs, notif_type, msg_target_org_id):
                    continue
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to {user_id}: {e}")
                disconnected_users.append(user_id)

        # Clean up dead connections
        for user_id in disconnected_users:
            self.disconnect(user_id)

    # ------------------------------------------------------------------
    # §bc3 T3.2b — per-developer notification preferences cache
    # ------------------------------------------------------------------

    async def _get_dev_prefs(self, user_id: str) -> Optional[dict]:
        """Redis-cached fetch of Developer.notification_prefs. 60s TTL.
        Returns None if the developer has no prefs (caller treats as defaults).
        Sentinel `__null__` is cached for has-row-no-prefs to avoid DB
        round-trips for the common case."""
        cache_key = f"dev_prefs:{user_id}"
        r = await self._get_redis()
        if r is not None:
            try:
                cached = await r.get(cache_key)
                if cached is not None:
                    if cached == b"__null__" or cached == "__null__":
                        return None
                    return json.loads(cached)
            except Exception:
                pass
        try:
            from agentvault_registry import models
            from agentvault_registry.database import get_db_context
            from sqlalchemy import select as _sel
            async with get_db_context() as db:
                r2 = await db.execute(
                    _sel(models.Developer.notification_prefs).where(
                        models.Developer.id == int(user_id)
                    )
                )
                row = r2.first()
                prefs = row[0] if row and row[0] else None
        except Exception as e:
            logger.debug(f"_get_dev_prefs DB lookup failed for {user_id}: {e}")
            return None
        if r is not None:
            try:
                if prefs is None:
                    await r.setex(cache_key, 60, b"__null__")
                else:
                    await r.setex(cache_key, 60, json.dumps(prefs))
            except Exception:
                pass
        return prefs

    async def _local_broadcast_to_subscribers(self, topic: str, message: dict):
        """Send a message to local connections subscribed to a topic (no Redis publish)."""
        if topic == self.CHAT_WAKE_TOPIC:     # V0650 (g): a wake for waiting sync calls, never a socket message
            self._wake_local_chat((message or {}).get("keys") or [])
            return
        message["timestamp"] = datetime.now(timezone.utc).isoformat()
        message["id"] = f"msg_{datetime.now(timezone.utc).timestamp()}"

        for user_id, topics in self.subscriptions.items():
            if topic in topics and user_id in self.active_connections:
                try:
                    await self.active_connections[user_id].send_json(message)
                except Exception as e:
                    logger.error(f"Error sending to subscriber {user_id}: {e}")

    # ------------------------------------------------------------------
    # Public broadcast methods (Redis Pub/Sub with local fallback)
    # ------------------------------------------------------------------

    async def broadcast(
        self,
        message: dict,
        exclude_user: Optional[str] = None,
        audience: Optional[str] = None,
    ):
        """Broadcast a message to all connected users across all workers.

        Publishes to Redis Pub/Sub so every worker's listener picks it up
        and forwards to its local connections.  Falls back to local-only
        delivery when Redis is unavailable.

        #5 (2026-05-08) — `audience` is a string identifier (e.g. 'admins',
        'admin_enforcement', 'admin_treasury') that's serialized into the
        Pub/Sub payload. Each worker resolves the predicate locally and
        applies the filter in `_local_broadcast`. Unknown audience strings
        fall back to broadcast-to-all (audit-warn on each occurrence).
        """
        await self._ensure_pubsub()
        r = await self._get_redis()
        if r is not None:
            try:
                payload = json.dumps({
                    "payload": message,
                    "exclude_user": exclude_user,
                    "audience": audience,
                })
                await r.publish(self.REDIS_BROADCAST_CHANNEL, payload)
                return  # Redis will deliver to all workers including this one
            except Exception as e:
                logger.warning(f"[WS] Redis publish failed, falling back to local: {e}")
        # Fallback: local only
        await self._local_broadcast(message, exclude_user, audience=audience)

    async def broadcast_to_subscribers(self, topic: str, message: dict):
        """Broadcast a message to users subscribed to a topic across all workers.

        Publishes to a topic-specific Redis channel so every worker's listener
        delivers to its locally-subscribed connections.  Falls back to local-only
        delivery when Redis is unavailable.
        """
        await self._ensure_pubsub()
        await self._ensure_topic_subscribed(topic)
        r = await self._get_redis()
        if r is not None:
            try:
                channel = f"{self.REDIS_TOPIC_PREFIX}{topic}"
                payload = json.dumps({"payload": message})
                await r.publish(channel, payload)
                return  # Redis will deliver to all workers including this one
            except Exception as e:
                logger.warning(f"[WS] Redis publish to topic {topic} failed, falling back to local: {e}")
        # Fallback: local only
        await self._local_broadcast_to_subscribers(topic, message)

    def subscribe(self, user_id: str, topic: str):
        """Subscribe a user to a topic"""
        if user_id in self.subscriptions:
            self.subscriptions[user_id].add(topic)
            logger.debug(f"User {user_id} subscribed to {topic}")
            # Ensure the Redis Pub/Sub connection listens on this topic channel.
            # _ensure_topic_subscribed is async so we schedule it as a fire-and-forget task.
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._ensure_topic_subscribed(topic))
            except RuntimeError:
                pass  # No running loop — Redis subscription will happen on next broadcast

    def unsubscribe(self, user_id: str, topic: str):
        """Unsubscribe a user from a topic"""
        if user_id in self.subscriptions:
            self.subscriptions[user_id].discard(topic)
            logger.debug(f"User {user_id} unsubscribed from {topic}")

    def get_connection_count(self) -> int:
        """Get the number of active connections"""
        return len(self.active_connections)

    def get_user_info(self, user_id: str) -> Optional[dict]:
        """Get user info for a connection"""
        return self.connection_users.get(user_id)


# Global connection manager instance
manager = ConnectionManager()


async def get_current_user_ws(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Developer:
    """Authenticate a WebSocket connection: the JWT offered as the `theprotocol.bearer.<jwt>` subprotocol
    first; a `?token=` query parameter is refused since V0377 (§MTLSHOPS (d), see the module head).

    On auth failure, accept-then-close so the client receives a real WS
    close frame with code=1008 (Policy Violation) instead of the HTTP 500
    that an HTTPException-in-WS-dep produces. Raising HTTPException inside
    a WebSocket dependency does not translate to a clean close — browsers
    see abnormal closure (1006) and cannot distinguish auth failure from
    a network blip, which drives retry storms on the frontend.
    """
    async def _reject(reason: str) -> None:
        # Accept first so the close is a proper WS close frame with code=1008.
        # Pre-accept close sends an HTTP rejection that browsers report as 1006.
        try:
            await websocket.accept(subprotocol=_select_subprotocol(websocket))
        except Exception:
            pass  # Already accepted or in unexpected state — ignore
        # §BATCH0911 — raise the exception Starlette HANDLES for a websocket (its
        # ExceptionMiddleware closes the accepted socket with this code and reason), not
        # WebSocketDisconnect, which escaped the app from inside a dependency: every expired-token
        # reconnect after a recreate logged two tracebacks and "Exception in ASGI application"
        # while the client had already been told 1008. Prototyped in the image: same 1008 and
        # reason on the client, nothing escapes.
        raise WebSocketException(code=1008, reason=reason)

    sub_token = _token_from_subprotocol(websocket)
    if sub_token:
        token = sub_token
    elif token:
        _WS_QUERY_TOKEN_TOTAL.inc()
        logger.warning(
            "WebSocket refused a query-string token (the transport was removed at V0377: the token is written "
            "to access logs; send it as the theprotocol.bearer subprotocol)"
        )
        await _reject("query_token_not_accepted")

    if not token:
        await _reject("unauthorized")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        developer_id = payload.get("sub")
        if not developer_id:
            await _reject("invalid_token")

        result = await db.execute(
            select(Developer).where(Developer.id == int(developer_id))
        )
        developer = result.scalar_one_or_none()
        if not developer:
            await _reject("unknown_developer")

        return developer
    except (WebSocketException, WebSocketDisconnect):
        raise
    except JWTError as e:
        logger.warning(f"JWT decode error during WS auth: {e}")
        await _reject("invalid_token")
    except Exception as e:
        logger.error(f"WebSocket auth error: {e}")
        await _reject("auth_failed")


def topic_allowed(user_data: dict, topic: str) -> bool:
    """Who may subscribe to which topic on the main socket (§TWOAGENT, 2026-09-24).

    A topic is a delivery channel, and the manager hands every message on it to every connection that holds it, so
    holding a topic is reading it. `subscribe` used to add ANY topic a connected developer named, including another
    developer's `chat:dev:<id>`, the channel their chat messages travel on. Now:
      chat:dev:<id>                  only that developer (the socket subscribes its own on connect)
      docker_stats                   admins only (host and container telemetry)
      system.events, event:<name>    anyone (the public ledger feed; /ws/events serves it without auth)
      agent:<id>                     anyone (public card changes; the owner's identity is not in them)
    Anything else is refused: nothing is published on it today, and a private topic added later must be opened here
    on purpose, never inherited by default."""
    t = str(topic or "")
    uid = str((user_data or {}).get("id") or "")
    if t.startswith("chat:"):
        return bool(uid) and t == f"chat:dev:{uid}"
    if t == "docker_stats":
        return bool((user_data or {}).get("is_admin"))
    return t == "system.events" or t.startswith("event:") or t.startswith("agent:")


async def _subscribe_checked(user_id: str, user_data: dict, topic: str) -> bool:
    """Subscribe `user_id` to `topic` if `topic_allowed` says so, and tell the caller either way."""
    if not topic_allowed(user_data, topic):
        logger.warning("[WS] subscription to %r refused for user %s", topic, user_id)
        await manager.send_personal_message({
            "type": "error",
            "data": {"message": "subscription refused: this topic is not yours to read", "topic": topic}
        }, user_id)
        return False
    manager.subscribe(user_id, topic)
    await manager.send_personal_message({"type": "subscribed", "data": {"topic": topic}}, user_id)
    return True


async def _release_ws_session(db: AsyncSession) -> None:
    """§WSPOOL (V0637): hand a websocket's request-scoped session back before the socket's receive loop.

    A websocket's dependencies live as long as the socket: the session get_current_user_ws and the endpoint share (one
    cached get_db) held its pooled connection idle in a transaction for the socket's whole life, a console tab's whole
    life. Measured 2026-10-24 on sbx-beta: 75 s, the length of a console walk, after the endpoint's organization_members
    read, with idle_in_transaction_session_timeout 0 (sbx-beta and EU alike), so nothing reaps it; a worker's pool is
    DB_POOL_SIZE + DB_MAX_OVERFLOW (5 + 5 there), and a read that finds it full waits up to the pool's 30 s (the
    console nightly's views walk read GET /agora/equity-map "still reading after 20 s" three times that night). Nothing
    after the setup reads the database through this session: closing it ends the transaction and returns the
    connection; get_db's own close at the socket's end is then a no-op."""
    try:
        await db.close()
    except Exception as e:  # noqa: BLE001 — a dead connection has nothing left to hand back
        logger.debug(f"websocket session release: {e!r}")


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    current_developer: Developer = Depends(get_current_user_ws),
    db: AsyncSession = Depends(get_db)
):
    """Main WebSocket endpoint"""
    user_id = str(current_developer.id)
    user_data = _build_user_data(current_developer, user_id=user_id)
    # §bc4 T4.2 — async lookup of OrganizationMember rows. _build_user_data
    # tries the eager-relationship first; this is the fallback so a closed
    # SA session doesn't leave org_ids empty.
    if not user_data.get("org_ids"):
        try:
            from sqlalchemy import select as _sel
            from agentvault_registry import models as _models
            r = await db.execute(
                _sel(_models.OrganizationMember.organization_id).where(
                    _models.OrganizationMember.developer_id == current_developer.id
                )
            )
            user_data["org_ids"] = [str(row[0]) for row in r.fetchall() if row[0]]
        except Exception as e:
            logger.debug(f"org_ids lookup failed for dev={current_developer.id}: {e}")
    await _release_ws_session(db)   # §WSPOOL: the socket holds no connection from here

    # Connect the user
    await manager.connect(websocket, user_id, user_data)

    # §OURSTATE-1 — server-side chat subscription: every authenticated socket
    # hears its own OurChat topic with no client round-trip. Delivery for
    # agent participants resolves DID→owner developer (the notify_agent_owners
    # pattern), so this ONE per-developer topic is the whole realtime plane.
    manager.subscribe(user_id, f"chat:dev:{user_id}")

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            
            # Handle different message types
            message_type = data.get("type")
            message_data = data.get("data", {})
            
            logger.debug(f"Received message from {user_id}: {message_type}")
            
            # Message handlers
            if message_type == "ping":
                # §PRESENCE — the heartbeat is what keeps the key alive. Presence
                # is therefore always something a live socket ASSERTED recently,
                # never something inferred from an absence.
                await manager.mark_present(user_id)
                # Heartbeat response
                await manager.send_personal_message({
                    "type": "pong",
                    "data": {"timestamp": message_data.get("timestamp")}
                }, user_id)
            
            elif message_type == "subscribe":
                # Subscribe to a topic (e.g., specific agent updates), if it is the caller's to read
                topic = message_data.get("topic")
                if topic:
                    await _subscribe_checked(user_id, user_data, topic)
            
            elif message_type == "unsubscribe":
                # Unsubscribe from a topic
                topic = message_data.get("topic")
                if topic:
                    manager.unsubscribe(user_id, topic)
                    await manager.send_personal_message({
                        "type": "unsubscribed",
                        "data": {"topic": topic}
                    }, user_id)
            
            elif message_type == "agent.subscribe":
                # Subscribe to specific agent updates
                agent_id = message_data.get("agent_id")
                if agent_id:
                    await _subscribe_checked(user_id, user_data, f"agent:{agent_id}")
            
            elif message_type == "metrics.request":
                # Fetch real metrics from database
                metrics = await _fetch_live_metrics()
                await manager.send_personal_message({
                    "type": "metrics.update",
                    "data": metrics
                }, user_id)
            
            else:
                # Unknown message type
                await manager.send_personal_message({
                    "type": "error",
                    "data": {"message": f"Unknown message type: {message_type}"}
                }, user_id)
    
    except WebSocketDisconnect:
        manager.disconnect(user_id)
        # Tell the ADMINS that user disconnected (presence is not everyone's to know; this went to every connected
        # tenant until 2026-09-24, §TWOAGENT)
        await manager.broadcast({
            "type": "user.disconnected",
            "data": {"user_id": user_id}
        }, audience="admins", exclude_user=user_id)
    
    except Exception as e:
        logger.error(f"WebSocket error for {user_id}: {e}")
        manager.disconnect(user_id)


# Utility functions to send events from other parts of the application

async def notify_agent_update(agent_id: str, agent_data: dict):
    """Notify subscribers about agent updates"""
    await manager.broadcast_to_subscribers(f"agent:{agent_id}", {
        "type": "agent.update",
        "data": {
            "agent_id": agent_id,
            **agent_data
        }
    })


async def notify_agent_status_change(agent_id: str, status: str):
    """Notify about agent status changes"""
    await manager.broadcast_to_subscribers(f"agent:{agent_id}", {
        "type": "agent.status",
        "data": {
            "agent_id": agent_id,
            "status": status
        }
    })


async def notify_proposal_update(proposal_id: str, proposal_data: dict):
    """Notify about governance proposal updates"""
    await manager.broadcast({
        "type": "proposal.update",
        "data": {
            "proposal_id": proposal_id,
            **proposal_data
        }
    })


async def notify_staking_reward(user_id: str, amount: str):
    """Notify user about staking rewards"""
    await manager.send_personal_message({
        "type": "staking.reward",
        "data": {
            "amount": amount,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    }, user_id)


async def notify_federation_sync(registry_id: str, agents_synced: int):
    """Notify about federation sync events"""
    await manager.broadcast({
        "type": "federation.sync",
        "data": {
            "registry_id": registry_id,
            "agents_synced": agents_synced
        }
    })


async def notify_peer_url_auto_corrected(
    peer_id: int,
    peer_name: str,
    old_url: str,
    new_url: str,
    drift_type: str,
):
    """§pass-N (2026-05-21) — broadcast peer URL self-heal to WS subscribers.

    Companion to the existing EventStore emit in
    `background_tasks/reactor_peer_url_self_heal.py` (which is audit-only).
    The frontend Federation.vue listens for this event_type to flash the edges
    incident to the self-healed peer.

    Best-effort, non-blocking: caller wraps in try/except.
    """
    from datetime import datetime, timezone
    await manager.broadcast({
        "type": "PeerRegistryUrlAutoCorrected",
        "data": {
            "peer_id": peer_id,
            "peer_name": peer_name,
            "old_url": old_url,
            "new_url": new_url,
            "drift_type": drift_type,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    })


async def send_notification(user_id: str, title: str, message: str, notification_type: str = "info"):
    """Send a general notification to a user"""
    await manager.send_personal_message({
        "type": "notification",
        "data": {
            "title": title,
            "message": message,
            "type": notification_type
        }
    }, user_id)


async def broadcast_notification(
    title: str,
    message: str,
    notification_type: str = "info",
    audience: Optional[str] = None,
):
    """Broadcast a notification to all users (or an audience subset).

    #5 (2026-05-08) — `audience` is a string identifier resolved against
    `AUDIENCE_PREDICATES`. Common values:
      None                    → broadcast to ALL connected users (default,
                                preserves existing-caller behavior).
      'admins'                → users with is_admin OR any admin_<flag>.
      'admin_treasury'        → treasury admins (mint, fee_collector,
                                FundingRequestCreated audience).
      'admin_enforcement'     → enforcement admins (suspensions, slashes,
                                disputes audience).
      'admin_platform'        → platform admins (infra, webhooks, agents).
      'admin_federation'      → federation admins (peer ops, drift).
      'admin_support'         → support admins (tickets).
    Unknown identifiers fall back to broadcast-to-all + log a warning.
    """
    await manager.broadcast(
        {
            "type": "notification",
            "data": {
                "title": title,
                "message": message,
                "type": notification_type,
            },
        },
        audience=audience,
    )


async def _fetch_live_metrics() -> dict:
    """Fetch real metrics from the database. Returns a dict suitable for WS broadcast."""
    from agentvault_registry.models import Agent, Stake, GovernanceProposal, PeerRegistry

    try:
        async with get_db_context() as db:
            total_agents = (await db.execute(select(func.count(Agent.id)))).scalar() or 0
            active_agents = (await db.execute(
                select(func.count(Agent.id)).where(Agent.status == "active")
            )).scalar() or 0
            total_staked = (await db.execute(
                select(func.coalesce(func.sum(Stake.amount), 0)).where(Stake.is_active == True)
            )).scalar() or 0
            proposals_active = (await db.execute(
                select(func.count(GovernanceProposal.id)).where(GovernanceProposal.status == "VOTING")
            )).scalar() or 0
            proposals_passed = (await db.execute(
                select(func.count(GovernanceProposal.id)).where(GovernanceProposal.status == "PASSED")
            )).scalar() or 0
            federation_peers = (await db.execute(
                select(func.count(PeerRegistry.id))
            )).scalar() or 0

        return {
            "total_agents": total_agents,
            "active_agents": active_agents,
            "total_staked": str(total_staked),
            "total_rewards": "0.00",  # Rewards require TEG query — omit for now
            "proposals_active": proposals_active,
            "proposals_passed": proposals_passed,
            "federation_peers": federation_peers,
            "daily_transactions": 0,  # Would require EventStore query
        }
    except Exception as e:
        logger.error(f"Failed to fetch live metrics: {e}")
        return {
            "total_agents": 0,
            "active_agents": 0,
            "total_staked": "0.00",
            "total_rewards": "0.00",
            "proposals_active": 0,
            "proposals_passed": 0,
            "federation_peers": 0,
            "daily_transactions": 0,
        }


# Background task to periodically send metrics updates
async def metrics_updater():
    """Periodically broadcast metrics updates to all connected users"""
    while True:
        try:
            # Wait 30 seconds between updates
            await asyncio.sleep(30)
            
            # Only send if there are connected users
            if manager.get_connection_count() > 0:
                metrics = await _fetch_live_metrics()
                await manager.broadcast({
                    "type": "metrics.update",
                    "data": metrics
                })
        except Exception as e:
            logger.error(f"Error in metrics updater: {e}")


@router.websocket("/ws/agents/{agent_id}")
async def websocket_agent_endpoint(
    websocket: WebSocket,
    agent_id: str,
    current_developer: Developer = Depends(get_current_user_ws),
    db: AsyncSession = Depends(get_db)
):
    """Agent-specific WebSocket endpoint for monitoring a single agent"""
    user_id = str(current_developer.id)
    user_data = _build_user_data(current_developer, user_id=user_id)
    await _release_ws_session(db)   # §WSPOOL
    
    # Connect the user and automatically subscribe to the agent
    await manager.connect(websocket, f"{user_id}_agent_{agent_id}", user_data)
    manager.subscribe(f"{user_id}_agent_{agent_id}", f"agent:{agent_id}")
    
    # Send subscription confirmation
    await manager.send_personal_message({
        "type": "subscribed",
        "data": {
            "agent_id": agent_id,
            "message": f"Subscribed to agent {agent_id} updates"
        }
    }, f"{user_id}_agent_{agent_id}")
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            
            # Handle agent-specific messages
            message_type = data.get("type")
            message_data = data.get("data", {})
            
            if message_type == "ping":
                await manager.send_personal_message({
                    "type": "pong",
                    "data": {"timestamp": message_data.get("timestamp")}
                }, f"{user_id}_agent_{agent_id}")
            
            elif message_type == "subscribe":
                # Already subscribed on connection
                await manager.send_personal_message({
                    "type": "subscribed",
                    "data": {"agent_id": agent_id}
                }, f"{user_id}_agent_{agent_id}")
            
            else:
                await manager.send_personal_message({
                    "type": "error",
                    "data": {"message": f"Unknown message type: {message_type}"}
                }, f"{user_id}_agent_{agent_id}")
    
    except WebSocketDisconnect:
        manager.disconnect(f"{user_id}_agent_{agent_id}")
    except Exception as e:
        logger.error(f"WebSocket error for agent {agent_id}: {e}")
        manager.disconnect(f"{user_id}_agent_{agent_id}")


@router.websocket("/ws/events")
async def websocket_events_endpoint(
    websocket: WebSocket,
):
    """Public events WebSocket endpoint for system-wide event streaming.
    No auth required — this streams public ledger data for Mission Control."""
    conn_id = f"public_{uuid.uuid4().hex[:12]}_events"
    user_data = {"id": conn_id, "role": "public"}

    await manager.connect(websocket, conn_id, user_data)
    manager.subscribe(conn_id, "system.events")

    await manager.send_personal_message({
        "type": "subscribed",
        "data": {
            "events": ["agent.created", "agent.updated", "agent.deleted",
                       "staking.updated", "proposal.created"]
        }
    }, conn_id)

    try:
        while True:
            data = await websocket.receive_json()

            # Support both frontend formats:
            #   { type: "ping", data: {...} }
            #   { action: "subscribe", channel: "events:all" }
            message_type = data.get("type") or data.get("action")
            message_data = data.get("data", {})

            if message_type == "ping":
                await manager.send_personal_message({
                    "type": "pong",
                    "data": {"timestamp": message_data.get("timestamp")}
                }, conn_id)

            elif message_type == "subscribe":
                events = message_data.get("events", [])
                channel = data.get("channel", "")
                if channel == "events:all":
                    manager.subscribe(conn_id, "system.events")
                for event in events:
                    manager.subscribe(conn_id, f"event:{event}")

                await manager.send_personal_message({
                    "type": "subscribed",
                    "data": {"events": events or ["all"]}
                }, conn_id)

    except WebSocketDisconnect:
        manager.disconnect(conn_id)
    except Exception as e:
        logger.error(f"WebSocket events error: {e}")
        manager.disconnect(conn_id)


@router.websocket("/ws/metrics")
async def websocket_metrics_endpoint(
    websocket: WebSocket,
    current_developer: Developer = Depends(get_current_user_ws),
    db: AsyncSession = Depends(get_db)
):
    """Metrics WebSocket endpoint for real-time metrics streaming"""
    user_id = str(current_developer.id)
    user_data = _build_user_data(current_developer, user_id=user_id)
    await _release_ws_session(db)   # §WSPOOL
    
    # Connect the user for metrics streaming
    await manager.connect(websocket, f"{user_id}_metrics", user_data)
    
    # Send initial metrics
    await manager.send_personal_message({
        "type": "metrics_update",
        "data": {
            "total_agents": 250,
            "active_agents": 198,
            "total_staked": "1000000.00",
            "total_rewards": "50000.00",
            "proposals_active": 5,
            "proposals_passed": 45,
            "federation_peers": 12,
            "daily_transactions": 1024
        }
    }, f"{user_id}_metrics")
    
    # Start metrics update loop
    metrics_task = None
    
    try:
        # Create a task to send periodic metrics
        async def send_metrics():
            while True:
                await asyncio.sleep(5)  # Send metrics every 5 seconds
                await manager.send_personal_message({
                    "type": "metrics_update",
                    "data": {
                        "total_agents": 250 + (asyncio.get_event_loop().time() % 10),
                        "active_agents": 198,
                        "total_staked": "1000000.00",
                        "total_rewards": "50000.00",
                        "proposals_active": 5,
                        "proposals_passed": 45,
                        "federation_peers": 12,
                        "daily_transactions": 1024 + int(asyncio.get_event_loop().time() % 100)
                    }
                }, f"{user_id}_metrics")
        
        metrics_task = asyncio.create_task(send_metrics())
        
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            
            message_type = data.get("type")
            message_data = data.get("data", {})
            
            if message_type == "ping":
                await manager.send_personal_message({
                    "type": "pong",
                    "data": {"timestamp": message_data.get("timestamp")}
                }, f"{user_id}_metrics")
    
    except WebSocketDisconnect:
        if metrics_task:
            metrics_task.cancel()
        manager.disconnect(f"{user_id}_metrics")
    except Exception as e:
        logger.error(f"WebSocket metrics error: {e}")
        if metrics_task:
            metrics_task.cancel()
        manager.disconnect(f"{user_id}_metrics")


@router.websocket("/ws/agents/status")
async def websocket_agent_status_endpoint(
    websocket: WebSocket,
    current_developer: Developer = Depends(get_current_user_ws),
    db: AsyncSession = Depends(get_db)
):
    """Agent status WebSocket endpoint for monitoring multiple agents' status"""
    user_id = str(current_developer.id)
    user_data = _build_user_data(current_developer, user_id=user_id)
    await _release_ws_session(db)   # §WSPOOL
    
    # Connect the user for status monitoring
    await manager.connect(websocket, f"{user_id}_status", user_data)
    
    await manager.send_personal_message({
        "type": "connected",
        "data": {"message": "Agent status monitoring connected"}
    }, f"{user_id}_status")
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            
            message_type = data.get("type")
            message_data = data.get("data", {})
            
            if message_type == "ping":
                await manager.send_personal_message({
                    "type": "pong",
                    "data": {"timestamp": message_data.get("timestamp")}
                }, f"{user_id}_status")
            
            elif message_type == "subscribe_status":
                # Subscribe to status updates for specific agents
                agent_ids = message_data.get("agent_ids", [])
                for agent_id in agent_ids:
                    manager.subscribe(f"{user_id}_status", f"agent_status:{agent_id}")
                
                await manager.send_personal_message({
                    "type": "subscribed",
                    "data": {
                        "agent_ids": agent_ids,
                        "message": f"Subscribed to status updates for {len(agent_ids)} agents"
                    }
                }, f"{user_id}_status")
    
    except WebSocketDisconnect:
        manager.disconnect(f"{user_id}_status")
    except Exception as e:
        logger.error(f"WebSocket status error: {e}")
        manager.disconnect(f"{user_id}_status")


# ========================================
# DOCKER STATS WEBSOCKET - NEW FUNCTIONALITY
# ========================================

# Check if Docker monitoring is available
try:
    import docker
    import psutil
    DOCKER_MONITORING_AVAILABLE = True
except ImportError:
    DOCKER_MONITORING_AVAILABLE = False

class DockerStatsWebSocket:
    """WebSocket handler for real-time Docker container statistics."""
    
    def __init__(self):
        self.monitoring_task = None
        self.should_broadcast = False
        
    async def broadcast_docker_stats(self, manager: ConnectionManager, interval: int = 5):
        """Broadcast Docker stats to all connected clients at specified interval."""
        if not DOCKER_MONITORING_AVAILABLE:
            logger.warning("Docker monitoring not available - missing required packages")
            return
            
        self.should_broadcast = True
        client = None
        
        try:
            # §F6 WP6.2 slice 2: CONTAINER_OBSERVE_VIA=runner samples THIS frame's own compose project through the frame
            # runner (off the event loop); unset keeps the socket read and its host-wide 'agentvault' filter
            from agentvault_registry.services import host_observe as _ho
            _via = _ho.observe_via()
            client = docker.from_env() if _via == "local" else None
            
            while self.should_broadcast:
                try:
                    stats = {}
                    
                    # Get container stats
                    if _via == "runner":
                        _res = await asyncio.to_thread(_ho.stats)
                        _containers = [_ho.RunnerContainer(r) for r in (_res.get("containers") or [])]
                    else:
                        _containers = [c for c in client.containers.list(ignore_removed=True) if 'agentvault' in c.name.lower()]
                    for container in _containers:
                        container_stats = container.stats(stream=False)
                            
                        # Calculate CPU percentage
                        cpu_delta = container_stats["cpu_stats"]["cpu_usage"]["total_usage"] - \
                                   container_stats["precpu_stats"]["cpu_usage"]["total_usage"]
                        system_cpu_delta = container_stats["cpu_stats"]["system_cpu_usage"] - \
                                          container_stats["precpu_stats"]["system_cpu_usage"]
                        number_cpus = len(container_stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [])) or 1
                        cpu_percentage = 0.0
                        if system_cpu_delta > 0 and cpu_delta > 0:
                            cpu_percentage = (cpu_delta / system_cpu_delta) * number_cpus * 100.0
                            
                        # Calculate memory usage
                        memory_usage = container_stats["memory_stats"].get("usage", 0)
                        memory_limit = container_stats["memory_stats"].get("limit", 1)
                        memory_percentage = (memory_usage / memory_limit) * 100 if memory_limit > 0 else 0
                            
                        stats[container.name] = {
                            "status": container.status,
                            "cpu_percent": round(cpu_percentage, 2),
                            "memory_percent": round(memory_percentage, 2),
                            "memory_mb": round(memory_usage / (1024 * 1024), 2)
                        }
                    
                    # Get host system stats
                    host_stats = {
                        "cpu_percent": psutil.cpu_percent(interval=0.1),
                        "memory_percent": psutil.virtual_memory().percent,
                        "disk_percent": psutil.disk_usage('/').percent
                    }
                    
                    # Broadcast to all subscribers
                    await manager.broadcast_to_subscribers(
                        "docker_stats",
                        {
                            "type": "docker_stats_update",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "data": {
                                "containers": stats,
                                "host": host_stats
                            }
                        }
                    )
                    
                except Exception as e:
                    logger.error(f"Error broadcasting Docker stats: {e}")
                
                await asyncio.sleep(interval)
                
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
        finally:
            if client:
                client.close()
            self.should_broadcast = False
    
    def stop_broadcasting(self):
        """Stop the Docker stats broadcasting."""
        self.should_broadcast = False


# Global instance for Docker stats broadcasting
docker_stats_ws = DockerStatsWebSocket()


def may_watch_docker_stats(developer) -> bool:
    """§SECFIX (2026-09-25): the same rule as the HTTP twin, /api/v1/admin/docker-stats (require_admin_flag
    "admin_platform": the flag or legacy is_admin, never while a password change is forced). This socket subscribed ANY
    authenticated developer to host and container telemetry (manager.subscribe skips topic_allowed) and its get_stats
    called the HTTP handler with the developer object, around the handler's own dependency."""
    from agentvault_registry.security import admin_flag_credential   # D6-821: and the second factor, as the HTTP twin
    return admin_flag_credential(developer, "admin_platform")


@router.websocket("/ws/docker-stats")
async def websocket_docker_stats(
    websocket: WebSocket,
    developer: Developer = Depends(get_current_user_ws),
):
    """WebSocket endpoint for real-time Docker container statistics.

    §RELEASEHARDEN D2 — authenticated by the same dependency as every other socket. The old body called
    `get_current_user_ws(token)` with the token in the WEBSOCKET position, which raised inside its own
    try and closed every caller with "Invalid authentication": the route had never authenticated anyone.
    """
    if not may_watch_docker_stats(developer):
        logger.warning("[WS] /ws/docker-stats refused for developer %s: admin_platform required", getattr(developer, "id", "?"))
        await websocket.close(code=1008, reason="admin_platform required")
        return

    # Check if monitoring is available
    if not DOCKER_MONITORING_AVAILABLE:
        await websocket.close(code=1011, reason="Docker monitoring not available on this server")
        return

    try:
        # Connect to WebSocket
        await manager.connect(websocket, f"docker_{developer.id}", {
            "id": developer.id,
            "email": developer.email,
            "type": "docker_monitor"
        })
        
        # Subscribe to Docker stats updates
        manager.subscribe(f"docker_{developer.id}", "docker_stats")
        
        # Send initial connection confirmation
        await manager.send_personal_message({
            "type": "connection_established",
            "data": {
                "message": "Connected to Docker stats WebSocket",
                "broadcast_interval": 5
            }
        }, f"docker_{developer.id}")
        
        # Start broadcasting if not already running
        if not docker_stats_ws.should_broadcast:
            import asyncio
            docker_stats_ws.monitoring_task = asyncio.create_task(
                docker_stats_ws.broadcast_docker_stats(manager)
            )
        
        # Keep connection alive and handle messages
        while True:
            data = await websocket.receive_json()
            message_type = data.get("type")
            
            if message_type == "ping":
                await manager.send_personal_message({
                    "type": "pong",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }, f"docker_{developer.id}")
            
            elif message_type == "get_stats":
                # Manual request for current stats
                from ..routers.admin_health import get_docker_stats
                stats = await get_docker_stats(developer)
                await manager.send_personal_message({
                    "type": "docker_stats_snapshot",
                    "data": stats
                }, f"docker_{developer.id}")
                
    except WebSocketDisconnect:
        manager.disconnect(f"docker_{developer.id}")
        
        # Stop broadcasting if no more clients
        if not any("docker_" in client_id for client_id in manager.active_connections.keys()):
            docker_stats_ws.stop_broadcasting()
            
    except Exception as e:
        logger.error(f"WebSocket Docker stats error: {e}")
        manager.disconnect(f"docker_{developer.id}")
        
        # Stop broadcasting if error
        if not any("docker_" in client_id for client_id in manager.active_connections.keys()):
            docker_stats_ws.stop_broadcasting()
