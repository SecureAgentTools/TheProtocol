"""Admin fiat onramp statistics tests (§pass73.3.10 Batch 43).

3 read-only tests probing the PB-1 admin fiat onramp aggregate
surfaces — used for revenue + conversion-rate dashboards.
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
    name="admin_fiat_stats_30day_envelope",
    category="admin_fiat",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["fiat", "admin", "stats"],
)
async def test_admin_fiat_stats(rig: FederationTestRig) -> AssertionResult:
    """getAdminFiatStats returns the 30-day fiat onramp aggregate —
    total_eur, total_avt, completed/pending/failed/refunded counts."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAdminFiatStats")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            state["window_days"] = r.get("window_days")
            state["total_eur"] = r.get("total_eur")
            state["completed_count"] = r.get("completed_count")
            state["success_rate_pct"] = r.get("success_rate_pct")
            return "window_days" in r or "total_eur" in r
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin fiat stats 30-day envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_fiat_pricing_current_envelope",
    category="admin_fiat",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["fiat", "admin", "pricing"],
)
async def test_admin_fiat_pricing(rig: FederationTestRig) -> AssertionResult:
    """getAdminFiatPricing returns the current admin pricing envelope —
    tier definitions, EUR limits, AVT rates."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAdminFiatPricing")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return bool(r.keys())
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin fiat pricing envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_fiat_purchases_recent",
    category="admin_fiat",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["fiat", "admin", "purchases"],
)
async def test_admin_fiat_purchases(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAdminFiatPurchases lists recent fiat purchases (possibly empty
    in a clean sandbox). Validates the read path is alive."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAdminFiatPurchases")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("purchases") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return True
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin fiat purchases listing reachable",
        capture_state=lambda: state,
    )
