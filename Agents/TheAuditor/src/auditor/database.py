"""The Auditor — SQLite database layer (async via aiosqlite).

v2.1 — dual-delta model:
  * `delta` / `status`            = HTTP live-read (transient; in-flight outbox lag)
  * `atomic_delta` / `atomic_status` = direct-DB single-statement invariant (TRUTH)

The "effective" (truth) status used for breach tracking, uptime and the streak is
`COALESCE(atomic_status, status)`. Rows recorded during a maintenance window are
flagged (`maintenance=1`) and never open a breach incident nor ding uptime.
"""
import json
import aiosqlite
from datetime import datetime, timezone
from typing import Optional

from .config import DATA_DIR

DB_PATH = DATA_DIR / "auditor.db"

# §LIVESTATS (2026-09-15, agentvault2-b5 with agentvault2-85): the one rule for which rows count, in the two forms the code
# needs, side by side. A row counts as OK (uptime, the streak) when its truth status (atomic when present, else the live
# read) is OK or it was recorded inside a maintenance window; it is a breach (the last breach) when its truth status is
# BREACH outside one. get_stats asks the SQL form. Every row record_audit returns, the websocket row the page counts, carries
# the Python form as counts_ok and counts_breach (None on a public reading, which counts for nothing), so the page keeps no
# copy of the rule. The Python form compares maintenance
# the way SQL does (== 1, == 0), so a NULL counts in neither. tests/test_live_rows_carry_the_server_count_rule.py runs one
# fixture through both forms.
OK_SQL = "(COALESCE(atomic_status, status) = 'OK' OR maintenance = 1)"
BREACH_SQL = "(COALESCE(atomic_status, status) = 'BREACH' AND maintenance = 0)"


def counts_ok(status: Optional[str], atomic_status: Optional[str], maintenance) -> bool:
    return (atomic_status if atomic_status is not None else status) == "OK" or maintenance == 1


def counts_breach(status: Optional[str], atomic_status: Optional[str], maintenance) -> bool:
    return (atomic_status if atomic_status is not None else status) == "BREACH" and maintenance == 0


