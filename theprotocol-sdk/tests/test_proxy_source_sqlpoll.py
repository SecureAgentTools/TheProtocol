"""V0659 (m): the SQL poll source, without a server: its cursor, its statements and its refusals.

The cursor semantics are the same on every engine, so they are pinned here against SQLite (the standard library's,
so this file runs in every SDK suite): resumption at every split point of a tie, rows that arrive while the proxy is
down, a late-committed row and settle_seconds, rewind, from_start. The SQL each engine is sent is pinned by building
the statement for each dialect and reading it: every value is a parameter, every name is quoted. The same scenarios
against a real PostgreSQL, MySQL and SQL Server are tests/test_proxy_source_sqlpoll_engines.py.

check_source(twice=True) proves stable ids and check_resume proves a restart goes on from the cursor; a tie is where
a cursor that is only the cursor column goes wrong, so the resume contract is run at EVERY split point of one.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import pathlib
import re
import sqlite3

import pytest

from theprotocol.proxy import plugins
from theprotocol.proxy.plugins import PluginError, Record, Source
from theprotocol.proxy.sources import SqlPollSource
from theprotocol.proxy.sources import sqlpoll
from theprotocol.proxy.spec import SpecError, parse
from theprotocol.proxy.testing import FakeContext, check_class, check_resume, check_source

DDL = "CREATE TABLE events (id INTEGER PRIMARY KEY, at TEXT, code TEXT, qty INTEGER, note TEXT)"
T1, T2, T3 = "2026-11-08 10:00:01", "2026-11-08 10:00:02", "2026-11-08 10:00:03"


def _db(tmp_path, rows=(), *, ddl=DDL, table="events", name="erp.db"):
    path = tmp_path / name
    con = sqlite3.connect(path)
    con.execute(ddl)
    con.commit()
    con.close()
    _insert(path, rows, table=table)
    return path


def _insert(path, rows, *, table="events"):
    rows = list(rows)
    if not rows:
        return
    cols = list(rows[0])
    con = sqlite3.connect(path)
    con.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                    [tuple(r[c] for c in cols) for r in rows])
    con.commit()
    con.close()


def _rows(ids, at=T1):
    return [{"id": i, "at": at, "code": f"c{i}", "qty": i * 10} for i in ids]


def _cfg(path, **kw):
    cfg = {"engine": "sqlite", "path": str(path), "table": "events", "cursor": "id", "poll_seconds": 0,
           "settle_seconds": 0}
    cfg.update(kw)
    return cfg


def _ts(path, **kw):
    return _cfg(path, cursor="at", cursor_type="timestamp", key="id", **kw)


async def _collect(src, limit=None):
    out = []
    await src.start()
    try:
        async for r in src.records():
            out.append(r)
            await src.committed(r)
            if limit and len(out) >= limit:
                break
    finally:
        await src.stop()
    return out


def _ids(records):
    return [r.record_id for r in records]


def _key_ids(records):
    return [r.meta["key"][-1] for r in records]


async def _until(pred, timeout=5.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not pred():
        if loop.time() > end:
            raise AssertionError("timed out waiting")
        await asyncio.sleep(0.02)


# --- the interface, the loader, the spec ---------------------------------------------------------------------------
def test_it_keeps_the_plugin_interface():
    check_class(SqlPollSource, "source")


def test_the_loader_finds_it_as_sqlpoll():
    assert plugins.available("source")["sqlpoll"] == "theprotocol.proxy.sources.sqlpoll:SqlPollSource"
    assert plugins.load("source", "sqlpoll") is SqlPollSource


def test_the_sdk_declares_it_in_the_sources_entry_point_group():
    """An installed SDK names it in the entry-point group theprotocol.proxy.sources, where a community source is
    found, as well as among the built-ins (which a source checkout with no installed distribution relies on)."""
    text = (pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    section = re.search(r'^\[project\.entry-points\."theprotocol\.proxy\.sources"\][ \t]*\n((?:[^\[].*\n|\n)*)', text,
                        re.M)
    assert section, "pyproject.toml declares no entry points in the group theprotocol.proxy.sources"
    assert re.search(r'^sqlpoll\s*=\s*"theprotocol\.proxy\.sources\.sqlpoll:SqlPollSource"\s*$', section.group(1),
                     re.M), section.group(1)


def _spec(password):
    return {"version": 1, "name": "erp-proxy", "registry": "https://registry.test",
            "identity": {"agent_did": "env:AGENT_DID", "client_id": "env:CLIENT_ID", "client_secret": "env:CS"},
            "sources": {"erp": {"type": "sqlpoll", "config": {
                "engine": "postgresql", "host": "erp-db", "database": "erp", "user": "tp_reader",
                "password": password, "table": "sales.order_events", "cursor": "event_id"}}}}


def test_the_spec_takes_the_password_only_as_a_reference():
    with pytest.raises(SpecError) as e:
        parse(_spec("hunter2-literal"))
    assert "sources.erp.config.password" in str(e.value)
    assert "hunter2-literal" not in str(e.value)
    spec = parse(_spec("env:ERP_DB_PASSWORD"))
    assert spec.sources["erp"].type == "sqlpoll"


def test_a_missing_driver_names_the_extra_that_brings_it(monkeypatch):
    monkeypatch.setattr(sqlpoll._Postgres, "module", "theprotocol_no_such_driver")
    src = SqlPollSource({"engine": "postgresql", "host": "erp-db", "table": "t", "cursor": "id"}, FakeContext())
    with pytest.raises(PluginError) as e:
        asyncio.run(src.start())
    assert "theprotocol-sdk[proxy-postgresql]" in str(e.value)


def _faked_driver(monkeypatch, seen):
    """PostgreSQL's dialect with its driver faked: connecting records what it was given and fails."""
    def connect(self, c):
        seen.update(c)
        raise ConnectionRefusedError("no server in this test")
    monkeypatch.setattr(sqlpoll._Postgres, "module", "sqlite3")      # importable: the driver itself is faked
    monkeypatch.setattr(sqlpoll._Postgres, "connect", connect)


