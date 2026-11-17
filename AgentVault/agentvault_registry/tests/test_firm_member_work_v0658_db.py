"""V0658 (v), item 6, on a REAL Postgres: the member agents' own settled work (services/track_record.member_agents_work)
and the Firms strip's answer (routers/organizations.discover_firms) over seeded rows, so the statement the unit test
pins by its text is also the one Postgres runs and the numbers are the right ones:

  organization A (listed): agents a1 and a2 active, a3 suspended, a4 active but hiding its organization (show_org off).
  organization B (listed): no agent.  organization C (open books, NOT listed): agent c1 active.
  a1: 2 settled as itself, 1 settled AS firm A, 1 settled as firm B, 1 open. Its travel credentials: 2 verified from a
      host that predates the payee fields, 1 verified naming no payee, 1 verified paying a1 itself, 1 not verified,
      and 2 verified signed for a firm (AS firm A, AS firm B: the firm's work, never a1's own).
  a2: 1 settled as itself.  a3 (suspended): 5.  a4 (hidden): 7, and 1 verified travel credential.  c1: 3.
  A non-member: 3 settled as itself.
  => A's agents on their own: a1 2 + 4 travel, a2 1 = 7 jobs; A's own count (as the firm): 1; B: 0 (listed, none);
     C: no line at all (its members are not stated in public).

V0666 (the order gwo_5dee4f33eba094f0c185ac9b): the counts follow the organization each agent belonged to WHEN THE ORDER WAS
AWARDED (guild_work_orders.worker_org_at_award, poster_org_at_award), and carry the poster side:
  a5 belonged to A at the award and has left: its 2 settled jobs stay A's. a6 joined A after its 4 were awarded: not A's.
  Posted: a1 3 settled (an open one is not counted), a4 hides its organization (2, not counted), a5 1 (left, counted), a6 1
  (joined after, not counted), the firm's own treasury 1 (the firm's `commissioned`, never its agents').
  => A's agents: 9 jobs delivered, 4 commissioned; A as the firm: 1 delivered, 1 commissioned.

The review of 4914af776: before it, the remote firm credentials, the hidden agent and the unlisted organization were all
counted. RED on 4914af776: A read 7 + 2 + 8 = 17 jobs, C carried a line, and the answer carried `agents`.

Skipped unless FIRMS_TEST_DB names a throwaway database it may WIPE (postgresql+asyncpg://...). Skipped, never silently
passed. RED on 553347408 (origin/v0657/cut): member_agents_work does not exist.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid

import pytest

DB = os.environ.get("FIRMS_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres database it may wipe: set FIRMS_TEST_DB. Skipped, never silently passed.",
                allow_module_level=True)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

# the table a migration creates (0118_guild_travel_credentials); it has no ORM model, so create_all leaves it out
TRAVEL_DDL = """
    CREATE TABLE IF NOT EXISTS guild_travel_credentials (
        id            VARCHAR(40) PRIMARY KEY,
        order_id      VARCHAR(40) NOT NULL,
        host_registry VARCHAR(300) NOT NULL,
        worker_did    VARCHAR(120) NOT NULL,
        poster_did    VARCHAR(120) NOT NULL,
        stars         INTEGER,
        bounty        NUMERIC(30, 10),
        currency      VARCHAR(12),
        bundle        JSONB NOT NULL,
        pubkey_id     VARCHAR(32),
        verified      BOOLEAN NOT NULL DEFAULT FALSE,
        received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uix_gtc_host_order UNIQUE (host_registry, order_id)
    )
