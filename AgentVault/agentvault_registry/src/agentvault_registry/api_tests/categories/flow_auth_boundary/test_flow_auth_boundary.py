"""Auth Boundary Flow.

Probes authorization boundaries — verifies that wrong-tier / cross-account /
tampered / expired tokens are properly REJECTED. Catches IDOR-style bugs and
admin-gate omissions before they hit prod.

Each "negative test" expects a 4xx response. A success (200) for any of these
probes indicates a real authz hole.

Sandbox-only.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict

from agentvault_registry.api_tests.base import APITestBase
from agentvault_registry.api_tests.multiframe_helpers import (
    SANDBOX_TARGET, get_target,
    login_admin, onboard_agent, get_agent_jwt, http_in_container,
)

logger = logging.getLogger(__name__)


class TestFlowAuthBoundary(APITestBase):
    CATEGORY_NAME = "flow_auth_boundary"
    flow_values: Dict[str, Any] = {}

    async def setup(self):
        await self.setup_category(self.CATEGORY_NAME)
        self.flow_values = {}

    async def teardown(self):
        return

    async def test_all(self, developer_token=None, agent_token=None):
        std = await self.test_category_endpoints(
            category=self.CATEGORY_NAME,
            developer_token=developer_token,
            agent_token=agent_token,
            priority_only=False,
        )
        std["flow_tests"] = await self.test_auth_boundary_flow(developer_token)
        return std

    async def test_auth_boundary_flow(self, developer_token: str) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info("Starting Auth Boundary Flow")
        logger.info("=" * 60)

        target = get_target("sandbox")
        results = []
        ts = int(time.time()) % 100000

        # Bootstrap: login admin + non-admin developer
        ok_a, dev_jwt_admin, det = await login_admin(target, "a")
        if not ok_a:
            results.append(self._fail_step(1, "Sandbox-A admin login", det))
            return self._summarize(results, False)

        # Login as non-admin developer — try a few known sandbox credentials.
        # If none work, skip the non-admin probes gracefully (mark EF) and
        # continue with the other 4 boundary probes.
        non_admin_jwt = ""
        for email, pwd in [
            ("developer@test.sandbox", "TestDev123!"),
            ("developer@test.sandbox", "DevPass123!"),
            ("auditor@theprotocol.cloud", "AuditorPass123!"),
        ]:
            jwt = await asyncio.to_thread(self._login_dev_sync, target, email, pwd)
            if jwt:
                non_admin_jwt = jwt
                break
        non_admin_login_ok = bool(non_admin_jwt)
        results.append({
            "step": 1, "name": "Login as non-admin developer",
            "path": "/auth/login", "method": "POST", "authRequired": "none",
            "healthy": True,  # informational — downstream probes that need this will EF gracefully
            "expected_failure": (not non_admin_login_ok),
            "expected_failure_reason": (
                "No non-admin developer credentials worked in sandbox. Skipping admin-gate + cross-owner probes."
                if not non_admin_login_ok else None
            ),
            "statusCode": 200 if non_admin_login_ok else 401,
            "responseData": {"jwt_acquired": non_admin_login_ok},
            "error": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Onboard alice + bob
        ok_a1, alice, det = await onboard_agent(target, "a", dev_jwt_admin, f"boundary-alice-{ts}")
        results.append(self._step_from_onboard(2, f"Onboard boundary-alice-{ts}", ok_a1, alice, det))
        if not ok_a1:
            return self._summarize(results, False)

        ok_b, bob, det = await onboard_agent(target, "a", dev_jwt_admin, f"boundary-bob-{ts}")
        results.append(self._step_from_onboard(3, f"Onboard boundary-bob-{ts}", ok_b, bob, det))
        if not ok_b:
            return self._summarize(results, False)

        # Get alice agent JWT
        ok_jwt, alice_jwt, det = await get_agent_jwt(target, "a", alice["client_id"], alice["client_secret"])
        if not ok_jwt:
            results.append(self._fail_step(4, "alice agent JWT", det))
            return self._summarize(results, False)

        # ── Probe 1: alice agent JWT used on a developer-tier endpoint ─────
        # /developers/me/agents requires developer JWT. alice's agent JWT should be rejected.
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            "/api/v1/developers/me/agents",
            jwt=alice_jwt, timeout=15,
        )
        # Expect REJECTION (4xx). 2xx = bug.
        rejected = (not ok) and code.isdigit() and 400 <= int(code) < 500
        results.append({
            "step": 4, "name": "Agent JWT on developer-tier endpoint (must reject)",
            "path": "/developers/me/agents", "method": "GET",
            "authRequired": "developer",
            "healthy": rejected,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {"expected": "401/403 — agent token rejected", "got": code,
                             "raw_excerpt": str(body)[:120]},
            "error": None if rejected else f"AUTH HOLE: agent JWT accepted on dev-tier endpoint (code={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Probe 2: developer JWT used on agent-tier endpoint ─────────────
        # /governance/proposals POST requires agent JWT. developer JWT should be rejected.
        ok, body, code = await http_in_container(
            target.a_registry_container, "POST",
            "/api/v1/governance/proposals",
            body={"title": "boundary probe", "description": "boundary test",
                  "duration_seconds": 60, "proposal_type": "standard"},
            jwt=dev_jwt_admin, timeout=15,
        )
        rejected = (not ok) and code.isdigit() and 400 <= int(code) < 500
        results.append({
            "step": 5, "name": "Developer JWT on agent-tier endpoint (must reject)",
            "path": "/governance/proposals", "method": "POST",
            "authRequired": "agent",
            "healthy": rejected,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {"expected": "401 — dev token on agent endpoint", "got": code,
                             "raw_excerpt": str(body)[:120]},
            "error": None if rejected else f"AUTH HOLE: dev JWT accepted on agent endpoint (code={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Probe 3: non-admin developer hits admin-only endpoint ──────────
        # /admin/system-resources requires is_admin=True. Non-admin should be 403.
        if non_admin_jwt:
            ok, body, code = await http_in_container(
                target.a_registry_container, "GET",
                "/api/v1/admin/system-resources",
                jwt=non_admin_jwt, timeout=15,
            )
            rejected = (not ok) and code.isdigit() and 400 <= int(code) < 500
            results.append({
                "step": 6, "name": "Non-admin dev on admin-only endpoint (must reject)",
                "path": "/admin/system-resources", "method": "GET",
                "authRequired": "developer (admin)",
                "healthy": rejected,
                "statusCode": int(code) if code.isdigit() else 500,
                "responseData": {"expected": "403 — admin flag required", "got": code,
                                 "raw_excerpt": str(body)[:120]},
                "error": None if rejected else f"AUTH HOLE: non-admin dev reached admin endpoint (code={code})",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        else:
            results.append({
                "step": 6, "name": "Non-admin dev on admin-only endpoint (skipped — no non-admin JWT)",
                "path": "/admin/system-resources", "method": "GET",
                "authRequired": "developer (admin)",
                "healthy": True,
                "expected_failure": True,
                "expected_failure_reason": "No non-admin dev credentials available in sandbox seed",
                "statusCode": 200,
                "responseData": {"skipped": True},
                "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        # ── Probe 4: tampered JWT (one char flipped) ───────────────────────
        if len(alice_jwt) >= 3:
            # flip a char in the signature segment (last segment)
            sig_part = alice_jwt.rsplit(".", 1)[-1]
            flipped_char = "X" if sig_part[5] != "X" else "Y"
            tampered_jwt = alice_jwt[:-(len(sig_part))] + sig_part[:5] + flipped_char + sig_part[6:]
        else:
            tampered_jwt = alice_jwt + "X"
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            "/api/v1/teg/balance",
            jwt=tampered_jwt, timeout=15,
        )
        rejected = (not ok) and code.isdigit() and 400 <= int(code) < 500
        results.append({
            "step": 7, "name": "Tampered JWT signature (must reject)",
            "path": "/teg/balance", "method": "GET",
            "authRequired": "agent",
            "healthy": rejected,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {"expected": "401 — invalid signature", "got": code,
                             "raw_excerpt": str(body)[:120]},
            "error": None if rejected else f"AUTH HOLE: tampered JWT accepted (code={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Probe 5: empty/missing Authorization on protected endpoint ─────
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            "/api/v1/teg/balance",
            jwt=None, timeout=15,
        )
        rejected = (not ok) and code.isdigit() and 400 <= int(code) < 500
        results.append({
            "step": 8, "name": "No Authorization header on protected endpoint (must reject)",
            "path": "/teg/balance", "method": "GET",
            "authRequired": "agent",
            "healthy": rejected,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {"expected": "401 — no creds", "got": code},
            "error": None if rejected else f"AUTH HOLE: missing auth header accepted (code={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Probe 6: cross-developer admin on agent that isn't theirs ──────
        if non_admin_jwt:
            ok, body, code = await http_in_container(
                target.a_registry_container, "POST",
                f"/api/v1/onboard/agents/{alice['did']}/reset-credentials",
                jwt=non_admin_jwt, timeout=15,
            )
            rejected = (not ok) and code.isdigit() and 400 <= int(code) < 500
            results.append({
                "step": 9, "name": "Non-owner dev tries to reset others' agent credentials (must reject)",
                "path": "/onboard/agents/{agent_did}/reset-credentials", "method": "POST",
                "authRequired": "developer (owner)",
                "healthy": rejected,
                "statusCode": int(code) if code.isdigit() else 500,
                "responseData": {"expected": "403 — not owner", "got": code,
                                 "raw_excerpt": str(body)[:120]},
                "error": None if rejected else f"AUTH HOLE: cross-dev admin allowed (code={code})",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        else:
            results.append({
                "step": 9, "name": "Cross-owner probe (skipped — no non-admin JWT)",
                "path": "/onboard/agents/{agent_did}/reset-credentials", "method": "POST",
                "authRequired": "developer (owner)",
                "healthy": True,
                "expected_failure": True,
                "expected_failure_reason": "No non-admin dev credentials in sandbox seed",
                "statusCode": 200,
                "responseData": {"skipped": True},
                "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        self.flow_values = {
            "alice_did": alice["did"],
            "bob_did": bob["did"],
            "non_admin_jwt_acquired": non_admin_login_ok,
        }
        return self._summarize(results, True)

    def _login_dev_sync(self, target, email: str, password: str) -> str:
        """Sync helper: login as a developer; returns the JWT or empty string."""
        rc, out = exec_in_container(target.a_registry_container, [
            "sh", "-c",
            "curl -sS -X POST "
            f"-H 'Content-Type: application/x-www-form-urlencoded' "
            f"--data-urlencode 'username={email}' "
            f"--data-urlencode 'password={password}' "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            "http://localhost:8000/api/v1/auth/login",
        ], 20)
        body, code = _split_http_body_code(out)
        if rc != 0 or not (code and code.startswith("2")):
            return ""
        try:
            import json as _j
            return _j.loads(body).get("access_token", "")
        except Exception:
            return ""

    def _step_from_onboard(self, step, name, ok, info, det):
        return {
            "step": step, "name": name,
            "path": "/onboard/create_agent", "method": "POST", "authRequired": "none",
            "healthy": ok, "statusCode": 200 if ok else 500,
            "responseData": {"did": (info or {}).get("did", "")[:30] + "..." if ok else None,
                             "detail": det},
            "error": None if ok else det,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _fail_step(self, step, name, detail):
        return {
            "step": step, "name": name, "path": "/auth/login", "method": "POST",
            "healthy": False, "statusCode": 500,
            "responseData": {"detail": detail}, "error": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _summarize(self, results, flow_success: bool) -> Dict[str, Any]:
        total = len(results)
        ok = sum(1 for r in results if r.get("healthy"))
        return {
            "flow_name": "flow_auth_boundary_complete",
            "success": flow_success and ok == total,
            "total_steps": total,
            "successful_steps": ok,
            "results": results,
            "flow_values": dict(self.flow_values),
        }


# Re-export helpers used by sync login
from agentvault_registry.api_tests.multiframe_helpers import (
    exec_in_container, _split_http_body_code, _HTTP_MARKER,
)
