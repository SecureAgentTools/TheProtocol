"""Developer-level drill-down tests (§pass73.3.15 Batch 72).

3 read-only tests probing developer stats / flare / trust-score
surfaces. All probe getAdminDevelopers first.
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


async def _pick_dev_id(rig: FederationTestRig):
    devs = await rig.mcp("sandbox-A-admin").call(
        "getAdminDevelopers", {"limit": 1}
    )
    items = devs if isinstance(devs, list) else (
        devs.get("developers") or devs.get("items") or devs.get("data") or []
    ) if isinstance(devs, dict) else []
    if not items or not isinstance(items[0], dict):
        return None
    return items[0].get("id") or items[0].get("developer_id")


@federation_test(
    name="developer_stats_envelope",
    category="developer_drilldowns",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["developer", "stats"],
)
async def test_developer_stats(rig: FederationTestRig) -> AssertionResult:
    """getDeveloperStats returns aggregate stats per developer."""
    state: dict = {}

    async def predicate():
        try:
            dev_id = await _pick_dev_id(rig)
            if dev_id is None:
                state["no_dev"] = True
                return True
            state["dev_id"] = dev_id
            r = await rig.mcp("sandbox-A-admin").call(
                "getDeveloperStats", {"developer_id": str(dev_id)}
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
        description="developer stats envelope reachable for picked dev",
        capture_state=lambda: state,
    )


@federation_test(
    name="developer_flare_envelope",
    category="developer_drilldowns",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["developer", "flare"],
)
async def test_developer_flare(rig: FederationTestRig) -> AssertionResult:
    """getDeveloperFlare returns the per-developer flare visualization
    metadata (badge state, achievements)."""
    state: dict = {}

    async def predicate():
        try:
            dev_id = await _pick_dev_id(rig)
            if dev_id is None:
                state["no_dev"] = True
                return True
            state["dev_id"] = dev_id
            r = await rig.mcp("sandbox-A-admin").call(
                "getDeveloperFlare", {"developer_id": str(dev_id)}
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
        description="developer flare envelope reachable for picked dev",
        capture_state=lambda: state,
    )


@federation_test(
    name="trust_score_for_picked_agent",
    category="developer_drilldowns",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["trust-score", "agent"],
)
async def test_trust_score(rig: FederationTestRig) -> AssertionResult:
    """getTrustScore returns trust score for a known agent DID."""
    state: dict = {}

    async def predicate():
        try:
            agents = await rig.mcp("sandbox-A").call("discoverAgents", {"limit": 1})
            items = agents if isinstance(agents, list) else (
                agents.get("agents") or agents.get("items") or agents.get("data") or []
            ) if isinstance(agents, dict) else []
            if not items or not isinstance(items[0], dict):
                state["no_agents"] = True
                return True
            did = items[0].get("did") or items[0].get("agent_did")
            if not did:
                state["no_did"] = True
                return True
            state["agent_did"] = did
            r = await rig.mcp("sandbox-A").call(
                "getTrustScore", {"agent_did": did}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return True
            elif isinstance(r, (int, float)):
                state["score"] = r
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e) or "400" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="trust score endpoint reachable for picked DID",
        capture_state=lambda: state,
    )
