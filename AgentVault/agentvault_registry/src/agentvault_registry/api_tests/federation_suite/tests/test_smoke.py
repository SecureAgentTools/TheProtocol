"""Smoke tests — verify the rig itself works before exercising any federation
claim. Each test pokes one registry's MCP surface with a trivial read.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


@federation_test(
    name="smoke_all_registries_reachable",
    category="smoke",
    budget_sec=30.0,
    severity="critical",
    requires=[
        "sandbox-A", "sandbox-B",
        "sandboxalpha", "sandboxdelta",
    ],
    tags=["substrate", "health"],
)
async def test_smoke_all_registries_reachable(rig: FederationTestRig) -> AssertionResult:
    """Verify rig can hit /getNetworkStats on every sandbox registry via MCP.

    Pre-flight test — if this fails, the substrate is broken (auth, network,
    MCP wiring) and downstream tests will all fail. Run this first.
    """
    failed_registries = []

    async def predicate() -> bool:
        nonlocal failed_registries
        failed_registries = []
        for label in ("sandbox-A", "sandbox-B", "sandboxalpha", "sandboxdelta"):
            try:
                r = await rig.mcp(label).call("getNetworkStats")
                if not isinstance(r, dict) or "total_agents" not in r:
                    failed_registries.append(f"{label}: bad shape {r!r:.80}")
            except Exception as e:
                failed_registries.append(f"{label}: {e!r}")
        return not failed_registries

    async def capture_state():
        return {"failed_registries": failed_registries}

    return await rig.assert_within(
        budget_sec=30.0,
        predicate=predicate,
        description="all 4 sandbox registries answer getNetworkStats via MCP",
        poll_interval_sec=2.0,
        capture_state=capture_state,
    )


@federation_test(
    name="smoke_admin_bridge_reachable_on_each_registry",
    category="smoke",
    budget_sec=30.0,
    severity="critical",
    requires=[
        "sandbox-A-admin", "sandbox-B-admin",
        "sandboxalpha-admin", "sandboxdelta-admin",
    ],
    tags=["substrate", "admin"],
)
async def test_smoke_admin_bridge_reachable(rig: FederationTestRig) -> AssertionResult:
    """Verify admin MCP bridge responds on every sandbox registry.

    Uses adminQueryEventStore which is the lightest admin-tier call available
    (just queries the EventStore stats endpoint, no mutation).
    """
    failed_registries = []

    async def predicate() -> bool:
        nonlocal failed_registries
        failed_registries = []
        for label in (
            "sandbox-A-admin", "sandbox-B-admin",
            "sandboxalpha-admin", "sandboxdelta-admin",
        ):
            try:
                # adminRequest GET on a known-safe endpoint
                r = await rig.mcp(label).call(
                    "adminRequest",
                    {"method": "GET", "endpoint": "/api/v1/admin/health-check-simple"},
                )
                if not isinstance(r, dict):
                    failed_registries.append(f"{label}: bad shape {r!r:.80}")
            except Exception as e:
                failed_registries.append(f"{label}: {e!r}")
        return not failed_registries

    async def capture_state():
        return {"failed_registries": failed_registries}

    return await rig.assert_within(
        budget_sec=30.0,
        predicate=predicate,
        description="all 4 sandbox admin bridges answer adminRequest GET",
        poll_interval_sec=2.0,
        capture_state=capture_state,
    )


# ─── Suite self-checks (U3/U4, 2026-09-05) ────────────────────────────────
# These measure the SUITE, not the tier. They are the first users of the
# `no-probe` tag: they make no round trip, so the vacuity verdict must not fire
# on them — which is also the tag's own control.

@federation_test(
    name="suite_test_names_are_unique",
    category="suite_self_check",
    budget_sec=1.0,
    severity="high",
    tags=["no-probe", "self-check"],
)
async def test_suite_names_unique(rig):
    """Two tests sharing a name is a picker that selects the wrong subject.

    The runner's `test_name_filter` selects by NAME, so a duplicate means asking
    for one test silently runs two; every name-keyed view (the run differ, any
    per-test history) collapses them into one row. Measured 2026-09-05: three
    pairs, each spanning two categories, all green and all invisible.
    """
    from collections import Counter
    from agentvault_registry.api_tests.federation_suite.decorator import REGISTRY
    dupes = {n: c for n, c in Counter(s.name for s in REGISTRY).items() if c > 1}
    detail = ", ".join(f"{n}×{c}" for n, c in sorted(dupes.items()))
    return AssertionResult(
        passed=not dupes,
        description="every registered federation test has a unique name",
        budget_sec=1.0, elapsed_sec=0.0, polling_attempts=1,
        last_state={"registered": len(REGISTRY), "duplicates": dupes},
        failure_detail=None if not dupes else (
            f"duplicate test name(s): {detail}. Rename one — the runner filters "
            f"by name, so a duplicate makes `test_name_filter` ambiguous."
        ),
    )
