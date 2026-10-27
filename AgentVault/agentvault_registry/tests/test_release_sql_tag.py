"""D6-815 (2026-10-24) — every statement the registry sends names its release (core/release_sql_tag.py).

Behind pgbouncer (transaction pooling, server-side prepared statements shared by their text), a migration that changes a
column's type leaves the previous release's prepared statements planned for the old type, and Postgres refuses to re-plan
them. Measured on a throwaway database behind pgbouncer 1.25.2: a recreated registry sending the old text failed 6 of 6
reads after 0195's widening; the new release's text passed 12 of 12. These pin the comment and its wiring.
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/t")
os.environ.setdefault("API_KEY_SECRET", "test-only-secret-value-0123456789abcdef")

import sqlalchemy as sa
from sqlalchemy import event

from agentvault_registry.core import release_sql_tag as rst
from agentvault_registry.core.registry_identity import BUNDLED_IMAGE_TAG


def _sent(eng):
    seen = []
    event.listen(eng, "after_cursor_execute", lambda conn, cur, st, p, ctx, many: seen.append(st))
    return seen


def test_the_comment_names_this_images_release():
    assert rst.RELEASE_SQL_TAG == f"/* {BUNDLED_IMAGE_TAG} */ "


def test_the_comment_goes_in_front_once():
    s = "SELECT contracts.id FROM contracts"
    once = rst.tag_with_release(s)
    assert once == rst.RELEASE_SQL_TAG + s and rst.tag_with_release(once) == once


def test_two_releases_send_two_texts(monkeypatch):
    """The point of it: the next release's same query is another text, which pgbouncer prepares afresh."""
    s = "SELECT contracts.origin_ref FROM contracts"
    this = rst.tag_with_release(s)
    monkeypatch.setattr(rst, "RELEASE_SQL_TAG", "/* TheProtocolReleaseV9999 */ ")
    assert rst.tag_with_release(s) != this and rst.tag_with_release(s).endswith(s)


def test_every_statement_a_tagged_engine_sends_carries_it():
    eng = sa.create_engine("sqlite://")
    rst.tag_engine_statements(eng)
    seen = _sent(eng)
    with eng.connect() as c:
        assert c.execute(sa.text("SELECT 1")).scalar() == 1
        c.execute(sa.text("CREATE TABLE t (x INTEGER)"))
        c.execute(sa.text("INSERT INTO t (x) VALUES (:x)"), [{"x": 1}, {"x": 2}])
        assert c.execute(sa.text("SELECT count(*) FROM t")).scalar() == 2
    assert len(seen) == 4 and all(st.startswith(rst.RELEASE_SQL_TAG) for st in seen), seen


def test_an_untagged_engine_sends_the_bare_text():
    """Control: without the listener a statement goes out as written, so the test above can fail."""
    eng = sa.create_engine("sqlite://")
    seen = _sent(eng)
    with eng.connect() as c:
        c.execute(sa.text("SELECT 1"))
    assert seen == ["SELECT 1"]


def test_the_registrys_engine_is_tagged():
    from agentvault_registry import database
    assert event.contains(database.engine.sync_engine, "before_cursor_execute", database._RELEASE_TAG_LISTENER)
