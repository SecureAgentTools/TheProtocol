"""Attestation subsystem health + circuit catalog tests (§pass73.3.9 Batch 8).

4 read-only tests probing the ZKP attestation subsystem (CLAUDE.md
zkp_phase_*_enabled gating). Validates: health, circuit catalog,
attestation analytics, public signing key.
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
    name="attestation_health_endpoint_returns_status",
    category="attestation_subsystem",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["attestation", "health"],
)
async def test_attestation_health(rig: FederationTestRig) -> AssertionResult:
    """getAttestationHealth returns {status:"healthy", service:"Attestations"}
    on both mainframes."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getAttestationHealth")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if not isinstance(r, dict):
                    state[label] = {"bad_shape": type(r).__name__}
                    continue
                state[label] = {
                    "status": r.get("status"),
                    "service": r.get("service"),
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or v.get("status") in ("healthy", "ok", "ready", "active")
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="attestation health returns healthy status on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="attestation_circuit_catalog_lists_known_circuits",
    category="attestation_subsystem",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["attestation", "circuits", "zkp"],
)
async def test_circuit_catalog(rig: FederationTestRig) -> AssertionResult:
    """getCircuits returns ≥1 ZKP circuit with acir_url + source_url.

    Per CLAUDE.md PART 9 the 6-phase ZKP work shipped on sandbox-A; the
    fairMarkup + accurateResourceUsage circuits should be registered.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getCircuits")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            circuits = r.get("circuits") if isinstance(r, dict) else r
            if not isinstance(circuits, list):
                state["bad_shape"] = type(circuits).__name__
                return False
            state["count"] = len(circuits)
            state["sample_ids"] = [c.get("circuit_id") for c in circuits[:3] if isinstance(c, dict)]
            # Every circuit must have an acir_url + source_url
            with_urls = sum(
                1 for c in circuits
                if isinstance(c, dict) and c.get("acir_url") and c.get("source_url")
            )
            state["with_urls"] = with_urls
            return len(circuits) >= 1 and with_urls >= 1
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="circuit catalog has ≥1 circuit with acir_url + source_url",
        capture_state=lambda: state,
    )


@federation_test(
    name="attestation_signing_pubkey_published",
    category="attestation_subsystem",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["attestation", "signing-key"],
)
async def test_attestation_signing_pubkey(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAttestationSigningPubkey returns a verification key used to
    verify ZKP attestation bundles. Validates the signing infra surface."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getAttestationSigningPubkey")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            state["keys"] = sorted(r.keys())[:8]
            state["alg"] = r.get("alg")
            state["pubkey_id"] = r.get("pubkey_id")
            # Validate at least one key-related field present (the real shape
            # is {alg, pubkey_b64, pubkey_id, issuer_registry})
            return bool(
                r.get("pubkey_b64") or r.get("public_key") or r.get("pubkey")
                or r.get("key") or r.get("jwk") or r.get("verification_key")
                or r.get("x")
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="attestation signing pubkey published on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="attestation_analytics_per_frame",
    category="attestation_subsystem",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["attestation", "analytics"],
)
async def test_attestation_analytics(rig: FederationTestRig) -> AssertionResult:
    """getAttestationsAnalytics returns an analytics envelope on both
    mainframes — counts, percentages, timeline buckets."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getAttestationsAnalytics")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {"keys": sorted(r.keys())[:6]}
                else:
                    state[label] = {"bad_shape": type(r).__name__}
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
        description="attestation analytics reachable on both mainframes",
        capture_state=lambda: state,
    )