async def _read_all(src):
    await src.start()
    try:
        async for _ in src.records():
            pass
    finally:
        await src.stop()


ERP = {"engine": "postgresql", "host": "erp-db", "database": "erp", "user": "file:/run/secrets/erp-user",
       "password": "env:ERP_DB_PASSWORD", "table": "events", "cursor": "id",
       "connect_args": {"sslmode": "verify-full", "sslpassword": "env:ERP_DB_PASSWORD"}}


def test_the_credentials_are_references_the_context_resolves_when_it_connects(monkeypatch):
    seen = {}
    _faked_driver(monkeypatch, seen)
    ctx = FakeContext(secrets={"env:ERP_DB_PASSWORD": "s3cret-value", "file:/run/secrets/erp-user": "tp_reader"})
    with pytest.raises(ConnectionRefusedError):
        asyncio.run(_read_all(SqlPollSource(ERP, ctx)))
    assert seen["password"] == "s3cret-value" and seen["user"] == "tp_reader" and seen["host"] == "erp-db"
    assert seen["args"] == {"sslmode": "verify-full", "sslpassword": "s3cret-value"}


def test_a_reference_that_does_not_resolve_is_named_and_nothing_connects(monkeypatch):
    seen = {}
    _faked_driver(monkeypatch, seen)
    ctx = FakeContext(secrets={"file:/run/secrets/erp-user": "tp_reader"})
    with pytest.raises(PluginError) as e:
        asyncio.run(_read_all(SqlPollSource(ERP, ctx)))
    assert "does not resolve" in str(e.value) and seen == {}


@pytest.mark.parametrize("args,where", [
    ({"sslpassword": "hunter2-literal"}, "connect_args.sslpassword"),        # libpq's name: no separator before it
    ({"ssl": {"key_passphrase": "hunter2-literal"}}, "connect_args.ssl.key_passphrase"),
    ({"tds_secret": "hunter2-literal"}, "connect_args.tds_secret"),
    ({"sslmode": "require", "PASSWD": "hunter2-literal"}, "connect_args.PASSWD"),
])
def test_connect_args_take_a_credential_only_as_a_reference(args, where):
    """The spec's own rule refuses a literal under a key that ENDS in a secret word after a separator (ssl_password);
    a driver's own spelling (libpq's sslpassword) is not caught by it, so the source refuses any connect_args key that
    names a password, a passphrase or a secret, and names the key, never the value."""
    cfg = {"engine": "postgresql", "host": "erp-db", "table": "events", "cursor": "id", "connect_args": args}
    with pytest.raises(PluginError) as e:
        SqlPollSource(cfg, FakeContext())
    assert where in str(e.value) and "hunter2-literal" not in str(e.value)
    SqlPollSource(dict(cfg, connect_args={"sslmode": "require", "sslpassword": "env:ERP_KEY_PASSPHRASE"}),
                  FakeContext())


@pytest.mark.parametrize("path", ["file:erp.db", "file:erp.db?mode=ro", "env:ERP_SQLITE_FILE"])
def test_the_sqlite_path_is_a_file_name_taken_as_written(tmp_path, path):
    """A path is not a secret, so it is never resolved as a reference: SQLite's own URI spelling (file:erp.db) would be
    read as the CONTENT of erp.db, a binary file. A path that reads like a reference is refused when the source is
    built, before anything (the log's redactor included) tries to resolve it."""
    with pytest.raises(PluginError) as e:
        SqlPollSource(dict(_cfg(tmp_path / "erp.db"), path=path), FakeContext())
    assert "taken as written" in str(e.value) and path in str(e.value)


# --- the harness these tests trust ----------------------------------------------------------------------------------
class _LosesTheRest(Source):
    """A source whose restart goes past every record it had not read yet (what a cursor compared under other rules
    than its ORDER BY does): the resume contract has to see that."""

    name = "loses_the_rest"
    config_schema = {"type": "object"}

    async def records(self):
        if await self.ctx.state.get("next") is not None:
            return                            # restarted: the cursor is past everything that is left
        for i in range(5):
            yield Record(record_id=str(i), payload={"i": i})

    async def committed(self, record):
        await self.ctx.state.set("next", int(record.record_id) + 1)


def test_the_resume_contract_sees_a_restart_that_loses_the_rest():
    with pytest.raises(AssertionError) as e:
        asyncio.run(check_resume(_LosesTheRest, {}, first=2))
    assert "skipped" in str(e.value) and "'2', '3', '4'" in str(e.value)


# --- the shipped contracts -----------------------------------------------------------------------------------------
def test_it_passes_the_shipped_source_contract(tmp_path):
    path = _db(tmp_path, _rows([1, 2, 3]))
    got = asyncio.run(check_source(SqlPollSource, _cfg(path), limit=10))
    assert _ids(got) == ["1", "2", "3"]
    assert got[0].payload == {"id": 1, "at": T1, "code": "c1", "qty": 10, "note": None}
    assert got[0].meta == {"table": "events", "cursor": 1, "key": [1]}


def test_it_passes_the_shipped_resume_contract(tmp_path):
    path = _db(tmp_path, _rows([1, 2, 3, 4, 5]))
    ids = asyncio.run(check_resume(SqlPollSource, _cfg(path, batch_size=2), first=2))
    assert ids == ["1", "2", "3", "4", "5"]


# --- ties: the case a cursor of the cursor column alone gets wrong ---------------------------------------------------
TIE = ([{"id": 9, "at": T1, "code": "a"}]
       + [{"id": i, "at": T2, "code": "b"} for i in (10, 4, 7, 2)]      # one time, keys written out of order
       + [{"id": 1, "at": T3, "code": "c"}])


