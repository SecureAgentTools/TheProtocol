"""V0663, governed code, first slice (order gwo_58327a76b7e3ecf63140eb79): the routes and the three places beside them.

Routes (routers/code_changes):
  POST /api/v1/code-changes                          a member's agent proposes
  GET  /api/v1/code-changes, /api/v1/code-changes/{id}   public, as the ballot is
  POST /api/v1/code-changes/{id}/reviews             a member developer reviews
  POST /api/v1/code-changes/{id}/ballot              the proposer's agent opens the ballot
  POST /api/v1/admin/code-changes/{id}/{acceptance,ballot,veto,go,merged}   admin_platform
A refusal answers its status with {"code", "detail"}.

Beside them:
  - the Guild verify waits for the merge on a code-change order (services/code_changes.settlement_gate, called in
    routers/guild.verify right after the quantum gate; session-watch, room seq 3409); a plain order is untouched;
  - the order reaper leaves a code change that is still in review or ballot alone (its 7-day dispute);
  - a code_change ballot is never lifted to the federation (D7: one frame's ballot first);
  - migration 0225_code_changes creates the two tables.
Red on 728196e91: no router, no gate, no migration.
"""
from __future__ import annotations

import asyncio
import pathlib
import re

import httpx
import pytest
from fastapi import HTTPException

from agentvault_registry.services import code_changes as cc
from tests.test_code_changes_flow_v0663 import (CHECKER_PUB_B64, CONSOLE, REPO, SHA, FakeStore, _mb,
                                                acceptance_record)

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
ALEMBIC = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"


# --- the routes ------------------------------------------------------------------------------------------------------

class _Agent:
    did, creator_developer_id = "did:a:proposer", 1


class _Dev:
    def __init__(self, i):
        self.id = i


def _app(monkeypatch, store):
    from fastapi import FastAPI
    from agentvault_registry import database
    from agentvault_registry.routers import code_changes as route
    from agentvault_registry.routers.utils import get_current_agent
    from agentvault_registry.security import get_current_developer

    monkeypatch.setattr(cc, "store_for", lambda db, agent=None: store)
    app = FastAPI()
    app.include_router(route.router)

    async def get_db():
        yield None
    app.dependency_overrides[database.get_db] = get_db
    app.dependency_overrides[get_current_agent] = lambda: _Agent()
    app.dependency_overrides[get_current_developer] = lambda: _Dev(7)
    app.dependency_overrides[route._ADMIN] = lambda: _Dev(99)
    return app


def _call(app, method, path, body=None):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://reg.test") as c:
            return await c.request(method, path, json=body)
    return asyncio.run(go())


BODY = {"repository": REPO, "paths": [CONSOLE + "views/GuildBoard.vue"], "title": "A clearer order page",
        "problem": "The order page hides who is paid.", "bounty": 50.0, "currency": "ECU"}


def test_a_member_agent_proposes_and_anyone_reads_the_record(monkeypatch):
    store = FakeStore()
    app = _app(monkeypatch, store)
    r = _call(app, "POST", "/api/v1/code-changes", BODY)
    assert r.status_code == 201 and r.json()["state"] == "proposed" and r.json()["proposer_did"] == "did:a:proposer"
    cid = r.json()["id"]
    assert _call(app, "GET", f"/api/v1/code-changes/{cid}").json()["id"] == cid
    listed = _call(app, "GET", "/api/v1/code-changes").json()
    assert [x["id"] for x in listed["code_changes"]] == [cid]


def test_a_refusal_answers_its_status_code_and_sentence(monkeypatch):
    app = _app(monkeypatch, FakeStore())
    r = _call(app, "POST", "/api/v1/code-changes", {**BODY, "paths": [CONSOLE + ".env"]})
    assert r.status_code == 422 and r.json()["code"] == "path_refused" and "forbidden" in r.json()["detail"]
    assert _call(app, "GET", "/api/v1/code-changes/cc_none").status_code == 404


