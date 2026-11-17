"""Reconcile: both sides read back and compared by key, without holding either in memory.

The source side is read by the mapping's own source, with a fresh state of its own (so it reads from the start) and
finishing after one pass: a sqlpoll source opens its own read-only connection, a file source reads its files. Each
record the mapping takes and maps gives (key, the mapped values of the paired target fields): the values compared are
AFTER the mapping (and its transforms). The target side is read from the writer's target: a SQL table (SELECT the key
and the fields, ORDER BY the key, through a read-only connection), a file_out folder (its csv and jsonl files), a REST
target only when the manifest names how to read it back (else the verdict is not_measured, exit 3).

Each side goes into a temporary SQLite file as (key text, row hash), and the two are merged in key order: missing (in
the source, not the target), extra (in the target, not the source), mismatched (both, different hashes). The checksum
of a side is the sha256 of its (key, row hash) lines in key order; the source's lines are also checksummed per batch of
batch_rows keys. Values are compared in one text form on both sides (null stays null; a boolean is 1 or 0; a number its
plain digits; a list or an object its canonical JSON; a date-time that names its zone, as a datetime or as ISO text with Z
or an offset, the same moment in UTC `...Z`), so the database's own types and its session's time zone do not make a
false mismatch (a timestamptz written as ...T13:22:00Z reads back as ...T14:22:00+01:00 on a server in Berlin).
"""
from __future__ import annotations

import csv
import decimal
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from ..mapping import _MISSING, apply, lookup, takes
from ..plugins import PluginError, Record, Refused, load
from ..spec import Spec, is_ref
from .schema import canonical, sha256_hex

FILE_SOURCES = ("filedrop", "sftp")


class NotMeasured(Exception):
    """The side could not be read: what was missing."""


_ZONED = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?(Z|[+-]\d{2}(:?\d{2})?)$")


def _utc(d: datetime) -> str:
    """A moment in UTC, `...Z`, microseconds only when it has some: the same text whichever zone it was read in."""
    u = d.astimezone(timezone.utc).replace(tzinfo=None)
    return u.isoformat(timespec="microseconds" if u.microsecond else "seconds") + "Z"


def _zoned(s: str) -> Optional[str]:
    """An ISO date-time WITH a zone (Z or an offset), as UTC; None for anything else (a naive time stays as written)."""
    if not _ZONED.match(s):
        return None
    t = s.replace(" ", "T", 1)
    t = t[:-1] + "+00:00" if t.endswith("Z") else t
    t = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", t)    # -0500 as -05:00: Python 3.10's fromisoformat takes only the colon form
    if re.search(r"[+-]\d{2}$", t):
        t += ":00"
    m = re.match(r"^(.*\.)(\d+)([+-].*)$", t)
    if m:                                           # more than 6 fraction digits: fromisoformat takes up to 6
        t = m.group(1) + (m.group(2) + "000000")[:6] + m.group(3)
    try:
        return _utc(datetime.fromisoformat(t))
    except ValueError:
        return None


def text(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime) and v.tzinfo is not None:
        return _utc(v)
    if isinstance(v, str):
        z = _zoned(v)
        if z is not None:
            return z
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isfinite(v) and v == int(v):
            return str(int(v))
        return repr(v)
    if isinstance(v, decimal.Decimal):
        if v.is_finite() and v == v.to_integral_value():
            return str(int(v))
        return format(v.normalize(), "f")
    if isinstance(v, (dict, list)):
        return canonical(v).decode("utf-8")
    return str(v)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float, decimal.Decimal)) and not isinstance(v, bool)


def as_number(v: Any) -> Any:
    """A source value paired with a numeric target column, as a number when it is one written as text ("12.50")."""
    if isinstance(v, str):
        try:
            d = decimal.Decimal(v.strip())
        except decimal.InvalidOperation:
            return v
        return d if d.is_finite() else v
    return v


def key_text(values: Sequence[Any]) -> str:
    return canonical([text(v) for v in values]).decode("utf-8")


def row_hash(k: str, values: Sequence[Any]) -> str:
    return sha256_hex(canonical([k, [text(v) for v in values]]))


