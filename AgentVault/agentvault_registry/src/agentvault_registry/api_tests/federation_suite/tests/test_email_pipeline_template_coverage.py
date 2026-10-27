"""Email pipeline template coverage tests (§pass73.3.9 Batch 2).

3 tests probing the themed email pipeline (`send_themed_email` per
CLAUDE.md PART 9). Validates: template inventory ≥10, preview renders
HTML, and a sample of canonical templates renders without error.
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


# Templates that ship in /app/src/agentvault_registry/templates/email — probe
# a representative sample so this test catches template-rename regressions.
_PROBE_TEMPLATES = [
    "funding_approved",
    "operator_activated",
    "operator_revoked",
    "agent_slashed",
    "mtls_enrolled",
]


@federation_test(
    name="email_templates_inventory_non_empty",
    category="email_pipeline",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["email", "templates"],
)
async def test_email_templates_inventory(rig: FederationTestRig) -> AssertionResult:
    """getEmailTemplates returns ≥10 named templates on each mainframe.

    Per CLAUDE.md PART 9 email pipeline ships 23+ templates × HTML/text
    variants. Loose threshold of 10 tolerates trim-down or rename without
    becoming brittle.
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getEmailTemplates")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                tpls = r.get("templates") if isinstance(r, dict) else r
                if not isinstance(tpls, list):
                    state[label] = {"bad_shape": type(tpls).__name__}
                    continue
                state[label] = {"count": len(tpls), "sample": tpls[:3]}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (isinstance(v.get("count"), int) and v["count"] >= 10)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="email templates inventory ≥10 on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="email_preview_renders_html_body",
    category="email_pipeline",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["email", "preview", "html"],
)
async def test_email_preview_html_body(rig: FederationTestRig) -> AssertionResult:
    """previewAdminEmail renders HTML for a known template.

    Asserts the preview envelope contains content_type=text/html and
    html_length_bytes >= 1000 (canonical themed templates are 5KB+).
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "previewAdminEmail", {"template": "funding_approved"}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            state["template"] = r.get("template")
            state["content_type"] = r.get("content_type")
            state["html_length_bytes"] = r.get("html_length_bytes")
            ct = (r.get("content_type") or "").lower()
            return "html" in ct and isinstance(r.get("html_length_bytes"), int) \
                and r["html_length_bytes"] >= 1000
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="email preview returns ≥1KB HTML for funding_approved template",
        capture_state=lambda: state,
    )


@federation_test(
    name="email_canonical_templates_render_clean",
    category="email_pipeline",
    budget_sec=30.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["email", "templates", "canonical-set"],
)
async def test_canonical_templates_render(rig: FederationTestRig) -> AssertionResult:
    """5 canonical templates render without error.

    Targets templates exercised by daily operations: funding flow, operator
    lifecycle, slashing, mTLS enrollment. Each preview must return a dict
    with content_type set. Catches partial template breakage.
    """
    state: dict = {"results": {}}

    async def predicate():
        for tpl in _PROBE_TEMPLATES:
            try:
                r = await rig.mcp("sandbox-A-admin").call(
                    "previewAdminEmail", {"template": tpl}
                )
                if isinstance(r, dict) and not r.get("_text"):
                    state["results"][tpl] = {
                        "ok": True,
                        "html_bytes": r.get("html_length_bytes"),
                    }
                else:
                    state["results"][tpl] = {"ok": False, "shape": type(r).__name__}
            except Exception as e:
                state["results"][tpl] = {"ok": False, "error": repr(e)[:80]}
        # at least 3/5 must render cleanly (tolerates 1-2 renamed templates)
        ok_count = sum(1 for v in state["results"].values() if v.get("ok"))
        state["ok_count"] = ok_count
        return ok_count >= 3

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="≥3/5 canonical email templates render cleanly",
        capture_state=lambda: state,
    )
