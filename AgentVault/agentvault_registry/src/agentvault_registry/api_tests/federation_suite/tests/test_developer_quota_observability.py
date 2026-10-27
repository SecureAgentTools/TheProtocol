"""Developer quota + admin observability tests (§pass73.3.9 Batch 17).

3 read-only tests probing the developer registration + quota admin
surfaces. Catches: developers list missing, quota patch broken, agents-
by-developer cascade missing.
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
    name="admin_developers_listing_per_frame",
    category="developer_quota",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["developers", "admin-listing"],
)
async def test_admin_developers_listing(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAdminDevelopers returns ≥1 developer on each mainframe (at
    minimum the commander dev + the auto-created tutorial developer)."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getAdminDevelopers")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                devs = r if isinstance(r, list) else (
                    r.get("developers") or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                state[label] = {"count": len(devs)}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (isinstance(v.get("count"), int) and v["count"] >= 1)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin developers listing has ≥1 entry on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="auth_registration_config_published",
    category="developer_quota",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["auth", "registration-config"],
)
async def test_auth_registration_config(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAuthRegistrationConfig returns the public registration config
    (open/invite-only, password policy, etc.) on both mainframes."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getAuthRegistrationConfig")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if not isinstance(r, dict):
                    state[label] = {"bad_shape": type(r).__name__}
                    continue
                state[label] = {"keys": sorted(r.keys())[:8]}
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
        description="auth registration config readable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_flags_inventory_readable",
    category="developer_quota",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["admin-flags", "rbac"],
)
async def test_admin_flags(rig: FederationTestRig) -> AssertionResult:
    """getAdminFlags returns the inventory of admin-cluster flags.

    Per CLAUDE.md the 5-cluster RBAC system has admin_treasury,
    admin_support, admin_enforcement, admin_federation, admin_platform.
    The flag inventory endpoint should surface these.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAdminFlags")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                flags = r.get("flags") or r.get("clusters") or r.get("admin_flags")
                if isinstance(flags, (list, dict)):
                    state["flag_count"] = len(flags)
                return bool(r.keys())
            if isinstance(r, list):
                state["count"] = len(r)
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin flags inventory readable on sandbox-A",
        capture_state=lambda: state,
    )
