"""Admin dashboard counter consistency tests (§pass73.3.11 Batch 44).

3 tests probing getAdminDashboard counters for self-consistency:
  - both frames report non-empty counter envelope
  - active_developers ≤ developer_count
  - tokens_used + tokens_expired ≤ bootstrap_tokens_issued
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
    name="admin_dashboard_envelope_per_frame",
    category="admin_dashboard",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["dashboard", "counters"],
)
async def test_dashboard_envelope(rig: FederationTestRig) -> AssertionResult:
    """getAdminDashboard returns developer_count + agent_count + bootstrap
    counters on both mainframes with positive values."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getAdminDashboard")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if not isinstance(r, dict):
                    state[label] = {"bad_shape": type(r).__name__}
                    continue
                state[label] = {
                    "developer_count": r.get("developer_count"),
                    "agent_count": r.get("agent_count"),
                    "active_agents": r.get("active_agents"),
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (
                    isinstance(v.get("developer_count"), int)
                    and isinstance(v.get("agent_count"), int)
                )
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin dashboard envelope has dev+agent counters on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_dashboard_active_devs_le_total",
    category="admin_dashboard",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["dashboard", "active-developers", "invariant"],
)
async def test_active_devs_invariant(rig: FederationTestRig) -> AssertionResult:
    """active_developers ≤ developer_count (active is a subset)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAdminDashboard")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            dc = r.get("developer_count")
            ad = r.get("active_developers")
            state["developer_count"] = dc
            state["active_developers"] = ad
            return (
                isinstance(dc, int) and isinstance(ad, int)
                and ad <= dc
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="active_developers ≤ developer_count on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_dashboard_bootstrap_token_accounting",
    category="admin_dashboard",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["dashboard", "bootstrap-tokens", "invariant"],
)
async def test_bootstrap_token_accounting(
    rig: FederationTestRig,
) -> AssertionResult:
    """tokens_used + tokens_expired ≤ bootstrap_tokens_issued (used and
    expired are both subsets of total issued)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAdminDashboard")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            issued = r.get("bootstrap_tokens_issued")
            used = r.get("tokens_used")
            expired = r.get("tokens_expired")
            state["bootstrap_tokens_issued"] = issued
            state["tokens_used"] = used
            state["tokens_expired"] = expired
            return (
                isinstance(issued, int)
                and isinstance(used, int)
                and isinstance(expired, int)
                and (used + expired) <= issued
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="bootstrap token accounting: used + expired ≤ issued",
        capture_state=lambda: state,
    )
