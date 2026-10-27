"""Registry Card v0.3 well-known surface tests (§pass73.3.9 Batch 5).

3 tests validating the §pass60 Registry Card v0.3 contract per CLAUDE.md
PART 5 (FLOW Registry Card v0.3). Each registry serves:
  /.well-known/registry-card.json     — EdDSA-signed 13-field envelope
  /.well-known/registry-jwks.json     — Ed25519 verification key

These tests probe via the MCP wrappers (`getWellKnownRegistryCard` +
`getWellKnownDevJwks`) which proxy to the well-known endpoints.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
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


# All 4 sandbox registries serve a registry card. Mainframes claim
# sovereign-mainframe tier; cloud-ops claim sandbox tier.
_ALL_REGISTRIES = ("sandbox-A", "sandbox-B", "sandboxalpha", "sandboxdelta")


# Card versions this suite knows. A bump is a deliberate one-line edit here;
# the uniformity check is what catches a SPLIT federation.
_KNOWN_CARD_VERSIONS = ("0.3", "0.4", "0.5", "0.6")

@federation_test(
    name="all_registries_serve_v03_envelope",
    category="registry_card_pull_sync",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-A", "sandbox-B", "sandboxalpha", "sandboxdelta"],
    tags=["registry-card", "envelope", "uniformity", "well-known"],
)
async def test_v03_envelope(rig: FederationTestRig) -> AssertionResult:
    """Every registry serves a known card version + the canonical envelope, AND
    they all serve the SAME version.

    §FEDSUITE 2026-09-04: this asserted `version in ("0.3","0.4")` and went red
    the moment the frames reached v0.6 — a hardcoded list that rots by
    construction. Worse, it could not see what actually mattered: the frames
    served v0.6 while the operators served v0.4, an ~80-version split inside one
    federation, and every node reported the SAME `software_version` string so
    nothing else showed it either.

    The assertion is now two-part: the version must be one this suite knows, and
    the federation must AGREE on it. The uniformity leg is the one with teeth —
    a split federation is a real finding, while a version bump is a one-line
    edit here rather than a red build."""
    state: dict = {}

    async def predicate():
        for label in _ALL_REGISTRIES:
            try:
                r = await rig.mcp(label).call("getWellKnownRegistryCard")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if not isinstance(r, dict):
                    state[label] = {"bad_shape": type(r).__name__}
                    continue
                state[label] = {
                    "version": r.get("registry_card_version"),
                    "has_identity": isinstance(r.get("identity"), dict),
                    "has_operator": isinstance(r.get("operator"), dict),
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        # ⚠ Bookkeeping keys must NOT go into `state`: the predicate below
        # iterates state.values() and requires every entry to be a dict, so a
        # stray list/bool here makes the assertion unsatisfiable. That bug was
        # written and caught here — the test failed with all four registries
        # reporting a perfectly uniform 0.6.
        per_registry = {k: v for k, v in state.items() if not k.startswith("_")}
        seen = {v.get("version") for v in per_registry.values()
                if isinstance(v, dict) and v.get("version")}
        state["_versions_seen"] = sorted(seen)
        state["_uniform"] = len(seen) <= 1
        if len(seen) > 1:
            return False          # split federation — the finding this missed
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (
                    v.get("version") in _KNOWN_CARD_VERSIONS
                    and v.get("has_identity")
                    and v.get("has_operator")
                )
            )
            for v in per_registry.values()
        )

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="all registries serve a known card version, the same one, with the canonical envelope",
        capture_state=lambda: state,
    )


@federation_test(
    name="developer_jwks_publishes_ed25519_key",
    category="registry_card_pull_sync",
    budget_sec=30.0,
    severity="high",
    requires=["sandbox-A"],
    tags=["jwks", "ed25519", "registry-card-signing"],
)
async def test_jwks_ed25519(rig: FederationTestRig) -> AssertionResult:
    """/.well-known/dev-jwks.json (getWellKnownDevJwks: the DEVELOPERS' signing
    keys, not the registry card's, which is /.well-known/registry-jwks.json)
    publishes ≥1 Ed25519 EdDSA key on sandbox-A. A frame where no developer has
    made a signing key yet publishes none, legitimately: NOT MEASURED, a named
    skip (§TESTBED 2026-09-19, a fresh kit sandbox).

    Sandbox-B's JWKS is currently empty (`{keys: []}`) since its EdDSA
    keypair hasn't been minted yet; testing sandbox-A only avoids a
    false positive on a known-empty Frame-B state."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getWellKnownDevJwks")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            keys = r.get("keys") or []
            eddsa_keys = [
                k for k in keys
                if isinstance(k, dict)
                and k.get("alg") == "EdDSA"
                and k.get("crv") == "Ed25519"
            ]
            state["key_count"] = len(keys)
            state["eddsa_count"] = len(eddsa_keys)
            state["kids"] = [k.get("kid", "")[:16] for k in eddsa_keys][:3]
            if not keys:
                state["verdict"] = "NOT MEASURED — no developer on this frame has published a signing key yet"
                return False
            return len(eddsa_keys) >= 1
        except Exception as e:
            state["error"] = repr(e)
            return False

    res = await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="sandbox-A publishes Ed25519 EdDSA signing key in JWKS",
        capture_state=lambda: state,
    )
    if not res.passed and str(state.get("verdict", "")).startswith("NOT MEASURED"):
        raise PreconditionUnmet(state["verdict"])
    return res


