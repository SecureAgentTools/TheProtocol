"""V0659 (m): the SQL poll source against real servers, PostgreSQL, MySQL and SQL Server, each in a container.

An engine's tests run when its address is in the environment and are skipped, saying why, when it is not (or when
its driver is not installed), so the default SDK suite stays hermetic:

    TP_PROXY_TEST_POSTGRESQL=postgresql://postgres:<password>@<host>:5432/postgres
    TP_PROXY_TEST_MYSQL=mysql://root:<password>@<host>:3306/tptest
    TP_PROXY_TEST_SQLSERVER=sqlserver://sa:<password>@<host>:1433/tptest

The address is an ADMIN login: the tests make their own tables and a login that may only SELECT them, and the source
reads as that login, so every test here also proves the source needs nothing more than SELECT. (SQL Server's test
database is switched to READ_COMMITTED_SNAPSHOT, as Azure SQL ships, so that a reader there sees what PostgreSQL's
and MySQL's readers see: the last committed version of a row, not a lock to wait on.)

What only a real engine can show: a timestamp that keeps the engine's full precision (SQL Server's 100 ns), a text
key compared in its column's own collation, a transaction that took a lower id and commits late, a session the
engine itself holds read only, a poll that sees what committed after it began (MySQL's REPEATABLE READ keeps a
long transaction on one snapshot), and what one poll costs: the rows the engine itself counts as read for a batch.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import os
import re
import secrets
import urllib.parse
import xml.etree.ElementTree as ET

import pytest

from theprotocol.proxy.plugins import PluginError
from theprotocol.proxy.sources import SqlPollSource
from theprotocol.proxy.testing import FakeContext, check_resume, check_source

_ADDRESS = {"postgresql": ("TP_PROXY_TEST_POSTGRESQL", "psycopg", "proxy-postgresql"),
            "mysql": ("TP_PROXY_TEST_MYSQL", "pymysql", "proxy-mysql"),
            "sqlserver": ("TP_PROXY_TEST_SQLSERVER", "pymssql", "proxy-sqlserver")}

HOSTILE = "O'Brien\"; DROP TABLE x; --"


class _Engine:
    name = driver = default_db = ""
    digits = 6                    # the fraction of a second the engine's timestamp column keeps
    readonly_words: tuple = ()    # what the engine says when a read-only session is asked to write
    denied_words: tuple = ()      # what the engine says when a login is refused a write it may not make

    def __init__(self, url: str):
        u = urllib.parse.urlsplit(url)
        self.host, self.port = u.hostname, u.port
        self.user = urllib.parse.unquote(u.username or "")
        self.password = urllib.parse.unquote(u.password or "")
        self.database = (u.path or "/").lstrip("/") or self.default_db
        self.reader = "tp_reader_" + secrets.token_hex(4)
        self.reader_password = "Rd-" + secrets.token_hex(12)
        self.tables: list = []
        self._admin = None

    # what each engine spells its own way
    def connect(self, *, user=None, password=None, autocommit=True, database=None):  # pragma: no cover
        raise NotImplementedError

    def ddl(self, t):  # pragma: no cover
        raise NotImplementedError

    def grant(self, t):  # pragma: no cover
        raise NotImplementedError

    def insert_sql(self, t):  # pragma: no cover
        raise NotImplementedError

    def new_id(self, cur):
        return cur.fetchone()[0]

    def qualified(self, t):
        return t

    def q(self, name):
        return f'"{name}"'

    # the same for all of them
    def admin(self):
        if self._admin is None:
            self._admin = self.connect()
        return self._admin

    def exec(self, sql, params=None, *, conn=None):
        cur = (conn or self.admin()).cursor()
        try:
            cur.execute(sql, params) if params is not None else cur.execute(sql)
            try:
                return list(cur.fetchall())
            except Exception:  # noqa: BLE001 - a statement with no rows
                return []
        finally:
            cur.close()

    def table(self):
        t = "sqlpoll_" + secrets.token_hex(5)
        self.exec(self.ddl(t))
        self.grant(t)
        self.tables.append(t)
        return t

    def insert(self, t, rows, *, conn=None):
        ids = []
        for row in rows:
            cur = (conn or self.admin()).cursor()
            try:
                cur.execute(self.insert_sql(t), tuple(row))
                ids.append(int(self.new_id(cur)))
            finally:
                cur.close()
        return ids

    def bulk(self, t, rows):
        """Many rows in one transaction (insert() commits each row on its own)."""
        conn = self.connect(autocommit=False)
        try:
            cur = conn.cursor()
            cur.executemany(f"INSERT INTO {self.qualified_sql(t)} (at, region, code, qty) VALUES (%s, %s, %s, %s)",
                            [tuple(r) for r in rows])
            conn.commit()
        finally:
            conn.close()

    def index(self, t, *cols):
        self.exec(f"CREATE INDEX {self.q('ix_' + t)} ON {self.qualified_sql(t)} ({', '.join(self.q(c) for c in cols)})")

    def analyze(self, t):  # pragma: no cover
        raise NotImplementedError

    def rows_read(self, sql, params):  # pragma: no cover
        """(the rows, how many rows or index entries the engine read to find them, what it said)."""
        raise NotImplementedError

    def ts(self, second, fraction=0):
        frac = str(fraction).rjust(self.digits, "0")
        return f"2026-11-08 10:00:{second:02d}.{frac}"

    def config(self, t, *, admin=False, **kw):
        cfg = {"engine": self.name, "host": self.host, "database": self.database,
               "user": self.user if admin else self.reader,
               "password": self.password if admin else self.reader_password,
               "table": self.qualified(t), "cursor": "id", "poll_seconds": 0, "settle_seconds": 0,
               "timeout_seconds": 20}
        if self.port:
            cfg["port"] = self.port
        cfg.update(kw)
        return cfg

    def ordered(self, t, *cols):
        order = ", ".join(self.q(c) for c in cols)
        return self.exec(f"SELECT id FROM {self.qualified_sql(t)} ORDER BY {order}")

    def qualified_sql(self, t):
        return self.q(t)

    def setup(self):  # pragma: no cover
        raise NotImplementedError

    def teardown(self):
        for t in self.tables:
            with contextlib.suppress(Exception):
                self.exec(f"DROP TABLE {self.qualified_sql(t)}")
        self.drop_reader()
        with contextlib.suppress(Exception):
            self._admin.close()

    def drop_reader(self):  # pragma: no cover
        pass


class _Postgres(_Engine):
    name, driver, default_db = "postgresql", "psycopg", "postgres"
    readonly_words = ("read-only",)
    denied_words = ("permission denied",)

    def analyze(self, t):
        self.exec(f"ANALYZE {self.q(t)}")

    def rows_read(self, sql, params):
        """EXPLAIN ANALYZE: what each scan returned and what its filter took out (a bitmap's index half is not counted
        twice)."""
        rows = self.exec(sql, params)
        plan = self.exec("EXPLAIN (ANALYZE, FORMAT JSON) " + sql, params)[0][0]
        plan = json.loads(plan) if isinstance(plan, str) else plan
        read = 0

        def walk(node):
            nonlocal read
            kind = node.get("Node Type", "")
            if kind.endswith("Scan") and kind != "Bitmap Index Scan":
                read += (node.get("Actual Rows", 0) * node.get("Actual Loops", 1)
                         + node.get("Rows Removed by Filter", 0) + node.get("Rows Removed by Index Recheck", 0))
            for child in node.get("Plans", ()):
                walk(child)

        walk(plan[0]["Plan"])
        return rows, int(read), plan

    def connect(self, *, user=None, password=None, autocommit=True, database=None):
        import psycopg
        return psycopg.connect(host=self.host, port=self.port or 5432, user=user or self.user,
                               password=password or self.password, dbname=database or self.database,
                               autocommit=autocommit, connect_timeout=10)

    def setup(self):
        self.exec(f"CREATE ROLE {self.q(self.reader)} LOGIN PASSWORD '{self.reader_password}'")

    def ddl(self, t):
        return (f"CREATE TABLE {self.q(t)} (id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, "
                f"at timestamptz(6), region varchar(16), code varchar(80), qty numeric(12,2), note text)")

    def grant(self, t):
        self.exec(f"GRANT SELECT ON {self.q(t)} TO {self.q(self.reader)}")

    def insert_sql(self, t):
        return f"INSERT INTO {self.q(t)} (at, region, code, qty) VALUES (%s, %s, %s, %s) RETURNING id"

    def drop_reader(self):
        with contextlib.suppress(Exception):
            self.exec(f"DROP ROLE {self.q(self.reader)}")


class _MySQL(_Engine):
    name, driver, default_db = "mysql", "pymysql", "tptest"
    readonly_words = ("READ ONLY", "read only", "1792")
    denied_words = ("command denied",)

    def analyze(self, t):
        self.exec(f"ANALYZE TABLE {self.q(t)}")

    def rows_read(self, sql, params):
        """The session's handler counters around the one statement: every row or index entry the engine read (an
        index dive, Handler_read_key, is not a row)."""
        def counters():
            return {str(n): int(v) for n, v in self.exec("SHOW SESSION STATUS LIKE 'Handler_read%'")}
        before = counters()
        rows = self.exec(sql, params)
        after = counters()
        delta = {n: after[n] - before.get(n, 0) for n in after if after[n] != before.get(n, 0)}
        return rows, sum(v for n, v in delta.items() if n != "Handler_read_key"), delta

    def connect(self, *, user=None, password=None, autocommit=True, database=None):
        import pymysql
        return pymysql.connect(host=self.host, port=self.port or 3306, user=user or self.user,
                               password=password or self.password, database=database or self.database,
                               autocommit=autocommit, charset="utf8mb4", connect_timeout=10)

    def q(self, name):
        return f"`{name}`"

    def setup(self):
        self.exec(f"CREATE USER '{self.reader}'@'%' IDENTIFIED BY '{self.reader_password}'")

    def ddl(self, t):
        return (f"CREATE TABLE {self.q(t)} (id BIGINT AUTO_INCREMENT PRIMARY KEY, at DATETIME(6), "
                f"region VARCHAR(16), code VARCHAR(80), qty DECIMAL(12,2), note TEXT) ENGINE=InnoDB")

    def grant(self, t):
        self.exec(f"GRANT SELECT ON {self.q(self.database)}.{self.q(t)} TO '{self.reader}'@'%'")

    def insert_sql(self, t):
        return f"INSERT INTO {self.q(t)} (at, region, code, qty) VALUES (%s, %s, %s, %s)"

    def new_id(self, cur):
        return cur.lastrowid

    def drop_reader(self):
        with contextlib.suppress(Exception):
            self.exec(f"DROP USER '{self.reader}'@'%'")


class _SqlServer(_Engine):
    name, driver, default_db = "sqlserver", "pymssql", "tptest"
    digits = 7
    denied_words = ("permission was denied",)

    def analyze(self, t):
        self.exec(f"UPDATE STATISTICS [dbo].[{t}] WITH FULLSCAN")

    def rows_read(self, sql, params):
        """The actual plan (SET STATISTICS XML): the rows each scan or seek read (ActualRowsRead). The lookup of each
        row found, by its clustered key, is not counted: it is the row, not the search for it."""
        ns = "{http://schemas.microsoft.com/sqlserver/2004/07/showplan}"
        cur = self.admin().cursor()
        try:
            cur.execute("SET STATISTICS XML ON")
            cur.execute(sql, tuple(params))
            rows = list(cur.fetchall())
            plan = None
            while cur.nextset():
                got = cur.fetchall()
                if got and isinstance(got[0][0], str) and "ShowPlanXML" in got[0][0]:
                    plan = got[0][0]
            cur.execute("SET STATISTICS XML OFF")
        finally:
            cur.close()
        assert plan, "SQL Server gave no actual plan"
        read, ops = 0, []
        for rel in ET.fromstring(plan).iter(ns + "RelOp"):
            op = rel.get("PhysicalOp") or ""
            scan = rel.find(ns + "IndexScan")
            if not ("Scan" in op or "Seek" in op) or (scan is not None and scan.get("Lookup") in ("1", "true")):
                continue
            info = rel.find(ns + "RunTimeInformation")
            n = sum(int(c.get("ActualRowsRead") or c.get("ActualRows") or 0)
                    for c in (info if info is not None else ()) if c.tag == ns + "RunTimeCountersPerThread")
            read += n
            ops.append((op, n))
        return rows, read, ops

    def connect(self, *, user=None, password=None, autocommit=True, database=None):
        import pymssql
        return pymssql.connect(server=self.host, port=str(self.port or 1433), user=user or self.user,
                               password=password or self.password, database=database or self.database,
                               autocommit=autocommit, login_timeout=10)

    def q(self, name):
        return f"[{name}]"

    def qualified(self, t):
        return f"dbo.{t}"

    def qualified_sql(self, t):
        return f"[dbo].[{t}]"

    def setup(self):
        master = self.connect(database="master")
        try:
            self.exec(f"IF DB_ID(N'{self.database}') IS NULL CREATE DATABASE [{self.database}]", conn=master)
            self.exec(f"ALTER DATABASE [{self.database}] SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE",
                      conn=master)
            self.exec(f"CREATE LOGIN [{self.reader}] WITH PASSWORD = N'{self.reader_password}', CHECK_POLICY = OFF",
                      conn=master)
        finally:
            master.close()
        self.exec(f"CREATE USER [{self.reader}] FOR LOGIN [{self.reader}]")

    def ddl(self, t):
        return (f"CREATE TABLE [dbo].[{t}] (id bigint IDENTITY(1,1) PRIMARY KEY, at datetime2(7), "
                f"region varchar(16), code varchar(80), qty decimal(12,2), note nvarchar(200))")

    def grant(self, t):
        self.exec(f"GRANT SELECT ON [dbo].[{t}] TO [{self.reader}]")

    def insert_sql(self, t):
        return f"INSERT INTO [dbo].[{t}] (at, region, code, qty) OUTPUT INSERTED.id VALUES (%s, %s, %s, %s)"

    def drop_reader(self):
        with contextlib.suppress(Exception):
            self.exec(f"DROP USER [{self.reader}]")
        with contextlib.suppress(Exception):
            master = self.connect(database="master")
            try:
                self.exec(f"DROP LOGIN [{self.reader}]", conn=master)
            finally:
                master.close()


_CLASSES = {"postgresql": _Postgres, "mysql": _MySQL, "sqlserver": _SqlServer}


def _engines():
    out = []
    for name, (var, module, extra) in _ADDRESS.items():
        if not os.environ.get(var):
            why = f"{var} is not set (a {name} server for these tests)"
        elif importlib.util.find_spec(module) is None:
            why = f"the {module} driver is not installed (theprotocol-sdk[{extra}])"
        else:
            why = ""
        out.append(pytest.param(name, id=name, marks=pytest.mark.skipif(bool(why), reason=why)))
    return out


@pytest.fixture(scope="module", params=_engines())
def engine(request):
    e = _CLASSES[request.param](os.environ[_ADDRESS[request.param][0]])
    e.setup()
    yield e
    e.teardown()


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


def _last_key(ids):
    return [json.loads(i)[-2] if i.startswith("[") else int(i) for i in ids]


# --- the shipped contracts, as a login that may only SELECT ------------------------------------------------------------
def test_it_passes_the_shipped_contracts(engine):
    t = engine.table()
    ids = engine.insert(t, [(engine.ts(1), "eu", f"c{i}", f"{i}.50") for i in range(5)])
    got = asyncio.run(check_source(SqlPollSource, engine.config(t), limit=10))
    assert [r.record_id for r in got] == [str(i) for i in ids]
    first = got[0].payload
    assert first["id"] == ids[0] and first["code"] == "c0" and first["qty"] == "0.50" and first["note"] is None
    assert first["at"].startswith("2026-11-08T10:00:01")
    resumed = asyncio.run(check_resume(SqlPollSource, engine.config(t, batch_size=2), first=2))
    assert resumed == [str(i) for i in ids]


def test_the_reader_login_may_only_select(engine):
    """The control for every test here: the login the source reads as cannot write."""
    t = engine.table()
    conn = engine.connect(user=engine.reader, password=engine.reader_password)
    try:
        with pytest.raises(Exception) as e:
            engine.exec(engine.insert_sql(t), (engine.ts(1), "eu", "x", "1.00"), conn=conn)
    finally:
        conn.close()
    # the engine's own refusal of the permission, not any failure an insert could meet (a column, a syntax slip)
    assert any(w in str(e.value) for w in engine.denied_words), repr(e.value)
    assert engine.exec(f"SELECT COUNT(*) FROM {engine.qualified_sql(t)}")[0][0] == 0


# --- ties and precision -----------------------------------------------------------------------------------------------
def test_a_restart_at_any_point_of_a_tie_reads_no_row_twice_and_skips_none(engine):
    t = engine.table()
    # written out of time order, so the ids do not give the order away
    engine.insert(t, [(engine.ts(3), "eu", "late", "1.00")])
    engine.insert(t, [(engine.ts(2, 5), "eu", f"tie{i}", "1.00") for i in range(4)])
    engine.insert(t, [(engine.ts(1), "eu", f"early{i}", "1.00") for i in range(2)])
    want = [r[0] for r in engine.ordered(t, "at", "id")]
    cfg = engine.config(t, cursor="at", cursor_type="timestamp", key="id", batch_size=2)
    for first in range(1, len(want)):
        ids = asyncio.run(check_resume(SqlPollSource, cfg, first=first, limit=50))
        assert _last_key(ids) == want, f"split after {first}"


def test_a_key_that_names_the_timestamp_cursor_takes_the_cursors_own_text(engine):
    """key: [at, id] with at the cursor (a key written out whole): the key's cursor column is the cursor's own text,
    the value the place and the record id carry, never the driver's datetime for it, which no key takes."""
    t = engine.table()
    engine.insert(t, [(engine.ts(3), "eu", "late", "1.00")])
    engine.insert(t, [(engine.ts(2, 5), "eu", f"tie{i}", "1.00") for i in range(4)])
    engine.insert(t, [(engine.ts(1), "eu", f"early{i}", "1.00") for i in range(2)])
    want = [r[0] for r in engine.ordered(t, "at", "id")]
    cfg = engine.config(t, cursor="at", cursor_type="timestamp", key=["at", "id"], batch_size=2)
    got = asyncio.run(check_source(SqlPollSource, cfg, limit=50))
    assert [json.loads(r.record_id)[1] for r in got] == want
    assert all(json.loads(r.record_id)[0] == r.meta["cursor"] == r.meta["key"][0] for r in got)
    for first in range(1, len(want)):
        ids = asyncio.run(check_resume(SqlPollSource, cfg, first=first, limit=50))
        assert [json.loads(i)[1] for i in ids] == want, f"split after {first}"


