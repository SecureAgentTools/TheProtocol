"""V0664 consoles (C2, gwo_ebaafc5c4af1fa3a6858e55d): a proxy's status, opt-in, and its owner reads it.

  POST /api/v1/agents/me/proxy-status   agent tier: the proxy posts {name, sdk_version, uptime_s, mappings, sources} as its own agent;
                                        one row per agent, overwritten; the body is capped at 16 KiB and refused above (413); names and
                                        counts only: a field the contract does not name is refused (422), so a proxy cannot put text,
                                        a record or an error message in the row; NO event per report
  GET  /api/v1/agents/{did}/proxy-status  the agent's OWNER only (the developer who created it): the last report and when it came;
                                        anyone else, and an agent that does not exist, get the same 404
  GET  /api/v1/developers/me/proxy-status  the developer's agents that have reported, newest first (C3's "My proxies"), at most 200
  migration 0229_proxy_status           one additive table, rolling back drops it; the route is in the generated auth-tier map
Red on v0664/cut 64ab5a54e: the routes, the service and the table do not exist.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import pathlib
import types

import httpx
import pytest
from sqlalchemy import create_engine, text

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
ALEMBIC = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
PATH = "/api/v1/agents/me/proxy-status"
DID_A, DID_B = "did:theprotocol:agent-a", "did:theprotocol:agent-b"

REPORT = {"name": "gate-out", "sdk_version": "0.9.0", "uptime_s": 3600,
          "mappings": {"gate-out": {"pending": 2, "done": 40, "dead": 1, "paused": False, "breaker": None},
                       "gate-in": {"pending": 0, "done": 7, "dead": 0, "paused": True, "breaker": "stopped"}},
          "sources": {"gates": {"finished": False, "last_read_at": "2026-11-14T10:00:00Z"},
                      "idle": {"finished": True, "last_read_at": None}}}

from agentvault_registry.services import proxy_status as ps         # red on the base: the module does not exist

DDL = (
    "CREATE TABLE agents (did TEXT PRIMARY KEY, creator_developer_id INTEGER)",
    "CREATE TABLE agent_proxy_status (agent_did TEXT PRIMARY KEY, reported_at TIMESTAMP NOT NULL, report TEXT NOT NULL)",
)


class SqliteDb:
    """The calls the store makes on its session (execute, commit), on a synchronous SQLite connection."""

    def __init__(self) -> None:
        self.conn = create_engine("sqlite://").connect()
        for stmt in DDL:
            self.conn.execute(text(stmt))
        self.conn.execute(text("INSERT INTO agents VALUES ('%s', 1), ('%s', 2)" % (DID_A, DID_B)))
        self.conn.commit()

    async def execute(self, stmt, params=None):
        return self.conn.execute(stmt, params or {})

    async def commit(self):
        self.conn.commit()


def _app(store, agent=None, developer=None):
    from fastapi import FastAPI
    from agentvault_registry import database, security
    from agentvault_registry.routers import proxy_status as route
    app = FastAPI()
    app.include_router(route.router)

    async def get_db():
        yield None
    app.dependency_overrides[database.get_db] = get_db
    if agent is not None:
        app.dependency_overrides[security.get_current_agent] = lambda: agent
    if developer is not None:
        app.dependency_overrides[security.get_current_developer] = lambda: developer
    route.store_for = lambda db: store                      # noqa: E731
    return app


def _call(app, method, path, body=None, raw=None):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://reg.test") as c:
            if raw is not None:
                return await c.request(method, path, content=raw, headers={"content-type": "application/json"})
            return await c.request(method, path, json=body)
    return asyncio.run(go())


def _agent(did=DID_A, dev=1):
    return types.SimpleNamespace(did=did, creator_developer_id=dev)


def _dev(i):
    return types.SimpleNamespace(id=i)


@pytest.fixture
def store():
    return ps.DbStore(SqliteDb())


# ── the report's shape ──────────────────────────────────────────────────────────────────────────────────────────

def test_the_documented_report_is_accepted_and_kept_as_it_came():
    assert ps.check(REPORT) == REPORT


@pytest.mark.parametrize("bad,why", [
    ({**REPORT, "extra": 1}, "extra"),
    ({k: v for k, v in REPORT.items() if k != "name"}, "name"),
    ({**REPORT, "uptime_s": "3600"}, "uptime_s"),
    ({**REPORT, "uptime_s": -1}, "uptime_s"),
    ({**REPORT, "sdk_version": "x" * 41}, "sdk_version"),
    ({**REPORT, "mappings": {"m": {"pending": 1, "done": 1, "dead": 0, "paused": False, "breaker": None, "why": "text"}}}, "why"),
    ({**REPORT, "mappings": {"m": {"pending": 1, "done": 1, "dead": 0, "paused": False}}}, "breaker"),
    ({**REPORT, "mappings": {"m": {"pending": "1", "done": 1, "dead": 0, "paused": False, "breaker": None}}}, "pending"),
    ({**REPORT, "mappings": {"m": {"pending": True, "done": 1, "dead": 0, "paused": False, "breaker": None}}}, "pending"),
    ({**REPORT, "mappings": {"m": {"pending": 1, "done": 1, "dead": 0, "paused": 0, "breaker": None}}}, "paused"),
    ({**REPORT, "mappings": {"m": {"pending": 1, "done": 1, "dead": 0, "paused": False, "breaker": "a long sentence about what went wrong"}}}, "breaker"),
    ({**REPORT, "mappings": {"": {"pending": 1, "done": 1, "dead": 0, "paused": False, "breaker": None}}}, "name"),
    ({**REPORT, "mappings": {"x" * 121: {"pending": 1, "done": 1, "dead": 0, "paused": False, "breaker": None}}}, "name"),
    ({**REPORT, "mappings": {"bad\nname": {"pending": 1, "done": 1, "dead": 0, "paused": False, "breaker": None}}}, "name"),
    ({**REPORT, "sources": {"s": {"finished": "yes", "last_read_at": None}}}, "finished"),
    ({**REPORT, "sources": {"s": {"finished": True, "last_read_at": "yesterday"}}}, "last_read_at"),
    ({**REPORT, "sources": {"s": {"finished": True, "last_read_at": "2026-11-14T10:00:00Z", "n": 1}}}, "n"),
    ({**REPORT, "mappings": {f"m{i}": REPORT["mappings"]["gate-out"] for i in range(201)}}, "mappings"),
    ({**REPORT, "mappings": []}, "mappings"),
    ([], "report"),
])
def test_a_report_that_is_not_names_and_counts_is_refused_naming_the_field(bad, why):
    with pytest.raises(ps.Refusal) as e:
        ps.check(bad)
    assert why in e.value.detail and e.value.status == 422


def test_a_refusal_never_repeats_what_it_was_given():
    secret = "SECRET-TEXT-12345"
    with pytest.raises(ps.Refusal) as e:
        ps.check({**REPORT, "mappings": {"m": {"pending": 1, "done": 1, "dead": 0, "paused": False, "breaker": secret}}})
    assert secret not in e.value.detail


# ── the routes ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_agent_posts_its_report_and_its_owner_reads_it(store):
    r = _call(_app(store, agent=_agent()), "POST", PATH, REPORT)
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["reported_at"]
    r = _call(_app(store, developer=_dev(1)), "GET", f"/api/v1/agents/{DID_A}/proxy-status")
    assert r.status_code == 200
    body = r.json()
    assert body["agent_did"] == DID_A and body["report"] == REPORT and body["reported_at"]
    assert 0 <= body["age_s"] < 60


def test_one_row_per_agent_overwritten(store):
    app = _app(store, agent=_agent())
    _call(app, "POST", PATH, REPORT)
    newer = {**REPORT, "uptime_s": 7200}
    _call(app, "POST", PATH, newer)
    assert store.db.conn.execute(text("SELECT count(*) FROM agent_proxy_status")).scalar() == 1
    r = _call(_app(store, developer=_dev(1)), "GET", f"/api/v1/agents/{DID_A}/proxy-status")
    assert r.json()["report"]["uptime_s"] == 7200


def test_a_stranger_gets_a_404_exactly_like_an_agent_that_does_not_exist(store):
    _call(_app(store, agent=_agent()), "POST", PATH, REPORT)
    stranger = _call(_app(store, developer=_dev(2)), "GET", f"/api/v1/agents/{DID_A}/proxy-status")
    nobody = _call(_app(store, developer=_dev(2)), "GET", "/api/v1/agents/did:theprotocol:no-such/proxy-status")
    assert stranger.status_code == nobody.status_code == 404
    assert stranger.json() == nobody.json()
    assert "uptime" not in stranger.text and "gate-out" not in stranger.text


def test_the_owner_of_an_agent_that_never_reported_is_told_so(store):
    r = _call(_app(store, developer=_dev(1)), "GET", f"/api/v1/agents/{DID_A}/proxy-status")
    assert r.status_code == 404 and r.json()["code"] == "no_report"


def test_a_report_above_16_kib_is_refused_and_one_at_the_cap_is_kept(store):
    app = _app(store, agent=_agent())
    big = json.dumps({**REPORT, "name": "n" * 20000})
    assert len(big.encode()) > 16 * 1024
    r = _call(app, "POST", PATH, raw=big)
    assert r.status_code == 413
    assert store.db.conn.execute(text("SELECT count(*) FROM agent_proxy_status")).scalar() == 0
    many = {f"m{i}": REPORT["mappings"]["gate-out"] for i in range(120)}                  # under the cap, over 200 bytes a mapping
    ok = {**REPORT, "mappings": many}
    assert 8 * 1024 < len(json.dumps(ok).encode()) < 16 * 1024
    assert _call(app, "POST", PATH, ok).status_code == 200


def test_a_bad_body_is_refused_422_and_changes_nothing(store):
    app = _app(store, agent=_agent())
    for body in ({"name": "x"}, {**REPORT, "note": "a value"}):
        r = _call(app, "POST", PATH, body)
        assert r.status_code == 422, body
    assert _call(app, "POST", PATH, raw="not json").status_code == 422
    assert store.db.conn.execute(text("SELECT count(*) FROM agent_proxy_status")).scalar() == 0


def test_no_event_is_emitted_per_report(store, monkeypatch):
    from agentvault_registry import event_emitter

    async def boom(*a, **k):
        raise AssertionError("a status report must not emit an event")
    monkeypatch.setattr(event_emitter, "emit", boom, raising=False)
    assert _call(_app(store, agent=_agent()), "POST", PATH, REPORT).status_code == 200
    assert "event_emitter" not in (SRC / "routers" / "proxy_status.py").read_text()
    assert "event_emitter" not in (SRC / "services" / "proxy_status.py").read_text()


def test_the_owners_list_is_theirs_only_newest_first(store):
    _call(_app(store, agent=_agent(DID_A, 1)), "POST", PATH, REPORT)
    _call(_app(store, agent=_agent(DID_B, 2)), "POST", PATH, {**REPORT, "name": "other"})
    store.db.conn.execute(text("UPDATE agent_proxy_status SET reported_at = :t WHERE agent_did = :d"),
                          {"t": dt.datetime(2026, 11, 1), "d": DID_A})
    store.db.conn.execute(text("INSERT INTO agents VALUES ('did:theprotocol:agent-c', 1)"))
    _call(_app(store, agent=_agent("did:theprotocol:agent-c", 1)), "POST", PATH, {**REPORT, "name": "newer"})
    r = _call(_app(store, developer=_dev(1)), "GET", "/api/v1/developers/me/proxy-status")
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["agent_did"] for i in items] == ["did:theprotocol:agent-c", DID_A]
    assert all(set(i) == {"agent_did", "reported_at", "age_s", "report"} for i in items)
    assert "other" not in r.text
    assert _call(_app(store, developer=_dev(9)), "GET", "/api/v1/developers/me/proxy-status").json()["items"] == []


# ── the wiring ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_routes_are_mounted_and_in_the_generated_auth_tier_map():
    main = (SRC / "main.py").read_text()
    assert "proxy_status as proxy_status_router" in main and "include_router(proxy_status_router.router)" in main
    tiers = json.loads((SRC / "static/new_registry_frontend/src/services/api/authTiers.generated.json").read_text())
    ops = tiers["operations"] if isinstance(tiers, dict) and "operations" in tiers else tiers
    flat = json.dumps(ops)
    assert "/api/v1/agents/me/proxy-status" in flat


def test_the_migration_adds_one_table_and_removes_it():
    mig = (ALEMBIC / "0229_proxy_status.py").read_text()
    assert 'revision = "0229_proxy_status"' in mig and len("0229_proxy_status") <= 32
    assert 'down_revision = "0228_workflow_templates"' in mig
    assert '"agent_proxy_status"' in mig and "agent_did" in mig and "reported_at" in mig and "report" in mig
    assert "drop_table" in mig.split("def downgrade")[1]
