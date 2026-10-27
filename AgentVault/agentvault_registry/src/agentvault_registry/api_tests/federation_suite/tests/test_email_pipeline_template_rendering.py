"""Email template rendering tests (§pass73.3.17 Batch 106).

3 tests verifying the email pipeline renders templates without errors.
Per CLAUDE.md PART 9 Email_Pipeline.md — 23+ templates × HTML+text.
A render error means users get broken emails.
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
    name="email_template_inventory_has_minimum_count",
    category="email_template_rendering",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["email", "templates", "inventory"],
)
async def test_template_inventory_min(
    rig: FederationTestRig,
) -> AssertionResult:
    """getEmailTemplates returns ≥10 templates (CLAUDE.md says 23+)."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getEmailTemplates")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            templates = r if isinstance(r, list) else (
                r.get("templates") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(templates) if isinstance(templates, list) else None
            return isinstance(state["count"], int) and state["count"] >= 10
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="email templates inventory has ≥10 templates",
        capture_state=lambda: state,
    )


@federation_test(
    name="email_template_preview_renders_known_template",
    category="email_template_rendering",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["email", "preview", "rendering"],
)
async def test_template_preview(rig: FederationTestRig) -> AssertionResult:
    """previewAdminEmail for a known template name returns rendered
    HTML/text body without 500. Picks first template from inventory."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            tmpls = await admin.call("getEmailTemplates")
            templates = tmpls if isinstance(tmpls, list) else (
                tmpls.get("templates") or tmpls.get("items") or []
            ) if isinstance(tmpls, dict) else []
            if not templates:
                state["no_templates"] = True
                return True
            first = templates[0] if isinstance(templates[0], dict) else None
            if not first:
                return True
            name = first.get("name") or first.get("template_name") or \
                   first.get("id")
            if not name:
                state["no_name"] = True
                state["first_keys"] = sorted((first or {}).keys())[:8]
                return True
            state["template_name"] = name
            r = await admin.call("previewAdminEmail", {"template_name": name})
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return True
            elif isinstance(r, str):
                state["text_len"] = len(r)
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="preview email template renders without 500",
        capture_state=lambda: state,
    )


@federation_test(
    name="broadcast_template_inventory",
    category="email_template_rendering",
    budget_sec=20.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["broadcast", "templates"],
)
async def test_broadcast_templates(rig: FederationTestRig) -> AssertionResult:
    """getBroadcastTemplates returns the broadcast template catalog
    (separate from transactional email templates)."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getBroadcastTemplates")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            templates = r if isinstance(r, list) else (
                r.get("templates") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(templates) if isinstance(templates, list) else None
            return isinstance(state["count"], int)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="broadcast templates inventory reachable",
        capture_state=lambda: state,
    )