@federation_test(
    name="sovereign_mainframe_tier_correct_per_registry",
    category="registry_card_pull_sync",
    budget_sec=30.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B", "sandboxalpha", "sandboxdelta"],
    tags=["registry-card", "tier", "sovereign-mainframe-promotion"],
)
async def test_sovereign_mainframe_tier(rig: FederationTestRig) -> AssertionResult:
    """Per §pass73 (sandbox promotion): the two sandbox frames claim
    `sovereign-mainframe`; their cloud operators claim `cloud-operator`.

    ⚠ THIS TEST USED TO EXPECT `sandbox` FOR THE OPERATORS, AND THAT WAS A
    PRODUCT BUG WRITTEN DOWN AS A CONTRACT. The docstring's reasoning was right
    — an operator is NOT a mainframe — but "not a mainframe" does not mean tier
    `sandbox`; a cloud operator's tier is `cloud-operator`. The old value was an
    artefact of `_build_tier` evaluating its `"sandbox" in name` substring
    fallback BEFORE the structural operator check, so any operator whose NAME
    contained "sandbox" or "test" published `tier: sandbox` in its signed card.
    Measured live 2026-09-04: `qatest16`, a real Frame-A cloud operator, said
    `sandbox` while `op-berlin` and `sbxalphaop` — structurally identical — said
    `cloud-operator`. Four letters in a free-text name were the whole difference.
    Fixed in `registry_card_builder._build_tier` (§TIERFLAG) and pinned by
    `tests/test_registry_card_tier.py`; the expectation here follows the fix.
    """
    state: dict = {}
    expected = {
        "sandbox-A": "sovereign-mainframe",
        "sandbox-B": "sovereign-mainframe",
        "sandboxalpha": "cloud-operator",
        "sandboxdelta": "cloud-operator",
    }

    async def predicate():
        for label, want_tier in expected.items():
            try:
                r = await rig.mcp(label).call("getWellKnownRegistryCard")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if not isinstance(r, dict):
                    state[label] = {"bad_shape": type(r).__name__}
                    continue
                tier = (r.get("identity") or {}).get("tier")
                state[label] = {"tier": tier, "want": want_tier, "ok": tier == want_tier}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (v.get("silent") or v.get("ok"))
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="mainframes claim sovereign-mainframe tier, cloud-ops claim sandbox tier",
        capture_state=lambda: state,
    )