async def init_db() -> None:
    """Create tables if they don't exist, run migrations (idempotent)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        # §GLOBALSTD refinement (2026-08-22): WAL. In rollback-journal mode the
        # /metrics stats scan (COUNT over 733k rows) held a SHARED lock past the
        # 5s busy timeout and killed a WHOLE audit cycle on all three frames with
        # "database is locked" (2026-08-22 02:15:14, plus a public-API 500). WAL
        # makes readers and writers non-blocking; the mode is persistent in the
        # DB header, this is belt-and-braces for fresh deploys.
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS audit_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                tokens_issued REAL NOT NULL,
                total_circulating REAL NOT NULL,
                delta REAL NOT NULL,
                status TEXT NOT NULL,
                response_ms INTEGER NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS breaches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_at TEXT NOT NULL,
                delta REAL NOT NULL,
                resolved_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_history(timestamp DESC)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_breach_detected ON breaches(detected_at DESC)"
        )

        # ── §GLOBALSTD Phase 1 (2026-08-22): TPSA-1 attestation chain ────
        # `payload` holds the EXACT signed bytes (prev_hash is inside them, so
        # the chain itself is signed). Append-only by convention: nothing in
        # this codebase updates or deletes rows here — a rewrite breaks the
        # hash chain visibly, which is the point.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS attestations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                frame TEXT NOT NULL,
                ts TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                digest TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                signature TEXT NOT NULL,
                kid TEXT NOT NULL
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_att_frame ON attestations(frame, id DESC)"
        )

        # ── Migration: frame column (pre-v2.0) ──────────────────────────
        cursor = await db.execute("PRAGMA table_info(audit_history)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "frame" not in columns:
            await db.execute(
                "ALTER TABLE audit_history ADD COLUMN frame TEXT NOT NULL DEFAULT 'frame-a'"
            )
            await db.execute("ALTER TABLE audit_history ADD COLUMN extra_data TEXT")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_frame ON audit_history(frame)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_frame_ts ON audit_history(frame, timestamp DESC)"
            )

        # ── Migration: atomic-invariant columns (v2.1) ──────────────────
        cursor = await db.execute("PRAGMA table_info(audit_history)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "atomic_delta" not in columns:
            await db.execute("ALTER TABLE audit_history ADD COLUMN atomic_delta REAL")
            await db.execute("ALTER TABLE audit_history ADD COLUMN atomic_status TEXT")
            await db.execute(
                "ALTER TABLE audit_history ADD COLUMN maintenance INTEGER NOT NULL DEFAULT 0"
            )
            await db.execute("ALTER TABLE audit_history ADD COLUMN tokens_destroyed REAL")

        # ── Migration: a reading's source (§MTLSHOPS (a), 2026-09-15) ───
        # 'audit' is this auditor's own verdict (atomic, or the live read it mirrors); 'public' is a public-only slot's
        # reading of a frame's public supply audit, which never feeds the truth status, uptime, the streak or a supply
        # incident.
        cursor = await db.execute("PRAGMA table_info(audit_history)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "source" not in columns:
            await db.execute("ALTER TABLE audit_history ADD COLUMN source TEXT NOT NULL DEFAULT 'audit'")

        cursor = await db.execute("PRAGMA table_info(breaches)")
        bcolumns = [row[1] for row in await cursor.fetchall()]
        if "frame" not in bcolumns:
            await db.execute(
                "ALTER TABLE breaches ADD COLUMN frame TEXT NOT NULL DEFAULT 'frame-a'"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_breach_frame ON breaches(frame)"
            )

        # ── Migration: breach kind + detail (2026-06-04, FX solvency) ────
        # Distinguishes 'supply' (I1 Δ) incidents from 'solvency' (I2 reserve<floor)
        # incidents. `detail` stores the solvency snapshot JSON for the incident log.
        cursor = await db.execute("PRAGMA table_info(breaches)")
        bcolumns = [row[1] for row in await cursor.fetchall()]
        if "kind" not in bcolumns:
            await db.execute(
                "ALTER TABLE breaches ADD COLUMN kind TEXT NOT NULL DEFAULT 'supply'"
            )
            await db.execute("ALTER TABLE breaches ADD COLUMN detail TEXT")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_breach_kind ON breaches(kind)"
            )

        await db.commit()


# ── Meta key/value store ──────────────────────────────────────────────────

async def get_meta(key: str) -> Optional[dict]:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute("SELECT value FROM meta WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None


async def set_meta(key: str, value: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            "INSERT INTO meta (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, json.dumps(value), now),
        )
        await db.commit()


async def resolve_open_breaches(frame: Optional[str] = None) -> int:
    """Resolve (close) any currently-open breach incidents. Returns count closed."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(str(DB_PATH)) as db:
        if frame:
            cursor = await db.execute(
                "UPDATE breaches SET resolved_at = ? WHERE resolved_at IS NULL AND frame = ?",
                (now, frame),
            )
        else:
            cursor = await db.execute(
                "UPDATE breaches SET resolved_at = ? WHERE resolved_at IS NULL", (now,)
            )
        await db.commit()
        return cursor.rowcount


async def record_solvency_incident(
    frame: str, breached: bool, detail: Optional[dict] = None, maintenance: bool = False
) -> None:
    """Open/close a kind='solvency' incident for a frame's @fx_reserve. Mirrors the
    supply-breach semantics: opens ONE incident while the reserve is below floor
    (outside a maintenance window), resolves it when solvency returns. The `delta`
    column carries the headroom (negative = shortfall below floor); `detail` holds
    the solvency snapshot. Router residue is Δ-neutral and is NOT tracked here."""
    now = datetime.now(timezone.utc).isoformat()
    detail_json = json.dumps(detail) if detail else None
    async with aiosqlite.connect(str(DB_PATH)) as db:
        if not breached:
            await db.execute(
                "UPDATE breaches SET resolved_at = ? "
                "WHERE resolved_at IS NULL AND frame = ? AND kind = 'solvency'",
                (now, frame),
            )
        elif not maintenance:
            row = await db.execute(
                "SELECT id FROM breaches WHERE resolved_at IS NULL AND frame = ? "
                "AND kind = 'solvency' ORDER BY id DESC LIMIT 1",
                (frame,),
            )
            if not await row.fetchone():
                headroom = float((detail or {}).get("headroom", 0.0) or 0.0)
                await db.execute(
                    "INSERT INTO breaches (detected_at, delta, frame, kind, detail) "
                    "VALUES (?, ?, ?, 'solvency', ?)",
                    (now, headroom, frame, detail_json),
                )
        await db.commit()