def test_one_batch_reads_about_one_batch_of_the_index_wherever_its_place_is(engine):
    """A poll asks for the rows after a place, and what that costs must not grow with the rows BEFORE the place.
    Measured on MySQL 8.4 at 20,000 rows: a row comparison (at, id) > (:c, :k) gives MySQL no index range, and every
    poll read the whole table for one batch of 51 (19,991 rows); `at >= :c` in front of it still read the whole tie
    before a place inside one (1,051 in a tie of 2,000), and the same `at >= :c` turned SQL Server's seek into a scan
    of the table at a tie. The table here: 20,000 rows with a time each, a tie of 1,000 at one later time, 10 more (a
    table of a few thousand rows is one SQL Server would rather scan than look 51 rows up in); the index is the cursor
    and its key, as the cursor's description asks. With the place near the end of the distinct times, and in the
    middle of the tie, one batch of 50 reads fewer than three batches of rows or index entries, as each engine counts
    them (MySQL's handler reads, PostgreSQL's EXPLAIN ANALYZE, SQL Server's actual plan)."""
    t = engine.table()
    engine.index(t, "at", "id")
    engine.bulk(t, [(engine.ts(1, f), "eu", f"d{f}", "1.00") for f in range(20000)]
                + [(engine.ts(2), "eu", f"t{i}", "1.00") for i in range(1000)]
                + [(engine.ts(3, f), "eu", f"e{f}", "1.00") for f in range(10)])
    engine.analyze(t)
    batch = 50
    # the place is reached in big batches; the read measured is the source's own statement for one batch of 50
    cfg = engine.config(t, cursor="at", cursor_type="timestamp", key="id", batch_size=5000)
    ctx = FakeContext()
    for upto, where in ((19990, "near the end of the distinct times"), (500, "in the middle of the tie")):
        src = SqlPollSource(cfg, ctx)
        assert len(asyncio.run(_collect(src, limit=upto))) == upto
        bound = engine.exec(src._sql.highest()[0])[0][0]           # what settle_seconds holds a read to
        sql, params = src._sql.select(src._committed, bound, batch + 1)
        rows, read, said = engine.rows_read(sql, params)
        assert len(rows) == batch + 1, where
        assert read < 3 * batch, f"one batch with the place {where} read {read} rows ({said})"


