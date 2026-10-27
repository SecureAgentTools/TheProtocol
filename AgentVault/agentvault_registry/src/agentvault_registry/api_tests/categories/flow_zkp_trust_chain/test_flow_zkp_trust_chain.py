"""ZKP Attestation trust-chain integration E2E flow (Phase 3, v2.0.0 circuits).

Every verified attestation here is a real v2 proof made by the target's own
/admin/tutorial/generate-proof (zkp_v2_helpers).

Asserts:
  - submit verified ⇒ +1 reputation (the agent's first verified attestation
    for the circuit that UTC day) and an EigenTrustSignal with the circuit's weight
  - dispute filing accepts attestation_ids and stores referenced_attestations
  - preview-slash-reduction returns factor < 1.0 when references are valid
  - revoke ⇒ AttestationReputationClawed + reverse EigenTrustSignal, and
    reputation_score -1 in the DB (the revoked attestation is the one that
    got the point)
  - slash-reduction factor returns to 1.0 once attestation is revoked
  - the governance count counts circuit-days, not rows: after the revoke,
    three more fairMarkupPolicy proofs and one accurateResourceUsagePolicy
    proof on the same UTC day are four verified rows and count 2; only the
    first proof of each circuit and day gets a reputation point, and the
    revoked first proof still holds its circuit's day, so the later
    fairMarkupPolicy proofs get none
  - the bonus applies exactly when that count reaches the threshold the
    registry reports (10 circuit-days in 30 days by default; one run cannot
    reach that with two provable circuits, so the flow checks the rule, not
    the multiplier)
  - MCP getAgentProfile passthrough includes recent_attestations

Sandbox-only. The flow waits out the last ten minutes before a UTC midnight
so its same-day assertions cannot straddle two days.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict
from urllib.parse import quote

from agentvault_registry.api_tests.base import APITestBase
from agentvault_registry.api_tests.multiframe_helpers import (
    REG_DB_A,
    get_target,
    login_admin, onboard_agent, get_agent_jwt,
    http_in_container, query_event_count,
    run_psql_in_db_container,
)
from agentvault_registry.api_tests.zkp_v2_helpers import (
    FAIR_MARKUP, RESOURCE_USAGE,
    prove_and_submit, status_of, wait_out_utc_midnight,
)

logger = logging.getLogger(__name__)


class TestFlowZkpTrustChain(APITestBase):
    CATEGORY_NAME = "flow_zkp_trust_chain"
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
        std["flow_tests"] = await self.test_zkp_trust_chain_flow(developer_token)
        return std

    async def _submit_one(self, target, dev_jwt: str, agent_jwt: str, circuit_id: str, agent_did: str) -> Dict[str, Any]:
        """A fresh real v2 proof for circuit_id and agent_did, submitted as that agent (zkp_v2_helpers.prove_and_submit)."""
        return await prove_and_submit(target.a_registry_container, dev_jwt, agent_jwt, circuit_id, agent_did)

    async def test_zkp_trust_chain_flow(self, developer_token: str) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info("Starting ZKP Attestation Trust-Chain Flow (Phase 3)")
        logger.info("=" * 60)

        target = get_target("sandbox")
        results = []
        ts = int(time.time()) % 100000
        # The reputation point and the governance count are per UTC day.
        slept = await wait_out_utc_midnight()
        if slept:
            logger.info(f"[flow_zkp_trust_chain] waited {slept:.0f}s past UTC midnight")

        # ── Setup: admin + defendant agent + complainant agent ──────────
        ok_a, dev_jwt, det = await login_admin(target, "a")
        if not ok_a:
            results.append(self._fail_step(1, "Submit attestation", f"Admin login: {det}"))
            return self._summarize(results, False)

        ok, def_info, det = await onboard_agent(target, "a", dev_jwt, f"zkp-tc-def-{ts}")
        if not ok:
            results.append(self._fail_step(1, "Submit attestation", f"Onboard def: {det}"))
            return self._summarize(results, False)
        defendant_did = def_info["did"]
        ok_jwt, def_jwt, det = await get_agent_jwt(
            target, "a", def_info["client_id"], def_info["client_secret"]
        )
        if not ok_jwt:
            results.append(self._fail_step(1, "Submit attestation", f"Def JWT: {det}"))
            return self._summarize(results, False)

        ok, comp_info, det = await onboard_agent(target, "a", dev_jwt, f"zkp-tc-comp-{ts}")
        if not ok:
            results.append(self._fail_step(1, "Submit attestation", f"Onboard comp: {det}"))
            return self._summarize(results, False)
        ok_jwt, comp_jwt, det = await get_agent_jwt(
            target, "a", comp_info["client_id"], comp_info["client_secret"]
        )
        if not ok_jwt:
            results.append(self._fail_step(1, "Submit attestation", f"Comp JWT: {det}"))
            return self._summarize(results, False)

        # ── Step 1: submit A1 → EigenTrustSignal emitted ────────────────
        baseline_signal = max(0, query_event_count(target.a_es_db_container, "EigenTrustSignal"))
        sub1 = await self._submit_one(target, dev_jwt, def_jwt, FAIR_MARKUP, defendant_did)
        att1 = sub1["attestation_id"] if sub1["verified"] else None
        rep_delta_a1 = sub1["response"].get("reputation_delta")
        # tiny grace for async event task
        import asyncio as _aio
        await _aio.sleep(1.0)
        post_signal = max(0, query_event_count(target.a_es_db_container, "EigenTrustSignal"))
        delta_signal_step1 = post_signal - baseline_signal
        step1_ok = bool(att1) and rep_delta_a1 == 1 and delta_signal_step1 >= 1
        results.append({
            "step": 1, "name": "Submit A1 (real fairMarkupPolicy/v2.0.0 proof) → verified, +1 reputation, EigenTrustSignal emitted",
            "path": "/attestations/submit", "method": "POST", "authRequired": "agent",
            "healthy": step1_ok,
            "statusCode": status_of(sub1["code"]),
            "responseData": {
                "attestation_id": att1,
                "reputation_delta": rep_delta_a1,
                "delta_EigenTrustSignal": delta_signal_step1,
            },
            "error": None if step1_ok else (sub1["error"] or "reputation point or signal missing"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not step1_ok:
            return self._summarize(results, False)

        # ── Step 2: complainant files dispute citing A1 ─────────────────
        ok, body, code = await http_in_container(
            target.a_registry_container, "POST", "/api/v1/disputes/",
            body={"defendant_did": defendant_did, "attestation_ids": [att1]},
            jwt=comp_jwt, timeout=10,
        )
        dispute_id = None
        if ok and isinstance(body, dict):
            dispute_id = body.get("id")
        step2_ok = ok and dispute_id is not None
        results.append({
            "step": 2, "name": "File dispute citing A1 (referenced_attestations stored)",
            "path": "/disputes/", "method": "POST", "authRequired": "agent",
            "healthy": step2_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {"dispute_id": dispute_id},
            "error": None if step2_ok else f"file dispute (http={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not step2_ok:
            return self._summarize(results, False)

        # ── Step 3: preview slash reduction → factor < 1.0 ──────────────
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            f"/api/v1/attestations/admin/disputes/{dispute_id}/preview-slash-reduction",
            jwt=dev_jwt, timeout=10,
        )
        factor_pre = (body or {}).get("slash_factor")
        eligible_pre = (body or {}).get("eligible_attestations")
        step3_ok = (
            ok and isinstance(factor_pre, (int, float))
            and factor_pre < 1.0
            and isinstance(eligible_pre, list)
            and att1 in eligible_pre
        )
        results.append({
            "step": 3, "name": "Preview slash factor with valid A1 → factor < 1.0",
            "path": "/attestations/admin/disputes/{id}/preview-slash-reduction",
            "method": "GET", "authRequired": "developer",
            "healthy": step3_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "slash_factor": factor_pre,
                "eligible_count": len(eligible_pre) if isinstance(eligible_pre, list) else 0,
            },
            "error": None if step3_ok else f"slash factor wrong (http={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 4: snapshot rep, revoke A1, assert claw-back events ────
        baseline_clawed = max(0, query_event_count(target.a_es_db_container, "AttestationReputationClawed"))
        baseline_signal_pre_revoke = max(0, query_event_count(target.a_es_db_container, "EigenTrustSignal"))

        rc, rep_pre = run_psql_in_db_container(
            REG_DB_A,
            f"SELECT reputation_score FROM agents WHERE did = '{defendant_did}';",
            db_name=None,
        )
        rep_pre_int = int(rep_pre.strip()) if rc == 0 and rep_pre.strip().lstrip("-").isdigit() else None

        ok, body, code = await http_in_container(
            target.a_registry_container, "POST",
            f"/api/v1/attestations/{att1}/revoke",
            body={"reason": f"trust-chain test @{ts}"},
            jwt=def_jwt, timeout=10,
        )
        await _aio.sleep(1.5)
        post_clawed = max(0, query_event_count(target.a_es_db_container, "AttestationReputationClawed"))
        post_signal_post_revoke = max(0, query_event_count(target.a_es_db_container, "EigenTrustSignal"))
        delta_clawed = post_clawed - baseline_clawed
        delta_signal_revoke = post_signal_post_revoke - baseline_signal_pre_revoke

        rc, rep_post = run_psql_in_db_container(
            REG_DB_A,
            f"SELECT reputation_score FROM agents WHERE did = '{defendant_did}';",
            db_name=None,
        )
        rep_post_int = int(rep_post.strip()) if rc == 0 and rep_post.strip().lstrip("-").isdigit() else None

        rep_delta = (
            (rep_pre_int - rep_post_int)
            if (rep_pre_int is not None and rep_post_int is not None)
            else None
        )
        step4_ok = (
            ok and delta_clawed >= 1
            and delta_signal_revoke >= 1   # reverse EigenTrustSignal
            and rep_delta == 1             # claw back -1 in DB
        )
        results.append({
            "step": 4, "name": "Revoke A1 → AttestationReputationClawed + reverse signal + reputation -1",
            "path": "/attestations/{id}/revoke", "method": "POST", "authRequired": "agent",
            "healthy": step4_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "delta_AttestationReputationClawed": delta_clawed,
                "delta_EigenTrustSignal_postRevoke": delta_signal_revoke,
                "rep_pre": rep_pre_int, "rep_post": rep_post_int, "rep_delta": rep_delta,
            },
            "error": None if step4_ok else "claw-back missing or rep not decremented",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 5: re-preview slash factor → 1.0 (revoked A1 excluded) ─
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            f"/api/v1/attestations/admin/disputes/{dispute_id}/preview-slash-reduction",
            jwt=dev_jwt, timeout=10,
        )
        factor_post = (body or {}).get("slash_factor")
        eligible_post = (body or {}).get("eligible_attestations")
        step5_ok = (
            ok and factor_post == 1.0
            and isinstance(eligible_post, list)
            and att1 not in eligible_post
        )
        results.append({
            "step": 5, "name": "Re-preview slash factor after revoke → 1.0 (no eligible refs)",
            "path": "/attestations/admin/disputes/{id}/preview-slash-reduction",
            "method": "GET", "authRequired": "developer",
            "healthy": step5_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "slash_factor": factor_post,
                "eligible_after_revoke": eligible_post,
            },
            "error": None if step5_ok else f"factor not 1.0 after revoke (got {factor_post})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 6: governance preview after the revoke → count 0, no bonus ─
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            f"/api/v1/attestations/admin/governance/preview-voting-power?agent_did={quote(defendant_did, safe='')}",
            jwt=dev_jwt, timeout=10,
        )
        # A1 is revoked and was the only verified attestation: the count is 0.
        below_threshold_ok = (
            ok and isinstance(body, dict)
            and body.get("recent_verified_attestations") == 0
            and body.get("bonus_eligible") is False
            and body.get("multiplier") == 1.0
        )
        results.append({
            "step": 6, "name": "Voting-power preview after the revoke → 0 circuit-days, no bonus",
            "path": "/attestations/admin/governance/preview-voting-power",
            "method": "GET", "authRequired": "developer",
            "healthy": below_threshold_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "recent_verified": (body or {}).get("recent_verified_attestations"),
                "bonus_eligible": (body or {}).get("bonus_eligible"),
                "multiplier": (body or {}).get("multiplier"),
            },
            "error": None if below_threshold_ok else "below-threshold preview wrong",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 7: three more fairMarkupPolicy proofs + one accurateResourceUsagePolicy ─
        # Same UTC day as A1. A1 (revoked) stays the first verified fairMarkupPolicy
        # attestation of the day, so the three get no point; the resource-usage
        # proof is the first of its circuit and gets one.
        submitted = []
        markup_deltas = []
        errors = []
        for _ in range(3):
            sub = await self._submit_one(target, dev_jwt, def_jwt, FAIR_MARKUP, defendant_did)
            if sub["verified"]:
                submitted.append(sub["attestation_id"])
                markup_deltas.append(sub["response"].get("reputation_delta"))
            else:
                errors.append(sub["error"])
        sub_ru = await self._submit_one(target, dev_jwt, def_jwt, RESOURCE_USAGE, defendant_did)
        ru_delta = sub_ru["response"].get("reputation_delta")
        if sub_ru["verified"]:
            submitted.append(sub_ru["attestation_id"])
        else:
            errors.append(sub_ru["error"])
        step7_ok = (
            len(submitted) == 4
            and all(d is None for d in markup_deltas)
            and ru_delta == 1
        )
        results.append({
            "step": 7, "name": "4 more verified proofs the same day: only the resource-usage one gets a point",
            "path": "/attestations/submit (×4)", "method": "POST", "authRequired": "agent",
            "healthy": step7_ok,
            "statusCode": 200 if step7_ok else 500,
            "responseData": {
                "submitted_count": len(submitted),
                "fair_markup_reputation_deltas": markup_deltas,
                "resource_usage_reputation_delta": ru_delta,
            },
            "error": None if step7_ok else (
                "; ".join(e for e in errors if e) or
                f"reputation points wrong (markup={markup_deltas}, resource usage={ru_delta})"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 8: governance count = circuit-days, not rows ───────────
        ok_rows, rows_body, _ = await http_in_container(
            target.a_registry_container, "GET",
            f"/api/v1/agents/by-did/{quote(defendant_did, safe='')}/attestations?verified=true&limit=50",
            timeout=10,
        )
        rows = (rows_body or {}).get("items", []) if (ok_rows and isinstance(rows_body, dict)) else []
        live_rows = [r for r in rows if isinstance(r, dict) and not r.get("revoked_at")]
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            f"/api/v1/attestations/admin/governance/preview-voting-power?agent_did={quote(defendant_did, safe='')}",
            jwt=dev_jwt, timeout=10,
        )
        count = (body or {}).get("recent_verified_attestations") if isinstance(body, dict) else None
        threshold = (body or {}).get("threshold_count") if isinstance(body, dict) else None
        eligible = (body or {}).get("bonus_eligible") if isinstance(body, dict) else None
        multiplier = (body or {}).get("multiplier") if isinstance(body, dict) else None
        rule_ok = (
            isinstance(threshold, int)
            and isinstance(count, int)
            and eligible is (count >= threshold)
            and isinstance(multiplier, (int, float))
            and ((float(multiplier) > 1.0) if eligible else (float(multiplier) == 1.0))
        )
        circuit_days_ok = (
            ok and step7_ok
            and len(live_rows) == 4
            and count == 2
            and rule_ok
        )
        results.append({
            "step": 8, "name": "Governance count = circuit-days: 4 verified rows on one day count 2; bonus follows the threshold",
            "path": "/attestations/admin/governance/preview-voting-power",
            "method": "GET", "authRequired": "developer",
            "healthy": circuit_days_ok,
            "statusCode": status_of(code),
            "responseData": {
                "verified_unrevoked_rows": len(live_rows),
                "recent_verified": count,
                "threshold_count": threshold,
                "bonus_eligible": eligible,
                "multiplier": multiplier,
            },
            "error": None if circuit_days_ok else (
                f"expected 4 live rows counting 2 circuit-days (rows={len(live_rows)}, count={count}, "
                f"threshold={threshold}, eligible={eligible}, multiplier={multiplier})"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 9: MCP getAgentProfile passthrough → recent_attestations ─
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            f"/api/v1/attestations/admin/mcp-passthrough/get-agent-profile?agent_did={quote(defendant_did, safe='')}",
            jwt=dev_jwt, timeout=10,
        )
        recent_atts = (body or {}).get("recent_attestations") if (ok and isinstance(body, dict)) else None
        step9_ok = (
            ok and isinstance(recent_atts, list)
            and len(recent_atts) >= 1
            and all(isinstance(a, dict) and "circuit_id" in a for a in recent_atts)
        )
        results.append({
            "step": 9, "name": "MCP getAgentProfile passthrough → recent_attestations populated",
            "path": "/attestations/admin/mcp-passthrough/get-agent-profile",
            "method": "GET", "authRequired": "developer",
            "healthy": step9_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {"recent_attestations_count": len(recent_atts) if isinstance(recent_atts, list) else 0},
            "error": None if step9_ok else "MCP profile missing recent_attestations",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 10: dispute with NO attestations → factor stays 1.0 ────
        ok, body, code = await http_in_container(
            target.a_registry_container, "POST", "/api/v1/disputes/",
            body={"defendant_did": defendant_did},
            jwt=comp_jwt, timeout=10,
        )
        dispute2_id = (body or {}).get("id") if (ok and isinstance(body, dict)) else None
        ok2, body2, code2 = await http_in_container(
            target.a_registry_container, "GET",
            f"/api/v1/attestations/admin/disputes/{dispute2_id}/preview-slash-reduction",
            jwt=dev_jwt, timeout=10,
        )
        step10_ok = (
            ok and ok2 and dispute2_id is not None
            and (body2 or {}).get("slash_factor") == 1.0
        )
        results.append({
            "step": 10, "name": "Dispute without referenced_attestations → factor = 1.0",
            "path": "/disputes/ + preview-slash-reduction",
            "method": "POST+GET", "authRequired": "developer",
            "healthy": step10_ok,
            "statusCode": int(code2) if code2.isdigit() else 500,
            "responseData": {
                "dispute_id": dispute2_id,
                "slash_factor": (body2 or {}).get("slash_factor"),
            },
            "error": None if step10_ok else "no-refs factor wrong",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        self.flow_values = {
            "defendant_did": defendant_did,
            "attestation_id_revoked": att1,
            "dispute_id_with_attestation": dispute_id,
            "dispute_id_no_attestation": dispute2_id,
            "submitted_count": len(submitted),
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
            "flow_name": "flow_zkp_trust_chain_complete",
            "success": flow_success and ok == total,
            "total_steps": total,
            "successful_steps": ok,
            "results": results,
            "flow_values": dict(self.flow_values),
        }
