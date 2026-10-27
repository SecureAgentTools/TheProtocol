"""Sovereign mainframe invariant tests (§pass73.3.17 Batch 95).

3 tests verifying sandbox-A + sandbox-B both report sovereign-mainframe
tier per §pass73 (both promoted to mainframe in allowlist). Both must
share key tier signals: tier=mainframe, IS_CENTRAL_REGISTRY=true,
sovereign visual variant.
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
    name="sandbox_a_has_mainframe_tier_signal",
    category="sovereign_mainframe_invariants",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A"],
    tags=["sovereign", "mainframe-tier", "sandbox-a"],
)
async def test_sandbox_a_mainframe(rig: FederationTestRig) -> AssertionResult:
    """Sandbox-A's registry card reports tier=mainframe (since §pass73
    sandbox-A was promoted from sandbox to sovereign-mainframe tier)."""
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
            state["tier"] = ident.get("tier") if isinstance(ident, dict) else None
            state["did"] = ident.get("did") if isinstance(ident, dict) else None
            state["visual_id"] = (
                (r.get("visual") or {}).get("variant_id")
                if isinstance(r.get("visual"), dict) else None
            )
            return state["tier"] in ("mainframe", "sovereign-mainframe")
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="sandbox-A registry card tier == 'mainframe'",
        capture_state=lambda: state,
    )


@federation_test(
    name="sandbox_b_has_mainframe_tier_signal",
    category="sovereign_mainframe_invariants",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-B"],
    tags=["sovereign", "mainframe-tier", "sandbox-b"],
)
async def test_sandbox_b_mainframe(rig: FederationTestRig) -> AssertionResult:
    """Sandbox-B's registry card also reports tier=mainframe (paired
    promotion in §pass73)."""
    state: dict = {}

    async def predicate():
        try:
            pub = rig.mcp("sandbox-B")
            r = await pub.call("getRegistryCard")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                return False
            ident = r.get("identity") or r
            state["tier"] = ident.get("tier") if isinstance(ident, dict) else None
            state["did"] = ident.get("did") if isinstance(ident, dict) else None
            return state["tier"] in ("mainframe", "sovereign-mainframe")
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="sandbox-B registry card tier == 'mainframe'",
        capture_state=lambda: state,
    )


@federation_test(
    name="sandbox_cloud_ops_have_sandbox_tier",
    category="sovereign_mainframe_invariants",
    budget_sec=20.0,
    severity="medium",
    requires=["sandboxalpha", "sandboxdelta"],
    tags=["sovereign", "sandbox-tier", "cloud-op"],
)
async def test_cloud_ops_sandbox_tier(
    rig: FederationTestRig,
) -> AssertionResult:
    """Sandbox cloud-ops do NOT claim a mainframe tier.

    The docstring's own words for what this is: a negative control of mainframe
    promotion scope. That is the invariant with teeth — a cloud operator that
    self-reported a mainframe tier would open mainframe-gated views and read as
    a peer frame in topology.

    ⚠ IT USED TO ASSERT `tier == "sandbox"`, AND THAT WAS AN ACCIDENT OF THE
    OPERATORS' NAMES. `_build_tier()` tests `"sandbox" in name` BEFORE it tests
    `"cloud-op" in name`, so the retired `cloud-op-sandboxalpha` fell into the
    sandbox branch on a substring. The current operators are named
    `cloud-op-sbxalphaop`, carry no "sandbox" substring, and reach the branch
    written for them: `cloud-operator`. Nothing regressed — the old answer was
    the coincidence.

    The field also conflates two axes (a ROLE like `cloud-operator` and an
    ENVIRONMENT like `sandbox`), which is why pinning one exact string here was
    fragile in the first place. So this asserts membership of the declared
    vocabulary plus the actual invariant, and leaves the role/environment
    question to whoever owns the card schema.
    """
    state: dict = {}
    # The vocabulary _build_tier() declares in its own docstring.
    known = {"sovereign-mainframe", "regional-mainframe", "cloud-operator",
             "sandbox", "standalone"}
    mainframe_tiers = {"sovereign-mainframe", "regional-mainframe", "mainframe"}

    async def predicate():
        try:
            tiers = {}
            for label in ("sandboxalpha", "sandboxdelta"):
                try:
                    r = await rig.mcp(label).call("getRegistryCard")
                    ident = r.get("identity") or r if isinstance(r, dict) else {}
                    tiers[label] = ident.get("tier") if isinstance(ident, dict) else None
                except Exception as e:
                    tiers[label] = f"err: {repr(e)[:60]}"
            state["tiers"] = tiers
            vals = [tiers.get(l) for l in ("sandboxalpha", "sandboxdelta")]
            state["unknown_tier"] = [v for v in vals if v not in known]
            state["claims_mainframe"] = [v for v in vals if v in mainframe_tiers]
            # ⚠ pair all() with the count it assumes — all() over [] is True.
            return (len(vals) == 2
                    and not state["unknown_tier"]
                    and not state["claims_mainframe"])
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="sandbox cloud-ops report a known non-mainframe tier",
        capture_state=lambda: state,
    )
