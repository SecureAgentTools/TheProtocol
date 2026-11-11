"""V0658 (t), session-code 2026-11-08: an organization's room wears its organization's hosted logo in the chat list (the
sidebar, on the desktop and in Pocket), as the thread's header has since V0657 (b) item 5. The maintainer's check (the
sessions' room seq 2156-2157): the logo showed next to the room's name at the top of the thread, and the room's entry in
the sidebar still showed the generic room avatar, because neither list read said anything about the organization.

What each test pins (the real functions over a recording fake database, as tests/test_orgs_v2_v0657.py does):
- the thread list (GET /chat/conversations) names each org room's organization with the block the thread's header
  reads (org_mark.room_org: id, slug, name, the hosted logo's path on this registry, listed), read in ONE statement for
  the page; a row that is not a room carries none;
- an org room whose organization hosts no logo says so (logo None): the console keeps today's avatar;
- a list whose organization read fails still answers, its rooms without a block (a list never fails over a logo);
- the rooms section (GET /chat/org-rooms) carries the same block on its rooms and on its organizations without a room;
- a list with no org room asks nothing more about any organization;
- one definition: the header's room_org and the lists' room_orgs answer the same block, one statement over the page's
  ids (compiled for PostgreSQL and SQLite), and on a real PostgreSQL (skipped unless ORGS_TEST_DB names a throwaway
  database);
- the statement is portable (the review of 5b12cf182): the thread's header reads it on every room, and the route tests
  read real SQLite rows (tests/_sqlite_db.py), where `= ANY(:ids)` is no function at all
  (tests/test_chat_board_v0652.py's thread read answered `no such function: ANY`). An expanding IN reads the same rows on
  both;
- an organization that is no longer active names no logo: the logo route serves only an active organization's
  (GET /organizations/{id}/logo answers 404), so a block naming one would cost a failed image per load.

RED on origin/v0657/cut 553347408: the list rows and the rooms section carry no organization block and room_orgs does
not exist. RED on 5b12cf182 (the first change): the real SQLite rows refuse the statement (no such function: ANY), the
statement compiles to `= ANY(...)` and not to an expanding IN, and on a real PostgreSQL the inactive organization's
block names its logo.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import uuid

import pytest

ORG = "4f3c1b2a-0000-4000-8000-000000000001"
ORG2 = "4f3c1b2a-0000-4000-8000-000000000002"
ORG3 = "4f3c1b2a-0000-4000-8000-000000000003"
SHA = "a" * 64
SHA3 = "c" * 64
NOW = dt.datetime(2026, 11, 8, 12, 0, tzinfo=dt.timezone.utc)
ORG_READ = "FROM organizations o LEFT JOIN organization_logos"


class _Result:
    def __init__(self, rows=()):
        self._rows = list(rows)
        self.rowcount = len(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def all(self):
        return list(self._rows)

    def scalar(self):
        r = self.first()
        return (r[0] if isinstance(r, (tuple, list)) else r) if r is not None else None

    def scalars(self):
        return self


class _Db:
    """Answers by the first handler whose needle is in the statement (an exception is raised); records every
    statement."""

    def __init__(self, *handlers):
        self.handlers = list(handlers)
        self.calls = []
        self.statements = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.calls.append((sql, dict(params or {})))
        self.statements.append(stmt)
        for needle, res in self.handlers:
            if needle in sql:
                if isinstance(res, Exception):
                    raise res
                return res
        return _Result([])

    def sql(self, needle):
        return [c for c in self.calls if needle in c[0]]


def _run(coro):
    return asyncio.run(coro)


def _dev(dev_id=6):
    from agentvault_registry.services import chat_service as cs
    return cs.Actor("developer", developer_id=dev_id, display_name="maintainer")


def _conv(cid, kind, org_id=None, org_name=None, title=None, pair=None):
    """A row of the list's statement, in its column order (c.id ... org_name)."""
    return (cid, kind, title, 4, NOW, "the last words", pair, None, NOW, 1, 2, False,
            "open" if kind == "org" else None, None, org_id, None, "developer", "6", None, org_name)


