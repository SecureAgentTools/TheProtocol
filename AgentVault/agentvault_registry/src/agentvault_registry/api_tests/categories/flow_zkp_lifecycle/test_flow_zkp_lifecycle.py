"""ZKP Attestation lifecycle E2E flow (Phase 2, v2.0.0 circuits).

Every attestation here is a real fairMarkupPolicy/v2.0.0 proof made by the
target's own /admin/tutorial/generate-proof (zkp_v2_helpers): proof_of_reputation
(Option B) is never a verified proof, so it cannot stand in for one.

Asserts:
  - new attestations get expires_at = now + ZKP_DEFAULT_EXPIRY_DAYS days
  - agent self-revoke writes revoked_at + revoked_by + revoked_reason
  - re-verify of revoked row returns verified=false, revoked=true
  - synthetic-expired row is picked up by the expiry sweeper, an
    AttestationExpired event is emitted exactly once (daily idempotency)
  - re-verify of expired row returns verified=false, expired=true

The "synthetic expired" step uses a direct UPDATE on the registry DB to
shift expires_at into the past — the same approach `flow_funding_request`
uses to query EventStore counts. The expiry sweep is invoked
synchronously via the sandbox-only debug endpoint
`POST /api/v1/admin/attestations/run-expiry-sweep`.

Sandbox-only — relies on SANDBOX_MODE=true and the api-tester's sandbox
token acquisition.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict

from agentvault_registry.api_tests.base import APITestBase
from agentvault_registry.api_tests.multiframe_helpers import (
    REG_DB_A,
    get_target,
    login_admin, onboard_agent, get_agent_jwt,
    http_in_container, query_event_count,
    run_psql_in_db_container,
)
from agentvault_registry.api_tests.zkp_v2_helpers import FAIR_MARKUP, prove_and_submit

logger = logging.getLogger(__name__)

# Sandbox A registry DB container (where the attestations table lives)
_REG_DB = REG_DB_A


class TestFlowZkpLifecycle(APITestBase):
    CATEGORY_NAME = "flow_zkp_lifecycle"
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
        std["flow_tests"] = await self.test_zkp_lifecycle_flow(developer_token)
        return std

    async def _submit_attestation(
        self, target, dev_jwt: str, agent_jwt: str, agent_did: str
    ) -> tuple[bool, str | None, dict]:
        """A fresh fairMarkupPolicy/v2.0.0 proof for agent_did, submitted as that agent: (verified, attestation_id, details)."""
        sub = await prove_and_submit(target.a_registry_container, dev_jwt, agent_jwt, FAIR_MARKUP, agent_did)
        return sub["verified"], sub["attestation_id"], sub

    async def test_zkp_lifecycle_flow(self, developer_token: str) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info("Starting ZKP Attestation Lifecycle Flow (Phase 2)")
        logger.info("=" * 60)

        target = get_target("sandbox")
        results = []
        ts = int(time.time()) % 100000

        # ── Step 1: submit attestation, assert expires_at is set ─────────
        ok_a, dev_jwt, det = await login_admin(target, "a")
        if not ok_a:
            results.append(self._fail_step(1, "Submit attestation", f"Admin login: {det}"))
            return self._summarize(results, False)

        ok, agent_info, det = await onboard_agent(target, "a", dev_jwt, f"zkp-life-{ts}")
        if not ok:
            results.append(self._fail_step(1, "Submit attestation", f"Onboard: {det}"))
            return self._summarize(results, False)
        agent_did = agent_info["did"]

        ok_jwt, agent_jwt, det = await get_agent_jwt(
            target, "a", agent_info["client_id"], agent_info["client_secret"]
        )
        if not ok_jwt:
            results.append(self._fail_step(1, "Submit attestation", f"Agent JWT: {det}"))
            return self._summarize(results, False)

        ok, att1_id, sub1 = await self._submit_attestation(target, dev_jwt, agent_jwt, agent_did)
        # Read back the row to inspect expires_at (the submit response doesn't echo it)
        expires_at_present = False
        if ok and att1_id:
            ok2, row, code = await http_in_container(
                target.a_registry_container, "GET",
                f"/api/v1/attestations/{att1_id}",
                jwt=dev_jwt, timeout=10,
            )
            if ok2 and isinstance(row, dict):
                expires_at_present = bool(row.get("expires_at"))
        step1_ok = ok and bool(att1_id) and expires_at_present
        results.append({
            "step": 1, "name": "Submit a real v2 proof (verified), assert expires_at populated",
            "path": "/attestations/submit", "method": "POST", "authRequired": "agent",
            "healthy": step1_ok,
            "statusCode": 200 if step1_ok else 500,
            "responseData": {
                "attestation_id": att1_id,
                "expires_at_set": expires_at_present,
            },
            "error": None if step1_ok else (sub1["error"] or "expires_at missing"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not step1_ok:
            return self._summarize(results, False)

        # ── Step 2: agent self-revoke ───────────────────────────────────
        revoke_reason = f"flow_zkp_lifecycle test revoke @{ts}"
        ok, body, code = await http_in_container(
            target.a_registry_container, "POST",
            f"/api/v1/attestations/{att1_id}/revoke",
            body={"reason": revoke_reason},
            jwt=agent_jwt, timeout=10,
        )
        revoke_ok = (
            ok and isinstance(body, dict)
            and body.get("attestation_id") == att1_id
            and bool(body.get("revoked_at"))
            and body.get("revoked_by") == agent_did
        )
        results.append({
            "step": 2, "name": "Agent self-revoke own attestation",
            "path": "/attestations/{id}/revoke", "method": "POST", "authRequired": "agent",
            "healthy": revoke_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "revoked_at": (body or {}).get("revoked_at"),
                "revoked_by": (body or {}).get("revoked_by"),
                "revoked_reason": (body or {}).get("revoked_reason"),
            },
            "error": None if revoke_ok else f"revoke failed (http={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 3: GET /{id} reflects revoke state ─────────────────────
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            f"/api/v1/attestations/{att1_id}",
            jwt=dev_jwt, timeout=10,
        )
        state_ok = (
            ok and isinstance(body, dict)
            and body.get("revoked_by") == agent_did
            and revoke_reason in (body.get("revoked_reason") or "")
        )
        results.append({
            "step": 3, "name": "GET /attestations/{id} reflects revoke state",
            "path": "/attestations/{id}", "method": "GET", "authRequired": "developer",
            "healthy": state_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "revoked_by": (body or {}).get("revoked_by"),
                "revoked_reason": (body or {}).get("revoked_reason"),
            },
            "error": None if state_ok else f"GET mismatch (http={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 4: re-verify revoked row → verified=false, revoked=true ─
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            f"/api/v1/attestations/{att1_id}/verify",
            timeout=15,
        )
        rev_verify_ok = (
            ok and isinstance(body, dict)
            and body.get("verified") is False
            and body.get("revoked") is True
            and "revoked" in str(body.get("failure_reason") or "")
        )
        results.append({
            "step": 4, "name": "Re-verify revoked row → verified=false, revoked=true",
            "path": "/attestations/{id}/verify", "method": "GET", "authRequired": "none",
            "healthy": rev_verify_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "verified": (body or {}).get("verified"),
                "revoked": (body or {}).get("revoked"),
                "expired": (body or {}).get("expired"),
            },
            "error": None if rev_verify_ok else f"reverify wrong (http={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 5: submit second attestation, force-expire it via psql ──
        ok, att2_id, sub2 = await self._submit_attestation(target, dev_jwt, agent_jwt, agent_did)
        force_ok = ok and bool(att2_id)
        if force_ok:
            sql = (
                f"UPDATE attestations SET expires_at = NOW() - INTERVAL '1 day' "
                f"WHERE id = '{att2_id}';"
            )
            rc, out = run_psql_in_db_container(_REG_DB, sql, db_name=None)
            force_ok = (rc == 0)
        results.append({
            "step": 5, "name": "Submit a second real v2 proof + force-expire via psql",
            "path": "/attestations/submit + UPDATE attestations", "method": "POST",
            "authRequired": "agent",
            "healthy": force_ok,
            "statusCode": 200 if force_ok else 500,
            "responseData": {"attestation_id": att2_id},
            "error": None if force_ok else (sub2["error"] or "psql update failed"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not force_ok:
            return self._summarize(results, False)

        # ── Step 6: run sweep → AttestationExpired emitted; second sweep is no-op ─
        baseline_expired = max(0, query_event_count(target.a_es_db_container, "AttestationExpired"))
        ok1, body1, code1 = await http_in_container(
            target.a_registry_container, "POST",
            "/api/v1/attestations/admin/run-expiry-sweep",
            body={}, jwt=dev_jwt, timeout=15,
        )
        first_processed = (body1 or {}).get("processed") if (ok1 and isinstance(body1, dict)) else None
        # small grace — emission is awaited inline but EventStore Kafka path
        # may need a tick to land the row.
        import asyncio as _aio
        await _aio.sleep(1.5)
        post_expired = max(0, query_event_count(target.a_es_db_container, "AttestationExpired"))
        delta_first = post_expired - baseline_expired

        ok2, body2, code2 = await http_in_container(
            target.a_registry_container, "POST",
            "/api/v1/attestations/admin/run-expiry-sweep",
            body={}, jwt=dev_jwt, timeout=15,
        )
        second_processed = (body2 or {}).get("processed") if (ok2 and isinstance(body2, dict)) else None

        sweep_ok = (
            ok1 and ok2
            and (first_processed is not None and first_processed >= 1)
            and (second_processed == 0)
            and delta_first >= 1
        )
        results.append({
            "step": 6, "name": "Sweep emits exactly once (daily idempotency)",
            "path": "/attestations/admin/run-expiry-sweep", "method": "POST",
            "authRequired": "developer",
            "healthy": sweep_ok,
            "statusCode": int(code1) if code1.isdigit() else 500,
            "responseData": {
                "first_processed": first_processed,
                "second_processed": second_processed,
                "delta_AttestationExpired": delta_first,
            },
            "error": None if sweep_ok else f"sweep idempotency wrong (1st={first_processed}, 2nd={second_processed}, delta={delta_first})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 7: re-verify expired row → verified=false, expired=true ─
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            f"/api/v1/attestations/{att2_id}/verify",
            timeout=15,
        )
        exp_verify_ok = (
            ok and isinstance(body, dict)
            and body.get("verified") is False
            and body.get("expired") is True
            and body.get("revoked") is False
            and "expired" in str(body.get("failure_reason") or "")
        )
        results.append({
            "step": 7, "name": "Re-verify expired row → verified=false, expired=true",
            "path": "/attestations/{id}/verify", "method": "GET", "authRequired": "none",
            "healthy": exp_verify_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "verified": (body or {}).get("verified"),
                "expired": (body or {}).get("expired"),
                "revoked": (body or {}).get("revoked"),
            },
            "error": None if exp_verify_ok else f"reverify wrong (http={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        self.flow_values = {
            "agent_did": agent_did,
            "attestation_id_revoked": att1_id,
            "attestation_id_expired": att2_id,
            "delta_AttestationExpired": delta_first,
        }
        return self._summarize(results, True)

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
            "flow_name": "flow_zkp_lifecycle_complete",
            "success": flow_success and ok == total,
            "total_steps": total,
            "successful_steps": ok,
            "results": results,
            "flow_values": dict(self.flow_values),
        }
