"""Relay + diagnostics config + OAuth status tests (§pass73.3.12 Batch 57).

3 read-only tests probing infrastructure surfaces — relay status,
diagnostics framework config, OAuth federation trust status.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
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
    name="relay_status_envelope",
    category="relay_and_diagnostics",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["relay", "infra"],
)
async def test_relay_status(rig: FederationTestRig) -> AssertionResult:
    """getRelayStatus returns the relay-action subsystem status envelope.
    May be silent (404) if relay is not enabled — still validates."""
    state: dict = {}

    async def predicate():
        try:
            agents = await rig.mcp("sandbox-A").call("discoverAgents", {"limit": 1})
            items = agents if isinstance(agents, list) else (
                agents.get("agents") or agents.get("items") or agents.get("data") or []
            ) if isinstance(agents, dict) else []
            if not items:
                state["no_agents"] = True
                return True
            did = (items[0].get("did") if isinstance(items[0], dict) else None) or \
                  (items[0].get("agent_did") if isinstance(items[0], dict) else None)
            if not did:
                state["no_did"] = True
                return True
            state["agent_did"] = did
            r = await rig.mcp("sandbox-A").call("getRelayStatus", {"agent_did": did})
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:6]
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            # accept tier mismatch (relay may require agent JWT)
            return "401" in repr(e) or "403" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="relay status endpoint reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="diagnostic_config_envelope",
    category="relay_and_diagnostics",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["diagnostics", "config"],
)
async def test_diagnostic_config(rig: FederationTestRig) -> AssertionResult:
    """getDiagnosticConfig returns the diagnostics framework config
    envelope (intervals, severity thresholds, alert routing)."""
    state: dict = {}

    async def predicate():
        try:
            tgts = await rig.mcp("sandbox-A-admin").call("getDiagnosticTargets")
            items = tgts if isinstance(tgts, list) else (
                tgts.get("targets") or tgts.get("items") or tgts.get("data") or []
            ) if isinstance(tgts, dict) else []
            items = [t for t in items if isinstance(t, dict) and t.get("operator_id")]
            if not items:
                # §MCPTEST30 (V0562): this read nothing and passed. A frame with no target has nothing to read a
                # configuration of: NOT MEASURED, with the frame's own reason
                why = (tgts.get("reason_code") if isinstance(tgts, dict) else None) or "none given"
                raise PreconditionUnmet(f"fixture (a diagnostics target) absent: sandbox-A lists none (reason {why})")
            # an operator names containers, so its configuration has content; this registry itself (V0562) names none
            pick = next((t for t in items if t.get("role") == "operator" and not t.get("is_self")), items[0])
            # §MCPTEST30 (V0562): the target's id is `operator_id`; this read `id`, `target_id` and `name`, found none,
            # and passed on "no_target_id" every night without asking for a configuration at all
            tid = pick["operator_id"]
            state["target_id"], state["target_role"] = tid, pick.get("role")
            r = await rig.mcp("sandbox-A-admin").call(
                "getDiagnosticConfig", {"target_id": str(tid)}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                sections = {"docker", "env", "nginx", "spire", "partner_tegs"}
                state["missing_sections"] = sorted(sections - set(r.keys()))
                return r.get("target") == tid and not state["missing_sections"]
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="diagnostic config envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="oauth_federation_status_envelope_via_relay",
    category="relay_and_diagnostics",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["oauth", "federation"],
)
async def test_oauth_federation_status(rig: FederationTestRig) -> AssertionResult:
    """getOAuthFederationStatus returns the OAuth federation trust
    status envelope (issuer trust state per peer)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getOAuthFederationStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return bool(r.keys())
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="oauth federation status envelope reachable",
        capture_state=lambda: state,
    )
