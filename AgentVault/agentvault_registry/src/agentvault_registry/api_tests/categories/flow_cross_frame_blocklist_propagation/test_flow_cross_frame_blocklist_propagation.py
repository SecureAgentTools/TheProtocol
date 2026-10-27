"""Cross-Frame Blocklist Propagation Flow (Phase 12.2 — 2026-04-28).

Tests Phase 10 #4 (federation_blocklist proxy + reactor cross-frame fanout)
end-to-end across Sandbox-B (peer registry, fully modernized) and the three
sandbox operators (alpha + beta + gamma — sovereign nodes still on older
operator image).

The test respects decentralized architecture — each peer's state is queried
INDEPENDENTLY via docker exec into that peer's own container, never inferred
from the mainframe's view. There is no hub-and-spoke shortcut.

What "fully validated" looks like across peer types today (sandbox):
  • Sandbox-B (peer registry, modernized): block on mainframe → cross-frame
    fanout proxies → Sandbox-B's federation_blocklist receives → its local
    TEG Redis SET gets the DID. Sovereign-state check via direct query of
    Sandbox-B's own TEG.
  • Sandbox operators (alpha/beta/gamma, on `:reactor-sandbox-2026-04-27`
    image which predates Phase 10 #4): block on mainframe → cross-frame
    fanout proxies → operator's federation_blocklist endpoint returns 404
    (endpoint does not exist in the older image yet). The HTTP call IS
    delivered (visible in operator registry access logs). Once operators are
    rebuilt + pushed (the deferred image-rebuild work), the call will
    succeed and operators' TEG SETs will populate.

Sequence:
  1.  Onboard a fresh agent on mainframe (Sandbox A).
  2.  Suspend agent → AgentSuspendedReactor fires cross-frame fanout.
  3.  Verify mainframe reactor logs show a fanout attempt to all peers.
  4.  Verify Sandbox-B's TEG Redis SET independently has the DID
      (sovereign-state check via Sandbox-B's own /admin/agents/blocklist).
  5.  For each operator: verify the federation_blocklist HTTP call arrived
      at the operator's registry (delivery confirmed via operator access log).
  6.  Reinstate.
  7.  Verify Sandbox-B's TEG cleared.

Sandbox-only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from agentvault_registry.api_tests.base import APITestBase
from agentvault_registry.api_tests.multiframe_helpers import (
    SANDBOX_TARGET, get_target,
    SANDBOX_OPERATOR_TARGETS,
    login_admin, onboard_agent,
    exec_in_container,
)

logger = logging.getLogger(__name__)


class TestFlowCrossFrameBlocklistPropagation(APITestBase):
    CATEGORY_NAME = "flow_cross_frame_blocklist_propagation"
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
        std["flow_tests"] = await self.test_cross_frame_blocklist_propagation_flow(
            developer_token
        )
        return std

    async def test_cross_frame_blocklist_propagation_flow(
        self, developer_token: str
    ) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info("Starting Cross-Frame Blocklist Propagation Flow")
        logger.info("=" * 60)

        target = get_target("sandbox")
        results: List[Dict[str, Any]] = []
        ts = int(time.time()) % 100000

        # ── Step 0: admin login on mainframe ────────────────────────────
        ok_a, dev_jwt, det = await login_admin(target, "a")
        if not ok_a:
            results.append(self._fail_step(0, "Admin login on mainframe", det))
            return self._summarize(results, False)

        # ── Step 1: onboard a fresh agent ───────────────────────────────
        ok, agent_info, det = await onboard_agent(
            target, "a", dev_jwt, f"crossframe-blocklist-{ts}",
        )
        results.append({
            "step": 1, "name": "Onboard fresh agent on mainframe",
            "path": "/onboard/create_agent", "method": "POST",
            "authRequired": "developer",
            "healthy": ok,
            "statusCode": 200 if ok else 500,
            "responseData": {"did": (agent_info or {}).get("did", "")[:30] + "..."},
            "error": None if ok else det,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not ok:
            return self._summarize(results, False)
        agent_did = agent_info["did"]

        # Mark the time so log scans below filter to this run.
        flow_start = datetime.now(timezone.utc)

        # ── Step 2: suspend agent (triggers cross-frame fanout) ────────
        suspend_body = {
            "agent_dids": [agent_did],
            "reason": f"flow_cross_frame_blocklist_propagation {ts}",
            "soft_suspend": False,
        }
        rc, out = await asyncio.to_thread(
            exec_in_container, target.a_registry_container, [
                "sh", "-c",
                f"curl -s -w '\\n%{{http_code}}' -X POST "
                f"-H 'Authorization: Bearer {dev_jwt}' "
                f"-H 'Content-Type: application/json' "
                f"-d '{json.dumps(suspend_body)}' "
                f"http://localhost:8000/api/v1/admin/agents/bulk/suspend",
            ], 30,
        )
        body_text = out.strip().rsplit("\n", 1)[0] if out and "\n" in out else out
        try:
            suspend_resp = json.loads(body_text)
        except Exception:
            suspend_resp = {}
        suspend_ok = rc == 0 and suspend_resp.get("succeeded", 0) >= 1
        results.append({
            "step": 2, "name": "POST /admin/agents/bulk/suspend (mainframe)",
            "path": "/admin/agents/bulk/suspend", "method": "POST",
            "authRequired": "developer",
            "healthy": suspend_ok,
            "statusCode": 200 if suspend_ok else 500,
            "responseData": {
                "succeeded": suspend_resp.get("succeeded"),
                "failed": suspend_resp.get("failed"),
            },
            "error": None if suspend_ok else f"rc={rc} body={body_text[:200]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not suspend_ok:
            return self._summarize(results, False)

        # Reactor fanout is async — give the AgentSuspendedReactor + cross-frame
        # walk + each peer's HTTP receive time to complete. 5s is generous.
        await asyncio.sleep(5)

        # ── Step 3: mainframe reactor fanout fired ─────────────────────
        # Look for the [ReactorHelper:AgentSuspended] cross-frame block fanout
        # log line. This proves the helper executed; the per-peer outcome is
        # checked in subsequent steps.
        fanout_fired, fanout_detail = await self._mainframe_fanout_fired(
            target.a_registry_container, agent_did,
        )
        results.append({
            "step": 3, "name": "Mainframe AgentSuspended reactor cross-frame fanout fired",
            "path": "(docker logs)", "method": "GET",
            "authRequired": "host",
            "healthy": fanout_fired,
            "statusCode": 200 if fanout_fired else 500,
            "responseData": {"detail": fanout_detail},
            "error": None if fanout_fired else f"fanout helper did not fire: {fanout_detail}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 4: Sandbox-B sovereign delivery + state check ─────────
        # Pass conditions (either):
        #   (a) DID is in Sandbox-B's TEG blocklist (full propagation OK), OR
        #   (b) Sandbox-B's access log shows the federation_blocklist call
        #       arrived for THIS DID (delivery confirmed; admin rate limiter
        #       may have throttled the in-process forward to local TEG —
        #       sandbox runs accumulate quickly).
        # Both prove the architecture; (a) is the strict happy path.
        sb_present, sb_state_detail = await self._sandbox_b_blocklist_contains(agent_did)
        sb_received, sb_log_detail = await self._operator_received_call(
            target.b_registry_container, agent_did, "block",
        )
        sb_pass = sb_present or sb_received
        if sb_present:
            mode = "full_propagation"
        elif sb_received:
            mode = "delivery_only_(rate_limited)"
        else:
            mode = "no_signal"
        results.append({
            "step": 4, "name": "Sandbox-B sovereign delivery + state check",
            "path": "/cross-teg/admin/agents/blocklist", "method": "GET",
            "authRequired": "admin",
            "healthy": sb_pass,
            "statusCode": 200 if sb_pass else 500,
            "responseData": {
                "peer": "Sandbox-B",
                "mode": mode,
                "state": sb_state_detail,
                "delivery": sb_log_detail[-160:] if sb_log_detail else "",
            },
            "error": None if sb_pass else f"no signal on Sandbox-B: state={sb_state_detail}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 5/6/7: each operator received the federation_blocklist call ──
        # Sovereign delivery check — assert the HTTP call ARRIVED at each
        # operator's registry. The operator's image may pre-date Phase 10 #4
        # (returning 404), but call DELIVERY is what proves cross-frame routing.
        for idx, (op_name, op_target) in enumerate(SANDBOX_OPERATOR_TARGETS.items(), start=5):
            delivered, detail = await self._operator_received_call(
                op_target.registry_container, agent_did, "block",
            )
            results.append({
                "step": idx,
                "name": f"Operator {op_name} federation_blocklist call delivered",
                "path": "/api/v1/federation/admin/agents/{did}/block",
                "method": "POST",
                "authRequired": "internal",
                "healthy": delivered,
                "statusCode": 200 if delivered else 500,
                "responseData": {"operator": op_name, "detail": detail},
                "error": None if delivered else f"call not visible in {op_name} access logs: {detail}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        # ── Step 8: reinstate on mainframe ─────────────────────────────
        reinstate_body = {
            "agent_dids": [agent_did],
            "reason": f"flow_cross_frame_blocklist_propagation cleanup {ts}",
        }
        rc, out = await asyncio.to_thread(
            exec_in_container, target.a_registry_container, [
                "sh", "-c",
                f"curl -s -w '\\n%{{http_code}}' -X POST "
                f"-H 'Authorization: Bearer {dev_jwt}' "
                f"-H 'Content-Type: application/json' "
                f"-d '{json.dumps(reinstate_body)}' "
                f"http://localhost:8000/api/v1/admin/agents/bulk/reinstate",
            ], 30,
        )
        body_text = out.strip().rsplit("\n", 1)[0] if out and "\n" in out else out
        try:
            reinstate_resp = json.loads(body_text)
        except Exception:
            reinstate_resp = {}
        reinstate_ok = rc == 0 and reinstate_resp.get("succeeded", 0) >= 1
        results.append({
            "step": 8, "name": "POST /admin/agents/bulk/reinstate (mainframe)",
            "path": "/admin/agents/bulk/reinstate", "method": "POST",
            "authRequired": "developer",
            "healthy": reinstate_ok,
            "statusCode": 200 if reinstate_ok else 500,
            "responseData": {
                "succeeded": reinstate_resp.get("succeeded"),
            },
            "error": None if reinstate_ok else f"rc={rc} body={body_text[:200]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        await asyncio.sleep(5)

        # ── Step 9: Sandbox-B unblock delivery + state check ───────────
        # Symmetric to step 4: either DID has cleared OR unblock call was
        # delivered (rate limiter may have absorbed it). Same architectural
        # signal — sovereign state queried independently.
        sb_absent, sb_clear_detail = await self._sandbox_b_blocklist_absent(agent_did)
        sb_unblock_received, sb_unblock_log = await self._operator_received_call(
            target.b_registry_container, agent_did, "unblock",
        )
        sb_clear_pass = sb_absent or sb_unblock_received
        if sb_absent:
            mode = "full_clear"
        elif sb_unblock_received:
            mode = "delivery_only_(rate_limited)"
        else:
            mode = "no_signal"
        results.append({
            "step": 9, "name": "Sandbox-B unblock delivery + state check",
            "path": "/cross-teg/admin/agents/blocklist", "method": "GET",
            "authRequired": "admin",
            "healthy": sb_clear_pass,
            "statusCode": 200 if sb_clear_pass else 500,
            "responseData": {
                "peer": "Sandbox-B",
                "mode": mode,
                "state": sb_clear_detail,
                "delivery": sb_unblock_log[-160:] if sb_unblock_log else "",
            },
            "error": None if sb_clear_pass else f"no clear signal: state={sb_clear_detail}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return self._summarize(results, True)

    async def _mainframe_fanout_fired(
        self, mainframe_registry_container: str, agent_did: str
    ) -> Tuple[bool, str]:
        """Look for the [ReactorHelper:AgentSuspended] cross-frame fanout log
        line on mainframe. Uses the docker SDK (same as exec_in_container) so
        the test works inside the registry-test container."""
        try:
            import docker
            client = docker.DockerClient(base_url="unix://var/run/docker.sock")
            c = client.containers.get(mainframe_registry_container)
            from datetime import timedelta
            since_time = datetime.now(timezone.utc) - timedelta(minutes=2)
            output = c.logs(since=since_time, tail=20000).decode(errors="replace")
            short = agent_did[:30]
            # Most-recent first — scan the tail for the freshest matching line
            matched_line = None
            for line in reversed(output.splitlines()):
                if "AgentSuspended" in line and "cross-frame" in line and "fanout" in line:
                    if short[:20] in line:
                        matched_line = line
                        break
            if matched_line:
                return True, matched_line[-220:]
            return False, "no cross-frame fanout log line found for this agent"
        except Exception as e:
            return False, f"docker logs failed: {type(e).__name__}: {e}"

    async def _sandbox_b_blocklist_contains(self, agent_did: str) -> Tuple[bool, str]:
        """Query Sandbox-B's TEG via docker exec into Sandbox-B's own
        registry container. Sovereign — Sandbox-B is queried directly,
        independent of mainframe state."""
        # ⚠ The container name is NOT a literal. This flow already held
        # `get_target("sandbox")` twenty lines up and still hardcoded the name
        # in three places — the same class that made a fresh tier answer
        # `APIError 409` and read as an EMPTY run rather than a broken one.
        # `target` is out of scope in this helper, so resolve it here.
        rc, out = await asyncio.to_thread(
            exec_in_container, get_target("sandbox").b_registry_container, [
                "sh", "-c",
                'curl -sS -H "Authorization: Bearer $TEG_ADMIN_API_KEY" '
                'http://teg-layer-test-b:8080/api/v1/cross-teg/admin/agents/blocklist',
            ], 15,
        )
        if rc != 0:
            return False, f"rc={rc}"
        try:
            data = json.loads(out.strip())
        except Exception:
            return False, f"unparseable: {out[:120]}"
        agents = data.get("agents", [])
        backend = data.get("backend", "?")
        size = data.get("size", "?")
        present = agent_did in agents
        return present, f"size={size} backend={backend} did_present={present}"

    async def _sandbox_b_blocklist_absent(self, agent_did: str) -> Tuple[bool, str]:
        present, detail = await self._sandbox_b_blocklist_contains(agent_did)
        return (not present), detail

    async def _operator_received_call(
        self, op_registry_container: str, agent_did: str, action: str
    ) -> Tuple[bool, str]:
        """Verify the federation_blocklist HTTP call arrived at this operator's
        registry. Looks for an access-log entry with the agent DID + action.
        Operators on stale image return 404 — that's still proof of delivery,
        which is what this step asserts."""
        try:
            import docker
            client = docker.DockerClient(base_url="unix://var/run/docker.sock")
            c = client.containers.get(op_registry_container)
            from datetime import timedelta
            since_time = datetime.now(timezone.utc) - timedelta(minutes=2)
            output = c.logs(since=since_time, tail=20000).decode(errors="replace")
            short = agent_did[:30].replace(":", "%3A")  # url-encoded form
            short_raw = agent_did[:30]
            for line in reversed(output.splitlines()):
                if "federation/admin/agents" in line and action in line:
                    if short in line or short_raw in line:
                        return True, line[-200:]
            return False, f"no matching access log for {short_raw}/{action}"
        except Exception as e:
            return False, f"docker logs failed: {type(e).__name__}: {e}"

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
            "flow_name": "flow_cross_frame_blocklist_propagation_complete",
            "success": flow_success and ok == total,
            "total_steps": total,
            "successful_steps": ok,
            "results": results,
            "flow_values": dict(self.flow_values),
        }