class _Ctx:
    """The context a reconcile read hands a source: a fresh state in memory, the spec's secrets, no registry."""

    def __init__(self, spec: Spec, name: str):
        self.proxy_name, self.agent_did, self.registry_url, self.dry_run = spec.name, "", spec.registry, False
        self.logger = logging.getLogger(f"theprotocol.proxy.migrate.{name}")
        self._spec = spec
        self._mem: Dict[str, Any] = {}
        self.state = self

    async def get(self, key: str, default: Any = None) -> Any:
        return self._mem.get(key, default)

    async def set(self, key: str, value: Any) -> None:
        self._mem[key] = value

    def secret(self, ref: str) -> str:
        return self._spec.secret(ref)

    async def call(self, *a: Any, **k: Any) -> Any:
        raise PluginError("a reconcile read calls nothing")


def _row_of(source_type: str, config: Mapping[str, Any], rec: Record) -> Mapping[str, Any]:
    kind = config.get("stands_in_for") if source_type == "migrate_sample" else source_type
    p = rec.payload or {}
    if kind in FILE_SOURCES and isinstance(p, Mapping) and isinstance(p.get("data"), Mapping):
        return p["data"]
    return p


async def source_side(spec: Spec, mapping: str, keys: Sequence[str], targets: Sequence[str], *,
                      limit: Optional[int] = None) -> AsyncIterator[Tuple[List[Any], List[Any]]]:
    """(source key values, mapped target-field values) per record the mapping takes and maps; with `limit`, from the
    first `limit` records only (a dry run --limit N loaded the first N: its reconcile compares those)."""
    m = next((x for x in spec.mappings if x.name == mapping), None)
    if m is None:
        raise NotMeasured(f"the spec has no mapping {mapping!r}")
    ps = spec.sources[m.source]
    cfg = dict(ps.config)
    if ps.type in ("sqlpoll", "sftp", "filedrop"):
        cfg["poll_seconds"] = 0
    if ps.type == "sqlpoll":
        cfg["settle_seconds"] = 0
        cfg["from_start"] = True
    if ps.type == "webhook":
        raise NotMeasured(f"the source {m.source} is a webhook receiver: it cannot be read again")
    src = load("source", ps.type)(cfg, _Ctx(spec, m.source))
    await src.start()
    try:
        read = 0
        async for rec in src.records():
            if limit is not None and read >= limit:
                break
            read += 1
            rec = rec if rec.source else Record(record_id=rec.record_id, payload=rec.payload, source=m.source,
                                                observed_at=rec.observed_at, meta=rec.meta)
            try:
                if not takes(m.when, rec):
                    continue
                mapped = apply(m.fields, rec)
            except (Refused, ValueError, TypeError):
                continue
            row = _row_of(ps.type, ps.config, rec)
            kv = []
            for k in keys:
                v = row.get(k, _MISSING) if isinstance(row, Mapping) else _MISSING
                if v is _MISSING:
                    raise NotMeasured(f"the source's rows have no key field {k!r}")
                kv.append(v)
            yield kv, [mapped.get(t) for t in targets]
    finally:
        await src.stop()


# ── the target side ──────────────────────────────────────────────────────────────────────────────────────────────────

def _resolved(spec: Spec, v: Any) -> Any:
    if isinstance(v, str) and is_ref(v):
        return spec.secret(v)
    if isinstance(v, Mapping):
        return {str(k): _resolved(spec, x) for k, x in v.items()}
    return v