def test_a_timestamp_keeps_the_engines_full_precision(engine):
    """Times that differ only in the last digit the column keeps (1 us; 100 ns on SQL Server). A cursor carried as a
    Python datetime would round SQL Server's down and read its own row again at the restart."""
    t = engine.table()
    engine.insert(t, [(engine.ts(1, f), "eu", f"p{f}", "1.00") for f in (3, 1, 2)])
    want = [r[0] for r in engine.ordered(t, "at", "id")]
    cfg = engine.config(t, cursor="at", cursor_type="timestamp", key="id", batch_size=1)
    got = asyncio.run(check_source(SqlPollSource, cfg, limit=10))
    fractions = [re.search(r"\.(\d+)", r.meta["cursor"]).group(1) for r in got]
    assert fractions == [str(f).rjust(engine.digits, "0") for f in (1, 2, 3)], [r.meta["cursor"] for r in got]
    for first in (1, 2):
        ids = asyncio.run(check_resume(SqlPollSource, cfg, first=first, limit=10))
        assert _last_key(ids) == want


def test_a_text_key_is_a_parameter_and_keeps_its_columns_order(engine):
    """Quotes and a statement in a key are a value; and the next rows after a text key are asked for in the column's
    own collation, which is what ORDER BY uses (on SQL Server a parameter is nvarchar, and a varchar column compared
    with one is compared under other rules: 'co-op' and 'coat' change places)."""
    t = engine.table()
    codes = ["a", HOSTILE, "co-op", "coat", "co op", "x'y", "z", "Zebra", "coop"]
    engine.insert(t, [(engine.ts(1), "eu", c, "1.00") for c in codes])
    want = [r[0] for r in engine.ordered(t, "at", "code")]
    cfg = engine.config(t, cursor="at", cursor_type="timestamp", key="code", batch_size=1)
    by_id = dict(engine.exec(f"SELECT code, id FROM {engine.qualified_sql(t)}"))
    for first in range(1, len(codes)):
        ids = asyncio.run(check_resume(SqlPollSource, cfg, first=first, limit=50))
        assert [by_id[json.loads(i)[0]] for i in ids] == want, f"split after {first}"
    assert engine.exec(f"SELECT COUNT(*) FROM {engine.qualified_sql(t)}")[0][0] == len(codes)


