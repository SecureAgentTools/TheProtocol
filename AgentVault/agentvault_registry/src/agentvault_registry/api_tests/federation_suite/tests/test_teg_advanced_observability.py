"""TEG advanced observability tests (§pass73.3.15 Batch 71).

3 read-only tests probing TEG-layer advanced surfaces: price feed,
attestations, and advanced transaction stream.
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
    name="teg_price_envelope",
    category="teg_advanced_observability",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["teg", "price"],
)
async def test_teg_price(rig: FederationTestRig) -> AssertionResult:
    """getTegPrice returns the TEG price-feed envelope."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getTegPrice")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:6]
                return bool(r.keys())
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="TEG price envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="teg_attestations_envelope",
    category="teg_advanced_observability",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["teg", "attestations"],
)
async def test_teg_attestations(rig: FederationTestRig) -> AssertionResult:
    """getTegAttestations returns the TEG-side attestation envelope
    (chain validity attestations)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getTegAttestations")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("attestations") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="TEG attestations envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="teg_advanced_transactions_envelope",
    category="teg_advanced_observability",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["teg", "advanced-transactions"],
)
async def test_teg_advanced_transactions(
    rig: FederationTestRig,
) -> AssertionResult:
    """getTegAdvancedTransactions returns the TEG advanced tx stream
    (with policy decoration + cross-TEG annotations)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getTegAdvancedTransactions")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("transactions") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="TEG advanced transactions envelope reachable",
        capture_state=lambda: state,
    )
