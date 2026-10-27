"""§MCPTEST30 (V0555): the console suite's history (routers/console_suite.py), its own index and cap apart from the MCP
tester's. Records go through the real routes on a FastAPI app with an in-memory Redis; the controls are what a record
must not become: another flow's run, an unbounded field, a second copy, a run past the cap."""
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.routers import console_suite as cs


class _FakeRedis:
    def __init__(self):
        self.kv, self.z = {}, {}

    async def exists(self, k):
        return 1 if k in self.kv else 0

    async def set(self, k, v, ex=None):
        self.kv[k] = v.encode() if isinstance(v, str) else v

    async def get(self, k):
        return self.kv.get(k)

    async def delete(self, *ks):
        for k in ks:
            self.kv.pop(k, None)

    async def zadd(self, k, mapping):
        self.z.setdefault(k, {}).update(mapping)

    async def zcard(self, k):
        return len(self.z.get(k, {}))

    def _sorted(self, k):
        return [m for m, _ in sorted(self.z.get(k, {}).items(), key=lambda kv: kv[1])]

    async def zrange(self, k, a, b):
        return [m.encode() for m in self._sorted(k)[a:b + 1]]

    async def zrevrange(self, k, a, b):
        return [m.encode() for m in list(reversed(self._sorted(k)))[a:b + 1]]

    async def zrem(self, k, *ms):
        for m in ms:
            self.z.get(k, {}).pop(m, None)


def _run(rid="fes-20261003T010203Z-abcd", started="2026-10-03T01:02:03.000Z", **over):
    run = {
        "run_id": rid, "flow_name": cs.FLOW_NAME, "flow_label": "Console lifecycles (Playwright)",
        "status": "completed", "started_at": started, "finished_at": "2026-10-03T01:12:03.000Z",
        "summary": {"tool_count": 3, "passed": 1, "failed": 1, "skipped": 1, "lifecycles": 2, "lifecycles_passed": 1,
                    "target": "Sandbox Alpha", "nested": {"dropped": True}},
        "scope": {"target": "sbx-alpha", "grep": "mcp_tester", "project": "all", "full": False, "by": "agentvault2-09"},
        "lifecycles": [
            {"lifecycle": "console_smoke", "project": "desktop", "status": "passed", "duration_s": 1.9, "steps": 3,
             "capture": {"requests": 20, "console_errors": 0, "unexpected": [], "warnings": ["w"]}, "a11y": None},
            {"lifecycle": "mcp_tester_page_reads_a_run", "project": "desktop", "status": "failed", "duration_s": 40.0,
             "steps": 8, "capture": {"requests": 90, "console_errors": 1, "unexpected": ["GET /x answered 500"]}},
        ],
        "results": [
            {"tool": "ui:console_smoke.login-page-renders", "tier": "ui:public", "healthy": True, "skipped": False,
             "status": "ok", "elapsed": 0.4, "error": None, "skip_reason": None, "response_excerpt": "title", "kind": None},
            {"tool": "ui:mcp_tester_page_reads_a_run.tiles-match-the-run", "tier": "ui:admin", "healthy": False,
             "skipped": False, "status": "bug", "elapsed": 2.0, "error": "x" * 5000, "kind": "bug"},
            {"tool": "ui:route_sweep_admin.page/galactic-command", "skipped": True, "skip_reason": "not opened headless"},
            "not a row",
        ],
        "hard_fails": [{"tool": "ui:mcp_tester_page_reads_a_run.tiles-match-the-run", "error": "Expected 35"}],
        "bug_finds": ["ui:old.reporter: tool and text in one string"],
        "skipped": [{"tool": "ui:route_sweep_admin.page/galactic-command", "reason": "not opened headless"}],
        "log_lines": [{"ts": "2026-10-03T01:02:04Z", "msg": "run begins"}],
        "unknown_key": "dropped",
    }
    run.update(over)
    return run


