"""The `sql_upsert` writer: each mapped record is written into a table of the NEW system, by key.

    sinks:
      crm:
        type: sql_upsert
        config:
          engine: postgresql             # postgresql, mysql, sqlserver or sqlite
          host: new-db.internal
          database: crm
          user: tp_migrate               # a login that may write the target tables and nothing else
          password: env:NEW_DB_PASSWORD  # a reference, never the password itself
          table: public.customers
          key: [legacy_id]               # the target's unique key columns
          on_conflict: update            # update (default) or skip
          preimage: true                 # keep the row each key held before the migration, for the way back

What it promises, and how each promise holds:

* **One key, one write.** A delivery key seen again writes nothing; a NEW record for the same row updates it (on_conflict:
  update) or leaves it (skip). The write is one atomic upsert in the engine's own form: INSERT ... ON CONFLICT (PostgreSQL,
  SQLite), INSERT ... ON DUPLICATE KEY UPDATE (MySQL), MERGE ... WITH (HOLDLOCK) (SQL Server).
* **The way back.** The first time a row's key is seen, the row it held is read in the SAME transaction as the write and kept
  in the proxy's state (a missing row is kept as null), and the state has it BEFORE the transaction commits: a stop in
  between loses nothing. Only that first, oldest pre-image is kept (a second write does not replace it). restore_preimages
  puts the rows back newest first: a null pre-image deletes the row, a row restores it; it can be run again.
* **Values are parameters, names are checked.** Every value goes to the driver as a parameter. A table or column name (it
  cannot be a parameter) must match the pattern sqlpoll uses and is quoted for its engine.
* **A refusal names the column and never the value.** A driver's own error text carries values (Key (id)=(5), invalid input
  syntax for ...: "x"), so it is never repeated: the refusal names the table, the kind of error and, when the driver says
  which, the column. A lost connection, a deadlock or a lock wait is a Retry; a constraint, a type or a name error is Refused.
* **A dry run writes nothing**: no connection is opened, nothing is kept in the state; the outcome names the table and the
  columns, never a value.

The tables are the customer's: this writer never creates or alters one. The login should be allowed to INSERT, UPDATE and
SELECT the target tables (and DELETE, if a rollback may delete rows that did not exist before). The drivers are the sqlpoll
extras ([proxy-postgresql], [proxy-mysql], [proxy-sqlserver]; SQLite needs none), imported when the writer first connects.
"""
from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import datetime as _dt
import decimal
import hashlib
import json
import math
import re
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..plugins import Event, Outcome, PluginError, Refused, Retry, Sink
from ..sources.sqlpoll import ENGINES, _DIALECTS, _name, _written_credentials
from ..spec import is_ref
from ._json import dumps as _dumps

ON_CONFLICT = ("update", "skip")
_PRE_N = "pre_n"            # how many pre-images are kept; pre_at:<i> holds the i-th one's hash (append-only)


# ── the statements (pure: pinned in the tests, one per engine) ───────────────────────────────────────────────────

def _q(engine: str, name: str) -> str:
    return _DIALECTS[engine]().quote(name)


def _table(engine: str, parts: Sequence[str]) -> str:
    return ".".join(_q(engine, p) for p in parts)


