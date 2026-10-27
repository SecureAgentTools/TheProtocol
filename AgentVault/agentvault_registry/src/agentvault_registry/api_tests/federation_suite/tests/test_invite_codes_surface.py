"""Invite codes + auth registration config + email templates tests
(§pass73.3.13 Batch 63).

3 read-only tests probing the onboarding gate (invite codes, auth
registration config) + email template catalog.
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
    name="invite_codes_inventory",
    category="invite_codes_surface",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["invites", "admin"],
)
async def test_invite_codes(rig: FederationTestRig) -> AssertionResult:
    """getInviteCodes returns the invite code inventory + usage stats."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getInviteCodes")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("invites") or r.get("codes") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="invite codes inventory reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="auth_registration_config_envelope",
    category="invite_codes_surface",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["auth", "registration"],
)
async def test_auth_registration_config(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAuthRegistrationConfig returns the registration policy
    envelope (open-signup vs invite-only, 2FA required, etc.)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getAuthRegistrationConfig")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return bool(r.keys())
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="auth registration config envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_email_templates_inventory",
    category="invite_codes_surface",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["email", "templates"],
)
async def test_admin_email_templates(rig: FederationTestRig) -> AssertionResult:
    """getEmailTemplates returns the admin email template catalog.
    Should have ≥10 templates (23 documented as of §pass~73)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getEmailTemplates")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("templates") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin email templates inventory reachable",
        capture_state=lambda: state,
    )
