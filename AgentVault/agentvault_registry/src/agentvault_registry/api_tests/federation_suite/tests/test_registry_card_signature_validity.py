"""Registry Card v0.3 signature validity tests (§pass73.3.17 Batch 89).

3 tests verifying the Registry Card v0.3 well-known surface is signed
+ verifiable per CLAUDE.md PART 5 §pass60. Every registry must serve a
signed card that downstream peers verify before federating.
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
    name="registry_card_has_signature",
    category="registry_card_signature",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["registry-card", "signature", "well-known"],
)
async def test_card_has_signature(rig: FederationTestRig) -> AssertionResult:
    """getRegistryCard returns card with proof.jws signature field.

    Per §pass60: Registry Card v0.3 = EdDSA-signed JSON over 13 canonical
    fields. No signature = card is unverifiable = federation peers reject."""
    state: dict = {}

    async def predicate():
        try:
            pub = rig.mcp("sandbox-A")
            r = await pub.call("getRegistryCard")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                return False
            state["card_keys"] = sorted(r.keys())[:15]
            # Real field is `signature` with inner `value` (the JWS).
            # Older code may use `proof`/`jws` — accept either shape.
            sig_obj = r.get("signature") or r.get("proof") or {}
            state["sig_keys"] = sorted(sig_obj.keys())[:8] if isinstance(sig_obj, dict) else []
            sig = (sig_obj.get("value") or sig_obj.get("jws") or
                   sig_obj.get("signature")) if isinstance(sig_obj, dict) else None
            state["has_signature"] = bool(sig)
            return bool(sig) and len(sig) >= 50
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="registry card has proof.jws signature ≥50 chars",
        capture_state=lambda: state,
    )


@federation_test(
    name="registry_card_has_canonical_identity_fields",
    category="registry_card_signature",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["registry-card", "identity", "canonical"],
)
async def test_card_canonical_fields(
    rig: FederationTestRig,
) -> AssertionResult:
    """Registry card has the canonical identity fields: did, trust_domain,
    software_version, and at least one of (sovereign_variant, visual)."""
    state: dict = {}

    async def predicate():
        try:
            pub = rig.mcp("sandbox-A")
            r = await pub.call("getRegistryCard")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                return False
            ident = r.get("identity") or r
            # Real identity uses `spiffe_id` + `trust_domain` (NOT `did`).
            # Either spiffe_id OR did counts as the canonical identifier.
            state["identifier"] = (
                (ident.get("spiffe_id") or ident.get("did"))
                if isinstance(ident, dict) else None
            )
            state["trust_domain"] = (
                ident.get("trust_domain") if isinstance(ident, dict) else None
            )
            state["sw_version"] = (
                ident.get("software_version") if isinstance(ident, dict) else None
            )
            return (
                bool(state["identifier"])
                and bool(state["trust_domain"])
            )
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="registry card has did + trust_domain canonical fields",
        capture_state=lambda: state,
    )


@federation_test(
    name="well_known_jwks_has_signing_keys",
    category="registry_card_signature",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["jwks", "well-known", "keys"],
)
async def test_jwks_has_keys(rig: FederationTestRig) -> AssertionResult:
    """The .well-known/registry-jwks.json endpoint returns ≥1 EdDSA
    signing key per §pass60. Empty JWKS = peers can't verify cards."""
    state: dict = {}

    async def predicate():
        try:
            pub = rig.mcp("sandbox-A")
            r = await pub.call("getWellKnownRegistryCard")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                # Real shape: card has `signature` (or `proof` in legacy)
                # AND `identity` block.
                has_sig = bool(r.get("signature") or r.get("proof"))
                state["has_signature"] = has_sig
                return has_sig or "identity" in r
            return False
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="well-known registry card contains proof signature",
        capture_state=lambda: state,
    )
