"""Coordinated Suspension End-to-End Flow.

Tests Phase 6's 3-lever invariant: a single bulk/suspend call must fire
registry status flip + IRONHAND mTLS revoke + TEG account suspend in one
atomic admin action, observably.

Catches:
  • Lever skew — e.g., registry-suspended-but-TEG-still-active gap
  • SPIRE entry not deleted on revoke
  • TEG account_status not updated
  • AgentSuspended event not emitted (reactor pipeline gap)
  • Reinstate path not symmetric (re-enroll mTLS, reactivate TEG)

Sandbox-only.

Flow:
  1.  admin login
  2.  onboard fresh agent (active, no mTLS yet)
  3.  agent enables mTLS (POST /agent/enable-mtls) — agent JWT
  4.  pre-state: GET /admin/agents/{did} — assert active + mtls_enabled + spiffe_id
  5.  POST /admin/agents/bulk/suspend [did] — assert response shows
      registry=True, mtls=revoked, teg=suspended in lever breakdown
  6.  post-suspend: GET /admin/agents/{did} — assert suspended + !mtls_enabled +
      !spiffe_id
  7.  EventStore: AgentSuspended event count delta ≥ 1
  8.  POST /admin/agents/bulk/reinstate [did] — assert response shows
      registry=True, mtls=enrolled, teg=reinstated
  9.  post-reinstate: GET /admin/agents/{did} — assert active + mtls_enabled +
      spiffe_id (re-enrolled fresh)
  10. EventStore: AgentReinstated event count delta ≥ 1

Each step records its own probe so a partial pass is observable per-lever.
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
    login_admin, onboard_agent, get_agent_jwt,
    query_event_count, http_in_container,
)

logger = logging.getLogger(__name__)


class TestFlowCoordinatedSuspension(APITestBase):
    CATEGORY_NAME = "flow_coordinated_suspension"
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
        std["flow_tests"] = await self.test_coordinated_suspension_flow(developer_token)
        return std

    async def test_coordinated_suspension_flow(self, developer_token: str) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info("Starting Coordinated Suspension End-to-End Flow")
        logger.info("=" * 60)

        target = get_target("sandbox")
        results = []
        ts = int(time.time()) % 100000
        REASON = f"flow_coordinated_suspension_complete {ts} — quality gate"

        # Step 0: admin login
        ok_a, dev_jwt, det = await login_admin(target, "a")
        if not ok_a:
            results.append(self._fail_step(1, "Admin login", det))
            return self._summarize(results, False)

        # Snapshot baseline event counts
        baseline_susp = max(0, query_event_count(target.a_es_db_container, "AgentSuspended"))
        baseline_rein = max(0, query_event_count(target.a_es_db_container, "AgentReinstated"))

        # Step 1: onboard fresh agent
        ok, agent_info, det = await onboard_agent(
            target, "a", dev_jwt, f"coord-susp-{ts}",
        )
        results.append({
            "step": 1, "name": f"Onboard coord-susp-{ts}",
            "path": "/onboard/create_agent", "method": "POST", "authRequired": "developer",
            "healthy": ok, "statusCode": 200 if ok else 500,
            "responseData": {
                "did": (agent_info or {}).get("did", "")[:30] + "..." if ok else None,
                "detail": det,
            },
            "error": None if ok else det,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not ok:
            return self._summarize(results, False)

        agent_did = agent_info["did"]

        # Step 2: get agent JWT (needed to enable mTLS)
        ok_jwt, agent_jwt, det = await get_agent_jwt(
            target, "a",
            agent_info["client_id"],
            agent_info["client_secret"],
        )
        if not ok_jwt:
            results.append(self._fail_step(2, "Get agent JWT", det))
            return self._summarize(results, False)

        # Step 3: enable mTLS (sets up SPIRE entry + spiffe_id)
        ok, body, code = await http_in_container(
            target.a_registry_container, "POST",
            "/api/v1/agent/enable-mtls",
            jwt=agent_jwt, timeout=30,
        )
        spiffe_id = (body or {}).get("spiffe_id") if isinstance(body, dict) else None
        mtls_enrolled = ok and bool(spiffe_id)
        results.append({
            "step": 2, "name": "Enable mTLS (SPIRE enrollment)",
            "path": "/agent/enable-mtls", "method": "POST", "authRequired": "agent",
            "healthy": mtls_enrolled,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {"spiffe_id": (spiffe_id or "")[:50], "raw": str(body)[:120]},
            "error": None if mtls_enrolled else f"http={code} no_spiffe_id",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not mtls_enrolled:
            return self._summarize(results, False)

        # Step 4: pre-state probe via admin agent detail
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            f"/api/v1/admin/agents/{agent_did}",
            jwt=dev_jwt, timeout=15,
        )
        pre_status = (body or {}).get("status") if isinstance(body, dict) else None
        pre_mtls = bool((body or {}).get("mtls_enabled")) if isinstance(body, dict) else False
        pre_spiffe = (body or {}).get("spiffe_id") if isinstance(body, dict) else None
        pre_correct = (
            ok and pre_status == "active" and pre_mtls and bool(pre_spiffe)
        )
        results.append({
            "step": 3, "name": "Pre-state: active + mTLS enrolled + SPIFFE id present",
            "path": "/admin/agents/{did}", "method": "GET", "authRequired": "developer",
            "healthy": pre_correct,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "status": pre_status, "mtls_enabled": pre_mtls,
                "spiffe_id": (pre_spiffe or "")[:50],
            },
            "error": None if pre_correct else f"pre-state wrong: status={pre_status} mtls={pre_mtls} spiffe={bool(pre_spiffe)}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not pre_correct:
            return self._summarize(results, False)

        # Step 5: bulk/suspend — the 3-lever atomic action
        ok, body, code = await http_in_container(
            target.a_registry_container, "POST",
            "/api/v1/admin/agents/bulk/suspend",
            body={"agent_dids": [agent_did], "reason": REASON, "soft_suspend": False},
            jwt=dev_jwt, timeout=60,
        )
        per_agent = []
        if ok and isinstance(body, dict):
            per_agent = body.get("results", []) or []
        first = per_agent[0] if per_agent else {}
        suspend_reason = (first.get("reason") or "") if isinstance(first, dict) else ""
        # Lever breakdown is in the reason: "registry=True mtls=revoked teg=suspended"
        registry_ok = "registry=True" in suspend_reason or "registry=true" in suspend_reason.lower()
        mtls_revoked_ok = "mtls=revoked" in suspend_reason
        teg_suspended_ok = "teg=suspended" in suspend_reason
        all_three = registry_ok and mtls_revoked_ok and teg_suspended_ok
        results.append({
            "step": 4, "name": "bulk/suspend — all 3 levers fire (registry+mTLS+TEG)",
            "path": "/admin/agents/bulk/suspend", "method": "POST", "authRequired": "developer",
            "healthy": ok and all_three,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "registry_flipped": registry_ok,
                "mtls_revoked": mtls_revoked_ok,
                "teg_suspended": teg_suspended_ok,
                "lever_reason": suspend_reason[:120],
                "agg_mtls_revoked": (body or {}).get("mtls_revoked"),
                "agg_teg_suspended": (body or {}).get("teg_suspended"),
            },
            "error": None if (ok and all_three) else (
                f"lever skew — registry={registry_ok} mtls={mtls_revoked_ok} teg={teg_suspended_ok}"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Step 6: post-suspend admin probe — assert state actually changed
        await asyncio.sleep(2)
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            f"/api/v1/admin/agents/{agent_did}",
            jwt=dev_jwt, timeout=15,
        )
        post_status = (body or {}).get("status") if isinstance(body, dict) else None
        post_mtls = bool((body or {}).get("mtls_enabled")) if isinstance(body, dict) else True
        post_spiffe = (body or {}).get("spiffe_id") if isinstance(body, dict) else None
        post_correct = (
            ok and post_status == "suspended" and not post_mtls and not post_spiffe
        )
        results.append({
            "step": 5, "name": "Post-suspend: status=suspended + mTLS off + SPIFFE cleared",
            "path": "/admin/agents/{did}", "method": "GET", "authRequired": "developer",
            "healthy": post_correct,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "status": post_status, "mtls_enabled": post_mtls,
                "spiffe_id": (post_spiffe or "(null)")[:50],
            },
            "error": None if post_correct else (
                f"post-suspend wrong: status={post_status} mtls={post_mtls} spiffe={bool(post_spiffe)}"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Step 7: AgentSuspended event count increased
        post_susp = max(0, query_event_count(target.a_es_db_container, "AgentSuspended"))
        delta_susp = post_susp - baseline_susp
        events_correct = delta_susp >= 1
        results.append({
            "step": 6, "name": "EventStore: AgentSuspended event delta ≥ 1",
            "path": "/admin/eventstore-stats", "method": "GET", "authRequired": "developer",
            "healthy": events_correct,
            "statusCode": 200,
            "responseData": {
                "delta_AgentSuspended": delta_susp,
                "baseline": baseline_susp,
                "post": post_susp,
            },
            "error": None if events_correct else (
                f"event emission gap: AgentSuspended delta={delta_susp} (should be ≥1)"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Step 8: bulk/reinstate — symmetric reverse
        ok, body, code = await http_in_container(
            target.a_registry_container, "POST",
            "/api/v1/admin/agents/bulk/reinstate",
            body={"agent_dids": [agent_did], "reason": f"reinstate {ts}", "soft_reinstate": False},
            jwt=dev_jwt, timeout=60,
        )
        per_agent = (body or {}).get("results", []) if isinstance(body, dict) else []
        first = per_agent[0] if per_agent else {}
        reinstate_reason = (first.get("reason") or "") if isinstance(first, dict) else ""
        reg_ok = "registry=True" in reinstate_reason or "registry=true" in reinstate_reason.lower()
        mtls_re_ok = "mtls=enrolled" in reinstate_reason or "mtls=already_enrolled" in reinstate_reason
        teg_re_ok = "teg=reinstated" in reinstate_reason or "teg=already_active" in reinstate_reason
        all_three_re = reg_ok and mtls_re_ok and teg_re_ok
        results.append({
            "step": 7, "name": "bulk/reinstate — all 3 levers reverse (registry+mTLS+TEG)",
            "path": "/admin/agents/bulk/reinstate", "method": "POST", "authRequired": "developer",
            "healthy": ok and all_three_re,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "registry_flipped": reg_ok,
                "mtls_enrolled": mtls_re_ok,
                "teg_reinstated": teg_re_ok,
                "lever_reason": reinstate_reason[:120],
            },
            "error": None if (ok and all_three_re) else (
                f"reinstate lever skew — registry={reg_ok} mtls={mtls_re_ok} teg={teg_re_ok}"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Step 9: post-reinstate admin probe — symmetric to step 4
        await asyncio.sleep(2)
        ok, body, code = await http_in_container(
            target.a_registry_container, "GET",
            f"/api/v1/admin/agents/{agent_did}",
            jwt=dev_jwt, timeout=15,
        )
        re_status = (body or {}).get("status") if isinstance(body, dict) else None
        re_mtls = bool((body or {}).get("mtls_enabled")) if isinstance(body, dict) else False
        re_spiffe = (body or {}).get("spiffe_id") if isinstance(body, dict) else None
        re_correct = (
            ok and re_status == "active" and re_mtls and bool(re_spiffe)
        )
        results.append({
            "step": 8, "name": "Post-reinstate: active + mTLS re-enrolled + fresh SPIFFE",
            "path": "/admin/agents/{did}", "method": "GET", "authRequired": "developer",
            "healthy": re_correct,
            "statusCode": int(code) if code.isdigit() else 500,
            "responseData": {
                "status": re_status, "mtls_enabled": re_mtls,
                "spiffe_id": (re_spiffe or "")[:50],
            },
            "error": None if re_correct else (
                f"post-reinstate wrong: status={re_status} mtls={re_mtls} spiffe={bool(re_spiffe)}"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Step 10: AgentReinstated event count increased
        post_rein = max(0, query_event_count(target.a_es_db_container, "AgentReinstated"))
        delta_rein = post_rein - baseline_rein
        events_correct_re = delta_rein >= 1
        results.append({
            "step": 9, "name": "EventStore: AgentReinstated event delta ≥ 1",
            "path": "/admin/eventstore-stats", "method": "GET", "authRequired": "developer",
            "healthy": events_correct_re,
            "statusCode": 200,
            "responseData": {
                "delta_AgentReinstated": delta_rein,
                "baseline": baseline_rein,
                "post": post_rein,
            },
            "error": None if events_correct_re else (
                f"event emission gap: AgentReinstated delta={delta_rein} (should be ≥1)"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        self.flow_values = {
            "agent_did": agent_did,
            "delta_AgentSuspended": delta_susp,
            "delta_AgentReinstated": delta_rein,
            "suspend_levers": {
                "registry": registry_ok,
                "mtls": mtls_revoked_ok,
                "teg": teg_suspended_ok,
            },
            "reinstate_levers": {
                "registry": reg_ok,
                "mtls": mtls_re_ok,
                "teg": teg_re_ok,
            },
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
            "flow_name": "flow_coordinated_suspension_complete",
            "success": flow_success and ok == total,
            "total_steps": total,
            "successful_steps": ok,
            "results": results,
            "flow_values": dict(self.flow_values),
        }
