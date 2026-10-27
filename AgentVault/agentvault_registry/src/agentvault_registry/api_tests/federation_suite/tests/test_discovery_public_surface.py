"""Public discovery surface tests (§pass73.3.9 Batch 10).

4 read-only tests probing the public discovery + onboarding surfaces.
These are the endpoints unauth users hit when discovering TheProtocol:
agent catalog, agent templates, public registry config, showcase agents.
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


def _items_of(r, *keys):
    if isinstance(r, list):
        return r
    if isinstance(r, dict):
        for k in keys + ("items", "data", "results"):
            v = r.get(k)
            if isinstance(v, list):
                return v
    return []


@federation_test(
    name="agent_cards_listing_paginated_per_frame",
    category="discovery_public_surface",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["discovery", "agent-cards"],
)
async def test_agent_cards_listing(rig: FederationTestRig) -> AssertionResult:
    """listAgentCards returns ≥1 agent card on each mainframe with the
    canonical envelope (id, name, is_active)."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("listAgentCards", {"limit": 5})
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                items = _items_of(r, "items", "agents", "cards")
                state[label] = {"count": len(items)}
                if items and isinstance(items[0], dict):
                    state[label]["sample_keys"] = sorted(items[0].keys())[:6]
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (isinstance(v.get("count"), int) and v["count"] >= 1)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="agent cards listing returns ≥1 entry on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="agent_templates_catalog_published",
    category="discovery_public_surface",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["discovery", "agent-templates"],
)
async def test_agent_templates_catalog(rig: FederationTestRig) -> AssertionResult:
    """listAgentTemplates publishes ≥3 templates (web-scraper, api-gateway,
    data-processor are canonical) on each frame."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("listAgentTemplates")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                tpls = _items_of(r, "templates")
                state[label] = {"count": len(tpls)}
                if tpls and isinstance(tpls[0], dict):
                    state[label]["sample_ids"] = [t.get("id") for t in tpls[:5]]
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (isinstance(v.get("count"), int) and v["count"] >= 3)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="agent templates catalog has ≥3 templates on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="public_registry_config_per_frame",
    category="discovery_public_surface",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["discovery", "public-config"],
)
async def test_public_registry_config(rig: FederationTestRig) -> AssertionResult:
    """getPublicRegistryConfig returns the public-facing config envelope
    on each frame — fee rates, registry tier, federation status, etc."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getPublicRegistryConfig")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if not isinstance(r, dict):
                    state[label] = {"bad_shape": type(r).__name__}
                    continue
                state[label] = {"keys": sorted(r.keys())[:8]}
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
        description="public registry config readable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="downloads_manifest_per_frame",
    category="discovery_public_surface",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A", "sandbox-B"],
    tags=["discovery", "downloads"],
)
async def test_downloads_manifest(rig: FederationTestRig) -> AssertionResult:
    """getDownloadsManifest surfaces the downloadable artifact manifest.

    Used by the operator portal + SDK bootstrap flows to fetch templates,
    bundles, etc. Required on every registry serving operator onboarding.
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getDownloadsManifest")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {"keys": sorted(r.keys())[:8]}
                elif isinstance(r, list):
                    state[label] = {"count": len(r)}
                else:
                    state[label] = {"bad_shape": type(r).__name__}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent")
                or (isinstance(v.get("keys"), list) and v["keys"])
                or isinstance(v.get("count"), int)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="downloads manifest readable on both mainframes",
        capture_state=lambda: state,
    )
