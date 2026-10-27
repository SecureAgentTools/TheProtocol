"""The canary precondition guard, gated against itself.

`require_canary_subsystem` was added to TEN tests at once. A guard applied that
widely earns its own control: if its discriminator were wrong in the permissive
direction it would convert real red rows into quiet skips across a third of the
failing column, which is precisely the failure mode the guard exists to prevent
in the other direction.

Both directions are exercised here against STUBS — no network, no fixture, so
this runs identically on a bare frame and a busy one:

  * `total_paths == 0`  → PreconditionUnmet. The tier has no canary subsystem.
  * `total_paths  > 0`  → returns the body. A configured path that is missing,
    inactive or failing is a REAL finding and must stay RED; the guard must not
    swallow it.
  * an unreadable body  → PreconditionUnmet, NOT a silent pass. "Could not
    check" is its own state and must never read as "checked and fine".

A guard that cannot distinguish "never provisioned" from "provisioned and
broken" is worse than no guard: the first is a fact about the tier, the second
is a defect, and collapsing them hides the defect behind the fact.
"""
from __future__ import annotations

from typing import Any, Dict

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet, require_canary_subsystem,
)


class _StubMCP:
    def __init__(self, payload: Any):
        self._payload = payload

    async def call(self, tool: str, args: Dict[str, Any], timeout: int = 40) -> Any:
        return self._payload


class _StubRig:
    """Answers `mcp(label)` with a fixed payload — the helper's only dependency."""

    def __init__(self, payload: Any):
        self._payload = payload

    def mcp(self, label: str) -> _StubMCP:
        return _StubMCP(self._payload)


def _wrapped(summary: Dict[str, Any]) -> Dict[str, Any]:
    """The adminRequest envelope the real call returns."""
    return {"ok": True, "status_code": 200, "method": "GET",
            "endpoint": "/api/v1/admin/canary/status",
            "response": {"summary": summary, "paths": [], "agents": []}}


@federation_test(
    name="canary_precondition_guard_discriminates",
    category="event_contract",
    budget_sec=20.0,
    severity="high",
    requires=[],
    tags=["no-probe", "selftest", "control", "canary", "precondition"],
)
async def test_canary_guard_discriminates(rig: FederationTestRig) -> AssertionResult:
    """Zero paths skips; configured paths do not; an unreadable body skips."""
    # `no-probe`: this is STATIC ANALYSIS, not an integration test — it walks
    # the source tree via _census()/the guard under test and never reaches the
    # tier, so the U1 vacuity verdict must not fire on it. The tag is a claim
    # a reader can check, and U1 is what made the distinction visible: before
    # it, a source-reading gate and a tier probe were indistinguishable rows.
    state: Dict[str, Any] = {}

    # 1) no subsystem → must raise
    try:
        await require_canary_subsystem(_StubRig(_wrapped({"total_paths": 0})))
        state["zero_paths"] = "DID NOT RAISE — the guard would never fire"
    except PreconditionUnmet as e:
        state["zero_paths"] = f"raised: {str(e)[:60]}"
    except Exception as e:                       # any other error is also wrong
        state["zero_paths"] = f"WRONG EXCEPTION {type(e).__name__}: {e}"

    # 2) configured → must NOT raise, and must hand back the body
    try:
        body = await require_canary_subsystem(
            _StubRig(_wrapped({"total_paths": 13, "active_paths": 13})))
        got = isinstance(body, dict) and (body.get("summary") or {}).get("total_paths") == 13
        state["configured"] = "returned body" if got else f"returned {type(body).__name__}"
    except Exception as e:
        state["configured"] = f"RAISED {type(e).__name__} — real failures would be skipped"

    # 3) unreadable → must raise, not pass silently
    try:
        await require_canary_subsystem(_StubRig("not a dict at all"))
        state["unreadable"] = "DID NOT RAISE — could-not-check read as fine"
    except PreconditionUnmet as e:
        state["unreadable"] = f"raised: {str(e)[:60]}"
    except Exception as e:
        state["unreadable"] = f"WRONG EXCEPTION {type(e).__name__}: {e}"

    ok = (state["zero_paths"].startswith("raised:")
          and state["configured"] == "returned body"
          and state["unreadable"].startswith("raised:"))
    state["verdict"] = ok

    async def predicate():
        return ok

    return await rig.assert_within(
        budget_sec=5.0, predicate=predicate, poll_interval_sec=1.0,
        description="the canary precondition guard skips an unprovisioned tier, "
                    "stays out of the way of a configured one, and refuses to "
                    "treat an unreadable status as healthy",
        capture_state=lambda: state,
    )
