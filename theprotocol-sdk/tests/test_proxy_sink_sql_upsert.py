"""V0664 (Migrate a system, M1, gwo_eb42941e8b374e6db2bbbd01): the writer `sql_upsert`, a sink that writes each mapped record into a
table of the NEW system by key.

What it promises, and how each promise is held here:
* the same key delivered twice writes once; a second record for the same row updates it (or leaves it, on_conflict: skip);
* the oldest pre-image of each key (the pre-migration row, or none) is kept once, in the proxy's state, BEFORE the write
  commits, and restore_preimages puts it back newest first (a missing row is deleted again), idempotently;
* a refusal names the column and NEVER the value (the driver's own text carries values, so it is never repeated);
* values are parameters, names are checked and quoted (the sqlpoll rules);
* a dry run writes nothing; a literal password is refused at load.
SQLite runs for real. PostgreSQL, MySQL and SQL Server: the statement text is pinned, the error classification is exercised
on stand-in exceptions, and a real-server test runs when its address is in the environment (TP_PROXY_TEST_<ENGINE>, as
test_proxy_source_sqlpoll_engines does) and is skipped, saying why, when not.
RED on stack master ed708438: theprotocol.proxy.sinks does not exist.
"""
from __future__ import annotations

import json
import os
import sqlite3

import pytest

from theprotocol.proxy.plugins import Event, PluginError, Refused, Retry
from theprotocol.proxy.testing import FakeContext, check_sink

SECRET_VALUE = "Zq-7731-NOT-A-NUMBER"


@pytest.fixture(autouse=True)
def fake_plugins(monkeypatch):
    """The spec tests below name a source and need one: the shared fakes (proxy_fake) stand in."""
    from theprotocol.proxy import plugins
    monkeypatch.setitem(plugins.BUILTINS["source"], "list_source", "proxy_fake:ListSource")
    monkeypatch.setitem(plugins.BUILTINS["sink"], "list_sink", "proxy_fake:ListSink")


def _ev(i=1, **data):
    return Event(event_id=f"evt-{i}", event_type="migration.row", aggregate_id="customers", data=data)


def _db(tmp_path, ddl="CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT)"):
    path = tmp_path / "target.db"
    c = sqlite3.connect(path)
    c.execute(ddl)
    c.commit()
    c.close()
    return path


