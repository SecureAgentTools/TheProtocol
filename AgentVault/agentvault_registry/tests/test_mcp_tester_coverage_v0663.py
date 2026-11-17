"""V0663 (order gwo_0b31c0b849ebd207102d8bf4, his suggestion 7, his yes at room seq 3068): the MCP tester's coverage.

Per tool, per target, from the latest completed run the tester holds for that target: whether the tool has
  failed        a row of the tool failed (said first; a failure is never folded into coverage)
  success       a passing 2xx anywhere in the run: its own row, an `admin_effect:` or `earned:` row, a probe family
  refusal_only  it passed on a refusal alone (the router's own rule, `mcp_tester._refusal_only`, and the flag a run since
                V0636 stores on the row), with the row's reason (the declared by-design reason, else the generic one)
  not_measured  nothing of it passed (skipped, switched off), with the reason the row gives
A target is one suite against one target (`mcp_tester._suite_key`); the federation suite has no tool rows and is not
one. Counts are per target and never summed (sessionlogs2026/CLASSIFICATION_2026-11-13_MCP_REFUSAL_ONLY.md: the same
tool is refusal-only on one target and earned on another). A tool a target does not list is `not_listed` there and
counted nowhere. A newer run still in flight (or failed) for a target is named beside the one read.
GET /api/v1/admin/mcp-tester/coverage, behind the tester's admin rule (`_require_admin`).
Red on b27f2ebaf: the module and the route do not exist.
"""
from __future__ import annotations

import asyncio
import types

import httpx
import pytest

try:     # red as one failure per test, not a collection error that stops the suite
    from agentvault_registry.routers import mcp_tester_coverage as cov
except ImportError:
    cov = None


def row(tool, status=200, *, healthy=True, skipped=False, skip_reason=None, refusal_only=False, declared=None,
        switched_off=None, error=None, tier="developer"):
    return {"tool": tool, "tier": tier, "status": status, "healthy": healthy, "skipped": skipped,
            "skip_reason": skip_reason, "refusal_only": refusal_only, "declared_unmeasured": declared,
            "switched_off": switched_off, "error": error}


RUN_ROWS = [
    row("theprotocol_getA"),                                                         # success, its own row
    row("theprotocol_getB", 404, skipped=True, refusal_only=True, declared="an operator's own tool",
        skip_reason="refusal only, by design: an operator's own tool; the refusal is measured, the success path is not"),
    row("theprotocol_setC", 404),                                                    # refusal, then earned below
    row("admin_effect: setC rotates the key", 200),
    row("theprotocol_listD", 0, skipped=True, skip_reason="NOT MEASURED: a federation peer reads it"),
    row("theprotocol_putE", 200),
    row("hygiene: putE leaks a stack trace", 500, healthy=False, error="a traceback in the body"),
    row("theprotocol_oldF", 404),                                                    # a run before V0636: no flag
    row("theprotocol_flagG", 409, switched_off="FEATURE_G_ENABLED"),
    row("hygiene: getA bounds", 200),                                                # not a tool of its own
]


def test_the_module_exists():
    from agentvault_registry.routers import mcp_tester_coverage as m
    assert callable(m.classify_run) and callable(m.pick_runs) and callable(m.coverage_view) and m.router is not None


def test_each_tool_gets_one_class_and_its_reason():
    out = cov.classify_run(RUN_ROWS)
    assert set(out) == {"getA", "getB", "setC", "listD", "putE", "oldF", "flagG"}
    assert out["getA"]["class"] == "success"
    assert out["getB"]["class"] == "refusal_only" and "an operator's own tool" in out["getB"]["reason"]
    assert out["setC"]["class"] == "success", "a refusal beside an earned 2xx is a success path"
    assert out["listD"]["class"] == "not_measured" and out["listD"]["reason"].startswith("NOT MEASURED: a federation peer")
    assert out["putE"]["class"] == "failed" and "traceback" in out["putE"]["reason"], "a failure is said, never folded"
    assert out["oldF"]["class"] == "refusal_only" and out["oldF"]["reason"].startswith("refusal only:")
    assert out["flagG"]["class"] == "not_measured" and "FEATURE_G_ENABLED" in out["flagG"]["reason"]
    assert out["getB"]["status"] == 404 and out["getA"]["tier"] == "developer"


def test_the_refusal_only_rule_is_the_routers_own():
    import pathlib
    src = (pathlib.Path(cov.__file__)).read_text()
    assert "def _refusal_only" not in src and "def _tool_base" not in src
    assert "_refusal_only" in src and "_tool_base" in src and "refusal_only_reason" in src


def meta(run_id, flow, target, status="completed", started=0.0):
    return {"run_id": run_id, "flow_name": flow, "flow_label": "", "status": status, "started_at": started,
            "finished_at": started + 60, "summary": {"target": target, "pass_pct": 90.0, "refusal_only": 1}}


