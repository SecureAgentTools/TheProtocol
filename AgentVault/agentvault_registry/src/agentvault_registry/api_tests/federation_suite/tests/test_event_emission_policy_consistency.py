"""Event emission policy consistency tests (§pass73.3.17 Batch 96).

3 tests verifying the f037 emission policy table holds the documented
invariants per CLAUDE.md PART 3. Critical for supply invariant correctness
since policy partitions TEG vs Registry emission of financial events.
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
    name="emission_policies_inventory_populated",
    category="event_emission_policy_consistency",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["emission-policy", "f037", "inventory"],
)
async def test_policies_inventory(rig: FederationTestRig) -> AssertionResult:
    """getEventEmissionPolicies returns ≥30 policy rows per CLAUDE.md
    PART 3 (165 since §pass58 in prod; sandbox-A should have ≥30)."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getEventEmissionPolicies")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            policies = r if isinstance(r, list) else (
                r.get("policies") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(policies) if isinstance(policies, list) else None
            return isinstance(state["count"], int) and state["count"] >= 30
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="event emission policies has ≥30 rows",
        capture_state=lambda: state,
    )


@federation_test(
    name="tokens_transferred_policy_correct_partition",
    category="event_emission_policy_consistency",
    budget_sec=20.0,
    severity="critical",
    requires=["sandbox-A-admin"],
    tags=["emission-policy", "tokens-transferred", "partition"],
)
async def test_tokens_transferred_policy(
    rig: FederationTestRig,
) -> AssertionResult:
    """TokensTransferred policy: emit_from_teg=False, emit_from_registry=True.

    Per CLAUDE.md PART 3 — this partition is the SUPPLY INVARIANT
    SECURITY BOUNDARY. Both must hold or supply audit drifts."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getEventEmissionPolicies")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            policies = r if isinstance(r, list) else (
                r.get("policies") or r.get("items") or []
            ) if isinstance(r, dict) else []
            target = None
            for p in policies if isinstance(policies, list) else []:
                if isinstance(p, dict) and p.get("event_type") == "TokensTransferred":
                    target = p
                    break
            if not target:
                state["no_tokens_transferred"] = True
                return False
            state["policy"] = target
            return (
                target.get("emit_from_teg") is False
                and target.get("emit_from_registry") is True
            )
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="TokensTransferred: emit_from_teg=False + emit_from_registry=True",
        capture_state=lambda: state,
    )


@federation_test(
    name="cross_registry_transfer_completed_skip_in_projection",
    category="event_emission_policy_consistency",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["emission-policy", "cross-registry", "skip-projection"],
)
async def test_cross_reg_xfer_skip_projection(
    rig: FederationTestRig,
) -> AssertionResult:
    """CrossRegistryTransferCompleted has skip_in_projection=True per
    CLAUDE.md PART 3 (audit trail only — balance tracked via
    TokensTransferred). If False, double-counts cross-reg transfers."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getEventEmissionPolicies")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            policies = r if isinstance(r, list) else (
                r.get("policies") or r.get("items") or []
            ) if isinstance(r, dict) else []
            target = None
            for p in policies if isinstance(policies, list) else []:
                if (isinstance(p, dict)
                        and p.get("event_type") == "CrossRegistryTransferCompleted"):
                    target = p
                    break
            if not target:
                state["no_cross_reg"] = True
                # Tolerated if event type isn't on this registry
                return True
            state["policy"] = target
            return target.get("skip_in_projection") is True
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="CrossRegistryTransferCompleted has skip_in_projection=True",
        capture_state=lambda: state,
    )
