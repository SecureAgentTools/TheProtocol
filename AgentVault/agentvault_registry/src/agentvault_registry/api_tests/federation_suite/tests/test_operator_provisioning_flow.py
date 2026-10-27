"""Operator provisioning management flow tests (§pass73.3.15 — RBAC follow-on).

End-to-end exercise of the operator-application MANAGEMENT lifecycle
WITHOUT actually spawning a cloud-op stack:

  1. Bootstrap a candidate developer (idempotent)
  2. Admin patches the dev's resource quota
  3. Dev/admin submits an operator-application (idempotent, dedupes by email)
  4. Admin approves the application
  5. Admin observes the application appearing in the inventory

This exercises the same quota + state-transition code paths that
sandbox/prod operator onboarding uses, minus the heavy cloud-op
container spin-up (which is 90-180s — covered separately by
the retired `sandboxProvisionerLifecycleTest`).

ALL TESTS ARE IDEMPOTENT — sentinel dev email is fixed; reruns reuse
existing dev + application records.
"""
from __future__ import annotations
import asyncio
import base64
import json
from typing import Optional


def _decode_jwt_sub(jwt: str) -> Optional[int]:
    """Extract `sub` claim (developer_id) from a JWT."""
    try:
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        sub = claims.get("sub")
        return int(sub) if sub is not None else None
    except Exception:
        return None

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, jwt_usable,
)


CANDIDATE_EMAIL = "rbac_operator_candidate@test.sandbox"
CANDIDATE_PASSWORD = "OperatorCandidate2026!"
CANDIDATE_NAME = "RBAC Operator Candidate"

# Module-level cache shared across tests in this file.
# §MCPTEST30 (2026-09-30): it outlives the run (it lives as long as the gunicorn worker), so the candidate's token is
# handed out only while its own `exp` is more than five minutes away and is dropped when the registry refuses it. The
# 03:10Z nightly presented an expired token here and read the 401 as the my-status surface failing.
_STATE: dict = {}
_LOCK = asyncio.Lock()


def _forget_token() -> None:
    """Drop the candidate's cached token (refused or expiring); the dev id and the application stay cached."""
    _STATE.pop("dev_jwt", None)


def _is_silent_or_error(r):
    if isinstance(r, str):
        return True
    if isinstance(r, dict):
        if not r:
            return True
        if "_text" in r:
            return isinstance(r["_text"], str)
    return False


async def _ensure_candidate_dev(rig: FederationTestRig, fresh: bool = False) -> tuple[int, str]:
    """Idempotently provision the candidate operator developer.

    Returns (dev_id, dev_jwt). dev_jwt expires (90 min): a cached one is handed out only while jwt_usable() says so,
    otherwise the login path below mints a fresh one (it is also the idempotent path). `fresh` drops the cached token
    first: the sentinel's claim is that the token MINTS, which a cached one cannot show (§MCPTEST30 2026-10-06: two
    runs 65 min apart on one worker, the second sentinel made no call and read vacuous).
    """
    async with _LOCK:
        if fresh:
            _forget_token()
        if "dev_id" in _STATE and jwt_usable(_STATE.get("dev_jwt")):
            return _STATE["dev_id"], _STATE["dev_jwt"]
        _forget_token()

        admin = rig.mcp("sandbox-A-admin")

        # Try direct login first (idempotent path).
        # MCP wrapper returns underlying /auth/login response (no developer_id);
        # decode JWT `sub` claim ourselves.
        try:
            tok = await admin.call(
                "adminGetDeveloperToken",
                {"email": CANDIDATE_EMAIL, "password": CANDIDATE_PASSWORD},
            )
            if isinstance(tok, dict) and tok.get("access_token"):
                jwt = tok["access_token"]
                did = _decode_jwt_sub(jwt)
                if did:
                    _STATE["dev_id"] = did
                    _STATE["dev_jwt"] = jwt
                    return did, jwt
        except Exception:
            pass

        # Register fresh via adminRequest → /auth/register
        # (MCP authRegister wrapper drops `name` field; bypass it).
        try:
            await admin.call(
                "adminRequest",
                {
                    "method": "POST",
                    "endpoint": "/api/v1/auth/register",
                    "body": {
                        "name": CANDIDATE_NAME,
                        "email": CANDIDATE_EMAIL,
                        "password": CANDIDATE_PASSWORD,
                    },
                },
            )
        except Exception:
            pass

        # Login post-register
        tok = await admin.call(
            "adminGetDeveloperToken",
            {"email": CANDIDATE_EMAIL, "password": CANDIDATE_PASSWORD},
        )
        if not isinstance(tok, dict) or not tok.get("access_token"):
            raise RuntimeError(
                f"operator_provisioning: login after register failed: {tok}"
            )
        jwt = tok["access_token"]
        dev_id = _decode_jwt_sub(jwt)
        if not dev_id:
            raise RuntimeError("operator_provisioning: JWT sub decode failed")

        # Force-verify email (idempotent)
        try:
            await admin.call("forceEmailVerify", {"developer_id": int(dev_id)})
        except Exception:
            pass

        _STATE["dev_id"] = int(dev_id)
        _STATE["dev_jwt"] = jwt
        return _STATE["dev_id"], _STATE["dev_jwt"]


