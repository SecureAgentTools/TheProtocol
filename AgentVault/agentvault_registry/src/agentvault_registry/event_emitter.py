"""
Event Emitter for TEG and Registry services
This module can be imported by TEG/Registry to emit events to the Event Store

TITANIUM VAULT D1: Added idempotency key support and retry with exponential backoff.
Every financial event now carries a deterministic idempotency key to prevent
duplicate events on network retry. The EventStore deduplicates on this key.

§SOVKIT K1 (2026-09-14): the registry writes to its event store over HTTP only, through the frame's
mTLS sidecar; Kafka is private to the store (the registry's fire-and-forget producer was removed).
"""

import aiohttp
import ssl
import asyncio
import json
import logging
import os
import uuid
from decimal import Decimal
from urllib.parse import urlparse
from typing import Dict, Optional, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# §pass52: Observability + safety-invariants (Phase A + Phase D groundwork)
# ---------------------------------------------------------------------------
# Pure additive; no behavior change. Counters fire on every gate decision +
# every emit() call so we can prove the policy table is becoming authoritative
# before flipping to fail-closed (Phase J — deferred).
try:
    from prometheus_client import Counter as _PCounter
    _gate_decision_total = _PCounter(
        "event_emitter_gate_decision_total",
        "Emission gate decisions",
        ["event_type", "source_service", "decision"],
    )
    _unknown_event_type_total = _PCounter(
        "event_emitter_unknown_event_type_total",
        "Emit attempts for event types with no policy row (fail-open default)",
        ["event_type", "source_service"],
    )
    _idem_key_form_total = _PCounter(
        "event_emitter_idempotency_key_form_total",
        "Idempotency-key form on emit() calls (instrumentation for Phase D enforcement)",
        ["event_type", "key_form"],  # key_form: deterministic | random_uuid | null
    )
except ImportError:
    _gate_decision_total = None
    _unknown_event_type_total = None
    _idem_key_form_total = None


# BALANCE_MOVING_EVENT_TYPES — events that mutate agent balance projection.
# These MUST never have skip_in_projection=true and MUST carry a deterministic
# idempotency_key (Phase D enforcement). The constant is the single source of
# truth shared by Registry, TEG, and EventStore via the agentvault_common
# package (still being introduced; for now mirrored in each service).
BALANCE_MOVING_EVENT_TYPES = frozenset({
    "TokensIssued", "TokensTransferred", "TokensStaked", "TokensUnstaked",
    "BalanceCorrected", "DisputeSlash", "DisputeCompensationMinted",
    "TransactionFeeCollected", "RewardsAutoCompounded", "ProjectionSnapshot",
})


# ---------------------------------------------------------------------------
# Decimal-safe JSON serialization (2026-05-07 — defense in depth)
# ---------------------------------------------------------------------------
# Multiple emit sites (governance vote, federation peer-slash-config, agent
# export) silently 3-retried with "Object of type Decimal is not JSON
# serializable" — the SQLAlchemy Numeric column type maps to Decimal at
# runtime, and aiohttp's default JSON encoder can't handle it. Events were
# lost without surfacing as a hard failure (the wrapper's broad except
# swallowed it). This pre-serializer + `data=` instead of `json=` ensures
# Decimals (and a couple other common types) round-trip cleanly. Targeted
# fixes at the emit-site level are still in place; this is belt-and-braces.

def _emit_safe_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    raise TypeError(
        f"[event_emitter] Object of type {type(obj).__name__} is not JSON serializable"
    )


def _emit_safe_dumps(payload: Any) -> str:
    """JSON-encode an event payload with Decimal/datetime/set support."""
    return json.dumps(payload, default=_emit_safe_default)

# ---------------------------------------------------------------------------
# §SOVKIT K1 (his word 2026-09-14 "2 yes": Kafka is PRIVATE to the event store).
# The registry used to produce to Redpanda first (fire-and-forget: `send()` never awaited delivery) and fall back to
# HTTP; agentvault2-85 measured the store's consumer writing whatever arrived on :9092 with none of the HTTP route's
# checks, reachable by every container on the frame network. The registry now writes ONLY through the store's HTTP
# route (over the frame's mTLS sidecar, the answer read and reported); the broker belongs to the store alone.
# `shutdown_kafka` stays as a no-op so main.py's shutdown hook keeps its call.
# ---------------------------------------------------------------------------
async def shutdown_kafka():
    """No-op since §SOVKIT K1: the registry holds no Kafka producer (kept for main.py's shutdown hook)."""
    return None


# §BRIDGE R7 — how many of this registry's own events stay in the central ring.
# A SEED, deliberately: it primes a client's console and its replay buffer, and
# it is not a substitute for the ledger. Bounded in code (hard cap 2000) so an
# env typo cannot turn a cache into a memory leak.
RECENT_EVENTS_RING = max(15, min(2000, int(os.getenv("RECENT_EVENTS_RING", "400"))))