def test_rows_with_the_same_time_are_read_in_key_order_across_batches(tmp_path):
    path = _db(tmp_path, TIE)
    got = asyncio.run(check_source(SqlPollSource, _ts(path, batch_size=2), limit=50))
    assert _key_ids(got) == [9, 2, 4, 7, 10, 1]
    assert [r.meta["cursor"] for r in got] == [T1, T2, T2, T2, T2, T3]


@pytest.mark.parametrize("first", range(1, 6))
def test_a_restart_at_any_point_of_a_tie_reads_no_row_twice_and_skips_none(tmp_path, first):
    path = _db(tmp_path, TIE)
    ids = asyncio.run(check_resume(SqlPollSource, _ts(path, batch_size=2), first=first, limit=50))
    assert [json.loads(i)[0] for i in ids] == [9, 2, 4, 7, 10, 1]


def test_a_later_row_with_the_last_time_and_a_greater_key_is_read(tmp_path):
    path = _db(tmp_path, [{"id": 1, "at": T1}, {"id": 2, "at": T2}])
    ctx = FakeContext()

    async def go():
        first = await _collect(SqlPollSource(_ts(path), ctx))
        _insert(path, [{"id": 3, "at": T2}])
        second = await _collect(SqlPollSource(_ts(path), ctx))
        return first, second

    first, second = asyncio.run(go())
    assert _key_ids(first) == [1, 2] and _key_ids(second) == [3]


def test_a_key_that_names_the_timestamp_cursor_takes_the_cursors_own_text(tmp_path):
    """key: [changed_at, event_id] with changed_at the cursor: the key's cursor column is the cursor's own text, the
    same value the place and the record id carry, never the driver's value for the column (on every server engine a
    datetime, which no key takes). Here a time kept as seconds in a REAL, which the driver gives back as a float."""
    ddl = "CREATE TABLE events (id INTEGER PRIMARY KEY, at REAL, code TEXT)"
    rows = ([{"id": 9, "at": 1762596001.5}] + [{"id": i, "at": 1762596002.25} for i in (10, 4, 7, 2)]
            + [{"id": 1, "at": 1762596003.75}])
    path = _db(tmp_path, rows, ddl=ddl)
    cfg = _cfg(path, cursor="at", cursor_type="timestamp", key=["at", "id"], batch_size=2)
    got = asyncio.run(check_source(SqlPollSource, cfg, limit=50))
    assert [json.loads(r.record_id) for r in got] == [
        ["1762596001.5", 9], ["1762596002.25", 2], ["1762596002.25", 4], ["1762596002.25", 7],
        ["1762596002.25", 10], ["1762596003.75", 1]]
    assert all(r.meta["key"][0] == r.meta["cursor"] for r in got)
    for first in range(1, 6):
        ids = asyncio.run(check_resume(SqlPollSource, cfg, first=first, limit=50))
        assert [json.loads(i)[1] for i in ids] == [9, 2, 4, 7, 10, 1], f"split after {first}"


# --- resumption ------------------------------------------------------------------------------------------------------
def test_rows_that_arrive_while_it_is_down_are_read_once(tmp_path):
    path = _db(tmp_path, _rows([1, 2, 3]))
    ctx = FakeContext()

    async def go():
        first = await _collect(SqlPollSource(_cfg(path), ctx))
        _insert(path, _rows([4, 5]))
        second = await _collect(SqlPollSource(_cfg(path), ctx))
        third = await _collect(SqlPollSource(_cfg(path), ctx))
        return first, second, third

    first, second, third = asyncio.run(go())
    assert _ids(first) == ["1", "2", "3"] and _ids(second) == ["4", "5"] and third == []


def test_polling_reads_rows_written_after_it_started(tmp_path):
    path = _db(tmp_path, _rows([1, 2]))

    async def go():
        src = SqlPollSource(_cfg(path, poll_seconds=0.05), FakeContext())
        await src.start()
        got = []

        async def consume():
            async for r in src.records():
                got.append(r.record_id)
                await src.committed(r)

        task = asyncio.ensure_future(consume())
        try:
            await _until(lambda: len(got) >= 2)
            _insert(path, _rows([3, 4]))
            await _until(lambda: len(got) >= 4)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await src.stop()
        return got

    assert asyncio.run(go()) == ["1", "2", "3", "4"]


def test_a_failed_query_connects_again_and_goes_on_from_the_committed_row(tmp_path):
    path = _db(tmp_path, _rows([1, 2, 3, 4, 5]))
    ctx = FakeContext()

    async def go():
        src = SqlPollSource(_cfg(path, batch_size=2), ctx)
        await src.start()
        real, calls = src._query, {"n": 0}

        def flaky(sql, params):
            if sql.startswith("SELECT *"):
                calls["n"] += 1
                if calls["n"] == 2:                  # the second batch: rows 1 and 2 are read and committed
                    raise sqlite3.OperationalError("the server went away")
            return real(sql, params)

        src._query = flaky
        got = []
        with pytest.raises(sqlite3.OperationalError):
            async for r in src.records():
                got.append(r.record_id)
                await src.committed(r)
        dropped = src._conn is None
        async for r in src.records():            # what the core does: it calls records() again
            got.append(r.record_id)
            await src.committed(r)
        await src.stop()
        return got, dropped

    got, dropped = asyncio.run(go())
    assert dropped, "a connection that failed a query was kept"
    assert got == ["1", "2", "3", "4", "5"]


