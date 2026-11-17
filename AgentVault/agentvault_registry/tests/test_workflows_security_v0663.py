"""V0663 (order gwo_1a029763e5442f09aecc26a6, the security read of 2026-11-14, W1 to W4): agent workflows.

Each test names the failure scenario the read described and was written red before its fix.

  W1  a step's order is linked to its step BEFORE the order exists, so there is no moment the order is open and unlinked; a stop
      between the claim and the order's insert leaves a claim the next advance clears (nothing holds the posting lock) and posts again;
  W2  a cross-registry bid meets the workflow's bid gate like a local one;
  W3  a step's output hash is the hash of what was delivered, never the worker's own claim;
  W4  `candidates` reads its agents in a handful of queries, not about a thousand, and answers exactly as the per-agent read did.
"""
from __future__ import annotations

import hashlib
import json
import types

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from agentvault_registry import models
from agentvault_registry.background_tasks import leader
from agentvault_registry.routers import guild as G
from agentvault_registry.services import workflow_rules as wr
from agentvault_registry.services import workflows as W
from tests.test_workflows_v0663 import A, A2, B, OWNER, _body, _env  # noqa: F401


class _Crash(BaseException):
    """The process stopping: not an Exception, so no `except Exception` cleanup runs."""


class _Redis:
    def __init__(self):
        self.kv = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    async def get(self, key):
        return self.kv.get(key)

    async def delete(self, key):
        self.kv.pop(key, None)


def _redis(monkeypatch, r="new"):
    r = _Redis() if r == "new" else r

    async def _get_redis():
        return r
    monkeypatch.setattr(leader, "get_redis", _get_redis)
    return r


def _posting(monkeypatch, db, *, crash_on=()):
    """The Guild's post replaced by a fake that inserts the order under the id it is GIVEN, and records what the step's row said at
    the moment the order did not exist yet."""
    seen = {"n": 0, "step_at_post": [], "ids": []}

    def new_id():
        seen["n"] += 1
        return f"gwo_s{seen['n']}"

    async def post(body, agent, db_, *, order_id=None):
        seen["ids"].append(order_id)
        row = (await db_.execute(text("SELECT order_id FROM agent_workflow_steps WHERE order_id=:o"), {"o": order_id})).first()
        exists = (await db_.execute(text("SELECT 1 FROM guild_work_orders WHERE id=:o"), {"o": order_id})).first()
        seen["step_at_post"].append((row[0] if row else None, bool(exists)))
        if seen["n"] in crash_on:
            raise _Crash()
        await db_.execute(text("INSERT INTO guild_work_orders (id, poster_did, status) VALUES (:i,:p,'open')"),
                          {"i": order_id, "p": agent.did})
        await db_.commit()
        return {"order_id": order_id, "status": "open"}
    monkeypatch.setattr(G, "new_order_id", new_id)
    monkeypatch.setattr(G, "_post_order", post)
    return seen


# ── W1 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_W1_the_step_is_linked_to_the_orders_id_before_the_order_exists(monkeypatch):
    """The order must never be open and unlinked: at the moment the Guild posts it, the step's row already names its id."""
    db = _env()
    _redis(monkeypatch)
    seen = _posting(monkeypatch, db)
    owner = types.SimpleNamespace(did=OWNER)
    v = await W.create(db, OWNER, _body())
    out = await W.advance(db, owner, v["id"])
    assert seen["step_at_post"] == [("gwo_s1", False)]                 # linked to its id, and the order did not exist yet
    assert out["posted_order_id"] == "gwo_s1" and out["steps"][0]["order_id"] == "gwo_s1"
    with pytest.raises(HTTPException) as e:                              # and the ruleset applies from the first moment
        await W.gate(db, "gwo_s1", B, 5.0, stage="bid")
    assert e.value.status_code == 403 and "bonded_only" in e.value.detail


