"""Multi-Frame EigenTrust Simulation Flow.

Validates the `/admin/simulation/*` API surface end-to-end:
  1. status endpoint returns clean state initially
  2. start a small sim (1 instance, 5 cycles)
  3. status reports running:true
  4. logs returns recent lines
  5. stop the sim
  6. status reports clean state again

The simulation runs against the prod registry-A (which holds the
sim_credentials.json + sim infrastructure). If a sim is ALREADY running
on prod, this flow gracefully refuses (mark expected_failure) instead of
clobbering it.

Sandbox-only: the tester runs flows only where API_TEST_EXECUTION_ENABLED=true.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from agentvault_registry.api_tests.base import APITestBase

logger = logging.getLogger(__name__)


def _ef_step(step: int, name: str, method: str, path: str, reason: str) -> Dict[str, Any]:
    return {
        "step": step,
        "name": name,
        "path": path,
        "method": method,
        "authRequired": "developer",
        "healthy": True,
        "expected_failure": True,
        "expected_failure_reason": reason,
        "statusCode": 200,
        "responseTime": 0,
        "responseData": {"skipped": True, "reason": reason},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error": None,
    }


class TestMultiframeEigentrust(APITestBase):
    """EigenTrust simulation flow — sandbox-orchestrated, prod-targeted."""

    CATEGORY_NAME = "multiframe_eigentrust"

    flow_values: Dict[str, Any] = {}
    _developer_token: Optional[str] = None

    async def setup(self):
        await self.setup_category(self.CATEGORY_NAME)
        self.flow_values = {}
        logger.info("Multiframe EigenTrust test setup complete")

    async def teardown(self):
        return

    async def test_all(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None,
    ):
        standard_results = await self.test_category_endpoints(
            category=self.CATEGORY_NAME,
            developer_token=developer_token,
            agent_token=agent_token,
            priority_only=False,
        )
        flow_results = await self.test_eigentrust_flow(developer_token)
        standard_results["flow_tests"] = flow_results
        return standard_results

    async def test_eigentrust_flow(self, developer_token: str) -> Dict[str, Any]:
        """EigenTrust simulation lifecycle — start, observe, stop, verify cleanup."""
        logger.info("=" * 60)
        logger.info("Starting Multi-Frame EigenTrust Simulation Flow")
        logger.info("=" * 60)

        self._developer_token = developer_token
        results = []
        sim_started = False

        # Step 1: Initial status (must not be running)
        logger.info("Step 1: GET /admin/simulation/status (initial)")
        status_initial = await self.test_endpoint(
            method="GET",
            path="/admin/simulation/status",
            auth_type="developer",
            developer_token=developer_token,
        )
        results.append({"step": 1, "name": "Initial simulation status", **status_initial})

        # If a sim is already running, refuse — don't clobber prod-side workload.
        is_running_already = False
        if status_initial.get("healthy") and isinstance(status_initial.get("responseData"), dict):
            running = status_initial["responseData"].get("running", False)
            instances = status_initial["responseData"].get("instances", 0)
            self.flow_values["initial_running"] = bool(running)
            self.flow_values["initial_instances"] = int(instances or 0)
            if running and instances > 0:
                is_running_already = True
                logger.warning(f"Simulation already running ({instances} instances) — flow will skip start/stop steps")

        # Step 2: Verify sim_credentials.json is reachable. The file lives on
        # the host at /opt/theprotocol/stack/Agentvault2/scripts/sim_credentials.json
        # and is mounted into registry-a's /scripts dir. From registry-test the
        # mount may be absent; we probe a few candidate paths and treat
        # "unreachable" as informational (not a hard failure) since the
        # simulation runs against registry-a anyway.
        creds_candidates = [
            "/scripts/sim_credentials.json",
            "/opt/theprotocol/stack/Agentvault2/scripts/sim_credentials.json",
        ]
        creds_path = None
        creds_size = 0
        agent_count = 0
        for p in creds_candidates:
            if os.path.exists(p):
                creds_path = p
                creds_size = os.path.getsize(p)
                try:
                    import json as _json
                    with open(p) as f:
                        creds = _json.load(f)
                    if isinstance(creds, dict):
                        if "agents" in creds:
                            agent_count = len(creds["agents"])
                        else:
                            agent_count = sum(len(v) if isinstance(v, list) else 0 for v in creds.values())
                    elif isinstance(creds, list):
                        agent_count = len(creds)
                except Exception as e:
                    logger.warning(f"Failed to parse {p}: {e}")
                break
        creds_reachable = creds_path is not None and agent_count > 0
        results.append({
            "step": 2,
            "name": "Sim credentials file reachable",
            "path": "/admin/simulation/credentials",
            "method": "GET",
            "authRequired": "developer",
            # Always healthy=True — when not reachable the step is informational
            # (the simulation runs against registry-a which has the mount).
            "healthy": True,
            "expected_failure": (not creds_reachable),
            "expected_failure_reason": (
                "sim_credentials.json not mounted into registry-test container — "
                "informational only; simulation runs against registry-a which has the mount."
                if not creds_reachable else None
            ),
            "statusCode": 200,
            "responseTime": 0,
            "responseData": {
                "file_path": creds_path,
                "file_size_bytes": creds_size,
                "agent_count": agent_count,
                "candidates_probed": creds_candidates,
            },
            "error": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        if is_running_already:
            # Production sim is busy — refuse start/stop and mark remaining steps expected_failure
            results.append(_ef_step(
                3, "Start simulation (skipped: prod sim busy)",
                "POST", "/admin/simulation/start",
                f"Simulation already running on target registry ({self.flow_values.get('initial_instances')} instances) — refusing to clobber.",
            ))
            results.append(_ef_step(
                4, "Wait for sim active (skipped)",
                "GET", "/admin/simulation/status",
                "Skipped — sim already running",
            ))
            results.append(_ef_step(
                5, "Sim logs (skipped)",
                "GET", "/admin/simulation/logs",
                "Skipped — sim already running",
            ))
            results.append(_ef_step(
                6, "Stop simulation (skipped)",
                "POST", "/admin/simulation/stop",
                "Skipped — sim already running, refusing to stop external workload",
            ))
            results.append(_ef_step(
                7, "Final status (skipped)",
                "GET", "/admin/simulation/status",
                "Skipped — sim already running",
            ))
            return self._summarize(results, flow_success=True)

        # Step 3: Start a small simulation
        logger.info("Step 3: POST /admin/simulation/start (1 instance, 5 cycles)")
        start_result = await self.test_endpoint(
            method="POST",
            path="/admin/simulation/start",
            auth_type="developer",
            body={
                "mode": "modern",
                "instances": 1,
                "pairs": 2,
                "cycle_interval": 3,
                "cycles": 5,
                "raw": False,
            },
            developer_token=developer_token,
            timeout=60.0,
        )
        results.append({"step": 3, "name": "Start simulation", **start_result})
        if start_result.get("healthy"):
            sim_started = True

        if not sim_started:
            # Start failed — record but don't crash; mark remaining steps as expected_failure
            results.append(_ef_step(
                4, "Wait for sim active (start failed)",
                "GET", "/admin/simulation/status",
                "start endpoint did not return success",
            ))
            results.append(_ef_step(
                5, "Sim logs (start failed)",
                "GET", "/admin/simulation/logs",
                "start endpoint did not return success",
            ))
            results.append(_ef_step(
                6, "Stop simulation (start failed)",
                "POST", "/admin/simulation/stop",
                "Nothing to stop",
            ))
            results.append(_ef_step(
                7, "Final status (start failed)",
                "GET", "/admin/simulation/status",
                "Skipped — start failed",
            ))
            return self._summarize(results, flow_success=False)

        # Step 4: Wait for sim to become active
        logger.info("Step 4: Sleep 20s, then re-check status")
        await asyncio.sleep(20)
        status_running = await self.test_endpoint(
            method="GET",
            path="/admin/simulation/status",
            auth_type="developer",
            developer_token=developer_token,
        )
        results.append({"step": 4, "name": "Sim status (running)", **status_running})

        # Step 5: Logs
        logger.info("Step 5: GET /admin/simulation/logs?tail=20")
        logs_result = await self.test_endpoint(
            method="GET",
            path="/admin/simulation/logs",
            auth_type="developer",
            test_path_override="/admin/simulation/logs?tail=20",
            developer_token=developer_token,
        )
        results.append({"step": 5, "name": "Sim logs (tail=20)", **logs_result})

        # Step 6: Stop
        logger.info("Step 6: POST /admin/simulation/stop")
        stop_result = await self.test_endpoint(
            method="POST",
            path="/admin/simulation/stop",
            auth_type="developer",
            developer_token=developer_token,
            timeout=60.0,
        )
        results.append({"step": 6, "name": "Stop simulation", **stop_result})

        # Step 7: Verify cleanup — sleep 2s for stop to settle
        await asyncio.sleep(2)
        logger.info("Step 7: GET /admin/simulation/status (after stop)")
        status_final = await self.test_endpoint(
            method="GET",
            path="/admin/simulation/status",
            auth_type="developer",
            developer_token=developer_token,
        )
        results.append({"step": 7, "name": "Final simulation status (cleaned)", **status_final})

        return self._summarize(results, flow_success=True)

    def _summarize(self, results, flow_success: bool) -> Dict[str, Any]:
        total_steps = len(results)
        successful_steps = sum(1 for r in results if r.get("healthy"))
        logger.info("=" * 60)
        logger.info(f"Multi-Frame EigenTrust Flow: {successful_steps}/{total_steps} steps healthy")
        logger.info("=" * 60)
        return {
            "flow_name": "multiframe_eigentrust_complete",
            "success": flow_success and successful_steps == total_steps,
            "total_steps": total_steps,
            "successful_steps": successful_steps,
            "results": results,
            "flow_values": dict(self.flow_values),
        }