def test_a_database_that_answers_with_the_place_itself_stops_it_instead_of_reading_it_forever(tmp_path, monkeypatch):
    """If the rows after a place come back with the row AT the place (a value that does not compare back the way it
    was read: a cursor whose text is shorter than its value, a comparison inclusive by mistake), a batch of one reads
    that row again, and again, with no end and no error. The source stops at once and names the place."""
    path = _db(tmp_path, _rows([1, 2, 3]))
    real = sqlpoll.Statements.after

    def lets_the_place_through(self, pos):
        sql, params = real(self, pos)
        return sql.replace('"id" > ', '"id" >= '), params

    monkeypatch.setattr(sqlpoll.Statements, "after", lets_the_place_through)
    got = []

    async def go():
        src = SqlPollSource(_cfg(path, batch_size=1), FakeContext())
        await src.start()
        try:
            async for r in src.records():
                got.append(r.record_id)
                await src.committed(r)
        finally:
            await src.stop()

    with pytest.raises(PluginError) as e:
        asyncio.run(asyncio.wait_for(go(), timeout=20))
    assert got == ["1"], got[:10]
    assert "the row at that place itself" in str(e.value) and "[1,[]]" in str(e.value).replace(" ", "")


def test_a_count_that_fails_does_not_keep_the_source_from_reading(tmp_path, monkeypatch):
    """The count of rows with no cursor value or no key is only for the log. A count the database cannot finish (a
    statement timeout on a large view) must not keep the source from ever reading: the runtime would restart it
    forever."""
    path = _db(tmp_path, _rows([1, 2, 3]))
    monkeypatch.setattr(sqlpoll.Statements, "unplaced", lambda self: ("SELECT COUNT(*) FROM no_such_view", []))
    ctx, lines = _logged_context("unplaced-fails")
    got = asyncio.run(_collect(SqlPollSource(_cfg(path), ctx)))
    assert _ids(got) == ["1", "2", "3"]
    assert any("could not be counted" in m and "no_such_view" in m for m in lines.lines), lines.lines


# --- a row committed late, and settle_seconds --------------------------------------------------------------------------
def _late_writer(path, rows):
    """What a transaction that took a lower id (or an earlier time) and commits later looks like to a poll: while the
    source waits out settle_seconds, rows appear BEHIND the highest value it saw."""
    calls = []

    async def fake_sleep(seconds):
        calls.append(seconds)
        if len(calls) == 1:
            _insert(path, rows)

    return fake_sleep, calls


def test_settle_reads_a_row_that_commits_behind_the_highest_value_while_it_waits(tmp_path, monkeypatch):
    path = _db(tmp_path, _rows([2]))
    sleep, calls = _late_writer(path, _rows([1]))
    monkeypatch.setattr(sqlpoll, "_sleep", sleep)
    got = asyncio.run(_collect(SqlPollSource(_cfg(path, settle_seconds=1.5), FakeContext())))
    assert calls == [1.5]
    assert _ids(got) == ["1", "2"]


def test_without_settle_a_row_committed_late_is_stepped_over(tmp_path):
    """The control: what settle_seconds is for. With 0 the poll reads 2 at once, 1 commits behind it, and no restart
    reads it again."""
    path = _db(tmp_path, _rows([2]))
    ctx = FakeContext()

    async def go():
        first = await _collect(SqlPollSource(_cfg(path, settle_seconds=0), ctx))
        _insert(path, _rows([1]))
        second = await _collect(SqlPollSource(_cfg(path, settle_seconds=0), ctx))
        return first, second

    first, second = asyncio.run(go())
    assert _ids(first) == ["2"] and second == []


def test_a_pass_reads_only_up_to_the_highest_value_it_saw_before_waiting(tmp_path, monkeypatch):
    path = _db(tmp_path, _rows([1, 2, 3]))
    sleep, _ = _late_writer(path, _rows([5]))
    monkeypatch.setattr(sqlpoll, "_sleep", sleep)
    ctx = FakeContext()

    async def go():
        first = await _collect(SqlPollSource(_cfg(path, settle_seconds=1), ctx))
        second = await _collect(SqlPollSource(_cfg(path, settle_seconds=1), ctx))
        return first, second

    first, second = asyncio.run(go())
    assert _ids(first) == ["1", "2", "3"] and _ids(second) == ["5"]


# --- the record --------------------------------------------------------------------------------------------------------
def test_a_record_carries_the_row_as_json(tmp_path):
    path = _db(tmp_path, ddl="CREATE TABLE events (id INTEGER PRIMARY KEY, at TEXT, ratio REAL, raw BLOB, note TEXT)")
    _insert(path, [{"id": 1, "at": T1, "ratio": 0.25, "raw": b"\x00\xffok", "note": None}])
    got = asyncio.run(check_source(SqlPollSource, _cfg(path)))
    assert got[0].payload == {"id": 1, "at": T1, "ratio": 0.25, "raw": "AP9vaw==", "note": None}


def test_columns_limits_what_a_record_carries(tmp_path):
    path = _db(tmp_path, _rows([1]))
    got = asyncio.run(check_source(SqlPollSource, _cfg(path, columns=["code"])))
    assert got[0].payload == {"code": "c1"} and got[0].record_id == "1"


def test_a_key_of_several_columns_names_the_record_with_all_of_them(tmp_path):
    path = _db(tmp_path, [{"id": 1, "at": T1, "code": "eu"}, {"id": 2, "at": T1, "code": "us"}])
    got = asyncio.run(check_source(SqlPollSource, _cfg(path, key=["code", "id"])))
    assert _ids(got) == ['["eu",1]', '["us",2]']


def test_a_changed_row_is_a_new_record_and_the_same_version_is_the_same_record(tmp_path):
    """With a timestamp cursor that is not the key (changed_at), each version of a row is a record of its own: an
    exactly-once key of the row's key alone would take the change for a repeat and drop it."""
    path = _db(tmp_path, [{"id": 1, "at": T1}])
    ctx = FakeContext()

    async def go():
        first = await _collect(SqlPollSource(_ts(path), ctx))
        con = sqlite3.connect(path)
        con.execute("UPDATE events SET at = ? WHERE id = 1", (T2,))
        con.commit()
        con.close()
        second = await _collect(SqlPollSource(_ts(path), ctx))
        again = await _collect(SqlPollSource(_ts(path), FakeContext()))
        return first, second, again

    first, second, again = asyncio.run(go())
    assert _ids(first) == [json.dumps([1, T1], separators=(",", ":"))]
    assert _ids(second) == [json.dumps([1, T2], separators=(",", ":"))]
    assert _ids(again) == _ids(second)