def test_each_step_reaches_the_flow_as_the_right_actor(monkeypatch):
    store = FakeStore()
    app = _app(monkeypatch, store)
    cid = _call(app, "POST", "/api/v1/code-changes", BODY).json()["id"]
    store.orders["gwo_1"].update(status="submitted", worker_did="did:a:worker",
                                 deliverable={"commits": [{"repo": REPO, "commit": SHA}]})
    # V0663 fixes (F2, F3, F8): the server reads the check from the repository (only the commit is sent), the go is the
    # maintainer's (developer 99 here) and the merge names a release branch that holds the commit
    monkeypatch.setenv("CODE_CHANGES_MAINTAINER", "99")
    monkeypatch.setenv("CODE_CHANGES_RELEASE_BRANCHES", "v0663/cut")
    monkeypatch.setenv("CODE_CHANGES_CHECKER_PUBLIC_KEY", CHECKER_PUB_B64)     # V0664: the host checker's signed records
    store.repo.touched[SHA] = [CONSOLE + "views/GuildBoard.vue"]
    store.repo.contained.add(("v0663/cut", SHA))
    r = _call(app, "POST", f"/api/v1/admin/code-changes/{cid}/acceptance", {"signed": acceptance_record(store, cid, SHA)})
    assert r.status_code == 200 and r.json()["state"] == "accepted"
    r = _call(app, "POST", f"/api/v1/code-changes/{cid}/reviews", {"verdict": "approve", "commit": SHA, "findings": "ok"})
    assert r.status_code == 200 and r.json()["review_verdict"]["ok"] is True
    assert store.revs[0]["reviewer_developer_id"] == 7, "the reviewer is the signed-in developer"
    r = _call(app, "POST", f"/api/v1/code-changes/{cid}/ballot")
    assert r.status_code == 200 and r.json()["state"] == "balloting", "the proposer's agent opens it"
    store.proposals[1].update(status="PASSED", tallied_at=store.clock)
    assert _call(app, "POST", f"/api/v1/admin/code-changes/{cid}/go").json()["go"]["by"] == 99
    r = _call(app, "POST", f"/api/v1/admin/code-changes/{cid}/merged", _mb(store, cid, SHA, "v0663/cut"))
    assert r.status_code == 200 and r.json()["state"] == "merged"


def test_the_admin_routes_need_the_platform_flag():
    src = (SRC / "routers" / "code_changes.py").read_text()
    assert '_ADMIN = require_admin_flag("admin_platform")' in src
    for step in ("acceptance", "ballot", "veto", "go", "merged"):
        # the decorator's line (its summary may hold parentheses), then the function taking Security(_ADMIN)
        assert re.search(rf'@router\.post\("/api/v1/admin/code-changes/{{cid}}/{step}"[^\n]*\n\s*async def \w+\([^)]*Security\(_ADMIN\)',
                         src), step


# --- the Guild verify waits for the merge ----------------------------------------------------------------------------

class _Rows:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class _Db:
    def __init__(self, row):
        self.row, self.sql = row, []

    async def execute(self, stmt, params=None):
        self.sql.append(str(stmt))
        return _Rows(self.row)


@pytest.mark.parametrize("state", ["proposed", "accepted", "balloting", "passed", "failed", "vetoed"])
def test_verify_on_a_code_change_order_waits_for_its_merge(state):
    with pytest.raises(HTTPException) as e:
        asyncio.run(cc.settlement_gate(_Db({"id": "cc_1", "state": state}), "gwo_1"))
    assert e.value.status_code == 409 and "merge" in str(e.value.detail)


def test_a_merged_change_and_a_plain_order_settle_as_before():
    asyncio.run(cc.settlement_gate(_Db({"id": "cc_1", "state": "merged"}), "gwo_1"))
    asyncio.run(cc.settlement_gate(_Db(None), "gwo_2"))


def test_the_verify_route_calls_the_gate_right_after_the_quantum_gate():
    src = (SRC / "routers" / "guild.py").read_text()
    q = src.index('await _qacc.settlement_gate(db, "guild_work_order", oid)')
    g = src.index("await _ccg.settlement_gate(db, oid)")
    claim = src.index("claimed = await db.execute(text(", q)
    assert q < g < claim, "after the quantum gate, before the claim"


# --- the reaper leaves a change in review or ballot alone -----------------------------------------------------------

def test_the_submitted_order_sweep_skips_an_active_code_change():
    from agentvault_registry.background_tasks import guild_order_reaper as reaper

    class _Db2:
        def __init__(self):
            self.sql = []

        async def execute(self, stmt, params=None):
            self.sql.append(str(stmt))

            class _R:
                def mappings(self):
                    return self

                def all(self):
                    return []
            return _R()
    db = _Db2()
    asyncio.run(reaper._sweep_abandoned_submitted(db))
    sql = " ".join(db.sql)
    assert "NOT EXISTS" in sql and "code_changes" in sql
    for s in cc.ACTIVE_STATES:
        assert f"'{s}'" in sql, s


# --- one frame's ballot first (D7) --------------------------------------------------------------------------------------

def test_a_code_change_ballot_is_never_lifted_to_the_federation():
    src = (SRC / "routers" / "governance.py").read_text()
    assert re.search(r'"proposal_type", None\)\s+in\s+\(\s*"federation_ballot"\s*,\s*"code_change"\s*\)', src)


# --- the migration -------------------------------------------------------------------------------------------------------

def test_the_migration_creates_both_tables():
    m = (ALEMBIC / "0225_code_changes.py").read_text()
    assert 'revision = "0225_code_changes"' in m and 'down_revision = "0222_chat_fed_events"' in m
    assert '"code_changes"' in m and '"code_change_reviews"' in m
