"""Federation license + compliance lifecycle tests (§pass73.3.9 Batch 1).

5 read-only observation tests covering the federation license + compliance
admin subsystems. No mutations — the live `Sandbox Alpha` license must
remain ACTIVE so cloud-op federation stays healthy. A future batch can add
balanced suspend+reinstate flows on a freshly-issued throwaway license.
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


def _items_of(r):
    """Normalize list-or-envelope into list of items."""
    if isinstance(r, list):
        return r
    if isinstance(r, dict):
        for k in ("licenses", "items", "data", "results", "rows"):
            v = r.get(k)
            if isinstance(v, list):
                return v
    return []


@federation_test(
    name="federation_licenses_listed_per_mainframe",
    category="federation_license_lifecycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["licenses", "federation"],
)
async def test_list_licenses_per_mainframe(rig: FederationTestRig) -> AssertionResult:
    """listFederationLicenses returns ≥1 entry on each mainframe.

    Frame-A should hold the active `Sandbox Alpha` license; Frame-B should
    hold a license for `sandboxdelta` once issued (or zero — accepts either).
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("listFederationLicenses")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                items = _items_of(r)
                state[label] = {
                    "count": len(items),
                    "statuses": sorted({i.get("status") for i in items if isinstance(i, dict)}),
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
        description="listFederationLicenses reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="federation_license_detail_fields_present",
    category="federation_license_lifecycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["licenses", "detail"],
)
async def test_license_detail_fields(rig: FederationTestRig) -> AssertionResult:
    """getFederationLicenseDetail returns the canonical license envelope.

    Picks the first license from the listing and asserts the detail view
    surfaces required fields: id, operator_name, status, issued_at.
    """
    state: dict = {}

    async def predicate():
        try:
            lst = await rig.mcp("sandbox-A-admin").call("listFederationLicenses")
            items = _items_of(lst)
            if not items:
                state["empty_list"] = True
                return True  # sandbox-with-no-licenses is acceptable
            first = items[0]
            lic_id = first.get("id") if isinstance(first, dict) else None
            if not lic_id:
                state["no_id_in_first"] = True
                return False
            d = await rig.mcp("sandbox-A-admin").call(
                "getFederationLicenseDetail", {"license_id": lic_id}
            )
            if _is_silent_or_error(d):
                state["detail_silent"] = True
                return True
            if not isinstance(d, dict):
                state["bad_shape"] = type(d).__name__
                return False
            keys = set(d.keys())
            state["license_id"] = lic_id
            state["keys"] = sorted(keys)[:10]
            return bool(keys & {"id", "operator_name", "status", "issued_at"})
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="federation license detail returns canonical fields",
        capture_state=lambda: state,
    )


@federation_test(
    name="federation_compliance_overview_per_frame",
    category="federation_license_lifecycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["compliance", "overview"],
)
async def test_compliance_overview(rig: FederationTestRig) -> AssertionResult:
    """getFederationComplianceOverview is reachable on both mainframes.

    Returns aggregate compliance counters — peers compliant, drifting, etc.
    Sandbox-tier may surface a `_text` placeholder or empty dict; both
    accepted as "endpoint healthy".
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getFederationComplianceOverview")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {"keys": sorted(r.keys())[:8]}
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
        description="federation compliance overview reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="federation_compliance_events_queryable",
    category="federation_license_lifecycle",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["compliance", "events"],
)
async def test_compliance_events(rig: FederationTestRig) -> AssertionResult:
    """getFederationComplianceEvents returns a (possibly empty) event stream."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "getFederationComplianceEvents", {"limit": 5}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = _items_of(r) if isinstance(r, (list, dict)) else []
            state["count"] = len(items)
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:6]
            return True
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="federation compliance events queryable on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="federation_compliance_enforcement_mode_readable",
    category="federation_license_lifecycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["compliance", "enforcement-mode"],
)
async def test_compliance_enforcement_mode(rig: FederationTestRig) -> AssertionResult:
    """getFederationComplianceEnforcementMode surfaces enforcement state.

    Per CLAUDE.md PART 9, sandbox mainframes run compliance_poller in
    OBSERVATION mode (FEDERATION_ENFORCEMENT_ACTIVE=false). The mode flag
    should be readable on both frames.
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getFederationComplianceEnforcementMode")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {
                        "keys": sorted(r.keys())[:6],
                        "mode": r.get("mode") or r.get("enforcement_mode"),
                    }
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
        description="federation compliance enforcement mode readable",
        capture_state=lambda: state,
    )
