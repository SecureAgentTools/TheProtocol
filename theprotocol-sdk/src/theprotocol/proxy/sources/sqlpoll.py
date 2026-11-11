"""The SQL poll source: the rows of a table or view, read in the order of a cursor column.

V0659 (m). A record is one ROW. The source reads the rows in the order of a cursor column (an id that only grows, or a
timestamp), with ties broken by a key, and keeps its place in `ctx.state` once the core has the row:

    sources:
      orders:
        type: sqlpoll
        config:
          engine: postgresql             # postgresql, mysql or sqlserver (sqlite: a database file)
          host: erp-db.internal
          database: erp
          user: tp_proxy_reader          # a login that may only SELECT
          password: env:ERP_DB_PASSWORD  # a reference, never the password itself
          table: sales.order_events      # a table or a view
          cursor: changed_at             # the rows are read in the order of this column
          cursor_type: timestamp         # id (an integer that only grows) or timestamp
          key: event_id                  # tells apart rows with the same cursor value

The cursor is a column whose values only grow as rows are written: the database's own sequence (an identity), or a
time the writer sets as it writes (now()). A date a person types in (an order date, a valid-from) is not a cursor: a
row dated behind the place is never read, and one dated ahead moves the place past the rows written after it with
earlier dates. Give
the table an index on the cursor and its key, in that order (CREATE INDEX ... ON sales.order_events (changed_at,
event_id)): each poll asks for the rows after a place in that order, and with the index it reads one batch of them.

What it promises, and how each promise holds:

* **Resumption with no duplicate and no gap.** The source's place is the last committed row's (cursor, key) pair, and
  the next read asks for the rows AFTER that pair in (cursor, key) order: `(cursor, key) > (:cursor, :key)`, on MySQL
  and SQL Server spelled out as `cursor > :cursor OR (cursor = :cursor AND key > :key)`, which is the form their index
  ranges take. So rows with the same cursor value (a tie) are read in key order, a batch may end in the middle of a
  tie, and a restart in the middle of a tie goes on at the next key. The cursor value alone would read the tie again
  (>=) or lose its rest (>).
* **A timestamp keeps its full precision.** A timestamp cursor is carried as the database's own text for its value
  (selected as text, given back as text, converted back by the database), never as a Python datetime: SQL Server's
  datetime2 holds 100 ns and a Python datetime 1 us, and a cursor rounded down reads its own row again.
* **A row committed late is not stepped over** (settle_seconds). An id or a time is taken when a row is written but is
  seen only when its transaction commits, so a transaction that took id 41 and commits after the one that took 42 lands
  behind a cursor already at 42: a gap no restart repairs. Each poll therefore notes the highest cursor value there is,
  waits settle_seconds, and reads only up to that value: every transaction shorter than settle_seconds is in.
* **Read only.** The source sends SELECTs and nothing else, on a session the database itself holds read only where it
  can (PostgreSQL and MySQL: a read-only session; SQLite: the file opened read only). SQL Server has no such switch for
  a session: there the login is the guarantee, so give the proxy a login that may only SELECT the table or view.
* **Parameterized queries only.** Every value (a cursor value, a key, a limit) goes to the driver as a parameter. A name
  (the table, a column) cannot be a parameter, so each is checked against a strict pattern when the source is built
  and then quoted for its engine.

A row with no cursor value or no key cannot be placed in the order and is never read: the source counts such rows when
it first connects and says so. Two rows with the same cursor value AND the same key cannot be told apart either, and a
restart between them would skip one, so the source stops before them and names them (the fix is a key that is unique).
A database that answers the rows after a place with the row AT that place (a value that does not compare back the way
it was read) would have the source read that row forever; it stops instead, and names the place.

Reading again from a point (tp-proxy run --replay SOURCE=POINT, see rewind): the point is a value of the cursor
column, compared with the column by the database's own rules for its type, and the log says where the replay reads
again from, or that no row has reached the point yet, and whether the point is after the place kept (which skips the
rows between).

The record: `record_id` is the key's value (a JSON list of the values for a key of several columns). When the cursor
is not part of the key (a timestamp cursor), the cursor value is part of the id as well, so a row changed later (a new
changed_at) is a new record, and the same version of it read again is the same record. `payload` is the row, every
column as JSON (a decimal and a time as text, bytes in base64); `meta` holds the table, the cursor value and the key.

The drivers are optional extras: theprotocol-sdk[proxy-postgresql] (psycopg), [proxy-mysql] (PyMySQL),
[proxy-sqlserver] (pymssql), or [proxy-sql] for all three; SQLite needs none (its `path` is a file name taken as
written, a relative one read from the proxy's working directory). The driver runs in a thread of its own, so a slow
query never holds up the rest of the proxy.
"""
from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import datetime as _dt
import decimal
import importlib
import json
import math
import re
import urllib.parse
import uuid
from typing import Any, AsyncIterator, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..plugins import PluginError, Record, Source
from ..spec import is_ref

ENGINES = ("postgresql", "mysql", "sqlserver", "sqlite")
CURSOR_TYPES = ("id", "timestamp")