@pytest.mark.asyncio
async def test_W1_a_stop_between_the_claim_and_the_order_is_recovered_by_the_next_advance(monkeypatch):
    """A restart in the window used to leave the step 'pending' for good, the order never linked and the step never posted again."""
    db = _env()
    _redis(monkeypatch)
    seen = _posting(monkeypatch, db, crash_on=(1,))
    owner = types.SimpleNamespace(did=OWNER)
    v = await W.create(db, OWNER, _body())
    with pytest.raises(_Crash):
        await W.advance(db, owner, v["id"])
    stranded = (await db.execute(text("SELECT order_id FROM agent_workflow_steps WHERE step_key='build'"))).scalar()
    assert stranded == "gwo_s1"                                            # claimed, never posted
    out = await W.advance(db, owner, v["id"])                              # nothing holds the posting lock now
    assert out["posted_order_id"] == "gwo_s2" and out["steps"][0]["order_id"] == "gwo_s2"
    assert (await db.execute(text("SELECT count(*) FROM guild_work_orders"))).scalar() == 1


@pytest.mark.asyncio
async def test_W1_a_call_that_is_posting_is_not_stolen_from(monkeypatch):
    """While another call holds the posting lock, a claim whose order is not there yet is that call's, not a stranded one."""
    db = _env()
    r = _redis(monkeypatch)
    _posting(monkeypatch, db, crash_on=(1,))
    owner = types.SimpleNamespace(did=OWNER)
    v = await W.create(db, OWNER, _body())
    with pytest.raises(_Crash):
        await W.advance(db, owner, v["id"])
    step_id = (await db.execute(text("SELECT id FROM agent_workflow_steps WHERE step_key='build'"))).scalar()
    r.kv[W._lock_key(step_id)] = "1"                                      # another call is posting it right now
    with pytest.raises(HTTPException) as e:
        await W.advance(db, owner, v["id"])
    assert e.value.status_code == 409
    assert (await db.execute(text("SELECT order_id FROM agent_workflow_steps WHERE step_key='build'"))).scalar() == "gwo_s1"


@pytest.mark.asyncio
async def test_W1_without_redis_a_stranded_claim_is_not_cleared_on_a_guess(monkeypatch):
    db = _env()
    _redis(monkeypatch, r=None)
    _posting(monkeypatch, db, crash_on=(1,))
    owner = types.SimpleNamespace(did=OWNER)
    v = await W.create(db, OWNER, _body())
    with pytest.raises(_Crash):
        await W.advance(db, owner, v["id"])
    with pytest.raises(HTTPException) as e:
        await W.advance(db, owner, v["id"])
    assert e.value.status_code == 409
    assert (await db.execute(text("SELECT order_id FROM agent_workflow_steps WHERE step_key='build'"))).scalar() == "gwo_s1"


@pytest.mark.asyncio
async def test_W1_a_refused_post_frees_the_step_and_the_lock(monkeypatch):
    db = _env()
    r = _redis(monkeypatch)
    _posting(monkeypatch, db)

    async def refuse(body, agent, db_, *, order_id=None):
        raise HTTPException(402, detail="Escrow failed")
    monkeypatch.setattr(G, "_post_order", refuse)
    owner = types.SimpleNamespace(did=OWNER)
    v = await W.create(db, OWNER, _body())
    with pytest.raises(HTTPException) as e:
        await W.advance(db, owner, v["id"])
    assert e.value.status_code == 402
    assert (await db.execute(text("SELECT order_id FROM agent_workflow_steps WHERE step_key='build'"))).scalar() is None
    assert not r.kv                                                        # the lock is not left held


# ── W2 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_W2_a_cross_registry_bid_meets_the_workflow_gate_before_any_collateral(monkeypatch):
    """A foreign agent bidding on a ruleset step is refused up front (the gate), not accepted and refused at the award."""
    gated = []

    async def caller_is(*a, **k):
        return True

    async def noop(*a, **k):
        return None

    async def load(db_, oid):
        return {"id": oid, "status": "open", "poster_did": "did:theprotocol:eu.test:poster", "bounty": 10, "min_reputation": None,
                "stake_required": None, "worker_home_registry": None}

    async def gate(db_, order_id, bidder, price, *, stage):
        gated.append((order_id, bidder, price, stage))
        raise HTTPException(403, detail="workflow rule bonded_only: refused")
    monkeypatch.setattr(G, "_caller_is", caller_is)
    monkeypatch.setattr(G._rb, "gate", noop)
    monkeypatch.setattr(G._ep, "gate", noop)
    monkeypatch.setattr(G, "_load", load)
    monkeypatch.setattr(G, "_require_enabled", lambda: None)
    monkeypatch.setattr(W, "gate", gate)
    body = G.FederatedBidIn(bidder_did="did:theprotocol:far.test:x", home_registry_url="https://far.example", price=5.0)
    with pytest.raises(HTTPException) as e:
        await G.place_bid_federated("gwo_x", body, db=object(), peer_spiffe_id="spiffe://far.example/service/registry")
    assert e.value.status_code == 403 and "workflow rule" in e.value.detail
    assert gated == [("gwo_x", "did:theprotocol:far.test:x", 5.0, "bid")]


