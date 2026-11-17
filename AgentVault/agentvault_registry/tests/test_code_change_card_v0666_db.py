"""V0666 D3, the change's room card and its state lines on a REAL Postgres (the order: "a real-Postgres test where the card or
a state line is written"; the card's lock is a Postgres advisory lock and the state line's once-only is a compare-and-set,
neither of which SQLite has). Four halves:

  1. the first refresh posts ONE `code.change.live` card (a rail-only card the chat's own validator takes) into the room,
     remembers its message and the state the room saw, and posts no state line (the card announces the change);
  2. a state change updates the same card in place and posts ONE line; a refresh with nothing new posts nothing;
  3. two refreshes racing on one state change post the line once;
  4. the migration (alembic/versions/0232_code_change_room.py) adds exactly the model's CHECK and its downgrade removes
     the three columns; the CHECK refuses a state that is no change's state.

Skipped unless CODE_DISTRIBUTIONS_TEST_DB names a throwaway database it may WIPE (postgresql+asyncpg://...). Skipped, never
silently passed. RED on 27775eacd: no code.change.live card, no services/code_change_card, no migration 0232.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import importlib.util
import os
import pathlib
import uuid

import pytest

DB = os.environ.get("CODE_DISTRIBUTIONS_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres database it may wipe: set CODE_DISTRIBUTIONS_TEST_DB. Skipped, never silently passed.",
                allow_module_level=True)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

MIGRATION = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0232_code_change_room.py"
CONSOLE = "agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/"


@pytest.fixture
async def maker(monkeypatch):
    from agentvault_registry.models import Base
    from agentvault_registry.services import chat_service as cs
    monkeypatch.setenv("CODE_DISTRIBUTIONS_ENABLED", "true")
    delivered = []
    monkeypatch.setattr(cs, "deliver", lambda *a, **k: delivered.append(a))
    engine = create_async_engine(DB)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    m = async_sessionmaker(engine, expire_on_commit=False)
    m.delivered = delivered
    yield m
    await engine.dispose()


async def _seed(maker):
    from agentvault_registry.models import (CodeChange, CodeDistribution, Conversation, Developer, Organization,
                                            OrganizationMember)
    async with maker() as s:
        owner = Developer(name="owner", email=f"o{uuid.uuid4().hex[:6]}@test.local", hashed_password="x", is_verified=True)
        s.add(owner)
        await s.flush()
        org = Organization(id=f"org-{uuid.uuid4().hex[:8]}", name="Lyceum Labs", slug=f"lyceum-{uuid.uuid4().hex[:6]}",
                           owner_id=owner.id)
        s.add(org)
        await s.flush()
        s.add(OrganizationMember(id=uuid.uuid4().hex, organization_id=org.id, developer_id=owner.id, role="owner",
                                 is_active=True))
        room = Conversation(id=str(uuid.uuid4()), kind="org", title="Lyceum builders", org_id=org.id,
                            created_by_ptype="developer", created_by_id=str(owner.id))
        s.add(room)
        dist = CodeDistribution(id="cdst_lyceum", organization_id=org.id, slug="lyceum", title="Lyceum's line",
                                base_release="V0666", open_paths=[CONSOLE + "views"], quorum_percent=50,
                                pass_rule="simple", state="active", created_by_developer_id=owner.id)
        s.add(dist)
        await s.flush()
        s.add(CodeChange(id="cc_room1", repository="theprotocol/AgentVault", paths=[CONSOLE + "views/A.vue"],
                         title="A seating chart", problem="p", mode="branch", branch="b", commit="a" * 40,
                         proposer_did="did:a:proposer", proposer_developer_id=owner.id, sensitive=False,
                         state="proposed", code_distribution_id=dist.id, announce_conversation_id=room.id))
        await s.commit()
        return room.id


def _ctx(maker):
    @contextlib.asynccontextmanager
    async def session():
        async with maker() as s:
            yield s
    return session


async def _messages(maker, room):
    async with maker() as s:
        return [dict(r) for r in (await s.execute(text(
            "SELECT id, kind, body, card FROM chat_messages WHERE conversation_id = :c ORDER BY seq"), {"c": room})).mappings()]


async def _row(maker):
    async with maker() as s:
        return dict((await s.execute(text("SELECT announce_message_id, announce_state, state FROM code_changes "
                                          "WHERE id = 'cc_room1'"))).mappings().first())


async def _set_state(maker, state, **extra):
    async with maker() as s:
        sets = ", ".join([f"{k} = :{k}" for k in ("state", *extra)])
        await s.execute(text(f"UPDATE code_changes SET {sets} WHERE id = 'cc_room1'"), {"state": state, **extra})
        await s.commit()


async def test_the_first_refresh_posts_one_card_and_no_line(maker):
    from agentvault_registry.services import chat_service as cs
    from agentvault_registry.services import code_change_card as ccc
    room = await _seed(maker)
    await ccc.refresh("cc_room1", session=_ctx(maker))
    msgs = await _messages(maker, room)
    assert [m["kind"] for m in msgs] == ["card"]
    card = msgs[0]["card"]
    assert card["type"] == "code.change.live" and card["data"]["state"] == "proposed"
    assert card["data"]["line"]["organization_name"] == "Lyceum Labs" and card["data"]["line"]["release_name"] == "V0666_lyceum"
    assert cs.validate_card(card, rail_author=True) is None and cs.validate_card(card) is not None
    r = await _row(maker)
    assert r["announce_message_id"] == msgs[0]["id"] and r["announce_state"] == "proposed"
    await ccc.refresh("cc_room1", session=_ctx(maker))
    assert len(await _messages(maker, room)) == 1, "a second refresh with nothing new posts nothing"


async def test_a_state_change_updates_the_card_in_place_and_posts_one_line(maker):
    from agentvault_registry.services import code_change_card as ccc
    room = await _seed(maker)
    await ccc.refresh("cc_room1", session=_ctx(maker))
    await _set_state(maker, "accepted")
    await ccc.refresh("cc_room1", session=_ctx(maker))
    msgs = await _messages(maker, room)
    assert [m["kind"] for m in msgs] == ["card", "text"]
    assert msgs[0]["card"]["data"]["state"] == "accepted", "the same card, updated in place"
    assert msgs[1]["body"] == "A seating chart: the signed checks passed; it waits for its reviews."
    assert (await _row(maker))["announce_state"] == "accepted"
    await ccc.refresh("cc_room1", session=_ctx(maker))
    assert len(await _messages(maker, room)) == 2
    await _set_state(maker, "withdrawn")
    await ccc.refresh("cc_room1", session=_ctx(maker))
    msgs = await _messages(maker, room)
    assert [m["kind"] for m in msgs] == ["card", "text", "text"] and msgs[2]["body"].endswith("withdrawn.")
    assert msgs[0]["card"]["data"]["state"] == "withdrawn"


async def test_two_refreshes_racing_on_one_change_post_its_line_once(maker):
    from agentvault_registry.services import code_change_card as ccc
    room = await _seed(maker)
    await ccc.refresh("cc_room1", session=_ctx(maker))
    await _set_state(maker, "accepted")
    await asyncio.gather(*[ccc.refresh("cc_room1", session=_ctx(maker)) for _ in range(4)])
    msgs = await _messages(maker, room)
    assert [m["kind"] for m in msgs] == ["card", "text"], [m["kind"] for m in msgs]


async def test_the_check_refuses_a_state_that_is_no_changes_state(maker):
    await _seed(maker)
    async with maker() as s:
        with pytest.raises(IntegrityError):
            await s.execute(text("UPDATE code_changes SET announce_state = 'almost' WHERE id = 'cc_room1'"))
            await s.commit()


async def test_the_migration_adds_exactly_the_models_check_and_its_downgrade_removes_the_columns(maker):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location("m0232", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    engine = create_async_engine(DB)

    async def checks(conn):
        rows = (await conn.execute(text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'code_changes'::regclass "
            "AND contype = 'c' AND conname LIKE 'ck_code_changes_announce%' ORDER BY conname"))).all()
        return {n: d for n, d in rows}

    def run(sync_conn, fn):
        with Operations.context(MigrationContext.configure(sync_conn)):
            fn()

    async with engine.begin() as conn:
        # a database built from the models (create_all, the fixture) carries the model's foreign key by ITS name: the
        # migration's downgrade must drop exactly that key (a name Postgres generated is a name the migration cannot
        # know: session-volume's find, room seq 4932). No renaming here: the models and the migration agree, or this fails.
        fk = (await conn.execute(text(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'code_changes'::regclass AND contype = 'f' "
            "AND pg_get_constraintdef(oid) LIKE '%(announce_conversation_id)%'"))).scalar()
        assert fk == "fk_code_changes_announce_conversation_id", fk
        from_models = await checks(conn)
        await conn.run_sync(run, mod.downgrade)
        for col in ("announce_conversation_id", "announce_message_id", "announce_state"):
            assert not (await conn.execute(text(
                "SELECT 1 FROM information_schema.columns WHERE table_name = 'code_changes' AND column_name = :c"),
                {"c": col})).first(), col
        assert await checks(conn) == {}
        await conn.run_sync(run, mod.upgrade)
        narrow = await checks(conn)
        # V0667 D4 (0237_code_change_upstream) widens this one check by two room states, and the MODEL carries the widened check: the chain 0232 then 0237's
        # swap is what the model says
        spec237 = importlib.util.spec_from_file_location("m0237", MIGRATION.parent / "0237_code_change_upstream.py")
        m237 = importlib.util.module_from_spec(spec237)
        spec237.loader.exec_module(m237)

        def widen():
            from alembic import op
            op.drop_constraint("ck_code_changes_announce_state", "code_changes", type_="check")
            op.create_check_constraint("ck_code_changes_announce_state", "code_changes", m237._check(m237.NEW))
        await conn.run_sync(run, widen)
        from_migration = await checks(conn)
    await engine.dispose()
    assert set(narrow) == set(mod.CHECKS) == set(from_models) == set(from_migration), (narrow, from_models)
    assert narrow != from_models and "'upstream'" not in narrow["ck_code_changes_announce_state"]       # 0232's own check is the narrow one
    assert from_migration == from_models


# --- V0667 D4: the room's card says when a merged change went upstream, and when it landed there (migration 0237 widens the room's state words) -------------------------

async def test_a_merged_change_that_goes_upstream_tells_its_room_once_when_proposed_and_once_when_it_landed(maker):
    from agentvault_registry.models import CodeChange
    from agentvault_registry.services import code_change_card as ccc
    room = await _seed(maker)
    await ccc.refresh("cc_room1", session=_ctx(maker))                                     # the card
    async with maker() as s:
        await s.execute(text("UPDATE code_changes SET state = 'merged', merged = CAST(:m AS jsonb) WHERE id = 'cc_room1'"),
                        {"m": '{"commit": "' + "a" * 40 + '", "into": "distribution/V0666_lyceum", "at": "2026-11-16T10:00:00+00:00"}'})
        await s.commit()
    await ccc.refresh("cc_room1", session=_ctx(maker))                                     # "merged into ..."
    lines = [m["body"] for m in await _messages(maker, room) if m["kind"] == "text"]
    assert len(lines) == 1 and "merged" in lines[0]
    async with maker() as s:                                                               # its decider proposes it upstream
        s.add(CodeChange(id="cc_up1", repository="theprotocol/AgentVault", paths=[CONSOLE + "views/A.vue"], title="A seating chart", problem="p", mode="branch",
                         branch="b", commit="a" * 40, proposer_did="did:a:owner", proposer_developer_id=(await s.execute(text("SELECT proposer_developer_id FROM code_changes WHERE id = 'cc_room1'"))).scalar_one(),
                         sensitive=False, state="proposed", upstream_of="cc_room1", provenance={"line": {"slug": "lyceum"}}))
        await s.commit()
    await ccc.refresh("cc_room1", session=_ctx(maker))
    assert (await _row(maker))["announce_state"] == "upstreaming"                          # a word the CHECK of 0237 allows
    lines = [m["body"] for m in await _messages(maker, room) if m["kind"] == "text"]
    assert len(lines) == 2 and "proposed upstream" in lines[1] and "cc_up1" in lines[1]
    await ccc.refresh("cc_room1", session=_ctx(maker))                                     # once: a second refresh says nothing more
    assert len([m for m in await _messages(maker, room) if m["kind"] == "text"]) == 2
    async with maker() as s:                                                               # it lands on the main code
        await s.execute(text("UPDATE code_changes SET state = 'merged' WHERE id = 'cc_up1'"))
        await s.execute(text("UPDATE code_changes SET upstream_since = CAST(:m AS jsonb) WHERE id = 'cc_room1'"),
                        {"m": '{"change_id": "cc_up1", "at": "2026-11-20T10:00:00+00:00"}'})
        await s.commit()
    await ccc.refresh("cc_room1", session=_ctx(maker))
    assert (await _row(maker))["announce_state"] == "upstream"
    lines = [m["body"] for m in await _messages(maker, room) if m["kind"] == "text"]
    assert len(lines) == 3 and "upstream since cc_up1" in lines[2]