class _ComparedAsSent(SqlPollSource):
    """The source without its casts to each column's own type: every value compared as the driver sends it."""

    async def _ensure(self):
        await super()._ensure()
        self._sql.types = {}


def test_without_its_casts_sql_server_repeats_and_loses_text_keys(engine):
    """The control for the text-key test above. pymssql sends a text as nvarchar, and under SQL Server's default
    collation (SQL_Latin1_General_CP1_CI_AS) a varchar column compared with an nvarchar is compared under other rules
    than its own ORDER BY: a restart after 'co-op' loses 'coat' and 'coop', and one after 'coat' reads 'co-op' again."""
    if engine.name != "sqlserver":
        pytest.skip("only SQL Server compares a varchar column with the driver's text under other rules")
    t = engine.table()
    codes = ["co op", "co-op", "coat", "coop"]
    engine.insert(t, [(engine.ts(1), "eu", c, "1.00") for c in codes])
    cfg = engine.config(t, cursor="at", cursor_type="timestamp", key="code", batch_size=1)
    wrong = []
    for first in range(1, len(codes)):
        try:
            asyncio.run(check_resume(_ComparedAsSent, cfg, first=first, limit=50))
        except AssertionError:
            wrong.append(first)
    assert wrong, "compared as sent, every split point resumed right: the casts would prove nothing"
    ids = asyncio.run(check_resume(SqlPollSource, cfg, first=2, limit=50))     # with them, the same split is right
    assert [json.loads(i)[0] for i in ids] == [r[0] for r in engine.exec(
        f"SELECT code FROM {engine.qualified_sql(t)} ORDER BY at, code")]


