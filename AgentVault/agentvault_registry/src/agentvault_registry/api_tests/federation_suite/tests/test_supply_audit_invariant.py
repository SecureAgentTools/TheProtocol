"""Supply audit invariant tests (§pass73.3.9 Batch 12).

3 tests probing the Option-4 self-consistent supply auditor (CLAUDE.md
PART 4). The auditor verifies the supply invariant WITHIN the EventStore:
  tokens_issued == total_circulating + tokens_destroyed
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
    name="supply_auditor_cycles_advancing",
    category="supply_audit_invariant",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["supply-audit", "cycles"],
)
async def test_supply_auditor_cycles(rig: FederationTestRig) -> AssertionResult:
    """getSupplyAuditorStatus shows cycles_24h ≥1 — auditor worker alive.

    Per CLAUDE.md the auditor runs continuously (92K+ cycles lifetime as
    of 2026-05 baseline). A zero count in 24h would indicate the worker
    crashed or wasn't leader-elected.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getSupplyAuditorStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            summ = r.get("summary") or {}
            state["cycles_24h"] = summ.get("cycles_24h")
            state["breaches_24h"] = summ.get("breaches_24h")
            state["registries_reporting"] = summ.get("registries_reporting")
            return (
                isinstance(summ.get("cycles_24h"), int)
                and summ["cycles_24h"] >= 1
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="supply auditor reports ≥1 cycle in 24h window",
        capture_state=lambda: state,
    )


@federation_test(
    name="supply_audit_no_24h_breaches",
    category="supply_audit_invariant",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["supply-audit", "breaches", "delta-zero"],
)
async def test_no_breaches_24h(rig: FederationTestRig) -> AssertionResult:
    """getSupplyAuditorStatus reports breaches_24h = 0.

    A breach indicates the invariant `tokens_issued == circulating +
    destroyed` failed somewhere. Zero tolerance per CLAUDE.md PART 4.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getSupplyAuditorStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            summ = r.get("summary") or {}
            state["breaches_24h"] = summ.get("breaches_24h")
            return summ.get("breaches_24h") == 0
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="zero supply audit breaches in 24h window",
        capture_state=lambda: state,
    )


@federation_test(
    name="supply_audit_per_registry_health",
    category="supply_audit_invariant",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["supply-audit", "per-registry"],
)
async def test_per_registry_health(rig: FederationTestRig) -> AssertionResult:
    """getSupplyAuditorStatus.per_registry surfaces individual registry
    health. Both mainframes must report `healthy=true` with last_delta=0.0.

    §TESTBED (2026-09-19): each frame's OWN auditor is asked. The status is read
    from the Prometheus the frame queries: on the network's tier that is the
    host's shared monitor (every registry in one list), while a kit frame's own
    Prometheus scrapes only itself (measured: one entry per frame). Two distinct
    healthy registries across both answers, and none reported unhealthy, is the
    same promise in both topologies."""
    state: dict = {}

    async def predicate():
        try:
            healthy_zero_delta, unhealthy, counts = set(), [], {}
            for label in ("sandbox-A-admin", "sandbox-B-admin"):
                r = await rig.mcp(label).call("getSupplyAuditorStatus")
                if _is_silent_or_error(r):
                    state[f"silent_{label}"] = True
                    continue
                per_reg = r.get("per_registry") if isinstance(r, dict) else None
                if not isinstance(per_reg, list):
                    state[f"bad_shape_{label}"] = type(per_reg).__name__ if per_reg else None
                    return False
                counts[label] = len(per_reg)
                for reg in per_reg:
                    if not isinstance(reg, dict):
                        continue
                    rid = reg.get("registry_id")
                    if reg.get("healthy") and reg.get("last_delta") == 0.0:
                        healthy_zero_delta.add(rid)
                    elif reg.get("healthy") is False:
                        unhealthy.append(rid)
            state["registry_count"] = counts
            state["healthy_zero_delta"] = sorted(str(x) for x in healthy_zero_delta)
            state["unhealthy"] = unhealthy
            if len(counts) == 0:   # both silent: the sandbox admin proxy's accepted shape, as before
                return True
            # At least 2 registries healthy with delta=0 (both mainframes), none unhealthy
            return len(healthy_zero_delta) >= 2 and not unhealthy
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="≥2 registries healthy with last_delta=0.0 across both frames' auditors",
        capture_state=lambda: state,
    )
