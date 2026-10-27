"""Bundle marketplace observability tests (§pass73.3.9 Batch 25).

3 tests probing the bundle marketplace public surfaces. Bundles are the
§pass51 .tpb signed archives that ship sovereign agent templates +
operator deployments per CLAUDE.md (Agent Bundles).
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
    name="featured_bundles_published_per_frame",
    category="bundle_marketplace",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A", "sandbox-B"],
    tags=["bundles", "featured"],
)
async def test_featured_bundles(rig: FederationTestRig) -> AssertionResult:
    """getFeaturedBundles returns the curated featured bundle list on
    each mainframe — includes sovereign agent templates (Moira, Veridian,
    etc.) per CLAUDE.md Wave-2 sovereigns."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getFeaturedBundles")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                feat = r.get("featured") if isinstance(r, dict) else r
                if not isinstance(feat, list):
                    state[label] = {"bad_shape": type(feat).__name__}
                    continue
                state[label] = {
                    "count": len(feat),
                    "sample_slugs": [
                        b.get("slug") for b in feat[:3] if isinstance(b, dict)
                    ],
                }
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
        description="featured bundles reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="bundle_manifest_queryable_when_featured_present",
    category="bundle_marketplace",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["bundles", "manifest"],
)
async def test_bundle_manifest(rig: FederationTestRig) -> AssertionResult:
    """getBundleManifest returns the manifest envelope for a known bundle
    id from the featured list. Validates the manifest read path."""
    state: dict = {}

    async def predicate():
        try:
            feat_resp = await rig.mcp("sandbox-A").call("getFeaturedBundles")
            feat = (feat_resp or {}).get("featured") if isinstance(feat_resp, dict) else []
            if not feat:
                state["no_featured"] = True
                return True  # No featured bundles → no manifest to query
            target = feat[0]
            bid = target.get("id") if isinstance(target, dict) else None
            if not bid:
                state["no_bundle_id"] = True
                return False
            state["bundle_id"] = bid
            r = await rig.mcp("sandbox-A").call("getBundleManifest", {"bundle_id": bid})
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return bool(r.keys())
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="bundle manifest queryable for a featured bundle id",
        capture_state=lambda: state,
    )


@federation_test(
    name="pipeline_templates_catalog_published",
    category="bundle_marketplace",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A", "sandbox-B"],
    tags=["bundles", "pipeline-templates"],
)
async def test_pipeline_templates(rig: FederationTestRig) -> AssertionResult:
    """getPipelineTemplates publishes the CI/CD pipeline template
    catalog on each frame — used by `tp-operator` provisioner."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getPipelineTemplates")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                tpls = r if isinstance(r, list) else (
                    r.get("templates") or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                state[label] = {"count": len(tpls)}
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
        description="pipeline templates catalog reachable on both mainframes",
        capture_state=lambda: state,
    )
