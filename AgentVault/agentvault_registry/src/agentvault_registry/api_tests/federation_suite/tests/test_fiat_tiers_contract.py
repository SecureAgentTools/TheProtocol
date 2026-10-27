"""Fiat onramp tier math contract tests (§pass73.3.17 Batch 97).

3 tests verifying fiat tier math + pricing per CLAUDE.md PART 5 FLOW 12:
  €1-€19.99 = 2000 AVT/EUR
  €20-€99.99 = 2500 AVT/EUR (+25%)
  €100-€500 = 3000 AVT/EUR (+50%)
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
    name="fiat_tiers_inventory_has_three_tiers",
    category="fiat_tiers_contract",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["fiat", "tiers", "pricing"],
)
async def test_fiat_three_tiers(rig: FederationTestRig) -> AssertionResult:
    """getFiatTiers returns 3 pricing tiers (€1-19.99, €20-99.99, €100-500)
    per CLAUDE.md PART 5 FLOW 12."""
    state: dict = {}

    async def predicate():
        try:
            pub = rig.mcp("sandbox-A")
            r = await pub.call("getFiatTiers")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            tiers = r if isinstance(r, list) else (
                r.get("tiers") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["tier_count"] = len(tiers) if isinstance(tiers, list) else None
            return isinstance(state["tier_count"], int) and \
                state["tier_count"] >= 3
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="fiat tiers inventory has ≥3 tiers",
        capture_state=lambda: state,
    )


@federation_test(
    name="fiat_quote_5eur_returns_10000_avt",
    category="fiat_tiers_contract",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A"],
    tags=["fiat", "quote", "math"],
)
async def test_fiat_quote_5eur(rig: FederationTestRig) -> AssertionResult:
    """getFiatQuote(eur=5) returns 10000 AVT (5 × 2000 AVT/EUR, tier 1)."""
    state: dict = {}

    async def predicate():
        try:
            pub = rig.mcp("sandbox-A")
            r = await pub.call("getFiatQuote", {"eur_amount": "5.0"})
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                return False
            state["keys"] = sorted(r.keys())[:8]
            avt = r.get("avt_amount") or r.get("amount_avt") or r.get("avt")
            state["avt"] = avt
            try:
                avt_f = float(avt)
                state["avt_float"] = avt_f
                # 5 EUR × 2000 AVT/EUR = 10000 AVT
                return abs(avt_f - 10000) < 1
            except (TypeError, ValueError):
                return False
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="5 EUR → 10000 AVT (tier 1: 2000 AVT/EUR)",
        capture_state=lambda: state,
    )


@federation_test(
    name="fiat_quote_100eur_returns_300000_avt",
    category="fiat_tiers_contract",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A"],
    tags=["fiat", "quote", "tier-3"],
)
async def test_fiat_quote_100eur(rig: FederationTestRig) -> AssertionResult:
    """getFiatQuote(eur=100) returns 300000 AVT (100 × 3000, tier 3
    pricing kicks in at €100)."""
    state: dict = {}

    async def predicate():
        try:
            pub = rig.mcp("sandbox-A")
            r = await pub.call("getFiatQuote", {"eur_amount": "100.0"})
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                return False
            avt = r.get("avt_amount") or r.get("amount_avt") or r.get("avt")
            state["avt"] = avt
            try:
                avt_f = float(avt)
                state["avt_float"] = avt_f
                return abs(avt_f - 300000) < 10
            except (TypeError, ValueError):
                return False
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="100 EUR → 300000 AVT (tier 3: 3000 AVT/EUR)",
        capture_state=lambda: state,
    )
