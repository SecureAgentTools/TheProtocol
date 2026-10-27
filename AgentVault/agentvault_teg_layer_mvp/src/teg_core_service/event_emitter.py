"""
Event Emitter for TEG and Registry services
This module can be imported by TEG/Registry to emit events to the Event Store

f037: Emission policy support — fetches policies from Registry API to determine
which event types the TEG is authorized to emit. Falls back to env var blocklist.

§SOVKIT K1 (2026-09-14): the TEG writes to its event store over HTTP only, through the frame's mTLS
sidecar; Kafka is private to the store (the TEG's fire-and-forget producer was removed).
"""

import aiohttp
import ssl
import json
import logging
import os
import uuid
import time as _time
from typing import Any, Dict, Optional, Set, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# 2026-06-02 (FX Phase 1 canary-outage fix): bound the EventEmitter HTTP emit so a
# hung/unreachable EventStore endpoint fails fast instead of blocking on aiohttp's 300s
# default. Without this, during a broken-cert/unreachable-ES window emits pile up (default
# 100 conns) and the TEG event loop wedges (sandbox cloud-op TEG wedge, localhost /health
# → 000). Mirrors core/cross_teg/client.py's existing httpx.Timeout(20) + Limits(max=10).
_EMIT_TIMEOUT = aiohttp.ClientTimeout(total=10, connect=5)
_EMIT_CONN_LIMIT = 20

# §pass52 Phase A: observability counters (pure additive, no behavior change)
try:
    from prometheus_client import Counter as _PCounter
    _gate_decision_total = _PCounter(
        "event_emitter_gate_decision_total",
        "TEG emission gate decisions",
        ["event_type", "source_service", "decision"],
    )
    _unknown_event_type_total = _PCounter(
        "event_emitter_unknown_event_type_total",
        "TEG emit attempts for event types with no policy row (fail-closed default)",
        ["event_type", "source_service"],
    )
    _idem_key_form_total = _PCounter(
        "event_emitter_idempotency_key_form_total",
        "TEG idempotency-key form on emit() calls",
        ["event_type", "key_form"],
    )
except ImportError:
    _gate_decision_total = None
    _unknown_event_type_total = None
    _idem_key_form_total = None


# BALANCE_MOVING_EVENT_TYPES — events that mutate agent balance projection.
# Must match the Registry-side constant exactly (single source of truth).
BALANCE_MOVING_EVENT_TYPES = frozenset({
    "TokensIssued", "TokensTransferred", "TokensStaked", "TokensUnstaked",
    "BalanceCorrected", "DisputeSlash", "DisputeCompensationMinted",
    "TransactionFeeCollected", "RewardsAutoCompounded", "ProjectionSnapshot",
})


# f037: Policy cache for TEG emission control
_teg_policy_cache: Dict[str, bool] = {}  # event_type → emit_from_teg
_teg_policy_cache_ts: float = 0
_TEG_POLICY_CACHE_TTL = 120  # seconds — refresh from Registry API every 2 min


_svid_ctx_cache: Dict[str, Any] = {"key": None, "ctx": None}
_policy_fetch_warned_at: float = -1e9


def _svid_ssl_context() -> Tuple[Optional[ssl.SSLContext], float]:
    """The frame SVID as a client TLS context, built in ONE place for the emitter's sessions and the policy fetch.

    Returns (context, the newer of the certificate's and the bundle's mtimes), or (None, 0.0) when a file is missing
    or unreadable. Cached on the directory and that mtime, so a rotated SVID is read on the next call (§MTLSHOPS
    V0379: after agentvault2-b5's registry terminator the policy fetch must present it too).
    """
    cert_dir = os.getenv("SVID_CERT_DIR", "/certs")
    cert_path = os.path.join(cert_dir, "svid.0.pem")
    key_path = os.path.join(cert_dir, "svid.0.key")
    ca_path = os.path.join(cert_dir, "bundle.0.pem")
    if not (os.path.exists(cert_path) and os.path.exists(key_path) and os.path.exists(ca_path)):
        return None, 0.0
    try:
        mtime = max(os.path.getmtime(cert_path), os.path.getmtime(ca_path))
    except OSError:
        return None, 0.0
    if _svid_ctx_cache["key"] == (cert_dir, mtime):
        return _svid_ctx_cache["ctx"], mtime
    try:
        ctx = ssl.create_default_context(cafile=ca_path)
        # §pass73.3.20 — ALSO trust public CAs (system roots) so the L2 balance outbox
        # can verify the PUBLIC ES endpoint (events.theprotocol.cloud, Let's Encrypt) for
        # OFF-HOST operators, in addition to the SPIRE bundle (internal nginx-event-store).
        # create_default_context(cafile=...) loads ONLY the bundle; this adds the system
        # roots without replacing it. The mTLS client cert + X-Federation-License header
        # are still presented, so the operator revocation/quarantine chain stays intact.
        try:
            ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
        except Exception:
            pass
        ctx.load_cert_chain(cert_path, key_path)
    except Exception:
        return None, 0.0
    _svid_ctx_cache.update(key=(cert_dir, mtime), ctx=ctx)
    return ctx, mtime


