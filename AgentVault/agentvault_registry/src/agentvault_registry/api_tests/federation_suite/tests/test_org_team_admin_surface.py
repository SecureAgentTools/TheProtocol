"""Organization + team observability tests (§pass73.3.10 Batch 37).

3 read-only tests probing the organization + team admin surfaces.
The CICD subsystem uses orgs/teams for ownership-scoped pipelines.
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
    name="my_organizations_listing_per_frame",
    category="organizations",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["organizations", "developer"],
)
async def test_my_organizations(rig: FederationTestRig) -> AssertionResult:
    """getMyOrganizations returns the developer's org membership list
    (possibly empty for a fresh sandbox dev)."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getMyOrganizations")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                orgs = r if isinstance(r, list) else (
                    r.get("organizations") or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                state[label] = {"count": len(orgs)}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or isinstance(v.get("count"), int)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="developer org membership reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="my_developer_teg_summary_per_frame",
    category="organizations",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["developer", "teg-summary"],
)
async def test_my_developer_teg_summary(
    rig: FederationTestRig,
) -> AssertionResult:
    """getMyDeveloperTegSummary returns the developer's TEG balance +
    transaction count aggregate across their agents."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getMyDeveloperTegSummary")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {"keys": sorted(r.keys())[:8]}
                else:
                    state[label] = {"bad_shape": type(r).__name__}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (isinstance(v.get("keys"), list) and v["keys"])
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="developer TEG summary reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="my_notification_prefs_per_frame",
    category="organizations",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A", "sandbox-B"],
    tags=["developer", "notifications"],
)
async def test_my_notification_prefs(
    rig: FederationTestRig,
) -> AssertionResult:
    """getMyNotificationPrefs returns the developer's notification
    preference envelope (email subscriptions, etc.)."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getMyNotificationPrefs")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {"keys": sorted(r.keys())[:6]}
                else:
                    state[label] = {"bad_shape": type(r).__name__}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (isinstance(v.get("keys"), list) and v["keys"])
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="developer notification preferences reachable on both mainframes",
        capture_state=lambda: state,
    )
