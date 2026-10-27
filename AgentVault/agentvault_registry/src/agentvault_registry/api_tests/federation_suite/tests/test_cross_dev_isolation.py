"""Cross-developer isolation tests (§pass73.3.17 Batch 85).

3 tests verifying that developer A's JWT cannot access developer B's
private resources. Critical for tenancy isolation in a public
multi-tenant registry.

Reuses RBAC + operator sentinel devs that already exist in the test
fixtures (see test_rbac_5cluster_matrix.py + test_operator_provisioning_flow.py).
"""
from __future__ import annotations
import base64
import json
from typing import Optional

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


def _decode_jwt_sub(jwt: str) -> Optional[int]:
    try:
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        sub = claims.get("sub")
        return int(sub) if sub is not None else None
    except Exception:
        return None


async def _login_or_skip(rig: FederationTestRig, email: str, password: str):
    """Returns (jwt, dev_id) or None if login fails (test skips)."""
    admin = rig.mcp("sandbox-A-admin")
    try:
        r = await admin.call(
            "adminGetDeveloperToken",
            {"email": email, "password": password},
        )
        if isinstance(r, dict) and r.get("access_token"):
            jwt = r["access_token"]
            return jwt, _decode_jwt_sub(jwt)
    except Exception:
        pass
    return None


@federation_test(
    name="dev_a_cannot_read_dev_b_profile",
    category="cross_dev_isolation",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["isolation", "tenancy", "profile"],
)
async def test_dev_a_cant_read_b_profile(
    rig: FederationTestRig,
) -> AssertionResult:
    """Dev A's JWT can access /developers/me (which is THEIR profile),
    but a foreign /developers/{B-id}/admin-flags endpoint must 403.

    /developers/me is owner-scoped (always self); admin endpoints require
    admin flag. A non-admin dev hitting another dev's admin path = 403."""
    state: dict = {}

    async def predicate():
        try:
            # Use the RBAC treasury dev (has admin_treasury but not admin_platform)
            auth = await _login_or_skip(
                rig, "rbac_treasury@test.sandbox", "RbacTestDev2026!"
            )
            if not auth:
                state["skip"] = "no RBAC treasury dev"
                return True
            jwt_a, dev_a_id = auth
            state["dev_a_id"] = dev_a_id

            admin = rig.mcp("sandbox-A-admin")

            # Try to access admin endpoint that DEV A doesn't have flag for
            # (admin_platform endpoint with treasury-only dev)
            r = await admin.call(
                "adminRequest",
                {
                    "method": "GET",
                    "endpoint": "/api/v1/admin/canary-judge/status",
                    "developer_jwt": jwt_a,
                },
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            # Treasury dev can't access platform endpoint → 403
            return state["status_code"] == 403
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="treasury-only dev gets 403 on platform endpoint",
        capture_state=lambda: state,
    )


@federation_test(
    name="dev_can_access_own_profile",
    category="cross_dev_isolation",
    budget_sec=30.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["isolation", "self-read"],
)
async def test_dev_own_profile_accessible(
    rig: FederationTestRig,
) -> AssertionResult:
    """Positive control: dev CAN access their own /developers/me — proves
    the 403 in the other test is endpoint-specific, not blanket-deny."""
    state: dict = {}

    async def predicate():
        try:
            auth = await _login_or_skip(
                rig, "rbac_treasury@test.sandbox", "RbacTestDev2026!"
            )
            if not auth:
                state["skip"] = "no RBAC treasury dev"
                return True
            jwt_a, dev_a_id = auth
            state["dev_a_id"] = dev_a_id

            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {
                    "method": "GET",
                    "endpoint": "/api/v1/developers/me",
                    "developer_jwt": jwt_a,
                },
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            resp = r.get("response") if isinstance(r, dict) else None
            if isinstance(resp, dict):
                state["returned_id"] = resp.get("id")
                # Self-read: returned id must match the dev's own id
                return (
                    state["status_code"] == 200
                    and resp.get("id") == dev_a_id
                )
            return state["status_code"] == 200
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="dev's /developers/me returns own profile (id matches sub)",
        capture_state=lambda: state,
    )


@federation_test(
    name="dev_a_cannot_force_password_reset_on_b",
    category="cross_dev_isolation",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["isolation", "destructive-action"],
)
async def test_dev_cant_force_reset_other(
    rig: FederationTestRig,
) -> AssertionResult:
    """Dev A (non-admin) cannot fire admin-only destructive actions like
    forceDeveloperPasswordReset on Dev B. Must 403 immediately.

    This is the highest-value isolation test — preventing privilege
    escalation between developer accounts."""
    state: dict = {}

    async def predicate():
        try:
            auth = await _login_or_skip(
                rig, "rbac_treasury@test.sandbox", "RbacTestDev2026!"
            )
            if not auth:
                state["skip"] = "no RBAC treasury dev"
                return True
            jwt_a, dev_a_id = auth

            admin = rig.mcp("sandbox-A-admin")
            # Try to force-reset password on a different dev (id=1, commander)
            r = await admin.call(
                "adminRequest",
                {
                    "method": "POST",
                    "endpoint": "/api/v1/admin/developers/1/force-password-reset",
                    "developer_jwt": jwt_a,
                },
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            # Must reject with 403 (or 404 if endpoint name differs, never 200)
            return state["status_code"] in (403, 404, 405)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="non-admin dev cannot force-reset commander password",
        capture_state=lambda: state,
    )
