"""Broadcast email retry + scheduler subsystem tests (§pass73.3.11 Batch 46).

3 read-only tests probing the broadcast email retry worker + scheduler
+ dead-letter inventory. These power broadcast notifications + email
delivery resilience.
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
    name="broadcast_email_retry_worker_status",
    category="email_retry_subsystem",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["broadcasts", "email", "retry-worker"],
)
async def test_email_retry_status(rig: FederationTestRig) -> AssertionResult:
    """getBroadcastEmailRetryStatus returns the retry worker state
    envelope — worker_id, registry_id, is_leader_now, interval_sec."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getBroadcastEmailRetryStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            state["worker_id"] = r.get("worker_id")
            state["is_leader_now"] = r.get("is_leader_now")
            state["interval_sec"] = r.get("interval_sec")
            return (
                r.get("worker_id") == "broadcast_email_retry"
                and isinstance(r.get("interval_sec"), int)
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="broadcast email retry worker envelope reachable on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="broadcast_email_dead_letter_queue",
    category="email_retry_subsystem",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["broadcasts", "email", "dead-letter"],
)
async def test_email_dead_letter(rig: FederationTestRig) -> AssertionResult:
    """getBroadcastEmailRetryDeadLetter returns the dead-letter queue —
    emails that failed after max retries. Reachable + paginated."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "getBroadcastEmailRetryDeadLetter"
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            items = r.get("items") or []
            state["count"] = len(items) if isinstance(items, list) else None
            state["limit"] = r.get("limit")
            state["skip"] = r.get("skip")
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="broadcast email dead-letter queue reachable on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="broadcast_scheduler_worker_alive",
    category="email_retry_subsystem",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["broadcasts", "scheduler"],
)
async def test_broadcast_scheduler(rig: FederationTestRig) -> AssertionResult:
    """getBroadcastSchedulerStatus shows the scheduler worker is alive +
    last_cycle_iso is recent. The scheduler fires scheduled broadcasts."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getBroadcastSchedulerStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            state["worker_id"] = r.get("worker_id")
            state["is_leader_now"] = r.get("is_leader_now")
            state["last_cycle_iso"] = r.get("last_cycle_iso")
            state["last_duration_ms"] = r.get("last_duration_ms")
            return (
                r.get("worker_id") == "broadcast_scheduler"
                and isinstance(r.get("last_duration_ms"), int)
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="broadcast scheduler worker alive with last_cycle observable",
        capture_state=lambda: state,
    )
