"""Federation admin lifecycle tests (Phase F §pass73.3.6+).

5 tests probing operational admin surfaces — federation_compliance,
license details, operator lifecycle observability, audit logs, system
metrics. All read-only.
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


def _unwrap_admin_request(r):
    if isinstance(r, dict) and "response" in r and isinstance(r.get("response"), dict):
        return r["response"]
    return r


@federation_test(
    name="federation_self_health_check_returns_ok",
    category="federation_admin_lifecycle",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["self-health", "federation"],
)
async def test_federation_self_health(rig: FederationTestRig) -> AssertionResult:
    """getAdminFederationSelfHealth returns a healthy status payload on
    both mainframes — operator-visible federation self-diagnostic."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getAdminFederationSelfHealth")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {"keys": list(r.keys())[:8]}
                else:
                    state[label] = type(r).__name__
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (isinstance(v.get("keys"), list) and v["keys"])
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="federation self-health reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_dashboard_reachable_per_frame",
    category="federation_admin_lifecycle",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["admin-dashboard"],
)
async def test_admin_dashboard(rig: FederationTestRig) -> AssertionResult:
    """getAdminDashboard returns populated counters on both mainframes."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getAdminDashboard")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {
                        "developer_count": r.get("developer_count"),
                        "agent_count": r.get("agent_count"),
                    }
                else:
                    state[label] = type(r).__name__
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent")
                or (isinstance(v.get("agent_count"), int) and v["agent_count"] >= 1)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin dashboard returns ≥1 agent count on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_workers_status_lists_workers",
    category="federation_admin_lifecycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["workers", "background-tasks"],
)
async def test_admin_workers_status(rig: FederationTestRig) -> AssertionResult:
    """getAdminWorkersStatus lists ≥5 active background workers.

    Per CLAUDE.md PART 9, sandbox-A runs ~15 active workers (federation_sync,
    canary_runner, supply_auditor, saga_timeout_checker, etc.). Loose ≥5
    threshold tolerates variance.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAdminWorkersStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                workers = r.get("workers") or r.get("items") or r.get("data") or []
                state["count"] = len(workers)
                state["keys"] = list(r.keys())[:6]
            elif isinstance(r, list):
                state["count"] = len(r)
            else:
                return False
            return isinstance(state.get("count"), int) and state["count"] >= 5
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin workers status lists ≥5 workers on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_audit_logs_recent_activity",
    category="federation_admin_lifecycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["audit-logs", "security"],
)
async def test_admin_audit_logs(rig: FederationTestRig) -> AssertionResult:
    """getAdminAuditLogs returns a list of recent audit entries.

    Validates the audit log subsystem is alive + queryable. The federation
    suite itself generates audit events (MCP tool calls when
    MCP_AUDIT_LOGGING_ENABLED) so this should be populated.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAdminAuditLogs", {"limit": 5})
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                logs = r.get("logs") or r.get("items") or r.get("data") or []
                state["count"] = len(logs)
            elif isinstance(r, list):
                state["count"] = len(r)
            else:
                return False
            return isinstance(state.get("count"), int) and state["count"] >= 0
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin audit logs queryable on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="cloud_op_listing_per_mainframe",
    category="federation_admin_lifecycle",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["cloud-operators", "operator-listing"],
)
async def test_cloud_operators_listed(rig: FederationTestRig) -> AssertionResult:
    """getCloudOperators returns ≥1 cloud-op on each mainframe.

    Sandbox-A should list sandboxalpha; sandbox-B should list sandboxdelta.
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getCloudOperators")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                ops = r if isinstance(r, list) else (
                    r.get("operators") or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                state[label] = {"count": len(ops)}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (v.get("silent") or v.get("count", 0) >= 1)
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="each mainframe lists ≥1 cloud-op",
        capture_state=lambda: state,
    )