# A name the source writes into SQL: letters, digits, underscore, dollar, space and hyphen, starting with a letter or
# an underscore. No quote character of any of the engines can be in it, so quoting it is safe in every one of them.
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$ -]{0,127}$")
# A column type as SQL Server's catalog names it: int, varchar(40), datetime2(7), decimal(18, 0), nvarchar(max).
_SQLSERVER_TYPE = re.compile(r"^[a-z][a-z0-9_]{0,63}(?:\(\s*(?:\d{1,5}|max)\s*(?:,\s*\d{1,5}\s*)?\))?$")
# What a replay point looks like: an integer for an id cursor; a date, a time, a zone for a timestamp cursor.
_POINT_ID = re.compile(r"^[+-]?\d{1,30}$")
_POINT_TS = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,9})?)?)?"
                       r"(Z|[+-]\d{2}(?::?\d{2})?)?$")          # group 7: the zone, when the point names one
# A connect_args key that holds a credential. The spec's own rule sees a key that ENDS in such a word after a separator
# (ssl_password); a driver's own spelling has none (libpq's sslpassword), so here the word anywhere in the key counts.
_CREDENTIAL = re.compile(r"password|passwd|passphrase|secret", re.I)

_C = "__tp_c"            # the column the source selects its cursor value as
_K = "__tp_k"            # __tp_k0, __tp_k1, ...: the key's columns
_STATE_KEY = "sqlpoll.cursor"

_sleep = asyncio.sleep   # what the source waits with (a test puts something in its place)


def _name(value: Any, what: str) -> str:
    text = value if isinstance(value, str) else ""
    if not _NAME.match(text) or text != text.strip():
        raise PluginError(f"sqlpoll: {what} {value!r} is not a name this source writes into SQL (letters, digits, "
                          f"_ $ space and -, starting with a letter or _): a name cannot be a query parameter, so "
                          f"anything else is refused rather than quoted")
    return text


def _written_credentials(node: Any, at: str) -> List[str]:
    """The paths under `node` whose key names a credential and whose value is written out rather than a reference."""
    out: List[str] = []
    if isinstance(node, Mapping):
        for k, v in node.items():
            here = f"{at}.{k}"
            if isinstance(v, str) and v and _CREDENTIAL.search(str(k)) and not is_ref(v):
                out.append(here)
            out.extend(_written_credentials(v, here))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(_written_credentials(v, f"{at}[{i}]"))
    return out


def _json(v: Any) -> Any:
    """A column's value as JSON: what a mapping reads in the record's payload."""
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else str(v)
    if isinstance(v, decimal.Decimal):
        return str(v)                                   # exact; a float would round it
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        return v.isoformat()
    if isinstance(v, _dt.timedelta):
        return str(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(v)).decode("ascii")
    if isinstance(v, (list, tuple)):
        return [_json(x) for x in v]
    if isinstance(v, Mapping):
        return {str(k): _json(x) for k, x in v.items()}
    return str(v)


# ── the engines ──────────────────────────────────────────────────────────────────────────────────────────────────────

class _Dialect:
    """How one engine is spoken to: its quoting, its placeholder, its LIMIT, its text for a time, its session."""

    engine = ""
    module = ""          # the driver's module
    extra = ""           # the SDK extra that brings it
    port = 0
    ph = "%s"            # the driver's placeholder
    row_compare = True   # (a, b) > (x, y)
    limit_first = False  # the limit's parameter comes before the others (SELECT TOP (n) ...)

    def quote(self, name: str) -> str:
        return f'"{name}"'

    def as_text(self, expr: str) -> str:
        return f"CAST({expr} AS text)"

    def select(self, columns: str, table: str, where: str, order: str) -> str:
        return f"SELECT {columns} FROM {table}{where} ORDER BY {order} LIMIT {self.ph}"

    def connect(self, c: Mapping[str, Any]) -> Any:  # pragma: no cover - each engine has its own
        raise NotImplementedError


class _Postgres(_Dialect):
    engine, module, extra, port = "postgresql", "psycopg", "proxy-postgresql", 5432

    def connect(self, c: Mapping[str, Any]) -> Any:
        import psycopg
        args = {"host": c.get("host"), "port": c.get("port"), "dbname": c.get("database"), "user": c.get("user"),
                "password": c.get("password")}
        args = {k: v for k, v in args.items() if v not in (None, "")}
        args.update(c.get("args") or {})
        args.setdefault("connect_timeout", max(2, int(math.ceil(c["timeout"]))))
        conn = psycopg.connect(autocommit=True, **args)
        try:
            cur = conn.cursor()
            # every transaction of this session is read only; times come back in UTC and in ISO form, so the text
            # of a cursor value is the same on every read
            cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
            cur.execute("SET TIME ZONE 'UTC'")
            cur.execute("SET DateStyle TO ISO")
            cur.execute("SELECT set_config('statement_timeout', %s, false)", (str(int(c["timeout"] * 1000)),))
            cur.close()
        except Exception:
            conn.close()
            raise
        return conn


class _MySQL(_Dialect):
    engine, module, extra, port = "mysql", "pymysql", "proxy-mysql", 3306
    # MySQL takes no index range from a row comparison: (at, id) > (:c, :k) read the table from its start on every
    # poll (measured on 8.4, 20,000 rows, the place near the end: 19,991 rows read for one batch of 51). Spelled out,
    # the same order is a range that starts at the place (50 rows), also inside a tie, where `at >= :c` in front of
    # the row comparison still read the whole tie before the place (1,051 of a tie of 2,000).
    row_compare = False

    def quote(self, name: str) -> str:
        return f"`{name}`"

    def as_text(self, expr: str) -> str:
        return f"CAST({expr} AS CHAR)"

    def connect(self, c: Mapping[str, Any]) -> Any:
        import pymysql
        t = float(c["timeout"])
        args = {"host": c.get("host"), "port": int(c.get("port") or self.port), "user": c.get("user"),
                "password": c.get("password") or "", "database": c.get("database"), "charset": "utf8mb4",
                "autocommit": True, "connect_timeout": max(1, int(math.ceil(t))), "read_timeout": t,
                "write_timeout": t}
        args = {k: v for k, v in args.items() if v is not None}
        args.update(c.get("args") or {})
        conn = pymysql.connect(**args)
        try:
            cur = conn.cursor()
            # autocommit: each SELECT is a transaction of its own, so a poll sees what committed since the last one
            # (one long transaction would keep one snapshot, and see nothing new, under REPEATABLE READ)
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            cur.execute("SET time_zone = '+00:00'")
            cur.execute("SET SESSION max_execution_time = %s", (int(t * 1000),))
            cur.close()
        except Exception:
            conn.close()
            raise
        return conn