def _block(org_id, slug, name, sha, listed):
    return {"id": org_id, "slug": slug, "name": name,
            "logo": (f"/api/v1/organizations/{org_id}/logo?v={sha[:12]}" if sha else None), "listed": listed}


def _list_db(org_rows=None, org_read=None):
    rows = [_conv("c-room", "org", ORG, "TheProtocol Sessions", title="Old Name"),
            _conv("c-plain", "org", ORG2, "Plain Org", title="Plain Org"),
            _conv("c-dm", "dm", pair="dm|dev:6|dev:9")]
    return _Db(("FROM conversations c JOIN conversation_participants p", _Result(rows)),
               ("FROM conversation_participants", _Result([])),
               ("SELECT did FROM agents WHERE creator_developer_id", _Result([])),
               (ORG_READ, org_read if org_read is not None else _Result(org_rows or [
                   (ORG, "sessions", "TheProtocol Sessions", SHA, {"public_listing": True}),
                   (ORG2, "plain", "Plain Org", None, {})])))


# ── the thread list ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_list_names_each_org_rooms_organization_with_its_hosted_logo():
    from agentvault_registry.services import chat_service as cs
    db = _list_db()
    out = _run(cs.list_conversations(db, _dev()))
    rows = {c["id"]: c for c in out["conversations"]}
    assert rows["c-room"]["org"] == _block(ORG, "sessions", "TheProtocol Sessions", SHA, True), \
        "the room's entry carries the block the thread's header reads, its logo the path this registry hosts"
    assert rows["c-room"]["title"] == "TheProtocol Sessions", "the room is still named by its live name"
    reads = db.sql(ORG_READ)
    assert len(reads) == 1, "one statement for the page's organizations, never one per row"
    assert reads[0][1] == {"ids": [ORG, ORG2]}


def test_an_org_room_whose_organization_hosts_no_logo_says_so_and_a_thread_carries_none():
    from agentvault_registry.services import chat_service as cs
    out = _run(cs.list_conversations(_list_db(), _dev()))
    rows = {c["id"]: c for c in out["conversations"]}
    assert rows["c-plain"]["org"] == _block(ORG2, "plain", "Plain Org", None, False), \
        "no hosted logo: the block says None, and the console keeps today's room avatar"
    assert "org" in rows["c-dm"] and rows["c-dm"]["org"] is None, "a thread that is not a room names no organization"


def test_a_list_whose_organization_read_fails_still_answers():
    from agentvault_registry.services import chat_service as cs
    out = _run(cs.list_conversations(_list_db(org_read=RuntimeError("relation organization_logos is unreadable")),
                                     _dev()))
    rows = {c["id"]: c for c in out["conversations"]}
    assert set(rows) == {"c-room", "c-plain", "c-dm"}, "the inbox answers whole"
    assert rows["c-room"]["org"] is None and rows["c-plain"]["org"] is None, "its rooms keep today's avatar"


def test_a_list_with_no_org_room_asks_nothing_about_an_organization():
    from agentvault_registry.services import chat_service as cs
    db = _Db(("FROM conversations c JOIN conversation_participants p", _Result([_conv("c-dm", "dm", pair="dm|dev:6|dev:9")])),
             ("FROM conversation_participants", _Result([])),
             ("SELECT did FROM agents WHERE creator_developer_id", _Result([])))
    out = _run(cs.list_conversations(db, _dev()))
    assert [c["id"] for c in out["conversations"]] == ["c-dm"]
    assert db.sql(ORG_READ) == [], "no room on the page: no organization read"


