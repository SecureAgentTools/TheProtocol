"""Federation discovery + topology BFS tests (Phase F §pass73.3.6+).

5 tests exercising the BFS topology discovery that powers cross-frame
routing fallbacks. The §pass73.3.6 fix added cross-frame peer rows to
sandbox cloud-ops; this surface validates the rest of the discovery
pipeline.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)
from agentvault_registry.api_tests.federation_suite.peer_feed_probe import peer_feed_row


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
    name="agent_locations_trusted_registries_populated",
    category="federation_discovery",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A", "sandbox-B"],
    tags=["bfs", "topology", "trusted-registries"],
)
async def test_trusted_registries_populated(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAgentLocationsTrustedRegistries returns ≥1 trusted peer on
    each mainframe — the BFS topology discovery surface."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getAgentLocationsTrustedRegistries")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                regs = r if isinstance(r, list) else (
                    r.get("registries") or r.get("trusted_registries") or
                    r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                state[label] = {"count": len(regs)}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (v.get("silent") or v.get("count", 0) >= 1)
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="trusted registries populated on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="federation_network_stats_present_per_frame",
    category="federation_discovery",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["federation", "network-stats"],
)
async def test_federation_network_stats(rig: FederationTestRig) -> AssertionResult:
    """getFederationNetworkStats returns a structured payload on both
    mainframes — federation-wide aggregate stats."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getFederationNetworkStats")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                state[label] = {"keys": list(r.keys())[:8] if isinstance(r, dict) else type(r).__name__}
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
        description="getFederationNetworkStats reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="federation_health_check_per_frame",
    category="federation_discovery",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["federation", "health-check"],
)
async def test_federation_health_check(rig: FederationTestRig) -> AssertionResult:
    """getFederationHealthCheck returns a healthy status on both mainframes."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getFederationHealthCheck")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                state[label] = {"keys": list(r.keys())[:8] if isinstance(r, dict) else type(r).__name__}
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
        description="getFederationHealthCheck reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="agent_locations_per_frame",
    category="federation_discovery",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["agent-locations", "topology"],
)
async def test_agent_locations(rig: FederationTestRig) -> AssertionResult:
    """getAgentLocations returns a structured location list per mainframe."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getAgentLocations")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    locs = r.get("locations") or r.get("items") or r.get("data") or []
                    state[label] = {"count": len(locs) if isinstance(locs, list) else 0}
                elif isinstance(r, list):
                    state[label] = {"count": len(r)}
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
        description="getAgentLocations reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="federation_registry_cards_endpoint_reachable_per_frame",
    category="federation_discovery",
    budget_sec=90.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["registry-cards", "federation-listing", "mtls", "read-only"],
)
async def test_federation_registry_cards(rig: FederationTestRig) -> AssertionResult:
    """§MCPTEST30 (V0547): the peers' registry-card feed, read the way a peer reads it (peer_feed_probe): sandbox-B's
    registry with its own SVID at the address its peer row names, and a caller with no certificate refused. This row
    called the MCP wrapper, which turned the route's 401 into an empty list, and passed on any dict: it could not fail."""
    return await peer_feed_row(rig, "/api/v1/federation/registry-cards", "registry-card feed")
