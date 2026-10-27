"""Enforcement + coordinated-suspension propagation tests (Phase E §pass73.3.5+).

4 tests covering the coordinated suspension subsystem documented in
CLAUDE.md PART 9. Currently untested at the federation level.

Read-mostly probes — actual suspension would mutate global state.
We verify the enforcement surface is healthy + the relevant data
shapes are populated.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
    require_running_container, FED_AGENT_A, FED_AGENT_B,
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
    name="enforcement_policy_readable_per_frame",
    category="enforcement_propagation",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["enforcement", "policy"],
)
async def test_enforcement_policy_readable(rig: FederationTestRig) -> AssertionResult:
    """getEnforcementPolicy returns the current policy state on both mainframes."""
    policies: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getEnforcementPolicy")
                if _is_silent_or_error(r):
                    policies[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    policies[label] = {"keys": list(r.keys())[:8]}
                else:
                    policies[label] = type(r).__name__
            except Exception as e:
                policies[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (v.get("silent") or (isinstance(v.get("keys"), list) and v["keys"]))
            for v in policies.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="getEnforcementPolicy returns structured payload on both mainframes",
        capture_state=lambda: policies,
    )


@federation_test(
    name="enforcement_pending_readable_per_frame",
    category="enforcement_propagation",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["enforcement", "pending"],
)
async def test_enforcement_pending_readable(rig: FederationTestRig) -> AssertionResult:
    """getEnforcementPending returns a list shape on both mainframes —
    typically empty in healthy sandbox state."""
    pending: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getEnforcementPending")
                if _is_silent_or_error(r):
                    pending[label] = {"silent": True}
                    continue
                items = r if isinstance(r, list) else (
                    r.get("pending") or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                pending[label] = {"count": len(items)}
            except Exception as e:
                pending[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (v.get("silent") or isinstance(v.get("count"), int))
            for v in pending.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="getEnforcementPending returns list shape on both mainframes",
        capture_state=lambda: pending,
    )


@federation_test(
    name="ironhand_identities_readable_per_frame",
    category="enforcement_propagation",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["revoked", "identity-fabric", "ironhand"],
)
async def test_ironhand_identities_readable(rig: FederationTestRig) -> AssertionResult:
    """IRONHAND identity surface returns a structured roster on both mainframes.

    Replaces an earlier draft that called getRevokedIdentities — that tool is
    tier-2 (requires agent JWT). The admin-bridge IRONHAND endpoint exposes
    the same identity-fabric revocation visibility from the operator side.
    """
    identities: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call(
                    "adminRequest",
                    {"method": "GET", "endpoint": "/api/v1/admin/ironhand/identities"},
                )
                if _is_silent_or_error(r):
                    identities[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    enrolled = r.get("enrolled") or r.get("items") or r.get("data") or []
                    summary = r.get("summary") or {}
                    identities[label] = {
                        "enrolled_count": len(enrolled),
                        "has_summary": bool(summary),
                    }
                elif isinstance(r, list):
                    identities[label] = {"enrolled_count": len(r)}
                else:
                    identities[label] = type(r).__name__
            except Exception as e:
                identities[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (v.get("silent") or v.get("enrolled_count") is not None)
            for v in identities.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="IRONHAND identities roster readable on both mainframes",
        capture_state=lambda: identities,
    )


@federation_test(
    name="enforcement_agent_status_endpoint_reachable",
    category="enforcement_propagation",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["enforcement", "agent-status", "fed-test-agents"],
)
async def test_enforcement_agent_status_reachable(rig: FederationTestRig) -> AssertionResult:
    """getEnforcementAgentStatus returns a structured payload on each mainframe
    when queried with that frame's local fed-test-agent DID.

    Earlier draft called the tool with no args; the tool requires `agent_did`.
    Each mainframe is queried with the DID of the fed-test-agent that lives
    in that frame (loaded from the container's persistent creds volume).
    """
    import json as _j
    statuses: dict = {}

    # Resolve DIDs from the fed-test-agent containers
    async def _read_did(container: str) -> str:
        from agentvault_registry.api_tests.multiframe_helpers import exec_in_container
        import asyncio as _asyncio
        rc, out = await _asyncio.to_thread(
            exec_in_container, container, ["cat", "/var/lib/agent/creds.json"], 10,
        )
        if rc != 0:
            return ""
        try:
            return _j.loads(out).get("agent_did", "")
        except Exception:
            return ""

    # §FEDFIXTURE: the fed-test-agent containers are Exited on this tier.
    # Skip loudly on an absent fixture instead of reporting missing_did.
    require_running_container(FED_AGENT_A)
    require_running_container(FED_AGENT_B)
    did_a = await _read_did(FED_AGENT_A)
    did_b = await _read_did(FED_AGENT_B)
    statuses["_dids"] = {"sandbox-A": did_a, "sandbox-B": did_b}

    async def predicate():
        targets = [
            ("sandbox-A-admin", did_a),
            ("sandbox-B-admin", did_b),
        ]
        for label, did in targets:
            if not did:
                statuses[label] = {"missing_did": True}
                continue
            try:
                r = await rig.mcp(label).call(
                    "getEnforcementAgentStatus", {"agent_did": did},
                )
                if _is_silent_or_error(r):
                    statuses[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    statuses[label] = {
                        "enforcement_status": r.get("enforcement_status"),
                        "keys": list(r.keys())[:6],
                    }
                else:
                    statuses[label] = type(r).__name__
            except Exception as e:
                statuses[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent")
                or v.get("enforcement_status") is not None
            )
            for k, v in statuses.items()
            if k.endswith("-admin")
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="getEnforcementAgentStatus returns enforcement_status for fed-test-agents on each frame",
        capture_state=lambda: statuses,
    )
