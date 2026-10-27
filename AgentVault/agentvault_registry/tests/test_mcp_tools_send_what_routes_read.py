"""§MCPTEST30 (2026-10-01) — a tool sends the parameters its route reads, and does itself what the route cannot.

FastAPI drops a query parameter its route does not declare and answers 200, so a tool that names a filter, a page or a
size the route never reads hands back the unfiltered first page and calls it the answer (the request survey's
UNDECLARED class, gated in tests/test_mcp_tool_requests_meet_their_routes.py: 15 tools on 2026-10-01). Where the route
has the capability under another name the tool now uses that name; where it has none, the tool applies it to what the
route served, and says the window it had; the audit-log route gained the two filters its tool always sent.
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.mcp import tools_admin, tools_developer, tools_discovery


class _Auth:
    raw_token = "t"
    developer_id = 1
    is_admin = True
    auth_type = "developer"


@pytest.fixture
def seen(monkeypatch):
    calls = []

    def answer(path):
        if path.endswith("/arena/matches"):
            return {"matches": [{"match_id": "a", "started": True, "finished": False},
                                {"match_id": "b", "started": True, "finished": True},
                                {"match_id": "c", "started": False, "finished": False}]}
        if path.endswith("/eventstore-recent"):
            return [{"n": i} for i in range(15)]
        if path.endswith("/disputes/settlements"):
            return {"count": 7, "stats": {}, "settlements": [{"id": f"s{i}"} for i in range(7)]}
        return {"ok": True}

    async def pub(path, params=None, **kw):
        calls.append((path, dict(params or {})))
        return answer(path)

    async def adm(auth, path, params=None, **kw):
        calls.append((path, dict(params or {})))
        return answer(path)

    async def dev(auth, method, path, params=None, **kw):
        calls.append((path, dict(params or {})))
        return answer(path)
    monkeypatch.setattr(tools_discovery, "_public_get", pub)
    monkeypatch.setattr(tools_admin, "_admin_get", adm)
    monkeypatch.setattr(tools_developer, "_dev_request", dev)
    return calls


def _run(coro):
    return asyncio.run(coro)


def test_renamed_parameters_reach_the_names_the_routes_read(seen):
    _run(tools_discovery.list_agent_cards(limit=3, offset=3))
    _run(tools_admin.get_cloud_operator_logs(_Auth(), application_id="app", lines=50))
    _run(tools_admin.get_cloud_operator_self_logs(_Auth(), lines=20))
    _run(tools_developer.operator_portal_self_logs(_Auth(), lines=30))
    _run(tools_admin.get_admin_simulation_logs(_Auth(), limit=60))
    _run(tools_admin.get_recent_webhook_deliveries(_Auth(), status="failure"))
    _run(tools_developer.get_my_mcp_audit_log(_Auth(), limit=5, cursor="row-9"))
    _run(tools_admin.get_admin_mcp_audit_log_by_actor(_Auth(), actor_id="7", cursor="row-3"))
    _run(tools_discovery.list_federation_agent_cards(limit=10, since="2026-10-01T00:00:00Z"))
    params = [p for _, p in seen]
    assert params[0] == {"limit": 3, "skip": 3}
    assert params[1] == {"tail": 50} and params[2] == {"tail": 20} and params[3] == {"tail": 30}
    assert params[4] == {"tail": 60} and params[5] == {"limit": 100, "status_filter": "failure"}
    assert params[6] == {"limit": 5, "cursor": "row-9"} and params[7] == {"actor_id": "7", "limit": 50, "cursor": "row-3"}
    assert params[8] == {"limit": 10, "since": "2026-10-01T00:00:00Z"}
    assert not any(k in p for p in params for k in ("offset", "lines", "status", "query")), params


def test_what_a_route_cannot_do_the_tool_does_on_what_it_served(seen):
    out = _run(tools_discovery.list_arena_matches(limit=5, status="active"))
    assert [m["match_id"] for m in out["matches"]] == ["a"] and seen[-1][1] == {}
    assert [m["match_id"] for m in _run(tools_discovery.list_arena_matches(status="waiting"))["matches"]] == ["c"]
    assert _run(tools_discovery.list_arena_matches(limit=1))["matches"] == [{"match_id": "a", "started": True,
                                                                              "finished": False}]
    assert "status must be one of" in _run(tools_discovery.list_arena_matches(status="paused"))["error"]
    out = _run(tools_admin.get_eventstore_recent(_Auth(), limit=50))
    assert out["total"] == 15 and out["cache_window"] == 15 and seen[-1][1] == {}
    assert _run(tools_admin.get_eventstore_recent(_Auth(), limit=4))["total"] == 4
    out = _run(tools_developer.get_federation_dispute_settlements(_Auth(), limit=3, offset=3))
    assert [s["id"] for s in out["settlements"]] == ["s3", "s4", "s5"] and out["total"] == 7
    assert out["served_window"] == 100 and seen[-1][1] == {}


def test_the_event_search_has_no_free_text_query():
    import inspect
    assert "query" not in inspect.signature(tools_admin.search_admin_events).parameters
    schema = next(s for s in tools_admin.ADMIN_TOOL_SCHEMAS if s["name"] == "theprotocol_searchAdminEvents")
    assert "query" not in schema["inputSchema"]["properties"]


class _Rows:
    def __iter__(self):
        return iter([])


class _AuditDB:
    def __init__(self):
        self.sql, self.params = None, None

    async def execute(self, stmt, params=None):
        self.sql, self.params = str(stmt), params
        return _Rows()


def test_the_audit_log_route_reads_the_filters_its_tool_sends_and_orders_uniquely():
    from agentvault_registry.routers import admin_cicd as R
    db = _AuditDB()
    out = _run(R.list_audit_logs(action=None, event_type="AUTHENTICATION_FAILURE", actor_type="agent", actor_id=None,
                                 target_id=None, severity=None, since_hours=24, limit=10, offset=0, db=db,
                                 current_admin=None))
    assert out["count"] == 0
    assert "event_type::text = :event_type" in db.sql and db.params["event_type"] == "AUTHENTICATION_FAILURE"
    assert "actor_type = :actor_type" in db.sql and db.params["actor_type"] == "agent"
    assert "ORDER BY timestamp DESC, id DESC" in db.sql, "a page under LIMIT/OFFSET needs a unique order"


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
