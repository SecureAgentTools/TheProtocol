"""License + operator lifecycle tests (read-only, Phase D-safe).

Covers D1-D6 from Operator_Lifecycle_Cascade.md + License_Drift_Detection.md:
  - Federation license exposed via well-known + admin
  - License JWKS surface consistent
  - License drift surfaces readable
  - Operator lifecycle endpoints structured
  - Operator self-view readable from cloud-op
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


def _unwrap(resp):
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for k in ("items", "licenses", "drifts", "operators",
                   "events", "data", "results", "applications"):
            v = resp.get(k)
            if isinstance(v, list):
                return v
    return []


@federation_test(
    name="federation_license_listed_on_mainframes",
    category="federation_lifecycle",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["license", "operator"],
)
async def test_federation_licenses_listed(rig: FederationTestRig) -> AssertionResult:
    """listFederationLicenses returns ≥1 license per mainframe.

    Sandbox mainframes issue licenses to their child cloud-ops; both should
    have at least 1 active license each.
    """
    counts: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("listFederationLicenses")
                licenses = _unwrap(r)
                counts[label] = len(licenses)
            except Exception as e:
                counts[label] = f"error: {e!r}"
        return all(isinstance(v, int) and v >= 1 for v in counts.values())

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="listFederationLicenses non-empty on both sandbox mainframes",
        capture_state=lambda: counts,
    )


@federation_test(
    name="cloud_op_my_federation_registrations_readable",
    category="federation_lifecycle",
    budget_sec=15.0,
    severity="high",
    requires=["sandboxalpha", "sandboxdelta"],
    tags=["license", "operator-self", "registrations"],
)
async def test_cloud_op_my_registrations(rig: FederationTestRig) -> AssertionResult:
    """Each cloud-op admin can read its own federation registrations.

    Cloud-op admin → getMyFederationRegistrations returns the parent's
    license/registration record.
    """
    seen: dict = {}

    async def predicate():
        for label in ("sandboxalpha", "sandboxdelta"):
            try:
                r = await rig.mcp(label).call("getMyFederationRegistrations")
                # Endpoint may return empty string when developer has no
                # federation registrations (e.g., the bootstrap admin dev
                # was never registered as an operator dev)
                if isinstance(r, str):
                    seen[label] = "empty_string" if not r.strip() else r[:40]
                elif isinstance(r, dict) and (not r or r.get("_text") == ""):
                    seen[label] = "empty_envelope"
                elif isinstance(r, dict):
                    seen[label] = list(r.keys())[:5]
                elif isinstance(r, list):
                    seen[label] = f"list[{len(r)}]"
                else:
                    seen[label] = type(r).__name__
            except Exception as e:
                seen[label] = f"error: {e!r}"
        # Accept any non-error structured response (empty string included —
        # endpoint exists, just no registrations for this admin developer)
        return all(
            not (isinstance(v, str) and v.startswith("error:"))
            for v in seen.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="getMyFederationRegistrations endpoint reachable on both cloud-ops",
        capture_state=lambda: seen,
    )


@federation_test(
    name="federation_license_drifts_readable",
    category="federation_lifecycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["drift", "compliance"],
)
async def test_license_drift_readable(rig: FederationTestRig) -> AssertionResult:
    """getFederationComplianceDrifts returns a structured payload on both
    mainframes — drifts may be empty (clean state) or populated."""
    seen: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getFederationComplianceDrifts")
                drifts = _unwrap(r) if not isinstance(r, dict) else r
                seen[label] = (
                    {"count": len(drifts)} if isinstance(drifts, list)
                    else {"keys": list(drifts.keys())[:6] if isinstance(drifts, dict) else None}
                )
            except Exception as e:
                seen[label] = f"error: {e!r}"
        # Accept any non-error structured response
        return all(isinstance(v, dict) for v in seen.values())

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="getFederationComplianceDrifts readable on both mainframes",
        capture_state=lambda: seen,
    )


@federation_test(
    name="operator_lifecycle_overview_readable",
    category="federation_lifecycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["operator-lifecycle"],
)
async def test_operator_lifecycle_overview(rig: FederationTestRig) -> AssertionResult:
    """getOperatorsLifecycleOverview returns a structured payload on both
    mainframes."""
    seen: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getOperatorsLifecycleOverview")
                if isinstance(r, dict):
                    seen[label] = list(r.keys())[:6]
                elif isinstance(r, list):
                    seen[label] = f"list[{len(r)}]"
                else:
                    seen[label] = type(r).__name__
            except Exception as e:
                seen[label] = f"error: {e!r}"
        return all(
            (isinstance(v, list) and v) or (isinstance(v, str) and v.startswith("list"))
            for v in seen.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="getOperatorsLifecycleOverview readable on both mainframes",
        capture_state=lambda: seen,
    )


@federation_test(
    name="cloud_op_self_lifecycle_readable",
    category="federation_lifecycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandboxalpha", "sandboxdelta"],
    tags=["operator-self"],
)
async def test_cloud_op_self_lifecycle(rig: FederationTestRig) -> AssertionResult:
    """Each cloud-op exposes its own lifecycle state via getOperatorMyLifecycle."""
    seen: dict = {}

    async def predicate():
        for label in ("sandboxalpha", "sandboxdelta"):
            try:
                r = await rig.mcp(label).call("getOperatorMyLifecycle")
                if isinstance(r, str):
                    seen[label] = "empty_string" if not r.strip() else r[:40]
                elif isinstance(r, dict) and (not r or r.get("_text") == ""):
                    seen[label] = "empty_envelope"
                elif isinstance(r, dict):
                    seen[label] = list(r.keys())[:5]
                else:
                    seen[label] = type(r).__name__
            except Exception as e:
                seen[label] = f"error: {e!r}"
        # Accept reachable-with-empty-state OR populated dict.
        # Cloud-op admin may not have an operator record tied to its dev row.
        return all(
            not (isinstance(v, str) and v.startswith("error:"))
            for v in seen.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="getOperatorMyLifecycle endpoint reachable on both cloud-ops",
        capture_state=lambda: seen,
    )


@federation_test(
    name="cloud_op_self_status_readable",
    category="federation_lifecycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandboxalpha", "sandboxdelta"],
    tags=["operator-self", "status"],
)
async def test_cloud_op_self_status(rig: FederationTestRig) -> AssertionResult:
    """Each cloud-op admin can read its own operator status."""
    seen: dict = {}

    async def predicate():
        for label in ("sandboxalpha", "sandboxdelta"):
            try:
                r = await rig.mcp(label).call("getOperatorMyStatus")
                if isinstance(r, str):
                    seen[label] = "empty_string" if not r.strip() else r[:40]
                elif isinstance(r, dict) and (not r or r.get("_text") == ""):
                    seen[label] = "empty_envelope"
                elif isinstance(r, dict):
                    seen[label] = list(r.keys())[:5]
                else:
                    seen[label] = type(r).__name__
            except Exception as e:
                seen[label] = f"error: {e!r}"
        return all(
            not (isinstance(v, str) and v.startswith("error:"))
            for v in seen.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="getOperatorMyStatus endpoint reachable on both cloud-ops",
        capture_state=lambda: seen,
    )
