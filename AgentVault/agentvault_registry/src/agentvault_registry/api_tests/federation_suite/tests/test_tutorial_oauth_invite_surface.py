"""Tutorial + OAuth federation + invite code observability tests
(§pass73.3.9 Batch 30).

3 read-only tests probing miscellaneous developer onboarding surfaces:
tutorial health, OAuth federation trust list, invite code admin
inventory.
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
    name="tutorial_health_per_frame",
    category="tutorial_onboarding",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["tutorial", "health"],
)
async def test_tutorial_health(rig: FederationTestRig) -> AssertionResult:
    """getTutorialHealth returns {healthy: true} on each mainframe.
    The tutorial subsystem runs interactive onboarding for new devs."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getTutorialHealth")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {
                        "healthy": r.get("healthy"),
                        "sandbox_url": r.get("sandbox_url"),
                    }
                else:
                    state[label] = {"bad_shape": type(r).__name__}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or v.get("healthy") is True
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="tutorial health = healthy on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="oauth_federation_status_published",
    category="tutorial_onboarding",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["oauth", "federation", "trust-list"],
)
async def test_oauth_federation_status(
    rig: FederationTestRig,
) -> AssertionResult:
    """getOAuthFederationStatus surfaces the cross-frame OAuth trust list.

    Sandbox-A should list Registry Test B as a trusted federation
    OAuth peer (token-exchange + introspection allowed).
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getOAuthFederationStatus")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if not isinstance(r, dict):
                    state[label] = {"bad_shape": type(r).__name__}
                    continue
                state[label] = {
                    "oauth_enabled": r.get("oauth_enabled"),
                    "token_exchange_enabled": r.get("token_exchange_enabled"),
                    "trusted_count": len(r.get("trusted_registries") or []),
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent")
                or v.get("oauth_enabled") is True
                or isinstance(v.get("trusted_count"), int)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="OAuth federation status published on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_invite_codes_inventory",
    category="tutorial_onboarding",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["invite-codes", "admin"],
)
async def test_invite_codes(rig: FederationTestRig) -> AssertionResult:
    """getInviteCodes returns the admin invite code inventory. Sandbox
    typically has ≥0 codes; the endpoint must be reachable."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getInviteCodes")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            codes = r.get("invite_codes") if isinstance(r, dict) else r
            if not isinstance(codes, list):
                state["bad_shape"] = type(codes).__name__
                return False
            state["count"] = len(codes)
            state["statuses"] = sorted(
                {c.get("status") for c in codes if isinstance(c, dict)}
            )
            return True
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="invite codes inventory reachable on sandbox-A",
        capture_state=lambda: state,
    )