@pytest.fixture()
def client(monkeypatch):
    fake = _FakeRedis()

    async def _get_redis():
        return fake
    monkeypatch.setattr(cs, "get_redis", _get_redis)
    app = FastAPI()
    app.include_router(cs.router, prefix="/api/v1")
    holder = {"dev": SimpleNamespace(id=1, is_admin=True)}
    app.dependency_overrides[security.get_current_developer] = lambda: holder["dev"]
    return TestClient(app, raise_server_exceptions=False), fake, holder


def test_a_run_is_recorded_listed_and_read_back_whole(client):
    c, fake, _ = client
    r = c.post("/api/v1/admin/console-suite/runs", json=_run())
    assert r.status_code == 200 and r.json()["status"] == "recorded", r.text
    lst = c.get("/api/v1/admin/console-suite/runs").json()
    assert lst["total"] == 1 and lst["cap"] == cs._MAX_HISTORY
    meta = lst["runs"][0]
    assert meta["run_id"] == "fes-20261003T010203Z-abcd" and "results" not in meta
    assert meta["lifecycle_names"] == ["console_smoke", "mcp_tester_page_reads_a_run"] and meta["projects"] == ["desktop"]
    assert isinstance(meta["started_at"], float)            # ISO text from the runner, Unix seconds here
    run = c.get("/api/v1/admin/console-suite/runs/fes-20261003T010203Z-abcd").json()
    assert [x["tool"] for x in run["results"]] == [
        "ui:console_smoke.login-page-renders", "ui:mcp_tester_page_reads_a_run.tiles-match-the-run",
        "ui:route_sweep_admin.page/galactic-command"]           # the non-row was dropped
    assert len(run["results"][1]["error"]) == 1500               # cut, not refused
    assert run["lifecycles"][1]["capture"] == {"requests": 90, "console_errors": 1, "unexpected": ["GET /x answered 500"]}
    assert "nested" not in run["summary"] and "unknown_key" not in run
    assert run["bug_finds"] == [{"tool": "ui:old.reporter", "error": "tool and text in one string", "reason": None}]
    assert run["scope"]["by"] == "agentvault2-09" and run["scope"]["full"] is False


def test_the_same_run_twice_is_kept_once_unless_replaced(client):
    c, fake, _ = client
    assert c.post("/api/v1/admin/console-suite/runs", json=_run()).json()["status"] == "recorded"
    again = c.post("/api/v1/admin/console-suite/runs", json=_run(status="failed"))
    assert again.status_code == 200 and again.json()["status"] == "exists"
    assert c.get("/api/v1/admin/console-suite/runs/fes-20261003T010203Z-abcd").json()["status"] == "completed"
    rep = c.post("/api/v1/admin/console-suite/runs?replace=true", json=_run(status="failed"))
    assert rep.json()["status"] == "replaced"
    assert c.get("/api/v1/admin/console-suite/runs/fes-20261003T010203Z-abcd").json()["status"] == "failed"
    assert c.get("/api/v1/admin/console-suite/runs").json()["total"] == 1


def test_another_flow_or_a_bad_id_is_refused_and_nothing_is_written(client):
    c, fake, _ = client
    for body, word in ((_run(flow_name="flow_mcp_lifecycle_complete"), "flow_name"),
                       (_run(rid="x"), "run_id"), (_run(rid="../../etc"), "run_id"), (_run(started=None), "started_at")):
        r = c.post("/api/v1/admin/console-suite/runs", json=body)
        assert r.status_code == 422 and word in r.json()["detail"], r.text
    assert c.post("/api/v1/admin/console-suite/runs", content=b"[1, 2]").status_code == 422
    assert c.post("/api/v1/admin/console-suite/runs", content=b"not json").status_code == 422
    assert fake.kv == {} and fake.z == {}


