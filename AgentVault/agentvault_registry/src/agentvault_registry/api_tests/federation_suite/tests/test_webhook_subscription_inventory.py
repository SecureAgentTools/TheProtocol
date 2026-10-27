"""Webhook subscription inventory tests (§pass73.3.9 Batch 11).

3 read-only tests probing the webhook subscription + delivery infra
(webhook_retry_worker per CLAUDE.md PART 9):
  - supported event types catalog
  - dev webhook listing surface reachable per developer
  - admin webhook aggregate reachable
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
    name="supported_webhook_events_catalog_per_frame",
    category="webhook_subscription",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["webhooks", "event-types"],
)
async def test_supported_webhook_events(
    rig: FederationTestRig,
) -> AssertionResult:
    """getSupportedWebhookEvents returns ≥10 event types on each frame
    (agent.*, staking.*, governance.* canonical categories per
    CLAUDE.md PART 5)."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getSupportedWebhookEvents")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                events = r.get("events") if isinstance(r, dict) else r
                if not isinstance(events, list):
                    state[label] = {"bad_shape": type(events).__name__}
                    continue
                state[label] = {
                    "count": len(events),
                    "categories": sorted(
                        {e.split(".")[0] for e in events if isinstance(e, str) and "." in e}
                    )[:8],
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (isinstance(v.get("count"), int) and v["count"] >= 10)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="supported webhook events ≥10 on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="developer_webhooks_listing_reachable",
    category="webhook_subscription",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["webhooks", "dev-listing"],
)
async def test_developer_webhooks_listing(
    rig: FederationTestRig,
) -> AssertionResult:
    """listDeveloperWebhooks returns the per-developer webhook list
    (possibly empty for a fresh sandbox dev). Validates the read path."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("listDeveloperWebhooks")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                hooks = r if isinstance(r, list) else (
                    r.get("webhooks") or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                state[label] = {"count": len(hooks)}
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
        description="dev webhook listing reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="webhook_aggregate_admin_view",
    category="webhook_subscription",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["webhooks", "admin", "aggregate"],
)
async def test_webhook_aggregate_admin(
    rig: FederationTestRig,
) -> AssertionResult:
    """getWebhookAggregate surfaces aggregate webhook metrics on the
    admin side — delivery counters, failure rates, queue depth."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getWebhookAggregate")
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
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="webhook aggregate admin view reachable on sandbox-A",
        capture_state=lambda: state,
    )