class EventEmitter:
    """
    Client for emitting events to the Event Store.
    This class should be used by TEG and Registry services.
    
    TITANIUM VAULT D1: All emit calls now support idempotency_key parameter.
    If provided, the EventStore will deduplicate on this key. Retries reuse
    the same key, guaranteeing exactly-once delivery.
    """
    
    def __init__(
        self, 
        event_store_url: str = "http://localhost:8200",
        internal_api_key: str = "",
        source_service: str = "unknown"
    ):
        self.event_store_url = event_store_url.rstrip("/")
        self.internal_api_key = internal_api_key
        self.source_service = source_service
        self.session: Optional[aiohttp.ClientSession] = None
        # Serializes session creation/recreation to prevent leaks when SPIRE cert
        # rotation interleaves with concurrent emit() calls. Without it, the await
        # on session.close() during refresh yields control, allowing other coroutines
        # to lazy-create their own session at line ~195, leading to orphaned sessions.
        self._session_lock = asyncio.Lock()
        self.federation_license_key = os.getenv("FEDERATION_LICENSE_KEY", "")
        self.federation_operator_id = os.getenv("FEDERATION_OPERATOR_ID", "")
        # mTLS client certs (SPIRE SVIDs) for EventStore authentication
        self._ssl_context: Optional[ssl.SSLContext] = None
        self._cert_dir = os.getenv("SVID_CERT_DIR", "/certs")
        self._cert_path = os.path.join(self._cert_dir, "svid.0.pem")
        self._key_path = os.path.join(self._cert_dir, "svid.0.key")
        self._ca_path = os.path.join(self._cert_dir, "bundle.0.pem")
        # §SVIDRACE (V0639): the stamp of the cert, the key and the bundle the context was built from (es_ssl_helper.
        # file_stamp), recorded only after a build that succeeded: the cert-writer rewrites the three files in place,
        # and a context keyed on the cert alone missed a bundle that changed after the cert was copied.
        self._svid_stamp: tuple = ()
        self._es_uses_public_ca = "." in (urlparse(event_store_url).hostname or "")
        self._build_ssl_context()

    def _build_ssl_context(self):
        """Build SSL context from current SPIRE SVID certs on disk."""
        if not (os.path.exists(self._cert_path) and os.path.exists(self._key_path) and os.path.exists(self._ca_path)):
            return
        stamp = self._material_stamp()   # read BEFORE the build: a change during it moves the stamp again
        try:
            if self._es_uses_public_ca:
                ctx = ssl.create_default_context()  # System CAs for public endpoints
            else:
                ctx = ssl.create_default_context(cafile=self._ca_path)  # SPIRE bundle for internal
            ctx.load_cert_chain(self._cert_path, self._key_path)  # Always present SPIRE SVID
            self._ssl_context = ctx
            self._svid_stamp = stamp
        except Exception:
            pass  # Keep the previous context; the stamp stays unrecorded, so the next emit retries the build

    def _material_stamp(self) -> tuple:
        from .es_ssl_helper import file_stamp
        return file_stamp(self._cert_path, self._key_path, self._ca_path)

    def _auth_headers(self) -> Dict[str, str]:
        """The ONE credential this registry presents to its own event store over HTTP.

        §SOVKIT S2.3 (2026-09-14, agentvault2-85's S0 risk 5): a registry that held a FEDERATION LICENCE used to send
        it INSTEAD of its internal key, so a frame licensed by another frame (asia by eu; every frame the runner
        licenses) had its HTTP fallback to its OWN ledger refused whenever the licence matched nothing there (hidden
        by Kafka, exposed by the mTLS-required flag). The internal key is this registry's credential for its own
        store and wins whenever it is configured; the licence is only what a registry WITHOUT one has left. Over the
        mTLS gateway the sidecar clears both and the client certificate is the authority, so this decides nothing
        there. Pinned by tests/test_sovkit_v0368.py.
        """
        if self.internal_api_key:
            return {"X-Internal-Key": self.internal_api_key}
        if self.federation_license_key:
            return {"X-Federation-License": self.federation_license_key}
        return {}

    async def _ensure_session(self):
        """Create the session if missing or closed. Lock-protected against
        concurrent creators (e.g., another coroutine in mid-SSL-refresh)."""
        if self.session and not self.session.closed:
            return  # Fast path — no allocation, no lock acquired
        async with self._session_lock:
            if self.session and not self.session.closed:
                return  # Double-check inside lock
            connector = aiohttp.TCPConnector(ssl=self._ssl_context) if self._ssl_context else None
            self.session = aiohttp.ClientSession(connector=connector)

    async def _refresh_ssl_if_needed(self):
        """Check if SPIRE SVID was rotated, rebuild SSL context + session if so.

        The session swap is performed under self._session_lock so concurrent emit()
        coroutines don't race to lazy-create their own (which previously leaked).
        The old session is closed OUTSIDE the lock to avoid blocking other emitters
        during the SSL handshake teardown.
        """
        stamp = self._material_stamp()
        if not stamp:
            return
        if stamp == self._svid_stamp:
            return  # Fast path — no lock acquired
        old_session = None
        async with self._session_lock:
            if self._material_stamp() == self._svid_stamp:
                return  # Double-check: another coroutine already rotated
            logger.info("[EventEmitter] SPIRE material changed (cert, key or bundle), refreshing SSL context")
            self._build_ssl_context()
            old_session = self.session
            connector = aiohttp.TCPConnector(ssl=self._ssl_context) if self._ssl_context else None
            self.session = aiohttp.ClientSession(connector=connector)
        if old_session:
            try:
                await old_session.close()
            except Exception as e:
                logger.warning(f"[EventEmitter] Failed to close old session during rotation: {e}")

    async def __aenter__(self):
        """Async context manager entry"""
        connector = aiohttp.TCPConnector(ssl=self._ssl_context) if self._ssl_context else None
        self.session = aiohttp.ClientSession(connector=connector)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    async def emit(
        self,
        event_type: str,
        aggregate_id: str,
        data: Dict,
        aggregate_type: str = "Agent",
        metadata: Optional[Dict] = None,
        idempotency_key: Optional[str] = None,
        max_retries: int = 3,
        defer: bool = True,
        outcome: Optional[Dict] = None,
    ) -> bool:
        """
        Emit an event to the Event Store.

        §SOVKIT K1 / V0372 (2026-09-14): when every attempt failed for a reason the store may recover from
        (a connection error, a timeout, 429, 5xx) and `defer` is on, the event is written to the durable outbox
        (`es_emit_outbox`, drained by background_tasks/es_emit_outbox_drainer) and True is returned: the ledger
        gets the record when the store answers again. A 4xx is never deferred. `outcome`, when given, is filled
        with what happened (`retryable`, `status`, `error`) for the drainer's decision.
        
        TITANIUM VAULT D1: Now supports idempotency_key and retry with backoff.
        
        Args:
            event_type: Type of event (e.g., "TokensIssued")
            aggregate_id: ID of the aggregate (e.g., agent DID)
            data: Event data payload
            aggregate_type: Type of aggregate (default: "Agent")
            metadata: Optional metadata
            idempotency_key: Deterministic key for deduplication. If None, a random
                UUID is generated (safe for non-financial events). For financial events,
                callers MUST provide a deterministic key tied to the operation.
            max_retries: Maximum number of retry attempts (default: 3)
            
        Returns:
            bool: True if successful (including idempotent duplicate), False otherwise
        """
        # Refresh SPIRE SVID if rotated (cheap stat() check)
        await self._refresh_ssl_if_needed()

        # Ensure session exists (lock-protected against concurrent creators)
        await self._ensure_session()

        # f037: Refresh policy cache if stale
        if _time.monotonic() - _emission_policy_cache_ts > _EMISSION_POLICY_CACHE_TTL:
            try:
                # First load is awaited (blocking) to ensure policies are ready
                if _emission_policy_cache_ts == 0:
                    await _load_emission_policies()
                else:
                    asyncio.ensure_future(_load_emission_policies())
            except Exception:
                pass  # Non-blocking — cache refresh failure is not fatal

        # f037: Check emission policy — is this source authorized to emit this event?
        if not _get_emission_policy(event_type, self.source_service):
            logger.info(
                f"[EmissionPolicy] BLOCKED: {event_type} from {self.source_service} "
                f"(policy: emit_from_{self.source_service}=false)"
            )
            if outcome is not None:   # D6-818: a caller that reports what it stored can tell a block from a write
                outcome.update({"blocked_by_policy": True, "retryable": False, "status": None, "error": None})
            return True  # Return True so callers don't treat as failure

        # TITANIUM VAULT D1: Generate idempotency key if not provided
        # §pass52 Phase A: count which form the caller passed so we can drive
        # balance-moving events to 100% deterministic before Phase D enforces it.
        if _idem_key_form_total is not None:
            if idempotency_key is None:
                _idem_key_form_total.labels(
                    event_type=event_type, key_form="null_fallback_uuid"
                ).inc()
            elif idempotency_key.startswith(("xfer-", "tokens_transferred:", "tokens_issued:",
                                             "tokens_staked:", "tokens_unstaked:",
                                             "dispute-comp-", "dispute-slash-",
                                             "transfer_fee:", "reward-", "snapshot-")):
                _idem_key_form_total.labels(
                    event_type=event_type, key_form="deterministic"
                ).inc()
            else:
                _idem_key_form_total.labels(
                    event_type=event_type, key_form="other"
                ).inc()
        idem_key = idempotency_key or str(uuid.uuid4())
        
        event_payload = {
            "event_type": event_type,
            "aggregate_id": aggregate_id,
            "aggregate_type": aggregate_type,
            "data": data,
            "metadata": metadata or {},
            "source_service": self.source_service,
            "idempotency_key": idem_key
        }
        if self.federation_operator_id:
            event_payload["source_operator_id"] = self.federation_operator_id

        headers = {"Content-Type": "application/json", **self._auth_headers()}

        # §SOVKIT K1: no Kafka path; the store's HTTP route is the ONE write path (through the frame's mTLS sidecar).

        # TITANIUM VAULT D1: Retry with exponential backoff.
        # 2026-05-07: pre-serialize via _emit_safe_dumps so Decimal-typed values
        # (from SQLAlchemy Numeric columns — voting_power, auto_slash_max_avt, …)
        # don't silently 3-retry-then-die. Switch from `json=` (default encoder)
        # to `data=` (pre-serialized string + explicit Content-Type).
        try:
            payload_body = _emit_safe_dumps(event_payload)
        except TypeError as ser_exc:
            logger.error(
                f"Failed to serialize event payload: {ser_exc} — "
                f"event_type={event_type} aggregate_id={aggregate_id} key={idem_key}"
            )
            return False
        post_headers = dict(headers)
        post_headers.setdefault("Content-Type", "application/json")
        last_error = None
        last_status = None
        retryable = False
        for attempt in range(max_retries):
            try:
                async with self.session.post(
                    f"{self.event_store_url}/api/v1/events/",
                    data=payload_body,
                    headers=post_headers,
                ) as response:
                    if response.status == 201:
                        result = await response.json()
                        logger.info(
                            f"Emitted {event_type} event for {aggregate_id}: "
                            f"{result.get('id', 'unknown')} (key={idem_key})"
                        )
                        # Broadcast to WebSocket clients for live event ledger
                        await self._broadcast_to_ws(event_payload, result)
                        return True
                    elif response.status == 202:
                        # Accepted for async processing via HTTP→Kafka bridge
                        # (EVENTSTORE_HTTP_VIA_KAFKA=true on destination ES).
                        # Body is still JSON with idempotency_key + event_id;
                        # no need to retry.
                        result = await response.json()
                        logger.debug(
                            f"Accepted (async via Kafka) {event_type} for "
                            f"{aggregate_id}: {result.get('event_id', 'unknown')} "
                            f"(key={idem_key})"
                        )
                        # §BRIDGE R7 (2026-08-19) — SEED THE RING ON THIS PATH TOO.
                        #
                        # This branch returned success without ever reaching the
                        # broadcast/cache path, and `EVENTSTORE_HTTP_VIA_KAFKA` is
                        # true on ALL THREE mainframe EventStores — so every
                        # emission has taken this branch since §ESKAFKAFIX, the
                        # `recent_events` ring has been EMPTY on every frame
                        # (measured: LLEN 0 on frame-a, frame-b and frame-c), and
                        # `/public/eventstore-recent` has been serving `[]` to the
                        # landing page it exists to seed.
                        #
                        # Only the CACHE is added here, deliberately. The live WS
                        # broadcast stays exactly as it was on both paths: the
                        # EventStore itself broadcasts when it consumes from Kafka,
                        # and adding a second emitter-side broadcast would change
                        # what subscribers receive. Seeding a cache changes nothing
                        # that is already on the wire.
                        # The ring is written by background_tasks/recent_events_ring, which
                        # listens to THIS frame's EventStore broadcasts — so it sees this event
                        # once the store has it, AND everything the registry never emits
                        # (teg-balance-outbox is the majority on frame-c). One writer, so our
                        # own events are not double-counted while everyone else's are single.
                        return True
                    elif response.status == 409:
                        # TITANIUM VAULT D1: Idempotent duplicate — this is SUCCESS
                        logger.info(
                            f"Idempotent duplicate accepted: {event_type} for "
                            f"{aggregate_id} (key={idem_key})"
                        )
                        return True
                    else:
                        error_text = await response.text()
                        last_error = f"{response.status} - {error_text}"
                        last_status = response.status
                        retryable = response.status in (408, 425, 429) or response.status >= 500
                        logger.warning(
                            f"Event emit attempt {attempt + 1}/{max_retries} failed: "
                            f"{last_error} (key={idem_key})"
                        )
                        
            except Exception as e:
                last_error = str(e)
                last_status = None
                retryable = True
                logger.warning(
                    f"Event emit attempt {attempt + 1}/{max_retries} error: "
                    f"{last_error} (key={idem_key})"
                )
            
            # Exponential backoff: 1s, 2s, 4s
            if attempt < max_retries - 1:
                backoff = 2 ** attempt
                logger.debug(f"Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
        
        if outcome is not None:
            outcome.update({"retryable": retryable, "status": last_status, "error": last_error})
        # §SOVKIT K1 / V0372: the store may come back; the event waits for it in the durable outbox
        if defer and retryable and _outbox_enabled():
            if await _outbox_enqueue(event_payload, idem_key, last_error):
                logger.warning("[EMIT-DEFERRED] %s aggregate=%s key=%s: the store did not answer (%s); queued in es_emit_outbox for the drainer",
                               event_type, aggregate_id, idem_key, str(last_error)[:160])
                try:
                    if _es_outbox_deferred_total is not None:
                        _es_outbox_deferred_total.labels(event_type=str(event_type)).inc()
                except Exception:  # noqa: BLE001
                    pass
                return True
        # All retries exhausted
        logger.error(
            f"Failed to emit event after {max_retries} attempts: "
            f"{event_type} for {aggregate_id} (key={idem_key}). "
            f"Last error: {last_error}"
        )
        return False
    
    def _ws_message(self, event_payload: dict, result: dict) -> dict:
        """The one shape both the live broadcast and the recent-events ring use."""
        return {
            "type": "event",
            "data": {
                # 201 returns `id`; the 202 (async-via-Kafka) body calls it
                # `event_id`. Same event, different key.
                "id": result.get("id") or result.get("event_id"),
                "event_type": event_payload.get("event_type"),
                "aggregate_id": event_payload.get("aggregate_id"),
                "aggregate_type": event_payload.get("aggregate_type"),
                "data": event_payload.get("data", {}),
                "timestamp": result.get("timestamp", datetime.now(timezone.utc).isoformat()),
                "source_service": event_payload.get("source_service"),
            },
        }

    async def _broadcast_to_ws(self, event_payload: dict, result: dict) -> None:
        """Best-effort broadcast to WebSocket subscribers for live event ledger.

        system.events is the public ledger feed: anyone may subscribe (routers/websocket.topic_allowed) and the public
        /ws/events subscribes every visitor to it. So it carries each event with its personal ids withheld, as every
        public read does since D6-606: an account id built from an e-mail address (a developer's TEG account) becomes
        its opaque public id, an address is withheld. The event stored on the ledger is unchanged."""
        try:
            from .identifiers import withhold_personal_ids
            from .routers.websocket import manager
            ws_message = withhold_personal_ids(self._ws_message(event_payload, result))
            await manager.broadcast_to_subscribers("system.events", ws_message)
        except Exception as e:
            # Never let WS broadcast failure affect event emission
            logger.debug(f"WS broadcast skipped: {e}")

    # NOTE (§BRIDGE R7-B): the `recent_events` ring writer USED to live here as
    # `_cache_recent_event`. It is gone, not moved-and-left-behind: with
    # KAFKA_ENABLED=true this path never ran (measured LLEN 0 on all three
    # frames), and a dead writer that still looks live is how the seed stayed
    # empty for months without anyone noticing. THE ONE WRITER is now
    # background_tasks/recent_events_ring.py, which rings what the EventStore
    # broadcasts — everything on the frame, whoever emitted it. RECENT_EVENTS_RING
    # above is still the ring bound; that task imports it.

    async def close(self):
        """Close the HTTP session. Call on shutdown."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    def emit_background(
        self,
        event_type: str,
        aggregate_id: str,
        data: Dict,
        aggregate_type: str = "Agent",
        metadata: Optional[Dict] = None,
        idempotency_key: Optional[str] = None,
        max_retries: int = 3
    ) -> None:
        """
        Fire-and-forget event emission. Returns immediately, event is
        emitted in a background task. Safe because:
        - Idempotency keys prevent duplicates on retry
        - EventStore deduplicates on key (409 Conflict = success)
        - Transfer already completed in TEG before this is called
        """
        try:
            asyncio.create_task(self._emit_background_wrapper(
                event_type, aggregate_id, data, aggregate_type,
                metadata, idempotency_key, max_retries
            ))
        except RuntimeError:
            # No event loop — fall back to sync-ish best effort
            logger.debug(f"[EmitBG] No event loop, skipping background emit for {event_type}")

    async def _emit_background_wrapper(self, *args, **kwargs):
        """Wrapper that catches exceptions so background task never crashes.

        §SILENT (2026-09-14): a lost background emit is an ERROR and a count, never a warning nobody
        reads. A fire-and-forget ledger event that fails after the money moved leaves Δ at 0.0 while
        the ES balances drift from TEG truth (§S4); the only instrument that can see it is this line.
        """
        try:
            ok = await self.emit(*args, **kwargs)
        except Exception as e:
            ok = False
            detail = f"{type(e).__name__}: {e}"
        else:
            detail = "the emitter exhausted its retries"
        if not ok:
            _report_lost_emit(kwargs.get("event_type") or (args[0] if args else "?"),
                              kwargs.get("aggregate_id") or (args[1] if len(args) > 1 else "?"),
                              kwargs.get("idempotency_key") or (args[5] if len(args) > 5 else None),
                              "emit_background", detail)

    # ─── Convenience methods for common events ───────────────────────
    # All methods pass through to emit() which handles idempotency + retry.
    
    async def emit_tokens_issued(
        self,
        agent_did: str,
        amount: str,
        transaction_id: str,
        issued_by: str = "system",
        reason: str = "manual"
    ) -> bool:
        """Emit a TokensIssued event"""
        return await self.emit(
            event_type="TokensIssued",
            aggregate_id=agent_did,
            data={
                "amount": amount,
                "transaction_id": transaction_id,
                "issued_by": issued_by,
                "reason": reason
            },
            idempotency_key=f"tokens_issued:{transaction_id}"
        )
    
    async def emit_tokens_transferred(
        self,
        from_agent: str,
        to_agent: str,
        amount: str,
        transaction_id: str,
        memo: Optional[str] = None
    ) -> bool:
        """Emit a TokensTransferred event"""
        data = {
            "from": from_agent,
            "to": to_agent,
            "amount": amount,
            "transaction_id": transaction_id
        }
        if memo:
            data["memo"] = memo
            
        return await self.emit(
            event_type="TokensTransferred",
            aggregate_id=from_agent,
            data=data,
            idempotency_key=f"tokens_transferred:{transaction_id}"
        )
    
    async def emit_tokens_staked(
        self,
        agent_did: str,
        amount: str,
        pool_id: str,
        lock_period_days: int = 30,
        expected_apy: Optional[str] = None,
        transaction_id: Optional[str] = None,
    ) -> bool:
        """Emit a TokensStaked event"""
        data = {
            "amount": amount,
            "pool_id": pool_id,
            "lock_period_days": lock_period_days
        }
        if expected_apy:
            data["expected_apy"] = expected_apy
        # §PlanB-① (2026-06-01): carry the originating TEG transaction_id so
        # getTegTransactionDetail resolves stakes via the ES by-transaction lookup
        # (previously absent → stakes 404'd in detail).
        if transaction_id:
            data["transaction_id"] = transaction_id

        return await self.emit(
            event_type="TokensStaked",
            aggregate_id=agent_did,
            data=data,
            idempotency_key=f"tokens_staked:{pool_id}:{agent_did}"
        )
    
    async def emit_tokens_unstaked(
        self,
        agent_did: str,
        amount: str,
        pool_id: str,
        rewards_earned: Optional[str] = None,
        transaction_id: Optional[str] = None,
    ) -> bool:
        """Emit a TokensUnstaked event"""
        data = {
            "amount": amount,
            "pool_id": pool_id
        }
        if rewards_earned:
            data["rewards_earned"] = rewards_earned
        # §PlanB-① (2026-06-01): carry the originating TEG transaction_id (see emit_tokens_staked).
        if transaction_id:
            data["transaction_id"] = transaction_id

        return await self.emit(
            event_type="TokensUnstaked",
            aggregate_id=agent_did,
            data=data,
            idempotency_key=f"tokens_unstaked:{pool_id}:{agent_did}"
        )
    
    async def emit_agent_created(
        self,
        agent_did: str,
        name: str,
        description: str,
        developer_id: str,
        registry_id: str,
        capabilities: list,
        initial_reputation: int = 100
    ) -> bool:
        """Emit an AgentCreated event"""
        return await self.emit(
            event_type="AgentCreated",
            aggregate_id=agent_did,
            data={
                "name": name,
                "description": description,
                "developer_id": developer_id,
                "registry_id": registry_id,
                "capabilities": capabilities,
                "initial_reputation": initial_reputation
            },
            idempotency_key=f"agent_created:{agent_did}"
        )
    
    async def emit_agent_updated(
        self,
        agent_did: str,
        changes: Dict
    ) -> bool:
        """Emit an AgentUpdated event"""
        return await self.emit(
            event_type="AgentUpdated",
            aggregate_id=agent_did,
            data=changes
        )
    
    async def emit_attestation_submitted(
        self,
        agent_did: str,
        attestation_type: str,
        attestation_data: Dict
    ) -> bool:
        """Emit an AttestationSubmitted event"""
        return await self.emit(
            event_type="AttestationSubmitted",
            aggregate_id=agent_did,
            data={
                "attestation_type": attestation_type,
                "attestation_data": attestation_data
            }
        )
    
    async def emit_reputation_changed(
        self,
        agent_did: str,
        old_score: int,
        new_score: int,
        reason: str
    ) -> bool:
        """Emit a ReputationChanged event"""
        return await self.emit(
            event_type="ReputationChanged",
            aggregate_id=agent_did,
            data={
                "old_score": old_score,
                "new_score": new_score,
                "reason": reason
            }
        )
    
    # --- OWL25: Sovereign Settlement Event Methods ---
    
    async def emit_dispute_compensation_request(
        self,
        dispute_id: int,
        complainant_did: str,
        defendant_did: str,
        amount: int,
        origin_registry_url: str,
        ruling: str
    ) -> bool:
        """Emit a DisputeCompensationRequest event (no balance effect, informational only).

        D15 (2026-05-06): aggregate_id normalized to "dispute:N" for consistent
        EventStore replay. Both parties' DIDs remain in `data` for queryability.
        """
        return await self.emit(
            event_type="DisputeCompensationRequest",
            aggregate_id=f"dispute:{dispute_id}",
            aggregate_type="Dispute",
            data={
                "dispute_id": dispute_id,
                "complainant_did": complainant_did,
                "defendant_did": defendant_did,
                "amount": amount,
                "origin_registry_url": origin_registry_url,
                "ruling": ruling
            },
            idempotency_key=f"dispute_comp_req:{dispute_id}:{complainant_did}"
        )

    async def emit_dispute_slash(
        self,
        dispute_id: int,
        defendant_did: str,
        amount: int,
        origin_registry_url: str,
        slash_tx_id: str
    ) -> bool:
        """Emit a DisputeSlash event (balance-affecting: deducts from defendant).

        D15 (2026-05-06): aggregate_id normalized to "dispute:N". reactor_agent_slashed
        reads defendant_did from data, not aggregate_id, so this is non-breaking.
        """
        return await self.emit(
            event_type="DisputeSlash",
            aggregate_id=f"dispute:{dispute_id}",
            aggregate_type="Dispute",
            data={
                "dispute_id": dispute_id,
                "defendant_did": defendant_did,
                "amount": amount,
                "origin_registry_url": origin_registry_url,
                "slash_tx_id": slash_tx_id
            },
            idempotency_key=f"dispute_slash:{dispute_id}:{defendant_did}:{slash_tx_id}"
        )

    async def emit_dispute_compensation_minted(
        self,
        dispute_id: int,
        complainant_did: str,
        amount: int,
        slash_evidence_event_id: str,
        mint_tx_id: str
    ) -> bool:
        """Emit a DisputeCompensationMinted event (balance-affecting: credits complainant).

        D15 (2026-05-06): aggregate_id normalized to "dispute:N".
        """
        return await self.emit(
            event_type="DisputeCompensationMinted",
            aggregate_id=f"dispute:{dispute_id}",
            aggregate_type="Dispute",
            data={
                "dispute_id": dispute_id,
                "complainant_did": complainant_did,
                "amount": amount,
                "slash_evidence_event_id": slash_evidence_event_id,
                "mint_tx_id": mint_tx_id
            },
            idempotency_key=f"dispute_comp_mint:{dispute_id}:{complainant_did}:{mint_tx_id}"
        )
    # --- END OWL25 ---

    # --- IRONHAND: Agent mTLS Revocation Events (f052) ---

    async def emit_agent_mtls_revoked(
        self,
        agent_did: str,
        spiffe_id: str,
        reason: str = "admin_revocation",
        revoked_by: str = "",
    ) -> bool:
        """Emit an AgentMtlsRevoked event for real-time revocation propagation.

        Subscribers (agents, operators) listen for this event to immediately
        block the revoked SPIFFE ID in their local A2AAuthenticator blocklist.
        """
        return await self.emit(
            event_type="AgentMtlsRevoked",
            aggregate_id=agent_did,
            data={
                "spiffe_id": spiffe_id,
                "agent_did": agent_did,
                "reason": reason,
                "revoked_by": revoked_by,
            },
            idempotency_key=f"mtls_revoked:{agent_did}:{spiffe_id}"
        )

    async def emit_agent_mtls_enrolled(
        self,
        agent_did: str,
        spiffe_id: str,
    ) -> bool:
        """Emit an AgentMtlsEnrolled event (informational)."""
        return await self.emit(
            event_type="AgentMtlsEnrolled",
            aggregate_id=agent_did,
            data={
                "spiffe_id": spiffe_id,
                "agent_did": agent_did,
            },
            idempotency_key=f"mtls_enrolled:{agent_did}:{spiffe_id}"
        )

    # --- END IRONHAND ---

    # --- Phase 6 coordinated suspension ---

    async def emit_agent_reinstated(
        self,
        agent_did: str,
        actor_developer_id: Optional[int] = None,
        actor_email: str = "system",
        prior_reason: Optional[str] = None,
    ) -> bool:
        """Emit AgentReinstated when an admin reactivates a suspended agent."""
        from datetime import datetime, timezone
        return await self.emit(
            event_type="AgentReinstated",
            aggregate_id=agent_did,
            data={
                "agent_did": agent_did,
                "actor_developer_id": actor_developer_id,
                "actor_email": actor_email,
                "prior_reason": prior_reason,
                "reinstated_at": datetime.now(timezone.utc).isoformat(),
            },
            idempotency_key=f"agent_reinstated:{agent_did}:{datetime.now(timezone.utc).isoformat()}"
        )

    # --- END Phase 6 ---

    async def emit_event(
        self,
        aggregate_id: str,
        event_type: str,
        event_data: Dict
    ) -> bool:
        """
        Emit a generic event (compatibility method).
        
        Args:
            aggregate_id: ID of the aggregate
            event_type: Type of event
            event_data: Event data payload
            
        Returns:
            bool: True if successful, False otherwise
        """
        return await self.emit(
            event_type=event_type,
            aggregate_id=aggregate_id,
            data=event_data
        )
    
    async def close(self):
        """Close the HTTP session"""
        if self.session:
            await self.session.close()
            self.session = None


# ---------------------------------------------------------------------------
# f037 — Event Emission Policy Cache
# ---------------------------------------------------------------------------
# In-memory cache of EventEmissionPolicy rows, refreshed from DB every 60s.
# Used by emit() to gate whether this service layer is authorized to emit.

import time as _time

_emission_policy_cache: Dict[str, dict] = {}  # event_type → {emit_from_teg, emit_from_registry, skip_in_projection}
_emission_policy_cache_ts: float = 0
try:
    from prometheus_client import Counter as _LostCounter
    _value_emit_failed_total = _LostCounter(
        "registry_value_emit_failed_total",
        "Ledger emits that failed after the fact they describe had already happened (logged, counted, never silent)",
        ["event_type"],
    )
except Exception:  # noqa: BLE001 — a second registration in a test process, or no prometheus
    _value_emit_failed_total = None


try:
    from prometheus_client import Counter as _DeferCounter
    _es_outbox_deferred_total = _DeferCounter(
        "registry_es_emit_outbox_deferred_total",
        "Ledger emits the store could not take that were queued in es_emit_outbox for the drainer (§SOVKIT K1 / V0372)",
        ["event_type"],
    )
except Exception:  # noqa: BLE001 — a second registration in a test process, or no prometheus
    _es_outbox_deferred_total = None


def _outbox_enabled() -> bool:
    return (os.getenv("ES_EMIT_OUTBOX_ENABLED") or "true").strip().lower() == "true"


async def _outbox_enqueue(event_payload: Dict, idem_key: str, last_error: Optional[str]) -> bool:
    """§SOVKIT K1 / V0372: write the event as it would have been POSTed into es_emit_outbox (its own short transaction;
    ON CONFLICT on the idempotency key does nothing: a second deferral of the same operation collapses onto the first
    row). Never raises: False means the database refused too, and the caller reports the emit as LOST."""
    try:
        import json as _json
        from sqlalchemy.dialects.postgresql import insert as _pg_insert
        from agentvault_registry import models as _models
        from agentvault_registry.database import get_db_context as _get_db_context
        async with _get_db_context() as db:
            await db.execute(
                _pg_insert(_models.EsEmitOutbox).values(
                    event_type=str(event_payload.get("event_type"))[:128],
                    aggregate_id=str(event_payload.get("aggregate_id"))[:512],
                    aggregate_type=str(event_payload.get("aggregate_type") or "Agent")[:64],
                    payload=_json.loads(_emit_safe_dumps(event_payload)),
                    idempotency_key=str(idem_key)[:255],
                    last_error=(str(last_error)[:500] if last_error else None),
                ).on_conflict_do_nothing(index_elements=["idempotency_key"])
            )
            await db.commit()
        return True
    except Exception as e:  # noqa: BLE001 — reported by the caller as EMIT-LOST
        logger.warning("[EMIT-DEFERRED] es_emit_outbox refused the row for key=%s: %s", idem_key, f"{type(e).__name__}: {e}")
        return False


def _report_lost_emit(event_type: str, aggregate_id: str, idempotency_key: Optional[str], where: str, detail: str) -> None:
    logger.error("[EMIT-LOST] %s aggregate=%s key=%s at %s: %s", event_type, aggregate_id, idempotency_key, where or "?", detail)
    try:
        if _value_emit_failed_total is not None:
            _value_emit_failed_total.labels(event_type=str(event_type)).inc()
    except Exception:  # noqa: BLE001 — the count must never cost the log line
        pass


async def emit_or_report(
    emitter,
    *,
    event_type: str,
    aggregate_id: str,
    data: Dict,
    idempotency_key: Optional[str] = None,
    aggregate_type: str = "Agent",
    where: str = "",
) -> bool:
    """§SILENT (2026-09-14) — emit a ledger event whose subject has ALREADY happened, and never lose it silently.

    The callers this replaces (the token bridge, A2A authorize) wrapped their emit in `except Exception: pass`
    because the request must not fail after the money moved: a client that sees a 500 retries the payment. That
    half is right and stays. The other half was wrong: a dropped emit leaves the supply invariant at Δ 0.0
    (both legs of a transfer are derived from one event, so a missing event moves nothing) while the ES balances
    drift from TEG truth, and nothing anywhere went red. So a failure is LOGGED at ERROR with the event's type,
    aggregate and key, COUNTED (`registry_value_emit_failed_total{event_type}`), and RETURNED as False for the
    caller to record; it is never raised and never silent. A False from `emit` (retries exhausted) is the same
    failure and is reported the same way.
    """
    try:
        if emitter is None:
            raise RuntimeError("no event emitter configured")
        ok = await emitter.emit(
            event_type=event_type, aggregate_id=aggregate_id, data=data,
            aggregate_type=aggregate_type, idempotency_key=idempotency_key,
        )
        if ok:
            return True
        detail = "the emitter exhausted its retries"
    except Exception as exc:  # noqa: BLE001 — reported below, never raised past the money that moved
        detail = f"{type(exc).__name__}: {exc}"
    _report_lost_emit(event_type, aggregate_id, idempotency_key, where, detail)
    return False


_EMISSION_POLICY_CACHE_TTL = 60  # seconds
_emission_policy_load_error: Optional[str] = None   # W3: the last load's failure (None after a good load)
_emission_policy_loaded_wall: float = 0.0            # W3: the wall clock of the last good load, for the admin read
_shadow_logged: set = set()                          # W3: the types a shadow refusal was logged for, once per process
SHADOW_REDIS_KEY = "emission:policy:would_refuse"    # W3: per-type counts across workers, for the admin read
try:
    from prometheus_client import Gauge as _PGauge
    _missing_rows_gauge = _PGauge(
        "registry_emission_policy_missing_rows",
        "Emitted event types (core/event_catalog.py) this frame's policy table has no row for, at the boot check",
        ["emitter"],
    )
except Exception:  # noqa: BLE001 — a second registration in a test process, or no prometheus
    _missing_rows_gauge = None


def emission_policy_mode() -> str:
    """W3: what the registry's gate does with an event type that has NO policy row: "off" allows it (the legacy
    fail-open), "shadow" allows it and counts and logs it as a refusal enforce would make (this release's default),
    "enforce" refuses it. EVENT_EMITTER_POLICY_MODE names the mode; EVENT_EMITTER_FAIL_CLOSED=true still means enforce.
    A row's own emit_from_registry=false is refused in every mode, as before."""
    if os.environ.get("EVENT_EMITTER_FAIL_CLOSED", "false").strip().lower() == "true":
        return "enforce"
    mode = (os.environ.get("EVENT_EMITTER_POLICY_MODE") or "shadow").strip().lower()
    return mode if mode in ("off", "shadow", "enforce") else "shadow"


async def _load_emission_policies():
    """Load emission policies from DB into in-memory cache."""
    global _emission_policy_cache, _emission_policy_cache_ts, _emission_policy_load_error, _emission_policy_loaded_wall
    try:
        from .database import get_db_context
        from .models import EventEmissionPolicy
        from sqlalchemy import select
        async with get_db_context() as db:
            result = await db.execute(select(EventEmissionPolicy))
            rows = result.scalars().all()
            new_cache = {}
            for row in rows:
                new_cache[row.event_type] = {
                    'emit_from_teg': row.emit_from_teg,
                    'emit_from_registry': row.emit_from_registry,
                    'skip_in_projection': row.skip_in_projection,
                }
            _emission_policy_cache = new_cache
            _emission_policy_cache_ts = _time.monotonic()
            _emission_policy_load_error = None
            _emission_policy_loaded_wall = _time.time()
            logger.debug(f"[EmissionPolicy] Loaded {len(new_cache)} policies from DB")
    except Exception as e:
        _emission_policy_load_error = f"{type(e).__name__}: {e}"[:300]
        logger.warning(f"[EmissionPolicy] Failed to load policies: {e} — the cached rows stay (none: every type is allowed and counted as unreadable)")


def _get_emission_policy(event_type: str, source_service: str) -> bool:
    """
    Check whether this source_service is authorized to emit this event_type.
    Returns True if emission is allowed, False if blocked by policy.
    If no policy exists for this event_type, emission_policy_mode() decides (W3).

    §pass52 Phase A: every decision path is instrumented. `decision` label:
      - allow          — explicit policy row says yes
      - deny-policy    — explicit policy row says no
      - allow-via-fail-open — no policy row exists, mode "off": allowed
      - shadow-would-refuse — no policy row exists, mode "shadow" (W3's default): allowed, logged once per type and
                          counted in Redis, a refusal enforce would make
      - deny-no-policy — no policy row exists, mode "enforce": refused
      - allow-policy-unreadable — the table could not be read: allowed in every mode (W3: no decision is possible)
      - deny-unknown-source — source_service not recognized
    """
    policy = _emission_policy_cache.get(event_type)
    if policy is None:
        # §pass52 Phase A: track unknown event types so we can drive count to 0
        # before flipping the default to fail-closed (Phase J).
        if _unknown_event_type_total is not None:
            _unknown_event_type_total.labels(
                event_type=event_type, source_service=source_service,
            ).inc()
        # §pass52 Phase J, W3 (2026-10-25): the mode decides (emission_policy_mode: off, shadow, enforce). Whatever the
        # mode, a table that could not be read decides nothing: refusing a ledger event whose money already moved would
        # leave the ledger short, so it is allowed and counted as unreadable (a read failure is not a refusal).
        mode = emission_policy_mode()
        if not _emission_policy_cache:
            decision_label = "allow-policy-unreadable"
        elif mode == "enforce":
            decision_label = "deny-no-policy"
        elif mode == "shadow":
            decision_label = "shadow-would-refuse"
        else:
            decision_label = "allow-via-fail-open"
        if _gate_decision_total is not None:
            _gate_decision_total.labels(
                event_type=event_type, source_service=source_service,
                decision=decision_label,
            ).inc()
        if decision_label == "shadow-would-refuse":
            _shadow_note(event_type, source_service)
        if decision_label == "deny-no-policy":
            logger.error(
                f"[EmissionPolicy] DENIED (fail-closed): no policy row for {event_type} "
                f"from {source_service}. Add a policy row via /admin/event-emission-policies "
                f"to re-enable. See §pass52 Phase J + project_event_emission_policy_not_authoritative."
            )
            return False
        return True  # No policy row = allow (event types without policy rows are unregulated)

    if source_service == 'teg':
        allowed = policy['emit_from_teg']
    elif source_service == 'registry':
        allowed = policy['emit_from_registry']
    else:
        if _gate_decision_total is not None:
            _gate_decision_total.labels(
                event_type=event_type, source_service=source_service,
                decision="deny-unknown-source",
            ).inc()
        return False  # Unknown source = DENY (fail-closed for security)

    if _gate_decision_total is not None:
        _gate_decision_total.labels(
            event_type=event_type, source_service=source_service,
            decision="allow" if allowed else "deny-policy",
        ).inc()
    return allowed


def get_emission_policies_snapshot() -> Dict[str, dict]:
    """Return current policy cache for admin API / diagnostics."""
    return dict(_emission_policy_cache)


def emission_policy_state() -> Dict[str, Any]:
    """W3: this process's view of the policy table, for the admin read: how many rows it holds, when it last read
    them, and the last read's failure."""
    return {
        "rows_cached": len(_emission_policy_cache),
        "loaded_at": (datetime.fromtimestamp(_emission_policy_loaded_wall, tz=timezone.utc).isoformat()
                      if _emission_policy_loaded_wall else None),
        "load_error": _emission_policy_load_error,
        "mode": emission_policy_mode(),
    }


def _shadow_note(event_type: str, source_service: str) -> None:
    """W3 shadow: an event type with no row, which enforce would refuse. Logged once per type per process and counted
    in Redis across the workers (the admin read's per-type figure); the emit itself goes on, never waits for either."""
    if event_type not in _shadow_logged:
        _shadow_logged.add(event_type)
        logger.warning(
            f"[EmissionPolicy] SHADOW: no policy row for {event_type} from {source_service}; enforce would refuse it "
            f"(mode {emission_policy_mode()}). Its row belongs in a migration's EMISSION_POLICY_ROWS."
        )
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_shadow_count(event_type))


