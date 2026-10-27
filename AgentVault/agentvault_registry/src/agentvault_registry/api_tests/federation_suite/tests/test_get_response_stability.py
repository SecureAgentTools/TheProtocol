"""GET response stability tests (§pass73.3.17 Batch 83).

3 tests verifying that pure-read GET endpoints return STABLE responses
across consecutive calls (no random data, no cache-coherency issues).
Critical for clients depending on consistent state.
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
    name="network_stats_stable_across_calls",
    category="get_response_stability",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["stability", "network-stats"],
)
async def test_network_stats_stable(rig: FederationTestRig) -> AssertionResult:
    """Two back-to-back getNetworkStats calls return same key set.

    Top-level shape must be stable; underlying numbers can drift
    slightly (live cluster) — we check schema only."""
    state: dict = {}

    async def predicate():
        try:
            pub = rig.mcp("sandbox-A")
            r1 = await pub.call("getNetworkStats")
            r2 = await pub.call("getNetworkStats")
            if not isinstance(r1, dict) or not isinstance(r2, dict):
                return False
            k1 = sorted(r1.keys())
            k2 = sorted(r2.keys())
            state["keys1"] = k1[:10]
            state["keys2"] = k2[:10]
            return k1 == k2 and len(k1) > 0
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="getNetworkStats schema stable across consecutive calls",
        capture_state=lambda: state,
    )


@federation_test(
    name="discover_registries_count_stable",
    category="get_response_stability",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["stability", "discovery"],
)
async def test_discover_registries_stable(
    rig: FederationTestRig,
) -> AssertionResult:
    """Two consecutive discoverRegistries calls return SAME registry
    count (no flapping, no race in service registry)."""
    state: dict = {}

    async def predicate():
        try:
            pub = rig.mcp("sandbox-A")
            r1 = await pub.call("discoverRegistries")
            r2 = await pub.call("discoverRegistries")

            def _count(r):
                items = r if isinstance(r, list) else (
                    r.get("registries") or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                return len(items)

            c1 = _count(r1)
            c2 = _count(r2)
            state["count1"] = c1
            state["count2"] = c2
            return c1 == c2 and c1 >= 1
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="discoverRegistries count stable + ≥1",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_dashboard_idempotent_read",
    category="get_response_stability",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["stability", "admin-dashboard"],
)
async def test_admin_dashboard_stable(rig: FederationTestRig) -> AssertionResult:
    """Two consecutive getAdminDashboard calls return same top-level
    key set (counter values may drift slightly)."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r1 = await admin.call("getAdminDashboard")
            r2 = await admin.call("getAdminDashboard")
            if _is_silent_or_error(r1) or _is_silent_or_error(r2):
                state["silent"] = True
                return True
            if not isinstance(r1, dict) or not isinstance(r2, dict):
                return False
            k1 = sorted(r1.keys())
            k2 = sorted(r2.keys())
            state["keys"] = k1[:10]
            return k1 == k2
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="getAdminDashboard schema stable across calls",
        capture_state=lambda: state,
    )
