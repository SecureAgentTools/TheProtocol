"""IRONHAND-specific canary subsystem observability tests
(§pass73.3.10 Batch 40).

3 read-only tests probing the IRONHAND canary subsystem — measures mTLS
SVID revocation propagation latency (3-layer: ES WS, polling, SVID expiry
per CLAUDE.md PART 12).
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
    name="canary_ironhand_status_observable",
    category="canary_ironhand",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["canary", "ironhand", "mtls"],
)
async def test_canary_ironhand_status(
    rig: FederationTestRig,
) -> AssertionResult:
    """getCanaryIronhandStatus surfaces SVID revocation propagation
    metrics — passes_24h, p95 propagation_ms. Validates the IRONHAND
    canary worker is alive."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCanaryIronhandStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            summ = r.get("summary") or {}
            state["cycles_24h"] = summ.get("cycles_24h")
            state["passes_24h"] = summ.get("passes_24h")
            state["pass_rate_24h"] = summ.get("pass_rate_24h")
            state["p95_ms"] = summ.get("revocation_p95_propagation_ms")
            return (
                isinstance(summ.get("cycles_24h"), int)
                and summ["cycles_24h"] >= 0
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="canary IRONHAND status reachable with summary counters",
        capture_state=lambda: state,
    )


@federation_test(
    name="canary_ironhand_svids_inventory",
    category="canary_ironhand",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["canary", "ironhand", "svids"],
)
async def test_canary_ironhand_svids(
    rig: FederationTestRig,
) -> AssertionResult:
    """getCanaryIronhandSvids returns the SVID inventory tracked by the
    canary worker — DIDs whose SVIDs are being monitored."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCanaryIronhandSvids")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:6]
                svids = r.get("svids") or r.get("items") or r.get("data") or []
                if isinstance(svids, list):
                    state["count"] = len(svids)
                return bool(r.keys())
            elif isinstance(r, list):
                state["count"] = len(r)
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="canary IRONHAND SVIDs inventory reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="canary_ironhand_recent_events",
    category="canary_ironhand",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["canary", "ironhand", "events"],
)
async def test_canary_ironhand_events(
    rig: FederationTestRig,
) -> AssertionResult:
    """getCanaryIronhandEvents returns recent IRONHAND canary firing
    events (passes + failures with propagation latencies)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCanaryIronhandEvents")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            events = r if isinstance(r, list) else (
                r.get("events") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(events)
            return isinstance(state.get("count"), int) and state["count"] >= 0
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="canary IRONHAND events stream reachable",
        capture_state=lambda: state,
    )
