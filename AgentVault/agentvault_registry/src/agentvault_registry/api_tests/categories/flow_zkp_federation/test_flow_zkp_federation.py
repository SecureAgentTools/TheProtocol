"""ZKP Attestation cross-frame federation + signed bundles E2E flow (Phase 4).

The attestation is a real fairMarkupPolicy/v2.0.0 proof made by the target's
own /admin/tutorial/generate-proof (zkp_v2_helpers), so the bundle carries
proof bytes a third party can check with `bb verify` against the key served at
/api/v1/circuits/{id}/vk. verify-bundle itself checks the Ed25519 signature
only; it does not run bb.

Asserts:
  - sandbox B has the `attestations` schema (Phase-1 migration applied
    cross-frame — replication wiring is deferred but schema parity ships)
  - GET /attestations/{id}/bundle returns a fully-formed bundle with
    Ed25519 signature, issuer_registry, valid_until, and all required
    public fields, the submitted proof bytes, their sha256 as proof_hash and
    the public inputs as submitted
  - GET /attestations/signing-pubkey returns a 32-byte b64 Ed25519 pubkey
    with a stable pubkey_id
  - POST /api/v1/public/attestations/verify-bundle accepts the bundle
    and reports verified=true
  - tampering proof_b64 leaves signature invalid (bundle still parseable
    but signature does not cover the new payload → verified=false)
  - tampering signature alone produces verified=false
  - posting the bundle with an explicit `issuer_pubkey_b64` (the offline
    cross-registry verifier path) succeeds when the matching key is
    supplied and fails when a foreign key is supplied
  - the bundle returned by a second GET round-trips identically (signing
    is deterministic per Ed25519 spec — same input + same key = same sig)

Cross-frame replication of attestation rows themselves is NOT exercised
by this flow — schema parity is sufficient for Phase 4 ship.

Sandbox-only.
"""
from __future__ import annotations

import base64
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict

from agentvault_registry.api_tests.base import APITestBase
from agentvault_registry.api_tests.multiframe_helpers import (
    REG_DB_B,
    get_target,
    login_admin, onboard_agent, get_agent_jwt,
    http_in_container, run_psql_in_db_container,
)
from agentvault_registry.api_tests.zkp_v2_helpers import (
    FAIR_MARKUP, derive_reference, proof_sha256, prove_and_submit, status_of,
)

logger = logging.getLogger(__name__)


