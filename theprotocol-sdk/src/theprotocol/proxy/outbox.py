"""The durable outbox (SQLite, WAL) between a proxy's sources and its actions.

A record enters once: its exactly-once key is the primary key, so the same record read again (after a restart, a
replay from a source's point, a broker's redelivery) is ignored, and the source's cursor moves only after the row is on
disk. A row keeps the source's record as it came and what the mapping made of it (`mapped`, empty when the record could
not be mapped: such a row is dead from the start, and a replay maps it again with the spec as it is then). A row is
`pending` until its action or sink says `done`; a refusal moves it to `dead` with the other side's answer, a transient
failure leaves it pending with a later `next_at`. `tp-proxy replay` turns dead rows back to pending.
The same file keeps the plugins' small state (cursors) and the proxy's switches (pause, the breakers).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    key TEXT PRIMARY KEY,
    mapping TEXT NOT NULL,
    version INTEGER NOT NULL,
    source TEXT NOT NULL,
    record_id TEXT NOT NULL,
    action TEXT NOT NULL,
    record TEXT NOT NULL,
    mapped TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_at REAL NOT NULL,
    last_error TEXT,
    answer TEXT,
    outcome TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS outbox_due ON outbox(status, next_at);
CREATE TABLE IF NOT EXISTS state (scope TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(scope, key));
CREATE TABLE IF NOT EXISTS switches (name TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL);
"""


@dataclass(frozen=True)
class Row:
    key: str
    mapping: str
    version: int
    source: str
    record_id: str
    action: str
    record: Dict[str, Any]
    mapped: Optional[Dict[str, Any]]
    status: str
    attempts: int
    next_at: float
    last_error: Optional[str]
    answer: Any
    outcome: Any


