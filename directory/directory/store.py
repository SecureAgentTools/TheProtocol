"""SQLite store for the Directory trial. One writer (the ingest loop), many readers (GraphQL)."""
from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional


log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS registries (
  name TEXT PRIMARY KEY, trust_domain TEXT, tier TEXT, public_url TEXT, did_namespace TEXT,
  verified INTEGER NOT NULL DEFAULT 0, reason TEXT, reachable INTEGER NOT NULL DEFAULT 0, card_epoch TEXT,
  location TEXT, latitude REAL, longitude REAL, parent_name TEXT, federation_status TEXT, hop INTEGER,
  last_sync_at REAL, last_error TEXT, agents_indexed INTEGER NOT NULL DEFAULT 0, card_json TEXT,
  -- §DIRFEED: the cursor this Directory has walked to on that registry's card feed, whether the registry
  -- answers the feed at all, and when it was last read in FULL (the pass that can see a card go away).
  cards_cursor TEXT, feed_supported INTEGER NOT NULL DEFAULT 0, last_full_at REAL, listings_indexed INTEGER NOT NULL DEFAULT 0,
  -- §DISCPANEL: how deep THIS Directory walks from that source (its own override, else the global default)
  hop_depth INTEGER,
  -- §DISCMIX: the registry's settlement currency, off its own signed card — an index row has to know which
  -- unit its home settles in, or a console cannot say whether reaching it costs an FX hop.
  currency TEXT,
  -- §MEMBERSHIP phase C: the registry board's two public reads (board.py): the state of the LAST read, the figures
  -- of the last good one and when, when it was last checked, and the last error verbatim
  membership_state TEXT, membership_json TEXT, membership_at REAL, membership_checked_at REAL, membership_error TEXT,
  commons_state TEXT, commons_json TEXT, commons_at REAL, commons_checked_at REAL, commons_error TEXT
);
CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY, did TEXT, name TEXT, hri TEXT, description TEXT, is_active INTEGER,
  updated_at TEXT, source TEXT, source_td TEXT, issuer TEXT, shape TEXT, home TEXT,
  bond_json TEXT, enforcement_json TEXT, verified INTEGER NOT NULL DEFAULT 0, reachable INTEGER NOT NULL DEFAULT 1,
  fetched_at REAL, card_json TEXT
);
CREATE INDEX IF NOT EXISTS agents_source ON agents(source);
CREATE INDEX IF NOT EXISTS agents_issuer ON agents(issuer);
CREATE TABLE IF NOT EXISTS listings (
  id TEXT PRIMARY KEY, listing_id TEXT, source TEXT, symbol TEXT, display_name TEXT, currency TEXT,
  status TEXT, approved INTEGER, ipo_price TEXT, last_price TEXT, best_bid TEXT, best_ask TEXT,
  volume_24h TEXT, trades_24h INTEGER, organization_id TEXT, treasury_agent_did TEXT,
  reachable INTEGER NOT NULL DEFAULT 1, fetched_at REAL, listing_json TEXT
);
CREATE INDEX IF NOT EXISTS listings_source ON listings(source);
CREATE INDEX IF NOT EXISTS listings_symbol ON listings(symbol);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

# columns added after the first trial DB was written — an index that cannot migrate is an index you delete,
# which is exactly the thing the re-read switch exists to avoid.
_ADDED = {
    "registries": {"cards_cursor": "TEXT", "feed_supported": "INTEGER NOT NULL DEFAULT 0",
                   "last_full_at": "REAL", "listings_indexed": "INTEGER NOT NULL DEFAULT 0",
                   "hop_depth": "INTEGER", "currency": "TEXT",
                   "membership_state": "TEXT", "membership_json": "TEXT", "membership_at": "REAL",
                   "membership_checked_at": "REAL", "membership_error": "TEXT",
                   "commons_state": "TEXT", "commons_json": "TEXT", "commons_at": "REAL",
                   "commons_checked_at": "REAL", "commons_error": "TEXT"},
}