async def _shadow_count(event_type: str) -> None:
    try:
        from .background_tasks.leader import get_redis
        r = await asyncio.wait_for(get_redis(), timeout=1.0)
        if r is not None:
            await asyncio.wait_for(r.hincrby(SHADOW_REDIS_KEY, event_type, 1), timeout=1.0)
            await asyncio.wait_for(r.expire(SHADOW_REDIS_KEY, 7 * 86400), timeout=1.0)
    except Exception:  # noqa: BLE001 — a count, never the emit's concern
        pass


async def shadow_counts() -> Optional[Dict[str, int]]:
    """W3: the shadow refusals counted across the workers (the last 7 days of activity); None when Redis is not
    readable (the admin read says so, never a zero it did not measure)."""
    try:
        from .background_tasks.leader import get_redis
        r = await asyncio.wait_for(get_redis(), timeout=2.0)
        if r is None:
            return None
        raw = await asyncio.wait_for(r.hgetall(SHADOW_REDIS_KEY), timeout=2.0)
        out: Dict[str, int] = {}
        for k, v in (raw or {}).items():
            k = k.decode() if isinstance(k, bytes) else str(k)
            out[k] = int(v.decode() if isinstance(v, bytes) else v)
        return out
    except Exception:  # noqa: BLE001
        return None