def sql_rows(spec: Spec, cfg: Mapping[str, Any], keys: Sequence[str], fields: Sequence[str]) -> Iterator[Dict[str, Any]]:
    """The target table's key and fields, ORDER BY the key, through a read-only connection (sqlpoll's dialects)."""
    from ..sources.sqlpoll import _DIALECTS, _json, _name
    engine = str(cfg.get("engine") or "")
    if engine not in _DIALECTS:
        raise NotMeasured(f"the target's engine {engine!r} is not one of {', '.join(_DIALECTS)}")
    d = _DIALECTS[engine]()
    try:
        import importlib
        importlib.import_module(d.module)
    except ImportError:
        raise NotMeasured(f"reading the {engine} target needs its driver, {d.module}") from None
    try:
        c = {f: _resolved(spec, cfg.get(f)) for f in ("host", "database", "user", "password")}
    except Exception:  # noqa: BLE001 - a reference that does not resolve; its value is never in the message
        raise NotMeasured("a reference in the target's connection does not resolve") from None
    c["args"] = _resolved(spec, dict(cfg.get("connect_args") or {}))
    c["path"], c["port"] = cfg.get("path"), cfg.get("port")
    c["timeout"] = float(cfg.get("timeout_seconds") or 30)
    if engine == "sqlite" and not (c["path"] and os.path.exists(str(c["path"]))):
        raise NotMeasured(f"the target database file {c['path']} does not exist")
    table = ".".join(d.quote(_name(p, "the table name part")) for p in str(cfg["table"]).split("."))
    cols = list(dict.fromkeys([*keys, *fields]))
    sql = (f"SELECT {', '.join(d.quote(_name(x, 'column')) for x in cols)} FROM {table} "
           f"ORDER BY {', '.join(d.quote(k) for k in keys)}")
    conn = d.connect(c)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        while True:
            batch = cur.fetchmany(1000)
            if not batch:
                break
            for r in batch:
                # a number stays a number (a numeric column compares by value: 12.5 is 12.50); the rest as sqlpoll
                # gives it (a date-time as ISO text with its zone, which text() reads in UTC)
                yield {col: (r[i] if _is_number(r[i]) else _json(r[i])) for i, col in enumerate(cols)}
    finally:
        conn.close()


