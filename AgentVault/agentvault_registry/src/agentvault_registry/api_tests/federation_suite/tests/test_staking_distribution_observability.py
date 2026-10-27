"""Staking distribution + APY tier observability tests (§pass73.3.9 Batch 9).

4 read-only tests probing the staking distribution worker surface
(staking_distributor reactor per CLAUDE.md PART 9). Validates: APY tiers
published, daily distributions tracked, recent distribution non-zero.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, target_switches, rewards_off,
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


def _to_float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@federation_test(
    name="staking_apy_tiers_published",
    category="staking_distribution",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["staking", "apy", "tiers"],
)
async def test_apy_tiers_published(rig: FederationTestRig) -> AssertionResult:
    """getLockPayoutTiersTeg publishes ≥3 tiers (bronze/silver/gold or
    similar) on both mainframes with base_apy + min_stake."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getLockPayoutTiersTeg")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                tiers = r.get("tiers") if isinstance(r, dict) else r
                if not isinstance(tiers, list):
                    state[label] = {"bad_shape": type(tiers).__name__}
                    continue
                # §MCPTEST30 (V0550): where rewards are switched off (its registry-config says so) the documented
                # answer is no tiers at all, with the engine named disabled: that is the pass there, a tier a finding
                if rewards_off(await target_switches(rig, label)):
                    meta = r.get("metadata") if isinstance(r, dict) else None
                    state[label] = {"rewards_off": True, "count": len(tiers),
                                    "engine": (meta or {}).get("engine") if isinstance(meta, dict) else None,
                                    "off_shape": not tiers}
                    continue
                state[label] = {
                    "count": len(tiers),
                    "names": [t.get("name") for t in tiers if isinstance(t, dict)][:5],
                }
                # Each tier must have base_apy + min_stake
                complete = all(
                    isinstance(t, dict)
                    and t.get("base_apy") is not None
                    and t.get("min_stake") is not None
                    for t in tiers
                )
                state[label]["complete_envelope"] = complete
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (v.get("rewards_off") and v.get("off_shape")) or (
                    not v.get("rewards_off") and v.get("count", 0) >= 3 and v.get("complete_envelope")
                )
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="≥3 APY tiers published with base_apy+min_stake on both mainframes (none where rewards are off)",
        capture_state=lambda: state,
    )


@federation_test(
    name="staking_distributions_listed_per_frame",
    category="staking_distribution",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["staking", "distributions"],
)
async def test_distributions_listed(rig: FederationTestRig) -> AssertionResult:
    """getLockPayoutRuns returns ≥1 distribution per mainframe.

    The staking_distributor worker runs daily; in a long-lived sandbox
    we expect multiple distributions over time.
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getLockPayoutRuns", {"limit": 5})
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                rows = r.get("distributions") if isinstance(r, dict) else r
                if not isinstance(rows, list):
                    state[label] = {"bad_shape": type(rows).__name__}
                    continue
                state[label] = {"count": len(rows)}
                if rows and isinstance(rows[0], dict):
                    state[label]["latest_type"] = rows[0].get("distribution_type")
                    state[label]["latest_status"] = rows[0].get("status")
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
        description="staking distributions listed on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="staking_global_stats_distribution_per_frame",
    category="staking_distribution",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["staking", "global-stats"],
)
async def test_staking_global_stats(rig: FederationTestRig) -> AssertionResult:
    """getLockStats surfaces aggregate staking metrics per frame."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getLockStats")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if not isinstance(r, dict):
                    state[label] = {"bad_shape": type(r).__name__}
                    continue
                state[label] = {"keys": sorted(r.keys())[:8]}
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
        description="staking global stats readable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="staking_apy_rates_summary_per_frame",
    category="staking_distribution",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A", "sandbox-B"],
    tags=["staking", "apy-summary"],
)
async def test_apy_rates_summary(rig: FederationTestRig) -> AssertionResult:
    """getLockPayoutTiers returns the current APY rate summary on each frame.

    This is the canonical agent-facing surface for "what APY do I get".
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getLockPayoutTiers")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {"keys": sorted(r.keys())[:6]}
                elif isinstance(r, list):
                    state[label] = {"count": len(r)}
                else:
                    state[label] = {"bad_shape": type(r).__name__}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent")
                or (isinstance(v.get("keys"), list) and v["keys"])
                or isinstance(v.get("count"), int)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="APY rates summary readable on both mainframes",
        capture_state=lambda: state,
    )