def _rows(path, table="customers", order="id"):
    c = sqlite3.connect(path)
    try:
        return [tuple(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY {order}")]
    finally:
        c.close()


def _sink(path, ctx=None, **cfg):
    from theprotocol.proxy.sinks.sql_upsert import SqlUpsertSink
    base = {"engine": "sqlite", "path": str(path), "table": "customers", "key": ["id"]}
    base.update(cfg)
    ctx = ctx or FakeContext()
    return SqlUpsertSink(base, ctx), ctx


async def _run(sink, i, key=None, **data):
    return await sink.deliver(_ev(i, **data), key=key or f"k-{i}", dry_run=False)


# ── the contract, and the names ───────────────────────────────────────────────────────────────────────────────

async def test_it_keeps_the_sink_contract_and_is_a_builtin(tmp_path):
    from theprotocol.proxy import plugins
    from theprotocol.proxy.sinks.sql_upsert import SqlUpsertSink
    assert plugins.BUILTINS["sink"]["sql_upsert"] == "theprotocol.proxy.sinks.sql_upsert:SqlUpsertSink"
    assert plugins.load("sink", "sql_upsert") is SqlUpsertSink
    path = _db(tmp_path)
    out = await check_sink(SqlUpsertSink, {"engine": "sqlite", "path": str(path), "table": "customers", "key": ["id"]},
                           _ev(1, id=1, name="Ada", email="ada@example.org"),
                           delivered=lambda: _rows(path))
    assert out.status == "done" and out.reference == "[1]"


@pytest.mark.parametrize("cfg, word", [
    ({"table": "customers; DROP TABLE x"}, "table"),
    ({"key": ["id\"; --"]}, "key"),
    ({"columns": ["name", "e mail'"]}, "column"),
    ({"engine": "oracle"}, "engine"),
    ({"key": []}, "key"),
    ({"on_conflict": "merge"}, "on_conflict"),
])
def test_a_name_that_is_not_a_name_is_refused_when_the_sink_is_built(tmp_path, cfg, word):
    with pytest.raises(PluginError) as e:
        _sink(tmp_path / "x.db", **cfg)
    assert word in str(e.value)


def test_a_literal_password_is_refused_at_load_and_a_reference_loads(tmp_path):
    import proxy_fake as F
    from theprotocol.proxy.spec import SpecError, parse
    sink = {"type": "sql_upsert", "config": {"engine": "postgresql", "host": "db.internal", "database": "crm", "user": "tp",
                                              "password": "hunter2-written-out", "table": "public.customers", "key": ["id"]}}
    with pytest.raises(SpecError) as e:
        parse(F.spec_doc(tmp_path, sinks={"crm": sink}), base=tmp_path)
    assert "sinks.crm.config.password" in e.value.problems
    sink["config"]["password"] = "env:CRM_PASSWORD"
    assert parse(F.spec_doc(tmp_path, sinks={"crm": sink}), base=tmp_path) is not None


# ── the statements, one per engine ────────────────────────────────────────────────────────────────────────────

STATEMENTS = {
    "postgresql": ('INSERT INTO "public"."customers" ("id", "name") VALUES (%s, %s) ON CONFLICT ("id") DO UPDATE SET '
                   '"name" = EXCLUDED."name"'),
    "sqlite": ('INSERT INTO "customers" ("id", "name") VALUES (?, ?) ON CONFLICT ("id") DO UPDATE SET '
               '"name" = excluded."name"'),
    "mysql": ("INSERT INTO `customers` (`id`, `name`) VALUES (%s, %s) ON DUPLICATE KEY UPDATE `name` = VALUES(`name`)"),
    "sqlserver": ("MERGE INTO [customers] WITH (HOLDLOCK) AS tgt USING (VALUES (%s, %s)) AS src ([id], [name]) "
                  "ON tgt.[id] = src.[id] WHEN MATCHED THEN UPDATE SET tgt.[name] = src.[name] WHEN NOT MATCHED THEN "
                  "INSERT ([id], [name]) VALUES (src.[id], src.[name]);"),
}


@pytest.mark.parametrize("engine", sorted(STATEMENTS))
def test_each_engine_has_its_own_upsert_statement_pinned(engine):
    from theprotocol.proxy.sinks.sql_upsert import upsert_statement
    table = ["public", "customers"] if engine == "postgresql" else ["customers"]
    assert upsert_statement(engine, table, ["id", "name"], ["id"], "update") == STATEMENTS[engine]


@pytest.mark.parametrize("engine, tail", [
    ("postgresql", 'ON CONFLICT ("id") DO NOTHING'),
    ("sqlite", 'ON CONFLICT ("id") DO NOTHING'),
    ("mysql", "ON DUPLICATE KEY UPDATE `id` = `id`"),
])
def test_skip_leaves_an_existing_row_alone_in_the_statement(engine, tail):
    from theprotocol.proxy.sinks.sql_upsert import upsert_statement
    assert upsert_statement(engine, ["customers"], ["id", "name"], ["id"], "skip").endswith(tail)


def test_sql_server_skip_has_no_matched_branch_and_a_key_only_row_updates_nothing():
    from theprotocol.proxy.sinks.sql_upsert import upsert_statement
    skip = upsert_statement("sqlserver", ["customers"], ["id", "name"], ["id"], "skip")
    assert "WHEN MATCHED" not in skip and "WHEN NOT MATCHED THEN INSERT" in skip
    keyonly = upsert_statement("sqlite", ["customers"], ["id"], ["id"], "update")
    assert keyonly.endswith('ON CONFLICT ("id") DO NOTHING')


def test_the_pre_image_read_is_by_key_with_a_parameter_per_key_column():
    from theprotocol.proxy.sinks.sql_upsert import preimage_statement
    assert preimage_statement("sqlite", ["customers"], ["a", "b"]) == 'SELECT * FROM "customers" WHERE "a" = ? AND "b" = ?'
    # locked for the transaction that is about to change the row (SQLite's BEGIN IMMEDIATE already serializes)
    assert preimage_statement("postgresql", ["public", "customers"], ["id"]) == (
        'SELECT * FROM "public"."customers" WHERE "id" = %s FOR UPDATE')
    assert preimage_statement("mysql", ["customers"], ["id"]) == "SELECT * FROM `customers` WHERE `id` = %s FOR UPDATE"
    assert preimage_statement("sqlserver", ["customers"], ["id"]) == (
        "SELECT * FROM [customers] WITH (UPDLOCK, HOLDLOCK) WHERE [id] = %s")


# ── what it writes ────────────────────────────────────────────────────────────────────────────────────────────

async def test_one_key_is_one_write_and_a_later_record_for_the_row_updates_it(tmp_path):
    path = _db(tmp_path)
    sink, _ = _sink(path)
    await sink.start()
    try:
        await _run(sink, 1, key="same", id=1, name="Ada", email="a@x.org")
        again = await _run(sink, 1, key="same", id=1, name="CHANGED", email="a@x.org")
        assert again.status == "done"
        assert _rows(path) == [(1, "Ada", "a@x.org")]                       # the repeat of a key wrote nothing
        await _run(sink, 2, key="other", id=1, name="Ada Lovelace", email="a@x.org")
        assert _rows(path) == [(1, "Ada Lovelace", "a@x.org")]              # a new key for the same row is an update
    finally:
        await sink.stop()


async def test_skip_keeps_the_existing_row(tmp_path):
    path = _db(tmp_path)
    c = sqlite3.connect(path)
    c.execute("INSERT INTO customers VALUES (1, 'Old', 'o@x.org')")
    c.commit()
    c.close()
    sink, _ = _sink(path, on_conflict="skip")
    await sink.start()
    try:
        await _run(sink, 1, id=1, name="New", email="n@x.org")
        await _run(sink, 2, id=2, name="Fresh", email="f@x.org")
    finally:
        await sink.stop()
    assert _rows(path) == [(1, "Old", "o@x.org"), (2, "Fresh", "f@x.org")]


async def test_columns_is_an_allow_list_and_a_composite_key_works(tmp_path):
    path = _db(tmp_path, "CREATE TABLE lines (a INTEGER, b TEXT, qty INTEGER, note TEXT, PRIMARY KEY (a, b))")
    sink, _ = _sink(path, table="lines", key=["a", "b"], columns=["a", "b", "qty"])
    await sink.start()
    try:
        await _run(sink, 1, a=1, b="x", qty=2, note="never written")
        await _run(sink, 2, a=1, b="x", qty=5, note="never written")
        await _run(sink, 3, a=1, b="y", qty=1, note="never written")
    finally:
        await sink.stop()
    assert _rows(path, "lines", "a, b") == [(1, "x", 5, None), (1, "y", 1, None)]


async def test_a_dict_value_goes_in_as_json_text_and_a_null_as_null(tmp_path):
    path = _db(tmp_path, "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
    sink, _ = _sink(path)
    await sink.start()
    try:
        await _run(sink, 1, id=1, name={"first": "Ada"}, email=None)
    finally:
        await sink.stop()
    (row,) = _rows(path)
    assert json.loads(row[1]) == {"first": "Ada"} and row[2] is None


async def test_the_hostile_value_is_a_parameter_never_part_of_the_statement(tmp_path):
    path = _db(tmp_path)
    sink, _ = _sink(path)
    await sink.start()
    try:
        await _run(sink, 1, id=1, name="O'Brien\"; DROP TABLE customers; --", email="x")
    finally:
        await sink.stop()
    assert _rows(path) == [(1, "O'Brien\"; DROP TABLE customers; --", "x")]


# ── the way back ──────────────────────────────────────────────────────────────────────────────────────────────

async def test_the_oldest_pre_image_is_kept_and_restore_puts_every_row_back(tmp_path):
    from theprotocol.proxy.sinks.sql_upsert import restore_preimages
    path = _db(tmp_path)
    c = sqlite3.connect(path)
    c.execute("INSERT INTO customers VALUES (1, 'Original', 'o@x.org')")
    c.commit()
    c.close()
    sink, ctx = _sink(path)
    await sink.start()
    try:
        await _run(sink, 1, key="a", id=1, name="First", email="1@x.org")
        await _run(sink, 2, key="b", id=1, name="Second", email="2@x.org")     # the pre-image stays the ORIGINAL
        await _run(sink, 3, key="c", id=2, name="New row", email="n@x.org")    # a row that did not exist: pre-image null
    finally:
        await sink.stop()
    assert _rows(path) == [(1, "Second", "2@x.org"), (2, "New row", "n@x.org")]
    n = await restore_preimages(ctx.state, {"engine": "sqlite", "path": str(path), "table": "customers", "key": ["id"]})
    assert n == 2
    assert _rows(path) == [(1, "Original", "o@x.org")]                          # the new row is deleted again
    again = await restore_preimages(ctx.state, {"engine": "sqlite", "path": str(path), "table": "customers", "key": ["id"]})
    assert again == 2 and _rows(path) == [(1, "Original", "o@x.org")]          # idempotent: the same end state


async def test_the_state_is_written_append_only_so_20000_keys_cost_20000_small_writes():
    """The order of the pre-images was one list read, searched and rewritten whole for every new key: quadratic (about 175 GB of
    state writes at 100,000 rows). Now a counter and one small key per pre-image: no write grows with the number of keys."""
    import time
    from theprotocol.proxy.sinks.sql_upsert import SqlUpsertSink
    ctx = FakeContext()
    sizes = []
    real = ctx.state.set

    async def counting(key, value):
        sizes.append(len(json.dumps(value)))
        await real(key, value)
    ctx.state.set = counting
    sink = SqlUpsertSink({"engine": "sqlite", "path": "unused.db", "table": "customers", "key": ["id"]}, ctx)

    async def no_db(fn, *args):                       # the statements are not the question here: the state's writes are
        return (True, None) if fn.__name__ == "_begin_and_read" else None
    sink._db = no_db
    t = time.time()
    for i in range(20000):
        await sink.deliver(_ev(i, id=i, name="x"), key=f"k{i}", dry_run=False)
    took = time.time() - t
    assert took < 20, f"20,000 keys took {took:.1f} s"
    assert max(sizes) < 400 and sum(sizes) < 20000 * 400, (max(sizes), sum(sizes))
    assert ctx.state.data["pre_n"] == 20000 and len(ctx.state.data["pre_at:19999"]) == 32
    assert "pre_order" not in ctx.state.data


@pytest.mark.parametrize("fail_after", [0, 1, 2, 3])
async def test_a_stop_after_any_of_the_three_state_writes_still_leaves_the_key_restorable(tmp_path, fail_after):
    """The pre-image is kept with three writes (the listing pre_at:<n>, the counter pre_n, the entry pre:<hash>). Make the state fail
    after each of them, run the delivery again as a restart does, and a rollback still puts the pre-migration row back."""
    from theprotocol.proxy.sinks.sql_upsert import restore_preimages
    path = _db(tmp_path)
    c = sqlite3.connect(path)
    c.execute("INSERT INTO customers VALUES (1, 'Original', 'o')")
    c.commit()
    c.close()
    ctx = FakeContext()
    real = ctx.state.set
    seen = {"n": 0, "armed": True}

    async def flaky(key, value):
        if seen["armed"] and (key.startswith("pre:") or key.startswith("pre_at:") or key == "pre_n"):
            if seen["n"] == fail_after:
                seen["armed"] = False
                raise RuntimeError("the state stopped here")
            seen["n"] += 1
        await real(key, value)
    ctx.state.set = flaky
    sink, _ = _sink(path, ctx=ctx)
    await sink.start()
    try:
        if fail_after < 3:
            with pytest.raises(Exception):
                await _run(sink, 1, key="a", id=1, name="Changed", email="c")
        # the retry (a restart: the same delivery again over the same state)
        sink2, _ = _sink(path, ctx=ctx)
        await sink2.start()
        try:
            await _run(sink2, 1, key="a", id=1, name="Changed", email="c")
        finally:
            await sink2.stop()
    finally:
        await sink.stop()
    assert _rows(path) == [(1, "Changed", "c")]
    n = await restore_preimages(ctx.state, {"engine": "sqlite", "path": str(path), "table": "customers", "key": ["id"]})
    assert n >= 1 and _rows(path) == [(1, "Original", "o")]


async def test_restore_walks_the_counter_down_newest_first_over_many_keys(tmp_path):
    from theprotocol.proxy.sinks.sql_upsert import restore_preimages
    path = _db(tmp_path)
    c = sqlite3.connect(path)
    c.executemany("INSERT INTO customers VALUES (?, ?, ?)", [(i, f"old{i}", "o") for i in range(1, 301)])
    c.commit()
    c.close()
    sink, ctx = _sink(path)
    await sink.start()
    try:
        for i in range(1, 301):
            await _run(sink, i, id=i, name=f"new{i}", email="n")
    finally:
        await sink.stop()
    assert ctx.state.data["pre_n"] == 300
    n = await restore_preimages(ctx.state, {"engine": "sqlite", "path": str(path), "table": "customers", "key": ["id"]})
    assert n == 300 and _rows(path)[0] == (1, "old1", "o") and _rows(path)[-1] == (300, "old300", "o")


async def test_restore_goes_newest_first(tmp_path):
    """Two keys, one table with a UNIQUE column: restoring oldest first would clash with a row the newer key holds."""
    from theprotocol.proxy.sinks.sql_upsert import restore_preimages
    path = _db(tmp_path, "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT UNIQUE, email TEXT)")
    c = sqlite3.connect(path)
    c.execute("INSERT INTO customers VALUES (1, 'ada', 'a'), (2, 'bob', 'b')")
    c.commit()
    c.close()
    sink, ctx = _sink(path)
    await sink.start()
    try:
        await _run(sink, 1, id=1, name="tmp", email="a")      # 1: ada -> tmp
        await _run(sink, 2, id=2, name="ada", email="b")      # 2: bob -> ada (free now)
    finally:
        await sink.stop()
    n = await restore_preimages(ctx.state, {"engine": "sqlite", "path": str(path), "table": "customers", "key": ["id"]})
    assert n == 2 and _rows(path) == [(1, "ada", "a"), (2, "bob", "b")]


async def test_preimage_false_keeps_none_and_restore_has_nothing_to_do(tmp_path):
    from theprotocol.proxy.sinks.sql_upsert import restore_preimages
    path = _db(tmp_path)
    sink, ctx = _sink(path, preimage=False)
    await sink.start()
    try:
        await _run(sink, 1, id=1, name="A", email="a")
    finally:
        await sink.stop()
    assert await restore_preimages(ctx.state, {"engine": "sqlite", "path": str(path), "table": "customers", "key": ["id"]}) == 0
    assert _rows(path) == [(1, "A", "a")]


async def test_the_pre_image_is_in_the_state_before_the_write_commits(tmp_path):
    """A stop between the pre-image read and the commit must not lose the pre-migration row: the state holds it first."""
    path = _db(tmp_path)
    c = sqlite3.connect(path)
    c.execute("INSERT INTO customers VALUES (1, 'Original', 'o')")
    c.commit()
    c.close()
    sink, ctx = _sink(path)
    await sink.start()
    seen = {}
    real_set = ctx.state.set

    async def spy(key, value):
        if key.startswith("pre:"):
            seen["rows_at_that_time"] = _rows(path)
        await real_set(key, value)
    ctx.state.set = spy
    try:
        await _run(sink, 1, id=1, name="Changed", email="c")
    finally:
        await sink.stop()
    assert seen["rows_at_that_time"] == [(1, "Original", "o")]                  # the write had not happened yet


# ── what it refuses, and what it retries ──────────────────────────────────────────────────────────────────────

async def test_a_type_error_is_refused_naming_the_column_and_never_the_value(tmp_path):
    path = _db(tmp_path, "CREATE TABLE customers (id INTEGER PRIMARY KEY, age INTEGER NOT NULL, name TEXT) STRICT")
    sink, _ = _sink(path)
    await sink.start()
    try:
        with pytest.raises(Refused) as e:
            await _run(sink, 1, id=1, age=SECRET_VALUE, name="x")
    finally:
        await sink.stop()
    assert "age" in e.value.detail and SECRET_VALUE not in e.value.detail and SECRET_VALUE not in repr(e.value.answer)


async def test_a_null_in_a_not_null_column_is_refused_naming_the_column(tmp_path):
    path = _db(tmp_path, "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT)")
    sink, _ = _sink(path)
    await sink.start()
    try:
        with pytest.raises(Refused) as e:
            await _run(sink, 1, id=1, name=None, email="x")
    finally:
        await sink.stop()
    assert "name" in e.value.detail


async def test_an_unknown_column_and_a_missing_key_are_refused_by_name(tmp_path):
    path = _db(tmp_path)
    sink, _ = _sink(path)
    await sink.start()
    try:
        with pytest.raises(Refused) as e1:
            await _run(sink, 1, id=1, name="x", nickname="y")
        assert "nickname" in e1.value.detail
        with pytest.raises(Refused) as e2:
            await _run(sink, 2, name="x", email="y")
        assert "id" in e2.value.detail
    finally:
        await sink.stop()


async def test_a_locked_database_is_a_retry_and_a_missing_table_a_refusal(tmp_path):
    path = _db(tmp_path)
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    sink, _ = _sink(path, timeout_seconds=0.2)
    await sink.start()
    try:
        with pytest.raises(Retry):
            await _run(sink, 1, id=1, name="x", email="y")
    finally:
        holder.execute("ROLLBACK")
        holder.close()
        await sink.stop()
    sink2, _ = _sink(path, table="no_such_table")
    await sink2.start()
    try:
        with pytest.raises(Refused) as e:
            await _run(sink2, 1, id=1, name="x", email="y")
        assert "no_such_table" in e.value.detail
    finally:
        await sink2.stop()


# ── the dry run ───────────────────────────────────────────────────────────────────────────────────────────────

async def test_a_dry_run_names_the_table_and_the_columns_and_writes_nothing(tmp_path):
    path = _db(tmp_path)
    ctx = FakeContext(dry_run=True)
    sink, _ = _sink(path, ctx=ctx)
    await sink.start()
    out = await sink.deliver(_ev(1, id=1, name="Ada", email="a"), key="k", dry_run=True)
    await sink.stop()
    assert out.status == "dry_run" and "customers" in out.detail
    assert out.data["columns"] == ["email", "id", "name"] and out.data["table"] == "customers"
    assert "Ada" not in json.dumps(out.data) and "Ada" not in out.detail            # names, never values
    assert _rows(path) == [] and ctx.state.data == {}


# ── the classification of the other engines' errors ───────────────────────────────────────────────────────────

class _PgError(Exception):
    def __init__(self, sqlstate, column=None):
        super().__init__("raw driver text with a value: " + SECRET_VALUE)
        self.sqlstate = sqlstate
        self.diag = type("Diag", (), {"column_name": column})()


class _MyError(Exception):
    pass


@pytest.mark.parametrize("engine, exc, want", [
    ("postgresql", _PgError("23502", "name"), "refuse"),
    ("postgresql", _PgError("22P02"), "refuse"),
    ("postgresql", _PgError("42703"), "refuse"),
    ("postgresql", _PgError("40P01"), "retry"),
    ("postgresql", _PgError("40001"), "retry"),
    ("postgresql", _PgError("08006"), "retry"),
    ("mysql", _MyError(1048, "Column 'name' cannot be null"), "refuse"),
    ("mysql", _MyError(1366, "Incorrect integer value: 'x' for column 'age' at row 1"), "refuse"),
    ("mysql", _MyError(1213, "Deadlock found"), "retry"),
    ("mysql", _MyError(2013, "Lost connection"), "retry"),
    ("sqlserver", _MyError(515, "Cannot insert the value NULL into column 'name'"), "refuse"),
    ("sqlserver", _MyError(8152, "String or binary data would be truncated"), "refuse"),
    ("sqlserver", _MyError(1205, "deadlock victim"), "retry"),
])
def test_each_engines_errors_are_a_refusal_or_a_retry(engine, exc, want):
    from theprotocol.proxy.sinks.sql_upsert import classify_error
    assert classify_error(engine, exc) == want


def test_a_refusal_never_repeats_the_drivers_text_which_carries_the_value(tmp_path):
    """PostgreSQL's and MySQL's messages hold the offending value; the refusal is built from the table, the error's class and
    the column the driver names, so the stand-in error whose text holds a value yields a refusal that does not."""
    from theprotocol.proxy.sinks.sql_upsert import SqlUpsertSink
    for engine, exc in (("postgresql", _PgError("23502", "name")), ("mysql", _MyError(1366, f"Incorrect integer value: '{SECRET_VALUE}' for column 'age' at row 1"))):
        cfg = {"engine": engine, "host": "h", "table": "customers", "key": ["id"]}
        sink = SqlUpsertSink(cfg, FakeContext())
        out = sink._translated(exc, ["id", "name", "age"])
        assert isinstance(out, Refused) and SECRET_VALUE not in out.detail and "column" in out.detail
    retry = SqlUpsertSink({"engine": "postgresql", "host": "h", "table": "customers", "key": ["id"]}, FakeContext())._translated(
        _PgError("40P01"), ["id"])
    assert isinstance(retry, Retry) and SECRET_VALUE not in retry.detail


def test_the_column_comes_from_the_driver_not_its_text_being_repeated():
    from theprotocol.proxy.sinks.sql_upsert import column_of
    assert column_of("postgresql", _PgError("23502", "name"), ["id", "name"]) == "name"
    assert column_of("mysql", _MyError(1048, "Column 'name' cannot be null"), ["id", "name"]) == "name"
    assert column_of("sqlserver", _MyError(515, "Cannot insert the value NULL into column 'name'"), ["id", "name"]) == "name"
    assert column_of("mysql", _MyError(1406, "something else"), ["id", "name"]) is None


# ── a real server, when there is one ──────────────────────────────────────────────────────────────────────────

_REAL = {"postgresql": ("TP_PROXY_TEST_POSTGRESQL", "psycopg"), "mysql": ("TP_PROXY_TEST_MYSQL", "pymysql"),
         "sqlserver": ("TP_PROXY_TEST_SQLSERVER", "pymssql")}


@pytest.mark.parametrize("engine", sorted(_REAL))
async def test_a_real_server_upserts_by_key_and_restores(engine):
    import importlib.util
    import urllib.parse
    env, driver = _REAL[engine]
    if not os.environ.get(env):
        pytest.skip(f"{env} is not set: no {engine} server to write to")
    if importlib.util.find_spec(driver) is None:
        pytest.skip(f"the {driver} driver is not installed")
    from theprotocol.proxy.sinks.sql_upsert import SqlUpsertSink, restore_preimages
    u = urllib.parse.urlsplit(os.environ[env])
    ident = {"postgresql": "public.tp_m1_customers", "mysql": "tp_m1_customers", "sqlserver": "tp_m1_customers"}[engine]
    ctx = FakeContext(secrets={"env:TP_M1_PW": urllib.parse.unquote(u.password or "")})
    cfg = {"engine": engine, "host": u.hostname, "port": u.port, "user": urllib.parse.unquote(u.username or ""),
           "password": "env:TP_M1_PW", "database": (u.path or "/").lstrip("/") or None, "table": ident, "key": ["id"]}
    cfg = {k: v for k, v in cfg.items() if v is not None}
    if engine == "postgresql":                       # the table is the test's own (it was assumed to exist, and failed where it did not)
        import psycopg
        pg = dict(host=u.hostname, port=u.port, user=urllib.parse.unquote(u.username or ""),
                  password=urllib.parse.unquote(u.password or ""), dbname=(u.path or "/").lstrip("/") or None)
        with psycopg.connect(autocommit=True, **{k: v for k, v in pg.items() if v is not None}) as c:
            c.execute(f"DROP TABLE IF EXISTS {ident}")
            c.execute(f"CREATE TABLE {ident} (id int PRIMARY KEY, name text)")
    sink = SqlUpsertSink(cfg, ctx)
    await sink.start()
    try:
        for i, name in ((1, "Ada"), (2, "Ada Lovelace")):
            await sink.deliver(_ev(i, id=1, name=name), key=f"k{i}", dry_run=False)
    finally:
        await sink.stop()
    assert await restore_preimages(ctx.state, cfg, secret=ctx.secret) == 1
    if engine == "postgresql":
        with psycopg.connect(autocommit=True, **{k: v for k, v in pg.items() if v is not None}) as c:
            c.execute(f"DROP TABLE IF EXISTS {ident}")


# ── what the state keeps of a json, array and binary column (the M8 real-type finding, room seq 3853) ──────────────────────────

def test_a_json_value_is_kept_as_json_and_comes_back_as_json_text():
    """Python's str() of a dict ("{'old': True}", single quotes) is not JSON: PostgreSQL refused it on a restore. The state keeps the
    value of a json or jsonb column as {"$json": value}, and the restore sends it as JSON text."""
    from theprotocol.proxy.sinks.sql_upsert import _JsonColumn, _kept, _restored
    for value in ({"old": True, "n": [1, 2.5, None], "s": "x'y"}, [1, "two", {"3": 3}], "hello", 42, True):
        kept = _kept(_JsonColumn(value))
        assert kept == {"$json": value}
        assert json.loads(json.dumps(kept)) == kept                               # what the state file holds
        assert json.loads(_restored(kept)) == value                                # JSON text, double quotes
    assert _restored(_kept({"a": 1})) == '{"a":1}'                                 # a bare dict is a JSON value as well
    assert _kept([1, 2, 3]) == [1, 2, 3] and _restored([1, 2, 3]) == [1, 2, 3]     # an array column stays an array


def test_the_markers_do_not_collide_and_bytes_still_round_trip():
    from theprotocol.proxy.sinks.sql_upsert import _JsonColumn, _kept, _restored
    assert _restored(_kept(b"\x00\xffA")) == b"\x00\xffA"
    tricky = {"$b64": "AAE="}                                                      # a JSON object that looks like the bytes marker
    kept = _kept(_JsonColumn(tricky))
    assert kept == {"$json": tricky} and json.loads(_restored(kept)) == tricky


def test_a_decimal_inside_a_json_value_is_kept_as_its_exact_text():
    import decimal
    from theprotocol.proxy.sinks.sql_upsert import _JsonColumn, _kept
    assert _kept(_JsonColumn({"price": decimal.Decimal("12.50")})) == {"$json": {"price": "12.50"}}


async def test_a_real_postgresql_restores_json_jsonb_array_bytea_and_numeric_columns():
    import importlib.util
    import urllib.parse
    env = "TP_PROXY_TEST_POSTGRESQL"
    if not os.environ.get(env):
        pytest.skip(f"{env} is not set: no postgresql server to write to")
    if importlib.util.find_spec("psycopg") is None:
        pytest.skip("the psycopg driver is not installed")
    import psycopg
    from theprotocol.proxy.sinks.sql_upsert import SqlUpsertSink, restore_preimages
    u = urllib.parse.urlsplit(os.environ[env])
    kw = dict(host=u.hostname, port=u.port, user=urllib.parse.unquote(u.username or ""),
              password=urllib.parse.unquote(u.password or ""), dbname=(u.path or "/").lstrip("/") or None)
    kw = {k: v for k, v in kw.items() if v is not None}
    table = "public.tp_m6_types"
    with psycopg.connect(autocommit=True, **kw) as c:
        c.execute(f"DROP TABLE IF EXISTS {table}")
        c.execute(f"CREATE TABLE {table} (id int PRIMARY KEY, doc jsonb, plain json, tags int[], blob bytea, price numeric(14,4), "
                  f"seen timestamptz, label text)")
        c.execute(f"INSERT INTO {table} VALUES (1, '{{\"old\": true, \"l\": [1, 2]}}', '[\"a\", {{\"b\": null}}]', '{{1,2,3}}', "
                  f"'\\x00ff41', 12.5000, '2026-01-02 03:04:05+01', 'before')")
        c.execute(f"INSERT INTO {table} VALUES (3, '\"just text\"', NULL, NULL, NULL, NULL, NULL, 'three')")
    ctx = FakeContext(secrets={"env:TP_M6_PW": kw.get("password", "")})
    cfg = {"engine": "postgresql", "host": kw["host"], "port": kw["port"], "user": kw["user"], "password": "env:TP_M6_PW",
           "database": kw.get("dbname"), "table": table, "key": ["id"]}
    cfg = {k: v for k, v in cfg.items() if v is not None}
    sink = SqlUpsertSink(cfg, ctx)
    await sink.start()
    try:
        await sink.deliver(_ev(1, id=1, doc={"new": 1}, plain=["x"], tags="{9}", blob=b"\x01", price=decimal_("1.1000"),
                               seen="2030-01-01T00:00:00+00:00", label="after"), key="k1", dry_run=False)
        await sink.deliver(_ev(2, id=3, doc={"new": 3}, label="after3"), key="k2", dry_run=False)
        await sink.deliver(_ev(3, id=2, doc={"fresh": True}, label="created"), key="k3", dry_run=False)
    finally:
        await sink.stop()
    n = await restore_preimages(ctx.state, cfg, secret=ctx.secret)
    assert n == 3
    with psycopg.connect(**kw) as c:
        rows = c.execute(f"SELECT id, doc, plain, tags, bytes_(blob), price::text, seen, label FROM {table} ORDER BY id"
                         .replace("bytes_(blob)", "blob")).fetchall()
        c.execute(f"DROP TABLE {table}")
    assert [r[0] for r in rows] == [1, 3]                                           # the created row is deleted again
    one, three = rows
    assert one[1] == {"old": True, "l": [1, 2]} and one[2] == ["a", {"b": None}] and one[3] == [1, 2, 3]
    assert bytes(one[4]) == b"\x00\xffA" and one[5] == "12.5000" and one[7] == "before"
    assert one[6].isoformat() == "2026-01-02T02:04:05+00:00" or one[6].utcoffset() is not None
    assert three[1] == "just text" and three[7] == "three"


def decimal_(text):
    import decimal
    return decimal.Decimal(text)
