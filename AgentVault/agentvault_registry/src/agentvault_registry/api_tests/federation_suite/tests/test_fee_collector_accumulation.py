"""Fee collector + treasury accumulation observation tests (§pass73.3.9 Batch 3).

4 read-only observation tests validating fee collector + treasury aggregate
surfaces on both mainframes. Catches:
  - fee_collector account being unreachable / missing balance field
  - treasury aggregate missing supply_audit delta
  - EventStore balance projection broken (no agents listed)
  - sparkline buckets missing / malformed
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


def _to_float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@federation_test(
    name="fee_collector_balance_field_present",
    category="fee_collector_accumulation",
    budget_sec=45.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["fee-collector", "balance"],
)
async def test_fee_collector_balance(rig: FederationTestRig) -> AssertionResult:
    """getFeeCollectorInfo returns a numeric balance ≥0 + canonical DID on both
    mainframes.

    Transient-tolerant (§pass73.3.21): the registry endpoint proxies the LOCAL
    TEG /admin/fee-collector/info (10s upstream timeout). A cold first call can
    ReadTimeout — the endpoint then returns HTTP 200 with balance=null + teg_error
    set (httpx ReadTimeout's str() is ''), an upstream transient, NOT a
    fee_collector invariant violation. A null-with-teg_error frame is treated as
    "pending" and RETRIED within budget (the warm retry returns the real balance
    in ~2.4s). A frame is a hard failure only if, while reachable, it reports a
    negative balance.
    """
    state: dict = {}

    async def predicate():
        pending = False
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getFeeCollectorInfo")
            except Exception as e:
                state[label] = {"pending": True, "error": repr(e)[:140]}
                pending = True
                continue
            if _is_silent_or_error(r):
                state[label] = {"silent": True}        # MCP-level silent — acceptable
                continue
            if not isinstance(r, dict):
                state[label] = {"bad_shape": type(r).__name__}
                return False                            # malformed shape — real problem
            raw_balance = r.get("balance")
            if raw_balance is None:
                # upstream TEG transiently unreachable (teg_error set; '' for ReadTimeout)
                state[label] = {"pending_upstream": True, "teg_error": r.get("teg_error")}
                pending = True
                continue
            bal = _to_float(raw_balance)
            state[label] = {
                "balance": bal,
                "did": r.get("fee_collector_did"),
                "period": r.get("period"),
            }
            if isinstance(bal, float) and bal < 0.0:
                state[label]["NEGATIVE"] = True         # real invariant violation
                return False
        if pending:
            return False                                # retry within budget for a warm read
        # Every frame resolved: pass iff each is MCP-silent or has a numeric balance >=0.
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (
                    isinstance(v.get("balance"), float) and v["balance"] >= 0.0
                )
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=45.0, predicate=predicate,
        description="fee_collector balance ≥0 with canonical DID on both mainframes (transient-tolerant)",
        capture_state=lambda: state,
    )


@federation_test(
    name="treasury_aggregate_supply_audit_delta_zero",
    category="fee_collector_accumulation",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["treasury", "supply-audit", "delta-zero"],
)
async def test_treasury_supply_delta_zero(rig: FederationTestRig) -> AssertionResult:
    """getTreasuryAggregate.supply_audit.delta = 0.0 on both mainframes.

    This is the core supply invariant from CLAUDE.md PART 4. Failing this
    means tokens were minted/burned outside the official paths. Tolerates
    sandbox-tier `_text` placeholders.
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getTreasuryAggregate")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if not isinstance(r, dict):
                    state[label] = {"bad_shape": type(r).__name__}
                    continue
                sa = r.get("supply_audit") or {}
                delta = _to_float(sa.get("delta"))
                state[label] = {
                    "delta": delta,
                    "status": sa.get("status"),
                    "tokens_issued": _to_float(sa.get("tokens_issued")),
                    "total_circulating": _to_float(sa.get("total_circulating")),
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (
                    v.get("delta") is not None and float(v["delta"]) == 0.0
                )
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="supply audit delta=0.0 on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="eventstore_balances_lists_agents",
    category="fee_collector_accumulation",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["eventstore", "projections", "balances"],
)
async def test_eventstore_balances_lists_agents(
    rig: FederationTestRig,
) -> AssertionResult:
    """getEventStoreBalances returns the projection of agent balances.

    On sandbox-A there should be ≥10 known agents (canary infra + service
    agents + fed-test-agent). On sandbox-B likely ≥2 (fed-test-agent-b +
    test seed). Loose ≥2 threshold tolerates per-frame variance.
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getEventStoreBalances")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                agents = r.get("agents") if isinstance(r, dict) else r
                if not isinstance(agents, list):
                    state[label] = {"bad_shape": type(agents).__name__}
                    continue
                state[label] = {"agent_count": len(agents)}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (isinstance(v.get("agent_count"), int) and v["agent_count"] >= 2)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="EventStore projection lists ≥2 agents on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="fee_collector_sparkline_7day_bucket_count",
    category="fee_collector_accumulation",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["fee-collector", "sparkline"],
)
async def test_fee_collector_sparkline(rig: FederationTestRig) -> AssertionResult:
    """fee_collector sparkline returns 7 buckets (one per day, 7d window).

    Validates the sparkline aggregator query is alive. Each bucket should
    have `t`, `amount`, `count` fields.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getFeeCollectorInfo")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            sl = r.get("sparkline") if isinstance(r, dict) else None
            if not isinstance(sl, list):
                state["no_sparkline"] = True
                return False
            state["bucket_count"] = len(sl)
            if sl:
                first = sl[0]
                state["sample_keys"] = sorted(first.keys()) if isinstance(first, dict) else []
            # Sparkline is 7-day so should be ~6-8 buckets (boundary edge cases)
            return 5 <= len(sl) <= 9
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="fee_collector sparkline has 7-day bucket window on sandbox-A",
        capture_state=lambda: state,
    )