# --- parameters and names --------------------------------------------------------------------------------------------
HOSTILE = "O'Brien\"; DROP TABLE events; --"


def test_a_key_with_quotes_and_semicolons_is_a_value_not_sql(tmp_path):
    ddl = "CREATE TABLE events (code TEXT PRIMARY KEY, at TEXT)"
    rows = [{"code": c, "at": T1} for c in ("a", HOSTILE, "x'y", "z")]
    path = _db(tmp_path, rows, ddl=ddl)
    cfg = _cfg(path, cursor="at", cursor_type="timestamp", key="code", batch_size=1)
    for first in range(1, 4):
        ids = asyncio.run(check_resume(SqlPollSource, cfg, first=first, limit=10))
        assert [json.loads(i)[0] for i in ids] == sorted(r["code"] for r in rows)
    con = sqlite3.connect(path)
    assert con.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 4
    con.close()


@pytest.mark.parametrize("field,value", [
    ("table", 'events"; DROP TABLE events; --'), ("table", "a`b"), ("table", "a]b"), ("table", "a;b"),
    ("table", ""), ("table", " events"), ("table", "a.b.c.d"), ("table", "a..b"), ("cursor", "id'"),
    ("cursor", "id\n"), ("key", ["id", 'x"']), ("columns", ["code", "x)"]), ("columns", []),
])
def test_names_that_could_leave_their_quotes_are_refused(tmp_path, field, value):
    cfg = _cfg(tmp_path / "erp.db", **{field: value})
    with pytest.raises(PluginError):
        SqlPollSource(cfg, FakeContext())


def test_names_a_legacy_system_really_has_are_taken(tmp_path):
    for table in ("Order Details", "sales.order_events", "erp.dbo.ORDERS", "_staging", "t$1", "order-lines"):
        SqlPollSource(_cfg(tmp_path / "erp.db", table=table), FakeContext())


@pytest.mark.parametrize("cfg", [
    {"engine": "oracle"}, {"batch_size": 0}, {"batch_size": 1.5}, {"poll_seconds": -1}, {"settle_seconds": -0.5},
    {"timeout_seconds": 0}, {"path": ""}, {"cursor_type": "uuid"}, {"key": ["id", "id"]},
    {"engine": "postgresql", "host": ""}, {"engine": "mysql"}, {"engine": "sqlserver"},
])
def test_what_cannot_work_is_refused_when_it_is_built(tmp_path, cfg):
    full = _cfg(tmp_path / "erp.db")
    full.update(cfg)
    if cfg.get("engine") in ("mysql", "sqlserver"):
        full.pop("path", None)
    with pytest.raises(PluginError):
        SqlPollSource(full, FakeContext())


def test_a_timestamp_cursor_needs_a_key(tmp_path):
    with pytest.raises(PluginError) as e:
        SqlPollSource(_cfg(tmp_path / "erp.db", cursor="at", cursor_type="timestamp"), FakeContext())
    assert "key" in str(e.value)


def test_an_id_cursor_refuses_values_that_are_not_integers(tmp_path):
    path = _db(tmp_path, [{"id": "a"}, {"id": "b"}], ddl="CREATE TABLE events (id TEXT PRIMARY KEY)")
    with pytest.raises(PluginError) as e:
        asyncio.run(_collect(SqlPollSource(_cfg(path), FakeContext())))
    assert "integers" in str(e.value)


# --- the statements: every value a parameter, every name quoted ---------------------------------------------------------
POS = {"c": "2026-11-08 10:00:00.1234567", "k": [HOSTILE, 7]}
BOUND = "2026-11-08 11:00:00"


def _statements(engine):
    st = sqlpoll.Statements(sqlpoll._DIALECTS[engine](), table=["sales", "events"], columns=None, cursor="at",
                            cursor_type="timestamp", keys=["region", "id"])
    if engine == "sqlserver":
        st.types = {"at": "datetime2(7)", "region": "varchar(8)", "id": "int"}
    return st


@pytest.mark.parametrize("engine,sql", [
    ("postgresql",
     'SELECT *, CAST("at" AS text) AS "__tp_c", "region" AS "__tp_k0", "id" AS "__tp_k1" FROM "sales"."events" '
     'WHERE "at" IS NOT NULL AND "region" IS NOT NULL AND "id" IS NOT NULL AND ("at", "region", "id") > (%s, %s, %s) '
     'AND "at" <= %s ORDER BY "at", "region", "id" LIMIT %s'),
    ("sqlite",
     'SELECT *, CAST("at" AS TEXT) AS "__tp_c", "region" AS "__tp_k0", "id" AS "__tp_k1" FROM "sales"."events" '
     'WHERE "at" IS NOT NULL AND "region" IS NOT NULL AND "id" IS NOT NULL AND ("at", "region", "id") > (?, ?, ?) '
     'AND "at" <= ? ORDER BY "at", "region", "id" LIMIT ?'),
])
def test_the_next_rows_are_asked_for_with_every_value_a_parameter(engine, sql):
    got, params = _statements(engine).select(POS, BOUND, 501)
    assert got == sql
    assert params == [POS["c"], HOSTILE, 7, BOUND, 501]
    for value in (POS["c"], "O'Brien", "DROP", BOUND, "501"):
        assert value not in got