def test_a_key_of_two_columns_resumes_at_every_split_point(engine):
    t = engine.table()
    engine.insert(t, [(engine.ts(1), region, f"k{n}", "1.00") for n in (2, 1) for region in ("us", "eu", "ap")])
    engine.insert(t, [(engine.ts(2), "eu", "k0", "1.00")])
    want = [r[0] for r in engine.ordered(t, "at", "region", "code")]
    cfg = engine.config(t, cursor="at", cursor_type="timestamp", key=["region", "code"], batch_size=1)
    by_key = {(r, c): i for i, r, c in engine.exec(f"SELECT id, region, code FROM {engine.qualified_sql(t)}")}
    for first in range(1, len(want)):
        ids = asyncio.run(check_resume(SqlPollSource, cfg, first=first, limit=50))
        assert [by_key[tuple(json.loads(i)[:2])] for i in ids] == want, f"split after {first}"


# --- a row committed late ------------------------------------------------------------------------------------------------
def _late(engine, t, settle):
    """A transaction takes id N and stays open; another takes N+1 and commits; the source reads; the first commits
    (with settle: while the source waits; without: once it has read). Returns (what the source read, what a restart
    afterwards reads, the two ids)."""
    slow = engine.connect(autocommit=False)
    try:
        first_id = engine.insert(t, [(engine.ts(1), "eu", "slow", "1.00")], conn=slow)[0]
        second_id = engine.insert(t, [(engine.ts(2), "eu", "fast", "1.00")])[0]
        ctx = FakeContext()

        async def go():
            src = SqlPollSource(engine.config(t, settle_seconds=settle), ctx)
            if settle:
                task = asyncio.ensure_future(_collect(src))
                await asyncio.sleep(0.5)        # well inside settle_seconds: the source is waiting it out
                slow.commit()
                read = await asyncio.wait_for(task, timeout=60)
            else:
                read = await _collect(src)       # read before the commit, whatever the box's load
                slow.commit()
            again = await _collect(SqlPollSource(engine.config(t, settle_seconds=settle), ctx))
            return read, again

        read, again = asyncio.run(go())
    finally:
        with contextlib.suppress(Exception):
            slow.rollback()
        slow.close()
    return [int(r.record_id) for r in read], [int(r.record_id) for r in again], (first_id, second_id)