async def emission_policy_boot_check() -> Dict[str, Any]:
    """W3: at startup, the emitted types (core/event_catalog.py) this frame's table has no row for: named once per
    process in a WARNING and published as a gauge per emitter. Never raises; the admin read shows the same lists."""
    try:
        await _load_emission_policies()
        from .core.event_catalog import REGISTRY_EMITS, TEG_EMITS, TEG_ALWAYS_ALLOWED
        rows = set(_emission_policy_cache)
        if not rows:
            logger.warning(f"[EmissionPolicy] boot check: the policy table was not read ({_emission_policy_load_error})")
            return {"read": False, "error": _emission_policy_load_error}
        missing = {"registry": sorted(REGISTRY_EMITS - rows), "teg": sorted(TEG_EMITS - rows - TEG_ALWAYS_ALLOWED)}
        if _missing_rows_gauge is not None:
            for k, v in missing.items():
                _missing_rows_gauge.labels(emitter=k).set(len(v))
        names = sorted(set(missing["registry"]) | set(missing["teg"]))
        if names:
            logger.warning(
                f"[EmissionPolicy] boot check: {len(names)} emitted event type(s) have no policy row on this frame "
                f"(mode {emission_policy_mode()}): {', '.join(names)}"
            )
        else:
            logger.info(f"[EmissionPolicy] boot check: every emitted event type has its policy row ({len(rows)} rows, "
                        f"mode {emission_policy_mode()})")
        return {"read": True, "rows": len(rows), "missing": missing}
    except Exception as e:  # noqa: BLE001 — a check, never a boot failure
        logger.warning(f"[EmissionPolicy] boot check failed: {type(e).__name__}: {e}")
        return {"read": False, "error": f"{type(e).__name__}: {e}"[:300]}