# ── W3 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_W3_the_output_hash_is_never_the_workers_own_claim():
    claimed = "a" * 64
    delivered = {"hash": claimed, "uri": "ipfs://something-else"}
    canonical = hashlib.sha256(json.dumps(delivered, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    assert wr.output_hash(delivered) == canonical and wr.output_hash(delivered) != claimed
    assert wr.output_hash({"text": "x"}) == hashlib.sha256(b'{"text":"x"}').hexdigest()


@pytest.mark.asyncio
async def test_W3_a_worker_cannot_make_the_receipt_attest_another_outputs_hash(monkeypatch):
    """The worker delivers {"hash": <the hash of a different, approved output>}: the receipt chain attests what was delivered."""
    db = _env()
    _redis(monkeypatch)
    _posting(monkeypatch, db)
    owner = types.SimpleNamespace(did=OWNER)
    v = await W.create(db, OWNER, _body())
    await W.advance(db, owner, v["id"])
    approved_elsewhere = "b" * 64
    deliverable = {"hash": approved_elsewhere, "note": "this is not that output"}
    await db.execute(text("UPDATE guild_work_orders SET status='settled', worker_did=:w, deliverable=:d WHERE id='gwo_s1'"),
                     {"w": A, "d": json.dumps(deliverable)})
    await db.commit()
    out = await W.advance(db, owner, v["id"])
    h = out["steps"][0]["output_hash"]
    assert h != approved_elsewhere and h == wr.output_hash(deliverable)
    assert out["chain_ok"] is True


# ── W4 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_W4_candidates_reads_its_agents_in_a_handful_of_queries_and_answers_as_before(monkeypatch):
    db = _env()
    _redis(monkeypatch)
    _posting(monkeypatch, db)
    s = db.sync
    base = 100
    for k in range(60):                                                    # sixty more agents: bonded or not, three owners
        did = f"did:theprotocol:eu.test:many-{k}"
        s.add(models.Agent(id=base + k, did=did, client_id=f"cm{k}", hashed_client_secret="x", creator_developer_id=(1, 2, 3)[k % 3],
                           status="active", reputation_score=k % 7))
    s.commit()
    s.execute(text("UPDATE agents SET reputation_bond_status='locked' WHERE did LIKE 'did:theprotocol:eu.test:many-%' AND id % 2 = 0"))
    s.commit()
    v = await W.create(db, OWNER, _body(ruleset={"bonded_only": True, "min_reputation": 2}))

    # the per-agent answer, as the code read it before (the same rules over the same facts)
    w = await W._load_workflow(db, v["id"])
    steps = await W._load_steps(db, v["id"])
    rules = wr.merge(w["ruleset"], steps[0]["ruleset"])
    orders = await W._orders_of(db, [x for x in steps if x["step_key"] != "build"])
    rows = (await db.execute(text("SELECT did FROM agents WHERE status='active' AND did <> :o ORDER BY reputation_score DESC NULLS LAST LIMIT 200"),
                             {"o": OWNER})).mappings().all()
    no_price = {k: val for k, val in rules.items() if k != "max_price"}
    expected = [r["did"] for r in rows if not wr.evaluate(no_price, await W._facts(db, r["did"], 0.0, steps, orders))][:50]
    assert expected, "the control population must have passing agents"

    count = {"n": 0}
    real = db.execute

    async def counted(*a, **k):
        count["n"] += 1
        return await real(*a, **k)
    db.execute = counted
    out = await W.candidates(db, v["id"], "build")
    db.execute = real
    assert out["passing"] == expected and out["considered"] == len(rows)
    assert out["refused"] == len(rows) - len([r for r in rows if not wr.evaluate(
        no_price, await W._facts(db, r["did"], 0.0, steps, orders))])
    assert count["n"] <= 12, f"candidates ran {count['n']} queries for {len(rows)} agents"