"""


@pytest.fixture
async def maker():
    from agentvault_registry.models import Base
    engine = create_async_engine(DB)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(TRAVEL_DDL))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


TREASURY_A = "did:theprotocol:eu.test:treasury-a"
TREASURY_B = "did:theprotocol:eu.test:treasury-b"


async def _seed(maker):
    from agentvault_registry.models import Agent, Developer, GuildWorkOrder, Organization
    now = dt.datetime.now(dt.timezone.utc)
    async with maker() as s:
        dev = Developer(name=f"owner-{uuid.uuid4().hex[:8]}", email=f"o{uuid.uuid4().hex[:6]}@test.local",
                        hashed_password="x", is_verified=True)
        s.add(dev)
        await s.flush()
        a = Organization(id=str(uuid.uuid4()), name="TheProtocol Sessions", slug=f"sessions-{uuid.uuid4().hex[:6]}",
                         owner_id=dev.id, is_active=True, treasury_agent_did=TREASURY_A,
                         settings={"public_transparency_opt_in": True, "public_listing": True})
        b = Organization(id=str(uuid.uuid4()), name="Reach Limited", slug=f"reach-{uuid.uuid4().hex[:6]}",
                         owner_id=dev.id, is_active=True,
                         settings={"public_transparency_opt_in": True, "public_listing": True})
        c = Organization(id=str(uuid.uuid4()), name="Quiet Works", slug=f"quiet-{uuid.uuid4().hex[:6]}",
                         owner_id=dev.id, is_active=True, settings={"public_transparency_opt_in": True})
        s.add_all([a, b, c])
        await s.flush()

        def agent(org, status="active", show_org=True):
            did = f"did:theprotocol:eu.test:{uuid.uuid4()}"
            s.add(Agent(did=did, client_id=f"c-{uuid.uuid4().hex[:10]}", hashed_client_secret="x",
                        creator_developer_id=dev.id, status=status, enforcement_status="active",
                        organization_id=org, show_org=show_org))
            return did
        a1, a2, a3 = agent(a.id), agent(a.id), agent(a.id, status="suspended")
        a4 = agent(a.id, show_org=False)
        c1 = agent(c.id)
        stranger = agent(None)
        a5 = agent(None)          # V0666: belonged to A when its orders were awarded, has left since
        a6 = agent(a.id)          # V0666: joined A after its orders were awarded
        await s.flush()
        org_of = {a1: a.id, a2: a.id, a3: a.id, a4: a.id, c1: c.id, a5: a.id}   # at award; a6 and the stranger: none

        def order(worker, status="settled", payee_org=None, poster=None, poster_org=None, worker_org="same"):
            s.add(GuildWorkOrder(id=f"gwo_{uuid.uuid4().hex[:20]}", poster_did=poster or "did:theprotocol:eu.test:poster",
                                 title="t", bounty=1, currency="ECU", status=status, worker_did=worker,
                                 payee_org_id=payee_org, settled_at=now if status == "settled" else None,
                                 worker_org_at_award=org_of.get(worker) if worker_org == "same" else worker_org,
                                 poster_org_at_award=poster_org))
        order(a1), order(a1), order(a1, payee_org=a.id), order(a1, payee_org=b.id), order(a1, status="open")
        order(a2)
        for _ in range(5):
            order(a3)
        for _ in range(7):
            order(a4)
        for _ in range(3):
            order(c1)
        for _ in range(3):
            order(stranger)
        for _ in range(2):
            order(a5)             # left since: still A's by the award
        for _ in range(4):
            order(a6)             # joined after: nobody's by the award
        # the other side: orders the organization's agents POSTED (the worker is outside every organization)
        for _ in range(3):
            order(stranger, poster=a1, poster_org=a.id)
        order(stranger, poster=a1, poster_org=a.id, status="open")     # not settled: not counted
        for _ in range(2):
            order(stranger, poster=a4, poster_org=a.id)                # hiding its organization: not counted
        order(stranger, poster=a5, poster_org=a.id)                    # left since: counted
        order(stranger, poster=a6)                                     # joined after: not counted
        order(stranger, poster=TREASURY_A)                             # the firm's own treasury: the firm's, not its agents'
        await s.flush()

        def travel(worker, bundle, verified=True):
            return s.execute(text(
                "INSERT INTO guild_travel_credentials (id, order_id, host_registry, worker_did, poster_did, bundle, "
                "verified) VALUES (:i, :o, 'https://asia.example', :w, 'did:x:poster', CAST(:b AS JSONB), :v)"),
                {"i": uuid.uuid4().hex[:20], "o": uuid.uuid4().hex[:20], "w": worker, "b": json.dumps(bundle),
                 "v": verified})
        # the agent's own work on another registry: a host that predates the payee fields (twice), a claim naming no
        # payee, a claim paying the worker itself
        await travel(a1, {})
        await travel(a1, {})
        await travel(a1, {"payee_org_id": None, "payee_did": None})
        await travel(a1, {"payee_org_id": None, "payee_did": a1})
        await travel(a1, {}, verified=False)
        # work a1 did AS a firm through the firm-remote bid: the host signed the payee firm and its treasury
        await travel(a1, {"payee_org_id": a.id, "payee_did": TREASURY_A})
        await travel(a1, {"payee_org_id": b.id, "payee_did": TREASURY_B})
        # the hidden agent's own work elsewhere
        await travel(a4, {})
        await s.commit()
        return a.id, b.id, c.id


async def test_the_agents_own_work_is_counted_and_never_the_firms(maker):
    from agentvault_registry.services import track_record as tr
    a, b, c = await _seed(maker)
    async with maker() as s:
        out = await tr.member_agents_work(s, [a, b, c])
    assert out == {a: {"jobs": 9, "commissioned": 4}}, out


async def test_the_firms_strip_answers_both_counts_apart(maker):
    from agentvault_registry.routers import organizations as r
    a, b, c = await _seed(maker)
    async with maker() as s:
        out = await r.discover_firms(limit=12, db=s)
    by = {f["org_id"]: f for f in out["firms"]}
    assert by[a]["listed"] is True and by[a]["verified_jobs"] == 1, "the firm's own count: the one job AS the firm"
    assert by[a]["commissioned"] == 1, "the firm's own treasury posted one: the firm's count, never its agents'"
    assert by[a]["member_work"] == {"jobs": 9, "commissioned": 4}
    assert by[b]["verified_jobs"] == 1 and by[b]["member_work"] == {"jobs": 0, "commissioned": 0}, "listed, its agents have none"
    assert by[c]["listed"] is False and "member_work" not in by[c], "an unlisted firm's members are not stated"


async def test_the_listed_organizations_answer_both_counts_apart(maker, monkeypatch):
    """#/firms's list: A and B are listed, C is not (so C is not named at all); each one's own count and its agents'."""
    from agentvault_registry.routers import organizations as r
    monkeypatch.setattr("agentvault_registry.core.public_url.public_ui_origin", lambda: "https://eu.example")
    monkeypatch.setattr("agentvault_registry.core.public_url.public_ui_url_static", lambda: "https://eu.example/ui")
    a, b, c = await _seed(maker)
    async with maker() as s:
        out = await r.list_listed_organizations(limit=200, offset=0, db=s)
    by = {o["id"]: o for o in out["organizations"]}
    assert set(by) == {a, b}, "only the listed organizations are named"
    assert by[a]["settled_work"] == 1 and by[a]["member_work"] == {"jobs": 9, "commissioned": 4}
    assert by[b]["settled_work"] == 1 and by[b]["member_work"] == {"jobs": 0, "commissioned": 0}


async def test_the_track_record_carries_the_line_for_a_listed_organization_only(maker):
    from agentvault_registry.routers import organizations as r
    a, b, c = await _seed(maker)
    async with maker() as s:
        rec_a = await r.get_org_track_record(a, db=s)
        rec_c = await r.get_org_track_record(c, db=s)
    assert rec_a["verified_jobs"] == 1 and rec_a["member_work"] == {"jobs": 9, "commissioned": 4}
    assert rec_c["verified_jobs"] == 0 and "member_work" not in rec_c
