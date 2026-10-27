"""ZKP Phase 6: Frontend surface — endpoint-only quality-gate flow.

Asserts the contracts that the new Vue views depend on are correct, plus
the SPA shell is served and the Oracle chapter content is bundled into
the dist. Visual UX verification is the user's manual smoke test post-batch
(per CLAUDE.md; autonomous mode cannot drive a browser).

Steps:
  1. GET /attestations (developer auth) returns the canonical list shape.
  2. By-did endpoint returns the agent-profile widget contract.
  3. Bundle endpoint exposes all 15 canonical fields.
  4. Signing-pubkey endpoint returns a 32-byte Ed25519 key.
  5. SPA shell at /ui returns HTTP 200 + index.html with #app marker.
  6. Bundled JS dist contains the new Oracle ch10 content marker
     (confirms `npm run build-quick` ran AFTER the markdown was edited).

Sandbox-only.
"""
from __future__ import annotations

import base64
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict
from urllib.parse import quote

from agentvault_registry.api_tests.base import APITestBase
from agentvault_registry.api_tests.multiframe_helpers import (
    get_target,
    login_admin, onboard_agent, get_agent_jwt,
    http_in_container, exec_in_container,
)
from agentvault_registry.api_tests.zkp_v2_helpers import FAIR_MARKUP, prove_and_submit

logger = logging.getLogger(__name__)

# Marker string from the new Oracle chapter 10 content — must match the
# exact text in `assets/docs/oracle/10_zkp_attestation.md`.
# The chapter's opening line since the §ZKV2 rewrite; no quote character, since it goes into a sh -c grep.
_ORACLE_CH10_MARKER = "Prove that a public policy limit held for a private figure"


