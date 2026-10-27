"""ZKP Phase 5: the v2.0.0 circuit catalog + periodic-attestation cron E2E flow.

Asserts:
  - GET /api/v1/circuits/ lists the four v2.0.0 circuits as active, each with
    its vk_url, metadata_url, public inputs, public output and the policy in
    force, and the four v1.0.0 circuits as retired, each naming its v2.0.0
    successor and carrying no vk_url
  - the ACIR endpoint serves fairCrossRegistryFee/v2.0.0's bytecode
  - every v2.0.0 verification key is served (an UltraHonk key is never under
    512 bytes), and a v1.0.0 key is not (404)
  - GET /circuits/{id}/metadata carries the statement and a policy_in_force
    equal to the policy the list reports
  - a real fairMarkupPolicy/v2.0.0 proof submitted under
    fairCrossRegistryFee/v2.0.0 is not verified (a proof is valid for the
    circuit it was made for)
  - schedules: a v2.0.0 circuit is accepted, a v1.0.0 one is refused with 400
    naming its successor; create + list + cron wired
  - the schedule cron emits AttestationDueReminder events, idempotently
    once per overdue cycle
  - submitting a verified attestation that matches a schedule advances
    next_due_at, and the attestation is found by its circuit_id filter

The tutorial endpoint proves all four v2.0.0 circuits, each proof for the
agent that will submit it (zkp_v2_helpers); this flow checks the keys and
metadata of fairCrossRegistryFee/v2.0.0 and contentSafetyAttestation/v2.0.0
and submits fairMarkupPolicy proofs.

Sandbox-only (uses SANDBOX_MODE-gated `/admin/run-schedule-cron`).
"""
from __future__ import annotations

import asyncio as _aio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from agentvault_registry.api_tests.base import APITestBase
from agentvault_registry.api_tests.multiframe_helpers import (
    REG_DB_A,
    get_target,
    login_admin, onboard_agent, get_agent_jwt,
    http_in_container, query_event_count,
    run_psql_in_db_container,
)
from agentvault_registry.api_tests.zkp_v2_helpers import (
    CONTENT_SAFETY, FAIR_MARKUP, FEE, V1_CIRCUITS, V2_CIRCUITS,
    fetch_size, make_proof, prove_and_submit, status_of, submission, submit,
)

logger = logging.getLogger(__name__)

# The smallest size bb ever writes for an UltraHonk verification key
# (core/zkp_verifier._MIN_VK_BYTES).
_MIN_VK_BYTES = 512