@federation_test(
    name="operator_candidate_dev_bootstrap",
    category="operator_provisioning_flow",
    budget_sec=60.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["operator", "bootstrap"],
)
async def test_candidate_bootstrap(rig: FederationTestRig) -> AssertionResult:
    """Sentinel candidate developer is registered + email-verified."""
    state: dict = {}

    async def predicate():
        try:
            dev_id, dev_jwt = await _ensure_candidate_dev(rig, fresh=True)
            state["dev_id"] = dev_id
            state["jwt_present"] = bool(dev_jwt)
            return bool(dev_id and dev_jwt)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=60.0, predicate=predicate,
        description="candidate dev exists + JWT mints for operator flow",
        capture_state=lambda: state,
    )


@federation_test(
    name="operator_quota_patch_grants_capacity",
    category="operator_provisioning_flow",
    budget_sec=30.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["operator", "quota"],
)
async def test_quota_patch(rig: FederationTestRig) -> AssertionResult:
    """Admin patches dev quota (max_agents) and getAdminDeveloperQuota
    reflects the new value."""
    state: dict = {}

    async def predicate():
        try:
            dev_id, _ = await _ensure_candidate_dev(rig)
            admin = rig.mcp("sandbox-A-admin")

            # Read current quota
            try:
                pre = await admin.call("getAdminDeveloperQuota",
                                        {"developer_id": dev_id})
                state["pre"] = pre if isinstance(pre, dict) else {"shape": type(pre).__name__}
            except Exception as e:
                state["pre_error"] = repr(e)[:200]

            # Quota schema is bundle-scoped (not agent-scoped) — patch
            # max_bundle_count and verify roundtrip.
            target_count = 250
            r = await admin.call(
                "patchDeveloperQuota",
                {"developer_id": dev_id,
                 "quota_updates": {"max_bundle_count": target_count}},
            )
            state["patch"] = r if isinstance(r, dict) else {"shape": type(r).__name__}

            # Read post-state
            post = await admin.call("getAdminDeveloperQuota",
                                     {"developer_id": dev_id})
            state["post"] = post if isinstance(post, dict) else None
            post_count = (
                post.get("max_bundle_count") if isinstance(post, dict) else None
            )
            state["post_max_bundle_count"] = post_count
            return post_count == target_count
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="admin patchDeveloperQuota persists + reads back",
        capture_state=lambda: state,
    )


@federation_test(
    name="operator_application_submit_and_inventory",
    category="operator_provisioning_flow",
    budget_sec=30.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["operator", "application", "submit"],
)
async def test_application_submit(rig: FederationTestRig) -> AssertionResult:
    """Submit operator-application (idempotent — dedupes by email). Admin
    sees it in `listAdminOperatorApplications` inventory."""
    state: dict = {}

    async def predicate():
        try:
            await _ensure_candidate_dev(rig)
            admin = rig.mcp("sandbox-A-admin")

            # Try submit via adminRequest → public endpoint (no developer_jwt
            # needed; submission is a Tier-1 landing-page surface).
            # 409 if pending app exists — idempotent pass path.
            app_id = None
            try:
                r = await admin.call(
                    "adminRequest",
                    {
                        "method": "POST",
                        "endpoint": "/api/v1/operator-applications",
                        "body": {
                            "name": CANDIDATE_NAME,
                            "email": CANDIDATE_EMAIL,
                            "organization": "RBAC Federation Test",
                            "deployment": "sandbox",
                            "experience": "advanced",
                            "use_case": "federation_test_suite operator provisioning probe",
                            # §LEGALKIT made acceptance of the Federation Operator Terms a required field
                            # (routers/operator_applications.py refuses 422 without it). The standing pair kept
                            # passing on an application row older than that rule; a fresh frame met the 422
                            # (§NIGHTPROV, nt260927x2a), and approve then had no application to act on.
                            "accept_operator_terms": True,
                        },
                    },
                )
                state["submit_status"] = (
                    r.get("status_code") if isinstance(r, dict) else None
                )
                resp = r.get("response") if isinstance(r, dict) else None
                if isinstance(resp, dict):
                    app_id = resp.get("id") or resp.get("application_id")
                    state["app_id"] = app_id
            except Exception as e:
                state["submit_error"] = repr(e)[:300]

            # List admin inventory + verify the email appears
            apps = await admin.call(
                "listAdminOperatorApplications", {}
            )
            items = apps if isinstance(apps, list) else (
                apps.get("applications") or apps.get("items") or
                apps.get("data") or []
            ) if isinstance(apps, dict) else []
            matching = [
                it for it in items
                if isinstance(it, dict) and it.get("email") == CANDIDATE_EMAIL
            ]
            state["matching_count"] = len(matching)
            if matching:
                state["app_id"] = matching[0].get("id")
                state["status"] = matching[0].get("status")
                _STATE["application_id"] = matching[0].get("id")
                _STATE["application_status"] = matching[0].get("status")
            return len(matching) >= 1
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="operator-application submitted + visible in admin inventory",
        capture_state=lambda: state,
    )