def file_rows(cfg: Mapping[str, Any]) -> Iterator[Dict[str, Any]]:
    """The rows of a file_out folder (its csv and jsonl files; not manifest.json)."""
    d = Path(str(cfg["path"]))
    if not d.is_dir():
        raise NotMeasured(f"the target folder {d} does not exist")
    for p in sorted(d.rglob("*")):
        if not p.is_file() or p.name == "manifest.json" or p.name.endswith((".tmp", ".part")):
            continue
        if p.suffix == ".csv":
            with p.open(encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    yield {k: (None if v == "" else v) for k, v in r.items()}
        elif p.suffix == ".jsonl":
            with p.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        doc = json.loads(line)
                        if isinstance(doc, dict):
                            yield doc


def requests_rows(path: Path) -> Iterator[Dict[str, Any]]:
    """A scratch rest target: the bodies it would have sent (requests.jsonl)."""
    if not path.is_file():
        raise NotMeasured(f"the scratch requests file {path} does not exist")
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                doc = json.loads(line)
                body = doc.get("body") if isinstance(doc, dict) else None
                if isinstance(body, dict):
                    yield body


def rest_rows(spec: Spec, read: Mapping[str, Any]) -> Iterator[Dict[str, Any]]:
    import httpx
    headers = {k: _resolved(spec, v) for k, v in (read.get("headers") or {}).items()}
    try:
        r = httpx.get(str(read["url"]), headers=headers, timeout=60.0, follow_redirects=False)
    except httpx.HTTPError as e:
        raise NotMeasured(f"the read-back GET failed: {type(e).__name__}") from None
    if r.status_code != 200:
        raise NotMeasured(f"the read-back GET answered HTTP {r.status_code}")
    try:
        doc = r.json()
    except ValueError:
        raise NotMeasured("the read-back GET did not answer JSON") from None
    items = lookup(doc, read["items_path"]) if read.get("items_path") else doc
    if not isinstance(items, list):
        raise NotMeasured("the read-back answer holds no list of items")
    for it in items:
        if isinstance(it, dict):
            yield it


# ── the merge ────────────────────────────────────────────────────────────────────────────────────────────────────────

async def compare(spec: Spec, entry: Mapping[str, Any], target_rows: Iterator[Dict[str, Any]], *, batch_rows: int,
                  workdir: Optional[Path] = None, limit: Optional[int] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """(the reconcile result of one manifest entry, the source's batch checksums)."""
    pairs: Mapping[str, str] = entry["pairs"]
    tfields = list(pairs.values())
    skeys, tkeys = list(entry["source"]["key"]), list(entry["target"]["key"])
    fd, tmp = tempfile.mkstemp(prefix="reconcile-", suffix=".sqlite", dir=str(workdir) if workdir else None)
    os.close(fd)
    db = sqlite3.connect(tmp)
    try:
        db.execute("CREATE TABLE s (k TEXT PRIMARY KEY, h TEXT NOT NULL)")
        db.execute("CREATE TABLE t (k TEXT PRIMARY KEY, h TEXT NOT NULL)")
        dup_s = dup_t = 0
        # the target first: which of its paired fields (and keys) come back as numbers decides which source values
        # are compared by value; a text column stays text ("12.50" and "12.5" are different texts)
        num_f: set = set()
        num_k: set = set()
        for row in target_rows:
            kv = []
            for i, c in enumerate(tkeys):
                if c not in row:
                    raise NotMeasured(f"the target's rows have no key field {c!r}")
                kv.append(row[c])
                if _is_number(row[c]):
                    num_k.add(i)
            for f in tfields:
                if _is_number(row.get(f)):
                    num_f.add(f)
            k = key_text(kv)
            cur = db.execute("INSERT OR IGNORE INTO t VALUES (?, ?)", (k, row_hash(k, [row.get(f) for f in tfields])))
            dup_t += 1 - cur.rowcount
        async for kv, vals in source_side(spec, entry["mapping"], skeys, tfields, limit=limit):
            kv = [as_number(v) if i in num_k else v for i, v in enumerate(kv)]
            vals = [as_number(v) if f in num_f else v for f, v in zip(tfields, vals)]
            k = key_text(kv)
            cur = db.execute("INSERT OR IGNORE INTO s VALUES (?, ?)", (k, row_hash(k, vals)))
            dup_s += 1 - cur.rowcount
        db.commit()
        out = {"source": 0, "target": 0, "missing": 0, "extra": 0, "mismatched": 0}
        hs, ht = hashlib.sha256(), hashlib.sha256()
        batches: List[Dict[str, Any]] = []
        bh, bn = hashlib.sha256(), 0
        a = db.execute("SELECT k, h FROM s ORDER BY k")
        b = db.cursor().execute("SELECT k, h FROM t ORDER BY k")
        x, y = a.fetchone(), b.fetchone()
        while x is not None or y is not None:
            if y is None or (x is not None and x[0] < y[0]):
                out["missing"] += 1
                step_s, step_t = True, False
            elif x is None or y[0] < x[0]:
                out["extra"] += 1
                step_s, step_t = False, True
            else:
                if x[1] != y[1]:
                    out["mismatched"] += 1
                step_s = step_t = True
            if step_s:
                line = f"{x[0]}\t{x[1]}\n".encode("utf-8")
                hs.update(line)
                bh.update(line)
                bn += 1
                out["source"] += 1
                if bn >= batch_rows:
                    batches.append({"n": len(batches) + 1, "count": bn, "sha256": bh.hexdigest()})
                    bh, bn = hashlib.sha256(), 0
                x = a.fetchone()
            if step_t:
                ht.update(f"{y[0]}\t{y[1]}\n".encode("utf-8"))
                out["target"] += 1
                y = b.fetchone()
        if bn:
            batches.append({"n": len(batches) + 1, "count": bn, "sha256": bh.hexdigest()})
        out["checksum_source"], out["checksum_target"] = hs.hexdigest(), ht.hexdigest()
        why = []
        if dup_s:
            why.append(f"{dup_s} source rows repeat a key")
        if dup_t:
            why.append(f"{dup_t} target rows repeat a key")
        ok = out["missing"] == out["extra"] == out["mismatched"] == 0 and not dup_s and not dup_t
        out["verdict"] = "pass" if ok else "fail"
        out["why"] = "; ".join(why)
        return out, batches
    finally:
        db.close()
        try:
            os.unlink(tmp)
        except OSError:
            pass


def not_measured(why: str) -> Dict[str, Any]:
    return {"source": None, "target": None, "missing": None, "extra": None, "mismatched": None,
            "checksum_source": None, "checksum_target": None, "verdict": "not_measured", "why": why}