def upsert_statement(engine: str, table: Sequence[str], columns: Sequence[str], key: Sequence[str], on_conflict: str) -> str:
    """The upsert of one row: `columns` in the order the parameters come, `key` the unique columns. Every value is a
    placeholder; the names are quoted for the engine."""
    d = _DIALECTS[engine]()
    q = lambda n: d.quote(n)                                       # noqa: E731
    tbl, ph = _table(engine, table), d.ph
    values = ", ".join([ph] * len(columns))
    cols = ", ".join(q(c) for c in columns)
    loose = [c for c in columns if c not in key]
    update = on_conflict == "update" and bool(loose)
    if engine in ("postgresql", "sqlite"):
        ex = "EXCLUDED" if engine == "postgresql" else "excluded"
        head = f"INSERT INTO {tbl} ({cols}) VALUES ({values}) ON CONFLICT ({', '.join(q(k) for k in key)})"
        if not update:
            return head + " DO NOTHING"
        return head + " DO UPDATE SET " + ", ".join(f"{q(c)} = {ex}.{q(c)}" for c in loose)
    if engine == "mysql":
        head = f"INSERT INTO {tbl} ({cols}) VALUES ({values}) ON DUPLICATE KEY UPDATE "
        if not update:
            return head + f"{q(key[0])} = {q(key[0])}"
        return head + ", ".join(f"{q(c)} = VALUES({q(c)})" for c in loose)
    # sqlserver: MERGE with HOLDLOCK, the only form that does not race an insert against another
    on = " AND ".join(f"tgt.{q(k)} = src.{q(k)}" for k in key)
    sql = (f"MERGE INTO {tbl} WITH (HOLDLOCK) AS tgt USING (VALUES ({values})) AS src ({cols}) ON {on}")
    if update:
        sql += " WHEN MATCHED THEN UPDATE SET " + ", ".join(f"tgt.{q(c)} = src.{q(c)}" for c in loose)
    sql += f" WHEN NOT MATCHED THEN INSERT ({cols}) VALUES ({', '.join('src.' + q(c) for c in columns)});"
    return sql


def preimage_statement(engine: str, table: Sequence[str], key: Sequence[str]) -> str:
    """The row a key holds now, locked for the transaction that is about to change it: FOR UPDATE (PostgreSQL, MySQL),
    WITH (UPDLOCK, HOLDLOCK) (SQL Server); SQLite's BEGIN IMMEDIATE already serializes the writers."""
    d = _DIALECTS[engine]()
    where = " AND ".join(f"{d.quote(k)} = {d.ph}" for k in key)
    tbl = _table(engine, table)
    if engine == "sqlserver":
        return f"SELECT * FROM {tbl} WITH (UPDLOCK, HOLDLOCK) WHERE {where}"
    lock = "" if engine == "sqlite" else " FOR UPDATE"
    return f"SELECT * FROM {tbl} WHERE {where}{lock}"


def delete_statement(engine: str, table: Sequence[str], key: Sequence[str]) -> str:
    d = _DIALECTS[engine]()
    where = " AND ".join(f"{d.quote(k)} = {d.ph}" for k in key)
    return f"DELETE FROM {_table(engine, table)} WHERE {where}"


# ── what an error of each engine means ───────────────────────────────────────────────────────────────────────────

_MYSQL_REFUSE = {1048, 1054, 1062, 1064, 1136, 1146, 1264, 1265, 1292, 1364, 1366, 1406, 1451, 1452, 1054, 1166, 3819}
_MYSQL_RETRY = {1040, 1205, 1213, 2002, 2003, 2006, 2013, 2055, 1317}
_MSSQL_REFUSE = {102, 156, 207, 208, 213, 229, 230, 241, 242, 245, 515, 547, 2601, 2627, 8114, 8115, 8143, 8152}
_MSSQL_RETRY = {1204, 1205, 1222, 20002, 20003, 20004, 20006, 20017, 20047, 20049}


def _code(exc: BaseException) -> Optional[int]:
    a = getattr(exc, "args", ())
    return a[0] if a and isinstance(a[0], int) else None