@federation_test(
    name="operator_application_admin_approve",
    category="operator_provisioning_flow",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["operator", "application", "approve"],
)
async def test_application_approve(rig: FederationTestRig) -> AssertionResult:
    """Admin approves the application; status transitions to 'approved'."""
    state: dict = {}

    async def predicate():
        try:
            await _ensure_candidate_dev(rig)
            admin = rig.mcp("sandbox-A-admin")

            # Find the application id (rebootstrap inventory if needed)
            app_id = _STATE.get("application_id")
            if not app_id:
                apps = await admin.call(
                    "listAdminOperatorApplications", {}
                )
                items = apps if isinstance(apps, list) else (
                    apps.get("applications") or apps.get("items") or
                    apps.get("data") or []
                ) if isinstance(apps, dict) else []
                for it in items:
                    if isinstance(it, dict) and it.get("email") == CANDIDATE_EMAIL:
                        app_id = it.get("id")
                        break
            if not app_id:
                state["no_app_id"] = True
                return False
            state["app_id"] = app_id

            # Check current status
            cur = await admin.call(
                "getAdminOperatorApplication", {"application_id": app_id}
            )
            cur_status = cur.get("status") if isinstance(cur, dict) else None
            state["pre_status"] = cur_status

            # If already approved/active, idempotent pass
            if cur_status in ("approved", "active", "provisioning",
                              "provisioned", "live"):
                state["idempotent_skip"] = True
                return True

            # Approve
            r = await admin.call(
                "approveOperatorApplication", {"application_id": app_id}
            )
            state["approve"] = r if isinstance(r, dict) else {"shape": type(r).__name__}

            # Re-read status
            post = await admin.call(
                "getAdminOperatorApplication", {"application_id": app_id}
            )
            post_status = post.get("status") if isinstance(post, dict) else None
            state["post_status"] = post_status
            return post_status in ("approved", "active", "provisioning",
                                    "provisioned", "live")
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="admin approves application → status transitions",
        capture_state=lambda: state,
    )


@federation_test(
    name="operator_my_status_visible_to_candidate",
    category="operator_provisioning_flow",
    budget_sec=20.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["operator", "my-status"],
)
async def test_my_status(rig: FederationTestRig) -> AssertionResult:
    """The candidate dev's /operators/my-status reflects their application
    (probed via adminRequest with developer_jwt override)."""
    state: dict = {}

    async def predicate():
        try:
            dev_id, dev_jwt = await _ensure_candidate_dev(rig)
            state["dev_id"] = dev_id
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {
                    "method": "GET",
                    "endpoint": "/api/v1/operators/my-status",
                    "developer_jwt": dev_jwt,
                },
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            if state["status_code"] == 401:
                # §MCPTEST30: the registry refused the TEST'S token (expired or revoked), so the surface was never
                # asked. Drop it; the next attempt mints a fresh one and measures.
                _forget_token()
                state["credential_refused"] = True
                return False
            state.pop("credential_refused", None)
            resp = r.get("response") if isinstance(r, dict) else None
            if isinstance(resp, dict):
                state["resp_keys"] = sorted(resp.keys())[:8]
                state["app_status"] = resp.get("status") or resp.get("application_status")
            # Accept 200 (has app) or 404 (no app yet); either confirms surface
            return state["status_code"] in (200, 404)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="operators/my-status reachable for candidate dev",
        capture_state=lambda: state,
    )
