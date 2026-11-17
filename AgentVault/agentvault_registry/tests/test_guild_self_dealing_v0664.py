"""V0664 (order gwo_48ac3a9ec2ab8bb3d5643c92, room seq 3638): no self-dealing on ordinary Guild orders. A bid or an
award whose worker, payee agent or paid organization belongs to the developer who posted the order is refused, with a sentence
that says why; GUILD_SELF_DEALING_MODE off | shadow | enforce (default enforce in the code: the session room on EU runs shadow
until the sessions have developers of their own, room seq 3652)."""
from __future__ import annotations

import logging
import types

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from agentvault_registry import models
from agentvault_registry.routers import guild as G
from agentvault_registry.services import guild_self_dealing as SD
from tests._sqlite_db import sqlite_db

POSTER, WORKER_SAME, WORKER_OTHER = "did:t:poster", "did:t:same-dev", "did:t:other-dev"
FOREIGN = "did:t:never-seen-here"
ORDER = {"id": "gwo_x", "poster_did": POSTER, "status": "open", "bounty": 10}


def _db():
    db = sqlite_db(models.Developer)
    s = db.sync
    s.execute(text("CREATE TABLE agents (did TEXT PRIMARY KEY, creator_developer_id INTEGER)"))
    s.execute(text("CREATE TABLE organizations (id TEXT PRIMARY KEY, owner_id INTEGER)"))
    for did, dev in ((POSTER, 1), (WORKER_SAME, 1), (WORKER_OTHER, 2), ("did:t:treasury-own", 1), ("did:t:treasury-other", 2)):
        s.execute(text("INSERT INTO agents (did, creator_developer_id) VALUES (:d, :v)"), {"d": did, "v": dev})
    s.execute(text("INSERT INTO organizations (id, owner_id) VALUES ('org-own', 1), ('org-other', 2)"))
    s.commit()
    return db


# ── the mode ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_default_is_enforce_and_an_unknown_word_is_enforce_too(monkeypatch):
    monkeypatch.delenv("GUILD_SELF_DEALING_MODE", raising=False)
    assert SD.mode() == "enforce"
    for word, want in (("off", "off"), ("SHADOW", "shadow"), (" enforce ", "enforce"), ("banana", "enforce"), ("", "enforce")):
        monkeypatch.setenv("GUILD_SELF_DEALING_MODE", word)
        assert SD.mode() == want, word


# ── what counts ──────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_worker_of_the_posters_own_developer_is_refused_with_a_sentence_that_says_why():
    why = await SD.refusal(_db(), ORDER, worker_did=WORKER_SAME)
    assert why and "poster's own developer" in why and "someone else's work" in why


@pytest.mark.asyncio
async def test_a_payee_agent_or_a_paid_organization_of_the_poster_developer_is_refused():
    db = _db()
    assert await SD.refusal(db, ORDER, worker_did=WORKER_OTHER, payee_did="did:t:treasury-own")
    assert await SD.refusal(db, ORDER, worker_did=WORKER_OTHER, org_id="org-own")


@pytest.mark.asyncio
async def test_another_developer_a_foreign_agent_and_an_unknown_poster_pass():
    db = _db()
    assert await SD.refusal(db, ORDER, worker_did=WORKER_OTHER) is None
    assert await SD.refusal(db, ORDER, worker_did=WORKER_OTHER, payee_did="did:t:treasury-other", org_id="org-other") is None
    assert await SD.refusal(db, ORDER, worker_did=FOREIGN) is None                       # another registry's agent: no developer here
    assert await SD.refusal(db, {**ORDER, "poster_did": "did:t:poster-from-elsewhere"}, worker_did=WORKER_SAME) is None


# ── the three modes ──────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_enforce_refuses_with_403(monkeypatch):
    monkeypatch.setenv("GUILD_SELF_DEALING_MODE", "enforce")
    with pytest.raises(HTTPException) as e:
        await SD.gate(_db(), ORDER, worker_did=WORKER_SAME, stage="bid")
    assert e.value.status_code == 403 and "poster's own developer" in e.value.detail


