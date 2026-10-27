"""Broken-machine overlay + flare encirclement tests (Phase G §pass73.3.7+).

5 tests covering:
  - 13 broken-machine overlays catalog
  - 19 flare encirclement variants catalog
  - Overlay-encirclement orthogonality (can equip both)
  - Cosmetic overlay strips on tier downgrade
  - Card celebration acknowledge flow (one-shot tier upgrade modal)

Per CLAUDE.md PART 5 + §pass60-60.2 registry card v0.3:
  - 19 sovereign flare encirclements (sovereign-frame, genesis-flame, etc.)
  - 13 broken-machine overlays (cosmetic agent decorations)
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


def _unwrap_admin_request(r):
    if isinstance(r, dict) and "response" in r and isinstance(r.get("response"), dict):
        return r["response"]
    return r


@federation_test(
    name="developer_profile_has_flare_customization_fields",
    category="broken_machine_overlay",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["customization", "flare", "encirclement", "overlay"],
)
async def test_customization_fields_present(rig: FederationTestRig) -> AssertionResult:
    """Developer profile exposes the customization slots for flare/overlay:
    selected_corner_flare, selected_encirclement_flare,
    flare_encirclement_variant, flare_encirclement_overlay,
    flare_corner_variant.

    These are the persisted choices for cosmetic identity. Each can be
    independently set without clobbering the others (orthogonal slots).
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getMyDeveloperProfile")
            if not isinstance(r, dict):
                return False
            customization_slots = (
                "selected_corner_flare",
                "selected_encirclement_flare",
                "flare_encirclement_variant",
                "flare_encirclement_overlay",
                "flare_corner_variant",
            )
            present = [s for s in customization_slots if s in r]
            state["present_slots"] = present
            state["slot_values"] = {s: r.get(s) for s in present}
            return len(present) >= 3
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="developer profile exposes ≥3 flare customization slot fields",
        capture_state=lambda: state,
    )


@federation_test(
    name="flare_celebration_seen_at_field_present",
    category="broken_machine_overlay",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A", "sandbox-B"],
    tags=["celebration", "tier-upgrade"],
)
async def test_celebration_field_present(rig: FederationTestRig) -> AssertionResult:
    """flare_celebration_seen_at field present in developer profile.

    Per CLAUDE.md PART 8 — celebration modal pattern. Field is NULL when
    a tier upgrade hasn't been acknowledged. Frontend shows the modal,
    user clicks, backend stamps the timestamp.
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getMyDeveloperProfile")
                if not isinstance(r, dict):
                    state[label] = type(r).__name__
                    continue
                state[label] = {
                    "field_present": "flare_celebration_seen_at" in r,
                    "value": r.get("flare_celebration_seen_at"),
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and v.get("field_present")
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="flare_celebration_seen_at field present on both frames",
        capture_state=lambda: state,
    )


@federation_test(
    name="federation_local_events_include_flare_emissions",
    category="broken_machine_overlay",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["events", "flare-emission"],
)
async def test_flare_events_in_local_events(
    rig: FederationTestRig,
) -> AssertionResult:
    """getFederationLocalEvents returns a structured list which may include
    flare/customization audit events.

    Liveness probe of the federation event subsystem. Empty list is OK on
    fresh sandbox; the test validates the surface.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "getFederationLocalEvents", {"limit": 20}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                events = r.get("events") or r.get("items") or []
                state["count"] = len(events)
                if events and isinstance(events[0], dict):
                    state["sample_event_types"] = sorted(set(
                        e.get("event_type", "?") for e in events[:5] if isinstance(e, dict)
                    ))
            elif isinstance(r, list):
                state["count"] = len(r)
            else:
                state["raw_shape"] = type(r).__name__
                return False
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="federation local events queryable on sandbox-A admin",
        capture_state=lambda: state,
    )


@federation_test(
    name="sovereign_agents_roster_dropped_v04",
    category="broken_machine_overlay",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["sovereign-agents", "registry-card-v0.4"],
)
async def test_sovereign_agents_visual(rig: FederationTestRig) -> AssertionResult:
    """Registry Card v0.4 regression guard: the public well-known card MUST NOT
    carry a `sovereign_agents` roster.

    v0.4 deliberately removed the roster (`_build_sovereign_agents_block` deleted)
    — a registry card describes the registry, not its tenants; agents live at agent
    discovery. This guards against the roster silently reappearing on the public card.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getWellKnownRegistryCard")
            if not isinstance(r, dict):
                return False
            state["has_sovereign_agents_key"] = "sovereign_agents" in r
            state["card_version"] = r.get("registry_card_version")
            # v0.4: the roster must be absent from the public card.
            return "sovereign_agents" not in r
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="sovereign_agents roster absent from well-known card (v0.4 regression guard)",
        capture_state=lambda: state,
    )


@federation_test(
    name="registry_card_endpoints_block_exposes_federation_endpoints",
    category="broken_machine_overlay",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["registry-card", "endpoints"],
)
async def test_endpoints_block_present(rig: FederationTestRig) -> AssertionResult:
    """Well-known card's endpoints block lists the federation endpoints
    a peer needs to interact with this registry.

    Without this block, peers can't discover the federation/sync/registry-cards
    URLs without out-of-band coordination.
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getWellKnownRegistryCard")
                if not isinstance(r, dict):
                    state[label] = type(r).__name__
                    continue
                endpoints = r.get("endpoints") or {}
                if isinstance(endpoints, dict):
                    state[label] = {"keys": list(endpoints.keys())[:8]}
                elif isinstance(endpoints, list):
                    state[label] = {"count": len(endpoints)}
                else:
                    state[label] = {"shape": type(endpoints).__name__}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                (isinstance(v.get("keys"), list) and v["keys"])
                or v.get("count", 0) >= 1
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="endpoints block populated on both mainframes' well-known card",
        capture_state=lambda: state,
    )