class TestFlowZkpFrontend(APITestBase):
    CATEGORY_NAME = "flow_zkp_frontend"
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
        std["flow_tests"] = await self.test_zkp_frontend_flow(developer_token)
        return std

    async def test_zkp_frontend_flow(self, developer_token: str) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info("Starting ZKP Phase 6: Frontend Surface Flow (endpoint-only)")
        logger.info("=" * 60)

        target = get_target("sandbox")
        results = []
        ts = int(time.time()) % 100000

        # ── Setup: admin + agent (used by step 2) ───────────────────────
        ok_a, dev_jwt, det = await login_admin(target, "a")
        if not ok_a:
            results.append(self._fail_step(1, "List attestations", f"Admin login: {det}"))
            return self._summarize(results, False)

        # ── Step 1: GET /attestations returns canonical list shape ──────
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            "/api/v1/attestations?limit=5",
            jwt=dev_jwt, timeout=10,
        )
        items = (body or {}).get("items", []) if (ok and isinstance(body, dict)) else []
        list_keys_ok = (
            ok and isinstance(body, dict)
            and isinstance(body.get("items"), list)
            and "count" in body and "limit" in body and "offset" in body
        )
        # If items present, verify first row's shape matches AttestationRecord.
        sample = items[0] if items else None
        required_row_keys = {
            "id", "agent_did", "circuit_id", "verified", "submitted_at",
            "expires_at", "revoked_at",
        }
        row_shape_ok = sample is None or required_row_keys.issubset(set(sample.keys()))
        step1_ok = list_keys_ok and row_shape_ok
        results.append({
            "step": 1, "name": "GET /attestations returns canonical list shape",
            "path": "/attestations", "method": "GET", "authRequired": "developer",
            "healthy": step1_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "list_keys_ok": list_keys_ok,
                "items_count": len(items),
                "row_shape_ok": row_shape_ok,
            },
            "error": None if step1_ok else "list contract violated",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not step1_ok:
            return self._summarize(results, False)

        # ── Step 2: by-did widget contract ──────────────────────────────
        ok, agent_info, det = await onboard_agent(target, "a", dev_jwt, f"zkp-fe-{ts}")
        if not ok:
            results.append(self._fail_step(2, "by-did widget contract", f"Onboard: {det}"))
            return self._summarize(results, False)
        agent_did = agent_info["did"]
        ok_jwt, agent_jwt, det = await get_agent_jwt(
            target, "a", agent_info["client_id"], agent_info["client_secret"]
        )
        if not ok_jwt:
            results.append(self._fail_step(2, "by-did widget contract", f"Agent JWT: {det}"))
            return self._summarize(results, False)

        # Submit one real v2 proof so by-did has a verified attestation to return.
        sub = await prove_and_submit(target.a_registry_container, dev_jwt, agent_jwt, FAIR_MARKUP, agent_did)
        att_id = sub["attestation_id"] if sub["verified"] else None

        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            f"/api/v1/agents/by-did/{quote(agent_did, safe='')}/attestations",
            timeout=10,
        )
        widget_items = (body or {}).get("items", []) if (ok and isinstance(body, dict)) else []
        widget_ok = (
            ok and isinstance(body, dict)
            and bool(att_id)
            and any(
                isinstance(a, dict) and a.get("id") == att_id and a.get("verified") is True
                for a in widget_items
            )
        )
        results.append({
            "step": 2, "name": "by-did widget contract: GET returns the agent's attestation",
            "path": "/agents/by-did/{did}/attestations",
            "method": "GET", "authRequired": "none",
            "healthy": widget_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {"items_count": len(widget_items), "found": widget_ok},
            "error": None if widget_ok else (sub["error"] or "widget contract violated"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 3: bundle endpoint contract ────────────────────────────
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            f"/api/v1/attestations/{att_id}/bundle",
            timeout=10,
        )
        required_bundle_keys = {
            "attestation_id", "agent_did", "circuit_id", "circuit_version",
            "public_inputs", "proof_b64", "proof_hash", "verified",
            "submitted_at", "issuer_registry", "valid_until", "revoked",
            "signature_alg", "signature", "signature_pubkey_id",
        }
        bundle_ok = (
            ok and isinstance(body, dict)
            and required_bundle_keys.issubset(set(body.keys()))
            and bool(body.get("signature"))
        )
        results.append({
            "step": 3, "name": "Bundle endpoint exposes all 15 canonical fields",
            "path": "/attestations/{id}/bundle",
            "method": "GET", "authRequired": "none",
            "healthy": bundle_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {"required_field_count": len(required_bundle_keys)},
            "error": None if bundle_ok else "bundle contract violated",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 4: signing-pubkey contract ─────────────────────────────
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            "/api/v1/attestations/signing-pubkey",
            timeout=10,
        )
        try:
            pub_len = (
                len(base64.b64decode(body.get("pubkey_b64", "")))
                if isinstance(body, dict) else 0
            )
        except Exception:
            pub_len = 0
        pubkey_ok = (
            ok and isinstance(body, dict)
            and pub_len == 32
            and bool(body.get("pubkey_id"))
            and bool(body.get("issuer_registry"))
        )
        results.append({
            "step": 4, "name": "Signing-pubkey endpoint contract",
            "path": "/attestations/signing-pubkey",
            "method": "GET", "authRequired": "none",
            "healthy": pubkey_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {"pubkey_len_bytes": pub_len},
            "error": None if pubkey_ok else "signing-pubkey contract violated",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 5: SPA shell at /ui ────────────────────────────────────
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            "/ui",
            timeout=10,
        )
        # `/ui` returns index.html. The body is HTML; the helper falls back
        # to {"_raw": str_truncated} for non-JSON responses.
        body_raw: str = ""
        if isinstance(body, dict) and "_raw" in body:
            body_raw = body.get("_raw", "")
        elif isinstance(body, str):
            body_raw = body
        # The Vue SPA index.html starts with <!DOCTYPE html><html lang="en"...>.
        # http_in_container truncates body to ~300 chars; we accept either the
        # `<div id="app"` marker OR `<!DOCTYPE` + `<html` as proof the SPA shell
        # was served (vs an error page).
        spa_ok = (
            code == "200"
            and (
                "<div id=\"app\"" in body_raw
                or "id=app" in body_raw
                or ("<!DOCTYPE html>" in body_raw and "<html" in body_raw.lower())
            )
        )
        results.append({
            "step": 5, "name": "SPA shell /ui serves index.html (HTTP 200, app marker present)",
            "path": "/ui", "method": "GET", "authRequired": "none",
            "healthy": spa_ok,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "body_excerpt": body_raw[:120],
            },
            "error": None if spa_ok else f"SPA shell missing marker (http={code})",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 6: Oracle ch10 marker bundled into dist ────────────────
        # Search the served JS chunks for our unique marker string. If the
        # dist was rebuilt after the markdown was edited, the marker should
        # appear in one of the dist/assets/*.js files.
        # The frontend dist lives under the registry source tree at runtime:
        #   /app/src/agentvault_registry/static/new_registry_frontend/dist/assets/
        # (Dockerfile copies the registry source into /app/src, so the static
        # path is one level deeper than a naive guess.)
        rc, out = exec_in_container(
            target.a_registry_container,
            ["sh", "-c", (
                "find /app -path '*new_registry_frontend/dist/assets/*.js' "
                f"-exec grep -l '{_ORACLE_CH10_MARKER}' {{}} \\; 2>/dev/null | head -1 || true"
            )],
            10,
        )
        oracle_ok = rc == 0 and len(out.strip()) > 0
        results.append({
            "step": 6, "name": "Oracle ch10 marker is bundled into the dist JS",
            "path": "filesystem grep on dist/assets/*.js",
            "method": "EXEC", "authRequired": "none",
            "healthy": oracle_ok,
            "statusCode": 200 if oracle_ok else 500,
            "responseData": {"matching_file": out.strip()[:120] if oracle_ok else None},
            "error": None if oracle_ok else (
                "marker not found — frontend dist not rebuilt with updated ch10. "
                "Run `npm run build-quick` and `docker compose --build registry-test`."
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        self.flow_values = {
            "agent_did": agent_did,
            "attestation_id": att_id,
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
            "flow_name": "flow_zkp_frontend_complete",
            "success": flow_success and ok == total,
            "total_steps": total,
            "successful_steps": ok,
            "results": results,
            "flow_values": dict(self.flow_values),
        }