@pytest.mark.asyncio
async def test_shadow_logs_and_never_refuses(monkeypatch, caplog):
    monkeypatch.setenv("GUILD_SELF_DEALING_MODE", "shadow")
    with caplog.at_level(logging.WARNING):
        await SD.gate(_db(), ORDER, worker_did=WORKER_SAME, stage="award")
    assert any("self-dealing" in r.getMessage() and "shadow" in r.getMessage() and "gwo_x" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_off_reads_nothing(monkeypatch):
    monkeypatch.setenv("GUILD_SELF_DEALING_MODE", "off")

    class Dead:
        async def execute(self, *a, **k):
            raise AssertionError("mode off must not read")
    await SD.gate(Dead(), ORDER, worker_did=WORKER_SAME, stage="bid")


@pytest.mark.asyncio
async def test_a_different_developer_passes_in_every_mode(monkeypatch):
    for m in ("off", "shadow", "enforce"):
        monkeypatch.setenv("GUILD_SELF_DEALING_MODE", m)
        await SD.gate(_db(), ORDER, worker_did=WORKER_OTHER, stage="bid")


# ── where it is called ───────────────────────────────────────────────────────────────────────────────────────────────
class _Sentinel(Exception):
    pass


async def _noop(*a, **k):
    return None


@pytest.mark.asyncio
async def test_a_bid_meets_the_gate_before_any_collateral_or_insert(monkeypatch):
    seen = []

    async def load(db, oid):
        return {**ORDER, "min_reputation": None, "stake_required": 5}

    async def gate(db, order, **kw):
        seen.append(kw)
        raise _Sentinel()
    monkeypatch.setattr(G, "_require_enabled", lambda: None)
    monkeypatch.setattr(G, "_load", load)
    monkeypatch.setattr(G._rb, "gate", _noop)
    monkeypatch.setattr(G._ep, "gate", _noop)
    monkeypatch.setattr(G, "_firm_bounty_gate", _noop)

    async def rep(db, did):
        return 5.0
    monkeypatch.setattr(G, "_agent_reputation", rep)
    from agentvault_registry.services import workflows as W
    monkeypatch.setattr(W, "gate", _noop)
    monkeypatch.setattr(SD, "gate", gate)
    agent = types.SimpleNamespace(did=WORKER_SAME)
    with pytest.raises(_Sentinel):                                   # the gate ran, and the stake leg (db.execute) did not
        await G.place_bid("gwo_x", G.BidIn(price=1.0, on_behalf_of_org_id="org-own"), agent, db=object())
    assert seen == [{"worker_did": WORKER_SAME, "org_id": "org-own", "stage": "bid"}]


@pytest.mark.asyncio
async def test_an_award_meets_the_gate_with_the_worker_and_the_org_before_the_claim(monkeypatch):
    seen = []

    class Rows:
        def __init__(self, row):
            self.row = row

        def mappings(self):
            return self

        def first(self):
            return self.row

    class DB:
        async def execute(self, stmt, params=None):
            sql = str(stmt)
            if "FROM guild_bids WHERE id" in sql:
                return Rows({"id": 7, "bidder_did": WORKER_SAME, "status": "open", "on_behalf_of_org_id": None,
                             "home_registry_url": None, "payee_did_hint": None, "eta_seconds": None, "price": 3})
            raise AssertionError("the claim ran after a refusal: " + sql[:60])

    async def load(db, oid):
        return {**ORDER, "poster_did": POSTER}

    async def gate(db, order, **kw):
        seen.append(kw)
        raise _Sentinel()
    monkeypatch.setattr(G, "_require_enabled", lambda: None)
    monkeypatch.setattr(G, "_load", load)
    from agentvault_registry.services import workflows as W
    monkeypatch.setattr(W, "gate", _noop)
    monkeypatch.setattr(SD, "gate", gate)
    with pytest.raises(_Sentinel):
        await G.award("gwo_x", G.AwardIn(bid_id=7), types.SimpleNamespace(did=POSTER), db=DB())
    assert seen == [{"worker_did": WORKER_SAME, "payee_did": None, "org_id": None, "stage": "award"}]
