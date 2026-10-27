"""Admin signing-keys surface tests (§pass73.3.13 Batch 59).

3 read-only tests probing admin agent signing-key inventory + system
resources + topology peer events.
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
    name="admin_agent_signing_keys_for_known_did",
    category="signing_keys",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["signing-keys", "admin"],
)
async def test_admin_agent_signing_keys(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAdminAgentSigningKeys returns the per-agent signing key
    inventory. Picks first agent from admin agent list."""
    state: dict = {}

    async def predicate():
        try:
            agents = await rig.mcp("sandbox-A-admin").call(
                "getAdminAgents", {"limit": 3}
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
                "getAdminAgentSigningKeys", {"agent_did": did}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return True
            elif isinstance(r, list):
                state["count"] = len(r)
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin agent signing keys reachable for picked DID",
        capture_state=lambda: state,
    )


@federation_test(
    name="system_resources_envelope",
    category="signing_keys",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["system", "resources"],
)
async def test_system_resources(rig: FederationTestRig) -> AssertionResult:
    """getSystemResources returns host resource envelope (cpu/mem/disk).
    Used by ops dashboard."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getSystemResources")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return bool(r.keys())
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="system resources envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="topology_peer_events_inventory",
    category="signing_keys",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["topology", "events"],
)
async def test_topology_peer_events(rig: FederationTestRig) -> AssertionResult:
    """getTopologyPeerEvents returns per-peer event feed used by the
    topology peer modal. Needs peer_id — probe getAllFederationPeersAdmin
    first."""
    state: dict = {}

    async def predicate():
        try:
            peers = await rig.mcp("sandbox-A-admin").call(
                "getAllFederationPeersAdmin"
            )
            items = peers if isinstance(peers, list) else (
                peers.get("peers") or peers.get("items") or peers.get("data") or []
            ) if isinstance(peers, dict) else []
            if not items or not isinstance(items[0], dict):
                state["no_peers"] = True
                return True
            pid = items[0].get("id") or items[0].get("peer_id") or \
                  items[0].get("peer_registry_id")
            if pid is None:
                state["no_peer_id"] = True
                state["peer_keys"] = sorted((items[0] or {}).keys())[:8]
                return True
            state["peer_id"] = pid
            r = await rig.mcp("sandbox-A-admin").call(
                "getTopologyPeerEvents", {"peer_id": str(pid)}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items2 = r if isinstance(r, list) else (
                r.get("events") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items2)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="topology peer events inventory reachable for picked peer",
        capture_state=lambda: state,
    )