def _warn_policy_fetch(message: str) -> None:
    """A failed fetch leaves the TEG deciding from its cached or import-time policies, and after b2 a refused
    certificate is one way to fail. WARNING at most once every ten minutes, DEBUG for the rest, so a registry that
    stays unreachable does not flood the log."""
    global _policy_fetch_warned_at
    now = _time.monotonic()
    if now - _policy_fetch_warned_at >= 600:
        _policy_fetch_warned_at = now
        logger.warning(message)
    else:
        logger.debug(message)


async def _fetch_teg_policies():
    """Fetch emission policies from the Registry API."""
    global _teg_policy_cache, _teg_policy_cache_ts
    registry_url = os.getenv('REGISTRY_URL', 'http://registry-a:8000')
    api_key = os.getenv('REGISTRY_API_KEY', '')

    try:
        ctx, _ = _svid_ssl_context()
        connector = aiohttp.TCPConnector(ssl=ctx) if ctx is not None else None
        async with aiohttp.ClientSession(connector=connector) as session:
            headers = {}
            if api_key:
                headers['Authorization'] = f'Bearer {api_key}'
            async with session.get(
                f'{registry_url}/api/v1/agents/locations/emission-policies',
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    new_cache = {}
                    for p in data.get('policies', []):
                        new_cache[p['event_type']] = p.get('emit_from_teg', False)
                    # §pass73.3.20: LedgerBalanceChanged is TEG-NATIVE (the L2 balance outbox emits it;
                    # the registry never does). Force-allow it regardless of the registry policy table —
                    # otherwise this fetch blanks the import-time seed and cloud-op TEGs (whose own
                    # registry lacks the row) silently DROP balance events (emit() returns True but no
                    # POST). This removes the per-registry-DB policy-row dependency fleet-wide.
                    new_cache["LedgerBalanceChanged"] = True
                    _teg_policy_cache = new_cache
                    _teg_policy_cache_ts = _time.monotonic()
                    logger.info(f"[EmissionPolicy] TEG loaded {len(new_cache)} policies from Registry API")
                    return
                _warn_policy_fetch(f"[EmissionPolicy] Registry API answered {resp.status}; the TEG keeps its cached policies")
    except Exception as e:
        _warn_policy_fetch(f"[EmissionPolicy] Failed to fetch from Registry API: {type(e).__name__}: {e}")

    # Fallback: use env var blocklist
    if not _teg_policy_cache:
        blocked = os.getenv('TEG_BLOCKED_EVENT_TYPES',
            'TokensTransferred,TokensStaked,TokensUnstaked,StakeForceUnstaked,'
            'RewardsDistributed,RewardsAutoCompounded,DailyDistributionCompleted,'
            'CrossRegistryTransferCompleted,DisputeSlash,DisputeCompensationMinted'
        ).split(',')
        _teg_policy_cache = {evt.strip(): False for evt in blocked if evt.strip()}
        _teg_policy_cache_ts = _time.monotonic()
        logger.info(f"[EmissionPolicy] TEG using env var fallback: {len(_teg_policy_cache)} blocked types")


def _teg_should_emit(event_type: str) -> bool:
    """Check if TEG is authorized to emit this event type.

    §pass52 Phase A: instrumented. TEG fails CLOSED (unknown event types are
    denied). Counter labels:
      - allow         — explicit emit_from_teg=true row
      - deny-policy   — explicit emit_from_teg=false row
      - deny-no-policy — no policy row at all (TEG fail-closed default)
    """
    if event_type in _teg_policy_cache:
        allowed = _teg_policy_cache[event_type]
        if _gate_decision_total is not None:
            _gate_decision_total.labels(
                event_type=event_type, source_service="teg",
                decision="allow" if allowed else "deny-policy",
            ).inc()
        return allowed
    # Unknown event type — TEG fails closed
    if _unknown_event_type_total is not None:
        _unknown_event_type_total.labels(
            event_type=event_type, source_service="teg",
        ).inc()
    if _gate_decision_total is not None:
        _gate_decision_total.labels(
            event_type=event_type, source_service="teg",
            decision="deny-no-policy",
        ).inc()
    return False  # Unknown event type → DENY (fail-closed for security)


# f037: Populate cache IMMEDIATELY at import time from env var (sync, no API call)
# This ensures the very first emit() call is already gated.
_initial_blocked = os.getenv('TEG_BLOCKED_EVENT_TYPES',
    'TokensTransferred,TokensStaked,TokensUnstaked,StakeForceUnstaked,'
    'RewardsDistributed,RewardsAutoCompounded,DailyDistributionCompleted,'
    'CrossRegistryTransferCompleted,DisputeSlash,DisputeCompensationMinted'
).split(',')
_teg_policy_cache = {evt.strip(): False for evt in _initial_blocked if evt.strip()}
# §pass73.3.19 L2 CQRS outbox: LedgerBalanceChanged is a TEG-NATIVE event (only the balance
# outbox emits it; Registry never does). TEG is fail-closed on no-policy types, so seed it
# allowed at import time — otherwise the first outbox emits silently no-op before the policy
# fetch lands. ⚠ There is NO policy row for it anywhere: measured 2026-09-05 (§EVTYPES) on prod
# registry-a AND both sandbox frames, `event_emission_policies` has no LedgerBalanceChanged row.
# An earlier comment here claimed a "belt+suspenders" row existed — it does not, and never did.
# The force-allow below and its twin in _fetch_teg_policies() are the ONLY things keeping the
# balance outbox alive; deleting either silently stops every ledger balance event fleet-wide.
# `.forgejo/checks/teg_emission_policy_contract.py` pins both against the source.
_teg_policy_cache["LedgerBalanceChanged"] = True
_teg_policy_cache_ts = _time.monotonic()
logger.info(f"[EmissionPolicy] TEG initial blocklist: {len(_teg_policy_cache)} event types blocked")


# Phase 11.1 (2026-04-28): Redis pub/sub cache invalidation. The /admin/emission-
# policy/refresh handler publishes an invalidation, every other TEG worker's
# listener drops its local cache timestamp, and the next emit() refetches. TTL
# is the safety net if the message is missed.
EMISSION_POLICY_CACHE_NAME = "emission_policy"


async def drop_emission_policy_cache() -> None:
    """Force the next emit() to re-fetch policies from Registry API. Called by
    the TEG-side Redis pub/sub listener when an invalidation message arrives."""
    global _teg_policy_cache_ts
    _teg_policy_cache_ts = 0
    logger.info("[EmissionPolicy] TEG local cache dropped via invalidation")


async def publish_emission_policy_invalidation() -> None:
    """Publish an invalidation message to all TEG workers."""
    try:
        from .cache_invalidation import publish_invalidation
        await publish_invalidation(EMISSION_POLICY_CACHE_NAME)
    except Exception as e:
        logger.warning(f"[EmissionPolicy] TEG invalidation publish failed: {e}")


def start_emission_policy_invalidation_listener():
    """Wire up the per-worker subscriber. Called from FastAPI startup."""
    try:
        from .cache_invalidation import start_invalidation_listener
        start_invalidation_listener(
            EMISSION_POLICY_CACHE_NAME,
            on_invalidate=drop_emission_policy_cache,
        )
    except Exception as e:
        logger.warning(f"[EmissionPolicy] TEG invalidation listener setup failed: {e}")


# ---------------------------------------------------------------------------
# §SOVKIT K1 (his word 2026-09-14 "2 yes": Kafka is PRIVATE to the event store).
# The TEG used to produce to Redpanda first and fall back to HTTP; the store's consumer took whatever arrived on
# :9092 with none of the HTTP route's checks. The TEG now writes ONLY through the store's HTTP route (over the
# frame's mTLS sidecar, V0370+ template); the broker belongs to the store alone. `shutdown_kafka` stays as a
# no-op so main.py's shutdown hook keeps its call.
# ---------------------------------------------------------------------------
async def shutdown_kafka():
    """No-op since §SOVKIT K1: the TEG holds no Kafka producer (kept for main.py's shutdown hook)."""
    return None


class EventEmitter:
    """
    Client for emitting events to the Event Store.
    This class should be used by TEG and Registry services.

    §SOVKIT K1 (2026-09-14): HTTP to the store's route only (the Kafka producer was removed).
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
        self.federation_license_key = os.getenv("FEDERATION_LICENSE_KEY", "")
        self.federation_operator_id = os.getenv("FEDERATION_OPERATOR_ID", "")
        # §LEDGERGATE: the store's answer to the last emit (its HTTP status; None when none came back). The balance
        # outbox reads it to tell an event the store rejected (422) from a store it could not reach.
        self.last_status: Optional[int] = None
        # mTLS client certs (SPIRE SVIDs). Built here + rebuilt on rotation by
        # _refresh_ssl_if_needed(): a long-lived aiohttp session pins the client cert at
        # connector-build time, so without refresh the emitter keeps presenting the SVID
        # captured at startup and — once its issuing CA ages out of the rotating SPIRE
        # trust bundle — the EventStore nginx rejects every emit with HTTP 400 until the
        # process restarts (frame-b TEG incident 2026-05-29).
        self._ssl_context: Optional[ssl.SSLContext] = None
        self._cert_mtime: float = 0.0
        self._last_ssl_check: float = 0.0
        self._build_ssl_context()

    def _build_ssl_context(self) -> None:
        """(Re)build the mTLS SSL context from the on-disk SPIRE SVID + trust bundle and
        record the cert mtime for rotation detection. Safe to call repeatedly. Mirrors the
        self-heal pattern in core/cross_teg/client.py:_refresh_ssl_if_needed()."""
        ctx, mtime = _svid_ssl_context()
        if ctx is None:
            return  # a missing or unreadable file keeps the context already held, as it always did
        self._ssl_context = ctx
        self._cert_mtime = mtime

    async def _refresh_ssl_if_needed(self) -> None:
        """Rebuild the mTLS context + drop the cached aiohttp session when the SPIRE SVID/
        bundle rotates on disk. Without this the long-lived session keeps presenting the SVID
        captured at startup; once its issuing CA ages out of the rotating trust bundle the
        EventStore nginx rejects every emit with HTTP 400 until the process restarts
        (frame-b TEG incident 2026-05-29). Throttled to one stat() sweep per 15s."""
        if self._ssl_context is None:
            return  # plain HTTP (no mTLS configured) — nothing to refresh
        now = _time.monotonic()
        if now - self._last_ssl_check < 15.0:
            return
        self._last_ssl_check = now
        cert_dir = os.getenv("SVID_CERT_DIR", "/certs")
        try:
            newest = max(
                os.path.getmtime(os.path.join(cert_dir, "svid.0.pem")),
                os.path.getmtime(os.path.join(cert_dir, "bundle.0.pem")),
            )
        except OSError:
            return
        if newest <= self._cert_mtime:
            return  # no rotation since the context was last built
        logger.info("[EventEmitter] SPIRE SVID/bundle rotated — rebuilding mTLS context + session")
        self._build_ssl_context()
        old, self.session = self.session, None
        if old is not None and not old.closed:
            try:
                await old.close()
            except Exception:
                pass

    async def __aenter__(self):
        """Async context manager entry"""
        connector = aiohttp.TCPConnector(ssl=self._ssl_context, limit=_EMIT_CONN_LIMIT) if self._ssl_context else aiohttp.TCPConnector(limit=_EMIT_CONN_LIMIT)
        self.session = aiohttp.ClientSession(connector=connector, timeout=_EMIT_TIMEOUT)
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
        idempotency_key: Optional[str] = None
    ) -> bool:
        """
        Emit an event to the Event Store.
        
        Args:
            event_type: Type of event (e.g., "TokensIssued")
            aggregate_id: ID of the aggregate (e.g., agent DID)
            data: Event data payload
            aggregate_type: Type of aggregate (default: "Agent")
            metadata: Optional metadata
            
        Returns:
            bool: True if successful, False otherwise
        """
        # Self-heal: rebuild the mTLS SSL context + session if the SPIRE SVID/bundle
        # rotated on disk (stops the long-lived session presenting a stale cert → 400).
        await self._refresh_ssl_if_needed()

        if not self.session:
            # Create session if not using context manager
            connector = aiohttp.TCPConnector(ssl=self._ssl_context, limit=_EMIT_CONN_LIMIT) if self._ssl_context else aiohttp.TCPConnector(limit=_EMIT_CONN_LIMIT)
            self.session = aiohttp.ClientSession(connector=connector, timeout=_EMIT_TIMEOUT)

        # f037: Refresh policy cache if stale
        if _time.monotonic() - _teg_policy_cache_ts > _TEG_POLICY_CACHE_TTL:
            try:
                import asyncio
                asyncio.ensure_future(_fetch_teg_policies())
            except Exception:
                pass

        # f037: Check emission policy
        if not _teg_should_emit(event_type):
            logger.info(f"[EmissionPolicy] TEG BLOCKED: {event_type} (policy: emit_from_teg=false)")
            return True

        # Deterministic key (e.g. L2 outbox: ledger-tx-{teg}-{txid}) → ES UNIQUE(idempotency_key)
        # makes re-emits exactly-once (409 → treated as success below). Falls back to random uuid.
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

        # §SOVKIT K1: no Kafka path; the store's HTTP route is the ONE write path (through the frame's mTLS sidecar).
        # Fallback: HTTP POST to EventStore
        headers = {"Content-Type": "application/json"}
        if self.federation_license_key:
            headers["X-Federation-License"] = self.federation_license_key
        else:
            headers["X-Internal-Key"] = self.internal_api_key

        try:
            async with self.session.post(
                f"{self.event_store_url}/api/v1/events/",
                json=event_payload,
                headers=headers
            ) as response:
                self.last_status = response.status
                if response.status in (200, 201):
                    result = await response.json()
                    logger.info(f"Emitted {event_type} event for {aggregate_id}: {result['id']}")
                    return True
                elif response.status == 202:
                    # Accepted for async processing via HTTP→Kafka bridge on
                    # destination ES (EVENTSTORE_HTTP_VIA_KAFKA=true). Body has
                    # idempotency_key + event_id; not a failure.
                    result = await response.json()
                    logger.debug(
                        f"Accepted (async via Kafka) {event_type} for {aggregate_id}: "
                        f"{result.get('event_id', 'unknown')}"
                    )
                    return True
                elif response.status == 409:
                    logger.info(f"Idempotent duplicate: {event_type} for {aggregate_id}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to emit event: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            self.last_status = None
            logger.error(f"Error emitting event: {e}")
            return False
    
    # Convenience methods for common events
    
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
            }
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
            aggregate_id=from_agent,  # Sender is the aggregate
            data=data
        )
    
    async def emit_tokens_staked(
        self,
        agent_did: str,
        amount: str,
        pool_id: str,
        lock_period_days: int = 30,
        expected_apy: Optional[str] = None
    ) -> bool:
        """Emit a TokensStaked event"""
        data = {
            "amount": amount,
            "pool_id": pool_id,
            "lock_period_days": lock_period_days
        }
        if expected_apy:
            data["expected_apy"] = expected_apy
            
        return await self.emit(
            event_type="TokensStaked",
            aggregate_id=agent_did,
            data=data
        )
    
    async def emit_tokens_unstaked(
        self,
        agent_did: str,
        amount: str,
        pool_id: str,
        rewards_earned: Optional[str] = None
    ) -> bool:
        """Emit a TokensUnstaked event"""
        data = {
            "amount": amount,
            "pool_id": pool_id
        }
        if rewards_earned:
            data["rewards_earned"] = rewards_earned
            
        return await self.emit(
            event_type="TokensUnstaked",
            aggregate_id=agent_did,
            data=data
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
            }
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
    
    async def close(self):
        """Close the HTTP session"""
        if self.session:
            await self.session.close()
            self.session = None


# Example usage in TEG service:
"""
from event_emitter import EventEmitter

# Initialize emitter
emitter = EventEmitter(
    event_store_url="http://localhost:8200",
    internal_api_key="your-internal-key",
    source_service="teg"
)

# After a token transfer in TEG
async def transfer_tokens(from_did, to_did, amount):
    # ... existing transfer logic ...
    
    # Emit event
    await emitter.emit_tokens_transferred(
        from_agent=from_did,
        to_agent=to_did,
        amount=str(amount),
        transaction_id=transaction_id
    )
"""
