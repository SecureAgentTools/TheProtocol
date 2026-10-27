"""RFC 7807 error contract tests (§pass73.3.17 Batch 79).

3 tests verifying error responses adhere to RFC 7807 (Problem Details
for HTTP APIs). Per CLAUDE.md PART 5 §pass56: "All error responses are
RFC 7807 dual-emit: legacy `detail` field present, PLUS new
`type`/`title`/`status`/`instance` fields."

Triggers known error responses and asserts each has BOTH legacy + RFC 7807
fields. Regression detector for the error envelope post §pass56.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


def _extract_error_body(r):
    """adminRequest wraps response in {status_code, response, ok} — drill in."""
    if not isinstance(r, dict):
        return None
    resp = r.get("response")
    if isinstance(resp, dict):
        return resp
    return None


@federation_test(
    name="error_404_has_rfc7807_fields",
    category="error_contract_rfc7807",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["rfc7807", "errors", "404"],
)
async def test_rfc7807_404(rig: FederationTestRig) -> AssertionResult:
    """GET to a definitely-not-found admin path returns 404 with both
    legacy `detail` AND RFC 7807 fields (`type`, `title`, `status`)."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {
                    "method": "GET",
                    "endpoint": "/api/v1/admin/this-path-does-not-exist-zzz",
                },
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            body = _extract_error_body(r) or {}
            state["body_keys"] = sorted(body.keys())[:12]
            has_legacy = bool(body.get("detail"))
            has_type = bool(body.get("type"))
            has_title = bool(body.get("title"))
            has_status = body.get("status") is not None
            state["dual_fields"] = {
                "detail": has_legacy, "type": has_type,
                "title": has_title, "status": has_status,
            }
            return has_legacy and has_type and has_title and has_status
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="404 response has RFC 7807 fields (type/title/status) + legacy detail",
        capture_state=lambda: state,
    )


@federation_test(
    name="error_422_has_rfc7807_validation_details",
    category="error_contract_rfc7807",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["rfc7807", "errors", "422", "validation"],
)
async def test_rfc7807_422(rig: FederationTestRig) -> AssertionResult:
    """POST with missing required fields returns 422 with RFC 7807 +
    validation detail array."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {
                    "method": "POST",
                    "endpoint": "/api/v1/operator-applications",
                    "body": {},  # Missing all required fields → 422
                },
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            body = _extract_error_body(r) or {}
            state["body_keys"] = sorted(body.keys())[:12]
            # 422 is validation error — must have BOTH RFC 7807 + detail
            return (
                state["status_code"] == 422
                and bool(body.get("detail"))
                and bool(body.get("type"))
                and bool(body.get("title"))
            )
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="422 validation error has RFC 7807 + detail array",
        capture_state=lambda: state,
    )


@federation_test(
    name="error_401_has_rfc7807_fields",
    category="error_contract_rfc7807",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["rfc7807", "errors", "401"],
)
async def test_rfc7807_401(rig: FederationTestRig) -> AssertionResult:
    """401 unauthorized response also follows RFC 7807."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {
                    "method": "GET",
                    "endpoint": "/api/v1/admin/dashboard",
                    "developer_jwt": "garbage.not.real",
                },
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            body = _extract_error_body(r) or {}
            state["body_keys"] = sorted(body.keys())[:12]
            return (
                state["status_code"] == 401
                and bool(body.get("type"))
                and bool(body.get("title"))
            )
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="401 unauthorized response has RFC 7807 fields",
        capture_state=lambda: state,
    )
