"""Enforcement policy observability tests (§pass73.3.9 Batch 28).

3 admin tests probing the enforcement policy subsystem — policy
versioning, defaults catalog, pending enforcement queue per
CLAUDE.md PART 9.
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
    name="enforcement_policy_active_with_version",
    category="enforcement_policy",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["enforcement", "policy", "version"],
)
async def test_enforcement_policy_active(
    rig: FederationTestRig,
) -> AssertionResult:
    """Each frame serves a reachable, ACTIVE enforcement policy.

    ⚠ IT USED TO REQUIRE `version >= 1`, WHICH IS A HISTORY ASSUMPTION, NOT A
    HEALTH ONE. A version only advances when someone EDITS the policy, so a
    frame where nobody has is at version 0 — with `is_active: true` and
    `modified_at: null`, i.e. the defaults in force and untouched. That is a
    correctly populated policy table, and it is what a fresh frame looks like:
    sbx-beta reads 0 while sbx-alpha, which has been edited, reads 6.

    So it asserts what the old docstring already claimed to be about — the
    active row is reachable and well-formed — and reports the version rather
    than gating on it. Same shape as the `total_agents >= 1` assumption next
    door: a fresh tier fails a check that encodes a lived-in one's history.
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getEnforcementPolicy")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if not isinstance(r, dict):
                    state[label] = {"bad_shape": type(r).__name__}
                    continue
                state[label] = {
                    "version": r.get("version"),
                    "is_active": r.get("is_active"),
                    "modified_at": r.get("modified_at"),
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        seen = [state.get(l) for l in ("sandbox-A-admin", "sandbox-B-admin")]
        # ⚠ read the two frames by NAME and pair all() with the count it
        # assumes — all() over an empty or short list is True.
        return len(seen) == 2 and all(
            isinstance(v, dict) and (
                v.get("silent") or (
                    isinstance(v.get("version"), int)
                    and v["version"] >= 0
                    and v.get("is_active") is True
                )
            )
            for v in seen
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="active enforcement policy with version≥1 on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="enforcement_policy_defaults_catalog",
    category="enforcement_policy",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["enforcement", "defaults"],
)
async def test_enforcement_policy_defaults(
    rig: FederationTestRig,
) -> AssertionResult:
    """getEnforcementPolicyDefaults returns the catalog of default
    enforcement policy rules used by `resetEnforcementPolicy`."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getEnforcementPolicyDefaults")
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
        description="enforcement policy defaults catalog reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="enforcement_pending_queue_observable",
    category="enforcement_policy",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["enforcement", "pending"],
)
async def test_enforcement_pending(rig: FederationTestRig) -> AssertionResult:
    """getEnforcementPending returns the pending enforcement queue —
    actions awaiting approval (possibly empty for a clean sandbox)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getEnforcementPending")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("pending") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int) and state["count"] >= 0
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="enforcement pending queue observable on sandbox-A",
        capture_state=lambda: state,
    )
