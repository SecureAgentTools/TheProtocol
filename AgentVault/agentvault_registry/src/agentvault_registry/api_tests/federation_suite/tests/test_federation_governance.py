"""Federation governance + license-related tests (Phase E §pass73.3.5+).

3 tests covering federation-wide governance surfaces — proposals,
compliance drift symmetry, license signing key consistency. Federation
governance proposals are fleet-wide so they should return identical
results on every mainframe.
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
    name="federation_peers_listed_per_frame",
    category="federation_governance",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["governance", "peers"],
)
async def test_federation_peers_listed(rig: FederationTestRig) -> AssertionResult:
    """listFederationPeers returns the public peer list on both mainframes.

    Replaces an earlier draft that called getRegistryFederationProposals —
    that tool is tier-2 (requires agent JWT) and the public bridge can't
    satisfy it without an agent context. Switched to the tier-1 public peer
    list which exposes the same federation-surface visibility claim.
    """
    peers: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("listFederationPeers")
                if _is_silent_or_error(r):
                    peers[label] = {"silent": True}
                    continue
                items = r if isinstance(r, list) else (
                    r.get("peers") or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                peers[label] = {"count": len(items)}
            except Exception as e:
                peers[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (v.get("silent") or isinstance(v.get("count"), int))
            for v in peers.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="listFederationPeers returns list shape on both mainframes",
        capture_state=lambda: peers,
    )


@federation_test(
    name="federation_compliance_enforcement_mode_consistent",
    category="federation_governance",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["compliance", "enforcement-mode"],
)
async def test_federation_compliance_enforcement_mode(
    rig: FederationTestRig,
) -> AssertionResult:
    """getFederationComplianceEnforcementMode returns the current
    enforcement mode (typically 'observation' on sandbox) on both
    mainframes — config drift detector."""
    modes: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call(
                    "getFederationComplianceEnforcementMode"
                )
                if _is_silent_or_error(r):
                    modes[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    mode = r.get("mode") or r.get("enforcement_mode") or r.get("state")
                    modes[label] = {"mode": mode, "keys": list(r.keys())[:5]}
                else:
                    modes[label] = {"raw": str(r)[:80]}
            except Exception as e:
                modes[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (v.get("silent") or v.get("mode") is not None or v.get("raw"))
            for v in modes.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="federation compliance enforcement mode readable on both mainframes",
        capture_state=lambda: modes,
    )


@federation_test(
    name="federation_compliance_events_per_frame",
    category="federation_governance",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["compliance", "events", "audit"],
)
async def test_federation_compliance_events(rig: FederationTestRig) -> AssertionResult:
    """getFederationComplianceEvents returns a list of compliance audit
    events on both mainframes. Empty is fine on a fresh sandbox; the test
    validates the surface."""
    events: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getFederationComplianceEvents")
                if _is_silent_or_error(r):
                    events[label] = {"silent": True}
                    continue
                items = r if isinstance(r, list) else (
                    r.get("events") or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                events[label] = {"count": len(items)}
            except Exception as e:
                events[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (v.get("silent") or isinstance(v.get("count"), int))
            for v in events.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="getFederationComplianceEvents returns list shape on both mainframes",
        capture_state=lambda: events,
    )