class Store:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)
            for table, cols in _ADDED.items():
                have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
                for col, decl in cols.items():
                    if col not in have:
                        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    @contextlib.contextmanager
    def _conn(self):
        """One connection per call, COMMITTED and then CLOSED.

        ⚠ `with sqlite3.connect(...) as c:` COMMITS OR ROLLS BACK. IT DOES NOT
        CLOSE. Every one of this class's 17 call sites is written
        `with self._conn() as c:`, which read as connection management and was
        transaction management — so each call leaked a file descriptor for the
        life of the process.

        MEASURED 2026-09-06 23:3xZ on the sandbox Directory: 1024 open fds
        against a limit of 1024, **1011 of them `directory.db`**, and every
        ingest cycle since 21:52 failing with `sqlite3.OperationalError: unable
        to open database file` — which is what SQLite says when it cannot get a
        handle, not what it says when a file is missing. The file was present,
        writable and owned correctly the whole time; a `docker exec` write test
        passed while the app could not connect, because the exec had its own
        fds. The peer Directory on the same image was at 147/1024 with 132
        `directory.db` — leaking identically, just slower, because it indexes
        100 cards where this tier holds 5,500.

        Yielding from a contextmanager keeps every call site unchanged and adds
        the `close()` that was missing; the inner `with c:` preserves the
        commit/rollback the callers rely on.
        """
        c = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        try:
            with c:
                yield c
        finally:
            c.close()

    # ── writes (ingest) ──────────────────────────────────────────────────────
    def upsert_registry(self, **r: Any) -> None:
        cols = ["name", "trust_domain", "tier", "public_url", "did_namespace", "verified", "reason", "reachable", "card_epoch",
                "location", "latitude", "longitude", "parent_name", "federation_status", "hop", "last_sync_at", "last_error",
                "agents_indexed", "card_json", "currency"]  # the feed columns move through set_registry_field, never through the card sync
        vals = [r.get(k) for k in cols]
        with self.lock, self._conn() as c:
            c.execute(f"INSERT INTO registries ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
                      f"ON CONFLICT(name) DO UPDATE SET " + ",".join(f"{k}=excluded.{k}" for k in cols[1:]), vals)

    def set_registry_field(self, name: str, **fields: Any) -> None:
        with self.lock, self._conn() as c:
            for k, v in fields.items():
                c.execute(f"UPDATE registries SET {k}=? WHERE name=?", (v, name))

    def upsert_agent(self, **a: Any) -> None:
        cols = ["id", "did", "name", "hri", "description", "is_active", "updated_at", "source", "source_td", "issuer", "shape",
                "home", "bond_json", "enforcement_json", "verified", "reachable", "fetched_at", "card_json"]
        vals = [a.get(k) for k in cols]
        with self.lock, self._conn() as c:
            c.execute(f"INSERT INTO agents ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
                      f"ON CONFLICT(id) DO UPDATE SET " + ",".join(f"{k}=excluded.{k}" for k in cols[1:]), vals)

    def agent_epoch(self, agent_id: str) -> Optional[str]:
        with self._conn() as c:
            row = c.execute("SELECT updated_at FROM agents WHERE id=?", (agent_id,)).fetchone()
            return row["updated_at"] if row else None

    def set_meta(self, key: str, value: Any) -> None:
        with self.lock, self._conn() as c:
            c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self._conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return json.loads(row["value"]) if row else default

    def upsert_listing(self, **l: Any) -> None:
        cols = ["id", "listing_id", "source", "symbol", "display_name", "currency", "status", "approved", "ipo_price",
                "last_price", "best_bid", "best_ask", "volume_24h", "trades_24h", "organization_id",
                "treasury_agent_did", "reachable", "fetched_at", "listing_json"]
        vals = [l.get(k) for k in cols]
        with self.lock, self._conn() as c:
            c.execute(f"INSERT INTO listings ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
                      f"ON CONFLICT(id) DO UPDATE SET " + ",".join(f"{k}=excluded.{k}" for k in cols[1:]), vals)

    def sweep_source(self, table: str, source: str, seen_ids: List[str]) -> int:
        """A FULL pass is the only pass that can see something GO AWAY. Rows this source no longer publishes are
        marked unreachable, never deleted (his answer 3: outside the federation you stay discoverable, not
        interactable — and a deletion here would erase the only record that the thing ever existed).

        §DIRPAGE (2026-09-09) adds the OTHER HALF: a row this source still publishes is marked
        reachable AGAIN. Without it a row swept by mistake could never come back — the incremental
        walk skips a card whose epoch is unchanged (that is the whole point of the feed), so it is
        never re-upserted and its `reachable=0` is permanent. Measured on the sandbox Directory the
        day this was found: the store held 5,471 Sandbox Alpha rows and reported 5,000, because a
        truncated full pass had swept 471 LIVE agents and nothing could undo it.

        The seen set goes through a TEMP TABLE rather than a `?`-per-id `IN (...)`: at 5,471 ids the
        old form was already near SQLite's host-parameter ceiling, and the point of the walk is that
        a source may be arbitrarily large.
        """
        assert table in ("agents", "listings")
        with self.lock, self._conn() as c:
            c.execute("CREATE TEMP TABLE IF NOT EXISTS _seen (id TEXT PRIMARY KEY)")
            c.execute("DELETE FROM _seen")
            if seen_ids:
                c.executemany("INSERT OR IGNORE INTO _seen(id) VALUES (?)", [(str(i),) for i in seen_ids])
            gone = c.execute(
                f"UPDATE {table} SET reachable=0 WHERE source=? AND reachable=1 AND id NOT IN (SELECT id FROM _seen)",
                (source,)).rowcount or 0
            restored = c.execute(
                f"UPDATE {table} SET reachable=1 WHERE source=? AND reachable=0 AND id IN (SELECT id FROM _seen)",
                (source,)).rowcount or 0
            if restored:
                log.info("sweep_source(%s, %s): restored %d row(s) a previous partial pass had marked unreachable",
                         table, source, restored)
            return gone

    def count_for_source(self, table: str, source: str, reachable_only: bool = True) -> int:
        assert table in ("agents", "listings")
        q = f"SELECT count(*) FROM {table} WHERE source=?" + (" AND reachable=1" if reachable_only else "")
        with self._conn() as c:
            return c.execute(q, (source,)).fetchone()[0]

    # ── reads (GraphQL) ──────────────────────────────────────────────────────
    def list_registries(self) -> List[Dict[str, Any]]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM registries ORDER BY hop, name")]

    def get_registry(self, name: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM registries WHERE lower(name)=lower(?)", (name,)).fetchone()
            return dict(row) if row else None

    def registry_by_trust_domain(self, td: str, tier_prefix: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            q = "SELECT * FROM registries WHERE lower(trust_domain)=lower(?)"
            rows = [dict(r) for r in c.execute(q, (td,))]
        if tier_prefix:
            rows = [r for r in rows if (r.get("tier") or "").startswith(tier_prefix)] or rows
        return rows[0] if rows else None

    def list_agents(self, *, first: int = 50, after: Optional[str] = None, issuer: Optional[str] = None,
                    name_contains: Optional[str] = None, bonded_only: bool = False, source: Optional[str] = None,
                    include_gone: bool = False) -> Dict[str, Any]:
        """The page the public surface asks for is the LIVE set. §DARKSYNC (2026-09-22): `include_gone` is kept for a
        future admin or CLI reader and is passed by NO public caller — the GraphQL `agents` field no longer takes it,
        because a gone row is indistinguishable from a card its home took dark on purpose."""
        where, args = ["1=1"], []
        if after: where.append("id > ?"); args.append(after)
        if issuer: where.append("issuer = ?"); args.append(issuer)
        if name_contains: where.append("lower(name) LIKE ?"); args.append(f"%{name_contains.lower()}%")
        if source: where.append("lower(source) = lower(?)"); args.append(source)
        if bonded_only: where.append("json_extract(bond_json, '$.is_bonded') = 1")
        if not include_gone: where.append("reachable = 1")
        with self._conn() as c:
            total = c.execute(f"SELECT count(*) FROM agents WHERE {' AND '.join(where[1:] or ['1=1'])}", args[0 if not after else 1:]).fetchone()[0] if not after else None
            rows = [dict(r) for r in c.execute(f"SELECT * FROM agents WHERE {' AND '.join(where)} ORDER BY id LIMIT ?", args + [first + 1])]
        has_next = len(rows) > first
        rows = rows[:first]
        return {"rows": rows, "end_cursor": rows[-1]["id"] if rows else None, "has_next_page": has_next, "total": total}

    def get_agent(self, did: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM agents WHERE did=? OR id=?", (did, did)).fetchone()
            return dict(row) if row else None

    def list_listings(self, *, first: int = 50, after: Optional[str] = None, source: Optional[str] = None,
                      symbol: Optional[str] = None, trading_only: bool = False) -> Dict[str, Any]:
        where, args = ["1=1"], []
        if after: where.append("id > ?"); args.append(after)
        if source: where.append("lower(source) = lower(?)"); args.append(source)
        if symbol: where.append("upper(symbol) = upper(?)"); args.append(symbol)
        if trading_only: where.append("status = 'trading' AND reachable = 1")
        with self._conn() as c:
            total = c.execute(f"SELECT count(*) FROM listings WHERE {' AND '.join(where[1:] or ['1=1'])}",
                              args[0 if not after else 1:]).fetchone()[0] if not after else None
            rows = [dict(r) for r in c.execute(f"SELECT * FROM listings WHERE {' AND '.join(where)} ORDER BY id LIMIT ?", args + [first + 1])]
        has_next = len(rows) > first
        rows = rows[:first]
        return {"rows": rows, "end_cursor": rows[-1]["id"] if rows else None, "has_next_page": has_next, "total": total}

    def counts(self) -> Dict[str, int]:
        with self._conn() as c:
            return {"agents": c.execute("SELECT count(*) FROM agents WHERE reachable=1").fetchone()[0],
                    "agents_including_gone": c.execute("SELECT count(*) FROM agents").fetchone()[0],
                    "listings": c.execute("SELECT count(*) FROM listings WHERE reachable=1").fetchone()[0],
                    "registries": c.execute("SELECT count(*) FROM registries").fetchone()[0],
                    "registries_verified": c.execute("SELECT count(*) FROM registries WHERE verified=1").fetchone()[0],
                    "agents_by_source": {r["source"]: r["n"] for r in c.execute("SELECT source, count(*) n FROM agents WHERE reachable=1 GROUP BY source")}}


def now() -> float:
    return time.time()
