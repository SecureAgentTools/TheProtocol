"""Diagnostic actions + checks inventory tests (§pass73.3.9 Batch 20).

3 read-only tests probing the diagnostic admin subsystem — used by the
Cassowary diagnostics dashboard for operator-driven health checks +
repair actions.
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
    name="diagnostic_checks_inventory",
    category="diagnostic_actions",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["diagnostics", "checks"],
)
async def test_diagnostic_checks(rig: FederationTestRig) -> AssertionResult:
    """getDiagnosticChecks returns ≥3 registered checks (supply-audit,
    spire-federation, etc.) with check_id, title, description."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getDiagnosticChecks")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            checks = r.get("checks") if isinstance(r, dict) else r
            if not isinstance(checks, list):
                state["bad_shape"] = type(checks).__name__
                return False
            state["count"] = len(checks)
            state["sample_ids"] = [
                c.get("check_id") for c in checks[:5] if isinstance(c, dict)
            ]
            return len(checks) >= 3
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="diagnostic checks inventory has ≥3 registered checks",
        capture_state=lambda: state,
    )


# §F6 group 4 (2026-09-27): retired, never ported (each reached into Frame A or Frame B from any frame)
RETIRED_ACTIONS = {"identity-network-reconnect", "spire-bundle-refresh"}

@federation_test(
    name="diagnostic_actions_inventory",
    category="diagnostic_actions",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["diagnostics", "actions"],
)
async def test_diagnostic_actions(rig: FederationTestRig) -> AssertionResult:
    """getDiagnosticActions returns the repair actions a frame's own operators get (nginx-reload, teg-restart), and
    neither Frame-A-era action: §F6 group 4 (2026-09-27) retired identity-network-reconnect and spire-bundle-refresh,
    which reached into Frame A and Frame B from whichever frame ran them."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getDiagnosticActions")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            actions = r.get("actions") if isinstance(r, dict) else r
            if not isinstance(actions, list):
                state["bad_shape"] = type(actions).__name__
                return False
            state["count"] = len(actions)
            state["sample_ids"] = [
                a.get("action_id") for a in actions[:5] if isinstance(a, dict)
            ]
            # Catch destructive actions for visibility
            state["destructive_count"] = sum(
                1 for a in actions if isinstance(a, dict) and a.get("destructive")
            )
            ids = {a.get("action_id") for a in actions if isinstance(a, dict)}
            state["retired_present"] = sorted(ids & RETIRED_ACTIONS)
            return len(actions) >= 2 and not state["retired_present"]
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="diagnostic actions inventory: this frame's operator actions, no Frame-A-era action",
        capture_state=lambda: state,
    )


@federation_test(
    name="diagnostic_targets_listing",
    category="diagnostic_actions",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["diagnostics", "targets"],
)
async def test_diagnostic_targets(rig: FederationTestRig) -> AssertionResult:
    """getDiagnosticTargets returns the inventory of target services
    that diagnostics can be run against (registry, teg, eventstore, ...)"""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getDiagnosticTargets")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                targets = r.get("targets")
                if not isinstance(targets, list):
                    state["bad_shape"] = type(targets).__name__
                    return False
                state["target_count"] = len(targets)
                # §MCPTEST30 (V0562): this passed on any dict with a key in it. The listing's shape is the claim: each
                # target named and typed, and a list with no operator saying why (V0561's reason_code)
                bad = [t for t in targets if not (isinstance(t, dict) and t.get("operator_id") and t.get("display_name")
                                                  and t.get("role") in ("mainframe", "operator", "frame"))]
                state["malformed"] = len(bad)
                state["roles"] = sorted({t.get("role") for t in targets if isinstance(t, dict)})
                operators = [t for t in targets if isinstance(t, dict) and not t.get("is_self")]
                state["reason_code"] = r.get("reason_code")
                return not bad and (bool(operators) or bool(r.get("reason_code")))
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="diagnostic targets inventory reachable",
        capture_state=lambda: state,
    )
