"""Pagination contract tests (§pass73.3.17 Batch 80).

3 tests verifying paginated admin endpoints obey limit/offset
semantics: total monotonically reflects DB, limit caps items, offset
advances the window deterministically.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


@federation_test(
    name="pagination_limit_caps_returned_items",
    category="pagination_contract",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["pagination", "limit"],
)
async def test_limit_caps(rig: FederationTestRig) -> AssertionResult:
    """getAdminDevelopers with limit=5 returns exactly 5 items (assuming
    >5 devs exist) — limit clause works."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getAdminDevelopers", {"limit": 5})
            items = r if isinstance(r, list) else (
                r.get("developers") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["limit_5_count"] = len(items)
            state["total"] = r.get("total") if isinstance(r, dict) else None
            # Sandbox-A has thousands of devs → limit=5 must return exactly 5
            return len(items) == 5
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="limit=5 returns exactly 5 items when DB has ≥5",
        capture_state=lambda: state,
    )


@federation_test(
    name="pagination_offset_advances_window",
    category="pagination_contract",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["pagination", "offset"],
)
async def test_offset_advances(rig: FederationTestRig) -> AssertionResult:
    """getAdminDevelopers offset=0 and offset=5 with limit=5 return
    DISJOINT sets (no overlap → offset works)."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            page1 = await admin.call("getAdminDevelopers", {"limit": 5, "offset": 0})
            page2 = await admin.call("getAdminDevelopers", {"limit": 5, "offset": 5})

            def _ids(r):
                items = r if isinstance(r, list) else (
                    r.get("developers") or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                return [it.get("id") for it in items if isinstance(it, dict)]

            ids1 = _ids(page1)
            ids2 = _ids(page2)
            state["page1_ids"] = ids1
            state["page2_ids"] = ids2
            overlap = set(ids1) & set(ids2)
            state["overlap"] = list(overlap)
            return len(ids1) == 5 and len(ids2) == 5 and not overlap
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="offset=0 and offset=5 windows are disjoint (no overlap)",
        capture_state=lambda: state,
    )


@federation_test(
    name="pagination_total_matches_count",
    category="pagination_contract",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["pagination", "total"],
)
async def test_total_field(rig: FederationTestRig) -> AssertionResult:
    """getAdminDevelopers returns `total` field with int value matching
    actual row count. Probes with limit=1 → total stays consistent."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r1 = await admin.call("getAdminDevelopers", {"limit": 1})
            r2 = await admin.call("getAdminDevelopers", {"limit": 10})
            if not isinstance(r1, dict) or not isinstance(r2, dict):
                state["bad_shape"] = True
                return False
            t1 = r1.get("total")
            t2 = r2.get("total")
            state["total_limit_1"] = t1
            state["total_limit_10"] = t2
            # Total is total of underlying table; should NOT change between
            # consecutive requests with different limits (no inserts mid-test)
            return isinstance(t1, int) and isinstance(t2, int) and t1 == t2
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="total field stable across different limit values",
        capture_state=lambda: state,
    )
