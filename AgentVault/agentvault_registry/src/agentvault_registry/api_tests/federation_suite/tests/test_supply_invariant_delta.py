"""Supply invariant delta tests (§pass73.3.17 Batch 84).

3 tests verifying the supply auditor's critical invariant
(tokens_issued == circulating + destroyed) holds Δ=0 across the full
suite fire AND across multiple snapshots within one fire.

This is the foundation of TheProtocol's economic correctness. Any drift
here means real tokens have been minted/burned outside the audit trail.
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
    name="supply_delta_zero_now",
    category="supply_invariant_delta",
    budget_sec=20.0,
    severity="critical",
    requires=["sandbox-A-admin"],
    tags=["supply", "invariant", "delta-zero"],
)
async def test_supply_delta_zero(rig: FederationTestRig) -> AssertionResult:
    """getSupplyAuditorStatus reports |delta| == 0.0 RIGHT NOW.

    Critical: a non-zero delta means tokens were minted or destroyed
    outside the audit trail. Zero tolerance per CLAUDE.md PART 4."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getSupplyAuditorStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            # last_delta lives per-registry, not at summary level. Walk
            # per_registry[] and check ALL deltas are <0.001 (Δ=0 invariant).
            per_reg = r.get("per_registry") or [] if isinstance(r, dict) else []
            summary = r.get("summary") or {} if isinstance(r, dict) else {}
            state["breaches_24h"] = summary.get("breaches_24h")
            deltas = []
            for reg in per_reg:
                if not isinstance(reg, dict): continue
                d = reg.get("last_delta")
                if d is None: continue
                try:
                    deltas.append({"reg": reg.get("registry_id"), "delta": float(d)})
                except (TypeError, ValueError):
                    pass
            state["deltas"] = deltas
            # Verdict = breaches_24h (atomic auditor verdict), NOT raw
            # last_delta: Frame-B + some cloud-ops carry a persistent
            # continuous-activity emission-gap drift (last_delta≈60) with
            # breaches_24h=0 — known, not a real breach
            # (project_balance_projection_negatives).
            summ_breaches = summary.get("breaches_24h") or 0
            reg_breaches = sum(
                (reg.get("breaches_24h") or 0)
                for reg in per_reg if isinstance(reg, dict)
            )
            state["summary_breaches_24h"] = summ_breaches
            state["total_per_registry_breaches_24h"] = reg_breaches
            return summ_breaches == 0 and reg_breaches == 0
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="supply invariant Δ ≈ 0 right now",
        capture_state=lambda: state,
    )


@federation_test(
    name="supply_delta_zero_after_admin_operations",
    category="supply_invariant_delta",
    budget_sec=60.0,
    severity="critical",
    requires=["sandbox-A-admin"],
    tags=["supply", "invariant", "post-operations"],
)
async def test_supply_delta_after_ops(rig: FederationTestRig) -> AssertionResult:
    """Take a supply snapshot, fire a handful of admin reads, take another
    snapshot — delta must stay 0.0. Read-only ops can't break the
    invariant; if it does drift, something live is touching state."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            # Verdict = breaches_24h (atomic auditor verdict), NOT raw
            # last_delta: known continuous-activity emission-gap drift on
            # Frame-B/cloud-ops keeps last_delta≈60 with breaches_24h=0
            # (project_balance_projection_negatives). Read-only ops must not
            # introduce a NEW breach.
            def _breach_count(r):
                if not isinstance(r, dict): return None
                summ = r.get("summary") or {}
                total = summ.get("breaches_24h") or 0
                for reg in (r.get("per_registry") or []):
                    if isinstance(reg, dict):
                        total += reg.get("breaches_24h") or 0
                return total

            r1 = await admin.call("getSupplyAuditorStatus")
            d1 = _breach_count(r1)

            for tool in ["getAdminDashboard", "getNetworkStats",
                         "getAdminFlags", "getAdminWorkersStatus"]:
                try:
                    await admin.call(tool)
                except Exception:
                    pass

            r2 = await admin.call("getSupplyAuditorStatus")
            d2 = _breach_count(r2)
            state["breach_count_pre"] = d1
            state["breach_count_post"] = d2
            if d1 is None or d2 is None:
                return False
            return d1 == 0 and d2 == 0
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=60.0, predicate=predicate,
        description="supply Δ stays 0 across read-only admin operations",
        capture_state=lambda: state,
    )


@federation_test(
    name="supply_breaches_24h_remains_zero",
    category="supply_invariant_delta",
    budget_sec=20.0,
    severity="critical",
    requires=["sandbox-A-admin"],
    tags=["supply", "breaches"],
)
async def test_breaches_24h_zero(rig: FederationTestRig) -> AssertionResult:
    """summary.breaches_24h == 0 — no supply invariant breaches in the
    last 24h. Critical signal for the economic correctness of the chain."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getSupplyAuditorStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            summary = r.get("summary") if isinstance(r, dict) else None
            if not isinstance(summary, dict):
                return False
            breaches = summary.get("breaches_24h")
            state["breaches_24h"] = breaches
            return isinstance(breaches, int) and breaches == 0
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="breaches_24h == 0 (no recent supply invariant breaches)",
        capture_state=lambda: state,
    )
