"""
Projection Service - Calculates current state from event streams

f037: Added emission policy support — fetches skip_in_projection flags from
Registry API to dynamically control which event types affect balance calculations.
"""

from typing import Dict, List, Optional, Tuple, Set
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from src.models.events import Event
from src.services.event_store import EventStore
import logging
import time
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# f037: Projection Skip Policy — fetched from Registry API
# ---------------------------------------------------------------------------
_skip_in_projection: Set[str] = {'RewardsDistributed'}  # Default: hardcoded known skips
_skip_policy_cache_ts: float = 0
_SKIP_POLICY_TTL = 120  # seconds

# §pass53 PR-11b: known-event-type registry. Populated from the same Registry
# policy fetch (`_refresh_skip_policies`). Used by `_is_known_event_type()` at
# the EventStore write boundary to reject unknown event types AFTER the §pass52
# Phase J fail-closed flip is verified safe.
# Default to empty + fail-open behavior; the policy refresh populates this with
# all event_types that have a policy row, regardless of skip_in_projection flag.
# This is the closed-set source for PR-11b's defensive validator.
_known_event_types: Set[str] = set()

# §pass52 Phase A: observability counters (pure additive)
try:
    from prometheus_client import Counter as _PCounter
    _projection_skipped_total = _PCounter(
        "projection_event_skipped_total",
        "Events skipped in balance projection",
        ["event_type", "reason"],
    )
except ImportError:
    _projection_skipped_total = None

# BALANCE_MOVING_EVENT_TYPES — events that mutate agent balance projection.
# Mirror of the Registry / TEG constant. Used by Phase H write-time validator
# (in routers/events.py) to reject misconfigured skip_in_projection flags
# and missing idempotency keys on balance-moving events.
BALANCE_MOVING_EVENT_TYPES = frozenset({
    "TokensIssued", "TokensTransferred", "TokensStaked", "TokensUnstaked",
    "BalanceCorrected", "DisputeSlash", "DisputeCompensationMinted",
    "TransactionFeeCollected", "RewardsAutoCompounded", "ProjectionSnapshot",
})


async def _refresh_skip_policies():
    """Fetch skip_in_projection flags from Registry emission policies API.

    §pass53 PR-11b: also populates _known_event_types with every event_type
    that has a policy row (regardless of skip flag). Used by the write-boundary
    validator in routers/events.py to reject unknown event types when
    EVENTSTORE_STRICT_EVENT_TYPES=true (deferred enforcement; observability-only
    by default).
    """
    global _skip_in_projection, _skip_policy_cache_ts, _known_event_types
    registry_url = os.getenv('REGISTRY_URL', 'http://registry-a:8000')
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f'{registry_url}/api/v1/agents/locations/emission-policies',
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    new_skips = set()
                    new_known = set()
                    for p in data.get('policies', []):
                        et = p.get('event_type')
                        if et:
                            new_known.add(et)
                            if p.get('skip_in_projection', False):
                                new_skips.add(et)
                    _skip_in_projection = new_skips
                    _known_event_types = new_known
                    _skip_policy_cache_ts = time.monotonic()
                    logger.info(
                        f"[ProjectionPolicy] Loaded skip set: {new_skips or 'none'} | "
                        f"known event_types: {len(new_known)}"
                    )
                    return
    except Exception as e:
        logger.debug(f"[ProjectionPolicy] Failed to fetch from Registry: {e} — using defaults")


def _is_known_event_type(event_type: str) -> bool:
    """§pass53 PR-11b: is this event_type registered in the policy table?

    Used at the EventStore write boundary. The closed set is derived dynamically
    from the policy table cache (refreshed every 120s + on Redis pub/sub
    invalidation per Phase F). When EVENTSTORE_STRICT_EVENT_TYPES=true,
    unknown types are rejected at append_event with 422. Default behavior
    (env unset): permissive — only logs a warning via the Phase A counter.
    """
    # Empty set = cache not yet populated → never reject (fail-open during startup)
    if not _known_event_types:
        return True
    return event_type in _known_event_types


