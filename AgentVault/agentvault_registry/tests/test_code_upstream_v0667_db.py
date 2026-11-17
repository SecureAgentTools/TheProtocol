"""V0667 D4, upstream, on a REAL Postgres (the order: "a rule that reads or writes a store: one test through the REAL route on a real Postgres via asyncpg").

  1. migration 0237_code_change_upstream: down removes exactly its three columns, its foreign key, its unique constraint and the two new room states; up puts exactly them back
     (the schema equals what it was); a downgrade turns a room's `upstream` / `upstreaming` back into `merged` first;
  2. the constraints: a line change goes upstream ONCE (unique), the history it names cannot be deleted (RESTRICT), the room's state is one of the known words;
  3. THROUGH THE REAL ROUTE (POST /api/v1/code-changes/{id}/upstream, the production DbStore, asyncpg): a decider's agent proposes a merged line change upstream; the new change
     is a main-line row for the same commit with its provenance stored as JSONB (the reviews and the checker's record intact); the line's copy reads the proposal; a stranger, a
     second proposal and an unmerged change are refused with their sentences and write nothing; the mark the merge leaves on the line's copy round-trips through JSONB.
Skipped unless CODE_DISTRIBUTIONS_TEST_DB names a throwaway database it may WIPE (postgresql+asyncpg://...). Skipped, never silently passed.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import pathlib
import uuid

import httpx
import pytest

DB = os.environ.get("CODE_DISTRIBUTIONS_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres database it may wipe: set CODE_DISTRIBUTIONS_TEST_DB. Skipped, never silently passed.", allow_module_level=True)

from alembic.operations import Operations  # noqa: E402
from alembic.runtime.migration import MigrationContext  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from agentvault_registry.services import code_authority as ca  # noqa: E402
from agentvault_registry.services import code_changes as cc  # noqa: E402
from tests.test_code_distributions_v0666_db import _dist, _seed  # noqa: E402

ALEMBIC = pathlib.Path(__file__).resolve().parents[1] / "alembic"
CONSOLE = "agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/"
DOC = CONSOLE + "assets/docs/lyceum.md"
SHA = "a" * 40


def _migration():
    path = next((ALEMBIC / "versions").glob("0237_*.py"))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
async def engine():
    from agentvault_registry.models import Base
    eng = create_async_engine(DB)
    async with eng.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def _run(conn, mod, fn):
    def go(sync_conn):
        with Operations.context(MigrationContext.configure(sync_conn)):
            getattr(mod, fn)()
    await conn.run_sync(go)


def _schema(sync_conn):
    insp = inspect(sync_conn)
    cols = sorted(c["name"] for c in insp.get_columns("code_changes"))
    checks = {c["name"]: c["sqltext"] for c in insp.get_check_constraints("code_changes")}
    return {"columns": cols, "uniques": sorted(u["name"] for u in insp.get_unique_constraints("code_changes")),
            "fks": sorted(f["name"] for f in insp.get_foreign_keys("code_changes") if f.get("name")), "checks": sorted(checks),
            "room_check": checks.get("ck_code_changes_announce_state")}


# --- 1. the migration ----------------------------------------------------------------------------------------------------

async def test_0237_down_then_up_restores_the_schema_exactly(engine):
    mod = _migration()
    assert mod.down_revision == "0236_content_changes" and mod.revision == "0237_code_change_upstream"   # re-chained on 0236 at the D6 base merge
    async with engine.begin() as conn:
        before = await conn.run_sync(_schema)
    assert {"upstream_of", "provenance", "upstream_since"} <= set(before["columns"])
    assert "'upstream'" in before["room_check"] and "'upstreaming'" in before["room_check"]
    async with engine.begin() as conn:
        await _run(conn, mod, "downgrade")
        mid = await conn.run_sync(_schema)
    assert not ({"upstream_of", "provenance", "upstream_since"} & set(mid["columns"]))
    assert "uq_code_changes_upstream_of" not in mid["uniques"] and "fk_code_changes_upstream_of" not in mid["fks"]
    assert "'upstream'" not in mid["room_check"] and "'merged'" in mid["room_check"]
    async with engine.begin() as conn:
        await _run(conn, mod, "upgrade")
        after = await conn.run_sync(_schema)
    assert after == before


async def test_the_downgrade_turns_an_upstream_room_state_back_into_merged_first(engine, maker):
    mod = _migration()
    devs, org, team = await _seed(maker)
    async with maker() as s:
        d = _dist(org, team)
        s.add(d)
        await s.flush()
        s.add(_line_change("cc_a", devs["member"], d.id, announce_state="upstream"))
        await s.commit()
    async with engine.begin() as conn:
        await _run(conn, mod, "downgrade")
    async with maker() as s:
        assert (await s.execute(text("SELECT announce_state FROM code_changes WHERE id = 'cc_a'"))).scalar_one() == "merged"


# --- 2. the constraints --------------------------------------------------------------------------------------------------------

def _line_change(cid, proposer, dist_id, **over):
    from agentvault_registry.models import CodeChange
    row = {"id": cid, "repository": "theprotocol/AgentVault", "paths": [DOC], "title": "A clearer page", "problem": "The page says too little.",
           "mode": "branch", "branch": "lyceum/clearer", "commit": SHA, "proposer_did": "did:a:member", "proposer_developer_id": proposer,
           "sensitive": False, "state": "merged", "code_distribution_id": dist_id,
           "acceptance": {"ok": True, "reasons": [], "record": {"commit": SHA, "read_from": "checker", "touched": [DOC]}},
           "ballot_rule": {"quorum_percent": 50, "pass_rule": "simple"}, "ballot_result": {"status": "PASSED", "counted": 3},
           "merged": {"commit": SHA, "into": "distribution/V0666_lyceum", "at": "2026-11-16T10:00:00+00:00"}}
    row.update(over)
    return CodeChange(**row)


def _main_change(cid, proposer, **over):
    from agentvault_registry.models import CodeChange
    row = {"id": cid, "repository": "theprotocol/AgentVault", "paths": [DOC], "title": "T", "problem": "P", "mode": "branch", "branch": "b",
           "commit": SHA, "proposer_did": "did:a:owner", "proposer_developer_id": proposer, "sensitive": False, "state": "proposed"}
    row.update(over)
    return CodeChange(**row)


async def test_a_line_change_goes_upstream_once_and_the_history_it_names_stays(maker):
    devs, org, team = await _seed(maker)
    async with maker() as s:
        d = _dist(org, team)
        s.add(d)
        await s.flush()
        s.add(_line_change("cc_line", devs["member"], d.id))
        await s.flush()
        s.add(_main_change("cc_up1", devs["owner"], upstream_of="cc_line", provenance={"x": 1}))
        await s.commit()
    async with maker() as s:
        s.add(_main_change("cc_up2", devs["owner"], upstream_of="cc_line"))
        with pytest.raises(IntegrityError):                         # unique: once
            await s.commit()
    async with maker() as s:
        s.add(_main_change("cc_up3", devs["owner"], upstream_of="cc_nothing"))
        with pytest.raises(IntegrityError):                         # the history it names exists
            await s.commit()
    async with maker() as s:
        with pytest.raises(IntegrityError):                         # RESTRICT: the line change cannot be deleted under it
            await s.execute(text("DELETE FROM code_changes WHERE id = 'cc_line'"))
            await s.commit()
    async with maker() as s:
        s.add(_main_change("cc_ok", devs["owner"], announce_state="upstream"))
        await s.commit()
    async with maker() as s:
        s.add(_main_change("cc_bad", devs["owner"], announce_state="upstreamish"))
        with pytest.raises(IntegrityError):
            await s.commit()


# --- 3. THE REAL ROUTE ---------------------------------------------------------------------------------------------------------

class _Agent:
    def __init__(self, did, dev):
        self.did, self.creator_developer_id = did, dev


def _app(maker, agent, monkeypatch):
    from fastapi import FastAPI
    from agentvault_registry import database
    from agentvault_registry.routers import code_changes as cc_route
    from agentvault_registry.routers.utils import get_current_agent
    monkeypatch.setenv("CODE_DISTRIBUTIONS_ENABLED", "true")
    monkeypatch.setenv(ca.ENV, "eu")
    monkeypatch.setattr(ca, "own_name", lambda: "eu")
    monkeypatch.delenv("REPO_ACCOUNTS_ENABLED", raising=False)
    app = FastAPI()
    app.include_router(cc_route.router)

    async def get_db():
        async with maker() as s:
            yield s
    app.dependency_overrides[database.get_db] = get_db
    app.dependency_overrides[get_current_agent] = lambda: agent
    return app


async def _call(app, method, path):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://reg.test") as c:
        return await c.request(method, path)


async def _seed_merged(maker, **over):
    from agentvault_registry.models import CodeChangeReview
    devs, org, team = await _seed(maker)
    async with maker() as s:
        d = _dist(org, team, slug="lyceum")
        s.add(d)
        await s.flush()
        s.add(_line_change("cc_line", devs["member"], d.id, **over))
        await s.flush()
        s.add(CodeChangeReview(code_change_id="cc_line", reviewer_developer_id=devs["lead"], verdict="approve", commit=SHA, findings="read"))
        await s.commit()
    return devs, org, d.id


async def test_a_decider_proposes_a_merged_line_change_upstream_through_the_real_route(maker, monkeypatch):
    devs, org, dist_id = await _seed_merged(maker)
    app = _app(maker, _Agent("did:a:owner", devs["owner"]), monkeypatch)
    r = await _call(app, "POST", "/api/v1/code-changes/cc_line/upstream")
    assert r.status_code == 201, r.text
    body = r.json()
    ucid = body["id"]
    assert body["upstream_of"] == "cc_line" and body["commit"] == SHA and body["state"] == "proposed" and "code_distribution" not in body
    async with maker() as s:
        row = (await s.execute(text("SELECT upstream_of, code_distribution_id, commit, paths, provenance, proposer_developer_id FROM code_changes WHERE id = :i"),
                               {"i": ucid})).one()
        assert row.upstream_of == "cc_line" and row.code_distribution_id is None and row.commit == SHA and row.paths == [DOC]
        assert row.proposer_developer_id == devs["owner"]
        prov = row.provenance
        assert prov["line"]["slug"] == "lyceum" and prov["line"]["id"] == dist_id and prov["line"]["organization_name"] == "Lyceum"
        assert prov["line_change"]["id"] == "cc_line" and prov["line_change"]["merged"]["commit"] == SHA
        assert prov["ballot"]["result"]["status"] == "PASSED" and prov["ballot"]["rule"]["quorum_percent"] == 50
        assert [(x["reviewer_developer_id"], x["verdict"], x["commit"]) for x in prov["reviews"]] == [(devs["lead"], "approve", SHA)]
        assert prov["checker"]["record"]["read_from"] == "checker" and prov["checker"]["ok"] is True
        assert (await s.execute(text("SELECT count(*) FROM code_changes WHERE upstream_of IS NOT NULL"))).scalar_one() == 1
    line = (await _call(app, "GET", "/api/v1/code-changes/cc_line")).json()
    assert line["upstream"] == {"change_id": ucid, "state": "proposed", "since": None}
    listed = (await _call(app, "GET", "/api/v1/code-changes?upstream=true")).json()["code_changes"]
    assert [c["id"] for c in listed] == [ucid] and listed[0]["provenance"]["line"]["slug"] == "lyceum"
    again = await _call(app, "POST", "/api/v1/code-changes/cc_line/upstream")
    assert again.status_code == 409 and again.json()["code"] == "already_upstream" and ucid in again.json()["detail"]
    async with maker() as s:
        assert (await s.execute(text("SELECT count(*) FROM code_changes WHERE upstream_of IS NOT NULL"))).scalar_one() == 1     # nothing written by the refusal


async def test_the_real_route_refuses_a_stranger_and_an_unmerged_change_and_writes_nothing(maker, monkeypatch):
    devs, org, dist_id = await _seed_merged(maker)
    stranger = _app(maker, _Agent("did:a:s", devs["gone"]), monkeypatch)             # in no good standing: not a decider
    r = await _call(stranger, "POST", "/api/v1/code-changes/cc_line/upstream")
    assert r.status_code == 403 and r.json()["code"] == "not_a_decider"
    async with maker() as s:
        await s.execute(text("UPDATE code_changes SET state = 'passed' WHERE id = 'cc_line'"))
        await s.commit()
    owner = _app(maker, _Agent("did:a:owner", devs["owner"]), monkeypatch)
    r = await _call(owner, "POST", "/api/v1/code-changes/cc_line/upstream")
    assert r.status_code == 409 and r.json()["code"] == "not_merged"
    async with maker() as s:
        assert (await s.execute(text("SELECT count(*) FROM code_changes WHERE upstream_of IS NOT NULL"))).scalar_one() == 0


async def test_the_mark_a_merge_leaves_on_the_lines_copy_round_trips_through_jsonb(maker, monkeypatch):
    devs, org, dist_id = await _seed_merged(maker)
    app = _app(maker, _Agent("did:a:owner", devs["owner"]), monkeypatch)
    ucid = (await _call(app, "POST", "/api/v1/code-changes/cc_line/upstream")).json()["id"]
    async with maker() as s:
        await cc.DbStore(s).update("cc_line", upstream_since={"change_id": ucid, "at": "2026-11-20T10:00:00+00:00"})
        await s.execute(text("UPDATE code_changes SET state = 'merged' WHERE id = :i"), {"i": ucid})
        await s.commit()
    line = (await _call(app, "GET", "/api/v1/code-changes/cc_line")).json()
    assert line["upstream_since"] == {"change_id": ucid, "at": "2026-11-20T10:00:00+00:00"}
    assert line["upstream"] == {"change_id": ucid, "state": "merged", "since": "2026-11-20T10:00:00+00:00"}