def test_settle_reads_a_row_whose_transaction_commits_late(engine):
    t = engine.table()
    read, again, (first_id, second_id) = _late(engine, t, settle=2.0)
    assert first_id < second_id
    assert read == [first_id, second_id] and again == []


def test_without_settle_a_row_committed_late_is_stepped_over(engine):
    """The control: what settle_seconds is for. The engine hands out the lower id first and shows it last."""
    t = engine.table()
    read, again, (first_id, second_id) = _late(engine, t, settle=0)
    assert read == [second_id] and again == []


# --- polling and the session ----------------------------------------------------------------------------------------------
def test_polling_sees_rows_committed_after_it_began(engine):
    t = engine.table()
    engine.insert(t, [(engine.ts(1), "eu", f"c{i}", "1.00") for i in range(2)])

    async def go():
        src = SqlPollSource(engine.config(t, poll_seconds=0.2), FakeContext())
        await src.start()
        got = []

        async def consume():
            async for r in src.records():
                got.append(int(r.record_id))
                await src.committed(r)

        task = asyncio.ensure_future(consume())
        try:
            for _ in range(200):
                if len(got) >= 2:
                    break
                await asyncio.sleep(0.05)
            more = engine.insert(t, [(engine.ts(2), "eu", f"d{i}", "1.00") for i in range(2)])
            for _ in range(200):
                if len(got) >= 4:
                    break
                await asyncio.sleep(0.05)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await src.stop()
        return got, more

    got, more = asyncio.run(go())
    assert got[2:] == more and len(got) == 4


