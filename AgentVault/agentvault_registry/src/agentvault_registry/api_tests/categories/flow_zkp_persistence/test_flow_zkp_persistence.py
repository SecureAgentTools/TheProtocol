"""ZKP attestation persistence end-to-end flow (Phase 1, v2.0.0 circuits).

Asserts that a verified attestation is durably persisted in the registry DB and
queryable by id, by agent DID and (negatively) by a bogus filter, that the
public re-verify runs bb again on the stored proof bytes, and what the
registry refuses:

  - a real fairMarkupPolicy/v2.0.0 proof (made by the target's own
    /admin/tutorial/generate-proof) verifies, and the submit answer carries
    the public values the proof was made for, its commitment included;
  - the same proof bytes submitted again answer HTTP 409;
  - the same proof under a changed public input is refused;
  - a v1.0.0 circuit id is refused as retired;
  - proof_of_reputation (Option B) is answered as not verified, and the
    re-verify of its proofless row says there is nothing to re-verify;
  - the proof's reference names the agent it was made for: its inputs without
    reference_label answer 422, and the same proof submitted by another agent
    is not verified, the reason naming another agent;
  - a proof with one element raised by the field order (the same proof to bb,
    other bytes to a replay check) is refused as non-canonical;
  - a second, different proof with the same circuit and reference (made inside
    the target with the first proof's label) answers 409: one verified
    attestation per circuit and reference.

Sandbox-only: relies on the api-tester's sandbox token acquisition and on the
target registry being able to prove (zkp_v2_helpers).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict
from urllib.parse import quote

from agentvault_registry.api_tests.base import APITestBase
from agentvault_registry.api_tests.multiframe_helpers import (
    get_target,
    login_admin, onboard_agent, get_agent_jwt,
    http_in_container,
)
from agentvault_registry.api_tests.zkp_v2_helpers import (
    FAIR_MARKUP, OPTION_B,
    carried_matches, offset_element, proof_sha256, prove_and_submit, prove_with_label,
    status_of, submission, submit,
)

logger = logging.getLogger(__name__)


class TestFlowZkpPersistence(APITestBase):
    CATEGORY_NAME = "flow_zkp_persistence"
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
        std["flow_tests"] = await self.test_zkp_persistence_flow(developer_token)
        return std

    async def test_zkp_persistence_flow(self, developer_token: str) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info("Starting ZKP Attestation Persistence Flow (Phase 1, v2.0.0)")
        logger.info("=" * 60)

        target = get_target("sandbox")
        reg = target.a_registry_container
        results = []
        ts = int(time.time()) % 100000

        # ── Step 1: setup + submit a real v2 proof ──────────────────────
        ok_a, dev_jwt, det = await login_admin(target, "a")
        if not ok_a:
            results.append(self._fail_step(1, "Submit attestation", f"Admin login failed: {det}"))
            return self._summarize(results, False)

        agent_label = f"zkp-pers-{ts}"
        ok, agent_info, det = await onboard_agent(target, "a", dev_jwt, agent_label)
        if not ok:
            results.append(self._fail_step(1, "Submit attestation", f"Onboard failed: {det}"))
            return self._summarize(results, False)

        agent_did = agent_info["did"]
        ok_jwt, agent_jwt, det = await get_agent_jwt(
            target, "a", agent_info["client_id"], agent_info["client_secret"]
        )
        if not ok_jwt:
            results.append(self._fail_step(1, "Submit attestation", f"Get agent JWT failed: {det}"))
            return self._summarize(results, False)

        sub = await prove_and_submit(reg, dev_jwt, agent_jwt, FAIR_MARKUP, agent_did)
        proof = sub["proof"]
        resp = sub["response"]
        attestation_id = sub["attestation_id"]
        values_ok = carried_matches(resp, proof)
        first_point = resp.get("reputation_delta") == 1
        submitted_ok = sub["verified"] and values_ok and first_point
        results.append({
            "step": 1, "name": "Submit a real fairMarkupPolicy/v2.0.0 proof: verified, carries its public values, +1 reputation",
            "path": "/attestations/submit", "method": "POST", "authRequired": "agent",
            "healthy": submitted_ok,
            "statusCode": status_of(sub["code"]),
            "responseData": {
                "attestation_id": attestation_id,
                "status": resp.get("status"),
                "proof_public_values_match": values_ok,
                "reputation_delta": resp.get("reputation_delta"),
                "agent_did": agent_did,
            },
            "error": None if submitted_ok else (
                sub["error"] or ("proof_public_values differ from the proof" if not values_ok
                                 else f"reputation_delta={resp.get('reputation_delta')} for the agent's first proof of the day, expected 1")
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not sub["verified"]:
            return self._summarize(results, False)

        # ── Step 2: GET /attestations/{id} → match ──────────────────────
        ok, body, code = await http_in_container(
            reg, "GET", f"/api/v1/attestations/{attestation_id}",
            jwt=dev_jwt, timeout=10,
        )
        expected_hash = proof_sha256(proof.get("proof_bytes_base64", ""))
        single_match = (
            ok
            and isinstance(body, dict)
            and body.get("id") == attestation_id
            and body.get("agent_did") == agent_did
            and body.get("circuit_id") == FAIR_MARKUP
            and body.get("circuit_version") == "v2.0.0"
            and body.get("verified") is True
            and body.get("proof_hash") == expected_hash
        )
        results.append({
            "step": 2, "name": "GET /attestations/{id} gives the record, its circuit and the sha256 of the proof",
            "path": "/attestations/{id}", "method": "GET", "authRequired": "developer",
            "healthy": single_match,
            "statusCode": status_of(code),
            "responseData": {
                "id": (body or {}).get("id"),
                "circuit_id": (body or {}).get("circuit_id"),
                "circuit_version": (body or {}).get("circuit_version"),
                "verified": (body or {}).get("verified"),
                "proof_hash_matches": (body or {}).get("proof_hash") == expected_hash,
            },
            "error": None if single_match else f"single GET mismatch (http={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 3: GET /attestations?agent_did=X&limit=10 ──────────────
        ok, body, code = await http_in_container(
            reg, "GET",
            f"/api/v1/attestations?agent_did={quote(agent_did, safe='')}&limit=10",
            jwt=dev_jwt, timeout=10,
        )
        items_list_dev = (body or {}).get("items", []) if (ok and isinstance(body, dict)) else []
        list_dev_ok = ok and any(
            isinstance(a, dict) and a.get("id") == attestation_id for a in items_list_dev
        )
        results.append({
            "step": 3, "name": "GET /attestations?agent_did=... lists our record",
            "path": "/attestations", "method": "GET", "authRequired": "developer",
            "healthy": list_dev_ok,
            "statusCode": status_of(code),
            "responseData": {
                "count_returned": len(items_list_dev) if isinstance(items_list_dev, list) else 0,
                "found_attestation_id": list_dev_ok,
            },
            "error": None if list_dev_ok else f"list-by-agent_did missing record (http={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 4: GET /agents/by-did/{did}/attestations (public) ──────
        ok, body, code = await http_in_container(
            reg, "GET",
            f"/api/v1/agents/by-did/{quote(agent_did, safe='')}/attestations",
            timeout=10,
        )
        items_by_did = (body or {}).get("items", []) if (ok and isinstance(body, dict)) else []
        by_did_ok = ok and any(
            isinstance(a, dict) and a.get("id") == attestation_id for a in items_by_did
        )
        results.append({
            "step": 4, "name": "GET /agents/by-did/{did}/attestations (public) lists our record",
            "path": "/agents/by-did/{did}/attestations", "method": "GET", "authRequired": "none",
            "healthy": by_did_ok,
            "statusCode": status_of(code),
            "responseData": {
                "count_returned": len(items_by_did) if isinstance(items_by_did, list) else 0,
                "found_attestation_id": by_did_ok,
            },
            "error": None if by_did_ok else f"by-did public listing missing record (http={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 5: GET /attestations/{id}/verify (public re-verify) ────
        ok, body, code = await http_in_container(
            reg, "GET",
            f"/api/v1/attestations/{attestation_id}/verify",
            timeout=30,
        )
        re_verified = (
            ok
            and isinstance(body, dict)
            and body.get("verified") is True
            and body.get("failure_reason") is None
            and bool(body.get("re_verified_at"))
            and body.get("attestation_id") == attestation_id
        )
        results.append({
            "step": 5, "name": "GET /attestations/{id}/verify runs bb again on the stored proof: verified",
            "path": "/attestations/{id}/verify", "method": "GET", "authRequired": "none",
            "healthy": re_verified,
            "statusCode": status_of(code),
            "responseData": {
                "verified": (body or {}).get("verified"),
                "failure_reason": (body or {}).get("failure_reason"),
                "re_verified_at": (body or {}).get("re_verified_at"),
            },
            "error": None if re_verified else f"re-verify mismatch (http={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 6: GET /attestations with bogus filter → 0 results ─────
        bogus_did = "did:theprotocol:zzz-not-a-real-agent-deadbeef"
        ok, body, code = await http_in_container(
            reg, "GET",
            f"/api/v1/attestations?agent_did={quote(bogus_did, safe='')}",
            jwt=dev_jwt, timeout=10,
        )
        bogus_items = (body or {}).get("items") if (ok and isinstance(body, dict)) else None
        bogus_count = (body or {}).get("count") if (ok and isinstance(body, dict)) else None
        empty_ok = (
            ok
            and isinstance(bogus_items, list)
            and len(bogus_items) == 0
            and bogus_count == 0
        )
        results.append({
            "step": 6, "name": "GET /attestations with bogus filter returns 0 items, no error",
            "path": "/attestations", "method": "GET", "authRequired": "developer",
            "healthy": empty_ok,
            "statusCode": status_of(code),
            "responseData": {
                "items_count": len(bogus_items) if isinstance(bogus_items, list) else None,
                "count_field": bogus_count,
            },
            "error": None if empty_ok else f"bogus-filter response wrong (http={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 7: the same proof bytes again → 409 ────────────────────
        ok, body, code = await submit(reg, agent_jwt, submission(FAIR_MARKUP, proof))
        replay_detail = str((body or {}).get("detail") or "")
        replay_ok = (not ok) and code == "409" and attestation_id in replay_detail
        results.append({
            "step": 7, "name": "The same proof submitted again answers 409 naming the first attestation",
            "path": "/attestations/submit", "method": "POST", "authRequired": "agent",
            "healthy": replay_ok,
            "statusCode": status_of(code),
            "responseData": {"detail": replay_detail[:200]},
            "error": None if replay_ok else f"replayed proof not refused with 409 (http={code}, status={(body or {}).get('status')})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 8: the same proof under a changed public input → refused ─
        stated = dict(proof.get("public_inputs") or {})
        stated["offered_price"] = str(int(stated.get("offered_price", "0")) + 1)
        ok, body, code = await submit(reg, agent_jwt, submission(FAIR_MARKUP, proof, stated))
        reason = str((body or {}).get("reason") or "")
        changed_ok = (
            ok
            and (body or {}).get("status") == "failed"
            and "offered_price" in reason
            and "differs from the value the proof was made for" in reason
        )
        results.append({
            "step": 8, "name": "The proof under a changed offered_price is refused (public input differs from the proof)",
            "path": "/attestations/submit", "method": "POST", "authRequired": "agent",
            "healthy": changed_ok,
            "statusCode": status_of(code),
            "responseData": {"status": (body or {}).get("status"), "reason": reason[:200]},
            "error": None if changed_ok else f"changed input not refused as expected (http={code}, reason={reason[:120]!r})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 9: a v1.0.0 circuit id → refused as retired ────────────
        v1_body = {
            "circuit_id": "fairMarkupPolicy/v1.0.0",
            "proof_data": {"proof_bytes": proof.get("proof_bytes_base64", ""), "format": "ultra_honk"},
            "public_inputs": {
                "policy_parameters_hash": "1",
                "self_attested_total_component_costs": "600",
                "offered_price": "720",
            },
        }
        ok, body, code = await submit(reg, agent_jwt, v1_body)
        reason = str((body or {}).get("reason") or "")
        retired_ok = ok and (body or {}).get("status") == "failed" and "retired" in reason
        results.append({
            "step": 9, "name": "A fairMarkupPolicy/v1.0.0 submission is refused as retired",
            "path": "/attestations/submit", "method": "POST", "authRequired": "agent",
            "healthy": retired_ok,
            "statusCode": status_of(code),
            "responseData": {"status": (body or {}).get("status"), "reason": reason[:200]},
            "error": None if retired_ok else (
                f"v1 not refused as retired (http={code}, reason={reason[:120]!r}); "
                "a registry that sets ZKP_ACCEPT_V1_CIRCUITS=true answers differently on purpose"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 10: Option B → not verified; its re-verify has nothing to run ─
        ok, body, code = await submit(reg, agent_jwt, {
            "circuit_id": OPTION_B,
            "proof_data": {"proof_bytes": "", "format": "option_b"},
            "public_inputs": {"reputation_threshold": 100, "agent_did": agent_did},
        })
        option_b_id = (body or {}).get("attestation_id")
        reason = str((body or {}).get("reason") or "")
        rv_ok, rv_body, rv_code = (False, {}, "000")
        if option_b_id:
            rv_ok, rv_body, rv_code = await http_in_container(
                reg, "GET", f"/api/v1/attestations/{option_b_id}/verify", timeout=15,
            )
        rv_reason = str((rv_body or {}).get("failure_reason") or "")
        option_b_ok = (
            ok
            and (body or {}).get("status") == "failed"
            and "nothing was proven" in reason
            and bool(option_b_id)
            and rv_ok
            and (rv_body or {}).get("verified") is False
            and "no proof bytes stored" in rv_reason
        )
        results.append({
            "step": 10, "name": "Option B (proof_of_reputation) is not a verified proof; re-verify of its proofless row says so",
            "path": "/attestations/submit + /attestations/{id}/verify", "method": "POST+GET",
            "authRequired": "agent",
            "healthy": option_b_ok,
            "statusCode": status_of(code),
            "responseData": {
                "status": (body or {}).get("status"),
                "reason": reason[:160],
                "attestation_id": option_b_id,
                "reverify_verified": (rv_body or {}).get("verified"),
                "reverify_failure_reason": rv_reason[:120],
            },
            "error": None if option_b_ok else f"Option B answer wrong (submit http={code}, re-verify http={rv_code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 11: no reference_label → 422 ────────────────────────────
        unlabelled = {k: v for k, v in (proof.get("public_inputs") or {}).items() if k != "reference_label"}
        ok, body, code = await submit(reg, agent_jwt, submission(FAIR_MARKUP, proof, unlabelled))
        detail = str((body or {}).get("detail") or "")
        no_label_ok = (not ok) and code == "422" and "reference_label" in detail
        results.append({
            "step": 11, "name": "The proof's inputs without reference_label answer 422",
            "path": "/attestations/submit", "method": "POST", "authRequired": "agent",
            "healthy": no_label_ok,
            "statusCode": status_of(code),
            "responseData": {"detail": detail[:200]},
            "error": None if no_label_ok else f"a submission without reference_label was not refused with 422 (http={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 12: the same proof submitted by another agent → not verified ─
        other_did = None
        other_ok, other_body, other_code = False, {}, "000"
        ok_o, other_info, det_o = await onboard_agent(target, "a", dev_jwt, f"zkp-pers-other-{ts}")
        if ok_o:
            other_did = other_info["did"]
            ok_oj, other_jwt, det_o = await get_agent_jwt(
                target, "a", other_info["client_id"], other_info["client_secret"]
            )
            if ok_oj:
                other_ok, other_body, other_code = await submit(reg, other_jwt, submission(FAIR_MARKUP, proof))
        reason = str((other_body or {}).get("reason") or "")
        foreign_ok = (
            other_ok
            and (other_body or {}).get("status") == "failed"
            and "another agent" in reason
        )
        results.append({
            "step": 12, "name": "The same proof submitted by another agent is not verified (the reference names its agent)",
            "path": "/attestations/submit", "method": "POST", "authRequired": "agent",
            "healthy": foreign_ok,
            "statusCode": status_of(other_code),
            "responseData": {
                "other_agent_did": other_did,
                "status": (other_body or {}).get("status"),
                "reason": reason[:200],
            },
            "error": None if foreign_ok else (
                f"second agent setup failed: {det_o}" if other_code == "000"
                else f"another agent's submission answered http={other_code}, status={(other_body or {}).get('status')}"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 13: one element raised by the field order → refused ────
        offset_b64 = offset_element(proof.get("proof_bytes_base64", ""))
        off_ok, off_body, off_code = False, {}, "000"
        if offset_b64:
            off_ok, off_body, off_code = await submit(
                reg, agent_jwt, submission(FAIR_MARKUP, {"proof_bytes_base64": offset_b64}, proof.get("public_inputs")),
            )
        reason = str((off_body or {}).get("reason") or "")
        offset_ok = off_ok and (off_body or {}).get("status") == "failed" and "non-canonical" in reason
        results.append({
            "step": 13, "name": "The proof with one element offset by the field order is refused as non-canonical",
            "path": "/attestations/submit", "method": "POST", "authRequired": "agent",
            "healthy": offset_ok,
            "statusCode": status_of(off_code),
            "responseData": {"status": (off_body or {}).get("status"), "reason": reason[:200]},
            "error": None if offset_ok else (
                "could not build the offset proof" if not offset_b64
                else f"offset proof answered http={off_code}, status={(off_body or {}).get('status')}, reason={reason[:120]!r}"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 14: the same circuit and reference again → 409 ─────────
        # generate-proof always picks a new label, so the second proof is made in
        # the target with the first proof's label: other bytes, the same reference.
        label = (proof.get("public_inputs") or {}).get("reference_label") or ""
        again_ok, again, again_code, again_detail = False, {}, "000", ""
        made_ok, again = await prove_with_label(reg, FAIR_MARKUP, agent_did, label)
        if made_ok:
            ok, body, again_code = await submit(reg, agent_jwt, submission(FAIR_MARKUP, again))
            again_detail = str((body or {}).get("detail") or "")
            again_ok = (
                (not ok) and again_code == "409" and attestation_id in again_detail
                and again.get("proof_bytes_base64") != proof.get("proof_bytes_base64")
            )
        results.append({
            "step": 14, "name": "A different proof with the same circuit and reference answers 409 naming the first attestation",
            "path": "/attestations/submit", "method": "POST", "authRequired": "agent",
            "healthy": again_ok,
            "statusCode": status_of(again_code),
            "responseData": {"reference_label": label, "detail": again_detail[:200]},
            "error": None if again_ok else (
                f"could not prove in the target: {str(again.get('error'))[:200]}" if not made_ok
                else f"same reference not refused with 409 (http={again_code})"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        self.flow_values = {
            "agent_did": agent_did,
            "attestation_id": attestation_id,
            "option_b_attestation_id": option_b_id,
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
            "flow_name": "flow_zkp_persistence_complete",
            "success": flow_success and ok == total,
            "total_steps": total,
            "successful_steps": ok,
            "results": results,
            "flow_values": dict(self.flow_values),
        }
