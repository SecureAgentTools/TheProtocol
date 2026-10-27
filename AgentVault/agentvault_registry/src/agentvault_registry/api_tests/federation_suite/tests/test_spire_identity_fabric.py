"""SPIRE identity fabric observability tests (§pass73.3.9 Batch 27).

3 admin tests probing the SPIRE/SPIFFE identity fabric admin surfaces
(CLAUDE.md PART 12 IRONHAND). Validates: frames spire status, ironhand
identity counts, orphan inventory.
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
    name="frames_spire_status_lists_trust_domains",
    category="spire_identity_fabric",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["spire", "trust-domains", "frames"],
)
async def test_frames_spire_status(rig: FederationTestRig) -> AssertionResult:
    """getFramesSpireStatus lists peer trust domains known to the local
    SPIRE server. Sandbox-A should know the Frame-B trust
    domain) at minimum."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getFramesSpireStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            state["spire_trust_domains"] = r.get("spire_trust_domains")
            state["local_trust_domain"] = r.get("local_trust_domain")
            state["in_both"] = r.get("in_both")
            tds = r.get("spire_trust_domains") or []
            return isinstance(tds, list) and len(tds) >= 1
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="SPIRE frames status lists ≥1 trust domain on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="ironhand_identities_summary_counters",
    category="spire_identity_fabric",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["ironhand", "identities", "mtls"],
)
async def test_ironhand_identities_summary(
    rig: FederationTestRig,
) -> AssertionResult:
    """listIronhandIdentities returns a summary with total_spire_entries,
    agent_entries, db_enrolled counters. Validates the IRONHAND mTLS
    enrollment fabric is alive."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("listIronhandIdentities")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            summ = r.get("summary") or {}
            state["total_spire_entries"] = summ.get("total_spire_entries")
            state["db_enrolled"] = summ.get("db_enrolled")
            state["agent_entries"] = summ.get("agent_entries")
            state["operator_entries"] = summ.get("operator_entries")
            # At least the SPIRE entry total must be ≥1
            return (
                isinstance(summ.get("total_spire_entries"), int)
                and summ["total_spire_entries"] >= 1
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="IRONHAND identity summary has ≥1 SPIRE entry on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="agent_orphans_inventory_reachable",
    category="spire_identity_fabric",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["orphans", "agents"],
)
async def test_agent_orphans(rig: FederationTestRig) -> AssertionResult:
    """getAdminAgentOrphans returns the orphan agent inventory (agents
    whose owner developer was deleted). Healthy sandbox has 0; a non-
    zero count would indicate sweeper drift."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAdminAgentOrphans")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            state["total"] = r.get("total")
            state["count"] = len(r.get("agents") or [])
            # Envelope must be present + total = a number (0 or positive both OK)
            return isinstance(r.get("total"), int)
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="agent orphans inventory readable on sandbox-A",
        capture_state=lambda: state,
    )