class _SqlServer(_Dialect):
    engine, module, extra, port = "sqlserver", "pymssql", "proxy-sqlserver", 1433
    row_compare, limit_first = False, True

    def quote(self, name: str) -> str:
        return f"[{name}]"

    def as_text(self, expr: str) -> str:
        return f"CONVERT(varchar(40), {expr}, 126)"   # ISO 8601 with a T: read back the same whatever DATEFORMAT is

    def select(self, columns: str, table: str, where: str, order: str) -> str:
        return f"SELECT TOP ({self.ph}) {columns} FROM {table}{where} ORDER BY {order}"

    def connect(self, c: Mapping[str, Any]) -> Any:
        import pymssql
        t = max(1, int(math.ceil(float(c["timeout"]))))
        args = {"server": c.get("host"), "port": str(c.get("port") or self.port), "user": c.get("user"),
                "password": c.get("password"), "database": c.get("database"), "login_timeout": t, "timeout": t,
                "autocommit": True}
        args = {k: v for k, v in args.items() if v not in (None, "")}
        args.update(c.get("args") or {})
        return pymssql.connect(**args)


class _SQLite(_Dialect):
    engine, module, extra, port = "sqlite", "sqlite3", "", 0
    ph = "?"

    def as_text(self, expr: str) -> str:
        return f"CAST({expr} AS TEXT)"

    def connect(self, c: Mapping[str, Any]) -> Any:
        import sqlite3
        uri = "file:" + urllib.parse.quote(str(c["path"])) + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=float(c["timeout"]), isolation_level=None)
        conn.execute("PRAGMA query_only = ON")
        return conn


_DIALECTS: Dict[str, Callable[[], _Dialect]] = {
    "postgresql": _Postgres, "mysql": _MySQL, "sqlserver": _SqlServer, "sqlite": _SQLite}


# ── the statements ───────────────────────────────────────────────────────────────────────────────────────────────────

