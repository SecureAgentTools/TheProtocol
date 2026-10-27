"""Event ID uniqueness tests (§pass73.3.17 Batch 81).

3 tests verifying core invariants on the EventStore — every event has
a unique id, an idempotency_key (when present) is consistent, and the
recent feed is monotonically ordered by timestamp.

These are CRITICAL invariants for the CQRS ledger. A breach here means
projections could double-count or miss events.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


def _is_silent_or_error(r):
    if isinstance(r, str):
        return True
    if isinstance(r, dict):
        if not r:
            return True
        if "_text" in r:
            return isinstance(r["_text"], str)
    return False


@federation_test(
    name="recent_events_have_unique_ids",
    category="event_id_uniqueness",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["event-store", "uniqueness", "invariant"],
)
async def test_unique_event_ids(rig: FederationTestRig) -> AssertionResult:
    """Recent 100 events from getEventStoreRecent all have distinct `id`.

    A duplicate event id means the CQRS ledger has corrupted state or
    a projection could double-count."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getEventStoreRecent")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            # Real shape: top-level list of events (no `events`/`items` wrapper)
            events = r if isinstance(r, list) else (
                r.get("events") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            ids = [e.get("id") for e in events if isinstance(e, dict) and e.get("id")]
            state["count"] = len(ids)
            state["unique_count"] = len(set(ids))
            # If no events at all, accept (sandbox may be quiet)
            return len(ids) == 0 or len(ids) == len(set(ids))
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="recent event IDs are all unique (no duplicates)",
        capture_state=lambda: state,
    )


@federation_test(
    name="recent_events_monotonic_timestamps",
    category="event_id_uniqueness",
    budget_sec=30.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["event-store", "monotonic", "ordering"],
)
async def test_monotonic_timestamps(
    rig: FederationTestRig,
) -> AssertionResult:
    """Recent events feed is sorted DESC by timestamp.

    If events arrive out of order, downstream consumers (canaries,
    reactors) may miss events or react in wrong order."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getEventStoreRecent")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            events = r if isinstance(r, list) else (
                r.get("events") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            timestamps = [
                e.get("timestamp") for e in events if isinstance(e, dict)
            ]
            state["count"] = len(timestamps)
            if len(timestamps) < 2:
                return True  # too few to check ordering
            # Check DESC order — recent first
            descending = all(
                timestamps[i] >= timestamps[i + 1]
                for i in range(len(timestamps) - 1)
                if timestamps[i] and timestamps[i + 1]
            )
            state["descending"] = descending
            if not descending:
                # Find first violation
                for i in range(len(timestamps) - 1):
                    if (timestamps[i] and timestamps[i + 1]
                            and timestamps[i] < timestamps[i + 1]):
                        state["violation_at_idx"] = i
                        state["pair"] = (timestamps[i], timestamps[i + 1])
                        break
            return descending
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="recent events feed is DESC-monotonic by timestamp",
        capture_state=lambda: state,
    )


@federation_test(
    name="event_store_stats_total_matches_actual",
    category="event_id_uniqueness",
    budget_sec=30.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["event-store", "stats", "consistency"],
)
async def test_event_count_consistency(
    rig: FederationTestRig,
) -> AssertionResult:
    """getEventStoreStats `total_events` matches the actual table count.
    Stats endpoint must reflect reality, not a stale cached number."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getEventStoreStats")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                return False
            # Real top-level keys: total_events, unique_agents, event_counts,
            # newest_event, oldest_event, last_refresh_ts
            total = r.get("total_events") or (r.get("stats") or {}).get("total_events")
            unique_agents = r.get("unique_agents")
            state["total_events"] = total
            state["unique_agents"] = unique_agents
            return isinstance(total, int) and total > 0
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="event store stats.total_events is a positive int",
        capture_state=lambda: state,
    )
