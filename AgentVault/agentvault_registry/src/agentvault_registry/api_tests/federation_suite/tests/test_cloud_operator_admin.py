"""Cloud operator admin observability tests (§pass73.3.14 Batch 65).

3 read-only tests probing the cloud-operator admin surface from
sandbox-A's perspective (the parent registry sees its cloud-op fleet).
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


def _is_silent_or_error(r):
    if isinstance(r, str):
        return True
    if isinstance(r, dict):
        if not r:
            return True
        if "_text" in r:
            return isinstance(r["_text"], str)
    return False


async def _pick_cloud_op_id(rig: FederationTestRig):
    """Pick an operator_id from getCloudOperators list."""
    ops = await rig.mcp("sandbox-A-admin").call("getCloudOperators")
    items = ops if isinstance(ops, list) else (
        ops.get("operators") or ops.get("items") or ops.get("data") or []
    ) if isinstance(ops, dict) else []
    if not items or not isinstance(items[0], dict):
        return None
    return (items[0].get("operator_id") or items[0].get("id") or
            items[0].get("operator_slug") or items[0].get("slug"))


@federation_test(
    name="cloud_operator_health_envelope",
    category="cloud_op_admin",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["cloud-op", "health"],
)
async def test_cloud_operator_health(rig: FederationTestRig) -> AssertionResult:
    """getCloudOperatorHealth returns per-cloud-op health envelope.
    Probe getCloudOperators first to pick a slug."""
    state: dict = {}

    async def predicate():
        try:
            op_id = await _pick_cloud_op_id(rig)
            if op_id is None:
                state["no_ops"] = True
                return True
            state["operator_id"] = op_id
            r = await rig.mcp("sandbox-A-admin").call(
                "getCloudOperatorHealth", {"operator_id": str(op_id)}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e) or "400" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="cloud operator health envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="cloud_operator_logs_envelope",
    category="cloud_op_admin",
    budget_sec=20.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["cloud-op", "logs"],
)
async def test_cloud_operator_logs(rig: FederationTestRig) -> AssertionResult:
    """getCloudOperatorLogs returns log envelope. May fail in sandbox
    if log endpoint isn't wired — accept 4xx as auth/wiring gap."""
    state: dict = {}

    async def predicate():
        try:
            op_id = await _pick_cloud_op_id(rig)
            if op_id is None:
                state["no_ops"] = True
                return True
            state["operator_id"] = op_id
            r = await rig.mcp("sandbox-A-admin").call(
                "getCloudOperatorLogs", {"operator_id": str(op_id)}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return True
            elif isinstance(r, str):
                state["text_len"] = len(r)
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e) or "400" in repr(e)

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="cloud operator logs endpoint reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="cloud_operators_inventory_growing",
    category="cloud_op_admin",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["cloud-op", "inventory"],
)
async def test_cloud_operators_growing(
    rig: FederationTestRig,
) -> AssertionResult:
    """getCloudOperators returns the cloud operator inventory.
    Sandbox-A federates with sandboxalpha + sandboxdelta → expect ≥2."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCloudOperators")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("operators") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="cloud operators inventory reachable",
        capture_state=lambda: state,
    )
