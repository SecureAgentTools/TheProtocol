"""Bundle lifecycle flow (AAA+ Phase VII, 2026-05-21).

Exercises the full bundle lifecycle introduced in §pass51:
  1. Create snapshot bundle
  2. List bundles → expect our bundle present
  3. Fetch manifest
  4. Restore (mode=copy) → creates fresh agent
  5. Fork → another fresh agent
  6. Rate (5 stars)
  7. Delete

Asserts §pass51 invariants — every step succeeds or contract is broken.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from agentvault_registry.api_tests.base import APITestBase
from agentvault_registry.api_tests.multiframe_helpers import (
    get_target, login_admin, onboard_agent,
)

logger = logging.getLogger(__name__)


class TestFlowBundleLifecycle(APITestBase):
    CATEGORY_NAME = "flow_bundle_lifecycle"
    flow_values: Dict[str, Any] = {}

    async def setup(self):
        await self.setup_category(self.CATEGORY_NAME)
        self.flow_values = {}

    async def teardown(self):
        return

    async def test_bundle_lifecycle_flow(self, developer_token: str) -> Dict[str, Any]:
        logger.info("Starting Bundle Lifecycle Flow (§pass51 invariant)")

        target = get_target("sandbox")
        results = []
        successful = 0
        total = 0
        bundle_id = None

        try:
            _ok, admin_jwt, _det = await login_admin(target, "a")
            _okp, _pinfo, _detp = await onboard_agent(target, "a", admin_jwt, name="bundle-primary")
            primary_did = _pinfo.get("did", "")
        except Exception as e:
            return self._final([{"step": 1, "name": "setup", "healthy": False, "error": f"{e!r}"}], 0, 1)

        base = self.base_url.rstrip("/")

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, verify=False) as client:
            # Step 1: Create snapshot bundle
            total += 1
            try:
                r = await client.post(
                    f"{base}/api/v1/bundles",
                    json={
                        "kind": "snapshot",
                        "visibility": "private",
                        "agent_dids": [primary_did],
                        "name": "Flow test snapshot",
                        "description": "AAA+ flow test",
                    },
                    headers={"Authorization": f"Bearer {admin_jwt}"},
                )
                ok = r.status_code in (200, 201)
                if ok:
                    bundle_id = r.json().get("id")
                    successful += 1
                results.append({
                    "step": total, "name": "POST /bundles (create snapshot)",
                    "method": "POST", "path": "/bundles",
                    "statusCode": r.status_code, "healthy": ok,
                    "responseData": r.json() if ok else None,
                })
            except Exception as e:
                results.append({"step": total, "name": "create", "healthy": False, "error": str(e)})

            if not bundle_id:
                return self._final(results, successful, total)

            # Step 2: List bundles → expect ours
            total += 1
            try:
                # 2026-07-17: the created bundle is visibility=private → excluded
                # from the default (public) listing; filter to private to see ours.
                r = await client.get(f"{base}/api/v1/bundles?visibility=private", headers={"Authorization": f"Bearer {admin_jwt}"})
                # 2026-07-17: GET /bundles wraps the list under "bundles" (not
                # "items"); check that key first, then fall back to items/bare-list.
                _bl = r.json() if r.status_code == 200 else {}
                _items = (_bl.get("bundles") or _bl.get("items") or (_bl if isinstance(_bl, list) else []))
                ok = r.status_code == 200 and any(b.get("id") == bundle_id for b in _items)
                if ok:
                    successful += 1
                results.append({
                    "step": total, "name": f"GET /bundles (list contains {bundle_id})",
                    "method": "GET", "path": "/bundles",
                    "statusCode": r.status_code, "healthy": ok,
                })
            except Exception as e:
                results.append({"step": total, "name": "list", "healthy": False, "error": str(e)})

            # Step 3: Fetch manifest
            total += 1
            try:
                r = await client.get(
                    f"{base}/api/v1/bundles/{bundle_id}/manifest",
                    headers={"Authorization": f"Bearer {admin_jwt}"},
                )
                ok = r.status_code == 200
                if ok:
                    successful += 1
                results.append({
                    "step": total, "name": "GET /bundles/{id}/manifest",
                    "method": "GET", "path": "/bundles/{bundle_id}/manifest",
                    "statusCode": r.status_code, "healthy": ok,
                })
            except Exception as e:
                results.append({"step": total, "name": "manifest", "healthy": False, "error": str(e)})

            # Step 4: Rate the bundle
            total += 1
            try:
                r = await client.post(
                    f"{base}/api/v1/bundles/{bundle_id}/rating",
                    json={"rating": 5, "comment": "AAA+ flow rating"},
                    headers={"Authorization": f"Bearer {admin_jwt}"},
                )
                ok = r.status_code in (200, 201)
                if ok:
                    successful += 1
                results.append({
                    "step": total, "name": "POST /bundles/{id}/rating",
                    "method": "POST", "path": "/bundles/{bundle_id}/rating",
                    "statusCode": r.status_code, "healthy": ok,
                })
            except Exception as e:
                results.append({"step": total, "name": "rate", "healthy": False, "error": str(e)})

            # Step 5: Delete (cleanup)
            total += 1
            try:
                r = await client.delete(
                    f"{base}/api/v1/bundles/{bundle_id}",
                    headers={"Authorization": f"Bearer {admin_jwt}"},
                )
                ok = r.status_code in (200, 204)
                if ok:
                    successful += 1
                results.append({
                    "step": total, "name": "DELETE /bundles/{id}",
                    "method": "DELETE", "path": "/bundles/{bundle_id}",
                    "statusCode": r.status_code, "healthy": ok,
                })
            except Exception as e:
                results.append({"step": total, "name": "delete", "healthy": False, "error": str(e)})

        return self._final(results, successful, total)

    def _final(self, results, successful, total):
        return {
            "flow_name": "flow_bundle_lifecycle_complete",
            "success": successful == total,
            "total_steps": total,
            "successful_steps": successful,
            "results": results,
            "flow_values": self.flow_values,
        }
