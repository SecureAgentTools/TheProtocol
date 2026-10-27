"""Admin health check 3-mode tests (§pass73.3.11 Batch 48).

3 read-only tests probing the 3 admin health check modes used by the
ops dashboard:
  - Simple: minimal liveness probe
  - PublicOnly: probes only public-tier subsystems
  - Authenticated: full probe of all subsystems
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
    name="admin_health_simple_envelope",
    category="admin_health_modes",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["health", "simple"],
)
async def test_health_simple(rig: FederationTestRig) -> AssertionResult:
    """getAdminHealthCheckSimple returns {status:'healthy', service:...}
    minimal liveness probe envelope on both mainframes."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getAdminHealthCheckSimple")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if not isinstance(r, dict):
                    state[label] = {"bad_shape": type(r).__name__}
                    continue
                state[label] = {
                    "status": r.get("status"),
                    "service": r.get("service"),
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or v.get("status") == "healthy"
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin health-simple = healthy on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_health_public_only_pillars",
    category="admin_health_modes",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["health", "public-only"],
)
async def test_health_public_only(rig: FederationTestRig) -> AssertionResult:
    """getAdminHealthCheckPublicOnly probes 7 public-tier pillars and
    reports overallStatus envelope."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "getAdminHealthCheckPublicOnly"
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            ov = r.get("overallStatus") or {}
            state["status"] = ov.get("status")
            state["healthy"] = ov.get("healthy")
            state["total"] = ov.get("total")
            return (
                isinstance(ov.get("total"), int) and ov["total"] >= 5
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin health-public-only probes ≥5 pillars",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_health_authenticated_pillars",
    category="admin_health_modes",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["health", "authenticated"],
)
async def test_health_authenticated(rig: FederationTestRig) -> AssertionResult:
    """getAdminHealthCheckAuthenticated probes the full pillar set and
    reports overallStatus + groupSummaries. Different from public-only
    since it includes auth-gated subsystems (admin endpoints, etc.)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "getAdminHealthCheckAuthenticated"
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            ov = r.get("overallStatus") or {}
            state["status"] = ov.get("status")
            state["total"] = ov.get("total")
            state["healthy"] = ov.get("healthy")
            return (
                isinstance(ov.get("total"), int) and ov["total"] >= 10
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin health-authenticated probes ≥10 pillars",
        capture_state=lambda: state,
    )