# ── the rooms section ───────────────────────────────────────────────────────────────────────────────────────────────
def test_the_rooms_section_names_each_organization_with_its_hosted_logo():
    from agentvault_registry.services import chat_service as cs
    member_rows = [
        # o.id, o.name, om.role, c.id, c.mode, c.topic, c.last_message_at, c.last_preview, chat_enabled, policy, unread
        (ORG, "TheProtocol Sessions", "owner", None, None, None, None, None, True, "owner_admin", 0),
        (ORG3, "Dark Org", "owner", None, None, None, None, None, False, "owner_admin", 0),
    ]
    db = _Db(("FROM organization_members om", _Result(member_rows)),
             (ORG_READ, _Result([(ORG, "sessions", "TheProtocol Sessions", SHA, {"public_listing": True}),
                                 (ORG3, "dark", "Dark Org", SHA3, None)])))
    out = _run(cs.list_org_rooms(db, _dev()))
    assert out["rooms"][0]["org"] == _block(ORG, "sessions", "TheProtocol Sessions", SHA, True), \
        "a room not opened yet wears its organization's logo in the section"
    assert out["enableable"][0]["org"] == _block(ORG3, "dark", "Dark Org", SHA3, False), \
        "an organization without a room is shown by its logo too"
    assert len(db.sql(ORG_READ)) == 1 and db.sql(ORG_READ)[0][1] == {"ids": [ORG, ORG3]}


def test_the_rooms_section_answers_when_the_organization_read_fails():
    from agentvault_registry.services import chat_service as cs
    member_rows = [(ORG, "TheProtocol Sessions", "owner", "c-room", "open", None, None, None, True, "owner_admin", 0)]
    db = _Db(("FROM organization_members om", _Result(member_rows)), (ORG_READ, RuntimeError("unreadable")))
    out = _run(cs.list_org_rooms(db, _dev()))
    assert out["rooms"][0]["org_id"] == ORG and out["rooms"][0]["org"] is None


# ── one definition: the header's block and the lists' ──────────────────────────────────────────────────────────────
def test_the_header_and_the_lists_read_one_block_in_one_statement():
    from sqlalchemy.dialects import postgresql, sqlite
    from agentvault_registry.services import org_mark
    row = (ORG, "sessions", "TheProtocol Sessions", SHA, '{"public_listing": true}')
    one = _run(org_mark.room_org(_Db((ORG_READ, _Result([row]))), ORG))
    db = _Db((ORG_READ, _Result([row])))
    many = _run(org_mark.room_orgs(db, [ORG, None, ORG, ""]))
    assert many == {ORG: one} and one == _block(ORG, "sessions", "TheProtocol Sessions", SHA, True)
    assert db.calls[0][1] == {"ids": [ORG]}, "the page's ids, once each"
    assert _run(org_mark.room_orgs(_Db(), [])) == {} and _run(org_mark.room_org(_Db(), "")) is None
    # the statement room_orgs EXECUTES, compiled for both databases the registry's code meets
    stmt = db.statements[0]
    for dialect in (postgresql.dialect(), sqlite.dialect()):
        sql = " ".join(str(stmt.compile(dialect=dialect)).split())
        assert "WHERE o.id IN (__[POSTCOMPILE_ids])" in sql, \
            f"{dialect.name}: one statement over the page's ids, an expanding IN that both databases read"
        assert "ANY(" not in sql, f"{dialect.name}: never Postgres' ANY, which SQLite has no function for"
        assert "LEFT JOIN organization_logos l ON l.organization_id = o.id AND o.is_active = TRUE" in sql, \
            f"{dialect.name}: a room without a logo is still named, and only an active organization's logo is"


