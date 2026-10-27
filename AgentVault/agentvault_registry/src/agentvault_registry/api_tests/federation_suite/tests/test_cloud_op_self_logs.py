"""Cloud-op self-introspection observability tests (§pass73.3.10 Batch 35).

3 read-only tests probing the cloud-op self-introspection surfaces.
Cloud-ops are run by independent operators and can introspect their
own runtime state without going through the parent mainframe.
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


@federation_test(
    name="cloud_op_self_logs_per_cloudop",
    category="cloud_op_self_introspection",
    budget_sec=30.0,
    severity="low",
    requires=["sandboxalpha", "sandboxdelta"],
    tags=["cloud-op", "self-logs"],
)
async def test_cloud_op_self_logs(rig: FederationTestRig) -> AssertionResult:
    """An operator's own admin reads its registry's recent log lines through its own licence: operatorPortalSelfLogs
    on the operator, which forwards to the parent frame's self-logs route with the operator's FEDERATION_LICENSE_KEY.

    §MCPTEST30 (V0549): until V0549 this row called getCloudOperatorSelfLogs on each operator's ADMIN bridge, which no
    MCP caller can succeed with (an operator answers 503 "mainframe only"; a frame 401 for the licence header the tool
    never sends), and accepted the error as a pass: it was green every night on two 503s. It now reads the path an
    operator actually has, and passes only on lines read under the licence. It keeps counts, never a log line."""
    state: dict = {}

    async def predicate():
        for label in ("sandboxalpha", "sandboxdelta"):
            try:
                r = await rig.mcp(label).call("operatorPortalSelfLogs", {"lines": 10})
            except Exception as e:
                state[label] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
                continue
            if not isinstance(r, dict) or "_text" in r or not r:
                text = r.get("_text") if isinstance(r, dict) else r
                state[label] = {"refused": str(text)[:200]}
                continue
            out = r.get("output")
            state[label] = {
                "operator_name": r.get("operator_name"),
                "auth_mode": r.get("auth_mode"),
                "lines": len(out.splitlines()) if isinstance(out, str) else None,
            }
        return all(
            isinstance(v, dict) and v.get("auth_mode") == "federation_license" and v.get("operator_name")
            and isinstance(v.get("lines"), int) and v["lines"] > 0
            for v in state.values()
        ) and len(state) == 2

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate, poll_interval_sec=5.0,
        description="each operator's own admin reads its registry's log lines through its licence (operatorPortalSelfLogs)",
        capture_state=lambda: state,
    )


# §MCPTEST30 (V0550): an operator's APPLICANT reads it on the PARENT frame. getOperatorMyStatus and getOperatorMyLifecycle
# serve the developer who applied for an operator, on the frame that approved it (the operators router is mainframe-only).
# These two rows called them on the operators themselves, met 503 "mainframe only" and 404 "No operator application found
# for this developer account", and accepted both as a pass; V0549 made them NOT MEASURED (`unanswered`). Measured
# 2026-10-02: on sbx-alpha the frame admin applied for sbxalphaop, on sbx-beta for sbxbetaop, and the rig holds both
# logins (sandbox-A, sandbox-B). Each operator's name is read from its own registry card, never a literal.
_PARENTS = (("sandbox-A", "sandboxalpha"), ("sandbox-B", "sandboxdelta"))


async def _operator_name(rig: FederationTestRig, label: str):
    card = await rig.mcp(label).call("getRegistryCard")
    ident = card.get("identity") if isinstance(card, dict) and isinstance(card.get("identity"), dict) else {}
    return ident.get("registry_name")


def _application(r):
    app = r.get("application") if isinstance(r, dict) else None
    return app if isinstance(app, dict) else None


@federation_test(
    name="operator_portal_self_status_per_cloudop",
    category="cloud_op_self_introspection",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B", "sandboxalpha", "sandboxdelta"],
    tags=["cloud-op", "operator-portal"],
)
async def test_operator_portal_self_status(
    rig: FederationTestRig,
) -> AssertionResult:
    """The applicant of each operator reads the operator's status on its parent: getOperatorMyStatus answers with the
    application whose name is the operator's own (its card's) and whose status is approved."""
    state: dict = {}

    async def predicate():
        for parent, op in _PARENTS:
            try:
                want = await _operator_name(rig, op)
                r = await rig.mcp(parent).call("getOperatorMyStatus")
            except Exception as e:
                state[parent] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
                continue
            app = _application(r)
            state[parent] = {"operator": want, "application": (app or {}).get("name"),
                             "status": (app or {}).get("status"),
                             "refused": str(r.get("_text"))[:200] if isinstance(r, dict) and "_text" in r else None}
        return len(state) == 2 and all(
            v.get("operator") and v.get("application") == v.get("operator") and v.get("status") == "approved"
            for v in state.values())

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate, poll_interval_sec=5.0,
        description="each operator's applicant reads its approved application on the parent frame (getOperatorMyStatus)",
        capture_state=lambda: state,
    )


@federation_test(
    name="operator_lifecycle_per_cloudop_self_view",
    category="cloud_op_self_introspection",
    budget_sec=20.0,
    severity="low",
    requires=["sandbox-A", "sandbox-B", "sandboxalpha", "sandboxdelta"],
    tags=["cloud-op", "lifecycle"],
)
async def test_operator_my_lifecycle(rig: FederationTestRig) -> AssertionResult:
    """The applicant of each operator reads the operator's lifecycle on its parent: getOperatorMyLifecycle answers with
    the operator's own application, its federation licence and its peer row."""
    state: dict = {}

    async def predicate():
        for parent, op in _PARENTS:
            try:
                want = await _operator_name(rig, op)
                r = await rig.mcp(parent).call("getOperatorMyLifecycle")
            except Exception as e:
                state[parent] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
                continue
            app = _application(r)
            state[parent] = {"operator": want, "application": (app or {}).get("name"),
                             "licence": bool(isinstance(r, dict) and r.get("federation_license")),
                             "peer_row": bool(isinstance(r, dict) and r.get("peer_registry")),
                             "refused": str(r.get("_text"))[:200] if isinstance(r, dict) and "_text" in r else None}
        return len(state) == 2 and all(
            v.get("operator") and v.get("application") == v.get("operator") and v.get("licence") and v.get("peer_row")
            for v in state.values())

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate, poll_interval_sec=5.0,
        description="each operator's applicant reads its lifecycle on the parent frame: application, licence, peer row",
        capture_state=lambda: state,
    )