def test_mysql_spells_the_order_out_so_its_index_range_starts_at_the_place():
    """MySQL takes no index range from a row comparison: (at, region, id) > (...) read the table from its start on
    every poll (measured on 8.4: 19,991 rows read for one batch of 51 at 20,000 rows, the place near the end; with
    `at >= :c` in front of it, still the whole tie before the place, 1,051 in the middle of a tie of 2,000). Spelled
    out, the same order is a range that starts at the place: 50 rows read in each case."""
    got, params = _statements("mysql").select(POS, BOUND, 501)
    assert got == (
        "SELECT *, CAST(`at` AS CHAR) AS `__tp_c`, `region` AS `__tp_k0`, `id` AS `__tp_k1` FROM `sales`.`events` "
        "WHERE `at` IS NOT NULL AND `region` IS NOT NULL AND `id` IS NOT NULL AND "
        "((`at` > %s) OR (`at` = %s AND `region` > %s) OR (`at` = %s AND `region` = %s AND `id` > %s)) "
        "AND `at` <= %s ORDER BY `at`, `region`, `id` LIMIT %s")
    assert params == [POS["c"], POS["c"], HOSTILE, POS["c"], HOSTILE, 7, BOUND, 501]
    for value in (POS["c"], "O'Brien", "DROP", BOUND, "501"):
        assert value not in got


def test_sql_server_spells_the_order_out_and_compares_each_value_as_its_column_type():
    got, params = _statements("sqlserver").select(POS, BOUND, 501)
    c, r, i = "CAST(%s AS datetime2(7))", "CAST(%s AS varchar(8))", "CAST(%s AS int)"
    assert got == (
        "SELECT TOP (%s) *, CONVERT(varchar(40), [at], 126) AS [__tp_c], [region] AS [__tp_k0], [id] AS [__tp_k1] "
        "FROM [sales].[events] WHERE [at] IS NOT NULL AND [region] IS NOT NULL AND [id] IS NOT NULL AND "
        f"(([at] > {c}) OR ([at] = {c} AND [region] > {r}) OR ([at] = {c} AND [region] = {r} AND [id] > {i})) "
        f"AND [at] <= {c} ORDER BY [at], [region], [id]")
    assert params == [501, POS["c"], POS["c"], HOSTILE, POS["c"], HOSTILE, 7, BOUND]


def test_a_replay_point_reads_its_own_value_again_and_an_id_needs_no_tiebreak():
    st = sqlpoll.Statements(sqlpoll._DIALECTS["postgresql"](), table=["events"], columns=["code"], cursor="id",
                            cursor_type="id", keys=["id"])
    assert st.select(None, None, 11) == (
        'SELECT "code", "id" AS "__tp_c", "id" AS "__tp_k0" FROM "events" WHERE "id" IS NOT NULL '
        'ORDER BY "id" LIMIT %s', [11])
    assert st.select({"c": 41, "k": []}, None, 11)[0].endswith('WHERE "id" IS NOT NULL AND "id" > %s ORDER BY "id" '
                                                               'LIMIT %s')
    assert st.select({"c": 41, "k": None}, None, 11) == (
        'SELECT "code", "id" AS "__tp_c", "id" AS "__tp_k0" FROM "events" WHERE "id" IS NOT NULL AND "id" >= %s '
        'ORDER BY "id" LIMIT %s', [41, 11])


# --- what cannot be placed, and what cannot be told apart -------------------------------------------------------------
class _Lines(logging.Handler):
    """What a source logs, read from its own context's logger (the proxy's logger may not propagate)."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _logged_context(name):
    ctx, lines = FakeContext(), _Lines()
    ctx.logger = logging.getLogger(f"sqlpoll-test.{name}")
    ctx.logger.handlers[:] = [lines]
    ctx.logger.setLevel(logging.DEBUG)
    ctx.logger.propagate = False
    return ctx, lines


def test_a_row_without_a_cursor_or_a_key_is_never_read_and_is_counted(tmp_path):
    ddl = "CREATE TABLE events (seq INTEGER, at TEXT, code TEXT)"
    rows = [{"seq": 1, "at": T1, "code": "a"}, {"seq": 2, "at": None, "code": "b"},
            {"seq": 3, "at": T2, "code": None}, {"seq": 4, "at": T3, "code": "d"}]
    path = _db(tmp_path, rows, ddl=ddl)
    ctx, lines = _logged_context("unplaced")
    got = asyncio.run(check_source(SqlPollSource, _cfg(path, cursor="at", cursor_type="timestamp", key="code"),
                                   ctx=ctx, twice=False))
    assert [r.meta["key"] for r in got] == [["a"], ["d"]]
    assert any("2 row(s) of events have no at or no key (code)" in m for m in lines.lines), lines.lines


@pytest.mark.parametrize("batch_size", [1, 2, 500])
def test_two_rows_with_the_same_cursor_and_key_stop_it_before_them(tmp_path, batch_size):
    path = _db(tmp_path, [{"id": 1}, {"id": 2}, {"id": 2}, {"id": 3}], ddl="CREATE TABLE events (id INTEGER)")
    ctx = FakeContext()
    got = []

    async def go():
        src = SqlPollSource(_cfg(path, batch_size=batch_size), ctx)
        await src.start()
        try:
            async for r in src.records():
                got.append(r.record_id)
                await src.committed(r)
        finally:
            await src.stop()

    with pytest.raises(PluginError) as e:
        asyncio.run(go())
    assert got == ["1"], "a row of the pair was read, so a restart could skip the other"
    assert "unique" in str(e.value)
    assert ctx.state.data["sqlpoll.cursor"]["at"] == {"c": 1, "k": []}


# --- rewind, from_start, a place kept for another reading ---------------------------------------------------------------
def test_rewind_reads_again_from_a_point(tmp_path):
    path = _db(tmp_path, _rows([1, 2, 3, 4, 5]))
    ctx = FakeContext()

    async def go():
        await _collect(SqlPollSource(_cfg(path), ctx))
        src = SqlPollSource(_cfg(path), ctx)
        await src.start()
        await src.rewind("3")
        await src.stop()
        from_3 = await _collect(SqlPollSource(_cfg(path), ctx))
        src = SqlPollSource(_cfg(path), ctx)
        await src.start()
        await src.rewind("start")
        await src.stop()
        everything = await _collect(SqlPollSource(_cfg(path), ctx))
        return from_3, everything

    from_3, everything = asyncio.run(go())
    assert _ids(from_3) == ["3", "4", "5"] and _ids(everything) == ["1", "2", "3", "4", "5"]


def test_rewind_to_a_time_reads_the_rows_at_it_and_after_it(tmp_path):
    path = _db(tmp_path, TIE)
    ctx = FakeContext()

    async def go():
        await _collect(SqlPollSource(_ts(path), ctx))
        src = SqlPollSource(_ts(path), ctx)
        await src.start()
        await src.rewind(T2)
        await src.stop()
        return await _collect(SqlPollSource(_ts(path), ctx))

    assert _key_ids(asyncio.run(go())) == [2, 4, 7, 10, 1]


async def _replay(path, cfg, ctx, point, *, read_first=None):
    """Read (all, or the first `read_first`), then replay from `point`, then read again: what the second read gives."""
    await _collect(SqlPollSource(cfg, ctx), limit=read_first)
    src = SqlPollSource(cfg, ctx)
    await src.start()
    try:
        await src.rewind(point)
    finally:
        await src.stop()
    return await _collect(SqlPollSource(cfg, ctx))


def test_a_replay_says_where_it_reads_again_from(tmp_path):
    path = _db(tmp_path, _rows([1, 2, 3, 4, 5]))
    ctx, lines = _logged_context("replay-from")
    again = asyncio.run(_replay(path, _cfg(path), ctx, "3"))
    assert _ids(again) == ["3", "4", "5"]
    assert any("a replay of events from 3 reads it again from the row with id 3" in m for m in lines.lines), lines.lines
    assert not any("after the place kept" in m or "no row of" in m for m in lines.lines), lines.lines


def test_a_replay_point_after_the_place_kept_says_which_rows_it_skips(tmp_path):
    """A replay point later than the place kept moves the place FORWARD: the rows between are never read, those not
    read yet and those written later alike. It is the operator's command, so it is done, and said out loud."""
    path = _db(tmp_path, _rows([1, 2, 3, 4, 5]))
    ctx, lines = _logged_context("replay-ahead")
    again = asyncio.run(_replay(path, _cfg(path), ctx, "5", read_first=2))     # 3, 4 and 5 not read yet
    assert _ids(again) == ["5"]
    assert any("the replay point 5 is after the place kept in events (id 2)" in m for m in lines.lines), lines.lines