def test_the_header_and_the_lists_read_real_sqlite_rows():
    """The rows the route tests read (tests/_sqlite_db.py): the thread's header (room_org) and the lists (room_orgs) on a
    real database other than PostgreSQL, so the statement cannot lean on Postgres-only SQL."""
    from agentvault_registry import models
    from agentvault_registry.services import org_mark
    from tests._sqlite_db import sqlite_db
    db = sqlite_db(models.Developer, models.Organization, models.OrganizationLogo)
    s = db.sync
    s.add(models.Developer(id=6, name="maintainer", email="d6@example.test", hashed_password="x"))
    s.flush()
    s.add_all([
        models.Organization(id=ORG, name="TheProtocol Sessions", slug="sessions", owner_id=6, is_active=True,
                            settings={"public_listing": True}),
        models.Organization(id=ORG2, name="Plain Org", slug="plain", owner_id=6, is_active=True, settings={}),
        models.Organization(id=ORG3, name="Gone Org", slug="gone", owner_id=6, is_active=False, settings=None),
    ])
    s.flush()
    s.add_all([models.OrganizationLogo(organization_id=o, content_type="image/png", data=b"\x89PNG\r\n\x1a\n", sha256=d,
                                       size=8) for o, d in ((ORG, SHA), (ORG3, SHA3))])
    s.commit()
    many = _run(org_mark.room_orgs(db, [ORG, ORG2, ORG3, "4f3c1b2a-0000-4000-8000-00000000000f", None]))
    assert set(many) == {ORG, ORG2, ORG3}, "an id this registry does not hold answers nothing"
    assert many[ORG] == _block(ORG, "sessions", "TheProtocol Sessions", SHA, True)
    assert many[ORG2] == _block(ORG2, "plain", "Plain Org", None, False), "no hosted logo: logo None"
    assert many[ORG3] == _block(ORG3, "gone", "Gone Org", None, False), \
        "an organization no longer active names no logo: its logo route answers 404"
    assert _run(org_mark.room_org(db, ORG)) == many[ORG], "the header's read is the lists' read"
    assert _run(org_mark.room_org(db, ORG3)) == many[ORG3]


@pytest.mark.skipif(not os.environ.get("ORGS_TEST_DB"),
                    reason="needs a REAL Postgres database it may WIPE: set ORGS_TEST_DB (postgresql+asyncpg://...)")
def test_room_orgs_on_a_real_postgres():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from agentvault_registry.models import Base, Developer, Organization, OrganizationLogo
    from agentvault_registry.services import org_mark

    async def go():
        engine = create_async_engine(os.environ["ORGS_TEST_DB"])
        try:
            async with engine.begin() as conn:
                await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
                await conn.execute(text("CREATE SCHEMA public"))
                await conn.run_sync(Base.metadata.create_all)
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as s:
                dev = Developer(name=f"owner-{uuid.uuid4().hex[:8]}", email=f"o{uuid.uuid4().hex[:6]}@test.local",
                                hashed_password="x", is_verified=True)
                s.add(dev)
                await s.flush()
                a = Organization(id=str(uuid.uuid4()), name="TheProtocol Sessions", slug=f"s-{uuid.uuid4().hex[:6]}",
                                 owner_id=dev.id, is_active=True, settings={"public_listing": True})
                b = Organization(id=str(uuid.uuid4()), name="Plain Org", slug=f"p-{uuid.uuid4().hex[:6]}",
                                 owner_id=dev.id, is_active=True, settings={})
                c = Organization(id=str(uuid.uuid4()), name="Gone Org", slug=f"g-{uuid.uuid4().hex[:6]}",
                                 owner_id=dev.id, is_active=False, settings=None)
                s.add_all([a, b, c])
                await s.flush()
                for o, d in ((a, SHA), (c, SHA3)):
                    s.add(OrganizationLogo(organization_id=o.id, content_type="image/png", data=b"\x89PNG\r\n\x1a\n",
                                           sha256=d, size=8))
                await s.commit()
            async with maker() as s:
                many = await org_mark.room_orgs(s, [a.id, b.id, c.id, str(uuid.uuid4())])
                one = await org_mark.room_org(s, a.id)
                gone = await org_mark.room_org(s, c.id)
            return a, b, c, many, one, gone
        finally:
            await engine.dispose()

    a, b, c, many, one, gone = _run(go())
    assert set(many) == {a.id, b.id, c.id}, "an unknown id answers nothing"
    assert many[a.id] == one == _block(a.id, a.slug, "TheProtocol Sessions", SHA, True)
    assert many[b.id] == _block(b.id, b.slug, "Plain Org", None, False)
    assert many[c.id] == gone == _block(c.id, c.slug, "Gone Org", None, False), \
        "an organization no longer active is still named, and names no logo (its logo route answers 404)"