class Statements:
    """The SQL the source sends, built from checked names, with every value a parameter.

    `types` (SQL Server, filled when the source first connects) is each cursor and key column's own type, so a value is
    compared AS that type: a parameter is sent as nvarchar, and a varchar column compared with an nvarchar converts the
    column, which under a SQL collation can order differently from the column's own ORDER BY (and scans the index)."""

    def __init__(self, dialect: _Dialect, *, table: Sequence[str], columns: Optional[Sequence[str]], cursor: str,
                 cursor_type: str, keys: Sequence[str]):
        self.d = dialect
        self.table = ".".join(table)
        self.table_sql = ".".join(dialect.quote(p) for p in table)
        self.columns_sql = "*" if not columns else ", ".join(dialect.quote(c) for c in columns)
        self.cursor, self.cursor_type = cursor, cursor_type
        self.keys = list(keys)                                  # what names a record
        self.ties = [k for k in self.keys if k != cursor]       # what tells apart rows with the same cursor value
        self.types: Dict[str, str] = {}

    def q(self, name: str) -> str:
        return self.d.quote(name)

    def param(self, column: str) -> str:
        t = self.types.get(column)
        return f"CAST({self.d.ph} AS {t})" if t else self.d.ph

    def _cursor_value(self, expr: Optional[str] = None) -> str:
        e = expr or self.q(self.cursor)
        return self.d.as_text(e) if self.cursor_type == "timestamp" else e

    def _placed(self) -> str:
        cols = [self.cursor] + [k for k in self.keys if k != self.cursor]
        return " AND ".join(f"{self.q(c)} IS NOT NULL" for c in cols)

    def after(self, pos: Optional[Mapping[str, Any]]) -> Tuple[str, List[Any]]:
        """The rows after a place: every row for none; `cursor >= point` for a point (a replay); and for a committed
        row, the rows after it in (cursor, key) order."""
        if pos is None:
            return "", []
        c = self.q(self.cursor)
        if pos.get("k") is None:
            return f"{c} >= {self.param(self.cursor)}", [pos["c"]]
        cols = [self.cursor] + self.ties
        vals = [pos["c"]] + list(pos["k"])
        if len(cols) == 1:
            return f"{c} > {self.param(self.cursor)}", vals
        if self.d.row_compare:
            return (f"({', '.join(self.q(x) for x in cols)}) > ({', '.join(self.param(x) for x in cols)})", vals)
        # no row comparison (SQL Server has none; MySQL takes no index range from one): the same order, spelled out.
        # No `cursor >= :c` in front of it: measured, it adds nothing on MySQL and turns SQL Server's seek into a scan
        # of the table when the place is inside a tie.
        terms: List[str] = []
        params: List[Any] = []
        for i in range(len(cols)):
            parts = [f"{self.q(cols[j])} = {self.param(cols[j])}" for j in range(i)]
            parts.append(f"{self.q(cols[i])} > {self.param(cols[i])}")
            terms.append("(" + " AND ".join(parts) + ")")
            params.extend(vals[:i + 1])
        return "(" + " OR ".join(terms) + ")", params

    def _with_limit(self, sql: str, params: List[Any], limit: int) -> Tuple[str, List[Any]]:
        return sql, ([limit] + params) if self.d.limit_first else (params + [limit])

    def select(self, pos: Optional[Mapping[str, Any]], bound: Any, limit: int) -> Tuple[str, List[Any]]:
        """The next rows after `pos`, up to the cursor value `bound` (none: no bound), at most `limit` of them."""
        conds, params = [self._placed()], []
        where, p = self.after(pos)
        if where:
            conds.append(where)
            params.extend(p)
        if bound is not None:
            conds.append(f"{self.q(self.cursor)} <= {self.param(self.cursor)}")
            params.append(bound)
        extra = [f"{self._cursor_value()} AS {self.q(_C)}"]
        extra += [f"{self.q(k)} AS {self.q(_K + str(i))}" for i, k in enumerate(self.keys)]
        order = ", ".join(self.q(x) for x in [self.cursor] + self.ties)
        sql = self.d.select(", ".join([self.columns_sql] + extra), self.table_sql,
                            " WHERE " + " AND ".join(conds), order)
        return self._with_limit(sql, params, limit)

    def last(self) -> Tuple[str, List[Any]]:
        """The last row in (cursor, key) order: where `from_start: false` begins."""
        extra = [f"{self._cursor_value()} AS {self.q(_C)}"]
        extra += [f"{self.q(k)} AS {self.q(_K + str(i))}" for i, k in enumerate(self.keys)]
        order = ", ".join(f"{self.q(x)} DESC" for x in [self.cursor] + self.ties)
        sql = self.d.select(", ".join(extra), self.table_sql, " WHERE " + self._placed(), order)
        return self._with_limit(sql, [], 1)

    def highest(self) -> Tuple[str, List[Any]]:
        """The highest cursor value there is now (what settle_seconds holds the read to)."""
        return f"SELECT {self._cursor_value('MAX(' + self.q(self.cursor) + ')')} FROM {self.table_sql}", []

    def unplaced(self) -> Tuple[str, List[Any]]:
        """How many rows have no cursor value or no key (and so are never read)."""
        cols = [self.cursor] + [k for k in self.keys if k != self.cursor]
        cond = " OR ".join(f"{self.q(c)} IS NULL" for c in cols)
        return f"SELECT COUNT(*) FROM {self.table_sql} WHERE {cond}", []

    def between(self, low: Any, high: Any) -> Tuple[str, List[Any]]:
        """The first row with a cursor value from `low` up to, not including, `high`: there is one when a replay point
        (`high`) is after the place kept (`low`), and every row between them is then never read. One row, by the
        index, so a large table costs what a small one does."""
        c = self.q(self.cursor)
        where = f" WHERE {self._placed()} AND {c} >= {self.param(self.cursor)} AND {c} < {self.param(self.cursor)}"
        sql = self.d.select(f"{self._cursor_value()} AS {self.q(_C)}", self.table_sql, where, c)
        return self._with_limit(sql, [low, high], 1)

    def describe(self) -> Tuple[str, List[Any]]:
        """SQL Server: the type of each cursor and key column, as the catalog names it."""
        cols = [self.cursor] + [k for k in self.keys if k != self.cursor]
        probe = f"SELECT {', '.join(self.q(c) for c in cols)} FROM {self.table_sql}"
        return "SELECT name, system_type_name FROM sys.dm_exec_describe_first_result_set(%s, NULL, 0)", [probe]


# ── the source ───────────────────────────────────────────────────────────────────────────────────────────────────────