async def record_escrow_incident(
    frame: str, breached: bool, detail: Optional[dict] = None, maintenance: bool = False
) -> None:
    """Open/close a kind='escrow' incident for a frame's AGORA escrow invariant (I-X3).
    Mirrors `record_solvency_incident`: opens ONE incident on a CONFIRMED escrow breach
    (the auditor's own TEG-actual-vs-registry-expected verdict, persisted on re-read and
    not explained by in-flight funding), outside a maintenance window; resolves it when
    I-X3 returns to OK. The `delta` column carries the confirmed escrow delta (actual −
    expected); `detail` holds the I-X3 snapshot. ERROR/absent cycles never reach here."""
    now = datetime.now(timezone.utc).isoformat()
    detail_json = json.dumps(detail) if detail else None
    async with aiosqlite.connect(str(DB_PATH)) as db:
        if not breached:
            await db.execute(
                "UPDATE breaches SET resolved_at = ? "
                "WHERE resolved_at IS NULL AND frame = ? AND kind = 'escrow'",
                (now, frame),
            )
        elif not maintenance:
            row = await db.execute(
                "SELECT id FROM breaches WHERE resolved_at IS NULL AND frame = ? "
                "AND kind = 'escrow' ORDER BY id DESC LIMIT 1",
                (frame,),
            )
            if not await row.fetchone():
                edelta = float((detail or {}).get("delta", 0.0) or 0.0)
                await db.execute(
                    "INSERT INTO breaches (detected_at, delta, frame, kind, detail) "
                    "VALUES (?, ?, ?, 'escrow', ?)",
                    (now, edelta, frame, detail_json),
                )
        await db.commit()


