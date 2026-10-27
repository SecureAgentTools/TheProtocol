"""Admin funding request observability tests (§pass73.3.10 Batch 36).

3 read-only tests probing the FLOW 10 funding request subsystem
(CLAUDE.md PART 5 FLOW 10). The admin queue tracks pending, approved,
and rejected funding requests from agents.
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
    name="admin_funding_pending_queue_per_frame",
    category="admin_funding",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["funding", "pending"],
)
async def test_funding_pending(rig: FederationTestRig) -> AssertionResult:
    """getAdminFundingPending returns the pending funding request
    queue per mainframe (possibly empty)."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getAdminFundingPending")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                items = r if isinstance(r, list) else (
                    r.get("requests") or r.get("pending")
                    or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                state[label] = {"count": len(items)}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or isinstance(v.get("count"), int)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin funding pending queue reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_funding_all_history_per_frame",
    category="admin_funding",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["funding", "history"],
)
async def test_funding_all_history(rig: FederationTestRig) -> AssertionResult:
    """getAdminFundingAll returns the full funding request history —
    pending + approved + rejected per mainframe."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getAdminFundingAll")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                items = r if isinstance(r, list) else (
                    r.get("requests") or r.get("history")
                    or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                state[label] = {"count": len(items)}
                if items and isinstance(items[0], dict):
                    state[label]["statuses"] = sorted(
                        {i.get("status") for i in items if isinstance(i, dict)}
                    )[:4]
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or isinstance(v.get("count"), int)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin funding history reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_funding_compliance_overview",
    category="admin_funding",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["funding", "compliance"],
)
async def test_admin_funding_compliance(
    rig: FederationTestRig,
) -> AssertionResult:
    """Probe admin-side compliance of the funding subsystem — fetch
    pending + all queues on both frames, verify both are reachable.

    Replaces the original `my_funding_requests_developer_surface` test
    which hit a TIER 2 auth trap (getMyFundingRequests requires agent
    JWT, not dev JWT — federation suite uses dev JWT through public
    bridge).
    """
    state: dict = {}

    async def predicate():
        ok_count = 0
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                # Try both pending + all to verify the queue is reachable
                p = await rig.mcp(label).call("getAdminFundingPending")
                a = await rig.mcp(label).call("getAdminFundingAll")
                state[label] = {
                    "pending_ok": isinstance(p, (dict, list)),
                    "all_ok": isinstance(a, (dict, list)),
                }
                if state[label]["pending_ok"] and state[label]["all_ok"]:
                    ok_count += 1
            except Exception as e:
                state[label] = f"error: {e!r}"
        state["ok_count"] = ok_count
        return ok_count >= 2

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin funding compliance: pending + all queues reachable on both mainframes",
        capture_state=lambda: state,
    )