def classify_error(engine: str, exc: BaseException) -> str:
    """'refuse' for an answer a retry will not change (a constraint, a type, a name), 'retry' for one that may change (a
    connection, a deadlock, a lock wait). What it does not know is a retry: the breaker stops a mapping that keeps failing."""
    if engine == "postgresql":
        st = str(getattr(exc, "sqlstate", "") or "")
        if st[:2] in ("22", "23", "42", "0A", "44") or st in ("2201G",):
            return "refuse"
        return "retry"
    if engine == "mysql":
        c = _code(exc)
        if c in _MYSQL_RETRY:
            return "retry"
        return "refuse" if c in _MYSQL_REFUSE else "retry"
    if engine == "sqlserver":
        c = _code(exc)
        if c in _MSSQL_RETRY:
            return "retry"
        return "refuse" if c in _MSSQL_REFUSE else "retry"
    import sqlite3
    if isinstance(exc, (sqlite3.IntegrityError, sqlite3.DataError, sqlite3.ProgrammingError)):
        return "refuse"
    if isinstance(exc, sqlite3.OperationalError):
        text = str(exc).lower()
        return "retry" if ("locked" in text or "busy" in text or "disk i/o" in text) else "refuse"
    return "retry"


_PATTERNS = {
    "mysql": re.compile(r"[Cc]olumn '([^']+)'"),
    "sqlserver": re.compile(r"[Cc]olumn '([^']+)'"),
    "sqlite": re.compile(r"(?:column named |column |failed: )(?:[A-Za-z0-9_$]+\.)?([A-Za-z0-9_$]+)"),
}


def column_of(engine: str, exc: BaseException, columns: Sequence[str]) -> Optional[str]:
    """The column an error is about, when the DRIVER says which: PostgreSQL's diag.column_name, the quoted column name in
    MySQL's and SQL Server's messages, the dotted name in SQLite's. Only a name among `columns` (the writer's own) is returned;
    nothing else of the driver's text is ever used."""
    found: Optional[str] = None
    if engine == "postgresql":
        found = getattr(getattr(exc, "diag", None), "column_name", None)
    else:
        m = _PATTERNS[engine].search(str(exc))
        found = m.group(1) if m else None
    if isinstance(found, str) and "." in found:
        found = found.rsplit(".", 1)[-1]
    return found if found in set(columns) else None


# ── values ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _param(v: Any, engine: str = "") -> Any:
    """A mapped value as a driver parameter: a dict or a list as compact JSON text; on SQLite a Decimal as its exact text
    (the sqlite3 module refuses a Decimal, and a float would round it; the other drivers bind a Decimal themselves);
    the rest as it is."""
    if isinstance(v, (dict, list)):
        return _dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if engine == "sqlite" and isinstance(v, decimal.Decimal):
        return str(v)
    return v


class _JsonColumn:
    """A value read from a json or jsonb column, so that the state can say it was JSON: a jsonb text value ("hello") and a
    jsonb object read back as the same Python types as a text column and a hstore, and only the column's type tells them apart."""

    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value


_PG_JSON_OIDS = (114, 3802)                          # json, jsonb


def _kept(v: Any) -> Any:
    """A column's value as the state keeps it (JSON): exact for a decimal and a time (text), bytes as {"$b64"}, the value of a
    json or jsonb column as {"$json": value} (a dict that is not marked is the same: a plain JSON object could collide with
    the markers, so the marker is the only object form the state uses), a list as a list (an array column)."""
    if isinstance(v, _JsonColumn):
        return {"$json": json.loads(json.dumps(v.value, default=_kept))}
    if isinstance(v, dict):
        return {"$json": json.loads(json.dumps(v, default=_kept))}
    if isinstance(v, (list, tuple)):
        return [_kept(x) for x in v]
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else str(v)
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"$b64": base64.b64encode(bytes(v)).decode("ascii")}
    return str(v)


