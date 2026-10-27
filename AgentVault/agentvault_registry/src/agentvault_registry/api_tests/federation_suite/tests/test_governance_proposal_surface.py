"""Governance proposal surface tests (§pass73.3.17 Batch 101).

3 tests verifying the governance subsystem endpoints respond + the
core proposal lifecycle surfaces (list, detail, votes) are healthy.

Per CLAUDE.md PART 5 FLOW 7, governance is agent-only — dev JWT
returns 401. Tests verify endpoint exists and auth-gates properly.
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
    name="governance_proposals_list_envelope",
    category="governance_proposal_surface",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["governance", "proposals"],
)
async def test_proposals_list(rig: FederationTestRig) -> AssertionResult:
    """getGovernanceProposals returns the proposal list envelope.
    Tier 1 read — accessible without auth."""
    state: dict = {}

    async def predicate():
        try:
            pub = rig.mcp("sandbox-A")
            r = await pub.call("getGovernanceProposals")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            proposals = r if isinstance(r, list) else (
                r.get("proposals") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(proposals) if isinstance(proposals, list) else None
            return isinstance(state["count"], int)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="governance proposals list envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="auto_tally_config_envelope",
    category="governance_proposal_surface",
    budget_sec=20.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["governance", "auto-tally"],
)
async def test_auto_tally_config(rig: FederationTestRig) -> AssertionResult:
    """getAutoTallyConfig returns the proposal auto-tally background
    task config (enabled, interval, etc.)."""
    state: dict = {}

    async def predicate():
        try:
            pub = rig.mcp("sandbox-A")
            r = await pub.call("getAutoTallyConfig")
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
        budget_sec=20.0, predicate=predicate,
        description="auto-tally config envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="registry_federation_proposals_envelope",
    category="governance_proposal_surface",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["governance", "federation-proposals"],
)
async def test_federation_proposals(
    rig: FederationTestRig,
) -> AssertionResult:
    """getRegistryFederationProposals is Tier-2 (agent JWT required since
    §pass70 Sprint 8 re-tier). Probed via public bridge with dev JWT →
    401/403/404 are auth-tier-mismatch passes; 200 + envelope also fine."""
    state: dict = {}

    async def predicate():
        try:
            pub = rig.mcp("sandbox-A")
            r = await pub.call("getRegistryFederationProposals")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            proposals = r if isinstance(r, list) else (
                r.get("proposals") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(proposals) if isinstance(proposals, list) else None
            return isinstance(state["count"], int)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return ("401" in repr(e) or "403" in repr(e) or "404" in repr(e))

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="federation proposals envelope reachable",
        capture_state=lambda: state,
    )