async def record_audit(
    tokens_issued: float,
    total_circulating: float,
    delta: float,
    status: str,
    response_ms: int,
    frame: str = "frame-a",
    extra_data: Optional[dict] = None,
    atomic_delta: Optional[float] = None,
    atomic_status: Optional[str] = None,
    maintenance: bool = False,
    tokens_destroyed: Optional[float] = None,
    source: str = "audit",
    public_breach_readings: int = 5,
) -> dict:
    """Record an audit result. Returns the inserted row as dict.

    `status`/`delta` are the HTTP live-read values (kept for continuity); breach
    tracking keys off the TRUTH status `COALESCE(atomic_status, status)`.
    """
    now = datetime.now(timezone.utc).isoformat()
    extra_json = json.dumps(extra_data) if extra_data else None
    truth_status = atomic_status or status
    truth_delta = atomic_delta if atomic_delta is not None else delta
    # The row stores maintenance as 1 or 0, and the counts it returns come from that stored value, so they agree with
    # OK_SQL and BREACH_SQL on the row (agentvault2-85: a maintenance of None stored 0 while the argument said neither).
    stored_maintenance = 1 if maintenance else 0

    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute(
            """INSERT INTO audit_history
               (timestamp, tokens_issued, total_circulating, delta, status, response_ms,
                frame, extra_data, atomic_delta, atomic_status, maintenance, tokens_destroyed, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now, tokens_issued, total_circulating, delta, status, response_ms,
                frame, extra_json, atomic_delta, atomic_status,
                stored_maintenance, tokens_destroyed, source,
            ),
        )
        row_id = cursor.lastrowid

        public_breach_streak = 0
        if source == "public":
            # §MTLSHOPS (a): a public reading is two queries and can show a transient BREACH under cross-frame load. It
            # opens a kind='public' incident only after `public_breach_readings` consecutive BREACH readings outside
            # maintenance, an OK reading resolves it, and it never touches the supply incidents below.
            if status == "BREACH" and not maintenance:
                cur = await db.execute(
                    "SELECT status, maintenance FROM audit_history WHERE frame = ? AND source = 'public' "
                    "ORDER BY id DESC LIMIT ?",
                    (frame, max(1, public_breach_readings)),
                )
                for st, mt in await cur.fetchall():
                    if st == "BREACH" and not mt:
                        public_breach_streak += 1
                    else:
                        break
                if public_breach_streak >= max(1, public_breach_readings):
                    row = await db.execute(
                        "SELECT id FROM breaches WHERE resolved_at IS NULL AND frame = ? AND kind = 'public' "
                        "ORDER BY id DESC LIMIT 1",
                        (frame,),
                    )
                    if not await row.fetchone():
                        await db.execute(
                            "INSERT INTO breaches (detected_at, delta, frame, kind, detail) VALUES (?, ?, ?, 'public', ?)",
                            (now, delta, frame, json.dumps({"readings": public_breach_streak,
                                                            "source": "the frame's public supply audit"})),
                        )
            elif status == "OK":
                await db.execute(
                    "UPDATE breaches SET resolved_at = ? WHERE resolved_at IS NULL AND frame = ? AND kind = 'public'",
                    (now, frame),
                )
        # ── Breach incident tracking (keyed on TRUTH status) ────────────
        elif truth_status == "OK":
            # Clearing condition: resolve this frame's open SUPPLY incident. Escrow, solvency and public incidents have
            # their own clearing conditions (record_escrow_incident, record_solvency_incident, the public branch above).
            # Closing them here on a healthy supply reading cut each long escrow breach on the legacy frames into
            # one-cycle incidents: 17,049 of them from 2026-06-28 to 08-27 (agentvault2-33, measured 2026-10-02).
            await db.execute(
                "UPDATE breaches SET resolved_at = ? WHERE resolved_at IS NULL AND frame = ? "
                "AND COALESCE(kind, 'supply') = 'supply'",
                (now, frame),
            )
        elif truth_status == "BREACH" and not maintenance:
            # Real breach outside a maintenance window → open a supply incident unless one is already open. An open
            # incident of ANOTHER kind is no reason to leave a supply breach unrecorded.
            row = await db.execute(
                "SELECT id FROM breaches WHERE resolved_at IS NULL AND frame = ? AND COALESCE(kind, 'supply') = 'supply' "
                "ORDER BY id DESC LIMIT 1",
                (frame,),
            )
            existing = await row.fetchone()
            if not existing:
                await db.execute(
                    "INSERT INTO breaches (detected_at, delta, frame) VALUES (?, ?, ?)",
                    (now, truth_delta, frame),
                )
        # maintenance BREACH / ERROR / UNKNOWN → record the row only, leave
        # the incident table untouched (safe-window semantics).

        await db.commit()

    return {
        "id": row_id,
        "timestamp": now,
        "tokens_issued": tokens_issued,
        "total_circulating": total_circulating,
        "delta": delta,
        "status": status,
        "response_ms": response_ms,
        "frame": frame,
        "extra_data": extra_data,
        "source": source,
        "public_breach_streak": public_breach_streak,
        "atomic_delta": atomic_delta,
        "atomic_status": atomic_status,
        "maintenance": maintenance,
        "tokens_destroyed": tokens_destroyed,
        # §MTLSHOPS (a) with §LIVESTATS: a public reading counts for nothing in the stats, so its row carries no answer
        # (None) and the page moves none of its stats for it.
        "counts_ok": None if source == "public" else counts_ok(status, atomic_status, stored_maintenance),
        "counts_breach": None if source == "public" else counts_breach(status, atomic_status, stored_maintenance),
    }


async def get_history(limit: int = 200, frame: Optional[str] = None) -> list[dict]:
    """Get recent audit history, optionally filtered by frame."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        if frame:
            cursor = await db.execute(
                "SELECT * FROM audit_history WHERE frame = ? ORDER BY id DESC LIMIT ?",
                (frame, limit),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM audit_history ORDER BY id DESC LIMIT ?", (limit,)
            )
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("extra_data"):
                try:
                    d["extra_data"] = json.loads(d["extra_data"])
                except (json.JSONDecodeError, TypeError):
                    pass
            if "maintenance" in d:
                d["maintenance"] = bool(d["maintenance"])
            results.append(d)
        return results


async def get_breaches(frame: Optional[str] = None, kind: Optional[str] = None) -> list[dict]:
    """Get breaches, optionally filtered by frame and/or kind ('supply'|'solvency')."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        clauses: list[str] = []
        params: list = []
        if frame:
            clauses.append("frame = ?")
            params.append(frame)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        cursor = await db.execute(
            f"SELECT * FROM breaches {where} ORDER BY id DESC LIMIT 100", tuple(params)
        )
        rows = await cursor.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if d.get("detail"):
                try:
                    d["detail"] = json.loads(d["detail"])
                except (json.JSONDecodeError, TypeError):
                    pass
            out.append(d)
        return out


async def get_stats(frame: Optional[str] = None, frames: Optional[list] = None) -> dict:
    """Get aggregate statistics, optionally filtered by a single `frame` or a list
    of `frames`. The list form mode-scopes the header/stat panel to one environment
    (prod vs sandbox) so the audit count, uptime and max-Δ match the frames shown.

    Uptime + the consecutive-OK streak key off the TRUTH status
    (`COALESCE(atomic_status, status)`), and treat maintenance-tagged rows as OK
    so deliberate, safe breaches during a maintenance window never ding the SLO.
    """
    # "Effective OK" predicate shared across queries: the module's rule (§LIVESTATS).
    OK = OK_SQL

    async with aiosqlite.connect(str(DB_PATH)) as db:
        # §MTLSHOPS (a) (2026-09-15): a public-only slot's readings never feed the audit count, the streak, the deltas or
        # the uptime. A scope that holds only such readings reports its uptime as not measured (None), never as 100.
        clauses = ["source != 'public'"]
        params_l: list = []
        if frames:
            _ph = ",".join("?" * len(frames))
            clauses.append(f"frame IN ({_ph})")
            params_l.extend(frames)
        elif frame:
            clauses.append("frame = ?")
            params_l.append(frame)
        where = "WHERE " + " AND ".join(clauses)
        params: tuple = tuple(params_l)

        cursor = await db.execute(
            f"SELECT COUNT(*) FROM audit_history {where}", params
        )
        total_audits = (await cursor.fetchone())[0]

        if total_audits == 0:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM audit_history " + where.replace("source != 'public'", "source = 'public'"), params
            )
            public_readings = (await cursor.fetchone())[0]
            return {
                "total_audits": 0,
                "consecutive_ok": 0,
                "last_breach": None,
                "avg_delta": 0.0,
                "max_delta": 0.0,
                "avg_atomic_delta": 0.0,
                "max_atomic_delta": 0.0,
                "uptime_pct": None if public_readings else 100.0,
                "public_readings": public_readings,
                "ok_audits": 0,
                "oldest_audit": None,
            }

        # Consecutive OK (truth-based) from the latest going back.
        cursor = await db.execute(
            f"SELECT status, atomic_status, maintenance FROM audit_history {where} ORDER BY id DESC",
            params,
        )
        consecutive_ok = 0
        async for row in cursor:
            if counts_ok(row[0], row[1], row[2]):
                consecutive_ok += 1
            else:
                break

        # Last breach (truth-based, excluding maintenance rows).
        cursor = await db.execute(
            f"SELECT timestamp FROM audit_history "
            f"{where + ' AND' if where else 'WHERE'} {BREACH_SQL} ORDER BY id DESC LIMIT 1",
            params,
        )
        last_breach_row = await cursor.fetchone()
        last_breach = last_breach_row[0] if last_breach_row else None

        # Live-read delta aggregates (the transient signal).
        cursor = await db.execute(
            f"SELECT AVG(ABS(delta)), MAX(ABS(delta)) FROM audit_history {where}", params
        )
        agg = await cursor.fetchone()
        avg_delta = agg[0] or 0.0
        max_delta = agg[1] or 0.0

        # Atomic delta aggregates (truth). Only over rows that have it.
        cursor = await db.execute(
            f"SELECT AVG(ABS(atomic_delta)), MAX(ABS(atomic_delta)) FROM audit_history "
            f"{where + ' AND' if where else 'WHERE'} atomic_delta IS NOT NULL",
            params,
        )
        aagg = await cursor.fetchone()
        avg_atomic_delta = aagg[0] or 0.0
        max_atomic_delta = aagg[1] or 0.0

        # Uptime (truth-based).
        cursor = await db.execute(
            f"SELECT COUNT(*) FROM audit_history "
            f"{where + ' AND' if where else 'WHERE'} {OK}",
            params,
        )
        ok_count = (await cursor.fetchone())[0]
        uptime_pct = round((ok_count / total_audits) * 100, 2) if total_audits > 0 else 100.0

        # Oldest audit.
        cursor = await db.execute(
            f"SELECT timestamp FROM audit_history {where} ORDER BY id ASC LIMIT 1", params
        )
        oldest_row = await cursor.fetchone()
        oldest_audit = oldest_row[0] if oldest_row else None

        return {
            "total_audits": total_audits,
            "consecutive_ok": consecutive_ok,
            "last_breach": last_breach,
            "avg_delta": round(avg_delta, 6),
            "max_delta": round(max_delta, 6),
            "avg_atomic_delta": round(avg_atomic_delta, 6),
            "max_atomic_delta": round(max_atomic_delta, 6),
            "uptime_pct": uptime_pct,
            "ok_audits": ok_count,
            "oldest_audit": oldest_audit,
        }


# ── §GLOBALSTD Phase 1 (2026-08-22): TPSA-1 attestations ────────────────────

_ATT_COLS = "id, frame, ts, kind, payload, digest, prev_hash, signature, kid"


def _att_row(row) -> dict:
    return dict(zip([c.strip() for c in _ATT_COLS.split(",")], row))


async def get_attestation_head(frame: str) -> Optional[str]:
    """Digest of the frame's latest attestation ('' semantics handled by caller)."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute(
            "SELECT digest FROM attestations WHERE frame = ? ORDER BY id DESC LIMIT 1",
            (frame,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def get_attestation_head_row(frame: str) -> Optional[dict]:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute(
            "SELECT id, frame, ts, kind, digest, kid FROM attestations "
            "WHERE frame = ? ORDER BY id DESC LIMIT 1",
            (frame,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return dict(zip(["id", "frame", "ts", "kind", "digest", "kid"], row))


async def record_attestation(
    frame: str, ts: str, kind: str, payload: str,
    digest: str, prev_hash: str, signature: str, kid: str,
) -> int:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute(
            "INSERT INTO attestations (frame, ts, kind, payload, digest, prev_hash, signature, kid) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (frame, ts, kind, payload, digest, prev_hash, signature, kid),
        )
        await db.commit()
        return cursor.lastrowid


async def get_attestations(
    frame: Optional[str] = None, limit: int = 50, before_id: Optional[int] = None,
) -> list:
    q = f"SELECT {_ATT_COLS} FROM attestations"
    where, params = [], []
    if frame:
        where.append("frame = ?"); params.append(frame)
    if before_id is not None:
        where.append("id < ?"); params.append(before_id)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 200)))
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute(q, params)
        return [_att_row(r) for r in await cursor.fetchall()]


async def get_attestation(att_id: int) -> Optional[dict]:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute(
            f"SELECT {_ATT_COLS} FROM attestations WHERE id = ?", (att_id,)
        )
        row = await cursor.fetchone()
        return _att_row(row) if row else None