ALPHA, BETA = "http://sbx-alpha-registry:8000", "http://sbx-beta-registry:8000"
MAIN, OPS, FED = "flow_mcp_lifecycle_complete", "flow_mcp_lifecycle_cloudop_sandboxalpha_complete", "flow_federation_suite_complete"


def test_the_latest_completed_run_per_target_and_a_newer_one_in_flight_is_named():
    metas = [   # newest first, as the index answers
        meta("r9", MAIN, ALPHA, status="running", started=900),
        meta("r8", FED, ALPHA, started=800),
        meta("r7", MAIN, ALPHA, started=700),
        meta("r6", OPS, ALPHA, started=600),
        meta("r5", MAIN, ALPHA, started=500),
        meta("r4", MAIN, BETA, started=400),
    ]
    picked = cov.pick_runs(metas)
    by = {p["key"]: p for p in picked}
    assert set(by) == {f"{MAIN}@sbx-alpha-registry:8000", f"{OPS}@sbx-alpha-registry:8000", f"{MAIN}@sbx-beta-registry:8000"}
    assert by[f"{MAIN}@sbx-alpha-registry:8000"]["run_id"] == "r7"
    assert by[f"{MAIN}@sbx-alpha-registry:8000"]["newer"] == {"run_id": "r9", "status": "running", "started_at": 900}
    assert by[f"{MAIN}@sbx-beta-registry:8000"]["newer"] is None
    assert [p["key"] for p in picked][0] == f"{MAIN}@sbx-alpha-registry:8000", "the main sweep first"


def test_counts_per_target_never_summed_and_a_tool_a_target_does_not_list():
    a = {"run_id": "r7", "key": "main@alpha", "label": "alpha"}
    b = {"run_id": "r6", "key": "ops@alpha", "label": "ops"}
    view = cov.coverage_view([(a, RUN_ROWS), (b, [row("theprotocol_getA"), row("theprotocol_onlyOps", 403, skipped=True,
                                                     refusal_only=True, skip_reason="refusal only: x")])])
    ta, tb = view["targets"]
    assert ta["counts"] == {"tools": 7, "failed": 1, "success": 2, "refusal_only": 2, "not_measured": 2}
    assert tb["counts"] == {"tools": 2, "failed": 0, "success": 1, "refusal_only": 1, "not_measured": 0}
    assert not any(k in view for k in ("counts", "total", "totals")), "never summed across targets"
    tools = {t["tool"]: t for t in view["tools"]}
    assert tools["onlyOps"]["by_target"]["main@alpha"]["class"] == "not_listed"
    assert tools["listD"]["by_target"]["ops@alpha"]["class"] == "not_listed"
    order = [t["tool"] for t in view["tools"]]
    assert order[0] == "putE", "the worst first: a failure, then refusal only, then not measured, then success"
    assert order.index("getB") < order.index("listD") < order.index("getA")


# --- the route -----------------------------------------------------------------------------------------------------

def _app(monkeypatch, metas, rows_by_run, *, admin=True):
    from fastapi import FastAPI
    from agentvault_registry import security
    from agentvault_registry.routers import mcp_tester

    async def load_metas(limit=60):
        return metas

    async def load_rows(run_id):
        return rows_by_run.get(run_id, [])
    monkeypatch.setattr(cov, "_load_metas", load_metas)
    monkeypatch.setattr(cov, "_load_rows", load_rows)
    if admin:
        monkeypatch.setattr(security, "admin_credential", lambda d: True)
    app = FastAPI()
    app.include_router(cov.router, prefix="/api/v1")
    app.dependency_overrides[security.get_current_developer] = lambda: types.SimpleNamespace(id=7, is_admin=admin)
    return app


def _get(app):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://reg.test") as c:
            return await c.get("/api/v1/admin/mcp-tester/coverage")
    return asyncio.run(go())


def test_the_route_answers_per_target(monkeypatch):
    r = _get(_app(monkeypatch, [meta("r7", MAIN, ALPHA, started=700)], {"r7": RUN_ROWS}))
    assert r.status_code == 200
    body = r.json()
    assert [t["run_id"] for t in body["targets"]] == ["r7"]
    assert body["targets"][0]["counts"]["refusal_only"] == 2 and body["targets"][0]["target"] == "sbx-alpha-registry:8000"
    assert {t["tool"] for t in body["tools"]} >= {"getA", "putE"}


def test_a_tester_with_no_run_says_so(monkeypatch):
    body = _get(_app(monkeypatch, [], {})).json()
    assert body["targets"] == [] and body["tools"] == [] and body["note"]


def test_the_route_is_behind_the_testers_admin_rule(monkeypatch):
    r = _get(_app(monkeypatch, [meta("r7", MAIN, ALPHA)], {"r7": RUN_ROWS}, admin=False))
    assert r.status_code == 403
    import pathlib
    src = pathlib.Path(cov.__file__).read_text()
    assert "_require_admin(current_developer)" in src and "Security(security.get_current_developer)" in src
