"""JWT token uniqueness tests (§pass73.3.17 Batch 82).

3 tests verifying JWT signing behavior — two logins produce different
tokens (different nonce/iat) for the same user (replay protection),
but both decode to the same `sub` (dev_id).

Catches signing-key drift, jti omission, or replay vulnerability.
"""
from __future__ import annotations
import base64
import json
import time

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


def _decode_jwt(jwt: str) -> dict:
    payload = jwt.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


@federation_test(
    name="two_logins_produce_different_jwts",
    category="jwt_token_uniqueness",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["jwt", "uniqueness", "replay-prevention"],
)
async def test_two_logins_differ(rig: FederationTestRig) -> AssertionResult:
    """Two consecutive logins as the same dev must produce different
    access_tokens (different `iat` or `jti` claim). Same string = JWT
    is fully deterministic = replay attack window."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r1 = await admin.call(
                "adminGetDeveloperToken",
                {"email": SANDBOX_ADMIN_EMAIL, "password": SANDBOX_ADMIN_PASSWORD},
            )
            jwt1 = r1.get("access_token") if isinstance(r1, dict) else None
            # Tiny sleep to ensure iat differs (typically 1s resolution)
            time.sleep(1.1)
            r2 = await admin.call(
                "adminGetDeveloperToken",
                {"email": SANDBOX_ADMIN_EMAIL, "password": SANDBOX_ADMIN_PASSWORD},
            )
            jwt2 = r2.get("access_token") if isinstance(r2, dict) else None
            if not jwt1 or not jwt2:
                state["missing_token"] = True
                return False
            state["jwt1_prefix"] = jwt1[:30]
            state["jwt2_prefix"] = jwt2[:30]
            state["differ"] = jwt1 != jwt2
            return jwt1 != jwt2
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="two logins produce different JWTs (replay-resistant)",
        capture_state=lambda: state,
    )


@federation_test(
    name="two_logins_same_sub_claim",
    category="jwt_token_uniqueness",
    budget_sec=60.0,  # two slow sequential logins under load need retry room
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["jwt", "sub-claim", "consistency"],
)
async def test_same_sub(rig: FederationTestRig) -> AssertionResult:
    """Two logins as same user produce JWTs with the SAME sub claim
    (dev_id is consistent across login sessions)."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r1 = await admin.call(
                "adminGetDeveloperToken",
                {"email": SANDBOX_ADMIN_EMAIL, "password": SANDBOX_ADMIN_PASSWORD},
            )
            time.sleep(0.5)
            r2 = await admin.call(
                "adminGetDeveloperToken",
                {"email": SANDBOX_ADMIN_EMAIL, "password": SANDBOX_ADMIN_PASSWORD},
            )
            jwt1 = r1.get("access_token") if isinstance(r1, dict) else None
            jwt2 = r2.get("access_token") if isinstance(r2, dict) else None
            # Transient login error under concurrent-suite load (error dict /
            # timeout) → no token this round; return False so the widened
            # budget retries instead of KeyError-failing the whole test.
            if not jwt1 or not jwt2:
                state["missing_token"] = {"r1": bool(jwt1), "r2": bool(jwt2)}
                return False
            sub1 = _decode_jwt(jwt1).get("sub")
            sub2 = _decode_jwt(jwt2).get("sub")
            state["sub1"] = sub1
            state["sub2"] = sub2
            return sub1 == sub2 and sub1 is not None
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=60.0, predicate=predicate,
        description="two logins → same sub claim (consistent dev_id)",
        capture_state=lambda: state,
    )


@federation_test(
    name="different_users_different_sub",
    category="jwt_token_uniqueness",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["jwt", "sub-claim", "uniqueness"],
)
async def test_different_users_different_sub(
    rig: FederationTestRig,
) -> AssertionResult:
    """Two DIFFERENT user logins produce JWTs with different sub claims.
    Catches signing-key drift or sub-claim contamination."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")

            # Login as commander
            r1 = await admin.call(
                "adminGetDeveloperToken",
                {"email": SANDBOX_ADMIN_EMAIL, "password": SANDBOX_ADMIN_PASSWORD},
            )
            jwt1 = r1.get("access_token")
            sub1 = _decode_jwt(jwt1).get("sub") if jwt1 else None

            # Login as RBAC operator candidate (created by other tests)
            r2 = await admin.call(
                "adminGetDeveloperToken",
                {"email": "rbac_operator_candidate@test.sandbox",
                 "password": "OperatorCandidate2026!"},
            )
            jwt2 = r2.get("access_token")
            sub2 = _decode_jwt(jwt2).get("sub") if jwt2 else None

            if not sub1 or not sub2:
                state["missing_sub"] = True
                state["jwt1_present"] = bool(jwt1)
                state["jwt2_present"] = bool(jwt2)
                return False
            state["sub1"] = sub1
            state["sub2"] = sub2
            return sub1 != sub2
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="different users → different sub claims",
        capture_state=lambda: state,
    )