class TestFlowZkpFederation(APITestBase):
    CATEGORY_NAME = "flow_zkp_federation"
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
        std["flow_tests"] = await self.test_zkp_federation_flow(developer_token)
        return std

    async def test_zkp_federation_flow(self, developer_token: str) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info("Starting ZKP Attestation Federation+Bundles Flow (Phase 4)")
        logger.info("=" * 60)

        target = get_target("sandbox")
        results = []
        ts = int(time.time()) % 100000

        # ── Setup: admin + agent on sandbox A ───────────────────────────
        ok_a, dev_jwt, det = await login_admin(target, "a")
        if not ok_a:
            results.append(self._fail_step(1, "Submit attestation", f"Admin login: {det}"))
            return self._summarize(results, False)

        ok, agent_info, det = await onboard_agent(target, "a", dev_jwt, f"zkp-fed-{ts}")
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

        # ── Step 1: submit a real v2 proof on sandbox A ─────────────────
        sub = await prove_and_submit(target.a_registry_container, dev_jwt, agent_jwt, FAIR_MARKUP, agent_did)
        att_id = sub["attestation_id"] if sub["verified"] else None
        proof = sub["proof"]
        step1_ok = sub["verified"]
        results.append({
            "step": 1, "name": "Submit a real fairMarkupPolicy/v2.0.0 proof on sandbox A (verified)",
            "path": "/attestations/submit", "method": "POST", "authRequired": "agent",
            "healthy": step1_ok,
            "statusCode": status_of(sub["code"]),
            "responseData": {"attestation_id": att_id, "status": sub["response"].get("status")},
            "error": sub["error"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not step1_ok:
            return self._summarize(results, False)

        # ── Step 2: sandbox B schema parity (attestations table exists) ─
        rc, out = run_psql_in_db_container(
            REG_DB_B,
            "SELECT 1 FROM information_schema.tables WHERE table_name='attestations';",
            db_name=None,
        )
        sb_b_schema_ok = (rc == 0) and ("1" in out)
        results.append({
            "step": 2, "name": "Sandbox B has the `attestations` schema (Phase-1 migration replayed)",
            "path": "psql information_schema.tables",
            "method": "EXEC", "authRequired": "none",
            "healthy": sb_b_schema_ok,
            "statusCode": 200 if sb_b_schema_ok else 500,
            "responseData": {"rc": rc, "result": out.strip()[:60]},
            "error": None if sb_b_schema_ok else "sandbox B missing attestations table",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 3: GET signing-pubkey ─────────────────────────────────
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET", "/api/v1/attestations/signing-pubkey",
            timeout=10,
        )
        pubkey_b64 = (body or {}).get("pubkey_b64") if (ok and isinstance(body, dict)) else None
        pubkey_id = (body or {}).get("pubkey_id") if (ok and isinstance(body, dict)) else None
        try:
            pubkey_len = len(base64.b64decode(pubkey_b64)) if pubkey_b64 else 0
        except Exception:
            pubkey_len = 0
        step3_ok = ok and pubkey_len == 32 and bool(pubkey_id)
        results.append({
            "step": 3, "name": "GET /signing-pubkey returns 32-byte Ed25519 pubkey",
            "path": "/attestations/signing-pubkey",
            "method": "GET", "authRequired": "none",
            "healthy": step3_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {"pubkey_len": pubkey_len, "pubkey_id": pubkey_id},
            "error": None if step3_ok else "pubkey wrong size",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 4: GET bundle → has all canonical fields + signature ──
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET", f"/api/v1/attestations/{att_id}/bundle",
            timeout=10,
        )
        bundle = body if (ok and isinstance(body, dict)) else None
        required = [
            "attestation_id", "agent_did", "circuit_id", "circuit_version",
            "public_inputs", "proof_b64", "proof_hash", "verified",
            "submitted_at", "issuer_registry", "valid_until", "revoked",
            "signature_alg", "signature", "signature_pubkey_id",
        ]
        proof_b64 = proof.get("proof_bytes_base64", "")
        # The row keeps the stated inputs (reference_label included) with every proven
        # value, the commitment among them, in decimal; the reference names this agent.
        stored_expected = {**(proof.get("public_inputs") or {}), **(proof.get("public_outputs") or {})}
        bundle_inputs = (bundle or {}).get("public_inputs") or {}
        label = bundle_inputs.get("reference_label")
        names_agent = isinstance(label, str) and str(bundle_inputs.get("context")) == str(derive_reference(agent_did, label))
        carries_proof = (
            bundle is not None
            and bundle.get("proof_b64") == proof_b64
            and bundle.get("proof_hash") == proof_sha256(proof_b64)
            and bundle.get("verified") is True
            and bundle.get("circuit_id") == FAIR_MARKUP
            and bundle_inputs == stored_expected
            and names_agent
        )
        bundle_ok = (
            bundle is not None
            and all(k in bundle for k in required)
            and bundle.get("attestation_id") == att_id
            and bundle.get("signature_alg") == "Ed25519"
            and bool(bundle.get("signature"))
            and carries_proof
        )
        results.append({
            "step": 4, "name": "GET /{id}/bundle gives the full canonical bundle + signature + the submitted proof",
            "path": "/attestations/{id}/bundle",
            "method": "GET", "authRequired": "none",
            "healthy": bundle_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "missing_fields": [k for k in required if not (bundle and k in bundle)],
                "has_signature": bool(bundle and bundle.get("signature")),
                "carries_submitted_proof": carries_proof,
            },
            "error": None if bundle_ok else "bundle missing required fields",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not bundle_ok:
            return self._summarize(results, False)

        # ── Step 5: verify-bundle (local) → verified=true ──────────────
        ok, body, code = await http_in_container(
            target.a_registry_container, "POST",
            "/api/v1/public/attestations/verify-bundle",
            body={"bundle": bundle}, timeout=10,
        )
        v5_ok = ok and isinstance(body, dict) and body.get("verified") is True
        results.append({
            "step": 5, "name": "POST /public/verify-bundle (local pubkey path) → true",
            "path": "/public/attestations/verify-bundle",
            "method": "POST", "authRequired": "none",
            "healthy": v5_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "verified": (body or {}).get("verified"),
                "reason": (body or {}).get("reason"),
            },
            "error": None if v5_ok else f"verify failed (http={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 6: tamper proof_b64 → verify → false ──────────────────
        tampered = dict(bundle)
        tampered["proof_b64"] = "AAAAAA"  # bogus
        ok, body, code = await http_in_container(
            target.a_registry_container, "POST",
            "/api/v1/public/attestations/verify-bundle",
            body={"bundle": tampered}, timeout=10,
        )
        v6_ok = ok and isinstance(body, dict) and body.get("verified") is False
        results.append({
            "step": 6, "name": "Tamper proof_b64 → signature invalid → verified=false",
            "path": "/public/attestations/verify-bundle",
            "method": "POST", "authRequired": "none",
            "healthy": v6_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "verified": (body or {}).get("verified"),
                "reason": (body or {}).get("reason"),
            },
            "error": None if v6_ok else "tampered proof was accepted",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 7: tamper signature → verify → false ──────────────────
        tampered2 = dict(bundle)
        # flip a byte in the signature
        sig_bytes = bytearray(base64.b64decode(bundle["signature"]))
        sig_bytes[0] ^= 0xFF
        tampered2["signature"] = base64.b64encode(bytes(sig_bytes)).decode()
        ok, body, code = await http_in_container(
            target.a_registry_container, "POST",
            "/api/v1/public/attestations/verify-bundle",
            body={"bundle": tampered2}, timeout=10,
        )
        v7_ok = ok and isinstance(body, dict) and body.get("verified") is False
        results.append({
            "step": 7, "name": "Tamper signature byte → verified=false",
            "path": "/public/attestations/verify-bundle",
            "method": "POST", "authRequired": "none",
            "healthy": v7_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "verified": (body or {}).get("verified"),
                "reason": (body or {}).get("reason"),
            },
            "error": None if v7_ok else "tampered signature was accepted",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 8: explicit issuer_pubkey_b64 path (cross-registry) ───
        ok, body, code = await http_in_container(
            target.a_registry_container, "POST",
            "/api/v1/public/attestations/verify-bundle",
            body={"bundle": bundle, "issuer_pubkey_b64": pubkey_b64},
            timeout=10,
        )
        v8_ok = ok and isinstance(body, dict) and body.get("verified") is True

        # And the negative — supplying a foreign pubkey must reject.
        # Use a fresh-generated 32-byte pubkey (32 0xAA bytes is invalid as
        # Ed25519 in some encodings but a deterministic mismatch test
        # uses a clearly foreign key). We use 32 bytes of 0x42 to be safe.
        foreign_b64 = base64.b64encode(b"\x42" * 32).decode("ascii")
        ok2, body2, code2 = await http_in_container(
            target.a_registry_container, "POST",
            "/api/v1/public/attestations/verify-bundle",
            body={"bundle": bundle, "issuer_pubkey_b64": foreign_b64},
            timeout=10,
        )
        v8_neg_ok = ok2 and isinstance(body2, dict) and body2.get("verified") is False

        step8_ok = v8_ok and v8_neg_ok
        results.append({
            "step": 8, "name": "Explicit issuer_pubkey_b64 path: same key OK, foreign key rejected",
            "path": "/public/attestations/verify-bundle",
            "method": "POST", "authRequired": "none",
            "healthy": step8_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "matching_key_verified": (body or {}).get("verified"),
                "foreign_key_verified": (body2 or {}).get("verified"),
            },
            "error": None if step8_ok else "issuer_pubkey paths wrong",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 9: deterministic signing — second GET returns same sig ─
        ok, body2, code = await http_in_container(
            target.a_registry_container, "GET", f"/api/v1/attestations/{att_id}/bundle",
            timeout=10,
        )
        bundle2 = body2 if (ok and isinstance(body2, dict)) else {}
        # Ed25519 is deterministic per RFC 8032 — same key, same payload, same sig.
        signature_stable = (
            bundle.get("signature") == bundle2.get("signature")
            and bundle.get("signature_pubkey_id") == bundle2.get("signature_pubkey_id")
        )
        results.append({
            "step": 9, "name": "Bundle is round-trip identical (deterministic Ed25519)",
            "path": "/attestations/{id}/bundle",
            "method": "GET", "authRequired": "none",
            "healthy": signature_stable,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "first_sig_prefix": (bundle.get("signature") or "")[:24],
                "second_sig_prefix": (bundle2.get("signature") or "")[:24],
                "stable": signature_stable,
            },
            "error": None if signature_stable else "signatures differ across calls",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        self.flow_values = {
            "agent_did": agent_did,
            "attestation_id": att_id,
            "bundle_signature_prefix": bundle.get("signature", "")[:32],
            "pubkey_id": pubkey_id,
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
            "flow_name": "flow_zkp_federation_complete",
            "success": flow_success and ok == total,
            "total_steps": total,
            "successful_steps": ok,
            "results": results,
            "flow_values": dict(self.flow_values),
        }
