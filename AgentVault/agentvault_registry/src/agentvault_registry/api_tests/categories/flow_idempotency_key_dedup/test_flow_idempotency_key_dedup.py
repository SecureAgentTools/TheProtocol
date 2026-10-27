"""Idempotency-Key dedup flow (AAA+ Phase VII, 2026-05-21).

Asserts §pass57 invariant on /teg/transfer:
  Step 1: POST with Idempotency-Key=X + body B → 200
  Step 2: POST with Idempotency-Key=X + body B (same) → cached 200 (no double-transfer)
  Step 3: POST with Idempotency-Key=X + body B' (different) → 422 (collision)

Verifies via TEG balance delta that exactly ONE transfer occurred.
"""
from __future__ import annotations

import logging
import secrets
import time
from decimal import Decimal
from typing import Any, Dict, Optional

import httpx

from agentvault_registry.api_tests.base import APITestBase
from agentvault_registry.api_tests.multiframe_helpers import (
    get_target, login_admin, onboard_agent, mint_to_agent,
    get_agent_jwt, teg_balance_for,
)

logger = logging.getLogger(__name__)


class TestFlowIdempotencyKeyDedup(APITestBase):
    CATEGORY_NAME = "flow_idempotency_key_dedup"
    flow_values: Dict[str, Any] = {}

    async def setup(self):
        await self.setup_category(self.CATEGORY_NAME)
        self.flow_values = {}

    async def teardown(self):
        return

    async def test_idempotency_key_dedup_flow(self, developer_token: str) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info("Starting Idempotency-Key Dedup Flow (§pass57 invariant)")
        logger.info("=" * 60)

        target = get_target("sandbox")
        results = []
        successful = 0
        total = 0
        idem_key = f"flow-idemp-{secrets.token_hex(8)}"

        try:
            # Setup: get admin token + onboard 2 agents + fund alice
            _ok, admin_jwt, _det = await login_admin(target, "a")
            _oka, _ainfo, _deta = await onboard_agent(target, "a", admin_jwt, name="alice-idemp")
            alice_did = _ainfo.get("did", ""); alice_cid = _ainfo.get("client_id", ""); alice_sec = _ainfo.get("client_secret", "")
            _okb, _binfo, _detb = await onboard_agent(target, "a", admin_jwt, name="bob-idemp")
            bob_did = _binfo.get("did", "")
            await mint_to_agent(target, "a", alice_did, "100")
            _okj, alice_jwt, _detj = await get_agent_jwt(target, "a", alice_cid, alice_sec)
            bal_pre = await teg_balance_for(target, "a", alice_did, admin_jwt)
        except Exception as e:
            return self._final([{
                "step": 1, "name": "setup",
                "healthy": False, "error": f"setup failed: {e!r}",
            }], 0, 1)

        base = self.base_url.rstrip("/")
        body_a = {"receiver_agent_id": bob_did, "amount": "5", "currency": "AVT"}
        body_b_different = {"receiver_agent_id": bob_did, "amount": "7", "currency": "AVT"}

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, verify=False) as client:
            # Step 1: first call with body_a + idem_key → expect 200
            total += 1
            try:
                r1 = await client.post(
                    f"{base}/api/v1/teg/transfer",
                    json=body_a,
                    headers={"Authorization": f"Bearer {alice_jwt}", "Idempotency-Key": idem_key},
                )
                ok = r1.status_code == 200
                results.append({
                    "step": total, "name": "POST /teg/transfer (first call)",
                    "method": "POST", "path": "/teg/transfer",
                    "statusCode": r1.status_code, "healthy": ok,
                    "responseData": r1.json() if ok else None,
                })
                if ok:
                    successful += 1
            except Exception as e:
                results.append({"step": total, "name": "first call", "healthy": False, "error": str(e)})
                return self._final(results, successful, total)

            # Step 2: same key + same body → expect cached 200
            total += 1
            try:
                r2 = await client.post(
                    f"{base}/api/v1/teg/transfer",
                    json=body_a,
                    headers={"Authorization": f"Bearer {alice_jwt}", "Idempotency-Key": idem_key},
                )
                ok = r2.status_code == 200
                results.append({
                    "step": total, "name": "POST /teg/transfer (cached replay)",
                    "method": "POST", "path": "/teg/transfer",
                    "statusCode": r2.status_code, "healthy": ok,
                })
                if ok:
                    successful += 1
            except Exception as e:
                results.append({"step": total, "name": "cached replay", "healthy": False, "error": str(e)})

            # Step 3: same key + DIFFERENT body → expect 422
            total += 1
            try:
                r3 = await client.post(
                    f"{base}/api/v1/teg/transfer",
                    json=body_b_different,
                    headers={"Authorization": f"Bearer {alice_jwt}", "Idempotency-Key": idem_key},
                )
                ok = r3.status_code == 422
                results.append({
                    "step": total, "name": "POST /teg/transfer (key collision — different body)",
                    "method": "POST", "path": "/teg/transfer",
                    "statusCode": r3.status_code, "healthy": ok,
                    "responseData": r3.json() if ok else None,
                    "expected": 422,
                })
                if ok:
                    successful += 1
            except Exception as e:
                results.append({"step": total, "name": "key collision", "healthy": False, "error": str(e)})

        # Step 4: verify exactly ONE transfer (balance delta = 5 not 10)
        total += 1
        try:
            bal_post = await teg_balance_for(target, "a", alice_did, admin_jwt)
            delta = Decimal(str(bal_pre)) - Decimal(str(bal_post))
            # Should be 5.025 (5 + 0.5% fee). Anything > 7 = dedup broke + 2 transfers fired.
            ok = delta < Decimal("7")
            results.append({
                "step": total, "name": "balance delta = 1 transfer (no double-spend)",
                "healthy": ok,
                "balance_pre": str(bal_pre),
                "balance_post": str(bal_post),
                "delta": str(delta),
            })
            if ok:
                successful += 1
        except Exception as e:
            results.append({"step": total, "name": "balance verify", "healthy": False, "error": str(e)})

        return self._final(results, successful, total)

    def _final(self, results, successful, total):
        return {
            "flow_name": "flow_idempotency_key_dedup_complete",
            "success": successful == total,
            "total_steps": total,
            "successful_steps": successful,
            "results": results,
            "flow_values": self.flow_values,
        }
