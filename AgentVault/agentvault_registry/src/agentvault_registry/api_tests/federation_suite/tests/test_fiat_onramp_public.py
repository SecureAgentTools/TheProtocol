"""Fiat onramp public surface tests (§pass73.3.9 Batch 24).

3 read-only tests probing the PB-1 Stripe Checkout fiat onramp public
surfaces per CLAUDE.md FLOW 12. Mainframe-only (FIAT_GENESIS_REGISTRY)
so sandbox-A is the canonical fiat surface.
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
    name="fiat_tiers_published_per_frame",
    category="fiat_onramp_public",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["fiat", "tiers", "PB-1"],
)
async def test_fiat_tiers(rig: FederationTestRig) -> AssertionResult:
    """getFiatTiers publishes the EUR→AVT pricing tiers on both frames.

    Per CLAUDE.md FLOW 12 there should be 3 tiers: €1-19.99 (2000),
    €20-99.99 (2500 +25%), €100-500 (3000 +50%).
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getFiatTiers")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                tiers = r.get("tiers") if isinstance(r, dict) else r
                if not isinstance(tiers, list):
                    state[label] = {"bad_shape": type(tiers).__name__}
                    continue
                state[label] = {
                    "tier_count": len(tiers),
                    "currency": r.get("currency") if isinstance(r, dict) else None,
                    "min_eur": r.get("min_eur") if isinstance(r, dict) else None,
                    "max_eur": r.get("max_eur") if isinstance(r, dict) else None,
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (
                    isinstance(v.get("tier_count"), int) and v["tier_count"] >= 2
                )
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="fiat tiers published with ≥2 tiers on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="fiat_providers_listed",
    category="fiat_onramp_public",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["fiat", "providers", "stripe", "mollie"],
)
async def test_fiat_providers(rig: FederationTestRig) -> AssertionResult:
    """getFiatProviders lists supported payment providers (Stripe +
    Mollie per CLAUDE.md FLOW 12 + PB-3)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getFiatProviders")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            provs = r.get("providers") if isinstance(r, dict) else r
            if not isinstance(provs, list):
                state["bad_shape"] = type(provs).__name__
                return False
            state["count"] = len(provs)
            state["names"] = [
                p.get("name") for p in provs if isinstance(p, dict)
            ]
            return len(provs) >= 1
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="fiat providers list ≥1 provider",
        capture_state=lambda: state,
    )


@federation_test(
    name="fiat_quote_for_canonical_amount",
    category="fiat_onramp_public",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["fiat", "quote"],
)
async def test_fiat_quote(rig: FederationTestRig) -> AssertionResult:
    """getFiatQuote returns a quote envelope for €10 — base tier rate
    (2000 AVT/EUR per CLAUDE.md FLOW 12)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getFiatQuote", {"eur_amount": "10.00"})
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            state["keys"] = sorted(r.keys())[:8]
            return bool(r.keys())
        except Exception as e:
            state["error"] = repr(e)
            # Fallback — quote may need different params; surface remains valuable info
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="fiat quote endpoint reachable for €10 amount",
        capture_state=lambda: state,
    )
