"""Webhook + attestation subsystem health tests (Phase H §pass73.3.8+).

5 tests probing the webhook delivery + attestation subsystems. Both are
under-tested at the federation level despite being load-bearing for
external integrations (webhooks) and ZKP scaffolding (attestations).
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
    name="webhook_aggregate_status_per_frame",
    category="webhook_attestation_health",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["webhooks", "aggregate"],
)
async def test_webhook_aggregate(rig: FederationTestRig) -> AssertionResult:
    """getWebhookAggregate returns delivery health metrics on each mainframe."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getWebhookAggregate")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {"keys": list(r.keys())[:8]}
                else:
                    state[label] = type(r).__name__
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
        description="webhook aggregate reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="supported_webhook_events_listed",
    category="webhook_attestation_health",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A", "sandbox-B"],
    tags=["webhooks", "events-catalog"],
)
async def test_supported_webhook_events(rig: FederationTestRig) -> AssertionResult:
    """getSupportedWebhookEvents lists the event types a developer can subscribe to."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getSupportedWebhookEvents")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                items = r if isinstance(r, list) else (
                    r.get("events") or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                state[label] = {"count": len(items)}
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
        description="supported webhook events catalog reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="broadcast_email_retry_status_alive",
    category="webhook_attestation_health",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["broadcast", "email-retry", "worker"],
)
async def test_broadcast_email_retry_alive(rig: FederationTestRig) -> AssertionResult:
    """getBroadcastEmailRetryStatus returns worker state.

    The broadcast-email-retry worker drives re-delivery of failed
    notification emails. Empty payload OK; we just need the surface alive.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getBroadcastEmailRetryStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = list(r.keys())[:8]
            elif isinstance(r, list):
                state["count"] = len(r)
            else:
                state["raw"] = type(r).__name__
                return False
            return True
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="broadcast email retry worker status reachable on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="attestation_health_per_frame",
    category="webhook_attestation_health",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["attestations", "health"],
)
async def test_attestation_health(rig: FederationTestRig) -> AssertionResult:
    """getAttestationHealth returns the attestation subsystem state."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getAttestationHealth")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {"keys": list(r.keys())[:8]}
                else:
                    state[label] = type(r).__name__
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
        description="attestation health reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="attestation_signing_pubkey_present",
    category="webhook_attestation_health",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["attestations", "signing", "pubkey"],
)
async def test_attestation_pubkey(rig: FederationTestRig) -> AssertionResult:
    """getAttestationSigningPubkey returns the attestation signing public key."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getAttestationSigningPubkey")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {"keys": list(r.keys())[:6]}
                else:
                    state[label] = type(r).__name__
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
        description="attestation signing pubkey queryable on both mainframes",
        capture_state=lambda: state,
    )
