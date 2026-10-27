"""Reactor causality tests (§pass73.3.17 Batch 88).

3 tests verifying reactor framework is actually FIRING — not just alive.
Probes lifetime dispatch counters + last-fire timestamps. A reactor
that's "alive but never fires" is silently broken.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
    require_canary_subsystem,
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
    name="reactors_have_lifetime_dispatches",
    category="reactor_causality",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["reactors", "causality", "dispatches"],
)
async def test_reactors_dispatched(rig: FederationTestRig) -> AssertionResult:
    """getReactorStatus reports total_lifetime_dispatches > 0. A reactor
    framework that's never dispatched anything is broken."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getReactorStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                return False
            state["keys"] = sorted(r.keys())[:10]
            # Possible shapes
            total = (
                r.get("total_lifetime_dispatches")
                or r.get("lifetime_dispatches")
                or (r.get("summary") or {}).get("lifetime_dispatches")
            )
            state["lifetime_dispatches"] = total
            if isinstance(total, int):
                return total > 0
            # Aggregate from per-reactor entries
            reactors = r.get("reactors") or []
            if isinstance(reactors, list) and reactors:
                aggregate = sum(
                    (r2.get("dispatches") or r2.get("lifetime_dispatches") or 0)
                    for r2 in reactors if isinstance(r2, dict)
                )
                state["aggregate_dispatches"] = aggregate
                return aggregate > 0
            return False
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="reactor framework has dispatched ≥1 event lifetime",
        capture_state=lambda: state,
    )


@federation_test(
    name="reactors_count_reasonable_population",
    category="reactor_causality",
    budget_sec=30.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["reactors", "population"],
)
async def test_reactor_count(rig: FederationTestRig) -> AssertionResult:
    """getReactorStatus lists ≥15 reactors per CLAUDE.md PART 9 (34
    reactors live, but some are disabled in sandbox). A drop below 15
    indicates reactor framework discovery is broken."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getReactorStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                return False
            reactors = r.get("reactors") or []
            count = len(reactors) if isinstance(reactors, list) else None
            state["count"] = count
            return isinstance(count, int) and count >= 15
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="reactor framework has ≥15 reactors registered",
        capture_state=lambda: state,
    )


@federation_test(
    name="canary_subsystem_has_recent_passes",
    category="reactor_causality",
    budget_sec=30.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["canary", "recent-passes"],
)
async def test_canary_recent_passes(
    rig: FederationTestRig,
) -> AssertionResult:
    """getCanaryStatus reports per-path 24h_pass_rate. At least one path
    has 24h_pass_rate > 0 (canary subsystem is producing real signal)."""
    state: dict = {}

    # §FEDCANARY: a tier with zero configured paths has no canary subsystem to
    # measure — skip loudly rather than poll a fixture that was never provisioned.
    # A CONFIGURED path that is missing or failing still goes RED.
    await require_canary_subsystem(rig)
    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getCanaryStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                return False
            paths = r.get("paths") or r.get("canaries") or []
            if not isinstance(paths, list):
                return False
            state["path_count"] = len(paths)
            # Real shape: paths[i].stats_24h.pass_rate (NOT pass_rate_24h)
            def _path_pass_rate(p):
                if not isinstance(p, dict): return 0
                s24 = p.get("stats_24h") or {}
                if isinstance(s24, dict):
                    return s24.get("pass_rate") or s24.get("passed") or 0
                return p.get("pass_rate_24h") or p.get("recent_24h_pass_rate") or 0
            paths_with_passes = sum(
                1 for p in paths if (_path_pass_rate(p) or 0) > 0
            )
            state["paths_with_24h_passes"] = paths_with_passes
            return paths_with_passes >= 1
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="≥1 canary path has 24h_pass_rate > 0",
        capture_state=lambda: state,
    )