def test_the_cap_drops_the_oldest_run_and_its_keys(client, monkeypatch):
    c, fake, _ = client
    monkeypatch.setattr(cs, "_MAX_HISTORY", 2)
    for i, ts in enumerate(("2026-10-03T01:00:00Z", "2026-10-03T03:00:00Z", "2026-10-03T02:00:00Z")):
        assert c.post("/api/v1/admin/console-suite/runs", json=_run(rid=f"fes-run-{i}", started=ts)).status_code == 200
    ids = [m["run_id"] for m in c.get("/api/v1/admin/console-suite/runs").json()["runs"]]
    assert ids == ["fes-run-1", "fes-run-2"]                     # newest first; the 01:00Z run went
    assert c.get("/api/v1/admin/console-suite/runs/fes-run-0").status_code == 404
    assert not [k for k in fake.kv if "fes-run-0" in k]


def test_the_newest_whole_suite_runs_outlive_a_morning_of_small_runs(client, monkeypatch):
    """V0558: EU held 120 of 120 runs and no whole-suite run on 2026-10-03; small runs no longer push whole ones out."""
    c, fake, _ = client
    monkeypatch.setattr(cs, "_MAX_HISTORY", 3)
    monkeypatch.setattr(cs, "_KEEP_WHOLE", 1)
    whole = dict(scope={"target": "sbx-alpha", "grep": None, "project": "all", "full": True})
    assert c.post("/api/v1/admin/console-suite/runs", json=_run(rid="fes-whole-0", started="2026-10-03T00:00:00Z", **whole)).status_code == 200
    for i in range(5):
        assert c.post("/api/v1/admin/console-suite/runs", json=_run(rid=f"fes-part-{i}", started=f"2026-10-03T0{i + 1}:00:00Z")).status_code == 200
    ids = {m["run_id"] for m in c.get("/api/v1/admin/console-suite/runs").json()["runs"]}
    assert ids == {"fes-whole-0", "fes-part-3", "fes-part-4"}        # the oldest run stayed: it is the newest whole one
    # the control: a newer whole run takes the protection over, and the older whole run is dropped like any other
    assert c.post("/api/v1/admin/console-suite/runs", json=_run(rid="fes-whole-1", started="2026-10-03T07:00:00Z", **whole)).status_code == 200
    assert c.post("/api/v1/admin/console-suite/runs", json=_run(rid="fes-part-9", started="2026-10-03T08:00:00Z")).status_code == 200
    ids = {m["run_id"] for m in c.get("/api/v1/admin/console-suite/runs").json()["runs"]}
    assert ids == {"fes-whole-1", "fes-part-4", "fes-part-9"} and not [k for k in fake.kv if "fes-whole-0" in k]


def test_a_run_the_cache_let_go_leaves_the_index_too(client):
    c, fake, _ = client
    c.post("/api/v1/admin/console-suite/runs", json=_run())
    fake.kv.pop("console_suite:meta:fes-20261003T010203Z-abcd")
    lst = c.get("/api/v1/admin/console-suite/runs").json()
    assert lst["runs"] == [] and lst["total"] == 0


def test_only_an_admin_reads_or_records(client):
    c, fake, holder = client
    holder["dev"] = SimpleNamespace(id=2, is_admin=False)
    assert c.post("/api/v1/admin/console-suite/runs", json=_run()).status_code == 403
    assert c.get("/api/v1/admin/console-suite/runs").status_code == 403
    assert c.get("/api/v1/admin/console-suite/runs/fes-20261003T010203Z-abcd").status_code == 403
    assert fake.kv == {}


def test_an_oversized_body_is_refused_before_it_is_parsed(client, monkeypatch):
    c, fake, _ = client
    monkeypatch.setattr(cs, "_MAX_BODY_BYTES", 1000)
    r = c.post("/api/v1/admin/console-suite/runs", content=json.dumps(_run()).encode())
    assert r.status_code == 413 and fake.kv == {}


def test_the_app_mounts_the_history():
    from agentvault_registry import main as m
    try:
        from fastapi.routing import iter_route_contexts       # FastAPI keeps an included router as one lazy entry
        routes = [rc._effective_route for rc in iter_route_contexts(m.app.routes)]
    except ImportError:
        routes = list(m.app.routes)
    paths = {getattr(rt, "path", "") for rt in routes}
    assert "/api/v1/admin/console-suite/runs" in paths and "/api/v1/admin/console-suite/runs/{run_id}" in paths
