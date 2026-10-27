"""§SECFIX D6-503 (2026-10-16): a firm bid needs the organization's consent unless the registry deliberately says not.

A firm bid (on_behalf_of_org_id) binds the organization: its treasury is the payee and its reputation carries the
work. The design gives that authority through the organization itself, an `org:` delegation grant carrying
`guild.bid_for_org` (the owner slice holds it); GUILD_ORG_BID_MODE=enforce asks for it. Measured on the wave-1 base
(7140a4a6) through this same request: the switch defaulted to `off`, and so did any value it did not know, so on a
registry that did not set it every member's agent bid in the firm's name with no consent at all. The default and an
unknown value are `enforce` now; `off` and `shadow` stay an operator's explicit choice.

POST /api/v1/guild/orders/{oid}/bids runs through FastAPI on the real router over real (SQLite) tables. Supplied: the
session, the bidding agent, the ledger/webhook/push side effects, and (for the control that HAS consent) the grant
read, whose `= ANY(permissions)` is Postgres syntax.
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry.routers import guild
from agentvault_registry.security import get_current_agent
from tests._sqlite_db import sqlite_db

POSTER, BIDDER = "did:theprotocol:guild-poster-0001", "did:theprotocol:org-o-member-agent-0002"
ORDER = "gwo_firmbid0001"


def _seed():
    db = sqlite_db(models.Developer, models.Organization, models.Agent, models.GuildWorkOrder, models.GuildBid)
    s = db.sync
    # its BIGINT key is no rowid alias in SQLite, so the events table is declared by hand
    s.execute(text("CREATE TABLE guild_order_events (id INTEGER PRIMARY KEY, order_id TEXT, seq INTEGER, "
                   "event_type TEXT, actor_did TEXT, payload TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
    s.add(models.Developer(id=1, name="d", email="d@example.org", hashed_password="x"))
    s.add(models.Organization(id="org-o", name="Org O", slug="o", owner_id=1, settings={},
                              treasury_agent_did="did:theprotocol:org-o-treasury"))
    db.agents = {}
    for n, (did, org) in enumerate(((POSTER, None), (BIDDER, "org-o")), start=1):
        db.agents[did] = models.Agent(id=n, did=did, client_id=f"c{n}", hashed_client_secret="x",
                                      creator_developer_id=1, organization_id=org, status="active")
        s.add(db.agents[did])
    s.add(models.GuildWorkOrder(id=ORDER, poster_did=POSTER, title="t", bounty=10, currency="SBXA", status="open"))
    s.commit()
    return db


@pytest.fixture()
def bid(monkeypatch):
    db = _seed()
    app = FastAPI()
    app.include_router(guild.router)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_agent] = lambda: db.agents[BIDDER]
    # pysqlite binds no Decimal through a raw-text statement, and the route reads a failed INSERT as a duplicate bid
    monkeypatch.setitem(sqlite3.adapters, (Decimal, sqlite3.PrepareProtocol), str)
    monkeypatch.setenv("GUILD_ENABLED", "true")
    monkeypatch.setenv("REPUTATION_BOND_MODE", "off")             # the provider gates this test is not about
    monkeypatch.setenv("ENFORCEMENT_PROPAGATION_MODE", "off")
    monkeypatch.delenv("GUILD_ORG_BID_MODE", raising=False)       # the registry did not set it
    monkeypatch.setattr(guild, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(guild, "_guild_webhook", lambda *a, **k: None)
    from agentvault_registry.background_tasks import push_notify

    async def _no_push(*_a, **_k):
        return None

    monkeypatch.setattr(push_notify, "notify_agent_owners", _no_push)

    async def place(**extra):
        body = {"price": 5, **extra}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.post(f"/api/v1/guild/orders/{ORDER}/bids", json=body)

    place.bids = lambda: db.sync.execute(text("SELECT COUNT(*) FROM guild_bids")).scalar()
    return place


async def test_by_default_a_member_cannot_bid_for_its_firm_without_the_firms_consent(bid):
    r = await bid(on_behalf_of_org_id="org-o")
    assert r.status_code == 403, r.text                    # the base placed the firm bid
    assert "guild.bid_for_org" in r.json()["detail"]
    assert bid.bids() == 0


async def test_an_unknown_mode_is_read_as_enforce(bid, monkeypatch):
    monkeypatch.setenv("GUILD_ORG_BID_MODE", "on")
    assert (await bid(on_behalf_of_org_id="org-o")).status_code == 403


async def test_control_with_the_firms_grant_the_member_bids_for_it(bid, monkeypatch):
    async def _granted(_db, agent_did, org_id):
        return (agent_did, org_id) == (BIDDER, "org-o")

    monkeypatch.setattr(guild, "_org_bid_grant_exists", _granted)
    r = await bid(on_behalf_of_org_id="org-o")
    assert r.status_code == 200, r.text
    assert r.json()["firm"] == "org-o" and bid.bids() == 1


async def test_control_an_operator_that_switches_the_gate_off_gets_what_it_asked_for(bid, monkeypatch):
    monkeypatch.setenv("GUILD_ORG_BID_MODE", "off")
    assert (await bid(on_behalf_of_org_id="org-o")).status_code == 200


async def test_control_an_individual_bid_needs_no_firm_consent(bid):
    r = await bid()
    assert r.status_code == 200, r.text
    assert r.json()["firm"] is None