def test_a_replay_point_no_row_has_reached_reads_nothing_and_says_so(tmp_path):
    path = _db(tmp_path, _rows([1, 2, 3]))
    ctx, lines = _logged_context("replay-none")
    assert asyncio.run(_replay(path, _cfg(path), ctx, "99")) == []
    assert any("no row of events has id 99 or later" in m for m in lines.lines), lines.lines
    assert any("the replay point 99 is after the place kept in events (id 3)" in m for m in lines.lines), lines.lines


def test_a_replay_point_with_a_zone_that_finds_nothing_names_the_zone(tmp_path):
    """The rows hold 10:00:01 to 10:00:03 and the point is 12:00:02+02:00 (10:00:02 UTC). How a zone in the point is
    read is the database's own rule for the column (PostgreSQL and SQL Server drop it on a column that keeps none); a
    point that finds nothing, and lands after the place kept, says so rather than going on in silence."""
    path = _db(tmp_path, TIE)
    ctx, lines = _logged_context("replay-zone")
    assert asyncio.run(_replay(path, _ts(path), ctx, "2026-11-08T12:00:02+02:00")) == []
    none = [m for m in lines.lines if "no row of events has at 2026-11-08T12:00:02+02:00 or later" in m]
    assert none and "zone" in none[0], lines.lines
    assert any("is after the place kept in events (at 2026-11-08 10:00:03)" in m for m in lines.lines), lines.lines


def test_a_replay_point_is_checked_with_bounded_reads_not_a_count_of_the_tail(tmp_path):
    """A count of every row at or after the point would read the whole tail of a large table, inside the statement
    timeout, for a number nothing used. The point is checked with reads of one row."""
    path = _db(tmp_path, TIE)
    ctx = FakeContext()
    sent = []

    async def go():
        await _collect(SqlPollSource(_ts(path), ctx))
        src = SqlPollSource(_ts(path), ctx)
        await src.start()
        try:
            await src._ensure()
            real = src._query

            def spy(sql, params):
                sent.append(sql)
                return real(sql, params)

            src._query = spy
            await src.rewind(T2)
        finally:
            await src.stop()

    asyncio.run(go())
    assert sent and all("COUNT(" not in s and s.endswith(" LIMIT ?") for s in sent), sent


def test_a_replay_the_database_cannot_read_keeps_the_place_and_says_what_failed(tmp_path):
    """The database's own words, not a verdict on the point: a timeout is a timeout, not "does not read the point as a
    value"; and the place kept is unchanged."""
    path = _db(tmp_path, TIE)
    ctx = FakeContext()

    async def go():
        await _collect(SqlPollSource(_ts(path), ctx))
        kept = dict(ctx.state.data["sqlpoll.cursor"]["at"])
        src = SqlPollSource(_ts(path), ctx)
        await src.start()
        try:
            await src._ensure()

            def times_out(sql, params):
                raise sqlite3.OperationalError("canceling statement due to statement timeout")

            src._query = times_out
            with pytest.raises(PluginError) as e:
                await src.rewind(T2)
        finally:
            await src.stop()
        return str(e.value), kept

    why, kept = asyncio.run(go())
    assert "statement timeout" in why and "unchanged" in why and "does not read" not in why
    assert ctx.state.data["sqlpoll.cursor"]["at"] == kept


