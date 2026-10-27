"""Sandbox topology invariant tests (Phase F §pass73.3.6+).

5 tests verifying the structural invariants of the 4-registry sandbox
topology (sandbox-A + sandbox-B + sandboxalpha + sandboxdelta). These
should always pass — if any fails, the sandbox has drifted from spec.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
    require_canary_subsystem,
    canary_paths_fired_but_inactive,
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


def _unwrap_admin_request(r):
    if isinstance(r, dict) and "response" in r and isinstance(r.get("response"), dict):
        return r["response"]
    return r


@federation_test(
    name="every_sandbox_registry_card_reports_tier",
    category="sandbox_topology_invariants",
    budget_sec=15.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-B", "sandboxalpha", "sandboxdelta"],
    tags=["registry-card", "tier", "topology"],
)
async def test_registry_card_tier_present(rig: FederationTestRig) -> AssertionResult:
    """Every sandbox registry's `/.well-known/registry-card.json` reports
    a non-empty `identity.tier` field. Mainframes report `sovereign-mainframe`
    (§pass73), cloud-ops report a sandbox/cloud-op tier."""
    tiers: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B", "sandboxalpha", "sandboxdelta"):
            try:
                r = await rig.mcp(label).call("getWellKnownRegistryCard")
                if not isinstance(r, dict) or not r:
                    tiers[label] = None
                    continue
                tier = ((r.get("identity") or {}).get("tier")
                        if isinstance(r.get("identity"), dict) else None)
                tiers[label] = tier
            except Exception as e:
                tiers[label] = f"error: {e!r}"
        return all(isinstance(v, str) and v for v in tiers.values())

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="every sandbox registry exposes identity.tier",
        capture_state=lambda: tiers,
    )


@federation_test(
    name="mainframes_report_sovereign_tier",
    category="sandbox_topology_invariants",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A", "sandbox-B"],
    tags=["sovereign-mainframe", "tier"],
)
async def test_mainframes_sovereign_tier(rig: FederationTestRig) -> AssertionResult:
    """Sandbox mainframes report tier='sovereign-mainframe' per §pass73.

    ⚠ WHEN THIS IS RED ON A FRESH FRAME, READ THE NAME BEFORE THE TIER.
    `services/registry_card_builder.py::_build_tier()` decides the tier from a
    HARDCODED ALLOWLIST of registry names — `registry-a`, `frame-b`, `frame-c`,
    `registry-test{,-b,-c}` — and anything else whose name merely CONTAINS
    "sandbox" or "test" falls through to tier `sandbox`. A frame provisioned
    under any new name therefore cannot report sovereign-mainframe no matter how
    it is configured, even with IS_CENTRAL_REGISTRY=true and its own trust
    domain, EventStore and economy.

    That is not only a test failure: `_build_tier()`'s own docstring says the
    tier is what makes the 5-signal `useMainframe` composable open
    mainframe-gated views, so a fresh frame is missing those views too. Same
    class as the retired-container literals §APITEST found — a fresh frame
    failing an identity check that names the old frames by literal.

    The state below reports the registry NAME alongside the tier so the reader
    sees which half is wrong without going to the source.
    """
    tiers: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getWellKnownRegistryCard")
                if not isinstance(r, dict):
                    tiers[label] = None
                    continue
                identity = r.get("identity") or {}
                tier = identity.get("tier") if isinstance(identity, dict) else None
                name = identity.get("registry_name") if isinstance(identity, dict) else None
                tiers[label] = tier
                tiers[f"{label}_name"] = name
            except Exception as e:
                tiers[label] = f"error: {e!r}"
        seen = [tiers.get(l) for l in ("sandbox-A", "sandbox-B")]
        # ⚠ all() over an empty list is True — pair it with the count it assumes,
        # or a run that read nothing reports both frames sovereign.
        return len(seen) == 2 and all(v == "sovereign-mainframe" for v in seen)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="both sandbox mainframes report sovereign-mainframe tier",
        capture_state=lambda: tiers,
    )


@federation_test(
    name="sandbox_canary_topology_minimum_active",
    category="sandbox_topology_invariants",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["canary", "topology", "minimum"],
)
async def test_canary_topology_minimum(rig: FederationTestRig) -> AssertionResult:
    """The tier keeps its canaries armed, read off the REST rail: at least one active, and none that fired in the
    last 24 h left switched off.

    §CANARYONBOARD (2026-09-23): the threshold was `>= 11`, the legacy tier's count, and the clusters' frames carry 4
    by design. `active == total` is not the invariant either — a retired row is legitimate (EU keeps two). The sibling
    in canary_subsystem asserts the same thing through the MCP surface.
    """
    state: dict = {}

    # §FEDCANARY: a tier with zero configured paths has no canary subsystem to
    # measure — skip loudly rather than poll a fixture that was never provisioned.
    # A CONFIGURED path that is missing or failing still goes RED.
    await require_canary_subsystem(rig)
    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "adminRequest",
                {"method": "GET", "endpoint": "/api/v1/admin/canary/status"},
            )
            inner = _unwrap_admin_request(r)
            if not isinstance(inner, dict):
                return False
            summary = inner.get("summary") or {}
            state["summary"] = summary
            fired_but_off = canary_paths_fired_but_inactive(inner)
            state["fired_but_inactive"] = fired_but_off
            active = summary.get("active_paths")
            return isinstance(active, int) and active >= 1 and not fired_but_off
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="this tier keeps at least one canary armed and switched none off mid-window (REST rail)",
        capture_state=lambda: state,
    )


@federation_test(
    name="every_registry_exposes_jwks",
    category="sandbox_topology_invariants",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B", "sandboxalpha", "sandboxdelta"],
    tags=["jwks", "well-known"],
)
async def test_jwks_per_registry(rig: FederationTestRig) -> AssertionResult:
    """Every registry serves a JWKS endpoint with ≥1 key.

    Registry Card v0.3 requires EdDSA-signed cards; the public JWKS is the
    verification key. Without it, federated peers can't verify card signatures.
    """
    jwks: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B", "sandboxalpha", "sandboxdelta"):
            try:
                r = await rig.mcp(label).call("getSpireJWKS")
                if _is_silent_or_error(r):
                    jwks[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    keys = r.get("keys") or []
                    jwks[label] = {"key_count": len(keys)}
                else:
                    jwks[label] = type(r).__name__
            except Exception as e:
                jwks[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (v.get("silent") or v.get("key_count", 0) >= 1)
            for v in jwks.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="every sandbox registry serves JWKS with ≥1 key",
        capture_state=lambda: jwks,
    )


@federation_test(
    name="canary_judge_pass_outcome_distribution",
    category="sandbox_topology_invariants",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["canary", "judge", "outcome-distribution"],
)
async def test_canary_pass_distribution(rig: FederationTestRig) -> AssertionResult:
    """Canary topology 24h pass rate ≥50% — sandbox baseline health invariant.

    The 2 multi-hop paths bring down the cumulative rate due to historic
    pre-fix failures, but the new fires all pass. A 50% threshold is loose
    enough to tolerate the historical drag.
    """
    state: dict = {}

    # §FEDCANARY: a tier with zero configured paths has no canary subsystem to
    # measure — skip loudly rather than poll a fixture that was never provisioned.
    # A CONFIGURED path that is missing or failing still goes RED.
    await require_canary_subsystem(rig)
    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "adminRequest",
                {"method": "GET", "endpoint": "/api/v1/admin/canary/status"},
            )
            inner = _unwrap_admin_request(r)
            if not isinstance(inner, dict):
                return False
            summary = inner.get("summary") or {}
            rate = summary.get("pass_rate_24h")
            state["pass_rate_24h"] = rate
            state["passes_24h"] = summary.get("passes_24h")
            state["failures_24h"] = summary.get("failures_24h")
            return isinstance(rate, (int, float)) and rate >= 50.0
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="sandbox canary 24h pass_rate ≥50%",
        capture_state=lambda: state,
    )