def test_the_session_is_read_only_even_for_a_login_that_may_write(engine):
    if not engine.readonly_words:
        pytest.skip("SQL Server has no read-only session: there the login is the guarantee "
                    "(test_the_reader_login_may_only_select)")
    t = engine.table()

    async def go():
        src = SqlPollSource(engine.config(t, admin=True), FakeContext())
        await src.start()
        try:
            await src._ensure()
            with pytest.raises(Exception) as e:
                await src._db(src._query, engine.insert_sql(t).replace(" RETURNING id", ""),
                              [engine.ts(1), "eu", "x", "1.00"])
            return str(e.value)
        finally:
            await src.stop()

    why = asyncio.run(go())
    assert any(w in why for w in engine.readonly_words), why
    assert engine.exec(f"SELECT COUNT(*) FROM {engine.qualified_sql(t)}")[0][0] == 0


def test_rewind_to_a_time_reads_the_rows_at_it_and_after_it(engine):
    t = engine.table()
    ids = engine.insert(t, [(engine.ts(s), "eu", f"c{s}", "1.00") for s in (1, 2, 3)])
    cfg = engine.config(t, cursor="at", cursor_type="timestamp", key="id")
    ctx = FakeContext()

    async def go():
        await _collect(SqlPollSource(cfg, ctx))
        src = SqlPollSource(cfg, ctx)
        await src.start()
        try:
            with pytest.raises(PluginError):
                await src.rewind("2026-11-08 25:00:00")      # the shape of a time, and no such time
            await src.rewind("2026-11-08 10:00:02")
        finally:
            await src.stop()
        return await _collect(SqlPollSource(cfg, ctx))

    assert _last_key([r.record_id for r in asyncio.run(go())]) == ids[1:]


def test_a_wrong_password_is_refused_without_the_password_in_the_answer(engine):
    t = engine.table()
    wrong = "Wrong-" + secrets.token_hex(8)
    src = SqlPollSource(engine.config(t, password=wrong), FakeContext())

    async def go():
        await src.start()
        try:
            async for _ in src.records():
                pass
        finally:
            await src.stop()

    with pytest.raises(Exception) as e:
        asyncio.run(go())
    assert wrong not in str(e.value) and wrong not in repr(e.value)
