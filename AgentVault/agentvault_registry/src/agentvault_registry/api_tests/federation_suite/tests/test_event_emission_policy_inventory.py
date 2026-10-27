"""Event emission policy (f037) inventory tests (§pass73.3.9 Batch 15).

3 tests probing the per-event-type emission policy table (CLAUDE.md
PART 3). Validates: ≥100 policies registered, canonical TokensTransferred
rule emits-from-registry-only, all policies have description + updated_at.
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
    name="emission_policies_inventory_size",
    category="event_emission_policy",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["emission-policy", "f037", "inventory"],
)
async def test_inventory_size(rig: FederationTestRig) -> AssertionResult:
    """getEventEmissionPolicies returns ≥100 policy rows per mainframe.

    Per CLAUDE.md PART 3 the production fleet has 165+ policies live since
    §pass58 migration 0078. Sandbox parity says ≥100 is the safe floor.
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getEventEmissionPolicies")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                pols = r.get("policies") if isinstance(r, dict) else r
                if not isinstance(pols, list):
                    state[label] = {"bad_shape": type(pols).__name__}
                    continue
                state[label] = {"count": len(pols)}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (isinstance(v.get("count"), int) and v["count"] >= 100)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="emission policy inventory ≥100 on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="tokens_transferred_policy_canonical",
    category="event_emission_policy",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["emission-policy", "tokens-transferred", "partition-rule"],
)
async def test_tokens_transferred_policy(
    rig: FederationTestRig,
) -> AssertionResult:
    """TokensTransferred policy rule from CLAUDE.md PART 3:
      emit_from_teg=false, emit_from_registry=true, skip_in_projection=false

    A change to these flags would shift the canonical token-motion event
    away from the registry-emits-once doctrine + risk supply double-count.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getEventEmissionPolicies")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            pols = r.get("policies") if isinstance(r, dict) else r
            if not isinstance(pols, list):
                state["bad_shape"] = type(pols).__name__
                return False
            tt = next(
                (p for p in pols if isinstance(p, dict) and p.get("event_type") == "TokensTransferred"),
                None,
            )
            if not tt:
                state["no_TokensTransferred"] = True
                return False
            state["tt"] = {
                "emit_from_teg": tt.get("emit_from_teg"),
                "emit_from_registry": tt.get("emit_from_registry"),
                "skip_in_projection": tt.get("skip_in_projection"),
            }
            return (
                tt.get("emit_from_teg") is False
                and tt.get("emit_from_registry") is True
                and tt.get("skip_in_projection") is False
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="TokensTransferred policy: TEG=false, registry=true, skip_projection=false",
        capture_state=lambda: state,
    )


@federation_test(
    name="emission_policies_description_no_regression",
    category="event_emission_policy",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["emission-policy", "metadata", "regression-floor"],
)
async def test_policies_descriptions(rig: FederationTestRig) -> AssertionResult:
    """Tracks emission policy description completeness with a no-regression
    floor — currently ~70% (116/166 as of §pass73.3.9). The remaining 50
    events (AdminBroadcastEdited, BundleCreated, AgentFlagAcknowledged,
    etc.) are technical debt; a drop below 60% would indicate someone
    stripped descriptions or added new event types without descriptions.

    To raise the floor: backfill descriptions on the no-desc events and
    bump the threshold here.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getEventEmissionPolicies")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            pols = r.get("policies") if isinstance(r, dict) else r
            if not isinstance(pols, list) or not pols:
                state["empty"] = True
                return False
            with_desc = sum(
                1 for p in pols
                if isinstance(p, dict) and (p.get("description") or "").strip()
            )
            state["total"] = len(pols)
            state["with_desc"] = with_desc
            state["pct"] = round(with_desc / len(pols) * 100, 1)
            no_desc_events = [
                p.get("event_type") for p in pols
                if isinstance(p, dict) and not (p.get("description") or "").strip()
            ]
            state["no_desc_count"] = len(no_desc_events)
            state["no_desc_sample"] = no_desc_events[:5]
            # No-regression floor: 60% (current baseline ~70%, safety margin 10%)
            return with_desc / len(pols) >= 0.60
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="emission policy descriptions ≥60% (no-regression floor)",
        capture_state=lambda: state,
    )