class Outbox:
    """One SQLite file (or ":memory:" for a dry run, which keeps nothing)."""

    def __init__(self, path: str, *, readonly: bool = False):
        self.path = path
        self.readonly = readonly
        self._lock = threading.Lock()
        if readonly:
            # a dry run reads the real file's cursors and switches and never writes to it
            self._db = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, isolation_level=None,
                                       check_same_thread=False, timeout=30)
            return
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=30)
        if path != ":memory:":
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _x(self, sql: str, args: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, tuple(args))

    # ── records ───────────────────────────────────────────────────────────────────────────────────────────────────

    def enqueue(self, *, key: str, mapping: str, version: int, source: str, record_id: str, action: str,
                record: Dict[str, Any], mapped: Optional[Dict[str, Any]], error: Optional[str] = None,
                now: Optional[float] = None) -> bool:
        """Put a record in, with what its mapping made of it; False when its key is already there (sent, waiting or
        dead: never twice). With `error` (the mapping refused the record) the row is dead from the start."""
        t = time.time() if now is None else now
        status = "pending" if error is None else "dead"
        cur = self._x("INSERT OR IGNORE INTO outbox (key, mapping, version, source, record_id, action, record, mapped, "
                      "status, attempts, next_at, last_error, created_at, updated_at) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
                      (key, mapping, int(version), source, record_id, action, _dump(record),
                       None if mapped is None else _dump(mapped), status, t, error, t, t))
        return cur.rowcount == 1

    def set_mapped(self, key: str, mapped: Dict[str, Any]) -> None:
        """What a replay's fresh mapping made of a row that had none."""
        self._x("UPDATE outbox SET mapped = ?, updated_at = ? WHERE key = ?", (_dump(mapped), time.time(), key))

    def _row(self, r: tuple) -> Row:
        return Row(key=r[0], mapping=r[1], version=r[2], source=r[3], record_id=r[4], action=r[5],
                   record=json.loads(r[6]), mapped=json.loads(r[7]) if r[7] is not None else None, status=r[8],
                   attempts=r[9], next_at=r[10], last_error=r[11], answer=json.loads(r[12]) if r[12] else None,
                   outcome=json.loads(r[13]) if r[13] else None)

    _COLS = ("key, mapping, version, source, record_id, action, record, mapped, status, attempts, next_at, last_error, "
             "answer, outcome")

    def get(self, key: str) -> Optional[Row]:
        r = self._x(f"SELECT {self._COLS} FROM outbox WHERE key = ?", (key,)).fetchone()
        return self._row(r) if r else None

    def due(self, *, limit: int = 50, now: Optional[float] = None, skip_mappings: Iterable[str] = ()) -> List[Row]:
        t = time.time() if now is None else now
        skip = list(skip_mappings)
        sql = f"SELECT {self._COLS} FROM outbox WHERE status = 'pending' AND next_at <= ?"
        if skip:
            sql += f" AND mapping NOT IN ({','.join('?' for _ in skip)})"
        sql += " ORDER BY created_at, key LIMIT ?"
        return [self._row(r) for r in self._x(sql, [t, *skip, int(limit)]).fetchall()]

    def done(self, key: str, outcome: Dict[str, Any]) -> None:
        self._x("UPDATE outbox SET status = 'done', outcome = ?, last_error = NULL, attempts = attempts + 1, "
                "updated_at = ? WHERE key = ? AND status = 'pending'", (json.dumps(outcome, default=str), time.time(), key))

    def retry(self, key: str, error: str, *, after: float, now: Optional[float] = None) -> int:
        """Leave the row pending until `after` seconds from now; answers the attempts made so far."""
        now = time.time() if now is None else now
        self._x("UPDATE outbox SET attempts = attempts + 1, last_error = ?, next_at = ?, updated_at = ? "
                "WHERE key = ? AND status = 'pending'", (error[:2000], now + max(0.0, after), now, key))
        r = self._x("SELECT attempts FROM outbox WHERE key = ?", (key,)).fetchone()
        return int(r[0]) if r else 0

    def dead(self, key: str, error: str, answer: Any = None) -> None:
        self._x("UPDATE outbox SET status = 'dead', attempts = attempts + 1, last_error = ?, answer = ?, updated_at = ? "
                "WHERE key = ? AND status = 'pending'",
                (error[:2000], json.dumps(answer, default=str) if answer is not None else None, time.time(), key))

    def dead_letters(self, *, mapping: Optional[str] = None, limit: int = 1000) -> List[Row]:
        sql = f"SELECT {self._COLS} FROM outbox WHERE status = 'dead'"
        args: List[Any] = []
        if mapping:
            sql += " AND mapping = ?"
            args.append(mapping)
        sql += " ORDER BY updated_at LIMIT ?"
        args.append(int(limit))
        return [self._row(r) for r in self._x(sql, args).fetchall()]

    def replay(self, *, keys: Iterable[str] = (), mapping: Optional[str] = None) -> int:
        """Dead rows back to pending (these keys, a mapping's, or every one); answers how many."""
        keys = list(keys)
        now = time.time()
        sql = "UPDATE outbox SET status = 'pending', attempts = 0, next_at = ?, updated_at = ? WHERE status = 'dead'"
        args: List[Any] = [now, now]
        if keys:
            sql += f" AND key IN ({','.join('?' for _ in keys)})"
            args.extend(keys)
        if mapping:
            sql += " AND mapping = ?"
            args.append(mapping)
        return self._x(sql, args).rowcount

    def counts(self) -> Dict[str, int]:
        out = {"pending": 0, "done": 0, "dead": 0}
        for status, n in self._x("SELECT status, count(*) FROM outbox GROUP BY status").fetchall():
            out[status] = int(n)
        return out

    def counts_by_mapping(self) -> Dict[str, Dict[str, int]]:
        out: Dict[str, Dict[str, int]] = {}
        for mapping, status, n in self._x("SELECT mapping, status, count(*) FROM outbox GROUP BY mapping, status"):
            out.setdefault(mapping, {"pending": 0, "done": 0, "dead": 0})[status] = int(n)
        return out

    def last_done(self) -> Dict[str, float]:
        """Per mapping, when its last row was done (the epoch second)."""
        return {m: float(t) for m, t in self._x("SELECT mapping, max(updated_at) FROM outbox WHERE status = 'done' "
                                               "GROUP BY mapping").fetchall()}

    # ── plugin state and the proxy's switches ─────────────────────────────────────────────────────────────────────

    def state_get(self, scope: str, key: str, default: Any = None) -> Any:
        r = self._x("SELECT value FROM state WHERE scope = ? AND key = ?", (scope, key)).fetchone()
        return json.loads(r[0]) if r else default

    def state_set(self, scope: str, key: str, value: Any) -> None:
        self._x("INSERT INTO state (scope, key, value) VALUES (?, ?, ?) ON CONFLICT(scope, key) DO UPDATE SET "
                "value = excluded.value", (scope, key, json.dumps(value, default=str)))

    def switch(self, name: str, default: Any = None) -> Any:
        r = self._x("SELECT value FROM switches WHERE name = ?", (name,)).fetchone()
        return json.loads(r[0]) if r else default

    def set_switch(self, name: str, value: Any) -> None:
        if value is None:
            self._x("DELETE FROM switches WHERE name = ?", (name,))
            return
        self._x("INSERT INTO switches (name, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
                "value = excluded.value, updated_at = excluded.updated_at", (name, json.dumps(value), time.time()))

    def switches(self) -> Dict[str, Any]:
        return {n: json.loads(v) for n, v in self._x("SELECT name, value FROM switches").fetchall()}


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


class PluginState:
    """The StateStore a plugin gets: its own scope in the outbox file."""

    def __init__(self, outbox: Outbox, scope: str):
        self._o, self._scope = outbox, scope

    async def get(self, key: str, default: Any = None) -> Any:
        return self._o.state_get(self._scope, key, default)

    async def set(self, key: str, value: Any) -> None:
        self._o.state_set(self._scope, key, value)