class TestFlowZkpNewCircuits(APITestBase):
    CATEGORY_NAME = "flow_zkp_new_circuits"
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
        std["flow_tests"] = await self.test_zkp_new_circuits_flow(developer_token)
        return std

    async def test_zkp_new_circuits_flow(self, developer_token: str) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info("Starting ZKP Phase 5: v2.0.0 Circuits + Cron Flow")
        logger.info("=" * 60)

        target = get_target("sandbox")
        reg = target.a_registry_container
        results = []
        ts = int(time.time()) % 100000

        # ── Setup ───────────────────────────────────────────────────────
        ok_a, dev_jwt, det = await login_admin(target, "a")
        if not ok_a:
            results.append(self._fail_step(1, "List circuits", f"Admin login: {det}"))
            return self._summarize(results, False)

        ok, agent_info, det = await onboard_agent(target, "a", dev_jwt, f"zkp-nc-{ts}")
        if not ok:
            results.append(self._fail_step(1, "List circuits", f"Onboard: {det}"))
            return self._summarize(results, False)
        agent_did = agent_info["did"]
        ok_jwt, agent_jwt, det = await get_agent_jwt(
            target, "a", agent_info["client_id"], agent_info["client_secret"]
        )
        if not ok_jwt:
            results.append(self._fail_step(1, "List circuits", f"Agent JWT: {det}"))
            return self._summarize(results, False)

        # ── Step 1: the catalog: v2 active, v1 retired ──────────────────
        ok, body, code = await http_in_container(reg, "GET", "/api/v1/circuits/", timeout=10)
        circuits = (body or {}).get("circuits", []) if (ok and isinstance(body, dict)) else []
        by_id = {c.get("circuit_id"): c for c in circuits if isinstance(c, dict)}
        active_ok = all(
            by_id.get(cid, {}).get("status") == "active"
            and by_id[cid].get("vk_url") == f"/api/v1/circuits/{cid}/vk"
            and by_id[cid].get("metadata_url") == f"/api/v1/circuits/{cid}/metadata"
            and bool(by_id[cid].get("public_inputs"))
            and len(by_id[cid].get("public_outputs") or []) == 1
            and bool(by_id[cid].get("policy"))
            and by_id[cid].get("acir_available") is True
            for cid in V2_CIRCUITS
        )
        retired_ok = all(
            by_id.get(cid, {}).get("status") == "retired"
            and by_id[cid].get("superseded_by") == cid.replace("/v1.0.0", "/v2.0.0")
            and "vk_url" not in by_id[cid]
            for cid in V1_CIRCUITS
        )
        step1_ok = ok and active_ok and retired_ok
        results.append({
            "step": 1, "name": "GET /circuits/ lists the v2.0.0 circuits active (vk, metadata, policy) and v1.0.0 retired",
            "path": "/circuits/", "method": "GET", "authRequired": "none",
            "healthy": step1_ok,
            "statusCode": status_of(code),
            "responseData": {
                "statuses": {cid: c.get("status") for cid, c in by_id.items()},
                "policies": {cid: by_id.get(cid, {}).get("policy") for cid in V2_CIRCUITS},
            },
            "error": None if step1_ok else (
                f"catalog wrong (http={code}, v2 active={active_ok}, v1 retired={retired_ok})"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not step1_ok:
            return self._summarize(results, False)

        # ── Step 2: ACIR distribution for fairCrossRegistryFee/v2.0.0 ───
        acir_code, acir_len = await fetch_size(reg, f"/api/v1/circuits/{FEE}/acir")
        step2_ok = acir_code == "200" and acir_len > 32
        results.append({
            "step": 2, "name": "ACIR endpoint serves fairCrossRegistryFee/v2.0.0 bytecode",
            "path": "/circuits/{id}/acir", "method": "GET", "authRequired": "none",
            "healthy": step2_ok,
            "statusCode": status_of(acir_code),
            "responseData": {"acir_bytes": acir_len},
            "error": None if step2_ok else f"ACIR endpoint returned http={acir_code} bytes={acir_len}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 3: verification keys served for v2, not for v1 ─────────
        vk_sizes: Dict[str, Any] = {}
        for cid in V2_CIRCUITS:
            vk_code, vk_len = await fetch_size(reg, f"/api/v1/circuits/{cid}/vk")
            vk_sizes[cid] = {"http": vk_code, "bytes": vk_len}
        v1_vk_code, _ = await fetch_size(reg, "/api/v1/circuits/fairMarkupPolicy/v1.0.0/vk")
        step3_ok = (
            all(v["http"] == "200" and v["bytes"] >= _MIN_VK_BYTES for v in vk_sizes.values())
            and v1_vk_code == "404"
        )
        results.append({
            "step": 3, "name": "Every v2.0.0 verification key is served; a v1.0.0 key is not (404)",
            "path": "/circuits/{id}/vk", "method": "GET", "authRequired": "none",
            "healthy": step3_ok,
            "statusCode": 200 if step3_ok else 500,
            "responseData": {"v2": vk_sizes, "v1_fairMarkupPolicy_http": v1_vk_code},
            "error": None if step3_ok else "verification keys not served as expected",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 4: metadata with the policy in force ───────────────────
        ok, meta, code = await http_in_container(
            reg, "GET", f"/api/v1/circuits/{CONTENT_SAFETY}/metadata", timeout=10,
        )
        listed_policy = by_id.get(CONTENT_SAFETY, {}).get("policy")
        in_force = (meta or {}).get("policy_in_force") if isinstance(meta, dict) else None
        step4_ok = (
            ok and isinstance(meta, dict)
            and bool(meta.get("Statement"))
            and isinstance(in_force, dict)
            and in_force == listed_policy
            and (in_force.get("min_rejection_bps") or {}).get("rule") == "at_least"
        )
        results.append({
            "step": 4, "name": "GET /circuits/{id}/metadata carries the statement and the policy in force",
            "path": "/circuits/{id}/metadata", "method": "GET", "authRequired": "none",
            "healthy": step4_ok,
            "statusCode": status_of(code),
            "responseData": {"policy_in_force": in_force, "listed_policy": listed_policy},
            "error": None if step4_ok else f"metadata wrong (http={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 5: a proof is valid only for its own circuit ───────────
        ok_p, proof, code_p = await make_proof(reg, dev_jwt, FAIR_MARKUP, agent_did)
        cross_ok = False
        cross_status: Optional[str] = None
        cross_reason = ""
        if ok_p:
            ok, body, code = await submit(reg, agent_jwt, submission(FEE, proof, {
                "max_fee_bps": "50",
                "window_ref": "1",
                "total_volume": "30000",
                "total_fees": "150",
                # without a label the registry answers 422 before it looks at the proof
                "reference_label": (proof.get("public_inputs") or {}).get("reference_label", "flow-cross"),
            }))
            cross_status = (body or {}).get("status")
            cross_reason = str((body or {}).get("reason") or "")
            cross_ok = ok and cross_status == "failed" and bool(cross_reason)
        results.append({
            "step": 5, "name": "A fairMarkupPolicy proof submitted under fairCrossRegistryFee/v2.0.0 is not verified",
            "path": "/attestations/submit", "method": "POST", "authRequired": "agent",
            "healthy": cross_ok,
            "statusCode": 200 if cross_ok else status_of(code_p),
            "responseData": {"status": cross_status, "reason": cross_reason[:200]},
            "error": None if cross_ok else (
                f"generate-proof failed (http={code_p})" if not ok_p
                else f"cross-circuit proof answered status={cross_status}"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 6: create schedule (v2 accepted, v1 refused) ───────────
        ok, body, code = await http_in_container(
            reg, "POST", "/api/v1/attestations/schedules",
            body={"circuit_id": FAIR_MARKUP, "interval_hours": 1},
            jwt=agent_jwt, timeout=10,
        )
        schedule_id = (body or {}).get("id") if (ok and isinstance(body, dict)) else None
        next_due_at_initial = (body or {}).get("next_due_at") if (ok and isinstance(body, dict)) else None
        ok_v1, body_v1, code_v1 = await http_in_container(
            reg, "POST", "/api/v1/attestations/schedules",
            body={"circuit_id": "fairMarkupPolicy/v1.0.0", "interval_hours": 1},
            jwt=agent_jwt, timeout=10,
        )
        v1_detail = str((body_v1 or {}).get("detail") or "")
        v1_refused = (not ok_v1) and code_v1 == "400" and FAIR_MARKUP in v1_detail
        step6_ok = ok and bool(schedule_id) and bool(next_due_at_initial) and v1_refused
        results.append({
            "step": 6, "name": "Schedule a v2.0.0 circuit (1h interval); a v1.0.0 schedule is refused naming its successor",
            "path": "/attestations/schedules", "method": "POST", "authRequired": "agent",
            "healthy": step6_ok,
            "statusCode": status_of(code),
            "responseData": {
                "schedule_id": schedule_id,
                "next_due_at": next_due_at_initial,
                "v1_http": code_v1,
                "v1_detail": v1_detail[:160],
            },
            "error": None if step6_ok else f"schedule create failed or v1 accepted (http={code}, v1 http={code_v1})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not (ok and schedule_id and next_due_at_initial):
            return self._summarize(results, False)

        # ── Step 7: force overdue + cron emits exactly once (idempotent) ─
        # Push next_due_at into the past via direct UPDATE.
        sql = (
            f"UPDATE attestation_schedules "
            f"SET next_due_at = NOW() - INTERVAL '1 hour', "
            f"    last_reminder_at = NULL "
            f"WHERE id = '{schedule_id}';"
        )
        rc, out = run_psql_in_db_container(
            REG_DB_A, sql,
            db_name=None,
        )
        force_ok = (rc == 0)

        baseline_reminder = max(0, query_event_count(
            target.a_es_db_container, "AttestationDueReminder",
        ))
        ok1, body1, code1 = await http_in_container(
            reg, "POST",
            "/api/v1/attestations/admin/run-schedule-cron",
            body={}, jwt=dev_jwt, timeout=15,
        )
        first_processed = (body1 or {}).get("processed") if (ok1 and isinstance(body1, dict)) else None

        await _aio.sleep(1.5)
        post_reminder = max(0, query_event_count(
            target.a_es_db_container, "AttestationDueReminder",
        ))
        delta_first = post_reminder - baseline_reminder

        ok2, body2, code2 = await http_in_container(
            reg, "POST",
            "/api/v1/attestations/admin/run-schedule-cron",
            body={}, jwt=dev_jwt, timeout=15,
        )
        second_processed = (body2 or {}).get("processed") if (ok2 and isinstance(body2, dict)) else None

        step7_ok = (
            force_ok
            and ok1 and ok2
            and first_processed == 1
            and second_processed == 0
            and delta_first >= 1
        )
        results.append({
            "step": 7, "name": "Schedule cron emits exactly once (daily idempotency)",
            "path": "/attestations/admin/run-schedule-cron", "method": "POST",
            "authRequired": "developer",
            "healthy": step7_ok,
            "statusCode": status_of(code1),
            "responseData": {
                "first_processed": first_processed,
                "second_processed": second_processed,
                "delta_AttestationDueReminder": delta_first,
            },
            "error": None if step7_ok else (
                f"cron idempotency wrong "
                f"(1st={first_processed}, 2nd={second_processed}, delta={delta_first})"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 8: submit a fresh matching proof → next_due_at advanced ─
        # A proof counts once, so a new one is made: submit-side coupling should
        # advance next_due_at and clear last_reminder_at.
        sub = await prove_and_submit(reg, dev_jwt, agent_jwt, FAIR_MARKUP, agent_did)
        submit_ok = sub["verified"]
        att_id = sub["attestation_id"] if submit_ok else None

        # Read the schedule row from the public by-did endpoint and verify
        # next_due_at advanced beyond the forced past time.
        from urllib.parse import quote
        ok2, body2, code2 = await http_in_container(
            reg, "GET",
            f"/api/v1/agents/by-did/{quote(agent_did, safe='')}/attestation-schedules",
            timeout=10,
        )
        items = (body2 or {}).get("items", []) if (ok2 and isinstance(body2, dict)) else []
        schedule_row = next(
            (s for s in items if s.get("id") == schedule_id), None,
        )
        next_due_at_after = schedule_row.get("next_due_at") if schedule_row else None
        last_attestation_at = schedule_row.get("last_attestation_at") if schedule_row else None

        # Compare ISO timestamps lexicographically — works when both are UTC.
        advanced = bool(
            schedule_row
            and next_due_at_after
            and last_attestation_at
            and next_due_at_after > (next_due_at_initial or "")
        )
        step8_ok = submit_ok and advanced
        results.append({
            "step": 8, "name": "A verified fairMarkupPolicy/v2.0.0 proof advances next_due_at + sets last_attestation_at",
            "path": "/attestations/submit + by-did/{did}/attestation-schedules",
            "method": "POST+GET", "authRequired": "agent",
            "healthy": step8_ok,
            "statusCode": 200 if step8_ok else 500,
            "responseData": {
                "attestation_id": att_id,
                "next_due_at_initial": next_due_at_initial,
                "next_due_at_after": next_due_at_after,
                "last_attestation_at": last_attestation_at,
            },
            "error": None if step8_ok else (sub["error"] or "submit-side coupling did not advance schedule"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 9: list attestations filtered by circuit_id ────────────
        step9_ok = False
        if att_id:
            ok, body, code = await http_in_container(
                reg, "GET",
                f"/api/v1/attestations?circuit_id={FAIR_MARKUP}&limit=10",
                jwt=dev_jwt, timeout=10,
            )
            items = (body or {}).get("items", []) if (ok and isinstance(body, dict)) else []
            step9_ok = ok and any(
                isinstance(a, dict) and a.get("id") == att_id for a in items
            )
        results.append({
            "step": 9, "name": "List attestations filtered by circuit_id finds the verified v2 attestation",
            "path": "/attestations", "method": "GET", "authRequired": "developer",
            "healthy": step9_ok,
            "statusCode": 200 if step9_ok else 500,
            "responseData": {"found": step9_ok},
            "error": None if step9_ok else "filter missed our submission",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        self.flow_values = {
            "agent_did": agent_did,
            "schedule_id": schedule_id,
            "attestation_id_fair_markup": att_id,
            "delta_AttestationDueReminder": delta_first,
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
            "flow_name": "flow_zkp_new_circuits_complete",
            "success": flow_success and ok == total,
            "total_steps": total,
            "successful_steps": ok,
            "results": results,
            "flow_values": dict(self.flow_values),
        }
