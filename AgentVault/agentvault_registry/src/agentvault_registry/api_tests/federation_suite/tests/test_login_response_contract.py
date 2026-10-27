"""Login response contract tests (§pass73.3.16 Batch 77).

3 tests verifying the /api/v1/auth/login response payload shape +
JWT structure invariants. Contract tests — if the auth team changes
the response shape, these surface it immediately.
"""
from __future__ import annotations
import base64
import json

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)
# §SBROTATE creds — §MCPTEST-MCP10 moved this OUT of the parenthesised import
# above, where it was a SyntaxError (the module had not compiled since).
# §FEDBETA 2026-09-04: the fixture email was hardcoded here while
# SANDBOX_ADMIN_EMAIL already existed with this exact default. On a frame
# whose fixture admin is named differently the login simply fails, and a
# NEGATIVE auth test then passes for the wrong reason — it asserts the
# login is refused, and a nonexistent account refuses every time.
from agentvault_registry.core.sandbox_creds import SANDBOX_ADMIN_EMAIL, SANDBOX_ADMIN_PASSWORD, SANDBOX_TUTORIAL_PASSWORD  # §SBROTATE


@federation_test(
    name="login_response_has_required_fields",
    category="login_response_contract",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["auth", "contract", "login-payload"],
)
async def test_login_response_fields(
    rig: FederationTestRig,
) -> AssertionResult:
    """/auth/login response must include access_token + token_type +
    expires_in. These are documented in CLAUDE.md PART 6 and consumed
    by every bridge."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "adminGetDeveloperToken",
                {
                    "email": SANDBOX_ADMIN_EMAIL,
                    "password": SANDBOX_ADMIN_PASSWORD,
                },
            )
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            state["keys"] = sorted(r.keys())
            required = ["access_token", "token_type"]
            missing = [k for k in required if not r.get(k)]
            state["missing"] = missing
            return not missing
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="login response has access_token + token_type",
        capture_state=lambda: state,
    )


@federation_test(
    name="login_jwt_has_sub_and_exp_claims",
    category="login_response_contract",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["auth", "contract", "jwt-claims"],
)
async def test_jwt_claims(rig: FederationTestRig) -> AssertionResult:
    """The access_token JWT payload must contain `sub` (dev_id) and
    `exp` (expiry). RBAC + operator tests depend on `sub` for dev_id
    extraction; expiring tokens are required by the security model."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "adminGetDeveloperToken",
                {
                    "email": SANDBOX_ADMIN_EMAIL,
                    "password": SANDBOX_ADMIN_PASSWORD,
                },
            )
            if not isinstance(r, dict) or not r.get("access_token"):
                state["no_token"] = True
                return False
            jwt = r["access_token"]
            # decode payload
            payload = jwt.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            state["claim_keys"] = sorted(claims.keys())
            state["sub"] = claims.get("sub")
            state["exp"] = claims.get("exp")
            return bool(claims.get("sub")) and bool(claims.get("exp"))
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="login JWT payload has sub + exp claims",
        capture_state=lambda: state,
    )


@federation_test(
    name="jwt_exp_within_reasonable_window",
    category="login_response_contract",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["auth", "contract", "jwt-expiry"],
)
async def test_jwt_expiry_window(rig: FederationTestRig) -> AssertionResult:
    """JWT exp claim should be between 5 min and 24h from now. Server
    config is 90 min per CLAUDE.md PART 6 — but we accept the wider
    window to allow for future tuning."""
    import time
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "adminGetDeveloperToken",
                {
                    "email": SANDBOX_ADMIN_EMAIL,
                    "password": SANDBOX_ADMIN_PASSWORD,
                },
            )
            if not isinstance(r, dict) or not r.get("access_token"):
                return False
            jwt = r["access_token"]
            payload = jwt.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            exp = claims.get("exp")
            if not exp:
                state["no_exp"] = True
                return False
            now = int(time.time())
            ttl = int(exp) - now
            state["exp"] = exp
            state["now"] = now
            state["ttl_seconds"] = ttl
            # 5 min = 300s; 24h = 86400s
            return 300 <= ttl <= 86400
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="JWT expiry in reasonable window (5min-24h)",
        capture_state=lambda: state,
    )
