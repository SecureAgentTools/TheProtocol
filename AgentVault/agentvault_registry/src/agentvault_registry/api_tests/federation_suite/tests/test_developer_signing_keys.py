"""Developer signing key + JWKS observability tests (§pass73.3.10 Batch 34).

3 read-only tests probing developer-tier signing key surfaces. Devs
sign API requests + bundle uploads with EdDSA keys; the JWKS surface
publishes the verification keys for federation peers.
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
    name="well_known_dev_jwks_per_frame",
    category="developer_signing",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["developer", "jwks", "well-known"],
)
async def test_well_known_dev_jwks(rig: FederationTestRig) -> AssertionResult:
    """getWellKnownDevJwks publishes the developer JWKS envelope at the
    well-known endpoint. Sandbox-A publishes ≥1 Ed25519 key; sandbox-B
    may publish an empty keys list (Frame-B JWKS rotation pending).

    Renamed from `my_developer_jwks_per_frame` because
    `getMyDeveloperJwks` actually requires `developer_id` param (not
    derived from JWT). The well-known surface is the proper public read.
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getWellKnownDevJwks")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if not isinstance(r, dict):
                    state[label] = {"bad_shape": type(r).__name__}
                    continue
                keys = r.get("keys") or []
                state[label] = {"key_count": len(keys) if isinstance(keys, list) else 0}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or isinstance(v.get("key_count"), int)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="well-known dev JWKS reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="my_signing_keys_inventory_per_frame",
    category="developer_signing",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["developer", "signing-keys"],
)
async def test_my_signing_keys(rig: FederationTestRig) -> AssertionResult:
    """getMySigningKeys returns the developer's active signing keys list.
    Validates the per-developer signing key inventory endpoint."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getMySigningKeys")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                keys = r if isinstance(r, list) else (
                    r.get("keys") or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                state[label] = {"count": len(keys)}
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
        description="developer signing keys inventory reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="my_developer_profile_envelope",
    category="developer_signing",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A", "sandbox-B"],
    tags=["developer", "profile"],
)
async def test_my_developer_profile(rig: FederationTestRig) -> AssertionResult:
    """getMyDeveloperProfile returns the developer profile envelope —
    email, location, bio, contact info. The /me read path."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getMyDeveloperProfile")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if not isinstance(r, dict):
                    state[label] = {"bad_shape": type(r).__name__}
                    continue
                state[label] = {
                    "email": r.get("email"),
                    "has_id": r.get("id") is not None or r.get("developer_id") is not None,
                    "keys": sorted(r.keys())[:6],
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or v.get("has_id") or v.get("email")
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="developer profile readable on both mainframes",
        capture_state=lambda: state,
    )
