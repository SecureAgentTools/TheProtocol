"""V0663 (agent workflows): the service over a real (SQLite) database, the gate at bid and award, and advance.

The Guild's own post_order is replaced by a fake that inserts the order row (its escrow is the Guild's, tested there); everything
else is the real service code: creating a workflow, the ruleset gate, advance recording a settled step's hash and receipt, and the
chain a stranger can recompute."""
from __future__ import annotations

import datetime as _dt
import sqlite3
import types
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from agentvault_registry import models
from agentvault_registry.routers import guild as G
from agentvault_registry.services import workflow_rules as wr
from agentvault_registry.services import workflows as W
from tests._sqlite_db import sqlite_db

sqlite3.register_adapter(Decimal, str)   # PostgreSQL binds a Decimal to NUMERIC; SQLite needs telling

OWNER_DEV, DEV_A, DEV_B = 1, 2, 3
OWNER = "did:theprotocol:eu.test:owner"
A = "did:theprotocol:eu.test:agent-a"      # owned by DEV_A
B = "did:theprotocol:eu.test:agent-b"      # owned by DEV_B
A2 = "did:theprotocol:eu.test:agent-a2"    # a second agent of DEV_A


def _env():
    db = sqlite_db(models.Developer, models.Agent, models.AgentCard)
    s = db.sync
    s.connection().connection.dbapi_connection.create_function(
        "now", 0, lambda: _dt.datetime.now(_dt.timezone.utc).isoformat(" "))
    for i in (OWNER_DEV, DEV_A, DEV_B):
        s.add(models.Developer(id=i, name=f"d{i}", email=f"d{i}@example.test", hashed_password="x"))
    for n, (did, dev, rep, bond) in enumerate([(OWNER, OWNER_DEV, 0, "none"), (A, DEV_A, 5, "bonded"),
                                               (B, DEV_B, 5, "none"), (A2, DEV_A, 5, "bonded")], start=1):
        s.add(models.Agent(id=n, did=did, client_id=f"c{n}", hashed_client_secret="x", creator_developer_id=dev,
                           status="active", reputation_score=rep))
    s.commit()
    s.execute(text("UPDATE agents SET reputation_bond_status='locked' WHERE did IN (:a, :a2)"), {"a": A, "a2": A2})
    s.execute(text("CREATE TABLE guild_work_orders (id TEXT PRIMARY KEY, poster_did TEXT, status TEXT, worker_did TEXT, deliverable TEXT)"))
    s.execute(text("""CREATE TABLE agent_workflows (id TEXT PRIMARY KEY, owner_did TEXT, title TEXT, ruleset TEXT, ruleset_hash TEXT,
        total_budget NUMERIC, currency TEXT, status TEXT DEFAULT 'draft', created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"""))
    s.execute(text("""CREATE TABLE agent_workflow_steps (id INTEGER PRIMARY KEY AUTOINCREMENT, workflow_id TEXT, position INTEGER, step_key TEXT,
        role TEXT, spec TEXT, acceptance TEXT, budget NUMERIC, deadline_seconds INTEGER, ruleset TEXT, input_from TEXT, order_id TEXT,
        output_hash TEXT, receipt TEXT)"""))
    s.commit()
    return db


def _fake_post(db_holder):
    """The Guild's post: inserts the order under the id it is GIVEN (agent workflows choose it first, security read W1); the ids
    the service asks for are gwo_fake1, gwo_fake2 ..., patched in by `_patch_posting`."""
    async def post_order(body, agent, db, *, order_id=None):
        oid = order_id
        await db.execute(text("INSERT INTO guild_work_orders (id, poster_did, status) VALUES (:i,:p,'open')"),
                         {"i": oid, "p": agent.did})
        await db.commit()
        return {"order_id": oid, "status": "open"}
    return post_order


def _patch_posting(monkeypatch, db):
    n = {"i": 0}

    def new_order_id():
        n["i"] += 1
        return f"gwo_fake{n['i']}"
    monkeypatch.setattr(G, "new_order_id", new_order_id)
    monkeypatch.setattr(G, "_post_order", _fake_post(db))


def _body(**kw):
    b = {"title": "Release chain", "total_budget": 30,
         "ruleset": {"bonded_only": True},
         "steps": [{"key": "build", "role": "builder", "budget": 10, "spec": "build it"},
                   {"key": "verify", "role": "verifier", "budget": 10, "input_from": "build",
                    "ruleset": {"independent_of": ["build"]}}]}
    b.update(kw)
    return b


@pytest.mark.asyncio
async def test_create_validates_and_hashes():
    db = _env()
    v = await W.create(db, OWNER, _body())
    assert v["status"] == "draft" and [s["key"] for s in v["steps"]] == ["build", "verify"]
    assert v["ruleset_hash"] == wr.ruleset_hash({"bonded_only": True}) and v["chain"] == [] and v["chain_ok"]
    for bad, why in [(_body(total_budget=15), "above total_budget"),
                     (_body(ruleset={"frame": "eu"}), "frame"),
                     (_body(steps=[]), "steps"),
                     (_body(steps=[{"key": "a", "role": "r", "budget": 1}, {"key": "a", "role": "r", "budget": 1}]), "twice"),
                     (_body(steps=[{"key": "a", "role": "r", "budget": 1, "input_from": "z"}]), "earlier step"),
                     (_body(steps=[{"key": "a", "role": "r", "budget": 1, "ruleset": {"independent_of": ["a"]}}]), "itself|belongs")]:
        with pytest.raises(HTTPException) as e:
            await W.create(db, OWNER, bad)
        assert e.value.status_code == 422, why