def _restored(v: Any) -> Any:
    """A kept value as a driver parameter again: bytes from {"$b64"}, a json or jsonb value as JSON text (the server reads it
    into the column's type; Python's own str() of a dict, with its single quotes, is not JSON and is refused)."""
    if isinstance(v, dict) and set(v) == {"$b64"}:
        return base64.b64decode(v["$b64"])
    if isinstance(v, dict) and set(v) == {"$json"}:
        return json.dumps(v["$json"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return v


def _canon(values: Sequence[Any]) -> str:
    return json.dumps(list(values), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _hash(values: Sequence[Any]) -> str:
    return hashlib.sha256(_canon(values).encode("utf-8")).hexdigest()[:32]


# ── the sink ─────────────────────────────────────────────────────────────────────────────────────────────────────

class SqlUpsertSink(Sink):
    name = "sql_upsert"
    description = ("Write each mapped record into a table by key (PostgreSQL, MySQL, SQL Server or SQLite), keeping the oldest "
                   "pre-image of each key for the way back.")
    config_schema: Mapping[str, Any] = {
        "type": "object",
        "required": ["engine", "table", "key"],
        "additionalProperties": False,
        "properties": {
            "engine": {"enum": list(ENGINES), "description": "postgresql, mysql, sqlserver or sqlite."},
            "host": {"type": "string"}, "port": {"type": "integer", "minimum": 1, "maximum": 65535},
            "database": {"type": "string"}, "user": {"type": "string"},
            "password": {"type": "string", "x-secret": True,
                         "description": "The login's password: a reference (env:NAME or file:/path)."},
            "path": {"type": "string", "description": "sqlite: the database file, taken as written."},
            "connect_args": {"type": "object", "description": "More of the driver's connect arguments (TLS and the like)."},
            "table": {"type": "string", "description": "The target table, with its schema if it needs one (public.customers)."},
            "key": {"type": "array", "items": {"type": "string"}, "minItems": 1, "uniqueItems": True,
                    "description": "The target's unique key columns: the row a record is."},
            "columns": {"type": "array", "items": {"type": "string"}, "minItems": 1, "uniqueItems": True,
                        "description": "An allow-list: only these columns are written (default: every mapped field)."},
            "on_conflict": {"enum": list(ON_CONFLICT), "default": "update"},
            "preimage": {"type": "boolean", "default": True,
                         "description": "Keep each key's first row, for restore_preimages."},
            "timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "default": 30},
        },
    }

    def __init__(self, config: Mapping[str, Any], ctx: Any) -> None:
        super().__init__(config, ctx)
        cfg = self.config
        engine = str(cfg.get("engine") or "")
        if engine not in _DIALECTS:
            raise PluginError(f"sql_upsert: engine {engine!r} is not one of {', '.join(ENGINES)}")
        self.engine = engine
        table = cfg.get("table")
        if not isinstance(table, str) or not 1 <= len(table.split(".")) <= 3:
            raise PluginError(f"sql_upsert: table {table!r} is a name, or schema.name (database.schema.name)")
        self.table: List[str] = [_name(p, "the table name part") for p in table.split(".")]
        self.table_text = ".".join(self.table)
        key = cfg.get("key")
        if not isinstance(key, (list, tuple)) or not key:
            raise PluginError("sql_upsert: key is a list of the target's unique key columns")
        self.keys = [_name(k, "key column") for k in key]
        if len(set(self.keys)) != len(self.keys):
            raise PluginError("sql_upsert: key names a column twice")
        cols = cfg.get("columns")
        self.allow: Optional[List[str]] = None
        if cols is not None:
            if not isinstance(cols, (list, tuple)) or not cols:
                raise PluginError("sql_upsert: columns is a list of column names")
            self.allow = [_name(c, "column") for c in cols]
            if len(set(self.allow)) != len(self.allow):
                raise PluginError("sql_upsert: columns names a column twice")
        self.on_conflict = str(cfg.get("on_conflict") or "update")
        if self.on_conflict not in ON_CONFLICT:
            raise PluginError(f"sql_upsert: on_conflict {self.on_conflict!r} is not one of {', '.join(ON_CONFLICT)}")
        self.preimage = bool(cfg.get("preimage", True))
        if engine == "sqlite":
            path = cfg.get("path")
            if not isinstance(path, str) or not path:
                raise PluginError("sql_upsert: the sqlite engine writes a database file: name it in path")
            if is_ref(path) or path.strip().lower().startswith("file:"):
                raise PluginError("sql_upsert: path reads like a reference or a file: URI; a path is the database file's name")
        elif not isinstance(cfg.get("host"), str) or not cfg.get("host"):
            raise PluginError(f"sql_upsert: the {engine} engine needs a host")
        args = cfg.get("connect_args")
        if args is not None and not isinstance(args, Mapping):
            raise PluginError("sql_upsert: connect_args is an object of the driver's connect arguments")
        written = _written_credentials(args or {}, "connect_args")
        if written:
            raise PluginError(f"sql_upsert: {', '.join(written)} holds a credential written out: give it as a reference")
        t = cfg.get("timeout_seconds", 30)
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(float(t)) or t <= 0:
            raise PluginError(f"sql_upsert: timeout_seconds {t!r} is a number above 0")
        self._timeout = float(t)
        self._pool: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._conn: Any = None
        self._lock = asyncio.Lock()

    # ── the connection: one worker thread, every driver call on it ───────────────────────────────────────────────

    def _resolved(self, v: Any) -> Any:
        if isinstance(v, str) and is_ref(v):
            return self.ctx.secret(v)
        if isinstance(v, Mapping):
            return {str(k): self._resolved(x) for k, x in v.items()}
        if isinstance(v, list):
            return [self._resolved(x) for x in v]
        return v

    async def start(self) -> None:
        if self.ctx.dry_run or self._pool is not None:
            return
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="tp-sql-upsert")

    async def stop(self) -> None:
        pool, self._pool = self._pool, None
        if pool is not None:
            try:
                await asyncio.get_running_loop().run_in_executor(pool, self._close)
            finally:
                pool.shutdown(wait=True)

    def _close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - a connection that is already gone
                pass

    def _connect(self) -> Any:
        cfg, t, engine = self.config, self._timeout, self.engine
        try:
            c = {f: self._resolved(cfg.get(f)) for f in ("host", "database", "user", "password")}
            args = self._resolved(dict(cfg.get("connect_args") or {}))
        except Exception as e:  # noqa: BLE001 - a reference that does not resolve; its value is never in the message
            raise PluginError(f"sql_upsert: a reference in the connection does not resolve: {e}") from None
        port = cfg.get("port")
        if engine == "sqlite":
            import sqlite3
            return sqlite3.connect(str(cfg["path"]), timeout=t, isolation_level=None)   # transactions are ours
        if engine == "postgresql":
            import psycopg
            kw = {"host": c["host"], "port": port, "dbname": c["database"], "user": c["user"], "password": c["password"]}
            kw = {k: v for k, v in kw.items() if v not in (None, "")}
            kw.update(args)
            kw.setdefault("connect_timeout", max(2, int(math.ceil(t))))
            conn = psycopg.connect(autocommit=False, **kw)
            cur = conn.cursor()
            cur.execute("SELECT set_config('statement_timeout', %s, false)", (str(int(t * 1000)),))
            cur.close()
            conn.commit()
            return conn
        if engine == "mysql":
            import pymysql
            kw = {"host": c["host"], "port": int(port or 3306), "user": c["user"], "password": c["password"] or "",
                  "database": c["database"], "charset": "utf8mb4", "autocommit": False,
                  "connect_timeout": max(1, int(math.ceil(t))), "read_timeout": t, "write_timeout": t}
            kw = {k: v for k, v in kw.items() if v is not None}
            kw.update(args)
            return pymysql.connect(**kw)
        import pymssql
        tt = max(1, int(math.ceil(t)))
        kw = {"server": c["host"], "port": str(port or 1433), "user": c["user"], "password": c["password"],
              "database": c["database"], "login_timeout": tt, "timeout": tt, "autocommit": False}
        kw = {k: v for k, v in kw.items() if v not in (None, "")}
        kw.update(args)
        return pymssql.connect(**kw)

    def _conn_ready(self) -> Any:
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    async def _db(self, fn: Any, *args: Any) -> Any:
        if self._pool is None:                     # a sink used without start() (a contract test) gets its worker on first use
            self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="tp-sql-upsert")
        return await asyncio.get_running_loop().run_in_executor(self._pool, fn, *args)

    # ── the worker's steps ────────────────────────────────────────────────────────────────────────────────────

    def _begin_and_read(self, select: Optional[str], params: Sequence[Any]) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Open the transaction and, when asked, read the row the key holds now: (found, the row's columns as a dict)."""
        conn = self._conn_ready()
        if self.engine == "sqlite":
            conn.execute("BEGIN IMMEDIATE")
        if select is None:
            return False, None
        cur = conn.cursor()
        try:
            cur.execute(select, tuple(params))
            row = cur.fetchone()
            desc = list(cur.description or [])
            names = [d[0] for d in desc]
            json_cols = {d[0] for d in desc if self.engine == "postgresql" and getattr(d, "type_code", None) in _PG_JSON_OIDS}
        finally:
            cur.close()
        if row is None:
            return True, None
        return True, {n: (_JsonColumn(v) if n in json_cols else v) for n, v in zip(names, row)}

    def _write_commit(self, sql: str, params: Sequence[Any]) -> None:
        conn = self._conn_ready()
        cur = conn.cursor()
        try:
            cur.execute(sql, tuple(params))
        finally:
            cur.close()
        conn.commit()

    def _rollback(self) -> None:
        conn = self._conn
        if conn is None:
            return
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 - a connection that is gone: the next call connects again
            self._close()

    # ── what a driver's error becomes ─────────────────────────────────────────────────────────────────────────

    def _translated(self, e: BaseException, columns: Sequence[str]) -> Exception:
        if isinstance(e, (PluginError, Refused, Retry)):
            return e
        kind = classify_error(self.engine, e)
        what = type(e).__name__
        if kind == "retry":
            return Retry(f"{self.table_text}: the target did not take the record now ({what})")
        col = column_of(self.engine, e, list(columns) + self.keys)
        return Refused(f"{self.table_text}: the target refused the record ({what}"
                       + (f", column {col}" if col else "") + ")")

    # ── a record ──────────────────────────────────────────────────────────────────────────────────────────────

    def _plan(self, data: Mapping[str, Any]) -> Tuple[List[str], List[Any]]:
        names = sorted(str(k) for k in data)
        if self.allow is not None:
            names = [n for n in names if n in self.allow]
        for n in names:
            _name(n, "column")                       # a mapped field that is not a name this writer quotes is refused
        missing = [k for k in self.keys if k not in names or data.get(k) is None]
        if missing:
            raise Refused(f"sql_upsert: the record carries no value for the key column {', '.join(missing)}")
        return names, [data[k] for k in self.keys]

    async def deliver(self, event: Event, *, key: str, dry_run: bool) -> Outcome:
        data = dict(event.data)
        try:
            names, keyvals = self._plan(data)
        except PluginError as e:
            raise Refused(str(e)) from None
        if dry_run:
            return Outcome.dry(f"would upsert into {self.table_text} ({len(names)} columns)", table=self.table_text,
                               columns=names, key=list(self.keys), on_conflict=self.on_conflict)
        if await self.ctx.state.get(f"d:{key}") is not None:
            return Outcome.done(_canon(keyvals), "already written")
        sql = upsert_statement(self.engine, self.table, names, self.keys, self.on_conflict)
        params = [_param(data[n], self.engine) for n in names]
        h = _hash(keyvals)
        async with self._lock:
            need_pre = self.preimage and await self.ctx.state.get(f"pre:{h}") is None
            select = preimage_statement(self.engine, self.table, self.keys) if need_pre else None
            try:
                _, row = await self._db(self._begin_and_read, select, [_param(v, self.engine) for v in keyvals])
                if need_pre:
                    # The pre-migration row is in the state BEFORE the write commits: a stop between the two loses nothing.
                    # Append-only (a counter and one key per new pre-image, never a list rewritten as it grows), and in
                    # THIS order: the listing first, the entry last. `pre:<hash>` is what says "already kept", so it must
                    # be the last of the three to exist: a stop after pre_at leaves one listing with no entry (restore
                    # skips it, the retry writes it); a stop after pre_n lists the hash twice on the retry (restore applies
                    # the same pre-image twice, harmlessly); a stop before pre:<hash> never leaves a key that is "kept" but
                    # never listed, which a rollback would not restore.
                    n = int(await self.ctx.state.get(_PRE_N) or 0)
                    await self.ctx.state.set(f"pre_at:{n}", h)
                    await self.ctx.state.set(_PRE_N, n + 1)
                    await self.ctx.state.set(f"pre:{h}", {"key": [_kept(v) for v in keyvals], "row": None if row is None else
                                                          {k: _kept(v) for k, v in row.items()}})
                await self._db(self._write_commit, sql, params)
            except BaseException as e:
                try:
                    await self._db(self._rollback)
                except Exception:  # noqa: BLE001 - the original error is the one to report
                    pass
                if isinstance(e, Exception):
                    raise self._translated(e, names) from None
                raise
        await self.ctx.state.set(f"d:{key}", 1)
        return Outcome.done(_canon(keyvals), f"written to {self.table_text}")

    # ── the way back ──────────────────────────────────────────────────────────────────────────────────────────

    async def restore(self, *, newest_first: bool = True) -> int:
        """Put every kept pre-image back, newest first; a null one deletes the row. Returns how many it applied."""
        count = int(await self.ctx.state.get(_PRE_N) or 0)
        n = 0
        for i in (range(count - 1, -1, -1) if newest_first else range(count)):
            h = await self.ctx.state.get(f"pre_at:{i}")
            entry = await self.ctx.state.get(f"pre:{h}") if h else None
            if not entry:
                continue
            keyvals, row = entry["key"], entry.get("row")
            async with self._lock:
                try:
                    if row is None:
                        sql, params, cols = delete_statement(self.engine, self.table, self.keys), keyvals, self.keys
                    else:
                        cols = sorted(row)
                        for c in cols:
                            _name(c, "column")
                        sql = upsert_statement(self.engine, self.table, cols, self.keys, "update")
                        params = [_restored(row[c]) for c in cols]
                    await self._db(self._begin_and_read, None, [])
                    await self._db(self._write_commit, sql, params)
                except BaseException as e:
                    try:
                        await self._db(self._rollback)
                    except Exception:  # noqa: BLE001
                        pass
                    if isinstance(e, Exception):
                        raise self._translated(e, self.keys) from None
                    raise
            n += 1
        return n


class _RestoreContext:
    """What restore_preimages hands the sink: the state of the sink being undone and a way to resolve its references."""

    def __init__(self, state: Any, secret: Any) -> None:
        import logging
        self.state, self._secret = state, secret
        self.proxy_name, self.agent_did, self.registry_url, self.dry_run = "restore", "", "", False
        self.logger = logging.getLogger("theprotocol.proxy.restore")

    def secret(self, ref: str) -> str:
        if self._secret is None:
            raise PluginError(f"a reference ({ref}) in the sink's config needs restore_preimages(..., secret=spec.secret)")
        return self._secret(ref)


async def restore_preimages(state: Any, config: Mapping[str, Any], *, secret: Any = None, newest_first: bool = True) -> int:
    """Undo a migration's writes to one table: every pre-image the sink kept in `state`, put back (a null one deletes the
    row), newest first. `config` is the sink's config; `secret` resolves its references (spec.secret). Returns how many
    pre-images it applied. Running it again leaves the same rows."""
    sink = SqlUpsertSink(config, _RestoreContext(state, secret))
    await sink.start()
    try:
        return await sink.restore(newest_first=newest_first)
    finally:
        await sink.stop()