def _should_skip_in_projection(event_type: str) -> bool:
    """Check if this event type should be skipped in balance projection.

    §pass52 Phase A: instrumented with `projection_event_skipped_total` Prom
    counter so we can prove skip rates per event_type and catch spurious skips
    on balance-moving events (which would be a Phase H validator failure).
    """
    if event_type in _skip_in_projection:
        if _projection_skipped_total is not None:
            _projection_skipped_total.labels(
                event_type=event_type, reason="skip_in_projection"
            ).inc()
        return True
    return False


def _safe_decimal(value) -> Decimal:
    """Parse amount that may be int, float, string-int, or string-float.
    Returns Decimal to preserve fractional AVT (staking rewards, fees).
    E.g. 1000, 1000.5, '1000', '1000.046' all -> Decimal('1000.046')"""
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


# _safe_int removed — was dead code with int(float()) truncation


# P2-005: Simple in-memory balance cache with TTL
# Avoids replaying entire event stream for every balance query.
# Cache entries expire after CACHE_TTL_SECONDS.
CACHE_TTL_SECONDS = 30  # Balance is fresh for 30 seconds
_balance_cache: Dict[str, Tuple[float, 'BalanceProjection']] = {}  # agent_did -> (expiry_ts, projection)
_cache_max_size = 500  # Evict oldest entries when exceeded


def _get_cached_balance(agent_did: str) -> Optional['BalanceProjection']:
    """Get a cached balance if it exists and hasn't expired."""
    entry = _balance_cache.get(agent_did)
    if entry is None:
        return None
    expiry_ts, projection = entry
    if time.monotonic() > expiry_ts:
        del _balance_cache[agent_did]
        return None
    return projection


def _set_cached_balance(agent_did: str, projection: 'BalanceProjection'):
    """Store a balance in the cache with TTL."""
    # Simple size eviction: clear oldest half if at capacity
    if len(_balance_cache) >= _cache_max_size:
        sorted_keys = sorted(_balance_cache, key=lambda k: _balance_cache[k][0])
        for k in sorted_keys[:len(sorted_keys) // 2]:
            del _balance_cache[k]
    _balance_cache[agent_did] = (time.monotonic() + CACHE_TTL_SECONDS, projection)


def invalidate_balance_cache(agent_did: Optional[str] = None):
    """Invalidate cache for a specific agent, or all agents if None."""
    if agent_did:
        _balance_cache.pop(agent_did, None)
    else:
        _balance_cache.clear()


class BalanceProjection:
    """Represents current balance state calculated from events"""
    def __init__(
        self,
        agent_did: str,
        liquid_balance = 0,
        staked_balance = 0,
        last_event_timestamp: Optional[datetime] = None,
        event_count: int = 0
    ):
        self.agent_did = agent_did
        self.liquid_balance = Decimal(str(liquid_balance))
        self.staked_balance = Decimal(str(staked_balance))
        self.last_event_timestamp = last_event_timestamp
        self.event_count = event_count

    def to_dict(self) -> Dict:
        return {
            "agent_did": self.agent_did,
            "liquid_balance": float(self.liquid_balance),
            "staked_balance": float(self.staked_balance),
            "total_balance": float(self.liquid_balance + self.staked_balance),
            "last_event_timestamp": self.last_event_timestamp.isoformat() if self.last_event_timestamp else None,
            "event_count": self.event_count
        }


class TransactionHistoryItem:
    """Represents a single transaction in history"""
    def __init__(
        self,
        id: str,
        event_type: str,
        amount: Optional[str],
        timestamp: datetime,
        details: Dict
    ):
        self.id = id
        self.event_type = event_type
        self.amount = amount
        self.timestamp = timestamp
        self.details = details
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type": self.event_type,
            "amount": self.amount,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details
        }