@pytest.mark.asyncio
async def test_advance_posts_one_step_at_a_time_and_chains_settled_output(monkeypatch):
    db = _env()
    _patch_posting(monkeypatch, db)
    owner = types.SimpleNamespace(did=OWNER)
    v = await W.create(db, OWNER, _body())
    wid = v["id"]
    v = await W.advance(db, owner, wid)
    assert v["status"] == "running" and v["posted_order_id"] == "gwo_fake1"
    assert v["steps"][0]["order_id"] == "gwo_fake1" and v["steps"][1]["order_id"] is None
    # nothing settled: advancing again posts nothing and changes nothing
    again = await W.advance(db, owner, wid)
    assert again["posted_order_id"] is None and again["steps"] == v["steps"]
    # step 1 settles with a deliverable
    await db.execute(text("UPDATE guild_work_orders SET status='settled', worker_did=:w, deliverable=:d WHERE id='gwo_fake1'"),
                     {"w": A, "d": '{"hash": "AA11", "uri": "x"}'})
    await db.commit()
    v = await W.advance(db, owner, wid)
    assert v["steps"][0]["output_hash"] == wr.output_hash({"hash": "AA11", "uri": "x"}) != "aa11" and v["steps"][0]["receipt"] and v["posted_order_id"] == "gwo_fake2"
    assert v["chain_ok"] and len(v["chain"]) == 1
    # step 2 settles: done, and the chain verifies from the outside
    await db.execute(text("UPDATE guild_work_orders SET status='settled', worker_did=:w, deliverable=:d WHERE id='gwo_fake2'"),
                     {"w": B, "d": '{"text": "ok"}'})
    await db.commit()
    v = await W.advance(db, owner, wid)
    assert v["status"] == "done" and v["chain_ok"] and len(v["chain"]) == 2
    assert wr.verify_chain(v["chain"]) == (True, None)
    # a forged stored hash is caught by the recomputation
    await db.execute(text("UPDATE agent_workflow_steps SET output_hash='ff' WHERE step_key='build'"))
    await db.commit()
    forged = await W.view(db, wid)
    assert forged["chain_ok"] is False and forged["chain_problem"]


@pytest.mark.asyncio
async def test_only_the_owner_advances_or_cancels(monkeypatch):
    db = _env()
    _patch_posting(monkeypatch, db)
    v = await W.create(db, OWNER, _body())
    for fn in (W.advance, W.cancel):
        with pytest.raises(HTTPException) as e:
            await fn(db, types.SimpleNamespace(did=A), v["id"])
        assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_cancel_waits_for_the_open_step_order(monkeypatch):
    db = _env()
    _patch_posting(monkeypatch, db)
    owner = types.SimpleNamespace(did=OWNER)
    v = await W.create(db, OWNER, _body())
    await W.advance(db, owner, v["id"])
    with pytest.raises(HTTPException) as e:
        await W.cancel(db, owner, v["id"])
    assert e.value.status_code == 409 and "build" in e.value.detail
    await db.execute(text("UPDATE guild_work_orders SET status='cancelled' WHERE id='gwo_fake1'"))
    await db.commit()
    assert (await W.cancel(db, owner, v["id"]))["status"] == "cancelled"
    with pytest.raises(HTTPException):
        await W.advance(db, owner, v["id"])


@pytest.mark.asyncio
async def test_gate_refuses_an_unbonded_bidder_and_names_the_rule(monkeypatch):
    db = _env()
    _patch_posting(monkeypatch, db)
    owner = types.SimpleNamespace(did=OWNER)
    v = await W.create(db, OWNER, _body())
    await W.advance(db, owner, v["id"])
    await W.gate(db, "gwo_fake1", A, 5.0, stage="bid")                       # bonded: passes
    with pytest.raises(HTTPException) as e:
        await W.gate(db, "gwo_fake1", B, 5.0, stage="bid")                   # not bonded
    assert e.value.status_code == 403 and "bonded_only" in e.value.detail
    await W.gate(db, "gwo_not_a_step", B, 5.0, stage="bid")                  # an order that is no step's: untouched


@pytest.mark.asyncio
async def test_independence_is_about_the_owner_not_the_agent(monkeypatch):
    db = _env()
    _patch_posting(monkeypatch, db)
    owner = types.SimpleNamespace(did=OWNER)
    v = await W.create(db, OWNER, _body(ruleset={}))
    await W.advance(db, owner, v["id"])
    await db.execute(text("UPDATE guild_work_orders SET status='settled', worker_did=:w, deliverable='{}' WHERE id='gwo_fake1'"), {"w": A})
    await db.commit()
    await W.advance(db, owner, v["id"])                                      # posts the verify order gwo_fake2
    # a different AGENT of the same OWNER is not independent
    with pytest.raises(HTTPException) as e:
        await W.gate(db, "gwo_fake2", A2, 5.0, stage="bid")
    assert e.value.status_code == 403 and "independent_of" in e.value.detail and "same owner" in e.value.detail
    await W.gate(db, "gwo_fake2", B, 5.0, stage="bid")                       # another owner passes
    await W.gate(db, "gwo_fake2", B, 5.0, stage="award")


@pytest.mark.asyncio
async def test_candidates_lists_who_passes_and_counts_the_rest(monkeypatch):
    db = _env()
    _patch_posting(monkeypatch, db)
    v = await W.create(db, OWNER, _body())
    c = await W.candidates(db, v["id"], "build")
    assert set(c["passing"]) == {A, A2} and c["refused"] == 1 and c["considered"] == 3 and c["scope"].endswith("this registry only")
