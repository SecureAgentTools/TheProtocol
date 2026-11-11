"""D6-817 (V0658 (c)): every statement the TEG sends names the TEG's release.

The TEG's asyncpg engine runs behind pgbouncer in transaction pooling, which hands a prepared statement to any client that
sends the same text: after a TEG migration that changes a column's type, every read of that table would fail with "cached
plan must not change result type" (the class the registry closed as D6-815). So every statement carries a leading comment
naming the TEG's release, from a constant in the TEG's source (core/release.TEG_RELEASE, bumped by the build), never from
an env value, on both of the TEG's engines.

RED on v0657/cut (e70fb58b2): there is no release constant, and a statement goes out as it was written.
"""
import ast
import pathlib

import importlib

from sqlalchemy import create_engine, event, text

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "teg_core_service"


def _mods():
    """The release constant and the tag module (imported per test, so a TEG without them fails each test, not the run)."""
    return (importlib.import_module("teg_core_service.core.release"),
            importlib.import_module("teg_core_service.database.release_sql_tag"))


def _sent(engine):
    """The statements `engine` sends to its driver, as the driver receives them."""
    seen = []

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)
    return seen


def test_the_release_is_a_constant_of_the_source():
    release, tag = _mods()
    assert isinstance(release.TEG_RELEASE, str) and release.TEG_RELEASE.strip() == release.TEG_RELEASE != ""
    assert "*/" not in release.TEG_RELEASE and "/*" not in release.TEG_RELEASE
    assert tag.RELEASE_SQL_TAG == f"/* {release.TEG_RELEASE} */ "


def test_no_environment_value_names_the_release():
    _mods()
    for f in (SRC / "core" / "release.py", SRC / "database" / "release_sql_tag.py"):
        tree = ast.parse(f.read_text())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
                {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not names & {"environ", "getenv", "os"}, (f.name, names & {"environ", "getenv", "os"})


def test_a_statement_carries_the_release_once():
    _, tag = _mods()
    engine = create_engine("sqlite://")
    tag.tag_engine_statements(engine)
    seen = _sent(engine)
    with engine.connect() as c:
        assert c.execute(text("SELECT 1")).scalar() == 1
        c.execute(text(f"{tag.RELEASE_SQL_TAG}SELECT 2"))
    assert seen == [f"{tag.RELEASE_SQL_TAG}SELECT 1", f"{tag.RELEASE_SQL_TAG}SELECT 2"], seen


def test_control_an_untagged_engine_sends_the_statement_as_written():
    engine = create_engine("sqlite://")
    seen = _sent(engine)
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    assert seen == ["SELECT 1"], seen


def test_both_of_the_tegs_engines_are_tagged():
    """In the source (whatever DATABASE_URL this process has), and on the engines this process built."""
    _mods()
    src = (SRC / "database" / "db_session.py").read_text()
    calls = [ast.unparse(c.args[0]) for c in ast.walk(ast.parse(src)) if isinstance(c, ast.Call)
             and getattr(c.func, "id", "") == "tag_engine_statements" and c.args]
    assert sorted(calls) == ["async_engine", "engine"], calls
    from teg_core_service.database import db_session as s
    assert event.contains(s.engine, "before_cursor_execute", s._RELEASE_TAG_LISTENER)
    if s.async_engine is not None:
        assert event.contains(s.async_engine.sync_engine, "before_cursor_execute", s._ASYNC_RELEASE_TAG_LISTENER)
