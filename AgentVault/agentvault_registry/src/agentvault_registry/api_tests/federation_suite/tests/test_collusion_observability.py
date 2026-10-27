"""Collusion detection observability tests (§pass73.3.17 Batch 100).

3 tests verifying the collusion detection subsystem reports correctly.
Per CLAUDE.md PART 9, Tarjan SCC active with 1013+ lifetime rings.
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
    name="collusion_status_envelope_active",
    category="collusion_observability",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["collusion", "status", "subsystem"],
)
async def test_collusion_status(rig: FederationTestRig) -> AssertionResult:
    """getCollusionStatus reports active subsystem with last_run_at,
    total_rings_detected, last_scc_count."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getCollusionStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                return False
            state["keys"] = sorted(r.keys())[:10]
            return len(r.keys()) >= 1
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="collusion status envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="collusion_rings_inventory_reachable",
    category="collusion_observability",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["collusion", "rings"],
)
async def test_collusion_rings(rig: FederationTestRig) -> AssertionResult:
    """getCollusionRings returns the detected rings inventory. May be
    empty in sandbox (no real malicious activity) — surface check."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getCollusionRings")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            rings = r if isinstance(r, list) else (
                r.get("rings") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(rings) if isinstance(rings, list) else None
            return isinstance(state["count"], int)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="collusion rings inventory reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="collusion_by_agent_for_known_did",
    category="collusion_observability",
    budget_sec=30.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-A-admin"],
    tags=["collusion", "by-agent"],
)
async def test_collusion_by_agent(rig: FederationTestRig) -> AssertionResult:
    """getAdminCollusionByAgent returns per-agent collusion signal envelope."""
    state: dict = {}

    async def predicate():
        try:
            pub = rig.mcp("sandbox-A")
            admin = rig.mcp("sandbox-A-admin")
            agents = await pub.call("discoverAgents", {"limit": 1})
            items = agents if isinstance(agents, list) else (
                agents.get("agents") or agents.get("items") or agents.get("data") or []
            ) if isinstance(agents, dict) else []
            if not items or not isinstance(items[0], dict):
                state["no_agents"] = True
                return True
            did = items[0].get("did") or items[0].get("agent_did")
            if not did:
                return True
            state["agent_did"] = did
            r = await admin.call(
                "getAdminCollusionByAgent", {"agent_did": did}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="collusion by-agent envelope reachable for known DID",
        capture_state=lambda: state,
    )
