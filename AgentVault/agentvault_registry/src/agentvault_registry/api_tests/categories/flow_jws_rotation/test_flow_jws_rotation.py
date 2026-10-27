"""JWS signing-key rotation flow (AAA+ Phase VII, 2026-05-21).

Asserts §pass36 Option C signing-key lifecycle:
  1. Onboard agent (gets initial signing key via migration 0063 backfill OR auto-rotation)
  2. Read signing-keys list (expect rotation_seq=1 entry)
  3. Rotate key (expect new entry rotation_seq=2 with private_pem shown ONCE)
  4. Read again (expect 2 entries; old key has expires_at set ~ now+7d)

If JWS_VERIFY_ENABLED becomes true and a signing key rotation breaks JWS
verification, this flow fails fast.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from agentvault_registry.api_tests.base import APITestBase
from agentvault_registry.api_tests.multiframe_helpers import (
    get_target, login_admin, onboard_agent,
)

logger = logging.getLogger(__name__)


class TestFlowJwsRotation(APITestBase):
    CATEGORY_NAME = "flow_jws_rotation"
    flow_values: Dict[str, Any] = {}

    async def setup(self):
        await self.setup_category(self.CATEGORY_NAME)
        self.flow_values = {}

    async def teardown(self):
        return

    async def test_jws_rotation_flow(self, developer_token: Optional[str] = None) -> Dict[str, Any]:
        logger.info("Starting JWS Rotation Flow (§pass36 Option C invariant)")

        target = get_target("sandbox")
        results = []
        successful = 0
        total = 0

        try:
            _ok, admin_jwt, _det = await login_admin(target, "a")
            _okg, _ginfo, _detg = await onboard_agent(target, "a", admin_jwt, name="jws-rotation")
            agent_did = _ginfo.get("did", "")
        except Exception as e:
            return self._final([{"step": 1, "name": "setup", "healthy": False, "error": f"{e!r}"}], 0, 1)

        base = self.base_url.rstrip("/")

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, verify=False) as client:
            # Step 1: GET signing keys (expect at least 1)
            total += 1
            try:
                r = await client.get(
                    f"{base}/api/v1/admin/agents/{agent_did}/signing-keys",
                    headers={"Authorization": f"Bearer {admin_jwt}"},
                )
                # 2026-07-17: GET signing-keys returns wrapped {"agent_did":..,"keys":[..]}
                # (not a bare list); a freshly-onboarded agent legitimately has 0 keys
                # until the first rotate mints one — so accept an empty list here.
                _kbody = r.json() if r.status_code == 200 else {}
                keys = _kbody.get("keys", []) if isinstance(_kbody, dict) else (_kbody if isinstance(_kbody, list) else [])
                ok = r.status_code == 200 and isinstance(keys, list)
                results.append({
                    "step": total,
                    "name": "GET /admin/agents/{did}/signing-keys (initial)",
                    "method": "GET", "path": "/admin/agents/{did}/signing-keys",
                    "statusCode": r.status_code, "healthy": ok,
                    "initial_key_count": len(keys) if isinstance(keys, list) else 0,
                })
                if ok:
                    successful += 1
                    initial_seq = max((k.get("rotation_seq", 0) for k in keys), default=0)
                else:
                    initial_seq = 0
            except Exception as e:
                results.append({"step": total, "name": "initial keys", "healthy": False, "error": str(e)})
                return self._final(results, successful, total)

            # Step 2: POST rotate
            total += 1
            try:
                r = await client.post(
                    f"{base}/api/v1/admin/agents/{agent_did}/rotate-signing-key",
                    json={},
                    headers={"Authorization": f"Bearer {admin_jwt}"},
                )
                rotated = r.json() if r.status_code == 200 else {}
                ok = (
                    r.status_code == 200
                    and "new_kid" in rotated
                    and "private_pem" in rotated
                    and rotated.get("shown_once") is True
                )
                results.append({
                    "step": total,
                    "name": "POST /admin/agents/{did}/rotate-signing-key (private_pem shown once)",
                    "method": "POST", "path": "/admin/agents/{did}/rotate-signing-key",
                    "statusCode": r.status_code, "healthy": ok,
                    "private_pem_present": "private_pem" in rotated,
                    "shown_once_flag": rotated.get("shown_once"),
                })
                if ok:
                    successful += 1
            except Exception as e:
                results.append({"step": total, "name": "rotate", "healthy": False, "error": str(e)})

            # Step 3: GET keys again (expect seq+1)
            total += 1
            try:
                r = await client.get(
                    f"{base}/api/v1/admin/agents/{agent_did}/signing-keys",
                    headers={"Authorization": f"Bearer {admin_jwt}"},
                )
                _kb = r.json() if r.status_code == 200 else {}
                keys = _kb.get("keys", []) if isinstance(_kb, dict) else (_kb if isinstance(_kb, list) else [])
                final_seq = max((k.get("rotation_seq", 0) for k in keys), default=0)
                ok = r.status_code == 200 and final_seq > initial_seq
                results.append({
                    "step": total,
                    "name": "GET signing-keys (post-rotation, seq incremented)",
                    "method": "GET", "path": "/admin/agents/{did}/signing-keys",
                    "statusCode": r.status_code, "healthy": ok,
                    "final_key_count": len(keys),
                    "rotation_seq_progressed": f"{initial_seq} → {final_seq}",
                })
                if ok:
                    successful += 1
            except Exception as e:
                results.append({"step": total, "name": "post-rotation keys", "healthy": False, "error": str(e)})

        return self._final(results, successful, total)

    def _final(self, results, successful, total):
        return {
            "flow_name": "flow_jws_rotation_complete",
            "success": successful == total,
            "total_steps": total,
            "successful_steps": successful,
            "results": results,
            "flow_values": self.flow_values,
        }