# Phase 10 #3: Redis-backed cache invalidation. Per-uvicorn-worker module-level
# state means a write on one worker leaves three others stale until TTL elapses.
# Pub/sub propagates writes to all workers within milliseconds. TTL is the
# safety net if the message is missed.
EMISSION_POLICY_CACHE_NAME = "emission_policy"


async def drop_emission_policy_cache() -> None:
    """Force the next emit() to re-fetch policies from DB. Called by the
    Redis pub/sub listener when an admin update fires invalidation."""
    global _emission_policy_cache_ts
    _emission_policy_cache_ts = 0
    logger.info("[EmissionPolicy] Local cache dropped via invalidation")


async def publish_emission_policy_invalidation() -> None:
    """Publish a Redis pub/sub message to drop the policy cache on every
    worker. Called by the admin endpoint that updates EventEmissionPolicy."""
    try:
        from agentvault_registry.cache_invalidation import publish_invalidation
        await publish_invalidation(EMISSION_POLICY_CACHE_NAME)
    except Exception as e:
        logger.warning(f"[EmissionPolicy] Invalidation publish failed: {e}")


def start_emission_policy_invalidation_listener():
    """Wire up the per-worker subscriber. Called from FastAPI startup."""
    try:
        from agentvault_registry.cache_invalidation import start_invalidation_listener
        start_invalidation_listener(
            EMISSION_POLICY_CACHE_NAME,
            on_invalidate=drop_emission_policy_cache,
        )
    except Exception as e:
        logger.warning(f"[EmissionPolicy] Invalidation listener setup failed: {e}")


# Global event emitter instance
_event_emitter: Optional[EventEmitter] = None


def own_store_key() -> str:
    """The internal key this registry presents to its own event store (EVENT_STORE_API_KEY, else EVENT_STORE_INTERNAL_KEY):
    the store's INTERNAL_API_KEY, which a frame's template gives both. SEC-12: the public account id is keyed with it too
    (identifiers.public_account_id), as the store keys its own."""
    return os.getenv('EVENT_STORE_API_KEY', os.getenv('EVENT_STORE_INTERNAL_KEY', ''))


def get_event_emitter() -> EventEmitter:
    """
    Get or create the global event emitter instance.
    
    Returns:
        EventEmitter instance
    """
    global _event_emitter
    if _event_emitter is None:
        event_store_url = os.getenv('EVENT_STORE_URL', 'http://localhost:8200')
        internal_api_key = own_store_key()
        _event_emitter = EventEmitter(
            event_store_url=event_store_url,
            internal_api_key=internal_api_key,
            source_service="registry"
        )
    return _event_emitter
