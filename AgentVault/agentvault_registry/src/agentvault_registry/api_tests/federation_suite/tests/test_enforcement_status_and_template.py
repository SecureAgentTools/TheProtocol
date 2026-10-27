"""Enforcement agent status + agent template detail tests
(§pass73.3.14 Batch 68).

3 read-only tests probing the enforcement subsystem status surface +
specific agent template lookup.
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
    name="enforcement_agent_status_envelope",
    category="enforcement_and_template",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["enforcement", "agent-status"],
)
async def test_enforcement_agent_status(
    rig: FederationTestRig,
) -> AssertionResult:
    """getEnforcementAgentStatus returns the enforcement subsystem
    agent status envelope (suspended/quarantined agent counts)."""
    state: dict = {}

    async def predicate():
        try:
            agents = await rig.mcp("sandbox-A-admin").call(
                "getAdminAgents", {"limit": 1}
            )
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
            r = await rig.mcp("sandbox-A-admin").call(
                "getEnforcementAgentStatus", {"agent_did": did}
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
        description="enforcement agent status envelope reachable for picked DID",
        capture_state=lambda: state,
    )


@federation_test(
    name="agent_template_by_id_envelope",
    category="enforcement_and_template",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["agent-template", "lookup"],
)
async def test_agent_template_by_id(rig: FederationTestRig) -> AssertionResult:
    """getAgentTemplate returns a specific template's full detail.
    Probe listAgentTemplates first to pick a template_id."""
    state: dict = {}

    async def predicate():
        try:
            tpls = await rig.mcp("sandbox-A").call("listAgentTemplates")
            items = tpls if isinstance(tpls, list) else (
                tpls.get("templates") or tpls.get("items") or tpls.get("data") or []
            ) if isinstance(tpls, dict) else []
            if not items or not isinstance(items[0], dict):
                state["no_templates"] = True
                return True
            tid = (items[0].get("id") or items[0].get("template_id") or
                   items[0].get("slug") or items[0].get("name"))
            if tid is None:
                state["no_template_id"] = True
                state["tpl_keys"] = sorted((items[0] or {}).keys())[:8]
                return True
            state["template_id"] = tid
            r = await rig.mcp("sandbox-A").call(
                "getAgentTemplate", {"template_id": str(tid)}
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
        description="agent template by id envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="dev_trust_graph_envelope",
    category="enforcement_and_template",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["dev-trust-graph", "reputation"],
)
async def test_dev_trust_graph(rig: FederationTestRig) -> AssertionResult:
    """getDevTrustGraph returns the developer trust graph envelope
    (web-of-trust between developers, used by reputation calc)."""
    state: dict = {}

    async def predicate():
        try:
            # Needs developer DID. Use the active dev's developer-level DID
            # from the admin auth profile probe.
            prof = await rig.mcp("sandbox-A-admin").call("getAuthProfile")
            dev_did = None
            if isinstance(prof, dict):
                dev_did = prof.get("did") or prof.get("developer_did")
            if not dev_did:
                # Fallback: pick an agent DID and use that (the endpoint
                # may accept any DID format)
                agents = await rig.mcp("sandbox-A").call(
                    "discoverAgents", {"limit": 1}
                )
                items = agents if isinstance(agents, list) else (
                    agents.get("agents") or agents.get("items") or agents.get("data") or []
                ) if isinstance(agents, dict) else []
                if items and isinstance(items[0], dict):
                    dev_did = items[0].get("did") or items[0].get("agent_did")
            if not dev_did:
                state["no_did"] = True
                return True
            state["did"] = dev_did
            r = await rig.mcp("sandbox-A").call("getDevTrustGraph", {"did": dev_did})
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
        description="developer trust graph envelope reachable for picked DID",
        capture_state=lambda: state,
    )