class SqlPollSource(Source):
    """The rows of a table or view, in the order of a cursor column, resumed by (cursor, key)."""

    name = "sqlpoll"
    description = ("The rows of a table or view (PostgreSQL, MySQL, SQL Server or SQLite), read in the order of a "
                   "cursor column and resumed where they stopped, read only.")
    config_schema: Mapping[str, Any] = {
        "type": "object",
        "required": ["engine", "table", "cursor"],
        "additionalProperties": False,
        "properties": {
            "engine": {"enum": list(ENGINES),
                       "description": "postgresql, mysql or sqlserver; sqlite reads a database file."},
            "host": {"type": "string", "description": "The database server (all but sqlite)."},
            "port": {"type": "integer", "minimum": 1, "maximum": 65535,
                     "description": "Its port (default: 5432, 3306 or 1433)."},
            "database": {"type": "string", "description": "The database to read (all but sqlite)."},
            "user": {"type": "string", "description": "A login that may only SELECT the table or view."},
            "password": {"type": "string", "x-secret": True,
                         "description": "The login's password: a reference (env:NAME or file:/path)."},
            "path": {"type": "string",
                     "description": "sqlite: the database file's name, taken as written (not a reference, not a "
                                    "file: URI), opened read only; a relative one is read from the proxy's working "
                                    "directory."},
            "connect_args": {"type": "object",
                             "description": "More of the driver's connect arguments (TLS and the like). A value may be "
                                            "a reference, and one whose key names a password, a passphrase or a "
                                            "secret must be. The login itself goes in user and password."},
            "table": {"type": "string",
                      "description": "The table or view, with its schema if it needs one (sales.order_events)."},
            "columns": {"type": "array", "items": {"type": "string"}, "minItems": 1, "uniqueItems": True,
                        "description": "The columns a record carries (default: all of them)."},
            "cursor": {"type": "string",
                       "description": "The column the rows are read in the order of. Its values must only grow as "
                                      "rows are written: the database's own sequence, or a time the writer sets as it "
                                      "writes (now()); a date a person types in is not a cursor (a row dated behind "
                                      "the place is never read). Index it with the key, in that order: each poll asks "
                                      "for the rows after a place in that order."},
            "cursor_type": {"enum": list(CURSOR_TYPES), "default": "id",
                            "description": "id: an integer that only grows (an identity, a sequence). timestamp: a "
                                           "time set as the row is written (a date or a time column), carried as the "
                                           "database's own text for it."},
            "key": {"anyOf": [{"type": "string"},
                              {"type": "array", "items": {"type": "string"}, "minItems": 1, "uniqueItems": True}],
                    "description": "The column (or columns) that tell apart rows with the same cursor value and name "
                                   "a record: unique as the database compares it (a case-insensitive column counts A "
                                   "and a as one). Default: the cursor itself (an id is unique). A timestamp cursor "
                                   "needs one."},
            "batch_size": {"type": "integer", "minimum": 1, "maximum": 100000, "default": 500,
                           "description": "How many rows one query reads."},
            "poll_seconds": {"type": "number", "minimum": 0, "default": 10,
                             "description": "How long to wait before reading again once every row is read. 0: read "
                                            "once and finish (for tp-proxy run --once)."},
            "settle_seconds": {"type": "number", "minimum": 0, "default": 5,
                               "description": "Each poll reads only up to the highest cursor value it saw this long "
                                              "before, so a transaction that took a lower id or an earlier time and "
                                              "commits later is still read. Longer than the legacy system's longest "
                                              "writing transaction. 0 reads at once and accepts that risk."},
            "from_start": {"type": "boolean", "default": True,
                           "description": "With no place kept yet: read the rows already there (default), or only "
                                          "the rows that arrive next."},
            "timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "default": 30,
                                "description": "How long connecting, and each query, may take."},
        },
    }

    def __init__(self, config: Mapping[str, Any], ctx: Any) -> None:
        super().__init__(config, ctx)
        cfg = self.config
        engine = str(cfg.get("engine") or "")
        if engine not in _DIALECTS:
            raise PluginError(f"sqlpoll: engine {engine!r} is not one of {', '.join(ENGINES)}")
        self._d = _DIALECTS[engine]()
        table = cfg.get("table")
        if not isinstance(table, str) or not 1 <= len(table.split(".")) <= 3:
            raise PluginError(f"sqlpoll: table {table!r} is a name, or schema.name (database.schema.name)")
        parts = [_name(p, "the table name part") for p in table.split(".")]
        cursor = _name(cfg.get("cursor"), "cursor")
        self._type = str(cfg.get("cursor_type") or "id")
        if self._type not in CURSOR_TYPES:
            raise PluginError(f"sqlpoll: cursor_type {self._type!r} is not one of {', '.join(CURSOR_TYPES)}")
        raw_key = cfg.get("key")
        keys = [raw_key] if isinstance(raw_key, str) else list(raw_key or [])
        keys = [_name(k, "key") for k in keys]
        if len(set(keys)) != len(keys):
            raise PluginError(f"sqlpoll: key {raw_key!r} names a column twice")
        if not keys:
            if self._type == "timestamp":
                raise PluginError("sqlpoll: a timestamp cursor needs a key: rows written at the same time are told "
                                  "apart by it, and a restart between them would lose some without one")
            keys = [cursor]
        columns = cfg.get("columns")
        if columns is not None:
            if not isinstance(columns, (list, tuple)) or not columns:
                raise PluginError("sqlpoll: columns is a list of column names")
            columns = [_name(c, "column") for c in columns]
            if len(set(columns)) != len(columns):
                raise PluginError("sqlpoll: columns names a column twice")
        if engine == "sqlite":
            path = cfg.get("path")
            if not isinstance(path, str) or not path:
                raise PluginError("sqlpoll: the sqlite engine reads a database file: name it in path")
            if is_ref(path) or path.strip().lower().startswith("file:"):
                # a reference would be resolved to the CONTENT of a file (SQLite's own URI spelling, file:erp.db, reads
                # exactly like one), and the log's redactor resolves every reference in the spec
                raise PluginError(f"sqlpoll: path {path!r} reads like a reference or a file: URI; a path is the "
                                  f"database file's name, taken as written (the source opens it read only itself; a "
                                  f"relative one is read from the proxy's working directory)")
        elif not isinstance(cfg.get("host"), str) or not cfg.get("host"):
            raise PluginError(f"sqlpoll: the {engine} engine needs a host")
        args = cfg.get("connect_args")
        if args is not None and not isinstance(args, Mapping):
            raise PluginError("sqlpoll: connect_args is an object of the driver's connect arguments")
        written = _written_credentials(args or {}, "connect_args")
        if written:
            raise PluginError(f"sqlpoll: {', '.join(written)} holds a credential written out: give it as a reference "
                              f"(env:NAME or file:/path), as the password is given")
        self._batch = self._number("batch_size", 500, minimum=1, integer=True)
        self._poll = self._number("poll_seconds", 10, minimum=0)
        self._settle = self._number("settle_seconds", 5, minimum=0)
        self._timeout = self._number("timeout_seconds", 30, minimum=0, strict=True)
        self._from_start = bool(cfg.get("from_start", True))
        self._cursor, self._keys = cursor, keys
        self._tie_index = [i for i, k in enumerate(keys) if k != cursor]
        self._sql = Statements(self._d, table=parts, columns=columns, cursor=cursor, cursor_type=self._type,
                               keys=keys)
        # what the kept place is a place IN: another database's rows are not below it. The database as the spec writes
        # it (a reference as written, so a rotated secret changes nothing); host and port left out, so a failover or a
        # move of the server keeps the place.
        where = {"path": cfg.get("path")} if engine == "sqlite" else {"database": cfg.get("database")}
        self._reads = {"engine": engine, **where, "table": self._sql.table, "cursor": cursor,
                       "cursor_type": self._type, "key": list(keys)}
        self._pool: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._conn: Any = None
        self._ready = False
        self._fresh = True
        self._committed: Optional[Dict[str, Any]] = None
        self._other: Optional[Mapping[str, Any]] = None   # a place kept for another table, cursor or key

    def _number(self, field: str, default: float, *, minimum: float, integer: bool = False,
                strict: bool = False) -> Any:
        v = self.config.get(field, default)
        ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))
        if ok and integer:
            ok = float(v).is_integer()
        if not ok or (v <= minimum if strict else v < minimum):
            raise PluginError(f"sqlpoll: {field} {v!r} is not a number {'above' if strict else 'of at least'} "
                              f"{minimum:g}")
        return int(v) if integer else float(v)

    # ── where it reads from ─────────────────────────────────────────────────────────────────────────────────────

    def _resolved(self, v: Any) -> Any:
        if isinstance(v, str) and is_ref(v):
            return self.ctx.secret(v)
        if isinstance(v, Mapping):
            return {str(k): self._resolved(x) for k, x in v.items()}
        if isinstance(v, list):
            return [self._resolved(x) for x in v]
        return v

    def _connect_config(self) -> Dict[str, Any]:
        cfg = self.config
        try:
            out = {f: self._resolved(cfg.get(f)) for f in ("host", "database", "user", "password")}
            out["args"] = self._resolved(dict(cfg.get("connect_args") or {}))
        except Exception as e:  # noqa: BLE001 - a reference that does not resolve; its value is never in the message
            raise PluginError(f"sqlpoll: a reference in the connection does not resolve: {e}") from None
        out["path"] = cfg.get("path")      # a file name, taken as written: never a reference
        out["port"] = cfg.get("port")
        out["timeout"] = self._timeout
        return out

    def _reading(self, reads: Optional[Mapping[str, Any]]) -> str:
        r = reads or {}
        key = r.get("key")
        key = ", ".join(map(str, key)) if isinstance(key, list) else key
        text = f"{r.get('table')} by {r.get('cursor')} ({r.get('cursor_type')}), key {key}"
        if r.get("engine"):
            where = r.get("path") if r.get("engine") == "sqlite" else r.get("database")
            text += f", on {r.get('engine')}" + (f" {where}" if where else "")
        return text

    # ── the worker thread: every call to the driver happens on it ────────────────────────────────────────────────

    def _close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - a connection that is already gone
                pass

    def _guarded(self, fn: Callable[..., Any], *args: Any) -> Any:
        try:
            return fn(*args)
        except Exception:
            self._close()      # the connection may be broken: the next call connects again
            raise

    async def _db(self, fn: Callable[..., Any], *args: Any) -> Any:
        if self._pool is None:
            raise PluginError("sqlpoll: the source is not started")
        return await asyncio.get_running_loop().run_in_executor(self._pool, self._guarded, fn, *args)

    def _open(self, c: Mapping[str, Any]) -> None:
        self._close()
        self._conn = self._d.connect(c)

    def _query(self, sql: str, params: Sequence[Any]) -> Tuple[List[str], List[Sequence[Any]]]:
        cur = self._conn.cursor()
        try:
            if params:
                cur.execute(sql, tuple(params))
            else:
                cur.execute(sql)
            rows = list(cur.fetchall())
            names = [d[0] for d in (cur.description or [])]
        finally:
            try:
                cur.close()
            except Exception:  # noqa: BLE001
                pass
        return names, rows

    def _scalar(self, stmt: Tuple[str, List[Any]]) -> Any:
        _, rows = self._query(*stmt)
        return rows[0][0] if rows else None

    # ── the values ──────────────────────────────────────────────────────────────────────────────────────────────

    def _cursor_value(self, v: Any) -> Any:
        if self._type == "timestamp":
            if isinstance(v, (bytes, bytearray)):
                v = bytes(v).decode("utf-8")
            return v if isinstance(v, str) else str(v)
        if isinstance(v, int) and not isinstance(v, bool):
            return v
        if isinstance(v, decimal.Decimal) and v.is_finite() and v == v.to_integral_value():
            return int(v)
        raise PluginError(f"sqlpoll: the cursor column {self._cursor} holds a {type(v).__name__} ({v!r}): an id "
                          f"cursor takes integers (a date or a time is cursor_type: timestamp)")

    def _key_value(self, v: Any, column: str) -> Any:
        if isinstance(v, (int, str)) and not isinstance(v, bool):
            return v
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, decimal.Decimal) and v.is_finite() and v == v.to_integral_value():
            return int(v)
        raise PluginError(f"sqlpoll: the key column {column} holds a {type(v).__name__}: a key is an integer, a text "
                          f"or a UUID")

    def _row(self, names: Sequence[str], row: Sequence[Any]) -> Tuple[Dict[str, Any], Any, List[Any]]:
        """(payload, cursor value, key values) of one row as selected (its payload columns, then the source's own)."""
        n = len(names) - 1 - len(self._keys)
        payload = {str(names[i]): _json(row[i]) for i in range(n)}
        cursor = self._cursor_value(row[n])
        # a key that names the cursor column (key: [changed_at, event_id]) holds the cursor's own text there, the value
        # the place and the record id carry; the driver's value for the column (a datetime) is no key
        keys = [cursor if k == self._cursor else self._key_value(row[n + 1 + i], k) for i, k in enumerate(self._keys)]
        return payload, cursor, keys

    def _place(self, cursor: Any, keys: Sequence[Any]) -> Dict[str, Any]:
        return {"c": cursor, "k": [keys[i] for i in self._tie_index]}

    def _record_id(self, cursor: Any, keys: Sequence[Any]) -> str:
        if self._keys == [self._cursor]:
            return str(keys[0])
        parts = list(keys) + ([] if self._cursor in self._keys else [cursor])
        return json.dumps(parts, separators=(",", ":"), ensure_ascii=False)

    async def _persist(self) -> None:
        await self.ctx.state.set(_STATE_KEY, {"reads": self._reads, "at": self._committed})

    # ── the plugin ──────────────────────────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        try:
            importlib.import_module(self._d.module)
        except ImportError:
            raise PluginError(f"sqlpoll: the {self._d.engine} engine needs its driver, {self._d.module}: "
                              f"pip install 'theprotocol-sdk[{self._d.extra}]'") from None
        kept = await self.ctx.state.get(_STATE_KEY, None)
        self._fresh = not kept
        self._committed, self._other = None, None
        if kept:
            if kept.get("reads") != self._reads:
                self._other = dict(kept.get("reads") or {})
            else:
                self._committed = kept.get("at")
        if self._pool is None:
            self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="tp-proxy-sqlpoll")

    async def stop(self) -> None:
        pool, self._pool = self._pool, None
        self._ready = False
        if pool is None:
            return
        try:
            await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(pool, self._close),
                                   timeout=self._timeout + 5)
        except Exception:  # noqa: BLE001 - a query still running: its thread closes when it ends
            pass
        finally:
            pool.shutdown(wait=False)

    async def _ensure(self) -> None:
        """Connect (again, after a failure), and on the first connection learn what the source needs to know."""
        if self._conn is None:
            await self._db(self._open, self._connect_config())
        if self._ready:
            return
        if self._d.engine == "sqlserver":
            try:
                _, rows = await self._db(self._query, *self._sql.describe())
            except Exception as e:  # noqa: BLE001 - the catalog said no: the source still reads, comparing as sent
                rows = []
                self.ctx.logger.warning(f"sqlpoll: the column types of {self._sql.table} could not be read "
                                        f"({type(e).__name__}: {e})")
                if self._conn is None:
                    await self._db(self._open, self._connect_config())
            types: Dict[str, str] = {}
            for name, type_name in rows:
                t = str(type_name or "").strip().lower()
                if _SQLSERVER_TYPE.match(t):
                    types[str(name)] = t
            missing = [c for c in [self._cursor] + self._keys if c not in types]
            if missing:
                self.ctx.logger.warning(f"sqlpoll: the type of {', '.join(missing)} in {self._sql.table} is not "
                                        f"known, so a value is compared as the driver sends it")
            self._sql.types = types
        try:
            unplaced = await self._db(self._scalar, self._sql.unplaced())
        except Exception as e:  # noqa: BLE001 - a count for the log: the source reads without it
            unplaced = None
            self.ctx.logger.warning(f"sqlpoll: the rows of {self._sql.table} with no {self._cursor} or no key could "
                                    f"not be counted ({type(e).__name__}: {e}); the source reads on without the count")
            if self._conn is None:
                await self._db(self._open, self._connect_config())
        if unplaced:
            self.ctx.logger.warning(f"sqlpoll: {unplaced} row(s) of {self._sql.table} have no {self._cursor} or no "
                                    f"key ({', '.join(self._keys)}), and are never read: a row is read in the order "
                                    f"of its cursor and key, and these have none to be placed by")
        if self._fresh and self._committed is None and self._other is None:
            if not self._from_start:
                names, rows = await self._db(self._query, *self._sql.last())
                if rows:
                    _, cursor, keys = self._row(names, rows[0])
                    self._committed = self._place(cursor, keys)
            await self._persist()       # so a restart knows this was decided (and the rows since are new)
            self._fresh = False
        self._ready = True

    async def records(self) -> AsyncIterator[Record]:
        if self._other is not None:
            raise PluginError(f"sqlpoll: the place kept in this proxy's state is for {self._reading(self._other)}, "
                              f"and this spec reads {self._reading(self._reads)}: read again from a point to begin "
                              f"(tp-proxy run --replay SOURCE=start, or SOURCE=<a value of {self._cursor}>)")
        await self._ensure()
        pos = self._committed
        while True:
            bound, waited = None, 0.0
            if self._settle > 0:
                high = await self._db(self._scalar, self._sql.highest())
                bound = None if high is None else self._cursor_value(high)
                if bound is not None:
                    await _sleep(self._settle)
                    waited = self._settle
            if self._settle <= 0 or bound is not None:
                while True:
                    asked = pos
                    names, rows = await self._db(self._query, *self._sql.select(pos, bound, self._batch + 1))
                    parts = [self._row(names, r) for r in rows]
                    for i in range(min(len(parts), self._batch)):
                        payload, cursor, keys = parts[i]
                        here = self._place(cursor, keys)
                        if asked is not None and asked.get("k") is not None and here == asked:
                            raise PluginError(
                                f"sqlpoll: asked for the rows of {self._sql.table} after the place "
                                f"{json.dumps([here['c'], here['k']], default=str)} ({self._cursor}, then the key), "
                                f"the database answered with the row at that place itself: its {self._cursor} or key "
                                f"does not compare back the way it was read, and the source would read that row "
                                f"forever. It stops here, with the place it had.")
                        if i + 1 < len(parts) and self._place(parts[i + 1][1], parts[i + 1][2]) == here:
                            raise PluginError(
                                f"sqlpoll: two rows of {self._sql.table} have the same {self._cursor} and key "
                                f"({', '.join(self._keys)}): {json.dumps([cursor] + list(keys), default=str)}. No "
                                f"key tells them apart, so a restart between them would skip one; the source stops "
                                f"before them. Name a key that is unique.")
                        pos = here
                        yield Record(record_id=self._record_id(cursor, keys), payload=payload,
                                     meta={"table": self._sql.table, "cursor": cursor, "key": keys})
                    if len(parts) <= self._batch:
                        break
            if self._poll <= 0:
                return
            await _sleep(max(0.0, self._poll - waited))

    async def committed(self, record: Record) -> None:
        m = record.meta or {}
        keys = m.get("key")
        if "cursor" not in m or not isinstance(keys, list) or len(keys) != len(self._keys):
            return
        self._committed = self._place(m["cursor"], keys)
        self._fresh = False
        await self._persist()

    async def rewind(self, point: str) -> None:
        """`point` is "start" (every row again) or a value of the cursor column: an integer for an id cursor, a date
        or a time for a timestamp cursor (2026-11-08, 2026-11-08 10:00:00.5, 2026-11-08T10:00:00Z). The rows with that
        value or a later one are read again. Records already in the outbox are not sent twice: their keys are there.

        The database compares the point with the column, by its own rules for the column's type. A time without a
        zone is the column's own time (on a column that keeps a zone: UTC, the zone the source's session reads in). A
        time WITH a zone on a column that keeps none is where the engines differ: PostgreSQL (timestamp) and SQL
        Server (datetime2) drop the zone and take the time as the column's own, MySQL (DATETIME) turns it into UTC; a
        column that keeps a zone (timestamptz, datetimeoffset, MySQL's TIMESTAMP) compares the instant it names.

        Before the place moves, two reads of one row each, by the index, say what the replay does, in the log: where
        it reads again from (or that no row has reached the point yet), and whether the point is AFTER the place kept,
        which moves the place forward: every row between them is then never read, those not read yet and any written
        later. It is done (the operator asked for it), and said. A point the database cannot read leaves the place as
        it was, and the error is the database's own."""
        text = str(point or "").strip()
        if not text:
            raise PluginError("sqlpoll: a replay point is 'start' or a value of the cursor column")
        zone = False
        if text.lower() == "start":
            self._committed, self._other, self._fresh = None, None, False
            await self._persist()
            self.ctx.logger.info(f"sqlpoll: a replay of {self._sql.table} from start reads every row of it again")
            return
        if self._type == "id":
            if not _POINT_ID.match(text):
                raise PluginError(f"sqlpoll: {point!r} is not an integer, and {self._cursor} is an id cursor")
            place: Dict[str, Any] = {"c": int(text), "k": None}
        else:
            m = _POINT_TS.match(text)
            try:
                ok = bool(m) and bool(_dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
                if ok and m.group(4):
                    _dt.time(int(m.group(4)), int(m.group(5)), int(m.group(6) or 0))
            except ValueError:
                ok = False
            if not ok:
                raise PluginError(f"sqlpoll: {point!r} is not a date or a time (2026-11-08, 2026-11-08 10:00:00, "
                                  f"2026-11-08T10:00:00Z)")
            zone = bool(m.group(7))
            place = {"c": text, "k": None}
        kept: Optional[Mapping[str, Any]] = None
        skipped: List[Sequence[Any]] = []
        try:
            await self._ensure()
            kept = self._committed if self._other is None else None
            names, first = await self._db(self._query, *self._sql.select(place, None, 1))
            if kept is not None:
                _, skipped = await self._db(self._query, *self._sql.between(kept["c"], place["c"]))
        except PluginError:
            raise
        except Exception as e:  # noqa: BLE001 - the database's own words; nothing has changed
            raise PluginError(f"sqlpoll: {self._sql.table} could not be read from the replay point {point!r}, so the "
                              f"place kept is unchanged: {type(e).__name__}: {e}") from None
        if first:
            _, at, _ = self._row(names, first[0])
            self.ctx.logger.info(f"sqlpoll: a replay of {self._sql.table} from {text} reads it again from the row "
                                 f"with {self._cursor} {at}")
        else:
            hint = (" A point with a zone, on a column that keeps none, is read as that database reads it: PostgreSQL "
                    "and SQL Server drop the zone, MySQL turns the time into UTC." if zone else "")
            self.ctx.logger.warning(f"sqlpoll: no row of {self._sql.table} has {self._cursor} {text} or later: a "
                                    f"replay from there reads nothing again now, and reads the rows from that point on "
                                    f"as they arrive.{hint}")
        if skipped and kept is not None:
            self.ctx.logger.warning(f"sqlpoll: the replay point {text} is after the place kept in {self._sql.table} "
                                    f"({self._cursor} {kept['c']}): the rows after that place and before the point are "
                                    f"never read, those not read yet and any written later alike")
        self._committed, self._other, self._fresh = place, None, False
        await self._persist()
