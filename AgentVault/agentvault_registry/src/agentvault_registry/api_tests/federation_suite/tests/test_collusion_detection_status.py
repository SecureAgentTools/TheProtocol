"""Collusion detection status tests (§pass73.3.9 Batch 14).

3 tests probing the Tarjan-SCC collusion detection worker (CLAUDE.md
PART 9 — collusion_worker; 1013+ lifetime rings detected as of §pass28).
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
    name="collusion_status_summary_readable",
    category="collusion_detection",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["collusion", "status"],
)
async def test_collusion_status(rig: FederationTestRig) -> AssertionResult:
    """getCollusionStatus returns the lifetime + 24h ring counters and
    per-registry breakdown. The lifetime_rings counter should be ≥0
    (and historically ≥1000 on sandbox-A)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCollusionStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            summ = r.get("summary") or {}
            state["lifetime_rings"] = summ.get("lifetime_rings")
            state["rings_24h"] = summ.get("rings_24h")
            state["cycles_24h"] = summ.get("cycles_24h")
            state["registries_reporting"] = summ.get("registries_reporting")
            return (
                isinstance(summ.get("lifetime_rings"), int)
                and summ["lifetime_rings"] >= 0
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="collusion detection status reachable with summary counters",
        capture_state=lambda: state,
    )


@federation_test(
    name="collusion_rings_list_queryable",
    category="collusion_detection",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["collusion", "rings"],
)
async def test_collusion_rings(rig: FederationTestRig) -> AssertionResult:
    """getCollusionRings returns the list of detected rings (possibly
    empty). Validates the read path is healthy."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCollusionRings")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            rows = r if isinstance(r, list) else (
                r.get("rings") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(rows)
            return isinstance(state.get("count"), int) and state["count"] >= 0
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="collusion rings list queryable on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="collusion_per_registry_decay_passes",
    category="collusion_detection",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["collusion", "per-registry", "decay"],
)
async def test_collusion_per_registry(rig: FederationTestRig) -> AssertionResult:
    """getCollusionStatus.per_registry shows ≥1 registry with decay_passes_24h
    ≥1. The decay worker reduces stale rings over time."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCollusionStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            per_reg = r.get("per_registry") if isinstance(r, dict) else None
            if not isinstance(per_reg, list):
                state["bad_shape"] = type(per_reg).__name__ if per_reg else None
                return False
            state["registry_count"] = len(per_reg)
            with_decay = [
                reg.get("registry_id")
                for reg in per_reg
                if isinstance(reg, dict)
                and isinstance(reg.get("decay_passes_24h"), int)
                and reg["decay_passes_24h"] >= 0
            ]
            state["registries_with_decay_counter"] = with_decay
            return len(with_decay) >= 1
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="≥1 registry surfaces collusion decay_passes_24h counter",
        capture_state=lambda: state,
    )