@pytest.mark.parametrize("cursor_type,point", [
    ("id", "abc"), ("id", "1.5"), ("id", ""), ("id", "  "),
    ("timestamp", "yesterday"), ("timestamp", "2026-13-45"), ("timestamp", "11/08/2026"), ("timestamp", "1; --"),
    ("timestamp", "2026-11-08 25:00"), ("timestamp", "2026-11-08 10:00:61"),
])
def test_rewind_refuses_a_point_it_cannot_honour(tmp_path, cursor_type, point):
    path = _db(tmp_path, _rows([1]))
    cfg = _ts(path) if cursor_type == "timestamp" else _cfg(path)

    async def go():
        src = SqlPollSource(cfg, FakeContext())
        await src.start()
        try:
            await src.rewind(point)
        finally:
            await src.stop()

    with pytest.raises(PluginError):
        asyncio.run(go())


def test_from_start_false_takes_only_the_rows_that_arrive_next(tmp_path):
    path = _db(tmp_path, _rows([1, 2, 3]))
    ctx = FakeContext()

    async def go():
        first = await _collect(SqlPollSource(_cfg(path, from_start=False), ctx))
        _insert(path, _rows([4]))
        second = await _collect(SqlPollSource(_cfg(path, from_start=False), ctx))
        third = await _collect(SqlPollSource(_cfg(path, from_start=False), ctx))
        return first, second, third

    first, second, third = asyncio.run(go())
    assert first == [] and _ids(second) == ["4"] and third == []


def test_from_start_false_on_an_empty_table_still_reads_what_arrives_while_it_is_down(tmp_path):
    path = _db(tmp_path)
    ctx = FakeContext()

    async def go():
        first = await _collect(SqlPollSource(_cfg(path, from_start=False), ctx))
        _insert(path, _rows([1, 2]))
        second = await _collect(SqlPollSource(_cfg(path, from_start=False), ctx))
        return first, second

    first, second = asyncio.run(go())
    assert first == [] and _ids(second) == ["1", "2"]


def test_a_place_kept_for_another_cursor_is_not_used_for_this_one(tmp_path):
    path = _db(tmp_path, _rows([1, 2, 3]))
    ctx = FakeContext()

    async def go():
        await _collect(SqlPollSource(_cfg(path), ctx))
        with pytest.raises(PluginError) as e:
            await _collect(SqlPollSource(_ts(path), ctx))
        src = SqlPollSource(_ts(path), ctx)
        await src.start()
        await src.rewind("start")
        await src.stop()
        return str(e.value), await _collect(SqlPollSource(_ts(path), ctx))

    why, got = asyncio.run(go())
    assert "events by id (id)" in why and "events by at (timestamp)" in why and "--replay" in why
    assert _key_ids(got) == [1, 2, 3]


def test_a_place_kept_for_another_database_is_not_used_for_this_one(tmp_path):
    """The same table, cursor and key in ANOTHER database (staging pointed at production, a migrated server whose
    ids start again) must not inherit the place: every row below it would never be read, in silence. The place names
    the engine and the database as the spec writes them (a reference as written, so a rotated secret changes
    nothing; host and port left out, so a failover keeps its place)."""
    erp = _db(tmp_path, _rows([1, 2, 3]), name="erp.db")
    other = _db(tmp_path, _rows([1, 2, 3, 4, 5]), name="erp-restored.db")
    ctx = FakeContext()

    async def go():
        await _collect(SqlPollSource(_cfg(erp), ctx))
        with pytest.raises(PluginError) as e:
            await _collect(SqlPollSource(_cfg(other), ctx))
        return str(e.value)

    why = asyncio.run(go())
    assert "erp.db" in why and "erp-restored.db" in why and "--replay" in why
    assert ctx.state.data["sqlpoll.cursor"]["reads"]["engine"] == "sqlite"


# --- read only ------------------------------------------------------------------------------------------------------------
def test_the_database_file_is_opened_read_only(tmp_path):
    path = _db(tmp_path, _rows([1]))

    async def go():
        src = SqlPollSource(_cfg(path), FakeContext())
        await src.start()
        try:
            await src._ensure()
            with pytest.raises(sqlite3.Error) as e:
                await src._db(src._query, "INSERT INTO events (id) VALUES (99)", [])
            return str(e.value)
        finally:
            await src.stop()

    why = asyncio.run(go())
    assert "readonly" in why.replace(" ", "").replace("-", "").lower() or "query_only" in why
    con = sqlite3.connect(path)
    assert con.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    con.close()


# --- through the core -----------------------------------------------------------------------------------------------------
def test_through_the_core_each_row_is_sent_once_and_the_cursor_is_kept_in_the_outbox(tmp_path):
    """The real runtime, its outbox file and its committed() after the row is on disk: two runs of `tp-proxy run
    --once` over a table that grew in between send each row once, and the place is the JSON the outbox keeps."""
    import proxy_fake as F
    from theprotocol.proxy.runtime import Proxy

    path = _db(tmp_path, _rows([1, 2]))
    reg = F.FakeRegistry()
    doc = F.spec_doc(tmp_path, sources={"erp": {"type": "sqlpoll", "config": _cfg(path)}},
                     mappings=[{"name": "reading", "version": 1, "from": "erp", "to": "attest",
                                "fields": {"value": "$.payload.qty", "id": "$.record_id"}}])

    async def run_once():
        p = Proxy(parse(doc, base=tmp_path), transport=reg.transport, service=False, poll_s=0.01)
        try:
            await asyncio.wait_for(p.run(until_idle=True), timeout=20)
            return p.outbox.state_get("source:erp", "sqlpoll.cursor")
        finally:
            p.close()

    first = asyncio.run(run_once())
    _insert(path, _rows([3]))
    second = asyncio.run(run_once())
    assert [e["attestation_data"]["claim"] for e in reg.effects] == [
        {"value": 10, "id": "1"}, {"value": 20, "id": "2"}, {"value": 30, "id": "3"}]
    assert first["at"] == {"c": 2, "k": []} and second["at"] == {"c": 3, "k": []}
    assert second["reads"] == {"engine": "sqlite", "path": str(path), "table": "events", "cursor": "id",
                               "cursor_type": "id", "key": ["id"]}