class ProjectionService:
    """
    Service for building projections (read models) from event streams.
    Implements the Event Sourcing pattern for calculating current state.

    Phase 1 Scaling: When MATERIALIZED_BALANCES=true (default), balance lookups
    read from the trigger-maintained materialized_balances table (O(1)) instead
    of replaying all events (O(n)). Falls back to event replay on any failure.
    """
    
    TRANSACTION_EVENT_TYPES = [
        "TokensIssued",
        "TokensTransferred",
        "TokensStaked",
        "TokensUnstaked",
        "RewardsDistributed",       # OWL20-PREP: Staking reward payouts
        "RewardsAutoCompounded",    # OWL20-PREP: Auto-compounded rewards
        "DisputeSlash",             # OWL25: Sovereign slash on defendant
        "DisputeCompensationMinted",# OWL25: Sovereign mint for complainant
        "CrossRegistryTransferCompleted",  # OWL-BRIDGE: Some cross-reg transfers ONLY have this event
        "BalanceCorrected",                   # Manual correction event (admin reconciliation)
        "TransactionFeeCollected",            # TEG fee deducted from sender on top of transfer
    ]
    
    def __init__(self, event_store: EventStore):
        self.event_store = event_store
        logger.info("ProjectionService initialized")
    
    async def calculate_balance(self, agent_did: str) -> BalanceProjection:
        """
        Calculate current balance for an agent.

        Resolution order (fastest first):
        1. In-memory cache (P2-005, 30s TTL)
        2. Materialized balance table (Phase 1 Scaling, O(1) SQL read)
        3. Full event replay (original path, O(n))
        """
        # P2-005: Check cache first
        cached = _get_cached_balance(agent_did)
        if cached is not None:
            logger.debug(f"Cache hit for {agent_did}")
            return cached

        # Phase 1 Scaling: Try materialized balance table (O(1))
        try:
            from .materialized_projections import get_materialized_balance
            mat = await get_materialized_balance(self.event_store.db, agent_did)
            if mat is not None:
                projection = BalanceProjection(
                    agent_did=agent_did,
                    liquid_balance=mat["liquid_balance"],
                    staked_balance=mat["staked_balance"],
                    last_event_timestamp=mat["last_event_timestamp"],
                    event_count=mat["event_count"],
                )
                _set_cached_balance(agent_did, projection)
                logger.debug(f"Materialized hit for {agent_did}")
                return projection
        except Exception as mat_exc:
            logger.debug(f"Materialized lookup failed for {agent_did}, falling back to replay: {mat_exc}")

        logger.info(f"Calculating balance for agent: {agent_did} (event replay)")

        # f037: Refresh projection skip policies if stale
        if time.monotonic() - _skip_policy_cache_ts > _SKIP_POLICY_TTL:
            try:
                import asyncio
                await _refresh_skip_policies()
            except Exception:
                pass

        # Get all events involving this agent (as aggregate or recipient)
        events = await self.event_store.get_events_involving_agent(agent_did)

        # Initialize projection (Decimal precision to avoid fractional AVT loss)
        liquid_balance = Decimal("0")
        staked_balance = Decimal("0")
        last_timestamp = None

        # Process each event to build current state
        for event in events:
            last_timestamp = event.timestamp

            # f037: Skip event types flagged by emission policy
            if _should_skip_in_projection(event.event_type):
                logger.debug(f"Skipping {event.event_type} (skip_in_projection=true)")
                continue

            # Apply event to projection based on type
            if event.event_type == "TokensIssued":
                amount = _safe_decimal(event.data.get("amount", 0))
                liquid_balance += amount
                logger.debug(f"Applied TokensIssued: +{amount} liquid")

            elif event.event_type == "TokensTransferred":
                amount = _safe_decimal(event.data.get("amount", 0))
                from_agent = event.data.get("from")
                to_agent = event.data.get("to")

                # Deduct from sender
                if from_agent == agent_did:
                    liquid_balance -= amount
                    logger.debug(f"Applied TokensTransferred (sent): -{amount} liquid")

                # Add to receiver
                if to_agent == agent_did:
                    liquid_balance += amount
                    logger.debug(f"Applied TokensTransferred (received): +{amount} liquid")

            elif event.event_type == "TokensStaked":
                amount = _safe_decimal(event.data.get("amount", 0))
                liquid_balance -= amount
                staked_balance += amount
                logger.debug(f"Applied TokensStaked: -{amount} liquid, +{amount} staked")

            elif event.event_type == "TokensUnstaked":
                amount = _safe_decimal(event.data.get("amount", 0))
                liquid_balance += amount
                staked_balance -= amount
                logger.debug(f"Applied TokensUnstaked: +{amount} liquid, -{amount} staked")

            # OWL20-PREP: Rewards that are auto-compounded move from liquid to staked.
            # f037 fix: the preceding TokensIssued event already added `amount` to liquid,
            # so auto-compound must subtract it from liquid before adding to staked.
            elif event.event_type == "RewardsAutoCompounded":
                amount = _safe_decimal(event.data.get("amount", 0))
                liquid_balance -= amount
                staked_balance += amount
                logger.debug(f"Applied RewardsAutoCompounded: -{amount} liquid, +{amount} staked")

            # RewardsDistributed: Now handled by f037 skip_in_projection policy.
            # If skip_in_projection=true in the policy DB, the event is skipped
            # by the policy gate above. No hardcoded skip needed here.

            # OWL25: Dispute slash — deducts from defendant (sovereign local operation)
            elif event.event_type == "DisputeSlash":
                amount = _safe_decimal(event.data.get("amount", 0))
                liquid_balance -= amount
                logger.debug(f"Applied DisputeSlash: -{amount} liquid")

            # OWL25: Dispute compensation mint — credits complainant (sovereign local operation)
            elif event.event_type == "DisputeCompensationMinted":
                amount = _safe_decimal(event.data.get("amount", 0))
                liquid_balance += amount
                logger.debug(f"Applied DisputeCompensationMinted: +{amount} liquid")

            # OWL-BRIDGE: Cross-registry voluntary transfer (sender debited, receiver credited)
            elif event.event_type == "CrossRegistryTransferCompleted":
                amount = _safe_decimal(event.data.get("amount", 0))
                from_agent = event.data.get("from")
                to_agent = event.data.get("to")
                if from_agent == agent_did:
                    liquid_balance -= amount
                    logger.debug(f"Applied CrossRegistryTransferCompleted (sent): -{amount} liquid")
                if to_agent == agent_did:
                    liquid_balance += amount
                    logger.debug(f"Applied CrossRegistryTransferCompleted (received): +{amount} liquid")

            # Manual balance correction (admin reconciliation)
            elif event.event_type == "BalanceCorrected":
                adjustment = _safe_decimal(event.data.get("adjustment", 0))
                liquid_balance += adjustment
                logger.debug(f"Applied BalanceCorrected: {adjustment} liquid")

            # TEG fee: deducted from sender on top of transfer amount
            elif event.event_type == "TransactionFeeCollected":
                fee = _safe_decimal(event.data.get("fee_amount", 0))
                liquid_balance -= fee
                logger.debug(f"Applied TransactionFeeCollected: -{fee} liquid")

        projection = BalanceProjection(
            agent_did=agent_did,
            liquid_balance=liquid_balance,
            staked_balance=staked_balance,
            last_event_timestamp=last_timestamp,
            event_count=len(events)
        )
        
        logger.info(
            f"Balance calculated for {agent_did}: "
            f"liquid={liquid_balance}, staked={staked_balance}, "
            f"events={len(events)}"
        )
        
        # P2-005: Store in cache
        _set_cached_balance(agent_did, projection)
        
        return projection
    
    async def get_transaction_history(
        self,
        agent_did: str,
        limit: int = 50,
        event_types: Optional[List[str]] = None
    ) -> List[TransactionHistoryItem]:
        """
        Build human-readable transaction history from events.
        """
        logger.info(f"Building transaction history for agent: {agent_did}")
        
        # Get all events involving this agent
        events = await self.event_store.get_events_involving_agent(agent_did)
        
        # Filter to transaction events only
        if event_types is None:
            event_types = self.TRANSACTION_EVENT_TYPES
        
        history = []
        for event in events:
            if event.event_type in event_types:
                
                item = TransactionHistoryItem(
                    id=str(event.id),
                    event_type=event.event_type,
                    amount=event.data.get("amount"),
                    timestamp=event.timestamp,
                    details=event.data
                )
                history.append(item)
        
        # Sort by timestamp descending (newest first)
        history.sort(key=lambda x: x.timestamp, reverse=True)
        
        # Apply limit
        if limit:
            history = history[:limit]
        
        logger.info(f"Built transaction history: {len(history)} items")
        return history
    
    async def get_balance_at_timestamp(
        self,
        agent_did: str,
        timestamp: datetime
    ) -> BalanceProjection:
        """
        Calculate balance at a specific point in time.
        Useful for historical queries and auditing.
        """
        logger.info(f"Calculating balance at {timestamp} for agent: {agent_did}")
        
        # Get all events involving this agent up to the specified timestamp
        all_events = await self.event_store.get_events_involving_agent(agent_did)
        events = [e for e in all_events if e.timestamp <= timestamp]
        
        # Same logic as calculate_balance but with filtered events
        liquid_balance = Decimal("0")
        staked_balance = Decimal("0")
        last_timestamp = None

        for event in events:
            last_timestamp = event.timestamp

            # Respect emission policies — skip events marked as skip_in_projection
            if _should_skip_in_projection(event.event_type):
                continue

            if event.event_type == "TokensIssued":
                liquid_balance += _safe_decimal(event.data.get("amount", 0))

            elif event.event_type == "TokensTransferred":
                amount = _safe_decimal(event.data.get("amount", 0))
                if event.data.get("from") == agent_did:
                    liquid_balance -= amount
                if event.data.get("to") == agent_did:
                    liquid_balance += amount

            elif event.event_type == "TokensStaked":
                amount = _safe_decimal(event.data.get("amount", 0))
                liquid_balance -= amount
                staked_balance += amount

            elif event.event_type == "TokensUnstaked":
                amount = _safe_decimal(event.data.get("amount", 0))
                liquid_balance += amount
                staked_balance -= amount

            elif event.event_type == "RewardsAutoCompounded":
                amount = _safe_decimal(event.data.get("amount", 0))
                liquid_balance -= amount
                staked_balance += amount

            # RewardsDistributed: skip (already counted via TokensTransferred)
            elif event.event_type == "RewardsDistributed":
                pass

            elif event.event_type == "DisputeSlash":
                liquid_balance -= _safe_decimal(event.data.get("amount", 0))

            elif event.event_type == "DisputeCompensationMinted":
                liquid_balance += _safe_decimal(event.data.get("amount", 0))

            elif event.event_type == "CrossRegistryTransferCompleted":
                amount = _safe_decimal(event.data.get("amount", 0))
                if event.data.get("from") == agent_did:
                    liquid_balance -= amount
                if event.data.get("to") == agent_did:
                    liquid_balance += amount

            elif event.event_type == "BalanceCorrected":
                liquid_balance += _safe_decimal(event.data.get("adjustment", 0))

            elif event.event_type == "TransactionFeeCollected":
                liquid_balance -= _safe_decimal(event.data.get("fee_amount", 0))

        return BalanceProjection(
            agent_did=agent_did,
            liquid_balance=liquid_balance,
            staked_balance=staked_balance,
            last_event_timestamp=last_timestamp,
            event_count=len(events)
        )
    
    async def get_all_balances(self) -> List[BalanceProjection]:
        """
        Calculate balances for all agents in the system.

        Resolution order (fastest first):
        1. Materialized balance table (Phase 1 Scaling, O(agents) SQL read)
        2. Snapshot + event replay (f037, O(events-after-snapshot))
        3. Full event replay (original path, O(all-events))
        """
        # Phase 1 Scaling: Try materialized balance table
        try:
            from .materialized_projections import get_all_materialized_balances, get_supply_summary
            mat_balances = await get_all_materialized_balances(self.event_store.db)
            if mat_balances is not None and len(mat_balances) > 0:
                balances = []
                for mb in mat_balances:
                    if mb["liquid_balance"] != 0 or mb["staked_balance"] != 0:
                        balances.append(BalanceProjection(
                            agent_did=mb["agent_did"],
                            liquid_balance=mb["liquid_balance"],
                            staked_balance=mb["staked_balance"],
                            last_event_timestamp=mb["last_event_timestamp"],
                            event_count=mb["event_count"],
                        ))

                # Also populate _last_supply_audit from materialized supply_summary
                supply = await get_supply_summary(self.event_store.db)
                if supply:
                    self._last_supply_audit = {
                        "tokens_issued": supply["tokens_issued"],
                        "tokens_destroyed": supply["tokens_destroyed"],
                        "tokens_fees_collected": supply["tokens_fees_collected"],
                        "transit_net": supply.get("transit_net", 0),  # §B
                        "net_supply": supply["net_supply"],
                    }
                else:
                    # Compute from materialized balances as fallback
                    total_circ = sum(mb["liquid_balance"] + mb["staked_balance"] for mb in mat_balances)
                    self._last_supply_audit = {
                        "tokens_issued": total_circ,
                        "tokens_destroyed": 0,
                        "tokens_fees_collected": 0,
                        "transit_net": 0,  # §B
                        "net_supply": total_circ,
                    }

                logger.info(f"Materialized: returned {len(balances)} agent balances (O(1))")
                return balances
        except Exception as mat_exc:
            logger.debug(f"Materialized all-balances failed, falling back to replay: {mat_exc}")

        # f037: Check for snapshot baseline
        snapshot = await self.event_store.get_latest_snapshot()

        # Single-pass: accumulate balances for all agents at once (Decimal precision)
        agent_state: Dict[str, Dict] = {}  # agent_did -> {liquid, staked, last_ts, count}

        if snapshot and snapshot.data.get("agents"):
            # Start from snapshot baseline
            snap_agents = snapshot.data["agents"]
            logger.info(f"[Snapshot] Using projection snapshot from {snapshot.timestamp} "
                        f"({len(snap_agents)} agents) — replaying only newer events")
            for sa in snap_agents:
                did = sa.get("did", "")
                if did:
                    agent_state[did] = {
                        "liquid": Decimal(str(sa.get("liquid", 0))),
                        "staked": Decimal(str(sa.get("staked", 0))),
                        "last_ts": snapshot.timestamp,
                        "count": 0
                    }
            # Only get events AFTER the snapshot
            all_events = await self.event_store.get_events_after(snapshot.timestamp)
            logger.info(f"[Snapshot] Replaying {len(all_events)} events after snapshot")
        else:
            logger.info("Calculating balances for all agents (full replay — no snapshot)")
            all_events = await self.event_store.get_all_events(limit=200000)

        # f037: Supply conservation tracking (Option 4 — self-consistent audit)
        # When snapshot exists, the snapshot total IS the baseline "issued" amount.
        # Only post-snapshot events contribute to issued/destroyed.
        snapshot_total = Decimal("0")
        if snapshot and snapshot.data.get("agents"):
            for sa in snapshot.data["agents"]:
                snapshot_total += Decimal(str(sa.get("liquid", 0))) + Decimal(str(sa.get("staked", 0)))

        supply_issued = snapshot_total      # Snapshot baseline counts as "issued"
        supply_fees_collected = Decimal("0") # Total fees deducted (TransactionFeeCollected)
        supply_slashed = Decimal("0")        # Total slashed (DisputeSlash)
        supply_minted_compensation = Decimal("0")  # Compensation minted (DisputeCompensationMinted)
        supply_bridge_locked = Decimal("0")  # SF-3: Net AVT locked for cross-frame bridge
        supply_wrapped_minted = Decimal("0") # SF-3: Net wrapped-AVT minted from other frames

        def _ensure_agent(did: str):
            if did not in agent_state:
                agent_state[did] = {
                    "liquid": Decimal("0"), "staked": Decimal("0"),
                    "last_ts": None, "count": 0
                }

        # f037: Refresh projection skip policies
        try:
            await _refresh_skip_policies()
        except Exception:
            pass

        for event in all_events:
            # f037: Skip event types flagged by emission policy
            if _should_skip_in_projection(event.event_type):
                continue

            agent_did = event.aggregate_id
            _ensure_agent(agent_did)
            state = agent_state[agent_did]
            state["count"] += 1
            state["last_ts"] = event.timestamp

            if event.event_type == "TokensIssued":
                amount = _safe_decimal(event.data.get("amount", 0))
                state["liquid"] += amount
                supply_issued += amount  # f037: track supply creation

            elif event.event_type == "TokensTransferred":
                amount = _safe_decimal(event.data.get("amount", 0))
                from_agent = event.data.get("from")
                to_agent = event.data.get("to")

                if from_agent == agent_did:
                    state["liquid"] -= amount
                if to_agent and to_agent != agent_did:
                    _ensure_agent(to_agent)
                    agent_state[to_agent]["liquid"] += amount
                    agent_state[to_agent]["last_ts"] = event.timestamp
                elif to_agent == agent_did:
                    state["liquid"] += amount

            elif event.event_type == "TokensStaked":
                amount = _safe_decimal(event.data.get("amount", 0))
                state["liquid"] -= amount
                state["staked"] += amount

            elif event.event_type == "TokensUnstaked":
                amount = _safe_decimal(event.data.get("amount", 0))
                state["liquid"] += amount
                state["staked"] -= amount

            elif event.event_type == "RewardsAutoCompounded":
                amount = _safe_decimal(event.data.get("amount", 0))
                state["liquid"] -= amount
                state["staked"] += amount

            # RewardsDistributed: skip in balance projection (already counted
            # via TokensTransferred from TEG EnhancedTransferService).
            # Event is preserved in immutable log for audit trail.
            elif event.event_type == "RewardsDistributed":
                pass

            elif event.event_type == "DisputeSlash":
                amount = _safe_decimal(event.data.get("amount", 0))
                state["liquid"] -= amount
                supply_slashed += amount  # f037: tokens destroyed

            elif event.event_type == "DisputeCompensationMinted":
                amount = _safe_decimal(event.data.get("amount", 0))
                state["liquid"] += amount
                supply_minted_compensation += amount  # f037: tokens created

            elif event.event_type == "CrossRegistryTransferCompleted":
                amount = _safe_decimal(event.data.get("amount", 0))
                from_agent = event.data.get("from")
                to_agent = event.data.get("to")
                if from_agent == agent_did:
                    state["liquid"] -= amount
                if to_agent and to_agent != agent_did:
                    _ensure_agent(to_agent)
                    agent_state[to_agent]["liquid"] += amount
                    agent_state[to_agent]["last_ts"] = event.timestamp
                elif to_agent == agent_did:
                    state["liquid"] += amount

            elif event.event_type == "BalanceCorrected":
                adj = _safe_decimal(event.data.get("adjustment", 0))
                state["liquid"] += adj
                if adj > 0:
                    supply_issued += adj  # f037: positive correction = supply creation
                else:
                    supply_slashed += abs(adj)  # f037: negative correction = supply destruction

            elif event.event_type == "TransactionFeeCollected":
                fee = _safe_decimal(event.data.get("fee_amount", 0))
                state["liquid"] -= fee
                supply_fees_collected += fee
                # f037: Credit fee collector (fees stay in circulation, just change hands)
                _ensure_agent("teg:system:fee_collector")
                agent_state["teg:system:fee_collector"]["liquid"] += fee

            # SF-3: Cross-frame bridge events
            elif event.event_type == "TokensBridgeLocked":
                amount = _safe_decimal(event.data.get("amount", 0))
                supply_bridge_locked += amount

            elif event.event_type == "TokensBridgeUnlocked":
                amount = _safe_decimal(event.data.get("amount", 0))
                supply_bridge_locked -= amount

            elif event.event_type == "WrappedTokensMinted":
                amount = _safe_decimal(event.data.get("amount", 0))
                supply_wrapped_minted += amount

            elif event.event_type == "WrappedTokensBurned":
                amount = _safe_decimal(event.data.get("amount", 0))
                supply_wrapped_minted -= amount

        # Build projection objects
        balances = []
        for did, state in agent_state.items():
            if state["liquid"] != 0 or state["staked"] != 0 or state["count"] > 0:
                balances.append(BalanceProjection(
                    agent_did=did,
                    liquid_balance=state["liquid"],
                    staked_balance=state["staked"],
                    last_event_timestamp=state["last_ts"],
                    event_count=state["count"]
                ))
        
        logger.info(f"Calculated balances for {len(balances)} agents (single-pass)")

        # f037: Attach supply conservation metadata to the result
        # Stored as class attribute so the router can access it
        self._last_supply_audit = {
            "tokens_issued": str(supply_issued + supply_minted_compensation),
            "tokens_destroyed": str(supply_slashed),
            "tokens_fees_collected": str(supply_fees_collected),
            "bridge_locked": str(supply_bridge_locked),
            "wrapped_foreign": str(supply_wrapped_minted),
            "net_supply": str(supply_issued + supply_minted_compensation - supply_slashed),
        }

        return balances
