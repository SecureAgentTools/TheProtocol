"""Reactor Batch 2 — Operator Canary (sandboxalpha / sandboxdelta).

Sister flow to `flow_reactor_batch_2` but targets a sandbox OPERATOR's
registry container instead of the central sandbox registry. Goal: catch
operator-side reactor regressions in the BFF regression suite.

§pass73.3 topology: sandboxalpha (frame-a child, port 30000) +
sandboxdelta (frame-b child, port 30100). sandboxbeta + sandboxgamma
were torn down §pass73.3 for capacity. Both surviving operators are
covered by the `_all_flow` variant.

Auth: skips the password-login path (operator first-boot admin password
is not in session memory) and mints a developer JWT directly inside the
operator registry container using its own SECRET_KEY/ALGORITHM. This is
the same JWT format the real /auth/login flow produces and exercises the
full Authorization header → require_admin_flag(...) chain.

Sandbox-only. The operator container must have run `alembic upgrade head`
or its developers table needs the admin_* / suspension columns from
migrations 0009 + 0011. (Sandbox operators were patched 2026-04-27 to
add these columns surgically.)

Flow shape mirrors flow_reactor_batch_2 step-for-step.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from agentvault_registry.api_tests.base import APITestBase
from agentvault_registry.api_tests.multiframe_helpers import (
    SANDBOX_OPERATOR_TARGETS, get_operator_target,
    exec_in_container, http_in_container,
    mint_admin_jwt_in_container,
)

logger = logging.getLogger(__name__)

# Default canary — sandboxalpha is the frame-a child operator and the most
# heavily-exercised cloud-op in the canary topology. The `_all_flow` variant
# below covers both sandboxalpha + sandboxdelta in one sweep.
DEFAULT_OPERATOR = "sandboxalpha"


# Reactors covered by this flow (event_type → reactor name from /admin/reactor/status)
TRACKED_REACTORS = {
    "WebhookRetryExhausted": "WebhookRetryExhausted",
    "DisputeSlash": "AgentSlashed",
    "BridgeTransferExpired": "BridgeTransferExpired",
    "ProposalTallied": "ProposalTallied",
    "RegistryFederated": "RegistryFederated",
    "BalanceCorrected": "BalanceCorrected",
}


def _payload_webhook_exhausted(suffix: str) -> Dict[str, Any]:
    return {
        "event_type": "WebhookRetryExhausted",
        "aggregate_id": f"webhook:opflow-{suffix}",
        "aggregate_type": "Webhook",
        "data": {
            "webhook_id": f"opflow-{suffix}",
            "developer_id": 1,
            "target_url": "https://opflow.invalid/hook",
            "consecutive_failures": 10,
            "last_error": "Connection refused",
            "last_response_code": None,
            "disabled_at": "2026-04-27T11:00:00Z",
        },
        "idempotency_key": f"opflow_webhook_exhausted:{suffix}",
    }


def _payload_dispute_slash(suffix: str, did: str) -> Dict[str, Any]:
    return {
        "event_type": "DisputeSlash",
        "aggregate_id": did,
        "aggregate_type": "Agent",
        "data": {
            "dispute_id": int(suffix) if suffix.isdigit() else 99999,
            "defendant_did": did,
            "amount": 5,
            "origin_registry_url": "http://opflow.invalid",
            "slash_tx_id": f"opflow-slash-{suffix}",
        },
        "idempotency_key": f"opflow_dispute_slash:{suffix}",
    }


def _payload_bridge_expired(suffix: str, did: str) -> Dict[str, Any]:
    return {
        "event_type": "BridgeTransferExpired",
        "aggregate_id": f"opflow-bridge-{suffix}",
        "aggregate_type": "BridgeTransaction",
        "data": {
            "bridge_tx_id": f"opflow-bridge-{suffix}",
            "source_frame_id": "frame-a",
            "target_frame_id": "frame-b",
            "source_agent_did": did,
            "target_agent_did": "did:theprotocol:opflow-target",
            "amount": "1",
            "expired_at": "2026-04-27T09:46:00Z",
            "expires_at": "2026-04-27T09:30:00Z",
        },
        "idempotency_key": f"opflow_bridge_expired:{suffix}",
    }


def _payload_proposal_tallied(suffix: str, result: str) -> Dict[str, Any]:
    return {
        "event_type": "ProposalTallied",
        "aggregate_id": f"proposal_opflow_{suffix}_{result.lower()}",
        "aggregate_type": "Governance",
        "data": {
            "proposal_id": f"opflow-{suffix}-{result.lower()}",
            "result": result,
            "votes_for": 100 if result == "PASSED" else 20,
            "votes_against": 20 if result == "PASSED" else 100,
            "total_votes": 120,
            "quorum_met": True,
            "pass_rate": 83.3 if result == "PASSED" else 16.7,
        },
        "idempotency_key": f"opflow_proposal_tallied:{suffix}:{result.lower()}",
    }


def _payload_registry_federated(suffix: str) -> Dict[str, Any]:
    return {
        "event_type": "RegistryFederated",
        "aggregate_id": f"77{suffix[-3:].zfill(3)}",
        "aggregate_type": "Agent",
        "data": {
            "peer_registry_id": int(f"77{suffix[-3:].zfill(3)}"),
            "peer_name": f"opflow-fake-peer-{suffix}",
            "peer_url": "http://nonexistent.opflow.invalid:9999",
            "policy_hash": f"opflow-hash-{suffix}",
            "admitted_by": "opflow@test.sandbox",
            "admitted_at": "2026-04-27T09:46:00Z",
        },
        "idempotency_key": f"opflow_registry_federated:{suffix}",
    }


def _payload_balance_corrected(suffix: str, did: str) -> Dict[str, Any]:
    return {
        "event_type": "BalanceCorrected",
        "aggregate_id": did,
        "aggregate_type": "Agent",
        "data": {
            "agent_did": did,
            "delta": "+1.0",
            "new_balance": "100.0",
            "reason": "opflow test",
            "actor": "opflow-test",
            "recorded_at": "2026-04-27T09:46:00Z",
        },
        "idempotency_key": f"opflow_balance_corrected:{suffix}",
    }


class TestFlowReactorBatch2Operator(APITestBase):
    CATEGORY_NAME = "flow_reactor_batch_2_operator"
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
        std["flow_tests"] = await self.test_reactor_batch_2_operator_flow(developer_token)
        return std

    async def test_reactor_batch_2_operator_flow(self, developer_token: str) -> Dict[str, Any]:
        """Single-operator canary (sandboxalpha by default — §pass73.3 topology)."""
        return await self._run_for_operator(DEFAULT_OPERATOR)

    async def test_reactor_batch_2_operator_all_flow(self, developer_token: str) -> Dict[str, Any]:
        """Run the canary flow against ALL surviving sandbox operators
        (sandboxalpha + sandboxdelta — §pass73.3 topology, sandboxbeta +
        sandboxgamma torn down). Returns a consolidated summary; reports
        per-operator results."""
        per_operator: List[Dict[str, Any]] = []
        all_ok = True
        total_steps = 0
        successful_steps = 0
        for op_label in ("sandboxalpha", "sandboxdelta"):
            r = await self._run_for_operator(op_label)
            per_operator.append({
                "operator": op_label,
                "success": r.get("success"),
                "successful_steps": r.get("successful_steps"),
                "total_steps": r.get("total_steps"),
            })
            all_ok = all_ok and bool(r.get("success"))
            total_steps += r.get("total_steps", 0)
            successful_steps += r.get("successful_steps", 0)
        # Aggregate flow_values from the LAST run so the BFF surfaces
        # something useful (each individual run sets its own per-operator
        # keys; we don't merge to avoid clobbering)
        return {
            "flow_name": "flow_reactor_batch_2_operator_all_complete",
            "success": all_ok,
            "total_steps": total_steps,
            "successful_steps": successful_steps,
            "results": [{
                "step": i + 1,
                "name": f"Operator {p['operator']}: {p['successful_steps']}/{p['total_steps']}",
                "path": "/admin/api-test/test-flow",
                "method": "POST",
                "authRequired": "developer",
                "healthy": p["success"],
                "statusCode": 200 if p["success"] else 500,
                "responseData": p,
                "error": None if p["success"] else f"{p['operator']} flow failed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            } for i, p in enumerate(per_operator)],
            "flow_values": dict(self.flow_values),
        }

    async def _run_for_operator(self, operator_label: str) -> Dict[str, Any]:
        try:
            target = get_operator_target(operator_label)
        except ValueError as e:
            return self._summarize(
                [self._fail_step(1, "Resolve operator target", str(e))], False,
            )

        logger.info("=" * 60)
        logger.info(f"Starting Reactor Batch 2 Operator Canary ({target.label})")
        logger.info("=" * 60)

        results: List[Dict[str, Any]] = []
        suffix = str(int(time.time()) % 1_000_000)

        # Step 1: mint admin JWT inside operator container (skip /auth/login —
        # operator's first-boot admin password is not in session memory)
        ok_jwt, dev_jwt, det = await mint_admin_jwt_in_container(
            target.registry_container, developer_id=1, minutes=10,
        )
        if not ok_jwt:
            results.append(self._fail_step(
                1, f"Mint admin JWT inside {target.registry_container}", det,
            ))
            return self._summarize(results, False)
        results.append(self._pass_step(
            1, f"Mint admin JWT inside {target.registry_container}",
            "/auth/login (skipped — JWT minted directly)", "POST",
            {"developer_id": 1, "minutes": 10},
        ))

        # Step 2: snapshot baseline reactor inventory on the operator
        baseline = await self._snapshot_reactor_status(target.registry_container, dev_jwt)
        if baseline is None:
            results.append(self._fail_step(
                2, f"Snapshot baseline /admin/reactor/status on {target.label}",
                "request failed",
            ))
            return self._summarize(results, False)
        baseline_counts = baseline["counts"]
        all_19_present = baseline["total"] >= 19
        results.append({
            "step": 2,
            "name": f"Snapshot baseline /admin/reactor/status on {target.label} (≥19 reactors)",
            "path": "/admin/reactor/status", "method": "GET",
            "authRequired": "developer",
            "healthy": all_19_present,
            "statusCode": 200,
            "responseData": {
                "operator": target.label,
                "total_reactors": baseline["total"],
                "tracked_baseline": baseline_counts,
            },
            "error": None if all_19_present else (
                f"Expected ≥19 reactors on {target.label}, got {baseline['total']}"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if not all_19_present:
            return self._summarize(results, False)

        # Find a real agent DID in the operator's DB (or fall back)
        ok_did, did = await self._fetch_real_did_on_operator(target)
        if not ok_did:
            did = f"did:theprotocol:opflow-fallback-{suffix}"
            logger.info(f"[OpFlow] Using fallback DID: {did}")

        # Steps 3-9: emit synthetic events on the operator
        emit_steps: List[tuple] = [
            (3, "WebhookRetryExhausted",     _payload_webhook_exhausted(suffix)),
            (4, "DisputeSlash",              _payload_dispute_slash(suffix, did)),
            (5, "BridgeTransferExpired",     _payload_bridge_expired(suffix, did)),
            (6, "ProposalTallied (PASSED)",  _payload_proposal_tallied(suffix, "PASSED")),
            (7, "ProposalTallied (FAILED)",  _payload_proposal_tallied(suffix, "FAILED")),
            (8, "RegistryFederated",         _payload_registry_federated(suffix)),
            (9, "BalanceCorrected",          _payload_balance_corrected(suffix, did)),
        ]
        for step_no, label, payload in emit_steps:
            ok_emit, emit_detail = await self._emit_event(
                target.registry_container, payload,
            )
            results.append({
                "step": step_no,
                "name": f"Emit synthetic {label} on {target.label}",
                "path": f"/api/v1/events ({payload['event_type']})",
                "method": "EMIT (in-container)",
                "authRequired": "internal",
                "healthy": ok_emit,
                "statusCode": 201 if ok_emit else 500,
                "responseData": {
                    "operator": target.label,
                    "event_type": payload["event_type"],
                    "idempotency_key": payload["idempotency_key"],
                    "detail": emit_detail[:200] if isinstance(emit_detail, str) else emit_detail,
                },
                "error": None if ok_emit else f"emit failed: {emit_detail}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        # Wait for async WS dispatch + handler completion. Sandbox operators
        # typically dispatch in <100ms, but the central sandbox EventStore is
        # the relay — give it 4s for back-and-forth.
        await asyncio.sleep(4)

        # Step 10: re-probe and verify all 19 reactors still live + the 6 new
        # event types are still present in the operator's inventory.
        post = await self._snapshot_reactor_status(target.registry_container, dev_jwt)
        if post is None:
            results.append(self._fail_step(
                10, f"Re-probe /admin/reactor/status on {target.label}",
                "request failed",
            ))
            return self._summarize(results, False)
        post_counts = post["counts"]
        all_19_still = post["total"] >= 19
        all_six_present = all(ev in post_counts for ev in TRACKED_REACTORS)
        healthy_step10 = all_19_still and all_six_present
        results.append({
            "step": 10,
            "name": (
                f"Re-probe /admin/reactor/status on {target.label} — all 19 still subscribed "
                "+ 6 new reactors present"
            ),
            "path": "/admin/reactor/status", "method": "GET",
            "authRequired": "developer",
            "healthy": healthy_step10,
            "statusCode": 200,
            "responseData": {
                "operator": target.label,
                "total_reactors": post["total"],
                "baseline_counts": baseline_counts,
                "post_counts": post_counts,
                "informational_deltas": {
                    k: post_counts.get(k, 0) - baseline_counts.get(k, 0)
                    for k in TRACKED_REACTORS
                },
                "all_six_new_reactors_present": all_six_present,
                "note": (
                    "Per-worker semantic: dispatch_count varies across workers. "
                    "Operator runs with --workers 8, so deltas are informational. "
                    "Inventory presence is the regression-stable invariant."
                ),
            },
            "error": None if healthy_step10 else (
                f"reactor inventory broke on {target.label} "
                f"(total={post['total']}, six_new_present={all_six_present})"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        self.flow_values = {
            "reactor_batch_2_operator_label": target.label,
            "reactor_batch_2_operator_total_reactors": post["total"],
            "reactor_batch_2_operator_baseline_counts": baseline_counts,
            "reactor_batch_2_operator_post_counts": post_counts,
            "reactor_batch_2_operator_real_did": did,
        }
        return self._summarize(results, True)

    # ────────────────────────────────────────────────────── helpers

    async def _snapshot_reactor_status(self, container: str, dev_jwt: str):
        ok, body, code = await http_in_container(
            container, "GET",
            "/api/v1/admin/reactor/status",
            jwt=dev_jwt, timeout=15,
        )
        if not ok or not isinstance(body, dict):
            return None
        reactors = body.get("reactors") or []
        counts = {}
        for r in reactors:
            if isinstance(r, dict):
                ev = r.get("event_type")
                cnt = r.get("dispatch_count") or 0
                if ev is not None:
                    counts[ev] = cnt
        total = (body.get("summary") or {}).get("total_reactors") or len(reactors)
        return {"total": total, "counts": counts}

    async def _fetch_real_did_on_operator(self, target) -> tuple[bool, str]:
        """Pick a real agent DID from the operator's registry DB."""
        # Operator's DB is in a separate container, accessed via its env var
        rc, out = await asyncio.to_thread(
            exec_in_container, target.db_container, [
                "sh", "-c",
                "PGPASSWORD=$POSTGRES_PASSWORD psql -U $POSTGRES_USER "
                "-d $POSTGRES_DB -At -c "
                "\"SELECT did FROM agents WHERE status='active' LIMIT 1\"",
            ], 15,
        )
        if rc == 0 and out and out.strip().startswith("did:"):
            return True, out.strip().split("\n")[0]
        return False, ""

    async def _emit_event(self, container: str, payload: Dict[str, Any]) -> tuple[bool, str]:
        """Emit a synthetic event using the registry's Python emitter inside the
        operator container. Same base64-encoded payload trick as the central
        flow_reactor_batch_2 to avoid bare null/true/false NameErrors."""
        payload_b64 = base64.b64encode(json.dumps(payload).encode()).decode()
        script = (
            "import asyncio, base64, json, sys\n"
            "sys.path.insert(0, '/app/src')\n"
            "from agentvault_registry.event_emitter import get_event_emitter\n"
            f"PAYLOAD = json.loads(base64.b64decode('{payload_b64}').decode())\n"
            "async def main():\n"
            "    e = get_event_emitter()\n"
            "    await e.emit(\n"
            "        event_type=PAYLOAD['event_type'],\n"
            "        aggregate_id=PAYLOAD['aggregate_id'],\n"
            "        aggregate_type=PAYLOAD['aggregate_type'],\n"
            "        data=PAYLOAD['data'],\n"
            "        idempotency_key=PAYLOAD['idempotency_key'],\n"
            "    )\n"
            "    print('OK')\n"
            "    await e.close()\n"
            "asyncio.run(main())\n"
        )
        b64 = base64.b64encode(script.encode()).decode()
        cmd = ["sh", "-c", f"echo '{b64}' | base64 -d | python3 -"]
        rc, out = await asyncio.to_thread(exec_in_container, container, cmd, 30)
        out = (out or "")[-500:]
        if rc == 0 and "OK" in out:
            return True, "emitted"
        return False, f"rc={rc} out={out}"

    def _pass_step(self, step, name, path, method, data):
        return {
            "step": step, "name": name, "path": path, "method": method,
            "authRequired": "developer",
            "healthy": True, "statusCode": 200,
            "responseData": data, "error": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _fail_step(self, step, name, detail):
        return {
            "step": step, "name": name,
            "path": "/admin/reactor/status (operator)", "method": "GET",
            "authRequired": "developer",
            "healthy": False, "statusCode": 500,
            "responseData": {"detail": detail}, "error": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _summarize(self, results, flow_success: bool) -> Dict[str, Any]:
        total = len(results)
        ok = sum(1 for r in results if r.get("healthy"))
        return {
            "flow_name": "flow_reactor_batch_2_operator_canary_complete",
            "success": flow_success and ok == total,
            "total_steps": total,
            "successful_steps": ok,
            "results": results,
            "flow_values": dict(self.flow_values),
        }
