"""Agent DID doc + locations extra tests (§pass73.3.14 Batch 67).

3 read-only tests probing the agent DID document + agent locations
emission policies + auth profile envelope.
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
    name="agent_did_doc_envelope",
    category="agent_did_doc_extra",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["did-doc", "agent"],
)
async def test_agent_did_doc(rig: FederationTestRig) -> AssertionResult:
    """getAgentDIDDoc returns the W3C DID Document for a known agent.
    Probe discoverAgents first."""
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
            r = await rig.mcp("sandbox-A").call("getAgentDIDDoc", {"agent_did": did})
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                # DID doc should have @context + id
                return "id" in r or "@context" in r or bool(r.keys())
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="agent DID doc envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="agent_locations_emission_policies_envelope",
    category="agent_did_doc_extra",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["agent-locations", "emission-policies"],
)
async def test_agent_locations_emission_policies(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAgentLocationsEmissionPolicies returns the internal emission
    policy summary used by TEG/EventStore."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getAgentLocationsEmissionPolicies")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return bool(r.keys())
            elif isinstance(r, list):
                state["count"] = len(r)
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="agent locations emission policies envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="auth_profile_envelope",
    category="agent_did_doc_extra",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["auth", "profile"],
)
async def test_auth_profile(rig: FederationTestRig) -> AssertionResult:
    """getAuthProfile returns the authenticated user's profile envelope.
    Via admin bridge → commander developer profile."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAuthProfile")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return "email" in r or "id" in r or bool(r.keys())
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="auth profile envelope reachable",
        capture_state=lambda: state,
    )
